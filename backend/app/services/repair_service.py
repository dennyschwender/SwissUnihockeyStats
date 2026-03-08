"""
Conservative DB repair service.

Fixes persistent failures that the normal scheduler cannot self-heal:
  - Stuck in_progress sync_status rows (crashed workers)
  - Games with null game_date (forces re-index via sync_status delete)
  - Finished scored games with zero events (forces re-index)
  - Games with null period where OT/SO can be inferred from events
  - Stale failed sync_status rows blocking retries

Also provides read-only report queries for the admin dashboard.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from app.models.db_models import SyncStatus

logger = logging.getLogger(__name__)

# How old an in_progress row must be before we reset it
_STUCK_THRESHOLD_HOURS = 2
# How old a failed row must be before we clear it for retry
_STALE_FAILED_DAYS = 7


class RepairService:
    def __init__(self, db_service):
        self.db_service = db_service

    # ── Conservative repairs ───────────────────────────────────────────────

    def fix_stuck_in_progress(self) -> int:
        """Delete in_progress sync_status rows older than 2h.

        Crashed workers leave rows locked; deleting them lets the scheduler
        re-queue the work on the next tick.
        Returns number of rows deleted.
        """
        cutoff = datetime.utcnow() - timedelta(hours=_STUCK_THRESHOLD_HOURS)
        with self.db_service.session_scope() as session:
            n = session.execute(text("""
                DELETE FROM sync_status
                WHERE sync_status = 'in_progress'
                  AND last_sync < :cutoff
            """), {"cutoff": cutoff}).rowcount
        if n:
            logger.info("[repair] reset %d stuck in_progress rows", n)
        return n

    def fix_null_game_dates(self) -> int:
        """Delete game_events sync_status for finished games with null game_date.

        The event indexer backfills game_date from the game_details API when
        it runs. Deleting the sync_status row forces a re-run.
        Returns number of sync_status rows deleted.
        """
        with self.db_service.session_scope() as session:
            n = session.execute(text("""
                DELETE FROM sync_status
                WHERE entity_type = 'game_events'
                  AND entity_id IN (
                      SELECT 'game:' || g.id || CHAR(58) || 'events'
                      FROM games g
                      WHERE g.game_date IS NULL
                        AND g.status = 'finished'
                        AND g.home_score IS NOT NULL
                  )
            """)).rowcount
        if n:
            logger.info("[repair] queued %d null-game_date games for re-index", n)
        return n

    def fix_missing_events(self) -> int:
        """Delete game_events sync_status for finished scored games with 0 events.

        These games were marked completed but the API returned no events.
        Deleting the sync_status row forces the scheduler to retry them.
        Returns number of sync_status rows deleted.
        """
        with self.db_service.session_scope() as session:
            n = session.execute(text("""
                DELETE FROM sync_status
                WHERE entity_type = 'game_events'
                  AND entity_id IN (
                      SELECT 'game:' || g.id || CHAR(58) || 'events'
                      FROM games g
                      WHERE g.status = 'finished'
                        AND g.home_score IS NOT NULL
                        AND NOT EXISTS (
                            SELECT 1 FROM game_events ge WHERE ge.game_id = g.id
                        )
                  )
            """)).rowcount
        if n:
            logger.info("[repair] queued %d no-events games for re-index", n)
        return n

    def fix_null_period_from_events(self) -> int:
        """Set period='OT' or 'SO' from existing event rows for finished games.

        OT: a goal event at time >= 61:00 exists.
        SO: a Penaltyschiessen event exists (takes priority over OT).
        Returns total number of games updated.
        """
        with self.db_service.session_scope() as session:
            ot = session.execute(text("""
                UPDATE games
                SET period = 'OT'
                WHERE status = 'finished'
                  AND period IS NULL
                  AND home_score IS NOT NULL
                  AND id IN (
                      SELECT DISTINCT game_id FROM game_events
                      WHERE time >= '61:00'
                        AND event_type LIKE 'Torschütze%'
                  )
            """)).rowcount
            so = session.execute(text("""
                UPDATE games
                SET period = 'SO'
                WHERE status = 'finished'
                  AND period IS NULL
                  AND home_score IS NOT NULL
                  AND id IN (
                      SELECT DISTINCT game_id FROM game_events
                      WHERE event_type LIKE 'Penaltyschiessen%'
                  )
            """)).rowcount
        total = ot + so
        if total:
            logger.info("[repair] set period for %d games (OT=%d SO=%d)", total, ot, so)
        return total

    def fix_stale_failed_rows(self) -> int:
        """Delete failed game_events sync_status rows older than 7 days.

        Failed rows block the scheduler from retrying for max_age (up to 720h).
        Deleting them lets the scheduler queue a fresh attempt.
        Returns number of rows deleted.
        """
        cutoff = datetime.utcnow() - timedelta(days=_STALE_FAILED_DAYS)
        with self.db_service.session_scope() as session:
            n = session.execute(text("""
                DELETE FROM sync_status
                WHERE entity_type = 'game_events'
                  AND sync_status = 'failed'
                  AND last_sync < :cutoff
            """), {"cutoff": cutoff}).rowcount
        if n:
            logger.info("[repair] cleared %d stale failed rows", n)
        return n

    # ── Report queries (read-only) ─────────────────────────────────────────

    def report_games_no_lineup(self) -> list[dict]:
        """Finished games that have events but zero game_players rows.

        These games were indexed for events but the lineup was never captured.
        Returned as list of dicts with keys: game_id, game_date, season_id,
        home_team_id, away_team_id, event_count.
        """
        with self.db_service.session_scope() as session:
            rows = session.execute(text("""
                SELECT g.id, g.game_date, g.season_id,
                       g.home_team_id, g.away_team_id,
                       COUNT(ge.id) AS event_count
                FROM games g
                JOIN game_events ge ON ge.game_id = g.id
                WHERE g.status = 'finished'
                  AND g.home_score IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM game_players gp WHERE gp.game_id = g.id
                  )
                GROUP BY g.id
                ORDER BY g.game_date DESC
                LIMIT 200
            """)).fetchall()
        return [
            {
                "game_id": r[0],
                "game_date": str(r[1]) if r[1] else None,
                "season_id": r[2],
                "home_team_id": r[3],
                "away_team_id": r[4],
                "event_count": r[5],
            }
            for r in rows
        ]

    def report_roster_gaps(self) -> list[dict]:
        """Teams where game_players count > team_players count.

        Players appeared in game lineups but were never added to the roster.
        Returned as list of dicts with keys: team_id, season_id,
        game_player_count, roster_count, delta.
        """
        with self.db_service.session_scope() as session:
            rows = session.execute(text("""
                SELECT gp.team_id, gp.season_id,
                       COUNT(DISTINCT gp.player_id) AS gp_count,
                       COUNT(DISTINCT tp.player_id) AS tp_count
                FROM game_players gp
                LEFT JOIN team_players tp
                    ON tp.team_id = gp.team_id
                    AND tp.season_id = gp.season_id
                    AND tp.player_id = gp.player_id
                GROUP BY gp.team_id, gp.season_id
                HAVING COUNT(DISTINCT gp.player_id) > COUNT(DISTINCT tp.player_id)
                ORDER BY (COUNT(DISTINCT gp.player_id) - COUNT(DISTINCT tp.player_id)) DESC
                LIMIT 100
            """)).fetchall()
        return [
            {
                "team_id": r[0],
                "season_id": r[1],
                "game_player_count": r[2],
                "roster_count": r[3],
                "delta": r[2] - r[3],
            }
            for r in rows
        ]

    def report_unresolved_stats(self) -> list[dict]:
        """player_statistics rows with null team_id or null game_class.

        Returned as list of dicts with keys: player_id, season_id,
        league_abbrev, team_name, team_id, game_class.
        """
        with self.db_service.session_scope() as session:
            rows = session.execute(text("""
                SELECT ps.player_id, ps.season_id, ps.league_abbrev,
                       ps.team_name, ps.team_id, ps.game_class
                FROM player_statistics ps
                WHERE ps.team_id IS NULL OR ps.game_class IS NULL
                ORDER BY ps.season_id DESC, ps.player_id
                LIMIT 200
            """)).fetchall()
        return [
            {
                "player_id": r[0],
                "season_id": r[1],
                "league_abbrev": r[2],
                "team_name": r[3],
                "team_id": r[4],
                "game_class": r[5],
            }
            for r in rows
        ]

    # ── Entry point ────────────────────────────────────────────────────────

    def run_nightly(self) -> dict:
        """Run all conservative fixes. Returns summary dict with row counts."""
        logger.info("[repair] starting nightly repair run")
        result = {
            "stuck_in_progress": self.fix_stuck_in_progress(),
            "null_game_dates":   self.fix_null_game_dates(),
            "missing_events":    self.fix_missing_events(),
            "null_period_fixed": self.fix_null_period_from_events(),
            "stale_failed":      self.fix_stale_failed_rows(),
        }
        result["total_fixed"] = sum(result.values())
        logger.info("[repair] nightly run complete: %s", result)
        self._write_sync_status(result["total_fixed"])
        return result

    def _write_sync_status(self, total_fixed: int):
        """Upsert a completed sync_status row so the scheduler sees last run time."""
        with self.db_service.session_scope() as session:
            row = session.query(SyncStatus).filter_by(
                entity_type="repair", entity_id="all"
            ).first()
            if not row:
                row = SyncStatus(entity_type="repair", entity_id="all")
                session.add(row)
            row.sync_status = "completed"
            row.last_sync = datetime.utcnow()
            row.records_synced = total_fixed
            row.error_message = None


# Module-level singleton (same pattern as data_indexer)
_repair_service: RepairService | None = None


def get_repair_service() -> RepairService:
    global _repair_service
    if _repair_service is None:
        from app.services.database import get_database_service
        _repair_service = RepairService(get_database_service())
    return _repair_service

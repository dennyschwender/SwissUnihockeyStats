"""
Hierarchical Data Indexer
Fetches data from Swiss Unihockey API following the documented hierarchy:
SEASONS → CLUBS → TEAMS → PLAYERS
SEASONS → LEAGUES → GROUPS → GAMES → PLAYERS
"""
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.models.db_models import (
    Season, Club, Team, Player, TeamPlayer, League, LeagueGroup,
    Game, GamePlayer, GameEvent, PlayerStatistics, SyncStatus
)
from app.services.swissunihockey import get_swissunihockey_client
from app.services.database import get_database_service

logger = logging.getLogger(__name__)


@dataclass
class _PlayerGameStatsFetchResult:
    """Result of a Phase-1 API fetch for one player's game stats."""
    player_id: int
    game_stats: dict = field(default_factory=dict)  # game_id -> (goals, assists, pim)
    api_error: bool = False  # True only for HTTP 5xx — increments skip counter


@dataclass
class _PlayerStatsFetchResult:
    """Result of a Phase-1 API fetch for one player's seasonal stats."""
    player_id: int
    raw_data: dict = field(default_factory=dict)
    api_error: bool = False  # True only for HTTP 5xx — increments skip counter


def _phase_from_slider_text(slider_text: str) -> str:
    """Extract a stable phase bucket from a slider round title.

    Examples::

        'Runde 22 / 31.1.26'               → 'Regelsaison'
        'Playoff Viertelfinals / 14.2.26'  → 'Playoff Viertelfinals'
        'Final / ...'                       → 'Final'
        ''                                  → 'Regelsaison'

    All numbered rounds ("Runde N") collapse into the single bucket
    ``'Regelsaison'`` so that Vorrunde and Rückrunde share one
    :class:`LeagueGroup`.  Every other label gets its own bucket, which
    means playoff phases each become a separate group.
    """
    
    if not slider_text:
        return "Regelsaison"
    label = slider_text.split(" / ")[0].strip()
    if re.match(r'Runde\s+\d+$', label, re.IGNORECASE):
        return "Regelsaison"
    return label or "Regelsaison"


def _parse_game_rows(regions: list) -> list[dict]:
    """Parse raw API regions into a list of game dicts (pure, no DB access).

    Each returned dict has the keys:
        game_id, game_date, game_time_str, venue,
        home_team_id, home_team_name, home_logo_url,
        away_team_id, away_team_name, away_logo_url,
        home_score, away_score, status, period
    """
    
    games: list[dict] = []
    for region in regions:
        for row in region.get("rows", []):
            cells = row.get("cells", [])
            if not cells:
                continue

            # --- game_id (from date cell link) ---
            date_cell = cells[0] if cells else {}
            link = date_cell.get("link", {})
            if not link.get("ids"):
                continue
            game_id = link["ids"][0]

            # --- date / time ---
            game_date = None
            game_time_str = None
            date_text = date_cell.get("text", "")
            if isinstance(date_text, list):
                date_text = date_text[0] if date_text else ""
            if date_text:
                for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%y %H:%M"):
                    try:
                        game_date = datetime.strptime(date_text.strip(), fmt)
                        game_time_str = game_date.strftime("%H:%M")
                        break
                    except ValueError:
                        pass

            # --- venue ---
            venue = None
            if len(cells) > 1:
                v = cells[1].get("text", [])
                venue = (v[0] if isinstance(v, list) else v) or None

            # --- home team (cells[2] = name/link, cells[3] = logo) ---
            home_team_id = None
            home_team_name = None
            home_logo_url = None
            if len(cells) > 2:
                hl = cells[2].get("link", {})
                if hl.get("ids"):
                    home_team_id = hl["ids"][0]
                t = cells[2].get("text", [])
                home_team_name = (t[0] if isinstance(t, list) else t) or None
            if len(cells) > 3:
                home_logo_url = cells[3].get("image", {}).get("url") or None

            # --- away team (cells[6] preferred; cells[5] fallback; logo at cells[5]) ---
            away_team_id = None
            away_team_name = None
            away_logo_url = None
            if len(cells) > 6:
                al = cells[6].get("link", {})
                if al.get("ids"):
                    away_team_id = al["ids"][0]
                t = cells[6].get("text", [])
                away_team_name = (t[0] if isinstance(t, list) else t) or None
            elif len(cells) > 5:
                al = cells[5].get("link", {})
                if al.get("ids"):
                    away_team_id = al["ids"][0]
                t = cells[5].get("text", [])
                away_team_name = (t[0] if isinstance(t, list) else t) or None
            if len(cells) > 5:
                away_logo_url = cells[5].get("image", {}).get("url") or None

            if not home_team_id or not away_team_id:
                continue

            # --- score / status (cell[7]) ---
            home_score = None
            away_score = None
            status = "scheduled"
            period = None
            if len(cells) > 7:
                score_text = cells[7].get("text", ["-"])
                score_text = score_text[0] if isinstance(score_text, list) else score_text
                if score_text and score_text not in ("-", ""):
                    m = re.match(r'(\d+)\s*:\s*(\d+)\s*(n\.V\.|n\.P\.)?',
                                  score_text.strip(), re.I)
                    if m:
                        home_score = int(m.group(1))
                        away_score = int(m.group(2))
                        sfx = (m.group(3) or "").upper()
                        period = "SO" if "P" in sfx else ("OT" if "V" in sfx else None)
                        status = "finished"

            games.append({
                "game_id": game_id,
                "game_date": game_date,
                "game_time_str": game_time_str,
                "venue": venue,
                "home_team_id": home_team_id,
                "home_team_name": home_team_name,
                "home_logo_url": home_logo_url,
                "away_team_id": away_team_id,
                "away_team_name": away_team_name,
                "away_logo_url": away_logo_url,
                "home_score": home_score,
                "away_score": away_score,
                "status": status,
                "period": period,
            })
    return games


# Note: the API groups all A-level youth under league_id 13 (U14A/U16A/U18A/U21A),
# all B-level under 14, all C-level under 15 — sub-categories cannot be split further.
#
#   Tier 1 — NLA / L-UPL                         (league_id 1, 10, 24)
#   Tier 2 — + NLB, all A-level youth            (league_id 2, 13)
#   Tier 3 — + 1. Liga, all B-level youth        (league_id 3, 14)
#   Tier 4 — + 2. Liga, all C-level youth        (league_id 4, 15)
#   Tier 5 — + 3. Liga, U21 D                    (league_id 5, 16)
#   Tier 6 — + 4./5. Liga, Supercup, Test, Regional  (league_id 6, 7, 12, 23, 25)
# ---------------------------------------------------------------------------
LEAGUE_TIERS: dict[int, int] = {
    1:  1,   # Herren/Damen NLA (legacy name)
    10: 1,   # Herren/Damen SML (NLA, intermediate name)
    24: 1,   # Herren/Damen L-UPL (NLA, current name)
    2:  2,   # Herren/Damen NLB
    13: 2,   # A-level youth: U14A, U16A, U18A, U21A, Juniorinnen U21A/U17A
    3:  3,   # 1. Liga (Herren/Damen)
    14: 3,   # B-level youth: U14B, U16B, U18B, U21B, Juniorinnen U21B/U17B
    4:  4,   # 2. Liga (Herren/Damen)
    15: 4,   # C-level youth: U16C, U18C, U21C
    5:  5,   # 3. Liga (Herren/Damen)
    16: 5,   # U21 D
    6:  6,   # 4. Liga
    7:  6,   # 5. Liga
    12: 6,   # Regional (Junioren A–E, Juniorinnen A–D, Senioren)
    23: 6,   # Supercup
    25: 6,   # Test / Cup
}
# Default tier for unknown league_ids (7 = no filter / include everything)
_DEFAULT_TIER = 7

TIER_LABELS: dict[int, str] = {
    1: "Tier 1 — NLA/L-UPL only",
    2: "Tier 2 — + NLB, U21A/U18A/U16A",
    3: "Tier 3 — + 1. Liga, U21B/U18B/U16B",
    4: "Tier 4 — + 2. Liga, U21C/U18C/U16C",
    5: "Tier 5 — + 3. Liga, U21D",
    6: "Tier 6 — + 4./5. Liga, Regional, Cups",
    7: "All leagues (no tier filter)",
}


def league_tier(league_id: int) -> int:
    """Return the tier (1=top) for a given API league_id."""
    return LEAGUE_TIERS.get(league_id, _DEFAULT_TIER)


# ── Age-based TTL for game events / lineups ──────────────────────────────────
# The older a game is, the less likely its data changes.  We poll very
# frequently while a game is live, then back off aggressively once the
# data is stable.  The overnight nightly run (scheduler tick) is the last
# chance to pick up late-published data (e.g. best-player awards) before
# the game is effectively frozen.
#
#   < 3 h since kickoff  →   5 min   (game may still be live)
#   3 – 12 h             →   1 h     (just finished today)
#   12 – 48 h            →   4 h     (overnight / recent — nightly batch covers this)
#   48 h – 7 d           → 168 h     (best player / referee data published late)
#   ≥ 7 d                → 720 h     (data frozen — almost no re-index)
def _game_events_ttl_hours(game_date: "datetime | None") -> float:
    if game_date is None:
        return 4.0  # safe default — treat as recently finished
    now = datetime.now(timezone.utc)
    gd  = game_date if game_date.tzinfo else game_date.replace(tzinfo=timezone.utc)
    age = (now - gd).total_seconds() / 3600
    if age < 3:
        return 5 / 60      # 5 minutes — may still be live
    if age < 12:
        return 1.0         # 1 hour — just finished today
    if age < 48:
        return 4.0         # 4 hours — yesterday / very recent
    if age < 168:
        return 24.0        # 1 day — officials add best players / referees within 24-48h
    return 720.0           # 30 days — effectively frozen


class DataIndexer:
    """Hierarchical data indexer for Swiss Unihockey stats"""

    def __init__(self, db=None, api=None):
        self.client = api if api is not None else get_swissunihockey_client()
        self.db_service = db if db is not None else get_database_service()

    def cleanup_stale_sync_status(self) -> int:
        """Reset any in_progress rows left over from a previous server process."""
        with self.db_service.session_scope() as session:
            stale = session.query(SyncStatus).filter(
                SyncStatus.sync_status == "in_progress"
            ).all()
            for row in stale:
                row.sync_status = "failed"
                row.error_message = "Server restarted while job was running"
            session.commit()
            return len(stale)

    # ==================== UTILITY METHODS ====================
    
    def _should_update(self, entity_type: str, entity_id: str, max_age_hours: int = 24) -> bool:
        """Check if an entity needs updating based on last sync time
        
        Args:
            entity_type: Type of entity (e.g., "season", "club")
            entity_id: ID of specific entity
            max_age_hours: Maximum age in hours before update needed
        
        Returns:
            True if update is needed
        """
        with self.db_service.session_scope() as session:
            sync = session.query(SyncStatus).filter(
                SyncStatus.entity_type == entity_type,
                SyncStatus.entity_id == entity_id
            ).first()
            
            if not sync:
                return True
            
            last = sync.last_sync
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - last
            return age > timedelta(hours=max_age_hours)
    
    def _mark_sync_start(self, session: Session, entity_type: str, entity_id: str):
        """Mark synchronization as started"""
        sync = session.query(SyncStatus).filter(
            SyncStatus.entity_type == entity_type,
            SyncStatus.entity_id == entity_id
        ).first()
        
        if not sync:
            sync = SyncStatus(
                entity_type=entity_type,
                entity_id=entity_id
            )
            session.add(sync)
        
        sync.last_sync = datetime.now(timezone.utc)
        sync.sync_status = "in_progress"
        sync.error_message = None
        session.commit()
    
    def _mark_sync_complete(self, session: Session, entity_type: str, entity_id: str, records_count: int = 0):
        """Mark synchronization as completed (upsert — creates the row if it doesn't exist).

        _mark_sync_start is the historic row creator, but several indexer methods
        (teams, players, game_events, …) never call _mark_sync_start, so calling
        the old update-only version silently wrote nothing.  This version always
        creates the row when missing so the scheduler's freshness check works.
        """
        sync = session.query(SyncStatus).filter(
            SyncStatus.entity_type == entity_type,
            SyncStatus.entity_id == entity_id
        ).first()

        if not sync:
            sync = SyncStatus(entity_type=entity_type, entity_id=entity_id)
            session.add(sync)

        sync.sync_status    = "completed"
        sync.records_synced = records_count
        sync.last_sync      = datetime.now(timezone.utc)
        sync.error_message  = None
        session.commit()
    
    def bulk_already_indexed(self, entity_type: str, entity_ids: list[str],
                              max_age_hours: int = 720) -> set[str]:
        """Return the set of *entity_ids* that already have a fresh 'success'
        SyncStatus row, so the caller can skip re-indexing them.

        This replaces N individual _should_update() calls (each a DB query)
        with a single IN-based query.
        """
        if not entity_ids:
            return set()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        try:
            with self.db_service.session_scope() as session:
                rows = (
                    session.query(SyncStatus.entity_id)
                    .filter(
                        SyncStatus.entity_type == entity_type,
                        SyncStatus.entity_id.in_(entity_ids),
                        SyncStatus.sync_status == "completed",
                        SyncStatus.last_sync > cutoff,
                    )
                    .all()
                )
            return {r[0] for r in rows}
        except Exception:
            return set()

    def _mark_sync_failed(self, session: Session, entity_type: str, entity_id: str, error: str):
        """Mark synchronization as failed.

        Always upserts the row and sets last_sync=now so _should_update can
        use it for backoff — without last_sync, _should_update returns True
        (no row → needs update) and the entity is retried on every cycle.

        The session may already be in a rolled-back state (e.g. after a
        sqlite3.OperationalError: database is locked).  Roll it back first
        so we can issue a fresh query, and swallow any secondary errors so
        the original exception propagates cleanly.
        """
        try:
            session.rollback()          # clear PendingRollbackError state
            sync = session.query(SyncStatus).filter(
                SyncStatus.entity_type == entity_type,
                SyncStatus.entity_id == entity_id
            ).first()
            if not sync:
                sync = SyncStatus(entity_type=entity_type, entity_id=entity_id)
                session.add(sync)
            sync.sync_status = "failed"
            sync.last_sync = datetime.now(timezone.utc)   # enable backoff
            sync.error_message = error[:500] if error else error
            session.commit()
        except Exception:
            # Best-effort: if we still can't write, silently ignore so the
            # original exception is not masked.
            pass

    def record_season_sync(self, entity_type: str, season_id: int, records: int = 0):
        """Upsert a season-level sync_status sentinel row.

        The scheduler's _last_sync_for() queries sync_status for a row matching
        entity_type + entity_id LIKE '%{season}%'.  Several tasks (league_groups,
        games, game_events) write per-entity rows whose entity_id does NOT contain
        the season year, so _last_sync_for always returns None and the scheduler
        re-queues those jobs on every tick.

        Calling this method after a season-wide task completes writes:
            entity_type = <entity_type>
            entity_id   = "season:<season_id>"
            sync_status = "completed"
        which the scheduler will find on the next freshness check.
        """
        entity_id = f"season:{season_id}"
        try:
            with self.db_service.session_scope() as session:
                sync = session.query(SyncStatus).filter(
                    SyncStatus.entity_type == entity_type,
                    SyncStatus.entity_id   == entity_id,
                ).first()
                if not sync:
                    sync = SyncStatus(entity_type=entity_type, entity_id=entity_id)
                    session.add(sync)
                sync.sync_status    = "completed"
                sync.records_synced = records
                sync.last_sync      = datetime.now(timezone.utc)
                session.commit()
                logger.debug(
                    "record_season_sync: %s / %s = %d records",
                    entity_type, entity_id, records,
                )
        except Exception as exc:
            logger.warning("record_season_sync failed for %s season %s: %s", entity_type, season_id, exc)

    def _extract_table_data(self, api_response: Dict[str, Any]) -> List[Dict]:
        """Extract data from API table format: data.regions[0].rows"""
        if not isinstance(api_response, dict):
            return []
        
        data = api_response.get("data", {})
        if isinstance(data, dict) and "regions" in data:
            regions = data.get("regions", [])
            if regions and len(regions) > 0:
                rows = regions[0].get("rows", [])
                return rows if isinstance(rows, list) else []
        
        # Fallback to entries format
        return api_response.get("entries", [])
    
    # ==================== LEVEL 1: SEASONS ====================
    
    def index_seasons(self, force: bool = False) -> int:
        """Index all seasons from API
        
        Args:
            force: Force update even if recently synced
        
        Returns:
            Number of seasons indexed
        """
        if not force and not self._should_update("seasons", "all", max_age_hours=720):  # 30 days
            logger.info("Seasons recently synced, skipping")
            return 0
        
        logger.info("Indexing seasons...")
        
        try:
            with self.db_service.session_scope() as session:
                self._mark_sync_start(session, "seasons", "all")

                # Fetch seasons from API
                seasons_data = self.client.get_seasons()
                entries = seasons_data.get("entries", [])

                # Derive the latest season that has actually started.
                # Sep-Dec: current year; Jan-Aug: previous year.
                _now_dt = datetime.now()
                _max_season = _now_dt.year if _now_dt.month >= 9 else _now_dt.year - 1

                count = 0
                for entry in entries:
                    context = entry.get("set_in_context", {})
                    season_id = context.get("season")

                    if not season_id:
                        continue

                    # Skip seasons that haven't started yet (e.g. API already
                    # exposes 2026/27 in February 2026 — ignore it until Sep 2026).
                    if season_id > _max_season:
                        logger.debug("Skipping future season %s (max=%s)", season_id, _max_season)
                        continue

                    # merge() upserts: updates if exists, inserts if not.
                    # This makes concurrent calls safe (no UNIQUE constraint race).
                    existing = session.get(Season, season_id)
                    if existing is None:
                        season = Season(
                            id=season_id,
                            highlighted=entry.get("highlight", False),
                        )
                        session.add(season)
                    else:
                        season = existing

                    season.text = entry.get("text", f"{season_id}/{season_id+1}")
                    season.last_updated = datetime.now(timezone.utc)
                    count += 1

                self._mark_sync_complete(session, "seasons", "all", count)
                logger.info(f"✓ Indexed {count} seasons")
            return count

        except Exception as e:
            logger.error(f"Failed to index seasons: {e}", exc_info=True)
            try:
                with self.db_service.session_scope() as s:
                    self._mark_sync_failed(s, "seasons", "all", str(e))
            except Exception:
                pass
            raise
    
    # ==================== LEVEL 2: CLUBS ====================
    
    def index_clubs(self, season_id: int, force: bool = False) -> int:
        """Index clubs for a specific season
        
        Args:
            season_id: Season ID to index clubs for
            force: Force update even if recently synced
        
        Returns:
            Number of clubs indexed
        """
        entity_id = f"season:{season_id}"
        if not force and not self._should_update("clubs", entity_id, max_age_hours=168):  # 7 days
            logger.debug(f"Clubs for season {season_id} recently synced, skipping")
            # Still bump last_sync so the scheduler's _snap_to_hour advances to
            # the *next* nightly window instead of replaying the same past date.
            with self.db_service.session_scope() as _s:
                self._mark_sync_complete(_s, "clubs", entity_id, 0)
            return 0
        
        logger.info(f"Indexing clubs for season {season_id}...")
        
        try:
            with self.db_service.session_scope() as session:
                self._mark_sync_start(session, "clubs", entity_id)

                # Fetch clubs from API
                clubs_data = self.client.get_clubs(season=season_id)
                entries = self._extract_table_data(clubs_data)

                count = 0
                for entry in entries:
                    # Club ID is in set_in_context
                    context = entry.get("set_in_context", {})
                    club_id = context.get("club_id")
                    if not club_id:
                        continue

                    # Check if club exists for this season
                    club = session.query(Club).filter(
                        Club.id == club_id,
                        Club.season_id == season_id
                    ).first()

                    if not club:
                        club = Club(id=club_id, season_id=season_id)
                        session.add(club)

                    club.name = entry.get("text", "")
                    club.text = entry.get("text", "")
                    club.region = entry.get("region")
                    club.last_updated = datetime.now(timezone.utc)
                    count += 1

                self._mark_sync_complete(session, "clubs", entity_id, count)
                logger.info(f"✓ Indexed {count} clubs for season {season_id}")
                return count
        except Exception as e:
            logger.error(f"Failed to index clubs for season {season_id}: {e}", exc_info=True)
            return 0
    
    # ==================== LEVEL 3: TEAMS ====================
    
    def index_teams_for_club(self, club_id: int, season_id: int, force: bool = False) -> tuple[int, list[int]]:
        """Index teams for a specific club
        
        Args:
            club_id: Club ID
            season_id: Season ID
            force: Force update
        
        Returns:
            Tuple of (number of teams indexed, list of team IDs)
        """
        entity_id = f"club:{club_id}:season:{season_id}"
        if not force and not self._should_update("teams", entity_id, max_age_hours=72):  # 3 days
            return (0, [])
        
        logger.debug(f"Indexing teams for club {club_id}, season {season_id}...")
        
        team_ids = []
        try:
            with self.db_service.session_scope() as session:
                # Fetch teams from API (without mode parameter - it returns empty with mode="by_club")
                teams_data = self.client.get_teams(season=season_id, club=club_id)
                rows = self._extract_table_data(teams_data)
                
                count = 0
                for row in rows:
                    # Team ID is directly in the row
                    team_id = row.get("id")
                    if not team_id:
                        continue
                    
                    # Check if team exists for this season (composite PK: id + season_id)
                    team = session.query(Team).filter(
                        Team.id == team_id,
                        Team.season_id == season_id
                    ).first()
                    
                    if not team:
                        team = Team(id=team_id, club_id=club_id, season_id=season_id)
                        session.add(team)
                    # Do NOT overwrite club_id if team already exists - teams are shared
                    # across clubs in a season (league standings), first write wins
                    
                    # Extract team name from cells
                    cells = row.get("cells", [])
                    team_name = "Unknown Team"
                    if cells and len(cells) > 0:
                        first_cell = cells[0]
                        if isinstance(first_cell, dict):
                            text_value = first_cell.get("text", "Unknown Team")
                            # text_value might be a list like ['Chur Unihockey']
                            if isinstance(text_value, list) and text_value:
                                team_name = text_value[0]
                            else:
                                team_name = str(text_value) if text_value else "Unknown Team"
                    
                    team.name = team_name
                    team.text = team_name
                    team.last_updated = datetime.now(timezone.utc)
                    team_ids.append(team_id)
                    count += 1
                
                self._mark_sync_complete(session, "teams", entity_id, count)
                return (count, team_ids)
        except Exception as e:
            logger.debug(f"Failed to index teams for club {club_id}: {e}")
            return (0, team_ids)
    
    # ==================== LEVEL 4: PLAYERS ====================
    
    def index_players_for_team(self, team_id: int, season_id: int, force: bool = False) -> int:
        """Index players for a specific team
        
        Args:
            team_id: Team ID
            season_id: Season ID
            force: Force update
        
        Returns:
            Number of players indexed
        """
        entity_id = f"team:{team_id}:season:{season_id}"
        if not force and not self._should_update("players", entity_id, max_age_hours=24):
            return 0
        
        logger.debug(f"Indexing players for team {team_id}...")
        
        try:
            with self.db_service.session_scope() as session:
                # Fetch players from API
                players_data = self.client.get_team_players(team_id)
                rows = self._extract_table_data(players_data)
                
                if not rows or (isinstance(rows, str) and rows == ""):
                    logger.debug(f"No players found for team {team_id}")
                    return 0
                
                count = 0
                for row in rows:
                    # Player ID is in cells[2].link.ids[0] (player name cell)
                    person_id = None
                    player_name = "Unknown Player"
                    
                    cells = row.get("cells", [])
                    if len(cells) >= 3:
                        # cells[2] usually contains player name with link to player detail
                        name_cell = cells[2]
                        if isinstance(name_cell, dict):
                            # Get player name
                            if "text" in name_cell and name_cell["text"]:
                                player_name = name_cell["text"][0] if isinstance(name_cell["text"], list) else name_cell["text"]
                            # Get player ID from link
                            if "link" in name_cell:
                                link = name_cell["link"]
                                if isinstance(link, dict) and "ids" in link and link["ids"]:
                                    person_id = link["ids"][0]
                    
                    if not person_id:
                        logger.debug(f"Could not extract person_id from row: {row}")
                        continue
                    
                    # Get or create player
                    player = session.query(Player).filter(Player.person_id == person_id).first()
                    
                    if not player:
                        player = Player(
                            person_id=person_id,
                            full_name=player_name,
                            name_normalized=player_name.lower()
                        )
                        session.add(player)
                    
                    player.last_updated = datetime.now(timezone.utc)
                    
                    # Create or update team roster entry
                    team_player = session.query(TeamPlayer).filter(
                        TeamPlayer.team_id == team_id,
                        TeamPlayer.player_id == person_id,
                        TeamPlayer.season_id == season_id
                    ).first()
                    
                    if not team_player:
                        team_player = TeamPlayer(
                            team_id=team_id,
                            player_id=person_id,
                            season_id=season_id
                        )
                        session.add(team_player)
                    
                    # Extract additional info from cells: [0]=jersey#, [1]=position
                    if len(cells) >= 1:
                        num_cell = cells[0]
                        num_txt = num_cell.get("text", "") if isinstance(num_cell, dict) else ""
                        if isinstance(num_txt, list): num_txt = num_txt[0] if num_txt else ""
                        try:
                            team_player.jersey_number = int(num_txt) if num_txt else None
                        except (ValueError, TypeError):
                            team_player.jersey_number = None
                    else:
                        team_player.jersey_number = row.get("number")
                    if len(cells) >= 2:
                        pos_cell = cells[1]
                        pos_txt = pos_cell.get("text", "") if isinstance(pos_cell, dict) else ""
                        if isinstance(pos_txt, list): pos_txt = pos_txt[0] if pos_txt else ""
                        team_player.position = pos_txt or None
                    else:
                        team_player.position = row.get("position")
                    team_player.last_updated = datetime.now(timezone.utc)
                    
                    count += 1
                
                self._mark_sync_complete(session, "players", entity_id, count)
                logger.debug(f"✓ Indexed {count} players for team {team_id}")
                return count
        except Exception as e:
            logger.debug(f"Failed to index players for team {team_id}: {e}")
            return 0
    
    # ------------------------------------------------------------------
    # Internal helper shared by both the single-player and full-season
    # stats indexing paths.
    # ------------------------------------------------------------------

    def _apply_player_stats_result(
        self,
        session,
        person_id: int,
        stats_data: dict,
        season_id: int,
        season_label: str,
        staged: dict,
    ) -> int:
        """Write PlayerStatistics rows from a pre-fetched API response.

        Accepts the raw dict returned by client.get_player_stats() and upserts
        matching PlayerStatistics rows using the supplied session.
        Returns the number of rows upserted.

        Cell layout (0-indexed):
          0 – season text (e.g. "2025/26")
          1 – league name
          2 – club/team name
          3 – games played
          4 – goals
          5 – assists
          6 – points
          7 – 2-min penalties
          8 – 5-min penalties
          9 – 10-min penalties
         10 – match penalties
        """
        regions = stats_data.get("data", {}).get("regions", [])
        count = 0

        # Build team_name → (game_class, team_id) lookup for this player's roster memberships
        # so each PlayerStatistics row is tagged with the correct gender/age class and exact team.
        _gc_map: dict[str, int] = {}   # team_name → game_class
        _tid_map: dict[str, int] = {}  # team_name → team.id
        try:
            for tname, tgc, tid in (
                session.query(Team.name, Team.game_class, Team.id)
                .join(TeamPlayer, TeamPlayer.team_id == Team.id)
                .filter(
                    Team.season_id == season_id,
                    TeamPlayer.player_id == person_id,
                    TeamPlayer.season_id == season_id,
                    Team.game_class.isnot(None),
                )
                .all()
            ):
                if tname:
                    _gc_map[tname] = tgc
                    _tid_map[tname] = tid
        except Exception:
            pass

        for region in regions:
            for row in region.get("rows", []):
                cells = row.get("cells", [])
                if len(cells) < 4:
                    continue

                def _txt(idx, _c=cells):
                    v = _c[idx].get("text") if len(_c) > idx else None
                    if isinstance(v, list):
                        v = v[0] if v else None
                    return (v or "").strip()

                def _int(idx, _c=cells):
                    try:
                        return int(_txt(idx, _c))
                    except (ValueError, TypeError):
                        return 0

                row_season = _txt(0)
                if season_label and row_season != season_label:
                    continue

                league_abbrev   = _txt(1)
                team_name_txt   = _txt(2)
                game_class      = _gc_map.get(team_name_txt)
                team_db_id      = _tid_map.get(team_name_txt)
                games_played    = _int(3)
                goals           = _int(4)
                assists         = _int(5)
                points          = _int(6)
                pen_2min        = _int(7)
                pen_5min        = _int(8)
                pen_10min       = _int(9)
                pen_match       = _int(10)
                penalty_minutes = pen_2min * 2 + pen_5min * 5 + pen_10min * 10
                now             = datetime.now(timezone.utc)
                key             = (person_id, season_id, league_abbrev)

                def _apply(obj):
                    obj.league_abbrev   = league_abbrev
                    obj.team_name       = team_name_txt
                    obj.game_class      = game_class
                    obj.team_id         = team_db_id
                    obj.games_played    = games_played
                    obj.goals           = goals
                    obj.assists         = assists
                    obj.points          = points
                    obj.penalty_minutes = penalty_minutes
                    obj.pen_2min        = pen_2min
                    obj.pen_5min        = pen_5min
                    obj.pen_10min       = pen_10min
                    obj.pen_match       = pen_match
                    obj.last_updated    = now

                if key in staged:
                    _apply(staged[key])
                    count += 1
                    continue

                with session.no_autoflush:
                    existing = (
                        session.query(PlayerStatistics)
                        .filter(
                            PlayerStatistics.player_id == person_id,
                            PlayerStatistics.season_id == season_id,
                            PlayerStatistics.league_abbrev == league_abbrev,
                        ).first()
                    )

                if existing:
                    _apply(existing)
                    staged[key] = existing
                else:
                    obj = PlayerStatistics(
                        player_id       = person_id,
                        season_id       = season_id,
                        league_abbrev   = league_abbrev,
                        team_name       = team_name_txt,
                        game_class      = game_class,
                        team_id         = team_db_id,
                        games_played    = games_played,
                        goals           = goals,
                        assists         = assists,
                        points          = points,
                        penalty_minutes = penalty_minutes,
                        pen_2min        = pen_2min,
                        pen_5min        = pen_5min,
                        pen_10min       = pen_10min,
                        pen_match       = pen_match,
                        last_updated    = now,
                    )
                    session.add(obj)
                    staged[key] = obj
                count += 1
        return count

    def _fetch_player_stats_raw(self, person_id: int) -> "_PlayerStatsFetchResult":
        """Phase-1 worker: fetch seasonal stats for one player (no DB access)."""
        try:
            raw = self.client.get_player_stats(person_id)
            return _PlayerStatsFetchResult(player_id=person_id, raw_data=raw)
        except Exception as exc:
            import requests as _req
            is_5xx = (
                isinstance(exc, _req.HTTPError)
                and exc.response is not None
                and exc.response.status_code >= 500
            )
            return _PlayerStatsFetchResult(player_id=person_id, api_error=is_5xx)

    def _upsert_player_stats_from_api(
        self,
        person_id: int,
        season_id: int,
        season_label: str,
        session,
        staged: dict,
    ) -> tuple[int, bool]:
        """Fetch /api/players/:id/statistics and upsert matching rows.

        Uses the caller-supplied session so it can be embedded in a larger
        transaction (season loop) or a standalone one (single-player call).
        Returns a (rows_upserted, api_error) tuple where api_error is True
        only for HTTP 5xx responses (used to increment the skip counter).
        """
        try:
            stats_data = self.client.get_player_stats(person_id)
        except Exception as exc:
            import requests as _req
            if isinstance(exc, _req.HTTPError) and exc.response is not None and exc.response.status_code >= 500:
                logger.debug("API 5xx for player stats %s: %s", person_id, exc)
                return 0, True   # (rows_upserted, api_error)
            logger.debug("Could not fetch stats for player %s: %s", person_id, exc)
            return 0, False
        return self._apply_player_stats_result(session, person_id, stats_data, season_id, season_label, staged), False

    def index_player_stats_one(self, player_id: int, season_id: int, force: bool = False) -> int:
        """Index statistics for a single player in one season.

        Useful for targeted refreshes (e.g. after a game) without running the
        full season sweep.  Returns the number of stat rows upserted.
        """
        entity_id = f"player:{player_id}:{season_id}"
        if not force and not self._should_update("player_stats_one", entity_id, max_age_hours=1):
            return 0

        from app.models.db_models import Season as SeasonModel
        with self.db_service.session_scope() as session:
            season_row = session.get(SeasonModel, season_id)
            season_label = season_row.text if season_row and season_row.text else str(season_id)
            staged: dict[tuple, PlayerStatistics] = {}
            count, _api_err = self._upsert_player_stats_from_api(player_id, season_id, season_label, session, staged)
            if count:
                self._mark_sync_complete(session, "player_stats_one", entity_id, count)
        return count

    def index_player_stats_for_season(
        self, season_id: int, force: bool = False, exact_tier: int | None = None,
        on_progress=None,
    ) -> int:
        """Index player statistics for every known player in a season.

        Args:
            season_id:  Season to process.
            force:      Bypass the recency check.
            exact_tier: When set (1–6), only process players whose team's league
                        is at that specific tier.  Each tier slice has its own
                        SyncStatus row so the scheduler can track them
                        independently.  When None, all players are processed.
        """
        if exact_tier is not None:
            entity_type = f"player_stats_t{exact_tier}"
            entity_id   = f"season_player_stats:t{exact_tier}:{season_id}"
        else:
            entity_type = "player_stats"
            entity_id   = f"season:{season_id}"

        if not force and not self._should_update(entity_type, entity_id, max_age_hours=24):
            # Bump last_sync so the scheduler's _snap_to_hour advances to the
            # *next* nightly window instead of replaying the same past window
            # every tick (mirrors the same fix in index_leagues).
            with self.db_service.session_scope() as _s:
                self._mark_sync_complete(_s, entity_type, entity_id, 0)
            return 0

        # T1–T3 stats are computed from local game data; skip API calls for these tiers.
        if exact_tier in {1, 2, 3}:
            logger.info(
                "Skipping API player stats for tier %d (handled by local aggregation)", exact_tier
            )
            return 0

        tier_lbl = f" (tier {exact_tier} only)" if exact_tier else ""
        logger.info("Indexing player stats for season %s%s...", season_id, tier_lbl)

        # ── Pre-fetch season label (one short read) ──────────────────────────
        from app.models.db_models import Season as SeasonModel
        with self.db_service.session_scope() as session:
            season_row = session.get(SeasonModel, season_id)
            season_label = season_row.text if season_row and season_row.text else str(season_id)

        # ── Collect eligible player IDs ───────────────────────────────────────
        with self.db_service.session_scope() as session:
            from app.models.db_models import GamePlayer as _GamePlayer, Team as _TTeam
            if exact_tier is not None:
                tier_team_ids = {
                    t.id for t in session.query(_TTeam)
                    .filter(_TTeam.season_id == season_id).all()
                    if league_tier(t.league_id or 0) == exact_tier
                }
                tp_ids = {
                    r[0] for r in
                    session.query(TeamPlayer.player_id)
                    .filter(
                        TeamPlayer.season_id == season_id,
                        TeamPlayer.team_id.in_(tier_team_ids),
                    ).distinct().all()
                }
                gp_ids = {
                    r[0] for r in
                    session.query(_GamePlayer.player_id)
                    .filter(
                        _GamePlayer.season_id == season_id,
                        _GamePlayer.team_id.in_(tier_team_ids),
                    ).distinct().all()
                }
            else:
                tp_ids = {
                    r[0] for r in
                    session.query(TeamPlayer.player_id)
                    .filter(TeamPlayer.season_id == season_id)
                    .distinct().all()
                }
                gp_ids = {
                    r[0] for r in
                    session.query(_GamePlayer.player_id)
                    .filter(_GamePlayer.season_id == season_id)
                    .distinct().all()
                }
            player_ids = list(tp_ids | gp_ids)

        if not player_ids:
            logger.info("No players found for season %s%s", season_id, tier_lbl)
            if exact_tier is not None:
                with self.db_service.session_scope() as session:
                    self._mark_sync_complete(session, entity_type, entity_id, 0)
            return 0

        # Exclude players whose API skip window is still active
        now = datetime.now(timezone.utc)
        with self.db_service.session_scope() as session:
            skip_ids = {
                r[0] for r in session.query(Player.person_id)
                .filter(Player.api_skip_until.isnot(None), Player.api_skip_until > now)
                .all()
            }
        if skip_ids:
            logger.info("player_stats: skipping %d player(s) with active API skip window", len(skip_ids))
        player_ids = [pid for pid in player_ids if pid not in skip_ids]

        if not player_ids:
            logger.info("No eligible players for season %s%s after skip filter", season_id, tier_lbl)
            with self.db_service.session_scope() as session:
                self._mark_sync_complete(session, entity_type, entity_id, 0)
            return 0

        # Per-player checkpoint resume
        if not force:
            already_synced = self.bulk_already_indexed(
                "player_stats",
                [f"player_stats:{pid}:{season_id}" for pid in player_ids],
                max_age_hours=24,
            )
            if already_synced:
                before = len(player_ids)
                player_ids = [
                    pid for pid in player_ids
                    if f"player_stats:{pid}:{season_id}" not in already_synced
                ]
                logger.info(
                    "player_stats: skipping %d already-synced players (checkpoint resume), %d remaining",
                    before - len(player_ids), len(player_ids),
                )

        if not player_ids:
            with self.db_service.session_scope() as session:
                self._mark_sync_complete(session, entity_type, entity_id, 0)
            return 0

        logger.info("Indexing player stats for season %s%s (%d players)...", season_id, tier_lbl, len(player_ids))

        # ── Phase 1: parallel API fetches (no DB session held) ───────────────
        completed = 0
        _lock = threading.Lock()
        fetch_results: list = []

        def _fetch_one(pid: int):
            nonlocal completed
            result = self._fetch_player_stats_raw(pid)
            with _lock:
                completed += 1
                if on_progress:
                    on_progress(int(completed / len(player_ids) * 80))
            return result

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(_fetch_one, pid): pid for pid in player_ids}
            for fut in as_completed(futures):
                try:
                    fetch_results.append(fut.result())
                except Exception as exc:
                    logger.warning("player_stats worker error: %s", exc)

        # ── Phase 2: batched DB writes ────────────────────────────────────────
        count = self._run_player_stats_phase2(
            fetch_results=fetch_results,
            season_id=season_id,
            season_label=season_label,
            entity_type=entity_type,
            entity_id=entity_id,
            exact_tier=exact_tier,
            now=now,
        )

        if on_progress:
            on_progress(100)
        logger.info("✓ Indexed %d player stat rows for season %s%s", count, season_id, tier_lbl)
        return count

    def compute_player_stats_for_season(
        self, season_id: int, force: bool = False, tiers: tuple[int, ...] = (1, 2, 3),
    ) -> int:
        """Compute PlayerStatistics from local GamePlayer/GameEvent data for T1–T3.

        Replaces per-player API calls for tiers where game data is complete.
        """
        entity_type = "compute_player_stats"
        entity_id = f"season:{season_id}"

        if not force and not self._should_update(entity_type, entity_id, max_age_hours=6):
            with self.db_service.session_scope() as _s:
                self._mark_sync_complete(_s, entity_type, entity_id, 0)
            return 0

        from app.services.local_stats_aggregator import aggregate_player_stats_for_season
        try:
            count = aggregate_player_stats_for_season(self.db_service, season_id, tiers=tiers)
            with self.db_service.session_scope() as session:
                self._mark_sync_complete(session, entity_type, entity_id, count)
            logger.info("compute_player_stats season=%s → %d rows", season_id, count)
            return count
        except Exception as exc:
            logger.error("compute_player_stats season=%s failed: %s", season_id, exc)
            raise

    # ==================== LEAGUES PATH ====================

    def index_leagues(self, season_id: int, force: bool = False) -> int:
        """Index all leagues for a season (from the flat /api/leagues endpoint).

        The leagues endpoint does NOT accept a season parameter — it returns all
        leagues across all seasons.  We filter by comparing against known seasons
        pulled from the DB; since the API only returns current/recent leagues we
        store every entry and tag it with the requested season_id so it can be
        used as the anchor for group/game indexing.

        Returns:
            Number of new League rows inserted.
        """
        entity_id = f"season:{season_id}"
        if not force and not self._should_update("leagues", entity_id, max_age_hours=168):
            logger.debug(f"Leagues for season {season_id} recently synced, skipping")
            # Still bump last_sync so the scheduler's _snap_to_hour advances to
            # the *next* nightly window instead of replaying the same past date.
            with self.db_service.session_scope() as _s:
                self._mark_sync_complete(_s, "leagues", entity_id, 0)
            return 0

        logger.info(f"Indexing leagues for season {season_id}...")

        try:
            with self.db_service.session_scope() as session:
                self._mark_sync_start(session, "leagues", entity_id)

                leagues_data = self.client.get_leagues()
                entries = leagues_data.get("entries", [])

                count = 0
                # Stage by (league_id, game_class) to handle duplicate API entries
                # within the same response without hitting the UNIQUE constraint.
                staged: dict[tuple, League] = {}
                for entry in entries:
                    context = entry.get("set_in_context", {})
                    league_id = context.get("league")
                    game_class = context.get("game_class")
                    if not league_id or not game_class:
                        continue

                    key = (league_id, game_class)
                    league = staged.get(key) or session.query(League).filter(
                        League.season_id == season_id,
                        League.league_id == league_id,
                        League.game_class == game_class
                    ).first()

                    if league is None:
                        league = League(
                            season_id=season_id,
                            league_id=league_id,
                            game_class=game_class,
                        )
                        session.add(league)

                    league.name = entry.get("text", "")
                    league.text = entry.get("text", "")
                    league.mode = context.get("mode")
                    league.last_updated = datetime.now(timezone.utc)
                    staged[key] = league
                    count += 1

                self._mark_sync_complete(session, "leagues", entity_id, count)
                logger.info(f"✓ Indexed {count} leagues for season {season_id}")
                return count

        except Exception as e:
            logger.error(f"Failed to index leagues for season {season_id}: {e}", exc_info=True)
            # If this is a past season that already has leagues indexed, treat
            # the API failure as non-fatal and mark completed so the scheduler
            # doesn't re-queue it every tick (the API may no longer serve old data).
            try:
                with self.db_service.session_scope() as s:
                    existing = s.query(League).filter(
                        League.season_id == season_id
                    ).count()
                    if existing > 0:
                        logger.info(
                            f"[leagues] API failed but {existing} leagues already exist "
                            f"for season {season_id} — marking completed to suppress retries"
                        )
                        self._mark_sync_complete(s, "leagues", entity_id, existing)
                    else:
                        self._mark_sync_failed(s, "leagues", entity_id, str(e))
            except Exception:
                pass
            return 0

    def index_groups_for_league(self, league_db_id: int, season_id: int,
                                 league_id: int, game_class: int,
                                 force: bool = False) -> int:
        """Index groups (divisions) for a league.

        Returns:
            Number of new LeagueGroup rows inserted.
        """
        entity_id = f"league:{league_db_id}"
        if not force and not self._should_update("groups", entity_id, max_age_hours=24):
            return 0

        logger.debug(f"Indexing groups for league {league_id} game_class {game_class} season {season_id}")

        try:
            with self.db_service.session_scope() as session:
                groups_data = self.client.get_groups(
                    season=season_id, league=league_id, game_class=game_class
                )
                entries = groups_data.get("entries", [])
                count = 0
                for entry in entries:
                    ctx = entry.get("set_in_context", {})
                    group_name = entry.get("text", "") or ctx.get("group", "")
                    # Use a stable integer key: hash the string group name
                    # (the API doesn't give a numeric group ID directly)
                    group_key = abs(hash(f"{league_db_id}:{group_name}")) % (10 ** 9)

                    grp = session.query(LeagueGroup).filter(
                        LeagueGroup.league_id == league_db_id,
                        LeagueGroup.group_id == group_key
                    ).first()

                    if not grp:
                        grp = LeagueGroup(
                            league_id=league_db_id,
                            group_id=group_key,
                            name=group_name,
                            text=group_name,
                        )
                        session.add(grp)
                    else:
                        grp.name = group_name
                        grp.text = group_name
                    grp.last_updated = datetime.now(timezone.utc)
                    count += 1

                logger.debug(f"✓ Indexed {count} groups for league {league_id}")
                return count
        except Exception as e:
            logger.error(f"Failed to index groups for league {league_id}: {e}", exc_info=True)
            return 0

    def index_games_for_league(self, league_db_id: int, season_id: int,
                                league_id: int, game_class: int,
                                group_name: str = None, group_db_id: int = None,
                                force: bool = False) -> int:
        """Index all games for a league/game_class/season/group combination.

        Parses the table-format response from /api/games?mode=list.
        Columns (0-indexed):
          0 – date/time  (link → game_id)
          1 – venue
          2 – home team name  (link → home_team_id)
          3 – home team logo  (empty text, link → home_team_id)
          4 – separator  (text: "-")
          5 – away team logo  (empty text, link → away_team_id)
          6 – away team name  (link → away_team_id)
          7 – score/result  (text: "3:2" or "3:2 n.V.", "-" / empty if not played)
          8 – broadcast icon

        Args:
            group_name: The group text string (e.g. "Gruppe 1") used as the
                        ``group`` query parameter so the API filters to that
                        specific division. When None the API returns only the
                        next ~10 upcoming games regardless of group.
            group_db_id: The primary-key of the matching LeagueGroup row to use
                         as the FK on every Game row inserted.

        Returns:
            Number of new/updated Game rows.
        """
        group_tag = f":{group_name}" if group_name else ""
        entity_id = f"games:league:{league_db_id}{group_tag}"
        if not force and not self._should_update("games", entity_id, max_age_hours=1):
            return 0

        logger.info(
            f"Indexing games for league {league_id} game_class {game_class} "
            f"season {season_id} group={group_name!r}"
        )

        # ── Phase 1: Fetch all rounds from API (no DB session held) ──────────
        # All network I/O happens here so the SQLite write lock is not acquired
        # until Phase 2.  See index_game_events() for the same pattern.
        base_kwargs: dict = dict(season=season_id, league=league_id,
                                 game_class=game_class, mode="list")
        if group_name:
            base_kwargs["group"] = group_name

        # collected = list of {"phase": str, "games": list[dict]}
        collected: list[dict] = []
        visited_rounds: set = set()
        forward_start_round = None

        try:
            # Backward pass: current round → first round via slider.prev
            round_id = None  # None = API returns the current (latest) round
            while True:
                call_kwargs = {**base_kwargs}
                if round_id is not None:
                    call_kwargs["round"] = round_id

                games_data = self.client.get_games(**call_kwargs)
                d = games_data.get("data", {})
                slider = d.get("slider", {})

                if round_id is None and forward_start_round is None:
                    forward_start_round = (
                        (slider.get("next") or {}).get("set_in_context", {}).get("round")
                    )

                collected.append({
                    "phase": _phase_from_slider_text(slider.get("text", "")),
                    "games": _parse_game_rows(d.get("regions", [])),
                })
                visited_rounds.add(round_id)
                prev_round = (
                    (slider.get("prev") or {}).get("set_in_context", {}).get("round")
                )
                if prev_round is None or prev_round in visited_rounds:
                    break
                round_id = prev_round

            # Forward pass: capture future rounds via slider.next
            round_id = forward_start_round
            while round_id and round_id not in visited_rounds:
                call_kwargs = {**base_kwargs, "round": round_id}
                games_data = self.client.get_games(**call_kwargs)
                d = games_data.get("data", {})
                slider = d.get("slider", {})

                collected.append({
                    "phase": _phase_from_slider_text(slider.get("text", "")),
                    "games": _parse_game_rows(d.get("regions", [])),
                })
                visited_rounds.add(round_id)
                next_round = (
                    (slider.get("next") or {}).get("set_in_context", {}).get("round")
                )
                if not next_round or next_round in visited_rounds:
                    break
                round_id = next_round

        except Exception as e:
            # A 400 from the federation API means this league/game_class combo
            # has no data (e.g. a playoff round that hasn't started yet).
            # Mark it complete (count=0) so we don't retry every scheduler tick.
            _resp = getattr(e, "response", None)
            _status = getattr(_resp, "status_code", None) if _resp is not None else None
            with self.db_service.session_scope() as session:
                if _status == 400:
                    logger.warning(
                        f"League {league_id} game_class={game_class} group={group_name!r} "
                        f"returned 400 — no data yet, skipping until next cycle"
                    )
                    self._mark_sync_complete(session, "games", entity_id, 0)
                else:
                    logger.error(
                        f"Failed to index games for league {league_id}: {e}", exc_info=True
                    )
                    self._mark_sync_failed(session, "games", entity_id, str(e))
            return 0

        # ── Phase 2: Write all collected data in a single short session ───────
        with self.db_service.session_scope() as session:
            # Per-phase LeagueGroup cache: maps cache_key → LeagueGroup.id
            _phase_group_cache: dict[str, int] = {}

            def _get_or_create_phase_group(phase: str) -> int:
                cache_key = f"{league_db_id}:{group_name or ''}:{phase}"
                if cache_key in _phase_group_cache:
                    return _phase_group_cache[cache_key]
                _gk = abs(hash(cache_key)) % (10 ** 9)
                _grp = session.query(LeagueGroup).filter(
                    LeagueGroup.league_id == league_db_id,
                    LeagueGroup.group_id == _gk,
                ).first()
                if not _grp:
                    _grp = LeagueGroup(
                        league_id=league_db_id,
                        group_id=_gk,
                        name=group_name or "",
                        text=group_name or "",
                        phase=phase,
                    )
                    session.add(_grp)
                    session.flush()
                elif not _grp.phase:
                    _grp.phase = phase
                _phase_group_cache[cache_key] = _grp.id
                return _grp.id

            count = 0
            for round_data in collected:
                effective_group_id = _get_or_create_phase_group(round_data["phase"])
                for g in round_data["games"]:
                    game_id = g["game_id"]
                    home_team_id = g["home_team_id"]
                    away_team_id = g["away_team_id"]
                    team_name_map = {
                        home_team_id: g["home_team_name"],
                        away_team_id: g["away_team_name"],
                    }
                    team_logo_map = {
                        home_team_id: g["home_logo_url"],
                        away_team_id: g["away_logo_url"],
                    }

                    # Ensure team stubs exist
                    for tid in (home_team_id, away_team_id):
                        tname = team_name_map.get(tid)
                        tlogo = team_logo_map.get(tid)
                        existing = session.get(Team, (tid, season_id))
                        if not existing:
                            stub = Team(
                                id=tid,
                                season_id=season_id,
                                league_id=league_id,
                                game_class=game_class,
                                name=tname,
                                text=tname,
                                logo_url=tlogo,
                            )
                            session.add(stub)
                            try:
                                session.flush()
                            except Exception:
                                session.rollback()
                        else:
                            if tname and not existing.name:
                                existing.name = tname
                                existing.text = tname
                            if tlogo and not existing.logo_url:
                                existing.logo_url = tlogo
                            if not existing.league_id:
                                existing.league_id = league_id
                            if not existing.game_class:
                                existing.game_class = game_class

                    # Upsert game
                    game = session.get(Game, game_id)
                    if not game:
                        game = Game(
                            id=game_id,
                            season_id=season_id,
                            group_id=effective_group_id,
                            home_team_id=home_team_id,
                            away_team_id=away_team_id,
                        )
                        session.add(game)
                        try:
                            session.flush()
                        except IntegrityError:
                            # Concurrent job inserted this game_id first
                            session.rollback()
                            game = session.get(Game, game_id)
                            if not game:
                                continue

                    game.game_date = g["game_date"]
                    game.game_time = g["game_time_str"]
                    game.venue = g["venue"]
                    game.group_id = effective_group_id
                    # Only overwrite score/status when the API returned a real result;
                    # never clobber an existing stored score with None.
                    if g["home_score"] is not None:
                        game.home_score = g["home_score"]
                        game.away_score = g["away_score"]
                        game.status = g["status"]
                        if g["period"]:
                            game.period = g["period"]
                    elif game.status != "finished":
                        game.status = g["status"]
                    game.last_updated = datetime.now(timezone.utc)
                    count += 1

            session.commit()
            self._mark_sync_complete(session, "games", entity_id, count)
            logger.info(
                f"✓ Indexed {count} games for league {league_id} "
                f"group={group_name!r} ({len(visited_rounds)} rounds)"
            )
            return count

    def index_game_events(self, game_id: int, season_id: int,
                          force: bool = False,
                          game_date: "datetime | None" = None) -> int:
        """Fetch and store events (goals, penalties) for a single finished game.

        API calls are made *before* the DB session is opened so that the
        write lock is held for the minimum possible time.

        Args:
            game_date: Kickoff datetime (UTC or naive).  When supplied the
                       age-based TTL is computed directly; otherwise one cheap
                       DB lookup is made to retrieve it.

        Returns:
            Number of events stored.
        """
        entity_id = f"game:{game_id}:events"
        if not force:
            if game_date is None:
                with self.db_service.session_scope() as _s:
                    _g = _s.get(Game, game_id)
                    game_date = _g.game_date if _g else None
            ttl = _game_events_ttl_hours(game_date)
            if not self._should_update("game_events", entity_id, max_age_hours=ttl):
                return 0

        # ── 1. Fetch from API (no DB lock held) ───────────────────────────
        try:
            events_data = self.client.get_game_events_by_id(game_id)
        except Exception as e:
            logger.debug(f"Failed to fetch events for game {game_id}: {e}")
            return 0

        rows = self._extract_table_data(events_data)
        if not rows:
            rows = events_data.get("data", {}).get("regions", [{}])[0].get("rows", []) if events_data.get("data") else []

        # Try to get score + confirm finished via summary title
        # Title format: "Team A - Team B 3:2 (1:0, 2:2, 0:0)"
        game_is_finished = False
        home_score_val = None
        away_score_val = None
        period_from_api: str | None = None
        try:
            summary = self.client.get_game_summary(game_id)
            title = summary.get("data", {}).get("title", "") or ""
            
            m = re.search(r'(\d+):(\d+)\s*(n\.V\.|n\.P\.)?', title, re.I)
            if m:
                home_score_val = int(m.group(1))
                away_score_val = int(m.group(2))
                _sfx = (m.group(3) or "").upper()
                if "P" in _sfx:
                    period_from_api = "SO"
                elif "V" in _sfx:
                    period_from_api = "OT"
                game_is_finished = True
        except Exception:
            pass

        # Fetch game details (referees, spectators, precise venue) from /api/games/{id}
        referee_1_val: str | None = None
        referee_2_val: str | None = None
        spectators_val: int | None = None
        venue_val: str | None = None
        home_logo_val: str | None = None
        away_logo_val: str | None = None
        try:
            details = self.client.get_game_details(game_id)
            _rows = (details.get("data", {}).get("regions") or [{}])[0].get("rows", [])
            if _rows:
                _cells = _rows[0].get("cells", [])
                def _dcell(idx):
                    if len(_cells) <= idx:
                        return ""
                    v = _cells[idx].get("text", "")
                    return (v[0] if isinstance(v, list) else v or "").strip()
                # Column layout from attribute_list:
                # 0=home_logo 1=home_name 2=away_logo 3=away_name
                # 4=result 5=date 6=time 7=location 8=first_referee 9=second_referee 10=spectators
                if len(_cells) > 0:
                    home_logo_val = _cells[0].get("image", {}).get("url") or None
                if len(_cells) > 2:
                    away_logo_val = _cells[2].get("image", {}).get("url") or None
                # Parse date/time from cells 5 and 6 to backfill null game_date
                _date_str = _dcell(5)
                _time_str = _dcell(6)
                if _date_str:
                    _dt_str = f"{_date_str} {_time_str}".strip()
                    for _fmt in ("%d.%m.%Y %H:%M", "%d.%m.%y %H:%M", "%d.%m.%Y", "%d.%m.%y"):
                        try:
                            venue_val_date = datetime.strptime(_dt_str, _fmt)
                            break
                        except ValueError:
                            venue_val_date = None
                else:
                    venue_val_date = None

                _venue = _dcell(7)
                if _venue:
                    venue_val = _venue
                _ref1 = _dcell(8)
                if _ref1:
                    referee_1_val = _ref1
                _ref2 = _dcell(9)
                if _ref2:
                    referee_2_val = _ref2
                _spec = _dcell(10)
                if _spec and _spec.isdigit():
                    spectators_val = int(_spec)
                # Fallback: extract score from result cell (cell[4]) when
                # game_summary was unavailable (e.g. returns 404 for some games).
                if not game_is_finished:
                    _result = _dcell(4)
                    if _result:
                        
                        _m = re.match(r'(\d+)\s*:\s*(\d+)\s*(n\.V\.|n\.P\.)?', _result.strip(), re.I)
                        if _m:
                            home_score_val = int(_m.group(1))
                            away_score_val = int(_m.group(2))
                            if not period_from_api:
                                _sfx = (_m.group(3) or "").upper()
                                if "P" in _sfx:
                                    period_from_api = "SO"
                                elif "V" in _sfx:
                                    period_from_api = "OT"
                            game_is_finished = True
        except Exception:
            pass

        # ── 2. Parse / deduplicate (pure CPU, no I/O) ─────────────────────
        # Columns from /api/game_events/{id}:
        #   0 – clock time ("32:16", "")
        #   1 – event type text ("Torschütze", "Strafe", …)
        #   2 – team name
        #   3 – player name / note
        # Exact-match skips + prefix-skips for period-boundary events
        # (e.g. "Beginn 3. Drittel", "Ende 1. Drittel") that the old exact set
        # never caught because they contain the period number.
        SKIP_EVENTS_EXACT = {"spielende", "spielbeginn", ""}
        SKIP_EVENTS_PREFIX = ("beginn", "ende")
        raw_events: list[dict] = []
        for row in rows:
            cells = row.get("cells", [])
            if not cells:
                continue

            def _txt(cell):
                v = cell.get("text", "")
                return (v[0] if isinstance(v, list) and v else (v if not isinstance(v, list) else "")) or ""

            time_str    = _txt(cells[0]) if len(cells) > 0 else None
            event_type  = _txt(cells[1]) if len(cells) > 1 else "unknown"
            team_name   = _txt(cells[2]) if len(cells) > 2 else None
            player_name = _txt(cells[3]) if len(cells) > 3 else None

            etype_lo = event_type.lower()
            if etype_lo in SKIP_EVENTS_EXACT or etype_lo.startswith(SKIP_EVENTS_PREFIX):
                continue

            raw_events.append({
                "event_type": event_type,
                "time": time_str,
                "team": team_name,
                "player": player_name,
            })

        # Goals: API emits 2 rows per assisted goal (scorer-only, then
        # scorer+assist). Merge by (time, team), keeping the richer player.
        # Penalties: API emits 2 identical rows — keep only one.
        # Others (e.g. "Bester Spieler", "Technische Matchstrafe", «Spielabbruch»):
        # deduplicate by (event_type, time, team) in case the API repeats them.
        deduped: list[dict] = []
        seen_pen: set[tuple] = set()
        seen_other: set[tuple] = set()
        for ev in raw_events:
            etype_lo = ev["event_type"].lower()
            is_goal    = etype_lo.startswith(("torschütze", "eigentor"))
            is_penalty = "'-strafe" in etype_lo

            if is_penalty:
                key = (ev["event_type"], ev["time"], ev["team"])
                if key in seen_pen:
                    continue
                seen_pen.add(key)
                deduped.append(ev)
            elif is_goal:
                found = False
                for d in deduped:
                    if (d["time"] == ev["time"] and d["team"] == ev["team"]
                            and d["event_type"].lower().startswith(
                                ("torschütze", "eigentor"))):
                        if len(ev["player"] or "") > len(d["player"] or ""):
                            d["player"] = ev["player"]
                        found = True
                        break
                if not found:
                    deduped.append(ev)
            else:
                key = (ev["event_type"], ev["time"], ev["team"])
                if key in seen_other:
                    continue
                seen_other.add(key)
                deduped.append(ev)

        # Detect overtime: from explicit API suffix OR from goal events after 60:00
        is_ot = (period_from_api is None) and any(
            (ev.get("time") or "") >= "61:00"
            and ev["event_type"].lower().startswith(("torschütze", "eigentor"))
            for ev in deduped
        )
        # Detect SO: from explicit API suffix OR from "Penaltyschiessen" event type
        is_so = (period_from_api is None) and any(
            ev["event_type"].lower() == "penaltyschiessen"
            for ev in deduped
        )
        # SO supersedes OT if both are detected (game went OT then SO)
        new_period = period_from_api or ("SO" if is_so else ("OT" if is_ot else None))

        # ── 3. Write to DB (short critical section, no network I/O) ───────
        try:
            with self.db_service.session_scope() as session:
                # Delete stale events so re-indexing is idempotent
                session.query(GameEvent).filter(GameEvent.game_id == game_id).delete()
                session.flush()

                # Update game status/score + meta info if we got a result
                game_row = session.get(Game, game_id)
                if game_row:
                    if game_is_finished:
                        game_row.status = "finished"
                        game_row.home_score = home_score_val
                        game_row.away_score = away_score_val
                        if new_period:
                            game_row.period = new_period
                    if game_row.game_date is None and venue_val_date:
                        game_row.game_date = venue_val_date
                        game_row.game_time = venue_val_date.strftime("%H:%M")
                    if venue_val:
                        game_row.venue = venue_val
                    if referee_1_val is not None:
                        game_row.referee_1 = referee_1_val
                    if referee_2_val is not None:
                        game_row.referee_2 = referee_2_val
                    if spectators_val is not None:
                        game_row.spectators = spectators_val
                    # Backfill team logo URLs from game_details attribute_list
                    from app.models.db_models import Team as _Team
                    _season = game_row.season_id
                    if home_logo_val and game_row.home_team_id:
                        _ht = session.get(_Team, (game_row.home_team_id, _season))
                        if _ht and not _ht.logo_url:
                            _ht.logo_url = home_logo_val
                    if away_logo_val and game_row.away_team_id:
                        _at = session.get(_Team, (game_row.away_team_id, _season))
                        if _at and not _at.logo_url:
                            _at.logo_url = away_logo_val

                count = 0
                for ev in deduped:
                    evt = GameEvent(
                        game_id=game_id,
                        event_type=str(ev["event_type"])[:50],
                        period=None,
                        time=ev["time"] or None,
                        team_id=None,
                        season_id=None,
                        player_id=None,
                        raw_data=ev,
                        last_updated=datetime.now(timezone.utc),
                    )
                    session.add(evt)
                    count += 1

                self._mark_sync_complete(session, "game_events", entity_id, count)
                return count
        except Exception as e:
            logger.debug(f"Failed to write events for game {game_id}: {e}")
            return 0

    def index_game_lineup(self, game_id: int, season_id: int,
                          force: bool = False,
                          game_date: "datetime | None" = None) -> int:
        """Fetch and store home + away lineups for a single finished game.

        Both API calls are made *before* the DB session is opened so that
        the write lock is held for the minimum possible time.

        Args:
            game_date: Kickoff datetime (UTC or naive).  When supplied the
                       age-based TTL is computed directly; otherwise one cheap
                       DB lookup is made to retrieve it.

        Returns number of GamePlayer rows inserted/updated.
        """
        entity_id = f"game:{game_id}:lineup"
        if not force:
            if game_date is None:
                with self.db_service.session_scope() as _s:
                    _g = _s.get(Game, game_id)
                    game_date = _g.game_date if _g else None
            ttl = _game_events_ttl_hours(game_date)
            if not self._should_update("game_lineup", entity_id, max_age_hours=ttl):
                return 0

        # ── 1. Fetch both lineups from API (no DB lock held) ──────────────
        # API: is_home=0 → HOME lineup, is_home=1 → AWAY lineup.
        lineup_raw: dict[int, dict] = {}
        for is_home_flag in (1, 0):
            try:
                lineup_raw[is_home_flag] = self.client.get_game_lineup(game_id, is_home_flag)
            except Exception:
                lineup_raw[is_home_flag] = {}

        # ── 2. Write to DB (short critical section, no network I/O) ───────
        try:
            with self.db_service.session_scope() as session:
                # Build the set of player_ids already stored for this game.
                # We do NOT pre-read goals/assists/penalty_minutes here.
                # The update strategy below never touches those columns for
                # existing rows, eliminating the race condition with
                # index_player_game_stats that would otherwise wipe freshly
                # written stats (old approach: read-snapshot → delete-all →
                # re-insert from snapshot).
                existing_player_ids: set[int] = {
                    r[0] for r in session.query(GamePlayer.player_id)
                    .filter(GamePlayer.game_id == game_id).all()
                }

                game_row = session.get(Game, game_id)
                if game_row is None:
                    return 0
                home_team_id = game_row.home_team_id
                away_team_id = game_row.away_team_id

                # Pre-fetch valid FK sets to avoid IntegrityError on unknown players/teams
                from app.models.db_models import Player as _Player, Team as _Team
                valid_players: set[int] = {
                    r[0] for r in session.query(_Player.person_id).all()
                }
                valid_teams: set[tuple] = {
                    (r[0], r[1])
                    for r in session.query(_Team.id, _Team.season_id).all()
                }

                count = 0
                new_player_ids: set[int] = set()  # player_ids seen in the new lineup

                for is_home_flag in (1, 0):
                    team_id = away_team_id if is_home_flag else home_team_id
                    resp = lineup_raw.get(is_home_flag, {})

                    regions = resp.get("data", {}).get("regions", [])
                    for region in regions:
                        for row in region.get("rows", []):
                            cells = row.get("cells", [])
                            if not cells:
                                continue

                            def _txt(cell):
                                v = cell.get("text", "")
                                return (v[0] if isinstance(v, list) and v
                                        else (v if not isinstance(v, list) else "")) or ""

                            jersey_raw = _txt(cells[0]) if len(cells) > 0 else ""
                            position   = _txt(cells[1]) if len(cells) > 1 else None
                            player_raw = cells[2] if len(cells) > 2 else {}

                            # Extract player_id from link
                            player_id = None
                            link = player_raw.get("link", {})
                            if link:
                                ids = link.get("ids", [])
                                if ids:
                                    player_id = ids[0]

                            jersey = None
                            try:
                                jersey = int(jersey_raw)
                            except (ValueError, TypeError):
                                pass

                            if player_id is None:
                                continue

                            # Skip duplicates within this lineup response
                            if player_id in new_player_ids:
                                continue

                            # Auto-create a player stub if not yet in the table
                            if player_id not in valid_players:
                                player_name = _txt(player_raw)
                                parts = player_name.split(" ", 1)
                                stub = _Player(
                                    person_id=player_id,
                                    first_name=parts[0] if parts else None,
                                    last_name=parts[1] if len(parts) > 1 else None,
                                    full_name=player_name or f"Player {player_id}",
                                    name_normalized=(player_name or "").lower(),
                                    last_updated=datetime.now(timezone.utc),
                                )
                                session.add(stub)
                                valid_players.add(player_id)
                                logger.debug(
                                    f"Lineup: created player stub {player_id} '{player_name}'"
                                )

                            if (team_id, season_id) not in valid_teams:
                                logger.debug(
                                    f"Lineup skip: team ({team_id},{season_id}) not in teams table"
                                )
                                continue

                            new_player_ids.add(player_id)

                            pos_str = str(position)[:50] if position else None
                            is_home = not bool(is_home_flag)  # flag=0→home, flag=1→away

                            if player_id in existing_player_ids:
                                # UPDATE lineup fields only — goals/assists/penalty_minutes
                                # are managed exclusively by index_player_game_stats and
                                # must never be reset here (avoids the read-snapshot race).
                                session.query(GamePlayer).filter_by(
                                    game_id=game_id, player_id=player_id
                                ).update({
                                    "team_id":       team_id,
                                    "season_id":     season_id,
                                    "is_home_team":  is_home,
                                    "jersey_number": jersey,
                                    "position":      pos_str,
                                    "last_updated":  datetime.now(timezone.utc),
                                })
                            else:
                                # INSERT new player row — goals/assists/pim start as NULL
                                # (index_player_game_stats will fill them on its next run).
                                gp = GamePlayer(
                                    game_id=game_id,
                                    player_id=player_id,
                                    team_id=team_id,
                                    season_id=season_id,
                                    is_home_team=is_home,
                                    jersey_number=jersey,
                                    position=pos_str,
                                    goals=None,
                                    assists=None,
                                    penalty_minutes=None,
                                    last_updated=datetime.now(timezone.utc),
                                )
                                session.add(gp)
                                count += 1

                # Remove players who are no longer in the federation's lineup
                removed_ids = existing_player_ids - new_player_ids
                if removed_ids:
                    session.query(GamePlayer).filter(
                        GamePlayer.game_id == game_id,
                        GamePlayer.player_id.in_(removed_ids),
                    ).delete(synchronize_session=False)

                self._mark_sync_complete(session, "game_lineup", entity_id, count)
                return count
        except Exception as e:
            logger.debug(f"Failed to write lineup for game {game_id}: {e}")
            return 0

    def backfill_team_names(self, season_id: int, force: bool = False) -> int:
        """Backfill Team.name for stub rows that have no name.

        Calls the rankings API for every league in the season and records
        the (team_id → name) mapping returned by the API into the local DB.

        Returns number of Team rows updated.
        """
        entity_id = f"backfill_team_names:{season_id}"
        if not force and not self._should_update("team_names", entity_id, max_age_hours=24):
            logger.debug(f"Team names for season {season_id} recently backfilled, skipping")
            return 0

        logger.info(f"Backfilling team names for season {season_id}...")
        updated = 0

        with self.db_service.session_scope() as session:
            leagues = session.query(League).filter(League.season_id == season_id).all()
            name_map: dict[int, str] = {}  # team_id → name (across all leagues)

            for lg in leagues:
                try:
                    data = self.client.get_rankings(
                        league=lg.league_id,
                        game_class=lg.game_class,
                        season=season_id,
                    )
                    regions = data.get("data", {}).get("regions", [])
                    for region in regions:
                        for row in region.get("rows", []):
                            row_data = row.get("data", {})
                            team_info = row_data.get("team", {})
                            tid = team_info.get("id")
                            tname = team_info.get("name")
                            if tid and tname:
                                name_map[tid] = tname
                except Exception as e:
                    logger.warning(f"Rankings fetch failed for league {lg.league_id}: {e}")

            logger.info(f"Resolved {len(name_map)} team names from rankings API")

            # Bulk-update all nameless Team stubs in this season
            for team_id, name in name_map.items():
                team = session.get(Team, (team_id, season_id))
                if team and not team.name:
                    team.name = name
                    team.text = name
                    updated += 1

            session.commit()
            self._mark_sync_complete(session, "team_names", entity_id, updated)
            logger.info(f"✓ Backfilled names for {updated} teams in season {season_id}")
            return updated

    def backfill_team_league_attrs(self, season_id: int) -> int:
        """Backfill Team.league_id and Team.game_class from existing game records.

        Teams indexed via the clubs path never have league_id / game_class set.
        This method resolves them using the game → group → league chain that was
        already stored during the leagues indexing pass.

        Returns number of Team rows updated.
        """
        logger.info(f"Backfilling team league attrs for season {season_id}...")
        updated = 0
        with self.db_service.session_scope() as session:
            # Build team_id → (league_id, game_class) from all games in the season
            rows = (
                session.query(
                    Game.home_team_id,
                    Game.away_team_id,
                    League.league_id,
                    League.game_class,
                )
                .join(LeagueGroup, Game.group_id == LeagueGroup.id)
                .join(League, LeagueGroup.league_id == League.id)
                .filter(Game.season_id == season_id)
                .all()
            )
            team_attrs: dict[int, tuple[int, int]] = {}
            for home_id, away_id, l_id, gc in rows:
                for tid in (home_id, away_id):
                    if tid and tid not in team_attrs:
                        team_attrs[tid] = (l_id, gc)

            for team_id, (l_id, gc) in team_attrs.items():
                team = session.get(Team, (team_id, season_id))
                if team and (not team.league_id or not team.game_class):
                    if not team.league_id:
                        team.league_id = l_id
                    if not team.game_class:
                        team.game_class = gc
                    updated += 1

            session.commit()
        logger.info(f"✓ Backfilled league attrs for {updated} teams in season {season_id}")
        return updated

    def index_leagues_path(self, season_id: int = 2025,
                           index_games: bool = True,
                           index_events: bool = False,
                           force: bool = False) -> Dict[str, int]:
        """Full leagues → groups → games (→ events) indexing orchestration.

        Args:
            season_id:     Season to index.
            index_games:   Also fetch games for every league/group.
            index_events:  Also fetch game events for finished games (slow!).
            force:         Ignore existing sync timestamps.

        Returns:
            Dict with counts: leagues, groups, games, events.
        """
        stats: Dict[str, int] = {"leagues": 0, "groups": 0, "games": 0, "team_names": 0, "events": 0}

        logger.info(f"=== LEAGUES PATH starting for season {season_id} ===")

        # 1. Index leagues
        stats["leagues"] = self.index_leagues(season_id, force=force)

        # 2. Load league rows from DB
        with self.db_service.session_scope() as session:
            league_rows = [
                (lg.id, lg.league_id, lg.game_class)
                for lg in session.query(League).filter(League.season_id == season_id).all()
            ]

        logger.info(f"Processing {len(league_rows)} leagues...")

        for league_db_id, league_id, game_class in league_rows:
            # 3. Index groups
            g_count = self.index_groups_for_league(
                league_db_id, season_id, league_id, game_class, force=force
            )
            stats["groups"] += g_count

            if not index_games:
                continue

            # 4. Index games – one API call per group so all divisions are fetched
            with self.db_service.session_scope() as _gs:
                group_rows = [
                    (grp.id, grp.name)
                    for grp in _gs.query(LeagueGroup).filter(
                        LeagueGroup.league_id == league_db_id
                    ).all()
                ]
            # Fall back to a single ungrouped call if no groups were stored
            if not group_rows:
                group_rows = [(None, None)]
            for grp_db_id, grp_name in group_rows:
                gm_count = self.index_games_for_league(
                    league_db_id, season_id, league_id, game_class,
                    group_name=grp_name, group_db_id=grp_db_id,
                    force=force,
                )
                stats["games"] += gm_count

        # 5. Backfill team names from rankings API (fills stubs created during game indexing)
        if index_games:
            stats["team_names"] = self.backfill_team_names(season_id, force=force)
            # Also backfill league_id / game_class on teams that were indexed
            # via the clubs path (which never sets these fields)
            self.backfill_team_league_attrs(season_id)

        # 6. Optionally index events for past games (game_date < now, regardless of stored status)
        if index_events:
            now = datetime.now(timezone.utc)
            with self.db_service.session_scope() as session:
                past_ids = [
                    (g.id, g.season_id, g.game_date)
                    for g in session.query(Game).filter(
                        Game.season_id == season_id,
                        Game.game_date < now,
                    ).all()
                ]
            logger.info(f"Fetching events for {len(past_ids)} past games...")
            for game_id, sid, gdate in past_ids:
                stats["events"] += self.index_game_events(game_id, sid, force=force, game_date=gdate)

        logger.info(f"=== LEAGUES PATH complete === stats: {stats}")
        return stats

    # ==================== FULL INDEXING ORCHESTRATION ====================
    
    def index_current_season_clubs_path(self, season_id: int = 2025, max_clubs: int = None) -> Dict[str, int]:
        """Index current season following clubs → teams → players path
        
        Args:
            season_id: Season to index (default: 2025)
            max_clubs: Maximum number of clubs to process (for testing)
        
        Returns:
            Dict with counts of indexed entities
        """
        logger.info(f"=== Starting CLUBS PATH indexing for season {season_id} ===")
        
        stats = {
            "seasons": 0,
            "clubs": 0,
            "teams": 0,
            "players": 0
        }
        
        # 1. Ensure season exists
        stats["seasons"] = self.index_seasons()
        
        # 2. Index clubs for season (first time only)
        stats["clubs"] = self.index_clubs(season_id, force=False)
        
        # 3. Get list of club IDs (detached from session)
        with self.db_service.session_scope() as session:
            club_ids = [(c.id, c.name) for c in session.query(Club).filter(Club.season_id == season_id).all()]
        
        if max_clubs:
            club_ids = club_ids[:max_clubs]
        
        logger.info(f"Processing {len(club_ids)} clubs...")
        
        # 4. Process each club in separate sessions
        for i, (club_id, club_name) in enumerate(club_ids, 1):
            logger.info(f"[{i}/{len(club_ids)}] Processing club: {club_name} (ID: {club_id})")
            
            # Index teams for this club
            teams_count, team_ids = self.index_teams_for_club(club_id, season_id)
            stats["teams"] += teams_count
            
            # Index players for each team
            for team_id in team_ids:
                players_count = self.index_players_for_team(team_id, season_id)
                stats["players"] += players_count
        
        logger.info(f"=== CLUBS PATH indexing complete ===")
        logger.info(f"Stats: {stats}")
        return stats

    # ==================== PLAYER GAME STATS PATH ====================

    _API_FAILURE_THRESHOLD = 3
    _API_SKIP_DAYS = 7

    def _fetch_player_game_stats(
        self, player_id: int, season_id: int, force: bool = False, request_timeout: int | None = None
    ) -> "_PlayerGameStatsFetchResult":
        """Phase 1: fetch and parse one player's game stats. No DB writes.

        Returns a result object; sets api_error=True only on HTTP 5xx so the
        caller can track upstream failures separately from timeouts/parse errors.
        """
        result = _PlayerGameStatsFetchResult(player_id=player_id)
        entity_id = f"player_game_stats:{player_id}:{season_id}"
        if not force and not self._should_update("player_game_stats", entity_id, max_age_hours=4):
            return result

        try:
            data = self.client.get_player_overview(player_id, season=season_id, request_timeout=request_timeout)
        except Exception as exc:
            import requests as _req
            if isinstance(exc, _req.HTTPError) and exc.response is not None and exc.response.status_code >= 500:
                logger.debug("API 5xx for player %s: %s", player_id, exc)
                result.api_error = True
            else:
                logger.debug("Could not fetch overview for player %s: %s", player_id, exc)
            return result

        regions = data.get("data", {}).get("regions", [])
        for region in regions:
            for row in region.get("rows", []):
                row_id = row.get("id")
                if not row_id:
                    continue
                cells = row.get("cells", [])
                if len(cells) < 10:
                    continue

                def _txt(idx, _c=cells):
                    v = _c[idx].get("text") if len(_c) > idx else None
                    if isinstance(v, list):
                        v = v[0] if v else None
                    return (v or "").strip()

                if _txt(6) in ("Nicht gespielt", ""):
                    continue

                def _int(idx, _c=cells):
                    try:
                        return int(_txt(idx, _c))
                    except (ValueError, TypeError):
                        return 0

                result.game_stats[row_id] = (_int(6), _int(7), _int(9))  # goals, assists, pim

        return result

    def index_player_game_stats(self, player_id: int, season_id: int, force: bool = False, request_timeout: int | None = None) -> int:
        """Update game_players.goals/assists/penalty_minutes for one player using
        GET /api/players/:id/overview (per-game breakdown).

        Overview cell layout (0-indexed):
          0 – date, 1 – location, 2 – status/time,
          3 – home team, 4 – away team, 5 – score,
          6 – goals (T), 7 – assists (A), 8 – points (P), 9 – penalty minutes (SM)

        Returns the number of game_players rows updated.
        """
        entity_id = f"player_game_stats:{player_id}:{season_id}"
        fetch_result = self._fetch_player_game_stats(player_id, season_id, force=force, request_timeout=request_timeout)
        if not fetch_result.game_stats:
            return 0

        updated = 0
        try:
            with self.db_service.session_scope() as session:
                for game_id, (goals, assists, pim) in fetch_result.game_stats.items():
                    n = (
                        session.query(GamePlayer)
                        .filter(
                            GamePlayer.game_id == game_id,
                            GamePlayer.player_id == player_id,
                        )
                        .update({"goals": goals, "assists": assists, "penalty_minutes": pim})
                    )
                    updated += n or 0
                if updated:
                    self._mark_sync_complete(session, "player_game_stats", entity_id, updated)
        except Exception as exc:
            logger.error("Failed updating game stats for player %s: %s", player_id, exc, exc_info=True)
        return updated

    def index_player_game_stats_for_season(
        self, season_id: int, force: bool = False, exact_tier: int | None = None,
        on_progress=None, max_workers: int = 5,
    ) -> int:
        """Update game_players G/A/PIM for all known players in a season.

        Args:
            season_id: Season to process.
            force: Bypass the recency check.
            exact_tier: When set (1, 2, 3 …), only process players whose team's
                league is at that specific tier.  Each tier slice has its own
                SyncStatus row so the scheduler can track them independently.
                When None, all players in the season are processed.

        Returns total game_players rows updated.
        """
        if exact_tier is not None:
            entity_type = f"player_game_stats_t{exact_tier}"
            entity_id   = f"season_game_stats:t{exact_tier}:{season_id}"
        else:
            entity_type = "player_game_stats_season"
            entity_id   = f"season_game_stats:{season_id}"

        if not force and not self._should_update(entity_type, entity_id, max_age_hours=4):
            # Bump last_sync so the scheduler's _snap_to_hour advances to the
            # *next* nightly window instead of replaying the same past window
            # every tick (mirrors the same fix in index_leagues).
            with self.db_service.session_scope() as _s:
                self._mark_sync_complete(_s, entity_type, entity_id, 0)
            return 0

        with self.db_service.session_scope() as session:
            if exact_tier is not None:
                from app.models.db_models import Team as _TTeam
                tier_team_ids = {
                    t.id for t in session.query(_TTeam)
                    .filter(_TTeam.season_id == season_id).all()
                    if league_tier(t.league_id or 0) == exact_tier
                }
                tp_ids = {
                    r[0] for r in
                    session.query(TeamPlayer.player_id)
                    .filter(
                        TeamPlayer.season_id == season_id,
                        TeamPlayer.team_id.in_(tier_team_ids),
                    ).distinct().all()
                }
                gp_ids = {
                    r[0] for r in
                    session.query(GamePlayer.player_id)
                    .filter(
                        GamePlayer.season_id == season_id,
                        GamePlayer.team_id.in_(tier_team_ids),
                    ).distinct().all()
                }
            else:
                tp_ids = {
                    r[0] for r in
                    session.query(TeamPlayer.player_id)
                    .filter(TeamPlayer.season_id == season_id)
                    .distinct().all()
                }
                gp_ids = {
                    r[0] for r in
                    session.query(GamePlayer.player_id)
                    .filter(GamePlayer.season_id == season_id)
                    .distinct().all()
                }
            player_ids = list(tp_ids | gp_ids)

        tier_lbl = f" (tier {exact_tier} only)" if exact_tier else ""
        if not player_ids:
            logger.info("No players found for season %s%s", season_id, tier_lbl)
            # Stamp the SyncStatus so the scheduler doesn't re-queue this tier
            # indefinitely when the tier genuinely has no players.
            if exact_tier is not None:
                with self.db_service.session_scope() as session:
                    self._mark_sync_complete(session, entity_type, entity_id, 0)
            return 0

        # Pre-fetch: exclude players whose API skip window is still active
        now = datetime.now(timezone.utc)
        with self.db_service.session_scope() as session:
            skip_ids = {
                r[0] for r in session.query(Player.person_id)
                .filter(Player.api_skip_until.isnot(None), Player.api_skip_until > now).all()
            }
        if skip_ids:
            logger.info("Skipping %d players with active API skip window", len(skip_ids))
        player_ids = [pid for pid in player_ids if pid not in skip_ids]

        if not player_ids:
            logger.info("No eligible players to process for season %s%s after skip filter", season_id, tier_lbl)
            with self.db_service.session_scope() as session:
                self._mark_sync_complete(session, entity_type, entity_id, 0)
            return 0

        # Per-player checkpoint: skip players whose stats were already written in a
        # previous run's Phase 2 (enables resume after a Phase 2 failure).
        if not force:
            already_synced = self.bulk_already_indexed(
                "player_game_stats",
                [f"player_game_stats:{pid}:{season_id}" for pid in player_ids],
                max_age_hours=4,
            )
            if already_synced:
                before = len(player_ids)
                player_ids = [
                    pid for pid in player_ids
                    if f"player_game_stats:{pid}:{season_id}" not in already_synced
                ]
                logger.info(
                    "Skipping %d already-synced players (checkpoint resume), %d remaining",
                    before - len(player_ids), len(player_ids),
                )

        if not player_ids:
            # All players already synced this cycle — stamp the tier and return.
            with self.db_service.session_scope() as session:
                self._mark_sync_complete(session, entity_type, entity_id, 0)
            return 0

        logger.info(
            "Updating per-game G/A/PIM for %d players in season %s%s...",
            len(player_ids), season_id, tier_lbl,
        )

        # ── Phase 1: parallel API fetches (no DB writes) ────────────────────
        completed = 0
        _lock = threading.Lock()
        fetch_results: list["_PlayerGameStatsFetchResult"] = []

        def _fetch_one(pid: int) -> "_PlayerGameStatsFetchResult":
            nonlocal completed
            result = self._fetch_player_game_stats(pid, season_id=season_id, force=force, request_timeout=10)
            with _lock:
                completed += 1
                if on_progress:
                    on_progress(int(completed / len(player_ids) * 80))
            return result

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_fetch_one, pid): pid for pid in player_ids}
            for fut in as_completed(futures):
                try:
                    fetch_results.append(fut.result())
                except Exception as exc:
                    logger.warning("player_game_stats worker error: %s", exc)

        # ── Phase 2: single sequential session for all DB writes ────────────
        total = self._run_phase2(
            fetch_results=fetch_results,
            season_id=season_id,
            entity_type=entity_type,
            entity_id=entity_id,
            exact_tier=exact_tier,
            now=now,
        )

        if on_progress:
            on_progress(100)
        logger.info(
            "\u2713 Updated %d game_players rows with G/A/PIM for season %s%s",
            total, season_id, tier_lbl,
        )
        return total

    # Maximum players to write per Phase 2 batch.  Each batch is its own
    # session_scope(), so the SQLite write lock is held for seconds, not
    # minutes, even when processing thousands of players.
    _PHASE2_BATCH_SIZE = 300

    # Maximum players to write per player-stats Phase 2 batch.
    _PLAYER_STATS_PHASE2_BATCH_SIZE = 300

    def _run_phase2(
        self,
        fetch_results: list,
        season_id: int,
        entity_type: str,
        entity_id: str,
        exact_tier: Optional[int],
        now: datetime,
    ) -> int:
        """Phase 2: write player game stats in small batches to limit lock time.

        Each batch of _PHASE2_BATCH_SIZE players gets its own session_scope()
        so the SQLite write lock is held for only a few seconds per batch.
        Per-player SyncStatus rows are committed per batch, enabling checkpoint
        resume if a later batch fails.

        Returns total game_players rows updated.
        """
        total = 0
        for batch_start in range(0, len(fetch_results), self._PHASE2_BATCH_SIZE):
            batch = fetch_results[batch_start : batch_start + self._PHASE2_BATCH_SIZE]
            with self.db_service.session_scope() as session:
                for result in batch:
                    pid = result.player_id
                    entity_id_p = f"player_game_stats:{pid}:{season_id}"

                    if result.api_error:
                        player = session.query(Player).filter(Player.person_id == pid).first()
                        if player is not None:
                            player.api_failures = (player.api_failures or 0) + 1
                            if player.api_failures >= self._API_FAILURE_THRESHOLD:
                                player.api_skip_until = now + timedelta(days=self._API_SKIP_DAYS)
                                logger.info(
                                    "Player %s hit %d API failures; skipping until %s",
                                    pid, player.api_failures, player.api_skip_until,
                                )
                        continue

                    if not result.game_stats:
                        continue

                    updated = 0
                    for game_id, (goals, assists, pim) in result.game_stats.items():
                        n = (
                            session.query(GamePlayer)
                            .filter(
                                GamePlayer.game_id == game_id,
                                GamePlayer.player_id == pid,
                            )
                            .update({"goals": goals, "assists": assists, "penalty_minutes": pim})
                        )
                        updated += n or 0

                    if updated:
                        self._mark_sync_complete(session, "player_game_stats", entity_id_p, updated)
                        player = session.query(Player).filter(Player.person_id == pid).first()
                        if player is not None and (player.api_failures or 0) > 0:
                            player.api_failures = 0
                            player.api_skip_until = None
                        total += updated

        # Mark the tier (and optionally all tiers) complete after all batches.
        with self.db_service.session_scope() as session:
            self._mark_sync_complete(session, entity_type, entity_id, total)
            if exact_tier is None:
                for t in range(1, 7):
                    self._mark_sync_complete(
                        session,
                        f"player_game_stats_t{t}",
                        f"season_game_stats:t{t}:{season_id}",
                        total,
                    )
        return total

    def _run_player_stats_phase2(
        self,
        fetch_results: list,
        season_id: int,
        season_label: str,
        entity_type: str,
        entity_id: str,
        exact_tier,
        now,
    ) -> int:
        """Phase 2: write player seasonal stats in batches to limit SQLite lock time.

        Each batch of _PLAYER_STATS_PHASE2_BATCH_SIZE players gets its own
        session_scope() — the write lock is held for only a few seconds per batch.
        Per-player SyncStatus rows committed per batch enable checkpoint resume.
        """
        total = 0
        for batch_start in range(0, len(fetch_results), self._PLAYER_STATS_PHASE2_BATCH_SIZE):
            batch = fetch_results[batch_start : batch_start + self._PLAYER_STATS_PHASE2_BATCH_SIZE]
            with self.db_service.session_scope() as session:
                staged: dict = {}
                for result in batch:
                    pid = result.player_id
                    entity_id_p = f"player_stats:{pid}:{season_id}"

                    if result.api_error:
                        player = session.query(Player).filter(Player.person_id == pid).first()
                        if player is not None:
                            player.api_failures = (player.api_failures or 0) + 1
                            if player.api_failures >= self._API_FAILURE_THRESHOLD:
                                player.api_skip_until = now + timedelta(days=self._API_SKIP_DAYS)
                                logger.info(
                                    "player_stats: player %s hit %d API failures; skipping until %s",
                                    pid, player.api_failures, player.api_skip_until,
                                )
                        continue

                    n = self._apply_player_stats_result(
                        session, pid, result.raw_data, season_id, season_label, staged
                    )
                    # Stamp checkpoint even when n == 0 (fetched OK, just no rows this season).
                    # Only api_error players are skipped — they should be retried next run.
                    self._mark_sync_complete(session, "player_stats", entity_id_p, n)
                    # Reset failure counter on any successful fetch (n==0 is a valid terminal
                    # state for a player with no seasonal stats — unlike player_game_stats where
                    # 0 rows may mean "not indexed yet").
                    player = session.query(Player).filter(Player.person_id == pid).first()
                    if player is not None and (player.api_failures or 0) > 0:
                        player.api_failures = 0
                        player.api_skip_until = None
                    total += n

        with self.db_service.session_scope() as session:
            self._mark_sync_complete(session, entity_type, entity_id, total)
            if exact_tier is None:
                for t in range(1, 7):
                    self._mark_sync_complete(
                        session,
                        f"player_stats_t{t}",
                        f"season_player_stats:t{t}:{season_id}",
                        total,
                    )
        return total

    # ==================== GAME LIFECYCLE METHODS ====================

    def _fetch_game_metadata(self, game_api_id: int) -> "dict | None":
        """Fetch game metadata from the API.

        Parses the /api/games/{id} details response into a normalised dict with
        keys: status, date, time, venue, referee_1, referee_2.
        Returns None if the game is not found or the response is empty.
        """
        try:
            details = self.client.get_game_details(game_api_id)
        except Exception:
            return None

        if not details:
            return None

        _rows = (details.get("data", {}).get("regions") or [{}])[0].get("rows", [])
        result: dict = {}

        if _rows:
            _cells = _rows[0].get("cells", [])

            def _dcell(idx: int) -> str:
                if len(_cells) <= idx:
                    return ""
                v = _cells[idx].get("text", "")
                return (v[0] if isinstance(v, list) else v or "").strip()

            # Column layout: 0=home_logo 1=home_name 2=away_logo 3=away_name
            # 4=result 5=date 6=time 7=location 8=first_referee 9=second_referee 10=spectators
            _result_text = _dcell(4)
            
            if _result_text and re.search(r'\d+\s*:\s*\d+', _result_text):
                result["status"] = "finished"
            else:
                result["status"] = "scheduled"

            _date_str = _dcell(5)
            _time_str = _dcell(6)
            if _date_str:
                _dt_str = f"{_date_str} {_time_str}".strip()
                for _fmt in ("%d.%m.%Y %H:%M", "%d.%m.%y %H:%M", "%d.%m.%Y", "%d.%m.%y"):
                    try:
                        result["date"] = datetime.strptime(_dt_str, _fmt)
                        result["time"] = _time_str or None
                        break
                    except ValueError:
                        pass

            venue = _dcell(7)
            if venue:
                result["venue"] = venue
            ref1 = _dcell(8)
            if ref1:
                result["referee_1"] = ref1
            ref2 = _dcell(9)
            if ref2:
                result["referee_2"] = ref2

        return result or None

    def _get_league_groups_for_season(self, season_id: int, session) -> list:
        """Return all LeagueGroup rows for the given season.

        LeagueGroup has no direct season_id column; it links to League which
        has season_id.
        """
        from sqlalchemy import select
        from app.models.db_models import LeagueGroup, League
        return session.execute(
            select(LeagueGroup).join(League, LeagueGroup.league_id == League.id).where(
                League.season_id == season_id
            )
        ).scalars().all()

    def index_upcoming_games(self, season_id: int, force: bool = False) -> int:
        """Poll upcoming games for schedule updates.

        Uses the same batch league→group→games fetch as index_leagues_path
        (one API call per round, not one per game) to refresh game statuses.
        After the batch refresh, does a pure-DB scan to flip any newly-finished
        games from upcoming → post_game.

        Returns count of games transitioned to post_game.
        """
        from datetime import timedelta
        from app.models.db_models import Game, _utcnow
        from app.services.game_completeness import _resolve_game_tier, _is_game_complete

        # ── Phase 1: batch-refresh all game statuses via league→group round calls ──
        # This reuses index_games_for_league (force=True so TTL is bypassed),
        # updating game_date, status, score, venue, referees for ALL games in the
        # season in O(rounds) API calls instead of O(games) calls.
        with self.db_service.session_scope() as session:
            league_rows = [
                (lg.id, lg.league_id, lg.game_class)
                for lg in session.query(League).filter(
                    League.season_id == season_id
                ).all()
            ]

        games_refreshed = 0
        for league_db_id, league_id, game_class in league_rows:
            with self.db_service.session_scope() as _gs:
                group_rows = [
                    (grp.id, grp.name)
                    for grp in _gs.query(LeagueGroup).filter(
                        LeagueGroup.league_id == league_db_id
                    ).all()
                ]
            if not group_rows:
                group_rows = [(None, None)]
            for grp_db_id, grp_name in group_rows:
                games_refreshed += self.index_games_for_league(
                    league_db_id, season_id, league_id, game_class,
                    group_name=grp_name, group_db_id=grp_db_id,
                    force=True,
                )

        # ── Phase 2: pure-DB scan — flip finished games from upcoming → post_game ──
        transitioned = 0
        now = _utcnow()
        with self.db_service.session_scope() as session:
            stuck = session.query(Game).filter(
                Game.season_id == season_id,
                Game.completeness_status == "upcoming",
                Game.status == "finished",
            ).all()
            for game in stuck:
                game.completeness_status = "post_game"
                deadline = (
                    (game.game_date + timedelta(days=3))
                    if game.game_date
                    else (now + timedelta(days=3))
                )
                if game.give_up_at is None:
                    game.give_up_at = deadline
                tier = _resolve_game_tier(game, session)
                _, missing = _is_game_complete(game, tier, session)
                game.incomplete_fields = missing
                game.completeness_checked_at = now
                transitioned += 1

        logger.info(
            "[upcoming_games] season=%s refreshed=%d games, transitioned=%d to post_game",
            season_id, games_refreshed, transitioned,
        )
        return transitioned

    def _fetch_and_store_game_data(self, game, session) -> None:
        """Fetch and store all available data for a single game (events, lineup, score, referees, spectators).

        Best-effort: individual fetch failures are tolerated.
        """
        try:
            self.index_game_events(game.id, game.season_id, force=True, game_date=game.game_date)
        except Exception:
            pass
        try:
            self.index_game_lineup(game.id, game.season_id, force=True, game_date=game.game_date)
        except Exception:
            pass
        try:
            meta = self._fetch_game_metadata(game.id)
            if meta:
                if meta.get("referee_1"):
                    game.referee_1 = meta["referee_1"]
                if meta.get("referee_2"):
                    game.referee_2 = meta["referee_2"]
                if meta.get("venue"):
                    game.venue = meta["venue"]
        except Exception:
            pass

    def index_post_game_completion(self, season_id: int, force: bool = False) -> int:
        """Process post_game games: fetch full data, check completeness, transition state.

        Args:
            season_id: The season to process
            force: Reserved for future forced reprocessing of complete games

        Returns count of games transitioned (to complete or abandoned).
        """
        from datetime import timedelta
        from sqlalchemy import select
        from app.models.db_models import Game, GameSyncFailure, _utcnow
        from app.services.game_completeness import _resolve_game_tier, _is_game_complete

        transitioned = 0
        now = _utcnow()

        # Step 1: Process manual retries (GameSyncFailure rows with can_retry=True)
        with self.db_service.session_scope() as session:
            retry_failures = session.execute(
                select(GameSyncFailure).where(GameSyncFailure.can_retry == True, GameSyncFailure.season_id == season_id)
            ).scalars().all()
            for failure in retry_failures:
                game = session.get(Game, failure.game_id)
                if game is None:
                    continue
                game.completeness_status = "post_game"
                game.give_up_at = now + timedelta(days=3)
                game.incomplete_fields = None
                failure.retried_at = now
                failure.can_retry = False

        # Step 2: Process all post_game games
        now_naive = now.replace(tzinfo=None)
        with self.db_service.session_scope() as session:
            games = session.execute(
                select(Game).where(
                    Game.season_id == season_id,
                    Game.completeness_status == "post_game",
                )
            ).scalars().all()

            for game in games:
                # Fetch full game data from API
                try:
                    self._fetch_and_store_game_data(game, session)
                except Exception:
                    pass  # log but continue; completeness check still runs

                tier = _resolve_game_tier(game, session)
                is_complete, missing = _is_game_complete(game, tier, session)
                game.completeness_checked_at = now

                if is_complete:
                    game.completeness_status = "complete"
                    game.incomplete_fields = None
                    transitioned += 1
                elif game.give_up_at is not None and now_naive >= game.give_up_at.replace(tzinfo=None):
                    game.completeness_status = "abandoned"
                    game.incomplete_fields = missing
                    failure = session.execute(
                        select(GameSyncFailure).where(GameSyncFailure.game_id == game.id)
                    ).scalar_one_or_none()
                    if failure is None:
                        session.add(GameSyncFailure(
                            game_id=game.id,
                            season_id=game.season_id,
                            abandoned_at=now,
                            missing_fields=missing,
                            can_retry=False,
                        ))
                    else:
                        failure.abandoned_at = now
                        failure.missing_fields = missing
                        failure.can_retry = False
                    transitioned += 1
                else:
                    game.incomplete_fields = missing

        return transitioned

    def get_indexing_stats(self) -> Dict[str, Any]:
        """Get current indexing statistics

        Returns:
            Dict with entity counts and sync status
        """
        with self.db_service.session_scope() as session:
            return {
                "seasons": session.query(func.count(Season.id)).scalar(),
                "clubs": session.query(Club).count(),  # Use count() for composite PK
                "teams": session.query(func.count(Team.id)).scalar(),
                "players": session.query(func.count(Player.person_id)).scalar(),
                "team_players": session.query(func.count(TeamPlayer.id)).scalar(),
                "leagues": session.query(func.count(League.id)).scalar(),
                "games": session.query(func.count(Game.id)).scalar(),
                "last_updated": datetime.now(timezone.utc).isoformat()
            }


# Global indexer instance
_indexer: DataIndexer = None


def get_data_indexer() -> DataIndexer:
    """Get the global data indexer instance"""
    global _indexer
    if _indexer is None:
        _indexer = DataIndexer()
    return _indexer

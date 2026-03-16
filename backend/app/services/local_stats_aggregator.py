"""Local aggregation of PlayerStatistics from GamePlayer/GameEvent rows.

For tiers 1–3 where game data is complete (completeness_status='complete'),
compute PlayerStatistics directly from stored per-game data instead of
calling the per-player API endpoint.

Penalty breakdown (pen_2min/pen_5min/pen_10min/pen_match) is only computed
for T1/T2 because T3 games don't include detailed event data.
plus_minus is not computed (requires ice-time tracking not available locally).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.db_models import (
    Game,
    GameEvent,
    GamePlayer,
    League,
    LeagueGroup,
    Player as PlayerModel,
    PlayerStatistics,
    UnresolvedPlayerEvent,
)
logger = logging.getLogger(__name__)


def _get_league_tiers() -> dict:
    from app.services.data_indexer import LEAGUE_TIERS  # lazy to avoid circular import
    return LEAGUE_TIERS

_PEN_BREAKDOWN_TIERS = {1, 2}

_BUCKET_MINUTES: dict[str, int] = {"2min": 2, "5min": 5, "10min": 10, "match": 5}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _pen_bucket(event_type: str) -> str | None:
    et = event_type.lower()
    if "2'" in et:
        return "2min"
    if "5'" in et:
        return "5min"
    if "10'" in et:
        return "10min"
    if "match" in et or "technische" in et:
        return "match"
    return None


def _player_name_from_event(event: GameEvent) -> str | None:
    if event.raw_data and isinstance(event.raw_data, dict):
        return event.raw_data.get("player") or None
    return None


def _resolve_tier_and_abbrev(game: Game, session: Session) -> tuple[int, str] | None:
    """Return (tier, league_abbrev) for a game, or None if not resolvable."""
    if game.group_id is None:
        return None
    group = session.get(LeagueGroup, game.group_id)
    if group is None:
        return None
    league = session.get(League, group.league_id)
    if league is None:
        return None
    tier = _get_league_tiers().get(league.league_id, 6)
    abbrev = (league.name or "unknown")[:20]
    return tier, abbrev


def aggregate_player_stats_for_season(
    db_service,
    season_id: int,
    tiers: Sequence[int] = (1, 2, 3),
) -> int:
    """Aggregate PlayerStatistics from local game data for the given tiers.

    Only processes games with completeness_status='complete'.
    Upserts PlayerStatistics rows. Creates UnresolvedPlayerEvent rows
    for penalty events where the player name cannot be matched.

    Returns the number of PlayerStatistics rows created or updated.
    """
    tiers_set = set(tiers)
    updated = 0

    with db_service.session_scope() as session:
        games = (
            session.query(Game)
            .filter(
                Game.season_id == season_id,
                Game.completeness_status == "complete",
                Game.group_id.isnot(None),
            )
            .all()
        )

        # Resolve tier+abbrev per game, filter to target tiers
        tier_games: list[tuple[int, int, str]] = []  # (game_id, tier, abbrev)
        for game in games:
            result = _resolve_tier_and_abbrev(game, session)
            if result is not None:
                tier, abbrev = result
                if tier in tiers_set:
                    tier_games.append((game.id, tier, abbrev))

        if not tier_games:
            return 0

        game_ids = [gid for gid, _, _ in tier_games]
        tier_by_game = {gid: t for gid, t, _ in tier_games}
        abbrev_by_game = {gid: a for gid, _, a in tier_games}

        # ── Step 1: Aggregate from GamePlayer ──
        rows = (
            session.query(
                GamePlayer.player_id,
                GamePlayer.team_id,
                func.count(GamePlayer.game_id).label("games_played"),
                func.coalesce(func.sum(GamePlayer.goals), 0).label("goals"),
                func.coalesce(func.sum(GamePlayer.assists), 0).label("assists"),
                func.coalesce(func.sum(GamePlayer.penalty_minutes), 0).label("penalty_minutes"),
            )
            .filter(
                GamePlayer.season_id == season_id,
                GamePlayer.game_id.in_(game_ids),
            )
            .group_by(GamePlayer.player_id, GamePlayer.team_id)
            .all()
        )

        # Map (player_id, team_id) → first game_id (for abbrev lookup)
        first_game: dict[tuple[int, int], int] = {}
        for gp_pid, gp_tid, gp_gid in (
            session.query(GamePlayer.player_id, GamePlayer.team_id, GamePlayer.game_id)
            .filter(GamePlayer.season_id == season_id, GamePlayer.game_id.in_(game_ids))
            .all()
        ):
            if (gp_pid, gp_tid) not in first_game:
                first_game[(gp_pid, gp_tid)] = gp_gid

        # ── Step 2: Penalty breakdown from GameEvent (T1/T2 only) ──
        pen_breakdown: dict[tuple[int, int], dict[str, int]] = {}

        # Build player name → player_id lookup per (game_id, team_id)
        gp_all = (
            session.query(GamePlayer)
            .filter(GamePlayer.season_id == season_id, GamePlayer.game_id.in_(game_ids))
            .all()
        )
        player_names: dict[int, str] = {
            p.person_id: f"{p.first_name or ''} {p.last_name or ''}".strip().lower()
            for p in session.query(PlayerModel)
            .filter(PlayerModel.person_id.in_({gp.player_id for gp in gp_all}))
            .all()
        }
        # (game_id, team_id) → {lower_name: player_id}
        name_map: dict[tuple[int, int], dict[str, int]] = {}
        for gp in gp_all:
            key = (gp.game_id, gp.team_id)
            name = player_names.get(gp.player_id, "")
            if name:
                name_map.setdefault(key, {})[name] = gp.player_id

        penalty_events = (
            session.query(GameEvent)
            .filter(
                GameEvent.season_id == season_id,
                GameEvent.game_id.in_(game_ids),
                GameEvent.event_type.ilike("%'-strafe%"),
            )
            .all()
        )

        seen_unresolved: set[tuple] = set()
        for evt in penalty_events:
            if tier_by_game.get(evt.game_id) not in _PEN_BREAKDOWN_TIERS:
                continue
            bucket = _pen_bucket(evt.event_type)
            if bucket is None:
                continue
            raw_name = _player_name_from_event(evt)
            if not raw_name:
                continue
            key = (evt.game_id, evt.team_id)
            pid = name_map.get(key, {}).get(raw_name.lower())
            if pid is None:
                unresolved_key = (evt.game_id, evt.team_id, raw_name)
                if unresolved_key not in seen_unresolved:
                    seen_unresolved.add(unresolved_key)
                    existing = (
                        session.query(UnresolvedPlayerEvent)
                        .filter_by(
                            game_id=evt.game_id,
                            team_id=evt.team_id,
                            raw_name=raw_name,
                            resolved_at=None,
                        )
                        .first()
                    )
                    if existing is None:
                        session.add(
                            UnresolvedPlayerEvent(
                                game_id=evt.game_id,
                                team_id=evt.team_id,
                                season_id=evt.season_id,
                                raw_name=raw_name,
                                event_type=evt.event_type,
                                created_at=_now(),
                            )
                        )
                continue
            tid = evt.team_id
            pen_breakdown.setdefault((pid, tid), {"2min": 0, "5min": 0, "10min": 0, "match": 0})
            pen_breakdown[(pid, tid)][bucket] += 1

        # ── Step 3: Upsert PlayerStatistics ──
        now = _now()
        for row in rows:
            pid, tid = row.player_id, row.team_id
            first_gid = first_game.get((pid, tid), -1)
            abbrev = abbrev_by_game.get(first_gid, "unknown")
            breakdown = pen_breakdown.get((pid, tid), {})

            existing = (
                session.query(PlayerStatistics)
                .filter_by(player_id=pid, season_id=season_id, league_abbrev=abbrev)
                .first()
            )
            if existing is None:
                obj = PlayerStatistics(
                    player_id=pid,
                    season_id=season_id,
                    team_id=tid,
                    league_abbrev=abbrev,
                    games_played=row.games_played,
                    goals=row.goals,
                    assists=row.assists,
                    points=(row.goals or 0) + (row.assists or 0),
                    penalty_minutes=row.penalty_minutes,
                    pen_2min=breakdown.get("2min", 0),
                    pen_5min=breakdown.get("5min", 0),
                    pen_10min=breakdown.get("10min", 0),
                    pen_match=breakdown.get("match", 0),
                    computed_from_local=True,
                    local_computed_at=now,
                    last_updated=now,
                )
                session.add(obj)
            else:
                existing.games_played = row.games_played
                existing.goals = row.goals
                existing.assists = row.assists
                existing.points = (row.goals or 0) + (row.assists or 0)
                existing.penalty_minutes = row.penalty_minutes
                if breakdown:
                    existing.pen_2min = breakdown.get("2min", 0)
                    existing.pen_5min = breakdown.get("5min", 0)
                    existing.pen_10min = breakdown.get("10min", 0)
                    existing.pen_match = breakdown.get("match", 0)
                existing.computed_from_local = True
                existing.local_computed_at = now
                existing.last_updated = now
            updated += 1

        logger.info(
            "Local stats aggregation: %d PlayerStatistics rows upserted for season %s (tiers %s)",
            updated,
            season_id,
            sorted(tiers_set),
        )

    return updated


def _parse_goal_players(raw_data: dict) -> tuple[str | None, str | None]:
    """Parse scorer and optional assister from a goal event's raw_data.

    The "player" field format is either "Scorer" or "Scorer / Assister".
    Returns (scorer_name, assister_name_or_None).
    """
    raw = (raw_data or {}).get("player", "") or ""
    if "/" in raw:
        parts = raw.split("/", 1)
        return parts[0].strip() or None, parts[1].strip() or None
    return raw.strip() or None, None


def backfill_game_player_stats_from_events(
    db_service,
    season_id: int,
    tiers: Sequence[int] = (1, 2, 3),
) -> int:
    """Backfill GamePlayer.goals/assists/penalty_minutes from GameEvent rows.

    Only processes games in the target tiers where ALL GamePlayer rows for
    that game have goals IS NULL (i.e., not yet filled).

    Returns the number of GamePlayer rows updated.
    """
    tiers_set = set(tiers)
    updated = 0

    with db_service.session_scope() as session:
        # Find complete games in target tiers
        games = (
            session.query(Game)
            .filter(
                Game.season_id == season_id,
                Game.completeness_status == "complete",
                Game.group_id.isnot(None),
            )
            .all()
        )

        target_games: list[Game] = []
        for game in games:
            result = _resolve_tier_and_abbrev(game, session)
            if result is None:
                continue
            tier, _ = result
            if tier not in tiers_set:
                continue
            target_games.append(game)

        if not target_games:
            return 0

        target_game_ids = [g.id for g in target_games]

        # Only process games where NO GamePlayer row has goals already set (> 0).
        # GamePlayer.goals defaults to 0 on insert, so goals > 0 means already filled.
        eligible_game_ids: list[int] = []
        for gid in target_game_ids:
            gp_rows = (
                session.query(GamePlayer)
                .filter(GamePlayer.game_id == gid, GamePlayer.season_id == season_id)
                .all()
            )
            if not gp_rows:
                continue
            if all((gp.goals or 0) == 0 for gp in gp_rows):
                eligible_game_ids.append(gid)

        if not eligible_game_ids:
            return 0

        # Build player name → player_id map per (game_id, team_id)
        gp_all = (
            session.query(GamePlayer)
            .filter(
                GamePlayer.season_id == season_id,
                GamePlayer.game_id.in_(eligible_game_ids),
            )
            .all()
        )
        player_names: dict[int, str] = {
            p.person_id: f"{p.first_name or ''} {p.last_name or ''}".strip().lower()
            for p in session.query(PlayerModel)
            .filter(PlayerModel.person_id.in_({gp.player_id for gp in gp_all}))
            .all()
        }
        # (game_id, team_id) → {lower_name: player_id}
        name_map: dict[tuple[int, int], dict[str, int]] = {}
        for gp in gp_all:
            key = (gp.game_id, gp.team_id)
            name = player_names.get(gp.player_id, "")
            if name:
                name_map.setdefault(key, {})[name] = gp.player_id

        # Accumulate goals/assists/pim per (game_id, player_id)
        goals_acc: dict[tuple[int, int], int] = {}
        assists_acc: dict[tuple[int, int], int] = {}
        pim_acc: dict[tuple[int, int], int] = {}

        events = (
            session.query(GameEvent)
            .filter(
                GameEvent.season_id == season_id,
                GameEvent.game_id.in_(eligible_game_ids),
            )
            .all()
        )

        seen_unresolved: set[tuple] = set()

        def _add_unresolved(evt: GameEvent, raw_name: str) -> None:
            key = (evt.game_id, evt.team_id, raw_name)
            if key in seen_unresolved:
                return
            seen_unresolved.add(key)
            existing = (
                session.query(UnresolvedPlayerEvent)
                .filter_by(game_id=evt.game_id, team_id=evt.team_id,
                            raw_name=raw_name, resolved_at=None)
                .first()
            )
            if existing is None:
                session.add(UnresolvedPlayerEvent(
                    game_id=evt.game_id,
                    team_id=evt.team_id,
                    season_id=evt.season_id,
                    raw_name=raw_name,
                    event_type=evt.event_type,
                    created_at=_now(),
                ))

        def _resolve_name(evt: GameEvent, raw_name: str | None) -> int | None:
            if not raw_name:
                return None
            key = (evt.game_id, evt.team_id)
            pid = name_map.get(key, {}).get(raw_name.lower())
            if pid is None:
                # Try across all teams in the game
                for (gid, _tid), nmap in name_map.items():
                    if gid == evt.game_id:
                        pid = nmap.get(raw_name.lower())
                        if pid is not None:
                            break
            return pid

        for evt in events:
            et_lower = evt.event_type.lower() if evt.event_type else ""

            if "torschütze" in et_lower or "eigentor" in et_lower:
                scorer_name, assister_name = _parse_goal_players(evt.raw_data or {})
                is_own_goal = "eigentor" in et_lower

                if scorer_name:
                    pid = _resolve_name(evt, scorer_name)
                    if pid is not None:
                        key = (evt.game_id, pid)
                        goals_acc[key] = goals_acc.get(key, 0) + 1
                    else:
                        _add_unresolved(evt, scorer_name)

                if assister_name and not is_own_goal:
                    pid = _resolve_name(evt, assister_name)
                    if pid is not None:
                        key = (evt.game_id, pid)
                        assists_acc[key] = assists_acc.get(key, 0) + 1
                    else:
                        _add_unresolved(evt, assister_name)

            elif "'-strafe" in et_lower:
                bucket = _pen_bucket(evt.event_type)
                if bucket is None:
                    continue
                raw_name = _player_name_from_event(evt)
                if not raw_name:
                    continue
                pid = _resolve_name(evt, raw_name)
                if pid is not None:
                    key = (evt.game_id, pid)
                    pim_acc[key] = pim_acc.get(key, 0) + _BUCKET_MINUTES[bucket]
                else:
                    _add_unresolved(evt, raw_name)

        # Write back to GamePlayer rows (only those with goals == 0, i.e. not yet backfilled)
        for gp in gp_all:
            if (gp.goals or 0) != 0:
                continue
            key = (gp.game_id, gp.player_id)
            gp.goals = goals_acc.get(key, 0)
            gp.assists = assists_acc.get(key, 0)
            gp.penalty_minutes = pim_acc.get(key, 0)
            updated += 1

        logger.info(
            "Backfill game player stats: %d GamePlayer rows updated for season %s (tiers %s)",
            updated,
            season_id,
            sorted(tiers_set),
        )

    return updated

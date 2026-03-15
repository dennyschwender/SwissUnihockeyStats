"""Game completeness checks for the lifecycle scheduler."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db_models import Game, GameEvent, GamePlayer, League, LeagueGroup
from app.services.data_indexer import LEAGUE_TIERS

TIER_COMPLETENESS_FIELDS: dict[int, set[str]] = {
    1: {"score", "referees", "spectators", "events", "lineup", "best_players"},
    2: {"score", "referees", "spectators", "events", "lineup", "best_players"},
    3: {"score"},
    4: {"score"},
    5: {"score"},
    6: {"score"},
}

_DEFAULT_FIELDS = {"score"}


def _resolve_game_tier(game: Game, session: Session) -> int:
    """Resolve tier for a game via group_id → LeagueGroup → League → LEAGUE_TIERS."""
    if game.group_id is None:
        return 6
    group = session.get(LeagueGroup, game.group_id)
    if group is None:
        return 6
    league = session.get(League, group.league_id)
    if league is None:
        return 6
    return LEAGUE_TIERS.get(league.league_id, 6)


def _is_game_complete(game: Game, tier: int, session: Session) -> tuple[bool, list[str]]:
    """Check if a game has all required fields for its tier. Returns (is_complete, missing_fields)."""
    required = TIER_COMPLETENESS_FIELDS.get(tier, _DEFAULT_FIELDS)
    missing: list[str] = []

    if "score" in required:
        if game.home_score is None or game.away_score is None:
            missing.append("score")

    if "referees" in required:
        if game.referee_1 is None:
            missing.append("referees")

    if "spectators" in required:
        if game.spectators is None:
            missing.append("spectators")

    if "events" in required:
        row = session.execute(
            select(GameEvent)
            .where(GameEvent.game_id == game.id, GameEvent.event_type != "best_player")
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            missing.append("events")

    if "lineup" in required:
        row = session.execute(
            select(GamePlayer).where(GamePlayer.game_id == game.id).limit(1)
        ).scalar_one_or_none()
        if row is None:
            missing.append("lineup")

    if "best_players" in required:
        row = session.execute(
            select(GameEvent)
            .where(GameEvent.game_id == game.id, GameEvent.event_type == "best_player")
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            missing.append("best_players")

    return (len(missing) == 0, missing)

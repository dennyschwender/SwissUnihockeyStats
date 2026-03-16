"""Tests for game completeness service."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.db_models import Base, Game, GameEvent, GamePlayer, Player, Season, Club, Team
from app.services.game_completeness import (
    TIER_COMPLETENESS_FIELDS,
    _is_game_complete,
    _resolve_game_tier,
)


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


_SEASON_ID = 2025
_CLUB_H_ID = 10
_CLUB_A_ID = 11
_TEAM_H_ID = 100
_TEAM_A_ID = 101
_PLAYER_IDS = [1, 2, 3, 4, 5]


def _ensure_base_rows(session):
    """Create season/club/team/player rows if they don't already exist in this session."""
    if session.get(Season, _SEASON_ID) is None:
        session.add(Season(id=_SEASON_ID, text="2025"))
        session.flush()
    if session.get(Club, (_CLUB_H_ID, _SEASON_ID)) is None:
        session.add(Club(id=_CLUB_H_ID, season_id=_SEASON_ID, name="Home Club"))
        session.flush()
    if session.get(Club, (_CLUB_A_ID, _SEASON_ID)) is None:
        session.add(Club(id=_CLUB_A_ID, season_id=_SEASON_ID, name="Away Club"))
        session.flush()
    if session.get(Team, (_TEAM_H_ID, _SEASON_ID)) is None:
        session.add(Team(id=_TEAM_H_ID, season_id=_SEASON_ID, name="Home", club_id=_CLUB_H_ID))
        session.flush()
    if session.get(Team, (_TEAM_A_ID, _SEASON_ID)) is None:
        session.add(Team(id=_TEAM_A_ID, season_id=_SEASON_ID, name="Away", club_id=_CLUB_A_ID))
        session.flush()
    for pid in _PLAYER_IDS:
        if session.get(Player, pid) is None:
            session.add(Player(person_id=pid, full_name=f"Player {pid}"))
    session.flush()


def _make_game(session, api_id=1, status="finished", home_score=None, away_score=None):
    _ensure_base_rows(session)
    game = Game(
        id=api_id,
        season_id=_SEASON_ID,
        home_team_id=_TEAM_H_ID,
        away_team_id=_TEAM_A_ID,
        status=status,
        home_score=home_score,
        away_score=away_score,
    )
    session.add(game)
    session.flush()
    return game


# ── TIER_COMPLETENESS_FIELDS ────────────────────────────────────────────────


def test_tier1_requires_all_fields():
    assert TIER_COMPLETENESS_FIELDS[1] == {
        "score",
        "referees",
        "spectators",
        "events",
        "lineup",
        "best_players",
    }


def test_tier3_requires_only_score():
    assert TIER_COMPLETENESS_FIELDS[3] == {"score"}


def test_tier6_requires_only_score():
    assert TIER_COMPLETENESS_FIELDS[6] == {"score"}


# ── _resolve_game_tier ──────────────────────────────────────────────────────


def test_resolve_tier_null_group_id_returns_6(session):
    game = _make_game(session, api_id=10)
    assert game.group_id is None
    assert _resolve_game_tier(game, session) == 6


def test_resolve_tier_missing_league_group_returns_6(session):
    game = _make_game(session, api_id=11)
    game.group_id = 9999  # non-existent
    session.flush()
    assert _resolve_game_tier(game, session) == 6


# ── _is_game_complete — tier 6 (score only) ─────────────────────────────────


def test_score_present_tier6_complete(session):
    game = _make_game(session, api_id=20, home_score=3, away_score=1)
    ok, missing = _is_game_complete(game, 6, session)
    assert ok is True
    assert missing == []


def test_score_missing_tier6_incomplete(session):
    game = _make_game(session, api_id=21)
    ok, missing = _is_game_complete(game, 6, session)
    assert ok is False
    assert "score" in missing


def test_only_home_score_tier6_incomplete(session):
    game = _make_game(session, api_id=22, home_score=2)
    ok, missing = _is_game_complete(game, 6, session)
    assert ok is False
    assert "score" in missing


# ── _is_game_complete — tier 1 (all fields) ─────────────────────────────────


def test_tier1_all_fields_present_complete(session):
    game = _make_game(session, api_id=30, home_score=2, away_score=0)
    game.referee_1 = "Ref A"
    game.spectators = 500
    session.flush()
    # Add a non-best_player event
    session.add(
        GameEvent(
            game_id=game.id,
            event_type="goal",
            period=1,
            team_id=game.home_team_id,
            season_id=_SEASON_ID,
        )
    )
    # Add a best_player event
    session.add(
        GameEvent(
            game_id=game.id,
            event_type="best_player",
            period=0,
            team_id=game.home_team_id,
            season_id=_SEASON_ID,
        )
    )
    # Add lineup entry
    session.add(
        GamePlayer(
            game_id=game.id,
            team_id=game.home_team_id,
            player_id=1,
            season_id=_SEASON_ID,
            is_home_team=True,
        )
    )
    session.flush()
    ok, missing = _is_game_complete(game, 1, session)
    assert ok is True
    assert missing == []


def test_tier1_missing_referees(session):
    game = _make_game(session, api_id=31, home_score=2, away_score=0)
    game.spectators = 500
    session.flush()
    session.add(
        GameEvent(
            game_id=game.id,
            event_type="goal",
            period=1,
            team_id=game.home_team_id,
            season_id=_SEASON_ID,
        )
    )
    session.add(
        GameEvent(
            game_id=game.id,
            event_type="best_player",
            period=0,
            team_id=game.home_team_id,
            season_id=_SEASON_ID,
        )
    )
    session.add(
        GamePlayer(
            game_id=game.id,
            team_id=game.home_team_id,
            player_id=2,
            season_id=_SEASON_ID,
            is_home_team=True,
        )
    )
    session.flush()
    ok, missing = _is_game_complete(game, 1, session)
    assert ok is False
    assert "referees" in missing


def test_tier1_missing_events(session):
    game = _make_game(session, api_id=32, home_score=2, away_score=0)
    game.referee_1 = "Ref B"
    game.spectators = 500
    session.flush()
    # No non-best_player event
    session.add(
        GameEvent(
            game_id=game.id,
            event_type="best_player",
            period=0,
            team_id=game.home_team_id,
            season_id=_SEASON_ID,
        )
    )
    session.add(
        GamePlayer(
            game_id=game.id,
            team_id=game.home_team_id,
            player_id=3,
            season_id=_SEASON_ID,
            is_home_team=True,
        )
    )
    session.flush()
    ok, missing = _is_game_complete(game, 1, session)
    assert ok is False
    assert "events" in missing


def test_tier1_missing_lineup(session):
    game = _make_game(session, api_id=33, home_score=2, away_score=0)
    game.referee_1 = "Ref C"
    game.spectators = 500
    session.flush()
    session.add(
        GameEvent(
            game_id=game.id,
            event_type="goal",
            period=1,
            team_id=game.home_team_id,
            season_id=_SEASON_ID,
        )
    )
    session.add(
        GameEvent(
            game_id=game.id,
            event_type="best_player",
            period=0,
            team_id=game.home_team_id,
            season_id=_SEASON_ID,
        )
    )
    # No GamePlayer
    session.flush()
    ok, missing = _is_game_complete(game, 1, session)
    assert ok is False
    assert "lineup" in missing


def test_tier1_missing_best_players(session):
    game = _make_game(session, api_id=34, home_score=2, away_score=0)
    game.referee_1 = "Ref D"
    game.spectators = 500
    session.flush()
    session.add(
        GameEvent(
            game_id=game.id,
            event_type="goal",
            period=1,
            team_id=game.home_team_id,
            season_id=_SEASON_ID,
        )
    )
    # No best_player event
    session.add(
        GamePlayer(
            game_id=game.id,
            team_id=game.home_team_id,
            player_id=4,
            season_id=_SEASON_ID,
            is_home_team=True,
        )
    )
    session.flush()
    ok, missing = _is_game_complete(game, 1, session)
    assert ok is False
    assert "best_players" in missing


def test_tier1_missing_spectators(session):
    game = _make_game(session, api_id=36, home_score=2, away_score=0)
    game.referee_1 = "Ref E"
    # spectators deliberately left as None
    session.flush()
    session.add(
        GameEvent(
            game_id=game.id,
            event_type="goal",
            period=1,
            team_id=game.home_team_id,
            season_id=_SEASON_ID,
        )
    )
    session.add(
        GameEvent(
            game_id=game.id,
            event_type="best_player",
            period=0,
            team_id=game.home_team_id,
            season_id=_SEASON_ID,
        )
    )
    session.add(
        GamePlayer(
            game_id=game.id,
            team_id=game.home_team_id,
            player_id=5,
            season_id=_SEASON_ID,
            is_home_team=True,
        )
    )
    session.flush()
    ok, missing = _is_game_complete(game, 1, session)
    assert ok is False
    assert "spectators" in missing


def test_missing_fields_list_contains_all_missing(session):
    game = _make_game(session, api_id=35)  # no score, no anything
    ok, missing = _is_game_complete(game, 1, session)
    assert ok is False
    assert set(missing) == {"score", "referees", "spectators", "events", "lineup", "best_players"}

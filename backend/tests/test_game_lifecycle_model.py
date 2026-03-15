"""Tests for Game lifecycle columns and GameSyncFailure model."""
import pytest
from datetime import timedelta
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models.db_models import Base, Game, GameSyncFailure, _utcnow


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


def _get_valid_season_and_teams(session):
    """Create minimal Season, Club, Team rows needed for a Game FK."""
    from app.models.db_models import Season, Club, Team
    # Season.id is the API season ID (primary key), text is display name
    season = Season(id=1, text="2025/26")
    session.add(season)
    session.flush()
    # Club has composite PK (id, season_id)
    club_h = Club(id=10, season_id=season.id, name="Home Club")
    club_a = Club(id=11, season_id=season.id, name="Away Club")
    session.add_all([club_h, club_a])
    session.flush()
    # Team has composite PK (id, season_id)
    team_h = Team(id=100, season_id=season.id, club_id=club_h.id, name="Home Team")
    team_a = Team(id=101, season_id=season.id, club_id=club_a.id, name="Away Team")
    session.add_all([team_h, team_a])
    session.flush()
    return season, team_h, team_a


def test_game_has_completeness_status_column(engine):
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("games")}
    assert "completeness_status" in cols


def test_game_has_incomplete_fields_column(engine):
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("games")}
    assert "incomplete_fields" in cols


def test_game_has_give_up_at_column(engine):
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("games")}
    assert "give_up_at" in cols


def test_game_has_completeness_checked_at_column(engine):
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("games")}
    assert "completeness_checked_at" in cols


def test_game_completeness_status_default(session):
    season, team_h, team_a = _get_valid_season_and_teams(session)
    game = Game(
        id=999,
        season_id=season.id,
        home_team_id=team_h.id,
        away_team_id=team_a.id,
    )
    session.add(game)
    session.flush()
    assert game.completeness_status == "upcoming"


def test_game_incomplete_fields_nullable(session):
    season, team_h, team_a = _get_valid_season_and_teams(session)
    game = Game(
        id=998,
        season_id=season.id,
        home_team_id=team_h.id,
        away_team_id=team_a.id,
    )
    session.add(game)
    session.flush()
    assert game.incomplete_fields is None


def test_game_incomplete_fields_stores_list(session):
    season, team_h, team_a = _get_valid_season_and_teams(session)
    game = Game(
        id=997,
        season_id=season.id,
        home_team_id=team_h.id,
        away_team_id=team_a.id,
        incomplete_fields=["events", "lineup"],
    )
    session.add(game)
    session.flush()
    session.expire(game)
    reloaded = session.get(Game, game.id)
    assert reloaded.incomplete_fields == ["events", "lineup"]


def test_game_sync_failure_table_exists(engine):
    inspector = inspect(engine)
    assert "game_sync_failures" in inspector.get_table_names()


def test_game_sync_failure_can_retry_default_false(session):
    season, team_h, team_a = _get_valid_season_and_teams(session)
    game = Game(
        id=996,
        season_id=season.id,
        home_team_id=team_h.id,
        away_team_id=team_a.id,
    )
    session.add(game)
    session.flush()
    failure = GameSyncFailure(
        game_id=game.id,
        season_id=season.id,
        missing_fields=["events"],
    )
    session.add(failure)
    session.flush()
    assert failure.can_retry is False


def test_game_sync_failure_missing_fields_stores_list(session):
    season, team_h, team_a = _get_valid_season_and_teams(session)
    game = Game(
        id=995,
        season_id=season.id,
        home_team_id=team_h.id,
        away_team_id=team_a.id,
    )
    session.add(game)
    session.flush()
    failure = GameSyncFailure(
        game_id=game.id,
        season_id=season.id,
        missing_fields=["referees", "spectators"],
    )
    session.add(failure)
    session.flush()
    session.expire(failure)
    reloaded = session.get(GameSyncFailure, failure.id)
    assert reloaded.missing_fields == ["referees", "spectators"]


def test_game_sync_failure_abandoned_at_set_automatically(session):
    from datetime import timedelta
    from app.models.db_models import _utcnow
    season, team_h, team_a = _get_valid_season_and_teams(session)
    before = _utcnow()
    game = Game(
        id=994,
        season_id=season.id,
        home_team_id=team_h.id,
        away_team_id=team_a.id,
    )
    session.add(game)
    session.flush()
    failure = GameSyncFailure(
        game_id=game.id,
        season_id=season.id,
        missing_fields=[],
    )
    session.add(failure)
    session.flush()
    after = _utcnow()
    assert failure.abandoned_at is not None
    assert before - timedelta(seconds=1) <= failure.abandoned_at <= after + timedelta(seconds=1)

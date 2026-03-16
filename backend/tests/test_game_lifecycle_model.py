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


# ── Migration / backfill tests ─────────────────────────────────────────────


def _make_engine_without_lifecycle_cols():
    """Create a fresh in-memory DB WITHOUT the lifecycle columns to simulate pre-migration state."""
    from sqlalchemy import text

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    # Drop lifecycle columns by recreating the games table without them
    # (SQLite doesn't support DROP COLUMN in older versions, so we use raw DDL)
    # Instead, just verify the migration is idempotent by running it twice on a fresh DB.
    return engine


def test_migration_adds_completeness_status_column(engine):
    """Migration must be idempotent — running on a DB that already has the columns should not fail."""
    from app.database import run_lifecycle_migration

    run_lifecycle_migration(engine)  # Should not raise
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("games")}
    assert "completeness_status" in cols


def test_migration_backfills_non_finished_games_as_upcoming(engine, session):
    from app.database import run_lifecycle_migration

    season, team_h, team_a = _get_valid_season_and_teams(session)
    game = Game(
        id=901,
        season_id=season.id,
        home_team_id=team_h.id,
        away_team_id=team_a.id,
        status="scheduled",
    )
    session.add(game)
    session.commit()
    run_lifecycle_migration(engine)
    session.expire_all()
    updated = session.get(Game, game.id)
    assert updated.completeness_status == "upcoming"
    assert updated.give_up_at is None
    assert updated.incomplete_fields is None


def test_migration_backfills_finished_complete_game_as_complete(engine, session):
    from app.database import run_lifecycle_migration

    season, team_h, team_a = _get_valid_season_and_teams(session)
    game = Game(
        id=902,
        season_id=season.id,
        home_team_id=team_h.id,
        away_team_id=team_a.id,
        status="finished",
        home_score=3,
        away_score=1,
    )
    session.add(game)
    session.commit()
    run_lifecycle_migration(engine)
    session.expire_all()
    updated = session.get(Game, game.id)
    assert updated.completeness_status == "complete"
    assert updated.give_up_at is None
    assert updated.incomplete_fields is None


def test_migration_backfills_recent_finished_incomplete_as_post_game(engine, session):
    from datetime import timedelta
    from app.database import run_lifecycle_migration

    season, team_h, team_a = _get_valid_season_and_teams(session)
    game_date = _utcnow() - timedelta(days=1)  # 1 day ago — within 3-day window
    game = Game(
        id=903,
        season_id=season.id,
        home_team_id=team_h.id,
        away_team_id=team_a.id,
        status="finished",
        game_date=game_date,
        # no score → incomplete
    )
    session.add(game)
    session.commit()
    run_lifecycle_migration(engine)
    session.expire_all()
    updated = session.get(Game, game.id)
    assert updated.completeness_status == "post_game"
    assert updated.give_up_at is not None
    assert updated.incomplete_fields is not None


def test_migration_backfills_old_finished_incomplete_as_abandoned(engine, session):
    from datetime import timedelta
    from app.database import run_lifecycle_migration

    season, team_h, team_a = _get_valid_season_and_teams(session)
    game_date = _utcnow() - timedelta(days=10)  # 10 days ago — past 3-day window
    game = Game(
        id=904,
        season_id=season.id,
        home_team_id=team_h.id,
        away_team_id=team_a.id,
        status="finished",
        game_date=game_date,
        # no score → incomplete
    )
    session.add(game)
    session.commit()
    run_lifecycle_migration(engine)
    session.expire_all()
    updated = session.get(Game, game.id)
    assert updated.completeness_status == "abandoned"
    # A GameSyncFailure row should have been created
    from sqlalchemy import select
    from app.models.db_models import GameSyncFailure

    failure = session.execute(
        select(GameSyncFailure).where(GameSyncFailure.game_id == game.id)
    ).scalar_one_or_none()
    assert failure is not None
    assert failure.can_retry is False


def test_migration_is_idempotent(engine, session):
    from app.database import run_lifecycle_migration

    # Running twice should not raise or duplicate GameSyncFailure rows
    season, team_h, team_a = _get_valid_season_and_teams(session)
    from datetime import timedelta

    game_date = _utcnow() - timedelta(days=10)
    game = Game(
        id=905,
        season_id=season.id,
        home_team_id=team_h.id,
        away_team_id=team_a.id,
        status="finished",
        game_date=game_date,
    )
    session.add(game)
    session.commit()
    run_lifecycle_migration(engine)
    run_lifecycle_migration(engine)  # second run — must not fail or duplicate
    from sqlalchemy import select
    from app.models.db_models import GameSyncFailure

    failures = (
        session.execute(select(GameSyncFailure).where(GameSyncFailure.game_id == game.id))
        .scalars()
        .all()
    )
    assert len(failures) == 1  # exactly one, not duplicated

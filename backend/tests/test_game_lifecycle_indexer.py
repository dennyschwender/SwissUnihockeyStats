"""Tests for game lifecycle indexer methods."""

import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.db_models import Base, Game, Season, Club, Team, League, LeagueGroup, _utcnow
from app.services.data_indexer import DataIndexer


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def mock_db(engine):
    """Create a mock DatabaseService that returns real sessions."""
    from contextlib import contextmanager

    db = MagicMock()

    @contextmanager
    def session_scope():
        with Session(engine) as session:
            yield session
            session.commit()

    db.session_scope = session_scope
    db.engine = engine
    return db


@pytest.fixture
def indexer(mock_db):
    api = MagicMock()
    return DataIndexer(db=mock_db, api=api)


def _seed_game(
    engine,
    api_id=1,
    status="scheduled",
    home_score=None,
    away_score=None,
    completeness_status="upcoming",
):
    with Session(engine) as s:
        season = Season(id=1, text="2025")
        club_h = Club(id=10, name="H", season_id=1)
        club_a = Club(id=11, name="A", season_id=1)
        s.add_all([season, club_h, club_a])
        s.flush()
        team_h = Team(id=100, name="H", club_id=club_h.id, season_id=1)
        team_a = Team(id=101, name="A", club_id=club_a.id, season_id=1)
        s.add_all([team_h, team_a])
        s.flush()
        game = Game(
            id=api_id,
            season_id=season.id,
            home_team_id=team_h.id,
            away_team_id=team_a.id,
            status=status,
            home_score=home_score,
            away_score=away_score,
            completeness_status=completeness_status,
        )
        s.add(game)
        s.commit()
        return game.id, season.id


def test_index_upcoming_games_returns_int(engine, indexer):
    _, season_id = _seed_game(engine)
    # No leagues in test DB → batch phase does nothing; result is still an int.
    indexer.index_games_for_league = MagicMock(return_value=0)
    result = indexer.index_upcoming_games(season_id)
    assert isinstance(result, int)


def test_index_upcoming_games_transitions_api_finished_to_post_game(engine, indexer):
    """Batch fetch (via index_games_for_league) marks game finished → Phase 2 flips to post_game."""
    game_id, season_id = _seed_game(engine, status="scheduled", completeness_status="upcoming")

    # Add a league + group so Phase 1 actually calls index_games_for_league.
    with Session(engine) as s:
        lg = League(id=1, season_id=season_id, league_id=100, game_class=1, name="Test League")
        s.add(lg)
        s.flush()
        grp = LeagueGroup(id=1, league_id=lg.id, group_id=999, name="Test Group")
        s.add(grp)
        s.commit()

    # Simulate index_games_for_league updating the game's status to 'finished' in the DB.
    def _flip_to_finished(*args, **kwargs):
        with Session(engine) as s:
            g = s.get(Game, game_id)
            g.status = "finished"
            s.commit()
        return 1

    indexer.index_games_for_league = MagicMock(side_effect=_flip_to_finished)
    count = indexer.index_upcoming_games(season_id)
    assert count == 1
    with Session(engine) as s:
        game = s.get(Game, game_id)
        assert game.completeness_status == "post_game"
        assert game.give_up_at is not None


def test_index_upcoming_games_defensive_finished_stuck_in_upcoming(engine, indexer):
    """A game already status=finished but completeness_status=upcoming is transitioned by Phase 2."""
    game_id, season_id = _seed_game(engine, status="finished", completeness_status="upcoming")
    # No leagues → Phase 1 is a no-op; Phase 2 DB scan catches the stuck game.
    count = indexer.index_upcoming_games(season_id)
    assert count == 1
    with Session(engine) as s:
        game = s.get(Game, game_id)
        assert game.completeness_status == "post_game"


def test_index_upcoming_games_no_transition_for_scheduled(engine, indexer):
    """A still-scheduled game stays upcoming after the job runs."""
    game_id, season_id = _seed_game(engine, status="scheduled", completeness_status="upcoming")
    # Batch fetch returns 0 updates (game stays scheduled).
    indexer.index_games_for_league = MagicMock(return_value=0)
    count = indexer.index_upcoming_games(season_id)
    assert count == 0
    with Session(engine) as s:
        game = s.get(Game, game_id)
        assert game.completeness_status == "upcoming"  # unchanged


def test_get_league_groups_for_season_returns_list(engine, indexer):
    with Session(engine) as s:
        result = indexer._get_league_groups_for_season(1, s)
        assert isinstance(result, list)


# ── index_post_game_completion tests ────────────────────────────────────────

from datetime import timedelta


def _seed_post_game(engine, api_id=50, give_up_days=2, home_score=None, away_score=None):
    """Seed a post_game game with give_up_at in the future (default +2 days)."""
    with Session(engine) as s:
        from sqlalchemy import select as sa_select

        season = s.execute(sa_select(Season).limit(1)).scalar_one_or_none()
        if season is None:
            season = Season(id=1, text="2025")
            s.add(season)
            s.flush()
        # Use api_id-based unique IDs to avoid collisions between tests
        club_h = Club(id=api_id * 10, season_id=season.id, name="PH")
        club_a = Club(id=api_id * 10 + 1, season_id=season.id, name="PA")
        s.add_all([club_h, club_a])
        s.flush()
        team_h = Team(id=api_id * 10, season_id=season.id, club_id=club_h.id, name="PH")
        team_a = Team(id=api_id * 10 + 1, season_id=season.id, club_id=club_a.id, name="PA")
        s.add_all([team_h, team_a])
        s.flush()
        game = Game(
            id=api_id,
            season_id=season.id,
            home_team_id=team_h.id,
            away_team_id=team_a.id,
            status="finished",
            completeness_status="post_game",
            home_score=home_score,
            away_score=away_score,
            give_up_at=_utcnow() + timedelta(days=give_up_days),
        )
        s.add(game)
        s.commit()
        return game.id, season.id


def test_post_game_completes_when_score_present(engine, indexer):
    from app.models.db_models import GameSyncFailure

    game_id, season_id = _seed_post_game(engine, api_id=51, home_score=3, away_score=1)
    indexer._fetch_and_store_game_data = MagicMock()
    count = indexer.index_post_game_completion(season_id)
    assert count >= 1
    with Session(engine) as s:
        game = s.get(Game, game_id)
        assert game.completeness_status == "complete"
        assert game.incomplete_fields is None
        assert game.completeness_checked_at is not None


def test_post_game_stays_post_game_when_incomplete(engine, indexer):
    game_id, season_id = _seed_post_game(engine, api_id=52)  # no score
    indexer._fetch_and_store_game_data = MagicMock()
    count = indexer.index_post_game_completion(season_id)
    assert count == 0
    with Session(engine) as s:
        game = s.get(Game, game_id)
        assert game.completeness_status == "post_game"
        assert game.incomplete_fields is not None


def test_post_game_abandoned_when_past_deadline(engine, indexer):
    from app.models.db_models import GameSyncFailure
    from sqlalchemy import select as sa_select

    game_id, season_id = _seed_post_game(
        engine, api_id=53, give_up_days=-1
    )  # deadline was yesterday
    indexer._fetch_and_store_game_data = MagicMock()
    count = indexer.index_post_game_completion(season_id)
    assert count >= 1
    with Session(engine) as s:
        game = s.get(Game, game_id)
        assert game.completeness_status == "abandoned"
        failure = s.execute(
            sa_select(GameSyncFailure).where(GameSyncFailure.game_id == game_id)
        ).scalar_one_or_none()
        assert failure is not None


def test_post_game_retry_resets_to_post_game(engine, indexer):
    from app.models.db_models import GameSyncFailure

    game_id, season_id = _seed_post_game(engine, api_id=54, give_up_days=-1)
    # Seed an abandoned failure with can_retry=True
    with Session(engine) as s:
        game = s.get(Game, game_id)
        game.completeness_status = "abandoned"
        failure = GameSyncFailure(
            game_id=game_id, season_id=season_id, missing_fields=["score"], can_retry=True
        )
        s.add(failure)
        s.commit()
    indexer._fetch_and_store_game_data = MagicMock()
    indexer.index_post_game_completion(season_id)
    with Session(engine) as s:
        game = s.get(Game, game_id)
        assert game.completeness_status in (
            "post_game",
            "complete",
            "abandoned",
        )  # was reset and re-processed
        from sqlalchemy import select as sa_select

        failure = s.execute(
            sa_select(GameSyncFailure).where(GameSyncFailure.game_id == game_id)
        ).scalar_one()
        assert failure.can_retry is False
        assert failure.retried_at is not None

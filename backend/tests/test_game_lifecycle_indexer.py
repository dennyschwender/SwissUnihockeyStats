"""Tests for game lifecycle indexer methods."""
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.db_models import Base, Game, Season, Club, Team, _utcnow
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


def _seed_game(engine, api_id=1, status="scheduled", home_score=None, away_score=None, completeness_status="upcoming"):
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
    indexer._fetch_game_metadata = MagicMock(return_value={"status": "scheduled"})
    result = indexer.index_upcoming_games(season_id)
    assert isinstance(result, int)


def test_index_upcoming_games_transitions_api_finished_to_post_game(engine, indexer):
    game_id, season_id = _seed_game(engine, status="scheduled", completeness_status="upcoming")
    indexer._fetch_game_metadata = MagicMock(return_value={"status": "finished", "home_score": 3, "away_score": 1})
    count = indexer.index_upcoming_games(season_id)
    assert count == 1
    with Session(engine) as s:
        game = s.get(Game, game_id)
        assert game.completeness_status == "post_game"
        assert game.give_up_at is not None


def test_index_upcoming_games_defensive_finished_stuck_in_upcoming(engine, indexer):
    """A game with status=finished but completeness_status=upcoming should be transitioned."""
    game_id, season_id = _seed_game(engine, status="finished", completeness_status="upcoming")
    # No API call needed for defensive rule — it should flip without fetching
    count = indexer.index_upcoming_games(season_id)
    assert count == 1
    with Session(engine) as s:
        game = s.get(Game, game_id)
        assert game.completeness_status == "post_game"


def test_index_upcoming_games_skips_on_api_error(engine, indexer):
    game_id, season_id = _seed_game(engine)
    indexer._fetch_game_metadata = MagicMock(side_effect=Exception("API down"))
    count = indexer.index_upcoming_games(season_id)
    assert count == 0
    with Session(engine) as s:
        game = s.get(Game, game_id)
        assert game.completeness_status == "upcoming"  # unchanged


def test_get_league_groups_for_season_returns_list(engine, indexer):
    with Session(engine) as s:
        result = indexer._get_league_groups_for_season(1, s)
        assert isinstance(result, list)

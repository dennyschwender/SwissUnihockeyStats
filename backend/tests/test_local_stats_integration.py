"""Integration tests for local player stats computation."""
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models.db_models import Base, PlayerStatistics, UnresolvedPlayerEvent


@pytest.fixture
def engine():
    e = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    yield e
    e.dispose()


def test_player_statistics_has_local_columns(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("player_statistics")}
    assert "computed_from_local" in cols
    assert "local_computed_at" in cols


def test_unresolved_player_event_table_exists(engine):
    assert inspect(engine).has_table("unresolved_player_events")
    cols = {c["name"] for c in inspect(engine).get_columns("unresolved_player_events")}
    assert {"id", "game_id", "team_id", "raw_name", "event_type", "created_at",
            "resolved_at", "resolved_by"}.issubset(cols)


from unittest.mock import MagicMock
from contextlib import contextmanager
from app.services.data_indexer import DataIndexer


@pytest.fixture
def mock_db_indexer(engine):
    db = MagicMock()
    @contextmanager
    def session_scope():
        with Session(engine) as s:
            yield s
            s.commit()
    db.session_scope = session_scope
    db.engine = engine
    return db


@pytest.fixture
def indexer(mock_db_indexer):
    api = MagicMock()
    return DataIndexer(db=mock_db_indexer, api=api)


def test_compute_player_stats_for_season_returns_int(engine, indexer):
    with Session(engine) as s:
        from app.models.db_models import Season, SyncStatus
        s.add(Season(id=1, text="2025"))
        s.commit()
    result = indexer.compute_player_stats_for_season(season_id=1)
    assert isinstance(result, int)


def test_index_player_stats_skips_tier_1(engine, indexer):
    """index_player_stats_for_season with exact_tier=1 should return 0 (T1 uses local computation)."""
    with Session(engine) as s:
        from app.models.db_models import Season
        s.add(Season(id=1, text="2025"))
        s.commit()
    result = indexer.index_player_stats_for_season(season_id=1, exact_tier=1, force=True)
    assert result == 0


def test_index_player_stats_skips_tier_3(engine, indexer):
    with Session(engine) as s:
        from app.models.db_models import Season
        s.add(Season(id=1, text="2025"))
        s.commit()
    result = indexer.index_player_stats_for_season(season_id=1, exact_tier=3, force=True)
    assert result == 0

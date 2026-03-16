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

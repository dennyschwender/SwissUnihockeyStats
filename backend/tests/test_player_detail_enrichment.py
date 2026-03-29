"""Tests for player detail enrichment: TTL helper, translations, PPG."""
import pytest
from datetime import datetime, timezone


def test_migration_adds_player_columns(client):
    """New Player columns exist in the DB after initialization."""
    from app.services.database import get_database_service
    from sqlalchemy import text

    db = get_database_service()
    with db.engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(players)"))}
    assert "photo_url" in cols
    assert "height_cm" in cols
    assert "weight_kg" in cols
    assert "position_raw" in cols
    assert "license_raw" in cols
    assert "player_details_fetched_at" in cols

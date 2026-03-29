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


def test_translate_position_known_locale():
    from app.lib.player_translations import translate_position
    assert translate_position("Stürmer", "en") == "Forward"
    assert translate_position("Verteidiger", "en") == "Defender"
    assert translate_position("Torhüter", "en") == "Goalkeeper"


def test_translate_position_de_returns_german():
    from app.lib.player_translations import translate_position
    assert translate_position("Stürmer", "de") == "Stürmer"


def test_translate_position_unknown_falls_back_to_raw():
    from app.lib.player_translations import translate_position
    assert translate_position("Libero", "en") == "Libero"


def test_translate_position_none_returns_none():
    from app.lib.player_translations import translate_position
    assert translate_position(None, "en") is None


def test_translate_license_known():
    from app.lib.player_translations import translate_license
    assert translate_license("Herren Aktive GF L-UPL", "en") == "Men Active GF L-UPL"
    assert translate_license("Damen Aktive GF L-UPL", "en") == "Women Active GF L-UPL"


def test_translate_license_unknown_falls_back():
    from app.lib.player_translations import translate_license
    assert translate_license("Junioren U21 A", "en") == "Junioren U21 A"


def test_translate_license_none_returns_none():
    from app.lib.player_translations import translate_license
    assert translate_license(None, "en") is None


def test_player_details_stale_when_none():
    from app.services.stats_service import _player_details_stale
    assert _player_details_stale(None) is True


def test_player_details_stale_before_aug31_this_year():
    """Fetched before the most recent Aug 31 → stale."""
    from app.services.stats_service import _player_details_stale
    fetched = datetime(2025, 7, 1, tzinfo=timezone.utc)
    assert _player_details_stale(fetched, _today=datetime(2026, 3, 29, tzinfo=timezone.utc)) is True


def test_player_details_fresh_after_aug31():
    """Fetched after the most recent Aug 31 → not stale."""
    from app.services.stats_service import _player_details_stale
    fetched = datetime(2025, 9, 5, tzinfo=timezone.utc)
    assert _player_details_stale(fetched, _today=datetime(2026, 3, 29, tzinfo=timezone.utc)) is False


def test_player_details_stale_before_aug31_same_year():
    """Today is Sept 15; fetched Aug 1 of same year → stale."""
    from app.services.stats_service import _player_details_stale
    fetched = datetime(2025, 8, 1, tzinfo=timezone.utc)
    assert _player_details_stale(fetched, _today=datetime(2025, 9, 15, tzinfo=timezone.utc)) is True


def test_player_details_fresh_when_fetched_same_day_as_aug31():
    """Fetched exactly on Aug 31 → not stale."""
    from app.services.stats_service import _player_details_stale
    fetched = datetime(2025, 8, 31, 12, 0, tzinfo=timezone.utc)
    assert _player_details_stale(fetched, _today=datetime(2026, 3, 1, tzinfo=timezone.utc)) is False

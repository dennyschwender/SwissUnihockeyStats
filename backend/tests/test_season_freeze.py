"""Tests for season freeze feature."""
import pytest
from app.models.db_models import Season, Game


class TestSeasonModel:
    """Season.is_frozen column exists with correct default."""

    def test_is_frozen_default_false(self, app):
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            s = Season(id=9000, text="9000/01", highlighted=False)
            session.add(s)
        with db.session_scope() as session:
            s = session.query(Season).filter(Season.id == 9000).one()
            try:
                assert s.is_frozen is False
            finally:
                session.delete(s)

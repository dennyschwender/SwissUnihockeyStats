"""Tests for season freeze feature."""
import pytest
from app.models.db_models import Season, Game, SyncStatus, Team
from app.services.scheduler import _is_season_complete


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


class TestIsSeasonComplete:
    """_is_season_complete returns correct bool."""

    def _setup_season(self, session, season_id: int):
        s = Season(id=season_id, text=f"{season_id}/xx", highlighted=False)
        session.add(s)
        session.flush()
        # Add two teams so Game composite FK (home/away_team_id, season_id) is satisfied
        session.add(Team(id=1, season_id=season_id, name="Home Team"))
        session.add(Team(id=2, season_id=season_id, name="Away Team"))
        session.flush()
        return s

    def test_no_games_returns_false(self, app):
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            self._setup_season(session, 8001)
        with db.session_scope() as session:
            result = _is_season_complete(session, 8001)
        assert result is False

    def test_all_finished_no_in_progress_returns_true(self, app):
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            self._setup_season(session, 8002)
            session.add(Game(
                id=80021, season_id=8002, group_id=None,
                home_team_id=1, away_team_id=2,
                home_score=3, away_score=1, status="finished",
            ))
        with db.session_scope() as session:
            result = _is_season_complete(session, 8002)
        assert result is True

    def test_unfinished_game_returns_false(self, app):
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            self._setup_season(session, 8003)
            session.add(Game(
                id=80031, season_id=8003, group_id=None,
                home_team_id=1, away_team_id=2,
                status="scheduled",
            ))
        with db.session_scope() as session:
            result = _is_season_complete(session, 8003)
        assert result is False

    def test_in_progress_sync_blocks_freeze(self, app):
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            self._setup_season(session, 8004)
            session.add(Game(
                id=80041, season_id=8004, group_id=None,
                home_team_id=1, away_team_id=2,
                home_score=2, away_score=0, status="finished",
            ))
            session.add(SyncStatus(
                entity_type="leagues",
                entity_id="leagues:8004",
                sync_status="in_progress",
            ))
        with db.session_scope() as session:
            result = _is_season_complete(session, 8004)
        assert result is False

    def test_like_anchor_no_false_match(self, app):
        """Season 4 must not be blocked by entity_id 'leagues:8004'."""
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            self._setup_season(session, 4)
            self._setup_season(session, 8005)
            session.add(Game(
                id=40001, season_id=4, group_id=None,
                home_team_id=1, away_team_id=2,
                home_score=1, away_score=0, status="finished",
            ))
            # in_progress sync for season 8005 — must NOT block season 4
            session.add(SyncStatus(
                entity_type="leagues",
                entity_id="leagues:8005",
                sync_status="in_progress",
            ))
        with db.session_scope() as session:
            result = _is_season_complete(session, 4)
        assert result is True


class TestAdminFreezeEndpoints:
    """Admin freeze/unfreeze/completeness endpoints."""

    def test_completeness_returns_list(self, admin_client, app):
        resp = admin_client.get("/admin/api/seasons/completeness")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_freeze_endpoint(self, admin_client, app):
        from app.services.database import get_database_service
        from app.models.db_models import Season

        db = get_database_service()
        with db.session_scope() as session:
            s = Season(id=6001, text="6001/xx", highlighted=False, is_frozen=False)
            session.add(s)

        try:
            resp = admin_client.post("/admin/api/season/6001/freeze")
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["is_frozen"] is True

            with db.session_scope() as session:
                s = session.query(Season).filter(Season.id == 6001).one()
                assert s.is_frozen is True
        finally:
            with db.session_scope() as session:
                session.query(Season).filter(Season.id == 6001).delete()

    def test_unfreeze_endpoint(self, admin_client, app):
        from app.services.database import get_database_service
        from app.models.db_models import Season

        db = get_database_service()
        with db.session_scope() as session:
            s = Season(id=6002, text="6002/xx", highlighted=False, is_frozen=True)
            session.add(s)

        try:
            resp = admin_client.post("/admin/api/season/6002/unfreeze")
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["is_frozen"] is False

            with db.session_scope() as session:
                s = session.query(Season).filter(Season.id == 6002).one()
                assert s.is_frozen is False
        finally:
            with db.session_scope() as session:
                session.query(Season).filter(Season.id == 6002).delete()

    def test_freeze_404_on_missing_season(self, admin_client, app):
        resp = admin_client.post("/admin/api/season/99999/freeze")
        assert resp.status_code == 404

    def test_unfreeze_404_on_missing_season(self, admin_client, app):
        resp = admin_client.post("/admin/api/season/99999/unfreeze")
        assert resp.status_code == 404

    def test_completeness_contains_is_frozen_field(self, admin_client, app):
        from app.services.database import get_database_service
        from app.models.db_models import Season

        db = get_database_service()
        with db.session_scope() as session:
            s = Season(id=6003, text="6003/xx", highlighted=False, is_frozen=False)
            session.add(s)

        try:
            resp = admin_client.get("/admin/api/seasons/completeness")
            assert resp.status_code == 200
            data = resp.json()
            entry = next((d for d in data if d["season_id"] == 6003), None)
            assert entry is not None
            assert "is_frozen" in entry
            assert "games_total" in entry
            assert "games_finished" in entry
            assert "games_pct" in entry
            assert "is_complete" in entry
            assert "season_id" in entry
            assert "text" in entry
            assert "is_current" in entry
        finally:
            with db.session_scope() as session:
                session.query(Season).filter(Season.id == 6003).delete()

"""
Shared pytest fixtures for the SwissUnihockey backend test suite.
"""

import os
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# Override settings BEFORE importing the app so the app boots with test values
os.environ.setdefault("ADMIN_PIN", "testpin")
os.environ.setdefault("SESSION_SECRET", "test-secret-key-32-chars-xxxxxxxx")
os.environ.setdefault("DATABASE_PATH", ":memory:")
# Ensure DEBUG=true so the production-secret check doesn't reject the test PIN
os.environ.setdefault("DEBUG", "true")


def _make_mock_client():
    """Return a MagicMock that mimics SwissUnihockeyClient with sensible defaults."""
    mock = MagicMock()
    mock.get_clubs.return_value = {
        "entries": [
            {"id": 1, "text": "Test Club A", "region": "Zurich"},
            {"id": 2, "text": "Test Club B", "region": "Bern"},
        ]
    }
    mock.get_leagues.return_value = {
        "entries": [
            {"id": 1, "text": "NLA", "mode": 1},
            {"id": 2, "text": "NLB", "mode": 1},
        ]
    }
    mock.get_teams.return_value = {
        "entries": [
            {"id": 101, "text": "Team Alpha", "set_in_context": {"team_id": 101}},
            {"id": 102, "text": "Team Beta", "set_in_context": {"team_id": 102}},
        ]
    }
    mock.get_games.return_value = {"entries": []}
    mock.get_players.return_value = {"entries": []}
    mock.get_rankings.return_value = {"entries": []}
    mock.get_topscorers.return_value = {"entries": []}
    mock.get_game_events.return_value = {"entries": []}
    return mock


@pytest.fixture(scope="session")
def app():
    """Application fixture — patches the API client for the whole session."""
    mock_client = _make_mock_client()
    # Patch both the canonical location and every endpoint module that has
    # already bound the function via `from app.services.swissunihockey import
    # get_swissunihockey_client`.  Without these extra patches the endpoint
    # modules keep their original reference and hit the real API.
    _patch_targets = [
        "app.services.swissunihockey.get_swissunihockey_client",
        "app.api.v1.endpoints.clubs.get_swissunihockey_client",
        "app.api.v1.endpoints.leagues.get_swissunihockey_client",
        "app.api.v1.endpoints.teams.get_swissunihockey_client",
        "app.api.v1.endpoints.games.get_swissunihockey_client",
        "app.api.v1.endpoints.players.get_swissunihockey_client",
        "app.api.v1.endpoints.rankings.get_swissunihockey_client",
    ]
    patchers = [patch(t, return_value=mock_client) for t in _patch_targets]
    for p in patchers:
        p.start()
    try:
        from app.main import app as _app

        yield _app
    finally:
        for p in patchers:
            p.stop()


@pytest.fixture(scope="session")
def client(app):
    """Unauthenticated test client."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="session")
def admin_client(app):
    """Authenticated admin test client (session cookie set)."""
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/admin/login", data={"pin": os.environ["ADMIN_PIN"]}, follow_redirects=True)
        assert resp.status_code == 200, f"Admin login failed: {resp.status_code}"
        yield c


@pytest.fixture(autouse=True)
def clear_job_cooldowns():
    """Clear admin-job cooldown state and contact rate limits before each test."""
    from app.main import _job_last_done, _contact_attempts

    _job_last_done.clear()
    _contact_attempts.clear()
    yield
    _job_last_done.clear()
    _contact_attempts.clear()


@pytest.fixture
def mock_api_client():
    """
    Per-test fixture that patches get_swissunihockey_client with a fresh mock.
    Useful for tests that need to control specific return values.
    """
    mock_client = _make_mock_client()
    targets = [
        "app.services.swissunihockey.get_swissunihockey_client",
        "app.api.v1.endpoints.clubs.get_swissunihockey_client",
        "app.api.v1.endpoints.leagues.get_swissunihockey_client",
        "app.api.v1.endpoints.teams.get_swissunihockey_client",
        "app.api.v1.endpoints.games.get_swissunihockey_client",
        "app.api.v1.endpoints.players.get_swissunihockey_client",
        "app.api.v1.endpoints.rankings.get_swissunihockey_client",
    ]
    patchers = [patch(t, return_value=mock_client) for t in targets]
    for p in patchers:
        p.start()
    yield mock_client
    for p in patchers:
        p.stop()


@pytest.fixture
def db_session(app):  # noqa: F811
    """Yield a live SQLAlchemy session backed by the in-memory test DB.

    Unlike session_scope(), this fixture commits immediately so that other
    session_scope() calls (e.g. inside service functions) can see the seeded data.
    """
    from app.services.database import get_database_service

    db = get_database_service()
    with db.session_scope() as session:
        yield session

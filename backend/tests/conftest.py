"""
Shared pytest fixtures for the SwissUnihockey backend test suite.
"""
import os
import pytest
from fastapi.testclient import TestClient

# Override settings BEFORE importing the app so the app boots with test values
os.environ.setdefault("ADMIN_PIN", "testpin")
os.environ.setdefault("SESSION_SECRET", "test-secret-key-32-chars-xxxxxxxx")
os.environ.setdefault("DATABASE_PATH", ":memory:")


@pytest.fixture(scope="session")
def app():
    from app.main import app as _app
    return _app


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

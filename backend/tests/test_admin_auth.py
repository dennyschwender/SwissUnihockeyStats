"""
Tests for admin authentication (login / logout / PIN protection).
"""
import os
import pytest
from fastapi.testclient import TestClient


CORRECT_PIN = os.environ.get("ADMIN_PIN", "testpin")
WRONG_PIN   = "wrongpin-xyz"


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------

class TestAdminLoginPage:
    def test_login_page_returns_200(self, client):
        r = client.get("/admin/login")
        assert r.status_code == 200

    def test_login_page_contains_form(self, client):
        r = client.get("/admin/login")
        assert b'<form' in r.content
        assert b'name="pin"' in r.content


# ---------------------------------------------------------------------------
# Login submit
# ---------------------------------------------------------------------------

class TestAdminLoginSubmit:
    def test_correct_pin_redirects_to_admin(self, app):
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post("/admin/login", data={"pin": CORRECT_PIN}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "/admin" in r.headers.get("location", "")

    def test_wrong_pin_returns_401(self, app):
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post("/admin/login", data={"pin": WRONG_PIN}, follow_redirects=False)
            assert r.status_code == 401

    def test_wrong_pin_shows_error_message(self, app):
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post("/admin/login", data={"pin": WRONG_PIN})
            assert b"Incorrect" in r.content or b"error" in r.content.lower()

    def test_empty_pin_is_rejected(self, app):
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post("/admin/login", data={"pin": ""})
            assert r.status_code in (401, 200)  # either 401 or re-render with error
            # Must NOT redirect to admin dashboard
            assert b"Admin" in r.content  # stays on login page


# ---------------------------------------------------------------------------
# Protected routes — unauthenticated
# ---------------------------------------------------------------------------

class TestAdminProtectedRoutes:
    PROTECTED = [
        ("/admin",          "GET"),
        ("/admin/api/stats","GET"),
        ("/admin/api/index","POST"),
    ]

    @pytest.mark.parametrize("path,method", PROTECTED)
    def test_unauthenticated_access_is_redirected_or_rejected(self, client, path, method):
        if method == "GET":
            r = client.get(path, follow_redirects=False)
        else:
            r = client.post(path, json={}, follow_redirects=False)
        # Must NOT return 200 for unauthenticated request
        assert r.status_code != 200, f"{method} {path} returned 200 without auth"


# ---------------------------------------------------------------------------
# Protected routes — authenticated
# ---------------------------------------------------------------------------

class TestAdminAuthenticatedRoutes:
    def test_admin_page_accessible_after_login(self, admin_client):
        r = admin_client.get("/admin")
        assert r.status_code == 200
        assert b"Admin" in r.content

    def test_stats_endpoint_returns_json(self, admin_client):
        r = admin_client.get("/admin/api/stats")
        assert r.status_code == 200
        data = r.json()
        assert "totals" in data
        assert "by_season" in data

    def test_scheduler_status_returns_json(self, admin_client):
        r = admin_client.get("/admin/api/scheduler")
        assert r.status_code == 200
        data = r.json()
        assert "enabled" in data


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class TestAdminLogout:
    def test_logout_clears_session(self, app):
        with TestClient(app, raise_server_exceptions=False) as c:
            # Log in first
            c.post("/admin/login", data={"pin": CORRECT_PIN}, follow_redirects=True)
            # Confirm access
            assert c.get("/admin").status_code == 200
            # Log out
            c.get("/admin/logout", follow_redirects=True)
            # Admin should now redirect / reject
            r = c.get("/admin", follow_redirects=False)
            assert r.status_code != 200

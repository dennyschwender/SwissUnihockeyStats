"""
Tests for public-facing HTML and API routes.
External API calls are mocked via the session-scoped `app` fixture in conftest.py.
"""
import pytest


class TestPublicRoutes:
    def test_root_redirects_or_returns_html(self, client):
        r = client.get("/", follow_redirects=True)
        assert r.status_code == 200

    def test_locale_home_returns_html(self, client):
        r = client.get("/en")
        assert r.status_code == 200
        assert b"html" in r.content.lower()

    def test_de_home_returns_html(self, client):
        r = client.get("/de")
        assert r.status_code == 200

    def test_clubs_page_returns_html(self, client):
        r = client.get("/en/clubs")
        assert r.status_code == 200

    def test_teams_page_returns_html(self, client):
        r = client.get("/en/teams")
        assert r.status_code == 200

    def test_leagues_page_returns_html(self, client):
        r = client.get("/en/leagues")
        assert r.status_code == 200

    def test_games_page_returns_html(self, client):
        r = client.get("/en/games")
        assert r.status_code == 200


class TestApiV1Clubs:
    def test_clubs_api_returns_json(self, client):
        r = client.get("/api/v1/clubs")
        assert r.status_code == 200
        data = r.json()
        assert "clubs" in data
        assert "total" in data
        assert isinstance(data["clubs"], list)

    def test_clubs_api_filter_by_name(self, client):
        r = client.get("/api/v1/clubs?name=Test+Club+A")
        assert r.status_code == 200
        data = r.json()
        assert all("Test Club A" in c.get("text", "") for c in data["clubs"])

    def test_clubs_api_limit_bounds(self, client):
        r = client.get("/api/v1/clubs?limit=0")
        assert r.status_code == 422  # ge=1 validation

    def test_clubs_api_limit_max(self, client):
        r = client.get("/api/v1/clubs?limit=9999")
        assert r.status_code == 422  # le=1000 validation

    def test_club_not_found_returns_404(self, client):
        r = client.get("/api/v1/clubs/99999")
        assert r.status_code == 404


class TestApiV1Leagues:
    def test_leagues_api_returns_json(self, client):
        r = client.get("/api/v1/leagues")
        assert r.status_code == 200
        data = r.json()
        assert "leagues" in data
        assert isinstance(data["leagues"], list)

    def test_league_not_found_returns_404(self, client):
        r = client.get("/api/v1/leagues/99999")
        assert r.status_code == 404


class TestApiV1Teams:
    def test_teams_api_returns_json(self, client):
        r = client.get("/api/v1/teams")
        assert r.status_code == 200
        data = r.json()
        assert "teams" in data
        assert isinstance(data["teams"], list)

    def test_teams_limit_validation(self, client):
        r = client.get("/api/v1/teams?limit=0")
        assert r.status_code == 422


class TestApiV1Games:
    def test_games_api_returns_json(self, client):
        r = client.get("/api/v1/games")
        assert r.status_code == 200
        data = r.json()
        assert "games" in data

    def test_games_limit_validation(self, client):
        r = client.get("/api/v1/games?limit=9999")
        assert r.status_code == 422


class TestApiV1Players:
    def test_players_api_returns_json(self, client):
        r = client.get("/api/v1/players")
        assert r.status_code == 200
        data = r.json()
        assert "players" in data

    def test_players_limit_validation(self, client):
        r = client.get("/api/v1/players?limit=0")
        assert r.status_code == 422

    def test_players_name_search(self, client):
        r = client.get("/api/v1/players?name=alice")
        assert r.status_code == 200


class TestApiV1Misc:
    def test_unknown_api_route_returns_404(self, client):
        r = client.get("/api/v1/nonexistent-endpoint-xyz")
        assert r.status_code == 404


class TestAdminLoginAccessibility:
    """Login page must be publicly accessible (no auth required)."""

    def test_login_page_accessible_without_session(self, client):
        r = client.get("/admin/login")
        assert r.status_code == 200

    def test_admin_dashboard_not_accessible_without_session(self, client):
        r = client.get("/admin", follow_redirects=False)
        assert r.status_code != 200


class TestDebugEndpointsHidden:
    """Debug endpoints must not be accessible in non-DEBUG mode."""

    def test_debug_endpoints_require_debug_flag(self, client):
        # In DEBUG=true (test env), endpoints exist but require admin auth.
        # In production (DEBUG=false), they are not registered at all.
        # Either 404 (not registered) or non-200 (auth required) is acceptable.
        for path in ["/debug/player-index", "/debug/force-reindex"]:
            r = client.get(path, follow_redirects=False)
            assert r.status_code != 200, f"{path} returned 200 without auth"


class TestContactAndPrivacyRoutes:
    def test_contact_page_returns_html(self, client):
        r = client.get("/en/contact")
        assert r.status_code == 200
        assert b"html" in r.content.lower()

    def test_privacy_page_returns_html(self, client):
        r = client.get("/en/privacy")
        assert r.status_code == 200
        assert b"html" in r.content.lower()

    def test_contact_submit_missing_fields_returns_form(self, client):
        r = client.post(
            "/en/contact",
            data={"name": "", "email": "", "subject": "", "message": ""},
        )
        assert r.status_code == 200
        assert b"html" in r.content.lower()

    def test_contact_submit_invalid_email_returns_form(self, client):
        r = client.post(
            "/en/contact",
            data={"name": "Test User", "email": "notanemail", "subject": "Hi", "message": "Hello"},
        )
        assert r.status_code == 200

    def test_contact_submit_valid_redirects(self, client):
        r = client.post(
            "/en/contact",
            data={"name": "Test User", "email": "user@example.com", "subject": "Hi", "message": "Hello world"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "/en/contact" in r.headers.get("location", "")

    def test_contact_submit_rate_limited_after_limit_exceeded(self, client):
        # Send enough requests to guarantee hitting the per-IP limit (5/hour).
        # Some prior POST tests in this class may already have consumed slots,
        # so 6 additional submissions always reaches the cap regardless of order.
        last_response = None
        for _ in range(6):
            last_response = client.post(
                "/en/contact",
                data={"name": "Test User", "email": "user@example.com", "subject": "Hi", "message": "Hello world"},
                follow_redirects=False,
            )
        assert last_response is not None
        assert last_response.status_code == 429
        assert b"html" in last_response.content.lower()

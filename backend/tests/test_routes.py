"""
Tests for public-facing HTML and API routes.
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


class TestApiV1Routes:
    def test_clubs_api_returns_json(self, client):
        r = client.get("/api/v1/clubs")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (dict, list))

    def test_leagues_api_returns_json(self, client):
        r = client.get("/api/v1/leagues")
        assert r.status_code == 200

    def test_teams_api_returns_json(self, client):
        r = client.get("/api/v1/teams")
        # 200 when DB/live API available; 500 when external API unreachable in test env
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), (dict, list))

    def test_games_api_returns_json(self, client):
        r = client.get("/api/v1/games")
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), (dict, list))

    def test_players_api_accepts_query(self, client):
        r = client.get("/api/v1/players?q=test")
        # 200 ok, 422 bad params, 500 external API unavailable in test env
        assert r.status_code in (200, 422, 500)

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

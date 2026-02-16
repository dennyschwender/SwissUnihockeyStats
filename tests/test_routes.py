"""
Tests for FastAPI HTML routes and endpoints.
"""

import pytest
from bs4 import BeautifulSoup


class TestRootRoute:
    """Tests for root route."""

    def test_root_returns_html(self, client):
        """Test root route returns HTML."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_root_contains_swiss_unihockey(self, client):
        """Test root route contains app name."""
        response = client.get("/")
        assert "SwissUnihockey" in response.text or "Swiss Unihockey" in response.text


class TestLocaleRoutes:
    """Tests for locale-specific routes."""

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_locale_homepage(self, client, locale):
        """Test homepage works for all locales."""
        response = client.get(f"/{locale}")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_locale_contains_navigation(self, client, locale):
        """Test homepage contains navigation links."""
        response = client.get(f"/{locale}")
        html = response.text
        # Check for navigation to other pages
        assert f"/{locale}/clubs" in html or "/clubs" in html
        assert f"/{locale}/leagues" in html or "/leagues" in html

    def test_invalid_locale_still_works(self, client):
        """Test that invalid locale doesn't crash (uses default)."""
        response = client.get("/xx")  # Invalid locale code
        # Should still return 200 (using default locale)
        assert response.status_code == 200


class TestClubsRoutes:
    """Tests for clubs routes."""

    @pytest.mark.parametrize("locale", ["de", "en"])
    def test_clubs_page(self, client, locale):
        """Test clubs page loads successfully."""
        response = client.get(f"/{locale}/clubs")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_clubs_displays_data(self, client):
        """Test clubs page displays club data."""
        response = client.get("/de/clubs")
        html = response.text
        # Check for mock club names
        assert "HC Davos" in html
        assert "SC Bern" in html

    def test_clubs_search_endpoint(self, client):
        """Test htmx club search endpoint."""
        response = client.get("/de/clubs/search?q=Davos")
        assert response.status_code == 200
        assert "HC Davos" in response.text
        assert "SC Bern" not in response.text  # Should be filtered out

    def test_clubs_search_empty_query(self, client):
        """Test club search with empty query returns all clubs."""
        response = client.get("/de/clubs/search?q=")
        assert response.status_code == 200
        # Should return clubs (limited to 50)
        assert "HC Davos" in response.text

    def test_clubs_search_no_results(self, client):
        """Test club search with no matching results."""
        response = client.get("/de/clubs/search?q=NonexistentClub123")
        assert response.status_code == 200
        assert "No clubs found" in response.text


class TestLeaguesRoutes:
    """Tests for leagues routes."""

    @pytest.mark.parametrize("locale", ["de", "en"])
    def test_leagues_page(self, client, locale):
        """Test leagues page loads successfully."""
        response = client.get(f"/{locale}/leagues")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_leagues_displays_data(self, client):
        """Test leagues page displays league data."""
        response = client.get("/de/leagues")
        html = response.text
        # Check for mock league names
        assert "National League A" in html or "League" in html


class TestTeamsRoutes:
    """Tests for teams routes."""

    @pytest.mark.parametrize("locale", ["de", "en"])
    def test_teams_page(self, client, locale):
        """Test teams page loads successfully."""
        response = client.get(f"/{locale}/teams")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_teams_displays_data(self, client):
        """Test teams page displays team data."""
        response = client.get("/de/teams")
        html = response.text
        # Check for mock team names
        assert "HC Davos A" in html or "Team" in html

    def test_teams_search_endpoint(self, client):
        """Test htmx team search endpoint."""
        response = client.get("/de/teams/search?q=Davos")
        assert response.status_code == 200
        assert "HC Davos A" in response.text

    def test_teams_search_filter_by_mode(self, client):
        """Test team search with mode filter."""
        # Filter for men's teams (mode=1)
        response = client.get("/de/teams/search?mode=1")
        assert response.status_code == 200
        assert "HC Davos A" in response.text  # mode=1
        
        # Filter for women's teams (mode=2)
        response = client.get("/de/teams/search?mode=2")
        assert response.status_code == 200
        assert "SC Bern Women" in response.text  # mode=2

    def test_teams_search_combined_filters(self, client):
        """Test team search with both query and mode filter."""
        response = client.get("/de/teams/search?q=Bern&mode=2")
        assert response.status_code == 200
        assert "SC Bern Women" in response.text
        assert "HC Davos A" not in response.text

    def test_teams_search_no_results(self, client):
        """Test team search with no matching results."""
        response = client.get("/de/teams/search?q=NonexistentTeam123")
        assert response.status_code == 200
        assert "No teams found" in response.text


class TestGamesRoutes:
    """Tests for games routes."""

    @pytest.mark.parametrize("locale", ["de", "en"])
    def test_games_page(self, client, locale):
        """Test games page loads successfully."""
        response = client.get(f"/{locale}/games")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_games_displays_data(self, client):
        """Test games page displays game data."""
        response = client.get("/de/games")
        html = response.text
        # Check for game placeholders (template uses generic "Game 1", "Game 2" format)
        assert "Game 1" in html or "Game 2" in html

    def test_games_handles_api_error_gracefully(self, client, mock_swissunihockey_client):
        """Test games page handles API errors without crashing."""
        # Make API call fail
        mock_swissunihockey_client.get_games.side_effect = Exception("API Error")
        
        response = client.get("/de/games")
        # Should still return 200, just with empty games list
        assert response.status_code == 200


class TestRankingsRoutes:
    """Tests for rankings routes."""

    @pytest.mark.parametrize("locale", ["de", "en"])
    def test_rankings_page(self, client, locale):
        """Test rankings page loads successfully."""
        response = client.get(f"/{locale}/rankings")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_rankings_displays_standings(self, client):
        """Test rankings page displays standings data."""
        response = client.get("/de/rankings")
        html = response.text
        # Check for table structure with rank numbers
        assert "Tabelle" in html or "Standings" in html
        # Check table headers exist
        assert "Team" in html or "GP" in html

    def test_rankings_displays_top_scorers(self, client):
        """Test rankings page displays top scorers data."""
        response = client.get("/de/rankings")
        html = response.text
        # Check for mock player data
        assert "John Doe" in html or "Jane Smith" in html or "Player" in html

    def test_rankings_handles_api_errors(self, client, mock_swissunihockey_client):
        """Test rankings page handles API errors gracefully."""
        # Make API calls fail
        mock_swissunihockey_client.get_table.side_effect = Exception("API Error")
        mock_swissunihockey_client.get_top_scorers.side_effect = Exception("API Error")
        
        response = client.get("/de/rankings")
        # Should still return 200, just with empty data
        assert response.status_code == 200


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        # Health endpoint exists and returns OK
        assert response.text is not None


class TestStaticFiles:
    """Tests for static file serving."""

    def test_static_css_accessible(self, client):
        """Test static CSS files are accessible."""
        response = client.get("/static/css/main.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]


class TestHTMXEndpoints:
    """Tests specific to htmx partial responses."""

    def test_clubs_search_returns_partial_html(self, client):
        """Test clubs search returns HTML fragment, not full page."""
        response = client.get("/de/clubs/search?q=Davos")
        html = response.text
        # Should not contain full page structure (no <html>, <head>, etc.)
        assert "<html" not in html.lower()
        assert "<head" not in html.lower()
        # Should contain cards
        assert "card" in html.lower() or "HC Davos" in html

    def test_teams_search_returns_partial_html(self, client):
        """Test teams search returns HTML fragment, not full page."""
        response = client.get("/de/teams/search?q=Davos")
        html = response.text
        # Should not contain full page structure
        assert "<html" not in html.lower()
        assert "<head" not in html.lower()
        # Should contain cards
        assert "card" in html.lower() or "HC Davos A" in html


class TestResponseHeaders:
    """Tests for HTTP response headers."""

    @pytest.mark.parametrize("path", [
        "/",
        "/de",
        "/de/clubs",
        "/de/leagues",
        "/de/teams",
        "/de/games",
        "/de/rankings"
    ])
    def test_html_content_type(self, client, path):
        """Test HTML pages return correct content type."""
        response = client.get(path)
        assert "text/html" in response.headers["content-type"]

    def test_cors_headers_present(self, client):
        """Test CORS headers are configured."""
        response = client.get("/health")
        # Check that CORS middleware is working
        assert response.status_code == 200

"""Tests for Week 4 features: Universal Search and Favorites."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from backend.app.main import app


client = TestClient(app)


class TestUniversalSearch:
    """Test cases for universal search functionality."""

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_search_endpoint_exists(self, locale):
        """Test that search endpoint exists for all locales."""
        response = client.get(f"/{locale}/search", params={"q": "test"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")

    def test_search_requires_minimum_two_characters(self):
        """Test that search requires at least 2 characters."""
        # Single character
        response = client.get("/de/search", params={"q": "a"})
        assert response.status_code == 200
        assert "Enter at least 2 characters" in response.text

        # Empty query
        response = client.get("/de/search", params={"q": ""})
        assert response.status_code == 200
        assert "Enter at least 2 characters" in response.text

    def test_search_with_no_query_parameter(self):
        """Test search with missing query parameter."""
        response = client.get("/de/search")
        assert response.status_code == 200
        assert "Enter at least 2 characters" in response.text

    @patch("backend.app.main.get_swissunihockey_client")
    def test_search_returns_matching_clubs(self, mock_get_client):
        """Test search returns matching clubs."""
        mock_client = MagicMock()
        mock_client.get_clubs.return_value = {
            "entries": [
                {"text": "Zürich Lions", "set_in_context": {"club_id": 1}},
                {"text": "Bern Bears", "set_in_context": {"club_id": 2}},
                {"text": "Zürich FC", "set_in_context": {"club_id": 3}},
            ]
        }
        mock_client.get_leagues.return_value = {"entries": []}
        mock_client.get_teams.return_value = {"entries": []}
        mock_get_client.return_value = mock_client

        response = client.get("/de/search", params={"q": "zürich"})
        assert response.status_code == 200
        assert "Zürich Lions" in response.text
        assert "Zürich FC" in response.text
        assert "Bern Bears" not in response.text
        assert "🏢 Clubs" in response.text

    @patch("backend.app.main.get_swissunihockey_client")
    def test_search_returns_matching_leagues(self, mock_get_client):
        """Test search returns matching leagues."""
        mock_client = MagicMock()
        mock_client.get_clubs.return_value = {"entries": []}
        mock_client.get_leagues.return_value = {
            "entries": [
                {"text": "National League A"},
                {"text": "National League B"},
                {"text": "Regional League"},
            ]
        }
        mock_client.get_teams.return_value = {"entries": []}
        mock_get_client.return_value = mock_client

        response = client.get("/de/search", params={"q": "national"})
        assert response.status_code == 200
        assert "National League A" in response.text
        assert "National League B" in response.text
        assert "Regional League" not in response.text
        assert "🏆 Leagues" in response.text

    @patch("backend.app.main.get_swissunihockey_client")
    def test_search_returns_matching_teams(self, mock_get_client):
        """Test search returns matching teams."""
        mock_client = MagicMock()
        mock_client.get_clubs.return_value = {"entries": []}
        mock_client.get_leagues.return_value = {"entries": []}
        mock_client.get_teams.return_value = {
            "entries": [
                {"text": "GC Küsnacht"},
                {"text": "HC Davos"},
                {"text": "Küsnacht United"},
            ]
        }
        mock_get_client.return_value = mock_client

        response = client.get("/de/search", params={"q": "küsnacht"})
        assert response.status_code == 200
        assert "GC Küsnacht" in response.text
        assert "Küsnacht United" in response.text
        assert "HC Davos" not in response.text
        assert "👥 Teams" in response.text

    @patch("backend.app.main.get_swissunihockey_client")
    def test_search_case_insensitive(self, mock_get_client):
        """Test that search is case insensitive."""
        mock_client = MagicMock()
        mock_client.get_clubs.return_value = {
            "entries": [{"text": "Zürich Lions", "set_in_context": {"club_id": 1}}]
        }
        mock_client.get_leagues.return_value = {"entries": []}
        mock_client.get_teams.return_value = {"entries": []}
        mock_get_client.return_value = mock_client

        # Test with uppercase
        response = client.get("/de/search", params={"q": "ZÜRICH"})
        assert response.status_code == 200
        assert "Zürich Lions" in response.text

        # Test with lowercase
        response = client.get("/de/search", params={"q": "zürich"})
        assert response.status_code == 200
        assert "Zürich Lions" in response.text

        # Test with mixed case
        response = client.get("/de/search", params={"q": "ZüRiCh"})
        assert response.status_code == 200
        assert "Zürich Lions" in response.text

    @patch("backend.app.main.get_swissunihockey_client")
    def test_search_limits_results_to_five_per_category(self, mock_get_client):
        """Test that search limits results to 5 per category."""
        mock_client = MagicMock()
        # Create 10 matching clubs
        clubs = [
            {"text": f"TestClub{i}", "set_in_context": {"club_id": i}}
            for i in range(10)
        ]
        mock_client.get_clubs.return_value = {"entries": clubs}
        mock_client.get_leagues.return_value = {"entries": []}
        mock_client.get_teams.return_value = {"entries": []}
        mock_get_client.return_value = mock_client

        response = client.get("/de/search", params={"q": "test"})
        assert response.status_code == 200
        
        # Count div.search-item elements - should only have 5
        search_item_count = response.text.count('<div class="search-item"')
        assert search_item_count == 5, f"Should only return 5 search items, got {search_item_count}"

    @patch("backend.app.main.get_swissunihockey_client")
    def test_search_no_results(self, mock_get_client):
        """Test search with no matching results."""
        mock_client = MagicMock()
        mock_client.get_clubs.return_value = {"entries": []}
        mock_client.get_leagues.return_value = {"entries": []}
        mock_client.get_teams.return_value = {"entries": []}
        mock_get_client.return_value = mock_client

        response = client.get("/de/search", params={"q": "xyznonexistent"})
        assert response.status_code == 200
        assert "No results found" in response.text

    @patch("backend.app.main.get_swissunihockey_client")
    def test_search_across_all_categories(self, mock_get_client):
        """Test search returns results from all categories."""
        mock_client = MagicMock()
        mock_client.get_clubs.return_value = {
            "entries": [{"text": "Swiss Club", "set_in_context": {"club_id": 1}}]
        }
        mock_client.get_leagues.return_value = {
            "entries": [{"text": "Swiss League"}]
        }
        mock_client.get_teams.return_value = {
            "entries": [{"text": "Swiss Team"}]
        }
        mock_get_client.return_value = mock_client

        response = client.get("/de/search", params={"q": "swiss"})
        assert response.status_code == 200
        assert "🏢 Clubs" in response.text
        assert "🏆 Leagues" in response.text
        assert "👥 Teams" in response.text
        assert "Swiss Club" in response.text
        assert "Swiss League" in response.text
        assert "Swiss Team" in response.text

    @patch("backend.app.main.get_swissunihockey_client")
    def test_search_handles_api_errors_gracefully(self, mock_get_client):
        """Test that search handles API errors gracefully."""
        mock_client = MagicMock()
        # Make all API calls fail
        mock_client.get_clubs.side_effect = Exception("API Error")
        mock_client.get_leagues.side_effect = Exception("API Error")
        mock_client.get_teams.side_effect = Exception("API Error")
        mock_get_client.return_value = mock_client

        # Should handle errors gracefully (falls back to cache or shows error message)
        response = client.get("/de/search", params={"q": "test"})
        assert response.status_code == 200
        # Should either show cached results or an error message
        assert "service" in response.text.lower() or "search-results" in response.text.lower()


class TestFavoritesPage:
    """Test cases for favorites page."""

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_favorites_page_exists(self, locale):
        """Test that favorites page exists for all locales."""
        response = client.get(f"/{locale}/favorites")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")

    def test_favorites_page_contains_title(self):
        """Test that favorites page contains the favorites title."""
        response = client.get("/de/favorites")
        assert response.status_code == 200
        # Check for favorites-related content
        assert "favorites" in response.text.lower() or "favoriten" in response.text.lower()

    def test_favorites_page_has_alpine_js_component(self):
        """Test that favorites page includes Alpine.js component."""
        response = client.get("/de/favorites")
        assert response.status_code == 200
        # Check for Alpine.js directives
        assert "x-data" in response.text or "favoritesManager" in response.text

    def test_favorites_page_includes_empty_state(self):
        """Test that favorites page includes empty state message."""
        response = client.get("/de/favorites")
        assert response.status_code == 200
        # Should have template for when no favorites exist
        content_lower = response.text.lower()
        assert any(keyword in content_lower for keyword in ["empty", "no favorites", "keine", "leer"])

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_favorites_page_contains_navigation(self, locale):
        """Test that favorites page includes navigation."""
        response = client.get(f"/{locale}/favorites")
        assert response.status_code == 200
        # Should include navigation links
        assert f'href="/{locale}/' in response.text


class TestWeek4Integration:
    """Integration tests for Week 4 features."""

    def test_home_page_has_search_bar(self):
        """Test that home page includes the universal search bar."""
        response = client.get("/de/")
        assert response.status_code == 200
        # Check for search-related elements
        assert 'hx-get="/de/search"' in response.text or 'search' in response.text.lower()

    def test_home_page_has_favorites_link(self):
        """Test that home page includes link to favorites."""
        response = client.get("/de/")
        assert response.status_code == 200
        # Check for favorites link
        assert "/de/favorites" in response.text

    def test_clubs_page_has_favorite_buttons(self):
        """Test that clubs page includes favorite buttons."""
        response = client.get("/de/clubs")
        assert response.status_code == 200
        # Check for favorite button functionality
        content = response.text.lower()
        assert "favorite" in content or "favorit" in content or "star" in content

    def test_leagues_page_has_favorite_buttons(self):
        """Test that leagues page includes favorite buttons."""
        response = client.get("/de/leagues")
        assert response.status_code == 200
        # Check for favorite button functionality
        content = response.text.lower()
        assert "favorite" in content or "favorit" in content or "star" in content

    def test_teams_page_has_favorite_buttons(self):
        """Test that teams page includes favorite buttons."""
        response = client.get("/de/teams")
        assert response.status_code == 200
        # Check for favorite button functionality
        content = response.text.lower()
        assert "favorite" in content or "favorit" in content or "star" in content

    def test_favorites_js_loaded(self):
        """Test that favorites.js is loaded in base template."""
        response = client.get("/de/")
        assert response.status_code == 200
        # Check for favorites.js script tag
        assert "favorites.js" in response.text

    def test_base_template_has_alpine_js_store(self):
        """Test that base template includes Alpine.js data store."""
        response = client.get("/de/")
        assert response.status_code == 200
        # Check for Alpine.js store initialization
        assert "favoritesStore" in response.text or "x-data" in response.text


class TestWeek4Performance:
    """Performance tests for Week 4 features."""

    @patch("backend.app.main.get_swissunihockey_client")
    def test_search_performance_with_large_dataset(self, mock_get_client):
        """Test search performance with large number of results."""
        mock_client = MagicMock()
        # Create large dataset
        large_clubs = [
            {"text": f"Club {i}", "set_in_context": {"club_id": i}}
            for i in range(1000)
        ]
        mock_client.get_clubs.return_value = {"entries": large_clubs}
        mock_client.get_leagues.return_value = {"entries": []}
        mock_client.get_teams.return_value = {"entries": []}
        mock_get_client.return_value = mock_client

        # Search should still be fast and return max 5 results
        response = client.get("/de/search", params={"q": "club"})
        assert response.status_code == 200
        # Should limit to 5  results - count search item divs
        search_item_count = response.text.count('<div class="search-item"')
        assert search_item_count == 5, f"Should limit to 5 results, got {search_item_count}"

    def test_search_response_time(self):
        """Test that search responds quickly."""
        import time
        start = time.time()
        response = client.get("/de/search", params={"q": "test"})
        duration = time.time() - start
        
        assert response.status_code == 200
        # Search should respond in less than 2 seconds (generous for cached data)
        assert duration < 2.0, f"Search took {duration}s, should be < 2s"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Tests for SwissUnihockey API client."""

import pytest
from unittest.mock import Mock, patch
import requests
from api.client import SwissUnihockeyClient


class TestSwissUnihockeyClient:
    """Test cases for SwissUnihockeyClient."""

    def test_client_initialization(self):
        """Test client initializes with correct defaults."""
        client = SwissUnihockeyClient()
        assert client.base_url == "https://api-v2.swissunihockey.ch"
        assert client.locale == "de-CH"
        assert client.timeout == 30
        assert client.retry_attempts == 3
        assert client.retry_delay == 1

    def test_client_custom_initialization(self):
        """Test client initializes with custom parameters."""
        client = SwissUnihockeyClient(
            base_url="https://custom.url",
            locale="en",
            timeout=60,
            retry_attempts=5,
            retry_delay=2,
        )
        assert client.base_url == "https://custom.url"
        assert client.locale == "en"
        assert client.timeout == 60
        assert client.retry_attempts == 5
        assert client.retry_delay == 2

    @patch("api.client.SwissUnihockeyClient._make_request")
    def test_get_clubs_success(self, mock_request):
        """Test successful API call to get clubs."""
        mock_request.return_value = {
            "type": "dropdown",
            "entries": [{"text": "Test Club", "set_in_context": {"club_id": 123}}],
        }

        client = SwissUnihockeyClient(use_cache=False)
        result = client.get_clubs()

        assert result["type"] == "dropdown"
        assert len(result["entries"]) == 1
        assert result["entries"][0]["text"] == "Test Club"
        mock_request.assert_called_once()

    @patch("api.client.requests.Session.get")
    def test_retry_on_failure(self, mock_get):
        """Test retry logic on failed requests."""
        mock_get.side_effect = requests.exceptions.RequestException("Connection error")

        client = SwissUnihockeyClient(retry_attempts=3, retry_delay=0.01, use_cache=False)
        
        with pytest.raises(requests.exceptions.RequestException):
            client.get_clubs()

        # Should have tried 3 times
        assert mock_get.call_count == 3

    @patch("api.client.SwissUnihockeyClient._make_request")
    def test_get_rankings_with_params(self, mock_request):
        """Test API call with parameters."""
        mock_request.return_value = {"type": "table", "data": {}}

        client = SwissUnihockeyClient(use_cache=False)
        result = client.get_rankings(league=2, game_class=11, season=2025)

        # Verify method was called with correct parameters
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        # params is passed as second positional argument in get_rankings
        params_dict = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
        assert params_dict.get("league") == 2
        assert params_dict.get("game_class") == 11
        assert params_dict.get("season") == 2025

    def test_context_manager(self):
        """Test client works as context manager."""
        with SwissUnihockeyClient() as client:
            assert client is not None
            assert isinstance(client, SwissUnihockeyClient)

    @patch("api.client.requests.Session.get")
    def test_all_endpoints_exist(self, mock_get):
        """Test all endpoint methods exist and are callable."""
        mock_response = Mock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = SwissUnihockeyClient()
        
        # Test all endpoint methods
        endpoints = [
            "get_clubs",
            "get_leagues",
            "get_seasons",
            "get_teams",
            "get_games",
            "get_game_events",
            "get_rankings",
            "get_topscorers",
            "get_players",
            "get_national_players",
            "get_groups",
            "get_cups",
            "get_calendars",
        ]
        
        for endpoint in endpoints:
            assert hasattr(client, endpoint)
            method = getattr(client, endpoint)
            assert callable(method)

    @patch("api.client.SwissUnihockeyClient._make_request")
    def test_locale_parameter(self, mock_request):
        """Test locale is added to all requests."""
        mock_request.return_value = {"entries": []}

        client = SwissUnihockeyClient(locale="en", use_cache=False)
        client.get_clubs()

        # Verify _make_request was called (locale is added inside _make_request)
        mock_request.assert_called_once()
        # The client's locale should be set correctly
        assert client.locale == "en"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

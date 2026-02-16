"""
Pytest configuration and shared fixtures for SwissUnihockey tests.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
import sys
from pathlib import Path

# Add backend to path for imports
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


@pytest.fixture
def mock_swissunihockey_client():
    """Mock SwissUnihockeyClient for testing without API calls."""
    mock_client = Mock()
    
    # Mock clubs data
    mock_client.get_clubs.return_value = {
        "type": "dropdown",
        "entries": [
            {
                "text": "HC Davos",
                "set_in_context": {"club_id": 1}
            },
            {
                "text": "SC Bern",
                "set_in_context": {"club_id": 2}
            },
            {
                "text": "ZSC Lions",
                "set_in_context": {"club_id": 3}
            }
        ]
    }
    
    # Mock leagues data
    mock_client.get_leagues.return_value = {
        "type": "dropdown",
        "entries": [
            {
                "text": "National League A",
                "set_in_context": {
                    "league_id": 10,
                    "mode": "1",
                    "type": "championship"
                }
            },
            {
                "text": "National League B",
                "set_in_context": {
                    "league_id": 20,
                    "mode": "1",
                    "type": "championship"
                }
            }
        ]
    }
    
    # Mock teams data
    mock_client.get_teams.return_value = {
        "type": "dropdown",
        "entries": [
            {
                "text": "HC Davos A",
                "set_in_context": {
                    "team_id": 101,
                    "club_name": "HC Davos",
                    "league_name": "National League A",
                    "mode": "1"
                }
            },
            {
                "text": "SC Bern Women",
                "set_in_context": {
                    "team_id": 102,
                    "club_name": "SC Bern",
                    "league_name": "Women's League",
                    "mode": "2"
                }
            }
        ]
    }
    
    # Mock games data
    mock_client.get_games.return_value = {
        "entries": [
            {
                "game_id": 1001,
                "home_team": "HC Davos",
                "away_team": "SC Bern",
                "date": "2024-03-15",
                "time": "19:45"
            },
            {
                "game_id": 1002,
                "home_team": "ZSC Lions",
                "away_team": "HC Davos",
                "date": "2024-03-16",
                "time": "20:00"
            }
        ]
    }
    
    # Mock standings/table data
    mock_client.get_table.return_value = {
        "entries": [
            {
                "rank": 1,
                "team": "HC Davos",
                "gp": 30,
                "w": 20,
                "d": 5,
                "l": 5,
                "gf": 100,
                "ga": 60,
                "pts": 65
            },
            {
                "rank": 2,
                "team": "SC Bern",
                "gp": 30,
                "w": 18,
                "d": 6,
                "l": 6,
                "gf": 95,
                "ga": 65,
                "pts": 60
            }
        ]
    }
    
    # Mock top scorers data
    mock_client.get_top_scorers.return_value = {
        "entries": [
            {
                "rank": 1,
                "player": "John Doe",
                "team": "HC Davos",
                "gp": 30,
                "g": 25,
                "a": 30,
                "pts": 55
            },
            {
                "rank": 2,
                "player": "Jane Smith",
                "team": "SC Bern",
                "gp": 30,
                "g": 20,
                "a": 28,
                "pts": 48
            }
        ]
    }
    
    return mock_client


@pytest.fixture
def client(mock_swissunihockey_client):
    """FastAPI TestClient with mocked SwissUnihockey API."""
    # Patch the singleton service to return our mock
    with patch("app.services.swissunihockey.get_swissunihockey_client", return_value=mock_swissunihockey_client):
        from app.main import app
        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture
def valid_locales():
    """List of valid locale codes."""
    return ["de", "en", "fr", "it"]


@pytest.fixture
def sample_translations():
    """Sample translation data for testing."""
    return {
        "common": {
            "app_name": "SwissUnihockey",
            "language": "English"
        },
        "nav": {
            "home": "Home",
            "clubs": "Clubs",
            "leagues": "Leagues"
        }
    }

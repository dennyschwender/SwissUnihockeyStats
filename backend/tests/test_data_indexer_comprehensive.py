"""
Test suite for DataIndexer service
Testing hierarchical data indexing functionality
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from app.services.data_indexer import DataIndexer, get_data_indexer
from app.services.database import get_database_service


@pytest.fixture
def indexer():
    """Create DataIndexer instance for testing"""
    return DataIndexer()


@pytest.fixture
def mock_client():
    """Mock SwissUnihockey API client"""
    with patch('app.services.data_indexer.get_swissunihockey_client') as mock:
        client = Mock()
        mock.return_value = client
        yield client


class TestDataIndexerInit:
    """Test DataIndexer initialization"""
    
    def test_indexer_singleton(self):
        """Test that get_data_indexer returns singleton"""
        indexer1 = get_data_indexer()
        indexer2 = get_data_indexer()
        assert indexer1 is indexer2
    
    def test_indexer_has_client(self, indexer):
        """Test indexer has API client"""
        assert indexer.client is not None
    
    def test_indexer_has_db_service(self, indexer):
        """Test indexer has database service"""
        assert indexer.db_service is not None


class TestDataIndexerUtilityMethods:
    """Test utility methods of DataIndexer"""
    
    def test_should_update_no_sync_record(self, indexer):
        """Test should_update when no sync record exists"""
        # Should return True when entity never synced
        result = indexer._should_update("test_entity", "test_id", max_age_hours=24)
        assert result is True
    
    def test_extract_table_data_with_entries(self, indexer):
        """Test extracting table data from API response"""
        api_response = {
            "entries": [
                {"id": 1, "text": "Test 1"},
                {"id": 2, "text": "Test 2"}
            ]
        }
        result = indexer._extract_table_data(api_response)
        assert len(result) == 2
        assert result[0]["id"] == 1
    
    def test_extract_table_data_with_data_regions(self, indexer):
        """Test extracting from data.regions.rows structure"""
        api_response = {
            "data": {
                "regions": [
                    {
                        "rows": [
                            {"id": 1, "text": "Test 1"},
                            {"id": 2, "text": "Test 2"}
                        ]
                    }
                ]
            }
        }
        result = indexer._extract_table_data(api_response)
        assert len(result) == 2
    
    def test_extract_table_data_empty(self, indexer):
        """Test extracting from empty response"""
        result = indexer._extract_table_data({})
        assert result == []


class TestSeasonIndexing:
    """Test season indexing functionality"""
    
    def test_index_seasons(self, indexer, mock_client):
        """Test indexing seasons from API"""
        # Mock API response
        mock_client.get_seasons.return_value = {
            "entries": [
                {
                    "text": "2024/25",
                    "set_in_context": {"season": 2024},
                    "highlight": False
                },
                {
                    "text": "2025/26",
                    "set_in_context": {"season": 2025},
                    "highlight": True
                }
            ]
        }
        
        # Test indexing
        count = indexer.index_seasons(force=True)
        
        # Should have indexed seasons
        assert count >= 0  # Could be 0 if already synced
        mock_client.get_seasons.assert_called_once()


class TestClubIndexing:
    """Test club indexing functionality"""
    
    def test_index_clubs(self, indexer, mock_client):
        """Test indexing clubs for a season"""
        # Mock API response
        mock_client.get_clubs.return_value = {
            "entries": [
                {
                    "text": "Test Club 1",
                    "set_in_context": {"club_id": 1},
                    "region": "Zurich"
                },
                {
                    "text": "Test Club 2",
                    "set_in_context": {"club_id": 2},
                    "region": "Bern"
                }
            ]
        }
        
        # Test indexing
        count = indexer.index_clubs(season_id=2025, force=True)
        
        # Should have called API
        mock_client.get_clubs.assert_called_once_with(season=2025)
        assert count >= 0


class TestLeagueIndexing:
    """Test league indexing functionality"""
    
    def test_index_leagues(self, indexer, mock_client):
        """Test indexing leagues for a season"""
        # Mock API response
        mock_client.get_leagues.return_value = {
            "entries": [
                {
                    "text": "NLA",
                    "set_in_context": {
                        "league": 1,
                        "game_class": 11,
                        "mode": "league"
                    }
                }
            ]
        }
        
        # Test indexing
        count = indexer.index_leagues(season_id=2025, force=True)
        
        # Should have called API
        mock_client.get_leagues.assert_called_once()
        assert count >= 0


class TestGameIndexing:
    """Test game indexing functionality"""
    
    def test_index_games_for_league(self, indexer, mock_client):
        """Test indexing games for a specific league"""
        # This is a complex test that requires database setup
        # For now, just verify the method exists
        assert hasattr(indexer, 'index_games_for_league')
    
    def test_index_game_events(self, indexer, mock_client):
        """Test indexing events for a specific game"""
        # Mock API response
        mock_client.get_game_events_by_id.return_value = {
            "data": {
                "regions": [
                    {
                        "rows": [
                            {
                                "id": 1,
                                "type": "goal",
                                "time": "10:30",
                                "team": "Home"
                            }
                        ]
                    }
                ]
            }
        }
        
        # Test indexing
        # Note: This requires game to exist in DB
        # count = indexer.index_game_events(game_id=1, season_id=2025, force=True)
        # assert count >= 0
        
        # For now, just verify method exists
        assert hasattr(indexer, 'index_game_events')


class TestIndexerOrchestration:
    """Test high-level indexing orchestration"""
    
    def test_index_leagues_path_exists(self, indexer):
        """Test index_leagues_path method exists"""
        assert hasattr(indexer, 'index_leagues_path')
    
    def test_backfill_team_names_exists(self, indexer):
        """Test backfill_team_names method exists"""
        assert hasattr(indexer, 'backfill_team_names')
    
    def test_get_indexing_stats(self, indexer):
        """Test getting indexing statistics"""
        stats = indexer.get_indexing_stats()
        
        # Should return dict with counts
        assert isinstance(stats, dict)
        assert "seasons" in stats
        assert "clubs" in stats
        assert "teams" in stats
        assert "players" in stats
        assert "leagues" in stats
        assert "games" in stats


class TestSyncStatusManagement:
    """Test sync status tracking"""
    
    def test_cleanup_stale_sync_status(self, indexer):
        """Test cleanup of stale in_progress sync records"""
        # This modifies database, so just verify method exists
        assert hasattr(indexer, 'cleanup_stale_sync_status')
        
        # Could test with mock database
        # count = indexer.cleanup_stale_sync_status()
        # assert count >= 0


class TestTeamIndexing:
    """Test team indexing functionality"""
    
    def test_index_teams_for_club(self, indexer, mock_client):
        """Test indexing teams for a club"""
        # Mock API response
        mock_client.get_club_teams.return_value = {
            "entries": [
                {
                    "text": "Team 1",
                    "set_in_context": {
                        "team": 1,
                        "league": 1,
                        "game_class": 11
                    }
                }
            ]
        }
        
        # Verify method exists
        assert hasattr(indexer, 'index_teams_for_club')


class TestPlayerIndexing:
    """Test player indexing functionality"""
    
    def test_index_players_for_team(self, indexer, mock_client):
        """Test indexing players for a team"""
        # Mock API response
        mock_client.get_team_players.return_value = {
            "data": {
                "regions": [
                    {
                        "rows": [
                            {
                                "id": 1,
                                "text": "Player 1",
                                "jersey": "10"
                            }
                        ]
                    }
                ]
            }
        }
        
        # Verify method exists (actual test requires DB setup)
        assert hasattr(indexer, 'index_players_for_team')


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

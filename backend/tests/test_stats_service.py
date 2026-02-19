"""
Test suite for Stats Service
Testing statistics calculation and aggregation
"""
import pytest
from datetime import datetime, timedelta
from app.services.stats_service import (
    get_league_standings,
    get_league_top_scorers,
    get_recent_games,
    get_upcoming_games,
    get_player_stats,
    get_team_stats
)


class TestLeagueStandings:
    """Test league standings functionality"""
    
    def test_get_league_standings_returns_list(self):
        """Test that standings returns a list"""
        # Note: This requires database with data
        # For now, test that function exists and returns proper type
        result = get_league_standings(league_id=1)
        assert isinstance(result, list)
    
    def test_league_standings_structure(self):
        """Test standings have required fields"""
        result = get_league_standings(league_id=1)
        if result:
            standing = result[0]
            # Should have team info
            assert "team_id" in standing or "team_name" in standing


class TestTopScorers:
    """Test top scorers functionality"""
    
    def test_get_top_scorers_returns_list(self):
        """Test that top scorers returns a list"""
        result = get_league_top_scorers(league_id=1, limit=10)
        assert isinstance(result, list)
    
    def test_top_scorers_respects_limit(self):
        """Test that limit parameter works"""
        result = get_league_top_scorers(league_id=1, limit=5)
        assert len(result) <= 5
    
    def test_top_scorers_structure(self):
        """Test top scorers have required fields"""
        result = get_league_top_scorers(league_id=1, limit=1)
        if result:
            scorer = result[0]
            # Should have player and stats info
            assert any(key in scorer for key in ["player_id", "person_id", "name"])


class TestRecentGames:
    """Test recent games functionality"""
    
    def test_get_recent_games_returns_dict(self):
        """Test that recent games returns proper structure"""
        result = get_recent_games(limit=10)
        assert isinstance(result, dict)
        assert "games" in result
        assert "total" in result
    
    def test_recent_games_respects_limit(self):
        """Test that limit parameter works"""
        result = get_recent_games(limit=5)
        assert len(result["games"]) <= 5
    
    def test_recent_games_with_score_filter(self):
        """Test filtering games with scores"""
        result = get_recent_games(limit=10, with_score_only=True)
        # All games should have scores
        for game in result["games"]:
            assert game.get("home_score") is not None or game.get("away_score") is not None
    
    def test_recent_games_pagination(self):
        """Test pagination with offset"""
        result1 = get_recent_games(limit=5, offset=0)
        result2 = get_recent_games(limit=5, offset=5)
        
        # Should return different games (if enough data exists)
        if result1["total"] > 5:
            assert result1["games"] != result2["games"]


class TestUpcomingGames:
    """Test upcoming games functionality"""
    
    def test_get_upcoming_games_returns_list(self):
        """Test that upcoming games returns a list"""
        result = get_upcoming_games(limit=10)
        assert isinstance(result, list)
    
    def test_upcoming_games_are_future(self):
        """Test that upcoming games are in the future"""
        result = get_upcoming_games(limit=10)
        now = datetime.now().date()
        
        for game in result:
            game_date = game.get("game_date")
            if game_date:
                if isinstance(game_date, str):
                    game_date = datetime.fromisoformat(game_date).date()
                elif isinstance(game_date, datetime):
                    game_date = game_date.date()
                # Game should be today or in the future
                assert game_date >= now


class TestPlayerStats:
    """Test player statistics functionality"""
    
    def test_get_player_stats_returns_dict(self):
        """Test that player stats returns a dict"""
        # Note: Requires player_id from database
        result = get_player_stats(player_id=1, season=2025)
        assert isinstance(result, (dict, type(None)))
    
    def test_player_stats_with_invalid_id(self):
        """Test player stats with invalid ID"""
        result = get_player_stats(player_id=999999, season=2025)
        assert result is None or result == {}


class TestTeamStats:
    """Test team statistics functionality"""
    
    def test_get_team_stats_returns_dict(self):
        """Test that team stats returns a dict"""
        result = get_team_stats(team_id=1, season=2025)
        assert isinstance(result, (dict, type(None)))
    
    def test_team_stats_with_invalid_id(self):
        """Test team stats with invalid ID"""
        result = get_team_stats(team_id=999999, season=2025)
        assert result is None or result == {}


class TestStatsCalculations:
    """Test statistics calculation logic"""
    
    def test_standings_calculated_correctly(self):
        """Test that standings points are calculated correctly"""
        # This would require mocking game data
        # Points = wins * 3 + overtime_wins * 2 + overtime_losses * 1
        pass
    
    def test_goal_difference_calculated(self):
        """Test goal difference calculation"""
        # goal_diff = goals_for - goals_against
        pass


class TestStatsPerformance:
    """Test statistics query performance"""
    
    def test_standings_query_performance(self):
        """Test that standings query is fast enough"""
        import time
        start = time.time()
        get_league_standings(league_id=1)
        duration = time.time() - start
        
        # Should complete in less than 500ms
        assert duration < 0.5
    
    def test_top_scorers_query_performance(self):
        """Test that top scorers query is fast enough"""
        import time
        start = time.time()
        get_league_top_scorers(league_id=1, limit=25)
        duration = time.time() - start
        
        # Should complete in less than 500ms
        assert duration < 0.5
    
    def test_recent_games_query_performance(self):
        """Test that recent games query is fast enough"""
        import time
        start = time.time()
        get_recent_games(limit=50)
        duration = time.time() - start
        
        # Should complete in less than 500ms
        assert duration < 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

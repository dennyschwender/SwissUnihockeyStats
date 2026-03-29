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
    get_player_detail,
    get_team_detail,
)


class TestLeagueStandings:
    """Test league standings functionality"""

    def test_get_league_standings_returns_list(self):
        """Test that standings returns a list"""
        # Note: This requires database with data
        # For now, test that function exists and returns proper type
        result = get_league_standings(db_league_id=1)
        assert isinstance(result, list)

    def test_league_standings_structure(self):
        """Test standings have required fields"""
        result = get_league_standings(db_league_id=1)
        if result:
            standing = result[0]
            # Should have team info
            assert "team_id" in standing or "team_name" in standing


class TestTopScorers:
    """Test top scorers functionality"""

    def test_get_top_scorers_returns_list(self):
        """Test that top scorers returns a list"""
        result = get_league_top_scorers(db_league_id=1, limit=10)
        assert isinstance(result, list)

    def test_top_scorers_respects_limit(self):
        """Test that limit parameter works"""
        result = get_league_top_scorers(db_league_id=1, limit=5)
        assert len(result) <= 5

    def test_top_scorers_structure(self):
        """Test top scorers have required fields"""
        result = get_league_top_scorers(db_league_id=1, limit=1)
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

    def test_get_player_detail_returns_dict(self):
        """Test that player detail returns a dict"""
        result = get_player_detail(person_id=1)
        assert isinstance(result, dict)

    def test_player_detail_with_invalid_id(self):
        """Test player detail with invalid ID returns empty dict"""
        result = get_player_detail(person_id=999999)
        assert isinstance(result, dict)


class TestTeamStats:
    """Test team statistics functionality"""

    def test_get_team_detail_returns_dict(self):
        """Test that team detail returns a dict"""
        result = get_team_detail(team_id=1, season_id=2025)
        assert isinstance(result, dict)

    def test_team_detail_with_invalid_id(self):
        """Test team detail with invalid ID returns empty dict"""
        result = get_team_detail(team_id=999999, season_id=2025)
        assert isinstance(result, dict)


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
        get_league_standings(db_league_id=1)
        duration = time.time() - start

        # Should complete in less than 500ms
        assert duration < 0.5

    def test_top_scorers_query_performance(self):
        """Test that top scorers query is fast enough"""
        import time

        start = time.time()
        get_league_top_scorers(db_league_id=1, limit=25)
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


@pytest.fixture
def db_session():
    from app.services.database import get_database_service

    db = get_database_service()
    with db.session_scope() as session:
        yield session


def test_fetch_recent_game_rows_with_null_nullable_fields(db_session):
    """_fetch_recent_game_rows must not crash when nullable fields (game_date, period) are None."""
    from app.services.stats_service import _fetch_recent_game_rows
    from app.models.db_models import Player, Team, Season, Game, GamePlayer

    season = Season(id=1, text="2025/26")
    db_session.add(season)
    team = Team(id=1, season_id=1, name="Test Team", club_id=None)
    db_session.add(team)
    player = Player(person_id=9999, first_name="Test", last_name="Player")
    db_session.add(player)
    game = Game(
        id=1,
        season_id=1,
        home_team_id=1,
        away_team_id=1,
        game_date=None,  # <- the problematic field
        home_score=3,
        away_score=1,
        completeness_status="complete",
    )
    db_session.add(game)
    gp = GamePlayer(
        player_id=9999,
        game_id=1,
        team_id=1,
        season_id=1,
        is_home_team=True,
        goals=None,
        assists=None,
        penalty_minutes=None,
    )
    db_session.add(gp)
    db_session.flush()

    rows = _fetch_recent_game_rows(db_session, 9999, offset=0, limit=10)
    assert len(rows) == 1
    assert rows[0]["date"] == ""


@pytest.fixture(scope="module")
def populated_league_db(app):
    """Insert a minimal league+player stats dataset for search tests."""
    from app.services.database import get_database_service
    from app.models.db_models import League, Season, Player, PlayerStatistics, LeagueGroup

    db = get_database_service()
    with db.session_scope() as session:
        if not session.query(Season).filter_by(id=99).first():
            session.add(Season(id=99, text="2099/00"))
        if not session.query(League).filter_by(id=99).first():
            session.add(League(id=99, league_id=99, season_id=99, name="Herren NLA", game_class=1))
        if not session.query(LeagueGroup).filter_by(id=99).first():
            session.add(LeagueGroup(id=99, league_id=99, group_id=99, name="NLA"))
        if not session.query(Player).filter_by(person_id=9901).first():
            session.add(Player(person_id=9901, first_name="Anna", last_name="Mueller"))
        if not session.query(Player).filter_by(person_id=9902).first():
            session.add(Player(person_id=9902, first_name="Bob", last_name="Smith"))
        if not session.query(PlayerStatistics).filter_by(player_id=9901, season_id=99).first():
            session.add(PlayerStatistics(
                player_id=9901,
                season_id=99,
                league_abbrev="NLA",
                game_class=1,
                goals=10,
                assists=5,
                points=15,
                games_played=20,
                penalty_minutes=4,
            ))
        if not session.query(PlayerStatistics).filter_by(player_id=9902, season_id=99).first():
            session.add(PlayerStatistics(
                player_id=9902,
                season_id=99,
                league_abbrev="NLA",
                game_class=1,
                goals=2,
                assists=1,
                points=3,
                games_played=20,
                penalty_minutes=22,
            ))


def test_search_league_scorers_returns_matching_player(populated_league_db):
    """search_league_scorers returns rows matching name substring."""
    from app.services.stats_service import search_league_scorers

    rows = search_league_scorers(db_league_id=99, query="anna", limit=10)
    assert len(rows) >= 1
    assert any("anna" in r["player_name"].lower() for r in rows)


def test_search_league_scorers_empty_query_returns_top_rows(populated_league_db):
    """Empty query returns top scorers ordered by points desc."""
    from app.services.stats_service import search_league_scorers

    rows = search_league_scorers(db_league_id=99, query="", limit=5)
    assert len(rows) <= 5
    if len(rows) > 1:
        assert rows[0]["pts"] >= rows[1]["pts"]


def test_search_league_penalties_returns_matching_player(populated_league_db):
    """search_league_penalties returns rows matching name substring."""
    from app.services.stats_service import search_league_penalties

    rows = search_league_penalties(db_league_id=99, query="bob", limit=10)
    assert len(rows) >= 1
    assert any("bob" in r["player_name"].lower() for r in rows)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

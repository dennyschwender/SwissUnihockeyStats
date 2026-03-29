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


class TestTeamRosterPPG:
    """Test that roster player dicts include ppg field."""

    def test_ppg_present_in_roster_dicts(self):
        from app.services.database import get_database_service
        from app.models.db_models import Team, Season
        db = get_database_service()
        with db.session_scope() as session:
            season = session.query(Season).first()
            if not season:
                pytest.skip("No season in DB")
            team = session.query(Team).filter(Team.season_id == season.id).first()
            if not team:
                pytest.skip("No team in DB")
            team_id = team.id
            season_id = season.id

        result = get_team_detail(team_id=team_id, season_id=season_id)
        roster = result.get("roster", [])
        if not roster:
            pytest.skip("No roster players")
        for p in roster:
            assert "ppg" in p, f"ppg key missing from player dict: {p}"

    def test_ppg_is_none_when_gp_is_zero(self):
        from app.services.stats_service import _compute_ppg
        assert _compute_ppg(10, 0) is None
        assert _compute_ppg(0, 0) is None

    def test_ppg_rounded_to_two_decimals(self):
        from app.services.stats_service import _compute_ppg
        result = _compute_ppg(10, 3)
        assert result == 3.33


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])


class TestBuildSeriesRounds:
    """Test _build_series_rounds returns grouped phase structure."""

    def test_returns_list_of_phase_dicts(self):
        from app.services.stats_service import _build_series_rounds
        from app.services.database import get_database_service
        from app.models.db_models import LeagueGroup
        db = get_database_service()
        with db.session_scope() as session:
            groups = session.query(LeagueGroup).limit(2).all()
            if not groups:
                pytest.skip("No LeagueGroup rows in DB")
            group_ids = [g.id for g in groups]
            season_id = groups[0].league.season_id if groups[0].league else 2025
            result = _build_series_rounds(group_ids, season_id, session)
        assert isinstance(result, list)
        for phase in result:
            assert "phase_name" in phase
            assert "series_list" in phase
            assert isinstance(phase["series_list"], list)

    def test_empty_group_ids_returns_empty_list(self):
        from app.services.stats_service import _build_series_rounds
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            result = _build_series_rounds([], 2025, session)
        assert result == []

    def test_series_have_required_keys(self):
        from app.services.stats_service import _build_series_rounds
        from app.services.database import get_database_service
        from app.models.db_models import LeagueGroup, Game
        db = get_database_service()
        with db.session_scope() as session:
            grp = (
                session.query(LeagueGroup)
                .join(Game, Game.group_id == LeagueGroup.id)
                .first()
            )
            if not grp:
                pytest.skip("No LeagueGroup with games")
            result = _build_series_rounds([grp.id], grp.league.season_id if grp.league else 2025, session)
        if not result or not result[0]["series_list"]:
            pytest.skip("No series in result")
        s = result[0]["series_list"][0]
        for key in ("team_a_id", "team_b_id", "team_a_name", "team_b_name",
                    "team_a_wins", "team_b_wins", "games"):
            assert key in s, f"Missing key {key} in series dict"


class TestCareerBySeason:
    """Test career_by_season grouping in get_player_detail."""

    def _seed_player_with_two_seasons(self, session):
        from app.models.db_models import Player, Season, PlayerStatistics
        s1 = Season(id=2024, text="2023/24", highlighted=False)
        s2 = Season(id=2025, text="2024/25", highlighted=True)
        session.merge(s1)
        session.merge(s2)
        p = Player(person_id=9001, full_name="Test Player")
        session.merge(p)
        session.flush()
        session.merge(PlayerStatistics(
            id=90011, player_id=9001, season_id=2025,
            league_abbrev="NLA", team_name="Team A",
            games_played=10, goals=5, assists=3, points=8, penalty_minutes=4,
        ))
        session.merge(PlayerStatistics(
            id=90012, player_id=9001, season_id=2025,
            league_abbrev="NLB", team_name="Team B",
            games_played=5, goals=1, assists=2, points=3, penalty_minutes=2,
        ))
        session.merge(PlayerStatistics(
            id=90013, player_id=9001, season_id=2024,
            league_abbrev="NLA", team_name="Team A",
            games_played=20, goals=10, assists=8, points=18, penalty_minutes=6,
        ))
        session.commit()

    def test_career_by_season_present(self, db_session):
        self._seed_player_with_two_seasons(db_session)
        from app.services.stats_service import get_player_detail
        result = get_player_detail(person_id=9001)
        assert "career_by_season" in result

    def test_career_by_season_ordered_desc(self, db_session):
        self._seed_player_with_two_seasons(db_session)
        from app.services.stats_service import get_player_detail
        result = get_player_detail(person_id=9001)
        seasons = result["career_by_season"]
        assert len(seasons) == 2
        assert seasons[0]["season_id"] == 2025
        assert seasons[1]["season_id"] == 2024

    def test_career_by_season_totals_aggregated(self, db_session):
        self._seed_player_with_two_seasons(db_session)
        from app.services.stats_service import get_player_detail
        result = get_player_detail(person_id=9001)
        season_2025 = result["career_by_season"][0]
        assert season_2025["totals"]["gp"] == 15   # 10 + 5
        assert season_2025["totals"]["g"] == 6     # 5 + 1
        assert season_2025["totals"]["a"] == 5     # 3 + 2
        assert season_2025["totals"]["pts"] == 11  # 8 + 3
        assert len(season_2025["rows"]) == 2

    def test_career_by_season_single_row_season(self, db_session):
        self._seed_player_with_two_seasons(db_session)
        from app.services.stats_service import get_player_detail
        result = get_player_detail(person_id=9001)
        season_2024 = result["career_by_season"][1]
        assert len(season_2024["rows"]) == 1


class TestBuildTimelineEvents:
    """Test build_timeline_events includes score, minutes, infraction fields."""

    def test_goal_event_includes_score(self):
        from app.services.stats_service import build_timeline_events
        goals = [{"period": 1, "time": "05:00", "score": "1:0", "team": "Home", "player": "Player A"}]
        events, _ = build_timeline_events(goals, [], "Home", "Away")
        goal_ev = next(e for e in events if e["kind"] == "goal")
        assert "score" in goal_ev
        assert goal_ev["score"] == "1:0"

    def test_penalty_event_includes_minutes_and_infraction(self):
        from app.services.stats_service import build_timeline_events
        pens = [{"period": 1, "time": "03:00", "minutes": 2, "infraction": "Hooking", "team": "Home", "player": "Player B"}]
        events, _ = build_timeline_events([], pens, "Home", "Away")
        pen_ev = next(e for e in events if e["kind"] == "penalty")
        assert "minutes" in pen_ev
        assert pen_ev["minutes"] == 2
        assert "infraction" in pen_ev
        assert pen_ev["infraction"] == "Hooking"

    def test_penalty_missing_infraction_defaults_to_empty_string(self):
        from app.services.stats_service import build_timeline_events
        pens = [{"period": 1, "time": "03:00", "minutes": 5, "team": "Away", "player": "X"}]
        events, _ = build_timeline_events([], pens, "Home", "Away")
        pen_ev = events[0]
        assert pen_ev["infraction"] == ""

    def test_goal_missing_score_defaults_to_empty_string(self):
        from app.services.stats_service import build_timeline_events
        goals = [{"period": 1, "time": "05:00", "team": "Home", "player": "X"}]
        events, _ = build_timeline_events(goals, [], "Home", "Away")
        goal_ev = events[0]
        assert goal_ev["score"] == ""


class TestGetRefereeGames:
    """Test get_referee_games returns correct structure."""

    def _seed_referee_games(self, session):
        from app.models.db_models import Game, Season, Team
        from datetime import datetime
        session.merge(Season(id=2025, text="2024/25", highlighted=True))
        session.flush()
        for tid, tname in [(901, "Team A"), (902, "Team B"), (903, "Team C"),
                           (904, "Team D"), (905, "Team E"), (906, "Team F")]:
            session.merge(Team(id=tid, season_id=2025, name=tname))
        session.flush()
        session.merge(Game(
            id=5001, season_id=2025,
            home_team_id=901, away_team_id=902,
            home_score=3, away_score=2,
            referee_1="John Referee",
            game_date=datetime(2025, 1, 15),
        ))
        session.merge(Game(
            id=5002, season_id=2025,
            home_team_id=903, away_team_id=904,
            home_score=1, away_score=1,
            referee_2="John Referee",
            game_date=datetime(2025, 2, 10),
        ))
        session.merge(Game(
            id=5003, season_id=2025,
            home_team_id=905, away_team_id=906,
            home_score=None, away_score=None,
            referee_1="Other Referee",
            game_date=datetime(2025, 3, 1),
        ))
        session.flush()

    def test_returns_games_for_referee(self, db_session):
        self._seed_referee_games(db_session)
        from app.services.stats_service import get_referee_games
        result = get_referee_games("John Referee", db_session)
        assert result["name"] == "John Referee"
        assert result["total"] == 2

    def test_matches_referee_1_and_referee_2(self, db_session):
        self._seed_referee_games(db_session)
        from app.services.stats_service import get_referee_games
        result = get_referee_games("John Referee", db_session)
        game_ids = [g["game_id"] for g in result["games"]]
        assert 5001 in game_ids
        assert 5002 in game_ids
        assert 5003 not in game_ids

    def test_no_games_for_unknown_referee(self, db_session):
        from app.services.stats_service import get_referee_games
        result = get_referee_games("Nobody Here", db_session)
        assert result["total"] == 0
        assert result["games"] == []


class TestGetCoachDetail:
    """Test get_coach_detail returns correct structure."""

    def _seed_coach(self, session):
        from app.models.db_models import Staff, Season, Team
        session.merge(Season(id=2025, text="2024/25", highlighted=True))
        session.merge(Season(id=2024, text="2023/24", highlighted=False))
        session.merge(Team(id=201, season_id=2025, name="Team X"))
        session.flush()
        session.merge(Staff(
            id=401, season_id=2025, team_id=201, team_name="Team X",
            first_name="Anna", last_name="Coach", role="Headcoach",
        ))
        session.merge(Staff(
            id=401, season_id=2024, team_id=201, team_name="Team X",
            first_name="Anna", last_name="Coach", role="Headcoach",
        ))
        session.flush()

    def test_returns_coach_dict(self, db_session):
        self._seed_coach(db_session)
        from app.services.stats_service import get_coach_detail
        result = get_coach_detail(401, db_session)
        assert result is not None
        assert result["name"] == "Anna Coach"
        assert result["person_id"] == 401

    def test_seasons_ordered_desc(self, db_session):
        self._seed_coach(db_session)
        from app.services.stats_service import get_coach_detail
        result = get_coach_detail(401, db_session)
        season_ids = [s["season_id"] for s in result["seasons"]]
        assert season_ids == sorted(season_ids, reverse=True)

    def test_unknown_coach_returns_none(self, db_session):
        from app.services.stats_service import get_coach_detail
        result = get_coach_detail(999999, db_session)
        assert result is None

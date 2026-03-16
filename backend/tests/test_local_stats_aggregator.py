"""Unit tests for local_stats_aggregator."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from unittest.mock import MagicMock
from contextlib import contextmanager

from app.models.db_models import (
    Base,
    Season,
    Club,
    Team,
    League,
    LeagueGroup,
    Game,
    GamePlayer,
    GameEvent,
    Player,
    PlayerStatistics,
    UnresolvedPlayerEvent,
    _utcnow,
)
from app.services.local_stats_aggregator import (
    _pen_bucket,
    aggregate_player_stats_for_season,
)


@pytest.fixture
def engine():
    e = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture
def mock_db(engine):
    db = MagicMock()

    @contextmanager
    def session_scope():
        with Session(engine) as s:
            yield s
            s.commit()

    db.session_scope = session_scope
    db.engine = engine
    return db


def _seed_complete_game(engine, tier=1):
    """Seed a minimal complete game with one player scoring a goal and getting a penalty."""
    with Session(engine) as s:
        season = Season(id=1, text="2025")
        s.add(season)
        s.flush()
        club = Club(id=1, season_id=1, name="TestClub")
        s.add(club)
        s.flush()
        team = Team(id=1, season_id=1, club_id=1, name="TestTeam", league_id=1)
        s.add(team)
        s.flush()
        league = League(id=1, season_id=1, league_id=1, game_class=1, name="NLA")
        s.add(league)
        s.flush()
        group = LeagueGroup(id=1, league_id=1, group_id=10, name="NLA")
        s.add(group)
        s.flush()
        player = Player(person_id=42, first_name="Max", last_name="Muster")
        s.add(player)
        s.flush()
        game = Game(
            id=1,
            season_id=1,
            home_team_id=1,
            away_team_id=1,
            status="finished",
            completeness_status="complete",
            home_score=3,
            away_score=1,
            group_id=1,
        )
        s.add(game)
        s.flush()
        gp = GamePlayer(
            game_id=1,
            player_id=42,
            team_id=1,
            season_id=1,
            is_home_team=True,
            goals=2,
            assists=1,
            penalty_minutes=2,
        )
        s.add(gp)
        # Goal event with matching player name
        ge_goal = GameEvent(
            game_id=1,
            team_id=1,
            season_id=1,
            event_type="Torschütze",
            raw_data={
                "player": "Max Muster",
                "event_type": "Torschütze",
                "time": "10:00",
                "team": "TestTeam",
            },
        )
        # Penalty event
        ge_pen = GameEvent(
            game_id=1,
            team_id=1,
            season_id=1,
            event_type="2'-Strafe",
            raw_data={
                "player": "Max Muster",
                "event_type": "2'-Strafe",
                "time": "15:00",
                "team": "TestTeam",
            },
        )
        s.add_all([ge_goal, ge_pen])
        s.commit()


# ── _pen_bucket tests ─────────────────────────────────────────────────────────


def test_pen_bucket_2min():
    assert _pen_bucket("2'-Strafe") == "2min"


def test_pen_bucket_5min():
    assert _pen_bucket("5'-Strafe") == "5min"


def test_pen_bucket_10min():
    assert _pen_bucket("10'-Strafe") == "10min"


def test_pen_bucket_match():
    assert _pen_bucket("Matchstrafe") == "match"


def test_pen_bucket_technische():
    assert _pen_bucket("Technische Matchstrafe") == "match"


def test_pen_bucket_unknown():
    assert _pen_bucket("Timeout") is None


# ── aggregate_player_stats_for_season tests ───────────────────────────────────


def test_aggregate_creates_player_statistics_row(engine, mock_db):
    _seed_complete_game(engine)
    count = aggregate_player_stats_for_season(mock_db, season_id=1, tiers=[1, 2, 3])
    assert count >= 1
    with Session(engine) as s:
        row = s.query(PlayerStatistics).filter_by(player_id=42, season_id=1).first()
        assert row is not None
        assert row.goals == 2
        assert row.assists == 1
        assert row.games_played == 1
        assert row.computed_from_local is True
        assert row.local_computed_at is not None


def test_aggregate_pen_breakdown_t1(engine, mock_db):
    _seed_complete_game(engine, tier=1)
    aggregate_player_stats_for_season(mock_db, season_id=1, tiers=[1])
    with Session(engine) as s:
        row = s.query(PlayerStatistics).filter_by(player_id=42, season_id=1).first()
        assert row.pen_2min == 1


def test_aggregate_skips_non_complete_games(engine, mock_db):
    _seed_complete_game(engine)
    # Mark game as post_game (incomplete)
    with Session(engine) as s:
        g = s.get(Game, 1)
        g.completeness_status = "post_game"
        s.commit()
    count = aggregate_player_stats_for_season(mock_db, season_id=1, tiers=[1, 2, 3])
    assert count == 0


def test_aggregate_no_games_returns_zero(engine, mock_db):
    # Empty DB
    with Session(engine) as s:
        s.add(Season(id=1, text="2025"))
        s.commit()
    count = aggregate_player_stats_for_season(mock_db, season_id=1, tiers=[1, 2, 3])
    assert count == 0


def test_unresolved_event_created_for_unknown_player(engine, mock_db):
    _seed_complete_game(engine)
    # Add a penalty event with a name that doesn't match any GamePlayer
    with Session(engine) as s:
        ge = GameEvent(
            game_id=1,
            team_id=1,
            season_id=1,
            event_type="2'-Strafe",
            raw_data={
                "player": "Unknown Player",
                "event_type": "2'-Strafe",
                "time": "20:00",
                "team": "TestTeam",
            },
        )
        s.add(ge)
        s.commit()
    aggregate_player_stats_for_season(mock_db, season_id=1, tiers=[1])
    with Session(engine) as s:
        unresolved = s.query(UnresolvedPlayerEvent).filter_by(game_id=1).all()
        assert any(u.raw_name == "Unknown Player" for u in unresolved)

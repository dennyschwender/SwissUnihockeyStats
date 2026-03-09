"""Tests for the game_lineups scheduler policy entry."""
from datetime import timedelta

from app.services.scheduler import POLICIES


def _policy(name: str) -> dict:
    return next(p for p in POLICIES if p["name"] == name)


def test_game_lineups_policy_exists():
    names = [p["name"] for p in POLICIES]
    assert "game_lineups" in names


def test_game_lineups_policy_shape():
    p = _policy("game_lineups")
    assert p["priority"] == 75
    assert p["task"] == "game_lineups"
    assert p["scope"] == "season"
    assert p["max_tier"] == 2
    assert p["run_at_hour"] == 3
    assert p["max_age"] == timedelta(hours=24)


def test_game_lineups_policy_ordering():
    games_priority = _policy("games")["priority"]
    game_lineups_priority = _policy("game_lineups")["priority"]
    game_events_priority = _policy("game_events")["priority"]

    assert games_priority < game_lineups_priority < game_events_priority

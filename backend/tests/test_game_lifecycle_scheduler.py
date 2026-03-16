"""Tests for game lifecycle scheduler policies."""

import pytest
from app.services.scheduler import POLICIES


def _policy_names():
    """Extract all policy names/identifiers from POLICIES."""
    if isinstance(POLICIES, dict):
        return set(POLICIES.keys())
    elif isinstance(POLICIES, list):
        return {p.get("name") or p.get("job") for p in POLICIES}
    return set()


def test_old_policies_removed():
    names = _policy_names()
    assert "games" not in names, "Old 'games' policy should be removed"
    assert "game_lineups" not in names, "Old 'game_lineups' policy should be removed"
    assert "game_events" not in names, "Old 'game_events' policy should be removed"


def test_upcoming_games_policies_exist():
    names = _policy_names()
    assert any("upcoming_games" in str(n) for n in names), "upcoming_games policy must exist"


def test_post_game_completion_policy_exists():
    names = _policy_names()
    assert any(
        "post_game_completion" in str(n) for n in names
    ), "post_game_completion policy must exist"


def test_upcoming_games_has_three_daily_triggers():
    """There should be exactly 3 upcoming_games policies (noon, evening, night)."""
    if isinstance(POLICIES, list):
        upcoming = [
            p
            for p in POLICIES
            if "upcoming_games" in str(p.get("name", ""))
            or "upcoming_games" in str(p.get("task", ""))
        ]
        assert (
            len(upcoming) == 3
        ), f"Expected 3 upcoming_games policies, got {len(upcoming)}: {upcoming}"
    elif isinstance(POLICIES, dict):
        upcoming = [k for k in POLICIES if "upcoming_games" in k]
        assert len(upcoming) == 3


def test_post_game_completion_runs_every_2_hours():
    """post_game_completion policy should have max_age of 2 hours."""
    if isinstance(POLICIES, list):
        post_game = next(
            (
                p
                for p in POLICIES
                if "post_game_completion" in str(p.get("name", ""))
                or "post_game_completion" in str(p.get("task", ""))
            ),
            None,
        )
        assert post_game is not None
        from datetime import timedelta

        max_age = post_game.get("max_age")
        assert max_age == timedelta(hours=2), f"Expected 2-hour interval, got {max_age}"


def test_upcoming_games_run_at_hours():
    """upcoming_games policies should run at hours 12, 18, and 23."""
    if isinstance(POLICIES, list):
        upcoming = [
            p
            for p in POLICIES
            if "upcoming_games" in str(p.get("name", ""))
            or "upcoming_games" in str(p.get("task", ""))
        ]
        hours = {p.get("run_at_hour") for p in upcoming}
        assert hours == {12, 18, 23}, f"Expected run hours {{12, 18, 23}}, got {hours}"

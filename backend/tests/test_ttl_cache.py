"""Tests for the in-memory TTL cache module."""
import threading
import time
from unittest.mock import patch

from app.services.cache import get_cached, set_cached, invalidate_prefix, _cache, _lock


def _clear_cache():
    """Helper: clear all cache entries between tests."""
    with _lock:
        _cache.clear()


def test_set_and_get_returns_value():
    _clear_cache()
    set_cached(("standings", 1, 2025), {"data": "result"})
    result = get_cached(("standings", 1, 2025))
    assert result == {"data": "result"}


def test_get_returns_none_for_missing_key():
    _clear_cache()
    assert get_cached(("standings", 999, 2025)) is None


def test_get_returns_none_after_ttl_expiry():
    _clear_cache()
    with patch("app.services.cache._TTL", 0.05):  # 50ms TTL for test
        set_cached(("top_scorers", None, 20), [1, 2, 3])
        time.sleep(0.1)
        assert get_cached(("top_scorers", None, 20)) is None


def test_get_returns_value_within_ttl():
    _clear_cache()
    with patch("app.services.cache._TTL", 60):
        set_cached(("top_scorers", None, 20), [1, 2, 3])
        assert get_cached(("top_scorers", None, 20)) == [1, 2, 3]


def test_invalidate_prefix_removes_matching_keys():
    _clear_cache()
    set_cached(("standings", 1, 2025), "a")
    set_cached(("standings", 2, 2025), "b")
    set_cached(("league_scorers", 1, 2025), "c")
    invalidate_prefix("standings")
    assert get_cached(("standings", 1, 2025)) is None
    assert get_cached(("standings", 2, 2025)) is None
    assert get_cached(("league_scorers", 1, 2025)) == "c"


def test_invalidate_prefix_leaves_unrelated_keys():
    _clear_cache()
    set_cached(("top_scorers", None, 20), [1])
    set_cached(("standings", 1, 2025), "a")
    invalidate_prefix("standings")
    assert get_cached(("top_scorers", None, 20)) == [1]


def test_cache_key_with_tuple_arg():
    """Cache key containing a tuple (e.g. only_group_ids) works correctly."""
    _clear_cache()
    key_a = ("standings", 1, 2025, (1, 2))
    key_b = ("standings", 1, 2025, (2, 1))  # different order = different key
    set_cached(key_a, "result_a")
    assert get_cached(key_a) == "result_a"
    assert get_cached(key_b) is None


class TestStatsCacheFunctions:
    """get_upcoming_games and get_latest_results use the TTL cache."""

    def setup_method(self):
        _clear_cache()

    def test_get_upcoming_games_returns_cached_on_second_call(self, app):
        """Second call returns the cached result without hitting the DB again."""
        from app.services.stats_service import get_upcoming_games
        from app.services import cache as _cache

        # Prime cache with a fake entry for this key
        key = ("upcoming_games", 2025, None, 12)
        fake = [{"id": 999}]
        _cache.set_cached(key, fake)

        result = get_upcoming_games(limit=12, season_id=2025)
        assert result == fake

        # Cleanup
        _cache.invalidate_prefix("upcoming_games")

    def test_get_latest_results_returns_cached_on_second_call(self, app):
        """Second call returns the cached result without hitting the DB again."""
        from app.services.stats_service import get_latest_results
        from app.services import cache as _cache

        key = ("latest_results", 2025, None, 12)
        fake = [{"id": 888, "home_team": "A", "away_team": "B"}]
        _cache.set_cached(key, fake)

        result = get_latest_results(limit=12, season_id=2025)
        assert result == fake

        _cache.invalidate_prefix("latest_results")


def test_thread_safety_concurrent_set_and_invalidate():
    """Concurrent set from one thread and invalidate from another must not raise."""
    _clear_cache()
    errors = []

    def writer():
        for i in range(50):
            try:
                set_cached(("standings", i, 2025), f"data_{i}")
            except Exception as e:
                errors.append(e)

    def invalidator():
        for _ in range(10):
            try:
                invalidate_prefix("standings")
            except Exception as e:
                errors.append(e)

    t1 = threading.Thread(target=writer)
    t2 = threading.Thread(target=invalidator)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert errors == [], f"Thread safety errors: {errors}"

"""
Unit tests for DataCache (no network calls).
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta


def _make_client_mock():
    mock = MagicMock()
    mock.get_clubs.return_value = {
        "entries": [{"id": 1, "text": "SC Zurich"}, {"id": 2, "text": "HC Bern"}]
    }
    mock.get_leagues.return_value = {
        "entries": [{"id": 1, "text": "NLA"}, {"id": 2, "text": "NLB"}]
    }
    mock.get_teams.return_value = {"entries": []}
    return mock


@pytest.fixture
def cache():
    """Return a fresh DataCache instance for each test."""
    from app.services.data_cache import DataCache

    return DataCache()


@pytest.fixture
def client_mock():
    return _make_client_mock()


class TestDataCacheClubs:
    async def test_load_clubs_populates_list(self, cache, client_mock):
        with patch("app.services.data_cache.get_swissunihockey_client", return_value=client_mock):
            await cache.load_clubs()
        assert len(cache._clubs) == 2
        assert cache._clubs_loaded is True
        assert cache._clubs_loaded_at is not None

    async def test_load_clubs_idempotent_within_ttl(self, cache, client_mock):
        """Calling load_clubs twice within TTL should only call the API once."""
        with patch("app.services.data_cache.get_swissunihockey_client", return_value=client_mock):
            await cache.load_clubs()
            await cache.load_clubs()
        assert client_mock.get_clubs.call_count == 1

    async def test_load_clubs_refreshes_after_ttl(self, cache, client_mock):
        """After TTL expires the cache should reload from the API."""
        with patch("app.services.data_cache.get_swissunihockey_client", return_value=client_mock):
            await cache.load_clubs()
            # Artificially age the timestamp
            cache._clubs_loaded_at = datetime.now() - timedelta(days=8)
            await cache.load_clubs()
        assert client_mock.get_clubs.call_count == 2

    async def test_get_clubs_triggers_load(self, cache, client_mock):
        with patch("app.services.data_cache.get_swissunihockey_client", return_value=client_mock):
            result = await cache.get_clubs()
        assert len(result) == 2

    async def test_load_clubs_error_leaves_empty(self, cache):
        err_mock = MagicMock()
        err_mock.get_clubs.side_effect = RuntimeError("API down")
        with patch("app.services.data_cache.get_swissunihockey_client", return_value=err_mock):
            with pytest.raises(RuntimeError):
                await cache.load_clubs()
        assert cache._clubs == []


class TestDataCacheLeagues:
    async def test_load_leagues_populates_list(self, cache, client_mock):
        with patch("app.services.data_cache.get_swissunihockey_client", return_value=client_mock):
            await cache.load_leagues()
        assert len(cache._leagues) == 2
        assert cache._leagues_loaded is True


class TestDataCacheTeamExtraction:
    def test_extract_teams_nested_structure(self):
        from app.services.data_cache import DataCache

        data = {"data": {"regions": [{"rows": [{"id": 1, "cells": [{"text": ["Team A"]}]}]}]}}
        rows = DataCache._extract_teams(data)
        assert len(rows) == 1

    def test_extract_teams_flat_entries(self):
        from app.services.data_cache import DataCache

        data = {"entries": [{"id": 10}, {"id": 20}]}
        rows = DataCache._extract_teams(data)
        assert len(rows) == 2

    def test_normalize_teams_extracts_name(self):
        from app.services.data_cache import DataCache

        raw = [{"id": 5, "cells": [{"text": ["Eagles"]}]}]
        result = DataCache._normalize_teams(raw)
        assert result[0]["text"] == "Eagles"

    def test_normalize_teams_string_text(self):
        from app.services.data_cache import DataCache

        raw = [{"id": 6, "cells": [{"text": "Falcons"}]}]
        result = DataCache._normalize_teams(raw)
        assert result[0]["text"] == "Falcons"

    def test_normalize_teams_missing_cells_uses_unknown(self):
        from app.services.data_cache import DataCache

        raw = [{"id": 7}]
        result = DataCache._normalize_teams(raw)
        assert result[0]["text"] == "Unknown Team"


class TestPlayerSearch:
    async def test_search_players_empty_query_returns_empty(self, cache):
        cache._players_indexed = True
        result = await cache.search_players("")
        assert result == []

    async def test_search_players_short_query_returns_empty(self, cache):
        cache._players_indexed = True
        result = await cache.search_players("a")
        assert result == []

    async def test_search_players_finds_by_name(self, cache):
        cache._players_indexed = True
        cache._players = {
            1: {"id": 1, "name": "Alice Smith", "text": "Alice Smith"},
            2: {"id": 2, "name": "Bob Jones", "text": "Bob Jones"},
        }
        result = await cache.search_players("alice")
        assert len(result) == 1
        assert result[0]["name"] == "Alice Smith"

    async def test_search_players_case_insensitive(self, cache):
        cache._players_indexed = True
        cache._players = {
            1: {"id": 1, "name": "Carlos Ruiz", "text": "Carlos Ruiz"},
        }
        result = await cache.search_players("CARLOS")
        assert len(result) == 1

    async def test_search_players_respects_limit(self, cache):
        cache._players_indexed = True
        cache._players = {
            i: {"id": i, "name": f"Player {i}", "text": f"Player {i}"} for i in range(20)
        }
        result = await cache.search_players("player", limit=5)
        assert len(result) == 5


class TestCacheStats:
    def test_get_stats_returns_expected_keys(self, cache):
        stats = cache.get_stats()
        expected = {
            "teams_loaded",
            "teams_popular_loaded",
            "leagues_loaded",
            "clubs_loaded",
            "players_indexed",
            "all_loaded",
            "last_updated",
            "teams_count",
            "leagues_count",
            "clubs_count",
            "players_count",
            "games_count",
        }
        assert expected.issubset(set(stats.keys()))

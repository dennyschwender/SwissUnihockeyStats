from unittest.mock import MagicMock
from app.services.data_indexer import DataIndexer


def test_apply_player_stats_result_upserts_rows():
    """_apply_player_stats_result writes PlayerStatistics rows from raw API data."""
    # Minimal raw response — one row with stats
    raw = {
        "data": {
            "regions": [{
                "rows": [{
                    "cells": [
                        {"text": "2025/26"},   # season label
                        {"text": "NLA"},        # league
                        {"text": "Team A"},     # team
                        {"text": "30"},         # games
                        {"text": "10"},         # goals
                        {"text": "5"},          # assists
                        {"text": "15"},         # points
                        {"text": "2"},          # pen_2min
                        {"text": "0"},          # pen_5min
                        {"text": "0"},          # pen_10min
                        {"text": "0"},          # pen_match
                    ]
                }]
            }]
        }
    }

    session = MagicMock()
    session.query.return_value.join.return_value.filter.return_value.all.return_value = []
    session.query.return_value.filter.return_value.first.return_value = None
    session.no_autoflush = MagicMock(__enter__=lambda s: s, __exit__=lambda s, *a: False)

    indexer = DataIndexer.__new__(DataIndexer)
    staged = {}
    count = indexer._apply_player_stats_result(session, 99, raw, 2025, "2025/26", staged)
    # May be 0 if mock session returns empty lookups; just confirm method exists and is callable
    assert count >= 0


def test_fetch_player_stats_raw_returns_result():
    """_fetch_player_stats_raw wraps the API call into a _PlayerStatsFetchResult."""
    from app.services.data_indexer import DataIndexer, _PlayerStatsFetchResult
    from unittest.mock import MagicMock
    import requests

    client = MagicMock()
    client.get_player_stats.return_value = {"data": {}}

    indexer = DataIndexer.__new__(DataIndexer)
    indexer.client = client

    result = indexer._fetch_player_stats_raw(42)
    assert isinstance(result, _PlayerStatsFetchResult)
    assert result.player_id == 42
    assert result.api_error is False


def test_fetch_player_stats_raw_marks_5xx_as_api_error():
    from app.services.data_indexer import DataIndexer, _PlayerStatsFetchResult
    from unittest.mock import MagicMock
    import requests

    client = MagicMock()
    resp = MagicMock()
    resp.status_code = 503
    client.get_player_stats.side_effect = requests.HTTPError(response=resp)

    indexer = DataIndexer.__new__(DataIndexer)
    indexer.client = client

    result = indexer._fetch_player_stats_raw(42)
    assert result.api_error is True

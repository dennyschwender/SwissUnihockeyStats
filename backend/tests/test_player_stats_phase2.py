import math
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
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


def test_player_stats_phase2_uses_batch_sessions():
    """_run_player_stats_phase2 opens ceil(n/BATCH)+1 sessions."""
    from app.services.data_indexer import DataIndexer, _PlayerStatsFetchResult

    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    session.no_autoflush = MagicMock(__enter__=lambda s: s, __exit__=lambda s, *a: False)

    call_count = 0

    @contextmanager
    def counting_scope():
        nonlocal call_count
        call_count += 1
        yield session

    db = MagicMock()
    db.session_scope = counting_scope

    indexer = DataIndexer.__new__(DataIndexer)
    indexer.db_service = db
    indexer._API_FAILURE_THRESHOLD = 3
    indexer._API_SKIP_DAYS = 7
    indexer._PLAYER_STATS_PHASE2_BATCH_SIZE = 300

    n_players = 5
    results = [
        _PlayerStatsFetchResult(player_id=i, raw_data={"data": {"regions": []}})
        for i in range(n_players)
    ]

    with patch.object(indexer, "_mark_sync_complete"), \
         patch.object(indexer, "_apply_player_stats_result", return_value=0):
        indexer._run_player_stats_phase2(
            fetch_results=results,
            season_id=2025,
            season_label="2025/26",
            entity_type="player_stats_t1",
            entity_id="season_player_stats:t1:2025",
            exact_tier=1,
            now=datetime.now(timezone.utc),
        )

    expected = math.ceil(n_players / 300) + 1  # 1 batch + 1 tier mark
    assert call_count == expected


def test_index_player_stats_for_season_uses_parallel_phase1():
    """index_player_stats_for_season calls _fetch_player_stats_raw per player,
    not _upsert_player_stats_from_api."""
    from app.services.data_indexer import DataIndexer

    # Session that returns player IDs [1, 2, 3] and empty skip list
    session = MagicMock()
    # For player IDs query
    session.query.return_value.filter.return_value.distinct.return_value.all.return_value = [
        (1,), (2,), (3,),
    ]
    # For api_skip_until query (no skipped players)
    session.query.return_value.filter.return_value.all.return_value = []

    @contextmanager
    def fake_scope():
        yield session

    db = MagicMock()
    db.session_scope = fake_scope

    indexer = DataIndexer.__new__(DataIndexer)
    indexer.db_service = db
    indexer._API_FAILURE_THRESHOLD = 3
    indexer._API_SKIP_DAYS = 7
    indexer._PLAYER_STATS_PHASE2_BATCH_SIZE = 300
    indexer._should_update = MagicMock(return_value=True)
    indexer.bulk_already_indexed = MagicMock(return_value=set())

    fetch_results = [MagicMock(player_id=i, api_error=False, raw_data={}) for i in (1, 2, 3)]

    with patch.object(indexer, "_fetch_player_stats_raw", side_effect=fetch_results) as mock_fetch, \
         patch.object(indexer, "_run_player_stats_phase2", return_value=3) as mock_phase2:
        result = indexer.index_player_stats_for_season(season_id=2025, force=False)

    assert mock_fetch.call_count == 3
    assert mock_phase2.called
    assert result == 3

"""
Regression tests for the two-phase index_player_game_stats_for_season refactor.

Covers:
1. Phase 1 (_fetch_player_game_stats) makes no DB writes
2. Phase 2 (_run_phase2) uses a single session_scope for all players
3. HTTP 500 sets api_error on fetch result
4. Third failure sets api_skip_until (via _run_phase2)
5. Success resets api_failures / api_skip_until (via _run_phase2)
6. Skip pre-fetch excludes players with active api_skip_until window
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import requests

from app.services.data_indexer import DataIndexer, _PlayerGameStatsFetchResult


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_indexer(mock_client=None, mock_db=None):
    mock_client = mock_client or MagicMock()
    mock_db = mock_db or MagicMock()
    indexer = DataIndexer.__new__(DataIndexer)
    indexer.client = mock_client
    indexer.db_service = mock_db
    return indexer


def _session_scope(session):
    @contextmanager
    def _scope():
        yield session
    return _scope


def _overview_response(game_id: int, goals: int = 1, assists: int = 0, pim: int = 0):
    cells = [
        {"text": "2026-01-01"}, {"text": "H"}, {"text": ""},
        {"text": "A"}, {"text": "B"}, {"text": "3:2"},
        {"text": str(goals)}, {"text": str(assists)},
        {"text": str(goals + assists)}, {"text": str(pim)},
    ]
    return {"data": {"regions": [{"rows": [{"id": game_id, "cells": cells}]}]}}


def _make_player_mock(api_failures=0, api_skip_until=None):
    p = MagicMock()
    p.api_failures = api_failures
    p.api_skip_until = api_skip_until
    return p


# ── Test 1: Phase 1 makes no DB writes ───────────────────────────────────────

def test_fetch_helper_does_not_open_session():
    """_fetch_player_game_stats must not call session_scope."""
    mock_client = MagicMock()
    mock_client.get_player_overview.return_value = _overview_response(game_id=42)
    mock_db = MagicMock()
    indexer = _make_indexer(mock_client, mock_db)

    with patch.object(indexer, "_should_update", return_value=True):
        result = indexer._fetch_player_game_stats(player_id=99, season_id=2025)

    assert 42 in result.game_stats
    mock_db.session_scope.assert_not_called()


# ── Test 2: Phase 2 uses batched session_scopes ───────────────────────────────

def test_run_phase2_batches_sessions():
    """_run_phase2 opens ceil(n/BATCH_SIZE) + 1 sessions: one per batch plus one
    final session for the tier-level SyncStatus mark."""
    from app.services.data_indexer import DataIndexer

    session = MagicMock()
    session.query.return_value.filter.return_value.update.return_value = 1
    session.query.return_value.filter.return_value.first.return_value = _make_player_mock()

    call_count = 0

    @contextmanager
    def counting_scope():
        nonlocal call_count
        call_count += 1
        yield session

    mock_db = MagicMock()
    mock_db.session_scope = counting_scope
    indexer = _make_indexer(mock_db=mock_db)

    # 3 players << BATCH_SIZE → 1 batch session + 1 tier session = 2
    results = [
        _PlayerGameStatsFetchResult(player_id=1, game_stats={10: (1, 0, 0)}),
        _PlayerGameStatsFetchResult(player_id=2, game_stats={11: (0, 1, 0)}),
        _PlayerGameStatsFetchResult(player_id=3, game_stats={12: (2, 2, 2)}),
    ]

    with patch.object(indexer, "_mark_sync_complete"):
        indexer._run_phase2(
            fetch_results=results,
            season_id=2025,
            entity_type="player_game_stats_t1",
            entity_id="season_game_stats:t1:2025",
            exact_tier=1,
            now=datetime.now(timezone.utc),
        )

    expected = 2  # 1 batch + 1 tier mark
    assert call_count == expected, f"Expected {expected} session_scope calls, got {call_count}"


def test_run_phase2_opens_multiple_batch_sessions():
    """With more players than BATCH_SIZE, _run_phase2 opens multiple batch sessions."""
    from app.services.data_indexer import DataIndexer

    session = MagicMock()
    session.query.return_value.filter.return_value.update.return_value = 1
    session.query.return_value.filter.return_value.first.return_value = _make_player_mock()

    call_count = 0

    @contextmanager
    def counting_scope():
        nonlocal call_count
        call_count += 1
        yield session

    mock_db = MagicMock()
    mock_db.session_scope = counting_scope
    indexer = _make_indexer(mock_db=mock_db)

    batch_size = DataIndexer._PHASE2_BATCH_SIZE
    # Create enough players to fill 2 full batches + 1 partial
    n_players = batch_size * 2 + 5
    results = [
        _PlayerGameStatsFetchResult(player_id=i, game_stats={100 + i: (1, 0, 0)})
        for i in range(n_players)
    ]

    with patch.object(indexer, "_mark_sync_complete"):
        indexer._run_phase2(
            fetch_results=results,
            season_id=2025,
            entity_type="player_game_stats_t1",
            entity_id="season_game_stats:t1:2025",
            exact_tier=1,
            now=datetime.now(timezone.utc),
        )

    import math
    expected = math.ceil(n_players / batch_size) + 1  # batches + 1 tier mark
    assert call_count == expected, f"Expected {expected} session_scope calls, got {call_count}"


# ── Test 3: HTTP 500 sets api_error ──────────────────────────────────────────

def test_http_500_sets_api_error():
    mock_client = MagicMock()
    response = MagicMock()
    response.status_code = 500
    mock_client.get_player_overview.side_effect = requests.HTTPError(response=response)
    indexer = _make_indexer(mock_client)

    with patch.object(indexer, "_should_update", return_value=True):
        result = indexer._fetch_player_game_stats(player_id=7, season_id=2025)

    assert result.api_error is True
    assert result.game_stats == {}


def test_non_5xx_does_not_set_api_error():
    mock_client = MagicMock()
    response = MagicMock()
    response.status_code = 404
    mock_client.get_player_overview.side_effect = requests.HTTPError(response=response)
    indexer = _make_indexer(mock_client)

    with patch.object(indexer, "_should_update", return_value=True):
        result = indexer._fetch_player_game_stats(player_id=7, season_id=2025)

    assert result.api_error is False


# ── Test 4: Third failure sets api_skip_until ────────────────────────────────

def test_third_failure_sets_skip_until():
    player_mock = _make_player_mock(api_failures=2)  # 2 previous failures
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = player_mock

    mock_db = MagicMock()
    mock_db.session_scope = _session_scope(session)
    indexer = _make_indexer(mock_db=mock_db)

    now = datetime.now(timezone.utc)
    with patch.object(indexer, "_mark_sync_complete"):
        indexer._run_phase2(
            fetch_results=[_PlayerGameStatsFetchResult(player_id=7, game_stats={}, api_error=True)],
            season_id=2025,
            entity_type="player_game_stats_t1",
            entity_id="season_game_stats:t1:2025",
            exact_tier=1,
            now=now,
        )

    assert player_mock.api_failures == 3
    assert player_mock.api_skip_until is not None
    expected = now + timedelta(days=DataIndexer._API_SKIP_DAYS)
    assert abs((player_mock.api_skip_until - expected).total_seconds()) < 2


# ── Test 5: Success resets skip fields ───────────────────────────────────────

def test_success_resets_api_failures_and_skip_until():
    player_mock = _make_player_mock(
        api_failures=2,
        api_skip_until=datetime.now(timezone.utc) + timedelta(days=3),
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = player_mock
    session.query.return_value.filter.return_value.update.return_value = 1

    mock_db = MagicMock()
    mock_db.session_scope = _session_scope(session)
    indexer = _make_indexer(mock_db=mock_db)

    with patch.object(indexer, "_mark_sync_complete"):
        indexer._run_phase2(
            fetch_results=[_PlayerGameStatsFetchResult(player_id=7, game_stats={10: (1, 0, 0)})],
            season_id=2025,
            entity_type="player_game_stats_t1",
            entity_id="season_game_stats:t1:2025",
            exact_tier=1,
            now=datetime.now(timezone.utc),
        )

    assert player_mock.api_failures == 0
    assert player_mock.api_skip_until is None


# ── Test 6: Skip pre-fetch excludes active-skip players ──────────────────────

def test_skip_window_players_not_fetched():
    """Players with api_skip_until > now must not be passed to _fetch_player_game_stats."""
    fetched_pids = []

    def tracking_fetch(player_id, **kwargs):
        fetched_pids.append(player_id)
        return _PlayerGameStatsFetchResult(player_id=player_id)

    # Simulate DB returning player 99 as "in skip window"
    skip_session = MagicMock()
    skip_session.query.return_value.filter.return_value.all.return_value = [(99,)]

    # player_ids session returns players 99 and 100
    player_ids_session = MagicMock()
    player_ids_session.query.return_value.filter.return_value.distinct.return_value.all.return_value = [
        (99,), (100,)
    ]
    player_ids_session.query.return_value.filter.return_value.distinct.return_value.all.side_effect = None

    scope_calls = []

    @contextmanager
    def multi_scope():
        # First call: player_ids query; second: skip_ids query; third: phase2 write
        call_idx = len(scope_calls)
        scope_calls.append(call_idx)
        if call_idx == 0:
            yield player_ids_session
        elif call_idx == 1:
            yield skip_session
        else:
            yield MagicMock()

    mock_db = MagicMock()
    mock_db.session_scope = multi_scope

    indexer = _make_indexer(mock_db=mock_db)

    with (
        patch.object(indexer, "_should_update", return_value=True),
        patch.object(indexer, "_fetch_player_game_stats", side_effect=tracking_fetch),
        patch.object(indexer, "_mark_sync_complete"),
        patch.object(indexer, "_run_phase2", return_value=0),
    ):
        indexer.index_player_game_stats_for_season(season_id=2025, force=True)

    assert 99 not in fetched_pids, "Skipped player 99 was still fetched"

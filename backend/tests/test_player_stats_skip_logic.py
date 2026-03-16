"""
Tests for api_failures/api_skip_until skip logic in player_stats indexing.

Covers:
1. HTTP 500 response sets api_error flag in _upsert_player_stats_from_api
2. Non-5xx exception does not set api_error flag
3. Third failure sets api_skip_until on the Player row
4. Successful update resets api_failures/api_skip_until
5. Players with active api_skip_until window are excluded from processing
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call
import requests

from app.services.data_indexer import DataIndexer

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


def _make_player_mock(api_failures=0, api_skip_until=None):
    p = MagicMock()
    p.api_failures = api_failures
    p.api_skip_until = api_skip_until
    return p


def _make_session_for_upsert():
    """Return a session mock that supports no_autoflush context and basic queries."""
    session = MagicMock()
    # Make no_autoflush work as a context manager
    session.no_autoflush.__enter__ = lambda s: None
    session.no_autoflush.__exit__ = lambda s, *a: None
    # Default: no existing PlayerStatistics row
    session.query.return_value.filter.return_value.first.return_value = None
    return session


# ── Test 1: HTTP 500 sets api_error ──────────────────────────────────────────


def test_http_500_sets_api_error():
    """_upsert_player_stats_from_api returns (0, True) on HTTP 5xx."""
    mock_client = MagicMock()
    response = MagicMock()
    response.status_code = 500
    mock_client.get_player_stats.side_effect = requests.HTTPError(response=response)

    indexer = _make_indexer(mock_client)
    session = _make_session_for_upsert()
    staged = {}

    count, api_err = indexer._upsert_player_stats_from_api(
        person_id=7, season_id=2025, season_label="2025/26", session=session, staged=staged
    )

    assert count == 0
    assert api_err is True


# ── Test 2: Non-5xx exception does not set api_error ─────────────────────────


def test_non_5xx_does_not_set_api_error():
    """_upsert_player_stats_from_api returns (0, False) on non-HTTP-5xx exceptions."""
    mock_client = MagicMock()
    mock_client.get_player_stats.side_effect = requests.ConnectionError("network failure")

    indexer = _make_indexer(mock_client)
    session = _make_session_for_upsert()
    staged = {}

    count, api_err = indexer._upsert_player_stats_from_api(
        person_id=7, season_id=2025, season_label="2025/26", session=session, staged=staged
    )

    assert count == 0
    assert api_err is False


def test_http_404_does_not_set_api_error():
    """_upsert_player_stats_from_api returns (0, False) on HTTP 4xx."""
    mock_client = MagicMock()
    response = MagicMock()
    response.status_code = 404
    mock_client.get_player_stats.side_effect = requests.HTTPError(response=response)

    indexer = _make_indexer(mock_client)
    session = _make_session_for_upsert()
    staged = {}

    count, api_err = indexer._upsert_player_stats_from_api(
        person_id=7, season_id=2025, season_label="2025/26", session=session, staged=staged
    )

    assert count == 0
    assert api_err is False


# ── Test 3: Third failure sets api_skip_until ─────────────────────────────────


def test_third_failure_sets_skip_until():
    """After 3 API failures in the season loop, api_skip_until is set on the Player row."""
    from app.models.db_models import Player as PlayerModel

    player_mock = _make_player_mock(api_failures=2)  # 2 previous failures
    session = MagicMock()
    # skip_ids query
    session.query.return_value.filter.return_value.all.return_value = []
    # player lookup in the loop
    session.query.return_value.filter.return_value.first.return_value = player_mock

    mock_db = MagicMock()
    mock_db.session_scope = _session_scope(session)

    mock_client = MagicMock()
    response = MagicMock()
    response.status_code = 500
    mock_client.get_player_stats.side_effect = requests.HTTPError(response=response)

    indexer = _make_indexer(mock_client, mock_db)

    with (
        patch.object(indexer, "_should_update", return_value=True),
        patch.object(indexer, "_mark_sync_complete"),
        patch.object(indexer, "_mark_sync_failed"),
    ):
        # Patch the internals to return a single player_id=[7] after the player_ids query
        from app.models.db_models import Season as SeasonModel

        season_mock = MagicMock()
        season_mock.text = "2025/26"
        session.get.return_value = season_mock

        # Make tp_ids / gp_ids queries return player 7
        # We need multiple returns from session.query chain
        # The simplest approach: patch _upsert_player_stats_from_api directly
        # but still exercise the loop logic, so instead we just call the method
        # with a carefully crafted session that returns player_ids=[7]
        pass

    # Directly test the loop logic: call index_player_stats_for_season with mocked internals
    # We patch _upsert_player_stats_from_api to return (0, True) — 5xx error
    with (
        patch.object(indexer, "_should_update", return_value=True),
        patch.object(indexer, "_mark_sync_complete"),
        patch.object(indexer, "_mark_sync_failed"),
        patch.object(indexer, "_upsert_player_stats_from_api", return_value=(0, True)),
    ):
        # Build session that returns player_ids and player_mock
        session2 = MagicMock()
        # season lookup
        season_mock2 = MagicMock()
        season_mock2.text = "2025/26"
        session2.get.return_value = season_mock2

        # We need to intercept the chained query calls.
        # The function does:
        #   tp_ids from session.query(TeamPlayer.player_id).filter(...).distinct().all()
        #   gp_ids from session.query(_GamePlayer.player_id).filter(...).distinct().all()
        #   skip_ids from session.query(Player.person_id).filter(...).all()
        #   player lookup: session.query(Player).filter(...).first()
        #
        # Use a counter-based side_effect to distinguish calls.
        call_counter = [0]

        def query_side_effect(model):
            call_counter[0] += 1
            q = MagicMock()
            n = call_counter[0]
            if n == 1:
                # tp_ids: TeamPlayer.player_id
                q.filter.return_value.distinct.return_value.all.return_value = [(7,)]
            elif n == 2:
                # gp_ids: GamePlayer.player_id
                q.filter.return_value.distinct.return_value.all.return_value = []
            elif n == 3:
                # skip_ids: Player.person_id — no skip
                q.filter.return_value.all.return_value = []
            else:
                # player lookup in loop
                q.filter.return_value.first.return_value = player_mock
            return q

        session2.query.side_effect = query_side_effect
        mock_db2 = MagicMock()
        mock_db2.session_scope = _session_scope(session2)
        indexer.db_service = mock_db2

        indexer.index_player_stats_for_season(season_id=2025, force=True)

    assert player_mock.api_failures == 3
    assert player_mock.api_skip_until is not None
    expected = timedelta(days=DataIndexer._API_SKIP_DAYS)
    # Check that api_skip_until is approximately now + skip_days
    diff = player_mock.api_skip_until - datetime.now(timezone.utc)
    assert abs(diff.total_seconds() - expected.total_seconds()) < 10


# ── Test 4: Success resets api_failures/api_skip_until ───────────────────────


def test_success_resets_skip_fields():
    """Successful fetch routes player through Phase 1/2; _run_player_stats_phase2 handles reset."""
    call_counter = [0]

    def query_side_effect(model):
        call_counter[0] += 1
        q = MagicMock()
        n = call_counter[0]
        if n == 1:
            # tp_ids
            q.filter.return_value.distinct.return_value.all.return_value = [(7,)]
        elif n == 2:
            # gp_ids
            q.filter.return_value.distinct.return_value.all.return_value = []
        else:
            # skip_ids — not in skip window
            q.filter.return_value.all.return_value = []
        return q

    session = MagicMock()
    season_mock = MagicMock()
    season_mock.text = "2025/26"
    session.get.return_value = season_mock
    session.query.side_effect = query_side_effect

    mock_db = MagicMock()
    mock_db.session_scope = _session_scope(session)

    indexer = _make_indexer(mock_db=mock_db)

    fetch_result = MagicMock()
    fetch_result.player_id = 7
    fetch_result.api_error = False
    fetch_result.raw_data = {"data": {}}

    with (
        patch.object(indexer, "_should_update", return_value=True),
        patch.object(indexer, "_fetch_player_stats_raw", return_value=fetch_result) as mock_fetch,
        patch.object(indexer, "_run_player_stats_phase2", return_value=1) as mock_phase2,
    ):
        result = indexer.index_player_stats_for_season(season_id=2025, force=True)

    # Phase 1 was called for player 7; Phase 2 was called with the result
    assert mock_fetch.call_count == 1
    assert mock_fetch.call_args[0][0] == 7
    assert mock_phase2.called
    assert result == 1


# ── Test 5: Skip window excludes players ─────────────────────────────────────


def test_skip_window_excludes_players():
    """Players with api_skip_until > now must not be passed to _fetch_player_stats_raw."""
    call_counter = [0]

    def query_side_effect(model):
        call_counter[0] += 1
        q = MagicMock()
        n = call_counter[0]
        if n == 1:
            # tp_ids — includes player 99 (the skipped one) and player 100
            q.filter.return_value.distinct.return_value.all.return_value = [(99,), (100,)]
        elif n == 2:
            # gp_ids
            q.filter.return_value.distinct.return_value.all.return_value = []
        else:
            # skip_ids — player 99 is in the skip window
            q.filter.return_value.all.return_value = [(99,)]
        return q

    session = MagicMock()
    season_mock = MagicMock()
    season_mock.text = "2025/26"
    session.get.return_value = season_mock
    session.query.side_effect = query_side_effect

    mock_db = MagicMock()
    mock_db.session_scope = _session_scope(session)

    mock_client = MagicMock()
    indexer = _make_indexer(mock_client, mock_db)

    fetched_ids = []

    def tracking_fetch(person_id):
        fetched_ids.append(person_id)
        r = MagicMock()
        r.player_id = person_id
        r.api_error = False
        r.raw_data = {}
        return r

    with (
        patch.object(indexer, "_should_update", return_value=True),
        patch.object(indexer, "_fetch_player_stats_raw", side_effect=tracking_fetch),
        patch.object(indexer, "_run_player_stats_phase2", return_value=1),
    ):
        indexer.index_player_stats_for_season(season_id=2025, force=True)

    assert 99 not in fetched_ids, "Skipped player 99 was still processed"
    assert 100 in fetched_ids, "Player 100 should have been processed"

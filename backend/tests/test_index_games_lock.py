"""
Regression test: index_games_for_league must NOT hold the SQLite write lock
during network I/O (API calls).

Root cause of production OperationalError: database is locked —
the old implementation opened session_scope() first, then called
client.get_games() inside the loop. The first session.flush() escalated
SQLite from DEFERRED → RESERVED, and the lock was held for every subsequent
API call (20–60 s), starving concurrent writers.

Fix: all API calls must complete in Phase 1 (no DB session open), then
a single short session_scope() in Phase 2 writes all collected data.
"""
from contextlib import contextmanager
from unittest.mock import Mock, MagicMock

from app.services.data_indexer import DataIndexer


# Minimal API response that terminates the pagination loop immediately:
# - no "prev" in slider → backward loop stops after one call
# - no "next" in slider → forward_start_round stays None → forward loop never runs
_EMPTY_ROUND = {
    "data": {
        "slider": {},   # no prev, no next
        "regions": [],  # no rows → no DB writes needed
    }
}


def _mock_session_scope():
    """Return a context-manager that yields a Mock session (no real DB I/O)."""
    mock_session = MagicMock()
    # _get_or_create_phase_group looks up LeagueGroup; return existing stub
    existing_group = Mock()
    existing_group.id = 99
    existing_group.phase = "Regelsaison"
    mock_session.query.return_value.filter.return_value.first.return_value = existing_group
    # session.get() returns a mock object so Team/Game lookups succeed
    mock_session.get.return_value = Mock()

    @contextmanager
    def _scope():
        yield mock_session

    return _scope


class TestIndexGamesForLeagueLockOrder:
    """API calls must all complete before the DB session is opened."""

    def test_api_calls_happen_before_db_session_is_opened(self):
        """get_games() must be called before session_scope() is entered.

        With the old implementation this test FAILS because the session is
        opened at the top of the function and API calls happen inside it.
        After the fix (Phase 1 = all API, Phase 2 = all DB) it PASSES.
        """
        call_order: list[str] = []

        indexer = DataIndexer()

        # Replace session_scope with a tracking wrapper around the mock session
        real_mock_factory = _mock_session_scope()

        @contextmanager
        def tracking_scope():
            call_order.append("session_enter")
            with real_mock_factory() as s:
                yield s

        indexer.db_service.session_scope = tracking_scope

        # Replace the API client with a mock that records calls
        mock_client = Mock()

        def tracking_get_games(**kwargs):
            call_order.append("api_call")
            return _EMPTY_ROUND

        mock_client.get_games.side_effect = tracking_get_games
        indexer.client = mock_client

        # force=True bypasses the should_update age-check
        indexer.index_games_for_league(
            league_db_id=1,
            season_id=2025,
            league_id=100,
            game_class=1,
            force=True,
        )

        api_indices = [i for i, x in enumerate(call_order) if x == "api_call"]
        session_indices = [i for i, x in enumerate(call_order) if x == "session_enter"]

        assert api_indices, "get_games() was never called — check the mock setup"
        assert session_indices, "session_scope was never entered — check the mock setup"

        last_api = max(api_indices)
        first_session = min(session_indices)

        assert last_api < first_session, (
            f"DB session was opened before all API calls completed.\n"
            f"Call order: {call_order}\n"
            f"Last api_call at index {last_api}, "
            f"first session_enter at index {first_session}.\n"
            f"Fix: move all client.get_games() calls to Phase 1 "
            f"(before session_scope), then write in Phase 2."
        )

    def test_api_called_once_for_single_round_league(self):
        """With a single round (no pagination), get_games() is called exactly once."""
        indexer = DataIndexer()
        indexer.db_service.session_scope = _mock_session_scope()

        mock_client = Mock()
        mock_client.get_games.return_value = _EMPTY_ROUND
        indexer.client = mock_client

        indexer.index_games_for_league(
            league_db_id=1, season_id=2025, league_id=100,
            game_class=1, force=True,
        )

        assert mock_client.get_games.call_count == 1

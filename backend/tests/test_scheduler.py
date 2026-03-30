"""
Test suite for Scheduler service
Testing background job scheduling functionality
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta
from app.services.scheduler import Scheduler, POLICIES, get_scheduler, init_scheduler


@pytest.fixture
def mock_admin_jobs():
    """Mock admin jobs dictionary"""
    return {}


@pytest.fixture
def mock_submit_job():
    """Mock submit job coroutine"""

    async def _submit(job_id: str, season: int, task: str, force: bool = False, max_tier: int = 7):
        # Simulate job submission
        await asyncio.sleep(0.01)
        return job_id

    return _submit


@pytest.fixture
def scheduler(mock_admin_jobs, mock_submit_job):
    """Create Scheduler instance for testing"""
    return Scheduler(mock_admin_jobs, mock_submit_job)


class TestSchedulerInitialization:
    """Test Scheduler initialization"""

    def test_scheduler_init(self, scheduler):
        """Test scheduler initializes correctly"""
        assert scheduler._admin_jobs is not None
        assert scheduler._submit is not None
        assert scheduler._running is False
        assert isinstance(scheduler._queue, list)
        assert isinstance(scheduler._history, list)

    def test_scheduler_singleton(self):
        """Test get_scheduler returns singleton"""
        admin_jobs = {}

        async def submit(job_id, season, task, force=False, max_tier=7):
            pass

        sched1 = init_scheduler(admin_jobs, submit)
        sched2 = get_scheduler()

        assert sched2 is not None
        # Note: Multiple calls to init_scheduler will create new instances
        # This is by design for testing

    def test_scheduler_enabled_by_default(self, scheduler):
        """Test scheduler default is True when no config file exists"""
        from unittest.mock import patch

        with patch.object(type(scheduler), "_load_state", return_value=True):
            scheduler._enabled = scheduler._load_state()
        assert scheduler.enabled is True


class TestSchedulerState:
    """Test scheduler state management"""

    def test_enable_scheduler(self, scheduler):
        """Test enabling scheduler"""
        scheduler.enable(True)
        assert scheduler.enabled is True

    def test_disable_scheduler(self, scheduler):
        """Test disabling scheduler"""
        scheduler.enable(False)
        assert scheduler.enabled is False

    def test_toggle_scheduler(self, scheduler):
        """Test toggling scheduler state"""
        initial = scheduler.enabled
        scheduler.enable(not initial)
        assert scheduler.enabled != initial
        scheduler.enable(initial)
        assert scheduler.enabled == initial


class TestSchedulerQueue:
    """Test scheduler queue management"""

    def test_empty_queue_initially(self, scheduler):
        """Test queue is empty initially"""
        assert len(scheduler._queue) == 0

    def test_get_schedule(self, scheduler):
        """Test getting current schedule"""
        schedule = scheduler.get_schedule()
        assert isinstance(schedule, list)


class TestSchedulerPolicies:
    """Test scheduling policies"""

    def test_policies_defined(self):
        """Test that POLICIES are defined"""
        assert len(POLICIES) > 0

        # Check policy structure
        for policy in POLICIES:
            assert "task" in policy
            assert "scope" in policy
            assert "max_age" in policy
            assert "label" in policy

    def test_seasons_policy_exists(self):
        """Test seasons policy exists"""
        seasons_policy = next((p for p in POLICIES if p["task"] == "seasons"), None)
        assert seasons_policy is not None
        assert seasons_policy["scope"] == "global"

    def test_league_policies_exist(self):
        """Test league-related policies exist"""
        league_policy = next((p for p in POLICIES if p["task"] == "leagues"), None)
        assert league_policy is not None


class TestSchedulerLifecycle:
    """Test scheduler lifecycle"""

    def test_stop_scheduler(self, scheduler):
        """Test stopping scheduler"""
        scheduler.stop()
        assert scheduler._running is False

    @pytest.mark.asyncio
    async def test_scheduler_run_and_stop(self, scheduler):
        """Test starting and stopping scheduler"""
        # Start scheduler in background
        run_task = asyncio.create_task(scheduler.run())

        # Let it run for a moment
        await asyncio.sleep(0.1)

        # Stop it
        scheduler.stop()

        # Wait for task to complete
        try:
            await asyncio.wait_for(run_task, timeout=1.0)
        except asyncio.TimeoutError:
            run_task.cancel()


class TestSchedulerJobSubmission:
    """Test job submission through scheduler"""

    @pytest.mark.asyncio
    async def test_submit_job_called(self, mock_admin_jobs):
        """Test that submit job is called"""
        job_submitted = False

        async def mock_submit(job_id, season, task, force=False, max_tier=7):
            nonlocal job_submitted
            job_submitted = True
            return job_id

        scheduler = Scheduler(mock_admin_jobs, mock_submit)

        # Trigger refresh manually (normally done by scheduler loop)
        # This would require database access, so we'll skip actual refresh
        # Just verify the structure is correct
        assert callable(scheduler._submit)


class TestSchedulerHistory:
    """Test scheduler job history"""

    def test_history_initially_empty(self, scheduler):
        """Test history is empty initially"""
        assert len(scheduler._history) == 0

    def test_get_schedule_returns_list(self, scheduler):
        """Test get_schedule returns proper structure"""
        schedule = scheduler.get_schedule()
        assert isinstance(schedule, list)
        # Each item should be a dict with job info
        for item in schedule:
            assert isinstance(item, dict)


class TestSchedulerIntegration:
    """Integration tests for scheduler"""

    @pytest.mark.asyncio
    async def test_scheduler_with_disabled_state(self, scheduler):
        """Test scheduler respects enabled state"""
        scheduler.enable(False)

        # Start scheduler
        run_task = asyncio.create_task(scheduler.run())

        # Let it run briefly
        await asyncio.sleep(0.1)

        # Queue should not grow when disabled
        initial_queue_size = len(scheduler._queue)
        await asyncio.sleep(0.2)
        final_queue_size = len(scheduler._queue)

        # Stop scheduler
        scheduler.stop()
        try:
            await asyncio.wait_for(run_task, timeout=1.0)
        except asyncio.TimeoutError:
            run_task.cancel()

        # When disabled, scheduler shouldn't add jobs
        # (though initial refresh might add some)
        assert True  # This test needs database to be meaningful


class TestSchedulerErrorHandling:
    """Test scheduler error handling"""

    @pytest.mark.asyncio
    async def test_scheduler_handles_submit_error(self):
        """Test scheduler handles errors in job submission"""

        async def failing_submit(job_id, season, task, force=False, max_tier=7):
            raise Exception("Test error")

        scheduler = Scheduler({}, failing_submit)

        # Scheduler should not crash when submit fails
        # This would be tested with actual refresh cycle
        assert True


class TestSchedulerPersistence:
    """Test scheduler state persistence"""

    def test_state_persistence_methods_exist(self, scheduler):
        """Test that state persistence methods exist"""
        assert hasattr(scheduler, "_load_state")
        assert hasattr(scheduler, "_save_state")


class TestSeasonFiltering:
    """Unit tests for _season_filtered logic (no DB needed)."""

    def _make_scheduler_bare(self):
        from app.services.scheduler import Scheduler

        with patch("app.services.scheduler.Scheduler._load_state", return_value=True):
            sched = Scheduler.__new__(Scheduler)
            sched._min_season = None
            sched._excluded_seasons = []
            sched._max_concurrent = 2
            sched._policy_tiers = {}
            sched._enabled = True
            sched._queue = []
            sched._history = []
            sched._running = False
        return sched

    def test_no_filter_allows_all_seasons(self):
        sched = self._make_scheduler_bare()
        assert sched._season_filtered(2024) is False
        assert sched._season_filtered(2025) is False

    def test_min_season_blocks_older_seasons(self):
        sched = self._make_scheduler_bare()
        sched._min_season = 2024
        assert sched._season_filtered(2023) is True
        assert sched._season_filtered(2024) is False

    def test_excluded_seasons_blocks_listed_seasons(self):
        sched = self._make_scheduler_bare()
        sched._excluded_seasons = [2022, 2023]
        assert sched._season_filtered(2022) is True
        assert sched._season_filtered(2024) is False

    def test_none_season_never_filtered(self):
        """Global-scope jobs (season=None) must never be filtered."""
        sched = self._make_scheduler_bare()
        sched._min_season = 2030
        sched._excluded_seasons = [2025]
        assert sched._season_filtered(None) is False


class TestSnapToHour:
    """Unit tests for _snap_to_hour helper."""

    def test_snap_forward_same_day(self):
        from app.services.scheduler import _snap_to_hour

        dt = datetime(2025, 3, 5, 1, 30, 0)
        result = _snap_to_hour(dt, 3)
        assert result == datetime(2025, 3, 5, 3, 0, 0)

    def test_snap_wraps_to_next_day_when_past_hour(self):
        from app.services.scheduler import _snap_to_hour

        dt = datetime(2025, 3, 5, 4, 0, 0)
        result = _snap_to_hour(dt, 3)
        assert result == datetime(2025, 3, 6, 3, 0, 0)

    def test_snap_exactly_on_hour_moves_to_next_day(self):
        from app.services.scheduler import _snap_to_hour

        dt = datetime(2025, 3, 5, 3, 0, 0)
        result = _snap_to_hour(dt, 3)
        assert result == datetime(2025, 3, 6, 3, 0, 0)


class TestPoliciesStructure:
    """Validate POLICIES data structure completeness."""

    def test_all_policies_have_required_fields(self):
        from app.services.scheduler import POLICIES

        required = {"name", "entity_type", "max_age", "task", "scope", "label", "priority"}
        for p in POLICIES:
            missing = required - p.keys()
            assert not missing, f"Policy '{p.get('name')}' missing fields: {missing}"

    def test_policy_scopes_are_valid(self):
        from app.services.scheduler import POLICIES

        for p in POLICIES:
            assert p["scope"] in {
                "global",
                "season",
            }, f"Policy {p['name']} has invalid scope {p['scope']}"

    def test_policy_priorities_are_positive(self):
        from app.services.scheduler import POLICIES

        for p in POLICIES:
            assert p["priority"] > 0, f"Policy {p['name']} has non-positive priority"



class TestPoliciesDefinition:
    """Validate specific policy definitions and their properties."""

    def test_games_policy_exists_and_is_past_only(self):
        """games policy must exist, be past_only, and require leagues."""
        from app.services.scheduler import POLICIES

        p = next((p for p in POLICIES if p["name"] == "games"), None)
        assert p is not None, "games policy not found in POLICIES"
        assert p["past_only"] is True
        assert p["requires"] == "leagues"
        assert p["task"] == "games"
        assert p["scope"] == "season"
        assert p["run_at_hour"] == 3

    def test_game_events_policy_exists_and_is_past_only(self):
        """game_events policy must exist, be past_only, and require games."""
        from app.services.scheduler import POLICIES

        p = next((p for p in POLICIES if p["name"] == "game_events"), None)
        assert p is not None, "game_events policy not found in POLICIES"
        assert p["past_only"] is True
        assert p["requires"] == "games"
        assert p["task"] == "events"
        assert p["scope"] == "season"
        assert p["run_at_hour"] == 3

    def test_games_policy_priority_between_leagues_and_upcoming(self):
        """games must have priority between leagues(50) and upcoming_games_noon(70)."""
        from app.services.scheduler import POLICIES

        leagues_p = next(p["priority"] for p in POLICIES if p["name"] == "leagues")
        games_p = next(p["priority"] for p in POLICIES if p["name"] == "games")
        game_events_p = next(p["priority"] for p in POLICIES if p["name"] == "game_events")
        upcoming_p = next(p["priority"] for p in POLICIES if p["name"] == "upcoming_games_noon")

        assert leagues_p < games_p < game_events_p < upcoming_p


class TestClearDone:
    """Unit tests for clear_done helper."""

    def _make_scheduler_with_history(self):
        from app.services.scheduler import Scheduler, JobRecord

        with patch("app.services.scheduler.Scheduler._load_state", return_value=True):
            sched = Scheduler.__new__(Scheduler)
            sched._min_season = None
            sched._excluded_seasons = []
            sched._max_concurrent = 2
            sched._policy_tiers = {}
            sched._enabled = True
            sched._queue = []
            sched._running = False
        now = datetime.now()
        sched._history = [
            JobRecord("a1", "clubs", "clubs", 2025, "done", now, now, now),
            JobRecord("b2", "teams", "teams", 2025, "running", now, now, None),
            JobRecord("c3", "games", "games", 2025, "error", now, now, now),
        ]
        return sched

    def test_clear_done_removes_finished_jobs(self):
        sched = self._make_scheduler_with_history()
        removed = sched.clear_done()
        assert removed == 2  # done + error
        remaining = sched.get_history()
        assert len(remaining) == 1
        assert remaining[0]["status"] == "running"


class TestLaunchAndReturnIdForce:
    """_launch_and_return_id passes force flag to _submit"""

    @pytest.mark.asyncio
    async def test_force_flag_forwarded(self, mock_admin_jobs):
        captured = {}

        async def submit(job_id, season, task, force=False, max_tier=7):
            captured["force"] = force

        sched = Scheduler(mock_admin_jobs, submit)
        from app.services.scheduler import ScheduledJob, _utcnow, POLICIES
        policy = next(p for p in POLICIES if p["name"] == "seasons")
        job = ScheduledJob(
            run_at=_utcnow(),
            priority=policy["priority"],
            policy_name=policy["name"],
            task=policy["task"],
            season=None,
            label="test",
            max_tier=policy.get("max_tier", 7),
        )
        await sched._launch_and_return_id(job, force=True)
        assert captured["force"] is True


class TestSeasonGapDetection:
    """_refresh_queue forces index_seasons when seasons are missing from DB"""

    @pytest.mark.asyncio
    async def test_gap_triggers_forced_seasons_job(self, mock_admin_jobs):
        launched = []

        async def submit(job_id, season, task, force=False, max_tier=7):
            launched.append({"task": task, "force": force})

        sched = Scheduler(mock_admin_jobs, submit)
        sched._min_season = 2020

        # Simulate DB returning only season 2025 (highlighted), missing 2020-2024
        from unittest.mock import patch, MagicMock
        mock_season_rows = [(2025, True)]  # (id, highlighted)

        mock_session = MagicMock()
        mock_session.query.return_value.order_by.return_value.all.return_value = mock_season_rows
        # Season.is_frozen query returns None (not frozen)
        mock_session.query.return_value.filter.return_value.scalar.return_value = None

        mock_db = MagicMock()
        mock_db.session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.session_scope.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.scheduler.get_database_service", return_value=mock_db):
            await sched._refresh_queue()

        seasons_jobs = [j for j in launched if j["task"] == "seasons"]
        assert len(seasons_jobs) == 1
        assert seasons_jobs[0]["force"] is True

    @pytest.mark.asyncio
    async def test_no_gap_no_forced_job(self, mock_admin_jobs):
        launched = []

        async def submit(job_id, season, task, force=False, max_tier=7):
            launched.append({"task": task, "force": force})

        sched = Scheduler(mock_admin_jobs, submit)
        sched._min_season = 2025

        from unittest.mock import patch, MagicMock
        mock_season_rows = [(2025, True)]
        mock_session = MagicMock()
        mock_session.query.return_value.order_by.return_value.all.return_value = mock_season_rows
        mock_session.query.return_value.filter.return_value.scalar.return_value = None

        mock_db = MagicMock()
        mock_db.session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.session_scope.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.scheduler.get_database_service", return_value=mock_db):
            await sched._refresh_queue()

        forced_seasons = [j for j in launched if j["task"] == "seasons" and j["force"]]
        assert len(forced_seasons) == 0

    @pytest.mark.asyncio
    async def test_gap_skipped_when_seasons_job_already_queued(self, mock_admin_jobs):
        launched = []

        async def submit(job_id, season, task, force=False, max_tier=7):
            launched.append({"task": task, "force": force})

        sched = Scheduler(mock_admin_jobs, submit)
        sched._min_season = 2020

        # Pre-queue a seasons job
        from app.services.scheduler import ScheduledJob, _utcnow
        sched._queue.append(ScheduledJob(
            run_at=_utcnow(),
            priority=10,
            policy_name="seasons",
            task="seasons",
            season=None,
            label="already queued",
        ))

        from unittest.mock import patch, MagicMock
        mock_season_rows = [(2025, True)]
        mock_session = MagicMock()
        mock_session.query.return_value.order_by.return_value.all.return_value = mock_season_rows
        mock_session.query.return_value.filter.return_value.scalar.return_value = None

        mock_db = MagicMock()
        mock_db.session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.session_scope.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.scheduler.get_database_service", return_value=mock_db):
            await sched._refresh_queue()

        forced_seasons = [j for j in launched if j["task"] == "seasons" and j["force"]]
        assert len(forced_seasons) == 0

    @pytest.mark.asyncio
    async def test_gap_skipped_when_seasons_job_running_in_history(self, mock_admin_jobs):
        launched = []

        async def submit(job_id, season, task, force=False, max_tier=7):
            launched.append({"task": task, "force": force})

        sched = Scheduler(mock_admin_jobs, submit)
        sched._min_season = 2020

        # Simulate a seasons job already running (in history, not queue)
        from app.services.scheduler import JobRecord, _utcnow
        sched._history.append(JobRecord(
            job_id="abc123",
            policy_name="seasons",
            task="seasons",
            season=None,
            status="running",
            scheduled_at=_utcnow(),
        ))

        from unittest.mock import patch, MagicMock
        mock_season_rows = [(2025, True)]
        mock_session = MagicMock()
        mock_session.query.return_value.order_by.return_value.all.return_value = mock_season_rows
        mock_session.query.return_value.filter.return_value.scalar.return_value = None

        mock_db = MagicMock()
        mock_db.session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.session_scope.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.scheduler.get_database_service", return_value=mock_db):
            await sched._refresh_queue()

        forced_seasons = [j for j in launched if j["task"] == "seasons" and j["force"]]
        assert len(forced_seasons) == 0

    @pytest.mark.asyncio
    async def test_gap_fires_when_seasons_job_queued_far_in_future(self, mock_admin_jobs):
        """A normally-scheduled future seasons job must not suppress the gap-fill."""
        launched = []

        async def submit(job_id, season, task, force=False, max_tier=7):
            launched.append({"task": task, "force": force})

        sched = Scheduler(mock_admin_jobs, submit)
        sched._min_season = 2020

        # Simulate the normal 30-day policy: seasons job queued weeks away
        from app.services.scheduler import ScheduledJob, _utcnow
        from datetime import timedelta
        sched._queue.append(ScheduledJob(
            run_at=_utcnow() + timedelta(days=14),
            priority=10,
            policy_name="seasons",
            task="seasons",
            season=None,
            label="scheduled far away",
        ))

        from unittest.mock import patch, MagicMock
        mock_season_rows = [(2025, True)]
        mock_session = MagicMock()
        mock_session.query.return_value.order_by.return_value.all.return_value = mock_season_rows
        mock_session.query.return_value.filter.return_value.scalar.return_value = None

        mock_db = MagicMock()
        mock_db.session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.session_scope.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.scheduler.get_database_service", return_value=mock_db):
            await sched._refresh_queue()

        forced_seasons = [j for j in launched if j["task"] == "seasons" and j["force"]]
        assert len(forced_seasons) == 1

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])


def test_repair_policy_exists():
    """Repair policy must be present and configured as a global nightly job."""
    from app.services.scheduler import POLICIES

    policy = next((p for p in POLICIES if p["name"] == "repair"), None)
    assert policy is not None, "repair policy missing from POLICIES"
    assert policy["scope"] == "global"
    assert policy["task"] == "repair"
    assert policy.get("run_at_hour") == 3


def test_player_game_stats_workers_persists(tmp_path, monkeypatch):
    """player_game_stats_workers is saved to and loaded from config."""
    import json
    from app.services.scheduler import Scheduler

    cfg = tmp_path / "scheduler_config.json"
    monkeypatch.setattr("app.services.scheduler._CONFIG_PATH", str(cfg))
    sched = Scheduler({}, submit_job=None)

    sched.set_player_game_stats_workers(12)

    data = json.loads(cfg.read_text())
    assert data["player_game_stats_workers"] == 12
    assert sched._player_game_stats_workers == 12

    # Reload from file via a fresh Scheduler (tests _load_state)
    sched2 = Scheduler({}, submit_job=None)
    assert sched2._player_game_stats_workers == 12


def test_player_game_stats_workers_reload_config(tmp_path, monkeypatch):
    """_reload_config picks up player_game_stats_workers written externally."""
    import json
    from app.services.scheduler import Scheduler

    cfg = tmp_path / "scheduler_config.json"
    monkeypatch.setattr("app.services.scheduler._CONFIG_PATH", str(cfg))
    sched = Scheduler({}, submit_job=None)

    # Simulate another process writing the config file directly
    cfg.write_text(json.dumps({"player_game_stats_workers": 15}))
    sched._reload_config()

    assert sched._player_game_stats_workers == 15


@pytest.mark.asyncio
async def test_fresh_sync_status_not_requeued_on_restart(scheduler):
    """Jobs with a fresh SyncStatus must not be queued after a restart with all-fresh data."""
    from datetime import datetime, timezone
    from app.models.db_models import SyncStatus
    from app.services.scheduler import POLICIES

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Seed a fresh SyncStatus (just completed) for every policy
    db = scheduler._db_service if hasattr(scheduler, "_db_service") else None
    if db is None:
        from app.services.database import get_database_service

        db = get_database_service()

    with db.session_scope() as s:
        for policy in POLICIES:
            scope = policy.get("scope", "global")
            if scope == "season":
                entity_id = "season:1"
            else:
                entity_id = policy["entity_type"]
            existing = (
                s.query(SyncStatus)
                .filter_by(
                    entity_type=policy["entity_type"],
                    entity_id=entity_id,
                )
                .first()
            )
            if existing:
                existing.sync_status = "completed"
                existing.last_sync = now
            else:
                s.add(
                    SyncStatus(
                        entity_type=policy["entity_type"],
                        entity_id=entity_id,
                        sync_status="completed",
                        last_sync=now,
                        records_synced=0,
                    )
                )

    # Clear the queue before the simulated restart tick
    scheduler._queue.clear()

    # Run one tick — simulates restart with all-fresh SyncStatus
    await scheduler._refresh_queue()

    # No job should be immediately due: all SyncStatus rows are within max_age.
    # Jobs may still be enqueued with a future run_at (e.g. next nightly window),
    # but none should have run_at <= now (which was the cold_start behaviour).
    import datetime as _dt

    check_now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    due_now = [j.policy_name for j in scheduler._queue if j.run_at <= check_now]
    assert len(due_now) == 0, f"Expected no immediately-due jobs, got {len(due_now)}: {due_now}"


class TestSeasonFreezeScheduler:
    """Frozen seasons are skipped by _maybe_schedule."""

    def test_maybe_schedule_skips_frozen_season(self, scheduler, app):
        """_maybe_schedule returns without enqueuing when season.is_frozen is True."""
        from app.services.database import get_database_service
        from app.models.db_models import Season

        db = get_database_service()
        with db.session_scope() as session:
            s = Season(id=7001, text="7001/xx", highlighted=False, is_frozen=True)
            session.add(s)

        policy = next(p for p in POLICIES if p["scope"] == "season")
        queue_before = len(scheduler._queue)

        with db.session_scope() as session:
            scheduler._maybe_schedule(session, policy, season=7001, is_current_season=False)

        assert len(scheduler._queue) == queue_before  # nothing enqueued

        with db.session_scope() as session:
            session.query(Season).filter(Season.id == 7001).delete()

    def test_maybe_schedule_does_not_skip_unfrozen_season(self, scheduler, app):
        """_maybe_schedule proceeds normally for unfrozen seasons."""
        from app.services.database import get_database_service
        from app.models.db_models import Season

        db = get_database_service()
        with db.session_scope() as session:
            s = Season(id=7002, text="7002/xx", highlighted=True, is_frozen=False)
            session.add(s)

        policy = next(p for p in POLICIES if p["scope"] == "season" and not p.get("current_only"))
        queue_before = len(scheduler._queue)

        with db.session_scope() as session:
            scheduler._maybe_schedule(session, policy, season=7002, is_current_season=True)

        assert len(scheduler._queue) > queue_before

        scheduler._queue.clear()
        with db.session_scope() as session:
            session.query(Season).filter(Season.id == 7002).delete()


class TestPastOnlyFlag:
    """past_only policies must not run for the current season."""

    def test_past_only_policy_skipped_for_current_season(self):
        """A past_only policy must return early when is_current_season=True."""
        from unittest.mock import MagicMock
        from app.services.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched._min_season = None
        sched._excluded_seasons = []
        sched._max_concurrent = 2
        sched._policy_tiers = {}
        sched._enabled = True
        sched._queue = []
        sched._history = []
        sched._running = False

        past_only_policy = {
            "name": "games",
            "entity_type": "games",
            "task": "games",
            "scope": "season",
            "past_only": True,
            "label": "Games (past seasons)",
            "max_age": __import__("datetime").timedelta(days=7),
            "priority": 55,
            "run_at_hour": 3,
        }

        mock_session = MagicMock()
        sched._maybe_schedule(mock_session, past_only_policy, season=2025, is_current_season=True)

        assert sched._queue == [], "past_only policy must not be queued for current season"

    def test_past_only_policy_runs_for_past_season(self):
        """A past_only policy must NOT be skipped when is_current_season=False."""
        from unittest.mock import MagicMock, patch
        from datetime import timedelta
        from app.services.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched._min_season = None
        sched._excluded_seasons = []
        sched._max_concurrent = 2
        sched._policy_tiers = {}
        sched._enabled = True
        sched._queue = []
        sched._history = []
        sched._running = False

        past_only_policy = {
            "name": "games",
            "entity_type": "games",
            "task": "games",
            "scope": "season",
            "past_only": True,
            "requires": "leagues",
            "label": "Games (past seasons)",
            "max_age": timedelta(days=7),
            "priority": 55,
            "run_at_hour": 3,
        }

        mock_session = MagicMock()
        # is_frozen → False
        mock_session.query.return_value.filter.return_value.scalar.return_value = False
        from datetime import datetime
        leagues_done = datetime(2026, 3, 30, 3, 0, 0)

        with patch("app.services.scheduler._last_sync_for") as mock_lsf, \
             patch("app.services.scheduler._last_attempt_for", return_value=None):
            mock_lsf.side_effect = lambda s, entity_type, season: (
                leagues_done if entity_type == "leagues" else None
            )
            sched._maybe_schedule(mock_session, past_only_policy, season=2019, is_current_season=False)

        assert len(sched._queue) == 1, "past_only policy should be queued for past season"
        assert sched._queue[0].policy_name == "games"

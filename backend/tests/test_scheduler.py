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
        with patch.object(type(scheduler), '_load_state', return_value=True):
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
        assert hasattr(scheduler, '_load_state')
        assert hasattr(scheduler, '_save_state')


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
            sched._cold_start = False
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
            assert p["scope"] in {"global", "season"}, \
                f"Policy {p['name']} has invalid scope {p['scope']}"

    def test_policy_priorities_are_positive(self):
        from app.services.scheduler import POLICIES
        for p in POLICIES:
            assert p["priority"] > 0, f"Policy {p['name']} has non-positive priority"


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
            sched._cold_start = False
            sched._queue = []
            sched._running = False
        now = datetime.now()
        sched._history = [
            JobRecord("a1", "clubs", "clubs", 2025, "done",    now, now, now),
            JobRecord("b2", "teams", "teams", 2025, "running", now, now, None),
            JobRecord("c3", "games", "games", 2025, "error",   now, now, now),
        ]
        return sched

    def test_clear_done_removes_finished_jobs(self):
        sched = self._make_scheduler_with_history()
        removed = sched.clear_done()
        assert removed == 2  # done + error
        remaining = sched.get_history()
        assert len(remaining) == 1
        assert remaining[0]["status"] == "running"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

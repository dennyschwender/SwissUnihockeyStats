"""
Tests for repair job overlap detection in _dispatch_due().

Verifies that the repair job is deferred by 30 minutes when other jobs
are still running, to prevent VACUUM from acquiring an exclusive lock
while writers are active.
"""
import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

from app.services.scheduler import Scheduler, ScheduledJob


def _utcnow():
    # Match the scheduler's naive-UTC convention
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_scheduler():
    """Create a minimal Scheduler instance without touching the DB."""
    with patch("app.services.scheduler.Scheduler._load_state", return_value=True):
        sched = Scheduler.__new__(Scheduler)
        sched._admin_jobs = {}
        sched._submit = AsyncMock(return_value="job-id")
        sched._running = False
        sched._queue = []
        sched._history = []
        sched._cold_start = False
        sched._enabled = True
        sched._max_concurrent = 5
        sched._min_season = None
        sched._excluded_seasons = []
        sched._policy_tiers = {}
    return sched


def _make_repair_job(run_at=None) -> ScheduledJob:
    if run_at is None:
        run_at = _utcnow() - timedelta(seconds=1)
    return ScheduledJob(
        run_at=run_at,
        priority=50,
        policy_name="repair",
        task="repair",
        season=None,
        label="repair",
        max_tier=7,
    )


def _make_games_job(run_at=None) -> ScheduledJob:
    if run_at is None:
        run_at = _utcnow() - timedelta(seconds=1)
    return ScheduledJob(
        run_at=run_at,
        priority=50,
        policy_name="games",
        task="games",
        season=2025,
        label="games",
        max_tier=7,
    )


async def test_repair_deferred_when_jobs_running():
    """repair job must be re-queued ~30 min out when other jobs are running."""
    sched = _make_scheduler()
    repair_job = _make_repair_job()
    sched._queue.append(repair_job)

    launched = []

    async def mock_launch(job):
        launched.append(job)

    with patch.object(sched, "_launch", side_effect=mock_launch), \
         patch.object(sched, "_count_running", return_value=1):
        await sched._dispatch_due()

    # repair must NOT have been launched
    assert repair_job not in launched, "repair job should not be launched while other jobs run"
    assert len(launched) == 0

    # repair must have been re-queued
    assert repair_job in sched._queue, "repair job should be back in the queue"

    # run_at must be approximately 30 minutes from now
    expected = _utcnow() + timedelta(minutes=30)
    delta = abs((repair_job.run_at - expected).total_seconds())
    assert delta < 5, f"run_at should be ~30 min from now, got delta={delta}s"


async def test_repair_launches_when_no_jobs_running():
    """repair job must be launched when no other jobs are running."""
    sched = _make_scheduler()
    repair_job = _make_repair_job()
    sched._queue.append(repair_job)

    launched = []

    async def mock_launch(job):
        launched.append(job)

    with patch.object(sched, "_launch", side_effect=mock_launch), \
         patch.object(sched, "_count_running", return_value=0):
        await sched._dispatch_due()

    assert repair_job in launched, "repair job should launch when no other jobs are running"
    assert repair_job not in sched._queue, "repair job should not be re-queued after launch"


async def test_non_repair_job_not_affected():
    """Non-repair jobs must be launched even when other jobs are running."""
    sched = _make_scheduler()
    games_job = _make_games_job()
    sched._queue.append(games_job)

    launched = []

    async def mock_launch(job):
        launched.append(job)

    with patch.object(sched, "_launch", side_effect=mock_launch), \
         patch.object(sched, "_count_running", return_value=1):
        await sched._dispatch_due()

    assert games_job in launched, "non-repair job should launch regardless of running jobs"
    assert games_job not in sched._queue, "non-repair job should not be re-queued"

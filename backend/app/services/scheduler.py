"""
Background job scheduler.

Implements the staged-update policy from DATABASE_IMPLEMENTATION.md:

  Entity              Frequency       Max Age
  ──────────────────  ──────────────  ────────
  Seasons             Yearly          30 days
  Clubs               Quarterly       7 days
  Teams               Monthly         3 days
  Players             Weekly          24 hours
  Leagues             Monthly         7 days
  Games (finished)    Once            N/A
  Games (today)       Hourly          1 hour
  Player Stats        After games     4 hours  (future)

The scheduler holds a priority queue of ScheduledJob items.
Every TICK_SECONDS it wakes up, pops all due jobs, and submits
them as admin background tasks via the same _run() mechanism
used by the admin POST /admin/api/index endpoint.

All scheduling state is in-memory; the *actual* freshness source of
truth is SyncStatus in the database, which is consulted every tick.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Policy definitions
# ─────────────────────────────────────────────────────────────────────────────

# The entity_type keys used in sync_status rows
# Each entry: (entity_type_prefix, max_age_timedelta, task_name, scope)
# scope: "global" = not per-season, "season" = repeat for each indexed season
POLICIES: list[dict] = [
    {
        "name":        "seasons",
        "entity_type": "seasons",
        "max_age":     timedelta(days=30),
        "task":        "seasons",       # special: calls index_seasons directly
        "scope":       "global",
        "label":       "Seasons refresh",
        "priority":    10,              # lower = higher prio
    },
    {
        "name":        "clubs",
        "entity_type": "clubs",
        "max_age":     timedelta(days=7),
        "task":        "clubs",
        "scope":       "season",
        "label":       "Clubs refresh",
        "priority":    20,
    },
    {
        "name":        "teams",
        "entity_type": "teams",
        "max_age":     timedelta(days=3),
        "task":        "teams",
        "scope":       "season",
        "label":       "Teams refresh",
        "priority":    30,
    },
    {
        "name":        "players",
        "entity_type": "players",
        "max_age":     timedelta(hours=24),
        "task":        "players",
        "scope":       "season",
        "label":       "Players refresh",
        "priority":    40,
    },
    {
        "name":        "leagues",
        "entity_type": "leagues",
        "max_age":     timedelta(days=7),
        "task":        "leagues",
        "scope":       "season",
        "label":       "Leagues refresh",
        "priority":    50,
    },
    {
        "name":        "league_groups",
        "entity_type": "league_groups",
        "max_age":     timedelta(days=7),
        "task":        "groups",
        "scope":       "season",
        "label":       "League groups refresh",
        "priority":    60,
    },
    {
        "name":        "games",
        "entity_type": "games",
        "max_age":     timedelta(days=7),
        "task":        "games",
        "scope":       "season",
        "label":       "Games refresh",
        "priority":    70,
    },
    {
        "name":        "game_events",
        "entity_type": "game_events",
        "max_age":     timedelta(hours=1),
        "task":        "events",
        "scope":       "season",
        "label":       "Game events refresh",
        "priority":    80,
    },
    {
        "name":        "player_stats",
        "entity_type": "player_stats",
        "max_age":     timedelta(hours=4),
        "task":        "player_stats",
        "scope":       "season",
        "label":       "Player stats refresh",
        "priority":    85,
    },
]

# How often the scheduler wakes up (seconds)
TICK_SECONDS = 300  # 5 minutes

# Where to persist scheduler config (enabled flag)
# Resolved relative to this file: ../../data/scheduler_config.json
_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__),   # .../backend/app/services
    "..", "..", "..",            # up to SwissUnihockeyStats/
    "data", "scheduler_config.json",
)
_CONFIG_PATH = os.path.normpath(_CONFIG_PATH)


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(order=True)
class ScheduledJob:
    """A job waiting in the queue."""
    run_at: datetime
    priority: int
    # fields below are not used for ordering
    policy_name: str = field(compare=False)
    task: str        = field(compare=False)
    season: int | None = field(compare=False, default=None)
    label: str       = field(compare=False, default="")


@dataclass
class JobRecord:
    """Runtime record for a submitted job."""
    job_id: str
    policy_name: str
    task: str
    season: int | None
    status: str          # pending / running / done / error
    scheduled_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    stats: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler
# ─────────────────────────────────────────────────────────────────────────────

class Scheduler:
    """
    Lightweight in-process scheduler backed by the SyncStatus table.

    Usage::

        sched = Scheduler(admin_jobs_dict, run_admin_job_coro)
        asyncio.create_task(sched.run())
        ...
        sched.stop()
    """

    def __init__(
        self,
        admin_jobs: dict,
        submit_job: Callable[[str, int | None, str, bool], Awaitable[str]],
    ):
        """
        admin_jobs  – the _admin_jobs dict shared with the admin routes
        submit_job  – async callable(job_id, season, task, force) → None
                      that starts the indexer coroutine for the given job_id
        """
        self._admin_jobs = admin_jobs
        self._submit = submit_job
        self._running = False
        self._queue: list[ScheduledJob] = []
        self._history: list[JobRecord] = []
        self._enabled = self._load_state()

    # ── persistence ───────────────────────────────────────────────────────────

    def _load_state(self) -> bool:
        """Return the persisted enabled flag (default True if file missing)."""
        try:
            with open(_CONFIG_PATH) as f:
                return bool(json.load(f).get("enabled", True))
        except (FileNotFoundError, json.JSONDecodeError):
            return True

    def _save_state(self):
        """Persist the current enabled flag to disk."""
        try:
            os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
            with open(_CONFIG_PATH, "w") as f:
                json.dump({"enabled": self._enabled}, f)
        except OSError as exc:
            logger.warning("[scheduler] could not save config: %s", exc)

    # ── public ────────────────────────────────────────────────────────────────

    def stop(self):
        self._running = False

    def enable(self, v: bool):
        self._enabled = v
        self._save_state()
        if v:
            # Drop any stale overdue jobs that accumulated while paused so
            # they don't all fire at once when the scheduler resumes.
            self._purge_overdue()
        logger.info("[scheduler] %s", "enabled" if v else "disabled")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _purge_overdue(self):
        """Remove jobs from the queue that are already past-due.

        Called when the scheduler is re-enabled so stale jobs don't burst.
        They will be naturally rescheduled on the next _refresh_queue tick.
        """
        now = _utcnow()
        stale = [j for j in self._queue if j.run_at <= now]
        for j in stale:
            self._queue.remove(j)
            logger.info(
                "[scheduler] cancelled stale job %s season=%s (was due %s)",
                j.policy_name, j.season,
                j.run_at.strftime("%Y-%m-%d %H:%M UTC"),
            )

    def get_schedule(self) -> list[dict]:
        """Return the current queue + next-run estimates for the admin UI."""
        now = _utcnow()
        out = []
        for job in sorted(self._queue):
            out.append({
                "policy":   job.policy_name,
                "task":     job.task,
                "season":   job.season,
                "label":    job.label,
                "run_at":    job.run_at.strftime("%Y-%m-%d %H:%M UTC"),
                "due_in_s": max(0, int((job.run_at - now).total_seconds())),
            })
        return out

    def get_history(self, limit: int = 50) -> list[dict]:
        return [
            {
                "job_id":       r.job_id,
                "policy":       r.policy_name,
                "task":         r.task,
                "season":       r.season,
                "status":       r.status,
                "scheduled_at": _fmt(r.scheduled_at),
                "started_at":   _fmt(r.started_at),
                "finished_at":  _fmt(r.finished_at),
                "error":        r.error,
                "stats":        r.stats,
            }
            for r in reversed(self._history[-limit:])
        ]

    async def trigger_now(self, policy_name: str, season: int | None) -> str | None:
        """Immediately launch a job for the given policy, bypassing the queue.

        Returns the job_id string on success, or None if the policy is unknown.
        """
        policy = _find_policy(policy_name)
        if not policy:
            return None
        logger.info("[scheduler] manual trigger: %s season=%s", policy_name, season)
        job = ScheduledJob(
            run_at=_utcnow(),
            priority=policy["priority"],
            policy_name=policy["name"],
            task=policy["task"],
            season=season,
            label=policy["label"] + (f" S{season}" if season else ""),
        )
        job_id = await self._launch_and_return_id(job)
        return job_id

    async def _launch_and_return_id(self, job: ScheduledJob) -> str:
        """Like _launch() but returns the job_id."""
        job_id = str(uuid.uuid4())[:8]
        record = JobRecord(
            job_id=job_id,
            policy_name=job.policy_name,
            task=job.task,
            season=job.season,
            status="pending",
            scheduled_at=job.run_at,
        )
        self._history.append(record)
        if len(self._history) > 500:
            self._history = self._history[-500:]

        logger.info(
            "[scheduler] launching job_id=%s  task=%s  season=%s",
            job_id, job.task, job.season,
        )

        self._admin_jobs[job_id] = {
            "job_id":    job_id,
            "season":    job.season,
            "task":      job.task,
            "label":     job.label,
            "status":    "running",
            "progress":  0,
            "stats":     {},
            "log_lines": [],
            "error":     None,
            "scheduled": True,
        }

        record.status = "running"
        record.started_at = _utcnow()

        try:
            await self._submit(job_id, job.season, job.task, force=False)
            asyncio.create_task(
                self._watch(job_id, record),
                name=f"sched-watch-{job_id}",
            )
        except Exception as exc:
            record.status = "error"
            record.error  = str(exc)
            record.finished_at = _utcnow()
            logger.error("[scheduler] launch failed %s: %s", job_id, exc)
        return job_id

    # ── main loop ─────────────────────────────────────────────────────────────

    async def run(self):
        self._running = True
        logger.info("[scheduler] started (tick=%ds)", TICK_SECONDS)
        try:
            # First tick is immediate so we populate the queue on startup
            await self._tick()
            while self._running:
                await asyncio.sleep(TICK_SECONDS)
                if self._running:
                    await self._tick()
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("[scheduler] stopped")

    # ── tick ──────────────────────────────────────────────────────────────────

    async def _tick(self):
        if not self._enabled:
            return
        try:
            await self._refresh_queue()
            await self._dispatch_due()
        except Exception as exc:
            logger.exception("[scheduler] tick error: %s", exc)

    async def _refresh_queue(self):
        """
        For every policy × season combination, check whether a job is already
        queued/running. If not, look up the last sync time and schedule the
        next run if the data is stale (or has never been synced).
        """
        try:
            from app.services.database import get_database_service
            from app.models.db_models import Season, SyncStatus
            db_service = get_database_service()

            with db_service.session_scope() as session:
                # Seasons that have been at least partially indexed
                indexed_seasons: list[int] = [
                    r[0] for r in session.query(Season.id).order_by(Season.id.desc()).all()
                ]

                for policy in POLICIES:
                    if policy["scope"] == "global":
                        self._maybe_schedule(session, policy, season=None)
                    else:
                        for sid in indexed_seasons:
                            self._maybe_schedule(session, policy, season=sid)
        except Exception as exc:
            logger.error("[scheduler] refresh_queue error: %s", exc)

    def _maybe_schedule(self, session, policy: dict, season: int | None):
        """Schedule a job if none is already queued for this policy+season."""
        key = (policy["name"], season)

        # Don't double-queue
        if any((j.policy_name, j.season) == key for j in self._queue):
            return

        # Don't re-queue if still running
        if any(
            r.policy_name == policy["name"] and r.season == season
            and r.status in ("pending", "running")
            for r in self._history
        ):
            return

        last_sync = _last_sync_for(session, policy["entity_type"], season)
        now = _utcnow()

        if last_sync is None:
            # Never synced – run soon (stagger by priority to avoid thundering herd)
            run_at = now + timedelta(seconds=policy["priority"])
        else:
            run_at = last_sync + policy["max_age"]

        self._enqueue(policy, season=season, run_at=run_at)

    def _enqueue(self, policy: dict, season: int | None, run_at: datetime):
        season_label = f" S{season}" if season else ""
        job = ScheduledJob(
            run_at=run_at,
            priority=policy["priority"],
            policy_name=policy["name"],
            task=policy["task"],
            season=season,
            label=f"{policy['label']}{season_label}",
        )
        self._queue.append(job)
        logger.debug(
            "[scheduler] queued %s season=%s run_at=%s",
            policy["name"], season, run_at.strftime("%Y-%m-%d %H:%M UTC"),
        )

    async def _dispatch_due(self):
        now = _utcnow()        
        due = [j for j in self._queue if j.run_at <= now]
        if not due:
            return

        # Remove from queue
        for j in due:
            self._queue.remove(j)

        # Jobs whose scheduled time is more than one tick old were queued
        # before the scheduler was paused / restarted.  Cancel them instead
        # of firing a burst; they will be naturally rescheduled on the next
        # _refresh_queue() call.
        stale_cutoff = now - timedelta(seconds=TICK_SECONDS)
        stale  = [j for j in due if j.run_at < stale_cutoff]
        fresh  = [j for j in due if j.run_at >= stale_cutoff]

        for j in stale:
            logger.info(
                "[scheduler] skipped overdue job %s season=%s (was due %s, scheduler was paused)",
                j.policy_name, j.season,
                j.run_at.strftime("%Y-%m-%d %H:%M UTC"),
            )

        # Sort by (run_at, priority) so highest-priority runs first
        fresh.sort()

        for job in fresh:
            await self._launch(job)

    async def _launch(self, job: ScheduledJob):
        await self._launch_and_return_id(job)

    async def _watch(self, job_id: str, record: JobRecord):
        """Poll the admin job dict until the job finishes."""
        consecutive_missing = 0
        while True:
            await asyncio.sleep(2)
            entry = self._admin_jobs.get(job_id)
            if not entry:
                consecutive_missing += 1
                if consecutive_missing >= 3:
                    record.status = "error"
                    record.error  = "job entry vanished (server may have restarted)"
                    record.finished_at = _utcnow()
                    logger.warning("[scheduler] job %s lost from registry", job_id)
                    return
                continue
            consecutive_missing = 0
            status = entry.get("status", "running")
            if status == "done":
                record.status      = "done"
                record.stats       = entry.get("stats", {})
                record.finished_at = _utcnow()
                logger.info(
                    "[scheduler] job %s done  stats=%s",
                    job_id, record.stats,
                )
                # Immediately refresh the queue so any newly-available
                # entities (e.g. season-scoped jobs after seasons run)
                # are picked up without waiting for the next 5-min tick.
                asyncio.create_task(self._tick())
                return
            if status in ("error", "stopped"):
                record.status      = status
                record.error       = entry.get("error", "unknown")
                record.finished_at = _utcnow()
                logger.warning(
                    "[scheduler] job %s %s: %s",
                    job_id, status, record.error,
                )
                asyncio.create_task(self._tick())
                return


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC


def _fmt(dt: datetime | None) -> str | None:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else None


def _find_policy(name: str) -> dict | None:
    return next((p for p in POLICIES if p["name"] == name), None)


def _last_sync_for(session, entity_type: str, season: int | None):
    """
    Return the most recent completed sync datetime for this entity_type / season,
    or None if never synced.
    """
    from app.models.db_models import SyncStatus

    q = (session.query(SyncStatus.last_sync)
         .filter(
             SyncStatus.entity_type == entity_type,
             SyncStatus.sync_status == "completed",
         ))

    if season is not None:
        # entity_id is like "clubs:2025" or just "2025" — match both patterns
        q = q.filter(
            SyncStatus.entity_id.like(f"%{season}%")
        )

    row = q.order_by(SyncStatus.last_sync.desc()).first()
    return row[0] if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton
# ─────────────────────────────────────────────────────────────────────────────

_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler | None:
    return _scheduler


def init_scheduler(admin_jobs: dict, submit_job) -> Scheduler:
    global _scheduler
    _scheduler = Scheduler(admin_jobs, submit_job)
    return _scheduler

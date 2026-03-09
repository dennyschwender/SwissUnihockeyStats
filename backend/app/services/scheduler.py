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
import time as _time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Awaitable

_SNAPSHOT_INTERVAL_S = 6 * 3600

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Policy definitions
# ─────────────────────────────────────────────────────────────────────────────

# The entity_type keys used in sync_status rows
# Each entry: (entity_type_prefix, max_age_timedelta, task_name, scope)
# scope: "global" = not per-season, "season" = repeat for each indexed season

def _snap_to_hour(dt: datetime, hour: int) -> datetime:
    """Return the earliest datetime > dt whose UTC hour == hour and minutes/seconds == 0.

    Used by nightly policies: pass last_sync as dt to get the very next
    nightly window after that sync.  This guarantees a run the following
    morning even when the last sync happened late in the evening, ensuring
    late-night game results are always captured by morning.
    """
    candidate = dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= dt:
        candidate += timedelta(days=1)
    return candidate
POLICIES: list[dict] = [
    # ── Weekly / multi-day policies — run at 03:00 UTC ──────────────────────
    # Snapped to 03:00 UTC (04:00–05:00 Swiss local) so nightly runs never
    # drift into the afternoon and are always finished before evening games.
    {
        "name":        "seasons",
        "entity_type": "seasons",
        "max_age":     timedelta(days=30),
        "task":        "seasons",       # special: calls index_seasons directly
        "scope":       "global",
        "label":       "Seasons refresh",
        "priority":    10,              # lower = higher prio
        "run_at_hour": 3,
    },
    {
        "name":        "clubs",
        "entity_type": "clubs",
        "max_age":     timedelta(days=7),
        "task":        "clubs",
        "scope":       "season",
        "label":       "Clubs refresh",
        "priority":    20,
        "run_at_hour": 3,
    },
    {
        "name":        "teams",
        "entity_type": "teams",
        "max_age":     timedelta(days=3),
        "task":        "teams",
        "scope":       "season",
        "label":       "Teams refresh",
        "priority":    30,
        "run_at_hour": 3,
    },
    {
        "name":        "players",
        "entity_type": "players",
        "max_age":     timedelta(hours=24),
        "task":        "players",
        "scope":       "season",
        "label":       "Players refresh",
        "priority":    40,
        "max_tier":    2,   # NLA/L-UPL + NLB only — /api/teams/{id}/players returns 400 for any lower league
        "run_at_hour": 3,
    },
    {
        "name":        "leagues",
        "entity_type": "leagues",
        "max_age":     timedelta(days=7),
        "task":        "leagues",
        "scope":       "season",
        "label":       "Leagues refresh",
        "priority":    50,
        "run_at_hour": 3,
    },
    {
        "name":        "games",
        "entity_type": "games",
        "max_age":     timedelta(days=7),
        "task":        "games",
        "scope":       "season",
        "label":       "Games refresh",
        "priority":    70,
        "run_at_hour": 3,
    },
    {
        "name":        "game_lineups",
        "entity_type": "game_lineups",
        "max_age":     timedelta(hours=24),
        "task":        "game_lineups",
        "scope":       "season",
        "label":       "Game lineups refresh",
        "priority":    75,      # runs after games (70), before game_events (80)
        "max_tier":    2,       # NLA + NLB + A-level only, mirrors game_events
        "run_at_hour": 3,
    },
    # ── Live / recent game-events polling ────────────────────────────────────
    # Runs every 10 minutes (no hour-snap) throughout the day so that:
    #   • live games (< 3 h old)   are refreshed every ~5 min
    #   • today's games (< 12 h)   are refreshed every ~1 h
    #   • yesterday's games (<48 h) are refreshed every ~4 h
    #   • older games (≥ 48 h)     are skipped immediately (720 h TTL)
    # The per-game TTL is computed by _game_events_ttl_hours() inside
    # index_game_events(); the scheduler just provides the trigger cadence.
    # player_stats / player_game_stats still run at 04:00 UTC (after the
    # overnight events pass) so G/A/PIM numbers reflect last night's games.
    {
        "name":        "game_events",
        "entity_type": "game_events",
        "max_age":     timedelta(minutes=10),
        "task":        "events",
        "scope":       "season",
        "label":       "Game events refresh",
        "priority":    80,
        "max_tier":    2,   # NLA + NLB + A-level youth only
        "current_only": True,
        # no run_at_hour — runs throughout the day based on game ages
    },
    # ── Player season stats: cascade T1 → T2 → … → T6 ──────────────────────
    # current_only is NOT set: these run once for past seasons too (frozen after
    # first successful sync). Tiers beyond the players policy max_tier will find
    # 0 players and freeze immediately via the empty-tier stamp.
    # run_at_hour=4: runs after game_events (03:xx) so stats reflect last night's games.
    {
        "name":        "player_stats_t1",
        "entity_type": "player_stats_t1",
        "max_age":     timedelta(hours=24),
        "task":        "player_stats",
        "scope":       "season",
        "label":       "Player stats \u2013 T1 (NLA/L-UPL)",
        "priority":    85,
        "max_tier":    1,
        "fixed_tier":  True,
        "run_at_hour": 4,
    },
    {
        "name":        "player_stats_t2",
        "entity_type": "player_stats_t2",
        "max_age":     timedelta(hours=24),
        "task":        "player_stats",
        "scope":       "season",
        "label":       "Player stats \u2013 T2 (NLB)",
        "priority":    85,
        "max_tier":    2,
        "fixed_tier":  True,
        "requires":    "player_stats_t1",
        "run_at_hour": 4,
    },
    {
        "name":        "player_stats_t3",
        "entity_type": "player_stats_t3",
        "max_age":     timedelta(hours=24),
        "task":        "player_stats",
        "scope":       "season",
        "label":       "Player stats \u2013 T3 (1.Liga)",
        "priority":    85,
        "max_tier":    3,
        "fixed_tier":  True,
        "requires":    "player_stats_t2",
        "run_at_hour": 4,
    },
    {
        "name":        "player_stats_t4",
        "entity_type": "player_stats_t4",
        "max_age":     timedelta(hours=24),
        "task":        "player_stats",
        "scope":       "season",
        "label":       "Player stats \u2013 T4 (2.Liga)",
        "priority":    85,
        "max_tier":    4,
        "fixed_tier":  True,
        "requires":    "player_stats_t3",
        "run_at_hour": 4,
    },
    {
        "name":        "player_stats_t5",
        "entity_type": "player_stats_t5",
        "max_age":     timedelta(hours=24),
        "task":        "player_stats",
        "scope":       "season",
        "label":       "Player stats \u2013 T5 (3.Liga)",
        "priority":    85,
        "max_tier":    5,
        "fixed_tier":  True,
        "requires":    "player_stats_t4",
        "run_at_hour": 4,
    },
    {
        "name":        "player_stats_t6",
        "entity_type": "player_stats_t6",
        "max_age":     timedelta(hours=24),
        "task":        "player_stats",
        "scope":       "season",
        "label":       "Player stats \u2013 T6 (4./5.Liga, Regional)",
        "priority":    85,
        "max_tier":    6,
        "fixed_tier":  True,
        "requires":    "player_stats_t5",
        "run_at_hour": 4,
    },
    # ── Per-game G/A/PIM: cascade T1 → T2 → … → T6 ──────────────────────────
    # current_only is NOT set: same rationale as player_stats above.
    # run_at_hour=4: runs after game_events (03:xx) so stats reflect last night's games.
    {
        "name":        "player_game_stats_t1",
        "entity_type": "player_game_stats_t1",
        "max_age":     timedelta(hours=24),
        "task":        "player_game_stats",
        "scope":       "season",
        "label":       "Per-game G/A/PIM \u2013 T1 (NLA/L-UPL)",
        "priority":    86,
        "max_tier":    1,
        "fixed_tier":  True,
        "run_at_hour": 4,
    },
    {
        "name":        "player_game_stats_t2",
        "entity_type": "player_game_stats_t2",
        "max_age":     timedelta(hours=24),
        "task":        "player_game_stats",
        "scope":       "season",
        "label":       "Per-game G/A/PIM \u2013 T2 (NLB)",
        "priority":    86,
        "max_tier":    2,
        "fixed_tier":  True,
        "requires":    "player_game_stats_t1",
        "run_at_hour": 4,
    },
    {
        "name":        "player_game_stats_t3",
        "entity_type": "player_game_stats_t3",
        "max_age":     timedelta(hours=24),
        "task":        "player_game_stats",
        "scope":       "season",
        "label":       "Per-game G/A/PIM \u2013 T3 (1.Liga)",
        "priority":    86,
        "max_tier":    3,
        "fixed_tier":  True,
        "requires":    "player_game_stats_t2",
        "run_at_hour": 4,
    },
    {
        "name":        "player_game_stats_t4",
        "entity_type": "player_game_stats_t4",
        "max_age":     timedelta(hours=24),
        "task":        "player_game_stats",
        "scope":       "season",
        "label":       "Per-game G/A/PIM \u2013 T4 (2.Liga)",
        "priority":    86,
        "max_tier":    4,
        "fixed_tier":  True,
        "requires":    "player_game_stats_t3",
        "run_at_hour": 4,
    },
    {
        "name":        "player_game_stats_t5",
        "entity_type": "player_game_stats_t5",
        "max_age":     timedelta(hours=24),
        "task":        "player_game_stats",
        "scope":       "season",
        "label":       "Per-game G/A/PIM \u2013 T5 (3.Liga)",
        "priority":    86,
        "max_tier":    5,
        "fixed_tier":  True,
        "requires":    "player_game_stats_t4",
        "run_at_hour": 4,
    },
    {
        "name":        "player_game_stats_t6",
        "entity_type": "player_game_stats_t6",
        "max_age":     timedelta(hours=24),
        "task":        "player_game_stats",
        "scope":       "season",
        "label":       "Per-game G/A/PIM \u2013 T6 (4./5.Liga, Regional)",
        "priority":    86,
        "max_tier":    6,
        "fixed_tier":  True,
        "requires":    "player_game_stats_t5",
        "run_at_hour": 4,
    },

    # ── Nightly DB repair ─────────────────────────────────────────────────
    # Runs at 03:30 UTC — after nightly indexing jobs (03:00) so repairs
    # catch anything they left behind.  Global scope: no season argument.
    {
        "name":        "repair",
        "entity_type": "repair",
        "max_age":     timedelta(hours=24),
        "task":        "repair",
        "scope":       "global",
        "label":       "Nightly DB repair",
        "priority":    90,
        "run_at_hour": 3,
    },
]

# How often the scheduler wakes up (seconds)
TICK_SECONDS = 300  # 5 minutes

# Where to persist scheduler config.
# Use DATA_DIR env var if set (Docker: /app/data), else resolve relative to this
# file (local dev: backend/app/services/../../../data).
_DATA_DIR_ENV = os.environ.get("DATA_DIR")
if _DATA_DIR_ENV:
    _CONFIG_PATH = os.path.join(_DATA_DIR_ENV, "scheduler_config.json")
else:
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
    max_tier: int    = field(compare=False, default=7)


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
        submit_job: Callable[[str, int | None, str, bool, int], Awaitable[str]],
    ):
        """
        admin_jobs  – the _admin_jobs dict shared with the admin routes
        submit_job  – async callable(job_id, season, task, force, max_tier) → None
                      that starts the indexer coroutine for the given job_id
        """
        self._admin_jobs = admin_jobs
        self._submit = submit_job
        self._running = False
        self._queue: list[ScheduledJob] = []
        self._history: list[JobRecord] = []
        self._cold_start = True   # run all jobs immediately on first enable
        self._enabled = self._load_state()
        self._last_snapshot_ts: float = 0.0

    # ── persistence ───────────────────────────────────────────────────────────

    def _load_state(self) -> bool:
        """Return the persisted enabled flag (default True if file missing)."""
        try:
            with open(_CONFIG_PATH) as f:
                data = json.load(f)
                self._min_season: int | None = data.get("min_season", None)
                self._excluded_seasons: list[int] = data.get("excluded_seasons", [])
                self._max_concurrent: int = max(1, int(data.get("max_concurrent", 2)))
                self._policy_tiers: dict[str, int] = data.get("policy_tiers", {})
                return bool(data.get("enabled", True))
        except (FileNotFoundError, json.JSONDecodeError):
            self._min_season = None
            self._excluded_seasons = []
            self._max_concurrent = 2
            self._policy_tiers = {}
            return True

    def _save_state(self):
        """Persist the current config to disk (atomic write to avoid truncation)."""
        try:
            os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
            tmp = _CONFIG_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump({
                    "enabled": self._enabled,
                    "min_season": self._min_season,
                    "excluded_seasons": self._excluded_seasons,
                    "max_concurrent": self._max_concurrent,
                    "policy_tiers": self._policy_tiers,
                }, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, _CONFIG_PATH)  # atomic on POSIX
        except OSError as exc:
            logger.warning("[scheduler] could not save config: %s", exc)

    def _reload_config(self):
        """Re-read config fields from disk without touching queue/job state.

        Called by getters so that all gunicorn worker processes return
        the latest saved values, even if another worker handled the POST
        that changed them.  The Scheduler's running state (queue, history,
        _enabled) is NOT changed here — only the admin-controlled knobs.
        """
        try:
            with open(_CONFIG_PATH) as f:
                data = json.load(f)
            self._min_season = data.get("min_season", None)
            self._excluded_seasons = data.get("excluded_seasons", [])
            self._max_concurrent = max(1, int(data.get("max_concurrent", 2)))
            self._policy_tiers = data.get("policy_tiers", {})
        except (FileNotFoundError, json.JSONDecodeError):
            pass  # keep current in-memory values on read failure

    # ── public ────────────────────────────────────────────────────────────────

    def stop(self):
        self._running = False

    def get_season_filter(self) -> dict:
        self._reload_config()
        return {
            "min_season": self._min_season,
            "excluded_seasons": sorted(self._excluded_seasons),
            "max_concurrent": self._max_concurrent,
        }

    # Extra per-task tier keys that are configurable but don't correspond to a
    # single non-cascade POLICY entry.  These control the manual season-card
    # dropdowns and are displayed in the Settings tier editor.
    _EXTRA_TIER_DEFAULTS: dict[str, int] = {
        "player_stats":      3,
        "game_lineups":      3,
        "player_game_stats": 3,
    }

    def get_policy_tiers(self) -> dict:
        """Return the effective max_tier for every season-scoped policy.

        Policies marked with fixed_tier=True have their tier baked into their
        name and are excluded — they should not appear in the tier editor.
        Extra per-task keys (player_stats, game_lineups, player_game_stats) are
        appended at the end so they show up in the Settings tier table.
        """
        self._reload_config()
        result = {
            p["name"]: self._policy_tiers.get(p["name"], p.get("max_tier", 7))
            for p in POLICIES
            if p["scope"] == "season" and not p.get("fixed_tier")
        }
        for key, default in self._EXTRA_TIER_DEFAULTS.items():
            result[key] = self._policy_tiers.get(key, default)
        return result

    def set_policy_tiers(self, tiers: dict[str, int]):
        """Override max_tier for the given policies and persist to disk."""
        valid_names = {p["name"] for p in POLICIES} | set(self._EXTRA_TIER_DEFAULTS)
        for name, tier in tiers.items():
            if name not in valid_names:
                continue
            self._policy_tiers[name] = max(1, min(6, int(tier)))
        self._save_state()
        logger.info("[scheduler] policy_tiers updated: %s", self._policy_tiers)

    def set_max_concurrent(self, n: int):
        """Set maximum number of jobs that may run simultaneously."""
        self._max_concurrent = max(1, n)
        self._save_state()
        logger.info("[scheduler] max_concurrent set to %d", self._max_concurrent)

    def _count_running(self) -> int:
        """Count jobs currently in pending/running state."""
        return sum(
            1 for r in self._history
            if r.status in ("pending", "running")
        )

    def set_season_filter(self, min_season: int | None, excluded_seasons: list[int]):
        """Persist season filter settings and clear any queued jobs for filtered seasons."""
        self._min_season = min_season
        self._excluded_seasons = list(excluded_seasons)
        self._save_state()
        # Drop queued jobs for now-excluded seasons
        before = len(self._queue)
        self._queue = [j for j in self._queue if not self._season_filtered(j.season)]
        dropped = before - len(self._queue)
        if dropped:
            logger.info("[scheduler] dropped %d queued job(s) for filtered seasons", dropped)
        logger.info(
            "[scheduler] season filter updated: min=%s excluded=%s",
            min_season, excluded_seasons,
        )

    def _season_filtered(self, season: int | None) -> bool:
        """Return True if this season should be skipped."""
        if season is None:
            return False  # global-scope jobs are never filtered
        if self._min_season is not None and season < self._min_season:
            return True
        if season in self._excluded_seasons:
            return True
        return False

    def enable(self, v: bool):
        self._enabled = v
        self._save_state()
        if v:
            # Drop any stale queued jobs so re-enable triggers a fresh
            # cold-start run for all policies (don't wait for max_age).
            self._purge_overdue()
            self._cold_start = True
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
                "run_at":   job.run_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
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

    def clear_done(self) -> int:
        """Remove all finished (done/error) entries from history. Returns count removed."""
        before = len(self._history)
        self._history = [r for r in self._history if r.status in ("running", "pending")]
        return before - len(self._history)

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
            max_tier=policy.get("max_tier", 7),
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
            await self._submit(job_id, job.season, job.task, False, job.max_tier)
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

        # Write stats snapshot every 6 hours
        now_mono = _time.monotonic()
        if now_mono - self._last_snapshot_ts >= _SNAPSHOT_INTERVAL_S:
            try:
                from app.services.stats_snapshot import write_stats_snapshot
                from app.services.database import get_database_service
                recent = [j for j in list(self._history)[-200:] if j.status == "done"]
                durations = [
                    (j.finished_at - j.started_at).total_seconds()
                    for j in recent
                    if j.finished_at is not None and j.started_at is not None
                ]
                avg_dur = sum(durations) / len(durations) if durations else 0.0
                errors  = sum(1 for j in list(self._history)[-200:] if j.error)
                write_stats_snapshot(
                    get_database_service(),
                    jobs_run=len(recent),
                    jobs_errors=errors,
                    avg_job_duration_s=avg_dur,
                )
            except Exception as exc:
                logger.warning("Failed to write stats snapshot: %s", exc)
            self._last_snapshot_ts = now_mono

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
                season_rows = (
                    session.query(Season.id, Season.highlighted)
                    .order_by(Season.id.desc())
                    .all()
                )
                # Identify the current (highlighted) season — only it gets recurring updates
                current_season_id: int | None = next(
                    (r[0] for r in season_rows if r[1]), None
                )
                indexed_seasons: list[int] = [r[0] for r in season_rows]

                for policy in POLICIES:
                    if policy["scope"] == "global":
                        self._maybe_schedule(session, policy, season=None, is_current_season=True)
                    else:
                        for sid in indexed_seasons:
                            if self._season_filtered(sid):
                                continue
                            self._maybe_schedule(
                                session, policy, season=sid,
                                is_current_season=(sid == current_season_id),
                            )

                # Cold start complete – subsequent ticks use normal max_age scheduling
                self._cold_start = False
        except Exception as exc:
            logger.error("[scheduler] refresh_queue error: %s", exc, exc_info=True)

    def _maybe_schedule(
        self,
        session,
        policy: dict,
        season: int | None,
        is_current_season: bool = True,
    ):
        """Schedule a job if none is already queued for this policy+season.

        Past seasons (is_current_season=False) are indexed once and then frozen:
        once a completed sync exists their data never changes, so we skip
        rescheduling to avoid thousands of redundant API calls per day.
        """
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

        # current_only policies (e.g. game_events) are live data that changes
        # every match — they must never run on past seasons, even for an initial sync.
        if policy.get("current_only") and not is_current_season:
            return

        # Cascade prerequisite: ensure ordering on the very first run
        # (T1 must have completed at least once before T2 is eligible, etc.).
        # We do NOT block on staleness here — each tier's own max_age already
        # governs when it re-runs.  Blocking on staleness caused T3–T6 to stay
        # permanently gated whenever T1/T2 hadn't refreshed within the window.
        if "requires" in policy:
            req_last = _last_sync_for(session, policy["requires"], season)
            if req_last is None:
                return  # prerequisite has never completed for this season yet

        # Past seasons are frozen once indexed — their data never changes after
        # the season ends, so we index once and never reschedule again.
        if not is_current_season and last_sync is not None:
            return

        # For past seasons: if the last attempt (even a failed one) was recent,
        # don't keep retrying.  This prevents infinite re-queuing when the API
        # no longer serves historical data (returns error → status='failed' →
        # _last_sync_for finds nothing → schedules again → repeat).
        if not is_current_season and last_sync is None:
            last_attempt = _last_attempt_for(session, policy["entity_type"], season)
            if last_attempt is not None:
                # Normalize to naive UTC to match _utcnow() (which is naive).
                # DB rows written with datetime.now(timezone.utc) may be
                # returned as offset-aware by SQLAlchemy on some backends.
                if last_attempt.tzinfo is not None:
                    last_attempt = last_attempt.replace(tzinfo=None)
                if (now - last_attempt) < policy["max_age"]:
                    return  # back off until max_age expires

        if last_sync is None or self._cold_start:
            # Never synced or cold-start (first run after enable) –
            # run soon, staggered by priority to avoid thundering herd.
            run_at = now + timedelta(seconds=policy["priority"])
        else:
            if "run_at_hour" in policy:
                # Snap to the next nightly window AFTER the last sync, not after
                # last_sync + max_age.  Anchoring on max_age caused night-time
                # manual syncs (e.g. 20:23) to skip the very next 03:00 window
                # entirely because last_sync + max_age (e.g. next-day 20:23) was
                # still past the only 03:00 candidate for that day → snapped to
                # the morning two days later.  Snapping from last_sync instead
                # always schedules the immediately following nightly window, which
                # is what we want so late-evening games are indexed by morning.
                run_at = _snap_to_hour(last_sync, policy["run_at_hour"])
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
            max_tier=self._policy_tiers.get(policy["name"]) or policy.get("max_tier") or 7,
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

        # Remove all due jobs from the queue up front
        for j in due:
            self._queue.remove(j)

        # Sort by (run_at, priority) — oldest/highest-priority first
        due.sort()

        # Enforce concurrency cap: dispatch up to available slots,
        # re-enqueue overflow with a short stagger so they fire quickly.
        slots = max(0, self._max_concurrent - self._count_running())
        to_launch = due[:slots]
        to_defer  = due[slots:]

        for i, j in enumerate(to_defer):
            j.run_at = now + timedelta(seconds=5 + i * 3)
            self._queue.append(j)

        if to_defer:
            logger.info(
                "[scheduler] deferred %d job(s) (max_concurrent=%d, running=%d)",
                len(to_defer), self._max_concurrent, self._count_running(),
            )
            # Schedule a fast follow-up tick so deferred jobs aren't waiting
            # the full TICK_SECONDS interval before the next dispatch attempt.
            asyncio.create_task(self._deferred_tick(delay=8))

        for job in to_launch:
            if job.task == "repair" and self._count_running() > 0:
                # Other jobs are still running — defer repair by 30 minutes so
                # VACUUM doesn't acquire an exclusive lock while writers are active.
                deferred_run_at = now + timedelta(minutes=30)
                job.run_at = deferred_run_at
                self._queue.append(job)
                logger.info(
                    "[scheduler] deferred repair by 30min (%d job(s) still running)",
                    self._count_running(),
                )
                continue
            await self._launch(job)

    async def _deferred_tick(self, delay: int = 8):
        """Fire a tick after a short delay to dispatch deferred overflow jobs."""
        await asyncio.sleep(delay)
        await self._tick()

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
        # entity_id is stored as "clubs:2025" or just "2025".
        # Use exact-match alternatives to avoid season 202 matching 2025.
        q = q.filter(
            (SyncStatus.entity_id == str(season)) |
            SyncStatus.entity_id.like(f"%:{season}")
        )

    row = q.order_by(SyncStatus.last_sync.desc()).first()
    return row[0] if row else None


def _last_attempt_for(session, entity_type: str, season: int | None):
    """
    Return the most recent sync attempt datetime (any status) for this
    entity_type / season, or None if never attempted.  Used to suppress
    retries for past seasons that keep failing (e.g. API no longer returns
    historical data) so we don't hammer the API every tick.
    """
    from app.models.db_models import SyncStatus

    q = (session.query(SyncStatus.last_sync)
         .filter(SyncStatus.entity_type == entity_type))

    if season is not None:
        q = q.filter(
            (SyncStatus.entity_id == str(season)) |
            SyncStatus.entity_id.like(f"%:{season}")
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

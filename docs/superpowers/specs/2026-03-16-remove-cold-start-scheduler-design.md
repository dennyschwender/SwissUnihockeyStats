# Remove Scheduler Cold-Start Queue Flooding — Design Spec

**Date:** 2026-03-16
**Status:** Approved

---

## Problem

On every server restart, `Scheduler._cold_start = True` causes `_maybe_schedule()` to enqueue **all** policies immediately, regardless of how recently they ran. A restart after a recent full sync floods the queue with 19 × N-seasons redundant jobs. These run unnecessarily, hold the SQLite write lock, and delay genuinely stale jobs.

---

## Root Cause

```python
# _maybe_schedule() — current behaviour
if last_sync is None or self._cold_start:
    self._enqueue(policy, season, run_at=now + stagger)
```

`self._cold_start` is `True` for the entire first scheduler tick. Any policy with a fresh `SyncStatus` row is still enqueued.

---

## Fix

Remove `_cold_start` entirely. The correct invariant is already expressed by `last_sync is None`:

```python
# _maybe_schedule() — after fix
if last_sync is None:
    self._enqueue(policy, season, run_at=now + stagger)
```

A job is enqueued on startup only if:
- `last_sync is None` — never run (fresh install, new season added), **or**
- `last_sync + max_age < now` — genuinely stale (handled by the existing stale-check branch, unchanged)

Fresh installs still bootstrap correctly: every policy has `last_sync is None` → all jobs queue immediately, staggered by priority. Restarts with fresh SyncStatus → nothing queued.

---

## Changes

### `backend/app/services/scheduler.py`

1. Remove `self._cold_start = True` from `__init__`.
2. Remove `self._cold_start = False` from the post-first-tick reset (if it exists).
3. In `_maybe_schedule()`, remove `or self._cold_start` from the condition.
4. Remove any other references to `_cold_start`.

No other files need changes. All other scheduler logic (snap-to-hour, max_age windows, `requires` dependency, `current_only`, priority staggering) is untouched.

---

## Testing

- Existing tests that verify stale jobs queue and fresh jobs skip continue to pass unchanged.
- New test: seed `SyncStatus` rows marking all policies as freshly completed, construct a `Scheduler`, run one tick, assert the job queue is empty.

---

## Success Criteria

1. After a server restart, no jobs are enqueued for policies whose SyncStatus is within `max_age`.
2. On a fresh install (empty DB), all policies still enqueue on the first tick.
3. All existing scheduler tests pass.

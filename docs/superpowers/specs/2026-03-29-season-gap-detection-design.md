# Season Gap Detection Design

**Date:** 2026-03-29
**Status:** Approved

## Problem

When `min_season` is set in the admin scheduler config, the scheduler only iterates over seasons already present in the `Season` DB table. If a season in the expected range `[min_season, current_season]` has never been fetched, it is silently absent — no jobs are ever queued for it, even if the user expects it to be indexed.

The `index_seasons` global task (which populates the `Season` table) has a 30-day max_age, so missing seasons can remain absent for up to a month after changing `min_season`.

## Goal

When `min_season` is configured, seasons in the range `[min_season, current_season]` that are missing from the DB should be fetched close to immediately (not waiting up to 30 days), and continue to be indexed until frozen.

## Design

### Gap detection in `refresh_queue`

After computing `indexed_seasons` from the DB, add a gap check:

```python
if self._min_season is not None and current_season_id is not None:
    expected = set(range(self._min_season, current_season_id + 1))
    missing = expected - set(indexed_seasons)
    if missing:
        # force index_seasons if not already queued/running
```

If `min_season` is `None` (no lower bound), skip the check entirely.

### Forced `index_seasons` job

When gaps are detected and no `seasons` job is already queued or running, append an immediate `Job` directly onto `self._queue` with:

- `run_at = _utcnow()` (immediate)
- `force = True` (bypasses the 30-day `_should_update` cache in `index_seasons`)
- `label = "Seasons refresh (gap fill)"` (visible in admin job history)

The `force` flag is already threaded through the dispatch path to `data_indexer.index_seasons(force=True)` — no changes needed there.

### After `index_seasons` completes

No additional changes needed. On the next `refresh_queue` tick:

1. New `Season` rows appear in `indexed_seasons`
2. `_season_filtered` passes them (they are ≥ `min_season`)
3. `_maybe_schedule` queues all their policies immediately (`last_sync is None`)

Past seasons are indexed once per policy and then auto-frozen by the existing freeze logic. The gap detection check will no longer fire once all expected seasons are in the DB.

## Scope

- One change: add ~15 lines to `refresh_queue` in `scheduler.py`
- No changes to `data_indexer.py`, `main.py`, admin UI, or DB models
- No new tests required beyond verifying existing scheduler tests still pass (the gap-fill path is simple enough to be covered by integration testing against the live admin)

## Out of Scope

- Triggering gap fill on `set_season_filter` (Option A) — redundant given self-healing tick
- UI feedback for in-progress gap fill — job appears in normal scheduler history

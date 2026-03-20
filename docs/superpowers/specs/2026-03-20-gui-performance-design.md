# GUI Performance: Query Fixes + In-Memory TTL Cache

**Date:** 2026-03-20
**Status:** Approved
**Priority:** High — pages take 3–5s to load on Raspberry Pi 5

## Problem

Page navigation takes seconds. The two highest-traffic pages — home and league detail — are the worst offenders. Root causes identified via code analysis:

1. **N+1 queries** in `get_overall_top_scorers()`: 20 sequential DB queries per home page load to resolve each player's primary team.
2. **Lazy-loaded relationships**: `League.groups` accessed post-query in `get_league_top_scorers()` and `get_league_top_penalties()`, triggering N sub-queries.
3. **Missing composite index** on `PlayerStatistics(season_id, league_abbrev, points DESC)`: top-scorer queries do full table scan + sort.
4. **No caching**: Every page load re-runs all expensive queries even though underlying data only changes during sync jobs (hourly/nightly).

## Approach: Option B — Query Fixes + Short-TTL In-Memory Cache

Fix the root-cause query issues AND add a lightweight TTL cache for the 4 most expensive functions.

## Design

### Part 1: Query Fixes

**Fix 1 — `get_overall_top_scorers()` N+1** (`stats_service.py` ~line 1193)

Current: loops over top-20 player results, fires one `session.query(PlayerStatistics)` per player to find their primary team (21+ queries total).

Fix: after fetching top-N player IDs, fetch all their `PlayerStatistics` rows in a single `IN` query, then resolve primary team in Python by selecting the row with the highest `games_played` per player.

**Fix 2 — `League.groups` lazy load** (`stats_service.py` ~lines 637, 976)

In `get_league_top_scorers()` and `get_league_top_penalties()`, `league.groups` is accessed after the league is queried, triggering SQLAlchemy lazy loading. Fix: add `.options(joinedload(League.groups))` to the initial league query in both functions.

**Fix 3 — Composite index on `PlayerStatistics`** (`models.py`)

Add `Index("idx_stats_season_league_points", "season_id", "league_abbrev", "points")` to the `PlayerStatistics` model. Add idempotent migration in `database.py` (pattern already established for other indexes).

### Part 2: In-Memory TTL Cache

**New module: `services/cache.py`**

A plain dict-based cache with no external dependencies:

```python
_cache: dict[tuple, tuple[Any, float]]  # key → (value, stored_at_timestamp)
```

Public API:
- `get_cached(key: tuple) -> Any | None` — returns value if not expired, else None
- `set_cached(key: tuple, value: Any) -> None` — stores value with current timestamp
- `invalidate_prefix(prefix: str) -> None` — removes all keys where `key[0] == prefix`

TTL configured via env var `QUERY_CACHE_TTL_SECONDS`, default `3600` (1 hour). Data changes only during sync jobs so 1-hour staleness is acceptable.

**Functions to cache** (wrap with get/set in `stats_service.py`):

| Function | Cache key |
|---|---|
| `get_overall_top_scorers(season_id, gender)` | `("top_scorers", season_id, gender)` |
| `get_league_standings(league_id, season_id)` | `("standings", league_id, season_id)` |
| `get_league_top_scorers(league_id, season_id)` | `("league_scorers", league_id, season_id)` |
| `get_league_top_penalties(league_id, season_id)` | `("league_penalties", league_id, season_id)` |

**Cache invalidation:**

When a sync job completes in `data_indexer.py`, call `invalidate_prefix(...)` for the relevant prefix. This ensures cache is cleared after a sync without waiting for TTL expiry:

- After `index_games_for_league(league_id, season_id)` completes → invalidate `"standings"`, `"league_scorers"`, `"league_penalties"` for that league/season
- After `index_player_stats(season_id)` completes → invalidate `"top_scorers"` for that season

## Out of Scope

- HTMX partial re-queries (minor traffic, low impact)
- Large JSON payloads in templates (client-side, not server perf)
- Chart.js lazy loading (admin only)
- Background job speed improvements
- HTTP-level caching headers
- `get_league_top_penalties` logic deduplication (separate refactor)

## Expected Outcome

| Page | Before | After (cold) | After (warm) |
|------|--------|-------------|--------------|
| Home | 3–5s | 1–2s | <200ms |
| League detail | 3–5s | 1–2s | <200ms |
| Team detail | 0.5–1s | 0.3–0.5s | <200ms |

Cold = first hit after cache miss or TTL expiry. Warm = cached result served.

## Files Changed

| File | Change |
|------|--------|
| `backend/app/services/cache.py` | New — TTL cache module |
| `backend/app/services/stats_service.py` | Fix N+1, add joinedload, wrap 4 functions with cache |
| `backend/app/models.py` | Add composite index on PlayerStatistics |
| `backend/app/services/database.py` | Add idempotent migration for new index |
| `backend/app/services/data_indexer.py` | Call `invalidate_prefix()` after relevant syncs |
| `backend/tests/test_cache.py` | New — unit tests for cache module |

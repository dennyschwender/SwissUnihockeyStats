# Home Page Cache: upcoming_games + latest_results

**Date:** 2026-03-20
**Status:** Approved
**Priority:** High — home page loads 3–4s on Pi5; `get_upcoming_games` and `get_latest_results` are uncached

## Problem

The home page calls `get_upcoming_games` and `get_latest_results` on every request. These are not cached. The existing TTL cache (added in the GUI performance session) covers standings, scorers, and penalties — but not these two functions, which dominate home page latency.

## Approach

Apply the same `get_cached` / `set_cached` pattern already used for `get_league_standings`, `get_overall_top_scorers`, etc. in `stats_service.py`. Add invalidation hooks in `data_indexer.py` after the two syncs that change games data.

## Design

### Cache keys

Both functions accept `(limit, league_ids, league_category, season_id)`. `league_ids` is a legacy parameter never passed from the home page — ignore it in the cache key.

| Function | Cache key |
|---|---|
| `get_upcoming_games` | `("upcoming_games", season_id, league_category, limit)` |
| `get_latest_results` | `("latest_results", season_id, league_category, limit)` |

`league_category` is a string like `"2_11"` or `None`. Including it in the key caches all filtered variants separately. `season_id` will be the resolved value after the `if season_id is None` fallback inside the function — resolve it first, then use it as the cache key.

Both use the existing TTL from `QUERY_CACHE_TTL_SECONDS` (default 1 hour).

### Wrapping pattern (identical to existing cache usage)

```python
def get_upcoming_games(limit=10, league_ids=None, league_category=None, season_id=None):
    db = get_database_service()
    with db.session_scope() as session:
        if season_id is None:
            season_id = _get_current_season_id(session)

    key = ("upcoming_games", season_id, league_category, limit)
    cached = get_cached(key)
    if cached is not None:
        return cached

    # ... existing query logic unchanged ...

    set_cached(key, result)
    return result
```

The `session_scope` used to resolve `season_id` is a lightweight read — open it first, close it, then check the cache before opening the main query session. This avoids holding a session open during the cache check.

The same pattern applies to `get_latest_results`.

### Invalidation

Add two `invalidate_prefix` calls in two places in `data_indexer.py`:

**1. End of `index_games_for_league`** (line ~1688, after existing invalidations):
```python
invalidate_prefix("upcoming_games")
invalidate_prefix("latest_results")
```

**2. Before `return transitioned` in `index_upcoming_games`** (line ~3056):
```python
invalidate_prefix("upcoming_games")
invalidate_prefix("latest_results")
```

`index_games_for_league` is called when game scores are written (latest_results changes, upcoming games may move to results). `index_upcoming_games` is called when schedule changes are fetched (upcoming games dates/kickoff times change).

## Files Changed

| File | Change |
|---|---|
| `backend/app/services/stats_service.py` | Wrap `get_upcoming_games` and `get_latest_results` with cache |
| `backend/app/services/data_indexer.py` | Add 2+2 `invalidate_prefix` calls |

## Expected Outcome

- Home page warm hits: <200ms (down from 3–4s)
- All league-category filter variants cached separately
- Cache invalidated automatically after each games sync — data stays fresh within one sync cycle

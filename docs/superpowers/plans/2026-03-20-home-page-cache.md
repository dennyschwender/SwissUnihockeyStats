# Home Page Cache Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cache `get_upcoming_games` and `get_latest_results` in `stats_service.py` so the home page warm-hits drop from 3–4s to <200ms.

**Architecture:** Apply the existing `get_cached` / `set_cached` pattern (already imported in `stats_service.py`) to both functions. Resolve `season_id` first in a lightweight session, then check the cache before opening the main query session. Invalidate in `data_indexer.py` after the two syncs that change games data.

**Tech Stack:** Python, SQLAlchemy, existing `backend/app/services/cache.py` (TTL cache, thread-safe).

---

## File Map

| File | Action |
|---|---|
| `backend/app/services/stats_service.py` | Wrap `get_upcoming_games` and `get_latest_results` with cache |
| `backend/app/services/data_indexer.py` | Add `invalidate_prefix` calls after `index_games_for_league` and `index_upcoming_games` |

---

## Existing cache pattern to follow

`get_cached`, `set_cached`, `invalidate_prefix` are already imported at line 31 of `stats_service.py`:

```python
from app.services.cache import get_cached, set_cached
```

`invalidate_prefix` is already imported at line 33 of `data_indexer.py`:
```python
from app.services.cache import invalidate_prefix
```

Example of the existing pattern (from `get_league_standings`):
```python
key = ("standings", db_league_id, tuple(sorted(only_group_ids or [])))
cached = get_cached(key)
if cached is not None:
    return cached
# ... query ...
result = [...]
set_cached(key, result)
return result
```

---

## Task 1: Cache `get_upcoming_games` and `get_latest_results`

**Files:**
- Modify: `backend/app/services/stats_service.py`
- Modify: `backend/app/services/data_indexer.py`
- Test: `backend/tests/test_ttl_cache.py` (run existing tests to verify no regression)

### Context

**`get_upcoming_games`** starts at line 2139. The current structure is:

```python
def get_upcoming_games(limit=10, league_ids=None, league_category=None, season_id=None):
    from datetime import date as _date
    db = get_database_service()
    with db.session_scope() as session:
        if season_id is None:
            season_id = _get_current_season_id(session)
        today = _date.today()
        q = session.query(Game).filter(...)
        # ... league_category / league_ids filter ...
        games_raw = q.order_by(...).limit(limit).all()
        if not games_raw:
            return []
        # ... team names, group/league lookups, build result list ...
        return {"games": [...], "total": total}  # returns a dict
```

The function returns a **dict** (`{"games": [...], "total": total}`) not a list.

**`get_latest_results`** starts at line 2372. Same structure but:
- Filters `Game.home_score.isnot(None)` and `game_date <= today`
- Orders by `Game.game_date.desc()`
- Returns a **list** of dicts (not a dict wrapper)

Both functions currently do `season_id` resolution **inside** the single `session_scope`. The pattern requires resolving `season_id` first (so we know the cache key), then checking the cache before opening the main query session.

**Wrapping approach:** Split the season_id resolution into a short session, then check cache, then run the full query if cache miss.

### Step-by-step for `get_upcoming_games`

- [ ] **Step 1: Write the failing cache test**

Add to `backend/tests/test_ttl_cache.py`:

```python
class TestStatsCacheFunctions:
    """get_upcoming_games and get_latest_results use the TTL cache."""

    def test_get_upcoming_games_returns_cached_on_second_call(self, app):
        """Second call returns the cached result without hitting the DB again."""
        from app.services.stats_service import get_upcoming_games
        from app.services import cache as _cache

        # Prime cache with a fake entry for this key
        key = ("upcoming_games", 2025, None, 12)
        fake = {"games": [{"id": 999}], "total": 1}
        _cache.set_cached(key, fake)

        result = get_upcoming_games(limit=12, season_id=2025)
        assert result == fake

        # Cleanup
        _cache.invalidate_prefix("upcoming_games")

    def test_get_latest_results_returns_cached_on_second_call(self, app):
        """Second call returns the cached result without hitting the DB again."""
        from app.services.stats_service import get_latest_results
        from app.services import cache as _cache

        key = ("latest_results", 2025, None, 12)
        fake = [{"id": 888, "home_team": "A", "away_team": "B"}]
        _cache.set_cached(key, fake)

        result = get_latest_results(limit=12, season_id=2025)
        assert result == fake

        _cache.invalidate_prefix("latest_results")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/test_ttl_cache.py::TestStatsCacheFunctions -v
```

Expected: FAIL — functions don't check the cache yet so `fake` entries are ignored.

- [ ] **Step 3: Wrap `get_upcoming_games` with cache**

In `backend/app/services/stats_service.py`, modify `get_upcoming_games` (line 2139).

Change the opening of the function from:

```python
def get_upcoming_games(
    limit: int = 10,
    league_ids: Optional[list] = None,
    league_category: Optional[str] = None,
    season_id: Optional[int] = None,
) -> list[dict]:
    """
    Return next scheduled games (no score yet), ordered soonest first.

    Args:
        limit: Maximum number of games to return
        league_ids: Filter by league IDs (legacy parameter)
        league_category: Filter by league category (e.g., "2_11" for NLB Men)
        season_id: Season ID to filter by
    """
    from datetime import date as _date

    db = get_database_service()
    with db.session_scope() as session:
        if season_id is None:
            season_id = _get_current_season_id(session)

        today = _date.today()
        q = session.query(Game).filter(
```

To:

```python
def get_upcoming_games(
    limit: int = 10,
    league_ids: Optional[list] = None,
    league_category: Optional[str] = None,
    season_id: Optional[int] = None,
) -> list[dict]:
    """
    Return next scheduled games (no score yet), ordered soonest first.

    Args:
        limit: Maximum number of games to return
        league_ids: Filter by league IDs (legacy parameter)
        league_category: Filter by league category (e.g., "2_11" for NLB Men)
        season_id: Season ID to filter by
    """
    from datetime import date as _date

    db = get_database_service()
    if season_id is None:
        with db.session_scope() as session:
            season_id = _get_current_season_id(session)

    key = ("upcoming_games", season_id, league_category, limit)
    cached = get_cached(key)
    if cached is not None:
        return cached

    with db.session_scope() as session:
        today = _date.today()
        q = session.query(Game).filter(
```

Then at the very end of the function, just before `return {"games": [...], "total": total}` — find the final return statement and wrap it:

```python
        result = {"games": [...], "total": total}
        set_cached(key, result)
        return result
```

**Important:** The existing return statement builds the result inline like:
```python
        return {
            "games": [
                {...}
                for g in games_raw
            ],
            "total": total,
        }
```

Replace this with:
```python
        result = {
            "games": [
                {...}
                for g in games_raw
            ],
            "total": total,
        }
        set_cached(key, result)
        return result
```

Also wrap the `if not games_raw: return []` early-return around line 2192. The existing code returns `[]` when empty — preserve that behavior:
```python
        if not games_raw:
            set_cached(key, [])
            return []
```

- [ ] **Step 4: Wrap `get_latest_results` with cache**

Same pattern. In `backend/app/services/stats_service.py`, modify `get_latest_results` (line 2372):

Change opening:
```python
    db = get_database_service()
    with db.session_scope() as session:
        if season_id is None:
            season_id = _get_current_season_id(session)

        today = _date.today()
        q = session.query(Game).filter(
```

To:
```python
    db = get_database_service()
    if season_id is None:
        with db.session_scope() as session:
            season_id = _get_current_season_id(session)

    key = ("latest_results", season_id, league_category, limit)
    cached = get_cached(key)
    if cached is not None:
        return cached

    with db.session_scope() as session:
        today = _date.today()
        q = session.query(Game).filter(
```

At the end, before the final return (the list comprehension around line 2480):
```python
        result = [
            {...}
            for g in games_raw
        ]
        set_cached(key, result)
        return result
```

Also wrap the empty early-return:
```python
        if not games_raw:
            set_cached(key, [])
            return []
```

- [ ] **Step 5: Run the cache tests to verify they pass**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/test_ttl_cache.py::TestStatsCacheFunctions -v
```

Expected: both PASS.

- [ ] **Step 6: Add invalidation to `data_indexer.py`**

**Location 1:** End of `index_games_for_league`, after existing invalidations at line ~1688:

```python
            invalidate_prefix("standings")
            invalidate_prefix("league_scorers")
            invalidate_prefix("league_penalties")
            invalidate_prefix("upcoming_games")   # ADD
            invalidate_prefix("latest_results")   # ADD
            return count
```

**Location 2:** Before `return transitioned` in `index_upcoming_games` (line ~3056):

```python
        logger.info(
            "[upcoming_games] season=%s refreshed=%d games, transitioned=%d to post_game",
            season_id,
            games_refreshed,
            transitioned,
        )
        invalidate_prefix("upcoming_games")   # ADD
        invalidate_prefix("latest_results")   # ADD
        return transitioned
```

- [ ] **Step 7: Run full test suite**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest --tb=short -q
```

Expected: all tests pass (same count as before, no new failures).

- [ ] **Step 8: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add backend/app/services/stats_service.py backend/app/services/data_indexer.py backend/tests/test_ttl_cache.py
git commit -m "perf: cache get_upcoming_games and get_latest_results — home page warm hits <200ms"
```

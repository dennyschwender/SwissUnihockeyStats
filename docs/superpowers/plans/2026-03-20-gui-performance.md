# GUI Performance Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut home page and league detail page load times from 3–5s to <200ms on warm cache and ~1s on cold load.

**Architecture:** Three independent improvements: (1) fix N+1 query in `get_overall_top_scorers`, (2) add `joinedload` for `League.groups` in three functions, (3) new `services/cache.py` TTL cache wrapping the four most expensive query functions with invalidation hooks in `data_indexer.py`. Also adds two composite DB indexes.

**Tech Stack:** Python, SQLAlchemy (ORM queries), SQLite (WAL mode), threading.Lock for cache thread-safety, pytest.

**Spec:** `docs/superpowers/specs/2026-03-20-gui-performance-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/app/services/cache.py` | **Create** | TTL cache module (get/set/invalidate, threading.Lock) |
| `backend/tests/test_cache.py` | **Create** | Unit tests for cache module |
| `backend/app/services/stats_service.py` | **Modify** | Fix N+1 (~line 1193), add joinedload (~lines 442, 637, 976), wrap 4 functions with cache |
| `backend/app/models/db_models.py` | **Modify** | Add 2 new composite indexes to PlayerStatistics.__table_args__ |
| `backend/app/services/database.py` | **Modify** | Add idempotent CREATE INDEX migrations for the 2 new indexes |
| `backend/app/services/data_indexer.py` | **Modify** | Call `invalidate_prefix()` after `index_games_for_league` and `index_player_stats_for_season` |

---

## Task 1: Create `services/cache.py` TTL cache module

**Files:**
- Create: `backend/app/services/cache.py`
- Create: `backend/tests/test_cache.py`

- [ ] **Step 1: Write failing tests for the cache module**

Create `backend/tests/test_cache.py`:

```python
"""Tests for the in-memory TTL cache module."""
import threading
import time
import pytest
from unittest.mock import patch

from app.services.cache import get_cached, set_cached, invalidate_prefix, _cache, _lock


def _clear_cache():
    """Helper: clear all cache entries between tests."""
    with _lock:
        _cache.clear()


def test_set_and_get_returns_value():
    _clear_cache()
    set_cached(("standings", 1, 2025), {"data": "result"})
    result = get_cached(("standings", 1, 2025))
    assert result == {"data": "result"}


def test_get_returns_none_for_missing_key():
    _clear_cache()
    assert get_cached(("standings", 999, 2025)) is None


def test_get_returns_none_after_ttl_expiry():
    _clear_cache()
    with patch("app.services.cache._TTL", 0.05):  # 50ms TTL for test
        set_cached(("top_scorers", None, 20), [1, 2, 3])
        time.sleep(0.1)
        assert get_cached(("top_scorers", None, 20)) is None


def test_get_returns_value_within_ttl():
    _clear_cache()
    with patch("app.services.cache._TTL", 60):
        set_cached(("top_scorers", None, 20), [1, 2, 3])
        assert get_cached(("top_scorers", None, 20)) == [1, 2, 3]


def test_invalidate_prefix_removes_matching_keys():
    _clear_cache()
    set_cached(("standings", 1, 2025), "a")
    set_cached(("standings", 2, 2025), "b")
    set_cached(("league_scorers", 1, 2025), "c")
    invalidate_prefix("standings")
    assert get_cached(("standings", 1, 2025)) is None
    assert get_cached(("standings", 2, 2025)) is None
    assert get_cached(("league_scorers", 1, 2025)) == "c"


def test_invalidate_prefix_leaves_unrelated_keys():
    _clear_cache()
    set_cached(("top_scorers", None, 20), [1])
    set_cached(("standings", 1, 2025), "a")
    invalidate_prefix("standings")
    assert get_cached(("top_scorers", None, 20)) == [1]


def test_cache_key_with_tuple_arg():
    """Cache key containing a tuple (e.g. only_group_ids) works correctly."""
    _clear_cache()
    key_a = ("standings", 1, 2025, (1, 2))
    key_b = ("standings", 1, 2025, (2, 1))  # different order = different key
    set_cached(key_a, "result_a")
    assert get_cached(key_a) == "result_a"
    assert get_cached(key_b) is None


def test_thread_safety_concurrent_set_and_invalidate():
    """Concurrent set from one thread and invalidate from another must not raise."""
    _clear_cache()
    errors = []

    def writer():
        for i in range(50):
            try:
                set_cached(("standings", i, 2025), f"data_{i}")
            except Exception as e:
                errors.append(e)

    def invalidator():
        for _ in range(10):
            try:
                invalidate_prefix("standings")
            except Exception as e:
                errors.append(e)

    t1 = threading.Thread(target=writer)
    t2 = threading.Thread(target=invalidator)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert errors == [], f"Thread safety errors: {errors}"
```

- [ ] **Step 2: Run tests — verify they all fail (module does not exist)**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/test_cache.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'app.services.cache'`

- [ ] **Step 3: Create `backend/app/services/cache.py`**

```python
"""
In-memory TTL cache for expensive DB query results.

Thread-safe: all operations hold _lock. Scheduler worker threads call
invalidate_prefix() while FastAPI route handlers call get/set from the
asyncio event loop.

TTL is configured via QUERY_CACHE_TTL_SECONDS env var (default: 3600s / 1 hour).
Data only changes during sync jobs so 1-hour staleness is acceptable.
"""
import os
import threading
import time
from typing import Any

_TTL: float = float(os.environ.get("QUERY_CACHE_TTL_SECONDS", "3600"))
_lock = threading.Lock()
_cache: dict[tuple, tuple[Any, float]] = {}  # key → (value, stored_at)


def get_cached(key: tuple) -> Any | None:
    """Return cached value if present and not expired, else None."""
    with _lock:
        entry = _cache.get(key)
    if entry is None:
        return None
    value, stored_at = entry
    if time.monotonic() - stored_at > _TTL:
        return None
    return value


def set_cached(key: tuple, value: Any) -> None:
    """Store value in cache with current timestamp."""
    with _lock:
        _cache[key] = (value, time.monotonic())


def invalidate_prefix(prefix: str) -> None:
    """Remove all cache entries whose key starts with prefix."""
    with _lock:
        keys_to_remove = [k for k in _cache if k[0] == prefix]
        for k in keys_to_remove:
            del _cache[k]
```

- [ ] **Step 4: Run tests — all should pass**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/test_cache.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add backend/app/services/cache.py backend/tests/test_cache.py
git commit -m "feat(perf): add in-memory TTL cache module with thread safety"
```

---

## Task 2: Fix N+1 in `get_overall_top_scorers`

**Files:**
- Modify: `backend/app/services/stats_service.py:1131-1231`

- [ ] **Step 1: Read the current function**

Read lines 1131–1231 of `backend/app/services/stats_service.py` to understand the exact structure before editing.

- [ ] **Step 2: Replace the N+1 inner loop with a batch query**

The existing loop (lines 1193–1231) fires one `session.query(PlayerStatistics)` per player. Replace it with a batch fetch.

The existing result dict uses these exact keys (preserve them):
`rank`, `player_id`, `player_name`, `team_name`, `team_id`, `league`, `gender`, `gp`, `g`, `a`, `pts`, `pim`.
`gender` is looked up from `team_gender` (a dict already built earlier in the function, mapping team_name → "M"/"W").
`league` maps to `PlayerStatistics.league_abbrev`.

Replace lines 1192–1231 (the `result = []` + loop + `return result`) with:

```python
        # Batch-fetch primary team for all players in one query (replaces N+1 loop)
        player_ids = [row[0] for row in stats]
        all_ps_rows = (
            session.query(
                PlayerStatistics.player_id,
                PlayerStatistics.team_name,
                PlayerStatistics.team_id,
                PlayerStatistics.league_abbrev,
                PlayerStatistics.games_played,
            )
            .filter(
                PlayerStatistics.player_id.in_(player_ids),
                PlayerStatistics.season_id == season_id,
            )
            .all()
        )
        # Build lookup: player_id → row with highest games_played
        ps_by_player: dict[int, Any] = {}
        for ps_row in all_ps_rows:
            pid = ps_row[0]
            if pid not in ps_by_player or ps_row[4] > ps_by_player[pid][4]:
                ps_by_player[pid] = ps_row

        result = []
        for i, (player_id, full_name, gp, g, a, pts, pim) in enumerate(stats, 1):
            primary = ps_by_player.get(player_id)
            team_name = primary[1] if primary else "Unknown"
            team_id = primary[2] if primary else None
            league_abbrev = primary[3] if primary else None
            result.append(
                {
                    "rank": i,
                    "player_id": player_id,
                    "player_name": full_name or f"Player {player_id}",
                    "team_name": team_name or "Unknown",
                    "team_id": team_id,
                    "league": league_abbrev or "",
                    "gender": team_gender.get(team_name or "", ""),
                    "gp": gp or 0,
                    "g": g or 0,
                    "a": a or 0,
                    "pts": pts or 0,
                    "pim": pim or 0,
                }
            )

        return result
```

- [ ] **Step 3: Run the existing test suite to verify no regressions**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/ -v -x 2>&1 | tail -20
```

Expected: all previously-passing tests still pass. If any test references `get_overall_top_scorers`, check it passes.

- [ ] **Step 4: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add backend/app/services/stats_service.py
git commit -m "fix(perf): batch primary-team lookup in get_overall_top_scorers (21 queries → 2)"
```

---

## Task 3: Add `joinedload(League.groups)` to three functions

**Files:**
- Modify: `backend/app/services/stats_service.py` (lines ~421–442, ~612–637, ~960–976)

`joinedload` is already imported from `sqlalchemy.orm` (check imports at top; if not present, add it).

- [ ] **Step 1: Check joinedload import**

Search the top of `stats_service.py` for `joinedload`. If it's not imported, add it:

```python
from sqlalchemy.orm import joinedload
```

Add after the existing `from sqlalchemy import ...` line.

- [ ] **Step 2: Fix `get_league_standings` (~line 430)**

Find where `league` is queried in this function. It will look something like:

```python
league = session.query(League).filter(League.id == db_league_id).first()
```

Replace with:

```python
league = (
    session.query(League)
    .options(joinedload(League.groups))
    .filter(League.id == db_league_id)
    .first()
)
```

- [ ] **Step 3: Fix `get_league_top_scorers` (~line 625)**

Same pattern — find the `session.query(League)` call and add `.options(joinedload(League.groups))`.

- [ ] **Step 4: Fix `get_league_top_penalties` (~line 965)**

Same pattern.

- [ ] **Step 5: Run tests**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/ -v -x 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add backend/app/services/stats_service.py
git commit -m "fix(perf): eager-load League.groups in standings and top-scorer queries"
```

---

## Task 4: Add composite DB indexes to PlayerStatistics

**Files:**
- Modify: `backend/app/models/db_models.py` (PlayerStatistics `__table_args__`)
- Modify: `backend/app/services/database.py` (idempotent migrations)

- [ ] **Step 1: Add indexes to the model**

In `backend/app/models/db_models.py`, find `PlayerStatistics.__table_args__` (currently ends around line 474). Add two new indexes:

```python
    __table_args__ = (
        ForeignKeyConstraint(["team_id", "season_id"], ["teams.id", "teams.season_id"]),
        Index("idx_stats_player", "player_id"),
        Index("idx_stats_season", "season_id"),
        Index("idx_stats_unique", "player_id", "season_id", "league_abbrev", unique=True),
        # New: for league-level top-scorer queries (filter by season+league, sort by points)
        Index("idx_stats_season_league_points", "season_id", "league_abbrev", "points"),
        # New: for overall top-scorers aggregation (group by player within season)
        Index("idx_stats_season_player", "season_id", "player_id"),
    )
```

- [ ] **Step 2: Add idempotent migrations in `database.py`**

In `backend/app/services/database.py`, find where existing index migrations are done (look for `CREATE INDEX IF NOT EXISTS` or similar). If none exist for indexes (only column migrations exist), add a new block. The pattern uses `CREATE INDEX IF NOT EXISTS` which is natively idempotent in SQLite:

Find the `_run_migrations` method (or equivalent) and add after the existing migration blocks:

```python
        # ── New composite indexes on player_statistics (idempotent) ─────────
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_stats_season_league_points "
            "ON player_statistics (season_id, league_abbrev, points)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_stats_season_player "
            "ON player_statistics (season_id, player_id)"
        ))
```

- [ ] **Step 3: Run tests**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/ -v -x 2>&1 | tail -20
```

Expected: all tests pass. The `:memory:` SQLite in tests will also create these indexes on startup.

- [ ] **Step 4: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add backend/app/models/db_models.py backend/app/services/database.py
git commit -m "feat(perf): add composite indexes on player_statistics for scorer/standings queries"
```

---

## Task 5: Wrap the four expensive functions with the TTL cache

**Files:**
- Modify: `backend/app/services/stats_service.py`

All four functions are in `stats_service.py`. The cache import goes at the top; each function gets a cache check at the start and a `set_cached` call before returning.

- [ ] **Step 1: Add cache import to `stats_service.py`**

At the top of `stats_service.py`, after the existing imports, add:

```python
from app.services.cache import get_cached, set_cached
```

- [ ] **Step 2: Wrap `get_overall_top_scorers` (lines ~1131)**

Find the function. After the `def` line and any docstring, insert cache get/set:

```python
def get_overall_top_scorers(season_id: Optional[int] = None, limit: int = 20) -> list[dict]:
    cache_key = ("top_scorers", season_id, limit)
    cached = get_cached(cache_key)
    if cached is not None:
        return cached
    # ... existing function body ...
    # Before the final return:
    set_cached(cache_key, results)
    return results
```

- [ ] **Step 3: Wrap `get_league_standings` (lines ~421)**

```python
def get_league_standings(db_league_id: int, only_group_ids: list[int] | None = None) -> list[dict]:
    cache_key = ("standings", db_league_id, tuple(sorted(only_group_ids or [])))
    cached = get_cached(cache_key)
    if cached is not None:
        return cached
    # ... existing function body ...
    # Before the final return:
    set_cached(cache_key, results)
    return results
```

Note: `get_league_standings` has no `season_id` parameter — the `db_league_id` is the League table primary key which already scopes to one season (each season has its own League rows). The `only_group_ids` list is normalised to `tuple(sorted(...))` so call order doesn't matter.

- [ ] **Step 4: Wrap `get_league_top_scorers` (lines ~612)**

Note: the spec's cache key table incorrectly lists `season_id` as a parameter for this function — it does not exist in the actual signature. The correct cache key uses only `db_league_id` and `limit`. The league's DB primary key already encodes the season.

```python
def get_league_top_scorers(db_league_id: int, limit: int = 20) -> list[dict]:
    cache_key = ("league_scorers", db_league_id, limit)
    cached = get_cached(cache_key)
    if cached is not None:
        return cached
    # ... existing function body ...
    set_cached(cache_key, results)
    return results
```

- [ ] **Step 5: Wrap `get_league_top_penalties` (lines ~960)**

Note: same situation as `get_league_top_scorers` — no `season_id` param; cache key uses only `db_league_id` and `limit`.

```python
def get_league_top_penalties(db_league_id: int, limit: int = 100) -> list[dict]:
    cache_key = ("league_penalties", db_league_id, limit)
    cached = get_cached(cache_key)
    if cached is not None:
        return cached
    # ... existing function body ...
    set_cached(cache_key, results)
    return results
```

- [ ] **Step 6: Run tests**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/ -v -x 2>&1 | tail -20
```

Expected: all tests pass. The cache will be populated during test runs but TTL is irrelevant since tests complete fast.

- [ ] **Step 7: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add backend/app/services/stats_service.py
git commit -m "feat(perf): wrap expensive stats queries with 1h TTL in-memory cache"
```

---

## Task 6: Add cache invalidation in `data_indexer.py`

**Files:**
- Modify: `backend/app/services/data_indexer.py`

When sync jobs complete, the TTL cache should be invalidated so stale data is not served for the full hour. Two insertion points.

- [ ] **Step 1: Add cache import to `data_indexer.py`**

At the top of `data_indexer.py`, after the existing imports, add:

```python
from app.services.cache import invalidate_prefix
```

- [ ] **Step 2: Invalidate after `index_games_for_league` completes**

Find the end of `index_games_for_league` in `data_indexer.py` (around line 1684). Before `return count`, add:

```python
        # Invalidate cached standings/scorers for this league so stale data is not served
        invalidate_prefix("standings")
        invalidate_prefix("league_scorers")
        invalidate_prefix("league_penalties")
        return count
```

Note: we invalidate all standings/scorers (not just this league_id) since the cache is small and this is simpler and safer.

- [ ] **Step 3: Invalidate after `index_player_stats_for_season` completes**

Find the end of `index_player_stats_for_season` (around line 1238). Before the final `return`, add:

```python
        # Invalidate cached overall top scorers for this season
        invalidate_prefix("top_scorers")
```

- [ ] **Step 4: Run tests**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/ -v -x 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add backend/app/services/data_indexer.py
git commit -m "feat(perf): invalidate query cache after game and player stats syncs"
```

---

## Task 7: Verify end-to-end and run full test suite

- [ ] **Step 1: Run full test suite with coverage**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/ --cov=app --cov-report=term-missing 2>&1 | tail -40
```

Expected: all tests pass, no regressions.

- [ ] **Step 2: Lint**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/flake8 app/services/cache.py app/services/stats_service.py app/services/data_indexer.py app/models/db_models.py --max-line-length=120
```

Expected: no errors.

- [ ] **Step 3: Final commit if any lint fixes were needed**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add backend/app/services/cache.py backend/app/services/stats_service.py backend/app/services/data_indexer.py backend/app/models/db_models.py backend/app/services/database.py
git commit -m "fix(perf): lint fixes"
```

---

## Summary

| Task | Queries saved | Impact |
|------|--------------|--------|
| Fix N+1 in top_scorers | 19 queries per home load | High |
| joinedload League.groups | N queries → 1 per function | Medium |
| Composite indexes | Faster sort/filter on PlayerStatistics | Medium |
| TTL cache (4 functions) | 0 queries on warm hit | Very High |
| Cache invalidation | Fresh data after sync | Correctness |

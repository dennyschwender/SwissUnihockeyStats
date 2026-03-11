# Indexer Performance Improvements — Design Spec

**Date:** 2026-03-11
**Status:** Approved

---

## Problem

All indexing jobs are I/O-bound on the Swiss Unihockey API (~20s/call for player endpoints). Three specific issues:

1. **`player_game_stats` max_workers is hardcoded at 5** and is never passed from `_run()` to the indexer. The parameter exists on the function signature but is ignored at call time. With T3 having 7,403 players at ~20s/call, Phase 1 takes ~8 hours at 5 workers.

2. **`_GAMES_BATCH = 2` and `_EV_BATCH = 2`** in `main.py` are conservative constants that limit games and lineup indexing to 2 concurrent requests at a time. Both can be safely raised.

3. **`index_player_stats_for_season` is fully serial** — it iterates 1,000+ players one at a time inside a single open `session_scope()`, calling the API for each. This is the exact anti-pattern that caused DB lock cascades in player_game_stats. It's not causing problems now because runs return 0 (already synced), but will become a multi-hour freeze on first full sync.

---

## Design

### Change 1: Configurable `max_workers` for player_game_stats

**Files:** `scheduler.py`, `main.py`, admin HTML template

**Config key:** `player_game_stats_workers` in `scheduler_config.json` (default `10`)

**Flow:**
- `scheduler.py` `_load_state()`: read `player_game_stats_workers` into `self._player_game_stats_workers` (int, min 1, default 10)
- `scheduler.py` `_save_state()`: persist it back to JSON alongside existing fields
- `scheduler.py`: add `set_player_game_stats_workers(n: int)` method (mirrors `set_max_concurrent`)
- `main.py` `admin_scheduler_control()`: add `action == "player_game_stats_workers"` branch calling the new setter
- `main.py` `_run()` (lines ~1918-1932): pass `max_workers=sched._player_game_stats_workers` to `index_player_game_stats_for_season()`
- Admin UI (`templates/admin/scheduler.html` or equivalent): add a number input for this setting, wired to the same scheduler control endpoint

**Expected speedup:** Phase 1 halved (8h→4h for T3) at default 10 workers.

---

### Change 2: Increase batch constants

**File:** `main.py`

| Constant | Old | New | Rationale |
|---|---|---|---|
| `_GAMES_BATCH` | 2 | 4 | Games API is moderately fast; 4 concurrent groups is safe |
| `_EV_BATCH` | 2 | 6 | Lineup API is fast (~0.65s/call); 6 concurrent games fine |

One-line changes each. No structural impact.

---

### Change 3: `index_player_stats_for_season` Phase 1/2 refactor

**File:** `data_indexer.py`

Apply the same two-phase pattern already used by `index_player_game_stats_for_season`:

**Phase 1 (new):** Fetch all player stats in parallel using `ThreadPoolExecutor(max_workers=5)`. No session open during fetches. Collect `_PlayerStatsFetchResult` objects.

**Phase 2 (new):** Write all results in batches of `_PLAYER_STATS_PHASE2_BATCH_SIZE = 300`. Each batch in its own `session_scope()`. Per-player SyncStatus marks after each batch (checkpoint resume).

**Checkpoint resume (new):** Before Phase 1, call `bulk_already_indexed("player_stats", [f"player_stats:{pid}:{season}" for pid in player_ids], max_age_hours=24)` to skip already-synced players. Matches the pattern in `player_game_stats`.

**New dataclass:**
```python
@dataclass
class _PlayerStatsFetchResult:
    player_id: int
    stats: dict = field(default_factory=dict)  # league_id -> {goals, assists, ...}
    api_error: bool = False
```

**SyncStatus entity:** `entity_type="player_stats"`, `entity_id=f"player_stats:{pid}:{season_id}"`

The existing top-level SyncStatus for the season/tier is stamped after all batches complete (identical to player_game_stats behavior).

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/services/scheduler.py` | `_load_state`, `_save_state`, new `set_player_game_stats_workers()` |
| `backend/app/main.py` | `admin_scheduler_control()`, `_run()`, `_GAMES_BATCH`, `_EV_BATCH` |
| `backend/app/services/data_indexer.py` | `index_player_stats_for_season` refactor + `_PlayerStatsFetchResult` |
| `backend/templates/admin/...` | Add `player_game_stats_workers` input to scheduler settings |
| `backend/tests/` | Tests for new config endpoint + player_stats Phase 1/2 |

---

## Verification

1. Set `player_game_stats_workers=10` via admin panel → confirm `scheduler_config.json` persists it
2. Trigger player_game_stats manually → confirm logs show 10 workers (not 5)
3. Confirm games job processes 4 groups in parallel instead of 2
4. Confirm lineups job processes 6 games in parallel instead of 2
5. Trigger player_stats → confirm logs show parallel fetches (not 1-by-1 serial)
6. Simulate Phase 2 failure mid-run → restart → confirm Phase 1 skips already-synced players
7. `pytest` — all existing tests pass + new tests green

# Season Freeze: Auto-Detection + Admin UI

**Date:** 2026-03-20
**Status:** Approved
**Priority:** High — scheduler runs jobs all day because past seasons never settle as "done"

## Problem

The scheduler re-queues jobs for both past and current seasons continuously. Past season syncs fail partway (API errors, partial data), so `last_sync` never gets set, the freeze logic never triggers, and the scheduler retries forever — consuming CPU all day. There is no way to explicitly mark a season as "done forever" or to see completion status in the admin dashboard.

## Approach: `is_frozen` Flag + Auto-Detection + Admin UI

Add `is_frozen` to the `Season` model. The scheduler skips all jobs for frozen seasons. Auto-freeze triggers when all games are finished and no syncs are in-progress. The admin dashboard shows completeness per season with manual freeze/unfreeze controls.

## Design

### Part 1: Data Model

Add one column to `Season` in `backend/app/models/db_models.py`:

```python
is_frozen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")
```

Add idempotent migration in `backend/app/services/database.py` (same pattern as existing column migrations):

```python
if "is_frozen" not in existing_cols:
    conn.execute(text("ALTER TABLE seasons ADD COLUMN is_frozen INTEGER NOT NULL DEFAULT 0"))
```

### Part 2: Completeness Check

A season is **complete** when:
1. It has at least one game (`Game.season_id == season_id`, count > 0)
2. All games are finished (`Game.status != 'finished'`, count == 0)
3. No syncs are actively in-progress for this season (`SyncStatus.entity_id LIKE '%:{season_id}%' AND sync_status == 'in_progress'`, count == 0)

Note: `SyncStatus` has no `season_id` FK — uses string `entity_id` like `"season:2025"`. The trailing-anchor LIKE pattern (`%:{season_id}`) prevents false matches (e.g. season_id=2 matching "2024"). The LIKE guard prevents freezing a season while a sync is actively running.

**Known limitation:** Games that are permanently stuck at `status='scheduled'` (e.g. cancelled games the API never updates) will block auto-freeze. In that case the admin can use the manual Freeze button in the dashboard.

Helper function `_is_season_complete(session, season_id: int) -> bool` in `scheduler.py`:

```python
def _is_season_complete(session, season_id: int) -> bool:
    total = session.query(func.count(Game.id)).filter(Game.season_id == season_id).scalar()
    if not total:
        return False
    unfinished = session.query(func.count(Game.id)).filter(
        Game.season_id == season_id, Game.status != "finished"
    ).scalar()
    in_progress = session.query(SyncStatus).filter(
        SyncStatus.entity_id.like(f"%:{season_id}"),  # trailing anchor — avoids matching "2025" inside "2025123"
        SyncStatus.sync_status == "in_progress",
    ).count()
    return unfinished == 0 and in_progress == 0
```

### Part 3: Scheduler Changes

**`backend/app/services/scheduler.py`**

**Change 1 — Skip frozen seasons in `_maybe_schedule()`:**

At the very top of `_maybe_schedule()`, before any other logic:

```python
if season is not None:
    frozen = session.query(Season.is_frozen).filter(Season.id == season).scalar()
    if frozen:
        return  # season is frozen — skip entirely
```

**Change 2 — Auto-freeze after `refresh_queue()` completes:**

After the policy-iteration session_scope closes, open a **separate** `session_scope()` for the auto-freeze writes. This avoids holding a write lock open during the async yields in the policy loop:

```python
# Separate session_scope — do NOT nest inside the policy-iteration session
with db_service.session_scope() as session:
    past_seasons = session.query(Season).filter(
        Season.highlighted == False, Season.is_frozen == False
    ).all()
    for season in past_seasons:
        if _is_season_complete(session, season.id):
            season.is_frozen = True
            logger.info("Season %s auto-frozen (all games finished, no active syncs)", season.id)
    # session_scope commits on exit — do NOT add session.commit() here
```

**Important:** Never add a manual `session.commit()` inside this block — `session_scope()` commits on exit. Exceptions propagate outside the `with` block per the session_scope contract.

This runs once per tick. Once a season is frozen, it is excluded by the `is_frozen == False` filter and never checked again. Cost: 3 COUNT queries per non-frozen past season per tick — negligible.

### Part 4: Admin API Endpoints

**New endpoints in `backend/app/main.py`:**

`GET /admin/api/seasons/completeness`

Returns list of all seasons with completeness data:
```json
[
  {
    "season_id": 2024,
    "text": "2024/25",
    "is_current": false,
    "is_frozen": true,
    "games_total": 94,
    "games_finished": 94,
    "games_pct": 100,
    "is_complete": true
  }
]
```

`POST /admin/api/season/{season_id}/freeze` — set `is_frozen = True`

`POST /admin/api/season/{season_id}/unfreeze` — set `is_frozen = False`

Both return `{"ok": true, "season_id": ..., "is_frozen": ...}`.

### Part 5: Admin UI

In the existing seasons admin page (`backend/templates/admin/seasons.html` or equivalent), add a completeness column to the season list table:

- **Games**: `94/94` (or `87/94` if incomplete) with a ✓ when 100%
- **Status**: `Frozen` badge (grey) if `is_frozen`, `Complete` badge (green) if `is_complete` but not frozen, blank otherwise
- **Action**: "Freeze" button (if not frozen and is_complete) or "Unfreeze" button (if frozen)

Completeness data loaded once on page load from `GET /admin/api/seasons/completeness`. Freeze/Unfreeze buttons POST to the respective endpoint and refresh the row via HTMX or page reload.

## Out of Scope

- Adding `season_id` FK to `SyncStatus` (separate improvement)
- Freeze based on SyncStatus completeness (no clean way to scope SyncStatus by season without FK)
- Per-entity-type completeness breakdown in admin UI
- Email/notification when a season auto-freezes

## Files Changed

| File | Change |
|------|--------|
| `backend/app/models/db_models.py` | Add `is_frozen` to `Season` |
| `backend/app/services/database.py` | Add idempotent migration for `is_frozen` column |
| `backend/app/services/scheduler.py` | Add `_is_season_complete()`, skip frozen in `_maybe_schedule()`, auto-freeze in `refresh_queue()` |
| `backend/app/main.py` | Add 3 new admin API endpoints |
| `backend/templates/admin/` | Add completeness column + freeze/unfreeze buttons to seasons page |
| `backend/tests/test_scheduler.py` | Tests for freeze skip and auto-freeze logic |
| `backend/tests/test_season_freeze.py` | Tests for completeness check and admin endpoints |

## Expected Outcome

- Past seasons with all games finished auto-freeze within one scheduler tick (≤5 minutes)
- Frozen seasons cost zero scheduler work — no DB queries, no API calls
- Admin can see completion status for every season at a glance
- Admin can manually freeze/unfreeze any season as override
- Nightly indexing load drops dramatically once historical seasons are frozen

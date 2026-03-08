# DB Repair Service — Design

**Date**: 2026-03-08
**Status**: Approved

## Problem

The indexing pipeline has several classes of persistent failures that the normal
scheduler cannot self-heal:

| Class | Root Cause |
|---|---|
| `game_date IS NULL` | Playoff date formats missed by parser; backfill needs re-index |
| Finished games with zero events | Events job never ran, TTL skipped, or first attempt failed |
| `game.period IS NULL` | OT/SO not detected; fixable from existing event rows |
| Stuck `in_progress` sync_status | Crashed workers leave rows locked indefinitely |
| Stale `failed` sync_status | Failed rows block retry for up to 7 days |
| Missing lineup (GamePlayer) | Events indexed but game_summary lineup absent |
| Roster gaps (TeamPlayer) | Players in game lineups never added to team roster |
| Unresolved player stats | `team_id`/`game_class` NULL in `player_statistics` |

## Solution

A dedicated `RepairService` that runs nightly, applies conservative DB-only fixes,
and surfaces a report of suspicious games on the admin dashboard.

---

## Architecture

### 1. `app/services/repair_service.py` (new file)

**Conservative repair methods** (modify DB / queue re-indexing):

| Method | Action |
|---|---|
| `fix_stuck_in_progress()` | Reset `sync_status='in_progress'` rows older than 2h to `NULL` (delete row) so scheduler re-queues |
| `fix_null_game_dates()` | Delete `game_events` sync_status rows for finished games with `game_date IS NULL` — forces event indexer to re-run and backfill date from detail API |
| `fix_missing_events()` | Delete `game_events` sync_status rows for finished games with `home_score IS NOT NULL` and zero `game_events` rows — forces re-index |
| `fix_null_period_from_events()` | Pure SQL: set `period='OT'` where events contain a goal at time ≥ `61:00`; set `period='SO'` where a `Penaltyschiessen` event exists |
| `fix_stale_failed_rows()` | Delete `sync_status` rows with `status='failed'` and `last_sync < now()-7d` for `entity_type='game_events'` |

All repair methods are idempotent and operate only on the local DB (no API calls).
Re-indexing is delegated to the existing event indexer via sync_status deletion.

**Report query methods** (read-only):

| Method | What it returns |
|---|---|
| `report_games_no_lineup()` | Finished games that have events but zero `game_players` rows |
| `report_roster_gaps()` | Teams where `game_players` count > `team_players` count |
| `report_unresolved_stats()` | `player_statistics` rows with `team_id IS NULL OR game_class IS NULL` |

**Entry point:**

```python
def run_nightly(self) -> dict:
    """Run all conservative fixes. Returns summary dict with row counts."""
```

Returns a dict like:
```python
{
    "stuck_in_progress": 2,
    "null_game_dates": 5,
    "missing_events": 12,
    "null_period_fixed": 8,
    "stale_failed": 3,
    "total_fixed": 30
}
```

---

### 2. Scheduler Integration (`app/services/scheduler.py`)

Add a new policy to `POLICIES`:

```python
{
    "entity_type": "repair",
    "entity_id": "all",
    "task": "repair",
    "max_age_hours": 24,
    "run_after_utc": 3,      # 03:30 UTC — after nightly indexing jobs
    "run_after_minute": 30,
    "current_only": False,   # runs regardless of season
    "scope": "global",
}
```

The scheduler's `_dispatch()` gets a new branch for `task='repair'` that:
1. Calls `repair_service.run_nightly()`
2. Writes a `sync_status` row (`entity_type='repair'`, `entity_id='all'`,
   `records_synced=total_fixed`, `status='completed'`)

---

### 3. CLI (`manage.py repair` command)

New command `repair`:
- Instantiates `RepairService`
- Calls `run_nightly()`
- Prints a table of rows fixed per category
- Prints counts from the three report queries

Usage:
```
python manage.py repair
```

---

### 4. Admin Dashboard

New **"DB Health"** section on the existing admin page, below current stats.

**Subsection A — Last repair run**
Reads the `sync_status` row for `entity_type='repair'`. Shows:
- Last run timestamp
- Total rows fixed
- "Run repair now" button → POST `/api/v1/admin/repair` → triggers `run_nightly()` inline

**Subsection B — Suspicious games** (computed live on page load)
Three collapsible tables:

1. **Missing lineup** — finished games with events but zero `game_players` rows
   - Columns: game id (linked to detail page), date, home team, away team, event count
2. **Roster gaps** — teams where game players outnumber roster entries
   - Columns: team name, season, game players count, roster count, delta
3. **Unresolved player stats** — `player_statistics` with null `team_id` or `game_class`
   - Columns: player name, team_name, league_abbrev, season

---

## Data Flow

```
Nightly (03:30 UTC)
  scheduler._dispatch("repair")
    └─ RepairService.run_nightly()
         ├─ fix_stuck_in_progress()      → DELETE sync_status WHERE in_progress > 2h
         ├─ fix_null_game_dates()        → DELETE sync_status → scheduler re-queues events
         ├─ fix_missing_events()         → DELETE sync_status → scheduler re-queues events
         ├─ fix_null_period_from_events() → UPDATE games SET period=...
         ├─ fix_stale_failed_rows()      → DELETE sync_status WHERE failed > 7d
         └─ write sync_status row (completed, records_synced=total)

Manual (admin button or manage.py)
  POST /api/v1/admin/repair
    └─ RepairService.run_nightly()  (same path as above)

Admin dashboard (page load)
  GET /admin  →  runs report queries live
    ├─ report_games_no_lineup()
    ├─ report_roster_gaps()
    └─ report_unresolved_stats()
```

---

## Files to Create / Modify

| File | Change |
|---|---|
| `app/services/repair_service.py` | **New** — RepairService class |
| `app/services/scheduler.py` | Add `repair` policy + `_dispatch` branch |
| `app/api/v1/admin.py` | Add `POST /repair` endpoint |
| `app/main.py` | Wire `RepairService` into app startup |
| `backend/manage.py` | Add `repair` command |
| `backend/templates/admin.html` | Add DB Health section |

---

## Out of Scope

- Aggressive re-indexing (force-reindex all suspicious games) — reported only, not fixed
- Lower-league roster indexing (API returns 400 for tier 3+) — by design
- Real-time repair on demand per-game — out of scope for this iteration

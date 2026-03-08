# DB Repair Service Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `RepairService` that runs nightly to fix persistent DB failures, surfaces a health report on the admin dashboard, and can be triggered manually via CLI or admin button.

**Architecture:** A standalone `RepairService` class with idempotent SQL-only fix methods and read-only report queries. The nightly scheduler policy calls `run_nightly()` via the existing `_run()` dispatch in `main.py`. The admin dashboard adds a "DB Health" section with last-run stats and three suspicious-game tables. A `manage.py repair` CLI command allows ad-hoc execution.

**Tech Stack:** Python 3.9+, SQLAlchemy (raw `text()` queries), FastAPI, Jinja2, Alpine.js, Click (CLI)

---

## Reference: Key Files

| File | Role |
|---|---|
| `backend/app/services/repair_service.py` | **New** — RepairService class |
| `backend/app/services/scheduler.py` | Add `repair` policy to `POLICIES` list |
| `backend/app/main.py` | Add `repair` task branch in `_run()`, add `POST /admin/api/repair` endpoint |
| `backend/manage.py` | Add `repair` CLI command |
| `backend/templates/admin.html` | Add DB Health section |
| `backend/tests/test_repair_service.py` | **New** — unit tests |

## Reference: SyncStatus Row for Repair

The repair job writes `entity_type='repair'`, `entity_id='all'`, `sync_status='completed'`, `records_synced=<total rows fixed>` to `sync_status`. The scheduler uses this to determine when to run next (24h max_age).

## Reference: How SyncStatus is Written

Use raw SQLAlchemy `text()` for the upsert (same as migrations in `database.py`):

```python
from sqlalchemy import text
conn.execute(text("""
    INSERT INTO sync_status (entity_type, entity_id, sync_status, last_sync, records_synced)
    VALUES (:et, :eid, 'completed', :now, :n)
    ON CONFLICT (entity_type, entity_id) DO UPDATE SET
        sync_status='completed', last_sync=:now, records_synced=:n, error_message=NULL
"""), {"et": "repair", "eid": "all", "now": datetime.utcnow(), "n": total})
```

## Reference: How _run() Adds New Task Branches

In `main.py`, `_run()` is a large async function with consecutive `if task == "..."` blocks. After the last block (around line 2050), add:

```python
if task == "repair":
    push("info", "Running DB repair...")
    result = await asyncio.to_thread(repair_service.run_nightly)
    stats.update(result)
    push("ok", f"Repair done: {result['total_fixed']} rows fixed")
    set_progress(100)
```

`repair_service` is the module-level singleton (same pattern as `indexer`).

---

## Task 1: RepairService — skeleton + tests

**Files:**
- Create: `backend/app/services/repair_service.py`
- Create: `backend/tests/test_repair_service.py`

### Step 1: Write the failing tests

```python
# backend/tests/test_repair_service.py
"""Tests for RepairService — conservative DB repairs and health reports."""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import text
from app.services.repair_service import RepairService
from app.services.database import DatabaseService
from app.models.db_models import Base, Game, GameEvent, SyncStatus


@pytest.fixture
def db():
    """Fresh in-memory DB for each test."""
    svc = DatabaseService("sqlite:///:memory:")
    svc.initialize()
    return svc


@pytest.fixture
def repair(db):
    return RepairService(db)


def test_run_nightly_returns_dict(repair):
    result = repair.run_nightly()
    assert isinstance(result, dict)
    assert "total_fixed" in result
    assert "stuck_in_progress" in result
    assert "null_game_dates" in result
    assert "missing_events" in result
    assert "null_period_fixed" in result
    assert "stale_failed" in result


def test_run_nightly_on_empty_db_returns_zeros(repair):
    result = repair.run_nightly()
    assert result["total_fixed"] == 0


def test_fix_stuck_in_progress_resets_old_rows(db, repair):
    """in_progress rows older than 2h should be deleted."""
    with db.session_scope() as session:
        old = SyncStatus(
            entity_type="game_events",
            entity_id="game:999:events",
            sync_status="in_progress",
            last_sync=datetime.utcnow() - timedelta(hours=3),
        )
        recent = SyncStatus(
            entity_type="game_events",
            entity_id="game:998:events",
            sync_status="in_progress",
            last_sync=datetime.utcnow() - timedelta(minutes=10),
        )
        session.add_all([old, recent])

    n = repair.fix_stuck_in_progress()
    assert n == 1  # only the old one

    with db.session_scope() as session:
        remaining = session.query(SyncStatus).filter_by(sync_status="in_progress").count()
        assert remaining == 1  # recent one untouched


def test_fix_null_game_dates_deletes_sync_rows(db, repair):
    """Finished games with null game_date should have their sync_status deleted."""
    with db.session_scope() as session:
        # Insert a minimal game with null date and a finished sync row
        session.execute(text("""
            INSERT INTO seasons (id) VALUES (2025)
        """))
        session.execute(text("""
            INSERT INTO games (id, season_id, status, home_score, away_score)
            VALUES (1001, 2025, 'finished', 3, 2)
        """))
        session.execute(text("""
            INSERT INTO sync_status (entity_type, entity_id, sync_status, last_sync)
            VALUES ('game_events', 'game:1001:events', 'completed', :now)
        """), {"now": datetime.utcnow()})

    n = repair.fix_null_game_dates()
    assert n == 1

    with db.session_scope() as session:
        row = session.query(SyncStatus).filter_by(entity_id="game:1001:events").first()
        assert row is None  # deleted so scheduler re-queues


def test_fix_missing_events_deletes_sync_rows(db, repair):
    """Finished scored games with 0 events should have sync_status deleted."""
    with db.session_scope() as session:
        session.execute(text("INSERT INTO seasons (id) VALUES (2025)"))
        session.execute(text("""
            INSERT INTO games (id, season_id, status, home_score, away_score, game_date)
            VALUES (1002, 2025, 'finished', 2, 1, '2025-10-01')
        """))
        # sync_status exists (completed) but no game_events rows
        session.execute(text("""
            INSERT INTO sync_status (entity_type, entity_id, sync_status, last_sync)
            VALUES ('game_events', 'game:1002:events', 'completed', :now)
        """), {"now": datetime.utcnow()})

    n = repair.fix_missing_events()
    assert n == 1


def test_fix_null_period_from_events_sets_ot(db, repair):
    """Games with a goal event at time >= 61:00 should get period='OT'."""
    with db.session_scope() as session:
        session.execute(text("INSERT INTO seasons (id) VALUES (2025)"))
        session.execute(text("""
            INSERT INTO games (id, season_id, status, home_score, away_score, game_date, period)
            VALUES (1003, 2025, 'finished', 3, 2, '2025-11-01', NULL)
        """))
        session.execute(text("""
            INSERT INTO game_events (id, game_id, event_type, time)
            VALUES (1, 1003, 'Torschütze', '62:15')
        """))

    n = repair.fix_null_period_from_events()
    assert n >= 1

    with db.session_scope() as session:
        row = session.execute(text("SELECT period FROM games WHERE id=1003")).fetchone()
        assert row[0] == "OT"


def test_fix_null_period_from_events_sets_so(db, repair):
    """Games with a Penaltyschiessen event should get period='SO'."""
    with db.session_scope() as session:
        session.execute(text("INSERT INTO seasons (id) VALUES (2025)"))
        session.execute(text("""
            INSERT INTO games (id, season_id, status, home_score, away_score, game_date, period)
            VALUES (1004, 2025, 'finished', 3, 2, '2025-11-01', NULL)
        """))
        session.execute(text("""
            INSERT INTO game_events (id, game_id, event_type, time)
            VALUES (2, 1004, 'Penaltyschiessen', '65:00')
        """))

    n = repair.fix_null_period_from_events()
    assert n >= 1

    with db.session_scope() as session:
        row = session.execute(text("SELECT period FROM games WHERE id=1004")).fetchone()
        assert row[0] == "SO"


def test_fix_stale_failed_rows_deletes_old_failures(db, repair):
    """Failed sync_status rows older than 7 days should be deleted."""
    with db.session_scope() as session:
        old_fail = SyncStatus(
            entity_type="game_events",
            entity_id="game:888:events",
            sync_status="failed",
            last_sync=datetime.utcnow() - timedelta(days=8),
        )
        recent_fail = SyncStatus(
            entity_type="game_events",
            entity_id="game:887:events",
            sync_status="failed",
            last_sync=datetime.utcnow() - timedelta(days=2),
        )
        session.add_all([old_fail, recent_fail])

    n = repair.fix_stale_failed_rows()
    assert n == 1  # only the old one

    with db.session_scope() as session:
        remaining = session.query(SyncStatus).filter_by(sync_status="failed").count()
        assert remaining == 1


def test_report_methods_return_lists(repair):
    assert isinstance(repair.report_games_no_lineup(), list)
    assert isinstance(repair.report_roster_gaps(), list)
    assert isinstance(repair.report_unresolved_stats(), list)


def test_run_nightly_writes_sync_status(db, repair):
    """run_nightly() should write a completed sync_status row."""
    repair.run_nightly()
    with db.session_scope() as session:
        row = session.query(SyncStatus).filter_by(
            entity_type="repair", entity_id="all"
        ).first()
        assert row is not None
        assert row.sync_status == "completed"
```

### Step 2: Run tests to verify they fail

```bash
cd backend
pytest tests/test_repair_service.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'RepairService'`

### Step 3: Implement RepairService

```python
# backend/app/services/repair_service.py
"""
Conservative DB repair service.

Fixes persistent failures that the normal scheduler cannot self-heal:
  - Stuck in_progress sync_status rows (crashed workers)
  - Games with null game_date (forces re-index via sync_status delete)
  - Finished scored games with zero events (forces re-index)
  - Games with null period where OT/SO can be inferred from events
  - Stale failed sync_status rows blocking retries

Also provides read-only report queries for the admin dashboard.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import text

logger = logging.getLogger(__name__)

# How old an in_progress row must be before we reset it
_STUCK_THRESHOLD_HOURS = 2
# How old a failed row must be before we clear it for retry
_STALE_FAILED_DAYS = 7


class RepairService:
    def __init__(self, db_service):
        self.db_service = db_service

    # ── Conservative repairs ───────────────────────────────────────────────

    def fix_stuck_in_progress(self) -> int:
        """Delete in_progress sync_status rows older than 2h.

        Crashed workers leave rows locked; deleting them lets the scheduler
        re-queue the work on the next tick.
        Returns number of rows deleted.
        """
        cutoff = datetime.utcnow() - timedelta(hours=_STUCK_THRESHOLD_HOURS)
        with self.db_service.session_scope() as session:
            n = session.execute(text("""
                DELETE FROM sync_status
                WHERE sync_status = 'in_progress'
                  AND last_sync < :cutoff
            """), {"cutoff": cutoff}).rowcount
        if n:
            logger.info("[repair] reset %d stuck in_progress rows", n)
        return n

    def fix_null_game_dates(self) -> int:
        """Delete game_events sync_status for finished games with null game_date.

        The event indexer backfills game_date from the game_details API when
        it runs. Deleting the sync_status row forces a re-run.
        Returns number of sync_status rows deleted.
        """
        with self.db_service.session_scope() as session:
            n = session.execute(text("""
                DELETE FROM sync_status
                WHERE entity_type = 'game_events'
                  AND entity_id IN (
                      SELECT 'game:' || g.id || ':events'
                      FROM games g
                      WHERE g.game_date IS NULL
                        AND g.status = 'finished'
                        AND g.home_score IS NOT NULL
                  )
            """)).rowcount
        if n:
            logger.info("[repair] queued %d null-game_date games for re-index", n)
        return n

    def fix_missing_events(self) -> int:
        """Delete game_events sync_status for finished scored games with 0 events.

        These games were marked completed but the API returned no events.
        Deleting the sync_status row forces the scheduler to retry them.
        Returns number of sync_status rows deleted.
        """
        with self.db_service.session_scope() as session:
            n = session.execute(text("""
                DELETE FROM sync_status
                WHERE entity_type = 'game_events'
                  AND entity_id IN (
                      SELECT 'game:' || g.id || ':events'
                      FROM games g
                      WHERE g.status = 'finished'
                        AND g.home_score IS NOT NULL
                        AND NOT EXISTS (
                            SELECT 1 FROM game_events ge WHERE ge.game_id = g.id
                        )
                  )
            """)).rowcount
        if n:
            logger.info("[repair] queued %d no-events games for re-index", n)
        return n

    def fix_null_period_from_events(self) -> int:
        """Set period='OT' or 'SO' from existing event rows for finished games.

        OT: a goal event at time >= 61:00 exists.
        SO: a Penaltyschiessen event exists (takes priority over OT).
        Returns total number of games updated.
        """
        with self.db_service.session_scope() as session:
            ot = session.execute(text("""
                UPDATE games
                SET period = 'OT'
                WHERE status = 'finished'
                  AND period IS NULL
                  AND home_score IS NOT NULL
                  AND id IN (
                      SELECT DISTINCT game_id FROM game_events
                      WHERE time >= '61:00'
                        AND event_type LIKE 'Torschütze%'
                  )
            """)).rowcount
            so = session.execute(text("""
                UPDATE games
                SET period = 'SO'
                WHERE status = 'finished'
                  AND period IS NULL
                  AND home_score IS NOT NULL
                  AND id IN (
                      SELECT DISTINCT game_id FROM game_events
                      WHERE event_type LIKE 'Penaltyschiessen%'
                  )
            """)).rowcount
        total = ot + so
        if total:
            logger.info("[repair] set period for %d games (OT=%d SO=%d)", total, ot, so)
        return total

    def fix_stale_failed_rows(self) -> int:
        """Delete failed game_events sync_status rows older than 7 days.

        Failed rows block the scheduler from retrying for max_age (up to 720h).
        Deleting them lets the scheduler queue a fresh attempt.
        Returns number of rows deleted.
        """
        cutoff = datetime.utcnow() - timedelta(days=_STALE_FAILED_DAYS)
        with self.db_service.session_scope() as session:
            n = session.execute(text("""
                DELETE FROM sync_status
                WHERE entity_type = 'game_events'
                  AND sync_status = 'failed'
                  AND last_sync < :cutoff
            """), {"cutoff": cutoff}).rowcount
        if n:
            logger.info("[repair] cleared %d stale failed rows", n)
        return n

    # ── Report queries (read-only) ─────────────────────────────────────────

    def report_games_no_lineup(self) -> list[dict]:
        """Finished games that have events but zero game_players rows.

        These games were indexed for events but the lineup was never captured.
        Returned as list of dicts with keys: game_id, game_date, season_id,
        home_team_id, away_team_id, event_count.
        """
        with self.db_service.session_scope() as session:
            rows = session.execute(text("""
                SELECT g.id, g.game_date, g.season_id,
                       g.home_team_id, g.away_team_id,
                       COUNT(ge.id) AS event_count
                FROM games g
                JOIN game_events ge ON ge.game_id = g.id
                WHERE g.status = 'finished'
                  AND g.home_score IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM game_players gp WHERE gp.game_id = g.id
                  )
                GROUP BY g.id
                ORDER BY g.game_date DESC
                LIMIT 200
            """)).fetchall()
        return [
            {
                "game_id": r[0],
                "game_date": str(r[1]) if r[1] else None,
                "season_id": r[2],
                "home_team_id": r[3],
                "away_team_id": r[4],
                "event_count": r[5],
            }
            for r in rows
        ]

    def report_roster_gaps(self) -> list[dict]:
        """Teams where game_players count > team_players count.

        Players appeared in game lineups but were never added to the roster.
        Returned as list of dicts with keys: team_id, season_id,
        game_player_count, roster_count, delta.
        """
        with self.db_service.session_scope() as session:
            rows = session.execute(text("""
                SELECT gp.team_id, gp.season_id,
                       COUNT(DISTINCT gp.player_id) AS gp_count,
                       COUNT(DISTINCT tp.player_id) AS tp_count
                FROM game_players gp
                LEFT JOIN team_players tp
                    ON tp.team_id = gp.team_id
                    AND tp.season_id = gp.season_id
                    AND tp.player_id = gp.player_id
                GROUP BY gp.team_id, gp.season_id
                HAVING COUNT(DISTINCT gp.player_id) > COUNT(DISTINCT tp.player_id)
                ORDER BY (COUNT(DISTINCT gp.player_id) - COUNT(DISTINCT tp.player_id)) DESC
                LIMIT 100
            """)).fetchall()
        return [
            {
                "team_id": r[0],
                "season_id": r[1],
                "game_player_count": r[2],
                "roster_count": r[3],
                "delta": r[2] - r[3],
            }
            for r in rows
        ]

    def report_unresolved_stats(self) -> list[dict]:
        """player_statistics rows with null team_id or null game_class.

        Returned as list of dicts with keys: player_id, season_id,
        league_abbrev, team_name, team_id, game_class.
        """
        with self.db_service.session_scope() as session:
            rows = session.execute(text("""
                SELECT ps.player_id, ps.season_id, ps.league_abbrev,
                       ps.team_name, ps.team_id, ps.game_class
                FROM player_statistics ps
                WHERE ps.team_id IS NULL OR ps.game_class IS NULL
                ORDER BY ps.season_id DESC, ps.player_id
                LIMIT 200
            """)).fetchall()
        return [
            {
                "player_id": r[0],
                "season_id": r[1],
                "league_abbrev": r[2],
                "team_name": r[3],
                "team_id": r[4],
                "game_class": r[5],
            }
            for r in rows
        ]

    # ── Entry point ────────────────────────────────────────────────────────

    def run_nightly(self) -> dict:
        """Run all conservative fixes. Returns summary dict with row counts."""
        logger.info("[repair] starting nightly repair run")
        result = {
            "stuck_in_progress": self.fix_stuck_in_progress(),
            "null_game_dates":   self.fix_null_game_dates(),
            "missing_events":    self.fix_missing_events(),
            "null_period_fixed": self.fix_null_period_from_events(),
            "stale_failed":      self.fix_stale_failed_rows(),
        }
        result["total_fixed"] = sum(result.values())
        logger.info("[repair] nightly run complete: %s", result)
        self._write_sync_status(result["total_fixed"])
        return result

    def _write_sync_status(self, total_fixed: int):
        """Upsert a completed sync_status row so the scheduler sees last run time."""
        with self.db_service.session_scope() as session:
            session.execute(text("""
                INSERT INTO sync_status
                    (entity_type, entity_id, sync_status, last_sync, records_synced)
                VALUES ('repair', 'all', 'completed', :now, :n)
                ON CONFLICT (entity_type, entity_id) DO UPDATE SET
                    sync_status   = 'completed',
                    last_sync     = :now,
                    records_synced = :n,
                    error_message = NULL
            """), {"now": datetime.utcnow(), "n": total_fixed})


# Module-level singleton (same pattern as data_indexer)
_repair_service: RepairService | None = None


def get_repair_service() -> RepairService:
    global _repair_service
    if _repair_service is None:
        from app.services.database import get_database_service
        _repair_service = RepairService(get_database_service())
    return _repair_service
```

### Step 4: Run tests to verify they pass

```bash
cd backend
pytest tests/test_repair_service.py -v
```

Expected: all 10 tests PASS

### Step 5: Commit

```bash
git add backend/app/services/repair_service.py backend/tests/test_repair_service.py
git commit -m "feat: add RepairService with conservative DB repair methods and report queries"
```

---

## Task 2: Scheduler integration

**Files:**
- Modify: `backend/app/services/scheduler.py` — add repair policy to `POLICIES`
- Modify: `backend/app/main.py` — add repair singleton init + task branch in `_run()`

### Step 1: Write the failing test

```python
# In backend/tests/test_scheduler.py — add to the existing file:

def test_repair_policy_exists():
    """Repair policy must be present and configured as a global nightly job."""
    from app.services.scheduler import POLICIES
    policy = next((p for p in POLICIES if p["name"] == "repair"), None)
    assert policy is not None, "repair policy missing from POLICIES"
    assert policy["scope"] == "global"
    assert policy["task"] == "repair"
    assert policy.get("run_at_hour") == 3
```

### Step 2: Run test to verify it fails

```bash
cd backend
pytest tests/test_scheduler.py::test_repair_policy_exists -v
```

Expected: FAIL — `AssertionError: repair policy missing from POLICIES`

### Step 3: Add repair policy to POLICIES

In `backend/app/services/scheduler.py`, append to the `POLICIES` list after the last `player_game_stats_t6` entry (after line 316, before the closing `]`):

```python
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
```

### Step 4: Run test to verify it passes

```bash
cd backend
pytest tests/test_scheduler.py::test_repair_policy_exists -v
```

Expected: PASS

### Step 5: Wire repair singleton in main.py

In `backend/app/main.py`, find the line that creates the `indexer` singleton (search for `get_data_indexer`). Add the repair service import and singleton below it:

```python
from app.services.repair_service import get_repair_service
repair_service = get_repair_service()
```

Then in the `_TASK_META` dict (around line 1043), add:

```python
"repair": "DB Repair",
```

And in `_TASK_TIMEOUT` dict (around line 1067), add:

```python
"repair": 120,
```

Then in `_run()`, after the last `if task == ...` block, add:

```python
        # ── DB REPAIR ──────────────────────────────────────────────────────
        if task == "repair":
            push("info", "Running nightly DB repair...")
            result = await asyncio.to_thread(repair_service.run_nightly)
            stats.update(result)
            push("ok", (
                f"Repair complete: {result['total_fixed']} rows fixed "
                f"(stuck={result['stuck_in_progress']}, "
                f"dates={result['null_game_dates']}, "
                f"events={result['missing_events']}, "
                f"period={result['null_period_fixed']}, "
                f"failed={result['stale_failed']})"
            ))
            set_progress(100)
```

### Step 6: Write integration test

```python
# In backend/tests/test_admin_indexing.py — add to TestAdminIndexingAPI:

def test_repair_task_is_recognised(self, admin_client):
    r = admin_client.post("/admin/api/index", json={"season": 0, "task": "repair"})
    assert r.status_code == 200
    data = r.json()
    assert "job_id" in data
```

### Step 7: Run all tests

```bash
cd backend
pytest tests/test_scheduler.py tests/test_admin_indexing.py tests/test_repair_service.py -v
```

Expected: all PASS

### Step 8: Commit

```bash
git add backend/app/services/scheduler.py backend/app/main.py backend/tests/test_admin_indexing.py
git commit -m "feat: integrate repair task into scheduler and _run() dispatch"
```

---

## Task 3: `manage.py repair` CLI command

**Files:**
- Modify: `backend/manage.py` — add `repair` command

### Step 1: Write the failing test

```python
# backend/tests/test_repair_cli.py  (new file)
"""Tests for manage.py repair command."""
from click.testing import CliRunner


def test_repair_command_exits_zero():
    from manage import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["repair"])
    assert result.exit_code == 0, result.output


def test_repair_command_prints_summary():
    from manage import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["repair"])
    assert "Repair complete" in result.output
    assert "total_fixed" in result.output or "rows fixed" in result.output
```

### Step 2: Run tests to verify they fail

```bash
cd backend
pytest tests/test_repair_cli.py -v
```

Expected: FAIL — `No such command 'repair'`

### Step 3: Add the repair command to manage.py

In `backend/manage.py`, add after the `stats` command (after line 582):

```python
@cli.command()
def repair():
    """Run conservative DB repairs and print a health summary.

    Fixes:
      - Stuck in_progress sync_status rows (crashed workers)
      - Games with null game_date (queues re-index)
      - Finished games with zero events (queues re-index)
      - Null period detectable from existing events
      - Stale failed sync_status rows blocking retries

    Also prints counts of suspicious games (no-lineup, roster gaps,
    unresolved player stats) for investigation.
    """
    from app.services.repair_service import get_repair_service

    click.echo("Running DB repair...")
    svc = get_repair_service()
    result = svc.run_nightly()

    click.echo("\n=== Repair Summary ===")
    click.echo(f"  Stuck in_progress reset : {result['stuck_in_progress']}")
    click.echo(f"  Null game_date queued   : {result['null_game_dates']}")
    click.echo(f"  Missing events queued   : {result['missing_events']}")
    click.echo(f"  Null period fixed       : {result['null_period_fixed']}")
    click.echo(f"  Stale failed cleared    : {result['stale_failed']}")
    click.echo(f"  ─────────────────────────────")
    click.echo(f"  Total rows fixed        : {result['total_fixed']}")

    click.echo("\n=== Suspicious Games (report only) ===")

    no_lineup = svc.report_games_no_lineup()
    click.echo(f"  Games with events but no lineup : {len(no_lineup)}")
    for g in no_lineup[:5]:
        click.echo(f"    game {g['game_id']}  date={g['game_date']}  events={g['event_count']}")
    if len(no_lineup) > 5:
        click.echo(f"    ... and {len(no_lineup) - 5} more")

    gaps = svc.report_roster_gaps()
    click.echo(f"  Teams with roster gaps          : {len(gaps)}")
    for g in gaps[:5]:
        click.echo(f"    team {g['team_id']} s={g['season_id']}  game={g['game_player_count']} roster={g['roster_count']}")

    unresolved = svc.report_unresolved_stats()
    click.echo(f"  Unresolved player stats rows    : {len(unresolved)}")

    click.echo("\n✓ Repair done.")
```

### Step 4: Run tests to verify they pass

```bash
cd backend
pytest tests/test_repair_cli.py -v
```

Expected: PASS

### Step 5: Commit

```bash
git add backend/manage.py backend/tests/test_repair_cli.py
git commit -m "feat: add manage.py repair CLI command"
```

---

## Task 4: Admin API endpoint

**Files:**
- Modify: `backend/app/main.py` — add `POST /admin/api/repair` endpoint

### Step 1: Write the failing test

```python
# In backend/tests/test_admin_indexing.py — add new class:

class TestAdminRepairEndpoint:
    def test_repair_endpoint_requires_auth(self, client):
        r = client.post("/admin/api/repair")
        assert r.status_code in (401, 403)

    def test_repair_endpoint_returns_ok(self, admin_client):
        r = admin_client.post("/admin/api/repair")
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True
        assert "total_fixed" in data
        assert "stuck_in_progress" in data
        assert "null_game_dates" in data

    def test_repair_endpoint_includes_reports(self, admin_client):
        r = admin_client.post("/admin/api/repair")
        data = r.json()
        assert "games_no_lineup" in data
        assert "roster_gaps" in data
        assert "unresolved_stats" in data
        assert isinstance(data["games_no_lineup"], list)
```

### Step 2: Run tests to verify they fail

```bash
cd backend
pytest tests/test_admin_indexing.py::TestAdminRepairEndpoint -v
```

Expected: FAIL — 404 (endpoint doesn't exist)

### Step 3: Add endpoint to main.py

After the `admin_cleanup_duplicates` endpoint (around line 700), add:

```python
@app.post("/admin/api/repair")
async def admin_repair(_: None = Depends(require_admin)):
    """Run conservative DB repairs immediately and return summary + health report."""
    try:
        result = await asyncio.to_thread(repair_service.run_nightly)
        result["ok"] = True
        result["games_no_lineup"] = repair_service.report_games_no_lineup()
        result["roster_gaps"] = repair_service.report_roster_gaps()
        result["unresolved_stats"] = repair_service.report_unresolved_stats()
        return result
    except Exception as exc:
        logger.error("admin_repair failed: %s", exc, exc_info=True)
        return {"ok": False, "detail": str(exc)}
```

### Step 4: Also add `GET /admin/api/repair-report` (read-only, for dashboard page load)

This endpoint returns only the report queries (no fixes) so the dashboard can load health data without side effects:

```python
@app.get("/admin/api/repair-report")
async def admin_repair_report(_: None = Depends(require_admin)):
    """Return the health report (read-only, no fixes applied)."""
    from app.services.database import get_database_service
    from app.models.db_models import SyncStatus
    try:
        # Last repair run info from sync_status
        db = get_database_service()
        last_run = None
        last_fixed = 0
        with db.session_scope() as session:
            row = session.query(SyncStatus).filter_by(
                entity_type="repair", entity_id="all"
            ).first()
            if row:
                last_run = row.last_sync.isoformat() if row.last_sync else None
                last_fixed = row.records_synced or 0

        return {
            "ok": True,
            "last_run": last_run,
            "last_fixed": last_fixed,
            "games_no_lineup": repair_service.report_games_no_lineup(),
            "roster_gaps": repair_service.report_roster_gaps(),
            "unresolved_stats": repair_service.report_unresolved_stats(),
        }
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}
```

### Step 5: Run tests to verify they pass

```bash
cd backend
pytest tests/test_admin_indexing.py -v
```

Expected: all PASS

### Step 6: Commit

```bash
git add backend/app/main.py backend/tests/test_admin_indexing.py
git commit -m "feat: add POST /admin/api/repair and GET /admin/api/repair-report endpoints"
```

---

## Task 5: Admin dashboard — DB Health section

**Files:**
- Modify: `backend/templates/admin.html`

### Step 1: Find the right insertion point

The admin.html has a two-column `.layout` grid. The DB Health section goes at the bottom of the left (main) column, after the season accordion cards. Search for the closing tag of the main column content to find the insertion point.

Run:
```bash
grep -n "layout\|</main\|sidebar\|<!-- end" backend/templates/admin.html | head -20
```

### Step 2: Add CSS for the health section

In the `<style>` block of `admin.html`, before the closing `</style>`, add:

```css
/* ── DB Health section ── */
.health-section {
  background: #161b22; border: 1px solid #30363d; border-radius: 8px;
  padding: 1rem; margin-top: 1.25rem;
}
.health-section .section-title { margin-bottom: .75rem; }
.health-meta { font-size: .78rem; color: #8b949e; margin-bottom: .75rem; display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; }
.health-meta strong { color: #c9d1d9; }
.repair-btn {
  background: #21262d; border: 1px solid #30363d; color: #c9d1d9;
  border-radius: 6px; padding: .3rem .8rem; font-size: .78rem; cursor: pointer;
  margin-left: auto;
}
.repair-btn:hover { background: #30363d; }
.repair-btn:disabled { opacity: .5; cursor: not-allowed; }
.health-table { width: 100%; border-collapse: collapse; font-size: .78rem; margin-bottom: .75rem; }
.health-table th { text-align: left; color: #6e7681; font-weight: 600; padding: .3rem .5rem; border-bottom: 1px solid #21262d; }
.health-table td { padding: .3rem .5rem; border-bottom: 1px solid #161b22; }
.health-table a { color: #58a6ff; text-decoration: none; }
.health-table a:hover { text-decoration: underline; }
.collapsible-header {
  cursor: pointer; user-select: none; display: flex; align-items: center;
  gap: .5rem; font-size: .78rem; font-weight: 600; color: #8b949e;
  padding: .4rem 0; border-bottom: 1px solid #21262d; margin-bottom: .5rem;
}
.collapsible-header:hover { color: #c9d1d9; }
.collapsible-chevron { font-size: .65rem; transition: transform .2s; }
.collapsible-chevron.open { transform: rotate(90deg); }
.collapsible-body { display: none; }
.collapsible-body.open { display: block; }
.health-empty { color: #3fb950; font-size: .78rem; padding: .3rem 0; }
```

### Step 3: Add the DB Health section HTML

Find the closing `</div>` of the main (left) column content and insert the health section before it. The section uses Alpine.js `x-data` for the "Run repair now" button state and collapsible tables:

```html
<!-- ── DB Health ───────────────────────────────────────────────── -->
<div class="health-section" x-data="healthPanel()" x-init="load()">
  <div class="section-title">DB Health</div>

  <div class="health-meta">
    <span>Last repair: <strong x-text="lastRun || 'never'"></strong></span>
    <span>Rows fixed: <strong x-text="lastFixed"></strong></span>
    <button class="repair-btn" :disabled="running" @click="runRepair()">
      <span x-show="!running">Run repair now</span>
      <span x-show="running">Running…</span>
    </button>
  </div>

  <template x-if="error">
    <div style="color:#f85149;font-size:.78rem;margin-bottom:.5rem" x-text="error"></div>
  </template>

  <!-- Games with events but no lineup -->
  <div>
    <div class="collapsible-header" @click="toggle('lineup')">
      <span class="collapsible-chevron" :class="{open: open.lineup}">▶</span>
      Games with events but no lineup
      <span style="margin-left:auto;color:#d29922;font-weight:700" x-text="gamesNoLineup.length"></span>
    </div>
    <div class="collapsible-body" :class="{open: open.lineup}">
      <template x-if="gamesNoLineup.length === 0">
        <div class="health-empty">✓ None</div>
      </template>
      <template x-if="gamesNoLineup.length > 0">
        <table class="health-table">
          <thead><tr><th>Game</th><th>Date</th><th>Season</th><th>Events</th></tr></thead>
          <tbody>
            <template x-for="g in gamesNoLineup" :key="g.game_id">
              <tr>
                <td><a :href="'/en/game/' + g.game_id" target="_blank" x-text="g.game_id"></a></td>
                <td x-text="g.game_date || '—'"></td>
                <td x-text="g.season_id"></td>
                <td x-text="g.event_count"></td>
              </tr>
            </template>
          </tbody>
        </table>
      </template>
    </div>
  </div>

  <!-- Roster gaps -->
  <div>
    <div class="collapsible-header" @click="toggle('roster')">
      <span class="collapsible-chevron" :class="{open: open.roster}">▶</span>
      Roster gaps (game players not in team roster)
      <span style="margin-left:auto;color:#d29922;font-weight:700" x-text="rosterGaps.length"></span>
    </div>
    <div class="collapsible-body" :class="{open: open.roster}">
      <template x-if="rosterGaps.length === 0">
        <div class="health-empty">✓ None</div>
      </template>
      <template x-if="rosterGaps.length > 0">
        <table class="health-table">
          <thead><tr><th>Team ID</th><th>Season</th><th>In Games</th><th>In Roster</th><th>Gap</th></tr></thead>
          <tbody>
            <template x-for="g in rosterGaps" :key="g.team_id + '-' + g.season_id">
              <tr>
                <td x-text="g.team_id"></td>
                <td x-text="g.season_id"></td>
                <td x-text="g.game_player_count"></td>
                <td x-text="g.roster_count"></td>
                <td x-text="g.delta"></td>
              </tr>
            </template>
          </tbody>
        </table>
      </template>
    </div>
  </div>

  <!-- Unresolved player stats -->
  <div>
    <div class="collapsible-header" @click="toggle('stats')">
      <span class="collapsible-chevron" :class="{open: open.stats}">▶</span>
      Unresolved player stats (null team_id or game_class)
      <span style="margin-left:auto;color:#d29922;font-weight:700" x-text="unresolvedStats.length"></span>
    </div>
    <div class="collapsible-body" :class="{open: open.stats}">
      <template x-if="unresolvedStats.length === 0">
        <div class="health-empty">✓ None</div>
      </template>
      <template x-if="unresolvedStats.length > 0">
        <table class="health-table">
          <thead><tr><th>Player</th><th>Team Name</th><th>League</th><th>Season</th></tr></thead>
          <tbody>
            <template x-for="s in unresolvedStats" :key="s.player_id + '-' + s.season_id + '-' + s.league_abbrev">
              <tr>
                <td x-text="s.player_id"></td>
                <td x-text="s.team_name || '—'"></td>
                <td x-text="s.league_abbrev || '—'"></td>
                <td x-text="s.season_id"></td>
              </tr>
            </template>
          </tbody>
        </table>
      </template>
    </div>
  </div>
</div>
```

### Step 4: Add the Alpine.js component

In the `<script>` section of admin.html (or near the bottom before `</body>`), add:

```javascript
function healthPanel() {
  return {
    lastRun: null,
    lastFixed: 0,
    gamesNoLineup: [],
    rosterGaps: [],
    unresolvedStats: [],
    running: false,
    error: null,
    open: { lineup: false, roster: false, stats: false },

    async load() {
      try {
        const r = await fetch('/admin/api/repair-report');
        const d = await r.json();
        if (d.ok) {
          this.lastRun = d.last_run ? new Date(d.last_run).toLocaleString() : null;
          this.lastFixed = d.last_fixed;
          this.gamesNoLineup = d.games_no_lineup;
          this.rosterGaps = d.roster_gaps;
          this.unresolvedStats = d.unresolved_stats;
        }
      } catch (e) {
        this.error = 'Failed to load health report';
      }
    },

    async runRepair() {
      this.running = true;
      this.error = null;
      try {
        const r = await fetch('/admin/api/repair', { method: 'POST' });
        const d = await r.json();
        if (d.ok) {
          this.lastFixed = d.total_fixed;
          this.lastRun = new Date().toLocaleString();
          this.gamesNoLineup = d.games_no_lineup;
          this.rosterGaps = d.roster_gaps;
          this.unresolvedStats = d.unresolved_stats;
        } else {
          this.error = d.detail || 'Repair failed';
        }
      } catch (e) {
        this.error = 'Repair request failed';
      } finally {
        this.running = false;
      }
    },

    toggle(key) {
      this.open[key] = !this.open[key];
    },
  };
}
```

### Step 5: Smoke-test manually

```bash
cd backend
uvicorn app.main:app --reload --port 8000
# Open http://localhost:8000/admin in browser (PIN: from .env)
# Verify DB Health section appears at bottom of main column
# Verify "Run repair now" button triggers POST and updates counts
# Verify three collapsible tables expand/collapse
```

### Step 6: Commit

```bash
git add backend/templates/admin.html
git commit -m "feat: add DB Health section to admin dashboard"
```

---

## Task 6: Run full test suite + deploy

### Step 1: Run all tests

```bash
cd backend
pytest -v 2>&1 | tail -30
```

Expected: all tests PASS (no regressions)

### Step 2: Push and deploy

```bash
git push
ssh pi4desk "cd ~/dockerimages/SwissUnihockeyStats && git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml build && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --force-recreate"
```

### Step 3: Verify in production

```bash
ssh pi4desk "docker logs swissunihockey-prod --tail 50 | grep -i repair"
```

Expected: no errors; on the next 03:30 UTC tick you'll see `[repair] starting nightly repair run`.

Verify manually:
- Open `https://swissunihockeystats.mennylenderr.ch/admin`
- Scroll to "DB Health" section
- Confirm it loads (counts appear)
- Click "Run repair now" and confirm counts update

---

## Summary of files changed

| File | Change |
|---|---|
| `backend/app/services/repair_service.py` | **New** — RepairService (5 fixes, 3 reports, run_nightly, sync_status write) |
| `backend/app/services/scheduler.py` | +1 policy: `repair` global nightly at 03:30 UTC |
| `backend/app/main.py` | +repair singleton init, +`repair` task branch in `_run()`, +`POST /admin/api/repair`, +`GET /admin/api/repair-report` |
| `backend/manage.py` | +`repair` CLI command |
| `backend/templates/admin.html` | +DB Health section (CSS + HTML + Alpine.js component) |
| `backend/tests/test_repair_service.py` | **New** — 10 unit tests |
| `backend/tests/test_repair_cli.py` | **New** — 2 CLI tests |
| `backend/tests/test_admin_indexing.py` | +3 endpoint tests |

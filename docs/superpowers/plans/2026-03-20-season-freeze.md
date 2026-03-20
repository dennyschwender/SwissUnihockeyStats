# Season Freeze Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `is_frozen` to `Season` so the scheduler skips past-season jobs once all games are finished, and expose freeze/unfreeze controls in the admin UI.

**Architecture:** Add the DB column + migration first (Task 1), then the scheduler skip + auto-freeze logic (Task 2), then the three admin API endpoints (Task 3), then wire up the admin UI (Task 4). Tasks 1–4 are sequential because each builds on the previous.

**Tech Stack:** Python, SQLAlchemy, FastAPI, SQLite, Jinja2 + HTMX, pytest.

---

## File Map

| File | Action |
|------|--------|
| `backend/app/models/db_models.py` | Add `is_frozen` to `Season` |
| `backend/app/services/database.py` | Add idempotent migration for `is_frozen` column |
| `backend/app/services/scheduler.py` | Add `_is_season_complete()`, skip frozen in `_maybe_schedule()`, auto-freeze in `_refresh_queue()` |
| `backend/app/main.py` | Add 3 admin API endpoints (completeness, freeze, unfreeze) |
| `backend/templates/admin/_tab_seasons.html` | Add completeness column + freeze/unfreeze buttons to seasons card |
| `backend/tests/test_season_freeze.py` | Tests for `_is_season_complete` and admin endpoints |
| `backend/tests/test_scheduler.py` | Tests for freeze skip and auto-freeze in `_maybe_schedule` / `_refresh_queue` |

---

## Task 1: Data Model + Migration

**Files:**
- Modify: `backend/app/models/db_models.py`
- Modify: `backend/app/services/database.py`
- Test: `backend/tests/test_season_freeze.py`

### Context

`Season` is defined at line 35 of `db_models.py`. `Boolean` is already imported. The existing columns are `id`, `text`, `highlighted`, `last_updated`, `last_full_sync`. The new column goes after `last_full_sync`.

The `_run_sqlite_migrations` method in `database.py` (line 197) adds columns with the pattern:
```python
existing_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(seasons)"))}
if "is_frozen" not in existing_cols:
    conn.execute(text("ALTER TABLE seasons ADD COLUMN is_frozen INTEGER NOT NULL DEFAULT 0"))
```
Add this block at the end of `_run_sqlite_migrations`, just before `conn.commit()` (line 431). The block for `player_statistics` ends around line 429 — add the seasons block after that.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_season_freeze.py`:

```python
"""Tests for season freeze feature."""
import pytest
from app.models.db_models import Season, Game


class TestSeasonModel:
    """Season.is_frozen column exists with correct default."""

    def test_is_frozen_default_false(self, app):
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            s = Season(id=9000, text="9000/01", highlighted=False)
            session.add(s)
        with db.session_scope() as session:
            s = session.query(Season).filter(Season.id == 9000).one()
            assert s.is_frozen is False
            session.delete(s)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/test_season_freeze.py::TestSeasonModel::test_is_frozen_default_false -v
```

Expected: FAIL — `Season` has no attribute `is_frozen`.

- [ ] **Step 3: Add `is_frozen` to Season model**

In `backend/app/models/db_models.py`, after the `last_full_sync` line (line 44):

```python
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")
```

- [ ] **Step 4: Add migration to `_run_sqlite_migrations`**

In `backend/app/services/database.py`, just before `conn.commit()` at the end of `_run_sqlite_migrations` (around line 430):

```python
            # ── Add is_frozen to seasons ─────────────────────────────────────
            season_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(seasons)"))}
            if "is_frozen" not in season_cols:
                conn.execute(text("ALTER TABLE seasons ADD COLUMN is_frozen INTEGER NOT NULL DEFAULT 0"))
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/test_season_freeze.py::TestSeasonModel::test_is_frozen_default_false -v
```

Expected: PASS.

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest --tb=short -q
```

Expected: all tests pass (or the same tests that were failing before, no new failures).

- [ ] **Step 7: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add backend/app/models/db_models.py backend/app/services/database.py backend/tests/test_season_freeze.py
git commit -m "feat(db): add is_frozen to Season model with idempotent migration"
```

---

## Task 2: Scheduler — Skip Frozen + Auto-Freeze

**Files:**
- Modify: `backend/app/services/scheduler.py`
- Test: `backend/tests/test_season_freeze.py` (add new test class)
- Test: `backend/tests/test_scheduler.py` (add new tests)

### Context

`_maybe_schedule` is at line 825 of `scheduler.py`. The skip-frozen check goes at the very top — before the double-queue guard — reading `Season.is_frozen` for the given `season` id.

`_refresh_queue` is at line 775. It opens one `session_scope()` covering the whole policy loop (lines 787–820). The auto-freeze block must open a **separate** `session_scope()` **after** the existing `with` block closes (after line 823), still inside the outer `try`. This avoids nesting session scopes or holding a write lock during the async policy iteration.

`_is_season_complete` is a module-level helper (not a method) that takes `(session, season_id: int) -> bool`.

**`_is_season_complete` logic:**
1. Count all games for the season — if 0, return False.
2. Count games where `status != 'finished'` — if > 0, return False.
3. Count `SyncStatus` rows where `entity_id LIKE '%:{season_id}'` AND `sync_status == 'in_progress'` — if > 0, return False.
4. Return True.

The LIKE pattern `%:{season_id}` uses a **trailing anchor** (no trailing `%`) to prevent season_id=2 matching entity_id `"season:2025"`. For example `%:2025` matches `"season:2025"` and `"clubs:2025"` but not `"season:20250"`.

**Skip-frozen in `_maybe_schedule`:**

```python
# At the very top of _maybe_schedule, before the double-queue guard (around line 838):
if season is not None:
    frozen = session.query(Season.is_frozen).filter(Season.id == season).scalar()
    if frozen:
        return  # season is frozen — skip entirely
```

Requires `Season` to be imported — it already is (imported inside `_refresh_queue` via local import).

Wait — the local imports are inside `_refresh_queue`, not at module level, and `_maybe_schedule` is a method called from within `_refresh_queue`. The `session` in `_maybe_schedule` is the same session passed from `_refresh_queue`. So the query works. But `Season` must be imported in scope where `_maybe_schedule` is defined. Since it's a class method, add the import at the top of the method body:

```python
def _maybe_schedule(self, session, policy, season, is_current_season=True):
    from app.models.db_models import Season, SyncStatus  # noqa: F811 — also imported in _refresh_queue
    if season is not None:
        frozen = session.query(Season.is_frozen).filter(Season.id == season).scalar()
        if frozen:
            return
    # ... rest of existing method unchanged ...
```

Actually, looking at the code more carefully — `Season` and `SyncStatus` are imported inside `_refresh_queue` (local import). `_maybe_schedule` is called from within that function but is a separate method. The cleanest approach: add a module-level import of `Season` and `SyncStatus` at the top of the file, or add a local import inside `_maybe_schedule`. Use local import to match the existing pattern in this file.

**Auto-freeze block in `_refresh_queue`:**

After the `except Exception` block at line 822–823, add:

```python
        # ── Auto-freeze past seasons whose data is complete ───────────────────
        try:
            from app.services.database import get_database_service
            from app.models.db_models import Season

            db_service = get_database_service()
            with db_service.session_scope() as session:
                past_seasons = session.query(Season).filter(
                    Season.highlighted == False, Season.is_frozen == False
                ).all()
                for season in past_seasons:
                    if _is_season_complete(session, season.id):
                        season.is_frozen = True
                        logger.info(
                            "[scheduler] Season %s auto-frozen (all games finished, no active syncs)",
                            season.id,
                        )
                # session_scope commits on exit — do NOT add session.commit() here
        except Exception as exc:
            logger.error("[scheduler] auto-freeze error: %s", exc, exc_info=True)
```

Note: the local variable `season` in the auto-freeze loop shadows the outer `season` variable (which is `None` in `_refresh_queue`'s scope since it iterates `sid`). This is fine — `_refresh_queue` uses `sid` as the loop variable, not `season`. Use `s` as the loop variable to avoid any shadowing confusion:

```python
                for s in past_seasons:
                    if _is_season_complete(session, s.id):
                        s.is_frozen = True
                        logger.info(
                            "[scheduler] Season %s auto-frozen (all games finished, no active syncs)",
                            s.id,
                        )
```

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_season_freeze.py`:

```python
from app.services.scheduler import _is_season_complete
from app.models.db_models import SyncStatus, Game


class TestIsSeasonComplete:
    """_is_season_complete returns correct bool."""

    def _setup_season(self, session, season_id: int) -> Season:
        s = Season(id=season_id, text=f"{season_id}/xx", highlighted=False)
        session.add(s)
        session.flush()
        return s

    def test_no_games_returns_false(self, app):
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            self._setup_season(session, 8001)
        with db.session_scope() as session:
            assert _is_season_complete(session, 8001) is False

    def test_all_finished_no_in_progress_returns_true(self, app):
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            self._setup_season(session, 8002)
            session.add(Game(
                id=80021, season_id=8002, group_id=None,
                home_team_id=1, away_team_id=2,
                home_score=3, away_score=1, status="finished",
            ))
        with db.session_scope() as session:
            assert _is_season_complete(session, 8002) is True

    def test_unfinished_game_returns_false(self, app):
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            self._setup_season(session, 8003)
            session.add(Game(
                id=80031, season_id=8003, group_id=None,
                home_team_id=1, away_team_id=2,
                status="scheduled",
            ))
        with db.session_scope() as session:
            assert _is_season_complete(session, 8003) is False

    def test_in_progress_sync_blocks_freeze(self, app):
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            self._setup_season(session, 8004)
            session.add(Game(
                id=80041, season_id=8004, group_id=None,
                home_team_id=1, away_team_id=2,
                home_score=2, away_score=0, status="finished",
            ))
            session.add(SyncStatus(
                entity_type="leagues",
                entity_id="leagues:8004",
                sync_status="in_progress",
            ))
        with db.session_scope() as session:
            assert _is_season_complete(session, 8004) is False

    def test_like_anchor_no_false_match(self, app):
        """Season 4 must not match entity_id 'leagues:8004'."""
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            self._setup_season(session, 4)
            self._setup_season(session, 8005)
            session.add(Game(
                id=40001, season_id=4, group_id=None,
                home_team_id=1, away_team_id=2,
                home_score=1, away_score=0, status="finished",
            ))
            # in_progress sync for season 8005 — must NOT block season 4
            session.add(SyncStatus(
                entity_type="leagues",
                entity_id="leagues:8005",
                sync_status="in_progress",
            ))
        with db.session_scope() as session:
            assert _is_season_complete(session, 4) is True
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/test_season_freeze.py::TestIsSeasonComplete -v
```

Expected: FAIL — `cannot import name '_is_season_complete' from 'app.services.scheduler'`.

- [ ] **Step 3: Add `_is_season_complete` to `scheduler.py`**

Add the following module-level function just above the `Scheduler` class definition (around line 388):

```python
def _is_season_complete(session, season_id: int) -> bool:
    """Return True when a past season has all games finished and no active syncs.

    Three conditions must all hold:
    1. The season has at least one game (data exists).
    2. Every game has status == 'finished' (no scheduled or live games remain).
    3. No SyncStatus row for this season is in_progress (no active sync running).

    The LIKE pattern uses a trailing anchor (%:{season_id}) — no trailing %
    — to avoid season_id=4 matching entity_id "leagues:8004".
    """
    from app.models.db_models import Game, SyncStatus
    from sqlalchemy import func  # for func.count

    total = session.query(func.count(Game.id)).filter(Game.season_id == season_id).scalar()
    if not total:
        return False
    unfinished = (
        session.query(func.count(Game.id))
        .filter(Game.season_id == season_id, Game.status != "finished")
        .scalar()
    )
    if unfinished:
        return False
    in_progress = (
        session.query(SyncStatus)
        .filter(
            SyncStatus.entity_id.like(f"%:{season_id}"),
            SyncStatus.sync_status == "in_progress",
        )
        .count()
    )
    return in_progress == 0
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/test_season_freeze.py::TestIsSeasonComplete -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Add skip-frozen check to `_maybe_schedule`**

In `backend/app/services/scheduler.py`, at the very top of `_maybe_schedule` (line ~838, before the double-queue guard at `key = ...`):

```python
    def _maybe_schedule(self, session, policy, season, is_current_season=True):
        # Skip frozen seasons entirely — no jobs, no DB queries
        if season is not None:
            from app.models.db_models import Season as _Season
            frozen = session.query(_Season.is_frozen).filter(_Season.id == season).scalar()
            if frozen:
                return
        # ... rest of existing method unchanged (key = ...) ...
```

- [ ] **Step 6: Add auto-freeze block at the end of `_refresh_queue`**

In `backend/app/services/scheduler.py`, at the end of `_refresh_queue` (after the existing `except Exception as exc:` block at line ~822), add the auto-freeze block. The structure of `_refresh_queue` is:

```python
    async def _refresh_queue(self):
        try:
            ...
            with db_service.session_scope() as session:
                ...  # policy loop
        except Exception as exc:
            logger.error(...)

        # ADD THIS AFTER THE EXCEPT BLOCK:
        # ── Auto-freeze past seasons whose data is complete ───────────────────
        try:
            from app.services.database import get_database_service
            from app.models.db_models import Season

            db_service = get_database_service()
            with db_service.session_scope() as session:
                past_seasons = session.query(Season).filter(
                    Season.highlighted == False,  # noqa: E712
                    Season.is_frozen == False,    # noqa: E712
                ).all()
                for s in past_seasons:
                    if _is_season_complete(session, s.id):
                        s.is_frozen = True
                        logger.info(
                            "[scheduler] Season %s auto-frozen (all games finished, no active syncs)",
                            s.id,
                        )
                # session_scope commits on exit — do NOT add session.commit() here
        except Exception as exc:
            logger.error("[scheduler] auto-freeze error: %s", exc, exc_info=True)
```

- [ ] **Step 7: Write scheduler freeze/skip tests**

Add to `backend/tests/test_scheduler.py`:

```python
class TestSeasonFreezeScheduler:
    """Frozen seasons are skipped by _maybe_schedule."""

    def test_maybe_schedule_skips_frozen_season(self, scheduler, app):
        """_maybe_schedule returns without enqueuing when season.is_frozen is True."""
        from app.services.database import get_database_service
        from app.models.db_models import Season

        db = get_database_service()
        with db.session_scope() as session:
            s = Season(id=7001, text="7001/xx", highlighted=False, is_frozen=True)
            session.add(s)

        policy = next(p for p in POLICIES if p["scope"] == "season")
        queue_before = len(scheduler._queue)

        with db.session_scope() as session:
            scheduler._maybe_schedule(session, policy, season=7001, is_current_season=False)

        assert len(scheduler._queue) == queue_before  # nothing enqueued

        # cleanup
        with db.session_scope() as session:
            session.query(Season).filter(Season.id == 7001).delete()

    def test_maybe_schedule_does_not_skip_unfrozen_season(self, scheduler, app):
        """_maybe_schedule proceeds normally for unfrozen seasons."""
        from app.services.database import get_database_service
        from app.models.db_models import Season

        db = get_database_service()
        with db.session_scope() as session:
            s = Season(id=7002, text="7002/xx", highlighted=True, is_frozen=False)
            session.add(s)

        policy = next(p for p in POLICIES if p["scope"] == "season" and not p.get("current_only"))
        queue_before = len(scheduler._queue)

        with db.session_scope() as session:
            scheduler._maybe_schedule(session, policy, season=7002, is_current_season=True)

        # Season 7002 has never been synced so a job should be enqueued
        assert len(scheduler._queue) > queue_before

        # cleanup
        scheduler._queue.clear()
        with db.session_scope() as session:
            session.query(Season).filter(Season.id == 7002).delete()
```

- [ ] **Step 8: Run all new scheduler tests**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/test_scheduler.py::TestSeasonFreezeScheduler -v
```

Expected: both PASS.

- [ ] **Step 9: Run full test suite**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest --tb=short -q
```

Expected: no new failures.

- [ ] **Step 10: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add backend/app/services/scheduler.py backend/tests/test_season_freeze.py backend/tests/test_scheduler.py
git commit -m "feat(scheduler): add season freeze — skip frozen seasons, auto-freeze complete past seasons"
```

---

## Task 3: Admin API Endpoints

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_season_freeze.py` (add new test class)

### Context

Existing season endpoints in `main.py` start around line 1490. Follow the same pattern:

```python
@app.post("/admin/api/season/{season_id}/set-current")
async def admin_set_current_season(season_id: int, _: None = Depends(require_admin)):
    from app.services.database import get_database_service
    from app.models.db_models import Season
    db = get_database_service()
    with db.session_scope() as session:
        ...
    return {"ok": True, ...}
```

Add the three new endpoints after the `admin_delete_season_layer` endpoint (around line 1589).

**GET `/admin/api/seasons/completeness`** — returns completeness data for all seasons:

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

`is_complete` uses `_is_season_complete`. Import it from `app.services.scheduler` inside the function body.

**POST `/admin/api/season/{season_id}/freeze`** — set `is_frozen = True`.

**POST `/admin/api/season/{season_id}/unfreeze`** — set `is_frozen = False`.

Both freeze/unfreeze return `{"ok": True, "season_id": season_id, "is_frozen": True/False}`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_season_freeze.py`:

```python
class TestAdminFreezeEndpoints:
    """Admin freeze/unfreeze/completeness endpoints."""

    def test_completeness_returns_list(self, admin_client, app):
        resp = admin_client.get("/admin/api/seasons/completeness")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_freeze_endpoint(self, admin_client, app):
        from app.services.database import get_database_service
        from app.models.db_models import Season

        db = get_database_service()
        with db.session_scope() as session:
            s = Season(id=6001, text="6001/xx", highlighted=False, is_frozen=False)
            session.add(s)

        resp = admin_client.post("/admin/api/season/6001/freeze")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["is_frozen"] is True

        with db.session_scope() as session:
            s = session.query(Season).filter(Season.id == 6001).one()
            assert s.is_frozen is True
            session.delete(s)

    def test_unfreeze_endpoint(self, admin_client, app):
        from app.services.database import get_database_service
        from app.models.db_models import Season

        db = get_database_service()
        with db.session_scope() as session:
            s = Season(id=6002, text="6002/xx", highlighted=False, is_frozen=True)
            session.add(s)

        resp = admin_client.post("/admin/api/season/6002/unfreeze")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["is_frozen"] is False

        with db.session_scope() as session:
            s = session.query(Season).filter(Season.id == 6002).one()
            assert s.is_frozen is False
            session.delete(s)

    def test_freeze_404_on_missing_season(self, admin_client, app):
        resp = admin_client.post("/admin/api/season/99999/freeze")
        assert resp.status_code == 404

    def test_completeness_contains_is_frozen_field(self, admin_client, app):
        from app.services.database import get_database_service
        from app.models.db_models import Season

        db = get_database_service()
        with db.session_scope() as session:
            s = Season(id=6003, text="6003/xx", highlighted=False, is_frozen=False)
            session.add(s)

        resp = admin_client.get("/admin/api/seasons/completeness")
        assert resp.status_code == 200
        data = resp.json()
        entry = next((d for d in data if d["season_id"] == 6003), None)
        assert entry is not None
        assert "is_frozen" in entry
        assert "games_total" in entry
        assert "games_finished" in entry
        assert "games_pct" in entry
        assert "is_complete" in entry

        with db.session_scope() as session:
            session.query(Season).filter(Season.id == 6003).delete()
```

- [ ] **Step 2: Run the failing tests**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/test_season_freeze.py::TestAdminFreezeEndpoints -v
```

Expected: FAIL — 404 or 405 (routes not defined yet).

- [ ] **Step 3: Add the three endpoints to `main.py`**

Add after the `admin_delete_season_layer` function (around line 1589):

```python
@app.get("/admin/api/seasons/completeness")
async def admin_seasons_completeness(_: None = Depends(require_admin)):
    """Return completeness data for all seasons."""
    from app.services.database import get_database_service
    from app.models.db_models import Season, Game
    from app.services.scheduler import _is_season_complete
    from sqlalchemy import func

    db = get_database_service()
    result = []
    with db.session_scope() as session:
        seasons = session.query(Season).order_by(Season.id.desc()).all()
        for s in seasons:
            games_total = (
                session.query(func.count(Game.id))
                .filter(Game.season_id == s.id)
                .scalar()
            ) or 0
            games_finished = (
                session.query(func.count(Game.id))
                .filter(Game.season_id == s.id, Game.status == "finished")
                .scalar()
            ) or 0
            games_pct = int(games_finished * 100 / games_total) if games_total else 0
            is_complete = _is_season_complete(session, s.id)
            result.append({
                "season_id": s.id,
                "text": s.text or str(s.id),
                "is_current": bool(s.highlighted),
                "is_frozen": bool(s.is_frozen),
                "games_total": games_total,
                "games_finished": games_finished,
                "games_pct": games_pct,
                "is_complete": is_complete,
            })
    return result


@app.post("/admin/api/season/{season_id}/freeze")
async def admin_freeze_season(season_id: int, _: None = Depends(require_admin)):
    """Mark a season as frozen — scheduler will skip it."""
    from app.services.database import get_database_service
    from app.models.db_models import Season

    db = get_database_service()
    with db.session_scope() as session:
        s = session.query(Season).filter(Season.id == season_id).first()
        if not s:
            raise HTTPException(status_code=404, detail=f"Season {season_id} not found")
        s.is_frozen = True
    return {"ok": True, "season_id": season_id, "is_frozen": True}


@app.post("/admin/api/season/{season_id}/unfreeze")
async def admin_unfreeze_season(season_id: int, _: None = Depends(require_admin)):
    """Unfreeze a season — scheduler will resume processing it."""
    from app.services.database import get_database_service
    from app.models.db_models import Season

    db = get_database_service()
    with db.session_scope() as session:
        s = session.query(Season).filter(Season.id == season_id).first()
        if not s:
            raise HTTPException(status_code=404, detail=f"Season {season_id} not found")
        s.is_frozen = False
    return {"ok": True, "season_id": season_id, "is_frozen": False}
```

- [ ] **Step 4: Run the tests**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest tests/test_season_freeze.py::TestAdminFreezeEndpoints -v
```

Expected: all 5 PASS.

- [ ] **Step 5: Run full test suite**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest --tb=short -q
```

Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add backend/app/main.py backend/tests/test_season_freeze.py
git commit -m "feat(admin): add seasons completeness, freeze, unfreeze API endpoints"
```

---

## Task 4: Admin UI — Completeness Column + Freeze/Unfreeze Buttons

**Files:**
- Modify: `backend/templates/admin/_tab_seasons.html`

### Context

The seasons card in `_tab_seasons.html` contains a `#seasons-container` div (line 11) that is populated by JavaScript. Look for `pullSeasons` or `loadSeasons` in the admin JS (either inline in the HTML file or in a separate static JS file).

The seasons list is loaded dynamically. The simplest approach: after the existing seasons load call, also fetch `/admin/api/seasons/completeness` and merge the data by `season_id`, then render the extra columns. Use HTMX or plain JavaScript (matching whatever pattern is already in use).

**Important:** Read the full HTML file and any referenced JS before editing, so you don't break existing functionality. Look for `pullSeasons` or the `#seasons-container` rendering logic.

- [ ] **Step 1: Read the full `_tab_seasons.html` to understand the JS structure**

```bash
cat /home/denny/Development/SwissUnihockeyStats/backend/templates/admin/_tab_seasons.html
```

Also check if there's a separate admin JS file:

```bash
ls /home/denny/Development/SwissUnihockeyStats/backend/static/
ls /home/denny/Development/SwissUnihockeyStats/backend/static/js/ 2>/dev/null || true
```

- [ ] **Step 2: Find where seasons are rendered in the JS**

Look for `seasons-container`, `renderSeason`, or the function that builds the seasons list HTML. Understand the existing row structure before modifying it.

- [ ] **Step 3: Add completeness column to the seasons table**

Modify the season row rendering to add:
- **Games**: `{games_finished}/{games_total}` (with ✓ when 100%)
- **Status**: `Frozen` badge (grey, `background:#30363d;color:#8b949e`) if `is_frozen`, `Complete` badge (green) if `is_complete` but not frozen, blank otherwise
- **Action**: "Freeze" button (if not frozen and `is_complete`) or "Unfreeze" button (if frozen)

Load completeness data from `GET /admin/api/seasons/completeness` once on page load (or when seasons are loaded) and merge by `season_id`.

The freeze/unfreeze buttons POST to the respective endpoint and trigger a page reload or re-fetch of the seasons data.

Example button handler:
```javascript
async function freezeSeason(seasonId) {
  await fetch(`/admin/api/season/${seasonId}/freeze`, {method: 'POST'});
  loadSeasons();  // or whatever the existing refresh function is called
}
async function unfreezeSeason(seasonId) {
  await fetch(`/admin/api/season/${seasonId}/unfreeze`, {method: 'POST'});
  loadSeasons();
}
```

- [ ] **Step 4: Verify the admin UI renders correctly**

Start the dev server and visit the admin page:

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Navigate to the admin dashboard → Seasons tab. Verify:
- Completeness columns appear
- Freeze/Unfreeze buttons appear and work (check Network tab for the POST calls)
- No JS errors in the console

- [ ] **Step 5: Run the full test suite one final time**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend
.venv/bin/pytest --tb=short -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add backend/templates/admin/_tab_seasons.html
git commit -m "feat(admin): add completeness column and freeze/unfreeze buttons to seasons admin UI"
```

# Admin Dashboard Overhaul — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Decompose the 2,325-line `admin.html` monolith into Jinja2 partials + ES JS modules + a single CSS file, add a Trends tab with historical Chart.js graphs, and align the admin visual style with the site theme.

**Architecture:** CSS extracted first (safest, no behaviour change), then shared JS utilities, then one tab extracted at a time (HTML partial + JS module), then the new Trends feature via TDD. Each tab extraction is validated by the existing test suite before moving on.

**Tech Stack:** Python/FastAPI, Jinja2, vanilla JS (ES modules), Chart.js (already bundled), SQLite/SQLAlchemy, pytest

---

## Critical Implementation Note — Inline Handlers

The existing HTML uses `onclick="functionName()"` inline event handlers. ES modules have their own scope — inline handlers cannot see module-level functions. **Fix:** at the bottom of each module, explicitly export public functions to `window`:

```js
// At the bottom of seasons.js (example)
Object.assign(window, {
  toggleSeason, setCurrentSeason, triggerIndex,
  triggerIndexTiered, triggerIndexEvents, deleteLayer,
  pullSeasons, runPurge,
});
```

Do this for every module. Do NOT change the HTML onclick attributes during the refactor — that's a separate cleanup pass.

---

## Task 1: Create directory structure

**Files:**
- Create: `backend/templates/admin/` (directory)
- Create: `backend/static/js/admin/` (directory)
- Create: `backend/static/css/admin.css` (empty for now)

**Step 1: Create directories and placeholder files**

```bash
mkdir -p backend/templates/admin
mkdir -p backend/static/js/admin
touch backend/static/css/admin.css
touch backend/static/js/admin/utils.js
touch backend/static/js/admin/stats.js
touch backend/static/js/admin/seasons.js
touch backend/static/js/admin/scheduling.js
touch backend/static/js/admin/settings.js
touch backend/static/js/admin/database.js
touch backend/static/js/admin/system.js
touch backend/static/js/admin/trends.js
```

**Step 2: Run existing tests to establish baseline**

```bash
cd backend && .venv/bin/pytest tests/test_admin_auth.py tests/test_admin_indexing.py -v
```

Expected: all pass.

**Step 3: Commit**

```bash
git add backend/templates/admin backend/static/js/admin backend/static/css/admin.css
git commit -m "chore: scaffold admin overhaul directory structure"
```

---

## Task 2: Extract CSS to admin.css + site theme alignment

**Files:**
- Modify: `backend/templates/admin.html` (remove `<style>` block lines 7–317, add links)
- Modify: `backend/static/css/admin.css` (fill with extracted + updated styles)

**Step 1: Read the current style block**

Read `backend/templates/admin.html` lines 7–317. This is the entire `<style>` block to extract.

**Step 2: Write admin.css**

Copy everything between `<style>` and `</style>` into `backend/static/css/admin.css`, then apply these theme updates:

- Replace all hard-coded `#238636` (GitHub green) → `var(--admin-ok, #2ea043)`
- Replace all hard-coded `#1f6feb` (GitHub blue) → `var(--admin-running, #1f6feb)`
- Replace all hard-coded `#f85149` (GitHub red) → `var(--swiss-red)`
- Replace hard-coded dark backgrounds (`#0d1117`, `#161b22`, `#21262d`) → keep as-is (admin-specific, not overriding public site)
- Add at the top of admin.css:

```css
/* ── Admin-specific custom properties ─────────────────── */
:root {
  --admin-ok:      #2ea043;
  --admin-running: #1f6feb;
  --admin-warn:    #d29922;
}
```

**Step 3: Update admin.html `<head>`**

Replace the `<style>…</style>` block (lines 7–317) with:

```html
  <link rel="stylesheet" href="/static/css/main.css?v=25">
  <link rel="stylesheet" href="/static/css/admin.css?v=1">
```

**Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_admin_auth.py tests/test_admin_indexing.py -v
```

Expected: all pass (CSS change is invisible to Python tests).

**Step 5: Manual smoke test**

Start the dev server (`uvicorn app.main:app --reload --port 8000`), open `/admin`, verify the page still looks correct with no unstyled elements.

**Step 6: Commit**

```bash
git add backend/templates/admin.html backend/static/css/admin.css
git commit -m "refactor: extract admin CSS to static/css/admin.css, align with site theme"
```

---

## Task 3: Create utils.js (shared JS utilities)

**Files:**
- Modify: `backend/static/js/admin/utils.js`

**Step 1: Write utils.js**

```js
// backend/static/js/admin/utils.js
// Shared utilities for all admin tab modules.

/**
 * Fetch JSON from url. Returns parsed JSON or null on error.
 * Shows a console.error on non-2xx responses.
 */
export async function fetchJSON(url, options = {}) {
  try {
    const r = await fetch(url, options);
    if (!r.ok) {
      console.error(`fetchJSON ${url}: HTTP ${r.status}`);
      return null;
    }
    return await r.json();
  } catch (e) {
    console.error(`fetchJSON ${url}:`, e);
    return null;
  }
}

/**
 * Poll fn every intervalMs. Pauses when browser tab is hidden.
 * Returns handle with .stop() method.
 */
export function poll(fn, intervalMs) {
  let id = null;
  const tick = () => { if (!document.hidden) fn(); };
  const start = () => { id = setInterval(tick, intervalMs); };
  const stop  = () => { if (id !== null) { clearInterval(id); id = null; } };
  document.addEventListener('visibilitychange', () => document.hidden ? stop() : start());
  start();
  return { stop };
}

/**
 * Append a colored line to a log container element.
 * level: 'ok' | 'warn' | 'error' | 'info'
 */
export function logLine(container, text, level = 'info') {
  if (!container) return;
  const span = document.createElement('span');
  span.className = `log-${level}`;
  span.textContent = text + '\n';
  container.appendChild(span);
  container.scrollTop = container.scrollHeight;
}

/** Format bytes as human-readable string (KB / MB / GB). */
export function formatBytes(n) {
  if (n == null) return '—';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
  return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
}

/** Format seconds as human-readable duration (e.g. 2m 34s). */
export function formatDuration(s) {
  if (s == null || isNaN(s)) return '—';
  s = Math.round(s);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return rem ? `${m}m ${rem}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm ? `${h}h ${rm}m` : `${h}h`;
}
```

**Step 2: No tests needed** — utils.js is pure logic with no DOM/network; it will be exercised by importing modules in later tasks.

**Step 3: Commit**

```bash
git add backend/static/js/admin/utils.js
git commit -m "feat: add admin shared JS utilities (fetchJSON, poll, logLine, formatBytes)"
```

---

## Task 4: Extract Seasons tab

**Files:**
- Create: `backend/templates/admin/_tab_seasons.html`
- Modify: `backend/static/js/admin/seasons.js`
- Modify: `backend/static/js/admin/stats.js`
- Modify: `backend/templates/admin.html`

**Step 1: Identify the Seasons tab HTML**

In `admin.html`, the Seasons tab is `<div class="tab-panel active" id="tab-cleanup">` (around line 641) through the closing `</div>` before `<!-- ══ Tab: System ══ -->`. Also extract the DB Health Alpine.js component that lives inside it.

**Step 2: Create `_tab_seasons.html`**

Cut that entire `<div class="tab-panel" id="tab-cleanup">…</div>` block and paste it as `backend/templates/admin/_tab_seasons.html`. Keep all HTML intact — no changes.

**Step 3: Create `_tab_scheduling.html` placeholder (just the opening tag)**

Leave it in admin.html for now — extract one tab per task.

**Step 4: Add include to admin.html**

Replace the cut block in `admin.html` with:

```html
  {% include "admin/_tab_seasons.html" %}
```

**Step 5: Extract Seasons JS to seasons.js**

The following functions from the `<script>` block belong to seasons.js. Move them (cut from admin.html script, paste into seasons.js):

```
renderSeasons()          line ~958
buildSeasonCard()        line ~972
toggleSeason()           line ~1093
buildCompletenessChip()  line ~1125
buildSeasonFreshSummary() line ~1153
setCurrentSeason()       line ~1176
pullSeasons()            line ~1190
triggerIndex()           line ~1212
triggerIndexTiered()     line ~1229
triggerIndexEvents()     line ~1249
deleteLayer()            line ~1274
runPurge()               line ~1883
toggleEl()               line ~1965
```

Add at the top:
```js
import { fetchJSON, logLine } from './utils.js';
```

Add at the bottom (inline handler exports):
```js
Object.assign(window, {
  toggleSeason, setCurrentSeason, triggerIndex,
  triggerIndexTiered, triggerIndexEvents, deleteLayer,
  pullSeasons, runPurge, toggleEl,
});
```

**Step 6: Extract Stats bar JS to stats.js**

```
loadStats()   line ~909
isSeasonFiltered()  (inline helper used inside loadStats)
```

`loadStats` calls `renderSeasons` — import it:

```js
import { fetchJSON } from './utils.js';
import { renderSeasons } from './seasons.js';
```

Add to bottom:
```js
// No window exports needed — loadStats called at boot and by setInterval
export { loadStats };
```

**Step 7: Update admin.html `<script>` block**

Add ES module imports at the very top of the `<script type="module">` block:

```html
<script type="module">
import { loadStats } from '/static/js/admin/stats.js';
import '/static/js/admin/seasons.js';
// … other imports added in later tasks
```

Change the `<script>` tag to `<script type="module">` (if not already).

Remove the now-moved functions from the inline script.

**Step 8: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_admin_auth.py tests/test_admin_indexing.py -v
```

**Step 9: Manual smoke test**

Open `/admin`, click through the Seasons tab — accordion opens/closes, Index buttons work, purge preview works.

**Step 10: Commit**

```bash
git add backend/templates/admin/_tab_seasons.html backend/static/js/admin/seasons.js backend/static/js/admin/stats.js backend/templates/admin.html
git commit -m "refactor: extract Seasons tab to partial + JS module"
```

---

## Task 5: Extract Scheduling tab

**Files:**
- Create: `backend/templates/admin/_tab_scheduling.html`
- Modify: `backend/static/js/admin/scheduling.js`
- Modify: `backend/templates/admin.html`

**Step 1: Identify Scheduling tab HTML**

`<div class="tab-panel" id="tab-scheduling">` (line ~362) through its closing `</div>`.

**Step 2: Create `_tab_scheduling.html`**

Cut and paste the block. Replace in admin.html with:
```html
  {% include "admin/_tab_scheduling.html" %}
```

**Step 3: Extract Scheduling JS to scheduling.js**

Functions to move:
```
const jobs = {}           (global state — move to module top)
pollJob()                 line ~1303
renderJobs()              line ~1385
the setInterval tick      line ~1448 (job elapsed timer)
clearDoneJobs()           line ~1456
stopJob()                 line ~1468
renderActivityTable()     line ~1486
loadScheduler()           line ~1584
renderScheduler()         line ~1623
schedSetEnabled()         line ~1722
loadSchedDiag()           line ~1973
```

Add at top:
```js
import { fetchJSON, poll, logLine } from './utils.js';

const jobs = {};
```

Add at bottom:
```js
Object.assign(window, {
  clearDoneJobs, stopJob, schedSetEnabled, loadSchedDiag,
});
export { loadScheduler, pollJob };
```

**Step 4: Update admin.html**

```js
import { loadScheduler } from '/static/js/admin/scheduling.js';
```

**Step 5: Run tests + smoke test**

```bash
cd backend && .venv/bin/pytest tests/test_admin_auth.py tests/test_admin_indexing.py -v
```

Manually verify: scheduler queue renders, active jobs panel updates, activity table loads.

**Step 6: Commit**

```bash
git add backend/templates/admin/_tab_scheduling.html backend/static/js/admin/scheduling.js backend/templates/admin.html
git commit -m "refactor: extract Scheduling tab to partial + JS module"
```

---

## Task 6: Extract Settings tab

**Files:**
- Create: `backend/templates/admin/_tab_settings.html`
- Modify: `backend/static/js/admin/settings.js`
- Modify: `backend/templates/admin.html`

**Step 1: Identify Settings tab HTML**

`<div class="tab-panel" id="tab-settings">` (line ~440) through its closing `</div>`.

**Step 2: Create `_tab_settings.html`**, replace with `{% include "admin/_tab_settings.html" %}`.

**Step 3: Extract Settings JS to settings.js**

Functions:
```
let _settingsDirty   line ~894 (global state flag)
schedSaveFilter()    line ~1733
schedClearFilter()   line ~1762
loadRenderingFilters() line ~1787
rfSave()             line ~1803
rfClear()            line ~1825
schedSaveTiers()     line ~1840
schedTrigger()       line ~1861
```

Add at top:
```js
import { fetchJSON } from './utils.js';
let _settingsDirty = false;
```

Add at bottom:
```js
Object.assign(window, {
  schedSaveFilter, schedClearFilter, schedSaveTiers,
  schedTrigger, rfSave, rfClear,
});
export { loadRenderingFilters };
```

**Step 4: Update admin.html**, import settings.js.

**Step 5: Run tests + smoke test** — verify tier inputs save, rendering filters round-trip.

**Step 6: Commit**

```bash
git add backend/templates/admin/_tab_settings.html backend/static/js/admin/settings.js backend/templates/admin.html
git commit -m "refactor: extract Settings tab to partial + JS module"
```

---

## Task 7: Extract Database tab

**Files:**
- Create: `backend/templates/admin/_tab_database.html`
- Modify: `backend/static/js/admin/database.js`
- Modify: `backend/templates/admin.html`

**Step 1:** Extract `<div class="tab-panel" id="tab-db">` block.

**Step 2:** Move functions:
```
loadDbInfo()    line ~2139
runVacuum()     line ~2204
runCleanup()    line ~2226
```

```js
import { fetchJSON, logLine, formatBytes } from './utils.js';
// … functions …
Object.assign(window, { runVacuum, runCleanup });
export { loadDbInfo };
```

**Step 3:** Run tests + smoke test — verify VACUUM button logs output, DB info table renders.

**Step 4: Commit**

```bash
git add backend/templates/admin/_tab_database.html backend/static/js/admin/database.js backend/templates/admin.html
git commit -m "refactor: extract Database tab to partial + JS module"
```

---

## Task 8: Extract System tab

**Files:**
- Create: `backend/templates/admin/_tab_system.html`
- Modify: `backend/static/js/admin/system.js`
- Modify: `backend/templates/admin.html`

**Step 1:** Extract `<div class="tab-panel" id="tab-system">` block.

**Step 2:** Move functions:
```
loadSystemStats()   line ~2033
```

```js
import { fetchJSON, formatBytes, formatDuration } from './utils.js';
// … function …
Object.assign(window, { loadSystemStats });
export { loadSystemStats };
```

**Step 3:** Run tests + smoke test — gauges render, refresh button works.

**Step 4: Commit**

```bash
git add backend/templates/admin/_tab_system.html backend/static/js/admin/system.js backend/templates/admin.html
git commit -m "refactor: extract System tab to partial + JS module"
```

---

## Task 9: Slim admin.html to base template

After Tasks 4–8, admin.html's `<script>` block should contain only:
- `setInterval` / `setTimeout` boot calls (which must remain global or be moved into a main init block)
- `switchTab()` function
- Any remaining global state not yet moved

**Step 1: Read what's left in admin.html's `<script>` block.** Everything still there that isn't a function definition belongs in a clean init block.

**Step 2: Create `backend/templates/admin/_stats_bar.html`**

Extract the stats bar HTML (the `<div>` containing totals chips, lines ~322–360) into its own partial.

**Step 3: Final admin.html structure should be:**

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Admin — SwissUnihockey Stats</title>
  <link rel="stylesheet" href="/static/css/main.css?v=25">
  <link rel="stylesheet" href="/static/css/admin.css?v=1">
  <script defer src="/static/js/vendor/alpine.min.js"></script>
</head>
<body>
  {% include "admin/_stats_bar.html" %}

  <div class="tab-bar">
    <!-- tab buttons here -->
  </div>

  {% include "admin/_tab_seasons.html" %}
  {% include "admin/_tab_scheduling.html" %}
  {% include "admin/_tab_settings.html" %}
  {% include "admin/_tab_database.html" %}
  {% include "admin/_tab_system.html" %}
  {% include "admin/_tab_trends.html" %}

  <script type="module">
    import { loadStats } from '/static/js/admin/stats.js';
    import { loadScheduler } from '/static/js/admin/scheduling.js';
    import { loadRenderingFilters } from '/static/js/admin/settings.js';
    import { loadDbInfo } from '/static/js/admin/database.js';
    import { loadSystemStats } from '/static/js/admin/system.js';
    import '/static/js/admin/seasons.js';
    import '/static/js/admin/trends.js';

    // Boot sequence
    loadStats();
    loadScheduler();
    loadRenderingFilters();
    setTimeout(loadDbInfo, 2000);

    // Polling
    import { poll } from '/static/js/admin/utils.js';
    poll(loadStats,       30000);
    poll(loadScheduler,   10000);
    poll(loadDbInfo,      30000);
    poll(loadSystemStats, 15000);

    // switchTab lives here — it's truly global UI logic
    function switchTab(name) { /* … */ }
    window.switchTab = switchTab;
  </script>
</body>
</html>
```

**Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_admin_auth.py tests/test_admin_indexing.py -v
```

**Step 5: Full manual smoke test** — click every tab, every button. Confirm nothing broken.

**Step 6: Commit**

```bash
git add backend/templates/admin.html backend/templates/admin/_stats_bar.html
git commit -m "refactor: slim admin.html to ~100-line base template with includes"
```

---

## Task 10: Trends — DB table + migration

**Files:**
- Modify: `backend/app/services/database.py` (add `admin_stats_snapshots` table creation to `_run_sqlite_migrations`)
- Create: `backend/tests/test_admin_trends_migration.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_admin_trends_migration.py
"""Verify admin_stats_snapshots table is created idempotently by migration."""
import os
os.environ.setdefault("DATABASE_PATH", ":memory:")
os.environ.setdefault("ADMIN_PIN", "testpin")
os.environ.setdefault("SESSION_SECRET", "test-secret-key-32-chars-xxxxxxxx")
os.environ.setdefault("DEBUG", "true")

from sqlalchemy import text

def test_admin_stats_snapshots_table_exists():
    from app.services.database import DatabaseService
    db = DatabaseService.__new__(DatabaseService)
    db.database_url = "sqlite:///:memory:"
    db._initialized = False
    db.initialize()

    with db.engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ))}
    assert "admin_stats_snapshots" in tables

def test_migration_is_idempotent():
    """Running migration twice must not raise."""
    from app.services.database import DatabaseService
    db = DatabaseService.__new__(DatabaseService)
    db.database_url = "sqlite:///:memory:"
    db._initialized = False
    db.initialize()
    db._run_sqlite_migrations()  # second call — must not raise
```

**Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/pytest tests/test_admin_trends_migration.py -v
```

Expected: FAIL — `admin_stats_snapshots` does not exist yet.

**Step 3: Add migration to database.py**

In `_run_sqlite_migrations`, after the existing players migration block, add:

```python
# ── Create admin_stats_snapshots if it doesn't exist ─────────────────
conn.execute(text("""
    CREATE TABLE IF NOT EXISTS admin_stats_snapshots (
        ts               DATETIME PRIMARY KEY,
        db_size_bytes    INTEGER,
        games            INTEGER,
        players          INTEGER,
        events           INTEGER,
        player_stats     INTEGER,
        jobs_run         INTEGER,
        jobs_errors      INTEGER,
        avg_job_duration_s REAL
    )
"""))
```

**Step 4: Run test to verify it passes**

```bash
cd backend && .venv/bin/pytest tests/test_admin_trends_migration.py -v
```

Expected: 2 passed.

**Step 5: Run full test suite**

```bash
cd backend && .venv/bin/pytest tests/test_admin_auth.py tests/test_admin_indexing.py tests/test_admin_trends_migration.py -v
```

**Step 6: Commit**

```bash
git add backend/app/services/database.py backend/tests/test_admin_trends_migration.py
git commit -m "feat: add admin_stats_snapshots table via idempotent migration"
```

---

## Task 11: Trends — snapshot writer + scheduler integration

**Files:**
- Modify: `backend/app/main.py` (add `_write_stats_snapshot()` function)
- Modify: `backend/app/services/scheduler.py` (call snapshot writer every 6 hours in background loop)
- Create: `backend/tests/test_admin_stats_history.py` (partial — snapshot write tests)

**Step 1: Write the failing tests (snapshot insert)**

```python
# backend/tests/test_admin_stats_history.py
"""Tests for admin stats snapshot writes and history API."""
import os
os.environ.setdefault("DATABASE_PATH", ":memory:")
os.environ.setdefault("ADMIN_PIN", "testpin")
os.environ.setdefault("SESSION_SECRET", "test-secret-key-32-chars-xxxxxxxx")
os.environ.setdefault("DEBUG", "true")

from sqlalchemy import text
from datetime import datetime, timezone

def _make_db():
    from app.services.database import DatabaseService
    db = DatabaseService.__new__(DatabaseService)
    db.database_url = "sqlite:///:memory:"
    db._initialized = False
    db.initialize()
    return db

def test_write_stats_snapshot_inserts_row():
    from app.main import _write_stats_snapshot
    db = _make_db()
    _write_stats_snapshot(db, jobs_run=3, jobs_errors=1, avg_job_duration_s=42.5)
    with db.engine.connect() as conn:
        rows = list(conn.execute(text("SELECT * FROM admin_stats_snapshots")))
    assert len(rows) == 1
    row = rows[0]._mapping
    assert row["jobs_run"] == 3
    assert row["jobs_errors"] == 1
    assert abs(row["avg_job_duration_s"] - 42.5) < 0.01

def test_write_stats_snapshot_populates_entity_counts():
    from app.main import _write_stats_snapshot
    db = _make_db()
    _write_stats_snapshot(db, jobs_run=0, jobs_errors=0, avg_job_duration_s=0)
    with db.engine.connect() as conn:
        row = dict(list(conn.execute(text("SELECT * FROM admin_stats_snapshots")))[0]._mapping)
    # games/players/events default to 0 in empty DB — just check keys present
    for col in ("db_size_bytes", "games", "players", "events", "player_stats"):
        assert col in row
```

**Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_admin_stats_history.py::test_write_stats_snapshot_inserts_row -v
```

Expected: FAIL — `_write_stats_snapshot` not yet defined.

**Step 3: Add `_write_stats_snapshot` to main.py**

Find a good location in `backend/app/main.py` near the other admin utility functions. Add:

```python
def _write_stats_snapshot(
    db_service,
    jobs_run: int,
    jobs_errors: int,
    avg_job_duration_s: float,
) -> None:
    """Write one row to admin_stats_snapshots. Called by scheduler every 6h."""
    import os
    from sqlalchemy import text as _text
    from datetime import datetime, timezone

    # Collect entity counts from DB
    with db_service.session_scope() as session:
        games        = session.query(func.count(Game.id)).scalar() or 0
        players      = session.query(func.count(Player.person_id)).scalar() or 0
        events       = session.query(func.count(GameEvent.id)).scalar() or 0
        player_stats = session.query(func.count(PlayerStatistics.id)).scalar() or 0

    # DB file size (bytes)
    db_path = settings.DATABASE_PATH
    try:
        db_size = os.path.getsize(db_path) if db_path and db_path != ":memory:" else 0
    except OSError:
        db_size = 0

    ts = datetime.now(timezone.utc).replace(microsecond=0)

    with db_service.engine.connect() as conn:
        conn.execute(_text("""
            INSERT OR REPLACE INTO admin_stats_snapshots
            (ts, db_size_bytes, games, players, events, player_stats,
             jobs_run, jobs_errors, avg_job_duration_s)
            VALUES (:ts, :db_size, :games, :players, :events, :player_stats,
                    :jobs_run, :jobs_errors, :avg_dur)
        """), {
            "ts": ts, "db_size": db_size, "games": games,
            "players": players, "events": events,
            "player_stats": player_stats, "jobs_run": jobs_run,
            "jobs_errors": jobs_errors, "avg_dur": avg_job_duration_s,
        })
        conn.commit()
```

Make sure `Game`, `Player`, `GameEvent`, `PlayerStatistics`, `func` are already imported at the top of `main.py`. They likely are since it's the main routes file — check and add any missing.

**Step 4: Integrate with scheduler**

In `backend/app/services/scheduler.py`, find the background watch loop (the `asyncio` task or thread that runs continuously). Add a 6-hour snapshot trigger:

```python
# Near the top of the scheduler background loop, add tracking vars:
_last_snapshot_ts = 0.0
_SNAPSHOT_INTERVAL_S = 6 * 3600

# Inside the loop body:
import time
now = time.monotonic()
if now - _last_snapshot_ts >= _SNAPSHOT_INTERVAL_S:
    try:
        completed = [j for j in self._history if j.get("status") == "done"]
        recent = [j for j in completed if j.get("duration_s") is not None]
        avg_dur = (sum(j["duration_s"] for j in recent) / len(recent)) if recent else 0.0
        errors  = sum(1 for j in completed if j.get("error"))
        _write_stats_snapshot(
            self.db_service,
            jobs_run=len(completed),
            jobs_errors=errors,
            avg_job_duration_s=avg_dur,
        )
    except Exception as exc:
        logger.warning("Failed to write stats snapshot: %s", exc)
    _last_snapshot_ts = now
```

Import `_write_stats_snapshot` from `app.main` — or better, move it to a new `app/services/stats_snapshot.py` module to avoid circular imports (main.py imports scheduler.py; scheduler.py must not import main.py).

**Circular import fix:** Create `backend/app/services/stats_snapshot.py`:
```python
# backend/app/services/stats_snapshot.py
"""Write periodic admin stats snapshots to admin_stats_snapshots table."""
import os, logging
from datetime import datetime, timezone
from sqlalchemy import func, text

logger = logging.getLogger(__name__)

def write_stats_snapshot(db_service, jobs_run, jobs_errors, avg_job_duration_s):
    # … same body as above, but import models here locally …
    from app.models.db_models import Game, Player, GameEvent, PlayerStatistics
    from app.config import get_settings
    settings = get_settings()
    # … rest of function …
```

Then import it in both `main.py` (for the API handler that might call it manually) and `scheduler.py`.

**Step 5: Run snapshot tests**

```bash
cd backend && .venv/bin/pytest tests/test_admin_stats_history.py -v
```

Expected: 2 passed.

**Step 6: Commit**

```bash
git add backend/app/services/stats_snapshot.py backend/app/services/scheduler.py backend/app/main.py backend/tests/test_admin_stats_history.py
git commit -m "feat: add _write_stats_snapshot() and scheduler 6h integration"
```

---

## Task 12: Trends — API endpoint + tests

**Files:**
- Modify: `backend/app/main.py` (add `GET /admin/api/stats/history`)
- Modify: `backend/tests/test_admin_stats_history.py` (add API tests)

**Step 1: Write failing API tests**

Append to `test_admin_stats_history.py`:

```python
def test_stats_history_returns_list(admin_client):
    r = admin_client.get("/admin/api/stats/history?days=30")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)

def test_stats_history_row_shape(admin_client):
    """Each row must have the expected keys."""
    # First insert a snapshot
    from app.main import _write_stats_snapshot
    from app.services.database import get_database_service
    _write_stats_snapshot(get_database_service(), jobs_run=1, jobs_errors=0, avg_job_duration_s=10.0)
    r = admin_client.get("/admin/api/stats/history?days=30")
    assert r.status_code == 200
    rows = r.json()
    if rows:
        row = rows[0]
        for key in ("ts", "db_size_bytes", "games", "players", "events",
                    "player_stats", "jobs_run", "jobs_errors", "avg_job_duration_s"):
            assert key in row, f"Missing key: {key}"

def test_stats_history_days_filter(admin_client):
    """?days=0 must return an empty list (no future rows)."""
    r = admin_client.get("/admin/api/stats/history?days=0")
    assert r.status_code == 200
    assert r.json() == []
```

Note: `admin_client` fixture is in `conftest.py` — check if it exists, else use the pattern from `test_admin_auth.py`.

**Step 2: Run to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_admin_stats_history.py::test_stats_history_returns_list -v
```

Expected: FAIL — endpoint not yet defined.

**Step 3: Add endpoint to main.py**

Add after existing admin API routes:

```python
@app.get("/admin/api/stats/history")
async def admin_stats_history(
    days: int = 30,
    _: None = Depends(require_admin),
):
    """Return admin_stats_snapshots rows for the last `days` days, newest first."""
    from sqlalchemy import text
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with db_service.engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ts, db_size_bytes, games, players, events, player_stats,
                   jobs_run, jobs_errors, avg_job_duration_s
            FROM admin_stats_snapshots
            WHERE ts >= :cutoff
            ORDER BY ts DESC
        """), {"cutoff": cutoff}).fetchall()
    return [dict(r._mapping) for r in rows]
```

**Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_admin_stats_history.py -v
```

Expected: all pass.

**Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_admin_stats_history.py
git commit -m "feat: add GET /admin/api/stats/history endpoint for trend data"
```

---

## Task 13: Trends — template + JS

**Files:**
- Create: `backend/templates/admin/_tab_trends.html`
- Modify: `backend/static/js/admin/trends.js`
- Modify: `backend/templates/admin.html` (add Trends tab button + include)

**Step 1: Create `_tab_trends.html`**

```html
<!-- backend/templates/admin/_tab_trends.html -->
<div class="tab-panel" id="tab-trends">
  <div class="trends-toolbar">
    <span class="section-title">Historical Trends</span>
    <div class="trends-range-btns">
      <button class="btn btn-sm" onclick="setTrendsRange(7)"  id="tr-7d">7d</button>
      <button class="btn btn-sm active" onclick="setTrendsRange(30)" id="tr-30d">30d</button>
      <button class="btn btn-sm" onclick="setTrendsRange(90)" id="tr-90d">90d</button>
    </div>
  </div>
  <div class="trends-grid">
    <div class="trend-card">
      <h3>DB Size</h3>
      <canvas id="chart-db-size"></canvas>
    </div>
    <div class="trend-card">
      <h3>Record Counts</h3>
      <canvas id="chart-records"></canvas>
    </div>
    <div class="trend-card">
      <h3>Jobs Run vs. Errors</h3>
      <canvas id="chart-jobs"></canvas>
    </div>
    <div class="trend-card">
      <h3>Avg Job Duration</h3>
      <canvas id="chart-duration"></canvas>
    </div>
  </div>
  <p class="trends-hint">Snapshots taken every 6 hours by the scheduler.</p>
</div>
```

**Step 2: Add Trends tab CSS to admin.css**

```css
/* ── Trends tab ─────────────────────────────────────── */
.trends-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}
.trends-range-btns { display: flex; gap: .4rem; }
.trends-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}
@media (max-width: 700px) { .trends-grid { grid-template-columns: 1fr; } }
.trend-card {
  background: var(--swiss-dark);
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 1rem;
}
.trend-card h3 {
  margin: 0 0 .75rem;
  font-size: .85rem;
  color: var(--swiss-white);
  opacity: .7;
  text-transform: uppercase;
  letter-spacing: .05em;
}
.trends-hint {
  font-size: .75rem;
  opacity: .5;
  margin-top: .75rem;
  text-align: center;
}
```

**Step 3: Write trends.js**

```js
// backend/static/js/admin/trends.js
import { fetchJSON } from './utils.js';

let _trendsRange = 30;
let _charts = {};

async function loadTrends() {
  const data = await fetchJSON(`/admin/api/stats/history?days=${_trendsRange}`);
  if (!data || data.length === 0) return;

  const labels = data.map(r => r.ts.slice(0, 16).replace('T', ' '));

  _renderLine('chart-db-size', labels,
    [{ label: 'DB Size (MB)', data: data.map(r => ((r.db_size_bytes || 0) / 1024 / 1024).toFixed(2)),
       borderColor: 'var(--swiss-red)', tension: 0.3 }]);

  _renderLine('chart-records', labels, [
    { label: 'Games',   data: data.map(r => r.games),        borderColor: '#58a6ff', tension: 0.3 },
    { label: 'Players', data: data.map(r => r.players),      borderColor: '#3fb950', tension: 0.3 },
    { label: 'Events',  data: data.map(r => r.events),       borderColor: '#d29922', tension: 0.3 },
  ]);

  _renderBar('chart-jobs', labels, [
    { label: 'Jobs Run',   data: data.map(r => r.jobs_run),    backgroundColor: '#1f6feb88' },
    { label: 'Errors',     data: data.map(r => r.jobs_errors), backgroundColor: 'var(--swiss-red)88' },
  ]);

  _renderLine('chart-duration', labels,
    [{ label: 'Avg Duration (s)', data: data.map(r => r.avg_job_duration_s?.toFixed(1) ?? 0),
       borderColor: '#3fb950', tension: 0.3 }]);
}

function _chartDefaults() {
  return {
    responsive: true,
    animation: false,
    plugins: { legend: { labels: { color: '#c9d1d9', font: { size: 11 } } } },
    scales: {
      x: { ticks: { color: '#8b949e', maxTicksLimit: 8 }, grid: { color: '#21262d' } },
      y: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } },
    },
  };
}

function _renderLine(canvasId, labels, datasets) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  if (_charts[canvasId]) _charts[canvasId].destroy();
  _charts[canvasId] = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: _chartDefaults(),
  });
}

function _renderBar(canvasId, labels, datasets) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  if (_charts[canvasId]) _charts[canvasId].destroy();
  _charts[canvasId] = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets },
    options: _chartDefaults(),
  });
}

function setTrendsRange(days) {
  _trendsRange = days;
  document.querySelectorAll('.trends-range-btns .btn').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById(`tr-${days}d`);
  if (btn) btn.classList.add('active');
  loadTrends();
}

// Load when Trends tab is activated
document.addEventListener('DOMContentLoaded', () => {
  // Hook into existing switchTab function
  const origSwitch = window.switchTab;
  window.switchTab = function(name) {
    origSwitch(name);
    if (name === 'trends') loadTrends();
  };
});

Object.assign(window, { setTrendsRange });
```

**Step 4: Add Trends tab button to admin.html tab bar**

Find the tab buttons section, add after System:
```html
<button class="tab-btn" id="tabBtn-trends" onclick="switchTab('trends')">📈 Trends</button>
```

Add include at bottom of tab panels section:
```html
{% include "admin/_tab_trends.html" %}
```

**Step 5: Verify Chart.js is available**

Check that `admin.html` or `base.html` already loads Chart.js. If not, add:
```html
<script src="/static/js/vendor/chart.umd.min.js"></script>
```
And download Chart.js UMD build to `backend/static/js/vendor/chart.umd.min.js`.

**Step 6: Manual smoke test**

- Click Trends tab — four chart canvases render (empty if no snapshots yet)
- 7d / 30d / 90d buttons switch range
- After manually inserting a test snapshot via sqlite3, charts update on range switch

**Step 7: Run all tests**

```bash
cd backend && .venv/bin/pytest tests/test_admin_auth.py tests/test_admin_indexing.py tests/test_admin_trends_migration.py tests/test_admin_stats_history.py -v
```

Expected: all pass.

**Step 8: Commit**

```bash
git add backend/templates/admin/_tab_trends.html backend/static/js/admin/trends.js backend/static/css/admin.css backend/templates/admin.html
git commit -m "feat: add Trends tab with Chart.js historical graphs"
```

---

## Task 14: Final verification + cleanup

**Step 1: Run full test suite**

```bash
cd backend && .venv/bin/pytest -v
```

Confirm: `test_admin_auth`, `test_admin_indexing`, `test_admin_trends_migration`, `test_admin_stats_history`, `test_player_game_stats` all pass. The 15 pre-existing failures in `test_routes` / `test_stats_service` / `test_api_endpoints` are unrelated — ignore them.

**Step 2: Line count check**

```bash
wc -l backend/templates/admin.html
```

Expected: < 150 lines (was 2,325).

```bash
wc -l backend/static/css/admin.css backend/static/js/admin/*.js
```

Should show clear per-file distribution.

**Step 3: Smoke test checklist**

Go through every tab manually:
- [ ] Seasons: accordion opens, Index button starts job, job log streams, Set Current works
- [ ] Scheduling: queue renders, Enable/Disable toggles, Diagnostics expand
- [ ] Settings: save tier limits, save rendering filters, round-trip correctly
- [ ] Database: VACUUM button logs output, DB file sizes show
- [ ] System: gauges render, refresh updates values
- [ ] Trends: tab loads, range buttons switch, charts render data

**Step 4: Final commit**

```bash
git add -A
git commit -m "refactor: complete admin dashboard overhaul — partials, JS modules, Trends tab"
```

---

## Smoke Test Reference (for each tab after Task 9)

| Tab | Key interactions to verify |
|-----|---------------------------|
| Seasons | Accordion expand/collapse, Index button → job starts, log streams, Set Current, Delete Layer |
| Scheduling | Scheduler status badge, Enable/Disable, activity table loads, active jobs panel |
| Settings | Tier limit saves, rendering filter save/clear round-trips |
| Database | DB size table renders, VACUUM runs and logs, Cleanup runs |
| System | All 3 gauges show values, Refresh updates |
| Trends | 4 charts render, range buttons work |

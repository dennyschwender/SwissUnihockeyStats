# Admin Dashboard Overhaul — Design Document

**Date:** 2026-03-09
**Status:** Approved

---

## Goals

1. **Code quality (primary):** Decompose the 2,325-line `admin.html` monolith into maintainable Jinja2 partials, a static CSS file, and modular ES JS files.
2. **Missing feature:** Add a Trends tab with historical Chart.js graphs (DB size, record counts, job health over time).
3. **UX polish (byproduct):** Admin visual style aligns with the site's existing design system.

---

## Approach: Jinja2 partials + static JS modules

Split `admin.html` into a base template + one partial per tab. Extract all JS into `static/js/admin/` as ES modules. Extract CSS to `static/css/admin.css` following the site theme. Add trend graphs backed by a new SQLite snapshot table.

---

## File Structure

```
backend/
├── templates/
│   ├── admin.html                   # ~100 lines: base layout, tab nav, {% include %} calls
│   ├── admin_login.html             # Unchanged
│   └── admin/
│       ├── _stats_bar.html          # Totals bar (always visible)
│       ├── _tab_seasons.html        # Seasons accordion, Danger Zone, DB Health
│       ├── _tab_scheduling.html     # Queue, activity log, diagnostics, active jobs
│       ├── _tab_trends.html         # NEW — historical trend graphs
│       ├── _tab_settings.html       # Scheduler settings, rendering filters
│       ├── _tab_database.html       # DB file sizes, PRAGMA info, maintenance
│       └── _tab_system.html         # CPU/memory/disk gauges, process info
├── static/
│   ├── css/
│   │   └── admin.css                # All admin-specific styles
│   └── js/
│       └── admin/
│           ├── utils.js             # Shared: fetchJSON, poll, logLine, formatBytes, formatDuration
│           ├── stats.js             # Totals bar + per-season stats polling
│           ├── seasons.js           # Seasons accordion, task buttons, purge
│           ├── scheduling.js        # Scheduler control, queue, activity log, jobs panel
│           ├── trends.js            # NEW — Chart.js graphs
│           ├── settings.js          # Scheduler settings, rendering filters
│           ├── database.js          # DB info, VACUUM, cleanup
│           └── system.js            # System metrics polling
```

---

## Section 1: Template Decomposition

`admin.html` is reduced to ~100 lines containing:
- `<link>` to `main.css` and `admin.css`
- Tab navigation bar
- `{% include "admin/_tab_*.html" %}` for each tab
- `<script type="module">` imports for each JS file

Each partial contains only HTML structure — no `<style>` blocks, no inline `<script>` blocks.

---

## Section 2: JS Shared Utilities (`utils.js`)

Four shared patterns extracted from duplicated code across all tabs:

```js
// Replaces ~20 identical fetch() blocks
async function fetchJSON(url, options = {})

// Returns handle with .stop(); pauses when tab is not visible (IntersectionObserver / visibilityState)
function poll(fn, intervalMs)

// Applies ok/warn/error/info CSS class to log output containers
function logLine(container, text, level)

// Formatting helpers
function formatBytes(n)
function formatDuration(s)
```

Each tab JS file imports only what it needs:
```js
import { fetchJSON, poll, logLine, formatBytes } from './utils.js';
```

`poll()` uses `document.visibilityState` to pause background polling when the browser tab is hidden — reducing multi-tab CPU waste beyond the interval increases already applied.

---

## Section 3: Trends Tab (new feature)

### Data Model

New SQLite table `admin_stats_snapshots` (created by idempotent migration on startup):

| Column | Type | Description |
|---|---|---|
| `ts` | DATETIME PK | Snapshot timestamp |
| `db_size_bytes` | INTEGER | SQLite file size |
| `games` | INTEGER | Total game rows |
| `players` | INTEGER | Total player rows |
| `events` | INTEGER | Total game_event rows |
| `player_stats` | INTEGER | Total player_statistics rows |
| `jobs_run` | INTEGER | Jobs completed since last snapshot |
| `jobs_errors` | INTEGER | Jobs with errors since last snapshot |
| `avg_job_duration_s` | REAL | Average job duration (seconds) |

### Snapshot Writes

New `_write_stats_snapshot()` function called by the scheduler's existing background loop every 6 hours. No new thread required.

### API Endpoint

`GET /admin/api/stats/history?days=30` — returns last N days of snapshots as JSON array, newest first.

### UI

Four Chart.js line graphs in a 2×2 grid on the new Trends tab:
1. **DB size** over time
2. **Record counts** (games, players, events) — multi-line
3. **Jobs run vs. errors** per day — bar + line combo
4. **Avg job duration** over time

Time range selector: **7d / 30d / 90d** toggle buttons.

---

## Section 4: CSS (`admin.css`)

`admin.html` links both `main.css` (site-wide variables, buttons, chips, Inter font) and `admin.css` (admin-specific layout only).

`admin.css` sections:
```css
/* 1. CSS custom properties (admin-specific: --admin-ok, --admin-running) */
/* 2. Base layout & tab nav */
/* 3. Stats bar */
/* 4. Seasons accordion */
/* 5. Job panels & log output */
/* 6. Scheduling tab */
/* 7. Trends tab */
/* 8. Settings & forms */
/* 9. Database tab */
/* 10. System gauges */
/* 11. Utility classes (badges, buttons, chips) */
```

**Rules:**
- No inline `style=""` attributes in any partial
- All colors via CSS custom properties from `main.css` (`--swiss-red`, `--swiss-white`, `--swiss-dark`) or local `admin.css` vars
- Current GitHub-dark palette replaced by site's red/white/dark scheme
- Status colors: errors → `--swiss-red`, ok → `--admin-ok` (#2ea043), running → `--admin-running` (#1f6feb)

---

## Section 5: Testing

**Existing (must stay green):**
- `test_admin_auth.py` — PIN auth, rate limiting, sessions
- `test_admin_indexing.py` — all 24 admin API endpoints

**New:**

| File | Coverage |
|---|---|
| `test_admin_stats_history.py` | `_write_stats_snapshot()` inserts correct columns; `GET /admin/api/stats/history` returns correct shape; `?days=` filter works |
| `test_admin_trends_migration.py` | `admin_stats_snapshots` table created idempotently on startup |

**No JS tests** — no JS test infrastructure in this project; JS refactor validated manually via smoke-test checklist (every button/panel per tab).

---

## Out of Scope

- Job retry/restart UI
- Scheduler bulk-trigger UI
- Auth audit log
- Per-season scheduler overrides
- CSS framework introduction
- Alpine.js rewrite of all tabs

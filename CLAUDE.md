# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FastAPI PWA displaying Swiss floorball (unihockey) statistics. Fetches data from the official Swiss Unihockey API, stores it in SQLite, and serves it via Jinja2 templates with HTMX/Alpine.js. Multi-language (de, en, fr, it), mobile-first.

## Commands

All commands run from `backend/` unless noted. Use `.venv/bin/` binaries (system Python has no uvicorn/pytest).

```bash
# Setup
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env  # then set SESSION_SECRET and ADMIN_PIN

# Dev server
.venv/bin/uvicorn app.main:app --reload --port 8000

# Tests
.venv/bin/pytest                                    # all tests
.venv/bin/pytest tests/test_scheduler.py            # single file
.venv/bin/pytest tests/test_scheduler.py::test_foo  # single test
.venv/bin/pytest --cov=app --cov-report=term        # with coverage

# Linting
.venv/bin/black app/ tests/
.venv/bin/flake8 app/ tests/ --max-line-length=120

# Data indexing (populate DB from API)
.venv/bin/python manage.py index-clubs-path --season 2025
.venv/bin/python manage.py index-leagues-path --season 2025 --events
```

## Architecture

### Request Flow

```
Browser → FastAPI (main.py) → page route /{locale}/{page}
                            → Jinja2 template (templates/)
                            → stats_service.py (DB queries via SQLAlchemy)

Browser → FastAPI (main.py) → /api/v1/* → api/v1/ routers
                                         → SwissUnihockeyClient (API + file cache)
```

### Data Flow

The app separates live API proxying (for JSON endpoints) from indexed DB data (for page routes):

- **Page routes** (`main.py`) query SQLite via `stats_service.py` — fast, no API calls.
- **JSON API** (`api/v1/`) proxy to SwissUnihockey API via `services/api_client.py` with file-based caching.
- **Background indexer** (`services/data_indexer.py`) populates SQLite on a schedule.

### Key Services

| File | Purpose |
|---|---|
| `services/database.py` | SQLAlchemy engine + `session_scope()` context manager, idempotent migrations |
| `services/data_indexer.py` | Hierarchical API → DB sync (clubs→teams→players, leagues→games→events) |
| `services/scheduler.py` | In-memory policy-based background scheduler |
| `services/api_client.py` | `SwissUnihockeyClient` with file-based TTL cache |
| `services/stats_service.py` | All SQLAlchemy queries for page rendering |
| `services/repair_service.py` | Fix stuck/stale `SyncStatus` rows, force re-index |

### Database

SQLite with WAL mode. `busy_timeout=30000` is set **before** `journal_mode=WAL` (order matters). `NullPool` for file-based SQLite (each `session_scope()` gets its own connection); `StaticPool` for `:memory:` tests.

**Season-scoped composite keys**: `Club(id, season_id)`, `Team(id, season_id)`, and their FKs. Many entities exist multiple times across seasons.

**SyncStatus**: tracks sync state for every indexed entity (`pending` / `in_progress` / `completed` / `failed`). The scheduler reads this to decide what to re-fetch.

### session_scope Anti-Pattern

Never manually commit inside `session_scope()` — the context manager commits on exit. Never swallow exceptions inside the `with` block (leaves session in `PendingRollbackError`):

```python
# WRONG
with db.session_scope() as session:
    try:
        session.commit()       # manual commit
    except Exception:
        logger.error(...)      # swallows error → PendingRollbackError on exit

# CORRECT
try:
    with db.session_scope() as session:
        ...                    # session_scope commits on exit
except Exception as exc:
    logger.error(...)
```

`_mark_sync_complete(session, ...)` calls `session.commit()` internally — don't wrap it in another commit.

### Data Indexer: Two-Phase Player Stats

Player game stats use a two-phase approach to avoid holding SQLite write locks during slow API calls:

- **Phase 1**: Concurrent API fetches (`ThreadPoolExecutor`, up to `max_concurrent` workers). No DB writes.
- **Phase 2**: Batched DB writes at `_PHASE2_BATCH_SIZE=300` players per `session_scope()`. Each batch holds the write lock for seconds, not minutes.
- **Checkpoint resume**: Per-player `SyncStatus` (`player_game_stats:{pid}:{season}`) allows restarts to skip completed players.

**Do not increase `max_concurrent` above 2 for SQLite** — concurrent writes cause lock timeouts.

### Scheduler

Policy-based in-memory scheduler (`services/scheduler.py`). Defines `POLICIES` list with (entity_type, max_age, priority, scope). Scope is `"global"` (once per run) or `"season"` (repeated per indexed season). Nightly jobs snap to 03:00 UTC via `_snap_to_hour()`. Ticks every `TICK_SECONDS`; reads SyncStatus to find stale entities and submits jobs to admin.

### League Tiers

`LEAGUE_TIERS` in `data_indexer.py` maps API `league_id` → tier (1=NLA, 2=NLB, 3=1.Liga, ..., 6=Regional). Only tiers 1–2 support the `/api/teams/{id}/players` endpoint. Use `--max-tier` flag on CLI commands to limit scope.

## Adding a New Page

1. Create `backend/templates/<page>.html` extending `base.html`
2. Add route in `backend/app/main.py` using `/{locale}/<page>` pattern
3. Add translation keys to all four `backend/locales/*/messages.json` files
4. Add nav/footer link in `backend/templates/base.html` if needed

## i18n

All user-facing strings live in `backend/locales/{locale}/messages.json`. Access in templates via `{{ t.section.key }}`. Load in routes: `get_translations(locale)` from `app.lib.i18n`. Supported locales: `de`, `en`, `fr`, `it`.

## Code Conventions

- Page routes: `/{locale}/{page}` — template context always includes `locale` and `t`
- Business logic in `services/`; routes in `main.py`
- Static files at `/static/` with cache-busting query strings

## Tests

- `backend/tests/` — 23 test modules, pytest with `asyncio_mode = auto`
- `conftest.py` provides session-scoped `app`/`client`/`admin_client` fixtures with mocked API client and `:memory:` SQLite
- `DATABASE_PATH=:memory:` uses `StaticPool`; file-based uses `NullPool`
- Admin auth in tests: POST to `/admin/login` with `pin=testpin`

## Environment

| Variable | Description |
|---|---|
| `ADMIN_PIN` | Admin dashboard PIN (required in production) |
| `SESSION_SECRET` | Secret key for session cookies (required in production) |
| `DEBUG` | `true` for development |
| `DATABASE_PATH` | SQLite file path (default: `../data/swissunihockey.db`) |
| `SWISSUNIHOCKEY_CACHE_DIR` | File cache directory (default: `../data/cache`) |
| `SMTP_HOST/PORT/USER/PASSWORD` | Optional: contact form email |
| `CONTACT_EMAIL` | Optional: contact form recipient |

## Deployment

Production runs on `pi4desk` at `/home/denny/dockerimages/SwissUnihockeyStats/`.

```bash
# Correct deploy (rebuilds image, force-recreates container)
docker compose build --no-cache && docker compose up -d --force-recreate

# Do NOT use docker restart — it reuses old container layers
```

DB volume: `/home/denny/dockerimages/SwissUnihockeyStats/data/swissunihockey.db`

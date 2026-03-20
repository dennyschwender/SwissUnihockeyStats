# Docker Compose Cleanup & Resource Tuning

**Date:** 2026-03-20
**Status:** Approved
**Priority:** Medium — prod settings were never applied; Pi 5 resources under-allocated

## Problem

The project has three compose files (`docker-compose.yml`, `docker-compose.prod.yml`, `docker-compose.dev.yml`), but the Pi 5 production deploy only runs `docker compose up -d` — meaning the prod overrides (gunicorn command, higher resource limits, `DEBUG=false`) are **never applied**. The container has been running with plain uvicorn, 1.0 CPU cap, and 512 MB RAM on an 8 GB / 4-core Pi 5.

Additionally:
- `docker-compose.dev.yml` is stale/broken: references paths that don't exist (`./api`, `./tests`, `./config.ini`), uses `python -i` as command
- `docker-compose.yml` contains large blocks of commented-out services (`preload-cache`, `cache-refresher`) and an unused named volume (`cache-data`)
- The two-file deploy command in CLAUDE.md is fragile and never actually used

## Approach: Single Consolidated `docker-compose.yml`

Merge prod settings into `docker-compose.yml` as the one authoritative file. Delete both `docker-compose.prod.yml` and `docker-compose.dev.yml`. `docker compose up -d` then works correctly with no flags.

## Design

### `docker-compose.yml` — final content

**Service settings (merged from both files):**

| Setting | Value | Source |
|---------|-------|--------|
| Container name | `swissunihockeystats` | user preference |
| Image | `swissunihockey:latest` | base |
| Command | gunicorn, 1 worker, UvicornWorker, 120s timeout | prod |
| `DEBUG` | `false` | prod |
| `WORKERS` | `1` | prod |
| `TZ` | `Europe/Zurich` | base |
| `DATABASE_PATH` | `/app/data/swissunihockey.db` | both |
| `SWISSUNIHOCKEY_CACHE_DIR` | `/app/data/cache` | both |
| `HOST` | `0.0.0.0` | base |
| `PORT` | `8000` | base |
| Volumes | `./data:/app/data`, `./backend/.env:/app/.env:ro` | both |
| Port | `8000:8000` | base |
| CPU limit | `3.0` | raised for Pi 5 (was 2.0 in prod, 1.0 in base) |
| Memory limit | `2G` | raised for Pi 5 (was 1G in prod, 512M in base) |
| CPU reservation | `1.0` | raised (was 0.5) |
| Memory reservation | `512M` | raised (was 256M) |
| Healthcheck | curl to `http://127.0.0.1:8000/health`, 30s interval | base |
| Restart | `unless-stopped` | both |
| Network | `swissunihockey-net` bridge | base |

**Removed:**
- Commented-out `preload-cache` service block
- Commented-out `cache-refresher` service block
- Unused `cache-data` named volume
- `./scripts:/app/scripts:ro` volume mount (scripts not needed at runtime)

**Deleted files:**
- `docker-compose.prod.yml`
- `docker-compose.dev.yml`

### CLAUDE.md deploy command update

Replace:
```bash
docker build --no-cache -t swissunihockey:latest . && \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --force-recreate
```

With:
```bash
docker build --no-cache -t swissunihockey:latest . && docker compose up -d --force-recreate
```

## Out of Scope

- Any changes to `Dockerfile`
- Any changes to application code
- Gunicorn worker count (stays at 1 — SQLite requires single process)
- Adding a dev compose file (dev workflow uses `.venv/bin/uvicorn` directly per CLAUDE.md)

## Expected Outcome

- `docker compose up -d` on Pi 5 applies gunicorn, correct resource limits, `DEBUG=false`
- Container has 3 CPU cores and 2 GB RAM available for nightly indexing
- Compose configuration is a single source of truth, no fragile multi-file merging

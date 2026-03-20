# Docker Compose Cleanup & Resource Tuning Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate three Docker Compose files into one clean `docker-compose.yml` with prod settings (gunicorn, 3 CPU / 2 GB limits, DEBUG=false) and update CLAUDE.md and memory to match.

**Architecture:** Delete `docker-compose.prod.yml` and `docker-compose.dev.yml`. Rewrite `docker-compose.yml` with all prod settings merged in. Update CLAUDE.md deploy command. Update MEMORY.md container name and deploy command.

**Tech Stack:** Docker Compose, bash.

---

## File Map

| File | Action |
|------|--------|
| `docker-compose.yml` | Rewrite — merged prod settings, cleaned of dead blocks |
| `docker-compose.prod.yml` | Delete |
| `docker-compose.dev.yml` | Delete |
| `CLAUDE.md` | Update deploy command |
| `.claude/projects/-home-denny-Development-SwissUnihockeyStats/memory/MEMORY.md` | Update container name + deploy command |

---

## Task 1: Rewrite `docker-compose.yml`

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Replace the entire content of `docker-compose.yml`**

Write this exact content to `/home/denny/Development/SwissUnihockeyStats/docker-compose.yml`:

```yaml
services:
  swissunihockey:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: swissunihockeystats
    image: swissunihockey:latest

    environment:
      - HOST=0.0.0.0
      - PORT=8000
      - WORKERS=1
      - DEBUG=false
      - TZ=Europe/Zurich
      - DATABASE_PATH=/app/data/swissunihockey.db
      - SWISSUNIHOCKEY_CACHE_DIR=/app/data/cache

    volumes:
      - ./data:/app/data
      - ./backend/.env:/app/.env:ro

    ports:
      - "8000:8000"

    # Single uvicorn worker — SQLite does not support concurrent multi-process writes.
    # Async uvicorn handles all request concurrency within one process via asyncio.
    command: [
      "gunicorn", "app.main:app",
      "--workers", "1",
      "--worker-class", "uvicorn.workers.UvicornWorker",
      "--bind", "0.0.0.0:8000",
      "--timeout", "120",
      "--access-logfile", "-",
      "--error-logfile", "-"
    ]

    deploy:
      resources:
        limits:
          cpus: '3.0'
          memory: 2G
        reservations:
          cpus: '1.0'
          memory: 512M

    healthcheck:
      test: ["CMD", "curl", "-fs", "http://127.0.0.1:8000/health"]
      interval: 30s
      timeout: 10s
      start_period: 60s
      retries: 3

    restart: unless-stopped

    networks:
      - swissunihockey-net

networks:
  swissunihockey-net:
    driver: bridge
```

- [ ] **Step 2: Verify the file is valid YAML**

```bash
docker compose -f /home/denny/Development/SwissUnihockeyStats/docker-compose.yml config --quiet
```

Expected: no output, exit code 0. If it prints errors, fix the YAML.

- [ ] **Step 3: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add docker-compose.yml
git commit -m "chore(docker): consolidate compose files — prod settings, 3CPU/2G limits, gunicorn"
```

---

## Task 2: Delete obsolete compose files

**Files:**
- Delete: `docker-compose.prod.yml`
- Delete: `docker-compose.dev.yml`

- [ ] **Step 1: Delete both files**

```bash
cd /home/denny/Development/SwissUnihockeyStats
rm docker-compose.prod.yml docker-compose.dev.yml
```

- [ ] **Step 2: Verify only one compose file remains**

```bash
ls /home/denny/Development/SwissUnihockeyStats/docker-compose*.yml
```

Expected: only `docker-compose.yml` listed.

- [ ] **Step 3: Verify compose still validates**

```bash
docker compose -f /home/denny/Development/SwissUnihockeyStats/docker-compose.yml config --quiet
```

Expected: no output, exit code 0.

- [ ] **Step 4: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add -A
git commit -m "chore(docker): delete docker-compose.prod.yml and docker-compose.dev.yml"
```

---

## Task 3: Update CLAUDE.md deploy command

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Find and update the deploy command in CLAUDE.md**

Find this block in `/home/denny/Development/SwissUnihockeyStats/CLAUDE.md`:

```bash
# Correct deploy (rebuilds image, force-recreates container)
docker build --no-cache -t swissunihockey:latest . && \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --force-recreate
```

Replace with:

```bash
# Correct deploy (rebuilds image, force-recreates container)
docker build --no-cache -t swissunihockey:latest . && docker compose up -d --force-recreate
```

Also update the container name reference if present. Find:
```
Production container name: `swissunihockey-prod`
```
and any reference to `swissunihockey-prod` in CLAUDE.md. Change to `swissunihockeystats`.

- [ ] **Step 2: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add CLAUDE.md
git commit -m "docs: update deploy command and container name in CLAUDE.md"
```

---

## Task 4: Update MEMORY.md

**Files:**
- Modify: `/home/denny/.claude/projects/-home-denny-Development-SwissUnihockeyStats/memory/MEMORY.md`

- [ ] **Step 1: Update container name and deploy command in MEMORY.md**

Find the deploy section. Update:
- Container name: `swissunihockey-prod` → `swissunihockeystats`
- Deploy command: remove `-f docker-compose.yml -f docker-compose.prod.yml` → simplify to `docker compose up -d --force-recreate`

The corrected deploy entry should read:
```
Correct deploy: `docker build --no-cache -t swissunihockey:latest . && docker compose up -d --force-recreate`
```

And the container name line:
```
Production container name: `swissunihockeystats`
```

- [ ] **Step 2: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats
git add /home/denny/.claude/projects/-home-denny-Development-SwissUnihockeyStats/memory/MEMORY.md
git commit -m "docs: update container name and deploy command in memory"
```

Note: MEMORY.md is outside the repo — if git add fails for that path, skip the commit; the file is already saved.

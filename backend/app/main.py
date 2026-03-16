"""
Main FastAPI application entry point
"""
from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import asyncio
import hashlib
import hmac
import html
import json
import os
import re
import smtplib
import time
import uuid
import logging
import traceback
from email.message import EmailMessage
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from app.config import settings
from app.api.v1.router import api_router
from app.lib.i18n import get_translations, get_locale_from_path, DEFAULT_LOCALE
from app.services.swissunihockey import get_swissunihockey_client
from app.services.data_cache import preload_common_data, preload_data, get_cached_teams, get_cached_leagues, get_cached_clubs
from app.services import rendering_config as _rcfg
from app.services.season_utils import get_current_season as _get_current_season_impl

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Setup paths
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def get_current_season() -> int:
    """Re-export from season_utils for backwards compatibility."""
    return _get_current_season_impl()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events: startup and shutdown"""
    # Startup: Initialize database and preload common data
    logger.info("🚀 Starting SwissUnihockey application...")
    current_season = get_current_season()
    logger.info(f"📅 Current season: {current_season}/{current_season + 1}")

    _sched_task = None  # initialise before try so shutdown block can always reference it

    # ── 1. Database init & data preload ────────────────────────────────────────────
    # Separated so that SQLite lock contention on parallel gunicorn worker
    # startup does not prevent the scheduler from initialising (step 2).
    try:
        logger.info("🗄️ Initializing database...")
        from app.services.database import get_database_service
        db_service = get_database_service()
        db_service.initialize()
        logger.info("✓ Database initialized")

        # Reset any sync rows that were left in_progress by a prior server process
        from app.services.data_indexer import DataIndexer as _DI
        _stale = _DI().cleanup_stale_sync_status()
        if _stale:
            logger.warning(f"⚠️ Reset {_stale} stale in_progress sync row(s) to failed")

        # Preload common data (leagues, popular teams) into memory cache
        await preload_common_data()  # Loads leagues and popular teams
        logger.info("✓ Common data preloaded")

        # Note: Use manage.py to trigger database indexing:
        # python manage.py index-clubs-path --season 2025

    except Exception as e:
        logger.error(f"❌ Failed to initialize DB/data: {e}")
        logger.warning("⚠️ App will start but some data may be stale or missing")

    # ── 2. Scheduler (always starts, even if DB init failed above) ───────────────────────────
    # With gunicorn multi-worker, the DB-init block can raise
    # "database is locked" for some workers.  Keeping the scheduler in its own
    # try ensures every worker has a Scheduler instance ->
    # no 503 on /admin/api/scheduler endpoints.
    try:
        from app.services.scheduler import init_scheduler
        _sched_instance = init_scheduler(_admin_jobs, _submit_job)
        _sched_task = asyncio.create_task(
            _sched_instance.run(), name="scheduler"
        )
        logger.info("✓ Scheduler started")
    except Exception as e:
        logger.error(f"❌ Failed to start scheduler: {e}")

    # ── 3. Admin PIN hash & stats pre-warm ───────────────────────────────────────────
    try:
        # Restore cooldown timestamps so manual jobs can't be double-triggered
        # right after a deploy.
        _load_cooldowns()
        logger.info("✓ Job cooldowns loaded")

        # Pre-compute admin PIN hash (pbkdf2_hmac 100k rounds, ~1-2 s on Pi ARM)
        # in an executor so it doesn't block the event loop.  Awaited here to
        # ensure it finishes BEFORE the stats-cache task starts, avoiding a
        # concurrent thread-pool race (Python 3.14 + SQLite segfault).
        # Guard against a second lifespan startup (e.g. nested TestClient in tests)
        # to avoid concurrent pbkdf2 + SQLite threads that segfault in Python 3.14.
        global _ADMIN_PIN_HASH
        if not _ADMIN_PIN_HASH:
            _ADMIN_PIN_HASH = await asyncio.get_running_loop().run_in_executor(
                None, _pin_hash, settings.ADMIN_PIN
            )
            logger.info("✓ Admin PIN hash pre-computed")

        # Pre-warm admin stats cache so the first admin page load is instant.
        # Guard prevents duplicate tasks if lifespan starts more than once.
        if _stats_cache is None and not _stats_is_refreshing:
            asyncio.create_task(_refresh_stats_cache(), name="stats-prewarm")
            logger.info("✓ Admin stats pre-warm scheduled")

    except Exception as e:
        logger.error(f"❌ Failed during warm-up: {e}")

    yield

    # Shutdown
    logger.info("Shutting down application...")
    try:
        from app.services.scheduler import get_scheduler
        sched = get_scheduler()
        if sched:
            sched.stop()
        if _sched_task and not _sched_task.done():
            _sched_task.cancel()
        _persist_cooldowns()
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}")
    try:
        from app.services.database import get_database_service
        db_service = get_database_service()
        db_service.close()
    except Exception as e:
        logger.error(f"Error closing database: {e}")
    logger.info("👋 Shutting down SwissUnihockey application")


# Create FastAPI app with lifespan
class _AdminNotAuthenticated(Exception):
    """Raised by require_admin dependency when session is not authenticated."""
    pass


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,  # type: ignore[arg-type]
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Configure session middleware with CSRF mitigations (SameSite=lax, HTTPS-only in prod)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET,
    session_cookie="admin_session",
    same_site="lax",
    https_only=not settings.DEBUG,
)
# Configure CORS — restrict to specific methods and headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(o) for o in settings.BACKEND_CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Include API router (JSON endpoints)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# ── Request-pressure tracking ──────────────────────────────────────────────
# Counts how many non-health/non-static HTTP requests are currently in flight.
# The background indexer checks this and yields CPU between batches so that
# frontend page loads are never starved by indexing work.
_active_requests: int = 0


@app.middleware("http")
async def _request_pressure_middleware(request: Request, call_next):
    global _active_requests
    path = request.url.path
    # Skip health checks and static assets — they don't need scheduling priority
    if not path.startswith("/static/") and path != "/health":
        _active_requests += 1
        try:
            return await call_next(request)
        finally:
            _active_requests -= 1
    return await call_next(request)


async def _backoff_if_busy():
    """Pause the indexer briefly when frontend requests are in flight.

    Called between batch items in _run() so that page requests always
    get a free event-loop turn while the background indexer is running.
    """
    if _active_requests > 0:
        await asyncio.sleep(0.5)


@app.exception_handler(_AdminNotAuthenticated)
async def _admin_not_auth_handler(request: Request, exc: _AdminNotAuthenticated):
    return RedirectResponse(url="/admin/login", status_code=302)


# ============================================================================
# AUTH HELPERS
# ============================================================================

def _pin_hash(pin: str) -> str:
    """Stable hash of the PIN so we never store it plaintext in session."""
    return hashlib.pbkdf2_hmac(
        'sha256',
        pin.encode(),
        settings.SESSION_SECRET.encode(),
        100_000,
    ).hex()

# Computed once at import time — blocks import for ~200 ms on Pi ARM but
# acceptable: done before the server accepts any connections, so
# require_admin() is always an instant string comparison at runtime.
# Avoids the reload race condition where _ADMIN_PIN_HASH == '' after restart.
_ADMIN_PIN_HASH: str = _pin_hash(settings.ADMIN_PIN)

_ADMIN_TOKEN_KEY = "admin_authed"

# ---------------------------------------------------------------------------
# Login rate limiting (in-memory, per client IP)
# ---------------------------------------------------------------------------
_LOGIN_MAX_ATTEMPTS = 10
_LOGIN_WINDOW_SECS  = 300  # 5 minutes
_login_attempts: dict = {}  # ip -> (count, window_start)


def _check_login_rate_limit(ip: str) -> bool:
    """Return True if the IP has exceeded the login attempt limit."""
    now = time.time()
    entry = _login_attempts.get(ip)
    if entry is None:
        _login_attempts[ip] = (1, now)
        return False
    count, window_start = entry
    if now - window_start > _LOGIN_WINDOW_SECS:
        _login_attempts[ip] = (1, now)
        return False
    if count >= _LOGIN_MAX_ATTEMPTS:
        return True
    _login_attempts[ip] = (count + 1, window_start)
    return False


def _reset_login_rate_limit(ip: str) -> None:
    """Clear rate-limit state after a successful login."""
    _login_attempts.pop(ip, None)


# ---------------------------------------------------------------------------
# Contact form rate limiting (in-memory, per client IP)
# ---------------------------------------------------------------------------
_CONTACT_MAX_SUBMISSIONS = 5
_CONTACT_WINDOW_SECS = 3600  # 1 hour
_contact_attempts: dict = {}  # ip -> (count, window_start)

# Privacy policy "last updated" date — update this when the policy changes.
PRIVACY_POLICY_LAST_UPDATED = "2026-03-06"


def _check_contact_rate_limit(ip: str) -> bool:
    """Return True if the IP has exceeded the contact form submission limit."""
    now = time.time()
    entry = _contact_attempts.get(ip)
    if entry is None:
        _contact_attempts[ip] = (1, now)
        return False
    count, window_start = entry
    if now - window_start > _CONTACT_WINDOW_SECS:
        _contact_attempts[ip] = (1, now)
        return False
    if count >= _CONTACT_MAX_SUBMISSIONS:
        return True
    _contact_attempts[ip] = (count + 1, window_start)
    return False


def require_admin(request: Request):
    """FastAPI dependency — raises exception caught by handler below if not logged in."""
    if request.session.get(_ADMIN_TOKEN_KEY) != _ADMIN_PIN_HASH:
        raise _AdminNotAuthenticated()


# DEBUG endpoints — only registered when DEBUG=True, admin-only
if settings.DEBUG:
    @app.get("/debug/player-index")
    async def debug_player_index(_: None = Depends(require_admin)):
        """Debug endpoint to see player index status."""
        from app.services.data_cache import get_data_cache
        cache = get_data_cache()
        return {
            "players_indexed": cache._players_indexed,
            "player_count": len(cache._players),
            "game_count": len(cache._games),
            "sample_players": list(cache._players.values())[:5],
        }

    @app.get("/debug/force-reindex")
    async def debug_force_reindex(_: None = Depends(require_admin)):
        """Force player reindexing and return detailed logs."""
        from app.services.data_cache import get_data_cache
        cache = get_data_cache()
        try:
            players_teams = await cache.index_players_from_teams()
            players_games = await cache.index_players_from_games()
            return {
                "success": True,
                "players_from_teams": players_teams,
                "players_from_games": players_games,
                "total_players": len(cache._players),
            }
        except Exception as e:
            logger.error("Reindex failed: %s", e, exc_info=True)
            return {"success": False, "error": "Reindex failed — see server logs"}

    @app.get("/debug/test-games-fetch")
    async def debug_test_games_fetch(_: None = Depends(require_admin)):
        """Debug endpoint to test various API endpoints."""
        client = get_swissunihockey_client()
        from app.services.data_cache import get_data_cache
        cache = get_data_cache()

        results = {}
        current_season = get_current_season()

        # Test endpoint: Team players
        await cache.load_leagues()
        if cache._leagues:
            first_league = cache._leagues[0]
            try:
                teams_data = client.get_teams(
                    league=first_league.get("id"),
                    game_class=first_league.get("game_classes", [{}])[0].get("id", 11),
                    mode="1",
                    season=current_season,
                )
                teams = []
                if isinstance(teams_data, dict):
                    if "data" in teams_data:
                        regions = teams_data.get("data", {}).get("regions", [])
                        if regions:
                            teams = regions[0].get("rows", [])
                    elif "entries" in teams_data:
                        teams = teams_data["entries"]
                if teams:
                    team_id = teams[0].get("id")
                    team_name = teams[0].get("text", "")
                    try:
                        players_data = client.get_team_players(team_id)
                        results["team_players"] = {
                            "success": True,
                            "team_id": team_id,
                            "team_name": team_name,
                            "has_data": bool(players_data),
                        }
                    except Exception as e:
                        results["team_players"] = {"success": False, "team_id": team_id, "error": str(e)}
            except Exception as e:
                results["team_players"] = {"success": False, "error": str(e)}

        # Test games endpoint
        try:
            games_data = client.get_games(mode="list", season=current_season, league=1, game_class=11)
            results["games_mode_list"] = {
                "success": True,
                "has_data": bool(games_data),
                "game_count": len(games_data.get("entries", [])) if isinstance(games_data, dict) else 0,
            }
        except Exception as e:
            results["games_mode_list"] = {"success": False, "error": str(e)}

        return results


# ============================================================================
# HTML Template Routes (Python Full-Stack with Jinja2 + htmx)
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def root_redirect(request: Request):
    """Redirect root to default locale"""
    return RedirectResponse(f"/{DEFAULT_LOCALE}", status_code=302)


# ============================================================================
# ADMIN LOGIN / LOGOUT
# ============================================================================

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if request.session.get(_ADMIN_TOKEN_KEY) == _ADMIN_PIN_HASH:
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse(request, "admin_login.html", {"error": None})


@app.post("/admin/login")
async def admin_login_submit(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if _check_login_rate_limit(client_ip):
        return templates.TemplateResponse(
            request,
            "admin_login.html",
            {"error": "Too many login attempts. Please wait a few minutes."},
            status_code=429,
        )
    form = await request.form()
    pin  = str(form.get("pin", "")).strip()
    if hmac.compare_digest(_pin_hash(pin), _ADMIN_PIN_HASH):
        _reset_login_rate_limit(client_ip)
        request.session[_ADMIN_TOKEN_KEY] = _ADMIN_PIN_HASH
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse(
        request,
        "admin_login.html",
        {"error": "Incorrect PIN. Try again."},
        status_code=401,
    )


@app.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=302)


# ==================== ADMIN ROUTES ====================
# Must be registered BEFORE the /{locale} catch-all route.

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, _: None = Depends(require_admin)):
    """Admin dashboard — indexing status and controls"""
    return templates.TemplateResponse(request, "admin.html", {})


@app.get("/admin/api/stats")
async def admin_stats(_: None = Depends(require_admin)):
    """Per-entity DB counts, per-season breakdown, and last 100 sync records.

    Uses an in-memory cache (_stats_cache) so that repeated 30-second polls
    return instantly.  A background task keeps the cache warm; the first call
    after a server restart will await the initial computation.
    """
    now = time.monotonic()
    cache_age = now - _stats_cache_time

    if _stats_cache is not None:
        # Return cached data immediately and kick off a background refresh if stale.
        if cache_age >= _STATS_CACHE_TTL:
            asyncio.ensure_future(_refresh_stats_cache())
        return _stats_cache

    # No cache yet — await the first computation (only happens once after restart).
    try:
        await _refresh_stats_cache()
        return _stats_cache or {"totals": {}, "by_season": [], "sync_status": []}
    except Exception as exc:
        logger.error("admin_stats failed: %s", exc, exc_info=True)
        return {"totals": {}, "by_season": [], "sync_status": [], "error": str(exc)}


@app.get("/admin/api/stats/history")
async def admin_stats_history(
    days: int = 30,
    _: None = Depends(require_admin),
):
    """Return admin_stats_snapshots rows for the last `days` days, newest first."""
    from sqlalchemy import text
    from datetime import datetime, timezone, timedelta
    from app.services.database import get_database_service
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    db_service = get_database_service()
    with db_service.engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ts, db_size_bytes, games, players, events, player_stats,
                   jobs_run, jobs_errors, avg_job_duration_s
            FROM admin_stats_snapshots
            WHERE ts >= :cutoff
            ORDER BY ts DESC
        """), {"cutoff": cutoff}).fetchall()
    return [dict(r._mapping) for r in rows]


@app.get("/admin/api/db-info")
async def admin_db_info(_: None = Depends(require_admin)):
    """SQLite file sizes and PRAGMA health metrics."""
    import os
    from app.services.database import get_database_service
    from sqlalchemy import text as _text

    db_service = get_database_service()
    url = db_service.database_url  # e.g. sqlite:///data/swissunihockey.db
    is_sqlite = url.startswith("sqlite")

    file_info: dict = {}
    pragma_info: dict = {}

    if is_sqlite and ":memory:" not in url:
        # Strip leading sqlite:/// prefix to get the filesystem path
        db_path = url.replace("sqlite:///", "").replace("sqlite://", "")
        for suffix, key in [("", "db"), ("-wal", "wal"), ("-shm", "shm")]:
            p = db_path + suffix
            try:
                size = os.path.getsize(p)
                file_info[key] = {"path": p, "size": size, "exists": True}
            except FileNotFoundError:
                file_info[key] = {"path": p, "size": 0, "exists": False}

    if is_sqlite:
        try:
            loop = asyncio.get_running_loop()
            def _read_pragma():
                with db_service.session_scope() as s:
                    def pg(name):
                        try:
                            return s.execute(_text(f"PRAGMA {name}")).scalar()
                        except Exception:
                            return None
                    return {
                        "page_count":    pg("page_count"),
                        "page_size":     pg("page_size"),
                        "freelist_count": pg("freelist_count"),
                        "journal_mode":  pg("journal_mode"),
                        "wal_checkpoint": pg("wal_autocheckpoint"),
                        # integrity_ok intentionally omitted — quick_check is
                        # slow and can block other requests on a Pi
                    }
            pragma_info = await loop.run_in_executor(None, _read_pragma)
        except Exception as e:
            pragma_info = {"error": str(e)}

    return {"files": file_info, "pragma": pragma_info, "is_sqlite": is_sqlite}


@app.post("/admin/api/vacuum")
async def admin_vacuum(_: None = Depends(require_admin)):
    """Run VACUUM + WAL checkpoint in the background.

    VACUUM rewrites the entire DB file and can take several minutes on large
    databases.  To avoid browser connection timeouts (typically ~120s) the
    operation runs as a background task; this endpoint returns immediately.
    Check server logs for completion / errors.
    """
    from app.services.database import get_database_service
    from sqlalchemy import text as _text

    db_service = get_database_service()
    if ":memory:" in db_service.database_url:
        return {"ok": False, "detail": "VACUUM not applicable for in-memory DB"}

    if db_service.engine is None:
        return {"ok": False, "detail": "Database engine not initialized"}

    engine = db_service.engine

    async def _run_vacuum():
        import time
        t0 = time.time()
        try:
            def _vacuum():
                with engine.connect() as conn:
                    conn.execute(_text("PRAGMA wal_checkpoint(TRUNCATE)"))
                    conn.execute(_text("VACUUM"))

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _vacuum)
            elapsed = round(time.time() - t0, 2)
            logger.info("Admin VACUUM completed in %.2fs", elapsed)
        except Exception as e:
            logger.error("Admin VACUUM failed after %.2fs: %s", time.time() - t0, e, exc_info=True)

    asyncio.create_task(_run_vacuum())
    return {"ok": True, "started": True}


@app.post("/admin/api/cleanup")
async def admin_cleanup_duplicates(_: None = Depends(require_admin)):
    """Remove duplicate rows that can accumulate when indexing runs multiple times.

    Targets:
    - league_groups: duplicates on (league_id, group_id) — no unique constraint
    - game_events:   duplicates on (game_id, event_type, period, time, player_id)
    - sync_status:   completed/failed entries older than 7 days (just clutter)
    """
    # Refuse to run while any indexing/purge job is active — a mid-flight
    # insert could race with our DELETE and leave orphaned FK references.
    running = [j for j in _admin_jobs.values() if j.get("status") == "running"]
    if running:
        labels = ", ".join(j.get("label", j["job_id"]) for j in running)
        return {
            "ok": False,
            "conflict": True,
            "detail": f"Cannot cleanup while jobs are running: {labels}",
        }

    from app.services.database import get_database_service
    from sqlalchemy import text as _text
    import time

    db_service = get_database_service()
    if db_service.engine is None:
        return {"ok": False, "detail": "Database engine not initialized"}

    loop = asyncio.get_running_loop()

    def _cleanup():
        t0 = time.time()
        counts = {}
        with db_service.engine.connect() as conn:
            # ── league_groups duplicates ─────────────────────────────────────
            # Keep the row with the lowest id per (league_id, group_id, phase).
            # Rows that share (league_id, group_id) but differ in phase are
            # intentional (phase-keyed groups) and must NOT be merged.
            # NULLs are treated as equivalent via COALESCE.
            #
            # IMPORTANT: before deleting non-min rows, remap any games that
            # reference them to the surviving (min) row — otherwise the FK
            # constraint fails.
            non_min_ids = [
                r[0] for r in conn.execute(_text(
                    "SELECT id FROM league_groups "
                    "WHERE id NOT IN ("
                    "  SELECT MIN(id) FROM league_groups "
                    "  GROUP BY league_id, group_id, COALESCE(phase, '')"
                    ")"
                )).fetchall()
            ]
            if non_min_ids:
                # Build old_id → new_id (min sibling) mapping
                id_map_rows = conn.execute(_text(
                    "SELECT id, league_id, group_id, COALESCE(phase,'') as ph FROM league_groups"
                )).fetchall()
                min_for: dict[tuple, int] = {}
                for row_id, lid, gid, ph in id_map_rows:
                    key = (lid, gid, ph)
                    if key not in min_for or row_id < min_for[key]:
                        min_for[key] = row_id
                # Full lookup: every id → its min sibling
                full_map: dict[int, tuple] = {}
                for row_id, lid, gid, ph in id_map_rows:
                    full_map[row_id] = (lid, gid, ph)
                # Remap game.group_id for any games pointing at non-min rows
                remapped = 0
                for old_id in non_min_ids:
                    key = full_map.get(old_id)
                    if key is None:
                        continue
                    new_id = min_for[key]
                    if new_id == old_id:
                        continue
                    r2 = conn.execute(
                        _text("UPDATE games SET group_id=:new WHERE group_id=:old"),
                        {"new": new_id, "old": old_id},
                    )
                    remapped += r2.rowcount
                counts["games_remapped"] = remapped
                # Now it's safe to delete
                placeholders = ",".join(str(i) for i in non_min_ids)
                r = conn.execute(_text(f"DELETE FROM league_groups WHERE id IN ({placeholders})"))
                counts["league_groups"] = r.rowcount
            else:
                counts["league_groups"] = 0
                counts["games_remapped"] = 0

            # ── game_events duplicates ───────────────────────────────────────
            # Keep the row with the lowest id per
            # (game_id, event_type, period, time, player_id).
            # Batched by game_id to avoid holding the write lock over 300k+ rows
            # in a single statement.
            game_id_rows = conn.execute(_text(
                "SELECT DISTINCT game_id FROM game_events "
                "GROUP BY game_id, event_type, period, time, player_id "
                "HAVING COUNT(*) > 1"
            )).fetchall()
            dup_game_ids = [r[0] for r in game_id_rows]
            event_deleted = 0
            _CHUNK = 200
            for _i in range(0, len(dup_game_ids), _CHUNK):
                chunk = dup_game_ids[_i: _i + _CHUNK]
                placeholders = ",".join("?" * len(chunk))
                r = conn.execute(_text(
                    f"DELETE FROM game_events "
                    f"WHERE game_id IN ({placeholders}) "
                    f"AND id NOT IN ("
                    f"  SELECT MIN(id) FROM game_events "
                    f"  WHERE game_id IN ({placeholders}) "
                    f"  GROUP BY game_id, event_type, period, time, player_id"
                    f")"
                ), chunk + chunk)
                event_deleted += r.rowcount
                conn.commit()
            counts["game_events"] = event_deleted

            # ── stale sync_status entries ────────────────────────────────────
            # Remove completed/failed records older than 7 days — pure clutter.
            r = conn.execute(_text(
                "DELETE FROM sync_status "
                "WHERE sync_status IN ('completed', 'failed', 'stale') "
                "  AND last_sync < datetime('now', '-7 days')"
            ))
            counts["sync_status"] = r.rowcount

            conn.commit()
        counts["total"] = sum(counts.values())
        counts["elapsed_s"] = round(time.time() - t0, 2)
        return counts

    try:
        result = await loop.run_in_executor(None, _cleanup)
        logger.info(
            "Admin cleanup: removed %d league_group dups (remapped %d games), "
            "%d game_event dups, %d stale sync_status rows in %.2fs",
            result["league_groups"], result.get("games_remapped", 0),
            result["game_events"], result["sync_status"], result["elapsed_s"],
        )
        return {"ok": True, **result}
    except Exception as e:
        logger.error("Admin cleanup failed: %s", e, exc_info=True)
        return {"ok": False, "detail": str(e)}


@app.post("/admin/api/repair")
async def admin_repair(_: None = Depends(require_admin)):
    """Run conservative DB repairs immediately and return summary + health report."""
    from app.services.repair_service import get_repair_service
    try:
        svc = get_repair_service()
        result = await asyncio.to_thread(svc.run_nightly)
        result["ok"] = True
        result["games_no_lineup"] = svc.report_games_no_lineup()
        result["roster_gaps"] = svc.report_roster_gaps()
        result["unresolved_stats"] = svc.report_unresolved_stats()
        return result
    except Exception as exc:
        logger.error("admin_repair failed: %s", exc, exc_info=True)
        return {"ok": False, "detail": str(exc)}


@app.get("/admin/api/repair-report")
async def admin_repair_report(_: None = Depends(require_admin)):
    """Return the health report (read-only, no fixes applied)."""
    from app.services.repair_service import get_repair_service
    from app.models.db_models import SyncStatus
    try:
        svc = get_repair_service()
        db = svc.db_service
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
            "games_no_lineup": svc.report_games_no_lineup(),
            "roster_gaps": svc.report_roster_gaps(),
            "unresolved_stats": svc.report_unresolved_stats(),
        }
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


@app.get("/admin/api/system")
async def admin_api_system(_: None = Depends(require_admin)):
    """Return system / container performance metrics for the admin System tab."""
    import os as _os
    try:
        import psutil
    except ImportError:
        return {"ok": False, "error": "psutil not installed — run: pip install psutil"}

    try:
        cpu_pct   = psutil.cpu_percent(interval=0.2)
        cpu_count = psutil.cpu_count(logical=True)
        _freq     = psutil.cpu_freq()
        cpu_freq  = round(_freq.current, 1) if _freq else None

        vm  = psutil.virtual_memory()
        mem = {
            "total":     vm.total,
            "used":      vm.used,
            "available": vm.available,
            "percent":   vm.percent,
        }

        disk = None
        for _path in ["/app/data", "/"]:
            try:
                du   = psutil.disk_usage(_path)
                disk = {
                    "path":    _path,
                    "total":   du.total,
                    "used":    du.used,
                    "free":    du.free,
                    "percent": du.percent,
                }
                break
            except Exception:
                pass

        _net   = psutil.net_io_counters()
        net_io = {
            "bytes_sent":   _net.bytes_sent,
            "bytes_recv":   _net.bytes_recv,
            "packets_sent": _net.packets_sent,
            "packets_recv": _net.packets_recv,
        } if _net else {}

        proc = psutil.Process(_os.getpid())
        with proc.oneshot():
            proc_rss     = proc.memory_info().rss
            proc_cpu_pct = proc.cpu_percent(interval=None)
            proc_threads = proc.num_threads()

        uptime_s = int(time.time() - psutil.boot_time())

        # cgroup v2 (and v1 fallback) memory limit — only meaningful inside a container
        cgroup_mem_limit = None
        cgroup_mem_used  = None
        for _p in ("/sys/fs/cgroup/memory.max",
                   "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
            try:
                val = Path(_p).read_text().strip()
                if val not in ("max", "0", ""):
                    cgroup_mem_limit = int(val)
                break
            except Exception:
                pass
        for _p in ("/sys/fs/cgroup/memory.current",
                   "/sys/fs/cgroup/memory/memory.usage_in_bytes"):
            try:
                cgroup_mem_used = int(Path(_p).read_text().strip())
                break
            except Exception:
                pass

        return {
            "ok":  True,
            "cpu": {"percent": cpu_pct, "count": cpu_count, "freq_mhz": cpu_freq},
            "mem": mem,
            "disk": disk,
            "net_io": net_io,
            "process": {
                "pid":     _os.getpid(),
                "rss":     proc_rss,
                "cpu_pct": proc_cpu_pct,
                "threads": proc_threads,
            },
            "uptime_s":         uptime_s,
            "hostname":         _os.environ.get("HOSTNAME", "unknown"),
            "cgroup_mem_limit": cgroup_mem_limit,
            "cgroup_mem_used":  cgroup_mem_used,
        }
    except Exception as exc:
        logger.error("System stats error: %s", exc, exc_info=True)
        return {"ok": False, "error": str(exc)}


@app.get("/admin/api/scheduler-diag")
async def admin_scheduler_diag(_: None = Depends(require_admin)):
    """Freshness diagnosis: for every policy × season show what _last_sync_for()
    actually returns so we can spot mismatches between the scheduler's queries
    and what the data_indexer writes to sync_status."""
    from app.services.database import get_database_service
    from app.models.db_models import Season, SyncStatus
    from app.services.scheduler import get_scheduler, POLICIES, _last_sync_for, _utcnow
    import asyncio

    _sched = get_scheduler()  # capture once; shared with _run() closure

    def _run():
        db = get_database_service()
        now = _utcnow()
        rows = []
        with db.session_scope() as session:
            season_rows = (session.query(Season.id, Season.highlighted)
                           .order_by(Season.id.desc()).limit(20).all())
            current_sid = next((r[0] for r in season_rows if r[1]), None)
            # Respect scheduler season filter — excluded/below-min seasons are not managed
            indexed_sids = [
                r[0] for r in season_rows
                if not (_sched and _sched._season_filtered(r[0]))
            ]

            for policy in POLICIES:
                seasons_to_check = [None] if policy["scope"] == "global" else indexed_sids
                for sid in seasons_to_check:
                    last_sync = _last_sync_for(session, policy["entity_type"], sid)
                    max_age = policy["max_age"]
                    is_current = sid == current_sid
                    # Past seasons are frozen once indexed: the scheduler intentionally
                    # never re-queues them, so they should never show as stale.
                    is_frozen = (
                        not is_current
                        and sid is not None
                        and last_sync is not None
                        and not policy.get("current_only", False)
                    )
                    if is_frozen:
                        status = "FROZEN"
                        next_run = "—"
                    elif last_sync is None:
                        status = "NEVER_SYNCED"
                        next_run = "IMMEDIATE"
                    else:
                        age = now - last_sync
                        if age > max_age:
                            status = "STALE"
                            next_run = "IMMEDIATE"
                        else:
                            remaining = max_age - age
                            h, rem = divmod(int(remaining.total_seconds()), 3600)
                            m = rem // 60
                            status = "FRESH"
                            next_run = f"in {h}h {m}m"
                    rows.append({
                        "policy":       policy["name"],
                        "entity_type":  policy["entity_type"],
                        "scope":        policy["scope"],
                        "season":       sid,
                        "is_current":   is_current,
                        "current_only": policy.get("current_only", False),
                        "max_age_h":    round(policy["max_age"].total_seconds() / 3600, 1),
                        "last_sync":    last_sync.strftime("%Y-%m-%d %H:%M") if last_sync else None,
                        "status":       status,
                        "next_run":     next_run,
                    })
        return rows

    try:
        result = await asyncio.get_event_loop().run_in_executor(None, _run)
        sf = _sched.get_season_filter() if _sched else {
            "min_season": None, "excluded_seasons": [], "max_concurrent": 2
        }
        return {"ok": True, "rows": result, "season_filter": sf}
    except Exception as exc:
        logger.error("scheduler-diag error: %s", exc, exc_info=True)
        return {"ok": False, "error": str(exc)}


def _admin_stats_sync():
    """Synchronous DB work for admin stats (called via run_in_executor)."""
    from app.services.database import get_database_service
    from app.models.db_models import (
        Season, Club, Team, Player, TeamPlayer,
        League, LeagueGroup, Game, GamePlayer, GameEvent, PlayerStatistics, SyncStatus
    )
    from sqlalchemy import func, text

    db_service = get_database_service()
    with db_service.session_scope() as session:
        # Short busy timeout — WAL mode readers shouldn't block, but if they do
        # we want to fail fast (3 s) rather than hang for 30 s.
        try:
            session.execute(text("PRAGMA busy_timeout=3000"))
        except Exception:
            pass

        def safe_count(q):
            try:
                return q.scalar() or 0
            except Exception:
                return -1

        def safe_group_by(col, season_col):
            try:
                return {sid: n for sid, n in session.query(season_col, func.count(col)).group_by(season_col).all()}
            except Exception:
                return {}

        # ── Global totals ──────────────────────────────────────────────────
        # clubs/teams: COUNT(DISTINCT id) — same API id reused across seasons
        # leagues: COUNT(DISTINCT league_id, game_class) — unique league type
        # league_groups: COUNT(DISTINCT group_id) — unique API group
        totals = {
            "seasons":       safe_count(session.query(func.count(Season.id))),
            "clubs":         safe_count(session.query(func.count(func.distinct(Club.id)))),
            "teams":         safe_count(session.query(func.count(func.distinct(Team.id)))),
            "players":       safe_count(session.query(func.count(Player.person_id))),
            "team_players":  safe_count(session.query(func.count(TeamPlayer.id))),
            "leagues":       safe_count(session.query(func.count(func.distinct(League.league_id)))),
            "league_groups": safe_count(session.query(func.count(func.distinct(LeagueGroup.group_id)))),
            "games":         safe_count(session.query(func.count(Game.id))),
            "game_events":   safe_count(session.query(func.count(GameEvent.id))),
            "game_players":  safe_count(session.query(func.count(GamePlayer.id))),
            "player_stats":  safe_count(session.query(func.count(PlayerStatistics.id))),
        }

        # ── Per-season aggregates via GROUP BY ─────────────────────────────
        clubs_by_s   = safe_group_by(Club.id,            Club.season_id)
        teams_by_s   = safe_group_by(Team.id,            Team.season_id)
        tp_by_s      = safe_group_by(TeamPlayer.id,      TeamPlayer.season_id)
        leagues_by_s = safe_group_by(League.id,          League.season_id)
        games_by_s   = safe_group_by(Game.id,            Game.season_id)
        gp_by_s      = safe_group_by(GamePlayer.id,      GamePlayer.season_id)
        pstats_by_s  = safe_group_by(PlayerStatistics.id, PlayerStatistics.season_id)

        try:
            groups_by_s = {r[0]: r[1] for r in
                session.query(League.season_id, func.count(LeagueGroup.id))
                .join(LeagueGroup, LeagueGroup.league_id == League.id)
                .group_by(League.season_id)
                .all()
            }
        except Exception:
            groups_by_s = {}

        try:
            events_by_s = {r[0]: r[1] for r in
                session.query(Game.season_id, func.count(GameEvent.id))
                .join(GameEvent, GameEvent.game_id == Game.id)
                .group_by(Game.season_id)
                .all()
            }
        except Exception:
            events_by_s = {}

        try:
            season_rows = (session.query(Season.id, Season.text, Season.highlighted)
                           .order_by(Season.id.desc()).all())
        except Exception:
            season_rows = []

        by_season = [
            {
                "season_id":     sid,
                "season_text":   stext or str(sid),
                "clubs":         clubs_by_s.get(sid, 0),
                "teams":         teams_by_s.get(sid, 0),
                "team_players":  tp_by_s.get(sid, 0),
                "leagues":       leagues_by_s.get(sid, 0),
                "league_groups": groups_by_s.get(sid, 0),
                "games":         games_by_s.get(sid, 0),
                "game_events":   events_by_s.get(sid, 0),
                "game_players":  gp_by_s.get(sid, 0),
                "player_stats":  pstats_by_s.get(sid, 0),
                "is_current":    bool(shighlighted),
            }
            for sid, stext, shighlighted in season_rows
        ]

        # ── Recent sync records ────────────────────────────────────────────
        try:
            syncs = (session.query(SyncStatus)
                     .order_by(SyncStatus.last_sync.desc())
                     .limit(100).all())
            sync_status = [
                {
                    "entity_type": s.entity_type,
                    "entity_id":   s.entity_id,
                    "status":      s.sync_status,
                    "last_sync":   s.last_sync.strftime("%Y-%m-%d %H:%M") if s.last_sync else None,
                    "records":     s.records_synced or 0,
                    "error":       s.error_message,
                }
                for s in syncs
            ]
        except Exception:
            sync_status = []

    return {"totals": totals, "by_season": by_season, "sync_status": sync_status}


# ── Admin stats in-memory cache ───────────────────────────────────────────────
# The stats query runs ~18 GROUP BY queries and can take 5-30 s on a Pi.
# We cache the last result and serve it instantly; background refresh keeps it
# fresh every _STATS_CACHE_TTL seconds (same as the JS poll interval).
_stats_cache: dict | None = None
_stats_cache_time: float = 0.0
_stats_is_refreshing: bool = False
_STATS_CACHE_TTL: float = 30.0  # seconds


async def _refresh_stats_cache() -> None:
    """Compute fresh admin stats in a thread and update the module-level cache."""
    global _stats_cache, _stats_cache_time, _stats_is_refreshing
    if _stats_is_refreshing:
        return  # already running
    _stats_is_refreshing = True
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _admin_stats_sync)
        _stats_cache = result
        _stats_cache_time = time.monotonic()
        logger.debug("Admin stats cache refreshed")
    except Exception as exc:
        logger.warning("Admin stats cache refresh failed: %s", exc)
    finally:
        _stats_is_refreshing = False


# In-memory job registry for background indexing tasks
_admin_jobs: dict  = {}
_admin_tasks: dict = {}  # job_id → asyncio.Task (running only)


async def _submit_job(job_id: str, season: int | None, task: str, force: bool = False, max_tier: int = 7):
    """Bridge used by the scheduler to start an _run() coroutine for a pre-registered job."""
    t = asyncio.create_task(_run(job_id, season, task, force, max_tier=max_tier), name=f"job-{job_id}")
    _admin_tasks[job_id] = t

# Task definitions: human label + which tasks it maps to internally
_TASK_META = {
    "seasons":           "Index Seasons",
    "clubs":             "Index Clubs",
    "teams":             "Index Teams (all clubs)",
    "players":           "Index Players (all teams)",
    "clubs_path":        "Index Clubs Path (clubs + teams + players)",
    "leagues":           "Index Leagues",
    "groups":            "Index League Groups",
    "games":             "Index Games",
    "events":            "Index Game Events (finished games)",
    "player_stats":      "Index Player Statistics",
    "player_game_stats": "Index Player Game Stats (G/A/PIM per game)",
    "game_lineups":      "Index Game Lineups (player appearances per game)",
    "team_names":        "Backfill Team Names (from rankings API)",
    "leagues_path":      "Index Leagues Path (leagues + groups + games)",
    "full":              "Full Index (clubs path + leagues path + lineups + game stats)",
    "repair":            "DB Repair",
    "upcoming_games":        "Index Upcoming Games",
    "post_game_completion":  "Index Post-Game Completion",
}

# Minimum minutes before the same (task, season) can be re-triggered without force=True.
_TASK_COOLDOWN_MINS: dict[str, int] = {
    "full":              30,
    "clubs_path":        60,
    "leagues_path":      30,
    "leagues":           30,
    "groups":            30,
    "games":             15,
    "events":            10,
    "players":           60,
    "teams":             60,
    "clubs":             120,
    "player_stats":      30,
    "player_game_stats": 30,
    "game_lineups":      30,
    "team_names":        60,
    "seasons":           60,
}
# Tracks when each (task, season) last finished successfully (in-memory).
_job_last_done: dict[tuple[str, int], datetime] = {}


def _load_cooldowns() -> None:
    """Populate _job_last_done from scheduler_config.json on startup."""
    try:
        from app.services.scheduler import _CONFIG_PATH
        with open(_CONFIG_PATH) as f:
            data = json.load(f)
        raw = data.get("cooldowns", {})
        # raw keys are "task:season" strings, values are ISO datetime strings
        result = {}
        for key_str, dt_str in raw.items():
            parts = key_str.split(":", 1)
            if len(parts) != 2:
                continue
            try:
                task_k = parts[0]
                season_k = int(parts[1])
                dt_k = datetime.fromisoformat(dt_str)
                result[(task_k, season_k)] = dt_k
            except (ValueError, TypeError):
                continue
        _job_last_done.update(result)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass  # startup without file is fine


def _persist_cooldowns() -> None:
    """Write _job_last_done to the cooldowns section of scheduler_config.json."""
    try:
        from app.services.scheduler import _CONFIG_PATH
        # Read-modify-write to avoid clobbering scheduler's own keys
        try:
            with open(_CONFIG_PATH) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        data["cooldowns"] = {
            f"{task}:{season}": dt.isoformat()
            for (task, season), dt in _job_last_done.items()
        }
        tmp = _CONFIG_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _CONFIG_PATH)
    except OSError as exc:
        logger.warning("Could not persist cooldowns: %s", exc)


@app.post("/admin/api/index")
async def admin_start_indexing(payload: dict, _: None = Depends(require_admin)):
    """Start a background indexing job.

    payload: { season: int, task: str, force: bool, max_tier?: int }
    task is one of: clubs | teams | players | clubs_path |
                    leagues | groups | games | events | leagues_path | full
    max_tier: 1–7 — only index events for leagues at or below this tier
               (1=L-UPL only … 7=all incl. youth/regional, default 7)
    """
    season   = int(payload.get("season", get_current_season()))
    task     = payload.get("task", "full")
    force    = bool(payload.get("force", False))
    max_tier = int(payload.get("max_tier", 7))

    if task not in _TASK_META:
        raise HTTPException(status_code=400, detail=f"Unknown task '{task}'. Valid: {list(_TASK_META)}")

    # Cooldown guard — skip if data was indexed recently and force is not set.
    if not force:
        cooldown = _TASK_COOLDOWN_MINS.get(task, 0)
        last_done = _job_last_done.get((task, season))
        if cooldown and last_done:
            age_mins = (datetime.now(timezone.utc) - last_done).total_seconds() / 60
            remaining = cooldown - age_mins
            if remaining > 0:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Data is fresh — last run {age_mins:.0f} min ago "
                        f"(cooldown {cooldown} min, {remaining:.0f} min left). "
                        f"Enable \"Force\" to override."
                    ),
                )

    # Prune old finished jobs before adding a new one
    _purge_expired_jobs()

    job_id = str(uuid.uuid4())[:8]
    _started_at = datetime.now(timezone.utc).isoformat()
    _admin_jobs[job_id] = {
        "job_id":     job_id,
        "season":     season,
        "task":       task,
        "label":      _TASK_META[task],
        "status":     "running",
        "progress":   0,
        "stats":      {},
        "log_lines":  [],
        "error":      None,
        "started_at": _started_at,
    }
    t = asyncio.create_task(_run(job_id, season, task, force, max_tier=max_tier), name=f"job-{job_id}")
    _admin_tasks[job_id] = t
    return {"job_id": job_id, "season": season, "task": task, "label": _TASK_META[task], "started_at": _started_at}


_JOB_EXPIRY_SECS = 300  # auto-purge finished jobs after 5 minutes


@app.get("/admin/api/jobs")
async def admin_list_jobs(_: None = Depends(require_admin)):
    """Return all known manual jobs (running + completed)."""
    _purge_expired_jobs()
    return list(_admin_jobs.values())


def _purge_expired_jobs():
    """Remove finished _admin_jobs older than _JOB_EXPIRY_SECS."""
    now = datetime.now(timezone.utc)
    expired = [
        jid for jid, j in list(_admin_jobs.items())
        if j.get("status") in ("done", "error", "stopped")
        and "finished_at" in j
        and (now - datetime.fromisoformat(j["finished_at"])).total_seconds() > _JOB_EXPIRY_SECS
    ]
    for jid in expired:
        _admin_jobs.pop(jid, None)


@app.get("/admin/api/jobs/{job_id}")
async def admin_job_status(job_id: str, _: None = Depends(require_admin)):
    """Return current status and buffered log lines for a running job.

    log_lines   – lines accumulated since the last GET (drained on read)
    log_history – all lines from previous drains (persistent, not drained)
                  Clients should display this on first encounter of a job
                  so that a page refresh restores the output context.
    """
    job = _admin_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    log_lines = job.pop("log_lines", [])
    job["log_lines"] = []
    # Return a snapshot of history *before* extending it with this batch,
    # so clients can show history + current lines without duplicates.
    history_snapshot = list(job.get("log_history", []))
    history = job.setdefault("log_history", [])
    history.extend(log_lines)
    if len(history) > 400:
        del history[:len(history) - 400]
    return {**job, "log_lines": log_lines, "log_history": history_snapshot}


@app.delete("/admin/api/jobs/{job_id}")
async def admin_stop_job(job_id: str, _: None = Depends(require_admin)):
    """Cancel a running job."""
    job = _admin_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "running":
        return {"ok": False, "detail": f"Job is already {job.get('status')}"}
    task = _admin_tasks.get(job_id)
    if task and not task.done():
        task.cancel()
    job["status"] = "stopped"
    job["error"]  = "Cancelled by user"
    job["log_lines"].append({"level": "warn", "msg": "Job cancelled by user"})
    _admin_tasks.pop(job_id, None)
    logger.info("Admin job %s cancelled by user", job_id)
    return {"ok": True, "job_id": job_id}


_LAYER_DELETE_ORDER = [
    # (model_class, filter_col) — ordered leaf-first so FK constraints aren't violated
    ("GameEvent",         "season_id"),
    ("GamePlayer",        "season_id"),
    ("Game",              "season_id"),
    ("LeagueGroup",       None),          # handled via League cascade
    ("League",            "season_id"),
    ("PlayerStatistics",  "season_id"),
    ("TeamPlayer",        "season_id"),
    ("Team",              "season_id"),
    ("Club",              "season_id"),
]

_LAYER_SETS: dict[str, list[str]] = {
    "events":       ["GameEvent"],
    "games":        ["GameEvent", "GamePlayer", "Game"],
    "groups":       ["GameEvent", "GamePlayer", "Game", "LeagueGroup"],
    "leagues":      ["GameEvent", "GamePlayer", "Game", "LeagueGroup", "League"],
    "player_stats": ["PlayerStatistics"],
    "players":      ["PlayerStatistics", "TeamPlayer"],
    "teams":        ["PlayerStatistics", "TeamPlayer", "Team"],
    "clubs":        ["PlayerStatistics", "TeamPlayer", "Team", "Club"],
    "all":          [m for m, _ in _LAYER_DELETE_ORDER],
}


@app.post("/admin/api/season/{season_id}/set-current")
async def admin_set_current_season(season_id: int, _: None = Depends(require_admin)):
    """Mark a season as the current active season (clears flag on all others)."""
    from app.services.database import get_database_service
    from app.models.db_models import Season
    db = get_database_service()
    with db.session_scope() as session:
        if not session.query(Season).filter(Season.id == season_id).first():
            raise HTTPException(status_code=404, detail=f"Season {season_id} not found")
        session.query(Season).update({Season.highlighted: False})
        session.query(Season).filter(Season.id == season_id).update({Season.highlighted: True})
    return {"ok": True, "current_season": season_id}


@app.delete("/admin/api/season/{season_id}")
async def admin_delete_season_layer(season_id: int, layer: str = "all", _: None = Depends(require_admin)):
    """Delete indexed data for a season layer.

    layer values: all | clubs | teams | players | player_stats |
                  leagues | groups | games | events
    """
    from app.models.db_models import (
        Club, League, LeagueGroup, Team, TeamPlayer, PlayerStatistics,
        Game, GamePlayer, GameEvent, SyncStatus
    )
    model_map = {
        "Club": Club, "League": League, "LeagueGroup": LeagueGroup,
        "Team": Team, "TeamPlayer": TeamPlayer,
        "PlayerStatistics": PlayerStatistics,
        "Game": Game, "GamePlayer": GamePlayer, "GameEvent": GameEvent,
    }

    layer = layer.lower()
    if layer not in _LAYER_SETS:
        raise HTTPException(status_code=400, detail=f"Unknown layer '{layer}'. Valid: {list(_LAYER_SETS)}")

    targets = _LAYER_SETS[layer]

    from app.services.database import get_database_service
    db = get_database_service()
    totals: dict[str, int] = {}

    with db.session_scope() as session:
        # Use the global ordered list so we always delete in safe (leaf-first) order
        for model_name, filter_col in _LAYER_DELETE_ORDER:
            if model_name not in targets:
                continue
            model_cls = model_map[model_name]
            if model_name == "LeagueGroup":
                # Delete via parent league IDs to respect FK
                league_ids = [
                    r[0] for r in session.query(League.id).filter(League.season_id == season_id).all()
                ]
                if league_ids:
                    n = session.query(LeagueGroup).filter(LeagueGroup.league_id.in_(league_ids)).delete(synchronize_session=False)
                else:
                    n = 0
            else:
                n = session.query(model_cls).filter(
                    getattr(model_cls, filter_col) == season_id
                ).delete(synchronize_session=False)
            totals[model_name] = n

        # Also clean up SyncStatus rows for this season
        if layer == "all":
            session.query(SyncStatus).filter(
                SyncStatus.entity_id == f"season:{season_id}"
            ).delete(synchronize_session=False)

    logger.info("Admin deleted season=%s layer=%s — %s", season_id, layer, totals)
    return {"ok": True, "season_id": season_id, "layer": layer, "deleted": totals}


@app.get("/admin/api/scheduler")
async def admin_scheduler_status(_: None = Depends(require_admin)):
    """Return the scheduler queue and recent history."""
    from app.services.scheduler import get_scheduler
    sched = get_scheduler()
    if not sched:
        return {"enabled": False, "queue": [], "history": []}
    return {
        "enabled": sched.enabled,
        "queue":   sched.get_schedule(),
        "history": sched.get_history(200),
        "season_filter": sched.get_season_filter(),
        "policy_tiers": sched.get_policy_tiers(),
        "running": sched._count_running(),
    }


@app.post("/admin/api/scheduler")
async def admin_scheduler_control(payload: dict, _: None = Depends(require_admin)):
    """Control the scheduler.

    payload options:
      { "action": "enable" }            – resume auto-scheduling
      { "action": "disable" }           – pause auto-scheduling
      { "action": "trigger", "policy": "clubs", "season": 2025 }  – run now
    """
    from app.services.scheduler import get_scheduler
    sched = get_scheduler()
    if not sched:
        raise HTTPException(status_code=503, detail="Scheduler not running")

    action = payload.get("action")
    if action == "enable":
        sched.enable(True)
        return {"ok": True, "enabled": True}
    if action == "disable":
        sched.enable(False)
        return {"ok": True, "enabled": False}
    if action == "season_filter":
        min_season = payload.get("min_season")  # int or null
        excluded   = payload.get("excluded_seasons", [])
        if min_season is not None and not isinstance(min_season, int):
            raise HTTPException(status_code=400, detail="min_season must be an integer or null")
        if not isinstance(excluded, list) or not all(isinstance(s, int) for s in excluded):
            raise HTTPException(status_code=400, detail="excluded_seasons must be a list of integers")
        sched.set_season_filter(min_season, excluded)
        return {"ok": True, **sched.get_season_filter()}
    if action == "max_concurrent":
        n = payload.get("value", 2)
        if not isinstance(n, int) or n < 1:
            raise HTTPException(status_code=400, detail="value must be a positive integer")
        sched.set_max_concurrent(n)
        return {"ok": True, "max_concurrent": sched._max_concurrent}
    if action == "player_game_stats_workers":
        n = payload.get("value", 10)
        if not isinstance(n, int) or n < 1:
            raise HTTPException(status_code=400, detail="value must be a positive integer")
        sched.set_player_game_stats_workers(n)
        return {"ok": True, "player_game_stats_workers": sched._player_game_stats_workers}
    if action == "policy_tiers":
        tiers_raw = payload.get("tiers", {})
        if not isinstance(tiers_raw, dict):
            raise HTTPException(status_code=400, detail="tiers must be a dict mapping policy name to tier (1-6)")
        tiers: dict[str, int] = {}
        for k, v in tiers_raw.items():
            if not isinstance(v, int) or not 1 <= v <= 6:
                raise HTTPException(status_code=400, detail=f"tier for '{k}' must be an integer 1–6")
            tiers[k] = v
        sched.set_policy_tiers(tiers)
        return {"ok": True, "policy_tiers": sched.get_policy_tiers()}
    if action == "clear_done":
        removed = sched.clear_done()
        # Only protect entries whose _watch() coroutine is still active.
        # _watch() polls _admin_jobs every 2 s; if the entry disappears before
        # _watch() gets a chance to read "done", it counts 3 consecutive misses
        # and marks the JobRecord as "error" → immediate re-queue → storm.
        # Once _watch() has seen "done" and exited it sets the JobRecord to
        # "done"/"error" — at that point removing the _admin_jobs entry is safe.
        # We therefore protect only entries whose JobRecord is still running.
        active_watch_ids = {
            r.job_id for r in sched._history
            if r.status in ("pending", "running")
        }
        finished_ids = [
            jid for jid, j in list(_admin_jobs.items())
            if j.get("status") in ("done", "error", "stopped")
            and jid not in active_watch_ids
        ]
        for jid in finished_ids:
            _admin_jobs.pop(jid, None)
        return {"ok": True, "removed": removed + len(finished_ids)}
    if action == "trigger":
        policy = payload.get("policy")
        season = payload.get("season")
        if not isinstance(policy, str):
            raise HTTPException(status_code=400, detail="Missing or invalid 'policy'")
        job_id = await sched.trigger_now(policy, season)
        if job_id is None:
            raise HTTPException(status_code=400, detail=f"Unknown policy '{policy}'")
        # Return enough info for the UI to register and poll the job
        job_entry = _admin_jobs.get(job_id, {})
        return {
            "ok":     True,
            "policy": policy,
            "season": season,
            "job_id": job_id,
            "label":  job_entry.get("label", f"{policy} S{season}"),
            "task":   job_entry.get("task", policy),
        }
    raise HTTPException(status_code=400, detail=f"Unknown action '{action}'")


@app.get("/admin/api/rendering")
async def admin_rendering_get(_: None = Depends(require_admin)):
    """Return current rendering exclusion config."""
    return _rcfg.get_config()


@app.post("/admin/api/rendering")
async def admin_rendering_post(payload: dict, _: None = Depends(require_admin)):
    """Update rendering exclusion config.

    Accepts the full config object:
      {
        "excluded_league_ids":   [1, 2],
        "excluded_league_names": ["Herren Test"],
        "excluded_club_ids":     [],
        "excluded_club_names":   ["Test Club"],
        "excluded_team_ids":     [],
        "excluded_team_names":   []
      }
    """
    try:
        updated = _rcfg.set_config(payload)
        return {"ok": True, **updated}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/admin/api/purge")
async def admin_purge_seasons(payload: dict, _: None = Depends(require_admin)):
    """Purge data for one or more seasons as a background job.

    payload:
      { "season": 2022, "mode": "exact|older|older-or-equal|newer|newer-or-equal", "dry_run": false }
    """
    season  = payload.get("season")
    mode    = payload.get("mode", "exact")
    dry_run = bool(payload.get("dry_run", False))

    VALID_MODES = {"exact", "older", "older-or-equal", "newer", "newer-or-equal"}
    if not isinstance(season, int):
        raise HTTPException(status_code=400, detail="season must be an integer")
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {VALID_MODES}")

    job_id = str(uuid.uuid4())[:8]
    label  = f"purge season {season} [{mode}]" + (" (dry-run)" if dry_run else "")
    _admin_jobs[job_id] = {
        "job_id":    job_id,
        "season":    season,
        "task":      "purge",
        "label":     label,
        "status":    "running",
        "progress":  0,
        "stats":     {},
        "log_lines": [],
        "error":     None,
    }
    task = asyncio.create_task(
        _run_purge(job_id, season, mode, dry_run),
        name=f"purge-{job_id}",
    )
    _admin_tasks[job_id] = task
    logger.info("Admin purge job %s started — season=%s mode=%s dry_run=%s", job_id, season, mode, dry_run)
    return {"ok": True, "job_id": job_id, "label": label}


async def _run_purge(job_id: str, season: int, mode: str, dry_run: bool):
    """Background coroutine for multi-season purge."""
    job = _admin_jobs[job_id]

    def push(level: str, msg: str):
        job["log_lines"].append({"level": level, "msg": msg})
        logger.info("[admin %s] %s", job_id, msg)

    try:
        from app.services.database import get_database_service
        from app.models.db_models import (
            Season, Club, League, LeagueGroup, Team, Player,
            TeamPlayer, Game, GamePlayer, GameEvent, PlayerStatistics, SyncStatus,
        )
        from sqlalchemy import func, or_ as sa_or

        CHUNK = 500

        def batched_count(session, model, col, ids: list) -> int:
            if not ids:
                return 0
            total = 0
            for i in range(0, len(ids), CHUNK):
                total += session.query(func.count(model.id)).filter(
                    col.in_(ids[i: i + CHUNK])
                ).scalar() or 0
            return total

        def batched_delete(session, model, col, ids: list) -> int:
            if not ids:
                return 0
            total = 0
            for i in range(0, len(ids), CHUNK):
                total += session.query(model).filter(
                    col.in_(ids[i: i + CHUNK])
                ).delete(synchronize_session=False)
            return total

        op_map = {
            "exact":          lambda col: col == season,
            "older":          lambda col: col < season,
            "older-or-equal": lambda col: col <= season,
            "newer":          lambda col: col > season,
            "newer-or-equal": lambda col: col >= season,
        }
        season_filter = op_map[mode]

        db = get_database_service()

        with db.session_scope() as session:
            target_ids = [
                r[0] for r in session.query(Season.id).filter(season_filter(Season.id)).all()
            ]

        if not target_ids:
            push("warn", f"No seasons found matching mode='{mode}' season={season}.")
            job["status"] = "done"
            job["progress"] = 100
            return

        push("info", f"Seasons to purge ({len(target_ids)}): {sorted(target_ids)}")
        job["progress"] = 5

        # Fetch IDs once — reused for both counting and deleting to avoid TOCTOU.
        with db.session_scope() as session:
            game_ids = [r[0] for r in session.query(Game.id).filter(Game.season_id.in_(target_ids)).all()]
            league_ids = [r[0] for r in session.query(League.id).filter(League.season_id.in_(target_ids)).all()]

        sync_filters = sa_or(*[
            SyncStatus.entity_id.like(f"%:{s}:%") | SyncStatus.entity_id.like(f"%:{s}")
            for s in target_ids
        ]) if target_ids else (SyncStatus.id == -1)

        with db.session_scope() as session:
            counts = {
                "GameEvent":        batched_count(session, GameEvent,        GameEvent.game_id,           game_ids),
                "GamePlayer":       batched_count(session, GamePlayer,       GamePlayer.game_id,          game_ids),
                "PlayerStatistics": batched_count(session, PlayerStatistics, PlayerStatistics.season_id,  target_ids),
                "TeamPlayer":       batched_count(session, TeamPlayer,       TeamPlayer.season_id,        target_ids),
                "Game":             len(game_ids),
                "LeagueGroup":      batched_count(session, LeagueGroup,      LeagueGroup.league_id,       league_ids),
                "Team":             batched_count(session, Team,             Team.season_id,              target_ids),
                "Club":             batched_count(session, Club,             Club.season_id,              target_ids),
                "League":           len(league_ids),
                "SyncStatus":       session.query(func.count(SyncStatus.id)).filter(sync_filters).scalar() or 0,
                "Season":           len(target_ids),
            }

        total_rows = sum(counts.values())
        for name, n in counts.items():
            push("info", f"  {name:20s}: {n:>8,}")
        push("info", f"  {'TOTAL':20s}: {total_rows:>8,}")
        job["progress"] = 15

        if dry_run:
            push("warn", "[dry-run] Nothing deleted.")
            job["status"]   = "done"
            job["progress"] = 100
            job["stats"]    = counts
            return

        push("info", "Deleting...")

        # Each step runs in its own session_scope so the write lock is held
        # only for the duration of that step, not the entire purge.
        deleted: dict[str, int] = {}
        steps = [
            ("GameEvent",        lambda s: batched_delete(s, GameEvent,        GameEvent.game_id,           game_ids)),
            ("GamePlayer",       lambda s: batched_delete(s, GamePlayer,       GamePlayer.game_id,          game_ids)),
            ("PlayerStatistics", lambda s: batched_delete(s, PlayerStatistics, PlayerStatistics.season_id,  target_ids)),
            ("TeamPlayer",       lambda s: batched_delete(s, TeamPlayer,       TeamPlayer.season_id,        target_ids)),
            ("Game",             lambda s: batched_delete(s, Game,             Game.season_id,              target_ids)),
            ("LeagueGroup",      lambda s: batched_delete(s, LeagueGroup,      LeagueGroup.league_id,       league_ids)),
            ("Team",             lambda s: batched_delete(s, Team,             Team.season_id,              target_ids)),
            ("Club",             lambda s: batched_delete(s, Club,             Club.season_id,              target_ids)),
            ("League",           lambda s: batched_delete(s, League,           League.season_id,            target_ids)),
        ]
        for i, (name, fn) in enumerate(steps, 1):
            with db.session_scope() as session:
                n = fn(session)
            deleted[name] = n
            push("ok", f"  Deleted {n:,} {name} rows")
            job["progress"] = 15 + int(i / (len(steps) + 3) * 75)
            await asyncio.sleep(0)  # yield to event loop between steps

        with db.session_scope() as session:
            n = session.query(SyncStatus).filter(sync_filters).delete(synchronize_session=False)
        deleted["SyncStatus"] = n
        push("ok", f"  Deleted {n:,} SyncStatus rows")
        job["progress"] = 15 + int((len(steps) + 1) / (len(steps) + 3) * 75)
        await asyncio.sleep(0)

        with db.session_scope() as session:
            n = batched_delete(session, Season, Season.id, target_ids)
        deleted["Season"] = n
        push("ok", f"  Deleted {n:,} Season rows")

        # Orphaned players: no TeamPlayer AND no GamePlayer rows anywhere.
        # Run after all season data is deleted so the joins reflect final state.
        with db.session_scope() as session:
            orphan_ids = [
                r[0] for r in
                session.query(Player.person_id)
                .outerjoin(TeamPlayer, TeamPlayer.player_id == Player.person_id)
                .outerjoin(GamePlayer, GamePlayer.player_id == Player.person_id)
                .filter(TeamPlayer.player_id.is_(None))
                .filter(GamePlayer.player_id.is_(None))
                .all()
            ]
            if orphan_ids:
                n = batched_delete(session, Player, Player.person_id, orphan_ids)
                deleted["Player (orphaned)"] = n
                push("ok", f"  Deleted {n:,} orphaned Player rows")

        total_deleted = sum(deleted.values())
        push("ok", f"✓ Purge complete — {total_deleted:,} rows deleted across {len(target_ids)} season(s).")
        logger.info("Admin purge %s complete — %s rows", job_id, total_deleted)
        job["status"]   = "done"
        job["progress"] = 100
        job["stats"]    = deleted

    except Exception as exc:
        push("error", f"Purge failed: {exc}")
        logger.exception("Purge job %s failed", job_id)
        job["status"] = "error"
        job["error"]  = str(exc)
        job["progress"] = 100


# ==================== END ADMIN ROUTES ====================


async def _run(job_id: str, season: int | None, task: str, force: bool, max_tier: int = 7):
    """Module-level coroutine that drives a single indexing job.

    Args:
        max_tier: For players (roster) and events tasks, only process leagues
                  with tier <= max_tier.  1=L-UPL/NLA only, 2=+NLB, … 7=all
                  (default auto-detects from leagues indexed for the season).
    """
    job = _admin_jobs[job_id]

    def push(level: str, msg: str):
        job["log_lines"].append({"level": level, "msg": msg})
        logger.info("[admin %s] %s", job_id, msg)

    def set_progress(pct: int):
        job["progress"] = min(pct, 99)

    try:
        from app.services.data_indexer import get_data_indexer
        from app.services.database import get_database_service
        from app.services.repair_service import get_repair_service
        from app.models.db_models import Club, Team, League, Game
        indexer        = get_data_indexer()
        db_service     = get_database_service()
        repair_service = get_repair_service()

        stats: dict = {}

        # Resolve None season: use current season as default for all non-season tasks
        if season is None:
            season = get_current_season()

        # ── GUARD: skip future seasons ─────────────────────────────────────
        if task != "seasons" and season is not None:
            current = get_current_season()
            if season > current:
                push("warn", f"Season {season} is beyond the flagged current season ({current}). Skipping.")
                job["status"]   = "done"
                job["progress"] = 100
                job["stats"]    = stats
                return

        # ── SEASONS ────────────────────────────────────────────────────────
        if task == "seasons":
            push("info", "Fetching seasons list from API...")
            n = await asyncio.to_thread(indexer.index_seasons, force=True)
            stats["seasons"] = n
            push("ok", f"Seasons: {n}")
            set_progress(100)

        # ── CLUBS ──────────────────────────────────────────────────────────
        if task in ("clubs", "clubs_path", "full"):
            push("info", f"Indexing clubs for season {season}...")
            n = await asyncio.to_thread(indexer.index_clubs, season, force=force)
            stats["clubs"] = n
            push("ok", f"Clubs: {n}")
            set_progress(10)

        # ── TEAMS ──────────────────────────────────────────────────────────
        if task in ("teams", "clubs_path", "full"):
            with db_service.session_scope() as s:
                club_list = [(c.id, c.name) for c in
                             s.query(Club).filter(Club.season_id == season).all()]
            total = len(club_list)
            push("info", f"Indexing teams for {total} clubs...")
            teams_n = 0
            team_id_list = []
            for i, (cid, cname) in enumerate(club_list, 1):
                await _backoff_if_busy()
                cnt, tids = await asyncio.to_thread(indexer.index_teams_for_club, cid, season, force=force)
                teams_n += cnt
                team_id_list.extend(tids)
                set_progress(10 + int(i / total * 25))
            stats["teams"] = teams_n
            push("ok", f"Teams: {teams_n}")
            await asyncio.to_thread(indexer.record_season_sync, "teams", season, teams_n)

        # ── PLAYERS ────────────────────────────────────────────────────────
        if task in ("players", "clubs_path", "full"):
            from app.services.data_indexer import league_tier as _lt
            # Auto-detect effective tier from leagues already indexed for this season
            effective_tier_p = max_tier
            if max_tier == 7:
                with db_service.session_scope() as _sp:
                    _lids = [r[0] for r in
                             _sp.query(League.league_id).filter(League.season_id == season).all()]
                if _lids:
                    effective_tier_p = max(_lt(lid) for lid in _lids)
            # Build tier-filtered team list fresh (ensures newly indexed teams are included)
            with db_service.session_scope() as s:
                _t_rows = s.query(Team.id, Team.league_id).filter(Team.season_id == season).distinct().all()
            team_id_list = [r[0] for r in _t_rows if _lt(r[1] or 0) <= effective_tier_p]
            auto_lbl_p = " (auto)" if max_tier == 7 else ""
            total = len(team_id_list)
            push("info", f"Indexing players for {total} teams (tier ≤ {effective_tier_p}{auto_lbl_p})...")
            players_n = 0
            for i, tid in enumerate(team_id_list, 1):
                await _backoff_if_busy()
                players_n += await asyncio.to_thread(indexer.index_players_for_team, tid, season, force=force)
                set_progress(35 + int(i / total * 25) if total else 60)
            stats["players"] = players_n
            push("ok", f"Players: {players_n}")
            await asyncio.to_thread(indexer.record_season_sync, "players", season, players_n)

        # ── PLAYER STATS ───────────────────────────────────────────────────
        if task in ("player_stats", "clubs_path", "full"):
            _exact_tier_ps = max_tier if max_tier < 7 else None
            _tier_lbl_ps   = f" (tier {max_tier} only)" if _exact_tier_ps else ""
            push("info", f"Indexing player statistics for season {season}{_tier_lbl_ps}...")
            stats_n = await asyncio.to_thread(
                indexer.index_player_stats_for_season,
                season, force=force, exact_tier=_exact_tier_ps,
                on_progress=set_progress,
            )
            stats["player_stats"] = stats_n
            push("ok", f"Player stats: {stats_n}")
            await asyncio.to_thread(indexer.record_season_sync, "player_stats", season, stats_n)
            set_progress(60)

        # ── GAME LINEUPS (standalone — without events) ─────────────────────
        if task == "game_lineups":
            from app.services.data_indexer import league_tier
            effective_tier_gl = max_tier if max_tier != 7 else 3
            with db_service.session_scope() as s:
                t_rows = s.query(Team.id, Team.league_id).filter(Team.season_id == season).distinct().all()
            t_ids = {r[0] for r in t_rows if league_tier(r[1] or 0) <= effective_tier_gl}
            with db_service.session_scope() as s:
                game_ids_gl = [
                    g.id for g in s.query(Game.id).filter(
                        Game.season_id == season,
                        Game.home_score.isnot(None),
                        (Game.home_team_id.in_(t_ids)) | (Game.away_team_id.in_(t_ids)),
                    ).all()
                ]
            total_gl = len(game_ids_gl)
            push("info", f"Indexing lineups for {total_gl} games (tier ≤ {effective_tier_gl})...")
            lineup_n2 = 0
            for i, gid in enumerate(game_ids_gl, 1):
                await _backoff_if_busy()
                lineup_n2 += max(0, await asyncio.to_thread(indexer.index_game_lineup, gid, season, force=force))
                set_progress(int(i / total_gl * 95) if total_gl else 99)
            stats["game_lineups"] = lineup_n2
            push("ok", f"Game lineups: {lineup_n2}")
            await asyncio.to_thread(indexer.record_season_sync, "game_lineups", season, lineup_n2)

        # ── PLAYER GAME STATS (standalone or as part of full) ──────────────
        if task in ("player_game_stats", "full"):
            # max_tier < 7 means this is a tier-specific scheduler policy run
            _exact_tier = max_tier if max_tier < 7 else None
            _tier_lbl   = f" (tier {max_tier} only)" if _exact_tier else ""
            push("info", f"Updating per-game G/A/PIM for season {season}{_tier_lbl}...")
            from app.services.scheduler import get_scheduler as _get_sched
            pgstats_n = await asyncio.to_thread(
                indexer.index_player_game_stats_for_season,
                season_id=season, force=force, exact_tier=_exact_tier,
                on_progress=set_progress,
                max_workers=getattr(_get_sched(), "_player_game_stats_workers", 10),
            )
            stats["player_game_stats"] = pgstats_n
            push("ok", f"Player game stats: {pgstats_n}")
            if not _exact_tier:  # scheduler tier-runs use their own entity_type keys
                await asyncio.to_thread(indexer.record_season_sync, "player_game_stats", season, pgstats_n)

        # ── LEAGUES ────────────────────────────────────────────────────────
        if task in ("leagues", "groups", "games", "leagues_path", "full"):
            push("info", f"Indexing leagues for season {season}...")
            n = await asyncio.to_thread(indexer.index_leagues, season, force=force)
            stats["leagues"] = n
            push("ok", f"Leagues: {n}")
            set_progress(62)

        # ── GROUPS ─────────────────────────────────────────────────────────
        lg_list: list[tuple] = []
        if task in ("groups", "games", "leagues_path", "full"):
            with db_service.session_scope() as s:
                lg_list = [(lg.id, lg.league_id, lg.game_class) for lg in
                           s.query(League).filter(League.season_id == season).all()]
            total  = len(lg_list)
            groups_n = 0
            push("info", f"Indexing groups for {total} leagues...")
            for i, (ldb, lid, gc) in enumerate(lg_list, 1):
                await _backoff_if_busy()
                groups_n += await asyncio.to_thread(indexer.index_groups_for_league, ldb, season, lid, gc, force=force)
                set_progress(62 + int(i / total * 13))
            stats["league_groups"] = groups_n
            push("ok", f"Groups: {groups_n}")
            # Write season-level sentinel so the scheduler's _last_sync_for()
            # finds a "league_groups / season:{season}" row with the right entity_type.
            # Without this the scheduler re-queues league_groups every 5-min tick.
            await asyncio.to_thread(indexer.record_season_sync, "league_groups", season, groups_n)

        # ── GAMES ──────────────────────────────────────────────────────────
        if task in ("games", "leagues_path", "full"):
            from app.models.db_models import LeagueGroup
            if not lg_list:
                with db_service.session_scope() as s:
                    lg_list = [(lg.id, lg.league_id, lg.game_class) for lg in
                               s.query(League).filter(League.season_id == season).all()]
            # Build per-group work list so each group gets its own API call
            work: list[tuple] = []  # (league_db_id, league_id, game_class, group_db_id, group_name)
            with db_service.session_scope() as s:
                for ldb, lid, gc in lg_list:
                    grps = s.query(LeagueGroup).filter(LeagueGroup.league_id == ldb).all()
                    if grps:
                        for grp in grps:
                            work.append((ldb, lid, gc, grp.id, grp.name))
                    else:
                        work.append((ldb, lid, gc, None, None))
            total  = len(work)
            games_n = 0
            push("info", f"Indexing games for {total} groups across {len(lg_list)} leagues (batch concurrency=2)...")

            # Process in small batches so the event loop stays responsive
            _GAMES_BATCH = 4
            for batch_start in range(0, max(total, 1), _GAMES_BATCH):
                await _backoff_if_busy()
                batch = work[batch_start:batch_start + _GAMES_BATCH]
                batch_results = await asyncio.gather(
                    *(asyncio.to_thread(
                        indexer.index_games_for_league,
                        ldb, season, lid, gc,
                        group_name=grp_name, group_db_id=grp_db_id,
                        force=force,
                    ) for ldb, lid, gc, grp_db_id, grp_name in batch),
                    return_exceptions=True,
                )
                for r in batch_results:
                    if isinstance(r, int):
                        games_n += r
                done = min(batch_start + _GAMES_BATCH, total)
                set_progress(75 + int(done / total * 20) if total else 95)
            stats["games"] = games_n
            push("ok", f"Games: {games_n}")
            # Season-level sentinel: games entity_ids are "games:league:{id}" (no season year)
            await asyncio.to_thread(indexer.record_season_sync, "games", season, games_n)

        # ── BACKFILL TEAM NAMES ────────────────────────────────────────────
        if task in ("team_names", "games", "leagues_path", "full"):
            push("info", "Backfilling team names from rankings API...")
            n = await asyncio.to_thread(indexer.backfill_team_names, season, force=force)
            stats["team_names"] = n
            push("ok", f"Team names backfilled: {n}")

        # ── GAME EVENTS ────────────────────────────────────────────────────
        if task in ("events", "full"):
            from app.services.data_indexer import league_tier
            from app.models.db_models import LeagueGroup, League as _League
            _now = datetime.now(timezone.utc)

            # Auto-detect effective tier from leagues actually indexed for this season
            effective_tier = max_tier
            if max_tier == 7:
                with db_service.session_scope() as _s2:
                    _db_lids = [
                        r[0]
                        for r in _s2.query(_League.league_id)
                        .filter(_League.season_id == season)
                        .all()
                    ]
                if _db_lids:
                    effective_tier = max(league_tier(lid) for lid in _db_lids)

            with db_service.session_scope() as s:
                # Join Game → League to filter by tier.
                # Also include games with NULL game_date that are finished or
                # already have a score — these were played but date parsing failed.
                from sqlalchemy import or_
                rows = (
                    s.query(Game.id, Game.season_id, _League.league_id)
                    .join(LeagueGroup, Game.group_id == LeagueGroup.id, isouter=True)
                    .join(_League, LeagueGroup.league_id == _League.id, isouter=True)
                    .filter(
                        Game.season_id == season,
                        or_(
                            Game.game_date < _now,
                            Game.home_score.isnot(None),   # scored but date missing
                            Game.status == "finished",     # finished but date missing
                        ),
                    )
                    .all()
                )
                finished = [
                    (r.id, r.season_id)
                    for r in rows
                    if league_tier(r.league_id or 0) <= effective_tier
                ]
            total    = len(finished)
            auto_lbl = " (auto)" if max_tier == 7 else ""
            tier_lbl = f"tier ≤ {effective_tier}{auto_lbl}"

            # ── Bulk pre-filter: skip games already indexed within max_age ──
            if not force:
                events_eids = [f"game:{gid}:events" for gid, _ in finished]
                lineup_eids = [f"game:{gid}:lineup" for gid, _ in finished]
                fresh_ev = indexer.bulk_already_indexed("game_events", events_eids, 720)
                fresh_ln = indexer.bulk_already_indexed("game_lineup", lineup_eids, 720)
                pre_count = len(finished)
                finished = [
                    (gid, sid) for gid, sid in finished
                    if f"game:{gid}:events" not in fresh_ev
                    or f"game:{gid}:lineup" not in fresh_ln
                ]
                skipped = pre_count - len(finished)
                if skipped:
                    push("info", f"  Skipping {skipped} already-indexed game(s).")

            total    = len(finished)
            push("info", f"Indexing events + lineups for {total} past games ({tier_lbl}, batch concurrency=2)...")
            events_n = 0
            lineup_n = 0

            # Process in small batches (6 games at a time) so the event loop
            # stays responsive for admin API requests between batches.
            _EV_BATCH = 6
            for batch_start in range(0, max(total, 1), _EV_BATCH):
                await _backoff_if_busy()
                batch = finished[batch_start:batch_start + _EV_BATCH]
                batch_results = await asyncio.gather(
                    *(asyncio.gather(
                        asyncio.to_thread(indexer.index_game_events, gid, sid_, force=force),
                        asyncio.to_thread(indexer.index_game_lineup, gid, sid_, force=force),
                    ) for gid, sid_ in batch),
                    return_exceptions=True,
                )
                for r in batch_results:
                    if not isinstance(r, Exception) and isinstance(r, (list, tuple)) and len(r) == 2:
                        events_n += r[0]
                        lineup_n += r[1]
                done = min(batch_start + _EV_BATCH, total)
                set_progress(int(done / total * 95) if total else 99)
            stats["game_events"] = events_n
            stats["lineups"] = lineup_n
            push("ok", f"Game events: {events_n}  Lineups: {lineup_n}")
            # Season-level sentinel: game_events entity_ids are "game:{id}:events" (no season year)
            await asyncio.to_thread(indexer.record_season_sync, "game_events", season, events_n)

        # ── UPCOMING GAMES ─────────────────────────────────────────────────
        if task == "upcoming_games":
            push("info", "Indexing upcoming games...")
            n = await asyncio.to_thread(indexer.index_upcoming_games, season, force=force)
            stats["transitioned"] = n
            push("ok", f"Upcoming games: {n}")
            await asyncio.to_thread(indexer.record_season_sync, "upcoming_games", season, n)

        # ── POST-GAME COMPLETION ────────────────────────────────────────────
        if task == "post_game_completion":
            push("info", "Indexing post-game completion...")
            n = await asyncio.to_thread(indexer.index_post_game_completion, season, force=force)
            stats["transitioned"] = n
            push("ok", f"Post-game completion: {n}")
            await asyncio.to_thread(indexer.record_season_sync, "post_game_completion", season, n)

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

        job["stats"]    = stats
        job["progress"] = 100
        job["status"]   = "done"
        summary = "  ".join(f"{k}={v}" for k, v in stats.items())
        push("ok", f"Done — {summary}")

    except asyncio.CancelledError:
        job["status"] = "stopped"
        job["error"]  = "Cancelled"
        logger.info("Admin indexing job %s was cancelled", job_id)
        raise  # let asyncio clean up properly
    except Exception as exc:
        job["status"] = "error"
        job["error"]  = f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"
        logger.error("Admin indexing job %s failed: %s", job_id, exc, exc_info=True)
    finally:
        if job.get("status") in ("done", "error", "stopped"):
            now_utc = datetime.now(timezone.utc)
            job["finished_at"] = now_utc.isoformat()
            if job.get("status") == "done":
                _job_last_done[(task, season)] = now_utc
                _persist_cooldowns()
        _admin_tasks.pop(job_id, None)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/cache/status")
async def cache_status():
    """Cache status endpoint - shows hybrid cache statistics"""
    from app.services.data_cache import get_data_cache
    cache = get_data_cache()
    stats = cache.get_stats()

    if stats["all_loaded"]:
        status = "fully_loaded"
    elif stats["teams_popular_loaded"]:
        status = "popular_teams_loaded"
    else:
        status = "partially_loaded"

    return {
        "status": status,
        "teams_loaded_all": stats["teams_loaded"],
        "teams_loaded_popular": stats["teams_popular_loaded"],
        "clubs_loaded": stats["clubs_loaded"],
        "leagues_loaded": stats["leagues_loaded"],
        "teams_count": stats["teams_count"],
        "clubs_count": stats["clubs_count"],
        "leagues_count": stats["leagues_count"],
        "last_updated": stats["last_updated"],
        "total_records": stats["teams_count"] + stats["clubs_count"] + stats["leagues_count"]
    }


@app.get("/{locale}", response_class=HTMLResponse)
async def home(request: Request, locale: str, league_category: str = "all"):
    """Homepage with upcoming games + overall top scorers"""
    from app.services.stats_service import get_upcoming_games, get_latest_results, get_overall_top_scorers
    from app.services.database import get_database_service
    from app.models.db_models import League, PlayerStatistics
    from app.services.data_indexer import league_tier
    from sqlalchemy import distinct, func
    
    # Active season = the highlighted (current) season that has any player stats;
    # fall back to the season with most stats rows (avoids showing last year while
    # current season indexing is still in progress).
    db = get_database_service()
    with db.session_scope() as session:
        from app.models.db_models import Season as SeasonModel
        highlighted = (
            session.query(SeasonModel.id)
            .filter(SeasonModel.highlighted == True)
            .scalar()
        )
        if highlighted:
            has_stats = (
                session.query(PlayerStatistics.id)
                .filter(PlayerStatistics.season_id == highlighted)
                .first()
            )
            active_season = highlighted if has_stats else get_current_season()
        else:
            # fallback: season with most stats rows
            row = (
                session.query(
                    PlayerStatistics.season_id,
                    func.count(PlayerStatistics.id).label('count')
                )
                .group_by(PlayerStatistics.season_id)
                .order_by(func.count(PlayerStatistics.id).desc())
                .first()
            )
            active_season = row[0] if row else get_current_season()
    
    # Get upcoming games (filtered by league category if specified)
    upcoming = get_upcoming_games(
        limit=12, 
        league_category=league_category if league_category != "all" else None,
        season_id=active_season
    )
    
    # Get recent completed games (filtered by league category if specified)
    recent = get_latest_results(
        limit=12, 
        league_category=league_category if league_category != "all" else None,
        season_id=active_season
    )
    
    # Get overall top scorers across all leagues
    overall_scorers = get_overall_top_scorers(season_id=active_season, limit=10)
    
    # Get unique league categories for filtering - include both upcoming and recent games
    upcoming_league_cats = set(g.get('league_category', '') for g in upcoming if g.get('league_category'))
    recent_league_cats = set(g.get('league_category', '') for g in recent if g.get('league_category'))
    all_game_cats = upcoming_league_cats | recent_league_cats
    
    with db.session_scope() as session:
        league_categories = (
            session.query(
                League.league_id,
                League.game_class,
                League.name
            )
            .filter(League.season_id == active_season)
            .distinct()
            .order_by(League.league_id, League.game_class)
            .all()
        )
        
        # Group by league_id for cleaner display - only include if has games
        leagues_grouped = {}
        for league_id, game_class, name in league_categories:
            key = f"{league_id}_{game_class}"
            # Only include if this category has games (upcoming or recent)
            if key not in all_game_cats:
                continue
                
            if league_id not in leagues_grouped:
                # Extract base name (e.g., "NLB" from "Herren NLB")
                base_name = name.split()[-1] if name else f"League {league_id}"
                leagues_grouped[league_id] = {
                    "name": base_name, 
                    "classes": [],
                    "tier": league_tier(league_id)
                }
            
            leagues_grouped[league_id]["classes"].append({
                "id": key,
                "game_class": game_class,
                "full_name": name
            })
    
    # Sort leagues by tier (lower tier = higher priority leagues like NLA, NLB)
    league_filters = [
        {"id": lid, "name": data["name"], "classes": data["classes"], "tier": data["tier"]}
        for lid, data in sorted(leagues_grouped.items(), key=lambda x: (x[1]["tier"], x[0]))
    ]
    
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "upcoming_games": upcoming,
            "recent_games": recent,
            "overall_top_scorers": overall_scorers,
            "league_filters": league_filters,
            "league_category": league_category,
        }
    )


@app.get("/{locale}/upcoming-games-partial", response_class=HTMLResponse)
async def upcoming_games_partial(request: Request, locale: str, league_category: str = "all"):
    """HTMX endpoint for filtered upcoming games"""
    from app.services.stats_service import get_upcoming_games
    from app.services.database import get_database_service
    from app.models.db_models import PlayerStatistics
    from sqlalchemy import func
    
    # Get active season
    db = get_database_service()
    with db.session_scope() as session:
        active_season_row = (
            session.query(
                PlayerStatistics.season_id,
                func.count(PlayerStatistics.id).label('count')
            )
            .group_by(PlayerStatistics.season_id)
            .order_by(func.count(PlayerStatistics.id).desc())
            .first()
        )
        active_season = active_season_row[0] if active_season_row else get_current_season()
    
    # Get upcoming games filtered by league category
    upcoming = get_upcoming_games(
        limit=12, 
        league_category=league_category if league_category != "all" else None,
        season_id=active_season
    )
    
    return templates.TemplateResponse(
        request,
        "partials/upcoming_games_list.html",
        {
            "locale": locale,
            "upcoming_games": upcoming,
        }
    )


@app.get("/{locale}/recent-games-partial", response_class=HTMLResponse)
async def recent_games_partial(request: Request, locale: str, league_category: str = "all"):
    """HTMX endpoint for filtered recent games"""
    from app.services.stats_service import get_latest_results
    from app.services.database import get_database_service
    from app.models.db_models import PlayerStatistics
    from sqlalchemy import func
    
    # Get active season
    db = get_database_service()
    with db.session_scope() as session:
        active_season_row = (
            session.query(
                PlayerStatistics.season_id,
                func.count(PlayerStatistics.id).label('count')
            )
            .group_by(PlayerStatistics.season_id)
            .order_by(func.count(PlayerStatistics.id).desc())
            .first()
        )
        active_season = active_season_row[0] if active_season_row else get_current_season()
    
    # Get recent games filtered by league category
    recent = get_latest_results(
        limit=12, 
        league_category=league_category if league_category != "all" else None,
        season_id=active_season
    )
    
    return templates.TemplateResponse(
        request,
        "partials/recent_games_list.html",
        {
            "locale": locale,
            "recent_games": recent,
        }
    )


@app.get("/{locale}/clubs", response_class=HTMLResponse)
async def clubs_page(request: Request, locale: str):
    """Clubs listing page"""
    # Use cached data instead of API call (loads on-demand if needed)
    clubs_list = await get_cached_clubs()
    if isinstance(clubs_list, list):
        clubs_list = _rcfg.filter_clubs(clubs_list)

    return templates.TemplateResponse(
        request,
        "clubs.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "clubs": clubs_list[:100] if isinstance(clubs_list, list) else []  # Limit to 100 for initial display
        }
    )


@app.get("/{locale}/clubs/search", response_class=HTMLResponse)
async def clubs_search(request: Request, locale: str, q: str = ""):
    """HTMX endpoint for club search"""
    # Use cached data instead of API call - instant results!
    all_clubs = await get_cached_clubs()
    
    # Apply rendering exclusions, then filter by search query
    all_clubs = _rcfg.filter_clubs(all_clubs)
    filtered_clubs = all_clubs
    if q:
        filtered_clubs = [
            club for club in filtered_clubs
            if q.lower() in club.get("text", "").lower()
        ]
    
    filtered_clubs = filtered_clubs[:50]  # Limit results
    
    # Return partial HTML for htmx — same card structure as the full clubs listing
    from urllib.parse import quote_plus
    cards = ""
    for club in filtered_clubs:
        club_name = club.get("text", "Unknown")
        region = club.get("region") or club.get("set_in_context", {}).get("region", "")
        href = f"/{locale}/teams?club={quote_plus(club_name)}"
        region_html = f'<p style="color: var(--text-secondary); margin: 0.5rem 0 0 0;">📍 {region}</p>' if region else ""
        cards += (
            f'<div class="card" onclick="window.location=\'{href}\'" style="cursor: pointer;">'
            f'<h3 style="margin: 0;">{club_name}</h3>'
            f'{region_html}'
            f'</div>'
        )

    if filtered_clubs:
        html = f'<div class="cards-grid">{cards}</div>'
    else:
        html = '<div style="text-align: center; padding: 3rem; color: var(--text-muted); grid-column: 1/-1;">No clubs found.</div>'
    
    return HTMLResponse(content=html)


@app.get("/{locale}/club/{club_id}", response_class=HTMLResponse)
async def club_detail(request: Request, locale: str, club_id: int):
    """Club detail page with teams and players"""
    error_message = None
    club_data = {}
    teams = []
    players = []
    
    try:
        # Get club from cache
        all_clubs = await get_cached_clubs()
        
        # Find the club with matching ID
        matching_clubs = [
            c for c in all_clubs 
            if c.get("set_in_context", {}).get("club_id") == club_id
        ]
        
        if matching_clubs:
            club_data = matching_clubs[0]
            club_name = club_data.get("text", "")
            current_season = get_current_season()

            # Fetch teams from DB: the API /api/teams?club= parameter is ignored by the server,
            # so we match by team name (teams are indexed from rankings and carry the club name).
            try:
                from app.models.db_models import Team, League, LeagueGroup, Game, GamePlayer
                from app.services.database import get_database_service
                from app.services.data_indexer import league_tier as _league_tier
                from sqlalchemy import and_, text as sa_text
                _db = get_database_service()
                with _db.session_scope() as session:
                    rows = (
                        session.query(Team, League)
                        .outerjoin(
                            League,
                            and_(
                                League.league_id == Team.league_id,
                                League.season_id == Team.season_id,
                                League.game_class == Team.game_class,
                            )
                        )
                        .filter(
                            Team.name.like(f"%{club_name}%"),
                            Team.season_id == current_season,
                        )
                        .all()
                    )

                    # Sort by tier (same ordering as the teams page), then league name, then team name
                    rows.sort(key=lambda r: (
                        _league_tier(r[0].league_id or 0),
                        (r[1].name or "~~~~") if r[1] else "~~~~",
                        r[0].name,
                    ))

                    # Fetch group names per team via games → league_groups
                    team_ids = [t.id for t, _lg in rows]
                    group_by_team: dict[int, str] = {}
                    groups_per_league: dict[int, int] = {}
                    if team_ids:
                        id_list = ",".join(str(i) for i in team_ids)
                        grp_rows = session.execute(
                            sa_text(f"""
                                SELECT t_id, lg.name
                                FROM (
                                    SELECT home_team_id AS t_id, group_id
                                    FROM games WHERE home_team_id IN ({id_list})
                                    UNION ALL
                                    SELECT away_team_id AS t_id, group_id
                                    FROM games WHERE away_team_id IN ({id_list})
                                ) g
                                JOIN league_groups lg ON lg.id = g.group_id
                                GROUP BY t_id
                            """)
                        ).fetchall()
                        group_by_team = {r[0]: r[1] for r in grp_rows}

                        # Count groups per league — same logic as leagues page:
                        # distinct non-empty group names (len({g.name or g.text for g in lg.groups} - {None, ""}))
                        league_db_ids = list({lg.id for _, lg in rows if lg is not None})
                        if league_db_ids:
                            lg_id_list = ",".join(str(i) for i in league_db_ids)
                            cnt_rows = session.execute(
                                sa_text(f"""
                                    SELECT league_id,
                                           COUNT(DISTINCT CASE WHEN COALESCE(NULLIF(name,''), text, '') != ''
                                                               THEN COALESCE(NULLIF(name,''), text) END)
                                    FROM league_groups
                                    WHERE league_id IN ({lg_id_list})
                                    GROUP BY league_id
                                """)
                            ).fetchall()
                            groups_per_league = {r[0]: r[1] for r in cnt_rows}

                    teams = [
                        {
                            "id": t.id,
                            "text": t.name,
                            # Strip the club name prefix so only suffix remains (I, II, III, …)
                            "suffix": t.name.replace(club_name, "").strip(),
                            "league_name": lg.name if lg else "",
                            "league_id": t.league_id,
                            "logo_url": t.logo_url or "",
                            # Only show group if the league has more than one group
                            "group_name": (
                                group_by_team.get(t.id, "")
                                if (lg and groups_per_league.get(lg.id, 0) > 1)
                                else ""
                            ),
                        }
                        for t, lg in rows
                    ]
            except Exception as team_error:
                logger.warning(f"Could not load teams for club {club_id} ({club_name}): {team_error}")
        else:
            error_message = f"Club with ID {club_id} not found"
            logger.warning(error_message)
    
    except Exception as e:
        logger.error(f"Error fetching club {club_id}: {e}")
        error_message = f"Could not load club details: {str(e)}"
    
    return templates.TemplateResponse(
        request,
        "club_detail.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "club": club_data,
            "teams": teams,
            "players": players,
            "error_message": error_message
        }
    )


@app.get("/{locale}/leagues", response_class=HTMLResponse)
async def leagues_page(request: Request, locale: str, season: Optional[int] = None):
    """Leagues listing page — DB-backed, ordered by admin tier categorization"""
    from app.services.stats_service import get_leagues_from_db, get_all_seasons
    from app.services.data_indexer import LEAGUE_TIERS, _DEFAULT_TIER

    all_seasons = get_all_seasons()
    # Resolve selected season: use query param, else fall back to current
    if season is None:
        current = next((s for s in all_seasons if s["current"]), None)
        season = current["id"] if current else (all_seasons[0]["id"] if all_seasons else 2025)

    leagues_list = get_leagues_from_db(season_id=season)

    # Apply rendering exclusions before any processing
    leagues_list = _rcfg.filter_leagues(leagues_list)

    # Tier → human-readable label (matches admin categorization)
    TIER_DISPLAY: dict[int, str] = {
        1: "NLA / L-UPL",
        2: "NLB",
        3: "1. Liga",
        4: "2. Liga",
        5: "3. Liga",
        6: "4. / 5. Liga & Cups",
        7: "Youth & Regional",
    }

    # Age-group mapping for youth/junior/senior leagues (non-senior competitions).
    # User rule: U21=U21, U18=U18+A, U16=U16+B, U14=U14+C, U12=D
    _AGE_GROUP_MAP = {
        19: "U21", 26: "U21",
        18: "U18", 31: "U18", 41: "U18",
        16: "U16", 28: "U16", 32: "U16", 42: "U16",
        14: "U14", 33: "U14", 43: "U14", 49: "U14",
        34: "U12", 36: "U12", 44: "U12",
        35: "U10",
        51: "Senioren",
    }

    # Build flat list with annotated gender / field / tier for client-side filtering
    leagues_flat = []
    for lg in leagues_list:
        gc = lg["game_class"]
        if gc in (11, 12):
            gender = "men"
        elif gc in (21, 22):
            gender = "women"
        else:
            # Youth/age-group leagues: use age group as the gender key so the
            # template can group them by age rather than a generic "youth" bucket.
            gender = _AGE_GROUP_MAP.get(gc, "Other")
        # Big field: senior (11/21) + all U* juniors (14,16,18,19,26,28,49)
        # Small field: 12/22, letter-based Regional (31-36, 41-44), Senioren (51)
        if gc in (11, 21, 14, 16, 18, 19, 26, 28, 49):
            field = "big"
        else:
            field = "small"
        # sex: biological sex for sub-grouping within a tier (independent of age group)
        if gc in (21, 22, 26, 28, 41, 42, 43, 44):
            sex = "women"
        elif gc == 49:
            sex = "mixed"
        else:
            sex = "men"
        # Senior leagues get meaningful tier labels; youth groups are flat (no sub-tiers).
        if gender in ("men", "women"):
            tier = LEAGUE_TIERS.get(lg["league_id"], _DEFAULT_TIER)
            tier_label = TIER_DISPLAY.get(tier, f"Tier {tier}")
        else:
            tier = 0
            tier_label = None
        leagues_flat.append({
            "id": lg["id"],
            "name": lg["name"],
            "gender": gender,
            "sex": sex,
            "field": field,
            "tier": tier,
            "tier_label": tier_label,
            "group_count": lg["group_count"],
        })

    # Resolve display name for selected season
    selected_season_name = next((s["name"] for s in all_seasons if s["id"] == season), str(season))

    return templates.TemplateResponse(
        request,
        "leagues.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "leagues_flat": leagues_flat,
            "seasons": all_seasons,
            "selected_season": season,
            "selected_season_name": selected_season_name,
        },
    )


def _zone_cutoffs(league_name: str) -> tuple[int, int]:
    """Return (playoff_spots, playout_spots) for a league.
    Returns (0, 0) when unknown — the template will fall back to a size heuristic.
    Based on Modus 2025-26 document.
    """
    _ZONE_TABLE: dict[str, tuple[int, int]] = {
        # ── Men senior ────────────────────────────────────────────────────────
        "herren nla": (8, 4), "herren prime league": (8, 4),
        "herren nlb": (8, 4),
        "herren l-upl": (8, 4),
        "herren 1. liga": (8, 4),
        "herren 2. liga": (2, 2),
        "herren 3. liga": (1, 1),
        "herren 4. liga": (1, 0),
        "herren 5. liga": (1, 0),
        # ── Women senior ──────────────────────────────────────────────────────
        "damen nla": (8, 2), "damen prime league": (8, 2),
        "damen nlb": (8, 2),
        "damen l-upl": (8, 2),
        "damen 1. liga": (1, 1),
        "damen 2. liga": (1, 0),
        "damen 3. liga": (1, 1),
        # ── Men youth ─────────────────────────────────────────────────────────
        "junioren u21 a": (8, 4),
        "junioren u21 b": (2, 2),
        "junioren u21 c": (1, 1),
        "junioren u21 d": (1, 0),
        "junioren u18 a": (8, 4),
        "junioren u18 b": (1, 1),
        "junioren u18 c": (1, 0),
        "junioren u16 a": (8, 4),
        "junioren u16 b": (2, 2),
        "junioren u16 c": (1, 0),
        "junioren u14 a": (2, 2),
        "junioren u14 b": (1, 0),
        # ── Women youth ───────────────────────────────────────────────────────
        "juniorinnen u21 a": (8, 2),
        "juniorinnen u21 b": (1, 0),
        "juniorinnen u17 a": (8, 2),
        "juniorinnen u17 b": (1, 0),
    }
    name = (league_name or "").lower().strip()
    return _ZONE_TABLE.get(name, (0, 0))  # (0, 0) → JS heuristic fallback


@app.get("/{locale}/league/{league_id}", response_class=HTMLResponse)
async def league_detail(request: Request, locale: str, league_id: int):
    """League detail page — standings + top scorers from DB"""
    from app.services.stats_service import (
        get_league_by_id,
        get_league_standings,
        get_league_top_scorers,
        get_league_top_penalties,
        get_league_top_scorers_by_phase,
        get_recent_games,
        get_all_seasons,
    )
    from app.services.database import get_database_service
    from app.models.db_models import Game, LeagueGroup, League as _LeagueModel

    league_data = get_league_by_id(league_id)
    error_message = None

    if league_data is None:
        error_message = f"League with ID {league_id} not found."
        return templates.TemplateResponse(
            request,
            "league_detail.html",
            {
                "locale": locale,
                "t": get_translations(locale),
                "league": {},
                "groups": [],
                "standings": [],
                "standings_by_group": {},
                "standings_by_phase": {},
                "series_by_phase": {},
                "topscorers_by_phase": {},
                "topscorers": [],
                "top_penalties": [],
                "games": [],
                "upcoming_games": [],
                "available_seasons": [],
                "selected_season_name": "",
                "playoff_spots": 0,
                "playout_spots": 0,
                "error_message": error_message,
            },
        )

    # standings computed after phase groups are mapped (below)

    # --- Season switcher: find the same league (by API id) across all seasons ---
    _all_seasons = get_all_seasons()
    _api_league_id = league_data.get("league_id")  # API-level id, stable across seasons
    db = get_database_service()
    with db.session_scope() as _s:
        _siblings = (
            _s.query(_LeagueModel.id, _LeagueModel.season_id)
            .filter(_LeagueModel.league_id == _api_league_id)
            .order_by(_LeagueModel.season_id.desc())
            .all()
        )
    _season_to_db = {r.season_id: r.id for r in _siblings}
    available_seasons = [
        {"id": sz["id"], "name": sz["name"], "league_db_id": _season_to_db[sz["id"]]}
        for sz in _all_seasons if sz["id"] in _season_to_db
    ]
    selected_season_name = next(
        (sz["name"] for sz in _all_seasons if sz["id"] == league_data.get("season_id")),
        str(league_data.get("season_id", "")),
    )
    # -------------------------------------------------------------------------

    groups = league_data.get("groups", [])  # [{name, ids: [int]}]
    # standings_by_group computed below after phase groups are mapped
    # flat lookup: DB group_id → display name (for annotating game records)
    _group_id_to_name: dict[int | None, str] = {
        gid: grp["name"]
        for grp in groups
        for gid in grp["ids"]
    }
    topscorers = get_league_top_scorers(league_id, limit=100)
    top_penalties = get_league_top_penalties(league_id, limit=100)
    # Per-phase scorer aggregation from GamePlayer rows (empty if game details not indexed)
    topscorers_by_phase: dict = {}

    # Helper: map raw phase string → canonical category key
    def _canonical_phase(phase_str: str | None) -> str:
        if not phase_str or phase_str == "Regelsaison":
            return "regular"
        p = phase_str.lower()
        if "playoff" in p or "superfinal" in p:
            return "playoff"
        if "playout" in p:
            return "playout"
        if "aufstieg" in p or "abstieg" in p or "qualifikation" in p:
            return "promotion"
        return "regular"

    # Upcoming (unscored) games for this league
    from app.services.stats_service import get_upcoming_games
    group_ids_for_league = [gid for grp in league_data.get("groups", []) for gid in grp["ids"]]

    # Build group_id → canonical phase mapping for annotating game cards
    _group_id_to_phase: dict[int, str] = {}
    if group_ids_for_league:
        with db.session_scope() as _phsess:
            _phase_rows = (
                _phsess.query(LeagueGroup.id, LeagueGroup.phase, LeagueGroup.name)
                .filter(LeagueGroup.id.in_(group_ids_for_league))
                .all()
            )
            for _pr in _phase_rows:
                _group_id_to_phase[_pr.id] = _canonical_phase(_pr.phase)

    # Compute standings per canonical phase (regular / playoff / playout / promotion)
    _phase_to_group_ids: dict[str, list[int]] = {}
    for _gid, _ph in _group_id_to_phase.items():
        _phase_to_group_ids.setdefault(_ph, []).append(_gid)
    standings_by_phase: dict[str, list[dict]] = {}  # populated below (non-regular phases)

    # --- Regular season standings (only regular-phase group IDs) ---
    _regular_group_ids = _phase_to_group_ids.get("regular", [])
    standings = get_league_standings(league_id, only_group_ids=_regular_group_ids if _regular_group_ids else None)

    # Restrict standings_by_group to regular groups only
    _regular_group_id_set = set(_regular_group_ids)

    # Detect "Spielfortführung" groups (replayed/delayed games) and merge them into
    # the corresponding main group instead of showing them as a separate filter chip.
    _spielfort_names: set[str] = {grp["name"] for grp in groups if "spielfort" in grp["name"].lower()}
    _spielfort_gids: set[int] = {
        gid for grp in groups if grp["name"] in _spielfort_names
        for gid in grp["ids"] if gid in _regular_group_id_set
    }
    _grp_extra: dict[str, set[int]] = {}
    if _spielfort_gids:
        from sqlalchemy import or_ as _or_sf
        with db.session_scope() as _sfsess:
            _sf_rows = _sfsess.query(Game.home_team_id, Game.away_team_id).filter(
                Game.group_id.in_(_spielfort_gids)
            ).all()
            _sf_teams = {r.home_team_id for r in _sf_rows} | {r.away_team_id for r in _sf_rows}
            for _grp in groups:
                if _grp["name"] in _spielfort_names:
                    continue
                _base_ids = [g for g in _grp["ids"] if g in _regular_group_id_set and g not in _spielfort_gids]
                if not _base_ids:
                    continue
                _has = _sfsess.query(Game.id).filter(
                    Game.group_id.in_(_base_ids),
                    _or_sf(Game.home_team_id.in_(_sf_teams), Game.away_team_id.in_(_sf_teams))
                ).first()
                if _has:
                    _grp_extra.setdefault(_grp["name"], set()).update(_spielfort_gids)

    # Build per-group standings; Spielfortführung entries are folded into their
    # parent group and excluded from the filter chips.
    _display_groups = [grp for grp in groups if grp["name"] not in _spielfort_names]
    standings_by_group: dict[str, list[dict]] = {}
    for grp in groups:
        if grp["name"] in _spielfort_names:
            continue
        _base = [g for g in grp["ids"] if g in _regular_group_id_set and g not in _spielfort_gids]
        _all_ids = list(set(_base) | _grp_extra.get(grp["name"], set()))
        standings_by_group[grp["name"]] = get_league_standings(
            league_id, only_group_ids=_all_ids or grp["ids"]
        )

    # --- Series data per phase (playoff / playout) ---
    from datetime import date as _date
    from app.models.db_models import Team as _TmModel
    # Build regular-season rank map: team_id → rank (1-based position in standings)
    _reg_rank: dict[int, int] = {}
    for _ri, _rs in enumerate(standings, 1):
        _tid = _rs.get("team_id")
        if _tid:
            _reg_rank[_tid] = _ri
    series_by_phase: dict[str, list[dict]] = {}
    for _sph, _sgids in _phase_to_group_ids.items():
        if _sph not in ("playoff", "playout"):
            continue
        with db.session_scope() as _ssess:
            _sgames = (
                _ssess.query(Game)
                .filter(Game.group_id.in_(_sgids))
                .order_by(Game.game_date.asc())
                .all()
            )
            _sti = {g.home_team_id for g in _sgames} | {g.away_team_id for g in _sgames}
            _snm: dict[int, str] = {}
            _slogo: dict[int, str] = {}
            for _t in _ssess.query(_TmModel).filter(
                _TmModel.id.in_(_sti), _TmModel.season_id == league_data["season_id"]
            ).all():
                _snm[_t.id] = _t.name or _t.text or f"Team {_t.id}"
                if _t.logo_url:
                    _slogo[_t.id] = _t.logo_url
            # Fallback: find names from any season
            _missing = _sti - _snm.keys()
            if _missing:
                for _t in _ssess.query(_TmModel).filter(_TmModel.id.in_(_missing), _TmModel.name.isnot(None)).all():
                    _snm.setdefault(_t.id, _t.name)
                    if _t.logo_url:
                        _slogo.setdefault(_t.id, _t.logo_url)
            # Group games by sorted team-pair key (stable), but determine
            # team_a / team_b from the home/away of the FIRST game in the series.
            _pairs: dict[tuple, list] = {}
            for _g in _sgames:
                _key = tuple(sorted([_g.home_team_id, _g.away_team_id]))
                _pairs.setdefault(_key, []).append(_g)
            _series_list = []
            for _key, _pgames in sorted(_pairs.items(), key=lambda x: _snm.get(x[0], "")):
                _sorted_pgames = sorted(_pgames, key=lambda x: x.game_date or datetime.min)
                _first_g = _sorted_pgames[0]
                _ta = _first_g.home_team_id   # home of game 1 = team A
                _tb = _first_g.away_team_id   # away of game 1 = team B
                _ta_wins = 0
                _tb_wins = 0
                _games_list = []
                for _g in _sorted_pgames:
                    _played = _g.home_score is not None
                    if _played:
                        _home_wins = _g.home_score > _g.away_score
                        if _g.home_team_id == _ta:
                            if _home_wins:
                                _ta_wins += 1
                            else:
                                _tb_wins += 1
                        else:
                            if _home_wins:
                                _tb_wins += 1
                            else:
                                _ta_wins += 1
                    _games_list.append({
                        "game_id": _g.id,
                        "date": _g.game_date.strftime("%d.%m.%Y") if _g.game_date else "",
                        "weekday": _g.game_date.strftime("%a") if _g.game_date else "",
                        "home_team": _snm.get(_g.home_team_id, f"Team {_g.home_team_id}"),
                        "away_team": _snm.get(_g.away_team_id, f"Team {_g.away_team_id}"),
                        "home_team_id": _g.home_team_id,
                        "away_team_id": _g.away_team_id,
                        "home_score": _g.home_score,
                        "away_score": _g.away_score,
                        "played": _played,
                    })
                _series_list.append({
                    "team_a_id": _ta,
                    "team_b_id": _tb,
                    "team_a_name": _snm.get(_ta, f"Team {_ta}"),
                    "team_b_name": _snm.get(_tb, f"Team {_tb}"),
                    "team_a_logo": _slogo.get(_ta),
                    "team_b_logo": _slogo.get(_tb),
                    "team_a_rank": _reg_rank.get(_ta),
                    "team_b_rank": _reg_rank.get(_tb),
                    "team_a_wins": _ta_wins,
                    "team_b_wins": _tb_wins,
                    "games": _games_list,
                })
            series_by_phase[_sph] = _series_list

    # Standings per non-regular phase (for potential fallback table)
    for _ph, _gids in _phase_to_group_ids.items():
        if _ph != "regular":
            standings_by_phase[_ph] = get_league_standings(league_id, only_group_ids=_gids)

    # Per-phase top scorer aggregation (only when GamePlayer rows exist)
    topscorers_by_phase = get_league_top_scorers_by_phase(
        league_id, _phase_to_group_ids, limit=100
    )

    upcoming_games: list[dict] = []
    if group_ids_for_league:
        with db.session_scope() as sess:
            from app.models.db_models import LeagueGroup as LG
            from datetime import date as _date
            from app.models.db_models import Team as TM
            today = _date.today()
            uq = (
                sess.query(Game)
                .filter(
                    Game.group_id.in_(group_ids_for_league),
                    Game.home_score.is_(None),
                    Game.game_date.isnot(None),
                    Game.game_date >= today,
                )
                .order_by(Game.game_date.asc())
                .limit(30)
                .all()
            )
            u_team_ids = {g.home_team_id for g in uq} | {g.away_team_id for g in uq}
            u_names: dict = {}
            for t in sess.query(TM).filter(TM.id.in_(u_team_ids), TM.season_id == league_data["season_id"]).all():
                u_names[t.id] = t.name or t.text or f"Team {t.id}"
            missing = u_team_ids - u_names.keys()
            if missing:
                for t in sess.query(TM).filter(TM.id.in_(missing), TM.name.isnot(None)).all():
                    u_names.setdefault(t.id, t.name)
            for g in uq:
                upcoming_games.append({
                    "game_id": g.id,
                    "group_name": _group_id_to_name.get(g.group_id, ""),
                    "phase": _group_id_to_phase.get(g.group_id, "regular"),
                    "date": g.game_date.strftime("%d.%m.%Y") if g.game_date else "",
                    "weekday": g.game_date.strftime("%a") if g.game_date else "",
                    "time": g.game_time or "",
                    "home_team": u_names.get(g.home_team_id, f"Team {g.home_team_id}"),
                    "away_team": u_names.get(g.away_team_id, f"Team {g.away_team_id}"),
                    "home_team_id": g.home_team_id,
                    "away_team_id": g.away_team_id,
                })

    # Recent results for this league
    recent_games = []
    with db.session_scope() as session:
        from app.models.db_models import Team
        group_ids = [gid for grp in league_data.get("groups", []) for gid in grp["ids"]]
        if group_ids:
            games_raw = (
                session.query(Game)
                .filter(
                    Game.group_id.in_(group_ids),
                    Game.home_score.isnot(None),
                )
                .order_by(Game.game_date.desc())
                .limit(300)
                .all()
            )
            team_ids = set()
            for g in games_raw:
                team_ids.add(g.home_team_id)
                team_ids.add(g.away_team_id)
            team_names: dict = {}
            for t in session.query(Team).filter(
                Team.id.in_(team_ids),
                Team.season_id == league_data["season_id"],
            ).all():
                team_names[t.id] = t.name or t.text or f"Team {t.id}"

            for g in games_raw:
                recent_games.append({
                    "game_id": g.id,
                    "group_name": _group_id_to_name.get(g.group_id, ""),
                    "phase": _group_id_to_phase.get(g.group_id, "regular"),
                    "date": g.game_date.strftime("%Y-%m-%d") if g.game_date else "",
                    "time": g.game_time or "",
                    "home_team": team_names.get(g.home_team_id, f"Team {g.home_team_id}"),
                    "away_team": team_names.get(g.away_team_id, f"Team {g.away_team_id}"),
                    "home_team_id": g.home_team_id,
                    "away_team_id": g.away_team_id,
                    "home_score": g.home_score,
                    "away_score": g.away_score,
                })

    _playoff_spots, _playout_spots = _zone_cutoffs(league_data.get("name", ""))
    return templates.TemplateResponse(
        request,
        "league_detail.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "league": league_data,
            "groups": _display_groups,
            "standings": standings,
            "standings_by_group": standings_by_group,
            "standings_by_phase": standings_by_phase,
            "series_by_phase": series_by_phase,
            "topscorers_by_phase": topscorers_by_phase,
            "topscorers": topscorers,
            "top_penalties": top_penalties,
            "games": recent_games,
            "upcoming_games": upcoming_games,
            "available_seasons": available_seasons,
            "selected_season_name": selected_season_name,
            "playoff_spots": _playoff_spots,
            "playout_spots": _playout_spots,
            "error_message": error_message,
        },
    )


@app.get("/{locale}/teams", response_class=HTMLResponse)
async def teams_page(request: Request, locale: str, season: Optional[int] = None, club: str = ""):
    """Teams listing page. Optional ?club=name pre-filters by club name."""
    import re as _re
    from app.services.stats_service import get_teams_list, get_seasons_with_teams
    from app.services.data_indexer import LEAGUE_TIERS, _DEFAULT_TIER
    _LEVEL_RE = _re.compile(r'\b([A-E])\b')
    try:
        seasons = get_seasons_with_teams()
        if season is None:
            season = next((s["id"] for s in seasons if s["current"]), seasons[0]["id"] if seasons else None)

        limit = 50 if club else 5000
        teams_list = get_teams_list(season_id=season, sort="league", limit=limit, q=club)

        if not teams_list and not club:
            # DB is empty (fresh install) — fall back to API cache
            cached = await get_cached_teams()
            teams_list = [
                {"id": t.get("id"), "text": t.get("text", ""), "game_class": None, "league_id": None, "league_name": None}
                for t in cached[:200]
            ]

        # Enrich teams with the same gender/sex/field/tier fields as the leagues page
        _AGE_GROUP_MAP: dict[int, str] = {
            19: "U21", 26: "U21",
            18: "U18", 31: "U18", 41: "U18",
            16: "U16", 28: "U16", 32: "U16", 42: "U16",
            14: "U14", 33: "U14", 43: "U14", 49: "U14",
            34: "U12", 36: "U12", 44: "U12",
            35: "U10",
            51: "Senioren",
        }
        TIER_DISPLAY: dict[int, str] = {
            1: "NLA / L-UPL", 2: "NLB", 3: "1. Liga",
            4: "2. Liga", 5: "3. Liga", 6: "4. / 5. Liga & Cups",
        }
        _rc = _rcfg.get_config()
        _excl_lg_names = set(_rc.get("excluded_league_names") or [])
        _excl_lg_ids   = set(_rc.get("excluded_league_ids") or [])
        teams_list = _rcfg.filter_teams(teams_list)
        teams_flat: list[dict] = []
        for t in teams_list:
            ln = t.get("league_name") or ""
            if ln in _excl_lg_names:
                continue
            if t.get("league_id") in _excl_lg_ids:
                continue
            gc = t.get("game_class") or 0
            if gc in (11, 12):
                gender = "men"
            elif gc in (21, 22):
                gender = "women"
            else:
                gender = _AGE_GROUP_MAP.get(gc, "Other")
            field = "big" if gc in (11, 21, 14, 16, 18, 19, 26, 28, 49) else "small"
            if gc in (21, 22, 26, 28, 41, 42, 43, 44):
                sex = "women"
            elif gc == 49:
                sex = "mixed"
            else:
                sex = "men"
            if gender in ("men", "women"):
                tier = LEAGUE_TIERS.get(t.get("league_id") or 0, _DEFAULT_TIER)
                tier_label = TIER_DISPLAY.get(tier, f"Tier {tier}")
            else:
                tier = 0
                tier_label = None
            # Level (A/B/C/D) — only meaningful for youth; seniors have no level
            if gender not in ("men", "women"):
                lm = _LEVEL_RE.search(ln)
                level = lm.group(1) if lm else None
            else:
                level = None
            teams_flat.append({
                "id": t["id"],
                "text": t["text"],
                "league_name": ln,
                "gender": gender,
                "sex": sex,
                "field": field,
                "tier": tier,
                "tier_label": tier_label,
                "level": level,
            })

        return templates.TemplateResponse(
            request,
            "teams.html",
            {
                "locale": locale,
                "t": get_translations(locale),
                "teams_flat": teams_flat,
                "seasons": seasons,
                "current_season_id": season,
                "club": club,
            }
        )
    except Exception as e:
        logger.error(f"Error in teams_page: {type(e).__name__}: {e}", exc_info=True)
        raise


@app.get("/{locale}/teams/search", response_class=HTMLResponse)
async def teams_search(request: Request, locale: str, q: str = "", sort: str = "league", leagues: str = "", season: Optional[int] = None):
    """HTMX endpoint for team search"""
    from app.services.stats_service import get_teams_list

    all_seasons = (season == 0)
    league_names = [n.strip() for n in leagues.split(",") if n.strip()] if leagues else None
    teams = get_teams_list(
        season_id=None if all_seasons else season,
        all_seasons=all_seasons,
        q=q, sort=sort, league_names=league_names, limit=400 if all_seasons else 200
    )

    if not teams and not any([q, league_names]):
        # DB empty — fall back to API cache with basic name filter
        all_teams = await get_cached_teams()
        if q:
            all_teams = [t for t in all_teams if q.lower() in t.get("text", "").lower()]
        teams = [
            {"id": t.get("id"), "text": t.get("text", ""), "category": None, "league_name": None}
            for t in all_teams[:200]
        ]

    cat_colors = {"Men": "#3b82f6", "Women": "#ec4899", "Mixed": "#8b5cf6"}

    if not teams:
        return HTMLResponse(content='<div style="text-align:center;padding:3rem;color:var(--gray-600);"><p>No teams found matching your filters.</p></div>')

    list_class = "teams-list teams-list--all-seasons" if all_seasons else "teams-list"
    html = f'<div class="teams-list-meta">{len(teams)} team{"s" if len(teams) != 1 else ""}</div><div class="{list_class}">'
    for team in teams:
        team_id   = team.get("id", "")
        name      = team.get("text", "")
        category  = team.get("category") or ""
        league    = team.get("league_name") or ""
        season_nm = team.get("season_name") or ""
        cat_color = cat_colors.get(category, "var(--gray-400)")
        cat_label = category or "\u2014"
        season_span = f'<span class="teams-list-season">{season_nm}</span>' if all_seasons else ""
        html += (
            f'<a href="/{locale}/team/{team_id}" class="teams-list-row">'
            f'<span class="teams-list-badge" style="color:{cat_color}">{cat_label}</span>'
            f'<span class="teams-list-name">{name}</span>'
            f'<span class="teams-list-league">{league}</span>'
            f'{season_span}'
            f'<span class="teams-list-arrow">\u203a</span>'
            f'</a>'
        )
    html += '</div>'

    return HTMLResponse(content=html)


# ==================== Detail Pages ====================

@app.get("/{locale}/team/{team_id}", response_class=HTMLResponse)
async def team_detail(request: Request, locale: str, team_id: int, season: Optional[int] = None):
    """Team detail page — roster + stats + recent results from DB"""
    from app.services.stats_service import get_team_detail

    team = get_team_detail(team_id, season_id=season)
    error_message = None
    if not team:
        error_message = f"Team {team_id} not found in database."

    return templates.TemplateResponse(
        request,
        "team_detail.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "team": team,
            "error_message": error_message,
            "playoff_spots": _zone_cutoffs((team or {}).get("league_name") or "")[0],
            "playout_spots": _zone_cutoffs((team or {}).get("league_name") or "")[1],
        },
    )


@app.get("/{locale}/schedule", response_class=HTMLResponse)
async def schedule_page(request: Request, locale: str, sex: str = "all", age: str = "all", field: str = "all", page: int = 1):
    """Redirect /schedule → /games?mode=schedule (preserving filters)."""
    params = f"mode=schedule&sex={sex}&age={age}&field={field}&page={page}"
    return RedirectResponse(url=f"/{locale}/games?{params}", status_code=301)


@app.get("/{locale}/players", response_class=HTMLResponse)
async def players_page(request: Request, locale: str, order_by: str = "points", page: int = 1, season: Optional[int] = None, gender: str = "all"):
    """Players leaderboard page — DB-backed with pagination, season and gender filters"""
    from app.services.stats_service import get_player_leaderboard, get_seasons_with_player_stats
    from app.services.database import get_database_service
    from app.models.db_models import PlayerStatistics as _PS
    from sqlalchemy import func as _func

    per_page = 50
    valid_order = {"points", "goals", "assists", "pim"}
    if order_by not in valid_order:
        order_by = "points"
    valid_gender = {"all", "men", "women"}
    if gender not in valid_gender:
        gender = "all"

    seasons = get_seasons_with_player_stats()

    # Resolve active season: use query param if provided, else season with most PS rows
    if season is not None:
        active_season = season
    else:
        db = get_database_service()
        with db.session_scope() as session:
            row = (
                session.query(_PS.season_id, _func.count(_PS.id).label('cnt'))
                .group_by(_PS.season_id)
                .order_by(_func.count(_PS.id).desc())
                .first()
            )
            active_season = row[0] if row else None

    # Map gender string to game_class integer (11=men/Herren, 21=women/Damen)
    gc_filter = {"men": 11, "women": 21}.get(gender)

    offset = (page - 1) * per_page
    data = get_player_leaderboard(
        season_id=active_season,
        game_class=gc_filter,
        limit=per_page,
        offset=offset,
        order_by=order_by,
    )
    total_pages = max(1, (data["total"] + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request,
        "players.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "players": data["players"],
            "order_by": order_by,
            "page": page,
            "total_pages": total_pages,
            "total": data["total"],
            "seasons": seasons,
            "active_season": active_season,
            "gender": gender,
        },
    )


@app.get("/{locale}/players/search", response_class=HTMLResponse)
async def search_players(request: Request, locale: str, q: str = ""):
    """HTMX player name search — returns partial HTML cards with team/league info."""
    from app.services.database import get_database_service
    from app.models.db_models import Player, PlayerStatistics
    from sqlalchemy import or_, func

    if not q or len(q) < 2:
        return HTMLResponse(
            '<p style="text-align:center;padding:1.5rem;color:var(--gray-500);font-size:.875rem">'
            "Enter at least 2 characters to search\u2026</p>"
        )

    db = get_database_service()
    with db.session_scope() as session:
        player_rows = (
            session.query(Player)
            .filter(
                or_(
                    Player.full_name.ilike(f"%{q}%"),
                    Player.name_normalized.like(f"%{q.lower()}%"),
                )
            )
            .limit(50)
            .all()
        )

        if not player_rows:
            return HTMLResponse(
                f'<p style="text-align:center;padding:1.5rem;color:var(--gray-500);font-size:.875rem">'
                f"No players found for <em>{q}</em></p>"
            )

        # Fetch most recent stats row per player to get team + league info
        player_ids = [p.person_id for p in player_rows]
        latest_subq = (
            session.query(
                PlayerStatistics.player_id,
                func.max(PlayerStatistics.season_id).label("max_season"),
            )
            .filter(PlayerStatistics.player_id.in_(player_ids))
            .group_by(PlayerStatistics.player_id)
            .subquery()
        )
        stats_rows = (
            session.query(PlayerStatistics)
            .join(
                latest_subq,
                (PlayerStatistics.player_id == latest_subq.c.player_id)
                & (PlayerStatistics.season_id == latest_subq.c.max_season),
            )
            .all()
        )
        stats_map: dict[int, PlayerStatistics] = {s.player_id: s for s in stats_rows}

        parts = []
        for pl in player_rows:
            name = pl.full_name or f"Player {pl.person_id}"
            st = stats_map.get(pl.person_id)
            subtitle = ""
            if st:
                team = st.team_name or ""
                league = st.league_abbrev or ""
                if team and league:
                    subtitle = f'<span class="search-item-subtitle">{team} \u00b7 {league}</span>'
                elif team:
                    subtitle = f'<span class="search-item-subtitle">{team}</span>'
            parts.append(
                f'<div class="search-item" onclick="window.location.href=\'/{locale}/player/{pl.person_id}\'">'
                f'<span class="search-item-main"><strong>{name}</strong>{subtitle}</span>'
                f"</div>"
            )

        return HTMLResponse('<div class="search-items">' + "".join(parts) + "</div>")


@app.get("/{locale}/player/{player_id}", response_class=HTMLResponse)
async def player_detail(request: Request, locale: str, player_id: int):
    """Player detail page — career stats from DB"""
    from app.services.stats_service import get_player_detail

    player = get_player_detail(player_id)
    error_message = None
    if not player:
        error_message = f"Player {player_id} not found in database."

    return templates.TemplateResponse(
        request,
        "player_detail.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "player": player,
            "error_message": error_message,
        },
    )


# ==================== Other Pages ====================

@app.get("/{locale}/games", response_class=HTMLResponse)
async def games_page(
    request: Request,
    locale: str,
    mode: str = "results",   # "results" | "schedule"
    sex: str = "all",
    age: str = "all",
    field: str = "all",
    level: str = "all",
    page: int = 1,
    # backward-compat alias kept so old /games?scored_only=0 links still work
    scored_only: Optional[str] = None,
):
    """Combined results + schedule page with sex/age/field/level filters."""
    from app.services.stats_service import get_recent_games

    # Honor legacy scored_only param
    if scored_only is not None and mode == "results":
        mode = "results" if scored_only != "0" else "schedule"

    per_page = 50
    offset = (page - 1) * per_page
    data = get_recent_games(
        mode=mode, sex=sex, age=age, field=field, level=level,
        limit=per_page, offset=offset,
    )
    total_pages = max(1, (data["total"] + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request,
        "games.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "games": data["games"],
            "mode": mode,
            "sex": sex,
            "age": age,
            "field": field,
            "level": level,
            "page": page,
            "total_pages": total_pages,
            "total": data["total"],
        },
    )


@app.get("/{locale}/game/{game_id}", response_class=HTMLResponse)
async def game_detail(request: Request, locale: str, game_id: int):
    """Game detail page — box score from DB"""
    from app.services.stats_service import get_game_box_score, get_playoff_series_for_game

    box = get_game_box_score(game_id)
    error_message = None
    if not box:
        error_message = f"Game {game_id} not found in database."

    playoff_series = get_playoff_series_for_game(game_id) if box else None

    return templates.TemplateResponse(
        request,
        "game_detail.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "game": box,
            "error_message": error_message,
            "playoff_series": playoff_series,
        },
    )


# ============================================================================
# Universal Search
# ============================================================================

@app.get("/{locale}/search", response_class=HTMLResponse)
async def universal_search(request: Request, locale: str, q: str = ""):
    """Universal search across players, teams, and leagues — DB-backed."""
    if not q or len(q) < 2:
        return HTMLResponse('<div class="search-results"><p style="text-align:center;padding:2rem;color:var(--gray-500)">Enter at least 2 characters to search…</p></div>')

    from app.services.database import get_database_service
    from app.models.db_models import Player, Team, League
    from sqlalchemy import or_

    db = get_database_service()
    html_parts: list[str] = []

    with db.session_scope() as session:
        # --- Players ---
        players = (
            session.query(Player)
            .filter(Player.full_name.ilike(f"%{q}%"))
            .limit(8).all()
        )
        if players:
            html_parts.append('<div class="search-category"><h3>🏒 Players</h3><div class="search-items">')
            for pl in players:
                name = pl.full_name or f"Player {pl.person_id}"
                html_parts.append(
                    f'<div class="search-item" onclick="window.location.href=\'/{locale}/player/{pl.person_id}\'">'
                    f'<strong>{name}</strong></div>'
                )
            html_parts.append('</div></div>')

        # --- Teams ---
        from sqlalchemy import func
        from app.services.data_indexer import league_tier as _league_tier
        # Subquery: for each unique team id, get the most recent season
        team_subq = (
            session.query(Team.id, func.max(Team.season_id).label("max_season"))
            .filter(
                or_(Team.name.ilike(f"%{q}%"), Team.text.ilike(f"%{q}%")),
                Team.name.isnot(None),
            )
            .group_by(Team.id)
            .limit(8)
            .subquery()
        )
        unique_teams_rows = (
            session.query(Team, League)
            .join(team_subq, (Team.id == team_subq.c.id) & (Team.season_id == team_subq.c.max_season))
            .outerjoin(
                League,
                (League.league_id == Team.league_id)
                & (League.season_id == Team.season_id)
                & (League.game_class == Team.game_class),
            )
            .all()
        )
        unique_teams_rows.sort(key=lambda r: (
            _league_tier(r[0].league_id or 0),
            (r[1].name or r[1].text or "~~~~") if r[1] else "~~~~",
            r[0].name or "",
        ))
        if unique_teams_rows:
            html_parts.append('<div class="search-category"><h3>👥 Teams</h3><div class="search-items">')
            for t, lg in unique_teams_rows:
                tname = t.name or t.text or f"Team {t.id}"
                lgname = (lg.name or lg.text or "") if lg else ""
                subtitle = f'<span class="search-item-subtitle">{lgname}</span>' if lgname else ""
                html_parts.append(
                    f'<div class="search-item" onclick="window.location.href=\'/{locale}/team/{t.id}\'">'
                    f'<span class="search-item-main"><strong>{tname}</strong>{subtitle}</span></div>'
                )
            html_parts.append('</div></div>')

        # --- Leagues ---
        leagues = (
            session.query(League)
            .filter(or_(League.name.ilike(f"%{q}%"), League.text.ilike(f"%{q}%")))
            .order_by(League.season_id.desc())
            .limit(5).all()
        )
        seen_league_names: set[str] = set()
        unique_leagues = []
        for lg in leagues:
            key = (lg.name or lg.text or "").lower()
            if key not in seen_league_names:
                seen_league_names.add(key)
                unique_leagues.append(lg)
        unique_leagues = unique_leagues[:5]
        if unique_leagues:
            html_parts.append('<div class="search-category"><h3>🏆 Leagues</h3><div class="search-items">')
            for lg in unique_leagues:
                lgname = lg.name or lg.text or f"League {lg.id}"
                html_parts.append(
                    f'<div class="search-item" onclick="window.location.href=\'/{locale}/league/{lg.id}\'">'
                    f'<strong>{lgname}</strong></div>'
                )
            html_parts.append('</div></div>')

    if not html_parts:
        return HTMLResponse('<div class="search-results"><p style="text-align:center;padding:2rem;color:var(--gray-500)">No results found for <em>' + q + '</em></p></div>')

    return HTMLResponse('<div class="search-results">' + "".join(html_parts) + '</div>')


@app.get("/{locale}/favorites", response_class=HTMLResponse)
async def favorites_page(request: Request, locale: str):
    """Favorites page"""
    return templates.TemplateResponse(
        request,
        "favorites.html",
        {
            "locale": locale,
            "t": get_translations(locale)
        }
    )


@app.get("/{locale}/contact", response_class=HTMLResponse)
async def contact_page(request: Request, locale: str, sent: str = ""):
    """Contact page"""
    return templates.TemplateResponse(
        request,
        "contact.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "success": sent == "1",
            "error": False,
            "form_name": "",
            "form_email": "",
            "form_subject": "",
            "form_message": "",
        }
    )


@app.post("/{locale}/contact", response_class=HTMLResponse)
async def contact_submit(request: Request, locale: str):
    """Handle contact form submission and send email"""
    client_ip = request.client.host if request.client else "unknown"
    t = get_translations(locale)

    if _check_contact_rate_limit(client_ip):
        return templates.TemplateResponse(
            request,
            "contact.html",
            {
                "locale": locale,
                "t": t,
                "success": False,
                "error": True,
                "form_name": "",
                "form_email": "",
                "form_subject": "",
                "form_message": "",
            },
            status_code=429,
        )

    form = await request.form()
    name = str(form.get("name", "")).strip()
    email_val = str(form.get("email", "")).strip()
    subject = str(form.get("subject", "")).strip() or "Contact form message"
    message = str(form.get("message", "")).strip()

    # Enforce field length limits and validate email format
    valid = (
        name
        and email_val
        and message
        and len(name) <= 120
        and len(email_val) <= 254
        and len(subject) <= 200
        and len(message) <= 4000
        and re.match(r'^[^@\r\n]+@[^@\r\n]+\.[^@\r\n]+$', email_val)
    )
    if not valid:
        return templates.TemplateResponse(
            request,
            "contact.html",
            {
                "locale": locale,
                "t": t,
                "success": False,
                "error": True,
                "form_name": name,
                "form_email": email_val,
                "form_subject": subject,
                "form_message": message,
            }
        )

    # Strip newlines to prevent email header injection
    safe_subject = subject.replace('\r', '').replace('\n', '')
    safe_email = email_val.replace('\r', '').replace('\n', '')

    # Send email if SMTP is configured
    if settings.SMTP_HOST and settings.CONTACT_EMAIL:
        try:
            msg = EmailMessage()
            msg["Subject"] = f"[SwissUnihockey Contact] {safe_subject}"
            msg["From"] = settings.SMTP_USER or settings.CONTACT_EMAIL
            msg["To"] = settings.CONTACT_EMAIL
            msg["Reply-To"] = safe_email
            msg.set_content(
                f"Name: {name}\nEmail: {email_val}\n\n{message}"
            )

            def _send_email() -> None:
                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                    server.starttls()
                    if settings.SMTP_USER and settings.SMTP_PASSWORD:
                        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    server.send_message(msg)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _send_email)
        except Exception as exc:
            logger.error(f"Contact form email failed: {exc}")
            return templates.TemplateResponse(
                request,
                "contact.html",
                {
                    "locale": locale,
                    "t": t,
                    "success": False,
                    "error": True,
                    "form_name": name,
                    "form_email": email_val,
                    "form_subject": subject,
                    "form_message": message,
                }
            )

    return RedirectResponse(url=f"/{locale}/contact?sent=1", status_code=303)


@app.get("/{locale}/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request, locale: str):
    """Privacy policy page"""
    return templates.TemplateResponse(
        request,
        "privacy.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "privacy_last_updated": PRIVACY_POLICY_LAST_UPDATED,
        }
    )


# ============================================================================
# GameSyncFailure Admin Routes
# ============================================================================

@app.get("/admin/sync-failures", response_class=HTMLResponse)
async def admin_sync_failures(request: Request, _: None = Depends(require_admin)):
    """Admin page showing all GameSyncFailure rows with retry controls."""
    from sqlalchemy import select
    from app.models.db_models import GameSyncFailure, Game
    from app.services.database import get_database_service
    locale = get_locale_from_path(request.url.path)
    t = get_translations(locale)
    with get_database_service().session_scope() as session:
        rows = session.execute(
            select(GameSyncFailure, Game)
            .join(Game, GameSyncFailure.game_id == Game.id)
            .order_by(GameSyncFailure.abandoned_at.desc())
        ).all()
        failures_data = [
            {
                "failure_id": f.id,
                "game_id": g.id,
                "game_api_id": g.id,
                "season_id": f.season_id,
                "game_date": g.game_date,
                "abandoned_at": f.abandoned_at,
                "missing_fields": f.missing_fields or [],
                "can_retry": f.can_retry,
                "retried_at": f.retried_at,
            }
            for f, g in rows
        ]
    return templates.TemplateResponse(
        request,
        "admin_sync_failures.html",
        {"failures": failures_data, "t": t, "locale": locale},
    )


@app.post("/admin/sync-failures/{failure_id}/retry")
async def admin_retry_sync_failure(failure_id: int, request: Request, _: None = Depends(require_admin)):
    """Queue a GameSyncFailure for retry by setting can_retry=True."""
    from app.models.db_models import GameSyncFailure
    from app.services.database import get_database_service
    with get_database_service().session_scope() as session:
        failure = session.get(GameSyncFailure, failure_id)
        if failure is None:
            raise HTTPException(status_code=404, detail="Failure not found")
        failure.can_retry = True
    return RedirectResponse(url="/admin/sync-failures", status_code=303)


# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle HTTP exceptions (404, etc.)"""
    locale = get_locale_from_path(request.url.path)
    
    if exc.status_code == 404:
        return templates.TemplateResponse(
            request,
            "error_404.html",
            {
                "locale": locale,
                "t": get_translations(locale)
            },
            status_code=404
        )
    
    # For other HTTP errors, return JSON
    from fastapi.responses import JSONResponse
    return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions (500)"""
    locale = get_locale_from_path(request.url.path)
    error_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Log error (in production, send to logging service)
    print(f"[ERROR {error_id}] {exc}")
    
    return templates.TemplateResponse(
        request,
        "error_500.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "error_id": error_id,
            "timestamp": timestamp
        },
        status_code=500
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )

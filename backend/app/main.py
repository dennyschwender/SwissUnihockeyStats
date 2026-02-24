"""
Main FastAPI application entry point
"""
from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import asyncio
import hashlib
import hmac
import time
import uuid
import logging
import traceback
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
    """
    Get the current Swiss Unihockey season year.
    Prefers the season flagged as highlighted in the DB.
    Falls back to date-based detection if DB is unavailable or no season is flagged.
    """
    try:
        from app.services.database import get_database_service
        from app.models.db_models import Season as _Season
        db = get_database_service()
        with db.session_scope() as session:
            row = session.query(_Season.id).filter(_Season.highlighted == True).first()
            if row:
                return row[0]
    except Exception:
        pass
    # Date-based fallback: Sep-Dec → current year, Jan-Aug → previous year
    now = datetime.now()
    return now.year if now.month >= 9 else now.year - 1


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events: startup and shutdown"""
    # Startup: Initialize database and preload common data
    logger.info("🚀 Starting SwissUnihockey application...")
    current_season = get_current_season()
    logger.info(f"📅 Current season: {current_season}/{current_season + 1}")

    _sched_task = None  # initialise before try so shutdown block can always reference it

    try:
        # Initialize database
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

        # Start background scheduler
        from app.services.scheduler import init_scheduler
        _sched_instance = init_scheduler(_admin_jobs, _submit_job)
        _sched_task = asyncio.create_task(
            _sched_instance.run(), name="scheduler"
        )
        logger.info("✓ Scheduler started")

        # Pre-compute admin PIN hash (pbkdf2_hmac 100k rounds, ~1-2 s on Pi ARM)
        # in an executor so it doesn’t block the event loop.  Awaited here to
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
        logger.error(f"❌ Failed to initialize application: {e}")
        logger.warning("⚠️ App will start but may have issues")

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

# Configure CORS
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET, session_cookie="admin_session")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(o) for o in settings.BACKEND_CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router (JSON endpoints)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


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

def require_admin(request: Request):
    """FastAPI dependency — raises exception caught by handler below if not logged in."""
    if request.session.get(_ADMIN_TOKEN_KEY) != _ADMIN_PIN_HASH:
        raise _AdminNotAuthenticated()


# DEBUG endpoints — admin-only
@app.get("/debug/player-index")
async def debug_player_index(_: None = Depends(require_admin)):
    """Debug endpoint to see player index status"""
    from app.services.data_cache import get_data_cache
    cache = get_data_cache()
    
    player_count = len(cache._players)
    game_count = len(cache._games)
    indexed = cache._players_indexed
    
    sample_players = list(cache._players.values())[:5] if cache._players else []
    
    return {
        "players_indexed": indexed,
        "player_count": player_count,
        "game_count": game_count,
        "sample_players": sample_players
    }


@app.get("/debug/force-reindex")
async def debug_force_reindex(_: None = Depends(require_admin)):
    """Force player reindexing and return detailed logs"""
    from app.services.data_cache import get_data_cache
    import logging
    
    cache = get_data_cache()
    
    # Try to index with detailed logging
    try:
        players_teams = await cache.index_players_from_teams()
        players_games = await cache.index_players_from_games()
        
        return {
            "success": True,
            "players_from_teams": players_teams,
            "players_from_games": players_games,
            "total_players": len(cache._players),
            "sample": list(cache._players.values())[:3]
        }
    except Exception as e:
        logger.error(f"Reindex failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


@app.get("/debug/test-games-fetch")
async def debug_test_games_fetch(_: None = Depends(require_admin)):
    """Debug endpoint to test various API endpoints"""
    client = get_swissunihockey_client()
    from app.services.data_cache import get_data_cache
    cache = get_data_cache()
    
    results = {}
    
    # Test NEW endpoint: Team players
    await cache.load_leagues()
    if cache._leagues:
        first_league = cache._leagues[0]
        try:
            teams_data = client.get_teams(
                league=first_league.get("id"),
                game_class=first_league.get("game_classes", [{}])[0].get("id", 11),
                mode="1",
                season=2025
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
                
                # Try NEW endpoint: /api/teams/:team_id/players
                try:
                    players_data = client.get_team_players(team_id)
                    results["team_players"] = {
                        "success": True,
                        "team_id": team_id,
                        "team_name": team_name,
                        "data_type": str(type(players_data)),
                        "has_data": bool(players_data),
                        "raw_data": players_data  # Include full raw data
                    }
                except Exception as e:
                    results["team_players"] = {"success": False, "team_id": team_id, "error": str(e)}
        except Exception as e:
            results["team_players"] = {"success": False, "error": str(e)}
    
    # Test NEW games endpoint with mode=list
    try:
        games_data = client.get_games(
            mode="list",
            season=2025,
            league=1,
            game_class=11
        )
        results["games_mode_list"] = {
            "success": True,
            "data_type": str(type(games_data)),
            "has_data": bool(games_data)
        }
        if isinstance(games_data, dict):
            results["games_mode_list"]["keys"] = list(games_data.keys())
            if "entries" in games_data:
                results["games_mode_list"]["game_count"] = len(games_data["entries"])
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
    form = await request.form()
    pin  = str(form.get("pin", "")).strip()
    if hmac.compare_digest(_pin_hash(pin), _ADMIN_PIN_HASH):
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
    global _stats_cache, _stats_cache_time
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
    """Run VACUUM + WAL checkpoint to reclaim free pages and merge WAL back into DB."""
    from app.services.database import get_database_service
    from sqlalchemy import text as _text

    db_service = get_database_service()
    if ":memory:" in db_service.database_url:
        return {"ok": False, "detail": "VACUUM not applicable for in-memory DB"}

    if db_service.engine is None:
        return {"ok": False, "detail": "Database engine not initialized"}

    engine = db_service.engine
    loop = asyncio.get_running_loop()
    def _vacuum():
        import time
        t0 = time.time()
        with engine.connect() as conn:
            conn.execute(_text("PRAGMA wal_checkpoint(TRUNCATE)"))
            conn.execute(_text("VACUUM"))
        return round(time.time() - t0, 2)

    try:
        elapsed = await loop.run_in_executor(None, _vacuum)
        logger.info("Admin VACUUM completed in %.2fs", elapsed)
        return {"ok": True, "elapsed_s": elapsed}
    except Exception as e:
        logger.error("Admin VACUUM failed: %s", e, exc_info=True)
        return {"ok": False, "detail": str(e)}


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
        totals = {
            "seasons":       safe_count(session.query(func.count(Season.id))),
            "clubs":         safe_count(session.query(func.count(Club.id))),
            "teams":         safe_count(session.query(func.count(Team.id))),
            "players":       safe_count(session.query(func.count(Player.person_id))),
            "team_players":  safe_count(session.query(func.count(TeamPlayer.id))),
            "leagues":       safe_count(session.query(func.count(League.id))),
            "league_groups": safe_count(session.query(func.count(LeagueGroup.id))),
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

    job_id = str(uuid.uuid4())[:8]
    _admin_jobs[job_id] = {
        "job_id":    job_id,
        "season":    season,
        "task":      task,
        "label":     _TASK_META[task],
        "status":    "running",
        "progress":  0,
        "stats":     {},
        "log_lines": [],
        "error":     None,
    }
    t = asyncio.create_task(_run(job_id, season, task, force, max_tier=max_tier), name=f"job-{job_id}")
    _admin_tasks[job_id] = t
    return {"job_id": job_id, "season": season, "task": task, "label": _TASK_META[task]}


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

        session.commit()

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
        # Also purge manual jobs that are finished
        manual_removed = [jid for jid, j in list(_admin_jobs.items())
                          if j.get("status") in ("done", "error", "stopped")]
        for jid in manual_removed:
            _admin_jobs.pop(jid, None)
        return {"ok": True, "removed": removed + len(manual_removed)}
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

        with db.session_scope() as session:
            game_ids = [r[0] for r in session.query(Game.id).filter(Game.season_id.in_(target_ids)).all()]
            league_ids = [r[0] for r in session.query(League.id).filter(League.season_id.in_(target_ids)).all()]
            sync_filters = sa_or(*[
                SyncStatus.entity_id.like(f"%:{s}:%") | SyncStatus.entity_id.like(f"%:{s}")
                for s in target_ids
            ]) if target_ids else (SyncStatus.id == -1)

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

        with db.session_scope() as session:
            game_ids = [r[0] for r in session.query(Game.id).filter(Game.season_id.in_(target_ids)).all()]
            league_ids = [r[0] for r in session.query(League.id).filter(League.season_id.in_(target_ids)).all()]

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
            deleted: dict[str, int] = {}
            for i, (name, fn) in enumerate(steps, 1):
                n = fn(session)
                deleted[name] = n
                push("ok", f"  Deleted {n:,} {name} rows")
                job["progress"] = 15 + int(i / (len(steps) + 2) * 75)

            # SyncStatus
            sync_filters = sa_or(*[
                SyncStatus.entity_id.like(f"%:{s}:%") | SyncStatus.entity_id.like(f"%:{s}")
                for s in target_ids
            ]) if target_ids else (SyncStatus.id == -1)
            n = session.query(SyncStatus).filter(sync_filters).delete(synchronize_session=False)
            deleted["SyncStatus"] = n
            push("ok", f"  Deleted {n:,} SyncStatus rows")

            n = batched_delete(session, Season, Season.id, target_ids)
            deleted["Season"] = n
            push("ok", f"  Deleted {n:,} Season rows")

            # Orphaned players: no TeamPlayer AND no GamePlayer rows anywhere
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
        from app.models.db_models import Club, Team, League, Game
        indexer    = get_data_indexer()
        db_service = get_database_service()

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
                cnt, tids = await asyncio.to_thread(indexer.index_teams_for_club, cid, season, force=force)
                teams_n += cnt
                team_id_list.extend(tids)
                set_progress(10 + int(i / total * 25))
            stats["teams"] = teams_n
            push("ok", f"Teams: {teams_n}")

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
                players_n += await asyncio.to_thread(indexer.index_players_for_team, tid, season, force=force)
                set_progress(35 + int(i / total * 25) if total else 60)
            stats["players"] = players_n
            push("ok", f"Players: {players_n}")

        # ── PLAYER STATS ───────────────────────────────────────────────────
        if task in ("player_stats", "clubs_path", "full"):
            push("info", f"Indexing player statistics for season {season}...")
            stats_n = await asyncio.to_thread(indexer.index_player_stats_for_season, season, force=force)
            stats["player_stats"] = stats_n
            push("ok", f"Player stats: {stats_n}")
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
                lineup_n2 += max(0, await asyncio.to_thread(indexer.index_game_lineup, gid, season, force=force))
                set_progress(int(i / total_gl * 95) if total_gl else 99)
            stats["game_lineups"] = lineup_n2
            push("ok", f"Game lineups: {lineup_n2}")

        # ── PLAYER GAME STATS (standalone or as part of full) ──────────────
        if task in ("player_game_stats", "full"):
            push("info", f"Updating per-game G/A/PIM for season {season}...")
            pgstats_n = await asyncio.to_thread(indexer.index_player_game_stats_for_season, season_id=season, force=force)
            stats["player_game_stats"] = pgstats_n
            push("ok", f"Player game stats: {pgstats_n}")

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
                groups_n += await asyncio.to_thread(indexer.index_groups_for_league, ldb, season, lid, gc, force=force)
                set_progress(62 + int(i / total * 13))
            stats["league_groups"] = groups_n
            push("ok", f"Groups: {groups_n}")

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
            _GAMES_BATCH = 2
            for batch_start in range(0, max(total, 1), _GAMES_BATCH):
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
                # Join Game → League to filter by tier
                rows = (
                    s.query(Game.id, Game.season_id, _League.league_id)
                    .join(LeagueGroup, Game.group_id == LeagueGroup.id, isouter=True)
                    .join(_League, LeagueGroup.league_id == _League.id, isouter=True)
                    .filter(
                        Game.season_id == season,
                        Game.game_date < _now,
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

            # Process in small batches (2 games at a time) so the event loop
            # stays responsive for admin API requests between batches.
            _EV_BATCH = 2
            for batch_start in range(0, max(total, 1), _EV_BATCH):
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
    
    # Get the season with the most player statistics (active season)
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
        
        if active_season_row:
            active_season = active_season_row[0]
        else:
            active_season = get_current_season()
    
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
    
    # Filter clubs by search query
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
    _EXCLUDED_LEAGUE_NAMES = {"Herren Test"}
    leagues_flat = []
    for lg in leagues_list:
        if lg["name"] in _EXCLUDED_LEAGUE_NAMES:
            continue
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
                "topscorers": [],
                "games": [],
                "upcoming_games": [],
                "available_seasons": [],
                "selected_season_name": "",
                "playoff_spots": 0,
                "playout_spots": 0,
                "error_message": error_message,
            },
        )

    standings = get_league_standings(league_id)

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
    standings_by_group = {
        grp["name"]: get_league_standings(league_id, only_group_ids=grp["ids"])
        for grp in groups
    }
    # flat lookup: DB group_id → display name (for annotating game records)
    _group_id_to_name: dict[int | None, str] = {
        gid: grp["name"]
        for grp in groups
        for gid in grp["ids"]
    }
    topscorers = get_league_top_scorers(league_id, limit=100)

    # Upcoming (unscored) games for this league
    from app.services.stats_service import get_upcoming_games
    group_ids_for_league = [gid for grp in league_data.get("groups", []) for gid in grp["ids"]]
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
                .limit(100)
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
                    "date": g.game_date.strftime("%Y-%m-%d") if g.game_date else "",
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
            "groups": groups,
            "standings": standings,
            "standings_by_group": standings_by_group,
            "topscorers": topscorers,
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
    from app.services.stats_service import get_teams_list, get_seasons_with_teams
    from app.services.data_indexer import LEAGUE_TIERS, _DEFAULT_TIER
    try:
        seasons = get_seasons_with_teams()
        if season is None:
            season = next((s["id"] for s in seasons if s["current"]), seasons[0]["id"] if seasons else None)

        limit = 50 if club else 500
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
        teams_flat: list[dict] = []
        for t in teams_list:
            ln = t.get("league_name") or ""
            if ln == "Herren Test":
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
            teams_flat.append({
                "id": t["id"],
                "text": t["text"],
                "league_name": ln,
                "gender": gender,
                "sex": sex,
                "field": field,
                "tier": tier,
                "tier_label": tier_label,
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
        },
    )


@app.get("/{locale}/schedule", response_class=HTMLResponse)
async def schedule_page(request: Request, locale: str, league_category: str = "all", page: int = 1):
    """Upcoming games schedule page with pagination and league filter"""
    from app.services.stats_service import get_schedule
    from app.services.database import get_database_service
    from app.models.db_models import PlayerStatistics as _PS, League as _League
    from app.services.data_indexer import league_tier as _lt
    from sqlalchemy import func as _func

    per_page = 50
    db = get_database_service()
    with db.session_scope() as session:
        active_season_row = (
            session.query(_PS.season_id, _func.count(_PS.id).label("count"))
            .group_by(_PS.season_id)
            .order_by(_func.count(_PS.id).desc())
            .first()
        )
        active_season = active_season_row[0] if active_season_row else get_current_season()

    offset = (page - 1) * per_page
    data = get_schedule(
        season_id=active_season,
        league_category=league_category if league_category != "all" else None,
        limit=per_page,
        offset=offset,
    )
    total_pages = max(1, (data["total"] + per_page - 1) // per_page)

    with db.session_scope() as session:
        league_rows = (
            session.query(_League.league_id, _League.game_class, _League.name)
            .filter(_League.season_id == active_season)
            .distinct()
            .order_by(_League.league_id, _League.game_class)
            .all()
        )
        leagues_grouped: dict = {}
        for league_id, game_class, name in league_rows:
            key = f"{league_id}_{game_class}"
            if league_id not in leagues_grouped:
                base_name = name.split()[-1] if name else f"League {league_id}"
                leagues_grouped[league_id] = {
                    "name": base_name,
                    "classes": [],
                    "tier": _lt(league_id),
                }
            leagues_grouped[league_id]["classes"].append({
                "id": key,
                "game_class": game_class,
                "full_name": name,
            })
        league_filters = [
            {"id": lid, "name": ldata["name"], "classes": ldata["classes"], "tier": ldata["tier"]}
            for lid, ldata in sorted(leagues_grouped.items(), key=lambda x: (x[1]["tier"], x[0]))
        ]

    return templates.TemplateResponse(
        request,
        "schedule.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "games": data["games"],
            "page": page,
            "total_pages": total_pages,
            "total": data["total"],
            "league_category": league_category,
            "league_filters": league_filters,
        },
    )


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
    """HTMX player name search — returns partial HTML rows."""
    from app.services.database import get_database_service
    from app.models.db_models import Player
    from sqlalchemy import or_

    filtered: list[dict] = []

    if q and len(q) >= 2:
        db = get_database_service()
        with db.session_scope() as session:
            rows = (
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
            for pl in rows:
                filtered.append({"id": pl.person_id, "name": pl.full_name or f"Player {pl.person_id}"})

    if not filtered:
        msg = "Enter at least 2 characters to search" if not q else "No players found"
        return HTMLResponse(f'<tr><td colspan="8" style="text-align:center;padding:2rem;color:var(--gray-600)">{msg}</td></tr>')

    rows_html = ""
    for p in filtered:
        rows_html += f'<tr onclick="window.location=\'/{locale}/player/{p["id"]}\'" style="cursor:pointer"><td colspan="8">{p["name"]}</td></tr>'
    return HTMLResponse(rows_html)


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
async def games_page(request: Request, locale: str, scored_only: str = "1", page: int = 1):
    """Games schedule page — DB-backed with pagination"""
    from app.services.stats_service import get_recent_games

    per_page = 50
    with_score = scored_only != "0"
    offset = (page - 1) * per_page
    data = get_recent_games(limit=per_page, offset=offset, with_score_only=with_score)
    total_pages = max(1, (data["total"] + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request,
        "games.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "games": data["games"],
            "scored_only": with_score,
            "page": page,
            "total_pages": total_pages,
            "total": data["total"],
        },
    )


@app.get("/{locale}/game/{game_id}", response_class=HTMLResponse)
async def game_detail(request: Request, locale: str, game_id: int):
    """Game detail page — box score from DB"""
    from app.services.stats_service import get_game_box_score

    box = get_game_box_score(game_id)
    error_message = None
    if not box:
        error_message = f"Game {game_id} not found in database."

    return templates.TemplateResponse(
        request,
        "game_detail.html",
        {
            "locale": locale,
            "t": get_translations(locale),
            "game": box,
            "error_message": error_message,
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
        teams_raw = (
            session.query(Team, League)
            .outerjoin(
                League,
                (League.league_id == Team.league_id) & (League.season_id == Team.season_id)
            )
            .filter(
                or_(Team.name.ilike(f"%{q}%"), Team.text.ilike(f"%{q}%")),
                Team.name.isnot(None),
            )
            .order_by(Team.season_id.desc())
            .limit(16).all()
        )
        # deduplicate by (name, league_id) so same club in different leagues all show
        seen_team_keys: set[str] = set()
        unique_teams = []
        for t, lg in teams_raw:
            key = f"{(t.name or t.text or '').lower()}|{t.league_id}"
            if key not in seen_team_keys:
                seen_team_keys.add(key)
                unique_teams.append((t, lg))
        unique_teams = unique_teams[:8]
        if unique_teams:
            html_parts.append('<div class="search-category"><h3>👥 Teams</h3><div class="search-items">')
            for t, lg in unique_teams:
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

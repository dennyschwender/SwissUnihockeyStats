"""
Main FastAPI application entry point
"""
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager
import asyncio
import hashlib
import hmac
import uuid
import logging
import traceback
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
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Configure CORS
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET, session_cookie="admin_session")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router (JSON endpoints)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


# DEBUG endpoint to check player index status
@app.get("/debug/player-index")
async def debug_player_index():
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
async def debug_force_reindex():
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
async def debug_test_games_fetch():
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
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "locale": DEFAULT_LOCALE,
            "t": get_translations(DEFAULT_LOCALE)
        }
    )


# ============================================================================
# AUTH HELPERS
# ============================================================================

def _pin_hash(pin: str) -> str:
    """Stable hash of the PIN so we never store it plaintext in session."""
    return hashlib.pbkdf2_hmac(
        'sha256',
        pin.encode(),
        settings.SESSION_SECRET.encode(),
        1,
    ).hex()

_ADMIN_TOKEN_KEY = "admin_authed"

def require_admin(request: Request):
    """FastAPI dependency — raises 302 redirect if not logged in."""
    if request.session.get(_ADMIN_TOKEN_KEY) != _pin_hash(settings.ADMIN_PIN):
        raise HTTPException(status_code=307, headers={"Location": "/admin/login"})


# ============================================================================
# ADMIN LOGIN / LOGOUT
# ============================================================================

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if request.session.get(_ADMIN_TOKEN_KEY) == _pin_hash(settings.ADMIN_PIN):
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": None})


@app.post("/admin/login")
async def admin_login_submit(request: Request):
    form = await request.form()
    pin  = str(form.get("pin", "")).strip()
    if hmac.compare_digest(_pin_hash(pin), _pin_hash(settings.ADMIN_PIN)):
        request.session[_ADMIN_TOKEN_KEY] = _pin_hash(settings.ADMIN_PIN)
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse(
        "admin_login.html",
        {"request": request, "error": "Incorrect PIN. Try again."},
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
    return templates.TemplateResponse("admin.html", {"request": request})


@app.get("/admin/api/stats")
async def admin_stats(_: None = Depends(require_admin)):
    """Per-entity DB counts, per-season breakdown, and last 50 sync records."""
    from app.services.database import get_database_service
    from app.models.db_models import (
        Season, Club, Team, Player, TeamPlayer,
        League, LeagueGroup, Game, GameEvent, PlayerStatistics, SyncStatus
    )
    from sqlalchemy import func

    db_service = get_database_service()
    with db_service.session_scope() as session:
        totals = {
            "seasons":      session.query(func.count(Season.id)).scalar() or 0,
            "clubs":        session.query(Club).count(),
            "teams":        session.query(func.count(Team.id)).scalar() or 0,
            "players":      session.query(func.count(Player.person_id)).scalar() or 0,
            "team_players": session.query(func.count(TeamPlayer.id)).scalar() or 0,
            "leagues":      session.query(func.count(League.id)).scalar() or 0,
            "league_groups":session.query(func.count(LeagueGroup.id)).scalar() or 0,
            "games":        session.query(func.count(Game.id)).scalar() or 0,
            "game_events":    session.query(func.count(GameEvent.id)).scalar() or 0,
            "player_stats":   session.query(func.count(PlayerStatistics.id)).scalar() or 0,
        }

        season_rows = session.query(Season.id, Season.text, Season.highlighted).order_by(Season.id.desc()).all()
        by_season = []
        for sid, stext, shighlighted in season_rows:
            clubs_n   = session.query(Club).filter(Club.season_id == sid).count()
            teams_n   = session.query(Team).filter(Team.season_id == sid).count()
            tp_n      = session.query(TeamPlayer).filter(TeamPlayer.season_id == sid).count()
            leagues_n = session.query(League).filter(League.season_id == sid).count()
            groups_n  = (session.query(func.count(LeagueGroup.id))
                         .join(League, LeagueGroup.league_id == League.id)
                         .filter(League.season_id == sid).scalar() or 0)
            games_n        = session.query(Game).filter(Game.season_id == sid).count()
            events_n       = (session.query(func.count(GameEvent.id))
                              .join(Game, GameEvent.game_id == Game.id)
                              .filter(Game.season_id == sid).scalar() or 0)
            player_stats_n = (session.query(func.count(PlayerStatistics.id))
                              .filter(PlayerStatistics.season_id == sid).scalar() or 0)
            by_season.append({
                "season_id":     sid,
                "season_text":   stext or str(sid),
                "clubs":         clubs_n,
                "teams":         teams_n,
                "team_players":  tp_n,
                "leagues":       leagues_n,
                "league_groups": groups_n,
                "games":         games_n,
                "game_events":   events_n,
                "player_stats":  player_stats_n,
                "is_current":    bool(shighlighted),
            })

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

    return {"totals": totals, "by_season": by_season, "sync_status": sync_status}


# In-memory job registry for background indexing tasks
_admin_jobs: dict  = {}
_admin_tasks: dict = {}  # job_id → asyncio.Task (running only)


async def _submit_job(job_id: str, season: int | None, task: str, force: bool = False, max_tier: int = 7):
    """Bridge used by the scheduler to start an _run() coroutine for a pre-registered job."""
    t = asyncio.create_task(_run(job_id, season, task, force, max_tier=max_tier), name=f"job-{job_id}")
    _admin_tasks[job_id] = t

# Task definitions: human label + which tasks it maps to internally
_TASK_META = {
    "seasons":      "Index Seasons",
    "clubs":        "Index Clubs",
    "teams":        "Index Teams (all clubs)",
    "players":      "Index Players (all teams)",
    "clubs_path":   "Index Clubs Path (clubs + teams + players)",
    "leagues":      "Index Leagues",
    "groups":       "Index League Groups",
    "games":        "Index Games",
    "events":       "Index Game Events (finished games)",
    "player_stats": "Index Player Statistics",
    "leagues_path": "Index Leagues Path (leagues + groups + games)",
    "full":         "Full Index (clubs path + leagues path)",
}


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


@app.get("/admin/api/jobs/{job_id}")
async def admin_job_status(job_id: str, _: None = Depends(require_admin)):
    """Return current status and buffered log lines for a running job."""
    job = _admin_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    log_lines = job.pop("log_lines", [])
    job["log_lines"] = []
    return {**job, "log_lines": log_lines}


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
        "history": sched.get_history(50),
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
    if action == "trigger":
        policy = payload.get("policy")
        season = payload.get("season")
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


# ==================== END ADMIN ROUTES ====================


async def _run(job_id: str, season: int | None, task: str, force: bool, max_tier: int = 7):
    """Module-level coroutine that drives a single indexing job.

    Args:
        max_tier: For events tasks, only process leagues with tier <= max_tier.
                  1=L-UPL/NLA only, 2=+NLB, … 7=all (default).
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
            n = indexer.index_seasons(force=True)
            stats["seasons"] = n
            push("ok", f"Seasons: {n}")
            set_progress(100)

        # ── CLUBS ──────────────────────────────────────────────────────────
        if task in ("clubs", "clubs_path", "full"):
            push("info", f"Indexing clubs for season {season}...")
            n = indexer.index_clubs(season, force=force)
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
                cnt, tids = indexer.index_teams_for_club(cid, season, force=force)
                teams_n += cnt
                team_id_list.extend(tids)
                set_progress(10 + int(i / total * 25))
                await asyncio.sleep(0)
            stats["teams"] = teams_n
            push("ok", f"Teams: {teams_n}")

        # ── PLAYERS ────────────────────────────────────────────────────────
        if task in ("players", "clubs_path", "full"):
            if "team_id_list" not in dir():
                with db_service.session_scope() as s:
                    team_id_list = [r[0] for r in
                                    s.query(Team.id).filter(Team.season_id == season).distinct().all()]
            total = len(team_id_list)
            push("info", f"Indexing players for {total} teams...")
            players_n = 0
            for i, tid in enumerate(team_id_list, 1):
                players_n += indexer.index_players_for_team(tid, season, force=force)
                set_progress(35 + int(i / total * 25))
                await asyncio.sleep(0)
            stats["players"] = players_n
            push("ok", f"Players: {players_n}")

        # ── PLAYER STATS ───────────────────────────────────────────────────
        if task in ("player_stats", "clubs_path", "full"):
            push("info", f"Indexing player statistics for season {season}...")
            stats_n = indexer.index_player_stats_for_season(season, force=force)
            stats["player_stats"] = stats_n
            push("ok", f"Player stats: {stats_n}")
            set_progress(60)

        # ── LEAGUES ────────────────────────────────────────────────────────
        if task in ("leagues", "groups", "games", "leagues_path", "full"):
            push("info", f"Indexing leagues for season {season}...")
            n = indexer.index_leagues(season, force=force)
            stats["leagues"] = n
            push("ok", f"Leagues: {n}")
            set_progress(62)

        # ── GROUPS ─────────────────────────────────────────────────────────
        if task in ("groups", "games", "leagues_path", "full"):
            with db_service.session_scope() as s:
                lg_list = [(lg.id, lg.league_id, lg.game_class) for lg in
                           s.query(League).filter(League.season_id == season).all()]
            total  = len(lg_list)
            groups_n = 0
            push("info", f"Indexing groups for {total} leagues...")
            for i, (ldb, lid, gc) in enumerate(lg_list, 1):
                groups_n += indexer.index_groups_for_league(ldb, season, lid, gc, force=force)
                set_progress(62 + int(i / total * 13))
                await asyncio.sleep(0)
            stats["league_groups"] = groups_n
            push("ok", f"Groups: {groups_n}")

        # ── GAMES ──────────────────────────────────────────────────────────
        if task in ("games", "leagues_path", "full"):
            from app.models.db_models import LeagueGroup
            if "lg_list" not in dir():
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
            push("info", f"Indexing games for {total} groups across {len(lg_list)} leagues...")
            for i, (ldb, lid, gc, grp_db_id, grp_name) in enumerate(work, 1):
                games_n += indexer.index_games_for_league(
                    ldb, season, lid, gc,
                    group_name=grp_name, group_db_id=grp_db_id,
                    force=force,
                )
                set_progress(75 + int(i / total * 20))
                await asyncio.sleep(0)
            stats["games"] = games_n
            push("ok", f"Games: {games_n}")

        # ── GAME EVENTS ────────────────────────────────────────────────────
        if task in ("events", "full"):
            from datetime import datetime as _dt
            from app.services.data_indexer import league_tier
            _now = _dt.utcnow()
            with db_service.session_scope() as s:
                # Join Game → League to filter by tier
                from app.models.db_models import LeagueGroup, League as _League
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
                    if league_tier(r.league_id or 0) <= max_tier
                ]
            total    = len(finished)
            tier_lbl = f"tier ≤ {max_tier}" if max_tier < 7 else "all tiers"
            push("info", f"Indexing events for {total} past games ({tier_lbl})...")
            events_n = 0
            for i, (gid, sid_) in enumerate(finished, 1):
                events_n += indexer.index_game_events(gid, sid_, force=force)
                set_progress(int(i / total * 95) if total else 99)
                await asyncio.sleep(0)
            stats["game_events"] = events_n
            push("ok", f"Game events: {events_n}")

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
        job["error"]  = str(exc)
        logger.error("Admin indexing job %s failed: %s", job_id, exc, exc_info=True)
    finally:
        _admin_tasks.pop(job_id, None)


@app.get("/{locale}", response_class=HTMLResponse)
async def home(request: Request, locale: str):
    """Homepage with language selection"""
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "locale": locale,
            "t": get_translations(locale)
        }
    )


@app.get("/{locale}/clubs", response_class=HTMLResponse)
async def clubs_page(request: Request, locale: str):
    """Clubs listing page"""
    # Use cached data instead of API call (loads on-demand if needed)
    clubs_list = await get_cached_clubs()
    
    return templates.TemplateResponse(
        "clubs.html",
        {
            "request": request,
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
    
    # Return partial HTML for htmx
    html = ""
    for club in filtered_clubs:
        club_name = club.get("text", "Unknown")
        html += f'<div class="club-card"><h3>{club_name}</h3></div>'
    
    if not filtered_clubs:
        html = f'<div style="text-align: center; padding: 3rem; color: var(--text-muted);">{get_translations(locale).common.get("no_results", "No results found")}</div>'
    
    return HTMLResponse(content=html)


@app.get("/{locale}/club/{club_id}", response_class=HTMLResponse)
async def club_detail(request: Request, locale: str, club_id: int):
    """Club detail page with teams and players"""
    client = get_swissunihockey_client()
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
            current_season = get_current_season()
            
            # Fetch teams for this club
            try:
                teams_data = client.get_teams(club=club_id, season=current_season)
                teams = teams_data.get("entries", [])[:30] if isinstance(teams_data, dict) else []
            except Exception as team_error:
                logger.warning(f"Could not load teams for club {club_id}: {team_error}")
            
            # Fetch players for this club
            try:
                players_data = client.get_players(club=club_id, season=current_season)
                players = players_data.get("entries", [])[:50] if isinstance(players_data, dict) else []
            except Exception as player_error:
                logger.warning(f"Could not load players for club {club_id}: {player_error}")
        else:
            error_message = f"Club with ID {club_id} not found"
            logger.warning(error_message)
    
    except Exception as e:
        logger.error(f"Error fetching club {club_id}: {e}")
        error_message = f"Could not load club details: {str(e)}"
    
    return templates.TemplateResponse(
        "club_detail.html",
        {
            "request": request,
            "locale": locale,
            "t": get_translations(locale),
            "club": club_data,
            "teams": teams,
            "players": players,
            "error_message": error_message
        }
    )


@app.get("/{locale}/leagues", response_class=HTMLResponse)
async def leagues_page(request: Request, locale: str):
    """Leagues listing page"""
    # Use cached data instead of API call (loads on-demand if needed)
    leagues_list = await get_cached_leagues()
    
    # Group leagues: First by gender/category, then by league level, then by groups
    from collections import defaultdict
    
    # Structure: {gender: {league_level: [league_entries]}}
    gender_leagues = defaultdict(lambda: defaultdict(list))
    
    for idx, league in enumerate(leagues_list, 1):
        league_num = league.get("set_in_context", {}).get("league")
        game_class = league.get("set_in_context", {}).get("game_class")
        
        if league_num and game_class:
            # Determine gender/category from game_class
            if game_class in [11, 12]:  # Men and Men U21
                gender = "men"
            elif game_class in [21, 22]:  # Women and Women U21
                gender = "women"
            elif game_class == 31:  # Mixed
                gender = "mixed"
            else:
                gender = "other"
            
            league_with_index = {**league, "_index": idx, "_game_class": game_class}
            gender_leagues[gender][league_num].append(league_with_index)
    
    # Sort each gender's leagues by level, and sort leagues within each level
    for gender in gender_leagues:
        gender_leagues[gender] = dict(sorted(gender_leagues[gender].items()))
    
    # Order genders: Men, Women, Mixed, Other
    gender_order = ["men", "women", "mixed", "other"]
    ordered_gender_leagues = {
        gender: gender_leagues[gender] 
        for gender in gender_order 
        if gender in gender_leagues
    }
    
    return templates.TemplateResponse(
        "leagues.html",
        {
            "request": request,
            "locale": locale,
            "t": get_translations(locale),
            "leagues": leagues_list,  # Keep original for backwards compatibility
            "gender_leagues": ordered_gender_leagues
        }
    )


@app.get("/{locale}/league/{league_id}", response_class=HTMLResponse)
async def league_detail(request: Request, locale: str, league_id: int):
    """League detail page with standings, teams, and top scorers"""
    client = get_swissunihockey_client()
    error_message = None
    league_data = {}
    teams = []
    standings = []
    topscorers = []
    games = []
    
    try:
        # Get league from cache
        all_leagues = await get_cached_leagues()
        
        # Try multiple ways to find the league:
        # 1. By league_id in set_in_context
        matching_leagues = [
            l for l in all_leagues
            if l.get("set_in_context", {}).get("league_id") == league_id
        ]
        
        # 2. If not found, try by top-level id field
        if not matching_leagues:
            matching_leagues = [
                l for l in all_leagues
                if l.get("id") == league_id
            ]
        
        # 3. If still not found and league_id is small (< 1000), try by index
        if not matching_leagues and league_id < 1000 and league_id <= len(all_leagues):
            matching_leagues = [all_leagues[league_id - 1]]  # Convert to 0-based index
        
        if matching_leagues:
            league_data = matching_leagues[0]
            # Extract the actual league parameters from the data for API calls
            actual_league = league_data.get("set_in_context", {}).get("league")
            game_class = league_data.get("set_in_context", {}).get("game_class")
            league_mode = league_data.get("set_in_context", {}).get("mode", "1")
            
            # Store these for template use
            league_data["_league_param"] = actual_league
            league_data["_game_class_param"] = game_class
            
            logger.info(f"Found league: {league_data.get('text')} (league={actual_league}, game_class={game_class}, mode={league_mode})")
            current_season = get_current_season()
            logger.info(f"API parameters: league={actual_league}, game_class={game_class}, mode={league_mode}, season={current_season}")
            
            # Fetch teams for this league
            try:
                logger.info(f"Fetching teams for league {actual_league}, game_class {game_class}")
                teams_data = client.get_teams(league=actual_league, game_class=game_class, mode=league_mode, season=current_season)
                logger.info(f"Teams response type: {type(teams_data)}, keys: {teams_data.keys() if isinstance(teams_data, dict) else 'N/A'}")
                # API v2 returns data.regions[0].rows structure
                teams = teams_data.get("entries", [])
                if not teams and isinstance(teams_data, dict):
                    regions = teams_data.get("data", {}).get("regions", [])
                    teams = regions[0].get("rows", []) if regions else []
                teams = teams[:50]
                logger.info(f"Loaded {len(teams)} teams")
            except Exception as team_error:
                logger.warning(f"Could not load teams for league {actual_league}: {team_error}")
            
            # Fetch standings
            try:
                logger.info(f"Fetching standings for league {actual_league}, game_class {game_class}")
                standings_data = client.get_rankings(league=actual_league, game_class=game_class, mode=league_mode, season=current_season)
                logger.info(f"Standings response type: {type(standings_data)}, keys: {standings_data.keys() if isinstance(standings_data, dict) else 'N/A'}")
                # API v2 returns data.regions[0].rows structure
                standings = standings_data.get("entries", [])
                if not standings and isinstance(standings_data, dict):
                    regions = standings_data.get("data", {}).get("regions", [])
                    standings = regions[0].get("rows", []) if regions else []
                standings = standings[:30]
                logger.info(f"Loaded {len(standings)} standings entries")
            except Exception as standings_error:
                logger.warning(f"Could not load standings for league {actual_league}: {standings_error}")
            
            # Fetch top scorers
            try:
                logger.info(f"Fetching top scorers for league {actual_league}, game_class {game_class}")
                topscorers_data = client.get_topscorers(league=actual_league, game_class=game_class, mode=league_mode, season=current_season)
                logger.info(f"Top scorers response type: {type(topscorers_data)}, keys: {topscorers_data.keys() if isinstance(topscorers_data, dict) else 'N/A'}")
                # API v2 returns data.regions[0].rows structure
                topscorers = topscorers_data.get("entries", [])
                if not topscorers and isinstance(topscorers_data, dict):
                    regions = topscorers_data.get("data", {}).get("regions", [])
                    topscorers = regions[0].get("rows", []) if regions else []
                topscorers = topscorers[:30]
                logger.info(f"Loaded {len(topscorers)} top scorers")
            except Exception as scorers_error:
                logger.warning(f"Could not load top scorers for league {actual_league}: {scorers_error}")
            
            # Fetch recent games
            try:
                logger.info(f"Fetching games for league {actual_league}, game_class {game_class}")
                games_data = client.get_games(league=actual_league, game_class=game_class, mode=league_mode, season=current_season)
                logger.info(f"Games response type: {type(games_data)}, keys: {games_data.keys() if isinstance(games_data, dict) else 'N/A'}")
                # API v2 returns data.regions[0].rows structure
                games = games_data.get("entries", [])
                if not games and isinstance(games_data, dict):
                    regions = games_data.get("data", {}).get("regions", [])
                    games = regions[0].get("rows", []) if regions else []
                games = games[:20]
                logger.info(f"Loaded {len(games)} games")
            except Exception as games_error:
                logger.warning(f"Could not load games for league {actual_league}: {games_error}")
        else:
            error_message = f"League with ID {league_id} not found. Please try selecting from the leagues list."
            logger.warning(f"League {league_id} not found. Total leagues available: {len(all_leagues)}")
    
    except Exception as e:
        logger.error(f"Error fetching league {league_id}: {e}")
        error_message = f"Could not load league details: {str(e)}"
    
    return templates.TemplateResponse(
        "league_detail.html",
        {
            "request": request,
            "locale": locale,
            "t": get_translations(locale),
            "league": league_data,
            "teams": teams,
            "standings": standings,
            "topscorers": topscorers,
            "games": games,
            "error_message": error_message
        }
    )


@app.get("/{locale}/teams", response_class=HTMLResponse)
async def teams_page(request: Request, locale: str):
    """Teams listing page"""
    try:
        teams_list = await get_cached_teams()
        error_message = None
        
        # Limit to first 50 teams for initial display
        display_teams = teams_list[:50] if isinstance(teams_list, list) else []
        
        return templates.TemplateResponse(
            "teams.html",
            {
                "request": request,
                "locale": locale,
                "t": get_translations(locale),
                "teams": display_teams,
                "error_message": error_message
            }
        )
    except Exception as e:
        logger.error(f"Error in teams_page: {type(e).__name__}: {e}", exc_info=True)
        raise


@app.get("/{locale}/teams/search", response_class=HTMLResponse)
async def teams_search(request: Request, locale: str, q: str = "", mode: str = "all"):
    """HTMX endpoint for team search"""
    # Use cached data instead of API call - instant results! (loads on-demand if needed)
    all_teams = await get_cached_teams()
    
    # Filter teams by search query and mode
    filtered_teams = all_teams
    if q:
        filtered_teams = [
            team for team in filtered_teams
            if q.lower() in team.get("text", "").lower()
        ]
    
    if mode != "all":
        filtered_teams = [
            team for team in filtered_teams
            if str(team.get("set_in_context", {}).get("mode", "")) == mode
        ]
    
    filtered_teams = filtered_teams[:50]
    
    # Return partial HTML for htmx
    html = '<div class="cards-grid">'
    for team in filtered_teams:
        club_name = team.get("set_in_context", {}).get("club_name", "N/A")
        league_name = team.get("set_in_context", {}).get("league_name", "N/A")
        team_id = team.get("id", "")
        html += f'''
        <div class="card" style="cursor: pointer;" onclick="window.location='/{locale}/team/{team_id}'">
            <div class="card-icon">👥</div>
            <h3>{team.get("text", "")}</h3>
            <p style="color: var(--gray-600); font-size: 0.875rem;">
                Club: {club_name}<br>
                League: {league_name}
            </p>
        </div>
        '''
    html += '</div>'
    
    if not filtered_teams:
        html = '<div style="text-align: center; padding: 3rem; color: var(--gray-600);"><p>No teams found</p></div>'
    
    return HTMLResponse(content=html)


# ==================== Detail Pages ====================

@app.get("/{locale}/team/{team_id}", response_class=HTMLResponse)
async def team_detail(request: Request, locale: str, team_id: int, league: int = None, game_class: int = None):
    """Team detail page"""
    client = get_swissunihockey_client()
    error_message = None
    team_data = {}
    players = []
    games = []
    
    try:
        current_season = get_current_season()
        # If we have league and game_class, fetch team info from teams API
        if league is not None and game_class is not None:
            try:
                teams_data = client.get_teams(league=league, game_class=game_class, season=current_season)
                regions = teams_data.get("data", {}).get("regions", [])
                if regions:
                    all_teams = regions[0].get("rows", [])
                    # Find our team in the list
                    matching_teams = [t for t in all_teams if t.get("id") == team_id]
                    if matching_teams:
                        team_raw = matching_teams[0]
                        # Extract team name from cells[0].text[0]
                        team_name = team_raw.get("cells", [{}])[0].get("text", [f"Team {team_id}"])[0]
                        team_data = {
                            "id": team_id,
                            "text": team_name,
                            "club_name": team_raw.get("cells", [{}])[0].get("text", [""])[0] if len(team_raw.get("cells", [])) > 0 else ""
                        }
                        logger.info(f"Found team: {team_name}")
            except Exception as team_error:
                logger.warning(f"Could not load team from teams API: {team_error}")
        
        # Try to fetch players for this team
        try:
            players_data = client.get_players(team=team_id, season=current_season)
            logger.info(f"Players response type: {type(players_data)}, keys: {players_data.keys() if isinstance(players_data, dict) else 'N/A'}")
            
            # If we don't have team_data yet, try to extract from players response
            if not team_data and isinstance(players_data, dict):
                team_context = players_data.get("data", {}).get("context", {})
                if team_context:
                    team_data = {
                        "id": team_id,
                        "text": team_context.get("team_name", f"Team {team_id}"),
                        "club_name": team_context.get("club_name", ""),
                    }
                    logger.info(f"Found team info in players context: {team_data}")
            
            # Extract players from response
            if isinstance(players_data, dict):
                regions = players_data.get("data", {}).get("regions", [])
                if regions:
                    players = regions[0].get("rows", [])
                else:
                    players = players_data.get("entries", [])
                logger.info(f"Loaded {len(players)} players")
        except Exception as player_error:
            logger.warning(f"Could not load players for team {team_id}: {player_error}")
            players = []
        
        # If still no team_data, try cache
        if not team_data:
            all_teams = await get_cached_teams()
            matching_teams = [t for t in all_teams if t.get("id") == team_id]
            if matching_teams:
                team_data = matching_teams[0]
        
        # If STILL no team_data, search through leagues to find the team
        if not team_data or team_data.get("text", "").startswith("Team "):
            logger.info(f"Searching through leagues to find team {team_id}")
            try:
                all_leagues = await get_cached_leagues()
                found = False
                # Try common league/game_class combinations
                for league_data in all_leagues[:20]:  # Check first 20 leagues
                    if found:
                        break
                    league_num = league_data.get("set_in_context", {}).get("league")
                    game_class_num = league_data.get("set_in_context", {}).get("game_class")
                    if league_num and game_class_num:
                        try:
                            teams_data = client.get_teams(league=league_num, game_class=game_class_num, season=current_season)
                            regions = teams_data.get("data", {}).get("regions", [])
                            if regions:
                                all_teams = regions[0].get("rows", [])
                                matching_teams = [t for t in all_teams if t.get("id") == team_id]
                                if matching_teams:
                                    team_raw = matching_teams[0]
                                    team_name = team_raw.get("cells", [{}])[0].get("text", [f"Team {team_id}"])[0]
                                    team_data = {
                                        "id": team_id,
                                        "text": team_name,
                                        "club_name": team_raw.get("cells", [{}])[0].get("text", [""])[0] if len(team_raw.get("cells", [])) > 0 else ""
                                    }
                                    logger.info(f"Found team '{team_name}' in league {league_num}/{game_class_num}")
                                    found = True
                                    break
                        except Exception as search_error:
                            continue  # Try next league
            except Exception as search_error:
                logger.warning(f"Error searching for team in leagues: {search_error}")
        
        # Final fallback
        if not team_data:
            team_data = {"id": team_id, "text": f"Team {team_id}"}
        
        # Note: Games API doesn't support filtering by team ID or by league/game_class
        # Teams without roster data typically also don't have games data
        # Leave games empty to show "No Recent Games" message
        games = []
        
        # If we still don't have team_data, show error
        if not team_data or not team_data.get("text"):
            error_message = f"Team with ID {team_id} not found"
            logger.warning(error_message)
            
    except Exception as e:
        logger.error(f"Error fetching team {team_id}: {e}")
        error_message = f"Could not load team details: {str(e)}"
        team_data = {"id": team_id, "text": f"Team {team_id}"}
        players = []
        games = []
    
    return templates.TemplateResponse(
        "team_detail.html",
        {
            "request": request,
            "locale": locale,
            "t": get_translations(locale),
            "team": team_data,
            "players": players,
            "games": games,
            "error_message": error_message
        }
    )


@app.get("/{locale}/players", response_class=HTMLResponse)
async def players_page(request: Request, locale: str):
    """Players search page"""
    return templates.TemplateResponse(
        "players.html",
        {
            "request": request,
            "locale": locale,
            "t": get_translations(locale),
            "players": []  # Start with no players, use search to load
        }
    )


@app.get("/{locale}/players/search", response_class=HTMLResponse)
async def search_players(request: Request, locale: str, q: str = "", team: str = "", club: str = ""):
    """Search players endpoint
    
    Searches player database indexed from Swiss Unihockey API.
    """
    try:
        filtered_players = []
        
        # If team or club specified, use the API endpoint directly
        if team or club:
            client = get_swissunihockey_client()
            params = {}
            if team:
                params['team'] = team
            if club:
                params['club'] = club
            players_data = client.get_players(**params)
            all_players = players_data.get("entries", players_data.get("data", [])) if isinstance(players_data, dict) else []
            
            # Filter by query if provided
            if q:
                q_lower = q.lower()
                filtered_players = [
                    p for p in all_players
                    if q_lower in str(p.get("text", "")).lower()
                    or q_lower in str(p.get("given_name", "")).lower()
                    or q_lower in str(p.get("family_name", "")).lower()
                ]
            else:
                filtered_players = all_players[:50]
        
        # If we have a search query, search through database
        elif q:
            # Search through database
            from app.services.database import get_database_service
            from app.models.db_models import Player, TeamPlayer, Team
            from sqlalchemy import or_
            
            q_lower = q.lower()
            db_service = get_database_service()
            
            with db_service.session_scope() as session:
                # Search players by name
                db_players = session.query(Player).filter(
                    or_(
                        Player.full_name.ilike(f"%{q}%"),
                        Player.name_normalized.like(f"%{q_lower}%")
                    )
                ).limit(50).all()
                
                # Convert database players to format expected by template
                for player in db_players:
                    # Get most recent team
                    team_name = "N/A"
                    if player.team_memberships:
                        # Get the most recently updated team membership
                        latest_membership = max(player.team_memberships, key=lambda x: x.last_updated)
                        if latest_membership.team:
                            team_name = latest_membership.team.name
                    
                    filtered_players.append({
                        "id": player.person_id,
                        "name": player.full_name,
                        "text": player.full_name,
                        "team": team_name,
                        "position": ""
                    })
            
            logger.info(f"Found {len(filtered_players)} players matching '{q}'")
        
    except Exception as e:
        logger.error(f"Error searching players: {e}")
        filtered_players = []
    
    # Generate HTML response for search results
    html = '<div class="cards-grid">'
    for player in filtered_players:
        # Extract player name
        player_name = player.get("name", player.get("text", ""))
        if not player_name:
            player_name = f"{player.get('given_name', '')} {player.get('family_name', '')}".strip()
        
        player_id = player.get("id", 0)
        team_name = player.get("team", player.get("set_in_context", {}).get("team_name", "N/A"))
        position = player.get("position", "")
        
        html += f'''
        <div class="card" onclick="window.location='/{locale}/player/{player_id}'">
            <div class="card-icon">👤</div>
            <h3>{player_name}</h3>
            <p style="color: var(--gray-600); font-size: 0.875rem;">
                Team: {team_name}<br>
                {"Position: " + position if position else ""}
            </p>
        </div>
        '''
    html += '</div>'
    
    if not filtered_players:
        if q:
            html = '<div style="text-align: center; padding: 3rem; color: var(--gray-600);"><p>No players found matching your search</p></div>'
        else:
            html = '<div style="text-align: center; padding: 3rem; color: var(--gray-600);"><p>Enter a player name to search</p></div>'
    
    return HTMLResponse(content=html)


@app.get("/{locale}/player/{player_id}", response_class=HTMLResponse)
async def player_detail(request: Request, locale: str, player_id: int):
    """Player detail page"""
    client = get_swissunihockey_client()
    error_message = None
    player_data = {}
    
    try:
        # Fetch all players and find the one with matching ID
        # Note: This could be optimized with player caching in the future
        players_data = client.get_players()
        all_players = players_data.get("entries", players_data.get("data", [])) if isinstance(players_data, dict) else []
        
        # Find the player with matching ID
        matching_players = [p for p in all_players if p.get("id") == player_id]
        
        if matching_players:
            player_data = matching_players[0]
        else:
            error_message = f"Player with ID {player_id} not found"
            logger.warning(error_message)
            
    except Exception as e:
        logger.error(f"Error fetching player {player_id}: {e}")
        error_message = f"Could not load player details: {str(e)}"
        player_data = {}
    
    return templates.TemplateResponse(
        "player_detail.html",
        {
            "request": request,
            "locale": locale,
            "t": get_translations(locale),
            "player": player_data,
            "error_message": error_message
        }
    )


# ==================== Other Pages ====================

@app.get("/{locale}/games", response_class=HTMLResponse)
async def games_page(request: Request, locale: str):
    """Games schedule page"""
    client = get_swissunihockey_client()
    
    try:
        games_data = client.get_games()
        games = games_data.get("entries", [])[:50] if isinstance(games_data, dict) else []
    except Exception as e:
        # Handle API errors gracefully
        games = []
    
    return templates.TemplateResponse(
        "games.html",
        {
            "request": request,
            "locale": locale,
            "t": get_translations(locale),
            "games": games
        }
    )


@app.get("/{locale}/game/{game_id}", response_class=HTMLResponse)
async def game_detail(request: Request, locale: str, game_id: int):
    """Game detail page with events and statistics"""
    client = get_swissunihockey_client()
    error_message = None
    game_data = {}
    events = []
    
    try:
        # Fetch game events which includes game details
        game_events_data = client.get_game_events(game_id=game_id)
        
        if game_events_data:
            # Extract game info and events
            game_data = game_events_data.get("game", {})
            events = game_events_data.get("events", [])
            
            # If game_id not in data, add it
            if not game_data.get("game_id"):
                game_data["game_id"] = game_id
        else:
            error_message = f"Game with ID {game_id} not found"
            logger.warning(error_message)
    
    except Exception as e:
        logger.error(f"Error fetching game {game_id}: {e}")
        error_message = f"Could not load game details: {str(e)}"
    
    return templates.TemplateResponse(
        "game_detail.html",
        {
            "request": request,
            "locale": locale,
            "t": get_translations(locale),
            "game": game_data,
            "events": events,
            "error_message": error_message
        }
    )


@app.get("/{locale}/rankings", response_class=HTMLResponse)
async def rankings_page(request: Request, locale: str):
    """Rankings and top scorers page"""
    client = get_swissunihockey_client()
    
    # Note: These methods might need league_id parameters in production
    # For now, using mock data structure
    standings = []
    topscorers = []
    
    # Try to get rankings if available
    try:
        standings_data = client.get_table()
        if isinstance(standings_data, dict) and "entries" in standings_data:
            standings = standings_data["entries"][:20]
    except:
        pass
    
    try:
        topscorers_data = client.get_top_scorers()
        if isinstance(topscorers_data, dict) and "entries" in topscorers_data:
            topscorers = topscorers_data["entries"][:20]
    except:
        pass
    
    return templates.TemplateResponse(
        "rankings.html",
        {
            "request": request,
            "locale": locale,
            "t": get_translations(locale),
            "standings": standings,
            "topscorers": topscorers
        }
    )


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
    
    # Determine status message
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


# ============================================================================
# Universal Search
# ============================================================================

@app.get("/{locale}/search", response_class=HTMLResponse)
async def universal_search(request: Request, locale: str, q: str = ""):
    """Universal search across clubs, leagues, and teams"""
    if not q or len(q) < 2:
        return HTMLResponse(content='<div class="search-results"><p class="text-gray-600">Enter at least 2 characters to search...</p></div>')
    
    query_lower = q.lower()
    all_clubs = []
    all_leagues = []
    all_teams = []
    
    try:
        # Fetch data from API client (testable via mocking get_swissunihockey_client)
        client = get_swissunihockey_client()
        clubs_data = client.get_clubs()
        leagues_data = client.get_leagues()
        teams_data = client.get_teams()
        
        all_clubs = clubs_data.get("entries", []) if clubs_data else []
        all_leagues = leagues_data.get("entries", []) if leagues_data else []
        all_teams = teams_data.get("entries", []) if teams_data else []
    except Exception as e:
        try:
            # Fallback to cached data if API call fails
            all_clubs = await get_cached_clubs()
            all_leagues = await get_cached_leagues()
            all_teams = await get_cached_teams()
        except Exception:
            # If both API and cache fail, return empty results
            return HTMLResponse(content='<div class="search-results"><p class="text-gray-600" style="text-align: center; padding: 2rem;">Service temporarily unavailable</p></div>')
    
    # Search clubs
    matching_clubs = [
        club for club in all_clubs
        if query_lower in club.get("text", "").lower()
    ][:5]  # Limit to 5 results per category
    
    # Search leagues
    matching_leagues = [
        league for league in all_leagues
        if query_lower in league.get("text", "").lower()
    ][:5]
    
    # Search teams (now works instantly with 30,000+ records via cache!)
    matching_teams = [
        team for team in all_teams
        if query_lower in team.get("text", "").lower()
    ][:5]
    
    # Build HTML response
    html = '<div class="search-results">'
    
    total_results = len(matching_clubs) + len(matching_leagues) + len(matching_teams)
    
    if total_results == 0:
        html += '<p class="text-gray-600" style="text-align: center; padding: 2rem;">No results found</p>'
    elif total_results > 0:
        # Clubs section
        if matching_clubs:
            html += '<div class="search-category"><h3>🏢 Clubs</h3><div class="search-items">'
            for club in matching_clubs:
                club_id = club.get("set_in_context", {}).get("club_id", "")
                html += f'''
                <div class="search-item" onclick="window.location.href='/{locale}/clubs'">
                    <strong>{club.get("text", "")}</strong>
                    <span class="text-gray-600">Club ID: {club_id}</span>
                </div>
                '''
            html += '</div></div>'
        
        # Leagues section  
        if matching_leagues:
            html += '<div class="search-category"><h3>🏆 Leagues</h3><div class="search-items">'
            for league in matching_leagues:
                html += f'''
                <div class="search-item" onclick="window.location.href='/{locale}/leagues'">
                    <strong>{league.get("text", "")}</strong>
                </div>
                '''
            html += '</div></div>'
        
        # Teams section
        if matching_teams:
            html += '<div class="search-category"><h3>👥 Teams</h3><div class="search-items">'
            for team in matching_teams:
                html += f'''
                <div class="search-item" onclick="window.location.href='/{locale}/teams'">
                    <strong>{team.get("text", "")}</strong>
                </div>
                '''
            html += '</div></div>'
    
    html += '</div>'
    return HTMLResponse(content=html)


@app.get("/{locale}/favorites", response_class=HTMLResponse)
async def favorites_page(request: Request, locale: str):
    """Favorites page"""
    return templates.TemplateResponse(
        "favorites.html",
        {
            "request": request,
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
            "error_404.html",
            {
                "request": request,
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
        "error_500.html",
        {
            "request": request,
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

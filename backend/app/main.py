"""
Main FastAPI application entry point
"""
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager
import uuid
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events: startup and shutdown"""
    # Startup: Preload common data (leagues, popular teams)
    logger.info("🚀 Starting SwissUnihockey application...")
    try:
        await preload_common_data()  # Loads leagues and popular teams
        # Note: Remaining teams will lazy-load on first search
    except Exception as e:
        logger.error(f"❌ Failed to preload common data: {e}")
        logger.warning("⚠️ App will start but may load data on first request")
    
    # Optionally preload ALL data including all teams (uncomment for full preload):
    # await preload_data()
    
    yield
    
    # Shutdown
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router (JSON endpoints)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


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


@app.get("/{locale}/leagues", response_class=HTMLResponse)
async def leagues_page(request: Request, locale: str):
    """Leagues listing page"""
    # Use cached data instead of API call (loads on-demand if needed)
    leagues_list = await get_cached_leagues()
    
    return templates.TemplateResponse(
        "leagues.html",
        {
            "request": request,
            "locale": locale,
            "t": get_translations(locale),
            "leagues": leagues_list
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
async def team_detail(request: Request, locale: str, team_id: int):
    """Team detail page"""
    client = get_swissunihockey_client()
    error_message = None
    team_data = {}
    players = []
    games = []
    
    try:
        # Get team from cache (teams are loaded on demand)
        all_teams = await get_cached_teams()
        
        # Find the team with matching ID
        matching_teams = [t for t in all_teams if t.get("id") == team_id]
        
        if matching_teams:
            team_data = matching_teams[0]
            
            # Try fetching players for this team
            try:
                players_data = client.get_players(team=team_id)
                players = players_data.get("entries", players_data.get("data", [])) if isinstance(players_data, dict) else []
            except Exception as player_error:
                logger.warning(f"Could not load players for team {team_id}: {player_error}")
                players = []
            
            # Try fetching games for this team
            try:
                games_data = client.get_games(team=team_id)
                games = games_data.get("entries", games_data.get("data", []))[:10] if isinstance(games_data, dict) else []
            except Exception as game_error:
                logger.warning(f"Could not load games for team {team_id}: {game_error}")
                games = []
        else:
            error_message = f"Team with ID {team_id} not found"
            logger.warning(error_message)
            
    except Exception as e:
        logger.error(f"Error fetching team {team_id}: {e}")
        error_message = f"Could not load team details: {str(e)}"
        team_data = {}
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
    """Search players endpoint"""
    client = get_swissunihockey_client()
    
    try:
        params = {}
        if team:
            params['team'] = team
        if club:
            params['club'] = club
            
        players_data = client.get_players(**params)
        all_players = players_data.get("entries", players_data.get("data", [])) if isinstance(players_data, dict) else []
        
        # Filter by query string if provided
        if q:
            q_lower = q.lower()
            filtered_players = [
                p for p in all_players
                if q_lower in str(p.get("given_name", "")).lower() 
                or q_lower in str(p.get("family_name", "")).lower()
                or q_lower in str(p.get("text", "")).lower()
            ]
        else:
            filtered_players = all_players[:50]  # Limit to 50 if no search query
    except Exception as e:
        logger.error(f"Error searching players: {e}")
        filtered_players = []
    
    # Generate HTML response for search results
    html = '<div class="cards-grid">'
    for player in filtered_players:
        player_name = player.get("text", f"{player.get('given_name', '')} {player.get('family_name', '')}").strip()
        player_id = player.get("id", 0)
        team_name = player.get("set_in_context", {}).get("team_name", "N/A")
        position = player.get("position", "N/A")
        
        html += f'''
        <div class="card" onclick="window.location='/de/player/{player_id}'">
            <div class="card-icon">👤</div>
            <h3>{player_name}</h3>
            <p style="color: var(--gray-600); font-size: 0.875rem;">
                Team: {team_name}<br>
                Position: {position}
            </p>
        </div>
        '''
    html += '</div>'
    
    if not filtered_players:
        html = '<div style="text-align: center; padding: 3rem; color: var(--gray-600);"><p>No players found</p></div>'
    
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
    
    # Use cached data - instant search across all datasets! (loads on-demand if needed)
    all_clubs = await get_cached_clubs()
    all_leagues = await get_cached_leagues()
    all_teams = await get_cached_teams()
    
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
    return {"detail": exc.detail}, exc.status_code


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

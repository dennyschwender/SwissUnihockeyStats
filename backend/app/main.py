"""
Main FastAPI application entry point
"""
from pathlib import Path
from datetime import datetime
import uuid
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

# Setup paths
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Create FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
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
    # Get clubs from API
    client = get_swissunihockey_client()
    clubs_data = client.get_clubs()
    
    return templates.TemplateResponse(
        "clubs.html",
        {
            "request": request,
            "locale": locale,
            "t": get_translations(locale),
            "clubs": clubs_data.get("entries", [])[:50]  # Limit to 50 for initial load
        }
    )


@app.get("/{locale}/clubs/search", response_class=HTMLResponse)
async def clubs_search(request: Request, locale: str, q: str = ""):
    """HTMX endpoint for club search"""
    client = get_swissunihockey_client()
    clubs_data = client.get_clubs()
    all_clubs = clubs_data.get("entries", [])
    
    # Filter clubs by search query
    if q:
        filtered_clubs = [
            club for club in all_clubs 
            if q.lower() in club.get("text", "").lower()
        ]
    else:
        filtered_clubs = all_clubs[:50]
    
    # Return partial HTML for htmx
    html = '<div class="cards-grid">'
    for club in filtered_clubs:
        html += f'''
        <div class="card" style="cursor: pointer;">
            <h3>{club.get("text", "")}</h3>
            <p>ID: {club.get("set_in_context", {}).get("club_id", "N/A")}</p>
        </div>
        '''
    html += '</div>'
    
    if not filtered_clubs:
        html = '<div style="text-align: center; padding: 3rem; color: var(--gray-600);"><p>No clubs found</p></div>'
    
    return HTMLResponse(content=html)


@app.get("/{locale}/leagues", response_class=HTMLResponse)
async def leagues_page(request: Request, locale: str):
    """Leagues listing page"""
    client = get_swissunihockey_client()
    leagues_data = client.get_leagues()
    
    return templates.TemplateResponse(
        "leagues.html",
        {
            "request": request,
            "locale": locale,
            "t": get_translations(locale),
            "leagues": leagues_data.get("entries", [])
        }
    )


@app.get("/{locale}/teams", response_class=HTMLResponse)
async def teams_page(request: Request, locale: str):
    """Teams listing page"""
    client = get_swissunihockey_client()
    teams_data = client.get_teams()
    
    return templates.TemplateResponse(
        "teams.html",
        {
            "request": request,
            "locale": locale,
            "t": get_translations(locale),
            "teams": teams_data.get("entries", [])[:50]
        }
    )


@app.get("/{locale}/teams/search", response_class=HTMLResponse)
async def teams_search(request: Request, locale: str, q: str = "", mode: str = "all"):
    """HTMX endpoint for team search"""
    client = get_swissunihockey_client()
    teams_data = client.get_teams()
    all_teams = teams_data.get("entries", [])
    
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
        html += f'''
        <div class="card">
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

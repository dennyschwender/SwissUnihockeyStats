"""
Main FastAPI application entry point
"""
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
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


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )

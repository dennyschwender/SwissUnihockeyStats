# SwissUnihockey FastAPI Backend

Modern backend API for SwissUnihockey statistics platform.

## Features

- ✅ FastAPI async framework
- ✅ Integration with SwissUnihockey API v2
- ✅ Intelligent caching layer
- ✅ RESTful API endpoints
- ✅ CORS support for frontend
- ✅ Database models (SQLAlchemy)
- ✅ Pydantic schemas for validation
- ✅ Redis caching (optional)

## Tech Stack

- **Framework**: FastAPI 0.109+
- **Python**: 3.11+
- **Database**: PostgreSQL (optional for persistence)
- **Cache**: Redis (optional)
- **ORM**: SQLAlchemy 2.0
- **Validation**: Pydantic V2

## Installation

```bash
# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1  # Windows
# source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env with your configuration

# Run development server
uvicorn app.main:app --reload --port 8000
```

## API Documentation

Once running, visit:
- **Interactive docs**: http://localhost:8000/docs
- **Alternative docs**: http://localhost:8000/redoc
- **OpenAPI schema**: http://localhost:8000/openapi.json

## Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Configuration settings
│   ├── database.py          # Database connection
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py    # Main API router
│   │       └── endpoints/
│   │           ├── clubs.py
│   │           ├── leagues.py
│   │           ├── teams.py
│   │           ├── games.py
│   │           ├── players.py
│   │           └── rankings.py
│   │
│   ├── models/              # SQLAlchemy models
│   │   ├── __init__.py
│   │   ├── club.py
│   │   ├── league.py
│   │   └── team.py
│   │
│   ├── schemas/             # Pydantic schemas
│   │   ├── __init__.py
│   │   ├── club.py
│   │   ├── league.py
│   │   └── team.py
│   │
│   ├── services/            # Business logic
│   │   ├── __init__.py
│   │   ├── swissunihockey.py  # Integration with API client
│   │   └── cache.py
│   │
│   └── utils/               # Helper utilities
│       ├── __init__.py
│       └── dependencies.py
│
├── tests/                   # Backend tests
├── .env.example
├── requirements.txt
├── pyproject.toml
└── README.md
```

## Environment Variables

```bash
# API Configuration
API_V1_PREFIX=/api/v1
PROJECT_NAME=SwissUnihockey API
VERSION=1.0.0

# CORS
BACKEND_CORS_ORIGINS=["http://localhost:3000", "http://localhost:3001"]

# SwissUnihockey API
SWISSUNIHOCKEY_API_URL=https://api-v2.swissunihockey.ch
SWISSUNIHOCKEY_LOCALE=de-CH
SWISSUNIHOCKEY_CACHE_ENABLED=true

# Redis (optional)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Database (optional for persistence)
DATABASE_URL=postgresql://user:pass@localhost/swissunihockey
```

## Development

```bash
# Run with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
pytest

# Format code
black app/
isort app/

# Lint
flake8 app/
mypy app/
```

## Deployment

### Docker

```bash
# Build image
docker build -t swissunihockey-backend .

# Run container
docker run -d -p 8000:8000 --env-file .env swissunihockey-backend
```

### Railway.app / Render

1. Connect GitHub repository
2. Set environment variables
3. Deploy automatically on push

## API Endpoints

### Clubs
- `GET /api/v1/clubs` - List all clubs
- `GET /api/v1/clubs/{club_id}` - Get club details

### Leagues
- `GET /api/v1/leagues` - List all leagues
- `GET /api/v1/leagues/{league_id}` - Get league details

### Teams
- `GET /api/v1/teams` - List teams (with filters)
- `GET /api/v1/teams/{team_id}` - Get team details

### Games
- `GET /api/v1/games` - List games (with filters)
- `GET /api/v1/games/{game_id}` - Get game details
- `GET /api/v1/games/{game_id}/events` - Get game events

### Players
- `GET /api/v1/players` - Search players
- `GET /api/v1/players/{player_id}` - Get player details

### Rankings
- `GET /api/v1/rankings` - Get league standings

---

**Status**: 🚧 Under Development  
**Version**: 1.0.0  
**License**: MIT

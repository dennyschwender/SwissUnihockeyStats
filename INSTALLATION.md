# Installation Guide

This guide will help you set up the SwissUnihockey project, including both the Python API client and the modern web application (FastAPI backend + Next.js frontend).

## Prerequisites

### Required

- **Python 3.11+** - [Download](https://www.python.org/downloads/)
- **Git** - [Download](https://git-scm.com/)

### Optional (for full stack web app)

- **Node.js 18.0.0+** - [Download](https://nodejs.org/) (LTS version recommended)
- **npm 9.0.0+** - Included with Node.js
- **Docker & Docker Compose** - [Download](https://www.docker.com/products/docker-desktop) (optional)

## Quick Start Options

### Option 1: Python API Client Only

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/swissunihockey.git
cd swissunihockey

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Windows CMD:
.venv\Scripts\activate.bat
# Linux/macOS:
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Test the API
python test_api.py

# Preload cache (recommended)
python scripts/preload_cache.py
```

### Option 2: FastAPI Backend + Next.js Frontend

```bash
# Clone the repository (if not already done)
git clone https://github.com/YOUR_USERNAME/swissunihockey.git
cd swissunihockey

# ===== BACKEND SETUP =====

# Create and activate virtual environment (see Option 1 above)
python -m venv .venv
.venv\Scripts\Activate.ps1  # Windows PowerShell

# Install backend dependencies
pip install -r backend/requirements.txt

# Configure backend environment
cd backend
cp .env.example .env
# Edit .env if needed (default settings work for development)

# Start backend server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# ===== FRONTEND SETUP (in new terminal) =====

# Navigate to frontend directory
cd web

# Install Node.js dependencies
npm install

# Configure frontend environment
cp .env.example .env
# Edit .env if needed (default points to http://localhost:8000)

# Start frontend development server
npm run dev

# Access the application
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# API Docs: http://localhost:8000/docs
```

### Option 3: Docker (Full Stack)

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/swissunihockey.git
cd swissunihockey

# Build and start all services
docker-compose build
docker-compose up -d

# Preload cache (optional but recommended)
docker-compose run --rm preload-cache

# Access services
# Frontend: http://localhost:3000
# Backend: http://localhost:8000
# API Docs: http://localhost:8000/docs

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

## Detailed Setup

### 1. Python Environment Setup

#### Create Virtual Environment

**Why?** Virtual environments isolate project dependencies from system Python.

```bash
# Create virtual environment
python -m venv .venv

# Activate (choose your platform)
# Windows PowerShell:
.venv\Scripts\Activate.ps1

# Windows CMD:
.venv\Scripts\activate.bat

# Linux/macOS:
source .venv/bin/activate

# Verify activation (should show .venv path)
which python  # Linux/macOS
where python  # Windows
```

#### Install Python Dependencies

```bash
# Install API client dependencies
pip install -r requirements.txt

# Install backend dependencies
pip install -r backend/requirements.txt

# Verify installation
pip list
```

### 2. Backend Setup

#### Install FastAPI and Dependencies

```bash
cd backend

# Dependencies include:
# - FastAPI 0.109.2
# - Uvicorn 0.27.1 (ASGI server)
# - Pydantic V2 (data validation)
# - SQLAlchemy 2.0.25 (database ORM)
# - Redis 5.0.1 (caching)
# - HTTPx (async HTTP client)
# And more...

pip install -r requirements.txt
```

#### Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env file
# Default values work for development:
# - CORS origins: http://localhost:3000
# - API settings from ../config.ini
```

#### Start Backend Server

```bash
# Development mode (auto-reload on code changes)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Production mode
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

**Verify backend:**

- Health check: <http://localhost:8000/>
- API docs: <http://localhost:8000/docs>
- OpenAPI spec: <http://localhost:8000/openapi.json>

### 3. Frontend Setup

#### Install Node.js

**Download:** <https://nodejs.org/>

- Choose LTS (Long Term Support) version
- Includes npm package manager
- Minimum: Node.js 18.0.0, npm 9.0.0

**Verify installation:**

```bash
node --version  # Should show v18.0.0 or higher
npm --version   # Should show v9.0.0 or higher
```

#### Install Frontend Dependencies

```bash
cd web

# Install all dependencies
npm install

# This installs:
# - Next.js 14.1.0
# - React 18.2.0
# - TypeScript 5.3.3
# - Tailwind CSS 3.4.1
# - next-intl 3.6.0 (i18n)
# - TanStack Query 5.17.19 (data fetching)
# - Zustand 4.5.0 (state management)
# - Axios 1.6.5 (HTTP client)
# - And more...
```

#### Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env file (optional)
# NEXT_PUBLIC_API_URL=http://localhost:8000
# NEXT_PUBLIC_DEFAULT_LOCALE=de
```

#### Start Frontend Development Server

```bash
# Development mode (hot reload)
npm run dev

# Production build
npm run build
npm start
```

**Access frontend:**

- Application: <http://localhost:3000>
- Auto redirects to: <http://localhost:3000/de> (German default)

## Troubleshooting

### Python Issues

**Problem:** Python command not found

```bash
# Windows: Add Python to PATH during installation
# Or use full path:
C:\Python311\python.exe -m venv .venv
```

**Problem:** pip install fails with SSL errors

```bash
# Try with trusted host
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
```

**Problem:** Virtual environment activation fails (Windows)

```powershell
# Enable script execution
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Backend Issues

**Problem:** Port 8000 already in use

```bash
# Find and kill process on Windows
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# Or use different port
uvicorn app.main:app --reload --port 8001
```

**Problem:** Import errors when running backend

```bash
# Ensure you're in the backend directory
cd backend
uvicorn app.main:app --reload

# Or run from root with module path
python -m uvicorn backend.app.main:app --reload
```

### Frontend Issues

**Problem:** Node.js not found

```bash
# Download and install from https://nodejs.org/
# Verify installation:
node --version
npm --version
```

**Problem:** npm install fails

```bash
# Clear npm cache
npm cache clean --force

# Delete node_modules and package-lock.json
rm -rf node_modules package-lock.json

# Reinstall
npm install
```

**Problem:** Port 3000 already in use

```bash
# Next.js will automatically try 3001, 3002, etc.
# Or specify port:
npm run dev -- --port 3001
```

**Problem:** Module not found errors

```bash
# Ensure all dependencies are installed
npm install

# Check for missing peer dependencies
npm install --legacy-peer-deps
```

### Docker Issues

**Problem:** Docker daemon not running

```bash
# Start Docker Desktop
# Or on Linux:
sudo systemctl start docker
```

**Problem:** Port conflicts

```bash
# Stop containers using the same ports
docker ps
docker stop <container_id>

# Or change ports in docker-compose.yml
```

**Problem:** Build fails

```bash
# Rebuild without cache
docker-compose build --no-cache

# Check logs
docker-compose logs <service_name>
```

## Verification Checklist

After installation, verify everything works:

### Python API Client

- [ ] Virtual environment activated
- [ ] Dependencies installed: `pip list | grep swissunihockey`
- [ ] API connection works: `python test_api.py`
- [ ] Cache directory created: `ls data/cache/`

### Backend

- [ ] Dependencies installed: `pip list | grep fastapi`
- [ ] Server starts: `uvicorn app.main:app --reload`
- [ ] Health check works: <http://localhost:8000/>
- [ ] API docs accessible: <http://localhost:8000/docs>
- [ ] Sample endpoint works: <http://localhost:8000/api/v1/clubs/>

### Frontend

- [ ] Node.js installed: `node --version`
- [ ] Dependencies installed: `ls web/node_modules/`
- [ ] Dev server starts: `npm run dev`
- [ ] Homepage loads: <http://localhost:3000/>
- [ ] Language switching works: <http://localhost:3000/en>, /fr, /it
- [ ] Backend connection works (check browser console)

## Next Steps

### For Python API Client

- Explore examples: `python API_USAGE_EXAMPLES.py`
- Read [GETTING_STARTED.md](docs/GETTING_STARTED.md)
- Build your first feature using [FEATURE_IDEAS.md](docs/FEATURE_IDEAS.md)

### For Full Stack Application

- Follow [QUICK_START.md](docs/QUICK_START.md) for Week 1-4 MVP
- Read [MODERN_WEB_APP_ROADMAP.md](docs/MODERN_WEB_APP_ROADMAP.md) for complete roadmap
- Explore [COMPONENT_LIBRARY.md](docs/COMPONENT_LIBRARY.md) for UI components

## Support

- **Issues:** <https://github.com/YOUR_USERNAME/swissunihockey/issues>
- **Discussions:** <https://github.com/YOUR_USERNAME/swissunihockey/discussions>
- **Documentation:** [docs/](docs/)

## Development Workflow

```bash
# 1. Start backend
cd backend
uvicorn app.main:app --reload

# 2. Start frontend (new terminal)
cd web
npm run dev

# 3. Make changes
# - Backend auto-reloads on save
# - Frontend hot-reloads on save

# 4. Test
cd .. # back to root
pytest  # Python tests
cd web
npm test  # Frontend tests

# 5. Format code
black .  # Python
cd web
npm run format  # TypeScript/React

# 6. Commit changes
git add .
git commit -m "feat: description"
git push
```

Happy coding! 🏒

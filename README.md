# SwissUnihockey Statistics Project 🏒

[![Python Tests](https://github.com/YOUR_USERNAME/swissunihockey/workflows/Python%20Tests/badge.svg)](https://github.com/YOUR_USERNAME/swissunihockey/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A complete Python API client for Swiss Unihockey (floorball) statistics **+ comprehensive guides to build a modern, mobile-first web application** that surpasses existing platforms.

## 🎯 Two Ways to Use This Project

### 1️⃣ Python API Client (Ready Now)
Use the complete Python client to fetch data from Swiss Unihockey API for your own projects.

### 2️⃣ Build Modern Web Platform (Full Stack Guide)
Follow our comprehensive roadmap to build a **React + FastAPI application** with:
- 📱 Mobile-first PWA
- 🔴 Real-time live scores  
- 🌙 Dark mode
- 📴 Offline support
- 🔔 Push notifications
- 📊 Advanced analytics

**👉 [Start Building the Modern Platform →](docs/PROJECT_STATUS.md)**

## 🚀 Quick Start

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/swissunihockey.git
cd swissunihockey

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Test the API connection
python test_api.py

# Fetch sample data
python scripts/example_fetch_data.py
```

## � Docker Quick Start

**Prefer Docker?** Run everything in containers without installing Python locally:

```bash
# Build and start
docker-compose build
docker-compose up -d

# Preload cache (recommended)
docker-compose run --rm preload-cache

# Open Python shell
docker-compose exec swissunihockey python

# Or use Makefile shortcuts
make build
make up
make preload
```

**📚 Complete Docker guide:** [DOCKER.md](docs/DOCKER.md)

## �📊 What You Can Build

- **Live league standings** for all divisions
- **Player statistics** and top scorer leaderboards
- **Match center** with schedules and results
- **Team profiles** with historical data
- **Advanced analytics** and predictions

See [FEATURE_IDEAS.md](docs/FEATURE_IDEAS.md) for 20+ concrete feature ideas!

## 📖 API Documentation
- Base URL: `https://api-v2.swissunihockey.ch`
- Documentation: https://api-v2.swissunihockey.ch/api/doc/table/overview
- Format: JSON responses
- Authentication: Public endpoints don't require authentication

## Available Data

### Public Endpoints
- `/api/clubs` - All Swiss Unihockey clubs
- `/api/leagues` - League/game class information
- `/api/seasons` - Historical seasons (2017/18+)
- `/api/teams` - Team rosters and details
- `/api/games` - Match schedules and results
- `/api/game_events` - Detailed game events (goals, penalties)
- `/api/players` - Player profiles
- `/api/rankings` - League standings
- `/api/topscorers` - Top scorer statistics
- `/api/groups` - Group/division information
- `/api/cups` - Cup competitions
- `/api/calendars` - Match calendars
- `/api/national_players` - National team players

### Localization
Supports: `en`, `de-CH`, `fr-CH`, `it-CH` (currently defaults to de-CH)

## Project Structure

```
swissunihockey/
├── README.md
├── LICENSE
├── requirements.txt
├── config.ini
├── api/                   # API client library
│   ├── __init__.py
│   ├── client.py         # Main API client with caching
│   ├── cache.py          # Cache manager
│   └── endpoints.py      # Convenience functions
├── data/                 # Data storage (gitignored)
│   ├── cache/           # API response cache
│   ├── raw/             # Raw API responses (manual saves)
│   └── processed/       # Cleaned data
├── scripts/             # Example scripts
│   ├── example_fetch_data.py
│   ├── preload_cache.py      # Preload commonly used data
│   └── test_caching.py       # Test caching performance
├── tests/               # Unit tests
│   └── test_client.py
├── .github/             # GitHub workflows & templates
└── docs/                # Documentation
```

## 💻 Usage Examples

### Basic Usage (with automatic caching)

```python
# Using the API client with automatic caching (default)
from api import SwissUnihockeyClient

with SwissUnihockeyClient() as client:
    # First call: fetches from API and caches (30-day cache)
    clubs = client.get_clubs()  # ~300ms
    
    # Second call: returns from cache (no API call!)
    clubs = client.get_clubs()  # ~2ms ⚡ 150x faster!
    
    # Get NLB Men standings (1-hour cache)
    standings = client.get_rankings(
        league=2,        # NLB
        game_class=11,   # Men
        season=2025
    )
    
    # Force refresh (bypass cache)
    fresh_data = client.get_clubs(force_refresh=True)
```

### Cache Management

```python
# Preload cache for faster subsequent requests
from api import SwissUnihockeyClient

client = SwissUnihockeyClient()

# Preload commonly used data
client.get_clubs()
client.get_leagues()
client.get_seasons()

# Check cache statistics
stats = client.cache.get_stats()
print(f"Cached {stats['total_entries']} entries, {stats['total_size_mb']} MB")

# Clear specific category
client.cache.clear("rankings")

# Clear all cache
client.cache.clear()
```

### Disable Caching (for real-time applications)

```python
# Disable caching entirely
client = SwissUnihockeyClient(use_cache=False)
live_data = client.get_game_events(game_id=12345)
```

**💡 Caching Details:**
- Static data (clubs, seasons): 30-day cache
- Semi-static (teams, players): 7-day cache
- Dynamic data (rankings, top scorers): 1-hour cache
- Real-time (live games): 5-minute cache
- Stored in: `data/cache/` directory

See [CACHING_STRATEGY.md](docs/CACHING_STRATEGY.md) for full documentation.

See [API_USAGE_EXAMPLES.py](API_USAGE_EXAMPLES.py) for more code samples and [GETTING_STARTED.md](docs/GETTING_STARTED.md) for detailed tutorials.

## 🧪 Testing

```bash
# Install test dependencies
pip install pytest pytest-cov black flake8

# Run tests
pytest

# Run tests with coverage
pytest --cov=api --cov-report=html

# Check code formatting
black --check .

## 📝 Documentation

### Python API Client
- **[GETTING_STARTED.md](docs/GETTING_STARTED.md)** - Quick start guide and tutorials
- **[API_USAGE_EXAMPLES.py](API_USAGE_EXAMPLES.py)** - Code snippets and patterns
- **[CACHING_STRATEGY.md](docs/CACHING_STRATEGY.md)** - 💾 How to avoid unnecessary API calls (NEW!)
- **[FEATURE_IDEAS.md](docs/FEATURE_IDEAS.md)** - 20+ feature ideas to build

### Modern Web Application (Full Stack)
- **[PROJECT_STATUS.md](docs/PROJECT_STATUS.md)** - 📋 **START HERE** - Complete overview & status
- **[MODERN_WEB_APP_ROADMAP.md](docs/MODERN_WEB_APP_ROADMAP.md)** - 🏗️ Architecture & 12-week plan
- **[TECH_STACK.md](docs/TECH_STACK.md)** - 🛠️ Technology decisions & deployment
- **[QUICK_START.md](docs/QUICK_START.md)** - 🚀 4-week MVP development guide
- **[COMPONENT_LIBRARY.md](docs/COMPONENT_LIBRARY.md)** - 🎨 Copy-paste React components

### Docker & Deployment
- **[DOCKER_COMPLETE.md](docs/DOCKER_COMPLETE.md)** - 🐳 Complete Docker setup summary
- **[DOCKER.md](docs/DOCKER.md)** - Full Docker deployment guide
- **[DOCKER_ARCHITECTURE.md](docs/DOCKER_ARCHITECTURE.md)** - Architecture diagrams

### Other
- **[CONTRIBUTING.md](docs/CONTRIBUTING.md)** - Contribution guidelines
- **[CHANGELOG.md](docs/CHANGELOG.md)** - Version history
- **[SECURITY.md](docs/SECURITY.md)** - Security policy

Contributions are welcome! Please read [CONTRIBUTING.md](docs/CONTRIBUTING.md) for details on how to contribute to this project.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 Full Documentation

All comprehensive guides are in the [docs/](docs/) folder:

- **[Getting Started Guide](docs/GETTING_STARTED.md)** - Tutorials and quick start
- **[Project Status & Roadmap](docs/PROJECT_STATUS.md)** - Current status and next steps
- **[Docker Guide](docs/DOCKER_COMPLETE.md)** - Complete containerization docs
- **[Contributing](docs/CONTRIBUTING.md)** - How to contribute
- **[Changelog](docs/CHANGELOG.md)** - Version history

**📚 Browse all documentation:** [docs/](docs/)

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Data provided by [Swiss Unihockey](https://swissunihockey.ch) API
- Built with Python and love for floorball 🏒

## ⚠️ Disclaimer

This is an independent project and is not officially affiliated with Swiss Unihockey. Please be respectful of the API and follow their terms of service.

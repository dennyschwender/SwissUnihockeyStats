# SwissUnihockey - Quick Start Guide

## Production-Ready Python Full-Stack Web Application

Modern web application for Swiss floorball statistics with universal search and favorites system.

## 🚀 Quick Start

### Prerequisites

- Python 3.13+
- Virtual environment (`.venv/` in workspace root)

### Start the Server

```powershell
# From workspace root
cd swissunihockey/backend
..\..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Or use the simplified command:

```powershell
cd swissunihockey/backend
uvicorn app.main:app --reload
```

### Access the Application

- **Homepage**: <http://localhost:8000/de>
- **English**: <http://localhost:8000/en>
- **French**: <http://localhost:8000/fr>  
- **Italian**: <http://localhost:8000/it>
- **API Docs**: <http://localhost:8000/docs>
- **Favorites**: <http://localhost:8000/de/favorites>

## ✨ Key Features

### Week 4 (NEW!)

- **Universal Search**: Big search bar on home page - search across all clubs, leagues, and teams simultaneously
- **Favorites System**: Star your favorite items, persistent across sessions using localStorage
- **Toast Notifications**: Get feedback when adding/removing favorites

### Weeks 1-3

- **Multi-language**: German, English, French, Italian support
- **6 Core Pages**: Home, Clubs, Leagues, Teams, Games, Rankings
- **Dynamic Interactions**: htmx for instant search, Alpine.js for state management
- **Loading Skeletons**: Professional loading states
- **Custom Error Pages**: User-friendly 404/500 pages
- **SEO Optimized**: Open Graph, Twitter Cards, hreflang tags

## 📊 Architecture

- **Backend**: FastAPI 0.109.2 with Jinja2 templates
- **Frontend**: Server-side rendering + htmx (35 KB) + Alpine.js
- **API Client**: SwissUnihockey API v2 integration
- **Caching**: File-based caching for API responses
- **Testing**: 113 tests (100% passing)

## 🎯 Try the Features

### 1. Universal Search

1. Visit <http://localhost:8000/de>
2. Type in the search bar (e.g., "Zürich")
3. See live results across clubs, leagues, and teams
4. Click any result to navigate

### 2. Favorites System

1. Browse to any page (clubs, leagues, teams)
2. Click the ⭐ star icon on any card
3. See toast notification confirming addition
4. Visit <http://localhost:8000/de/favorites> to see all saved items
5. Click star again to remove from favorites

### 3. htmx Dynamic Search

1. Go to <http://localhost:8000/de/clubs>
2. Use the search box
3. Results update instantly without page reload
4. Filter teams by mode (Men/Women/Mixed)

## 📁 Project Structure

```
swissunihockey/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + routes
│   │   ├── config.py            # Settings
│   │   ├── api/v1/              # JSON API endpoints
│   │   ├── lib/i18n.py          # Multi-language system
│   │   └── services/            # API client integration
│   ├── templates/               # Jinja2 HTML templates
│   │   ├── base.html           # Base layout
│   │   ├── home.html           # Homepage with search
│   │   ├── favorites.html      # Favorites management
│   │   ├── clubs.html          # Clubs page
│   │   ├── leagues.html        # Leagues page
│   │   ├── teams.html          # Teams page
│   │   └── ...
│   ├── static/
│   │   ├── css/main.css        # Swiss theme styles
│   │   └── js/favorites.js     # Favorites management
│   ├── i18n/                   # Translation JSON files
│   └── requirements.txt        # Python dependencies
├── tests/                      # Test suite (113 tests)
└── api/                        # SwissUnihockey API client
```

## 🧪 Testing

```powershell
# Run all tests
cd swissunihockey
..\.venv\Scripts\python.exe -m pytest tests/ -v

# Run with coverage
pytest tests/ --cov=backend --cov-report=term-missing

# Results: 113 tests passing, 48% backend coverage
```

## 📝 Documentation

- [MODERN_IMPLEMENTATION.md](MODERN_IMPLEMENTATION.md) - Complete implementation status
- [PYTHON_FULL_STACK.md](PYTHON_FULL_STACK.md) - Architecture deep dive
- [PERFORMANCE_COMPARISON.md](PERFORMANCE_COMPARISON.md) - Next.js vs htmx analysis

## 🎨 Design

**Swiss Theme**: Red & white color scheme inspired by Swiss flag

- Primary color: #FF0000 (Swiss Red)
- Background: Gradient from white to light red
- Typography: Inter font stack
- Icons: Unicode emojis (no external dependencies)

## 🔧 Development Tips

### Favorite Buttons

Favorite buttons use Alpine.js reactive state:

```html
<button 
    @click.stop="toggleFavorite('clubs', 123, 'Club Name', {})"
    :class="isFavorite('clubs', 123) ? 'active' : 'inactive'"
    class="favorite-btn"
>⭐</button>
```

### Universal Search

Search endpoint returns categorized HTML:

```html
<!-- htmx triggers search -->
<input 
    hx-get="/de/search"
    hx-trigger="keyup changed delay:300ms"
    hx-target="#universal-search-results"
>
```

### LocalStorage Structure

```json
{
  "swissunihockey_favorites": {
    "clubs": [{"id": 123, "name": "Club Name", "addedAt": "2026-02-17T..."}],
    "leagues": [...],
    "teams": [...]
  }
}
```

## 🚢 Deployment

Ready for production deployment:

- No build step required (server-side rendering)
- Single Python process
- Environment variables via .env
- Docker support (optional)

## 📈 Performance

- **Bundle size**: 35 KB (htmx + Alpine.js)
- **Initial load**: ~100ms (server-side rendering)
- **Search response**: <100ms (cached API data)
- **90% smaller** than Next.js alternative (350 KB)

## 🎉 Project Status

**MVP Complete**: 100% of core features implemented

- Week 1: Infrastructure + Backend ✅
- Week 2: Core pages ✅
- Week 3: Polish + SEO ✅
- Week 4: Search + Favorites ✅

**Production Ready**: Fully functional, tested, and documented

---

**Version**: 1.0.0  
**Last Updated**: February 17, 2026  
**License**: MIT

# 💾 Caching Strategy - Avoid Unnecessary API Calls

## 🎯 Goal
Minimize API requests to SwissUnihockey API by implementing intelligent local caching with appropriate TTL (Time To Live) for different data types.

---

## 📊 Data Classification by Update Frequency

### 1. Static Data (Cache: 30 days)
Data that rarely changes:
- **Clubs** - Club information changes infrequently
- **Venues** - Hall/venue information is stable
- **Seasons** - Historical seasons never change

**Strategy**: Long-term file cache (30 days)

### 2. Semi-Static Data (Cache: 7 days)
Data that changes occasionally:
- **Teams** - Team rosters change between seasons
- **Players** - Player profiles updated occasionally
- **Leagues** - League structure mostly stable

**Strategy**: Medium-term file cache (7 days)

### 3. Dynamic Data (Cache: 1 hour)
Data that updates daily:
- **Rankings/Standings** - Updated after each game
- **Top Scorers** - Changes with every match
- **Game Schedules** - New games added regularly

**Strategy**: Short-term file cache (1 hour)

### 4. Real-Time Data (Cache: 5 minutes or no cache)
Data that changes during games:
- **Live Game Events** - Goals, penalties in real-time
- **Live Scores** - Updates every few minutes

**Strategy**: Very short cache or no cache

---

## 🏗️ Implementation Architecture

### Two-Tier Caching System

```
┌─────────────────────────────────────────┐
│         Application Request             │
└────────────────┬────────────────────────┘
                 │
                 ▼
         ┌───────────────┐
         │ Memory Cache  │  (Fast, per-session)
         │  (Optional)   │
         └───────┬───────┘
                 │ Miss
                 ▼
         ┌───────────────┐
         │  File Cache   │  (Persistent, disk-based)
         │ data/cache/   │
         └───────┬───────┘
                 │ Miss/Expired
                 ▼
         ┌───────────────┐
         │   API Call    │  (Network request)
         │   + Save      │
         └───────────────┘
```

---

## 📁 Directory Structure

```
swissunihockey/
├── data/
│   ├── cache/              # Cached API responses
│   │   ├── clubs/
│   │   │   └── clubs_all.json
│   │   ├── leagues/
│   │   │   └── leagues_all.json
│   │   ├── teams/
│   │   │   ├── team_123.json
│   │   │   └── team_456.json
│   │   ├── rankings/
│   │   │   └── ranking_league2_season2025.json
│   │   └── metadata.json   # Cache metadata (timestamps, TTL)
│   ├── raw/               # Raw API dumps (manual saves)
│   └── processed/         # Processed/cleaned data
└── api/
    ├── client.py          # Main client (with caching)
    └── cache.py           # Cache manager (NEW)
```

---

## 💻 Implementation Code

### 1. Cache Manager (api/cache.py)

```python
"""Cache management for SwissUnihockey API."""

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class CacheManager:
    """Manage file-based caching for API responses."""

    # Cache TTL in seconds for different data types
    TTL_CONFIG = {
        "static": 30 * 24 * 60 * 60,      # 30 days (clubs, venues, seasons)
        "semi_static": 7 * 24 * 60 * 60,  # 7 days (teams, players, leagues)
        "dynamic": 60 * 60,                # 1 hour (rankings, topscorers)
        "realtime": 5 * 60,                # 5 minutes (live games)
    }

    def __init__(self, cache_dir: str = "data/cache"):
        """
        Initialize cache manager.

        Args:
            cache_dir: Directory for cache files
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.cache_dir / "metadata.json"
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> Dict[str, Any]:
        """Load cache metadata."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load cache metadata: {e}")
        return {}

    def _save_metadata(self):
        """Save cache metadata."""
        try:
            with open(self.metadata_file, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save cache metadata: {e}")

    def _get_cache_key(self, endpoint: str, params: Optional[Dict] = None) -> str:
        """
        Generate unique cache key for endpoint + parameters.

        Args:
            endpoint: API endpoint
            params: Query parameters

        Returns:
            MD5 hash of endpoint + sorted params
        """
        # Sort params for consistent hashing
        param_str = ""
        if params:
            sorted_params = sorted(params.items())
            param_str = str(sorted_params)
        
        key_str = f"{endpoint}:{param_str}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def _get_cache_path(self, cache_key: str, category: str = "general") -> Path:
        """Get file path for cache key."""
        category_dir = self.cache_dir / category
        category_dir.mkdir(parents=True, exist_ok=True)
        return category_dir / f"{cache_key}.json"

    def _determine_ttl(self, endpoint: str) -> int:
        """
        Determine TTL based on endpoint type.

        Args:
            endpoint: API endpoint

        Returns:
            TTL in seconds
        """
        # Static data
        if endpoint in ["/api/clubs", "/api/seasons", "/api/venues"]:
            return self.TTL_CONFIG["static"]
        
        # Semi-static data
        if endpoint in ["/api/teams", "/api/players", "/api/leagues"]:
            return self.TTL_CONFIG["semi_static"]
        
        # Real-time data
        if "/api/game_events" in endpoint or "/live" in endpoint:
            return self.TTL_CONFIG["realtime"]
        
        # Dynamic data (default)
        return self.TTL_CONFIG["dynamic"]

    def get(
        self,
        endpoint: str,
        params: Optional[Dict] = None,
        category: str = "general"
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached data if available and not expired.

        Args:
            endpoint: API endpoint
            params: Query parameters
            category: Cache category (clubs, teams, rankings, etc.)

        Returns:
            Cached data or None if not found/expired
        """
        cache_key = self._get_cache_key(endpoint, params)
        cache_path = self._get_cache_path(cache_key, category)

        if not cache_path.exists():
            logger.debug(f"Cache miss: {endpoint}")
            return None

        # Check if cache is expired
        metadata = self.metadata.get(cache_key, {})
        cached_at = metadata.get("cached_at")
        ttl = metadata.get("ttl", self._determine_ttl(endpoint))

        if cached_at:
            cached_datetime = datetime.fromisoformat(cached_at)
            expires_at = cached_datetime + timedelta(seconds=ttl)
            
            if datetime.now() > expires_at:
                logger.debug(f"Cache expired: {endpoint}")
                return None

        # Load cached data
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.debug(f"Cache hit: {endpoint}")
                return data
        except Exception as e:
            logger.error(f"Failed to read cache: {e}")
            return None

    def set(
        self,
        endpoint: str,
        params: Optional[Dict],
        data: Dict[str, Any],
        category: str = "general",
        ttl: Optional[int] = None
    ):
        """
        Save data to cache.

        Args:
            endpoint: API endpoint
            params: Query parameters
            data: Data to cache
            category: Cache category
            ttl: Custom TTL in seconds (optional)
        """
        cache_key = self._get_cache_key(endpoint, params)
        cache_path = self._get_cache_path(cache_key, category)

        # Save data
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            # Update metadata
            self.metadata[cache_key] = {
                "endpoint": endpoint,
                "params": params,
                "category": category,
                "cached_at": datetime.now().isoformat(),
                "ttl": ttl or self._determine_ttl(endpoint),
            }
            self._save_metadata()

            logger.debug(f"Cached: {endpoint}")
        except Exception as e:
            logger.error(f"Failed to write cache: {e}")

    def clear(self, category: Optional[str] = None):
        """
        Clear cache.

        Args:
            category: Specific category to clear, or None for all
        """
        if category:
            category_dir = self.cache_dir / category
            if category_dir.exists():
                for file in category_dir.glob("*.json"):
                    file.unlink()
                logger.info(f"Cleared cache category: {category}")
        else:
            for file in self.cache_dir.glob("**/*.json"):
                if file.name != "metadata.json":
                    file.unlink()
            self.metadata = {}
            self._save_metadata()
            logger.info("Cleared all cache")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_files = sum(1 for _ in self.cache_dir.glob("**/*.json"))
        total_size = sum(f.stat().st_size for f in self.cache_dir.glob("**/*.json"))
        
        return {
            "total_entries": len(self.metadata),
            "total_files": total_files,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "categories": list(set(m["category"] for m in self.metadata.values())),
        }
```

### 2. Updated API Client (api/client.py)

Add caching support to existing client:

```python
# Add to imports
from api.cache import CacheManager

# Update __init__ method
def __init__(
    self,
    base_url: str = "https://api-v2.swissunihockey.ch",
    locale: str = "de-CH",
    timeout: int = 30,
    retry_attempts: int = 3,
    retry_delay: int = 1,
    use_cache: bool = True,  # NEW
    cache_dir: str = "data/cache"  # NEW
):
    """Initialize the API client."""
    self.base_url = base_url.rstrip("/")
    self.locale = locale
    self.timeout = timeout
    self.retry_attempts = retry_attempts
    self.retry_delay = retry_delay
    self.session = requests.Session()
    
    # Initialize cache
    self.use_cache = use_cache
    self.cache = CacheManager(cache_dir) if use_cache else None

# Update _make_request method
def _make_request(
    self,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    category: str = "general",
    force_refresh: bool = False  # NEW
) -> Dict[str, Any]:
    """
    Make a request to the API with caching support.

    Args:
        endpoint: API endpoint
        params: Query parameters
        category: Cache category
        force_refresh: Skip cache and fetch fresh data

    Returns:
        JSON response as dictionary
    """
    # Add locale to parameters
    if params is None:
        params = {}
    params["locale"] = self.locale

    # Try cache first (if enabled and not forcing refresh)
    if self.use_cache and not force_refresh:
        cached_data = self.cache.get(endpoint, params, category)
        if cached_data is not None:
            return cached_data

    # Fetch from API
    url = f"{self.base_url}{endpoint}"
    last_exception = None
    
    for attempt in range(self.retry_attempts):
        try:
            logger.debug(f"Request attempt {attempt + 1}/{self.retry_attempts}: {url}")
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            logger.debug(f"Successfully fetched data from {endpoint}")
            
            # Cache the response
            if self.use_cache:
                self.cache.set(endpoint, params, data, category)
            
            return data
            
        except requests.exceptions.RequestException as e:
            last_exception = e
            logger.warning(
                f"Request failed (attempt {attempt + 1}/{self.retry_attempts}): {str(e)}"
            )
            
            if attempt < self.retry_attempts - 1:
                time.sleep(self.retry_delay * (2 ** attempt))
    
    raise last_exception
```

### 3. Update Endpoint Methods

Add category parameter to endpoint methods:

```python
def get_clubs(self, force_refresh: bool = False) -> Dict[str, Any]:
    """Fetch all clubs."""
    return self._make_request("/api/clubs", category="clubs", force_refresh=force_refresh)

def get_rankings(
    self,
    league: int,
    game_class: int,
    season: int,
    mode: str = "championship",
    force_refresh: bool = False
) -> Dict[str, Any]:
    """Fetch league rankings/standings."""
    params = {
        "league": league,
        "game_class": game_class,
        "season": season,
        "mode": mode,
    }
    return self._make_request("/api/rankings", params, category="rankings", force_refresh=force_refresh)
```

---

## 🚀 Usage Examples

### Basic Usage (Automatic Caching)

```python
from api import SwissUnihockeyClient

# Initialize with caching enabled (default)
client = SwissUnihockeyClient()

# First call: fetches from API and caches
clubs = client.get_clubs()  # API call + cache save

# Second call: returns cached data (no API call!)
clubs = client.get_clubs()  # Cache hit (instant)

# Force refresh
clubs = client.get_clubs(force_refresh=True)  # API call
```

### Disable Caching

```python
# Disable caching for real-time applications
client = SwissUnihockeyClient(use_cache=False)
```

### Cache Management

```python
# Get cache statistics
stats = client.cache.get_stats()
print(f"Cache entries: {stats['total_entries']}")
print(f"Cache size: {stats['total_size_mb']} MB")

# Clear specific category
client.cache.clear("rankings")  # Clear only rankings

# Clear all cache
client.cache.clear()  # Clear everything
```

### Advanced: Preload Cache

```python
"""Preload cache with frequently used data."""

def preload_cache():
    """Download and cache commonly used data."""
    client = SwissUnihockeyClient()
    
    print("Preloading cache...")
    
    # Static data (30-day cache)
    print("  • Clubs...", end="")
    client.get_clubs()
    print(" ✓")
    
    print("  • Leagues...", end="")
    client.get_leagues()
    print(" ✓")
    
    print("  • Seasons...", end="")
    client.get_seasons()
    print(" ✓")
    
    # Dynamic data for current season
    current_season = 2025
    for league in [1, 2, 3]:  # NLA, NLB, 1. Liga
        print(f"  • Rankings league {league}...", end="")
        try:
            client.get_rankings(league=league, game_class=11, season=current_season)
            print(" ✓")
        except:
            print(" ✗")
    
    print(f"\nCache preloaded!")
    print(f"Stats: {client.cache.get_stats()}")

if __name__ == "__main__":
    preload_cache()
```

---

## 📊 Performance Comparison

### Without Caching
```
First API call:  ~300ms
Second API call: ~300ms
Third API call:  ~300ms
Total: 900ms
```

### With Caching
```
First API call:  ~300ms (cache miss)
Second call:     ~2ms   (cache hit!)
Third call:      ~2ms   (cache hit!)
Total: 304ms (3x faster!)
```

### For 100 Requests
```
Without cache: 30 seconds
With cache:    0.5 seconds (60x faster!)
```

---

## 🎯 Best Practices

### 1. Use Categories
Organize cache by data type for easier management:
```python
client.get_clubs(category="clubs")
client.get_rankings(category="rankings")
```

### 2. Periodic Cache Refresh
Set up scheduled jobs to refresh cache:
```python
# Refresh dynamic data every hour
schedule.every(1).hour.do(lambda: client.get_rankings(force_refresh=True))
```

### 3. Cache Warming
Preload cache on application startup:
```python
def on_startup():
    client = SwissUnihockeyClient()
    # Warm cache with common queries
    client.get_clubs()
    client.get_leagues()
```

### 4. Monitor Cache Size
```python
# Check cache size regularly
stats = client.cache.get_stats()
if stats['total_size_mb'] > 100:  # If cache > 100 MB
    client.cache.clear("rankings")  # Clear dynamic data
```

---

## 🔧 Configuration

### Environment Variables

```bash
# .env
SWISSUNIHOCKEY_CACHE_ENABLED=true
SWISSUNIHOCKEY_CACHE_DIR=data/cache
SWISSUNIHOCKEY_CACHE_TTL_STATIC=2592000  # 30 days
SWISSUNIHOCKEY_CACHE_TTL_DYNAMIC=3600    # 1 hour
```

### Custom TTL

```python
# Override default TTL
client.cache.set(
    endpoint="/api/clubs",
    params={},
    data=clubs_data,
    ttl=7 * 24 * 60 * 60  # 7 days
)
```

---

## 🎉 Summary

**Storage Location**: `data/cache/` directory (automatically created)

**Cache Strategy**:
- Static data (clubs, seasons): 30 days
- Semi-static (teams, players): 7 days  
- Dynamic (rankings, scorers): 1 hour
- Real-time (live games): 5 minutes

**Benefits**:
- ✅ 60x faster for repeated requests
- ✅ Reduces API load
- ✅ Works offline with cached data
- ✅ Automatic cache invalidation
- ✅ Easy to manage and clear

**Next Steps**:
1. Copy `cache.py` to `api/` folder
2. Update `client.py` with caching support
3. Run preload script to warm cache
4. Enjoy fast, efficient API access! 🚀

# Data Indexing Strategy

## Overview

SwissUnihockeyStats uses a **hierarchical indexing system** to build comprehensive player profiles from multiple data sources. This approach addresses API limitations and provides better search functionality.

## Indexing Hierarchy

Data is indexed in the following order:

```
1. Seasons (current + recent)
   ↓
2. Leagues & Clubs (structural data)
   ↓
3. Teams (with rosters → players)
   ↓
4. Games (with events → player stats)
   ↓
5. Players (aggregated profiles)
```

## Data Structures

### Core Storage
- **`_leagues`**: List of all leagues (50 leagues)
- **`_clubs`**: List of all clubs (346 clubs)
- **`_teams`**: List of teams (lazy-loaded per search)
- **`_games`**: Dictionary keyed by game_id
- **`_players`**: Dictionary keyed by person_id

### Player Profile Structure
```python
{
    "id": int,              # person_id
    "person_id": int,       # Same as id
    "name": str,            # Full name
    "text": str,            # Display text (name)
    "teams": [              # Teams player belongs to
        {
            "id": int,
            "name": str,
            "league": str
        }
    ],
    "games": [int],         # List of game_ids player participated in
    "stats": {              # Aggregated statistics
        "games_played": int,
        # More stats added from game events
    },
    "source": str,          # "team_roster" or "game_event"
    "raw_data": dict        # Original API response
}
```

## Indexing Methods

### 1. `index_players_from_teams()`
**Purpose**: Extract player information from team rosters

**Process**:
1. Iterate through leagues
2. Fetch teams for each league
3. For each team, fetch player roster
4. Create player profiles with team membership

**Challenges**: 
- `/api/players?team=X&season=Y` may return 404 for some seasons
- Workaround: Try current and previous seasons, handle errors gracefully

### 2. `index_players_from_games()`
**Purpose**: Extract player stats and fill gaps from game events

**Process**:
1. Fetch recent games from major leagues (NLA, NLB)
2. Extract player participation from game events
3. Update existing profiles or create new ones
4. Aggregate statistics (goals, assists, games played)

**Benefits**:
- Captures players who might not be in team rosters
- Provides real-time statistics
- Works even when roster endpoints are unavailable

### 3. `build_comprehensive_player_index()`
**Purpose**: Orchestrate the complete indexing process

**Process**:
```python
async def build_comprehensive_player_index():
    1. Index from team rosters (primary source)
    2. Enhance with game data (stats + gaps)
    3. Mark as indexed
    4. Log results
```

**Execution**: Runs as background task on application startup

## Search Functionality

### `search_players(query, limit=50)`
**Features**:
- Case-insensitive substring search on player names
- Lazy indexing (builds index on first search if not already done)
- Returns up to `limit` results
- Searches across all indexed players

**Usage**:
```python
results = await cache.search_players("bazzu", limit=50)
# Returns list of player dictionaries matching "bazzu"
```

## API Limitations & Solutions

### Problem: No Global Player Search
**API Issue**: `/api/players` requires specific parameters (team, club, or person_id)

**Solution**: Build our own player index from multiple sources

### Problem: 404 Errors for Some Endpoints
**API Issue**: Various endpoints return 404 depending on season/league/parameters

**Solution**: 
- Graceful error handling (try/except with continue)
- Multiple fallback strategies (try current season → previous season)
- Extract data from successful requests only
- Log failures as debug messages (don't crash)

### Problem: Topscorers Endpoint Unreliable
**API Issue**: `/api/topscorers` returns 404 for all tested league/season combinations

**Solution**: Don't rely on topscorers; extract from teams + games instead

## Performance Considerations

### Background Indexing
- Runs asynchronously on startup
- Doesn't block application initialization
- Users can start using app while indexing continues

### Lazy Loading
- Teams are loaded on-demand
- Player index built only when first search occurs
- Reduces startup time and memory usage

### Caching
- All fetched data is cached in memory
- Concurrent access protected by async locks
- `_players_indexed` flag prevents redundant indexing

## Future Improvements

### Phase 1: Persistence
- Save indexed data to file/database
- Only re-index changed data on startup
- Reduce API calls and startup time

### Phase 2: Incremental Updates
- Track last_updated timestamps per data type
- Only fetch new/changed data
- Schedule periodic background updates

### Phase 3: Enhanced Statistics
- Parse game events for detailed stats (goals, assists, penalties)
- Calculate advanced metrics (goals per game, etc.)
- Track career statistics across seasons

### Phase 4: Season Management
- Support multiple seasons
- Historical data comparisons
- Season-specific searches

## Usage Example

```python
from app.services.data_cache import get_data_cache

# Get cache instance
cache = get_data_cache()

# Search for players (triggers indexing if needed)
players = await cache.search_players("mueller")

# Access player data
for player in players:
    print(f"{player['name']} - {len(player['teams'])} teams")
    print(f"  Games played: {player['stats'].get('games_played', 0)}")
```

## Monitoring

### Logs to Watch
- `✓ Indexed X new players from Y teams` - Team roster extraction
- `✓ Updated X players from Y games` - Game event extraction
- `✓ Indexed Z total players in T.TTs` - Overall completion

### Common Warnings
- `Could not fetch players for team X: 404` - Expected for some teams/seasons
- `Could not process league X: ...` - Some leagues may have no data

### Error Indicators
- `❌ Error building player index` - Critical failure (should investigate)
- `All retry attempts failed` - API unavailable (temporary issue)

## Conclusion

This hierarchical indexing strategy provides:
- **Robustness**: Multiple data sources with fallbacks
- **Completeness**: Players from teams AND games
- **Performance**: Background processing, lazy loading, caching
- **Flexibility**: Easy to add new data sources
- **Reliability**: Graceful handling of API limitations

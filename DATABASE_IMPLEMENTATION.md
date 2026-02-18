# Database-Backed Player Indexing

This implementation replaces the in-memory cache with a persistent SQLite database for storing Swiss Unihockey data.

## Architecture

### Database Models

The database follows the hierarchical API structure:

```
seasons (top level)
├── clubs → teams → team_players (roster)
└── leagues → groups → games → game_players (lineups)
```

**Key Tables:**
- `seasons` - Season information (e.g., 2025/26)
- `clubs` - Clubs per season
- `teams` - Teams (belong to clubs and leagues)
- `players` - Unique players across all seasons
- `team_players` - Player roster assignments (many-to-many)
- `leagues` - Leagues per season (e.g., NLB Men)
- `league_groups` - Groups within leagues
- `games` - Games within groups
- `game_players` - Game lineups (many-to-many)
- `game_events` - Events within games (goals, penalties)
- `player_statistics` - Aggregated stats per season
- `sync_status` - Tracks last update time for each entity

### Staged Updates

Different entities have different update frequencies:

| Entity | Update Frequency | Max Age |
|--------|-----------------|---------|
| Seasons | Yearly | 30 days |
| Clubs | Quarterly | 7 days |
| Teams | Monthly | 3 days |
| Players | Weekly | 24 hours |
| Leagues | Monthly | 7 days |
| Games (finished) | Once | N/A |
| Games (today) | Hourly | 1 hour |
| Player Stats | After games | 4 hours |

## Getting Started

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Initialize Database

```bash
python manage.py init-db
```

This creates `data/swissunihockey.db` with all tables.

### 3. Index Data

**Option A: Index via Clubs Path (Recommended for initial setup)**

This follows: CLUBS → TEAMS → PLAYERS

```bash
# Index first 10 clubs (for testing)
python manage.py index-clubs-path --season 2025 --max-clubs 10

# Index all clubs (takes longer)
python manage.py index-clubs-path --season 2025
```

**Option B: Index via Leagues Path (For games data)**

This follows: LEAGUES → GROUPS → GAMES

```bash
# Index leagues first
python manage.py index-leagues --season 2025

# Then index games and lineups (TODO: implement)
# python manage.py index-games --season 2025
```

### 4. Check Statistics

```bash
python manage.py stats
```

Output:
```
=== Database Statistics ===
Seasons:      2
Clubs:        245
Teams:        1,230
Players:      15,420
Team-Players: 18,560
Leagues:      12
Games:        0
```

### 5. Search Players

```bash
python manage.py search-players "mueller"
```

Output:
```
Found 15 players matching 'mueller':
  [123456] Hans Mueller
      → UHC Thun
  [234567] Peter Mueller  
      → Kloten-Dietlikon Jets
  ...
```

## Using in Application

### Start the Server

```bash
cd backend
uvicorn app.main:app --reload
```

The database is automatically initialized on startup.

### Player Search API

Players are now searched from the database:

**Endpoint:** `GET /{locale}/players/search?q=mueller`

**Example:**
```bash
curl "http://localhost:8000/en/players/search?q=mueller"
```

## Management Commands Reference

```bash
# Database Operations
python manage.py init-db              # Initialize database
python manage.py reset-db             # Drop and recreate tables (WARNING!)
python manage.py stats                # Show database statistics

# Data Indexing
python manage.py index-seasons        # Index all seasons
python manage.py index-clubs-path --season 2025  # Index clubs → teams → players
python manage.py index-leagues --season 2025     # Index leagues

# Search
python manage.py search-players "name"  # Search players from CLI
```

## Incremental Updates

The system tracks `last_updated` timestamps for each entity. Updates are skipped if data is fresh:

```python
from app.services.data_indexer import get_data_indexer

indexer = get_data_indexer()

# These will check sync_status and skip if recent
indexer.index_clubs(season_id=2025)  # Skips if updated < 7 days ago
indexer.index_players_for_team(team_id=123, season_id=2025)  # Skips if < 24h

# Force update regardless of last sync
indexer.index_clubs(season_id=2025, force=True)
```

## Database Location

- **Development:** `data/swissunihockey.db` (SQLite)
- **Production:** Configure `DATABASE_URL` in settings for PostgreSQL

## Implementation Status

✅ **Completed:**
- Database models with hierarchical structure
- Database service with session management
- Data indexer following CLUBS → TEAMS → PLAYERS path
- Staged update tracking with sync_status
- Player search from database
- Management CLI
- Foreign key relationships and indexes

🔄 **In Progress:**
- LEAGUES → GROUPS → GAMES → LINEUPS indexing path
- Game events indexing
- Player statistics aggregation

📋 **Planned:**
- Scheduled background updates (Celery/APScheduler)
- Real-time game updates
- Full-text search with advanced filters
- API endpoints for database queries
- Data export/import utilities
- Migration scripts for schema changes

## Performance Considerations

### Indexing Performance

- **First full index:** ~30-60 minutes for one season
- **Incremental updates:** <5 minutes for recent changes
- **Memory usage:** Minimal (database is on disk)

### Search Performance

- Player name search: <10ms (indexed columns)
- Complex queries: <100ms (with proper indexes)
- Database size: ~100-200MB per season

### Optimization Tips

1. **Limit initial indexing:** Use `--max-clubs` for testing
2. **Index in batches:** Index important leagues (NLB, 1st Liga) first
3. **Schedule updates:** Run incremental updates during off-peak hours
4. **Monitor sync_status:** Check for failed syncs regularly
5. **Use PostgreSQL:** For production with many concurrent users

## Troubleshooting

### Database is empty after indexing

```bash
# Check sync status
python manage.py stats

# Verify seasons exist
python manage.py index-seasons

# Try manual indexing with verbose logging
python manage.py index-clubs-path --season 2025 --max-clubs 5
```

### Player search returns no results

```bash
# Check if players are indexed
python manage.py stats

# Verify database has data
python manage.py search-players "a"  # Should match many players
```

### Slow queries

```bash
# Rebuild database with optimized indexes
python manage.py reset-db
python manage.py init-db
python manage.py index-clubs-path --season 2025
```

## Migration from Old System

The old in-memory `data_cache.py` is still present for backwards compatibility with existing code. To fully migrate:

1. ✅ Database models created
2. ✅ Player search updated to use database
3. ❌ Update other endpoints to use database (clubs, teams, games)
4. ❌ Remove old data_cache player indexing methods
5. ❌ Update tests to use database fixtures

## Contributing

When adding new features:

1. Update database models in `app/models/db_models.py`
2. Add indexer methods in `app/services/data_indexer.py`
3. Create management commands in `backend/manage.py`
4. Update this README with usage examples
5. Add tests for new functionality

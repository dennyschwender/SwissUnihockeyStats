"""
Data caching service for SwissUnihockey API data
Lazy-loads data on first access and caches for future requests
"""
import logging
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime
from app.services.swissunihockey import get_swissunihockey_client

logger = logging.getLogger(__name__)


class DataCache:
    """In-memory cache for SwissUnihockey API data with hierarchical indexing
    
    Data is indexed in the following order:
    1. Seasons (current + recent)
    2. Leagues & Clubs (structural data)
    3. Teams (with rosters → players)
    4. Games (with events → player stats)
    5. Players (aggregated from teams + games)
    """
    
    def __init__(self):
        # Structural data
        self._leagues: List[Dict[str, Any]] = []
        self._clubs: List[Dict[str, Any]] = []
        self._teams: List[Dict[str, Any]] = []
        
        # Indexed data (keyed by ID)
        self._seasons: List[int] = []  # Available seasons
        self._games: Dict[int, Dict[str, Any]] = {}  # game_id -> game_data
        self._players: Dict[int, Dict[str, Any]] = {}  # person_id -> player_profile
        
        self._last_updated: Optional[datetime] = None
        
        # Track loading state per category
        self._leagues_loaded: bool = False
        self._clubs_loaded: bool = False
        self._teams_loaded: bool = False
        self._teams_popular_loaded: bool = False
        self._seasons_loaded: bool = False
        self._players_indexed: bool = False
        
        # Locks to prevent concurrent loading
        self._teams_lock: Optional[asyncio.Lock] = None
        self._leagues_lock: Optional[asyncio.Lock] = None
        self._clubs_lock: Optional[asyncio.Lock] = None
        self._players_lock: Optional[asyncio.Lock] = None
        self._games_lock: Optional[asyncio.Lock] = None
    
    def _ensure_locks(self):
        """Ensure async locks are created (must be called in async context)"""
        if self._teams_lock is None:
            self._teams_lock = asyncio.Lock()
        if self._leagues_lock is None:
            self._leagues_lock = asyncio.Lock()
        if self._clubs_lock is None:
            self._clubs_lock = asyncio.Lock()
        if self._players_lock is None:
            self._players_lock = asyncio.Lock()
        if self._games_lock is None:
            self._games_lock = asyncio.Lock()
    

    async def load_clubs(self) -> None:
        """Load clubs data from API (lazy loading)"""
        self._ensure_locks()
        async with self._clubs_lock:
            if self._clubs_loaded:
                logger.debug("Clubs already loaded, using cache")
                return
            
            logger.info("Loading clubs...")
            start_time = datetime.now()
            
            try:
                client = get_swissunihockey_client()
                clubs_data = client.get_clubs()
                self._clubs = clubs_data.get("entries", [])
                self._clubs_loaded = True
                
                elapsed = (datetime.now() - start_time).total_seconds()
                logger.info(f"✓ Loaded {len(self._clubs)} clubs in {elapsed:.2f}s")
                
            except Exception as e:
                logger.error(f"❌ Error loading clubs: {e}")
                self._clubs = []
                raise
    
    async def load_leagues(self) -> None:
        """Load leagues data from API (lazy loading)"""
        self._ensure_locks()
        async with self._leagues_lock:
            if self._leagues_loaded:
                logger.debug("Leagues already loaded, using cache")
                return
            
            logger.info("Loading leagues...")
            start_time = datetime.now()
            
            try:
                client = get_swissunihockey_client()
                leagues_data = client.get_leagues()
                self._leagues = leagues_data.get("entries", [])
                self._leagues_loaded = True
                
                elapsed = (datetime.now() - start_time).total_seconds()
                logger.info(f"✓ Loaded {len(self._leagues)} leagues in {elapsed:.2f}s")
                
            except Exception as e:
                logger.error(f"❌ Error loading leagues: {e}")
                self._leagues = []
                raise
    
    async def load_popular_teams(self) -> None:
        """Load teams using mode parameter (men's teams) for faster initial response"""
        self._ensure_locks()
        async with self._teams_lock:
            if self._teams_popular_loaded:
                logger.debug("Popular teams already loaded, using cache")
                return
            
            logger.info("Loading popular teams (men's teams)...")
            start_time = datetime.now()
            
            try:
                client = get_swissunihockey_client()
                
                # Load men's teams (mode=1) - covers most popular leagues
                # Note: League parameter doesn't work with API (returns 500 errors)
                teams_data_mens = client.get_teams(mode=1)
                
                # Extract actual teams from nested structure
                # API returns nested structure: { 'data': { 'regions': [{ 'rows': [...teams...] }] } }
                # OR flat structure: { 'entries': [...teams...] }
                
                # First try to extract from nested 'data.regions[0].rows'
                if isinstance(teams_data_mens, dict) and "data" in teams_data_mens:
                    data_field = teams_data_mens["data"]
                    if isinstance(data_field, dict) and "regions" in data_field and len(data_field["regions"]) > 0:
                        popular_teams = data_field["regions"][0].get("rows", [])
                    else:
                        popular_teams = data_field.get("entries", data_field.get("data", []))
                # Fallback: try top-level 'regions' or 'entries'
                elif isinstance(teams_data_mens, dict) and "regions" in teams_data_mens and len(teams_data_mens["regions"]) > 0:
                    popular_teams = teams_data_mens["regions"][0].get("rows", [])
                else:
                    popular_teams = teams_data_mens.get("entries", teams_data_mens.get("data", []))
                
                # Normalize team data structure - extract team name from cells array
                # API structure: {'id': 123, 'cells': [{'text': ['Team Name']}, ...]}
                # Desired: {'id': 123, 'text': 'Team Name', ...}
                normalized_teams = []
                for team in popular_teams:
                    if isinstance(team, dict):
                        normalized_team = {'id': team.get('id'), 'highlight': team.get('highlight', False)}
                        # Extract team name from first cell
                        cells = team.get('cells', [])
                        if cells and isinstance(cells[0], dict) and 'text' in cells[0]:
                            team_name = cells[0]['text']
                            # Name can be a list or string
                            normalized_team['text'] = team_name[0] if isinstance(team_name, list) else team_name
                        else:
                            normalized_team['text'] = 'Unknown Team'
                        normalized_teams.append(normalized_team)
               
                self._teams = normalized_teams
                self._teams_popular_loaded = True
                
                elapsed = (datetime.now() - start_time).total_seconds()
                logger.info(f"✓ Loaded {len(popular_teams)} popular teams in {elapsed:.2f}s")
                
            except Exception as e:
                logger.error(f"❌ Error loading popular teams: {e}")
                self._teams = []
                raise
    
    async def load_teams(self) -> None:
        """Load ALL teams data from API (lazy loading - loads remaining teams if popular already loaded)"""
        self._ensure_locks()
        async with self._teams_lock:
            if self._teams_loaded:
                logger.debug("All teams already loaded, using cache")
                return
            
            # If popular teams already loaded, log that we're loading the rest
            if self._teams_popular_loaded:
                logger.info("Loading remaining teams (popular leagues already cached)...")
            else:
                logger.info("Loading all teams (this may take a while)...")
            
            start_time = datetime.now()
            
            try:
                client = get_swissunihockey_client()
                
                def extract_teams(data_dict):
                    """Extract teams from API response (handles nested structure)"""
                    # Try nested structure: { 'data': { 'regions': [{ 'rows': [...] }] } }
                    if isinstance(data_dict, dict) and "data" in data_dict:
                        data_field = data_dict["data"]
                        if isinstance(data_field, dict) and "regions" in data_field and len(data_field["regions"]) > 0:
                            return data_field["regions"][0].get("rows", [])
                        # Try data.entries
                        return data_field.get("entries", data_field.get("data", []))
                    # Fallback: try top-level regions or entries
                    elif isinstance(data_dict, dict) and "regions" in data_dict and len(data_dict["regions"]) > 0:
                        return data_dict["regions"][0].get("rows", [])
                    return data_dict.get("entries", data_dict.get("data", []))
                
                def normalize_teams(raw_teams):
                    """Normalize team data structure - extract team name from cells array"""
                    normalized = []
                    for team in raw_teams:
                        if isinstance(team, dict):
                            norm_team = {'id': team.get('id'), 'highlight': team.get('highlight', False)}
                            # Extract team name from first cell
                            cells = team.get('cells', [])
                            if cells and isinstance(cells[0], dict) and 'text' in cells[0]:
                                team_name = cells[0]['text']
                                norm_team['text'] = team_name[0] if isinstance(team_name, list) else team_name
                            else:
                                norm_team['text'] = 'Unknown Team'
                            normalized.append(norm_team)
                    return normalized
                
                teams_data = client.get_teams()
                teams_list = normalize_teams(extract_teams(teams_data))
                
                if not teams_list:
                    logger.warning(f"Teams API returned empty data. Response keys: {list(teams_data.keys())}")
                    logger.info("Trying teams with mode parameter (1=Men's, 2=Women's, 3=Mixed)...")
                    
                    # Try with mode parameter to get actual data
                    teams_data_mens = client.get_teams(mode=1)
                    teams_mens = normalize_teams(extract_teams(teams_data_mens))
                    
                    teams_data_womens = client.get_teams(mode=2)
                    teams_womens = normalize_teams(extract_teams(teams_data_womens))
                    
                    teams_data_mixed = client.get_teams(mode=3)
                    teams_mixed = normalize_teams(extract_teams(teams_data_mixed))
                    
                    # Combine all teams
                    teams_list = teams_mens + teams_womens + teams_mixed
                    logger.info(f"Loaded teams by mode: {len(teams_mens)} mens, {len(teams_womens)} womens, {len(teams_mixed)} mixed")
                
                # If popular teams already loaded, merge and deduplicate
                if self._teams_popular_loaded and self._teams:
                    # Create set of existing team IDs to avoid duplicates
                    existing_ids = {team.get("context", {}).get("team_id") for team in self._teams}
                    new_teams = [team for team in teams_list if team.get("context", {}).get("team_id") not in existing_ids]
                    self._teams.extend(new_teams)
                    logger.info(f"Added {len(new_teams)} additional teams to existing {len(self._teams) - len(new_teams)} popular teams")
                else:
                    self._teams = teams_list
                
                self._teams_loaded = True
                
                elapsed = (datetime.now() - start_time).total_seconds()
                logger.info(f"✓ Loaded {len(self._teams)} total teams in {elapsed:.2f}s")
                
            except Exception as e:
                logger.error(f"❌ Error loading teams: {e}")
                # Don't clear existing popular teams if they exist
                if not self._teams_popular_loaded:
                    self._teams = []
                raise
    
    async def load_common_data(self) -> None:
        """Load commonly-accessed data (clubs, leagues, popular teams) - fast startup preload"""
        logger.info("Preloading commonly-accessed data...")
        start_time = datetime.now()
        
        try:
            # Load clubs, leagues and popular teams concurrently
            await asyncio.gather(
                self.load_clubs(),
                self.load_leagues(),
                self.load_popular_teams(),
                return_exceptions=True
            )
            
            self._last_updated = datetime.now()
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ Clubs, leagues, and popular teams preloaded in {elapsed:.2f}s")
            logger.info(f"💤 Remaining teams will lazy-load on first search")
            
        except Exception as e:
            logger.error(f"❌ Error during preload: {e}")
            raise
    
    async def load_all_data(self) -> None:
        """Load all data from API into cache (useful for full preload)"""
        logger.info("Starting full data preload...")
        start_time = datetime.now()
        
        try:
            # Load all categories concurrently
            await asyncio.gather(
                self.load_leagues(),
                self.load_teams(),
                return_exceptions=True
            )
            
            self._last_updated = datetime.now()
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ Full data preload complete in {elapsed:.2f} seconds")
            
        except Exception as e:
            logger.error(f"❌ Error during full preload: {e}")
            raise
    
    async def get_teams(self) -> List[Dict[str, Any]]:
        """Get cached teams data, loading popular teams if necessary.
        For full teams list, call load_teams() explicitly."""
        # Check if popular teams are loaded, if not load them
        if not self._teams_popular_loaded:
            await self.load_popular_teams()
        return self._teams
    
    async def get_clubs(self) -> List[Dict[str, Any]]:
        """Get cached clubs data, loading if necessary"""
        if not self._clubs_loaded:
            await self.load_clubs()
        return self._clubs
    
    async def get_leagues(self) -> List[Dict[str, Any]]:
        """Get cached leagues data, loading if necessary"""
        if not self._leagues_loaded:
            await self.load_leagues()
        return self._leagues
    
    def is_loaded(self) -> bool:
        """Check if all data has been loaded"""
        return self._teams_loaded and self._leagues_loaded and self._clubs_loaded
    
    def is_teams_loaded(self) -> bool:
        """Check if teams data has been loaded"""
        return self._teams_loaded
    
    def is_clubs_loaded(self) -> bool:
        """Check if clubs data has been loaded"""
        return self._clubs_loaded
    
    def is_leagues_loaded(self) -> bool:
        """Check if leagues data has been loaded"""
        return self._leagues_loaded
    
    def get_last_updated(self) -> Optional[datetime]:
        """Get the timestamp of last data load"""
        return self._last_updated
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "teams_loaded": self._teams_loaded,
            "teams_popular_loaded": self._teams_popular_loaded,
            "leagues_loaded": self._leagues_loaded,
            "clubs_loaded": self._clubs_loaded,
            "players_indexed": self._players_indexed,
            "all_loaded": self.is_loaded(),
            "last_updated": self._last_updated.isoformat() if self._last_updated else None,
            "teams_count": len(self._teams),
            "leagues_count": len(self._leagues),
            "clubs_count": len(self._clubs),
            "players_count": len(self._players),
            "games_count": len(self._games),
        }
    
    def _extract_player_name(self, player_data: Dict[str, Any]) -> str:
        """Extract player name from various data formats"""
        # Try direct text field
        name = player_data.get("text", "")
        if name:
            return name
        
        # Try given_name + family_name
        given = player_data.get("given_name", "")
        family = player_data.get("family_name", "")
        if given or family:
            return f"{given} {family}".strip()
        
        # Try cells array (topscorers format)
        cells = player_data.get("cells", [])
        if cells and isinstance(cells[0], dict):
            cell_text = cells[0].get("text", "")
            if isinstance(cell_text, list):
                return " ".join(str(t) for t in cell_text)
            return str(cell_text)
        
        return ""
    
    async def index_players_from_teams(self) -> int:
        """Extract and index players from team rosters
        
        Returns:
            Number of new players indexed
        """
        logger.info("Indexing players from team rosters...")
        client = get_swissunihockey_client()
        from app.main import get_current_season
        current_season = get_current_season()
        
        # Ensure leagues are loaded
        await self.load_leagues()
        
        new_players = 0
        teams_processed = 0
        
        # Process a sample of leagues to extract players from teams
        for league in self._leagues[:10]:  # Process first 10 leagues
            context = league.get("set_in_context", {})
            league_id = context.get("league")
            game_class = context.get("game_class")
            mode = context.get("mode", "1")
            
            if not league_id or not game_class:
                continue
                
            try:
                # Fetch teams for this league
                teams_data = client.get_teams(
                    league=league_id,
                    game_class=game_class,
                    mode=mode,
                    season=current_season
                )
                
                teams = []
                if isinstance(teams_data, dict):
                    if "data" in teams_data:
                        regions = teams_data.get("data", {}).get("regions", [])
                        if regions:
                            teams = regions[0].get("rows", [])
                    elif "entries" in teams_data:
                        teams = teams_data["entries"]
                
                # For each team, fetch players
                for team in teams[:3]:  # First 3 teams per league
                    team_id = team.get("id")
                    team_name = team.get("text", "")
                    
                    if not team_id:
                        continue
                    
                    try:
                        # Fetch players for this team
                        players_data = client.get_players(team=team_id, season=current_season)
                        
                        players = []
                        if isinstance(players_data, dict):
                            players = players_data.get("entries", players_data.get("data", []))
                        
                        # Index each player
                        for player in players:
                            player_id = player.get("person_id") or player.get("id")
                            if not player_id:
                                continue
                            
                            # Create or update player profile
                            if player_id not in self._players:
                                player_name = self._extract_player_name(player)
                                
                                self._players[player_id] = {
                                    "id": player_id,
                                    "person_id": player_id,
                                    "name": player_name,
                                    "text": player_name,
                                    "teams": [{"id": team_id, "name": team_name, "league": league.get("text", "")}],
                                    "games": [],  # Will be populated from game events
                                    "stats": {},  # Will aggregate from games
                                    "source": "team_roster",
                                    "raw_data": player
                                }
                                new_players += 1
                            else:
                                # Add team to existing player
                                team_info = {"id": team_id, "name": team_name, "league": league.get("text", "")}
                                if team_info not in self._players[player_id]["teams"]:
                                    self._players[player_id]["teams"].append(team_info)
                        
                        teams_processed += 1
                        
                    except Exception as e:
                        logger.debug(f"Could not fetch players for team {team_id}: {e}")
                        continue
                        
            except Exception as e:
                logger.debug(f"Could not process league {league_id}: {e}")
                continue
        
        logger.info(f"✓ Indexed {new_players} new players from {teams_processed} teams")
        return new_players
    
    async def index_players_from_games(self) -> int:
        """Extract and index players from game events and lineups
        
        Returns:
            Number of players updated with game stats
        """
        logger.info("Indexing players from game events...")
        client = get_swissunihockey_client()
        from app.main import get_current_season
        current_season = get_current_season()
        
        # Ensure leagues are loaded
        await self.load_leagues()
        
        players_updated = 0
        games_processed = 0
        
        # Process recent games from major leagues
        major_leagues = [(1, 11), (1, 21), (2, 11), (2, 21)]  # NLA/NLB Men & Women
        
        for league_id, game_class in major_leagues:
            try:
                # Fetch recent games for this league
                games_data = client.get_games(
                    league=league_id,
                    game_class=game_class,
                    mode="1",
                    season=current_season
                )
                
                games = []
                if isinstance(games_data, dict):
                    games = games_data.get("entries", games_data.get("data", []))
                
                # Process first few games to extract player stats
                for game in games[:5]:  # Process 5 games per league
                    game_id = game.get("id")
                    if not game_id:
                        continue
                    
                    # Store game data
                    if game_id not in self._games:
                        self._games[game_id] = game
                    
                    # Extract players from game details/events
                    # Game events contain player actions (goals, assists, etc.)
                    events = game.get("events", [])
                    for event in events:
                        player_id = event.get("person_id") or event.get("player_id")
                        if not player_id:
                            continue
                        
                        # Create minimal player entry if not exists
                        if player_id not in self._players:
                            player_name = event.get("player_name", f"Player #{player_id}")
                            self._players[player_id] = {
                                "id": player_id,
                                "person_id": player_id,
                                "name": player_name,
                                "text": player_name,
                                "teams": [],
                                "games": [game_id],
                                "stats": {"games_played": 1},
                                "source": "game_event"
                            }
                            players_updated += 1
                        else:
                            # Update existing player with game info
                            if game_id not in self._players[player_id].get("games", []):
                                self._players[player_id].setdefault("games", []).append(game_id)
                                stats = self._players[player_id].setdefault("stats", {})
                                stats["games_played"] = stats.get("games_played", 0) + 1
                                players_updated += 1
                    
                    games_processed += 1
                    
            except Exception as e:
                logger.debug(f"Could not process games for league {league_id}/{game_class}: {e}")
                continue
        
        logger.info(f"✓ Updated {players_updated} players from {games_processed} games")
        return players_updated
    
    async def build_comprehensive_player_index(self) -> None:
        """Build comprehensive player index from all available sources
        
        Indexing order:
        1. Teams (rosters) - primary source
        2. Games (events) - adds stats and fills gaps
        3. Topscorers - optional enhancement (if available)
        """
        self._ensure_locks()
        async with self._players_lock:
            if self._players_indexed:
                logger.debug("Players already indexed, using cache")
                return
            
            logger.info("Building comprehensive player index...")
            start_time = datetime.now()
            
            try:
                # Step 1: Index from team rosters
                team_players = await self.index_players_from_teams()
                
                # Step 2: Enhance with game data
                game_players = await self.index_players_from_games()
                
                self._players_indexed = True
                elapsed = (datetime.now() - start_time).total_seconds()
                
                logger.info(f"✓ Indexed {len(self._players)} total players "
                           f"({team_players} from teams, {game_players} from games) "
                           f"in {elapsed:.2f}s")
                
            except Exception as e:
                logger.error(f"❌ Error building player index: {e}")
                raise
    
    
    async def search_players(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Search for players by name in the indexed player data"""
        # Ensure players are indexed
        if not self._players_indexed:
            await self.build_comprehensive_player_index()
        
        if not query or len(query) < 2:
            return []
        
        query_lower = query.lower()
        results = []
        
        for player_id, player in self._players.items():
            player_name = player.get("name", "").lower()
            if query_lower in player_name:
                results.append(player)
                if len(results) >= limit:
                    break
        
        return results


# Global cache instance
_cache: Optional[DataCache] = None


def get_data_cache() -> DataCache:
    """Get or create the global data cache instance"""
    global _cache
    if _cache is None:
        _cache = DataCache()
    return _cache


async def preload_common_data():
    """Preload commonly-accessed data (clubs, leagues) for fast initial response"""
    cache = get_data_cache()
    await cache.load_common_data()


async def preload_data():
    """Preload all data into cache (full preload - optional)"""
    cache = get_data_cache()
    await cache.load_all_data()


async def get_cached_teams() -> List[Dict[str, Any]]:
    """Get teams from cache, loading on-demand if necessary"""
    return await get_data_cache().get_teams()


async def get_cached_clubs() -> List[Dict[str, Any]]:
    """Get clubs from cache, loading on-demand if necessary"""
    return await get_data_cache().get_clubs()


async def get_cached_leagues() -> List[Dict[str, Any]]:
    """Get leagues from cache, loading on-demand if necessary"""
    return await get_data_cache().get_leagues()

"""
Data caching service for SwissUnihockey API data
Lazy-loads data on first access and caches for future requests
"""
import logging
import asyncio
import threading
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from app.services.swissunihockey import get_swissunihockey_client
from app.services.season_utils import get_current_season

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

    # TTL for each category before data is considered stale and reloaded
    _CLUBS_TTL    = timedelta(days=7)
    _LEAGUES_TTL  = timedelta(days=7)
    _TEAMS_TTL    = timedelta(days=3)

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

        # Track loading state and timestamps per category
        self._leagues_loaded: bool = False
        self._clubs_loaded: bool = False
        self._teams_loaded: bool = False
        self._teams_popular_loaded: bool = False
        self._seasons_loaded: bool = False
        self._players_indexed: bool = False

        self._clubs_loaded_at: Optional[datetime] = None
        self._leagues_loaded_at: Optional[datetime] = None
        self._teams_loaded_at: Optional[datetime] = None
        self._teams_popular_loaded_at: Optional[datetime] = None

        # Locks are initialized lazily because asyncio.Lock() must be created
        # inside a running event loop; they are created once on first use.
        self._teams_lock: Optional[asyncio.Lock] = None
        self._leagues_lock: Optional[asyncio.Lock] = None
        self._clubs_lock: Optional[asyncio.Lock] = None
        self._players_lock: Optional[asyncio.Lock] = None
        self._games_lock: Optional[asyncio.Lock] = None
        # Thread lock guarding the lock-creation step itself
        self._init_lock = threading.Lock()

    def _ensure_locks(self):
        """Ensure async locks are created exactly once (thread-safe)."""
        if self._teams_lock is not None:
            return  # fast path — already done
        with self._init_lock:
            # Double-checked under thread lock
            if self._teams_lock is None:
                self._teams_lock   = asyncio.Lock()
                self._leagues_lock = asyncio.Lock()
                self._clubs_lock   = asyncio.Lock()
                self._players_lock = asyncio.Lock()
                self._games_lock   = asyncio.Lock()

    # -------------------------------------------------------------------------
    # Static helpers shared by load_popular_teams() and load_teams()
    # -------------------------------------------------------------------------

    @staticmethod
    def _extract_teams(data_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract team rows from an API response (handles nested structure)."""
        if isinstance(data_dict, dict) and "data" in data_dict:
            data_field = data_dict["data"]
            if isinstance(data_field, dict) and "regions" in data_field and data_field["regions"]:
                return data_field["regions"][0].get("rows", [])
            return data_field.get("entries", data_field.get("data", []))
        if isinstance(data_dict, dict) and "regions" in data_dict and data_dict["regions"]:
            return data_dict["regions"][0].get("rows", [])
        return data_dict.get("entries", data_dict.get("data", []))

    @staticmethod
    def _normalize_teams(raw_teams: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize team data: extract team name from cells array."""
        normalized = []
        for team in raw_teams:
            if not isinstance(team, dict):
                continue
            norm_team = {"id": team.get("id"), "highlight": team.get("highlight", False)}
            cells = team.get("cells", [])
            if cells and isinstance(cells[0], dict) and "text" in cells[0]:
                team_name = cells[0]["text"]
                norm_team["text"] = team_name[0] if isinstance(team_name, list) else team_name
            else:
                norm_team["text"] = "Unknown Team"
            normalized.append(norm_team)
        return normalized
    

    async def load_clubs(self) -> None:
        """Load clubs data from API (lazy loading with TTL)."""
        self._ensure_locks()
        async with self._clubs_lock:
            now = datetime.now()
            if (self._clubs_loaded and self._clubs_loaded_at
                    and now - self._clubs_loaded_at < self._CLUBS_TTL):
                logger.debug("Clubs already loaded, using cache")
                return

            logger.info("Loading clubs...")
            start_time = datetime.now()

            try:
                loop = asyncio.get_running_loop()
                client = get_swissunihockey_client()
                clubs_data = await loop.run_in_executor(None, client.get_clubs)
                self._clubs = clubs_data.get("entries", [])
                self._clubs_loaded = True
                self._clubs_loaded_at = datetime.now()

                elapsed = (datetime.now() - start_time).total_seconds()
                logger.info(f"✓ Loaded {len(self._clubs)} clubs in {elapsed:.2f}s")

            except Exception as e:
                logger.error(f"❌ Error loading clubs: {e}")
                self._clubs = []
                raise

    async def load_leagues(self) -> None:
        """Load leagues data from API (lazy loading with TTL)."""
        self._ensure_locks()
        async with self._leagues_lock:
            now = datetime.now()
            if (self._leagues_loaded and self._leagues_loaded_at
                    and now - self._leagues_loaded_at < self._LEAGUES_TTL):
                logger.debug("Leagues already loaded, using cache")
                return

            logger.info("Loading leagues...")
            start_time = datetime.now()

            try:
                loop = asyncio.get_running_loop()
                client = get_swissunihockey_client()
                leagues_data = await loop.run_in_executor(None, client.get_leagues)
                self._leagues = leagues_data.get("entries", [])
                self._leagues_loaded = True
                self._leagues_loaded_at = datetime.now()

                elapsed = (datetime.now() - start_time).total_seconds()
                logger.info(f"✓ Loaded {len(self._leagues)} leagues in {elapsed:.2f}s")

            except Exception as e:
                logger.error(f"❌ Error loading leagues: {e}")
                self._leagues = []
                raise
    
    async def load_popular_teams(self) -> None:
        """Load teams using mode parameter (men's teams) for faster initial response."""
        self._ensure_locks()
        async with self._teams_lock:
            now = datetime.now()
            if (self._teams_popular_loaded and self._teams_popular_loaded_at
                    and now - self._teams_popular_loaded_at < self._TEAMS_TTL):
                logger.debug("Popular teams already loaded, using cache")
                return

            logger.info("Loading popular teams (men's teams)...")
            start_time = datetime.now()

            try:
                loop = asyncio.get_running_loop()
                client = get_swissunihockey_client()
                teams_data_mens = await loop.run_in_executor(None, lambda: client.get_teams(mode=1))
                popular_teams = self._extract_teams(teams_data_mens)
                normalized_teams = self._normalize_teams(popular_teams)

                self._teams = normalized_teams
                self._teams_popular_loaded = True
                self._teams_popular_loaded_at = datetime.now()

                elapsed = (datetime.now() - start_time).total_seconds()
                logger.info(f"✓ Loaded {len(popular_teams)} popular teams in {elapsed:.2f}s")

            except Exception as e:
                logger.error(f"❌ Error loading popular teams: {e}")
                self._teams = []
                raise
    
    async def load_teams(self) -> None:
        """Load ALL teams data from API (lazy loading - loads remaining teams if popular already loaded)."""
        self._ensure_locks()
        async with self._teams_lock:
            now = datetime.now()
            if (self._teams_loaded and self._teams_loaded_at
                    and now - self._teams_loaded_at < self._TEAMS_TTL):
                logger.debug("All teams already loaded, using cache")
                return

            if self._teams_popular_loaded:
                logger.info("Loading remaining teams (popular leagues already cached)...")
            else:
                logger.info("Loading all teams (this may take a while)...")

            start_time = datetime.now()

            try:
                loop = asyncio.get_running_loop()
                client = get_swissunihockey_client()

                teams_data = await loop.run_in_executor(None, client.get_teams)
                teams_list = self._normalize_teams(self._extract_teams(teams_data))

                if not teams_list:
                    logger.warning(f"Teams API returned empty data. Response keys: {list(teams_data.keys())}")
                    logger.info("Trying teams with mode parameter (1=Men's, 2=Women's, 3=Mixed)...")

                    teams_mens   = self._normalize_teams(self._extract_teams(
                        await loop.run_in_executor(None, lambda: client.get_teams(mode=1))
                    ))
                    teams_womens = self._normalize_teams(self._extract_teams(
                        await loop.run_in_executor(None, lambda: client.get_teams(mode=2))
                    ))
                    teams_mixed  = self._normalize_teams(self._extract_teams(
                        await loop.run_in_executor(None, lambda: client.get_teams(mode=3))
                    ))
                    teams_list = teams_mens + teams_womens + teams_mixed
                    logger.info(
                        f"Loaded teams by mode: {len(teams_mens)} mens, "
                        f"{len(teams_womens)} womens, {len(teams_mixed)} mixed"
                    )

                # If popular teams already loaded, merge and deduplicate
                if self._teams_popular_loaded and self._teams:
                    existing_ids = {team.get("context", {}).get("team_id") for team in self._teams}
                    new_teams = [
                        t for t in teams_list
                        if t.get("context", {}).get("team_id") not in existing_ids
                    ]
                    self._teams.extend(new_teams)
                    logger.info(
                        f"Added {len(new_teams)} additional teams to existing "
                        f"{len(self._teams) - len(new_teams)} popular teams"
                    )
                else:
                    self._teams = teams_list

                self._teams_loaded = True
                self._teams_loaded_at = datetime.now()

                elapsed = (datetime.now() - start_time).total_seconds()
                logger.info(f"✓ Loaded {len(self._teams)} total teams in {elapsed:.2f}s")

            except Exception as e:
                logger.error(f"❌ Error loading teams: {e}")
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
        """Get cached teams data, loading popular teams if necessary (respects TTL).
        For the full teams list, call load_teams() explicitly."""
        now = datetime.now()
        if (not self._teams_popular_loaded
                or not self._teams_popular_loaded_at
                or now - self._teams_popular_loaded_at >= self._TEAMS_TTL):
            await self.load_popular_teams()
        return self._teams

    async def get_clubs(self) -> List[Dict[str, Any]]:
        """Get cached clubs data, loading if necessary (respects TTL)."""
        now = datetime.now()
        if (not self._clubs_loaded
                or not self._clubs_loaded_at
                or now - self._clubs_loaded_at >= self._CLUBS_TTL):
            await self.load_clubs()
        return self._clubs

    async def get_leagues(self) -> List[Dict[str, Any]]:
        """Get cached leagues data, loading if necessary (respects TTL)."""
        now = datetime.now()
        if (not self._leagues_loaded
                or not self._leagues_loaded_at
                or now - self._leagues_loaded_at >= self._LEAGUES_TTL):
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
        season = get_current_season()
        
        new_players = 0
        teams_processed = 0
        
        # Focus on major leagues that are known to have rankings
        # NLB Men: league=2, game_class=11
        # NLB Women: league=2, game_class=21  
        major_leagues = [
            {"league": 2, "game_class": 11, "name": "Herren NLB"},
            {"league": 2, "game_class": 21, "name": "Damen NLB "},
            {"league": 3, "game_class": 11, "name": "1. Liga"},
            {"league": 3, "game_class": 21, "name": "Damen 1. Liga"},
        ]
        
        for league_info in major_leagues:
            league_id = league_info["league"]
            game_class = league_info["game_class"]
            league_name = league_info["name"]
            
            try:
                # Fetch teams from rankings (more reliable than teams endpoint)
                teams_data = client.get_rankings(
                    league=league_id,
                    game_class=game_class,
                    season=season
                )
                
                teams = []
                if isinstance(teams_data, dict):
                    if "data" in teams_data:
                        regions = teams_data.get("data", {}).get("regions", [])
                        if regions:
                            rows = regions[0].get("rows", [])
                            # Extract team info from ranking rows
                            # Each row has data.team.id and data.team.name
                            for row in rows:
                                row_data = row.get("data", {})
                                team_info = row_data.get("team", {})
                                if team_info.get("id"):
                                    teams.append({
                                        "id": team_info.get("id"),
                                        "text": team_info.get("name", "Unknown Team")
                                    })
                    elif "entries" in teams_data:
                        teams = teams_data["entries"]
                
                if not teams:
                    logger.debug(f"No teams found for league {league_id}")
                    continue
                
                logger.info(f"  → Found {len(teams)} teams in {league_name}")
                
                # For each team, fetch players
                for team in teams[:15]:  # Try up to 15 teams per league to find ones with rosters
                    team_id = team.get("id")
                    team_name = team.get("text", "")
                    
                    if not team_id:
                        continue
                    
                    try:
                        # Fetch players for this team using correct endpoint
                        players_data = client.get_team_players(team_id)
                        
                        players = []
                        if isinstance(players_data, dict):
                            # Team players use table format: data.regions[0].rows
                            data = players_data.get("data", {})
                            if isinstance(data, dict) and "regions" in data:
                                regions = data.get("regions", [])
                                if regions and len(regions) > 0:
                                    players = regions[0].get("rows", [])
                            # Fallback to other formats
                            elif "entries" in players_data:
                                players = players_data["entries"]
                        
                        if not players:
                            logger.debug(f"No players found for team {team_id}")
                            continue
                        
                        logger.info(f"  → Found {len(players)} players in team {team_id} ({team_name})")
                        
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
                                    "teams": [{"id": team_id, "name": team_name, "league": league_name}],
                                    "games": [],  # Will be populated from game events
                                    "stats": {},  # Will aggregate from games
                                    "source": "team_roster",
                                    "raw_data": player
                                }
                                new_players += 1
                            else:
                                # Add team to existing player
                                team_info = {"id": team_id, "name": team_name, "league": league_name}
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
        """Extract and index players from game lineups
        
        Uses hierarchical API structure:
        1. Get leagues from cache
        2. For each league, fetch games with actual league/game_class parameters
        3. For each game, fetch lineups for home and away teams
        
        Returns:
            Number of players updated with game stats
        """
        logger.info("Indexing players from game lineups...")
        client = get_swissunihockey_client()
        current_season = get_current_season()
        
        # Ensure leagues are loaded
        await self.load_leagues()
        
        if not self._leagues:
            logger.warning("No leagues loaded, cannot index from games")
            return 0
        
        players_updated = 0
        games_processed = 0
        
        # Process games from actual loaded leagues (use first 5 leagues)
        for league in self._leagues[:5]:
            league_id = league.get("id")
            league_name = league.get("text", "Unknown")
            
            # Get game classes for this league
            game_classes = league.get("game_classes", [])
            if not game_classes:
                continue
            
            # Process first game class (typically the main competition)
            for game_class_info in game_classes[:1]:
                game_class = game_class_info.get("id")
                
                if not game_class:
                    continue
                
                try:
                    # Try current season first, fall back to previous season
                    games_data = None
                    season_to_use = current_season
                    
                    for season_attempt in [current_season, current_season - 1]:
                        try:
                            logger.info(f"Fetching games for {league_name} (league={league_id}, game_class={game_class}, season={season_attempt})...")
                            games_data = client.get_games(
                                mode="list",
                                season=season_attempt,
                                league=league_id,
                                game_class=game_class
                            )
                            season_to_use = season_attempt
                            break
                        except Exception as e:
                            if season_attempt == current_season:
                                logger.debug(f"  Season {season_attempt} failed: {e}, trying previous season...")
                            else:
                                logger.debug(f"  Season {season_attempt} also failed: {e}")
                                continue
                    
                    if not games_data:
                        continue
                    
                    # Parse games list (table format with regions)
                    games = []
                    if isinstance(games_data, dict):
                        # Games use table format with regions
                        data = games_data.get("data", {})
                        if isinstance(data, dict) and "regions" in data:
                            regions = data.get("regions", [])
                            if regions:
                                games = regions[0].get("rows", [])
                        # Fallback to entries
                        elif "entries" in games_data:
                            games = games_data["entries"]
                    
                    logger.info(f"  → Found {len(games)} games")
                    
                    # Process first few games to extract players from lineups
                    for game in games[:5]:  # Process 5 games per league
                        game_id = game.get("id")
                        if not game_id:
                            continue

                        try:
                            # Fetch game lineups for both home and away teams
                            for is_home in [1, 0]:  # 1=home, 0=away
                                team_type = "home" if is_home else "away"
                                logger.info(f"  Fetching {team_type} lineup for game {game_id}...")

                                lineup_data = client.get_game_lineup(game_id, is_home)

                                if not lineup_data or not isinstance(lineup_data, dict):
                                    continue

                                # Parse lineup data (table format)
                                players = []
                                data = lineup_data.get("data", {})
                                if isinstance(data, dict) and "regions" in data:
                                    regions = data.get("regions", [])
                                    if regions:
                                        players = regions[0].get("rows", [])

                                logger.info(f"    → Found {len(players)} players in {team_type} lineup")

                                # Index each player
                                for player in players:
                                    player_id = player.get("person_id") or player.get("id")
                                    if not player_id:
                                        continue

                                    player_name = self._extract_player_name(player)

                                    if player_id not in self._players:
                                        self._players[player_id] = {
                                            "id": player_id,
                                            "person_id": player_id,
                                            "name": player_name,
                                            "text": player_name,
                                            "teams": [],
                                            "games": [game_id],
                                            "stats": {"games_played": 1},
                                            "source": "game_lineup",
                                        }
                                        players_updated += 1
                                    else:
                                        if game_id not in self._players[player_id].get("games", []):
                                            self._players[player_id].setdefault("games", []).append(game_id)
                                            stats = self._players[player_id].setdefault("stats", {})
                                            stats["games_played"] = stats.get("games_played", 0) + 1
                                            players_updated += 1

                            games_processed += 1

                        except Exception as e:
                            logger.debug(f"Could not fetch game lineup for {game_id}: {e}")
                            continue
                
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


# Global cache instance (thread-safe singleton)
_cache: Optional[DataCache] = None
_cache_lock = threading.Lock()


def get_data_cache() -> DataCache:
    """Get or create the global data cache instance (thread-safe)."""
    global _cache
    if _cache is None:
        with _cache_lock:
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

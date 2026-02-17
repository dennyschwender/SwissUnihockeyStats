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
    """In-memory cache for SwissUnihockey API data with lazy loading"""
    
    def __init__(self):
        self._teams: List[Dict[str, Any]] = []
        self._clubs: List[Dict[str, Any]] = []
        self._leagues: List[Dict[str, Any]] = []
        self._last_updated: Optional[datetime] = None
        
        # Track loading state per category to prevent duplicate API calls
        self._teams_loaded: bool = False  # All teams loaded
        self._teams_popular_loaded: bool = False  # Popular teams (men's) loaded
        self._clubs_loaded: bool = False
        self._leagues_loaded: bool = False
        
        # Locks to prevent concurrent loading of same data (created lazily)
        self._teams_lock: Optional[asyncio.Lock] = None
        self._clubs_lock: Optional[asyncio.Lock] = None
        self._leagues_lock: Optional[asyncio.Lock] = None
    
    def _ensure_locks(self):
        """Ensure async locks are created (must be called in async context)"""
        if self._teams_lock is None:
            self._teams_lock = asyncio.Lock()
        if self._clubs_lock is None:
            self._clubs_lock = asyncio.Lock()
        if self._leagues_lock is None:
            self._leagues_lock = asyncio.Lock()
    
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
            # Load clubs, leagues, and popular teams concurrently
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
                self.load_clubs(),
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
        For full teams list, call load_teams() explicitly."""        # Check if popular teams are loaded, if not load them
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
        return self._teams_loaded and self._clubs_loaded and self._leagues_loaded
    
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
            "clubs_loaded": self._clubs_loaded,
            "leagues_loaded": self._leagues_loaded,
            "all_loaded": self.is_loaded(),
            "last_updated": self._last_updated.isoformat() if self._last_updated else None,
            "teams_count": len(self._teams),
            "clubs_count": len(self._clubs),
            "leagues_count": len(self._leagues),
        }


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

"""SwissUnihockey API client."""

import logging
import time
from typing import Any, Dict, Optional
import requests

try:
    from api.cache import CacheManager
except ImportError:
    from cache import CacheManager


logger = logging.getLogger(__name__)


class SwissUnihockeyClient:
    """Client for the SwissUnihockey API v2."""

    def __init__(
        self,
        base_url: str = "https://api-v2.swissunihockey.ch",
        locale: str = "de-CH",
        timeout: int = 30,
        retry_attempts: int = 3,
        retry_delay: int = 1,
        use_cache: bool = True,
        cache_dir: str = "data/cache",
    ):
        """
        Initialize the API client.

        Args:
            base_url: Base URL for the API
            locale: Locale for localized responses (en, de-CH, fr-CH, it-CH)
            timeout: Request timeout in seconds
            retry_attempts: Number of retry attempts for failed requests
            retry_delay: Delay between retries in seconds
            use_cache: Enable/disable caching (default: True)
            cache_dir: Directory for cache files (default: data/cache)
        """
        self.base_url = base_url.rstrip("/")
        self.locale = locale
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.session = requests.Session()
        
        # Initialize cache
        self.use_cache = use_cache
        self.cache = CacheManager(cache_dir) if use_cache else None

    def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        category: str = "general",
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Make a request to the API with caching and retry logic.

        Args:
            endpoint: API endpoint (e.g., '/api/clubs')
            params: Query parameters
            category: Cache category (clubs, teams, rankings, etc.)
            force_refresh: Skip cache and fetch fresh data

        Returns:
            JSON response as dictionary

        Raises:
            requests.exceptions.RequestException: If request fails after retries
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
                    time.sleep(self.retry_delay * (attempt + 1))  # Exponential backoff
                    
        # If all retries failed, raise the last exception
        logger.error(f"All retry attempts failed for {endpoint}")
        raise last_exception

    def get_clubs(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Fetch all clubs (cached for 30 days)."""
        return self._make_request("/api/clubs", category="clubs", force_refresh=force_refresh)

    def get_leagues(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Fetch all leagues (cached for 7 days)."""
        return self._make_request("/api/leagues", category="leagues", force_refresh=force_refresh)

    def get_seasons(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Fetch all seasons (cached for 30 days)."""
        return self._make_request("/api/seasons", category="seasons", force_refresh=force_refresh)

    def get_teams(self, **params) -> Dict[str, Any]:
        """
        Fetch teams.

        Args:
            **params: Query parameters (e.g., club, league, season, mode)

        Returns:
            Teams data
        """
        return self._make_request("/api/teams", params)

    def get_games(self, **params) -> Dict[str, Any]:
        """
        Fetch games.

        Args:
            **params: Query parameters (e.g., team_id, league, season, from_date, to_date)

        Returns:
            Games data
        """
        return self._make_request("/api/games", params)

    def get_game_events(self, **params) -> Dict[str, Any]:
        """
        Fetch game events.

        Args:
            **params: Query parameters (e.g., game_id)

        Returns:
            Game events data
        """
        return self._make_request("/api/game_events", params)

    def get_rankings(self, force_refresh: bool = False, **params) -> Dict[str, Any]:
        """
        Fetch league rankings/standings (cached for 1 hour).

        Args:
            force_refresh: Skip cache and fetch fresh data
            **params: Query parameters (league, game_class, season, group)

        Returns:
            Rankings data
        """
        return self._make_request("/api/rankings", params, category="rankings", force_refresh=force_refresh)

    def get_topscorers(self, force_refresh: bool = False, **params) -> Dict[str, Any]:
        """
        Fetch top scorers (cached for 1 hour).

        Args:
            force_refresh: Skip cache and fetch fresh data
            **params: Query parameters (league, game_class, season, group)

        Returns:
            Top scorers data
        """
        return self._make_request("/api/topscorers", params, category="topscorers", force_refresh=force_refresh)

    def get_players(self, **params) -> Dict[str, Any]:
        """
        Fetch players.

        Args:
            **params: Query parameters (e.g., team, club, person_id)

        Returns:
            Players data
        """
        return self._make_request("/api/players", params)

    def get_national_players(self, **params) -> Dict[str, Any]:
        """
        Fetch national team players.

        Args:
            **params: Query parameters

        Returns:
            National players data
        """
        return self._make_request("/api/national_players", params)

    def get_groups(self, **params) -> Dict[str, Any]:
        """
        Fetch groups/divisions.

        Args:
            **params: Query parameters (league, game_class, season)

        Returns:
            Groups data
        """
        return self._make_request("/api/groups", params)

    def get_cups(self, **params) -> Dict[str, Any]:
        """
        Fetch cup competitions.

        Args:
            **params: Query parameters

        Returns:
            Cups data
        """
        return self._make_request("/api/cups", params)

    def get_calendars(self, **params) -> Dict[str, Any]:
        """
        Fetch match calendars.

        Args:
            **params: Query parameters

        Returns:
            Calendars data
        """
        return self._make_request("/api/calendars", params)

    def close(self):
        """Close the session."""
        self.session.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

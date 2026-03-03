"""
SwissUnihockey API client and file-based cache manager.
Self-contained — no dependency on the old root-level api/ package.
"""

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import requests
import requests.exceptions

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cache manager
# ---------------------------------------------------------------------------

class CacheManager:
    """Manage file-based caching for API responses."""

    TTL_CONFIG = {
        "static":      30 * 24 * 60 * 60,  # 30 days
        "semi_static":  7 * 24 * 60 * 60,  # 7 days
        "dynamic":           60 * 60,       # 1 hour
        "realtime":          5 * 60,        # 5 minutes
    }

    def __init__(self, cache_dir: str = "data/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.cache_dir / "metadata.json"
        self.metadata = self._load_metadata()
        self._lock = threading.Lock()  # guards metadata mutations and tmp rename

    def _load_metadata(self) -> Dict[str, Any]:
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load cache metadata: {e}")
        return {}

    def _save_metadata(self):
        """Atomically persist metadata to disk using a temp file + rename.

        Uses a per-call unique tmp filename (PID + thread id) so that concurrent
        gunicorn worker *processes* each write their own tmp file and never race
        on the same path.  Within a process the threading.Lock still serialises
        the in-memory snapshot and the final rename.

        Pattern:
          1. snapshot self.metadata under lock (avoids "dict changed size" error)
          2. write to a process+thread-unique tmp file (no cross-process collision)
          3. atomic replace tmp → metadata.json (POSIX guarantee; last writer wins)
        """
        try:
            with self._lock:
                snapshot = dict(self.metadata)  # shallow copy under lock
            # Unique tmp path per call: avoids ENOENT race when multiple
            # gunicorn workers all try to rename the same metadata.tmp file.
            tmp = self.metadata_file.with_name(
                f"metadata.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(self.metadata_file)  # atomic on POSIX
        except Exception as e:
            logger.error(f"Failed to save cache metadata: {e}")

    def _get_cache_key(self, endpoint: str, params: Optional[Dict] = None) -> str:
        param_str = str(sorted(params.items())) if params else ""
        return hashlib.md5(f"{endpoint}:{param_str}".encode()).hexdigest()

    def _get_cache_path(self, cache_key: str, category: str = "general") -> Path:
        category_dir = self.cache_dir / category
        category_dir.mkdir(parents=True, exist_ok=True)
        return category_dir / f"{cache_key}.json"

    def _determine_ttl(self, endpoint: str) -> int:
        if endpoint in ["/api/clubs", "/api/seasons", "/api/venues"]:
            return self.TTL_CONFIG["static"]
        if endpoint in ["/api/teams", "/api/players", "/api/leagues"]:
            return self.TTL_CONFIG["semi_static"]
        if "/api/game_events" in endpoint or "/live" in endpoint:
            return self.TTL_CONFIG["realtime"]
        return self.TTL_CONFIG["dynamic"]

    def get(self, endpoint: str, params: Optional[Dict] = None, category: str = "general") -> Optional[Dict[str, Any]]:
        cache_key = self._get_cache_key(endpoint, params)
        cache_path = self._get_cache_path(cache_key, category)
        if not cache_path.exists():
            return None
        meta = self.metadata.get(cache_key, {})
        cached_at = meta.get("cached_at")
        ttl = meta.get("ttl", self._determine_ttl(endpoint))
        if cached_at:
            expires_at = datetime.fromisoformat(cached_at) + timedelta(seconds=ttl)
            if datetime.now() > expires_at:
                return None
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read cache: {e}")
            return None

    def set(self, endpoint: str, params: Optional[Dict], data: Dict[str, Any], category: str = "general", ttl: Optional[int] = None):
        cache_key = self._get_cache_key(endpoint, params)
        cache_path = self._get_cache_path(cache_key, category)
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            with self._lock:
                self.metadata[cache_key] = {
                    "endpoint": endpoint,
                    "params": params,
                    "category": category,
                    "cached_at": datetime.now().isoformat(),
                    "ttl": ttl or self._determine_ttl(endpoint),
                }
            self._save_metadata()
        except Exception as e:
            logger.error(f"Failed to write cache: {e}")

    def clear(self, category: Optional[str] = None):
        if category:
            category_dir = self.cache_dir / category
            if category_dir.exists():
                for file in category_dir.glob("*.json"):
                    file.unlink()
            with self._lock:
                self.metadata = {k: v for k, v in self.metadata.items() if v.get("category") != category}
        else:
            for file in self.cache_dir.glob("**/*.json"):
                if file.name != "metadata.json":
                    file.unlink()
            with self._lock:
                self.metadata = {}
        self._save_metadata()

    def get_stats(self) -> Dict[str, Any]:
        total_files = sum(1 for _ in self.cache_dir.glob("**/*.json") if _.name != "metadata.json")
        total_size = sum(f.stat().st_size for f in self.cache_dir.glob("**/*.json") if f.name != "metadata.json")
        categories: Dict[str, int] = {}
        for meta in self.metadata.values():
            cat = meta.get("category", "general")
            categories[cat] = categories.get(cat, 0) + 1
        return {
            "total_entries": len(self.metadata),
            "total_files": total_files,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "categories": categories,
        }


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class SwissUnihockeyClient:
    """HTTP client for the SwissUnihockey API v2."""

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
        self.base_url = base_url.rstrip("/")
        self.locale = locale
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.session = requests.Session()
        self.use_cache = use_cache
        self.cache = CacheManager(cache_dir) if use_cache else None

    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None, category: str = "general", force_refresh: bool = False, timeout: int | None = None) -> Dict[str, Any]:
        if params is None:
            params = {}
        params["locale"] = self.locale

        if self.use_cache and not force_refresh:
            cached = self.cache.get(endpoint, params, category)
            if cached is not None:
                return cached

        url = f"{self.base_url}{endpoint}"
        _timeout = timeout if timeout is not None else self.timeout
        last_exc = None
        for attempt in range(self.retry_attempts):
            try:
                resp = self.session.get(url, params=params, timeout=_timeout)
                resp.raise_for_status()
                data = resp.json()
                if self.use_cache:
                    self.cache.set(endpoint, params, data, category)
                return data
            except requests.exceptions.HTTPError as e:
                # 4xx errors are client errors — retrying will never help.
                # Raise immediately without wasting time on retries.
                if e.response is not None and 400 <= e.response.status_code < 500:
                    logger.warning(f"Client error {e.response.status_code} for {endpoint}, not retrying")
                    raise
                last_exc = e
                logger.warning(f"Request failed (attempt {attempt+1}/{self.retry_attempts}): {e}")
                if attempt < self.retry_attempts - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
            except requests.exceptions.RequestException as e:
                last_exc = e
                logger.warning(f"Request failed (attempt {attempt+1}/{self.retry_attempts}): {e}")
                if attempt < self.retry_attempts - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
        logger.error(f"All retry attempts failed for {endpoint}")
        raise last_exc

    # --- Seasons & Clubs ---
    def get_seasons(self, force_refresh: bool = False) -> Dict[str, Any]:
        return self._make_request("/api/seasons", category="seasons", force_refresh=force_refresh)

    def get_clubs(self, force_refresh: bool = False, **params) -> Dict[str, Any]:
        return self._make_request("/api/clubs", params, category="clubs", force_refresh=force_refresh)

    # --- Leagues & Groups ---
    def get_leagues(self, force_refresh: bool = False, **params) -> Dict[str, Any]:
        return self._make_request("/api/leagues", params, category="leagues", force_refresh=force_refresh)

    def get_groups(self, **params) -> Dict[str, Any]:
        return self._make_request("/api/groups", params)

    # --- Teams ---
    def get_teams(self, **params) -> Dict[str, Any]:
        return self._make_request("/api/teams", params)

    def get_team_players(self, team_id: int) -> Dict[str, Any]:
        return self._make_request(f"/api/teams/{team_id}/players", {})

    def get_team_details(self, team_id: int) -> Dict[str, Any]:
        return self._make_request(f"/api/teams/{team_id}", {})

    def get_team_stats(self, team_id: int) -> Dict[str, Any]:
        return self._make_request(f"/api/teams/{team_id}/statistics", {})

    # --- Players ---
    def get_players(self, **params) -> Dict[str, Any]:
        return self._make_request("/api/players", params)

    def get_player_details(self, player_id: int) -> Dict[str, Any]:
        return self._make_request(f"/api/players/{player_id}", {})

    def get_player_stats(self, player_id: int, **params) -> Dict[str, Any]:
        return self._make_request(f"/api/players/{player_id}/statistics", params)

    def get_player_overview(self, player_id: int, *, request_timeout: int | None = None, **params) -> Dict[str, Any]:
        return self._make_request(f"/api/players/{player_id}/overview", params, timeout=request_timeout)

    # --- Games ---
    def get_games(self, **params) -> Dict[str, Any]:
        return self._make_request("/api/games", params)

    def get_game_details(self, game_id: int) -> Dict[str, Any]:
        return self._make_request(f"/api/games/{game_id}", {})

    def get_game_summary(self, game_id: int) -> Dict[str, Any]:
        return self._make_request(f"/api/games/{game_id}/summary", {})

    def get_game_lineup(self, game_id: int, is_home: int = 1) -> Dict[str, Any]:
        return self._make_request(f"/api/games/{game_id}/teams/{is_home}/players", {})

    def get_game_events(self, **params) -> Dict[str, Any]:
        return self._make_request("/api/game_events", params)

    def get_game_events_by_id(self, game_id: int) -> Dict[str, Any]:
        return self._make_request(f"/api/game_events/{game_id}", {})

    # --- Rankings & Scores ---
    def get_rankings(self, force_refresh: bool = False, **params) -> Dict[str, Any]:
        return self._make_request("/api/rankings", params, category="rankings", force_refresh=force_refresh)

    def get_topscorers(self, force_refresh: bool = False, **params) -> Dict[str, Any]:
        return self._make_request("/api/topscorers", params, category="topscorers", force_refresh=force_refresh)

    # --- Misc ---
    def get_national_players(self, **params) -> Dict[str, Any]:
        return self._make_request("/api/national_players", params)

    def get_cups(self, **params) -> Dict[str, Any]:
        return self._make_request("/api/cups", params)

    def get_calendars(self, **params) -> Dict[str, Any]:
        return self._make_request("/api/calendars", params)

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

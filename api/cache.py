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
                # Remove metadata entries for this category
                self.metadata = {
                    k: v for k, v in self.metadata.items()
                    if v.get("category") != category
                }
                self._save_metadata()
        else:
            for file in self.cache_dir.glob("**/*.json"):
                if file.name != "metadata.json":
                    file.unlink()
            self.metadata = {}
            self._save_metadata()
            logger.info("Cleared all cache")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_files = sum(1 for _ in self.cache_dir.glob("**/*.json") if _.name != "metadata.json")
        total_size = sum(
            f.stat().st_size for f in self.cache_dir.glob("**/*.json")
            if f.name != "metadata.json"
        )
        
        categories = {}
        for key, meta in self.metadata.items():
            cat = meta.get("category", "general")
            categories[cat] = categories.get(cat, 0) + 1
        
        return {
            "total_entries": len(self.metadata),
            "total_files": total_files,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "categories": categories,
        }

"""
SwissUnihockey API integration service — thread-safe singleton wrapper around SwissUnihockeyClient.
"""

import threading
from app.services.api_client import SwissUnihockeyClient
from app.config import settings

# Global client instance (singleton pattern)
_client: SwissUnihockeyClient | None = None
_client_lock = threading.Lock()


def get_swissunihockey_client() -> SwissUnihockeyClient:
    """
    Get or create the SwissUnihockey API client instance (thread-safe).

    Returns:
        SwissUnihockeyClient: Configured API client
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:  # double-checked locking
                _client = SwissUnihockeyClient(
                    base_url=settings.SWISSUNIHOCKEY_API_URL,
                    locale=settings.SWISSUNIHOCKEY_LOCALE,
                    use_cache=settings.SWISSUNIHOCKEY_CACHE_ENABLED,
                    cache_dir=settings.SWISSUNIHOCKEY_CACHE_DIR,
                    timeout=10,
                    retry_attempts=2,
                )
    return _client


def close_swissunihockey_client():
    """Close and clear the global client instance."""
    global _client
    with _client_lock:
        if _client is not None:
            _client.close()
            _client = None

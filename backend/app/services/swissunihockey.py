"""
SwissUnihockey API integration service — singleton wrapper around SwissUnihockeyClient.
"""
from app.services.api_client import SwissUnihockeyClient
from app.config import settings


# Global client instance (singleton pattern)
_client: SwissUnihockeyClient | None = None


def get_swissunihockey_client() -> SwissUnihockeyClient:
    """
    Get or create SwissUnihockey API client instance
    
    Returns:
        SwissUnihockeyClient: Configured API client
    """
    global _client
    
    if _client is None:
        _client = SwissUnihockeyClient(
            base_url=settings.SWISSUNIHOCKEY_API_URL,
            locale=settings.SWISSUNIHOCKEY_LOCALE,
            use_cache=settings.SWISSUNIHOCKEY_CACHE_ENABLED,
            cache_dir=settings.SWISSUNIHOCKEY_CACHE_DIR,
            timeout=10,  # Reduce timeout to 10 seconds (was 30)
            retry_attempts=2  # Reduce retries to 2 (was 3)
        )
    
    return _client


def close_swissunihockey_client():
    """Close the global client instance"""
    global _client
    if _client is not None:
        _client.close()
        _client = None

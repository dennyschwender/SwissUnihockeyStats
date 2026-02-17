"""
SwissUnihockey API integration service
Connects FastAPI backend to the existing Python API client
"""
import sys
from pathlib import Path

# Add parent directory to path to import from ../api
backend_dir = Path(__file__).resolve().parent.parent.parent
root_dir = backend_dir.parent
sys.path.insert(0, str(root_dir))

# Import the existing API client
from api import SwissUnihockeyClient
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

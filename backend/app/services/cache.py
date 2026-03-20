"""
In-memory TTL cache for expensive DB query results.

Thread-safe: all operations hold _lock. Scheduler worker threads call
invalidate_prefix() while FastAPI route handlers call get/set from the
asyncio event loop.

TTL is configured via QUERY_CACHE_TTL_SECONDS env var (default: 3600s / 1 hour).
Data only changes during sync jobs so 1-hour staleness is acceptable.
"""
import os
import threading
import time
from typing import Any

_TTL: float = float(os.environ.get("QUERY_CACHE_TTL_SECONDS", "3600"))
_lock = threading.Lock()
_cache: dict[tuple, tuple[Any, float]] = {}  # key → (value, stored_at)


def get_cached(key: tuple) -> Any | None:
    """Return cached value if present and not expired, else None."""
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        value, stored_at = entry
        if time.monotonic() - stored_at > _TTL:
            del _cache[key]  # evict expired entry
            return None
        return value


def set_cached(key: tuple, value: Any) -> None:
    """Store value in cache with current timestamp."""
    with _lock:
        _cache[key] = (value, time.monotonic())


def invalidate_prefix(prefix: str) -> None:
    """Remove all cache entries whose key starts with prefix."""
    with _lock:
        keys_to_remove = [k for k in _cache if k[0] == prefix]
        for k in keys_to_remove:
            del _cache[k]

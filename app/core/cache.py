import time
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("check.cache")

class AsyncTTLCache:
    """
    An in-memory, thread-safe asynchronous TTL (Time-To-Live) cache.
    Stores cached objects with an expiration timestamp.
    """
    def __init__(self, default_ttl: int = 600):
        self.default_ttl = default_ttl
        self._cache: Dict[str, Tuple[Any, float]] = {}

    async def get(self, key: str) -> Optional[Any]:
        if key not in self._cache:
            logger.debug(f"Cache MISS for key: {key}")
            return None
        
        value, expiry = self._cache[key]
        if time.time() > expiry:
            logger.debug(f"Cache EXPIRED for key: {key}")
            del self._cache[key]
            return None
        
        logger.debug(f"Cache HIT for key: {key}")
        return value

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        duration = ttl if ttl is not None else self.default_ttl
        expiry = time.time() + duration
        self._cache[key] = (value, expiry)
        logger.debug(f"Cache SET for key: {key} (TTL: {duration}s)")

    async def delete(self, key: str) -> None:
        if key in self._cache:
            del self._cache[key]
            logger.debug(f"Cache DELETE for key: {key}")

    async def clear(self) -> None:
        self._cache.clear()
        logger.debug("Cache CLEARED")

# Global instances for reuse across the application
timetable_cache = AsyncTTLCache(default_ttl=600)  # 10 minutes cache for timetables

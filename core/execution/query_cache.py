"""Query result caching with TTL and LRU eviction."""
import time
import logging
import threading
from typing import Any, Dict, Optional, Tuple
from collections import OrderedDict

logger = logging.getLogger(__name__)


class QueryCache:
    """Thread-safe TTL-based LRU cache for query results."""

    def __init__(self, max_items: int = 200, ttl_seconds: int = 300):
        """Initialize query cache.

        Args:
            max_items: Maximum number of cache entries
            ttl_seconds: Time-to-live for cache entries in seconds
        """
        self.cache: "OrderedDict[Tuple[str, int], Dict[str, Any]]" = OrderedDict()
        self.max_items = max_items
        self.ttl_seconds = ttl_seconds
        self.hits = 0
        self.misses = 0
        self.bypassed = 0
        self._lock = threading.RLock()

    def get(self, key: Tuple[str, int]) -> Optional[Dict[str, Any]]:
        """Get cached item if not expired; maintains LRU order."""
        if self.ttl_seconds <= 0:
            return None
        with self._lock:
            item = self.cache.get(key)
            if not item:
                self.misses += 1
                return None
            ts = item.get('__cached_at__')
            if ts is None:
                self.cache.pop(key, None)
                self.misses += 1
                return None
            age = time.time() - ts
            if age > self.ttl_seconds:
                self.cache.pop(key, None)
                self.misses += 1
                return None
            # Refresh LRU order
            self.cache.move_to_end(key)
            self.hits += 1
            # Return a shallow copy with cache metadata
            res = dict(item)
            res.setdefault('cache', {})
            res['cache'].update({'hit': True, 'age_seconds': round(age, 3)})
            return res

    def set(self, key: Tuple[str, int], value: Dict[str, Any]) -> None:
        """Store item in cache with current timestamp."""
        if self.ttl_seconds <= 0:
            return
        with self._lock:
            # Add timestamp
            value = dict(value)
            value['__cached_at__'] = time.time()
            value.setdefault('cache', {})['cached'] = True
            self.cache[key] = value
            # Evict oldest if over capacity
            while len(self.cache) > self.max_items:
                try:
                    self.cache.popitem(last=False)
                except KeyError:
                    break

    def flush(self) -> Dict[str, Any]:
        """Clear all cached entries."""
        with self._lock:
            try:
                count = len(self.cache)
                self.cache.clear()
                self.hits = 0
                self.misses = 0
                self.bypassed = 0
                return {'success': True, 'cleared': count}
            except Exception as e:
                return {'success': False, 'error': str(e)}

    def get_stats(self) -> Dict[str, Any]:
        """Return cache statistics and configuration."""
        with self._lock:
            try:
                return {
                    'success': True,
                    'size': len(self.cache),
                    'max_items': self.max_items,
                    'ttl_seconds': self.ttl_seconds,
                    'hits': self.hits,
                    'misses': self.misses,
                    'bypassed': self.bypassed,
                    'enabled': self.ttl_seconds > 0,
                }
            except Exception as e:
                return {'success': False, 'error': str(e)}

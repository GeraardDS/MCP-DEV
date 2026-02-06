"""
Enhanced cache manager with size limits and eviction metrics.
Prevents memory leaks from unbounded cache growth.
"""

import time
import hashlib
import logging
from typing import Any, Optional, Dict, Tuple
from collections import OrderedDict
import threading

logger = logging.getLogger("mcp_powerbi_finvision.cache_manager")


class CacheEntry:
    """Represents a cached item with metadata."""
    
    def __init__(self, key: str, value: Any, ttl: float):
        self.key = key
        self.value = value
        self.created_at = time.time()
        self.expires_at = self.created_at + ttl if ttl > 0 else float('inf')
        self.hits = 0
        self.last_accessed = self.created_at
        
        # Approximate size (for memory limits)
        try:
            import sys
            self.size_bytes = sys.getsizeof(value)
        except Exception:
            self.size_bytes = 1024  # Default estimate
    
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.time() > self.expires_at
    
    def access(self) -> Any:
        """Record access and return value."""
        self.hits += 1
        self.last_accessed = time.time()
        return self.value
    
    def age_seconds(self) -> float:
        """Get age in seconds."""
        return time.time() - self.created_at


class EnhancedCacheManager:
    """
    Thread-safe cache with TTL, size limits, and eviction policies.
    """
    
    def __init__(self, config: Optional[dict] = None):
        """
        Initialize cache manager.
        
        Args:
            config: Configuration dict with:
                - ttl_seconds: Default TTL (0 = no expiry)
                - max_entries: Max number of entries (0 = unlimited)
                - max_size_mb: Max cache size in MB (0 = unlimited)
                - eviction_policy: 'lru', 'lfu', 'ttl' (default: 'lru')
        """
        self.config = config or {}
        
        self.default_ttl = float(self.config.get('ttl_seconds', 300))
        self.max_entries = int(self.config.get('max_entries', 1000))
        self.max_size_bytes = int(self.config.get('max_size_mb', 100)) * 1024 * 1024
        self.eviction_policy = self.config.get('eviction_policy', 'lru')
        
        # Storage
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        
        # Metrics
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.expired_removals = 0
        self.current_size_bytes = 0
        
        # Thread safety
        self.lock = threading.RLock()
        
        logger.info(
            f"Cache initialized: TTL={self.default_ttl}s, "
            f"MaxEntries={self.max_entries}, MaxSize={self.max_size_bytes/1024/1024:.1f}MB, "
            f"Policy={self.eviction_policy}"
        )
    
    def _make_key(self, *args, **kwargs) -> str:
        """Generate cache key from arguments."""
        key_data = f"{args}_{sorted(kwargs.items())}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def get(self, key: str) -> Tuple[Optional[Any], bool]:
        """
        Get value from cache.
        
        Returns:
            (value, hit) - value is None if miss, hit is True/False
        """
        with self.lock:
            entry = self.cache.get(key)
            
            if entry is None:
                self.misses += 1
                return None, False
            
            if entry.is_expired():
                self._remove_entry(key)
                self.misses += 1
                self.expired_removals += 1
                return None, False
            
            # Move to end for LRU
            if self.eviction_policy == 'lru':
                self.cache.move_to_end(key)
            
            self.hits += 1
            return entry.access(), True
    
    def set(self, key: str, value: Any, ttl: Optional[float] = None):
        """
        Store value in cache.
        
        Args:
            key: Cache key
            value: Value to store
            ttl: TTL in seconds (None = use default)
        """
        with self.lock:
            # Use default TTL if not specified
            ttl = ttl if ttl is not None else self.default_ttl
            
            # Remove existing entry if present
            if key in self.cache:
                self._remove_entry(key)
            
            # Create new entry
            entry = CacheEntry(key, value, ttl)
            
            # Check if we need to evict
            while self._should_evict(entry.size_bytes):
                self._evict_one()
            
            # Add to cache
            self.cache[key] = entry
            self.current_size_bytes += entry.size_bytes
    
    def _should_evict(self, new_entry_size: int) -> bool:
        """Check if eviction needed for new entry."""
        # Check entry count limit (use > to allow exactly max_entries items)
        if self.max_entries > 0 and len(self.cache) > self.max_entries:
            return True
        
        # Check size limit
        if self.max_size_bytes > 0:
            if self.current_size_bytes + new_entry_size > self.max_size_bytes:
                return True
        
        return False
    
    def _evict_one(self):
        """Evict one entry based on policy."""
        if not self.cache:
            return
        
        if self.eviction_policy == 'lru':
            # Remove least recently used (first in OrderedDict)
            key = next(iter(self.cache))
        elif self.eviction_policy == 'lfu':
            # Remove least frequently used
            key = min(self.cache.keys(), key=lambda k: self.cache[k].hits)
        elif self.eviction_policy == 'ttl':
            # Remove oldest by creation time
            key = min(self.cache.keys(), key=lambda k: self.cache[k].created_at)
        else:
            # Fallback to LRU
            key = next(iter(self.cache))
        
        self._remove_entry(key)
        self.evictions += 1
    
    def _remove_entry(self, key: str):
        """Remove entry and update size."""
        entry = self.cache.pop(key, None)
        if entry:
            self.current_size_bytes = max(0, self.current_size_bytes - entry.size_bytes)
    
    def clear(self):
        """Clear all entries."""
        with self.lock:
            self.cache.clear()
            self.current_size_bytes = 0
            logger.info("Cache cleared")
    
    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        with self.lock:
            to_remove = [k for k, v in self.cache.items() if v.is_expired()]
            for key in to_remove:
                self._remove_entry(key)
                self.expired_removals += 1
            return len(to_remove)
    
    def get_stats(self) -> dict:
        """Get cache statistics."""
        with self.lock:
            total_requests = self.hits + self.misses
            hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0
            
            # Entry stats
            if self.cache:
                entries = list(self.cache.values())
                avg_age = sum(e.age_seconds() for e in entries) / len(entries)
                avg_hits = sum(e.hits for e in entries) / len(entries)
            else:
                avg_age = 0
                avg_hits = 0
            
            return {
                'enabled': self.default_ttl > 0,
                'size': len(self.cache),
                'max_entries': self.max_entries,
                'size_bytes': self.current_size_bytes,
                'size_mb': round(self.current_size_bytes / 1024 / 1024, 2),
                'max_size_mb': self.max_size_bytes / 1024 / 1024,
                'hits': self.hits,
                'misses': self.misses,
                'hit_rate': round(hit_rate, 2),
                'evictions': self.evictions,
                'expired_removals': self.expired_removals,
                'avg_entry_age_seconds': round(avg_age, 1),
                'avg_entry_hits': round(avg_hits, 1),
                'eviction_policy': self.eviction_policy,
                'default_ttl_seconds': self.default_ttl
            }
    
    def get_top_entries(self, n: int = 10) -> list:
        """Get top N most accessed entries."""
        with self.lock:
            sorted_entries = sorted(
                self.cache.items(),
                key=lambda x: x[1].hits,
                reverse=True
            )[:n]
            
            return [{
                'key': key,
                'hits': entry.hits,
                'age_seconds': round(entry.age_seconds(), 1),
                'size_bytes': entry.size_bytes
            } for key, entry in sorted_entries]


# Convenience function to create cache from config
def create_cache_manager(config: dict) -> EnhancedCacheManager:
    """Create cache manager from config dict."""
    cache_config = {
        'ttl_seconds': config.get('performance', {}).get('cache_ttl_seconds', 300),
        'max_entries': config.get('performance', {}).get('cache_max_entries', 1000),
        'max_size_mb': config.get('performance', {}).get('cache_max_size_mb', 100),
        'eviction_policy': config.get('performance', {}).get('cache_eviction_policy', 'lru')
    }
    return EnhancedCacheManager(cache_config)

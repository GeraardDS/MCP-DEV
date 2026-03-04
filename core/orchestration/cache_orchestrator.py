"""Cache management orchestration."""
import logging
import time
from typing import Any, Dict, List, Optional
from .base_orchestrator import BaseOrchestrator

logger = logging.getLogger(__name__)

class CacheOrchestrator(BaseOrchestrator):
    """Handles cache management operations."""

    def warm_query_cache(self, connection_state, queries: List[str], runs: Optional[int] = 1, clear_cache: bool = False) -> Dict[str, Any]:
        """Warm query cache by executing queries repeatedly."""
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()
        executor = connection_state.query_executor
        if not executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')

        r = max(1, int(runs or 1))
        stats: List[Dict[str, Any]] = []
        if clear_cache:
            try:
                executor.flush_cache()
            except Exception:
                pass
        for q in queries or []:
            times = []
            ok = True
            for _ in range(r):
                start = time.time()
                res = executor.validate_and_execute_dax(q, 0, bypass_cache=False)
                ok = ok and bool(res.get('success'))
                times.append((time.time() - start) * 1000)
            stats.append({'query': q, 'success': ok, 'runs': r, 'avg_ms': round(sum(times)/len(times), 2) if times else 0})
        return {'success': True, 'warmed': len(stats), 'results': stats}

    def set_cache_policy(self, connection_state, ttl_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Set cache TTL policy."""
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()
        executor = connection_state.query_executor
        if not executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')
        changed = {}
        if isinstance(ttl_seconds, int) and ttl_seconds >= 0:
            executor.cache_ttl_seconds = ttl_seconds
            executor.flush_cache()
            changed['cache_ttl_seconds'] = ttl_seconds
        return {'success': True, 'changed': changed, 'current': {'cache_ttl_seconds': executor.cache_ttl_seconds}}

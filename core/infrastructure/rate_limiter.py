"""
Rate limiting for Power BI MCP Server.
Prevents overwhelming Desktop with rapid queries.
"""

import time
import threading
from collections import deque, defaultdict
from typing import Optional, Dict, Tuple
import logging

logger = logging.getLogger("mcp_powerbi_finvision.rate_limiter")


class RateLimiter:
    """
    Token bucket rate limiter with per-tool and global limits.
    Thread-safe implementation.
    """
    
    def __init__(self, config: Optional[dict] = None):
        """
        Initialize rate limiter.

        Args:
            config: Configuration dict with:
                - enabled: Whether rate limiting is enabled (default: True)
                - global_calls_per_second: Max calls/sec across all tools (default: 10)
                - global_burst: Max burst size (default: 20)
                - tool_limits: Dict of tool_name -> calls_per_second
                - tool_bursts: Dict of tool_name -> burst_size
        """
        self.config = config or {}

        # Check if rate limiting is enabled
        self.enabled = self.config.get('enabled', True)

        # Global limits
        self.global_rate = float(self.config.get('global_calls_per_second', 10))
        self.global_burst = int(self.config.get('global_burst', 20))
        self.global_tokens = float(self.global_burst)
        self.global_last_update = time.time()

        # Per-tool limits
        self.tool_limits = self.config.get('tool_limits', {})
        self.tool_bursts = self.config.get('tool_bursts', {})
        self.tool_tokens: Dict[str, float] = {}
        self.tool_last_update: Dict[str, float] = {}

        # Request tracking for metrics
        self.request_history = deque(maxlen=1000)
        self.tool_request_counts = defaultdict(int)
        self.tool_throttle_counts = defaultdict(int)

        # Thread safety
        self.lock = threading.RLock()

        status = "enabled" if self.enabled else "disabled"
        logger.info(f"Rate limiter {status}: {self.global_rate} calls/sec (burst {self.global_burst})")
    
    def _refill_tokens(self, current_time: float):
        """Refill token buckets based on elapsed time."""
        # Refill global bucket
        elapsed = current_time - self.global_last_update
        tokens_to_add = elapsed * self.global_rate
        self.global_tokens = min(self.global_burst, self.global_tokens + tokens_to_add)
        self.global_last_update = current_time
    
    def _refill_tool_tokens(self, tool_name: str, current_time: float):
        """Refill tokens for specific tool."""
        if tool_name not in self.tool_limits:
            return
        
        rate = self.tool_limits[tool_name]
        burst = self.tool_bursts.get(tool_name, int(rate * 2))
        
        if tool_name not in self.tool_last_update:
            self.tool_tokens[tool_name] = float(burst)
            self.tool_last_update[tool_name] = current_time
            return
        
        elapsed = current_time - self.tool_last_update[tool_name]
        tokens_to_add = elapsed * rate
        self.tool_tokens[tool_name] = min(burst, self.tool_tokens[tool_name] + tokens_to_add)
        self.tool_last_update[tool_name] = current_time
    
    def acquire(self, tool_name: str, cost: float = 1.0, 
                timeout: Optional[float] = None) -> Tuple[bool, Optional[float]]:
        """
        Try to acquire tokens for a request.
        
        Args:
            tool_name: Name of the tool being called
            cost: Token cost of this request (default 1.0)
            timeout: Max seconds to wait for tokens (None = no wait)
        
        Returns:
            (acquired, wait_time) - wait_time is None if acquired, else seconds to wait
        """
        start_time = time.time()

        while True:
            sleep_duration = None
            with self.lock:
                current_time = time.time()

                # Refill buckets
                self._refill_tokens(current_time)
                self._refill_tool_tokens(tool_name, current_time)

                # Check global limit
                if self.global_tokens >= cost:
                    # Check tool-specific limit (if exists)
                    if tool_name in self.tool_limits:
                        if self.tool_tokens.get(tool_name, 0) >= cost:
                            # Acquire from both buckets
                            self.global_tokens -= cost
                            self.tool_tokens[tool_name] -= cost
                            self._record_request(tool_name, current_time)
                            return True, None
                        else:
                            # Tool limit exceeded
                            wait_time = self._calculate_wait_time(tool_name, cost, current_time)
                    else:
                        # No tool-specific limit, just consume global
                        self.global_tokens -= cost
                        self._record_request(tool_name, current_time)
                        return True, None
                else:
                    # Global limit exceeded
                    wait_time = self._calculate_global_wait_time(cost, current_time)

                # If no timeout or timeout exceeded, return throttled
                if timeout is None or (current_time - start_time) >= timeout:
                    self.tool_throttle_counts[tool_name] += 1
                    logger.warning(f"Rate limit exceeded for {tool_name} (wait: {wait_time:.2f}s)")
                    return False, wait_time

                sleep_duration = min(0.1, wait_time)

            # Sleep outside the lock to avoid blocking other threads
            time.sleep(sleep_duration)

    # --- Convenience API expected by server wrapper ---
    def allow_request(self, tool_name: str, cost: float = 1.0) -> bool:
        """Non-blocking check-and-consume for a request.

        Returns True if tokens were available and consumed; False if throttled.
        """
        # Fast path: If rate limiting is disabled, always allow
        if not self.enabled:
            return True
        acquired, _ = self.acquire(tool_name, cost=cost, timeout=0.0)
        return acquired

    def get_retry_after(self, tool_name: str, cost: float = 1.0) -> float:
        """Estimate seconds until the next request of given cost would pass.

        Does not consume tokens.
        """
        with self.lock:
            now = time.time()
            # Refill to current time without consuming
            self._refill_tokens(now)
            self._refill_tool_tokens(tool_name, now)
            # Compute deficits
            global_deficit = max(0.0, cost - self.global_tokens)
            global_wait = global_deficit / self.global_rate if self.global_rate > 0 else float('inf')
            if tool_name in self.tool_limits:
                tool_deficit = max(0.0, cost - self.tool_tokens.get(tool_name, 0.0))
                tool_rate = float(self.tool_limits.get(tool_name, self.global_rate) or 0.0)
                tool_wait = tool_deficit / tool_rate if tool_rate > 0 else float('inf')
                wait = max(0.0, max(global_wait, tool_wait))
            else:
                wait = max(0.0, global_wait)
            # Bound the value to something reasonable for clients
            try:
                return round(wait, 2)
            except Exception:
                return float(wait)
    
    def _calculate_wait_time(self, tool_name: str, cost: float, current_time: float) -> float:
        """Calculate seconds to wait for tool-specific tokens."""
        needed = cost - self.tool_tokens.get(tool_name, 0)
        rate = self.tool_limits.get(tool_name, self.global_rate)
        return max(0.0, needed / rate)
    
    def _calculate_global_wait_time(self, cost: float, current_time: float) -> float:
        """Calculate seconds to wait for global tokens."""
        needed = cost - self.global_tokens
        return max(0.0, needed / self.global_rate)
    
    def _record_request(self, tool_name: str, timestamp: float):
        """Record request for metrics."""
        self.request_history.append((tool_name, timestamp))
        self.tool_request_counts[tool_name] += 1
    
    def get_stats(self) -> dict:
        """Get rate limiter statistics."""
        with self.lock:
            current_time = time.time()
            self._refill_tokens(current_time)
            
            # Calculate requests in last minute
            recent = [r for r in self.request_history if (current_time - r[1]) <= 60]
            
            return {
                'global_tokens_available': round(self.global_tokens, 2),
                'global_rate_limit': self.global_rate,
                'global_burst': self.global_burst,
                'requests_last_minute': len(recent),
                'total_requests': sum(self.tool_request_counts.values()),
                'total_throttled': sum(self.tool_throttle_counts.values()),
                'tool_counts': dict(self.tool_request_counts),
                'tool_throttled': dict(self.tool_throttle_counts),
                'tool_tokens': {k: round(v, 2) for k, v in self.tool_tokens.items()}
            }
    
    def reset_stats(self):
        """Reset statistics (preserves token counts)."""
        with self.lock:
            self.request_history.clear()
            self.tool_request_counts.clear()
            self.tool_throttle_counts.clear()


# Default rate limit profiles

RATE_LIMIT_PROFILES = {
    'conservative': {
        'global_calls_per_second': 5,
        'global_burst': 10,
        'tool_limits': {
            'run_dax': 2,
            'analyze_model_bpa': 0.5,  # 1 every 2 seconds
            'full_analysis': 0.2,  # 1 every 5 seconds
            'analyze_queries_batch': 1,
        },
        'tool_bursts': {
            'run_dax': 5,
            'analyze_model_bpa': 2,
            'full_analysis': 1,
            'analyze_queries_batch': 3,
        }
    },
    'balanced': {
        'global_calls_per_second': 10,
        'global_burst': 20,
        'tool_limits': {
            'run_dax': 5,
            'analyze_model_bpa': 1,
            'full_analysis': 0.5,
            'analyze_queries_batch': 2,
        },
        'tool_bursts': {
            'run_dax': 10,
            'analyze_model_bpa': 3,
            'full_analysis': 2,
            'analyze_queries_batch': 5,
        }
    },
    'aggressive': {
        'global_calls_per_second': 20,
        'global_burst': 40,
        'tool_limits': {
            'analyze_model_bpa': 2,
            'full_analysis': 1,
        },
        'tool_bursts': {
            'analyze_model_bpa': 5,
            'full_analysis': 3,
        }
    },
    'development': {
        'global_calls_per_second': 100,  # Effectively unlimited for dev
        'global_burst': 200,
    }
}


def create_rate_limiter(profile: str = 'balanced', custom_config: Optional[dict] = None) -> RateLimiter:
    """
    Create a rate limiter with a named profile.
    
    Args:
        profile: One of 'conservative', 'balanced', 'aggressive', 'development'
        custom_config: Optional overrides
    
    Returns:
        Configured RateLimiter instance
    """
    config = RATE_LIMIT_PROFILES.get(profile, RATE_LIMIT_PROFILES['balanced']).copy()
    
    if custom_config:
        config.update(custom_config)
    
    return RateLimiter(config)

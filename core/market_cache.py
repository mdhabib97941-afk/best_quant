"""
Titan Quant System - Shared In-Memory TTL Cache
===============================================
Thread-safe in-memory cache with Time-To-Live (TTL) expiration to eliminate
redundant external exchange REST polling across independent modules.
"""

import time
import threading
import urllib.request
import json
from typing import Any, Callable, Optional, Dict, Tuple

# Pre-configured standard TTL durations (in seconds)
TTL_TICKER = 3       # Spot / Perp last prices
TTL_DEPTH = 2        # L2 Depth snapshots
TTL_ORDERBOOK = 2    # L2 Depth / Orderbook snapshots
TTL_COINBASE = 5     # Coinbase spot & L2 flow
TTL_KLINES = 15      # 5m / 15m / 1h / 4h klines
TTL_OPTIONS = 60     # Deribit options summaries
TTL_DERIBIT = 60     # Deribit book summaries
TTL_DERIVATIVES = 60 # Deribit / Futures derivatives summaries
TTL_CME = 120        # CME futures basis

class MarketCache:
    """Thread-safe TTL cache store."""
    def __init__(self):
        self._store: Dict[str, Tuple[Any, float]] = {}
        self._lock = threading.RLock()
        self._key_locks: Dict[str, threading.Lock] = {}

    def get(self, key: str) -> Optional[Any]:
        """Retrieve an entry if present and not expired."""
        with self._lock:
            if key not in self._store:
                return None
            val, expiry = self._store[key]
            if time.time() > expiry:
                del self._store[key]
                return None
            return val

    def set(self, key: str, value: Any, ttl_seconds: float = 15.0) -> None:
        """Store a value with an expiration timestamp."""
        with self._lock:
            expiry = time.time() + max(0.1, float(ttl_seconds))
            self._store[key] = (value, expiry)

    def delete(self, key: str) -> bool:
        """Delete a key from the cache if present."""
        with self._lock:
            self._key_locks.pop(key, None)
            if key in self._store:
                del self._store[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._store.clear()
            self._key_locks.clear()

    def get_or_set(self, key: str, fetch_fn: Callable[[], Any], ttl_seconds: float = 15.0) -> Any:
        """
        Retrieve value from cache, or invoke fetch_fn(), store result, and return.
        Thread-safe under key-specific lock to prevent thundering herd without
        holding global cache lock during slow network execution.
        """
        cached = self.get(key)
        if cached is not None:
            return cached

        with self._lock:
            if key not in self._key_locks:
                self._key_locks[key] = threading.Lock()
            key_lock = self._key_locks[key]

        with key_lock:
            cached = self.get(key)
            if cached is not None:
                return cached
            val = fetch_fn()
            if val is not None:
                self.set(key, val, ttl_seconds)
            return val

    def cached_get_json(self, url: str, ttl_seconds: float = TTL_KLINES, timeout: float = 6.0, headers: Optional[dict] = None, ttl: Optional[float] = None) -> Any:
        """
        Fetch JSON from a URL with caching via this MarketCache instance.
        """
        eff_ttl = ttl if ttl is not None else ttl_seconds
        return cached_get_json(url, ttl_seconds=eff_ttl, timeout=timeout, headers=headers)

# Global singleton cache instance
_GLOBAL_CACHE = MarketCache()

def get_market_cache() -> MarketCache:
    """Return the global MarketCache instance."""
    return _GLOBAL_CACHE

def cached_get_json(url: str, ttl_seconds: float = TTL_KLINES, timeout: float = 6.0, headers: Optional[dict] = None, ttl: Optional[float] = None) -> Any:
    """
    Fetch JSON from a URL with caching.
    Returns parsed JSON object, or None if request fails.
    """
    eff_ttl = ttl if ttl is not None else ttl_seconds
    cache = get_market_cache()
    cached = cache.get(url)
    if cached is not None:
        return cached

    req_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) TitanQuant/2.0'}
    if headers:
        req_headers.update(headers)

    try:
        req = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data is not None:
                cache.set(url, data, eff_ttl)
            return data
    except Exception:
        return None

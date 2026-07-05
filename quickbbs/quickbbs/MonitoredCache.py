"""
Thread-safe LRU/TTL caches with optional hit/miss monitoring.

cachetools caches are NOT thread-safe — the library documents that access to
a shared cache from multiple threads must be properly synchronized. QuickBBS
shares its caches across watchdog observer threads, debounce timer threads,
task-runner threads, and request worker threads, so every cache class in this
module serializes access with an internal reentrant lock.

Monitoring provides cache statistics for performance analysis. Enable by
setting CACHE_MONITORING = True in quickbbs/quickbbs_settings.py.

Usage:
    from quickbbs.models import directoryindex_cache, fileindex_cache

    # After running the application, check stats:
    print(directoryindex_cache.stats())
    print(fileindex_cache.stats())

    # Or visit the endpoint (when CACHE_MONITORING = True):
    # http://localhost:8888/cache_stats/

Interpretation:
    - Hit rate >80%: Cache size is adequate
    - Hit rate 60-80%: Consider increasing cache size
    - Hit rate <60%: Increase cache size
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any

from cachetools import Cache, LRUCache, TTLCache

# Sentinel distinguishing "no default supplied" from an explicit None default.
_MISSING: Any = object()


class _ThreadSafeCacheMixin(Cache):
    """
    Mixin that serializes cachetools cache access with a reentrant lock.

    cachetools requires callers to synchronize shared-cache access. The lock
    must be reentrant: ``__setitem__`` re-enters ``popitem`` during eviction,
    and the compound operations re-enter the locked dunders.

    The compound operations (``get``, ``pop``, ``setdefault``, ``clear``) are
    overridden because they are check-then-act sequences that stay racy even
    when each primitive operation is individually locked — e.g. two threads
    calling ``pop(key, None)`` can both find the key, after which the loser
    raises ``KeyError`` despite the default.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Initialize the underlying cache and its lock.

        Args:
            *args: Positional arguments for the concrete cachetools base
                (e.g. maxsize, or maxsize/ttl for TTLCache)
            **kwargs: Keyword arguments for the concrete cachetools base
        """
        super().__init__(*args, **kwargs)
        self._rlock = threading.RLock()

    # -- primitive operations ------------------------------------------

    def __getitem__(self, key: Any) -> Any:
        with self._rlock:
            return super().__getitem__(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        # Eviction re-enters popitem(); the RLock makes that safe.
        with self._rlock:
            super().__setitem__(key, value)

    def __delitem__(self, key: Any) -> None:
        with self._rlock:
            super().__delitem__(key)

    def __contains__(self, key: Any) -> bool:
        with self._rlock:
            return super().__contains__(key)

    def __len__(self) -> int:
        with self._rlock:
            return super().__len__()

    def __iter__(self) -> Iterator[Any]:
        # Snapshot under the lock so callers can iterate (including
        # list(cache.keys())) without racing concurrent mutation.
        with self._rlock:
            return iter(list(super().__iter__()))

    # -- compound operations (check-then-act) --------------------------

    def get(self, key: Any, default: Any = None) -> Any:
        """
        Return the value for key if present, else default (atomic).

        Args:
            key: Cache key to look up
            default: Value returned when key is absent

        Returns:
            Cached value, or default when key is absent
        """
        with self._rlock:
            return super().get(key, default)

    def pop(self, key: Any, default: Any = _MISSING) -> Any:
        """
        Remove key and return its value (atomic).

        Never raises KeyError when a default is supplied, even under
        concurrent pops of the same key.

        Args:
            key: Cache key to remove
            default: Value returned when key is absent

        Returns:
            Removed value, or default when key is absent

        Raises:
            KeyError: If key is absent and no default was supplied
        """
        with self._rlock:
            if default is _MISSING:
                return super().pop(key)
            return super().pop(key, default)

    def setdefault(self, key: Any, default: Any = None) -> Any:
        """
        Return the value for key, inserting default if absent (atomic).

        Args:
            key: Cache key to look up
            default: Value stored and returned when key is absent

        Returns:
            Existing cached value, or default when key was absent
        """
        with self._rlock:
            return super().setdefault(key, default)

    def popitem(self) -> tuple[Any, Any]:
        """
        Remove and return an item per the cache's eviction policy (atomic).

        Returns:
            Tuple of (key, value) for the evicted item

        Raises:
            KeyError: If the cache is empty
        """
        with self._rlock:
            return super().popitem()

    def clear(self) -> None:
        """Remove all items from the cache (atomic)."""
        with self._rlock:
            super().clear()


class ThreadSafeLRUCache(_ThreadSafeCacheMixin, LRUCache):
    """cachetools LRUCache with an internal RLock; see _ThreadSafeCacheMixin."""


class ThreadSafeTTLCache(_ThreadSafeCacheMixin, TTLCache):
    """cachetools TTLCache with an internal RLock; see _ThreadSafeCacheMixin."""

    def expire(self, time: float | None = None) -> list[tuple[Any, Any]]:
        """
        Remove expired items from the cache (atomic).

        Args:
            time: Expiration cutoff; defaults to the cache's timer()

        Returns:
            List of the expired (key, value) pairs
        """
        with self._rlock:
            return list(super().expire(time))


class MonitoredLRUCache(ThreadSafeLRUCache):
    """
    Thread-safe LRU cache with hit/miss tracking for performance analysis.

    The hit/miss counters are incremented outside the lock, so under heavy
    concurrency they are approximate (accuracy-only — never affects cached
    data integrity).
    """

    def __init__(self, maxsize: int, name: str = "cache"):
        """
        Initialize monitored cache.

        Args:
            maxsize: Maximum number of items to store
            name: Cache name for identification in stats
        """
        super().__init__(maxsize)
        self.hits = 0
        self.misses = 0
        self.name = name

    def __getitem__(self, key: Any) -> Any:
        try:
            value = super().__getitem__(key)
            self.hits += 1
            return value
        except KeyError:
            self.misses += 1
            raise

    @property
    def hit_rate(self) -> float:
        """Return hit rate as a percentage (0-100)."""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    def stats(self) -> dict:
        """
        Return cache statistics.

        Returns:
            Dictionary with cache name, hits, misses, hit rate, size, and maxsize
        """
        return {
            "name": self.name,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{self.hit_rate:.1f}%",
            "size": len(self),
            "maxsize": self.maxsize,
        }

    def reset_stats(self) -> None:
        """Reset hit/miss counters to zero."""
        self.hits = 0
        self.misses = 0


def create_cache(maxsize: int, name: str, monitored: bool = False) -> LRUCache:
    """
    Factory function to create either monitored or standard LRU cache.

    Both variants are thread-safe (internally locked); the monitored variant
    additionally tracks hit/miss statistics.

    Args:
        maxsize: Maximum number of items to store
        name: Cache name for identification
        monitored: If True, create MonitoredLRUCache; otherwise ThreadSafeLRUCache

    Returns:
        ThreadSafeLRUCache or MonitoredLRUCache instance
    """
    if monitored:
        return MonitoredLRUCache(maxsize, name=name)
    return ThreadSafeLRUCache(maxsize)

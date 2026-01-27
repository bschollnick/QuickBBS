"""
Monitored LRU Cache with hit/miss tracking.

Provides cache statistics for performance analysis. Enable by setting
CACHE_MONITORING = True in quickbbs/models.py.

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

from cachetools import LRUCache


class MonitoredLRUCache(LRUCache):
    """LRU Cache with hit/miss tracking for performance analysis."""

    __slots__ = ("hits", "misses", "name")

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

    def __getitem__(self, key):
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

    Args:
        maxsize: Maximum number of items to store
        name: Cache name for identification
        monitored: If True, create MonitoredLRUCache; otherwise standard LRUCache

    Returns:
        LRUCache or MonitoredLRUCache instance
    """
    if monitored:
        return MonitoredLRUCache(maxsize, name=name)
    return LRUCache(maxsize)

"""CacheStatisticsTracking: hit rate and string form."""

from __future__ import annotations

import pytest
from django.test import TestCase

from cache_watcher.models import (
    CacheStatisticsTracking,
)

pytestmark = pytest.mark.api


class TestCacheStatisticsTracking(TestCase):
    """Tests for CacheStatisticsTracking model and properties."""

    def _make_stat(self, hits: int, misses: int) -> CacheStatisticsTracking:
        stat = CacheStatisticsTracking()
        stat.hits = hits
        stat.misses = misses
        return stat

    def test_hit_rate_zero_when_no_requests(self):
        """Hit rate zero when no requests."""
        stat = self._make_stat(0, 0)
        assert stat.hit_rate == 0.0

    def test_hit_rate_100_when_all_hits(self):
        """Hit rate 100 when all hits."""
        stat = self._make_stat(100, 0)
        assert stat.hit_rate == 100.0

    def test_hit_rate_0_when_all_misses(self):
        """Hit rate 0 when all misses."""
        stat = self._make_stat(0, 100)
        assert stat.hit_rate == 0.0

    def test_hit_rate_50_percent(self):
        """Hit rate 50 percent."""
        stat = self._make_stat(50, 50)
        assert stat.hit_rate == 50.0

    def test_hit_rate_75_percent(self):
        """Hit rate 75 percent."""
        stat = self._make_stat(75, 25)
        assert stat.hit_rate == 75.0

    def test_str_shows_cache_name(self):
        """Str shows cache name."""
        stat = CacheStatisticsTracking()
        stat.cache_name = "fileindex"
        stat.hits = 10
        stat.misses = 0
        assert "fileindex" in str(stat)

    def test_str_shows_hit_rate(self):
        """Str shows hit rate."""
        stat = CacheStatisticsTracking()
        stat.cache_name = "test_cache"
        stat.hits = 80
        stat.misses = 20
        result = str(stat)
        assert "80.0%" in result

    def test_str_shows_na_when_no_requests(self):
        """Str shows na when no requests."""
        stat = CacheStatisticsTracking()
        stat.cache_name = "empty"
        stat.hits = 0
        stat.misses = 0
        assert "n/a" in str(stat)

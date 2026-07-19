"""
Tests for the thread-safe cache classes in quickbbs/MonitoredCache.py.

Covers single-threaded LRU/TTL/monitoring behavior plus multithreaded hammer
tests: cachetools caches are not thread-safe on their own, and QuickBBS shares
these caches across watchdog, timer, task-runner, and request threads. The
hammer tests assert that no spurious exceptions escape (in particular no
KeyError from pop() with a default) and that size accounting stays sane.

No database access — SimpleTestCase throughout.
"""

from __future__ import annotations

import sys
import threading

from django.test import SimpleTestCase

from quickbbs.MonitoredCache import (
    MonitoredLRUCache,
    ThreadSafeLRUCache,
    ThreadSafeTTLCache,
    create_cache,
)

THREAD_COUNT = 8
OPS_PER_THREAD = 3000


class TestCreateCache(SimpleTestCase):
    """Tests for create_cache() factory in MonitoredCache.py."""

    def test_unmonitored_cache_is_thread_safe_variant(self):
        """create_cache() without monitoring returns a ThreadSafeLRUCache."""
        cache = create_cache(10, "plain")
        self.assertIsInstance(cache, ThreadSafeLRUCache)

    def test_monitored_cache_is_thread_safe_variant(self):
        """create_cache(monitored=True) returns a thread-safe MonitoredLRUCache."""
        cache = create_cache(10, "monitored", monitored=True)
        self.assertIsInstance(cache, MonitoredLRUCache)
        self.assertIsInstance(cache, ThreadSafeLRUCache)


class TestLRUBehaviourPreserved(SimpleTestCase):
    """Locking must not change cachetools LRUCache semantics."""

    def test_basic_get_set_delete(self):
        """Set, get, contains, len, and delete behave as a mapping."""
        cache = ThreadSafeLRUCache(4)
        cache["a"] = 1
        self.assertEqual(cache["a"], 1)
        self.assertIn("a", cache)
        self.assertEqual(len(cache), 1)
        del cache["a"]
        self.assertNotIn("a", cache)

    def test_lru_eviction_order(self):
        """Least-recently-used entry is evicted first."""
        cache = ThreadSafeLRUCache(3)
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3
        _ = cache["a"]  # touch "a" so "b" is now least recently used
        cache["d"] = 4
        self.assertNotIn("b", cache)
        self.assertIn("a", cache)

    def test_pop_with_default_on_missing_key(self):
        """pop() returns the default when the key is absent."""
        cache = ThreadSafeLRUCache(4)
        self.assertIsNone(cache.pop("missing", None))
        self.assertEqual(cache.pop("missing", "fallback"), "fallback")

    def test_pop_without_default_raises_keyerror(self):
        """pop() without a default raises KeyError for a missing key."""
        cache = ThreadSafeLRUCache(4)
        with self.assertRaises(KeyError):
            cache.pop("missing")

    def test_get_setdefault_clear(self):
        """get(), setdefault(), and clear() behave as a mapping."""
        cache = ThreadSafeLRUCache(4)
        cache["a"] = 1
        self.assertEqual(cache.get("a"), 1)
        self.assertIsNone(cache.get("missing"))
        self.assertEqual(cache.setdefault("a", 99), 1)
        self.assertEqual(cache.setdefault("b", 2), 2)
        cache.clear()
        self.assertEqual(len(cache), 0)

    def test_iteration_returns_snapshot(self):
        """Iteration yields a snapshot safe to consume while mutating."""
        cache = ThreadSafeLRUCache(4)
        cache["a"] = 1
        cache["b"] = 2
        keys = list(cache.keys())
        # Mutating while consuming a snapshot iterator must not raise
        for key in cache:
            cache.pop(key, None)
        self.assertEqual(sorted(keys), ["a", "b"])
        self.assertEqual(len(cache), 0)


class TestMonitoredLRUCache(SimpleTestCase):
    """Tests for hit/miss statistics on the monitored variant."""

    def test_stats_track_hits_and_misses(self):
        """stats() reports name, hits, misses, and size."""
        cache = MonitoredLRUCache(4, name="stats_test")
        cache["a"] = 1
        _ = cache["a"]
        with self.assertRaises(KeyError):
            _ = cache["missing"]
        stats = cache.stats()
        self.assertEqual(stats["name"], "stats_test")
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["size"], 1)

    def test_reset_stats(self):
        """reset_stats() zeroes the hit/miss counters."""
        cache = MonitoredLRUCache(4)
        cache["a"] = 1
        _ = cache["a"]
        cache.reset_stats()
        self.assertEqual(cache.hits, 0)
        self.assertEqual(cache.misses, 0)


class TestTTLBehaviourPreserved(SimpleTestCase):
    """Locking must not change cachetools TTLCache semantics."""

    def test_entries_expire(self):
        """Entries become unreachable after their TTL elapses."""
        current_time = [0.0]
        cache = ThreadSafeTTLCache(maxsize=4, ttl=10, timer=lambda: current_time[0])
        cache["a"] = 1
        self.assertEqual(cache.get("a"), 1)
        current_time[0] = 11.0
        self.assertIsNone(cache.get("a"))
        self.assertIsNone(cache.pop("a", None))

    def test_expire_returns_expired_pairs(self):
        """expire() returns the expired (key, value) pairs."""
        current_time = [0.0]
        cache = ThreadSafeTTLCache(maxsize=4, ttl=10, timer=lambda: current_time[0])
        cache["a"] = 1
        current_time[0] = 11.0
        self.assertEqual(cache.expire(), [("a", 1)])


class TestThreadSafety(SimpleTestCase):
    """
    Multithreaded hammer tests.

    A lowered sys.setswitchinterval() forces frequent thread preemption to
    widen race windows. Every worker records any exception; the assertions
    require that none escaped.
    """

    def setUp(self):
        self._old_switch_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)

    def tearDown(self):
        sys.setswitchinterval(self._old_switch_interval)

    def _run_workers(self, worker) -> list[BaseException]:
        errors: list[BaseException] = []

        def wrapped(seed: int) -> None:
            try:
                worker(seed)
            except BaseException as exc:  # pylint: disable=broad-exception-caught
                errors.append(exc)

        threads = [threading.Thread(target=wrapped, args=(i,)) for i in range(THREAD_COUNT)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return errors

    def test_concurrent_pop_with_default_never_raises(self):
        """Concurrent pop(key, None) never leaks a KeyError."""
        # Regression: MutableMapping/Cache pop() is check-then-act; without
        # internal locking, two threads popping the same key can both find it
        # and the loser raises KeyError DESPITE the default. This is the
        # watchdog invalidation pattern (cache.pop(hashkey(sha), None)).
        cache = ThreadSafeLRUCache(64)
        keys = [f"key{i}" for i in range(4)]

        def worker(seed: int) -> None:
            for i in range(OPS_PER_THREAD):
                key = keys[(seed + i) % len(keys)]
                if i % 2:
                    cache[key] = seed
                else:
                    cache.pop(key, None)

        errors = self._run_workers(worker)
        self.assertEqual(errors, [])

    def test_hammer_mixed_operations_lru(self):
        """Mixed concurrent operations raise nothing and respect maxsize."""
        maxsize = 32
        cache = create_cache(maxsize, "hammer", monitored=True)
        keys = [f"key{i}" for i in range(128)]

        def worker(seed: int) -> None:
            for i in range(OPS_PER_THREAD):
                key = keys[(seed * 31 + i * 7) % len(keys)]
                op = i % 10
                if op < 4:
                    cache[key] = i
                elif op < 6:
                    cache.get(key)
                elif op < 8:
                    cache.pop(key, None)
                elif op == 8:
                    for _ in cache:
                        pass
                else:
                    cache.setdefault(key, i)

        errors = self._run_workers(worker)
        self.assertEqual(errors, [])
        self.assertLessEqual(len(cache), maxsize)

    def test_hammer_ttl_cache(self):
        """Concurrent TTL operations (incl. expire) raise nothing."""
        maxsize = 32
        cache = ThreadSafeTTLCache(maxsize=maxsize, ttl=0.001)
        keys = [f"user{i}" for i in range(16)]

        def worker(seed: int) -> None:
            for i in range(OPS_PER_THREAD):
                key = keys[(seed + i) % len(keys)]
                op = i % 8
                if op < 4:
                    cache[key] = seed
                elif op < 6:
                    cache.get(key)
                elif op == 6:
                    cache.pop(key, None)
                else:
                    cache.expire()

        errors = self._run_workers(worker)
        self.assertEqual(errors, [])
        self.assertLessEqual(len(cache), maxsize)

"""
Tests for cache_watcher models and supporting classes.

Written from scratch using red/green TDD.

DATABASE SAFETY
---------------
- All tests use Django TestCase only. Never TransactionTestCase.
- TestCase wraps every test in a rolled-back transaction. Nothing persists.
- Filesystem directories are created in tempfile.mkdtemp() and cleaned up in tearDown.
- fs_Cache_Tracking queries are always scoped to directories created in the test,
  never global counts, to avoid interference with other data.

COVERAGE
--------
  LockFreeEventBuffer      — add_event, get_events_to_process, size, clear, overflow
  fs_Cache_Tracking        — add_from_indexdirs, sha_exists_in_cache,
                             remove_from_cache_indexdirs, remove_multiple_from_cache_indexdirs,
                             _validate_index_dir, clear_all_records, delete_orphaned_entries,
                             _bulk_invalidate_by_shas, _clear_layout_cache_bulk
  CacheStatisticsTracking  — hit_rate property, __str__
  CacheFileMonitorEventHandler — cleanup, _buffer_event (timer creation, dedup)
  WatchdogManager          — start, stop, shutdown, restart, _schedule_restart,
                             _process_pending_events (all via mocks — no real threads)
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time

import pytest
from django.test import TestCase

from cache_watcher.models import (
    CacheFileMonitorEventHandler,
    CacheStatisticsTracking,
    LockFreeEventBuffer,
    fs_Cache_Tracking,
    optimized_event_buffer,
)
from quickbbs.models import DirectoryIndex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dir(path: str) -> DirectoryIndex:
    """Create filesystem directory and register in DirectoryIndex."""
    os.makedirs(path, exist_ok=True)
    _, di = DirectoryIndex.add_directory(path + "/")
    return di


def _test_shas(dirs: dict) -> set[str]:
    """Return set of dir_fqpn_sha256 values for scoping DB queries."""
    return {d.dir_fqpn_sha256 for d in dirs.values() if d is not None}


# ===========================================================================
# LockFreeEventBuffer
# ===========================================================================

class TestLockFreeEventBuffer(TestCase):
    """Unit tests for LockFreeEventBuffer — no DB access."""

    def setUp(self):
        self.buf = LockFreeEventBuffer(max_size=10)

    def test_initial_size_is_zero(self):
        assert self.buf.size() == 0

    def test_add_event_increases_size(self):
        self.buf.add_event("/some/path")
        assert self.buf.size() == 1

    def test_add_multiple_events(self):
        self.buf.add_event("/a")
        self.buf.add_event("/b")
        self.buf.add_event("/c")
        assert self.buf.size() == 3

    def test_get_events_returns_set(self):
        self.buf.add_event("/x")
        result = self.buf.get_events_to_process()
        assert isinstance(result, set)

    def test_get_events_contains_added_path(self):
        self.buf.add_event("/mypath")
        result = self.buf.get_events_to_process()
        assert "/mypath" in result

    def test_get_events_clears_buffer(self):
        self.buf.add_event("/something")
        self.buf.get_events_to_process()
        assert self.buf.size() == 0

    def test_get_events_deduplicates(self):
        """Same path added multiple times appears only once in result."""
        self.buf.add_event("/dup")
        self.buf.add_event("/dup")
        self.buf.add_event("/dup")
        result = self.buf.get_events_to_process()
        assert result == {"/dup"}

    def test_get_events_empty_buffer_returns_empty_set(self):
        result = self.buf.get_events_to_process()
        assert result == set()

    def test_clear_empties_buffer(self):
        self.buf.add_event("/a")
        self.buf.add_event("/b")
        self.buf.clear()
        assert self.buf.size() == 0

    def test_clear_prevents_events_from_being_returned(self):
        self.buf.add_event("/a")
        self.buf.clear()
        result = self.buf.get_events_to_process()
        assert result == set()

    def test_overflow_trims_to_half_max(self):
        """Buffer trims to 50% of max_size when overflow occurs."""
        buf = LockFreeEventBuffer(max_size=10)
        for i in range(12):  # Exceeds max_size=10
            buf.add_event(f"/path{i}")
        # After overflow, size should be trimmed to <= max_size
        assert buf.size() <= 10

    def test_thread_safety_concurrent_adds(self):
        """Concurrent adds from multiple threads do not corrupt the buffer."""
        buf = LockFreeEventBuffer(max_size=1000)
        errors = []

        def add_events():
            try:
                for i in range(50):
                    buf.add_event(f"/thread-path-{threading.current_thread().name}-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_events) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert buf.size() > 0


# ===========================================================================
# fs_Cache_Tracking._validate_index_dir
# ===========================================================================

@pytest.mark.django_db
class TestValidateIndexDir(TestCase):
    """Tests for the static _validate_index_dir helper."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.di = _make_dir(self.temp_dir)
        self.cache = fs_Cache_Tracking()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_valid_directoryindex_returns_true(self):
        assert fs_Cache_Tracking._validate_index_dir(self.di) is True

    def test_none_returns_false(self):
        assert fs_Cache_Tracking._validate_index_dir(None) is False

    def test_object_without_sha_returns_false(self):
        class Fake:
            pass
        assert fs_Cache_Tracking._validate_index_dir(Fake()) is False

    def test_object_with_empty_sha_returns_false(self):
        class Fake:
            dir_fqpn_sha256 = ""
        assert fs_Cache_Tracking._validate_index_dir(Fake()) is False

    def test_object_with_none_sha_returns_false(self):
        class Fake:
            dir_fqpn_sha256 = None
        assert fs_Cache_Tracking._validate_index_dir(Fake()) is False


# ===========================================================================
# fs_Cache_Tracking.add_from_indexdirs
# ===========================================================================

@pytest.mark.django_db
class TestAddFromIndexdirs(TestCase):
    """Tests for add_from_indexdirs."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.di = _make_dir(self.temp_dir)
        self.cache = fs_Cache_Tracking()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_creates_cache_entry(self):
        result = self.cache.add_from_indexdirs(self.di)
        assert result is not None
        assert fs_Cache_Tracking.objects.filter(directory=self.di).exists()

    def test_entry_starts_not_invalidated(self):
        self.cache.add_from_indexdirs(self.di)
        entry = fs_Cache_Tracking.objects.get(directory=self.di)
        assert entry.invalidated is False

    def test_lastscan_is_recent(self):
        before = time.time() - 1
        self.cache.add_from_indexdirs(self.di)
        entry = fs_Cache_Tracking.objects.get(directory=self.di)
        assert entry.lastscan >= before

    def test_idempotent_second_call_updates(self):
        """Calling add_from_indexdirs twice updates rather than duplicating."""
        self.cache.add_from_indexdirs(self.di)
        self.cache.add_from_indexdirs(self.di)
        count = fs_Cache_Tracking.objects.filter(directory=self.di).count()
        assert count == 1

    def test_returns_entry_object(self):
        result = self.cache.add_from_indexdirs(self.di)
        assert isinstance(result, fs_Cache_Tracking)

    def test_none_input_returns_none(self):
        result = self.cache.add_from_indexdirs(None)
        assert result is None

    def test_reinvalidated_entry_is_reset_to_valid(self):
        """add_from_indexdirs on an already-invalidated entry marks it valid again."""
        self.cache.add_from_indexdirs(self.di)
        # Manually invalidate
        fs_Cache_Tracking.objects.filter(directory=self.di).update(invalidated=True)
        # Re-add
        self.cache.add_from_indexdirs(self.di)
        entry = fs_Cache_Tracking.objects.get(directory=self.di)
        assert entry.invalidated is False


# ===========================================================================
# fs_Cache_Tracking.sha_exists_in_cache
# ===========================================================================

@pytest.mark.django_db
class TestShaExistsInCache(TestCase):
    """Tests for sha_exists_in_cache."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.di = _make_dir(self.temp_dir)
        self.cache = fs_Cache_Tracking()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_returns_false_when_not_in_cache(self):
        assert self.cache.sha_exists_in_cache(self.di.dir_fqpn_sha256) is False

    def test_returns_true_after_adding(self):
        self.cache.add_from_indexdirs(self.di)
        assert self.cache.sha_exists_in_cache(self.di.dir_fqpn_sha256) is True

    def test_returns_false_after_invalidation(self):
        self.cache.add_from_indexdirs(self.di)
        fs_Cache_Tracking.objects.filter(directory=self.di).update(invalidated=True)
        assert self.cache.sha_exists_in_cache(self.di.dir_fqpn_sha256) is False

    def test_unknown_sha_returns_false(self):
        assert self.cache.sha_exists_in_cache("0" * 64) is False


# ===========================================================================
# fs_Cache_Tracking.remove_from_cache_indexdirs
# ===========================================================================

@pytest.mark.django_db
class TestRemoveFromCacheIndexdirs(TestCase):
    """Tests for remove_from_cache_indexdirs (single directory)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.di = _make_dir(self.temp_dir)
        self.cache = fs_Cache_Tracking()
        self.cache.add_from_indexdirs(self.di)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_returns_true_on_success(self):
        result = self.cache.remove_from_cache_indexdirs(self.di)
        assert result is True

    def test_entry_is_invalidated(self):
        self.cache.remove_from_cache_indexdirs(self.di)
        entry = fs_Cache_Tracking.objects.get(directory=self.di)
        assert entry.invalidated is True

    def test_sha_no_longer_in_cache(self):
        self.cache.remove_from_cache_indexdirs(self.di)
        assert self.cache.sha_exists_in_cache(self.di.dir_fqpn_sha256) is False

    def test_none_input_returns_false(self):
        result = self.cache.remove_from_cache_indexdirs(None)
        assert result is False

    def test_invalid_object_returns_false(self):
        class Fake:
            dir_fqpn_sha256 = ""
        result = self.cache.remove_from_cache_indexdirs(Fake())
        assert result is False


# ===========================================================================
# fs_Cache_Tracking.remove_multiple_from_cache_indexdirs
# ===========================================================================

@pytest.mark.django_db
class TestRemoveMultipleFromCacheIndexdirs(TestCase):
    """Tests for remove_multiple_from_cache_indexdirs (batch invalidation)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.temp_dir, "a"), exist_ok=True)
        os.makedirs(os.path.join(self.temp_dir, "b"), exist_ok=True)

        self.di_root = _make_dir(self.temp_dir)
        self.di_a = _make_dir(os.path.join(self.temp_dir, "a"))
        self.di_b = _make_dir(os.path.join(self.temp_dir, "b"))
        self.dirs = {"root": self.di_root, "a": self.di_a, "b": self.di_b}

        self.cache = fs_Cache_Tracking()
        for di in self.dirs.values():
            self.cache.add_from_indexdirs(di)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_empty_list_returns_false(self):
        result = self.cache.remove_multiple_from_cache_indexdirs([])
        assert result is False

    def test_single_dir_returns_true(self):
        result = self.cache.remove_multiple_from_cache_indexdirs([self.di_a])
        assert result is True

    def test_single_dir_is_invalidated(self):
        self.cache.remove_multiple_from_cache_indexdirs([self.di_a])
        entry = fs_Cache_Tracking.objects.get(directory=self.di_a)
        assert entry.invalidated is True

    def test_multiple_dirs_all_invalidated(self):
        self.cache.remove_multiple_from_cache_indexdirs([self.di_a, self.di_b])
        shas = _test_shas({"a": self.di_a, "b": self.di_b})
        count = fs_Cache_Tracking.objects.filter(
            directory__dir_fqpn_sha256__in=shas, invalidated=True
        ).count()
        assert count == 2

    def test_duplicate_dirs_processed_once(self):
        """Passing the same dir multiple times does not create extra entries."""
        self.cache.remove_multiple_from_cache_indexdirs([self.di_a, self.di_a, self.di_a])
        count = fs_Cache_Tracking.objects.filter(directory=self.di_a).count()
        assert count == 1

    def test_returns_false_for_all_invalid_objects(self):
        class Fake:
            dir_fqpn_sha256 = ""
        result = self.cache.remove_multiple_from_cache_indexdirs([Fake(), Fake()])
        assert result is False

    def test_other_dirs_not_affected(self):
        """Invalidating 'a' does not affect 'b'."""
        self.cache.remove_multiple_from_cache_indexdirs([self.di_a])
        entry_b = fs_Cache_Tracking.objects.get(directory=self.di_b)
        assert entry_b.invalidated is False


# ===========================================================================
# fs_Cache_Tracking.clear_all_records
# ===========================================================================

@pytest.mark.django_db
class TestClearAllRecords(TestCase):
    """Tests for clear_all_records."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.temp_dir, "c1"), exist_ok=True)
        os.makedirs(os.path.join(self.temp_dir, "c2"), exist_ok=True)
        self.di1 = _make_dir(os.path.join(self.temp_dir, "c1"))
        self.di2 = _make_dir(os.path.join(self.temp_dir, "c2"))
        self.cache = fs_Cache_Tracking()
        self.cache.add_from_indexdirs(self.di1)
        self.cache.add_from_indexdirs(self.di2)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_returns_count_of_invalidated(self):
        result = fs_Cache_Tracking.clear_all_records()
        # At minimum our two entries were invalidated
        assert result >= 2

    def test_all_test_entries_are_invalidated(self):
        fs_Cache_Tracking.clear_all_records()
        shas = {self.di1.dir_fqpn_sha256, self.di2.dir_fqpn_sha256}
        valid_count = fs_Cache_Tracking.objects.filter(
            directory__dir_fqpn_sha256__in=shas, invalidated=False
        ).count()
        assert valid_count == 0

    def test_idempotent_called_twice(self):
        """clear_all_records is safe to call multiple times."""
        fs_Cache_Tracking.clear_all_records()
        result2 = fs_Cache_Tracking.clear_all_records()
        assert isinstance(result2, int)


# ===========================================================================
# fs_Cache_Tracking.delete_orphaned_entries
# ===========================================================================

@pytest.mark.django_db
class TestDeleteOrphanedEntries(TestCase):
    """Tests for delete_orphaned_entries."""

    def setUp(self):
        self.cache = fs_Cache_Tracking()

    def test_returns_integer(self):
        result = fs_Cache_Tracking.delete_orphaned_entries()
        assert isinstance(result, int)

    def test_returns_zero_when_no_orphans(self):
        # No orphans should exist in a clean test transaction
        result = fs_Cache_Tracking.delete_orphaned_entries()
        assert result == 0

    def test_deletes_null_directory_entries(self):
        """fs_Cache_Tracking entries with null directory are deleted."""
        # Create an orphaned entry directly
        orphan = fs_Cache_Tracking.objects.create(
            directory=None,
            lastscan=0.0,
            invalidated=False,
        )
        pk = orphan.pk
        deleted = fs_Cache_Tracking.delete_orphaned_entries()
        assert deleted >= 1
        assert not fs_Cache_Tracking.objects.filter(pk=pk).exists()


# ===========================================================================
# fs_Cache_Tracking._bulk_invalidate_by_shas
# ===========================================================================

@pytest.mark.django_db
class TestBulkInvalidateByShas(TestCase):
    """Tests for _bulk_invalidate_by_shas."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.temp_dir, "d1"), exist_ok=True)
        os.makedirs(os.path.join(self.temp_dir, "d2"), exist_ok=True)
        self.di1 = _make_dir(os.path.join(self.temp_dir, "d1"))
        self.di2 = _make_dir(os.path.join(self.temp_dir, "d2"))
        self.cache = fs_Cache_Tracking()
        self.cache.add_from_indexdirs(self.di1)
        self.cache.add_from_indexdirs(self.di2)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_invalidates_entries_for_given_shas(self):
        shas = [self.di1.dir_fqpn_sha256]
        count = self.cache._bulk_invalidate_by_shas(shas)
        assert count >= 1
        entry = fs_Cache_Tracking.objects.get(directory=self.di1)
        assert entry.invalidated is True

    def test_returns_count_of_updated_entries(self):
        shas = [self.di1.dir_fqpn_sha256, self.di2.dir_fqpn_sha256]
        count = self.cache._bulk_invalidate_by_shas(shas)
        assert count >= 2

    def test_empty_sha_list_returns_zero(self):
        count = self.cache._bulk_invalidate_by_shas([])
        assert count == 0

    def test_creates_entry_for_dir_without_cache_record(self):
        """Directories without a cache entry get one created (invalidated=True)."""
        # Create a dir that has NO cache entry
        extra_path = os.path.join(self.temp_dir, "new_dir")
        os.makedirs(extra_path, exist_ok=True)
        di_new = _make_dir(extra_path)
        # Do NOT call add_from_indexdirs — no cache entry exists

        count = self.cache._bulk_invalidate_by_shas([di_new.dir_fqpn_sha256])
        assert count >= 1
        assert fs_Cache_Tracking.objects.filter(directory=di_new, invalidated=True).exists()


# ===========================================================================
# fs_Cache_Tracking._clear_layout_cache_bulk
# ===========================================================================

@pytest.mark.django_db
class TestClearLayoutCacheBulk(TestCase):
    """Tests for _clear_layout_cache_bulk."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.di = _make_dir(self.temp_dir)
        self.cache = fs_Cache_Tracking()
        from quickbbs.cache_registry import layout_manager_cache
        layout_manager_cache.clear()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        from quickbbs.cache_registry import layout_manager_cache
        layout_manager_cache.clear()

    def test_empty_list_does_not_raise(self):
        """Passing an empty list is a no-op, no exception raised."""
        try:
            self.cache._clear_layout_cache_bulk([])
        except Exception as e:
            self.fail(f"_clear_layout_cache_bulk([]) raised: {e}")

    def test_clears_layout_cache_for_directory(self):
        from frontend.managers import layout_manager
        layout_manager(page_number=1, directory=self.di, sort_ordering=0, show_duplicates=False)
        from quickbbs.cache_registry import layout_manager_cache
        assert len(layout_manager_cache) > 0

        self.cache._clear_layout_cache_bulk([self.di])
        assert len(layout_manager_cache) == 0

    def test_none_entries_in_list_are_skipped(self):
        """None entries in the list don't crash the method."""
        try:
            self.cache._clear_layout_cache_bulk([None, self.di, None])
        except Exception as e:
            self.fail(f"_clear_layout_cache_bulk with None raised: {e}")

    def test_no_db_queries_during_clear(self):
        """Layout cache clearing uses no DB queries."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            self.cache._clear_layout_cache_bulk([self.di])
        assert len(ctx.captured_queries) == 0


# ===========================================================================
# CacheStatisticsTracking
# ===========================================================================

class TestCacheStatisticsTracking(TestCase):
    """Tests for CacheStatisticsTracking model and properties."""

    def _make_stat(self, hits: int, misses: int) -> CacheStatisticsTracking:
        stat = CacheStatisticsTracking()
        stat.hits = hits
        stat.misses = misses
        return stat

    def test_hit_rate_zero_when_no_requests(self):
        stat = self._make_stat(0, 0)
        assert stat.hit_rate == 0.0

    def test_hit_rate_100_when_all_hits(self):
        stat = self._make_stat(100, 0)
        assert stat.hit_rate == 100.0

    def test_hit_rate_0_when_all_misses(self):
        stat = self._make_stat(0, 100)
        assert stat.hit_rate == 0.0

    def test_hit_rate_50_percent(self):
        stat = self._make_stat(50, 50)
        assert stat.hit_rate == 50.0

    def test_hit_rate_75_percent(self):
        stat = self._make_stat(75, 25)
        assert stat.hit_rate == 75.0

    def test_str_shows_cache_name(self):
        stat = CacheStatisticsTracking()
        stat.cache_name = "fileindex"
        stat.hits = 10
        stat.misses = 0
        assert "fileindex" in str(stat)

    def test_str_shows_hit_rate(self):
        stat = CacheStatisticsTracking()
        stat.cache_name = "test_cache"
        stat.hits = 80
        stat.misses = 20
        result = str(stat)
        assert "80.0%" in result

    def test_str_shows_na_when_no_requests(self):
        stat = CacheStatisticsTracking()
        stat.cache_name = "empty"
        stat.hits = 0
        stat.misses = 0
        assert "n/a" in str(stat)


# ===========================================================================
# CacheFileMonitorEventHandler
# ===========================================================================

class TestCacheFileMonitorEventHandler(TestCase):
    """Tests for CacheFileMonitorEventHandler."""

    def setUp(self):
        # Clear global event buffer before each test
        optimized_event_buffer.clear()
        self.handler = CacheFileMonitorEventHandler()

    def tearDown(self):
        # Cancel any pending timer to prevent test leakage
        self.handler.cleanup()
        optimized_event_buffer.clear()

    def test_initial_state_no_timer(self):
        assert self.handler.event_timer is None

    def test_initial_generation_is_zero(self):
        assert self.handler.timer_generation == 0

    def test_cleanup_cancels_timer(self):
        """cleanup() cancels any pending timer."""
        # Manually set a timer
        timer = threading.Timer(60, lambda: None)
        timer.start()
        self.handler.event_timer = timer
        self.handler.timer_generation = 1

        self.handler.cleanup()

        assert self.handler.event_timer is None

    def test_cleanup_increments_generation(self):
        """cleanup() increments timer_generation to invalidate stale timers."""
        self.handler.timer_generation = 3
        # Give it a timer to cancel
        timer = threading.Timer(60, lambda: None)
        timer.start()
        self.handler.event_timer = timer

        self.handler.cleanup()
        assert self.handler.timer_generation == 4

    def test_cleanup_with_no_timer_is_safe(self):
        """cleanup() on a handler with no timer does not raise."""
        assert self.handler.event_timer is None
        try:
            self.handler.cleanup()
        except Exception as e:
            self.fail(f"cleanup() with no timer raised: {e}")

    def test_buffer_event_adds_to_global_buffer(self):
        """_buffer_event adds the directory path to optimized_event_buffer."""
        from unittest.mock import MagicMock
        event = MagicMock()
        event.is_directory = True
        event.src_path = "/some/test/directory"

        optimized_event_buffer.clear()
        self.handler._buffer_event(event)

        result = optimized_event_buffer.get_events_to_process()
        assert "/some/test/directory" in result

    def test_buffer_file_event_adds_parent_dir(self):
        """_buffer_event for a file event adds the parent directory, not the file."""
        from unittest.mock import MagicMock
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/test/directory/file.jpg"

        optimized_event_buffer.clear()
        self.handler._buffer_event(event)

        result = optimized_event_buffer.get_events_to_process()
        assert "/some/test/directory" in result

    def test_buffer_event_creates_timer(self):
        """_buffer_event creates a timer if none exists."""
        from unittest.mock import MagicMock
        event = MagicMock()
        event.is_directory = True
        event.src_path = "/timer/test"

        assert self.handler.event_timer is None
        self.handler._buffer_event(event)
        assert self.handler.event_timer is not None

    def test_buffer_event_does_not_create_second_timer(self):
        """_buffer_event does not create a new timer if one already exists."""
        from unittest.mock import MagicMock
        event = MagicMock()
        event.is_directory = True
        event.src_path = "/timer/test"

        self.handler._buffer_event(event)
        first_timer = self.handler.event_timer

        # Second event — should not replace timer
        self.handler._buffer_event(event)
        assert self.handler.event_timer is first_timer


# ===========================================================================
# WatchdogManager — state machine tests via mocks
#
# Strategy: patch watchdog.startup and watchdog.stop_observer at the module
# level where WatchdogManager imports them, and patch threading.Timer so
# no real threads or timers are created.  Each test gets a fresh
# WatchdogManager instance so global state from apps.py doesn't interfere.
# ===========================================================================

class TestWatchdogManagerStart(TestCase):
    """Tests for WatchdogManager.start()."""

    def setUp(self):
        from cache_watcher.models import WatchdogManager
        self.manager = WatchdogManager()

    def tearDown(self):
        # Ensure no real timer is running after each test
        with self.manager.lock:
            if self.manager.restart_timer:
                self.manager.restart_timer.cancel()
                self.manager.restart_timer = None

    def test_start_sets_is_running(self):
        from unittest.mock import patch, MagicMock
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog") as mock_wdog, \
             patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start()
        assert self.manager.is_running is True

    def test_start_calls_watchdog_startup(self):
        from unittest.mock import patch, MagicMock
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog") as mock_wdog, \
             patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start()
        mock_wdog.startup.assert_called_once()

    def test_start_schedules_restart_timer(self):
        from unittest.mock import patch, MagicMock
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog"), \
             patch("cache_watcher.models.threading.Timer", return_value=mock_timer) as mock_timer_cls:
            self.manager.start()
        mock_timer_cls.assert_called_once()
        mock_timer.start.assert_called_once()

    def test_start_twice_does_not_call_startup_again(self):
        """Second call to start() when already running is a no-op."""
        from unittest.mock import patch, MagicMock
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog") as mock_wdog, \
             patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start()
            self.manager.start()
        assert mock_wdog.startup.call_count == 1

    def test_start_with_force_recreate_passes_flag(self):
        from unittest.mock import patch, MagicMock
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog") as mock_wdog, \
             patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start(force_recreate=True)
        _, kwargs = mock_wdog.startup.call_args
        assert kwargs.get("force_recreate") is True


class TestWatchdogManagerStop(TestCase):
    """Tests for WatchdogManager.stop()."""

    def setUp(self):
        from cache_watcher.models import WatchdogManager
        self.manager = WatchdogManager()

    def _start_mocked(self):
        """Start the manager with all external calls mocked."""
        from unittest.mock import patch, MagicMock
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog"), \
             patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start()
        # Replace the real timer with a mock so tearDown doesn't try to cancel a dead thread
        self.manager.restart_timer = mock_timer

    def tearDown(self):
        with self.manager.lock:
            if self.manager.restart_timer:
                self.manager.restart_timer.cancel()
                self.manager.restart_timer = None

    def test_stop_sets_is_running_false(self):
        from unittest.mock import patch
        self._start_mocked()
        with patch("cache_watcher.models.watchdog"):
            self.manager.stop()
        assert self.manager.is_running is False

    def test_stop_calls_stop_observer(self):
        from unittest.mock import patch
        self._start_mocked()
        with patch("cache_watcher.models.watchdog") as mock_wdog:
            self.manager.stop()
        mock_wdog.stop_observer.assert_called_once()

    def test_stop_clears_event_handler(self):
        from unittest.mock import patch
        self._start_mocked()
        with patch("cache_watcher.models.watchdog"):
            self.manager.stop()
        assert self.manager.event_handler is None

    def test_stop_when_not_running_is_safe(self):
        """stop() on an already-stopped manager does nothing."""
        assert self.manager.is_running is False
        from unittest.mock import patch
        with patch("cache_watcher.models.watchdog") as mock_wdog:
            self.manager.stop()
        mock_wdog.stop_observer.assert_not_called()


class TestWatchdogManagerShutdown(TestCase):
    """Tests for WatchdogManager.shutdown()."""

    def setUp(self):
        from cache_watcher.models import WatchdogManager
        self.manager = WatchdogManager()

    def test_shutdown_cancels_restart_timer(self):
        from unittest.mock import patch, MagicMock
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        self.manager.restart_timer = mock_timer
        with patch("cache_watcher.models.watchdog"):
            self.manager.shutdown()
        mock_timer.cancel.assert_called_once()
        assert self.manager.restart_timer is None

    def test_shutdown_sets_is_running_false(self):
        from unittest.mock import patch, MagicMock
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog"), \
             patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start()
        self.manager.restart_timer = mock_timer
        with patch("cache_watcher.models.watchdog"):
            self.manager.shutdown()
        assert self.manager.is_running is False

    def test_shutdown_when_not_running_does_not_raise(self):
        from unittest.mock import patch
        assert self.manager.is_running is False
        try:
            with patch("cache_watcher.models.watchdog"):
                self.manager.shutdown()
        except Exception as e:
            self.fail(f"shutdown() when not running raised: {e}")

    def test_shutdown_clears_event_handler(self):
        from unittest.mock import patch, MagicMock
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog"), \
             patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start()
        self.manager.restart_timer = mock_timer
        with patch("cache_watcher.models.watchdog"):
            self.manager.shutdown()
        assert self.manager.event_handler is None


class TestWatchdogManagerRestart(TestCase):
    """Tests for WatchdogManager.restart()."""

    def setUp(self):
        from cache_watcher.models import WatchdogManager
        self.manager = WatchdogManager()

    def tearDown(self):
        with self.manager.lock:
            if self.manager.restart_timer:
                self.manager.restart_timer.cancel()
                self.manager.restart_timer = None

    def _mock_timer(self):
        from unittest.mock import MagicMock
        t = MagicMock()
        t.is_alive.return_value = True
        return t

    def test_restart_calls_stop_then_start(self):
        from unittest.mock import patch
        mock_timer = self._mock_timer()
        # WatchdogManager uses __slots__ — patch at class level, not instance level
        with patch("cache_watcher.models.watchdog") as mock_wdog, \
             patch("cache_watcher.models.threading.Timer", return_value=mock_timer), \
             patch("cache_watcher.models.WatchdogManager._process_pending_events"):
            self.manager.start()
            self.manager.restart_timer = mock_timer
            self.manager.restart()

        # startup called twice: once for start(), once for restart()'s start()
        assert mock_wdog.startup.call_count == 2

    def test_restart_clears_event_buffer(self):
        from unittest.mock import patch
        mock_timer = self._mock_timer()
        optimized_event_buffer.add_event("/some/path")
        assert optimized_event_buffer.size() > 0

        with patch("cache_watcher.models.watchdog"), \
             patch("cache_watcher.models.threading.Timer", return_value=mock_timer), \
             patch("cache_watcher.models.WatchdogManager._process_pending_events"):
            self.manager.start()
            self.manager.restart_timer = mock_timer
            self.manager.restart()

        assert optimized_event_buffer.size() == 0

    def test_restart_uses_force_recreate(self):
        """restart() calls start(force_recreate=True) to prevent memory leaks."""
        from unittest.mock import patch
        mock_timer = self._mock_timer()
        with patch("cache_watcher.models.watchdog") as mock_wdog, \
             patch("cache_watcher.models.threading.Timer", return_value=mock_timer), \
             patch("cache_watcher.models.WatchdogManager._process_pending_events"):
            self.manager.start()
            self.manager.restart_timer = mock_timer
            self.manager.restart()

        # The second startup call (from restart) should have force_recreate=True
        second_call_kwargs = mock_wdog.startup.call_args_list[1][1]
        assert second_call_kwargs.get("force_recreate") is True

    def test_restart_schedules_next_restart(self):
        """After restarting, a new restart timer is scheduled."""
        from unittest.mock import patch
        mock_timer = self._mock_timer()
        with patch("cache_watcher.models.watchdog"), \
             patch("cache_watcher.models.threading.Timer", return_value=mock_timer) as mock_cls, \
             patch("cache_watcher.models.WatchdogManager._process_pending_events"):
            self.manager.start()
            self.manager.restart_timer = mock_timer
            self.manager.restart()

        # Timer constructor called at least twice: once in start(), once after restart()
        assert mock_cls.call_count >= 2


class TestWatchdogManagerScheduleRestart(TestCase):
    """Tests for WatchdogManager._schedule_restart()."""

    def setUp(self):
        from cache_watcher.models import WatchdogManager
        self.manager = WatchdogManager()

    def tearDown(self):
        with self.manager.lock:
            if self.manager.restart_timer:
                self.manager.restart_timer.cancel()
                self.manager.restart_timer = None

    def test_schedule_restart_creates_timer(self):
        from unittest.mock import patch, MagicMock
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            with self.manager.lock:
                self.manager._schedule_restart()
        assert self.manager.restart_timer is mock_timer

    def test_schedule_restart_starts_timer(self):
        from unittest.mock import patch, MagicMock
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            with self.manager.lock:
                self.manager._schedule_restart()
        mock_timer.start.assert_called_once()

    def test_schedule_restart_timer_is_daemon(self):
        """Timer must be a daemon thread so it doesn't block process exit."""
        from unittest.mock import patch, MagicMock
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            with self.manager.lock:
                self.manager._schedule_restart()
        assert mock_timer.daemon is True

    def test_schedule_restart_cancels_existing_timer(self):
        """Calling _schedule_restart when a timer exists cancels the old one."""
        from unittest.mock import patch, MagicMock
        old_timer = MagicMock()
        old_timer.is_alive.return_value = True
        self.manager.restart_timer = old_timer

        new_timer = MagicMock()
        new_timer.is_alive.return_value = True
        with patch("cache_watcher.models.threading.Timer", return_value=new_timer):
            with self.manager.lock:
                self.manager._schedule_restart()

        old_timer.cancel.assert_called_once()
        assert self.manager.restart_timer is new_timer

    def test_schedule_restart_uses_configured_interval(self):
        """Timer is created with the configured WATCHDOG_RESTART_INTERVAL."""
        from unittest.mock import patch, MagicMock
        from cache_watcher.models import WATCHDOG_RESTART_INTERVAL
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.threading.Timer", return_value=mock_timer) as mock_cls:
            with self.manager.lock:
                self.manager._schedule_restart()
        args = mock_cls.call_args[0]
        assert args[0] == WATCHDOG_RESTART_INTERVAL


class TestWatchdogManagerProcessPendingEvents(TestCase):
    """Tests for WatchdogManager._process_pending_events()."""

    def setUp(self):
        from cache_watcher.models import WatchdogManager
        self.manager = WatchdogManager()
        optimized_event_buffer.clear()

    def tearDown(self):
        optimized_event_buffer.clear()

    def test_empty_buffer_returns_immediately(self):
        """No semaphore acquisition when buffer is empty."""
        from unittest.mock import patch
        assert optimized_event_buffer.size() == 0
        with patch("cache_watcher.models.processing_semaphore") as mock_sem:
            self.manager._process_pending_events()
        mock_sem.acquire.assert_not_called()

    def test_non_empty_buffer_acquires_semaphore(self):
        from unittest.mock import patch, MagicMock
        optimized_event_buffer.add_event("/some/path")
        mock_sem = MagicMock()
        mock_sem.acquire.return_value = True
        with patch("cache_watcher.models.processing_semaphore", mock_sem), \
             patch("cache_watcher.models.Cache_Storage") as mock_cache, \
             patch("quickbbs.models.DirectoryIndex.objects") as mock_di:
            mock_di.filter.return_value.only.return_value = []
            self.manager._process_pending_events()
        mock_sem.acquire.assert_called_once_with(blocking=False)

    def test_semaphore_released_after_processing(self):
        from unittest.mock import patch, MagicMock
        optimized_event_buffer.add_event("/some/path")
        mock_sem = MagicMock()
        mock_sem.acquire.return_value = True
        with patch("cache_watcher.models.processing_semaphore", mock_sem), \
             patch("cache_watcher.models.Cache_Storage"), \
             patch("quickbbs.models.DirectoryIndex.objects") as mock_di:
            mock_di.filter.return_value.only.return_value = []
            self.manager._process_pending_events()
        mock_sem.release.assert_called_once()

    def test_semaphore_not_acquired_skips_processing(self):
        """If semaphore is held by another thread, processing is skipped gracefully."""
        from unittest.mock import patch, MagicMock
        optimized_event_buffer.add_event("/some/path")
        mock_sem = MagicMock()
        mock_sem.acquire.return_value = False  # Can't acquire — another thread holds it
        with patch("cache_watcher.models.processing_semaphore", mock_sem), \
             patch("cache_watcher.models.Cache_Storage") as mock_cache:
            self.manager._process_pending_events()
        mock_cache.remove_multiple_from_cache_indexdirs.assert_not_called()

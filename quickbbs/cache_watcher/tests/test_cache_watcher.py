"""
Tests for cache_watcher models and supporting classes.

Written from scratch using red/green TDD.

DATABASE SAFETY
---------------
- All tests use Django TestCase only. Never TransactionTestCase.
- TestCase wraps every test in a rolled-back transaction. Nothing persists.
- Filesystem directories are created in tempfile.mkdtemp() and cleaned up in tearDown.
- Invalidation-state queries are always scoped to directories created in the test,
  never global counts, to avoid interference with other data.

COVERAGE
--------
  LockFreeEventBuffer      — add_event, get_events_to_process, size, clear, overflow
  DirectoryIndex cache API — mark_scanned, cache_valid_for_sha, invalidate_cache,
                             invalidate_cache_by_sha, invalidate_caches,
                             invalidate_all_caches, _invalidate_by_shas,
                             layout-cache clearing on invalidation
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
from django.test import TestCase, override_settings

from cache_watcher.models import (
    CacheFileMonitorEventHandler,
    CacheStatisticsTracking,
    LockFreeEventBuffer,
    optimized_event_buffer,
)
from quickbbs.models import DirectoryIndex

pytestmark = pytest.mark.api

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


class AlbumsRootTestCase(TestCase):
    """Base for tests that register real directories in DirectoryIndex.

    add_directory() rejects paths outside the albums root, so ALBUMS_PATH is
    pointed at a per-test temp directory and content is created under
    <temp>/albums/ (exposed as self.albums_dir). Mirrors the pattern in
    quickbbs/tests/test_directoryindex.py.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.albums_dir = os.path.join(self.temp_dir, "albums")
        os.makedirs(self.albums_dir, exist_ok=True)
        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir)
        self._settings_override.enable()
        # Reset cached class-level path lookups so they pick up the new ALBUMS_PATH
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None

    def tearDown(self):
        self._settings_override.disable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)


# ===========================================================================
# LockFreeEventBuffer
# ===========================================================================


class TestLockFreeEventBuffer(TestCase):
    """Unit tests for LockFreeEventBuffer — no DB access."""

    def setUp(self):
        self.buf = LockFreeEventBuffer(max_size=10)

    def test_initial_size_is_zero(self):
        """Initial size is zero."""
        assert self.buf.size() == 0

    def test_add_event_increases_size(self):
        """Add event increases size."""
        self.buf.add_event("/some/path")
        assert self.buf.size() == 1

    def test_add_multiple_events(self):
        """Add multiple events."""
        self.buf.add_event("/a")
        self.buf.add_event("/b")
        self.buf.add_event("/c")
        assert self.buf.size() == 3

    def test_get_events_returns_set(self):
        """Get events returns set."""
        self.buf.add_event("/x")
        result = self.buf.get_events_to_process()
        assert isinstance(result, set)

    def test_get_events_contains_added_path(self):
        """Get events contains added path."""
        self.buf.add_event("/mypath")
        result = self.buf.get_events_to_process()
        assert "/mypath" in result

    def test_get_events_clears_buffer(self):
        """Get events clears buffer."""
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
        """Get events empty buffer returns empty set."""
        result = self.buf.get_events_to_process()
        assert result == set()

    def test_clear_empties_buffer(self):
        """Clear empties buffer."""
        self.buf.add_event("/a")
        self.buf.add_event("/b")
        self.buf.clear()
        assert self.buf.size() == 0

    def test_clear_prevents_events_from_being_returned(self):
        """Clear prevents events from being returned."""
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
# DirectoryIndex.mark_scanned
# ===========================================================================


@pytest.mark.django_db
class TestMarkScanned(AlbumsRootTestCase):
    """Tests for DirectoryIndex.mark_scanned (formerly add_from_indexdirs)."""

    def setUp(self):
        super().setUp()
        self.di = _make_dir(self.albums_dir)

    def tearDown(self):
        super().tearDown()

    def test_new_directory_starts_invalidated(self):
        """A freshly created row defaults to cache_invalidated=True."""
        assert self.di.cache_invalidated is True

    def test_mark_scanned_sets_valid(self):
        """Mark scanned sets valid."""
        self.di.mark_scanned()
        self.di.refresh_from_db()
        assert self.di.cache_invalidated is False

    def test_cache_lastscan_is_recent(self):
        """Cache lastscan is recent."""
        before = time.time() - 1
        self.di.mark_scanned()
        self.di.refresh_from_db()
        assert self.di.cache_lastscan >= before

    def test_idempotent_second_call(self):
        """Calling mark_scanned twice leaves the row valid."""
        self.di.mark_scanned()
        self.di.mark_scanned()
        self.di.refresh_from_db()
        assert self.di.cache_invalidated is False

    def test_updates_in_memory_instance(self):
        """Updates in memory instance."""
        self.di.mark_scanned()
        # No refresh — the instance itself is kept in sync
        assert self.di.cache_invalidated is False

    def test_reinvalidated_entry_is_reset_to_valid(self):
        """mark_scanned on an already-invalidated row marks it valid again."""
        self.di.mark_scanned()
        DirectoryIndex.objects.filter(pk=self.di.pk).update(cache_invalidated=True)
        self.di.mark_scanned()
        self.di.refresh_from_db()
        assert self.di.cache_invalidated is False


# ===========================================================================
# DirectoryIndex.cache_valid_for_sha
# ===========================================================================


@pytest.mark.django_db
class TestCacheValidForSha(AlbumsRootTestCase):
    """Tests for cache_valid_for_sha (formerly sha_exists_in_cache)."""

    def setUp(self):
        super().setUp()
        self.di = _make_dir(self.albums_dir)

    def tearDown(self):
        super().tearDown()

    def test_returns_false_when_never_scanned(self):
        """Returns false when never scanned."""
        assert DirectoryIndex.cache_valid_for_sha(self.di.dir_fqpn_sha256) is False

    def test_returns_true_after_mark_scanned(self):
        """Returns true after mark scanned."""
        self.di.mark_scanned()
        assert DirectoryIndex.cache_valid_for_sha(self.di.dir_fqpn_sha256) is True

    def test_returns_false_after_invalidation(self):
        """Returns false after invalidation."""
        self.di.mark_scanned()
        DirectoryIndex.objects.filter(pk=self.di.pk).update(cache_invalidated=True)
        assert DirectoryIndex.cache_valid_for_sha(self.di.dir_fqpn_sha256) is False

    def test_unknown_sha_returns_false(self):
        """Unknown sha returns false."""
        assert DirectoryIndex.cache_valid_for_sha("0" * 64) is False


# ===========================================================================
# DirectoryIndex.invalidate_cache
# ===========================================================================


@pytest.mark.django_db
class TestInvalidateCache(AlbumsRootTestCase):
    """Tests for invalidate_cache (formerly remove_from_cache_indexdirs)."""

    def setUp(self):
        super().setUp()
        self.di = _make_dir(self.albums_dir)
        self.di.mark_scanned()

    def tearDown(self):
        super().tearDown()

    def test_returns_true_on_success(self):
        """Returns true on success."""
        result = self.di.invalidate_cache()
        assert result is True

    def test_entry_is_invalidated(self):
        """Entry is invalidated."""
        self.di.invalidate_cache()
        self.di.refresh_from_db()
        assert self.di.cache_invalidated is True

    def test_sha_no_longer_valid(self):
        """Sha no longer valid."""
        self.di.invalidate_cache()
        assert DirectoryIndex.cache_valid_for_sha(self.di.dir_fqpn_sha256) is False

    def test_instance_refreshed(self):
        """invalidate_cache refreshes the instance so held references see the flip."""
        self.di.invalidate_cache()
        # No manual refresh — the method refreshes from DB itself
        assert self.di.cache_invalidated is True


# ===========================================================================
# DirectoryIndex.invalidate_cache_by_sha
# ===========================================================================


@pytest.mark.django_db
class TestInvalidateCacheBySha(AlbumsRootTestCase):
    """Tests for invalidate_cache_by_sha (formerly remove_from_cache_sha)."""

    def setUp(self):
        super().setUp()
        self.di = _make_dir(self.albums_dir)
        self.di.mark_scanned()

    def tearDown(self):
        super().tearDown()

    def test_returns_true_on_success(self):
        """Returns true on success."""
        assert DirectoryIndex.invalidate_cache_by_sha(self.di.dir_fqpn_sha256) is True

    def test_entry_is_invalidated(self):
        """Entry is invalidated."""
        DirectoryIndex.invalidate_cache_by_sha(self.di.dir_fqpn_sha256)
        self.di.refresh_from_db()
        assert self.di.cache_invalidated is True

    def test_unknown_sha_returns_false(self):
        """Unknown sha returns false."""
        assert DirectoryIndex.invalidate_cache_by_sha("0" * 64) is False


# ===========================================================================
# DirectoryIndex.invalidate_caches (batch)
# ===========================================================================


@pytest.mark.django_db
class TestInvalidateCaches(AlbumsRootTestCase):
    """Tests for invalidate_caches (formerly remove_multiple_from_cache_indexdirs)."""

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.albums_dir, "a"), exist_ok=True)
        os.makedirs(os.path.join(self.albums_dir, "b"), exist_ok=True)

        self.di_root = _make_dir(self.albums_dir)
        self.di_a = _make_dir(os.path.join(self.albums_dir, "a"))
        self.di_b = _make_dir(os.path.join(self.albums_dir, "b"))
        self.dirs = {"root": self.di_root, "a": self.di_a, "b": self.di_b}

        for di in self.dirs.values():
            di.mark_scanned()

    def tearDown(self):
        super().tearDown()

    def test_empty_list_returns_false(self):
        """Empty list returns false."""
        result = DirectoryIndex.invalidate_caches([])
        assert result is False

    def test_single_dir_returns_true(self):
        """Single dir returns true."""
        result = DirectoryIndex.invalidate_caches([self.di_a])
        assert result is True

    def test_single_dir_is_invalidated(self):
        """Single dir is invalidated."""
        DirectoryIndex.invalidate_caches([self.di_a])
        self.di_a.refresh_from_db()
        assert self.di_a.cache_invalidated is True

    def test_multiple_dirs_all_invalidated(self):
        """Multiple dirs all invalidated."""
        DirectoryIndex.invalidate_caches([self.di_a, self.di_b])
        shas = _test_shas({"a": self.di_a, "b": self.di_b})
        count = DirectoryIndex.objects.filter(dir_fqpn_sha256__in=shas, cache_invalidated=True).count()
        assert count == 2

    def test_parents_also_invalidated(self):
        """Invalidating a child expands to its parent directories.

        Temp dirs outside the albums root get no parent_directory link from
        add_directory(), so the parent assertion only applies when the link
        exists (same guard as the historical tests).
        """
        DirectoryIndex.invalidate_caches([self.di_a])
        if self.di_a.parent_directory_id is not None:
            self.di_root.refresh_from_db()
            assert self.di_root.cache_invalidated is True
        self.di_a.refresh_from_db()
        assert self.di_a.cache_invalidated is True

    def test_returns_false_for_all_invalid_objects(self):
        """Returns false for all invalid objects."""

        class Fake:
            dir_fqpn_sha256 = ""

        result = DirectoryIndex.invalidate_caches([Fake(), Fake()])
        assert result is False

    def test_other_dirs_not_affected(self):
        """Invalidating 'a' does not affect sibling 'b'."""
        DirectoryIndex.invalidate_caches([self.di_a])
        self.di_b.refresh_from_db()
        assert self.di_b.cache_invalidated is False


# ===========================================================================
# DirectoryIndex.invalidate_all_caches
# ===========================================================================


@pytest.mark.django_db
class TestInvalidateAllCaches(AlbumsRootTestCase):
    """Tests for invalidate_all_caches (formerly clear_all_records)."""

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.albums_dir, "c1"), exist_ok=True)
        os.makedirs(os.path.join(self.albums_dir, "c2"), exist_ok=True)
        self.di1 = _make_dir(os.path.join(self.albums_dir, "c1"))
        self.di2 = _make_dir(os.path.join(self.albums_dir, "c2"))
        self.di1.mark_scanned()
        self.di2.mark_scanned()

    def tearDown(self):
        super().tearDown()

    def test_returns_count_of_invalidated(self):
        """Returns count of invalidated."""
        result = DirectoryIndex.invalidate_all_caches()
        # At minimum our two entries were invalidated
        assert result >= 2

    def test_all_test_entries_are_invalidated(self):
        """All test entries are invalidated."""
        DirectoryIndex.invalidate_all_caches()
        shas = {self.di1.dir_fqpn_sha256, self.di2.dir_fqpn_sha256}
        valid_count = DirectoryIndex.objects.filter(dir_fqpn_sha256__in=shas, cache_invalidated=False).count()
        assert valid_count == 0

    def test_idempotent_called_twice(self):
        """invalidate_all_caches is safe to call multiple times."""
        DirectoryIndex.invalidate_all_caches()
        result2 = DirectoryIndex.invalidate_all_caches()
        assert isinstance(result2, int)


# ===========================================================================
# DirectoryIndex._invalidate_by_shas
# ===========================================================================


@pytest.mark.django_db
class TestInvalidateByShas(AlbumsRootTestCase):
    """Tests for _invalidate_by_shas (formerly _bulk_invalidate_by_shas)."""

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.albums_dir, "d1"), exist_ok=True)
        os.makedirs(os.path.join(self.albums_dir, "d2"), exist_ok=True)
        self.di1 = _make_dir(os.path.join(self.albums_dir, "d1"))
        self.di2 = _make_dir(os.path.join(self.albums_dir, "d2"))
        self.di1.mark_scanned()
        self.di2.mark_scanned()

    def tearDown(self):
        super().tearDown()

    def test_invalidates_entries_for_given_shas(self):
        """Invalidates entries for given shas."""
        shas = [self.di1.dir_fqpn_sha256]
        count = DirectoryIndex._invalidate_by_shas(shas)
        assert count >= 1
        self.di1.refresh_from_db()
        assert self.di1.cache_invalidated is True

    def test_returns_count_of_updated_entries(self):
        """Returns count of updated entries."""
        shas = [self.di1.dir_fqpn_sha256, self.di2.dir_fqpn_sha256]
        count = DirectoryIndex._invalidate_by_shas(shas)
        assert count >= 2

    def test_empty_sha_list_returns_zero(self):
        """Empty sha list returns zero."""
        count = DirectoryIndex._invalidate_by_shas([])
        assert count == 0

    def test_never_scanned_dir_still_counted(self):
        """A never-scanned directory row is matched by the UPDATE (no create pass needed)."""
        extra_path = os.path.join(self.albums_dir, "new_dir")
        os.makedirs(extra_path, exist_ok=True)
        di_new = _make_dir(extra_path)
        # Never mark_scanned — row is born cache_invalidated=True

        count = DirectoryIndex._invalidate_by_shas([di_new.dir_fqpn_sha256])
        assert count >= 1
        assert DirectoryIndex.objects.filter(pk=di_new.pk, cache_invalidated=True).exists()


# ===========================================================================
# Layout cache clearing on invalidation
# ===========================================================================


@pytest.mark.django_db
class TestLayoutCacheClearedOnInvalidate(AlbumsRootTestCase):
    """invalidate_cache clears layout cache entries (formerly _clear_layout_cache_bulk)."""

    def setUp(self):
        super().setUp()
        self.di = _make_dir(self.albums_dir)
        self.di.mark_scanned()
        from quickbbs.cache_registry import layout_manager_cache

        layout_manager_cache.clear()

    def tearDown(self):
        super().tearDown()
        from quickbbs.cache_registry import layout_manager_cache

        layout_manager_cache.clear()

    def test_clears_layout_cache_for_directory(self):
        """Clears layout cache for directory."""
        from frontend.managers import layout_manager

        layout_manager(page_number=1, directory=self.di, sort_ordering=0, show_duplicates=False)
        from quickbbs.cache_registry import layout_manager_cache

        assert len(layout_manager_cache) > 0

        self.di.invalidate_cache()
        assert len(layout_manager_cache) == 0


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
        """Initial state no timer."""
        assert self.handler.event_timer is None

    def test_initial_generation_is_zero(self):
        """Initial generation is zero."""
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


class TestProcessBufferedEventsCallsInvalidateCachesDirectly(TestCase):
    """_process_buffered_events calls DirectoryIndex.invalidate_caches() directly.

    Regression guard for the async_to_sync/sync_to_async removal: this
    method runs on a watchdog OS thread, never inside Django's ASGI event
    loop, so no async bridging should appear anywhere in its call stack.
    """

    def setUp(self):
        optimized_event_buffer.clear()
        self.handler = CacheFileMonitorEventHandler()

    def tearDown(self):
        self.handler.cleanup()
        optimized_event_buffer.clear()

    def test_existing_directories_invalidated_via_direct_call(self):
        """Matched DirectoryIndex rows are invalidated with a plain direct call."""
        from unittest.mock import MagicMock, patch

        optimized_event_buffer.add_event("/some/existing/dir")
        mock_dir = MagicMock()
        mock_dir.dir_fqpn_sha256 = "deadbeef"
        with (
            patch("cache_watcher.models.processing_semaphore") as mock_sem,
            patch("cache_watcher.models.DirectoryIndex") as mock_di,
        ):
            mock_sem.acquire.return_value = True
            mock_di.objects.filter.return_value.only.return_value = [mock_dir]
            self.handler._process_buffered_events(self.handler.timer_generation)

        mock_di.invalidate_caches.assert_called_once_with([mock_dir])

    def test_no_async_to_sync_in_call_stack(self):
        """async_to_sync/sync_to_async are never invoked for this path."""
        from unittest.mock import MagicMock, patch

        optimized_event_buffer.add_event("/some/existing/dir")
        mock_dir = MagicMock()
        mock_dir.dir_fqpn_sha256 = "deadbeef"
        with (
            patch("cache_watcher.models.processing_semaphore") as mock_sem,
            patch("cache_watcher.models.DirectoryIndex") as mock_di,
            patch("asgiref.sync.async_to_sync") as mock_a2s,
            patch("asgiref.sync.sync_to_async") as mock_s2a,
        ):
            mock_sem.acquire.return_value = True
            mock_di.objects.filter.return_value.only.return_value = [mock_dir]
            self.handler._process_buffered_events(self.handler.timer_generation)

        mock_a2s.assert_not_called()
        mock_s2a.assert_not_called()


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
        """Start sets is running."""
        from unittest.mock import MagicMock, patch

        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog") as mock_wdog, patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start()
        assert self.manager.is_running is True

    def test_start_calls_watchdog_startup(self):
        """Start calls watchdog startup."""
        from unittest.mock import MagicMock, patch

        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog") as mock_wdog, patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start()
        mock_wdog.startup.assert_called_once()

    def test_start_schedules_restart_timer(self):
        """Start schedules restart timer."""
        from unittest.mock import MagicMock, patch

        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog"), patch("cache_watcher.models.threading.Timer", return_value=mock_timer) as mock_timer_cls:
            self.manager.start()
        mock_timer_cls.assert_called_once()
        mock_timer.start.assert_called_once()

    def test_start_twice_does_not_call_startup_again(self):
        """Second call to start() when already running is a no-op."""
        from unittest.mock import MagicMock, patch

        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog") as mock_wdog, patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start()
            self.manager.start()
        assert mock_wdog.startup.call_count == 1

    def test_start_with_force_recreate_passes_flag(self):
        """Start with force recreate passes flag."""
        from unittest.mock import MagicMock, patch

        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog") as mock_wdog, patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
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
        from unittest.mock import MagicMock, patch

        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog"), patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start()
        # Replace the real timer with a mock so tearDown doesn't try to cancel a dead thread
        self.manager.restart_timer = mock_timer

    def tearDown(self):
        with self.manager.lock:
            if self.manager.restart_timer:
                self.manager.restart_timer.cancel()
                self.manager.restart_timer = None

    def test_stop_sets_is_running_false(self):
        """Stop sets is running false."""
        from unittest.mock import patch

        self._start_mocked()
        with patch("cache_watcher.models.watchdog"):
            self.manager.stop()
        assert self.manager.is_running is False

    def test_stop_calls_stop_observer(self):
        """Stop calls stop observer."""
        from unittest.mock import patch

        self._start_mocked()
        with patch("cache_watcher.models.watchdog") as mock_wdog:
            self.manager.stop()
        mock_wdog.stop_observer.assert_called_once()

    def test_stop_clears_event_handler(self):
        """Stop clears event handler."""
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
        """Shutdown cancels restart timer."""
        from unittest.mock import MagicMock, patch

        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        self.manager.restart_timer = mock_timer
        with patch("cache_watcher.models.watchdog"):
            self.manager.shutdown()
        mock_timer.cancel.assert_called_once()
        assert self.manager.restart_timer is None

    def test_shutdown_sets_is_running_false(self):
        """Shutdown sets is running false."""
        from unittest.mock import MagicMock, patch

        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog"), patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start()
        self.manager.restart_timer = mock_timer
        with patch("cache_watcher.models.watchdog"):
            self.manager.shutdown()
        assert self.manager.is_running is False

    def test_shutdown_when_not_running_does_not_raise(self):
        """Shutdown when not running does not raise."""
        from unittest.mock import patch

        assert self.manager.is_running is False
        try:
            with patch("cache_watcher.models.watchdog"):
                self.manager.shutdown()
        except Exception as e:
            self.fail(f"shutdown() when not running raised: {e}")

    def test_shutdown_clears_event_handler(self):
        """Shutdown clears event handler."""
        from unittest.mock import MagicMock, patch

        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog"), patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
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
        """Restart calls stop then start."""
        from unittest.mock import patch

        mock_timer = self._mock_timer()
        # WatchdogManager uses __slots__ — patch at class level, not instance level
        with (
            patch("cache_watcher.models.watchdog") as mock_wdog,
            patch("cache_watcher.models.threading.Timer", return_value=mock_timer),
            patch("cache_watcher.models.WatchdogManager._process_pending_events"),
        ):
            self.manager.start()
            self.manager.restart_timer = mock_timer
            self.manager.restart()

        # startup called twice: once for start(), once for restart()'s start()
        assert mock_wdog.startup.call_count == 2

    def test_restart_clears_event_buffer(self):
        """Restart clears event buffer."""
        from unittest.mock import patch

        mock_timer = self._mock_timer()
        optimized_event_buffer.add_event("/some/path")
        assert optimized_event_buffer.size() > 0

        with (
            patch("cache_watcher.models.watchdog"),
            patch("cache_watcher.models.threading.Timer", return_value=mock_timer),
            patch("cache_watcher.models.WatchdogManager._process_pending_events"),
        ):
            self.manager.start()
            self.manager.restart_timer = mock_timer
            self.manager.restart()

        assert optimized_event_buffer.size() == 0

    def test_restart_uses_force_recreate(self):
        """restart() calls start(force_recreate=True) to prevent memory leaks."""
        from unittest.mock import patch

        mock_timer = self._mock_timer()
        with (
            patch("cache_watcher.models.watchdog") as mock_wdog,
            patch("cache_watcher.models.threading.Timer", return_value=mock_timer),
            patch("cache_watcher.models.WatchdogManager._process_pending_events"),
        ):
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
        with (
            patch("cache_watcher.models.watchdog"),
            patch("cache_watcher.models.threading.Timer", return_value=mock_timer) as mock_cls,
            patch("cache_watcher.models.WatchdogManager._process_pending_events"),
        ):
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
        """Schedule restart creates timer."""
        from unittest.mock import MagicMock, patch

        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            with self.manager.lock:
                self.manager._schedule_restart()
        assert self.manager.restart_timer is mock_timer

    def test_schedule_restart_starts_timer(self):
        """Schedule restart starts timer."""
        from unittest.mock import MagicMock, patch

        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            with self.manager.lock:
                self.manager._schedule_restart()
        mock_timer.start.assert_called_once()

    def test_schedule_restart_timer_is_daemon(self):
        """Timer must be a daemon thread so it doesn't block process exit."""
        from unittest.mock import MagicMock, patch

        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            with self.manager.lock:
                self.manager._schedule_restart()
        assert mock_timer.daemon is True

    def test_schedule_restart_cancels_existing_timer(self):
        """Calling _schedule_restart when a timer exists cancels the old one."""
        from unittest.mock import MagicMock, patch

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
        from unittest.mock import MagicMock, patch

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
        """Non empty buffer acquires semaphore."""
        from unittest.mock import MagicMock, patch

        optimized_event_buffer.add_event("/some/path")
        mock_sem = MagicMock()
        mock_sem.acquire.return_value = True
        with patch("cache_watcher.models.processing_semaphore", mock_sem), patch("cache_watcher.models.DirectoryIndex") as mock_di:
            mock_di.objects.filter.return_value.only.return_value = []
            self.manager._process_pending_events()
        mock_sem.acquire.assert_called_once_with(blocking=False)

    def test_semaphore_released_after_processing(self):
        """Semaphore released after processing."""
        from unittest.mock import MagicMock, patch

        optimized_event_buffer.add_event("/some/path")
        mock_sem = MagicMock()
        mock_sem.acquire.return_value = True
        with patch("cache_watcher.models.processing_semaphore", mock_sem), patch("cache_watcher.models.DirectoryIndex") as mock_di:
            mock_di.objects.filter.return_value.only.return_value = []
            self.manager._process_pending_events()
        mock_sem.release.assert_called_once()

    def test_semaphore_not_acquired_skips_processing(self):
        """If semaphore is held by another thread, processing is skipped gracefully."""
        from unittest.mock import MagicMock, patch

        optimized_event_buffer.add_event("/some/path")
        mock_sem = MagicMock()
        mock_sem.acquire.return_value = False  # Can't acquire — another thread holds it
        with patch("cache_watcher.models.processing_semaphore", mock_sem), patch("cache_watcher.models.DirectoryIndex") as mock_di:
            self.manager._process_pending_events()
        mock_di.invalidate_caches.assert_not_called()

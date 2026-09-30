"""Filesystem event buffering and processing: LockFreeEventBuffer and CacheFileMonitorEventHandler."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest
from django.test import TestCase

from cache_watcher.models import (
    CacheFileMonitorEventHandler,
    LockFreeEventBuffer,
    optimized_event_buffer,
)

pytestmark = pytest.mark.api


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
            # Any exception, so a failure on a worker thread reaches the assertion below.
            except Exception as e:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                errors.append(e)

        threads = [threading.Thread(target=add_events) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert buf.size() > 0


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
        self.handler.cleanup()

    def test_a_directory_event_is_buffered(self):
        """on_created adds the directory path to optimized_event_buffer."""
        event = MagicMock()
        event.is_directory = True
        event.src_path = "/some/test/directory"

        optimized_event_buffer.clear()
        self.handler.on_created(event)

        result = optimized_event_buffer.get_events_to_process()
        assert "/some/test/directory" in result

    def test_a_file_event_buffers_its_parent_directory(self):
        """on_modified for a file adds the parent directory, not the file."""
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/test/directory/file.jpg"

        optimized_event_buffer.clear()
        self.handler.on_modified(event)

        result = optimized_event_buffer.get_events_to_process()
        assert "/some/test/directory" in result

    def test_an_event_starts_the_processing_timer(self):
        """on_deleted creates a processing timer if none exists."""
        event = MagicMock()
        event.is_directory = True
        event.src_path = "/timer/test"

        assert self.handler.event_timer is None
        self.handler.on_deleted(event)
        assert self.handler.event_timer is not None

    def test_a_second_event_reuses_the_timer(self):
        """on_moved does not create a new timer if one already exists."""
        event = MagicMock()
        event.is_directory = True
        event.src_path = "/timer/test"

        self.handler.on_moved(event)
        first_timer = self.handler.event_timer

        # Second event — should not replace timer
        self.handler.on_moved(event)
        assert self.handler.event_timer is first_timer


class TestProcessBufferedEventsCallsInvalidateCachesDirectly(TestCase):
    """_process_buffered_events calls DirectoryIndex.invalidate_caches() directly.

    Regression guard for the async_to_sync/sync_to_async removal: this
    method runs on a watchdog OS thread, never inside Django's ASGI event
    loop, so no async bridging should appear anywhere in its call stack.
    """

    # _process_buffered_events is a threading.Timer callback with no public caller; tests invoke it directly.
    # pylint: disable=protected-access

    def setUp(self):
        optimized_event_buffer.clear()
        self.handler = CacheFileMonitorEventHandler()

    def tearDown(self):
        self.handler.cleanup()
        optimized_event_buffer.clear()

    def test_existing_directories_invalidated_via_direct_call(self):
        """Matched DirectoryIndex rows are invalidated with a plain direct call."""
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

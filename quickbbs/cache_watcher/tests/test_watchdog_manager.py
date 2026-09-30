"""WatchdogManager start, stop, shutdown, restart and pending-event processing, driven through mocks.

watchdog.startup and watchdog.stop_observer are patched where cache_watcher.models
imports them, and threading.Timer is patched, so no real threads or timers are
created. Each test builds its own WatchdogManager, so the instance apps.py starts
does not interfere.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from django.test import TestCase

from cache_watcher.models import (
    WATCHDOG_RESTART_INTERVAL,
    WatchdogManager,
    optimized_event_buffer,
)
from quickbbs.common import get_dir_sha
from quickbbs.models import DirectoryIndex
from quickbbs.tests.albums_root import AlbumsRootTestCase

pytestmark = pytest.mark.api


class TestWatchdogManagerStart(TestCase):
    """Tests for WatchdogManager.start()."""

    def setUp(self):
        self.manager = WatchdogManager()

    def tearDown(self):
        # Ensure no real timer is running after each test
        with self.manager.lock:
            if self.manager.restart_timer:
                self.manager.restart_timer.cancel()
                self.manager.restart_timer = None

    def test_start_sets_is_running(self):
        """Start sets is running."""
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog"), patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start()
        assert self.manager.is_running is True

    def test_start_calls_watchdog_startup(self):
        """Start calls watchdog startup."""
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog") as mock_wdog, patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start()
        mock_wdog.startup.assert_called_once()

    def test_start_schedules_restart_timer(self):
        """Start schedules restart timer."""
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog"), patch("cache_watcher.models.threading.Timer", return_value=mock_timer) as mock_timer_cls:
            self.manager.start()
        mock_timer_cls.assert_called_once()
        mock_timer.start.assert_called_once()

    def test_start_twice_does_not_call_startup_again(self):
        """Second call to start() when already running is a no-op."""
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog") as mock_wdog, patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start()
            self.manager.start()
        assert mock_wdog.startup.call_count == 1

    def test_start_with_force_recreate_passes_flag(self):
        """Start with force recreate passes flag."""
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        with patch("cache_watcher.models.watchdog") as mock_wdog, patch("cache_watcher.models.threading.Timer", return_value=mock_timer):
            self.manager.start(force_recreate=True)
        _, kwargs = mock_wdog.startup.call_args
        assert kwargs.get("force_recreate") is True


class TestWatchdogManagerStop(TestCase):
    """Tests for WatchdogManager.stop()."""

    def setUp(self):
        self.manager = WatchdogManager()

    def _start_mocked(self):
        """Start the manager with all external calls mocked."""
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
        self._start_mocked()
        with patch("cache_watcher.models.watchdog"):
            self.manager.stop()
        assert self.manager.is_running is False

    def test_stop_calls_stop_observer(self):
        """Stop calls stop observer."""
        self._start_mocked()
        with patch("cache_watcher.models.watchdog") as mock_wdog:
            self.manager.stop()
        mock_wdog.stop_observer.assert_called_once()

    def test_stop_clears_event_handler(self):
        """Stop clears event handler."""
        self._start_mocked()
        with patch("cache_watcher.models.watchdog"):
            self.manager.stop()
        assert self.manager.event_handler is None

    def test_stop_when_not_running_is_safe(self):
        """stop() on an already-stopped manager does nothing."""
        assert self.manager.is_running is False
        with patch("cache_watcher.models.watchdog") as mock_wdog:
            self.manager.stop()
        mock_wdog.stop_observer.assert_not_called()


class TestWatchdogManagerShutdown(TestCase):
    """Tests for WatchdogManager.shutdown()."""

    def setUp(self):
        self.manager = WatchdogManager()

    def test_shutdown_cancels_restart_timer(self):
        """Shutdown cancels restart timer."""
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        self.manager.restart_timer = mock_timer
        with patch("cache_watcher.models.watchdog"):
            self.manager.shutdown()
        mock_timer.cancel.assert_called_once()
        assert self.manager.restart_timer is None

    def test_shutdown_sets_is_running_false(self):
        """Shutdown sets is running false."""
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
        assert self.manager.is_running is False
        with patch("cache_watcher.models.watchdog"):
            self.manager.shutdown()

    def test_shutdown_clears_event_handler(self):
        """Shutdown clears event handler."""
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
        self.manager = WatchdogManager()

    def tearDown(self):
        with self.manager.lock:
            if self.manager.restart_timer:
                self.manager.restart_timer.cancel()
                self.manager.restart_timer = None

    def _mock_timer(self):
        t = MagicMock()
        t.is_alive.return_value = True
        return t

    def test_restart_calls_stop_then_start(self):
        """Restart calls stop then start."""
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


class TestWatchdogManagerRestartTimer(TestCase):
    """The restart timer start() schedules (WatchdogManager._schedule_restart())."""

    def setUp(self):
        self.manager = WatchdogManager()
        self.timer = MagicMock()
        self.timer.is_alive.return_value = True

    def tearDown(self):
        with self.manager.lock:
            if self.manager.restart_timer:
                self.manager.restart_timer.cancel()
                self.manager.restart_timer = None

    def _start(self) -> MagicMock:
        """Start the manager with the watchdog and threading.Timer mocked; return the Timer class mock."""
        with patch("cache_watcher.models.watchdog"), patch("cache_watcher.models.threading.Timer", return_value=self.timer) as timer_class:
            self.manager.start()
        return timer_class

    def test_the_timer_is_kept_as_restart_timer(self):
        """start() stores the scheduled timer on the manager."""
        self._start()
        assert self.manager.restart_timer is self.timer

    def test_the_timer_is_a_daemon(self):
        """Timer must be a daemon thread so it doesn't block process exit."""
        self._start()
        assert self.timer.daemon is True

    def test_an_existing_timer_is_cancelled(self):
        """A timer already scheduled is cancelled and replaced."""
        old_timer = MagicMock()
        self.manager.restart_timer = old_timer
        self._start()
        old_timer.cancel.assert_called_once()
        assert self.manager.restart_timer is self.timer

    def test_the_timer_uses_the_configured_interval(self):
        """Timer is created with WATCHDOG_RESTART_INTERVAL."""
        timer_class = self._start()
        assert timer_class.call_args[0][0] == WATCHDOG_RESTART_INTERVAL


class TestWatchdogManagerProcessPendingEvents(TestCase):
    """Tests for WatchdogManager._process_pending_events()."""

    # _process_pending_events runs only inside restart(); tests invoke it directly to test it alone.
    # pylint: disable=protected-access

    def setUp(self):
        self.manager = WatchdogManager()
        optimized_event_buffer.clear()

    def tearDown(self):
        optimized_event_buffer.clear()

    def test_empty_buffer_returns_immediately(self):
        """No semaphore acquisition when buffer is empty."""
        assert optimized_event_buffer.size() == 0
        with patch("cache_watcher.models.processing_semaphore") as mock_sem:
            self.manager._process_pending_events()
        mock_sem.acquire.assert_not_called()

    def test_non_empty_buffer_acquires_semaphore(self):
        """Non empty buffer acquires semaphore."""
        optimized_event_buffer.add_event("/some/path")
        mock_sem = MagicMock()
        mock_sem.acquire.return_value = True
        with patch("cache_watcher.models.processing_semaphore", mock_sem), patch("cache_watcher.models.DirectoryIndex") as mock_di:
            mock_di.objects.filter.return_value.only.return_value = []
            self.manager._process_pending_events()
        mock_sem.acquire.assert_called_once_with(blocking=False)

    def test_semaphore_released_after_processing(self):
        """Semaphore released after processing."""
        optimized_event_buffer.add_event("/some/path")
        mock_sem = MagicMock()
        mock_sem.acquire.return_value = True
        with patch("cache_watcher.models.processing_semaphore", mock_sem), patch("cache_watcher.models.DirectoryIndex") as mock_di:
            mock_di.objects.filter.return_value.only.return_value = []
            self.manager._process_pending_events()
        mock_sem.release.assert_called_once()

    def test_semaphore_not_acquired_skips_processing(self):
        """If semaphore is held by another thread, processing is skipped gracefully."""
        optimized_event_buffer.add_event("/some/path")
        mock_sem = MagicMock()
        mock_sem.acquire.return_value = False  # Can't acquire — another thread holds it
        with patch("cache_watcher.models.processing_semaphore", mock_sem), patch("cache_watcher.models.DirectoryIndex") as mock_di:
            self.manager._process_pending_events()
        mock_di.invalidate_caches.assert_not_called()


@pytest.mark.django_db
class TestPendingEventsAddNewDirectories(AlbumsRootTestCase):
    """Events processed before a restart add new directories, as buffered processing does."""

    # _process_pending_events runs only inside restart(); tests invoke it directly to test it alone.
    # pylint: disable=protected-access

    def setUp(self):
        super().setUp()
        optimized_event_buffer.clear()

    def tearDown(self):
        optimized_event_buffer.clear()
        super().tearDown()

    def test_a_new_directory_gets_an_index_row_and_its_parent_is_invalidated(self):
        """A directory on disk with no DirectoryIndex row is added; its parent is invalidated."""
        parent = self.add_directory("parent")
        parent.mark_scanned()
        new_path = os.path.join(self.albums_dir, "parent", "new")
        os.makedirs(new_path)
        optimized_event_buffer.add_event(new_path)

        self.keep_connection_open("cache_watcher.models")
        WatchdogManager()._process_pending_events()

        assert DirectoryIndex.objects.filter(dir_fqpn_sha256=get_dir_sha(new_path)).exists()
        parent.refresh_from_db()
        assert parent.cache_invalidated is True

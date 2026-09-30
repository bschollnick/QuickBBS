"""Watchdog lock-file handling in cache_watcher.apps."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cache_watcher.apps import _remove_stale_lock

pytestmark = pytest.mark.api


class TestRemoveStaleLock:
    """`_remove_stale_lock` deletes a lock file only when its recorded PID is gone."""

    def test_a_dead_pid_removes_the_file(self, tmp_path):
        """ProcessLookupError means the PID is gone: the file is removed."""
        lock = tmp_path / "watchdog.lock"
        lock.write_text("12345\n", encoding="utf-8")
        with patch("cache_watcher.apps.os.kill", side_effect=ProcessLookupError):
            _remove_stale_lock(str(lock))
        assert not lock.exists()

    def test_another_users_pid_is_treated_as_live(self, tmp_path):
        """PermissionError means the PID exists under another user: the file stays."""
        lock = tmp_path / "watchdog.lock"
        lock.write_text("12345\n", encoding="utf-8")
        with patch("cache_watcher.apps.os.kill", side_effect=PermissionError):
            _remove_stale_lock(str(lock))
        assert lock.exists()

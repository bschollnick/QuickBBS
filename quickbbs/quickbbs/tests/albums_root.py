"""Test base for tests that need ALBUMS_PATH pointed at a temporary albums root."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest import mock

from django.test import TestCase, override_settings

from quickbbs.models import DirectoryIndex


class AlbumsRootMixin(unittest.TestCase):
    """Point ALBUMS_PATH at a fresh temporary directory for each test, and remove it afterwards.

    Combine with any Django test class, including `SimpleTestCase`, by listing it first.
    `DirectoryIndex.add_directory()` rejects paths outside `<ALBUMS_PATH>/albums`,
    so every directory a test registers lives under `self.albums_dir`.

    Attributes set by `setUp()`:
        temp_dir: The temporary directory, resolved through symlinks (macOS
            `/var` is `/private/var`) so it matches `normalize_fqpn()` output.
        albums_path_setting: The ALBUMS_PATH value: `temp_dir`, or
            `temp_dir/<albums_path_subdirectory>` when that is set.
        albums_dir: `<albums_path_setting>/albums`, created empty.
    """

    #: Put ALBUMS_PATH in this subdirectory of temp_dir instead of temp_dir itself.
    albums_path_subdirectory = ""

    #: Extra settings to override alongside ALBUMS_PATH (read-only; subclasses replace it).
    extra_settings: ClassVar[dict[str, object]] = {}

    def setUp(self) -> None:
        super().setUp()
        self.temp_dir = str(Path(tempfile.mkdtemp()).resolve())
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.albums_path_setting = os.path.join(self.temp_dir, self.albums_path_subdirectory) if self.albums_path_subdirectory else self.temp_dir
        self.albums_dir = os.path.join(self.albums_path_setting, "albums")
        os.makedirs(self.albums_dir, exist_ok=True)
        settings_override = override_settings(ALBUMS_PATH=self.albums_path_setting, **self.extra_settings)
        settings_override.enable()
        self.addCleanup(settings_override.disable)

    def keep_connection_open(self, *modules: str) -> None:
        """Replace `close_old_connections` in each named module with a no-op for this test.

        The code under test calls it after its work; with CONN_MAX_AGE=0 that closes
        the connection, which TestCase's transaction cannot reopen.
        """
        for module in modules:
            patcher = mock.patch(f"{module}.close_old_connections")
            patcher.start()
            self.addCleanup(patcher.stop)

    def add_directory(self, *relative_parts: str) -> DirectoryIndex:
        """Create `albums_dir/<relative_parts>` on disk and register it; no parts means `albums_dir` itself."""
        path = os.path.join(self.albums_dir, *relative_parts)
        os.makedirs(path, exist_ok=True)
        _, directory = DirectoryIndex.add_directory(path + os.sep)
        assert directory is not None, f"add_directory rejected {path}"
        return directory


class AlbumsRootTestCase(AlbumsRootMixin, TestCase):
    """Database TestCase with ALBUMS_PATH pointed at a temporary albums root (see AlbumsRootMixin)."""

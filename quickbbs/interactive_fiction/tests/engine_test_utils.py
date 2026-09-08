"""Shared generic-engine test helpers — not a test module itself (no
Test* classes).
"""

from __future__ import annotations

import unittest

from django.test import override_settings

from quickbbs.directoryindex import DirectoryIndex


class AlbumsPathOverrideMixin(unittest.TestCase):
    """Shared setUp/cleanup for a test that overrides settings.ALBUMS_PATH
    to an isolated temp directory and must also reset DirectoryIndex's own
    cached albums-root path -- otherwise a later test's own
    override_settings(ALBUMS_PATH=...) would silently resolve against a
    stale cached value from this one.

    Used by any test needing an isolated Albums tree for
    discover_api_descriptors() (which always derives its games directory
    from DirectoryIndex.get_albums_root(), never a raw ALBUMS_PATH),
    factored out after this exact setUp/cleanup pair was duplicated across
    three test classes (pylint duplicate-code).
    """

    def setUp(self) -> None:
        """Override ALBUMS_PATH to `self.temp_dir` and reset
        DirectoryIndex's cache. Subclasses that need `self.temp_dir` set
        to something specific (e.g. a pre-built directory) must set it
        BEFORE calling super().setUp()."""
        if not hasattr(self, "temp_dir"):
            import tempfile  # pylint: disable=import-outside-toplevel

            self.temp_dir = tempfile.mkdtemp()
        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir)
        self._settings_override.enable()
        DirectoryIndex._albums_prefix = None  # pylint: disable=protected-access
        DirectoryIndex._albums_root = None  # pylint: disable=protected-access
        self.addCleanup(self._settings_override.disable)
        self.addCleanup(self._reset_albums_root_cache)

    @staticmethod
    def _reset_albums_root_cache() -> None:
        """Clear DirectoryIndex's cached albums-root path so a later
        test's own override_settings(ALBUMS_PATH=...) isn't shadowed by
        this test's cached value."""
        DirectoryIndex._albums_prefix = None  # pylint: disable=protected-access
        DirectoryIndex._albums_root = None  # pylint: disable=protected-access

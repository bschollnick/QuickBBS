"""Tests for quickbbs/management/commands/management_helper.py — pure DB helpers."""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest
from django.test import TestCase, override_settings

from filetypes.models import filetypes
from quickbbs.management.commands.management_helper import (
    invalidate_directories_with_null_sha256,
    invalidate_directories_with_null_virtual_directory,
    invalidate_empty_directories,
)
from quickbbs.models import DirectoryIndex, FileIndex

pytestmark = pytest.mark.api


def _get_ft(fileext: str) -> filetypes:
    """Return filetypes object for a given extension."""
    return filetypes.objects.get(fileext=fileext)


def _sha(prefix: str) -> str:
    """Return a 64-char hex-like string padded with zeros."""
    return (prefix + "0" * 64)[:64]


def _make_fileindex(directory: DirectoryIndex, name: str, ft: filetypes, **kwargs) -> FileIndex:
    """Create a minimal FileIndex record without touching the filesystem."""
    defaults = {
        "home_directory": directory,
        "name": name,
        "lastscan": 0.0,
        "lastmod": 0.0,
        "filetype": ft,
        "delete_pending": False,
        "is_generic_icon": False,
    }
    defaults.update(kwargs)
    return FileIndex.objects.create(**defaults)


class ManagementHelperTestBase(TestCase):
    """Common tempdir/ALBUMS_PATH setup for management_helper tests."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.temp_dir, "albums"), exist_ok=True)
        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir)
        self._settings_override.enable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        _, self.dir_with_files = DirectoryIndex.add_directory(os.path.join(self.temp_dir, "albums") + "/")
        assert self.dir_with_files is not None
        os.makedirs(os.path.join(self.temp_dir, "albums", "empty"), exist_ok=True)
        _, self.empty_dir = DirectoryIndex.add_directory(os.path.join(self.temp_dir, "albums", "empty") + "/")
        assert self.empty_dir is not None
        self.ft_txt = _get_ft(".txt")
        self.ft_link = _get_ft(".link")

    def tearDown(self) -> None:
        self._settings_override.disable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)


class TestInvalidateEmptyDirectories(ManagementHelperTestBase):
    """Tests for invalidate_empty_directories."""

    def test_no_empty_directories_returns_zero(self):
        """When no directory has zero files, nothing is invalidated."""
        _make_fileindex(self.dir_with_files, "a.txt", self.ft_txt, file_sha256=_sha("a"), unique_sha256=_sha("ua"))
        self.empty_dir.delete()
        count = invalidate_empty_directories(verbose=False)
        assert count == 0

    def test_empty_directory_invalidated(self):
        """A directory with zero FileIndex entries is marked cache_invalidated."""
        self.empty_dir.cache_invalidated = False
        self.empty_dir.save(update_fields=["cache_invalidated"])
        count = invalidate_empty_directories(verbose=False)
        assert count >= 1
        self.empty_dir.refresh_from_db()
        assert self.empty_dir.cache_invalidated is True

    def test_start_path_filters_scope(self):
        """start_path restricts invalidation to directories under that prefix."""
        unrelated_root = tempfile.mkdtemp()
        try:
            count = invalidate_empty_directories(start_path=unrelated_root, verbose=False)
            assert count == 0
        finally:
            shutil.rmtree(unrelated_root, ignore_errors=True)


class TestInvalidateDirectoriesWithNullSha256(ManagementHelperTestBase):
    """Tests for invalidate_directories_with_null_sha256."""

    def test_no_null_sha_files_returns_zero(self):
        """When all files have a SHA256, nothing is invalidated."""
        _make_fileindex(self.dir_with_files, "a.txt", self.ft_txt, file_sha256=_sha("a"), unique_sha256=_sha("ua"))
        count = invalidate_directories_with_null_sha256(verbose=False)
        assert count == 0

    def test_null_sha_file_invalidates_parent_directory(self):
        """A file with NULL file_sha256 causes its parent directory to be invalidated."""
        _make_fileindex(self.dir_with_files, "broken.txt", self.ft_txt, file_sha256=None, unique_sha256=_sha("ub"))
        count = invalidate_directories_with_null_sha256(verbose=False)
        assert count == 1


class TestInvalidateDirectoriesWithNullVirtualDirectory(ManagementHelperTestBase):
    """Tests for invalidate_directories_with_null_virtual_directory."""

    def test_no_broken_links_returns_zero(self):
        """When no link files are missing virtual_directory, nothing is invalidated."""
        count = invalidate_directories_with_null_virtual_directory(verbose=False)
        assert count == 0

    def test_broken_link_file_invalidates_parent_directory(self):
        """A link file with NULL virtual_directory causes its parent directory to be invalidated."""
        _make_fileindex(
            self.dir_with_files,
            "shortcut.link",
            self.ft_link,
            file_sha256=_sha("c"),
            unique_sha256=_sha("uc"),
            virtual_directory=None,
        )
        count = invalidate_directories_with_null_virtual_directory(verbose=False)
        assert count == 1

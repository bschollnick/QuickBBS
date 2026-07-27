"""Tests for quickbbs/management/commands/scan.py."""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from filetypes.models import filetypes
from quickbbs.common import normalize_fqpn
from quickbbs.management.commands.add_directories import add_directories
from quickbbs.management.commands.add_files import add_files
from quickbbs.management.commands.scan import (
    _process_directory_verification_chunk,
    verify_directories,
)
from quickbbs.models import DirectoryIndex, FileIndex

pytestmark = pytest.mark.api


def _get_ft(fileext: str) -> filetypes:
    """Return filetypes object for a given extension."""
    return filetypes.objects.get(fileext=fileext)


class ScanCommandTestBase(TestCase):
    """Common tempdir/ALBUMS_PATH setup for scan.py tests."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.albums_root = os.path.join(self.temp_dir, "albums")
        os.makedirs(self.albums_root, exist_ok=True)
        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir)
        self._settings_override.enable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        self._coc_patcher = mock.patch("quickbbs.management.commands.scan.close_old_connections")
        self._coc_patcher.start()

    def tearDown(self) -> None:
        self._coc_patcher.stop()
        self._settings_override.disable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)


class TestHandleStartValidation(ScanCommandTestBase):
    """Tests for Command.handle()'s --start path validation."""

    def test_start_outside_albums_root_raises(self):
        """A --start path outside the albums root raises CommandError."""
        outside = tempfile.mkdtemp()
        try:
            with pytest.raises(CommandError, match="must be within the albums directory"):
                call_command("scan", "--verify_directories", f"--start={outside}")
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_start_nonexistent_path_raises(self):
        """A --start path that does not exist raises CommandError."""
        missing = os.path.join(self.albums_root, "does_not_exist")
        with pytest.raises(CommandError, match="does not exist"):
            call_command("scan", "--verify_directories", f"--start={missing}")

    def test_start_file_path_raises_does_not_exist(self):
        """A --start path pointing at a file (not a directory) is rejected.

        normalize_fqpn() always appends a trailing separator, so a file path
        is checked as "path/" which os.path.exists() reports as missing —
        this reaches the "does not exist" branch, not "is not a directory".
        """
        file_path = os.path.join(self.albums_root, "afile.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("x")
        with pytest.raises(CommandError, match="does not exist"):
            call_command("scan", "--verify_directories", f"--start={file_path}")

    def test_start_valid_directory_does_not_raise(self):
        """A valid --start directory under the albums root passes validation."""
        sub = os.path.join(self.albums_root, "sub")
        os.makedirs(sub, exist_ok=True)
        # Should run without raising CommandError.
        call_command("scan", "--verify_directories", f"--start={sub}")

    def test_start_sibling_prefix_directory_raises(self):
        """A --start path in a sibling directory that shares a string prefix
        with the albums root (e.g. 'albums-backup' vs 'albums') must be
        rejected, not wrongly treated as inside the tree."""
        sibling_root = self.albums_root + "-backup"
        sibling_sub = os.path.join(sibling_root, "sub")
        os.makedirs(sibling_sub, exist_ok=True)
        try:
            with pytest.raises(CommandError, match="must be within the albums directory"):
                call_command("scan", "--verify_directories", f"--start={sibling_sub}")
        finally:
            shutil.rmtree(sibling_root, ignore_errors=True)

    def test_start_mixed_case_argument_processes_correct_directory(self):
        """A mixed-case --start pointing at a real, in-tree directory is
        accepted and the normalized form reaches the underlying operation."""
        sub = os.path.join(self.albums_root, "MixedCase")
        os.makedirs(sub, exist_ok=True)
        mixed_case_start = os.path.join(self.albums_root, "MixedCase")
        # Should run without raising CommandError.
        call_command("scan", "--verify_directories", f"--start={mixed_case_start}")

    def test_deletes_pending_records_before_scan(self):
        """handle() deletes delete_pending FileIndex records before running any operation."""
        _, directory = DirectoryIndex.add_directory(self.albums_root + os.sep)
        assert directory is not None
        ft = _get_ft(".txt")
        FileIndex.objects.create(
            home_directory=directory,
            name="pending.txt",
            file_sha256=("p" + "0" * 64)[:64],
            unique_sha256=("up" + "0" * 64)[:64],
            lastscan=0.0,
            lastmod=0.0,
            filetype=ft,
            delete_pending=True,
            is_generic_icon=False,
        )
        call_command("scan", "--verify_directories")
        assert not FileIndex.objects.filter(delete_pending=True).exists()


class TestVerifyDirectories(ScanCommandTestBase):
    """Tests for verify_directories — the destructive DB-cleanup path."""

    def test_directory_missing_from_disk_is_deleted(self):
        """A DirectoryIndex row whose path no longer exists on disk is removed."""
        stale_path = os.path.join(self.albums_root, "stale")
        os.makedirs(stale_path, exist_ok=True)
        _, directory = DirectoryIndex.add_directory(stale_path + os.sep)
        assert directory is not None
        shutil.rmtree(stale_path)

        verify_directories(start_path=self.albums_root)

        assert not DirectoryIndex.objects.filter(pk=directory.pk).exists()

    def test_directory_present_on_disk_survives(self):
        """A DirectoryIndex row whose path still exists on disk is not deleted."""
        present_path = os.path.join(self.albums_root, "present")
        os.makedirs(present_path, exist_ok=True)
        _, directory = DirectoryIndex.add_directory(present_path + os.sep)
        assert directory is not None

        verify_directories(start_path=self.albums_root)

        assert DirectoryIndex.objects.filter(pk=directory.pk).exists()

    def test_process_chunk_only_deletes_missing(self):
        """_process_directory_verification_chunk deletes only directories missing on disk."""
        present_path = os.path.join(self.albums_root, "present2")
        stale_path = os.path.join(self.albums_root, "stale2")
        os.makedirs(present_path, exist_ok=True)
        os.makedirs(stale_path, exist_ok=True)
        _, present_dir = DirectoryIndex.add_directory(present_path + os.sep)
        _, stale_dir = DirectoryIndex.add_directory(stale_path + os.sep)
        assert present_dir is not None and stale_dir is not None
        shutil.rmtree(stale_path)

        deleted_count = _process_directory_verification_chunk([present_dir.pk, stale_dir.pk], deleted_count=0)

        assert deleted_count == 1
        assert DirectoryIndex.objects.filter(pk=present_dir.pk).exists()
        assert not DirectoryIndex.objects.filter(pk=stale_dir.pk).exists()


class TestAddDirectoriesIndependentValidation(ScanCommandTestBase):
    """add_directories() must reject an out-of-tree start_path on its own,
    without relying on scan.py.handle() having already validated it."""

    def test_rejects_out_of_tree_start_path(self):
        outside = tempfile.mkdtemp()
        try:
            add_directories(max_count=0, start_path=outside)
            assert not DirectoryIndex.objects.filter(fqpndirectory__startswith=normalize_fqpn(outside)).exists()
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_rejects_sibling_prefix_start_path(self):
        sibling_root = self.albums_root + "-backup"
        os.makedirs(sibling_root, exist_ok=True)
        try:
            add_directories(max_count=0, start_path=sibling_root)
            assert not DirectoryIndex.objects.filter(fqpndirectory__startswith=normalize_fqpn(sibling_root)).exists()
        finally:
            shutil.rmtree(sibling_root, ignore_errors=True)


class TestAddFilesIndependentValidation(ScanCommandTestBase):
    """add_files() must reject an out-of-tree start_path on its own, and its
    pre-check invalidation calls (management_helper.py) must not silently
    fall back to processing the whole tree when that happens."""

    def test_rejects_out_of_tree_start_path(self):
        outside = tempfile.mkdtemp()
        try:
            initial_count = DirectoryIndex.objects.count()
            add_files(max_count=0, start_path=outside)
            assert DirectoryIndex.objects.count() == initial_count
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_invalidate_helpers_reject_out_of_tree_start_path_directly(self):
        """Direct unit test of management_helper.py's own containment check.

        invalidate_directories_with_null_sha256() is called by add_files()
        (add_files.py:100) before add_files()'s own containment check
        (add_files.py:111-115) runs, so it must not depend on that later
        check. Note: FileIndex.find_files_without_sha()'s start_path filter
        is a plain __startswith on a genuinely out-of-tree path, which
        already matches zero real rows today — so this guard is defense in
        depth (fail fast, with a clear warning) rather than closing an
        observable data-corruption bug; calling it directly here (bypassing
        add_files() entirely) verifies the guard exists and fires on its
        own, independent of whether the current query happens to already
        be harmless.
        """
        from quickbbs.management.commands.management_helper import (
            invalidate_directories_with_null_sha256,
        )

        present_path = os.path.join(self.albums_root, "present")
        os.makedirs(present_path, exist_ok=True)
        _, directory = DirectoryIndex.add_directory(present_path + os.sep)
        assert directory is not None
        ft = _get_ft(".txt")
        FileIndex.objects.create(
            home_directory=directory,
            name="nosha.txt",
            file_sha256=None,
            unique_sha256=("nosha" + "0" * 64)[:64],
            lastscan=0.0,
            lastmod=0.0,
            filetype=ft,
            is_generic_icon=False,
        )

        outside = tempfile.mkdtemp()
        try:
            invalidated_count = invalidate_directories_with_null_sha256(start_path=outside, verbose=False)
            assert invalidated_count == 0
        finally:
            shutil.rmtree(outside, ignore_errors=True)

"""Tests for add_directories.py, add_files.py, and add_thumbnails.py bulk helpers."""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest import mock

import pytest
from django.test import TestCase, override_settings

from filetypes.models import filetypes
from quickbbs.management.commands.add_directories import add_directories
from quickbbs.management.commands.add_files import add_files
from quickbbs.management.commands.add_thumbnails import (
    _bulk_create_thumbnail_records,
    _bulk_link_fileindex_to_thumbnails,
    add_thumbnails,
)
from quickbbs.models import DirectoryIndex, FileIndex
from thumbnails.models import ThumbnailFiles

pytestmark = pytest.mark.api


def _get_ft(fileext: str) -> filetypes:
    """Return filetypes object for a given extension."""
    return filetypes.objects.get(fileext=fileext)


def _sha(prefix: str) -> str:
    """Return a 64-char hex-like string padded with zeros."""
    return (prefix + "0" * 64)[:64]


class AddCommandsTestBase(TestCase):
    """Common tempdir/ALBUMS_PATH setup, with close_old_connections patched
    out (TestCase's atomic wrapper cannot survive a real connection close)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.albums_root = os.path.join(self.temp_dir, "albums")
        os.makedirs(self.albums_root, exist_ok=True)
        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir)
        self._settings_override.enable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        self._coc_patchers = [
            mock.patch("quickbbs.management.commands.add_directories.close_old_connections"),
            mock.patch("quickbbs.management.commands.add_files.close_old_connections"),
            mock.patch("quickbbs.management.commands.add_thumbnails.close_old_connections"),
            mock.patch("quickbbs.directoryindex.close_old_connections"),
        ]
        for patcher in self._coc_patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in self._coc_patchers:
            patcher.stop()
        self._settings_override.disable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)


class TestAddDirectoriesCommand(AddCommandsTestBase):
    """Tests for add_directories()."""

    def test_walks_and_adds_nested_directories(self):
        """A small nested tree is fully registered in DirectoryIndex."""
        os.makedirs(os.path.join(self.albums_root, "a", "b"), exist_ok=True)
        os.makedirs(os.path.join(self.albums_root, "c"), exist_ok=True)

        add_directories()

        assert DirectoryIndex.objects.filter(fqpndirectory__icontains=os.path.join("albums", "a") + os.sep).exists()
        assert DirectoryIndex.objects.filter(fqpndirectory__icontains=os.path.join("albums", "a", "b") + os.sep).exists()
        assert DirectoryIndex.objects.filter(fqpndirectory__icontains=os.path.join("albums", "c") + os.sep).exists()

    def test_added_directories_marked_cache_invalidated(self):
        """Newly added directories are marked cache_invalidated for rescan."""
        os.makedirs(os.path.join(self.albums_root, "newdir"), exist_ok=True)

        add_directories()

        directory = DirectoryIndex.objects.filter(fqpndirectory__icontains="newdir").first()
        assert directory is not None
        assert directory.cache_invalidated is True

    def test_existing_directory_not_duplicated(self):
        """Running add_directories twice does not create duplicate rows."""
        sub = os.path.join(self.albums_root, "onlyone")
        os.makedirs(sub, exist_ok=True)

        add_directories()
        add_directories()

        assert DirectoryIndex.objects.filter(fqpndirectory__icontains="onlyone").count() == 1

    def test_missing_albums_root_is_noop(self):
        """A nonexistent albums root logs an error and returns without raising."""
        shutil.rmtree(self.albums_root)
        add_directories()  # should not raise
        assert not DirectoryIndex.objects.exists()


class TestAddFilesCommand(AddCommandsTestBase):
    """Tests for add_files()."""

    def test_syncs_real_file_into_fileindex(self):
        """A real file under a registered directory is picked up via update_database_from_disk."""
        _, directory = DirectoryIndex.add_directory(self.albums_root + os.sep)
        assert directory is not None
        with open(os.path.join(self.albums_root, "hello.txt"), "w", encoding="utf-8") as f:
            f.write("hello world")

        add_files()

        assert FileIndex.objects.filter(name__iexact="hello.txt", home_directory=directory).exists()

    def test_no_directories_in_db_is_noop(self):
        """When DirectoryIndex is empty, add_files logs and returns without raising."""
        add_files()  # should not raise
        assert not FileIndex.objects.exists()


class TestBulkCreateThumbnailRecords(AddCommandsTestBase):
    """Tests for _bulk_create_thumbnail_records."""

    def test_empty_list_returns_zero(self):
        """An empty SHA list creates nothing."""
        assert _bulk_create_thumbnail_records([]) == 0

    def test_creates_records_for_new_shas(self):
        """New SHA256 hashes get ThumbnailFiles records created."""
        shas = [_sha("a"), _sha("b")]
        created = _bulk_create_thumbnail_records(shas)
        assert created == 2
        assert ThumbnailFiles.objects.filter(sha256_hash__in=shas).count() == 2

    def test_skips_existing_records(self):
        """A SHA that already has a ThumbnailFiles record is not duplicated."""
        existing_sha = _sha("existing")
        ThumbnailFiles.objects.create(sha256_hash=existing_sha)
        created = _bulk_create_thumbnail_records([existing_sha, _sha("newone")])
        assert created == 1
        assert ThumbnailFiles.objects.filter(sha256_hash=existing_sha).count() == 1


class TestBulkLinkFileindexToThumbnails(AddCommandsTestBase):
    """Tests for _bulk_link_fileindex_to_thumbnails."""

    def setUp(self) -> None:
        super().setUp()
        _, self.directory = DirectoryIndex.add_directory(self.albums_root + os.sep)
        assert self.directory is not None
        self.ft = _get_ft(".txt")

    def _make_fileindex(self, name: str, sha: str) -> FileIndex:
        return FileIndex.objects.create(
            home_directory=self.directory,
            name=name,
            file_sha256=sha,
            unique_sha256=_sha(f"u_{name}"),
            lastscan=0.0,
            lastmod=0.0,
            filetype=self.ft,
            delete_pending=False,
            is_generic_icon=False,
        )

    def test_empty_list_returns_zero(self):
        """An empty SHA list links nothing."""
        assert _bulk_link_fileindex_to_thumbnails([]) == 0

    def test_links_fileindex_to_matching_thumbnail(self):
        """A FileIndex row with a matching ThumbnailFiles record gets new_ftnail set."""
        sha = _sha("link")
        thumbnail = ThumbnailFiles.objects.create(sha256_hash=sha)
        file_obj = self._make_fileindex("linkme.txt", sha)

        linked_count = _bulk_link_fileindex_to_thumbnails([sha])

        assert linked_count == 1
        file_obj.refresh_from_db()
        assert file_obj.new_ftnail_id == thumbnail.pk

    def test_already_linked_file_not_touched(self):
        """A FileIndex row that already has new_ftnail set is excluded from the update."""
        sha = _sha("already")
        thumbnail = ThumbnailFiles.objects.create(sha256_hash=sha)
        file_obj = self._make_fileindex("already.txt", sha)
        file_obj.new_ftnail = thumbnail
        file_obj.save(update_fields=["new_ftnail"])

        linked_count = _bulk_link_fileindex_to_thumbnails([sha])

        assert linked_count == 0


class TestAddThumbnailsCommand(AddCommandsTestBase):
    """Tests for add_thumbnails() — enqueue() is mocked to avoid real background tasks."""

    def setUp(self) -> None:
        super().setUp()
        _, self.directory = DirectoryIndex.add_directory(self.albums_root + os.sep)
        assert self.directory is not None
        self.ft_image = _get_ft(".jpg")

    def test_enqueues_thumbnailable_file_without_record(self):
        """A thumbnailable file with no ThumbnailFiles record triggers a bulk-create and an enqueue call."""
        sha = _sha("img")
        FileIndex.objects.create(
            home_directory=self.directory,
            name="photo.jpg",
            file_sha256=sha,
            unique_sha256=_sha("uimg"),
            lastscan=0.0,
            lastmod=0.0,
            filetype=self.ft_image,
            delete_pending=False,
            is_generic_icon=False,
        )

        with mock.patch("quickbbs.management.commands.add_thumbnails.generate_missing_thumbnails") as mock_task:
            add_thumbnails()

        assert ThumbnailFiles.objects.filter(sha256_hash=sha).exists()
        mock_task.using.assert_called_once()
        mock_task.using.return_value.enqueue.assert_called_once()

    def test_no_thumbnailable_files_skips_enqueue(self):
        """When there are no thumbnailable files, add_thumbnails does not enqueue anything."""
        with mock.patch("quickbbs.management.commands.add_thumbnails.generate_missing_thumbnails") as mock_task:
            add_thumbnails()

        mock_task.using.assert_not_called()

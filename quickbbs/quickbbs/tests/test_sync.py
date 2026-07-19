"""
Tests for the filesystem→database sync engine:
DirectoryIndex.sync_subdirectories(), sync_files(), handle_missing(), and the
update_database_from_disk() entry point in quickbbs/directoryindex.py.

RULE 1 — NON-DESTRUCTIVE DATA
-----------------------------
These tests exist to pin the sync engine's deletion behavior: records are
removed ONLY for the specific files/directories that vanished from disk
(hard-deleted by explicit ID list / scoped queryset), and records belonging
to unrelated directories are never touched. Surviving records must keep
their primary keys — a sync must never express "file removed" as a bulk
reset-and-recreate.

DATABASE SAFETY NOTES
---------------------
- All tests use Django's TestCase (each test wrapped in a rolled-back
  transaction against the test database). No TransactionTestCase is used — ever.
- Filesystem content is created in tempfile.mkdtemp() with ALBUMS_PATH
  overridden; tearDown removes only the temp directory.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest import mock

from django.test import TestCase, override_settings

from quickbbs.directoryindex import update_database_from_disk
from quickbbs.fileindex import FileIndex
from quickbbs.models import DirectoryIndex


class SyncTestBase(TestCase):
    """Temp albums tree fixture with helpers to write files and re-sync.

    update_database_from_disk() ends with close_old_connections(); with
    CONN_MAX_AGE=0 that closes the connection outright, which cannot be
    reopened inside TestCase's atomic wrapper — so it is patched to a no-op
    for the duration of each test.
    """

    def setUp(self) -> None:
        self._coc_patcher = mock.patch("quickbbs.directoryindex.close_old_connections")
        self._coc_patcher.start()
        self.temp_dir = tempfile.mkdtemp()
        self.albums_dir = os.path.join(self.temp_dir, "albums")
        os.makedirs(self.albums_dir, exist_ok=True)
        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir)
        self._settings_override.enable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        _, dir_obj = DirectoryIndex.add_directory(self.albums_dir + "/")
        assert dir_obj is not None, "add_directory rejected the albums fixture path"
        self.dir_obj: DirectoryIndex = dir_obj

    def tearDown(self) -> None:
        self._coc_patcher.stop()
        self._settings_override.disable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def write_file(self, name: str, content: bytes = b"data", directory: str | None = None) -> str:
        """Create a file under the albums dir (or *directory*) and return its path."""
        path = os.path.join(directory or self.albums_dir, name)
        with open(path, "wb") as fh:
            fh.write(content)
        return path

    def sync(self, directory: DirectoryIndex | None = None) -> DirectoryIndex | None:
        """Invalidate *directory* (default: the albums root) and run a full sync."""
        target = directory or self.dir_obj
        target.invalidate_cache()
        target.refresh_from_db()
        return update_database_from_disk(target)

    def file_pks(self, directory: DirectoryIndex | None = None) -> dict[str, int]:
        """Return {name: pk} for the directory's non-delete-pending files."""
        target = directory or self.dir_obj
        return dict(FileIndex.objects.filter(home_directory=target, delete_pending=False).values_list("name", "pk"))


class TestInitialSync(SyncTestBase):
    """First sync populates the database from disk."""

    def test_creates_fileindex_records_for_disk_files(self):
        """Every regular file on disk gets exactly one FileIndex record."""
        self.write_file("alpha.txt")
        self.write_file("beta.txt")
        self.sync()
        names = set(self.file_pks())
        assert {n.lower() for n in names} == {"alpha.txt", "beta.txt"}

    def test_creates_directoryindex_records_for_subdirectories(self):
        """Every subdirectory on disk gets a DirectoryIndex record linked to the parent."""
        os.makedirs(os.path.join(self.albums_dir, "sub_one"))
        os.makedirs(os.path.join(self.albums_dir, "sub_two"))
        self.sync()
        children = set(DirectoryIndex.objects.filter(parent_directory=self.dir_obj, delete_pending=False).values_list("fqpndirectory", flat=True))
        assert any("sub_one" in c for c in children)
        assert any("sub_two" in c for c in children)
        assert len(children) == 2

    def test_unchanged_resync_is_a_noop(self):
        """Re-syncing an unchanged tree keeps every PK — no delete-and-recreate."""
        self.write_file("alpha.txt")
        self.sync()
        before = self.file_pks()
        self.sync()
        assert self.file_pks() == before


class TestFileDeletion(SyncTestBase):
    """RULE 1: only the vanished file's record is removed; survivors keep PKs."""

    def test_deleted_file_removed_survivors_keep_pks(self):
        """Removing one file from disk deletes exactly that record."""
        self.write_file("keep_one.txt")
        path_b = self.write_file("remove_me.txt")
        self.write_file("keep_two.txt")
        self.sync()
        before = self.file_pks()
        assert len(before) == 3

        os.remove(path_b)
        self.sync()

        after = self.file_pks()
        removed = {n for n in before if n not in after}
        assert {n.lower() for n in removed} == {"remove_me.txt"}
        for name, pk in after.items():
            assert before[name] == pk, f"survivor {name} was recreated with a new PK"

    def test_sync_never_touches_sibling_directories(self):
        """Emptying one directory must not affect records of a sibling directory."""
        dir_a = os.path.join(self.albums_dir, "dir_a")
        dir_b = os.path.join(self.albums_dir, "dir_b")
        os.makedirs(dir_a)
        os.makedirs(dir_b)
        file_a = self.write_file("a.txt", directory=dir_a)
        self.write_file("b.txt", directory=dir_b)
        self.sync()

        _, rec_a = DirectoryIndex.add_directory(dir_a + "/")
        _, rec_b = DirectoryIndex.add_directory(dir_b + "/")
        self.sync(rec_a)
        self.sync(rec_b)
        b_before = self.file_pks(rec_b)
        assert len(b_before) == 1

        os.remove(file_a)
        self.sync(rec_a)

        assert not self.file_pks(rec_a)
        assert self.file_pks(rec_b) == b_before, "sibling directory records were modified"


class TestSubdirectoryDeletion(SyncTestBase):
    """RULE 1 for directories: only the vanished subdirectory's record goes."""

    def test_deleted_subdirectory_removed_survivor_keeps_pk(self):
        """Removing one subdirectory from disk deletes exactly that record."""
        keep_dir = os.path.join(self.albums_dir, "keep_dir")
        gone_dir = os.path.join(self.albums_dir, "gone_dir")
        os.makedirs(keep_dir)
        os.makedirs(gone_dir)
        self.sync()
        children_before = dict(DirectoryIndex.objects.filter(parent_directory=self.dir_obj, delete_pending=False).values_list("fqpndirectory", "pk"))
        assert len(children_before) == 2

        shutil.rmtree(gone_dir)
        self.sync()

        children_after = dict(DirectoryIndex.objects.filter(parent_directory=self.dir_obj, delete_pending=False).values_list("fqpndirectory", "pk"))
        assert len(children_after) == 1
        survivor_path, survivor_pk = next(iter(children_after.items()))
        assert "keep_dir" in survivor_path
        assert children_before[survivor_path] == survivor_pk


class TestFileAdditionAndUpdate(SyncTestBase):
    """New and modified files are handled in place."""

    def test_new_file_added_without_disturbing_existing_records(self):
        """A file added after the initial sync appears; old records keep PKs."""
        self.write_file("original.txt")
        self.sync()
        before = self.file_pks()

        self.write_file("newcomer.txt")
        self.sync()

        after = self.file_pks()
        assert len(after) == 2
        for name, pk in before.items():
            assert after[name] == pk

    def test_modified_file_updated_in_place(self):
        """Changing a file's content updates the record without replacing it.

        Pins current behavior: lastmod and size are refreshed in place (same
        PK). file_sha256 is NOT recomputed on content change — a known
        oversight in check_for_updates(), which only hashes records that have
        no SHA yet (see the OVERSIGHT comment there). When that is fixed,
        flip the final assertion to expect a changed SHA.
        """
        path = self.write_file("mutable.txt", content=b"first version")
        self.sync()
        before = self.file_pks()
        [(name, pk)] = before.items()
        old_record = FileIndex.objects.get(pk=pk)
        old_lastmod = old_record.lastmod
        old_sha = old_record.file_sha256

        with open(path, "wb") as fh:
            fh.write(b"second version - different bytes entirely")
        # Push mtime forward so the change is detected even with coarse clocks.
        stat = os.stat(path)
        os.utime(path, (stat.st_atime, stat.st_mtime + 10))
        self.sync()

        after = self.file_pks()
        assert after == {name: pk}, "modified file was recreated instead of updated"
        new_record = FileIndex.objects.get(pk=pk)
        assert new_record.lastmod != old_lastmod
        assert new_record.size == os.path.getsize(path)
        assert new_record.file_sha256 == old_sha, "SHA recompute behavior changed — update this test"


class TestHandleMissing(SyncTestBase):
    """A directory that vanished from disk is removed via handle_missing()."""

    def test_vanished_directory_record_is_removed(self):
        """update_database_from_disk on a missing directory deletes its record only."""
        sub = os.path.join(self.albums_dir, "vanishing")
        os.makedirs(sub)
        self.sync()
        _, sub_rec = DirectoryIndex.add_directory(sub + "/")
        sub_pk = sub_rec.pk
        root_pk = self.dir_obj.pk

        shutil.rmtree(sub)
        result = self.sync(sub_rec)

        assert result is None
        assert not DirectoryIndex.objects.filter(pk=sub_pk).exists()
        assert DirectoryIndex.objects.filter(pk=root_pk).exists(), "parent record must survive"

    def test_do_files_exist_reflects_disk_state(self):
        """do_files_exist is True only while the directory has files on record."""
        self.write_file("present.txt")
        self.sync()
        self.dir_obj.refresh_from_db()
        assert self.dir_obj.do_files_exist() is True

        os.remove(os.path.join(self.albums_dir, "present.txt"))
        self.sync()
        self.dir_obj.refresh_from_db()
        assert self.dir_obj.do_files_exist() is False


class TestDeleteDirectoryMethods(SyncTestBase):
    """RULE 1 for the explicit deletion APIs: only the targeted record goes."""

    def _two_subdirs_with_files(self) -> tuple[DirectoryIndex, DirectoryIndex]:
        """Create dir_a/dir_b each holding one file; return their records."""
        dir_a = os.path.join(self.albums_dir, "dir_a")
        dir_b = os.path.join(self.albums_dir, "dir_b")
        os.makedirs(dir_a)
        os.makedirs(dir_b)
        self.write_file("a.txt", directory=dir_a)
        self.write_file("b.txt", directory=dir_b)
        self.sync()
        _, rec_a = DirectoryIndex.add_directory(dir_a + "/")
        _, rec_b = DirectoryIndex.add_directory(dir_b + "/")
        assert rec_a is not None and rec_b is not None
        self.sync(rec_a)
        self.sync(rec_b)
        return rec_a, rec_b

    def test_delete_directory_record_removes_only_target(self):
        """delete_directory_record removes the target; siblings and parent survive."""
        rec_a, rec_b = self._two_subdirs_with_files()
        pk_a, pk_b, pk_root = rec_a.pk, rec_b.pk, self.dir_obj.pk

        DirectoryIndex.delete_directory_record(rec_a)

        assert not DirectoryIndex.objects.filter(pk=pk_a).exists()
        assert DirectoryIndex.objects.filter(pk=pk_b).exists()
        assert DirectoryIndex.objects.filter(pk=pk_root).exists()

    def test_delete_directory_record_orphans_own_files_only(self):
        """Deleting a directory orphans its files; sibling files are untouched.

        Pins current behavior: home_directory uses on_delete=SET_NULL, so the
        directory's FileIndex rows survive with home_directory=None (cleaned
        up later via the OrphanedFileIndex path) — they are NOT cascaded.
        """
        rec_a, rec_b = self._two_subdirs_with_files()
        files_a = list(FileIndex.objects.filter(home_directory=rec_a).values_list("pk", flat=True))
        files_b = list(FileIndex.objects.filter(home_directory=rec_b).values_list("pk", flat=True))
        assert files_a and files_b

        DirectoryIndex.delete_directory_record(rec_a)

        orphaned = FileIndex.objects.filter(pk__in=files_a)
        assert orphaned.count() == len(files_a)
        assert all(f.home_directory_id is None for f in orphaned)
        assert FileIndex.objects.filter(pk__in=files_b, home_directory=rec_b).count() == len(files_b)

    def test_delete_directory_by_path_removes_only_target(self):
        """delete_directory (by path) removes the matching record only."""
        rec_a, rec_b = self._two_subdirs_with_files()
        pk_a, pk_b = rec_a.pk, rec_b.pk

        DirectoryIndex.delete_directory(rec_a.fqpndirectory)

        assert not DirectoryIndex.objects.filter(pk=pk_a).exists()
        assert DirectoryIndex.objects.filter(pk=pk_b).exists()

    def test_delete_directory_cache_only_keeps_record(self):
        """cache_only=True clears caches but must not delete the record."""
        rec_a, _ = self._two_subdirs_with_files()

        DirectoryIndex.delete_directory(rec_a.fqpndirectory, cache_only=True)

        assert DirectoryIndex.objects.filter(pk=rec_a.pk).exists()

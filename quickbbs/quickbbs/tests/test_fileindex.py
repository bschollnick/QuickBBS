"""
Tests for FileIndex model methods.

DATABASE SAFETY NOTES
---------------------
- All tests use Django's TestCase, which wraps every test in a transaction
  that is rolled back after each test method. Nothing is committed to any
  persistent database.
- Verification suite files at Albums/verification_suite/ are read-only.
  Tests never write to, move, or delete gallery content.
- FileIndex records are created directly via ORM in tempfile directories or
  by calling from_filesystem() against real verification_suite files.
- No TransactionTestCase is used — ever.

VERIFICATION SUITE
------------------
Real files used (read-only):
  Albums/verification_suite/LICENCE.TXT           — plain text
  Albums/verification_suite/LICENCE copy.TXT      — duplicate content (same SHA)
  Albums/verification_suite/SOURCES.txt           — plain text
  Albums/verification_suite/markdown-test2.markdown — markdown
  Albums/verification_suite/TALE007.HTM           — HTML
  Albums/verification_suite/Bliss.bmp             — image
  Albums/verification_suite/9items.zip            — archive (unknown to filetype checks)
  Albums/verification_suite/Rojas-Galeano S... .pdf — PDF
  Albums/verification_suite/-Photo 6.jpg          — filename starts with dash
  Albums/verification_suite/benchtests/test1.txt  — file in subdirectory
"""

from __future__ import annotations

import os
import tempfile
import shutil
from pathlib import Path

import pytest
from django.conf import settings
from django.test import TestCase

from filetypes.models import filetypes
from quickbbs.common import get_file_sha, normalize_fqpn
from quickbbs.fileindex import (
    FileIndex,
    FILEINDEX_SR_FILETYPE,
    FILEINDEX_SR_FILETYPE_HOME,
    sanitize_filename_for_http,
)
from quickbbs.models import DirectoryIndex


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

VERIFICATION_SUITE = normalize_fqpn(
    os.path.join(settings.ALBUMS_PATH, "albums", "verification_suite")
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_ft(fileext: str) -> filetypes:
    """Return filetypes object for a given extension."""
    return filetypes.objects.get(fileext=fileext)


def _make_dir(path: str) -> DirectoryIndex:
    """Create a real filesystem directory and register it in DirectoryIndex."""
    os.makedirs(path, exist_ok=True)
    _, di = DirectoryIndex.add_directory(path + "/")
    return di


def _sha(prefix: str) -> str:
    """Return a 64-char hex-like string padded with zeros."""
    return (prefix + "0" * 64)[:64]


def _make_fileindex(directory: DirectoryIndex, name: str, file_sha: str, unique_sha: str, ft: filetypes, **kwargs) -> FileIndex:
    """Create a minimal FileIndex record without touching the filesystem."""
    return FileIndex.objects.create(
        home_directory=directory,
        name=name,
        file_sha256=file_sha,
        unique_sha256=unique_sha,
        lastscan=0.0,
        lastmod=0.0,
        filetype=ft,
        delete_pending=False,
        is_generic_icon=False,
        **kwargs,
    )


# ===========================================================================
# sanitize_filename_for_http — pure function, no DB needed
# ===========================================================================

class TestSanitizeFilenameForHttp(TestCase):
    """Unit tests for sanitize_filename_for_http."""

    def test_plain_filename_unchanged(self):
        """Normal filenames pass through unchanged."""
        assert sanitize_filename_for_http("photo.jpg") == "photo.jpg"

    def test_semicolon_replaced_with_underscore(self):
        """Semicolons become underscores (header parameter separator)."""
        assert sanitize_filename_for_http("file;evil.exe") == "file_evil.exe"

    def test_angle_brackets_removed(self):
        """Angle brackets are removed entirely."""
        assert sanitize_filename_for_http("<script>.txt") == "script.txt"
        assert sanitize_filename_for_http("a>b.txt") == "ab.txt"

    def test_control_chars_removed(self):
        """Control characters (0x00-0x1F) are stripped."""
        assert sanitize_filename_for_http("file\x00name.txt") == "filename.txt"
        assert sanitize_filename_for_http("file\nname.txt") == "filename.txt"
        assert sanitize_filename_for_http("file\x1fname.txt") == "filename.txt"

    def test_del_char_removed(self):
        """DEL (0x7F) is stripped."""
        assert sanitize_filename_for_http("file\x7fname.txt") == "filename.txt"

    def test_empty_string_returns_fallback(self):
        """Empty string (after sanitization) returns 'download.bin'."""
        assert sanitize_filename_for_http("") == "download.bin"
        # String that becomes empty after stripping control chars
        assert sanitize_filename_for_http("\x00\x01\x02") == "download.bin"

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped."""
        assert sanitize_filename_for_http("  photo.jpg  ") == "photo.jpg"

    def test_unicode_filename_preserved(self):
        """Unicode characters not in the removal set pass through."""
        assert sanitize_filename_for_http("日本語.txt") == "日本語.txt"

    def test_filename_starting_with_dash(self):
        """Filenames starting with dash (like verification_suite files) pass through."""
        assert sanitize_filename_for_http("-Photo 6.jpg") == "-Photo 6.jpg"

    def test_multiple_semicolons(self):
        """Multiple semicolons are all replaced."""
        assert sanitize_filename_for_http("a;b;c.txt") == "a_b_c.txt"


# ===========================================================================
# FileIndex.from_filesystem — reads real verification_suite files
# ===========================================================================

@pytest.mark.django_db
class TestFromFilesystem(TestCase):
    """
    Tests for FileIndex.from_filesystem() using real verification_suite files.

    RED tests: call from_filesystem() and assert the returned dict has the
    correct shape and values.  These tests define the contract.
    """

    def setUp(self):
        """Create a DirectoryIndex for the verification suite."""
        self.temp_dir = tempfile.mkdtemp()
        _, self.dir_obj = DirectoryIndex.add_directory(self.temp_dir + "/")
        self.ft_none = _get_ft(".none")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _vs_path(self, filename: str) -> Path:
        return Path(VERIFICATION_SUITE) / filename

    def test_returns_none_for_directory(self):
        """Directories return None — handled by DirectoryIndex, not FileIndex."""
        path = Path(VERIFICATION_SUITE)
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result is None

    def test_text_file_returns_dict(self):
        """Plain text file returns a metadata dict."""
        path = self._vs_path("LICENCE.TXT")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result is not None
        assert isinstance(result, dict)

    def test_text_file_name_field(self):
        """Name field is the filename normalized via normalize_string_title (title case)."""
        path = self._vs_path("LICENCE.TXT")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        # normalize_string_title applies .title().strip()
        assert result["name"] == "Licence.Txt"

    def test_text_file_size_positive(self):
        """File size is populated and positive."""
        path = self._vs_path("LICENCE.TXT")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result["size"] > 0

    def test_text_file_sha256_computed(self):
        """SHA256 hashes are computed and non-empty."""
        path = self._vs_path("LICENCE.TXT")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result["file_sha256"] is not None
        assert len(result["file_sha256"]) == 64
        assert result["unique_sha256"] is not None
        assert len(result["unique_sha256"]) == 64

    def test_file_sha_differs_from_unique_sha(self):
        """file_sha256 and unique_sha256 are different (path is included in unique)."""
        path = self._vs_path("LICENCE.TXT")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result["file_sha256"] != result["unique_sha256"]

    def test_duplicate_files_same_file_sha(self):
        """Two files with the same content have the same file_sha256."""
        path1 = self._vs_path("LICENCE.TXT")
        path2 = self._vs_path("LICENCE copy.TXT")
        result1 = FileIndex.from_filesystem(path1, directory_id=self.dir_obj)
        result2 = FileIndex.from_filesystem(path2, directory_id=self.dir_obj)
        assert result1 is not None
        assert result2 is not None
        assert result1["file_sha256"] == result2["file_sha256"]

    def test_duplicate_files_different_unique_sha(self):
        """Two files with the same content have different unique_sha256 (paths differ)."""
        path1 = self._vs_path("LICENCE.TXT")
        path2 = self._vs_path("LICENCE copy.TXT")
        result1 = FileIndex.from_filesystem(path1, directory_id=self.dir_obj)
        result2 = FileIndex.from_filesystem(path2, directory_id=self.dir_obj)
        assert result1["unique_sha256"] != result2["unique_sha256"]

    def test_precomputed_sha_used(self):
        """Precomputed SHA is used instead of recomputing."""
        path = self._vs_path("LICENCE.TXT")
        fake_sha = ("a" * 64, "b" * 64)
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj, precomputed_sha=fake_sha)
        assert result is not None
        assert result["file_sha256"] == "a" * 64
        assert result["unique_sha256"] == "b" * 64

    def test_home_directory_set(self):
        """home_directory is set to the provided directory_id."""
        path = self._vs_path("LICENCE.TXT")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result["home_directory"] == self.dir_obj

    def test_filetype_populated(self):
        """filetype is populated from the filetypes table."""
        path = self._vs_path("LICENCE.TXT")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result["filetype"] is not None
        assert isinstance(result["filetype"], filetypes)

    def test_txt_extension_filetype(self):
        """A .TXT file gets the .txt filetype (case-insensitive)."""
        path = self._vs_path("LICENCE.TXT")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result["filetype"].fileext == ".txt"

    def test_markdown_file(self):
        """Markdown file is processed and gets the .markdown filetype."""
        path = self._vs_path("markdown-test2.markdown")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result is not None
        assert result["filetype"].fileext == ".markdown"

    def test_html_file(self):
        """HTML file (.HTM extension) is processed correctly."""
        path = self._vs_path("TALE007.HTM")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result is not None
        assert result["filetype"].fileext == ".htm"

    def test_pdf_file(self):
        """PDF file is processed and gets the .pdf filetype."""
        path = self._vs_path("Rojas-Galeano S. ChatGPT. Your Python Coach, Mastering...in 100 Prompts 2023.pdf")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result is not None
        assert result["filetype"].fileext == ".pdf"

    def test_image_file(self):
        """BMP image file is processed correctly."""
        path = self._vs_path("Bliss.bmp")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result is not None
        assert result["filetype"].fileext == ".bmp"

    def test_filename_starting_with_dash(self):
        """Filenames starting with a dash are processed correctly."""
        path = self._vs_path("-Photo 6.jpg")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result is not None
        # normalize_string_title applies .title() — "-Photo 6.jpg" → "-Photo 6.Jpg"
        assert result["name"] == "-Photo 6.Jpg"

    def test_is_animated_false_for_non_gif(self):
        """Non-GIF files have is_animated=False."""
        path = self._vs_path("LICENCE.TXT")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result["is_animated"] is False

    def test_lastmod_populated(self):
        """lastmod is set from filesystem mtime."""
        path = self._vs_path("LICENCE.TXT")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result["lastmod"] > 0

    def test_lastscan_populated(self):
        """lastscan is set to a recent timestamp."""
        import time
        before = time.time() - 1
        path = self._vs_path("LICENCE.TXT")
        result = FileIndex.from_filesystem(path, directory_id=self.dir_obj)
        assert result["lastscan"] >= before

    def test_unknown_extension_returns_none(self):
        """File with extension not in filetypes table returns None."""
        # Create a temp file with an extension that doesn't exist in filetypes
        temp_file = Path(self.temp_dir) / "test.xyzzy_unknown_ext_12345"
        temp_file.write_bytes(b"test")
        result = FileIndex.from_filesystem(temp_file, directory_id=self.dir_obj)
        assert result is None


# ===========================================================================
# FileIndex.return_identical_files_count
# ===========================================================================

@pytest.mark.django_db
class TestReturnIdenticalFilesCount(TestCase):
    """Tests for FileIndex.return_identical_files_count."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        _, self.dir_obj = DirectoryIndex.add_directory(self.temp_dir + "/")
        self.ft = _get_ft(".txt")
        self.sha = "a" * 64

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_returns_zero_for_unknown_sha(self):
        """Returns 0 when no files have the given SHA."""
        assert FileIndex.return_identical_files_count("z" * 64) == 0

    def test_returns_one_for_single_file(self):
        """Returns 1 when exactly one file has the given SHA."""
        _make_fileindex(self.dir_obj, "a.txt", self.sha, "u" * 64, self.ft)
        assert FileIndex.return_identical_files_count(self.sha) == 1

    def test_returns_count_for_duplicates(self):
        """Returns 3 when three files share the same SHA."""
        for i in range(3):
            _make_fileindex(self.dir_obj, f"file{i}.txt", self.sha, _sha(f"u{i}"), self.ft)
        assert FileIndex.return_identical_files_count(self.sha) == 3

    def test_counts_only_matching_sha(self):
        """Does not count files with a different SHA."""
        _make_fileindex(self.dir_obj, "a.txt", self.sha, "u1" + "x" * 62, self.ft)
        _make_fileindex(self.dir_obj, "b.txt", "b" * 64, "u2" + "x" * 62, self.ft)
        assert FileIndex.return_identical_files_count(self.sha) == 1


# ===========================================================================
# FileIndex.return_list_all_identical_files_by_sha
# ===========================================================================

@pytest.mark.django_db
class TestReturnListAllIdenticalFilesBySha(TestCase):
    """Tests for FileIndex.return_list_all_identical_files_by_sha."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        _, self.dir_obj = DirectoryIndex.add_directory(self.temp_dir + "/")
        self.ft = _get_ft(".txt")
        self.sha = "d" * 64

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_empty_for_no_duplicates(self):
        """Returns empty queryset when fewer than 2 files share SHA."""
        _make_fileindex(self.dir_obj, "a.txt", self.sha, "u1" + "x" * 62, self.ft)
        result = FileIndex.return_list_all_identical_files_by_sha(self.sha)
        assert result.count() == 0

    def test_returns_entry_for_two_duplicates(self):
        """Returns one summary row when 2 files share SHA."""
        for i in range(2):
            _make_fileindex(self.dir_obj, f"f{i}.txt", self.sha, _sha(f"u{i}"), self.ft)
        result = FileIndex.return_list_all_identical_files_by_sha(self.sha)
        assert result.count() == 1
        row = result.first()
        assert row["file_sha256"] == self.sha
        assert row["dupe_count"] == 2

    def test_dupe_count_correct_for_three(self):
        """dupe_count is 3 when 3 files share SHA."""
        for i in range(3):
            _make_fileindex(self.dir_obj, f"f{i}.txt", self.sha, _sha(f"u{i}"), self.ft)
        result = FileIndex.return_list_all_identical_files_by_sha(self.sha)
        assert result.first()["dupe_count"] == 3


# ===========================================================================
# FileIndex.get_identical_file_entries_by_sha
# ===========================================================================

@pytest.mark.django_db
class TestGetIdenticalFileEntriesBySha(TestCase):
    """Tests for FileIndex.get_identical_file_entries_by_sha."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        _, self.dir_obj = DirectoryIndex.add_directory(self.temp_dir + "/")
        self.ft = _get_ft(".txt")
        self.sha = "e" * 64

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_returns_name_and_directory(self):
        """Each row contains name and home_directory__fqpndirectory."""
        _make_fileindex(self.dir_obj, "alpha.txt", self.sha, "u1" + "x" * 62, self.ft)
        result = list(FileIndex.get_identical_file_entries_by_sha(self.sha))
        assert len(result) == 1
        assert "name" in result[0]
        assert "home_directory__fqpndirectory" in result[0]

    def test_name_matches(self):
        """Returned name matches the created record."""
        _make_fileindex(self.dir_obj, "beta.txt", self.sha, "u2" + "x" * 62, self.ft)
        result = list(FileIndex.get_identical_file_entries_by_sha(self.sha))
        names = [r["name"] for r in result]
        assert "beta.txt" in names

    def test_empty_for_unknown_sha(self):
        """Returns empty queryset for SHA with no matches."""
        result = FileIndex.get_identical_file_entries_by_sha("z" * 64)
        assert result.count() == 0


# ===========================================================================
# FileIndex.find_files_without_sha
# ===========================================================================

@pytest.mark.django_db
class TestFindFilesWithoutSha(TestCase):
    """Tests for FileIndex.find_files_without_sha."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        _, self.dir_obj = DirectoryIndex.add_directory(self.temp_dir + "/")
        self.ft = _get_ft(".txt")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_finds_file_with_null_sha(self):
        """Files with null file_sha256 are returned."""
        record = FileIndex.objects.create(
            home_directory=self.dir_obj,
            name="no_sha.txt",
            file_sha256=None,
            unique_sha256=None,
            lastscan=0.0,
            lastmod=0.0,
            filetype=self.ft,
            delete_pending=False,
            is_generic_icon=False,
        )
        result = FileIndex.find_files_without_sha()
        pks = list(result.values_list("pk", flat=True))
        assert record.pk in pks

    def test_excludes_file_with_sha(self):
        """Files with a SHA are not returned."""
        _make_fileindex(self.dir_obj, "has_sha.txt", "f" * 64, "g" * 64, self.ft)
        result = FileIndex.find_files_without_sha()
        pks = list(result.values_list("pk", flat=True))
        # Should not contain any file that has a sha
        shas = list(FileIndex.objects.filter(pk__in=pks).values_list("file_sha256", flat=True))
        assert all(s is None for s in shas)

    def test_excludes_delete_pending(self):
        """Files marked delete_pending are excluded."""
        FileIndex.objects.create(
            home_directory=self.dir_obj,
            name="pending.txt",
            file_sha256=None,
            unique_sha256=None,
            lastscan=0.0,
            lastmod=0.0,
            filetype=self.ft,
            delete_pending=True,
            is_generic_icon=False,
        )
        result = FileIndex.find_files_without_sha()
        names = list(result.values_list("name", flat=True))
        assert "pending.txt" not in names

    def test_start_path_filter(self):
        """start_path filters to files in a specific directory subtree."""
        other_temp = tempfile.mkdtemp()
        try:
            _, other_dir = DirectoryIndex.add_directory(other_temp + "/")
            FileIndex.objects.create(
                home_directory=other_dir,
                name="other.txt",
                file_sha256=None,
                unique_sha256=None,
                lastscan=0.0,
                lastmod=0.0,
                filetype=self.ft,
                delete_pending=False,
                is_generic_icon=False,
            )
            # Filter to self.temp_dir — should not include other_dir's file
            result = FileIndex.find_files_without_sha(start_path=self.temp_dir)
            dirs = list(result.values_list("home_directory__fqpndirectory", flat=True))
            for d in dirs:
                assert d.startswith(self.temp_dir)
        finally:
            shutil.rmtree(other_temp, ignore_errors=True)


# ===========================================================================
# FileIndex.set_generic_icon_for_sha
# ===========================================================================

@pytest.mark.django_db
class TestSetGenericIconForSha(TestCase):
    """Tests for FileIndex.set_generic_icon_for_sha."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        _, self.dir_obj = DirectoryIndex.add_directory(self.temp_dir + "/")
        self.ft = _get_ft(".txt")
        self.sha = "c" * 64

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sets_is_generic_icon_true(self):
        """Sets is_generic_icon=True for all files with matching SHA."""
        rec = _make_fileindex(self.dir_obj, "a.txt", self.sha, "u1" + "x" * 62, self.ft)
        assert rec.is_generic_icon is False
        FileIndex.set_generic_icon_for_sha(self.sha, is_generic=True, clear_cache=False)
        rec.refresh_from_db()
        assert rec.is_generic_icon is True

    def test_sets_is_generic_icon_false(self):
        """Sets is_generic_icon=False for files previously marked generic."""
        rec = _make_fileindex(self.dir_obj, "b.txt", self.sha, "u2" + "x" * 62, self.ft)
        FileIndex.objects.filter(pk=rec.pk).update(is_generic_icon=True)
        FileIndex.set_generic_icon_for_sha(self.sha, is_generic=False, clear_cache=False)
        rec.refresh_from_db()
        assert rec.is_generic_icon is False

    def test_updates_all_files_with_sha(self):
        """Updates all records sharing the SHA, not just one."""
        recs = [
            _make_fileindex(self.dir_obj, f"f{i}.txt", self.sha, _sha(f"u{i}"), self.ft)
            for i in range(3)
        ]
        count = FileIndex.set_generic_icon_for_sha(self.sha, is_generic=True, clear_cache=False)
        assert count == 3
        for rec in recs:
            rec.refresh_from_db()
            assert rec.is_generic_icon is True

    def test_returns_updated_count(self):
        """Returns the number of records updated."""
        for i in range(2):
            _make_fileindex(self.dir_obj, f"g{i}.txt", self.sha, _sha(f"v{i}"), self.ft)
        count = FileIndex.set_generic_icon_for_sha(self.sha, is_generic=True, clear_cache=False)
        assert count == 2

    def test_no_match_returns_zero(self):
        """Returns 0 when no files match the SHA."""
        count = FileIndex.set_generic_icon_for_sha("z" * 64, is_generic=True, clear_cache=False)
        assert count == 0


# ===========================================================================
# FileIndex.link_to_thumbnail
# ===========================================================================

@pytest.mark.django_db
class TestLinkToThumbnail(TestCase):
    """Tests for FileIndex.link_to_thumbnail."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        _, self.dir_obj = DirectoryIndex.add_directory(self.temp_dir + "/")
        self.ft = _get_ft(".jpg")
        self.sha = "t" * 64
        # Create a minimal ThumbnailFiles record
        from thumbnails.models import ThumbnailFiles
        self.thumbnail = ThumbnailFiles.objects.create(
            sha256_hash=self.sha,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_links_unlinked_record(self):
        """Links a FileIndex record that has no thumbnail."""
        rec = _make_fileindex(self.dir_obj, "photo.jpg", self.sha, "u1" + "x" * 62, self.ft)
        has_unlinked, count = FileIndex.link_to_thumbnail(self.sha, self.thumbnail)
        assert has_unlinked is True
        assert count == 1
        rec.refresh_from_db()
        assert rec.new_ftnail_id == self.thumbnail.pk

    def test_already_linked_not_updated(self):
        """Records already linked to a thumbnail are not re-linked."""
        rec = _make_fileindex(self.dir_obj, "photo.jpg", self.sha, "u1" + "x" * 62, self.ft)
        # Pre-link it
        FileIndex.objects.filter(pk=rec.pk).update(new_ftnail=self.thumbnail)
        has_unlinked, count = FileIndex.link_to_thumbnail(self.sha, self.thumbnail)
        assert has_unlinked is False
        assert count == 0

    def test_links_multiple_records(self):
        """All unlinked records sharing the SHA are linked."""
        recs = [
            _make_fileindex(self.dir_obj, f"p{i}.jpg", self.sha, _sha(f"u{i}"), self.ft)
            for i in range(3)
        ]
        has_unlinked, count = FileIndex.link_to_thumbnail(self.sha, self.thumbnail)
        assert has_unlinked is True
        assert count == 3
        for rec in recs:
            rec.refresh_from_db()
            assert rec.new_ftnail_id == self.thumbnail.pk


# ===========================================================================
# FileIndex.get_by_sha256
# ===========================================================================

@pytest.mark.django_db
class TestGetBySha256(TestCase):
    """Tests for FileIndex.get_by_sha256."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        _, self.dir_obj = DirectoryIndex.add_directory(self.temp_dir + "/")
        self.ft = _get_ft(".txt")
        self.file_sha = "f" * 64
        self.unique_sha = "g" * 64
        self.rec = _make_fileindex(self.dir_obj, "test.txt", self.file_sha, self.unique_sha, self.ft)
        # Clear fileindex cache between tests
        from quickbbs.fileindex import fileindex_cache
        fileindex_cache.clear()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        from quickbbs.fileindex import fileindex_cache
        fileindex_cache.clear()

    def test_get_by_unique_sha(self):
        """Retrieves record by unique_sha256."""
        result = FileIndex.get_by_sha256(self.unique_sha, unique=True, select_related=FILEINDEX_SR_FILETYPE)
        assert result is not None
        assert result.pk == self.rec.pk

    def test_get_by_file_sha(self):
        """Retrieves record by file_sha256."""
        result = FileIndex.get_by_sha256(self.file_sha, unique=False, select_related=FILEINDEX_SR_FILETYPE)
        assert result is not None
        assert result.pk == self.rec.pk

    def test_returns_none_for_unknown_sha(self):
        """Returns None when SHA is not in the database."""
        result = FileIndex.get_by_sha256("z" * 64, unique=True, select_related=FILEINDEX_SR_FILETYPE)
        assert result is None

    def test_excludes_delete_pending(self):
        """delete_pending records are not returned."""
        FileIndex.objects.filter(pk=self.rec.pk).update(delete_pending=True)
        result = FileIndex.get_by_sha256(self.unique_sha, unique=True, select_related=FILEINDEX_SR_FILETYPE)
        assert result is None


# ===========================================================================
# FileIndex.is_animated_gif — pure file I/O, uses verification_suite
# ===========================================================================

class TestIsAnimatedGif(TestCase):
    """Tests for FileIndex.is_animated_gif."""

    def _vs_path(self, filename: str) -> Path:
        return Path(VERIFICATION_SUITE) / filename

    def test_non_gif_returns_false(self):
        """Non-GIF image returns False."""
        path = self._vs_path("Bliss.bmp")
        assert FileIndex.is_animated_gif(path) is False

    def test_nonexistent_file_returns_false(self):
        """Missing file returns False (not an exception)."""
        path = Path(tempfile.gettempdir()) / "nonexistent_quickbbs_test_12345.gif"
        assert FileIndex.is_animated_gif(path) is False


# ===========================================================================
# FileIndex properties — fqpndirectory and full_filepathname
# ===========================================================================

@pytest.mark.django_db
class TestFileIndexProperties(TestCase):
    """Tests for FileIndex.fqpndirectory and full_filepathname properties."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        _, self.dir_obj = DirectoryIndex.add_directory(self.temp_dir + "/")
        self.ft = _get_ft(".txt")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_fqpndirectory_matches_directory(self):
        """fqpndirectory returns the parent directory's fqpndirectory."""
        rec = _make_fileindex(self.dir_obj, "test.txt", "a" * 64, "b" * 64, self.ft)
        # Fetch with select_related so home_directory is loaded
        rec = FileIndex.objects.select_related("home_directory").get(pk=rec.pk)
        assert rec.fqpndirectory == self.dir_obj.fqpndirectory

    def test_full_filepathname_combines_dir_and_name(self):
        """full_filepathname is directory path + filename."""
        rec = _make_fileindex(self.dir_obj, "myfile.txt", "a" * 64, "b" * 64, self.ft)
        rec = FileIndex.objects.select_related("home_directory").get(pk=rec.pk)
        assert rec.full_filepathname == self.dir_obj.fqpndirectory + "myfile.txt"

    def test_fqpndirectory_raises_for_orphan(self):
        """fqpndirectory raises ValueError when home_directory is None."""
        rec = _make_fileindex(self.dir_obj, "orphan.txt", "a" * 64, "b" * 64, self.ft)
        rec.home_directory = None  # Simulate orphan without saving
        with self.assertRaises(ValueError):
            _ = rec.fqpndirectory

    def test_get_file_counts_returns_none(self):
        """get_file_counts returns None (Null Object pattern for templates)."""
        rec = _make_fileindex(self.dir_obj, "test.txt", "a" * 64, "b" * 64, self.ft)
        assert rec.get_file_counts() is None

    def test_get_dir_counts_returns_none(self):
        """get_dir_counts returns None (Null Object pattern for templates)."""
        rec = _make_fileindex(self.dir_obj, "test.txt", "a" * 64, "b" * 64, self.ft)
        assert rec.get_dir_counts() is None

"""
Tests for the two ORM query improvements planned in orm_query_improvements.md:

  1. get_all_parent_shas  — path-prefix approach (2 queries flat vs O(depth))
  2. files_in_dir(distinct=True) — Subquery approach vs PK-list materialisation

DATABASE SAFETY NOTES
---------------------
- pytest.ini sets --reuse-db, so pytest-django uses a *test* database
  (test_<DATABASE_NAME>), never the production database.
- All tests use Django's TestCase, which wraps every test in a transaction
  that is rolled back after each test method.  Nothing is committed to any
  persistent database.
- Filesystem directories are created in tempfile.mkdtemp() and deleted in
  tearDown — no gallery content is touched.
- add_directory() is used for record creation.  Because temp dirs are outside
  settings.ALBUMS_PATH the method does NOT wire parent_directory FK links
  automatically.  Where tests need a real parent chain (all parent SHA tests),
  the FK is set explicitly via .update() after creation.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest
from django.db import connection
from django.db.models.query import QuerySet
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from filetypes.models import filetypes
from quickbbs.directoryindex import DIRECTORYINDEX_SR_PARENT
from quickbbs.fileindex import FILEINDEX_SR_FILETYPE
from quickbbs.models import DirectoryIndex, FileIndex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fs_dirs(*paths: str) -> None:
    """Create filesystem directories so add_directory() succeeds."""
    for path in paths:
        os.makedirs(path, exist_ok=True)


def _wire_parent(child: DirectoryIndex, parent: DirectoryIndex) -> None:
    """
    Explicitly set parent_directory FK on a DirectoryIndex record.

    add_directory() only wires parent links when the path is inside
    settings.ALBUMS_PATH.  For test dirs in tempfile.mkdtemp() we set the
    link manually so get_all_parent_shas has a real FK chain to traverse.
    """
    DirectoryIndex.objects.filter(pk=child.pk).update(parent_directory=parent)
    child.parent_directory = parent  # keep in-memory object consistent


def _create_fileindex(directory: DirectoryIndex, name: str, file_sha: str, unique_sha: str, ft: filetypes) -> FileIndex:
    """
    Create a minimal FileIndex record in *directory* with the given SHA values.

    Accepts the filetype object as a parameter so callers can cache the lookup
    and avoid a repeated DB hit per file.  Does NOT touch the filesystem.
    """
    record = FileIndex.objects.create(
        home_directory=directory,
        name=name,
        file_sha256=file_sha,
        unique_sha256=unique_sha,
        lastscan=0.0,
        lastmod=0.0,
        filetype=ft,
        delete_pending=False,
        is_generic_icon=False,
    )
    return record


# ===========================================================================
# 1. get_all_parent_shas tests
# ===========================================================================

@pytest.mark.django_db
class TestGetAllParentShasCurrentImpl(TestCase):
    """
    Behaviour tests for get_all_parent_shas using the *current* implementation.

    These tests establish a correct-behaviour baseline.  After the path-prefix
    refactor they must still pass unchanged — that is the contract.

    The directory hierarchy created here:

        root/
        root/photos/
        root/photos/2024/
        root/photos/2024/january/
        root/videos/
        root/videos/2024/

    Parent FK links are wired manually (see _wire_parent) because the temp
    dirs are outside ALBUMS_PATH and add_directory() won't auto-link them.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        ap = self.temp_dir  # albums_path shorthand

        # Create filesystem dirs first (add_directory checks they exist)
        _make_fs_dirs(
            ap,
            os.path.join(ap, "photos"),
            os.path.join(ap, "photos", "2024"),
            os.path.join(ap, "photos", "2024", "january"),
            os.path.join(ap, "videos"),
            os.path.join(ap, "videos", "2024"),
        )

        # Create DB records
        _, self.root = DirectoryIndex.add_directory(ap + "/")
        _, self.photos = DirectoryIndex.add_directory(os.path.join(ap, "photos") + "/")
        _, self.photos_2024 = DirectoryIndex.add_directory(os.path.join(ap, "photos", "2024") + "/")
        _, self.photos_jan = DirectoryIndex.add_directory(os.path.join(ap, "photos", "2024", "january") + "/")
        _, self.videos = DirectoryIndex.add_directory(os.path.join(ap, "videos") + "/")
        _, self.videos_2024 = DirectoryIndex.add_directory(os.path.join(ap, "videos", "2024") + "/")

        # Wire parent FK chain explicitly
        _wire_parent(self.photos, self.root)
        _wire_parent(self.photos_2024, self.photos)
        _wire_parent(self.photos_jan, self.photos_2024)
        _wire_parent(self.videos, self.root)
        _wire_parent(self.videos_2024, self.videos)

    def tearDown(self):
        if hasattr(self, "temp_dir") and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    # --- correctness tests ---

    def test_empty_input_returns_empty_set(self):
        result = DirectoryIndex.get_all_parent_shas([], DIRECTORYINDEX_SR_PARENT)
        self.assertEqual(result, set())

    def test_root_returns_only_itself(self):
        """Root has no parent; result must be exactly {root_sha}."""
        result = DirectoryIndex.get_all_parent_shas(
            [self.root.dir_fqpn_sha256], DIRECTORYINDEX_SR_PARENT
        )
        self.assertEqual(result, {self.root.dir_fqpn_sha256})

    def test_single_leaf_includes_full_chain(self):
        """
        photos/2024/january → should include itself + 2024 + photos + root.
        """
        result = DirectoryIndex.get_all_parent_shas(
            [self.photos_jan.dir_fqpn_sha256], DIRECTORYINDEX_SR_PARENT
        )
        expected = {
            self.root.dir_fqpn_sha256,
            self.photos.dir_fqpn_sha256,
            self.photos_2024.dir_fqpn_sha256,
            self.photos_jan.dir_fqpn_sha256,
        }
        self.assertEqual(result, expected)

    def test_two_branches_share_root(self):
        """
        photos/2024/january + videos/2024 → all ancestors, root deduplicated.
        """
        result = DirectoryIndex.get_all_parent_shas(
            [self.photos_jan.dir_fqpn_sha256, self.videos_2024.dir_fqpn_sha256],
            DIRECTORYINDEX_SR_PARENT,
        )
        expected = {
            self.root.dir_fqpn_sha256,
            self.photos.dir_fqpn_sha256,
            self.photos_2024.dir_fqpn_sha256,
            self.photos_jan.dir_fqpn_sha256,
            self.videos.dir_fqpn_sha256,
            self.videos_2024.dir_fqpn_sha256,
        }
        self.assertEqual(result, expected)

    def test_result_is_a_set(self):
        """Return type must be set (no duplicates)."""
        result = DirectoryIndex.get_all_parent_shas(
            [self.photos_jan.dir_fqpn_sha256, self.photos_2024.dir_fqpn_sha256],
            DIRECTORYINDEX_SR_PARENT,
        )
        self.assertIsInstance(result, set)

    def test_duplicate_inputs_deduplicated(self):
        """Passing the same SHA twice must produce the same result as passing it once."""
        sha = self.photos_jan.dir_fqpn_sha256
        result_once = DirectoryIndex.get_all_parent_shas([sha], DIRECTORYINDEX_SR_PARENT)
        result_twice = DirectoryIndex.get_all_parent_shas([sha, sha], DIRECTORYINDEX_SR_PARENT)
        # Duplicate inputs must not inflate the output set
        self.assertEqual(result_once, result_twice)
        # Expected: root + photos + 2024 + january = 4 entries
        self.assertEqual(len(result_twice), 4)

    def test_input_shas_always_in_result(self):
        """Every input SHA must appear in the output regardless of parent links."""
        input_shas = [
            self.photos_jan.dir_fqpn_sha256,
            self.videos_2024.dir_fqpn_sha256,
        ]
        result = DirectoryIndex.get_all_parent_shas(input_shas, DIRECTORYINDEX_SR_PARENT)
        for sha in input_shas:
            self.assertIn(sha, result)

    def test_mid_chain_returns_self_and_up(self):
        """photos/2024 (mid-chain) → itself + photos + root, NOT january."""
        result = DirectoryIndex.get_all_parent_shas(
            [self.photos_2024.dir_fqpn_sha256], DIRECTORYINDEX_SR_PARENT
        )
        expected = {
            self.root.dir_fqpn_sha256,
            self.photos.dir_fqpn_sha256,
            self.photos_2024.dir_fqpn_sha256,
        }
        self.assertEqual(result, expected)
        # january is a child, not an ancestor — must NOT be included
        self.assertNotIn(self.photos_jan.dir_fqpn_sha256, result)

    # --- performance / query-count test ---

    def test_query_count_is_bounded(self):
        """
        Current implementation: O(depth) queries.  For a 4-level hierarchy
        (root → photos → 2024 → january) this should be ≤ 5 queries.

        After the path-prefix refactor this test should tighten to exactly 2.
        Update the assertion at that point.
        """
        with CaptureQueriesContext(connection) as ctx:
            DirectoryIndex.get_all_parent_shas(
                [self.photos_jan.dir_fqpn_sha256], DIRECTORYINDEX_SR_PARENT
            )
        self.assertLessEqual(
            len(ctx.captured_queries),
            5,
            f"Expected ≤5 queries, got {len(ctx.captured_queries)}",
        )


# ===========================================================================
# 2. files_in_dir tests
# ===========================================================================

@pytest.mark.django_db
class TestFilesInDir(TestCase):
    """
    Behaviour tests for DirectoryIndex.files_in_dir().

    Tests cover both distinct=False (simple queryset) and distinct=True
    (deduplication path — the one being refactored to use Subquery).

    The collation test is the most critical: files whose names differ only
    in separator characters (underscore vs hyphen) must sort identically
    whether distinct=False or distinct=True, because both paths must use
    PostgreSQL collation, not Python's.

    No real files are created on disk.  FileIndex records are inserted
    directly into the test DB via _create_fileindex().
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        _make_fs_dirs(self.temp_dir)

        _, self.directory = DirectoryIndex.add_directory(self.temp_dir + "/")

        # Cache the filetype lookup — avoids 7 identical DB hits in setUp.
        self._ft_none = filetypes.objects.get(fileext=".none")

        # Create test files:
        #
        #   file_a.jpg   — sha "aaa..." (unique)
        #   file_b.jpg   — sha "bbb..." (unique)
        #   file_c.jpg   — sha "ccc..." (unique)
        #   dup1.jpg     — sha "ddd..." (duplicate content, two locations)
        #   dup2.jpg     — sha "ddd..." (same file_sha256 as dup1)
        #
        # After distinct=True deduplication there should be 6 unique
        # file_sha256 values (a, b, c, d, e, f).
        #
        # The separator-collation files test the specific bug that prompted
        # the two-query design:
        #
        #   photo_holiday.jpg  — name contains underscore
        #   photo-holiday.jpg  — name contains hyphen
        #
        # NaturalSortField lowercases and zero-pads digits but does NOT
        # normalise separators, so '_' and '-' are preserved verbatim in the
        # sort key.  PostgreSQL en_US.UTF-8 sorts '_' before '-' (opposite of
        # Python ASCII where '-' 0x2D < '_' 0x5F).

        ft = self._ft_none
        self.file_a = _create_fileindex(self.directory, "file_a.jpg", "a" * 64, "ua" * 32, ft)
        self.file_b = _create_fileindex(self.directory, "file_b.jpg", "b" * 64, "ub" * 32, ft)
        self.file_c = _create_fileindex(self.directory, "file_c.jpg", "c" * 64, "uc" * 32, ft)
        self.dup1 = _create_fileindex(self.directory, "dup1.jpg", "d" * 64, "ud1" + "x" * 61, ft)
        self.dup2 = _create_fileindex(self.directory, "dup2.jpg", "d" * 64, "ud2" + "x" * 61, ft)

        # Separator-collation test files
        self.sep_under = _create_fileindex(
            self.directory, "photo_holiday.jpg", "e" * 64, "ue" * 32, ft
        )
        self.sep_dash = _create_fileindex(
            self.directory, "photo-holiday.jpg", "f" * 64, "uf" * 32, ft
        )

    def tearDown(self):
        if hasattr(self, "temp_dir") and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    # --- distinct=False tests ---

    def test_non_distinct_returns_all_files(self):
        """Without distinct, all 7 records are returned."""
        result = self.directory.files_in_dir(sort=0, distinct=False, select_related=())
        self.assertEqual(result.count(), 7)

    def test_non_distinct_returns_queryset(self):
        """distinct=False must return a QuerySet, not a list."""
        result = self.directory.files_in_dir(sort=0, distinct=False, select_related=())
        self.assertIsInstance(result, QuerySet)

    def test_non_distinct_excludes_delete_pending(self):
        """Files with delete_pending=True must be excluded."""
        self.file_a.delete_pending = True
        self.file_a.save(update_fields=["delete_pending"])
        result = self.directory.files_in_dir(sort=0, distinct=False, select_related=())
        self.assertEqual(result.count(), 6)

    def test_non_distinct_additional_filters(self):
        """additional_filters kwarg is applied correctly."""
        result = self.directory.files_in_dir(
            sort=0,
            distinct=False,
            select_related=(),
            additional_filters={"name": "file_a.jpg"},
        )
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first().name, "file_a.jpg")

    # --- distinct=True tests ---

    def test_distinct_deduplicates_by_file_sha256(self):
        """
        dup1 and dup2 share file_sha256 → distinct result has 6 unique items
        (a, b, c, d, e, f).
        """
        result = self.directory.files_in_dir(sort=0, distinct=True, select_related=())
        # Result is a list when distinct=True
        self.assertIsInstance(result, list)
        file_shas = [f.file_sha256 for f in result]
        self.assertEqual(len(file_shas), 6)
        self.assertEqual(len(set(file_shas)), 6, "file_sha256 values must be unique")

    def test_distinct_returns_list(self):
        """distinct=True must return a list, not a QuerySet."""
        result = self.directory.files_in_dir(sort=0, distinct=True, select_related=())
        self.assertIsInstance(result, list)

    def test_distinct_excludes_delete_pending(self):
        """delete_pending records are excluded even in distinct mode."""
        self.file_a.delete_pending = True
        self.file_a.save(update_fields=["delete_pending"])
        result = self.directory.files_in_dir(sort=0, distinct=True, select_related=())
        names = [f.name for f in result]
        self.assertNotIn("file_a.jpg", names)

    def test_distinct_true_matches_distinct_false_order(self):
        """
        CRITICAL: sort order must be identical between distinct=False and
        distinct=True for files that have unique file_sha256 values.

        Both must use PostgreSQL collation.  If distinct=True reverts to Python
        sorting, separator characters ('_' vs '-') will sort differently.
        """
        # Use only non-duplicate files for this comparison so DISTINCT ON
        # doesn't change which record is picked
        non_dup_shas = {
            self.sep_under.file_sha256,
            self.sep_dash.file_sha256,
            self.file_a.file_sha256,
            self.file_b.file_sha256,
            self.file_c.file_sha256,
        }

        # distinct=False: queryset, filter to non-dup files only
        qs_result = list(
            self.directory.files_in_dir(sort=2, distinct=False, select_related=())
            .filter(file_sha256__in=non_dup_shas)
        )

        # distinct=True: list, filter to non-dup files only
        distinct_result = [
            f for f in self.directory.files_in_dir(sort=2, distinct=True, select_related=())
            if f.file_sha256 in non_dup_shas
        ]

        qs_names = [f.name for f in qs_result]
        distinct_names = [f.name for f in distinct_result]

        self.assertEqual(
            qs_names,
            distinct_names,
            f"Sort order mismatch:\n  non-distinct: {qs_names}\n  distinct:     {distinct_names}",
        )

    def test_distinct_separator_collation(self):
        """
        '_' and '-' separator collation: PostgreSQL en_US.UTF-8 sorts '_' before
        '-'.  Python ASCII sorts them opposite ('-' 0x2D < '_' 0x5F).

        This test catches any regression where Python sorting is accidentally
        reintroduced into the distinct=True path.

        Sort order 2 sorts by name_sort only, making this a clean comparison.
        """
        result = self.directory.files_in_dir(sort=2, distinct=True, select_related=())
        names = [f.name for f in result]

        # Both files must be present
        self.assertIn("photo_holiday.jpg", names)
        self.assertIn("photo-holiday.jpg", names)

        under_pos = names.index("photo_holiday.jpg")
        dash_pos = names.index("photo-holiday.jpg")

        # PostgreSQL en_US.UTF-8: '_' sorts before '-'
        # (underscore position must be lower index than dash position)
        self.assertLess(
            under_pos,
            dash_pos,
            f"Expected 'photo_holiday.jpg' ({under_pos}) before "
            f"'photo-holiday.jpg' ({dash_pos}) per PostgreSQL collation",
        )

    def test_distinct_fields_only_reduces_fields(self):
        """fields_only parameter restricts loaded fields in distinct mode."""
        result = self.directory.files_in_dir(
            sort=0,
            distinct=True,
            select_related=(),
            fields_only=("unique_sha256", "file_sha256"),
        )
        self.assertIsInstance(result, list)
        # Should still return the right number of distinct records
        self.assertEqual(len({f.file_sha256 for f in result}), 6)

    def test_distinct_with_select_related(self):
        """
        select_related is applied correctly on the distinct=True path.

        This exercises the real-world call from get_distinct_file_shas(), which
        passes FILEINDEX_SR_FILETYPE_HOME_VIRTUAL.  The Subquery refactor must
        preserve this — the outer query still receives select_related.
        """
        result = self.directory.files_in_dir(
            sort=0,
            distinct=True,
            select_related=FILEINDEX_SR_FILETYPE,
        )
        self.assertIsInstance(result, list)
        # filetype relation must be pre-loaded (no extra query on access)
        with CaptureQueriesContext(connection) as ctx:
            _ = [f.filetype for f in result]
        self.assertEqual(
            len(ctx.captured_queries),
            0,
            "filetype should be pre-loaded via select_related, not lazy-loaded",
        )

    def test_distinct_with_additional_filters(self):
        """
        additional_filters is applied inside the distinct=True path.

        The filter must be applied in the inner DISTINCT ON query so that
        excluded records are not picked as the representative row for a SHA.
        """
        # Filter to only files whose name starts with "file_"
        result = self.directory.files_in_dir(
            sort=0,
            distinct=True,
            select_related=(),
            additional_filters={"name__startswith": "file_"},
        )
        names = [f.name for f in result]
        # Only file_a, file_b, file_c should appear
        self.assertEqual(sorted(names), ["file_a.jpg", "file_b.jpg", "file_c.jpg"])
        # Duplicate files (dup1/dup2) and separator files must be absent
        for excluded in ("dup1.jpg", "dup2.jpg", "photo_holiday.jpg", "photo-holiday.jpg"):
            self.assertNotIn(excluded, names)

    # --- query count tests (regression guards for the refactor) ---

    def test_distinct_query_count(self):
        """
        Baseline: current implementation issues 2 queries for distinct=True:
          1. DISTINCT ON query to get PKs
          2. Re-sort query with pk__in=[...]

        After the Subquery refactor, tighten this assertion to assertEqual(..., 1).
        """
        with CaptureQueriesContext(connection) as ctx:
            self.directory.files_in_dir(sort=0, distinct=True, select_related=())

        self.assertLessEqual(
            len(ctx.captured_queries),
            2,
            f"Expected ≤2 queries for distinct=True, got {len(ctx.captured_queries)}",
        )

    def test_non_distinct_single_query(self):
        """distinct=False must always issue exactly 1 query (no extra round-trips)."""
        with CaptureQueriesContext(connection) as ctx:
            list(self.directory.files_in_dir(sort=0, distinct=False, select_related=()))

        self.assertEqual(
            len(ctx.captured_queries),
            1,
            f"Expected 1 query for distinct=False, got {len(ctx.captured_queries)}",
        )

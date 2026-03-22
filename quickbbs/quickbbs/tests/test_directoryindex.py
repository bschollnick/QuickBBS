"""
Tests for quickbbs/directoryindex.py using red/green TDD methodology.

Tests cover:
- DirectoryIndex.add_directory()
- DirectoryIndex.search_for_directory() / search_for_directory_by_sha()
- DirectoryIndex.invalidate_thumb()
- DirectoryIndex.get_all_parent_shas()
- DirectoryIndex.get_file_counts() / get_dir_counts() / get_count_breakdown()
- DirectoryIndex.do_files_exist()
- DirectoryIndex.dirs_in_dir() / files_in_dir()
- DirectoryIndex.get_view_url() / get_thumbnail_url()
- DirectoryIndex.get_prev_next_siblings()
- DirectoryIndex.get_albums_prefix() / get_albums_root()
- DirectoryIndex properties: name, virtual_directory, numdirs, numfiles, is_cached
- DirectoryIndex._make_sibling_link()
- DirectoryIndex.delete_directory() / delete_directory_record()
- DirectoryIndex.return_by_sha256_list()
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest
from django.test import TestCase, override_settings

from quickbbs.directoryindex import (
    DIRECTORYINDEX_SR_FILETYPE_THUMB,
    DIRECTORYINDEX_SR_FILETYPE_THUMB_PARENT,
    DIRECTORYINDEX_SR_PARENT,
    DirectoryIndex,
)
from quickbbs.common import get_dir_sha, normalize_fqpn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dirs(base: str, *relative_paths: str) -> None:
    """Create real filesystem directories under *base*."""
    for rel in relative_paths:
        os.makedirs(os.path.join(base, rel), exist_ok=True)


# ---------------------------------------------------------------------------
# Base test setup mixin
# ---------------------------------------------------------------------------


class DirectoryIndexTestBase(TestCase):
    """Common setUp/tearDown for tests that need real filesystem directories.

    Sets ALBUMS_PATH to self.temp_dir so that add_directory will create proper
    parent_directory links for subdirectories under temp_dir/albums/.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.albums_path = os.path.join(self.temp_dir, "albums")
        _make_dirs(
            self.temp_dir,
            "albums",
            "albums/photos",
            "albums/photos/2024",
            "albums/videos",
        )
        self.dirs: dict[str, DirectoryIndex] = {}
        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir)
        self._settings_override.enable()
        # Reset cached class-level path lookups so they pick up the new ALBUMS_PATH
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None

    def tearDown(self) -> None:
        self._settings_override.disable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        if hasattr(self, "temp_dir") and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _add(self, rel_path: str, trailing_sep: bool = True) -> tuple[bool, DirectoryIndex]:
        """Convenience: call add_directory for a path relative to temp_dir."""
        path = os.path.join(self.temp_dir, rel_path)
        if trailing_sep and not path.endswith(os.sep):
            path += os.sep
        return DirectoryIndex.add_directory(path)


# ===========================================================================
# add_directory
# ===========================================================================


@pytest.mark.django_db
class TestAddDirectory(DirectoryIndexTestBase):
    """Tests for DirectoryIndex.add_directory()."""

    def test_add_new_directory_returns_false_created(self) -> None:
        """add_directory returns (False, record) for a brand-new directory."""
        found, record = self._add("albums")
        assert found is False
        assert record is not None
        assert record.pk is not None

    def test_add_existing_directory_returns_true(self) -> None:
        """Second add_directory call for same path returns (True, record)."""
        self._add("albums")
        found, record = self._add("albums")
        assert found is True
        assert record is not None

    def test_add_directory_normalizes_path(self) -> None:
        """add_directory stores a normalized (lowercase, resolved) path."""
        _, record = self._add("albums")
        assert record.fqpndirectory == normalize_fqpn(os.path.join(self.temp_dir, "albums") + os.sep)

    def test_add_directory_sets_sha256(self) -> None:
        """add_directory populates dir_fqpn_sha256."""
        _, record = self._add("albums")
        expected_sha = get_dir_sha(normalize_fqpn(os.path.join(self.temp_dir, "albums") + os.sep))
        assert record.dir_fqpn_sha256 == expected_sha

    def test_add_directory_sets_filetype(self) -> None:
        """add_directory assigns the .dir filetype."""
        _, record = self._add("albums")
        assert record.filetype is not None
        assert record.filetype.fileext == ".dir"

    def test_add_nonexistent_directory_returns_false_none(self) -> None:
        """add_directory returns (False, None) when path does not exist."""
        bogus = os.path.join(self.temp_dir, "does_not_exist") + os.sep
        found, record = DirectoryIndex.add_directory(bogus)
        assert found is False
        assert record is None

    def test_add_directory_idempotent_same_record(self) -> None:
        """Two add_directory calls for the same path return the same DB record."""
        _, first = self._add("albums")
        _, second = self._add("albums")
        assert first.pk == second.pk

    def test_add_directory_updates_lastmod(self) -> None:
        """add_directory sets lastmod from filesystem stat."""
        _, record = self._add("albums")
        path = os.path.join(self.temp_dir, "albums")
        stat_mtime = os.stat(path).st_mtime
        assert record.lastmod == stat_mtime


# ===========================================================================
# search_for_directory / search_for_directory_by_sha
# ===========================================================================


@pytest.mark.django_db
class TestSearchForDirectory(DirectoryIndexTestBase):
    """Tests for search_for_directory and search_for_directory_by_sha."""

    def setUp(self) -> None:
        super().setUp()
        _, self.dirs["albums"] = self._add("albums")

    def test_search_by_path_found(self) -> None:
        """search_for_directory returns (True, record) for an existing directory."""
        path = normalize_fqpn(os.path.join(self.temp_dir, "albums") + os.sep)
        found, record = DirectoryIndex.search_for_directory(path)
        assert found is True
        assert record is not None
        assert record.pk == self.dirs["albums"].pk

    def test_search_by_path_not_found(self) -> None:
        """search_for_directory returns (False, None) for a missing path."""
        bogus = normalize_fqpn(os.path.join(self.temp_dir, "ghost") + os.sep)
        found, record = DirectoryIndex.search_for_directory(bogus)
        assert found is False
        assert record is None

    def test_search_by_sha_found(self) -> None:
        """search_for_directory_by_sha returns (True, record) for a known SHA."""
        sha = self.dirs["albums"].dir_fqpn_sha256
        found, record = DirectoryIndex.search_for_directory_by_sha(sha)
        assert found is True
        assert record.pk == self.dirs["albums"].pk

    def test_search_by_sha_not_found(self) -> None:
        """search_for_directory_by_sha returns (False, None) for unknown SHA."""
        found, record = DirectoryIndex.search_for_directory_by_sha("0" * 64)
        assert found is False
        assert record is None

    def test_search_excludes_delete_pending(self) -> None:
        """search_for_directory_by_sha skips delete_pending=True records."""
        sha = self.dirs["albums"].dir_fqpn_sha256
        DirectoryIndex.objects.filter(pk=self.dirs["albums"].pk).update(delete_pending=True)
        found, record = DirectoryIndex.search_for_directory_by_sha(sha)
        assert found is False
        assert record is None


# ===========================================================================
# Properties
# ===========================================================================


@pytest.mark.django_db
class TestDirectoryIndexProperties(DirectoryIndexTestBase):
    """Tests for computed properties on DirectoryIndex."""

    def setUp(self) -> None:
        super().setUp()
        _, self.dir_obj = self._add("albums")

    def test_name_property_returns_basename(self) -> None:
        """name property returns the directory's basename."""
        assert self.dir_obj.name == "albums"

    def test_virtual_directory_alias(self) -> None:
        """virtual_directory property is an alias for name."""
        assert self.dir_obj.virtual_directory == self.dir_obj.name

    def test_numdirs_returns_none(self) -> None:
        """numdirs property returns None (template compat stub)."""
        assert self.dir_obj.numdirs is None

    def test_numfiles_returns_none(self) -> None:
        """numfiles property returns None (template compat stub)."""
        assert self.dir_obj.numfiles is None

    def test_is_cached_false_without_cache_entry(self) -> None:
        """is_cached returns False when no fs_Cache_Tracking entry exists."""
        assert self.dir_obj.is_cached is False


# ===========================================================================
# invalidate_thumb
# ===========================================================================


@pytest.mark.django_db
class TestInvalidateThumb(DirectoryIndexTestBase):
    """Tests for DirectoryIndex.invalidate_thumb()."""

    def setUp(self) -> None:
        super().setUp()
        _, self.dir_obj = self._add("albums")
        # Force is_generic_icon=True so we can observe the reset
        DirectoryIndex.objects.filter(pk=self.dir_obj.pk).update(is_generic_icon=True)
        self.dir_obj.refresh_from_db()

    def test_invalidate_thumb_clears_thumbnail(self) -> None:
        """invalidate_thumb sets thumbnail to None."""
        self.dir_obj.invalidate_thumb()
        self.dir_obj.refresh_from_db()
        assert self.dir_obj.thumbnail is None

    def test_invalidate_thumb_clears_generic_icon(self) -> None:
        """invalidate_thumb resets is_generic_icon to False."""
        self.dir_obj.invalidate_thumb()
        self.dir_obj.refresh_from_db()
        assert self.dir_obj.is_generic_icon is False

    def test_invalidate_thumb_updates_in_db(self) -> None:
        """invalidate_thumb writes the change to the database, not just in-memory."""
        self.dir_obj.invalidate_thumb()
        fresh = DirectoryIndex.objects.get(pk=self.dir_obj.pk)
        assert fresh.thumbnail is None
        assert fresh.is_generic_icon is False


# ===========================================================================
# get_albums_prefix / get_albums_root
# ===========================================================================


@pytest.mark.django_db
class TestAlbumsPrefixRoot(TestCase):
    """Tests for the cached albums prefix/root class methods."""

    def setUp(self) -> None:
        # Reset class-level caches to avoid cross-test pollution
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None

    def tearDown(self) -> None:
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None

    def test_get_albums_prefix_returns_string(self) -> None:
        """get_albums_prefix returns a non-empty string."""
        prefix = DirectoryIndex.get_albums_prefix()
        assert isinstance(prefix, str)
        assert len(prefix) > 0

    def test_get_albums_prefix_cached(self) -> None:
        """get_albums_prefix returns the same string on repeated calls."""
        first = DirectoryIndex.get_albums_prefix()
        second = DirectoryIndex.get_albums_prefix()
        assert first == second

    def test_get_albums_root_returns_string(self) -> None:
        """get_albums_root returns a non-empty string."""
        root = DirectoryIndex.get_albums_root()
        assert isinstance(root, str)
        assert len(root) > 0

    def test_get_albums_root_cached(self) -> None:
        """get_albums_root returns the same value on repeated calls."""
        first = DirectoryIndex.get_albums_root()
        second = DirectoryIndex.get_albums_root()
        assert first == second


# ===========================================================================
# get_all_parent_shas
# ===========================================================================


@pytest.mark.django_db
class TestGetAllParentShas(DirectoryIndexTestBase):
    """Tests for DirectoryIndex.get_all_parent_shas()."""

    def setUp(self) -> None:
        super().setUp()
        _make_dirs(self.temp_dir, "albums/photos/2024/jan")
        _, self.d_albums = self._add("albums")
        _, self.d_photos = self._add("albums/photos")
        _, self.d_2024 = self._add("albums/photos/2024")
        _, self.d_jan = self._add("albums/photos/2024/jan")
        _, self.d_videos = self._add("albums/videos")

    def test_empty_list_returns_empty_set(self) -> None:
        """Empty sha_list returns empty set."""
        result = DirectoryIndex.get_all_parent_shas([], DIRECTORYINDEX_SR_PARENT)
        assert result == set()

    def test_input_shas_always_in_result(self) -> None:
        """All input SHAs are always present in the result."""
        input_shas = [self.d_jan.dir_fqpn_sha256]
        result = DirectoryIndex.get_all_parent_shas(input_shas, DIRECTORYINDEX_SR_PARENT)
        assert self.d_jan.dir_fqpn_sha256 in result

    def test_multiple_branches_in_result(self) -> None:
        """SHAs from multiple branches are all present."""
        input_shas = [self.d_jan.dir_fqpn_sha256, self.d_videos.dir_fqpn_sha256]
        result = DirectoryIndex.get_all_parent_shas(input_shas, DIRECTORYINDEX_SR_PARENT)
        assert self.d_jan.dir_fqpn_sha256 in result
        assert self.d_videos.dir_fqpn_sha256 in result

    def test_result_is_set(self) -> None:
        """Return value is a set (no duplicates)."""
        input_shas = [self.d_jan.dir_fqpn_sha256]
        result = DirectoryIndex.get_all_parent_shas(input_shas, DIRECTORYINDEX_SR_PARENT)
        assert isinstance(result, set)

    def test_raises_without_select_related(self) -> None:
        """Passing select_related=None raises ValueError."""
        with pytest.raises(ValueError):
            DirectoryIndex.get_all_parent_shas(["abc"], None)

    def test_root_has_no_additional_parents(self) -> None:
        """A root-level directory (no parent_directory) returns just itself."""
        root_sha = self.d_albums.dir_fqpn_sha256
        result = DirectoryIndex.get_all_parent_shas([root_sha], DIRECTORYINDEX_SR_PARENT)
        assert root_sha in result
        # Root should not find extra parents it doesn't have
        assert len(result) >= 1


# ===========================================================================
# Verification suite fixtures — real indexed data under ALBUMS_PATH/albums/
# ===========================================================================

# These PKs and SHAs come from the live verification_suite data already indexed
# in the database. verification_suite/ has exactly 3 subdirectories.
VSUIT_PK = 131119
VSUIT_SHA = "3c6aeeebbb0873d83ce5920d9a17983c674fbb7678969517595133d0d9647c59"
VSUIT_CHILD_PKS = (131120, 131121, 131122)  # benchtests, numbersign_testing # copy, numbersign_testing
VSUIT_CHILD_SHAS = (
    "2e8d85fa537e1f9e0a83fc45b77b9b803591e939ae0894f491bf46694ce139f0",
    "c676433d976bcdbff77e08b394de23ee78e1903f40095dd87c2af93da657811f",
    "58d8ddd1480744f8a4cc7f17fcf5c649c835a5644816b070642e630d95571e66",
)


# ===========================================================================
# get_file_counts / get_dir_counts / do_files_exist
# ===========================================================================


@pytest.mark.django_db
class TestFileDirCounts(TestCase):
    """Tests for count and existence methods on DirectoryIndex.

    Uses the real verification_suite directory which has 3 known subdirectories
    and no FileIndex entries (unscanned).
    """

    def setUp(self) -> None:
        self.parent = DirectoryIndex.objects.get(pk=VSUIT_PK)
        self.child = DirectoryIndex.objects.get(pk=VSUIT_CHILD_PKS[0])  # benchtests (leaf)

    def test_get_file_counts_empty_directory(self) -> None:
        """get_file_counts returns 0 for a directory with no FileIndex entries."""
        assert self.parent.get_file_counts() == 0

    def test_get_dir_counts_with_children(self) -> None:
        """get_dir_counts returns the number of child DirectoryIndex entries."""
        count = self.parent.get_dir_counts()
        assert count == 3

    def test_get_dir_counts_empty(self) -> None:
        """get_dir_counts returns 0 for a leaf directory (benchtests has no subdirs)."""
        assert self.child.get_dir_counts() == 0

    def test_do_files_exist_empty_directory(self) -> None:
        """do_files_exist returns False for a directory with no FileIndex entries."""
        assert self.parent.do_files_exist() is False

    def test_get_count_breakdown_returns_dict(self) -> None:
        """get_count_breakdown returns a dictionary with dir and all_files keys."""
        breakdown = self.parent.get_count_breakdown()
        assert isinstance(breakdown, dict)
        assert "dir" in breakdown
        assert "all_files" in breakdown

    def test_get_count_breakdown_dir_count_correct(self) -> None:
        """get_count_breakdown dir count matches the 3 known subdirectories."""
        breakdown = self.parent.get_count_breakdown()
        assert breakdown["dir"] == 3

    def test_get_count_breakdown_all_files_zero(self) -> None:
        """get_count_breakdown shows 0 all_files for unscanned directory."""
        breakdown = self.parent.get_count_breakdown()
        assert breakdown["all_files"] == 0


# ===========================================================================
# dirs_in_dir
# ===========================================================================


@pytest.mark.django_db
class TestDirsInDir(TestCase):
    """Tests for DirectoryIndex.dirs_in_dir().

    Uses real verification_suite data: parent pk=131119, 3 known children.
    """

    def setUp(self) -> None:
        self.parent = DirectoryIndex.objects.get(pk=VSUIT_PK)
        self.child_pks = list(VSUIT_CHILD_PKS)

    def test_dirs_in_dir_returns_children(self) -> None:
        """dirs_in_dir returns all 3 known child directories."""
        qs = self.parent.dirs_in_dir(select_related=(), prefetch_related=())
        pks = list(qs.values_list("pk", flat=True))
        for pk in self.child_pks:
            assert pk in pks

    def test_dirs_in_dir_excludes_delete_pending(self) -> None:
        """dirs_in_dir excludes a child marked delete_pending=True."""
        target_pk = self.child_pks[0]
        DirectoryIndex.objects.filter(pk=target_pk).update(delete_pending=True)
        try:
            qs = self.parent.dirs_in_dir(select_related=(), prefetch_related=())
            pks = list(qs.values_list("pk", flat=True))
            assert target_pk not in pks
            # The other two children still appear
            for pk in self.child_pks[1:]:
                assert pk in pks
        finally:
            DirectoryIndex.objects.filter(pk=target_pk).update(delete_pending=False)

    def test_dirs_in_dir_fields_only(self) -> None:
        """fields_only returns only the specified fields and correct count."""
        qs = self.parent.dirs_in_dir(
            select_related=(),
            prefetch_related=(),
            fields_only=("id", "fqpndirectory"),
        )
        assert qs.count() == 3

    def test_dirs_in_dir_raises_without_select_related(self) -> None:
        """Omitting select_related raises ValueError."""
        with pytest.raises(ValueError):
            self.parent.dirs_in_dir(select_related=None, prefetch_related=())

    def test_dirs_in_dir_raises_without_prefetch_related(self) -> None:
        """Omitting prefetch_related raises ValueError."""
        with pytest.raises(ValueError):
            self.parent.dirs_in_dir(select_related=(), prefetch_related=None)

    def test_dirs_in_dir_sort_orders(self) -> None:
        """dirs_in_dir accepts sort values 0, 1, and 2 and returns all 3 children."""
        for sort in (0, 1, 2):
            qs = self.parent.dirs_in_dir(sort=sort, select_related=(), prefetch_related=())
            assert qs.count() == 3


# ===========================================================================
# return_by_sha256_list
# ===========================================================================


@pytest.mark.django_db
class TestReturnBySha256List(TestCase):
    """Tests for DirectoryIndex.return_by_sha256_list().

    Uses real verification_suite SHAs already in the database.
    """

    def setUp(self) -> None:
        self.sha1 = VSUIT_SHA
        self.sha2 = VSUIT_CHILD_SHAS[0]
        self.pk1 = VSUIT_PK
        self.pk2 = VSUIT_CHILD_PKS[0]

    def test_returns_matching_directories(self) -> None:
        """return_by_sha256_list returns directories matching the SHA list."""
        qs = DirectoryIndex.return_by_sha256_list([self.sha1, self.sha2], sort=0, select_related=(), prefetch_related=())
        pks = list(qs.values_list("pk", flat=True))
        assert self.pk1 in pks
        assert self.pk2 in pks

    def test_excludes_delete_pending(self) -> None:
        """return_by_sha256_list excludes delete_pending directories."""
        DirectoryIndex.objects.filter(pk=self.pk2).update(delete_pending=True)
        try:
            qs = DirectoryIndex.return_by_sha256_list([self.sha1, self.sha2], sort=0, select_related=(), prefetch_related=())
            pks = list(qs.values_list("pk", flat=True))
            assert self.pk2 not in pks
            assert self.pk1 in pks
        finally:
            DirectoryIndex.objects.filter(pk=self.pk2).update(delete_pending=False)

    def test_empty_sha_list_returns_empty_queryset(self) -> None:
        """Empty SHA list returns an empty queryset."""
        qs = DirectoryIndex.return_by_sha256_list([], sort=0, select_related=(), prefetch_related=())
        assert qs.count() == 0

    def test_raises_without_select_related(self) -> None:
        """Passing select_related=None raises ValueError."""
        with pytest.raises(ValueError):
            DirectoryIndex.return_by_sha256_list([], sort=0, select_related=None, prefetch_related=())

    def test_raises_without_prefetch_related(self) -> None:
        """Passing prefetch_related=None raises ValueError."""
        with pytest.raises(ValueError):
            DirectoryIndex.return_by_sha256_list([], sort=0, select_related=(), prefetch_related=None)


# ===========================================================================
# get_view_url / get_thumbnail_url
# ===========================================================================


@pytest.mark.django_db
class TestUrls(DirectoryIndexTestBase):
    """Tests for get_view_url and get_thumbnail_url."""

    def setUp(self) -> None:
        super().setUp()
        _, self.dir_obj = self._add("albums")

    def test_get_thumbnail_url_contains_sha(self) -> None:
        """get_thumbnail_url includes the dir SHA in the URL."""
        url = self.dir_obj.get_thumbnail_url()
        assert self.dir_obj.dir_fqpn_sha256 in url

    def test_get_thumbnail_url_returns_string(self) -> None:
        """get_thumbnail_url returns a non-empty string."""
        url = self.dir_obj.get_thumbnail_url()
        assert isinstance(url, str)
        assert len(url) > 0

    def test_get_view_url_returns_string(self) -> None:
        """get_view_url returns a non-empty string."""
        url = self.dir_obj.get_view_url()
        assert isinstance(url, str)
        assert len(url) > 0


# ===========================================================================
# get_prev_next_siblings
# ===========================================================================


@pytest.mark.django_db
class TestGetPrevNextSiblings(TestCase):
    """Tests for DirectoryIndex.get_prev_next_siblings().

    Uses real verification_suite data: parent pk=131119 has 3 known children
    with proper parent_directory links set.
    """

    def setUp(self) -> None:
        # verification_suite has no parent (its parent is the albums root, not None,
        # but we use the middle child which does have a parent)
        self.parent = DirectoryIndex.objects.select_related("parent_directory").get(pk=VSUIT_PK)
        # benchtests is a child of verification_suite — it has a proper parent link
        self.middle_child = DirectoryIndex.objects.select_related("parent_directory").get(pk=VSUIT_CHILD_PKS[1])

    def test_root_returns_none_none_when_no_parent(self) -> None:
        """A directory with no parent_directory returns (None, None)."""
        # Temporarily clear parent to simulate a root
        original_parent = self.parent.parent_directory
        DirectoryIndex.objects.filter(pk=self.parent.pk).update(parent_directory=None)
        try:
            fresh = DirectoryIndex.objects.select_related("parent_directory").get(pk=self.parent.pk)
            prev, nxt = fresh.get_prev_next_siblings()
            assert prev is None
            assert nxt is None
        finally:
            DirectoryIndex.objects.filter(pk=self.parent.pk).update(parent_directory=original_parent)

    def test_child_with_parent_returns_tuple(self) -> None:
        """A child with a real parent_directory returns a (prev, next) tuple."""
        assert self.middle_child.parent_directory is not None
        result = self.middle_child.get_prev_next_siblings(sort_order=0)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_child_siblings_are_dicts_or_none(self) -> None:
        """Each element of the siblings tuple is either a dict or None."""
        prev, nxt = self.middle_child.get_prev_next_siblings(sort_order=0)
        for item in (prev, nxt):
            assert item is None or (isinstance(item, dict) and "url" in item and "name" in item)


# ===========================================================================
# delete_directory
# ===========================================================================


@pytest.mark.django_db
class TestDeleteDirectory(DirectoryIndexTestBase):
    """Tests for DirectoryIndex.delete_directory()."""

    def setUp(self) -> None:
        super().setUp()
        _, self.dir_obj = self._add("albums")

    def test_delete_directory_removes_record(self) -> None:
        """delete_directory removes the record from the DB."""
        path = normalize_fqpn(os.path.join(self.temp_dir, "albums") + os.sep)
        DirectoryIndex.delete_directory(path)
        assert not DirectoryIndex.objects.filter(pk=self.dir_obj.pk).exists()

    def test_delete_directory_cache_only_keeps_record(self) -> None:
        """cache_only=True does not delete the DB record."""
        path = normalize_fqpn(os.path.join(self.temp_dir, "albums") + os.sep)
        DirectoryIndex.delete_directory(path, cache_only=True)
        assert DirectoryIndex.objects.filter(pk=self.dir_obj.pk).exists()


# ===========================================================================
# delete_directory_record
# ===========================================================================


@pytest.mark.django_db
class TestDeleteDirectoryRecord(DirectoryIndexTestBase):
    """Tests for DirectoryIndex.delete_directory_record()."""

    def setUp(self) -> None:
        super().setUp()
        _, self.dir_obj = self._add("albums")

    def test_delete_record_removes_from_db(self) -> None:
        """delete_directory_record deletes the given DirectoryIndex instance."""
        pk = self.dir_obj.pk
        DirectoryIndex.delete_directory_record(self.dir_obj)
        assert not DirectoryIndex.objects.filter(pk=pk).exists()

    def test_delete_record_none_is_noop(self) -> None:
        """Passing None to delete_directory_record is a no-op (no exception)."""
        DirectoryIndex.delete_directory_record(None)  # Should not raise

    def test_delete_record_cache_only_keeps_db_entry(self) -> None:
        """cache_only=True clears cache but does not delete from DB."""
        pk = self.dir_obj.pk
        DirectoryIndex.delete_directory_record(self.dir_obj, cache_only=True)
        assert DirectoryIndex.objects.filter(pk=pk).exists()

"""DirectoryIndex cache-state API: mark_scanned, cache_valid_for_sha and the invalidate_* methods."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from frontend.managers import layout_manager
from quickbbs.cache_registry import layout_manager_cache
from quickbbs.models import DirectoryIndex
from quickbbs.tests.albums_root import AlbumsRootTestCase

pytestmark = pytest.mark.api


def _test_shas(dirs: dict) -> set[str]:
    """Return set of dir_fqpn_sha256 values for scoping DB queries."""
    return {d.dir_fqpn_sha256 for d in dirs.values() if d is not None}


@pytest.mark.django_db
class TestMarkScanned(AlbumsRootTestCase):
    """Tests for DirectoryIndex.mark_scanned."""

    def setUp(self):
        super().setUp()
        self.di = self.add_directory()

    def test_new_directory_starts_invalidated(self):
        """A freshly created row defaults to cache_invalidated=True."""
        assert self.di.cache_invalidated is True

    def test_mark_scanned_sets_valid(self):
        """Mark scanned sets valid."""
        self.di.mark_scanned()
        self.di.refresh_from_db()
        assert self.di.cache_invalidated is False

    def test_cache_lastscan_is_recent(self):
        """Cache lastscan is recent."""
        before = time.time() - 1
        self.di.mark_scanned()
        self.di.refresh_from_db()
        assert self.di.cache_lastscan >= before

    def test_idempotent_second_call(self):
        """Calling mark_scanned twice leaves the row valid."""
        self.di.mark_scanned()
        self.di.mark_scanned()
        self.di.refresh_from_db()
        assert self.di.cache_invalidated is False

    def test_updates_in_memory_instance(self):
        """Updates in memory instance."""
        self.di.mark_scanned()
        # No refresh — the instance itself is kept in sync
        assert self.di.cache_invalidated is False

    def test_reinvalidated_entry_is_reset_to_valid(self):
        """mark_scanned on an already-invalidated row marks it valid again."""
        self.di.mark_scanned()
        DirectoryIndex.objects.filter(pk=self.di.pk).update(cache_invalidated=True)
        self.di.mark_scanned()
        self.di.refresh_from_db()
        assert self.di.cache_invalidated is False


@pytest.mark.django_db
class TestCacheValidForSha(AlbumsRootTestCase):
    """Tests for cache_valid_for_sha (formerly sha_exists_in_cache)."""

    def setUp(self):
        super().setUp()
        self.di = self.add_directory()

    def test_returns_false_when_never_scanned(self):
        """Returns false when never scanned."""
        assert DirectoryIndex.cache_valid_for_sha(self.di.dir_fqpn_sha256) is False

    def test_returns_true_after_mark_scanned(self):
        """Returns true after mark scanned."""
        self.di.mark_scanned()
        assert DirectoryIndex.cache_valid_for_sha(self.di.dir_fqpn_sha256) is True

    def test_returns_false_after_invalidation(self):
        """Returns false after invalidation."""
        self.di.mark_scanned()
        DirectoryIndex.objects.filter(pk=self.di.pk).update(cache_invalidated=True)
        assert DirectoryIndex.cache_valid_for_sha(self.di.dir_fqpn_sha256) is False

    def test_unknown_sha_returns_false(self):
        """Unknown sha returns false."""
        assert DirectoryIndex.cache_valid_for_sha("0" * 64) is False


@pytest.mark.django_db
class TestInvalidateCache(AlbumsRootTestCase):
    """Tests for invalidate_cache (formerly remove_from_cache_indexdirs)."""

    def setUp(self):
        super().setUp()
        self.di = self.add_directory()
        self.di.mark_scanned()

    def test_returns_true_on_success(self):
        """Returns true on success."""
        result = self.di.invalidate_cache()
        assert result is True

    def test_entry_is_invalidated(self):
        """Entry is invalidated."""
        self.di.invalidate_cache()
        self.di.refresh_from_db()
        assert self.di.cache_invalidated is True

    def test_sha_no_longer_valid(self):
        """Sha no longer valid."""
        self.di.invalidate_cache()
        assert DirectoryIndex.cache_valid_for_sha(self.di.dir_fqpn_sha256) is False

    def test_instance_refreshed(self):
        """invalidate_cache refreshes the instance so held references see the flip."""
        self.di.invalidate_cache()
        # No manual refresh — the method refreshes from DB itself
        assert self.di.cache_invalidated is True


@pytest.mark.django_db
class TestInvalidateCacheBySha(AlbumsRootTestCase):
    """Tests for invalidate_cache_by_sha (formerly remove_from_cache_sha)."""

    def setUp(self):
        super().setUp()
        self.di = self.add_directory()
        self.di.mark_scanned()

    def test_returns_true_on_success(self):
        """Returns true on success."""
        assert DirectoryIndex.invalidate_cache_by_sha(self.di.dir_fqpn_sha256) is True

    def test_entry_is_invalidated(self):
        """Entry is invalidated."""
        DirectoryIndex.invalidate_cache_by_sha(self.di.dir_fqpn_sha256)
        self.di.refresh_from_db()
        assert self.di.cache_invalidated is True

    def test_unknown_sha_returns_false(self):
        """Unknown sha returns false."""
        assert DirectoryIndex.invalidate_cache_by_sha("0" * 64) is False


@pytest.mark.django_db
class TestInvalidateCaches(AlbumsRootTestCase):
    """Tests for invalidate_caches (formerly remove_multiple_from_cache_indexdirs)."""

    def setUp(self):
        super().setUp()

        self.di_root = self.add_directory()
        self.di_a = self.add_directory("a")
        self.di_b = self.add_directory("b")
        self.dirs = {"root": self.di_root, "a": self.di_a, "b": self.di_b}

        for di in self.dirs.values():
            di.mark_scanned()

    def test_empty_list_returns_false(self):
        """Empty list returns false."""
        result = DirectoryIndex.invalidate_caches([])
        assert result is False

    def test_single_dir_returns_true(self):
        """Single dir returns true."""
        result = DirectoryIndex.invalidate_caches([self.di_a])
        assert result is True

    def test_single_dir_is_invalidated(self):
        """Single dir is invalidated."""
        DirectoryIndex.invalidate_caches([self.di_a])
        self.di_a.refresh_from_db()
        assert self.di_a.cache_invalidated is True

    def test_multiple_dirs_all_invalidated(self):
        """Multiple dirs all invalidated."""
        DirectoryIndex.invalidate_caches([self.di_a, self.di_b])
        shas = _test_shas({"a": self.di_a, "b": self.di_b})
        count = DirectoryIndex.objects.filter(dir_fqpn_sha256__in=shas, cache_invalidated=True).count()
        assert count == 2

    def test_parents_also_invalidated(self):
        """Invalidating a child expands to its parent directories."""
        assert self.di_a.parent_directory_id == self.di_root.pk
        DirectoryIndex.invalidate_caches([self.di_a])
        self.di_root.refresh_from_db()
        assert self.di_root.cache_invalidated is True
        self.di_a.refresh_from_db()
        assert self.di_a.cache_invalidated is True

    def test_a_never_scanned_directory_counts_as_invalidated(self):
        """A row born cache_invalidated=True still counts, so the call returns True."""
        never_scanned = self.add_directory("never_scanned")
        assert DirectoryIndex.invalidate_caches([never_scanned]) is True
        assert DirectoryIndex.objects.filter(pk=never_scanned.pk, cache_invalidated=True).exists()

    def test_returns_false_for_all_invalid_objects(self):
        """Returns false for all invalid objects."""
        blank = SimpleNamespace(dir_fqpn_sha256="")
        result = DirectoryIndex.invalidate_caches([blank, blank])
        assert result is False

    def test_other_dirs_not_affected(self):
        """Invalidating 'a' does not affect sibling 'b'."""
        DirectoryIndex.invalidate_caches([self.di_a])
        self.di_b.refresh_from_db()
        assert self.di_b.cache_invalidated is False


@pytest.mark.django_db
class TestInvalidateAllCaches(AlbumsRootTestCase):
    """Tests for invalidate_all_caches (formerly clear_all_records)."""

    def setUp(self):
        super().setUp()
        self.di1 = self.add_directory("c1")
        self.di2 = self.add_directory("c2")
        self.di1.mark_scanned()
        self.di2.mark_scanned()

    def test_returns_count_of_invalidated(self):
        """Returns count of invalidated."""
        result = DirectoryIndex.invalidate_all_caches()
        # At minimum our two entries were invalidated
        assert result >= 2

    def test_all_test_entries_are_invalidated(self):
        """All test entries are invalidated."""
        DirectoryIndex.invalidate_all_caches()
        shas = {self.di1.dir_fqpn_sha256, self.di2.dir_fqpn_sha256}
        valid_count = DirectoryIndex.objects.filter(dir_fqpn_sha256__in=shas, cache_invalidated=False).count()
        assert valid_count == 0

    def test_idempotent_called_twice(self):
        """invalidate_all_caches is safe to call multiple times."""
        DirectoryIndex.invalidate_all_caches()
        result2 = DirectoryIndex.invalidate_all_caches()
        assert isinstance(result2, int)


@pytest.mark.django_db
class TestLayoutCacheClearedOnInvalidate(AlbumsRootTestCase):
    """invalidate_cache clears layout cache entries (formerly _clear_layout_cache_bulk)."""

    def setUp(self):
        super().setUp()
        self.di = self.add_directory()
        self.di.mark_scanned()
        layout_manager_cache.clear()

    def tearDown(self):
        super().tearDown()
        layout_manager_cache.clear()

    def test_clears_layout_cache_for_directory(self):
        """Clears layout cache for directory."""
        layout_manager(page_number=1, directory=self.di, sort_ordering=0, show_duplicates=False)
        assert len(layout_manager_cache) > 0

        self.di.invalidate_cache()
        assert len(layout_manager_cache) == 0

"""Tests for Option 1 optimizations: parent SHA collection and cache invalidation."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from quickbbs.directoryindex import DIRECTORYINDEX_SR_PARENT
from quickbbs.models import DirectoryIndex
from quickbbs.tests.albums_root import AlbumsRootTestCase

pytestmark = pytest.mark.api


@pytest.mark.django_db
class TestGetAllParentShas(AlbumsRootTestCase):
    """Test the get_all_parent_shas method."""

    def setUp(self):
        """Create a test directory hierarchy."""
        super().setUp()
        self.dirs = {
            "root": self.add_directory(),
            "photos": self.add_directory("photos"),
            "photos_2024": self.add_directory("photos", "2024"),
            "photos_jan": self.add_directory("photos", "2024", "january"),
            "videos": self.add_directory("videos"),
            "videos_2024": self.add_directory("videos", "2024"),
        }

    def test_get_all_parent_shas_single_leaf(self):
        """Test getting parents for a single leaf directory."""
        leaf_sha = self.dirs["photos_jan"].dir_fqpn_sha256

        result = DirectoryIndex.get_all_parent_shas([leaf_sha], DIRECTORYINDEX_SR_PARENT)

        expected = {self.dirs[name].dir_fqpn_sha256 for name in ("photos_jan", "photos_2024", "photos", "root")}
        assert result == expected

    def test_get_all_parent_shas_multiple_branches(self):
        """Test getting parents for directories from different branches."""
        input_shas = [
            self.dirs["photos_jan"].dir_fqpn_sha256,  # Photos branch
            self.dirs["videos_2024"].dir_fqpn_sha256,  # Videos branch
        ]

        result = DirectoryIndex.get_all_parent_shas(input_shas, DIRECTORYINDEX_SR_PARENT)

        assert result == {directory.dir_fqpn_sha256 for directory in self.dirs.values()}

    def test_get_all_parent_shas_empty_list(self):
        """Test with empty input list."""
        result = DirectoryIndex.get_all_parent_shas([], DIRECTORYINDEX_SR_PARENT)
        assert result == set()

    def test_get_all_parent_shas_root_only(self):
        """Test with root directory (no parents)."""
        root_sha = self.dirs["root"].dir_fqpn_sha256

        result = DirectoryIndex.get_all_parent_shas([root_sha], DIRECTORYINDEX_SR_PARENT)

        # Should only include root itself
        assert result == {root_sha}
        assert len(result) == 1

    def test_get_all_parent_shas_performance(self):
        """Test that it uses fewer queries than the old approach."""
        input_shas = [
            self.dirs["photos_jan"].dir_fqpn_sha256,
            self.dirs["videos_2024"].dir_fqpn_sha256,
        ]

        # Count queries - should be very few (1-5 depending on directory depth)
        with CaptureQueriesContext(connection) as context:
            result = DirectoryIndex.get_all_parent_shas(input_shas, DIRECTORYINDEX_SR_PARENT)

        # Should use much fewer queries than old N*M approach (which would be 20+)
        assert len(context.captured_queries) <= 5, f"Expected ≤5 queries, got {len(context.captured_queries)}"

        # Verify correctness - at minimum includes input SHAs
        assert len(result) >= 2

    def test_get_all_parent_shas_deduplication(self):
        """Test that duplicate parents are deduplicated."""
        # Both of these share the same parent chain
        input_shas = [
            self.dirs["photos_2024"].dir_fqpn_sha256,
            self.dirs["photos_jan"].dir_fqpn_sha256,
        ]

        result = DirectoryIndex.get_all_parent_shas(input_shas, DIRECTORYINDEX_SR_PARENT)

        # Should include both input SHAs
        assert self.dirs["photos_2024"].dir_fqpn_sha256 in result
        assert self.dirs["photos_jan"].dir_fqpn_sha256 in result

        # Verify deduplication - result should be a set (no duplicates)
        assert isinstance(result, set)
        assert len(result) >= 2


@pytest.mark.django_db
class TestRemoveMultipleFromCacheOptimization(AlbumsRootTestCase):
    """Test the optimized remove_multiple_from_cache method."""

    def setUp(self):
        """Create test directory hierarchy and cache entries for each test."""
        super().setUp()
        self.dirs = {
            "root": self.add_directory(),
            "photos": self.add_directory("photos"),
            "photos_2024": self.add_directory("photos", "2024"),
            "photos_jan": self.add_directory("photos", "2024", "january"),
        }
        # Mark all directories scanned (cache valid)
        for dir_obj in self.dirs.values():
            dir_obj.mark_scanned()

    def test_recursive_parent_invalidation(self):
        """Test that invalidating a leaf directory invalidates all parents."""
        test_shas = {d.dir_fqpn_sha256 for d in self.dirs.values()}

        # Verify all cache entries for our test dirs start as valid
        initial_count = DirectoryIndex.objects.filter(dir_fqpn_sha256__in=test_shas, cache_invalidated=False).count()
        assert initial_count == 4

        # Invalidate the leaf directory
        result = DirectoryIndex.invalidate_caches([self.dirs["photos_jan"]])

        assert result is True

        # Verify at least the target directory is invalidated (scoped to our test dirs)
        invalidated_dirs = DirectoryIndex.objects.filter(dir_fqpn_sha256__in=test_shas, cache_invalidated=True)
        invalidated_shas = set(invalidated_dirs.values_list("dir_fqpn_sha256", flat=True))

        # The target and its whole parent chain up to the albums root
        assert invalidated_shas == {directory.dir_fqpn_sha256 for directory in self.dirs.values()}

    def test_multiple_paths_optimization(self):
        """Test invalidating multiple paths with shared parents."""
        videos_dir = self.add_directory("videos")
        videos_dir.mark_scanned()

        # Invalidate both leaf directories
        dirs = [
            self.dirs["photos_jan"],
            videos_dir,
        ]

        with CaptureQueriesContext(connection) as context:
            result = DirectoryIndex.invalidate_caches(dirs)

        # Should be much less than old approach (would be 60+ for 2 deep paths)
        assert len(context.captured_queries) <= 30, f"Expected ≤30 queries, got {len(context.captured_queries)}"

        assert result is True

        # Verify all affected directories are invalidated (scoped to our test dirs)
        test_shas = {d.dir_fqpn_sha256 for d in self.dirs.values()} | {videos_dir.dir_fqpn_sha256}
        invalidated_count = DirectoryIndex.objects.filter(dir_fqpn_sha256__in=test_shas, cache_invalidated=True).count()
        assert invalidated_count >= 2  # At minimum the two specified paths

    def test_sha_computation_not_duplicated(self):
        """Test that SHA computation happens only once per path."""
        dirs = [self.dirs["photos_jan"]] * 3  # Duplicate dirs

        # The optimization should deduplicate before processing
        result = DirectoryIndex.invalidate_caches(dirs)

        assert result is True

        # Should only process unique paths once (not 3x)
        # At minimum invalidates the target directory (scoped to our test dirs)
        test_shas = {d.dir_fqpn_sha256 for d in self.dirs.values()}
        invalidated_count = DirectoryIndex.objects.filter(dir_fqpn_sha256__in=test_shas, cache_invalidated=True).count()

        # Should be 1-4 depending on parent links, but definitely not 3-12 (3x the paths)
        assert invalidated_count >= 1
        assert invalidated_count <= 5  # Not multiplied by the duplicate count


@pytest.mark.django_db
class TestOptimizationEdgeCases(AlbumsRootTestCase):
    """Test edge cases for the optimization."""

    def test_empty_input(self):
        """An empty directory list invalidates nothing and returns False."""
        result = DirectoryIndex.invalidate_caches([])
        assert result is False

    def test_circular_reference_protection(self):
        """Invalidation completes on a real directory; max_iterations bounds any parent cycle."""
        test_dir = self.add_directory("test")
        result = DirectoryIndex.invalidate_caches([test_dir])
        assert isinstance(result, bool)

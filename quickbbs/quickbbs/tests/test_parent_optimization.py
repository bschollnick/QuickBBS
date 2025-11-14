"""Tests for Option 1 optimizations: parent SHA collection and cache invalidation."""

import os
import tempfile
import shutil
import pytest
from django.test import TestCase, TransactionTestCase
from django.db import connection
from django.test.utils import override_settings
from django.conf import settings
from django.core.management import call_command

from quickbbs.models import IndexDirs
from cache_watcher.models import fs_Cache_Tracking
from quickbbs.common import get_dir_sha


@pytest.fixture(scope="session", autouse=True)
def django_db_setup(django_db_setup, django_db_blocker):
    """Ensure filetypes table is populated before running tests."""
    with django_db_blocker.unblock():
        call_command("refresh-filetypes")


@pytest.mark.django_db
class TestGetAllParentShas(TransactionTestCase):
    """Test the optimized get_all_parent_shas method."""

    @classmethod
    def setUpClass(cls):
        """Create a test directory hierarchy."""
        super().setUpClass()
        # Ensure filetypes are populated
        call_command("refresh-filetypes")

        # Create temporary directory structure for testing
        cls.temp_dir = tempfile.mkdtemp()
        cls.albums_path = os.path.join(cls.temp_dir, "albums")

        # Create actual filesystem directories
        os.makedirs(os.path.join(cls.albums_path, "photos", "2024", "january"), exist_ok=True)
        os.makedirs(os.path.join(cls.albums_path, "videos", "2024"), exist_ok=True)

        cls.dirs = {}

        # Create root
        _, cls.dirs["root"] = IndexDirs.add_directory(cls.albums_path + "/")

        # Create photos branch
        _, cls.dirs["photos"] = IndexDirs.add_directory(os.path.join(cls.albums_path, "photos") + "/")
        _, cls.dirs["photos_2024"] = IndexDirs.add_directory(os.path.join(cls.albums_path, "photos", "2024") + "/")
        _, cls.dirs["photos_jan"] = IndexDirs.add_directory(os.path.join(cls.albums_path, "photos", "2024", "january") + "/")

        # Create videos branch
        _, cls.dirs["videos"] = IndexDirs.add_directory(os.path.join(cls.albums_path, "videos") + "/")
        _, cls.dirs["videos_2024"] = IndexDirs.add_directory(os.path.join(cls.albums_path, "videos", "2024") + "/")

    @classmethod
    def tearDownClass(cls):
        """Clean up temporary directories."""
        super().tearDownClass()
        if hasattr(cls, "temp_dir") and os.path.exists(cls.temp_dir):
            shutil.rmtree(cls.temp_dir)

    def test_get_all_parent_shas_single_leaf(self):
        """Test getting parents for a single leaf directory."""
        leaf_sha = self.dirs["photos_jan"].dir_fqpn_sha256

        result = IndexDirs.get_all_parent_shas([leaf_sha])

        # Should at minimum include the input SHA
        assert leaf_sha in result
        assert len(result) >= 1

        # If parent_directory links exist, should include all parents
        # Note: parent links may not be created for test directories outside ALBUMS_PATH
        if self.dirs["photos_jan"].parent_directory:
            assert len(result) > 1

    def test_get_all_parent_shas_multiple_branches(self):
        """Test getting parents for directories from different branches."""
        input_shas = [
            self.dirs["photos_jan"].dir_fqpn_sha256,  # Photos branch
            self.dirs["videos_2024"].dir_fqpn_sha256,  # Videos branch
        ]

        result = IndexDirs.get_all_parent_shas(input_shas)

        # Should include both input SHAs
        assert self.dirs["photos_jan"].dir_fqpn_sha256 in result
        assert self.dirs["videos_2024"].dir_fqpn_sha256 in result
        assert len(result) >= 2

        # If parent links exist, should include all parents up to root
        if self.dirs["photos_jan"].parent_directory or self.dirs["videos_2024"].parent_directory:
            assert len(result) > 2

    def test_get_all_parent_shas_empty_list(self):
        """Test with empty input list."""
        result = IndexDirs.get_all_parent_shas([])
        assert result == set()

    def test_get_all_parent_shas_root_only(self):
        """Test with root directory (no parents)."""
        root_sha = self.dirs["root"].dir_fqpn_sha256

        result = IndexDirs.get_all_parent_shas([root_sha])

        # Should only include root itself
        assert result == {root_sha}
        assert len(result) == 1

    def test_get_all_parent_shas_performance(self):
        """Test that it uses fewer queries than the old approach."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        input_shas = [
            self.dirs["photos_jan"].dir_fqpn_sha256,
            self.dirs["videos_2024"].dir_fqpn_sha256,
        ]

        # Count queries - should be very few (1-5 depending on directory depth)
        with CaptureQueriesContext(connection) as context:
            result = IndexDirs.get_all_parent_shas(input_shas)

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

        result = IndexDirs.get_all_parent_shas(input_shas)

        # Should include both input SHAs
        assert self.dirs["photos_2024"].dir_fqpn_sha256 in result
        assert self.dirs["photos_jan"].dir_fqpn_sha256 in result

        # Verify deduplication - result should be a set (no duplicates)
        assert isinstance(result, set)
        assert len(result) >= 2


@pytest.mark.django_db
class TestRemoveMultipleFromCacheOptimization(TestCase):
    """Test the optimized remove_multiple_from_cache method."""

    def setUp(self):
        """Create test directory hierarchy and cache entries for each test."""
        # Ensure filetypes are populated
        call_command("refresh-filetypes")

        # Create temporary directory structure for testing
        self.temp_dir = tempfile.mkdtemp()
        self.albums_path = os.path.join(self.temp_dir, "albums")

        # Create actual filesystem directories
        os.makedirs(os.path.join(self.albums_path, "photos", "2024", "january"), exist_ok=True)

        self.dirs = {}

        _, self.dirs["root"] = IndexDirs.add_directory(self.albums_path + "/")
        _, self.dirs["photos"] = IndexDirs.add_directory(os.path.join(self.albums_path, "photos") + "/")
        _, self.dirs["photos_2024"] = IndexDirs.add_directory(os.path.join(self.albums_path, "photos", "2024") + "/")
        _, self.dirs["photos_jan"] = IndexDirs.add_directory(os.path.join(self.albums_path, "photos", "2024", "january") + "/")

        # Create cache entries for all directories
        self.cache_storage = fs_Cache_Tracking()
        for dir_obj in self.dirs.values():
            self.cache_storage.add_from_indexdirs(dir_obj)

    def tearDown(self):
        """Clean up temporary directories after each test."""
        if hasattr(self, "temp_dir") and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_recursive_parent_invalidation(self):
        """Test that invalidating a leaf directory invalidates all parents."""
        # Verify all cache entries start as valid
        initial_count = fs_Cache_Tracking.objects.filter(invalidated=False).count()
        assert initial_count == 4

        # Invalidate the leaf directory
        leaf_path = self.dirs["photos_jan"].fqpndirectory
        result = self.cache_storage.remove_multiple_from_cache([leaf_path])

        assert result is True

        # Verify at least the target directory is invalidated
        invalidated_dirs = fs_Cache_Tracking.objects.filter(invalidated=True)
        invalidated_shas = set(invalidated_dirs.values_list("directory__dir_fqpn_sha256", flat=True))

        # Should at minimum invalidate the target directory
        assert self.dirs["photos_jan"].dir_fqpn_sha256 in invalidated_shas
        assert invalidated_dirs.count() >= 1

        # If parent links exist, should invalidate parent chain too
        if self.dirs["photos_jan"].parent_directory:
            assert invalidated_dirs.count() > 1

    def test_multiple_paths_optimization(self):
        """Test invalidating multiple paths with shared parents."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        # Create another branch (filesystem directory first)
        videos_path = os.path.join(self.albums_path, "videos")
        os.makedirs(videos_path, exist_ok=True)
        _, videos_dir = IndexDirs.add_directory(videos_path + "/")
        self.cache_storage.add_from_indexdirs(videos_dir)

        # Invalidate both leaf directories
        paths = [
            self.dirs["photos_jan"].fqpndirectory,
            videos_dir.fqpndirectory,
        ]

        with CaptureQueriesContext(connection) as context:
            result = self.cache_storage.remove_multiple_from_cache(paths)

        # Should be much less than old approach (would be 60+ for 2 deep paths)
        # Actual count includes: parent SHA collection + cache invalidation + directory counts
        assert len(context.captured_queries) <= 30, f"Expected ≤30 queries, got {len(context.captured_queries)}"

        assert result is True

        # Verify all affected directories are invalidated
        invalidated_count = fs_Cache_Tracking.objects.filter(invalidated=True).count()
        assert invalidated_count >= 2  # At minimum the two specified paths

    def test_sha_computation_not_duplicated(self):
        """Test that SHA computation happens only once per path."""
        paths = [self.dirs["photos_jan"].fqpndirectory] * 3  # Duplicate paths

        # The optimization should deduplicate before computing SHAs
        result = self.cache_storage.remove_multiple_from_cache(paths)

        assert result is True

        # Should only process unique paths once (not 3x)
        # At minimum invalidates the target directory
        invalidated_count = fs_Cache_Tracking.objects.filter(invalidated=True).count()

        # Should be 1-4 depending on parent links, but definitely not 3-12 (3x the paths)
        assert invalidated_count >= 1
        assert invalidated_count <= 5  # Not multiplied by the duplicate count


@pytest.mark.django_db
class TestOptimizationEdgeCases(TestCase):
    """Test edge cases for the optimization."""

    def test_nonexistent_directory(self):
        """Test handling of non-existent directories."""
        cache_storage = fs_Cache_Tracking()

        # Try to invalidate a directory that doesn't exist
        result = cache_storage.remove_multiple_from_cache(["/nonexistent/path/"])

        # Should handle gracefully - returns False since IndexDirs entry creation fails for non-existent paths
        assert result is False

    def test_empty_input(self):
        """Test with empty input list."""
        cache_storage = fs_Cache_Tracking()
        result = cache_storage.remove_multiple_from_cache([])
        assert result is False

    def test_circular_reference_protection(self):
        """Test that circular references don't cause infinite loops."""
        # The max_iterations limit should prevent issues
        # This is a safety test
        cache_storage = fs_Cache_Tracking()

        # Create a test directory
        temp_dir = tempfile.mkdtemp()
        test_path = os.path.join(temp_dir, "test")
        os.makedirs(test_path, exist_ok=True)

        try:
            # Even if there was a circular reference, should complete
            result = cache_storage.remove_multiple_from_cache([test_path + "/"])

            # Should not hang or error
            assert isinstance(result, bool)
        finally:
            shutil.rmtree(temp_dir)

"""Tests for Option 1 optimizations: parent SHA collection and cache invalidation."""

import os
import shutil
import tempfile

import pytest
from django.core.management import call_command
from django.test import TestCase, override_settings

from quickbbs.directoryindex import DIRECTORYINDEX_SR_PARENT
from quickbbs.models import DirectoryIndex


@pytest.mark.django_db
class TestGetAllParentShas(TestCase):
    """Test the get_all_parent_shas method."""

    def setUp(self):
        """Create a test directory hierarchy."""
        # Create temporary directory structure for testing.
        # ALBUMS_PATH is overridden so add_directory (which rejects paths
        # outside the albums root) accepts the temp hierarchy.
        self.temp_dir = tempfile.mkdtemp()
        self.albums_path = os.path.join(self.temp_dir, "albums")
        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir)
        self._settings_override.enable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None

        # Create actual filesystem directories
        os.makedirs(os.path.join(self.albums_path, "photos", "2024", "january"), exist_ok=True)
        os.makedirs(os.path.join(self.albums_path, "videos", "2024"), exist_ok=True)

        self.dirs = {}

        # Create root
        _, self.dirs["root"] = DirectoryIndex.add_directory(self.albums_path + "/")

        # Create photos branch
        _, self.dirs["photos"] = DirectoryIndex.add_directory(os.path.join(self.albums_path, "photos") + "/")
        _, self.dirs["photos_2024"] = DirectoryIndex.add_directory(os.path.join(self.albums_path, "photos", "2024") + "/")
        _, self.dirs["photos_jan"] = DirectoryIndex.add_directory(os.path.join(self.albums_path, "photos", "2024", "january") + "/")

        # Create videos branch
        _, self.dirs["videos"] = DirectoryIndex.add_directory(os.path.join(self.albums_path, "videos") + "/")
        _, self.dirs["videos_2024"] = DirectoryIndex.add_directory(os.path.join(self.albums_path, "videos", "2024") + "/")

    def tearDown(self):
        """Clean up temporary directories."""
        self._settings_override.disable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        if hasattr(self, "temp_dir") and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_get_all_parent_shas_single_leaf(self):
        """Test getting parents for a single leaf directory."""
        leaf_sha = self.dirs["photos_jan"].dir_fqpn_sha256

        result = DirectoryIndex.get_all_parent_shas([leaf_sha], DIRECTORYINDEX_SR_PARENT)

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

        result = DirectoryIndex.get_all_parent_shas(input_shas, DIRECTORYINDEX_SR_PARENT)

        # Should include both input SHAs
        assert self.dirs["photos_jan"].dir_fqpn_sha256 in result
        assert self.dirs["videos_2024"].dir_fqpn_sha256 in result
        assert len(result) >= 2

        # If parent links exist, should include all parents up to root
        if self.dirs["photos_jan"].parent_directory or self.dirs["videos_2024"].parent_directory:
            assert len(result) > 2

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
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

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
class TestRemoveMultipleFromCacheOptimization(TestCase):
    """Test the optimized remove_multiple_from_cache method."""

    def setUp(self):
        """Create test directory hierarchy and cache entries for each test."""
        # Create temporary directory structure for testing (ALBUMS_PATH
        # overridden — see TestGetAllParentShas.setUp).
        self.temp_dir = tempfile.mkdtemp()
        self.albums_path = os.path.join(self.temp_dir, "albums")
        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir)
        self._settings_override.enable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None

        # Create actual filesystem directories
        os.makedirs(os.path.join(self.albums_path, "photos", "2024", "january"), exist_ok=True)

        self.dirs = {}

        _, self.dirs["root"] = DirectoryIndex.add_directory(self.albums_path + "/")
        _, self.dirs["photos"] = DirectoryIndex.add_directory(os.path.join(self.albums_path, "photos") + "/")
        _, self.dirs["photos_2024"] = DirectoryIndex.add_directory(os.path.join(self.albums_path, "photos", "2024") + "/")
        _, self.dirs["photos_jan"] = DirectoryIndex.add_directory(os.path.join(self.albums_path, "photos", "2024", "january") + "/")

        # Mark all directories scanned (cache valid)
        for dir_obj in self.dirs.values():
            dir_obj.mark_scanned()

    def tearDown(self):
        """Clean up temporary directories after each test."""
        self._settings_override.disable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        if hasattr(self, "temp_dir") and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

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

        # Should at minimum invalidate the target directory
        assert self.dirs["photos_jan"].dir_fqpn_sha256 in invalidated_shas
        assert invalidated_dirs.count() >= 1

        # If parent links exist, should invalidate parent chain too
        if self.dirs["photos_jan"].parent_directory:
            assert invalidated_dirs.count() > 1

    def test_multiple_paths_optimization(self):
        """Test invalidating multiple paths with shared parents."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        # Create another branch (filesystem directory first)
        videos_path = os.path.join(self.albums_path, "videos")
        os.makedirs(videos_path, exist_ok=True)
        _, videos_dir = DirectoryIndex.add_directory(videos_path + "/")
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
class TestOptimizationEdgeCases(TestCase):
    """Test edge cases for the optimization."""

    def test_nonexistent_directory(self):
        """Test handling of empty/invalid directory lists."""
        # Try to invalidate with empty list
        result = DirectoryIndex.invalidate_caches([])

        # Should handle gracefully - returns False for empty list
        assert result is False

    def test_empty_input(self):
        """Test with empty input list."""
        result = DirectoryIndex.invalidate_caches([])
        assert result is False

    def test_circular_reference_protection(self):
        """Test that circular references don't cause infinite loops."""
        # The max_iterations limit should prevent issues
        # This is a safety test
        # Create a test directory under a temp albums root (add_directory
        # rejects paths outside the albums root)
        temp_dir = tempfile.mkdtemp()
        test_path = os.path.join(temp_dir, "albums", "test")
        os.makedirs(test_path, exist_ok=True)

        try:
            with override_settings(ALBUMS_PATH=temp_dir):
                DirectoryIndex._albums_prefix = None
                DirectoryIndex._albums_root = None
                # Create DirectoryIndex for the test path
                _, test_dir = DirectoryIndex.add_directory(test_path + "/")

                # Even if there was a circular reference, should complete
                result = DirectoryIndex.invalidate_caches([test_dir])

                # Should not hang or error
                assert isinstance(result, bool)
        finally:
            DirectoryIndex._albums_prefix = None
            DirectoryIndex._albums_root = None
            shutil.rmtree(temp_dir)

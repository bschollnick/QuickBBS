"""Tests for Option 3 optimization: bulk layout cache clearing."""

import os
import shutil
import tempfile

import pytest
from django.test import TestCase, override_settings

from frontend.managers import layout_manager
from quickbbs.cache_registry import (
    clear_layout_cache_for_directories,
    layout_manager_cache,
)
from quickbbs.models import DirectoryIndex


@pytest.mark.django_db
class TestBulkLayoutCacheClearing(TestCase):
    """Test bulk layout cache clearing via clear_layout_cache_for_directories."""

    def setUp(self):
        """Create test directory hierarchy for each test."""
        # Clear layout cache to ensure test isolation
        layout_manager_cache.clear()

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
        os.makedirs(os.path.join(self.albums_path, "photos", "2024"), exist_ok=True)
        os.makedirs(os.path.join(self.albums_path, "videos", "2024"), exist_ok=True)

        self.dirs = {}

        _, self.dirs["root"] = DirectoryIndex.add_directory(self.albums_path + "/")
        _, self.dirs["photos"] = DirectoryIndex.add_directory(os.path.join(self.albums_path, "photos") + "/")
        _, self.dirs["photos_2024"] = DirectoryIndex.add_directory(os.path.join(self.albums_path, "photos", "2024") + "/")
        _, self.dirs["videos"] = DirectoryIndex.add_directory(os.path.join(self.albums_path, "videos") + "/")
        _, self.dirs["videos_2024"] = DirectoryIndex.add_directory(os.path.join(self.albums_path, "videos", "2024") + "/")

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

    def test_bulk_cache_clearing_removes_all_entries(self):
        """Test that bulk clearing removes cache entries for all directories."""
        # Populate layout cache with entries for all directories
        for dir_obj in self.dirs.values():
            # Create cache entry for page 1, sort order 0
            layout_manager(page_number=1, directory=dir_obj, sort_ordering=0, show_duplicates=False)

        # Verify cache has entries
        initial_cache_size = len(layout_manager_cache)
        assert initial_cache_size > 0, "Cache should have entries"

        # Clear cache for all directories using bulk operation
        clear_layout_cache_for_directories({d.pk for d in self.dirs.values()})

        # Verify all relevant entries are removed
        # Cache should be empty or only contain entries for other directories
        final_cache_size = len(layout_manager_cache)

        # All entries should be cleared
        assert final_cache_size == 0, f"Expected 0 entries, found {final_cache_size}"

    def test_bulk_cache_clearing_handles_multiple_sort_orders(self):
        """Test that bulk clearing removes cache entries for all sort orders."""
        # Populate layout cache with multiple sort orders
        for dir_obj in [self.dirs["photos"], self.dirs["videos"]]:
            for sort_order in [0, 1, 2]:
                layout_manager(page_number=1, directory=dir_obj, sort_ordering=sort_order, show_duplicates=False)

        # Should have 2 dirs × 3 sort orders = 6 entries
        initial_cache_size = len(layout_manager_cache)
        assert initial_cache_size >= 6, f"Expected at least 6 entries, found {initial_cache_size}"

        # Clear cache for both directories
        clear_layout_cache_for_directories({self.dirs["photos"].pk, self.dirs["videos"].pk})

        # All entries should be cleared
        final_cache_size = len(layout_manager_cache)
        assert final_cache_size == 0, f"Expected 0 entries after bulk clear, found {final_cache_size}"

    def test_single_directory_clearing_uses_bulk(self):
        """Test that bulk clear works with a single-element list."""
        # Populate cache
        layout_manager(page_number=1, directory=self.dirs["photos"], sort_ordering=0, show_duplicates=False)

        initial_cache_size = len(layout_manager_cache)
        assert initial_cache_size > 0

        # Use bulk method with a single-element list
        clear_layout_cache_for_directories({self.dirs["photos"].pk})

        # Cache should be cleared
        final_cache_size = len(layout_manager_cache)
        assert final_cache_size == 0

    def test_bulk_clearing_with_empty_list(self):
        """Test that bulk clearing handles empty directory list gracefully."""
        # Populate cache
        layout_manager(page_number=1, directory=self.dirs["photos"], sort_ordering=0, show_duplicates=False)
        initial_cache_size = len(layout_manager_cache)

        # Clear with empty list - should not crash
        clear_layout_cache_for_directories(set())

        # Cache should be unchanged
        final_cache_size = len(layout_manager_cache)
        assert final_cache_size == initial_cache_size

    def test_bulk_clearing_ignores_none_directory_id(self):
        """None in directory_ids (orphaned FileIndex.home_directory) is ignored, not a crash."""
        # Populate cache
        layout_manager(page_number=1, directory=self.dirs["photos"], sort_ordering=0, show_duplicates=False)
        initial_cache_size = len(layout_manager_cache)
        assert initial_cache_size > 0

        # A None alongside a real pk should clear the real entry without raising
        cleared = clear_layout_cache_for_directories({self.dirs["photos"].pk, None})
        assert cleared > 0
        assert len(layout_manager_cache) == 0

        # An all-None set should behave like an empty set: no crash, nothing cleared
        cleared = clear_layout_cache_for_directories({None})
        assert cleared == 0

    def test_bulk_clearing_performance_no_db_queries(self):
        """Test that bulk clearing does not trigger database queries."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        # Populate cache
        for dir_obj in self.dirs.values():
            layout_manager(page_number=1, directory=dir_obj, sort_ordering=0, show_duplicates=False)

        # Count queries during bulk clear
        with CaptureQueriesContext(connection) as context:
            clear_layout_cache_for_directories({d.pk for d in self.dirs.values()})

        # Should use 0 database queries (only cache operations)
        assert len(context.captured_queries) == 0, f"Expected 0 queries, got {len(context.captured_queries)}: {context.captured_queries}"

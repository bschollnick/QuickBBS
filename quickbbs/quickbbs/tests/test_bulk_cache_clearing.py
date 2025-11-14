"""Tests for Option 3 optimization: bulk layout cache clearing."""

import os
import tempfile
import shutil
import pytest
from django.test import TestCase
from django.core.management import call_command

from quickbbs.models import IndexDirs
from cache_watcher.models import fs_Cache_Tracking
from frontend.managers import layout_manager, layout_manager_cache


@pytest.fixture(scope="session", autouse=True)
def django_db_setup(django_db_setup, django_db_blocker):
    """Ensure filetypes table is populated before running tests."""
    with django_db_blocker.unblock():
        call_command("refresh-filetypes")


@pytest.mark.django_db
class TestBulkLayoutCacheClearing(TestCase):
    """Test the optimized _clear_layout_cache_bulk method."""

    def setUp(self):
        """Create test directory hierarchy for each test."""
        # Ensure filetypes are populated
        call_command("refresh-filetypes")

        # Clear layout cache to ensure test isolation
        layout_manager_cache.clear()

        # Create temporary directory structure for testing
        self.temp_dir = tempfile.mkdtemp()
        self.albums_path = os.path.join(self.temp_dir, "albums")

        # Create actual filesystem directories
        os.makedirs(os.path.join(self.albums_path, "photos", "2024"), exist_ok=True)
        os.makedirs(os.path.join(self.albums_path, "videos", "2024"), exist_ok=True)

        self.dirs = {}

        _, self.dirs["root"] = IndexDirs.add_directory(self.albums_path + "/")
        _, self.dirs["photos"] = IndexDirs.add_directory(os.path.join(self.albums_path, "photos") + "/")
        _, self.dirs["photos_2024"] = IndexDirs.add_directory(os.path.join(self.albums_path, "photos", "2024") + "/")
        _, self.dirs["videos"] = IndexDirs.add_directory(os.path.join(self.albums_path, "videos") + "/")
        _, self.dirs["videos_2024"] = IndexDirs.add_directory(os.path.join(self.albums_path, "videos", "2024") + "/")

        # Create cache entries
        self.cache_storage = fs_Cache_Tracking()
        for dir_obj in self.dirs.values():
            self.cache_storage.add_from_indexdirs(dir_obj)

    def tearDown(self):
        """Clean up temporary directories after each test."""
        if hasattr(self, "temp_dir") and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_bulk_cache_clearing_removes_all_entries(self):
        """Test that bulk clearing removes cache entries for all directories."""
        # Populate layout cache with entries for all directories
        for dir_obj in self.dirs.values():
            # Create cache entry for page 1, sort order 0
            layout_manager(page_number=1, directory=dir_obj, sort_ordering=0)

        # Verify cache has entries
        initial_cache_size = len(layout_manager_cache)
        assert initial_cache_size > 0, "Cache should have entries"

        # Clear cache for all directories using bulk operation
        self.cache_storage._clear_layout_cache_bulk(list(self.dirs.values()))

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
                layout_manager(page_number=1, directory=dir_obj, sort_ordering=sort_order)

        # Should have 2 dirs × 3 sort orders = 6 entries
        initial_cache_size = len(layout_manager_cache)
        assert initial_cache_size >= 6, f"Expected at least 6 entries, found {initial_cache_size}"

        # Clear cache for both directories
        self.cache_storage._clear_layout_cache_bulk([self.dirs["photos"], self.dirs["videos"]])

        # All entries should be cleared
        final_cache_size = len(layout_manager_cache)
        assert final_cache_size == 0, f"Expected 0 entries after bulk clear, found {final_cache_size}"

    def test_single_directory_clearing_uses_bulk(self):
        """Test that _clear_layout_cache (single) delegates to bulk method."""
        # Populate cache
        layout_manager(page_number=1, directory=self.dirs["photos"], sort_ordering=0)

        initial_cache_size = len(layout_manager_cache)
        assert initial_cache_size > 0

        # Use single-directory method (should delegate to bulk)
        self.cache_storage._clear_layout_cache(self.dirs["photos"])

        # Cache should be cleared
        final_cache_size = len(layout_manager_cache)
        assert final_cache_size == 0

    def test_bulk_clearing_with_empty_list(self):
        """Test that bulk clearing handles empty directory list gracefully."""
        # Populate cache
        layout_manager(page_number=1, directory=self.dirs["photos"], sort_ordering=0)
        initial_cache_size = len(layout_manager_cache)

        # Clear with empty list - should not crash
        self.cache_storage._clear_layout_cache_bulk([])

        # Cache should be unchanged
        final_cache_size = len(layout_manager_cache)
        assert final_cache_size == initial_cache_size

    def test_bulk_clearing_performance_no_db_queries(self):
        """Test that bulk clearing does not trigger database queries."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        # Populate cache
        for dir_obj in self.dirs.values():
            layout_manager(page_number=1, directory=dir_obj, sort_ordering=0)

        # Count queries during bulk clear
        with CaptureQueriesContext(connection) as context:
            self.cache_storage._clear_layout_cache_bulk(list(self.dirs.values()))

        # Should use 0 database queries (only cache operations)
        assert len(context.captured_queries) == 0, f"Expected 0 queries, got {len(context.captured_queries)}: {context.captured_queries}"

"""Tests for Option 3 optimization: bulk layout cache clearing."""

import pytest

from frontend.managers import layout_manager
from quickbbs.cache_registry import (
    clear_layout_cache_for_directories,
    layout_manager_cache,
)
from quickbbs.tests.albums_root import AlbumsRootTestCase

pytestmark = pytest.mark.api


@pytest.mark.django_db
class TestBulkLayoutCacheClearing(AlbumsRootTestCase):
    """Test bulk layout cache clearing via clear_layout_cache_for_directories."""

    def setUp(self):
        """Create test directory hierarchy for each test."""
        super().setUp()
        # Clear layout cache to ensure test isolation
        layout_manager_cache.clear()
        self.dirs = {
            "root": self.add_directory(),
            "photos": self.add_directory("photos"),
            "photos_2024": self.add_directory("photos", "2024"),
            "videos": self.add_directory("videos"),
            "videos_2024": self.add_directory("videos", "2024"),
        }
        # Mark all directories scanned (cache valid)
        for dir_obj in self.dirs.values():
            dir_obj.mark_scanned()

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

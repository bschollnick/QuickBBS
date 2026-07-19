"""
Tests for frontend/managers.py pagination: calculate_page_bounds() (pure math)
and layout_manager() (DB-backed page layout).

DATABASE SAFETY NOTES
---------------------
- calculate_page_bounds tests use SimpleTestCase — no DB access at all.
- layout_manager tests use Django's TestCase (per-test rolled-back
  transaction). No TransactionTestCase is used — ever.
- Filesystem content is created in tempfile.mkdtemp() with ALBUMS_PATH
  overridden; tearDown removes only the temp directory.
"""

from __future__ import annotations

import os

from django.test import SimpleTestCase, override_settings

from frontend.managers import calculate_page_bounds, layout_manager
from quickbbs.cache_registry import layout_manager_cache
from quickbbs.models import DirectoryIndex
from quickbbs.tests.test_sync import SyncTestBase


class TestCalculatePageBounds(SimpleTestCase):
    """Pure pagination math — directories fill pages before files."""

    def test_first_page_all_directories(self):
        """When dirs outnumber the chunk, page 1 is directories only."""
        bounds = calculate_page_bounds(page_number=1, chunk_size=10, dirs_count=25)
        assert bounds["dirs_slice"] == (0, 10)
        assert bounds["files_slice"] is None
        assert bounds["dirs_on_page"] == 10

    def test_mixed_page_dirs_then_files(self):
        """A page straddling the dir/file boundary allots remaining space to files."""
        bounds = calculate_page_bounds(page_number=1, chunk_size=10, dirs_count=4)
        assert bounds["dirs_slice"] == (0, 4)
        assert bounds["files_slice"] == (0, 6)
        assert bounds["dirs_on_page"] == 4

    def test_later_page_all_files(self):
        """Pages past the directory range are files only, offset by dirs_count."""
        bounds = calculate_page_bounds(page_number=3, chunk_size=10, dirs_count=4)
        # start_idx = 20 → files_start = 20 - 4 = 16
        assert bounds["dirs_slice"] is None
        assert bounds["dirs_on_page"] == 0
        assert bounds["files_slice"] == (16, 26)

    def test_exact_boundary_page_starts_with_files(self):
        """A page starting exactly at dirs_count contains no directories."""
        bounds = calculate_page_bounds(page_number=2, chunk_size=10, dirs_count=10)
        assert bounds["dirs_slice"] is None
        assert bounds["files_slice"] == (0, 10)

    def test_no_directories_at_all(self):
        """With zero directories, page 1 is pure files from index 0."""
        bounds = calculate_page_bounds(page_number=1, chunk_size=10, dirs_count=0)
        assert bounds["dirs_slice"] is None
        assert bounds["files_slice"] == (0, 10)


class TestLayoutManager(SyncTestBase):
    """layout_manager against a real synced directory tree."""

    def setUp(self) -> None:
        super().setUp()
        layout_manager_cache.clear()
        # 2 subdirectories + 3 files in the albums root.
        for sub in ("sub_a", "sub_b"):
            os.makedirs(os.path.join(self.albums_dir, sub))
        # Distinct content per file — show_duplicates=False deduplicates by
        # file SHA, so identical bytes would collapse into one entry.
        for name in ("one.txt", "two.txt", "three.txt"):
            self.write_file(name, content=name.encode())
        self.sync()
        self.dir_obj.refresh_from_db()

    def tearDown(self) -> None:
        layout_manager_cache.clear()
        super().tearDown()

    def test_requires_directory(self):
        """layout_manager without a directory raises ValueError."""
        try:
            layout_manager(page_number=1, directory=None, sort_ordering=0, show_duplicates=False)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    @override_settings(GALLERY_ITEMS_PER_PAGE=4)
    def test_page_one_dirs_before_files(self):
        """Page 1 holds both directories, then files up to the page size."""
        layout = layout_manager(page_number=1, directory=self.dir_obj, sort_ordering=0, show_duplicates=False)
        assert layout["total_pages"] == 2  # 5 items / 4 per page
        assert layout["page_items"]["dir_count"] == 2
        assert layout["page_items"]["file_count"] == 2

    @override_settings(GALLERY_ITEMS_PER_PAGE=4)
    def test_page_two_remaining_files(self):
        """Page 2 holds the remaining file and no directories."""
        layout = layout_manager(page_number=2, directory=self.dir_obj, sort_ordering=0, show_duplicates=False)
        assert layout["page_items"]["dir_count"] == 0
        assert layout["page_items"]["file_count"] == 1

    @override_settings(GALLERY_ITEMS_PER_PAGE=4)
    def test_pages_partition_items_without_overlap(self):
        """Every item appears exactly once across all pages."""
        seen_dirs: list[str] = []
        seen_files: list[str] = []
        layout = layout_manager(page_number=1, directory=self.dir_obj, sort_ordering=0, show_duplicates=False)
        for page in range(1, layout["total_pages"] + 1):
            page_layout = layout_manager(page_number=page, directory=self.dir_obj, sort_ordering=0, show_duplicates=False)
            seen_dirs.extend(page_layout["page_items"]["directory_shas"])
            seen_files.extend(page_layout["page_items"]["file_shas"])
        assert len(seen_dirs) == len(set(seen_dirs)) == 2
        assert len(seen_files) == len(set(seen_files)) == 3

    def test_empty_directory_has_one_page(self):
        """An empty directory still reports a single (empty) page."""
        empty_path = os.path.join(self.albums_dir, "sub_a")
        _, empty_rec = DirectoryIndex.add_directory(empty_path + "/")
        self.sync(empty_rec)
        empty_rec.refresh_from_db()
        layout = layout_manager(page_number=1, directory=empty_rec, sort_ordering=0, show_duplicates=False)
        assert layout["total_pages"] == 1
        assert layout["page_items"]["dir_count"] == 0
        assert layout["page_items"]["file_count"] == 0

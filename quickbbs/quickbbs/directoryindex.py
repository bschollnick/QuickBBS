"""
DirectoryIndex Model - Master index for directories in the filesystem
"""

from __future__ import annotations

# Direct imports (replacing re-exports from .models)
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from asgiref.sync import sync_to_async
from cachetools import cached
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction
from django.db.models import Count, Q
from django.db.models.query import QuerySet
from django.urls import reverse

from filetypes.models import filetypes, get_ftype_dict
from quickbbs.common import (
    SORT_MATRIX,
    get_dir_sha,
    normalize_fqpn,
    normalize_string_title,
)
from quickbbs.natsort_model import NaturalSortField

# Items defined in models.py (must stay)
from .models import directoryindex_cache, distinct_files_cache

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cache_watcher.models import fs_Cache_Tracking

    from .fileindex import FileIndex

from .fileindex import FILEINDEX_SR_FILETYPE

# =============================================================================
# DIRECTORYINDEX SELECT_RELATED CONSTANTS
# Colocated with DirectoryIndex class for use by class methods and external callers
# See related_fetches.md for usage details
# NOTE: Using tuples (not lists) so they can be used as cache keys (hashable)
# =============================================================================

# Full - gallery with navigation
DIRECTORYINDEX_SR_FILETYPE_THUMB_CACHE_PARENT = ("filetype", "thumbnail", "Cache_Watcher", "parent_directory")

# For thumbnail view (no navigation needed)
DIRECTORYINDEX_SR_FILETYPE_THUMB_CACHE = ("filetype", "thumbnail", "Cache_Watcher")

# For directory listing display
DIRECTORYINDEX_SR_FILETYPE_THUMB = ("filetype", "thumbnail")

# For directory listing with navigation
DIRECTORYINDEX_SR_FILETYPE_THUMB_PARENT = ("filetype", "thumbnail", "parent_directory")

# For management commands
DIRECTORYINDEX_SR_CACHE = ("Cache_Watcher",)

# For parent navigation only
DIRECTORYINDEX_SR_PARENT = ("parent_directory",)


class DirectoryIndex(models.Model):
    """
    The master index for Directory / Folders in the Filesystem for the gallery.
    """

    _albums_prefix = None
    _albums_root = None

    @classmethod
    def get_albums_prefix(cls) -> str:
        """Cache the albums path prefix for optimization"""
        if cls._albums_prefix is None:
            cls._albums_prefix = settings.ALBUMS_PATH.lower() + r"/albums/"
        return cls._albums_prefix

    @classmethod
    def get_albums_root(cls) -> str:
        """Cache the albums root path for optimization"""
        if cls._albums_root is None:
            cls._albums_root = normalize_fqpn(os.path.join(settings.ALBUMS_PATH, "albums"))
        return cls._albums_root

    fqpndirectory = models.CharField(db_index=True, max_length=384, default="", unique=True, blank=True)  # True fqpn name

    dir_fqpn_sha256 = models.CharField(
        blank=True,
        unique=True,
        null=True,
        default=None,
        max_length=64,
    )  # sha of the directory fqpn (unique=True creates index; also in Meta composite index)

    parent_directory = models.ForeignKey(
        "self",
        db_index=True,
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        related_name="parent_dir",
    )
    lastscan = models.FloatField(db_index=True, default=None)  # Stored as Unix TimeStamp (ms)
    lastmod = models.FloatField(db_index=True, default=None)  # Stored as Unix TimeStamp (ms)
    name_sort = NaturalSortField(for_field="fqpndirectory", max_length=384, default="")
    is_generic_icon = models.BooleanField(default=False)  # File is to be ignored
    delete_pending = models.BooleanField(default=False, db_index=True)  # File is to be deleted,
    filetype = models.ForeignKey(
        filetypes,
        to_field="fileext",
        on_delete=models.CASCADE,
        db_index=True,
        default=".dir",
        related_name="dirs_filetype_data",
    )
    thumbnail = models.ForeignKey(
        "FileIndex",
        on_delete=models.SET_NULL,
        related_name="dir_thumbnail",
        null=True,
        default=None,
    )
    file_links = models.ManyToManyField(
        "FileIndex",
        default=None,
        related_name="file_links",
    )

    # Reverse relationships
    # From fs_Cache_Tracking.directory
    Cache_Watcher: "models.OneToOneRel[fs_Cache_Tracking]"  # type: ignore[valid-type]
    # From DirectoryIndex.parent_directory (self-referential)
    parent_dir: "models.manager.RelatedManager[DirectoryIndex]"
    # From FileIndex.home_directory
    FileIndex_entries: "models.manager.RelatedManager[FileIndex]"
    # From FileIndex.virtual_directory
    Virtual_FileIndex: "models.manager.RelatedManager[FileIndex]"

    class Meta:
        db_table = "quickbbs_directoryindex"
        verbose_name = "Master Directory Index"
        verbose_name_plural = "Master Directory Index"
        indexes = [
            models.Index(fields=["parent_directory", "delete_pending"]),
            models.Index(fields=["dir_fqpn_sha256", "delete_pending"]),
        ]

    @staticmethod
    def add_directory(fqpn_directory: str, thumbnail: bytes = b"") -> tuple[bool, "DirectoryIndex"]:  # pylint: disable=unused-argument
        """
        Create a new directory entry or get existing one

        Args:
            fqpn_directory: The fully qualified pathname for the directory
            thumbnail: thumbnail image to store for the thumbnail/cover art (currently unused)

        Returns:
            Database record
        """
        # Normalize once and compute SHA once
        fqpn_directory = normalize_fqpn(fqpn_directory)
        dir_sha256 = get_dir_sha(fqpn_directory)

        # Cache the albums path check
        albums_path_lower = os.path.join(settings.ALBUMS_PATH, "albums").lower()
        albums_root = DirectoryIndex.get_albums_root()
        is_in_albums = fqpn_directory.lower().startswith(albums_path_lower)

        # Determine parent directory link
        if is_in_albums:
            # Check if this IS the albums root directory - it has no parent
            if fqpn_directory.lower() == albums_root.lower():
                parent_dir_link = None
            else:
                # Regular subdirectory - find or create parent
                parent_dir = normalize_fqpn(str(Path(fqpn_directory).parent))

                if parent_dir.lower().startswith(albums_path_lower):
                    # Recursively add/update parent to ensure proper parent_directory chain
                    # This fixes both missing parents AND parents with NULL parent_directory
                    parent_sha = get_dir_sha(parent_dir)
                    found, _ = DirectoryIndex.search_for_directory_by_sha(parent_sha, DIRECTORYINDEX_SR_CACHE, ())

                    if not found:
                        print(f"Creating parent directory: {parent_dir}")

                    # Always call add_directory to ensure parent has correct parent_directory link
                    # update_or_create will handle both new and existing records
                    _, parent_dir_link = DirectoryIndex.add_directory(parent_dir)
                else:
                    # Parent is outside albums path, don't link it
                    parent_dir_link = None
        else:
            parent_dir_link = None

        # Use single stat call for both exists check and mtime
        dir_path = Path(fqpn_directory)
        try:
            stat_info = dir_path.stat()
        except (FileNotFoundError, OSError):
            return (False, None)  # Return None when directory doesn't exist

        defaults = {
            "fqpndirectory": fqpn_directory,  # Already normalized
            "lastmod": stat_info.st_mtime,
            "lastscan": time.time(),
            "filetype": filetypes.return_filetype(fileext=".dir"),
            "dir_fqpn_sha256": dir_sha256,  # Already computed
            "parent_directory": parent_dir_link,
            "is_generic_icon": False,
            "thumbnail": None,
        }

        # Use get_or_create with fqpndirectory as the unique lookup field
        new_rec, created = DirectoryIndex.objects.update_or_create(
            dir_fqpn_sha256=defaults["dir_fqpn_sha256"],
            defaults=defaults,
            create_defaults=defaults,
        )
        found = not created
        return found, new_rec

    def invalidate_thumb(self) -> None:
        """
        Invalidate the thumbnail for the directory.  This is used when the directory
        is deleted, and the thumbnail is no longer valid.

        Uses QuerySet.update() for efficient database-level UPDATE without
        model serialization overhead.

        Returns:
            None
        """
        DirectoryIndex.objects.filter(pk=self.pk).update(thumbnail=None, is_generic_icon=False)
        # Refresh local instance to reflect DB state
        self.thumbnail = None
        self.is_generic_icon = False

        # Clear LRUCache entry for this directory to avoid serving stale cached data
        directoryindex_cache.pop(self.dir_fqpn_sha256, None)

    @property
    def virtual_directory(self) -> str:
        """
        Return the virtual directory name of the directory.
        This is used to return the directory name without the full path.

        Returns:
            String
        """
        return str(Path(self.fqpndirectory).name)

    @property
    def numdirs(self) -> None:
        """
        Stub property for template compatibility.

        Provides API compatibility between DirectoryIndex and FileIndex objects when used in
        Jinja2 templates. This allows templates to access .numdirs on either object type
        without checking the instance type first. FileIndex objects return actual directory
        counts, while this property returns None since directory objects don't track this metric.

        Returns:
            None
        """
        return None

    @property
    def numfiles(self) -> None:
        """
        Stub property for template compatibility.

        Provides API compatibility between DirectoryIndex and FileIndex objects when used in
        Jinja2 templates. This allows templates to access .numfiles on either object type
        without checking the instance type first. FileIndex objects return actual file
        counts, while this property returns None since directory objects don't track this metric.

        Returns:
            None
        """
        return None

    @property
    def name(self) -> str:
        """
        Return the directory name of the directory.

        Returns:
            String
        """
        return str(Path(self.fqpndirectory).name)

    @property
    def is_cached(self) -> bool:
        """
        Check if this directory has a valid cache entry.

        Uses the 1-to-1 relationship to fs_Cache_Tracking (Cache_Watcher)
        to efficiently determine cache status without additional queries.

        Returns:
            True if directory is cached and not invalidated, False otherwise
        """
        try:
            return not self.Cache_Watcher.invalidated
        except ObjectDoesNotExist:
            return False

    @staticmethod
    def get_all_parent_shas(sha_list: list[str], select_related: list[str]) -> set[str]:
        """
        Get all parent directory SHAs using optimized batch queries.

        Pure Django ORM with no external dependencies. Uses iterative batch fetching
        instead of recursive CTE, but still much more efficient than N*M approach.

        Args:
            sha_list: List of directory SHA256 hashes to find parents for
            select_related: List of related fields to select (required)

        Returns:
            Set containing all input SHAs plus all ancestor SHAs

        Performance:
            - Queries: O(D) where D = max directory depth (typically 5-10)
            - Old approach: O(N + N*M) where N = dirs, M = avg depth
            - Improvement: Batches all directories per level vs per-directory traversal

        Example:
            Input: ["sha_of_/albums/photos/2024", "sha_of_/albums/videos"]
            Output: {"sha_of_/", "sha_of_/albums", "sha_of_/albums/photos",
                     "sha_of_/albums/photos/2024", "sha_of_/albums/videos"}
        """
        if select_related is None:
            raise ValueError("select_related parameter is required")
        if not sha_list:
            return set()

        all_shas = set(sha_list)
        current_level_shas = set(sha_list)
        max_iterations = 15  # Prevent infinite loops (reasonable max directory depth, reduces memory amplification)

        for iteration in range(max_iterations):
            if not current_level_shas:
                break

            # Batch fetch ALL parents for current level in ONE query
            parents = (
                DirectoryIndex.objects.filter(
                    dir_fqpn_sha256__in=current_level_shas,
                    delete_pending=False,
                    parent_directory__isnull=False,
                )
                .select_related(*select_related)
                .values_list("parent_directory__dir_fqpn_sha256", flat=True)
            )

            # Get unique parent SHAs from this level (only new ones)
            parent_shas = set(parents) - all_shas

            if not parent_shas:
                break  # No more parents to traverse

            all_shas.update(parent_shas)
            current_level_shas = parent_shas  # Next iteration: process these parents

            logger.debug("Parent traversal iteration %d: found %d new parents", iteration + 1, len(parent_shas))

        return all_shas

    @staticmethod
    def delete_directory_record(index_dir: "DirectoryIndex", cache_only: bool = False) -> None:
        """
        Delete the Directory_Index record and ensure cache cleanup.

        Optimized version that accepts an DirectoryIndex record directly,
        avoiding redundant database lookups.

        Args:
            index_dir: DirectoryIndex instance to delete
            cache_only: If True, only clear cache, don't delete the record

        Returns:
            None
        """
        # Inline import to avoid circular dependency:
        # cache_watcher.models imports DirectoryIndex in multiple places
        # pylint: disable-next=import-outside-toplevel
        from cache_watcher.models import Cache_Storage

        if not index_dir:
            return

        # Use optimized cache removal
        Cache_Storage.remove_from_cache_indexdirs(index_dir)

        if not cache_only:
            # Delete the directory record (cascades to related records)
            index_dir.delete()

    @staticmethod
    def delete_directory(fqpn_directory: str, cache_only: bool = False) -> None:
        """
        Delete the Directory_Index data for the fqpn_directory, and ensure that all
        FileIndex records are wiped as well.

        Args:
            fqpn_directory: text string of fully qualified pathname of the directory
            cache_only: Do not perform a delete on the Directory_Index data

        Returns:
        """
        # Inline import to avoid circular dependency:
        # cache_watcher.models imports DirectoryIndex in multiple places
        # pylint: disable-next=import-outside-toplevel
        from cache_watcher.models import Cache_Storage

        dir_sha256 = get_dir_sha(normalize_fqpn(fqpn_directory))
        Cache_Storage.remove_from_cache_sha(dir_sha256)
        if not cache_only:
            DirectoryIndex.objects.filter(dir_fqpn_sha256=dir_sha256).delete()

    def do_files_exist(self, additional_filters: dict[str, Any] | None = None) -> bool:
        """
        Check if any files exist in the current directory with optional filters

        Args:
            additional_filters: Additional Django ORM filters to apply (e.g., filetype, status filters)

        Returns: Boolean indicating if files exist in the directory using QuerySet.exists()
        """
        additional_filters = additional_filters or {}
        return self.FileIndex_entries.filter(delete_pending=False, **additional_filters).exists()

    def get_file_counts(self) -> int:
        """
        Return the number of files that are in the database for the current directory
        Returns: Integer - Number of files in the database for the directory
        """
        return self.FileIndex_entries.filter(delete_pending=False).count()

    def get_dir_counts(self) -> int:
        """
        Return the number of directories that are in the database for the current directory
        Returns: Integer - Number of directories
        """
        return DirectoryIndex.objects.filter(parent_directory=self.pk, delete_pending=False).count()

    def get_count_breakdown(self) -> dict[str, int]:
        """
        Return the count of items in the directory, broken down by filetype.
        Returns: dictionary, where the key is the filetype (e.g. "dir", "jpg", "mp4"),
        and the value is the number of items of that filetype.
        A special "all_files" key is used to store the # of all items in the directory (except
        for directories).  (all_files is the sum of all file types, except "dir")
        """
        filetypes_dict = get_ftype_dict()

        # Single aggregate query for ALL file counts by type
        file_aggregates = self.FileIndex_entries.filter(delete_pending=False).aggregate(
            total_files=Count("id"),
            **{f"type_{ft[1:]}": Count("id", filter=Q(filetype__fileext=ft)) for ft in filetypes_dict.keys()},
        )

        # Directory count (separate table, still needs its own query)
        dir_count = DirectoryIndex.objects.filter(parent_directory=self.pk, delete_pending=False).count()

        # Build result dictionary from aggregates
        totals = {ft[1:]: file_aggregates.get(f"type_{ft[1:]}", 0) for ft in filetypes_dict.keys()}
        totals["dir"] = dir_count
        totals["all_files"] = file_aggregates["total_files"]

        return totals

    @cached(directoryindex_cache)
    @staticmethod
    def search_for_directory_by_sha(sha_256: str, select_related: list[str], prefetch_related: list[str]) -> tuple[bool, "DirectoryIndex"]:
        """
        Return the database object matching the dir_fqpn_sha256

        Args:
            sha_256: The SHA-256 hash of the directory's fully qualified pathname
            select_related: List of related fields to select (required)
            prefetch_related: List of related fields to prefetch (required)

        Returns: A boolean representing the success of the search, and the resultant record
        """
        if select_related is None:
            raise ValueError("select_related parameter is required")
        if prefetch_related is None:
            raise ValueError("prefetch_related parameter is required")

        try:
            record = (
                DirectoryIndex.objects.select_related(*select_related)
                .prefetch_related(*prefetch_related)
                .get(
                    dir_fqpn_sha256=sha_256,
                    delete_pending=False,
                )
            )
            return (True, record)
        except DirectoryIndex.DoesNotExist:
            return (False, None)  # Return None when not found

    @staticmethod
    def search_for_directory(fqpn_directory: str, select_related: list[str], prefetch_related: list[str]) -> tuple[bool, "DirectoryIndex"]:
        """
        Return the database object matching the fqpn_directory

        NOTE: This method is NOT cached. It delegates to search_for_directory_by_sha()
        which IS cached. Do NOT add @cached decorator here as it creates duplicate cache
        entries (one by path, one by SHA) that become inconsistent during invalidation.

        Args:
            fqpn_directory: The fully qualified pathname of the directory
            select_related: List of related fields to select (required)
            prefetch_related: List of related fields to prefetch (required)

        Returns: A boolean representing the success of the search, and the resultant record
        """
        if select_related is None:
            raise ValueError("select_related parameter is required")
        if prefetch_related is None:
            raise ValueError("prefetch_related parameter is required")
        sha_256 = get_dir_sha(fqpn_directory)
        return DirectoryIndex.search_for_directory_by_sha(sha_256, select_related, prefetch_related)

    @staticmethod
    def return_by_sha256_list(
        sha256_list: list[str], sort: int, select_related: list[str], prefetch_related: list[str]
    ) -> "QuerySet[DirectoryIndex]":
        """
        Return directories matching the provided SHA256 list

        Args:
            sha256_list: List of directory SHA256 hashes to filter by
            sort: The sort order of the dirs (0-2)
            select_related: List of related fields to select (required)
            prefetch_related: List of related fields to prefetch (required)

        Returns: The sorted query of directories matching the SHA256 list
        """
        if select_related is None:
            raise ValueError("select_related parameter is required")
        if prefetch_related is None:
            raise ValueError("prefetch_related parameter is required")
        dirs = (
            DirectoryIndex.objects.select_related(*select_related)
            .prefetch_related(*prefetch_related)
            .filter(dir_fqpn_sha256__in=sha256_list)
            .filter(delete_pending=False)
            .order_by(*SORT_MATRIX[sort])
        )
        return dirs

    def files_in_dir(
        self,
        sort: int = 0,
        distinct: bool = False,
        additional_filters: dict[str, Any] | None = None,
        fields_only: list[str] | None = None,
        select_related: list[str] | None = None,
    ) -> "QuerySet[FileIndex] | list[FileIndex]":
        """
        Return the files in the current directory

        Args:
            sort: The sort order of the files (0-2)
            distinct: If True, return distinct files based on file_sha256 (deduplicates identical files)
            additional_filters: Additional Django ORM filters to apply (e.g., filetype, status filters)
            fields_only: If provided, return lightweight query with only these fields.
                        With distinct=True: Only optimizes if sort doesn't require related fields.
                        Current sort modes (0-2) use filetype relations, so fall back to full query.
            select_related: List of related fields to select (required)

        Returns: QuerySet[FileIndex] when distinct=False, list[FileIndex] when distinct=True

        Note:
            When distinct=True, PostgreSQL DISTINCT ON requires file_sha256 to be the first
            ORDER BY field, which disrupts the user's intended sort order. This method
            re-sorts the results in Python to maintain the correct order while still
            benefiting from PostgreSQL's fast DISTINCT ON operation.

            Using fields_only significantly reduces memory usage (~60-70%) when full
            objects with related data aren't needed. Common use cases:
            - Getting file names for filesystem comparison
            - Building file lists with only specific attributes
            - Batch operations needing only IDs or hashes

            With distinct=True and fields_only, sort fields are automatically included
            to enable Python re-sorting, then objects contain only requested + sort fields.
        """
        if select_related is None:
            raise ValueError("select_related parameter is required")
        if additional_filters is None:
            additional_filters = {}

        files = self.FileIndex_entries.filter(delete_pending=False, **additional_filters)

        # Determine field loading strategy
        if fields_only:
            if distinct:
                # For distinct queries, we need sort fields + requested fields for Python re-sorting
                sort_fields = SORT_MATRIX[sort]

                # Extract field names from sort specification (remove - prefix)
                sort_field_names = {f.lstrip("-") for f in sort_fields}

                # Combine requested fields, sort fields, and file_sha256 (needed for DISTINCT ON)
                all_fields_needed = set(fields_only) | sort_field_names | {"file_sha256"}

                # Check if sort fields require related objects (contain __)
                needs_related_fields = any("__" in field for field in sort_field_names)

                if needs_related_fields:
                    # Sort requires related fields - must use full select_related
                    # We can't use .only() effectively with related fields without causing N+1
                    # So fall back to full query for these cases
                    files = files.select_related(*select_related)
                else:
                    # Sort only uses local fields - can safely use .only()
                    files = files.only(*all_fields_needed)
            else:
                # Non-distinct queries - simple field restriction
                files = files.only(*fields_only)
        else:
            # Full query with all related objects
            files = files.select_related(*select_related)

        if distinct:
            # Step 1: Get deduplicated records (PostgreSQL orders by file_sha256 first)
            files = files.order_by("file_sha256", *SORT_MATRIX[sort]).distinct("file_sha256")

            # Step 2: Convert to list (need full objects for re-sorting)
            files_list = list(files)

            # Step 3: Re-sort in Python using user's preference
            # Apply sort fields in reverse order for stable multi-field sorting
            sort_fields = SORT_MATRIX[sort]

            # Helper function to extract sort key from related field paths
            def make_sort_key(field_path):
                """Create a sort key function for the given field path."""
                parts = field_path.split("__")

                def get_value(obj):
                    value = obj
                    for part in parts:
                        value = getattr(value, part)
                    return value

                return get_value

            for field in reversed(sort_fields):
                is_reverse = field.startswith("-")
                field_name = field.lstrip("-")
                files_list.sort(key=make_sort_key(field_name), reverse=is_reverse)

            return files_list

        files = files.order_by(*SORT_MATRIX[sort])
        return files

    @cached(distinct_files_cache)
    def get_distinct_file_shas(self, sort: int = 0) -> list[str]:
        """
        Get distinct file SHA256s for this directory with caching.

        This method provides memory-efficient caching of distinct file lists for pagination.
        Instead of caching full FileIndex objects (~1KB each), it caches only SHA256 strings
        (~64 bytes each), reducing memory usage by ~94%.

        Cache key: (self, sort) - directory instance and sort order
        Allows efficient pagination across multiple pages without re-fetching distinct files.

        Performance Impact:
        - First call: Fetches SHA256s with minimal data using fields_only (efficient)
        - Subsequent calls: Returns cached list (instant, no DB query)
        - Memory: ~64KB per 1,000 files (just SHA256 strings)

        Cache Invalidation:
        Automatically cleared by clear_layout_cache_for_directories() when:
        - Directory contents change (cache_watcher)
        - Thumbnails are generated (web views)
        - File properties change (management commands)

        Args:
            sort: Sort order to apply (0-2)

        Returns:
            List of unique_sha256 strings for distinct files in the directory,
            sorted according to sort order
        """
        # Use fields_only to minimize memory usage - only load fields needed for deduplication
        # This prevents loading full FileIndex objects with all relationships (~1KB each)
        # For a directory with 10,000 files, this saves ~10MB of memory per call
        # Note: files_in_dir(distinct=True) returns a list after deduplication and re-sorting
        # Import here to avoid circular import at module level
        # pylint: disable-next=import-outside-toplevel
        from .fileindex import FILEINDEX_SR_FILETYPE_HOME_VIRTUAL

        distinct_files_list = self.files_in_dir(
            sort=sort, distinct=True, fields_only=("unique_sha256", "file_sha256"), select_related=FILEINDEX_SR_FILETYPE_HOME_VIRTUAL
        )
        return [f.unique_sha256 for f in distinct_files_list]

    def get_cover_image(self) -> FileIndex | None:
        """
        Return the cover image for the directory based on priority filename matching.

        Args:
            None

        Returns:
            FileIndex record if a suitable cover image is found, None otherwise

        Logic:
            1. Get files in directory that can be thumbnailed (images, movies, PDFs)
            2. If no files exist, return None
            3. Check for files matching DIRECTORY_COVER_NAMES (case-insensitive)
            4. If match found, return that file's FileIndex record
            5. If no match, return the first file in the query
        """
        # Import here to avoid circular import at module level
        # pylint: disable-next=import-outside-toplevel
        from .fileindex import FILEINDEX_SR_FILETYPE

        # Get thumbnailable files (images, movies, PDFs), excluding link files
        thumbnailable_filters = (Q(filetype__is_image=True) & ~Q(filetype__is_link=True)) | Q(filetype__is_movie=True) | Q(filetype__is_pdf=True)

        files = self.files_in_dir(sort=0, select_related=FILEINDEX_SR_FILETYPE).filter(thumbnailable_filters)

        # If no files exist, return None
        if not files.exists():
            return None

        # Try to find a file matching the cover names using prebuilt query from settings
        # This replaces nested loops with a single database query for ~99% speedup
        cover_queries = getattr(settings, "DIRECTORY_COVER_QUERIES", Q())
        cover_file = files.filter(cover_queries).first()
        if cover_file:
            return cover_file

        # No match found, return first file
        return files.first()

    def dirs_in_dir(
        self, sort: int = 0, fields_only: list[str] | None = None, select_related: list[str] | None = None, prefetch_related: list[str] | None = None
    ) -> "QuerySet[DirectoryIndex]":
        """
        Return the directories in the current directory

        Args:
            sort: The sort order of the directories (0-2)
            fields_only: If provided, return lightweight query with only these fields.
                        Skips expensive select_related/prefetch_related operations.
                        Useful when only paths or IDs are needed for comparison.
            select_related: List of related fields to select (required)
            prefetch_related: List of related fields to prefetch (required)

        Returns: The sorted query of directories

        Note:
            Using fields_only significantly reduces memory usage (~60-70%) when full
            objects with related data aren't needed. Common use cases:
            - Path comparison during filesystem sync
            - Getting directory IDs for batch operations
            - Building simple directory lists
        """
        if select_related is None:
            raise ValueError("select_related parameter is required")
        if prefetch_related is None:
            raise ValueError("prefetch_related parameter is required")
        queryset = DirectoryIndex.objects.filter(parent_directory=self.pk, delete_pending=False)

        if fields_only:
            # Lightweight query - only load specified fields, skip related objects
            return queryset.only(*fields_only).order_by(*SORT_MATRIX[sort])

        # Full query with all related objects prefetched
        # REMOVED: Hardcoded Prefetch("FileIndex_entries"...) - Phase 5 Fix 3
        # Prefetching all files in a directory loads 1-2MB per directory unnecessarily
        # File counts are obtained via annotation, not prefetch iteration
        # Only prefetch if explicitly requested via prefetch_related parameter

        # Apply select_related for forward FKs/OneToOne
        if select_related:
            queryset = queryset.select_related(*select_related)

        # Apply prefetch_related for reverse FKs/M2M (on different relationships only)
        if prefetch_related:
            queryset = queryset.prefetch_related(*prefetch_related)

        return queryset.order_by(*SORT_MATRIX[sort])

    @cached(directoryindex_cache)
    def get_view_url(self) -> str:
        """
        Generate the URL for the viewing of the current database item

        Returns
        -------
            Django URL object

        """
        # pylint: disable-next=import-outside-toplevel
        from frontend.utilities import convert_to_webpath

        webpath = convert_to_webpath(self.fqpndirectory.removeprefix(self.get_albums_prefix()))
        # URL-encode each path component while preserving / separators
        parts = webpath.split("/")
        encoded_parts = [quote(part, safe="") for part in parts]
        webpath = "/".join(encoded_parts)
        return reverse("directories") + webpath

    # pylint: disable-next=unused-argument
    def get_thumbnail_url(self, size=None) -> str:
        """
        Generate the URL for the thumbnail of the current item
        The argument is unused, included for API compt. between FileIndex & DirectoryIndex

        Returns
        -------
            Django URL object

        """
        return reverse(r"thumbnail2_dir", args=(self.dir_fqpn_sha256,))

    async def get_prev_next_siblings(self, sort_order: int = 0) -> tuple[dict | None, dict | None]:
        """
        Get the previous and next sibling directories in parent directory.

        Used for breadcrumb navigation to allow moving between siblings.
        Returns dictionaries with 'url' and 'name' keys for prev/next navigation links.

        :Args:
            sort_order: Sort order to apply (0=name, 1=date, 2=name only)

        :return: Tuple of (prev_dict, next_dict) where each dict has 'url' and 'name' keys,
                 or (None, None) if no parent directory

        Note:
            ORM only derived from https://stackoverflow.com/questions/1042596/
            get-the-index-of-an-element-in-a-queryset
            Specifically Richard's answer.
        """
        from urllib.parse import unquote

        # No parent directory means this is a root directory
        if self.parent_directory is None:
            return (None, None)

        # Wrap queryset operations
        directories = await sync_to_async(self.parent_directory.dirs_in_dir)(sort=sort_order, select_related=(), prefetch_related=())
        parent_dir_data = await sync_to_async(list)(directories.values("fqpndirectory"))

        prevdir = None
        nextdir = None

        for count, entry in enumerate(parent_dir_data):
            if entry["fqpndirectory"] == self.fqpndirectory:
                if count >= 1:
                    # Use pathlib to normalize path (removes trailing slashes)
                    prev_path = str(Path(parent_dir_data[count - 1]["fqpndirectory"]))
                    prev_path = prev_path.replace(settings.ALBUMS_PATH, "")
                    # URL-encode each path component while preserving / separators
                    parts = prev_path.split("/")
                    encoded_parts = [quote(part, safe="") for part in parts]
                    prev_url = "/".join(encoded_parts)
                    # Get human-readable name (last part of path, decoded)
                    prev_name = unquote(parts[-1]) if parts and parts[-1] else ""
                    prevdir = {"url": prev_url, "name": prev_name}

                if count + 1 < len(parent_dir_data):
                    # Use pathlib to normalize path (removes trailing slashes)
                    next_path = str(Path(parent_dir_data[count + 1]["fqpndirectory"]))
                    next_path = next_path.replace(settings.ALBUMS_PATH, "")
                    # URL-encode each path component while preserving / separators
                    parts = next_path.split("/")
                    encoded_parts = [quote(part, safe="") for part in parts]
                    next_url = "/".join(encoded_parts)
                    # Get human-readable name (last part of path, decoded)
                    next_name = unquote(parts[-1]) if parts and parts[-1] else ""
                    nextdir = {"url": next_url, "name": next_name}
                break

        return (prevdir, nextdir)

    async def handle_missing(self) -> None:
        """
        Handle case where this directory doesn't exist on filesystem.

        Called during filesystem synchronization when directory is missing.
        - Deletes this directory record from database
        - Clears cache for parent directory

        This is an async method as it may need to clear caches that involve
        async operations.
        """
        # Access preloaded parent_directory (loaded via select_related)
        parent_dir = self.parent_directory
        await sync_to_async(DirectoryIndex.delete_directory_record)(self)

        # Clean up parent directory cache if it exists
        if parent_dir:
            await sync_to_async(DirectoryIndex.delete_directory_record)(parent_dir, cache_only=True)

    def process_new_files(self, fs_file_names: dict, precomputed_shas: dict[str, tuple] | None = None) -> list[FileIndex]:
        """
        Process new files in this directory that don't exist in the database.

        Creates new FileIndex records for files found on filesystem that don't
        have corresponding database entries.

        Performance Optimization:
        Accepts precomputed SHA256 hashes to enable batch parallel computation.

        :Args:
            fs_file_names: Dictionary mapping filenames to DirEntry objects
            precomputed_shas: Optional dict mapping file paths to (file_sha256, unique_sha256) tuples

        Returns:
            List of new FileIndex records to create
        """
        # Import at function level to avoid circular dependency
        from .fileindex import FileIndex

        records_to_create = []
        if precomputed_shas is None:
            precomputed_shas = {}

        # Single pass through new files
        for _, fs_entry in fs_file_names.items():
            try:
                # Process new file with precomputed SHA if available
                filedata = FileIndex.from_filesystem(fs_entry, directory_id=self, precomputed_sha=precomputed_shas.get(str(fs_entry)))
                if filedata is None:
                    continue

                # Early skip for archives and other excluded types
                filetype = filedata.get("filetype")
                if filetype and filetype.is_archive:
                    continue

                # Create record - home_directory already set via process_filedata(directory_id=self)
                record = FileIndex(**filedata)
                # record.home_directory = self  # Already set in filedata dict
                records_to_create.append(record)

            except (OSError, IOError, ValueError, TypeError) as e:
                logger.error(f"Error processing new file {fs_entry}: {e}")
                continue

        return records_to_create

    def sync_subdirectories(self, fs_entries: dict) -> None:
        """
        Synchronize my subdirectories with filesystem entries.

        Compares database records of subdirectories against filesystem and:
        - Marks missing subdirectories for deletion
        - Updates modification times for changed directories
        - Creates new subdirectories found in filesystem

        IMPORTANT - Async Wrapper Pattern:
        This function is SYNC and wrapped with sync_to_async at the call site.
        This pattern is safer than having nested @sync_to_async decorators within an async function.

        Why sync instead of async:
        - All operations are database transactions (atomic blocks)
        - Prevents nested async/sync boundary issues
        - Single sync_to_async wrapper is more efficient than multiple nested ones
        - Easier to reason about transaction boundaries

        Thread Safety:
        - All DB operations in transaction.atomic() blocks
        - Safe for WSGI (Gunicorn) and ASGI (Uvicorn/Hypercorn)
        - No thread pool usage = no connection leakage

        :Args:
            fs_entries: Dictionary mapping entry names to DirEntry objects
        """
        # Inline import to avoid circular dependency:
        # cache_watcher.models imports DirectoryIndex in multiple places
        # pylint: disable-next=import-outside-toplevel
        from cache_watcher.models import Cache_Storage

        print("Synchronizing directories...")
        logger.info("Synchronizing directories...")
        current_path = normalize_fqpn(self.fqpndirectory)

        # Get all database directories efficiently - use lightweight query for path comparison
        # Avoid loading full objects with select_related/prefetch_related when only paths needed
        all_dirs_queryset = DirectoryIndex.objects.filter(parent_directory=self.pk, delete_pending=False)
        db_dirs = set(all_dirs_queryset.values_list("fqpndirectory", flat=True))
        fs_dirs = {normalize_fqpn(current_path + entry.name) for entry in fs_entries.values() if entry.is_dir()}

        # Load full objects only for directories that exist in both DB and filesystem
        # This requires select_related for lastmod/size comparisons
        # Use queryset with iterator for memory-efficient streaming (single-pass iteration)
        existing_dirs_qs = self.dirs_in_dir(select_related=(), prefetch_related=(), fields_only=("id", "fqpndirectory", "lastmod")).filter(
            fqpndirectory__in=db_dirs & fs_dirs
        )
        existing_count = existing_dirs_qs.count()

        print(f"Existing directories in database: {existing_count}")
        if existing_count > 0:
            # Check each directory for updates
            updated_records = []
            for db_dir_entry in existing_dirs_qs.iterator(chunk_size=100):
                # Extract directory name from full path and title-case it to match fs_entries keys
                # NOTE: fs_entries dict is keyed by title-cased filenames (e.g., "Photos"), not full paths
                # (e.g., "/volumes/c-8tb/gallery/albums/photos/"). Using full path would always return None.
                # See return_disk_listing() in file_listings.py which uses normalize_string_title() for keys.
                dir_name = Path(db_dir_entry.fqpndirectory.rstrip(os.sep)).name
                dir_name_titled = normalize_string_title(dir_name)

                if fs_entry := fs_entries.get(dir_name_titled):
                    try:
                        # DirEntry.stat() is cached by Python's os.scandir()
                        # Multiple stat() calls on the same DirEntry reuse cached result
                        fs_stat = fs_entry.stat()
                        # Update modification time if changed (DirectoryIndex doesn't track size)
                        if db_dir_entry.lastmod != fs_stat.st_mtime:
                            db_dir_entry.lastmod = fs_stat.st_mtime
                            updated_records.append(db_dir_entry)
                    except (OSError, IOError) as e:
                        logger.error(f"Error checking directory {db_dir_entry.fqpndirectory}: {e}")

            print(f"Directories to Update: {len(updated_records)}")

            if updated_records:
                print(f"processing existing directory changes: {len(updated_records)}")
                with transaction.atomic():
                    # Lock rows to prevent concurrent modifications, then bulk update
                    update_ids = [r.id for r in updated_records]
                    DirectoryIndex.objects.select_for_update(skip_locked=True).filter(id__in=update_ids).only("id")
                    DirectoryIndex.objects.bulk_update(updated_records, ["lastmod"], batch_size=100)
                    for db_dir_entry in updated_records:
                        Cache_Storage.remove_from_cache_indexdirs(db_dir_entry)
                logger.info(f"Processing {len(updated_records)} directory updates")

        # Create new directories BEFORE deleting old ones to prevent foreign key violations
        new_dirs = fs_dirs - db_dirs
        if new_dirs:
            print(f"Directories to Add: {len(new_dirs)}")
            logger.info(f"Directories to Add: {len(new_dirs)}")
            with transaction.atomic():
                for dir_to_create in new_dirs:
                    DirectoryIndex.add_directory(fqpn_directory=dir_to_create)
            # Clear cache for parent directory (self) to show new subdirectories in web view
            Cache_Storage.remove_from_cache_indexdirs(self)

        # Delete directories that no longer exist in filesystem
        deleted_dirs = db_dirs - fs_dirs
        if deleted_dirs:
            print(f"Directories to Delete: {len(deleted_dirs)}")
            logger.info(f"Directories to Delete: {len(deleted_dirs)}")
            with transaction.atomic():
                all_dirs_queryset.filter(fqpndirectory__in=deleted_dirs).delete()
                Cache_Storage.remove_from_cache_indexdirs(self)

    def sync_files(self, fs_entries: dict, bulk_size: int) -> None:
        """
        Synchronize my files with filesystem entries.

        Compares database FileIndex records against filesystem and:
        - Marks missing files as delete_pending
        - Updates modified files (size, timestamps, SHA256)
        - Creates new files found in filesystem
        - Uses bulk operations for efficiency

        IMPORTANT - Simplification Notes:
        Removed complex chunking logic that was causing multiple QuerySet evaluations.
        Previous version called .count() multiple times and used dynamic batch sizing.

        Current approach:
        - Single pass through QuerySet (no chunking for updates check)
        - Simpler logic = faster execution and easier to understand
        - Still uses bulk operations for actual DB writes

        Thread Safety:
        - This is a SYNC function wrapped with sync_to_async at call site
        - All DB operations safe for WSGI/ASGI
        - Transactions handled in _execute_batch_operations

        :Args:
            fs_entries: Dictionary mapping entry names to DirEntry objects
            bulk_size: Size of batches for bulk operations (updates/creates)
        """
        # Inline imports to avoid circular dependencies
        from frontend.utilities import _batch_compute_file_shas

        from .fileindex import FileIndex

        # Build filesystem file dictionary (single pass)
        fs_file_names_dict = {name: entry for name, entry in fs_entries.items() if not entry.is_dir()}
        fs_file_names = list(fs_file_names_dict.keys())

        # Build case-insensitive lookup dictionary for matching
        # Maps lowercase filename -> original cased filename from filesystem
        fs_names_lower_map = {name.lower(): name for name in fs_file_names}

        # Optimize: First get just filenames with lightweight query (no prefetch overhead)
        # Then load full objects only for files that need comparison/updates
        all_db_filenames = set(FileIndex.objects.filter(home_directory=self.pk, delete_pending=False).values_list("name", flat=True))

        # Find files that exist in both DB and filesystem (case-insensitive match)
        # Build lowercase map from database names for matching
        db_names_lower_set = {name.lower() for name in all_db_filenames}
        matching_lower_names = set(fs_names_lower_map.keys()) & db_names_lower_set

        # Load full objects with prefetch only for files that need comparison
        # Convert matching lowercase names back to original database names
        matching_db_names = {name for name in all_db_filenames if name.lower() in matching_lower_names}
        potential_updates = list(self.files_in_dir(select_related=FILEINDEX_SR_FILETYPE).filter(name__in=matching_db_names))

        # Batch compute SHA256 for files missing hashes
        files_needing_hash = []
        for db_file_entry in potential_updates:
            if not db_file_entry.file_sha256:
                # Use case-insensitive lookup: db name -> lowercase -> fs name -> fs entry
                fs_name = fs_names_lower_map[db_file_entry.name.lower()]
                fs_entry = fs_file_names_dict[fs_name]
                files_needing_hash.append((db_file_entry, str(fs_entry)))

        # Parallel SHA256 computation for missing hashes
        sha_results = {}
        if files_needing_hash:
            paths_to_hash = [path for _, path in files_needing_hash]
            sha_results = _batch_compute_file_shas(paths_to_hash)

        # Single pass through files needing updates
        records_to_update = []
        for db_file_entry in potential_updates:
            # Use case-insensitive lookup: db name -> lowercase -> fs name -> fs entry
            fs_name = fs_names_lower_map[db_file_entry.name.lower()]
            fs_entry = fs_file_names_dict[fs_name]
            updated_record = db_file_entry.check_for_updates(
                fs_entry,
                self,
                sha_results.get(str(fs_entry)),
            )
            if updated_record:
                records_to_update.append(updated_record)

        # Get files to delete - case-insensitive: db files NOT matching any fs file
        # Find DB files whose lowercase name is NOT in the filesystem (case-insensitive comparison)
        #
        # NOTE: Must compare at lowercase level to avoid false deletions on case-preserving filesystems.
        # The DB may store "MyFile.txt" while filesystem returns "Myfile.Txt" (title-cased by return_disk_listing).
        # Comparing original cases directly would incorrectly mark the file for deletion.
        # Instead, we compare lowercase sets, then map back to original DB names.
        db_names_not_in_fs_lower = db_names_lower_set - matching_lower_names
        db_names_not_in_fs = {name for name in all_db_filenames if name.lower() in db_names_not_in_fs_lower}
        files_to_delete_ids = list(
            FileIndex.objects.filter(home_directory=self.pk, name__in=db_names_not_in_fs, delete_pending=False).values_list("id", flat=True)
        )

        # Process new files - case-insensitive: fs files NOT matching any db file
        # Filesystem files whose lowercase name is NOT in database (case-insensitive)
        fs_file_names_for_creation = [name for name in fs_file_names if name.lower() not in db_names_lower_set]
        creation_fs_file_names_dict = {name: fs_file_names_dict[name] for name in fs_file_names_for_creation}

        # Batch compute SHA256 for new files (excluding links/archives which are handled individually)
        new_file_paths = []
        for fs_entry in creation_fs_file_names_dict.values():
            if not fs_entry.is_dir():
                fileext = fs_entry.suffix.lower() if fs_entry.suffix else ""
                if fileext and fileext != ".":
                    # Only batch non-link files (links are processed specially in process_filedata)
                    if fileext not in [".link", ".alias"]:
                        new_file_paths.append(str(fs_entry))

        # Parallel SHA256 computation for new files
        new_sha_results = {}
        if new_file_paths:
            new_sha_results = _batch_compute_file_shas(new_file_paths)

        records_to_create = self.process_new_files(creation_fs_file_names_dict, new_sha_results)

        # Execute batch operations with transactions
        FileIndex.bulk_sync(records_to_update, records_to_create, files_to_delete_ids, bulk_size)

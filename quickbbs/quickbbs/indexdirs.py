"""
IndexDirs Model - Master index for directories in the filesystem
"""

from __future__ import annotations

import pathlib
import time
from typing import TYPE_CHECKING, Any

from django.db.models import Count, Prefetch, Q
from django.db.models.query import QuerySet
from django.urls import reverse

# Import shared foundation
from .models import (
    INDEXDATA_SELECT_RELATED_LIST,
    INDEXDIRS_PREFETCH_LIST,
    INDEXDIRS_SELECT_RELATED_LIST,
    SORT_MATRIX,
    NaturalSortField,
    cached,
    distinct_files_cache,
    filetypes,
    get_dir_sha,
    indexdirs_cache,
    logger,
    models,
    normalize_fqpn,
    os,
    settings,
    sync_to_async,
)

if TYPE_CHECKING:
    from cache_watcher.models import fs_Cache_Tracking

    from .indexdata import IndexData


class IndexDirs(models.Model):
    """
    The master index for Directory / Folders in the Filesystem for the gallery.
    """

    _albums_prefix = None

    @classmethod
    def get_albums_prefix(cls) -> str:
        """Cache the albums path prefix for optimization"""
        if cls._albums_prefix is None:
            cls._albums_prefix = settings.ALBUMS_PATH.lower() + r"/albums/"
        return cls._albums_prefix

    fqpndirectory = models.CharField(db_index=True, max_length=384, default="", unique=True, blank=True)  # True fqpn name

    dir_fqpn_sha256 = models.CharField(
        db_index=True,
        blank=True,
        unique=True,
        null=True,
        default=None,
        max_length=64,
    )  # sha of the directory fqpn

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
    is_generic_icon = models.BooleanField(default=False, db_index=True)  # File is to be ignored
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
        "IndexData",
        on_delete=models.SET_NULL,
        related_name="dir_thumbnail",
        null=True,
        default=None,
    )
    file_links = models.ManyToManyField(
        "IndexData",
        default=None,
        related_name="file_links",
    )

    # Reverse relationships
    # From fs_Cache_Tracking.directory
    Cache_Watcher: "models.OneToOneRel[fs_Cache_Tracking]"  # type: ignore[valid-type]
    # From IndexDirs.parent_directory (self-referential)
    parent_dir: "models.manager.RelatedManager[IndexDirs]"
    # From IndexData.home_directory
    IndexData_entries: "models.manager.RelatedManager[IndexData]"
    # From IndexData.virtual_directory
    Virtual_IndexData: "models.manager.RelatedManager[IndexData]"

    class Meta:
        verbose_name = "Master Directory Index"
        verbose_name_plural = "Master Directory Index"
        indexes = [
            models.Index(fields=["parent_directory", "delete_pending"]),
            models.Index(fields=["dir_fqpn_sha256", "delete_pending"]),
        ]

    @staticmethod
    def add_directory(fqpn_directory: str, thumbnail: bytes = b"") -> tuple[bool, "IndexDirs"]:  # pylint: disable=unused-argument
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
        albums_root = normalize_fqpn(os.path.join(settings.ALBUMS_PATH, "albums"))
        is_in_albums = fqpn_directory.lower().startswith(albums_path_lower)

        # Determine parent directory link
        if is_in_albums:
            # Check if this IS the albums root directory - it has no parent
            if fqpn_directory.lower() == albums_root.lower():
                parent_dir_link = None
            else:
                # Regular subdirectory - find or create parent
                parent_dir = normalize_fqpn(str(pathlib.Path(fqpn_directory).parent))

                if parent_dir.lower().startswith(albums_path_lower):
                    # Recursively add/update parent to ensure proper parent_directory chain
                    # This fixes both missing parents AND parents with NULL parent_directory
                    parent_sha = get_dir_sha(parent_dir)
                    found, _ = IndexDirs.search_for_directory_by_sha(parent_sha)

                    if not found:
                        print(f"Creating parent directory: {parent_dir}")

                    # Always call add_directory to ensure parent has correct parent_directory link
                    # update_or_create will handle both new and existing records
                    _, parent_dir_link = IndexDirs.add_directory(parent_dir)
                else:
                    # Parent is outside albums path, don't link it
                    parent_dir_link = None
        else:
            parent_dir_link = None

        # Use single stat call for both exists check and mtime
        dir_path = pathlib.Path(fqpn_directory)
        try:
            stat_info = dir_path.stat()
        except (FileNotFoundError, OSError):
            return (False, None)  # Return None when directory doesn't exist

        defaults = {
            "fqpndirectory": fqpn_directory,  # Already normalized
            "lastmod": stat_info.st_mtime,
            "lastscan": time.time(),
            "filetype": filetypes(fileext=".dir"),
            "dir_fqpn_sha256": dir_sha256,  # Already computed
            "parent_directory": parent_dir_link,
            "is_generic_icon": False,
            "thumbnail": None,
        }

        # Use get_or_create with fqpndirectory as the unique lookup field
        new_rec, created = IndexDirs.objects.update_or_create(
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
        IndexDirs.objects.filter(pk=self.pk).update(thumbnail=None, is_generic_icon=False)
        # Refresh local instance to reflect DB state
        self.thumbnail = None
        self.is_generic_icon = False

        # Clear LRUCache entry for this directory to avoid serving stale cached data
        if self.dir_fqpn_sha256 in indexdirs_cache:
            del indexdirs_cache[self.dir_fqpn_sha256]

    @property
    def virtual_directory(self) -> str:
        """
        Return the virtual directory name of the directory.
        This is used to return the directory name without the full path.

        Returns:
            String
        """
        return str(pathlib.Path(self.fqpndirectory).name)

    @property
    def numdirs(self) -> None:
        """
        Stub property for template compatibility.

        Provides API compatibility between IndexDirs and IndexData objects when used in
        Jinja2 templates. This allows templates to access .numdirs on either object type
        without checking the instance type first. IndexData objects return actual directory
        counts, while this property returns None since directory objects don't track this metric.

        Returns:
            None
        """
        return None

    @property
    def numfiles(self) -> None:
        """
        Stub property for template compatibility.

        Provides API compatibility between IndexDirs and IndexData objects when used in
        Jinja2 templates. This allows templates to access .numfiles on either object type
        without checking the instance type first. IndexData objects return actual file
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
        return str(pathlib.Path(self.fqpndirectory).name)

    @property
    def is_cached(self) -> bool:
        """
        Check if this directory has a valid cache entry.

        Uses the 1-to-1 relationship to fs_Cache_Tracking (Cache_Watcher)
        to efficiently determine cache status without additional queries.

        Returns:
            True if directory is cached and not invalidated, False otherwise
        """
        return hasattr(self, "Cache_Watcher") and not self.Cache_Watcher.invalidated

    @staticmethod
    def get_all_parent_shas(sha_list: list[str]) -> set[str]:
        """
        Get all parent directory SHAs using optimized batch queries.

        Pure Django ORM with no external dependencies. Uses iterative batch fetching
        instead of recursive CTE, but still much more efficient than N*M approach.

        Args:
            sha_list: List of directory SHA256 hashes to find parents for

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
                IndexDirs.objects.filter(
                    dir_fqpn_sha256__in=current_level_shas,
                    delete_pending=False,
                    parent_directory__isnull=False,
                )
                .select_related("parent_directory")
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
    def delete_directory_record(index_dir: "IndexDirs", cache_only: bool = False) -> None:
        """
        Delete the Index_Dirs record and ensure cache cleanup.

        Optimized version that accepts an IndexDirs record directly,
        avoiding redundant database lookups.

        Args:
            index_dir: IndexDirs instance to delete
            cache_only: If True, only clear cache, don't delete the record

        Returns:
            None
        """
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
        Delete the Index_Dirs data for the fqpn_directory, and ensure that all
        IndexData records are wiped as well.

        Args:
            fqpn_directory: text string of fully qualified pathname of the directory
            cache_only: Do not perform a delete on the Index_Dirs data

        Returns:
        """
        # pylint: disable-next=import-outside-toplevel
        from cache_watcher.models import Cache_Storage

        dir_sha256 = get_dir_sha(normalize_fqpn(fqpn_directory))
        Cache_Storage.remove_from_cache_sha(dir_sha256)
        if not cache_only:
            IndexDirs.objects.filter(dir_fqpn_sha256=dir_sha256).delete()

    def do_files_exist(self, additional_filters: dict[str, Any] | None = None) -> bool:
        """
        Check if any files exist in the current directory with optional filters

        Args:
            additional_filters: Additional Django ORM filters to apply (e.g., filetype, status filters)

        Returns: Boolean indicating if files exist in the directory using QuerySet.exists()
        """
        additional_filters = additional_filters or {}
        return self.IndexData_entries.filter(home_directory=self.pk, delete_pending=False, **additional_filters).exists()

    def get_file_counts(self) -> int:
        """
        Return the number of files that are in the database for the current directory
        Returns: Integer - Number of files in the database for the directory
        """
        return self.IndexData_entries.filter(delete_pending=False).count()
        # return IndexData.objects.filter(
        #    home_directory=self.pk, delete_pending=False
        # ).count()

    def get_dir_counts(self) -> int:
        """
        Return the number of directories that are in the database for the current directory
        Returns: Integer - Number of directories
        """
        return IndexDirs.objects.filter(parent_directory=self.pk, delete_pending=False).count()

    def get_count_breakdown(self) -> dict[str, int]:
        """
        Return the count of items in the directory, broken down by filetype.
        Returns: dictionary, where the key is the filetype (e.g. "dir", "jpg", "mp4"),
        and the value is the number of items of that filetype.
        A special "all_files" key is used to store the # of all items in the directory (except
        for directories).  (all_files is the sum of all file types, except "dir")
        """
        # pylint: disable-next=import-outside-toplevel
        from filetypes.models import get_ftype_dict

        filetypes_dict = get_ftype_dict()

        # Single aggregate query for ALL file counts by type
        file_aggregates = self.IndexData_entries.filter(delete_pending=False).aggregate(
            total_files=Count("id"),
            **{f"type_{ft[1:]}": Count("id", filter=Q(filetype__fileext=ft)) for ft in filetypes_dict.keys()},
        )

        # Directory count (separate table, still needs its own query)
        dir_count = IndexDirs.objects.filter(parent_directory=self.pk, delete_pending=False).count()

        # Build result dictionary from aggregates
        totals = {ft[1:]: file_aggregates.get(f"type_{ft[1:]}", 0) for ft in filetypes_dict.keys()}
        totals["dir"] = dir_count
        totals["all_files"] = file_aggregates["total_files"]

        return totals

    @cached(indexdirs_cache)
    @staticmethod
    def search_for_directory_by_sha(sha_256: str) -> tuple[bool, "IndexDirs"]:
        """
        Return the database object matching the dir_fqpn_sha256

        Args:
            sha_256: The SHA-256 hash of the directory's fully qualified pathname

        Returns: A boolean representing the success of the search, and the resultant record
        """
        # Internal prefetch list - excludes filetype (uses select_related instead)
        SEARCH_PREFETCH_LIST = [
            "IndexData_entries",
        ]

        try:
            record = (
                IndexDirs.objects.select_related(*INDEXDIRS_SELECT_RELATED_LIST)
                .prefetch_related(*SEARCH_PREFETCH_LIST)
                .get(
                    dir_fqpn_sha256=sha_256,
                    delete_pending=False,
                )
            )
            return (True, record)
        except IndexDirs.DoesNotExist:
            return (False, None)  # Return None when not found

    @staticmethod
    def search_for_directory(fqpn_directory: str) -> tuple[bool, "IndexDirs"]:
        """
        Return the database object matching the fqpn_directory

        NOTE: This method is NOT cached. It delegates to search_for_directory_by_sha()
        which IS cached. Do NOT add @cached decorator here as it creates duplicate cache
        entries (one by path, one by SHA) that become inconsistent during invalidation.

        Args:
            fqpn_directory: The fully qualified pathname of the directory

        Returns: A boolean representing the success of the search, and the resultant record
        """
        sha_256 = get_dir_sha(fqpn_directory)
        return IndexDirs.search_for_directory_by_sha(sha_256)

    @staticmethod
    def return_by_sha256_list(sha256_list: list[str], sort: int = 0) -> "QuerySet[IndexDirs]":
        """
        Return directories matching the provided SHA256 list

        Args:
            sha256_list: List of directory SHA256 hashes to filter by
            sort: The sort order of the dirs (0-2)

        Returns: The sorted query of directories matching the SHA256 list
        """
        dirs = (
            IndexDirs.objects.select_related(*INDEXDIRS_SELECT_RELATED_LIST)
            .prefetch_related(*INDEXDIRS_PREFETCH_LIST)
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
    ) -> "QuerySet[IndexData] | list[IndexData]":
        """
        Return the files in the current directory

        Args:
            sort: The sort order of the files (0-2)
            distinct: If True, return distinct files based on file_sha256 (deduplicates identical files)
            additional_filters: Additional Django ORM filters to apply (e.g., filetype, status filters)
            fields_only: If provided, return lightweight query with only these fields.
                        With distinct=True: Only optimizes if sort doesn't require related fields.
                        Current sort modes (0-2) use filetype relations, so fall back to full query.

        Returns: QuerySet[IndexData] when distinct=False, list[IndexData] when distinct=True

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
        if additional_filters is None:
            additional_filters = {}

        files = self.IndexData_entries.filter(delete_pending=False, **additional_filters)

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
                    files = files.select_related(*INDEXDATA_SELECT_RELATED_LIST)
                else:
                    # Sort only uses local fields - can safely use .only()
                    files = files.only(*all_fields_needed)
            else:
                # Non-distinct queries - simple field restriction
                files = files.only(*fields_only)
        else:
            # Full query with all related objects
            files = files.select_related(*INDEXDATA_SELECT_RELATED_LIST)

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
        Instead of caching full IndexData objects (~1KB each), it caches only SHA256 strings
        (~64 bytes each), reducing memory usage by ~94%.

        Cache key: (self, sort) - directory instance and sort order
        Allows efficient pagination across multiple pages without re-fetching distinct files.

        Performance Impact:
        - First call: Fetches and materializes all distinct files (expensive)
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
        distinct_files = self.files_in_dir(sort=sort, distinct=True)
        return [f.unique_sha256 for f in distinct_files]

    def get_cover_image(self) -> IndexData | None:
        """
        Return the cover image for the directory based on priority filename matching.

        Args:
            None

        Returns:
            IndexData record if a suitable cover image is found, None otherwise

        Logic:
            1. Get files in directory that can be thumbnailed (images, movies, PDFs)
            2. If no files exist, return None
            3. Check for files matching DIRECTORY_COVER_NAMES (case-insensitive)
            4. If match found, return that file's IndexData record
            5. If no match, return the first file in the query
        """
        # Get thumbnailable files (images, movies, PDFs), excluding link files
        thumbnailable_filters = (Q(filetype__is_image=True) & ~Q(filetype__is_link=True)) | Q(filetype__is_movie=True) | Q(filetype__is_pdf=True)

        files = self.files_in_dir(sort=0).filter(thumbnailable_filters)

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

    def dirs_in_dir(self, sort: int = 0, fields_only: list[str] | None = None) -> "QuerySet[IndexDirs]":
        """
        Return the directories in the current directory

        Args:
            sort: The sort order of the directories (0-2)
            fields_only: If provided, return lightweight query with only these fields.
                        Skips expensive select_related/prefetch_related operations.
                        Useful when only paths or IDs are needed for comparison.

        Returns: The sorted query of directories

        Note:
            Using fields_only significantly reduces memory usage (~60-70%) when full
            objects with related data aren't needed. Common use cases:
            - Path comparison during filesystem sync
            - Getting directory IDs for batch operations
            - Building simple directory lists
        """
        # Import here to avoid circular import at module level
        # pylint: disable-next=import-outside-toplevel
        from .indexdata import IndexData

        queryset = IndexDirs.objects.filter(parent_directory=self.pk, delete_pending=False)

        if fields_only:
            # Lightweight query - only load specified fields, skip related objects
            return queryset.only(*fields_only).order_by(*SORT_MATRIX[sort])

        # Full query with all related objects prefetched
        return (
            queryset.select_related(*INDEXDIRS_SELECT_RELATED_LIST)
            .prefetch_related(
                Prefetch("IndexData_entries", queryset=IndexData.objects.filter(delete_pending=False)),
            )
            .order_by(*SORT_MATRIX[sort])
        )

    @cached(indexdirs_cache)
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
        return reverse("directories") + webpath

    # pylint: disable-next=unused-argument
    def get_thumbnail_url(self, size=None) -> str:
        """
        Generate the URL for the thumbnail of the current item
        The argument is unused, included for API compt. between IndexData & IndexDirs

        Returns
        -------
            Django URL object

        """
        return reverse(r"thumbnail2_dir", args=(self.dir_fqpn_sha256,))

    async def get_prev_next_siblings(self, sort_order: int = 0) -> tuple[str | None, str | None]:
        """
        Get the previous and next sibling directories in parent directory.

        Used for breadcrumb navigation to allow moving between siblings.
        Returns URIs suitable for prev/next navigation links.

        :Args:
            sort_order: Sort order to apply (0=name, 1=date, 2=name only)

        :return: Tuple of (prev_uri, next_uri) or (None, None) if no parent directory

        Note:
            ORM only derived from https://stackoverflow.com/questions/1042596/
            get-the-index-of-an-element-in-a-queryset
            Specifically Richard's answer.
        """
        # No parent directory means this is a root directory
        if self.parent_directory is None:
            return (None, None)

        # Wrap queryset operations
        directories = await sync_to_async(self.parent_directory.dirs_in_dir)(sort=sort_order)
        parent_dir_data = await sync_to_async(list)(directories.values("fqpndirectory"))

        prevdir = None
        nextdir = None

        for count, entry in enumerate(parent_dir_data):
            if entry["fqpndirectory"] == self.fqpndirectory:
                if count >= 1:
                    # Use pathlib to normalize path (removes trailing slashes)
                    prevdir = str(pathlib.Path(parent_dir_data[count - 1]["fqpndirectory"]))
                    prevdir = prevdir.replace(settings.ALBUMS_PATH, "")

                if count + 1 < len(parent_dir_data):
                    # Use pathlib to normalize path (removes trailing slashes)
                    nextdir = str(pathlib.Path(parent_dir_data[count + 1]["fqpndirectory"]))
                    nextdir = nextdir.replace(settings.ALBUMS_PATH, "")
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
        await sync_to_async(IndexDirs.delete_directory_record)(self)

        # Clean up parent directory cache if it exists
        if parent_dir:
            await sync_to_async(IndexDirs.delete_directory_record)(parent_dir, cache_only=True)

    def process_new_files(self, fs_file_names: dict, precomputed_shas: dict[str, tuple] | None = None) -> list[IndexData]:
        """
        Process new files in this directory that don't exist in the database.

        Creates new IndexData records for files found on filesystem that don't
        have corresponding database entries.

        Performance Optimization:
        Accepts precomputed SHA256 hashes to enable batch parallel computation.

        :Args:
            fs_file_names: Dictionary mapping filenames to DirEntry objects
            precomputed_shas: Optional dict mapping file paths to (file_sha256, unique_sha256) tuples

        Returns:
            List of new IndexData records to create
        """
        # Import at function level to avoid circular dependency
        from frontend.utilities import process_filedata

        from .indexdata import IndexData

        records_to_create = []
        if precomputed_shas is None:
            precomputed_shas = {}

        # Single pass through new files
        for _, fs_entry in fs_file_names.items():
            try:
                # Process new file with precomputed SHA if available
                filedata = process_filedata(fs_entry, directory_id=self, precomputed_sha=precomputed_shas.get(str(fs_entry)))
                if filedata is None:
                    continue

                # Early skip for archives and other excluded types
                filetype = filedata.get("filetype")
                if hasattr(filetype, "is_archive") and filetype.is_archive:
                    continue

                # Create record - home_directory already set via process_filedata(directory_id=self)
                record = IndexData(**filedata)
                # record.home_directory = self  # Already set in filedata dict
                records_to_create.append(record)

            except Exception as e:
                logger.error(f"Error processing new file {fs_entry}: {e}")
                continue

        return records_to_create

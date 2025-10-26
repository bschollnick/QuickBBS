"""
Django Models for quickbbs
"""

from __future__ import annotations

# Standard library imports
import logging
import os
import pathlib
import time
from typing import TYPE_CHECKING, Any

# Third-party imports
from asgiref.sync import sync_to_async
from cachetools import LRUCache, cached

# Django imports
from django.conf import settings
from django.contrib.auth.models import User  # pylint: disable=imported-auth-user
from django.db import models
from django.db.models import Count, Prefetch, Q
from django.db.models.query import QuerySet
from django.http import FileResponse, Http404, HttpResponse
from django.urls import reverse

# Local application imports
from filetypes.models import filetypes, get_ftype_dict

# TODO: Examine django-sage-streaming as a replacement for RangedFileResponse
# https://github.com/sageteamorg/django-sage-streaming
from ranged_fileresponse import RangedFileResponse
from thumbnails.models import ThumbnailFiles

from quickbbs.common import get_dir_sha, normalize_fqpn
from quickbbs.natsort_model import NaturalSortField

if TYPE_CHECKING:
    from cache_watcher.models import fs_Cache_Tracking

# Logger
logger = logging.getLogger(__name__)

# Async-safe caches for database object lookups
indexdirs_cache = LRUCache(maxsize=2000)
indexdata_cache = LRUCache(maxsize=2000)
indexdata_download_cache = LRUCache(maxsize=1000)


class Owners(models.Model):
    """
    Start of a permissions based model.
    """

    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=None, null=True, editable=False, blank=True, db_index=True)
    ownerdetails = models.OneToOneField(User, on_delete=models.CASCADE, db_index=True, default=None)

    # Reverse one-to-one relationship
    indexdata: "models.OneToOneRel[IndexData]"  # type: ignore[valid-type]  # From IndexData.ownership

    class Meta:
        verbose_name = "Ownership"
        verbose_name_plural = "Ownership"


class Favorites(models.Model):
    """
    Start of setting up a users based favorites for gallery items
    """

    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=None, null=True, editable=False, blank=True, db_index=True)


# Forward ForeignKeys and OneToOne - use select_related() for SQL JOINs (single query)
INDEXDIRS_SELECT_RELATED_LIST = [
    "filetype",
    "Cache_Watcher",  # Reverse OneToOne - can use select_related
]

# Reverse ForeignKeys - use prefetch_related() for separate queries
INDEXDIRS_PREFETCH_LIST = [
    "IndexData_entries",
    # "file_links",
    # "thumbnail",
    # "parent_directory",
    # "home_directory",
]


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
        Placeholder property for backward compatibility reasons (allows IndexDirs objects
        to be used interchangeably with IndexData objects in templates)

        Returns:
            None
        """
        return None

    @property
    def numfiles(self) -> None:
        """
        Placeholder property for backward compatibility reasons (allows IndexDirs objects
        to be used interchangeably with IndexData objects in templates)

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
        max_iterations = 50  # Prevent infinite loops (max reasonable directory depth)

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

    def return_parent_directory(self) -> IndexDirs | None:
        """
        Return the database object of the parent directory to the current directory

        Returns:
            IndexDirs instance if parent exists, None otherwise

        Note:
            This method directly accesses the parent_directory ForeignKey field.
            When used in async contexts, ensure the parent is prefetched with
            select_related('parent_directory') or wrap the call with sync_to_async.
        """
        return self.parent_directory

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

    @cached(indexdirs_cache)
    @staticmethod
    def search_for_directory(fqpn_directory: str) -> tuple[bool, "IndexDirs"]:
        """
        Return the database object matching the fqpn_directory

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
        # necessary to prevent circular references on startup
        # pylint: disable-next=import-outside-toplevel
        from frontend.utilities import SORT_MATRIX

        dirs = (
            IndexDirs.objects.select_related(*INDEXDIRS_SELECT_RELATED_LIST)
            .prefetch_related(*INDEXDIRS_PREFETCH_LIST)
            .filter(dir_fqpn_sha256__in=sha256_list)
            .filter(delete_pending=False)
            .order_by(*SORT_MATRIX[sort])
        )
        return dirs

    def files_in_dir(
        self, sort: int = 0, distinct: bool = False, additional_filters: dict[str, Any] | None = None
    ) -> "QuerySet[IndexData] | list[IndexData]":
        """
        Return the files in the current directory

        Args:
            sort: The sort order of the files (0-2)
            distinct: If True, return distinct files based on file_sha256 (deduplicates identical files)
            additional_filters: Additional Django ORM filters to apply (e.g., filetype, status filters)

        Returns: QuerySet[IndexData] when distinct=False, list[IndexData] when distinct=True

        Note:
            When distinct=True, PostgreSQL DISTINCT ON requires file_sha256 to be the first
            ORDER BY field, which disrupts the user's intended sort order. This method
            re-sorts the results in Python to maintain the correct order while still
            benefiting from PostgreSQL's fast DISTINCT ON operation.
        """
        # necessary to prevent circular references on startup
        # pylint: disable-next=import-outside-toplevel
        from frontend.utilities import SORT_MATRIX

        if additional_filters is None:
            additional_filters = {}

        files = self.IndexData_entries.select_related(*INDEXDATA_SELECT_RELATED_LIST).filter(delete_pending=False, **additional_filters)

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
        # Get thumbnailable files (images, movies, PDFs)
        thumbnailable_filters = Q(filetype__is_image=True) | Q(filetype__is_movie=True) | Q(filetype__is_pdf=True)

        files = self.files_in_dir(sort=0).filter(thumbnailable_filters)

        # If no files exist, return None
        if not files.exists():
            return None

        # Check for priority cover names from settings
        cover_names = getattr(settings, "DIRECTORY_COVER_NAMES", ["cover", "title"])

        # Try to find a file matching the cover names (case-insensitive)
        for cover_name in cover_names:
            # Case-insensitive match on filename without extension
            for file_obj in files:
                # Get filename without extension
                name_without_ext = os.path.splitext(file_obj.name)[0].lower()
                if name_without_ext == cover_name.lower():
                    return file_obj

        # No match found, return first file
        return files.first()

    def dirs_in_dir(self, sort: int = 0) -> "QuerySet[IndexDirs]":
        """
        Return the directories in the current directory

        Args:
            sort: The sort order of the directories (0-2)

        Returns: The sorted query of directories
        """
        # necessary to prevent circular references on startup
        # pylint: disable-next=import-outside-toplevel
        from frontend.utilities import SORT_MATRIX

        return (
            IndexDirs.objects.prefetch_related(
                Prefetch("IndexData_entries", queryset=IndexData.objects.filter(delete_pending=False)),
                "filetype",
            )
            .filter(parent_directory=self.pk, delete_pending=False)
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
        from frontend.utilities import convert_to_webpath

        webpath = convert_to_webpath(self.fqpndirectory.removeprefix(self.get_albums_prefix()))
        return reverse("directories") + webpath

    def get_bg_color(self) -> str:
        """
        Get the html / Cell background color of the file.

        Returns
        -------
        * The background hex color code of the current database entry
        """
        return self.filetype.color

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


# Forward ForeignKeys - use select_related() for SQL JOINs (single query)
INDEXDATA_SELECT_RELATED_LIST = [
    "filetype",
    "new_ftnail",
    "home_directory",
]

# Reverse ForeignKeys - use prefetch_related() for separate queries
# Currently empty as IndexData has no reverse relationships in the standard query
INDEXDATA_PREFETCH_LIST = []

# Minimal select_related for downloads - filetype and home_directory needed
INDEXDATA_DOWNLOAD_SELECT_RELATED_LIST = [
    "filetype",
    "home_directory",
]


class IndexData(models.Model):
    """
    The Master Index for All files in the Gallery.  (See IndexDirs for the counterpart
    for Directories)

    The file_sha256 is the Sha256 of the file itself, and can be used to help eliminate multiple
    thumbnails being created for the same file.

    The unique_sha256 is the sha256 of the file + the fully qualified pathname of the file.
    The unique sha256 is the eventual replacement for the UUID.  The idea is that a regeneration of the
    database does not destroy the valid identifiers for the files.  The UUID works as an unique identifier,
    but is randomly generated, which means that it can't be regenerated after a database regeneration, or
    if the database record is deleted, and then recreated.  Where the unique_sha256 can be, as long as the
    file & file path is the same and unchanged.
    """

    id = models.AutoField(primary_key=True)

    file_sha256 = models.CharField(
        db_index=True,
        blank=True,
        unique=False,
        null=True,
        default=None,
        max_length=64,
    )  # This is the sha256 of the file itself
    unique_sha256 = models.CharField(
        db_index=True,
        blank=True,
        unique=True,
        null=True,
        default=None,
        max_length=64,
    )  # This is the sha256 of the (file + fqfn)

    lastscan = models.FloatField(db_index=True)  # Stored as Unix timestamp (seconds)
    lastmod = models.FloatField(db_index=True)  # Stored as Unix timestamp (seconds)
    name = models.CharField(db_index=True, max_length=384, default=None)
    # FQFN of the file itself
    name_sort = NaturalSortField(for_field="name", max_length=384, default="")
    duration = models.BigIntegerField(null=True)
    size = models.BigIntegerField(default=0)  # File size

    home_directory = models.ForeignKey(
        "IndexDirs",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        related_name="IndexData_entries",
    )
    virtual_directory = models.ForeignKey(
        "IndexDirs",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        related_name="Virtual_IndexData",
    )
    is_animated = models.BooleanField(default=False, db_index=True)
    ignore = models.BooleanField(default=False, db_index=True)  # File is to be ignored
    delete_pending = models.BooleanField(default=False, db_index=True)  # File is to be deleted,
    cover_image = models.BooleanField(default=False, db_index=True)  # This image is the directory placard
    filetype = models.ForeignKey(
        filetypes,
        to_field="fileext",
        on_delete=models.CASCADE,
        db_index=True,
        default=".none",
        related_name="file_filetype_data",
    )
    is_generic_icon = models.BooleanField(default=False, db_index=True)  # icon is a generic icon

    new_ftnail = models.ForeignKey(
        ThumbnailFiles,
        on_delete=models.SET_NULL,
        blank=True,
        default=None,
        null=True,
        related_name="IndexData",
    )

    # https://stackoverflow.com/questions/38388423

    ownership = models.OneToOneField(
        Owners,
        on_delete=models.CASCADE,
        db_index=True,
        default=None,
        null=True,
        blank=True,
    )

    # Reverse relationships
    dir_thumbnail: "models.manager.RelatedManager[IndexDirs]"  # From IndexDirs.thumbnail
    file_links: "models.manager.RelatedManager[IndexDirs]"  # From IndexDirs.file_links (ManyToMany)

    @property
    def fqpndirectory(self) -> str:
        """
        Return the fully qualified pathname of the directory containing this file
        Returns: String representing the directory path from the parent IndexDirs object
        """
        return self.home_directory.fqpndirectory

    @property
    def full_filepathname(self) -> str:
        """
        Return the complete file path including directory and filename
        Returns: String representing the full file path by concatenating directory + filename
        """
        return self.fqpndirectory + self.name

    @staticmethod
    def return_identical_files_count(sha: str) -> int:
        """
        Return the number of identical files in the database
        Returns: Integer - Number of identical files
        """
        return IndexData.objects.filter(file_sha256=sha).count()

    @staticmethod
    def return_list_all_identical_files_by_sha(sha: str) -> "QuerySet[IndexData]":
        """
        Return a query of all duplicate files based on file SHA256 hash

        Args:
            sha: The SHA256 hash of the file to find duplicates for

        Returns:
            QuerySet containing summary data (file_sha256 + count) using .values()
            and .annotate() for files with 2+ duplicates
        """
        dupes = (
            IndexData.objects.filter(file_sha256=sha)
            .values("file_sha256")
            .annotate(dupe_count=Count("file_sha256"))
            .exclude(dupe_count__lt=2)
            .order_by("-dupe_count")
        )
        return dupes

    @staticmethod
    def get_identical_file_entries_by_sha(sha: str) -> "QuerySet[dict[str, Any]]":
        """
        Get file entries for identical files based on SHA256 hash

        Args:
            sha: The SHA256 hash of the file to search for

        Returns:
            QuerySet with dictionary-like data containing only name and directory
            fields using .values() for identical files
        """
        return IndexData.objects.values("name", "home_directory__fqpndirectory").filter(file_sha256=sha)

    @cached(indexdata_cache)
    @staticmethod
    def get_by_filters(
        additional_filters: dict[str, Any] | None = None,
    ) -> "QuerySet[IndexData]":
        """
        Return the files in the current directory, filtered by additional filters

        Args:
            additional_filters: Additional filters to apply to the query

        Returns: The filtered query of files
        """
        if additional_filters is None:
            additional_filters = {}
        return IndexData.objects.select_related(*INDEXDATA_SELECT_RELATED_LIST).filter(delete_pending=False, **additional_filters)

    @staticmethod
    def return_by_sha256_list(sha256_list: list[str], sort: int = 0) -> "QuerySet[IndexData]":
        """
        Return files matching the provided SHA256 list

        Args:
            sha256_list: List of file SHA256 hashes to filter by
            sort: The sort order of the files (0-2)

        Returns: The sorted query of files matching the SHA256 list
        """
        # necessary to prevent circular references on startup
        # pylint: disable-next=import-outside-toplevel
        from frontend.utilities import SORT_MATRIX

        files = (
            IndexData.objects.select_related(*INDEXDATA_SELECT_RELATED_LIST)
            .filter(file_sha256__in=sha256_list, delete_pending=False)
            .order_by(*SORT_MATRIX[sort])
        )
        return files

    @cached(indexdata_cache)
    @staticmethod
    def get_by_sha256(sha_value: str, unique: bool = False) -> IndexData | None:
        """
        Return the IndexData object by SHA256

        Args:
            sha_value: The SHA256 of the IndexData object
            unique: If True, search by unique_sha256, otherwise by file_sha256

        Returns: IndexData object or None if not found
        """
        try:
            if unique:
                return IndexData.objects.select_related(*INDEXDATA_SELECT_RELATED_LIST).get(unique_sha256=sha_value, delete_pending=False)
            return IndexData.objects.select_related(*INDEXDATA_SELECT_RELATED_LIST).get(file_sha256=sha_value, delete_pending=False)
        except IndexData.DoesNotExist:
            return None

    @cached(indexdata_download_cache)
    @staticmethod
    def get_by_sha256_for_download(sha_value: str, unique: bool = False) -> IndexData | None:
        """
        Return the IndexData object by SHA256 optimized for file downloads.

        Uses select_related for forward FKs and .only() to fetch minimal fields
        for maximum performance with high concurrency.

        Args:
            sha_value: The SHA256 of the IndexData object
            unique: If True, search by unique_sha256, otherwise by file_sha256

        Returns: IndexData object or None if not found
        """
        try:
            # Determine which SHA field to filter on
            filter_field = "unique_sha256" if unique else "file_sha256"

            # Only fetch fields needed for download
            return (
                IndexData.objects.select_related("filetype", "home_directory")
                .only(
                    "name",
                    "filetype__mimetype",
                    "filetype__is_movie",
                    "home_directory__fqpndirectory",
                )
                .get(**{filter_field: sha_value, "delete_pending": False})
            )
        except IndexData.DoesNotExist:
            return None

    def get_file_sha(self, fqfn: str) -> tuple[str | None, str | None]:
        """
        Return the SHA256 hashes of the file as hexdigest strings.

        This is a convenience wrapper method that provides instance-based access
        to the centralized SHA256 hashing implementation in quickbbs.common.
        It delegates all hashing logic to quickbbs.common.get_file_sha().

        Args:
            fqfn: The fully qualified filename of the file to be hashed

        Returns:
            Tuple of (file_sha256, unique_sha256) where file_sha256 is the hash
            of the file contents and unique_sha256 is the hash of the file
            contents + fqfn
        """
        from quickbbs.common import get_file_sha

        return get_file_sha(fqfn)

    def get_file_counts(self) -> None:
        """
        Stub method to allow the same behavior between a Index_Dir objects and IndexData object.

        Returns: None
        """
        return None

    def get_dir_counts(self) -> None:
        """
        Stub method to allow the same behavior between a Index_Dir objects and IndexData object.

        Returns: None
        """
        return None

    def get_bg_color(self) -> str:
        """
        Get the html / Cell background color of the file.

        Returns
        -------
        * The background hex color code of the current database entry
        """
        return self.filetype.color

    def get_view_url(self) -> str:
        """
        Generate the URL for the viewing of the current database item

        Returns
        -------
            Django URL object

        """
        return reverse("view_item", args=(self.unique_sha256,))

    def get_thumbnail_url(self, size: str | None = None) -> str:
        """
        Generate the URL for the thumbnail of the current item

        Returns
        -------
            Django URL object

        """
        if size not in settings.IMAGE_SIZE and size is not None:
            size = None
        if size is None:
            size = "small"
        size = size.lower()
        if self.virtual_directory:
            return self.virtual_directory.get_thumbnail_url(size=size)
        url = reverse(r"thumbnail2_file", args=(self.file_sha256,)) + f"?size={size}"
        return url

    def get_download_url(self) -> str:
        """
        Generate the URL for the downloading of the current database item

        Returns
        -------
            Django URL object

        """
        return reverse("download_file") + self.name + f"?usha={self.unique_sha256}"

    def inline_sendfile(self, request: Any, ranged: bool = False) -> Any:
        """
        Helper function to send data to remote - matches original fast implementation.

        Loads entire file into memory for non-ranged requests (fast for small files,
        benefits from OS caching on repeated reads).

        Uses HttpResponse for non-ranged, RangedFileResponse for ranged (videos).
        """
        mtype = self.filetype.mimetype or "application/octet-stream"
        fqpn_filename = self.full_filepathname

        if not ranged:
            # Load entire file into memory - matches old fast code
            try:
                with open(fqpn_filename, "rb") as fh:
                    response = HttpResponse(fh.read(), content_type=mtype)
                    response["Content-Disposition"] = f"inline; filename={self.name}"
                    response["Cache-Control"] = "public, max-age=300"
            except FileNotFoundError as exc:
                raise Http404 from exc
        else:
            # Ranged request for video streaming
            try:
                response = RangedFileResponse(
                    request,
                    file=open(fqpn_filename, "rb"),  # pylint: disable=consider-using-with
                    as_attachment=False,
                    filename=self.name,
                )
                response["Cache-Control"] = "public, max-age=300"
            except FileNotFoundError as exc:
                raise Http404 from exc
        response["Content-Type"] = mtype
        return response

    async def async_inline_sendfile(self, request: Any, ranged: bool = False) -> Any:
        """
        Helper function to send data to remote (ASGI async version).

        Uses aiofiles for true async file I/O to avoid sync iterator warnings.
        For non-ranged requests, loads file into memory for optimal async serving.
        For ranged requests (videos), uses sync file handle as RangedFileResponse
        requires seekable files.

        Args:
            request: Django request object
            ranged: Whether to support HTTP range requests for video streaming

        Returns:
            FileResponse or RangedFileResponse with file content

        Raises:
            Http404: If file not found
            asyncio.CancelledError: Re-raised if client disconnects (file handle cleaned up)
        """
        import asyncio
        import io

        import aiofiles

        mtype = self.filetype.mimetype or "application/octet-stream"
        fqpn_filename = self.full_filepathname
        file_handle = None

        try:
            if not ranged:
                # Non-ranged: Load file async and serve from memory (eliminates sync iterator warning)
                async with aiofiles.open(fqpn_filename, "rb") as f:
                    content = await f.read()

                response = FileResponse(
                    io.BytesIO(content),
                    content_type=mtype,
                    as_attachment=False,
                    filename=self.name,
                )
            else:
                # Ranged request for video streaming - requires seekable sync file handle
                # RangedFileResponse needs seek() which aiofiles doesn't support
                #
                # IMPORTANT: RangedFileResponse takes ownership of the file handle and closes it
                # when the response completes. Do NOT use context manager (with open()) as it
                # would close the handle prematurely before streaming completes.
                #
                # Handle lifecycle:
                # - Normal operation: RangedFileResponse closes handle when streaming completes
                # - Errors: Exception handlers below close handle (FileNotFoundError, CancelledError)
                # - Concurrent streams: 50+ simultaneous open handles is safe (system limit ~1024)
                def _open_file():
                    return open(fqpn_filename, "rb")

                file_handle = await sync_to_async(_open_file)()
                response = RangedFileResponse(
                    request,
                    file=file_handle,
                    as_attachment=False,
                    filename=self.name,
                )
                response["Content-Type"] = mtype

            response["Cache-Control"] = "public, max-age=300"
            return response

        except FileNotFoundError as exc:
            # Clean up file handle if opened
            if file_handle is not None:
                file_handle.close()
            raise Http404 from exc
        except asyncio.CancelledError:
            # Client disconnected - clean up file handle if opened
            if file_handle is not None:
                file_handle.close()
            # Re-raise to let Django handle the cancellation
            raise

    class Meta:
        verbose_name = "Master Files Index"
        verbose_name_plural = "Master Files Index"
        indexes = [
            models.Index(fields=["home_directory", "delete_pending"]),
            models.Index(fields=["file_sha256", "delete_pending"]),
            models.Index(fields=["unique_sha256", "delete_pending"]),
            models.Index(fields=["name"], name="quickbbs_indexdata_name_idx"),
        ]

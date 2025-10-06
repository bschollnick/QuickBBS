"""
Django Models for quickbbs
"""

# Standard library imports
import logging
import os
import pathlib
import time
from typing import Any, Union

# Third-party imports
from asgiref.sync import sync_to_async
from cachetools import LRUCache, cached

# Django imports
from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Count, Prefetch, Q
from django.db.models.query import QuerySet
from django.http import HttpResponse
from django.urls import reverse

# Local application imports
from filetypes.models import filetypes, get_ftype_dict
from frontend.serve_up import async_send_file_response
from thumbnails.models import ThumbnailFiles

from quickbbs.common import get_dir_sha, normalize_fqpn
from quickbbs.natsort_model import NaturalSortField

from ranged_fileresponse import RangedFileResponse

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

    class Meta:
        verbose_name = "Ownership"
        verbose_name_plural = "Ownership"


class Favorites(models.Model):
    """
    Start of setting up a users based favorites for gallery items
    """

    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=None, null=True, editable=False, blank=True, db_index=True)


INDEXDIRS_PREFETCH_LIST = [
    "IndexData_entries",
    # "file_links",
    # "thumbnail",
    "filetype",
    # "parent_directory",
    #    "file_links",
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
        on_delete=models.CASCADE,
        related_name="dir_thumbnail",
        null=True,
        default=None,
    )
    file_links = models.ManyToManyField(
        "IndexData",
        default=None,
        related_name="file_links",
    )

    class Meta:
        verbose_name = "Master Directory Index"
        verbose_name_plural = "Master Directory Index"
        indexes = [
            models.Index(fields=["parent_directory", "delete_pending"]),
            models.Index(fields=["dir_fqpn_sha256", "delete_pending"]),
        ]

    @staticmethod
    def add_directory(fqpn_directory: str, thumbnail: bytes = b"") -> tuple[bool, "IndexDirs"]:
        """
        Create a new directory entry or get existing one

        Args:
            fqpn_directory: The fully qualified pathname for the directory
            thumbnail: thumbnail image to store for the thumbnail/cover art

        Returns:
            Database record
        """
        from django.conf import settings

        # Normalize once and compute SHA once
        fqpn_directory = normalize_fqpn(fqpn_directory)
        dir_sha256 = get_dir_sha(fqpn_directory)

        # Cache the albums path check
        albums_path_lower = os.path.join(settings.ALBUMS_PATH, "albums").lower()
        is_in_albums = fqpn_directory.lower().startswith(albums_path_lower)

        # Determine parent directory link
        if is_in_albums:
            parent_dir = normalize_fqpn(str(pathlib.Path(fqpn_directory).parent))
            parent_sha = get_dir_sha(parent_dir)
            found, parent_dir_link = IndexDirs.search_for_directory_by_sha(parent_sha)

            if not found and parent_dir.lower().startswith(albums_path_lower):
                print("Trying to create parent directory: ", parent_dir)
                # If the parent directory is not found, create it
                _, parent_dir_link = IndexDirs.add_directory(parent_dir)
        else:
            parent_dir_link = None

        # Prepare the defaults for fields that should be set on creation
        print("Parent Directory Link: ", parent_dir_link)

        # Use single stat call for both exists check and mtime
        dir_path = pathlib.Path(fqpn_directory)
        try:
            stat_info = dir_path.stat()
        except (FileNotFoundError, OSError):
            return (False, IndexDirs.objects.none)

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

    def get_dir_sha(self) -> str:
        """
        Return the SHA256 hash of the directory as a hexdigest string

        Returns:
            The SHA256 hash of the directory's fully qualified pathname
        """
        return get_dir_sha(self.fqpndirectory)

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

    def do_files_exist(self, additional_filters: Union[dict[str, Any], None] = None) -> bool:
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

    def return_parent_directory(self) -> Union["IndexDirs", None]:
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
        try:
            record = IndexDirs.objects.prefetch_related(*INDEXDIRS_PREFETCH_LIST).get(
                dir_fqpn_sha256=sha_256,
                delete_pending=False,
            )
            return (True, record)
        except IndexDirs.DoesNotExist:
            return (False, IndexDirs.objects.none())  # return an empty query set

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
            IndexDirs.objects.prefetch_related(*INDEXDIRS_PREFETCH_LIST)
            .filter(dir_fqpn_sha256__in=sha256_list)
            .filter(delete_pending=False)
            .order_by(*SORT_MATRIX[sort])
        )
        return dirs

    def files_in_dir(self, sort: int = 0, additional_filters: Union[dict[str, Any], None] = None) -> "QuerySet[IndexData]":
        """
        Return the files in the current directory

        Args:
            sort: The sort order of the files (0-2)
            additional_filters: Additional Django ORM filters to apply (e.g., filetype, status filters)

        Returns: The sorted query of files
        """
        # necessary to prevent circular references on startup
        # pylint: disable-next=import-outside-toplevel
        from frontend.utilities import SORT_MATRIX

        if additional_filters is None:
            additional_filters = {}

        files = (
            self.IndexData_entries.prefetch_related(
                "filetype",
            )
            .filter(delete_pending=False, **additional_filters)
            .order_by(*SORT_MATRIX[sort])
        )
        return files

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

    @cached(indexdirs_cache)
    def return_identifier(self) -> str:
        """
        Return the unique identifier for the directory
        Returns: The SHA256 hash of the directory's fully qualified pathname
        """
        return self.dir_fqpn_sha256

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


INDEXDATA_PREFETCH_LIST = [
    "filetype",
    "new_ftnail",
    "home_directory",
    # "IndexDirs_entries",
    # "dir_thumbnail",
    # "file_links",
]

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

    lastscan = models.FloatField(db_index=True)
    # Stored as Unix TimeStamp (ms)
    lastmod = models.FloatField(db_index=True)  # Stored as Unix TimeStamp (ms)
    # Stored as Unix TimeStamp (ms)
    name = models.CharField(db_index=True, max_length=384, default=None)
    # FQFN of the file itself
    name_sort = NaturalSortField(for_field="name", max_length=384, default="")
    duration = models.BigIntegerField(null=True)
    size = models.BigIntegerField(default=0)  # File size

    home_directory = models.ForeignKey(
        "IndexDirs",
        on_delete=models.CASCADE,
        null=True,
        default=None,
        related_name="IndexData_entries",
    )
    virtual_directory = models.ForeignKey(
        "IndexDirs",
        on_delete=models.CASCADE,
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

    # dir_sha256 = models.CharField(db_index=True, blank=True,
    #                               unique=True, null=True,
    #                               default=None, max_length=64)
    #
    # Replaced By:
    # file_links - Reverse Foreignkey from IndexDirs

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

    def update_or_create_file(self, fs_record: dict[str, Any], unique_file_sha256: str, dir_sha256: str) -> tuple[bool, "IndexData"]:
        """
        Add a file to the database, or update an existing file.
            fs_record: Dictionary with file information, including:
            - name: The name of the file
            - size: The size of the file
            - lastmod: The last modified time of the file
            - file_sha256: The SHA256 hash of the file
            - unique_sha256: The unique SHA256 hash of the file + fqfn
            - is_animated: Whether the file is animated (e.g., GIF)
            - ignore: Whether to ignore this file
            - delete_pending: Whether this file is pending deletion
            - cover_image: Whether this image is a cover image for the directory
            - filetype: The type of the file (e.g., .jpg, .mp4)

        Args:
            unique_file_sha256: The unique SHA256 hash of the file (unused parameter)
            dir_sha256: The SHA256 hash of the directory containing the file (legacy parameter)

        Returns: Tuple (found, new_rec) where found is a boolean indicating if the record was found,
                 and new_rec is the IndexData object.
        """
        defaults = {
            "name": fs_record["name"],
            "fqpndirectory": normalize_fqpn(fs_record["fqpndirectory"]),
            "size": int(fs_record["size"]),
            "lastmod": float(fs_record["lastmod"]),
            "file_sha256": fs_record.get("file_sha256", None),
            "unique_sha256": fs_record.get("unique_sha256", None),
            "is_animated": bool(fs_record.get("is_animated", False)),
            "ignore": bool(fs_record.get("ignore", False)),
            "delete_pending": bool(fs_record.get("delete_pending", False)),
            "index_image": bool(fs_record.get("index_image", False)),
            "filetype": fs_record["filetype"],
            "dir_sha256": dir_sha256,
        }

        # Create or update the IndexData record
        new_rec, created = IndexData.objects.update_or_create(
            unique_sha256=defaults["unique_sha256"],
            defaults=defaults,
            create_defaults=defaults,
        )
        found = not created
        return found, new_rec

    def return_unique_identifier(self) -> str:
        """
        Return the unique identifier for the file
        Returns: The unique SHA256 hash of the file + fully qualified filename
        """
        return self.unique_sha256

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

        Returns: QuerySet containing summary data (file_sha256 + count) using .values() and .annotate() for files with 2+ duplicates
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

        Returns: QuerySet with dictionary-like data containing only name and directory fields using .values() for identical files
        """
        return IndexData.objects.values("name", "home_directory__fqpndirectory").filter(file_sha256=sha)

    @cached(indexdata_cache)
    @staticmethod
    def get_by_filters(
        additional_filters: Union[dict[str, Any], None] = None,
    ) -> "QuerySet[IndexData]":
        """
        Return the files in the current directory, filtered by additional filters

        Args:
            additional_filters: Additional filters to apply to the query

        Returns: The filtered query of files
        """
        if additional_filters is None:
            additional_filters = {}
        return IndexData.objects.prefetch_related(*INDEXDATA_PREFETCH_LIST).filter(delete_pending=False, **additional_filters)

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
            IndexData.objects.prefetch_related(*INDEXDATA_PREFETCH_LIST)
            .filter(file_sha256__in=sha256_list, delete_pending=False)
            .order_by(*SORT_MATRIX[sort])
        )
        return files

    @cached(indexdata_cache)
    @staticmethod
    def get_by_sha256(sha_value: str, unique: bool = False) -> Union["IndexData", None]:
        """
        Return the IndexData object by SHA256

        Args:
            sha_value: The SHA256 of the IndexData object
            unique: If True, search by unique_sha256, otherwise by file_sha256

        Returns: IndexData object or None if not found
        """
        try:
            if unique:
                return IndexData.objects.prefetch_related(*INDEXDATA_PREFETCH_LIST).get(unique_sha256=sha_value, delete_pending=False)
            return IndexData.objects.prefetch_related(*INDEXDATA_PREFETCH_LIST).get(file_sha256=sha_value, delete_pending=False)
        except IndexData.DoesNotExist:
            return None

    @cached(indexdata_download_cache)
    @staticmethod
    def get_by_sha256_for_download(sha_value: str, unique: bool = False) -> Union["IndexData", None]:
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
            # Only fetch fields needed for download: name, filetype.mimetype, filetype.is_movie, home_directory.fqpndirectory
            if unique:
                return (IndexData.objects
                    .select_related("filetype", "home_directory")
                    .only("name", "filetype__mimetype", "filetype__is_movie", "home_directory__fqpndirectory")
                    .get(unique_sha256=sha_value, delete_pending=False))
            else:
                return (IndexData.objects
                    .select_related("filetype", "home_directory")
                    .only("name", "filetype__mimetype", "filetype__is_movie", "home_directory__fqpndirectory")
                    .get(file_sha256=sha_value, delete_pending=False))
        except IndexData.DoesNotExist:
            return None


    def get_file_sha(self, fqfn: str) -> tuple[str | None, str | None]:
        """
        Return the SHA256 hashes of the file as hexdigest strings.

        Delegates to the centralized implementation in quickbbs.common.

        Args:
            fqfn: The fully qualified filename of the file to be hashed

        Returns:
            Tuple of (file_sha256, unique_sha256) where file_sha256 is the hash
            of the file contents and unique_sha256 is the hash of the file
            contents + fqfn
        """
        from quickbbs.common import get_file_sha

        return get_file_sha(fqfn)

    def get_webpath(self) -> str:
        """
        Convert the fqpndirectory to an web path
        Returns:
        """
        return self.fqpndirectory.removeprefix(IndexDirs.get_albums_prefix())

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
        # options = {}
        # parameters = []
        return reverse("view_item", args=(self.unique_sha256,))

    def get_thumbnail_url(self, size: Union[str, None] = None) -> str:
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

        mtype = self.filetype.mimetype
        if mtype is None:
            mtype = "application/octet-stream"
        fqpn_filename = self.full_filepathname

        if not ranged:
            # Load entire file into memory - matches old fast code
            try:
                with open(fqpn_filename, "rb") as fh:
                    response = HttpResponse(fh.read(), content_type=mtype)
                    response["Content-Disposition"] = f"inline; filename={self.name}"
                    response["Cache-Control"] = "public, max-age=300"
            except FileNotFoundError:
                raise Http404
        else:
            # Ranged request for video streaming
            try:
                response = RangedFileResponse(
                    request,
                    file=open(fqpn_filename, "rb"),
                    as_attachment=False,
                    filename=self.name,
                )
                response["Cache-Control"] = "public, max-age=300"
            except FileNotFoundError:
                raise Http404
        response["Content-Type"] = mtype
        return response

    async def async_inline_sendfile(self, request: Any, ranged: bool = False) -> Any:
        """
        Helper function to send data to remote (ASGI async version).

        Uses aiofiles to open file handle asynchronously, avoiding sync iterator warnings.

        :Args:
            request: Django request object
            ranged: Whether to support HTTP range requests for video streaming

        :Return:
            HttpResponse with async file content
        """
        start = time.perf_counter()

        mtype = self.filetype.mimetype
        if mtype is None:
            mtype = "application/octet-stream"
        fqpn_filename = self.full_filepathname

        if not ranged:
            # Use sync file I/O in thread pool - faster than aiofiles for OS-cached files
            def _read_file():
                with open(fqpn_filename, "rb", buffering=8196) as fh:
                    return fh.read()

            try:
                start_file = time.perf_counter()
                content = await sync_to_async(_read_file)()
                file_time = (time.perf_counter() - start_file) * 1000

                response = HttpResponse(content, content_type=mtype)
                response["Content-Disposition"] = f"inline; filename={self.name}"
                response["Cache-Control"] = "public, max-age=300"
                response["Content-Type"] = mtype

                total_time = (time.perf_counter() - start) * 1000
                logger.info("[PERF] async_inline_sendfile: file read=%.2fms, total=%.2fms", file_time, total_time)
                return response
            except FileNotFoundError:
                raise Http404
        else:
            # Ranged request for video streaming
            result = await async_send_file_response(
                request=request,
                filename=self.name,
                filepath=fqpn_filename,
                mtype=mtype or "image/jpeg",
                attachment=False,
                expiration=300,
            )
            total_time = (time.perf_counter() - start) * 1000
            logger.info("[PERF] async_inline_sendfile (ranged): %.2fms", total_time)
            return result

    class Meta:
        verbose_name = "Master Files Index"
        verbose_name_plural = "Master Files Index"
        indexes = [
            models.Index(fields=["home_directory", "delete_pending"]),
            models.Index(fields=["file_sha256", "delete_pending"]),
            models.Index(fields=["unique_sha256", "delete_pending"]),
            models.Index(fields=["name"], name="quickbbs_indexdata_name_idx"),
        ]

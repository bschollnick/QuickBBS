"""
FileIndex Model - Master index for all files in the gallery
"""

from __future__ import annotations

import logging
import os
import platform
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

from asgiref.sync import sync_to_async
from cachetools.keys import hashkey
from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction
from django.db.models import Count
from django.db.models.query import QuerySet
from django.http import FileResponse, Http404
from django.urls import reverse

from filetypes.models import filetypes
from frontend.serve_up import sanitize_filename_for_http
from quickbbs.common import (
    SORT_MATRIX,
    get_file_sha,
    normalize_fqpn,
    normalize_string_title,
)
from quickbbs.MonitoredCache import create_cache
from quickbbs.natsort_model import NaturalSortField
from thumbnails.exceptions import MediaProcessingError
from thumbnails.models import ThumbnailFiles

# Lazy-loaded video info function — AVFoundation/ffmpeg imports are deferred to first call.
# Prefer AVFoundation on macOS for video metadata (no subprocess spawn, ~10x faster).
# Fall back to ffmpeg-based probe on other platforms.
# invalid-name disabled: pylint sees a module-level assignment and expects UPPER_CASE,
# but this is a mutable cache slot for the resolved backend, not a constant.
_get_video_info_impl = None  # pylint: disable=invalid-name


def _get_video_info(path: str) -> dict:
    """Get video metadata. Lazily imports the appropriate backend on first call.

    Args:
        path: Fully qualified path to the video file.

    Returns:
        Dictionary containing video metadata (duration, width, height, fps,
        codec, format).

    Raises:
        MediaProcessingError: If neither backend can extract metadata from the file.
    """
    global _get_video_info_impl
    if _get_video_info_impl is None:
        if platform.system() == "Darwin":
            try:
                # Deferred: pyobjc/AVFoundation is macOS-only and expensive to import —
                # loaded on first video-metadata call, never at module import time.
                # pylint: disable-next=import-outside-toplevel
                from thumbnails.avfoundation_video_thumbnails import (
                    _get_video_info as _avf_get_video_info,
                )

                _get_video_info_impl = _avf_get_video_info
            except ImportError:
                pass
        if _get_video_info_impl is None:
            # Deferred: ffmpeg probe fallback, only loaded when AVFoundation is unavailable.
            # pylint: disable-next=import-outside-toplevel
            from thumbnails.video_thumbnails import (
                _get_video_info as _ffmpeg_get_video_info,
            )

            _get_video_info_impl = _ffmpeg_get_video_info
    try:
        return _get_video_info_impl(path)
    except MediaProcessingError:
        # AVFoundation has no decoder for some containers/codecs (e.g. WMV,
        # FLV, MPEG-1) and reports "No video tracks found" for them. Retry
        # with the ffmpeg probe, which supports those formats. If the resolved
        # backend already IS the ffmpeg probe, there is nothing to fall back
        # to — re-raise for the caller to log.
        # pylint: disable-next=import-outside-toplevel
        from thumbnails.video_thumbnails import (
            _get_video_info as _ffmpeg_get_video_info,
        )

        if _get_video_info_impl is _ffmpeg_get_video_info:
            raise
        return _ffmpeg_get_video_info(path)


# Cyclic import: .models imports from .fileindex, so this must come after the
# module-level code above to avoid an ImportError at load time.
from .models import Owners  # noqa: E402  # pylint: disable=wrong-import-position

logger = logging.getLogger(__name__)

# Async-safe caches for database object lookups
fileindex_cache = create_cache(settings.FILEINDEX_CACHE_SIZE, "fileindex", monitored=settings.CACHE_MONITORING)
fileindex_download_cache = create_cache(settings.FILEINDEX_DOWNLOAD_CACHE_SIZE, "fileindex_download", monitored=settings.CACHE_MONITORING)

if TYPE_CHECKING:
    from django.db.models.fields.related_descriptors import RelatedManager

    from .directoryindex import DirectoryIndex


# =============================================================================
# FILEINDEX SELECT_RELATED CONSTANTS
# Colocated with FileIndex class for use by class methods and external callers
# See related_fetches.md for usage details
# NOTE: Using tuples (not lists) so they can be used as cache keys (hashable)
# =============================================================================

# Full - gallery display with link support
FILEINDEX_SR_FILETYPE_HOME_VIRTUAL = ("filetype", "home_directory", "virtual_directory")

# For downloads and file lists
FILEINDEX_SR_FILETYPE_HOME = ("filetype", "home_directory")

# For thumbnail view (needs filetype and virtual_directory for links)
FILEINDEX_SR_FILETYPE_VIRTUAL = ("filetype", "virtual_directory")

# For cache invalidation only
FILEINDEX_SR_HOME = ("home_directory",)

# For filetype checks only
FILEINDEX_SR_FILETYPE = ("filetype",)


class FileIndex(models.Model):
    """
    The Master Index for All files in the Gallery.  (See DirectoryIndex for the counterpart
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

    # Class-level caches for improved performance
    _encoding_cache = create_cache(settings.ENCODING_CACHE_SIZE, "encoding", monitored=settings.CACHE_MONITORING)
    _markdown_processor = None  # Lazy-initialized on first use
    _alias_cache = create_cache(settings.ALIAS_CACHE_SIZE, "alias", monitored=settings.CACHE_MONITORING)

    id = models.AutoField(primary_key=True)

    file_sha256 = models.CharField(
        blank=True,
        unique=False,
        null=True,
        default=None,
        max_length=64,
    )  # This is the sha256 of the file itself (indexed via Meta composite indexes)
    unique_sha256 = models.CharField(
        db_index=True,
        blank=True,
        unique=True,
        null=True,
        default=None,
        max_length=64,
    )  # This is the sha256 of the (file + fqfn)

    # lastscan/lastmod are never filtered or ordered on standalone (sorts always
    # follow a home_directory filter), so they carry no index — this also allows
    # HOT updates for the common mtime/size-only sync change.
    lastscan = models.FloatField()  # Stored as Unix timestamp (seconds)
    lastmod = models.FloatField()  # Stored as Unix timestamp (seconds)
    name = models.CharField(max_length=384, default=None)  # indexed via Meta indexes (btree + trigram)
    # FQFN of the file itself
    # db_index=False: name_sort is only used in ORDER BY after a home_directory
    # filter — a global index on it was never scanned (pg_stat, 2026-07-04).
    name_sort = NaturalSortField(for_field="name", max_length=384, default="", db_index=False)
    duration = models.BigIntegerField(null=True)
    size = models.BigIntegerField(default=0)  # File size

    home_directory = models.ForeignKey(
        "DirectoryIndex",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        related_name="FileIndex_entries",
    )
    virtual_directory = models.ForeignKey(
        "DirectoryIndex",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        related_name="Virtual_FileIndex",
    )
    is_animated = models.BooleanField(default=False)  # read as attribute, never filtered
    ignore = models.BooleanField(default=False)  # File is to be ignored
    # delete_pending=True rows are found via the partial fileindex_delete_pending_idx
    # (Meta.indexes); delete_pending=False predicates ride the composite indexes.
    delete_pending = models.BooleanField(default=False)  # File is to be deleted,
    cover_image = models.BooleanField(default=False)  # This image is the directory placard
    filetype = models.ForeignKey(
        filetypes,
        to_field="fileext",
        on_delete=models.CASCADE,
        # db_index=False: fileindex_filetype_delete_idx leads on filetype_id and
        # covers both query and FK-cascade lookups.
        db_index=False,
        default=".none",
        related_name="file_filetype_data",
    )
    is_generic_icon = models.BooleanField(default=False)  # icon is a generic icon

    new_ftnail = models.ForeignKey(
        ThumbnailFiles,
        on_delete=models.SET_NULL,
        blank=True,
        default=None,
        null=True,
        related_name="FileIndex",
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
    dir_thumbnail: "RelatedManager[DirectoryIndex]"  # From DirectoryIndex.thumbnail

    @property
    def fqpndirectory(self) -> str:
        """
        Return the fully qualified pathname of the directory containing this file
        Returns: String representing the directory path from the parent DirectoryIndex object
        Raises: ValueError if home_directory is None (orphaned record)
        """
        if self.home_directory is None:
            raise ValueError(
                f"FileIndex record (id={self.id}, sha256={self.file_sha256}) has no home_directory. "
                f"This indicates an orphaned record whose parent directory was deleted."
            )
        return self.home_directory.fqpndirectory

    @property
    def full_filepathname(self) -> str:
        """
        Return the complete file path including directory and filename
        Returns: String representing the full file path by concatenating directory + filename
        Raises: ValueError if home_directory is None (orphaned record)
        """
        return self.fqpndirectory + self.name

    @staticmethod
    def return_identical_files_count(sha: str) -> int:
        """
        Return the number of identical files in the database

        Benchmark-only — no production callers as of 2026-07-06.

        Returns: Integer - Number of identical files
        """
        return FileIndex.objects.filter(file_sha256=sha).count()

    @staticmethod
    def return_list_all_identical_files_by_sha(sha: str) -> "QuerySet[FileIndex, dict[str, Any]]":
        """
        Return a query of all duplicate files based on file SHA256 hash.

        .. note::
            **Prototype — not used in production code.**
            This function is only called from benchmarks and tests. The query
            structure (filter to one SHA, group by that SHA, annotate count) can
            return at most one summary row, making the `.values()/.annotate()`
            approach more complex than necessary. If promoted to production use,
            consider replacing with ``return_identical_files_count(sha) >= 2``
            at the call site, or simplifying the query to a plain filtered
            QuerySet with a count check.

        Args:
            sha: The SHA256 hash of the file to find duplicates for

        Returns:
            QuerySet containing summary data (file_sha256 + dupe_count) using
            .values() and .annotate() for files with 2+ duplicates. Always
            returns zero or one row.
        """
        dupes = (
            FileIndex.objects.filter(file_sha256=sha)
            .values("file_sha256")
            .annotate(dupe_count=Count("file_sha256"))
            .exclude(dupe_count__lt=2)
            .order_by("-dupe_count")
        )
        # cast: django-stubs infers an exact TypedDict row type for
        # .values()/.annotate() which does not unify with dict[str, Any].
        return cast("QuerySet[FileIndex, dict[str, Any]]", dupes)

    @staticmethod
    def get_identical_file_entries_by_sha(sha: str) -> "QuerySet[FileIndex, dict[str, Any]]":
        """
        Get file entries for identical files based on SHA256 hash

        Benchmark-only — no production callers as of 2026-07-06.

        Args:
            sha: The SHA256 hash of the file to search for

        Returns:
            QuerySet with dictionary-like data containing only name and directory
            fields using .values() for identical files
        """
        # cast: django-stubs infers an exact TypedDict row type for .values()
        # which does not unify with dict[str, Any].
        return cast(
            "QuerySet[FileIndex, dict[str, Any]]",
            FileIndex.objects.values("name", "home_directory__fqpndirectory").filter(file_sha256=sha),
        )

    @staticmethod
    def return_by_sha256_list(sha256_list: list[str], sort: int, select_related: list[str]) -> "QuerySet[FileIndex]":
        """
        Return files matching the provided SHA256 list

        Args:
            sha256_list: List of file SHA256 hashes to filter by
            sort: The sort order of the files (0-2)
            select_related: List of related fields to select (required)

        Returns: The sorted query of files matching the SHA256 list
        """
        if select_related is None:
            raise ValueError("select_related parameter is required")
        files = (
            FileIndex.objects.select_related(*select_related).filter(file_sha256__in=sha256_list, delete_pending=False).order_by(*SORT_MATRIX[sort])
        )
        return files

    @staticmethod
    def get_by_sha256(sha_value: str, unique: bool, select_related: list[str] | tuple[str, ...]) -> "FileIndex | None":
        """
        Return the FileIndex object by SHA256.

        Results are cached, but None (not found) is never cached — a missing record
        may be created shortly after (e.g. during thumbnail generation) and a cached
        None would mask it until eviction.

        Args:
            sha_value: The SHA256 of the FileIndex object
            unique: If True, search by unique_sha256 (expects one result),
                    If False, search by file_sha256 (may return first of multiple)
            select_related: Related fields to select (required)

        Returns: FileIndex object or None if not found
        """
        if select_related is None:
            raise ValueError("select_related parameter is required")
        key = hashkey(sha_value, unique, tuple(select_related))
        cached_val = fileindex_cache.get(key)
        if cached_val is not None:
            return cached_val
        result: FileIndex | None
        try:
            if unique:
                result = FileIndex.objects.select_related(*select_related).get(unique_sha256=sha_value, delete_pending=False)
            else:
                # When searching by file_sha256, there may be duplicates - return first
                result = FileIndex.objects.select_related(*select_related).filter(file_sha256=sha_value, delete_pending=False).first()
        except FileIndex.DoesNotExist:
            result = None
        if result is not None:
            fileindex_cache[key] = result
        return result

    @staticmethod
    def get_by_sha256_for_download(sha_value: str, unique: bool, select_related: list[str] | tuple[str, ...]) -> FileIndex | None:
        """
        Return the FileIndex object by SHA256 optimized for file downloads.

        Uses select_related for forward FKs and .only() to fetch minimal fields
        for maximum performance with high concurrency.

        Results are cached, but None (not found) is never cached — a missing
        record may be created shortly after (e.g. during thumbnail generation)
        and a cached None would mask it until eviction. Caching is done manually
        (rather than via @cached) so the key is built from tuple(select_related):
        the default @cached key function folds the select_related argument in
        verbatim, which raises TypeError when a caller passes a list.

        Args:
            sha_value: The SHA256 of the FileIndex object
            unique: If True, search by unique_sha256, otherwise by file_sha256
            select_related: Related fields to select (required)

        Returns: FileIndex object or None if not found
        """
        if select_related is None:
            raise ValueError("select_related parameter is required")
        key = hashkey(sha_value, unique, tuple(select_related))
        cached_val = fileindex_download_cache.get(key)
        if cached_val is not None:
            return cached_val
        # Determine which SHA field to filter on
        filter_field = "unique_sha256" if unique else "file_sha256"
        result: FileIndex | None
        try:
            # Only fetch fields needed for download
            result = (
                FileIndex.objects.select_related(*select_related)
                .only(
                    "name",
                    "filetype__mimetype",
                    "filetype__is_movie",
                    "home_directory__fqpndirectory",
                )
                .get(**{filter_field: sha_value, "delete_pending": False})
            )
        except FileIndex.DoesNotExist:
            result = None
        if result is not None:
            fileindex_download_cache[key] = result
        return result

    @classmethod
    def set_generic_icon_for_sha(cls, file_sha256: str, is_generic: bool, clear_cache: bool = True) -> int:
        """
        Set is_generic_icon for all FileIndex files with the given SHA256.

        Shared function to ensure consistent is_generic_icon updates across:
        - Thumbnail generation (success/failure)
        - Web view error handlers
        - Management commands

        Note: layout_manager_cache is not cleared here because it stores only
        SHA lists and pagination boundaries, which are unaffected by is_generic_icon.
        distinct_files_cache is also unaffected. Only callers that modify actual
        file membership (add/delete/move) need to clear the layout cache.

        Args:
            file_sha256: SHA256 hash of the file(s) to update
            is_generic: New value for is_generic_icon (True = use filetype icon, False = custom thumbnail)
            clear_cache: Whether to clear layout_manager_cache for affected directories (default: True)

        Returns:
            Number of files updated
        """
        # Deferred: quickbbs.cache_registry imports back into this module chain (genuine cycle)
        # pylint: disable-next=import-outside-toplevel
        from quickbbs.cache_registry import clear_layout_cache_for_directories

        # Get directory IDs BEFORE update (same pattern as link_to_thumbnail)
        directory_ids = set()
        if clear_cache:
            # DUPLICATE: this "collect distinct home_directory IDs before update"
            # line is intentionally duplicated in link_to_thumbnail() below (with
            # an added new_ftnail__isnull=True filter). Keep both in sync if the
            # collection logic changes — not extracted to a helper since each is
            # a single line with a different filter.
            directory_ids = set(cls.objects.filter(file_sha256=file_sha256).values_list("home_directory", flat=True).distinct())
            # Remove None values
            directory_ids.discard(None)

        # Update all files with this SHA256
        updated_count = cls.objects.filter(file_sha256=file_sha256).update(is_generic_icon=is_generic)

        # Clear layout cache for affected directories
        if directory_ids and updated_count > 0:
            cleared_count = clear_layout_cache_for_directories(directory_ids)
            if cleared_count > 0:
                logger.info("Cleared %d layout cache entries for %d directories", cleared_count, len(directory_ids))

        return updated_count

    @classmethod
    def link_to_thumbnail(cls, file_sha256: str, thumbnail: ThumbnailFiles) -> tuple[bool, int]:
        """
        Link FileIndex records to a thumbnail file.

        Checks for unlinked FileIndex records with the given SHA256 and links them
        to the provided thumbnail. This ensures all files with the same content
        share the same thumbnail.

        Args:
            file_sha256: SHA256 hash of the file(s) to link
            thumbnail: ThumbnailFiles object to link to

        Returns:
            Tuple of (has_unlinked, updated_count):
                - has_unlinked: Whether there were any unlinked records before update
                - updated_count: Number of records linked
        """
        # Import here to avoid circular dependency
        # pylint: disable-next=import-outside-toplevel
        from quickbbs.cache_registry import clear_layout_cache_for_directories

        # Get affected directories BEFORE updating for cache clearing
        # This also determines if there are any unlinked records (replaces separate .exists() query)
        # DUPLICATE: this "collect distinct home_directory IDs before update"
        # line is intentionally duplicated in set_generic_icon_for_sha() above
        # (without the new_ftnail__isnull=True filter). Keep both in sync if
        # the collection logic changes — not extracted to a helper since each
        # is a single line with a different filter.
        affected_dirs = list(cls.objects.filter(file_sha256=file_sha256, new_ftnail__isnull=True).values_list("home_directory", flat=True).distinct())
        has_unlinked = bool(affected_dirs)

        # Link unlinked records to the thumbnail
        updated_count = 0
        if has_unlinked:

            # Update thumbnail links
            updated_count = cls.objects.filter(
                file_sha256=file_sha256,
                new_ftnail__isnull=True,
            ).update(new_ftnail=thumbnail)

            # Clear layout caches for affected directories
            if affected_dirs and updated_count > 0:
                clear_layout_cache_for_directories(set(affected_dirs))

        return has_unlinked, updated_count

    @classmethod
    def from_filesystem(
        cls,
        fs_entry: Path,
        directory_id: Any | None = None,
        precomputed_sha: tuple[str | None, str | None] | None = None,
    ) -> dict[str, Any] | None:
        """
        Process a file system entry and return a dictionary with file metadata for FileIndex creation.

        This factory method creates metadata dictionaries suitable for bulk_create operations.
        Accepts precomputed SHA256 hashes to enable batch parallel computation for performance.

        Args:
            fs_entry: Path object representing the file
            directory_id: Optional directory identifier for the parent directory (DirectoryIndex instance)
            precomputed_sha: Optional precomputed (file_sha256, unique_sha256) tuple

        Returns:
            Dictionary containing file metadata suitable for FileIndex(**metadata), or None if processing fails
        """
        try:
            # Initialize the record dictionary
            record = {
                "home_directory": directory_id,
                "name": normalize_string_title(fs_entry.name),
                "is_animated": False,
                "file_sha256": None,
                "unique_sha256": None,
                "duration": None,
            }

            # Check if it's a directory first
            if fs_entry.is_dir():
                # Subdirectories are handled by DirectoryIndex.sync_subdirectories(), not here
                return None

            # Extract and normalize file extension
            fileext = (fs_entry.suffix.lower() if fs_entry.suffix else "") or ".none"
            fileext = ".none" if fileext == "." else fileext

            # Check if filetype exists
            if not filetypes.filetype_exists_by_ext(fileext):
                logger.warning("Can't match fileext '%s' with filetypes", fileext)
                return None

            # Use DirEntry's built-in stat cache (already cached from iterdir)
            try:
                fs_stat = fs_entry.stat()
                record.update(
                    {
                        "size": fs_stat.st_size,
                        "lastmod": fs_stat.st_mtime,
                        "lastscan": time.time(),
                        "filetype": filetypes.return_filetype(fileext=fileext),
                    }
                )
            except (OSError, IOError) as e:
                logger.error("Error getting file stats for %s: %s", fs_entry, e)
                return None

            # Handle link files. record is a dict[str, Any]-style mapping, but
            # record["filetype"] is always a filetypes instance (set from
            # return_filetype above); cast so the checker sees the model
            # attributes (is_link/is_image).
            filetype = cast("filetypes", record["filetype"])
            if filetype.is_link:
                # Calculate SHA256 for link files (required for virtual_directory resolution)
                record["file_sha256"], record["unique_sha256"] = get_file_sha(str(fs_entry))
                if record["file_sha256"] is None:
                    logger.error("Error calculating SHA for link file %s", fs_entry)
                    return None

                # Process link file and get virtual_directory
                virtual_dir = cls.process_link_file(fs_entry, filetype, cast("str", record["name"]))
                if virtual_dir is None:
                    return None  # Don't add to database - will retry on next scan

                record["virtual_directory"] = virtual_dir
            else:
                # Use precomputed hash if available, otherwise calculate
                if precomputed_sha:
                    record["file_sha256"], record["unique_sha256"] = precomputed_sha
                else:
                    record["file_sha256"], record["unique_sha256"] = get_file_sha(str(fs_entry))
                    # Continue processing even if SHA calculation fails (returns None, None)

            # Handle animated GIF detection
            if filetype.is_image and fileext == ".gif":
                record["is_animated"] = cls.is_animated_gif(fs_entry)

            return record

        except (OSError, ValueError, AttributeError) as e:
            logger.error("Unexpected error processing %s: %s", fs_entry, e)
            return None

    @classmethod
    def bulk_sync(
        cls,
        records_to_update: list["FileIndex"],
        records_to_create: list["FileIndex"],
        records_to_delete_ids: list[int],
        bulk_size: int,
    ) -> None:
        """
        Execute all database operations in batches with proper transaction handling.

        Performs bulk delete, update, and create operations in separate transactions
        for optimal performance and atomicity.

        Args:
            records_to_update: List of FileIndex records to update
            records_to_create: List of FileIndex records to create
            records_to_delete_ids: List of FileIndex record IDs to delete
            bulk_size: Size of batches for bulk operations

        Raises:
            Exception: If any database operation fails
        """
        # Import here to avoid circular dependency
        # pylint: disable-next=import-outside-toplevel
        from quickbbs.cache_registry import clear_layout_cache_for_directories

        try:
            # Collect affected directory PKs for cache clearing.
            # Use _id suffix to get raw FK integers consistently — avoids
            # mixing DirectoryIndex objects with ints from values_list().
            affected_directory_ids: set[int] = set()

            # Batch delete using IDs with optimized chunking
            if records_to_delete_ids:
                # Convert to list for efficient slicing
                delete_ids_list = list(records_to_delete_ids)

                # Get home directory PKs BEFORE deleting for cache clearing
                deleted_dir_pks = cls.objects.filter(id__in=delete_ids_list).values_list("home_directory_id", flat=True)
                affected_directory_ids.update(pk for pk in deleted_dir_pks if pk is not None)

                with transaction.atomic():
                    # Single DELETE — chunking integer PKs is unnecessary;
                    # PostgreSQL handles large IN lists efficiently.
                    cls.objects.filter(id__in=delete_ids_list).delete()
                    logger.info("Deleted %d records", len(records_to_delete_ids))

            # Batch update in chunks for memory efficiency
            if records_to_update:
                # Collect home directory PKs from updated records
                affected_directory_ids.update(record.home_directory_id for record in records_to_update if record.home_directory_id)

                for i in range(0, len(records_to_update), bulk_size):
                    chunk = records_to_update[i : i + bulk_size]
                    with transaction.atomic():
                        # Dynamic update field selection - only update fields that have changed
                        # is_animated is included unconditionally: check_for_updates() can set
                        # it, and omitting it here silently discards the change in bulk_update.
                        update_fields = ["lastmod", "size", "home_directory", "is_animated"]

                        # Single pass to detect which optional fields need updating
                        has_movies = has_hashes = has_link_with_vdir = False
                        for record in chunk:
                            ft = record.filetype
                            if not has_movies and ft.is_movie and record.duration is not None:
                                has_movies = True
                            if not has_hashes and record.file_sha256:
                                has_hashes = True
                            if not has_link_with_vdir and ft.is_link and record.virtual_directory is not None:
                                has_link_with_vdir = True
                            if has_movies and has_hashes and has_link_with_vdir:
                                break

                        if has_movies:
                            update_fields.append("duration")
                        if has_hashes:
                            update_fields.extend(["file_sha256", "unique_sha256"])
                        if has_link_with_vdir:
                            update_fields.append("virtual_directory")

                        # FileIndex.objects (not cls.objects): chunk is typed
                        # list[FileIndex], which does not satisfy the manager's
                        # Iterable[Self] under a subclass-bound cls.
                        FileIndex.objects.bulk_update(
                            chunk,
                            fields=update_fields,
                            batch_size=bulk_size,
                        )
                logger.info("Updated %d records", len(records_to_update))

            # Batch create in chunks for memory efficiency
            if records_to_create:
                # Collect home directory PKs from created records
                affected_directory_ids.update(record.home_directory_id for record in records_to_create if record.home_directory_id)

                for i in range(0, len(records_to_create), bulk_size):
                    chunk = records_to_create[i : i + bulk_size]
                    with transaction.atomic():
                        # FileIndex.objects (not cls.objects): see bulk_update note above.
                        FileIndex.objects.bulk_create(
                            chunk,
                            batch_size=bulk_size,
                            ignore_conflicts=True,  # Handle duplicates gracefully
                        )
                logger.info("Created %d records", len(records_to_create))

            # Clear layout caches for all affected directories
            if affected_directory_ids:
                cleared_count = clear_layout_cache_for_directories(affected_directory_ids)
                logger.info("Cleared %d layout cache entries for %d affected directories", cleared_count, len(affected_directory_ids))

        except Exception as e:
            logger.error("Database operation failed: %s", e)
            raise

    @classmethod
    def find_files_without_sha(cls, start_path: str | None = None) -> "QuerySet[FileIndex]":
        """
        Find FileIndex files with NULL file_sha256.

        Args:
            start_path: Optional starting directory path to filter files (must be normalized)

        Returns:
            QuerySet of FileIndex files with NULL file_sha256
        """
        files_without_sha = cls.objects.filter(file_sha256__isnull=True, delete_pending=False)

        # Filter by start_path if provided
        if start_path:
            files_without_sha = files_without_sha.filter(home_directory__fqpndirectory__startswith=start_path)

        return files_without_sha

    @classmethod
    def find_broken_link_files(cls, start_path: str | None = None) -> "QuerySet[FileIndex]":
        """
        Find link files with NULL virtual_directory.

        Args:
            start_path: Optional starting directory path to filter files (must be normalized)

        Returns:
            QuerySet of link files with NULL virtual_directory
        """
        link_files_without_vdir = cls.objects.filter(filetype__is_link=True, virtual_directory__isnull=True, delete_pending=False)

        # Filter by start_path if provided
        if start_path:
            link_files_without_vdir = link_files_without_vdir.filter(home_directory__fqpndirectory__startswith=start_path)

        return link_files_without_vdir

    @staticmethod
    def process_link_file(fs_entry: Path, filetype: Any, filename: str) -> "DirectoryIndex | None":
        """
        Process link files (.link or .alias) and return the virtual_directory.

        Extracts target directory from link file and finds/creates the corresponding
        DirectoryIndex record. Shared by both new file creation and existing file updates.

        Args:
            fs_entry: Path object for the link file
            filetype: Filetype object with is_link=True and fileext attribute
            filename: The normalized filename from the database or filesystem

        Returns:
            DirectoryIndex object for the target directory, or None if target cannot be resolved
        """
        # Deferred: .directoryindex imports FileIndex at module level (genuine cycle)
        # pylint: disable-next=import-outside-toplevel
        from .directoryindex import DirectoryIndex

        try:
            redirect_path = None

            if filetype.fileext == ".link":
                # Parse .link format
                name_lower = filename.lower()
                star_index = name_lower.find("*")
                if star_index == -1:
                    logger.warning("Invalid link format - no '*' found in: %s", filename)
                    return None

                redirect = name_lower[star_index + 1 :].replace("'", "").replace("__", "/")
                dot_index = redirect.rfind(".")
                if dot_index != -1:
                    redirect = redirect[:dot_index]
                redirect_path = f"/{redirect}"

                # Normalize based on whether it's absolute or relative
                if not redirect_path.startswith(settings.ALBUMS_PATH):
                    redirect_path = normalize_fqpn(settings.ALBUMS_PATH + redirect_path)
                else:
                    redirect_path = normalize_fqpn(redirect_path)

            elif filetype.fileext == ".alias":
                raw_target = FileIndex.resolve_macos_alias(str(fs_entry))
                # Physical → gallery translation returns the DirectoryIndex
                # directly (or None with the reason logged). Bypasses the
                # shared lookup below so an unmapped drive path can never
                # create an out-of-tree DirectoryIndex row.
                virtual_dir = DirectoryIndex.find_by_physical_path(raw_target)
                if virtual_dir is None:
                    logger.warning("Skipping alias with unresolvable target: %s → %s", filename, raw_target)
                return virtual_dir

            # Common resolution logic (once)
            if redirect_path:
                success, virtual_dir = DirectoryIndex.search_for_directory(redirect_path)
                if not success:
                    success, virtual_dir = DirectoryIndex.add_directory(redirect_path)

                if success and virtual_dir is not None:
                    return virtual_dir

                logger.warning("Skipping link with broken target: %s → %s", filename, redirect_path)

            return None

        except ValueError as e:
            logger.error("Error processing link file %s: %s", filename, e)
            return None

    def virtual_directory_needs_repair(self) -> bool:
        """
        Return True when this link file's virtual_directory needs re-resolution.

        True when virtual_directory is unset, or when it points outside the
        albums tree — a stale row created before the target's physical-path
        translation existed.

        Returns:
            True if the link target should be re-resolved
        """
        if self.virtual_directory is None:
            return True
        # Deferred: .directoryindex imports FileIndex at module level (genuine cycle)
        # pylint: disable-next=import-outside-toplevel
        from .directoryindex import DirectoryIndex

        return not self.virtual_directory.fqpndirectory.startswith(DirectoryIndex.get_albums_root())

    @staticmethod
    def is_animated_gif(fs_entry: Path) -> bool:
        """
        Detect if a GIF file is animated.

        Shared function to avoid duplicate animation detection logic.
        Used by both new file processing and existing file updates.

        Args:
            fs_entry: Path object for the GIF file

        Returns:
            True if animated, False if static or on error
        """
        try:
            # Deferred: PIL is only needed for GIF animation checks — keeps module import light.
            # pylint: disable-next=import-outside-toplevel
            from PIL import Image

            with Image.open(fs_entry) as img:
                return getattr(img, "is_animated", False)
        except (AttributeError, IOError, OSError) as e:
            logger.error("Error checking animation for %s: %s", fs_entry, e)
            return False

    def get_file_sha(self, fqfn: str) -> tuple[str | None, str | None]:
        """
        Return the SHA256 hashes of the file as hexdigest strings.

        **INTENTIONAL CONVENIENCE HELPER** - This method is deliberately kept as a
        simple wrapper to provide a consistent, instance-based interface for FileIndex
        objects. While it only delegates to quickbbs.common.get_file_sha(), it serves
        an important purpose:

        - Provides consistent API when working with FileIndex instances
        - Allows future enhancements without changing call sites
        - Improves code readability (obj.get_file_sha() vs importing external function)
        - Maintains encapsulation of hash calculation logic

        This is NOT redundant code - it's an intentional design choice for better
        developer ergonomics.

        All hashing logic is delegated to quickbbs.common.get_file_sha().

        Args:
            fqfn: The fully qualified filename of the file to be hashed

        Returns:
            Tuple of (file_sha256, unique_sha256) where file_sha256 is the hash
            of the file contents and unique_sha256 is the hash of the file
            contents + fqfn
        """
        return get_file_sha(fqfn)

    def get_file_counts(self) -> None:
        """
        **INTENTIONAL STUB METHOD** for template compatibility.

        This method is deliberately kept as a simple stub to provide polymorphic API
        compatibility between FileIndex and DirectoryIndex objects in templates. This
        design choice eliminates the need for type checking in templates and allows
        cleaner, more maintainable template code.

        **Why this exists:**
        - Enables duck typing in Jinja2 templates
        - Eliminates complex {% if obj.is_directory %} checks
        - Provides consistent interface across both model types
        - DirectoryIndex returns actual counts, FileIndex returns None
        - Templates can safely call this on any object without errors

        **This is NOT dead code** - it's an intentional design pattern (Null Object pattern)
        for better template ergonomics.

        Returns:
            None - individual files don't have child file counts
        """
        return None

    def get_dir_counts(self) -> None:
        """
        **INTENTIONAL STUB METHOD** for template compatibility.

        This method is deliberately kept as a simple stub to provide polymorphic API
        compatibility between FileIndex and DirectoryIndex objects in templates. This
        design choice eliminates the need for type checking in templates and allows
        cleaner, more maintainable template code.

        **Why this exists:**
        - Enables duck typing in Jinja2 templates
        - Eliminates complex {% if obj.is_directory %} checks
        - Provides consistent interface across both model types
        - DirectoryIndex returns actual counts, FileIndex returns None
        - Templates can safely call this on any object without errors

        **This is NOT dead code** - it's an intentional design pattern (Null Object pattern)
        for better template ergonomics.

        Returns:
            None - individual files don't have child directory counts
        """
        return None

    def get_view_url(self) -> str:
        """Generate the URL for viewing the current database item.

        Returns:
            URL string for this item's view page
        """
        return reverse("view_item", args=(self.unique_sha256,))

    def get_thumbnail_url(self, size: str | None = None) -> str:
        """Generate the URL for the thumbnail of the current item.

        Args:
            size: Thumbnail size name ('small', 'medium', or 'large').
                Invalid or None values fall back to 'small'.

        Returns:
            URL string for this item's thumbnail. Link files delegate to
            their virtual_directory's thumbnail URL.
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
        """Generate the URL for downloading the current database item.

        The filename is percent-encoded — names containing characters like
        ``#``, ``?``, or ``%`` would otherwise produce broken URLs.

        Returns:
            URL string for this item's download endpoint
        """
        return reverse("download_file") + quote(self.name, safe="") + f"?usha={self.unique_sha256}"

    def get_content_html(self, _webpath: str) -> str:
        """
        Process file content based on file type for display.

        ASYNC-SAFE: File I/O only (entry object already loaded from DB).
        For async contexts, wrap with: await asyncio.to_thread(entry.get_content_html, webpath)

        Args:
            _webpath: Web path for constructing file path (unused, kept for
                API compatibility).

        Returns:
            Rendered HTML for text/markdown/HTML files, or an empty string
            for all other file types.
        """
        if not (self.filetype.is_text or self.filetype.is_markdown or self.filetype.is_html):
            return ""

        if self.filetype.is_text or self.filetype.is_markdown:
            return self.process_text_content(is_markdown=True)
        # Must be is_html (guard at top already returned "" for non-text/md/html)
        return self.process_text_content(is_markdown=False)

    def inline_sendfile(self, request: Any, ranged: bool = False) -> Any:
        """
        Helper function to send data to remote.

        Uses FileResponse (streaming) for non-ranged requests — avoids loading the
        entire file into worker memory. Django closes the file handle automatically
        when streaming completes, so no context manager is needed.

        Uses RangedFileResponse for ranged requests (video streaming).
        """
        mtype = self.filetype.mimetype or "application/octet-stream"

        if not ranged:
            # SECURITY: Sanitize filename to prevent header injection
            safe_filename = sanitize_filename_for_http(self.name)
            try:
                fh = open(self.full_filepathname, "rb")  # pylint: disable=consider-using-with
                response = FileResponse(fh, content_type=mtype, as_attachment=False, filename=safe_filename)
                response["Cache-Control"] = f"public, max-age={settings.HTTP_CACHE_MAX_AGE}"
            except FileNotFoundError as exc:
                raise Http404 from exc
        else:
            # Ranged request for video streaming
            try:
                # SECURITY: Sanitize filename to prevent header injection
                # Deferred: only the ranged (video streaming) path needs these; frontend.serve_up
                # also imports back into quickbbs modules (genuine cycle).
                # pylint: disable-next=import-outside-toplevel
                from ranged_fileresponse import RangedFileResponse

                # pylint: disable-next=import-outside-toplevel
                from frontend.serve_up import open_sized_file

                safe_filename = sanitize_filename_for_http(self.name)
                response = RangedFileResponse(
                    request,
                    file=open_sized_file(self.full_filepathname),
                    as_attachment=False,
                    filename=safe_filename,
                )
                response["Cache-Control"] = f"public, max-age={settings.HTTP_CACHE_MAX_AGE}"
            except FileNotFoundError as exc:
                raise Http404 from exc
        response["Content-Type"] = mtype
        return response

    async def async_inline_sendfile(self, request: Any, ranged: bool = False) -> Any:  # pylint: disable=unused-argument
        """
        Helper function to send data to remote (ASGI async version).

        All requests are served by build_async_ranged_response, which streams
        the file through an aiofiles async generator in 64 KB chunks, so worker
        memory stays flat regardless of file size. Requests without a Range
        header get a streaming 200; requests with a valid Range header get a
        206 Partial Content.

        Args:
            request: Django request object
            ranged: Unused; retained for signature compatibility with
                inline_sendfile. Range headers are honored regardless.

        Returns:
            StreamingHttpResponse (200 or 206) streaming the file content

        Raises:
            Http404: If file not found
        """
        mtype = self.filetype.mimetype or "application/octet-stream"

        # SECURITY: Sanitize filename to prevent header injection
        safe_filename = sanitize_filename_for_http(self.name)

        # Deferred: frontend.serve_up imports back into quickbbs modules
        # pylint: disable-next=import-outside-toplevel
        from frontend.serve_up import build_async_ranged_response

        try:
            file_size = await sync_to_async(os.path.getsize)(self.full_filepathname)
        except FileNotFoundError as exc:
            raise Http404 from exc

        return build_async_ranged_response(
            request=request,
            path=self.full_filepathname,
            file_size=file_size,
            content_type=mtype,
            filename=safe_filename,
            expiration=settings.HTTP_CACHE_MAX_AGE,
        )

    def check_for_updates(
        self,
        fs_entry,
        home_directory,
        fs_stat=None,
        precomputed_sha: tuple[str | None, str | None] | None = None,
    ):
        """
        Check if this file record needs updating based on filesystem entry.

        Compares modification time, size, SHA256, and other attributes between
        this database record and the filesystem entry.

        Performance Optimization:
        Accepts precomputed SHA256 hashes to enable batch parallel computation.
        When precomputed_sha is provided, skips individual SHA256 calculation.
        Accepts pre-computed fs_stat to avoid redundant filesystem syscalls.

        Known Oversight (SHA staleness):
        The SHA is only computed when the record has none. If a file's content
        changes, lastmod/size are refreshed but file_sha256/unique_sha256 keep
        their original values, so SHA-keyed features (thumbnails, duplicate
        detection) will not notice edited files. Pinned by
        test_sync.py::test_modified_file_updated_in_place.

        Args:
            fs_entry: Path object for filesystem entry (DirEntry with cached stat).
            home_directory: DirectoryIndex object for the parent directory.
            fs_stat: Optional pre-computed stat result from fs_entry.stat().
            precomputed_sha: Optional precomputed (file_sha256, unique_sha256) tuple.

        Returns:
            This record (with fields modified in memory, unsaved) if changes
            were detected, None otherwise.

        Raises:
            TypeError: If fs_stat is neither None nor a stat result.
        """
        try:
            # Use pre-computed stat if provided, otherwise call stat()
            # Note: DirEntry.stat() is already cached by Python's os.scandir()
            # Multiple stat() calls on the same DirEntry object reuse the cached result
            if fs_stat is None:
                fs_stat = fs_entry.stat()
            elif not hasattr(fs_stat, "st_mtime"):
                raise TypeError(f"fs_stat must be a stat result or None, got {type(fs_stat)!r}")
            update_needed = False

            # Get filetype (prefetched via select_related by caller)
            try:
                filetype = self.filetype
            except ObjectDoesNotExist:
                filetype = None

            # Use filetype.fileext instead of parsing Path object (avoids object creation overhead)
            fext = filetype.fileext if filetype else ""
            if filetype and fext and fext != ".none":  # Only process files with valid extensions

                # Fix broken link files - re-resolve when virtual_directory is
                # missing OR points outside the albums tree (stale rows created
                # before the target's translation existed). Self-heals on the
                # next rescan. The virtual_directory access lazy-loads one row,
                # but only for link files — rare enough to be acceptable.
                if filetype.is_link and self.virtual_directory_needs_repair():
                    virtual_dir = FileIndex.process_link_file(fs_entry, filetype, self.name)
                    if virtual_dir is not None and virtual_dir.pk != self.virtual_directory_id:
                        self.virtual_directory = virtual_dir
                        update_needed = True

                # Use precomputed hash if available, otherwise calculate.
                # A failed batch hash arrives as (None, None) — treat it the same
                # as "no precomputed value" so we don't flag a no-op update.
                #
                # TODO: Investigate recomputing the SHA when lastmod/size
                # change (see "Known Oversight" in the docstring). The SHA is
                # only computed when the record has none — a content change
                # refreshes lastmod/size below but keeps the stale
                # file_sha256/unique_sha256, so SHA-keyed features
                # (thumbnails, duplicate detection) will not notice edited
                # files. Pinned by
                # test_sync.py::test_modified_file_updated_in_place — update
                # that test when this is fixed.
                if not self.file_sha256:
                    if precomputed_sha and precomputed_sha[0]:
                        self.file_sha256, self.unique_sha256 = precomputed_sha
                        update_needed = True
                    else:
                        self.file_sha256, self.unique_sha256 = self.get_file_sha(fqfn=fs_entry)
                        if self.file_sha256 is not None:
                            update_needed = True

                # Compare by FK id — comparing the objects would lazy-load the
                # DirectoryIndex row (not in the caller's select_related), one
                # query per synced file.
                if self.home_directory_id != home_directory.pk:
                    self.home_directory = home_directory
                    update_needed = True

                # Check modification time
                if self.lastmod != fs_stat.st_mtime:
                    self.lastmod = fs_stat.st_mtime
                    update_needed = True

                # Check file size
                if self.size != fs_stat.st_size:
                    self.size = fs_stat.st_size
                    update_needed = True

                # Movie duration loading - check each file individually
                if filetype.is_movie and self.duration is None:
                    try:
                        video_details = _get_video_info(str(fs_entry))
                        self.duration = video_details.get("duration", None)
                        update_needed = True
                    except (OSError, ValueError, RuntimeError, MediaProcessingError) as e:
                        logger.error("Error getting duration for %s: %s", fs_entry, e)

                # Animated GIF detection - only check if not previously checked
                if filetype.is_image and fext == ".gif" and not self.is_animated:
                    if FileIndex.is_animated_gif(fs_entry):
                        self.is_animated = True
                        update_needed = True

            return self if update_needed else None

        except (OSError, IOError) as e:
            logger.error("Error checking file %s: %s", fs_entry, e)
            return None

    def get_text_encoding(self) -> str:
        """
        Detect the text encoding of this file.

        Reads only the first 4KB for efficient encoding detection.
        Uses charset_normalizer for robust encoding detection.

        ASYNC-SAFE: Pure file I/O, no Django ORM operations.
        For async contexts, wrap with: await asyncio.to_thread(file.get_text_encoding)

        Returns:
            Detected encoding string, defaults to 'utf-8' if detection fails
        """
        filename = self.full_filepathname
        try:
            with open(filename, "rb") as f:
                raw_data = f.read(settings.ENCODING_DETECT_READ_SIZE)

                # Deferred: charset_normalizer is only needed for text-file display — lazy import
                # keeps it off the hot module-load path.
                # pylint: disable-next=import-outside-toplevel
                import charset_normalizer

                result = charset_normalizer.from_bytes(raw_data)
                best_match = result.best()
                if best_match is None:
                    return "utf-8"
                encoding = best_match.encoding
                return encoding if encoding else "utf-8"
        except (OSError, IOError):
            return "utf-8"

    def get_text_encoding_cached(self) -> str:
        """
        Cache text encoding detection based on filename.

        Uses direct LRU cache access to avoid repeated encoding detection
        for the same file. Cache key is the full file pathname.

        Returns:
            Detected encoding string, defaults to 'utf-8' if detection fails
        """
        key = self.full_filepathname
        try:
            return FileIndex._encoding_cache[key]
        except KeyError:
            result = self.get_text_encoding()
            FileIndex._encoding_cache[key] = result
            return result

    def process_text_content(self, is_markdown: bool = False) -> str:
        """
        Process text or HTML files with size limits and encoding detection.

        ASYNC-SAFE: Pure file I/O, no Django ORM operations.
        For async contexts, wrap with: await asyncio.to_thread(file.process_text_content, is_markdown)

        Args:
            is_markdown: If True, render the content through markdown2;
                if False, return the raw content with newlines converted
                to <br> tags.

        Returns:
            Rendered HTML content, or an HTML error message when the file is
            too large (settings.MAX_TEXT_FILE_DISPLAY_SIZE) or unreadable.
        """
        max_text_file_size = settings.MAX_TEXT_FILE_DISPLAY_SIZE

        filename = self.full_filepathname
        try:
            # Use os.stat directly (avoids Path object creation overhead)
            stat_info = os.stat(filename)

            # Check file size limit
            if stat_info.st_size > max_text_file_size:
                return f"<p><em>File too large to display ({stat_info.st_size:,} bytes). Maximum size: {max_text_file_size:,} bytes.</em></p>"

            encoding = self.get_text_encoding_cached()

            with open(filename, "r", encoding=encoding) as f:
                content = f.read()

                # Process content based on type
                if is_markdown:
                    if FileIndex._markdown_processor is None:
                        # Deferred: markdown2 is only needed to render markdown files —
                        # imported once on first use, cached on the class.
                        # pylint: disable-next=import-outside-toplevel
                        import markdown2

                        FileIndex._markdown_processor = markdown2.Markdown()
                    return FileIndex._markdown_processor.convert(content)
                return content.replace("\n", "<br>")

        except UnicodeDecodeError:
            return "<p><em>We are unable to view this file.</em></p>"
        except (OSError, IOError) as e:
            return f"<p><em>Error reading file: {str(e)}</em></p>"

    @classmethod
    def resolve_macos_alias(cls, alias_path: str) -> str:
        """
        Resolve a macOS alias file to its raw target path.

        Uses the macOS Foundation framework to resolve the alias bookmark.
        The result is the physical (drive-level) target; translate it to a
        gallery directory with DirectoryIndex.find_by_physical_path().

        Args:
            alias_path: Path to the macOS alias file

        Returns:
            Raw resolved target path (lowercased)

        Raises:
            ValueError: If bookmark data cannot be created or resolved
        """
        key = hashkey(alias_path)
        cached_val = cls._alias_cache.get(key)
        if cached_val is not None:
            return cached_val
        result = cls._resolve_alias_uncached(alias_path)
        cls._alias_cache[key] = result
        return result

    @staticmethod
    def _resolve_alias_uncached(path: str) -> str:
        """
        Resolve a macOS alias to its raw target path without caching.

        Returns the bookmark's physical target (typically a masters-volume
        path) with no gallery translation applied — callers pass the result
        to DirectoryIndex.find_by_physical_path() for that.

        Foundation imports are deferred to preserve lazy-loading behaviour —
        the framework is only available on macOS and should not be imported
        at module load time.

        Args:
            path: Path to the macOS alias file

        Returns:
            Raw resolved target path (lowercased), no trailing separator

        Raises:
            ValueError: If bookmark data cannot be created or resolved
        """
        # Deferred: the Foundation framework is macOS-only and must not be imported at
        # module load time (see docstring); no-name-in-module is a pyobjc stub limitation.
        from Foundation import (  # pylint: disable=no-name-in-module,import-outside-toplevel
            NSURL,
            NSURLBookmarkResolutionWithoutMounting,
            NSURLBookmarkResolutionWithoutUI,
        )

        options = NSURLBookmarkResolutionWithoutUI | NSURLBookmarkResolutionWithoutMounting
        alias_url = NSURL.fileURLWithPath_(path)
        bookmark, error = NSURL.bookmarkDataWithContentsOfURL_error_(alias_url, None)
        if error:
            raise ValueError(f"Error creating bookmark data: {error}")

        resolved_url, _, error = NSURL.URLByResolvingBookmarkData_options_relativeToURL_bookmarkDataIsStale_error_(
            bookmark, options, None, None, None
        )
        if error:
            raise ValueError(f"Error resolving bookmark data: {error}")

        return str(resolved_url.path()).strip().lower()

    class Meta:
        """Model metadata: SHA/name/filetype lookup indexes, partial indexes for unlinked thumbnails and pending deletes, and the trigram search index."""

        verbose_name = "Master Files Index"
        verbose_name_plural = "Master Files Index"
        # Index set pruned 2026-07-04 against pg_stat_user_indexes evidence
        # (see claude_docs/plans/fable_optimizations-2.md Opt 2a). Removed as
        # never/rarely scanned: (home_directory, delete_pending),
        # (unique_sha256, delete_pending), (name, delete_pending) — lookups use
        # the plain FK index, the unique_sha256 unique index, and
        # quickbbs_fileindex_name_idx respectively.
        indexes = [
            models.Index(fields=["file_sha256", "delete_pending"]),
            models.Index(fields=["name"], name="quickbbs_fileindex_name_idx"),
            models.Index(fields=["filetype", "delete_pending"], name="fileindex_filetype_delete_idx"),
            # Performance optimization: Partial index for thumbnail linking queries
            # Speeds up: FileIndex.objects.filter(file_sha256=sha, new_ftnail__isnull=True).exists()
            models.Index(
                fields=["file_sha256"],
                name="fileindex_sha256_unlinked_idx",
                condition=models.Q(new_ftnail__isnull=True),
            ),
            # Performance optimization: Composite index for file type queries in directories
            # Speeds up: FileIndex.objects.filter(home_directory=dir, filetype=type, delete_pending=False)
            models.Index(
                fields=["home_directory", "filetype", "delete_pending"],
                name="fileindex_home_type_delete_idx",
            ),
            # Partial index for scan's delete_pending=True cleanup pass — the
            # pending set is tiny, so this replaces the 24 MB full-column index.
            models.Index(
                fields=["id"],
                name="fileindex_delete_pending_idx",
                condition=models.Q(delete_pending=True),
            ),
            # Trigram index: serves search's name__iregex / name__icontains
            # (frontend/views.py _safe_regex_search) — previously a 1.3 s
            # parallel seq scan over 1.8M rows per search query.
            GinIndex(fields=["name"], name="fileindex_name_trgm_idx", opclasses=["gin_trgm_ops"]),
        ]

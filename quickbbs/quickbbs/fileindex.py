"""
FileIndex Model - Master index for all files in the gallery
"""

from __future__ import annotations

import asyncio
import io
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles
import charset_normalizer
import markdown2
from cachetools import LRUCache, cached
from django.db import transaction
from django.db.models import Count
from django.db.models.query import QuerySet
from django.http import FileResponse, Http404, HttpResponse
from django.urls import reverse
from PIL import Image

from quickbbs.common import normalize_fqpn, normalize_string_title
from thumbnails.video_thumbnails import _get_video_info

# Import shared foundation
from .models import (
    SORT_MATRIX,
    NaturalSortField,
    Owners,
    RangedFileResponse,
    ThumbnailFiles,
    cached,
    fileindex_cache,
    fileindex_download_cache,
    filetypes,
    get_file_sha,
    logger,
    models,
    settings,
    sync_to_async,
)

if TYPE_CHECKING:
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
    _encoding_cache = LRUCache(maxsize=1000)
    _markdown_processor = markdown2.Markdown()
    _alias_cache = LRUCache(maxsize=250)

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
    dir_thumbnail: "models.manager.RelatedManager[DirectoryIndex]"  # From DirectoryIndex.thumbnail
    file_links: "models.manager.RelatedManager[DirectoryIndex]"  # From DirectoryIndex.file_links (ManyToMany)

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
        Returns: Integer - Number of identical files
        """
        return FileIndex.objects.filter(file_sha256=sha).count()

    @staticmethod
    def return_list_all_identical_files_by_sha(sha: str) -> "QuerySet[FileIndex]":
        """
        Return a query of all duplicate files based on file SHA256 hash

        Args:
            sha: The SHA256 hash of the file to find duplicates for

        Returns:
            QuerySet containing summary data (file_sha256 + count) using .values()
            and .annotate() for files with 2+ duplicates
        """
        dupes = (
            FileIndex.objects.filter(file_sha256=sha)
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
        return FileIndex.objects.values("name", "home_directory__fqpndirectory").filter(file_sha256=sha)

    @cached(fileindex_cache)
    @staticmethod
    def get_by_filters(
        select_related: list[str],
        additional_filters: dict[str, Any] | None = None,
    ) -> "QuerySet[FileIndex]":
        """
        Return the files in the current directory, filtered by additional filters

        Args:
            select_related: List of related fields to select (required)
            additional_filters: Additional filters to apply to the query

        Returns: The filtered query of files
        """
        if select_related is None:
            raise ValueError("select_related parameter is required")
        if additional_filters is None:
            additional_filters = {}
        return FileIndex.objects.select_related(*select_related).filter(delete_pending=False, **additional_filters)

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

    @cached(fileindex_cache)
    @staticmethod
    def get_by_sha256(sha_value: str, unique: bool, select_related: list[str]) -> FileIndex | None:
        """
        Return the FileIndex object by SHA256

        Args:
            sha_value: The SHA256 of the FileIndex object
            unique: If True, search by unique_sha256 (expects one result),
                    If False, search by file_sha256 (may return first of multiple)
            select_related: List of related fields to select (required)

        Returns: FileIndex object or None if not found
        """
        if select_related is None:
            raise ValueError("select_related parameter is required")
        try:
            if unique:
                return FileIndex.objects.select_related(*select_related).get(unique_sha256=sha_value, delete_pending=False)
            # When searching by file_sha256, there may be duplicates - return first
            return FileIndex.objects.select_related(*select_related).filter(file_sha256=sha_value, delete_pending=False).first()
        except FileIndex.DoesNotExist:
            return None

    @cached(fileindex_download_cache)
    @staticmethod
    def get_by_sha256_for_download(sha_value: str, unique: bool, select_related: list[str]) -> FileIndex | None:
        """
        Return the FileIndex object by SHA256 optimized for file downloads.

        Uses select_related for forward FKs and .only() to fetch minimal fields
        for maximum performance with high concurrency.

        Args:
            sha_value: The SHA256 of the FileIndex object
            unique: If True, search by unique_sha256, otherwise by file_sha256
            select_related: List of related fields to select (required)

        Returns: FileIndex object or None if not found
        """
        if select_related is None:
            raise ValueError("select_related parameter is required")
        try:
            # Determine which SHA field to filter on
            filter_field = "unique_sha256" if unique else "file_sha256"

            # Only fetch fields needed for download
            return (
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
            return None

    @classmethod
    def set_generic_icon_for_sha(cls, file_sha256: str, is_generic: bool, select_related: list[str], clear_cache: bool = True) -> int:
        """
        Set is_generic_icon for all FileIndex files with the given SHA256.

        Shared function to ensure consistent is_generic_icon updates across:
        - Thumbnail generation (success/failure)
        - Web view error handlers
        - Management commands

        When is_generic_icon changes, the layout cache must be cleared because
        the cached layout includes thumbnail counts and display states that are
        now stale.

        Args:
            file_sha256: SHA256 hash of the file(s) to update
            is_generic: New value for is_generic_icon (True = use filetype icon, False = custom thumbnail)
            select_related: List of related fields to select (required)
            clear_cache: Whether to clear layout_manager_cache for affected directories (default: True)

        Returns:
            Number of files updated
        """
        if select_related is None:
            raise ValueError("select_related parameter is required")
        # Inline import to avoid circular dependency (frontend.utilities imports DirectoryIndex)
        from frontend.managers import clear_layout_cache_for_directories

        # Update all files with this SHA256
        updated_count = cls.objects.filter(file_sha256=file_sha256).update(is_generic_icon=is_generic)

        # Clear layout cache for affected directories if requested
        if clear_cache and updated_count > 0:
            # Get unique directories containing these files
            affected_files = cls.objects.filter(file_sha256=file_sha256).select_related(*select_related)
            affected_directories = list({f.home_directory for f in affected_files if f.home_directory})

            if affected_directories:
                cleared_count = clear_layout_cache_for_directories(affected_directories)
                if cleared_count > 0:
                    print(f"Cleared {cleared_count} layout cache entries for {len(affected_directories)} directories")

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
        # Check if there are any unlinked FileIndex records for this SHA256
        has_unlinked = cls.objects.filter(file_sha256=file_sha256, new_ftnail__isnull=True).exists()

        # Link unlinked records to the thumbnail
        updated_count = 0
        if has_unlinked:
            updated_count = cls.objects.filter(
                file_sha256=file_sha256,
                new_ftnail__isnull=True,
            ).update(new_ftnail=thumbnail)

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
                print(f"Can't match fileext '{fileext}' with filetypes")
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
                print(f"Error getting file stats for {fs_entry}: {e}")
                return None

            # Handle link files
            filetype = record["filetype"]
            if filetype.is_link:
                # Calculate SHA256 for link files (required for virtual_directory resolution)
                record["file_sha256"], record["unique_sha256"] = get_file_sha(str(fs_entry))
                if record["file_sha256"] is None:
                    print(f"Error calculating SHA for link file {fs_entry}")
                    return None

                # Process link file and get virtual_directory
                virtual_dir = cls.process_link_file(fs_entry, filetype, record["name"])
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

        except Exception as e:
            print(f"Unexpected error processing {fs_entry}: {e}")
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
        try:
            # Batch delete using IDs with optimized chunking
            if records_to_delete_ids:
                # Convert to list for efficient slicing
                delete_ids_list = list(records_to_delete_ids)

                with transaction.atomic():
                    # Process deletes in optimally-sized chunks
                    for i in range(0, len(delete_ids_list), bulk_size):
                        chunk_ids = delete_ids_list[i : i + bulk_size]
                        # Use bulk delete with specific field for index usage
                        cls.objects.filter(id__in=chunk_ids).delete()
                    print(f"Deleted {len(records_to_delete_ids)} records")
                    logger.info(f"Deleted {len(records_to_delete_ids)} records")

            # Batch update in chunks for memory efficiency
            if records_to_update:
                for i in range(0, len(records_to_update), bulk_size):
                    chunk = records_to_update[i : i + bulk_size]
                    with transaction.atomic():
                        # Dynamic update field selection - only update fields that have changed
                        update_fields = ["lastmod", "size", "home_directory"]

                        # Check if any records have movies for duration field
                        has_movies = any(
                            getattr(getattr(record, "filetype", None), "is_movie", False) and getattr(record, "duration", None) is not None
                            for record in chunk
                        )
                        if has_movies:
                            update_fields.append("duration")

                        # Add hash fields only if they exist in the records
                        has_hashes = any(getattr(record, "file_sha256", None) for record in chunk)
                        if has_hashes:
                            update_fields.extend(["file_sha256", "unique_sha256"])

                        # Add virtual_directory for link files
                        has_link_with_vdir = any(
                            getattr(getattr(record, "filetype", None), "is_link", False) and getattr(record, "virtual_directory", None) is not None
                            for record in chunk
                        )
                        if has_link_with_vdir:
                            update_fields.append("virtual_directory")

                        cls.objects.bulk_update(
                            chunk,
                            fields=update_fields,
                            batch_size=bulk_size,
                        )
                logger.info(f"Updated {len(records_to_update)} records")

            # Batch create in chunks for memory efficiency
            if records_to_create:
                for i in range(0, len(records_to_create), bulk_size):
                    chunk = records_to_create[i : i + bulk_size]
                    with transaction.atomic():
                        cls.objects.bulk_create(
                            chunk,
                            batch_size=bulk_size,
                            ignore_conflicts=True,  # Handle duplicates gracefully
                        )
                logger.info(f"Created {len(records_to_create)} records")

        except Exception as e:
            logger.error(f"Database operation failed: {e}")
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
        # Inline import to avoid circular dependency (DirectoryIndex imports FileIndex)
        from .directoryindex import DirectoryIndex, DIRECTORYINDEX_SR_FILETYPE_THUMB

        try:
            redirect_path = None

            if filetype.fileext == ".link":
                # Parse .link format
                name_lower = filename.lower()
                star_index = name_lower.find("*")
                if star_index == -1:
                    logger.warning(f"Invalid link format - no '*' found in: {filename}")
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
                redirect_path = FileIndex.resolve_macos_alias(str(fs_entry))

            # Common resolution logic (once)
            if redirect_path:
                found, virtual_dir = DirectoryIndex.search_for_directory(redirect_path, DIRECTORYINDEX_SR_FILETYPE_THUMB, ())
                if not found:
                    found, virtual_dir = DirectoryIndex.add_directory(redirect_path)

                if found and virtual_dir is not None:
                    return virtual_dir

                logger.warning(f"Skipping link with broken target: {filename} → {redirect_path}")

            return None

        except ValueError as e:
            logger.error(f"Error processing link file {filename}: {e}")
            return None

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
            with Image.open(fs_entry) as img:
                return getattr(img, "is_animated", False)
        except (AttributeError, IOError, OSError) as e:
            logger.error(f"Error checking animation for {fs_entry}: {e}")
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

    def get_content_html(self, _webpath: str) -> str:
        """
        Process file content based on file type for display.

        ASYNC-SAFE: File I/O only (entry object already loaded from DB).
        For async contexts, wrap with: await asyncio.to_thread(entry.get_content_html, webpath)

        :Args:
            _webpath: Web path for constructing file path (unused, kept for API compatibility)

        Returns:
            Processed HTML content or empty string
        """
        if not (self.filetype.is_text or self.filetype.is_markdown or self.filetype.is_html):
            return ""

        if self.filetype.is_text or self.filetype.is_markdown:
            return self.process_text_content(is_markdown=True)
        if self.filetype.is_html:
            return self.process_text_content(is_markdown=False)

        return ""

    def inline_sendfile(self, request: Any, ranged: bool = False) -> Any:
        """
        Helper function to send data to remote - matches original fast implementation.

        Loads entire file into memory for non-ranged requests (fast for small files,
        benefits from OS caching on repeated reads).

        Uses HttpResponse for non-ranged, RangedFileResponse for ranged (videos).
        """
        mtype = self.filetype.mimetype or "application/octet-stream"

        if not ranged:
            # Load entire file into memory - matches old fast code
            try:
                with open(self.full_filepathname, "rb") as fh:
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
                    file=open(self.full_filepathname, "rb"),  # pylint: disable=consider-using-with
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
        mtype = self.filetype.mimetype or "application/octet-stream"
        file_handle = None

        try:
            if not ranged:
                # Non-ranged: Load file async and serve from memory (eliminates sync iterator warning)
                async with aiofiles.open(self.full_filepathname, "rb") as f:
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
                    return open(self.full_filepathname, "rb")

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

        :Args:
            fs_entry: Path object for filesystem entry (DirEntry with cached stat)
            home_directory: DirectoryIndex object for the parent directory
            fs_stat: Optional pre-computed stat result from fs_entry.stat()
            precomputed_sha: Optional precomputed (file_sha256, unique_sha256) tuple

        Returns:
            This record if changes detected, None otherwise
        """
        try:
            # Use pre-computed stat if provided, otherwise call stat()
            # Note: DirEntry.stat() is already cached by Python's os.scandir()
            # Multiple stat() calls on the same DirEntry object reuse the cached result
            if fs_stat is None:
                fs_stat = fs_entry.stat()
            update_needed = False

            # Extract file extension using pathlib for consistency
            path_obj = Path(self.name)
            fext = path_obj.suffix.lower() if path_obj.suffix else ""
            if fext:  # Only process files with extensions
                # Use prefetched filetype (check if loaded without triggering query)
                if "filetype" in self.__dict__:
                    filetype = self.filetype
                else:
                    # Fall back to lazy load (safe in sync context) or lookup by extension
                    try:
                        filetype = self.filetype
                    except Exception:
                        filetype = filetypes.return_filetype(fileext=fext)

                # Fix broken link files - process virtual_directory if missing
                if filetype.is_link and self.virtual_directory is None:
                    virtual_dir = FileIndex.process_link_file(fs_entry, filetype, self.name)
                    if virtual_dir is not None:
                        self.virtual_directory = virtual_dir
                        update_needed = True

                # Use precomputed hash if available, otherwise calculate
                if not self.file_sha256:
                    if precomputed_sha:
                        self.file_sha256, self.unique_sha256 = precomputed_sha
                        update_needed = True
                    else:
                        self.file_sha256, self.unique_sha256 = self.get_file_sha(fqfn=fs_entry)
                        if self.file_sha256 is not None:
                            update_needed = True

                if self.home_directory != home_directory:
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
                    except Exception as e:
                        logger.error(f"Error getting duration for {fs_entry}: {e}")

                # Animated GIF detection - only check if not previously checked
                if filetype.is_image and fext == ".gif" and self.is_animated is None:
                    self.is_animated = FileIndex.is_animated_gif(fs_entry)
                    update_needed = True

            return self if update_needed else None

        except (OSError, IOError) as e:
            logger.error(f"Error checking file {fs_entry}: {e}")
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
                raw_data = f.read(4096)  # Read only first 4KB

                # Detect encoding using charset_normalizer
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

        Uses LRU cache to avoid repeated encoding detection for the same file.
        Cache key is based on the full file pathname.

        Returns:
            Detected encoding string, defaults to 'utf-8' if detection fails
        """

        @cached(FileIndex._encoding_cache)
        def _get_cached_encoding(_filename: str) -> str:
            # This is a workaround - we need to call the instance method
            # but caching needs a hashable key (string), not an instance
            # _filename is used by @cached decorator as cache key
            return self.get_text_encoding()

        return _get_cached_encoding(self.full_filepathname)

    def process_text_content(self, is_markdown: bool = False) -> str:
        """
        Process text or HTML files with size limits and encoding detection.

        ASYNC-SAFE: Pure file I/O, no Django ORM operations.
        For async contexts, wrap with: await asyncio.to_thread(file.process_text_content, is_markdown)

        :Args:
            is_markdown: Whether to process as markdown (True) or HTML (False)

        Returns:
            Processed HTML content or error message
        """
        # File size limit for text file processing (1MB)
        max_text_file_size = 1024 * 1024

        filename = self.full_filepathname
        try:
            # Use single stat call for both size and mtime
            file_path = Path(filename)
            stat_info = file_path.stat()

            # Check file size limit
            if stat_info.st_size > max_text_file_size:
                return f"<p><em>File too large to display ({stat_info.st_size:,} bytes). Maximum size: {max_text_file_size:,} bytes.</em></p>"

            encoding = self.get_text_encoding_cached()

            with open(filename, "r", encoding=encoding) as f:
                content = f.read()

                # Process content based on type
                if is_markdown:
                    return FileIndex._markdown_processor.convert(content)
                return content.replace("\n", "<br>")

        except UnicodeDecodeError:
            return "<p><em>We are unable to view this file.</em></p>"
        except (OSError, IOError) as e:
            return f"<p><em>Error reading file: {str(e)}</em></p>"

    @classmethod
    def resolve_macos_alias(cls, alias_path: str) -> str:
        """
        Resolve a macOS alias file to its target path.

        Uses macOS Foundation framework to resolve alias files and applies
        path mappings from settings.ALIAS_MAPPING.

        :Args:
            alias_path: Path to the macOS alias file

        Returns:
            Resolved path to the target file/directory

        Raises:
            ValueError: If bookmark data cannot be created or resolved
        """
        from Foundation import (  # pylint: disable=no-name-in-module
            NSURL,
            NSURLBookmarkResolutionWithoutMounting,
            NSURLBookmarkResolutionWithoutUI,
        )

        @cached(cls._alias_cache)
        def _resolve_cached(path: str) -> str:
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

            resolved_url = str(resolved_url.path()).strip().lower()
            # album_path = f"{settings.ALBUMS_PATH}{os.sep}albums{os.sep}"
            for disk_path, replacement_path in settings.ALIAS_MAPPING.items():
                if resolved_url.startswith(disk_path.lower()):
                    resolved_url = resolved_url.replace(disk_path.lower(), replacement_path.lower()) + os.sep
                    break

            # The copier is set to transform spaces to underscores.  We can safely disable that now, but
            # that legacy means that there would be tremendous pain in duplication of data.  So for now,
            # we will just check if the resolved path exists, and if not, we will try replacing spaces with underscores.
            # If that works, then we will return that modified path instead.  Otherwise, we return the original resolved path.

            if resolved_url:
                if os.path.exists(resolved_url):
                    return resolved_url
                resolved_url = resolved_url.replace(" ", "_")

            return resolved_url

        return _resolve_cached(alias_path)

    class Meta:
        verbose_name = "Master Files Index"
        verbose_name_plural = "Master Files Index"
        indexes = [
            models.Index(fields=["home_directory", "delete_pending"]),
            models.Index(fields=["file_sha256", "delete_pending"]),
            models.Index(fields=["unique_sha256", "delete_pending"]),
            models.Index(fields=["name"], name="quickbbs_fileindex_name_idx"),
            # Composite indexes for common query patterns
            models.Index(fields=["name", "delete_pending"], name="fileindex_name_delete_idx"),
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
        ]

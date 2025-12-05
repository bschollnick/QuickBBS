"""
The models, and logic for thumbnail storage for the Quickbbs reloaded project.

* Thumbnail Files - Is the core storage for the thumbnails.  This stores the actual
    data for the thumbnail (e.g. FileSize, FileName, uuid, etc.  The actual
    thumbnail is stored in the *Thumb tables (see below) )

    These tables are the binary storage for Thumbnail Files.
    * SmallThumb - The binary storage for the Small Thumbnails
    * MediumThumb - The Binary storage for the Medium Thumbnails
    * LargeThumb - The Binary Storage for the Large Thumbnails

v4 - Attempting to reduce the amount of queries by maximizing the foreign key logic,
    to access the FileIndex information, instead of fetching it separately.
    Changing the directory thumbnail logic, the directory data is still it's own table,
    but the thumbnail is now a foreign key to the ThumbnailFiles model for the file
    that is being shown as the thumbnail. This eliminates the need for the redundant blob
    in the DirectoryThumbnail model, and allows for easier management of the thumbnails.

v3 - Pilot changing the thumbnail storage to be a single table, with the small, medium,
    and large blobs containing the actual thumbnail data.  This will reduce the number of
    queries, and allow for easier management of the thumbnails.

    Split the directory thumbnails into a separate table, so that we can manage the thumbnails
    separately from the FileIndex model.

"""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING

from asgiref.sync import sync_to_async
from cachetools import LRUCache, cached
from django.conf import settings
from django.db import models, transaction
from django.db.utils import IntegrityError

from frontend.serve_up import send_file_response

if TYPE_CHECKING:
    from django.db.models.manager import RelatedManager

    from quickbbs.models import FileIndex

# from .image_utils import resize_pil_image, return_image_obj
from .thumbnail_engine import create_thumbnails_from_path

__version__ = "4.0"

__author__ = "Benjamin Schollnick"
__email__ = "Benjamin@schollnick.net"

__url__ = "https://github.com/bschollnick/quickbbs"
__license__ = "TBD"


ThumbnailFiles_Prefetch_List = [
    "FileIndex__filetype",
    "FileIndex__home_directory",
]

# Optimized prefetch for bulk operations
ThumbnailFiles_Bulk_Prefetch_List = [
    "FileIndex__filetype",
    "FileIndex__home_directory",
]

# =============================================================================
# THUMBNAILFILES PREFETCH_RELATED CONSTANTS
# Colocated with ThumbnailFiles class for use by class methods and external callers
# See related_fetches.md for usage details
# NOTE: Using tuples (not lists) so they can be used as cache keys (hashable)
# =============================================================================

# Minimal - one FileIndex with filetype (for path and graphic check)
THUMBNAILFILES_PR_FILEINDEX_FILETYPE = ("FileIndex__filetype",)

# Async-safe cache for thumbnail lookups
thumbnailfiles_cache = LRUCache(maxsize=1000)


class ThumbnailFiles(models.Model):
    """
    ThumbnailFiles is the primary storage for any thumbnails that are created.

    Primary Key - `sha256_hash` - This is the sha256 hash of the file that the thumbnail is for.

    * SmallThumb - The binary storage for the Small Thumbnails
    * MediumThumb - The Binary storage for the Medium Thumbnails
    * LargeThumb - The Binary Storage for the Large Thumbnails

    """

    sha256_hash = models.CharField(
        db_index=True,
        blank=True,
        unique=True,
        null=True,
        default=None,
        max_length=64,
    )
    small_thumb = models.BinaryField(default=b"", null=True)
    medium_thumb = models.BinaryField(default=b"", null=True)
    large_thumb = models.BinaryField(default=b"", null=True)

    # Reverse ForeignKey relationship
    FileIndex: "RelatedManager[FileIndex]"  # From FileIndex.new_ftnail

    class Meta:
        verbose_name = "Image File Thumbnails Cache"
        verbose_name_plural = "Image File Thumbnails Cache"
        indexes = [
            # Optimize SHA256 lookups with partial index
            models.Index(
                fields=["sha256_hash"],
                name="thumbnails_sha256_lookup_idx",
                condition=models.Q(sha256_hash__isnull=False),
            ),
            # Optimize thumbnail existence checks
            models.Index(
                fields=["sha256_hash"],
                name="thumbnails_has_small_idx",
                condition=models.Q(small_thumb__isnull=False) & ~models.Q(small_thumb=b""),
            ),
            models.Index(
                fields=["sha256_hash"],
                name="thumbnails_has_medium_idx",
                condition=models.Q(medium_thumb__isnull=False) & ~models.Q(medium_thumb=b""),
            ),
            models.Index(
                fields=["sha256_hash"],
                name="thumbnails_has_large_idx",
                condition=models.Q(large_thumb__isnull=False) & ~models.Q(large_thumb=b""),
            ),
        ]
        # Note: Constraints can be added later after cleaning up existing data
        # constraints = []

    @staticmethod
    def get_or_create_thumbnail_record(
        file_sha256: str, suppress_save: bool, prefetch_related_thumbnail: list[str], select_related_fileindex: list[str]
    ) -> "ThumbnailFiles":
        """
        Get or create a thumbnail record for a file.

        Args:
            file_sha256: The sha256 hash of the file to retrieve or create a thumbnail for
            suppress_save: If True, do not save the thumbnail after creation
            prefetch_related_thumbnail: List of related fields to prefetch for ThumbnailFiles (required)
            select_related_fileindex: List of related fields to select_related for FileIndex (required)

        Returns:
            ThumbnailFiles object, either retrieved from database or newly created
        """
        if not file_sha256:
            raise ValueError(f"file_sha256 parameter is required and cannot be None or empty, got: {file_sha256!r}")
        if prefetch_related_thumbnail is None:
            raise ValueError("prefetch_related_thumbnail parameter is required")
        if select_related_fileindex is None:
            raise ValueError("select_related_fileindex parameter is required")

        from django.db import connection

        from quickbbs.fileindex import FILEINDEX_SR_HOME
        from quickbbs.models import FileIndex

        # MEMORY MANAGEMENT NOTE:
        # Periodic cache clearing was removed because it conflicts with CIContext recycling.
        # CIContext already recycles every 500 operations (see core_image_thumbnails.py).
        # Clearing caches more frequently (every 100) prevents the recycling from working
        # and causes GPU memory accumulation from repeated CIContext recreations.
        #
        # Cache clearing still happens:
        # 1. After batch operations (batch_create_async)
        # 2. Automatically via CIContext recycling (every 500 operations)
        #
        # This provides sufficient memory management without the overhead and GPU memory
        # issues caused by too-frequent cache clearing.

        # CRITICAL: Advisory lock for Gunicorn multi-process environments
        # Multiple worker processes generating the same thumbnail concurrently can cause corrupted/white
        # thumbnails when Core Image GPU operations conflict or saves are interleaved.
        #
        # Advisory locks work across ALL database connections/processes, unlike row-level locks.
        # The lock key is derived from the SHA256 hash to ensure per-file locking.
        # Convert first 8 bytes of SHA256 to integer for advisory lock key
        # PostgreSQL advisory locks use bigint (64-bit), so we use first 8 bytes
        lock_key = int(file_sha256[:16], 16) % (2**63 - 1)  # Stay within bigint range

        with transaction.atomic():
            # Acquire advisory lock - blocks until lock is available
            # This works across ALL Gunicorn worker processes
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])

            defaults = {
                "sha256_hash": file_sha256,
                "small_thumb": b"",
                "medium_thumb": b"",
                "large_thumb": b"",
            }
            thumbnail, created = ThumbnailFiles.objects.prefetch_related(*prefetch_related_thumbnail).get_or_create(
                sha256_hash=file_sha256, defaults=defaults
            )

            # CRITICAL: Link FileIndex records to thumbnail FIRST, before checking if thumbnail exists
            # This ensures FileIndex records are linked even if thumbnail was generated by another process
            has_unlinked, updated_count = FileIndex.link_to_thumbnail(file_sha256, thumbnail)

            # Re-check if thumbnail exists (another worker may have generated it while we waited for lock)
            # Must re-fetch from database to see changes from other processes
            thumbnail.refresh_from_db()
            if thumbnail.thumbnail_exists():
                return thumbnail

            # Get an FileIndex record for file path (prefer prefetched)
            prefetched_indexdata = list(thumbnail.FileIndex.all())
            if prefetched_indexdata:
                index_data_item = prefetched_indexdata[0]
            else:
                index_data_item = FileIndex.objects.select_related(*select_related_fileindex).filter(file_sha256=file_sha256).first()

            # CRITICAL: Handle orphaned ThumbnailFiles by linking to matching FileIndex records
            # This can happen if thumbnail was created but linking failed, or from data migration issues
            if index_data_item is None:
                # No linked FileIndex - try to find and link FileIndex records with this SHA256
                matching_files_count = FileIndex.objects.filter(file_sha256=file_sha256).count()
                if matching_files_count > 0:
                    # Found FileIndex records - link them
                    print(f"Orphaned ThumbnailFiles {thumbnail.id}: Found {matching_files_count} FileIndex records with SHA256 {file_sha256[:16]}..., linking...")
                    has_unlinked_fix, updated_count_fix = FileIndex.link_to_thumbnail(file_sha256, thumbnail)
                    if updated_count_fix > 0:
                        print(f"  ✓ Linked {updated_count_fix} FileIndex records to ThumbnailFiles {thumbnail.id}")
                        # Successfully linked - now fetch one for processing
                        index_data_item = FileIndex.objects.select_related(*select_related_fileindex).filter(file_sha256=file_sha256).first()
                        # Update has_unlinked to trigger save
                        has_unlinked = True
                    else:
                        print(f"  ERROR: Failed to link FileIndex records (already linked elsewhere?)")
                        raise ValueError(f"Cannot link orphaned ThumbnailFiles {thumbnail.id} to FileIndex records")
                else:
                    # No FileIndex exists for this SHA256
                    print(f"ERROR: Orphaned ThumbnailFiles {thumbnail.id} has SHA256 {file_sha256[:16]}... but NO FileIndex records exist")
                    print(f"  This thumbnail record is invalid and should be deleted manually")
                    raise ValueError(f"Orphaned ThumbnailFiles {thumbnail.id}: No FileIndex records found for SHA256 {file_sha256}")

                # If still no FileIndex after linking attempt, raise error
                if index_data_item is None:
                    raise ValueError(f"Orphaned ThumbnailFiles {thumbnail.id}: Failed to get FileIndex after linking")

            if created or has_unlinked:
                if not created:  # If not newly created, save the thumbnail to update it
                    thumbnail.save()

                # Clear prefetch cache since we just updated the links
                # This ensures thumbnail.FileIndex.all() returns fresh data
                if updated_count > 0 and hasattr(thumbnail, "_prefetched_objects_cache"):
                    thumbnail._prefetched_objects_cache.clear()

            # File I/O operations (inside transaction to maintain lock during generation)
            # CRITICAL: Check for orphaned FileIndex records (home_directory is None)
            # This can happen when a directory is deleted but FileIndex records remain
            if index_data_item.home_directory is None:
                # Orphaned record - mark as generic icon and skip thumbnail generation
                print(
                    f"WARNING: Orphaned FileIndex record (id={index_data_item.id}, "
                    f"sha256={file_sha256[:16]}...) has no home_directory"
                )
                print("  This record should be cleaned up. Marking thumbnail as generic icon.")

                # Mark both FileIndex and ThumbnailFiles as generic
                index_data_item.is_generic_icon = True
                index_data_item.save(update_fields=["is_generic_icon"])

                # Return the thumbnail (empty, but marked as generic)
                return thumbnail

            # If already marked as generic, check if parent directory has been invalidated
            # If parent is invalidated (rescanned), retry thumbnail creation
            # If parent is NOT invalidated, skip creation (use filetype thumbnail)
            if index_data_item.is_generic_icon:
                parent_invalidated = False
                # Check if parent directory has been invalidated/rescanned
                parent_invalidated = (
                    hasattr(index_data_item.home_directory, "Cache_Watcher") and index_data_item.home_directory.Cache_Watcher.invalidated
                )

                if not parent_invalidated:
                    # Parent not rescanned, skip thumbnail creation
                    # send_thumbnail() will return the filetype thumbnail
                    return thumbnail
                # Parent was rescanned, continue to retry thumbnail creation below

            filename = index_data_item.full_filepathname
            filetype = index_data_item.filetype

            # CRITICAL: Skip alias/link files entirely
            # Alias files (.link, etc.) should NEVER have thumbnails generated
            # They should not be marked as generic_icon, just return empty thumbnail
            if filetype and filetype.is_link:
                # Return thumbnail without generating anything
                # The view layer will handle displaying link icons appropriately
                return thumbnail

            # Try to create thumbnails, but mark as generic on any failure
            thumbnails = None  # Initialize to prevent UnboundLocalError
            try:
                if filetype.is_image:
                    # Note: CoreImage/AVFoundation disabled due to GPU memory leaks
                    # "auto" backend now uses PIL (CPU-based, stable memory)
                    thumbnails = create_thumbnails_from_path(
                        filename,
                        settings.IMAGE_SIZE,
                        output="JPEG",
                        quality=settings.CORE_IMAGE_QUALITY,
                        backend="auto",
                    )

                    # Validate thumbnail is not empty
                    if not thumbnails or not thumbnails.get("small"):
                        raise ValueError(f"Image thumbnail creation returned empty result for {index_data_item.name}")

                    # NOTE: All-white detection removed (2025-12-02)
                    # This was a CoreImage-specific workaround for GPU corruption bugs.
                    # PIL is reliable - if it produces an all-white thumbnail, that's because
                    # the source image is actually all-white, which is a legitimate result.
                elif filetype.is_movie:
                    thumbnails = create_thumbnails_from_path(
                        filename,
                        settings.IMAGE_SIZE,
                        output="JPEG",
                        quality=settings.PIL_IMAGE_QUALITY,
                        backend="video",
                    )
                    # Validate result
                    if not thumbnails or not thumbnails.get("small"):
                        raise ValueError(f"Video thumbnail creation returned empty result for {index_data_item.name}")

                elif filetype.is_pdf:
                    thumbnails = create_thumbnails_from_path(
                        filename,
                        settings.IMAGE_SIZE,
                        output="JPEG",
                        quality=settings.PIL_IMAGE_QUALITY,
                        backend="pdf",
                    )
                    # Validate result
                    if not thumbnails or not thumbnails.get("small"):
                        raise ValueError(f"PDF thumbnail creation returned empty result for {index_data_item.name}")
                else:
                    # File type doesn't support custom thumbnails (text, archives, etc.)
                    # Mark ALL files with this SHA256 as generic (not just one)
                    # Use FileIndex classmethod to ensure layout cache is cleared
                    print(
                        f"File type {filetype.fileext} doesn't support custom thumbnails, "
                        f"marking all instances as generic: {index_data_item.name}"
                    )
                    FileIndex.set_generic_icon_for_sha(file_sha256, is_generic=True, select_related=FILEINDEX_SR_HOME, clear_cache=True)

                    # Clear LRUCache entry for this SHA256 to avoid serving stale cached data
                    thumbnailfiles_cache.pop(file_sha256, None)

                    return thumbnail

                thumbnail.small_thumb = thumbnails["small"]
                thumbnail.medium_thumb = thumbnails["medium"]
                thumbnail.large_thumb = thumbnails["large"]

                if not suppress_save:
                    thumbnail.save(update_fields=["small_thumb", "medium_thumb", "large_thumb"])

                # If this was a retry (file was marked generic), turn off generic flag
                # on success for ALL instances
                # Use FileIndex classmethod to ensure layout cache is cleared
                if index_data_item.is_generic_icon:
                    print(f"Thumbnail creation succeeded on retry for {index_data_item.name}, " f"turning off generic flag for all instances")
                    FileIndex.set_generic_icon_for_sha(file_sha256, is_generic=False, select_related=FILEINDEX_SR_HOME, clear_cache=True)

                    # Clear LRUCache entry for this SHA256 to avoid serving stale cached data
                    thumbnailfiles_cache.pop(file_sha256, None)

            except Exception as e:
                # Any error during thumbnail creation - mark ALL files with this SHA256 as generic
                # Use FileIndex classmethod to ensure layout cache is cleared
                print(f"Thumbnail creation failed for {index_data_item.name}: {e}")
                if not index_data_item.is_generic_icon:
                    FileIndex.set_generic_icon_for_sha(file_sha256, is_generic=True, select_related=FILEINDEX_SR_HOME, clear_cache=True)

                    # Clear LRUCache entry for this SHA256 to avoid serving stale cached data
                    thumbnailfiles_cache.pop(file_sha256, None)

            return thumbnail

    def number_of_indexdata_references(self) -> int:
        """
        Return the number of FileIndex references for this thumbnail.

        Returns:
            Count of FileIndex objects referencing this thumbnail
        """
        from quickbbs.models import FileIndex

        return FileIndex.objects.filter(file_sha256=self.sha256_hash).count()

    @classmethod
    @cached(thumbnailfiles_cache)
    def get_thumbnail_by_sha(cls, sha256: str, prefetch_related: list[str]) -> "ThumbnailFiles":
        """
        Get thumbnail object by SHA256 hash with optimized caching.

        Args:
            sha256: SHA256 hash of the file
            prefetch_related: List of related fields to prefetch (required)

        Returns:
            ThumbnailFiles object for the specified hash
        """
        if prefetch_related is None:
            raise ValueError("prefetch_related parameter is required")
        return cls.objects.prefetch_related(*prefetch_related).get(sha256_hash=sha256)

    @classmethod
    def get_thumbnails_by_sha_list(cls, sha256_list: list[str], prefetch_related: list[str]) -> dict[str, "ThumbnailFiles"]:
        """
        Get multiple thumbnails by SHA256 hash list to avoid N+1 queries.

        Args:
            sha256_list: List of SHA256 hashes
            prefetch_related: List of related fields to prefetch (required)

        Returns:
            Dictionary mapping SHA256 hash to ThumbnailFiles object
        """
        if prefetch_related is None:
            raise ValueError("prefetch_related parameter is required")
        thumbnails = cls.objects.prefetch_related(*prefetch_related).filter(sha256_hash__in=sha256_list)

        return {thumb.sha256_hash: thumb for thumb in thumbnails}

    def thumbnail_exists(self, size: str = "small") -> bool:
        """
        Check if the thumbnail exists for the given size.

        Args:
            size: The size of the thumbnail to check for (small, medium, or large)

        Returns:
            True if the thumbnail exists, False otherwise
        """
        match size.lower():
            case "small":
                return self.small_thumb not in ["", b"", None]
            case "medium":
                return self.medium_thumb not in ["", b"", None]
            case "large":
                return self.large_thumb not in ["", b"", None]
        return False

    def invalidate_thumb(self) -> None:
        """
        Clear all thumbnail data for regeneration.

        Sets all thumbnail binary fields (small, medium, large) to empty byte strings.
        Does not save the object - call save() explicitly after invalidation.

        Returns:
            None

        Note:
            This function does not delete the thumbnail object or save changes.
            The intention is to clear thumbnail data for regeneration.

        Example:
            >>> thumbnail = ThumbnailFiles.objects.get(sha256_hash='...')
            >>> thumbnail.invalidate_thumb()
            >>> thumbnail.save()
        """
        self.small_thumb = b""
        self.medium_thumb = b""
        self.large_thumb = b""

        # Clear LRUCache entry for this SHA256 to avoid serving stale cached data
        thumbnailfiles_cache.pop(self.sha256_hash, None)

    def retrieve_sized_tnail(self, size: str = "small") -> bytes:
        """
        Get thumbnail blob of specified size.

        Args:
            size: The size string (small, medium, or large)

        Returns:
            Binary blob containing the image data for the specified size
        """
        blobdata = b""
        match size.lower():
            case "small":
                blobdata = self.small_thumb
            case "medium":
                blobdata = self.medium_thumb
            case "large":
                blobdata = self.large_thumb
        return blobdata

    def send_thumbnail(
        self,
        filename_override: str | None = None,
        fext_override: str | None = None,
        size: str = "small",
        index_data_item=None,
    ):
        """
        Send thumbnail as HTTP response with appropriate headers.

        Args:
            filename_override: Optional filename to use instead of the original
            fext_override: Optional file extension override (unused, kept for API compatibility)
            size: The size of thumbnail to send (small, medium, or large)
            index_data_item: Pre-fetched FileIndex to avoid additional query

        Returns:
            Django FileResponse containing the thumbnail with appropriate headers

        Note:
            Thumbnails are stored as JPEGs, so JPEG will always be sent regardless of
            the original file type.

        Example:
            >>> thumbnail.send_thumbnail(filename_override="cover.jpg", size="medium")
        """
        # Get FileIndex to check if file is marked as generic
        if not index_data_item:
            try:
                index_data_list = list(self.FileIndex.all())
                if index_data_list:
                    index_data_item = index_data_list[0]
            except:
                pass

        # If file is marked as generic icon OR filetype is generic, use filetype thumbnail instead
        # This handles both explicit marking (is_generic_icon) and filetype-based generic status (filetype.generic)
        if index_data_item and (index_data_item.is_generic_icon or index_data_item.filetype.generic):
            return index_data_item.filetype.send_thumbnail()

        # Use provided index_data_item for filename
        if index_data_item:
            filename = filename_override or index_data_item.name
        else:
            filename = filename_override or "thumbnail"

        mtype = "image/jpeg"
        blob = self.retrieve_sized_tnail(size=size)

        # Validate that thumbnail blob is not empty
        if not blob or len(blob) == 0:
            raise ValueError(f"Thumbnail blob is empty for {filename}")

        return send_file_response(
            filename=filename,
            content_to_send=io.BytesIO(blob),
            mtype=mtype or "image/jpeg",
            attachment=False,
            expiration=300,
        )

    # NOTE: Future optimization opportunity
    # Current implementation uses asyncio.gather() which doesn't parallelize CPU-bound
    # image processing operations. If batch thumbnail generation becomes slow, consider
    # implementing a singleton ProcessPoolExecutor pattern similar to the SHA256 pool
    # in frontend/utilities.py:46-169. This would parallelize PIL/PyMuPDF operations
    # across multiple CPU cores while maintaining proper cleanup.
    @classmethod
    async def batch_create_async(cls, sha256_list: list[str], batchsize: int = 100, max_workers: int = 4) -> dict[str, bool]:
        """
        Batch create thumbnails asynchronously with controlled concurrency.

        This method processes multiple thumbnails in parallel using asyncio tasks,
        with batching to limit concurrent operations and avoid overwhelming the system.

        MEMORY MANAGEMENT: Clears backend caches after batch completion to release
        accumulated resources (especially important for Core Image on macOS).

        :Args:
            sha256_list: List of SHA256 hashes to create thumbnails for
            batchsize: Maximum number of thumbnails to process (default: 100)
            max_workers: Maximum number of concurrent tasks (default: 4)

        Returns:
            Dictionary mapping SHA256 hash to success status (True/False)

        Example:
            >>> results = await ThumbnailFiles.batch_create_async(['abc123', 'def456'], max_workers=6)
            >>> results
            {'abc123': True, 'def456': False}
        """
        if not sha256_list:
            return {}

        # Limit to batchsize
        sha256_list = sha256_list[:batchsize]

        print(f"Processing {len(sha256_list)} thumbnails with {max_workers} concurrent tasks")

        results = {}

        # Process in batches to limit concurrency
        for i in range(0, len(sha256_list), max_workers):
            batch = sha256_list[i : i + max_workers]
            tasks = [cls._process_single_thumbnail_async(sha256) for sha256 in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for sha256, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    print(f"Task execution error for {sha256}: {result}")
                    results[sha256] = False
                else:
                    success, _, _ = result
                    results[sha256] = success

        successful_count = sum(1 for v in results.values() if v)
        if successful_count > 0:
            print(f"Successfully processed {successful_count}/{len(sha256_list)} thumbnails")

        # MEMORY MANAGEMENT: Clear backend caches after batch completes
        # This releases Core Image CIContext instances and their GPU resources
        try:
            from thumbnails.thumbnail_engine import clear_backend_caches, get_cache_stats

            # Log cache stats before clearing
            cache_stats_before = get_cache_stats()
            if cache_stats_before["total_cached_instances"] > 0:
                print(f"Cache stats before clearing: {cache_stats_before['total_cached_instances']} instances")

                # Clear caches and get statistics
                clear_stats = clear_backend_caches(force_gc=True)

                print(
                    f"Cleared {clear_stats['processors_cleared']} processors, "
                    f"{clear_stats['backends_cleared']} backends. "
                    f"GC collected {clear_stats['gc_objects_collected']} objects. "
                    f"Memory change: {clear_stats['memory_freed_mb']:.1f} MB"
                )
        except Exception as e:
            # Don't fail the batch if cache clearing fails
            print(f"Warning: Cache clearing failed: {e}")

        return results

    @classmethod
    @sync_to_async
    def _process_single_thumbnail_async(cls, sha256: str) -> tuple[bool, str, "ThumbnailFiles | None"]:
        """
        Process a single thumbnail with proper Django database handling (async wrapper).

        :Args:
            sha256: SHA256 hash of the file to create thumbnail for

        Returns:
            Tuple of (success, sha256, thumbnail) where success is bool,
            sha256 is the file hash, and thumbnail is the ThumbnailFiles object or None
        """
        try:
            with transaction.atomic():
                thumbnail = cls.get_or_create_thumbnail_record(
                    sha256,
                    suppress_save=False,
                    prefetch_related_thumbnail=THUMBNAILFILES_PR_FILEINDEX_FILETYPE,
                    select_related_fileindex=("filetype",),
                )
            return True, sha256, thumbnail
        except IntegrityError as e:
            print(f"Error creating thumbnail for {sha256}: {e}")
            return False, sha256, None
        except Exception as e:
            print(f"Unexpected error creating thumbnail for {sha256}: {e}")
            return False, sha256, None

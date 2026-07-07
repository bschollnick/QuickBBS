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

import io
import logging
from typing import TYPE_CHECKING, cast

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection, models, transaction
from django.db.models import Q
from PIL import Image

from frontend.serve_up import send_file_response
from quickbbs.cache_registry import clear_layout_cache_for_directories
from thumbnails.exceptions import (
    MediaProcessingError,
    OrphanedFileIndex,
    OrphanedThumbnail,
    ThumbnailGenerationError,
    UnsupportedFormatError,
)
from thumbnails.thumbnail_engine import BackendType, create_thumbnails_from_path

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.db.models.fields.related_descriptors import RelatedManager
    from PIL import Image

    # Inside the ThumbnailFiles class body, the bare name "FileIndex" in a
    # type string resolves to the reverse-manager class attribute (declared
    # below), not the model — annotations there must use this alias instead.
    from quickbbs.models import DirectoryIndex
    from quickbbs.models import FileIndex
    from quickbbs.models import FileIndex as FileIndexModel

__version__ = "4.0"

logger = logging.getLogger(__name__)

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

# Empty-value sentinel for thumbnail existence checks (avoids per-call list creation)
_EMPTY_THUMB_VALUES = ("", b"", None)


def is_all_white_thumbnail(small_thumb: bytes | memoryview | None) -> bool:
    """Return True if the thumbnail blob decodes to an entirely white image.

    Shared detector used by both the creation-time white check
    (settings.MAC_OPTIMIZATION_WHITECHECK) and the offline repair scan
    (manage.py scan --verify_thumbnails). Callers apply their own size
    prefilter (settings.SMALL_THUMBNAIL_SAFEGUARD_SIZE).

    Args:
        small_thumb: JPEG/PNG blob of the small thumbnail (bytes or a
            memoryview from a BinaryField), or None.

    Returns:
        True if every pixel is white, False for empty/None blobs, non-RGB/L
        modes, or any non-white pixel.
    """
    if not small_thumb:
        return False
    with Image.open(io.BytesIO(small_thumb)) as img:
        extrema = img.getextrema()
        if img.mode == "RGB":
            return extrema == ((255, 255), (255, 255), (255, 255))
        if img.mode == "L":
            return extrema == (255, 255)
    return False


def _is_suspect_all_white(small_thumb: bytes) -> bool:
    """Return True if a fresh thumbnail looks like GPU all-white corruption.

    Creation-time gate: only blobs small enough to plausibly be corruption
    (below SMALL_THUMBNAIL_SAFEGUARD_SIZE) are decoded and pixel-checked.

    Args:
        small_thumb: JPEG blob of the freshly generated small thumbnail.

    Returns:
        True if the blob is below the safeguard size and entirely white.
    """
    return len(small_thumb) < settings.SMALL_THUMBNAIL_SAFEGUARD_SIZE and is_all_white_thumbnail(small_thumb)


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
    # NULL is the only representation of "no thumbnail data" — b"" is
    # forbidden by the thumbnails_no_empty_blobs constraint below.
    small_thumb = models.BinaryField(default=None, null=True)
    medium_thumb = models.BinaryField(default=None, null=True)
    large_thumb = models.BinaryField(default=None, null=True)

    # Reverse ForeignKey relationship
    FileIndex: "RelatedManager[FileIndexModel]"  # From FileIndex.new_ftnail

    class Meta:
        verbose_name = "Image File Thumbnails Cache"
        verbose_name_plural = "Image File Thumbnails Cache"
        # Index set pruned 2026-07-04 against pg_stat_user_indexes evidence
        # (see claude_docs/plans/fable_optimizations-2.md Opt 2b). Removed:
        # thumbnails_sha256_lookup_idx (duplicate of the sha256_hash unique
        # index, which equality lookups now use) and the never-scanned
        # has_medium/has_large partials (nothing queries medium/large-blob
        # existence — only small_thumb drives generation decisions).
        indexes = [
            # Small-thumbnail existence checks (generate_missing_thumbnails
            # pre-filter: sha256_hash__in=... AND small_thumb IS NOT NULL).
            models.Index(
                fields=["sha256_hash"],
                name="thumbnails_has_small_idx",
                condition=models.Q(small_thumb__isnull=False) & ~models.Q(small_thumb=b""),
            ),
            # Missing-thumbnail lookups: lets get_files_needing_thumbnail_shas
            # read the (tiny) set of thumbnail ids awaiting generation instead
            # of probing this table once per file in a directory.
            models.Index(
                fields=["id"],
                name="thumbnails_small_missing_idx",
                condition=models.Q(small_thumb__isnull=True),
            ),
        ]
        constraints = [
            # NULL is the only "no thumbnail data" state; a stray b"" write
            # would silently escape thumbnails_small_missing_idx, so fail loudly.
            models.CheckConstraint(
                name="thumbnails_no_empty_blobs",
                condition=~models.Q(small_thumb=b"") & ~models.Q(medium_thumb=b"") & ~models.Q(large_thumb=b""),
            ),
        ]

    @staticmethod
    def get_or_create_thumbnail_record(
        file_sha256: str,
        suppress_save: bool,
        prefetch_related_thumbnail: list[str] | tuple[str, ...],
        select_related_fileindex: list[str] | tuple[str, ...],
    ) -> "ThumbnailFiles":
        """
        Get or create a thumbnail record for a file.

        Args:
            file_sha256: The sha256 hash of the file to retrieve or create a thumbnail for
            suppress_save: If True, do not save the thumbnail after creation
            prefetch_related_thumbnail: Related fields to prefetch for ThumbnailFiles (required)
            select_related_fileindex: Related fields to select_related for FileIndex (required)

        Returns:
            ThumbnailFiles object, either retrieved from database or newly created

        Raises:
            OrphanedThumbnail: When the ThumbnailFiles record exists but no FileIndex
                records are found for the given SHA256.  The caller should delete
                ``exc.thumbnail`` and skip further processing for this hash.
            OrphanedFileIndex: When a FileIndex record exists but its home_directory
                is None (parent directory deleted).  The caller should delete
                ``exc.thumbnail`` so it can be regenerated if the file returns.
            ThumbnailGenerationError: When the thumbnail pipeline ran but produced an
                invalid result (empty output, all-white GPU corruption, empty blob).
            ValueError: When required parameters are missing or empty.
        """
        if not file_sha256:
            raise ValueError(f"file_sha256 parameter is required and cannot be None or empty, got: {file_sha256!r}")
        if prefetch_related_thumbnail is None:
            raise ValueError("prefetch_related_thumbnail parameter is required")
        if select_related_fileindex is None:
            raise ValueError("select_related_fileindex parameter is required")

        from quickbbs.models import (
            FileIndex,  # inline: circular import (fileindex.py → thumbnails.models)
        )

        # MEMORY MANAGEMENT NOTE:
        # Periodic cache clearing was removed because it conflicts with CIContext recycling.
        # CIContext already recycles every 500 operations (see core_image_thumbnails.py).
        # Clearing caches more frequently (every 100) prevents the recycling from working
        # and causes GPU memory accumulation from repeated CIContext recreations.
        #
        # Cache clearing still happens automatically via CIContext recycling
        # (every 500 operations).
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
                "small_thumb": None,
                "medium_thumb": None,
                "large_thumb": None,
            }
            # defer(): the blob columns are NOT fetched here. Existence is
            # answered by the single-column probe below, generation assigns
            # the blobs in memory, and serving lazy-loads only the one
            # requested size — so the up-to-three-blob transfer the full-row
            # fetch used to pay on every call is avoided entirely.
            thumbnail, created = (
                ThumbnailFiles.objects.defer("small_thumb", "medium_thumb", "large_thumb")
                .prefetch_related(*prefetch_related_thumbnail)
                .get_or_create(sha256_hash=file_sha256, defaults=defaults)
            )

            # CRITICAL: Link FileIndex records to thumbnail FIRST, before checking if thumbnail exists
            # This ensures FileIndex records are linked even if thumbnail was generated by another process
            has_unlinked, updated_count = FileIndex.link_to_thumbnail(file_sha256, thumbnail)

            # Re-check if the thumbnail exists (another worker may have generated
            # it while we waited for the lock). A single-column EXISTS probe over
            # thumbnails_has_small_idx replaces the previous refresh_from_db of
            # all three blob columns — no blob data crosses the wire just to
            # answer "is it generated yet?". NULL is the only "no thumbnail
            # data" state (thumbnails_no_empty_blobs constraint), and blobs are
            # generated together, so probing small_thumb alone is sufficient.
            # Skip the probe on fresh creates — no other process could have
            # modified a record that didn't exist until this transaction.
            if not created and ThumbnailFiles.objects.filter(pk=thumbnail.pk, small_thumb__isnull=False).exists():
                return thumbnail

            # Get a FileIndex record for file path (prefer prefetched)
            index_data_item = thumbnail.FileIndex.first()
            if index_data_item is None:
                index_data_item = FileIndex.objects.select_related(*select_related_fileindex).filter(file_sha256=file_sha256).first()

            # CRITICAL: Handle orphaned ThumbnailFiles by linking to matching FileIndex records
            # This can happen if thumbnail was created but linking failed, or from data migration issues
            if index_data_item is None:
                # No linked FileIndex - attempt to link any FileIndex records with this SHA256.
                # link_to_thumbnail returns updated_count=0 when nothing was linked (no records exist
                # or all are already linked elsewhere), so no separate count()/exists() query needed.
                has_unlinked_fix, updated_count_fix = FileIndex.link_to_thumbnail(file_sha256, thumbnail)
                if updated_count_fix > 0:
                    logger.warning(
                        "Orphaned ThumbnailFiles %s: linked %d FileIndex records for SHA256 %s...",
                        thumbnail.id,
                        updated_count_fix,
                        file_sha256[:16],
                    )
                    # Successfully linked - now fetch one for processing
                    index_data_item = FileIndex.objects.select_related(*select_related_fileindex).filter(file_sha256=file_sha256).first()
                    # Update has_unlinked to trigger save
                    has_unlinked = True
                elif FileIndex.objects.filter(file_sha256=file_sha256).exists():
                    # Records exist but couldn't be linked (already linked elsewhere?)
                    logger.error(
                        "Orphaned ThumbnailFiles %s: FileIndex records exist for SHA256 %s but could not be linked",
                        thumbnail.id,
                        file_sha256[:16],
                    )
                    raise ValueError(f"Cannot link orphaned ThumbnailFiles {thumbnail.id} to FileIndex records")
                else:
                    # No FileIndex exists for this SHA256 - truly orphaned record.
                    # Raise OrphanedThumbnail so the caller can delete it and skip.
                    raise OrphanedThumbnail(thumbnail, file_sha256)

                # If still no FileIndex after linking attempt, raise error
                if index_data_item is None:
                    raise ValueError(f"Orphaned ThumbnailFiles {thumbnail.id}: Failed to get FileIndex after linking")

            if created or has_unlinked:
                if not created:  # If not newly created, save the thumbnail to update it
                    # The blob columns are deferred, so Django excludes them
                    # from this save — only the loaded (non-blob) fields are
                    # written.
                    thumbnail.save()

                # Clear prefetch cache since we just updated the links
                # This ensures thumbnail.FileIndex.all() returns fresh data
                # Use has_unlinked instead of updated_count to handle race conditions
                # (if another process linked records between check and update, updated_count=0 but cache is stale)
                if has_unlinked and hasattr(thumbnail, "_prefetched_objects_cache"):
                    thumbnail._prefetched_objects_cache.clear()

            # File I/O operations (inside transaction to maintain lock during generation)
            # CRITICAL: Check for orphaned FileIndex records (home_directory is None)
            # This can happen when a directory is deleted but FileIndex records remain
            if index_data_item.home_directory is None:
                # Orphaned FileIndex — its parent directory no longer exists.
                # Raise so the caller can delete the ThumbnailFiles record and
                # skip processing; it will be regenerated if the file returns.
                raise OrphanedFileIndex(thumbnail, index_data_item.id, file_sha256)

            # If already marked as generic, check if parent directory has been invalidated
            # If parent is invalidated (rescanned), retry thumbnail creation
            # If parent is NOT invalidated, skip creation (use filetype thumbnail)
            if index_data_item.is_generic_icon:
                # Check if parent directory has been invalidated/rescanned
                try:
                    parent_invalidated = index_data_item.home_directory.Cache_Watcher.invalidated
                except ObjectDoesNotExist:
                    parent_invalidated = False

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
                    # "auto" resolves to CoreImage only when settings.MACINTOSH_OPTIMIZATIONS
                    # is True (and the platform supports it); otherwise PIL.
                    thumbnails = create_thumbnails_from_path(
                        filename,
                        settings.IMAGE_SIZE,
                        output="JPEG",
                        quality=settings.PIL_IMAGE_QUALITY,
                        backend="auto",
                    )

                    # Validate thumbnail is not empty
                    if not thumbnails or not thumbnails.get("small"):
                        raise ThumbnailGenerationError(
                            f"Image thumbnail creation returned empty result for {index_data_item.name}",
                            filename=index_data_item.name,
                        )

                elif filetype.is_movie:
                    # "corevideo" resolves to AVFoundation only when
                    # settings.MACINTOSH_OPTIMIZATIONS is True; otherwise FFmpeg.
                    thumbnails = create_thumbnails_from_path(
                        filename,
                        settings.IMAGE_SIZE,
                        output="JPEG",
                        quality=settings.PIL_IMAGE_QUALITY,
                        backend="corevideo",
                    )
                    # Validate result
                    if not thumbnails or not thumbnails.get("small"):
                        raise ThumbnailGenerationError(
                            f"Video thumbnail creation returned empty result for {index_data_item.name}",
                            filename=index_data_item.name,
                        )

                elif filetype.is_pdf:
                    # "pdf" resolves to PDFKit only when settings.MACINTOSH_OPTIMIZATIONS
                    # is True (and the platform supports it); otherwise PyMuPDF.
                    thumbnails = create_thumbnails_from_path(
                        filename,
                        settings.IMAGE_SIZE,
                        output="JPEG",
                        quality=settings.PIL_IMAGE_QUALITY,
                        backend="pdf",
                    )
                    # Validate result
                    if not thumbnails or not thumbnails.get("small"):
                        raise ThumbnailGenerationError(
                            f"PDF thumbnail creation returned empty result for {index_data_item.name}",
                            filename=index_data_item.name,
                        )
                else:
                    # File type doesn't support custom thumbnails (text, archives, etc.)
                    # Mark ALL files with this SHA256 as generic (not just one)
                    # Use FileIndex classmethod to ensure layout cache is cleared
                    # print(
                    #     f"File type {filetype.fileext} doesn't support custom thumbnails, "
                    #     f"marking all instances as generic: {index_data_item.name}"
                    # )
                    FileIndex.set_generic_icon_for_sha(file_sha256, is_generic=True, clear_cache=True)

                    return thumbnail

                # Creation-time GPU-corruption safeguard (opt-in). A suspiciously
                # small, entirely white small-thumb is regenerated ONCE with the
                # explicit cross-platform backend; the retry result is used
                # unconditionally — genuinely all-white content (e.g. blank PDF
                # pages) is legitimate and must not loop.
                if settings.MAC_OPTIMIZATION_WHITECHECK and _is_suspect_all_white(thumbnails["small"]):
                    fallback_backend: BackendType
                    if filetype.is_image:
                        fallback_backend = "image"
                    elif filetype.is_movie:
                        fallback_backend = "video"
                    else:
                        fallback_backend = "pymupdf"
                    white_defect_msg = (
                        f"All-white thumbnail detected for {index_data_item.name} "
                        f"(sha256={file_sha256}) — regenerating with backend '{fallback_backend}'"
                    )
                    logger.warning("%s", white_defect_msg)
                    print(white_defect_msg)
                    thumbnails = create_thumbnails_from_path(
                        filename,
                        settings.IMAGE_SIZE,
                        output="JPEG",
                        quality=settings.PIL_IMAGE_QUALITY,
                        backend=fallback_backend,
                    )

                thumbnail.small_thumb = thumbnails["small"]
                thumbnail.medium_thumb = thumbnails["medium"]
                thumbnail.large_thumb = thumbnails["large"]

                if not suppress_save:
                    thumbnail.save(update_fields=["small_thumb", "medium_thumb", "large_thumb"])

                # If this was a retry (file was marked generic), turn off generic flag
                # on success for ALL instances
                # Use FileIndex classmethod to ensure layout cache is cleared
                if index_data_item.is_generic_icon:
                    # print(f"Thumbnail creation succeeded on retry for {index_data_item.name}, " f"turning off generic flag for all instances")
                    FileIndex.set_generic_icon_for_sha(file_sha256, is_generic=False, clear_cache=True)

            except FileNotFoundError as e:
                # File was moved or deleted — mark this specific FileIndex as delete_pending
                # rather than marking ALL files with this SHA256 as generic.
                # Other FileIndex records with the same SHA256 may still exist at valid paths.
                logger.warning("File not found for %s: %s", index_data_item.name, e)
                index_data_item.delete_pending = True
                index_data_item.save(update_fields=["delete_pending"])

                # Clear layout cache so gallery view reflects the removed file
                if index_data_item.home_directory_id:
                    clear_layout_cache_for_directories({index_data_item.home_directory_id})

            except MediaProcessingError as e:
                # File exists but could not be loaded as an image (corrupt, wrong format, etc.)
                # Log at WARNING (not ERROR) since this is a data issue, not a code issue.
                logger.warning(
                    "Unreadable image file, marking as generic icon: %s (%s)",
                    filename,
                    e,
                )
                if not index_data_item.is_generic_icon:
                    FileIndex.set_generic_icon_for_sha(file_sha256, is_generic=True, clear_cache=True)

            # TODO: narrow to (OSError, RuntimeError, ValueError) once thumbnail backend
            # exception types are fully catalogued across PIL/PyMuPDF/ffmpeg
            except Exception as e:
                # Any error during thumbnail creation - mark ALL files with this SHA256 as generic
                # Use FileIndex classmethod to ensure layout cache is cleared
                logger.exception("Thumbnail creation failed for %s: %s", index_data_item.name, e)
                if not index_data_item.is_generic_icon:
                    FileIndex.set_generic_icon_for_sha(file_sha256, is_generic=True, clear_cache=True)

            return thumbnail

    def number_of_indexdata_references(self) -> int:
        """
        Return the number of FileIndex references for this thumbnail.

        Returns:
            Count of FileIndex objects referencing this thumbnail
        """
        from quickbbs.models import (
            FileIndex,  # inline: circular import (fileindex.py → thumbnails.models)
        )

        return FileIndex.objects.filter(file_sha256=self.sha256_hash).count()

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
                return self.small_thumb not in _EMPTY_THUMB_VALUES
            case "medium":
                return self.medium_thumb not in _EMPTY_THUMB_VALUES
            case "large":
                return self.large_thumb not in _EMPTY_THUMB_VALUES
        return False

    def invalidate_thumb(self) -> None:
        """
        Clear all thumbnail data for regeneration.

        Sets all thumbnail binary fields (small, medium, large) to None —
        NULL is the canonical "no thumbnail data" state.
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
        self.small_thumb = None
        self.medium_thumb = None
        self.large_thumb = None

    def retrieve_sized_tnail(self, size: str = "small") -> bytes:
        """
        Get thumbnail blob of specified size.

        Args:
            size: The size string (small, medium, or large)

        Returns:
            Binary blob containing the image data for the specified size,
            or b"" when no thumbnail has been generated (column is NULL).
        """
        blobdata: bytes | memoryview | None = b""
        match size.lower():
            case "small":
                blobdata = self.small_thumb
            case "medium":
                blobdata = self.medium_thumb
            case "large":
                blobdata = self.large_thumb
        return bytes(blobdata) if blobdata else b""

    def send_thumbnail(
        self,
        filename_override: str | None = None,
        fext_override: str | None = None,
        size: str = "small",
        index_data_item: "FileIndexModel | None" = None,
    ):
        """
        Send thumbnail as HTTP response with appropriate headers.

        Args:
            filename_override: Optional filename to use instead of the original
            fext_override: Unused; retained for API compatibility
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
        # Get FileIndex to check if file is marked as generic.
        # Callers in hot paths should always supply index_data_item to avoid this query.
        # select_related("filetype") is required: the generic check below reads
        # filetype.generic, which would otherwise lazy-load the filetype row
        # with an extra query per call. "filetype" must also appear in only()
        # so the joined row is loaded rather than deferred, and "new_ftnail"
        # must be loaded because the reverse related manager attaches self as
        # the known related object — reading a deferred FK would trigger a
        # per-call lazy load.
        if not index_data_item:
            try:
                index_data_item = self.FileIndex.select_related("filetype").only("name", "is_generic_icon", "filetype", "new_ftnail").first()
            except (AttributeError, ObjectDoesNotExist) as e:
                # FileIndex relationship may not exist for this thumbnail
                logger.debug("FileIndex not available for thumbnail %s: %s", self.pk, e)

        # If file is marked as generic icon OR filetype is generic, use filetype thumbnail instead
        # This handles both explicit marking (is_generic_icon) and filetype-based generic status (filetype.generic)
        if index_data_item is not None and (index_data_item.is_generic_icon or index_data_item.filetype.generic):
            return index_data_item.filetype.send_thumbnail()

        # Use provided index_data_item for filename
        if index_data_item:
            filename = filename_override or index_data_item.name
        else:
            filename = filename_override or "thumbnail"

        mtype = "image/jpeg"
        blob = self.retrieve_sized_tnail(size=size)

        # Validate that thumbnail blob is not empty
        if not blob:
            raise ThumbnailGenerationError(f"Thumbnail blob is empty for {filename}", filename=filename)

        return send_file_response(
            filename=filename,
            content_to_send=io.BytesIO(blob),
            mtype=mtype or "image/jpeg",
            attachment=False,
            expiration=300,
        )

    # Batch thumbnail generation lives in quickbbs.tasks.generate_missing_thumbnails
    # (suppress_save=True + one bulk_update). Image decode there is sequential by
    # design: ThreadPoolExecutor with the ORM is forbidden (see
    # .claude/critical-runtime.md) and ProcessPoolExecutor cannot spawn from the
    # daemon worker threads that run tasks (see quickbbs/common.py).
    @classmethod
    def get_files_needing_thumbnail_shas(cls, directory: "DirectoryIndex", sort_ordering: int) -> "QuerySet":
        """
        Return a queryset of file SHA256 hashes that don't have valid thumbnails.

        A file needs a thumbnail when either:
        1. It has no ThumbnailFiles link (``new_ftnail__isnull=True``), or
        2. Its linked ThumbnailFiles row has ``small_thumb`` NULL — the canonical
           "no thumbnail data" state (a record is linked before generation
           completes; see get_or_create_thumbnail_record).

        The NULL condition is evaluated as a subquery over the
        ``thumbnails_small_missing_idx`` partial index, so the planner hashes
        the (tiny) set of missing-thumbnail ids instead of probing the
        thumbnails table once per file in the directory.

        Returns a queryset (not a list) to allow caller flexibility:
        - Slice for batch processing: ``qs[:limit]``
        - Count without materialising: ``qs.count()``
        - Existence check: ``qs.exists()``

        Args:
            directory: DirectoryIndex object whose files to check
            sort_ordering: Sort order to apply to the file query

        Returns:
            QuerySet of file_sha256 values for files needing thumbnail generation.
        """
        missing_thumb_ids = cls.objects.filter(small_thumb__isnull=True).values("id")
        # cast: files_in_dir with distinct=False always returns a QuerySet,
        # but its union return type can't be narrowed by mypy.
        return (
            cast(
                "QuerySet[FileIndexModel]",
                directory.files_in_dir(sort=sort_ordering, fields_only=("file_sha256",), select_related=()),
            )
            .filter(Q(new_ftnail__isnull=True) | Q(new_ftnail_id__in=missing_thumb_ids))
            .values_list("file_sha256", flat=True)
        )

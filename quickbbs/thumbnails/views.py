"""
Thumbnail serving views for QuickBBS Gallery.

Handles serving directory and file thumbnails with cover image selection,
thumbnail generation, and fallback to generic icons.
"""

import logging
import warnings

from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from django.http import Http404, HttpResponseBadRequest
from PIL import Image

from quickbbs.fileindex import FILEINDEX_SR_FILETYPE_HOME_VIRTUAL
from quickbbs.models import DirectoryIndex, FileIndex
from thumbnails.exceptions import OrphanedFileIndex, OrphanedThumbnail
from thumbnails.models import THUMBNAILFILES_PR_FILEINDEX_FILETYPE, ThumbnailFiles

logger = logging.getLogger()

warnings.simplefilter("ignore", Image.DecompressionBombWarning)


def thumbnail2_dir(request: WSGIRequest, dir_sha256: str | None = None):  # pylint: disable=unused-argument
    """
    Serve directory thumbnail using prioritized cover image selection.

    Uses DirectoryIndex.get_cover_image() to select thumbnails based on priority filenames
    (e.g., "cover", "title") before falling back to the first available file.

    Args:
        request: Django Request object
        dir_sha256: the sha256 of the directory

    Returns:
        The image of the thumbnail to send

    Raises:
        Http404: If the directory cannot be found
    """
    # Use optimized model method with prefetched relationships
    success, directory = DirectoryIndex.search_for_directory_by_sha(dir_sha256)
    if not success:
        logger.warning("Directory not found for thumbnail request: %s", dir_sha256)
        raise Http404(f"Directory not found: {dir_sha256}")

    # If directory already has a thumbnail set AND cache is valid, try to return it
    try:
        if directory.thumbnail and directory.thumbnail.new_ftnail and directory.is_cached:
            try:
                return directory.thumbnail.new_ftnail.send_thumbnail(fext_override=".jpg", size="small", index_data_item=directory.thumbnail)
            except (OSError, ValueError, AttributeError) as e:
                # If thumbnail serving fails, fall through to cover image logic
                print(f"Directory thumbnail serving failed for {directory.fqpndirectory}: {e}")
                # Continue to cover image selection below
    except FileIndex.DoesNotExist:
        # Thumbnail FK points to deleted/non-existent record - clear it and regenerate
        print(f"Thumbnail reference broken for {directory.fqpndirectory} - regenerating")
        directory.invalidate_thumb()

    # Cache is invalidated or no thumbnail set - regenerate using get_cover_image
    # Clear any existing thumbnail reference
    if not directory.is_cached:
        directory.invalidate_thumb()

    # Use get_cover_image to find the best cover image for this directory
    cover_image = directory.get_cover_image()

    # If no cover image found, try syncing from disk and retry
    if not cover_image:
        from quickbbs.directoryindex import (
            update_database_from_disk,  # pylint: disable=import-outside-toplevel
        )

        update_database_from_disk(directory)
        cover_image = directory.get_cover_image()

    # If still no cover image found, return default directory icon
    if not cover_image:
        return directory.filetype.send_thumbnail()

    # Set directory thumbnail to the selected cover image
    # Wrap in transaction to prevent race conditions with concurrent requests
    with transaction.atomic():
        directory.thumbnail = cover_image
        directory.is_generic_icon = False
        directory.save(update_fields=["thumbnail", "is_generic_icon"])
        # Flag the file as the directory's cover so future
        # get_cover_image() calls short-circuit to it directly
        if not cover_image.cover_image:
            cover_image.cover_image = True
            cover_image.save(update_fields=["cover_image"])

    # Ensure thumbnail record exists
    if not directory.thumbnail.new_ftnail:
        try:
            thumbnail = ThumbnailFiles.get_or_create_thumbnail_record(
                directory.thumbnail.file_sha256,
                suppress_save=False,
                prefetch_related_thumbnail=THUMBNAILFILES_PR_FILEINDEX_FILETYPE,
                select_related_fileindex=("filetype",),
            )
        except (OrphanedThumbnail, OrphanedFileIndex) as exc:
            logger.warning(
                "Deleting thumbnail for directory cover %s: %s",
                directory.fqpndirectory,
                exc,
            )
            exc.thumbnail.delete()
            return directory.filetype.send_thumbnail()
        # Wrap in transaction to prevent race conditions
        with transaction.atomic():
            directory.thumbnail.new_ftnail = thumbnail
            directory.thumbnail.save(update_fields=["new_ftnail"])

    # Try to return the thumbnail, fall back to generic icon on error
    try:
        return directory.thumbnail.new_ftnail.send_thumbnail(fext_override=".jpg", size="small", index_data_item=directory.thumbnail)
    except (OSError, ValueError, AttributeError) as e:
        # If thumbnail generation/serving fails, mark directory as generic and return filetype icon
        print(f"Directory thumbnail generation failed for {directory.fqpndirectory}: {e}")
        # Wrap in transaction to prevent race conditions
        with transaction.atomic():
            directory.is_generic_icon = True
            directory.save(update_fields=["is_generic_icon"])

        return directory.filetype.send_thumbnail()


def _serve_existing_thumbnail(request: WSGIRequest, sha256: str, thumbsize: str):
    """
    Serve an already-generated thumbnail without the generation lock.

    Read-only fast path for thumbnail2_file: resolves the FileIndex via the
    cached get_by_sha256 lookup, honors the generic-icon and link
    short-circuits, then serves the requested blob size loaded with a single
    single-column SELECT.

    Args:
        request: Django Request object
        sha256: The sha256 of the file - FileIndex object
        thumbsize: Validated thumbnail size (small, medium, or large)

    Returns:
        An HTTP response when the request can be satisfied without generation,
        or None when the caller must fall through to the locked
        get_or_create_thumbnail_record path (record or requested size missing).
    """
    index_data_item = FileIndex.get_by_sha256(sha256, unique=False, select_related=FILEINDEX_SR_FILETYPE_HOME_VIRTUAL)
    if index_data_item is None:
        return None

    # Return generic icon if filetype is generic OR if file is marked as generic icon
    if index_data_item.filetype.generic or index_data_item.is_generic_icon:
        return index_data_item.filetype.send_thumbnail()

    # Handle link files: if this is a link type with a virtual_directory,
    # delegate to the virtual directory's thumbnail
    if index_data_item.filetype.is_link and index_data_item.virtual_directory:
        return thumbnail2_dir(request, index_data_item.virtual_directory.dir_fqpn_sha256)

    existing_thumbnail = ThumbnailFiles.objects.only("id", "sha256_hash", f"{thumbsize}_thumb").filter(sha256_hash=sha256).first()
    if existing_thumbnail is None or not existing_thumbnail.retrieve_sized_tnail(size=thumbsize):
        return None

    try:
        return existing_thumbnail.send_thumbnail(
            filename_override=index_data_item.name,
            fext_override=".jpg",
            size=thumbsize,
            index_data_item=index_data_item,
        )
    except (OSError, ValueError, AttributeError) as e:
        # If thumbnail serving fails, mark ALL files with this SHA256 as generic
        # Use FileIndex classmethod to ensure layout cache is cleared
        print(f"Thumbnail serving failed for {index_data_item.name}: {e}")
        FileIndex.set_generic_icon_for_sha(sha256, is_generic=True, clear_cache=True)
        return index_data_item.filetype.send_thumbnail()


def thumbnail2_file(request: WSGIRequest, sha256: str):
    """
    Create and serve a thumbnail for a specific file.

    Steady state (thumbnail already generated) is served by the read-only
    fast path in _serve_existing_thumbnail: one cached FileIndex lookup plus
    one single-column SELECT of the requested blob size. Only when the record
    or the requested size is missing does the request fall through to
    get_or_create_thumbnail_record, which takes the transaction + advisory
    lock needed to serialize generation.

    Args:
        request: Django Request object
        sha256: The sha256 of the file - FileIndex object

    Returns:
        The sent thumbnail
    """
    thumbsize = request.GET.get("size", "small").lower()
    if thumbsize not in ("small", "medium", "large"):
        thumbsize = "small"

    fast_response = _serve_existing_thumbnail(request, sha256, thumbsize)
    if fast_response is not None:
        return fast_response

    # Slow path: no thumbnail record, or the requested size is not yet
    # generated — take the locked generation path.
    try:
        thumbnail = ThumbnailFiles.get_or_create_thumbnail_record(
            sha256, suppress_save=False, prefetch_related_thumbnail=THUMBNAILFILES_PR_FILEINDEX_FILETYPE, select_related_fileindex=("filetype",)
        )
    except (OrphanedThumbnail, OrphanedFileIndex) as exc:
        logger.warning(
            "Deleting thumbnail for file SHA256 %s: %s",
            sha256,
            exc,
        )
        exc.thumbnail.delete()
        return HttpResponseBadRequest(content="File no longer exists in gallery.")

    # Get associated FileIndex - try reverse FK first, fall back to model method
    try:
        index_data_item = thumbnail.FileIndex.first()
        if not index_data_item:
            # Fallback: prefetch cache might be stale, use cached model method
            index_data_item = FileIndex.get_by_sha256(sha256, unique=False, select_related=FILEINDEX_SR_FILETYPE_HOME_VIRTUAL)
            if not index_data_item:
                return HttpResponseBadRequest(content="No associated file data found.")
    except (AttributeError, IndexError):
        return HttpResponseBadRequest(content="Error accessing file data.")

    # Return generic icon if filetype is generic OR if file is marked as generic icon
    if index_data_item.filetype.generic or index_data_item.is_generic_icon:
        return index_data_item.filetype.send_thumbnail()

    # Handle link files: if this is a link type with a virtual_directory,
    # delegate to the virtual directory's thumbnail
    if index_data_item.filetype.is_link and index_data_item.virtual_directory:
        return thumbnail2_dir(request, index_data_item.virtual_directory.dir_fqpn_sha256)

    # Try to return custom thumbnail, fall back to generic icon on error
    try:
        return thumbnail.send_thumbnail(
            filename_override=index_data_item.name,
            fext_override=".jpg",
            size=thumbsize,
            index_data_item=index_data_item,
        )
    except (OSError, ValueError, AttributeError) as e:
        # If thumbnail generation/serving fails, mark ALL files with this SHA256 as generic
        # Use FileIndex classmethod to ensure layout cache is cleared
        print(f"Thumbnail generation failed for {index_data_item.name}: {e}")
        FileIndex.set_generic_icon_for_sha(sha256, is_generic=True, clear_cache=True)
        return index_data_item.filetype.send_thumbnail()

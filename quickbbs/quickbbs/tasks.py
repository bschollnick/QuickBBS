"""Steady-queue background tasks for QuickBBS."""

from __future__ import annotations

import logging

from django.tasks import task
from steady_queue.concurrency import limits_concurrency

from frontend.managers import clear_layout_cache_for_directories
from thumbnails.models import THUMBNAILFILES_PR_FILEINDEX_FILETYPE, ThumbnailFiles

logger = logging.getLogger(__name__)


@limits_concurrency(key="thumbnail_generation", to=2)
@task()
def generate_missing_thumbnails(
    files_needing_thumbnails: list[str],
    directory_pk: int | None = None,
    batchsize: int = 5,
) -> dict[str, bool]:
    """
    Batch-create thumbnails for files that are missing them.

    Processes each SHA256 hash synchronously via
    ThumbnailFiles.get_or_create_thumbnail_record with suppress_save=True,
    collects the modified thumbnail objects, then writes them all to the
    database in a single bulk_update call. Clears the layout cache for the
    directory afterward so cached counts reflect the new thumbnails.

    Args:
        files_needing_thumbnails: SHA256 hashes needing thumbnail generation.
        directory_pk: Primary key of the directory containing these files.
            When None, cache clearing is skipped (used by bulk maintenance commands).
        batchsize: Maximum number of thumbnails to process (default: 5).

    Returns:
        Dictionary mapping each SHA256 hash to its success status.
    """
    if not files_needing_thumbnails:
        return {}

    sha256_list = files_needing_thumbnails[:batchsize]
    logger.info("Processing %d thumbnails", len(sha256_list))

    results: dict[str, bool] = {}
    thumbnails_to_update: list[ThumbnailFiles] = []

    for sha256 in sha256_list:
        try:
            thumbnail = ThumbnailFiles.get_or_create_thumbnail_record(
                sha256,
                suppress_save=True,
                prefetch_related_thumbnail=THUMBNAILFILES_PR_FILEINDEX_FILETYPE,
                select_related_fileindex=("filetype",),
            )
            # Only queue for bulk_update if thumbnail data was actually generated
            if thumbnail.small_thumb:
                thumbnails_to_update.append(thumbnail)
            results[sha256] = True
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Error creating thumbnail for %s", sha256)
            results[sha256] = False

    if thumbnails_to_update:
        ThumbnailFiles.objects.bulk_update(
            thumbnails_to_update,
            ["small_thumb", "medium_thumb", "large_thumb"],
        )

    if any(results.values()) and directory_pk is not None:
        cleared_count = clear_layout_cache_for_directories({directory_pk})
        if cleared_count:
            logger.info(
                "Cleared %d layout cache entries for directory after thumbnail processing",
                cleared_count,
            )

    successful_count = sum(1 for v in results.values() if v)
    if successful_count > 0:
        logger.info(
            "Successfully processed %d/%d thumbnails, bulk-updated %d records",
            successful_count,
            len(sha256_list),
            len(thumbnails_to_update),
        )

    return results

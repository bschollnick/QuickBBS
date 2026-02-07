"""
Function to add missing thumbnails for files in the database.

This module scans FileIndex for files missing thumbnails and generates them.
Only processes files with non-generic filetypes (images, videos, PDFs).
"""

from __future__ import annotations

import time
from itertools import batched

from django.db import close_old_connections
from django.db.models import Q

from quickbbs.models import FileIndex
from quickbbs.tasks import generate_missing_thumbnails
from thumbnails.models import ThumbnailFiles

# Batch size for bulk_create and bulk_update operations
BULK_UPDATE_BATCH_SIZE = 250


def _bulk_create_thumbnail_records(unique_sha256s: list[str]) -> int:
    """
    Create ThumbnailFiles records in bulk for SHA256 hashes that don't have records.

    Args:
        unique_sha256s: List of unique SHA256 hashes to create records for

    Returns:
        Number of records created
    """
    if not unique_sha256s:
        return 0

    # Find which SHA256s already have ThumbnailFiles records
    existing_sha256s = set(ThumbnailFiles.objects.filter(sha256_hash__in=unique_sha256s).values_list("sha256_hash", flat=True))

    # Create records only for SHA256s that don't exist
    records_to_create = [
        ThumbnailFiles(
            sha256_hash=sha256,
            small_thumb=b"",
            medium_thumb=b"",
            large_thumb=b"",
        )
        for sha256 in unique_sha256s
        if sha256 not in existing_sha256s
    ]

    if records_to_create:
        ThumbnailFiles.objects.bulk_create(
            records_to_create,
            batch_size=BULK_UPDATE_BATCH_SIZE,
            ignore_conflicts=True,  # Skip if another process created it
        )

    return len(records_to_create)


def _bulk_link_fileindex_to_thumbnails(sha256_list: list[str]) -> int:
    """
    Link FileIndex records to their ThumbnailFiles records in bulk.

    Args:
        sha256_list: List of SHA256 hashes to link

    Returns:
        Number of FileIndex records updated
    """
    if not sha256_list:
        return 0

    # Get ThumbnailFiles records for these SHA256s
    thumbnail_map = {t.sha256_hash: t for t in ThumbnailFiles.objects.filter(sha256_hash__in=sha256_list)}

    # Get FileIndex records that need linking
    files_to_update = list(
        FileIndex.objects.filter(
            file_sha256__in=sha256_list,
            new_ftnail__isnull=True,
        ).only("id", "file_sha256", "new_ftnail")
    )

    # Update the new_ftnail field
    for file_record in files_to_update:
        thumbnail = thumbnail_map.get(file_record.file_sha256)
        if thumbnail:
            file_record.new_ftnail = thumbnail

    # Bulk update
    if files_to_update:
        FileIndex.objects.bulk_update(
            files_to_update,
            fields=["new_ftnail"],
            batch_size=BULK_UPDATE_BATCH_SIZE,
        )

    return len(files_to_update)


def add_thumbnails(max_count: int = 0) -> None:
    """
    Scan FileIndex for files missing thumbnails and generate them.

    Two-pass approach:
    1. Ensure all thumbnailable files have a ThumbnailFiles record (uses bulk operations)
    2. Generate thumbnails for records with empty thumbnail data

    Only processes files with thumbnailable filetypes:
    - is_image=True (images: jpg, png, gif, etc.)
    - is_pdf=True (PDF documents)
    - is_movie=True (videos: mp4, avi, etc.)

    Note: --start is not supported for thumbnail operations because thumbnails are
    content-addressed by SHA256. A thumbnail benefits all files with the same hash,
    regardless of directory location.

    Args:
        max_count: Maximum number of thumbnails to generate (0 = unlimited)

    Returns:
        None
    """
    print("=" * 60)
    print("Adding missing thumbnails for files in database")
    print("=" * 60)

    # ========================================================================
    # PASS 1: Ensure all thumbnailable files have a ThumbnailFiles record
    # Uses bulk_create and bulk_update for efficiency
    # ========================================================================
    print("\nPASS 1: Ensuring ThumbnailFiles records exist (bulk mode)...")

    # Get thumbnailable files with no thumbnail record
    # EXCLUDE link files (.alias/.link) - they're marked thumbnailable to avoid generic icons
    # but attempting to generate thumbnails for them causes ImageIO memory leaks
    files_without_records = FileIndex.objects.filter(
        Q(new_ftnail__isnull=True)
        & Q(is_generic_icon=False)
        & Q(delete_pending=False)
        & Q(filetype__is_link=False)  # Exclude alias/link files
        & (Q(filetype__is_image=True) | Q(filetype__is_pdf=True) | Q(filetype__is_movie=True))
    )

    # Get list of SHA256 values (may have duplicates for files with same content)
    sha256_list = list(files_without_records.values_list("file_sha256", flat=True))
    total_files = len(sha256_list)

    # Get unique SHA256s for bulk_create
    unique_sha256s = list(set(sha256_list))
    print(f"Found {total_files} files without ThumbnailFiles records ({len(unique_sha256s)} unique SHA256s)")

    if total_files > 0:
        print("Creating ThumbnailFiles records in bulk...")
        start_time = time.time()

        # Process in batches
        total_created = 0
        total_linked = 0

        for i in range(0, len(unique_sha256s), BULK_UPDATE_BATCH_SIZE):
            batch = unique_sha256s[i : i + BULK_UPDATE_BATCH_SIZE]

            # Bulk create ThumbnailFiles records
            created = _bulk_create_thumbnail_records(batch)
            total_created += created

            # Bulk link FileIndex records to ThumbnailFiles
            linked = _bulk_link_fileindex_to_thumbnails(batch)
            total_linked += linked

            # Progress indicator
            processed = min(i + BULK_UPDATE_BATCH_SIZE, len(unique_sha256s))
            if processed % 1000 == 0 or processed == len(unique_sha256s):
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                print(f"  Processed {processed}/{len(unique_sha256s)} unique SHA256s ({rate:.1f}/sec)...")
                close_old_connections()

        elapsed = time.time() - start_time
        print(f"Pass 1 complete: Created {total_created} ThumbnailFiles records, linked {total_linked} FileIndex records")
        print(f"  Time: {elapsed:.1f}s")
        close_old_connections()
    else:
        print("All thumbnailable files already have ThumbnailFiles records")

    # ========================================================================
    # PASS 2: Generate thumbnails for empty ThumbnailFiles records
    # ========================================================================
    print("\nPASS 2: Generating missing thumbnails...")

    # Simple query - no reverse FK joins needed since we're not filtering by path
    empty_thumbnails_qs = ThumbnailFiles.objects.filter(
        small_thumb__in=[b"", None],
    )

    if max_count > 0:
        empty_thumbnails_qs = empty_thumbnails_qs[:max_count]
        print(f"Limiting to {max_count} thumbnails...")

    # Get list of SHA256 values only (lightweight - no ThumbnailFiles objects cached)
    sha256_list = list(empty_thumbnails_qs.values_list("sha256_hash", flat=True))
    count = len(sha256_list)
    print(f"Found {count} thumbnails to generate")

    if count == 0:
        print("All thumbnails are already generated")
        return

    # Enqueue thumbnail generation tasks via steady-queue
    print(f"\nEnqueuing {count} thumbnails to steady-queue...")
    enqueued = 0
    task_count = 0

    for batch in batched(sha256_list, BULK_UPDATE_BATCH_SIZE):
        batch_size = len(batch)
        generate_missing_thumbnails.enqueue(
            files_needing_thumbnails=list(batch),
            batchsize=batch_size,
        )
        enqueued += batch_size
        task_count += 1

        if enqueued % 1000 == 0 or enqueued == count:
            print(f"  Enqueued {enqueued}/{count} thumbnails...")

    print("=" * 60)
    print(f"Enqueued {enqueued} thumbnails in {task_count} tasks")
    print("Thumbnails will be generated asynchronously by steady-queue workers.")
    print("Start a worker with: python manage.py steady_queue")
    print("=" * 60)

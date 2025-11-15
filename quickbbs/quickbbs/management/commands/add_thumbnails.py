"""
Function to add missing thumbnails for files in the database.

This module scans FileIndex for files missing thumbnails and generates them.
Only processes files with non-generic filetypes (images, videos, PDFs).
"""

import time

from django.db import close_old_connections
from django.db.models import Q
from thumbnails.models import ThumbnailFiles

from quickbbs.models import FileIndex


def add_thumbnails(max_count: int = 0) -> None:
    """
    Scan FileIndex for files missing thumbnails and generate them.

    Two-pass approach:
    1. Ensure all thumbnailable files have a ThumbnailFiles record
    2. Generate thumbnails for records with empty thumbnail data

    Only processes files with thumbnailable filetypes:
    - is_image=True (images: jpg, png, gif, etc.)
    - is_pdf=True (PDF documents)
    - is_movie=True (videos: mp4, avi, etc.)

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
    # ========================================================================
    print("\nPASS 1: Ensuring ThumbnailFiles records exist...")

    # Get thumbnailable files with no thumbnail record
    # Note: Don't use distinct() - we want ALL unlinked records to get linked
    # to their existing ThumbnailFiles record (by SHA256)
    files_without_records = FileIndex.objects.filter(
        Q(new_ftnail__isnull=True)
        & Q(is_generic_icon=False)
        & Q(delete_pending=False)
        & (Q(filetype__is_image=True) | Q(filetype__is_pdf=True) | Q(filetype__is_movie=True))
    )

    count = files_without_records.count()
    print(f"Found {count} files without ThumbnailFiles records")

    if count > 0:
        print("Creating ThumbnailFiles records and generating thumbnails...")
        processed = 0

        # Fetch all records without using iterator to avoid server-side cursor issues
        for file_record in files_without_records.all():
            try:
                # Create ThumbnailFiles record and generate thumbnail
                # (automatically skips if thumbnail already exists)
                ThumbnailFiles.get_or_create_thumbnail_record(file_sha256=file_record.file_sha256, suppress_save=False)
            except Exception as e:  # pylint: disable=broad-exception-caught
                print(f"ERROR processing {file_record.name}: {e}")

            processed += 1

            if processed % 1000 == 0:
                print(f"  Processed {processed} files...")
                close_old_connections()

        print(f"Total processed: {processed} files")
        close_old_connections()
    else:
        print("All thumbnailable files already have ThumbnailFiles records")

    # ========================================================================
    # PASS 2: Generate thumbnails for empty ThumbnailFiles records
    # ========================================================================
    print("\nPASS 2: Generating missing thumbnails...")

    # Find ThumbnailFiles with empty small_thumb
    empty_thumbnails = ThumbnailFiles.objects.filter(Q(small_thumb__in=[b"", None]))

    if max_count > 0:
        empty_thumbnails = empty_thumbnails[:max_count]
        print(f"Limiting to {max_count} thumbnails...")

    count = empty_thumbnails.count()
    print(f"Found {count} thumbnails to generate")

    if count == 0:
        print("All thumbnails are already generated")
        return

    # Generate thumbnails
    print(f"\nGenerating {count} thumbnails...")
    processed = 0
    success = 0
    errors = 0
    start_time = time.time()

    # Fetch all records without using iterator to avoid server-side cursor issues
    for thumbnail in empty_thumbnails.all():
        try:
            # Get any FileIndex record for this SHA256 (for file path)
            index_record = FileIndex.objects.filter(file_sha256=thumbnail.sha256_hash).first()

            if not index_record:
                print(f"Warning: No FileIndex for SHA256 {thumbnail.sha256_hash}")
                errors += 1
                processed += 1
                continue

            # Generate thumbnail (this will populate small/medium/large)
            ThumbnailFiles.get_or_create_thumbnail_record(file_sha256=thumbnail.sha256_hash, suppress_save=False)
            success += 1
            processed += 1

            # Progress
            if processed % 50 == 0:
                elapsed = time.time() - start_time
                rate = success / elapsed if elapsed > 0 else 0
                print(f"  {processed}/{count} " f"(Success: {success}, Errors: {errors}) " f"({rate:.1f}/sec)")

            # Cleanup - close connections every 1000 entries
            if processed % 1000 == 0:
                close_old_connections()

        except Exception as e:  # pylint: disable=broad-exception-caught
            errors += 1
            processed += 1
            print(f"Error: {e}")

    close_old_connections()

    # Statistics
    total_time = time.time() - start_time
    rate = success / total_time if total_time > 0 else 0

    print("=" * 60)
    print("Complete:")
    print(f"  Total processed: {processed}")
    print(f"  Success: {success}")
    print(f"  Errors: {errors}")
    print(f"  Time: {total_time:.1f}s")
    print(f"  Rate: {rate:.1f} thumbnails/sec")
    print("=" * 60)

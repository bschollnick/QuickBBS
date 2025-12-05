"""
Function to add missing thumbnails for files in the database.

This module scans FileIndex for files missing thumbnails and generates them.
Only processes files with non-generic filetypes (images, videos, PDFs).
"""

import time

from django.db import close_old_connections
from django.db.models import Q
from thumbnails.models import ThumbnailFiles, THUMBNAILFILES_PR_FILEINDEX_FILETYPE

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
    # EXCLUDE link files (.alias/.link) - they're marked thumbnailable to avoid generic icons
    # but attempting to generate thumbnails for them causes ImageIO memory leaks
    files_without_records = FileIndex.objects.filter(
        Q(new_ftnail__isnull=True)
        & Q(is_generic_icon=False)
        & Q(delete_pending=False)
        & Q(filetype__is_link=False)  # Exclude alias/link files
        & (Q(filetype__is_image=True) | Q(filetype__is_pdf=True) | Q(filetype__is_movie=True))
    )

    # Get list of SHA256 values only (lightweight - no FileIndex objects cached)
    # This avoids memory spike from Django's queryset result caching
    sha256_list = list(files_without_records.values_list('file_sha256', flat=True))
    count = len(sha256_list)
    print(f"Found {count} files without ThumbnailFiles records")

    if count > 0:
        print("Creating ThumbnailFiles records and generating thumbnails...")
        processed = 0

        # Iterate through SHA256 list (no queryset caching, no server-side cursor)
        for file_sha256 in sha256_list:
            try:
                # Create ThumbnailFiles record and generate thumbnail
                # (automatically skips if thumbnail already exists)
                # get_or_create_thumbnail_record fetches FileIndex internally
                ThumbnailFiles.get_or_create_thumbnail_record(
                    file_sha256=file_sha256,
                    suppress_save=False,
                    prefetch_related_thumbnail=THUMBNAILFILES_PR_FILEINDEX_FILETYPE,
                    select_related_fileindex=("filetype",),
                )
            except Exception as e:  # pylint: disable=broad-exception-caught
                print(f"ERROR processing SHA256 {file_sha256}: {e}")

            processed += 1

            # Progress output and periodic cleanup
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
    # EXCLUDE link files - attempting to generate thumbnails causes ImageIO memory leaks
    # Filter by FileIndex filetype (must use FileIndex__ prefix for reverse relationship)
    # CRITICAL: Use distinct() because joining through FileIndex can create duplicates
    empty_thumbnails_qs = ThumbnailFiles.objects.filter(
        Q(small_thumb__in=[b"", None])
        & Q(FileIndex__filetype__is_link=False)
 #       & (Q(FileIndex__filetype__is_image=True) | Q(FileIndex__filetype__is_pdf=True) | Q(FileIndex__filetype__is_movie=True))
    ).distinct()

    if max_count > 0:
        empty_thumbnails_qs = empty_thumbnails_qs[:max_count]
        print(f"Limiting to {max_count} thumbnails...")

    # Get list of SHA256 values only (lightweight - no ThumbnailFiles objects cached)
    sha256_list = list(empty_thumbnails_qs.values_list('sha256_hash', flat=True))
    count = len(sha256_list)
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

    # Iterate through SHA256 list (no queryset caching, no server-side cursor)
    for sha256_hash in sha256_list:
        try:
            # Generate thumbnail (this will populate small/medium/large)
            # get_or_create_thumbnail_record fetches FileIndex internally
            ThumbnailFiles.get_or_create_thumbnail_record(
                file_sha256=sha256_hash,
                suppress_save=False,
                prefetch_related_thumbnail=THUMBNAILFILES_PR_FILEINDEX_FILETYPE,
                select_related_fileindex=("filetype",),
            )
            success += 1
            processed += 1

            # Progress output
            if processed % 10 == 0:
                elapsed = time.time() - start_time
                rate = success / elapsed if elapsed > 0 else 0
                print(f"  {processed}/{count} (Success: {success}, Errors: {errors}) ({rate:.1f}/sec)")

            # Cleanup - close connections every 1000 entries
            if processed % 1000 == 0:
                close_old_connections()

        except Exception as e:  # pylint: disable=broad-exception-caught
            errors += 1
            processed += 1
            # Print first few errors with traceback for debugging
            if errors <= 3:
                import traceback
                print(f"Error details for debugging:")
                print(f"  SHA256: {sha256_hash}")
                traceback.print_exc()
            else:
                print(f"Error: {e}")
                sys.exit()

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

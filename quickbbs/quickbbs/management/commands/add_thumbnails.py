"""
Function to add missing thumbnails for files in the database.

This module scans IndexData for files missing thumbnails and generates them.
Only processes files with non-generic filetypes (images, videos, PDFs).
"""

import time

from django.db import close_old_connections
from django.db.models import Q
from thumbnails.models import ThumbnailFiles

from quickbbs.models import IndexData


def add_thumbnails(max_count: int = 0) -> None:
    """
    Scan IndexData for files missing thumbnails and generate them.

    Only processes files with thumbnailable filetypes:
    - is_image=True (images: jpg, png, gif, etc.)
    - is_pdf=True (PDF documents)
    - is_movie=True (videos: mp4, avi, etc.)

    Skips files marked as generic icons or pending deletion.

    Args:
        max_count: Maximum number of thumbnails to generate (0 = unlimited)

    Returns:
        None
    """
    print("=" * 60)
    print("Adding missing thumbnails for files in database")
    print("=" * 60)

    # Query for files that need thumbnails:
    # - Not marked as generic icon
    # - Not marked for deletion
    # - File type supports thumbnails (is_image, is_pdf, or is_movie)
    # - Either no thumbnail reference OR thumbnail exists but has no data
    print("Finding files missing thumbnails...")

    files_needing_thumbnails = (
        IndexData.objects.select_related("new_ftnail", "filetype", "home_directory")
        .filter(
            Q(is_generic_icon=False)
            & Q(delete_pending=False)
            & (Q(filetype__is_image=True) | Q(filetype__is_pdf=True) | Q(filetype__is_movie=True))
            & (
                Q(new_ftnail__isnull=True)  # No thumbnail record at all
                | Q(new_ftnail__small_thumb__in=[b"", None])  # Has record but no thumbnail data
            )
        )
        .only(
            "file_sha256",
            "name",
            "new_ftnail",
            "filetype__is_image",
            "filetype__is_movie",
            "filetype__is_pdf",
            "home_directory__fqpndirectory",
        )
    )

    total_files = files_needing_thumbnails.count()
    print(f"Found {total_files} files missing thumbnails")

    if total_files == 0:
        print("No files need thumbnails - database is up to date")
        return

    # Apply max_count limit if specified
    if 0 < max_count < total_files:
        print(f"Limiting to first {max_count} files (use max_count=0 for unlimited)")
        files_needing_thumbnails = files_needing_thumbnails[:max_count]
        total_files = max_count

    # Process files and generate thumbnails
    print(f"\nGenerating thumbnails for {total_files} files...")
    processed_count = 0
    success_count = 0
    skip_count = 0
    error_count = 0
    start_time = time.time()

    for file_record in files_needing_thumbnails:
        try:
            # Skip if no file_sha256 (shouldn't happen but be defensive)
            if not file_record.file_sha256:
                print(f"Skipping {file_record.name} - no file SHA256")
                skip_count += 1
                continue

            # Generate thumbnail using existing get_or_create_thumbnail_record
            # This function handles all the logic for creating thumbnails
            # Note: Files are already filtered to only include is_image, is_pdf, or is_movie
            ThumbnailFiles.get_or_create_thumbnail_record(file_sha256=file_record.file_sha256, suppress_save=False)

            success_count += 1
            processed_count += 1

            # Progress indicator
            if processed_count % 50 == 0:
                elapsed_time = time.time() - start_time
                success_rate = success_count / elapsed_time if elapsed_time > 0 else 0
                print(
                    f"Processed {processed_count}/{total_files} files "
                    f"(Success: {success_count}, Skipped: {skip_count}, Errors: {error_count}) "
                    f"({success_rate:.1f} thumbnails/sec)"
                )

            # Periodic connection cleanup to prevent exhaustion
            if processed_count % 100 == 0:
                close_old_connections()

        except Exception as e:  # pylint: disable=broad-exception-caught
            error_count += 1
            processed_count += 1
            print(f"Error generating thumbnail for {file_record.name}: {e}")
            continue

    # Final connection cleanup
    close_old_connections()

    # Calculate final statistics
    total_time = time.time() - start_time
    success_rate = success_count / total_time if total_time > 0 else 0

    print("=" * 60)
    print("Thumbnail generation complete:")
    print(f"  Total processed: {processed_count}")
    print(f"  Successfully generated: {success_count}")
    print(f"  Skipped: {skip_count}")
    print(f"  Errors: {error_count}")
    print(f"  Total time: {total_time:.1f} seconds")
    print(f"  Generation rate: {success_rate:.1f} thumbnails/sec")
    print("=" * 60)

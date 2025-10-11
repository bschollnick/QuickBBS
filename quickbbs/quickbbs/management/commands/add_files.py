"""
Function to add missing files from filesystem to database.

This module iterates through directories in the database and adds any missing
files to IndexData. It uses the sync_database_disk function to properly scan
directories and add files.
"""

import asyncio
import os

from django.conf import settings
from django.db import close_old_connections
from frontend.utilities import sync_database_disk

from quickbbs.common import normalize_fqpn
from quickbbs.models import IndexDirs


def add_files(max_count: int = 0) -> None:
    """
    Iterate through directories in database and add any missing files.

    Uses sync_database_disk to properly scan directories and add files.
    Processes directories using iterator() to avoid loading all into memory.

    Args:
        max_count: Maximum number of directories to process (0 = unlimited)

    Returns:
        None
    """
    print("=" * 60)
    print("Adding missing files from filesystem to database")
    print("=" * 60)

    # Get the albums root directory
    albums_root = os.path.join(settings.ALBUMS_PATH, "albums")
    albums_root = normalize_fqpn(albums_root)

    if not os.path.exists(albums_root):
        print(f"ERROR: Albums root does not exist: {albums_root}")
        return

    print(f"Scanning albums root: {albums_root}")

    # Get total count for progress reporting
    total_dirs = IndexDirs.objects.count()
    print(f"Found {total_dirs} directories in database")

    if total_dirs == 0:
        print("No directories found in database. Run --add_directories first.")
        return

    # Determine how many to process
    dirs_to_process = max_count if max_count > 0 else total_dirs
    print(f"Processing {dirs_to_process} directories to add missing files...")

    # Iterate through directories using iterator() - no list building
    processed_count = 0

    # Use iterator to avoid loading all directories into memory
    # Process directories WITHOUT closing connections during iteration
    # Server-side cursors don't survive close_old_connections()
    for directory in IndexDirs.objects.all().iterator(chunk_size=100):
        try:
            # Use sync_database_disk to scan the directory and add missing files
            # This is an async function, so we need to run it
            asyncio.run(sync_database_disk(directory.fqpndirectory))

            processed_count += 1

            # Progress indicator
            if processed_count % 10 == 0:
                print(f"Processed {processed_count} directories...")

            # Check if we've hit the max_count limit
            if 0 < max_count <= processed_count:
                print(f"Reached max_count limit of {max_count}")
                break

        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Error processing directory {directory.fqpndirectory}: {e}")
            continue

    # Only close connections AFTER iteration is complete
    close_old_connections()

    print("=" * 60)
    print(f"Successfully processed {processed_count} directories")
    print("=" * 60)

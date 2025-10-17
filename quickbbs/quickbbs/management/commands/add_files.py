"""
Function to add missing files from filesystem to database.

This module iterates through directories in the database and adds any missing
files to IndexData. It uses the sync_database_disk function to properly scan
directories and add files.
"""

import asyncio
import os
import time

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections
from frontend.utilities import sync_database_disk

from quickbbs.common import normalize_fqpn
from quickbbs.models import IndexData, IndexDirs


async def _add_files_async(max_count: int = 0, start_path: str | None = None) -> None:
    """
    Async implementation of add_files.

    Iterates through directories in database and adds any missing files.
    Uses sync_database_disk to properly scan directories and add files.

    Args:
        max_count: Maximum number of directories to process (0 = unlimited)
        start_path: Starting directory path to walk from (default: ALBUMS_PATH/albums)

    Returns:
        None
    """
    print("=" * 60)
    print("Adding missing files from filesystem to database")
    print("=" * 60)

    # Get the albums root directory
    if start_path:
        albums_root = normalize_fqpn(start_path)
    else:
        albums_root = os.path.join(settings.ALBUMS_PATH, "albums")
        albums_root = normalize_fqpn(albums_root)

    if not os.path.exists(albums_root):
        print(f"ERROR: Albums root does not exist: {albums_root}")
        return

    print(f"Scanning albums root: {albums_root}")

    # Get total count for progress reporting
    total_dirs = await sync_to_async(IndexDirs.objects.count, thread_sensitive=True)()
    print(f"Found {total_dirs} directories in database")

    if total_dirs == 0:
        print("No directories found in database. Run --add_directories first.")
        return

    # Determine how many to process
    dirs_to_process = max_count if max_count > 0 else total_dirs
    print(f"Processing {dirs_to_process} directories to add missing files...")

    # Track file additions across all directories
    initial_file_count = await sync_to_async(IndexData.objects.count, thread_sensitive=True)()
    print(f"Initial file count in database: {initial_file_count}")

    # Iterate through directories
    processed_count = 0
    start_time = time.time()

    # Fetch all directories first with Cache_Watcher prefetched
    # This prevents sync DB queries when accessing is_cached property
    # Filter directories to only those under the albums_root if start_path was specified
    if start_path:
        directories = await sync_to_async(list, thread_sensitive=True)(
            IndexDirs.objects.select_related("Cache_Watcher").filter(fqpndirectory__startswith=albums_root).all()
        )
    else:
        directories = await sync_to_async(list, thread_sensitive=True)(IndexDirs.objects.select_related("Cache_Watcher").all())

    for directory in directories:
        try:
            # Use sync_database_disk to scan the directory and add missing files
            await sync_database_disk(directory)

            processed_count += 1

            # Progress indicator
            if processed_count % 10 == 0:
                current_file_count = await sync_to_async(IndexData.objects.count, thread_sensitive=True)()
                files_added = current_file_count - initial_file_count
                elapsed_time = time.time() - start_time
                file_rate = files_added / elapsed_time if elapsed_time > 0 else 0
                print(f"Processed {processed_count} directories, " f"added {files_added} files ({file_rate:.1f} files/sec)...")

            # Check if we've hit the max_count limit
            if 0 < max_count <= processed_count:
                print(f"Reached max_count limit of {max_count}")
                break

        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Error processing directory {directory.fqpndirectory}: {e}")
            continue

    # Only close connections AFTER iteration is complete
    close_old_connections()

    # Calculate final statistics
    final_file_count = await sync_to_async(IndexData.objects.count, thread_sensitive=True)()
    total_files_added = final_file_count - initial_file_count
    total_time = time.time() - start_time
    file_rate = total_files_added / total_time if total_time > 0 else 0

    print("=" * 60)
    print(f"Successfully processed {processed_count} directories")
    print(f"Total files added: {total_files_added}")
    print(f"Total time: {total_time:.1f} seconds")
    print(f"File addition rate: {file_rate:.1f} files/sec")
    print("=" * 60)


def add_files(max_count: int = 0, start_path: str | None = None) -> None:
    """
    Synchronous wrapper for add_files.

    Iterates through directories in database and adds any missing files.
    Uses sync_database_disk to properly scan directories and add files.

    Args:
        max_count: Maximum number of directories to process (0 = unlimited)
        start_path: Starting directory path to walk from (default: ALBUMS_PATH/albums)

    Returns:
        None
    """
    asyncio.run(_add_files_async(max_count=max_count, start_path=start_path))

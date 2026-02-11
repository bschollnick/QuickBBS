"""
Function to add missing files from filesystem to database.

This module iterates through directories in the database and adds any missing
files to FileIndex. It uses the update_database_from_disk function to properly scan
directories and add files.

Memory-optimized: Uses chunked processing to avoid loading all directories into
memory at once. Tracks file additions locally instead of expensive count() queries.
"""

from __future__ import annotations

import asyncio
import os
import time

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections

from frontend.utilities import update_database_from_disk
from quickbbs.common import normalize_fqpn
from quickbbs.management.commands.management_helper import (
    invalidate_directories_with_null_sha256,
    invalidate_directories_with_null_virtual_directory,
    invalidate_empty_directories,
)
from quickbbs.models import DirectoryIndex, FileIndex

# Batch size for chunked directory processing
BULK_UPDATE_BATCH_SIZE = 250


async def _process_directory_chunk(
    directory_pks: list[int],
    processed_count: int,
    files_added: int,
    max_count: int,
    start_time: float,
) -> tuple[int, int, bool]:
    """
    Process a chunk of directories by their primary keys.

    Args:
        directory_pks: List of DirectoryIndex primary keys to process
        processed_count: Current count of directories processed
        files_added: Current count of files added
        max_count: Maximum number of directories to process (0 = unlimited)
        start_time: Start time for rate calculations

    Returns:
        Tuple of (updated processed_count, updated files_added, reached_max_count flag)
    """
    # Fetch full directory objects for this chunk with related data
    directories = await sync_to_async(list, thread_sensitive=True)(
        DirectoryIndex.objects.select_related("Cache_Watcher", "parent_directory").filter(pk__in=directory_pks).order_by("fqpndirectory")
    )

    for directory in directories:
        try:
            # Count files in this directory before processing
            files_before = await sync_to_async(lambda d: d.FileIndex_entries.count(), thread_sensitive=True)(directory)

            # Use update_database_from_disk to scan the directory and add missing files
            await sync_to_async(update_database_from_disk)(directory)

            # Count files after processing to track additions locally
            files_after = await sync_to_async(lambda d: d.FileIndex_entries.count(), thread_sensitive=True)(directory)
            files_added += files_after - files_before

            processed_count += 1

            # Progress indicator every 100 directories (reduced from 10 to avoid spam)
            if processed_count % 100 == 0:
                elapsed_time = time.time() - start_time
                dir_rate = processed_count / elapsed_time if elapsed_time > 0 else 0
                file_rate = files_added / elapsed_time if elapsed_time > 0 else 0
                print(
                    f"Processed {processed_count} directories, " f"added {files_added} files ({dir_rate:.1f} dirs/sec, {file_rate:.1f} files/sec)..."
                )

            # Check if we've hit the max_count limit
            if 0 < max_count <= processed_count:
                print(f"Reached max_count limit of {max_count}")
                return processed_count, files_added, True

        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Error processing directory {directory.fqpndirectory}: {e}")
            continue

    return processed_count, files_added, False


async def _add_files_async(max_count: int = 0, start_path: str | None = None) -> None:
    """
    Async implementation of add_files.

    Iterates through directories in database and adds any missing files.
    Uses update_database_from_disk to properly scan directories and add files.

    Memory-optimized: Fetches directory PKs in chunks instead of loading all
    directory objects into memory at once. Tracks file additions locally.

    Args:
        max_count: Maximum number of directories to process (0 = unlimited)
        start_path: Starting directory path to walk from (default: ALBUMS_PATH/albums)

    Returns:
        None
    """
    print("=" * 60)
    print("Adding missing files from filesystem to database")
    print("=" * 60)

    # Invalidate directories containing files with NULL SHA256
    await sync_to_async(invalidate_directories_with_null_sha256, thread_sensitive=True)(start_path=start_path, verbose=True)

    # Invalidate directories with link files missing virtual_directory
    await sync_to_async(invalidate_directories_with_null_virtual_directory, thread_sensitive=True)(start_path=start_path, verbose=True)

    # Invalidate empty directories before adding files
    print("-" * 30)
    print("Invalidating empty directories (before adding files)...")
    await sync_to_async(invalidate_empty_directories, thread_sensitive=True)(start_path=start_path, verbose=True)
    print("-" * 30)

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

    # Build the base queryset for directories
    if start_path:
        base_qs = DirectoryIndex.objects.filter(fqpndirectory__startswith=albums_root).order_by("fqpndirectory")
    else:
        base_qs = DirectoryIndex.objects.order_by("fqpndirectory")

    # Get total count and directory PKs (lightweight - just integers)
    total_dirs = await sync_to_async(base_qs.count, thread_sensitive=True)()
    print(f"Found {total_dirs} directories in database")

    if total_dirs == 0:
        print("No directories found in database. Run --add_directories first.")
        return

    # Determine how many to process
    dirs_to_process = max_count if max_count > 0 else total_dirs
    print(f"Processing up to {dirs_to_process} directories to add missing files (chunked mode)...")

    # Get initial file count for final statistics
    initial_file_count = await sync_to_async(FileIndex.objects.count, thread_sensitive=True)()
    print(f"Initial file count in database: {initial_file_count}")

    # Fetch only primary keys (lightweight - avoids loading full objects into memory)
    all_pks = await sync_to_async(list, thread_sensitive=True)(base_qs.values_list("pk", flat=True))

    # Process in chunks
    processed_count = 0
    files_added = 0
    start_time = time.time()
    reached_max = False

    for i in range(0, len(all_pks), BULK_UPDATE_BATCH_SIZE):
        if reached_max:
            break

        chunk_pks = all_pks[i : i + BULK_UPDATE_BATCH_SIZE]

        processed_count, files_added, reached_max = await _process_directory_chunk(chunk_pks, processed_count, files_added, max_count, start_time)

        # Close old connections after each chunk to prevent exhaustion
        await sync_to_async(close_old_connections, thread_sensitive=True)()

    # Calculate final statistics
    final_file_count = await sync_to_async(FileIndex.objects.count, thread_sensitive=True)()
    total_files_added = final_file_count - initial_file_count
    total_time = time.time() - start_time
    dir_rate = processed_count / total_time if total_time > 0 else 0
    file_rate = total_files_added / total_time if total_time > 0 else 0

    # Invalidate empty directories after all file additions
    print("-" * 30)
    print("Invalidating empty directories (after adding files)...")
    await sync_to_async(invalidate_empty_directories, thread_sensitive=True)(start_path=start_path, verbose=True)
    print("-" * 30)

    print("=" * 60)
    print(f"Successfully processed {processed_count} directories")
    print(f"Total files added: {total_files_added} (tracked: {files_added})")
    print(f"Total time: {total_time:.1f} seconds")
    print(f"Directory rate: {dir_rate:.1f} dirs/sec")
    print(f"File addition rate: {file_rate:.1f} files/sec")
    print("=" * 60)


def add_files(max_count: int = 0, start_path: str | None = None) -> None:
    """
    Synchronous wrapper for add_files.

    Iterates through directories in database and adds any missing files.
    Uses update_database_from_disk to properly scan directories and add files.

    Args:
        max_count: Maximum number of directories to process (0 = unlimited)
        start_path: Starting directory path to walk from (default: ALBUMS_PATH/albums)

    Returns:
        None
    """
    asyncio.run(_add_files_async(max_count=max_count, start_path=start_path))

"""
Function to add missing files from filesystem to database.

This module iterates through directories in the database and adds any missing
files to FileIndex. It uses the update_database_from_disk function to properly
scan directories and add files.

Memory-optimized: Uses chunked processing to avoid loading all directories into
memory at once. Tracks file additions locally instead of expensive count() queries.
"""

from __future__ import annotations

import logging
import os
import time

from django.conf import settings
from django.db import close_old_connections

from quickbbs.common import normalize_fqpn
from quickbbs.directoryindex import update_database_from_disk
from quickbbs.management.commands.management_helper import (
    invalidate_directories_with_null_sha256,
    invalidate_directories_with_null_virtual_directory,
    invalidate_empty_directories,
)
from quickbbs.models import DirectoryIndex

logger = logging.getLogger(__name__)

# Batch size for chunked directory processing
BULK_UPDATE_BATCH_SIZE = 250


def _process_directory_chunk(
    directory_pks: list[int],
    processed_count: int,
    max_count: int,
    start_time: float,
) -> tuple[int, bool]:
    """
    Process a chunk of directories by their primary keys.

    Args:
        directory_pks: List of DirectoryIndex primary keys to process
        processed_count: Current count of directories processed
        max_count: Maximum number of directories to process (0 = unlimited)
        start_time: Start time for rate calculations

    Returns:
        Tuple of (updated processed_count, reached_max_count flag)
    """
    directories = list(
        DirectoryIndex.objects.select_related("Cache_Watcher", "parent_directory")
        .filter(pk__in=directory_pks)
        .order_by("fqpndirectory")
    )

    for directory in directories:
        try:
            update_database_from_disk(directory)

            processed_count += 1

            if processed_count % 100 == 0:
                elapsed_time = time.time() - start_time
                dir_rate = processed_count / elapsed_time if elapsed_time > 0 else 0
                print(f"Processed {processed_count} directories ({dir_rate:.1f} dirs/sec)...")

            if 0 < max_count <= processed_count:
                print(f"Reached max_count limit of {max_count}")
                return processed_count, True

        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Error processing directory %s", directory.fqpndirectory)
            continue

    return processed_count, False


def add_files(max_count: int = 0, start_path: str | None = None) -> None:
    """
    Iterate through directories in database and add any missing files.

    Uses update_database_from_disk to properly scan directories and add files.
    Performs pre- and post-scan invalidation of empty directories and directories
    containing files with NULL SHA256 or virtual_directory links.

    Memory-optimized: Fetches directory PKs in chunks instead of loading all
    directory objects into memory at once.

    Args:
        max_count: Maximum number of directories to process (0 = unlimited)
        start_path: Starting directory path to walk from (default: ALBUMS_PATH/albums)

    Returns:
        None
    """
    print("=" * 60)
    print("Adding missing files from filesystem to database")
    print("=" * 60)

    invalidate_directories_with_null_sha256(start_path=start_path, verbose=True)
    invalidate_directories_with_null_virtual_directory(start_path=start_path, verbose=True)

    print("-" * 30)
    print("Invalidating empty directories (before adding files)...")
    invalidate_empty_directories(start_path=start_path, verbose=True)
    print("-" * 30)

    if start_path:
        albums_root = normalize_fqpn(start_path)
    else:
        albums_root = normalize_fqpn(os.path.join(settings.ALBUMS_PATH, "albums"))

    if not os.path.exists(albums_root):
        print(f"ERROR: Albums root does not exist: {albums_root}")
        return

    print(f"Scanning albums root: {albums_root}")

    if start_path:
        base_qs = DirectoryIndex.objects.filter(fqpndirectory__startswith=albums_root).order_by("fqpndirectory")
    else:
        base_qs = DirectoryIndex.objects.order_by("fqpndirectory")

    # Materialise PKs once — len() gives the total count for free
    all_pks = list(base_qs.values_list("pk", flat=True))
    total_dirs = len(all_pks)
    print(f"Found {total_dirs} directories in database")

    if total_dirs == 0:
        print("No directories found in database. Run --add_directories first.")
        return

    print(f"Processing up to {max_count if max_count > 0 else total_dirs} directories (chunked mode)...")

    processed_count = 0
    start_time = time.time()
    reached_max = False

    for i in range(0, len(all_pks), BULK_UPDATE_BATCH_SIZE):
        if reached_max:
            break

        chunk_pks = all_pks[i : i + BULK_UPDATE_BATCH_SIZE]
        processed_count, reached_max = _process_directory_chunk(chunk_pks, processed_count, max_count, start_time)

        close_old_connections()

    total_time = time.time() - start_time
    dir_rate = processed_count / total_time if total_time > 0 else 0

    print("-" * 30)
    print("Invalidating empty directories (after adding files)...")
    invalidate_empty_directories(start_path=start_path, verbose=True)
    print("-" * 30)

    print("=" * 60)
    print(f"Successfully processed {processed_count} directories")
    print(f"Total time: {total_time:.1f} seconds")
    print(f"Directory rate: {dir_rate:.1f} dirs/sec")
    print("=" * 60)

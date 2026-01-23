"""
Function to add missing directories from filesystem to database.

This module walks the albums directory and adds any missing directories to both
DirectoryIndex and fs_Cache_Tracking tables. Directories added to fs_Cache_Tracking
are marked as invalidated to ensure they are scanned when accessed via the web.
"""

from __future__ import annotations

import os
import time

from django.conf import settings
from django.db import close_old_connections

from cache_watcher.models import fs_Cache_Tracking
from quickbbs.common import normalize_fqpn
from quickbbs.models import DirectoryIndex

# Batch size for bulk_update operations
BULK_UPDATE_BATCH_SIZE = 250


def _flush_cache_invalidations(entries_to_invalidate: list[fs_Cache_Tracking]) -> None:
    """
    Flush pending cache invalidations using bulk_update.

    Args:
        entries_to_invalidate: List of fs_Cache_Tracking entries to mark as invalidated
    """
    if not entries_to_invalidate:
        return

    # Set invalidated=True on all entries
    for entry in entries_to_invalidate:
        entry.invalidated = True

    # Use bulk_update to update all entries in a single query
    fs_Cache_Tracking.objects.bulk_update(
        entries_to_invalidate,
        fields=["invalidated"],
        batch_size=BULK_UPDATE_BATCH_SIZE,
    )


def _process_missing_directories(
    missing_paths: list[str],
    cache_instance: fs_Cache_Tracking,
    added_count: int,
    max_count: int,
    start_time: float,
) -> tuple[int, bool]:
    """
    Process a list of missing directory paths, adding them to the database.

    Uses bulk_update to efficiently mark cache entries as invalidated instead of
    individual saves.

    Args:
        missing_paths: List of normalized directory paths to add
        cache_instance: fs_Cache_Tracking instance for adding cache entries
        added_count: Current count of directories added
        max_count: Maximum number of directories to add (0 = unlimited)
        start_time: Start time for rate calculations

    Returns:
        Tuple of (updated added_count, reached_max_count flag)
    """
    entries_to_invalidate: list[fs_Cache_Tracking] = []

    for normalized_root in missing_paths:
        try:
            # Add directory to DirectoryIndex
            _, dir_record = DirectoryIndex.add_directory(normalized_root)

            if dir_record:
                # Add to fs_Cache_Tracking (created with invalidated=False)
                cache_entry = cache_instance.add_from_indexdirs(dir_record)

                if cache_entry:
                    # Collect for bulk invalidation
                    entries_to_invalidate.append(cache_entry)

                added_count += 1

                # Flush invalidations when batch is full
                if len(entries_to_invalidate) >= BULK_UPDATE_BATCH_SIZE:
                    _flush_cache_invalidations(entries_to_invalidate)
                    entries_to_invalidate = []

                # Progress indicator
                if added_count % 100 == 0:
                    elapsed_time = time.time() - start_time
                    add_rate = added_count / elapsed_time if elapsed_time > 0 else 0
                    print(f"Added {added_count} directories ({add_rate:.1f} added/sec)...")
                    # Close old connections periodically to prevent exhaustion
                    close_old_connections()

                # Check if we've hit the max_count limit
                if 0 < max_count <= added_count:
                    print(f"Reached max_count limit of {max_count}")
                    # Flush remaining invalidations before returning
                    _flush_cache_invalidations(entries_to_invalidate)
                    return added_count, True

        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Error adding directory {normalized_root}: {e}")
            continue

    # Flush any remaining invalidations
    _flush_cache_invalidations(entries_to_invalidate)
    return added_count, False


def add_directories(max_count: int = 0, start_path: str | None = None) -> None:
    """
    Walk the albums directory and add any missing directories to the database.

    Adds directories to both DirectoryIndex and fs_Cache_Tracking tables.
    Directories are marked as invalidated in fs_Cache_Tracking to ensure
    they will be scanned when accessed via the web interface.

    Uses batch existence checks for performance: collects paths in batches and
    queries the database with __in lookups instead of individual exists() calls.
    This reduces database round-trips from N to N/batch_size.

    Args:
        max_count: Maximum number of directories to add (0 = unlimited)
        start_path: Starting directory path to walk from (default: ALBUMS_PATH/albums)

    Returns:
        None
    """
    print("=" * 60)
    print("Adding missing directories from filesystem to database")
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
    print("Walking filesystem and checking database (batch mode)...")

    # Batch processing configuration
    batch_size = 500  # Check 500 directories per database query
    batch_paths: list[str] = []

    added_count = 0
    scanned_count = 0
    cache_instance = fs_Cache_Tracking()
    start_time = time.time()
    reached_max = False

    for root, _, _ in os.walk(albums_root):
        if reached_max:
            break

        # Normalize and collect paths
        normalized_root = normalize_fqpn(root)
        batch_paths.append(normalized_root)
        scanned_count += 1

        # Progress indicator every 1000 directories scanned
        if scanned_count % 1000 == 0:
            elapsed_time = time.time() - start_time
            scan_rate = scanned_count / elapsed_time if elapsed_time > 0 else 0
            print(f"Scanned {scanned_count} directories, added {added_count} ({scan_rate:.1f} dirs/sec)...")

        # Process batch when full
        if len(batch_paths) >= batch_size:
            # Single query to find all existing directories in this batch
            existing_paths = set(DirectoryIndex.objects.filter(fqpndirectory__in=batch_paths).values_list("fqpndirectory", flat=True))

            # Find missing directories (not in database)
            missing_paths = [p for p in batch_paths if p not in existing_paths]

            # Process missing directories
            if missing_paths:
                added_count, reached_max = _process_missing_directories(missing_paths, cache_instance, added_count, max_count, start_time)

            # Clear batch for next iteration
            batch_paths = []

    # Process remaining paths in final partial batch
    if batch_paths and not reached_max:
        existing_paths = set(DirectoryIndex.objects.filter(fqpndirectory__in=batch_paths).values_list("fqpndirectory", flat=True))
        missing_paths = [p for p in batch_paths if p not in existing_paths]

        if missing_paths:
            added_count, _ = _process_missing_directories(missing_paths, cache_instance, added_count, max_count, start_time)

    # Final connection cleanup
    close_old_connections()

    # Calculate final statistics
    total_time = time.time() - start_time
    scan_rate = scanned_count / total_time if total_time > 0 else 0
    add_rate = added_count / total_time if total_time > 0 else 0

    print("=" * 60)
    print(f"Scanned {scanned_count} filesystem directories")
    print(f"Successfully added {added_count} directories to database")
    print(f"Total time: {total_time:.1f} seconds")
    print(f"Scan rate: {scan_rate:.1f} directories/sec")
    print(f"Add rate: {add_rate:.1f} directories/sec")
    print("=" * 60)

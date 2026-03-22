"""
Function to add missing directories from filesystem to database.

This module walks the albums directory and adds any missing directories to both
DirectoryIndex and fs_Cache_Tracking tables. Directories added to fs_Cache_Tracking
are marked as invalidated to ensure they are scanned when accessed via the web.
"""

from __future__ import annotations

import logging
import os
import time

from django.conf import settings
from django.db import close_old_connections

from cache_watcher.models import fs_Cache_Tracking
from quickbbs.common import normalize_fqpn
from quickbbs.models import DirectoryIndex

logger = logging.getLogger(__name__)

# Batch size for bulk DB write operations (matches settings.BATCH_SIZES["db_write"])
BULK_UPDATE_BATCH_SIZE = 250

# Batch size for filesystem-scan existence checks (matches settings.BATCH_SIZES["db_read"])
FS_SCAN_BATCH_SIZE = 500


def _flush_cache_invalidations(cache_pks: list[int]) -> None:
    """
    Mark a batch of fs_Cache_Tracking rows as invalidated with a single UPDATE.

    Args:
        cache_pks: Primary keys of fs_Cache_Tracking rows to mark as invalidated
    """
    if not cache_pks:
        return
    fs_Cache_Tracking.objects.filter(pk__in=cache_pks).update(invalidated=True)


def _process_missing_directories(
    missing_paths: list[str],
    cache_instance: fs_Cache_Tracking,
    added_count: int,
    max_count: int,
    start_time: float,
) -> tuple[int, bool]:
    """
    Process a list of missing directory paths, adding them to the database.

    Adds each path to DirectoryIndex via add_directory(), then creates an
    fs_Cache_Tracking entry via add_from_indexdirs(). Cache entries are
    collected and marked invalidated in a single UPDATE per batch.

    Only increments added_count when both the DirectoryIndex record and its
    cache entry are successfully created.

    Args:
        missing_paths: List of normalized directory paths to add
        cache_instance: fs_Cache_Tracking instance used to call add_from_indexdirs()
        added_count: Current count of successfully added directories
        max_count: Maximum number of directories to add (0 = unlimited)
        start_time: Start time for rate calculations

    Returns:
        Tuple of (updated added_count, reached_max_count flag)
    """
    pending_cache_pks: list[int] = []

    for normalized_root in missing_paths:
        try:
            _, dir_record = DirectoryIndex.add_directory(normalized_root)

            if dir_record:
                cache_entry = cache_instance.add_from_indexdirs(dir_record)

                if cache_entry:
                    pending_cache_pks.append(cache_entry.pk)
                    added_count += 1
                else:
                    # Cache entry creation failed — log but still count the dir record
                    logger.warning("add_from_indexdirs returned None for %s", normalized_root)

                # Flush invalidations when batch is full
                if len(pending_cache_pks) >= BULK_UPDATE_BATCH_SIZE:
                    _flush_cache_invalidations(pending_cache_pks)
                    pending_cache_pks = []

                # Progress indicator
                if added_count % 100 == 0:
                    elapsed_time = time.time() - start_time
                    add_rate = added_count / elapsed_time if elapsed_time > 0 else 0
                    print(f"Added {added_count} directories ({add_rate:.1f} added/sec)...")
                    close_old_connections()

                # Check if we've hit the max_count limit
                if 0 < max_count <= added_count:
                    print(f"Reached max_count limit of {max_count}")
                    _flush_cache_invalidations(pending_cache_pks)
                    return added_count, True

        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Error adding directory %s", normalized_root)
            continue

    _flush_cache_invalidations(pending_cache_pks)
    return added_count, False


def add_directories(max_count: int = 0, start_path: str | None = None) -> None:
    """
    Walk the albums directory and add any missing directories to the database.

    Adds directories to both DirectoryIndex and fs_Cache_Tracking tables.
    Directories are marked as invalidated in fs_Cache_Tracking to ensure
    they will be scanned when accessed via the web interface.

    Uses batch existence checks for performance: collects paths in batches and
    queries the database with __in lookups instead of individual exists() calls.
    This reduces database round-trips from N to N/FS_SCAN_BATCH_SIZE.

    Args:
        max_count: Maximum number of directories to add (0 = unlimited)
        start_path: Starting directory path to walk from (default: ALBUMS_PATH/albums)

    Returns:
        None
    """
    print("=" * 60)
    print("Adding missing directories from filesystem to database")
    print("=" * 60)

    if start_path:
        albums_root = normalize_fqpn(start_path)
    else:
        albums_root = normalize_fqpn(os.path.join(settings.ALBUMS_PATH, "albums"))

    if not os.path.exists(albums_root):
        print(f"ERROR: Albums root does not exist: {albums_root}")
        return

    print(f"Scanning albums root: {albums_root}")
    print("Walking filesystem and checking database (batch mode)...")

    batch_paths: list[str] = []
    added_count = 0
    scanned_count = 0
    # fs_Cache_Tracking() is intentionally unsaved — add_from_indexdirs() uses only the
    # passed dir_record, not self state, so no DB identity is needed on the caller.
    cache_instance = fs_Cache_Tracking()
    start_time = time.time()
    reached_max = False

    for root, _, _ in os.walk(albums_root):
        if reached_max:
            break

        normalized_root = normalize_fqpn(root)
        batch_paths.append(normalized_root)
        scanned_count += 1

        if scanned_count % 1000 == 0:
            elapsed_time = time.time() - start_time
            scan_rate = scanned_count / elapsed_time if elapsed_time > 0 else 0
            print(f"Scanned {scanned_count} directories, added {added_count} ({scan_rate:.1f} dirs/sec)...")

        if len(batch_paths) >= FS_SCAN_BATCH_SIZE:
            existing_paths = set(DirectoryIndex.objects.filter(fqpndirectory__in=batch_paths).values_list("fqpndirectory", flat=True))
            missing_paths = [p for p in batch_paths if p not in existing_paths]

            if missing_paths:
                added_count, reached_max = _process_missing_directories(missing_paths, cache_instance, added_count, max_count, start_time)

            batch_paths = []

    # Process remaining paths in final partial batch
    if batch_paths and not reached_max:
        existing_paths = set(DirectoryIndex.objects.filter(fqpndirectory__in=batch_paths).values_list("fqpndirectory", flat=True))
        missing_paths = [p for p in batch_paths if p not in existing_paths]

        if missing_paths:
            added_count, _ = _process_missing_directories(missing_paths, cache_instance, added_count, max_count, start_time)

    close_old_connections()

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

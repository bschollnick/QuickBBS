"""
Function to add missing directories from filesystem to database.

This module walks the albums directory and adds any missing directories to
DirectoryIndex. Added directories are marked cache_invalidated to ensure they
are scanned when accessed via the web.
"""

from __future__ import annotations

import logging
import os
import time

from django.conf import settings
from django.db import close_old_connections

from quickbbs.common import normalize_fqpn
from quickbbs.models import DirectoryIndex

logger = logging.getLogger(__name__)

# Batch size for bulk DB write operations (matches settings.BATCH_SIZES["db_write"])
BULK_UPDATE_BATCH_SIZE = 250

# Batch size for filesystem-scan existence checks (matches settings.BATCH_SIZES["db_read"])
FS_SCAN_BATCH_SIZE = 500


def _flush_cache_invalidations(dir_pks: list[int]) -> None:
    """
    Mark a batch of DirectoryIndex rows as cache-invalidated with a single UPDATE.

    Args:
        dir_pks: Primary keys of DirectoryIndex rows to mark as invalidated
    """
    if not dir_pks:
        return
    DirectoryIndex.objects.filter(pk__in=dir_pks).update(cache_invalidated=True)


def _process_missing_directories(
    missing_paths: list[str],
    added_count: int,
    max_count: int,
    start_time: float,
) -> tuple[int, bool]:
    """
    Process a list of missing directory paths, adding them to the database.

    Adds each path to DirectoryIndex via add_directory(), records the scan via
    mark_scanned(), then marks the batch invalidated in a single UPDATE so the
    directories are rescanned when accessed via the web.

    Args:
        missing_paths: List of normalized directory paths to add
        added_count: Current count of successfully added directories
        max_count: Maximum number of directories to add (0 = unlimited)
        start_time: Start time for rate calculations

    Returns:
        Tuple of (updated added_count, reached_max_count flag)
    """
    pending_dir_pks: list[int] = []

    for normalized_root in missing_paths:
        try:
            _, dir_record = DirectoryIndex.add_directory(normalized_root)

            if dir_record:
                dir_record.mark_scanned()
                pending_dir_pks.append(dir_record.pk)
                added_count += 1

                # Flush invalidations when batch is full
                if len(pending_dir_pks) >= BULK_UPDATE_BATCH_SIZE:
                    _flush_cache_invalidations(pending_dir_pks)
                    pending_dir_pks = []

                # Progress indicator
                if added_count % 100 == 0:
                    elapsed_time = time.time() - start_time
                    add_rate = added_count / elapsed_time if elapsed_time > 0 else 0
                    print(f"Added {added_count} directories ({add_rate:.1f} added/sec)...")
                    close_old_connections()

                # Check if we've hit the max_count limit
                if 0 < max_count <= added_count:
                    print(f"Reached max_count limit of {max_count}")
                    _flush_cache_invalidations(pending_dir_pks)
                    return added_count, True

        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Error adding directory %s", normalized_root)
            continue

    _flush_cache_invalidations(pending_dir_pks)
    return added_count, False


def add_directories(max_count: int = 0, start_path: str | None = None) -> None:
    """
    Walk the albums directory and add any missing directories to the database.

    Adds directories to DirectoryIndex, marked cache_invalidated to ensure
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
                added_count, reached_max = _process_missing_directories(missing_paths, added_count, max_count, start_time)

            batch_paths = []

    # Process remaining paths in final partial batch
    if batch_paths and not reached_max:
        existing_paths = set(DirectoryIndex.objects.filter(fqpndirectory__in=batch_paths).values_list("fqpndirectory", flat=True))
        missing_paths = [p for p in batch_paths if p not in existing_paths]

        if missing_paths:
            added_count, _ = _process_missing_directories(missing_paths, added_count, max_count, start_time)

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

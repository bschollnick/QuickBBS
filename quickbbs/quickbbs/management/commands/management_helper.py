"""
Helper functions for Django management commands.

Provides common utilities used across multiple management commands for
directory validation, cache invalidation, and database maintenance.
"""

from __future__ import annotations

import time

from django.db.models import Count

from quickbbs.common import normalize_fqpn
from quickbbs.models import IndexDirs


def invalidate_empty_directories(start_path: str | None = None, verbose: bool = True) -> int:
    """
    Invalidate directories with 0 files in fs_Cache_Tracking.

    Uses Count annotation on IndexData_entries (reverse FK from IndexData.home_directory)
    to efficiently identify empty directories without requiring separate IndexData queries.

    Args:
        start_path: Optional starting directory path to filter directories
        verbose: Whether to print progress messages (default: True)

    Returns:
        Number of directories invalidated
    """
    # Query directories with 0 IndexData_entries using Count annotation
    # IndexData_entries is the reverse relationship from IndexData.home_directory
    empty_directories_query = IndexDirs.objects.annotate(file_count=Count("IndexData_entries")).filter(file_count=0).select_related("Cache_Watcher")

    # Filter to start_path if specified
    if start_path:
        normalized_start = normalize_fqpn(start_path)
        empty_directories_query = empty_directories_query.filter(fqpndirectory__startswith=normalized_start)

    empty_directories = list(empty_directories_query)
    empty_count = len(empty_directories)

    if empty_count == 0:
        if verbose:
            print("No empty directories found to invalidate")
        return 0

    if verbose:
        print(f"Found {empty_count} empty directories to invalidate")

    invalidated_count = 0
    # Invalidate each empty directory in fs_Cache_Tracking
    for directory in empty_directories:
        # Check if directory has a Cache_Watcher entry (1-to-1 relationship)
        if hasattr(directory, "Cache_Watcher"):
            # Update existing cache entry to invalidated
            directory.Cache_Watcher.invalidated = True
            directory.Cache_Watcher.lastscan = time.time()
            directory.Cache_Watcher.save()
            invalidated_count += 1

    if verbose:
        print(f"Invalidated {invalidated_count} empty directories in cache")

    return invalidated_count

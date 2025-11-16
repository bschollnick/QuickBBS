"""
Helper functions for Django management commands.

Provides common utilities used across multiple management commands for
directory validation, cache invalidation, and database maintenance.
"""

from __future__ import annotations

import time

from django.db.models import Count

from cache_watcher.models import Cache_Storage
from quickbbs.common import normalize_fqpn
from quickbbs.models import FileIndex, DirectoryIndex


def invalidate_empty_directories(start_path: str | None = None, verbose: bool = True) -> int:
    """
    Invalidate directories with 0 files in fs_Cache_Tracking.

    Uses Count annotation on FileIndex_entries (reverse FK from FileIndex.home_directory)
    to efficiently identify empty directories without requiring separate FileIndex queries.

    Args:
        start_path: Optional starting directory path to filter directories
        verbose: Whether to print progress messages (default: True)

    Returns:
        Number of directories invalidated
    """
    # Query directories with 0 FileIndex_entries using Count annotation
    # FileIndex_entries is the reverse relationship from FileIndex.home_directory
    empty_directories_query = (
        DirectoryIndex.objects.annotate(file_count=Count("FileIndex_entries")).filter(file_count=0).select_related("Cache_Watcher")
    )

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


def invalidate_directories_with_null_sha256(start_path: str | None = None, verbose: bool = True) -> int:
    """
    Find files with NULL SHA256 and invalidate their parent directories.

    This ensures that directories containing files without SHA256 hashes
    will be rescanned and have their files' hashes calculated.

    Args:
        start_path: Optional starting directory path to filter files
        verbose: Whether to print progress messages (default: True)

    Returns:
        Number of directories invalidated
    """
    if verbose:
        print("-" * 60)
        print("Checking for files with NULL SHA256...")

    # Normalize start_path if provided
    normalized_start = normalize_fqpn(start_path) if start_path else None

    # Query for files with NULL SHA256 using FileIndex classmethod
    files_without_sha = FileIndex.find_files_without_sha(start_path=normalized_start)

    # Count before getting directories
    file_count = files_without_sha.count()
    if verbose:
        print(f"Found {file_count} files with NULL SHA256")

    if file_count == 0:
        if verbose:
            print("No directories need invalidation.")
            print("-" * 60)
        return 0

    # Get distinct list of directories containing files without SHA256
    # Use values_list to get just the directory IDs efficiently
    directory_ids = files_without_sha.values_list("home_directory_id", flat=True).distinct()

    # Use .count() to avoid materializing queryset twice
    directory_count = directory_ids.count()
    if verbose:
        print(f"Found {directory_count} directories containing files without SHA256")

    # Invalidate each directory in fs_Cache_Tracking
    directories_to_invalidate = DirectoryIndex.objects.filter(id__in=directory_ids)

    invalidated_count = 0
    for directory in directories_to_invalidate:
        Cache_Storage.remove_from_cache_indexdirs(directory)
        invalidated_count += 1
        if verbose:
            print(f"  Invalidated: {directory.fqpndirectory}")

    if verbose:
        print(f"Invalidated {invalidated_count} directories in fs_Cache_Tracking")
        print("-" * 60)

    return invalidated_count


def invalidate_directories_with_null_virtual_directory(start_path: str | None = None, verbose: bool = True) -> int:
    """
    Find link files with NULL virtual_directory and invalidate their parent directories.

    This ensures that directories containing link files (.link, .alias) without
    virtual_directory set will be rescanned and have the virtual_directory populated.

    Args:
        start_path: Optional starting directory path to filter files
        verbose: Whether to print progress messages (default: True)

    Returns:
        Number of directories invalidated
    """
    if verbose:
        print("-" * 60)
        print("Checking for link files with NULL virtual_directory...")

    # Normalize start_path if provided
    normalized_start = normalize_fqpn(start_path) if start_path else None

    # Query for link files with NULL virtual_directory using FileIndex classmethod
    link_files_without_vdir = FileIndex.find_broken_link_files(start_path=normalized_start)

    # Count before getting directories
    file_count = link_files_without_vdir.count()
    if verbose:
        print(f"Found {file_count} link files with NULL virtual_directory")

    if file_count == 0:
        if verbose:
            print("No directories need invalidation.")
            print("-" * 60)
        return 0

    # Get distinct list of directories containing link files without virtual_directory
    # Use values_list to get just the directory IDs efficiently
    directory_ids = link_files_without_vdir.values_list("home_directory_id", flat=True).distinct()

    # Use .count() to avoid materializing queryset twice
    directory_count = directory_ids.count()
    if verbose:
        print(f"Found {directory_count} directories containing link files without virtual_directory")

    # Invalidate each directory in fs_Cache_Tracking
    directories_to_invalidate = DirectoryIndex.objects.filter(id__in=directory_ids)

    invalidated_count = 0
    for directory in directories_to_invalidate:
        Cache_Storage.remove_from_cache_indexdirs(directory)
        invalidated_count += 1
        if verbose:
            print(f"  Invalidated: {directory.fqpndirectory}")

    if verbose:
        print(f"Invalidated {invalidated_count} directories in fs_Cache_Tracking")
        print("-" * 60)

    return invalidated_count

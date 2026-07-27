"""
Helper functions for Django management commands.

Provides common utilities used across multiple management commands for
directory validation, cache invalidation, and database maintenance.
"""

from __future__ import annotations

import os
import time

from django.conf import settings
from django.db.models import Count

from quickbbs.common import normalize_fqpn
from quickbbs.models import DirectoryIndex, FileIndex


def resolve_albums_root(start_path: str | None) -> str | None:
    """
    Resolve, validate, and confirm on-disk existence of a scan operation's root.

    If start_path is supplied, it becomes the operation's scope and must lie
    within the real albums root — used by add_directories()/add_files() so
    each is independently safe against an out-of-tree --start rather than
    relying solely on scan.py's Command.handle() having validated it first.

    Args:
        start_path: Optional starting directory path (raw, unnormalized);
            defaults to ALBUMS_PATH/albums when None.

    Returns:
        The normalized, existing albums root to scan from, or None if
        start_path lies outside the real albums root, or the resolved root
        does not exist on disk (caller should abort; an error message is
        already printed in either case).
    """
    if start_path:
        albums_root = normalize_fqpn(start_path)
        if not DirectoryIndex.is_in_albums_tree(albums_root):
            print(f"ERROR: --start path is outside the albums root: {albums_root}")
            return None
    else:
        albums_root = normalize_fqpn(os.path.join(settings.ALBUMS_PATH, "albums"))

    if not os.path.exists(albums_root):
        print(f"ERROR: Albums root does not exist: {albums_root}")
        return None

    print(f"Scanning albums root: {albums_root}")
    return albums_root


def invalidate_empty_directories(start_path: str | None = None, verbose: bool = True) -> int:
    """
    Mark directories with 0 files as cache-invalidated.

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
    empty_directories_query = DirectoryIndex.objects.annotate(file_count=Count("FileIndex_entries")).filter(file_count=0)

    # Filter to start_path if specified
    if start_path:
        normalized_start = normalize_fqpn(start_path)
        if not DirectoryIndex.is_in_albums_tree(normalized_start):
            if verbose:
                print(f"WARNING: --start path is outside the albums root, skipping: {normalized_start}")
            return 0
        empty_directories_query = empty_directories_query.filter(fqpndirectory__startswith=normalized_start)

    empty_pks = list(empty_directories_query.values_list("pk", flat=True))
    empty_count = len(empty_pks)

    if empty_count == 0:
        if verbose:
            print("No empty directories found to invalidate")
        return 0

    if verbose:
        print(f"Found {empty_count} empty directories to invalidate")

    now = time.time()
    invalidated_count = DirectoryIndex.objects.filter(pk__in=empty_pks).update(cache_invalidated=True, cache_lastscan=now)

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
    if normalized_start is not None and not DirectoryIndex.is_in_albums_tree(normalized_start):
        if verbose:
            print(f"WARNING: --start path is outside the albums root, skipping: {normalized_start}")
            print("-" * 60)
        return 0

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

    directories_to_invalidate = list(DirectoryIndex.objects.filter(id__in=directory_ids))
    invalidated_count = len(directories_to_invalidate)
    if verbose:
        print(f"Found {invalidated_count} directories containing files without SHA256")

    if directories_to_invalidate:
        DirectoryIndex.invalidate_caches(directories_to_invalidate)

    if verbose:
        print(f"Invalidated {invalidated_count} directories")
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
    if normalized_start is not None and not DirectoryIndex.is_in_albums_tree(normalized_start):
        if verbose:
            print(f"WARNING: --start path is outside the albums root, skipping: {normalized_start}")
            print("-" * 60)
        return 0

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

    directories_to_invalidate = list(DirectoryIndex.objects.filter(id__in=directory_ids))
    invalidated_count = len(directories_to_invalidate)
    if verbose:
        print(f"Found {invalidated_count} directories containing link files without virtual_directory")

    if directories_to_invalidate:
        DirectoryIndex.invalidate_caches(directories_to_invalidate)

    if verbose:
        print(f"Invalidated {invalidated_count} directories")
        print("-" * 60)

    return invalidated_count

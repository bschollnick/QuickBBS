"""
Function to add missing directories from filesystem to database.

This module walks the albums directory and adds any missing directories to both
IndexDirs and fs_Cache_Tracking tables. Directories added to fs_Cache_Tracking
are marked as invalidated to ensure they are scanned when accessed via the web.
"""

import os

from django.conf import settings
from django.db import close_old_connections

from cache_watcher.models import fs_Cache_Tracking
from quickbbs.common import normalize_fqpn
from quickbbs.models import IndexDirs


def add_directories(max_count: int = 0) -> None:
    """
    Walk the albums directory and add any missing directories to the database.

    Adds directories to both IndexDirs and fs_Cache_Tracking tables.
    Directories are marked as invalidated in fs_Cache_Tracking to ensure
    they will be scanned when accessed via the web interface.

    Args:
        max_count: Maximum number of directories to add (0 = unlimited)

    Returns:
        None
    """
    print("=" * 60)
    print("Adding missing directories from filesystem to database")
    print("=" * 60)

    # Get the albums root directory
    albums_root = os.path.join(settings.ALBUMS_PATH, "albums")
    albums_root = normalize_fqpn(albums_root)

    if not os.path.exists(albums_root):
        print(f"ERROR: Albums root does not exist: {albums_root}")
        return

    print(f"Scanning albums root: {albums_root}")
    print("Walking filesystem and checking database...")

    # Iterate through filesystem and check database on-the-fly
    added_count = 0
    scanned_count = 0
    cache_instance = fs_Cache_Tracking()

    for root, _, _ in os.walk(albums_root):
        # Normalize the root path
        normalized_root = normalize_fqpn(root)
        scanned_count += 1

        # Progress indicator every 1000 directories
        if scanned_count % 1000 == 0:
            print(f"Scanned {scanned_count} directories, added {added_count}...")

        # Check if directory exists in database
        if not IndexDirs.objects.filter(fqpndirectory=normalized_root).exists():
            try:
                # Add directory to IndexDirs
                _, dir_record = IndexDirs.add_directory(normalized_root)

                if dir_record:
                    # Add to fs_Cache_Tracking and mark as invalidated
                    # This ensures the directory will be scanned when accessed
                    cache_entry = cache_instance.add_to_cache(normalized_root)

                    if cache_entry:
                        # Mark as invalidated so it will be scanned
                        cache_entry.invalidated = True
                        cache_entry.save()

                    added_count += 1

                    # Progress indicator
                    if added_count % 100 == 0:
                        print(f"Added {added_count} directories...")
                        # Close old connections periodically to prevent exhaustion
                        close_old_connections()

                    # Check if we've hit the max_count limit
                    if 0 < max_count <= added_count:
                        print(f"Reached max_count limit of {max_count}")
                        break

            except Exception as e:  # pylint: disable=broad-exception-caught
                print(f"Error adding directory {normalized_root}: {e}")
                continue

        # Break outer loop if max_count reached
        if 0 < max_count <= added_count:
            break

    # Final connection cleanup
    close_old_connections()

    print("=" * 60)
    print(f"Scanned {scanned_count} filesystem directories")
    print(f"Successfully added {added_count} directories to database")
    print("=" * 60)

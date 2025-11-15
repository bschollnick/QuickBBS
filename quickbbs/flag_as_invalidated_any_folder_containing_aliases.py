#!/usr/bin/env python
"""
Flag directories containing .alias files as invalidated.

This script marks all directories containing .alias files as invalidated in the
fs_Cache_Tracking table. This forces these directories to be rescanned on next access,
which will regenerate their thumbnails using the corrected logic that excludes .alias
files from folder cover image selection.

Usage:
    python manage.py shell < flag_as_invalidated_any_folder_containing_aliases.py

Or run directly:
    python flag_as_invalidated_any_folder_containing_aliases.py
"""

import os
import sys
import time


def main():
    """Mark all folders containing .alias files as invalidated."""
    # Setup Django if running as standalone script
    if __name__ == "__main__":
        import django

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.quickbbs_settings")
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        django.setup()

    from django.db import transaction

    from cache_watcher.models import fs_Cache_Tracking
    from quickbbs.models import IndexData

    print("Searching for directories containing .alias files...")

    # Find all directories containing .alias files
    alias_files = IndexData.objects.filter(filetype__fileext=".alias", delete_pending=False).select_related("home_directory").distinct()

    # Get unique directories
    directories_with_aliases = set()
    for alias_file in alias_files:
        if alias_file.home_directory:
            directories_with_aliases.add(alias_file.home_directory)

    print(f"Found {len(directories_with_aliases)} directories containing .alias files")

    if directories_with_aliases:
        # Mark them as invalidated
        with transaction.atomic():
            current_time = time.time()
            invalidated_count = 0

            for directory in directories_with_aliases:
                entry, created = fs_Cache_Tracking.objects.update_or_create(
                    directory=directory,
                    defaults={
                        "invalidated": True,
                        "lastscan": current_time,
                    },
                )
                invalidated_count += 1
                action = "Created and marked" if created else "Marked"
                print(f"{action} as invalidated: {directory.fqpndirectory}")

        print(f"\n✓ Successfully invalidated {invalidated_count} directories")
    else:
        print("No directories with .alias files found")


if __name__ == "__main__":
    main()
else:
    # Running via manage.py shell
    main()

#!/usr/bin/env python
"""Diagnostic script to check cache watcher status."""

import os
import sys

import django

# Setup Django - add parent directory (where manage.py is) to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")
django.setup()

from cache_watcher.models import Cache_Storage, fs_Cache_Tracking

from quickbbs.common import get_dir_sha


def main():
    """Check cache watcher status."""
    print("=== Cache Watcher Diagnostic ===\n")

    # Check total cache entries
    total = fs_Cache_Tracking.objects.count()
    invalidated_count = fs_Cache_Tracking.objects.filter(invalidated=True).count()
    valid_count = fs_Cache_Tracking.objects.filter(invalidated=False).count()

    print(f"Total cache entries: {total}")
    print(f"Valid entries (invalidated=False): {valid_count}")
    print(f"Invalidated entries (invalidated=True): {invalidated_count}")
    print()

    # Show recent invalidated entries
    if invalidated_count > 0:
        print("Recently invalidated directories:")
        recent_invalidated = fs_Cache_Tracking.objects.filter(invalidated=True).order_by("-lastscan")[:10]

        for entry in recent_invalidated:
            print(f"  - {entry.DirName}")
            print(f"    SHA: {entry.directory_sha256[:16]}...")
            print(f"    Last scan: {entry.lastscan}")
        print()

    # Test a specific directory if provided
    if len(sys.argv) > 1:
        test_dir = sys.argv[1]
        print(f"\nTesting directory: {test_dir}")
        dir_sha = get_dir_sha(test_dir)
        print(f"Directory SHA: {dir_sha[:16]}...")

        # Check if exists in cache
        try:
            entry = fs_Cache_Tracking.objects.get(directory_sha256=dir_sha)
            print(f"Found in cache:")
            print(f"  Invalidated: {entry.invalidated}")
            print(f"  Last scan: {entry.lastscan}")
            print(f"  DirName: {entry.DirName}")

            # Check using Cache_Storage method
            is_cached = Cache_Storage.sha_exists_in_cache(dir_sha)
            print(f"  sha_exists_in_cache(): {is_cached}")
        except fs_Cache_Tracking.DoesNotExist:
            print("  Not found in cache")
        print()

    print("\n=== Watchdog Status ===")
    print("Check logs for:")
    print("  - 'Watchdog started monitoring' message")
    print("  - 'Processing N buffered directory changes' messages")
    print("  - 'Successfully invalidated N cache entries' messages")


if __name__ == "__main__":
    main()

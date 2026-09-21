#!/usr/bin/env python
"""
Check ALL files in database for case normalization issues.
"""

from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")

import django  # pylint: disable=wrong-import-position

django.setup()

# pylint: disable=wrong-import-position
from quickbbs.common import normalize_string_title
from quickbbs.fileindex import FileIndex

# pylint: enable=wrong-import-position


def check_all_files():
    """Check all files in database for case consistency."""
    print("=" * 80)
    print("CHECKING ALL FILES IN DATABASE")
    print("=" * 80)
    print()

    total_files = FileIndex.objects.filter(delete_pending=False).count()
    print(f"Total files in database: {total_files:,}")
    print()

    # Check for files that don't match title-case normalization
    inconsistent_files = []

    # Process in batches
    batch_size = 1000
    for offset in range(0, total_files, batch_size):
        files = FileIndex.objects.filter(delete_pending=False).order_by("id")[offset : offset + batch_size]
        for file_entry in files:
            normalized = normalize_string_title(file_entry.name)
            if file_entry.name != normalized:
                inconsistent_files.append((file_entry.id, file_entry.home_directory_id, file_entry.name, normalized))

        if (offset + batch_size) % 10000 == 0:
            print(f"Processed {offset + batch_size:,} files...")

    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print()

    if inconsistent_files:
        print(f"⚠ Found {len(inconsistent_files)} files with non-title-case names:")
        print()

        # Show first 50
        for file_id, dir_id, original, normalized in inconsistent_files[:50]:
            print(f"File ID: {file_id}, Dir ID: {dir_id}")
            print(f"  Current: '{original}'")
            print(f"  Should be: '{normalized}'")
            print()

        if len(inconsistent_files) > 50:
            print(f"... and {len(inconsistent_files) - 50} more")
            print()

        # Analyze patterns
        print("=" * 80)
        print("PATTERN ANALYSIS")
        print("=" * 80)
        print()

        # Check if they're all lowercase
        all_lowercase = sum(1 for _, _, orig, _ in inconsistent_files if orig == orig.lower())
        print(f"All lowercase: {all_lowercase} ({all_lowercase * 100.0 / len(inconsistent_files):.1f}%)")

        # Check if they're all uppercase
        all_uppercase = sum(1 for _, _, orig, _ in inconsistent_files if orig == orig.upper() and orig != orig.lower())
        print(f"All uppercase: {all_uppercase} ({all_uppercase * 100.0 / len(inconsistent_files):.1f}%)")

        # Mixed case
        mixed_case = len(inconsistent_files) - all_lowercase - all_uppercase
        print(f"Mixed case: {mixed_case} ({mixed_case * 100.0 / len(inconsistent_files):.1f}%)")

    else:
        print(f"✓ All {total_files:,} files have consistent title-case names")

    print()


if __name__ == "__main__":
    check_all_files()

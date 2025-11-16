#!/usr/bin/env python
"""
Diagnostic script to test case sensitivity and title-case normalization.

This script checks for potential issues with filename case handling that could
cause files to be deleted and recreated during synchronization.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")

import django

django.setup()

from quickbbs.common import normalize_string_title


def test_title_case_consistency():
    """Test if .title() produces consistent results for various filenames."""
    test_cases = [
        "TEST.JPG",
        "test.jpg",
        "Test.Jpg",
        "Test.JPG",
        "my_file.txt",
        "MY_FILE.TXT",
        "My_File.Txt",
        "some-file.pdf",
        "SOME-FILE.PDF",
        "file's_name.doc",
        "FILE'S_NAME.DOC",
        "abc_def_ghi.png",
        "ABC_DEF_GHI.PNG",
        "IMG_1234.JPG",
        "img_1234.jpg",
    ]

    print("=" * 80)
    print("TITLE-CASE NORMALIZATION TEST")
    print("=" * 80)
    print()

    # Group by normalized result to find collisions
    normalized_groups = {}
    for filename in test_cases:
        normalized = normalize_string_title(filename)
        if normalized not in normalized_groups:
            normalized_groups[normalized] = []
        normalized_groups[normalized].append(filename)

    # Show results
    for normalized, originals in sorted(normalized_groups.items()):
        print(f"Normalized: '{normalized}'")
        for orig in originals:
            print(f"  ← '{orig}'")
        if len(originals) > 1:
            print("  ✓ All variations normalize to same value (good!)")
        print()


def test_case_insensitive_matching():
    """Test case-insensitive matching logic from directoryindex.py."""
    print("=" * 80)
    print("CASE-INSENSITIVE MATCHING TEST")
    print("=" * 80)
    print()

    # Simulate filesystem names (title-cased)
    fs_file_names = [
        "Test.Jpg",
        "My_File.Txt",
        "Some-File.Pdf",
        "Img_1234.Jpg",
    ]

    # Simulate database names (various cases - might differ if imported at different times)
    db_file_names = [
        "test.jpg",        # lowercase (old import?)
        "My_File.Txt",     # exact match
        "SOME-FILE.PDF",   # uppercase (manual entry?)
        "Img_1234.Jpg",    # exact match
        "OLD_FILE.TXT",    # file deleted from filesystem
    ]

    # Build case-insensitive lookup (from directoryindex.py logic)
    fs_names_lower_map = {name.lower(): name for name in fs_file_names}
    db_names_lower_set = {name.lower() for name in db_file_names}

    # Find matching files (case-insensitive)
    matching_lower_names = set(fs_names_lower_map.keys()) & db_names_lower_set

    # Files to update (exist in both)
    print("Files to UPDATE (exist in both FS and DB):")
    for lower_name in sorted(matching_lower_names):
        fs_name = fs_names_lower_map[lower_name]
        db_name = [n for n in db_file_names if n.lower() == lower_name][0]
        match_status = "✓ exact match" if fs_name == db_name else "⚠ case differs"
        print(f"  FS: '{fs_name}' ↔ DB: '{db_name}' ({match_status})")
    print()

    # Files to delete (in DB but not in FS)
    db_names_not_in_fs_lower = db_names_lower_set - matching_lower_names
    db_names_not_in_fs = {name for name in db_file_names if name.lower() in db_names_not_in_fs_lower}
    print("Files to DELETE (in DB but not in FS):")
    for name in sorted(db_names_not_in_fs):
        print(f"  '{name}'")
    print()

    # Files to create (in FS but not in DB)
    fs_file_names_for_creation = [name for name in fs_file_names if name.lower() not in db_names_lower_set]
    print("Files to CREATE (in FS but not in DB):")
    for name in sorted(fs_file_names_for_creation):
        print(f"  '{name}'")
    print()


def check_database_name_consistency():
    """Check actual database for name case consistency issues."""
    from quickbbs.fileindex import FileIndex

    print("=" * 80)
    print("DATABASE NAME CONSISTENCY CHECK")
    print("=" * 80)
    print()

    # Get a sample of files from database
    files = FileIndex.objects.filter(delete_pending=False).order_by("?")[:100]

    if not files:
        print("No files found in database.")
        return

    # Check for files that don't match title-case normalization
    inconsistent_files = []
    for file_entry in files:
        normalized = normalize_string_title(file_entry.name)
        if file_entry.name != normalized:
            inconsistent_files.append((file_entry.name, normalized))

    if inconsistent_files:
        print(f"Found {len(inconsistent_files)} files with non-title-case names:")
        print()
        for original, normalized in inconsistent_files[:20]:  # Show first 20
            print(f"  DB: '{original}'")
            print(f"  →  '{normalized}' (what it should be)")
            print()
        if len(inconsistent_files) > 20:
            print(f"  ... and {len(inconsistent_files) - 20} more")
    else:
        print(f"✓ All {len(files)} sampled files have consistent title-case names")
    print()


def check_for_duplicate_lowercases():
    """Check for files that differ only in case (would cause conflicts)."""
    from quickbbs.fileindex import FileIndex
    from django.db.models import Count
    from django.db.models.functions import Lower

    print("=" * 80)
    print("DUPLICATE LOWERCASE NAMES CHECK")
    print("=" * 80)
    print()

    # Find files in same directory with same lowercase name
    from quickbbs.directoryindex import DirectoryIndex

    dirs = DirectoryIndex.objects.filter(delete_pending=False)[:10]  # Sample 10 directories

    found_duplicates = False
    for directory in dirs:
        # Get files in this directory
        files = FileIndex.objects.filter(
            home_directory=directory,
            delete_pending=False
        ).values_list('name', flat=True)

        # Check for lowercase collisions
        lowercase_map = {}
        for name in files:
            lower = name.lower()
            if lower not in lowercase_map:
                lowercase_map[lower] = []
            lowercase_map[lower].append(name)

        # Report duplicates
        for lower_name, originals in lowercase_map.items():
            if len(originals) > 1:
                found_duplicates = True
                print(f"In directory: {directory.fqpndirectory}")
                print(f"  Lowercase: '{lower_name}'")
                for orig in originals:
                    print(f"    → '{orig}'")
                print()

    if not found_duplicates:
        print("✓ No duplicate lowercase names found in sampled directories")
    print()


if __name__ == "__main__":
    test_title_case_consistency()
    test_case_insensitive_matching()
    check_database_name_consistency()
    check_for_duplicate_lowercases()

    print("=" * 80)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 80)

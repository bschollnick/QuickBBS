#!/usr/bin/env python
"""
Diagnose why files are being deleted and recreated during sync.

This simulates the sync process to identify what's causing the issue.
"""

from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")

import django

django.setup()

from pathlib import Path

from quickbbs.common import normalize_string_title
from quickbbs.directoryindex import DirectoryIndex
from quickbbs.fileindex import FileIndex


def analyze_sync_for_directory(fqpn: str):
    """Analyze what would happen during sync for a specific directory."""
    print("=" * 80)
    print(f"ANALYZING SYNC FOR: {fqpn}")
    print("=" * 80)
    print()

    # Get the DirectoryIndex entry
    found, directory = DirectoryIndex.search_for_directory(fqpn)
    if not found or directory is None:
        print(f"Directory not found in database: {fqpn}")
        return

    print(f"Directory ID: {directory.pk}")
    print(f"Directory path: {directory.fqpndirectory}")
    print()

    # Get DB files
    db_files = list(
        FileIndex.objects.filter(
            home_directory=directory.pk,
            delete_pending=False
        ).values_list("name", flat=True)
    )

    print(f"Files in database: {len(db_files)}")
    print()

    # Get filesystem files
    try:
        path = Path(fqpn)
        if not path.exists():
            print(f"Path does not exist on filesystem: {fqpn}")
            return

        fs_entries = list(path.iterdir())
        fs_file_entries = [e for e in fs_entries if not e.is_dir()]

        # Apply title-case normalization (same as return_disk_listing)
        fs_file_names = [normalize_string_title(e.name) for e in fs_file_entries]

        print(f"Files on filesystem: {len(fs_file_names)}")
        print()

        # Build case-insensitive maps (same as sync_files_with_db)
        fs_names_lower_map = {name.lower(): name for name in fs_file_names}
        db_names_lower_set = {name.lower() for name in db_files}

        # Find matches
        matching_lower_names = set(fs_names_lower_map.keys()) & db_names_lower_set

        # Files to update
        matching_db_names = {name for name in db_files if name.lower() in matching_lower_names}

        # Files to delete
        db_names_not_in_fs_lower = db_names_lower_set - matching_lower_names
        db_names_not_in_fs = {name for name in db_files if name.lower() in db_names_not_in_fs_lower}

        # Files to create
        fs_file_names_for_creation = [name for name in fs_file_names if name.lower() not in db_names_lower_set]

        print("=" * 80)
        print("SYNC ANALYSIS RESULTS")
        print("=" * 80)
        print()
        print(f"Files to UPDATE: {len(matching_db_names)}")
        print(f"Files to DELETE: {len(db_names_not_in_fs)}")
        print(f"Files to CREATE: {len(fs_file_names_for_creation)}")
        print()

        if db_names_not_in_fs:
            print("=" * 80)
            print("FILES TO DELETE (in DB but not on FS):")
            print("=" * 80)
            for name in sorted(db_names_not_in_fs)[:20]:
                print(f"  '{name}'")
                # Check if case variation exists on FS
                if name.lower() in fs_names_lower_map:
                    fs_name = fs_names_lower_map[name.lower()]
                    print(f"    → FS has: '{fs_name}' (case mismatch!)")
            if len(db_names_not_in_fs) > 20:
                print(f"  ... and {len(db_names_not_in_fs) - 20} more")
            print()

        if fs_file_names_for_creation:
            print("=" * 80)
            print("FILES TO CREATE (on FS but not in DB):")
            print("=" * 80)
            for name in sorted(fs_file_names_for_creation)[:20]:
                print(f"  '{name}'")
                # Check if case variation exists in DB
                if name.lower() in db_names_lower_set:
                    db_name = [n for n in db_files if n.lower() == name.lower()][0]
                    print(f"    → DB has: '{db_name}' (case mismatch!)")
            if len(fs_file_names_for_creation) > 20:
                print(f"  ... and {len(fs_file_names_for_creation) - 20} more")
            print()

        # Check for case mismatches that should NOT cause delete/create
        print("=" * 80)
        print("CASE MISMATCH CHECK:")
        print("=" * 80)
        case_mismatches = []
        for db_name in db_files:
            if db_name.lower() in fs_names_lower_map:
                fs_name = fs_names_lower_map[db_name.lower()]
                if db_name != fs_name:
                    case_mismatches.append((db_name, fs_name))

        if case_mismatches:
            print(f"Found {len(case_mismatches)} files with case mismatches:")
            print()
            for db_name, fs_name in case_mismatches[:20]:
                print(f"  DB: '{db_name}'")
                print(f"  FS: '{fs_name}'")
                print(f"  → These MATCH (case-insensitive), should UPDATE not DELETE/CREATE")
                print()
            if len(case_mismatches) > 20:
                print(f"  ... and {len(case_mismatches) - 20} more")
        else:
            print("✓ No case mismatches found")
        print()

    except Exception as e:
        print(f"Error scanning filesystem: {e}")
        import traceback
        traceback.print_exc()


def find_directories_with_issues():
    """Scan all directories to find those with potential sync issues."""
    print("=" * 80)
    print("SCANNING FOR DIRECTORIES WITH POTENTIAL ISSUES")
    print("=" * 80)
    print()

    directories = DirectoryIndex.objects.filter(delete_pending=False)[:50]  # Sample first 50

    problematic_dirs = []

    for directory in directories:
        try:
            path = Path(directory.fqpndirectory)
            if not path.exists():
                continue

            # Get DB files
            db_files = list(
                FileIndex.objects.filter(
                    home_directory=directory.pk,
                    delete_pending=False
                ).values_list("name", flat=True)
            )

            if not db_files:
                continue

            # Get FS files
            fs_entries = [e for e in path.iterdir() if not e.is_dir()]
            fs_file_names = [normalize_string_title(e.name) for e in fs_entries]

            # Quick case mismatch check
            db_names_lower_set = {name.lower() for name in db_files}
            fs_names_lower_set = {name.lower() for name in fs_file_names}

            # Files that match case-insensitively but not exactly
            matching_lower = db_names_lower_set & fs_names_lower_set
            case_mismatches = sum(
                1 for db_name in db_files
                if db_name.lower() in matching_lower
                and db_name not in fs_file_names
            )

            if case_mismatches > 0:
                problematic_dirs.append((directory.fqpndirectory, case_mismatches, len(db_files)))

        except Exception:
            continue

    if problematic_dirs:
        print(f"Found {len(problematic_dirs)} directories with case mismatches:")
        print()
        for fqpn, mismatches, total in sorted(problematic_dirs, key=lambda x: -x[1])[:10]:
            print(f"  {fqpn}")
            print(f"    {mismatches}/{total} files have case mismatches")
        print()
    else:
        print("✓ No directories with case mismatches found")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Analyze specific directory
        analyze_sync_for_directory(sys.argv[1])
    else:
        # Scan for issues
        find_directories_with_issues()

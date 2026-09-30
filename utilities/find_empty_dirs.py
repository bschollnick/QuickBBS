#!/usr/bin/env python3
"""Find empty directories in a directory tree.

This script walks a directory tree and identifies leaf directories that contain
no files (ignoring hidden files) and no subdirectories.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def is_hidden(path: Path) -> bool:
    """Check if a file or directory is hidden (starts with '.').

    :Args:
        path: Path to check

    :Returns:
        True if the path name starts with '.', False otherwise
    """
    return path.name.startswith(".")


def find_empty_directories(root_path: Path) -> list[Path]:
    """Find all empty directories (no files, no subdirectories).

    Walks the directory tree and identifies directories that:
    - Contain no non-hidden files
    - Contain no subdirectories (hidden or otherwise)

    :Args:
        root_path: Starting directory path

    :Returns:
        List of empty directory paths
    """
    empty_dirs: list[Path] = []

    for dirpath, dirnames, filenames in root_path.walk():
        # Filter out hidden files
        non_hidden_files = [f for f in filenames if not f.startswith(".")]

        # Check if this is a leaf directory (no subdirectories) with no non-hidden files
        if not dirnames and not non_hidden_files:
            empty_dirs.append(dirpath)

    return empty_dirs


def main() -> int:
    """Main entry point for the script.

    :Returns:
        Exit code (0 for success, 1 for error)
    """
    parser = argparse.ArgumentParser(
        description="Find empty directories (no files, no subdirectories)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /path/to/directory              # List empty directories
  %(prog)s -v /path/to/directory           # Verbose output
  %(prog)s --delete /path/to/directory     # Delete empty directories
  %(prog)s -v --delete .                   # Delete with verbose output
        """,
    )
    parser.add_argument("directory", type=Path, help="Root directory to search")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show progress while scanning")
    parser.add_argument("--delete", action="store_true", help="Delete the empty directories that are found")

    args = parser.parse_args()

    # Validate directory exists
    if not args.directory.exists():
        print(f"Error: Directory does not exist: {args.directory}", file=sys.stderr)
        return 1

    if not args.directory.is_dir():
        print(f"Error: Not a directory: {args.directory}", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"Scanning directory tree: {args.directory}")

    # Find empty directories
    empty_dirs = find_empty_directories(args.directory)

    # Display results
    if empty_dirs:
        print(f"\nFound {len(empty_dirs)} empty director{'y' if len(empty_dirs) == 1 else 'ies'}:\n")
        for empty_dir in sorted(empty_dirs):
            print(f"  {empty_dir}")

        # Delete if requested
        if args.delete:
            print(f"\nDeleting {len(empty_dirs)} empty director{'y' if len(empty_dirs) == 1 else 'ies'}...")
            deleted_count = 0
            failed_count = 0

            for empty_dir in sorted(empty_dirs):
                try:
                    # Remove any hidden files (like .DS_Store) before deleting directory
                    for item in empty_dir.iterdir():
                        if item.is_file() and is_hidden(item):
                            item.unlink()
                            if args.verbose:
                                print(f"  Removed hidden file: {item}")

                    # Now remove the empty directory
                    empty_dir.rmdir()
                    if args.verbose:
                        print(f"  Deleted: {empty_dir}")
                    deleted_count += 1
                except OSError as e:
                    print(f"  Failed to delete {empty_dir}: {e}", file=sys.stderr)
                    failed_count += 1

            print(f"\nDeleted {deleted_count} director{'y' if deleted_count == 1 else 'ies'}")
            if failed_count:
                print(f"Failed to delete {failed_count} director{'y' if failed_count == 1 else 'ies'}", file=sys.stderr)
    else:
        print(f"\nNo empty directories found in {args.directory}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

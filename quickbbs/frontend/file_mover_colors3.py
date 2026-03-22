"""
STANDALONE FILE MANIPULATION UTILITY - NO DATABASE OPERATIONS

This script and cached_exists.py are standalone file manipulation utilities that use:
- In-memory dictionaries for file caching
- File system operations only
- NO actual database queries or connections

Any references to "database operations" in this context refer to the cached_exists
module's in-memory file caching system, NOT actual database queries.

PATH AND FILENAME NORMALIZATION:
- Source directories can have leading/trailing whitespace in their names
- Target directories will have all whitespace stripped from each path component
- Filenames will have leading/trailing whitespace stripped
- Internal spaces in filenames are converted to underscores
- All directory names are converted to title case in the target

Example:
  Source: /albums/alice - tifa /subdir/ file.jpg
  Target: /target/Alice - Tifa/Subdir/file.jpg
"""

import argparse
import dataclasses
import os
import shutil
import sys
import time
from collections.abc import Generator
from pathlib import Path

import numpy as np
import xattr
from colorama import Fore, Style, init

# Initialize colorama for cross-platform color support
init(autoreset=True)

# Archive extensions to skip (replaces filedb._archives)
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".lzh", ".gz"}

# Filename sanitization translation table (faster than regex)
FILENAME_TRANS = str.maketrans({"?": "", "/": "", ":": "", "#": "_", " ": "_"})


@dataclasses.dataclass(slots=True)
class ProcessingStats:
    """Simple statistics tracking without thread-local complexity."""

    total_files_scanned: int = 0
    files_with_color_tags: int = 0
    files_actually_processed: int = 0
    files_skipped_existing: int = 0
    files_skipped_no_color: int = 0
    errors_encountered: int = 0
    start_time: float | None = None
    end_time: float | None = None
    max_count_reached: bool = False

    def start_timing(self) -> None:
        """Start the timing counter."""
        self.start_time = time.time()

    def stop_timing(self) -> None:
        """Stop the timing counter."""
        self.end_time = time.time()

    def get_duration(self) -> float:
        """Return the total execution time in seconds."""
        if self.start_time is not None and self.end_time is not None:
            return self.end_time - self.start_time
        return 0.0

    def format_duration(self) -> str:
        """Return duration as a human-readable string."""
        duration = self.get_duration()
        if duration < 60:
            return f"{duration:.2f} seconds"
        if duration < 3600:
            minutes = int(duration // 60)
            seconds = duration % 60
            return f"{minutes}m {seconds:.1f}s"

        hours = int(duration // 3600)
        minutes = int((duration % 3600) // 60)
        seconds = duration % 60
        return f"{hours}h {minutes}m {seconds:.0f}s"

    def print_summary(self) -> None:
        """Print comprehensive processing summary."""
        duration = self.get_duration()
        status = "Maximum file count reached" if self.max_count_reached else "Processing complete"
        print(f"\n{status} in {self.format_duration()}")
        print(f"Files scanned: {self.total_files_scanned:,}")
        print(f"Files with color tags: {self.files_with_color_tags:,}")
        print(f"Files processed: {self.files_actually_processed:,}")
        print(f"Skipped (no color): {self.files_skipped_no_color:,}")
        print(f"Skipped (existing): {self.files_skipped_existing:,}")
        print(f"Errors: {self.errors_encountered:,}")

        if duration > 0 and self.total_files_scanned > 0:
            scan_rate = self.total_files_scanned / duration
            print(f"\nPerformance: {scan_rate:.1f} files/second")


@dataclasses.dataclass
class ProcessingConfig:
    """Configuration for a file processing run."""

    operation: str
    max_count: int | None
    existing_files: dict[str, set[str]]


def get_color(filename: str | os.PathLike) -> int:
    """Get macOS Finder color label code for a file.

    Uses np.frombuffer() for zero-copy parsing of the 32-byte FinderInfo struct.

    :Args:
        filename: Path to the file to check

    :return: Color code integer (0 = none, 1-7 = colors)
    """
    try:
        attrs = xattr.xattr(filename)
        finder_attrs = attrs["com.apple.FinderInfo"]
        flags = np.frombuffer(finder_attrs, dtype=np.uint8)
        return int(flags[9] >> 1 & 7)
    except (KeyError, OSError, IndexError):
        return 0


def copy_with_metadata(src: str, dst: str, move: bool = False) -> None:
    """Copy or move file preserving all metadata including extended attributes.

    This function preserves:
    - File content
    - Permissions and timestamps (via shutil.copy2)
    - Extended attributes (xattrs) - critical for macOS aliases

    :Args:
        src: Source file path
        dst: Destination file path
        move: If True, move the file (copy + delete source); if False, copy only
    """
    # Copy file + basic metadata (timestamps, permissions)
    shutil.copy2(src, dst)

    # Copy extended attributes (preserves aliases, Finder info, etc.)
    try:
        src_attrs = xattr.xattr(src)
        dst_attrs = xattr.xattr(dst)
        for attr in src_attrs.list():
            dst_attrs.set(attr, src_attrs.get(attr))
    except OSError:
        # Silently continue if xattr copy fails - file is still copied
        pass

    # Remove source file if moving
    if move:
        os.remove(src)


def process_folder(
    src_dir: str,
    dst_dir: str,
    files: list[str],
    config: ProcessingConfig,
    stats: ProcessingStats,
) -> bool:
    """Process files in a folder, copying/moving only those with color labels.

    :Args:
        src_dir: Source directory path
        dst_dir: Destination directory path
        files: List of filenames to process
        config: Processing configuration (operation, max_count, existing_files cache)
        stats: Statistics tracker to update in place

    :return: True if processing should continue, False if max_count reached
    """
    for file_ in files:
        stats.total_files_scanned += 1

        # Show progress every 500 files
        if stats.total_files_scanned % 500 == 0:
            print(
                f"\r{Fore.CYAN}Processed: {stats.total_files_scanned:,} | "
                f"Colored: {stats.files_with_color_tags:,} | "
                f"Copied: {stats.files_actually_processed:,} | "
                f"Skipped: {stats.files_skipped_no_color + stats.files_skipped_existing:,}{Style.RESET_ALL}",
                end="",
                flush=True,
            )

        # Check if max_count has been reached
        if config.max_count and stats.files_actually_processed >= config.max_count:
            stats.max_count_reached = True
            return False

        src_file = os.path.join(src_dir, file_)
        fext = os.path.splitext(file_)[1].lower()

        # Skip archive files
        if fext in ARCHIVE_EXTENSIONS:
            continue

        # Check color label
        color_code = get_color(src_file)
        if color_code == 0:
            stats.files_skipped_no_color += 1
            continue

        stats.files_with_color_tags += 1

        # Normalize filename: strip leading/trailing whitespace first, then sanitize
        # This handles files like " file.jpg " -> "file.jpg" -> sanitized
        normalized_filename = file_.strip()
        dst_filename = normalized_filename.translate(FILENAME_TRANS)

        # Lazy-load directory contents on first access
        if dst_dir not in config.existing_files:
            # First time seeing this destination directory - scan it now
            config.existing_files[dst_dir] = set()
            if os.path.exists(dst_dir):
                try:
                    for existing_file in os.listdir(dst_dir):
                        # Normalize the same way we do for source files
                        normalized = existing_file.strip()
                        sanitized = normalized.translate(FILENAME_TRANS)
                        config.existing_files[dst_dir].add(sanitized)
                except OSError:
                    pass  # Empty cache for inaccessible directories

        # Check directory-specific index
        if dst_filename in config.existing_files[dst_dir]:
            stats.files_skipped_existing += 1
            continue

        # Ensure destination directory exists (only when we have files with color labels)
        os.makedirs(dst_dir, exist_ok=True)

        dst_file = os.path.join(dst_dir, dst_filename)

        # Perform file operation
        try:
            copy_with_metadata(src_file, dst_file, move=config.operation == "move")
            config.existing_files[dst_dir].add(dst_filename)
            stats.files_actually_processed += 1
        except (OSError, shutil.Error) as e:
            print(f"Error processing {src_file}: {e}")
            stats.errors_encountered += 1

    return True  # Continue processing


def directory_generator(
    root_src_dir: Path,
    root_target_dir: Path,
) -> Generator[tuple[str, str, list[str]], None, None]:
    """Generate (src_dir, dst_dir, files) tuples for all directories containing files.

    Destination paths are normalised: each path component has whitespace stripped,
    spaces converted to underscores, and title case applied.

    CRITICAL: Spaces are converted to underscores BEFORE title casing to prevent
    duplicates. Without this, "Gonig South" and "goning_south" would produce two
    different directories instead of mapping to the same "Goning_South".

    :Args:
        root_src_dir: Resolved source root Path
        root_target_dir: Resolved destination root Path

    :Yields:
        Tuple of (src_dir, dst_dir, files) for each directory containing files
    """
    for src_dir, _, files in os.walk(root_src_dir):
        if not files:
            continue
        rel = Path(src_dir).relative_to(root_src_dir)
        dst_dir = (root_target_dir / rel).resolve()
        parts = dst_dir.parts
        normalized_parts = [parts[0]] + [
            p
            for p in (part.strip().replace(" ", "_").title() for part in parts[1:])
            if p
        ]
        dst_dir = Path(*normalized_parts) if len(normalized_parts) > 1 else Path(normalized_parts[0])
        yield (src_dir, str(dst_dir), files)


def main(args: argparse.Namespace) -> None:
    """Run the file mover/copier for files with macOS Finder color labels.

    :Args:
        args: Parsed command line arguments
    """
    root_src_dir = Path(args.source).resolve()
    root_target_dir = Path(args.target).resolve()

    print(f"Starting with: {root_src_dir}")
    print(f"Target path: {root_target_dir}")
    print(f"Operation: {args.operation}")
    if args.max_count:
        print(f"Maximum files to process: {args.max_count}")

    if not root_src_dir.exists():
        print(f"Error: Source directory '{root_src_dir}' does not exist.")
        sys.exit(1)

    if not root_src_dir.is_dir():
        print(f"Error: Source path '{root_src_dir}' is not a directory.")
        sys.exit(1)

    stats = ProcessingStats()
    stats.start_timing()

    config = ProcessingConfig(
        operation=args.operation,
        max_count=args.max_count,
        existing_files={},
    )

    print("Processing directories...")

    # Process directories sequentially (no threading - simpler and prevents race conditions)
    for src_dir, dst_dir, files in directory_generator(root_src_dir, root_target_dir):
        try:
            if not process_folder(src_dir, dst_dir, files, config, stats):
                break  # max_count reached
        except OSError as e:
            print(f"Error processing {src_dir}: {e}")
            stats.errors_encountered += 1

    # Print newline after progress indicator
    print()
    stats.stop_timing()
    stats.print_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copy or move files with macOS Finder color labels")

    parser.add_argument("source", help="Source directory path")
    parser.add_argument("target", help="Target directory path")
    parser.add_argument(
        "--operation",
        choices=["copy", "move"],
        default="copy",
        help="Operation to perform (default: copy)",
    )
    parser.add_argument(
        "--max-count",
        "--max_count",
        type=int,
        default=None,
        help="Maximum number of files to copy/move (stops after this limit)",
    )

    print("QuickBBS File Mover v3.1 - Optimized Edition")
    print("=" * 45)
    args = parser.parse_args()

    main(args)

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

DIRECTORY EXCLUSIONS (--exclude):
- Pass a comma-separated list of directory name fragments to skip entirely
- Matching is case-insensitive; fragments are checked against each directory name component
- Excluded source directories are never processed and never removed from the target
- Example: --exclude Facebook,Reddit,Fapello,Cfakes
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


def is_excluded_dir(dirname: str, exclude_fragments: list[str]) -> bool:
    """Return True if dirname contains any excluded fragment (case-insensitive).

    Args:
        dirname: The directory name (single path component, not a full path) to test.
        exclude_fragments: List of pre-lowercased fragment strings to match against.

    Returns:
        True if the directory should be excluded from processing.
    """
    if not exclude_fragments:
        return False
    lower = dirname.lower()
    return any(frag in lower for frag in exclude_fragments)


@dataclasses.dataclass(slots=True)
class ProcessingStats:
    """Simple statistics tracking without thread-local complexity."""

    total_files_scanned: int = 0
    files_with_color_tags: int = 0
    files_actually_processed: int = 0
    files_skipped_existing: int = 0
    files_skipped_no_color: int = 0
    errors_encountered: int = 0
    mirror_files_removed: int = 0
    mirror_dirs_removed: int = 0
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
        if self.mirror_files_removed or self.mirror_dirs_removed:
            print(f"Mirror removed files: {self.mirror_files_removed:,}")
            print(f"Mirror removed dirs: {self.mirror_dirs_removed:,}")

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

    Args:
        filename: Path to the file to check.

    Returns:
        Color code integer (0 = none, 1-7 = colors). Returns 0 when the file
        has no FinderInfo attribute or cannot be read.
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

    Args:
        src: Source file path.
        dst: Destination file path.
        move: If True, move the file (copy + delete source); if False, copy only.
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

    Args:
        src_dir: Source directory path.
        dst_dir: Destination directory path.
        files: List of filenames to process.
        config: Processing configuration (operation, max_count, existing_files cache).
        stats: Statistics tracker to update in place.

    Returns:
        True if processing should continue, False if max_count was reached.
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
    exclude_fragments: list[str] | None = None,
) -> Generator[tuple[str, str, list[str]], None, None]:
    """Generate (src_dir, dst_dir, files) tuples for all directories containing files.

    Destination paths are normalised: each path component has whitespace stripped,
    spaces converted to underscores, and title case applied.

    CRITICAL: Spaces are converted to underscores BEFORE title casing to prevent
    duplicates. Without this, "Gonig South" and "goning_south" would produce two
    different directories instead of mapping to the same "Goning_South".

    Args:
        root_src_dir: Resolved source root Path.
        root_target_dir: Resolved destination root Path.
        exclude_fragments: Pre-lowercased directory name fragments to skip entirely.
            Any directory whose name contains a fragment (and all its descendants)
            is excluded from processing.

    Yields:
        Tuple of (src_dir, dst_dir, files) for each non-excluded directory with files.
    """
    frags = exclude_fragments or []
    for src_dir, dirs, files in os.walk(root_src_dir, topdown=True):
        if frags:
            dirs[:] = [d for d in dirs if not is_excluded_dir(d, frags)]
        if not files:
            continue
        rel = Path(src_dir).relative_to(root_src_dir)
        dst_dir = (root_target_dir / rel).resolve()
        parts = dst_dir.parts
        normalized_parts = [parts[0]] + [p for p in (part.strip().replace(" ", "_").title() for part in parts[1:]) if p]
        dst_dir = Path(*normalized_parts) if len(normalized_parts) > 1 else Path(normalized_parts[0])
        yield (src_dir, str(dst_dir), files)


def build_expected_target_paths(
    root_src_dir: Path,
    root_target_dir: Path,
    exclude_fragments: list[str] | None = None,
) -> set[Path]:
    """Build the set of all paths that should exist in the target after a mirror copy.

    Walks the source tree and computes the normalized target path for every source
    file and directory using the same normalization as directory_generator(). Also
    adds all ancestor directories so intermediate dirs are not flagged as orphans.
    Excluded source directories (and their descendants) are omitted entirely.

    Args:
        root_src_dir: Resolved source root Path.
        root_target_dir: Resolved destination root Path.
        exclude_fragments: Pre-lowercased directory name fragments to skip. Excluded
            source directories produce no expected target entries.

    Returns:
        Set of Path objects for every file, dir, and ancestor dir expected in target.
    """
    frags = exclude_fragments or []
    expected: set[Path] = set()

    for src_dir, subdirs, files in os.walk(root_src_dir, topdown=True):
        if frags:
            subdirs[:] = [d for d in subdirs if not is_excluded_dir(d, frags)]
        src_path = Path(src_dir)
        rel = src_path.relative_to(root_src_dir)

        # Normalize only the relative portion — apply title-case/underscore to rel parts only,
        # keeping root_target_dir untouched so system path components aren't mangled.
        normalized_rel_parts = [p for p in (part.strip().replace(" ", "_").title() for part in rel.parts) if p]
        dst_dir = root_target_dir.joinpath(*normalized_rel_parts) if normalized_rel_parts else root_target_dir

        # Add this dir and all its ancestors up to (not including) root_target_dir
        ancestor = dst_dir
        while ancestor != root_target_dir:
            expected.add(ancestor)
            ancestor = ancestor.parent
            if ancestor == ancestor.parent:
                break  # safety: stop at filesystem root

        # Add expected target path for each file
        for file_ in files:
            normalized_filename = file_.strip()
            dst_filename = normalized_filename.translate(FILENAME_TRANS)
            expected.add(dst_dir / dst_filename)

    return expected


def mirror_cleanup(
    root_src_dir: Path,
    root_target_dir: Path,
    stats: ProcessingStats,
    exclude_fragments: list[str] | None = None,
) -> None:
    """Remove files and directories in the target that have no counterpart in the source.

    Walks the target tree bottom-up so files are removed before their parent
    directories are evaluated. Uses os.rmdir() for directories so only truly
    empty (and orphaned) dirs are removed. Target directories whose path contains
    an excluded fragment are skipped entirely and left untouched.

    Args:
        root_src_dir: Resolved source root Path.
        root_target_dir: Resolved destination root Path.
        stats: Statistics tracker updated in place.
        exclude_fragments: Pre-lowercased directory name fragments. Target dirs
            matching any fragment (and all their contents) are preserved as-is.
    """
    frags = exclude_fragments or []
    if not root_target_dir.exists():
        return

    print(f"{Fore.YELLOW}Mirror cleanup: checking target for orphaned files...{Style.RESET_ALL}")
    expected = build_expected_target_paths(root_src_dir, root_target_dir, frags)

    for target_dir, _, files in os.walk(root_target_dir, topdown=False):
        target_dir_path = Path(target_dir).resolve()

        # Preserve excluded target subtrees — skip if any path component matches a fragment.
        # topdown=False queues all dirs before yielding, so pruning dirs[:] has no effect;
        # the per-dir check here covers all descendants because child paths share the fragment.
        if frags and any(is_excluded_dir(part, frags) for part in target_dir_path.parts):
            continue

        # Remove orphaned files
        for file_ in files:
            file_path = (target_dir_path / file_).resolve()
            if file_path not in expected:
                try:
                    os.remove(file_path)
                    print(f"  {Fore.RED}Removed file:{Style.RESET_ALL} {file_path}")
                    stats.mirror_files_removed += 1
                except OSError as e:
                    print(f"  Error removing {file_path}: {e}")
                    stats.errors_encountered += 1

        # Remove orphaned directories (only if empty after file removals)
        if target_dir_path == root_target_dir:
            continue
        if target_dir_path not in expected:
            try:
                os.rmdir(target_dir_path)
                print(f"  {Fore.RED}Removed dir: {Style.RESET_ALL} {target_dir_path}")
                stats.mirror_dirs_removed += 1
            except OSError:
                # Dir is not empty or not accessible — leave it
                pass


def main(args: argparse.Namespace) -> None:
    """Run the file mover/copier for files with macOS Finder color labels.

    Args:
        args: Parsed command line arguments.
    """
    root_src_dir = Path(args.source).resolve()
    root_target_dir = Path(args.target).resolve()
    exclude_fragments = [f.strip().lower() for f in args.exclude.split(",") if f.strip()]

    print(f"Starting with: {root_src_dir}")
    print(f"Target path: {root_target_dir}")
    print(f"Operation: {args.operation}")
    if args.max_count:
        print(f"Maximum files to process: {args.max_count}")
    if args.mirror:
        print("Mirror mode: orphaned target files will be removed")
    if exclude_fragments:
        print(f"Excluding directories containing: {', '.join(exclude_fragments)}")

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
    for src_dir, dst_dir, files in directory_generator(root_src_dir, root_target_dir, exclude_fragments):
        try:
            if not process_folder(src_dir, dst_dir, files, config, stats):
                break  # max_count reached
        except OSError as e:
            print(f"Error processing {src_dir}: {e}")
            stats.errors_encountered += 1

    # Print newline after progress indicator
    print()

    if args.mirror:
        mirror_cleanup(root_src_dir, root_target_dir, stats, exclude_fragments)

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
    parser.add_argument(
        "--mirror",
        action="store_true",
        default=False,
        help="Mirror mode: remove files/dirs in target that do not exist in source",
    )
    parser.add_argument(
        "--exclude",
        default="",
        metavar="FRAGMENTS",
        help="Comma-separated directory name fragments to exclude (case-insensitive). "
        "Any source directory whose name contains a fragment is skipped entirely, "
        "and its target counterpart is preserved. "
        "Example: --exclude Facebook,Reddit,Fapello,Cfakes",
    )

    print("QuickBBS File Mover v3.1 - Optimized Edition")
    print("=" * 45)
    args = parser.parse_args()

    main(args)

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
import os
import shutil
import sys
import time
from hashlib import sha224
from pathlib import Path
from struct import unpack

import xattr
from colorama import Fore, Style, init

# Initialize colorama for cross-platform color support
init(autoreset=True)

# Simple file processing without external dependencies

# Archive extensions to skip (replaces filedb._archives)
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".lzh", ".gz"}

# Maximum file size for SHA calculation (2MB)
MAX_SHA_SIZE = 2 * 1024 * 1024


def calculate_sha224(filepath: str) -> str:
    """Calculate SHA224 hash for a file.

    Args:
        filepath: Path to the file

    Returns:
        SHA224 hash as hexadecimal string, or None if error
    """
    try:
        file_size = os.path.getsize(filepath)
        if file_size > MAX_SHA_SIZE:
            return None

        hasher = sha224()
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):  # 64KB chunks
                hasher.update(chunk)
        return hasher.hexdigest()
    except (OSError, IOError):
        return None


def build_global_filename_index(root_target_dir: str) -> set[str]:
    """Build set of all filenames anywhere in target tree.

    This prevents duplicates across the entire target tree - if a file exists
    in Target/Alice/, it won't be copied again to Target/ or Target/Bob/.

    Args:
        root_target_dir: Root target directory path

    Returns:
        Set of sanitized filenames found anywhere in target tree
    """
    filenames = set()

    if not os.path.exists(root_target_dir):
        print(f"{Fore.YELLOW}Target directory does not exist yet - starting fresh{Style.RESET_ALL}")
        return filenames

    print(f"{Fore.CYAN}Scanning target tree for existing files...{Style.RESET_ALL}")
    file_count = 0
    start_time = time.time()

    try:
        for _, _, files in os.walk(root_target_dir):
            for filename in files:
                # Normalize and sanitize filename the same way we do for source files
                # Strip whitespace first, then sanitize
                normalized = filename.strip()
                sanitized = normalized.translate(FILENAME_TRANS)
                filenames.add(sanitized)

                file_count += 1
                if file_count % 1000 == 0:
                    elapsed = time.time() - start_time
                    rate = file_count / elapsed if elapsed > 0 else 0
                    # \r returns cursor to start of line for overwriting
                    print(
                        f"\r{Fore.GREEN}  Scanned: {file_count:,} files " f"({rate:.0f} files/sec){Style.RESET_ALL}",
                        end="",
                        flush=True,
                    )

    except (OSError, PermissionError) as e:
        print(f"\n{Fore.RED}Warning: Could not scan {root_target_dir}: {e}{Style.RESET_ALL}")

    # Final newline after progress indicator
    print()
    elapsed = time.time() - start_time
    print(f"{Fore.GREEN}Found {len(filenames):,} unique filenames in target tree " f"({elapsed:.1f}s){Style.RESET_ALL}")
    return filenames


class ProcessingStats:
    """Simple statistics tracking without thread-local complexity."""

    def __init__(self):
        self.total_files_scanned = 0
        self.files_with_color_tags = 0
        self.files_actually_processed = 0
        self.files_skipped_existing = 0
        self.files_skipped_sha = 0
        self.errors_encountered = 0
        self.start_time = None
        self.end_time = None
        self.max_count_reached = False

    def start_timing(self):
        """Start the timing counter."""
        self.start_time = time.time()

    def stop_timing(self):
        """Stop the timing counter."""
        self.end_time = time.time()

    def get_duration(self) -> float:
        """Get the total execution time in seconds."""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0.0

    def format_duration(self) -> str:
        """Format duration as human-readable string."""
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

    def print_summary(self):
        """Print comprehensive processing summary."""
        duration = self.get_duration()
        status = "Maximum file count reached" if self.max_count_reached else "Processing complete"
        print(f"\n{status} in {self.format_duration()}")
        print(f"Files scanned: {self.total_files_scanned:,}")
        print(f"Files with color tags: {self.files_with_color_tags:,}")
        print(f"Files processed: {self.files_actually_processed:,}")
        print(f"Skipped: {self.files_skipped_existing + self.files_skipped_sha:,}")
        print(f"Errors: {self.errors_encountered:,}")

        if duration > 0 and self.total_files_scanned > 0:
            scan_rate = self.total_files_scanned / duration
            print(f"\nPerformance: {scan_rate:.1f} files/second")


# Global statistics tracker
stats = ProcessingStats()

colornames = {
    0: "none",
    1: "gray",
    2: "green",
    3: "purple",
    4: "blue",
    5: "yellow",
    6: "red",
    7: "orange",
}

# Filename sanitization translation table (faster than regex)
FILENAME_TRANS = str.maketrans({"?": "", "/": "", ":": "", "#": "_", " ": "_"})


def get_color(filename):
    """Get macOS Finder color label for a file using xattr method.

    Args:
        filename: Path to the file to check

    Returns:
        Tuple of (color_code, color_name)
    """
    try:
        attrs = xattr.xattr(filename)
        finder_attrs = attrs["com.apple.FinderInfo"]
        flags = unpack(32 * "B", finder_attrs)
        color = flags[9] >> 1 & 7
        return (color, colornames[color])
    except (KeyError, OSError, FileNotFoundError):
        return (0, colornames[0])


def copy_with_metadata(src: str, dst: str) -> None:
    """Copy file preserving all metadata including extended attributes.

    This function preserves:
    - File content
    - Permissions and timestamps (via shutil.copy2)
    - Extended attributes (xattrs) - critical for macOS aliases

    Args:
        src: Source file path
        dst: Destination file path
    """
    # Copy file + basic metadata (timestamps, permissions)
    shutil.copy2(src, dst)

    # Copy extended attributes (preserves aliases, Finder info, etc.)
    try:
        src_attrs = xattr.xattr(src)
        dst_attrs = xattr.xattr(dst)
        for attr in src_attrs.list():
            dst_attrs.set(attr, src_attrs.get(attr))
    except (OSError, IOError):
        # Silently continue if xattr copy fails - file is still copied
        pass


def process_folder(src_dir, dst_dir, files, config):
    """Process files in a folder, copying/moving only those with color labels.

    Args:
        src_dir: Source directory path
        dst_dir: Destination directory path
        files: List of filenames to process
        config: Dictionary with 'existing_files', 'operation', and 'max_count' keys

    Returns:
        True if processing should continue, False if max_count reached
    """
    stats.total_files_scanned += len(files)

    for file_ in files:
        # Check if max_count has been reached
        if config["max_count"] and stats.files_actually_processed >= config["max_count"]:
            stats.max_count_reached = True
            return False
        src_file = os.path.join(src_dir, file_)
        fext = os.path.splitext(file_)[1].lower()

        # Skip archive files
        if fext in ARCHIVE_EXTENSIONS:
            continue

        # Check color label
        color_code = get_color(src_file)[0]
        if color_code == 0:
            continue

        stats.files_with_color_tags += 1

        # Normalize filename: strip leading/trailing whitespace first, then sanitize
        # This handles files like " file.jpg " -> "file.jpg" -> sanitized
        normalized_filename = file_.strip()
        dst_filename = normalized_filename.translate(FILENAME_TRANS)

        # Check global index - prevents duplicates anywhere in target tree
        if dst_filename in config["existing_files"]:
            stats.files_skipped_existing += 1
            continue

        # Ensure destination directory exists (only when we have files with color labels)
        os.makedirs(dst_dir, exist_ok=True)

        dst_file = os.path.join(dst_dir, dst_filename)

        # Perform file operation
        try:
            if config["operation"] == "copy":
                copy_with_metadata(src_file, dst_file)
            elif config["operation"] == "move":
                # Move preserves xattrs on same filesystem, but copy+delete for cross-filesystem
                copy_with_metadata(src_file, dst_file)
                os.remove(src_file)

            # Update global index after successful operation
            config["existing_files"].add(dst_filename)

            stats.files_actually_processed += 1

        except (OSError, IOError, PermissionError, shutil.Error) as e:
            print(f"Error processing {src_file}: {e}")
            stats.errors_encountered += 1

    return True  # Continue processing


def main(args):
    """Main function to process files with color labels.

    Args:
        args: Parsed command line arguments
    """
    use_shas = getattr(args, "use_shas", False)
    operation = getattr(args, "operation", "copy")
    max_count = getattr(args, "max_count", None)

    root_src_dir = Path(args.source).resolve()
    root_target_dir = Path(args.target).resolve()

    print(f"Starting with: {root_src_dir}")
    print(f"Target path: {root_target_dir}")
    print(f"Operation: {operation}")
    print(f"SHA hashing: {'enabled' if use_shas else 'disabled'}")
    if max_count:
        print(f"Maximum files to process: {max_count}")

    stats.start_timing()

    if not root_src_dir.exists():
        print(f"Error: Source directory '{root_src_dir}' does not exist.")
        sys.exit(1)

    if not root_src_dir.is_dir():
        print(f"Error: Source path '{root_src_dir}' is not a directory.")
        sys.exit(1)

    # Build global filename index to prevent duplicates across entire target tree
    existing_files = build_global_filename_index(str(root_target_dir))

    print("Processing directories...")

    # Create config dictionary to reduce function arguments
    config = {
        "use_shas": use_shas,
        "operation": operation,
        "max_count": max_count,
        "existing_files": existing_files,  # Global index shared across all processing
    }

    def directory_generator():
        """Generate directory information for processing.

        Yields:
            Tuple of (src_dir, dst_dir, files) for each directory containing files

        Uses os.walk to traverse the source directory tree and yields processing
        information for directories that contain files. Destination paths are
        transformed to title case and all path components are stripped of
        leading/trailing whitespace.
        """
        for src_dir, _, files in os.walk(str(root_src_dir)):
            if files:  # Only yield directories with files
                dst_dir = Path(src_dir.replace(str(root_src_dir), str(root_target_dir))).resolve()

                # Normalize path: strip whitespace from each component and apply title case
                # This handles directories like "alice_with_cats - tifa /" -> "alice_with_cats - tifa/"
                parts = dst_dir.parts
                normalized_parts = [parts[0]]  # Keep root as-is
                for part in parts[1:]:
                    # Strip leading/trailing whitespace and apply title case
                    normalized_part = part.strip().title()
                    if normalized_part:  # Only add non-empty parts
                        normalized_parts.append(normalized_part)

                dst_dir = Path(*normalized_parts) if len(normalized_parts) > 1 else Path(normalized_parts[0])
                yield (src_dir, str(dst_dir), files)

    # Process directories sequentially (no threading - simpler and prevents race conditions)
    for src_dir, dst_dir, files in directory_generator():
        try:
            if not process_folder(src_dir, dst_dir, files, config):
                break  # max_count reached
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            print(f"Error processing {src_dir}: {e}")
            stats.errors_encountered += 1
            # Continue despite errors

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
        "--use-shas",
        action="store_true",
        help="Use SHA224 hashing for duplicate detection (currently unused)",
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

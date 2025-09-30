"""
STANDALONE FILE MANIPULATION UTILITY - NO DATABASE OPERATIONS

This script and cached_exists.py are standalone file manipulation utilities that use:
- In-memory dictionaries for file caching
- File system operations only
- NO actual database queries or connections

Any references to "database operations" in this context refer to the cached_exists
module's in-memory file caching system, NOT actual database queries.
"""

import argparse
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha224
from pathlib import Path
from struct import unpack

import xattr

# Simple file processing without external dependencies

MAX_THREADS = 4  # Optimal for I/O-bound operations

# Archive extensions to skip (replaces filedb._archives)
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".lzh", ".gz"}

# Maximum file size for SHA calculation (2MB)
MAX_SHA_SIZE = 2 * 1024 * 1024


def calculate_sha224(filepath: str) -> str:
    """Calculate SHA224 hash for a file.

    :Args:
        filepath: Path to the file

    :Returns:
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


def scan_destination_directory(dst_dir: str, use_shas: bool) -> dict[str, str]:
    """Scan destination directory for existing files.

    :Args:
        dst_dir: Destination directory path
        use_shas: Whether to calculate SHA224 hashes

    :Returns:
        Dictionary with filename as key, value is None (no SHA) or SHA224 hash
    """
    file_map = {}

    try:
        # Use os.walk for consistency, only process the immediate directory
        for root, _, files in os.walk(dst_dir):
            if root != dst_dir:  # Skip subdirectories
                continue

            for filename in files:
                filepath = os.path.join(root, filename)
                sha_value = None

                if use_shas:
                    try:
                        file_size = os.path.getsize(filepath)
                        if file_size <= MAX_SHA_SIZE:
                            sha_value = calculate_sha224(filepath)
                    except OSError:
                        pass  # sha_value remains None

                file_map[filename] = sha_value
            break  # Only process the first (target) directory
    except (OSError, PermissionError):
        pass  # Return empty dict if directory can't be read

    return file_map


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
        print(f"\nProcessing complete in {self.format_duration()}")
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


def get_color(filename):
    """Get macOS Finder color label for a file using xattr method.

    :Args:
        filename: Path to the file to check

    :Returns:
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


# Pre-compile regex for filename sanitization
replacements = {"?": "", "/": "", ":": "", "#": "_"}
regex = re.compile(f"({'|'.join(map(re.escape, replacements.keys()))})")


def multiple_replace(dictdata, text):
    """Replace multiple characters in filename using regex.

    :Args:
        dictdata: Dictionary mapping characters to replace with their replacements
        text: Text string to perform replacements on

    :Returns:
        String with specified characters replaced according to dictdata mapping
    """
    return regex.sub(lambda mo: dictdata[mo.string[mo.start() : mo.end()]], text)


def process_folder(src_dir, dst_dir, files, config):
    """Process files in a folder, copying/moving only those with color labels.

    :Args:
        src_dir: Source directory path
        dst_dir: Destination directory path
        files: List of filenames to process
        config: Dictionary with 'use_shas' and 'operation' keys
    """
    # Scan destination directory for existing files (per-directory scope) - only if it exists
    existing_file_map = scan_destination_directory(dst_dir, config["use_shas"]) if os.path.exists(dst_dir) else {}

    stats.total_files_scanned += len(files)

    for file_ in files:
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

        # Ensure destination directory exists (only when we have files with color labels)
        os.makedirs(dst_dir, exist_ok=True)

        # Sanitize destination filename
        dst_filename = multiple_replace(replacements, file_).replace(" ", "_")
        dst_file = os.path.join(dst_dir, dst_filename)

        # Check if file already exists
        if dst_filename in existing_file_map:
            stats.files_skipped_existing += 1
            continue

        # Check SHA if enabled
        src_sha = None
        if config["use_shas"]:
            try:
                src_sha = calculate_sha224(src_file)
                if src_sha and src_sha in existing_file_map.values():
                    stats.files_skipped_sha += 1
                    continue
            except (OSError, IOError, PermissionError):
                src_sha = None

        # Perform file operation
        try:
            if config["operation"] == "copy":
                shutil.copy2(src_file, dst_file)
            elif config["operation"] == "move":
                shutil.move(src_file, dst_file)

            # Update local tracking for this directory (no persistent cache needed)
            existing_file_map[dst_filename] = src_sha if config["use_shas"] else None

            stats.files_actually_processed += 1

        except (OSError, IOError, PermissionError, shutil.Error) as e:
            print(f"Error processing {src_file}: {e}")
            stats.errors_encountered += 1


def main(args):
    """Main function to process files with color labels.

    :Args:
        args: Parsed command line arguments
    """
    use_shas = getattr(args, "use_shas", False)
    operation = getattr(args, "operation", "copy")
    max_threads = getattr(args, "threads", MAX_THREADS)

    root_src_dir = Path(args.source).resolve()
    root_target_dir = Path(args.target).resolve()

    print(f"Starting with: {root_src_dir}")
    print(f"Target path: {root_target_dir}")
    print(f"Operation: {operation}")
    print(f"Threads: {max_threads}")
    print(f"SHA hashing: {'enabled' if use_shas else 'disabled'}")

    stats.start_timing()

    if not root_src_dir.exists():
        print(f"Error: Source directory '{root_src_dir}' does not exist.")
        sys.exit(1)

    if not root_src_dir.is_dir():
        print(f"Error: Source path '{root_src_dir}' is not a directory.")
        sys.exit(1)

#    root_target_dir.mkdir(parents=True, exist_ok=True)

    # No persistent cache needed - using per-directory processing

    print("Processing directories...")

    # Create config dictionary to reduce function arguments
    config = {"use_shas": use_shas, "operation": operation}

    def process_wrapper(folder_info):
        """Process a single directory with error handling.

        :Args:
            folder_info: Tuple of (src_dir, dst_dir, files) to process
        """
        src_dir, dst_dir, files = folder_info
        try:
            process_folder(src_dir, dst_dir, files, config)
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            print(f"Error processing {src_dir}: {e}")
            stats.errors_encountered += 1

    def directory_generator():
        """Generate directory information for processing.

        :Yields:
            Tuple of (src_dir, dst_dir, files) for each directory containing files

        Uses os.walk to traverse the source directory tree and yields processing
        information for directories that contain files. Destination paths are
        transformed to title case with spaces replaced by underscores.
        """
        for src_dir, _, files in os.walk(str(root_src_dir)):
            if files:  # Only yield directories with files
                dst_dir = Path(
                    src_dir.replace(str(root_src_dir), str(root_target_dir))
                ).resolve()
                dst_dir = dst_dir.parent / dst_dir.name.title().replace(" ", "_")
                yield (src_dir, str(dst_dir), files)

    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        executor.map(process_wrapper, directory_generator())

    stats.stop_timing()
    stats.print_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Copy or move files with macOS Finder color labels"
    )

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
        help="Use SHA224 hashing for duplicate detection",
    )
    parser.add_argument(
        "--threads",
        "-t",
        type=int,
        default=MAX_THREADS,
        help=f"Number of worker threads (default: {MAX_THREADS})",
    )

    print("QuickBBS File Mover v3.0 - Performance Optimized")
    print("=" * 45)
    args = parser.parse_args()

    main(args)

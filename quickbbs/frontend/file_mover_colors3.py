import argparse
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from struct import unpack

import imagehash
import xattr

# Import the standalone cached_exists module
from depreciated.cached_exists import cached_exist

MAX_THREADS = 8  # Optimal for I/O-bound operations


class ProcessingStats:
    """Track file processing statistics across all threads."""

    def __init__(self):
        self.total_files_scanned = 0
        self.files_with_color_tags = 0
        self.files_actually_processed = 0
        self.files_skipped_existing = 0
        self.files_skipped_sha = 0
        self.files_skipped_imagehash = 0
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
        elif duration < 3600:
            minutes = int(duration // 60)
            seconds = duration % 60
            return f"{minutes}m {seconds:.1f}s"
        else:
            hours = int(duration // 3600)
            minutes = int((duration % 3600) // 60)
            seconds = duration % 60
            return f"{hours}h {minutes}m {seconds:.0f}s"

    def print_summary(self):
        """Print comprehensive processing summary."""
        print(f"\n{'='*60}")
        print("PROCESSING COMPLETE - SUMMARY")
        print(f"{'='*60}")
        print(f"Total execution time: {self.format_duration()}")
        print(f"Total files scanned: {self.total_files_scanned:,}")
        print(f"Files with color tags (eligible): {self.files_with_color_tags:,}")
        print(f"Files actually copied/moved: {self.files_actually_processed:,}")
        print()
        print("Skipped files breakdown:")
        print(f"  • Already exists: {self.files_skipped_existing:,}")
        print(f"  • Duplicate SHA: {self.files_skipped_sha:,}")
        print(f"  • Duplicate image hash: {self.files_skipped_imagehash:,}")
        print(f"  • Errors: {self.errors_encountered:,}")

        total_skipped = (self.files_skipped_existing + self.files_skipped_sha +
                        self.files_skipped_imagehash + self.errors_encountered)
        print(f"  • Total skipped: {total_skipped:,}")

        if self.get_duration() > 0:
            rate = self.total_files_scanned / self.get_duration()
            print(f"\nProcessing rate: {rate:.1f} files/second")


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
    """Get macOS Finder color label for a file.

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
    except (KeyError, OSError, FileNotFoundError):
        color = 0

    return (color, colornames[color])


# Pre-compile regex for filename sanitization
FILENAME_REPLACEMENTS = {"?": "", "/": "", ":": "", "#": "_"}
FILENAME_REGEX = re.compile("(%s)" % "|".join(map(re.escape, FILENAME_REPLACEMENTS.keys())))


def sanitize_filename(filename: str) -> str:
    """Sanitize filename by removing/replacing invalid characters.

    :Args:
        filename: Original filename to sanitize

    :Returns:
        Sanitized filename safe for filesystem use
    """
    sanitized = FILENAME_REGEX.sub(lambda mo: FILENAME_REPLACEMENTS[mo.group()], filename)
    return sanitized.replace(" ", "_")


def process_folder(src_dir: str, dst_dir: str, files: list, use_shas: bool,
                  use_imagehash: bool, filedb, operation: str = "copy") -> None:
    """Process files in a folder, copying/moving only those with color labels.

    :Args:
        src_dir: Source directory path
        dst_dir: Destination directory path
        files: List of filenames to process
        use_shas: Whether to use SHA224 hashing for duplicate detection
        use_imagehash: Whether to use image hashing for duplicate detection
        filedb: Cached exists database instance
        operation: Either 'copy' or 'move'
    """
    # Track total files scanned
    stats.total_files_scanned += len(files)

    # Pre-filter files by color label and extension
    labeled_files = []
    for file_ in files:
        src_file = os.path.join(src_dir, file_)
        fext = os.path.splitext(file_)[1].lower()

        # Skip archive files early
        if fext in filedb._archives:
            continue

        # Check color label
        if get_color(src_file)[0] != 0:
            labeled_files.append((file_, fext, src_file))
            stats.files_with_color_tags += 1

    if not labeled_files:
        return  # No labeled files to process

    # Only read destination directory if we have labeled files to process
    filedb.read_path(dst_dir, recursive=True)

    # Ensure destination directory exists
    os.makedirs(dst_dir, exist_ok=True)

    # Process only the labeled files
    for file_, fext, src_file in labeled_files:
        dst_filename = sanitize_filename(file_)
        dst_file = os.path.join(dst_dir, dst_filename)

        # Check if file already exists by filename
        if filedb.search_file_exist(dst_filename)[0]:
            stats.files_skipped_existing += 1
            continue

        src_sha = None
        src_hash = None

        # Generate and check SHA224 if enabled
        if use_shas:
            src_sha = filedb.generate_sha224(src_file, hexdigest=True)
            if src_sha and filedb.search_sha224_exist(shaHD=src_sha)[0]:
                stats.files_skipped_sha += 1
                continue

        # Generate and check image hash if enabled
        if use_imagehash and fext in filedb._graphics:
            src_hash = filedb.generate_imagehash(src_file)
            if src_hash and filedb.search_imagehash_exist(img_hash=src_hash)[0]:
                stats.files_skipped_imagehash += 1
                continue

        # Perform the file operation
        try:
            if operation == "copy":
                shutil.copy2(src_file, dst_file)
            elif operation == "move":
                shutil.move(src_file, dst_file)
            else:
                print(f"Unknown operation: {operation}")
                stats.errors_encountered += 1
                continue

            # Add file to cache
            filedb.addFile(
                dirpath=dst_dir,
                filename=dst_filename,
                sha_hd=src_sha,
                filesize=None,
                mtime=None,
                img_hash=src_hash,
            )

            stats.files_actually_processed += 1
            print(f"Processed: {src_file} -> {dst_file}")

        except (OSError, IOError) as e:
            print(f"Error processing {src_file}: {e}")
            stats.errors_encountered += 1
            continue


def main(args) -> None:
    """Main function to process files with color labels.

    :Args:
        args: Parsed command line arguments
    """
    # Configuration
    use_imagehash = getattr(args, 'use_imagehash', False)
    use_shas = getattr(args, 'use_shas', False)
    operation = getattr(args, 'operation', 'copy')
    max_threads = getattr(args, 'threads', MAX_THREADS)

    root_src_dir = Path(args.source).resolve()
    root_target_dir = Path(args.target).resolve()

    print(f"Starting with: {root_src_dir}")
    print(f"Target path: {root_target_dir}")
    print(f"Operation: {operation}")
    print(f"Threads: {max_threads}")
    print(f"SHA hashing: {'enabled' if use_shas else 'disabled'}")
    print(f"Image hashing: {'enabled' if use_imagehash else 'disabled'}")
    print()

    # Start timing
    stats.start_timing()

    if not root_src_dir.exists():
        print(f"Error: Source directory '{root_src_dir}' does not exist.")
        sys.exit(1)

    if not root_src_dir.is_dir():
        print(f"Error: Source path '{root_src_dir}' is not a directory.")
        sys.exit(1)

    # Create target directory if it doesn't exist
    root_target_dir.mkdir(parents=True, exist_ok=True)

    # Create shared cache instance with thread safety
    try:
        filedb = cached_exist(
            use_shas=use_shas,
            use_image_hash=use_imagehash,
            FilesOnly=True,
            image_hasher=imagehash.phash,
        )
        filedb.MAX_SHA_SIZE = 1024 * 1024 * 2
    except Exception as e:
        print(f"Error initializing file database: {e}")
        sys.exit(1)

    # Collect all directories to process
    folders_to_process = []
    try:
        for src_dir, dirs, files in os.walk(str(root_src_dir), topdown=True):
            # Skip empty directories or directories with no files
            if not files:
                continue

            dst_dir = Path(src_dir.replace(str(root_src_dir), str(root_target_dir))).resolve()
            # Convert to title case and replace spaces with underscores
            dst_dir = dst_dir.parent / dst_dir.name.title().replace(" ", "_")

            folders_to_process.append((src_dir, str(dst_dir), files))

    except OSError as e:
        print(f"Error walking source directory: {e}")
        sys.exit(1)

    if not folders_to_process:
        print("No files found to process.")
        return

    print(f"Found {len(folders_to_process)} directories to process...")

    # Process folders with ThreadPoolExecutor
    processed_count = 0
    error_count = 0

    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        # Submit all tasks
        future_to_folder = {
            executor.submit(
                process_folder, src_dir, dst_dir, files, use_shas, use_imagehash, filedb, operation
            ): (src_dir, dst_dir)
            for src_dir, dst_dir, files in folders_to_process
        }

        # Process completed tasks
        for future in future_to_folder:
            src_dir, dst_dir = future_to_folder[future]
            try:
                future.result()  # This will raise any exception that occurred
                processed_count += 1
            except Exception as e:
                error_count += 1
                print(f"Error processing folder '{src_dir}': {e}")
                stats.errors_encountered += 1
                continue

    # Stop timing and print comprehensive summary
    stats.stop_timing()
    stats.print_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Copy or move files with macOS Finder color labels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /path/to/source /path/to/target
  %(prog)s --move --use-shas /path/to/source /path/to/target
  %(prog)s --threads 4 --use-imagehash /path/to/source /path/to/target
        """
    )

    parser.add_argument("source", help="Source directory path")
    parser.add_argument("target", help="Target directory path")

    parser.add_argument(
        "--operation", "--op",
        choices=["copy", "move"],
        default="copy",
        help="Operation to perform (default: copy)"
    )

    parser.add_argument(
        "--use-shas", "--shas",
        action="store_true",
        help="Use SHA224 hashing for duplicate detection"
    )

    parser.add_argument(
        "--use-imagehash", "--imagehash",
        action="store_true",
        help="Use perceptual image hashing for duplicate detection"
    )

    parser.add_argument(
        "--threads", "-t",
        type=int,
        default=MAX_THREADS,
        help=f"Number of worker threads (default: {MAX_THREADS})"
    )

    parser.add_argument(
        "--version", "-v",
        action="version",
        version="%(prog)s 3.0 - macOS Color Label File Mover"
    )

    print("QuickBBS File Mover v3.0")
    print("=" * 40)
    args = parser.parse_args()
    main(args)

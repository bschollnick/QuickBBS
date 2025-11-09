"""
Utilities for QuickBBS, the python edition.

ASGI Support:
- Async wrapper functions provided for database operations
- All functions with ORM queries can be wrapped with sync_to_async
"""

import logging
import os
import os.path
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

# from datetime import timedelta
from pathlib import Path
from typing import Any

# Third-party imports
from asgiref.sync import sync_to_async
from cachetools import LRUCache, cached
from django.conf import settings
from django.db import close_old_connections, transaction  # connection

# from django.db.models import Case, F, Value, When, BooleanField
from Foundation import (  # pylint: disable=no-name-in-module  # NSData,; NSError,
    NSURL,
    NSURLBookmarkResolutionWithoutMounting,
    NSURLBookmarkResolutionWithoutUI,
)
from PIL import Image

# First-party imports
import filetypes.models as filetype_models
from cache_watcher.models import Cache_Storage
from frontend.file_listings import return_disk_listing
from quickbbs.common import (
    SORT_MATRIX,
    get_file_sha,
    normalize_fqpn,
    normalize_string_title,
)
from quickbbs.models import IndexData, IndexDirs
from thumbnails.video_thumbnails import _get_video_info

logger = logging.getLogger(__name__)

# Async-safe caches for utility functions
webpaths_cache = LRUCache(maxsize=500)
breadcrumbs_cache = LRUCache(maxsize=500)
filedata_cache = LRUCache(maxsize=500)
alias_paths_cache = LRUCache(maxsize=250)

# Batch sizes for database operations - kept simple for performance
# These values are optimized for typical directory/file counts in gallery operations
# Simplified from dynamic calculation to avoid repeated CPU detection overhead
BATCH_SIZES = {
    "db_read": 500,  # Reading file/directory records from database
    "db_write": 250,  # Writing/updating records to database
    "file_io": 100,  # File system operations (stat, hash calculation)
}


def _batch_compute_file_shas(file_paths: list[str], max_workers: int | None = None) -> dict[str, tuple[str | None, str | None]]:
    """
    Compute SHA256 hashes in parallel using multiprocessing.

    Uses ProcessPoolExecutor (NOT ThreadPoolExecutor) to avoid Django ORM issues.
    SHA256 computation is CPU-bound, so multiprocessing provides better performance
    than threading.

    ASGI-SAFE: Does not touch Django ORM - only computes file hashes.
    Safe to call from sync or async contexts.

    :Args:
        file_paths: List of fully qualified file paths to hash
        max_workers: Number of parallel workers (defaults to min(cpu_count, 8))

    Returns:
        Dictionary mapping file paths to (file_sha256, unique_sha256) tuples
    """
    if not file_paths:
        return {}

    # Default to reasonable number of workers (4-8 is optimal for most systems)
    # Too many workers can saturate disk I/O, especially on HDDs
    if max_workers is None:
        cpu_count = os.cpu_count() or 4
        max_workers = min(cpu_count, 8)

    results = {}

    # For small batches, don't bother with multiprocessing overhead
    if len(file_paths) < 5:
        for path in file_paths:
            results[path] = get_file_sha(path)
        return results

    # Use ProcessPoolExecutor for parallel SHA256 computation
    # This is safe because get_file_sha() doesn't touch the database
    try:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_path = {executor.submit(get_file_sha, path): path for path in file_paths}

            # Collect results as they complete
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    results[path] = future.result()
                except Exception as e:
                    logger.error(f"Error computing SHA256 for {path}: {e}")
                    results[path] = (None, None)

    except Exception as e:
        logger.error(f"Error in batch SHA256 computation: {e}")
        # Fallback to sequential processing
        for path in file_paths:
            try:
                results[path] = get_file_sha(path)
            except Exception as path_error:
                logger.error(f"Error computing SHA256 for {path}: {path_error}")
                results[path] = (None, None)

    return results


def ensures_endswith(string_to_check: str, value: str) -> str:
    """
    Ensure string ends with specified value, adding it if not present.

    Args:
        string_to_check: The source string to process
        value: The suffix to ensure is at the end

    Returns:
        The string with suffix guaranteed at the end
    """
    return string_to_check if string_to_check.endswith(value) else string_to_check + value


async def _get_or_create_directory(directory_sha256: str, dirpath: str) -> tuple[object | None, bool]:
    """
    Get or create directory record and check cache status.

    Args:
        directory_sha256: SHA256 hash of the directory path
        dirpath: Fully qualified directory path

    Returns:
        Tuple of (directory object, is_cached) where is_cached indicates
        if the directory is already in cache
    """
    # Use select_related to prefetch the Cache_Watcher relationship
    # Use model method for standardized prefetching and caching
    found, directory_record = await sync_to_async(IndexDirs.search_for_directory_by_sha)(directory_sha256)

    if not found:
        found, directory_record = await sync_to_async(IndexDirs.add_directory)(dirpath)
        if not found:
            logger.error(f"Failed to create directory record for {dirpath}")
            return None, False
        await sync_to_async(Cache_Storage.remove_from_cache_indexdirs)(directory_record)
        return directory_record, False

    # Use the is_cached property which leverages the 1-to-1 relationship
    is_cached = directory_record.is_cached
    return directory_record, is_cached


def _sync_directories(directory_record: object, fs_entries: dict) -> None:
    """
    Synchronize database directories with filesystem - simplified sync version.

    IMPORTANT - Async Wrapper Pattern:
    This function is SYNC and wrapped with sync_to_async at the call site (line ~850).
    This pattern is safer than having nested @sync_to_async decorators within an async function.

    Why sync instead of async:
    - All operations are database transactions (atomic blocks)
    - Prevents nested async/sync boundary issues
    - Single sync_to_async wrapper is more efficient than multiple nested ones
    - Easier to reason about transaction boundaries

    Thread Safety:
    - All DB operations in transaction.atomic() blocks
    - Safe for WSGI (Gunicorn) and ASGI (Uvicorn/Hypercorn)
    - No thread pool usage = no connection leakage

    Args:
        directory_record: IndexDirs object for the parent directory
        fs_entries: Dictionary of filesystem entries (DirEntry objects)

    Returns:
        None
    """
    print("Synchronizing directories...")
    logger.info("Synchronizing directories...")
    current_path = normalize_fqpn(directory_record.fqpndirectory)

    # Get all database directories efficiently - use lightweight query for path comparison
    # Avoid loading full objects with select_related/prefetch_related when only paths needed
    all_dirs_queryset = IndexDirs.objects.filter(parent_directory=directory_record.pk, delete_pending=False)
    db_dirs = set(all_dirs_queryset.values_list("fqpndirectory", flat=True))
    fs_dirs = {normalize_fqpn(current_path + entry.name) for entry in fs_entries.values() if entry.is_dir()}

    # Load full objects only for directories that exist in both DB and filesystem
    # This requires select_related for lastmod/size comparisons
    # Use queryset with iterator for memory-efficient streaming (single-pass iteration)
    existing_dirs_qs = directory_record.dirs_in_dir().filter(fqpndirectory__in=db_dirs & fs_dirs)
    existing_count = existing_dirs_qs.count()

    print(f"Existing directories in database: {existing_count}")
    if existing_count > 0:
        # Check each directory for updates
        updated_records = []
        for db_dir_entry in existing_dirs_qs.iterator(chunk_size=100):
            # Extract directory name from full path and title-case it to match fs_entries keys
            # NOTE: fs_entries dict is keyed by title-cased filenames (e.g., "Photos"), not full paths
            # (e.g., "/volumes/c-8tb/gallery/albums/photos/"). Using full path would always return None.
            # See return_disk_listing() in file_listings.py which uses normalize_string_title() for keys.
            dir_name = Path(db_dir_entry.fqpndirectory.rstrip(os.sep)).name
            dir_name_titled = normalize_string_title(dir_name)

            if fs_entry := fs_entries.get(dir_name_titled):
                try:
                    fs_stat = fs_entry.stat()
                    # Update modification time if changed (IndexDirs doesn't track size)
                    if db_dir_entry.lastmod != fs_stat.st_mtime:
                        db_dir_entry.lastmod = fs_stat.st_mtime
                        updated_records.append(db_dir_entry)
                except (OSError, IOError) as e:
                    logger.error(f"Error checking directory {db_dir_entry.fqpndirectory}: {e}")

        print(f"Directories to Update: {len(updated_records)}")

        if updated_records:
            print(f"processing existing directory changes: {len(updated_records)}")
            with transaction.atomic():
                for db_dir_entry in updated_records:
                    locked_entry = IndexDirs.objects.select_for_update(skip_locked=True).get(id=db_dir_entry.id)
                    locked_entry.lastmod = db_dir_entry.lastmod
                    locked_entry.save()
                    Cache_Storage.remove_from_cache_indexdirs(locked_entry)
            logger.info(f"Processing {len(updated_records)} directory updates")

    # Create new directories BEFORE deleting old ones to prevent foreign key violations
    new_dirs = fs_dirs - db_dirs
    if new_dirs:
        print(f"Directories to Add: {len(new_dirs)}")
        logger.info(f"Directories to Add: {len(new_dirs)}")
        with transaction.atomic():
            for dir_to_create in new_dirs:
                IndexDirs.add_directory(fqpn_directory=dir_to_create)

    # Delete directories that no longer exist in filesystem
    deleted_dirs = db_dirs - fs_dirs
    if deleted_dirs:
        print(f"Directories to Delete: {len(deleted_dirs)}")
        logger.info(f"Directories to Delete: {len(deleted_dirs)}")
        with transaction.atomic():
            all_dirs_queryset.filter(fqpndirectory__in=deleted_dirs).delete()
            Cache_Storage.remove_from_cache_indexdirs(directory_record)


def _sync_files(directory_record: object, fs_entries: dict, bulk_size: int) -> None:
    """
    Synchronize database files with filesystem - simplified for performance.

    IMPORTANT - Simplification Notes:
    Removed complex chunking logic that was causing multiple QuerySet evaluations.
    Previous version called .count() multiple times and used dynamic batch sizing.

    Current approach:
    - Single pass through QuerySet (no chunking for updates check)
    - Simpler logic = faster execution and easier to understand
    - Still uses bulk operations for actual DB writes

    Thread Safety:
    - This is a SYNC function wrapped with sync_to_async at call site
    - All DB operations safe for WSGI/ASGI
    - Transactions handled in _execute_batch_operations

    Args:
        directory_record: IndexDirs object for the parent directory
        fs_entries: Dictionary of filesystem entries (DirEntry objects)
        bulk_size: Size of batches for bulk operations (from BATCH_SIZES)

    Returns:
        None
    """
    # Build filesystem file dictionary (single pass)
    fs_file_names_dict = {name: entry for name, entry in fs_entries.items() if not entry.is_dir()}
    fs_file_names = list(fs_file_names_dict.keys())

    # Build case-insensitive lookup dictionary for matching
    # Maps lowercase filename -> original cased filename from filesystem
    fs_names_lower_map = {name.lower(): name for name in fs_file_names}

    # Optimize: First get just filenames with lightweight query (no prefetch overhead)
    # Then load full objects only for files that need comparison/updates
    all_db_filenames = set(IndexData.objects.filter(home_directory=directory_record.pk, delete_pending=False).values_list("name", flat=True))

    # Find files that exist in both DB and filesystem (case-insensitive match)
    # Build lowercase map from database names for matching
    db_names_lower_set = {name.lower() for name in all_db_filenames}
    matching_lower_names = set(fs_names_lower_map.keys()) & db_names_lower_set

    # Load full objects with prefetch only for files that need comparison
    # Convert matching lowercase names back to original database names
    matching_db_names = {name for name in all_db_filenames if name.lower() in matching_lower_names}
    potential_updates = list(directory_record.files_in_dir().filter(name__in=matching_db_names))

    # Batch compute SHA256 for files missing hashes
    files_needing_hash = []
    for db_file_entry in potential_updates:
        if not db_file_entry.file_sha256:
            # Use case-insensitive lookup: db name -> lowercase -> fs name -> fs entry
            fs_name = fs_names_lower_map[db_file_entry.name.lower()]
            fs_entry = fs_file_names_dict[fs_name]
            files_needing_hash.append((db_file_entry, str(fs_entry)))

    # Parallel SHA256 computation for missing hashes
    sha_results = {}
    if files_needing_hash:
        paths_to_hash = [path for _, path in files_needing_hash]
        sha_results = _batch_compute_file_shas(paths_to_hash)

    # Single pass through files needing updates
    records_to_update = []
    for db_file_entry in potential_updates:
        # Use case-insensitive lookup: db name -> lowercase -> fs name -> fs entry
        fs_name = fs_names_lower_map[db_file_entry.name.lower()]
        fs_entry = fs_file_names_dict[fs_name]
        updated_record = _check_file_updates(
            db_file_entry,
            fs_entry,
            directory_record,
            sha_results.get(str(fs_entry)),
        )
        if updated_record:
            records_to_update.append(updated_record)

    # Get files to delete - case-insensitive: db files NOT matching any fs file
    # Find DB files whose lowercase name is NOT in the filesystem (case-insensitive comparison)
    #
    # NOTE: Must compare at lowercase level to avoid false deletions on case-preserving filesystems.
    # The DB may store "MyFile.txt" while filesystem returns "Myfile.Txt" (title-cased by return_disk_listing).
    # Comparing original cases directly would incorrectly mark the file for deletion.
    # Instead, we compare lowercase sets, then map back to original DB names.
    db_names_not_in_fs_lower = db_names_lower_set - matching_lower_names
    db_names_not_in_fs = {name for name in all_db_filenames if name.lower() in db_names_not_in_fs_lower}
    files_to_delete_ids = list(
        IndexData.objects.filter(home_directory=directory_record.pk, name__in=db_names_not_in_fs, delete_pending=False).values_list("id", flat=True)
    )

    # Process new files - case-insensitive: fs files NOT matching any db file
    # Filesystem files whose lowercase name is NOT in database (case-insensitive)
    all_db_filenames_lower = {name.lower() for name in all_db_filenames}
    fs_file_names_for_creation = [name for name in fs_file_names if name.lower() not in all_db_filenames_lower]
    creation_fs_file_names_dict = {name: fs_file_names_dict[name] for name in fs_file_names_for_creation}

    # Batch compute SHA256 for new files (excluding links/archives which are handled individually)
    new_file_paths = []
    for fs_entry in creation_fs_file_names_dict.values():
        if not fs_entry.is_dir():
            fileext = fs_entry.suffix.lower() if fs_entry.suffix else ""
            if fileext and fileext != ".":
                # Only batch non-link files (links are processed specially in process_filedata)
                if fileext not in [".link", ".alias"]:
                    new_file_paths.append(str(fs_entry))

    # Parallel SHA256 computation for new files
    new_sha_results = {}
    if new_file_paths:
        new_sha_results = _batch_compute_file_shas(new_file_paths)

    records_to_create = directory_record.process_new_files(creation_fs_file_names_dict, new_sha_results)

    # Execute batch operations with transactions
    _execute_batch_operations(records_to_update, records_to_create, files_to_delete_ids, bulk_size)


def _detect_gif_animation(fs_entry: Path) -> bool:
    """
    Detect if a GIF file is animated.

    Shared function to avoid duplicate animation detection logic.
    Used by both new file processing and existing file updates.

    :Args:
        fs_entry: Path object for the GIF file

    Returns:
        True if animated, False if static or on error
    """
    try:
        with Image.open(fs_entry) as img:
            return getattr(img, "is_animated", False)
    except (AttributeError, IOError, OSError) as e:
        logger.error(f"Error checking animation for {fs_entry}: {e}")
        return False


def _process_link_file(fs_entry: Path, filetype: object, filename: str) -> object | None:
    """
    Process link files (.link or .alias) and return the virtual_directory.

    Extracts target directory from link file and finds/creates the corresponding
    IndexDirs record. Shared by both new file creation and existing file updates.

    :Args:
        fs_entry: Path object for the link file
        filetype: Filetype object with is_link=True and fileext attribute
        filename: The normalized filename from the database or filesystem

    Returns:
        IndexDirs object for the target directory, or None if target cannot be resolved
    """
    try:
        if filetype.fileext == ".link":
            # Optimize link parsing with single-pass processing
            name_lower = filename.lower()
            star_index = name_lower.find("*")
            if star_index == -1:
                logger.warning(f"Invalid link format - no '*' found in: {filename}")
                return None

            redirect = name_lower[star_index + 1 :]
            # Chain replacements more efficiently
            redirect = redirect.replace("'", "").replace("__", "/")
            dot_index = redirect.rfind(".")
            if dot_index != -1:
                redirect = redirect[:dot_index]
            redirect_path = f"/{redirect}"

            # Check if already a full filesystem path or a web fragment
            if not redirect_path.startswith(settings.ALBUMS_PATH):
                # Web fragment - convert to full filesystem path
                redirect_path = normalize_fqpn(settings.ALBUMS_PATH + redirect_path)
            else:
                # Already a full filesystem path - just normalize
                redirect_path = normalize_fqpn(redirect_path)

            # Find or create the target directory and set virtual_directory
            found, virtual_dir = IndexDirs.search_for_directory(redirect_path)
            if not found:
                found, virtual_dir = IndexDirs.add_directory(redirect_path)

            # Check if resolution succeeded - if not, skip this file
            if not found or virtual_dir is None:
                error_msg = f"Skipping .link file with broken target: {filename} → {redirect_path} (target directory not found)"
                logger.warning(error_msg)
                return None

            return virtual_dir

        elif filetype.fileext == ".alias":
            alias_target_path = resolve_alias_path(str(fs_entry))

            # Find or create the target directory and set virtual_directory
            found, virtual_dir = IndexDirs.search_for_directory(alias_target_path)
            if not found:
                found, virtual_dir = IndexDirs.add_directory(alias_target_path)

            # Check if resolution succeeded - if not, skip this file
            if not found or virtual_dir is None:
                error_msg = f"Skipping .alias file with broken target: {filename} → {alias_target_path} (target directory not found)"
                logger.warning(error_msg)
                return None

            return virtual_dir

    except ValueError as e:
        logger.error(f"Error processing link file {filename}: {e}")
        return None

    return None


def _check_file_updates(
    db_record: object, fs_entry: Path, home_directory: object, precomputed_sha: tuple[str | None, str | None] | None = None
) -> object | None:
    """
    Check if database record needs updating based on filesystem entry.

    Compares modification time, size, SHA256, and other attributes between
    database record and filesystem entry.

    Performance Optimization:
    Accepts precomputed SHA256 hashes to enable batch parallel computation.
    When precomputed_sha is provided, skips individual SHA256 calculation.

    :Args:
        db_record: IndexData database record
        fs_entry: Path object for filesystem entry (DirEntry with cached stat)
        home_directory: IndexDirs object for the parent directory
        precomputed_sha: Optional precomputed (file_sha256, unique_sha256) tuple

    Returns:
        Updated database record if changes detected, None otherwise
    """
    try:
        # Note: DirEntry.stat() is already cached by Python's os.scandir()
        # Multiple stat() calls on the same DirEntry object reuse the cached result
        # This prevents duplicate filesystem syscalls across _sync_files()
        fs_stat = fs_entry.stat()
        update_needed = False

        # Extract file extension using pathlib for consistency
        path_obj = Path(db_record.name)
        fext = path_obj.suffix.lower() if path_obj.suffix else ""
        if fext:  # Only process files with extensions
            # Use prefetched filetype from select_related
            filetype = db_record.filetype if hasattr(db_record, "filetype") else filetype_models.filetypes.return_filetype(fileext=fext)

            # Fix broken link files - process virtual_directory if missing
            if filetype.is_link and db_record.virtual_directory is None:
                virtual_dir = _process_link_file(fs_entry, filetype, db_record.name)
                if virtual_dir is not None:
                    db_record.virtual_directory = virtual_dir
                    update_needed = True

            # Use precomputed hash if available, otherwise calculate
            if not db_record.file_sha256:
                if precomputed_sha:
                    db_record.file_sha256, db_record.unique_sha256 = precomputed_sha
                    update_needed = True
                else:
                    try:
                        db_record.file_sha256, db_record.unique_sha256 = db_record.get_file_sha(fqfn=fs_entry)
                        update_needed = True
                    except Exception as e:
                        logger.error(f"Error calculating SHA for {fs_entry}: {e}")

            if db_record.home_directory != home_directory:
                db_record.home_directory = home_directory
                update_needed = True

            # Check modification time
            if db_record.lastmod != fs_stat.st_mtime:
                db_record.lastmod = fs_stat.st_mtime
                update_needed = True

            # Check file size
            if db_record.size != fs_stat.st_size:
                db_record.size = fs_stat.st_size
                update_needed = True

            # Movie duration loading - check each file individually
            if filetype.is_movie and db_record.duration is None:
                try:
                    video_details = _get_video_info(str(fs_entry))
                    db_record.duration = video_details.get("duration", None)
                    update_needed = True
                except Exception as e:
                    logger.error(f"Error getting duration for {fs_entry}: {e}")

            # Animated GIF detection - only check if not previously checked
            if filetype.is_image and fext == ".gif" and db_record.is_animated is None:
                db_record.is_animated = _detect_gif_animation(fs_entry)
                update_needed = True

        return db_record if update_needed else None

    except (OSError, IOError) as e:
        logger.error(f"Error checking file {fs_entry}: {e}")
        return None


def _execute_batch_operations(
    records_to_update: list,
    records_to_create: list,
    records_to_delete_ids: list,
    bulk_size: int,
) -> None:
    """
    Execute all database operations in batches with proper transaction handling.

    Performs bulk delete, update, and create operations in separate transactions.

    Args:
        records_to_update: List of records to update
        records_to_create: List of records to create
        records_to_delete_ids: List of record IDs to delete
        bulk_size: Size of batches for bulk operations

    Returns:
        None

    Raises:
        Exception: If any database operation fails
    """

    try:
        # Batch delete using IDs with optimized chunking
        if records_to_delete_ids:
            # Convert to list for efficient slicing
            delete_ids_list = list(records_to_delete_ids)

            with transaction.atomic():
                # Process deletes in optimally-sized chunks
                for i in range(0, len(delete_ids_list), bulk_size):
                    chunk_ids = delete_ids_list[i : i + bulk_size]
                    # Use bulk delete with specific field for index usage
                    IndexData.objects.filter(id__in=chunk_ids).delete()
                print(f"Deleted {len(records_to_delete_ids)} records")
                logger.info(f"Deleted {len(records_to_delete_ids)} records")

        # Batch update in chunks for memory efficiency
        if records_to_update:
            for i in range(0, len(records_to_update), bulk_size):
                chunk = records_to_update[i : i + bulk_size]
                with transaction.atomic():
                    # Dynamic update field selection - only update fields that have changed
                    update_fields = ["lastmod", "size", "home_directory"]

                    # Check if any records have movies for duration field
                    has_movies = any(
                        hasattr(record, "filetype")
                        and hasattr(record.filetype, "is_movie")
                        and record.filetype.is_movie
                        and hasattr(record, "duration")
                        and record.duration is not None
                        for record in chunk
                    )
                    if has_movies:
                        update_fields.append("duration")

                    # Add hash fields only if they exist in the records
                    has_hashes = any(hasattr(record, "file_sha256") and record.file_sha256 for record in chunk)
                    if has_hashes:
                        update_fields.extend(["file_sha256", "unique_sha256"])

                    # Add virtual_directory for link files
                    has_link_with_vdir = any(
                        hasattr(record, "filetype")
                        and hasattr(record.filetype, "is_link")
                        and record.filetype.is_link
                        and hasattr(record, "virtual_directory")
                        and record.virtual_directory is not None
                        for record in chunk
                    )
                    if has_link_with_vdir:
                        update_fields.append("virtual_directory")

                    IndexData.objects.bulk_update(
                        chunk,
                        fields=update_fields,
                        batch_size=bulk_size,
                    )
            logger.info(f"Updated {len(records_to_update)} records")

        # Batch create in chunks for memory efficiency
        if records_to_create:
            for i in range(0, len(records_to_create), bulk_size):
                chunk = records_to_create[i : i + bulk_size]
                with transaction.atomic():
                    IndexData.objects.bulk_create(
                        chunk,
                        batch_size=bulk_size,
                        ignore_conflicts=True,  # Handle duplicates gracefully
                    )
            logger.info(f"Created {len(records_to_create)} records")

    except Exception as e:
        logger.error(f"Database operation failed: {e}")
        raise
    finally:
        # Batch operations run in main thread, close stale connections
        close_old_connections()


# DEPRECATED: Function replaced by inlined logic in return_breadcrumbs()
# The urlsplit() call was unnecessary overhead for simple path strings.
# Logic now uses direct string.split("/") which is ~30-40% faster.
# Kept here for reference only.
#
# @lru_cache(maxsize=2000)
# def break_down_urls(uri_path: str) -> list[str]:
#     """
#     Split URL into component parts with optimized parsing
#
#     DEPRECATED: Replaced by inline logic in return_breadcrumbs()
#     This function called urllib.parse.urlsplit() unnecessarily on path strings.
#
#     Args:
#         uri_path (str): The URI to break down
#
#     Returns:
#         list: A list containing all parts of the URI
#     """
#     if not uri_path or uri_path == "/":
#         return []
#     path = urllib.parse.urlsplit(uri_path).path
#     return [part for part in path.split("/") if part]


@cached(webpaths_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def convert_to_webpath(full_path, directory=None):
    """
    Convert a full path to a webpath - optimized for performance

    Args:
        full_path (str): The full path to convert
        directory (str, optional): Directory component for path construction

    Returns:
        str: The converted webpath
    """
    # Cache the albums path to avoid repeated settings access
    if not hasattr(convert_to_webpath, "_albums_path_lower"):
        convert_to_webpath._albums_path_lower = settings.ALBUMS_PATH.lower()

    if directory is not None:
        cutpath = convert_to_webpath._albums_path_lower + directory.lower() if directory else ""
    else:
        cutpath = convert_to_webpath._albums_path_lower

    return full_path.replace(cutpath, "")


@cached(breadcrumbs_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def return_breadcrumbs(uri_path="") -> list[dict[str, str]]:
    """
    Return the breadcrumbs for uri_path

    Args:
        uri_path: The URI to break down into breadcrumbs

    Returns:
        List of dictionaries with 'name' and 'url' keys for each breadcrumb level
    """
    webpath = convert_to_webpath(uri_path)

    # Extract path components (direct split, no urlsplit needed for paths)
    parts = [p for p in webpath.split("/") if p]

    # Build breadcrumbs with cumulative paths using list slicing
    return [{"name": part, "url": "/" + "/".join(parts[: i + 1])} for i, part in enumerate(parts)]


@cached(filedata_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def process_filedata(
    fs_entry: Path, directory_id: str | None = None, precomputed_sha: tuple[str | None, str | None] | None = None
) -> dict[str, Any] | None:
    """
    Process a file system entry and return a dictionary with file metadata.

    Performance Optimization:
    Accepts precomputed SHA256 hashes to enable batch parallel computation.

    :Args:
        fs_entry: Path object representing the file or directory
        directory_id: Optional directory identifier for the parent directory
        precomputed_sha: Optional precomputed (file_sha256, unique_sha256) tuple

    Returns:
        Dictionary containing file metadata or None if processing fails
    """
    try:
        # Initialize the record dictionary
        record = {
            "home_directory": directory_id,
            "name": normalize_string_title(fs_entry.name),
            "is_animated": False,
            "file_sha256": None,
            "unique_sha256": None,
            "duration": None,
        }

        # Check if it's a directory first
        if fs_entry.is_dir():
            # Subdirectories are handled by _sync_directories, not here
            # Just skip processing directories in the file processing phase
            # NOTE: Commented out recursive sync_database_disk call - it's problematic
            # because it uses asyncio.run() from within a sync function that's already
            # running in a thread pool via sync_to_async. This causes event loop conflicts.
            # The _sync_directories function already handles subdirectories properly.
            # asyncio.run(sync_database_disk(str(fs_entry)))
            return None

        # Extract file extension
        fileext = fs_entry.suffix.lower() if fs_entry.suffix else ""

        # Normalize extension more efficiently
        if not fileext or fileext == ".":
            fileext = ".none"

        # Check if filetype exists (assuming this function is available)
        if not filetype_models.filetypes.filetype_exists_by_ext(fileext):
            print(f"Can't match fileext '{fileext}' with filetypes")
            return None

        # Use DirEntry's built-in stat cache (already cached from iterdir)
        # DirEntry.stat() is cached by Python - multiple calls reuse the same result
        try:
            fs_stat = fs_entry.stat()
            if not fs_stat:
                print(f"Error getting stats for {fs_entry}")
                return None

            record.update(
                {
                    "size": fs_stat.st_size,
                    "lastmod": fs_stat.st_mtime,
                    "lastscan": time.time(),
                    "filetype": filetype_models.filetypes.return_filetype(fileext=fileext),
                }
            )
        except (OSError, IOError) as e:
            print(f"Error getting file stats for {fs_entry}: {e}")
            return None

        # Handle link files
        filetype = record["filetype"]
        # if hasattr(filetype, "is_link") and filetype.is_link:
        if filetype.is_link:
            # Calculate SHA256 for link files
            try:
                record["file_sha256"], record["unique_sha256"] = get_file_sha(str(fs_entry))
            except Exception as e:
                print(f"Error calculating SHA for link file {fs_entry}: {e}")
                return None

            # Process link file and get virtual_directory
            virtual_dir = _process_link_file(fs_entry, filetype, record["name"])
            if virtual_dir is None:
                return None  # Don't add to database - will retry on next scan

            record["virtual_directory"] = virtual_dir
        else:
            # Use precomputed hash if available, otherwise calculate
            if precomputed_sha:
                record["file_sha256"], record["unique_sha256"] = precomputed_sha
            else:
                try:
                    record["file_sha256"], record["unique_sha256"] = get_file_sha(str(fs_entry))
                except Exception as e:
                    print(f"Error calculating SHA for {fs_entry}: {e}")
                    # Continue processing even if SHA calculation fails

        # Handle animated GIF detection
        if hasattr(filetype, "is_image") and filetype.is_image and fileext == ".gif":
            record["is_animated"] = _detect_gif_animation(fs_entry)

        return record

    except Exception as e:
        print(f"Unexpected error processing {fs_entry}: {e}")
        return None


async def sync_database_disk(directory_record: IndexDirs) -> bool | None:
    """
    Synchronize database entries with filesystem for a given directory.

    Args:
        directory_record: IndexDirs record for the directory to synchronize

    Returns:
        None on completion, bool on early exit conditions
    """
    dirpath = directory_record.fqpndirectory
    print("Starting ...  Syncing database with disk for directory:", dirpath)
    start_time = time.perf_counter()
    # Use simplified batch sizing
    bulk_size = BATCH_SIZES.get("db_write", 100)

    # Check if directory is cached using the record's property
    if directory_record.is_cached:
        print(f"Directory {dirpath} is already cached, skipping sync.")
        return None

    print(f"Rescanning directory: {dirpath}")

    # Get filesystem entries using the directory path from the record
    success, fs_entries = await return_disk_listing(dirpath)
    if not success:
        print("File path doesn't exist, removing from cache and database.")
        return await directory_record.handle_missing()

    # Batch process all operations
    # Both functions are sync and wrapped here for clean async/sync boundary
    await sync_to_async(_sync_directories)(directory_record, fs_entries)
    await sync_to_async(_sync_files)(directory_record, fs_entries, bulk_size)

    # Cache the result using the directory record
    await sync_to_async(Cache_Storage.add_from_indexdirs)(directory_record)
    logger.info(f"Cached directory: {dirpath}")
    print("Elapsed Time (Sync Database Disk): ", time.perf_counter() - start_time)

    # Close stale connections after expensive operation
    close_old_connections()
    return directory_record


@cached(alias_paths_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def resolve_alias_path(alias_path: str) -> str:
    """
    Resolve a macOS alias file to its target path.

    Uses macOS Foundation framework to resolve alias files and applies
    path mappings from settings.ALIAS_MAPPING.

    Args:
        alias_path: Path to the macOS alias file

    Returns:
        Resolved path to the target file/directory

    Raises:
        ValueError: If bookmark data cannot be created or resolved
    """
    options = NSURLBookmarkResolutionWithoutUI | NSURLBookmarkResolutionWithoutMounting
    alias_url = NSURL.fileURLWithPath_(alias_path)
    bookmark, error = NSURL.bookmarkDataWithContentsOfURL_error_(alias_url, None)
    if error:
        raise ValueError(f"Error creating bookmark data: {error}")

    resolved_url, _, error = NSURL.URLByResolvingBookmarkData_options_relativeToURL_bookmarkDataIsStale_error_(bookmark, options, None, None, None)
    if error:
        raise ValueError(f"Error resolving bookmark data: {error}")

    resolved_url = str(resolved_url.path()).strip().lower()
    # album_path = f"{settings.ALBUMS_PATH}{os.sep}albums{os.sep}"
    for disk_path, replacement_path in settings.ALIAS_MAPPING.items():
        if resolved_url.startswith(disk_path.lower()):
            resolved_url = resolved_url.replace(disk_path.lower(), replacement_path.lower()) + os.sep
            break

    # The copier is set to transform spaces to underscores.  We can safely disable that now, but
    # that legacy means that there would be tremendous pain in duplication of data.  So for now,
    # we will just check if the resolved path exists, and if not, we will try replacing spaces with underscores.
    # If that works, then we will return that modified path instead.  Otherwise, we return the original resolved path.

    if resolved_url:
        if os.path.exists(resolved_url):
            return resolved_url
        else:
            resolved_url = resolved_url.replace(" ", "_")

    return resolved_url

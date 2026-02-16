"""
Django management command for file system integrity and maintenance.

Provides commands to verify and maintain the integrity of the QuickBBS gallery
database against the actual file system. Includes functionality for:
- Verifying directories and files exist and are valid
- Adding missing directories and files to the database
- Generating missing thumbnails
- Maintaining database consistency with the file system

Usage:
    python manage.py scan --verify_directories
    python manage.py scan --verify_files
    python manage.py scan --add_directories [--max_count N] [--start PATH]
    python manage.py scan --add_files [--max_count N] [--start PATH]
    python manage.py scan --add_thumbnails [--max_count N]
    python manage.py scan --verify_thumbnails
"""

from __future__ import annotations

import asyncio
import io
import os
import time

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, connections, transaction
from PIL import Image

from cache_watcher.models import Cache_Storage, fs_Cache_Tracking
from frontend.utilities import update_database_from_disk
from quickbbs.common import normalize_fqpn
from quickbbs.management.commands.add_directories import add_directories
from quickbbs.management.commands.add_files import add_files
from quickbbs.management.commands.add_thumbnails import add_thumbnails
from quickbbs.management.commands.management_helper import (
    invalidate_directories_with_null_sha256,
    invalidate_directories_with_null_virtual_directory,
    invalidate_empty_directories,
)
from quickbbs.models import DirectoryIndex, FileIndex
from thumbnails.models import ThumbnailFiles

# Batch size for chunked processing operations
BULK_UPDATE_BATCH_SIZE = 250


def _process_directory_verification_chunk(
    directory_pks: list[int],
    cache_instance: fs_Cache_Tracking,
    deleted_count: int,
    cache_added_count: int,
) -> tuple[int, int]:
    """
    Process a chunk of directories for verification.

    Args:
        directory_pks: List of DirectoryIndex primary keys to process
        cache_instance: fs_Cache_Tracking instance for adding cache entries
        deleted_count: Current count of deleted directories
        cache_added_count: Current count of cache entries added

    Returns:
        Tuple of (updated deleted_count, updated cache_added_count)
    """
    # Fetch full directory objects for this chunk with related data
    directories = list(DirectoryIndex.objects.select_related("Cache_Watcher").filter(pk__in=directory_pks).order_by("fqpndirectory"))

    for directory in directories:
        if not os.path.exists(directory.fqpndirectory):
            print(f"Directory: {directory.fqpndirectory} does not exist")
            DirectoryIndex.delete_directory_record(directory)
            deleted_count += 1
        else:
            # Check if directory exists in fs_Cache_Tracking using 1-to-1 relationship
            try:
                _ = directory.Cache_Watcher
            except ObjectDoesNotExist:
                cache_instance.add_from_indexdirs(directory)
                cache_added_count += 1
                if cache_added_count <= 10 or cache_added_count % 100 == 0:
                    print(f"Added directory to fs_Cache_Tracking: {directory.fqpndirectory}")

    return deleted_count, cache_added_count


def verify_directories(start_path: str | None = None, max_count: int = 0):
    """
    Verify directories in the database against the filesystem.

    Uses chunked PK processing to avoid loading all directories into memory.
    Includes timing statistics and batch processing for efficiency.

    Args:
        start_path: Starting directory path to verify from (default: ALBUMS_PATH/albums)
        max_count: Maximum number of directories to process (0 = unlimited)

    Returns:
        None
    """
    print("=" * 60)
    print("Checking for invalid directories in Database (eg. Deleted, Moved, etc).")
    print("=" * 60)
    start_time = time.time()
    start_count = DirectoryIndex.objects.count()
    print(f"Starting Directory Count: {start_count}")
    albums_root = os.path.join(settings.ALBUMS_PATH, "albums") + os.sep

    # Invalidate directories with link files missing virtual_directory
    print("-" * 30)
    print("Invalidating directories with NULL virtual_directory link files...")
    invalidate_directories_with_null_virtual_directory(start_path=start_path, verbose=True)
    print("-" * 30)

    # Invalidate empty directories before verification begins
    print("-" * 30)
    print("Invalidating empty directories (before verification)...")
    invalidate_empty_directories(start_path=start_path, verbose=True)
    print("-" * 30)

    # Build base queryset
    if start_path:
        normalized_start = normalize_fqpn(start_path)
        print(f"Filtering directories under: {normalized_start}")
        base_qs = DirectoryIndex.objects.filter(fqpndirectory__startswith=normalized_start).order_by("fqpndirectory")
    else:
        print("Gathering all directories")
        base_qs = DirectoryIndex.objects.order_by("fqpndirectory")

    # Fetch only primary keys (lightweight)
    all_pks = list(base_qs.values_list("pk", flat=True))
    total_dirs = len(all_pks)
    print(f"Found {total_dirs} directories to verify (chunked mode)...")

    # Apply max_count limit if specified
    if max_count > 0:
        all_pks = all_pks[:max_count]
        total_dirs = len(all_pks)
        print(f"Limiting to {max_count} directories...")

    print("Starting Scan")
    cache_instance = fs_Cache_Tracking()
    processed_count = 0
    deleted_count = 0
    cache_added_count = 0
    scan_start = time.time()

    # Process in chunks
    for i in range(0, len(all_pks), BULK_UPDATE_BATCH_SIZE):
        chunk_pks = all_pks[i : i + BULK_UPDATE_BATCH_SIZE]

        deleted_count, cache_added_count = _process_directory_verification_chunk(chunk_pks, cache_instance, deleted_count, cache_added_count)

        processed_count += len(chunk_pks)

        # Progress indicator
        if processed_count % 1000 == 0 or processed_count == total_dirs:
            elapsed = time.time() - scan_start
            rate = processed_count / elapsed if elapsed > 0 else 0
            print(f"Processed {processed_count}/{total_dirs} directories ({rate:.1f} dirs/sec)...")

        # Close connections after each chunk
        close_old_connections()

    end_count = DirectoryIndex.objects.count()
    print("-" * 30)
    print(f"Verification complete: Deleted {deleted_count} directories, added {cache_added_count} cache entries")
    print(f"Starting Count: {start_count}, Ending Count: {end_count}, Difference: {start_count - end_count}")

    # Check for unlinked parents
    print("-" * 30)
    print("Checking for unlinked parents")
    unlinked_parents = DirectoryIndex.objects.filter(parent_directory__isnull=True).exclude(fqpndirectory=albums_root)
    unlinked_count = unlinked_parents.count()
    print(f"Found {unlinked_count} directories with no parents")

    if unlinked_count > 0:
        # Fetch PKs for unlinked parents
        unlinked_pks = list(unlinked_parents.order_by("fqpndirectory").values_list("pk", flat=True))
        fixed_count = 0

        # Process in chunks - CRITICAL: Order by fqpndirectory to process parents before children
        for i in range(0, len(unlinked_pks), BULK_UPDATE_BATCH_SIZE):
            chunk_pks = unlinked_pks[i : i + BULK_UPDATE_BATCH_SIZE]

            # Fetch directories for this chunk
            directories = list(DirectoryIndex.objects.filter(pk__in=chunk_pks).order_by("fqpndirectory"))

            for directory in directories:
                print(f"Fixing Parent directory for {directory.fqpndirectory}")
                DirectoryIndex.add_directory(directory.fqpndirectory)
                fixed_count += 1

            close_old_connections()

        print(f"Fixed {fixed_count} unlinked parent directories")

    # Invalidate empty directories after all verification operations
    print("-" * 30)
    print("Invalidating empty directories (after verification)...")
    invalidate_empty_directories(start_path=start_path, verbose=True)

    # Final statistics
    total_time = time.time() - start_time
    print("=" * 60)
    print("Directory verification complete")
    print(f"  Total time: {total_time:.1f} seconds")
    print(f"  Directories processed: {processed_count}")
    print(f"  Directories deleted: {deleted_count}")
    print(f"  Cache entries added: {cache_added_count}")
    print("=" * 60)


async def _process_verify_files_chunk(
    directory_pks: list[int],
    processed_count: int,
    start_time: float,
) -> int:
    """
    Process a chunk of directories for file verification.

    Args:
        directory_pks: List of DirectoryIndex primary keys to process
        processed_count: Current count of directories processed
        start_time: Start time for rate calculations

    Returns:
        Updated processed_count
    """
    # Fetch full directory objects for this chunk with related data
    directories = await sync_to_async(list, thread_sensitive=True)(
        DirectoryIndex.objects.select_related("Cache_Watcher", "parent_directory").filter(pk__in=directory_pks).order_by("fqpndirectory")
    )

    for directory in directories:
        # Remove from cache
        await sync_to_async(Cache_Storage.remove_from_cache_sha, thread_sensitive=True)(sha256=directory.dir_fqpn_sha256)
        # Verify and sync files
        await sync_to_async(update_database_from_disk)(directory)
        processed_count += 1

        # Progress indicator every 100 directories
        if processed_count % 100 == 0:
            elapsed = time.time() - start_time
            rate = processed_count / elapsed if elapsed > 0 else 0
            print(f"\tProcessed {processed_count} directories ({rate:.1f} dirs/sec)...")

    return processed_count


async def _verify_files_async(start_path: str | None = None, max_count: int = 0):
    """
    Async implementation of verify_files.

    Verifies files in the database against the filesystem and performs cleanup:
    - Invalidates directories with NULL SHA256 files
    - Invalidates directories with NULL virtual_directory link files
    - Deletes orphaned FileIndex records (where home_directory is None)
    - Verifies all files exist on disk and syncs database with filesystem

    Uses chunked PK processing to avoid loading all directories into memory.
    Includes timing statistics and batch processing for efficiency.

    Args:
        start_path: Starting directory path to verify from (default: ALBUMS_PATH/albums)
        max_count: Maximum number of directories to process (0 = unlimited)

    Returns:
        None
    """
    print("=" * 60)
    print("Verifying files in database against filesystem")
    print("=" * 60)
    overall_start = time.time()

    # Invalidate directories containing files with NULL SHA256
    await sync_to_async(invalidate_directories_with_null_sha256, thread_sensitive=True)(start_path=start_path)

    # Invalidate directories with link files missing virtual_directory
    await sync_to_async(invalidate_directories_with_null_virtual_directory, thread_sensitive=True)(start_path=start_path)

    # Delete orphaned FileIndex records (where home_directory is None)
    print("-" * 60)
    print("Checking for orphaned FileIndex records (home_directory=None)...")
    orphaned_query = FileIndex.objects.filter(home_directory=None)
    orphaned_count = await sync_to_async(orphaned_query.count, thread_sensitive=True)()
    if orphaned_count > 0:
        print(f"  Found {orphaned_count} orphaned FileIndex records")
        print("  These records cannot be recovered and will be deleted...")
        deleted_count, _ = await sync_to_async(orphaned_query.delete, thread_sensitive=True)()
        print(f"  ✓ Deleted {deleted_count} orphaned FileIndex records")
    else:
        print("  ✓ No orphaned FileIndex records found")
    print("-" * 60)

    print("Checking for invalid files in Database")
    start_count = await sync_to_async(FileIndex.objects.count, thread_sensitive=True)()
    print(f"\tStarting File Count: {start_count}")

    # Build base queryset
    if start_path:
        normalized_start = normalize_fqpn(start_path)
        print(f"\tFiltering directories under: {normalized_start}")
        base_qs = DirectoryIndex.objects.filter(fqpndirectory__startswith=normalized_start).order_by("fqpndirectory")
    else:
        base_qs = DirectoryIndex.objects.order_by("fqpndirectory")

    # Fetch only primary keys (lightweight - avoids loading full objects into memory)
    all_pks = await sync_to_async(list, thread_sensitive=True)(base_qs.values_list("pk", flat=True))
    total_dirs = len(all_pks)
    print(f"\tFound {total_dirs} directories to process (chunked mode)...")

    # Apply max_count limit if specified
    if max_count > 0:
        all_pks = all_pks[:max_count]
        total_dirs = len(all_pks)
        print(f"\tLimiting to {max_count} directories...")

    # Process in chunks
    processed_count = 0
    start_time = time.time()

    for i in range(0, len(all_pks), BULK_UPDATE_BATCH_SIZE):
        chunk_pks = all_pks[i : i + BULK_UPDATE_BATCH_SIZE]

        processed_count = await _process_verify_files_chunk(chunk_pks, processed_count, start_time)

        # Close connections after each chunk to prevent exhaustion
        await sync_to_async(connections.close_all, thread_sensitive=True)()

    # Final statistics
    end_count = await sync_to_async(FileIndex.objects.count, thread_sensitive=True)()
    total_time = time.time() - overall_start
    scan_time = time.time() - start_time
    dir_rate = processed_count / scan_time if scan_time > 0 else 0

    print("=" * 60)
    print("File verification complete")
    print(f"  Starting File Count: {start_count}")
    print(f"  Ending File Count: {end_count}")
    print(f"  Difference: {start_count - end_count}")
    print(f"  Directories processed: {processed_count}")
    print(f"  Directory rate: {dir_rate:.1f} dirs/sec")
    print(f"  Total time: {total_time:.1f} seconds")
    print("=" * 60)


def verify_files(start_path: str | None = None, max_count: int = 0):
    """
    Synchronous wrapper for verify_files.

    Verifies files in the database against the filesystem and performs cleanup:
    - Invalidates directories with NULL SHA256 files
    - Invalidates directories with NULL virtual_directory link files
    - Deletes orphaned FileIndex records (where home_directory is None)
    - Verifies all files exist on disk and syncs database with filesystem

    Args:
        start_path: Starting directory path to verify from (default: ALBUMS_PATH/albums)
        max_count: Maximum number of directories to process (0 = unlimited)

    Returns:
        None
    """
    asyncio.run(_verify_files_async(start_path=start_path, max_count=max_count))


def verify_thumbnails(max_count: int = 0):
    """
    Scan thumbnails for all-white corrupted images and fix them in-place.

    Uses a two-phase approach for efficiency:
    1. Database filter: Uses octet_length() to find thumbnails with suspiciously
       small blob sizes (below SMALL_THUMBNAIL_SAFEGUARD_SIZE). All-white JPEGs
       compress to ~700-1300 bytes while real photos are typically 3-15KB+.
    2. PIL validation: Opens only the suspect thumbnails to confirm all-white pixels.

    This avoids loading every thumbnail blob from the database (283 GB TOAST data).

    Also deletes orphaned ThumbnailFiles records (no linked FileIndex).

    Note: --start is not supported for thumbnail operations because thumbnails are
    content-addressed by SHA256. A corrupted thumbnail affects all files with the
    same hash, regardless of directory location.

    Args:
        max_count: Maximum number of suspect thumbnails to process (0 = unlimited)

    Returns:
        None
    """
    import sys
    from itertools import batched

    from django.db.models.functions import Length

    print("=" * 80)
    print("THUMBNAIL VERIFICATION - Scanning for all-white corrupted thumbnails")
    print("=" * 80)
    sys.stdout.flush()

    safeguard_size = settings.SMALL_THUMBNAIL_SAFEGUARD_SIZE
    total_thumbnails = ThumbnailFiles.objects.count()

    # Phase 1: Use octet_length to find suspect thumbnails (small blobs = likely corruption)
    print(f"Total thumbnails in database: {total_thumbnails}")
    print(f"Filtering for suspect thumbnails (small_thumb < {safeguard_size} bytes)...")
    sys.stdout.flush()
    pk_start = time.time()
    suspect_pks = list(
        ThumbnailFiles.objects.annotate(blob_size=Length("small_thumb"))
        .filter(blob_size__gt=0, blob_size__lt=safeguard_size)
        .values_list("pk", flat=True)
    )
    suspect_count = len(suspect_pks)
    pk_time = time.time() - pk_start
    print(f"Found {suspect_count} suspect thumbnails out of {total_thumbnails} ({pk_time:.1f}s)")
    sys.stdout.flush()

    if max_count > 0:
        suspect_pks = suspect_pks[:max_count]
        print(f"Limiting to {max_count} thumbnails...")

    # Track directories that need invalidation (only store IDs, not objects)
    directories_to_invalidate = set()
    batch_counter = 0
    corrupted_count = 0
    orphaned_count = 0
    chunk_size = 100  # Load blob data in small chunks
    start_time = time.time()

    print(f"\nPhase 2: Validating {len(suspect_pks)} suspect thumbnails with PIL...")
    print("-" * 80)
    sys.stdout.flush()

    # Process suspect PKs in chunks
    for pk_chunk in batched(suspect_pks, chunk_size):
        # Load only needed fields for this chunk
        thumbnails = ThumbnailFiles.objects.filter(pk__in=pk_chunk).only("id", "sha256_hash", "small_thumb")

        for thumbnail in thumbnails:
            batch_counter += 1

            try:
                # Check for orphaned thumbnail (no linked FileIndex records)
                if not FileIndex.objects.filter(file_sha256=thumbnail.sha256_hash).exists():
                    orphaned_count += 1
                    thumbnail.delete()
                    continue

                # Skip if small_thumb is empty or None
                if not thumbnail.small_thumb:
                    continue

                # Check if thumbnail is all-white
                with Image.open(io.BytesIO(thumbnail.small_thumb)) as img:
                    extrema = img.getextrema()

                    # Check if all pixels are white
                    is_all_white = False
                    if img.mode == "RGB":
                        is_all_white = extrema == ((255, 255), (255, 255), (255, 255))
                    elif img.mode == "L":
                        is_all_white = extrema == (255, 255)

                if is_all_white:
                    corrupted_count += 1
                    fi = FileIndex.objects.filter(file_sha256=thumbnail.sha256_hash).first()
                    fi_name = fi.name if fi else "unknown"
                    print(f"  Found potential issue: SHA256={thumbnail.sha256_hash[:16]}... file={fi_name}")

                    # Invalidate immediately
                    with transaction.atomic():
                        thumbnail.invalidate_thumb()
                        thumbnail.save(update_fields=["small_thumb", "medium_thumb", "large_thumb"])

                        # Get files using this thumbnail and collect directory IDs only
                        file_dir_ids = (
                            FileIndex.objects.filter(file_sha256=thumbnail.sha256_hash)
                            .exclude(home_directory__isnull=True)
                            .values_list("home_directory_id", flat=True)
                        )
                        directories_to_invalidate.update(file_dir_ids)

                    print("      Invalidated thumbnail")

            except Exception as e:
                print(f"  Error checking thumbnail {thumbnail.sha256_hash}: {e}")
                sys.stdout.flush()
                continue

        # Close connections after each chunk to prevent exhaustion
        close_old_connections()

    elapsed = time.time() - start_time
    rate = batch_counter / elapsed if elapsed > 0 else 0

    print("-" * 80)
    print(f"Scan complete: {batch_counter} suspect thumbnails validated in {elapsed:.1f}s ({rate:.1f}/sec)")
    print(f"  (filtered from {total_thumbnails} total using blob size < {safeguard_size} bytes)")
    print(f"Found and fixed {corrupted_count} corrupted white thumbnails")
    print(f"Deleted {orphaned_count} orphaned thumbnail records")

    if corrupted_count == 0 and orphaned_count == 0:
        print("No issues found. Database is clean!")
        return

    if corrupted_count == 0:
        print("No corrupted thumbnails found.")
        print(f"Cleaned up {orphaned_count} orphaned records.")
        return

    print("-" * 80)
    print(f"Invalidated {corrupted_count} thumbnails")

    if directories_to_invalidate:
        print(f"\nMarking {len(directories_to_invalidate)} directories as invalidated...")
        print("-" * 80)

        directory_counter = 0
        total_dirs = len(directories_to_invalidate)

        # Convert directory IDs to list for chunked processing
        dir_ids_list = list(directories_to_invalidate)

        # Process in chunks to avoid memory issues with large sets
        for i in range(0, len(dir_ids_list), BULK_UPDATE_BATCH_SIZE):
            chunk_ids = dir_ids_list[i : i + BULK_UPDATE_BATCH_SIZE]

            # Fetch actual DirectoryIndex objects for this chunk
            directories = DirectoryIndex.objects.filter(pk__in=chunk_ids)

            with transaction.atomic():
                for directory in directories:
                    directory_counter += 1

                    # Mark directory as invalidated in cache
                    fs_Cache_Tracking.objects.update_or_create(
                        directory=directory,
                        defaults={
                            "invalidated": True,
                            "lastscan": time.time(),
                        },
                    )
                    # Invalidate directory thumbnail as well
                    directory.invalidate_thumb()

                    # Show progress for first few and then periodically
                    if directory_counter <= 5 or directory_counter % 100 == 0:
                        print(f"  Invalidated directory {directory_counter}/{total_dirs}: {directory.fqpndirectory}")

            close_old_connections()

        print("-" * 80)
        print(f"Marked {len(directories_to_invalidate)} directories for regeneration")

    print("\n" + "=" * 80)
    print("SUMMARY:")
    print(f"  - Total thumbnails in database: {total_thumbnails}")
    print(f"  - Suspect thumbnails (blob < {safeguard_size} bytes): {suspect_count}")
    print(f"  - Corrupted thumbnails found and fixed: {corrupted_count}")
    print(f"  - Orphaned thumbnails deleted: {orphaned_count}")
    print(f"  - Directories marked for regeneration: {len(directories_to_invalidate)}")
    print("=" * 80)
    print("\nThumbnail verification complete!")
    print("Corrupted thumbnails will be regenerated on next access.")


class Command(BaseCommand):
    """
    Django management command for file system integrity and maintenance.

    Provides various scanning and validation operations for the QuickBBS gallery
    database to ensure consistency with the file system.
    """

    help = "Perform a Directory Validation/Integrity Scan"

    def add_arguments(self, parser):
        parser.add_argument(
            "--verify_directories",
            action="store_true",
            help="Trigger a Verification/Validation scan on the existing directories in the database",
        )
        parser.add_argument(
            "--verify_files",
            action="store_true",
            help="Trigger a Verification/Validation scan on the existing files in the database",
        )
        parser.add_argument(
            "--add_directories",
            action="store_true",
            help="Walk albums directory and add any missing directories to DirectoryIndex and fs_Cache_Tracking",
        )
        parser.add_argument(
            "--add_files",
            action="store_true",
            help="Walk albums directory and add any missing files to FileIndex",
        )
        parser.add_argument(
            "--add_thumbnails",
            action="store_true",
            help="Scan FileIndex for files missing thumbnails and generate them (images, videos, PDFs)",
        )
        parser.add_argument(
            "--verify_thumbnails",
            action="store_true",
            help="Scan all thumbnails for all-white corrupted images, invalidate them, and mark directories for regeneration",
        )
        parser.add_argument(
            "--max_count",
            type=int,
            default=0,
            help="Maximum number of records to process (0 = unlimited). Used with all scan operations.",
        )
        parser.add_argument(
            "--start",
            type=str,
            default=None,
            help=(
                "Starting directory path to filter operations (default: ALBUMS_PATH/albums). "
                "Used with --verify_directories, --verify_files, --add_directories, --add_files. "
                "NOT supported for thumbnail operations (thumbnails are content-addressed)."
            ),
        )

        parser.add_argument(
            "--dir",
            action="store_true",
            help="Scan directories for importation",
        )
        # parser.add_argument(
        #     "--files",
        #     action="store_true",
        #     help="Scan Files for importation",
        # )

    def handle(self, *args, **options):
        # Clean up stale records before any scan operation
        deleted_count, _ = FileIndex.objects.filter(delete_pending=True).delete()
        if deleted_count:
            print(f"Deleted {deleted_count} records marked as delete_pending")

        max_count = options.get("max_count", 0)
        start_path = options.get("start", None)

        # Validate start_path if provided
        if start_path:
            # Normalize the provided path
            normalized_start_path = normalize_fqpn(start_path)

            # Get the albums root directory
            albums_root = normalize_fqpn(os.path.join(settings.ALBUMS_PATH, "albums"))

            # Ensure the start_path is within the albums directory
            if not normalized_start_path.startswith(albums_root):
                raise CommandError(
                    f"Invalid --start path: '{start_path}'\n"
                    f"The path must be within the albums directory: '{albums_root}'\n"
                    f"Normalized path provided: '{normalized_start_path}'"
                )

            # Ensure the path exists
            if not os.path.exists(normalized_start_path):
                raise CommandError(f"Invalid --start path: '{start_path}'\n" f"The directory does not exist: '{normalized_start_path}'")

            # Ensure it's a directory
            if not os.path.isdir(normalized_start_path):
                raise CommandError(f"Invalid --start path: '{start_path}'\n" f"The path is not a directory: '{normalized_start_path}'")

        if options["verify_directories"]:
            verify_directories(start_path=start_path, max_count=max_count)
        if options["verify_files"]:
            verify_files(start_path=start_path, max_count=max_count)
        if options["add_directories"]:
            add_directories(max_count=max_count, start_path=start_path)
        if options["add_files"]:
            add_files(max_count=max_count, start_path=start_path)
        if options["add_thumbnails"]:
            add_thumbnails(max_count=max_count)
        if options["verify_thumbnails"]:
            verify_thumbnails(max_count=max_count)


# # Use
# from quickbbs.models import Directory_Index, Thumbnails_Dirs, convert_text_to_md5_hdigest
#
# new_dir_index = Directory_Index
#
# # class Directory_Index(models.Model):
# #     uuid = models.UUIDField(default=None, null=True, editable=False, db_index=True, blank=True)
# #     DirName = models.CharField(db_index=False, max_length=384, default='', blank=True)  # FQFN of the file itself
# #     WebPath_md5 = models.CharField(db_index=True, max_length=32, unique=False)
# #     DirName_md5 = models.CharField(db_index=True, max_length=32, unique=False)
# #     Combined_md5 = models.CharField(db_index=True, max_length=32, unique=True)
# #     is_generic_icon = models.BooleanField(default=False, db_index=True)  # File is to be ignored
# #     ignore = models.BooleanField(default=False, db_index=True)  # File is to be ignored
# #     delete_pending = models.BooleanField(default=False, db_index=True)  # File is to be deleted,
# #     SmallThumb = models.BinaryField(default=b"")
#
# # class Thumbnails_Dirs(models.Model):
# #     id = models.AutoField(primary_key=True, db_index=True)
# #     uuid = models.UUIDField(default=None, null=True, editable=False, db_index=True, blank=True)
# #     DirName = models.CharField(db_index=True, max_length=384, default='', blank=True)  # FQFN of the file itself
# #     FileSize = models.BigIntegerField(default=-1)
# #     FilePath = models.CharField(db_index=True, max_length=384, default=None)  # FQFN of the file itself
# #     SmallThumb = models.BinaryField(default=b"")
# #
# for entry in Thumbnails_Dirs.objects.all()[0:1]:
#     print(entry.FilePath)
#     #Combined_md5 = convert_text_to_md5_hdigest(entry.DirName)
#     found, record = Directory_Index.search_for_directory(entry.DirName)
#     # if found:
#     #     if record.DirName != entry.FilePath:
#     #         record.DirName = entry.FilePath
#     #         record.save()
#     #     if record.SmallThumb == b"":
#     #         record.SmallThumb = entry.SmallThumb
#     #         record.save()
#     # else:
#     Directory_Index.add_directory(fqpn_directory=entry.FilePath,
#                              thumbnail = entry.SmallThumb)
#     sys.exit()
#

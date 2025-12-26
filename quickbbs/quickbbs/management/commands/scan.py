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


def verify_directories(start_path: str | None = None):
    """
    Verify directories in the database against the filesystem.

    Args:
        start_path: Starting directory path to verify from (default: ALBUMS_PATH/albums)

    Returns:
        None
    """
    print("Checking for invalid directories in Database (eg. Deleted, Moved, etc).")
    start_count = DirectoryIndex.objects.count()
    print("Starting Directory Count: ", start_count)
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

    # Filter directories to only those under start_path if specified
    if start_path:
        normalized_start = normalize_fqpn(start_path)
        print(f"Filtering directories under: {normalized_start}")
        directories_to_scan = (
            DirectoryIndex.objects.select_related("Cache_Watcher")
            .filter(fqpndirectory__startswith=normalized_start)
            .order_by("fqpndirectory")
            .iterator(chunk_size=1000)
        )
    else:
        print("Gathering Directories")
        # Prefetch Cache_Watcher relationship to avoid N+1 queries
        directories_to_scan = DirectoryIndex.objects.select_related("Cache_Watcher").order_by("fqpndirectory").all().iterator(chunk_size=1000)

    print("Starting Scan")

    # Process directories WITHOUT closing connections during iteration
    # Server-side cursors don't survive close_old_connections()
    batch_counter = 0
    cache_instance = fs_Cache_Tracking()

    for directory in directories_to_scan:
        if not os.path.exists(directory.fqpndirectory):
            print(f"Directory: {directory.fqpndirectory} does not exist")
            DirectoryIndex.delete_directory_record(directory)
        else:
            # Check if directory exists in fs_Cache_Tracking using 1-to-1 relationship
            try:
                _ = directory.Cache_Watcher
            except ObjectDoesNotExist:
                cache_instance.add_from_indexdirs(directory)
                print(f"Added directory to fs_Cache_Tracking: {directory.fqpndirectory}")

        batch_counter += 1
        if batch_counter % 1000 == 0:
            print(f"Processed {batch_counter} directories...")

    # Only close connections AFTER iteration is complete
    close_old_connections()

    end_count = DirectoryIndex.objects.count()
    print("Ending Count: ", end_count)
    print("Difference : ", start_count - end_count)
    print("-" * 30)
    print("Checking for unlinked parents")
    unlinked_parents = DirectoryIndex.objects.filter(parent_directory__isnull=True).exclude(fqpndirectory=albums_root)
    # exclude the albums_root, since that is suppose to have no parent.  You can't tranverse below the albums_root
    print(f"Found {unlinked_parents.count()} directories with no parents")

    # CRITICAL: Order by fqpndirectory to process parent directories before children
    # Shallower paths (fewer separators) naturally sort before deeper paths
    batch_counter = 0
    for directory in unlinked_parents.order_by("fqpndirectory").iterator(chunk_size=1000):
        print(f"Fixing Parent directory for {directory.fqpndirectory}")
        DirectoryIndex.add_directory(directory.fqpndirectory)

        batch_counter += 1
        if batch_counter % 1000 == 0:
            print(f"Processed {batch_counter} unlinked parents...")

    # Close connections after second iteration is complete
    close_old_connections()

    # Invalidate empty directories after all verification operations
    print("-" * 30)
    print("Invalidating empty directories (after verification)...")
    invalidate_empty_directories(start_path=start_path, verbose=True)
    print("-" * 30)


async def _verify_files_async(start_path: str | None = None):
    """
    Async implementation of verify_files.

    Verifies files in the database against the filesystem and performs cleanup:
    - Invalidates directories with NULL SHA256 files
    - Invalidates directories with NULL virtual_directory link files
    - Deletes orphaned FileIndex records (where home_directory is None)
    - Verifies all files exist on disk and syncs database with filesystem

    Args:
        start_path: Starting directory path to verify from (default: ALBUMS_PATH/albums)

    Returns:
        None
    """
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
    print("\tStarting File Count: ", start_count)

    # Process directories in batches with connection cleanup
    batch_counter = 0
    cleanup_interval = 25  # Close connections every 25 directories

    # Fetch all directories first with Cache_Watcher prefetched
    # This prevents sync DB queries when accessing is_cached property
    # Filter directories to only those under start_path if specified
    if start_path:
        normalized_start = normalize_fqpn(start_path)
        print(f"\tFiltering directories under: {normalized_start}")
        directories = await sync_to_async(list, thread_sensitive=True)(
            DirectoryIndex.objects.select_related("Cache_Watcher", "parent_directory")
            .filter(fqpndirectory__startswith=normalized_start)
            .order_by("fqpndirectory")
            .all()
        )
    else:
        directories = await sync_to_async(list, thread_sensitive=True)(
            DirectoryIndex.objects.select_related("Cache_Watcher", "parent_directory").order_by("fqpndirectory").all()
        )

    for directory in directories:
        await sync_to_async(Cache_Storage.remove_from_cache_sha, thread_sensitive=True)(sha256=directory.dir_fqpn_sha256)
        await update_database_from_disk(directory)

        # Periodic connection cleanup to prevent exhaustion
        batch_counter += 1
        if batch_counter % cleanup_interval == 0:
            # Close connections in async context
            await sync_to_async(connections.close_all, thread_sensitive=True)()
            print(f"\tProcessed {batch_counter} directories...")

    # Final cleanup
    await sync_to_async(connections.close_all, thread_sensitive=True)()

    end_count = await sync_to_async(FileIndex.objects.count, thread_sensitive=True)()
    print("\tStarting File Count: ", start_count)
    print("\tEnding Count: ", end_count)
    print("\tDifference : ", start_count - end_count)


def verify_files(start_path: str | None = None):
    """
    Synchronous wrapper for verify_files.

    Verifies files in the database against the filesystem and performs cleanup:
    - Invalidates directories with NULL SHA256 files
    - Invalidates directories with NULL virtual_directory link files
    - Deletes orphaned FileIndex records (where home_directory is None)
    - Verifies all files exist on disk and syncs database with filesystem

    Args:
        start_path: Starting directory path to verify from (default: ALBUMS_PATH/albums)

    Returns:
        None
    """
    asyncio.run(_verify_files_async(start_path=start_path))


def verify_thumbnails():
    """
    Scan all thumbnails for all-white corrupted images and fix them in-place.

    This function:
    1. Iterates through ThumbnailFiles records checking for all-white pixel data
    2. Immediately invalidates corrupted thumbnails (sets to b"") as they're found
    3. Collects directory IDs (not objects) to minimize memory usage
    4. Marks parent directories as invalidated in fs_Cache_Tracking
    5. Ensures thumbnails will be regenerated on next access

    Memory efficient: Processes thumbnails in batches, fixes in-place, stores only directory IDs.

    Returns:
        None
    """
    print("=" * 80)
    print("THUMBNAIL VERIFICATION - Scanning for all-white corrupted thumbnails")
    print("=" * 80)

    # Get count for progress reporting
    print("\nCounting thumbnails to check...")
    total_thumbnails = ThumbnailFiles.objects.filter(small_thumb__isnull=False).exclude(small_thumb=b"").count()
    print(f"Found {total_thumbnails} thumbnails to check")

    # Track directories that need invalidation (only store IDs, not objects)
    directories_to_invalidate = set()
    batch_counter = 0
    corrupted_count = 0
    progress_interval = 1000  # Report progress every 1000 thumbnails

    print("\nScanning and fixing thumbnails in-place...")
    print("-" * 80)

    # Process thumbnails with iterator to avoid loading all into memory
    thumbnails = ThumbnailFiles.objects.filter(small_thumb__isnull=False).exclude(small_thumb=b"").select_related()

    for thumbnail in thumbnails.iterator(chunk_size=1000):
        batch_counter += 1

        try:
            # Check if thumbnail is all-white
            img = Image.open(io.BytesIO(thumbnail.small_thumb))
            extrema = img.getextrema()

            # Check if all pixels are white
            is_all_white = False
            if img.mode == "RGB":
                is_all_white = extrema == ((255, 255), (255, 255), (255, 255))
            elif img.mode == "L":
                is_all_white = extrema == (255, 255)

            if is_all_white:
                corrupted_count += 1
                print(f"  ⚠️  Found white thumbnail: SHA256={thumbnail.sha256_hash[:16]}...")

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

                print(f"      ✓ Invalidated thumbnail immediately")

        except Exception as e:
            print(f"  ❌ Error checking thumbnail {thumbnail.sha256_hash}: {e}")
            continue

        # Progress reporting
        if batch_counter % progress_interval == 0:
            print(f"Processed {batch_counter}/{total_thumbnails} thumbnails ({corrupted_count} corrupted found)...")

    # Close connections after iteration is complete
    close_old_connections()

    print("-" * 80)
    print(f"Scan complete: Processed {batch_counter} thumbnails")
    print(f"Found and fixed {corrupted_count} corrupted white thumbnails")

    if corrupted_count == 0:
        print("✅ No corrupted thumbnails found. Database is clean!")
        return

    print("-" * 80)
    print(f"Invalidated {corrupted_count} thumbnails")

    if directories_to_invalidate:
        print(f"\nMarking {len(directories_to_invalidate)} directories as invalidated...")
        print("-" * 80)

        directory_counter = 0
        total_dirs = len(directories_to_invalidate)

        with transaction.atomic():
            for directory in directories_to_invalidate:
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
                    print(f"  ✓ Invalidated directory {directory_counter}/{total_dirs}: {directory.fqpndirectory}")

        print("-" * 80)
        print(f"Marked {len(directories_to_invalidate)} directories for regeneration")

    print("\n" + "=" * 80)
    print("SUMMARY:")
    print(f"  - Total thumbnails scanned: {batch_counter}")
    print(f"  - Corrupted thumbnails found and fixed: {corrupted_count}")
    print(f"  - Directories marked for regeneration: {len(directories_to_invalidate)}")
    print("=" * 80)
    print("\n✅ Thumbnail verification complete!")
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
            help="Maximum number of records to add (0 = unlimited). Used with --add_directories, --add_files, or --add_thumbnails",
        )
        parser.add_argument(
            "--start",
            type=str,
            default=None,
            help="Starting directory path to walk from (default: ALBUMS_PATH/albums). Used with --verify_directories, --verify_files, --add_directories, or --add_files",
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
        # print(args)
        # print(options)

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
            verify_directories(start_path=start_path)
        if options["verify_files"]:
            verify_files(start_path=start_path)
        if options["add_directories"]:
            add_directories(max_count=max_count, start_path=start_path)
        if options["add_files"]:
            add_files(max_count=max_count, start_path=start_path)
        if options["add_thumbnails"]:
            add_thumbnails(max_count=max_count)
        if options["verify_thumbnails"]:
            verify_thumbnails()


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

"""Utility functions for cache_watcher application."""

import logging

from cache_watcher.models import fs_Cache_Tracking
from quickbbs.models import IndexDirs

logger = logging.getLogger(__name__)


def repair_missing_dirnames() -> int:
    """Repair fs_Cache_Tracking entries that have empty DirName but valid directory relationship.

    Examines all fs_Cache_Tracking entries with empty DirName field. If the entry has a valid
    1-to-1 relationship with an IndexDirs entry, extracts the fqpndirectory value and updates
    the DirName field.

    Returns:
        Number of records repaired
    """

    try:
        # Find entries with empty DirName but with a valid directory relationship
        entries_to_repair = fs_Cache_Tracking.objects.filter(
            DirName="", directory__isnull=False
        ).select_related("directory")

        repair_count = 0
        for entry in entries_to_repair:
            if entry.directory and entry.directory.fqpndirectory:
                entry.DirName = entry.directory.fqpndirectory
                entry.save(update_fields=["DirName"])
                repair_count += 1
                logger.debug(
                    f"Repaired DirName for cache entry: {entry.directory.fqpndirectory}"
                )

        logger.info(f"Repaired {repair_count} cache entries with missing DirName")
        return repair_count

    except Exception as e:
        logger.error(f"Error repairing missing dirnames: {e}")
        return 0


def repair_missing_dirnames_by_sha() -> int:
    """Repair fs_Cache_Tracking entries missing DirName and directory link by SHA256 lookup.

    Examines all fs_Cache_Tracking entries that have neither a DirName nor a 1-to-1 relationship
    with IndexDirs. Uses the directory_sha256 field to look up the corresponding IndexDirs entry,
    then updates both the DirName field and establishes the directory relationship.

    This method is more resilient as it works even when the 1-to-1 relationship is not set.

    Returns:
        Number of records repaired
    """
    try:
        # Find entries with empty DirName, no directory relationship, but valid SHA256
        entries_to_repair = fs_Cache_Tracking.objects.filter(
            DirName="",
            directory__isnull=True,
            directory_sha256__isnull=False,
        ).exclude(directory_sha256="")

        repair_count = 0
        for entry in entries_to_repair:
            try:
                # Look up IndexDirs by SHA256
                index_dir = IndexDirs.objects.get(dir_fqpn_sha256=entry.directory_sha256)

                # Update both DirName and directory relationship
                entry.DirName = index_dir.fqpndirectory
                entry.directory = index_dir
                entry.save(update_fields=["DirName", "directory"])
                repair_count += 1
                logger.debug(
                    f"Repaired DirName and directory link using SHA: {index_dir.fqpndirectory}"
                )

            except IndexDirs.DoesNotExist:
                logger.warning(
                    f"No IndexDirs entry found for SHA256: {entry.directory_sha256}"
                )
                continue

        logger.info(
            f"Repaired {repair_count} cache entries with missing DirName and directory link (by SHA256)"
        )
        return repair_count

    except Exception as e:
        logger.error(f"Error repairing missing dirnames by SHA: {e}")
        return 0

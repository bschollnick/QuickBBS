"""Utility functions for cache_watcher application."""

import logging

from cache_watcher.models import fs_Cache_Tracking
from quickbbs.models import DirectoryIndex

logger = logging.getLogger(__name__)


def repair_orphaned_cache_entries() -> int:
    """Remove cache entries that have no corresponding DirectoryIndex entry.

    With the new model design where directory is a required FK with CASCADE delete,
    orphaned entries shouldn't exist. This function cleans up any legacy data issues.

    Returns:
        Number of records deleted
    """
    try:
        # Use model method for standardized deletion logic
        return fs_Cache_Tracking.delete_orphaned_entries()

    except Exception as e:
        logger.error(f"Error repairing orphaned cache entries: {e}")
        return 0


def rebuild_cache_entries() -> int:
    """Rebuild cache entries for all DirectoryIndex that don't have cache tracking.

    Creates cache entries for DirectoryIndex records that don't have a corresponding
    fs_Cache_Tracking entry, marking them as invalidated so they'll be rescanned.

    Returns:
        Number of cache entries created
    """
    try:
        # Find DirectoryIndex without cache entries
        dirs_without_cache = DirectoryIndex.objects.filter(Cache_Watcher__isnull=True, delete_pending=False)

        created_count = 0
        for index_dir in dirs_without_cache:
            _, created = fs_Cache_Tracking.objects.get_or_create(
                directory=index_dir,
                defaults={
                    "invalidated": True,
                    "lastscan": 0,
                },
            )
            if created:
                created_count += 1
                logger.debug(f"Created cache entry for: {index_dir.fqpndirectory}")

        logger.info(f"Created {created_count} missing cache entries")
        return created_count

    except Exception as e:
        logger.error(f"Error rebuilding cache entries: {e}")
        return 0

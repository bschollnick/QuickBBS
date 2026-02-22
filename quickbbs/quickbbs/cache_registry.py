"""
Central cache registry for QuickBBS.

Houses the shared LRU caches and the cross-cutting cache invalidation function
that were previously in frontend/managers.py and quickbbs/directoryindex.py.

By living in the quickbbs package, these objects can be imported by any app
(quickbbs, cache_watcher, thumbnails, frontend, user_preferences) without
creating circular dependency chains.
"""

from __future__ import annotations

from cachetools.keys import hashkey
from django.conf import settings

from quickbbs.MonitoredCache import create_cache

# ---------------------------------------------------------------------------
# Cache instances
# ---------------------------------------------------------------------------

# Per-directory distinct file SHA lists (for pagination efficiency)
# Cache key: hashkey(directory_instance, sort_ordering)
distinct_files_cache = create_cache(
    settings.DISTINCT_FILES_CACHE_SIZE,
    "distinct_files",
    monitored=settings.CACHE_MONITORING,
)

# Gallery page layout results (pagination boundaries, page items)
# Cache key: hashkey(page_number, directory.pk, sort_ordering, show_duplicates)
layout_manager_cache = create_cache(
    settings.LAYOUT_MANAGER_CACHE_SIZE,
    "layout_manager",
    monitored=settings.CACHE_MONITORING,
)


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


def clear_layout_cache_for_directories(directory_ids: set[int]) -> int:
    """
    Clear layout_manager_cache and distinct_files_cache entries for one or more
    directories.

    Shared function to ensure consistent cache clearing across:
    - Cache watcher during filesystem invalidation
    - Management commands after file membership changes (add/delete/move)

    Args:
        directory_ids: Set of directory PKs to clear cache for

    Returns:
        Number of cache entries cleared (combined from both caches)
    """
    if not directory_ids:
        return 0

    # Deferred import to avoid circular dependency at module load time.
    # DirectoryIndex is only needed to construct stub instances for hashkey
    # lookups; the import resolves fine at call time.
    from quickbbs.models import (
        DirectoryIndex,  # pylint: disable=import-outside-toplevel
    )

    count = 0

    # distinct_files_cache: direct pop via constructed hashkeys
    # Keys are hashkey(directory_instance, sort) — sort is always 0, 1, or 2
    # Django models with same PK hash equally, so a stub instance matches cached entries
    for pk in directory_ids:
        stub = DirectoryIndex(pk=pk)
        for sort in range(3):
            if distinct_files_cache.pop(hashkey(stub, sort), None) is not None:
                count += 1

    # layout_manager_cache: scan keys (page_number is unbounded, can't construct keys)
    # Keys are hashkey(page_number, directory_pk, sort_ordering, show_duplicates)
    # key[1] is directory pk (int); page_number is unbounded so we scan rather than construct.
    for key in list(layout_manager_cache.keys()):
        try:
            if key[1] in directory_ids:
                layout_manager_cache.pop(key, None)
                count += 1
        except (IndexError, TypeError):
            continue

    return count

"""
Central cache registry for QuickBBS.

Houses the shared LRU caches and the cross-cutting cache invalidation function
that were previously in frontend/managers.py and quickbbs/directoryindex.py.

By living in the quickbbs package, these objects can be imported by any app
(quickbbs, cache_watcher, thumbnails, frontend, user_preferences) without
creating circular dependency chains.
"""

from __future__ import annotations

import importlib
from collections.abc import Set as AbstractSet

from cachetools import LRUCache
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

# Per-directory full (non-distinct) file SHA lists — the show_duplicates
# counterpart of distinct_files_cache, shared by item-view navigation and
# layout_manager pagination
# Cache key: hashkey(directory_instance, sort_ordering)
all_files_shas_cache = create_cache(
    settings.ALL_FILES_SHAS_CACHE_SIZE,
    "all_files_shas",
    monitored=settings.CACHE_MONITORING,
)

# Gallery page layout results (pagination boundaries, page items)
# Cache key: hashkey(page_number, directory.pk, sort_ordering, show_duplicates)
layout_manager_cache = create_cache(
    settings.LAYOUT_MANAGER_CACHE_SIZE,
    "layout_manager",
    monitored=settings.CACHE_MONITORING,
)

# Per-directory subdirectory counts (item-view "up" link page locale)
# Cache key: hashkey(directory_pk)
dir_counts_cache = create_cache(
    settings.DIR_COUNTS_CACHE_SIZE,
    "dir_counts",
    monitored=settings.CACHE_MONITORING,
)

# Ordered sibling-directory lists per parent directory (prev/next navigation
# and layout_manager page_locale computation)
# Cache key: hashkey(parent_pk, sort)
# Cache value: ordered list of (dir_fqpn_sha256, fqpndirectory) tuples
sibling_dirs_cache = create_cache(
    settings.SIBLING_DIRS_CACHE_SIZE,
    "sibling_dirs",
    monitored=settings.CACHE_MONITORING,
)


# ---------------------------------------------------------------------------
# Cache registry (for stats snapshots, bulk clearing, and cross-process
# invalidation signaling)
# ---------------------------------------------------------------------------

# All LRU/TTL caches across the codebase, resolved lazily at call time to
# avoid circular imports at module load. Each entry is a
# (module_path, attr_name, class_name) tuple. class_name is None for
# module-level variables; for class attributes set it to the class name string.
_MONITORED_CACHE_LOCATIONS: list[tuple[str, str, str | None]] = [
    ("quickbbs.cache_registry", "distinct_files_cache", None),
    ("quickbbs.cache_registry", "all_files_shas_cache", None),
    ("quickbbs.cache_registry", "layout_manager_cache", None),
    ("quickbbs.cache_registry", "dir_counts_cache", None),
    ("quickbbs.cache_registry", "sibling_dirs_cache", None),
    ("quickbbs.directoryindex", "directoryindex_cache", None),
    ("quickbbs.directoryindex", "get_view_url_cache", None),
    ("quickbbs.fileindex", "fileindex_cache", None),
    ("quickbbs.fileindex", "fileindex_download_cache", None),
    ("frontend.utilities", "webpaths_cache", None),
    ("frontend.utilities", "breadcrumbs_cache", None),
    ("quickbbs.common", "normalized_strings_cache", None),
    ("quickbbs.common", "directory_sha_cache", None),
    ("quickbbs.common", "normalized_paths_cache", None),
    ("quickbbs.fileindex", "_encoding_cache", "FileIndex"),
    ("quickbbs.fileindex", "_alias_cache", "FileIndex"),
]


def resolve_monitored_caches() -> list[tuple[str, LRUCache | Exception]]:
    """
    Resolve every cache registered in _MONITORED_CACHE_LOCATIONS.

    Imports each module at call time to avoid circular-import issues at
    module load. For class-level caches, class_name is used to look up the
    cache via getattr(getattr(module, class_name), attr_name).

    Returns:
        List of (label, cache) tuples for resolvable entries, or
        (label, exception) when the module/attribute could not be loaded.
        Callers filter by isinstance() for the cache type they need.
    """
    results: list[tuple[str, LRUCache | Exception]] = []
    for module_path, attr_name, class_name in _MONITORED_CACHE_LOCATIONS:
        label = f"{module_path}.{attr_name}"
        try:
            module = importlib.import_module(module_path)
            owner = getattr(module, class_name) if class_name is not None else module
            cache = getattr(owner, attr_name)
            results.append((label, cache))
        except (ImportError, AttributeError) as exc:
            results.append((label, exc))
    return results


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


def clear_layout_cache_for_directories(directory_ids: AbstractSet[int | None]) -> int:
    """
    Clear layout_manager_cache, distinct_files_cache, all_files_shas_cache,
    dir_counts_cache, and sibling_dirs_cache entries for one or more
    directories.

    Shared function to ensure consistent cache clearing across:
    - Cache watcher during filesystem invalidation
    - Management commands after file membership changes (add/delete/move)

    Args:
        directory_ids: Set of directory PKs to clear cache for. None values
            (e.g. from orphaned FileIndex.home_directory) are ignored.

    Returns:
        Number of cache entries cleared (combined from all caches)
    """
    directory_ids = {pk for pk in directory_ids if pk is not None}
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
        # dir_counts_cache: keyed hashkey(directory_pk)
        if dir_counts_cache.pop(hashkey(pk), None) is not None:
            count += 1
        for sort in range(3):
            if distinct_files_cache.pop(hashkey(stub, sort), None) is not None:
                count += 1
            # all_files_shas_cache: keyed hashkey(directory_instance, sort),
            # same shape as distinct_files_cache
            if all_files_shas_cache.pop(hashkey(stub, sort), None) is not None:
                count += 1
            # sibling_dirs_cache: keyed hashkey(parent_pk, sort) — the pk being
            # invalidated is the parent of the cached sibling list
            if sibling_dirs_cache.pop(hashkey(pk, sort), None) is not None:
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

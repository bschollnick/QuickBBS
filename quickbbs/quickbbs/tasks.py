"""Background tasks for QuickBBS (django-dbtasks backend)."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.tasks import TaskResultStatus, task
from django.utils import timezone

from dbtasks.models import ScheduledTask
from thumbnails.models import THUMBNAILFILES_PR_FILEINDEX_FILETYPE, ThumbnailFiles
from quickbbs.cache_registry import clear_layout_cache_for_directories
from quickbbs.MonitoredCache import MonitoredLRUCache

logger = logging.getLogger(__name__)

# All MonitoredLRUCache instances across the codebase, imported lazily at call
# time to avoid circular imports at module load. Each entry is a
# (module_path, variable_name, class_name) tuple. class_name is None for
# module-level variables; for class attributes set it to the class name string.
_MONITORED_CACHE_LOCATIONS: list[tuple[str, str, str | None]] = [
    ("quickbbs.cache_registry", "distinct_files_cache", None),
    ("quickbbs.cache_registry", "layout_manager_cache", None),
    ("quickbbs.cache_registry", "build_context_info_cache", None),
    ("quickbbs.directoryindex", "directoryindex_cache", None),
    ("quickbbs.fileindex", "fileindex_cache", None),
    ("quickbbs.fileindex", "fileindex_download_cache", None),
    ("frontend.utilities", "webpaths_cache", None),
    ("frontend.utilities", "breadcrumbs_cache", None),
    ("quickbbs.common", "normalized_strings_cache", None),
    ("quickbbs.common", "directory_sha_cache", None),
    ("quickbbs.common", "normalized_paths_cache", None),
    ("thumbnails.models", "thumbnailfiles_cache", None),
    ("quickbbs.fileindex", "_encoding_cache", "FileIndex"),
    ("quickbbs.fileindex", "_alias_cache", "FileIndex"),
]


def _collect_monitored_caches() -> list[MonitoredLRUCache]:
    """
    Return all MonitoredLRUCache instances registered in _MONITORED_CACHE_LOCATIONS.

    Imports each module at call time to avoid circular-import issues at module
    load. Silently skips any cache that is not a MonitoredLRUCache (i.e. when
    CACHE_MONITORING is False and create_cache() returned a plain LRUCache).
    For class-level caches, the class_name field in the tuple is used to look
    up the cache via ``getattr(getattr(module, class_name), attr_name)``.

    Returns:
        List of MonitoredLRUCache instances ready for stat collection.
    """
    import importlib  # pylint: disable=import-outside-toplevel

    caches: list[MonitoredLRUCache] = []
    for module_path, attr_name, class_name in _MONITORED_CACHE_LOCATIONS:
        try:
            module = importlib.import_module(module_path)
            if class_name is not None:
                owner = getattr(module, class_name)
                cache = getattr(owner, attr_name)
            else:
                cache = getattr(module, attr_name)
            if isinstance(cache, MonitoredLRUCache):
                caches.append(cache)
            else:
                logger.debug(
                    "Cache %s.%s is not monitored — skipping snapshot",
                    module_path,
                    attr_name,
                )
        except (ImportError, AttributeError) as exc:
            logger.warning(
                "Could not load cache %s.%s: %s",
                module_path,
                attr_name,
                exc,
            )
    return caches


@task()
def generate_missing_thumbnails(
    files_needing_thumbnails: list[str],
    directory_pk: int | None = None,
    batch_size: int = 5,
) -> dict[str, bool]:
    """
    Batch-create thumbnails for files that are missing them.

    Pre-filters SHA256 hashes that already have valid thumbnails to avoid
    unnecessary advisory lock acquisition and database round-trips. Then
    processes remaining hashes synchronously via
    ThumbnailFiles.get_or_create_thumbnail_record with suppress_save=True,
    collects the modified thumbnail objects, and writes them all to the
    database in a single bulk_update call. Clears the layout cache for the
    directory afterward so cached counts reflect the new thumbnails.

    Args:
        files_needing_thumbnails: SHA256 hashes needing thumbnail generation.
        directory_pk: Primary key of the directory containing these files.
            When None, cache clearing is skipped (used by bulk maintenance commands).
        batch_size: Maximum number of thumbnails to process (default: 5).

    Returns:
        Dictionary mapping each SHA256 hash to its success status.
    """
    if not files_needing_thumbnails:
        return {}

    sha256_list = files_needing_thumbnails[:batch_size]

    # Pre-filter: skip SHA256s that already have valid thumbnails.
    # Avoids acquiring advisory locks and running get_or_create for
    # thumbnails that already exist (common on rescans/retries).
    existing_shas = set(
        ThumbnailFiles.objects.filter(
            sha256_hash__in=sha256_list,
            small_thumb__isnull=False,
        )
        .exclude(small_thumb=b"")
        .values_list("sha256_hash", flat=True)
    )

    if existing_shas:
        logger.info(
            "Skipping %d thumbnails that already exist (of %d requested)",
            len(existing_shas),
            len(sha256_list),
        )

    # Remove already-existing from processing list, mark as successful
    sha256_list = [s for s in sha256_list if s not in existing_shas]
    results: dict[str, bool] = {s: True for s in existing_shas}

    if not sha256_list:
        return results

    logger.info("Processing %d thumbnails", len(sha256_list))

    thumbnails_to_update: list[ThumbnailFiles] = []

    for sha256 in sha256_list:
        try:
            thumbnail = ThumbnailFiles.get_or_create_thumbnail_record(
                sha256,
                suppress_save=True,
                prefetch_related_thumbnail=THUMBNAILFILES_PR_FILEINDEX_FILETYPE,
                select_related_fileindex=("filetype",),
            )
            # Only queue for bulk_update if thumbnail data was actually generated
            if thumbnail.small_thumb:
                thumbnails_to_update.append(thumbnail)
            results[sha256] = True
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Error creating thumbnail for %s", sha256)
            results[sha256] = False

    if thumbnails_to_update:
        ThumbnailFiles.objects.bulk_update(
            thumbnails_to_update,
            ["small_thumb", "medium_thumb", "large_thumb"],
            batch_size=batch_size,
        )

    successful_count = sum(results.values())
    if successful_count > 0 and directory_pk is not None:
        cleared_count = clear_layout_cache_for_directories({directory_pk})
        if cleared_count:
            logger.info(
                "Cleared %d layout cache entries for directory after thumbnail processing",
                cleared_count,
            )

    # newly_processed excludes the pre-existing shas that were seeded as True
    newly_processed = successful_count - len(existing_shas)
    if newly_processed > 0:
        logger.info(
            "Successfully processed %d new thumbnails, bulk-updated %d records (%d already existed)",
            newly_processed,
            len(thumbnails_to_update),
            len(existing_shas),
        )

    return results


@task()
def daily_cleanup_finished_jobs() -> int:
    """
    Delete completed and failed task records older than the configured retain period.

    Safety-net for records where delete_after was not set (e.g., tasks completed
    while the taskrunner was offline). The runner's built-in delete_tasks() loop
    handles records with delete_after set; this catches any that were missed.

    Registered as a periodic task via TASKS settings (runs daily at midnight).

    Returns:
        Number of task records deleted.
    """
    cutoff = timezone.now() - timedelta(days=settings.TASK_RETAIN_DAYS)
    deleted, _ = ScheduledTask.objects.filter(
        status__in=[TaskResultStatus.SUCCESSFUL, TaskResultStatus.FAILED],
        finished_at__lt=cutoff,
    ).delete()
    if deleted:
        logger.info(
            "Cleaned up %d completed task records older than %d days",
            deleted,
            settings.TASK_RETAIN_DAYS,
        )
    return deleted


def snapshot_cache_statistics() -> dict[str, dict[str, int | float | str]]:
    """
    Snapshot current MonitoredLRUCache hit/miss statistics to the database.

    Reads live hit/miss counters directly from the in-process MonitoredLRUCache
    instances and upserts one row per cache into cache_statistics_tracking.
    Must be called from within the web server process so the in-memory counters
    are accessible — calling from a separate worker process (e.g. a dbtasks
    runner) would see freshly-initialised caches with zero counts.

    Called directly from new_viewgallery() on every gallery request when
    CACHE_MONITORING is True. Skips caches whose stats are unchanged since the
    last snapshot to minimise unnecessary writes.

    Returns:
        Dictionary mapping cache name to its snapshot stats dict for changed caches.
    """
    # Deferred import to avoid circular dependency:
    # cache_watcher.models → quickbbs.cache_registry → (indirectly) tasks
    from cache_watcher.models import CacheStatisticsTracking  # pylint: disable=import-outside-toplevel

    caches = _collect_monitored_caches()
    if not caches:
        logger.debug("No monitored caches found — snapshot skipped")
        return {}

    # Fetch all existing rows in one query, keyed by cache name
    cache_names = [c.name for c in caches]
    existing_rows: dict[str, CacheStatisticsTracking] = {
        row.cache_name: row
        for row in CacheStatisticsTracking.objects.filter(cache_name__in=cache_names)
    }

    results: dict[str, dict[str, int | float | str]] = {}

    for cache in caches:
        stats = cache.stats()
        name = stats["name"]
        existing = existing_rows.get(name)

        if (
            existing is not None
            and existing.hits == stats["hits"]
            and existing.misses == stats["misses"]
            and existing.current_size == stats["size"]
        ):
            logger.debug("Cache snapshot [%s]: no change since last snapshot — skipping write", name)
            continue

        CacheStatisticsTracking.objects.update_or_create(
            cache_name=name,
            defaults={
                "hits": stats["hits"],
                "misses": stats["misses"],
                "current_size": stats["size"],
                "max_size": stats["maxsize"],
            },
        )
        results[name] = stats
        logger.info(
            "Cache snapshot [%s]: %d hits, %d misses, %.1f%% hit rate, %d/%d entries",
            name,
            stats["hits"],
            stats["misses"],
            cache.hit_rate,
            stats["size"],
            stats["maxsize"],
        )

    return results

"""Django admin registrations for the QuickBBS core models."""

import time

from dbtasks.models import ScheduledTask
from django.contrib import admin
from django.db import transaction
from django.db.models.query import QuerySet
from django.http import HttpRequest
from django.tasks import TaskResultStatus
from django.utils import timezone
from django.utils.html import format_html

from quickbbs.models import DirectoryIndex, Favorites, FileIndex, Owners
from quickbbs.tasks import get_vacuum_candidates
from thumbnails.models import ThumbnailFiles


@admin.register(FileIndex)
class AdminMasterIndex(admin.ModelAdmin):
    """Admin configuration for FileIndex (the master file index)."""

    search_fields = [
        "name",
        "file_sha256",
        "unique_sha256",
        "id",
    ]
    list_filter = ["filetype"]
    readonly_fields = (
        "id",
        "file_sha256",
        "unique_sha256",
        "name_sort",
        "display_fqpndirectory",
        "display_parent_directory",
        "has_thumbs",
        "small_thumb",
    )

    list_display = (
        "id",
        "file_sha256",
        "unique_sha256",
        "name",
        "has_thumbs",
        "lastscan",
        "lastmod",
        "size",
        "display_fqpndirectory",
        "delete_pending",
        "ownership",
        "filetype",
    )
    fields = (
        "id",
        "file_sha256",
        "unique_sha256",
        "virtual_directory",
        "has_thumbs",
        "name",
        "lastscan",
        "lastmod",
        "size",
        "display_fqpndirectory",
        "display_parent_directory",
        "delete_pending",
        "ownership",
        "filetype",
        "small_thumb",
    )

    def has_thumbs(self, obj: FileIndex) -> bool:
        """
        Return whether the file has any thumbnail data.

        Args:
            obj: FileIndex record being displayed

        Returns:
            True if the linked ThumbnailFiles record holds a small, medium,
            or large thumbnail; False if unlinked or all sizes are empty
        """
        if obj.new_ftnail is None:
            return False
        if any(
            [
                obj.new_ftnail.small_thumb,
                obj.new_ftnail.medium_thumb,
                obj.new_ftnail.large_thumb,
            ]
        ):
            return True
        return False

    def display_fqpndirectory(self, obj: FileIndex) -> str:
        """
        Return the file's directory path for display.

        Args:
            obj: FileIndex record being displayed

        Returns:
            The fully qualified directory path, or "No directory" when unset
        """
        if obj.fqpndirectory:
            return obj.fqpndirectory
        return "No directory"

    def display_parent_directory(self, obj: FileIndex) -> str:
        """
        Return the home directory path for display.

        Args:
            obj: FileIndex record being displayed

        Returns:
            The home directory's fully qualified path, or "No home directory"
            when the record is orphaned
        """
        if obj.home_directory:
            return obj.home_directory.fqpndirectory
        return "No home directory"

    def small_thumb(self, obj: FileIndex) -> bytes | memoryview | None:  # pragma: no cover
        """
        Return a short preview of the small thumbnail's raw bytes.

        Args:
            obj: FileIndex record being displayed

        Returns:
            The first 20 bytes of the small thumbnail (bytes or memoryview,
            depending on how the BinaryField was loaded), or None when no
            thumbnail is linked or the small size is empty
        """
        if obj.new_ftnail is None:
            return None
        if obj.new_ftnail.small_thumb:
            return obj.new_ftnail.small_thumb[0:20]
        return None


@admin.register(DirectoryIndex)
class AdminMasterDirs(admin.ModelAdmin):
    """Admin configuration for DirectoryIndex (the master directory index)."""

    search_fields = [
        "fqpndirectory",
        "dir_fqpn_sha256",
        # "dirname_sha256",
    ]
    readonly_fields = (
        "id",
        "dir_fqpn_sha256",
    )
    list_display = (
        "id",
        "dir_fqpn_sha256",
        # "dirname_sha256",
        "fqpndirectory",
        "is_generic_icon",
        "cache_invalidated",
        "cache_lastscan",
        "filetype",
        "delete_pending",
    )
    list_filter = ["filetype"]
    actions = ["force_rebuild_thumbnails"]

    fields = (
        "id",
        "dir_fqpn_sha256",
        # "dirname_sha256",
        "fqpndirectory",
        "is_generic_icon",
        "delete_pending",
    )

    @admin.action(description="Force rebuild thumbnails for selected directories")
    def force_rebuild_thumbnails(self, request: HttpRequest, queryset: "QuerySet[DirectoryIndex]") -> None:
        """
        Force rebuild thumbnails for all files in the selected directories.

        This action clears all thumbnail data (sets to NULL) for files in the selected
        directories, forcing them to be regenerated on next access. Also marks the
        directories as invalidated in the cache system.

        Args:
            request: The HTTP request object
            queryset: QuerySet of selected DirectoryIndex objects

        Returns:
            None - displays success message to user
        """
        directory_count = queryset.count()

        with transaction.atomic():
            # ThumbnailFiles is content-addressed (shared by sha256 across
            # FileIndex rows via the new_ftnail FK), so clear each distinct
            # thumbnail row once via a single UPDATE instead of looping
            # over every FileIndex row and re-saving shared thumbnails
            # redundantly.
            files_in_dirs = FileIndex.objects.filter(home_directory__in=queryset, delete_pending=False)
            total_files = files_in_dirs.count()
            thumb_ids = files_in_dirs.exclude(new_ftnail__isnull=True).values_list("new_ftnail_id", flat=True).distinct()
            total_thumbnails_cleared = ThumbnailFiles.objects.filter(id__in=thumb_ids).update(
                small_thumb=None,
                medium_thumb=None,
                large_thumb=None,
            )

            # Mark the directories as invalidated in the cache system with one
            # UPDATE — this ensures they will be rescanned and thumbnails
            # regenerated.
            directories_invalidated = queryset.update(cache_invalidated=True, cache_lastscan=time.time())

            for directory in queryset:
                # Invalidate the directory's thumbnail as well
                directory.invalidate_thumb()

        self.message_user(
            request,
            f"Cleared thumbnails for {total_thumbnails_cleared} files across {directory_count} "
            f"director{'y' if directory_count == 1 else 'ies'} (total files: {total_files}). "
            f"Invalidated {directories_invalidated} director{'y' if directories_invalidated == 1 else 'ies'} in cache.",
        )


admin.site.register(Owners)
admin.site.register(Favorites)


_original_admin_index = admin.site.index


def _index_with_vacuum_status(request: HttpRequest, extra_context: dict | None = None):
    """Inject PostgreSQL vacuum-candidate tables into the admin index context.

    Wraps AdminSite.index() rather than subclassing AdminSite, since
    quickbbs/urls.py registers the default admin.site directly. Reuses
    quickbbs.tasks.get_vacuum_candidates() (also used by the weekly_vacuum_check
    periodic task) so the admin widget and the logged warning agree.
    """
    extra_context = extra_context or {}
    extra_context["vacuum_candidates"] = get_vacuum_candidates()
    return _original_admin_index(request, extra_context)


admin.site.index = _index_with_vacuum_status


_STATUS_COLORS = {
    TaskResultStatus.READY: "#6c757d",
    TaskResultStatus.RUNNING: "#0d6efd",
    TaskResultStatus.SUCCESSFUL: "#198754",
    TaskResultStatus.FAILED: "#dc3545",
}


class ScheduledTaskAdmin(admin.ModelAdmin):
    """Admin view for django-dbtasks job queue records (pending and completed)."""

    list_display = (
        "task_path",
        "colored_status",
        "queue",
        "priority",
        "periodic",
        "enqueued_at",
        "started_at",
        "finished_at",
        "elapsed_runtime",
    )
    list_filter = ("status", "queue", "backend", "periodic")
    search_fields = ("task_path", "id", "exception_path")
    ordering = ("-enqueued_at",)
    actions = ("mark_ready", "mark_deletion")
    readonly_fields = (
        "id",
        "status",
        "enqueued_at",
        "started_at",
        "finished_at",
        "args",
        "kwargs",
        "task_path",
        "priority",
        "queue",
        "backend",
        "run_after",
        "delete_after",
        "periodic",
        "worker_ids",
        "return_value",
        "exception_path",
        "traceback",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Disallow manual creation — rows are managed by the task worker."""
        return False

    def has_change_permission(self, request: HttpRequest, obj: ScheduledTask | None = None) -> bool:
        """Disallow editing — job records are written only by the task worker."""
        return False

    def has_delete_permission(self, request: HttpRequest, obj: ScheduledTask | None = None) -> bool:
        """Allow deletion so stale/failed job records can be pruned manually."""
        return True

    @admin.display(description="Status", ordering="status")
    def colored_status(self, obj: ScheduledTask) -> str:
        """Return the job status as color-coded HTML for quick scanning."""
        color = _STATUS_COLORS.get(obj.status, "#6c757d")
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, obj.get_status_display())

    @admin.display(description="Elapsed")
    def elapsed_runtime(self, obj: ScheduledTask) -> str:
        """Return how long the job ran, or has been running, as H:MM:SS.

        Uses finished_at - started_at once the job completes; for a job
        still RUNNING, uses now - started_at so the column updates on every
        page load. Empty for jobs that haven't started yet.
        """
        if obj.started_at is None:
            return ""
        end = obj.finished_at or timezone.now()
        return str(end - obj.started_at).split(".", maxsplit=1)[0]

    @admin.action(description="Mark ready to run now")
    def mark_ready(self, request: HttpRequest, queryset: "QuerySet[ScheduledTask]") -> None:
        """Reset selected jobs to READY and clear run_after so they run immediately."""
        queryset.update(status=TaskResultStatus.READY, run_after=None)

    @admin.action(description="Mark ready for deletion")
    def mark_deletion(self, request: HttpRequest, queryset: "QuerySet[ScheduledTask]") -> None:
        """Set delete_after to now so the retention cleanup task removes these jobs."""
        queryset.update(delete_after=timezone.now())

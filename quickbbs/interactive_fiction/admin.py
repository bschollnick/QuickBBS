"""Admin configuration for interactive_fiction."""

from __future__ import annotations

from django.contrib import admin

from interactive_fiction.models import (
    CurrentGame,
    SaveState,
    Story,
    StoryAccess,
    StoryImage,
)


class StoryAccessInline(admin.TabularInline):
    """Inline editor for per-user StoryAccess grants on a Story."""

    model = StoryAccess
    extra = 1
    autocomplete_fields = ("user",)


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    """Admin interface for the Story model, including access grants."""

    list_display = ("title", "owner", "is_public", "is_available", "updated_at")
    list_filter = ("is_public", "is_available")
    search_fields = ("title", "slug", "owner__username")
    readonly_fields = ("created_at", "updated_at", "source_fqfn", "source_sha256")
    inlines = (StoryAccessInline,)


@admin.register(StoryAccess)
class StoryAccessAdmin(admin.ModelAdmin):
    """Admin interface for standalone StoryAccess management."""

    list_display = ("story", "user", "granted_at")
    search_fields = ("story__title", "user__username")
    autocomplete_fields = ("story", "user")


@admin.register(CurrentGame)
class CurrentGameAdmin(admin.ModelAdmin):
    """Admin interface for in-flight games.

    `state` is excluded from the list view and deferred on the list
    queryset — it's a potentially large JSONB blob (Postgres TOASTs it
    out-of-line), and no admin listing needs to detoast every row's
    state just to render a title/turn-count table, matching the same
    concern the design document raises for `Story.compiled_json`.
    """

    list_display = ("user", "story", "turn_count", "updated_at")
    search_fields = ("story__title", "user__username")
    autocomplete_fields = ("story", "user")
    readonly_fields = ("turn_count", "updated_at")

    def get_queryset(self, request):
        """
        Return the list-view queryset with `state` deferred.

        Args:
            request: The current admin request.

        Returns:
            The default queryset with `.defer("state")` applied.
        """
        return super().get_queryset(request).defer("state")


@admin.register(StoryImage)
class StoryImageAdmin(admin.ModelAdmin):
    """Admin interface for story image/video tag mappings."""

    list_display = ("story", "tag_name", "is_cover", "file_index")
    search_fields = ("story__title", "tag_name")
    autocomplete_fields = ("story", "file_index")


@admin.register(SaveState)
class SaveStateAdmin(admin.ModelAdmin):
    """Admin interface for named save slots — same `state`-deferral
    reasoning as CurrentGameAdmin."""

    list_display = ("user", "story", "slot", "label", "updated_at")
    search_fields = ("story__title", "user__username", "label")
    autocomplete_fields = ("story", "user")
    readonly_fields = ("updated_at",)

    def get_queryset(self, request):
        """
        Return the list-view queryset with `state` deferred.

        Args:
            request: The current admin request.

        Returns:
            The default queryset with `.defer("state")` applied.
        """
        return super().get_queryset(request).defer("state")

"""Admin configuration for interactive_fiction."""

from __future__ import annotations

from django.contrib import admin

from interactive_fiction.models import (
    CurrentGame,
    EngineAPI,
    SaveState,
    Story,
    StoryAccess,
    StoryImage,
    StorySystemConfig,
)


class StoryAccessInline(admin.TabularInline):
    """Inline editor for per-user StoryAccess grants on a Story."""

    model = StoryAccess
    extra = 1
    autocomplete_fields = ("user",)


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    """Admin interface for the Story model, including access grants.

    `is_engine_trusted` is deliberately admin-only (never exposed to the
    upload form or any user-facing view) — see
    claude_docs/plans/external_expansion_IF_engine.md's Design section for
    why this must stay a superuser-only, explicit, per-story opt-in.
    """

    list_display = ("title", "owner", "is_public", "is_available", "is_engine_trusted", "updated_at")
    list_filter = ("is_public", "is_available", "is_engine_trusted")
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


@admin.register(EngineAPI)
class EngineAPIAdmin(admin.ModelAdmin):
    """Admin interface for discovered engine APIs — the real Enabled/
    Disabled toggle (explicit user requirement, 2026-08-22) controlling
    whether a scanned API is available to any story at all. Rows are
    created/refreshed only by the `sync_engine_apis` management command,
    never by hand — `name`/`display_name`/`discovered_at`/`last_seen_at`
    are read-only here; `is_enabled` is the one real editable field.
    """

    list_display = ("display_name", "name", "is_enabled", "discovered_at", "last_seen_at")
    list_filter = ("is_enabled",)
    search_fields = ("name", "display_name")
    readonly_fields = ("name", "display_name", "discovered_at", "last_seen_at")


@admin.register(StorySystemConfig)
class StorySystemConfigAdmin(admin.ModelAdmin):
    """Admin interface for per-story engine-system config.

    Saving here goes through Django's normal admin full_clean() path
    AND StorySystemConfig.save()'s own explicit full_clean() call (see
    that method's docstring) — either one alone would already reject an
    invalid `config` for admin-created rows, but the model-level override
    additionally covers every non-admin creation path (management
    commands, `.objects.create()`), which is the real requirement.
    """

    list_display = ("story", "system_name", "updated_at")
    list_filter = ("system_name",)
    search_fields = ("story__title",)
    autocomplete_fields = ("story",)
    readonly_fields = ("updated_at",)


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

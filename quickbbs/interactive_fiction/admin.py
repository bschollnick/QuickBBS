"""Admin configuration for interactive_fiction."""

from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from interactive_fiction.models import (
    CurrentGame,
    EngineAPI,
    SaveState,
    Story,
    StoryAccess,
    StoryImage,
    StorySystemConfig,
)


class GameIngestionErrorFilter(admin.SimpleListFilter):
    """List filter for `Story.game_ingestion_error` — a plain CharField,
    not a boolean, so Django's declarative `list_filter` can't target it
    directly; this presents it as a Yes/No choice instead.
    """

    title = "ingestion error"
    parameter_name = "has_game_ingestion_error"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin) -> list[tuple[str, str]]:
        """Return the filter's two choices.

        Args:
            request: The current admin request (unused).
            model_admin: The ModelAdmin this filter is attached to (unused).

        Returns:
            The (value, label) pairs shown in the filter sidebar.
        """
        return [("yes", "Yes"), ("no", "No")]

    def queryset(self, request: HttpRequest, queryset: QuerySet[Story]) -> QuerySet[Story]:
        """Filter the queryset by whether `game_ingestion_error` is set.

        Args:
            request: The current admin request (unused).
            queryset: The Story queryset to filter.

        Returns:
            The filtered queryset, or the original queryset unchanged if
            no recognized value was selected.
        """
        if self.value() == "yes":
            return queryset.exclude(game_ingestion_error="")
        if self.value() == "no":
            return queryset.filter(game_ingestion_error="")
        return queryset


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

    `game_ingestion_error` is surfaced in `list_display`/`list_filter`
    (the game-folder separation design work's own decided
    "admin-visible flag, not log-only" requirement) so a game folder that
    failed ingestion (missing manifest, a MAIN_STORY_FILE that doesn't
    match a real .inkj, or an unresolved required plugin) is immediately
    visible without grepping logs.
    """

    list_display = ("title", "owner", "is_public", "is_available", "is_engine_trusted", "has_game_ingestion_error", "updated_at")
    list_filter = ("is_public", "is_available", "is_engine_trusted", GameIngestionErrorFilter)
    search_fields = ("title", "slug", "owner__username", "game_author")
    readonly_fields = ("created_at", "updated_at", "source_fqfn", "source_sha256")
    # compiled_json holds a full compiled Ink story — real-world stories
    # (a large multi-file corpus can easily run 100+ files) run several
    # MB, and Django's
    # default ModelAdmin renders every editable field as a form widget,
    # POSTing the whole thing back on every save. That blew right past
    # DATA_UPLOAD_MAX_MEMORY_SIZE the first time a story this large was
    # actually saved through this admin page (a real, previously-latent
    # bug this uncovered, not a hypothetical). It's also never meant to
    # be hand-edited here — ingestion/upload are the only real writers —
    # so simply excluding it from the form is correct, not a workaround.
    exclude = ("compiled_json",)
    inlines = (StoryAccessInline,)

    @admin.display(boolean=True, description="Ingestion error")
    def has_game_ingestion_error(self, obj: Story) -> bool:
        """
        Return whether this story's most recent game-folder ingestion failed.

        Args:
            obj: The Story row being displayed.

        Returns:
            True if `obj.game_ingestion_error` is non-blank.
        """
        return bool(obj.game_ingestion_error)


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
    created/refreshed only by the `scan_if_stories` management command,
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

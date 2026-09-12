"""Models for the interactive_fiction app.

Requires Django 6.1+: FK fields below use `models.DB_CASCADE`, a DB-enforced
`ON DELETE` constraint added in Django 6.1 that doesn't exist on 6.0 or
earlier (matching the precedent in `quickbbs/models.py` and
`user_preferences/models.py`).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from interactive_fiction.engine_api import clear_api_descriptor_cache, discover_api_descriptors
from ink_engine.engine_config_schemas import SystemConfigValidationError
from quickbbs.models import FileIndex

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser, AnonymousUser


#: The play-page layouts this engine ships, mapped to the template that
#: renders each. A game chooses one by NAME in its manifest
#: (`PLAY_LAYOUT`); the name is looked up here rather than used as a path,
#: so a manifest can never point the renderer at a template of its own —
#: which matters because game folders live in the untrusted Albums tree.
#:
#: "classic" is the default and the shape every story had before layouts
#: existed: a left sidebar of controls, story text filling the rest.
#: "three_column" adds a right-hand panel beside the story, for a game
#: with content that belongs next to the prose rather than inside it (an
#: inventory listing, a device the player opens).
PLAY_LAYOUTS: dict[str, str] = {
    "classic": "interactive_fiction/play_classic.jinja",
    "three_column": "interactive_fiction/play_three_column.jinja",
}

#: The layout used by a story that names none, names one this engine
#: version does not have, or has no game manifest at all (every uploaded
#: story).
DEFAULT_PLAY_LAYOUT = "classic"


def play_layout_template(layout_name: str) -> str:
    """Resolve a game's chosen layout name to the template that renders it.

    Args:
        layout_name: The name from the game's own manifest, or "" for a
            story with no manifest.

    Returns:
        The template path for that layout, falling back to
        `DEFAULT_PLAY_LAYOUT`'s own template for an unknown or empty name.
        Unknown names fall back rather than raise on purpose: a story
        ingested against a newer engine that had a layout this one lacks
        should still be playable, just plainer.
    """
    return PLAY_LAYOUTS.get(layout_name, PLAY_LAYOUTS[DEFAULT_PLAY_LAYOUT])


class Story(models.Model):
    """A single Ink story: compiled JSON plus ownership/visibility metadata."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DB_CASCADE, related_name="if_stories")
    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    compiled_json = models.JSONField()
    ink_version = models.CharField(max_length=32, blank=True)
    is_public = models.BooleanField(default=False)
    # Scanner-ingestion fields (populated only for stories ingested from the
    # Albums tree; blank/default for stories created via the upload form).
    source_fqfn = models.CharField(max_length=1024, blank=True, default="")
    source_sha256 = models.CharField(max_length=64, blank=True, default="")
    is_available = models.BooleanField(default=True)
    # Engine-service trust gate. Default False for EVERY story, including
    # every scanner-ingested `.inkj` and every user upload; only a
    # superuser flipping this in Django admin makes `_call_function()`
    # dispatch this story's EXTERNAL calls to a real Python callable
    # instead of its compiled-in Ink fallback. Getting the default wrong
    # reopens a remote-code-execution risk on uploaded Ink content.
    is_engine_trusted = models.BooleanField(default=False)
    # Game-manifest fields (see the game-folder separation design work):
    # populated from a game folder's own mandatory __init__.py
    # (Albums/interactive_fiction/<game_name>/__init__.py) at ingestion
    # time — blank/default for a story created via the upload form, which
    # has no game folder/manifest at all. game_required_plugins is the
    # list of ink_engine.plugin.Plugin names the manifest declares. It is
    # stored verbatim: ingestion never resolves these names (that would
    # mean loading the game's own .py files, which is_engine_trusted
    # gates). They are checked at play time by
    # engine_services.bindings_for(), which logs a mismatch.
    game_author = models.CharField(max_length=255, blank=True, default="")
    game_required_plugins = models.JSONField(default=list, blank=True)
    # The game's own declared character-creation questions (a game with
    # none, the normal case, skips straight to play() as before) — a
    # list of field dicts, e.g. {"var": "player_name", "type": "text",
    # "label": "What is your name?", "default": "Bob"} or a "radio_image"
    # field whose "value" is itself a dict of {var_name: value} pairs,
    # letting one form control set several related globals at once (a
    # real converted game's own gender picker sets two related globals
    # from a single 3-way choice — see interactive_fiction/views.py's
    # character_creation()). Rendered generically by
    # templates/interactive_fiction/character_creation.jinja; answers are
    # written into InkRuntimeState.globals before the story's first
    # continue_story() call, never stored on this row itself.
    game_new_game_fields = models.JSONField(default=list, blank=True)
    # Set by ingestion when a game folder's manifest is missing or its
    # MAIN_STORY_FILE doesn't match a real .inkj present. Blank means
    # "ingested cleanly" (the normal case for every non-game-folder story
    # too).
    game_ingestion_error = models.CharField(max_length=1024, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata: admin display names."""

        verbose_name_plural = "Stories"

    def __str__(self) -> str:
        """
        Return the story's title.

        Returns:
            The story's title.
        """
        return self.title

    @property
    def cover_image(self) -> "StoryImage | None":
        """Return this story's cover StoryImage, if one is set.

        Not a stored FK on Story itself (see StoryImage.is_cover's docstring
        for why) — one query here; the underlying gallery file is reachable
        via the returned row's own `file_index` FK.

        Returns:
            The StoryImage row with is_cover=True, or None.
        """
        return self.images.filter(is_cover=True).first()

    def opted_in_plugin_names(self) -> list[str]:
        """Return the plugin names this story has its own config row for.

        A story only ever gets bindings for a plugin it has explicitly
        opted into (a real `StorySystemConfig` row exists) — never a flat
        merge of every globally-enabled plugin (see
        `engine_services.bindings_for()`).

        Returns:
            Distinct `StorySystemConfig.system_name` values for this
            story.
        """
        return list(self.system_configs.values_list("system_name", flat=True).distinct())


class StoryAccess(models.Model):
    """Grants a specific user access to a non-public story.

    The owner always has implicit access — no row is created for the owner.
    """

    story = models.ForeignKey(Story, on_delete=models.DB_CASCADE, related_name="grants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DB_CASCADE, related_name="if_story_grants")
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Model metadata: uniqueness constraint on (story, user)."""

        constraints = [models.UniqueConstraint(fields=["story", "user"], name="unique_story_user_grant")]

    def __str__(self) -> str:
        """
        Return a human-readable description of the grant.

        Returns:
            A string of the form "<username> -> <story title>".
        """
        return f"{self.user} -> {self.story}"


class StoryImage(models.Model):
    """Maps a story's '# image: <tag_name>' or '# video: <tag_name>' Ink tag
    to a real gallery file.

    ``file_index`` is a real ForeignKey into the main gallery's own
    `FileIndex` — a story image/video is never stored per-story, and never
    stores any bytes of its own at all: the underlying file already lives on
    disk and is already tracked by the normal scanner
    (`quickbbs/management/commands/scan.py`), exactly like every other file
    in the gallery. Serving reuses `FileIndex.inline_sendfile`/
    `async_inline_sendfile` and `ThumbnailFiles.send_thumbnail` directly —
    see `interactive_fiction/story_views.py`'s `story_image`/`story_video`/
    `story_cover`.

    ``on_delete=DB_SET_NULL`` (not PROTECT) is deliberate and matches
    `FileIndex.home_directory`/`FileIndex.new_ftnail`'s own on_delete choice:
    if the underlying gallery file is ever removed/rescanned away, this
    mapping should simply go stale (`file_index=None`), not block the
    delete — there's no shared-blob lifetime to protect here the way an
    earlier, now-removed `StoryImageBlob` design needed, so this FK doesn't
    hit the same DB-level/Python-level on_delete mixing restriction that
    design worked around (Django 6.1 forbids mixing them in one connected FK
    graph — `FileIndex`/`ThumbnailFiles` already use DB-level `on_delete`
    throughout, matching every other FK in this file).

    ``is_cover`` (not a Story.cover_image FK) identifies the library-grid
    cover image, avoiding a typed FK from Story into this model.
    """

    story = models.ForeignKey(Story, on_delete=models.DB_CASCADE, related_name="images")
    tag_name = models.CharField(max_length=255, db_index=True)
    file_index = models.ForeignKey(FileIndex, on_delete=models.DB_SET_NULL, null=True, related_name="story_images")
    is_cover = models.BooleanField(default=False)

    class Meta:
        """Model metadata: uniqueness constraints on (story, tag_name) and,
        partially, on (story) where is_cover=True — at most one cover image
        per story."""

        constraints = [
            models.UniqueConstraint(fields=["story", "tag_name"], name="unique_story_image_tag"),
            models.UniqueConstraint(fields=["story"], condition=models.Q(is_cover=True), name="unique_story_cover_image"),
        ]

    def __str__(self) -> str:
        """
        Return a human-readable description of the image mapping.

        Returns:
            A string of the form "<story title>: <tag_name>".
        """
        return f"{self.story}: {self.tag_name}"


class EngineAPI(models.Model):
    """One discovered engine API — a reusable system Python module
    exposing an `ink_engine.plugin.Plugin`.

    One row per real discovered `Plugin.name`, populated by
    the `scan_if_stories` management command (never by hand — this is
    metadata ABOUT a scanned-and-found Python module, not story-author
    data). ``is_enabled`` gates whether the API is available to any story
    at all — a separate axis from a specific story's own `is_engine_trusted`
    flag and its `StorySystemConfig`/binding registration, which decide
    whether and how THAT story actually uses an enabled API. Disabling an
    API already in use by some story does not error at disable-time (a
    real "who's using this" check was explicitly decided against as
    unneeded complexity for this admin action) — the effect happens the
    next time that story's own bindings are resolved (see
    `engine_services.bindings_for()`'s own real handling and logging of a
    disabled/missing API).

    New for a given API name always starts disabled (`is_enabled=False`
    default) — same safe-by-default posture as `Story.is_engine_trusted`.
    """

    name = models.SlugField(unique=True, max_length=64)
    display_name = models.CharField(max_length=128)
    is_enabled = models.BooleanField(default=False)
    discovered_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata: admin display ordering."""

        verbose_name_plural = "Engine APIs"
        ordering = ["name"]

    def __str__(self) -> str:
        """
        Return a human-readable description of this engine API.

        Returns:
            A string of the form "<display name> (enabled|disabled)".
        """
        return f"{self.display_name} ({'enabled' if self.is_enabled else 'disabled'})"


def sync_engine_apis() -> tuple[int, int]:
    """Scan for real API files and upsert an `EngineAPI` row for each.

    Called by the `scan_if_stories` management command. Never removes a
    row for an API that's disappeared from disk (e.g. a third-party
    package temporarily uninstalled) — a missing-but-still-enabled API
    degrades the same real, logged way a disabled one does (see
    `engine_services.bindings_for()`), rather than silently vanishing
    from the admin listing along with any story config still referencing
    it by name.

    Returns:
        A tuple of (number of newly-discovered APIs created, number of
        already-known APIs whose display_name/last_seen_at was refreshed).
    """
    # Game folders may have been added/removed on disk since the last
    # discovery pass — clear the cache so this scan sees the real, current
    # state rather than a stale cached result.
    clear_api_descriptor_cache()
    descriptors = discover_api_descriptors()
    created_count = 0
    updated_count = 0
    for name, descriptor in descriptors.items():
        _, created = EngineAPI.objects.update_or_create(name=name, defaults={"display_name": descriptor.display_name})
        if created:
            created_count += 1
        else:
            updated_count += 1
    return created_count, updated_count


class StorySystemConfig(models.Model):
    """One reusable engine system's own config for one story.

    One row per (story, system_name), not one shared JSONField on
    `Story`, so each system's config is validated independently.

    ``system_name`` is a plain validated string, never a closed
    `TextChoices` enum: an enum could not name an API discovered later
    without a migration. `clean()` checks it against the LIVE set of
    `Plugin` names discovered on disk — regardless of that API's
    `EngineAPI.is_enabled` state — then runs that API's own
    `validate_config` against `config`.

    **Validation applies to untrusted stories too.** This is a separate
    risk from the EXTERNAL binding-trust `Story.is_engine_trusted`
    gates: an untrusted story's config could still become an injection
    surface if a future system read it carelessly.
    """

    story = models.ForeignKey(Story, on_delete=models.DB_CASCADE, related_name="system_configs")
    system_name = models.CharField(max_length=64)
    # Defaults to {} (not nullable) -- a config-less API (validate_config is
    # None, e.g. engine_plugins/scheduling.py's is_day binding) still needs
    # a real row to signal "this story wants this API's bindings" (see
    # engine_services.bindings_for()), even though there's nothing to
    # actually validate for it.
    config = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata: at most one config row per (story, system_name)."""

        constraints = [models.UniqueConstraint(fields=["story", "system_name"], name="unique_story_system_config")]

    def clean(self) -> None:
        """Validate `system_name` against the live API registry, then
        `config` against that API's own schema.

        Raises:
            django.core.exceptions.ValidationError: If `system_name` names
                no real, currently-discoverable `Plugin`, or `config`
                doesn't match that plugin's own registered schema.
        """
        descriptors = discover_api_descriptors()
        descriptor = descriptors.get(self.system_name)
        if descriptor is None:
            raise ValidationError({"system_name": f"'{self.system_name}' is not a real, currently-discoverable engine API"})
        if descriptor.validate_config is not None:
            try:
                descriptor.validate_config(self.config)
            except SystemConfigValidationError as exc:
                raise ValidationError({"config": str(exc)}) from exc

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Save, always running `full_clean()` first.

        Django does NOT call `clean()` automatically on `.save()` by
        default — only `ModelForm`/admin flows call `full_clean()` for
        you. Overriding `save()` here means every caller (management
        commands, a future config-loading admin action, `.objects.create()`
        calls) gets real schema enforcement, not just callers that happen
        to go through a form; skipping this would make the "closed,
        validated schema" plan requirement decorative rather than real.

        Args:
            force_insert: Forwarded to the real `Model.save()`.
            force_update: Forwarded to the real `Model.save()`.
            using: Forwarded to the real `Model.save()`.
            update_fields: Forwarded to the real `Model.save()`.
        """
        self.full_clean()
        super().save(force_insert=force_insert, force_update=force_update, using=using, update_fields=update_fields)

    def __str__(self) -> str:
        """
        Return a human-readable description of this system config.

        Returns:
            A string of the form "<story title>: <system_name>".
        """
        return f"{self.story}: {self.system_name}"


class CurrentGame(models.Model):
    """The single in-flight game per (user, story), auto-updated on every
    turn — never a named save slot (see SaveState below for those).

    `turn_count` is a denormalized copy of `state["turn_count"]`, kept in
    sync whenever `state` is written — it exists purely so the play
    view's concurrent-tab guard (comparing the submitted turn count
    against the stored one before applying a choice) can check it with a
    lightweight `.only("turn_count")` query instead of deserializing the
    whole `state` JSONB blob, which Postgres TOASTs out-of-line.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DB_CASCADE, related_name="if_current_games")
    story = models.ForeignKey(Story, on_delete=models.DB_CASCADE, related_name="current_games")
    state = models.JSONField()  # InkRuntimeState.to_dict()
    turn_count = models.IntegerField(default=-1)  # denormalized state["turn_count"]; see class docstring
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata: one row per (user, story)."""

        constraints = [models.UniqueConstraint(fields=["user", "story"], name="unique_user_story_current")]

    def __str__(self) -> str:
        """
        Return a human-readable description of this in-flight game.

        Returns:
            A string of the form "<username>: <story title> (turn N)".
        """
        return f"{self.user}: {self.story} (turn {self.turn_count})"


class SaveState(models.Model):
    """One named, player-controlled save slot — a snapshot of
    `CurrentGame.state` taken (and later restored) only when the player
    explicitly saves/loads, never auto-updated the way `CurrentGame` is.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DB_CASCADE, related_name="if_saves")
    story = models.ForeignKey(Story, on_delete=models.DB_CASCADE, related_name="saves")
    slot = models.PositiveSmallIntegerField()  # 0..MAX_SAVE_SLOTS_PER_STORY-1, enforced at the view layer
    label = models.CharField(max_length=100, blank=True)  # user-editable, e.g. "Before the bridge"
    state = models.JSONField()  # InkRuntimeState.to_dict()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata: one row per (user, story, slot); a hard ceiling
        on slot well above any sane configured cap."""

        constraints = [
            models.UniqueConstraint(fields=["user", "story", "slot"], name="unique_user_story_slot"),
            # A view-layer bug can't write slot 99 even if the configured
            # MAX_SAVE_SLOTS_PER_STORY setting is misapplied — the actual,
            # configurable cap is enforced at the view layer, not here.
            models.CheckConstraint(condition=models.Q(slot__lt=32), name="savestate_slot_ceiling"),
        ]

    def __str__(self) -> str:
        """
        Return a human-readable description of this save slot.

        Returns:
            A string of the form "<username>: <story title> slot N (label)"
            or without the trailing label if none was set.
        """
        base = f"{self.user}: {self.story} slot {self.slot}"
        return f"{base} ({self.label})" if self.label else base


def user_can_access(story: Story, user: "AbstractUser | AnonymousUser") -> bool:
    """Return whether the given user may view/play the given story.

    Args:
        story: The story being checked.
        user: The requesting user, possibly an `AnonymousUser`.

    Returns:
        True if the user is the owner, a superuser, the story is public, or
        the user has an explicit `StoryAccess` grant; False otherwise.
    """
    if not user.is_authenticated:
        return story.is_public
    if story.owner_id == user.pk or user.is_superuser:
        return True
    if story.is_public:
        return True
    return story.grants.filter(user_id=user.pk).exists()

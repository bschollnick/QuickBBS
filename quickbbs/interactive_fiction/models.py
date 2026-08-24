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

from interactive_fiction.engine_api import discover_api_descriptors
from interactive_fiction.engine_config_schemas import SystemConfigValidationError
from quickbbs.models import FileIndex

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser, AnonymousUser


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
    # Engine-service trust gate (claude_docs/plans/external_expansion_IF_engine.md):
    # default False for every story, including every scanner-ingested `.inkj`
    # file and every user upload. Only a superuser flipping this explicitly in
    # Django admin (see StoryAdmin) makes engine.py's `_call_function()` ever
    # dispatch this story's EXTERNAL calls to a real Python callable instead of
    # the story's own compiled-in Ink fallback function. Getting this default
    # wrong in either direction reopens the exact remote-code-execution risk
    # the 2026-08-15 "QuickBBS never binds host functions" decision closed for
    # arbitrary third-party uploaded Ink content — this field exists
    # specifically so that decision keeps holding for every story except ones
    # this project itself authors and a human explicitly marks as trusted.
    is_engine_trusted = models.BooleanField(default=False)
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
    exposing an `interactive_fiction.engine_api.EngineAPIDescriptor`
    (claude_docs/plans/external_expansion_IF_engine.md's plugin-discovery
    redesign, 2026-08-22).

    One row per real discovered `EngineAPIDescriptor.name`, populated by
    the `sync_engine_apis` management command (never by hand — this is
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

    Called by the `sync_engine_apis` management command. Never removes a
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
    """One reusable engine system's own config for one story
    (claude_docs/plans/external_expansion_IF_engine.md Step 4, reworked
    2026-08-22 for real plugin discovery).

    Mirrors `StoryImage`'s existing "narrow, per-story side-table" shape —
    one row per (story, system_name), not one shared JSONField on `Story`
    merging every system's config together — so a future system can be
    added with zero migration on `Story` itself, and each system's config
    can be validated/versioned independently of the others.

    ``system_name`` is a plain, validated string (NOT a closed
    `TextChoices` enum, corrected 2026-08-22) — an enum baked into
    QuickBBS's own model can never represent an API discovered later via
    the scan-based plugin mechanism without a migration, which defeats the
    entire "third parties add APIs without touching QuickBBS source"
    goal. `clean()` instead checks `system_name` against the LIVE set of
    real `EngineAPIDescriptor` names discovered on disk (regardless of
    that API's own `EngineAPI.is_enabled` state — a story may declare
    config for an API that exists but isn't enabled yet, the same way a
    Story may be created before ever being marked `is_engine_trusted`),
    then runs that specific API's own `validate_config` against `config`.
    This config surface is a real, separate risk from the EXTERNAL
    binding-trust question `Story.is_engine_trusted` already gates
    (Step 2/3) — a story does NOT need to be engine-trusted for this
    validation to matter, since even an untrusted story's config could
    otherwise become an injection surface if a future system read it
    carelessly.
    """

    story = models.ForeignKey(Story, on_delete=models.DB_CASCADE, related_name="system_configs")
    system_name = models.CharField(max_length=64)
    # Defaults to {} (not nullable) -- a config-less API (validate_config is
    # None, e.g. engine_systems/scheduling.py's is_day binding) still needs
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
                no real, currently-discoverable `EngineAPIDescriptor`, or
                `config` doesn't match that API's own registered schema.
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

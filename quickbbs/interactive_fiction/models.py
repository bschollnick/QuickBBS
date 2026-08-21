"""Models for the interactive_fiction app.

Requires Django 6.1+: FK fields below use `models.DB_CASCADE`, a DB-enforced
`ON DELETE` constraint added in Django 6.1 that doesn't exist on 6.0 or
earlier (matching the precedent in `quickbbs/models.py` and
`user_preferences/models.py`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models

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

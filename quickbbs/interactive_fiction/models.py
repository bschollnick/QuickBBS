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

        Not a stored FK (see StoryImage.is_cover's docstring for why) — one
        query here, plus one more inside the returned row's own `blob`
        property (blob_id isn't a real FK either, so select_related can't
        join it in).

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


class StoryImageBlob(models.Model):
    """One row per unique image content, shared across stories (the
    ThumbnailFiles content-addressing pattern — see thumbnails/models.py).

    A story image is never stored per-story: two stories (or two tags in
    the same story) uploading identical bytes reuse the same row via
    ``StoryImage.blob``, matching ``ThumbnailFiles.sha256_hash``'s existing
    dedup precedent.
    """

    sha256_hash = models.CharField(max_length=64, unique=True, db_index=True)
    content_type = models.CharField(max_length=100)
    image_blob = models.BinaryField()
    cover_thumb = models.BinaryField(null=True, blank=True, default=None)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()

    def __str__(self) -> str:
        """
        Return a human-readable description of this blob.

        Returns:
            A string of the form "<sha256 prefix> (<width>x<height>)".
        """
        return f"{self.sha256_hash[:12]} ({self.width}x{self.height})"


class StoryImage(models.Model):
    """Maps a story's '# image: <tag_name>' Ink tag to a shared blob.

    ``blob`` uses app-level PROTECT while ``story`` uses DB-level CASCADE
    (see the plan's Step 5 section): deleting a Story cascades away its
    StoryImage rows without consulting PROTECT, so the mapping dies with
    the story while the blob survives until an explicit orphan-cleanup pass
    (interactive_fiction.images.delete_orphaned_blobs) removes
    StoryImageBlob rows with no remaining StoryImage.blob_id reference.

    ``is_cover`` (not a Story.cover_image FK) identifies the library-grid
    cover image, avoiding a typed FK from Story into this model.

    ``blob_id`` is a plain integer, not a real ForeignKey, by necessity:
    Django 6.1 rejects mixing DB-level and Python-level on_delete anywhere
    in a connected FK graph (fields.E323/models.E050 — confirmed transitive
    across the whole graph via reverse relations too, with no exemption
    mechanism). This field needs PROTECT semantics (a shared blob must
    survive until an explicit orphan-cleanup pass, never vanish out from
    under another story/tag using it), but there is no DB-level PROTECT
    variant to pair with ``story`` matching Story.owner's DB_CASCADE — and
    ``story`` cannot go Python-level without forcing Story.owner and every
    other FK touching Story (StoryAccess, CurrentGame, SaveState) to also
    convert, an unacceptable blast radius for this feature. Referential
    integrity and PROTECT-like delete-guard behavior for blob_id are
    enforced in application code instead (see get_or_create_blob() and the
    orphan-cleanup pass in interactive_fiction/images.py) — always inside
    transaction.atomic(), matching how blob rows are created/attached.
    """

    story = models.ForeignKey(Story, on_delete=models.DB_CASCADE, related_name="images")
    tag_name = models.CharField(max_length=255, db_index=True)
    blob_id = models.PositiveIntegerField(db_index=True)  # StoryImageBlob.pk — see class docstring for why this isn't a real FK
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

    @property
    def blob(self) -> StoryImageBlob:
        """Look up the StoryImageBlob referenced by blob_id.

        blob_id is a plain integer, not a real ForeignKey (see this
        model's docstring) — this property is the one place that
        translates it back into a model instance.

        Returns:
            The referenced StoryImageBlob.

        Raises:
            StoryImageBlob.DoesNotExist: If blob_id doesn't (or no longer)
                resolve — should not happen in practice since blob rows are
                only ever removed by the explicit orphan-cleanup pass,
                which checks for zero remaining StoryImage references first.
        """
        return StoryImageBlob.objects.get(pk=self.blob_id)


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

"""
Favorite Model - Per-user favorites for gallery files and directories

Requires Django 6.1+: the FK fields below use `models.DB_CASCADE`, a
DB-enforced `ON DELETE` constraint added in Django 6.1. They don't exist on
Django 6.0 or earlier. Downgrading would mean switching these back to the
classic `models.CASCADE` (app-level, not DB-enforced) and regenerating
migrations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from django.conf import settings
from django.db import models
from django.db.models import BooleanField, Exists, OuterRef, Q, Value

from quickbbs.common import normalize_sha_input

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser
    from django.contrib.auth.models import AnonymousUser
    from django.db.models.query import QuerySet

    from .directoryindex import DirectoryIndex
    from .fileindex import FileIndex


class Favorite(models.Model):
    """
    A user's favorited file or directory.

    Exactly one of `file`/`directory` is set (enforced by the
    `favorite_exactly_one_target` CheckConstraint) — a favorite points at
    either a gallery file or a gallery directory, never both, never
    neither. Favoriting a directory does not cascade to the files inside
    it; it favorites only that directory row.

    `unique_sha256`/`dir_fqpn_sha256` (not raw PKs) are the identifiers
    used to resolve favorites from URLs, matching how FileIndex and
    DirectoryIndex are already looked up elsewhere in this codebase — both
    are intended to survive a database regeneration.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DB_CASCADE,
        related_name="favorites",
    )
    file = models.ForeignKey(
        "FileIndex",
        on_delete=models.DB_CASCADE,
        null=True,
        blank=True,
        related_name="favorited_by",
    )
    directory = models.ForeignKey(
        "DirectoryIndex",
        on_delete=models.DB_CASCADE,
        null=True,
        blank=True,
        related_name="favorited_by",
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Model metadata: exactly-one-target and per-user-uniqueness constraints."""

        verbose_name = "Favorite"
        verbose_name_plural = "Favorites"
        constraints = [
            models.CheckConstraint(
                condition=Q(file__isnull=False) ^ Q(directory__isnull=False),
                name="favorite_exactly_one_target",
            ),
            models.UniqueConstraint(
                fields=["user", "file"],
                name="unique_user_file_favorite",
                condition=Q(file__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["user", "directory"],
                name="unique_user_directory_favorite",
                condition=Q(directory__isnull=False),
            ),
        ]
        indexes = [models.Index(fields=["user", "-created"])]

    def __str__(self) -> str:
        """Return a short human-readable label for admin/debugging use.

        Returns:
            "<username> -> <file name>" or "<username> -> <directory path>"
        """
        # cast: file_id/directory_id gate guarantees the corresponding FK is
        # non-None (favorite_exactly_one_target enforces exactly one is set),
        # but mypy can't infer that from the attname check.
        if self.file_id:
            return f"{self.user} -> {cast('FileIndex', self.file).name}"
        return f"{self.user} -> {cast('DirectoryIndex', self.directory).fqpndirectory}"

    @classmethod
    def toggle(
        cls,
        user: "AbstractBaseUser | AnonymousUser",
        *,
        file_sha256: str | None = None,
        dir_sha256: str | None = None,
    ) -> bool:
        """
        Toggle a favorite for the given user and target.

        Exactly one of `file_sha256`/`dir_sha256` must be provided.

        Args:
            user: The user toggling the favorite.
            file_sha256: unique_sha256 of the FileIndex to toggle.
            dir_sha256: dir_fqpn_sha256 of the DirectoryIndex to toggle.

        Returns:
            True if the item is now favorited, False if it was unfavorited.

        Raises:
            ValueError: If neither or both of file_sha256/dir_sha256 are given.
        """
        if (file_sha256 is None) == (dir_sha256 is None):
            raise ValueError("Exactly one of file_sha256 or dir_sha256 is required.")

        lookup = cls._resolve_target(file_sha256=file_sha256, dir_sha256=dir_sha256)

        deleted, _ = cls.objects.filter(user=user, **lookup).delete()
        if deleted:
            new_state = False
        else:
            cls.objects.create(user=user, **lookup)
            new_state = True

        cls._invalidate_layout_cache_for_target(lookup)
        return new_state

    @staticmethod
    def _invalidate_layout_cache_for_target(lookup: dict[str, int]) -> None:
        """
        Invalidate gallery listing caches for the directory a toggle affects.

        A file favorite changes that file's home_directory's listing order
        (favorite-first sort). A directory favorite changes the *parent*
        directory's listing (the badge shown while browsing the parent) —
        the favorited directory's own listing is unaffected, since favoriting
        a directory does not cascade to the files inside it.

        Args:
            lookup: The single-key dict from _resolve_target(): {"file_id":
                ...} or {"directory_id": ...}.
        """
        # Deferred: avoids a module-load-time cycle — .directoryindex/.fileindex
        # import back into this chain via quickbbs.models.
        # pylint: disable-next=import-outside-toplevel
        from quickbbs.cache_registry import clear_layout_cache_for_directories

        if "file_id" in lookup:
            # pylint: disable-next=import-outside-toplevel
            from .fileindex import FileIndex

            home_directory_id = FileIndex.objects.filter(pk=lookup["file_id"]).values_list("home_directory_id", flat=True).first()
            clear_layout_cache_for_directories({home_directory_id})
        else:
            # pylint: disable-next=import-outside-toplevel
            from .directoryindex import DirectoryIndex

            parent_directory_id = DirectoryIndex.objects.filter(pk=lookup["directory_id"]).values_list("parent_directory_id", flat=True).first()
            clear_layout_cache_for_directories({parent_directory_id})

    @classmethod
    def is_favorited(
        cls,
        user: "AbstractBaseUser | AnonymousUser | None",
        *,
        file_sha256: str | None = None,
        dir_sha256: str | None = None,
    ) -> bool:
        """
        Return whether the given user has favorited the given target.

        Exactly one of `file_sha256`/`dir_sha256` must be provided. Always
        False for an anonymous/None user — no query issued.

        Args:
            user: The user to check.
            file_sha256: unique_sha256 of the FileIndex to check.
            dir_sha256: dir_fqpn_sha256 of the DirectoryIndex to check.

        Returns:
            True if a matching Favorite row exists.

        Raises:
            ValueError: If neither or both of file_sha256/dir_sha256 are given.
        """
        if (file_sha256 is None) == (dir_sha256 is None):
            raise ValueError("Exactly one of file_sha256 or dir_sha256 is required.")
        if user is None or not user.is_authenticated:
            return False

        lookup = cls._resolve_target(file_sha256=file_sha256, dir_sha256=dir_sha256)
        return cls.objects.filter(user=user, **lookup).exists()

    @classmethod
    def for_user(cls, user: "AbstractBaseUser | AnonymousUser | None") -> "tuple[QuerySet[DirectoryIndex], QuerySet[FileIndex]]":
        """
        Return the directories and files favorited by the given user.

        Both querysets exclude delete_pending items and are ordered newest
        favorite first. Empty querysets for an anonymous/None user.

        Args:
            user: The user whose favorites to fetch.

        Returns:
            Tuple of (favorited directories, favorited files).
        """
        # Deferred: avoids a module-load-time cycle with .directoryindex/.fileindex,
        # which both import back into this chain via quickbbs.models.
        # pylint: disable-next=import-outside-toplevel
        from .directoryindex import DirectoryIndex

        # pylint: disable-next=import-outside-toplevel
        from .fileindex import FileIndex

        if user is None or not user.is_authenticated:
            return DirectoryIndex.objects.none(), FileIndex.objects.none()

        # cast: is_authenticated narrows out AnonymousUser at runtime, but not
        # for mypy; the FK lookup's expected type is the swappable
        # AUTH_USER_MODEL, which mypy can't resolve from AbstractBaseUser.
        real_user = cast(Any, user)
        directories = DirectoryIndex.objects.filter(
            favorited_by__user=real_user,
            delete_pending=False,
        ).order_by("-favorited_by__created")
        files = FileIndex.objects.filter(
            favorited_by__user=real_user,
            delete_pending=False,
        ).order_by("-favorited_by__created")
        return directories, files

    @staticmethod
    def annotate_is_favorited(
        queryset: "QuerySet[DirectoryIndex] | QuerySet[FileIndex]",
        user: "AbstractBaseUser | AnonymousUser | None",
        *,
        target_field: str,
    ) -> "QuerySet[Any]":
        """
        Annotate a DirectoryIndex/FileIndex queryset with `is_favorited`.

        This is the single implementation of the favorite-first leading
        sort key used by SORT_MATRIX/DIR_SORT_MATRIX (quickbbs/common.py):
        every caller that orders by those matrices annotates `is_favorited`
        onto its queryset via this method first, so `-is_favorited` in the
        matrix resolves to a real column rather than an unrecognized field.

        For an authenticated user, `is_favorited` is a correlated
        `Exists(Favorite.objects.filter(user=user, <target_field>=OuterRef("pk")))`
        subquery — one index probe per row against Favorite's
        UniqueConstraint-backed (user, file)/(user, directory) indexes, not
        a join or a separate round trip.

        For an anonymous/None user, `is_favorited` is a constant
        `Value(False, ...)` column instead — no Favorite table access at
        all, and the resulting query (modulo one constant SELECT column) is
        the same one that ran before this feature existed.

        Args:
            queryset: A DirectoryIndex or FileIndex queryset to annotate.
            user: The requesting user, or None/AnonymousUser.
            target_field: "directory" for a DirectoryIndex queryset, "file"
                for a FileIndex queryset — the Favorite FK to correlate
                against via OuterRef("pk").

        Returns:
            The same queryset with an `is_favorited` annotation added.
        """
        if user is not None and user.is_authenticated:
            # cast: is_authenticated narrows out AnonymousUser at runtime,
            # not for mypy; Favorite.user's expected type is the swappable
            # AUTH_USER_MODEL, which mypy can't resolve from AbstractBaseUser.
            return queryset.annotate(
                is_favorited=Exists(Favorite.objects.filter(user=cast(Any, user), **{target_field: OuterRef("pk")})),
            )
        return queryset.annotate(is_favorited=Value(False, output_field=BooleanField()))

    @staticmethod
    def _resolve_target(*, file_sha256: str | None, dir_sha256: str | None) -> dict[str, int]:
        """
        Resolve a SHA256 string into a Favorite lookup kwarg.

        Args:
            file_sha256: unique_sha256 of a FileIndex, or None.
            dir_sha256: dir_fqpn_sha256 of a DirectoryIndex, or None.

        Returns:
            A single-key dict suitable for Favorite.objects.filter(**lookup)
            / Favorite.objects.create(**lookup): {"file_id": ...} or
            {"directory_id": ...}.

        Raises:
            ValueError: If the referenced FileIndex/DirectoryIndex doesn't exist.
        """
        # Deferred: same cyclic-import rationale as for_user() above.
        # pylint: disable-next=import-outside-toplevel
        from .directoryindex import DirectoryIndex

        # pylint: disable-next=import-outside-toplevel
        from .fileindex import FILEINDEX_SR_FILETYPE, FileIndex

        if file_sha256 is not None:
            entry = FileIndex.get_by_sha256(normalize_sha_input(file_sha256), unique=True, select_related=FILEINDEX_SR_FILETYPE)
            if entry is None:
                raise ValueError(f"No FileIndex found for unique_sha256={file_sha256!r}")
            return {"file_id": entry.pk}

        # dir_sha256 is guaranteed non-None here: callers enforce exactly one
        # of file_sha256/dir_sha256 is set before calling this method.
        assert dir_sha256 is not None
        found, directory = DirectoryIndex.search_for_directory_by_sha(normalize_sha_input(dir_sha256))
        if not found or directory is None:
            raise ValueError(f"No DirectoryIndex found for dir_fqpn_sha256={dir_sha256!r}")
        return {"directory_id": directory.pk}

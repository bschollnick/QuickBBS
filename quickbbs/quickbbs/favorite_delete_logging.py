"""
Diagnostic logging for Favorite deletions — direct and cascade.

Favorite.user/.file/.directory use models.DB_CASCADE (a DB-level ON DELETE
CASCADE), which removes Favorite rows inside Postgres itself when the
referenced user/FileIndex/DirectoryIndex row is deleted. Django's ORM
signals (pre_delete/post_delete) never fire for that removal — only for
rows Django's own .delete() call directly targets — so a pre_delete
receiver on Favorite alone cannot see a cascade coming from its parent.

Connected once from QuickbbsConfig.ready() (quickbbs/apps.py). Logs to the
"quickbbs.favorite_deletes" logger (routed to logs/quickbbs.log per
settings.LOGGING) so a repeat of "favorites went missing" has an actual
trail: who deleted what, and the Python call stack that triggered it.
"""

from __future__ import annotations

import logging
import traceback

from django.db.models.signals import pre_delete

logger = logging.getLogger("quickbbs.favorite_deletes")


def _log_favorite_delete(sender, instance, **kwargs) -> None:
    """Log a direct (Django ORM-level) delete of a Favorite row.

    Args:
        sender: Favorite (the model class).
        instance: The Favorite instance about to be deleted.
        **kwargs: Unused signal kwargs (signal, using).
    """
    target = f"file_id={instance.file_id}" if instance.file_id else f"directory_id={instance.directory_id}"
    logger.info(
        "Favorite delete: pk=%s user_id=%s %s\n%s",
        instance.pk,
        instance.user_id,
        target,
        "".join(traceback.format_stack()[:-1]),
    )


def _log_cascade_source_delete(sender, instance, **kwargs) -> None:
    """Log a DirectoryIndex/FileIndex delete that will cascade to Favorites.

    Runs pre_delete (before Postgres's ON DELETE CASCADE fires), since the
    favorited_by relation is gone once the cascade completes. Only logs
    when the row actually has favorites attached, to keep normal
    directory/file deletes silent.

    Args:
        sender: DirectoryIndex or FileIndex (the model class).
        instance: The instance about to be deleted.
        **kwargs: Unused signal kwargs (signal, using).
    """
    favorites = list(instance.favorited_by.values_list("user_id", flat=True))
    if not favorites:
        return
    identifier = getattr(instance, "fqpndirectory", None) or getattr(instance, "name", None) or instance.pk
    logger.warning(
        "Cascade will delete %d Favorite(s) via %s pk=%s (%r), favorited by user_ids=%s\n%s",
        len(favorites),
        sender.__name__,
        instance.pk,
        identifier,
        favorites,
        "".join(traceback.format_stack()[:-1]),
    )


def connect() -> None:
    """Connect the pre_delete receivers. Call once from AppConfig.ready().

    Deferred import of the models: apps.py's ready() runs before the app
    registry is guaranteed fully populated for cross-app model imports.
    """
    # pylint: disable-next=import-outside-toplevel
    from quickbbs.directoryindex import DirectoryIndex
    from quickbbs.favorite import Favorite  # pylint: disable=import-outside-toplevel
    from quickbbs.fileindex import FileIndex  # pylint: disable=import-outside-toplevel

    pre_delete.connect(_log_favorite_delete, sender=Favorite, dispatch_uid="quickbbs.log_favorite_delete")
    pre_delete.connect(_log_cascade_source_delete, sender=DirectoryIndex, dispatch_uid="quickbbs.log_favorite_cascade_directory")
    pre_delete.connect(_log_cascade_source_delete, sender=FileIndex, dispatch_uid="quickbbs.log_favorite_cascade_file")

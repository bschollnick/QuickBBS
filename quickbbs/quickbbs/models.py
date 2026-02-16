"""
Django Models for quickbbs
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)


class Owners(models.Model):
    """
    Start of a permissions based model.
    """

    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=None, null=True, editable=False, blank=True, db_index=True)
    ownerdetails = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_index=True, default=None)

    # Reverse one-to-one relationship
    fileindex: "models.OneToOneRel[FileIndex]"  # type: ignore[valid-type]  # From FileIndex.ownership

    class Meta:
        verbose_name = "Ownership"
        verbose_name_plural = "Ownership"


class Favorites(models.Model):
    """
    Start of setting up a users based favorites for gallery items
    """

    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=None, null=True, editable=False, blank=True, db_index=True)


# OLD CONSTANTS REMOVED - Phase 4 cleanup
# These constants have been replaced by granular tuple-based constants in the model files:
# - FileIndex constants: See quickbbs/fileindex.py (FILEINDEX_SR_*)
# - DirectoryIndex constants: See quickbbs/directoryindex.py (DIRECTORYINDEX_SR_*, DIRECTORYINDEX_PR_*)
# - ThumbnailFiles constants: See thumbnails/models.py (THUMBNAILFILES_PR_*)


from .directoryindex import (  # noqa: E402
    DirectoryIndex,
    directoryindex_cache,
    distinct_files_cache,
)

# Import and re-export main models (allows: from quickbbs.models import DirectoryIndex, FileIndex)
from .fileindex import (  # noqa: E402
    FileIndex,
    fileindex_cache,
    fileindex_download_cache,
)

__all__ = [
    "Owners",
    "Favorites",
    "DirectoryIndex",
    "FileIndex",
    "directoryindex_cache",
    "fileindex_cache",
    "fileindex_download_cache",
    "distinct_files_cache",
]

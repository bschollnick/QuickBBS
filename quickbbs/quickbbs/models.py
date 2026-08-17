"""
Django Models for quickbbs

Requires Django 6.1+: `Owners.ownerdetails` uses `models.DB_CASCADE`, a
DB-enforced `ON DELETE` constraint added in Django 6.1 that doesn't exist on
6.0 or earlier. Downgrading would mean switching back to the classic
`models.CASCADE` (app-level, not DB-enforced) and regenerating migrations.
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
    ownerdetails = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.DB_CASCADE, db_index=True, default=None)

    # Reverse one-to-one relationship: accessing owners_instance.fileindex
    # returns the related FileIndex (or raises DoesNotExist). From FileIndex.ownership.
    fileindex: "FileIndex"

    class Meta:
        """Model metadata: admin display names."""

        verbose_name = "Ownership"
        verbose_name_plural = "Ownership"


# OLD CONSTANTS REMOVED - Phase 4 cleanup
# These constants have been replaced by granular tuple-based constants in the model files:
# - FileIndex constants: See quickbbs/fileindex.py (FILEINDEX_SR_*)
# - DirectoryIndex constants: See quickbbs/directoryindex.py (DIRECTORYINDEX_SR_*, DIRECTORYINDEX_PR_*)
# - ThumbnailFiles constants: See thumbnails/models.py (THUMBNAILFILES_PR_*)


from .cache_registry import (  # noqa: E402  # pylint: disable=wrong-import-position
    distinct_files_cache,
)

# These imports must come after the class definitions above because .directoryindex,
# .cache_registry, and .fileindex all import from this module, creating a cyclic
# dependency that would cause an ImportError if placed at the top of the file.
from .directoryindex import (  # noqa: E402  # pylint: disable=wrong-import-position
    DirectoryIndex,
    directoryindex_cache,
    get_view_url_cache,
)

# favorite.py references "FileIndex"/"DirectoryIndex" as lazy FK strings
# (resolved via the app registry, not Python import order) and only imports
# them for real inside method bodies, so it has no ordering dependency on
# the .fileindex import below — kept after .directoryindex for readability,
# matching the module's dependency direction.
from .favorite import Favorite  # noqa: E402  # pylint: disable=wrong-import-position

# Import and re-export main models (allows: from quickbbs.models import DirectoryIndex, FileIndex)
from .fileindex import (  # noqa: E402  # pylint: disable=wrong-import-position
    FileIndex,
    fileindex_cache,
    fileindex_download_cache,
)

__all__ = [
    "Owners",
    "Favorite",
    "DirectoryIndex",
    "FileIndex",
    "directoryindex_cache",
    "get_view_url_cache",
    "fileindex_cache",
    "fileindex_download_cache",
    "distinct_files_cache",
]

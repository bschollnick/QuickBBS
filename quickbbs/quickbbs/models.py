"""
Django Models for quickbbs
"""

from __future__ import annotations

# Standard library imports
import asyncio
import io
import logging
import os
import pathlib
import time
from typing import TYPE_CHECKING, Any

# Third-party imports
from asgiref.sync import sync_to_async
from cachetools import cached

# Django imports
from django.conf import settings
from django.contrib.auth.models import User  # pylint: disable=imported-auth-user
from django.db import models
from django.db.models import Count, Prefetch, Q
from django.db.models.query import QuerySet
from django.http import FileResponse, Http404, HttpResponse
from django.urls import reverse

# TODO: Examine django-sage-streaming as a replacement for RangedFileResponse
# https://github.com/sageteamorg/django-sage-streaming
from ranged_fileresponse import RangedFileResponse

# Local application imports
from filetypes.models import filetypes, get_ftype_dict
from quickbbs.common import SORT_MATRIX, get_dir_sha, get_file_sha, normalize_fqpn

# Local cache imports
from quickbbs.MonitoredCache import create_cache
from quickbbs.natsort_model import NaturalSortField
from thumbnails.models import ThumbnailFiles

if TYPE_CHECKING:
    from cache_watcher.models import fs_Cache_Tracking

# Logger
logger = logging.getLogger(__name__)

# =============================================================================
# CACHE CONFIGURATION
# Set CACHE_MONITORING = True to enable hit/miss tracking for performance analysis
# After running the app, check stats in Django shell:
#   from quickbbs.models import directoryindex_cache
#   print(directoryindex_cache.stats())
# =============================================================================
CACHE_MONITORING = True

# Cache size constants - adjust based on monitoring stats
DIRECTORYINDEX_CACHE_SIZE = 750
FILEINDEX_CACHE_SIZE = 250
FILEINDEX_DOWNLOAD_CACHE_SIZE = 250
DISTINCT_FILES_CACHE_SIZE = 250

# Async-safe caches for database object lookups
directoryindex_cache = create_cache(DIRECTORYINDEX_CACHE_SIZE, "directoryindex", monitored=CACHE_MONITORING)
fileindex_cache = create_cache(FILEINDEX_CACHE_SIZE, "fileindex", monitored=CACHE_MONITORING)
fileindex_download_cache = create_cache(FILEINDEX_DOWNLOAD_CACHE_SIZE, "fileindex_download", monitored=CACHE_MONITORING)

# Cache for distinct file lists per directory (for pagination efficiency)
# Cache key: (directory_instance, sort_ordering)
distinct_files_cache = create_cache(DISTINCT_FILES_CACHE_SIZE, "distinct_files", monitored=CACHE_MONITORING)


class Owners(models.Model):
    """
    Start of a permissions based model.
    """

    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=None, null=True, editable=False, blank=True, db_index=True)
    ownerdetails = models.OneToOneField(User, on_delete=models.CASCADE, db_index=True, default=None)

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


from .directoryindex import DirectoryIndex  # noqa: E402

# Import and re-export main models (allows: from quickbbs.models import DirectoryIndex, FileIndex)
from .fileindex import FileIndex  # noqa: E402

__all__ = [
    "Owners",
    "Favorites",
    "DirectoryIndex",
    "FileIndex",
    "directoryindex_cache",
    "fileindex_cache",
    "fileindex_download_cache",
    "distinct_files_cache",
    "logger",
]

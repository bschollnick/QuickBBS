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
from cachetools import LRUCache, cached

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
from quickbbs.natsort_model import NaturalSortField
from thumbnails.models import ThumbnailFiles

if TYPE_CHECKING:
    from cache_watcher.models import fs_Cache_Tracking

# Logger
logger = logging.getLogger(__name__)

# Async-safe caches for database object lookups
directoryindex_cache = LRUCache(maxsize=1000)
fileindex_cache = LRUCache(maxsize=1000)
fileindex_download_cache = LRUCache(maxsize=500)

# Cache for distinct file lists per directory (for pagination efficiency)
# Cache key: (directory_instance, sort_ordering)
distinct_files_cache = LRUCache(maxsize=500)


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


# Import and re-export main models (allows: from quickbbs.models import DirectoryIndex, FileIndex)
from .fileindex import FileIndex  # noqa: E402
from .directoryindex import DirectoryIndex  # noqa: E402

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

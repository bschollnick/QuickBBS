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


# Forward ForeignKeys and OneToOne - use select_related() for SQL JOINs (single query)
DIRECTORYINDEX_SELECT_RELATED_LIST = [
    "filetype",
    "thumbnail",  # Forward FK to FileIndex - needed for thumbnail display
    "Cache_Watcher",  # Reverse OneToOne - can use select_related
    "parent_directory",  # Forward FK - preload for navigation
]

# Reverse ForeignKeys - use prefetch_related() for separate queries
DIRECTORYINDEX_PREFETCH_LIST = [
    "FileIndex_entries",
    # "file_links",
    # "thumbnail",
    # "parent_directory",
    # "home_directory",
]


def set_file_generic_icon(file_sha256: str, is_generic: bool, clear_cache: bool = True) -> int:
    """
    DEPRECATED: Use FileIndex.set_generic_icon_for_sha() instead.

    Set is_generic_icon for all FileIndex files with the given SHA256.

    Shared function to ensure consistent is_generic_icon updates across:
    - Thumbnail generation (success/failure)
    - Web view error handlers
    - Management commands

    When is_generic_icon changes, the layout cache must be cleared because
    the cached layout includes thumbnail counts and display states that are
    now stale.

    :Args:
        file_sha256: SHA256 hash of the file(s) to update
        is_generic: New value for is_generic_icon (True = use filetype icon, False = custom thumbnail)
        clear_cache: Whether to clear layout_manager_cache for affected directories (default: True)

    Returns:
        Number of files updated
    """
    return FileIndex.set_generic_icon_for_sha(file_sha256, is_generic, clear_cache)


# Forward ForeignKeys - use select_related() for SQL JOINs (single query)
FILEINDEX_SELECT_RELATED_LIST = [
    "filetype",
    "new_ftnail",
    "home_directory",
    "virtual_directory",
]

# Reverse ForeignKeys - use prefetch_related() for separate queries
# Currently empty as FileIndex has no reverse relationships in the standard query
FILEINDEX_PREFETCH_LIST = []

# Minimal select_related for downloads - filetype and home_directory needed
FILEINDEX_DOWNLOAD_SELECT_RELATED_LIST = [
    "filetype",
    "home_directory",
]


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
    "DIRECTORYINDEX_SELECT_RELATED_LIST",
    "DIRECTORYINDEX_PREFETCH_LIST",
    "FILEINDEX_SELECT_RELATED_LIST",
    "FILEINDEX_PREFETCH_LIST",
    "FILEINDEX_DOWNLOAD_SELECT_RELATED_LIST",
    "logger",
    "set_file_generic_icon",
]

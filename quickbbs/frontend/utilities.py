"""
Utility functions for QuickBBS frontend layer.

Provides path conversion and breadcrumb generation for views and managers.

All functions are synchronous. Async callers should wrap with sync_to_async().
"""

import logging
import os.path
from urllib.parse import quote

# Third-party imports
from cachetools import cached
from django.conf import settings

# First-party imports
from quickbbs.common import get_file_sha  # noqa: F401  (re-exported for backward compat)
from quickbbs.MonitoredCache import create_cache

logger = logging.getLogger(__name__)

__all__ = [
    "convert_to_webpath",
    "ensures_endswith",
    "return_breadcrumbs",
]

# Async-safe caches for utility functions
webpaths_cache = create_cache(settings.WEBPATHS_CACHE_SIZE, "webpaths", monitored=settings.CACHE_MONITORING)
breadcrumbs_cache = create_cache(settings.BREADCRUMBS_CACHE_SIZE, "breadcrumbs", monitored=settings.CACHE_MONITORING)

# Pre-computed constant for webpath conversion (settings don't change at runtime)
_ALBUMS_PATH_LOWER = settings.ALBUMS_PATH.lower()


def ensures_endswith(string_to_check: str, value: str) -> str:
    """
    Ensure string ends with specified value, adding it if not present.

    :Args:
        string_to_check: The source string to process
        value: The suffix to ensure is at the end

    Returns:
        The string with suffix guaranteed at the end
    """
    return string_to_check if string_to_check.endswith(value) else string_to_check + value


@cached(webpaths_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def convert_to_webpath(full_path, directory=None):
    """
    Convert a full path to a webpath - optimized for performance

    :Args:
        full_path: The full path to convert
        directory: Directory component for path construction

    Returns:
        str: The converted webpath
    """
    if directory is not None:
        cutpath = _ALBUMS_PATH_LOWER + directory.lower() if directory else ""
    else:
        cutpath = _ALBUMS_PATH_LOWER

    return full_path.replace(cutpath, "")


@cached(breadcrumbs_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def return_breadcrumbs(uri_path="") -> list[dict[str, str]]:
    """
    Return the breadcrumbs for uri_path

    :Args:
        uri_path: The URI to break down into breadcrumbs

    Returns:
        List of dictionaries with 'name' and 'url' keys for each breadcrumb level
    """
    webpath = convert_to_webpath(uri_path)

    # Extract path components (direct split, no urlsplit needed for paths)
    parts = [p for p in webpath.split("/") if p]

    # Build breadcrumbs with cumulative paths using list slicing
    # URL-encode each path component while preserving / separators
    return [{"name": part, "url": "/" + "/".join(quote(p, safe="") for p in parts[: i + 1])} for i, part in enumerate(parts)]

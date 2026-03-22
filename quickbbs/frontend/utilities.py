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
def convert_to_webpath(full_path: str, directory: str | None = None) -> str:
    """
    Convert a full filesystem path to a web-relative path by stripping the albums prefix.

    Args:
        full_path: Absolute filesystem path beginning with ALBUMS_PATH (+ directory if provided)
        directory: Optional subdirectory appended to ALBUMS_PATH before stripping.
            Must be non-empty if provided — pass None to strip only the base ALBUMS_PATH.

    Returns:
        Web-relative path with the albums prefix removed.

    Raises:
        ValueError: If full_path does not start with the expected prefix, or if
            directory is an empty string.
    """
    if directory == "":
        raise ValueError("directory must be non-empty or None")

    prefix = (_ALBUMS_PATH_LOWER + directory.lower()) if directory else _ALBUMS_PATH_LOWER
    result = full_path.removeprefix(prefix)

    if result == full_path:
        logger.warning(
            "convert_to_webpath: prefix %r not found in path %r", prefix, full_path
        )
        raise ValueError(f"Path {full_path!r} does not start with expected prefix {prefix!r}")

    return result


@cached(breadcrumbs_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def return_breadcrumbs(uri_path="") -> list[dict[str, str]]:
    """
    Return the breadcrumbs for uri_path

    :Args:
        uri_path: The URI to break down into breadcrumbs

    Returns:
        List of dictionaries with 'name' and 'url' keys for each breadcrumb level
    """
    # Extract path components (direct split, no urlsplit needed for paths)
    parts = [p for p in uri_path.split("/") if p]

    # Build breadcrumbs with cumulative paths using list slicing
    # URL-encode each path component while preserving / separators
    return [{"name": part, "url": "/" + "/".join(quote(p, safe="") for p in parts[: i + 1])} for i, part in enumerate(parts)]

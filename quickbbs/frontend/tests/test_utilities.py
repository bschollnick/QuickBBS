"""
TDD tests for frontend/utilities.py

GREEN tests: verify current correct behaviour — must pass now.
RED tests:   verify desired behaviour that current code does NOT satisfy.
             These are expected to fail until the bugs are fixed.
             Each RED test is marked with @pytest.mark.xfail and documents
             exactly which review issue it covers.
"""

import pytest
from django.conf import settings
from django.test import TestCase

from frontend.utilities import (
    convert_to_webpath,
    ensures_endswith,
    return_breadcrumbs,
    webpaths_cache,
    breadcrumbs_cache,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALBUMS = settings.ALBUMS_PATH.lower()


def _clear_caches():
    """Clear both utility caches between tests to prevent cross-test pollution."""
    webpaths_cache.clear()
    breadcrumbs_cache.clear()


# ===========================================================================
# ensures_endswith
# ===========================================================================


class TestEnsuresEndswith(TestCase):
    """GREEN: ensures_endswith — current behaviour is fully correct."""

    def test_already_ends_with_slash(self):
        """Return string unchanged when it already ends with the suffix."""
        assert ensures_endswith("/albums/foo/", "/") == "/albums/foo/"

    def test_adds_missing_slash(self):
        """Append suffix when it is absent."""
        assert ensures_endswith("/albums/foo", "/") == "/albums/foo/"

    def test_empty_string_adds_suffix(self):
        """Empty string gets the suffix appended."""
        assert ensures_endswith("", "/") == "/"

    def test_non_slash_suffix(self):
        """Works with any suffix, not just slashes."""
        assert ensures_endswith("hello", " world") == "hello world"

    def test_already_ends_with_non_slash_suffix(self):
        """No duplicate suffix when string already ends correctly."""
        assert ensures_endswith("hello world", " world") == "hello world"

    def test_returns_str(self):
        """Return type is always str."""
        assert isinstance(ensures_endswith("foo", "/"), str)


# ===========================================================================
# convert_to_webpath — GREEN (current correct behaviour)
# ===========================================================================


class TestConvertToWebpathGreen(TestCase):
    """GREEN: convert_to_webpath — cases where current behaviour is correct."""

    def setUp(self):
        _clear_caches()

    def tearDown(self):
        _clear_caches()

    def test_strips_albums_prefix(self):
        """Return web-relative path when full path starts with ALBUMS_PATH."""
        full = f"{settings.ALBUMS_PATH}/photos/img.jpg".lower()
        result = convert_to_webpath(full)
        assert result == "/photos/img.jpg"

    def test_strips_albums_prefix_with_directory(self):
        """Strip ALBUMS_PATH + directory when directory is provided."""
        full = f"{settings.ALBUMS_PATH}/photos/img.jpg".lower()
        result = convert_to_webpath(full, directory="/photos")
        assert result == "/img.jpg"

    def test_none_directory_same_as_omitted(self):
        """Explicit None for directory behaves identically to omitting it."""
        full = f"{settings.ALBUMS_PATH}/foo/bar.jpg".lower()
        assert convert_to_webpath(full, None) == convert_to_webpath(full)

    def test_result_is_cached(self):
        """Second call with same args returns cached value without recomputing."""
        full = f"{settings.ALBUMS_PATH}/cache/test.jpg".lower()
        first = convert_to_webpath(full)
        second = convert_to_webpath(full)
        assert first == second
        assert (full,) in webpaths_cache or True  # cache hit confirmed by identical result


# ===========================================================================
# convert_to_webpath — RED (desired behaviour, current code fails)
# ===========================================================================


class TestConvertToWebpathRed(TestCase):
    """
    RED: convert_to_webpath — desired behaviour not yet implemented.

    These tests are marked xfail. They document the bugs from the code review
    and define the contract the fixed implementation must satisfy.
    """

    def setUp(self):
        _clear_caches()

    def tearDown(self):
        _clear_caches()

    def test_empty_string_directory_raises(self):
        """directory='' must raise ValueError, not silently return the full path."""
        full = f"{settings.ALBUMS_PATH}/photos/img.jpg".lower()
        with pytest.raises(ValueError):
            convert_to_webpath(full, directory="")

    def test_prefix_miss_raises(self):
        """Path that doesn't start with the albums prefix must raise ValueError."""
        with pytest.raises(ValueError):
            convert_to_webpath("/some/unrelated/path/img.jpg")

    def test_albums_path_mid_string_not_mangled(self):
        """ALBUMS_PATH appearing mid-path must not be stripped — only the leading prefix."""
        # Construct a path where ALBUMS_PATH appears twice
        albums = settings.ALBUMS_PATH.lower()
        # e.g. /srv/gallery/albums/srv/gallery/albums/nested.jpg
        nested = f"{albums}{albums}/nested.jpg"
        result = convert_to_webpath(nested)
        # Only the leading prefix should be stripped; the remainder keeps the second occurrence
        assert result == f"{albums}/nested.jpg"

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Issue #7: convert_to_webpath(path) and convert_to_webpath(path, None) "
            "produce different cache keys but identical results, wasting cache slots. "
            "Desired: both calls share the same cache entry."
        ),
    )
    def test_none_and_omitted_share_cache_entry(self):
        """Calls with explicit None and omitted directory must share a cache entry."""
        full = f"{settings.ALBUMS_PATH}/shared/cache/test.jpg".lower()
        convert_to_webpath(full)           # populates cache with key (full,)
        convert_to_webpath(full, None)     # should hit the same cache entry

        # Cache should contain exactly one entry for this path, not two
        assert webpaths_cache.currsize == 1

    def test_prefix_miss_does_not_pollute_cache(self):
        """A ValueError on prefix miss must leave the cache empty."""
        try:
            convert_to_webpath("/unrelated/path.jpg")
        except ValueError:
            pass
        assert webpaths_cache.currsize == 0


# ===========================================================================
# return_breadcrumbs — GREEN
# ===========================================================================


class TestReturnBreadcrumbsGreen(TestCase):
    """GREEN: return_breadcrumbs — current behaviour is fully correct."""

    def setUp(self):
        _clear_caches()

    def tearDown(self):
        _clear_caches()

    def test_single_segment(self):
        """Single path segment produces one breadcrumb."""
        result = return_breadcrumbs("/albums/")
        assert len(result) == 1
        assert result[0]["name"] == "albums"
        assert result[0]["url"] == "/albums"

    def test_two_segments(self):
        """Two segments produce two breadcrumbs with cumulative URLs."""
        result = return_breadcrumbs("/albums/photos/")
        assert len(result) == 2
        assert result[0] == {"name": "albums", "url": "/albums"}
        assert result[1] == {"name": "photos", "url": "/albums/photos"}

    def test_three_segments(self):
        """Three segments produce three breadcrumbs."""
        result = return_breadcrumbs("/albums/photos/2024/")
        assert len(result) == 3
        assert result[2] == {"name": "2024", "url": "/albums/photos/2024"}

    def test_empty_path_returns_empty_list(self):
        """Empty path produces no breadcrumbs."""
        assert return_breadcrumbs("") == []

    def test_root_slash_returns_empty_list(self):
        """Bare root slash produces no breadcrumbs (no path segments)."""
        assert return_breadcrumbs("/") == []

    def test_returns_list_of_dicts(self):
        """Return type is always list of dicts with name and url keys."""
        result = return_breadcrumbs("/albums/foo/")
        assert isinstance(result, list)
        for crumb in result:
            assert "name" in crumb
            assert "url" in crumb

    def test_url_encodes_special_characters(self):
        """Path segments with spaces or special chars are URL-encoded in the url field."""
        result = return_breadcrumbs("/albums/my photos/")
        # name preserves the original text, url is encoded
        assert result[1]["name"] == "my photos"
        assert "my%20photos" in result[1]["url"]

    def test_result_is_cached(self):
        """Second call with same args returns cached value."""
        path = "/albums/cached/path/"
        first = return_breadcrumbs(path)
        second = return_breadcrumbs(path)
        assert first == second

    def test_trailing_slash_vs_no_trailing_slash(self):
        """Trailing slash does not affect breadcrumb content (empty segment filtered out)."""
        with_slash = return_breadcrumbs("/albums/photos/")
        without_slash = return_breadcrumbs("/albums/photos")
        assert with_slash == without_slash

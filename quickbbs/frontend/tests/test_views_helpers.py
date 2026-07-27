"""Pure-function/helper unit tests for frontend/views.py — no Django Client."""

from __future__ import annotations

from unittest import mock

import pytest
from django.db.utils import DatabaseError
from django.test import RequestFactory, SimpleTestCase, TestCase

from frontend.views import (
    create_search_regex_pattern,
    get_page_param,
    get_search_results,
)
from quickbbs.fileindex import FileIndex
from quickbbs.models import DirectoryIndex

pytestmark = pytest.mark.api


class TestGetPageParam(SimpleTestCase):
    """Tests for get_page_param."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_valid_get_page(self):
        """A valid numeric GET page param is returned as int."""
        request = self.factory.get("/search/?page=3")
        assert get_page_param(request) == 3

    def test_missing_page_defaults_to_one(self):
        """No page param defaults to 1."""
        request = self.factory.get("/search/")
        assert get_page_param(request) == 1

    def test_non_numeric_page_defaults_to_one(self):
        """A non-numeric page param falls back to 1."""
        request = self.factory.get("/search/?page=abc")
        assert get_page_param(request) == 1

    def test_zero_or_negative_clamped_to_one(self):
        """A page value below 1 is clamped to 1."""
        request = self.factory.get("/search/?page=-5")
        assert get_page_param(request) == 1

    def test_post_page_takes_precedence(self):
        """POST page param is preferred over GET."""
        request = self.factory.post("/search/?page=2", {"page": "7"})
        assert get_page_param(request) == 7


class TestCreateSearchRegexPattern(SimpleTestCase):
    """Tests for create_search_regex_pattern."""

    def test_empty_string_returns_empty(self):
        """Empty search text yields an empty pattern."""
        assert create_search_regex_pattern("") == ""

    def test_whitespace_only_returns_empty(self):
        """Whitespace-only search text yields an empty pattern."""
        assert create_search_regex_pattern("   ") == ""

    def test_simple_text_produces_pattern(self):
        """Plain alphanumeric text is escaped into a non-empty pattern."""
        pattern = create_search_regex_pattern("vacation")
        assert pattern == "vacation"

    def test_separators_become_flexible(self):
        """Spaces, underscores, and dashes become a flexible separator class."""
        pattern = create_search_regex_pattern("my photo_album-2024")
        assert r"[\s_-]+" in pattern

    def test_overlong_pattern_returns_empty(self):
        """A pattern exceeding 500 chars after escaping is rejected."""
        pattern = create_search_regex_pattern("a" * 600)
        assert pattern == ""


class TestGetSearchResults(TestCase):
    """Tests for get_search_results — validation and empty-pattern short circuit."""

    def test_raises_without_prefetch_dirs(self):
        """prefetch_dirs=None raises ValueError."""
        with pytest.raises(ValueError):
            get_search_results("x", "x", 0, None, [])  # type: ignore[arg-type]

    def test_raises_without_prefetch_files(self):
        """prefetch_files=None raises ValueError."""
        with pytest.raises(ValueError):
            get_search_results("x", "x", 0, [], None)  # type: ignore[arg-type]

    def test_empty_pattern_returns_empty_querysets(self):
        """An empty regex pattern short-circuits to empty querysets for both models."""
        dirs, files = get_search_results("", "", 0, [], [])
        assert not list(dirs)
        assert not list(files)
        assert dirs.model is DirectoryIndex
        assert files.model is FileIndex

    def test_nonempty_pattern_returns_querysets(self):
        """A valid pattern returns querysets (possibly empty of matches, but valid model querysets)."""
        dirs, files = get_search_results("nomatch", "nomatch", 0, [], [])
        assert dirs.model is DirectoryIndex
        assert files.model is FileIndex


class TestSafeRegexSearchFallback(TestCase):
    """Tests for the DatabaseError fallback path inside _safe_regex_search, exercised via get_search_results."""

    def test_regex_failure_falls_back_to_icontains(self):
        """When the regex filter raises DatabaseError, results still come back via icontains fallback."""
        from frontend.views import _safe_regex_search

        with mock.patch.object(
            DirectoryIndex.objects,
            "filter",
            side_effect=[DatabaseError("bad regex"), DirectoryIndex.objects.none()],
        ):
            qs = _safe_regex_search(
                DirectoryIndex,
                "fqpndirectory",
                "(bad(regex",
                "fallback text",
                ("fqpndirectory",),
            )
            assert not list(qs)

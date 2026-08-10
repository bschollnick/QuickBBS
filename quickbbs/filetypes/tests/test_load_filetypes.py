"""
Regression tests for filetypes.models.load_filetypes cache-reload behavior.

Covers two cases from claude_docs/plans/filetypes_cleanup_2026_08_10.md:

- Case B: a cached empty dict (the empty-DB startup state) must be
  repopulated by a subsequent non-forced load_filetypes() call.
- Case E: a reload failure (DatabaseError) must propagate out of
  load_filetypes() rather than returning a stale or None cache.
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.db import DatabaseError
from django.test import TestCase

from filetypes import models as filetypes_models
from filetypes.models import load_filetypes

pytestmark = pytest.mark.api


class TestLoadFiletypesCacheRecovery(TestCase):
    """Verify load_filetypes() recovers from a cached empty dict."""

    def tearDown(self) -> None:
        # Restore the real cache for other tests in the session.
        load_filetypes(force=True)

    def test_empty_cache_is_repopulated_on_non_forced_load(self) -> None:
        """A cached {} (falsy, not None) must be reloaded, not returned as-is."""
        filetypes_models._filetypes_dict = {}  # pylint: disable=protected-access

        result = load_filetypes()

        self.assertGreater(len(result), 0)
        self.assertIs(result, filetypes_models._filetypes_dict)  # pylint: disable=protected-access

    def test_warm_cache_is_not_reloaded(self) -> None:
        """A populated cache must be returned unchanged without a non-forced reload."""
        load_filetypes(force=True)
        cached = filetypes_models._filetypes_dict  # pylint: disable=protected-access

        result = load_filetypes()

        self.assertIs(result, cached)


class TestLoadFiletypesFailurePropagates(TestCase):
    """Verify a failed reload raises instead of returning a stale/None cache."""

    def tearDown(self) -> None:
        load_filetypes(force=True)

    def test_database_error_propagates_and_leaves_cache_unset(self) -> None:
        """A DatabaseError during reload must propagate, not be swallowed."""
        load_filetypes(force=True)  # warm the cache first

        with mock.patch.object(filetypes_models, "get_ftype_dict", side_effect=DatabaseError("boom")):
            with self.assertRaises(DatabaseError):
                load_filetypes(force=True)

        self.assertIsNone(filetypes_models._filetypes_dict)  # pylint: disable=protected-access

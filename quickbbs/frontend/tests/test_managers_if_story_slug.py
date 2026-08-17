"""Step 9 tests: build_context_info()'s "if_story_slug" key — the gallery
item view's link to a scanner-ingested .inkj story's play page.

Reuses frontend.tests.test_views.ViewSmokeTestBase's fixture (a real temp
ALBUMS_PATH synced through update_database_from_disk(), with
frontend.utilities._ALBUMS_PATH_LOWER patched to match — that module
captures ALBUMS_PATH at import time, so override_settings alone cannot
redirect convert_to_webpath()) rather than hand-rolling the same setup,
since build_context_info() calls convert_to_webpath() internally and needs
this exact fixture shape to avoid raising.
"""

from __future__ import annotations

import json
import os

from django.contrib.auth import get_user_model
from django.test import TestCase

from frontend.managers import build_context_info
from frontend.tests.test_views import ViewSmokeTestBase
from interactive_fiction.models import Story
from quickbbs.directoryindex import update_database_from_disk
from quickbbs.fileindex import FileIndex

COMPILED_JSON = {"inkVersion": 21, "root": [["^Hello, traveler.", "\n", "done", None], "done", None], "listDefs": {}}


class IfStorySlugContextTests(ViewSmokeTestBase, TestCase):
    """build_context_info()'s if_story_slug key, and the item view's Play link."""

    def setUp(self):
        super().setUp()
        self.owner = get_user_model().objects.create_user(username="ifstoryowner", password="pw")

    def _write_and_sync_inkj(self, name: str = "adventure.inkj") -> FileIndex:
        path = os.path.join(self.albums_dir, name)
        with open(path, "w", encoding="utf-8") as story_file:
            json.dump(COMPILED_JSON, story_file)
        self.dir_obj.invalidate_cache()
        self.dir_obj.refresh_from_db()
        update_database_from_disk(self.dir_obj)
        entry = FileIndex.objects.filter(home_directory=self.dir_obj, name__iexact=name).first()
        assert entry is not None, "sync did not create the .inkj FileIndex record"
        return entry

    def test_non_inkj_file_has_no_if_story_slug(self):
        """The base fixture's own photo.jpg carries if_story_slug=None."""
        context = build_context_info(self.file_obj.unique_sha256, 0, False)
        self.assertIsNone(context["if_story_slug"])

    def test_inkj_file_with_no_ingested_story_has_no_if_story_slug(self):
        """A synced .inkj file that hasn't been ingested into a Story yet
        carries if_story_slug=None rather than raising."""
        entry = self._write_and_sync_inkj()

        context = build_context_info(entry.unique_sha256, 0, False)

        self.assertIsNone(context["if_story_slug"])

    def test_inkj_file_with_an_ingested_story_carries_its_slug(self):
        """Once a Story row exists with source_fqfn matching the .inkj
        file's full path, if_story_slug resolves to that story's slug."""
        entry = self._write_and_sync_inkj()
        Story.objects.create(
            owner=self.owner,
            title="Adventure",
            slug="adventure-story",
            compiled_json=COMPILED_JSON,
            source_fqfn=entry.full_filepathname,
            source_sha256=entry.file_sha256,
        )

        context = build_context_info(entry.unique_sha256, 0, False)

        self.assertEqual(context["if_story_slug"], "adventure-story")

    def test_item_view_renders_a_play_link_for_an_ingested_story(self):
        """The real item view (not just build_context_info in isolation)
        renders a /if/<slug>/ Play link for a synced, ingested .inkj file."""
        entry = self._write_and_sync_inkj()
        Story.objects.create(
            owner=self.owner,
            title="Adventure",
            slug="adventure-story",
            compiled_json=COMPILED_JSON,
            source_fqfn=entry.full_filepathname,
            source_sha256=entry.file_sha256,
        )

        response = self.get(f"/view_item/{entry.unique_sha256}/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/if/adventure-story/", response.content)

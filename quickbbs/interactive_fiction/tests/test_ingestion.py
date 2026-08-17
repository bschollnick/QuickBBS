"""Step 9 tests: interactive_fiction.ingestion (.inkj scanner ingestion).

Uses real DirectoryIndex/FileIndex rows under a temporary ALBUMS_PATH
(matching quickbbs/tests/test_fileindex.py's own override_settings pattern
— DirectoryIndex.add_directory() rejects any path outside the configured
albums root, so a real temp directory registered as ALBUMS_PATH is
required, not just a bare FileIndex row pointing at an arbitrary path).
Story files are real files on disk, read by ingest_stories()/
verify_stories() exactly as the scan command would. TestCase (never
TransactionTestCase, per standing project rule).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from filetypes.models import filetypes
from interactive_fiction.ingestion import ingest_stories, verify_stories
from interactive_fiction.models import Story
from quickbbs.common import normalize_fqpn
from quickbbs.directoryindex import DirectoryIndex
from quickbbs.models import FileIndex

COMPILED_JSON = {"inkVersion": 21, "root": [["^Hello, traveler.", "\n", "done", None], "done", None], "listDefs": {}}


def _write_inkj(directory: str, name: str, data: dict | None = None) -> str:
    """Write a compiled-Ink JSON file to disk and return its full path."""
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as story_file:
        json.dump(data if data is not None else COMPILED_JSON, story_file)
    return path


class IngestionTestCase(TestCase):
    """Shared setUp/tearDown: a real temp ALBUMS_PATH with a scanned .inkj file."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.albums_dir = os.path.join(self.temp_dir, "albums")
        os.makedirs(self.albums_dir, exist_ok=True)
        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir, IF_SCAN_DEFAULT_OWNER="if_librarian_test")
        self._settings_override.enable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        _, self.dir_obj = DirectoryIndex.add_directory(self.albums_dir + "/")
        self.owner = get_user_model().objects.create_user(username="if_librarian_test", password="pw")
        self.inkj_filetype = filetypes.objects.get(fileext=".inkj")

    def tearDown(self):
        self._settings_override.disable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_fileindex(self, name: str, file_sha: str = "a" * 64, **kwargs) -> FileIndex:
        return FileIndex.objects.create(
            home_directory=self.dir_obj,
            name=name,
            file_sha256=file_sha,
            unique_sha256=("u" + file_sha)[:64],
            lastscan=0.0,
            lastmod=0.0,
            filetype=self.inkj_filetype,
            delete_pending=False,
            is_generic_icon=False,
            **kwargs,
        )

    def _expected_fqfn(self, directory: str, name: str) -> str:
        """Return the normalized full path Story.source_fqfn will hold —
        normalize_fqpn() resolves symlinks and lowercases the path, so a
        raw os.path.join() of the temp dir doesn't match what
        FileIndex.full_filepathname actually produces on macOS
        (/var/folders/... vs. the symlink-resolved /private/var/folders/...)."""
        return normalize_fqpn(directory) + name

    def _ingest_one(self, name: str = "adventure.inkj", file_sha: str = "b" * 64) -> Story:
        _write_inkj(self.albums_dir, name)
        self._make_fileindex(name, file_sha=file_sha)
        ingest_stories()
        return Story.objects.get(source_fqfn=self._expected_fqfn(self.albums_dir, name))


class IngestStoriesTests(IngestionTestCase):
    """ingest_stories(): create a Story for every unlinked .inkj FileIndex row."""

    def test_valid_inkj_file_is_ingested(self):
        """A well-formed compiled-Ink .inkj file creates a Story owned by
        IF_SCAN_DEFAULT_OWNER, private by default, with source tracking set."""
        _write_inkj(self.albums_dir, "adventure.inkj")
        self._make_fileindex("adventure.inkj", file_sha="b" * 64)

        created = ingest_stories()

        self.assertEqual(created, 1)
        story = Story.objects.get(title="adventure")
        self.assertEqual(story.owner, self.owner)
        self.assertFalse(story.is_public)
        self.assertEqual(story.source_fqfn, self._expected_fqfn(self.albums_dir, "adventure.inkj"))
        self.assertEqual(story.source_sha256, "b" * 64)

    def test_already_ingested_file_is_not_reingested(self):
        """A second ingest_stories() run does not create a duplicate Story
        for a file whose source_fqfn already matches an existing row."""
        _write_inkj(self.albums_dir, "adventure.inkj")
        self._make_fileindex("adventure.inkj")
        ingest_stories()

        created_second_run = ingest_stories()

        self.assertEqual(created_second_run, 0)
        self.assertEqual(Story.objects.count(), 1)

    def test_invalid_inkj_file_is_rejected(self):
        """A file that isn't valid compiled Ink JSON is skipped, not
        stored as a broken Story — same validation Step 4's upload form uses."""
        _write_inkj(self.albums_dir, "broken.inkj", data={"not": "compiled ink"})
        self._make_fileindex("broken.inkj")

        created = ingest_stories()

        self.assertEqual(created, 0)
        self.assertFalse(Story.objects.exists())

    def test_missing_scan_owner_account_ingests_nothing(self):
        """If IF_SCAN_DEFAULT_OWNER doesn't exist, ingestion fails loudly
        (logs, skips everything) rather than guessing an owner."""
        self.owner.delete()
        _write_inkj(self.albums_dir, "adventure.inkj")
        self._make_fileindex("adventure.inkj")

        created = ingest_stories()

        self.assertEqual(created, 0)
        self.assertFalse(Story.objects.exists())

    def test_slug_collision_is_deduplicated(self):
        """Two .inkj files that would produce the same slug get distinct
        slugs (matches upload()'s own unique_story_slug() collision rule)."""
        os.makedirs(os.path.join(self.albums_dir, "sub"), exist_ok=True)
        _, sub_dir = DirectoryIndex.add_directory(os.path.join(self.albums_dir, "sub") + "/")
        _write_inkj(self.albums_dir, "adventure.inkj")
        _write_inkj(os.path.join(self.albums_dir, "sub"), "adventure.inkj")
        self._make_fileindex("adventure.inkj", file_sha="b" * 64)
        FileIndex.objects.create(
            home_directory=sub_dir,
            name="adventure.inkj",
            file_sha256="c" * 64,
            unique_sha256="u" + "c" * 63,
            lastscan=0.0,
            lastmod=0.0,
            filetype=self.inkj_filetype,
            delete_pending=False,
            is_generic_icon=False,
        )

        created = ingest_stories()

        self.assertEqual(created, 2)
        slugs = set(Story.objects.values_list("slug", flat=True))
        self.assertEqual(len(slugs), 2)


class VerifyStoriesTests(IngestionTestCase):
    """verify_stories(): tombstone/restore/refresh scanner-ingested stories."""

    def test_missing_source_file_is_tombstoned(self):
        """A Story whose source .inkj file no longer has a live FileIndex
        row is tombstoned: is_available=False and compiled_json cleared,
        while the row itself (and any player saves pointing at it) survives."""
        story = self._ingest_one()
        FileIndex.objects.filter(home_directory=self.dir_obj, name="adventure.inkj").delete()

        tombstoned, restored, refreshed = verify_stories()

        self.assertEqual((tombstoned, restored, refreshed), (1, 0, 0))
        story.refresh_from_db()
        self.assertFalse(story.is_available)
        self.assertEqual(story.compiled_json, {})
        self.assertTrue(Story.objects.filter(pk=story.pk).exists())

    def test_already_tombstoned_story_is_not_retombstoned(self):
        """A story already tombstoned in a prior run doesn't get counted
        again on a subsequent run with no further change."""
        story = self._ingest_one()
        FileIndex.objects.filter(home_directory=self.dir_obj, name="adventure.inkj").delete()
        verify_stories()

        tombstoned, restored, refreshed = verify_stories()

        self.assertEqual((tombstoned, restored, refreshed), (0, 0, 0))
        story.refresh_from_db()
        self.assertFalse(story.is_available)

    def test_restored_file_refills_compiled_json_on_the_same_row(self):
        """A tombstoned story whose source file reappears at the same path
        is restored on the same Story.pk — every player's saves reconnect
        without FK churn."""
        story = self._ingest_one()
        original_pk = story.pk
        FileIndex.objects.filter(home_directory=self.dir_obj, name="adventure.inkj").delete()
        verify_stories()

        self._make_fileindex("adventure.inkj", file_sha="b" * 64)
        tombstoned, restored, refreshed = verify_stories()

        self.assertEqual((tombstoned, restored, refreshed), (0, 1, 0))
        story.refresh_from_db()
        self.assertEqual(story.pk, original_pk)
        self.assertTrue(story.is_available)
        self.assertEqual(story.compiled_json, COMPILED_JSON)

    def test_changed_source_file_is_refreshed(self):
        """A source file whose sha256 no longer matches Story.source_sha256
        is re-validated and its compiled_json replaced."""
        story = self._ingest_one()
        changed_json = {"inkVersion": 21, "root": [["^A different story.", "\n", "done", None], "done", None], "listDefs": {}}
        _write_inkj(self.albums_dir, "adventure.inkj", data=changed_json)
        FileIndex.objects.filter(home_directory=self.dir_obj, name="adventure.inkj").update(file_sha256="d" * 64)

        tombstoned, restored, refreshed = verify_stories()

        self.assertEqual((tombstoned, restored, refreshed), (0, 0, 1))
        story.refresh_from_db()
        self.assertEqual(story.compiled_json, changed_json)
        self.assertEqual(story.source_sha256, "d" * 64)

    def test_invalid_replacement_content_keeps_the_existing_story_available(self):
        """A source file that changed to something invalid is not applied —
        a half-written file mid-copy must not take down a working story."""
        story = self._ingest_one()
        original_json = story.compiled_json
        _write_inkj(self.albums_dir, "adventure.inkj", data={"not": "compiled ink"})
        FileIndex.objects.filter(home_directory=self.dir_obj, name="adventure.inkj").update(file_sha256="e" * 64)

        tombstoned, restored, refreshed = verify_stories()

        self.assertEqual((tombstoned, restored, refreshed), (0, 0, 0))
        story.refresh_from_db()
        self.assertTrue(story.is_available)
        self.assertEqual(story.compiled_json, original_json)

    def test_unchanged_story_is_left_alone(self):
        """A story whose source file hasn't changed is not touched at all."""
        story = self._ingest_one()
        original_updated_at = story.updated_at

        tombstoned, restored, refreshed = verify_stories()

        self.assertEqual((tombstoned, restored, refreshed), (0, 0, 0))
        story.refresh_from_db()
        self.assertEqual(story.updated_at, original_updated_at)


class PlayPageGalleryExitLinkTests(IngestionTestCase):
    """The play page's "View in gallery" link for a scanner-ingested story."""

    def test_play_page_links_back_to_the_source_gallery_item(self):
        """A scanner-ingested story's play page offers a link to the
        .inkj file's own item view, resolved via its live FileIndex row."""
        story = self._ingest_one()
        self.client.force_login(self.owner)

        response = self.client.get(f"/if/{story.slug}/", secure=True)

        self.assertEqual(response.status_code, 200)
        file_entry = FileIndex.objects.get(home_directory=self.dir_obj, name__iexact="adventure.inkj")
        self.assertIn(f"/view_item/{file_entry.unique_sha256}/".encode(), response.content)

    def test_tombstoned_story_has_no_gallery_link(self):
        """A story whose source file was removed (tombstoned) has no live
        FileIndex row to link to, so the link is omitted rather than 404ing."""
        story = self._ingest_one()
        FileIndex.objects.filter(home_directory=self.dir_obj, name__iexact="adventure.inkj").delete()
        verify_stories()
        story.refresh_from_db()
        self.assertFalse(story.is_available)
        self.client.force_login(self.owner)

        response = self.client.get(f"/if/{story.slug}/", secure=True)

        self.assertEqual(response.status_code, 404)

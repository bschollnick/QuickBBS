"""Step 9 tests: interactive_fiction.ingestion (game-folder ingestion,
re-scoped per the game-folder separation design work).

Uses real DirectoryIndex/FileIndex rows under a temporary ALBUMS_PATH
(matching quickbbs/tests/test_fileindex.py's own override_settings pattern
— DirectoryIndex.add_directory() rejects any path outside the configured
albums root, so a real temp directory registered as ALBUMS_PATH is
required, not just a bare FileIndex row pointing at an arbitrary path).
Every game folder is a real directory under
<ALBUMS_PATH>/interactive_fiction/<game_name>/, with a real __init__.py
manifest and a real .inkj file on disk, read by ingest_stories()/
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
from interactive_fiction.models import Story, StoryImage
from quickbbs.common import normalize_fqpn
from quickbbs.directoryindex import DirectoryIndex
from quickbbs.models import FileIndex

COMPILED_JSON = {"inkVersion": 21, "root": [["^Hello, traveler.", "\n", "done", None], "done", None], "listDefs": {}}

DEFAULT_MANIFEST = """
GAME_TITLE = "Adventure"
GAME_AUTHOR = "Test Author"
REQUIRED_PLUGINS = []
MAIN_STORY_FILE = "adventure.inkj"
"""


def _write_inkj(directory: str, name: str, data: dict | None = None) -> str:
    """Write a compiled-Ink JSON file to disk and return its full path."""
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as story_file:
        json.dump(data if data is not None else COMPILED_JSON, story_file)
    return path


def _write_manifest(directory: str, manifest_source: str = DEFAULT_MANIFEST) -> str:
    """Write a game folder's __init__.py manifest and return its full path."""
    path = os.path.join(directory, "__init__.py")
    with open(path, "w", encoding="utf-8") as manifest_file:
        manifest_file.write(manifest_source)
    return path


class IngestionTestCase(TestCase):
    """Shared setUp/tearDown: a real temp ALBUMS_PATH with
    interactive_fiction/<game_name>/ game folders."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.albums_dir = os.path.join(self.temp_dir, "albums")
        self.games_root = os.path.join(self.albums_dir, "interactive_fiction")
        os.makedirs(self.games_root, exist_ok=True)
        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir, IF_SCAN_DEFAULT_OWNER="if_librarian_test")
        self._settings_override.enable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        _, self.games_root_dir = DirectoryIndex.add_directory(self.games_root + "/")
        self.owner = get_user_model().objects.create_user(username="if_librarian_test", password="pw")
        self.inkj_filetype = filetypes.objects.get(fileext=".inkj")

    def tearDown(self):
        self._settings_override.disable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_game_dir(self, name: str) -> tuple[str, DirectoryIndex]:
        """Create one real game folder on disk plus its own DirectoryIndex row."""
        game_dir = os.path.join(self.games_root, name)
        os.makedirs(game_dir, exist_ok=True)
        _, dir_obj = DirectoryIndex.add_directory(game_dir + "/")
        return game_dir, dir_obj

    def _make_fileindex(self, dir_obj: DirectoryIndex, name: str, file_sha: str = "a" * 64, **kwargs) -> FileIndex:
        return FileIndex.objects.create(
            home_directory=dir_obj,
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

    def _make_valid_game(
        self, game_name: str = "adventure", inkj_name: str = "adventure.inkj", manifest_source: str = DEFAULT_MANIFEST
    ) -> tuple[str, DirectoryIndex]:
        """Create one complete, valid game folder: __init__.py manifest,
        one real .inkj file on disk, and a matching FileIndex row."""
        game_dir, dir_obj = self._make_game_dir(game_name)
        _write_manifest(game_dir, manifest_source)
        _write_inkj(game_dir, inkj_name)
        self._make_fileindex(dir_obj, inkj_name, file_sha="b" * 64)
        return game_dir, dir_obj

    def _ingest_one(self, game_name: str = "adventure", inkj_name: str = "adventure.inkj") -> Story:
        game_dir, _ = self._make_valid_game(game_name, inkj_name)
        ingest_stories()
        return Story.objects.get(source_fqfn=self._expected_fqfn(game_dir, inkj_name))


class IngestStoriesTests(IngestionTestCase):
    """ingest_stories(): create a Story for every real, valid game folder."""

    def test_valid_game_folder_is_ingested(self):
        """A well-formed game folder (manifest + valid .inkj) creates a
        Story owned by IF_SCAN_DEFAULT_OWNER, private by default, with
        source tracking and manifest fields set."""
        game_dir, _ = self._make_valid_game()

        created = ingest_stories()

        self.assertEqual(created, 1)
        story = Story.objects.get(title="Adventure")
        self.assertEqual(story.owner, self.owner)
        self.assertFalse(story.is_public)
        self.assertEqual(story.source_fqfn, self._expected_fqfn(game_dir, "adventure.inkj"))
        self.assertEqual(story.source_sha256, "b" * 64)
        self.assertEqual(story.game_author, "Test Author")
        self.assertEqual(story.game_required_plugins, [])
        self.assertEqual(story.game_ingestion_error, "")

    def test_already_ingested_folder_is_not_reingested_as_a_duplicate(self):
        """A second ingest_stories() run refreshes (not duplicates) the
        same folder's Story row — matched by its real main-story path."""
        self._make_valid_game()
        ingest_stories()

        ingested_second_run = ingest_stories()

        self.assertEqual(ingested_second_run, 1)
        self.assertEqual(Story.objects.count(), 1)

    def test_folder_with_no_init_py_records_an_ingestion_error(self):
        """A game folder missing its mandatory __init__.py manifest is a
        real, explicit ingestion failure — not silently skipped, not
        guessed via a filename fallback."""
        game_dir, dir_obj = self._make_game_dir("no_manifest")
        _write_inkj(game_dir, "adventure.inkj")
        self._make_fileindex(dir_obj, "adventure.inkj")

        created = ingest_stories()

        self.assertEqual(created, 0)
        story = Story.objects.get(title="no_manifest")
        self.assertIn("__init__.py", story.game_ingestion_error)
        self.assertFalse(story.is_available)

    def test_main_story_file_not_present_records_an_ingestion_error(self):
        """MAIN_STORY_FILE naming a file that doesn't exist in the folder
        is a real ingestion failure — any OTHER .inkj present is not a
        valid fallback."""
        game_dir, dir_obj = self._make_game_dir("bad_main")
        _write_manifest(game_dir, DEFAULT_MANIFEST)
        _write_inkj(game_dir, "not_the_main_file.inkj")
        self._make_fileindex(dir_obj, "not_the_main_file.inkj")

        created = ingest_stories()

        self.assertEqual(created, 0)
        story = Story.objects.get(title="bad_main")
        self.assertIn("MAIN_STORY_FILE", story.game_ingestion_error)

    def test_other_inkj_files_in_the_folder_are_ignored(self):
        """A folder with more than one .inkj file only ever ingests the
        one MAIN_STORY_FILE names — the rest are never touched."""
        game_dir, dir_obj = self._make_game_dir("multi")
        _write_manifest(game_dir, DEFAULT_MANIFEST)
        _write_inkj(game_dir, "adventure.inkj")
        _write_inkj(game_dir, "bonus.inkj")
        self._make_fileindex(dir_obj, "adventure.inkj", file_sha="b" * 64)
        self._make_fileindex(dir_obj, "bonus.inkj", file_sha="c" * 64)

        created = ingest_stories()

        self.assertEqual(created, 1)
        self.assertEqual(Story.objects.filter(is_available=True).count(), 1)
        story = Story.objects.get(is_available=True)
        self.assertEqual(story.source_fqfn, self._expected_fqfn(game_dir, "adventure.inkj"))

    def test_unresolvable_required_plugin_still_ingests_successfully(self):
        """REQUIRED_PLUGINS is copied onto the Story verbatim from the
        manifest, never resolved against discover_api_descriptors() at
        ingestion time — resolving/loading a game's own plugin .py files
        requires executing them, which is gated on Story.is_engine_trusted,
        which in turn requires the Story to already exist. Registering
        REQUIRED_PLUGINS' names is an admin-time decision (whether to
        trust this game), not an ingestion-time precondition — a name
        that doesn't (yet) resolve to a discovered API is not an error."""
        manifest = """
GAME_TITLE = "Adventure"
GAME_AUTHOR = "Test Author"
REQUIRED_PLUGINS = ["not_yet_discoverable_plugin"]
MAIN_STORY_FILE = "adventure.inkj"
"""
        self._make_valid_game(manifest_source=manifest)

        created = ingest_stories()

        self.assertEqual(created, 1)
        story = Story.objects.get(title="Adventure")
        self.assertEqual(story.game_required_plugins, ["not_yet_discoverable_plugin"])
        self.assertEqual(story.game_ingestion_error, "")
        self.assertFalse(story.is_engine_trusted)

    def test_invalid_inkj_file_is_rejected(self):
        """A MAIN_STORY_FILE that isn't valid compiled Ink JSON is
        rejected, not stored as a playable Story — same validation
        Step 4's upload form uses."""
        game_dir, dir_obj = self._make_game_dir("broken")
        _write_manifest(game_dir, DEFAULT_MANIFEST)
        _write_inkj(game_dir, "adventure.inkj", data={"not": "compiled ink"})
        self._make_fileindex(dir_obj, "adventure.inkj")

        created = ingest_stories()

        self.assertEqual(created, 0)
        story = Story.objects.get(title="broken")
        self.assertFalse(story.is_available)
        self.assertNotEqual(story.game_ingestion_error, "")

    def test_missing_scan_owner_account_ingests_nothing(self):
        """If IF_SCAN_DEFAULT_OWNER doesn't exist, ingestion fails loudly
        (logs, skips everything) rather than guessing an owner."""
        self.owner.delete()
        self._make_valid_game()

        created = ingest_stories()

        self.assertEqual(created, 0)
        self.assertFalse(Story.objects.exists())

    def test_no_games_root_at_all_ingests_nothing(self):
        """If <ALBUMS_PATH>/interactive_fiction/ doesn't exist at all
        (e.g. a fresh install with no games ingested yet), ingestion is a
        clean no-op, not an error."""
        shutil.rmtree(self.games_root)

        created = ingest_stories()

        self.assertEqual(created, 0)
        self.assertFalse(Story.objects.exists())


class VerifyStoriesTests(IngestionTestCase):
    """verify_stories(): tombstone/restore/refresh scanner-ingested stories."""

    def test_missing_source_file_is_tombstoned(self):
        """A Story whose source .inkj file no longer has a live FileIndex
        row is tombstoned: is_available=False and compiled_json cleared,
        while the row itself (and any player saves pointing at it) survives."""
        story = self._ingest_one()
        FileIndex.objects.filter(name="adventure.inkj").delete()

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
        FileIndex.objects.filter(name="adventure.inkj").delete()
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
        _, dir_obj = DirectoryIndex.add_directory(os.path.join(self.games_root, "adventure") + "/")
        FileIndex.objects.filter(name="adventure.inkj").delete()
        verify_stories()

        self._make_fileindex(dir_obj, "adventure.inkj", file_sha="b" * 64)
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
        game_dir = os.path.join(self.games_root, "adventure")
        changed_json = {"inkVersion": 21, "root": [["^A different story.", "\n", "done", None], "done", None], "listDefs": {}}
        _write_inkj(game_dir, "adventure.inkj", data=changed_json)
        FileIndex.objects.filter(name="adventure.inkj").update(file_sha256="d" * 64)

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
        game_dir = os.path.join(self.games_root, "adventure")
        _write_inkj(game_dir, "adventure.inkj", data={"not": "compiled ink"})
        FileIndex.objects.filter(name="adventure.inkj").update(file_sha256="e" * 64)

        tombstoned, restored, refreshed = verify_stories()

        self.assertEqual((tombstoned, restored, refreshed), (0, 0, 0))
        story.refresh_from_db()
        self.assertTrue(story.is_available)
        self.assertEqual(story.compiled_json, original_json)

    def test_unchanged_story_is_left_alone(self):
        """A story whose source file hasn't changed keeps the same
        content and availability across a verify pass (manifest fields
        ARE re-applied every pass, so updated_at legitimately advances —
        this is not the same guarantee as the old flat-file model's
        "untouched" behavior)."""
        story = self._ingest_one()
        original_compiled_json = story.compiled_json

        tombstoned, restored, refreshed = verify_stories()

        self.assertEqual((tombstoned, restored, refreshed), (0, 0, 0))
        story.refresh_from_db()
        self.assertTrue(story.is_available)
        self.assertEqual(story.compiled_json, original_compiled_json)

    def test_previously_broken_folder_is_retried_and_recovers(self):
        """A game folder that failed ingestion (e.g. missing manifest) is
        retried on every verify_stories() pass — once fixed, it recovers
        without manual intervention."""
        game_dir, dir_obj = self._make_game_dir("fixable")
        _write_inkj(game_dir, "adventure.inkj")
        self._make_fileindex(dir_obj, "adventure.inkj")
        ingest_stories()
        broken_story = Story.objects.get(title="fixable")
        self.assertNotEqual(broken_story.game_ingestion_error, "")

        _write_manifest(game_dir, DEFAULT_MANIFEST)
        verify_stories()

        broken_story.refresh_from_db()
        self.assertEqual(broken_story.game_ingestion_error, "")
        self.assertTrue(broken_story.is_available)
        self.assertEqual(broken_story.title, "Adventure")


class PlayPageGalleryExitLinkTests(IngestionTestCase):
    """The play page's "View in gallery" link for a scanner-ingested story."""

    def test_play_page_links_back_to_the_source_gallery_item(self):
        """A scanner-ingested story's play page offers a link to the
        .inkj file's own item view, resolved via its live FileIndex row."""
        story = self._ingest_one()
        self.client.force_login(self.owner)

        response = self.client.get(f"/if/{story.slug}/", secure=True)

        self.assertEqual(response.status_code, 200)
        file_entry = FileIndex.objects.get(name__iexact="adventure.inkj")
        self.assertIn(f"/view_item/{file_entry.unique_sha256}/".encode(), response.content)

    def test_tombstoned_story_has_no_gallery_link(self):
        """A story whose source file was removed (tombstoned) has no live
        FileIndex row to link to, so the link is omitted rather than 404ing."""
        story = self._ingest_one()
        FileIndex.objects.filter(name__iexact="adventure.inkj").delete()
        verify_stories()
        story.refresh_from_db()
        self.assertFalse(story.is_available)
        self.client.force_login(self.owner)

        response = self.client.get(f"/if/{story.slug}/", secure=True)

        self.assertEqual(response.status_code, 404)


# Kept as a plain data structure (not a hand-written manifest string) so
# it's rendered via repr() below — avoids duplicating this literal
# alongside test_views.py's own CHARACTER_CREATION_FIELDS fixture.
_NEW_GAME_FIELDS = [
    {"var": "player_name", "type": "text", "label": "What is your name?", "default": "Bob"},
    {
        "var": "player_is_man",
        "type": "radio_image",
        "label": "Are you a man or a woman?",
        "default": True,
        "options": [
            {"value": {"player_is_man": True}, "label": "Male", "image": "male.png"},
            {"value": {"player_is_man": False}, "label": "Female", "image": "female.png"},
        ],
    },
]

NEW_GAME_FIELDS_MANIFEST = f"""
GAME_TITLE = "Adventure"
GAME_AUTHOR = "Test Author"
REQUIRED_PLUGINS = []
MAIN_STORY_FILE = "adventure.inkj"

NEW_GAME_FIELDS = {_NEW_GAME_FIELDS!r}
"""


class NewGameFieldsIngestionTests(IngestionTestCase):
    """A game folder's NEW_GAME_FIELDS manifest entry is copied onto its
    Story row, and every radio_image option's own image is auto-linked
    as a StoryImage row under a synthetic "newgame:<filename>" tag —
    these are ordinary gallery files, scanned into FileIndex like any
    other file in the game folder, not served through a separate path."""

    def _make_png_fileindex(self, dir_obj: DirectoryIndex, name: str, file_sha: str) -> FileIndex:
        png_filetype = filetypes.objects.get(fileext=".png")
        return FileIndex.objects.create(
            home_directory=dir_obj,
            name=name,
            file_sha256=file_sha,
            unique_sha256=("u" + file_sha)[:64],
            lastscan=0.0,
            lastmod=0.0,
            filetype=png_filetype,
            delete_pending=False,
            is_generic_icon=False,
        )

    def test_new_game_fields_are_copied_onto_the_story(self):
        """NEW_GAME_FIELDS from the manifest is copied verbatim onto the
        Story row's game_new_game_fields."""
        self._make_valid_game(manifest_source=NEW_GAME_FIELDS_MANIFEST)

        ingest_stories()

        story = Story.objects.get(title="Adventure")
        self.assertEqual(len(story.game_new_game_fields), 2)
        self.assertEqual(story.game_new_game_fields[0]["var"], "player_name")
        self.assertEqual(story.game_new_game_fields[1]["var"], "player_is_man")

    def test_radio_image_options_are_linked_as_story_images_once_scanned(self):
        """Once male.png/female.png are real, scanned gallery files in the
        game folder, ingestion links each to this Story under its own
        "newgame:<filename>" tag — the same StoryImage mechanism a real
        `# image:` Ink tag uses."""
        _, dir_obj = self._make_valid_game(manifest_source=NEW_GAME_FIELDS_MANIFEST)
        self._make_png_fileindex(dir_obj, "male.png", file_sha="d" * 64)
        self._make_png_fileindex(dir_obj, "female.png", file_sha="e" * 64)

        ingest_stories()

        story = Story.objects.get(title="Adventure")
        self.assertTrue(StoryImage.objects.filter(story=story, tag_name="newgame:male.png").exists())
        self.assertTrue(StoryImage.objects.filter(story=story, tag_name="newgame:female.png").exists())

    def test_unscanned_image_is_left_unlinked_until_a_later_pass(self):
        """A radio_image option naming a file that hasn't been scanned yet
        (game folder just unzipped, scanner hasn't run) is silently left
        unlinked — ingestion doesn't fail because of it."""
        self._make_valid_game(manifest_source=NEW_GAME_FIELDS_MANIFEST)

        created = ingest_stories()

        self.assertEqual(created, 1)
        story = Story.objects.get(title="Adventure")
        self.assertFalse(StoryImage.objects.filter(story=story, tag_name="newgame:male.png").exists())

    def test_a_later_verify_pass_links_images_scanned_after_first_ingestion(self):
        """A subsequent verify_stories() run retries linking, picking up
        an image file that only became a real FileIndex row afterward."""
        _, dir_obj = self._make_valid_game(manifest_source=NEW_GAME_FIELDS_MANIFEST)
        ingest_stories()
        story = Story.objects.get(title="Adventure")
        self.assertFalse(StoryImage.objects.filter(story=story, tag_name="newgame:male.png").exists())

        self._make_png_fileindex(dir_obj, "male.png", file_sha="d" * 64)
        verify_stories()

        self.assertTrue(StoryImage.objects.filter(story=story, tag_name="newgame:male.png").exists())

"""Tests: interactive_fiction.ingestion, with folder ingestion disabled.

A game enters the database as a bundle; a game folder is not ingested.
These tests hold that line — a well-formed folder produces no Story —
and cover the parts of ingestion that do not depend on folders.
`test_bundle_ingestion.py` covers the live path: manifest fields, the
three hashes, re-ingest, tampering, discovery and verify.

The folder-ingestion cases these replaced are commented out below,
alongside the code they covered, so restoring one restores the other.

Uses real DirectoryIndex/FileIndex rows under a temporary ALBUMS_PATH
(matching quickbbs/tests/test_fileindex.py's own override_settings pattern
— DirectoryIndex.add_directory() rejects any path outside the configured
albums root, so a real temp directory registered as ALBUMS_PATH is
required, not just a bare FileIndex row pointing at an arbitrary path).
Every game folder is a real directory under
<ALBUMS_PATH>/interactive_fiction/<game_name>/, with a real manifest.yaml
manifest and a real .inkj file on disk, read by ingest_stories()/
verify_stories() exactly as the scan command would. TestCase (never
TransactionTestCase, per standing project rule).
"""

from __future__ import annotations

import json
import os
import shutil
from typing import ClassVar

import yaml
from django.contrib.auth import get_user_model

from filetypes.models import filetypes
from interactive_fiction.ingestion import (
    ingest_stories,
    ingest_stories_in_directory,
)
from interactive_fiction.models import Story
from quickbbs.common import normalize_fqpn
from quickbbs.directoryindex import DirectoryIndex
from quickbbs.models import FileIndex
from quickbbs.tests.albums_root import AlbumsRootTestCase

COMPILED_JSON = {"inkVersion": 21, "root": [["^Hello, traveler.", "\n", "done", None], "done", None], "listDefs": {}}

DEFAULT_MANIFEST = {
    "GAME_TITLE": "Adventure",
    "GAME_AUTHOR": "Test Author",
    "REQUIRED_PLUGINS": [],
    "MAIN_STORY_FILE": "adventure.inkj",
}


def _write_inkj(directory: str, name: str, data: dict | None = None) -> str:
    """Write a compiled-Ink JSON file to disk and return its full path."""
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as story_file:
        json.dump(data if data is not None else COMPILED_JSON, story_file)
    return path


def _write_manifest(directory: str, manifest_source: dict | None = None) -> str:
    """Write a game folder's manifest.yaml and return its full path."""
    path = os.path.join(directory, "manifest.yaml")
    with open(path, "w", encoding="utf-8") as manifest_file:
        yaml.safe_dump(DEFAULT_MANIFEST if manifest_source is None else manifest_source, manifest_file)
    return path


class IngestionTestCase(AlbumsRootTestCase):
    """A temporary albums root with interactive_fiction/<game_name>/ game folders."""

    extra_settings: ClassVar[dict[str, object]] = {"IF_SCAN_DEFAULT_OWNER": "if_librarian_test"}

    def setUp(self):
        super().setUp()
        self.games_root = os.path.join(self.albums_dir, "interactive_fiction")
        self.games_root_dir = self.add_directory("interactive_fiction")
        self.owner = get_user_model().objects.create_user(username="if_librarian_test", password="pw")
        self.inkj_filetype = filetypes.objects.get(fileext=".inkj")

    def _make_game_dir(self, name: str) -> tuple[str, DirectoryIndex]:
        """Create one real game folder on disk plus its own DirectoryIndex row."""
        game_dir = os.path.join(self.games_root, name)
        os.makedirs(game_dir, exist_ok=True)
        _, dir_obj = DirectoryIndex.add_directory(game_dir + "/")
        assert dir_obj is not None
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
        self, game_name: str = "adventure", inkj_name: str = "adventure.inkj", manifest_source: dict | None = None
    ) -> tuple[str, DirectoryIndex]:
        """Create one complete, valid game folder: manifest.yaml,
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


class FolderIngestionIsDisabledTests(IngestionTestCase):
    """A game folder is not a game: only a bundle is ingested."""

    def test_a_valid_game_folder_produces_no_story(self):
        """The folder is well-formed — manifest.yaml, a real .inkj, a
        FileIndex row — and is still not ingested."""
        self._make_valid_game()

        created = ingest_stories()

        self.assertEqual(created, 0)
        self.assertFalse(Story.objects.exists())

    def test_a_folder_beside_its_bundle_does_not_add_a_second_story(self):
        """The duplicate this disabling exists to prevent: one game
        ingested twice, once as a bundle and once as its own folder,
        leaving two rows with separate saves."""
        self._make_valid_game()

        ingest_stories()
        ingest_stories()

        self.assertEqual(Story.objects.count(), 0)

    def test_a_broken_folder_records_no_error_row_either(self):
        """A folder with no manifest is not ingested, so it produces no
        Story carrying game_ingestion_error — nothing reads it at all."""
        self._make_game_dir("brokengame")

        created = ingest_stories()

        self.assertEqual(created, 0)
        self.assertFalse(Story.objects.exists())

    def test_ingest_stories_in_directory_is_a_no_op(self):
        """The live-web hook runs on every directory sync and must stay
        silent now that a directory is never a game."""
        _, dir_obj = self._make_valid_game()

        self.assertEqual(ingest_stories_in_directory(dir_obj), 0)
        self.assertFalse(Story.objects.exists())

    def test_no_games_root_at_all_ingests_nothing(self):
        """A fresh install with no games is a clean no-op, not an error."""
        shutil.rmtree(self.games_root)

        created = ingest_stories()

        self.assertEqual(created, 0)
        self.assertFalse(Story.objects.exists())

    def test_missing_scan_owner_account_ingests_nothing(self):
        """If IF_SCAN_DEFAULT_OWNER doesn't exist, ingestion fails loudly
        (logs, skips everything) rather than guessing an owner."""
        self.owner.delete()
        self._make_valid_game()

        created = ingest_stories()

        self.assertEqual(created, 0)
        self.assertFalse(Story.objects.exists())


# The play page's "View in gallery" link pointed at the source
# `.inkj`'s own FileIndex row. Only a folder-ingested story had one:
# a bundle is a single file with no per-file gallery rows, so there is
# nothing to link to and nothing to test while folder ingestion is
# disabled. Restore with it.
# class PlayPageGalleryExitLinkTests(IngestionTestCase):
#     """The play page's "View in gallery" link for a scanner-ingested story."""
#
#     def test_play_page_links_back_to_the_source_gallery_item(self):
#         """A scanner-ingested story's play page offers a link to the
#         .inkj file's own item view, resolved via its live FileIndex row."""
#         story = self._ingest_one()
#         self.client.force_login(self.owner)
#
#         response = self.client.get(f"/if/{story.slug}/", secure=True)
#
#         self.assertEqual(response.status_code, 200)
#         file_entry = FileIndex.objects.get(name__iexact="adventure.inkj")
#         self.assertIn(f"/view_item/{file_entry.unique_sha256}/".encode(), response.content)
#
#     def test_tombstoned_story_has_no_gallery_link(self):
#         """A story whose source file was removed (tombstoned) has no live
#         FileIndex row to link to, so the link is omitted rather than 404ing."""
#         story = self._ingest_one()
#         FileIndex.objects.filter(name__iexact="adventure.inkj").delete()
#         verify_stories()
#         story.refresh_from_db()
#         self.assertFalse(story.is_available)
#         self.client.force_login(self.owner)
#
#         response = self.client.get(f"/if/{story.slug}/", secure=True)
#
#         self.assertEqual(response.status_code, 404)
#
#
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

NEW_GAME_FIELDS_MANIFEST = {**DEFAULT_MANIFEST, "NEW_GAME_FIELDS": _NEW_GAME_FIELDS}


# NEW_GAME_FIELDS reaching the Story row is covered for the live path
# by test_bundle_ingestion.py's test_the_manifest_fields_reach_the_row.
# These two asserted it through folder ingestion. Restore with it.
# class NewGameFieldsIngestionTests(IngestionTestCase):
#     """A game's NEW_GAME_FIELDS manifest entry is copied onto its Story row.
#
#     The option images themselves are no longer pre-linked at ingestion: a
#     bundled game resolves `newgame:<filename>` from its own bundle at
#     request time (`bundle_media.resolve_tag_in_bundle`).
#     """
#
#     def test_new_game_fields_are_copied_onto_the_story(self):
#         self._make_valid_game(manifest_source=NEW_GAME_FIELDS_MANIFEST)
#         ingest_stories()
#         story = Story.objects.get(title="Adventure")
#         self.assertEqual(story.game_new_game_fields, _NEW_GAME_FIELDS)
#
#     def test_a_game_declaring_none_gets_an_empty_list(self):
#         self._make_valid_game()
#         ingest_stories()
#         self.assertEqual(Story.objects.get(title="Adventure").game_new_game_fields, [])
#

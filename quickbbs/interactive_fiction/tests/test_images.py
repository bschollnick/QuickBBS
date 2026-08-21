"""Tests for interactive_fiction.images: linking a story's Ink tag to a real
gallery FileIndex row (see
claude_docs/plans/interactive_fiction_fileindex_mapping.md).

TestCase (never TransactionTestCase, per standing project rule).
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from interactive_fiction.images import find_file_by_path, link_story_image
from interactive_fiction.models import Story, StoryImage
from interactive_fiction.tests.image_test_utils import make_gallery_image
from quickbbs.models import DirectoryIndex


def _make_story() -> Story:
    user = get_user_model().objects.create_user(username="imgowner", password="pw")
    return Story.objects.create(owner=user, title="Image Story", slug="image-story", compiled_json={"inkVersion": 21, "root": [], "listDefs": {}})


class _AlbumsRootTestCase(TestCase):
    """Base class pointing ALBUMS_PATH at a temp dir, per
    quickbbs/tests/test_fileindex.py's own pattern — DirectoryIndex.add_directory()
    rejects any path outside the configured albums root."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.albums_dir = Path(self.temp_dir) / "albums"
        self.albums_dir.mkdir(exist_ok=True)
        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir)
        self._settings_override.enable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None

    def tearDown(self):
        self._settings_override.disable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)


class FindFileByPathTests(_AlbumsRootTestCase):
    """find_file_by_path(): resolve a full gallery path to its FileIndex row."""

    def test_a_real_gallery_file_resolves(self):
        """A path matching a real, scanned-in file resolves to its FileIndex row."""
        file_index = make_gallery_image(self.albums_dir, "forest.jpg")
        found = find_file_by_path(file_index.full_filepathname)
        self.assertIsNotNone(found)
        self.assertEqual(found.pk, file_index.pk)

    def test_an_unknown_path_returns_none(self):
        """A path with no matching DirectoryIndex row returns None, not raise."""
        self.assertIsNone(find_file_by_path("/nonexistent/gallery/path/missing.jpg"))

    def test_a_known_directory_but_unknown_filename_returns_none(self):
        """A real directory but a filename never scanned into it returns None."""
        file_index = make_gallery_image(self.albums_dir, "forest.jpg")
        directory_path = file_index.full_filepathname.rsplit(file_index.name, 1)[0]
        self.assertIsNone(find_file_by_path(directory_path + "does-not-exist.jpg"))


class LinkStoryImageTests(_AlbumsRootTestCase):
    """link_story_image(): per-tag attach/replace, is_cover exclusivity, eager thumbnailing."""

    def setUp(self):
        super().setUp()
        self.story = _make_story()

    def test_linking_creates_a_story_image_row(self):
        """A successful link creates a StoryImage row resolvable back to the linked file."""
        file_index = make_gallery_image(self.albums_dir, "forest.jpg")
        link_story_image(self.story, "forest.jpg", file_index)
        image = StoryImage.objects.get(story=self.story, tag_name="forest.jpg")
        self.assertEqual(image.file_index_id, file_index.pk)

    def test_linking_the_same_tag_again_replaces_it(self):
        """A second link to the same tag_name updates the existing row
        rather than violating the (story, tag_name) uniqueness constraint."""
        first_file = make_gallery_image(self.albums_dir, "forest_v1.jpg", color=(255, 0, 0))
        second_file = make_gallery_image(self.albums_dir, "forest_v2.jpg", color=(0, 255, 0))
        link_story_image(self.story, "forest.jpg", first_file)
        link_story_image(self.story, "forest.jpg", second_file)
        self.assertEqual(StoryImage.objects.filter(story=self.story, tag_name="forest.jpg").count(), 1)
        image = StoryImage.objects.get(story=self.story, tag_name="forest.jpg")
        self.assertEqual(image.file_index_id, second_file.pk)

    def test_setting_a_new_cover_clears_the_previous_one(self):
        """is_cover is exclusive per story (StoryImage's partial unique
        constraint) — linking a new cover unmarks the old one instead of
        violating the constraint."""
        first_file = make_gallery_image(self.albums_dir, "first.jpg")
        second_file = make_gallery_image(self.albums_dir, "second.jpg")
        link_story_image(self.story, "first.jpg", first_file, is_cover=True)
        link_story_image(self.story, "second.jpg", second_file, is_cover=True)
        self.assertEqual(StoryImage.objects.filter(story=self.story, is_cover=True).count(), 1)
        cover = self.story.cover_image
        self.assertEqual(cover.tag_name, "second.jpg")

    def test_linking_generates_a_thumbnail_eagerly(self):
        """Per the plan's decision, linking any tag (not just covers)
        eagerly generates the linked file's thumbnail, not lazily on
        first request."""
        file_index = make_gallery_image(self.albums_dir, "forest.jpg", color=(20, 200, 20))
        link_story_image(self.story, "forest.jpg", file_index)
        file_index.refresh_from_db()
        self.assertIsNotNone(file_index.new_ftnail)
        self.assertTrue(file_index.new_ftnail.thumbnail_exists("small"))

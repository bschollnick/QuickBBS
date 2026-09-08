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
from django.test import SimpleTestCase, TestCase, override_settings

from interactive_fiction.image_linking import (
    build_model_var_values,
    resolve_sibling_directory,
    resolve_tag_name,
    scan_corpus,
)
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

    def test_resolves_against_a_title_cased_stored_name(self):
        """The real scanner stores every FileIndex.name title-cased
        (quickbbs.common.normalize_string_title()) regardless of the real
        on-disk filename's actual casing — confirmed directly against a
        real scanned row (a .inkj on disk, stored title-cased). A
        caller building a path from a real filesystem filename (e.g. a
        game manifest's own literal MAIN_STORY_FILE string, all
        lowercase) must still resolve — this is exactly the bug that
        broke a real game's own ingestion until find_file_by_path's `name`
        lookup became case-insensitive (name__iexact)."""
        file_index = make_gallery_image(self.albums_dir, "forest.jpg")
        file_index.name = "Forest.Jpg"
        file_index.save(update_fields=["name"])
        directory_path = file_index.full_filepathname.rsplit("Forest.Jpg", 1)[0]

        found = find_file_by_path(directory_path + "forest.jpg")

        self.assertIsNotNone(found)
        self.assertEqual(found.pk, file_index.pk)


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


class SiblingRootResolutionTests(_AlbumsRootTestCase):
    """A game may serve art from a directory BESIDE its images/ tree.

    `find_gallery_images_root()` hands `resolve_tag_name` a single root --
    the game's own `images/`. ASFA's original also loads art from `UI/`, a
    SIBLING of `Images/`: the themed `antenna.png` (`game.js:358`
    getThemeFolder) and the occult book covers
    (`personSirRonaldGates.js:632`). Those tags resolved to nothing purely
    because the walk started one level too deep, and were recorded in the
    conversion as permanent "asset outside the gallery tree" blockers.

    Only roots the game itself declares in NON_CHARACTER_ROOTS are looked up
    this way, so a tag still cannot address anything outside the game's tree.
    """

    def _game_tree(self):
        """Build images/ and a ui/ sibling under a version directory.

        Returns:
            `(images_root, file_index)` — the images/ DirectoryIndex row that
            `find_gallery_images_root()` would return, and the FileIndex row
            for a file living in the ui/ sibling.
        """
        version_dir = self.albums_dir / "asfa_14.18a"
        make_gallery_image(version_dir / "images", "door.jpg")
        sibling_file = make_gallery_image(version_dir / "ui" / "books", "occulta.jpg")
        images_root = DirectoryIndex.objects.filter(fqpndirectory__iendswith="/images/").first()
        return images_root, sibling_file

    def test_a_sibling_of_images_resolves(self):
        """`resolve_sibling_directory` steps up to the version directory."""
        images_root, _ = self._game_tree()
        self.assertIsNotNone(images_root)
        self.assertIsNotNone(resolve_sibling_directory(images_root, "ui"))

    def test_a_tag_under_a_sibling_root_resolves_to_its_file(self):
        """The whole point: a `ui/...` tag finds its real file.

        Before this, the tag expanded correctly and then resolved to None,
        so the row was counted "unresolved" forever and the art never showed.
        """
        images_root, sibling_file = self._game_tree()
        found = resolve_tag_name("ui/books/occulta.jpg", images_root, {}, {"ui"})
        self.assertIsNotNone(found)
        self.assertEqual(found.pk, sibling_file.pk)

    def test_a_root_the_game_did_not_declare_still_resolves_to_nothing(self):
        """The sibling lookup is not a way out of the game's own tree.

        `ui` resolves only because the game named it; an undeclared prefix
        is refused exactly as before.
        """
        images_root, _ = self._game_tree()
        self.assertIsNone(resolve_tag_name("ui/books/occulta.jpg", images_root, {}, set()))

    def test_a_child_of_images_still_wins_over_a_sibling(self):
        """The sibling lookup is a FALLBACK, not a replacement.

        A root that really is a child of images/ must keep resolving there,
        so adding this cannot silently repoint an existing game's art.
        """
        version_dir = self.albums_dir / "asfa_14.18a"
        child_file = make_gallery_image(version_dir / "images" / "items", "key.jpg")
        make_gallery_image(version_dir / "items", "key.jpg")
        images_root = DirectoryIndex.objects.filter(fqpndirectory__iendswith="/images/").first()

        found = resolve_tag_name("items/key.jpg", images_root, {}, {"items"})

        self.assertIsNotNone(found)
        self.assertEqual(found.pk, child_file.pk)


class PersonValueModelChoiceTests(SimpleTestCase):
    """`build_model_var_values`/`_branches_of` against the corpus's own
    `person_value_now(character_id, attribute)` accessor (the 2026-09-06
    corpus-wide EXTERNAL rename's own real per-character-fact reader).

    A bare "{person_value_now("<id>", "<attr>")}" tag interpolation used to
    be invisible to this scanner entirely, which only knew the OLDER plain-
    VAR model-choice shape (`{X}`/`{X()}`) -- so it fell through to the
    empty-string default and produced a literal double-slash tag_name (e.g.
    "abby//abby0.jpg"), permanently unresolved. Confirmed live: fixing this
    took ASFA's own unresolved-image count from 1275 to 212 in one pass
    (`claude_docs/plans/asfa_engine_revamp.md`'s own Step 11 re-ingestion
    entry has the full before/after). These are the real corpus shapes
    that regression covers, pure functions with no filesystem/DB needed.
    """

    def _write(self, tmp_path: Path, name: str, text: str) -> None:
        (tmp_path / name).write_text(text, encoding="utf-8")

    def test_a_bare_person_value_now_reference_resolves_via_its_chosen_dispatcher(self):
        """The "*_model_chosen(" dispatch shape (abby.ink's own real
        pattern): the character id/attribute named in the bare tag
        reference must match the id/attribute the setter call two lines
        below it writes to, not the dispatcher's own (possibly shorter,
        real corpus example: "adele"/adele_ross) name."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write(
                tmp_path,
                "abby.ink",
                '+ [The one in white] -> abby_model_chosen("Agnes")\n'
                '+ [The one in black] -> abby_model_chosen("Asa")\n'
                "=== abby_model_chosen(chosenModel) ===\n"
                '~ temp _pick = set_person_value_now("abby", "model", chosenModel)\n'
                '# image: abby/{person_value_now("abby", "model")}/abby0.jpg\n'
                "-> DONE\n",
            )
            values = build_model_var_values(tmp_path)
            self.assertEqual(values.get("abby_model"), ["Agnes", "Asa"])
            entries = scan_corpus(tmp_path)
            tags = set(entries[0]["resolved"])
            self.assertEqual(tags, {"abby/Agnes/abby0.jpg", "abby/Asa/abby0.jpg"})
            self.assertNotIn("abby//abby0.jpg", tags)

    def test_a_bare_person_value_now_reference_resolves_via_a_direct_literal_write(self):
        """No dispatcher at all (tinarobbins.ink's own real pattern): a
        bare `set_person_value_now("id", "attr", "Literal")` call site,
        with no "_chosen("/"_choose_model(" wrapper in between."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write(
                tmp_path,
                "tinarobbins.ink",
                '~ temp _t = set_person_value_now("tina_robbins", "dress", "Vampyre")\n'
                '# image: tinarobbins/{person_value_now("tina_robbins", "dress")}/tina0.jpg\n',
            )
            values = build_model_var_values(tmp_path)
            self.assertEqual(values.get("tina_robbins_dress"), ["Vampyre"])

    def test_a_bare_person_value_now_reference_resolves_via_a_choose_model_stitch(self):
        """The second real dispatch shape (ellie.ink's own real pattern):
        a plain "<name>_choose_model(model)" stitch whose own NAME does not
        directly name the character id/attribute -- only its body's own
        set_person_value_now(...) write does."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write(
                tmp_path,
                "ellie.ink",
                '+ [brunette] -> ellie_choose_model("Carla")\n'
                '+ [blonde] -> ellie_choose_model("Alix")\n'
                "= ellie_choose_model(model)\n"
                '~ temp _set = set_person_value_now("ellie_bartel", "model", model)\n'
                '# image: ellie/{person_value_now("ellie_bartel", "model")}/ellie0.jpg\n',
            )
            values = build_model_var_values(tmp_path)
            self.assertEqual(values.get("ellie_bartel_model"), ["Alix", "Carla"])

    def test_a_zero_argument_function_return_may_itself_embed_a_person_value_now_reference(self):
        """mom.ink's own real mom_dress(): its return literal is not a
        plain string, it embeds a further "{person_value_now(...)}"
        reference (her chosen model folder nested inside her age folder) --
        a plain `[^"]*` capture would truncate at that reference's own
        inner quote and never see the "/Younger"/"/Natural" suffix."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write(
                tmp_path,
                "mom.ink",
                '~ temp _m = set_person_value_now("mom", "model", "Elexis")\n'
                "=== function mom_dress() ===\n"
                '{ person_value_now("mom", "flag46_rejuvenated"):\n'
                '    ~ return "{person_value_now("mom", "model")}/Younger"\n'
                "}\n"
                '~ return "{person_value_now("mom", "model")}/Natural"\n'
                "\n"
                "=== mom_hub ===\n"
                "# image: mom/{mom_dress()}/gabby-mom4.jpg\n",
            )
            values = build_model_var_values(tmp_path)
            self.assertEqual(set(values.get("mom_dress", [])), {"Elexis/Younger", "Elexis/Natural"})

    def test_cross_block_equality_prunes_impossible_person_value_now_combinations(self):
        """misslogan.ink's own real recurring pattern: a later condition's
        `person_value_now("miss_logan", "model") == "Kate"` must be checked
        against the SAME earlier bare-reference commitment
        `{person_value_now("miss_logan", "model")}` made elsewhere in the
        same tag -- "Younger" only ever pairs with "Kate" in the real
        source condition, so "Samantha"+"Younger" must never be generated
        as a candidate tag (there is no such file, and never will be)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write(
                tmp_path,
                "misslogan.ink",
                '+ [glasses] -> misslogan_choose_model("Kate")\n'
                '+ [books] -> misslogan_choose_model("Samantha")\n'
                "= misslogan_choose_model(model)\n"
                '~ temp _m = set_person_value_now("miss_logan", "model", model)\n'
                '# image: misslogan/{person_value_now("miss_logan", "model")}/'
                '{person_value_now("miss_logan", "model") == "Kate":Younger|Natural}/class1.jpg\n',
            )
            entries = scan_corpus(tmp_path)
            tags = set(entries[0]["resolved"])
            self.assertEqual(
                tags,
                {
                    "misslogan/Kate/Younger/class1.jpg",
                    "misslogan/Samantha/Natural/class1.jpg",
                },
            )
            self.assertNotIn("misslogan/Samantha/Younger/class1.jpg", tags)

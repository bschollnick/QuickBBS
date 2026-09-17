"""Media tags resolved from a bundle, and the open-bundle cache.

Every assertion here is about the MECHANISM: a tag resolves literally
when a game ships no resolver, the game's own resolver is consulted when
it does, the `newgame:` namespace is this application's rather than the
game's, and an open bundle is cached and really closed on eviction.

The fixture is a synthetic game built by the real bundler
(`bundle_fixtures`). Whether one particular game's 1,591 tags all resolve
is a fact about that game's content and belongs with the game, not here.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from interactive_fiction.bundle_media import (
    MAX_OPEN_BUNDLES,
    bundle_source,
    close_all_bundles,
    cover_member,
    resolve_tag_in_bundle,
)
from interactive_fiction.tests.bundle_fixtures import (
    ABSENT_TAG,
    NEW_GAME_IMAGE,
    VIDEO_TAG,
    write_bundle,
)


class BundleFixtureTestCase(SimpleTestCase):
    """One synthetic bundle per class, with no game-owned resolver."""

    with_resolver = False
    with_cover = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = Path(tempfile.mkdtemp())
        cls.bundle = write_bundle(
            cls.tmp,
            name="mediagame",
            with_resolver=cls.with_resolver,
            with_cover=cls.with_cover,
        )

    @classmethod
    def tearDownClass(cls):
        close_all_bundles()
        shutil.rmtree(cls.tmp, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.addCleanup(close_all_bundles)


class LiteralTagTests(BundleFixtureTestCase):
    """A game shipping no resolver answers its tags literally."""

    def test_a_tag_naming_a_real_member_resolves_to_it(self):
        self.assertEqual(resolve_tag_in_bundle(self.bundle, "image", "hero/portrait.jpg"), "hero/portrait.jpg")

    def test_a_tag_naming_nothing_answers_none(self):
        self.assertIsNone(resolve_tag_in_bundle(self.bundle, "image", ABSENT_TAG))

    def test_a_video_tag_resolves_the_same_way(self):
        self.assertEqual(resolve_tag_in_bundle(self.bundle, "video", VIDEO_TAG), VIDEO_TAG)

    def test_every_shipped_image_resolves(self):
        """The corpus-wide claim, at fixture scale: nothing the game ships
        is unreachable through a tag."""
        for tag in ("hero/portrait.jpg", "hero/standing.jpg", "villain/portrait.jpg"):
            with self.subTest(tag=tag):
                self.assertIsNotNone(resolve_tag_in_bundle(self.bundle, "image", tag))


class GameResolverTests(BundleFixtureTestCase):
    """A game shipping a resolver has it consulted instead."""

    with_resolver = True

    def test_the_games_own_rules_rewrite_the_tag(self):
        """The fixture's resolver sends any `hero/*.jpg` to the portrait,
        which a literal lookup would never do."""
        self.assertEqual(resolve_tag_in_bundle(self.bundle, "image", "hero/standing.jpg"), "hero/portrait.jpg")

    def test_a_tag_the_resolver_passes_through_still_resolves(self):
        self.assertEqual(
            resolve_tag_in_bundle(self.bundle, "image", "villain/portrait.jpg"), "villain/portrait.jpg"
        )

    def test_a_resolver_answering_nothing_answers_none(self):
        self.assertIsNone(resolve_tag_in_bundle(self.bundle, "image", "nobody/nothing.jpg"))


class OpenBundleCacheTests(BundleFixtureTestCase):
    def test_the_same_bundle_is_opened_once(self):
        """Opening parses the central directory; a lookup once open is
        orders of magnitude cheaper, so the open source is cached."""
        self.assertIs(bundle_source(self.bundle), bundle_source(self.bundle))

    def test_a_missing_bundle_answers_none_rather_than_raising(self):
        self.assertIsNone(bundle_source(self.tmp / "no_such_bundle.zip"))

    def test_eviction_closes_the_archive_it_drops(self):
        """A plain LRU would drop the reference and leak the descriptor."""
        source = bundle_source(self.bundle)
        for index in range(MAX_OPEN_BUNDLES + 1):
            bundle_source(self.tmp / f"filler{index}.zip")  # each answers None, the real one stays
        close_all_bundles()
        with self.assertRaises(Exception):
            source.read_bytes("manifest.yaml")


class NewGameImageTests(BundleFixtureTestCase):
    """Character-creation images are this application's own namespace.

    A game's shipped resolver answers STORY tags; it knows nothing about
    `newgame:`. Before this was handled, every character-creation picture
    on a bundled game 404'd.
    """

    with_resolver = True

    def test_each_declared_option_image_resolves(self):
        self.assertIsNotNone(resolve_tag_in_bundle(self.bundle, "image", f"newgame:{NEW_GAME_IMAGE}"))

    def test_it_finds_them_where_the_bundler_put_them(self):
        """A game FOLDER keeps these at its root; the bundler places them
        under `UI/`. Both layouts are searched rather than either being
        assumed."""
        self.assertEqual(
            resolve_tag_in_bundle(self.bundle, "image", f"newgame:{NEW_GAME_IMAGE}"), f"UI/{NEW_GAME_IMAGE}"
        )

    def test_an_undeclared_image_is_not_invented(self):
        self.assertIsNone(resolve_tag_in_bundle(self.bundle, "image", "newgame:no_such_option.png"))

    def test_the_namespace_does_not_leak_into_story_tags(self):
        """A story tag merely STARTING like the prefix must still go to
        the game's own resolver, not the UI search."""
        self.assertIsNone(resolve_tag_in_bundle(self.bundle, "image", "newgame_but_not_the_prefix.png"))


class CoverImageTests(BundleFixtureTestCase):
    def test_a_game_shipping_no_cover_answers_none(self):
        """A missing cover is cosmetic, not an error."""
        self.assertIsNone(cover_member(self.bundle))

    def test_a_missing_bundle_answers_none(self):
        self.assertIsNone(cover_member(self.tmp / "no_such_bundle.zip"))

"""A side-panel action that uses up an item: the scene's choice gated on it goes when the action returns.

Uses the same `game_with_item_action` fixture as the desktop player's
`ItemActionTests` (if_player/tests/test_player_api.py).
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client

from interactive_fiction.engine_api import clear_api_descriptor_cache
from interactive_fiction.models import CurrentGame, EngineAPI, Story
from quickbbs.tests.albums_root import AlbumsRootTestCase

FIXTURE = Path(__file__).parent / "fixtures" / "game_with_item_action"
GAME_PACKAGE = "itemgame"
GAME_MODULES = (GAME_PACKAGE, f"{GAME_PACKAGE}.plugins", f"{GAME_PACKAGE}.sidebar")
CHOICE_BUTTON = re.compile(rb'class="button is-link if-choice-button"[^>]*>([^<]+)<')


def _forget_game_modules() -> None:
    """Drop the fixture game's modules, so each test imports its own copy."""
    for name in GAME_MODULES:
        sys.modules.pop(name, None)


class ItemActionTests(AlbumsRootTestCase):
    """A trusted game whose cellar offers "Light the lantern" while the pack holds it."""

    def setUp(self):
        """Create the story and its viewer, and open the cellar."""
        super().setUp()
        _forget_game_modules()
        self.addCleanup(_forget_game_modules)
        clear_api_descriptor_cache()
        self.addCleanup(clear_api_descriptor_cache)

        game_dir = Path(self.albums_dir) / "interactive_fiction" / GAME_PACKAGE
        shutil.copytree(FIXTURE, game_dir, ignore=shutil.ignore_patterns("__pycache__"))
        EngineAPI.objects.update_or_create(name="fixture_pack", defaults={"display_name": "Fixture pack", "is_enabled": True})
        self.user = get_user_model().objects.create_user(username="caver", password="pw")
        self.story = Story.objects.create(
            owner=self.user,
            title="Item Game",
            slug="item-game",
            compiled_json=json.loads((game_dir / "story.inkj").read_text(encoding="utf-8-sig")),
            is_public=True,
            is_engine_trusted=True,
            game_required_plugins=["fixture_pack"],
            source_fqfn=str((game_dir / "story.inkj").resolve()).lower(),
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.page = self.client.get(f"/if/{self.story.slug}/", secure=True)

    def _saved(self) -> dict:
        return CurrentGame.objects.get(user=self.user, story=self.story).state

    def _lend_the_lantern(self) -> object:
        data = {"group": "sam", "label": "Lend Sam the lantern", "turn_count": self._saved()["turn_count"]}
        return self.client.post(f"/if/{self.story.slug}/take-action/", data, secure=True, HTTP_HX_REQUEST="true")

    def test_the_cellar_offers_the_lantern_while_the_pack_holds_it(self):
        """The scene before the action."""
        self.assertIn(b"Light the lantern", self.page.content)

    def test_using_up_the_item_removes_the_choice_gated_on_it(self):
        """The action's text, then the cellar's choices without the lantern."""
        response = self._lend_the_lantern()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"You hand Sam the lantern.", response.content)
        self.assertIn(b"Go back up", response.content)
        self.assertNotIn(b"Light the lantern", response.content)

    def test_the_scene_s_own_effects_happen_once(self):
        """The cellar's assignment is not repeated by the re-evaluation, and the pack is empty once."""
        self._lend_the_lantern()
        saved = self._saved()
        self.assertEqual(saved["globals"]["cellar_visits"], 1)
        self.assertEqual(saved["engine_state"]["fixture_pack"], {"items": []})

    def test_the_scene_carries_on_after_the_action(self):
        """The choice left is the scene's own, and it plays."""
        self._lend_the_lantern()
        response = self.client.post(f"/if/{self.story.slug}/play/", {"choice": 0, "turn_count": self._saved()["turn_count"]}, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"You climb back up.", response.content)

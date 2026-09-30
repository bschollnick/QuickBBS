"""The exits compass in the web player, and the panel refreshed on every turn.

Uses the same `game_with_exits` fixture as the desktop player's
`TakeExitTests` (if_player/tests/test_player_api.py), so the two players are
held to the same exits for the same game.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import Client

from ink_engine.game_panel import exits_section
from interactive_fiction.engine_api import clear_api_descriptor_cache
from interactive_fiction.models import CurrentGame, EngineAPI, Story
from quickbbs.tests.albums_root import AlbumsRootTestCase

FIXTURE = Path(__file__).parent / "fixtures" / "game_with_exits"
GAME_PACKAGE = "exitsgame"
GAME_MODULES = (GAME_PACKAGE, f"{GAME_PACKAGE}.plugins", f"{GAME_PACKAGE}.sidebar")
EXIT_ID_INPUT = re.compile(rb'name="exit_id" value="([^"]+)"')


def _forget_game_modules() -> None:
    """Drop the fixture game's modules, so each test imports its own copy."""
    for name in GAME_MODULES:
        sys.modules.pop(name, None)


class TakeExitTests(AlbumsRootTestCase):
    """A trusted three-column game whose panel draws a compass of the room's exits."""

    def setUp(self):
        super().setUp()
        _forget_game_modules()
        self.addCleanup(_forget_game_modules)
        clear_api_descriptor_cache()
        self.addCleanup(clear_api_descriptor_cache)

        game_dir = Path(self.albums_dir) / "interactive_fiction" / GAME_PACKAGE
        shutil.copytree(FIXTURE, game_dir, ignore=shutil.ignore_patterns("__pycache__"))
        EngineAPI.objects.update_or_create(name="fixture_map", defaults={"display_name": "Fixture map", "is_enabled": True})
        self.user = get_user_model().objects.create_user(username="explorer", password="pw")
        self.story = Story.objects.create(
            owner=self.user,
            title="Exits Game",
            slug="exits-game",
            compiled_json=json.loads((game_dir / "story.inkj").read_text(encoding="utf-8-sig")),
            is_public=True,
            is_engine_trusted=True,
            game_required_plugins=["fixture_map"],
            source_fqfn=str((game_dir / "story.inkj").resolve()).lower(),
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.page = self.client.get(f"/if/{self.story.slug}/", secure=True)

    def _turn_count(self) -> int:
        return CurrentGame.objects.get(user=self.user, story=self.story).turn_count

    def _post(self, route: str, data: dict) -> object:
        return self.client.post(f"/if/{self.story.slug}/{route}/", data, secure=True, HTTP_HX_REQUEST="true")

    def _take(self, exit_id: str, turn_count: int | None = None) -> object:
        return self._post("take-exit", {"exit_id": exit_id, "turn_count": self._turn_count() if turn_count is None else turn_count})

    @staticmethod
    def _exit_ids(content: bytes) -> list[str]:
        return [match.decode() for match in EXIT_ID_INPUT.findall(content)]

    def test_the_page_draws_a_compass_of_the_room_exits(self):
        """The same exits, in the same order, as the desktop player shows for this room."""
        self.assertEqual(self._exit_ids(self.page.content), ["position:s", "position:up", "to:cellar"])

    def test_the_movement_choice_is_hidden_while_a_compass_is_drawn(self):
        """The story's GO choice is left out; Wait keeps its story index and is numbered 1."""
        self.assertIn(b"Wait", self.page.content)
        self.assertNotIn(b'value="1" class="button is-link if-choice-button"', self.page.content)
        self.assertIn(b'data-choice-key="1">Wait', self.page.content)

    def test_a_blocked_exit_is_drawn_but_disabled(self):
        """The sealed attic shows on the compass, but its button cannot be pressed."""
        up_form = self.page.content.split(b'value="position:up"')[1].split(b"</form>")[0]
        self.assertIn(b"disabled", up_form)

    def test_taking_an_exit_narrates_advances_and_refreshes_the_panel(self):
        """An exit is a real turn: travel text, arrival, a new turn count, a transcript entry, the new room's exits."""
        before = self._turn_count()
        response = self._take("position:s")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"You step outside.", response.content)
        self.assertIn(b"You are in the garden.", response.content)
        self.assertEqual(self._turn_count(), before + 1)
        # The panel comes back out of band, showing the garden's exits.
        self.assertIn(b'id="if-game-panel" class="if-game-panel" hx-swap-oob="true"', response.content)
        self.assertEqual(self._exit_ids(response.content), ["position:n"])
        transcript = CurrentGame.objects.get(user=self.user, story=self.story).state["transcript"]
        self.assertEqual(transcript[-1]["chosen_label"], "the garden")

    def test_the_synthesized_way_back_can_be_taken(self):
        """The return exit add_missing_return_exits() made leads back, narrated."""
        self._take("position:s")
        back = self._take("position:n")
        self.assertIn(b"You go back inside.", back.content)
        self.assertIn(b"You are in the hall.", back.content)

    def test_an_ordinary_turn_refreshes_the_panel(self):
        """play_submit, not only a panel route, returns the panel for this turn."""
        self._take("position:s")
        response = self._post("play", {"choice": 0, "turn_count": self._turn_count()})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"You are in the garden.", response.content)
        self.assertEqual(self._exit_ids(response.content), ["position:n"])

    def test_undo_refreshes_the_panel_to_the_earlier_room(self):
        """Undo returns the hall's exits along with the hall's text."""
        self._take("position:s")
        response = self._post("undo", {})
        self.assertEqual(self._exit_ids(response.content), ["position:s", "position:up", "to:cellar"])

    def test_a_blocked_exit_is_refused(self):
        """Posting a blocked exit's id is refused and the turn does not advance."""
        before = self._turn_count()
        self.assertEqual(self._take("position:up").status_code, 400)
        self.assertEqual(self._turn_count(), before)

    def test_an_exit_the_room_does_not_offer_is_refused(self):
        """An id the room does not offer, or none at all, is refused."""
        self.assertEqual(self._take("position:e").status_code, 400)
        self.assertEqual(self._take("").status_code, 400)

    def test_a_stale_turn_count_is_rejected(self):
        """The concurrent-tab guard applies to exits as it does to choices."""
        before = self._turn_count()
        self.assertEqual(self._take("position:s", turn_count=before + 5).status_code, 409)
        self.assertEqual(self._turn_count(), before)

    def test_the_end_of_the_story_disables_every_exit(self):
        """A passable exit is a live button until the story ends."""
        section = exits_section([{"to": "garden", "position": "s", "label": "the garden", "passable": True, "arrival_knot": "garden"}])
        context = {"story": self.story, "turn_count": 3, "panel_sections": [section]}

        def forms(done: bool) -> list[str]:
            html = render_to_string("interactive_fiction/play_panel.jinja", {**context, "done": done}, using="Jinja2")
            return [form for form in html.split("</form>")[:-1] if 'value="position:s"' in form]

        self.assertEqual(len(forms(done=False)), 1)
        self.assertNotIn("disabled", forms(done=False)[0])
        self.assertIn("disabled", forms(done=True)[0])


class ClassicLayoutTests(AlbumsRootTestCase):
    """A story whose layout draws no panel gets no panel fragment on a turn."""

    def test_a_turn_returns_no_panel(self):
        """A classic-layout story's turn response carries no panel, and keeps its GO choice."""
        user = get_user_model().objects.create_user(username="reader", password="pw")
        compiled = json.loads((FIXTURE / "story.inkj").read_text(encoding="utf-8-sig"))
        story = Story.objects.create(owner=user, title="Plain", slug="plain-story", compiled_json=compiled, is_public=True)
        client = Client()
        client.force_login(user)
        client.get(f"/if/{story.slug}/", secure=True)
        turn_count = CurrentGame.objects.get(user=user, story=story).turn_count
        response = client.post(f"/if/{story.slug}/play/", {"choice": 0, "turn_count": turn_count}, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"if-game-panel", response.content)
        # Without a compass, the story's own movement choice stays in the list.
        self.assertIn(b"GO", response.content)

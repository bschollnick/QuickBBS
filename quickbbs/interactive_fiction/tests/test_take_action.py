"""A panel action section in the web player: story actions run as interludes.

Uses the same `game_with_actions` fixture as the desktop player's
`TakeActionTests` (if_player/tests/test_player_api.py).
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

from interactive_fiction.engine_api import clear_api_descriptor_cache
from interactive_fiction.models import CurrentGame, Story
from quickbbs.tests.albums_root import AlbumsRootTestCase

FIXTURE = Path(__file__).parent / "fixtures" / "game_with_actions"
GAME_PACKAGE = "actionsgame"
GAME_MODULES = (GAME_PACKAGE, f"{GAME_PACKAGE}.sidebar")
LABEL_INPUT = re.compile(rb'name="label" value="([^"]+)"')


def _forget_game_modules() -> None:
    """Drop the fixture game's modules, so each test imports its own copy."""
    for name in GAME_MODULES:
        sys.modules.pop(name, None)


class TakeActionTests(AlbumsRootTestCase):
    """A trusted three-column game whose panel slot lists its companion's actions."""

    def setUp(self):
        """Create the story and its viewer."""
        super().setUp()
        _forget_game_modules()
        self.addCleanup(_forget_game_modules)
        clear_api_descriptor_cache()
        self.addCleanup(clear_api_descriptor_cache)

        game_dir = Path(self.albums_dir) / "interactive_fiction" / GAME_PACKAGE
        shutil.copytree(FIXTURE, game_dir, ignore=shutil.ignore_patterns("__pycache__"))
        self.user = get_user_model().objects.create_user(username="shopper", password="pw")
        self.story = Story.objects.create(
            owner=self.user,
            title="Actions Game",
            slug="actions-game",
            compiled_json=json.loads((game_dir / "story.inkj").read_text(encoding="utf-8-sig")),
            is_public=True,
            is_engine_trusted=True,
            source_fqfn=str((game_dir / "story.inkj").resolve()).lower(),
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.page = self.client.get(f"/if/{self.story.slug}/", secure=True)

    def _turn_count(self) -> int:
        return CurrentGame.objects.get(user=self.user, story=self.story).turn_count

    def _take(self, group: str, label: str, turn_count: int | None = None) -> object:
        data = {"group": group, "label": label, "turn_count": self._turn_count() if turn_count is None else turn_count}
        return self.client.post(f"/if/{self.story.slug}/take-action/", data, secure=True, HTTP_HX_REQUEST="true")

    @staticmethod
    def _labels(content: bytes) -> list[str]:
        return [match.decode() for match in LABEL_INPUT.findall(content)]

    def test_the_page_lists_the_actions_in_the_slot(self):
        """The same actions, in the same order, as the desktop player shows."""
        self.assertIn(b"Companions", self.page.content)
        self.assertEqual(self._labels(self.page.content), ["Talk to Sam", "Send Sam home", "Check the time"])

    def test_a_tab_switch_lists_the_actions_too(self):
        """A tab switch lists the actions too."""
        response = self.client.get(f"/if/{self.story.slug}/panel/main/", secure=True)
        self.assertEqual(self._labels(response.content), ["Talk to Sam", "Send Sam home", "Check the time"])

    def test_an_action_runs_as_a_turn_and_returns_to_the_scene(self):
        """An action runs as a turn and returns to the scene."""
        before = self._turn_count()
        response = self._take("sam", "Talk to Sam")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Sam grins.", response.content)
        self.assertIn(b"Browse", response.content)
        self.assertIn(b"Leave", response.content)
        self.assertEqual(self._turn_count(), before + 1)
        saved = CurrentGame.objects.get(user=self.user, story=self.story).state
        self.assertEqual(saved["transcript"][-1]["chosen_label"], "Talk to Sam")
        self.assertEqual(saved["interludes"], [])

    def test_the_panel_is_refreshed_after_an_action(self):
        """The panel is refreshed after an action."""
        response = self._take("sam", "Send Sam home")
        self.assertIn(b'id="if-game-panel" class="if-game-panel" hx-swap-oob="true"', response.content)
        self.assertEqual(self._labels(response.content), ["Check the time"])

    def test_the_scene_carries_on_after_an_action(self):
        """The scene carries on after an action."""
        self._take("", "Check the time")
        response = self.client.post(f"/if/{self.story.slug}/play/", {"choice": 0, "turn_count": self._turn_count()}, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"You browse.", response.content)

    def test_an_action_not_offered_now_is_refused(self):
        """An action not offered now is refused."""
        before = self._turn_count()
        self.assertEqual(self._take("sam", "Dance").status_code, 400)
        self._take("sam", "Send Sam home")
        self.assertEqual(self._take("sam", "Talk to Sam").status_code, 400)
        self.assertEqual(self._turn_count(), before + 1)

    def test_a_stale_turn_count_is_rejected(self):
        """A stale turn count is rejected."""
        before = self._turn_count()
        self.assertEqual(self._take("sam", "Talk to Sam", turn_count=before + 5).status_code, 409)
        self.assertEqual(self._turn_count(), before)

    def test_undo_restores_the_turn_before_the_action(self):
        """Undo restores the turn before the action."""
        self._take("sam", "Send Sam home")
        response = self.client.post(f"/if/{self.story.slug}/undo/", {}, secure=True, HTTP_HX_REQUEST="true")
        self.assertEqual(self._labels(response.content), ["Talk to Sam", "Send Sam home", "Check the time"])


class PanelCommandReactionTests(TakeActionTests):
    """A panel command answering a knot plays it as a turn; a message-only command replays nothing."""

    def _command(self, command_id: str, turn_count: int | None = None) -> object:
        data = {"turn_count": self._turn_count() if turn_count is None else turn_count}
        return self.client.post(f"/if/{self.story.slug}/panel-command/{command_id}/bell/", data, secure=True, HTTP_HX_REQUEST="true")

    def _saved(self) -> dict:
        return CurrentGame.objects.get(user=self.user, story=self.story).state

    def test_a_knot_answer_plays_its_reaction_as_a_turn(self):
        """The reaction's text, a new turn, the label in the transcript and the message in the panel."""
        before = self._turn_count()
        response = self._command("ring")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"The bell rings and Sam leaves.", response.content)
        self.assertIn(b"You ring the bell.", response.content)
        self.assertEqual(self._turn_count(), before + 1)
        self.assertEqual(self._saved()["transcript"][-1]["chosen_label"], "Ring the bell")

    def test_the_reaction_shows_the_scene_again_with_fresh_choices(self):
        """The reaction diverts back to the scene, so the panel and choices are re-evaluated."""
        response = self._command("ring")
        self.assertIn(b"Browse", response.content)
        self.assertEqual(self._labels(response.content), ["Check the time"])

    def test_a_message_only_command_does_not_replay_the_turn(self):
        """No turn, and the scene's own assignment does not run again."""
        before_turn, before_shows = self._turn_count(), self._saved()["globals"]["scene_shows"]
        response = self._command("look")
        self.assertIn(b"A brass bell.", response.content)
        self.assertEqual(self._turn_count(), before_turn)
        self.assertEqual(self._saved()["globals"]["scene_shows"], before_shows)

    def test_a_reaction_can_be_undone(self):
        """Undo returns to the turn before the command."""
        self._command("ring")
        response = self.client.post(f"/if/{self.story.slug}/undo/", {}, secure=True, HTTP_HX_REQUEST="true")
        self.assertEqual(self._labels(response.content), ["Talk to Sam", "Send Sam home", "Check the time"])

    def test_a_stale_command_is_rejected(self):
        """The concurrent-tab guard applies to a reaction as to a choice."""
        before = self._turn_count()
        self.assertEqual(self._command("ring", turn_count=before + 5).status_code, 409)
        self.assertEqual(self._turn_count(), before)


class ActionSectionTemplateTests(AlbumsRootTestCase):
    """What play_panel_actions.jinja draws for a filled action section."""

    def setUp(self):
        """Create the story and its viewer."""
        super().setUp()
        user = get_user_model().objects.create_user(username="viewer", password="pw")
        self.story = Story.objects.create(owner=user, title="Shown", slug="shown-story", compiled_json={"inkVersion": 21, "root": []})

    def _render(self, **extra: object) -> str:
        section = {
            "heading": "Companions",
            "layout": "actions",
            "knot": "companion_actions",
            "empty_text": "Nobody is with you.",
            "groups": [
                {
                    "id": "sam",
                    "image_urls": ["/if/shown-story/image/sam-face.png/"],
                    "actions": [{"group": "sam", "label": "Talk to Sam", "target": "x"}],
                }
            ],
        }
        context = {"story": self.story, "turn_count": 3, "panel_sections": [], "panel_slots": [section], **extra}
        return render_to_string("interactive_fiction/play_panel.jinja", context, using="Jinja2")

    def test_a_group_row_shows_its_picture(self):
        """A group row shows its picture."""
        self.assertIn('<img class="if-panel-row-image" src="/if/shown-story/image/sam-face.png/"', self._render())

    def test_the_end_of_the_story_disables_every_action(self):
        """The end of the story disables every action."""
        self.assertNotIn("disabled", self._render(done=False))
        self.assertIn("disabled", self._render(done=True))

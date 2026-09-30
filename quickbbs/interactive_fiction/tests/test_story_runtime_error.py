"""A turn the story stops with an Ink runtime error: the player sees the error, and nothing is saved.

Fixtures: story_runtime_error.ink runs out of content inside a tunnel after
its first choice; story_runtime_error_opening.ink runs out on its opening
turn. inklecate stops both with a RUNTIME ERROR.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from interactive_fiction.models import CurrentGame, Story

if TYPE_CHECKING:
    from django.contrib.auth.models import _User

FIXTURES = Path(__file__).parent / "fixtures"


def _story(owner: _User, name: str) -> Story:
    compiled = json.loads((FIXTURES / f"{name}.ink.json").read_text(encoding="utf-8-sig"))
    return Story.objects.create(owner=owner, title=name, slug=name.replace("_", "-"), compiled_json=compiled, is_public=True)


class MidTurnRuntimeErrorTests(TestCase):
    """The choice that leads into the dead end."""

    def setUp(self):
        """Open the story at its first choice."""
        self.user = get_user_model().objects.create_user(username="walker", password="pw")
        self.story = _story(self.user, "story_runtime_error")
        self.client = Client()
        self.client.force_login(self.user)
        self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.before = CurrentGame.objects.get(user=self.user, story=self.story)

    def _go_in(self) -> object:
        data = {"choice": 0, "turn_count": self.before.turn_count}
        return self.client.post(f"/if/{self.story.slug}/play/", data, secure=True, HTTP_HX_REQUEST="true")

    def test_the_player_sees_the_error(self):
        """The partial names the cause, with status 200 so htmx swaps it in."""
        response = self._go_in()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"The story stopped with an error", response.content)
        self.assertIn(b"unexpectedly reached end of content", response.content)

    def test_the_game_is_not_changed(self):
        """The row keeps the turn before the choice."""
        self._go_in()
        after = CurrentGame.objects.get(user=self.user, story=self.story)
        self.assertEqual((after.turn_count, after.state), (self.before.turn_count, self.before.state))


class OpeningTurnRuntimeErrorTests(TestCase):
    """A story whose first turn dead-ends."""

    def test_the_page_shows_the_error_and_no_game_is_created(self):
        """A full page load gets the partial with status 500; no CurrentGame row is written."""
        user = get_user_model().objects.create_user(username="opener", password="pw")
        story = _story(user, "story_runtime_error_opening")
        client = Client()
        client.force_login(user)
        response = client.get(f"/if/{story.slug}/", secure=True)
        self.assertEqual(response.status_code, 500)
        self.assertIn(b"ran out of content", response.content)
        self.assertFalse(CurrentGame.objects.filter(user=user, story=story).exists())

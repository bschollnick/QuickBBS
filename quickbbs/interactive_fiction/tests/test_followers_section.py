"""A panel followers section in the web player: a head shot per follower,
a "Speak to" button only where the story's menu knot offers one, and a
rule between two followers.

Uses the same `game_with_followers` fixture as the desktop player's
render test (`if_player/tests/shell/test_followers_section.mjs`).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client

from interactive_fiction.engine_api import clear_api_descriptor_cache
from interactive_fiction.models import CurrentGame, Story
from quickbbs.tests.albums_root import AlbumsRootTestCase

FIXTURE = Path(__file__).parent / "fixtures" / "game_with_followers"
GAME_PACKAGE = "followersgame"
GAME_MODULES = (GAME_PACKAGE, f"{GAME_PACKAGE}.sidebar")


def _forget_game_modules() -> None:
    """Drop the fixture game's modules, so each test imports its own copy."""
    for name in GAME_MODULES:
        sys.modules.pop(name, None)


class FollowersSectionTests(AlbumsRootTestCase):
    """A trusted three-column game whose panel slot lists its two followers."""

    def setUp(self):
        """Create the story and its viewer."""
        super().setUp()
        _forget_game_modules()
        self.addCleanup(_forget_game_modules)
        clear_api_descriptor_cache()
        self.addCleanup(clear_api_descriptor_cache)

        game_dir = Path(self.albums_dir) / "interactive_fiction" / GAME_PACKAGE
        shutil.copytree(FIXTURE, game_dir, ignore=shutil.ignore_patterns("__pycache__"))
        self.user = get_user_model().objects.create_user(username="viewer", password="pw")
        self.story = Story.objects.create(
            owner=self.user,
            title="Followers Game",
            slug="followers-game",
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

    def test_the_page_shows_the_section_heading(self):
        """The section heading is drawn."""
        self.assertIn(b"Followers", self.page.content)

    def test_a_row_per_follower(self):
        """A row per follower, each labelled with its own name.

        A bare-folder fixture story (`source_fqfn` an `.inkj`, not a
        `.zip`) resolves no media at all -- `Story.bundle_path` answers
        None for anything but a real bundle, matching production ingestion
        ("A game enters the database as a bundle", `ingestion.py`'s own
        module docstring) -- so the head shot itself is proved at the
        engine level (`test_asfa_followers_sidebar.py`,
        `ink_engine/tests/test_game_panel_followers.py`) and by the
        desktop player's own render test, not here.
        """
        content = self.page.content
        self.assertIn(b"Sam", content)
        self.assertIn(b"Ada", content)

    def test_only_the_follower_with_a_matching_group_gets_a_button(self):
        """Sam's row has a "Speak to" button; Ada's row has none."""
        content = self.page.content
        self.assertIn(b'value="Talk to Sam"', content)
        self.assertNotIn(b"Talk to Ada", content)

    def test_two_rows_are_separated_by_a_rule(self):
        """Two followers render as separate rows joined by a rule."""
        self.assertIn(b"if-panel-follower-rule", self.page.content)

    def test_speaking_to_sam_runs_as_an_interlude_turn(self):
        """Running the row's own action returns to the scene, like an action section's does."""
        before = self._turn_count()
        response = self.client.post(
            f"/if/{self.story.slug}/take-action/",
            {"group": "sam", "label": "Talk to Sam", "turn_count": before},
            secure=True,
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Sam grins.", response.content)
        self.assertIn(b"Browse", response.content)
        self.assertEqual(self._turn_count(), before + 1)

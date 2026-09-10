"""Character-creation feature tests: the generic NEW_GAME_FIELDS manifest
schema (Story.game_new_game_fields), the /if/<slug>/new-game/ form/submit
views, and how play()/play_restart() route around them.

Split out from test_views.py to keep that module under pylint's
max-module-lines threshold. Uses Django's real test client against a
Story row built from tests/fixtures/character_creation_globals.ink.json
(a real compiled story declaring player_name/player_gender/
player_master_title as globals, so a submitted answer's effect on the
story's own first-turn text can be asserted directly) — TestCase (never
TransactionTestCase, per standing project rule).
"""

from __future__ import annotations

import json
from pathlib import Path as FilePath

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from interactive_fiction.models import CurrentGame, Story

FIXTURES = FilePath(__file__).parent / "fixtures"


def _load_compiled_json() -> dict:
    with open(FIXTURES / "section3_choices.ink.json", encoding="utf-8") as f:
        return json.load(f)


def _load_character_creation_globals_json() -> dict:
    with open(FIXTURES / "character_creation_globals.ink.json", encoding="utf-8") as f:
        return json.load(f)


def _load_checkbox_fields_json() -> dict:
    with open(FIXTURES / "character_creation_checkbox_fields.ink.json", encoding="utf-8") as f:
        return json.load(f)


CHARACTER_CREATION_FIELDS = [
    {
        "var": "player_name",
        "type": "text",
        "label": "What is your name?",
        "default": "Bob",
    },
    {
        "var": "player_gender",
        "type": "radio_image",
        "label": "Are you a man or a woman?",
        "default": {"player_gender": "man"},
        "options": [
            {"value": {"player_gender": "man"}, "label": "Male", "image": "male.png"},
            {"value": {"player_gender": "woman"}, "label": "Female", "image": "female.png"},
            {"value": {"player_gender": "futa"}, "label": "Futa", "image": "futa.png"},
        ],
    },
]


class PlayWithoutCharacterCreationTests(TestCase):
    """A story with no game_new_game_fields (the default/majority case)
    is completely unaffected by the character-creation feature — the
    existing fresh-game branch in play() runs exactly as before."""

    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(username="nocreation", password="pw")
        self.story = Story.objects.create(
            owner=self.user, title="Choices", slug="no-creation-story", compiled_json=_load_compiled_json(), is_public=True
        )
        self.client.force_login(self.user)

    def test_play_goes_straight_to_the_story_not_the_creation_form(self):
        """No game_new_game_fields means the existing fresh-game branch
        runs unchanged — no creation form is ever shown."""
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Hello, traveler.", response.content)
        self.assertTrue(CurrentGame.objects.filter(user=self.user, story=self.story).exists())


class CharacterCreationViewTests(TestCase):
    """GET/POST /if/<slug>/new-game/ — the generic character-creation form."""

    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(username="creationplayer", password="pw")
        self.story = Story.objects.create(
            owner=self.user,
            title="Creation Story",
            slug="creation-story",
            compiled_json=_load_character_creation_globals_json(),
            is_public=True,
            game_new_game_fields=CHARACTER_CREATION_FIELDS,
        )
        self.client.force_login(self.user)

    def test_play_redirects_to_character_creation_before_first_game(self):
        """A story with game_new_game_fields sends a first-time visitor to
        the creation form instead of starting the game immediately."""
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertRedirects(response, f"/if/{self.story.slug}/new-game/", fetch_redirect_response=False)
        self.assertFalse(CurrentGame.objects.filter(user=self.user, story=self.story).exists())

    def test_creation_form_renders_text_and_radio_image_fields(self):
        """The form shows one input per declared field, including every
        radio_image option's own label."""
        response = self.client.get(f"/if/{self.story.slug}/new-game/", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="player_name"', response.content)
        self.assertIn(b'name="player_gender"', response.content)
        self.assertIn(b"Male", response.content)
        self.assertIn(b"Female", response.content)
        self.assertIn(b"Futa", response.content)

    def test_anonymous_is_redirected_to_login(self):
        """The form is gated behind login, matching every other game view."""
        self.client.logout()
        response = self.client.get(f"/if/{self.story.slug}/new-game/", secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_user_without_access_is_forbidden(self):
        """A user with no grant on a non-public story is rejected with 403."""
        self.story.is_public = False
        self.story.save(update_fields=["is_public"])
        other = get_user_model().objects.create_user(username="creationother", password="pw")
        self.client.force_login(other)
        response = self.client.get(f"/if/{self.story.slug}/new-game/", secure=True)
        self.assertEqual(response.status_code, 403)

    def test_submitting_text_and_radio_choice_seeds_globals_and_starts_the_game(self):
        """Submitting the form sets player_name and the chosen gender
        value as real Ink globals, visible on the story's very first turn."""
        response = self.client.post(
            f"/if/{self.story.slug}/new-game/submit/",
            {"player_name": "Alicia", "player_gender": "1"},
            secure=True,
        )
        self.assertRedirects(response, f"/if/{self.story.slug}/", fetch_redirect_response=False)
        current_game = CurrentGame.objects.get(user=self.user, story=self.story)
        self.assertTrue(current_game.state["done"] or current_game.state.get("current_choices") == [])

        play_response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertIn(b"Hello, Alicia", play_response.content)

    def test_missing_submission_falls_back_to_declared_defaults(self):
        """An empty POST falls back to each field's own declared default
        (player_name="Bob") rather than erroring."""
        self.client.post(f"/if/{self.story.slug}/new-game/submit/", {}, secure=True)
        play_response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertIn(b"Hello, Bob", play_response.content)

    def test_anonymous_submit_is_redirected_to_login(self):
        """Submitting the form while logged out is gated behind login,
        not allowed through as an anonymous CurrentGame write."""
        self.client.logout()
        response = self.client.post(f"/if/{self.story.slug}/new-game/submit/", {"player_name": "X"}, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_submit_get_is_not_allowed(self):
        """The submit endpoint only accepts POST."""
        response = self.client.get(f"/if/{self.story.slug}/new-game/submit/", secure=True)
        self.assertEqual(response.status_code, 405)


class PlayRestartWithCharacterCreationTests(TestCase):
    """POST /if/<slug>/restart/ for a story with game_new_game_fields must
    re-ask the creation questions rather than silently reusing the
    previous answers."""

    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(username="restartcreation", password="pw")
        self.story = Story.objects.create(
            owner=self.user,
            title="Restart Creation Story",
            slug="restart-creation-story",
            compiled_json=_load_character_creation_globals_json(),
            is_public=True,
            game_new_game_fields=CHARACTER_CREATION_FIELDS,
        )
        self.client.force_login(self.user)
        self.client.post(
            f"/if/{self.story.slug}/new-game/submit/",
            {"player_name": "Alicia", "player_gender": "1"},
            secure=True,
        )

    def test_restart_deletes_the_current_game_and_redirects_to_creation(self):
        """Restarting a story with creation fields deletes the existing
        CurrentGame row and hands off to the creation form via
        HX-Redirect, rather than silently reusing the previous answers."""
        response = self.client.post(f"/if/{self.story.slug}/restart/", secure=True)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], f"/if/{self.story.slug}/new-game/")
        self.assertFalse(CurrentGame.objects.filter(user=self.user, story=self.story).exists())


CHECKBOX_FIELDS = [
    {
        "var": "is_explicit_mode",
        "type": "checkbox",
        "label": "Enable explicit (X-rated) images and scenes?",
        "default": True,
    },
    {
        "var": "is_british",
        "type": "checkbox",
        "label": "Set the game in the United Kingdom (vs. the United States)?",
        "default": False,
    },
    {
        "var": "npc_born_male",
        "type": "checkbox",
        "label": "Make the town's NPC male? (slightly harder)",
        "default": False,
        "linked_vars": {"npc_name": {"True": "Alex", "False": "Robin"}},
    },
    {
        "var": "exclude_optional_content",
        "type": "checkbox",
        "label": "Exclude optional content?",
        "default": False,
        "linked_vars": {"optional_quest_counter": {"True": -1, "False": 0}},
    },
    {
        "var": "transform_spell_disabled",
        "type": "checkbox",
        "label": "Disable the Transform spell entirely?",
        "default": False,
    },
    {
        "var": "lottery_bonus",
        "type": "checkbox",
        "label": "Start with a $500 lottery win in cash?",
        "default": False,
        "add_to": {"player_money": 500},
    },
    {
        "var": "mana_bonus",
        "type": "checkbox",
        "label": "Start with +100 occult mana?",
        "default": False,
        "add_to": {"player_mana": 100},
    },
]


class CheckboxFieldTests(TestCase):
    """`checkbox` field type: plain VAR write, `linked_vars` (a checkbox
    setting a second real VAR, mirroring `radio_image`'s own
    "one choice sets several VARs" pattern), and `add_to` (an additive
    bump against the story's own real declared default, not a flat
    overwrite) — see the character-creation expansion design work.
    """

    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(username="checkboxplayer", password="pw")
        self.story = Story.objects.create(
            owner=self.user,
            title="Checkbox Story",
            slug="checkbox-story",
            compiled_json=_load_checkbox_fields_json(),
            is_public=True,
            game_new_game_fields=CHECKBOX_FIELDS,
        )
        self.client.force_login(self.user)

    def test_unchecked_checkboxes_fall_back_to_their_declared_defaults(self):
        """An empty POST (no checkbox keys submitted at all, matching a
        real browser's own behavior for every unchecked checkbox) falls
        back to each field's own declared default, not an error or a
        forced False."""
        self.client.post(f"/if/{self.story.slug}/new-game/submit/", {}, secure=True)
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertIn(b"Explicit=true", response.content)
        self.assertIn(b"British=false", response.content)
        self.assertIn(b"NPC=Robin/false", response.content)
        self.assertIn(b"Quest=0", response.content)
        self.assertIn(b"Transform disabled=false", response.content)
        self.assertIn(b"Money=20", response.content)
        self.assertIn(b"Mana=0", response.content)

    def test_checking_a_plain_checkbox_sets_its_own_var(self):
        """A checked plain checkbox (is_british, no linked_vars/add_to)
        writes its own real VAR directly."""
        self.client.post(f"/if/{self.story.slug}/new-game/submit/", {"is_british": "on"}, secure=True)
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertIn(b"British=true", response.content)

    def test_omitting_a_true_default_checkbox_falls_back_to_true_not_false(self):
        """HTML checkboxes submit nothing at all when left unchecked, so
        a real browser's own unchecked-and-submitted state is
        indistinguishable, on the wire, from "this field was never
        rendered." Submitting every OTHER field but omitting
        is_explicit_mode's own key must fall back to its declared
        default (True) rather than being silently coerced to False just
        because its key is absent."""
        self.client.post(f"/if/{self.story.slug}/new-game/submit/", {"is_british": "on"}, secure=True)
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertIn(b"Explicit=true", response.content)

    def test_linked_vars_checkbox_sets_the_second_real_var_when_checked(self):
        """Checking npc_born_male also sets npc_name via linked_vars,
        the same 'one choice, several VARs' pattern radio_image already
        uses for the gender picker."""
        self.client.post(f"/if/{self.story.slug}/new-game/submit/", {"npc_born_male": "on"}, secure=True)
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertIn(b"NPC=Alex/true", response.content)

    def test_linked_vars_checkbox_sets_the_false_branch_when_unchecked(self):
        """The linked_vars False branch is a real, asserted value (not
        just 'don't set it') -- explicitly confirms exclude_optional_content
        left unchecked still writes optional_quest_counter=0, matching
        the manifest's own real default rather than leaving the story's
        compiled default (also 0 here) coincidentally agreeing."""
        self.client.post(f"/if/{self.story.slug}/new-game/submit/", {}, secure=True)
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertIn(b"Quest=0", response.content)

    def test_checking_exclude_optional_content_disables_the_optional_quest(self):
        """Checking exclude_optional_content sets optional_quest_counter=-1,
        the manifest's own permanent quest-disable sentinel."""
        self.client.post(f"/if/{self.story.slug}/new-game/submit/", {"exclude_optional_content": "on"}, secure=True)
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertIn(b"Quest=-1", response.content)

    def test_add_to_checkbox_adds_to_the_real_compiled_default_not_zero(self):
        """lottery_bonus adds 500 to the story's OWN real declared
        player_money default (20 in this fixture, matching
        a converted game's own resolved value) -- proves
        the additive path reads the real compiled default, not a naive
        base of 0."""
        self.client.post(f"/if/{self.story.slug}/new-game/submit/", {"lottery_bonus": "on"}, secure=True)
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertIn(b"Money=520", response.content)

    def test_two_add_to_checkboxes_both_apply_independently(self):
        """lottery_bonus and mana_bonus each add to their own distinct
        target VAR without interfering with each other."""
        self.client.post(
            f"/if/{self.story.slug}/new-game/submit/",
            {"lottery_bonus": "on", "mana_bonus": "on"},
            secure=True,
        )
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertIn(b"Money=520", response.content)
        self.assertIn(b"Mana=100", response.content)

    def test_unchecked_add_to_checkbox_leaves_the_default_untouched(self):
        """Leaving lottery_bonus unchecked must not add anything -- the
        additive amount is applied only when the checkbox itself
        resolves True."""
        self.client.post(f"/if/{self.story.slug}/new-game/submit/", {}, secure=True)
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertIn(b"Money=20", response.content)
        self.assertIn(b"Mana=0", response.content)

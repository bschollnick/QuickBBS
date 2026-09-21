"""`GameSavesDatabase` -- the database implementation of `GameSavesProtocol`.

The shared logic above it is proven in the `ink_engine` repo against an
in-memory implementation. These cover only what the ORM decides: which
rows are touched, what a read returns, and that a listing neither loads
a state blob nor shows the quicksave.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.test import TestCase
from if_session.game_saves import (
    QUICKSAVE_SLOT,
    GameSavesProtocol,
    has_quicksave,
    list_game_saves,
    load_game_save,
    quickload,
    quicksave,
    save_game,
)
from if_session.session_state import SAVE_FORMAT_VERSION

from interactive_fiction.game_saves_database import GameSavesDatabase
from interactive_fiction.models import SaveState, Story

MAX_SLOTS = 5
WHEN = "2026-09-16T12:00:00Z"
A_COMPILED_STORY: dict[str, Any] = {"inkVersion": 21, "root": [["done"], {"#f": 1}], "listDefs": {}}


def a_state(turn_count: int = 7) -> dict[str, Any]:
    return {"turn_count": turn_count, "save_format_version": SAVE_FORMAT_VERSION}


class GameSavesDatabaseTestCase(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(username="player", password="x")
        self.other_user = get_user_model().objects.create_user(username="someoneelse", password="x")
        # These tests exercise SaveState rows only, never the interpreter,
        # so a minimal compiled story is enough and keeps them fast.
        self.story = Story.objects.create(owner=self.user, title="The Haunted House", slug="thehauntedhouse", compiled_json=A_COMPILED_STORY)
        self.other_story = Story.objects.create(owner=self.user, title="Another Game", slug="anothergame", compiled_json=A_COMPILED_STORY)
        self.game_saves_database = GameSavesDatabase(user=self.user, story=self.story)

    def test_it_satisfies_the_protocol(self) -> None:
        self.assertIsInstance(self.game_saves_database, GameSavesProtocol)


class SaveAndLoadTests(GameSavesDatabaseTestCase):
    def test_a_saved_game_can_be_loaded_back(self) -> None:
        save_game(
            "thehauntedhouse", 0, a_state(), "Before the bridge", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS, saved_at=WHEN
        )
        self.assertEqual(load_game_save("thehauntedhouse", 0, saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS), a_state())

    def test_saving_writes_exactly_one_row(self) -> None:
        save_game("thehauntedhouse", 0, a_state(), "x", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS, saved_at=WHEN)
        self.assertEqual(SaveState.objects.count(), 1)

    def test_turn_count_is_denormalized_onto_the_row(self) -> None:
        """So a listing never has to de-TOAST the JSONB state column."""
        save_game(
            "thehauntedhouse", 0, a_state(turn_count=42), "x", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS, saved_at=WHEN
        )
        self.assertEqual(SaveState.objects.get(slot=0).turn_count, 42)

    def test_a_state_without_a_turn_count_stores_the_column_default(self) -> None:
        """The column is NOT NULL, so None becomes -1 rather than failing."""
        save_game(
            "thehauntedhouse",
            0,
            {"save_format_version": SAVE_FORMAT_VERSION},
            "x",
            saves_in=self.game_saves_database,
            maximum_gamesave_slots=MAX_SLOTS,
            saved_at=WHEN,
        )
        self.assertEqual(SaveState.objects.get(slot=0).turn_count, -1)

    def test_saving_the_same_slot_twice_updates_rather_than_duplicates(self) -> None:
        for turn in (1, 2):
            save_game(
                "thehauntedhouse",
                0,
                a_state(turn_count=turn),
                f"Save {turn}",
                saves_in=self.game_saves_database,
                maximum_gamesave_slots=MAX_SLOTS,
                saved_at=WHEN,
            )
        self.assertEqual(SaveState.objects.count(), 1)
        self.assertEqual(SaveState.objects.get(slot=0).turn_count, 2)

    def test_the_read_reports_the_database_write_time_not_the_passed_one(self) -> None:
        """updated_at is auto_now, so the column owns the timestamp."""
        save_game("thehauntedhouse", 0, a_state(), "x", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS, saved_at=WHEN)
        row = SaveState.objects.get(slot=0)
        game_save = self.game_saves_database.read_game_save("thehauntedhouse", 0)
        assert game_save is not None
        self.assertEqual(game_save["saved_at"], row.updated_at.isoformat())

    def test_an_empty_slot_reads_as_none(self) -> None:
        self.assertIsNone(self.game_saves_database.read_game_save("thehauntedhouse", 3))


class IsolationTests(GameSavesDatabaseTestCase):
    """A save must never leak between users or between stories."""

    def test_another_users_save_is_not_visible(self) -> None:
        other_players_saves = GameSavesDatabase(user=self.other_user, story=self.story)
        save_game(
            "thehauntedhouse", 0, a_state(turn_count=1), "Mine", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS, saved_at=WHEN
        )
        self.assertIsNone(other_players_saves.read_game_save("thehauntedhouse", 0))

    def test_another_storys_save_is_not_visible(self) -> None:
        other_players_saves = GameSavesDatabase(user=self.user, story=self.other_story)
        save_game(
            "thehauntedhouse", 0, a_state(turn_count=1), "Mine", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS, saved_at=WHEN
        )
        self.assertIsNone(other_players_saves.read_game_save("anothergame", 0))

    def test_deleting_does_not_touch_another_users_same_slot(self) -> None:
        other_players_saves = GameSavesDatabase(user=self.other_user, story=self.story)
        save_game("thehauntedhouse", 0, a_state(), "Mine", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS, saved_at=WHEN)
        save_game("thehauntedhouse", 0, a_state(), "Theirs", saves_in=other_players_saves, maximum_gamesave_slots=MAX_SLOTS, saved_at=WHEN)
        self.game_saves_database.delete_game_save("thehauntedhouse", 0)
        self.assertIsNotNone(other_players_saves.read_game_save("thehauntedhouse", 0))

    def test_saving_does_not_overwrite_another_users_same_slot(self) -> None:
        other_players_saves = GameSavesDatabase(user=self.other_user, story=self.story)
        save_game(
            "thehauntedhouse", 0, a_state(turn_count=1), "Mine", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS, saved_at=WHEN
        )
        save_game(
            "thehauntedhouse", 0, a_state(turn_count=2), "Theirs", saves_in=other_players_saves, maximum_gamesave_slots=MAX_SLOTS, saved_at=WHEN
        )
        self.assertEqual(SaveState.objects.count(), 2)
        game_save = self.game_saves_database.read_game_save("thehauntedhouse", 0)
        assert game_save is not None
        self.assertEqual(game_save["turn_count"], 1)


class ListingTests(GameSavesDatabaseTestCase):
    def test_a_fresh_story_lists_five_empty_slots(self) -> None:
        listing = list_game_saves("thehauntedhouse", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS)
        self.assertEqual(len(listing), MAX_SLOTS)
        self.assertTrue(all(entry["used"] is False for entry in listing))

    def test_an_occupied_slot_reports_its_label_and_turn_count(self) -> None:
        save_game(
            "thehauntedhouse", 2, a_state(turn_count=12), "Here", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS, saved_at=WHEN
        )
        entry = list_game_saves("thehauntedhouse", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS)[2]
        self.assertTrue(entry["used"])
        self.assertEqual(entry["label"], "Here")
        self.assertEqual(entry["turn_count"], 12)

    def test_the_quicksave_never_appears_in_the_listing(self) -> None:
        """-1 sorts first, so a missing exclude would put it at the top."""
        quicksave("thehauntedhouse", a_state(), saves_in=self.game_saves_database, saved_at=WHEN)
        listing = list_game_saves("thehauntedhouse", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS)
        self.assertEqual(len(listing), MAX_SLOTS)
        self.assertTrue(all(entry["used"] is False for entry in listing))

    def test_the_quicksave_is_excluded_from_the_summary_itself(self) -> None:
        quicksave("thehauntedhouse", a_state(), saves_in=self.game_saves_database, saved_at=WHEN)
        save_game("thehauntedhouse", 0, a_state(), "Real", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS, saved_at=WHEN)
        summaries = self.game_saves_database.summarize_game_saves("thehauntedhouse")
        self.assertEqual([s["gamesave_slot"] for s in summaries], [0])

    def test_a_listing_does_not_load_the_state_column(self) -> None:
        """The reason summarize_game_saves exists apart from read_game_save."""
        save_game("thehauntedhouse", 0, a_state(), "x", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS, saved_at=WHEN)
        with self.assertNumQueries(1):
            summaries = self.game_saves_database.summarize_game_saves("thehauntedhouse")
            # Touching a deferred field would issue a second query.
            self.assertEqual(summaries[0]["label"], "x")

    def test_only_this_users_saves_are_listed(self) -> None:
        other_players_saves = GameSavesDatabase(user=self.other_user, story=self.story)
        save_game("thehauntedhouse", 0, a_state(), "Theirs", saves_in=other_players_saves, maximum_gamesave_slots=MAX_SLOTS, saved_at=WHEN)
        listing = list_game_saves("thehauntedhouse", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS)
        self.assertTrue(all(entry["used"] is False for entry in listing))


class QuicksaveTests(GameSavesDatabaseTestCase):
    def test_a_quicksave_round_trips(self) -> None:
        quicksave("thehauntedhouse", a_state(turn_count=3), saves_in=self.game_saves_database, saved_at=WHEN)
        self.assertEqual(quickload("thehauntedhouse", saves_in=self.game_saves_database)["turn_count"], 3)

    def test_it_lands_in_the_reserved_slot(self) -> None:
        """The whole reason the column had to become signed."""
        quicksave("thehauntedhouse", a_state(), saves_in=self.game_saves_database, saved_at=WHEN)
        self.assertTrue(SaveState.objects.filter(slot=QUICKSAVE_SLOT).exists())

    def test_it_does_not_disturb_a_numbered_save(self) -> None:
        save_game(
            "thehauntedhouse", 0, a_state(turn_count=1), "Mine", saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS, saved_at=WHEN
        )
        quicksave("thehauntedhouse", a_state(turn_count=2), saves_in=self.game_saves_database, saved_at=WHEN)
        self.assertEqual(load_game_save("thehauntedhouse", 0, saves_in=self.game_saves_database, maximum_gamesave_slots=MAX_SLOTS)["turn_count"], 1)

    def test_has_quicksave_answers_without_loading_state(self) -> None:
        quicksave("thehauntedhouse", a_state(), saves_in=self.game_saves_database, saved_at=WHEN)
        with self.assertNumQueries(1):
            self.assertTrue(has_quicksave("thehauntedhouse", saves_in=self.game_saves_database))

    def test_has_quicksave_is_false_for_a_fresh_story(self) -> None:
        self.assertFalse(has_quicksave("thehauntedhouse", saves_in=self.game_saves_database))

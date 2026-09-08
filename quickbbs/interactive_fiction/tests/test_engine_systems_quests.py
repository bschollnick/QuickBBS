"""claude_docs/plans/quest_system.md Step 2: the generic QuestSystem
(interactive_fiction.engine_plugins.quests).

Pure-function coverage — no DB needed. SimpleTestCase throughout, and
fixture ids only (`quest_a`, `goal_1`, `subquest_x`): the engine layer
must never learn any one story's vocabulary, so these tests are written
so they would read identically for any game.
"""

from __future__ import annotations

import json

from django.test import SimpleTestCase

from interactive_fiction.engine_plugins.quests import (
    UNSTARTED_STAGE,
    JournalEntry,
    QuestSpec,
    QuestState,
    advance_to,
    fail_quest,
    is_complete,
    is_failed,
    is_met,
    is_started,
    journal_entries,
    meet_goal,
    met_goals,
    outstanding_goals,
    remaining_requirements,
    set_stage,
    stage_of,
    start_quest,
    unreachable_goals,
)

# A catalog exercising every structural feature at once: a parent with two
# required children and one optional child, goals on both a parent and a
# child, and a bare stage-only quest with no goals at all.
CATALOG: dict[str, QuestSpec] = {
    "quest_a": QuestSpec(
        quest_id="quest_a",
        goal_ids=("goal_1", "goal_2"),
        requires=("subquest_x", "subquest_y"),
        final_stage=100,
    ),
    "subquest_x": QuestSpec(quest_id="subquest_x", parent_id="quest_a", goal_ids=("goal_3",), final_stage=10),
    "subquest_y": QuestSpec(quest_id="subquest_y", parent_id="quest_a", final_stage=10),
    "subquest_z": QuestSpec(quest_id="subquest_z", parent_id="quest_a", final_stage=10),
    "quest_b": QuestSpec(quest_id="quest_b", final_stage=5),
}


class QuestStageTests(SimpleTestCase):
    """Stage reads, writes, and the never-regress guard."""

    def test_an_untouched_quest_reports_the_unstarted_stage(self):
        """A story compares stages against thresholds, so the floor must
        be a real number rather than None."""
        self.assertEqual(UNSTARTED_STAGE, stage_of(QuestState(), "quest_a"))
        self.assertFalse(is_started(QuestState(), "quest_a"))

    def test_starting_a_quest_records_it(self):
        """is_started is what a journal uses to decide visibility."""
        state = start_quest(QuestState(), "quest_a")
        self.assertTrue(is_started(state, "quest_a"))
        self.assertEqual(1, stage_of(state, "quest_a"))

    def test_starting_an_already_started_quest_does_not_reset_progress(self):
        """A re-enterable scene must not knock a quest back to stage 1."""
        state = advance_to(start_quest(QuestState(), "quest_a"), "quest_a", 50)
        self.assertEqual(50, stage_of(start_quest(state, "quest_a"), "quest_a"))

    def test_advance_to_moves_a_quest_forward(self):
        """The ordinary progress path."""
        self.assertEqual(20, stage_of(advance_to(QuestState(), "quest_a", 20), "quest_a"))

    def test_advance_to_refuses_to_regress(self):
        """Mirrors source's own `if (getQuestX() < n)` guard, so a scene
        reached out of order cannot undo progress."""
        state = advance_to(QuestState(), "quest_a", 50)
        self.assertEqual(50, stage_of(advance_to(state, "quest_a", 20), "quest_a"))
        self.assertEqual(50, stage_of(advance_to(state, "quest_a", 50), "quest_a"))

    def test_set_stage_still_allows_regression(self):
        """The escape hatch for a failed path being reset for a retry."""
        state = advance_to(QuestState(), "quest_a", 900)
        self.assertEqual(6, stage_of(set_stage(state, "quest_a", 6), "quest_a"))

    def test_writes_do_not_mutate_the_original_state(self):
        """Every plugin here is pure; a caller holding an older state must
        keep seeing what it held."""
        original = advance_to(QuestState(), "quest_a", 10)
        advance_to(original, "quest_a", 99)
        self.assertEqual(10, stage_of(original, "quest_a"))


class QuestGoalTests(SimpleTestCase):
    """Goals: idempotent, per-quest scoped, and countable."""

    def test_meeting_a_goal_records_it(self):
        state = meet_goal(QuestState(), "quest_a", "goal_1")
        self.assertTrue(is_met(state, "quest_a", "goal_1"))

    def test_meeting_a_goal_twice_records_it_once(self):
        """Idempotent for the same reason TADS 3's awardPointsOnce is: a
        re-entered scene must not make an "N of M" count drift."""
        state = meet_goal(meet_goal(QuestState(), "quest_a", "goal_1"), "quest_a", "goal_1")
        self.assertEqual(["goal_1"], met_goals(state, "quest_a"))

    def test_goal_ids_are_scoped_per_quest(self):
        """Two quests may reuse an id without colliding, so a catalog need
        not invent globally unique goal names."""
        state = meet_goal(QuestState(), "quest_a", "goal_1")
        self.assertFalse(is_met(state, "quest_b", "goal_1"))

    def test_outstanding_goals_follows_catalog_order(self):
        """The journal renders in this order, so it must be the catalog's
        rather than the order the player happened to meet them."""
        self.assertEqual(["goal_1", "goal_2"], outstanding_goals(QuestState(), "quest_a", CATALOG))
        state = meet_goal(QuestState(), "quest_a", "goal_1")
        self.assertEqual(["goal_2"], outstanding_goals(state, "quest_a", CATALOG))

    def test_outstanding_goals_is_empty_for_an_undeclared_quest(self):
        """An empty answer rather than a KeyError: a story mid-edit must
        not crash the engine."""
        self.assertEqual([], outstanding_goals(QuestState(), "quest_missing", CATALOG))


class QuestCompletionTests(SimpleTestCase):
    """Completion, including required vs. optional subquests."""

    def _finish(self, state: QuestState, quest_id: str) -> QuestState:
        """Drive one goal-less subquest to its final stage.

        Args:
            state: The state to advance.
            quest_id: The subquest to finish.

        Returns:
            The advanced state.
        """
        return advance_to(state, quest_id, 10)

    def test_a_stage_only_quest_completes_at_its_final_stage(self):
        self.assertFalse(is_complete(advance_to(QuestState(), "quest_b", 4), "quest_b", CATALOG))
        self.assertTrue(is_complete(advance_to(QuestState(), "quest_b", 5), "quest_b", CATALOG))

    def test_a_parent_is_incomplete_while_a_required_subquest_is(self):
        """The motivating property: without it, every site that cares has
        to hand-check the children, which is how a stage gets missed."""
        state = advance_to(QuestState(), "quest_a", 100)
        state = meet_goal(meet_goal(state, "quest_a", "goal_1"), "quest_a", "goal_2")
        self.assertFalse(is_complete(state, "quest_a", CATALOG))

    def test_a_parent_completes_once_every_requirement_is_met(self):
        state = advance_to(QuestState(), "quest_a", 100)
        state = meet_goal(meet_goal(state, "quest_a", "goal_1"), "quest_a", "goal_2")
        state = self._finish(meet_goal(state, "subquest_x", "goal_3"), "subquest_x")
        state = self._finish(state, "subquest_y")
        self.assertTrue(is_complete(state, "quest_a", CATALOG))

    def test_an_optional_subquest_does_not_block_its_parent(self):
        """subquest_z nests in the journal but is absent from `requires`,
        so a story can show side-work without it gating anything."""
        state = advance_to(QuestState(), "quest_a", 100)
        state = meet_goal(meet_goal(state, "quest_a", "goal_1"), "quest_a", "goal_2")
        state = self._finish(meet_goal(state, "subquest_x", "goal_3"), "subquest_x")
        state = self._finish(state, "subquest_y")
        state = start_quest(state, "subquest_z")
        self.assertFalse(is_complete(state, "subquest_z", CATALOG))
        self.assertTrue(is_complete(state, "quest_a", CATALOG))

    def test_an_unmet_goal_blocks_completion_even_at_the_final_stage(self):
        state = advance_to(QuestState(), "subquest_x", 10)
        self.assertFalse(is_complete(state, "subquest_x", CATALOG))
        self.assertTrue(is_complete(meet_goal(state, "subquest_x", "goal_3"), "subquest_x", CATALOG))

    def test_remaining_requirements_reports_which_children_are_outstanding(self):
        """What lets a journal say "1 of 2 done" rather than print a bare
        stage number."""
        state = self._finish(meet_goal(QuestState(), "subquest_x", "goal_3"), "subquest_x")
        self.assertEqual(["subquest_y"], remaining_requirements(state, "quest_a", CATALOG))

    def test_a_quest_declaring_no_ending_never_reports_complete(self):
        """Deliberate: silently calling such a quest finished would hide a
        catalog that forgot to say how it ends."""
        catalog = {"quest_c": QuestSpec(quest_id="quest_c")}
        self.assertFalse(is_complete(advance_to(QuestState(), "quest_c", 9999), "quest_c", catalog))

    def test_an_undeclared_quest_is_never_complete(self):
        self.assertFalse(is_complete(QuestState(), "quest_missing", CATALOG))


class QuestFailureTests(SimpleTestCase):
    """Failure is tracked apart from stages."""

    def test_a_quest_starts_unfailed(self):
        self.assertFalse(is_failed(QuestState(), "quest_a"))

    def test_failing_a_quest_records_it(self):
        """Kept off the stage number so the engine can answer "did this
        fail" without knowing any game's failure sentinel."""
        self.assertTrue(is_failed(fail_quest(QuestState(), "quest_a"), "quest_a"))

    def test_failing_twice_records_once(self):
        state = fail_quest(fail_quest(QuestState(), "quest_a"), "quest_a")
        self.assertEqual(["quest_a"], state.failed)

    def test_failing_does_not_disturb_stage_or_goals(self):
        state = meet_goal(advance_to(QuestState(), "quest_a", 40), "quest_a", "goal_1")
        state = fail_quest(state, "quest_a")
        self.assertEqual(40, stage_of(state, "quest_a"))
        self.assertTrue(is_met(state, "quest_a", "goal_1"))


class QuestJournalTests(SimpleTestCase):
    """Journal assembly: structure only, never player-facing wording."""

    def test_an_untouched_journal_is_empty(self):
        self.assertEqual([], journal_entries(QuestState(), CATALOG))

    def test_only_started_quests_appear(self):
        entries = journal_entries(start_quest(QuestState(), "quest_b"), CATALOG)
        self.assertEqual(["quest_b"], [entry.quest_id for entry in entries])

    def test_started_children_nest_under_their_parent(self):
        state = start_quest(start_quest(QuestState(), "quest_a"), "subquest_x")
        entries = journal_entries(state, CATALOG)
        self.assertEqual(["quest_a"], [entry.quest_id for entry in entries])
        self.assertEqual(["subquest_x"], [child.quest_id for child in entries[0].children])

    def test_a_started_child_of_an_unstarted_parent_is_promoted(self):
        """Dropping it would silently lose a quest the player really
        began — the failure mode this system exists to prevent."""
        entries = journal_entries(start_quest(QuestState(), "subquest_x"), CATALOG)
        self.assertEqual(["subquest_x"], [entry.quest_id for entry in entries])

    def test_an_entry_carries_stage_goals_and_flags(self):
        state = meet_goal(advance_to(start_quest(QuestState(), "quest_a"), "quest_a", 40), "quest_a", "goal_1")
        entry = journal_entries(state, CATALOG)[0]
        self.assertEqual(40, entry.stage)
        self.assertEqual(("goal_1",), entry.met)
        self.assertEqual(("goal_2",), entry.outstanding)
        self.assertFalse(entry.complete)
        self.assertFalse(entry.failed)

    def test_an_entry_reports_failure(self):
        state = fail_quest(start_quest(QuestState(), "quest_b"), "quest_b")
        self.assertTrue(journal_entries(state, CATALOG)[0].failed)

    def test_entries_carry_no_player_facing_text(self):
        """The engine's half of the split: ids only, so every string stays
        the game's to supply."""
        state = start_quest(QuestState(), "quest_a")
        entry = journal_entries(state, CATALOG)[0]
        self.assertEqual(
            {"quest_id", "stage", "complete", "failed", "met", "outstanding", "children"},
            set(vars(entry)),
        )
        self.assertIsInstance(entry, JournalEntry)


class QuestSerializationTests(SimpleTestCase):
    """State must survive the session round-trip."""

    def test_a_populated_state_round_trips_through_json(self):
        state = fail_quest(meet_goal(advance_to(QuestState(), "quest_a", 40), "quest_a", "goal_1"), "quest_b")
        restored = QuestState.from_dict(json.loads(json.dumps(state.to_dict())))
        self.assertEqual(40, stage_of(restored, "quest_a"))
        self.assertTrue(is_met(restored, "quest_a", "goal_1"))
        self.assertTrue(is_failed(restored, "quest_b"))

    def test_from_dict_tolerates_missing_keys(self):
        """A session saved before this system existed must still load."""
        restored = QuestState.from_dict({})
        self.assertEqual(UNSTARTED_STAGE, stage_of(restored, "quest_a"))
        self.assertEqual([], restored.failed)

    def test_to_dict_does_not_alias_live_state(self):
        """A serialized copy handed to a session must not stay wired to
        the state it came from."""
        state = meet_goal(QuestState(), "quest_a", "goal_1")
        serialized = state.to_dict()
        serialized["stages"]["quest_a"] = 99
        serialized["met_goals"]["quest_a"].append("goal_2")
        self.assertEqual(UNSTARTED_STAGE, stage_of(state, "quest_a"))
        self.assertEqual(["goal_1"], met_goals(state, "quest_a"))


class QuestInertWhenUnusedTests(SimpleTestCase):
    """A story declaring no quests pays nothing and crashes nowhere."""

    def test_every_query_answers_empty_against_an_empty_catalog(self):
        empty: dict[str, QuestSpec] = {}
        state = QuestState()
        self.assertEqual([], journal_entries(state, empty))
        self.assertEqual([], outstanding_goals(state, "anything", empty))
        self.assertEqual([], remaining_requirements(state, "anything", empty))
        self.assertFalse(is_complete(state, "anything", empty))
        self.assertFalse(is_started(state, "anything"))
        self.assertEqual(UNSTARTED_STAGE, stage_of(state, "anything"))

    def test_an_unused_state_serializes_to_empty_containers(self):
        self.assertEqual({"stages": {}, "met_goals": {}, "failed": []}, QuestState().to_dict())


class QuestUnreachableGoalAuditTests(SimpleTestCase):
    """The audit the surveyed prior art lacks."""

    def test_a_goal_no_scene_can_meet_is_reported(self):
        """A goal nothing meets is not a compile error and not a test
        failure — it is a quest that silently never finishes."""
        self.assertEqual(
            [("quest_a", "goal_2"), ("subquest_x", "goal_3")],
            unreachable_goals(CATALOG, {"goal_1"}),
        )

    def test_a_fully_reachable_catalog_reports_nothing(self):
        self.assertEqual([], unreachable_goals(CATALOG, {"goal_1", "goal_2", "goal_3"}))

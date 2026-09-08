"""claude_docs/plans/external_expansion_IF_engine.md Step 7: SkillSystem
(interactive_fiction.engine_plugins.skills).

Pure-function coverage — no DB needed. SimpleTestCase throughout.
"""

from __future__ import annotations

import json

from django.test import SimpleTestCase

from interactive_fiction.engine_plugins.skills import (
    CheckResult,
    SkillState,
    adjust_level,
    check,
    get_all_levels,
    get_level,
    set_level,
)


class GetSetAdjustLevelTests(SimpleTestCase):
    """Levels can be named anything (per the explicit "skills should be
    able to be called anything" requirement) and are set/adjusted without
    mutating the original state."""

    def test_unset_skill_returns_the_given_default(self):
        """A skill never set for a character returns whatever default the
        caller supplies, not a fixed value."""
        state = SkillState()
        self.assertEqual(get_level(state, "hero", "Wisdom", default=0), 0)
        self.assertEqual(get_level(state, "hero", "Wisdom", default=10), 10)

    def test_set_level_is_readable_back(self):
        """A level set via set_level() is returned unchanged by get_level()."""
        state = SkillState()
        state = set_level(state, "hero", "Strength", 15)
        self.assertEqual(get_level(state, "hero", "Strength"), 15)

    def test_set_level_does_not_mutate_the_original_state(self):
        """set_level() returns a new state; the original is untouched."""
        state = SkillState()
        set_level(state, "hero", "Strength", 15)
        self.assertEqual(get_level(state, "hero", "Strength"), 0)

    def test_adjust_level_adds_to_an_existing_level(self):
        """A positive delta increases an existing level."""
        state = SkillState()
        state = set_level(state, "hero", "Charisma", 10)
        state = adjust_level(state, "hero", "Charisma", 3)
        self.assertEqual(get_level(state, "hero", "Charisma"), 13)

    def test_adjust_level_subtracts_with_a_negative_delta(self):
        """A negative delta decreases an existing level."""
        state = SkillState()
        state = set_level(state, "hero", "Charisma", 10)
        state = adjust_level(state, "hero", "Charisma", -4)
        self.assertEqual(get_level(state, "hero", "Charisma"), 6)

    def test_adjust_level_on_an_unset_skill_starts_from_zero(self):
        """Adjusting a skill with no prior recorded level treats it as
        starting at 0."""
        state = SkillState()
        state = adjust_level(state, "hero", "Muscles", 5)
        self.assertEqual(get_level(state, "hero", "Muscles"), 5)

    def test_arbitrary_skill_names_are_supported(self):
        """The framework has no fixed skill list at all — any string the
        game layer chooses works identically."""
        state = SkillState()
        for name in ("Strength", "Muscles", "Wisdom", "Charisma", "some totally custom name"):
            state = set_level(state, "hero", name, 7)
        self.assertEqual(
            get_all_levels(state, "hero"), {name: 7 for name in ("Strength", "Muscles", "Wisdom", "Charisma", "some totally custom name")}
        )

    def test_different_characters_have_independent_levels(self):
        """Setting one character's level never affects another's."""
        state = SkillState()
        state = set_level(state, "hero", "Strength", 15)
        state = set_level(state, "villain", "Strength", 20)
        self.assertEqual(get_level(state, "hero", "Strength"), 15)
        self.assertEqual(get_level(state, "villain", "Strength"), 20)


class GetAllLevelsTests(SimpleTestCase):
    """get_all_levels() is the real "get current stats" query."""

    def test_returns_every_recorded_skill_for_a_character(self):
        """Every skill previously set for a character is included."""
        state = SkillState()
        state = set_level(state, "hero", "Strength", 15)
        state = set_level(state, "hero", "Wisdom", 12)
        self.assertEqual(get_all_levels(state, "hero"), {"Strength": 15, "Wisdom": 12})

    def test_character_with_no_skills_returns_an_empty_dict(self):
        """A character with no recorded skills returns an empty dict, not
        an error."""
        state = SkillState()
        self.assertEqual(get_all_levels(state, "nobody"), {})

    def test_returned_dict_is_an_independent_copy(self):
        """Mutating the returned dict must never affect SkillState's own
        internal storage."""
        state = SkillState()
        state = set_level(state, "hero", "Strength", 15)
        levels = get_all_levels(state, "hero")
        levels["Strength"] = 999
        self.assertEqual(get_level(state, "hero", "Strength"), 15)


class CheckTests(SimpleTestCase):
    """check() is a real roll-under mechanic: success when roll <=
    (normalized level + bonus)."""

    def test_level_zero_always_fails(self):
        """A 0-level skill normalizes to a 0 percentile target — a 1-100
        roll can never be <= 0."""
        state = SkillState(rng_seed=42)
        for _ in range(50):
            result, state = check(state, level=0, max_level=20)
            self.assertFalse(result.success)

    def test_max_level_with_no_bonus_almost_always_succeeds(self):
        """A level at the top of its range normalizes to 100 — every
        1-100 roll is <= 100, so this always succeeds."""
        state = SkillState(rng_seed=1)
        for _ in range(50):
            result, state = check(state, level=20, max_level=20)
            self.assertTrue(result.success)

    def test_success_exactly_matches_roll_vs_effective_target(self):
        """A direct, non-statistical proof: success is exactly (roll <=
        effective_target), not some other comparison."""
        state = SkillState(rng_seed=7)
        result, _new_state = check(state, level=10, max_level=20, bonus=5)
        self.assertEqual(result.effective_target, 55)  # 10/20*100=50, +5 bonus
        self.assertEqual(result.success, result.roll <= 55)

    def test_effective_target_normalizes_across_different_max_levels(self):
        """A level of 3 on a 1-6 scale and a level of 10 on a 1-20 scale
        both normalize to the same 50 percentile target — the game
        layer's own numeric range is purely presentational."""
        state = SkillState(rng_seed=99)
        result_a, _ = check(state, level=3, max_level=6)
        result_b, _ = check(state, level=10, max_level=20)
        self.assertEqual(result_a.effective_target, 50)
        self.assertEqual(result_b.effective_target, 50)

    def test_bonus_can_be_negative_a_penalty(self):
        """A negative bonus lowers the effective target, acting as a penalty."""
        state = SkillState(rng_seed=3)
        result, _ = check(state, level=10, max_level=20, bonus=-5)
        self.assertEqual(result.effective_target, 45)  # 50 - 5

    def test_effective_target_is_clamped_to_0_and_100(self):
        """A bonus pushing the target outside [0, 100] is clamped, not
        rejected or left out of range."""
        state = SkillState(rng_seed=0)
        high_result, _ = check(state, level=20, max_level=20, bonus=50)
        low_result, _ = check(state, level=0, max_level=20, bonus=-50)
        self.assertEqual(high_result.effective_target, 100)
        self.assertEqual(low_result.effective_target, 0)

    def test_check_advances_the_rng_state_deterministically(self):
        """Two checks starting from the SAME seed produce the SAME
        sequence of results — real determinism, not just "it runs"."""
        state_a = SkillState(rng_seed=555)
        state_b = SkillState(rng_seed=555)
        results_a = []
        results_b = []
        for _ in range(5):
            result_a, state_a = check(state_a, level=10, max_level=20)
            result_b, state_b = check(state_b, level=10, max_level=20)
            results_a.append((result_a.roll, result_a.success))
            results_b.append((result_b.roll, result_b.success))
        self.assertEqual(results_a, results_b)

    def test_check_does_not_mutate_the_original_state(self):
        """check() returns a new state; the original's rng_seed is untouched."""
        state = SkillState(rng_seed=1)
        original_seed = state.rng_seed
        check(state, level=10, max_level=20)
        self.assertEqual(state.rng_seed, original_seed)

    def test_repeated_checks_from_the_same_state_produce_a_real_distribution(self):
        """A real statistical sanity check, not just "it returns
        something": rolling a 50-percentile target many times should
        succeed roughly half the time, not always/never."""
        state = SkillState(rng_seed=2024)
        successes = 0
        trials = 500
        for _ in range(trials):
            result, state = check(state, level=10, max_level=20)
            if result.success:
                successes += 1
        # Loose bounds -- this is a sanity check against a badly broken
        # RNG/comparison, not a strict statistical test.
        self.assertGreater(successes, trials * 0.35)
        self.assertLess(successes, trials * 0.65)


class CheckResultTests(SimpleTestCase):
    """CheckResult is the real "get the result of a skill test" the game
    layer queries."""

    def test_check_result_fields_are_directly_readable(self):
        """CheckResult exposes success/roll/effective_target as plain
        attributes."""
        result = CheckResult(success=True, roll=42, effective_target=60)
        self.assertTrue(result.success)
        self.assertEqual(result.roll, 42)
        self.assertEqual(result.effective_target, 60)


class SkillStateSerializationTests(SimpleTestCase):
    """SkillState round-trips through plain JSON, matching every other
    engine_plugins state type's own convention."""

    def test_round_trips_through_real_json(self):
        """A real json.dumps/json.loads round-trip preserves every
        character's skill levels and the RNG seed."""
        state = SkillState(rng_seed=123)
        state = set_level(state, "hero", "Strength", 15)
        state = set_level(state, "villain", "Wisdom", 8)
        round_tripped = json.loads(json.dumps(state.to_dict()))
        restored = SkillState.from_dict(round_tripped)
        self.assertEqual(get_level(restored, "hero", "Strength"), 15)
        self.assertEqual(get_level(restored, "villain", "Wisdom"), 8)
        self.assertEqual(restored.rng_seed, 123)

    def test_restored_state_continues_the_same_rng_sequence(self):
        """A real proof that serialization preserves determinism across a
        save/load boundary, not just the skill levels."""
        state = SkillState(rng_seed=77)
        result_before, state = check(state, level=10, max_level=20)
        restored = SkillState.from_dict(json.loads(json.dumps(state.to_dict())))
        result_after, _ = check(restored, level=10, max_level=20)
        # Advancing the restored state continues the SAME sequence the
        # original would have continued -- prove by advancing a fresh copy
        # of the pre-restore state the same number of steps and comparing.
        expected_result, _ = check(state, level=10, max_level=20)
        self.assertEqual(result_after.roll, expected_result.roll)
        self.assertNotEqual(result_before.roll, result_after.roll)

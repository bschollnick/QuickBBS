"""Section 8 tests: sequences/cycles/shuffles + seeded RNG (interactive_fiction.engine).

InkRuntimeState is driven end-to-end against real compiled JSON
(tests/fixtures/section8_*.ink), with every expected transcript captured
from the local inklecate build's -p play-mode transcript before any
assertion was written (per the plan's standing validate-against-real-data
rule). NetRandom (the ported .NET System.Random algorithm) is additionally
unit-tested directly against real output captured from a `dotnet run`
console program calling `new Random(seed).Next()`, since matching that
algorithm exactly — not just "some reproducible PRNG" — is the actual
point of this section.
"""

from __future__ import annotations

import json
from pathlib import Path as FilePath

from django.test import SimpleTestCase

from interactive_fiction.engine import (
    InkRuntimeState,
    ListValue,
    NetRandom,
    load_list_defs,
    load_story_root,
)

FIXTURES = FilePath(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def _run(name: str, with_list_defs: bool = False) -> InkRuntimeState:
    data = _load(name)
    if with_list_defs:
        return InkRuntimeState(load_story_root(data), load_list_defs(data))
    return InkRuntimeState(load_story_root(data))


class NetRandomTests(SimpleTestCase):
    """NetRandom validated directly against real `dotnet run` output for
    `new System.Random(seed).Next()`, captured 2026-08-16 across 13 seeds
    spanning ordinary values, ±1, and the int32 boundary (Int32.MaxValue,
    Int32.MinValue, and values one away from each)."""

    # Each row: seed -> first 10 values from a real `new Random(seed)`,
    # calling `.Next()` ten times. Captured via a small dotnet console
    # program, not estimated or derived from documentation.
    REFERENCE_SEQUENCES = {
        0: [1559595546, 1755192844, 1649316166, 1198642031, 442452829, 1200195957, 1945678308, 949569752, 2099272109, 587775847],
        1: [534011718, 237820880, 1002897798, 1657007234, 1412011072, 929393559, 760389092, 2026928803, 217468053, 1379662799],
        -1: [534011718, 237820880, 1002897798, 1657007234, 1412011072, 929393559, 760389092, 2026928803, 217468053, 1379662799],
        42: [1434747710, 302596119, 269548474, 1122627734, 361709742, 563913476, 1555655117, 1101493307, 372913049, 1634773126],
        100: [2080427802, 341851734, 1431988776, 1938005744, 761513014, 2037243568, 1528357293, 1311292502, 749943798, 319576108],
        2147483647: [
            1559595546,
            1755192844,
            1649316172,
            1198642031,
            442452829,
            1200195955,
            1945678308,
            949569752,
            2099272109,
            587775835,
        ],
        -2147483648: [
            1559595546,
            1755192844,
            1649316172,
            1198642031,
            442452829,
            1200195955,
            1945678308,
            949569752,
            2099272109,
            587775835,
        ],
        2147483645: [
            1463279555,
            494969478,
            794669261,
            281911625,
            650819990,
            1741800751,
            21289446,
            942335297,
            1567912927,
            1151485578,
        ],
        12345: [143337951, 150666398, 1663795458, 1097663221, 1712597933, 1776631026, 356393799, 1580828476, 558810388, 1086637143],
        999999: [1112411752, 303862068, 127801651, 591210207, 1061528791, 1055852349, 334059998, 737249153, 1190236619, 5573998],
        55: [987059828, 2051597057, 456044278, 638924432, 81065019, 1338449596, 1179280838, 74775441, 1679264085, 1191885267],
        21: [1497171628, 2102636305, 959432320, 86893059, 1475823109, 1955796540, 676924889, 2099273353, 1236092579, 37532663],
        -55: [987059828, 2051597057, 456044278, 638924432, 81065019, 1338449596, 1179280838, 74775441, 1679264085, 1191885267],
    }

    def test_matches_real_dotnet_output_for_every_captured_seed(self):
        """Every one of the 13 captured seeds' first 10 values match the
        real .NET output exactly, including the Int32.MinValue edge case
        (special-cased to Int32.MaxValue in the seed-array init, per the
        real dotnet/runtime source)."""
        for seed, expected in self.REFERENCE_SEQUENCES.items():
            with self.subTest(seed=seed):
                rng = NetRandom(seed)
                actual = [rng.next() for _ in range(10)]
                self.assertEqual(actual, expected)

    def test_seed_one_and_negative_one_are_identical(self):
        """abs(seed) means 1 and -1 produce the same sequence, matching
        the real algorithm's seed-array initialization."""
        self.assertEqual([NetRandom(1).next() for _ in range(5)], [NetRandom(-1).next() for _ in range(5)])


class SequenceTests(SimpleTestCase):
    """Section 8: `{a|b|c}` sequences, capped at the last element once
    exhausted (section8_seq2.ink, section8_seq_sticky.ink)."""

    def test_once_only_choices_prune_after_two_visits(self):
        """A `*`-choice loop only offers "Again" once; the sequence
        advances a-then-b across the two visits (section8_seq2.ink)."""
        state = _run("section8_seq2.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "a\n")
        self.assertEqual([c.text for c in state.current_choices], ["Again", "Stop"])
        state.choose(0)
        text = state.continue_story()
        self.assertEqual(text, "b\n")
        self.assertEqual([c.text for c in state.current_choices], ["Stop"])

    def test_sequence_caps_at_last_element_once_exhausted(self):
        """A `+`-sticky-choice loop lets the sequence run past its length;
        it caps at "c" (MIN(visit_count, N-1)) rather than erroring or
        wrapping (section8_seq_sticky.ink)."""
        state = _run("section8_seq_sticky.ink.json")
        results = [state.continue_story()]
        for _ in range(4):
            state.choose(0)
            results.append(state.continue_story())
        self.assertEqual(results, ["a\n", "b\n", "c\n", "c\n", "c\n"])


class CycleTests(SimpleTestCase):
    """Section 8: `{&a|b|c}` cycles, wrapping via modulo instead of
    capping (section8_cycle.ink, section8_cycle_sticky.ink)."""

    def test_once_only_choices_prune_after_two_visits(self):
        """Matches SequenceTests' shape but with a cycle operator
        (section8_cycle.ink)."""
        state = _run("section8_cycle.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "a\n")
        state.choose(0)
        text = state.continue_story()
        self.assertEqual(text, "b\n")

    def test_cycle_wraps_around_via_modulo(self):
        """A `+`-sticky-choice loop shows the cycle wrapping back to "a"
        after "c", matching the real transcript's a,b,c,a,b sequence
        exactly (section8_cycle_sticky.ink)."""
        state = _run("section8_cycle_sticky.ink.json")
        results = [state.continue_story()]
        for _ in range(4):
            state.choose(0)
            results.append(state.continue_story())
        self.assertEqual(results, ["a\n", "b\n", "c\n", "a\n", "b\n"])


class ShuffleTests(SimpleTestCase):
    """Section 8: `{~a|b|c}` shuffles, deterministic once SEED_RANDOM is
    called explicitly (section8_shuffle_seeded.ink)."""

    def test_seeded_shuffle_matches_real_transcript(self):
        """With SEED_RANDOM(777), the shuffle draws "a" then "b" across
        two visits, matching the real captured transcript exactly — real
        Ink's own shuffle is time-seeded and non-reproducible without an
        explicit seed, so this fixture calls SEED_RANDOM first."""
        state = _run("section8_shuffle_seeded.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "a\n")
        state.choose(0)
        text = state.continue_story()
        self.assertEqual(text, "b\n")


class RandomTests(SimpleTestCase):
    """Section 8: SEED_RANDOM()/RANDOM(min, max) (section8_random.ink)."""

    def test_seeded_random_matches_real_transcript(self):
        """Three RANDOM(1,6) calls after SEED_RANDOM(999999) match the
        real transcript exactly: 5, 6, 2."""
        state = _run("section8_random.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "5\n6\n2\n")


class ListRandomTests(SimpleTestCase):
    """Section 8: LIST_RANDOM(list) (section8_lrnd.ink)."""

    def test_seeded_list_random_matches_real_transcript(self):
        """LIST_RANDOM on a 3-item LIST after SEED_RANDOM(42) picks
        "Cherry", matching the real transcript exactly."""
        state = _run("section8_lrnd.ink.json", with_list_defs=True)
        text = state.continue_story()
        self.assertEqual(text, "Cherry\n")

    def test_list_random_of_empty_list_degrades_to_empty_list(self):
        """An empty LIST operand degrades to an empty ListValue rather
        than crashing (no real transcript needed — this is Section 5-8's
        standing defensive-degradation philosophy, unit-tested directly)."""
        state = InkRuntimeState(load_story_root(_load("section8_lrnd.ink.json")))
        state.eval_stack.append(ListValue())
        state._push_list_random()  # pylint: disable=protected-access
        self.assertEqual(state.eval_stack[-1], ListValue())

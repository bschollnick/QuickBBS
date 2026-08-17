"""Section 7 tests: LISTs (interactive_fiction.engine).

InkRuntimeState is driven end-to-end against real compiled JSON
(tests/fixtures/section7_*.ink), with every expected transcript captured
from the local inklecate build's -p play-mode transcript before any
assertion was written (per the plan's standing validate-against-real-data
rule). apply_native_function() is additionally unit-tested directly for
the LIST operator family the fixtures don't each need their own story for.
"""

from __future__ import annotations

import json
from pathlib import Path as FilePath

from django.test import SimpleTestCase

from interactive_fiction.engine import (
    InkRuntimeState,
    ListValue,
    apply_native_function,
    load_list_defs,
    load_story_root,
)

FIXTURES = FilePath(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def _run(name: str) -> InkRuntimeState:
    data = _load(name)
    state = InkRuntimeState(load_story_root(data), load_list_defs(data))
    return state


class BasicListValueTests(SimpleTestCase):
    """Section 7: VAR initialized to a single-item LIST value, `+=`/`-=`
    reassignment, and `?` has-item conditional text (section7_basic.ink)."""

    def test_reassignment_and_has_item_conditions_match_transcript(self):
        """A LIST var's display form, `+=` growth, and `?`/else-branch
        conditional text all match the real transcript exactly."""
        state = _run("section7_basic.ink.json")
        text = state.continue_story()
        self.assertEqual(
            text,
            "You have Coins.\nNow you have Coins, Notes.\nYou still have coins.\nCoins are gone.\n",
        )

    def test_item_names_are_pre_registered_as_single_item_globals(self):
        """A bare list item name (e.g. "Coins") is readable as its own
        single-item LIST global before any story content runs."""
        state = _run("section7_basic.ink.json")
        self.assertEqual(state.globals["Coins"], ListValue.single("Wallet", "Coins", 1))


class ListUnaryOperatorTests(SimpleTestCase):
    """Section 7: LIST_MIN/LIST_MAX/LIST_ALL/LIST_COUNT/LIST_VALUE/
    LIST_INVERT and LIST comparisons (section7_ops.ink)."""

    def test_all_unary_ops_and_one_comparison_match_transcript(self):
        """Every unary LIST_* op and the == comparison match the real
        transcript exactly; the false > comparison produces no text."""
        state = _run("section7_ops.ink.json")
        text = state.continue_story()
        self.assertEqual(
            text,
            "Count: 2\nMin: Coins\nMax: Notes\nAll: Coins, Notes, Cards\n" "Value: 3\nInverted: Cards\nEqual!\n",
        )


class SwitchOnValueTests(SimpleTestCase):
    """Section 7: `{x: - 1: ... - 4: ... - else: ...}` switch-on-value,
    which depends on the DUPLICATE_TOP ("du") control command
    (section7_switch.ink)."""

    def test_matching_branch_is_selected(self):
        """The branch matching the switch value runs, matching the real
        transcript exactly."""
        state = _run("section7_switch.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "four\n")


class RecursiveBinaryStorageTests(SimpleTestCase):
    """Section 7: a recursive function combining a switch-on-value block
    with LIST-adjacent bit-flag storage — regression coverage for two real
    bugs found 2026-08-16 via smoke-testing listToNumber.ink.

    Bug 1: "du" (DUPLICATE_TOP) can be reached at eval-run depth > 0, not
    just depth 0 (the switch container here sits inside an outer, still-
    open eval bracket in real compiled output) — only handling it in
    _handle_string_content's main-stream branch left the duplicate never
    pushed, so every branch after the first tested against nothing.
    Bug 2: the switch's own trailing bare "pop" (also reachable at
    eval-run depth > 0) was previously only handled inside
    _handle_eval_run_command for the void-function-call form, leaving a
    stale duplicated value on eval_stack whenever no switch branch matched,
    corrupting the next eval run to use the stack — this recursive story's
    binaryValue=4/1 levels hit exactly this case.
    """

    def test_correct_bits_are_set_across_recursive_calls(self):
        """10 = 8 + 2, so only bit2 and bit8 end up true, matching the
        real transcript exactly."""
        state = _run("section7_binstore.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "Bits: false true false true\n")


class BoolDisplayTests(SimpleTestCase):
    """Regression coverage for a real bug found 2026-08-16 via
    smoke-testing: {x} for a bool VAR must display "true"/"false"
    (matching real inklecate), not Python's capitalized str(bool)
    (section7_bool.ink) — a Section 4 display bug, not LIST-specific, but
    only surfaced by Section 7's real-world bit-flag-storage testing."""

    def test_bool_displays_lowercase(self):
        """A bool VAR interpolated into text matches real Ink's lowercase
        "true", not Python's "True"."""
        state = _run("section7_bool.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "true\n")


class ListNativeFunctionTests(SimpleTestCase):
    """Section 7: apply_native_function() LIST operator coverage,
    unit-tested directly (ported from ink-engine-runtime/InkList.cs's
    AddListBinaryOp/AddListUnaryOp call sites)."""

    def setUp(self):
        self.wallet_defs = {"Wallet": {"Coins": 1, "Notes": 2, "Cards": 3}}
        self.coins = ListValue.single("Wallet", "Coins", 1)
        self.notes = ListValue.single("Wallet", "Notes", 2)
        self.coins_notes = ListValue(entries=((("Wallet", "Coins"), 1), (("Wallet", "Notes"), 2)), origin_names=("Wallet",))

    def test_union_add(self):
        """+ merges two LIST values (InkList.Union)."""
        result = apply_native_function("+", [self.coins, self.notes])
        self.assertEqual(result, self.coins_notes)

    def test_without_subtract(self):
        """- removes items present in the second operand (InkList.Without)."""
        result = apply_native_function("-", [self.coins_notes, self.coins])
        self.assertEqual(result, self.notes)

    def test_intersect(self):
        """^ returns only items shared between both operands (InkList.Intersect)."""
        result = apply_native_function("^", [self.coins_notes, self.coins])
        self.assertEqual(result, self.coins)

    def test_has_and_hasnt(self):
        """? and !? test whether the left operand contains every item of the right."""
        self.assertIs(apply_native_function("?", [self.coins_notes, self.coins]), True)
        self.assertIs(apply_native_function("!?", [self.coins_notes, self.coins]), False)
        self.assertIs(apply_native_function("?", [self.coins, self.notes]), False)

    def test_equality(self):
        """== / != compare LIST values by their full item set."""
        self.assertIs(apply_native_function("==", [self.coins, ListValue.single("Wallet", "Coins", 1)]), True)
        self.assertIs(apply_native_function("!=", [self.coins, self.notes]), True)

    def test_magnitude_comparisons(self):
        """>/</>=/<= compare LIST values by min/max item value, per InkList.GreaterThan/LessThan."""
        self.assertIs(apply_native_function(">", [self.notes, self.coins]), True)
        self.assertIs(apply_native_function("<", [self.coins, self.notes]), True)
        self.assertIs(apply_native_function(">=", [self.notes, self.coins]), True)
        self.assertIs(apply_native_function("<=", [self.coins, self.notes]), True)

    def test_empty_operand_comparisons_are_trivially_decided(self):
        """An empty LIST operand short-circuits every comparison by count
        alone, before any item value is examined."""
        empty = ListValue()
        self.assertIs(apply_native_function(">", [self.coins, empty]), True)
        self.assertIs(apply_native_function(">", [empty, self.coins]), False)
        self.assertIs(apply_native_function("<", [empty, self.coins]), True)

    def test_list_min_max_count_value(self):
        """LIST_MIN/LIST_MAX return single-item ListValues; LIST_COUNT/
        LIST_VALUE return plain ints."""
        self.assertEqual(apply_native_function("LIST_MIN", [self.coins_notes]), self.coins)
        self.assertEqual(apply_native_function("LIST_MAX", [self.coins_notes]), self.notes)
        self.assertEqual(apply_native_function("LIST_COUNT", [self.coins_notes]), 2)
        self.assertEqual(apply_native_function("LIST_VALUE", [self.coins]), 1)

    def test_list_all_and_invert(self):
        """LIST_ALL enumerates every item of the value's origin list(s);
        LIST_INVERT enumerates every item the value does NOT hold."""
        all_items = apply_native_function("LIST_ALL", [self.coins], self.wallet_defs)
        self.assertEqual(all_items.as_dict(), {("Wallet", "Coins"): 1, ("Wallet", "Notes"): 2, ("Wallet", "Cards"): 3})
        inverted = apply_native_function("LIST_INVERT", [self.coins], self.wallet_defs)
        self.assertEqual(inverted.as_dict(), {("Wallet", "Notes"): 2, ("Wallet", "Cards"): 3})

    def test_bool_operand_with_list_operand_raises(self):
        """A non-LIST operand paired with a LIST operand has no defined
        operation in Section 7's real-world scope."""
        with self.assertRaises(Exception):
            apply_native_function(">", [self.coins, 5])

"""Section 4 tests: variables + eval stack core (interactive_fiction.engine).

InkRuntimeState is driven end-to-end against real compiled JSON
(tests/fixtures/section4_*.ink), with every expected transcript captured
from the local inklecate build's -p play-mode transcript before any
assertion was written (per the plan's standing validate-against-real-data
rule). apply_native_function() is additionally unit-tested directly for
operator/type coverage the fixtures don't each need their own story for.
"""

from __future__ import annotations

import json
from pathlib import Path as FilePath

from django.test import SimpleTestCase

from interactive_fiction.engine import (
    InkPathError,
    InkRuntimeState,
    apply_native_function,
    load_story_root,
)

FIXTURES = FilePath(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


class VariableAssignmentTests(SimpleTestCase):
    """Section 4: VAR declarations, reassignment, arithmetic, and interpolation
    (section4_variables.ink)."""

    def test_var_reassignment_and_interpolation_matches_inklecate_transcript(self):
        """VAR declared at 0, reassigned via arithmetic, then interpolated and
        branched on with conditional text — matches the real transcript exactly."""
        state = InkRuntimeState(load_story_root(_load("section4_variables.ink.json")))
        text = state.continue_story()
        self.assertEqual(text, "You have 5 points.\nYou're doing well!\n")

    def test_global_decl_initializes_before_first_continue(self):
        """The VAR's declared value is visible in state.globals right after construction."""
        state = InkRuntimeState(load_story_root(_load("section4_variables.ink.json")))
        self.assertEqual(state.globals["score"], 0)

    def test_reassignment_updates_globals_dict(self):
        """After playing through the reassignment, globals reflects the new value."""
        state = InkRuntimeState(load_story_root(_load("section4_variables.ink.json")))
        state.continue_story()
        self.assertEqual(state.globals["score"], 5)


class ConditionalChoiceTests(SimpleTestCase):
    """Section 4: conditional choice visibility ({condition} on a ChoicePoint)."""

    def test_true_condition_shows_choice_and_matches_transcript(self):
        """A choice gated on a true VAR is shown and its target plays correctly."""
        state = InkRuntimeState(load_story_root(_load("section4_conditional_choice.ink.json")))
        state.continue_story()
        self.assertEqual([c.text for c in state.current_choices], ["Enter"])
        state.choose(0)
        text = state.continue_story()
        self.assertEqual(text, "You entered.\n")

    def test_false_condition_hides_choice_and_matches_transcript(self):
        """A choice gated on a false VAR never appears, matching the real transcript."""
        state = InkRuntimeState(load_story_root(_load("section4_conditional_choice_hidden.ink.json")))
        text = state.continue_story()
        self.assertEqual(text, "A door.\n")
        self.assertEqual(state.current_choices, [])


class NativeFunctionTests(SimpleTestCase):
    """Section 4: apply_native_function() operator coverage, unit-tested
    directly (ported from ink-engine-runtime/NativeFunctionCall.cs's Int/
    Float/String operator tables — inkpy has no equivalent, confirmed
    2026-08-16)."""

    def test_int_arithmetic(self):
        """Int + - * / % all operate directly on Python ints."""
        self.assertEqual(apply_native_function("+", [2, 3]), 5)
        self.assertEqual(apply_native_function("-", [5, 3]), 2)
        self.assertEqual(apply_native_function("*", [4, 3]), 12)
        self.assertEqual(apply_native_function("%", [7, 3]), 1)

    def test_int_division_truncates_like_csharp(self):
        """Int division truncates toward zero (int(a/b)), not Python's floor division."""
        self.assertEqual(apply_native_function("/", [7, 2]), 3)
        self.assertEqual(apply_native_function("/", [-7, 2]), -3)

    def test_float_division_is_true_division(self):
        """Float / never truncates."""
        self.assertEqual(apply_native_function("/", [7.0, 2.0]), 3.5)

    def test_mixed_int_float_promotes_to_float(self):
        """One float operand promotes the whole operation to float, per CoerceValuesToSingleType."""
        self.assertEqual(apply_native_function("+", [1, 2.5]), 3.5)
        self.assertIsInstance(apply_native_function("+", [1, 2.5]), float)

    def test_bool_coerces_to_int_before_arithmetic(self):
        """Bools are coerced to ints before any operation, matching the C# source's note
        that no operation is ever run directly on bools."""
        self.assertEqual(apply_native_function("+", [True, 1]), 2)

    def test_comparisons_return_bool(self):
        """Comparison ops return native Python bools."""
        self.assertIs(apply_native_function(">", [5, 3]), True)
        self.assertIs(apply_native_function("<=", [3, 3]), True)
        self.assertIs(apply_native_function("==", [3, 4]), False)

    def test_logic_ops(self):
        """&&/|| use C-style nonzero truthiness, not Python's and/or short-circuit values."""
        self.assertIs(apply_native_function("&&", [1, 0]), False)
        self.assertIs(apply_native_function("||", [0, 5]), True)

    def test_negate_and_not(self):
        """Unary negate (_) and logical not (!)."""
        self.assertEqual(apply_native_function("_", [5]), -5)
        self.assertIs(apply_native_function("!", [0]), True)
        self.assertIs(apply_native_function("!", [1]), False)

    def test_min_max_pow(self):
        """MIN/MAX/POW match Math.Min/Math.Max/Math.Pow semantics."""
        self.assertEqual(apply_native_function("MIN", [3, 7]), 3)
        self.assertEqual(apply_native_function("MAX", [3, 7]), 7)
        self.assertEqual(apply_native_function("POW", [2, 3]), 8.0)

    def test_floor_ceiling_int_float_on_ints_are_identity(self):
        """FLOOR/CEILING/INT on an int operand are no-ops, per AddIntUnaryOp(..., Identity)."""
        self.assertEqual(apply_native_function("FLOOR", [5]), 5)
        self.assertEqual(apply_native_function("CEILING", [5]), 5)
        self.assertEqual(apply_native_function("INT", [5]), 5)

    def test_floor_ceiling_on_floats_return_float(self):
        """FLOOR/CEILING on a float operand return float, not int."""
        self.assertEqual(apply_native_function("FLOOR", [2.7]), 2.0)
        self.assertEqual(apply_native_function("CEILING", [2.1]), 3.0)
        self.assertIsInstance(apply_native_function("FLOOR", [2.7]), float)

    def test_int_on_float_truncates(self):
        """INT on a float operand truncates to a Python int."""
        self.assertEqual(apply_native_function("INT", [2.9]), 2)
        self.assertIsInstance(apply_native_function("INT", [2.9]), int)

    def test_float_cast(self):
        """FLOAT casts an int operand to float."""
        self.assertEqual(apply_native_function("FLOAT", [5]), 5.0)
        self.assertIsInstance(apply_native_function("FLOAT", [5]), float)

    def test_string_concat_and_equality(self):
        """String Add is concatenation; ==/!= compare string equality."""
        self.assertEqual(apply_native_function("+", ["foo", "bar"]), "foobar")
        self.assertIs(apply_native_function("==", ["a", "a"]), True)
        self.assertIs(apply_native_function("!=", ["a", "b"]), True)

    def test_string_and_int_operand_promotes_to_string(self):
        """A string operand promotes an int operand to string too (str(5) == "5")."""
        self.assertEqual(apply_native_function("+", ["Score: ", 5]), "Score: 5")

    def test_string_subtraction_is_not_defined(self):
        """String "-" has no defined operation (only +, ==, != exist for strings)."""
        with self.assertRaises(InkPathError):
            apply_native_function("-", ["a", "b"])

"""Section 6 tests: functions + threads (interactive_fiction.engine).

InkRuntimeState is driven end-to-end against real compiled JSON
(tests/fixtures/section6_*.ink), with every expected transcript captured
from the local inklecate build's -p play-mode transcript before any
assertion was written (per the plan's standing validate-against-real-data
rule).
"""

from __future__ import annotations

import json
from pathlib import Path as FilePath

from django.test import SimpleTestCase

from interactive_fiction.engine import InkRuntimeState, load_story_root

FIXTURES = FilePath(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


class FunctionCallTests(SimpleTestCase):
    """Section 6: `{func(x)}` inline function calls with return values
    (section6_function.ink)."""

    def test_two_function_calls_match_inklecate_transcript(self):
        """Two independent {func(...)} calls, each returning a value used
        in interpolated text, match the real transcript exactly."""
        state = InkRuntimeState(load_story_root(_load("section6_function.ink.json")))
        text = state.continue_story()
        self.assertEqual(text, "You have 7 points now.\nThe double of 5 is 10.\n")

    def test_function_side_effect_updates_globals(self):
        """A function's own `~ score = ...` reassignment is visible in
        globals after the call, matching real Ink's shared VariablesState."""
        state = InkRuntimeState(load_story_root(_load("section6_function.ink.json")))
        state.continue_story()
        self.assertEqual(state.globals["score"], 7)

    def test_call_stack_is_empty_after_both_calls_return(self):
        """call_stack is pushed to and popped back to empty across each call."""
        state = InkRuntimeState(load_story_root(_load("section6_function.ink.json")))
        state.continue_story()
        self.assertEqual(state.call_stack, [])


class VoidFunctionCallTests(SimpleTestCase):
    """Section 6: `~ func()` void-context call with no `~ return`
    (section6_void_func.ink)."""

    def test_void_call_runs_its_side_effect_and_matches_transcript(self):
        """A void function with no explicit return still runs to
        completion and its side effect (score += 1) is visible afterward."""
        state = InkRuntimeState(load_story_root(_load("section6_void_func.ink.json")))
        text = state.continue_story()
        self.assertEqual(text, "Score is 1.\n")

    def test_void_return_value_is_consumed_not_leaked_onto_eval_stack(self):
        """The compiler's bare "pop" after a void call must leave
        eval_stack clean, not leaking a stray implicit-Void placeholder."""
        state = InkRuntimeState(load_story_root(_load("section6_void_func.ink.json")))
        state.continue_story()
        self.assertEqual(state.eval_stack, [])


class NestedFunctionCallTests(SimpleTestCase):
    """Section 6: a function calling another function, each with its own
    `temp=` parameter scope (section6_nested_func.ink)."""

    def test_nested_call_result_matches_inklecate_transcript(self):
        """outer(10) calls inner(10), and the combined result (10*2+1=21)
        matches the real transcript exactly."""
        state = InkRuntimeState(load_story_root(_load("section6_nested_func.ink.json")))
        text = state.continue_story()
        self.assertEqual(text, "21\n")


class RecursiveFunctionCallTests(SimpleTestCase):
    """Regression coverage for a real bug found 2026-08-16 while
    smoke-testing Section 7 against listToNumber.ink (not caught by any
    Section 6 fixture, since none exercised recursion): a function calling
    itself compiles its `{"f()": path}` target as a *relative* path (e.g.
    ".^.^.^" for direct recursion), not always the absolute top-level name
    Section 6's original _call_function assumed — every recursive call
    silently failed until _call_function was rewritten to resolve target
    paths via _resolve_target, the same way Divert/ChoicePoint targets
    already are (section6_recursive_function.ink)."""

    def test_recursive_self_call_reaches_the_expected_depth(self):
        """Three levels of self-recursion each increment count, matching
        the real transcript exactly (a Section 6 regression, not Section
        7's own scope — no LIST/listDefs involved)."""
        state = InkRuntimeState(load_story_root(_load("section6_recursive_function.ink.json")))
        text = state.continue_story()
        self.assertEqual(text, "Count is 3.\n")


class SingleTopLevelThreadTests(SimpleTestCase):
    """Section 6: a `<- knot` thread with no choices, weaving text inline
    before the main flow continues (section6_thread.ink)."""

    def test_thread_text_is_woven_in_before_main_flow_continues(self):
        """The threaded knot's text appears between the main flow's own
        lines, matching the real transcript exactly."""
        state = InkRuntimeState(load_story_root(_load("section6_thread.ink.json")))
        text = state.continue_story()
        self.assertEqual(text, "You are at a crossroads.\nA distant bell tolls.\n")
        self.assertTrue(state.done)


class ThreadedChoiceTests(SimpleTestCase):
    """Section 6: a thread that itself offers a choice, woven into the
    main flow's own choice list (section6_thread_choice.ink)."""

    def test_threaded_choice_appears_before_main_flow_choices(self):
        """Real Ink runs a thread immediately when reached, so its choices
        are collected before the main flow's own — confirmed against the
        real transcript's numbered choice order."""
        state = InkRuntimeState(load_story_root(_load("section6_thread_choice.ink.json")))
        state.continue_story()
        self.assertEqual([c.text for c in state.current_choices], ["Ring the bell", "Go left", "Go right"])

    def test_choosing_the_threaded_choice_resumes_only_within_the_thread(self):
        """Picking the thread's own choice abandons the main flow entirely,
        matching real Ink's per-thread resumption."""
        state = InkRuntimeState(load_story_root(_load("section6_thread_choice.ink.json")))
        state.continue_story()
        state.choose(0)
        text = state.continue_story()
        self.assertEqual(text, "A distant bell tolls.\n")

    def test_choosing_a_main_flow_choice_still_works_normally(self):
        """A non-threaded choice in the same turn is unaffected by the
        thread that ran alongside it."""
        state = InkRuntimeState(load_story_root(_load("section6_thread_choice.ink.json")))
        state.continue_story()
        state.choose(1)
        text = state.continue_story()
        self.assertEqual(text, "You went left.\n")


class MultipleThreadsTests(SimpleTestCase):
    """Section 6: two threads started in a row before the main flow's own
    choice (section6_thread_multi.ink)."""

    def test_choice_order_matches_thread_start_order_then_main_flow(self):
        """Choices appear in the order their threads were started
        (east before west), with the main flow's own choice last —
        matching the real transcript's numbered choice order exactly."""
        state = InkRuntimeState(load_story_root(_load("section6_thread_multi.ink.json")))
        state.continue_story()
        self.assertEqual([c.text for c in state.current_choices], ["Go east", "Go west", "Wait here"])

    def test_choosing_the_second_thread_matches_transcript(self):
        """Picking the second-started thread's choice resumes correctly,
        independent of the first thread ever having run."""
        state = InkRuntimeState(load_story_root(_load("section6_thread_multi.ink.json")))
        state.continue_story()
        state.choose(1)
        text = state.continue_story()
        self.assertEqual(text, "Sunset awaits.\n")

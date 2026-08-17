"""Section 5 tests: call stack + tunnels (interactive_fiction.engine).

InkRuntimeState is driven end-to-end against real compiled JSON
(tests/fixtures/section5_*.ink), with every expected transcript captured
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


class SingleTunnelTests(SimpleTestCase):
    """Section 5: a single `-> knot ->` / `->->` tunnel (section5_tunnel.ink)."""

    def test_tunnel_return_resumes_right_after_the_divert(self):
        """Content after the tunnel-push divert plays, matching the real transcript."""
        state = InkRuntimeState(load_story_root(_load("section5_tunnel.ink.json")))
        text = state.continue_story()
        self.assertEqual(text, "You approach the door.\nIt's dark in here.\nYou go inside.\n")
        self.assertTrue(state.done)

    def test_tunnel_stack_is_empty_after_a_clean_return(self):
        """tunnel_stack is pushed to and popped back to empty across the tunnel."""
        state = InkRuntimeState(load_story_root(_load("section5_tunnel.ink.json")))
        state.continue_story()
        self.assertEqual(state.tunnel_stack, [])


class NestedTunnelTests(SimpleTestCase):
    """Section 5: a tunnel that itself tunnels into another knot before
    returning (section5_nested_tunnel.ink)."""

    def test_nested_tunnel_returns_match_inklecate_transcript(self):
        """Both ->-> returns resolve to their correct, distinct addresses."""
        state = InkRuntimeState(load_story_root(_load("section5_nested_tunnel.ink.json")))
        text = state.continue_story()
        self.assertEqual(
            text,
            "You start the journey.\n"
            "Entering the outer tunnel.\n"
            "Entering the inner tunnel.\n"
            "Leaving the outer tunnel.\n"
            "You finish the journey.\n",
        )
        self.assertTrue(state.done)


class TunnelWithChoiceTests(SimpleTestCase):
    """Section 5: a tunnel containing choices gathered to a single ->->
    (section5_tunnel_choice.ink)."""

    def test_choosing_inside_a_tunnel_then_returns_to_caller(self):
        """A choice made inside the tunnel is followed, then ->-> returns correctly."""
        state = InkRuntimeState(load_story_root(_load("section5_tunnel_choice.ink.json")))
        text = state.continue_story()
        self.assertEqual(text, "You approach a fork.\nWhich way?\n")
        self.assertEqual([c.text for c in state.current_choices], ["Left", "Right"])
        state.choose(0)
        text2 = state.continue_story()
        self.assertEqual(text2, "You go left.\nYou continue on your way.\n")
        self.assertTrue(state.done)


class StarvedOperatorTests(SimpleTestCase):
    """Section 5: a native-function operator applied with too few eval_stack
    operands must degrade gracefully, not crash.

    Regression coverage for a real bug found 2026-08-16 by smoke-testing
    the engine against real-world example stories (not the hand-authored
    fixtures): pontoon_example.ink crashed with "IndexError: pop from
    empty list" on a bare "MIN" operator whose LIST-typed operand
    (Section 7, out of scope) never got pushed in the first place — the
    compiled form pairs LIST_MIN with a "visit" ControlCommand that
    Section 5 recognizes but doesn't implement, so nothing was on the
    stack when "MIN" ran. section5_starved_operator.json is
    hand-constructed (isolating just the starved-operator shape, not the
    full LIST/visit-index machinery around it) since no compiled .ink
    source directly authors a bare unpaired operator token.
    """

    def test_operator_with_no_operands_does_not_crash(self):
        """A starved operator is silently skipped; content after it still plays."""
        state = InkRuntimeState(load_story_root(_load("section5_starved_operator.json")))
        text = state.continue_story()
        self.assertEqual(text, "Survived.\n")

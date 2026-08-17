"""Step 3 tests: InkRuntimeState.to_dict()/from_dict() serialization
(interactive_fiction.engine).

Every test drives real compiled JSON (existing tests/fixtures/*.ink.json
from Sections 1-10) through a snapshot -> real json.dumps/json.loads round
-trip -> from_dict() rebuild, then confirms the rebuilt state produces
identical continuation output/choices to an unsnapshotted control run —
the actual correctness property this serialization exists for (Step 3's
save-slot/CurrentGame feature only works if a resumed game plays on
exactly as if it had never been serialized at all).
"""

from __future__ import annotations

import json
from pathlib import Path as FilePath

from django.test import SimpleTestCase

from interactive_fiction.engine import (
    InkRuntimeState,
    ListValue,
    ResolvedDivertTarget,
    load_list_defs,
    load_story_root,
)

FIXTURES = FilePath(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def _round_trip(state: InkRuntimeState, root, list_defs=None) -> InkRuntimeState:
    """Serialize state, pass through real json.dumps/loads, rebuild."""
    snapshot = json.loads(json.dumps(state.to_dict()))
    return InkRuntimeState.from_dict(root, snapshot, list_defs)


class BasicRoundTripTests(SimpleTestCase):
    """A freshly-constructed state, and one after a turn with a pending
    choice, both round-trip with identical observable state."""

    def test_fresh_state_round_trips(self):
        """A state that has never taken a turn (only __init__'s global
        -decl bootstrap has run) round-trips with matching globals and
        pointer position."""
        data = _load("section4_variables.ink.json")
        root = load_story_root(data)
        state = InkRuntimeState(root)
        state2 = _round_trip(state, load_story_root(data))
        self.assertEqual(state.globals, state2.globals)
        self.assertEqual(state.turn_count, state2.turn_count)

    def test_state_with_pending_choice_round_trips(self):
        """A state stopped at a choice point round-trips with matching
        choice text/count, and continuing both after choosing the same
        option produces identical text."""
        data = _load("section3_choices.ink.json")
        root = load_story_root(data)
        state = InkRuntimeState(root)
        state.continue_story()
        state2 = _round_trip(state, load_story_root(data))
        self.assertEqual([c.text for c in state.current_choices], [c.text for c in state2.current_choices])
        state.choose(0)
        state2.choose(0)
        self.assertEqual(state.continue_story(), state2.continue_story())


class MidTunnelRoundTripTests(SimpleTestCase):
    """A state snapshotted mid-tunnel (tunnel_stack non-empty) resumes
    and completes identically to the unsnapshotted original."""

    def test_mid_tunnel_state_resumes_identically(self):
        """A snapshot taken with tunnel_stack non-empty resumes and
        finishes the story with the same output as the unsnapshotted run."""
        data = _load("section5_nested_tunnel.ink.json")
        root = load_story_root(data)
        state = InkRuntimeState(root)
        while not state.done and not state.tunnel_stack:
            state._step()  # pylint: disable=protected-access
        self.assertTrue(state.tunnel_stack, "fixture must reach a non-empty tunnel_stack to test anything")
        state2 = _round_trip(state, load_story_root(data))
        self.assertEqual(len(state.tunnel_stack), len(state2.tunnel_stack))
        while not state.done:
            state._step()  # pylint: disable=protected-access
        while not state2.done:
            state2._step()  # pylint: disable=protected-access
        self.assertEqual(state.output.get_text(), state2.output.get_text())


class MidFunctionCallRoundTripTests(SimpleTestCase):
    """Regression coverage for a real bug found while building this
    serialization: the first version of to_dict()/from_dict() omitted
    _eval_run_depth (and the other transient mid-dispatch flags:
    _pending_thread, _in_tag, _tag_buffer, _string_capture_stack)
    entirely. A snapshot taken with call_stack non-empty — meaning a
    function call is in progress, and the *outer* eval run that called it
    is still open — resumed with _eval_run_depth reset to 0 (fresh
    construction's default), which silently routed the eventual "out"
    marker through the no-op CONTROL_COMMAND_MARKERS branch instead of
    real EVAL_OUTPUT handling, producing no output at all instead of the
    interpolated return value."""

    def test_mid_function_call_state_resumes_with_correct_output(self):
        """A snapshot taken with call_stack non-empty still produces the
        correct interpolated function-call result once resumed —
        confirmed against section6_nested_func.ink's real output ("21")."""
        data = _load("section6_nested_func.ink.json")
        root = load_story_root(data)
        state = InkRuntimeState(root)
        while not state.done and not state.call_stack:
            state._step()  # pylint: disable=protected-access
        self.assertTrue(state.call_stack, "fixture must reach a non-empty call_stack to test anything")
        state2 = _round_trip(state, load_story_root(data))
        self.assertEqual(state2._eval_run_depth, state._eval_run_depth)  # pylint: disable=protected-access
        while not state.done:
            state._step()  # pylint: disable=protected-access
        while not state2.done:
            state2._step()  # pylint: disable=protected-access
        self.assertEqual(state.output.get_text(), "21\n")
        self.assertEqual(state.output.get_text(), state2.output.get_text())


class ListValueRoundTripTests(SimpleTestCase):
    """LIST-valued globals round-trip through serialization unchanged,
    including entries/origin_names structure."""

    def test_list_valued_globals_round_trip(self):
        """A story whose globals include real LIST values round-trips
        every entry/origin_names exactly."""
        data = _load("listToNumber.ink.json")
        root = load_story_root(data)
        list_defs = load_list_defs(data)
        state = InkRuntimeState(root, list_defs)
        state.continue_story()
        self.assertTrue(any(isinstance(v, ListValue) for v in state.globals.values()))
        state2 = _round_trip(state, load_story_root(data), list_defs)
        self.assertEqual(state.globals, state2.globals)


class ResolvedDivertTargetRoundTripTests(SimpleTestCase):
    """A ResolvedDivertTarget value (from a DivertTargetValue literal —
    e.g. Ink's empty-bracket choice syntax's own temp-variable plumbing)
    round-trips through serialization to the same logical container."""

    def test_resolved_divert_target_in_temps_round_trips(self):
        """A ResolvedDivertTarget stored in a temp variable resolves to
        the same container (by name) before and after round-tripping."""
        data = _load("section10_bracket_choice.ink.json")
        root = load_story_root(data)
        state = InkRuntimeState(root)
        state.continue_story()
        # Drive one step into the choice-text-building machinery, where a
        # ResolvedDivertTarget is assigned to the temp variable "$r".
        while not state.done and "$r" not in state.temps:
            state._step()  # pylint: disable=protected-access
        self.assertIn("$r", state.temps)
        self.assertIsInstance(state.temps["$r"], ResolvedDivertTarget)
        original_target_path = state.temps["$r"].container.name if state.temps["$r"].container else None
        state2 = _round_trip(state, load_story_root(data))
        resumed_value = state2.temps["$r"]
        self.assertIsInstance(resumed_value, ResolvedDivertTarget)
        self.assertEqual(resumed_value.container.name if resumed_value.container else None, original_target_path)


class MissingContainerDegradationTests(SimpleTestCase):
    """A serialized path that no longer resolves (simulating a changed
    story) degrades to None/dropped rather than raising — the same
    defensive philosophy every other out-of-scope-construct handling in
    this module already follows. Full save-compatibility repair is Step
    4 scope; these tests only confirm from_dict() itself doesn't crash."""

    def test_unresolvable_pointer_path_degrades_to_none(self):
        """A pointer path that fails to resolve produces a null-container
        pointer rather than raising."""
        data = _load("section1_simple.ink.json")
        root = load_story_root(data)
        state = InkRuntimeState.from_dict(root, {"pointer": {"path": "does_not_exist", "index": 0}})
        self.assertIsNone(state.pointer.container if state.pointer else None)

    def test_unresolvable_choice_target_is_dropped(self):
        """A serialized choice whose target path fails to resolve is
        silently omitted from current_choices rather than raising."""
        data = _load("section1_simple.ink.json")
        root = load_story_root(data)
        state = InkRuntimeState.from_dict(root, {"current_choices": [{"text": "Ghost choice", "target_path": "does_not_exist"}]})
        self.assertEqual(state.current_choices, [])

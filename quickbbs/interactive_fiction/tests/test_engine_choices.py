"""Section 3 tests: diverts + basic [choice-only] choices (interactive_fiction.engine).

InkRuntimeState is tested end-to-end against real compiled JSON
(tests/fixtures/section3_choices.ink / section3_gather_loop.ink), driven
turn-by-turn exactly like a player would (continue_story()/choose()), with
every expected transcript captured from the local inklecate build's -p
play-mode transcript before any assertion was written (per the plan's
standing validate-against-real-data rule). Both fixtures deliberately use
only the plain "* [choice-only text]" bracket form — the "text[choice]more"
start+choice-only combo compiles to weave/tunnel machinery ($r variable
pointer redirection) that needs the call stack (Section 5/6), confirmed
absent from Section 3's scope by inspecting real compiled output for that
form (see the plan's Step 2 Section 3 entry).
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


def _play(state: InkRuntimeState, choices: list[int]) -> str:
    """Drive a full playthrough, choosing each index in order, and return the joined text."""
    text = state.continue_story()
    for index in choices:
        state.choose(index)
        text += state.continue_story()
    return text


class BasicChoiceTests(SimpleTestCase):
    """Section 3: two once-only bracket choices, no loop (section3_choices.ink)."""

    def test_first_turn_offers_both_choices_with_correct_text(self):
        """Both choices are collected on the opening turn with their bracket text."""
        state = InkRuntimeState(load_story_root(_load("section3_choices.ink.json")))
        state.continue_story()
        self.assertEqual([c.text for c in state.current_choices], ["Go north", "Go south"])

    def test_choosing_north_matches_inklecate_play_transcript(self):
        """Choosing the first choice matches inklecate -p's transcript exactly."""
        state = InkRuntimeState(load_story_root(_load("section3_choices.ink.json")))
        text = _play(state, [0])
        self.assertEqual(text, "Hello, traveler.\nYou went north.\n")
        self.assertTrue(state.done)

    def test_choosing_south_matches_inklecate_play_transcript(self):
        """Choosing the second choice reaches different, further content."""
        state = InkRuntimeState(load_story_root(_load("section3_choices.ink.json")))
        text = _play(state, [1])
        self.assertEqual(text, "Hello, traveler.\nYou went south.\nYou made your choice.\n")
        self.assertTrue(state.done)

    def test_story_ends_with_no_choices_pending_after_either_branch(self):
        """After either branch resolves, no more choices are offered."""
        state = InkRuntimeState(load_story_root(_load("section3_choices.ink.json")))
        _play(state, [1])
        self.assertEqual(state.current_choices, [])


class GatherLoopTests(SimpleTestCase):
    """Section 3: named knots, a self-loop divert, and once-only pruning
    (section3_gather_loop.ink)."""

    def test_leaving_immediately_matches_inklecate_play_transcript(self):
        """Choosing "Leave" on the first turn diverts straight to the outside knot."""
        state = InkRuntimeState(load_story_root(_load("section3_gather_loop.ink.json")))
        text = _play(state, [1])
        self.assertEqual(text, "You are in a room.\nYou step outside.\n")
        self.assertTrue(state.done)

    def test_looking_around_once_then_leaving_matches_inklecate_play_transcript(self):
        """Looping back into the same knot once, then leaving, matches the real transcript."""
        state = InkRuntimeState(load_story_root(_load("section3_gather_loop.ink.json")))
        text = _play(state, [0, 0])
        self.assertEqual(text, "You are in a room.\nYou are in a room.\nYou step outside.\n")
        self.assertTrue(state.done)

    def test_once_only_choice_is_pruned_after_being_taken(self):
        """ "Look around" (once_only) disappears from current_choices after being chosen."""
        state = InkRuntimeState(load_story_root(_load("section3_gather_loop.ink.json")))
        state.continue_story()
        self.assertEqual([c.text for c in state.current_choices], ["Look around", "Leave"])
        state.choose(0)
        state.continue_story()
        self.assertEqual([c.text for c in state.current_choices], ["Leave"])


class ControlCommandMarkerTests(SimpleTestCase):
    """Section 3: bare ControlCommand markers must never leak as visible text.

    Regression coverage for a real bug found 2026-08-16 by smoke-testing
    the engine against real-world example stories (not the hand-authored
    fixtures): a bare "nop"/"thread" marker in real compiled output (e.g.
    from murder_scene.ink's `<- compare_prints` thread weave) was falling
    through to push_text() and appearing in visible output as literal
    text, because only EVAL_START/EVAL_END/STRING_START/STRING_END/
    DONE_COMMANDS were recognized as control-command markers.

    section3_control_command_leak.json is hand-constructed, not compiled
    by inklecate — "nop" is an internal compiler artifact (a structural
    placeholder), not something directly authorable in .ink source, so
    there's no real .ink file to compile it from. Every other Section 3
    fixture is compiled from real .ink source and playtested against a
    real inklecate transcript; this one instead pins down the exact
    documented JSON encoding for ControlCommand markers (see
    serialisation.py's ENCODING SCHEME docstring in
    claude_docs/tools/inkpy-reference/runtime/, cross-referenced against
    control_command.py's CommandType enum for the full marker set).
    """

    def test_nop_marker_does_not_appear_in_output_text(self):
        """A bare "nop" marker between two text tokens contributes no text of its own."""
        state = InkRuntimeState(load_story_root(_load("section3_control_command_leak.json")))
        text = state.continue_story()
        self.assertEqual(text, "Before.\nAfter.\n")

    def test_nop_marker_inside_choice_text_string_capture_does_not_leak(self):
        """A bare "nop" marker inside an active str/../str capture (not just
        the main output stream) must not leak into a choice's text either.

        Regression coverage for a second, distinct instance of the same bug
        class found 2026-08-16 while hand-converting real narrative content
        (claude_docs/plans/a_spell_for_all.md): an inline conditional
        inside choice-only bracket text (`* [Follow {use_alt:Sarah|Angela}]`)
        compiles to two branch containers that both divert to a shared join
        point, followed by a bare "nop" *inside* the choice text's own
        str/../str string-capture run (section3_choice_text_conditional.ink,
        real inklecate-compiled output, not hand-constructed). This is a
        different code path than the main-stream leak above:
        _handle_string_capture_command was unconditionally capturing every
        token as literal text once a capture was active, without first
        checking CONTROL_COMMAND_MARKERS the way the main-stream branch in
        _handle_string_content already did — producing "Follow Angelanop"
        instead of "Follow Angela".
        """
        state = InkRuntimeState(load_story_root(_load("section3_choice_text_conditional.ink.json")))
        text = state.continue_story()
        self.assertEqual(text, "Test.\n")
        self.assertEqual([c.text for c in state.current_choices], ["Follow Angela"])
        state.choose(0)
        text += state.continue_story()
        self.assertEqual(text, "Test.\nDone.\n")
        self.assertTrue(state.done)

    def test_operator_inside_choice_text_string_capture_does_not_leak(self):
        """A native-function operator token (e.g. "==") inside an active
        str/../str capture must be evaluated, not captured as literal text.

        Regression coverage for a real bug found 2026-08-20 while
        hand-converting batch 2 of claude_docs/plans/a_spell_for_all.md
        (tammy.ink): a choice-text inline conditional whose CONDITION is a
        comparison, not a bare bool var (`* [{lvl == 2:"Fuck"|Other text}]`,
        section13_operator_in_choice_text_string_capture.ink, real
        inklecate-compiled output), compiles to a NESTED "ev"/"/ev" pair
        *inside* the outer choice-text "str"/"/str" capture — the inner
        eval run's own operator token ("==") is eval-stack machinery
        belonging to the condition check, not text content, but
        _handle_string_capture_command's `if self._string_capture_stack:`
        branch was unconditionally capturing every non-marker token as
        literal text once a capture was active (the same bug class as the
        "nop" leak above, but for NATIVE_FUNCTION_ARITY/story-metadata/RNG
        markers rather than CONTROL_COMMAND_MARKERS), producing
        '=="Fuck"' instead of '"Fuck"'. Fixed by also checking
        NATIVE_FUNCTION_ARITY/CHOICE_COUNT/TURNS/TURNS_SINCE/READ_COUNT/
        VISIT_INDEX/rnd/srnd/seq/lrnd before falling through to the
        unconditional text-capture branch, routing them to
        _apply_operator_defensively/_handle_story_metadata_command/
        _handle_rng_command exactly like at eval-run depth 0.
        """
        state = InkRuntimeState(
            load_story_root(_load("section13_operator_in_choice_text_string_capture.ink.json"))
        )
        text = state.continue_story()
        self.assertEqual(text, "Test.\n")
        self.assertEqual([c.text for c in state.current_choices], ['"Fuck"'])
        state.choose(0)
        text += state.continue_story()
        self.assertEqual(text, "Test.\nDone.\n")
        self.assertTrue(state.done)

    def test_var_interpolation_inside_choice_text_string_capture_does_not_truncate(self):
        """A plain `{var}` interpolation inside an active str/../str
        choice-text capture must be evaluated AND leave the literal text
        that follows it (in the same capture) intact.

        Regression coverage for a real bug found 2026-08-20 while
        hand-converting batch 3 of claude_docs/plans/a_spell_for_all.md
        (officerkhan.ink): `* [Obey the {officer_title}?]`
        (section14_var_interpolation_in_choice_text_string_capture.ink,
        real inklecate-compiled output) compiles the choice text's
        str/../str capture as `"str", "^Obey the ", "ev",
        {"VAR?": "officer_title"}, "out", "/ev", "^?", "/str"` — a NESTED
        "ev"/"/ev" pair around the VariableReference, same shape as the
        operator case fixed above (2026-08-16, tammy.ink), but for a bare
        variable read rather than a comparison. Two distinct bugs were
        found isolating this:

        (1) `_handle_string_capture_command`'s CONTROL_COMMAND_MARKERS
        fast path unconditionally swallowed "out" (EVAL_OUTPUT is
        literally a member of that frozenset) and returned True before
        ever reaching `_handle_eval_run_command`'s real EVAL_OUTPUT
        handling, discarding the interpolated value entirely.

        (2) Once "out" was excluded from that fast path, the literal `?`
        character immediately following the nested ev/../ev block (back
        at the capture's own base eval-run depth, which is itself already
        > 0 since the whole capture sits inside the choice's own
        surrounding "ev") still matched — this capture's own operator/
        native-function check was gated on a bare `self._eval_run_depth >
        0`, but `?` collides with LIST_NATIVE_FUNCTION_ARITY's "?" (the
        LIST "contains" operator, merged into NATIVE_FUNCTION_ARITY at
        module scope), and depth was still 1 (the capture's own base
        level), not 0. Fixed by recording each string capture's own
        baseline `_eval_run_depth` in a new parallel
        `_string_capture_eval_depth` stack when the capture opens, and
        comparing against THAT baseline (not a bare 0) to distinguish
        "genuinely inside the nested eval run this capture opened" from
        "back at this capture's own text level" — both EVAL_OUTPUT's
        CONTROL_COMMAND_MARKERS exclusion and the operator/native-function
        check now use this baseline comparison.

        Before both fixes: choice text was `"Obey the"` (missing both the
        interpolated "Officer" and the trailing "?"). After fixing bug (1)
        alone: `"Obey the Officer"` (interpolation restored, but "?" still
        swallowed as a false-positive LIST operator). After both fixes:
        `"Obey the Officer?"`, matching inklecate's own -p transcript for
        the identical compiled JSON exactly.
        """
        state = InkRuntimeState(
            load_story_root(_load("section14_var_interpolation_in_choice_text_string_capture.ink.json"))
        )
        text = state.continue_story()
        self.assertEqual(text, "Hub.\n")
        self.assertEqual([c.text for c in state.current_choices], ["Obey the Officer?"])
        state.choose(0)
        text += state.continue_story()
        self.assertEqual(text, "Hub.\nDone.\n")
        self.assertTrue(state.done)

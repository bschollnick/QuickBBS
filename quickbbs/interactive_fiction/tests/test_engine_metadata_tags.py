"""Section 9 tests: remaining eval-stack ops + tags (interactive_fiction.engine).

InkRuntimeState is driven end-to-end against real compiled JSON
(tests/fixtures/section9_*.ink), with every expected transcript captured
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


def _run(name: str) -> InkRuntimeState:
    return InkRuntimeState(load_story_root(_load(name)))


class TurnsTests(SimpleTestCase):
    """Section 9: TURNS() (section9_turns.ink)."""

    def test_turns_is_zero_before_any_choice_and_increments_after(self):
        """TURNS() reads 0 on the opening turn and 1 after one choice,
        matching the real transcript exactly — turn_count starts at -1
        internally (ports currentTurnIndex's own -1 initial value) so
        TURNS() (turn_count+1) reads 0 before any choice is made."""
        state = _run("section9_turns.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "Turn is 0.\n")
        state.choose(0)
        text = state.continue_story()
        self.assertEqual(text, "Turn is 1.\n")


class TurnsSinceTests(SimpleTestCase):
    """Section 9: TURNS_SINCE(-> knot) (section9_turns_since.ink) —
    regression coverage for the count_flags/enteringAtStart gating this
    section added to _record_visit()/_visit_changed_containers_due_to_divert()."""

    def test_turns_since_tracks_the_gather_across_a_loop_back_divert(self):
        """A gather labeled `- (start)` re-entered via its own loop-back
        divert (`-> start` from inside a descendant container) still
        records a fresh at-start visit, matching the real transcript's
        0, 0, 1 sequence exactly — the initial (incorrect) version of this
        gating stopped the ancestor walk at the first already-open
        ancestor unconditionally, which silently prevented `start` from
        ever getting a fresh turn-index visit recorded on re-entry."""
        state = _run("section9_turns_since.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "You are here. Since: 0.\n")
        state.choose(0)  # Wait -> loops back to start
        text = state.continue_story()
        self.assertEqual(text, "You are here. Since: 0.\n")
        state.choose(0)  # Leave
        text = state.continue_story()
        self.assertEqual(text, "Leaving. Since: 1.\n")

    def test_never_visited_target_returns_negative_one(self):
        """A DivertTargetValue that fails to resolve to a real Container
        degrades to -1 (the real engine's own "never visited" sentinel),
        not a crash — unit-tested directly since no real compiled story
        produces an unresolvable TURNS_SINCE target."""
        state = _run("section9_turns_since.ink.json")
        state.eval_stack.append(None)
        state._push_turns_since()  # pylint: disable=protected-access
        self.assertEqual(state.eval_stack[-1], -1)


class ReadCountTests(SimpleTestCase):
    """Section 9: bare `{knot_name}` display syntax (section9_readcount.ink)
    and the explicit `READ_COUNT(-> knot)` function form
    (section9_readcount_func.ink) — two different compiled shapes for the
    same underlying visit count, confirmed 2026-08-16 against real
    compiled output."""

    def test_bare_display_syntax_matches_real_transcript(self):
        """`{knot_name}` (compiles to a bare {"CNT?": path} literal,
        resolved directly to its visit count at push time) matches the
        real transcript exactly across two visits."""
        state = _run("section9_readcount.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "Visited 1 times.\n")
        state.choose(0)
        text = state.continue_story()
        self.assertEqual(text, "Visited 2 times.\n")

    def test_explicit_function_syntax_matches_real_transcript(self):
        """`READ_COUNT(-> knot_name)` (compiles to a DivertTargetValue
        literal followed by a bare "readc" marker) matches the real
        transcript exactly across two visits."""
        state = _run("section9_readcount_func.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "Count is 1.\n")
        state.choose(0)
        text = state.continue_story()
        self.assertEqual(text, "Count is 2.\n")


class ChoiceCountTests(SimpleTestCase):
    """Section 9: CHOICE_COUNT() (section9_choicecount.ink)."""

    def test_choice_count_reflects_choices_generated_so_far_this_turn(self):
        """CHOICE_COUNT() read before any ChoicePoint runs this turn is 0,
        matching the real transcript exactly — it is not a running total
        across turns, and not a forward-looking count of choices about to
        be generated later in the same turn."""
        state = _run("section9_choicecount.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "Choices available: 0\n")


class TagTests(SimpleTestCase):
    """Section 9: `# tag text` tag collection (section9_tags.ink)."""

    def test_tag_text_is_excluded_from_visible_output_and_collected_separately(self):
        """Two tagged lines produce visible text with the tag content
        entirely excluded, matching the real transcript exactly, with
        both tags collected into current_tags in encounter order."""
        state = _run("section9_tags.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "You step into a clearing.\nSunlight filters through the leaves.\n")
        self.assertEqual(state.current_tags, ["image: cover.jpg", "mood: calm"])

    def test_conditional_tag_content_does_not_leak_a_nop_marker(self):
        """A tag whose text is itself an inline conditional
        (`# image: {cond:a|b}`) must not leak a bare "nop" marker onto the
        end of the resolved tag string.

        Regression coverage for a third instance of the same bug class
        found 2026-08-16 while adding image tags to a real hand-converted
        story (claude_docs/plans/asfa_ink_conversions/julie.ink,
        claude_docs/plans/a_spell_for_all.md): unlike a conditional
        inside choice-only text (wrapped in ev/../ev, see
        test_engine_choices.py's ControlCommandMarkerTests), the compiler
        does not wrap a conditional inside a tag in ev/../ev at all — it
        runs at main-stream depth while self._in_tag is still True, so
        _handle_tag_command's capture branch was treating the branch's
        trailing "nop" as literal tag text (producing "image: alt.jpgnop"
        instead of "image: alt.jpg") the same way
        _handle_string_capture_command was for choice text.
        """
        state = _run("section9_tag_conditional.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "You step into a clearing.\n")
        self.assertEqual(state.current_tags, ["image: alt.jpg"])

    def test_current_tags_is_scoped_to_the_current_turn_not_cumulative(self):
        """current_tags must not accumulate every tag seen since the start
        of the playthrough — only the tags encountered on the turn just
        produced by the most recent continue_story() call.

        Regression coverage for a real bug found 2026-08-16 alongside the
        two "nop" leak fixes above, while wiring image tags into a real
        converted story (claude_docs/plans/asfa_ink_conversions/julie.ink):
        continue_story() reset current_choices at its start but never
        current_tags, so interactive_fiction.views._current_image_urls()
        (which iterates state.current_tags every turn, expecting only the
        current turn's tags per its own docstring) would show every image
        ever tagged, stacked up, by the end of a playthrough. Confirmed
        against inklecate -p's real transcript: a second tagged turn's
        "# tags:" line shows only that turn's tag, not both.
        """
        state = _run("section9_tag_per_turn.ink.json")
        state.continue_story()
        self.assertEqual(state.current_tags, ["image: a.jpg"])
        state.choose(0)
        state.continue_story()
        self.assertEqual(state.current_tags, ["image: b.jpg"])

    def test_plain_variable_interpolation_inside_a_tag_does_not_leak_into_output(self):
        """A tag whose text interpolates a plain VAR (`# image: {model}/x.jpg`,
        no conditional) must resolve entirely inside the tag, not leak the
        interpolated value onto the front of the next visible line.

        Regression coverage for a real bug found 2026-08-20 during the
        ASFA batch-conversion shakedown (claude_docs/plans/a_spell_for_all.md
        Section 13, esmeralda.ink): unlike the conditional-tag-content case
        above (test_conditional_tag_content_does_not_leak_a_nop_marker),
        this construct DOES run inside an "ev"/"/ev" eval run (a bare
        `{var}` interpolation always does), so it reaches
        _handle_eval_run_command's own EVAL_OUTPUT ("out") branch — which
        unconditionally wrote the popped value to self.output regardless of
        self._in_tag, instead of routing it into self._tag_buffer like
        every other tag-content token already does. Confirmed against
        inklecate -p's real transcript: "You step into a clearing." with a
        separate "# tags: image: Anna/gypsy0.jpg" line, no leaked "Anna"
        prefix and no empty model in the tag.
        """
        state = _run("section11_tag_variable_interpolation.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "You step into a clearing.\n")
        self.assertEqual(state.current_tags, ["image: Anna/gypsy0.jpg"])

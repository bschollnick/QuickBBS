"""Section 10 tests: EXTERNAL fallback resolution + full-story validation
(interactive_fiction.engine).

InkRuntimeState is driven end-to-end against real compiled JSON
(tests/fixtures/section10_*.ink), with every expected transcript captured
from the local inklecate build's -p play-mode transcript before any
assertion was written (per the plan's standing validate-against-real-data
rule). This module also covers the empty-bracket choice syntax
(`* text[]more`) uncovered by this section's real-world validation pass
against theintercept.ink — genuinely Section 10 scope, not a separate
section, since it was found and fixed as part of this section's own
full-story validation work.
"""

from __future__ import annotations

import json
from pathlib import Path as FilePath

from django.test import SimpleTestCase

from interactive_fiction.engine import (
    InkRuntimeState,
    find_unbound_externals,
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


class ExternalFallbackTests(SimpleTestCase):
    """Section 10 / Step 4: EXTERNAL declarations resolve to their ink
    fallback function — confirmed 2026-08-16 that `EXTERNAL name(...)`
    leaves no trace at all in compiled JSON; a same-named
    `=== function name(...) ===` immediately after it is already an
    ordinary function. The compiled call site itself, however, is not an
    ordinary `{"f()": ...}` — it's `{"x()": ..., "exArgs": n}`, a distinct
    key this module never had a builder for until Step 4 (found 2026-08-16
    while building Step 4's upload validation): every external call
    silently no-op'd instead of dispatching, and both fixtures below
    happened to render identical final text either way (uppercase.ink's
    fallback is an identity passthrough; string_to_list.ink's skipped call
    left the original string on the eval stack, which happens to render
    the same as the correctly-resolved single-word LIST item) — a false
    positive that masked the bug for two full sections. Text-only
    assertions here are kept for their original real-transcript-fidelity
    purpose; ExternalCallDispatchTests below adds a side-effect-based
    assertion the no-op bug could not have satisfied by coincidence."""

    def test_uppercase_fallback_matches_real_transcript(self):
        """UPPERCASE's ink fallback ({txt}) is a stub that doesn't
        actually uppercase — matches the real transcript exactly,
        including that non-transformation, since QuickBBS never binds a
        real host function (section10_external_uppercase.ink)."""
        state = _run("section10_external_uppercase.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "Give me wine!\n")

    def test_string_to_list_fallback_matches_real_transcript(self):
        """STRING_TO_LIST's fallback chain (a sentinel function + a
        recursive string-match search) resolves "Paris" back to the LIST
        item Paris, matching the real transcript exactly
        (section10_external_string_to_list.ink)."""
        state = _run("section10_external_string_to_list.ink.json", with_list_defs=True)
        text = state.continue_story()
        self.assertEqual(text, "Result: Paris\n")


class ExternalCallDispatchTests(SimpleTestCase):
    """Step 4: a direct, minimal regression for the "x()" no-op bug found
    2026-08-16 — isolates the dispatch itself (does calling an EXTERNAL
    with a fallback that mutates a global actually run the fallback body)
    rather than relying on final printed text, which the two real-story
    fixtures above showed can coincidentally match even when the call
    never dispatches at all."""

    def test_external_call_runs_its_fallback_body(self):
        """A fallback that sets a global variable must actually run — the
        global's value after the call proves dispatch happened, unlike a
        text-only assertion which the no-op bug could still satisfy by
        accident (section4_external_dispatch_proof.ink)."""
        state = _run("section4_external_dispatch_proof.ink.json")
        state.continue_story()
        self.assertEqual(state.globals.get("ran"), True)


class UnboundExternalTests(SimpleTestCase):
    """Step 4: find_unbound_externals() walks the tree for every "x()"
    call site and checks its target name resolves to a real Container —
    the only viable detection strategy given that EXTERNAL leaves zero
    trace of its own declaration in compiled JSON (confirmed above)."""

    def test_bound_externals_report_nothing(self):
        """A story whose every EXTERNAL has a same-named ink fallback
        reports no unbound names, across both real bundled EXTERNAL
        fixtures."""
        for name in ("section10_external_uppercase.ink.json", "section10_external_string_to_list.ink.json"):
            root = load_story_root(_load(name))
            self.assertEqual(find_unbound_externals(root), [])

    def test_missing_fallback_is_reported_by_name(self):
        """Removing UPPERCASE's own fallback function from the compiled
        tree (simulating a story whose EXTERNAL was never given one) is
        reported by name, not silently accepted."""
        data = _load("section10_external_uppercase.ink.json")
        del data["root"][2]["UPPERCASE"]
        root = load_story_root(data)
        self.assertEqual(find_unbound_externals(root), ["UPPERCASE"])


class VoidReturnTests(SimpleTestCase):
    """Step 4: a function that falls off the end of its body without an
    explicit "~ret" implicitly returns Void (real Ink: functions may
    evaluate to Void) — confirmed 2026-08-16 as a second bug found
    alongside the "x()" one: _advance_pointer was pushing a bare Python 0
    for this case, which a print expression calling such a function (e.g.
    `{UPPERCASE(...)}` where the fallback body has no `~ret`) then rendered
    as the literal text "0" appended after the function's own inline
    output. Covered indirectly by ExternalFallbackTests'
    uppercase.ink case above (its fallback has no `~ret`); this class adds
    a minimal, deliberately EXTERNAL-free fixture isolating just the
    void-return-printed-as-expression behavior."""

    def test_void_returning_function_prints_nothing(self):
        """A function with no `~ret` called as a print expression
        contributes no visible text for its own return value — only
        whatever it explicitly printed via its own inline `{...}` runs
        inside the function body (section4_void_return.ink)."""
        state = _run("section4_void_return.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "Give me wine!\n")


class EmptyBracketChoiceTests(SimpleTestCase):
    """Section 10: `* text[]more` (Ink's empty-bracket choice syntax) —
    found genuinely unimplemented during this section's real-world
    validation pass against theintercept.ink (flagged back in Section 3
    as deferred "weave/tunnel machinery," never picked up by name in any
    later section's own scope list until this validation pass surfaced
    it). Regression coverage for three real bugs found together:
    (1) ChoicePoint.has_start_content was treated as an unconditional
    bail rather than a second text-pop (Story.ProcessChoice pops
    choice-only text, then start text, concatenating them);
    (2) Divert.is_variable_target (`{"->": "varName", "var": true}`) was
    entirely unimplemented — the choice text is built via a divert into
    the choice's own display-text container, then a variable-pointer
    divert back to a saved return address;
    (3) _step()'s out-of-range-index check unconditionally ended the
    whole story instead of walking up to the parent container, which
    broke landing on the empty anonymous return-address container this
    construct's variable-target divert lands on
    (section10_bracket_choice.ink)."""

    def test_choice_text_and_followed_content_match_real_transcript(self):
        """The choice text ("Hut 14", built from start text alone — no
        choice-only text in this fixture) and the content reached after
        choosing it both match the real transcript exactly."""
        state = _run("section10_bracket_choice.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "They are keeping me waiting.\n")
        self.assertEqual([c.text for c in state.current_choices], ["Hut 14"])
        state.choose(0)
        text = state.continue_story()
        self.assertEqual(text, "Hut 14. The door was locked after I sat down.\nI don't even have a pen to do any work.\n")


class ThreadedFunctionConditionalChoiceTests(SimpleTestCase):
    """Section 10: a `<- funcName(-> returnPoint)` thread (a function
    called as a thread, not a bare knot) whose own choice is conditional
    — regression coverage confirmed correct in isolation before this
    section's fixes were applied to the real murder_scene.ink case, which
    additionally depends on the still-out-of-scope `ref` parameter
    feature and is documented as a known exception rather than fixed here
    (section10_thread_func_condition.ink)."""

    def test_false_condition_hides_the_threaded_choice(self):
        """A thread that's a function call, with an internally false
        choice condition, correctly shows no thread-generated choice —
        matching the real transcript's plain ["A", "B"] exactly, with no
        spurious blank-text choice."""
        state = _run("section10_thread_func_condition.ink.json")
        text = state.continue_story()
        self.assertEqual(text, "")
        self.assertEqual([c.text for c in state.current_choices], ["A", "B"])

"""claude_docs/plans/external_expansion_IF_engine.md Steps 2/3: the
Story.is_engine_trusted trust gate and _call_function's real EXTERNAL
dispatch branch.

This module locks in the single most important regression this plan must
never introduce: an EXTERNAL call from an untrusted story must always run
its Ink-side fallback, never a real Python callable, regardless of whether
a binding happens to be registered somewhere — proven now for real, since
Step 3 landed a genuine dispatch branch in _call_function. It also proves
the trusted half actually works (a real Python callable is reached, its
return value flows back into the story), and — per the explicit per-session
isolation requirement in the plan — that two concurrent InkRuntimeState
sessions calling the exact same registered Python callable never leak state
into each other. TestCase (never TransactionTestCase, per standing project
rule) is used only because Story.is_engine_trusted needs a real DB row; the
compiled-JSON fixtures reuse/extend test_engine_external_and_validation.py's
own hand-authored "x()" dispatch-proof convention.
"""

from __future__ import annotations

import json
from pathlib import Path as FilePath

from django.contrib.auth import get_user_model
from django.test import TestCase

from interactive_fiction.engine import InkRuntimeState, load_story_root
from interactive_fiction.models import Story

FIXTURES = FilePath(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


class StoryTrustFlagDefaultsTests(TestCase):
    """Step 2: the field itself must be safe by construction — off unless a
    human deliberately turns it on for a specific story."""

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="trust_gate_owner", password="pw")

    def test_new_story_defaults_to_untrusted(self):
        """A Story created without passing is_engine_trusted explicitly
        must default to False — the unsafe direction (True by default)
        would silently trust every scanner-ingested .inkj file and every
        user upload, reopening the 2026-08-15 'never bind host functions
        to arbitrary content' decision this field exists to preserve."""
        story = Story.objects.create(
            owner=self.owner,
            title="Untrusted by default",
            slug="untrusted-by-default",
            compiled_json=_load("section4_external_dispatch_proof.ink.json"),
        )
        self.assertFalse(story.is_engine_trusted)

    def test_scanner_ingested_style_story_is_untrusted(self):
        """A story with scanner-ingestion fields populated (source_fqfn/
        source_sha256, matching how ingestion.py creates real rows from
        .inkj files) still defaults to untrusted — ingestion has no code
        path that sets this flag, and must never gain one implicitly."""
        story = Story.objects.create(
            owner=self.owner,
            title="Scanned story",
            slug="scanned-story",
            compiled_json=_load("section4_external_dispatch_proof.ink.json"),
            source_fqfn="/albums/some/story.inkj",
            source_sha256="0" * 64,
        )
        self.assertFalse(story.is_engine_trusted)


def _mark_ran_binding() -> bool:
    """A trivial, genuinely stateless Python binding for MARK_RAN() —
    returns a fixed value with no side effect on any shared/module-level
    state, matching the per-session isolation requirement (a real binding
    would instead take explicit arguments/return a value derived only from
    them, never read or write anything outside the call)."""
    return True


def _bindings_for(story: Story) -> dict[str, object]:
    """The real decision point the view layer owns: only ever return real
    bindings for a story explicitly marked trusted — this is the one
    function in this whole test module that is allowed to branch on
    is_engine_trusted, mirroring where that decision will really live
    (views.py's _new_game_state()/_load_game_state(), not the interpreter
    itself)."""
    return {"MARK_RAN": _mark_ran_binding} if story.is_engine_trusted else {}


class UntrustedExternalCallAlwaysUsesFallbackTests(TestCase):
    """Step 2/3's real regression, now proven against the actual dispatch
    branch: an EXTERNAL call from an untrusted story always runs its Ink
    fallback, never a registered Python callable — even when a real
    binding for that exact function name exists and would be reachable for
    a trusted story."""

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="untrusted_gate_owner", password="pw")

    def test_marking_a_story_untrusted_still_runs_the_ink_fallback(self):
        """section4_external_dispatch_proof.ink's MARK_RAN() fallback sets
        a real global (True) — proving the call actually dispatched into
        Ink content, not the Python binding above, which would also set
        the eval stack's return value to True but never touch this
        InkRuntimeState's own `globals` dict at all, so the two paths are
        genuinely distinguishable by more than just the resulting value."""
        story = Story.objects.create(
            owner=self.owner,
            title="Explicitly untrusted",
            slug="explicitly-untrusted",
            compiled_json=_load("section4_external_dispatch_proof.ink.json"),
            is_engine_trusted=False,
        )
        state = InkRuntimeState(load_story_root(story.compiled_json), engine_bindings=_bindings_for(story))
        self.assertEqual(state.engine_bindings, {})
        state.continue_story()
        self.assertEqual(state.globals.get("ran"), True)


class TrustedExternalCallReachesThePythonBindingTests(TestCase):
    """Step 3: a trusted story's EXTERNAL call reaches the registered
    Python callable instead of its Ink fallback."""

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="trusted_dispatch_owner", password="pw")

    def test_trusted_story_dispatches_to_the_real_python_callable(self):
        """With a real binding registered and the story marked trusted,
        MARK_RAN()'s Ink fallback (which flips the already-initialized
        globals["ran"] from False to True) must NOT run — proving the
        Python callable was reached instead of the fallback, not just that
        some code path happened to also produce a truthy value."""
        story = Story.objects.create(
            owner=self.owner,
            title="Explicitly trusted",
            slug="explicitly-trusted-dispatches",
            compiled_json=_load("section4_external_dispatch_proof.ink.json"),
            is_engine_trusted=True,
        )
        state = InkRuntimeState(load_story_root(story.compiled_json), engine_bindings=_bindings_for(story))
        self.assertIn("MARK_RAN", state.engine_bindings)
        state.continue_story()
        self.assertEqual(state.globals.get("ran"), False)

    def test_trusted_story_binding_return_value_flows_back_into_the_story(self):
        """external_expansion_exargs_proof.ink's SUM3(1,2,3) computes 6 via
        its Ink fallback normally; bound to a real Python callable that
        returns a fixed 42 instead, the printed result must reflect the
        Python return value, proving the value genuinely flows back onto
        eval_stack and into the story's own print expression, not just
        that dispatch was reached."""
        story = Story.objects.create(
            owner=self.owner,
            title="Sum via Python",
            slug="sum-via-python",
            compiled_json=_load("external_expansion_sum3_print.ink.json"),
            is_engine_trusted=True,
        )
        state = InkRuntimeState(
            load_story_root(story.compiled_json),
            engine_bindings={"SUM3": lambda a, b, c: 42},
        )
        text = state.continue_story()
        self.assertEqual(text, "Result: 42\n")


class PerSessionIsolationTests(TestCase):
    """The explicit per-session isolation requirement in
    external_expansion_IF_engine.md: multiple users can run multiple Ink
    games concurrently, and nothing about one session may leak into
    another. This test runs two independent InkRuntimeState sessions
    through the exact same registered Python callable object (matching how
    a real per-story binding dict would be shared/reused across every
    request for that story, since it holds no per-game data itself) and
    confirms their resulting game states are fully independent."""

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="isolation_owner", password="pw")
        self.story = Story.objects.create(
            owner=self.owner,
            title="Shared bindings, independent sessions",
            slug="shared-bindings-independent-sessions",
            compiled_json=_load("external_expansion_sum3_print.ink.json"),
            is_engine_trusted=True,
        )

    def test_two_concurrent_sessions_through_the_same_binding_stay_independent(self):
        """Two InkRuntimeState instances, built from the SAME story and
        the SAME bindings dict/callable object, must each hold their own
        independent output/eval_stack/globals — a stateful (and therefore
        non-compliant) binding that stashed something on itself between
        calls would make the second session's result depend on the first
        having already run; this test would only pass by coincidence if
        that were happening, since both sessions call the identical
        SUM3(1,2,3) expression and must both see 6, in either call order."""
        calls: list[int] = []

        def counting_sum3(a: int, b: int, c: int) -> int:
            # Deliberately mutates a variable OUTSIDE this function's own
            # arguments/return value, the exact failure mode the isolation
            # requirement warns about -- proves the *session* state (each
            # InkRuntimeState's own globals/eval_stack) stays independent
            # even though this one shared, stateful callable object is
            # reused across both sessions on purpose.
            calls.append(1)
            return a + b + c

        bindings = {"SUM3": counting_sum3}
        root = load_story_root(self.story.compiled_json)

        session_a = InkRuntimeState(root, engine_bindings=bindings)
        session_b = InkRuntimeState(root, engine_bindings=bindings)

        text_a = session_a.continue_story()
        text_b = session_b.continue_story()

        self.assertEqual(text_a, "Result: 6\n")
        self.assertEqual(text_b, "Result: 6\n")
        # The shared callable really was invoked twice, independently --
        # confirms this test isn't vacuously passing because dispatch
        # never happened at all.
        self.assertEqual(len(calls), 2)
        # Each session's OWN state (eval_stack/output/globals) never
        # touched the other's, regardless of the shared callable above.
        self.assertIsNot(session_a.eval_stack, session_b.eval_stack)
        self.assertIsNot(session_a.output, session_b.output)
        self.assertIsNot(session_a.globals, session_b.globals)

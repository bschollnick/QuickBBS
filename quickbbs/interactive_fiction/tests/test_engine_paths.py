"""Section 1 tests: container/path addressing (interactive_fiction.engine).

Fixture JSON at tests/fixtures/section1_simple.ink.json was compiled from
tests/fixtures/section1_simple.ink using the local inklecate build
(claude_docs/tools/ink-reference) and hand-inspected (see the plan's Step 2
Section 1 entry) to pin down exact expected indices/paths before writing
these assertions.
"""

from __future__ import annotations

import json
from pathlib import Path as FilePath

from django.test import SimpleTestCase

from interactive_fiction.engine import (
    Container,
    Divert,
    InkPathError,
    InkRuntimeState,
    Path,
    _container_path,
    load_story_root,
    resolve_path,
)

FIXTURE_JSON = FilePath(__file__).parent / "fixtures" / "section1_simple.ink.json"


def _load_fixture() -> dict:
    with open(FIXTURE_JSON, encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


class PathParseTests(SimpleTestCase):
    """Section 1: Path.parse() against real Ink path syntax."""

    def test_parses_absolute_dotted_path(self):
        """An absolute path splits into name and index components."""
        path = Path.parse("start.4")
        self.assertFalse(path.is_relative)
        self.assertEqual(len(path.components), 2)
        self.assertEqual(path.components[0].name, "start")
        self.assertEqual(path.components[1].index, 4)

    def test_parses_relative_path_with_parent_marker(self):
        """A leading '.' marks relative; '^' marks a parent-container hop."""
        path = Path.parse(".^.b")
        self.assertTrue(path.is_relative)
        self.assertEqual(len(path.components), 2)
        self.assertTrue(path.components[0].is_parent)
        self.assertEqual(path.components[1].name, "b")

    def test_round_trips_to_string(self):
        """str(Path.parse(raw)) reproduces the original path string."""
        for raw in ("start.4", ".^.b", "next_knot.0"):
            self.assertEqual(str(Path.parse(raw)), raw)


class LoadStoryRootTests(SimpleTestCase):
    """Section 1: load_story_root() against real compiled JSON."""

    def test_raises_on_missing_root_key(self):
        """A story JSON with no 'root' key is rejected, not silently empty."""
        with self.assertRaises(InkPathError):
            load_story_root({"inkVersion": 21})

    def test_builds_named_top_level_knots(self):
        """Top-level knots become named children of the root container."""
        root = load_story_root(_load_fixture())
        self.assertIsInstance(root, Container)
        self.assertIn("start", root.named_content)
        self.assertIn("next_knot", root.named_content)

    def test_strips_text_marker_from_string_content(self):
        """The '^' text marker is stripped from leaf string content."""
        root = load_story_root(_load_fixture())
        start = root.named_content["start"]
        self.assertEqual(start.content[0], "First line.")
        self.assertEqual(start.content[2], "Second line.")

    def test_preserves_newline_leaves(self):
        """Bare newline leaves survive loading unchanged."""
        root = load_story_root(_load_fixture())
        start = root.named_content["start"]
        self.assertEqual(start.content[1], "\n")

    def test_loads_divert_token_as_typed_divert(self):
        """A divert token is loaded as a typed Divert (Section 3), not left opaque."""
        root = load_story_root(_load_fixture())
        start = root.named_content["start"]
        divert = start.content[4]
        self.assertIsInstance(divert, Divert)
        self.assertEqual(str(divert.target_path), "next_knot")

    def test_sets_parent_pointers_on_child_containers(self):
        """Every child Container's parent points back to its owner."""
        root = load_story_root(_load_fixture())
        start = root.named_content["start"]
        self.assertIs(start.parent, root)


class ResolvePathTests(SimpleTestCase):
    """Section 1: resolve_path() navigation against the real fixture tree."""

    def setUp(self):
        self.root = load_story_root(_load_fixture())

    def test_resolves_named_knot(self):
        """A single-component path resolves to the named knot container."""
        result = resolve_path(self.root, Path.parse("start"))
        self.assertIs(result, self.root.named_content["start"])

    def test_resolves_index_within_named_knot(self):
        """An index component resolves to positional content within a knot."""
        result = resolve_path(self.root, Path.parse("start.0"))
        self.assertEqual(result, "First line.")

    def test_resolves_second_knot_first_line(self):
        """Resolution reaches a second top-level knot's own content."""
        result = resolve_path(self.root, Path.parse("next_knot.0"))
        self.assertEqual(result, "Third line.")

    def test_resolves_parent_marker(self):
        """A '^' component steps back up to the parent container."""
        start = self.root.named_content["start"]
        result = resolve_path(start, Path.parse(".^"))
        self.assertIs(result, self.root)

    def test_returns_none_for_missing_named_content(self):
        """An unknown named component fails resolution without raising."""
        result = resolve_path(self.root, Path.parse("does_not_exist"))
        self.assertIsNone(result)

    def test_returns_none_for_out_of_range_index(self):
        """An out-of-range index fails resolution without raising."""
        start = self.root.named_content["start"]
        result = resolve_path(start, Path.parse("99"))
        self.assertIsNone(result)

    def test_returns_none_when_indexing_into_a_leaf(self):
        """Indexing past a leaf (non-Container) value fails, not raises."""
        # start.0 is a leaf string ("First line."), not a Container, so
        # start.0.0 must fail rather than raise.
        result = resolve_path(self.root, Path.parse("start.0.0"))
        self.assertIsNone(result)


class TerminatorOnlyNamedContainerTests(SimpleTestCase):
    """Regression coverage for a real bug found 2026-08-16 while building
    Step 3's save-state serialization: a container reachable *only*
    through a terminator-dict key (e.g. a choice's own weave container,
    "c-0") — with no positionally-placed slot in its parent's content and
    no redundant "#n" repeating that same key — previously had no .name
    set at all, since _load_container only ever set .name from a child's
    own "#n" entry. Real compiled output never repeats a terminator-dict
    key as the child's own "#n" (confirmed by grepping every
    terminator-dict entry in theintercept.ink's compiled output), so such
    a container was silently unnamed and unreachable by
    _container_path()'s real-Ink-matching algorithm (Object.path in
    ink-engine-runtime/Object.cs: named if the child has a valid name,
    else positional index — never a parent named_content reverse lookup).
    Fixed by porting JsonSerialisation.JArrayToContainer's
    `namedSubContainer.name = keyVal.Key`: every terminator-dict-only
    named child's own .name is now set from the dict key unconditionally,
    matching the real engine exactly (section1_terminator_only_named_container.ink,
    hand-authored specifically to isolate this shape: a choice's own
    weave container, "c-0", holding two diverts to an "elsewhere" knot,
    with no positional slot of its own)."""

    def test_choice_weave_container_gets_named_from_terminator_key(self):
        """A ChoicePoint's own weave container (compiled as "c-0" in the
        parent's terminator dict, no positional slot, no redundant "#n")
        has its .name set to "c-0", matching real compiled output's own
        JsonSerialisation.JArrayToContainer behavior."""
        with open(FilePath(__file__).parent / "fixtures" / "section1_terminator_only_named_container.ink.json", encoding="utf-8") as f:
            data = json.load(f)
        root = load_story_root(data)
        state = InkRuntimeState(root)
        state.continue_story()
        target = state.current_choices[0].target
        self.assertEqual(target.name, "c-0")

    def test_container_path_round_trips_through_such_a_container(self):
        """_container_path() produces a path string that resolve_path()
        round-trips back to the exact same container — the actual
        correctness property Step 3's save-state serialization depends
        on. Before the fix, this container's missing .name made it
        unreachable by name and absent from its parent's positional
        content, so _container_path() had no valid component to use."""
        with open(FilePath(__file__).parent / "fixtures" / "section1_terminator_only_named_container.ink.json", encoding="utf-8") as f:
            data = json.load(f)
        root = load_story_root(data)
        state = InkRuntimeState(root)
        state.continue_story()
        target = state.current_choices[0].target
        path_str = _container_path(target)
        resolved = resolve_path(root, Path.parse(path_str))
        self.assertIs(resolved, target)

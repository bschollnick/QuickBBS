"""Section 2 tests: output-stream glue/newline assembly (interactive_fiction.engine).

OutputStream is tested directly against controlled token sequences (unit
level) plus one end-to-end check against real compiled JSON
(tests/fixtures/section2_glue.ink / .ink.json), whose expected text was
captured from the local inklecate build's -p play-mode transcript (see the
plan's Step 2 Section 2 entry for the exact transcript and how the fixture
was iterated to be playable at all — inklecate's -p never enters a story
whose first line is a "== knot ==" header, which the original Section 1
fixture silently had and Section 2 caught).
"""

from __future__ import annotations

import json
from pathlib import Path as FilePath

from django.test import SimpleTestCase

from interactive_fiction.engine import (
    GLUE,
    NEWLINE,
    Container,
    OutputStream,
    load_story_root,
)

FIXTURE_JSON = FilePath(__file__).parent / "fixtures" / "section2_glue.ink.json"


def _load_fixture() -> dict:
    with open(FIXTURE_JSON, encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def _push_all(stream: OutputStream, tokens: list[str]) -> None:
    """Push a sequence of already-split tokens (text/newline/glue) onto stream."""
    for token in tokens:
        if token in (GLUE, NEWLINE):
            stream.push(token)
        else:
            stream.push_text(token)


class GlueTests(SimpleTestCase):
    """Section 2: glue joins text and suppresses the newline it spans."""

    def test_glue_across_a_real_newline_joins_without_space(self):
        """Glue immediately before a newline removes that newline entirely."""
        stream = OutputStream()
        _push_all(stream, ["Hello ", GLUE, NEWLINE, "World."])
        self.assertEqual(stream.get_text(), "Hello World.")

    def test_glue_does_not_add_extra_space(self):
        """Text on both sides of glue keeps exactly the whitespace it wrote."""
        stream = OutputStream()
        _push_all(stream, ["One ", GLUE, " Two ", GLUE, " Three."])
        self.assertEqual(stream.get_text(), "One Two Three.")

    def test_glue_with_nothing_to_suppress_contributes_no_text(self):
        """Glue between two text tokens with no newline is simply invisible."""
        stream = OutputStream()
        _push_all(stream, ["abc", GLUE, "def"])
        self.assertEqual(stream.get_text(), "abcdef")

    def test_glue_eats_trailing_whitespace_already_in_stream(self):
        """New glue trims a newline that was already pushed before it arrived."""
        stream = OutputStream()
        stream.push_text("Hello")
        stream.push(NEWLINE)
        stream.push(GLUE)
        stream.push_text("World.")
        self.assertEqual(stream.get_text(), "HelloWorld.")


class NewlineDedupTests(SimpleTestCase):
    """Section 2: newline suppression rules independent of glue."""

    def test_does_not_lead_with_a_newline(self):
        """A newline pushed before any real content is dropped."""
        stream = OutputStream()
        stream.push(NEWLINE)
        stream.push_text("Text.")
        self.assertEqual(stream.get_text(), "Text.")

    def test_consecutive_newlines_collapse_to_one(self):
        """Two newlines in a row (no glue involved) collapse to a single one."""
        stream = OutputStream()
        stream.push_text("First.")
        stream.push(NEWLINE)
        stream.push(NEWLINE)
        stream.push_text("Second.")
        self.assertEqual(stream.get_text(), "First.\nSecond.")

    def test_newline_after_real_content_is_kept(self):
        """A single newline between two real text tokens is preserved."""
        stream = OutputStream()
        stream.push_text("First.")
        stream.push(NEWLINE)
        stream.push_text("Second.")
        self.assertEqual(stream.get_text(), "First.\nSecond.")


class HeadTailWhitespaceSplitTests(SimpleTestCase):
    """Section 2: push_text() splits leading/trailing newline runs correctly."""

    def test_splits_leading_newline_run_to_single_newline(self):
        """Multiple leading newlines in one token collapse to one on push."""
        stream = OutputStream()
        stream.push_text("Before.")
        stream.push_text("\n\n\nAfter.")
        self.assertEqual(stream.get_text(), "Before.\nAfter.")

    def test_interior_newlines_are_left_untouched(self):
        """A newline in the middle of a text token is not collapsed away."""
        stream = OutputStream()
        stream.push_text("Line one.\nLine two.")
        self.assertEqual(stream.get_text(), "Line one.\nLine two.")


class InlineWhitespaceCollapseTests(SimpleTestCase):
    """Section 2: get_text() collapses runs of inline spaces/tabs."""

    def test_collapses_double_space_from_two_glued_pieces(self):
        """Two adjacent pieces each contributing a space collapse to one."""
        stream = OutputStream()
        stream.push_text("One ")
        stream.push_text(" Two")
        self.assertEqual(stream.get_text(), "One Two")

    def test_drops_leading_indentation_after_a_newline(self):
        """Spaces immediately after a newline (line-start) are dropped, not
        collapsed to one — verified against real inklecate -p output
        (test.ink "First.\\n  Indented.\\n" plays as "First.\\nIndented.\\n",
        2026-08-16): Ink source indentation is not significant whitespace.
        """
        stream = OutputStream()
        stream.push_text("First.")
        stream.push(NEWLINE)
        stream.push_text("  Indented.")
        self.assertEqual(stream.get_text(), "First.\nIndented.")


class RealCompiledStoryTests(SimpleTestCase):
    """Section 2: OutputStream against real inklecate-compiled JSON.

    Expected text captured from the local inklecate build's -p transcript
    for tests/fixtures/section2_glue.ink (per the plan's standing rule on
    validating against real data, not just hand-written unit cases).
    """

    def test_matches_inklecate_play_transcript(self):
        """The story's top-level content renders identically to `inklecate -p`."""
        root = load_story_root(_load_fixture())
        # The fixture has no named knots, so all playable content is the
        # single unnamed sub-container at content[0] (root.content[1:] are
        # story-level bookkeeping: the "done" control command and its
        # None terminator — out of Section 2's scope, so we stop there).
        story_content = root.content[0]
        self.assertIsInstance(story_content, Container)

        stream = OutputStream()
        for item in story_content.content:
            if item is None:
                continue
            if not isinstance(item, str):
                # First non-string token is the compiled "done" sub-container
                # marking the end of playable content for this fixture.
                break
            if item in (GLUE, NEWLINE):
                stream.push(item)
            else:
                stream.push_text(item)

        expected = (
            "Hello World, glued across a real newline.\n"
            "Second paragraph after a real (non-glued) newline.\n"
            "One Two Three, three glues on one line.\n"
        )
        self.assertEqual(stream.get_text(), expected)

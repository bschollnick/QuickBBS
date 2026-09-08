"""Tests for `interactive_fiction.story_markup.story_html`.

The contract has two halves and both matter: the allowlisted emphasis
tags must RENDER (a converted game's source may use `<b>` to mark the player's actual
instructions, so escaping them loses real narrative signal), and
everything else must STAY ESCAPED (story text is untrusted Albums-tree
content served to a logged-in player).
"""

from __future__ import annotations

import re

import pytest

from interactive_fiction.story_markup import ALLOWED_TAGS, story_html


@pytest.mark.parametrize(
    "text,expected",
    [
        ("the <i>Sacred Book of Control</i>", "the <i>Sacred Book of Control</i>"),
        ("an <b>extra-credit assignment</b>", "an <b>extra-credit assignment</b>"),
        ("<em>x</em> and <strong>y</strong>", "<em>x</em> and <strong>y</strong>"),
        # Tag names are normalised to lowercase so the output is uniform
        # regardless of how the story author cased them.
        ("<I>Mixed</I>", "<i>Mixed</i>"),
    ],
)
def test_allowed_emphasis_tags_render(text: str, expected: str) -> None:
    """Allowlisted inline emphasis survives as real markup."""
    assert str(story_html(text)) == expected


@pytest.mark.parametrize(
    "text",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        '<a href="javascript:alert(1)">click</a>',
        "<iframe src='evil'></iframe>",
        # An allowlisted tag NAME carrying attributes must not slip
        # through -- attributes are where event handlers live.
        '<b onclick="evil()">attrs</b>',
        "<div>block</div>",
    ],
)
def test_disallowed_markup_stays_escaped(text: str) -> None:
    """Anything off the allowlist renders literally, never as live markup.

    The check is "no live OPENING tag survives that we did not allow" --
    deliberately not a substring search for `onerror=`/`onclick=`, since
    those strings appear harmlessly inside fully-escaped output (e.g.
    `&lt;img src=x onerror=alert(1)&gt;` is inert text, not a handler).
    What makes markup dangerous is an unescaped `<name`, so that is what
    is asserted against.
    """
    rendered = str(story_html(text))
    live_tags = set(re.findall(r"<\s*/?\s*([a-zA-Z][a-zA-Z0-9]*)", rendered))
    assert live_tags <= ALLOWED_TAGS, f"unexpected live markup {live_tags - ALLOWED_TAGS} in {rendered!r}"
    # An opening tag on the allowlist may only survive bare -- never
    # carrying attributes.
    assert not re.search(r"<\s*[a-zA-Z][a-zA-Z0-9]*\s[^>]*>", rendered)
    assert "&lt;" in rendered


def test_bare_angle_brackets_are_escaped() -> None:
    """Prose comparisons are not mistaken for markup."""
    assert str(story_html("5 < 6 and 7 > 2")) == "5 &lt; 6 and 7 &gt; 2"


@pytest.mark.parametrize("text", [None, ""])
def test_empty_input_is_tolerated(text: str | None) -> None:
    """Callers need no None/empty guard of their own."""
    assert str(story_html(text)) == ""


def test_ampersand_is_escaped_once() -> None:
    """Escaping runs once; entities are not double-escaped into visible noise."""
    assert str(story_html("Tom & Jerry")) == "Tom &amp; Jerry"

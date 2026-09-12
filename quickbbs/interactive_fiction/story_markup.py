"""Render the small set of inline HTML tags story text is allowed to use.

A converted game's original source may write its prose as HTML, leaning on `<i>`/`<b>`
for real narrative work — the opening screen bolds `extra-credit
assignment` and `History Classroom` precisely because those are the
player's instructions, and italicises `Sacred Book of Control` as the
title of the thing the whole game is about. The Ink conversion carried
that markup across verbatim.

Ink itself has no concept of markup: `inklecate` passes `<i>` through as
four ordinary characters, and the engine hands the string to the view
unchanged. Whether the player sees italics or a literal `<i>` is decided
solely by the template — and `quickbbs/settings.py` sets
`"autoescape": True`, so `<` was being rendered as `&lt;` and every tag
showed up as visible text. Nothing stripped the markup; the escaper
neutralised it.

The fix is NOT `|safe`. Story text comes from `.inkj` files in the
Albums tree, which is untrusted content — marking it safe wholesale would
let any future story emit `<script>` into a logged-in player's page.
Instead this module escapes everything, then re-enables exactly the tags
on `ALLOWED_TAGS`. A tag outside that set stays escaped and visibly
literal, which is the honest failure mode: the author sees their tag
didn't render, rather than the tag silently executing.
"""

from __future__ import annotations

import html
import re

from markupsafe import Markup

# Inline emphasis only. Deliberately no `<img>`, `<a>`, or anything
# carrying attributes: attributes are where `onerror=`/`javascript:`
# payloads live, and images belong to the `# image:` tag pipeline
# (interactive_fiction.image_linking), which resolves them to real
# gallery files instead of letting story text address arbitrary URLs.
ALLOWED_TAGS: frozenset[str] = frozenset({"i", "b", "em", "strong"})

# Matches an escaped tag with NO attributes, e.g. "&lt;i&gt;" or
# "&lt;/b&gt;". Attribute-bearing tags never match, so they stay escaped.
_ESCAPED_TAG_RE = re.compile(r"&lt;(/?)([a-zA-Z][a-zA-Z0-9]*)&gt;")


def _unescape_allowed(match: re.Match[str]) -> str:
    """Restore one escaped tag to real markup when it is on the allowlist.

    Args:
        match: A match of `_ESCAPED_TAG_RE`, group 1 being "/" for a
            closing tag and group 2 the tag name.

    Returns:
        The real tag (e.g. `<i>`) when allowed, otherwise the matched
        text unchanged so it stays escaped and renders literally.
    """
    closing, name = match.group(1), match.group(2)
    if name.lower() in ALLOWED_TAGS:
        return f"<{closing}{name.lower()}>"
    return match.group(0)


def story_html(text: str | None) -> Markup:
    """Escape story text, then re-enable the allowed inline emphasis tags.

    Escape-then-selectively-unescape (rather than strip-the-bad-tags) is
    the safe direction: anything this function does not explicitly permit
    has already been neutralised by the time it is considered, so a tag
    shape nobody anticipated fails closed.

    Args:
        text: One paragraph of story text as the Ink engine produced it,
            possibly containing `<i>`/`<b>`. None/empty is tolerated so
            callers need no guard.

    Returns:
        Markup safe to render, with allowlisted tags live and everything
        else escaped.
    """
    if not text:
        return Markup("")
    return Markup(_ESCAPED_TAG_RE.sub(_unescape_allowed, html.escape(str(text))))

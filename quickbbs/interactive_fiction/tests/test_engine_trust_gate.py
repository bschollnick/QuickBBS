"""claude_docs/plans/external_expansion_IF_engine.md Step 2: the real
`Story.is_engine_trusted` DB field defaults safely.

The engine-side half of the trust-gate contract (InkRuntimeState's
dispatch is a pure function of whatever `engine_bindings` it is given —
proven with no Story/DB involved at all) moved to the standalone
`ink_engine` library's own `tests/` (2026-09-08's `ink_engine`
extraction — see claude_docs/plans/ink_engine_standalone_extraction.md).
What's left here is genuinely Django-specific: the real model field's
own safe-by-default guarantee.
"""

from __future__ import annotations

import json
from pathlib import Path as FilePath

from django.contrib.auth import get_user_model
from django.test import TestCase

from interactive_fiction.models import Story

FIXTURES = FilePath(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


class StoryTrustFlagDefaultsTests(TestCase):
    """The field itself must be safe by construction — off unless a
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

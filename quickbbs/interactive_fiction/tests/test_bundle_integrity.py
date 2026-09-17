"""Bundle tamper evidence: the four-case decision every scan applies.

A game is re-examined on every ingestion scan. A bundle whose contents no
longer match what was recorded is a new release when it says so, and
tampering when it does not.
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

from django.test import Client, TestCase

from ink_engine.bundle_integrity import recorded_hashes
from interactive_fiction.ingestion import (
    INTEGRITY_INVALID,
    INTEGRITY_NEW_VERSION,
    INTEGRITY_OK,
    INTEGRITY_TAMPERED,
    check_bundle_integrity,
)
from interactive_fiction.models import Story
from interactive_fiction.tests.bundle_fixtures import write_bundle

#: The decision table compares recorded hashes against computed ones, so
#: a bundle built by the real bundler exercises it exactly as a published
#: one would -- the hashes are real either way. A test reaching for a
#: shipped game would name content this repo must not know about, and
#: would only pass on a machine holding it.
BUNDLE_VERSION = "1.0"


class BundleIntegrityTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = Path(tempfile.mkdtemp())
        cls.bundle = write_bundle(cls.tmp, name="integritygame", version=BUNDLE_VERSION, with_resolver=True)
        cls.hashes = recorded_hashes(cls.bundle)
        cls.version = BUNDLE_VERSION

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        super().tearDownClass()

    def _story(self, **kwargs) -> Story:
        """An unsaved row carrying whatever a prior ingestion recorded."""
        return Story(**kwargs)

    def _ingested(self) -> Story:
        return self._story(
            bundle_manifest_sha256=self.hashes["manifest"],
            bundle_directory_sha256=self.hashes["directory"],
            bundle_story_sha256=self.hashes["story"],
            game_version=self.version,
        )

    def _stale(self, version: str) -> Story:
        return self._story(
            bundle_manifest_sha256="0" * 64,
            bundle_directory_sha256="0" * 64,
            bundle_story_sha256="0" * 64,
            game_version=version,
        )


class DecisionTableTests(BundleIntegrityTestCase):
    def test_a_never_ingested_row_is_a_new_release(self):
        """No stored hashes means nothing to compare against, so the
        bundle is recorded rather than accused."""
        decision, detail = check_bundle_integrity(self._story(), self.bundle)
        self.assertEqual(decision, INTEGRITY_NEW_VERSION)
        self.assertEqual(detail, "")

    def test_an_unchanged_bundle_passes(self):
        decision, detail = check_bundle_integrity(self._ingested(), self.bundle)
        self.assertEqual(decision, INTEGRITY_OK)
        self.assertEqual(detail, "")

    def test_changed_contents_with_a_changed_version_is_a_new_release(self):
        decision, _ = check_bundle_integrity(self._stale("13.0"), self.bundle)
        self.assertEqual(decision, INTEGRITY_NEW_VERSION)

    def test_changed_contents_at_the_same_version_is_tampering(self):
        decision, detail = check_bundle_integrity(self._stale(self.version), self.bundle)
        self.assertEqual(decision, INTEGRITY_TAMPERED)
        self.assertIn(BUNDLE_VERSION, detail)
        self.assertIn("administrator", detail)


class SelfInconsistentBundleTests(BundleIntegrityTestCase):
    """A bundle whose own recorded hashes do not describe its own
    contents is refused whatever version it claims -- otherwise changing
    the version string would launder a modified game."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _tampered_copy(self, entry: str, extra: bytes) -> Path:
        """Rewrite one entry, keeping the original archive comment -- an
        attacker who edits content but cannot recompute the hashes."""
        target = self.tmp / "tampered.zip"
        with zipfile.ZipFile(self.bundle) as source, zipfile.ZipFile(target, "w") as copy:
            copy.comment = source.comment
            for info in source.infolist():
                if info.filename.endswith("/"):
                    continue
                data = source.read(info.filename)
                copy.writestr(info.filename, data + extra if info.filename == entry else data)
        return target

    def test_injected_plugin_code_is_refused_even_with_a_new_version(self):
        bundle = self._tampered_copy("integritygame/image_resolver.py", b"\nimport os  # injected\n")
        decision, detail = check_bundle_integrity(self._stale("99.0"), bundle)
        self.assertEqual(decision, INTEGRITY_INVALID)
        self.assertIn("does not match", detail)

    def test_an_edited_story_is_refused_even_with_a_new_version(self):
        bundle = self._tampered_copy("integritygame/story.inkj", b" ")
        decision, _ = check_bundle_integrity(self._stale("99.0"), bundle)
        self.assertEqual(decision, INTEGRITY_INVALID)

    def test_an_unreadable_file_is_refused_rather_than_raising(self):
        broken = self.tmp / "broken.zip"
        broken.write_bytes(b"not a zip at all")
        decision, detail = check_bundle_integrity(self._story(), broken)
        self.assertEqual(decision, INTEGRITY_INVALID)
        self.assertTrue(detail)


class BundleVersionWarningTests(BundleIntegrityTestCase):
    """An unfamiliar container version warns; it never blocks ingestion."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _with_version(self, version: str) -> Path:
        """Copy the real bundle, rewriting only its declared version."""
        target = self.tmp / "versioned.zip"
        with zipfile.ZipFile(self.bundle) as source, zipfile.ZipFile(target, "w") as copy:
            comment = (source.comment or b"").decode()
            kept = [line for line in comment.splitlines() if not line.startswith("bundle_version=")]
            copy.comment = "\n".join([f"bundle_version={version}", *kept]).encode()
            for info in source.infolist():
                if not info.filename.endswith("/"):
                    copy.writestr(info.filename, source.read(info.filename))
        return target

    def test_an_unknown_version_is_logged_and_still_ingests(self):
        bundle = self._with_version("9.9")
        with self.assertLogs("interactive_fiction.ingestion", level="WARNING") as captured:
            decision, _detail = check_bundle_integrity(self._story(), bundle)
        self.assertTrue(any("9.9" in message for message in captured.output))
        self.assertNotEqual(decision, INTEGRITY_INVALID, "an unfamiliar version must not block ingestion")

    def test_the_current_version_logs_nothing(self):
        from ink_engine.bundle_integrity import (
            BUNDLE_VERSION,  # pylint: disable=import-outside-toplevel
        )

        bundle = self._with_version(BUNDLE_VERSION)
        with self.assertNoLogs("interactive_fiction.ingestion", level="WARNING"):
            check_bundle_integrity(self._story(), bundle)


class PluginDeniedScreenTests(TestCase):
    """A game that declares plugins explains itself when untrusted.

    Before this, an untrusted story played with zero bindings -- it
    loaded and then quietly did nothing, because every EXTERNAL fell
    through to its Ink stub. The game says what its plugins do, because
    only it knows.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bundle = write_bundle(self.tmp, name="deniedgame", with_plugins=True)
        from django.contrib.auth import (
            get_user_model,  # pylint: disable=import-outside-toplevel
        )

        from ink_engine.game_folder import (
            read_manifest,  # pylint: disable=import-outside-toplevel
        )
        from ink_engine.game_source import (
            open_game_source,  # pylint: disable=import-outside-toplevel
        )

        manifest = read_manifest(open_game_source(self.bundle))
        owner = get_user_model().objects.create_user(username="denyowner", password="pw")
        self.story = Story.objects.create(
            owner=owner,
            title=str(manifest.get("GAME_TITLE") or "A Test Game"),
            slug="denied-game",
            compiled_json={"inkVersion": 21, "root": [["done", None], "done", None], "listDefs": {}},
            source_fqfn=str(self.bundle),
            game_required_plugins=list(manifest.get("REQUIRED_PLUGINS") or []),
            is_engine_trusted=True,
            is_available=True,
        )

    def _untrust(self):
        self.story.is_engine_trusted = False
        self.story.save(update_fields=["is_engine_trusted"])

    def test_the_game_supplies_its_own_explanation(self):
        from interactive_fiction.engine_services import (
            plugin_denied_html,  # pylint: disable=import-outside-toplevel
        )

        html = plugin_denied_html(self.story)
        self.assertIn("world is empty", html, "the game's own screen should be used, not the host fallback")
        self.assertIn("<table>", html)

    def test_a_games_html_is_escaped(self):
        """The screen comes from the untrusted Albums tree and is shown
        BEFORE the game is trusted, so its own HTML must not execute."""
        from interactive_fiction.engine_services import (
            _screen_markdown,  # pylint: disable=import-outside-toplevel
        )

        self.assertNotIn("<script>", _screen_markdown().convert("<script>alert(1)</script>"))

    def test_a_games_markdown_cannot_carry_a_javascript_url(self):
        """`safe_mode="escape"` stops raw HTML but NOT Markdown's own link
        syntax: `![x](javascript:...)` renders a live `<img src=...>`.
        The screen is prose shown before trust, so link targets are
        stripped outright rather than allowlisted by scheme."""
        from interactive_fiction.engine_services import (  # pylint: disable=import-outside-toplevel
            _screen_markdown,
            _without_link_targets,
        )

        for probe in ("[click](javascript:alert(1))", "![x](javascript:alert(2))", "[ok](https://example.com)"):
            with self.subTest(probe=probe):
                rendered = _without_link_targets(_screen_markdown().convert(probe))
                self.assertNotIn("javascript:", rendered.lower())
                self.assertNotIn("href=", rendered)
                self.assertNotIn("src=", rendered)

    def test_stripping_link_targets_leaves_the_prose_readable(self):
        from interactive_fiction.engine_services import (
            plugin_denied_html,  # pylint: disable=import-outside-toplevel
        )

        html = plugin_denied_html(self.story)
        self.assertIn("<table>", html)
        self.assertNotIn("href=", html)

    def test_an_untrusted_story_refuses_to_play_and_points_at_an_admin(self):
        self._untrust()
        client = Client()
        client.force_login(self.story.owner)
        response = client.get(f"/if/{self.story.slug}/", secure=True)
        body = response.content.decode()

        self.assertEqual(response.status_code, 409)
        self.assertIn("is not ready to play", body)
        self.assertIn("Ask an administrator", body)
        self.assertIn("world is empty", body, "the game's own explanation should reach the player too")

    def test_a_trusted_story_plays(self):
        client = Client()
        client.force_login(self.story.owner)
        self.assertEqual(client.get(f"/if/{self.story.slug}/", secure=True).status_code, 200)

    def test_the_admin_sees_the_same_explanation(self):
        """The admin is the one who can act on it."""
        from django.contrib import (
            admin as django_admin,  # pylint: disable=import-outside-toplevel
        )

        rendered = django_admin.site._registry[Story].plugin_requirements(self.story)  # pylint: disable=protected-access
        self.assertIn("world is empty", rendered)

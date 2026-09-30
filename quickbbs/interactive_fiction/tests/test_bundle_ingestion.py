"""Ingesting a real `.zip` bundle, end to end.

The bundle path shares no machinery with the folder path: no FileIndex
row, no per-file gallery scan. What it does share is the integrity rule,
which decides whether a bundle is ingested at all.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model

from ink_engine.plugin import Plugin
from interactive_fiction.ingestion import (
    _ingest_one_bundle,
    canonical_game_path,
    game_bundles,
    manifest_plugin_mismatch,
    verify_stories,
)
from interactive_fiction.models import Story
from interactive_fiction.tests.bundle_fixtures import write_bundle
from quickbbs.tests.albums_root import AlbumsRootTestCase


class BundleIngestionTestCase(AlbumsRootTestCase):
    """Each test ingests a synthetic bundle into a temp games root."""

    def setUp(self):
        super().setUp()
        self.tmp = Path(self.temp_dir)
        self.games_root = Path(self.albums_dir) / "interactive_fiction"
        self.games_root.mkdir()
        self.owner = get_user_model().objects.create_user(username="scanowner", password="pw")

    def _place_bundle(self, name: str = "testgame.zip") -> Path:
        """Build a bundle where ingestion will find it.

        Built rather than copied from anywhere: a test that reached for a
        real game would name content this repo must not know about, and
        would only pass on a machine holding it.
        """
        built = write_bundle(self.tmp / f"src_{name}", name=Path(name).stem)
        target = self.games_root / name
        shutil.move(str(built), target)
        return target


class IngestOneBundleTests(BundleIngestionTestCase):
    """A bundle placed under the games root becomes one playable Story."""

    def test_a_real_bundle_is_ingested(self):
        """A valid bundle ingests to an available row with no error."""
        bundle = self._place_bundle()
        self.assertTrue(_ingest_one_bundle(self.owner, bundle))

        story = Story.objects.get(source_fqfn=str(canonical_game_path(bundle)))
        self.assertEqual(story.title, "A Test Game")
        self.assertTrue(story.is_available)
        self.assertEqual(story.game_ingestion_error, "")

    def test_the_manifest_fields_reach_the_row(self):
        """The manifest's plugin and new-game lists are copied onto the row."""
        bundle = self._place_bundle()
        _ingest_one_bundle(self.owner, bundle)

        story = Story.objects.get(source_fqfn=str(canonical_game_path(bundle)))
        # The point is that the manifest's own lists reach the row, not
        # how long any one game's happen to be.
        self.assertEqual(story.game_required_plugins, [])
        self.assertEqual([field["var"] for field in story.game_new_game_fields], ["player_side"])

    def test_the_compiled_story_is_read_from_inside_the_bundle(self):
        """The compiled story comes from the bundle, with its Ink version."""
        bundle = self._place_bundle()
        _ingest_one_bundle(self.owner, bundle)

        story = Story.objects.get(source_fqfn=str(canonical_game_path(bundle)))
        self.assertIn("root", story.compiled_json)
        self.assertTrue(story.ink_version)

    def test_the_three_hashes_and_version_are_recorded(self):
        """The three integrity hashes and the game version are stored."""
        bundle = self._place_bundle()
        _ingest_one_bundle(self.owner, bundle)

        story = Story.objects.get(source_fqfn=str(canonical_game_path(bundle)))
        self.assertEqual(len(story.bundle_manifest_sha256), 64)
        self.assertEqual(len(story.bundle_directory_sha256), 64)
        self.assertEqual(len(story.bundle_story_sha256), 64)
        self.assertEqual(story.game_version, "1.0")

    def test_re_ingesting_an_unchanged_bundle_keeps_the_same_row(self):
        """A rescan must not churn the pk: every player\'s SaveState and
        CurrentGame hang off it."""
        bundle = self._place_bundle()
        _ingest_one_bundle(self.owner, bundle)
        first = Story.objects.get(source_fqfn=str(canonical_game_path(bundle))).pk

        self.assertTrue(_ingest_one_bundle(self.owner, bundle))
        self.assertEqual(Story.objects.get(source_fqfn=str(canonical_game_path(bundle))).pk, first)
        self.assertEqual(Story.objects.filter(source_fqfn=str(canonical_game_path(bundle))).count(), 1)


#: A compiled story that calls one EXTERNAL, `whereabouts_of`.
STORY_CALLING_AN_EXTERNAL = {
    "inkVersion": 21,
    "root": [
        ["ev", "str", "^hero", "/str", {"x()": "whereabouts_of", "exArgs": 1}, "/ev", {"temp=": "here"}, "\n", "end", ["done", {"#n": "g-0"}], None],
        "done",
        {"whereabouts_of": [{"temp=": "who"}, "ev", "str", "^", "/str", "/ev", "~ret", None], "global decl": ["ev", "/ev", "end", None]},
    ],
    "listDefs": {},
}

#: The only discovered plugin that provides `whereabouts_of`.
WHEREABOUTS = Plugin(name="whereabouts", display_name="Whereabouts", bindings={"whereabouts_of": lambda who: ""})


class ManifestPluginCheckTests(BundleIngestionTestCase):
    """A trusted story's manifest must name every plugin its EXTERNALs need."""

    def _story(self, *, trusted: bool, required: list[str]) -> Story:
        return Story.objects.create(
            owner=self.owner,
            title="Checked",
            slug="checked",
            compiled_json=STORY_CALLING_AN_EXTERNAL,
            is_engine_trusted=trusted,
            game_required_plugins=required,
        )

    @mock.patch("interactive_fiction.ingestion.discover_api_descriptors", return_value={"whereabouts": WHEREABOUTS})
    def test_an_external_only_an_undeclared_plugin_provides_is_reported(self, _discover):
        """An EXTERNAL whose only provider is undeclared names that plugin."""
        mismatch = manifest_plugin_mismatch(self._story(trusted=True, required=[]))
        self.assertIn("'whereabouts' is the only provider", mismatch)

    @mock.patch("interactive_fiction.ingestion.discover_api_descriptors", return_value={"whereabouts": WHEREABOUTS})
    def test_a_declared_provider_passes(self, _discover):
        """A story whose EXTERNAL provider is declared has no mismatch."""
        self.assertEqual(manifest_plugin_mismatch(self._story(trusted=True, required=["whereabouts"])), "")

    @mock.patch("interactive_fiction.ingestion.discover_api_descriptors")
    def test_an_untrusted_story_is_not_checked(self, discover):
        """An untrusted story is not checked, so no game code is loaded."""
        self.assertEqual(manifest_plugin_mismatch(self._story(trusted=False, required=[])), "")
        discover.assert_not_called()

    def test_a_mismatch_leaves_the_bundle_unavailable_with_the_reason(self):
        """Ingestion leaves a mismatched story unavailable, with the reason."""
        bundle = self._place_bundle()
        with mock.patch("interactive_fiction.ingestion.manifest_plugin_mismatch", return_value="'x' is the only provider"):
            self.assertFalse(_ingest_one_bundle(self.owner, bundle))
        story = Story.objects.get(source_fqfn=str(canonical_game_path(bundle)))
        self.assertFalse(story.is_available)
        self.assertIn("'x' is the only provider", story.game_ingestion_error)


class TamperedBundleIngestionTests(BundleIngestionTestCase):
    """A bundle that changed without saying so is disabled, not ingested."""

    def _tamper(self, bundle: Path) -> None:
        """Rewrite one member inside an already-ingested bundle, keeping
        the archive comment -- the hashes then describe what it WAS."""
        rebuilt = bundle.parent / (bundle.name + ".rebuilt")
        with zipfile.ZipFile(bundle) as source, zipfile.ZipFile(rebuilt, "w") as copy:
            copy.comment = source.comment
            for info in source.infolist():
                if info.filename.endswith("/"):
                    continue
                data = source.read(info.filename)
                copy.writestr(info.filename, data + b"\n# injected\n" if info.filename.endswith("story.inkj") else data)
        bundle.unlink()
        rebuilt.rename(bundle)

    def test_a_tampered_bundle_is_refused_and_disabled(self):
        """Changed contents under the same version are refused and disabled."""
        bundle = self._place_bundle()
        _ingest_one_bundle(self.owner, bundle)

        self._tamper(bundle)
        self.assertFalse(_ingest_one_bundle(self.owner, bundle))

        story = Story.objects.get(source_fqfn=str(canonical_game_path(bundle)))
        self.assertFalse(story.is_available)
        self.assertIn("does not match", story.game_ingestion_error)

    def test_a_refused_bundle_keeps_its_row_rather_than_vanishing(self):
        """Disabling is not deletion: the game stays listed for an
        administrator to deal with."""
        bundle = self._place_bundle()
        _ingest_one_bundle(self.owner, bundle)
        original = Story.objects.get(source_fqfn=str(canonical_game_path(bundle))).pk

        self._tamper(bundle)
        _ingest_one_bundle(self.owner, bundle)
        self.assertEqual(Story.objects.get(source_fqfn=str(canonical_game_path(bundle))).pk, original)

    def test_a_corrupt_file_is_refused_without_crashing_the_scan(self):
        """A file that is not a zip is refused and recorded, not raised."""
        broken = self.games_root / "broken.zip"
        broken.write_bytes(b"not a zip at all")
        self.assertFalse(_ingest_one_bundle(self.owner, broken))
        self.assertTrue(Story.objects.filter(game_ingestion_error__contains="broken.zip").exists())


class GameBundleDiscoveryTests(BundleIngestionTestCase):
    """`game_bundles()` finds the bundles ingestion should consider."""

    def test_bundles_are_found_under_the_games_root(self):
        """A bundle directly in the games root is found."""
        self._place_bundle()
        self.assertEqual([p.name for p in game_bundles()], ["testgame.zip"])


class BundleDiscoveryLayoutTests(BundleIngestionTestCase):
    """Where a bundle is allowed to sit, and in what form its path is stored.

    Both facts were wrong when the live game was first switched over: the
    published bundle sits INSIDE its game folder (`<game>/<game>.zip`), which
    the games-root-only scan never saw, and an ingest handed a mixed-case
    path stored it verbatim, so the lowercased path the scan produces
    matched nothing and a duplicate Story row appeared on the next pass.
    """

    def test_a_bundle_inside_its_game_folder_is_found(self):
        """A bundle one level down, in its own game folder, is found."""
        nested = self.games_root / "nestedgame"
        nested.mkdir()
        built = write_bundle(self.tmp / "src_nested", name="nestedgame")
        shutil.move(str(built), nested / "nestedgame.zip")
        self.assertIn("nestedgame.zip", [bundle.name for bundle in game_bundles()])

    def test_the_stored_path_is_the_form_the_scan_produces(self):
        """A mixed-case path must not be stored verbatim: the scan walks
        an already-lowercased albums root, so the two would never match."""
        bundle = self._place_bundle()
        _ingest_one_bundle(self.owner, Path(str(bundle).upper()))
        self.assertTrue(Story.objects.filter(source_fqfn=str(bundle).lower()).exists())

    def test_ingesting_the_same_bundle_in_either_case_makes_one_row(self):
        """The same bundle reached in either letter case makes one row."""
        bundle = self._place_bundle()
        _ingest_one_bundle(self.owner, bundle)
        _ingest_one_bundle(self.owner, Path(str(bundle).upper()))
        self.assertEqual(Story.objects.filter(source_fqfn__iexact=str(bundle)).count(), 1)


class VerifyBundleStoriesTests(BundleIngestionTestCase):
    """`verify_stories()` must not mistake a bundle for a missing file.

    It resolves a story's source through a `.inkj`-filtered gallery
    lookup, which answers None for a `.zip` -- and None means "the source
    is gone", so a live bundled game was tombstoned on the next scan.
    Silent: no error, the game simply left the library.
    """

    def test_an_ingested_bundle_survives_a_verify_pass(self):
        """A verify pass leaves a live bundled game available."""
        bundle = self._place_bundle()
        _ingest_one_bundle(self.owner, bundle)
        story = Story.objects.get(source_fqfn=str(canonical_game_path(bundle)))
        self.assertTrue(story.is_available)

        tombstoned, _restored, _refreshed = verify_stories()

        story.refresh_from_db()
        self.assertEqual(tombstoned, 0)
        self.assertTrue(story.is_available, "a live bundled game was tombstoned by a verify pass")

    def test_a_bundle_that_really_vanished_is_tombstoned(self):
        """The check still has to work: a deleted bundle is a real
        tombstone, not something to skip past."""
        bundle = self._place_bundle()
        _ingest_one_bundle(self.owner, bundle)
        bundle.unlink()

        tombstoned, _restored, _refreshed = verify_stories()

        self.assertEqual(tombstoned, 1)
        self.assertFalse(Story.objects.get(source_fqfn=str(canonical_game_path(bundle))).is_available)

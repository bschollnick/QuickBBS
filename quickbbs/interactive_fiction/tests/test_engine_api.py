"""claude_docs/plans/external_expansion_IF_engine.md's plugin-discovery
redesign (2026-08-22; contract updated 2026-09-08 by the `ink_engine`
standalone-library extraction — see claude_docs/plans/
ink_engine_standalone_extraction.md): interactive_fiction.engine_api's
plugin-source assembly, EngineAPI's admin-managed enable/disable, and
engine_services.bindings_for()'s real per-story isolation + logging.
"""

from __future__ import annotations

import logging
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path

import ink_engine.engine_plugins
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from interactive_fiction.engine_api import clear_api_descriptor_cache, discover_api_descriptors
from interactive_fiction.engine_services import bindings_for
from interactive_fiction.models import EngineAPI, Story, StorySystemConfig
from interactive_fiction.tests.engine_test_utils import AlbumsPathOverrideMixin
from quickbbs.directoryindex import DirectoryIndex

_COMPILED_JSON = {"inkVersion": 21, "root": [["^Hello.", "\n", "done", None], "done", None], "listDefs": {}}


class DiscoverApiDescriptorsTests(AlbumsPathOverrideMixin, SimpleTestCase):
    """The real scan mechanism: every `.py` file under engine_plugins/
    defining a module-level `API` attribute is discovered; files without
    one are silently skipped.

    A converted game's own APIs no longer live under engine_plugins/ --
    they moved to their own game folder under Albums and
    are only ever discovered behind the Story.is_engine_trusted gate
    (engine_api._game_folder_is_trusted). That real, DB-backed discovery
    is covered by DiscoverApiDescriptorsGameFolderTests below; this class stays a plain,
    DB-free SimpleTestCase covering only the generic engine_plugins/ scan.

    discover_api_descriptors() also always scans DirectoryIndex.
    get_albums_root()/interactive_fiction/ for real game folders, which
    requires a Story.objects DB lookup per folder found -- forbidden in a
    SimpleTestCase -- so ALBUMS_PATH is overridden (via AlbumsPathOverrideMixin)
    to an empty temp dir with no interactive_fiction/ subdirectory."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        super().setUp()
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        # discover_api_descriptors() is cached (cleared only on a real
        # Story save or scan_if_stories run) -- force a fresh scan for
        # every test in this class, which exercises the scan mechanism
        # itself and must not see another test's cached result.
        clear_api_descriptor_cache()
        self.addCleanup(clear_api_descriptor_cache)

    def test_all_generic_plugin_apis_are_discovered(self):
        """Every generic, story-agnostic engine_plugins/ module that
        declares an API descriptor is found.

        Asserted as an exact set on purpose: a plugin appearing here that
        nobody meant to ship is as much a problem as one going missing, so
        this is expected to fail when a plugin is added, and to be updated
        deliberately."""
        descriptors = discover_api_descriptors()
        self.assertEqual(
            {"scheduling", "location_graph", "character_occupancy", "characters", "cost_table", "skills", "quests"},
            set(descriptors),
        )

    def test_scheduling_api_exposes_its_real_is_day_binding(self):
        """The scheduling API's descriptor carries a real is_day
        binding, not an empty placeholder."""
        descriptor = discover_api_descriptors()["scheduling"]
        self.assertIn("is_day", descriptor.bindings)

    def test_duplicate_api_name_across_two_files_raises(self):
        """A real, unambiguous configuration error — never silently
        resolved by picking one file's descriptor arbitrarily. Uses two
        REAL temporary .py files under ink_engine's own engine_plugins/
        (removed in tearDown), each declaring a real Plugin with the same
        name, rather than mocking the import mechanism — proving the real
        scanner's own duplicate-detection path, not an approximation of
        it.

        `discover_api_descriptors()` takes no `scan_dir` argument (the
        OLD system's own signature) — it always scans `ink_engine`'s own
        shipped `engine_plugins/` directory, so the duplicate fixture
        files are written there directly."""
        scan_dir = Path(ink_engine.engine_plugins.__file__).resolve().parent
        # No leading underscore: ink_engine.discovery._scan_directory()
        # deliberately skips any module whose name starts with "_" (its
        # own real-module/private-helper convention) -- these fixture
        # files must look like ordinary discoverable plugin modules.
        first_path = scan_dir / "test_dup_api_a.py"
        second_path = scan_dir / "test_dup_api_b.py"
        descriptor_source = textwrap.dedent("""
            from ink_engine.plugin import Plugin

            PLUGIN = Plugin(name="_test_dup_api", display_name="Test Dup API")
            """)
        first_path.write_text(descriptor_source)
        second_path.write_text(descriptor_source)
        try:
            with self.assertRaises(ValueError):
                discover_api_descriptors()
        finally:
            first_path.unlink()
            second_path.unlink()
            sys.modules.pop("ink_engine.engine_plugins.test_dup_api_a", None)
            sys.modules.pop("ink_engine.engine_plugins.test_dup_api_b", None)


class DiscoverApiDescriptorsGameFolderTests(AlbumsPathOverrideMixin, TestCase):
    """`discover_api_descriptors()` must discover a GAME's own API files
    under settings.ALBUMS_PATH/interactive_fiction/<game_name>/ — with
    zero game-specific code anywhere in the discovery mechanism itself.
    Proven here against a synthetic game fixture, not any one real game,
    per the plan's own explicit "prove genericity with a fixture, not
    just one real game" requirement.

    **Module-mode discovery, 2026-09-08** (the `ink_engine` standalone-
    library extraction — see claude_docs/plans/
    ink_engine_standalone_extraction.md): a trusted game folder is a REAL
    importable Python package now (`engine_api._ensure_importable()`
    puts its PARENT directory on `sys.path`, then `discover_plugins()`
    does one bare `importlib.import_module(game_name)` — never more than
    that one call for a module-mode source). This means `discover_
    api_descriptors()` never opens a game's own sibling `.py` files
    directly (e.g. `widgets.py`) — only the game's own `__init__.py` is
    ever imported, so a game's manifest must itself import and re-export
    its submodules' `Plugin`s as a `PLUGINS = [...]` list for
    `discover_plugins()` to ever see them.

    A TestCase (not SimpleTestCase) since a trusted game folder is only
    ever discovered behind engine_api._trusted_game_module_names()'s real
    Story.objects lookup (Story.is_engine_trusted) — every test asserting
    a game folder's API IS discovered must first create a trusted Story
    row whose source_fqfn falls under that folder."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        super().setUp()
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        # DirectoryIndex.get_albums_root() resolves to
        # <ALBUMS_PATH>/albums/ (a fixed "albums" subfolder appended to
        # the configured setting, not the setting's own value directly)
        # — matching that same real convention here, since
        # discover_api_descriptors() derives its own games directory from
        # DirectoryIndex.get_albums_root(), not settings.ALBUMS_PATH raw.
        self.games_dir = Path(self.temp_dir) / "albums" / "interactive_fiction"
        self.games_dir.mkdir(parents=True)
        self.owner = get_user_model().objects.create_user(username="game_folder_discovery_owner", password="pw")
        # discover_api_descriptors() is cached (cleared only on a real
        # Story save or scan_if_stories run) -- force a fresh scan for
        # every test in this class, which builds its own temp games_dir
        # and must not see another test's cached result. A Story.save()
        # in a test body also clears it via the post_save signal, so this
        # is a belt-and-suspenders guarantee at the boundaries.
        clear_api_descriptor_cache()
        self.addCleanup(clear_api_descriptor_cache)

    def tearDown(self):
        super().tearDown()
        # Every fixture game folder is imported for real under its own
        # bare name (sys.path-inserted, per _ensure_importable) -- evict
        # so the NEXT test's own same-named fixture (built under a fresh
        # temp games_dir) is actually re-imported rather than silently
        # reusing this test's now-deleted module.
        for name in list(sys.modules):
            if name.split(".", 1)[0] in ("teststory", "teststory2", "untrustedstory", "not_a_game", "gamea", "gameb"):
                sys.modules.pop(name, None)

    def _make_game_folder(self, name: str, *, plugin_names: tuple[str, ...] = (), with_init: bool = True) -> Path:
        """Create a synthetic game folder, real enough for module-mode
        discovery: a real Python package with an `__init__.py` that
        re-exports a `PLUGINS` list gathering each name in `plugin_names`
        from its own `widgets.py` sibling -- the same real pattern a
        converted game's own manifest follows.

        Args:
            name: The game folder's bare name (also its real dotted
                module name once discovered).
            plugin_names: `Plugin.name` values `widgets.py` should
                declare, each as its own `PLUGIN`-shaped attribute
                gathered into `__init__.py`'s own `PLUGINS` list. Empty
                for a game folder that ships no plugin at all.
            with_init: False to omit `__init__.py` entirely (not a real
                Python package at all, so never a game folder).

        Returns:
            The game folder's path.
        """
        game_dir = self.games_dir / name
        game_dir.mkdir()
        if not with_init:
            return game_dir
        if not plugin_names:
            (game_dir / "__init__.py").write_text("")
            return game_dir
        widgets_source = "\n".join(
            f'PLUGIN_{i} = Plugin(name="{plugin_name}", display_name="{plugin_name}")' for i, plugin_name in enumerate(plugin_names)
        )
        (game_dir / "widgets.py").write_text(f"from ink_engine.plugin import Plugin\n\n{widgets_source}\n")
        init_source = "from . import widgets as _widgets\n\nPLUGINS = [" + ", ".join(f"_widgets.PLUGIN_{i}" for i in range(len(plugin_names))) + "]\n"
        (game_dir / "__init__.py").write_text(init_source)
        return game_dir

    def _real_game_dir(self, name: str) -> Path:
        """Return `name`'s game folder as discover_api_descriptors() itself
        would see it: built from DirectoryIndex.get_albums_root(), which is
        resolved AND lowercased (normalize_fqpn) -- not the same as a plain
        `Path.resolve()` on this fixture's own `self.games_dir / name`,
        which resolves symlinks but does not lowercase (a real mismatch on
        case-preserving filesystems where a temp dir's path itself contains
        uppercase, e.g. macOS's /var -> /private/var symlink combined with
        a mixed-case mktemp prefix).

        Args:
            name: The game folder's name (matches _make_game_folder).

        Returns:
            The game folder's path exactly as engine_api.py's own
            `games_dir.iterdir()` would produce it.
        """
        return Path(DirectoryIndex.get_albums_root()) / "interactive_fiction" / name

    def _trust_game_folder(self, name: str) -> Story:
        """Create a Story whose source_fqfn falls under game folder `name`
        and is marked is_engine_trusted -- the one real gate that lets
        discover_api_descriptors() import that folder's own package.

        Uses `_real_game_dir(name)`, NOT `self.games_dir / name` or a plain
        `Path.resolve()` on it -- engine_api._trusted_game_module_names()
        compares source_fqfn against the real filesystem path
        discover_api_descriptors() iterates (built from
        DirectoryIndex.get_albums_root(), which is both resolved AND
        lowercased by normalize_fqpn). A plain `.resolve()` only resolves
        symlinks, so on a case-preserving filesystem where a resolved
        symlink component happens to differ in case (e.g. macOS's own
        /var -> /private/var combined with a mixed-case mktemp prefix)
        the two paths would mismatch despite naming the same real
        directory.

        Args:
            name: The game folder's name (matches _make_game_folder).

        Returns:
            The created, trusted Story row.
        """
        return Story.objects.create(
            owner=self.owner,
            title=name,
            slug=name,
            compiled_json=_COMPILED_JSON,
            source_fqfn=str(self._real_game_dir(name) / f"{name}.inkj"),
            is_engine_trusted=True,
        )

    def test_a_real_game_folder_api_is_discovered_by_file_path(self):
        """A synthetic game's own real package, importable once its
        Story is trusted, is discovered via its own `__init__.py`
        `PLUGINS` re-export."""
        self._make_game_folder("teststory", plugin_names=("teststory_widgets",))
        self._trust_game_folder("teststory")
        descriptors = discover_api_descriptors()
        self.assertIn("teststory_widgets", descriptors)

    def test_an_untrusted_game_folders_api_is_not_discovered(self):
        """The inverse of the above: with no trusted Story backing this
        folder, it is never made importable/imported at all — the real
        behavior the security gate exists for."""
        self._make_game_folder("untrustedstory", plugin_names=("untrustedstory_widgets",))
        descriptors = discover_api_descriptors()
        self.assertNotIn("untrustedstory_widgets", descriptors)

    def test_a_folder_with_no_init_py_is_not_treated_as_a_game(self):
        """A directory under interactive_fiction/ with no __init__.py is
        an ordinary, unrelated, or not-yet-populated directory — not a
        real Python package, so never a game folder at all."""
        self._make_game_folder("not_a_game", with_init=False)
        descriptors = discover_api_descriptors()
        self.assertNotIn("should_never_be_found", descriptors)

    def test_generic_plugin_and_game_folder_apis_coexist(self):
        """A real generic plugin API (ink_engine's own engine_plugins/)
        and a synthetic game's own API are both discovered in the same
        call, with no collision."""
        self._make_game_folder("teststory2", plugin_names=("teststory2_widgets",))
        self._trust_game_folder("teststory2")
        descriptors = discover_api_descriptors()
        self.assertIn("scheduling", descriptors)
        self.assertIn("teststory2_widgets", descriptors)

    def test_duplicate_name_across_two_game_folders_raises(self):
        """The duplicate-name check spans every game folder, not just
        one folder's own PLUGINS list."""
        for game_name in ("gamea", "gameb"):
            self._make_game_folder(game_name, plugin_names=("_shared_dup_name",))
            self._trust_game_folder(game_name)
        with self.assertRaises(ValueError):
            discover_api_descriptors()

    def test_no_games_directory_at_all_is_not_an_error(self):
        """settings.ALBUMS_PATH/interactive_fiction/ not existing at all
        (e.g. a fresh install with no games ingested yet) must not raise
        — only the generic plugin directory's own APIs are returned."""
        shutil.rmtree(self.games_dir)
        descriptors = discover_api_descriptors()
        self.assertIn("scheduling", descriptors)


# A game-specific discovery test class that stood here was REMOVED
# 2026-08-27: it asserted on one game's own API names and required that
# game's folder to exist on disk, coupling the engine's suite to a
# particular story's content. The generic mechanism it exercised is already proven
# by DiscoverApiDescriptorsGameFolderTests above, against a synthetic
# game fixture -- which is the stronger test, since it cannot pass for
# game-specific reasons. Per the design document's own principle 1.9,
# a game's own discovery assertions belong in that game's test folder
# (Albums/interactive_fiction/<game>/tests/).

class BindingsForPerStoryIsolationTests(TestCase):
    """engine_services.bindings_for()'s real requirements: per-story
    isolation (a story only gets bindings for APIs it opted into via its
    own StorySystemConfig rows) and global enable/disable
    (EngineAPI.is_enabled gates every opted-in API regardless)."""

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="api_isolation_owner", password="pw")
        EngineAPI.objects.update_or_create(name="scheduling", defaults={"display_name": "Scheduling", "is_enabled": True})

    def _make_story(self, slug: str, *, trusted: bool) -> Story:
        return Story.objects.create(
            owner=self.owner,
            title=slug,
            slug=slug,
            compiled_json=_COMPILED_JSON,
            is_engine_trusted=trusted,
        )

    def test_untrusted_story_gets_no_bindings_even_with_a_config_row(self):
        """An untrusted story's opt-in config is never enough on its own —
        Story.is_engine_trusted is still checked first."""
        story = self._make_story("untrusted-with-config", trusted=False)
        StorySystemConfig.objects.create(story=story, system_name="scheduling")
        self.assertEqual(bindings_for(story), {})

    def test_trusted_story_with_no_config_rows_gets_no_bindings(self):
        """Trust alone isn't enough — a story with zero StorySystemConfig
        rows has opted into nothing."""
        story = self._make_story("trusted-no-config", trusted=True)
        self.assertEqual(bindings_for(story), {})

    def test_trusted_story_with_an_enabled_opted_in_api_gets_its_bindings(self):
        """The real success path: trusted + opted-in + enabled yields the
        API's real bindings.

        `scheduling` is a stateful plugin now (it owns a real clock slot,
        `state_key="scheduling"`/`init_state`/`bind` all set) -- unlike
        the OLD system, a caller MUST pass an `engine_state` dict, or
        `bindings_for()` correctly withholds every stateful plugin's own
        bindings (see test_no_engine_state_dict_yields_no_stateful_bindings
        in test_engine_config_schemas.py's sibling coverage)."""
        story = self._make_story("trusted-opted-in", trusted=True)
        StorySystemConfig.objects.create(story=story, system_name="scheduling")
        result = bindings_for(story, {})
        self.assertIn("is_day", result)

    def test_two_stories_opted_into_the_same_api_are_fully_independent(self):
        """The real per-story isolation requirement: story A's own
        StorySystemConfig row/opt-in must never affect story B's
        bindings_for() result, and vice versa."""
        story_a = self._make_story("story-a", trusted=True)
        story_b = self._make_story("story-b", trusted=False)
        StorySystemConfig.objects.create(story=story_a, system_name="scheduling")
        self.assertIn("is_day", bindings_for(story_a, {}))
        self.assertEqual(bindings_for(story_b, {}), {})

    def test_opting_into_a_disabled_api_yields_no_bindings(self):
        """A disabled API contributes no bindings even to a trusted,
        opted-in story."""
        EngineAPI.objects.filter(name="scheduling").update(is_enabled=False)
        story = self._make_story("trusted-disabled-api", trusted=True)
        StorySystemConfig.objects.create(story=story, system_name="scheduling")
        self.assertEqual(bindings_for(story), {})

    def test_disabled_api_reference_is_logged_as_an_error(self):
        """Explicit user requirement: a disabled-but-opted-into API must
        be a REAL, LOGGED, OBSERVABLE misconfiguration — not the ordinary
        silent untrusted-story fallback."""
        EngineAPI.objects.filter(name="scheduling").update(is_enabled=False)
        story = self._make_story("trusted-disabled-logged", trusted=True)
        StorySystemConfig.objects.create(story=story, system_name="scheduling")
        with self.assertLogs("interactive_fiction.engine_services", level=logging.ERROR) as captured:
            bindings_for(story)
        self.assertTrue(any("scheduling" in message and "not enabled" in message for message in captured.output))

    def test_missing_api_reference_is_logged_as_an_error(self):
        """A system_name with no real API file backing it at all (e.g. a
        real row created while the API still existed on disk, which was
        then renamed/removed) is the same real, logged misconfiguration
        class as a disabled one. StorySystemConfig.clean() already
        prevents CREATING such a row today (confirmed: a plain
        .objects.create() with an unknown system_name is rejected at
        save time) — this test reaches the row into that state via a
        queryset .update(), which bypasses full_clean(), matching the
        real-world way this could happen (a row valid when created,
        whose backing API file is deleted afterward)."""
        story = self._make_story("trusted-missing-api", trusted=True)
        config = StorySystemConfig.objects.create(story=story, system_name="scheduling")
        StorySystemConfig.objects.filter(pk=config.pk).update(system_name="no_such_system")
        with self.assertLogs("interactive_fiction.engine_services", level=logging.ERROR) as captured:
            result = bindings_for(story)
        self.assertEqual(result, {})
        self.assertTrue(any("no_such_system" in message for message in captured.output))


class EngineAPIAdminToggleTests(TestCase):
    """The real Enabled/Disabled admin toggle requirement — new APIs
    start disabled by default, matching Story.is_engine_trusted's own
    safe-by-default posture."""

    def test_new_engine_api_row_defaults_to_disabled(self):
        """A freshly created EngineAPI row (matching what sync_engine_apis
        does for a real discovery) defaults to disabled."""
        api = EngineAPI.objects.create(name="brand_new_api", display_name="Brand New API")
        self.assertFalse(api.is_enabled)

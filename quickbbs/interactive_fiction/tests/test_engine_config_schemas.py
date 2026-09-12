"""The closed,
per-system config schema for StorySystemConfig.

StorySystemConfig's real enforcement — that an invalid config is rejected
at .save() time for every caller, not just ones that happen to go through
a ModelForm/admin — and the discover_api_descriptors() dispatch this
enforcement depends on. TestCase (never TransactionTestCase, per standing
project rule) is used only where a real Story/StorySystemConfig row is
needed.

The validators' own pure-function coverage (no DB needed) lives in the
standalone `ink_engine` library, beside each plugin that declares one --
`tests/test_engine_location_graph_config.py` and `tests/test_engine_costs.py`.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from ink_engine.engine_config_schemas import SystemConfigValidationError
from interactive_fiction.engine_api import discover_api_descriptors
from interactive_fiction.models import Story, StorySystemConfig
from interactive_fiction.tests.engine_test_utils import AlbumsPathOverrideMixin

_COMPILED_JSON = {"inkVersion": 21, "root": [["^Hello.", "\n", "done", None], "done", None], "listDefs": {}}

_VALID_LOCATION_GRAPH = {
    "locations": {
        "outside_hospital": {
            "known_by_default": True,
            "edges": [{"to": "hospital_foyer", "requires_known": False}],
        },
        "hospital_foyer": {
            "known_by_default": False,
            "edges": [],
        },
    },
}


class DiscoverApiDescriptorsDispatchTests(AlbumsPathOverrideMixin, SimpleTestCase):
    """StorySystemConfig.clean() (interactive_fiction/models.py) resolves
    a system_name's real validator dynamically via
    interactive_fiction.engine_api.discover_api_descriptors() — replacing
    the old closed VALIDATORS dict/validate_system_config() dispatch
    (removed as part of the plugin-discovery redesign, since a
    hardcoded dict can never represent an API discovered later without
    editing this file). This class covers the discovery function directly;
    StorySystemConfigSaveEnforcementTests below covers the real end-to-end
    model-layer enforcement.

    discover_api_descriptors() also scans DirectoryIndex.get_albums_root()/
    interactive_fiction/ for real game folders, which requires a
    Story.objects DB lookup per folder found (see engine_api.py's
    _trusted_game_module_names) -- forbidden in a SimpleTestCase. Neither
    test here cares about game folders at all (only the two generic
    engine_plugins/ APIs), so ALBUMS_PATH is overridden (via
    AlbumsPathOverrideMixin) to an empty temp dir with no
    interactive_fiction/ subdirectory, keeping this class a real, fast,
    DB-free SimpleTestCase rather than converting to TestCase just to
    tolerate a query neither test needs."""

    def test_real_apis_on_disk_are_discovered_with_their_validators(self):
        """Both real APIs are found, and the one declaring a config
        schema carries its own validator. `character_occupancy` takes no
        config: its schedules are built as Python objects, never as config
        this host could store (see that plugin's own module docstring), so
        its validator accepts an empty config and refuses anything else."""
        descriptors = discover_api_descriptors()
        self.assertIn("location_graph", descriptors)
        self.assertIn("character_occupancy", descriptors)
        map_validator = descriptors["location_graph"].validate_config
        self.assertIsNotNone(map_validator)
        with self.assertRaises(SystemConfigValidationError):
            map_validator({"locations": {}})
        occupancy_validator = descriptors["character_occupancy"].validate_config
        self.assertIsNotNone(occupancy_validator)
        occupancy_validator({})
        with self.assertRaises(SystemConfigValidationError):
            occupancy_validator({"characters": {}})

    def test_unregistered_system_name_is_absent_from_discovery(self):
        """A system_name with no real API file backing it is simply
        absent from discovery — StorySystemConfig.clean() is what turns
        that into a real ValidationError (see
        StorySystemConfigSaveEnforcementTests.test_unknown_system_name_is_rejected)."""
        descriptors = discover_api_descriptors()
        self.assertNotIn("no_such_system", descriptors)


class StorySystemConfigSaveEnforcementTests(TestCase):
    """StorySystemConfig.save() always runs full_clean() — an invalid
    config is rejected for every caller, not just ModelForm/admin flows."""

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="config_owner", password="pw")
        self.story = Story.objects.create(
            owner=self.owner,
            title="Config test story",
            slug="config-test-story",
            compiled_json=_COMPILED_JSON,
        )

    def test_valid_config_saves_cleanly(self):
        """A valid config saves without error, unmodified."""
        config = StorySystemConfig.objects.create(
            story=self.story,
            system_name="location_graph",
            config=_VALID_LOCATION_GRAPH,
        )
        self.assertEqual(config.config, _VALID_LOCATION_GRAPH)

    def test_invalid_config_is_rejected_on_plain_objects_create(self):
        """The real requirement: rejected even via a plain .objects.create()
        call, with no ModelForm/admin involved at all — proving save()'s
        own full_clean() override is what's doing the enforcement, not
        some form-layer validation this call path never goes through."""
        with self.assertRaises(ValidationError):
            StorySystemConfig.objects.create(
                story=self.story,
                system_name="location_graph",
                config={"locations": {}},
            )

    def test_second_config_for_the_same_story_and_system_is_rejected(self):
        """At most one config row per (story, system_name) — the real
        UniqueConstraint, not just documentation."""
        StorySystemConfig.objects.create(
            story=self.story,
            system_name="location_graph",
            config=_VALID_LOCATION_GRAPH,
        )
        with self.assertRaises(ValidationError):
            StorySystemConfig.objects.create(
                story=self.story,
                system_name="location_graph",
                config=_VALID_LOCATION_GRAPH,
            )

    def test_unknown_system_name_is_rejected(self):
        """system_name is a plain string (not a closed enum, corrected
        ) -- but a name with no real, currently-discoverable API
        backing it is still rejected, at the model layer, not silently
        accepted as "no validation needed"."""
        with self.assertRaises(ValidationError):
            StorySystemConfig.objects.create(
                story=self.story,
                system_name="no_such_system",
                config={"anything": True},
            )

    def test_config_less_api_accepts_an_empty_default_config(self):
        """An API with no config schema at all (validate_config=None,
        e.g. engine_plugins/scheduling.py's "scheduling") accepts the
        default empty config — the row's only real purpose for such an
        API is to signal "this story opted into scheduling's bindings"
        (see engine_services.bindings_for()), not to carry data."""
        config = StorySystemConfig.objects.create(story=self.story, system_name="scheduling")
        self.assertEqual(config.config, {})

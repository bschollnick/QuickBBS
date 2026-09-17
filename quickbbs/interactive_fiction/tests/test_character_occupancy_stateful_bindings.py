"""The "stateful EXTERNAL bindings" contract: character_occupancy.py's
set_location/where_is/who_is_at are the first real consumer
of Plugin's state_key/init_state/bind fields — proving (1) bindings_for()
actually resolves them for a real trusted, opted-in story, (2) two
sessions given independently-built engine_state dicts never leak a
set_location() write into each other (the same per-session isolation
requirement test_engine_trust_gate.py's PerSessionIsolationTests proves
for stateless bindings), and (3) a real save/load round-trip through
views.py's own _new_game_state()/_load_game_state()/
_build_current_game_state() persists and restores a set_location()
write across two separate InkRuntimeState instances, sourced only from
CurrentGame.state -- never from any Python object surviving between them.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path as FilePath

from django.contrib.auth import get_user_model
from django.test import TestCase

from ink_engine.engine import InkRuntimeState, load_story_root
from ink_engine.engine_plugins import location_graph
from ink_engine.engine_plugins.character_occupancy import (
    CHARACTER_OCCUPANCY,
    ScheduleRule,
    UnknownLocationError,
)
from ink_engine.engine_plugins.location_graph import LocationGraph
from interactive_fiction.engine_services import bindings_for
from interactive_fiction.models import EngineAPI, Story
from interactive_fiction.views import (
    _build_current_game_state,
    _load_game_state,
    _new_game_state,
)

FIXTURES = FilePath(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def _opt_in(story, plugin_name: str) -> None:
    """Declare one plugin on a story, the way its manifest would.

    `REQUIRED_PLUGINS` is the story's own declaration of what it
    activates (`Story.opted_in_plugin_names`).
    """
    story.game_required_plugins = [*story.game_required_plugins, plugin_name]
    story.save(update_fields=["game_required_plugins"])


class BindingsForResolvesCharacterOccupancyTests(TestCase):
    """bindings_for() actually resolves the 3 real bindings for a
    trusted, opted-in, enabled story -- the ordinary per-story-isolation
    contract test_engine_api.py's BindingsForPerStoryIsolationTests
    already proves for scheduling, now proven for the stateful case."""

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="occupancy_bindings_owner", password="pw")
        EngineAPI.objects.update_or_create(name="character_occupancy", defaults={"display_name": "Character occupancy", "is_enabled": True})

    def test_trusted_opted_in_story_gets_the_real_bindings(self):
        """The real success path yields the full occupancy binding set.

        Five bindings: `is_at`/`is_with`/
        `is_anywhere` were added because "is X here" and "is X
        anywhere at all" are different questions that a story reading the
        store by hand tends to conflate."""
        story = Story.objects.create(
            owner=self.owner,
            title="occupancy-bindings-story",
            slug="occupancy-bindings-story",
            compiled_json=_load("character_occupancy_set_and_get.ink.json"),
            is_engine_trusted=True,
        )
        _opt_in(story, "character_occupancy")
        engine_state: dict = {}
        result = bindings_for(story, engine_state)
        self.assertEqual(
            {"set_location", "where_is", "who_is_at", "is_at", "is_with", "is_anywhere"},
            set(result),
        )
        # init_state() already ran -- engine_state holds a fresh, empty
        # OccupancyState under the plugin's own state_key. This story
        # never opted into `location_graph` itself, so (unlike the OLD
        # `also_reads`-based system, which pre-allocated a reader's own
        # dependency slots regardless of story opt-in) no `location_graph`
        # slot exists at all -- character_occupancy._bind() reads it via
        # a plain `engine_state.get(...)`, so it simply sees `{}`.
        self.assertEqual(engine_state, {"character_occupancy": CHARACTER_OCCUPANCY.init_state(None)})

    def test_no_engine_state_dict_yields_no_stateful_bindings_and_logs(self):
        """A caller that forgets to pass engine_state gets no bindings
        for this API (not a crash) -- engine_services.bindings_for()'s
        own real, logged misconfiguration path."""
        story = Story.objects.create(
            owner=self.owner,
            title="occupancy-bindings-no-state",
            slug="occupancy-bindings-no-state",
            compiled_json=_load("character_occupancy_set_and_get.ink.json"),
            is_engine_trusted=True,
        )
        _opt_in(story, "character_occupancy")
        self.assertEqual(bindings_for(story), {})


class StatefulBindingPerSessionIsolationTests(TestCase):
    """The same per-session isolation requirement
    test_engine_trust_gate.py's PerSessionIsolationTests proves for a
    stateless shared callable, now proven for a REAL stateful binding
    built by character_occupancy.py's own bind_stateful: two sessions,
    each with their own engine_state dict (as two real Django requests
    would each build via views.py), must never let one session's
    set_location() write appear in the other's where_is()."""

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="occupancy_isolation_owner", password="pw")
        EngineAPI.objects.update_or_create(name="character_occupancy", defaults={"display_name": "Character occupancy", "is_enabled": True})
        self.story = Story.objects.create(
            owner=self.owner,
            title="occupancy-isolation-story",
            slug="occupancy-isolation-story",
            compiled_json=_load("character_occupancy_set_and_get.ink.json"),
            is_engine_trusted=True,
        )
        _opt_in(self.story, "character_occupancy")

    def test_two_sessions_with_independent_engine_state_stay_isolated(self):
        """Both sessions run the SAME compiled story (which itself calls
        set_location("traveler", "cellar") unconditionally), but each is
        given its own, separately-built engine_state dict -- exactly how
        views.py's _new_game_state() builds one per real request. Neither
        session's own engine_state dict may end up holding the other's
        data, and each session's own where_is() must reflect only
        its own write."""
        root = load_story_root(self.story.compiled_json)

        engine_state_a: dict = {}
        engine_state_b: dict = {}
        session_a = InkRuntimeState(root, engine_bindings=bindings_for(self.story, engine_state_a))
        session_b = InkRuntimeState(root, engine_bindings=bindings_for(self.story, engine_state_b))

        text_a = session_a.continue_story()
        text_b = session_b.continue_story()

        self.assertEqual(text_a, "Result: cellar\n")
        self.assertEqual(text_b, "Result: cellar\n")
        # Each session's own engine_state dict independently reflects the
        # same write -- proving isolation, not proving nothing happened.
        self.assertEqual(engine_state_a["character_occupancy"]["locations"]["traveler"], "cellar")
        self.assertEqual(engine_state_b["character_occupancy"]["locations"]["traveler"], "cellar")
        self.assertIsNot(engine_state_a["character_occupancy"], engine_state_b["character_occupancy"])

    def test_mutating_one_engine_state_dict_after_the_fact_never_touches_the_other(self):
        """Directly proves the two dicts share no nested structure by
        reference (e.g. a shared inner 'locations' dict would make this
        fail) -- the exact failure mode a careless bind_stateful
        implementation (returning closures over a dict copied shallowly,
        or worse, over a shared default) would produce."""
        engine_state_a: dict = {}
        engine_state_b: dict = {}
        bindings_a = bindings_for(self.story, engine_state_a)
        bindings_b = bindings_for(self.story, engine_state_b)

        bindings_a["set_location"]("traveler", "cellar")
        self.assertIsNone(bindings_b["where_is"]("traveler") or None)
        bindings_b["set_location"]("traveler", "home_bedroom")
        self.assertEqual(bindings_a["where_is"]("traveler"), "cellar")
        self.assertEqual(bindings_b["where_is"]("traveler"), "home_bedroom")


class SaveLoadRoundTripTests(TestCase):
    """A real save/load round trip through views.py's own machinery: a
    set_location() write made during one InkRuntimeState's
    continue_story() call must survive being serialized into
    CurrentGame.state and deserialized into a completely SEPARATE,
    freshly-constructed InkRuntimeState -- proving persistence actually
    works end to end, not just that the in-memory dict looks right
    immediately after the call that wrote it."""

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="occupancy_roundtrip_owner", password="pw")
        EngineAPI.objects.update_or_create(name="character_occupancy", defaults={"display_name": "Character occupancy", "is_enabled": True})
        self.story = Story.objects.create(
            owner=self.owner,
            title="occupancy-roundtrip-story",
            slug="occupancy-roundtrip-story",
            compiled_json=_load("character_occupancy_set_and_get.ink.json"),
            is_engine_trusted=True,
        )
        _opt_in(self.story, "character_occupancy")

    def test_set_location_survives_a_real_save_and_load(self):
        """_new_game_state() runs continue_story() once (which calls
        set_location("traveler", "cellar")), _build_current_game_state()
        persists the resulting engine_state, and a completely fresh
        _load_game_state() call -- given only the persisted dict, no
        reference to the original InkRuntimeState/engine_state objects --
        must resolve where_is("traveler") to the same value via a fresh
        binding closure built from the reloaded data."""
        engine_state: dict = {}
        state = _new_game_state(self.story, engine_state)
        self.assertEqual(state.last_turn_text, "Result: cellar\n")

        saved = _build_current_game_state(state, previous_raw_state=None, transcript=[], engine_state=engine_state)
        # Simulate a real save round trip through JSON (a Django JSONField
        # would do this too) -- proves the persisted shape is genuinely
        # JSON-safe, not just a Python dict that happens to look right.
        reloaded_raw_state = json.loads(json.dumps(saved))

        # A deep copy, matching views.py's own real call sites -- the
        # reloaded engine_state must not be the SAME object as the one
        # continue_story() already wrote into above.
        reloaded_engine_state = copy.deepcopy(reloaded_raw_state.get("engine_state", {}))
        self.assertIsNot(reloaded_engine_state, engine_state)

        reloaded = _load_game_state(self.story, reloaded_raw_state, reloaded_engine_state)
        # _load_game_state() does not call continue_story() again, so
        # querying where_is() directly through its own bindings
        # (rather than re-running the story) proves the reloaded STATE,
        # not a re-executed set_location() call, is what answers.
        where_is = bindings_for(self.story, reloaded_engine_state)["where_is"]
        self.assertEqual(where_is("traveler"), "cellar")
        # And the reload never touched the original session's own dict.
        self.assertEqual(engine_state["character_occupancy"]["locations"]["traveler"], "cellar")
        del reloaded  # constructed only to prove from_dict() itself does not error on the reloaded shape


class UndeclaredLocationIsFatalTests(TestCase):
    """Placing a character somewhere the story never declared stops the game.

    Fatal by design. Every other symptom of a
    wrong location id is silent — `who_is_at()` returns an empty list and
    `is_at()` returns False, both indistinguishable from the character
    legitimately being elsewhere — so a typo does not break a playthrough
    visibly, it quietly removes characters and every scene gated on their
    presence. A stopped game is recoverable; a lying one is not.

    The vocabulary is the location map's own declared set, reaching this
    binding through `EngineAPIDescriptor.also_reads`. No game supplies a
    separate catalog: occupancy depends on the map, so the places a
    character may stand in are the places the map declares.
    """

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="undeclared_location_owner", password="pw")
        EngineAPI.objects.update_or_create(name="character_occupancy", defaults={"display_name": "Character occupancy", "is_enabled": True})
        EngineAPI.objects.update_or_create(name="location_graph", defaults={"display_name": "Location graph", "is_enabled": True})

    def _story_declaring(self, locations, *, slug):
        """Build a trusted story whose MAP declares `locations`.

        The vocabulary comes from the location system, which occupancy
        depends on — not from occupancy's own config.

        Args:
            locations: The location ids the story's map declares.
            slug: A slug unique to the calling test.

        Returns:
            The created Story.
        """
        story = Story.objects.create(
            owner=self.owner,
            title=slug,
            slug=slug,
            compiled_json=_load("character_occupancy_set_and_get.ink.json"),
            is_engine_trusted=True,
        )
        _opt_in(story, "character_occupancy")
        if locations:
            _opt_in(story, "location_graph")
        return story

    def test_a_declared_location_is_accepted(self):
        """The ordinary path still works, so the guard is not simply
        rejecting everything."""
        story = self._story_declaring(["cellar"], slug="undeclared-ok")
        engine_state: dict = {}
        bindings = bindings_for(story, engine_state)
        self.assertEqual(bindings["set_location"]("traveler", "cellar"), 1)
        self.assertEqual(bindings["where_is"]("traveler"), "cellar")

    def test_an_undeclared_location_raises(self):
        """A typo'd id is refused at the write, naming the character and
        the value, rather than silently storing it."""
        story = self._story_declaring(["cellar"], slug="undeclared-raises")
        # A real story ships its map by instantiating the map plugin over
        # its config; the slot it seeds is what occupancy checks against.
        cellar_map = LocationGraph(name="cellar_map", config={"locations": {"cellar": {"known_by_default": True}}})
        engine_state = {location_graph.STATE_KEY: cellar_map.init_state(None)}
        bindings = bindings_for(story, engine_state)
        with self.assertRaises(UnknownLocationError) as caught:
            bindings["set_location"]("traveler", "celler")
        self.assertIn("celler", str(caught.exception))
        self.assertIn("traveler", str(caught.exception))

    def test_clearing_a_location_is_never_refused(self):
        """An empty string clears a character, which is a real answer and
        not a location to validate."""
        story = self._story_declaring(["cellar"], slug="undeclared-clear")
        engine_state: dict = {}
        bindings = bindings_for(story, engine_state)
        bindings["set_location"]("traveler", "cellar")
        self.assertEqual(bindings["set_location"]("traveler", ""), 1)
        self.assertEqual(bindings["where_is"]("traveler"), "")

    def test_a_story_declaring_no_locations_is_not_checked(self):
        """A story tracking its map some other way keeps working.

        `character_occupancy` explicitly supports a game that never
        declares a map, so an empty vocabulary means "not checked", never
        "nothing is valid".
        """
        story = self._story_declaring([], slug="undeclared-permissive")
        bindings = bindings_for(story, {})
        self.assertEqual(bindings["set_location"]("traveler", "anywhere_at_all"), 1)


class RecomputePopulatesTheStoreTests(TestCase):
    """(a) a recompute puts the player AND the scheduled NPCs
    into the occupancy store.

    The store is the live layer every presence question is answered from,
    so "nobody is anywhere" and "the schedules never ran" look identical
    from inside a story. `where_is()` reads that store and nothing
    else, so a schedule only reaches a story once a recompute has written
    its answer in — this asserts that write actually happens.
    """

    def test_the_player_and_the_scheduled_npcs_are_in_the_store(self):
        """A recompute resolves the NPCs and leaves the player untouched."""
        slot = CHARACTER_OCCUPANCY.init_state(None)
        # The player is registered by the story's own arrival, not by a
        # schedule, so a recompute must preserve that entry.
        CHARACTER_OCCUPANCY.place(slot, "player", "foyer")
        schedules = {
            # Always in the cellar: a populated store must contain her.
            "bambi": (ScheduleRule(condition=None, location_id="cellar"),),
            # Deliberately nowhere, to prove the store holds resolved
            # answers rather than one entry per declared character.
            "traveler": (ScheduleRule(condition=None, location_id=None),),
        }
        CHARACTER_OCCUPANCY.recompute(slot, schedules, frozenset(), 0)
        self.assertEqual(CHARACTER_OCCUPANCY.where_is(slot, "player"), "foyer")
        self.assertEqual(CHARACTER_OCCUPANCY.where_is(slot, "bambi"), "cellar")
        self.assertIsNone(CHARACTER_OCCUPANCY.where_is(slot, "traveler", default=None))
        self.assertEqual(slot["locations"].get("bambi"), "cellar")

    def test_characters_at_reports_the_npc_beside_the_player(self):
        """Presence at a location is answered from that same store."""
        slot = CHARACTER_OCCUPANCY.init_state(None)
        CHARACTER_OCCUPANCY.place(slot, "player", "cellar")
        schedules = {"bambi": (ScheduleRule(condition=None, location_id="cellar"),)}
        CHARACTER_OCCUPANCY.recompute(slot, schedules, frozenset(), 0)
        self.assertIn("bambi", CHARACTER_OCCUPANCY.characters_at(slot, "cellar"))
        self.assertIn("player", CHARACTER_OCCUPANCY.characters_at(slot, "cellar"))

    def test_a_recompute_moves_an_npc_when_the_schedule_answer_changes(self):
        """A stale entry is overwritten, not kept alongside the new one."""
        schedules_day = {"bambi": (ScheduleRule(condition=None, location_id="cellar"),)}
        schedules_night = {"bambi": (ScheduleRule(condition=None, location_id="foyer"),)}
        slot = CHARACTER_OCCUPANCY.init_state(None)
        CHARACTER_OCCUPANCY.recompute(slot, schedules_day, frozenset(), 0)
        self.assertEqual(CHARACTER_OCCUPANCY.where_is(slot, "bambi"), "cellar")
        CHARACTER_OCCUPANCY.recompute(slot, schedules_night, frozenset(), 0)
        self.assertEqual(CHARACTER_OCCUPANCY.where_is(slot, "bambi"), "foyer")
        self.assertNotIn("bambi", CHARACTER_OCCUPANCY.characters_at(slot, "cellar"))


class PlayerLocationFollowsTheStoryTests(TestCase):
    """(b) `where_is("player")` changes when the player walks
    from one location knot to another.

    The regression guarded here is Justification #2: presence answered
    from a store that the story had stopped updating, so the player stayed
    registered at the first room they ever entered.
    """

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="player_moves_owner", password="pw")
        EngineAPI.objects.update_or_create(name="character_occupancy", defaults={"display_name": "Character occupancy", "is_enabled": True})

    def test_the_player_moves_between_two_location_knots(self):
        """Driven through the real runtime, not by calling bindings by hand."""
        story = Story.objects.create(
            owner=self.owner,
            title="player-moves",
            slug="player-moves",
            compiled_json=_load("player_moves_between_locations.ink.json"),
            is_engine_trusted=True,
        )
        _opt_in(story, "character_occupancy")
        engine_state: dict = {}
        bindings = bindings_for(story, engine_state)
        state = InkRuntimeState(load_story_root(story.compiled_json), engine_bindings=bindings)

        first = state.continue_story()
        self.assertIn("foyer", first)
        self.assertEqual(bindings["where_is"]("player"), "foyer")

        # Walk to the cellar; the store must follow the player there.
        state.choose(0)
        second = state.continue_story()
        self.assertIn("cellar", second)
        self.assertEqual(bindings["where_is"]("player"), "cellar")
        self.assertEqual(engine_state["character_occupancy"]["locations"]["player"], "cellar")


class ReadingAnotherPluginsSlotNeverInventsItTests(TestCase):
    """(c) redesigned by the `ink_engine` standalone-
    library extraction: the OLD `also_reads`/`_init_state_for` mechanism
    this class used to test (a STRING name, declared separately from any
    real import, that `bindings_for()` would pre-allocate on a reader's
    behalf — the exact shape of a real bug that hid for a whole session,
    a misspelled `also_reads` name silently creating an empty slot no
    `Condition.engine_state` read ever matched) no longer exists at all.

    `character_occupancy._bind()` now reads another plugin's slot with a
    plain `engine_state.get(location_graph.STATE_KEY, {})` — a Python
    constant, imported directly, not a second string that could disagree
    with the real one. That makes the OLD bug class structurally
    impossible to reintroduce via THIS mechanism, and means there is no
    longer a slot to "invent": a plugin the story never opted into simply
    contributes nothing to `engine_state` at all, and a reader sees `{}`.
    """

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="shared_slot_owner", password="pw")
        EngineAPI.objects.update_or_create(name="character_occupancy", defaults={"display_name": "Character occupancy", "is_enabled": True})

    def _story(self, slug):
        story = Story.objects.create(
            owner=self.owner,
            title=slug,
            slug=slug,
            compiled_json=_load("character_occupancy_set_and_get.ink.json"),
            is_engine_trusted=True,
        )
        _opt_in(story, "character_occupancy")
        return story

    def test_a_plugin_the_story_never_opted_into_contributes_no_slot(self):
        """A story that opts into `character_occupancy` alone gets no
        `location_graph` slot at all -- unlike the OLD system, which
        pre-allocated a reader's own `also_reads` slots regardless of
        whether the story ever opted into the owning plugin."""
        engine_state: dict = {}
        bindings_for(self._story("shared-slot-shape"), engine_state)
        self.assertNotIn("location_graph", engine_state)
        # And nothing invented a slot under a misspelled name either --
        # the failure mode this class exists to guard against.
        self.assertNotIn("game_locations", engine_state)

    def test_reading_an_unopted_slot_answers_permissively_not_loudly(self):
        """Per `character_occupancy._bind()`'s own documented contract: a
        story with no map slot at all is simply not checked (see
        UndeclaredLocationIsFatalTests.test_a_story_declaring_no_locations_is_not_checked
        above) -- there is no separate "unowned slot" error path anymore,
        because there is no longer a second name that could name a slot
        nothing owns."""
        bindings = bindings_for(self._story("shared-slot-permissive"), {})
        self.assertEqual(bindings["set_location"]("traveler", "anywhere_at_all"), 1)

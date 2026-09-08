"""claude_docs/plans/external_expansion_IF_engine.md Step 6: the two
independent LocationSystem layers (interactive_fiction.engine_plugins.
location_graph, interactive_fiction.engine_plugins.character_occupancy).

Pure-function coverage — no DB needed. SimpleTestCase throughout.
"""

from __future__ import annotations

import json

from django.test import SimpleTestCase

import interactive_fiction.engine_plugins.character_occupancy as character_occupancy_module
import interactive_fiction.engine_plugins.location_graph as location_graph_module
from interactive_fiction.engine_plugins.character_occupancy import (
    Condition,
    OccupancyState,
    ScheduleRule,
    is_anywhere,
    is_at,
    is_with,
    recompute_occupancy,
    resolve_present_characters,
    resolve_schedule,
    set_location,
    where_is,
    who_is_at,
)
from interactive_fiction.engine_plugins.location_graph import (
    LocationGraphState,
    detail,
    has_visited,
    initial_state,
    is_known,
    mark_known,
    mark_unknown,
    movement_cost,
    reachable_edges,
    record_visit,
    set_all_known,
    visit_count,
)
from interactive_fiction.engine_plugins.scheduling import (
    EIGHT_AM,
    EIGHT_PM,
    MINUTES_PER_DAY,
    NOON,
    SIX_AM,
    SIX_PM,
)

_LOCATION_CONFIG = {
    "locations": {
        "outside_hospital": {
            "known_by_default": True,
            "edges": [{"to": "hospital_foyer"}],
        },
        "hospital_foyer": {
            "known_by_default": False,
            "edges": [{"to": "sacred_clearing", "requires_known": True}],
        },
        "sacred_clearing": {
            "known_by_default": False,
            "edges": [],
        },
    },
}


class LocationGraphInitialStateTests(SimpleTestCase):
    """initial_state() seeds every known_by_default location, and nothing
    else."""

    def test_only_known_by_default_locations_start_known(self):
        """Locations with known_by_default omitted or false start unknown."""
        state = initial_state(_LOCATION_CONFIG)
        self.assertTrue(is_known(state, "outside_hospital"))
        self.assertFalse(is_known(state, "hospital_foyer"))
        self.assertFalse(is_known(state, "sacred_clearing"))


class MarkKnownTests(SimpleTestCase):
    """mark_known() is a real, non-mutating state transition."""

    def test_marks_a_location_known_without_mutating_the_original(self):
        """mark_known() returns a new state; the original is untouched."""
        state = initial_state(_LOCATION_CONFIG)
        new_state = mark_known(state, "hospital_foyer")
        self.assertTrue(is_known(new_state, "hospital_foyer"))
        self.assertFalse(is_known(state, "hospital_foyer"))


class MarkUnknownTests(SimpleTestCase):
    """mark_unknown() is the real inverse of mark_known()."""

    def test_mark_unknown_removes_a_known_location_without_mutating(self):
        """mark_unknown() returns a new state; the original is untouched."""
        state = mark_known(initial_state(_LOCATION_CONFIG), "hospital_foyer")
        new_state = mark_unknown(state, "hospital_foyer")
        self.assertFalse(is_known(new_state, "hospital_foyer"))
        self.assertTrue(is_known(state, "hospital_foyer"))

    def test_mark_unknown_can_revoke_a_known_by_default_location(self):
        """A known_by_default location is not privileged — a story that
        takes a place away can take that one away too."""
        state = mark_unknown(initial_state(_LOCATION_CONFIG), "outside_hospital")
        self.assertFalse(is_known(state, "outside_hospital"))

    def test_mark_unknown_on_an_unknown_location_is_a_no_op(self):
        """Revoking a location that was never known is not an error."""
        state = initial_state(_LOCATION_CONFIG)
        self.assertFalse(is_known(mark_unknown(state, "sacred_clearing"), "sacred_clearing"))


class SetAllKnownTests(SimpleTestCase):
    """set_all_known() is the whole-map operation."""

    def test_true_marks_every_declared_location_known(self):
        """Every location in config becomes known, including ones that
        default to unknown."""
        state = set_all_known(_LOCATION_CONFIG, True)
        for location_id in _LOCATION_CONFIG["locations"]:
            self.assertTrue(is_known(state, location_id), location_id)

    def test_false_clears_every_location_including_known_by_default(self):
        """False is 'forget everything', not 'reset to a new game' — a
        known_by_default location is cleared too, which is exactly what
        distinguishes it from initial_state()."""
        state = set_all_known(_LOCATION_CONFIG, False)
        self.assertEqual(state.known, set())
        self.assertTrue(is_known(initial_state(_LOCATION_CONFIG), "outside_hospital"))

    def test_result_round_trips_through_serialization(self):
        """The whole-map state serializes like any other state."""
        state = set_all_known(_LOCATION_CONFIG, True)
        self.assertEqual(LocationGraphState.from_dict(state.to_dict()).known, state.known)


class ReachableEdgesTests(SimpleTestCase):
    """reachable_edges() applies the real requires_known gating."""

    def test_edge_with_no_requires_known_is_always_reachable(self):
        """Per the corrected default (2026-08-22): an edge with no
        requires_known key doesn't need its destination already known —
        walking there is often how it BECOMES known."""
        state = initial_state(_LOCATION_CONFIG)
        self.assertEqual(reachable_edges(_LOCATION_CONFIG, state, "outside_hospital"), ["hospital_foyer"])

    def test_requires_known_edge_is_hidden_until_the_destination_is_known(self):
        """An edge with requires_known: true is excluded while its
        destination is still unknown."""
        state = initial_state(_LOCATION_CONFIG)
        self.assertEqual(reachable_edges(_LOCATION_CONFIG, state, "hospital_foyer"), [])

    def test_requires_known_edge_appears_once_the_destination_is_known(self):
        """The same edge appears once its destination becomes known."""
        state = initial_state(_LOCATION_CONFIG)
        state = mark_known(state, "sacred_clearing")
        self.assertEqual(reachable_edges(_LOCATION_CONFIG, state, "hospital_foyer"), ["sacred_clearing"])

    def test_undeclared_location_has_no_edges(self):
        """A location id absent from config's own "locations" has no
        edges, rather than raising."""
        state = initial_state(_LOCATION_CONFIG)
        self.assertEqual(reachable_edges(_LOCATION_CONFIG, state, "nonexistent"), [])


class LocationGraphSerializationTests(SimpleTestCase):
    """LocationGraphState round-trips through plain JSON."""

    def test_round_trips_through_real_json(self):
        """A real json.dumps/json.loads round-trip preserves every known
        location."""
        state = initial_state(_LOCATION_CONFIG)
        state = mark_known(state, "hospital_foyer")
        round_tripped = json.loads(json.dumps(state.to_dict()))
        restored = LocationGraphState.from_dict(round_tripped)
        self.assertTrue(is_known(restored, "hospital_foyer"))
        self.assertTrue(is_known(restored, "outside_hospital"))
        self.assertFalse(is_known(restored, "sacred_clearing"))


class ResolveScheduleTests(SimpleTestCase):
    """resolve_schedule() against real _place_now() shapes, per
    a converted game's own globals file."""

    def test_zali_style_single_flag_fixed_place(self):
        """Real shape: `{ zali_met: ~ return 220 } ~ return 0` — one flag
        gates one fixed place, else absent."""
        rules = (
            ScheduleRule(condition=Condition.flag_is_set("zali_met"), location_id="zali_house"),
            ScheduleRule(condition=None, location_id=None),
        )
        self.assertIsNone(resolve_schedule(rules, flags=frozenset(), clock=0))
        self.assertEqual(resolve_schedule(rules, flags=frozenset({"zali_met"}), clock=0), "zali_house")

    def test_nina_style_shop_hours_split(self):
        """Real shape: `{ is_shop_open_now(): ~ return 371 } ~ return 462`
        — a time-of-day range gates the primary place, else a fixed
        fallback. Shop hours per source's own isShopOpen(): tick 96-216,
        i.e. 8:00am-6:00pm."""
        rules = (
            ScheduleRule(condition=Condition.minute_in_range(EIGHT_AM, SIX_PM), location_id="tv_station_reception"),
            ScheduleRule(condition=None, location_id="ninas_apartment"),
        )
        self.assertEqual(resolve_schedule(rules, flags=frozenset(), clock=100), "tv_station_reception")
        self.assertEqual(resolve_schedule(rules, flags=frozenset(), clock=250), "ninas_apartment")

    def test_doctor_kay_style_multi_condition_priority_chain(self):
        """Real shape: school-hours-afternoon -> school; school-hours ->
        hospital; not-day AND (deal-made OR charmed) -> hotel; else
        absent. First matching rule wins, in declared order."""
        rules = (
            ScheduleRule(
                condition=Condition.all_of(Condition.minute_in_range(EIGHT_AM, SIX_PM), Condition.minute_in_range(NOON, MINUTES_PER_DAY)),
                location_id="school_nurse_office",
            ),
            ScheduleRule(condition=Condition.minute_in_range(EIGHT_AM, SIX_PM), location_id="hospital_office"),
            ScheduleRule(
                condition=Condition.all_of(
                    Condition.negate(Condition.minute_in_range(SIX_AM, EIGHT_PM)),
                    Condition.any_of(Condition.flag_is_set("deal_made"), Condition.flag_is_set("charmed")),
                ),
                location_id="hotel_room",
            ),
            ScheduleRule(condition=None, location_id=None),
        )
        # Afternoon school hours (tick 150, in both ranges) -> school.
        self.assertEqual(resolve_schedule(rules, flags=frozenset(), clock=150), "school_nurse_office")
        # Morning school hours (tick 100, only in the first range) -> hospital.
        self.assertEqual(resolve_schedule(rules, flags=frozenset(), clock=100), "hospital_office")
        # Night, charmed -> hotel.
        self.assertEqual(resolve_schedule(rules, flags=frozenset({"charmed"}), clock=0), "hotel_room")
        # Night, not charmed/deal-made -> absent.
        self.assertIsNone(resolve_schedule(rules, flags=frozenset(), clock=0))

    def test_empty_schedule_with_no_fallback_resolves_to_none(self):
        """No rules at all resolves to None, matching source's own
        "not trackable" convention for a character with no real
        whereNow() override."""
        self.assertIsNone(resolve_schedule((), flags=frozenset(), clock=0))

    def test_resolve_schedule_reduces_absolute_clock_to_minute_of_day_itself(self):
        """The caller passes a raw absolute clock value (matching
        SchedulingState.clock) with zero coupling to that module —
        resolve_schedule() does the tick-to-minute reduction itself."""
        rules = (ScheduleRule(condition=Condition.minute_in_range(EIGHT_AM, SIX_PM), location_id="daytime_spot"),)
        # Day 5 (5 * 288 = 1440), tick-of-day 100 -> same result as day 0.
        self.assertEqual(resolve_schedule(rules, flags=frozenset(), clock=1440 + 100), "daytime_spot")


class ResolvePresentCharactersTests(SimpleTestCase):
    """resolve_present_characters() — the schedule-driven inverse of
    resolve_schedule(): given a place, who's there right now, across
    several characters at once. Synthetic character/place names
    throughout (per the location-dispatch design work's
    own generic-vs-bridge rule) — nothing here is game-specific."""

    def test_returns_every_character_currently_resolved_to_the_place(self):
        """Two characters both resolve to the same place; a third does
        not — only the first two are returned, in schedules' own order."""
        schedules = {
            "alice": (ScheduleRule(condition=None, location_id="the_square"),),
            "bob": (ScheduleRule(condition=None, location_id="the_square"),),
            "carol": (ScheduleRule(condition=None, location_id="elsewhere"),),
        }
        self.assertEqual(
            resolve_present_characters("the_square", schedules, flags=frozenset(), clock=0),
            ["alice", "bob"],
        )

    def test_nobody_present_returns_an_empty_list(self):
        """No character's schedule resolves to this place -> empty list,
        not None (unlike resolve_schedule() itself, this always returns a
        list since it's answering "who," not "where")."""
        schedules = {"alice": (ScheduleRule(condition=None, location_id="elsewhere"),)}
        self.assertEqual(resolve_present_characters("the_square", schedules, flags=frozenset(), clock=0), [])

    def test_empty_schedules_dict_returns_an_empty_list(self):
        """No characters at all -> empty list."""
        self.assertEqual(resolve_present_characters("the_square", {}, flags=frozenset(), clock=0), [])

    def test_respects_each_characters_own_flag_and_clock_gated_schedule(self):
        """Each character's own real Condition tree is evaluated
        independently against the SAME shared flags/clock — a
        time-of-day split for one character doesn't affect another's own
        unconditional rule."""
        schedules = {
            "alice": (
                ScheduleRule(condition=Condition.minute_in_range(EIGHT_AM, SIX_PM), location_id="the_square"),
                ScheduleRule(condition=None, location_id="home"),
            ),
            "bob": (ScheduleRule(condition=Condition.flag_is_set("bob_out"), location_id="the_square"),),
        }
        # Daytime, bob_out not set: only alice is at the square.
        self.assertEqual(resolve_present_characters("the_square", schedules, flags=frozenset(), clock=100), ["alice"])
        # Night, bob_out set: only bob is at the square (alice is home).
        self.assertEqual(
            resolve_present_characters("the_square", schedules, flags=frozenset({"bob_out"}), clock=0),
            ["bob"],
        )

    def test_delegates_to_story_rules_and_story_values_per_character(self):
        """A character's own STORY_RULE/STORY_VALUE nodes resolve through
        the same shared registries every other resolve_schedule() caller
        uses — no separate registry concept for the multi-character case."""
        schedules = {
            "alice": (ScheduleRule(condition=Condition.story_rule("shop_is_open"), location_id="the_shop"),),
            "bob": (ScheduleRule(condition=Condition.story_value("hour", ">", 12), location_id="the_shop"),),
        }
        story_rules = {"shop_is_open": lambda clock: clock == 999}
        story_values = {"hour": lambda clock: 13 if clock == 999 else 0}
        self.assertEqual(
            resolve_present_characters("the_shop", schedules, flags=frozenset(), clock=999, story_rules=story_rules, story_values=story_values),
            ["alice", "bob"],
        )
        self.assertEqual(
            resolve_present_characters("the_shop", schedules, flags=frozenset(), clock=0, story_rules=story_rules, story_values=story_values),
            [],
        )


class EngineStateConditionTests(SimpleTestCase):
    """ENGINE_STATE lets a schedule read a fact from the plugin that owns
    it, instead of the story reading it out, passing its NAME in as a
    flag, and the schedule testing membership."""

    STATE = {"characters": {"attributes": {"alice": {"deal_made": True, "stage": 3}}, "known": ["alice"]}}

    def _resolve(self, condition, engine_state=None):
        """Resolve a one-rule schedule under `condition`."""
        return resolve_schedule(
            (ScheduleRule(condition=condition, location_id="the_shop"), ScheduleRule(condition=None, location_id="home")),
            flags=frozenset(),
            clock=0,
            engine_state=engine_state if engine_state is not None else self.STATE,
        )

    def test_a_true_attribute_selects_its_branch(self):
        """The base case: the schedule reads the characters plugin
        directly, with nothing threaded through the flag set."""
        self.assertEqual(self._resolve(Condition.engine_state("characters", ("attributes", "alice", "deal_made"))), "the_shop")

    def test_a_missing_path_is_false_rather_than_an_error(self):
        """Story content asks about facts that have not happened yet; a
        character with no attributes must answer no, not crash mid-turn."""
        self.assertEqual(self._resolve(Condition.engine_state("characters", ("attributes", "bob", "deal_made"))), "home")
        self.assertEqual(self._resolve(Condition.engine_state("characters", ("attributes", "alice", "never_set"))), "home")

    def test_an_absent_state_slot_is_false_rather_than_an_error(self):
        """A story that has not opted into the owning plugin at all."""
        self.assertEqual(self._resolve(Condition.engine_state("nonexistent", ("a", "b")), engine_state={}), "home")

    def test_a_non_mapping_partway_down_the_path_is_false(self):
        """Walking into a scalar must stop, not raise."""
        self.assertEqual(self._resolve(Condition.engine_state("characters", ("attributes", "alice", "deal_made", "deeper"))), "home")

    def test_it_compares_values_not_just_truthiness(self):
        """The same node handles "stage is at least 3", which is what
        replaces a story pre-computing that into a boolean flag."""
        self.assertEqual(self._resolve(Condition.engine_state("characters", ("attributes", "alice", "stage"), ">=", 3)), "the_shop")
        self.assertEqual(self._resolve(Condition.engine_state("characters", ("attributes", "alice", "stage"), ">=", 4)), "home")

    def test_known_state_is_readable_through_the_same_kind(self):
        """No `CHARACTER_KNOWN` kind is needed: known-state is a list in
        the same slot, so one generic kind reaches it."""
        state = {"characters": {"attributes": {}, "known": ["alice"]}}
        self.assertEqual(self._resolve(Condition.engine_state("characters", ("known",), "contains", "alice"), state), "the_shop")

    def test_an_absent_value_compares_as_its_zero_not_as_nothing(self):
        """A fact that has not happened must equal its zero value.

        `charm_level == 0` means "uncharmed", and that has to hold for a
        character nobody ever charmed — whose attribute was never written.
        Treating an unresolved path as None instead made every such
        condition false, which silently inverted schedules that gate on a
        zero state. Caught by a real ASFA schedule (Ash's) rather than by
        this test, which now pins it."""
        self.assertEqual(self._resolve(Condition.engine_state("characters", ("records", "nobody", "attributes", "charm_level"), "==", 0), {}), "the_shop")

    def test_the_absent_value_is_configurable(self):
        """Where absence genuinely differs from a stored value, a caller
        can say what missing is worth."""
        condition = Condition.engine_state("characters", ("records", "nobody", "attributes", "stage"), "==", -1, missing=-1)
        self.assertEqual(self._resolve(condition, {}), "the_shop")

    def test_an_unsupported_operator_is_rejected_at_build_time(self):
        """A bad operator must fail where it is written, not silently
        mis-answer inside a player's turn."""
        with self.assertRaises(ValueError):
            Condition.engine_state("characters", ("attributes", "alice", "x"), "~=", 1)

    def test_it_composes_with_the_other_kinds(self):
        """ENGINE_STATE is an ordinary node: combinators must accept it."""
        condition = Condition.all_of(
            Condition.engine_state("characters", ("attributes", "alice", "deal_made")),
            Condition.negate(Condition.flag_is_set("blocked")),
        )
        self.assertEqual(self._resolve(condition), "the_shop")

    def test_a_schedule_with_no_engine_state_nodes_needs_no_state(self):
        """Backward compatibility: every existing schedule keeps working
        without passing anything."""
        rules = (ScheduleRule(condition=Condition.flag_is_set("open"), location_id="the_shop"),)
        self.assertEqual(resolve_schedule(rules, flags=frozenset({"open"}), clock=0), "the_shop")


class PresenceQueryTests(SimpleTestCase):
    """`is_at()`, `is_with()` and `is_anywhere()` — the three distinct
    presence questions, kept apart on purpose.

    A story that conflates "is X at this place" with "is X anywhere at
    all" reports characters as present across the whole map, so these
    tests pin the difference rather than just the happy path."""

    def setUp(self):
        self.state = OccupancyState(locations={"alice": "the_square", "player": "the_square", "bob": "the_shop"})

    def test_is_at_is_true_only_at_that_location(self):
        """The place-specific question."""
        self.assertTrue(is_at(self.state, "alice", "the_square"))
        self.assertFalse(is_at(self.state, "alice", "the_shop"))

    def test_is_at_is_false_for_an_unplaced_character(self):
        """Nowhere is not "at" anywhere — including not at ""."""
        self.assertFalse(is_at(self.state, "carol", "the_square"))
        self.assertFalse(is_at(self.state, "carol", ""))

    def test_is_anywhere_ignores_which_location(self):
        """The existence question: true wherever they are."""
        self.assertTrue(is_anywhere(self.state, "bob"))
        self.assertFalse(is_anywhere(self.state, "carol"))

    def test_is_anywhere_is_not_a_substitute_for_is_at(self):
        """The distinction that matters: Bob is somewhere, but not where
        Alice is. Using `is_anywhere` for presence would call him here."""
        self.assertTrue(is_anywhere(self.state, "bob"))
        self.assertFalse(is_at(self.state, "bob", "the_square"))

    def test_is_with_compares_two_characters_locations(self):
        """"Is X here", where here means wherever the player is."""
        self.assertTrue(is_with(self.state, "alice", "player"))
        self.assertFalse(is_with(self.state, "bob", "player"))

    def test_is_with_is_false_when_either_is_unplaced(self):
        """Two absent characters are not together; they are both nowhere."""
        self.assertFalse(is_with(self.state, "carol", "player"))
        self.assertFalse(is_with(OccupancyState(locations={"alice": "the_square"}), "alice", "player"))
        self.assertFalse(is_with(OccupancyState(), "carol", "dave"))

    def test_is_with_agrees_with_is_at_on_the_players_own_location(self):
        """The two spellings of the same question must not diverge."""
        for character_id in ("alice", "bob", "carol"):
            self.assertEqual(
                is_with(self.state, character_id, "player"),
                is_at(self.state, character_id, where_is(self.state, "player") or ""),
                character_id,
            )


class RecomputeOccupancyTests(SimpleTestCase):
    """recompute_occupancy() is the scheduler's write-back: it resolves
    every scheduled character and pushes the answers into the store, so
    later where_is()/who_is_at() reads see one consistent moment."""

    def test_every_scheduled_character_is_written_into_the_store(self):
        """The point of the write-back — after one recompute, a plain
        store read answers for a character who was never explicitly
        placed."""
        schedules = {
            "alice": (ScheduleRule(condition=None, location_id="the_square"),),
            "bob": (ScheduleRule(condition=None, location_id="the_shop"),),
        }
        updated = recompute_occupancy(OccupancyState(), schedules, flags=frozenset(), clock=0)
        self.assertEqual(where_is(updated, "alice"), "the_square")
        self.assertEqual(where_is(updated, "bob"), "the_shop")
        self.assertEqual(who_is_at(updated, "the_square"), ["alice"])

    def test_a_none_resolution_clears_the_previous_entry(self):
        """ "Nowhere" is an answer, not a reason to leave yesterday's
        location behind — the stale-entry bug this write-back exists to
        prevent."""
        schedules = {
            "alice": (
                ScheduleRule(condition=Condition.flag_is_set("alice_out"), location_id="the_square"),
                ScheduleRule(condition=None, location_id=None),
            )
        }
        placed = recompute_occupancy(OccupancyState(), schedules, flags=frozenset({"alice_out"}), clock=0)
        self.assertEqual(where_is(placed, "alice"), "the_square")
        cleared = recompute_occupancy(placed, schedules, flags=frozenset(), clock=0)
        self.assertIsNone(where_is(cleared, "alice"))

    def test_an_unchanged_location_stays_put(self):
        """Recomputing repeatedly is safe — a character whose schedule
        still resolves the same way keeps the same entry, so a story may
        recompute as often as it likes."""
        schedules = {"alice": (ScheduleRule(condition=None, location_id="the_square"),)}
        first = recompute_occupancy(OccupancyState(), schedules, flags=frozenset(), clock=0)
        second = recompute_occupancy(first, schedules, flags=frozenset(), clock=1)
        self.assertEqual(second.locations, {"alice": "the_square"})

    def test_characters_outside_the_schedules_are_left_untouched(self):
        """Explicitly-placed characters — the player above all — are not
        in any schedule table and must survive a recompute."""
        state = set_location(OccupancyState(), "player", "the_square")
        schedules = {"alice": (ScheduleRule(condition=None, location_id="the_shop"),)}
        updated = recompute_occupancy(state, schedules, flags=frozenset(), clock=0)
        self.assertEqual(where_is(updated, "player"), "the_square")

    def test_the_caller_s_state_is_never_mutated(self):
        """Same pure in/out contract as set_location() — callers hold a
        previous state safely."""
        state = OccupancyState()
        schedules = {"alice": (ScheduleRule(condition=None, location_id="the_square"),)}
        recompute_occupancy(state, schedules, flags=frozenset(), clock=0)
        self.assertEqual(state.locations, {})

    def test_flags_clock_and_registries_reach_every_character(self):
        """The resolution inputs are shared across the whole pass, exactly
        as resolve_present_characters() shares them."""
        schedules = {
            "alice": (
                ScheduleRule(condition=Condition.minute_in_range(EIGHT_AM, SIX_PM), location_id="the_square"),
                ScheduleRule(condition=None, location_id="home"),
            ),
            "bob": (
                ScheduleRule(condition=Condition.story_rule("shop_is_open"), location_id="the_shop"),
                ScheduleRule(condition=None, location_id="home"),
            ),
        }
        story_rules = {"shop_is_open": lambda clock: True}
        daytime = recompute_occupancy(OccupancyState(), schedules, flags=frozenset(), clock=NOON // 5, story_rules=story_rules)
        self.assertEqual(daytime.locations, {"alice": "the_square", "bob": "the_shop"})


class OccupancyStateTests(SimpleTestCase):
    """set_location()/where_is()/who_is_at() are pure, non-mutating
    functions over a plain dict of explicit character locations."""

    def test_set_location_then_where_is(self):
        """A character's explicitly-set location is readable back."""
        state = OccupancyState()
        state = set_location(state, "davy", "robbins_house")
        self.assertEqual(where_is(state, "davy"), "robbins_house")

    def test_set_location_does_not_mutate_the_original_state(self):
        """set_location() returns a new state; the original is untouched."""
        state = OccupancyState()
        set_location(state, "davy", "robbins_house")
        self.assertIsNone(where_is(state, "davy"))

    def test_clearing_a_location_with_none_removes_it(self):
        """Passing location_id=None removes the character's entry entirely."""
        state = OccupancyState()
        state = set_location(state, "davy", "robbins_house")
        state = set_location(state, "davy", None)
        self.assertIsNone(where_is(state, "davy"))

    def test_unset_character_has_no_location(self):
        """A character never explicitly placed anywhere has no location."""
        state = OccupancyState()
        self.assertIsNone(where_is(state, "nobody"))

    def test_who_is_at_returns_every_character_at_a_location(self):
        """who_is_at() lists every character explicitly placed at a given
        location, excluding characters placed elsewhere."""
        state = OccupancyState()
        state = set_location(state, "davy", "robbins_house")
        state = set_location(state, "mrs_robbins", "robbins_house")
        state = set_location(state, "tina", "elsewhere")
        self.assertEqual(who_is_at(state, "robbins_house"), ["davy", "mrs_robbins"])

    def test_occupancy_state_round_trips_through_real_json(self):
        """A real json.dumps/json.loads round-trip preserves every
        explicitly-set character location."""
        state = OccupancyState()
        state = set_location(state, "davy", "robbins_house")
        round_tripped = json.loads(json.dumps(state.to_dict()))
        restored = OccupancyState.from_dict(round_tripped)
        self.assertEqual(where_is(restored, "davy"), "robbins_house")


class LayeredIndependenceTests(SimpleTestCase):
    """The explicit 2026-08-22 layering requirement: location_graph and
    character_occupancy must be usable completely independently."""

    def test_character_occupancy_never_imports_location_graph(self):
        """A structural proof, not just a docstring claim: the occupancy
        module's own namespace holds no reference to the location_graph
        module."""
        self.assertNotIn(location_graph_module, character_occupancy_module.__dict__.values())

    def test_occupancy_functions_accept_plain_strings_never_a_location_graph_type(self):
        """A story tracking locations with its own scheme (not
        location_graph.py's config shape at all) can still use occupancy
        tracking — location ids are plain strings here, nothing about
        them is a location_graph.LocationGraphState or requires one to
        exist."""
        state = OccupancyState()
        state = set_location(state, "some_npc", "a-location-id-from-any-scheme-at-all")
        self.assertEqual(where_is(state, "some_npc"), "a-location-id-from-any-scheme-at-all")


class LocationDetailsTests(SimpleTestCase):
    """Declared details reach the session, and survive a round-trip."""

    CONFIG = {
        "locations": {
            "cellar": {"known_by_default": True, "details": {"name": "The Cellar", "terrain": "indoor", "external_identifier": [12]}},
            "moor": {"details": {"terrain": "hills", "story_scene": "storm"}},
            "void": {},
        }
    }

    def test_details_are_carried_into_the_session_state(self):
        """A dependent system reads one place for everything about a
        location, rather than a structure per consumer."""
        state = initial_state(self.CONFIG)
        self.assertEqual(detail(state, "cellar", "name"), "The Cellar")
        self.assertEqual(detail(state, "cellar", "external_identifier"), [12])
        self.assertEqual(detail(state, "moor", "story_scene"), "storm", "a story's own key is kept as declared")
        self.assertIsNone(detail(state, "void", "terrain"), "a location declaring nothing has no details")

    def test_movement_cost_comes_from_terrain(self):
        """Terrain fixes what arriving costs, so a story does not need a
        second table to answer it."""
        state = initial_state(self.CONFIG)
        self.assertEqual(movement_cost(state, "cellar"), 1)
        self.assertEqual(movement_cost(state, "moor"), 4)
        self.assertEqual(movement_cost(state, "void"), 1, "no terrain declared falls back to the default")

    def test_details_survive_a_serialization_round_trip(self):
        """They live in the session's own state, so they must round-trip
        like everything else in it."""
        state = LocationGraphState.from_dict(initial_state(self.CONFIG).to_dict())
        self.assertEqual(detail(state, "cellar", "name"), "The Cellar")
        self.assertEqual(movement_cost(state, "moor"), 4)

    def test_discovery_changes_keep_the_details(self):
        """`mark_known`/`mark_unknown` rebuild the state, so they must
        carry every field — dropping one is exactly how `declared` was
        lost when it was first added."""
        state = mark_unknown(mark_known(initial_state(self.CONFIG), "moor"), "cellar")
        self.assertEqual(detail(state, "cellar", "name"), "The Cellar")
        self.assertEqual(state.declared, {"cellar", "moor", "void"})


class LocationVisitTests(SimpleTestCase):
    """Visits are counted; "has been here" is derived from the count."""

    CONFIG = {"locations": {"cellar": {"known_by_default": True}}}

    def test_a_new_game_has_visited_nothing(self):
        """Absent means zero, so a new session declares no visits."""
        state = initial_state(self.CONFIG)
        self.assertEqual(visit_count(state, "cellar"), 0)
        self.assertFalse(has_visited(state, "cellar"))

    def test_visits_accumulate_and_the_boolean_follows(self):
        """The count is the stored fact and the flag is derived from it,
        so the two can never disagree — a boolean alone could not answer
        "how many times", while a count answers both questions."""
        state = record_visit(record_visit(initial_state(self.CONFIG), "cellar"), "cellar")
        self.assertEqual(visit_count(state, "cellar"), 2)
        self.assertTrue(has_visited(state, "cellar"))

    def test_a_story_may_declare_starting_visits(self):
        """A story resuming mid-narrative can say a place is already
        known to the character."""
        state = initial_state({"locations": {"cellar": {"details": {"visits": 3}}}})
        self.assertEqual(visit_count(state, "cellar"), 3)
        self.assertTrue(has_visited(state, "cellar"))

    def test_visits_survive_a_round_trip(self):
        """Counted visits are session state and must persist."""
        state = LocationGraphState.from_dict(record_visit(initial_state(self.CONFIG), "cellar").to_dict())
        self.assertEqual(visit_count(state, "cellar"), 1)

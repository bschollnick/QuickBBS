"""claude_docs/plans/external_expansion_IF_engine.md Step 5:
SchedulingSystem (interactive_fiction.engine_plugins.scheduling).

Pure-function coverage — no DB needed. SimpleTestCase throughout.
"""

from __future__ import annotations

import json

from django.test import SimpleTestCase

from interactive_fiction.engine_plugins.scheduling import (
    ONE_DAY,
    ONE_HOUR,
    DayPhaseBoundaries,
    Effect,
    EffectKind,
    SchedulingState,
    advance,
    day_of_week,
    hour_of_day,
    is_afternoon,
    is_day,
    is_evening,
    is_morning,
    is_night,
    is_weekday,
    jump_clock,
    minute_of_day,
    schedule_effect,
)


class ScheduleEffectTests(SimpleTestCase):
    """schedule_effect() queues a real, immutable-update timed event."""

    def test_queues_effect_at_the_right_due_time(self):
        """due_time is the current clock plus minutes_from_now, not an
        absolute time the caller must compute itself."""
        state = SchedulingState(clock=100)
        effect = Effect(kind=EffectKind.SET_PERSON_FLAG, target="brenda", payload={"flag": "brenda_flag1", "value": True})
        new_state = schedule_effect(state, effect, minutes_from_now=288)
        self.assertEqual(len(new_state.pending), 1)
        self.assertEqual(new_state.pending[0].due_time, 388)
        self.assertEqual(new_state.pending[0].effect, effect)

    def test_does_not_mutate_the_original_state(self):
        """Per the module's own stateless discipline — schedule_effect()
        returns a NEW SchedulingState rather than mutating the one it was
        given, matching every other function in this module."""
        state = SchedulingState(clock=0)
        schedule_effect(state, Effect(EffectKind.MOVE_CHARACTER, "davy", {"place_id": "robbins_house"}), 10)
        self.assertEqual(state.pending, [])


class AdvanceTests(SimpleTestCase):
    """advance() fires exactly the effects that are due, and only reports
    them — it never applies anything to any character/flag/place state
    itself (the explicit 2026-08-22 design decision)."""

    def test_advancing_past_the_due_time_fires_the_effect(self):
        """Advancing exactly to (or past) an effect's due_time fires it
        and removes it from the returned state's pending list."""
        state = SchedulingState(clock=0)
        state = schedule_effect(state, Effect(EffectKind.MOVE_CHARACTER, "davy", {"place_id": "robbins_house"}), 10)
        new_state, fired = advance(state, minutes=10)
        self.assertEqual(new_state.clock, 10)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0].target, "davy")
        self.assertEqual(new_state.pending, [])

    def test_advancing_short_of_the_due_time_fires_nothing(self):
        """Advancing less than an effect's due_time leaves it queued and
        fires nothing."""
        state = SchedulingState(clock=0)
        state = schedule_effect(state, Effect(EffectKind.SET_PLACE_FLAG, "hidden_room", {"flag": "known", "value": True}), 100)
        new_state, fired = advance(state, minutes=50)
        self.assertEqual(new_state.clock, 50)
        self.assertEqual(fired, [])
        self.assertEqual(len(new_state.pending), 1)

    def test_multiple_due_effects_fire_in_scheduled_order(self):
        """Mirrors source's own vTimedEvent array semantics — events are
        checked/fired in the order they were queued, matching
        checkTimedEvents()'s own forward iteration."""
        state = SchedulingState(clock=0)
        first = Effect(EffectKind.SET_PERSON_FLAG, "a", {"flag": "x", "value": True})
        second = Effect(EffectKind.SET_PERSON_FLAG, "b", {"flag": "y", "value": True})
        state = schedule_effect(state, first, 5)
        state = schedule_effect(state, second, 5)
        _new_state, fired = advance(state, minutes=5)
        self.assertEqual(fired, [first, second])

    def test_advance_never_applies_an_effect_only_reports_it(self):
        """The explicit design decision: advance() has zero side effects
        on anything outside its own returned SchedulingState — it does
        not, and structurally cannot, reach into any character/flag/place
        state, since it's never given any such state to reach into. This
        test exists to make that boundary explicit rather than implicit:
        the ONLY thing advance() ever produces is the tuple it returns."""
        state = SchedulingState(clock=0)
        state = schedule_effect(state, Effect(EffectKind.SET_PERSON_FLAG, "brenda", {"flag": "brenda_flag1", "value": True}), 10)
        new_state, fired = advance(state, minutes=10)
        # The only real assertion possible here: the fired Effect is pure
        # data the CALLER must still act on -- nothing about "brenda" or
        # "brenda_flag1" exists anywhere except inside that returned value.
        self.assertIsInstance(fired[0], Effect)
        self.assertEqual(fired[0].payload, {"flag": "brenda_flag1", "value": True})
        self.assertEqual(new_state.pending, [])

    def test_an_effect_not_yet_due_survives_multiple_advances(self):
        """A single pending effect stays queued across several small
        advances, then fires exactly once the cumulative clock reaches
        its due_time."""
        state = SchedulingState(clock=0)
        state = schedule_effect(state, Effect(EffectKind.MOVE_CHARACTER, "kate", {"place_id": "hotel_bar"}), 20)
        state, fired_1 = advance(state, minutes=5)
        state, fired_2 = advance(state, minutes=5)
        self.assertEqual(fired_1, [])
        self.assertEqual(fired_2, [])
        self.assertEqual(state.clock, 10)
        self.assertEqual(len(state.pending), 1)
        state, fired_3 = advance(state, minutes=10)
        self.assertEqual(state.clock, 20)
        self.assertEqual(len(fired_3), 1)


class SchedulingStateSerializationTests(SimpleTestCase):
    """to_dict()/from_dict() round-trip cleanly through plain JSON-safe
    values, matching InkRuntimeState's own established convention for
    storing per-session state."""

    def test_round_trips_an_empty_state(self):
        """A state with no pending effects round-trips its clock value
        correctly."""
        state = SchedulingState(clock=42)
        restored = SchedulingState.from_dict(state.to_dict())
        self.assertEqual(restored.clock, 42)
        self.assertEqual(restored.pending, [])

    def test_round_trips_pending_effects(self):
        """A queued but not-yet-fired effect round-trips its full shape
        (due_time, kind, target)."""
        state = SchedulingState(clock=0)
        state = schedule_effect(state, Effect(EffectKind.SET_PLACE_FLAG, "sacred_clearing", {"flag": "tunnel_known", "value": True}), 30)
        restored = SchedulingState.from_dict(state.to_dict())
        self.assertEqual(restored.clock, state.clock)
        self.assertEqual(len(restored.pending), 1)
        self.assertEqual(restored.pending[0].due_time, 30)
        self.assertEqual(restored.pending[0].effect.kind, EffectKind.SET_PLACE_FLAG)
        self.assertEqual(restored.pending[0].effect.target, "sacred_clearing")

    def test_to_dict_result_is_json_safe(self):
        """A real, direct proof rather than an assumption — round-trips
        through json.dumps/json.loads, matching how this would actually
        be stored inside CurrentGame.state (a Django JSONField)."""
        state = SchedulingState(clock=0)
        state = schedule_effect(state, Effect(EffectKind.MOVE_CHARACTER, "mia", {"place_id": "hotel_bar"}), 5)
        round_tripped = json.loads(json.dumps(state.to_dict()))
        restored = SchedulingState.from_dict(round_tripped)
        self.assertEqual(restored.pending[0].effect.target, "mia")


class JumpClockTests(SimpleTestCase):
    """jump_clock() — a generic hard clock jump/rewind for a cheat menu or
    debug tool, using minutes (ONE_HOUR=60, ONE_DAY=1440) as this
    module's own baseline unit."""

    def test_forward_jump_adds_the_delta(self):
        """A positive delta advances the clock by that many minutes."""
        state = SchedulingState(clock=100)
        new_state = jump_clock(state, ONE_HOUR)
        self.assertEqual(new_state.clock, 160)

    def test_backward_jump_subtracts_via_a_negative_delta(self):
        """A negative delta rewinds the clock by that many minutes."""
        state = SchedulingState(clock=100)
        new_state = jump_clock(state, -ONE_HOUR)
        self.assertEqual(new_state.clock, 40)

    def test_one_day_is_1440_minutes(self):
        """ONE_DAY is a clean, symmetric 1440 minutes — unlike one real
        converted game's own cheat-menu constants
        (a game's own ONE_DAY_TICKS_FORWARD/BACKWARD), which are
        asymmetric and story-specific."""
        self.assertEqual(ONE_DAY, 1440)

    def test_jump_clock_fires_nothing_forward(self):
        """A forward jump never fires a pending effect, even one that
        would be due at the new clock value — this is a hard jump, not
        simulated time passing; a caller wanting due effects to fire
        calls advance() separately."""
        state = SchedulingState(clock=0)
        state = schedule_effect(state, Effect(EffectKind.SET_PERSON_FLAG, "brenda", {"flag": "x", "value": True}), 10)
        new_state = jump_clock(state, ONE_DAY)
        self.assertEqual(len(new_state.pending), 1)

    def test_jump_clock_fires_nothing_backward(self):
        """A backward jump also never fires a pending effect."""
        state = SchedulingState(clock=2000)
        state = schedule_effect(state, Effect(EffectKind.SET_PERSON_FLAG, "brenda", {"flag": "x", "value": True}), 10)
        new_state = jump_clock(state, -ONE_DAY)
        self.assertEqual(len(new_state.pending), 1)

    def test_jump_clock_does_not_mutate_the_original_state(self):
        """jump_clock() returns a new state; the original is untouched."""
        state = SchedulingState(clock=50)
        jump_clock(state, ONE_HOUR)
        self.assertEqual(state.clock, 50)


class CalendarPrimitiveTests(SimpleTestCase):
    """The generic, datetime-like primitives every story can use directly
    without any story-specific business rules: minute_of_day/hour_of_day/
    day_of_week/is_weekday, all operating on the module's own
    minutes-since-epoch clock baseline."""

    def test_minute_of_day_wraps_at_1440(self):
        """A clock value more than one day in reduces to its position
        within the current day."""
        self.assertEqual(minute_of_day(0), 0)
        self.assertEqual(minute_of_day(1439), 1439)
        self.assertEqual(minute_of_day(1440), 0)
        self.assertEqual(minute_of_day(1440 + 90), 90)

    def test_hour_of_day_divides_minutes_by_sixty(self):
        """hour_of_day is a plain floor-division of minute_of_day by 60,
        with no game-specific ceiling idiom involved."""
        self.assertEqual(hour_of_day(0), 0)
        self.assertEqual(hour_of_day(59), 0)
        self.assertEqual(hour_of_day(60), 1)
        self.assertEqual(hour_of_day(23 * 60 + 59), 23)

    def test_day_of_week_zero_is_monday(self):
        """Day 0 is Monday, matching the corpus-wide "0=Monday" convention
        already established for a real converted game's own day_of_week."""
        self.assertEqual(day_of_week(0), 0)
        self.assertEqual(day_of_week(ONE_DAY), 1)
        self.assertEqual(day_of_week(ONE_DAY * 6), 6)
        self.assertEqual(day_of_week(ONE_DAY * 7), 0)

    def test_is_weekday_true_monday_through_friday(self):
        """Days 0-4 (Monday-Friday) are weekdays; 5-6 (Saturday-Sunday)
        are not."""
        weekday_flags = [is_weekday(ONE_DAY * day) for day in range(7)]
        self.assertEqual(weekday_flags, [True, True, True, True, True, False, False])


class DayPhaseTests(SimpleTestCase):
    """is_morning/is_afternoon/is_evening/is_night/is_day — generic
    day-phase buckets with common-sense default boundaries, overridable
    per-story via DayPhaseBoundaries."""

    def test_default_boundaries_partition_the_day(self):
        """Every minute of the day belongs to exactly one of
        morning/afternoon/evening/night under the defaults."""
        for minute in range(0, 1440, 13):
            phases = [is_morning(minute), is_afternoon(minute), is_evening(minute), is_night(minute)]
            self.assertEqual(sum(phases), 1, f"minute {minute} matched {sum(phases)} phases, expected exactly 1")

    def test_is_day_is_the_negation_of_is_night(self):
        """is_day is true exactly when is_night is false, for the same
        clock/boundaries."""
        for minute in range(0, 1440, 13):
            self.assertEqual(is_day(minute), not is_night(minute))

    def test_morning_default_window(self):
        """Default morning is [6:00, 12:00)."""
        self.assertFalse(is_morning(5 * 60 + 59))
        self.assertTrue(is_morning(6 * 60))
        self.assertTrue(is_morning(11 * 60 + 59))
        self.assertFalse(is_morning(12 * 60))

    def test_night_default_window_wraps_past_midnight(self):
        """Default night is [21:00, 24:00) union [0:00, 6:00) — confirmed
        by checking both sides of the midnight wraparound."""
        self.assertFalse(is_night(20 * 60 + 59))
        self.assertTrue(is_night(21 * 60))
        self.assertTrue(is_night(23 * 60 + 59))
        self.assertTrue(is_night(0))
        self.assertTrue(is_night(5 * 60 + 59))
        self.assertFalse(is_night(6 * 60))

    def test_custom_boundaries_for_a_vampire_themed_story(self):
        """A story can define its own day/night split entirely (e.g. a
        vampire game where night runs 20:00-8:00) by passing its own
        DayPhaseBoundaries rather than being stuck with the defaults."""
        vampire_phases = DayPhaseBoundaries(morning_start=8 * 60, afternoon_start=12 * 60, evening_start=16 * 60, night_start=20 * 60)
        self.assertFalse(is_night(19 * 60 + 59, vampire_phases))
        self.assertTrue(is_night(20 * 60, vampire_phases))
        self.assertTrue(is_night(7 * 60 + 59, vampire_phases))
        self.assertFalse(is_night(8 * 60, vampire_phases))

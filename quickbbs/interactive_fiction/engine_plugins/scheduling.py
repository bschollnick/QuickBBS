"""SchedulingSystem: a generic clock/timed-event framework
(claude_docs/plans/external_expansion_IF_engine.md Step 5).

A reusable engine service ANY story's own conversion builds its specific
time-driven behavior on top of — never one specific game's own
implementation (see the plan's "generic framework, not a game-specific
implementation" design section). This module has zero knowledge of what a "character," a
"flag," or a "location" means in any specific story; it only understands
a clock and a queue of (due_time, effect) pairs, where an effect is one
of a small, closed, non-executable vocabulary (`Effect.kind` below) —
plain data the CALLER interprets and applies, never code this module runs
itself.

**Baseline unit is minutes, not an arbitrary "tick"** (explicit
2026-08-23 decision): `SchedulingState.clock` and every function below
that takes a `clock` argument treat it as a count of real minutes
(1440/day), matching everyday clock/calendar arithmetic (like Python's
own `datetime`) rather than any specific story's own internal tick
resolution. A story with a coarser or finer native clock (e.g. a
5-minutes-per-tick game clock) converts to/from minutes at its own
boundary — see a converted game's own scheduling module for exactly that
conversion — this
module is never told about, or written in terms of, any such
story-specific tick size.

**Common calendar/day-phase helpers, not story-specific business rules**:
this module also owns the small set of generic, `datetime`-like
primitives every story naturally needs (`is_weekday`, `hour_of_day`,
`is_morning`/`is_afternoon`/`is_evening`/`is_night`/`is_day`) — with
common-sense default boundaries, overridable per-story via
`DayPhaseBoundaries` (e.g. a vampire-themed story where "day" runs
20:00-8:00). What this module does NOT own is any story's own specific
open-hours/business-rule logic (e.g. "is this particular shop open") —
that's real story-specific data that belongs in the story's own
scheduling module built on top of these primitives, never baked in here.

**Why a closed effect vocabulary, not "run this callback"**: the original
JS source's own equivalent (`time.js`'s `TimedEvent`/`startTimedEvent`)
literally `eval()`s an arbitrary JavaScript string when a timer fires —
exactly the kind of "run untrusted code" pattern this whole EXTERNAL/
Story.is_engine_trusted design exists to avoid reintroducing. Confirmed
directly against source: `movePersonfterTime()`/`setPersonFlagAfterTime()`/
`setPlaceFlagAfterTime()` (`time.js`'s only 3 real call sites) are
themselves already a small, closed, non-`eval` vocabulary — every timed
event in the entire original game reduces to one of exactly 3 effect
kinds. `Effect` below mirrors those 3 kinds as plain, JSON-safe data.

**Why `advance()` only REPORTS fired effects rather than applying them**
(explicit user decision, 2026-08-22): this module has no opinion about
what a "character" or "flag" actually is in any given story's own state
shape — applying a `MOVE_CHARACTER` effect would require this generic
module to know how a specific story represents character location, which
is exactly the kind of story-specific knowledge that must not leak into a
reusable framework. The caller (a story's own EXTERNAL binding) applies
each reported effect to whatever state model it actually uses.

**Per-session isolation** (the plan's hard, load-bearing requirement):
every function here is a pure function of its own explicit arguments —
no instance attributes, no module-level mutable state, no shared object
holding per-game data. `SchedulingState`/`Effect` are plain, JSON-safe
dataclasses meant to round-trip through a session's own serialized state
(e.g. inside `CurrentGame.state`, alongside Ink's own VARs) exactly like
every other piece of per-game data already does.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from interactive_fiction.engine_api import EngineAPIDescriptor


class EffectKind(Enum):
    """The only 3 real timed-event effects in the original source
    (`time.js`'s `movePersonfterTime`/`setPersonFlagAfterTime`/
    `setPlaceFlagAfterTime`) — a closed, non-`eval` vocabulary. Extend
    this only by adding another named, closed kind here, never by
    accepting an arbitrary string/code payload."""

    MOVE_CHARACTER = "move_character"
    SET_PERSON_FLAG = "set_person_flag"
    SET_PLACE_FLAG = "set_place_flag"


@dataclass(frozen=True)
class Effect:
    """One timed event's effect, as plain, JSON-safe data — never code.

    Args:
        kind: Which of the 3 closed effect kinds this is.
        target: The subject of the effect — a character id for
            MOVE_CHARACTER/SET_PERSON_FLAG, a place id for
            SET_PLACE_FLAG. Deliberately just a plain string; this module
            never looks it up against anything, it only ever reports it
            back to the caller.
        payload: The effect's own real arguments (e.g.
            {"place_id": "hotel_room"} for MOVE_CHARACTER, {"flag":
            "doctorkay_flag3_deal_made", "value": True} for
            SET_PERSON_FLAG/SET_PLACE_FLAG) — plain JSON-safe values only.
    """

    kind: EffectKind
    target: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _PendingEvent:
    """One entry in a SchedulingState's own timed-event queue — internal
    to this module; callers only ever see Effect objects returned from
    advance(), never this directly."""

    due_time: int
    effect: Effect


@dataclass
class SchedulingState:
    """A session's own clock + pending timed-event queue.

    Deliberately holds no other per-game data (no character positions, no
    story flags) — those live in whatever state shape the caller already
    uses (e.g. Ink's own globals dict). This is JSON-safe and meant to be
    stored as one plain value inside a session's own serialized state,
    exactly like InkRuntimeState's own to_dict()/from_dict() shape.

    Args:
        clock: The current time, in whole minutes since an arbitrary
            session-defined epoch (see this module's own docstring for
            why minutes, not a story-specific tick, is the baseline
            unit). This module treats it as an opaque, ever-increasing
            integer, except where the generic calendar/day-phase helpers
            below interpret it.
        pending: The real timed-event queue, each entry a (due_time,
            effect) pair — a direct, non-`eval` port of source's own
            `vTimedEvent` array of `TimedEvent(evt, time)` objects.
    """

    clock: int = 0
    pending: list[_PendingEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain, JSON-safe dict.

        Returns:
            A dict safe to store inside a session's own serialized state
            (e.g. alongside InkRuntimeState.to_dict()'s own fields).
        """
        return {
            "clock": self.clock,
            "pending": [
                {
                    "due_time": event.due_time,
                    "effect": {
                        "kind": event.effect.kind.value,
                        "target": event.effect.target,
                        "payload": event.effect.payload,
                    },
                }
                for event in self.pending
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SchedulingState":
        """Rebuild from a to_dict() result.

        Args:
            data: A to_dict() result.

        Returns:
            The rebuilt SchedulingState.
        """
        pending = [
            _PendingEvent(
                due_time=int(event["due_time"]),
                effect=Effect(
                    kind=EffectKind(event["effect"]["kind"]),
                    target=str(event["effect"]["target"]),
                    payload=dict(event["effect"].get("payload", {})),
                ),
            )
            for event in data.get("pending", [])
        ]
        return cls(clock=int(data.get("clock", 0)), pending=pending)


def clock_in(data: dict[str, Any]) -> int:
    """Return just the clock value, from a serialized SchedulingState.

    `SchedulingState.from_dict()` rebuilds every pending event into a real
    `_PendingEvent`/`Effect` dataclass (an `EffectKind` enum lookup plus a
    `dict(...)` copy per entry) purely to answer "what time is it" —
    real, measured cost that most read-only callers never needed, since
    the clock is a plain int (2026-09-04, mirroring `character_occupancy.
    py`'s own `_in`-suffixed fix for the same reconstruction-on-every-read
    shape). `n_time_now()`/`is_day_now()`/`hours_charmed()` and every other
    tick-consuming binding route through `current_tick()`
    (`_games/asfa/scheduling.py`), which called this indirectly via the
    full dataclass on every single call — confirmed real hot spots in
    ASFA's own corpus (e.g. `avernus_club` calls `n_time_now()` 5 times in
    one knot; `is_day_now()` alone has 104 call sites corpus-wide, each
    one paying the full reconstruction under the old path).

    Args:
        data: A serialized `SchedulingState` — this session's own clock
            slot.

    Returns:
        The clock value, defaulting to 0 exactly as `from_dict()` does.
    """
    return int(data.get("clock", 0))


def schedule_effect(state: SchedulingState, effect: Effect, minutes_from_now: int) -> SchedulingState:
    """Queue an effect to fire `minutes_from_now` minutes after the
    current clock.

    A direct, non-`eval` port of source's own `startTimedEvent(evt, cnt)`
    (`time.js`) — `minutes_from_now` mirrors `cnt` exactly (an offset
    from the current clock, not an absolute time), converted to minutes
    at the caller's own boundary if its native clock uses a different
    unit.

    Args:
        state: The session's current SchedulingState.
        effect: The closed-vocabulary effect to fire once due.
        minutes_from_now: How many minutes from `state.clock` until this
            effect becomes due.

    Returns:
        A new SchedulingState with the effect added to `pending` — this
        function never mutates `state` in place, matching the stateless/
        per-session-isolation discipline every function in this module
        follows.
    """
    new_pending = [*state.pending, _PendingEvent(due_time=state.clock + minutes_from_now, effect=effect)]
    return SchedulingState(clock=state.clock, pending=new_pending)


def advance(state: SchedulingState, minutes: int) -> tuple[SchedulingState, list[Effect]]:
    """Advance the clock by `minutes` and report every effect now due.

    A direct, non-`eval` port of source's own `passTime()` → `nTime +=
    ...` → `checkTimedEvents()` sequence (`time.js`) — every due event
    fires (once, then is removed from the queue), same as source's own
    `TimedEvent.checkEvent()`/`vTimedEvent.splice()`. Per the explicit
    "SchedulingSystem only reports effects" design decision, this
    function does NOT apply any effect to any character/flag/place state
    itself — the caller is responsible for interpreting and applying each
    returned Effect to whatever state model it actually uses.

    Args:
        state: The session's current SchedulingState.
        minutes: How many minutes to advance the clock by (a real
            turn/action taken — the caller decides how many minutes that
            corresponds to, converting from its own native clock unit if
            needed).

    Returns:
        A tuple of (the new SchedulingState, the list of Effects that
        became due this advance, in the order they were originally
        scheduled). The new state's `pending` list has every fired effect
        already removed; anything not yet due stays queued.
    """
    new_clock = state.clock + minutes
    fired: list[Effect] = []
    still_pending: list[_PendingEvent] = []
    for event in state.pending:
        if event.due_time <= new_clock:
            fired.append(event.effect)
        else:
            still_pending.append(event)
    return SchedulingState(clock=new_clock, pending=still_pending), fired


MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = 1440

# Named minute deltas for jump_clock() below — a common "advance/rewind by
# a round unit" convenience every story's own cheat menu or debug tooling
# is likely to want; a story with its own asymmetric or unusually-sized
# jump amounts (e.g. a game's own real cheat-menu constants) defines those
# itself rather than using these.
ONE_HOUR = MINUTES_PER_HOUR
ONE_DAY = MINUTES_PER_DAY

# Named minute-of-day constants for every whole hour, so a schedule rule
# built with minute_in_range()/Condition.minute_in_range() reads as a real
# clock time instead of a bare number a reader has to divide by 60 to
# understand (explicit 2026-08-23 decision). Covers every whole hour;
# a half-hour/quarter-hour boundary is built with ordinary arithmetic on
# top of these, e.g. `EIGHT_AM + 15` for 8:15am, `SIX_PM + 30` for 6:30pm.
MIDNIGHT = 0 * MINUTES_PER_HOUR
ONE_AM = 1 * MINUTES_PER_HOUR
TWO_AM = 2 * MINUTES_PER_HOUR
THREE_AM = 3 * MINUTES_PER_HOUR
FOUR_AM = 4 * MINUTES_PER_HOUR
FIVE_AM = 5 * MINUTES_PER_HOUR
SIX_AM = 6 * MINUTES_PER_HOUR
SEVEN_AM = 7 * MINUTES_PER_HOUR
EIGHT_AM = 8 * MINUTES_PER_HOUR
NINE_AM = 9 * MINUTES_PER_HOUR
TEN_AM = 10 * MINUTES_PER_HOUR
ELEVEN_AM = 11 * MINUTES_PER_HOUR
NOON = 12 * MINUTES_PER_HOUR
ONE_PM = 13 * MINUTES_PER_HOUR
TWO_PM = 14 * MINUTES_PER_HOUR
THREE_PM = 15 * MINUTES_PER_HOUR
FOUR_PM = 16 * MINUTES_PER_HOUR
FIVE_PM = 17 * MINUTES_PER_HOUR
SIX_PM = 18 * MINUTES_PER_HOUR
SEVEN_PM = 19 * MINUTES_PER_HOUR
EIGHT_PM = 20 * MINUTES_PER_HOUR
NINE_PM = 21 * MINUTES_PER_HOUR
TEN_PM = 22 * MINUTES_PER_HOUR
ELEVEN_PM = 23 * MINUTES_PER_HOUR


def jump_clock(state: SchedulingState, delta: int) -> SchedulingState:
    """Jump the clock by `delta` minutes in one step, firing nothing.

    A hard jump/rewind, not simulated time passing — this function never
    fires or checks any pending timed event in either direction. A caller
    wanting due events to fire after a forward jump should call
    `advance()` separately. Useful for a cheat menu or debug tool wanting
    to forcibly set the game to a prior or later moment without replaying
    every intervening turn.

    Args:
        state: The session's current SchedulingState.
        delta: The signed minute delta to apply (positive to jump
            forward, negative to jump backward).

    Returns:
        A new SchedulingState with `clock` adjusted by `delta` and
        `pending` copied over completely unchanged — this function never
        mutates `state` in place.
    """
    return SchedulingState(clock=state.clock + delta, pending=list(state.pending))


def minute_of_day(clock: int) -> int:
    """Return the minute-of-day (0-1439) for `clock`.

    Args:
        clock: The current absolute clock value, in minutes.

    Returns:
        `clock` reduced to its position within a 1440-minute day.
    """
    return clock % MINUTES_PER_DAY


def hour_of_day(clock: int) -> int:
    """Return the hour of the day (0-23) for `clock`.

    Args:
        clock: The current absolute clock value, in minutes.

    Returns:
        The hour of the day, 0-23.
    """
    return minute_of_day(clock) // MINUTES_PER_HOUR


def day_of_week(clock: int) -> int:
    """Return the day of the week for `clock` (0=Monday .. 6=Sunday).

    Args:
        clock: The current absolute clock value, in minutes.

    Returns:
        The day of the week, 0 (Monday) through 6 (Sunday).
    """
    return (clock // MINUTES_PER_DAY) % 7


def is_weekday(clock: int) -> bool:
    """Return whether `clock` falls on a weekday (Monday-Friday).

    Args:
        clock: The current absolute clock value, in minutes.

    Returns:
        True if `day_of_week(clock)` is Monday (0) through Friday (4).
    """
    return day_of_week(clock) <= 4


@dataclass(frozen=True)
class DayPhaseBoundaries:
    """The minute-of-day cutoffs the generic day-phase helpers below use.

    Common-sense defaults are provided, but a story with its own notion
    of when "morning"/"night"/etc. begin (e.g. a vampire-themed story
    where night runs 20:00-8:00) builds its own instance and passes it
    explicitly — this module never hardcodes a single story's own
    convention as if it were universal.

    Args:
        morning_start: Minute-of-day morning begins (default 6:00).
        afternoon_start: Minute-of-day afternoon begins (default 12:00).
        evening_start: Minute-of-day evening begins (default 17:00).
        night_start: Minute-of-day night begins (default 21:00); night is
            understood to wrap past midnight into `morning_start`.
    """

    morning_start: int = 6 * MINUTES_PER_HOUR
    afternoon_start: int = 12 * MINUTES_PER_HOUR
    evening_start: int = 17 * MINUTES_PER_HOUR
    night_start: int = 21 * MINUTES_PER_HOUR


DEFAULT_DAY_PHASES = DayPhaseBoundaries()


def is_morning(clock: int, boundaries: DayPhaseBoundaries = DEFAULT_DAY_PHASES) -> bool:
    """Return whether `clock` falls within the morning phase.

    Args:
        clock: The current absolute clock value, in minutes.
        boundaries: The day-phase cutoffs to use (default: common-sense
            6:00-12:00 morning).

    Returns:
        True if the minute-of-day is in `[morning_start, afternoon_start)`.
    """
    minute = minute_of_day(clock)
    return boundaries.morning_start <= minute < boundaries.afternoon_start


def is_afternoon(clock: int, boundaries: DayPhaseBoundaries = DEFAULT_DAY_PHASES) -> bool:
    """Return whether `clock` falls within the afternoon phase.

    Args:
        clock: The current absolute clock value, in minutes.
        boundaries: The day-phase cutoffs to use (default: common-sense
            12:00-17:00 afternoon).

    Returns:
        True if the minute-of-day is in `[afternoon_start, evening_start)`.
    """
    minute = minute_of_day(clock)
    return boundaries.afternoon_start <= minute < boundaries.evening_start


def is_evening(clock: int, boundaries: DayPhaseBoundaries = DEFAULT_DAY_PHASES) -> bool:
    """Return whether `clock` falls within the evening phase.

    Args:
        clock: The current absolute clock value, in minutes.
        boundaries: The day-phase cutoffs to use (default: common-sense
            17:00-21:00 evening).

    Returns:
        True if the minute-of-day is in `[evening_start, night_start)`.
    """
    minute = minute_of_day(clock)
    return boundaries.evening_start <= minute < boundaries.night_start


def is_night(clock: int, boundaries: DayPhaseBoundaries = DEFAULT_DAY_PHASES) -> bool:
    """Return whether `clock` falls within the night phase.

    Handles wraparound past midnight (e.g. a vampire-themed story's own
    night_start=20:00, morning_start=8:00: night covers 20:00-24:00 AND
    0:00-8:00).

    Args:
        clock: The current absolute clock value, in minutes.
        boundaries: The day-phase cutoffs to use (default: common-sense
            21:00-6:00 night).

    Returns:
        True if the minute-of-day falls outside
        `[morning_start, night_start)`.
    """
    minute = minute_of_day(clock)
    return not boundaries.morning_start <= minute < boundaries.night_start


def is_day(clock: int, boundaries: DayPhaseBoundaries = DEFAULT_DAY_PHASES) -> bool:
    """Return whether `clock` falls within the daytime portion of its day.

    Args:
        clock: The current absolute clock value, in minutes.
        boundaries: The day-phase cutoffs to use (default: common-sense
            6:00-21:00 day).

    Returns:
        True whenever `is_night()` is False for the same clock/boundaries.
    """
    return not is_night(clock, boundaries)


def _init_scheduling_state() -> dict[str, Any]:
    """Return a brand-new game's own fresh SchedulingState, serialized.

    Returns:
        `SchedulingState().to_dict()` — clock at 0, no pending events.
    """
    return SchedulingState().to_dict()


def _bind_scheduling_state(state_dict: dict[str, Any]) -> dict[str, Callable[..., Any]]:
    """Build this session's clock bindings over its own SchedulingState.

    The clock becomes engine-owned state here rather than a value each
    story threads through every time-dependent call (2026-08-29). A story
    whose native time unit isn't minutes converts at its own boundary —
    see the module docstring — and keeps its own calendar semantics on
    top; this layer only owns "what time is it" and "time passed".

    Args:
        state_dict: This session's own `SchedulingState.to_dict()` result,
            read fresh on every call and overwritten in place by
            `advance_clock_now`.

    Returns:
        The bindings dict for the Ink function names a story calls.
    """

    def clock_now() -> int:
        """EXTERNAL clock_now() — the current absolute clock, in minutes."""
        return clock_in(state_dict)

    def advance_clock_now(minutes: int) -> int:
        """EXTERNAL advance_clock_now(minutes) — move the clock forward and
        drop any timed events that came due.

        Effects that fire are reported by `advance()` for a caller that
        applies them; this binding exists so a story can advance time from
        its own turn loop, so it discards them rather than inventing an
        application policy the engine deliberately does not own. Returns
        the new clock value."""
        updated, _fired = advance(SchedulingState.from_dict(state_dict), minutes)
        state_dict.clear()
        state_dict.update(updated.to_dict())
        return updated.clock

    def set_clock_now(clock: int) -> int:
        """EXTERNAL set_clock_now(clock) — set the clock outright, firing
        nothing. For a story restoring a saved time or applying its own
        jump/rewind. Returns the new clock value."""
        current = SchedulingState.from_dict(state_dict)
        state_dict.clear()
        state_dict.update(SchedulingState(clock=clock, pending=list(current.pending)).to_dict())
        return clock

    return {
        "clock_now": clock_now,
        "advance_clock_now": advance_clock_now,
        "set_clock_now": set_clock_now,
    }


# The real plugin-discovery contract (interactive_fiction/engine_api.py,
# 2026-08-22; stateful clock added 2026-08-29) — no config schema of its
# own yet. `SchedulingState` is now bound as real per-session state, so a
# story reads the clock from the engine instead of threading its own time
# value through every call.
API = EngineAPIDescriptor(
    name="scheduling",
    display_name="Scheduling",
    state_key="scheduling",
    init_state=_init_scheduling_state,
    bind_stateful=_bind_scheduling_state,
    bindings={
        "is_day_now": is_day,
        "is_morning_now": is_morning,
        "is_afternoon_now": is_afternoon,
        "is_evening_now": is_evening,
        "is_night_now": is_night,
        "hour_of_day_now": hour_of_day,
        "day_of_week_now": day_of_week,
        "is_weekday_now": is_weekday,
    },
)

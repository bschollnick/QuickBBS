"""CharacterOccupancy: who's at which location right now
(claude_docs/plans/external_expansion_IF_engine.md Step 6).

This module knows nothing about `location_graph.py`'s own map schema — it
never imports it, and its functions accept plain location-id strings
exactly as `location_graph.py` happens to produce them, but a story using
occupancy tracking with locations tracked some other way is never forced
to adopt the map schema too. Per the plan's explicit layered-API
requirement (2026-08-22): "the game decides to use this extra
information, or decides not to be burdened with it" — a game that only
wants `location_graph.py`'s pure map, or that tracks who's where with its
own hand-rolled Ink presence VARs, never has to import this module at
all; nothing here is a prerequisite for the other.

**The real problem this framework exists to shrink** (per the plan's
corrected framing): ASFA's own `_globals.ink` currently hand-writes ~101
individually near-duplicate `_place_now()` Ink functions, one per
character, each re-deriving "where is this specific person right now"
from schedule/story-flag logic — plus one giant `recompute_characters_here()`
calling all 101 by name. This module lets a character's schedule RULE be
expressed as plain, closed, JSON-safe DATA (a `ScheduleRule`) instead of
101 separate hand-written Ink functions, evaluated by one generic
function (`resolve_schedule()`) rather than 101 near-duplicate
implementations of the same evaluation logic.

**Optional dependency on SchedulingSystem, not a hard one.** A story can
track a character's location as a flat "wherever it was last explicitly
set" value (`set_location()`/`where_is()` alone, no schedule at all —
matches many of the ~46 "one clean fixed home" characters per
`asfa_location_and_travel_system.md`'s own Section 4.1 table) OR layer a
real `ScheduleRule` on top that resolves dynamically against a clock tick
and a set of session flags (matching the day/night-split, shop-hours-split,
and multi-condition-priority-chain shapes real `_place_now()` functions
already use). `resolve_schedule()` takes a plain integer tick value, not a
`SchedulingState` object — this module has no import of, or dependency
on, `engine_systems.scheduling` at all; a story supplies whatever tick
value it has, however it tracks its own clock.

Per-session isolation: every function here is a pure function of its own
explicit arguments — no instance attributes, no shared/module-level
state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from interactive_fiction.engine_api import EngineAPIDescriptor
from interactive_fiction.engine_config_schemas import validate_character_occupancy

# Named, closed registries a caller supplies to evaluate_condition()/
# resolve_schedule() for STORY_RULE/STORY_VALUE nodes — plain functions of
# the raw clock value (whatever unit the caller's own story uses, e.g.
# ASFA's n_time), never an arbitrary string the engine itself evaluates.
# The registry is the caller's own, so it never needs to be a fixed, known
# set here -- a story registers whichever of its own already-built rules
# (e.g. asfa_scheduling.is_school_open) or int-valued functions (e.g.
# asfa_scheduling.hour_of_day) its own schedule data references. Named
# "story_*" (not a bare "rule"/"value") because from the engine's own
# vantage point every name in these nodes resolves to whatever the
# CALLING STORY defines -- the engine itself has no story loaded and no
# opinion about what's in the registry.
StoryRuleRegistry = dict[str, Callable[[int], bool]]
StoryValueRegistry = dict[str, Callable[[int], "int | str"]]

# Ordering operators only make sense for numbers (ASFA never needs
# alphabetical string ordering); equality works for either a number or a
# string (e.g. comparing club_manager_name_now()'s real string result
# against a specific manager's name).
_ORDERING_OPERATORS: dict[str, Callable[[int, int], bool]] = {
    ">": lambda actual, target: actual > target,
    ">=": lambda actual, target: actual >= target,
    "<": lambda actual, target: actual < target,
    "<=": lambda actual, target: actual <= target,
}
_EQUALITY_OPERATORS: dict[str, Callable[[int | str, int | str], bool]] = {
    "==": lambda actual, target: actual == target,
    "!=": lambda actual, target: actual != target,
}
_COMPARISON_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {**_ORDERING_OPERATORS, **_EQUALITY_OPERATORS}


class ConditionKind(Enum):
    """The closed vocabulary a ScheduleRule's own condition tree is built
    from — plain, JSON-safe data, never a code string. Covers every real
    shape found in ASFA's own `_place_now()` functions (see
    `claude_docs/plans/asfa_ink_conversions/_globals.ink`): a raw flag
    check (story-flag-gated presence, e.g. Mia's `mia_night_barmaid`), a
    time-of-day range check (shop-hours/day-night splits), a named story
    rule check (delegating to a story-supplied boolean function of the
    clock, e.g. Nina's `is_shop_open_now()`), a named story value
    comparison (delegating to a story-supplied int-valued function of the
    clock, e.g. Doctor Kay's `hour_of_day_now() > 12`), and AND/OR/NOT
    combinators for the multi-condition priority chains (e.g. Doctor
    Kay's real 3-branch schedule)."""

    FLAG = "flag"
    MINUTE_IN_RANGE = "minute_in_range"
    STORY_RULE = "story_rule"
    STORY_VALUE = "story_value"
    AND = "and"
    OR = "or"
    NOT = "not"


@dataclass(frozen=True)
class Condition:
    """One node in a ScheduleRule's own condition tree.

    Args:
        kind: Which closed condition kind this node is.
        payload: The kind-specific data for this node, as a plain,
            JSON-safe dict — never a code string. Shape depends on
            `kind`; use the classmethods below (`flag_is_set()`,
            `minute_in_range()`, `story_rule()`, `story_value()`) to
            build a `Condition` rather than constructing `payload`
            directly. One shared dict field (rather than a separate
            optional field per kind) keeps this dataclass's own shape
            small regardless of how many condition kinds exist, mirroring
            `scheduling.Effect`'s own `payload` field for the same
            reason.
        clauses: The child Conditions being combined, for AND/OR/NOT
            nodes only (exactly one child for NOT).
    """

    kind: ConditionKind
    payload: dict[str, Any] = field(default_factory=dict)
    clauses: tuple["Condition", ...] = ()

    @classmethod
    def flag_is_set(cls, flag: str) -> "Condition":
        """Build a FLAG condition.

        Args:
            flag: The session-flag name to check.

        Returns:
            A Condition testing whether `flag` is set.
        """
        return cls(kind=ConditionKind.FLAG, payload={"flag": flag})

    @classmethod
    def minute_in_range(cls, minute_low: int, minute_high: int) -> "Condition":
        """Build a MINUTE_IN_RANGE condition.

        Args:
            minute_low: The inclusive lower bound, in minutes-of-day
                (0-1439) — build with `scheduling.py`'s named hour
                constants (e.g. `scheduling.EIGHT_AM`) rather than a bare
                integer.
            minute_high: The exclusive upper bound, in minutes-of-day —
                built the same way (e.g. `scheduling.SIX_PM`).

        Returns:
            A Condition testing whether the current time of day falls in
            `[minute_low, minute_high)`.
        """
        return cls(kind=ConditionKind.MINUTE_IN_RANGE, payload={"minute_low": minute_low, "minute_high": minute_high})

    @classmethod
    def story_rule(cls, rule_name: str) -> "Condition":
        """Build a STORY_RULE condition.

        Named "story_rule" (not a bare "rule") because from this
        engine's own vantage point, `rule_name` resolves to whatever the
        CALLING STORY defines — the engine has no story loaded and no
        opinion about what's in the registry. Used from inside a
        specific story's own schedule-authoring code (e.g. ASFA's own
        `asfa_scheduling.py`), the "story_" qualifier is not redundant to
        restate — it's the same method either way, and the "which side
        of the engine/story boundary" clarity comes from how the call
        site is documented, not from a second method name.

        Args:
            rule_name: The name of a story-supplied boolean function of
                the raw clock, looked up in the `StoryRuleRegistry`
                passed to `evaluate_condition()`/`resolve_schedule()`
                (e.g. "is_school_open").

        Returns:
            A Condition true exactly when the registry's own function
            returns True for the current raw clock value.
        """
        return cls(kind=ConditionKind.STORY_RULE, payload={"rule_name": rule_name})

    @classmethod
    def story_value(cls, value_name: str, operator: str, value: int | str) -> "Condition":
        """Build a STORY_VALUE condition.

        Args:
            value_name: The name of a story-supplied int-or-str-valued
                function of the raw clock, looked up in the
                `StoryValueRegistry` passed to
                `evaluate_condition()`/`resolve_schedule()` (e.g.
                "hour_of_day", or a string-returning function like
                "club_manager_name").
            operator: One of ">", ">=", "<", "<=" (numbers only — ASFA
                never needs alphabetical string ordering) or "==", "!="
                (numbers or strings).
            value: The int or str to compare the named function's result
                against — must be an int for an ordering operator.

        Returns:
            A Condition true exactly when
            `registry[value_name](clock) <operator> value` holds.

        Raises:
            ValueError: If an ordering operator (">"/">="/"<"/"<=") is
                given a string `value` — ordering a string isn't a real
                ASFA need and is almost certainly a mistake.
        """
        if isinstance(value, str) and operator in _ORDERING_OPERATORS:
            raise ValueError(f"story_value(): ordering operator {operator!r} is not valid for a string value ({value!r})")
        return cls(kind=ConditionKind.STORY_VALUE, payload={"value_name": value_name, "operator": operator, "value": value})

    @classmethod
    def all_of(cls, *clauses: "Condition") -> "Condition":
        """Build an AND condition.

        Args:
            *clauses: The Conditions that must all be true.

        Returns:
            A Condition true only when every clause is true.
        """
        return cls(kind=ConditionKind.AND, clauses=clauses)

    @classmethod
    def any_of(cls, *clauses: "Condition") -> "Condition":
        """Build an OR condition.

        Args:
            *clauses: The Conditions where at least one must be true.

        Returns:
            A Condition true when any clause is true.
        """
        return cls(kind=ConditionKind.OR, clauses=clauses)

    @classmethod
    def negate(cls, clause: "Condition") -> "Condition":
        """Build a NOT condition.

        Args:
            clause: The Condition to invert.

        Returns:
            A Condition true exactly when `clause` is false.
        """
        return cls(kind=ConditionKind.NOT, clauses=(clause,))


@dataclass(frozen=True)
class EvalContext:
    """The real session state a Condition tree is evaluated against —
    bundled into one object so `evaluate_condition()` takes a single
    context argument rather than one parameter per kind of state a
    Condition might need (flags, the clock, either registry).

    Args:
        flags: The set of currently-set session-flag names.
        minute_of_day: The current minute within a 1440-minute day
            (`(clock % 288) * 5`) — used by MINUTE_IN_RANGE only, which
            is generic and unit-agnostic-by-design.
        clock: The raw, un-reduced clock value as originally passed to
            `resolve_schedule()` — used by STORY_RULE/STORY_VALUE only,
            which delegate entirely to caller-supplied functions
            operating in whatever unit those functions expect (e.g.
            ASFA's own `n_time` tick count, not `minute_of_day`). Defaults
            to 0 for a Condition tree with no STORY_RULE/STORY_VALUE nodes.
        story_rules: The registry of named boolean functions of `clock`
            for STORY_RULE nodes. Defaults to an empty registry.
        story_values: The registry of named int-valued functions of
            `clock` for STORY_VALUE nodes. Defaults to an empty registry.
    """

    flags: frozenset[str]
    minute_of_day: int
    clock: int = 0
    story_rules: StoryRuleRegistry = field(default_factory=dict)
    story_values: StoryValueRegistry = field(default_factory=dict)


def _evaluate_combinator(condition: Condition, context: EvalContext) -> bool:
    """Evaluate an AND/OR/NOT combinator node's own child clauses.

    Args:
        condition: The AND/OR/NOT condition to evaluate.
        context: The real session state to evaluate its clauses against.

    Returns:
        Whether `condition` holds.
    """
    if condition.kind is ConditionKind.AND:
        return all(_evaluate(clause, context) for clause in condition.clauses)
    if condition.kind is ConditionKind.OR:
        return any(_evaluate(clause, context) for clause in condition.clauses)
    return not _evaluate(condition.clauses[0], context)


def _evaluate(condition: Condition, context: EvalContext) -> bool:
    """Evaluate one Condition node against a bundled evaluation context.

    Args:
        condition: The condition to evaluate.
        context: The real session state to evaluate it against.

    Returns:
        Whether `condition` holds.
    """
    if condition.kind is ConditionKind.FLAG:
        return condition.payload["flag"] in context.flags
    if condition.kind is ConditionKind.MINUTE_IN_RANGE:
        return condition.payload["minute_low"] <= context.minute_of_day < condition.payload["minute_high"]
    if condition.kind is ConditionKind.STORY_RULE:
        return context.story_rules[condition.payload["rule_name"]](context.clock)
    if condition.kind is ConditionKind.STORY_VALUE:
        value_function = context.story_values[condition.payload["value_name"]]
        return _COMPARISON_OPERATORS[condition.payload["operator"]](value_function(context.clock), condition.payload["value"])
    return _evaluate_combinator(condition, context)


def evaluate_condition(condition: Condition, context: EvalContext) -> bool:
    """Evaluate one Condition node against real session state.

    Args:
        condition: The condition to evaluate.
        context: The real session state to evaluate it against — flags,
            the clock (both raw and reduced to minute-of-day), and the
            STORY_RULE/STORY_VALUE registries. Build one directly (its
            `story_rules`/`story_values` default to `{}` for a Condition
            tree with no such nodes).

    Returns:
        Whether `condition` holds.
    """
    return _evaluate(condition, context)


@dataclass(frozen=True)
class ScheduleRule:
    """One branch of a character's schedule — "if this condition holds,
    they're at this place" — evaluated in declared order, first match
    wins, matching every real `_place_now()` function's own real
    if/elif-chain shape (see `claude_docs/plans/asfa_ink_conversions/
    _globals.ink`, e.g. Doctor Kay's 3-branch chain).

    Args:
        condition: The Condition gating this branch. None means "always
            true" — used for a schedule's own required final fallback
            branch (matching every real `_place_now()` function's own
            trailing `~ return 0`/fixed-place default).
        location_id: The location to report if `condition` holds, or
            None to mean "not present anywhere" (matching source's own
            `return 0` convention for an absent character).
    """

    condition: Condition | None
    location_id: str | None


def resolve_schedule(
    rules: tuple[ScheduleRule, ...],
    flags: frozenset[str],
    clock: int,
    story_rules: StoryRuleRegistry | None = None,
    story_values: StoryValueRegistry | None = None,
) -> str | None:
    """Resolve a character's real current location from their schedule.

    A direct generalization of every real `_place_now()` function's own
    if/elif-chain shape — evaluated top to bottom, first matching rule
    wins.

    Args:
        rules: The character's own schedule, in real priority order. The
            caller is responsible for ending this with an unconditional
            fallback rule (`condition=None`) if one is wanted; a schedule
            with no matching rule and no fallback resolves to None,
            matching source's own "not trackable" convention.
        flags: The set of currently-set session-flag names.
        clock: The current absolute tick count. This function reduces it
            to minute-of-day itself via `(clock % 288) * 5` for
            MINUTE_IN_RANGE nodes, so the caller can pass the same raw
            clock value `SchedulingSystem.SchedulingState.clock` already
            tracks, with zero coupling between the two modules. The raw,
            un-reduced value is also passed through unchanged to any
            STORY_RULE/STORY_VALUE node's own registry function, so a
            story whose registry functions expect its own native clock
            unit (e.g. ASFA's `n_time` ticks) gets that unit back
            unmodified, not a same-day-only minute count.
        story_rules: The registry of named boolean functions of `clock`
            for any STORY_RULE node in `rules`. Defaults to an empty
            registry — a schedule with no STORY_RULE nodes never needs
            one.
        story_values: The registry of named int-valued functions of
            `clock` for any STORY_VALUE node in `rules`. Defaults to an
            empty registry.

    Returns:
        The resolved location id, or None if the character isn't present
        anywhere right now.
    """
    context = EvalContext(flags=flags, minute_of_day=(clock % 288) * 5, clock=clock, story_rules=story_rules or {}, story_values=story_values or {})
    for rule in rules:
        if rule.condition is None or _evaluate(rule.condition, context):
            return rule.location_id
    return None


@dataclass
class OccupancyState:
    """A session's own explicit character locations — the "flat" half of
    occupancy tracking, independent of any ScheduleRule.

    Args:
        locations: character_id -> location_id, for every character whose
            location is explicitly set right now (via `set_location()`).
            A character with a real ScheduleRule (Step 6's schedule-driven
            occupancy) is typically NOT stored here at all — its location
            is resolved fresh every query via `resolve_schedule()`
            instead, matching real `_place_now()` functions' own
            recompute-on-every-call behavior rather than a stored,
            potentially-stale value. A character absent from `locations`
            with no ScheduleRule is simply not present anywhere.
    """

    locations: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain, JSON-safe dict.

        Returns:
            A dict safe to store inside a session's own serialized state.
        """
        return {"locations": dict(self.locations)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OccupancyState":
        """Rebuild from a to_dict() result.

        Args:
            data: A to_dict() result.

        Returns:
            The rebuilt OccupancyState.
        """
        return cls(locations=dict(data.get("locations", {})))


def set_location(state: OccupancyState, character_id: str, location_id: str | None) -> OccupancyState:
    """Explicitly set (or clear) a character's current location.

    Args:
        state: The session's current OccupancyState.
        character_id: The character to move.
        location_id: The location to place them at, or None to mark them
            absent (removes any existing entry).

    Returns:
        A new OccupancyState reflecting the change — this function never
        mutates `state` in place.
    """
    new_locations = dict(state.locations)
    if location_id is None:
        new_locations.pop(character_id, None)
    else:
        new_locations[character_id] = location_id
    return OccupancyState(locations=new_locations)


def where_is(state: OccupancyState, character_id: str) -> str | None:
    """Return a character's explicitly-set current location, if any.

    Does NOT consult any ScheduleRule — a schedule-driven character's
    real location comes from calling `resolve_schedule()` directly with
    their own rules, not from this function. A story with both kinds of
    character calls whichever function is right for the specific
    character being asked about.

    Args:
        state: The session's current OccupancyState.
        character_id: The character to look up.

    Returns:
        The character's current location id, or None if they have no
        explicitly-set location right now.
    """
    return state.locations.get(character_id)


def who_is_at(state: OccupancyState, location_id: str) -> list[str]:
    """Return every character explicitly placed at `location_id` right now.

    Only reflects `OccupancyState`'s own flat `locations` — a
    schedule-driven character present at `location_id` via
    `resolve_schedule()` is not included unless the caller also folds
    that result in itself (this function has no way to know about a
    story's own set of schedule-driven characters, since ScheduleRules
    are never stored in OccupancyState).

    Args:
        state: The session's current OccupancyState.
        location_id: The location to check.

    Returns:
        The character ids explicitly placed at `location_id`, in
        insertion order.
    """
    return [character_id for character_id, current_location in state.locations.items() if current_location == location_id]


def _init_occupancy_state() -> dict[str, Any]:
    """Return a brand-new game's own fresh OccupancyState, serialized.

    Returns:
        `OccupancyState().to_dict()` — no character has an explicitly-set
        location yet.
    """
    return OccupancyState().to_dict()


def _bind_occupancy_state(state_dict: dict[str, Any]) -> dict[str, Callable[..., Any]]:
    """Build this session's real `set_location`/`where_is`/`who_is_at`
    EXTERNAL bindings, closing over `state_dict` (this one session's own
    live `OccupancyState`, serialized).

    Per `EngineAPIDescriptor.bind_stateful`'s own contract
    (`interactive_fiction/engine_api.py`, "stateful EXTERNAL bindings"
    design, `external_expansion_IF_engine.md`, 2026-08-23): `state_dict`
    is this ONE request's own dict — never shared or reused across
    sessions, since `engine_services.bindings_for()` is itself called
    fresh per request. `set_location`/`where_is`/`who_is_at` (above) stay
    pure functions of an explicit `OccupancyState` in, value/new-state
    out; this wrapper is the only place that adapts them to read/mutate
    `state_dict` in place, so a write survives exactly as long as
    `state_dict` itself does (a session's `CurrentGame.state["engine_state"]`
    entry) with no change to their own tested signatures.

    Args:
        state_dict: This session's own `OccupancyState.to_dict()` result,
            read fresh on every call and overwritten in place by
            `set_location_now`.

    Returns:
        The bindings dict — `{"set_location_now": ..., "where_is_now":
        ..., "who_is_at_now": ...}` — for the Ink function names a
        story's own `.ink` content calls.
    """

    def set_location_now(character_id: str, location_id: str) -> int:
        """EXTERNAL set_location_now(character_id, location_id) — Ink
        VARs carry no None, so an empty string clears a character's
        location, matching `set_location()`'s own `location_id=None`
        case; any other string sets it. Returns 1 (Ink has no void
        EXTERNAL return)."""
        current = OccupancyState.from_dict(state_dict)
        updated = set_location(current, character_id, location_id or None)
        state_dict.clear()
        state_dict.update(updated.to_dict())
        return 1

    def where_is_now(character_id: str) -> str:
        """EXTERNAL where_is_now(character_id) -- "" (not None; see
        set_location_now's own note) if the character has no
        explicitly-set location right now."""
        return where_is(OccupancyState.from_dict(state_dict), character_id) or ""

    def who_is_at_now(location_id: str) -> str:
        """EXTERNAL who_is_at_now(location_id) -- every character
        explicitly placed there, joined with "," (Ink has no native list
        return either; a champion caller splits this itself). Empty
        string if nobody is there."""
        return ",".join(who_is_at(OccupancyState.from_dict(state_dict), location_id))

    return {
        "set_location_now": set_location_now,
        "where_is_now": where_is_now,
        "who_is_at_now": who_is_at_now,
    }


# The real plugin-discovery contract (interactive_fiction/engine_api.py,
# 2026-08-22, extended 2026-08-23 for stateful bindings) — set_location()/
# where_is()/who_is_at() are exposed as real EXTERNAL bindings via
# state_key/init_state/bind_stateful, closures adapted per-session by
# _bind_occupancy_state() above (see its own docstring for why this
# needs a wrapper rather than binding the pure functions directly).
API = EngineAPIDescriptor(
    name="character_occupancy",
    display_name="Character occupancy",
    validate_config=validate_character_occupancy,
    state_key="character_occupancy",
    init_state=_init_occupancy_state,
    bind_stateful=_bind_occupancy_state,
)

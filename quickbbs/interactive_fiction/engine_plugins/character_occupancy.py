"""CharacterOccupancy: who's at which location right now
(claude_docs/plans/external_expansion_IF_engine.md Step 6).

**This module depends on the map; the map does not depend on it**
(clarified 2026-08-31). "Who is at which location" presupposes a set of
locations, so a story using occupancy is expected to declare its places
through `location_graph.py`, and placing a character somewhere the map
never declared raises `UnknownLocationError` rather than being stored.
The reverse is not true: a game wanting only the map never has to adopt
occupancy.

Earlier wording here described the two as mutually independent, which is
right about the map's freedom and wrong about occupancy's: read
symmetrically it says occupancy must not consult the map, which left a
mistyped location id silently accepted — `who_is_at()` then answers with
an empty list, indistinguishable from "nobody is here", so the characters
and the scenes gated on them quietly vanish for the rest of the
playthrough.

The map reaches this module as an ordinary `also_reads` state slot, not
an import: the vocabulary is read from the session's own location state,
so a story that declares no map is simply unchecked rather than
broken.

**The real problem this framework exists to shrink** (per the plan's
corrected framing): a large converted game's own `_globals.ink` can end
up hand-writing dozens of individually near-duplicate `_place_now()` Ink
functions, one per character, each re-deriving "where is this specific
person right now" from schedule/story-flag logic — plus one giant
`recompute_characters_here()` calling all of them by name. This module
lets a character's schedule RULE be expressed as plain, closed, JSON-safe
DATA (a `ScheduleRule`) instead of dozens of separate hand-written Ink
functions, evaluated by one generic function (`resolve_schedule()`)
rather than dozens of near-duplicate implementations of the same
evaluation logic.

**Optional dependency on SchedulingSystem, not a hard one.** A story can
track a character's location as a flat "wherever it was last explicitly
set" value (`set_location()`/`where_is()` alone, no schedule at all —
matches the many "one clean fixed home" characters a typical story
has) OR layer a
real `ScheduleRule` on top that resolves dynamically against a clock tick
and a set of session flags (matching the day/night-split, shop-hours-split,
and multi-condition-priority-chain shapes real `_place_now()` functions
already use). `resolve_schedule()` takes a plain integer tick value, not a
`SchedulingState` object — this module has no import of, or dependency
on, `engine_plugins.scheduling` at all; a story supplies whatever tick
value it has, however it tracks its own clock.

**How the two halves fit together** (design corrected 2026-08-29):
`OccupancyState` is the live occupancy layer — the one record of where
each character is, player and NPC alike — sitting above whatever map the
story uses. A story's own scheduler/recompute step is what revises it:
it resolves each schedule-driven character with `resolve_schedule()` and
writes the answer back via `set_location()`. Reads then come from the
store.

Earlier revisions of this module documented the opposite arrangement,
in which a schedule-driven character was deliberately kept OUT of the
store and re-resolved on every read. That mirrored one converted game's
original call-time `whereNow()` implementation, and was mistaken for a
rule of this framework; it is not. Resolving on read is still perfectly
possible — `resolve_schedule()` and `resolve_present_characters()` are
public and a story may call them whenever it likes — but the store, not
a re-resolution, is the intended answer to "where is X right now".

Per-session isolation: every function here is a pure function of its own
explicit arguments — no instance attributes, no shared/module-level
state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from interactive_fiction.engine_api import EngineAPIDescriptor
from interactive_fiction.engine_plugins.location_graph import STATE_KEY as _LOCATION_STATE_KEY
from interactive_fiction.engine_config_schemas import validate_character_occupancy

# Named, closed registries a caller supplies to evaluate_condition()/
# resolve_schedule() for STORY_RULE/STORY_VALUE nodes — plain functions of
# the raw clock value (whatever unit the caller's own story uses, e.g. a
# game's own tick counter), never an arbitrary string the engine itself
# evaluates. The registry is the caller's own, so it never needs to be a
# fixed, known set here -- a story registers whichever of its own
# already-built rules (e.g. a game's own `is_school_open`) or int-valued
# functions (e.g. a game's own `hour_of_day`) its own schedule data
# references. Named
# "story_*" (not a bare "rule"/"value") because from the engine's own
# vantage point every name in these nodes resolves to whatever the
# CALLING STORY defines -- the engine itself has no story loaded and no
# opinion about what's in the registry.
StoryRuleRegistry = dict[str, Callable[[int], bool]]
StoryValueRegistry = dict[str, Callable[[int], "int | str"]]

# Ordering operators only make sense for numbers (a converted game's own
# schedule data never needs alphabetical string ordering); equality works for either a number or a
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
# Membership, for reading a plugin's own LIST-shaped state (e.g. a set of
# known ids serialized as a list). Only meaningful for ENGINE_STATE, where
# the value read may be a collection; STORY_VALUE always yields a scalar.
# A non-collection answers False rather than raising, matching this
# module's standing "a fact that has not happened answers no" contract.
_MEMBERSHIP_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "contains": lambda actual, target: bool(actual) and target in actual,
    "excludes": lambda actual, target: not actual or target not in actual,
}
_COMPARISON_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {**_ORDERING_OPERATORS, **_EQUALITY_OPERATORS, **_MEMBERSHIP_OPERATORS}


class ConditionKind(Enum):
    """The closed vocabulary a ScheduleRule's own condition tree is built
    from — plain, JSON-safe data, never a code string. Covers every real
    shape found in a converted game's own `_place_now()`-style functions:
    a raw flag check (story-flag-gated presence, e.g. a character who is
    only present during a night shift), a time-of-day range check
    (shop-hours/day-night splits), a named story rule check (delegating
    to a story-supplied boolean function of the clock, e.g. an
    "is the shop open now" check), a named story value comparison
    (delegating to a story-supplied int-valued function of the clock,
    e.g. an "hour of day greater than X" check), a read of another
    plugin's own state (ENGINE_STATE — see `Condition.engine_state()` for
    why this exists and why it is one kind rather than one per plugin),
    and AND/OR/NOT combinators for multi-condition priority chains."""

    FLAG = "flag"
    MINUTE_IN_RANGE = "minute_in_range"
    STORY_RULE = "story_rule"
    STORY_VALUE = "story_value"
    ENGINE_STATE = "engine_state"
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
        specific story's own schedule-authoring code (e.g. a converted
        game's own scheduling module), the "story_" qualifier is not redundant to
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
            operator: One of ">", ">=", "<", "<=" (numbers only — schedule
                data never needs alphabetical string ordering) or "==", "!="
                (numbers or strings).
            value: The int or str to compare the named function's result
                against — must be an int for an ordering operator.

        Returns:
            A Condition true exactly when
            `registry[value_name](clock) <operator> value` holds.

        Raises:
            ValueError: If an ordering operator (">"/">="/"<"/"<=") is
                given a string `value` — ordering a string isn't a
                real schedule-data need and is almost certainly a mistake.
        """
        if isinstance(value, str) and operator in _ORDERING_OPERATORS:
            raise ValueError(f"story_value(): ordering operator {operator!r} is not valid for a string value ({value!r})")
        return cls(kind=ConditionKind.STORY_VALUE, payload={"value_name": value_name, "operator": operator, "value": value})

    @classmethod
    def engine_state(cls, state_key: str, path: tuple[str, ...], operator: str = "==", value: Any = True, missing: Any = False) -> "Condition":
        """Build an ENGINE_STATE condition — a read of another plugin's state.

        **Why this kind exists.** Every other kind answers from something
        the caller hands in. This one answers from state a different
        plugin already holds, and it exists because the alternative is a
        round trip: a story reads the fact out of the owning plugin,
        formats its NAME into the flag set, passes that in, and the
        schedule tests membership — three conversions to ask a question
        both ends could already answer. That indirection is unavoidable
        while a fact lives in the story's own variables (a story engine
        cannot read those), and pure waste once it does not.

        **Why one kind rather than one per plugin.** A `CHARACTER_KNOWN`
        or `CHARM_AT_LEAST` kind would put story concepts into a generic
        vocabulary and grow it every time a plugin appeared. This names a
        state slot and a path within it, so it stays a statement about
        engine state rather than about characters or charm, and no plugin
        needs the enum extended to become readable.

        Args:
            state_key: The state slot to read, as its owning API declares
                it (e.g. `"characters"`).
            path: The keys to walk within that slot, outermost first —
                e.g. `("records", "doctorkay", "attributes",
                "flag3_deal_made")`.
            missing: What an unresolved path is worth. This is not
                cosmetic: a fact that has not happened yet is usually
                indistinguishable from its zero value, and a story asking
                `charm_level == 0` means "uncharmed", which must hold for
                a character nobody has ever charmed. Defaults to False,
                which compares equal to 0 and unequal to any true value —
                the right answer for both the boolean and the counter
                case. Pass something else where absence genuinely differs
                from a stored value.
            operator: How to compare the value found, from the same
                closed set STORY_VALUE uses. Defaults to `"=="`.
            value: What to compare against. Defaults to True, the common
                case of testing a boolean fact.

        Returns:
            The ENGINE_STATE Condition.

        Raises:
            ValueError: If `operator` is not one of the supported
                comparison operators.
        """
        if operator not in _COMPARISON_OPERATORS:
            raise ValueError(f"unsupported operator {operator!r}; expected one of {sorted(_COMPARISON_OPERATORS)}")
        return cls(
            kind=ConditionKind.ENGINE_STATE,
            payload={"state_key": state_key, "path": tuple(path), "operator": operator, "value": value, "missing": missing},
        )

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
            a game's own raw tick count, not `minute_of_day`). Defaults
            to 0 for a Condition tree with no STORY_RULE/STORY_VALUE nodes.
        story_rules: The registry of named boolean functions of `clock`
            for STORY_RULE nodes. Defaults to an empty registry.
        story_values: The registry of named int-valued functions of
            `clock` for STORY_VALUE nodes. Defaults to an empty registry.
        engine_state: Other plugins' serialized state, keyed by state
            slot, for ENGINE_STATE nodes. Read-only here: a schedule
            answers questions, it never writes. Defaults to empty, so a
            condition tree with no ENGINE_STATE nodes needs nothing.
    """

    flags: frozenset[str]
    minute_of_day: int
    clock: int = 0
    story_rules: StoryRuleRegistry = field(default_factory=dict)
    story_values: StoryValueRegistry = field(default_factory=dict)
    engine_state: dict[str, dict[str, Any]] = field(default_factory=dict)


def _read_engine_state(engine_state: dict[str, dict[str, Any]], state_key: str, path: tuple[str, ...]) -> Any:
    """Walk `path` into one state slot, or return None if it does not resolve.

    Missing is not an error: a schedule asks about facts that have not
    happened yet far more often than ones that have, and a story whose
    plugin has written nothing for a character should get "no" rather than
    a crash mid-turn.

    Args:
        engine_state: Other plugins' serialized state, keyed by slot.
        state_key: The slot to read.
        path: The keys to walk, outermost first.

    Returns:
        The value found, or None if any step is missing or a non-mapping
        is hit before the path is exhausted.
    """
    current: Any = engine_state.get(state_key)
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


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
    if condition.kind is ConditionKind.ENGINE_STATE:
        actual = _read_engine_state(context.engine_state, condition.payload["state_key"], condition.payload["path"])
        if actual is None:
            actual = condition.payload.get("missing", False)
        return _COMPARISON_OPERATORS[condition.payload["operator"]](actual, condition.payload["value"])
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
    if/elif-chain shape (a converted story's own globals file typically
    holds one such chain per character).

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


def resolve_schedule(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    rules: tuple[ScheduleRule, ...],
    flags: frozenset[str],
    clock: int,
    story_rules: StoryRuleRegistry | None = None,
    story_values: StoryValueRegistry | None = None,
    engine_state: dict[str, Any] | None = None,
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
            unit (e.g. a game's own raw tick count) gets that unit back
            unmodified, not a same-day-only minute count.
        story_rules: The registry of named boolean functions of `clock`
            for any STORY_RULE node in `rules`. Defaults to an empty
            registry — a schedule with no STORY_RULE nodes never needs
            one.
        story_values: The registry of named int-valued functions of
            `clock` for any STORY_VALUE node in `rules`. Defaults to an
            empty registry.
        engine_state: Other plugins' serialized state, keyed by state
            slot, for any ENGINE_STATE node in `rules` — the schedule
            reads a fact from whichever plugin owns it rather than having
            it handed in as a flag. Defaults to empty.

    Returns:
        The resolved location id, or None if the character isn't present
        anywhere right now.

    `# pylint: disable=too-many-arguments,too-many-positional-arguments`
    above: each parameter is one kind of state a `Condition` may read, and
    the closed `ConditionKind` vocabulary is what decides how many there
    are. Dropping any one would drop support for a condition kind. Same
    reasoning already documented on `resolve_present_characters()`, which
    takes the same set plus a location.
    """
    context = EvalContext(
        flags=flags,
        minute_of_day=(clock % 288) * 5,
        clock=clock,
        story_rules=story_rules or {},
        story_values=story_values or {},
        engine_state=engine_state or {},
    )
    for rule in rules:
        if rule.condition is None or _evaluate(rule.condition, context):
            return rule.location_id
    return None


class UnknownLocationError(ValueError):
    """A character was placed at a location the story never declared.

    Fatal by design, and deliberately not a warning. An unknown location
    id fails silently everywhere else: `who_is_at()` returns an empty
    list, `is_at()` returns False, and both are indistinguishable from
    "nobody is here" — so a typo does not break the game visibly, it
    quietly removes characters and the content gated on their presence
    for the rest of the playthrough. A player cannot detect that; a
    stopped game they can.

    Raised only when the story declares a map at all. A story that
    declares none is not second-guessed — it may track its places some
    other way entirely, which this module supports.
    """


@dataclass
class OccupancyState:
    """A session's live occupancy layer — where every tracked character is
    right now, sitting above whatever map the story uses.

    This is the single record of a character's current location, for the
    player and every NPC alike. A story's own scheduler is what REVISES
    it: when the story recomputes its schedules (however often it chooses
    to), it resolves each schedule-driven character via
    `resolve_schedule()` and writes the result back here with
    `set_location()`. Reads (`where_is()`, `who_is_at()`) then come from
    this store rather than re-resolving, so every consumer sees one
    consistent answer for a given moment.

    That makes a stored value as fresh as the story's last recompute. A
    story that flips a schedule-relevant flag and then immediately asks
    where someone is should recompute in between; a story that recomputes
    on entering each location gets correct answers everywhere without
    thinking about it.

    Args:
        locations: character_id -> location_id, for every character whose
            location is currently known. A character absent from
            `locations` is simply not present anywhere — either never
            placed, or explicitly cleared by `set_location(..., None)`.
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


def set_location(
    state: OccupancyState,
    character_id: str,
    location_id: str | None,
    known_locations: frozenset[str] | None = None,
) -> OccupancyState:
    """Explicitly set (or clear) a character's current location.

    Checked on every write, which is the only moment the bad value is
    still attributable: once a wrong id is in the store, every later
    symptom (an empty `who_is_at()`, a False `is_at()`) looks exactly
    like a character legitimately being elsewhere.

    Args:
        state: The session's current OccupancyState.
        character_id: The character to move.
        location_id: The location to place them at, or None to mark them
            absent (removes any existing entry).
        known_locations: Every location this story declares, or None to
            skip the check. A story that declares no locations tracks its
            map some other way, which this module supports, so it is
            never second-guessed.

    Returns:
        A new OccupancyState reflecting the change — this function never
        mutates `state` in place.

    Raises:
        UnknownLocationError: If `location_id` is not among
            `known_locations`. Fatal rather than logged: the alternative
            is a playthrough that silently loses characters.
    """
    if location_id is not None and known_locations and location_id not in known_locations:
        raise UnknownLocationError(
            f"cannot place {character_id!r} at unknown location {location_id!r}: "
            f"this story declares no such location (it declares {', '.join(sorted(known_locations)[:5])}"
            f"{', …' if len(known_locations) > 5 else ''})"
        )
    new_locations = dict(state.locations)
    if location_id is None:
        new_locations.pop(character_id, None)
    else:
        new_locations[character_id] = location_id
    return OccupancyState(locations=new_locations)


def where_is(state: OccupancyState, character_id: str) -> str | None:
    """Return a character's current location from the occupancy store.

    This is a plain read of the store — it never evaluates a
    ScheduleRule. A schedule-driven character answers correctly here
    because the story's scheduler wrote their resolved location in (see
    `OccupancyState`), so the value is as fresh as the last recompute.

    Args:
        state: The session's current OccupancyState.
        character_id: The character to look up.

    Returns:
        The character's current location id, or None if they are not
        placed anywhere right now.
    """
    return state.locations.get(character_id)


def is_at(state: OccupancyState, character_id: str, location_id: str) -> bool:
    """Return whether a character is at a given location.

    The boolean counterpart to `where_is()`, which returns the location
    itself. Both read the same store; this one exists because "is X here"
    is the question most story content actually asks, and spelling it as
    an equality against a location id at every call site invites the
    subtly different question "is X anywhere at all" to creep in as a
    substitute — they are not the same, and a story that conflates them
    reports characters as present across the whole map.

    Args:
        state: The session's current OccupancyState.
        character_id: The character to check.
        location_id: The location to check them against.

    Returns:
        True if the character's stored location equals `location_id`. A
        character who is nowhere is never "at" anywhere, including at "".
    """
    return state.locations.get(character_id) == location_id


def is_with(state: OccupancyState, character_id: str, other_character_id: str) -> bool:
    """Return whether two characters are at the same location.

    The store-based form of "is X here", where "here" means wherever
    another character (typically the player) currently is. A story asking
    that question about the player should use this rather than reading the
    player's location and comparing by hand, so the two reads cannot come
    from different moments.

    Neither character being placed anywhere counts as False: two absent
    characters are not together, they are both nowhere.

    Args:
        state: The session's current OccupancyState.
        character_id: The character being asked about.
        other_character_id: The character whose location defines "here" —
            usually the player.

    Returns:
        True if both are placed and their locations are equal.
    """
    location = state.locations.get(other_character_id)
    return location is not None and state.locations.get(character_id) == location


def is_anywhere(state: OccupancyState, character_id: str) -> bool:
    """Return whether a character is placed anywhere at all.

    Deliberately distinct from `is_at()`: this asks only whether the
    character exists in the world right now, not where. Useful for a
    story gating on "has this character been removed / not yet
    introduced", and wrong as a stand-in for presence at a place.

    Args:
        state: The session's current OccupancyState.
        character_id: The character to check.

    Returns:
        True if the store holds any location for them.
    """
    return character_id in state.locations


def who_is_at(state: OccupancyState, location_id: str) -> list[str]:
    """Return every character currently at `location_id`.

    Reads the occupancy store and nothing else — it never evaluates a
    ScheduleRule. Schedule-driven characters appear here once the story's
    scheduler has written their resolved locations in (see
    `OccupancyState`), which is the intended arrangement; a story that
    instead wants to resolve schedules on the spot, without consulting
    the store, calls `resolve_present_characters()`.

    Args:
        state: The session's current OccupancyState.
        location_id: The location to check.

    Returns:
        The character ids currently at `location_id`, in insertion order.
    """
    return [character_id for character_id, current_location in state.locations.items() if current_location == location_id]


# Serialized-state operations, for the binding layer (2026-09-04, mirroring
# `characters.py`'s own established `_in`-suffixed pattern exactly).
#
# A binding holds this session's locations as their serialized dict and is
# asked one question per call. `OccupancyState` has exactly one field
# (`locations`), so `OccupancyState.from_dict(state_dict)` is `dict(data.get(
# "locations", {}))` — cheap for one call, but every EXTERNAL binding below
# used to pay it on EVERY call, and real corpus content calls these
# repeatedly in one turn: a location hub scene with N choices each checking
# a character's presence pays N reconstructions of the same unchanged dict
# to answer N questions about it (confirmed 2026-09-04 auditing
# ASFA's own mayorthomas.ink — `where_is_now("mayor_thomas")` appears 7
# times in one `+`-choice list alone, all evaluated together). These read
# the dict directly instead.


def where_is_in(locations: dict[str, str], character_id: str) -> str | None:
    """Return a character's current location, from a serialized locations dict.

    Args:
        locations: The serialized `OccupancyState.locations` mapping.
        character_id: The character to look up.

    Returns:
        The character's current location id, or None if they are not
        placed anywhere right now.
    """
    return locations.get(character_id)


def is_at_in(locations: dict[str, str], character_id: str, location_id: str) -> bool:
    """Return whether a character is at a given location, from a serialized locations dict.

    Args:
        locations: The serialized `OccupancyState.locations` mapping.
        character_id: The character to check.
        location_id: The location to check them against.

    Returns:
        True if the character's stored location equals `location_id`.
    """
    return locations.get(character_id) == location_id


def is_with_in(locations: dict[str, str], character_id: str, other_character_id: str) -> bool:
    """Return whether two characters are at the same location, from a serialized locations dict.

    Args:
        locations: The serialized `OccupancyState.locations` mapping.
        character_id: The character being asked about.
        other_character_id: The character whose location defines "here".

    Returns:
        True if both are placed and their locations are equal.
    """
    location = locations.get(other_character_id)
    return location is not None and locations.get(character_id) == location


def is_anywhere_in(locations: dict[str, str], character_id: str) -> bool:
    """Return whether a character is placed anywhere at all, from a serialized locations dict.

    Args:
        locations: The serialized `OccupancyState.locations` mapping.
        character_id: The character to check.

    Returns:
        True if the dict holds any location for them.
    """
    return character_id in locations


def who_is_at_in(locations: dict[str, str], location_id: str) -> list[str]:
    """Return every character currently at `location_id`, from a serialized locations dict.

    Args:
        locations: The serialized `OccupancyState.locations` mapping.
        location_id: The location to check.

    Returns:
        The character ids currently at `location_id`, in insertion order.
    """
    return [character_id for character_id, current_location in locations.items() if current_location == location_id]


def resolve_present_characters(  # pylint: disable=too-many-arguments
    location_id: str,
    schedules: dict[str, tuple[ScheduleRule, ...]],
    flags: frozenset[str],
    clock: int,
    *,
    story_rules: StoryRuleRegistry | None = None,
    story_values: StoryValueRegistry | None = None,
    engine_state: dict[str, Any] | None = None,
) -> list[str]:
    """Return every schedule-driven character currently resolved to
    `location_id`, given each character's own ScheduleRule tuple.

    The schedule-driven counterpart to `who_is_at()` above, which only
    covers `OccupancyState`'s own flat, explicitly-set locations. This
    function answers the inverse of what `resolve_schedule()` answers for
    one character at a time ("where is this character right now") across
    every character in `schedules` at once ("who is at this place right
    now") — the real missing piece behind every story's own hand-rolled
    "is X here OR is Y here OR is Z here" chains repeated at each
    location. A pure loop over the same per-character resolution
    `resolve_schedule()` already does one character at a time — no new
    evaluation concept, the same closed `Condition`/`ScheduleRule`
    vocabulary, opaque `location_id`/`character_id` strings throughout.

    A character with no real ScheduleRule at all (e.g. explicitly placed
    via `OccupancyState`/`set_location()` instead) is not covered by this
    function — fold in a `who_is_at()` result separately if a story mixes
    both kinds of character at the same location.

    `# pylint: disable=too-many-arguments` above: this takes every
    parameter `resolve_schedule()` itself requires (flags, clock,
    story_rules, story_values) plus `location_id`, since it's answering a
    strictly harder question (search N characters' own Condition trees,
    which may freely mix flag/story_rule/story_value nodes in one
    branch — see e.g. the Doctor Kay-style 3-branch chain covered by
    ResolveScheduleTests) rather than resolving one. None of the 6 is
    droppable without breaking a real, already-supported condition kind;
    accepted as a real 6-argument function rather than an artificial
    split by condition kind (which would silently break any mixed
    AND/OR condition combining more than one kind).

    Args:
        location_id: The location to check.
        schedules: character_id -> that character's own ScheduleRule
            tuple, exactly as passed to `resolve_schedule()` individually.
        flags: The set of currently-set session-flag names, shared across
            every character's own schedule evaluation (matches
            `resolve_schedule()`'s own single-flags-set-per-call
            contract — a story with per-character flag namespacing keeps
            that namespacing in its own flag names, not here).
        clock: The current absolute tick count, passed through unchanged
            to every character's own `resolve_schedule()` call.
        story_rules: The registry of named boolean functions of `clock`,
            shared across every character's own STORY_RULE nodes.
            Defaults to an empty registry.
        story_values: The registry of named int-or-str-valued functions
            of `clock`, shared across every character's own STORY_VALUE
            nodes. Defaults to an empty registry.

    Returns:
        The character ids whose own `resolve_schedule()` result equals
        `location_id`, in `schedules`' own iteration order.
    """
    return [
        character_id
        for character_id, rules in schedules.items()
        if resolve_schedule(rules, flags=flags, clock=clock, story_rules=story_rules, story_values=story_values, engine_state=engine_state)
        == location_id
    ]


def recompute_occupancy(  # pylint: disable=too-many-arguments
    state: OccupancyState,
    schedules: dict[str, tuple[ScheduleRule, ...]],
    flags: frozenset[str],
    clock: int,
    *,
    story_rules: StoryRuleRegistry | None = None,
    story_values: StoryValueRegistry | None = None,
    engine_state: dict[str, Any] | None = None,
) -> OccupancyState:
    """Re-resolve every scheduled character and write the results into the
    occupancy store.

    This is the write-back sibling of `resolve_present_characters()`: that
    function answers "who is at this place right now" without touching the
    store, while this one performs the update a story's scheduler exists to
    perform. A story calls it whenever it wants the store brought up to
    date — typically on entering a location — and afterwards every
    `where_is()`/`who_is_at()` read reflects the same single moment.

    Computation lives here, at the engine level, rather than in a story's
    own binding layer: the engine holds both the schedules and the store,
    so it is the layer that can resolve them against each other. A
    character whose schedule resolves to None is cleared from the store
    ("nowhere" is the honest answer, not a reason to leave a stale entry
    behind). Characters absent from `schedules` — those placed explicitly
    via `set_location()`, the player included — are left untouched.

    `# pylint: disable=too-many-arguments` above: the parameter list is
    `resolve_schedule()`'s own required inputs (flags, clock, story_rules,
    story_values) plus the two things being joined, the store and the
    schedule tables. None is droppable without dropping a supported
    condition kind, exactly as documented on
    `resolve_present_characters()`.

    Args:
        state: The session's current OccupancyState.
        schedules: character_id -> that character's own ScheduleRule
            tuple, exactly as passed to `resolve_schedule()` individually.
        flags: The set of currently-set session-flag names, shared across
            every character's own schedule evaluation.
        clock: The current absolute tick count, passed through unchanged
            to every character's own `resolve_schedule()` call.
        story_rules: The registry of named boolean functions of `clock`,
            shared across every character's own STORY_RULE nodes. Defaults
            to an empty registry.
        story_values: The registry of named int-or-str-valued functions of
            `clock`, shared across every character's own STORY_VALUE
            nodes. Defaults to an empty registry.
        engine_state: Other plugins' serialized state, keyed by state
            slot, shared across every character's own ENGINE_STATE nodes.
            Defaults to empty.

    Returns:
        A new OccupancyState with every scheduled character's location
        refreshed — this function never mutates `state` in place.
    """
    # Built as one dict, not via a `set_location()` call per character
    # (2026-09-05): each such call used to do `dict(state.locations)` — a
    # full copy of the WHOLE locations map — purely to write one entry, an
    # O(n²) cost in the character count where O(n) suffices. Confirmed
    # real: ASFA's own schedule tables name 63 + 16 characters here plus 7
    # more in its own `_recompute_all` tail loop, called from
    # `recompute_characters_here()` roughly once per turn (~146
    # corpus-wide call sites) — ~86 full-map copies per turn against a map
    # growing toward ~100 entries. `set_location()`'s own
    # `UnknownLocationError` validation is not exercised by this loop
    # either way: `recompute_occupancy()` never receives `known_locations`
    # from any real caller (confirmed via a full-tree grep — every real
    # call site here omits it, defaulting to `None`, which already skips
    # the check inside `set_location()` itself), so nothing is lost by not
    # calling through it.
    new_locations = dict(state.locations)
    for character_id, rules in schedules.items():
        resolved = resolve_schedule(rules, flags=flags, clock=clock, story_rules=story_rules, story_values=story_values, engine_state=engine_state)
        if resolved is None:
            new_locations.pop(character_id, None)
        else:
            new_locations[character_id] = resolved
    return OccupancyState(locations=new_locations)


def _init_occupancy_state() -> dict[str, Any]:
    """Return a brand-new game's own fresh OccupancyState, serialized.

    Returns:
        `OccupancyState().to_dict()` — no character has an explicitly-set
        location yet.
    """
    return OccupancyState().to_dict()


def _bind_occupancy_state(state_dict: dict[str, Any], readable: dict[str, dict[str, Any]] | None = None) -> dict[str, Callable[..., Any]]:
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
        readable: The state slots this API reads but does not own, per
            `EngineAPIDescriptor.also_reads` — here the location map,
            whose declared vocabulary says which places exist. A write to
            a location the map does not declare is a typo, and raises
            rather than silently removing the character from the game. A
            story with no map slot is not checked.

    Returns:
        The bindings dict — `{"set_location_now": ..., "where_is_now":
        ..., "who_is_at_now": ...}` — for the Ink function names a
        story's own `.ink` content calls.
    """

    known_locations = frozenset((readable or {}).get(_LOCATION_STATE_KEY, {}).get("declared", ()))

    def set_location_now(character_id: str, location_id: str) -> int:
        """EXTERNAL set_location_now(character_id, location_id) — Ink
        VARs carry no None, so an empty string clears a character's
        location, matching `set_location()`'s own `location_id=None`
        case; any other string sets it. Returns 1 (Ink has no void
        EXTERNAL return).

        Raises:
            UnknownLocationError: If the story declares its locations and
                this is not one of them.
        """
        current = OccupancyState.from_dict(state_dict)
        updated = set_location(current, character_id, location_id or None, known_locations)
        state_dict.clear()
        state_dict.update(updated.to_dict())
        return 1

    def where_is_now(character_id: str) -> str:
        """EXTERNAL where_is_now(character_id) -- "" (not None; see
        set_location_now's own note) if the character has no
        explicitly-set location right now."""
        return where_is_in(state_dict.setdefault("locations", {}), character_id) or ""

    def is_at_now(character_id: str, location_id: str) -> bool:
        """EXTERNAL is_at_now(character_id, location_id) -- whether that
        character is at that location right now. The presence question,
        asked directly rather than as an equality a caller assembles."""
        return is_at_in(state_dict.setdefault("locations", {}), character_id, location_id)

    def is_with_now(character_id: str, other_character_id: str) -> bool:
        """EXTERNAL is_with_now(character_id, other_character_id) --
        whether the two are at the same location. The store-based form of
        "is X here", where "here" is wherever the other character (usually
        the player) is."""
        return is_with_in(state_dict.setdefault("locations", {}), character_id, other_character_id)

    def is_anywhere_now(character_id: str) -> bool:
        """EXTERNAL is_anywhere_now(character_id) -- whether the character
        is placed anywhere at all. NOT a substitute for `is_at_now()`:
        this is true wherever they are on the map."""
        return is_anywhere_in(state_dict.setdefault("locations", {}), character_id)

    def who_is_at_now(location_id: str) -> str:
        """EXTERNAL who_is_at_now(location_id) -- every character
        explicitly placed there, joined with "," (Ink has no native list
        return either; a champion caller splits this itself). Empty
        string if nobody is there."""
        return ",".join(who_is_at_in(state_dict.setdefault("locations", {}), location_id))

    return {
        "set_location_now": set_location_now,
        "where_is_now": where_is_now,
        "is_at_now": is_at_now,
        "is_with_now": is_with_now,
        "is_anywhere_now": is_anywhere_now,
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
    also_reads=(_LOCATION_STATE_KEY,),
)

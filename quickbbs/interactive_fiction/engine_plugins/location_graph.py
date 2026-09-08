"""LocationGraph: a plain, occupancy-free map framework
(claude_docs/plans/external_expansion_IF_engine.md Step 6).

This module knows only about places and the edges between them — it has
NO concept of a character, an NPC, or the player being "at" anywhere.
That is deliberate: a game that only wants "just a map" (can the player
go from A to B, is a place known/reachable) must never be forced to adopt
occupancy tracking to use this module.

**The dependency runs one way, and only one way** (clarified 2026-08-31).
The map does not depend on occupancy; occupancy depends on the map,
because "who is at which location" presupposes a set of locations.
Earlier wording here described the independence as symmetric, which read
as "occupancy must not consult the map" and led to occupancy
reconstructing a location vocabulary of its own — the duplicated-state
mistake this framework exists to prevent. A story placing a character
somewhere this map never declared is an error, and
`character_occupancy.set_location()` raises rather than storing it.

So this module still imports nothing from `character_occupancy` and has
no occupancy concept; the reverse is not true, and should not be.

Config shape: this API's own `StorySystemConfig.config` JSON (system_name
`"location_graph"`, discovered via this module's own `API` descriptor
below), validated by `engine_config_schemas.validate_location_graph()`
(Step 4) — `{"locations": {location_id: {"known_by_default": bool,
"edges": [{"to": location_id, "requires_known": bool}]}}}`.

Per-session isolation: every function taking a `LocationGraphState`
returns a new one rather than mutating it, and is otherwise a pure
function of its own explicit arguments (the story's config, the session's
own set of known location ids) — no instance attributes, no shared/module-level state.
`LocationGraphState` is a plain, JSON-safe dataclass meant to round-trip
through a session's own serialized state, exactly like `SchedulingState`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from interactive_fiction.engine_api import EngineAPIDescriptor
from interactive_fiction.engine_config_schemas import TERRAIN_MOVEMENT_COST, validate_location_graph


@dataclass
class LocationGraphState:
    """A session's own set of known location ids.

    Deliberately holds nothing else (no current position — that is
    `character_occupancy.py`'s job, for the specific character called
    "the player" if a story chooses to track it that way; this module has
    no privileged notion of "the player" at all).

    Args:
        known: The set of location ids this session has discovered.
            Location ids not flagged `known_by_default` in the story's
            config start absent from this set until `mark_known()` adds
            them.
        declared: Every location id the story's map declares, discovered
            or not — the map's own vocabulary, carried in the session's
            state so any system depending on this one can ask what places
            exist without reaching for the config itself. `known` is
            always a subset of it. Empty for a session whose state
            predates this field, which readers must treat as "this story
            declares no map" rather than "this story has no places".
        details: location_id -> that location's declared details, exactly
            as the story's config gave them (see
            `engine_config_schemas._validate_location_details`). Static
            facts, carried here so a dependent system reads one place for
            everything about a location.
        visits: location_id -> how many times this session has entered
            it. Absent means zero. A counter rather than a flag because
            "has the player been here" is recoverable from a count while
            a count is not recoverable from a flag; `has_visited()` is
            that derived boolean.
    """

    known: set[str] = field(default_factory=set)
    declared: set[str] = field(default_factory=set)
    details: dict[str, dict[str, Any]] = field(default_factory=dict)
    visits: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain, JSON-safe dict.

        Returns:
            A dict safe to store inside a session's own serialized state.
        """
        return {
            "known": sorted(self.known),
            "declared": sorted(self.declared),
            "details": {location_id: dict(detail) for location_id, detail in sorted(self.details.items())},
            "visits": {location_id: count for location_id, count in sorted(self.visits.items()) if count},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LocationGraphState":
        """Rebuild from a to_dict() result.

        Args:
            data: A to_dict() result.

        Returns:
            The rebuilt LocationGraphState.
        """
        return cls(
            known=set(data.get("known", [])),
            declared=set(data.get("declared", [])),
            details={location_id: dict(detail) for location_id, detail in data.get("details", {}).items()},
            visits=dict(data.get("visits", {})),
        )


def initial_state(config: dict[str, Any]) -> LocationGraphState:
    """Build the starting LocationGraphState for a new session.

    Args:
        config: The story's own `location_graph` config (already
            validated by `engine_config_schemas.validate_location_graph()`).

    Returns:
        A LocationGraphState with every `known_by_default: true` location
        already known.
    """
    locations = config.get("locations", {})
    known = {location_id for location_id, location in locations.items() if location.get("known_by_default", False)}
    details = {location_id: dict(location.get("details", {})) for location_id, location in locations.items()}
    visits = {location_id: detail["visits"] for location_id, detail in details.items() if detail.get("visits")}
    return LocationGraphState(known=known, declared=set(locations), details=details, visits=visits)


def _with_known(state: LocationGraphState, known: set[str]) -> LocationGraphState:
    """Return `state` with a different `known` set and everything else kept.

    Every discovery change goes through here so a new field on the state
    cannot be silently dropped by one of them — which is exactly what
    happened when `declared` was added.

    Args:
        state: The session's current LocationGraphState.
        known: The replacement set of discovered location ids.

    Returns:
        A new LocationGraphState.
    """
    return LocationGraphState(
        known=known,
        declared=set(state.declared),
        details={location_id: dict(detail) for location_id, detail in state.details.items()},
        visits=dict(state.visits),
    )


def detail(state: LocationGraphState, location_id: str, key: str, default: Any = None) -> Any:
    """Return one declared fact about a location.

    Args:
        state: The session's current LocationGraphState.
        location_id: The location to ask about.
        key: The detail key — one the engine defines (`name`, `terrain`,
            `region`, `lit`, `description`, `external_identifier`) or one
            the story declared itself.
        default: What to return when the location or the key is absent.

    Returns:
        The declared value, or `default`.
    """
    return state.details.get(location_id, {}).get(key, default)


def movement_cost(state: LocationGraphState, location_id: str, default: int = 1) -> int:
    """Return what arriving at a location costs, from its terrain.

    Args:
        state: The session's current LocationGraphState.
        location_id: The location being entered.
        default: The cost for a location declaring no terrain.

    Returns:
        That terrain's cost, or `default`.
    """
    terrain = detail(state, location_id, "terrain")
    return TERRAIN_MOVEMENT_COST.get(terrain, default) if isinstance(terrain, str) else default


def visit_count(state: LocationGraphState, location_id: str) -> int:
    """Return how many times this session has entered a location.

    Args:
        state: The session's current LocationGraphState.
        location_id: The location to ask about.

    Returns:
        The count, 0 if never entered.
    """
    return state.visits.get(location_id, 0)


def has_visited(state: LocationGraphState, location_id: str) -> bool:
    """Return whether a location has ever been entered.

    Derived from `visit_count()` rather than stored: one fact, one place,
    so the flag and the count can never disagree.

    Args:
        state: The session's current LocationGraphState.
        location_id: The location to ask about.

    Returns:
        True if it has been entered at least once.
    """
    return visit_count(state, location_id) > 0


def record_visit(state: LocationGraphState, location_id: str) -> LocationGraphState:
    """Return `state` with one more visit counted for `location_id`.

    Args:
        state: The session's current LocationGraphState.
        location_id: The location just entered.

    Returns:
        A new LocationGraphState.
    """
    updated = _with_known(state, set(state.known))
    updated.visits[location_id] = visit_count(state, location_id) + 1
    return updated


# Serialized-state operations, for the binding layer.
#
# A binding holds this session's state as its serialized dict and is
# asked one question per call. Rebuilding a LocationGraphState to answer
# it costs ~30x the answer itself, and the reference game's corpus asks
# ~600 times a turn, so these read and write the dict directly. The
# dataclass stays the API for anything holding a real state object; these
# are the same operations against the same shape.


def is_known_in(state_dict: dict[str, Any], location_id: str) -> bool:
    """Return whether a location is discovered, from serialized state.

    Args:
        state_dict: This session's own serialized LocationGraphState.
        location_id: The location to check.

    Returns:
        True if it has been discovered.
    """
    return location_id in state_dict.get("known", ())


def set_known_in(state_dict: dict[str, Any], location_id: str, known: bool) -> None:
    """Mark a location discovered (or not), in serialized state.

    Mutates `state_dict` in place, which is what the binding layer needs:
    its dict IS the session's live state, so a write here is already
    persisted when the turn ends.

    Args:
        state_dict: This session's own serialized LocationGraphState.
        location_id: The location to mark.
        known: True to mark it discovered, False to forget it.
    """
    discovered = set(state_dict.get("known", ()))
    if known:
        discovered.add(location_id)
    else:
        discovered.discard(location_id)
    state_dict["known"] = sorted(discovered)


def record_visit_in(state_dict: dict[str, Any], location_id: str) -> int:
    """Count one more visit to a location, in serialized state.

    Args:
        state_dict: This session's own serialized LocationGraphState.
        location_id: The location just entered.

    Returns:
        The new visit count.
    """
    visits = state_dict.setdefault("visits", {})
    visits[location_id] = visits.get(location_id, 0) + 1
    return visits[location_id]


def detail_in(state_dict: dict[str, Any], location_id: str, key: str, default: Any = None) -> Any:
    """Return one declared fact about a location, from serialized state.

    Args:
        state_dict: This session's own serialized LocationGraphState.
        location_id: The location to ask about.
        key: The detail key.
        default: What to return when the location or key is absent.

    Returns:
        The declared value, or `default`.
    """
    return state_dict.get("details", {}).get(location_id, {}).get(key, default)


def declares(state: LocationGraphState, location_id: str) -> bool:
    """Return whether the map declares `location_id` at all.

    Distinct from `is_known()`, which asks whether the PLAYER has found
    the place: an undiscovered location is still a real place, while an
    undeclared one does not exist in this story. That difference is what
    lets a dependent system tell "not yet found" from "not a place",
    which is why the two are separate functions rather than one.

    Args:
        state: The session's current LocationGraphState.
        location_id: The location to check.

    Returns:
        True if the map declares it. False for every id when the story
        declares no map at all — callers must check `declared` itself
        before treating a False as an error (see
        `character_occupancy.set_location()`).
    """
    return location_id in state.declared


def is_known(state: LocationGraphState, location_id: str) -> bool:
    """Return whether `location_id` has been discovered this session.

    Args:
        state: The session's current LocationGraphState.
        location_id: The location to check.

    Returns:
        True if `location_id` is in `state.known`.
    """
    return location_id in state.known


def mark_known(state: LocationGraphState, location_id: str) -> LocationGraphState:
    """Mark `location_id` as discovered.

    Args:
        state: The session's current LocationGraphState.
        location_id: The location to mark known.

    Returns:
        A new LocationGraphState with `location_id` added to `known`.
    """
    return _with_known(state, {*state.known, location_id})


def mark_unknown(state: LocationGraphState, location_id: str) -> LocationGraphState:
    """Mark `location_id` as no longer discovered.

    The inverse of `mark_known()`. Real stories do revoke a discovery
    (a place is destroyed, sealed, or the memory of it taken), so this
    is a first-class operation rather than something a story has to
    reach around the API to do.

    Args:
        state: The session's current LocationGraphState.
        location_id: The location to mark unknown. Marking an already-
            unknown location is a no-op, not an error.

    Returns:
        A new LocationGraphState with `location_id` removed from `known`.
    """
    return _with_known(state, {known_id for known_id in state.known if known_id != location_id})


def set_all_known(config: dict[str, Any], known: bool) -> LocationGraphState:
    """Return a state with EVERY location in `config` known, or none of them.

    One step for the whole map, rather than folding `mark_known()` over
    every id at the call site. The two real uses are a debug/cheat
    "reveal the whole map" toggle and a test fixture that needs every
    destination reachable without replaying each discovery scene.

    Note the asymmetry, which is deliberate: `known=False` clears the map
    completely, including locations the story's config marks
    `known_by_default`. It is "forget everything," not "reset to a new
    game" — `initial_state(config)` is the function for the latter, and a
    caller wanting new-game state must call that instead.

    Args:
        config: The story's own `location_graph` config (already
            validated by `engine_config_schemas.validate_location_graph()`).
        known: True to mark every declared location known; False to mark
            every location unknown.

    Returns:
        A new LocationGraphState — every declared location id when
        `known` is True, an empty set when False.
    """
    declared = config.get("locations", {})
    return LocationGraphState(
        known=set(declared) if known else set(),
        declared=set(declared),
        details={location_id: dict(location.get("details", {})) for location_id, location in declared.items()},
    )


def reachable_edges(config: dict[str, Any], state: LocationGraphState, location_id: str) -> list[str]:
    """Return the real outgoing edges from `location_id` reachable right now.

    An edge with `requires_known: true` is only included once its
    destination is already known some other way (e.g. a hexagram/fast-
    travel-style destination that must first be discovered normally); an
    edge with `requires_known: false`, or the key omitted entirely
    (the default — most ordinary walkable edges don't require the
    destination to already be known, since walking there is often how it
    BECOMES known), is always included.

    Args:
        config: The story's own `location_graph` config.
        state: The session's current LocationGraphState.
        location_id: The location to list real outgoing edges from.

    Returns:
        The destination location ids reachable from `location_id` right
        now, in the order declared in `config`. Empty if `location_id`
        isn't declared in `config` at all.
    """
    location = config.get("locations", {}).get(location_id)
    if location is None:
        return []
    destinations = []
    for edge in location.get("edges", []):
        destination = edge["to"]
        if edge.get("requires_known", False) and not is_known(state, destination):
            continue
        destinations.append(destination)
    return destinations


# The real plugin-discovery contract (interactive_fiction/engine_api.py,
# 2026-08-22) — this module exposes no EXTERNAL-dispatched bindings of its
# own (its functions operate on a story's own explicitly-threaded state,
# not on Ink's eval_stack directly), only a config schema.
# The state slot this API owns. Named as a module constant because a
# dependent API names it in its own `also_reads` — `character_occupancy`
# reads the declared vocabulary from here to reject a write to a place
# this story never declared.
STATE_KEY = "location_graph"


def _init_location_graph_state() -> dict[str, Any]:
    """Return a brand-new session's own, empty location state.

    Empty rather than config-derived: `EngineAPIDescriptor.init_state`
    takes no arguments, so it cannot see the story's own config. A story
    wanting its map's real starting state calls `initial_state(config)`
    itself, as the reference game does from its own `init_state`.

    Returns:
        A JSON-safe dict with nothing known and no map declared.
    """
    return LocationGraphState().to_dict()


API = EngineAPIDescriptor(
    name="location_graph",
    display_name="Location graph",
    validate_config=validate_location_graph,
    state_key=STATE_KEY,
    init_state=_init_location_graph_state,
)

"""LocationGraph: a plain, occupancy-free map framework
(claude_docs/plans/external_expansion_IF_engine.md Step 6).

This module knows only about places and the edges between them — it has
NO concept of a character, an NPC, or the player being "at" anywhere.
That is deliberate: per the plan's explicit layered-API requirement
(2026-08-22), a game that only wants "just a map" (the original idea —
can the player go from A to B, is a place known/reachable) must never be
forced to adopt occupancy tracking to use this module, and a game using
`character_occupancy.py` for occupancy must never be forced to adopt
THIS module's schema to track where characters are. The two modules
share only a convention (plain string location ids), never an import or
a shared data type.

Config shape: this API's own `StorySystemConfig.config` JSON (system_name
`"location_graph"`, discovered via this module's own `API` descriptor
below), validated by `engine_config_schemas.validate_location_graph()`
(Step 4) — `{"locations": {location_id: {"known_by_default": bool,
"edges": [{"to": location_id, "requires_known": bool}]}}}`.

Per-session isolation: every function here is a pure function of its own
explicit arguments (the story's config, the session's own set of known
location ids) — no instance attributes, no shared/module-level state.
`LocationGraphState` is a plain, JSON-safe dataclass meant to round-trip
through a session's own serialized state, exactly like `SchedulingState`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from interactive_fiction.engine_api import EngineAPIDescriptor
from interactive_fiction.engine_config_schemas import validate_location_graph


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
    """

    known: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain, JSON-safe dict.

        Returns:
            A dict safe to store inside a session's own serialized state.
        """
        return {"known": sorted(self.known)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LocationGraphState":
        """Rebuild from a to_dict() result.

        Args:
            data: A to_dict() result.

        Returns:
            The rebuilt LocationGraphState.
        """
        return cls(known=set(data.get("known", [])))


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
    return LocationGraphState(known=known)


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
        A new LocationGraphState with `location_id` added to `known` —
        this function never mutates `state` in place, matching the
        stateless/per-session-isolation discipline every function in this
        module follows.
    """
    return LocationGraphState(known={*state.known, location_id})


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
API = EngineAPIDescriptor(
    name="location_graph",
    display_name="Location graph",
    validate_config=validate_location_graph,
)

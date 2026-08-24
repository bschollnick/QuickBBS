"""Closed, hand-coded validator FUNCTIONS for each real engine API's own
config JSON shape.

claude_docs/plans/external_expansion_IF_engine.md's explicit requirement:
"A closed, validated schema per system (not 'arbitrary JSON interpreted
flexibly,' and never anything that could feed into a Python eval/
attribute-path lookup) is required so this doesn't become its own
injection surface even for trusted stories." Story-author-controlled
config is a real, separate risk from the EXTERNAL binding-trust question
this plan's Step 2/3 already gates — a validated shape here is required
regardless of whether the owning story is engine-trusted at all.

Hand-coded rather than a jsonschema-library dependency: this project has
few enough real systems' schemas to validate right now that pulling in a
new Poetry dependency is premature; jsonschema becomes the stronger
choice once a system's schema arrives with real nested/conditional
structure this hand-written approach would strain to express clearly.

Every validator here takes an already-json-decoded Python value (dict/
list/str/int/float/bool/None only — the same universe `StorySystemConfig.
config`'s own JSONField already restricts it to) and either returns
cleanly or raises SystemConfigValidationError with a human-readable
reason. None of them ever construct a Python object, import a name by
string, or otherwise turn story-author data into code — every check here
is a plain shape/type/value comparison.

**Dispatch by system_name is no longer done in this module** (removed
2026-08-22, see the note near the bottom of this file) — each real API
now points its own `EngineAPIDescriptor.validate_config` directly at one
of these functions; `interactive_fiction.engine_api.discover_api_descriptors()`
resolves which function runs for a given `system_name` dynamically, not
via a hardcoded dict here.
"""

from __future__ import annotations

from typing import Any


class SystemConfigValidationError(ValueError):
    """Raised when a StorySystemConfig's config JSON doesn't match its
    system_name's closed schema."""


def _require_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemConfigValidationError(f"{path} must be an object, got {type(value).__name__}")
    return value


def _require_str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise SystemConfigValidationError(f"{path} must be a non-empty string")
    return value


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise SystemConfigValidationError(f"{path} must be a boolean")
    return value


def validate_location_graph(config: Any) -> None:
    """Validate a `location_graph` system config.

    Real shape, grounded in `claude_docs/plans/asfa_ink_conversions/
    location_scenes.ink`'s own established pattern (a named location, a
    "known" gate, real outgoing edges to other named locations, each
    edge optionally gated on the destination's own known-flag):

    ```json
    {
        "locations": {
            "<location_id>": {
                "known_by_default": false,
                "edges": [
                    {"to": "<other_location_id>", "requires_known": true}
                ]
            }
        }
    }
    ```

    `edges[].requires_known` defaults to `false` when omitted (see
    `location_graph.reachable_edges()`) — most ordinary walkable edges
    don't require the destination to already be known, since walking
    there is often how it becomes known; `true` is for a destination that
    must be discovered some other way first (e.g. a fast-travel-style
    target).

    Args:
        config: The already-JSON-decoded config value to validate.

    Raises:
        SystemConfigValidationError: If the shape doesn't match, including
            an edge referencing a location_id not itself declared in
            "locations" (a real, closed graph — no dangling edges).
    """
    root = _require_dict(config, "location_graph config")
    locations = _require_dict(root.get("locations", {}), "location_graph.locations")
    if not locations:
        raise SystemConfigValidationError("location_graph.locations must declare at least one location")

    for location_id, location in locations.items():
        _require_str(location_id, "location_graph.locations key")
        location_path = f"location_graph.locations.{location_id}"
        location_dict = _require_dict(location, location_path)
        _require_bool(location_dict.get("known_by_default", False), f"{location_path}.known_by_default")
        edges = location_dict.get("edges", [])
        if not isinstance(edges, list):
            raise SystemConfigValidationError(f"{location_path}.edges must be a list")
        for index, edge in enumerate(edges):
            edge_path = f"{location_path}.edges[{index}]"
            edge_dict = _require_dict(edge, edge_path)
            destination = _require_str(edge_dict.get("to"), f"{edge_path}.to")
            if destination not in locations:
                raise SystemConfigValidationError(f"{edge_path}.to references unknown location '{destination}'")
            if "requires_known" in edge_dict:
                _require_bool(edge_dict["requires_known"], f"{edge_path}.requires_known")


_CONDITION_KINDS = {"flag", "minute_in_range", "story_rule", "story_value", "and", "or", "not"}
_ORDERING_OPERATORS = {">", ">=", "<", "<="}
_EQUALITY_OPERATORS = {"==", "!="}
_COMPARISON_OPERATORS = _ORDERING_OPERATORS | _EQUALITY_OPERATORS


def _validate_minute_in_range_condition(condition_dict: dict[str, Any], path: str) -> None:
    """Validate a "minute_in_range" condition node's own bounds.

    Args:
        condition_dict: The condition node's already-JSON-decoded dict.
        path: A human-readable path for error messages.

    Raises:
        SystemConfigValidationError: If a bound is missing or out of range.
    """
    for bound_name in ("minute_low", "minute_high"):
        bound_value = condition_dict.get(bound_name)
        if not isinstance(bound_value, int) or isinstance(bound_value, bool) or not 0 <= bound_value <= 1440:
            raise SystemConfigValidationError(f"{path}.{bound_name} must be an integer in [0, 1440]")


def _validate_story_value_condition(condition_dict: dict[str, Any], path: str) -> None:
    """Validate a "story_value" condition node's own value/operator shape.

    Args:
        condition_dict: The condition node's already-JSON-decoded dict.
        path: A human-readable path for error messages.

    Raises:
        SystemConfigValidationError: If the shape doesn't match.
    """
    _require_str(condition_dict.get("value_name"), f"{path}.value_name")
    operator = condition_dict.get("operator")
    if operator not in _COMPARISON_OPERATORS:
        raise SystemConfigValidationError(f"{path}.operator must be one of {sorted(_COMPARISON_OPERATORS)}, got {operator!r}")
    value = condition_dict.get("value")
    is_valid_int = isinstance(value, int) and not isinstance(value, bool)
    is_valid_str = isinstance(value, str) and value != ""
    if operator in _ORDERING_OPERATORS:
        if not is_valid_int:
            raise SystemConfigValidationError(f"{path}.value must be an integer for ordering operator {operator!r}")
    elif not (is_valid_int or is_valid_str):
        raise SystemConfigValidationError(f"{path}.value must be a non-empty string or an integer")


def _validate_condition_clauses(condition_dict: dict[str, Any], path: str, kind: str) -> None:
    """Validate the "clauses" list of an AND/OR/NOT condition node.

    Args:
        condition_dict: The condition node's already-JSON-decoded dict.
        path: A human-readable path for error messages.
        kind: Either "not" (exactly 1 clause) or "and"/"or" (1+ clauses).

    Raises:
        SystemConfigValidationError: If the clause count or shape is wrong.
    """
    clauses = condition_dict.get("clauses", [])
    if kind == "not":
        if not isinstance(clauses, list) or len(clauses) != 1:
            raise SystemConfigValidationError(f"{path}.clauses must be a list of exactly 1 item for 'not'")
    elif not isinstance(clauses, list) or not clauses:
        raise SystemConfigValidationError(f"{path}.clauses must be a non-empty list for '{kind}'")
    for index, clause in enumerate(clauses):
        _validate_condition(clause, f"{path}.clauses[{index}]")


def _validate_condition(condition: Any, path: str) -> None:
    """Validate one node of a ScheduleRule's own recursive condition tree.

    Mirrors `character_occupancy.Condition`'s real closed shape exactly —
    a `kind` in `_CONDITION_KINDS`, plus exactly the fields that kind
    needs (never extra ones, never missing ones).

    Args:
        condition: The already-JSON-decoded condition node to validate.
        path: A human-readable path for error messages.

    Raises:
        SystemConfigValidationError: If the shape doesn't match.
    """
    condition_dict = _require_dict(condition, path)
    kind = condition_dict.get("kind")
    if kind not in _CONDITION_KINDS:
        raise SystemConfigValidationError(f"{path}.kind must be one of {sorted(_CONDITION_KINDS)}, got {kind!r}")
    if kind == "flag":
        _require_str(condition_dict.get("flag"), f"{path}.flag")
    elif kind == "minute_in_range":
        _validate_minute_in_range_condition(condition_dict, path)
    elif kind == "story_rule":
        _require_str(condition_dict.get("rule_name"), f"{path}.rule_name")
    elif kind == "story_value":
        _validate_story_value_condition(condition_dict, path)
    else:  # "not" / "and" / "or"
        _validate_condition_clauses(condition_dict, path, kind)


def validate_character_occupancy(config: Any) -> None:
    """Validate a `character_occupancy` system config.

    Real shape, mirroring `character_occupancy.ScheduleRule`/`Condition`
    exactly — this is a data-driven port of the real if/elif priority
    chains every `_place_now()` function in `claude_docs/plans/
    asfa_ink_conversions/_globals.ink` already uses:

    ```json
    {
        "characters": {
            "<character_id>": {
                "schedule": [
                    {
                        "condition": {"kind": "flag", "flag": "zali_met"},
                        "location_id": "zali_house"
                    },
                    {"condition": null, "location_id": null}
                ]
            }
        }
    }
    ```

    A schedule's own rules are evaluated top to bottom, first match wins
    (mirroring every real `_place_now()` function's own if/elif shape) —
    `condition: null` means "always true," used for a schedule's own
    trailing fallback rule. `location_id: null` means "not present
    anywhere," matching source's own `return 0` convention.

    Args:
        config: The already-JSON-decoded config value to validate.

    Raises:
        SystemConfigValidationError: If the shape doesn't match.
    """
    root = _require_dict(config, "character_occupancy config")
    characters = _require_dict(root.get("characters", {}), "character_occupancy.characters")
    if not characters:
        raise SystemConfigValidationError("character_occupancy.characters must declare at least one character")

    for character_id, character in characters.items():
        _require_str(character_id, "character_occupancy.characters key")
        character_path = f"character_occupancy.characters.{character_id}"
        character_dict = _require_dict(character, character_path)
        schedule = character_dict.get("schedule", [])
        if not isinstance(schedule, list) or not schedule:
            raise SystemConfigValidationError(f"{character_path}.schedule must be a non-empty list")
        for index, rule in enumerate(schedule):
            rule_path = f"{character_path}.schedule[{index}]"
            rule_dict = _require_dict(rule, rule_path)
            if "location_id" not in rule_dict:
                raise SystemConfigValidationError(f"{rule_path}.location_id is required (use null for 'not present')")
            location_id = rule_dict["location_id"]
            if location_id is not None and not isinstance(location_id, str):
                raise SystemConfigValidationError(f"{rule_path}.location_id must be a string or null")
            condition = rule_dict.get("condition")
            if condition is not None:
                _validate_condition(condition, f"{rule_path}.condition")


# NOTE (2026-08-22): the closed VALIDATORS dict + validate_system_config()
# that previously lived here were removed as part of the plugin-discovery
# redesign (interactive_fiction/engine_api.py) — a hardcoded dict of
# {system_name: validator} could never represent an API discovered later
# via the scan-based plugin mechanism without editing this file, which
# defeats the entire "third parties add APIs without touching QuickBBS
# source" goal. Each API now carries its OWN validator directly on its
# EngineAPIDescriptor.validate_config (see e.g.
# interactive_fiction/engine_systems/location_graph.py's own `API ='
# declaration) resolved dynamically via
# interactive_fiction.engine_api.discover_api_descriptors() — see
# StorySystemConfig.clean() in interactive_fiction/models.py for the real
# call site. validate_location_graph()/validate_character_occupancy()
# below remain as the real, reusable validator FUNCTIONS each API's own
# descriptor points at; only the closed dispatch-by-name dict was removed.

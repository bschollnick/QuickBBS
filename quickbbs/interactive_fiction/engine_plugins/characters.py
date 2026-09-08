"""Characters: per-character keyed storage, and one place to ask about a
character (`claude_docs/plans/asfa_engine_revamp.md` Step 9a).

**What this module owns, and what it deliberately does not.** A converted
game's characters accumulate a great deal of small per-character state —
"has this one been introduced", "did that one agree to the plan", numbered
switches whose meaning is private to one storyline. That data has no
natural home in any of the other plugins, so a conversion typically
flattens it into one global variable per fact, which is how a corpus ends
up with hundreds of near-identical names. This module gives that data its
own shape: `character_id -> {key: value}`.

It owns **only** that. Where a character is, what they can do, how charmed
they are, what they carry — those already belong to
`character_occupancy`, `skills`, and an inventory system respectively, and
storing them here as well would mean two records of one fact, which is the
bug class this framework exists to avoid. Instead the character API below
reads through to whichever plugin owns each fact, so a story can ask every
question about a character in one vocabulary without any state being
duplicated. `current_location_of()` is the worked example: it holds
nothing and answers from the occupancy store it is handed.

The shape mirrors what such games actually store. In the case this module
was built for, the original game's own character object carries a
`flags[]` array read through `checkFlag(n)`/`setFlag(n, value)` plus a
free-form `extra[]` — per-character keyed storage, exactly this. A
conversion that flattens those into globals is losing the structure, not
adding one.

Values are restricted to plain JSON-safe scalars so a session's state
round-trips like every other plugin's. Per-session isolation: every
function is a pure function of its explicit arguments.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from interactive_fiction.engine_api import EngineAPIDescriptor

# What an attribute may hold. Deliberately narrow: these values are
# serialized into a session's own state, so anything that does not survive
# a JSON round-trip cannot go here.
AttributeValue = bool | int | float | str


@dataclass
class CharacterState:
    """A session's per-character attributes, and its known-character set.

    Args:
        records: character_id -> that character's own record. Each record
            is `{"attributes": {name: value}}`. A character with nothing
            stored yet simply has no entry; reading an unset attribute
            returns a caller-supplied default rather than raising, because
            story content asks about facts that have not happened yet far
            more often than it asks about ones that have.

            **Keyed by character first, deliberately.** The obvious
            alternative — one `attributes` map of character to values —
            stores the same data but describes it backwards: a path into
            it reads "attributes, then doctorkay", when the fact being
            named is doctorkay's. Character-major means a record is
            addressed as `(character, "attributes", name)`, which is the
            sentence the caller is actually saying, and it leaves room for
            a record to carry more than attributes later without
            restructuring every reader.
        known: The characters the player has met. Kept as its own set
            rather than an attribute because "have I met this person" is
            asked across a whole corpus in one uniform way, and a
            dedicated vocabulary makes that uniformity visible — the same
            reasoning that gives `location_graph` a `known` set rather
            than a per-location flag.
    """

    records: dict[str, dict[str, dict[str, AttributeValue]]] = field(default_factory=dict)
    known: set[str] = field(default_factory=set)

    @property
    def attributes(self) -> dict[str, dict[str, AttributeValue]]:
        """Return every character's attributes, keyed by character.

        A convenience view for callers that want the whole picture; the
        records themselves stay the storage.

        Returns:
            character_id -> {attribute name: value}, excluding characters
            with no attributes.
        """
        return {character_id: dict(record.get("attributes", {})) for character_id, record in self.records.items()}

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain, JSON-safe dict.

        Returns:
            A dict safe to store inside a session's own serialized state.
            `known` becomes a sorted list so the serialized form is
            stable — an unordered set would otherwise produce a different
            payload on every save for identical state.
        """
        return {
            "records": {character_id: {"attributes": dict(record.get("attributes", {}))} for character_id, record in self.records.items()},
            "known": sorted(self.known),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CharacterState":
        """Rebuild from a to_dict() result.

        Args:
            data: A to_dict() result.

        Returns:
            The rebuilt CharacterState.
        """
        return cls(
            records={character_id: {"attributes": dict(record.get("attributes", {}))} for character_id, record in data.get("records", {}).items()},
            known=set(data.get("known", [])),
        )


# Serialized-state operations, for the binding layer.
#
# A binding holds this session's records as their serialized dict and is
# asked one attribute per call. Rebuilding a CharacterState to answer it
# copies every record — ~30x the cost of the answer — so these read and
# write the dict directly. The dataclass stays the API for anything
# holding a real state object; these are the same operations against the
# same shape, and `records` is that shape in both.


def read_attribute_in(
    records: dict[str, Any], entity_id: str, attribute: str, default: AttributeValue = False
) -> AttributeValue:
    """Return one stored attribute, from serialized records.

    Args:
        records: The serialized `CharacterState.records` mapping.
        entity_id: Whose record to read — a character, or whatever else a
            story keys this storage by.
        attribute: The attribute name.
        default: What to return when unset.

    Returns:
        The stored value, or `default`.
    """
    return records.get(entity_id, {}).get("attributes", {}).get(attribute, default)


def set_attribute_in(records: dict[str, Any], entity_id: str, attribute: str, value: AttributeValue) -> None:
    """Store one attribute, in serialized records.

    Mutates `records` in place: the binding layer's dict IS the session's
    live state, so a write here is already persisted when the turn ends.

    Args:
        records: The serialized `CharacterState.records` mapping.
        entity_id: Whose record to write.
        attribute: The attribute name.
        value: The value to store.
    """
    records.setdefault(entity_id, {}).setdefault("attributes", {})[attribute] = value


def does_attribute_exist_in(records: dict[str, Any], entity_id: str, attribute: str) -> bool:
    """Return whether an attribute has ever been stored, from serialized records.

    Distinct from reading it: a stored `False` and an unset attribute
    both read as false, and a story sometimes needs to tell them apart.

    Args:
        records: The serialized `CharacterState.records` mapping.
        entity_id: Whose record to check.
        attribute: The attribute name.

    Returns:
        True if the attribute is present, whatever its value.
    """
    return attribute in records.get(entity_id, {}).get("attributes", {})


def is_known_in(state_dict: dict[str, Any], character_id: str) -> bool:
    """Return whether the player has met this character, from serialized state.

    Mirrors `location_graph.is_known_in()` exactly, for the same reason:
    a plain membership check needs only the `known` list, not every
    character's own `records` — which `CharacterState.from_dict()` would
    otherwise rebuild in full just to answer this (2026-09-04, the same
    `_in`-suffixed pattern already applied to `character_occupancy.py`/
    `scheduling.py`/`inventory.py`/`quests.py`).

    Args:
        state_dict: This session's own serialized CharacterState.
        character_id: The character being asked about.

    Returns:
        True once `set_known_in()` has marked them met.
    """
    return character_id in state_dict.get("known", ())


def set_known_in(state_dict: dict[str, Any], character_id: str, known: bool) -> None:
    """Mark a character met (or not), in serialized state.

    Mutates `state_dict` in place, which is what the binding layer needs:
    its dict IS the session's live state, so a write here is already
    persisted when the turn ends. Touches only the `known` list, unlike
    `set_known()`/`set_unknown()`, which each deep-copy every character's
    `records` to build a new `CharacterState` purely to change this one
    list.

    Args:
        state_dict: This session's own serialized CharacterState.
        character_id: The character to mark.
        known: True to mark them met, False to mark them not met.
    """
    met = set(state_dict.get("known", ()))
    if known:
        met.add(character_id)
    else:
        met.discard(character_id)
    state_dict["known"] = sorted(met)


def clear_all_attributes_in(records: dict[str, Any], character_id: str) -> None:
    """Remove every attribute from one character, in serialized records.

    Mutates `records` in place. Their known-state is untouched (it lives
    in a separate top-level slot, `state_dict["known"]`, not in `records`
    at all) — forgetting the details of someone is not the same as never
    having met them.

    Args:
        records: The serialized `CharacterState.records` mapping.
        character_id: The character to clear.
    """
    records.pop(character_id, None)


def set_attribute(state: CharacterState, character_id: str, attribute: str, value: AttributeValue) -> CharacterState:
    """Set one attribute on one character.

    Args:
        state: The session's current CharacterState.
        character_id: The character the fact is about.
        attribute: The attribute name.
        value: The value to store.

    Returns:
        A new CharacterState reflecting the change — never mutates
        `state`, matching every other plugin's own contract.
    """
    updated = {other: {"attributes": dict(record.get("attributes", {}))} for other, record in state.records.items()}
    updated.setdefault(character_id, {"attributes": {}})["attributes"][attribute] = value
    return CharacterState(records=updated, known=set(state.known))


def read_attribute(state: CharacterState, character_id: str, attribute: str, default: AttributeValue = False) -> AttributeValue:
    """Return one attribute's value, or `default` if it was never set.

    Args:
        state: The session's current CharacterState.
        character_id: The character being asked about.
        attribute: The attribute name.
        default: What to return when the attribute has never been set.
            Defaults to False, since the commonest use is a story flag
            whose absence means "this has not happened".

    Returns:
        The stored value, or `default`.
    """
    return state.records.get(character_id, {}).get("attributes", {}).get(attribute, default)


def does_attribute_exist(state: CharacterState, character_id: str, attribute: str) -> bool:
    """Return whether an attribute has ever been set on a character.

    Distinct from `read_attribute()` returning a falsey value: a flag
    explicitly set to False is not the same as one never set at all, and
    a story that needs to tell those apart needs this.

    Args:
        state: The session's current CharacterState.
        character_id: The character being asked about.
        attribute: The attribute name.

    Returns:
        True if the attribute is present, whatever its value.
    """
    return attribute in state.records.get(character_id, {}).get("attributes", {})


def clear_all_attributes(state: CharacterState, character_id: str) -> CharacterState:
    """Remove every attribute from one character.

    Args:
        state: The session's current CharacterState.
        character_id: The character to clear.

    Returns:
        A new CharacterState with that character's attributes removed.
        Their known-state is untouched: forgetting the details of someone
        is not the same as never having met them.
    """
    updated = {other: {"attributes": dict(record.get("attributes", {}))} for other, record in state.records.items() if other != character_id}
    return CharacterState(records=updated, known=set(state.known))


def character_is_known(state: CharacterState, character_id: str) -> bool:
    """Return whether the player has met this character.

    Args:
        state: The session's current CharacterState.
        character_id: The character being asked about.

    Returns:
        True once `set_known()` has been called for them.
    """
    return character_id in state.known


def set_known(state: CharacterState, character_id: str) -> CharacterState:
    """Mark a character as met.

    Args:
        state: The session's current CharacterState.
        character_id: The character now known.

    Returns:
        A new CharacterState including them.
    """
    return CharacterState(
        records={other: {"attributes": dict(r.get("attributes", {}))} for other, r in state.records.items()}, known=state.known | {character_id}
    )


def set_unknown(state: CharacterState, character_id: str) -> CharacterState:
    """Mark a character as not met.

    The inverse of `set_known()`, for a story that can take a meeting
    back — an erased memory, a mistaken identity. Mirrors
    `location_graph.mark_unknown()`, which exists for the same reason.

    Args:
        state: The session's current CharacterState.
        character_id: The character to forget.

    Returns:
        A new CharacterState without them.
    """
    return CharacterState(
        records={other: {"attributes": dict(r.get("attributes", {}))} for other, r in state.records.items()}, known=state.known - {character_id}
    )


def known_characters(state: CharacterState) -> list[str]:
    """Return every character the player has met.

    Args:
        state: The session's current CharacterState.

    Returns:
        The known character ids, sorted for a stable answer.
    """
    return sorted(state.known)


def current_location_of(occupancy_state: dict[str, Any], character_id: str) -> str:
    """Return where a character is, read from the occupancy store.

    **This module stores no location.** The function exists so a story can
    ask every question about a character through one vocabulary, while the
    answer still comes from the single plugin that owns it. Written to
    take the occupancy plugin's own serialized state so this module needs
    no import of it — the two share only the convention that a location is
    a plain string.

    Args:
        occupancy_state: The session's serialized occupancy state, in
            `character_occupancy.OccupancyState.to_dict()` shape.
        character_id: The character being asked about.

    Returns:
        The character's location id, or "" when they are nowhere —
        matching the empty-string convention a story's own bindings use,
        since Ink has no None.
    """
    return occupancy_state.get("locations", {}).get(character_id, "")


# Places accumulate exactly the same kind of small keyed state characters
# do -- "is this door open", "has this shelf been read" -- and the storage
# is identical, so the functions above serve both rather than existing
# twice under two names (no-duplicated-logic). `PLACES_KEY` is the id
# space a story uses for place attributes; it is only a convention, since
# `set_attribute()` never inspects the id it is given.
#
# A story keeps them in a separate state slot from its characters, so a
# place and a character sharing a name cannot collide.


def _init_character_state() -> dict[str, Any]:
    """Return a brand-new game's own fresh CharacterState, serialized.

    Returns:
        `CharacterState().to_dict()` — nobody known, no attributes set.
    """
    return CharacterState().to_dict()


def _bind_character_state(state_dict: dict[str, Any], readable: dict[str, dict[str, Any]]) -> dict[str, Callable[..., Any]]:
    """Build this session's character bindings.

    Args:
        state_dict: This session's own serialized `CharacterState`, read
            fresh on every call and overwritten in place by any write.
        readable: The other plugins' state this API reads but does not
            own, keyed by state slot — see `EngineAPIDescriptor.also_reads`.
            Used only for the delegating accessors, never written to.

    Returns:
        The bindings dict for the Ink function names a story calls.
    """

    def set_attribute_now(character_id: str, attribute: str, value: AttributeValue) -> int:
        """EXTERNAL set_attribute_now(character_id, attribute, value) --
        store one fact about one character. Returns 1 (Ink has no void
        EXTERNAL return)."""
        set_attribute_in(state_dict.setdefault("records", {}), character_id, attribute, value)
        return 1

    def read_attribute_now(character_id: str, attribute: str) -> AttributeValue:
        """EXTERNAL read_attribute_now(character_id, attribute) -- the
        stored value, or false when never set."""
        return read_attribute_in(state_dict.setdefault("records", {}), character_id, attribute)

    def does_attribute_exist_now(character_id: str, attribute: str) -> bool:
        """EXTERNAL does_attribute_exist_now(character_id, attribute) --
        whether it was ever set, regardless of value."""
        return does_attribute_exist_in(state_dict.setdefault("records", {}), character_id, attribute)

    def clear_all_attributes_now(character_id: str) -> int:
        """EXTERNAL clear_all_attributes_now(character_id) -- forget every
        attribute on one character, keeping their known-state. Returns 1."""
        clear_all_attributes_in(state_dict.setdefault("records", {}), character_id)
        return 1

    def character_known_now(character_id: str) -> bool:
        """EXTERNAL character_known_now(character_id) -- has the player
        met them. Named to mirror `location_graph`'s own
        `location_known_now`/`set_location_known_now` pair exactly (same
        known/unknown axis, same getter-plus-one-boolean-setter shape),
        the established naming convention every other engine-plugin API
        in this corpus follows."""
        return is_known_in(state_dict, character_id)

    def set_character_known_now(character_id: str, known: bool) -> int:
        """EXTERNAL set_character_known_now(character_id, known) -- mark
        met (known=true) or not met (known=false). Returns 1. One setter
        taking a boolean, matching `set_location_known_now`'s own shape,
        rather than two separate mark/unmark functions."""
        set_known_in(state_dict, character_id, known)
        return 1

    def current_location_now(character_id: str) -> str:
        """EXTERNAL current_location_now(character_id) -- where they are.
        Reads the occupancy store, which owns this fact; this API stores
        no location of its own."""
        return current_location_of(readable.get("character_occupancy", {}), character_id)

    return {
        "set_attribute_now": set_attribute_now,
        "read_attribute_now": read_attribute_now,
        "does_attribute_exist_now": does_attribute_exist_now,
        "clear_all_attributes_now": clear_all_attributes_now,
        "character_known_now": character_known_now,
        "set_character_known_now": set_character_known_now,
        "current_location_now": current_location_now,
    }


# The real plugin-discovery contract (interactive_fiction/engine_api.py).
# `also_reads` names the slots this API answers from but never writes —
# the mechanism that lets a character be the one thing a story asks,
# without this module becoming a second home for another plugin's state.
API = EngineAPIDescriptor(
    name="characters",
    display_name="Characters",
    state_key="characters",
    init_state=_init_character_state,
    bind_stateful=_bind_character_state,
    also_reads=("character_occupancy",),
)

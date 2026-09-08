"""InventorySystem: a generic item-placement and holder-inventory framework.

A reusable engine service ANY story's own conversion builds its specific
item system on top of — never one specific game's own implementation. This
module has zero knowledge of what any item IS: an item is a plain string id
the game layer chooses, and this module only ever tracks where it is and
who has it. No item names, no display text, no prices, no currency, no
per-item behaviour, and no concept of what a "spell" or a "key" might mean
live here; all of that belongs in the game's own bridge module inside its
game folder.

**Two things are tracked, and they are mutually exclusive per item:**

1. **World placement** — `item_locations` maps an item to the location it
   is lying in. An item held by someone is not in the world, so its entry
   is dropped from that map rather than set to a sentinel.
2. **Holder inventories** — `holder_items` maps a holder to the items it
   carries and how many of each.

A "holder" is any opaque id string. The game layer decides what holders
exist: the player, an NPC, a chest, a body being possessed. This module
never distinguishes between them, which is what makes give-to-a-person,
take-from-a-person, and put-in-a-container the same operation.

**Counts, not sets.** Most stories only ever ask "is this held?", which
`has_item()` answers. But an item with limited uses needs a real number,
and retrofitting counts onto a set-based store later would mean changing
every call site — so the store is `{item_id: count}` from the start and
the boolean case is simply a count of 1.

**Capacity is a real mechanic.** A holder may declare a maximum number of
DISTINCT items (adding more of something already held never trips it).
`give_item` raises `InventoryFullError` rather than silently dropping the
item, so a game can reproduce its own refusal behaviour — including the
common one of leaving the item on the floor instead of destroying it.

Per-session isolation: every function here is a pure function of its own
explicit arguments — no instance attributes, no shared/module-level state,
and no function mutates the state it is given. `InventoryState` is a
plain, JSON-safe dataclass meant to round-trip through a session's own
serialized state, exactly like `SkillState`/`SchedulingState`/
`LocationGraphState`/`OccupancyState`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------
# Tunable limits
#
# Every bound this module enforces is a constant here, so raising or
# lowering one is a single edit rather than a hunt through call sites.
# --------------------------------------------------------------------------

#: A limit value meaning "no limit at all". Used for both stack size and
#: slot count, so a caller never has to remember which sentinel goes where.
UNLIMITED = 0

#: How many units of ONE item a holder may keep in its slot, when the game
#: layer sets nothing. Configurable per holder via `set_stack_limit()`.
DEFAULT_STACK_LIMIT = 25

#: The hardest ceiling this API will accept for a stack. A game asking for
#: more than this is rejected rather than quietly clamped, so a typo like
#: 2000 surfaces as an error instead of silently becoming something else.
#: Raising it is a one-line change here.
MAX_STACK_LIMIT = 100

#: How many DISTINCT items a holder may carry when the game layer sets
#: nothing. `UNLIMITED` keeps the pre-existing behaviour: a holder with no
#: capacity set is uncapped until a game says otherwise.
DEFAULT_SLOT_LIMIT = UNLIMITED

#: How many items one WORN slot holds when the game layer declares no
#: capacity for it. One is the ordinary case (a neck holds one necklace);
#: a game wanting two rings on one hand declares `{"finger": 2}` rather
#: than inventing a second slot name.
DEFAULT_WORN_SLOT_CAPACITY = 1

#: The hardest ceiling this API accepts for a worn slot's capacity, same
#: guard shape as MAX_STACK_LIMIT: rejected, never clamped.
MAX_WORN_SLOT_CAPACITY = 100


class InventoryError(Exception):
    """Base class for this module's own explicit, closed failure modes."""


class InventoryFullError(InventoryError):
    """A holder already carries its maximum number of distinct items.

    Raised rather than silently no-op'ing so the game layer can tell
    "can't take this, hands full" apart from "can't take this, it isn't
    here" — two outcomes a story usually narrates differently.
    """


class StackFullError(InventoryError):
    """One item's slot is already at its stack limit.

    Deliberately NOT the same error as `InventoryFullError`: "you cannot
    carry any more stones" and "your hands are full" are different
    refusals, and a story usually narrates them differently. A holder can
    hit this with slots still free.
    """


class InvalidLimitError(InventoryError):
    """A caller asked for a limit this API will not accept.

    Raised rather than clamping, so a typo (a stack of 2000 where 20 was
    meant) surfaces immediately instead of silently becoming
    MAX_STACK_LIMIT.
    """


class ItemNotHeldError(InventoryError):
    """A holder was asked to give up an item it does not have enough of.

    Covers both "does not hold it at all" and "holds fewer than the count
    asked for", since a story's narration for the two is the same: the
    transfer does not happen.
    """


class SlotOccupiedError(InventoryError):
    """A worn slot is already full.

    Distinct from `InventoryFullError` for the same reason
    `StackFullError` is: "you are already wearing a necklace" and "your
    hands are full" are different refusals a story narrates differently.
    """


class ContainerClosedError(InventoryError):
    """A container was reached into while shut.

    Raised for taking from a closed container whether or not its contents
    are visible — a transparent container shows what is inside but still
    has to be opened before anything can come out.
    """


@dataclass(frozen=True)
class ContainerSpec:
    """What makes one holder a container rather than an ordinary holder.

    Frozen so `_copied()` can share spec objects between states without a
    mutation to one state's container leaking into another's.

    Marking containers explicitly, rather than inferring them from holding
    something, follows the unanimous prior art in interactive-fiction
    world models (Inform 7, TADS 3, IntFicPy, Tale): a container is a KIND
    of thing with its own either/or properties, not a location and not
    merely "a holder that happens to have contents".

    Args:
        openable: Whether the container can be opened and shut at all.
            Defaults False, meaning permanently open — Inform's own
            default, so declaring an ordinary always-open container costs
            nothing.
        is_open: Whether it is open right now. Meaningless unless
            `openable`; a non-openable container is always treated as
            open.
        transparent: Whether its contents can be SEEN while shut. A
            transparent container shows what is inside but still has to be
            opened before anything can be taken out.
        expires_when_empty: Whether the declaration is dropped the moment
            it holds nothing — a wrapper only ever emptied, never
            refilled (a gift package, a burst pod). `is_container()`
            answers False for it from then on, as if never declared.
    """

    openable: bool = False
    is_open: bool = True
    transparent: bool = False
    expires_when_empty: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain, JSON-safe dict.

        Returns:
            A dict safe to store inside a session's own serialized state.
        """
        return {
            "openable": self.openable,
            "is_open": self.is_open,
            "transparent": self.transparent,
            "expires_when_empty": self.expires_when_empty,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContainerSpec":
        """Rebuild from a `to_dict()` result.

        Args:
            data: A previously serialized spec. Missing keys fall back to
                the field defaults.

        Returns:
            The rebuilt ContainerSpec.
        """
        return cls(
            openable=bool(data.get("openable", False)),
            is_open=bool(data.get("is_open", True)),
            transparent=bool(data.get("transparent", False)),
            expires_when_empty=bool(data.get("expires_when_empty", False)),
        )

    def accepts_reach(self) -> bool:
        """Return whether anything can be taken out right now.

        Returns:
            True when the container is open, or not openable at all.
        """
        return self.is_open or not self.openable

    def reveals_contents(self) -> bool:
        """Return whether the contents are visible right now.

        Returns:
            True when reachable, or when shut but transparent.
        """
        return self.accepts_reach() or self.transparent


@dataclass
class InventoryState:
    """A session's own item placements and per-holder inventories.

    Args:
        item_locations: item_id -> location_id, for items lying in the
            world. An item currently held by someone has NO entry here —
            being held and being on the ground are mutually exclusive, and
            an absent key says that unambiguously where a `None` value
            would not.
        holder_items: holder_id -> {item_id: count}. A holder is any
            opaque id the game layer chooses — the player, an NPC, or a
            container. Counts are always >= 1; an item reaching 0 is
            removed from the inner dict rather than left as a zero entry,
            so `has_item()` and `holder_items()` never disagree.
        capacities: holder_id -> maximum number of DISTINCT items, or
            None for unlimited. A holder with no entry is unlimited.
        stack_limits: holder_id -> how many units of ONE item fit in its
            slot. A holder with no entry uses DEFAULT_STACK_LIMIT. This is
            a property of the SLOT, not of the item: one value applies to
            everything that holder carries, rather than each item kind
            declaring its own.
        containers: holder_id -> ContainerSpec, for holders that are
            containers. A holder with no entry is an ordinary holder and
            behaves exactly as it did before containers existed.
        worn: holder_id -> slot_name -> [item_id, ...]. Slot names are
            chosen by the game layer and are opaque here, exactly like
            item ids. Nested by slot rather than kept as a flat set
            because the slot IS the constraint — what blocks a wear is
            answerable without consulting the game's catalog. A worn item
            stays in `holder_items` too: wearing requires holding, so
            "do you have it" keeps one home.
        worn_slot_capacities: slot_name -> how many items that slot holds.
            Global to the state rather than per-holder, because a slot's
            capacity is a fact about the game's anatomy ("a neck holds one
            necklace"), not about who is wearing it. A slot with no entry
            uses DEFAULT_WORN_SLOT_CAPACITY.
    """

    item_locations: dict[str, str] = field(default_factory=dict)
    holder_items: dict[str, dict[str, int]] = field(default_factory=dict)
    capacities: dict[str, int | None] = field(default_factory=dict)
    stack_limits: dict[str, int] = field(default_factory=dict)
    containers: dict[str, ContainerSpec] = field(default_factory=dict)
    worn: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    worn_slot_capacities: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain, JSON-safe dict.

        Returns:
            A dict safe to store inside a session's own serialized state.
        """
        return {
            "item_locations": dict(self.item_locations),
            "holder_items": {holder_id: dict(items) for holder_id, items in self.holder_items.items()},
            "capacities": dict(self.capacities),
            "stack_limits": dict(self.stack_limits),
            "containers": {holder_id: spec.to_dict() for holder_id, spec in self.containers.items()},
            "worn": {holder_id: {slot: list(items) for slot, items in slots.items()} for holder_id, slots in self.worn.items()},
            "worn_slot_capacities": dict(self.worn_slot_capacities),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InventoryState":
        """Rebuild from a `to_dict()` result.

        Args:
            data: A previously serialized state. Missing keys are
                tolerated and rebuilt empty, so an older saved state that
                predates a field still loads.

        Returns:
            The rebuilt InventoryState.
        """
        raw_holders = data.get("holder_items") or {}
        raw_containers = data.get("containers") or {}
        raw_worn = data.get("worn") or {}
        return cls(
            item_locations=dict(data.get("item_locations") or {}),
            holder_items={holder_id: dict(items) for holder_id, items in raw_holders.items()},
            capacities=dict(data.get("capacities") or {}),
            stack_limits=dict(data.get("stack_limits") or {}),
            containers={holder_id: ContainerSpec.from_dict(spec) for holder_id, spec in raw_containers.items()},
            worn={holder_id: {slot: list(items) for slot, items in slots.items()} for holder_id, slots in raw_worn.items()},
            worn_slot_capacities=dict(data.get("worn_slot_capacities") or {}),
        )


# Serialized-state operations, for the binding layer (2026-09-04, mirroring
# `character_occupancy.py`/`scheduling.py`'s own established `_in`-suffixed
# pattern). `InventoryState.from_dict()` rebuilds all 7 fields — including a
# nested comprehension for `worn` and a `ContainerSpec.from_dict()` call per
# container — the most expensive reconstruction of the state systems this
# pattern has been applied to, yet a plain presence/count/location read
# only ever touches ONE field. Real corpus hot spots confirmed: ASFA's
# `your_kitchen` calls `has_item_now` 14 times in one knot, `wild_ranges`
# 11, several more knots 8-10 times; 212 total `has_item_now` call sites
# corpus-wide.


def item_location_in(item_locations: dict[str, str], item_id: str) -> str | None:
    """Return the location an item is lying in, from a serialized item_locations dict.

    Args:
        item_locations: The serialized `InventoryState.item_locations` mapping.
        item_id: The item to look up.

    Returns:
        The location id, or None when the item is held or not in play.
    """
    return item_locations.get(item_id)


def item_count_in(holder_items: dict[str, dict[str, int]], holder_id: str, item_id: str) -> int:
    """Return how many of an item a holder carries, from a serialized holder_items dict.

    Args:
        holder_items: The serialized `InventoryState.holder_items` mapping.
        holder_id: The holder to check.
        item_id: The item to count.

    Returns:
        The count, or 0 when the holder has none.
    """
    return holder_items.get(holder_id, {}).get(item_id, 0)


def has_item_in(holder_items: dict[str, dict[str, int]], holder_id: str, item_id: str) -> bool:
    """Return whether a holder has at least one of an item, from a serialized holder_items dict.

    Args:
        holder_items: The serialized `InventoryState.holder_items` mapping.
        holder_id: The holder to check.
        item_id: The item to look for.

    Returns:
        True when the holder carries one or more.
    """
    return item_count_in(holder_items, holder_id, item_id) > 0


def item_holder_in(holder_items: dict[str, dict[str, int]], item_id: str) -> str | None:
    """Return which holder currently carries an item, from a serialized holder_items dict.

    Args:
        holder_items: The serialized `InventoryState.holder_items` mapping.
        item_id: The item to trace.

    Returns:
        The holder id, or None when the item is on the ground or out of play.
    """
    for holder_id, items in holder_items.items():
        if items.get(item_id, 0) > 0:
            return holder_id
    return None


def items_at_location_in(item_locations: dict[str, str], location_id: str) -> frozenset[str]:
    """Return every item lying at a location, from a serialized item_locations dict.

    Args:
        item_locations: The serialized `InventoryState.item_locations` mapping.
        location_id: The location to inspect.

    Returns:
        The item ids lying there — held items are never included.
    """
    return frozenset(item_id for item_id, where in item_locations.items() if where == location_id)


def held_items_in(holder_items: dict[str, dict[str, int]], holder_id: str) -> dict[str, int]:
    """Return everything a holder carries, from a serialized holder_items dict.

    Args:
        holder_items: The serialized `InventoryState.holder_items` mapping.
        holder_id: The holder to inspect.

    Returns:
        A copy of {item_id: count} — mutating it never affects the caller's own dict.
    """
    return dict(holder_items.get(holder_id, {}))


def stack_limit_in(stack_limits: dict[str, int], holder_id: str) -> int:
    """Return how many units of one item this holder may stack, from a serialized stack_limits dict.

    Args:
        stack_limits: The serialized `InventoryState.stack_limits` mapping.
        holder_id: The holder to inspect.

    Returns:
        The limit, or `DEFAULT_STACK_LIMIT` when the holder has none set.
    """
    return stack_limits.get(holder_id, DEFAULT_STACK_LIMIT)


def _copied(state: InventoryState) -> InventoryState:
    """Return a deep-enough copy of `state` for a single mutation.

    Args:
        state: The state to copy.

    Returns:
        A new InventoryState whose nested dicts are fresh, so mutating the
        copy can never write through to the caller's own state.
    """
    return InventoryState(
        item_locations=dict(state.item_locations),
        holder_items={holder_id: dict(items) for holder_id, items in state.holder_items.items()},
        capacities=dict(state.capacities),
        stack_limits=dict(state.stack_limits),
        containers=dict(state.containers),
        worn={holder_id: {slot: list(items) for slot, items in slots.items()} for holder_id, slots in state.worn.items()},
        worn_slot_capacities=dict(state.worn_slot_capacities),
    )


# --------------------------------------------------------------------------
# World placement
# --------------------------------------------------------------------------


def place_item(state: InventoryState, item_id: str, location_id: str) -> InventoryState:
    """Put an item down at a location, taking it from whoever held it.

    Args:
        state: The session's current InventoryState.
        item_id: The item to place.
        location_id: Where it now lies.

    Returns:
        A new InventoryState with the item at that location and held by
        nobody — this function never mutates `state` in place.
    """
    new_state = _copied(state)
    for items in new_state.holder_items.values():
        items.pop(item_id, None)
    new_state.item_locations[item_id] = location_id
    return new_state


def remove_from_world(state: InventoryState, item_id: str) -> InventoryState:
    """Remove an item from play entirely — no location, no holder.

    Args:
        state: The session's current InventoryState.
        item_id: The item to remove.

    Returns:
        A new InventoryState with the item nowhere. Removing an item that
        is already nowhere is not an error, so a story can call this
        unconditionally.
    """
    new_state = _copied(state)
    new_state.item_locations.pop(item_id, None)
    for items in new_state.holder_items.values():
        items.pop(item_id, None)
    return new_state


def item_location(state: InventoryState, item_id: str) -> str | None:
    """Return the location an item is lying in, if any.

    Args:
        state: The session's current InventoryState.
        item_id: The item to look up.

    Returns:
        The location id, or None when the item is held by someone or is
        not in play at all. Use `item_holder()` to tell those two apart.
    """
    return state.item_locations.get(item_id)


def items_at_location(state: InventoryState, location_id: str) -> frozenset[str]:
    """Return every item lying at a location.

    Args:
        state: The session's current InventoryState.
        location_id: The location to inspect.

    Returns:
        The item ids lying there — held items are never included.
    """
    return frozenset(item_id for item_id, where in state.item_locations.items() if where == location_id)


# --------------------------------------------------------------------------
# Holders (characters and containers alike)
# --------------------------------------------------------------------------


def set_capacity(state: InventoryState, holder_id: str, limit: int | None) -> InventoryState:
    """Set how many DISTINCT items a holder may carry.

    Args:
        state: The session's current InventoryState.
        holder_id: The holder to limit.
        limit: The maximum number of distinct items, or None for
            unlimited. Setting a limit below what the holder already
            carries is allowed and does not drop anything — it simply
            means no NEW distinct item can be added until something goes.

    Returns:
        A new InventoryState with the capacity applied.
    """
    new_state = _copied(state)
    new_state.capacities[holder_id] = limit
    return new_state


def capacity(state: InventoryState, holder_id: str) -> int | None:
    """Return a holder's distinct-item limit.

    Args:
        state: The session's current InventoryState.
        holder_id: The holder to inspect.

    Returns:
        The limit, or None when the holder is unlimited.
    """
    return state.capacities.get(holder_id)


def set_stack_limit(state: InventoryState, holder_id: str, limit: int) -> InventoryState:
    """Set how many units of ONE item fit in this holder's slot.

    The limit belongs to the slot, not the item: one value applies to
    everything the holder carries.

    Args:
        state: The session's current InventoryState.
        holder_id: The holder to limit.
        limit: Units per slot. `UNLIMITED` (0) for no limit, 1 to allow
            only a single unit, up to `MAX_STACK_LIMIT`. Lowering a limit
            below what is already stacked drops nothing — it simply means
            no more can be added until some is used.

    Returns:
        A new InventoryState with the limit applied.

    Raises:
        InvalidLimitError: `limit` is negative, or above MAX_STACK_LIMIT.
            Rejected rather than clamped so a typo surfaces as an error.
    """
    if limit < 0:
        raise InvalidLimitError(f"stack limit must be >= 0 ({UNLIMITED} means unlimited), got {limit}")
    if limit > MAX_STACK_LIMIT:
        raise InvalidLimitError(f"stack limit {limit} exceeds MAX_STACK_LIMIT ({MAX_STACK_LIMIT})")

    new_state = _copied(state)
    new_state.stack_limits[holder_id] = limit
    return new_state


def stack_limit(state: InventoryState, holder_id: str) -> int:
    """Return how many units of one item this holder may stack.

    Args:
        state: The session's current InventoryState.
        holder_id: The holder to inspect.

    Returns:
        The limit, or `DEFAULT_STACK_LIMIT` when the holder has none set.
        `UNLIMITED` (0) means no limit.
    """
    return state.stack_limits.get(holder_id, DEFAULT_STACK_LIMIT)


def _check_stack_room(state: InventoryState, holder_id: str, item_id: str, count: int) -> None:
    """Raise if adding `count` would overflow this holder's slot.

    Args:
        state: The session's current InventoryState.
        holder_id: The receiving holder.
        item_id: The item being added.
        count: How many units are being added.

    Raises:
        StackFullError: The resulting stack would exceed the limit. The
            slot is NOT topped up to the limit — the whole addition is
            refused, so the caller can leave the surplus where it was.
    """
    limit = stack_limit(state, holder_id)
    if limit == UNLIMITED:
        return
    if item_count(state, holder_id, item_id) + count > limit:
        raise StackFullError(
            f"holder '{holder_id}' cannot stack {count} more '{item_id}' " f"(has {item_count(state, holder_id, item_id)}, limit {limit})"
        )


def _capacity_load(state: InventoryState, holder_id: str) -> int:
    """Return how many distinct items count against a holder's capacity.

    Worn items are excluded, following the established convention in
    interactive-fiction world models that what you are wearing is not what
    you are carrying. A holder wearing nothing loads exactly as many items
    as it holds, so this is a no-op for any game that never uses slots.

    Args:
        state: The session's current InventoryState.
        holder_id: Whose load to measure.

    Returns:
        The number of distinct held items that are not currently worn.
    """
    held = state.holder_items.get(holder_id, {})
    if not held:
        return 0
    worn = worn_items(state, holder_id)
    return sum(1 for item_id in held if item_id not in worn)


def give_item(state: InventoryState, holder_id: str, item_id: str, count: int = 1) -> InventoryState:
    """Give a holder an item, taking it out of the world.

    Args:
        state: The session's current InventoryState.
        holder_id: Who receives it.
        item_id: What they receive.
        count: How many. Must be >= 1.

    Returns:
        A new InventoryState with the item held and no longer in the
        world.

    Raises:
        ValueError: `count` is less than 1.
        InventoryFullError: The holder is at its distinct-item capacity
            and this item would be a NEW distinct entry. Adding more of
            something already held never raises this, since it consumes
            no additional slot.
        StackFullError: The holder already has this item at its stack
            limit. This can happen with slots still free — the two
            refusals are independent.
    """
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")

    held = state.holder_items.get(holder_id, {})
    limit = state.capacities.get(holder_id)
    if limit is not None and item_id not in held and _capacity_load(state, holder_id) >= limit:
        raise InventoryFullError(f"holder '{holder_id}' already carries {_capacity_load(state, holder_id)} distinct item(s), its limit")
    _check_stack_room(state, holder_id, item_id, count)

    new_state = _copied(state)
    new_state.item_locations.pop(item_id, None)
    new_state.holder_items.setdefault(holder_id, {})
    new_state.holder_items[holder_id][item_id] = new_state.holder_items[holder_id].get(item_id, 0) + count
    return new_state


def take_item(state: InventoryState, holder_id: str, item_id: str, count: int = 1) -> InventoryState:
    """Take an item away from a holder, removing it from play.

    To move an item from one holder to another, use `transfer_item()`; to
    put it on the ground, use `place_item()`.

    Args:
        state: The session's current InventoryState.
        holder_id: Who loses it.
        item_id: What they lose.
        count: How many. Must be >= 1.

    Returns:
        A new InventoryState with the count reduced, and the item dropped
        from the holder's inventory entirely once it reaches zero.

    Raises:
        ValueError: `count` is less than 1.
        ItemNotHeldError: The holder does not hold at least `count` of it.
    """
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")
    if item_count(state, holder_id, item_id) < count:
        raise ItemNotHeldError(f"holder '{holder_id}' does not hold {count} of '{item_id}'")

    new_state = _copied(state)
    remaining = new_state.holder_items[holder_id][item_id] - count
    if remaining > 0:
        new_state.holder_items[holder_id][item_id] = remaining
    else:
        del new_state.holder_items[holder_id][item_id]
    return new_state


def has_item(state: InventoryState, holder_id: str, item_id: str) -> bool:
    """Return whether a holder has at least one of an item.

    The plain presence question, which is what most story conditions ask;
    `item_count()` answers the quantity question.

    Args:
        state: The session's current InventoryState.
        holder_id: The holder to check.
        item_id: The item to look for.

    Returns:
        True when the holder carries one or more.
    """
    return item_count(state, holder_id, item_id) > 0


def item_count(state: InventoryState, holder_id: str, item_id: str) -> int:
    """Return how many of an item a holder carries.

    Args:
        state: The session's current InventoryState.
        holder_id: The holder to check.
        item_id: The item to count.

    Returns:
        The count, or 0 when the holder has none.
    """
    return state.holder_items.get(holder_id, {}).get(item_id, 0)


def held_items(state: InventoryState, holder_id: str) -> dict[str, int]:
    """Return everything a holder carries.

    Args:
        state: The session's current InventoryState.
        holder_id: The holder to inspect.

    Returns:
        A copy of {item_id: count} — mutating it never affects `state`.
    """
    return dict(state.holder_items.get(holder_id, {}))


def item_holder(state: InventoryState, item_id: str) -> str | None:
    """Return which holder currently carries an item.

    Args:
        state: The session's current InventoryState.
        item_id: The item to trace.

    Returns:
        The holder id, or None when the item is on the ground or out of
        play. Where two holders somehow carry the same id, the first found
        is returned — the callers here never create that state, but a
        hand-built state could.
    """
    for holder_id, items in state.holder_items.items():
        if items.get(item_id, 0) > 0:
            return holder_id
    return None


# --------------------------------------------------------------------------
# Transfer — give-to and take-from a person are one operation
# --------------------------------------------------------------------------


def transfer_item(
    state: InventoryState,
    from_holder: str,
    to_holder: str,
    item_id: str,
    count: int = 1,
) -> InventoryState:
    """Move an item from one holder to another.

    Handing something over and taking something away are the same
    operation with the arguments swapped, so both directions of a story's
    give/take content route through this one call.

    Args:
        state: The session's current InventoryState.
        from_holder: Who gives it up.
        to_holder: Who receives it.
        item_id: What moves.
        count: How many. Must be >= 1.

    Returns:
        A new InventoryState with the item moved.

    Raises:
        ValueError: `count` is less than 1.
        ItemNotHeldError: `from_holder` does not hold enough of it. The
            state is left untouched.
        InventoryFullError: `to_holder` is at its distinct-item capacity.
        StackFullError: `to_holder` already has this item at its stack
            limit.

    In every failure case the state is left untouched — the giver does
    NOT lose the item, since both checks happen before anything is
    removed.
    """
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")
    if item_count(state, from_holder, item_id) < count:
        raise ItemNotHeldError(f"holder '{from_holder}' does not hold {count} of '{item_id}'")

    receiving = state.holder_items.get(to_holder, {})
    limit = state.capacities.get(to_holder)
    if limit is not None and item_id not in receiving and _capacity_load(state, to_holder) >= limit:
        raise InventoryFullError(f"holder '{to_holder}' already carries {_capacity_load(state, to_holder)} distinct item(s), its limit")
    _check_stack_room(state, to_holder, item_id, count)

    new_state = take_item(state, from_holder, item_id, count)
    new_state.holder_items.setdefault(to_holder, {})
    new_state.holder_items[to_holder][item_id] = new_state.holder_items[to_holder].get(item_id, 0) + count
    return new_state


# --------------------------------------------------------------------------
# Worn slots
#
# An OPTIONAL capability: slot names are chosen by the game layer and are
# opaque here, exactly like item ids. A game that declares no slots simply
# never wears anything, and every function below is inert for it.
# --------------------------------------------------------------------------


def set_worn_slot_capacity(state: InventoryState, slot: str, slot_capacity: int) -> InventoryState:
    """Declare how many items one worn slot holds.

    Args:
        state: The session's current InventoryState.
        slot: The game's own slot name.
        slot_capacity: How many items fit. Must be >= 1 and no greater
            than MAX_WORN_SLOT_CAPACITY.

    Returns:
        A new InventoryState with the capacity recorded.

    Raises:
        InvalidLimitError: `slot_capacity` is below 1 or above
            MAX_WORN_SLOT_CAPACITY. Rejected rather than clamped, so a
            typo surfaces instead of silently becoming something else.
            Zero is rejected too: a slot holding everything is not a
            constraint, so UNLIMITED is meaningless here.
    """
    if slot_capacity < 1 or slot_capacity > MAX_WORN_SLOT_CAPACITY:
        raise InvalidLimitError(f"worn slot capacity must be 1..{MAX_WORN_SLOT_CAPACITY}, got {slot_capacity}")
    new_state = _copied(state)
    new_state.worn_slot_capacities[slot] = slot_capacity
    return new_state


def worn_slot_capacity(state: InventoryState, slot: str) -> int:
    """Return how many items a worn slot holds.

    Args:
        state: The session's current InventoryState.
        slot: The slot name to look up.

    Returns:
        The declared capacity, or DEFAULT_WORN_SLOT_CAPACITY when the game
        has not declared one for this slot.
    """
    return state.worn_slot_capacities.get(slot, DEFAULT_WORN_SLOT_CAPACITY)


def wear_item(state: InventoryState, holder_id: str, item_id: str, slot: str) -> InventoryState:
    """Put a held item on, into one of the game's own worn slots.

    Wearing requires holding: the item stays in `holder_items` and is
    additionally recorded as worn, so "do you have it" keeps one home and
    the capacity exemption has something to exempt.

    Args:
        state: The session's current InventoryState.
        holder_id: Who is putting it on.
        item_id: What they are putting on.
        slot: Which of the game's slots it occupies.

    Returns:
        A new InventoryState with the item worn. Wearing something already
        worn in that slot is idempotent rather than an error.

    Raises:
        ItemNotHeldError: The holder does not have the item.
        SlotOccupiedError: The slot is already at its capacity. The state
            is left untouched — nothing is displaced to make room, since
            which item to remove is the story's decision, not this
            module's.
    """
    if not has_item(state, holder_id, item_id):
        raise ItemNotHeldError(f"holder '{holder_id}' does not hold '{item_id}'")

    occupants = state.worn.get(holder_id, {}).get(slot, [])
    if item_id in occupants:
        return _copied(state)
    if len(occupants) >= worn_slot_capacity(state, slot):
        raise SlotOccupiedError(f"slot '{slot}' on holder '{holder_id}' already holds {len(occupants)} item(s), its capacity")

    new_state = _copied(state)
    new_state.worn.setdefault(holder_id, {})
    new_state.worn[holder_id].setdefault(slot, [])
    new_state.worn[holder_id][slot].append(item_id)
    return new_state


def remove_worn_item(state: InventoryState, holder_id: str, item_id: str) -> InventoryState:
    """Take a worn item off, leaving it held.

    Args:
        state: The session's current InventoryState.
        holder_id: Who is taking it off.
        item_id: What they are taking off.

    Returns:
        A new InventoryState with the item no longer worn. Taking off
        something that was not worn is not an error — the end state the
        caller asked for is already true.
    """
    new_state = _copied(state)
    slots = new_state.worn.get(holder_id)
    if not slots:
        return new_state
    for slot, occupants in list(slots.items()):
        if item_id in occupants:
            remaining = [worn_id for worn_id in occupants if worn_id != item_id]
            if remaining:
                slots[slot] = remaining
            else:
                del slots[slot]
    if not slots:
        del new_state.worn[holder_id]
    return new_state


def is_worn(state: InventoryState, holder_id: str, item_id: str) -> bool:
    """Return whether a holder is currently wearing an item.

    Args:
        state: The session's current InventoryState.
        holder_id: Whose worn items to check.
        item_id: The item in question.

    Returns:
        True when the item occupies any of that holder's slots.
    """
    return item_id in worn_items(state, holder_id)


def worn_items(state: InventoryState, holder_id: str) -> frozenset[str]:
    """Return everything a holder is wearing, across all slots.

    Args:
        state: The session's current InventoryState.
        holder_id: Whose worn items to list.

    Returns:
        Every worn item id. Empty for a holder wearing nothing, which is
        every holder in a game that declares no slots.
    """
    slots = state.worn.get(holder_id)
    if not slots:
        return frozenset()
    return frozenset(item_id for occupants in slots.values() for item_id in occupants)


def worn_in_slot(state: InventoryState, holder_id: str, slot: str) -> tuple[str, ...]:
    """Return what occupies one of a holder's worn slots.

    Args:
        state: The session's current InventoryState.
        holder_id: Whose slot to inspect.
        slot: Which slot.

    Returns:
        The occupying item ids in the order they were put on. Empty when
        the slot is free.
    """
    return tuple(state.worn.get(holder_id, {}).get(slot, ()))

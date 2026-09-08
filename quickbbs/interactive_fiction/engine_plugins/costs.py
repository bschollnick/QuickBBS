"""CostTable: what an action costs, and whether it can be afforded.

A game charges for things — mana for a spell, time for a turn, money for
a purchase — and the amount usually depends on circumstance: a first cast
is cheaper than the rest, a skill discounts a whole category, one route
takes longer than another. Without somewhere to put that, those numbers
end up spread across the story's own content as literals, and the same
cost is then written in several places that drift apart.

This module is that somewhere. A story declares its costs as config; this
plugin holds them and answers `cost_of(...)`. It knows nothing about mana,
minutes or money: a cost has a RESOURCE name (a plain string the game
chooses) and an AMOUNT, and what those mean is entirely the game's.

**Lookup, not charging.** This plugin does not debit anything. The
resources a game spends live in whichever plugin owns them — a clock in
`scheduling`, a currency in the game's own module — and a `pay()` here
would have to reach into all of them, coupling three systems to save one
call. The caller looks the cost up and spends it through whatever owns
that resource.

**Variants** are how a conditional cost stays data. A cost may declare
named alternatives — `{"amount": 20, "variants": {"first": 10}}` — and
the caller names one when the condition holds. The condition itself stays
where it belongs (a character attribute, a skill, a quest stage); this
plugin only holds the number that goes with it. That keeps a cost table
from growing a rules engine, which is the failure mode it exists to
prevent.

Per-session isolation: every function is a pure function of its explicit
arguments. `CostTableState` is a plain, JSON-safe dataclass that
round-trips through a session's own serialized state like every other
plugin's.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from interactive_fiction.engine_api import EngineAPIDescriptor
from interactive_fiction.engine_config_schemas import validate_cost_table

# The state slot this API owns, named as a module constant because a
# dependent API names it in its own `also_reads`.
STATE_KEY = "cost_table"


@dataclass
class CostTableState:
    """A session's cost table.

    Held in session state rather than read from config on each lookup so
    a story can adjust a cost mid-game — a discount earned, a price that
    rises — without the table and the config disagreeing about which is
    authoritative.

    Args:
        costs: cost key -> that cost's declaration, exactly as the config
            gave it: `{"resource": str, "amount": number, "variants":
            {name: number}}`. A key absent from here has no declared
            cost, which `cost_of()` reports as the caller's own default
            rather than as an error — a story may ask about an action it
            has not priced.
    """

    costs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain, JSON-safe dict.

        Returns:
            A dict safe to store inside a session's own serialized state.
        """
        return {"costs": {key: dict(cost) for key, cost in sorted(self.costs.items())}}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CostTableState":
        """Rebuild from a to_dict() result.

        Args:
            data: A to_dict() result.

        Returns:
            The rebuilt CostTableState.
        """
        return cls(costs={key: dict(cost) for key, cost in data.get("costs", {}).items()})


def initial_state(config: dict[str, Any]) -> CostTableState:
    """Build the starting CostTableState for a new session.

    Args:
        config: The story's own `cost_table` config (already validated by
            `engine_config_schemas.validate_cost_table()`).

    Returns:
        A CostTableState holding every declared cost.
    """
    return CostTableState(costs={key: dict(cost) for key, cost in config.get("costs", {}).items()})


def cost_of(state: CostTableState, key: str, variant: str = "", default: float = 0) -> float:
    """Return what an action costs right now.

    Args:
        state: The session's current CostTableState.
        key: The cost's key, as the story declared it.
        variant: A named alternative to prefer — the caller names one when
            its condition holds ("first" for a first cast, say). Falls
            back to the base amount when the variant is not declared, so a
            caller may always pass its variant without checking whether
            this particular cost has one.
        default: What to return for a key the story never declared.

    Returns:
        The amount, or `default`.
    """
    cost = state.costs.get(key)
    if cost is None:
        return default
    if variant:
        amount = cost.get("variants", {}).get(variant)
        if amount is not None:
            return amount
    return cost.get("amount", default)


def resource_of(state: CostTableState, key: str, default: str = "") -> str:
    """Return which resource an action is paid in.

    Args:
        state: The session's current CostTableState.
        key: The cost's key.
        default: What to return for an undeclared key.

    Returns:
        The resource name the story declared, or `default`.
    """
    cost = state.costs.get(key)
    return cost.get("resource", default) if cost else default


def can_afford(state: CostTableState, key: str, available: float, variant: str = "") -> bool:
    """Return whether `available` covers this cost.

    The comparison, so every caller asks it the same way rather than each
    writing its own `>=` against a literal. The caller supplies what it
    has, since this plugin holds no resource of its own.

    Args:
        state: The session's current CostTableState.
        key: The cost's key.
        available: How much of the resource the caller currently holds.
        variant: A named alternative to prefer, as `cost_of()`.

    Returns:
        True if `available` is at least the cost. True for an undeclared
        key, which costs nothing.
    """
    return available >= cost_of(state, key, variant)


def set_cost(state: CostTableState, key: str, resource: str, amount: float) -> CostTableState:
    """Return `state` with one cost declared or changed.

    For a price that moves during play. Declaring a cost that did not
    exist is allowed: a story may price an action only once it becomes
    available.

    Args:
        state: The session's current CostTableState.
        key: The cost's key.
        resource: What the cost is paid in.
        amount: The new base amount. Any variants already declared for
            this key are kept.

    Returns:
        A new CostTableState.
    """
    updated = {existing: dict(cost) for existing, cost in state.costs.items()}
    cost = updated.setdefault(key, {})
    cost["resource"] = resource
    cost["amount"] = amount
    return CostTableState(costs=updated)


# Serialized-state reads, for the binding layer.
#
# A binding holds this session's table as its serialized dict and is asked
# one cost per call. Rebuilding a CostTableState for each would copy every
# declared cost to answer one lookup, which is the pattern the other
# plugins' `*_in` functions exist to avoid.


def cost_of_in(state_dict: dict[str, Any], key: str, variant: str = "", default: float = 0) -> float:
    """Return an action's cost, from serialized state.

    Args:
        state_dict: This session's own serialized CostTableState.
        key: The cost's key.
        variant: A named alternative to prefer.
        default: What to return for an undeclared key.

    Returns:
        The amount, or `default`.
    """
    cost = state_dict.get("costs", {}).get(key)
    if cost is None:
        return default
    if variant:
        amount = cost.get("variants", {}).get(variant)
        if amount is not None:
            return amount
    return cost.get("amount", default)


def set_cost_in(state_dict: dict[str, Any], key: str, resource: str, amount: float) -> None:
    """Declare or change one cost, in serialized state.

    Mutates `state_dict` in place: the binding layer's dict IS the
    session's live state, so a write here is already persisted when the
    turn ends.

    Args:
        state_dict: This session's own serialized CostTableState.
        key: The cost's key.
        resource: What the cost is paid in.
        amount: The new base amount.
    """
    cost = state_dict.setdefault("costs", {}).setdefault(key, {})
    cost["resource"] = resource
    cost["amount"] = amount


def _init_cost_table_state() -> dict[str, Any]:
    """Return a brand-new session's own, empty cost table.

    Empty rather than config-derived: `EngineAPIDescriptor.init_state`
    takes no arguments, so it cannot see the story's config. A story
    builds its real starting table with `initial_state(config)` from its
    own initializer.

    Returns:
        A JSON-safe dict with no costs declared.
    """
    return CostTableState().to_dict()


def _bind_cost_table_state(state_dict: dict[str, Any]) -> dict[str, Callable[..., Any]]:
    """Build this session's cost bindings over its own state dict.

    Args:
        state_dict: This session's own `CostTableState.to_dict()` result,
            read fresh on every call and written in place by
            `set_cost_now`.

    Returns:
        The bindings dict, keyed by the function names a story's own
        content calls.
    """

    def cost_of_now(key: str, variant: str = "") -> float:
        """EXTERNAL cost_of_now(key, variant) -- what this action costs.
        0 for an action the story never priced."""
        return cost_of_in(state_dict, key, variant)

    def can_afford_now(key: str, available: float, variant: str = "") -> bool:
        """EXTERNAL can_afford_now(key, available, variant) -- whether
        `available` covers it. The caller passes what it holds, since this
        system owns no resource of its own."""
        return available >= cost_of_in(state_dict, key, variant)

    def set_cost_now(key: str, resource: str, amount: float) -> int:
        """EXTERNAL set_cost_now(key, resource, amount) -- change a price
        during play. Returns 1 (Ink has no void EXTERNAL return)."""
        set_cost_in(state_dict, key, resource, amount)
        return 1

    return {"cost_of_now": cost_of_now, "can_afford_now": can_afford_now, "set_cost_now": set_cost_now}


API = EngineAPIDescriptor(
    name="cost_table",
    display_name="Cost table",
    validate_config=validate_cost_table,
    state_key=STATE_KEY,
    init_state=_init_cost_table_state,
    bind_stateful=_bind_cost_table_state,
)

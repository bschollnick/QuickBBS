"""Containers: holders that have been declared to BE containers.

A companion to `inventory.py`. A container's contents live in the
inventory's own `holder_items` like any other holder's — which is what
makes put-in-a-container and give-to-a-person the same operation — so this
module adds only what makes a container different from a person: whether
it can be shut, whether it is shut now, and whether you can see in while
it is.

Marking containers explicitly, rather than inferring one from the fact
that something is inside it, follows the unanimous prior art in
interactive-fiction world models (Inform 7, TADS 3, IntFicPy, Tale): a
container is a KIND of thing with its own either/or properties, not a
location and not merely a holder that happens to have contents.

Every function here is inert for a game that declares no containers: a
holder with no ContainerSpec is always reachable and always shows its
contents, exactly as every holder did before containers existed.
"""

from __future__ import annotations

from interactive_fiction.engine_plugins.inventory import (
    ContainerClosedError,
    ContainerSpec,
    InventoryState,
    _copied,
    held_items,
    transfer_item,
)


def declare_container(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    state: InventoryState,
    holder_id: str,
    *,
    openable: bool = False,
    is_open: bool = True,
    transparent: bool = False,
    expires_when_empty: bool = False,
) -> InventoryState:
    """Mark a holder as a container.

    Args:
        state: The session's current InventoryState.
        holder_id: The holder to mark.
        openable: Whether it can be opened and shut at all. Defaults
            False, meaning permanently open.
        is_open: Whether it starts open. Ignored unless `openable`.
        transparent: Whether contents are visible while shut.
        expires_when_empty: Whether the declaration itself is dropped the
            moment the container is emptied — see `ContainerSpec`'s own
            docstring. A story that declares one this way should also
            give it its starting contents before anything can observe it
            empty (e.g. via `put_in_container`), or it expires on the
            very next `take_from_container` call.

    Returns:
        A new InventoryState with the container declared.
    """
    new_state = _copied(state)
    new_state.containers[holder_id] = ContainerSpec(
        openable=openable, is_open=is_open, transparent=transparent, expires_when_empty=expires_when_empty
    )
    return new_state


def is_container(state: InventoryState, holder_id: str) -> bool:
    """Return whether a holder has been declared a container.

    Args:
        state: The session's current InventoryState.
        holder_id: The holder to test.

    Returns:
        True when the holder was declared via `declare_container()`.
    """
    return holder_id in state.containers


def set_container_open(state: InventoryState, holder_id: str, is_open: bool) -> InventoryState:
    """Open or shut a container.

    Args:
        state: The session's current InventoryState.
        holder_id: The container to operate.
        is_open: True to open, False to shut.

    Returns:
        A new InventoryState with the container's state changed. A holder
        that is not a container, or one that is not openable, is returned
        unchanged rather than raising — a story asking to open something
        permanently open has already got what it wanted.
    """
    spec = state.containers.get(holder_id)
    if spec is None or not spec.openable:
        return _copied(state)
    new_state = _copied(state)
    new_state.containers[holder_id] = ContainerSpec(
        openable=True, is_open=is_open, transparent=spec.transparent, expires_when_empty=spec.expires_when_empty
    )
    return new_state


def is_container_open(state: InventoryState, holder_id: str) -> bool:
    """Return whether a container can currently be reached into.

    Args:
        state: The session's current InventoryState.
        holder_id: The container to test.

    Returns:
        True when it is open or not openable. A holder that is not a
        container is always reachable, which keeps every pre-existing
        holder behaving exactly as it did before containers existed.
    """
    spec = state.containers.get(holder_id)
    if spec is None:
        return True
    return spec.accepts_reach()


def visible_contents(state: InventoryState, holder_id: str) -> dict[str, int]:
    """Return what can be SEEN inside a holder right now.

    Args:
        state: The session's current InventoryState.
        holder_id: The holder to look into.

    Returns:
        {item_id: count} when the contents are visible — always, for an
        ordinary holder or an open container, and also for a shut
        TRANSPARENT one. Empty for a shut opaque container, which is the
        whole point of opacity.
    """
    spec = state.containers.get(holder_id)
    if spec is not None and not spec.reveals_contents():
        return {}
    return held_items(state, holder_id)


def take_from_container(state: InventoryState, holder_id: str, to_holder: str, item_id: str, count: int = 1) -> InventoryState:
    """Take an item out of a container.

    Args:
        state: The session's current InventoryState.
        holder_id: The container to take from.
        to_holder: Who receives it.
        item_id: What to take.
        count: How many.

    Returns:
        A new InventoryState with the item moved. If the container
        declares `expires_when_empty` and this take leaves it holding
        nothing, the declaration itself is dropped in the same result —
        `is_container(result, holder_id)` answers False from here on, as
        if `declare_container()` had never run for it. The holder
        underneath is untouched (still whatever it was: an ordinary
        holder, a location's own drop pile), so nothing about the item
        that was just taken is affected — only the container's own
        wrapper is gone.

    Raises:
        ContainerClosedError: The container is shut. Being transparent
            does not help — seeing inside is not reaching inside.
        ItemNotHeldError: The container does not hold enough of it.
        InventoryFullError: The receiver is at its distinct-item capacity.
        StackFullError: The receiver is at its stack limit for this item.
    """
    if not is_container_open(state, holder_id):
        raise ContainerClosedError(f"container '{holder_id}' is shut")
    new_state = transfer_item(state, holder_id, to_holder, item_id, count)
    spec = new_state.containers.get(holder_id)
    if spec is not None and spec.expires_when_empty and not held_items(new_state, holder_id):
        new_state = _copied(new_state)
        del new_state.containers[holder_id]
    return new_state


def put_in_container(state: InventoryState, from_holder: str, holder_id: str, item_id: str, count: int = 1) -> InventoryState:
    """Put an item into a container.

    Args:
        state: The session's current InventoryState.
        from_holder: Who is putting it in.
        holder_id: The container to put it in.
        item_id: What to put in.
        count: How many.

    Returns:
        A new InventoryState with the item moved.

    Raises:
        ContainerClosedError: The container is shut.
        ItemNotHeldError: The giver does not hold enough of it.
        InventoryFullError: The container is at its distinct-item capacity.
        StackFullError: The container is at its stack limit for this item.
    """
    if not is_container_open(state, holder_id):
        raise ContainerClosedError(f"container '{holder_id}' is shut")
    return transfer_item(state, from_holder, holder_id, item_id, count)

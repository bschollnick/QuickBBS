"""Description-slot lookup for items: one text, chosen from three layers.

A companion to `inventory.py`, kept separate because it shares no state
with it — the inventory tracks where things are; this module answers what
a thing READS as. Splitting them keeps each module inside a reviewable
size and means a game that wants placements without prose (or prose
without placements) imports only what it uses.

**All text belongs to the caller.** This module holds no strings of its
own: slot names, authored text and default templates are supplied by the
game layer, exactly as item ids are. It performs only the walk from most
specific to least.

The three layers a game builds on this:

1. **Generic** — the game's own fallback templates, formatted with an
   item's display name, so an item that authored nothing still reads as a
   sentence rather than an id.
2. **Game** — the item's own authored string for a slot.
3. **Scene** — prose written inline at one moment in the story, which
   never calls here at all; a scene with its own words simply writes them.

Text that varies at runtime is deliberately NOT this module's business. A
description that depends on story state is rendered by the story layer,
which is the only layer that can see that state.
"""

from __future__ import annotations


def describe(
    slot: str,
    *,
    authored: dict[str, str] | None = None,
    defaults: dict[str, str] | None = None,
    name: str = "",
) -> str:
    """Return the text for one of an item's description slots.

    The lookup walks from most specific to least: the game's own authored
    string for this slot, else the game's default template for it,
    formatted with the item's display name. Text that varies at runtime is
    NOT this function's business — a game whose description depends on
    story state renders that in its own story layer and never calls here.

    Args:
        slot: Which description is wanted. Opaque here; the game layer
            decides what slots exist and what they mean.
        authored: This item's own text, per slot, or None when the item
            authored none.
        defaults: The game's fallback templates, per slot. A template may
            contain `{name}`, which is replaced with `name`.
        name: The item's display name, for formatting a default template.

    Returns:
        The authored string when there is one; otherwise the formatted
        default; otherwise an empty string when the game supplied no
        default for this slot either.
    """
    if authored:
        text = authored.get(slot)
        if text:
            return text
    if defaults:
        template = defaults.get(slot)
        if template:
            return template.format(name=name)
    return ""

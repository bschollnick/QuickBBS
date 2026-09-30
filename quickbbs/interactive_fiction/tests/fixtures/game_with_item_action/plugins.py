"""The fixture's pack: what the player carries, starting with a lantern."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ink_engine.plugin import EngineState, ListDefs, Plugin


def _bind(own_state: dict[str, Any], engine_state: EngineState, list_defs: ListDefs) -> dict[str, Callable[..., Any]]:
    """Bind `has_item(item)` and `use_item(item)` over the pack."""
    del engine_state, list_defs

    def use_item(item: str) -> bool:
        if item not in own_state["items"]:
            return False
        own_state["items"].remove(item)
        return True

    return {"has_item": lambda item: item in own_state["items"], "use_item": use_item}


PLUGIN = Plugin(
    name="fixture_pack",
    display_name="Fixture pack",
    state_key="fixture_pack",
    init_state=lambda config: {"items": ["lantern"]},
    bind=_bind,
)

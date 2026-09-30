"""The fixture's exits panel, built the way a real game builds one."""

from __future__ import annotations

from typing import Any

from ink_engine.game_panel import exits_section

from .plugins import FIXTURE_MAP


def panel_context(engine_state: dict[str, Any], globals_: dict[str, Any], bindings: dict[str, Any]) -> dict[str, Any] | None:
    """Return the exits panel for the room the story records in `current_location`."""
    del bindings
    slot = engine_state.get(FIXTURE_MAP.state_key)
    if slot is None:
        return None
    section = exits_section(FIXTURE_MAP.exits_from(slot, globals_["current_location"]))
    return {"panel_sections": [section]} if section is not None else None

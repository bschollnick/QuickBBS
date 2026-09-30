"""The fixture's panel: one action section in a slot, and two commands."""

from __future__ import annotations

from typing import Any

from ink_engine.game_panel import actions_section


def panel_context(engine_state: dict[str, Any], globals_: dict[str, Any], bindings: dict[str, Any]) -> dict[str, Any]:
    """Return a panel whose only section lists the story's `companion_actions` knot."""
    del engine_state, globals_, bindings
    return {"panel_sections": [], "panel_slots": [actions_section("companion_actions", heading="Companions", empty_text="Nobody is with you.")]}


def panel_command(
    engine_state: dict[str, Any], globals_: dict[str, Any], bindings: dict[str, Any], command_id: str, target_id: str
) -> str | dict[str, str]:
    """Answer "ring" with a story reaction, "look" with a message only, anything else with ""."""
    del engine_state, globals_, bindings
    if (command_id, target_id) == ("ring", "bell"):
        return {"knot": "bell_rings", "message": "You ring the bell.", "label": "Ring the bell"}
    if (command_id, target_id) == ("look", "bell"):
        return "A brass bell."
    return ""

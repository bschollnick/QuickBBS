"""The fixture's panel: one action section in a slot."""

from __future__ import annotations

from typing import Any

from ink_engine.game_panel import actions_section


def panel_context(engine_state: dict[str, Any], globals_: dict[str, Any], bindings: dict[str, Any]) -> dict[str, Any]:
    """Return a panel whose only section lists the story's `pack_actions` knot."""
    del engine_state, globals_, bindings
    return {"panel_sections": [], "panel_slots": [actions_section("pack_actions", heading="Companions", empty_text="Nobody is with you.")]}

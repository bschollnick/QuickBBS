"""The fixture's panel: one followers section in a slot."""

from __future__ import annotations

from typing import Any

from ink_engine.game_panel import followers_section

FOLLOWERS = (
    {"id": "sam", "label": "Sam", "head_shot_function": "sam_head_shot"},
    {"id": "ada", "label": "Ada", "head_shot_function": "ada_head_shot"},
)


def panel_context(engine_state: dict[str, Any], globals_: dict[str, Any], bindings: dict[str, Any]) -> dict[str, Any]:
    """Return a panel whose only section lists the fixture's two followers."""
    del engine_state, globals_, bindings
    return {
        "panel_sections": [],
        "panel_slots": [followers_section(list(FOLLOWERS), heading="Followers", knot="companion_actions", empty_text="No one is with you.")],
    }

"""The fixture's map: a hall, a garden south of it, a sealed attic above, and a cellar with no position."""

from __future__ import annotations

from ink_engine.engine_plugins.location_graph import (
    LocationGraph,
    add_missing_return_exits,
)

MAP = add_missing_return_exits(
    {
        "locations": {
            "hall": {
                "known_by_default": True,
                "arrival_knot": "hall",
                "arrival_text": "You go back inside.",
                "exits": [
                    {"to": "garden", "position": "s", "label": "the garden", "arrival_knot": "garden", "travel_text": "You step outside."},
                    {"to": "attic", "position": "up", "label": "the attic", "sealed": True, "show_when_blocked": True, "one_way": True},
                    {"to": "cellar", "label": "a trapdoor", "arrival_knot": "cellar", "travel_text": "You climb down.", "one_way": True},
                ],
            },
            "garden": {"known_by_default": True},
            "attic": {"known_by_default": True},
            "cellar": {"known_by_default": True},
        }
    }
)

FIXTURE_MAP = LocationGraph(config=MAP, name="fixture_map")
PLUGIN = FIXTURE_MAP.plugin()

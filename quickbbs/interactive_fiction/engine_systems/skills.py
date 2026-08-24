"""SkillSystem: a generic, roll-under skill-check framework
(claude_docs/plans/external_expansion_IF_engine.md Step 7).

A reusable engine service ANY story's own conversion builds its specific
skill/attribute system on top of — never an ASFA-specific implementation
(see the plan's "generic framework, not an ASFA-specific implementation"
design section). This module has zero knowledge of what "Strength" or
"Charisma" means, or what an ASFA-specific skill list looks like — a
skill is just a name (a plain string the game layer chooses) and a
numeric level on whatever range the game layer declares for it (1-6,
1-20, 1-100, or anything else); this module normalizes every check
internally to a percentile (0-100) roll, so the game layer's own display
range is purely presentational and never touches the actual roll math.

**Roll-under mechanic**: a check succeeds when a 1-100 roll is less than
or equal to (level + bonus). This module has no opinion about what a
caller does with a level outside a sane range, or a bonus that pushes the
effective target past 100 or below 0 — those are simply clamped at roll
time (see `check()`'s own docstring), never rejected, since the game
layer's own range validation (if any) is its own concern.

**Own independent RNG, not Ink's** (explicit user decision, 2026-08-22:
"Use the skillsystem's own RNG. Reduce the dependencies and the
arguments."): `SkillState` carries its own seed/call-count, fully
independent of `engine.py`'s `InkRuntimeState.story_seed`/
`previous_random`. This keeps `SkillSystem` fully decoupled from the Ink
interpreter's own RNG internals — zero import of `engine.py` anywhere in
this module — at the cost of skill checks and Ink's own `RANDOM()` not
sharing one combined random stream. A skill check is a pure function of
(skill state, RNG state) -> (result, new RNG state), fully deterministic
and replayable from its own serialized state alone.

Per-session isolation: every function here is a pure function of its own
explicit arguments — no instance attributes, no shared/module-level
state. `SkillState` is a plain, JSON-safe dataclass meant to round-trip
through a session's own serialized state, exactly like `SchedulingState`/
`LocationGraphState`/`OccupancyState`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SkillState:
    """A session's own skill levels plus this module's own independent RNG state.

    Args:
        levels: character_id -> {skill_name: level}, where level is on
            whatever numeric range the game layer chose for that skill —
            this module never reads or validates that range itself, only
            `check()`'s own caller-supplied `max_level` normalizes a
            given level into the percentile roll.
        rng_seed: This module's own RNG seed — fully independent of Ink's
            `story_seed`, per the explicit design decision above.
    """

    levels: dict[str, dict[str, int]] = field(default_factory=dict)
    rng_seed: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain, JSON-safe dict.

        Returns:
            A dict safe to store inside a session's own serialized state.
        """
        return {"levels": {character_id: dict(skills) for character_id, skills in self.levels.items()}, "rng_seed": self.rng_seed}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillState":
        """Rebuild from a to_dict() result.

        Args:
            data: A to_dict() result.

        Returns:
            The rebuilt SkillState.
        """
        levels = {character_id: dict(skills) for character_id, skills in data.get("levels", {}).items()}
        return cls(levels=levels, rng_seed=int(data.get("rng_seed", 0)))


def get_level(state: SkillState, character_id: str, skill_name: str, default: int = 0) -> int:
    """Return a character's current level in a skill.

    Args:
        state: The session's current SkillState.
        character_id: The character to look up.
        skill_name: The skill to look up — any string the game layer chose.
        default: The level to return if the character has no recorded
            level for this skill yet.

    Returns:
        The character's current level, or `default` if unset.
    """
    return state.levels.get(character_id, {}).get(skill_name, default)


def get_all_levels(state: SkillState, character_id: str) -> dict[str, int]:
    """Return every skill level currently recorded for a character.

    The real "get current stats for a player/NPC" query.

    Args:
        state: The session's current SkillState.
        character_id: The character to look up.

    Returns:
        A plain, independent copy of that character's skill_name -> level
        mapping (empty if the character has no recorded skills at all).
    """
    return dict(state.levels.get(character_id, {}))


def set_level(state: SkillState, character_id: str, skill_name: str, level: int) -> SkillState:
    """Set a character's level in a skill to an exact value.

    Args:
        state: The session's current SkillState.
        character_id: The character to update.
        skill_name: The skill to set.
        level: The exact level to set (on whatever range the game layer
            uses for this skill — not validated or clamped here).

    Returns:
        A new SkillState with the change applied — this function never
        mutates `state` in place, matching the stateless/per-session-
        isolation discipline every function in this module follows.
    """
    new_levels = {character_id: dict(skills) for character_id, skills in state.levels.items()}
    new_levels.setdefault(character_id, {})[skill_name] = level
    return SkillState(levels=new_levels, rng_seed=state.rng_seed)


def adjust_level(state: SkillState, character_id: str, skill_name: str, delta: int) -> SkillState:
    """Add (or, with a negative delta, subtract) an amount to a character's
    current level in a skill.

    Args:
        state: The session's current SkillState.
        character_id: The character to update.
        skill_name: The skill to adjust.
        delta: The amount to add — pass a negative value to subtract.

    Returns:
        A new SkillState with the change applied. A skill with no prior
        recorded level is treated as starting at 0 before applying delta,
        matching `get_level()`'s own default.
    """
    current = get_level(state, character_id, skill_name, default=0)
    return set_level(state, character_id, skill_name, current + delta)


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one skill check — the real "get the result of a
    skill test" the game layer queries.

    Args:
        success: Whether the check succeeded (roll <= effective target).
        roll: The raw 1-100 roll made for this check.
        effective_target: The actual roll-under target used, after
            normalizing `level` onto a 1-100 scale and applying `bonus`,
            clamped to [0, 100] — this is what `roll` was actually
            compared against, useful for the game layer to report "you
            needed X or under, you rolled Y."
    """

    success: bool
    roll: int
    effective_target: int


def check(state: SkillState, level: int, max_level: int, bonus: int = 0) -> tuple[CheckResult, SkillState]:
    """Perform one roll-under skill check.

    The level is normalized onto a 0-100 percentile scale via
    `round(level / max_level * 100)` before `bonus` is applied — the game
    layer's own numeric range (1-6, 1-20, 1-100, whatever a specific
    skill uses) is purely presentational; this module only ever rolls
    1-100 internally. `bonus` is added directly to the already-normalized
    percentile target (a +1/+2/+3-style bonus is a flat percentile bump,
    not itself normalized against `max_level`) — an effective target
    outside [0, 100] is clamped rather than rejected, matching this
    module's own "never reject a caller-supplied number, just make the
    math sane" convention.

    Args:
        state: The session's current SkillState (its own RNG state is
            what actually advances here).
        level: The character's current level in whatever skill is being
            tested, on a 0-`max_level` scale.
        max_level: The top of that skill's own declared range (e.g. 20
            for a 1-20 skill, 6 for a 1-6 skill) — used only to normalize
            `level` onto the internal 0-100 percentile scale.
        bonus: An optional flat percentile bonus (or, negative, a
            penalty) applied after normalization.

    Returns:
        A tuple of (the CheckResult, a new SkillState with the RNG
        advanced) — this function never mutates `state` in place.
    """
    percentile_level = round((level / max_level) * 100) if max_level else 0
    effective_target = max(0, min(100, percentile_level + bonus))
    rng = random.Random(state.rng_seed)
    roll = rng.randint(1, 100)
    next_seed = rng.randint(0, 2**31 - 1)
    result = CheckResult(success=roll <= effective_target, roll=roll, effective_target=effective_target)
    return result, SkillState(levels=state.levels, rng_seed=next_seed)

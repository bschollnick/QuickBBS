"""A generic quest/goal/journal framework for Ink stories.

Companion to `skills.py` and `inventory.py`, and built to the same
`engine_plugins/__init__.py` discipline: nothing here holds per-story
data, every function takes the session's own state explicitly and returns
a new state or a plain value, and no game's vocabulary appears anywhere.

**Three concepts, deliberately separated:**

* A **quest** has a numeric *stage*. That is the shape stories already
  use for long progressions -- a single counter compared against
  thresholds -- and it stays a plain int because the meanings of the
  numbers are a game fact, not an engine one.
* A **goal** is one discrete objective that is either met or outstanding.
  Goals hang off a quest and carry no stage of their own; they are what
  makes a journal renderable, because "2 of 4 ingredients found" needs
  countable units rather than a single number.
* The **journal** is assembled here but worded by the game. This module
  produces structure -- which quests are known, which goals remain, what
  nests under what -- and never a player-facing string.

**Structure is passed in, not stored.** Which quests exist, which are
subquests of which, and what any stage means all live in the game's own
catalog and arrive as a `dict[str, QuestSpec]` argument. `QuestState`
carries only what a session actually changed. This matches how
`inventory.py` takes item text and worn-slot capacities as arguments
rather than fields: two sessions of the same story share one catalog, and
a story that declares nothing gets empty answers everywhere.

**Everything is optional.** A story that declares no quests never starts
one, and every query returns an empty answer rather than raising. The
system is inert when unused, exactly as worn slots are in `inventory.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# A quest the player has never encountered has no stage at all. Stories
# compare stages against thresholds, so the unstarted value must be lower
# than any real stage a game would author; 0 is that floor, and
# `is_started` exists so a story never has to encode the convention
# itself.
UNSTARTED_STAGE = 0


@dataclass(frozen=True)
class QuestSpec:
    """One quest's own immutable structure, owned by the game's catalog.

    Frozen because this is a declaration rather than session state: two
    sessions sharing one catalog must not be able to edit each other's
    view of what a quest requires.

    Args:
        quest_id: The catalog's own opaque id for this quest.
        goal_ids: Every goal that belongs to this quest, in the order a
            journal should list them. A quest with no goals is normal --
            plenty of progressions are a bare stage counter.
        requires: Ids of subquests that must complete before this quest
            can. A child NOT listed here still nests in the journal and
            tracks its own stages, but does not block its parent -- so a
            story can show optional side-work without inventing a second
            mechanism for it.
        parent_id: The quest this one nests under in the journal, or None
            for a top-level quest.
        final_stage: The stage at or above which this quest counts as
            complete, or None when completion is decided only by goals
            and required subquests.
    """

    quest_id: str
    goal_ids: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    parent_id: str | None = None
    final_stage: int | None = None


@dataclass
class QuestState:
    """A session's own quest progress.

    Args:
        stages: quest_id -> current stage. A quest absent from this dict
            has never started.
        met_goals: quest_id -> the goal ids met so far. Stored per quest
            rather than as one flat set so two quests may reuse a goal id
            without colliding.
        failed: Quest ids that ended badly. Kept separate from stages
            because a story's own failure sentinel is a game fact -- the
            engine must be able to answer "did this fail" without knowing
            that some particular number means it.
    """

    stages: dict[str, int] = field(default_factory=dict)
    met_goals: dict[str, list[str]] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain, JSON-safe dict.

        Returns:
            A dict safe to store inside a session's own serialized state.
        """
        return {
            "stages": dict(self.stages),
            "met_goals": {quest_id: list(goals) for quest_id, goals in self.met_goals.items()},
            "failed": list(self.failed),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QuestState":
        """Rebuild from a to_dict() result.

        Tolerant of missing keys so a session saved before this system
        existed still loads -- the same contract `SkillState.from_dict`
        keeps.

        Args:
            data: A to_dict() result, or any dict missing some of its keys.

        Returns:
            The rebuilt QuestState.
        """
        stages = {quest_id: int(stage) for quest_id, stage in data.get("stages", {}).items()}
        goals_by_quest = {quest_id: list(goals) for quest_id, goals in data.get("met_goals", {}).items()}
        return cls(stages=stages, met_goals=goals_by_quest, failed=list(data.get("failed", [])))


# Serialized-state operations, for the binding layer (2026-09-04, mirroring
# `character_occupancy.py`/`scheduling.py`/`inventory.py`'s own established
# `_in`-suffixed pattern). `QuestState.from_dict()` rebuilds all 3 fields
# on every call, though a plain stage/started/failed read only ever
# touches one of them. Real corpus hot spots confirmed: ASFA's
# `kurndorf_ritual` calls quest functions 25 times in one knot, `seance`
# 20, `desiree_recite` 18, `sir_ronald_gates_hub` 16 -- 181 total
# `quest_stage_now` call sites corpus-wide. `is_complete`/`quest_complete_now`
# is deliberately NOT given an `_in` variant: it genuinely needs `stages`
# AND `met_goals` together (recursively, across subquest `requires`), and
# has only 7 corpus-wide call sites -- no real hot-path evidence, and the
# full-state path is simpler and safer for logic this involved.


def stage_of_in(stages: dict[str, int], quest_id: str) -> int:
    """Return a quest's current stage, from a serialized stages dict.

    Args:
        stages: The serialized `QuestState.stages` mapping.
        quest_id: The quest to read.

    Returns:
        The current stage, or `UNSTARTED_STAGE` for a quest never started.
    """
    return stages.get(quest_id, UNSTARTED_STAGE)


def is_started_in(stages: dict[str, int], quest_id: str) -> bool:
    """Whether the player has encountered a quest at all, from a serialized stages dict.

    Args:
        stages: The serialized `QuestState.stages` mapping.
        quest_id: The quest to test.

    Returns:
        True once the quest has any stage recorded.
    """
    return quest_id in stages


def is_failed_in(failed: list[str], quest_id: str) -> bool:
    """Whether a quest ended badly, from a serialized failed list.

    Args:
        failed: The serialized `QuestState.failed` list.
        quest_id: The quest to test.

    Returns:
        True once the quest has been failed.
    """
    return quest_id in failed


def is_met_in(met_goals: dict[str, list[str]], quest_id: str, goal_id: str) -> bool:
    """Whether one goal has been met, from a serialized met_goals dict.

    Args:
        met_goals: The serialized `QuestState.met_goals` mapping.
        quest_id: The quest the goal belongs to.
        goal_id: The goal to test.

    Returns:
        True once the goal is met.
    """
    return goal_id in met_goals.get(quest_id, [])


def stage_of(state: QuestState, quest_id: str) -> int:
    """Return a quest's current stage.

    Args:
        state: The session's current QuestState.
        quest_id: The quest to read.

    Returns:
        The current stage, or `UNSTARTED_STAGE` for a quest never started.
    """
    return state.stages.get(quest_id, UNSTARTED_STAGE)


def is_started(state: QuestState, quest_id: str) -> bool:
    """Whether the player has encountered a quest at all.

    Args:
        state: The session's current QuestState.
        quest_id: The quest to test.

    Returns:
        True once the quest has any stage recorded. A journal uses this to
        decide whether a quest is visible at all.
    """
    return quest_id in state.stages


def start_quest(state: QuestState, quest_id: str, stage: int = 1) -> QuestState:
    """Begin a quest, if it has not begun already.

    Idempotent: a scene the player can re-enter cannot reset progress by
    starting the quest again. This is the same reasoning behind
    `meet_goal`'s idempotency.

    Args:
        state: The session's current QuestState.
        quest_id: The quest to start.
        stage: The stage to start at.

    Returns:
        A new QuestState, or the original unchanged if already started.
    """
    if is_started(state, quest_id):
        return state
    return set_stage(state, quest_id, stage)


def set_stage(state: QuestState, quest_id: str, stage: int) -> QuestState:
    """Set a quest's stage unconditionally, including backwards.

    The escape hatch for the genuine exceptions -- a story that resets a
    failed path back to an earlier stage so it can be retried. Ordinary
    progress should use `advance_to`, which cannot regress by accident.

    Args:
        state: The session's current QuestState.
        quest_id: The quest to move.
        stage: The stage to move it to.

    Returns:
        A new QuestState with the change applied.
    """
    stages = dict(state.stages)
    stages[quest_id] = stage
    return QuestState(stages=stages, met_goals={k: list(v) for k, v in state.met_goals.items()}, failed=list(state.failed))


def advance_to(state: QuestState, quest_id: str, stage: int) -> QuestState:
    """Move a quest forward, never backward.

    Mirrors the `if (getQuestX() < n) setQuestX(n)` guard stories write by
    hand at nearly every real advance site. Advancing to a lower or equal
    stage is a no-op rather than an error, because the guard's whole point
    is that a re-entered scene must be harmless.

    Args:
        state: The session's current QuestState.
        quest_id: The quest to advance.
        stage: The stage to advance to.

    Returns:
        A new QuestState, or the original unchanged when it would regress.
    """
    if stage <= stage_of(state, quest_id):
        return state
    return set_stage(state, quest_id, stage)


def meet_goal(state: QuestState, quest_id: str, goal_id: str) -> QuestState:
    """Mark one goal met.

    Idempotent, for the reason TADS 3's `awardPointsOnce` is: re-entering
    the scene that completes a goal must not count it twice, or any
    "N of M done" report drifts.

    Args:
        state: The session's current QuestState.
        quest_id: The quest the goal belongs to.
        goal_id: The goal to mark met.

    Returns:
        A new QuestState, or the original unchanged if already met.
    """
    if is_met(state, quest_id, goal_id):
        return state
    goals_by_quest = {k: list(v) for k, v in state.met_goals.items()}
    goals_by_quest.setdefault(quest_id, []).append(goal_id)
    return QuestState(stages=dict(state.stages), met_goals=goals_by_quest, failed=list(state.failed))


def is_met(state: QuestState, quest_id: str, goal_id: str) -> bool:
    """Whether one goal has been met.

    Args:
        state: The session's current QuestState.
        quest_id: The quest the goal belongs to.
        goal_id: The goal to test.

    Returns:
        True once the goal is met.
    """
    return goal_id in state.met_goals.get(quest_id, [])


def met_goals(state: QuestState, quest_id: str) -> list[str]:
    """Return every goal met on a quest, in the order they were met.

    Args:
        state: The session's current QuestState.
        quest_id: The quest to read.

    Returns:
        A copy of the met-goal list, empty for an untouched quest.
    """
    return list(state.met_goals.get(quest_id, []))


def outstanding_goals(state: QuestState, quest_id: str, catalog: dict[str, QuestSpec]) -> list[str]:
    """Return a quest's goals that are still unmet, in catalog order.

    Args:
        state: The session's current QuestState.
        quest_id: The quest to read.
        catalog: The game's own quest catalog.

    Returns:
        The unmet goal ids. Empty for a quest with no goals, or one the
        catalog does not declare.
    """
    spec = catalog.get(quest_id)
    if spec is None:
        return []
    return [goal_id for goal_id in spec.goal_ids if not is_met(state, quest_id, goal_id)]


def fail_quest(state: QuestState, quest_id: str) -> QuestState:
    """Mark a quest as ended badly.

    Args:
        state: The session's current QuestState.
        quest_id: The quest that failed.

    Returns:
        A new QuestState, or the original unchanged if already failed.
    """
    if quest_id in state.failed:
        return state
    return QuestState(
        stages=dict(state.stages),
        met_goals={k: list(v) for k, v in state.met_goals.items()},
        failed=list(state.failed) + [quest_id],
    )


def is_failed(state: QuestState, quest_id: str) -> bool:
    """Whether a quest ended badly.

    Args:
        state: The session's current QuestState.
        quest_id: The quest to test.

    Returns:
        True once the quest has been failed.
    """
    return quest_id in state.failed


def remaining_requirements(state: QuestState, quest_id: str, catalog: dict[str, QuestSpec]) -> list[str]:
    """Return the required subquests that are not yet complete.

    What lets a journal say "2 of 4 ingredients found" instead of printing
    a bare stage number.

    Args:
        state: The session's current QuestState.
        quest_id: The parent quest.
        catalog: The game's own quest catalog.

    Returns:
        The incomplete required subquest ids, in the order `requires`
        lists them. Empty when every requirement is met, when the quest
        has none, or when the catalog does not declare it.
    """
    spec = catalog.get(quest_id)
    if spec is None:
        return []
    return [child_id for child_id in spec.requires if not is_complete(state, child_id, catalog)]


def is_complete(state: QuestState, quest_id: str, catalog: dict[str, QuestSpec]) -> bool:
    """Whether a quest is finished, honouring its required subquests.

    A quest completes when all three hold:

    * every required subquest is complete (checked one level deep -- see
      the module's own scope note, and note this recurses exactly once
      because a subquest's own `requires` is empty by construction in
      every catalog this supports),
    * every declared goal is met,
    * its `final_stage` has been reached, when it declares one.

    A quest with no goals, no requirements and no `final_stage` can never
    report complete, which is deliberate: silently calling such a quest
    finished would hide a catalog that forgot to say how it ends.

    Args:
        state: The session's current QuestState.
        quest_id: The quest to test.
        catalog: The game's own quest catalog.

    Returns:
        True when the quest is finished.
    """
    spec = catalog.get(quest_id)
    if spec is None:
        return False
    if any(not is_complete(state, child_id, catalog) for child_id in spec.requires):
        return False
    if outstanding_goals(state, quest_id, catalog):
        return False
    if spec.final_stage is None:
        return bool(spec.goal_ids or spec.requires)
    return stage_of(state, quest_id) >= spec.final_stage


@dataclass(frozen=True)
class JournalEntry:
    """One quest's own line in an assembled journal, plus its children.

    Carries structure and ids only. Every player-facing string is the
    game's to supply, keyed off these ids -- which is what keeps this
    module free of any one story's wording.

    Args:
        quest_id: The quest this entry describes.
        stage: Its current stage.
        complete: Whether it is finished.
        failed: Whether it ended badly.
        met: Goal ids already met, in catalog order.
        outstanding: Goal ids still to do, in catalog order.
        children: Entries for its subquests, one level deep.
    """

    quest_id: str
    stage: int
    complete: bool
    failed: bool
    met: tuple[str, ...]
    outstanding: tuple[str, ...]
    children: tuple["JournalEntry", ...] = ()


def _entry_for(state: QuestState, quest_id: str, catalog: dict[str, QuestSpec], children: tuple[JournalEntry, ...]) -> JournalEntry:
    """Build one JournalEntry for a quest that is known to be started.

    Args:
        state: The session's current QuestState.
        quest_id: The quest to describe.
        catalog: The game's own quest catalog.
        children: Already-assembled entries for this quest's subquests.

    Returns:
        The assembled entry.
    """
    spec = catalog[quest_id]
    outstanding = outstanding_goals(state, quest_id, catalog)
    return JournalEntry(
        quest_id=quest_id,
        stage=stage_of(state, quest_id),
        complete=is_complete(state, quest_id, catalog),
        failed=is_failed(state, quest_id),
        met=tuple(goal_id for goal_id in spec.goal_ids if is_met(state, quest_id, goal_id)),
        outstanding=tuple(outstanding),
        children=children,
    )


def journal_entries(state: QuestState, catalog: dict[str, QuestSpec]) -> list[JournalEntry]:
    """Assemble the player's journal: every started quest, children nested.

    Unstarted quests are omitted entirely, matching the convention that a
    journal shows only what the player has actually discovered.

    A started subquest whose parent has NOT started is promoted to the top
    level rather than dropped -- losing a quest the player really began
    would be the silent-failure mode this system exists to prevent.

    Args:
        state: The session's current QuestState.
        catalog: The game's own quest catalog.

    Returns:
        Top-level entries in catalog order, each with its started children
        nested one level deep.
    """
    children_by_parent: dict[str, list[JournalEntry]] = {}
    for quest_id, spec in catalog.items():
        if spec.parent_id is None or not is_started(state, quest_id):
            continue
        children_by_parent.setdefault(spec.parent_id, []).append(_entry_for(state, quest_id, catalog, ()))

    entries: list[JournalEntry] = []
    for quest_id, spec in catalog.items():
        if not is_started(state, quest_id):
            continue
        parent = spec.parent_id
        if parent is not None and is_started(state, parent) and parent in catalog:
            continue
        entries.append(_entry_for(state, quest_id, catalog, tuple(children_by_parent.get(quest_id, ()))))
    return entries


def unreachable_goals(catalog: dict[str, QuestSpec], reachable_goal_ids: set[str]) -> list[tuple[str, str]]:
    """Report goals a catalog declares that nothing can ever meet.

    The audit the surveyed prior art lacks. A goal that no scene ever
    meets is not a compile error and not a test failure -- it is a quest
    that silently never finishes, which is the exact bug class this
    conversion keeps hitting with gates on state nothing writes.

    Args:
        catalog: The game's own quest catalog.
        reachable_goal_ids: Every goal id some scene actually meets,
            gathered by the caller from the story source.

    Returns:
        (quest_id, goal_id) pairs for declared goals nothing can meet, in
        catalog order. Empty is the healthy answer.
    """
    return [(spec.quest_id, goal_id) for spec in catalog.values() for goal_id in spec.goal_ids if goal_id not in reachable_goal_ids]

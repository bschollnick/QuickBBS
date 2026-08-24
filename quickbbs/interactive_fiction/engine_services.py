"""Real Python callables bound to EXTERNAL calls for trusted stories only.

claude_docs/plans/external_expansion_IF_engine.md's real implementation
surface, reworked 2026-08-22 for the plugin-discovery/per-story-isolation
redesign (interactive_fiction/engine_api.py). `bindings_for(story)` is the
one function callers (interactive_fiction.views._new_game_state()/
_load_game_state()) use to decide what, if anything, InkRuntimeState should
be given — the ONLY place in this whole system allowed to branch on
Story.is_engine_trusted, mirroring the existing test suite's own
`_bindings_for()` helper convention.

**Per-story API isolation** (explicit user requirement, 2026-08-22: "Each
story should be able to use it's own externals, but they should be
isolated to each story"): a story's own bindings are derived from its OWN
`StorySystemConfig` rows — a story only ever gets bindings for an API it
has explicitly opted into (a real row with that API's `system_name`), not
a flat merge of every globally-enabled API. Two stories can each opt into
`"scheduling"` independently; neither's row, config, or resulting bindings
are visible to or shared with the other's `bindings_for()` call at all.

**Global enable/disable is a separate axis** (`EngineAPI.is_enabled`,
`interactive_fiction/engine_api.py`'s scan-and-toggle mechanism): an API a
story has opted into (a real `StorySystemConfig` row exists) still
contributes NO bindings unless that API is also globally enabled — a
disabled API silently (from the player's perspective) falls through to
its `.ink` file's own dead-stub fallback, but this is logged loudly here
as a real misconfiguration (explicit user requirement: "there should be
an error visible in some way... a service is missing, please contact
admin") — this is NOT the same as an ordinary untrusted story's permanent,
expected, silent stub fallback; a trusted story that opted into an API
which then became unavailable is a real operational problem.

Every registered callable MUST be stateless: it receives only the
arguments Ink pushed onto eval_stack for this one call and returns one
value, exactly like an ordinary Ink function's own args-in/one-value-out
shape. Per the plan's explicit per-session isolation requirement, no
callable here may read or write anything outside its own arguments/return
value — no module-level mutable state, no attribute on some shared
object, no per-request cache. Every user's game session is completely
self-contained (real interactive_fiction.engine.InkRuntimeState instances
are always constructed fresh per request, never pooled or reused); a
callable that stashed data on itself between calls would leak one
player's game state into another's the moment two sessions share this
same registry object, which every trusted story's sessions do.

**ASFA retrofit** (`claude_docs/plans/asfa_ink_conversions/`, started
2026-08-22): each real API's own bindings are declared on its own module
(see `interactive_fiction/engine_systems/scheduling.py`'s own `API =
EngineAPIDescriptor(...)`), verified via a real differential test
(`interactive_fiction/tests/test_asfa_scheduling_retrofit.py` and
siblings) proving the new Python function agrees with the ORIGINAL Ink
function it replaced across its full real input space, before the
corresponding `.ink` file was ever touched — per the explicit "avoid
rewriting this many times" process agreed with the user.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from interactive_fiction.engine_api import discover_api_descriptors
from interactive_fiction.models import EngineAPI

if TYPE_CHECKING:
    from interactive_fiction.models import Story

logger = logging.getLogger(__name__)


def bindings_for(story: "Story", engine_state: dict[str, Any] | None = None) -> dict[str, Callable[..., Any]]:
    """Return the real Python bindings a story's InkRuntimeState should get.

    The single point in this whole system allowed to branch on
    Story.is_engine_trusted — every other piece (InkRuntimeState,
    _call_function, any individual binding) is deliberately unaware of
    trust at all, and just does what it's told.

    Per-story isolation: only APIs this specific story has its own
    StorySystemConfig row for are even considered — never a flat merge of
    every enabled API, so two stories' bindings never bleed into each
    other regardless of what else is enabled globally.

    **Stateful APIs** (claude_docs/plans/external_expansion_IF_engine.md,
    "stateful EXTERNAL bindings" design, 2026-08-23): an API descriptor
    with `state_key`/`bind_stateful` set gets handed its own private slice
    of `engine_state` — `engine_state[state_key]`, created via
    `init_state()` the first time — and is asked to build its own
    bindings as closures over that ONE dict. Since `engine_state` itself
    is the caller's own per-request `CurrentGame.state["engine_state"]`
    dict (never shared or reused across sessions, exactly like `story`
    itself isn't), those closures are exactly as session-isolated as this
    function's own existing stateless bindings — nothing new for a
    calling view to reason about beyond passing its own real
    `engine_state` dict through and persisting it afterward, same as it
    already does for InkRuntimeState.to_dict()'s own fields.

    Args:
        story: The story whose trust flag, and whose own
            StorySystemConfig rows, decide the answer.
        engine_state: The session's own mutable, JSON-safe state dict
            (typically `CurrentGame.state.setdefault("engine_state", {})`)
            — required if any opted-into, enabled API declares
            `state_key`; unused (and safe to omit) otherwise. Mutated in
            place by any stateful API's own `init_state()`/bound
            closures, so the caller's own reference already reflects
            every write once this call and the resulting bindings' calls
            are done.

    Returns:
        The real bindings for every API this story has opted into AND
        that is currently enabled; empty for an untrusted story (its
        EXTERNAL calls always fall through to their own Ink fallback,
        unchanged) or a trusted story with no StorySystemConfig rows at
        all. An opted-into API that's missing or disabled contributes no
        bindings (its own calls fall through the same way) but is logged
        loudly here — a real, actionable misconfiguration for a trusted
        story, not the ordinary silent-by-design untrusted case.
    """
    if not story.is_engine_trusted:
        return {}

    system_names = list(story.system_configs.values_list("system_name", flat=True).distinct())
    if not system_names:
        return {}

    descriptors = discover_api_descriptors()
    enabled_names = set(EngineAPI.objects.filter(name__in=system_names, is_enabled=True).values_list("name", flat=True))

    resolved: dict[str, Callable[..., Any]] = {}
    for name in system_names:
        if name not in descriptors:
            logger.error(
                "interactive_fiction.engine_services: story %r opted into API '%s' but no such API is currently discoverable on disk", story, name
            )
            continue
        if name not in enabled_names:
            logger.error(
                "interactive_fiction.engine_services: story %r opted into API '%s' but it is not enabled "
                "(or has no EngineAPI row yet — run sync_engine_apis)",
                story,
                name,
            )
            continue
        descriptor = descriptors[name]
        if descriptor.bind_stateful is not None and descriptor.state_key is not None:
            if engine_state is None:
                logger.error(
                    "interactive_fiction.engine_services: story %r opted into stateful API '%s' but no engine_state dict was provided",
                    story,
                    name,
                )
                continue
            assert descriptor.init_state is not None, f"EngineAPIDescriptor '{name}' sets bind_stateful/state_key without init_state"
            api_state = engine_state.setdefault(descriptor.state_key, descriptor.init_state())
            resolved.update(descriptor.bind_stateful(api_state))
        else:
            resolved.update(descriptor.bindings)
    return resolved

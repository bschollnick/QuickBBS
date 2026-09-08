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

**A real converted-game retrofit** (started 2026-08-22): each real API's
own bindings are declared on its own module (see
`interactive_fiction/engine_plugins/scheduling.py`'s own `API =
EngineAPIDescriptor(...)`), verified via a real differential test proving
the new Python function agrees with the ORIGINAL Ink function it
replaced across its full real input space, before the corresponding
`.ink` file was ever touched — per the explicit "avoid rewriting this
many times" process agreed with the user.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from interactive_fiction.engine import load_list_defs, retrieve_python_list
from interactive_fiction.engine_api import discover_api_descriptors
from interactive_fiction.ingestion import read_manifest_value
from interactive_fiction.models import (
    DEFAULT_PLAY_LAYOUT,
    PLAY_LAYOUTS,
    EngineAPI,
    play_layout_template,
)
from quickbbs.models import DirectoryIndex

if TYPE_CHECKING:
    from interactive_fiction.engine_api import EngineAPIDescriptor
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

    # Loaded at most once per call, only if some opted-into descriptor
    # actually asks for it (needed_list_names) — every other story pays
    # nothing for this.
    list_defs: dict[str, dict[str, int]] | None = None

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
                "(or has no EngineAPI row yet — run scan_if_stories)",
                story,
                name,
            )
            continue
        descriptor = descriptors[name]
        # An API may declare both kinds of binding: its stateless ones are
        # plain functions of their arguments, while its stateful ones need
        # this session's own state slot. They are two halves of one API,
        # not alternatives, so both are resolved (2026-08-29 — previously
        # a descriptor with a state_key silently contributed none of its
        # stateless bindings, which would have dropped a real API's whole
        # pure-function surface the moment it grew its first stateful one).
        resolved.update(descriptor.bindings)
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
            readable = None
            if descriptor.also_reads:
                # Slots this API reads but does not own — for a binding
                # whose answer is a view over another system's state. Each
                # is allocated by its OWNING descriptor's own init_state,
                # so a reader binding first never creates a differently
                # shaped dict than the owner would have.
                readable = {key: engine_state.setdefault(key, _init_state_for(descriptors, key)) for key in descriptor.also_reads}
            list_item_tables = None
            if descriptor.needed_list_names:
                if list_defs is None:
                    list_defs = load_list_defs(story.compiled_json)
                list_item_tables = {list_name: retrieve_python_list(list_defs, list_name) for list_name in descriptor.needed_list_names}
            resolved.update(_call_bind_stateful(descriptor, api_state, readable, list_item_tables))
    return resolved


def _call_bind_stateful(
    descriptor: "EngineAPIDescriptor", api_state: dict[str, Any], readable: dict[str, Any] | None, list_item_tables: dict[str, dict[str, int]] | None
) -> dict[str, Callable[..., Any]]:
    """Call one descriptor's `bind_stateful` with exactly the optional
    arguments it actually asked for.

    Split out of `bindings_for`'s own per-API loop purely to keep that
    loop's own branch count readable — `bind_stateful`'s signature grows
    one positional argument per optional feature a descriptor opts into
    (`also_reads`, then `needed_list_names`), and picking the right one of
    the resulting four call shapes is its own small piece of dispatch.

    Args:
        descriptor: The API being bound. `bind_stateful` must be set.
        api_state: This API's own state slice.
        readable: The `also_reads` slices, or None if this descriptor
            declares none.
        list_item_tables: The `needed_list_names` tables, or None if this
            descriptor declares none.

    Returns:
        The bindings dict `descriptor.bind_stateful` returns.
    """
    assert descriptor.bind_stateful is not None
    if list_item_tables is not None:
        if readable is not None:
            return descriptor.bind_stateful(api_state, readable, list_item_tables)
        return descriptor.bind_stateful(api_state, list_item_tables)
    if readable is not None:
        return descriptor.bind_stateful(api_state, readable)
    return descriptor.bind_stateful(api_state)


def _init_state_for(descriptors: dict[str, "EngineAPIDescriptor"], state_key: str) -> dict[str, Any]:
    """Return a fresh state dict for `state_key`, from whichever API owns it.

    A slot's shape belongs to the API that declares it, so an API merely
    READING that slot (via `also_reads`) must never invent its own initial
    value for it — binding order would then decide the shape.

    Args:
        descriptors: Every discoverable API descriptor, by name.
        state_key: The slot to initialize.

    Returns:
        The owning descriptor's own `init_state()` result, or an empty
        dict if no discoverable API declares that slot (a story reading a
        slot nobody owns gets an empty one rather than an import error).
    """
    for descriptor in descriptors.values():
        if descriptor.state_key == state_key and descriptor.init_state is not None:
            return descriptor.init_state()
    logger.error("interactive_fiction.engine_services: no discoverable API owns state slot '%s'; initializing it empty", state_key)
    return {}


def game_panel_context(story: "Story", engine_state: dict[str, Any], globals_: dict[str, Any]) -> dict[str, Any] | None:
    """Return the side-panel data a game supplies for its play page.

    Some games are more than prose: the original A Spell For All renders
    a persistent right-hand panel beside the story text, and content that
    belongs in a panel — an inventory listing, a device the player can
    open — has nowhere to live in a pure choice-and-text page. Rather than
    grow the engine a notion of "inventory panel" (which would be one
    game's UI imposed on every other), a game folder may ship a
    `sidebar.py` exposing `panel_context()`, and the engine renders
    whatever rows it returns. A game without one renders exactly as before.

    **The game supplies data, never markup or a template path.** A game
    folder lives under the Albums tree, which is untrusted content; adding
    it to the template search path would turn every uploaded directory
    into a template source, and letting a game name an arbitrary template
    would let it render one it was never meant to reach. So the template
    ships with this app and the game only fills it.

    **Also receives real bindings** (`bindings_for(story, engine_state)`),
    the same way `game_panel_action`/`game_panel_command` do — some panel
    facts (is a container currently open, and which one) live in story
    state a stateful API owns (a character attribute, a quest stage), not
    in `engine_state`'s own slices or in plain Ink globals. This call is
    read-only by contract (nothing it returns is ever persisted back into
    `engine_state` — see `views.play`), so handing it real bindings is
    safe the same way it is for `game_panel_action`.

    This reuses `bindings_for()`'s own trust gate rather than inventing a
    second one: panel code is game-authored Python, so it must be
    reachable only for a story whose game folder is already trusted to
    execute at all. An untrusted story gets None, the same way it gets no
    bindings.

    Args:
        story: The story whose play page is being rendered.
        engine_state: The session's own `engine_state` dict, so the panel
            can read the same live inventory/skill state the story sees.
        globals_: The runtime's own Ink globals, for panel state that
            lives in the story rather than in an API's state slice.

    Returns:
        The panel's context dict, or None when this story supplies no
        panel (or is untrusted, or its module exposes no
        `panel_context()`). A panel that raises is logged and treated as
        absent — a broken panel must not take the play page down with it.
    """
    if not story.is_engine_trusted:
        return None

    module = _game_module(story, "sidebar")
    build = getattr(module, "panel_context", None) if module is not None else None
    if not callable(build):
        return None
    try:
        context = build(engine_state, globals_, bindings_for(story, engine_state))
    except Exception:  # pylint: disable=broad-except
        logger.exception("interactive_fiction.engine_services: story %r side panel failed to build; rendering without it", story)
        return None
    return context if isinstance(context, dict) else None


def _canonical_path(path: str) -> str:
    """Normalise one filesystem path for comparison against another.

    Neither side of the game-folder match arrives canonical:
    `Story.source_fqfn` is stored lowercased (the scanner's own
    normalisation) while the albums root keeps the filesystem's real
    casing, and either may reach here through a symlinked parent
    (`/var` -> `/private/var` on macOS) the other does not use. Comparing
    raw strings silently finds no game folder at all.

    Args:
        path: Any filesystem path.

    Returns:
        The path with symlinks resolved and casing flattened, or a
        lowercased copy when it cannot be resolved (a path that does not
        exist yet is still comparable).
    """
    try:
        return str(Path(path).resolve()).lower()
    except OSError:
        return str(path).lower()


def game_folder_for(story: "Story") -> Path | None:
    """Return the game folder a story was ingested from, if any.

    A story is tied to its game folder by `source_fqfn` living inside it —
    the same linkage `engine_api._game_folder_is_trusted` uses — so the
    folder is read back off that path rather than from a dedicated field,
    which deliberately does not exist: the game's own manifest is already
    the single source of truth for everything about a game, and copying
    its values onto columns would give each of them two homes that could
    disagree.

    Args:
        story: The story whose game folder is wanted.

    Returns:
        The folder's path, or None for a story with no game folder (every
        uploaded story, and any whose `source_fqfn` is outside the games
        tree).
    """
    games_root_path = Path(DirectoryIndex.get_albums_root()) / "interactive_fiction"
    games_root = _canonical_path(str(games_root_path)).rstrip("/") + "/"
    source = _canonical_path(str(story.source_fqfn))
    if not source.startswith(games_root):
        return None
    remainder = source[len(games_root) :].strip("/")
    if not remainder:
        return None
    return games_root_path / remainder.split("/", maxsplit=1)[0]


def _game_module(story: "Story", module_stem: str) -> Any:
    """Return one already-loaded module from a story's own game folder.

    Game folders are loaded wholesale by `discover_api_descriptors()`
    (every `.py` file, under a synthetic package name), so this only has
    to look the result up rather than import anything itself — which also
    means a game folder that failed to load contributes nothing here
    instead of raising during page render.

    Args:
        story: The story whose game folder is wanted.
        module_stem: The bare filename, without `.py`.

    Returns:
        The module, or None when this story has no game folder, or that
        folder has no such file.
    """
    game_dir = game_folder_for(story)
    if game_dir is None:
        return None

    discover_api_descriptors()
    return sys.modules.get(f"interactive_fiction._games.{game_dir.name}.{module_stem}")


def game_panel_action(story: "Story", engine_state: dict[str, Any], globals_: dict[str, Any], action_id: str, target_id: str) -> str:
    """Run one of a game panel's row actions and return what it answers.

    The per-click companion to `game_panel_context`: a game that ships a
    panel decides both what actions its rows offer and what each one says.
    Kept separate because it is answered per click rather than per page
    render, and because it must never mutate — see
    `views.play_panel_action` for why a panel action does not advance a
    turn.

    **Also receives real bindings and globals**
    (`bindings_for(story, engine_state)`, and the runtime's own Ink
    globals), the same way `game_panel_command` does — a dynamic Examine
    answer routinely needs to read facts a different stateful API owns (a
    quest stage, an NPC's own possession of some other item, a character
    attribute) or a fact that lives in Ink globals rather than any
    stateful API (e.g. `player_is_possessing`), not just the item
    catalog's static text. Since this path is read-only by contract (the
    caller never persists `engine_state` afterward — see
    `views.play_panel_action`), handing it real bindings is safe: a
    game's `panel_action` may call any binding to READ state, but nothing
    it does here is ever saved.

    Args:
        story: The story being played.
        engine_state: The session's own `engine_state` dict.
        globals_: The runtime's own Ink globals.
        action_id: The action the row offered.
        target_id: What it was invoked on.

    Returns:
        The fragment text to show, or "" when this story supplies no
        panel, its panel answers no actions, or it does not recognise this
        action/target. A panel that raises is logged and treated as silent
        for the same reason as `game_panel_context`.
    """
    if not story.is_engine_trusted:
        return ""

    module = _game_module(story, "sidebar")
    run = getattr(module, "panel_action", None) if module is not None else None
    if not callable(run):
        return ""
    try:
        return str(run(engine_state, bindings_for(story, engine_state), globals_, action_id, target_id))
    except Exception:  # pylint: disable=broad-except
        logger.exception("interactive_fiction.engine_services: story %r side panel failed on action %r/%r", story, action_id, target_id)
        return ""


def game_panel_command(story: "Story", engine_state: dict[str, Any], globals_: dict[str, Any], command_id: str, target_id: str) -> str:
    """Run one of a game panel's turn-advancing commands (Use/Cast/Give/Drop).

    The write-capable counterpart to `game_panel_action`: a panel row that
    genuinely changes the world (using an item, casting a spell) needs the
    same real bindings a story choice gets — `give_item_now`,
    `spend_item_use_now`, `advance_quest_now`, whatever the game's opted-into
    APIs expose — not a bespoke one-off write path per game. This is that
    documented side-loading route: any game's `sidebar.py` may expose a
    `panel_command(engine_state, globals_, bindings, command_id, target_id)`
    callable, and it is handed the exact same `bindings_for(story,
    engine_state)` dict `InkRuntimeState`'s own EXTERNAL calls use for this
    session, so a two- or three-pane game plugging in inventory, quests,
    skills, occupancy, or any future stateful API gets a real write surface
    for free, with no engine change required to add a new API — only a new
    `engine_plugins/`(or game-folder) module with its own `state_key`/
    `bind_stateful` (see `interactive_fiction/engine_api.py`).

    **This mutates `engine_state` in place**, exactly like a stateful
    binding invoked mid-turn does. The caller (`views.play_panel_command`)
    is responsible for the turn-count guard, the `transaction.atomic()`
    wrapper, and persisting the mutated `engine_state` back onto
    `CurrentGame` afterward — this function itself has no notion of a
    request, a turn, or a database row, matching `game_panel_context`/
    `game_panel_action`'s own separation of concerns.

    **`globals_` may also be mutated in place** (2026-09-04) — the same
    live `InkRuntimeState.globals` dict `play_panel_command` passes
    through to `_build_current_game_state()` afterward, so a write here
    (e.g. ASFA's own `panel_command` setting `player_is_possessing` to
    complete a Possession cast via a personal-affect item) is captured
    exactly like a mid-turn `~ player_is_possessing = "..."` assignment
    would be. Read-only use (the original reason this parameter exists)
    is unaffected.

    Args:
        story: The story being played.
        engine_state: The session's own mutable `engine_state` dict. Passed
            straight through to `bindings_for()`, so any stateful API's
            `bind_stateful` closures write into this exact dict.
        globals_: The runtime's own Ink globals (e.g. for
            `player_is_possessing`), read the same way `game_panel_context`
            reads them.
        command_id: The command the row offered (the game names these —
            e.g. "use", "cast"; distinct from `game_panel_action`'s
            read-only `action_id` vocabulary, though a game may reuse ids
            across both if that suits it).
        target_id: What the command was invoked on (an item id, a skill id).

    Returns:
        A short result message to show the player (e.g. "You are carrying
        too much."), or "" when this story supplies no panel, its panel
        answers no commands, or it does not recognise this command/target.
        A panel command that raises is logged and treated as a no-op — a
        broken command must not take the turn down with it, and
        `engine_state` may have been partially mutated by the failed call,
        exactly as a raising EXTERNAL binding mid-turn would leave state.
    """
    if not story.is_engine_trusted:
        return ""

    module = _game_module(story, "sidebar")
    run = getattr(module, "panel_command", None) if module is not None else None
    if not callable(run):
        return ""
    try:
        return str(run(engine_state, globals_, bindings_for(story, engine_state), command_id, target_id))
    except Exception:  # pylint: disable=broad-except
        logger.exception("interactive_fiction.engine_services: story %r side panel failed on command %r/%r", story, command_id, target_id)
        return ""


def play_layout_for(story: "Story") -> str:
    """Return the template that renders this story's play page.

    A game chooses its own page shape by naming one of the engine's
    layouts in its manifest (`PLAY_LAYOUT = "three_column"`). The engine
    ships the layouts; the game only picks one and fills it.

    The name is looked up in `models.PLAY_LAYOUTS`, never used as a path.
    That is the whole security property here: a game folder lives in the
    untrusted Albums tree, so a manifest that could name a template would
    be able to point the renderer at any file on disk.

    Unlike `bindings_for`/`game_panel_context`, this is deliberately NOT
    gated on `is_engine_trusted`. Choosing between the engine's own
    templates executes no game code and reveals nothing; refusing an
    untrusted game its layout would only render it badly, and the manifest
    is read as data (`ast`), never imported.

    Args:
        story: The story being played.

    Returns:
        A template path from `models.PLAY_LAYOUTS`, falling back to the
        default layout for a story with no game folder, no manifest, no
        `PLAY_LAYOUT`, or one naming a layout this engine version lacks.
    """
    game_dir = game_folder_for(story)
    if game_dir is None:
        return play_layout_template(DEFAULT_PLAY_LAYOUT)

    layout = read_manifest_value(game_dir, "PLAY_LAYOUT", "")
    if not isinstance(layout, str) or not layout:
        return play_layout_template(DEFAULT_PLAY_LAYOUT)
    if layout not in PLAY_LAYOUTS:
        logger.warning(
            "interactive_fiction.engine_services: story %r asks for play layout '%s', which this engine does not ship; using '%s'",
            story,
            layout,
            DEFAULT_PLAY_LAYOUT,
        )
    return play_layout_template(layout)

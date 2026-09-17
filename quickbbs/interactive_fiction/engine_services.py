"""Real Python callables bound to EXTERNAL calls for trusted stories only.

`bindings_for(story)` is the one function callers use to decide what, if
anything, `InkRuntimeState` should be given, and **the ONLY place allowed
to branch on `Story.is_engine_trusted`.**

**Per-story API isolation**: a story's bindings come from its OWN
its manifest's own `REQUIRED_PLUGINS`, never a flat merge of every globally-enabled
API. Two stories can each opt into `"scheduling"` independently; neither's
row, config, or resulting bindings are visible to the other.

**Global enable/disable is a separate axis** (`EngineAPI.is_enabled`). An
API a story opted into contributes NO bindings unless it is also globally
enabled. That case falls through to the `.ink` file's own dead-stub
fallback and is logged loudly as a misconfiguration -- unlike an
untrusted story's expected, permanent stub fallback.

**Every registered callable MUST be stateless**: it receives only the
arguments Ink pushed for this one call and returns one value. No
module-level mutable state, no attribute on a shared object, no
per-request cache. A callable that stashed data on itself would leak one
player's game state into another's, since sessions share this registry.

**Compiled LIST tables reach a plugin's `bind()` through the engine**:
`bindings_for()` computes them from `story.compiled_json` and passes
`list_defs=` to `resolve_bindings()`. A plugin's
`bind(own_state, engine_state, list_defs)` never receives `story`, so it
cannot load them itself.
"""

from __future__ import annotations

import functools
import importlib
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ink_engine import game_panel
from ink_engine.binding import resolve_bindings
from ink_engine.engine import load_list_defs
from ink_engine.game_folder import GameFolderError, plugin_denied_text
from ink_engine.game_source import GameSourceError
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
    from interactive_fiction.models import Story

logger = logging.getLogger(__name__)


def bindings_for(story: "Story", engine_state: dict[str, Any] | None = None) -> dict[str, Callable[..., Any]]:
    """Return the real Python bindings a story's InkRuntimeState should get.

    A stateful `Plugin` is handed its own private slice of `engine_state`
    (`engine_state[state_key]`, created via `init_state()` on first use)
    and builds its bindings as closures over that one dict. Since
    `engine_state` is the caller's own per-request dict, those closures
    are as session-isolated as the stateless ones.

    Args:
        story: The story whose trust flag, and whose own
            manifest, decide the answer.
        engine_state: The session's own mutable, JSON-safe state dict
            (typically `CurrentGame.state.setdefault("engine_state", {})`)
            — required if any opted-into, enabled API declares
            `state_key`; unused otherwise. Mutated in place, so the
            caller's reference reflects every write afterward.

    Returns:
        The real bindings for every plugin this story has opted into AND
        that is currently enabled; empty for an untrusted story or one
        whose manifest declares no plugins. A declared plugin that is
        missing or disabled contributes no bindings but is logged loudly.
    """
    if not story.is_engine_trusted:
        return {}

    system_names = story.opted_in_plugin_names()
    if not system_names:
        return {}

    plugins = discover_api_descriptors()
    enabled_names = set(EngineAPI.objects.filter(name__in=system_names, is_enabled=True).values_list("name", flat=True))

    active_names: list[str] = []
    for name in system_names:
        if name not in plugins:
            logger.error(
                "interactive_fiction.engine_services: story %r opted into plugin '%s' but no such plugin is currently discoverable on disk",
                story,
                name,
            )
            continue
        if name not in enabled_names:
            logger.error(
                "interactive_fiction.engine_services: story %r opted into plugin '%s' but it is not enabled "
                "(or has no EngineAPI row yet — run scan_if_stories)",
                story,
                name,
            )
            continue
        if engine_state is None and plugins[name].state_key is not None:
            # A stateful plugin needs somewhere to put its state, so a
            # caller that forgot to pass engine_state gets none of ITS
            # bindings (a stateless-only plugin is unaffected -- it never
            # needed engine_state in the first place).
            logger.error(
                "interactive_fiction.engine_services: story %r opted into stateful plugin '%s' but no engine_state dict was provided",
                story,
                name,
            )
            continue
        active_names.append(name)

    # Activation order is precedence: a later plugin's binding wins a name
    # collision. The game's manifest fixes that order; a name the manifest
    # does not list (an opt-in row left over from before the game's own
    # plugin took the name over) goes first, so it can never shadow the
    # game's own binding.
    manifest_order = [name for name in (story.game_required_plugins or []) if name in active_names]
    active_names = [name for name in active_names if name not in manifest_order] + manifest_order

    return resolve_bindings(
        plugins,
        active_names,
        engine_state if engine_state is not None else {},
        list_defs=load_list_defs(story.compiled_json),
    )


def game_panel_context(story: "Story", engine_state: dict[str, Any], globals_: dict[str, Any]) -> dict[str, Any] | None:
    """Return the side-panel data a game supplies for its play page.

    Some games are more than prose: a converted game's own original may
    render a persistent right-hand panel beside the story text, and
    content that belongs in a panel — an inventory listing, a device the
    player can open — has nowhere to live in a pure choice-and-text page.
    Rather than
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

    **Also receives real bindings**, since some panel facts live in story
    state a stateful API owns rather than in `engine_state` or Ink
    globals. This call is READ-ONLY by contract: nothing it returns is
    persisted back into `engine_state` (see `views.play`).

    Gated on `bindings_for()`'s own trust check -- panel code is
    game-authored Python, so an untrusted story gets None.

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

    return game_panel.panel_context(
        _game_module(story, "sidebar"),
        engine_state=engine_state,
        globals_=globals_,
        bindings=bindings_for(story, engine_state),
        logger=logger,
    )


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
    """Return one submodule of a story's own game folder.

    Gated on `story.is_engine_trusted` directly, same as `bindings_for()`.
    **A trusted game folder is a REAL importable package**, so
    `importlib.import_module()` would happily import an untrusted one too
    if asked: this function must refuse BEFORE ever calling it.

    Args:
        story: The story whose game folder is wanted.
        module_stem: The bare filename, without `.py` (e.g. "sidebar").

    Returns:
        The module, or None when this story is untrusted, has no game
        folder, or that folder has no such file.
    """
    if not story.is_engine_trusted:
        return None

    game_dir = game_folder_for(story)
    if game_dir is None:
        return None

    # Puts a trusted game's parent directory on sys.path as a side effect;
    # called here (idempotently) so order relative to bindings_for() does
    # not matter.
    discover_api_descriptors()
    try:
        return importlib.import_module(f"{game_dir.name}.{module_stem}")
    except ModuleNotFoundError:
        return None


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

    return game_panel.panel_action(
        _game_module(story, "sidebar"),
        engine_state=engine_state,
        globals_=globals_,
        bindings=bindings_for(story, engine_state),
        action_id=action_id,
        target_id=target_id,
        logger=logger,
    )


def game_panel_command(story: "Story", engine_state: dict[str, Any], globals_: dict[str, Any], command_id: str, target_id: str) -> str:
    """Run one of a game panel's turn-advancing commands (Use/Cast/Give/Drop).

    The write-capable counterpart to `game_panel_action`. A game's
    `sidebar.py` may expose
    `panel_command(engine_state, globals_, bindings, command_id, target_id)`,
    handed the same `bindings_for(story, engine_state)` dict this
    session's own EXTERNAL calls use.

    **This mutates `engine_state` AND `globals_` in place**, like a
    stateful binding invoked mid-turn. The caller
    (`views.play_panel_command`) owns the turn-count guard, the
    `transaction.atomic()` wrapper, and persisting both back onto
    `CurrentGame` afterward.

    Args:
        story: The story being played.
        engine_state: The session's own mutable `engine_state` dict. Passed
            straight through to `bindings_for()`, so any stateful plugin's
            `bind()` closures write into this exact dict.
        globals_: The runtime's own Ink globals (e.g. for
            `player_is_possessing`), read the same way `game_panel_context`
            reads them.
        command_id: The command the row offered (the game names these,
            e.g. "use", "cast"); a separate vocabulary from
            `game_panel_action`'s read-only `action_id`.
        target_id: What the command was invoked on (an item id, a skill id).

    Returns:
        A short result message to show the player (e.g. "You are carrying
        too much."), or "" when this story supplies no panel, its panel
        answers no commands, or it does not recognise this command/target.
        A panel command that raises is logged and treated as a no-op;
        `engine_state` may have been PARTIALLY MUTATED by the failed call.
    """
    if not story.is_engine_trusted:
        return ""

    return game_panel.panel_command(
        _game_module(story, "sidebar"),
        engine_state=engine_state,
        globals_=globals_,
        bindings=bindings_for(story, engine_state),
        command_id=command_id,
        target_id=target_id,
        logger=logger,
    )


#: Matches a rendered `href`/`src` attribute, whatever it points at.
#: Applied AFTER rendering, so it catches what Markdown's own link syntax
#: produces as well as anything that survived escaping.
_LINK_ATTRIBUTE_RE = re.compile(r'\s(?:href|src)="[^"]*"', re.IGNORECASE)


@functools.cache
def _screen_markdown() -> Any:
    """Return the shared Markdown processor for plugin-denied screens.

    Deferred like `fileindex.py`'s own: markdown2 is only needed when an
    untrusted story is actually opened. `safe_mode="escape"` because the
    text comes from the untrusted Albums tree.
    """
    # pylint: disable-next=import-outside-toplevel
    import markdown2

    return markdown2.Markdown(extras=["tables", "fenced-code-blocks"], safe_mode="escape")


def _without_link_targets(html: str) -> str:
    """Strip every `href`/`src` from rendered screen HTML.

    `safe_mode="escape"` stops raw HTML but not Markdown's own link
    syntax: `![x](javascript:alert(1))` renders a live
    `<img src="javascript:...">`. This screen is explanatory prose shown
    before a game is trusted -- it has no reason to link anywhere or load
    anything, so the targets go rather than being allowlisted by scheme.

    Dropping the attribute and keeping the element leaves the text
    readable; an `<a>` with no `href` is inert.

    Args:
        html: Rendered Markdown.

    Returns:
        The same HTML with every link target removed.
    """
    return _LINK_ATTRIBUTE_RE.sub("", html)


def plugin_denied_html(story: "Story") -> str:
    """Return the game's plugin-denied screen, rendered to HTML.

    A game that declares plugins is designed around them; run without
    them it is broken, not reduced. The game explains what its own
    plugins do, because only it knows -- a host can list names, but not
    that a game's own occupancy plugin missing means no character is
    anywhere.

    The screen is rendered in `safe_mode="escape"`: it comes from a game
    folder in the untrusted Albums tree, and it is shown BEFORE that game
    has been trusted. Raw markdown2 passes `<script>` straight through,
    so the game's own HTML is escaped and only Markdown's own constructs
    render -- the same posture `story_markup.py` takes for story text.

    Args:
        story: The story whose screen to render.

    Returns:
        HTML, or "" for a story with no game folder to read one from.
    """
    source = story.bundle_path or (Path(story.source_fqfn).parent if story.source_fqfn else None)
    if source is None:
        return ""
    try:
        text = plugin_denied_text(source)
    except (GameFolderError, GameSourceError, OSError) as error:
        logger.warning("interactive_fiction.engine_services: story %r has no readable plugin-denied screen: %s", story, error)
        return ""

    return _without_link_targets(str(_screen_markdown().convert(text)))


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

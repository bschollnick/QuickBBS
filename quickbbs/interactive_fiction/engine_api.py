"""The EngineAPI plugin contract and scanner
(claude_docs/plans/external_expansion_IF_engine.md's plugin-discovery
redesign, 2026-08-22).

**Real requirement, explicit user direction**: QuickBBS should be able to
scan for API files (Python modules declaring a reusable engine system —
SchedulingSystem, LocationSystem, SkillSystem, and any future third-party
one) and let an admin enable/disable each discovered API independently.
An enabled API is available to every story; a specific story's own
`StorySystemConfig` (per-story config) and binding registration (Step 3's
`Story.is_engine_trusted`/`engine_services.bindings_for()`) still decide
whether and how a given story actually uses it — enabling an API only
controls whether it EXISTS to be used at all, a separate axis from
per-story opt-in.

**The plugin contract**: any `.py` file under `ENGINE_API_SCAN_DIR`
(default `interactive_fiction/engine_plugins/`, the generic, story-
agnostic mechanics that ship with the engine regardless of which game is
loaded) OR under one real game's own folder
(`DirectoryIndex.get_albums_root()/interactive_fiction/<game_name>/`,
identified by that folder containing an `__init__.py` manifest) that
defines a module-level `API:
EngineAPIDescriptor` attribute is a real API. Files without that
attribute are ordinary helper modules, ignored by the scanner — this is
deliberately a required-attribute contract, not a naming/directory
convention, so a game's own API file is unambiguous and self-describing
rather than needing to be told an implicit naming rule. A game's own
folder lives outside this project's Python package tree entirely (a
plain Albums data directory), so its `.py` files are loaded by real
filesystem path, not a dotted import — see `discover_api_descriptors`'s
own two loader strategies.

**Why disabling an API must never crash a story that references it**:
per explicit user direction, a disabled (or since-removed) API's bindings
must fall through to the referencing `.ink` file's own dead-stub fallback
— exactly like an untrusted story today — but this must be a REAL,
LOGGED, OBSERVABLE misconfiguration, not a silently-degrading one; a
missing API for an ENABLED, trusted story is a real operational problem
worth an admin's attention, unlike the untrusted case (which is the
permanent, expected, silent default for every story that was never
explicitly opted in).
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quickbbs.directoryindex import DirectoryIndex

logger = logging.getLogger(__name__)

ENGINE_API_SCAN_DIR = Path(__file__).parent / "engine_plugins"


@dataclass(frozen=True)
class EngineAPIDescriptor:
    """The real, self-describing contract a `.py` file exposes to be
    discovered as an engine API.

    Args:
        name: The API's real, unique identifier (e.g. "scheduling") —
            this is what `StorySystemConfig.system_name` and
            `engine_services`'s per-story binding registration both
            reference; must be stable across scans (renaming it is a
            real breaking change for any story already referencing it).
        display_name: A human-readable label for the admin interface.
        bindings: The real Python callables this API exposes for EXTERNAL
            dispatch, keyed by the exact Ink function name a story's own
            `.ink` content would call — e.g. `{"is_day_now": is_day}`.
            Every callable here must be stateless, per the plan's
            per-session isolation requirement.
        validate_config: An optional validator for this API's own
            `StorySystemConfig.config` shape — `None` for an API with no
            structured config at all (e.g. a pure-function API needing no
            per-story data). Raises `engine_config_schemas.
            SystemConfigValidationError` on an invalid config, mirroring
            every other validator in this codebase.
        state_key: This API's own key inside a session's
            `CurrentGame.state["engine_state"]` dict — the generic,
            per-API-opaque JSON-safe state store `engine_services.
            bindings_for()` threads through (claude_docs/plans/
            external_expansion_IF_engine.md, "stateful EXTERNAL bindings"
            design, 2026-08-23). `None` for a pure-function API with no
            state at all (every API built before this field existed).
            Only meaningful together with `init_state`/`bind_stateful`.
        init_state: Return this API's own fresh, JSON-safe state dict for
            a brand-new game. Only called when `state_key` is set and no
            entry for it exists yet in the session's `engine_state` dict.
        bind_stateful: Given this API's own current state dict (already
            the live object at `engine_state[state_key]` for THIS one
            request — never shared across sessions, since `bindings_for()`
            is itself called fresh per request), return the real bindings
            for THIS one request: closures over that one dict, reading
            AND mutating it in place so whatever they write is naturally
            still there when the session's `engine_state` is persisted
            afterward. Only meaningful if `state_key` is set. Every
            closure returned here must still only ever touch the ONE dict
            it was given — never module-level state, another session's
            dict, or anything else — the same per-session isolation
            requirement `bindings` (above) is held to.
        also_reads: State keys this API needs to READ besides its own
            `state_key`, for a binding whose answer is a view over another
            system's state (2026-08-29). When set, `bind_stateful` is
            called with a second argument: a mapping of each named key to
            that session's live dict for it, allocated the same way
            `state_key` is. The owning API stays the single source of
            truth — a reader must not write through this mapping, or two
            systems end up disagreeing about one fact. Only meaningful
            together with `bind_stateful`.
        needed_list_names: The declared LIST names (e.g. "AllCharacters")
            `bind_stateful` wants each item table for (2026-09-04) — used
            to build a real `ListValue` in bulk rather than returning a
            comma-joined string for `.ink` content to parse itself (which
            this engine has no native primitive for). Scoped to only the
            LISTs actually needed, never the story's full LIST
            declaration set, since a binding builds one specific LIST-
            typed value at a time. When set, `bind_stateful` is called
            with a final positional argument: `{list_name: {item_name:
            int_value}}`, restricted to the requested names (each built
            by `engine.retrieve_python_list()`) — `(api_state,
            list_item_tables)` when `also_reads` is unset,
            `(api_state, readable, list_item_tables)` when it is also
            set. A name this API asks for that the story's own compiled
            LIST declarations do not define maps to `{}`, matching
            `retrieve_python_list`'s own not-found behavior — never
            raises, since a binding may support an optional LIST a given
            story does not declare.
    """

    name: str
    display_name: str
    bindings: dict[str, Callable[..., Any]] = field(default_factory=dict)
    validate_config: Callable[[Any], None] | None = None
    state_key: str | None = None
    init_state: Callable[[], dict[str, Any]] | None = None
    bind_stateful: Callable[..., dict[str, Callable[..., Any]]] | None = None
    also_reads: tuple[str, ...] = ()
    needed_list_names: tuple[str, ...] = ()


def _load_module_from_dotted_path(module_name: str, py_file: Path) -> Any:
    """Import a `.py` file that lives inside this project's own Python
    package tree, by its normal dotted module path.

    Args:
        module_name: The real dotted import path (e.g.
            "interactive_fiction.engine_plugins.scheduling").
        py_file: The file's path — unused for this loading strategy, kept
            only so this function has the same signature as
            `_load_module_from_file_path` below and callers don't need to
            know which strategy a given directory requires.

    Returns:
        The imported module.
    """
    del py_file
    return importlib.import_module(module_name)


def _ensure_namespace_package(package_name: str) -> None:
    """Register `package_name` in `sys.modules` as an empty namespace
    package, if it isn't already present.

    A synthetic module like `interactive_fiction._games.<game>.location`
    needs every ancestor in its dotted path (`interactive_fiction._games`,
    `interactive_fiction._games.<game>`) to ALSO be present in
    `sys.modules` before `from interactive_fiction._games.<game>.occupancy
    import X` inside `location.py` can resolve — Python's own import
    machinery checks each parent package in turn, not just the leaf
    module. `interactive_fiction._games` and
    `interactive_fiction._games.<game>` are not real directories anywhere
    on disk (a game's real folder lives under Albums, outside the Python
    package tree entirely) — they exist only as these synthetic, empty
    placeholder entries.

    Args:
        package_name: The dotted package name to ensure exists (e.g.
            "interactive_fiction._games.<game>").

    Returns:
        None.
    """
    if package_name in sys.modules:
        return
    package = types.ModuleType(package_name)
    package.__path__ = []  # marks it as a package to Python's import system
    sys.modules[package_name] = package


def _load_module_from_file_path(module_name: str, py_file: Path) -> Any:
    """Import a `.py` file that does NOT live inside this project's own
    Python package tree (a game's own API file under `Albums/
    interactive_fiction/<game>/`, a plain data directory, not a `quickbbs`
    package) — dotted-path `importlib.import_module` cannot resolve a
    module outside the package tree, so this loads it directly from its
    real filesystem path instead.

    Args:
        module_name: A synthetic dotted name under which this module is
            registered in `sys.modules` (must still be unique —
            collisions between two games' own same-named files are
            avoided by namespacing on the game's own folder name, see
            `discover_api_descriptors` below) — registered BEFORE
            `exec_module` runs (the standard dynamic-import pattern),
            specifically so a game's own sibling file can `from
            interactive_fiction._games.<game>.other_module import X` and
            have it resolve normally through Python's own import
            machinery, exactly as it would for a real package member.
            Every ancestor package in this dotted name is also ensured to
            exist in `sys.modules` (see `_ensure_namespace_package`) —
            required for that same cross-file `from ... import` to
            resolve at all, not just for the leaf module's own identity.
        py_file: The real `.py` file's path.

    Returns:
        The imported module.

    Raises:
        ImportError: `py_file` could not be loaded as a Python module.
    """
    already_loaded = sys.modules.get(module_name)
    if already_loaded is not None and getattr(already_loaded, "__file__", None) == str(py_file):
        # `discover_api_descriptors()` is called more than once within a
        # single Django request (2026-09-05, confirmed real: `views.play()`
        # calls it once via `bindings_for()` and again via
        # `game_panel_context()` -> `_game_module()`, unconditionally,
        # every GET). Without this check, EVERY game-folder `.py` file's
        # top-level code genuinely re-executes on the second scan — not a
        # cheap re-import, a real second `exec_module()` — plus a second
        # full filesystem walk and one `Story.objects.filter(...).exists()`
        # query per game folder in the caller above.
        #
        # The `__file__` check (not just the synthetic name) is required,
        # not cosmetic: caught by a real test failure
        # (`GamePanelTests`, test_views.py) — the synthetic module name is
        # deterministic per (game folder NAME, filename), but a test suite
        # legitimately reuses the same game folder name across separate
        # `TestCase`s backed by different temp directories, and a single
        # test can also overwrite `sidebar.py`'s own real file content
        # mid-suite and expect the NEW content on the next load. A
        # same-name-but-different-file collision must miss the cache and
        # re-execute, exactly as it would if the name check were absent
        # entirely.
        return already_loaded

    package_parts = module_name.split(".")[:-1]
    for i in range(1, len(package_parts) + 1):
        _ensure_namespace_package(".".join(package_parts[:i]))

    spec = importlib.util.spec_from_file_location(module_name, py_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load a module spec for '{py_file}'")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _load_game_folder_modules(game_dir: Path, module_name_for: Callable[[Path], str]) -> dict[str, Any]:
    """Load every `.py` file in a game folder (excluding `__init__.py`),
    tolerating sibling files that import from each other in either order.

    A game folder's files are loaded by real filesystem path
    (`_load_module_from_file_path`), never as members of a real Python
    package — so unlike an ordinary package import, nothing guarantees
    `occupancy.py` is already in `sys.modules` by the time `location.py`'s
    own top-level `from interactive_fiction._games.<game>.occupancy import
    X` runs, if the scanner happened to reach `location.py` first (plain
    alphabetical glob order, not import-dependency order). This retries
    any file whose load fails with `ModuleNotFoundError` against
    `interactive_fiction._games.<game>.*` after every other file in the
    folder has had a chance to load, succeeding once its own sibling
    dependency is registered — a real, unordered dependency graph among a
    handful of files, not worth a full topological sort for.

    Both `from interactive_fiction._games.<game>.other import X` (raises
    `ModuleNotFoundError`, a subclass, when `other` itself doesn't exist
    yet in `sys.modules`) and `from interactive_fiction._games.<game>
    import other` (raises plain `ImportError` when `other` exists as a
    package but doesn't YET have `other` as an attribute — the state right
    after `_ensure_namespace_package` creates the empty parent but before
    the sibling file has executed) are real, expected shapes of the same
    ordering problem here, so both are retried the same way.

    Args:
        game_dir: The game folder's real filesystem path.
        module_name_for: Given one `.py` file's path, return the synthetic
            dotted module name to register/import it under.

    Returns:
        A dict of {module_name: loaded module}, one entry per real `.py`
        file in the folder (excluding `__init__.py`).

    Raises:
        ImportError: A file's own import failure never resolves even
            after every sibling has had a chance to load first — a real
            unresolvable import, not just an ordering problem.
        Exception: Any other exception a module's own top-level code
            raises, surfaced immediately (not retried).
    """
    pending = [py_file for py_file in sorted(game_dir.glob("*.py")) if py_file.name != "__init__.py"]
    loaded: dict[str, Any] = {}
    game_package_prefix = ".".join(module_name_for(pending[0]).split(".")[:-1]) if pending else ""
    while pending:
        deferred: list[Path] = []
        progressed = False
        for py_file in pending:
            module_name = module_name_for(py_file)
            try:
                loaded[module_name] = _load_module_from_file_path(module_name, py_file)
                progressed = True
            except ImportError as exc:
                failed_name = exc.name if isinstance(exc, ModuleNotFoundError) else module_name
                if game_package_prefix and failed_name is not None and failed_name.startswith(game_package_prefix):
                    deferred.append(py_file)
                else:
                    raise
        if not progressed:
            unresolved = ", ".join(p.name for p in deferred)
            raise ImportError(f"Could not resolve sibling imports for: {unresolved}")
        pending = deferred
    return loaded


def _scan_directory_for_descriptors(
    directory: Path,
    module_name_for: Callable[[Path], str],
    loader: Callable[[str, Path], Any],
    descriptors: dict[str, EngineAPIDescriptor],
) -> None:
    """Scan one directory (non-recursively) for real API files, adding any
    found to `descriptors` in place.

    Shared by the generic `engine_plugins/` scan and each per-game folder
    scan in `discover_api_descriptors` below — the two differ only in
    which directory is scanned, how a file's module name is derived, and
    how the module is actually loaded (see `loader`), never in the
    detection/validation logic itself.

    Args:
        directory: The directory to scan. Must already be known to exist
            (callers check this, since "does this game folder exist at
            all" and "does it have a `__init__.py`" are meaningfully
            different failure modes higher up).
        module_name_for: Given one `.py` file's path, return the dotted
            (or synthetic) module name to import it under.
        loader: Given a module name and file path, return the imported
            module — `_load_module_from_dotted_path` for the generic
            plugin directory, `_load_module_from_file_path` for a game's
            own folder outside the Python package tree.
        descriptors: The result dict to add discoveries to, shared across
            every directory scanned in one `discover_api_descriptors`
            call — this is what makes the duplicate-name check below span
            every directory, not just the one currently being scanned.

    Raises:
        ValueError: A discovered `EngineAPIDescriptor.name` was already
            added by a previous file (in this directory or an earlier
            one) — a real, unambiguous configuration error.
    """
    modules = {}
    for py_file in sorted(directory.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        modules[module_name_for(py_file)] = loader(module_name_for(py_file), py_file)
    _add_descriptors_from_modules(modules, descriptors)


def _add_descriptors_from_modules(modules: dict[str, Any], descriptors: dict[str, EngineAPIDescriptor]) -> None:
    """Extract each module's own `API` attribute (if any) into
    `descriptors`, in place.

    Shared by `_scan_directory_for_descriptors` (generic plugin directory,
    one loader call per file) and `discover_api_descriptors`'s game-folder
    branch (which must load every sibling file up front via
    `_load_game_folder_modules` before any single file's `API` can be read
    — see that function's own docstring for why).

    Args:
        modules: {module_name: loaded module}, already imported/executed.
        descriptors: The result dict to add discoveries to, shared across
            every directory scanned in one `discover_api_descriptors`
            call — this is what makes the duplicate-name check below span
            every directory, not just the one currently being scanned.

    Raises:
        ValueError: A discovered `EngineAPIDescriptor.name` was already
            added by a previous module (in this directory or an earlier
            one) — a real, unambiguous configuration error.
    """
    for module_name, module in modules.items():
        api = getattr(module, "API", None)
        if api is None:
            continue
        if not isinstance(api, EngineAPIDescriptor):
            logger.warning("interactive_fiction.engine_api: %s defines API but it is not an EngineAPIDescriptor; skipping", module_name)
            continue
        if api.name in descriptors:
            raise ValueError(f"Duplicate EngineAPIDescriptor.name '{api.name}': declared by both a prior module and {module_name}")
        descriptors[api.name] = api


def discover_api_descriptors(scan_dir: Path = ENGINE_API_SCAN_DIR) -> dict[str, EngineAPIDescriptor]:
    """Scan `scan_dir` for generic plugin APIs, plus every real game
    folder under `DirectoryIndex.get_albums_root()/interactive_fiction/`
    for that game's own APIs, and return their combined descriptors.

    `scan_dir` (non-recursively) holds only the generic, story-agnostic
    engine plugins that ship regardless of which game is loaded —
    `scheduling.py`, `location_graph.py`, `character_occupancy.py`,
    `skills.py` — imported by their normal dotted module path, since they
    live inside this project's own `quickbbs.interactive_fiction` Python
    package.

    Each direct subdirectory of
    `DirectoryIndex.get_albums_root()/interactive_fiction/` that contains
    an `__init__.py` is treated as one game's own folder —
    its `.py` files (excluding `__init__.py` itself) are scanned the same
    way, but loaded by real filesystem path (`importlib.util.
    spec_from_file_location`), since a game's folder is a plain Albums
    data directory, never part of this project's own Python package tree.
    A folder under this path with no `__init__.py` is not a game folder
    at all and is skipped entirely (not an error — an ordinary,
    not-yet-populated or unrelated directory).

    Args:
        scan_dir: The generic-plugin directory to scan. Defaults to
            `interactive_fiction/engine_plugins/`.

    Returns:
        A dict of {api_name: EngineAPIDescriptor}, one entry per real
        discovered API, spanning both the generic plugin directory and
        every real game folder.

    Raises:
        ValueError: Two files (in the generic directory, one game's own
            folder, or across two different game folders) declare the
            same `EngineAPIDescriptor.name` — a real, unambiguous
            configuration error, never silently resolved by picking one
            arbitrarily.
    """
    descriptors: dict[str, EngineAPIDescriptor] = {}

    _scan_directory_for_descriptors(
        scan_dir,
        module_name_for=lambda py_file: f"interactive_fiction.engine_plugins.{py_file.stem}",
        loader=_load_module_from_dotted_path,
        descriptors=descriptors,
    )

    games_dir = Path(DirectoryIndex.get_albums_root()) / "interactive_fiction"
    if games_dir.is_dir():
        for game_dir in sorted(p for p in games_dir.iterdir() if p.is_dir()):
            if not (game_dir / "__init__.py").exists():
                continue
            if not _game_folder_is_trusted(game_dir):
                logger.info(
                    "interactive_fiction.engine_api: skipping '%s' — no trusted Story marks this game safe to execute (Story.is_engine_trusted)",
                    game_dir.name,
                )
                continue

            def _game_module_name(py_file: Path, game_name: str = game_dir.name) -> str:
                return f"interactive_fiction._games.{game_name}.{py_file.stem}"

            modules = _load_game_folder_modules(game_dir, _game_module_name)
            _add_descriptors_from_modules(modules, descriptors)

    return descriptors


def _game_folder_is_trusted(game_dir: Path) -> bool:
    """Return whether a game folder's own Python API files are safe to
    load and execute.

    A game folder lives under the Albums tree — the same place any
    scanner-ingested or uploaded content lands, none of it trusted by
    default (`Story.is_engine_trusted` defaults to `False` for exactly
    this reason). Executing a `.py` file is strictly more dangerous than
    running untrusted Ink (which is already sandboxed behind this same
    flag via `engine_services.bindings_for()`), so a game folder's own
    API code must be gated on the SAME real, existing trust flag, not a
    second, parallel mechanism — an admin explicitly marking this game's
    Story as engine-trusted is what allows its `.py` files to be
    imported/executed at all, mirroring exactly how an untrusted story's
    EXTERNAL calls already fall through to their own Ink dead-stub
    instead of ever reaching real Python.

    Args:
        game_dir: The candidate game folder's real filesystem path.

    Returns:
        True if a Story row backed by this game folder (matched by
        `source_fqfn` starting with the folder's own path — covers both
        a successfully-ingested game's real main-story path and a
        failed one's placeholder path) has `is_engine_trusted=True`.
        False for a folder with no Story yet, or one that's untrusted —
        the folder is still discoverable/listable, just never executed.
    """
    # Deferred import: interactive_fiction.models imports THIS module at
    # module load time (discover_api_descriptors is used by
    # StorySystemConfig.clean()) — a top-level import here would be a
    # real circular import, not just a style preference.
    from interactive_fiction.models import (
        Story,  # pylint: disable=import-outside-toplevel
    )

    folder_prefix = str(game_dir).rstrip("/") + "/"
    return Story.objects.filter(source_fqfn__startswith=folder_prefix, is_engine_trusted=True).exists()

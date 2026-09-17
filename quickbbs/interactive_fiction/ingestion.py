"""Scanner ingestion for game folders under Albums/interactive_fiction/
Game-folder ingestion.

Two entry points the scan command calls as an additive post-pass after its
own normal work — the only touch to existing scan code is two call sites in
quickbbs/management/commands/scan.py, not a change to update_database_from_disk
itself:

- ingest_stories(): after --add_files, create a Story for every real game
  folder under Albums/interactive_fiction/ with no matching
  Story.source_fqfn yet.
- verify_stories(): after --verify_files, tombstone Story rows whose source
  file is gone, and re-validate/refresh rows whose source file changed
  (sha256 drift) or reappeared after being tombstoned.

**Game-folder model**: a game is a
directory directly under `Albums/interactive_fiction/` containing exactly
one mandatory `__init__.py` manifest (GAME_TITLE, GAME_AUTHOR,
REQUIRED_PLUGINS, MAIN_STORY_FILE). One folder maps onto exactly one
Story row, built from the `.inkj` file MAIN_STORY_FILE names — a .inkj is
already a complete, self-contained game, never a chapter of something
larger, so any OTHER .inkj present in the same folder is simply ignored
by ingestion. A folder missing `__init__.py`, or whose MAIN_STORY_FILE
doesn't match a real file present, is a real, explicit ingestion failure
for that one folder (Story.game_ingestion_error set, surfaced in Django
admin per the plan's own decided hard-failure + admin-visible-flag
behavior) — never a silent skip or a guessed fallback.
REQUIRED_PLUGINS is copied onto the Story row verbatim from the manifest
(plain strings, read from `manifest.yaml` via `ink_engine.game_folder.read_manifest()`
like every other manifest field) — ingestion never resolves these names against
`discover_api_descriptors()`, since that would require the game's own
`.py` files to already be loaded (real code execution), which is exactly
what `Story.is_engine_trusted` gates on. Resolving/loading those plugins
for real is a separate, later, explicit admin action (marking the Story
trusted), not a precondition for the Story existing at all.

Every real .inkj candidate still goes through the same full validation
(validate_story_upload, imported from interactive_fiction.story_views) —
a mislabeled .inkj that isn't compiled Ink is rejected and logged, never
stored as a story.
"""

from __future__ import annotations

import logging
import os
import zipfile
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model

from ink_engine.bundle_integrity import recorded_hashes, unrecognized_bundle_version, verify_bundle
from ink_engine.game_folder import (
    GameFolderError,
    check_manifest_supported,
    read_manifest,
)
from ink_engine.game_source import GameSourceError, open_game_source
from interactive_fiction.bundle_media import build_cover_thumbnail
from interactive_fiction.images import find_file_by_path
from interactive_fiction.models import Story
from interactive_fiction.story_views import (
    create_story_from_compiled_json,
    unique_story_slug,
    validate_story_upload,
)
from quickbbs.common import normalize_fqpn
from quickbbs.models import DirectoryIndex, FileIndex

logger = logging.getLogger(__name__)


class _GameManifestError(Exception):
    """A real, explicit game-folder ingestion failure — the message is
    stored verbatim in Story.game_ingestion_error and logged, never
    silently swallowed."""


def _load_game_manifest(game_dir: Path) -> dict[str, Any]:
    """Read one game folder's `manifest.yaml`.

    A thin wrapper over `ink_engine.game_folder.read_manifest()`, which
    owns the parse and its mtime-keyed cache. This function's own job is
    QuickBBS ingestion policy: turning "this folder has no readable
    manifest" into `_GameManifestError`, whose message is stored verbatim
    in `Story.game_ingestion_error`.

    Args:
        game_dir: The game folder's real filesystem path.

    Returns:
        The manifest as a dict. Absent fields are simply absent keys.

    Raises:
        _GameManifestError: The folder has no readable manifest, or
            declares a manifest version or story format this engine
            cannot play.
    """
    try:
        check_manifest_supported(game_dir)
        return read_manifest(game_dir)
    except GameFolderError as error:
        raise _GameManifestError(f"Game folder '{game_dir.name}': {error}") from error


def read_manifest_value(game_dir: Path, field: str, default: Any = None) -> Any:
    """Read one value from a game folder's manifest.

    The manifest is the single source of truth for everything about a
    game, so anything a game declares about itself — which play layout it
    wants, what it is called — is read from here rather than copied onto a
    Story column where the two could drift apart.

    Args:
        game_dir: The game folder's real filesystem path.
        field: The manifest key to read.
        default: What to return when the folder has no readable manifest,
            or the manifest does not carry this field.

    Returns:
        The value, or `default`.
    """
    try:
        return _load_game_manifest(game_dir).get(field, default)
    except _GameManifestError:
        return default


def _resolve_main_story_path(game_dir: Path, manifest: Any) -> str:
    """Resolve which real `.inkj` file in `game_dir` is this game's Story source.

    Args:
        game_dir: The game folder's real filesystem path.
        manifest: The already-loaded manifest module (see _load_game_manifest).

    Returns:
        The main story file's full path, as a string.

    Raises:
        _GameManifestError: The manifest has no MAIN_STORY_FILE, or names
            a file that doesn't exist in `game_dir` — any other .inkj
            files present are not a valid fallback, per the plan's own
            "ignore, don't guess" rule.
    """
    main_story_file = manifest.get("MAIN_STORY_FILE")
    if not main_story_file:
        raise _GameManifestError(f"Game folder '{game_dir.name}': manifest.yaml has no MAIN_STORY_FILE")
    main_story_path = game_dir / main_story_file
    if not main_story_path.is_file():
        raise _GameManifestError(f"Game folder '{game_dir.name}': MAIN_STORY_FILE '{main_story_file}' does not exist in this folder")
    return str(main_story_path)


def game_folders() -> list[Path]:
    """Return every real game folder directly under Albums/interactive_fiction/.

    A "game folder" here means any directory at all under that path — a
    missing `__init__.py` is a real ingestion failure for that folder
    (see `_ingest_one_game_folder`), not grounds to exclude it from this
    listing; distinguishing "not a game" from "a broken game" is exactly
    the point of surfacing errors in admin rather than silently skipping.

    Args:
        None.

    Returns:
        Every direct subdirectory of Albums/interactive_fiction/, sorted
        by name. Empty if that path doesn't exist at all yet.
    """
    games_root = Path(DirectoryIndex.get_albums_root()) / "interactive_fiction"
    if not games_root.is_dir():
        return []
    return sorted((p for p in games_root.iterdir() if p.is_dir()), key=lambda p: p.name)


def _get_scan_owner():
    """Look up the dedicated scanner-ingestion owner account.

    Args:
        None.

    Returns:
        The User instance named by settings.IF_SCAN_DEFAULT_OWNER, or None
        if that account doesn't exist — callers must fail loudly (log,
        skip) rather than guessing an owner.
    """
    try:
        return get_user_model().objects.get(username=settings.IF_SCAN_DEFAULT_OWNER)
    except get_user_model().DoesNotExist:
        logger.error(
            "IF_SCAN_DEFAULT_OWNER account '%s' does not exist — no .inkj files will be ingested this run.",
            settings.IF_SCAN_DEFAULT_OWNER,
        )
        return None


def find_inkj_file_by_path(full_filepathname: str) -> FileIndex | None:
    """Resolve one .inkj file's full path directly to its live FileIndex row.

    A `.inkj`-filtered wrapper over
    `interactive_fiction.images.find_file_by_path`.

    Args:
        full_filepathname: The full path to look up (e.g. Story.source_fqfn).

    Returns:
        The matching live FileIndex row (filetype .inkj, not ignored, not
        delete_pending), or None if no such row exists (including when the
        containing directory itself has no DirectoryIndex row).
    """
    return find_file_by_path(full_filepathname, additional_filters={"filetype__fileext__iexact": ".inkj"})


def find_game_file_by_path(full_filepathname: str) -> FileIndex | None:
    """Resolve a story's own source file to its gallery row, whatever it is.

    Unlike `find_inkj_file_by_path` this places no extension filter: a
    bundle's source is a `.zip`, and filtering for `.inkj` answers None
    for every bundled game.

    Args:
        full_filepathname: The source file's real, resolved full path.

    Returns:
        The FileIndex row, or None if the file is not tracked.
    """
    return find_file_by_path(full_filepathname)


def _resolve_game_folder(owner, game_dir: Path) -> tuple[Any, str, FileIndex] | None:
    """Resolve one game folder's manifest, main-story path, and tracked
    gallery file — the shared validation prefix for both the create and
    refresh paths in _ingest_one_game_folder.

    Args:
        owner: The scanner-ingestion owner account.
        game_dir: The candidate game folder's real filesystem path.

    Returns:
        (manifest module, main story's full path, its FileIndex row), or
        None if any real validation step failed — in which case a
        matching Story row already has `game_ingestion_error` set (see
        _record_game_ingestion_error) and the error is already logged.
    """
    try:
        manifest = _load_game_manifest(game_dir)
        main_story_fqfn = _resolve_main_story_path(game_dir, manifest)
    except _GameManifestError as exc:
        logger.error("Game folder ingestion failed: %s", exc)
        _record_game_ingestion_error(owner, game_dir, str(exc))
        return None

    file_entry = find_inkj_file_by_path(main_story_fqfn)
    if file_entry is None:
        error = f"Game folder '{game_dir.name}': MAIN_STORY_FILE is not a tracked gallery file (run the gallery scanner first)"
        logger.error("Game folder ingestion failed: %s", error)
        _record_game_ingestion_error(owner, game_dir, error)
        return None

    return manifest, main_story_fqfn, file_entry


def _ingest_one_game_folder(owner, game_dir: Path) -> bool:
    """Create or refresh the one Story for one real game folder.

    Shared by ingest_stories() (full batch pass over every game folder)
    and ingest_stories_in_directory() (single-folder, called live from
    the web view path when that exact folder's files changed) — both need
    the same manifest-read/validate/create-or-refresh sequence per
    candidate folder, just scoped to a different set of candidates.

    A folder already backed by a Story row (matched by game_dir's own
    resolved main-story path as `source_fqfn`) is refreshed via
    _refresh_from_disk() instead of re-created — this keeps the same
    Story.pk across a manifest/content update, so every player's
    SaveState/CurrentGame reconnects without FK churn, matching
    verify_stories()'s own existing "restored"/"refreshed" behavior.

    Args:
        owner: The scanner-ingestion owner account (see _get_scan_owner()).
        game_dir: The candidate game folder's real filesystem path.

    Returns:
        True if a Story row was created or successfully refreshed; False
        on any real ingestion failure (manifest error, unreadable/invalid
        `.inkj`) — in every False case, a matching Story row (created if
        none existed) has `game_ingestion_error` set and is left
        unavailable, per the plan's own decided hard-failure + admin-
        visible-flag behavior; nothing is ever silently dropped.
    """
    resolved = _resolve_game_folder(owner, game_dir)
    if resolved is None:
        return False
    manifest, main_story_fqfn, file_entry = resolved

    existing = Story.objects.filter(source_fqfn=main_story_fqfn).first()
    if existing is not None:
        # A refresh failure here (invalid replacement content) is
        # _refresh_from_disk's own existing, correct "keep the working
        # story as-is" behavior — NOT a real ingestion failure to record
        # via game_ingestion_error/is_available=False, which would wrongly
        # take down an otherwise-fine, already-ingested game over a bad
        # in-progress file write. _refresh_from_disk already logs the
        # real reason.
        if _refresh_from_disk(existing, file_entry):
            _apply_game_manifest_fields(existing, manifest)
            return True
        return False

    data = _read_and_validate_main_story(owner, game_dir, main_story_fqfn)
    if data is None:
        return False

    _create_or_repurpose_game_story(owner, game_dir, resolved=(manifest, main_story_fqfn, file_entry), data=data)
    return True


def _read_and_validate_main_story(owner, game_dir: Path, main_story_fqfn: str) -> dict[str, Any] | None:
    """Read and validate a game folder's real main-story file's bytes.

    Args:
        owner: The scanner-ingestion owner account (for error recording).
        game_dir: The candidate game folder's real filesystem path.
        main_story_fqfn: The main story file's real, resolved full path.

    Returns:
        The validated compiled-Ink JSON dict, or None on any real failure
        (unreadable file, invalid content) — in which case a matching
        Story row already has `game_ingestion_error` set and the error is
        already logged.
    """
    try:
        with open(main_story_fqfn, "rb") as story_file:
            raw_bytes = story_file.read()
    except OSError as exc:
        error = f"Game folder '{game_dir.name}': could not read MAIN_STORY_FILE: {exc}"
        logger.error("Game folder ingestion failed: %s", error)
        _record_game_ingestion_error(owner, game_dir, error)
        return None

    data, errors = validate_story_upload(raw_bytes)
    if data is None:
        error = f"Game folder '{game_dir.name}': MAIN_STORY_FILE is not valid compiled Ink JSON: {'; '.join(errors)}"
        logger.error("Game folder ingestion failed: %s", error)
        _record_game_ingestion_error(owner, game_dir, error)
        return None

    return data


def _create_or_repurpose_game_story(owner, game_dir: Path, *, resolved: tuple[Any, str, FileIndex], data: dict[str, Any]) -> None:
    """Create this game folder's first-ever Story row, or repurpose its
    existing placeholder row (from a previously-failed ingestion) rather
    than leaving that row behind as an orphaned duplicate.

    Args:
        owner: The scanner-ingestion owner account.
        game_dir: The candidate game folder's real filesystem path.
        resolved: (manifest module, main story's real full path, its
            current FileIndex row) — the same tuple _resolve_game_folder
            returns.
        data: The already-validated compiled-Ink JSON dict.

    Returns:
        None.
    """
    manifest, main_story_fqfn, file_entry = resolved
    title = str(manifest.get("GAME_TITLE") or game_dir.name)
    placeholder = Story.objects.filter(source_fqfn=_placeholder_fqfn(game_dir)).first()
    if placeholder is not None:
        placeholder.title = title
        placeholder.compiled_json = data
        placeholder.ink_version = str(data.get("inkVersion", ""))
        placeholder.source_fqfn = main_story_fqfn
        placeholder.source_sha256 = file_entry.file_sha256 or ""
        placeholder.is_available = True
        placeholder.save(update_fields=["title", "compiled_json", "ink_version", "source_fqfn", "source_sha256", "is_available", "updated_at"])
        _apply_game_manifest_fields(placeholder, manifest)
        return

    story = create_story_from_compiled_json(owner, title, data, source_fqfn=main_story_fqfn, source_sha256=file_entry.file_sha256 or "")
    _apply_game_manifest_fields(story, manifest)


def _apply_game_manifest_fields(story: Story, manifest: Any) -> None:
    """Copy a game folder's manifest fields onto its Story row and clear
    any prior ingestion error — this folder just ingested successfully.

    Args:
        story: The Story row to update (mutated and saved in place).
        manifest: The already-loaded, already-validated manifest module.
    Returns:
        None.
    """
    story.title = str(manifest.get("GAME_TITLE") or story.title)
    story.game_author = str(manifest.get("GAME_AUTHOR") or "")
    story.game_required_plugins = list(manifest.get("REQUIRED_PLUGINS") or [])
    story.game_new_game_fields = list(manifest.get("NEW_GAME_FIELDS") or [])
    story.game_ingestion_error = ""
    story.save(update_fields=["title", "game_author", "game_required_plugins", "game_new_game_fields", "game_ingestion_error", "updated_at"])


def _placeholder_fqfn(game_dir: Path) -> str:
    """Return the stable, non-real `source_fqfn` used for a game folder's
    Story row while its real main-story path can't be resolved (manifest
    missing/invalid, MAIN_STORY_FILE not found).

    Args:
        game_dir: The game folder's real filesystem path.

    Returns:
        A per-folder-stable placeholder path — never a real file — so
        repeated ingestion attempts against the same broken folder update
        the same Story row instead of creating a new one each time, and
        so a later successful ingestion can find and repurpose that same
        row (see `_ingest_one_game_folder`'s own placeholder-repurposing
        step) rather than leaving it behind as an orphaned duplicate.
    """
    return str(game_dir / "__game_folder__")


def _record_game_ingestion_error(owner, game_dir: Path, error: str) -> None:
    """Create (if needed) or update the Story row representing a game
    folder that failed to ingest, so the failure is visible in Django
    admin rather than log-only.

    Args:
        owner: The scanner-ingestion owner account.
        game_dir: The failed game folder's real filesystem path.
        error: The human-readable failure reason (stored verbatim).

    Returns:
        None.
    """
    story = Story.objects.filter(source_fqfn=_placeholder_fqfn(game_dir)).first()
    if story is None:
        story = Story.objects.create(
            owner=owner,
            title=game_dir.name,
            slug=unique_story_slug(game_dir.name),
            compiled_json={},
            source_fqfn=_placeholder_fqfn(game_dir),
            is_available=False,
        )
    _set_game_ingestion_error(story, error)


def _set_game_ingestion_error(story: Story, error: str) -> None:
    """Record a real ingestion failure on an existing Story row.

    Args:
        story: The Story row to update (mutated and saved in place).
        error: The human-readable failure reason (stored verbatim).

    Returns:
        None.
    """
    story.game_ingestion_error = error
    story.is_available = False
    story.save(update_fields=["game_ingestion_error", "is_available", "updated_at"])


#: What `check_bundle_integrity()` decided about one bundle.
INTEGRITY_OK = "ok"
INTEGRITY_NEW_VERSION = "new_version"
INTEGRITY_TAMPERED = "tampered"
INTEGRITY_INVALID = "invalid"


def check_bundle_integrity(story: Story, bundle_path: Path) -> tuple[str, str]:
    """Decide whether a bundle is unchanged, a new release, or tampered with.

    A bundle that fails `verify_bundle()` is refused whatever its version:
    its own recorded hashes do not describe its own contents, so a changed
    version string would otherwise launder a corrupt bundle.

    Otherwise the three stored hashes are compared with the bundle's. A
    difference is a new release when `GAME_VERSION` also changed, and
    tampering when it did not -- the same bundle claiming to be the same
    version is not free to have different contents.

    Args:
        story: The row holding what was recorded at the last ingestion. A
            row with no stored hashes has never been ingested as a bundle
            and is treated as a new release, so its hashes get recorded.
        bundle_path: The `.zip` to check.

    Returns:
        `(decision, detail)` -- one of the INTEGRITY_* constants, and a
        human-readable reason (empty when nothing is wrong).
    """
    try:
        problems = verify_bundle(bundle_path)
        hashes = recorded_hashes(bundle_path)
        version = str(read_manifest_value(bundle_path, "GAME_VERSION", "") or "")
    except (GameSourceError, GameFolderError) as error:
        return INTEGRITY_INVALID, str(error)
    except (OSError, zipfile.BadZipFile) as error:
        # verify_bundle() opens the archive itself and lets a corrupt file
        # raise; a scan reads whatever is on disk and must not die on one.
        return INTEGRITY_INVALID, f"cannot read bundle '{bundle_path.name}': {error}"

    # A container version this reader does not know is a warning, not a
    # refusal: the layout has stayed backward-compatible, and refusing a
    # game over it would be a worse answer than ingesting and saying so.
    unknown_version = unrecognized_bundle_version(bundle_path)
    if unknown_version is not None:
        logger.warning(
            "interactive_fiction.ingestion: bundle '%s' declares bundle_version %s, which this reader does not know; "
            "ingesting anyway, but anything the newer format adds is unaccounted for",
            bundle_path.name,
            unknown_version,
        )

    if problems:
        return INTEGRITY_INVALID, "; ".join(problems)

    stored = (story.bundle_manifest_sha256, story.bundle_directory_sha256, story.bundle_story_sha256)
    if not any(stored):
        return INTEGRITY_NEW_VERSION, ""
    if stored == (hashes["manifest"], hashes["directory"], hashes["story"]):
        return INTEGRITY_OK, ""
    if version != story.game_version:
        return INTEGRITY_NEW_VERSION, ""
    return INTEGRITY_TAMPERED, (
        f"bundle contents changed but GAME_VERSION is still '{version}' -- "
        f"the game has been modified since it was ingested and will not run until an administrator re-approves it"
    )


def record_bundle_hashes(story: Story, bundle_path: Path) -> None:
    """Store a bundle's own hashes and version on its Story row.

    Args:
        story: The row to update (mutated and saved in place).
        bundle_path: The bundle whose claims are recorded.
    """
    hashes = recorded_hashes(bundle_path)
    story.bundle_manifest_sha256 = hashes["manifest"]
    story.bundle_directory_sha256 = hashes["directory"]
    story.bundle_story_sha256 = hashes["story"]
    story.game_version = str(read_manifest_value(bundle_path, "GAME_VERSION", "") or "")
    story.save(
        update_fields=[
            "bundle_manifest_sha256",
            "bundle_directory_sha256",
            "bundle_story_sha256",
            "game_version",
            "updated_at",
        ]
    )


def game_bundles() -> list[Path]:
    """Return every `.zip` bundle under Albums/interactive_fiction/.

    A bundle sits either directly in the games root or one level down in
    its own game folder (`<game>/<game>.zip`, which is how the published
    bundles are laid out). Both are found; nothing deeper is, so an
    archive a game merely SHIPS is never mistaken for the game itself.

    Returns:
        Every bundle, sorted by path. Empty if the games root does not
        exist.
    """
    games_root = Path(DirectoryIndex.get_albums_root()) / "interactive_fiction"
    if not games_root.is_dir():
        return []
    bundles = [entry for entry in games_root.iterdir() if entry.is_file() and entry.suffix.lower() == ".zip"]
    for game_dir in (entry for entry in games_root.iterdir() if entry.is_dir()):
        bundles.extend(entry for entry in game_dir.iterdir() if entry.is_file() and entry.suffix.lower() == ".zip")
    return sorted(bundles, key=str)


def canonical_game_path(path: Path) -> Path:
    """Return `path` in the form every stored `source_fqfn` uses.

    `DirectoryIndex.get_albums_root()` is `normalize_fqpn()` output --
    lowercased -- so a path discovered by walking it is already canonical
    and one handed in by a caller may not be. Comparing the two forms
    silently matches nothing.

    Args:
        path: A game folder or bundle path, in any case.

    Returns:
        The same path, lowercased to match the scan's own form.
    """
    return Path(str(path).lower())


def _ingest_one_bundle(owner, bundle_path: Path) -> bool:
    """Create or refresh the one Story for one `.zip` bundle.

    A bundle is self-contained: its story and media are read through
    `GameSource` rather than resolved against per-file gallery rows, so
    none of the `FileIndex` machinery the folder path uses applies.

    Integrity is decided first and governs everything after it. A bundle
    that fails verification, or that changed without saying so, is left
    unavailable with the reason on the row -- an administrator's problem,
    never a silent downgrade to "plays anyway".

    Args:
        owner: The scanner-ingestion owner account.
        bundle_path: The bundle's real filesystem path.

    Returns:
        True if a Story row was created or refreshed; False on any
        failure, in which case a row carries `game_ingestion_error` and
        is unavailable.
    """
    bundle_path = canonical_game_path(bundle_path)
    existing = Story.objects.filter(source_fqfn=str(bundle_path)).first()
    decision, detail = check_bundle_integrity(existing or Story(), bundle_path)
    if decision in (INTEGRITY_INVALID, INTEGRITY_TAMPERED):
        error = f"Game bundle '{bundle_path.name}': {detail}"
        logger.error("Game bundle ingestion refused: %s", error)
        if existing is not None:
            _set_game_ingestion_error(existing, error)
        else:
            _record_game_ingestion_error(owner, bundle_path, error)
        return False

    try:
        manifest = _load_game_manifest(bundle_path)
        source = open_game_source(bundle_path)
    except (_GameManifestError, GameSourceError) as exc:
        error = f"Game bundle '{bundle_path.name}': {exc}"
        logger.error("Game bundle ingestion failed: %s", error)
        _record_game_ingestion_error(owner, bundle_path, error)
        return False

    try:
        main_story_file = manifest.get("MAIN_STORY_FILE")
        if not main_story_file or not source.exists(main_story_file):
            error = f"Game bundle '{bundle_path.name}': MAIN_STORY_FILE '{main_story_file}' is not in the bundle"
            logger.error("Game bundle ingestion failed: %s", error)
            _record_game_ingestion_error(owner, bundle_path, error)
            return False

        data, errors = validate_story_upload(source.read_bytes(main_story_file))
        if data is None:
            error = f"Game bundle '{bundle_path.name}': MAIN_STORY_FILE is not valid compiled Ink JSON: {'; '.join(errors)}"
            logger.error("Game bundle ingestion failed: %s", error)
            _record_game_ingestion_error(owner, bundle_path, error)
            return False
    finally:
        source.close()

    title = str(manifest.get("GAME_TITLE") or bundle_path.stem)
    story = existing or Story.objects.filter(source_fqfn=_placeholder_fqfn(bundle_path)).first()
    if story is None:
        story = create_story_from_compiled_json(owner, title, data, source_fqfn=str(bundle_path), source_sha256="")
    else:
        story.title = title
        story.compiled_json = data
        story.ink_version = str(data.get("inkVersion", ""))
        story.source_fqfn = str(bundle_path)
        story.is_available = True
        story.save(update_fields=["title", "compiled_json", "ink_version", "source_fqfn", "is_available", "updated_at"])

    _apply_game_manifest_fields(story, manifest)
    # Recorded once here so playing never re-reads the manifest to find
    # the story, and the library grid never opens a bundle to draw a card.
    story.main_story_member = str(main_story_file)
    story.cover_thumbnail = build_cover_thumbnail(bundle_path)
    story.save(update_fields=["main_story_member", "cover_thumbnail", "updated_at"])
    record_bundle_hashes(story, bundle_path)
    return True


def ingest_stories() -> int:
    """Create or refresh a Story for every real game folder under
    Albums/interactive_fiction/.

    Args:
        None.

    Returns:
        The number of game folders successfully ingested (created or
        refreshed) this pass. A folder that failed (see
        _ingest_one_game_folder) is not counted here, but is still
        recorded — via a Story row with game_ingestion_error set — so it
        remains visible in admin.
    """
    owner = _get_scan_owner()
    if owner is None:
        return 0

    ingested = 0
    for game_dir in game_folders():
        if _ingest_one_game_folder(owner, game_dir):
            ingested += 1
    # Every bundle is re-examined on every pass, not only new ones: a
    # bundle that changed underneath an ingested row is exactly what the
    # integrity check exists to catch.
    for bundle_path in game_bundles():
        if _ingest_one_bundle(owner, bundle_path):
            ingested += 1

    return ingested


def ingest_stories_in_directory(directory: DirectoryIndex) -> int:
    """Ingest one game folder, if `directory` is itself a real, direct
    game folder under Albums/interactive_fiction/.

    The live-web counterpart to ingest_stories(): called from
    update_database_from_disk() right after sync_files() so a game
    folder's content becomes playable the moment its directory is next
    viewed, matching how any other file type is picked up live — instead
    of requiring a separate `manage.py scan --add_files` batch run.
    Directories that are NOT themselves a direct child of
    Albums/interactive_fiction/ (an ordinary gallery directory, or a
    sub-directory nested inside a game folder) are correctly a no-op here
    — a live single-directory sync has no way to know a nested change
    should re-trigger its ENCLOSING game folder's own manifest read, and
    guessing at that relationship risks re-ingesting the wrong folder;
    `manage.py scan --verify_files`'s own batch verify_stories() pass
    remains the correct, complete way to pick up such a change.

    Args:
        directory: The DirectoryIndex just synced by update_database_from_disk().

    Returns:
        1 if this directory is a real game folder and was successfully
        ingested; 0 otherwise (not a game folder, ingestion failed, or no
        scan owner configured).
    """
    games_root = normalize_fqpn(str(Path(DirectoryIndex.get_albums_root()) / "interactive_fiction"))
    directory_path = normalize_fqpn(directory.fqpndirectory)
    parent_path = normalize_fqpn(os.path.dirname(directory_path.rstrip(os.sep)))
    if parent_path != games_root:
        return 0

    owner = _get_scan_owner()
    if owner is None:
        return 0

    return 1 if _ingest_one_game_folder(owner, Path(directory_path)) else 0


def _tombstone(story: Story) -> None:
    """Mark a story unavailable and clear its compiled_json (a tombstone).

    Args:
        story: The scanner-ingested story whose source file is gone.

    Returns:
        None.
    """
    story.is_available = False
    story.compiled_json = {}
    story.save(update_fields=["is_available", "compiled_json", "updated_at"])


def _refresh_from_disk(story: Story, file_entry: FileIndex) -> bool:
    """Re-validate and reload a story's compiled_json from its current source file.

    Args:
        story: The scanner-ingested story to refresh (mutated in place on
            success).
        file_entry: The current FileIndex row for story.source_fqfn.

    Returns:
        True if the refresh applied (and was saved); False if the file
        couldn't be read or failed validation, in which case story is left
        untouched — a half-written file mid-copy must not take down a
        working story, and a real validation failure is logged rather than
        silently discarding the existing content.
    """
    try:
        with open(story.source_fqfn, "rb") as story_file:
            raw_bytes = story_file.read()
    except OSError as exc:
        logger.warning("Could not re-read story file '%s': %s", story.source_fqfn, exc)
        return False

    data, errors = validate_story_upload(raw_bytes)
    if data is None:
        logger.warning("Re-validation failed for '%s', keeping existing content: %s", story.source_fqfn, "; ".join(errors))
        return False

    story.compiled_json = data
    story.ink_version = str(data.get("inkVersion", ""))
    story.source_sha256 = file_entry.file_sha256 or ""
    story.is_available = True
    story.save(update_fields=["compiled_json", "ink_version", "source_sha256", "is_available", "updated_at"])
    return True


def verify_stories() -> tuple[int, int, int]:
    """Tombstone stories whose source file is gone; refresh ones that changed or reappeared.

    Args:
        None.

    Returns:
        (tombstoned_count, restored_count, refreshed_count) — restored_count
        is stories whose source file reappeared at the same path (matched
        by source_fqfn) and had compiled_json refilled on the same row, so
        every player's SaveState/CurrentGame reconnects without FK churn
        (both FKs point at the same, unchanged, Story.pk).
    """
    tombstoned = restored = refreshed = 0

    for story in Story.objects.exclude(source_fqfn="").defer("compiled_json"):
        # A bundle is one self-contained file, verified by its own hashes
        # at ingestion; it has no per-file gallery row to look up, and
        # asking for one answers None and tombstones a live game.
        if story.bundle_path is not None:
            if not story.bundle_path.is_file() and story.is_available:
                _tombstone(story)
                tombstoned += 1
            continue

        file_entry = find_inkj_file_by_path(story.source_fqfn)
        if file_entry is None:
            if story.is_available:
                _tombstone(story)
                tombstoned += 1
            continue

        was_tombstoned = not story.is_available
        sha_changed = bool(file_entry.file_sha256) and file_entry.file_sha256 != story.source_sha256
        if not (was_tombstoned or sha_changed):
            continue

        if _refresh_from_disk(story, file_entry):
            if was_tombstoned:
                restored += 1
            else:
                refreshed += 1

    # Re-run manifest-driven ingestion for every real game folder — this
    # retries a previously-broken folder (whose placeholder Story row has
    # a non-real source_fqfn the loop above can never match) and refreshes
    # game_required_plugins/game_new_game_fields from the manifest if
    # either changed, even when the main .inkj's own content didn't.
    owner = _get_scan_owner()
    if owner is not None:
        for game_dir in game_folders():
            _ingest_one_game_folder(owner, game_dir)

    return tombstoned, restored, refreshed

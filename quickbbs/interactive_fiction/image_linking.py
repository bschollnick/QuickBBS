"""Resolve a game's `# image:`/`# video:` Ink tags to real gallery files
and (re)link them as StoryImage rows — the graphics half of Interactive
Fiction ingestion.

Moved here from a game-conversion tooling folder 2026-08-27, unchanged in
its resolution logic. It had been filed with the one-shot JavaScript->Ink
conversion scripts it was written alongside,
but it is not one-shot: it has to run every time a story's tags change, so
it belongs in the ingestion path. Filing it as conversion tooling is what
let a graphics outage happen — new `# image:` tags were added by later
conversion passes and nothing in ingestion knew to link them. Now called
by `interactive_fiction.ingestion.relink_story_images()`, which
`scan_if_stories` runs on every pass.

Game-agnostic by construction. The two pieces of per-game knowledge —
which gallery folder each character's tag prefix maps to, and which
top-level non-character roots exist — are game DATA, loaded from the game
folder's own `image_mapping.py` (see `_load_game_image_mapping`),
mirroring how `engine_plugins/` (generic) and each game folder's own
plugin modules (specific) already split. A game with no such file simply
has no character-prefixed tags.

The source-image tree's gallery location is never hardcoded: it is
discovered live via DirectoryIndex, keyed by the game manifest's own
SOURCE_GAME_VERSION (see `find_gallery_images_root`), since a scan can
place that content at any real path on a given install, and a game-version
bump only needs that one manifest constant updated.

Linking is a full reconcile, not an append: see `relink_story_images` in
ingestion.py for the unlink-and-relink contract.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ink_engine.game_folder import read_module_literals

from interactive_fiction.images import link_story_image
from interactive_fiction.models import StoryImage
from quickbbs.models import DirectoryIndex

logger = logging.getLogger(__name__)

# Keyed by game folder, not module-global: two games have two different
# source-image trees, and a shared cache would serve the first game's
# images root to the second. The children cache is keyed by
# DirectoryIndex.pk so it stays correct across games either way.
_GALLERY_IMAGES_ROOT_DIR: dict[str, Any] = {}  # str(game_dir) -> cached DirectoryIndex row
_DIR_CHILDREN_CACHE: dict[int, dict[str, Any]] = {}  # DirectoryIndex.pk -> {lowercased child name: DirectoryIndex}


def _load_game_image_mapping(game_dir: Path) -> tuple[dict[str, str | None], set[str]]:
    """Load one game folder's own tag-prefix -> gallery-folder mapping.

    This is per-game DATA, not engine logic: a game's tag prefixes are its
    own character names, and a different game would have entirely
    different ones. Read from the game folder's `image_mapping.py` with
    the same AST-only literal evaluation `ingestion._load_game_manifest`
    uses, so an untrusted Albums-tree file is never imported/executed.

    Args:
        game_dir: The game folder to load `image_mapping.py` from.

    Returns:
        (CHARACTER_KEY_TO_GALLERY_FOLDER, NON_CHARACTER_ROOTS). Both are
        empty when the game folder has no `image_mapping.py`, or it
        declares neither name — a game whose tags are all `shared/`-
        prefixed or plainly-pathed needs no mapping at all.
    """
    literals = _read_game_mapping_literals(game_dir)

    folders_raw = literals.get("CHARACTER_KEY_TO_GALLERY_FOLDER")
    roots_raw = literals.get("NON_CHARACTER_ROOTS")
    folders = {str(k).lower(): v for k, v in folders_raw.items()} if isinstance(folders_raw, dict) else {}
    roots = {str(v).lower() for v in roots_raw} if isinstance(roots_raw, (set, list, tuple)) else set()
    return folders, roots


def _load_game_model_var_seeds(game_dir: Path) -> dict[str, list[str]]:
    """Load one game folder's own MODEL_VAR_VALUE_SEEDS, if it declares any.

    A seed supplies the possible values of a VAR that `build_model_var_values`
    cannot discover by regex — a numeric VAR interpolated into a folder
    name, or one assigned only from a function parameter so the literals
    live at the call sites. Which VARs need seeding is a fact about a
    specific game's content, so it is game data.

    Args:
        game_dir: The game folder to load `image_mapping.py` from.

    Returns:
        {var name (lowercased): [literal values]}, empty when the game
        declares no seeds.
    """
    raw = _read_game_mapping_literals(game_dir).get("MODEL_VAR_VALUE_SEEDS")
    if not isinstance(raw, dict):
        return {}
    return {str(name).lower(): [str(v) for v in values] for name, values in raw.items() if isinstance(values, (list, tuple, set))}


def _read_game_mapping_literals(game_dir: Path) -> dict[str, Any]:
    """Read every top-level literal assignment from a game's `image_mapping.py`.

    A thin call into `ink_engine.game_folder.read_module_literals()` — the
    shared AST-as-data primitive every manifest/mapping reader in this
    app builds on (see `ingestion._load_game_manifest`). A missing or
    unparseable file yields nothing rather than raising — a game is
    entitled to have no mapping at all. A name assigned a non-literal
    value is warned about (every top-level name in this file is
    meaningful, unlike a manifest's fixed field list) and omitted.

    Args:
        game_dir: The game folder to read `image_mapping.py` from.

    Returns:
        {assigned name: literal value} for every top-level assignment
        whose value is a Python literal; empty if the file is absent or
        cannot be parsed.
    """
    mapping_path = game_dir / "image_mapping.py"
    result = read_module_literals(mapping_path)
    for name in sorted(result.skipped):
        logger.warning("'%s' in '%s' is not a literal, ignoring.", name, mapping_path)
    return result.literals


def find_gallery_images_root(game_dir: Path, source_game_version: str | None):
    """Locate the real gallery DirectoryIndex row for one game's own
    source-image tree, via the game manifest's own SOURCE_GAME_VERSION
    field -- never a hardcoded absolute path.

    A gallery scan can land this content at any real filesystem path
    (a different install, a re-organized Albums tree, a future game
    version scanned to a differently-named directory) -- what's stable
    is the directory's own NAME (SOURCE_GAME_VERSION, e.g.
    a versioned source-tree name) and its own real "images" child, both discovered live
    via DirectoryIndex's own tree rather than assumed. Confirmed real:
    sibling game-version trees can exist side by side in the gallery --
    scoping to the manifest's own
    declared version, not a basename search across all three, avoids
    pulling an image from a different game revision that happens to
    share a filename.

    Args:
        game_dir: The game folder this tree belongs to (the cache key).
        source_game_version: That game manifest's own SOURCE_GAME_VERSION,
            passed in by the caller rather than read here — ingestion owns
            manifest loading, and reaching back into it from this module
            would make the two import each other.

    Returns:
        The real DirectoryIndex row for "<SOURCE_GAME_VERSION>/images/",
        or None when this game declares no SOURCE_GAME_VERSION (its tags,
        if any, reference gallery files by some other means) or that
        version has not been scanned into the gallery yet. Callers treat
        None as "resolve nothing this pass" rather than an error, so a
        game whose source tree is missing does not abort ingestion for
        every other game.
    """
    cache_key = str(game_dir)
    if cache_key in _GALLERY_IMAGES_ROOT_DIR:
        return _GALLERY_IMAGES_ROOT_DIR[cache_key]

    images_dir = None
    if not source_game_version:
        logger.info("'%s' declares no SOURCE_GAME_VERSION; no source-image tree to resolve against.", game_dir)
    else:
        version_dir = DirectoryIndex.objects.filter(fqpndirectory__iendswith=f"/{source_game_version}/").order_by("fqpndirectory").first()
        if version_dir is None:
            logger.warning("No gallery directory named '%s' found -- has the source game tree been scanned?", source_game_version)
        else:
            images_dir = version_dir.parent_dir.filter(fqpndirectory__iendswith="/images/").first()
            if images_dir is None:
                logger.warning("'%s' has no real 'images' subdirectory in the gallery.", source_game_version)

    _GALLERY_IMAGES_ROOT_DIR[cache_key] = images_dir
    return images_dir


def resolve_child_directory(parent, name: str):
    """Return `parent`'s own real child DirectoryIndex row matching `name`
    (case-insensitive), or None if no such child exists.

    Caches each parent's own children by lowercased name on first lookup
    (`_DIR_CHILDREN_CACHE`), since the same directories are walked
    repeatedly across thousands of tag resolutions in one run.

    Args:
        parent: The DirectoryIndex row to search under.
        name: The child directory's own name (case-insensitive).

    Returns:
        The matching child DirectoryIndex row, or None.
    """
    children = _DIR_CHILDREN_CACHE.get(parent.pk)
    if children is None:
        children = {}
        for child in parent.parent_dir.all():
            child_name = child.fqpndirectory.rstrip("/").rsplit("/", 1)[-1]
            children[child_name.lower()] = child
        _DIR_CHILDREN_CACHE[parent.pk] = children
    return children.get(name.lower())


# CHARACTER_KEY_TO_GALLERY_FOLDER / NON_CHARACTER_ROOTS now live in
# character_gallery_mapping.py, imported above (consolidated Step 3 of
# an image-triage design pass -- this
# script and retrofit_image_tags.py previously each declared their own
# copy, which had drifted cosmetically out of sync).

MEDIA_TAG_RE = re.compile(r"^\s*#\s*(image|video):\s*(.+?)\s*$")
INNERMOST_BRACE_RE = re.compile(r"\{([^{}]*)\}")
FILENAME_TOKEN_RE = re.compile(r"\S+\.(?:jpg|jpeg|png|gif|webp|bmp|mp4|webm)", re.IGNORECASE)


def _split_top_level(text: str, sep: str) -> list[str]:
    """Split `text` on `sep` at brace-depth 0 only.

    Args:
        text: The text to split.
        sep: The single-character separator to split on.

    Returns:
        The parts, in order.
    """
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


VAR_DECL_RE = re.compile(r'^\s*VAR\s+([a-z_][a-z0-9_]*)\s*=\s*"([^"]*)"', re.IGNORECASE | re.MULTILINE)
VAR_WRITE_RE = re.compile(r'~\s*([a-z_][a-z0-9_]*)\s*=\s*"([^"]*)"', re.IGNORECASE)
VAR_CHOSEN_CALL_RE = re.compile(r"([a-z_][a-z0-9_]*_model)_chosen\(\s*\"([^\"]*)\"", re.IGNORECASE)
# A second real model-picker dispatch shape, distinct from "*_model_chosen(":
# a plain "<name>_choose_model(model)" stitch (ellie.ink's ellie_choose_model,
# lauren.ink's lauren_choose_model, leanne.ink's leanne_choose_model,
# misslogan.ink's misslogan_choose_model -- all real, all corpus-standard,
# confirmed 2026-09-06 in this session's own model-picker conversion pass)
# whose own dispatcher name does not directly name the character id/attribute
# the way "*_model_chosen(" does -- it has to be read from the stitch's own
# body, which immediately writes the parameter through
# set_person_value_now("<character_id>", "<attribute>", <parameter>).
CHOOSE_MODEL_CALL_RE = re.compile(r"([a-z_][a-z0-9_]*)_choose_model\(\s*\"([^\"]*)\"", re.IGNORECASE)
CHOOSE_MODEL_STITCH_RE = re.compile(r"^\s*=\s*[a-z_][a-z0-9_]*_choose_model\(\s*([a-z_][a-z0-9_]*)\s*\)", re.IGNORECASE | re.MULTILINE)
# A direct literal write through the corpus's own standardized per-character
# accessor: `set_person_value_now("<character_id>", "<attribute>", "Literal")`.
# The more general real shape underlying VAR_CHOSEN_CALL_RE above -- a
# dispatcher/VAR wrapper around this same call is common but not universal
# (a character's own dress attribute can be set with a bare string literal
# at several sites with no dispatcher at all: `set_person_value_now(
# "<character_id>", "dress", "<literal>")`), so this is matched independently
# rather than assuming every real write goes through a "_chosen(" call.
PERSON_VALUE_WRITE_RE = re.compile(r'set_person_value_now\(\s*"([a-z_][a-z0-9_]*)"\s*,\s*"([a-z_][a-z0-9_]*)"\s*,\s*"([^"]*)"\s*\)', re.IGNORECASE)
FUNCTION_HEADER_RE = re.compile(r"^\s*={2,}\s*function\s+([a-z_][a-z0-9_]*)\s*\(", re.IGNORECASE | re.MULTILINE)
KNOT_HEADER_RE = re.compile(r"^\s*={2,}\s*[a-z_]", re.IGNORECASE | re.MULTILINE)
# A plain `[^"]*` body would truncate at the first quote INSIDE an
# embedded "{...}" interpolation -- real in a character's own model-return
# function, whose own return literal embeds a further person_value_now(...)
# call with its own quoted arguments (`"{person_value_now("<id>",
# "model")}/Younger"`).
# The alternation lets the body contain any run of non-quote characters OR
# one whole "{...}" block (which may itself contain quotes) before the
# closing quote.
RETURN_LITERAL_RE = re.compile(r'~\s*return\s+"((?:[^"{]|\{[^{}]*\})*)"', re.IGNORECASE)
# A tag's bare "{person_value_now("<character_id>", "<attribute>")}"
# interpolation (the corpus's own standardized per-character-fact accessor,
# 2026-09-06 corpus-wide EXTERNAL rename) reads the same fact
# "<character_id>_<attribute>_chosen(...)"/"~ <character_id>_<attribute> ="
# write sites already register under, via VAR_CHOSEN_CALL_RE/VAR_WRITE_RE --
# it just names it as an accessor CALL rather than a bare VAR. Recognized
# here and mapped onto that identical key, rather than added as a second,
# parallel value store (DRY): a scan that only knew the old plain-VAR shape
# would report every model choice converted onto this accessor as broken
# (confirmed live: 1275 tags corpus-wide, e.g. "abby/{person_value_now(...)}/
# abby0.jpg" resolving to a literal double-slash "abby//abby0.jpg" once the
# unresolved reference fell back to "").
PERSON_VALUE_CALL_RE = re.compile(r'^person_value_now\(\s*"([a-z_][a-z0-9_]*)"\s*,\s*"([a-z_][a-z0-9_]*)"\s*\)$', re.IGNORECASE)


def build_model_var_values(game_dir: Path) -> dict[str, list[str]]:
    """Scan the whole corpus for every literal value a "*_model"-style VAR
    or a zero-argument function can produce, for substituting into a bare
    "{X}"/"{X()}" tag interpolation with no ":"/"|" of its own.

    Covers four real shapes found in this corpus: a fixed, never-
    reassigned VAR declaration (`VAR X_model = "Carla"`, e.g.
    ellie_bartel_model/carol_bartel_model -- no real player choice, just
    one fixed literal), a plain `~ X_model = "Literal"` write (a later,
    in-play reassignment, e.g. donna_model's post-transform branches), a
    `X_model_chosen("Literal")` dispatch-call argument (the pattern each
    such VAR's own "X_model_chosen(chosenModel)" knot uses, where
    "chosenModel" itself is a parameter name, not a literal, so the real
    literals only appear at each CALL site: e.g.
    `abby_model_chosen("Agnes")`), and a zero-argument function whose own
    body is a sequence of `{condition: ~ return "Literal"}`-style
    branches (e.g. `misslogan_location_prefix()`, confirmed via
    misslogan.ink's own tag at line 389 using `{misslogan_location_prefix()}`
    exactly like a bare VAR interpolation) -- every literal `~ return
    "..."` found between that function's own `=== function X ===` header
    and the next knot/function header anywhere in the corpus is captured
    as one of X's real possible values.

    Args:
        game_dir: The game folder whose .ink corpus to scan.

    Returns:
        A dict of {name (lowercased, function names WITHOUT their own
        trailing "()"): [distinct literal values seen]}, covering every
        VAR/function name found this way anywhere in the corpus, not
        just names matching a fixed allowlist.
    """
    values: dict[str, set[str]] = {}
    for ink_path in sorted(game_dir.glob("*.ink")):
        text = ink_path.read_text(encoding="utf-8", errors="replace")
        for pattern in (VAR_DECL_RE, VAR_WRITE_RE, VAR_CHOSEN_CALL_RE):
            for match in pattern.finditer(text):
                var_name, literal = match.group(1).lower(), match.group(2)
                if literal:
                    values.setdefault(var_name, set()).add(literal)
        for match in PERSON_VALUE_WRITE_RE.finditer(text):
            character_id, attribute, literal = match.group(1).lower(), match.group(2).lower(), match.group(3)
            if literal:
                values.setdefault(f"{character_id}_{attribute}", set()).add(literal)

        choose_model_literals: dict[str, set[str]] = {}
        for match in CHOOSE_MODEL_CALL_RE.finditer(text):
            dispatcher, literal = match.group(1).lower(), match.group(2)
            if literal:
                choose_model_literals.setdefault(dispatcher, set()).add(literal)
        if choose_model_literals:
            all_starts = sorted(m.start() for m in KNOT_HEADER_RE.finditer(text))
            for stitch_match in CHOOSE_MODEL_STITCH_RE.finditer(text):
                dispatcher = re.match(r"^\s*=\s*([a-z_][a-z0-9_]*)_choose_model\(", stitch_match.group(0), re.IGNORECASE).group(1).lower()
                literals = choose_model_literals.get(dispatcher)
                if not literals:
                    continue
                parameter = stitch_match.group(1)
                later_headers = [pos for pos in all_starts if pos > stitch_match.start()]
                end = later_headers[0] if later_headers else len(text)
                body = text[stitch_match.start() : end]
                write_match = re.search(
                    r'set_person_value_now\(\s*"([a-z_][a-z0-9_]*)"\s*,\s*"([a-z_][a-z0-9_]*)"\s*,\s*' + re.escape(parameter) + r"\s*\)",
                    body,
                    re.IGNORECASE,
                )
                if write_match is None:
                    continue
                character_id, attribute = write_match.group(1).lower(), write_match.group(2).lower()
                values.setdefault(f"{character_id}_{attribute}", set()).update(literals)

        function_starts = [(m.start(), m.group(1).lower()) for m in FUNCTION_HEADER_RE.finditer(text)]
        if not function_starts:
            continue
        knot_starts = sorted(m.start() for m in KNOT_HEADER_RE.finditer(text))
        for start, func_name in function_starts:
            later_headers = [pos for pos in knot_starts if pos > start]
            end = later_headers[0] if later_headers else len(text)
            body = text[start:end]
            for match in RETURN_LITERAL_RE.finditer(body):
                literal = match.group(1)
                if literal:
                    values.setdefault(func_name, set()).add(literal)

    # A zero-argument function's own `~ return "..."` literal can itself
    # embed a further "{person_value_now("<id>", "<attr>")}" reference
    # rather than being a plain string (e.g. mom.ink's mom_dress(), whose
    # two branches return "{person_value_now("mom", "model")}/Younger" and
    # ".../Natural" -- her chosen model folder nested inside her age
    # folder). A single top-down pass over `values` cannot know those
    # referenced keys are populated at the time it visits the returning
    # function, since a `dict` has no guaranteed visitation order relative
    # to *_chosen(...)/set_person_value_now(...) writes elsewhere in the
    # corpus -- so this expands any such embedded reference in a second
    # pass, once every real key above is already known.
    embedded_call_re = re.compile(r'\{\s*person_value_now\(\s*"([a-z_][a-z0-9_]*)"\s*,\s*"([a-z_][a-z0-9_]*)"\s*\)\s*\}', re.IGNORECASE)
    for name, literals in list(values.items()):
        expanded: set[str] = set()
        for literal in literals:
            match = embedded_call_re.search(literal)
            if match is None:
                expanded.add(literal)
                continue
            referenced_key = f"{match.group(1).lower()}_{match.group(2).lower()}"
            for referenced_value in values.get(referenced_key, [""]):
                expanded.add(literal[: match.start()] + referenced_value + literal[match.end() :])
        values[name] = expanded
    return {name: sorted(literals) for name, literals in values.items()}


_MODEL_VAR_VALUES: dict[str, list[str]] = {}
VAR_EQUALITY_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\s*==\s*\"([^\"]*)\"", re.IGNORECASE)
# The same cross-block consistency VAR_EQUALITY_RE gives a bare VAR (e.g.
# "misslogan_model == "Kate""), for the corpus's own standardized
# person_value_now(...) accessor form of the identical equality (e.g.
# "person_value_now("miss_logan", "model") == "Kate""). Matched separately
# since the accessor call's own commas/quotes are not a bare identifier
# VAR_EQUALITY_RE's \b([a-z_][a-z0-9_]*)\b can match against.
PERSON_VALUE_EQUALITY_RE = re.compile(
    r'person_value_now\(\s*"([a-z_][a-z0-9_]*)"\s*,\s*"([a-z_][a-z0-9_]*)"\s*\)\s*==\s*"([^"]*)"', re.IGNORECASE
)


def _branches_of(inner: str, committed: dict[str, str]) -> list[tuple[str, dict[str, str]]]:
    """Return every literal alternative one already-brace-free "{...}" block's
    inner text can evaluate to, each paired with the VAR commitments that
    branch implies.

    Handles three real shapes found in this corpus: a "cond: a|b"
    conditional, a plain "a|b" alternation, and a bare VAR/zero-arg-
    function reference with neither ":" nor "|" (e.g. "{abby_model}" or
    "{misslogan_location_prefix()}") -- the last one is not a literal at
    all, but if it names a known model-choice VAR or zero-argument
    function (per build_model_var_values(), called once via
    _MODEL_VAR_VALUES), every real literal value ever assigned/returned
    is substituted as a real branch, since current_tags at play time
    always holds one of those real resolved strings, never the bare
    VAR/function-call text. An unresolvable bare reference (name unknown)
    is dropped to an empty-string branch, matching a pre-choice/default
    state.

    Cross-block consistency (the real bug this fixes, found 2026-08-26):
    a bare "{X}" reference records its own chosen literal as a real
    commitment (`committed[X] = literal`) for the REST of this same
    expansion path. A later condition containing "X == "Literal"" (e.g.
    misslogan.ink's own recurring
    "misslogan_flag18_age_transformed and misslogan_model == "Kate""
    pattern) is checked against any existing commitment for that VAR
    FIRST -- if X was already committed to a different literal, that
    equality is forced false (pruning the impossible combination, e.g.
    "Samantha" + "Younger", which can never actually occur at play time
    since "Younger" is only ever paired with "Kate" in the real source
    condition) rather than blindly enumerating both branches regardless
    of the earlier commitment.

    Args:
        inner: The text between one matched pair of braces.
        committed: VAR name -> literal value already chosen earlier in
            this same expansion path (mutated by the caller between
            recursive steps, never by this function itself).

    Returns:
        A list of (branch_text, new_commitments) pairs -- new_commitments
        is only the NEW commitment(s) this specific branch adds (the
        bare-VAR case), empty for a plain conditional/alternation branch.
    """
    # Ink's shuffle-sequence syntax: "{&a|b|c}" picks one alternative at
    # random each time, same shape as a plain "{a|b|c}" alternation for
    # our purposes (real play always resolves to exactly one literal
    # branch) -- strip the leading "&" marker before the usual
    # conditional/alternation handling below picks up its branches.
    if inner.lstrip().startswith("&"):
        inner = inner.lstrip()[1:]

    if ":" not in inner and "|" not in inner:
        stripped = inner.strip()
        person_value_call = PERSON_VALUE_CALL_RE.match(stripped)
        if person_value_call:
            character_id, attribute = person_value_call.group(1).lower(), person_value_call.group(2).lower()
            var_name = f"{character_id}_{attribute}"
        else:
            var_name = stripped.lower().removesuffix("()")
        values = _MODEL_VAR_VALUES.get(var_name, [""])
        if var_name in committed:
            return [(committed[var_name], {})]
        return [(value, {var_name: value}) for value in values]

    colon_parts = _split_top_level(inner, ":")
    condition = colon_parts[0] if len(colon_parts) > 1 else ""
    branch_section = colon_parts[-1] if len(colon_parts) > 1 else inner
    branches = [b.strip() for b in _split_top_level(branch_section, "|")]

    # A bare boolean VAR name as the whole condition (e.g.
    # "{is_explicit_mode:Explicit/}" -- no ":" alternative even, or
    # "{is_explicit_mode:a|b}") is the same kind of cross-block coupling
    # as an "X == "literal"" equality, just for a boolean rather than a
    # string VAR: a later "{is_explicit_mode:a|}"-style branch elsewhere
    # in the same tag must agree with an earlier commitment to this same
    # VAR, not be enumerated independently. Track it the same way, keyed
    # as boolean_name -> "true"/"false".
    bool_condition = condition.strip().lower()
    if bool_condition and re.fullmatch(r"[a-z_][a-z0-9_]*", bool_condition):
        bool_key = f"bool:{bool_condition}"
        one_branch = len(branches) == 1
        true_branch = branches[0]
        false_branch = branches[1] if not one_branch else ""
        if bool_key not in committed:
            return [(true_branch, {bool_key: "true"}), (false_branch, {bool_key: "false"})]
        return [(true_branch if committed[bool_key] == "true" else false_branch, {})]

    person_value_equality_matches = list(PERSON_VALUE_EQUALITY_RE.finditer(condition)) if condition else []
    equality_matches = list(VAR_EQUALITY_RE.finditer(condition)) if condition else []
    if not (person_value_equality_matches or equality_matches) or len(branches) != 2:
        return [(b, {}) for b in branches]

    if person_value_equality_matches:
        matched_equality = person_value_equality_matches[0]
        character_id, attribute, literal = matched_equality.group(1).lower(), matched_equality.group(2).lower(), matched_equality.group(3)
        var_name = f"{character_id}_{attribute}"
    else:
        matched_equality = equality_matches[0]
        var_name, literal = matched_equality.group(1).lower(), matched_equality.group(2)
    if var_name not in committed:
        # This equality is the FIRST reference to var_name in this tag --
        # nothing to prune against yet, so both branches remain possible
        # (matching the plain-conditional case above); this VAR's real
        # commitment comes from wherever its own bare "{var_name}"
        # reference is substituted elsewhere in the same tag.
        return [(b, {}) for b in branches]
    if committed[var_name] != literal:
        # The commitment already rules the equality out entirely (e.g.
        # "Samantha" can never satisfy "misslogan_model == "Kate""),
        # regardless of the condition's other operand(s) (e.g. the real
        # "flag18 AND model=="Kate"" case's own flag18 half) -- only the
        # FALSE branch is reachable.
        return [(branches[1], {})]
    # The commitment satisfies this one equality. If the real source
    # condition has another operand this function doesn't track (e.g.
    # "flag18 AND model=="Kate""), both branches stay possible (matching
    # Kate/Younger when transformed AND Kate/Natural when not) -- but if
    # the equality IS the whole condition (e.g. character_dress == "Gala"
    # with no other operand), the commitment fully determines the
    # outcome and only the TRUE branch is reachable (e.g. Gala can
    # never also produce the FALSE branch's "Pool.jpg", only the TRUE
    # branch's "Character-Pool.jpg").
    if matched_equality.group(0).strip() == condition.strip():
        return [(branches[0], {})]
    return [(b, {}) for b in branches]


def expand_braces(text: str, committed: dict[str, str] | None = None, *, _depth: int = 0) -> list[str]:
    """Expand every "{...}" block in `text` into all its literal alternatives.

    Args:
        text: Raw tag text, possibly containing "{...}" blocks.
        committed: VAR commitments already made earlier in this same tag
            (see _branches_of) -- None (the top-level call) starts a
            fresh, empty commitment set.
        _depth: Internal recursion guard.

    Returns:
        Every fully-literal candidate string `text` could resolve to at
        play time (matching engine.py's own current_tags, which always
        holds the already-interpolated text, never the raw template),
        with cross-referenced VARs (the same VAR named bare in one
        segment and tested by equality in another) resolved consistently
        rather than as an independent cross product.
    """
    if committed is None:
        committed = {}
    if _depth > 12 or "{" not in text:
        return [text]
    match = INNERMOST_BRACE_RE.search(text)
    if match is None:
        return [text]
    inner = match.group(1)
    results: list[str] = []
    for branch, new_commitments in _branches_of(inner, committed):
        replaced = text[: match.start()] + branch + text[match.end() :]
        next_committed = {**committed, **new_commitments}
        results.extend(expand_braces(replaced, next_committed, _depth=_depth + 1))
    return results


def extract_resolved_tags(raw_tag_text: str) -> list[str]:
    """Expand one raw tag's text into every real resolved tag_name it can
    produce at play time.

    Args:
        raw_tag_text: The text following "# image:"/"# video:" on one
            tag line, which may contain Ink "{...}" conditionals.

    Returns:
        De-duplicated, order-preserving list of fully-literal tag names
        (e.g. "guide/Male/guide12m.jpg").
    """
    seen: dict[str, None] = {}
    for candidate in expand_braces(raw_tag_text):
        candidate = candidate.strip().lstrip("!")
        if FILENAME_TOKEN_RE.search(candidate):
            seen.setdefault(candidate, None)
    return list(seen)


def scan_corpus(game_dir: Path) -> list[dict[str, Any]]:
    """Scan every .ink file in one game folder for every resolved image/video tag.

    Args:
        game_dir: The game folder whose .ink corpus to scan.

    Returns:
        A list of {"file", "line", "kind", "raw", "resolved": [tag names]}
        dicts, one per real "# image:"/"# video:" tag line found.
    """
    global _MODEL_VAR_VALUES  # pylint: disable=global-statement
    _MODEL_VAR_VALUES = build_model_var_values(game_dir)

    # A game may seed values build_model_var_values()'s own regexes cannot
    # discover -- a numeric VAR interpolated into a folder name, or a VAR
    # assigned only from a function parameter so the real literals appear
    # solely at call sites. Those are per-game facts about that game's own
    # content, so they live in the game folder's image_mapping.py
    # (MODEL_VAR_VALUE_SEEDS) rather than being hardcoded here.
    for name, values in _load_game_model_var_seeds(game_dir).items():
        _MODEL_VAR_VALUES[name] = values

    entries: list[dict[str, Any]] = []
    for ink_path in sorted(game_dir.glob("*.ink")):
        text = ink_path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            match = MEDIA_TAG_RE.match(line)
            if not match:
                continue
            kind, raw_tag_text = match.group(1), match.group(2)
            resolved = extract_resolved_tags(raw_tag_text)
            entries.append({"file": ink_path.name, "line": line_no, "kind": kind, "raw": raw_tag_text, "resolved": resolved})
    return entries


def resolve_sibling_directory(images_root, name: str):
    """Return the real DirectoryIndex row for a sibling of `images_root`.

    A game's art usually lives under its own `images/` tree, but the
    original may serve some of it from a directory BESIDE that one — e.g.
    a game may keep themed UI art and other non-character images in a
    `UI/` directory, a sibling of `images/`. Resolving those needs a
    lookup that steps up to the game version directory first.

    Args:
        images_root: The game's `images/` DirectoryIndex row.
        name: The sibling directory's own name (case-insensitive).

    Returns:
        The matching sibling row, or None when `images_root` has no parent
        (it is the tree root) or no such sibling exists.
    """
    parent = images_root.parent_directory
    if parent is None:
        return None
    return resolve_child_directory(parent, name)


def resolve_tag_name(tag_name: str, images_root, character_folders: dict[str, str | None], non_character_roots: set[str]):
    """Resolve one real, fully-literal tag_name to a live gallery FileIndex row.

    Walks the REAL DirectoryIndex tree from `images_root` one path segment
    at a time (resolve_child_directory), then looks up the final filename
    via that directory's own files_in_dir() -- never a hardcoded/string-
    built absolute path, so this works regardless of where the gallery
    actually scanned the source tree to on a given install.

    Args:
        tag_name: A tag_name exactly as it would appear in
            InkRuntimeState.current_tags at play time (e.g.
            "guide/Male/guide12m.jpg").
        images_root: The game's source-image tree DirectoryIndex row, from
            find_gallery_images_root().
        character_folders: The game's own tag-prefix -> gallery-folder
            mapping (see _load_game_image_mapping).
        non_character_roots: The game's own top-level non-character image
            roots.

    Returns:
        The matching FileIndex row, or None if it can't be resolved
        (unknown character prefix, or no matching directory/file found
        anywhere along the real path).
    """
    if images_root is None:
        return None

    prefix, _sep, rest = tag_name.partition("/")
    if not rest:
        return None
    prefix_lower = prefix.lower()

    if prefix_lower == "shared":
        # A synthetic namespace for a real bare top-level asset living
        # directly under images/, with no character or non-character-root
        # subdirectory at all (e.g. door2.jpg) -- confirmed real, not a
        # guess, at each real use site.
        current = images_root
        rest_parts = rest.split("/")
    elif prefix_lower in non_character_roots:
        current = resolve_child_directory(images_root, prefix_lower)
        if current is None:
            # A game may serve some art from a SIBLING of images/ rather than
            # a child of it: a converted game's original source may load
            # themed and non-character art from its own UI/ tree, which sits
            # beside images/, not inside it. Those tags were previously
            # recorded as permanently unresolvable "asset outside the gallery
            # tree" blockers purely because this walk started one level too
            # deep. Only roots the game itself declared are looked up this
            # way, so an arbitrary tag still cannot escape the game's tree.
            current = resolve_sibling_directory(images_root, prefix_lower)
        rest_parts = rest.split("/")
    else:
        gallery_folder = character_folders.get(prefix_lower)
        if gallery_folder is None:
            return None
        people_dir = resolve_child_directory(images_root, "people")
        current = resolve_child_directory(people_dir, gallery_folder) if people_dir else None
        rest_parts = rest.split("/")

    if current is None:
        return None

    filename = rest_parts[-1]
    for segment in rest_parts[:-1]:
        current = resolve_child_directory(current, segment)
        if current is None:
            return None

    matches = list(current.files_in_dir(additional_filters={"name__iexact": filename}, select_related=("home_directory",)))
    if len(matches) == 1:
        return matches[0]

    # Some real gallery assets exist as a video (.mp4) where the .ink tag
    # names a still-image extension, or vice-versa -- the narrative intent
    # is the same file, just a different real media format on disk. Fall
    # back to a stem-only (extension-agnostic) match before giving up.
    stem = filename.rsplit(".", 1)[0]
    stem_matches = [f for f in current.files_in_dir(select_related=("home_directory",)) if f.name.rsplit(".", 1)[0].lower() == stem.lower()]
    return stem_matches[0] if len(stem_matches) == 1 else None


# Tag namespace for images the game folder itself supplies (character-
# creation icons), linked by ingestion._link_new_game_field_images rather
# than by scanning .ink content. Reconciling story-content tags must never
# delete these -- they resolve from a different source entirely.
NEW_GAME_TAG_PREFIX = "newgame:"


def reconcile_story_images(story, game_dir: Path, source_game_version: str | None) -> dict[str, int]:
    """Rebuild one story's content-image links from its current .ink tags.

    A full reconcile, not an append. Every `# image:`/`# video:` tag in the
    game's corpus is re-expanded and re-resolved against the live gallery,
    and the story's content-image rows are made to match that result
    exactly:

    * a tag that now resolves is linked (or relinked, if it previously
      pointed at a different file);
    * a row whose tag no longer appears in the corpus, or whose file has
      left the gallery, is DELETED.

    The delete half is the point: without it a StoryImage row outlives the
    file it names, and the story keeps serving a link to content that is
    no longer there. Append-only linking is what allowed rows to drift out
    of step with both the corpus and the filesystem.

    `newgame:`-prefixed rows are never touched here -- they come from the
    manifest's NEW_GAME_FIELDS, not from story content, and are
    reconciled by ingestion._link_new_game_field_images instead.

    Args:
        story: The Story whose images to reconcile.
        game_dir: That story's game folder, holding both the .ink corpus
            and the game's own image_mapping.py.
        source_game_version: That game manifest's own SOURCE_GAME_VERSION,
            naming the gallery tree its images live in.

    Returns:
        {"linked", "unlinked", "broken", "tags"} counts for one pass.
    """
    character_folders, non_character_roots = _load_game_image_mapping(game_dir)
    images_root = find_gallery_images_root(game_dir, source_game_version)

    wanted: set[str] = set()
    for entry in scan_corpus(game_dir):
        wanted.update(entry["resolved"])

    linked = 0
    broken = 0
    resolved_now: set[str] = set()
    for tag_name in sorted(wanted):
        file_entry = resolve_tag_name(tag_name, images_root, character_folders, non_character_roots)
        if file_entry is None:
            broken += 1
            continue
        link_story_image(story, tag_name, file_entry)
        resolved_now.add(tag_name)
        linked += 1

    stale = StoryImage.objects.filter(story=story).exclude(tag_name__in=resolved_now).exclude(tag_name__startswith=NEW_GAME_TAG_PREFIX)
    unlinked = stale.count()
    if unlinked:
        stale.delete()

    return {"linked": linked, "unlinked": unlinked, "broken": broken, "tags": len(wanted)}

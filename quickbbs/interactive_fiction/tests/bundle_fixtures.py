"""Synthetic game bundles for tests, built by the real bundler.

Everything the bundle code does -- resolving a tag, serving a byte range,
refusing a tampered archive, caching an open handle -- is a property of
the bundle format, not of any particular game. So these tests build their
own game and bundle it.

The bundle is produced by `ink_engine.bundler`, the same code an author
runs, rather than by hand-assembling a zip: a hand-made archive gets the
package layout and the integrity hashes in the archive comment wrong, and
would prove the tests pass against a shape nothing else produces.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from ink_engine.bundler import build_bundle, select_bundle_contents

#: A minimal compiled story: it plays to an immediate end.
COMPILED_STORY = {"inkVersion": 21, "root": [["done", None], "done", None], "listDefs": {}}

#: Media the synthetic game ships, as tag -> bytes. The paths have the
#: shape a game uses -- a folder per character, a file per pose -- while
#: naming nobody's content.
IMAGES = {
    "hero/portrait.jpg": b"\xff\xd8\xff\xe0" + b"synthetic jpeg body" * 8,
    "hero/standing.jpg": b"\xff\xd8\xff\xe0" + b"another jpeg" * 8,
    "villain/portrait.jpg": b"\xff\xd8\xff\xe0" + b"a third jpeg" * 8,
}

#: One video, big enough that a Range request returns a real slice.
VIDEO_TAG = "hero/scene.mp4"
VIDEO_BYTES = bytes(range(256)) * 400  # 102,400 bytes

#: A character-creation image. The bundler places these under `UI/`.
NEW_GAME_IMAGE = "choice_a.png"

#: A tag the story names but the game never shipped -- the
#: declared-but-absent case every real corpus has some of.
ABSENT_TAG = "hero/missing.jpg"

#: The game's own plugin-denied screen. A game that declares plugins is
#: designed around them, and only the game can say what they do -- so it
#: ships the explanation rather than the application inventing one. The
#: table proves Markdown really rendered; the script proves it is escaped.
PLUGIN_DENIED_SCREEN = """# Without these, the world is empty

| Plugin | What it does |
|---|---|
| whereabouts | Tracks who is in which room |

<script>alert(1)</script>
"""

#: A game-owned resolver, in the shape a real one takes: it rewrites a
#: tag before the literal lookup, so a story can name a pose and let the
#: game decide which file answers it.
_RESOLVER_SOURCE = '''"""A game-owned resolver, for tests that need one to exist.

Signature matches what `bundle_media.resolve_tag_in_bundle()` calls:
every argument keyword, `reference` mapping a bundle path to whatever the
caller wants back.
"""


def resolve_tag(*, kind, tag, source, reference):
    """Rewrite any `hero/*.jpg` to the portrait; leave everything else."""
    del kind
    if tag.startswith("hero/") and tag.endswith(".jpg"):
        return reference("hero/portrait.jpg") if source.exists("hero/portrait.jpg") else None
    return reference(tag) if source.exists(tag) else None
'''


def write_game_directory(
    game_dir: Path,
    *,
    title: str = "A Test Game",
    version: str = "1.0",
    with_resolver: bool = False,
    with_cover: bool = False,
    with_plugins: bool = False,
) -> Path:
    """Write a synthetic game folder, ready to bundle.

    Args:
        game_dir: The folder to create. Its name becomes the bundle's
            package name, so it must be a valid Python identifier.
        title: The manifest's `GAME_TITLE`.
        version: The manifest's `GAME_VERSION`.
        with_resolver: Ship a game-owned `image_resolver.resolve_tag()`,
            which the bundle code consults in preference to a literal
            lookup. Without it, tags resolve literally.
        with_cover: Ship a cover image.
        with_plugins: Declare required plugins and ship the game's own
            plugin-denied screen, for tests about the trust gate.

    Returns:
        `game_dir`.
    """
    game_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "MANIFEST_VERSION": 1,
        "GAME_TITLE": title,
        "GAME_VERSION": version,
        "MAIN_STORY_FILE": "story.inkj",
        "MEDIA_DIRECTORIES": ["hero", "villain", "UI"],
        **(
            {
                "REQUIRED_PLUGINS": ["whereabouts"],
                "PLUGIN_DENIED_SCREEN": "plugin_denied.md",
                "EXTRA_FILES": ["plugin_denied.md"],
            }
            if with_plugins
            else {}
        ),
        "NEW_GAME_FIELDS": [
            {
                "var": "player_side",
                "type": "radio_image",
                "label": "Which side?",
                "default": {"player_side": "light"},
                "options": [{"value": {"player_side": "light"}, "label": "Light", "image": NEW_GAME_IMAGE}],
            }
        ],
    }
    (game_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    (game_dir / "story.inkj").write_text(json.dumps(COMPILED_STORY), encoding="utf-8")
    (game_dir / "__init__.py").write_text("from . import image_resolver\n" if with_resolver else "", encoding="utf-8")
    if with_resolver:
        (game_dir / "image_resolver.py").write_text(_RESOLVER_SOURCE, encoding="utf-8")

    for tag, body in IMAGES.items():
        path = game_dir / tag
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    (game_dir / VIDEO_TAG).write_bytes(VIDEO_BYTES)
    ui = game_dir / "UI"
    ui.mkdir(exist_ok=True)
    (ui / NEW_GAME_IMAGE).write_bytes(b"\x89PNG\r\n\x1a\n" + b"synthetic png" * 4)
    if with_cover:
        (game_dir / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"cover" * 8)
    if with_plugins:
        (game_dir / "plugin_denied.md").write_text(PLUGIN_DENIED_SCREEN, encoding="utf-8")
    return game_dir


def write_bundle(root: Path, *, name: str = "testgame", **kwargs: object) -> Path:
    """Build a synthetic game and bundle it, returning the bundle path.

    Args:
        root: A temporary directory to work in.
        name: The game's folder and package name.
        **kwargs: Passed to `write_game_directory()`.

    Returns:
        The written `.zip`.
    """
    game_dir = write_game_directory(root / name, **kwargs)  # type: ignore[arg-type]
    plan = select_bundle_contents(game_dir)
    return build_bundle(plan, root / f"{name}.zip")

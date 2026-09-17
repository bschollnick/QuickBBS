"""Serving a bundled game's own media, read from the `.zip` in place.

The game ships its own tag rules (`image_resolver.py`, which `if_player`
already uses); this module gives them a Django-shaped home rather than
reimplementing them. A tag becomes a URL here and bytes in
`story_views.story_image()`.

Opening a bundle parses its central directory: measured at 31.6 ms for
a 13,000-entry game bundle against 0.00023 ms for a lookup once open.
So an open source is cached for the worker's life and only closed when
evicted.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

from django.conf import settings
from django.http import HttpResponse, StreamingHttpResponse

from ink_engine.discovery import mount_game
from ink_engine.game_folder import read_cover_image
from ink_engine.game_source import GameSource, GameSourceError, open_game_source
from quickbbs.MonitoredCache import ThreadSafeLRUCache
from thumbnails.engine.engine import create_thumbnails_from_bytes
from thumbnails.models import ThumbnailFiles

logger = logging.getLogger(__name__)

#: How many bundles stay open at once. Each costs one file descriptor and
#: its table of contents; a library is a handful of games, not thousands.
MAX_OPEN_BUNDLES = 8


class _OpenBundleCache(ThreadSafeLRUCache):
    """An LRU of open bundles that closes what it evicts.

    A plain LRU would drop the reference and leak the descriptor.
    """

    def popitem(self) -> tuple[Any, Any]:
        key, source = super().popitem()
        try:
            source.close()
        except OSError as error:
            logger.warning("interactive_fiction.bundle_media: closing evicted bundle '%s': %s", key, error)
        return key, source


_open_bundles = _OpenBundleCache(maxsize=MAX_OPEN_BUNDLES)


def bundle_source(bundle_path: Path) -> GameSource | None:
    """Return an open source for one bundle, opening it if needed.

    Args:
        bundle_path: The bundle's real filesystem path.

    Returns:
        The open source, or None when the bundle cannot be opened -- a
        missing or corrupt file is a real condition on a live server, not
        an exception for every caller to handle.
    """
    key = str(bundle_path)
    source = _open_bundles.get(key)
    if source is not None:
        return source
    try:
        source = open_game_source(bundle_path)
    except GameSourceError as error:
        logger.warning("interactive_fiction.bundle_media: cannot open bundle '%s': %s", bundle_path.name, error)
        return None
    _open_bundles[key] = source
    return source


def close_all_bundles() -> None:
    """Close every open bundle. For tests and shutdown."""
    while _open_bundles:
        _open_bundles.popitem()
    _resolvers.clear()


#: One game's resolver module, kept with its mount. Mounting per tag
#: costs ~50 ms against ~0.1 ms once held, and a turn resolves several.
_resolvers: dict[str, Any] = {}


def _game_resolver(bundle_path: Path):
    """Return the game's own resolver module, mounting the bundle once.

    The mount is deliberately never released: the module stays imported
    for the worker's life, so dropping the `sys.path` entry would strand
    it. A second game with the same package name is the known cost, and
    `game_identity()` is what keeps published bundles distinct.

    Args:
        bundle_path: The bundle holding the game.

    Returns:
        The imported `image_resolver` module, or None when the game
        ships none.
    """
    key = str(bundle_path)
    if key in _resolvers:
        return _resolvers[key]
    try:
        mounted = mount_game(bundle_path)
        resolver = __import__(f"{mounted.package}.image_resolver", fromlist=["image_resolver"])
    except (ImportError, AttributeError, ValueError) as error:
        logger.info("interactive_fiction.bundle_media: '%s' ships no image_resolver (%s); tags read literally", bundle_path.name, error)
        resolver = None
    _resolvers[key] = resolver
    return resolver


#: QuickBBS's own namespace for a character-creation option's image
#: (`ingestion._new_game_field_image_tag`). These are the game's UI
#: assets, not story content, so the game's own story-tag resolver knows
#: nothing about them.
NEW_GAME_TAG_PREFIX = "newgame:"


def _resolve_new_game_image(source: GameSource, filename: str) -> str | None:
    """Find one character-creation image inside a bundle.

    A manifest names a bare filename. A game folder keeps these at its
    root, but the bundler places them under `UI/`, so both layouts are
    searched rather than assuming either.

    Args:
        source: The open bundle.
        filename: The manifest's own `image` value, e.g. "male.png".

    Returns:
        The path within the bundle, or None.
    """
    if source.exists(filename):
        return filename
    return next((name for name in source.iter_names() if name.rsplit("/", 1)[-1] == filename), None)


def resolve_tag_in_bundle(story_path: Path, kind: str, tag: str) -> str | None:
    """Resolve one media tag to a path inside the bundle.

    The game's own `image_resolver.resolve_tag()` decides, so the rules
    live with the game and one fix reaches both hosts. A game shipping no
    resolver answers its tags literally.

    Args:
        story_path: The bundle holding the game.
        kind: "image" or "video".
        tag: The tag as the story wrote it.

    Returns:
        The path within the bundle, or None when nothing answers it.
    """
    source = bundle_source(story_path)
    if source is None:
        return None
    if tag.startswith(NEW_GAME_TAG_PREFIX):
        return _resolve_new_game_image(source, tag[len(NEW_GAME_TAG_PREFIX) :])
    resolver = _game_resolver(story_path)
    if resolver is None:
        return tag if source.exists(tag) else None
    return resolver.resolve_tag(kind=kind, tag=tag, source=source, reference=lambda path: path)


#: Extension -> content type for what a game ships. `mimetypes` alone
#: answers None for several of these depending on the host's own registry.
_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".m4v": "video/mp4",
}

#: How much of a video to send per read. A game ships videos up to ~75 MB
#: and reading one whole into memory per request does not scale.
_STREAM_CHUNK = 64 * 1024


def content_type_for(path: str) -> str:
    """Return the content type to serve `path` as."""
    return _CONTENT_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


def _stream(handle: IO[bytes], remaining: int) -> Iterator[bytes]:
    """Yield `remaining` bytes from `handle`, then close it."""
    try:
        while remaining > 0:
            chunk = handle.read(min(_STREAM_CHUNK, remaining))
            if not chunk:
                return
            remaining -= len(chunk)
            yield chunk
    finally:
        handle.close()


def open_member(bundle_path: Path, member: str, *, start: int = 0) -> tuple[IO[bytes], int] | None:
    """Open one file inside a bundle for reading, seeked to `start`.

    Media is STORED rather than deflated (13,047 of one measured game
    bundle's 13,066 entries), so a seek is a seek and a Range request costs no
    decompression.

    Args:
        bundle_path: The bundle to read from.
        member: The path within it, as `resolve_tag_in_bundle()` answers.
        start: Byte offset to begin at.

    Returns:
        `(handle, total_size)`, or None when the bundle or member is
        missing. The caller owns the handle.
    """
    source = bundle_source(bundle_path)
    if source is None:
        return None
    try:
        handle, size = source.open_stream(member)
    except GameSourceError as error:
        logger.warning("interactive_fiction.bundle_media: reading '%s' from '%s': %s", member, bundle_path.name, error)
        return None
    if start:
        handle.seek(start)
    return handle, size


#: Where a cover sits when the manifest declares none. Mirrors the
#: engine's own `find_cover_image()` convention.
_COVER_SEARCH_DIRS = (".", "images", "Images")
_COVER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def cover_member(bundle_path: Path) -> str | None:
    """Return the bundle's own cover image path, or None.

    The engine's `find_cover_image()` answers a displayable REFERENCE --
    a `data:` URI inlining the bytes, which is right for a desktop window
    with no server and wrong here. This answers the path instead, so the
    cover can be thumbnailed once and served by URL.

    Args:
        bundle_path: The bundle to look in.

    Returns:
        The path within the bundle, or None when the game ships no cover
        -- a cosmetic gap, not an error.
    """
    source = bundle_source(bundle_path)
    if source is None:
        return None
    declared = read_cover_image(source)
    if declared:
        return declared if source.exists(declared) else None
    for directory in _COVER_SEARCH_DIRS:
        for extension in _COVER_EXTENSIONS:
            candidate = f"cover{extension}" if directory == "." else f"{directory}/cover{extension}"
            if source.exists(candidate):
                return candidate
    return None


def serve_member(request, bundle_path: Path, member: str, *, ranged: bool = False):
    """Serve one file from inside a bundle as an HTTP response.

    Args:
        request: The incoming request, read for a Range header.
        bundle_path: The bundle to read from.
        member: The path within it.
        ranged: Whether to honour a Range request. Videos need it for a
            browser to seek; images are sent whole.

    Returns:
        A streaming 200, a 206 for a satisfied Range request, or 404 when
        the member is missing.
    """
    opened = open_member(bundle_path, member)
    if opened is None:
        return HttpResponse(status=404)
    handle, size = opened
    content_type = content_type_for(member)

    range_header = request.META.get("HTTP_RANGE", "") if ranged else ""
    match = re.match(r"bytes=(\d+)-(\d*)", range_header)
    if match:
        handle.close()
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else size - 1
        end = min(end, size - 1)
        if start > end:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        reopened = open_member(bundle_path, member, start=start)
        if reopened is None:
            return HttpResponse(status=404)
        handle, _ = reopened
        length = end - start + 1
        response = StreamingHttpResponse(_stream(handle, length), status=206, content_type=content_type)
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
        response["Content-Length"] = str(length)
    else:
        response = StreamingHttpResponse(_stream(handle, size), content_type=content_type)
        response["Content-Length"] = str(size)

    if ranged:
        response["Accept-Ranges"] = "bytes"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def build_cover_thumbnail(bundle_path: Path):
    """Thumbnail a bundle's cover once, and return its `ThumbnailFiles` row.

    `ThumbnailFiles` is content-addressed on `sha256_hash`, so a cover
    owns a row keyed by its own bytes without any `FileIndex` -- which a
    bundle has none of. Its usual generation path resolves a FileIndex to
    read from, so the blobs are built here from the bundle's bytes
    directly and stored on the row.

    Args:
        bundle_path: The bundle whose cover to thumbnail.

    Returns:
        The populated `ThumbnailFiles` row, or None when the game ships
        no cover or its bytes cannot be rendered.
    """
    member = cover_member(bundle_path)
    if member is None:
        return None
    source = bundle_source(bundle_path)
    if source is None:
        return None
    try:
        raw = source.read_bytes(member)
    except GameSourceError as error:
        logger.warning("interactive_fiction.bundle_media: reading cover '%s': %s", member, error)
        return None

    digest = hashlib.sha256(raw).hexdigest()
    row, _created = ThumbnailFiles.objects.get_or_create(sha256_hash=digest)
    if row.small_thumb:
        return row

    try:
        blobs = create_thumbnails_from_bytes(raw, settings.IMAGE_SIZE, output="JPEG", quality=settings.PIL_IMAGE_QUALITY)
    except (OSError, ValueError) as error:
        logger.warning("interactive_fiction.bundle_media: cannot thumbnail cover '%s': %s", member, error)
        return None

    row.small_thumb = blobs.get("small") or None
    row.medium_thumb = blobs.get("medium") or None
    row.large_thumb = blobs.get("large") or None
    row.save(update_fields=["small_thumb", "medium_thumb", "large_thumb"])
    return row

"""Story image/video linking for the interactive_fiction app.

`# image: <tag_name>` and `# video: <tag_name>` Ink tags map to a real
`FileIndex` row already synced into the gallery by the normal scanner
(`quickbbs/management/commands/scan.py`) — this app never stores or decodes
any bytes of its own.
for the design this module implements.
"""

from __future__ import annotations

import os

from django.urls import reverse

from interactive_fiction.bundle_media import resolve_tag_in_bundle
from interactive_fiction.models import Story
from quickbbs.models import DirectoryIndex, FileIndex


def find_file_by_path(full_filepathname: str, *, additional_filters: dict[str, object] | None = None) -> FileIndex | None:
    """Resolve a gallery file's full path directly to its live FileIndex row.

    Shared by story_views.py's upload()/edit() (resolving a "reference an
    existing gallery file" lookups, and by
    `interactive_fiction.ingestion.find_inkj_file_by_path` (which passes
    additional_filters to also require a .inkj filetype). Lives here
    rather than in ingestion.py to avoid a circular import (ingestion.py
    already imports from story_views.py, which needs this function).

    Resolves in two steps, both through existing DirectoryIndex machinery
    rather than a bespoke FileIndex query: first the containing directory,
    via DirectoryIndex.search_for_directory() (cached, keyed on the
    directory's own indexed dir_fqpn_sha256), then the file within it, via
    that directory's own DirectoryIndex.files_in_dir(additional_filters=...)
    — the same method every other directory-scoped file lookup in the
    codebase uses.

    full_filepathname is FileIndex.full_filepathname's own concatenation
    (home_directory.fqpndirectory + name) with no separator recorded
    between them, but fqpndirectory always ends in a path separator (see
    quickbbs.common.normalize_fqpn()), so splitting at the last separator
    reliably recovers the directory/name pair the original concatenation
    was built from.

    The `name` match is case-INSENSITIVE (`name__iexact`, not `name`):
    every FileIndex row's own `name` is stored title-cased
    (quickbbs.common.normalize_string_title(), applied by the real
    scanner) regardless of the real on-disk filename's actual casing —
    confirmed directly against a real scanned row (a story's own `.inkj`
    file on disk, stored title-cased, e.g. `Mystory.Inkj`). A caller
    building `full_filepathname` from a
    real filesystem path (e.g. a manifest's own literal `MAIN_STORY_FILE`
    string) would otherwise never match any real scanned file at all.

    Args:
        full_filepathname: The full path to look up.
        additional_filters: Extra FileIndex field filters beyond `name`
            (case-insensitive) and `ignore=False` (e.g. a filetype
            restriction) — merged into the same files_in_dir() call
            rather than filtered afterward.

    Returns:
        The matching live FileIndex row (not ignored, not delete_pending,
        and matching any additional_filters), or None if no such row
        exists (including when the containing directory itself has no
        DirectoryIndex row).
    """
    directory_path, _sep, name = full_filepathname.rpartition(os.sep)
    if not directory_path:
        return None

    found, directory = DirectoryIndex.search_for_directory(directory_path + os.sep)
    if not found or directory is None:
        return None

    filters: dict[str, object] = {"name__iexact": name, "ignore": False}
    if additional_filters:
        filters.update(additional_filters)

    matches = directory.files_in_dir(additional_filters=filters, select_related=("home_directory",))
    return matches.first()


#: Media kind (ink_engine.media_resolver.parse_media_tags()'s own "image"/
#: "video" values) -> the URL name that serves it. Kept here, not in
#: ink_engine, since a URL name is a Django-routing concept the engine has
#: no business knowing.
_MEDIA_KIND_URL_NAMES: dict[str, str] = {"image": "if_story_image", "video": "if_story_video"}


class DjangoMediaResolver:  # pylint: disable=too-few-public-methods
    """Resolves a turn's media tags against the story's own bundle.

    `ink_engine.media_resolver.MediaResolver`'s Django-backed
    implementation. The game's shipped `image_resolver.py` decides what a
    tag means, so one fix to those rules reaches both applications.
    """

    def __init__(self, story: Story) -> None:
        """
        Args:
            story: The story whose bundle this resolver answers from.
        """
        self._story = story

    def resolve(self, requests: list[tuple[str, str]]) -> list[str]:
        """Resolve a turn's media requests against the story's bundle.

        Args:
            requests: `ink_engine.media_resolver.parse_media_tags()`'s own
                output for this turn.

        Returns:
            One `if_story_image`/`if_story_video` URL per request the
            game resolves, GROUPED by kind (all images, then all videos —
            `MediaResolver.resolve()`'s own contract). An unresolved tag
            is silently dropped: a work-in-progress story with placeholder
            tags still plays, text-only. A story with no bundle resolves
            nothing.
        """
        all_tag_names = [tag_name for _kind, tag_name in requests]
        if not all_tag_names:
            return []

        bundle = self._story.bundle_path
        if bundle is None:
            return []
        # The game answers its own tags, by the rules it ships.
        available = {tag_name for _kind, tag_name in requests if resolve_tag_in_bundle(bundle, _kind, tag_name) is not None}
        grouped: dict[str, list[str]] = {kind: [] for kind in _MEDIA_KIND_URL_NAMES}
        for kind, tag_name in requests:
            if tag_name in available:
                grouped[kind].append(tag_name)

        urls: list[str] = []
        for kind, url_name in _MEDIA_KIND_URL_NAMES.items():
            urls.extend(reverse(url_name, args=[self._story.slug, tag_name]) for tag_name in grouped[kind])
        return urls

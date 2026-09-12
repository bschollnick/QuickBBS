"""Story image/video linking for the interactive_fiction app.

`# image: <tag_name>` and `# video: <tag_name>` Ink tags map to a real
`FileIndex` row already synced into the gallery by the normal scanner
(`quickbbs/management/commands/scan.py`) — this app never stores or decodes
any bytes of its own.
for the design this module implements.
"""

from __future__ import annotations

import os

from django.db import transaction
from django.urls import reverse

from interactive_fiction.models import Story, StoryImage
from quickbbs.models import DirectoryIndex, FileIndex
from thumbnails.models import THUMBNAILFILES_PR_FILEINDEX_FILETYPE, ThumbnailFiles


def find_file_by_path(full_filepathname: str, *, additional_filters: dict[str, object] | None = None) -> FileIndex | None:
    """Resolve a gallery file's full path directly to its live FileIndex row.

    Shared by story_views.py's upload()/edit() (resolving a "reference an
    existing gallery file" image/video field, no filetype restriction),
    interactive_fiction.ingestion.find_inkj_file_by_path (which passes
    additional_filters to also require a .inkj filetype), and any
    game-conversion ingestion tooling resolving a `# image:`/`# video:`
    tag's on-disk path to a FileIndex row to link via link_story_image()
    below. Lives here rather than in ingestion.py to avoid a circular
    import (ingestion.py already imports from story_views.py, which needs
    this function).

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


def link_story_image(story: Story, tag_name: str, file_index: FileIndex, *, is_cover: bool = False) -> None:
    """Map a story's Ink tag to a real gallery file, replacing any prior mapping.

    Eagerly generates the linked file's thumbnail (via the same
    content-addressed `ThumbnailFiles` pipeline every other gallery file
    already uses) as part of linking, rather than leaving thumbnail
    generation to the first play-time request — see the design plan's
    "Resolution" step 4 for the tradeoff this accepts (more ingestion-time
    work, no first-request latency).

    Args:
        story: The story the image/video belongs to.
        tag_name: The Ink `# image: <tag_name>` or `# video: <tag_name>`
            value this file maps to.
        file_index: The gallery file this tag resolves to.
        is_cover: Whether to mark the resulting StoryImage as this story's
            cover (see StoryImage.is_cover) — the library-grid thumbnail
            comes from the linked file's own ThumbnailFiles row.
    """
    with transaction.atomic():
        if is_cover:
            StoryImage.objects.filter(story=story, is_cover=True).exclude(tag_name=tag_name).update(is_cover=False)
        defaults: dict[str, object] = {"file_index": file_index}
        if is_cover:
            defaults["is_cover"] = True
        StoryImage.objects.update_or_create(story=story, tag_name=tag_name, defaults=defaults)

    if file_index.file_sha256:
        ThumbnailFiles.get_or_create_thumbnail_record(
            file_index.file_sha256,
            suppress_save=False,
            prefetch_related_thumbnail=THUMBNAILFILES_PR_FILEINDEX_FILETYPE,
            select_related_fileindex=("filetype",),
        )


#: Media kind (ink_engine.media_resolver.parse_media_tags()'s own "image"/
#: "video" values) -> the URL name that serves it. Kept here, not in
#: ink_engine, since a URL name is a Django-routing concept the engine has
#: no business knowing.
_MEDIA_KIND_URL_NAMES: dict[str, str] = {"image": "if_story_image", "video": "if_story_video"}


class DjangoMediaResolver:  # pylint: disable=too-few-public-methods
    """Resolves media tags against this story's own `StoryImage` rows.

    `ink_engine.media_resolver.MediaResolver`'s Django-backed
    implementation: one batched `StoryImage` query per `resolve()` call.
    """

    def __init__(self, story: Story) -> None:
        """
        Args:
            story: The story whose own `StoryImage` rows this resolver
                answers from.
        """
        self._story = story

    def resolve(self, requests: list[tuple[str, str]]) -> list[str]:
        """Resolve a turn's media requests against `self._story.images`.

        Args:
            requests: `ink_engine.media_resolver.parse_media_tags()`'s own
                output for this turn.

        Returns:
            One `if_story_image`/`if_story_video` URL per request with a
            matching `StoryImage` row, GROUPED by kind (all images, then
            all videos — `MediaResolver.resolve()`'s own contract). A tag
            with no matching row is silently dropped: a work-in-progress
            story with placeholder tags still plays, text-only.
        """
        all_tag_names = [tag_name for _kind, tag_name in requests]
        if not all_tag_names:
            return []

        available = set(self._story.images.filter(tag_name__in=all_tag_names).values_list("tag_name", flat=True))
        grouped: dict[str, list[str]] = {kind: [] for kind in _MEDIA_KIND_URL_NAMES}
        for kind, tag_name in requests:
            if tag_name in available:
                grouped[kind].append(tag_name)

        urls: list[str] = []
        for kind, url_name in _MEDIA_KIND_URL_NAMES.items():
            urls.extend(reverse(url_name, args=[self._story.slug, tag_name]) for tag_name in grouped[kind])
        return urls

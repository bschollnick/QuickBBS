"""Story-management views for the interactive_fiction app.

story_image()/story_video()/story_cover() serve a story's linked gallery
FileIndex rows. upload()/edit() are the authoring flow, **referencing
existing gallery files by path rather than accepting uploaded bytes.**
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from ink_engine.engine import (
    InkPathError,
    find_unbound_externals,
    load_story_root,
)
from interactive_fiction.bundle_media import (
    resolve_tag_in_bundle,
    serve_member,
)
from interactive_fiction.models import Story
from quickbbs.common import can_upload_story


def _accessible_story(request: WSGIRequest, slug: str, *, defer_compiled: bool = False) -> Story | HttpResponse:
    """Call `views._get_accessible_story()`, imported here (not at module
    level) because `views.py -> ingestion.py -> story_views.py` already
    forms a cycle a module-level import would close (confirmed by testing).
    The one inline import in this file — every caller below goes through
    this wrapper instead of repeating it.
    """
    # isort:skip keeps this on one line: split across lines, the pylint
    # disable lands on the imported NAME, where it suppresses nothing.
    from interactive_fiction.views import _get_accessible_story  # pylint: disable=import-outside-toplevel  # isort:skip

    return _get_accessible_story(request, slug, defer_compiled=defer_compiled)


def story_image(request: WSGIRequest, slug: str, tag_name: str) -> HttpResponse:
    """Serve one image from a story's bundle, by its own media tag.

    Gated by the same user_can_access() check as the story itself (not
    login_required alone) — otherwise a guessable image URL would leak
    private story art to any authenticated user, or to anonymous users for
    a non-public story.

    Args:
        request: The incoming request.
        slug: The story's slug.
        tag_name: The tag as the story wrote it, resolved by the game's
            own rules (`bundle_media.resolve_tag_in_bundle`).

    Returns:
        The image, streamed from inside the bundle, or 404 when the story
        has no bundle or nothing answers the tag. 403 if the user may not
        read this story.

    Raises:
        Http404: If no accessible Story matches slug.
    """
    story = _accessible_story(request, slug, defer_compiled=True)
    if isinstance(story, HttpResponse):
        return story

    bundle = story.bundle_path
    if bundle is None:
        return HttpResponse(status=404)
    member = resolve_tag_in_bundle(bundle, "image", tag_name)
    if member is None:
        return HttpResponse(status=404)
    return serve_member(request, bundle, member)


def story_video(request: WSGIRequest, slug: str, tag_name: str) -> HttpResponse:
    """Serve one video from a story's bundle, with Range-request support.

    Gated the same way as story_image() above. A browser cannot seek
    without Range, so `serve_member` answers 206 for one.

    Args:
        request: The incoming request.
        slug: The story's slug.
        tag_name: The tag as the story wrote it.

    Returns:
        The video, streamed from inside the bundle, or 404 when the story
        has no bundle or nothing answers the tag.

    Raises:
        Http404: If no accessible Story matches slug.
    """
    story = _accessible_story(request, slug, defer_compiled=True)
    if isinstance(story, HttpResponse):
        return story

    bundle = story.bundle_path
    if bundle is None:
        return HttpResponse(status=404)
    member = resolve_tag_in_bundle(bundle, "video", tag_name)
    if member is None:
        return HttpResponse(status=404)
    return serve_member(request, bundle, member, ranged=True)


def story_cover(request: WSGIRequest, slug: str) -> HttpResponse:
    """Serve a story's library-grid cover thumbnail.

    Served from the thumbnail cached on the row at ingestion, never by
    reading the bundle: a library page is 30 cards, each its own request,
    and opening a bundle costs ~44 ms against ~0 for a stored blob.

    Gated the same way as story_image() and play() (user_can_access(), not
    login_required) so the library page's anonymous public-story branch can
    still render covers.

    Args:
        request: The incoming request.
        slug: The story's slug.

    Returns:
        The cover thumbnail (always JPEG, per ThumbnailFiles' own output
        format), or 404 when the game ships no cover -- a cosmetic gap,
        not an error.

    Raises:
        Http404: If no accessible Story matches slug.
    """
    story = _accessible_story(request, slug, defer_compiled=True)
    if isinstance(story, HttpResponse):
        return story

    thumbnail = story.cover_thumbnail
    if thumbnail is None or not thumbnail.small_thumb:
        return HttpResponse(status=404)

    response = HttpResponse(bytes(thumbnail.small_thumb), content_type="image/jpeg")
    response["Content-Disposition"] = f'inline; filename="{story.slug}-cover.jpg"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


def validate_story_upload(raw_bytes: bytes) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate an uploaded compiled-Ink-JSON file.

    Args:
        raw_bytes: The raw uploaded file content.

    Returns:
        (parsed_json, errors) — parsed_json is None if validation failed
        (errors is then non-empty); otherwise parsed_json is the decoded
        dict and errors is empty. Checks, in order: parses as JSON; has
        the expected top-level Ink structure (inkVersion/root/listDefs
        keys); inkVersion is in settings.SUPPORTED_INK_VERSIONS; every
        EXTERNAL-declared function call site resolves to a same-named ink
        fallback (find_unbound_externals(), naming the unbound
        function(s) in the error per the plan's requirement).
    """
    try:
        data = json.loads(raw_bytes)
    except (ValueError, UnicodeDecodeError):
        return None, ["File is not valid JSON."]

    if not isinstance(data, dict) or not all(key in data for key in ("inkVersion", "root", "listDefs")):
        return None, ["File does not look like compiled Ink JSON (missing inkVersion/root/listDefs)."]

    if data["inkVersion"] not in settings.SUPPORTED_INK_VERSIONS:
        supported = ", ".join(str(v) for v in settings.SUPPORTED_INK_VERSIONS)
        return None, [f"inkVersion {data['inkVersion']} is not supported (supported: {supported})."]

    try:
        root = load_story_root(data)
    except InkPathError as exc:
        return None, [f"Compiled JSON could not be loaded: {exc}"]

    unbound = find_unbound_externals(root)
    if unbound:
        names = ", ".join(unbound)
        return None, [f"EXTERNAL function(s) with no ink fallback: {names}."]

    return data, []


def create_story_from_compiled_json(owner, title: str, data: dict[str, Any], *, source_fqfn: str = "", source_sha256: str = "") -> Story:
    """Create a new Story row from already-validated compiled Ink JSON.

    Shared by upload() (source_fqfn/source_sha256 left at their defaults —
    an upload-form story has no scanner-tracked source file) and
    interactive_fiction.ingestion.ingest_stories() (which passes both,
    scanner-ingestion fields).

    Args:
        owner: The story's owner.
        title: The story's title.
        data: Already-validated compiled Ink JSON (see validate_story_upload()).
        source_fqfn: The scanner-tracked source file's full path, or "" for
            an upload-form story.
        source_sha256: The scanner-tracked source file's sha256, or "" for
            an upload-form story.

    Returns:
        The newly created Story, not public by default.
    """
    return Story.objects.create(
        owner=owner,
        title=title,
        slug=unique_story_slug(title),
        compiled_json=data,
        ink_version=str(data.get("inkVersion", "")),
        is_public=False,
        source_fqfn=source_fqfn,
        source_sha256=source_sha256,
    )


def unique_story_slug(title: str) -> str:
    """Generate a unique Story.slug from a title, appending -2/-3/... on collision.

    Args:
        title: The story's title, as entered on the upload form.

    Returns:
        A slug not already used by any existing Story row.
    """
    base = slugify(title) or "story"
    slug = base
    suffix = 2
    while Story.objects.filter(slug=slug).exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


@login_required
def upload(request: WSGIRequest) -> HttpResponse:
    """Upload a new compiled Ink story.

    Gated to can_upload_story() (staff/superuser, per the plan's decision)
    rather than every authenticated user. On successful validation, a new
    Story row is created with is_public=False by default (per the plan) —
    the owner opts into sharing afterward via edit(). An optional cover
    A cover is not set here: it comes from the game's own bundle, read and
    thumbnailed at ingestion.

    Args:
        request: The incoming request. POST: "title" (str). FILES:
            "story_file" (the compiled .ink.json).

    Returns:
        A redirect to the new story's play page on success; the upload
        form (re-rendered with errors) on validation failure or GET.
    """
    if not can_upload_story(request.user):
        return HttpResponse(status=403)

    errors: list[str] = []
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        upload_file = request.FILES.get("story_file")
        if not title:
            errors.append("Title is required.")
        if upload_file is None:
            errors.append("A compiled .ink.json file is required.")
        elif upload_file.size is not None and upload_file.size > settings.MAX_STORY_UPLOAD_BYTES:
            errors.append(f"File is too large (max {settings.MAX_STORY_UPLOAD_BYTES:,} bytes).")
        else:
            data, validation_errors = validate_story_upload(upload_file.read()) if upload_file else (None, [])
            errors.extend(validation_errors)
            if data is not None and not errors:
                story = create_story_from_compiled_json(request.user, title, data)
                return redirect("if_play", slug=story.slug)

    return render(request, "interactive_fiction/upload.jinja", {"errors": errors, "user": request.user}, using="Jinja2")


def _apply_story_file_replacement(request: WSGIRequest, story: Story) -> list[str]:
    """Validate and apply an optional "story_file" replacement upload onto `story`.

    Args:
        request: The incoming request. FILES: optional "story_file".
        story: The story being edited — mutated in place (compiled_json,
            ink_version) on success; left untouched on any error.

    Returns:
        A list of validation errors (empty if there was no upload, or it
        was valid and applied).
    """
    upload_file = request.FILES.get("story_file")
    if upload_file is None:
        return []
    if upload_file.size is not None and upload_file.size > settings.MAX_STORY_UPLOAD_BYTES:
        return [f"File is too large (max {settings.MAX_STORY_UPLOAD_BYTES:,} bytes)."]

    data, errors = validate_story_upload(upload_file.read())
    if data is not None and not errors:
        story.compiled_json = data
        story.ink_version = str(data.get("inkVersion", ""))
    return errors


@login_required
def edit(request: WSGIRequest, slug: str) -> HttpResponse:
    """Replace a story's compiled_json, retitle it, and manage sharing.

    Re-uploading a revised .ink.json goes through the same validation as
    upload() (JSON structure, inkVersion, unbound-EXTERNAL check). Existing
    players' CurrentGame/SaveState rows are left untouched here — a stored
    state whose path no longer resolves against the new compiled_json is
    repaired lazily on next load, not here (deferred; see the plan's
    Save-compatibility repair section). A cover is not set here: it comes
    from the game's own bundle, thumbnailed at ingestion.

    Args:
        request: The incoming request. POST: "title" (optional, str),
            "is_public" (optional checkbox). FILES: "story_file"
            (optional — omit to edit title/visibility only, without
            replacing content).

    Returns:
        The edit form (GET, or POST with errors); a redirect back to the
        edit form on success.

    Raises:
        Http404: If no Story matches slug.
    """
    story = get_object_or_404(Story.objects.defer("compiled_json"), slug=slug)
    if story.owner_id != request.user.pk and not request.user.is_superuser:
        return HttpResponse(status=403)

    errors: list[str] = []
    if request.method == "POST":
        errors.extend(_apply_story_file_replacement(request, story))

        title = request.POST.get("title", "").strip()
        if title:
            story.title = title
        story.is_public = bool(request.POST.get("is_public"))

        if not errors:
            story.save()
            return redirect("if_edit", slug=story.slug)

    return render(request, "interactive_fiction/edit.jinja", {"story": story, "errors": errors, "user": request.user}, using="Jinja2")

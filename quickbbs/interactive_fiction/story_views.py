"""Story-management views for the interactive_fiction app (Steps 4/5).

Split out of views.py (2026-08-16) once that module passed pylint's
1000-line module threshold after Steps 5/7/8 — a pure file-organization
split, no behavior changed. story_image()/story_cover() serve
StoryImageBlob content (Step 5); upload()/edit() are the authoring flow
(Step 4), with Step 5's image-zip/cover-image handling folded in.
"""

from __future__ import annotations

import io
import json
from typing import Any

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from frontend.serve_up import send_file_response
from interactive_fiction.engine import (
    InkPathError,
    find_unbound_externals,
    load_story_root,
)
from interactive_fiction.images import extract_image_zip, set_story_image
from interactive_fiction.models import Story, StoryImage, user_can_access
from quickbbs.common import can_upload_story


def story_image(request: WSGIRequest, slug: str, tag_name: str) -> HttpResponse:
    """Serve a story image blob by tag name.

    Gated by the same user_can_access() check as the story itself (not
    login_required alone) — otherwise a guessable image URL would leak
    private story art to any authenticated user, or to anonymous users for
    a non-public story. Imitates ThumbnailFiles.send_thumbnail's
    io.BytesIO(blob) + send_file_response pattern (thumbnails/models.py).

    Args:
        request: The incoming request.
        slug: The story's slug.
        tag_name: The image tag name to serve (matches a StoryImage.tag_name
            for this story exactly — no normalization).

    Returns:
        The image, served inline with X-Content-Type-Options: nosniff, or a
        403/404-equivalent response.

    Raises:
        Http404: If no accessible Story or matching StoryImage exists.
    """
    story = get_object_or_404(Story.objects.defer("compiled_json"), slug=slug, is_available=True)
    if not user_can_access(story, request.user):
        return HttpResponse(status=403)

    image = get_object_or_404(StoryImage, story=story, tag_name=tag_name)
    blob = image.blob
    response = send_file_response(
        filename=tag_name,
        content_to_send=io.BytesIO(blob.image_blob),
        mtype=blob.content_type,
        attachment=False,
        expiration=300,
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


def story_cover(request: WSGIRequest, slug: str) -> HttpResponse:
    """Serve a story's library-grid cover thumbnail.

    Gated the same way as story_image() and play() (user_can_access(), not
    login_required) so the library page's anonymous public-story branch can
    still render covers.

    Args:
        request: The incoming request.
        slug: The story's slug.

    Returns:
        The cover thumbnail (always JPEG, matching create_thumbnails_from_bytes'
        default output format), or a 403/404-equivalent response.

    Raises:
        Http404: If no accessible Story matches slug, or it has no
            cover_image / the cover's blob has no generated thumbnail yet.
    """
    story = get_object_or_404(Story.objects.defer("compiled_json"), slug=slug, is_available=True)
    if not user_can_access(story, request.user):
        return HttpResponse(status=403)
    cover = story.cover_image
    if cover is None or cover.blob.cover_thumb is None:
        return HttpResponse(status=404)

    response = send_file_response(
        filename=f"{story.slug}-cover.jpg",
        content_to_send=io.BytesIO(cover.blob.cover_thumb),
        mtype="image/jpeg",
        attachment=False,
        expiration=300,
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


def validate_story_upload(raw_bytes: bytes) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate an uploaded compiled-Ink-JSON file per Step 4's rules.

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
    per the plan's Step 9 scanner-ingestion fields).

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
    the owner opts into sharing afterward via edit(). An optional images zip
    (Step 5) is extracted after the story is saved, mapping each member's
    basename to a `# image: <tag_name>` tag; a tag whose referenced image
    fails to decode is reported but does not roll back the story itself —
    the story still plays text-only for that tag (per the plan).

    Args:
        request: The incoming request. POST: "title" (str), FILES:
            "story_file" (the compiled .ink.json), optional "images_zip"
            (a zip of tag-name-keyed image files).

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
        images_zip = request.FILES.get("images_zip")
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
                if images_zip is not None:
                    extract_image_zip(story, images_zip.read())
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


def _apply_cover_image_upload(request: WSGIRequest, story: Story) -> list[str]:
    """Validate and apply an optional "cover_image"/"cover_tag_name" upload.

    Args:
        request: The incoming request. FILES: optional "cover_image".
            POST: "cover_tag_name", required if "cover_image" is given.
        story: The story being edited.

    Returns:
        A list of validation errors (empty if there was no upload, or it
        was valid and applied).
    """
    cover_image = request.FILES.get("cover_image")
    if cover_image is None:
        return []
    cover_tag_name = request.POST.get("cover_tag_name", "").strip()
    if not cover_tag_name:
        return ["A tag name is required when uploading a cover image."]
    if cover_image.size is not None and cover_image.size > settings.MAX_STORY_IMAGE_UPLOAD_BYTES:
        return [f"Cover image is too large (max {settings.MAX_STORY_IMAGE_UPLOAD_BYTES:,} bytes)."]

    cover_error = set_story_image(story, cover_tag_name, cover_image.read(), is_cover=True)
    return [cover_error] if cover_error else []


@login_required
def edit(request: WSGIRequest, slug: str) -> HttpResponse:
    """Replace a story's compiled_json, retitle it, and manage sharing.

    Re-uploading a revised .ink.json goes through the same validation as
    upload() (JSON structure, inkVersion, unbound-EXTERNAL check). Existing
    players' CurrentGame/SaveState rows are left untouched here — a stored
    state whose path no longer resolves against the new compiled_json is
    repaired lazily on next load, not here (deferred; see the plan's
    Save-compatibility repair section). Images (Step 5) can be added or
    replaced via an "images_zip" upload (extracted the same way as
    upload()'s), and/or a single "cover_image" file mapped to the tag name
    given in "cover_tag_name" — the latter also sets Story.cover_image and
    generates its library-grid thumbnail.

    Args:
        request: The incoming request. POST: "title" (optional, str),
            "is_public" (optional checkbox), "cover_tag_name" (optional,
            str — required only if "cover_image" is given), FILES:
            "story_file" (optional — omit to edit title/visibility only,
            without replacing content), "images_zip" (optional),
            "cover_image" (optional, single file).

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
        errors.extend(_apply_cover_image_upload(request, story))

        title = request.POST.get("title", "").strip()
        if title:
            story.title = title
        story.is_public = bool(request.POST.get("is_public"))

        if not errors:
            story.save()
            images_zip = request.FILES.get("images_zip")
            if images_zip is not None:
                errors.extend(extract_image_zip(story, images_zip.read()))
            return redirect("if_edit", slug=story.slug)

    return render(request, "interactive_fiction/edit.jinja", {"story": story, "errors": errors, "user": request.user}, using="Jinja2")

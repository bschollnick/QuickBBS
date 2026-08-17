"""Save-slot views for the interactive_fiction app (Step 3).

Split out of views.py (2026-08-16) once that module passed pylint's
1000-line module threshold after Steps 5/7/8 — a pure file-organization
split, no behavior changed. saves()/saves_save()/saves_load()/
saves_export()/saves_import() are the named-slot manager: save/load copy
CurrentGame.state <-> SaveState.state as snapshots (never a live link — see
each view's own docstring), export/import round-trip a slot through a
downloadable JSON envelope.
"""

from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from interactive_fiction.models import CurrentGame, SaveState, Story, user_can_access
from interactive_fiction.views import _load_game_state, _render_play_content


@login_required
def saves(request: WSGIRequest, slug: str) -> HttpResponse:
    """List save slots for a story, with a save/load action per slot.

    Args:
        request: The incoming request.
        slug: The story's slug.

    Returns:
        The rendered save-slot manager page.

    Raises:
        Http404: If no accessible Story matches slug.
    """
    story = get_object_or_404(Story.objects.defer("compiled_json"), slug=slug, is_available=True)
    if not user_can_access(story, request.user):
        return HttpResponse(status=403)

    slots = list(SaveState.objects.filter(user=request.user, story=story).order_by("slot").only("slot", "label", "updated_at"))
    return render(
        request,
        "interactive_fiction/saves.jinja",
        {
            "story": story,
            "slots": slots,
            "max_slots": settings.MAX_SAVE_SLOTS_PER_STORY,
            "used_slot_numbers": {s.slot for s in slots},
            "user": request.user,
        },
        using="Jinja2",
    )


@login_required
@require_POST
def saves_save(request: WSGIRequest, slug: str, slot: int) -> HttpResponse:
    """Save the player's current in-flight game into a named slot.

    Copies CurrentGame.state into SaveState.state — a snapshot, not a
    link; subsequent play never mutates a saved slot (per the plan's
    "loading never mutates the slot during play" design).

    Args:
        request: The incoming request. POST body: optional "label".
        slug: The story's slug.
        slot: The slot index (0..MAX_SAVE_SLOTS_PER_STORY-1).

    Returns:
        A redirect back to the save-slot manager, or 400 if slot is out
        of the configured range.

    Raises:
        Http404: If no accessible Story or CurrentGame exists.
    """
    story = get_object_or_404(Story.objects.defer("compiled_json"), slug=slug, is_available=True)
    if not user_can_access(story, request.user):
        return HttpResponse(status=403)
    if slot < 0 or slot >= settings.MAX_SAVE_SLOTS_PER_STORY:
        return HttpResponse(status=400)

    current_game = get_object_or_404(CurrentGame, user=request.user, story=story)
    label = str(request.POST.get("label", ""))[:100]
    SaveState.objects.update_or_create(
        user=request.user,
        story=story,
        slot=slot,
        defaults={"state": current_game.state, "label": label},
    )
    return render(request, "interactive_fiction/play_saved.jinja", {"story": story, "slot": slot, "user": request.user}, using="Jinja2")


@login_required
@require_POST
def saves_load(request: WSGIRequest, slug: str, slot: int) -> HttpResponse:
    """Load a named slot's state into the player's in-flight game.

    Copies SaveState.state into CurrentGame.state — the slot itself is
    left untouched, matching the plan's "loading never mutates the slot"
    design; only a subsequent explicit save overwrites it. Writes
    save_state.state verbatim (not state.to_dict()) so Step 8's
    transcript/previous_state keys — which live alongside the engine's own
    serialized fields but aren't known to InkRuntimeState itself — survive
    the load instead of being silently dropped.

    Args:
        request: The incoming request.
        slug: The story's slug.
        slot: The slot index to load.

    Returns:
        The rendered play-content partial for the loaded turn.

    Raises:
        Http404: If no accessible Story or matching SaveState exists.
    """
    story = get_object_or_404(Story.objects.defer("compiled_json"), slug=slug, is_available=True)
    if not user_can_access(story, request.user):
        return HttpResponse(status=403)

    save_state = get_object_or_404(SaveState, user=request.user, story=story, slot=slot)
    state = _load_game_state(story, save_state)
    current_game, _ = CurrentGame.objects.get_or_create(
        user=request.user, story=story, defaults={"state": save_state.state, "turn_count": state.turn_count}
    )
    current_game.state = save_state.state
    current_game.turn_count = state.turn_count
    current_game.save(update_fields=["state", "turn_count", "updated_at"])

    return HttpResponse(
        _render_play_content(
            request, story, state, transcript=save_state.state.get("transcript", []), can_undo=bool(save_state.state.get("previous_state"))
        )
    )


@login_required
def saves_export(request: WSGIRequest, slug: str, slot: int) -> HttpResponse:
    """Download a save slot as a JSON file.

    Args:
        request: The incoming request.
        slug: The story's slug.
        slot: The slot index to export.

    Returns:
        A JSON attachment download, or 404 if no accessible Story or
        matching SaveState exists.
    """
    story = get_object_or_404(Story.objects.defer("compiled_json"), slug=slug, is_available=True)
    if not user_can_access(story, request.user):
        return HttpResponse(status=403)

    save_state = get_object_or_404(SaveState, user=request.user, story=story, slot=slot)
    envelope = {
        "quickbbs_if_save_version": 1,
        "story_slug": story.slug,
        "ink_version": story.ink_version,
        "label": save_state.label,
        "state": save_state.state,
    }
    response = JsonResponse(envelope)
    filename = f"{story.slug}-slot{slot}.json"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _parse_import_slot(request: WSGIRequest) -> int | None:
    """Parse and range-check the "slot" POST field for a save import.

    Args:
        request: The incoming request.

    Returns:
        The slot index, or None if it's missing, non-numeric, or outside
        [0, MAX_SAVE_SLOTS_PER_STORY).
    """
    try:
        slot = int(request.POST["slot"])
    except (KeyError, ValueError):
        return None
    if slot < 0 or slot >= settings.MAX_SAVE_SLOTS_PER_STORY:
        return None
    return slot


def _validate_save_envelope(envelope: object, story: Story) -> bool:
    """Return whether a decoded save-file envelope is well-formed and
    belongs to the given story.

    Args:
        envelope: The result of json.loads()'ing an uploaded save file —
            expected shape matches saves_export()'s own envelope:
            {"quickbbs_if_save_version": 1, "story_slug": ..., "state": {...}}.
        story: The story being imported into.

    Returns:
        True if envelope is a dict with a recognized version, a matching
        story_slug, and a dict-shaped "state" key.
    """
    if not isinstance(envelope, dict):
        return False
    if envelope.get("quickbbs_if_save_version") != 1:
        return False
    if envelope.get("story_slug") != story.slug:
        return False
    return isinstance(envelope.get("state"), dict)


@login_required
@require_POST
def saves_import(request: WSGIRequest, slug: str) -> HttpResponse:
    """Upload and import a save file into a chosen slot.

    Validates the envelope (matches saves_export()'s own shape:
    "quickbbs_if_save_version" understood, "story_slug" matches the story
    being loaded into) before writing anything, and rejects an oversized
    upload before attempting json.loads at all.

    Args:
        request: The incoming request. POST body: "slot" (int),
            optional "label" (str, overrides the envelope's own label if
            given). FILES: "save_file" (the exported JSON envelope).

    Returns:
        A redirect back to the save-slot manager, or 400 for a malformed
        /oversized/mismatched-story upload.

    Raises:
        Http404: If no accessible Story matches slug.
    """
    story = get_object_or_404(Story.objects.defer("compiled_json"), slug=slug, is_available=True)
    if not user_can_access(story, request.user):
        return HttpResponse(status=403)

    slot = _parse_import_slot(request)
    upload_file = request.FILES.get("save_file")
    if slot is None or upload_file is None or upload_file.size is None or upload_file.size > settings.MAX_SAVE_FILE_UPLOAD_BYTES:
        return HttpResponse(status=400)

    try:
        envelope = json.loads(upload_file.read())
    except (ValueError, UnicodeDecodeError):
        return HttpResponse(status=400)

    if not _validate_save_envelope(envelope, story):
        return HttpResponse(status=400)

    label = str(request.POST.get("label") or envelope.get("label", ""))[:100]
    SaveState.objects.update_or_create(
        user=request.user,
        story=story,
        slot=slot,
        defaults={"state": envelope["state"], "label": label},
    )
    return render(request, "interactive_fiction/play_saved.jinja", {"story": story, "slot": slot, "user": request.user}, using="Jinja2")

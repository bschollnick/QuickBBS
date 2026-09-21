"""Save-slot views for the interactive_fiction app.

saves()/saves_save()/saves_load()/saves_export()/saves_import() are the
named-slot manager: save/load copy CurrentGame.state <-> SaveState.state
as SNAPSHOTS, never a live link. export/import round-trip a slot through
a downloadable JSON envelope.

The slot, label, envelope and validation logic lives in
`if_session.game_saves`, shared with the desktop player. These views own
what is Django's: authentication, the upload size guard, and turning the
library's refusals into responses.
"""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, cast

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.handlers.wsgi import WSGIRequest
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from if_session import session_state
from if_session.game_saves import (
    GameSaveError,
    delete_game_save,
    export_game_save,
    import_game_save,
    list_game_saves,
    load_game_save,
    quickload,
    quicksave,
    save_game,
)

from interactive_fiction.game_saves_database import GameSavesDatabase
from interactive_fiction.models import CurrentGame, Story
from interactive_fiction.views import (
    _get_accessible_story,
    _load_game_state,
    _render_play_content,
    _unreadable_save_response,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser


def _request_user(request: WSGIRequest) -> AbstractUser:
    """Return the signed-in user behind a `@login_required` view.

    `request.user` is typed `User | AnonymousUser` because Django cannot
    see the decorator. Every view in this module carries it, so the
    anonymous case is unreachable; asserting it states that invariant
    once instead of repeating a cast at each use.
    """
    if not request.user.is_authenticated:
        raise PermissionDenied("This view requires a signed-in user.")
    return cast("AbstractUser", request.user)


def _game_saves_database(request: WSGIRequest, story: Story) -> GameSavesDatabase:
    """Return the database rows this request's saves are kept in."""
    return GameSavesDatabase(user=_request_user(request), story=story)


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
    story = _get_accessible_story(request, slug, defer_compiled=True)
    if isinstance(story, HttpResponse):
        return story

    return render(
        request,
        "interactive_fiction/saves.jinja",
        {
            "story": story,
            "slots": list_game_saves(
                story.slug,
                saves_in=_game_saves_database(request, story),
                maximum_gamesave_slots=settings.MAX_SAVE_SLOTS_PER_STORY,
            ),
            "max_slots": settings.MAX_SAVE_SLOTS_PER_STORY,
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
    story = _get_accessible_story(request, slug, defer_compiled=True)
    if isinstance(story, HttpResponse):
        return story
    current_game = get_object_or_404(CurrentGame, user=request.user, story=story)
    try:
        save_game(
            story.slug,
            slot,
            current_game.state,
            str(request.POST.get("label", "")),
            saves_in=_game_saves_database(request, story),
            maximum_gamesave_slots=settings.MAX_SAVE_SLOTS_PER_STORY,
            saved_at=timezone.now().isoformat(),
        )
    except GameSaveError:
        return HttpResponse(status=400)
    return render(request, "interactive_fiction/play_saved.jinja", {"story": story, "slot": slot, "user": request.user}, using="Jinja2")


@login_required
@require_POST
def saves_load(request: WSGIRequest, slug: str, slot: int) -> HttpResponse:
    """Load a named slot's state into the player's in-flight game.

    Copies SaveState.state into CurrentGame.state — the slot itself is
    left untouched, matching the plan's "loading never mutates the slot"
    design; only a subsequent explicit save overwrites it. Writes
    save_state.state verbatim (not state.to_dict()) so the
    transcript/previous_state keys — which live alongside the engine's own
    serialized fields but aren't known to InkRuntimeState itself — survive
    the load instead of being silently dropped.

    Args:
        request: The incoming request.
        slug: The story's slug.
        slot: The slot index to load.

    Returns:
        The rendered play-content partial for the loaded turn, or the
        refusal partial (409) if the slot holds a save this server cannot
        read. The slot is left untouched either way.

    Raises:
        Http404: If no accessible Story exists, or the slot is empty.
    """
    story = _get_accessible_story(request, slug, defer_compiled=True)
    if isinstance(story, HttpResponse):
        return story

    try:
        saved_state = load_game_save(
            story.slug,
            slot,
            saves_in=_game_saves_database(request, story),
            maximum_gamesave_slots=settings.MAX_SAVE_SLOTS_PER_STORY,
        )
    except GameSaveError as error:
        raise Http404(str(error)) from error
    except session_state.SaveFormatError as error:
        # Deliberately not wrapped by the library: the slot read fine and
        # the save itself is unreadable, which has its own refusal page.
        return _unreadable_save_response(request, story, error)

    return _resume_from_saved_state(request, story, saved_state)


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
    story = _get_accessible_story(request, slug, defer_compiled=True)
    if isinstance(story, HttpResponse):
        return story

    try:
        envelope = export_game_save(
            story.slug,
            slot,
            saves_in=_game_saves_database(request, story),
            maximum_gamesave_slots=settings.MAX_SAVE_SLOTS_PER_STORY,
            # Advisory only: recorded for whoever inspects the file, never
            # validated on import. A save refusing to load because a story
            # was recompiled is worse than one that loads and misbehaves
            # visibly.
            metadata={"ink_version": story.ink_version},
        )
    except GameSaveError as error:
        raise Http404(str(error)) from error
    response = JsonResponse(envelope)
    # Named for what the player sees in the table, not the stored number.
    filename = f"{story.slug}-slot{slot + 1}.json"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _parse_import_slot(request: WSGIRequest) -> int | None:
    """Parse the "slot" POST field for a save import.

    The form shows slots numbered from 1, matching what a player sees in
    the table, so the value arrives one higher than the stored number and
    is converted here. The range check itself belongs to
    `import_game_save()`, which refuses an out-of-range slot before
    writing anything.

    Args:
        request: The incoming request.

    Returns:
        The stored, zero-based slot number, or None if the field is
        missing or non-numeric.
    """
    try:
        return int(request.POST["slot"]) - 1
    except (KeyError, ValueError):
        return None


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
    story = _get_accessible_story(request, slug, defer_compiled=True)
    if isinstance(story, HttpResponse):
        return story

    slot = _parse_import_slot(request)
    upload_file = request.FILES.get("save_file")
    if slot is None or upload_file is None or upload_file.size is None or upload_file.size > settings.MAX_SAVE_FILE_UPLOAD_BYTES:
        return HttpResponse(status=400)

    try:
        envelope = json.loads(upload_file.read())
    except (ValueError, UnicodeDecodeError):
        return HttpResponse(status=400)

    # A posted label overrides the file's own; None means "use the file's".
    posted_label = str(request.POST["label"]) if request.POST.get("label") else None
    try:
        import_game_save(
            story.slug,
            slot,
            envelope,
            saves_in=_game_saves_database(request, story),
            maximum_gamesave_slots=settings.MAX_SAVE_SLOTS_PER_STORY,
            saved_at=timezone.now().isoformat(),
            label=posted_label,
        )
    except GameSaveError as error:
        return HttpResponse(str(error), status=400, content_type="text/plain; charset=utf-8")
    return render(request, "interactive_fiction/play_saved.jinja", {"story": story, "slot": slot, "user": request.user}, using="Jinja2")


def _resume_from_saved_state(request: WSGIRequest, story: Story, saved_state: dict) -> HttpResponse:
    """Put `saved_state` back into play and render the resumed turn.

    Shared by `saves_load()` and `saves_quickload()`: both replace the
    live game with a previously saved one, and the only difference is
    which slot it came from.

    Args:
        request: The incoming request.
        story: The story being resumed.
        saved_state: A state dict from `load_game_save()`/`quickload()`.

    Returns:
        The rendered play-content partial for the resumed turn, or the
        refusal partial (409) when the state cannot be read.
    """
    # Deep-copied for the same reason as views.py's play_undo(): saved_state
    # is about to become the new current_game.state verbatim, so nothing
    # built from it (bindings_for()'s stateful closures) may mutate it.
    try:
        state = _load_game_state(story, saved_state, copy.deepcopy(saved_state.get("engine_state", {})))
    except session_state.SaveFormatError as error:
        return _unreadable_save_response(request, story, error)
    current_game, _ = CurrentGame.objects.get_or_create(
        user=_request_user(request), story=story, defaults={"state": saved_state, "turn_count": state.turn_count}
    )
    # Written verbatim, not state.to_dict(): the transcript/previous_state
    # keys live alongside the engine's own fields and InkRuntimeState does
    # not know them, so rebuilding would silently drop them.
    current_game.state = saved_state
    current_game.turn_count = state.turn_count
    current_game.save(update_fields=["state", "turn_count", "updated_at"])
    if not request.htmx:
        # A plain form POST navigates the whole window, so a bare content
        # fragment would render as the entire document -- the transcript
        # with no page around it. The state is already saved above, so a
        # redirect lands on the game exactly where this load put it.
        return redirect("if_play", slug=story.slug)
    return HttpResponse(
        _render_play_content(
            request,
            story,
            state,
            transcript=saved_state.get("transcript", []),
            can_undo=bool(saved_state.get("previous_state")),
        )
    )


@login_required
@require_POST
def saves_delete(request: WSGIRequest, slug: str, slot: int) -> HttpResponse:
    """Empty one named save slot.

    Deleting an already-empty slot is not an error, matching the desktop
    player and the shared library.

    Args:
        request: The incoming request.
        slug: The story's slug.
        slot: The slot index to empty.

    Returns:
        A redirect back to the save-slot manager, or 400 if slot is out
        of the configured range.

    Raises:
        Http404: If no accessible Story matches slug.
    """
    story = _get_accessible_story(request, slug, defer_compiled=True)
    if isinstance(story, HttpResponse):
        return story
    try:
        delete_game_save(
            story.slug,
            slot,
            saves_in=_game_saves_database(request, story),
            maximum_gamesave_slots=settings.MAX_SAVE_SLOTS_PER_STORY,
        )
    except GameSaveError:
        return HttpResponse(status=400)
    return redirect("if_saves", slug=story.slug)


@login_required
@require_POST
def saves_quicksave(request: WSGIRequest, slug: str) -> HttpResponse:
    """Snapshot the in-flight game into the one quicksave.

    The quicksave has its own reserved slot, so this never disturbs a
    numbered one. A second quicksave replaces the first.

    Args:
        request: The incoming request.
        slug: The story's slug.

    Returns:
        The rendered confirmation partial.

    Raises:
        Http404: If no accessible Story or CurrentGame exists.
    """
    story = _get_accessible_story(request, slug, defer_compiled=True)
    if isinstance(story, HttpResponse):
        return story
    current_game = get_object_or_404(CurrentGame, user=request.user, story=story)
    quicksave(
        story.slug,
        current_game.state,
        saves_in=_game_saves_database(request, story),
        saved_at=timezone.now().isoformat(),
    )
    # Re-renders the turn the player is already on rather than a
    # confirmation page: a quicksave must not interrupt play. The
    # re-render is what makes the sidebar's Quickload button appear.
    state = _load_game_state(story, current_game, copy.deepcopy(current_game.state.get("engine_state", {})))
    return HttpResponse(
        _render_play_content(
            request,
            story,
            state,
            transcript=current_game.state.get("transcript", []),
            can_undo=bool(current_game.state.get("previous_state")),
        )
    )


@login_required
@require_POST
def saves_quickload(request: WSGIRequest, slug: str) -> HttpResponse:
    """Restore the in-flight game from the one quicksave.

    Args:
        request: The incoming request.
        slug: The story's slug.

    Returns:
        The rendered play-content partial for the resumed turn, or the
        refusal partial (409) when the quicksave cannot be read.

    Raises:
        Http404: If no accessible Story exists, or there is no quicksave.
    """
    story = _get_accessible_story(request, slug, defer_compiled=True)
    if isinstance(story, HttpResponse):
        return story
    try:
        saved_state = quickload(story.slug, saves_in=_game_saves_database(request, story))
    except GameSaveError as error:
        raise Http404(str(error)) from error
    except session_state.SaveFormatError as error:
        return _unreadable_save_response(request, story, error)
    return _resume_from_saved_state(request, story, saved_state)

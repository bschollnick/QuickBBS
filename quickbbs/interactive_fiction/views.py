"""Core play-loop views for the interactive_fiction app.

Play routes require login unconditionally (django.contrib.auth's
login_required), unlike the rest of the site's gallery views which only gate
behind quickbbs.common.require_login_if_configured. The library view is the
one route that follows the site-wide policy, since its anonymous branch
(Story.objects.filter(is_public=True)) already handles open-browsing installs.

The turn loop reads/writes CurrentGame.state via
InkRuntimeState.to_dict()/from_dict(), and play_submit() enforces a
concurrent-tab guard: a stale tab whose submitted turn_count no longer
matches the stored row is rejected. "transcript"/"previous_state" are
layered on top of InkRuntimeState's own serialized fields (see
_build_current_game_state()).

Sibling modules hold the rest of the app's views: story_views.py
(upload/authoring), save_views.py (named save slots), panel_views.py (a
game's side panel). The shared engine-state helpers they import stay here.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST
from if_session import session_state
from if_session.character_creation import answers_to_globals
from if_session.game_saves import has_quicksave

from ink_engine.engine import (
    InkRuntimeState,
    load_list_defs,
    load_story_root,
    start_new_story,
)
from interactive_fiction.engine_services import (
    bindings_for,
    game_panel_context,
    play_layout_for,
    plugin_denied_html,
)
from interactive_fiction.game_saves_database import GameSavesDatabase
from interactive_fiction.images import DjangoMediaResolver
from interactive_fiction.ingestion import find_game_file_by_path
from interactive_fiction.models import (
    CurrentGame,
    SaveState,
    Story,
    user_can_access,
)
from quickbbs.common import require_login_if_configured
from user_preferences.models import UserPreferences

# Mirrors UserPreferences.if_font_size/if_text_width's own `choices=`
# (user_preferences/models.py) — kept as plain sets rather than reflecting
# via UserPreferences._meta.get_field(...).choices, since Field.choices is
# typed Optional on the Django stubs (always non-None here, but mypy can't
# know that), and the model's choices rarely change without touching this
# view anyway.
_VALID_IF_FONT_SIZES = {"small", "medium", "large"}
_VALID_IF_TEXT_WIDTHS = {"narrow", "medium", "wide"}

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser, AnonymousUser


def _new_game_state(story: Story, engine_state: dict[str, Any], initial_globals: dict[str, Any] | None = None) -> InkRuntimeState:
    """Build a fresh InkRuntimeState for a story, run to its first stop point.

    Args:
        story: The story to start.
        engine_state: The session's own mutable `engine_state` dict (see
            `_build_current_game_state()`) — passed straight through to
            `engine_services.bindings_for()`, and mutated in place by any
            stateful API's own `init_state()`/bound closures, so the
            caller's own reference already reflects the new game's
            initial per-API state once this returns.
        initial_globals: Ink VAR values to set BEFORE the opening
            `continue_story()` call, e.g. a character-creation answer.
            None leaves the story's own declared VAR defaults untouched.

    Returns:
        A new InkRuntimeState, given real EXTERNAL bindings only if the
        story is marked Story.is_engine_trusted, and already advanced
        through its first continue_story() call so it is ready to display.
    """
    root = load_story_root(story.compiled_json, full_build=False)
    list_defs = load_list_defs(story.compiled_json)
    return start_new_story(
        root,
        list_defs,
        engine_bindings=bindings_for(story, engine_state),
        initial_globals=initial_globals,
    )


def _start_new_game(
    user: AbstractUser, story: Story, initial_globals: dict[str, Any] | None = None
) -> tuple[InkRuntimeState, list[dict[str, object]]]:
    """Build a fresh game for (user, story) and persist it as CurrentGame.

    The shared "start from scratch" sequence `play()`'s first-visit branch,
    `play_restart()`, and `character_creation_submit()` each need: a fresh
    `InkRuntimeState` (see `_new_game_state()`), a one-entry opening
    transcript, and a `CurrentGame` row written (or overwritten, for a
    restart) to hold them. `update_or_create` is used unconditionally —
    safe even for a caller that has already confirmed no row exists (the
    `play()` fresh-game case), since an update_or_create with nothing to
    update behaves exactly like a plain create.

    Args:
        user: The player starting the game.
        story: The story to start.
        initial_globals: See `_new_game_state()`.

    Returns:
        `(state, transcript)` — the new game's own `InkRuntimeState`,
        already advanced to its first stop point and ready to display,
        and its one-entry opening transcript.
    """
    engine_state: dict[str, Any] = {}
    state = _new_game_state(story, engine_state, initial_globals=initial_globals)
    transcript = _append_transcript_entry([], state.last_turn_text, chosen_label=None)
    CurrentGame.objects.update_or_create(
        user=user,
        story=story,
        defaults={
            "state": _build_current_game_state(state, previous_raw_state=None, transcript=transcript, engine_state=engine_state),
            "turn_count": state.turn_count,
        },
    )
    return state, transcript


def _get_accessible_story(request: WSGIRequest, slug: str, *, defer_compiled: bool = False) -> Story | HttpResponse:
    """Look up a story by slug and enforce `user_can_access()`.

    The lookup-then-access-check pair every view in this app needs before
    doing anything else with a story. `defer_compiled=True` skips loading
    `compiled_json` for views that never touch the Ink graph itself (image/
    video/cover serving, save-slot management) — the same optimization
    every one of those views already applied by hand.

    Args:
        request: The incoming request.
        slug: The story's slug.
        defer_compiled: Whether to defer loading `compiled_json`.

    Returns:
        The story on success, or a 403 `HttpResponse` — callers must check
        `isinstance(result, HttpResponse)` and return it as-is rather than
        using it as a `Story`.

    Raises:
        Http404: If no available Story matches slug.
    """
    queryset = Story.objects.defer("compiled_json") if defer_compiled else Story.objects
    story = get_object_or_404(queryset, slug=slug, is_available=True)
    if not user_can_access(story, request.user):
        return HttpResponse(status=403)
    return story


@login_required
def character_creation(request: WSGIRequest, slug: str) -> HttpResponse:
    """Show a game's own character-creation form (Step: new-game questions).

    Only reached for a story whose manifest declares
    `Story.game_new_game_fields` (the normal case, no such fields, skips
    straight to `play()`'s existing fresh-game branch) and only before
    that player's first `CurrentGame` row for this story exists —
    matching the real original game's own one-time "before the
    adventure starts" form (a converted game's own real start-screen HTML).

    Args:
        request: The incoming request.
        slug: The story's slug.

    Returns:
        The character-creation form page.

    Raises:
        Http404: If no accessible Story matches slug.
    """
    story = _get_accessible_story(request, slug)
    if isinstance(story, HttpResponse):
        return story
    return render(request, "interactive_fiction/character_creation.jinja", {"story": story, "user": request.user}, using="Jinja2")


@login_required
@require_POST
def character_creation_submit(request: WSGIRequest, slug: str) -> HttpResponse:
    """Process a submitted character-creation form and start the game.

    Args:
        request: The incoming request (POST body: one form field per
            `Story.game_new_game_fields` entry, keyed by that field's own
            `var` name).
        slug: The story's slug.

    Returns:
        A redirect to the normal play page — with a fresh CurrentGame row
        whose opening turn already reflects every submitted answer, or
        straight to the game in progress when one already exists.

    Raises:
        Http404: If no accessible Story matches slug.
    """
    story = _get_accessible_story(request, slug)
    if isinstance(story, HttpResponse):
        return story

    # Starting a new game REPLACES any game in progress, so this refuses
    # once one exists. play() already sends a first-time visitor here and
    # nobody else afterward, but that guard is on the route in: without
    # this one, a stale form, a double submit, or a bookmarked URL wipes a
    # playthrough with no warning and no undo.
    if CurrentGame.objects.filter(user=request.user, story=story).exists():
        return redirect("if_play", slug=story.slug)

    # A bare, binding-less state to read the story's own real starting
    # global values from (no EXTERNAL calls fire, no continue_story() —
    # constructing InkRuntimeState only runs its global-decl container),
    # so an "add_to" checkbox field can add to the ACTUAL declared
    # default rather than guessing 0.
    base_globals = InkRuntimeState(load_story_root(story.compiled_json, full_build=False), load_list_defs(story.compiled_json)).globals
    initial_globals = answers_to_globals(story.game_new_game_fields, request.POST, story_defaults=base_globals)
    _start_new_game(request.user, story, initial_globals=initial_globals)
    return redirect("if_play", slug=story.slug)


def _stale_turn_response(request: WSGIRequest, story: Story) -> HttpResponse:
    """Render the concurrent-tab guard's 409 partial.

    Shared by every view that enforces the "turn_count" guard
    (`play_submit`, `panel_views.play_panel_command`) — the message a
    submitting tab sees when the row it targeted has already moved on
    under it, so a stale submission is refused rather than silently
    applied on top of state the tab never actually saw.

    Args:
        request: The incoming request.
        story: The story the stale submission targeted.

    Returns:
        The rendered play_stale.jinja partial, status 409.
    """
    return HttpResponse(
        render_to_string("interactive_fiction/play_stale.jinja", {"story": story, "user": request.user}, request=request, using="Jinja2"),
        status=409,
    )


def _unreadable_save_response(request: WSGIRequest, story: Story, error: session_state.SaveFormatError) -> HttpResponse:
    """Render the refusal partial for a save this server cannot read.

    Refusing to load is the intended outcome, so it reaches the player as
    a message rather than a 500.

    Args:
        request: The incoming request.
        story: The story whose save was refused.
        error: The refusal, whose message names the two versions.

    Returns:
        The rendered play_unreadable_save.jinja partial, status 409.
    """
    return HttpResponse(
        render_to_string(
            "interactive_fiction/play_unreadable_save.jinja",
            {"story": story, "user": request.user, "reason": str(error)},
            request=request,
            using="Jinja2",
        ),
        status=409,
    )


def _current_game_for_turn(
    request: WSGIRequest, story: Story, submitted_turn_count: int
) -> tuple[CurrentGame, dict[str, Any], InkRuntimeState] | HttpResponse:
    """Row-lock a story's CurrentGame, enforce the concurrent-tab guard, and rebuild its InkRuntimeState.

    The read-check-load half of the "turn_count" guard both `play_submit`
    and `panel_views.play_panel_command` need before they can each do
    their own different write. MUST be called from inside a
    `transaction.atomic()` block — `select_for_update()` requires one, and
    the caller's own write happens inside the same block this locked the
    row for.

    Args:
        request: The incoming request.
        story: The story being played.
        submitted_turn_count: The turn_count the submitting tab last
            rendered (the guard token).

    Returns:
        `(current_game, engine_state, state)` on success — `engine_state`
        is a deep copy the caller may mutate freely (bindings_for()'s
        stateful closures write into it in place; `current_game.state`
        itself must stay untouched until the caller commits, so
        `play_undo()` can restore it verbatim), and `state` is already
        rebuilt with real bindings over that same `engine_state`. On a
        stale turn_count, `_stale_turn_response(request, story)` instead —
        the caller must check `isinstance(result, HttpResponse)` and
        return it as-is rather than unpacking.
    """
    current_game = get_object_or_404(CurrentGame.objects.select_for_update(), user=request.user, story=story)
    if current_game.turn_count != submitted_turn_count:
        return _stale_turn_response(request, story)

    previous_raw_state = current_game.state
    # Deep-copied, not the same dict object previous_raw_state holds:
    # bindings_for()'s stateful bindings mutate this dict in place as the
    # turn plays out, and previous_raw_state must stay exactly as it was
    # before this turn so play_undo() can restore it verbatim.
    engine_state = copy.deepcopy(previous_raw_state.get("engine_state", {}))
    try:
        state = _load_game_state(story, previous_raw_state, engine_state)
    except session_state.SaveFormatError as error:
        return _unreadable_save_response(request, story, error)
    return current_game, engine_state, state


def _load_game_state(story: Story, saved: CurrentGame | SaveState | dict[str, Any], engine_state: dict[str, Any]) -> InkRuntimeState:
    """Rebuild an InkRuntimeState from a stored CurrentGame/SaveState row or raw state dict.

    Args:
        story: The story the game belongs to (compiled_json must match
            what saved.state was serialized against).
        saved: The stored row (either model — both carry a `state`
            JSONField holding an InkRuntimeState.to_dict() result in the
            identical shape) or a raw state dict directly (play_undo()
            passes CurrentGame.state["previous_state"] this way).
        engine_state: The session's own mutable `engine_state` dict,
            typically read straight out of the same `saved` dict/row this
            call is rebuilding from (see `_build_current_game_state()`) —
            passed straight through to `engine_services.bindings_for()`.

    Returns:
        The rebuilt InkRuntimeState, given the same bindings a fresh game
        would get. Bindings are re-derived from story.is_engine_trusted on
        every load and are never part of the saved state; only each
        stateful API's DATA is. A path in saved.state that no longer
        resolves against story.compiled_json degrades per
        `InkRuntimeState.from_dict()` rather than raising.

    Raises:
        session_state.SaveFormatError: The save is from a newer format
            than this server reads. `from_dict()` reads every field with a
            default, so an unrecognised envelope would otherwise load as
            defaulted data rather than an error.
    """
    # A request reaches a handful of the story's knots; building the rest
    # is work thrown away when the request ends.
    root = load_story_root(story.compiled_json, full_build=False)
    list_defs = load_list_defs(story.compiled_json)
    raw_state = session_state.read_saved_state(saved if isinstance(saved, dict) else saved.state)
    return InkRuntimeState.from_dict(root, raw_state, list_defs, engine_bindings=bindings_for(story, engine_state))


def _play_content_context(
    request: WSGIRequest, story: Story, state: InkRuntimeState, *, transcript: list[dict[str, object]] | None = None, can_undo: bool = False
) -> dict[str, object]:
    """Build the template context shared by the play page and its partial.

    **`state.done` alone is NOT "the story ended".** The engine sets it at
    any bare "done"/"end" marker, including mid-turn while choices are
    still pending. The story is over only when `done and not
    current_choices`.

    Args:
        request: The incoming request.
        story: The story being played.
        state: The current InkRuntimeState.
        transcript: The rolling turn history (oldest first), or None
            if the caller has none to show (e.g. a fresh CurrentGame row
            that hasn't been through _build_current_game_state() yet).
        can_undo: Whether a "previous_state" exists to undo back to —
            False for a story's very first turn.

    Returns:
        `session_state.turn_context()`'s own seven keys plus this
        application's "story", "user" and "has_quicksave". "image_urls" resolves every image:/video: tag
        active on this turn to a servable URL, GROUPED by kind; a tag with
        tag the game does not resolve is silently dropped, not surfaced
        as an error, so a work-in-progress story with placeholder tags
        still plays. Each entry in "choices" is a dict, not a pair — a choice
        can carry its own pictures.
    """
    context = session_state.turn_context(
        state,
        resolver=DjangoMediaResolver(story),
        transcript=transcript,
        can_undo=can_undo,
    )
    # This application's own additions, on top of the shared seven: the
    # template needs the story row, the viewer, and whether the sidebar
    # should offer Quickload.
    context["story"] = story
    context["user"] = request.user
    context["has_quicksave"] = has_quicksave(story.slug, saves_in=GameSavesDatabase(user=request.user, story=story))
    return context


def _render_play_content(
    request: WSGIRequest,
    story: Story,
    state: InkRuntimeState,
    *,
    transcript: list[dict[str, object]] | None = None,
    can_undo: bool = False,
    oob: bool = False,
) -> str:
    """Render the play-content partial for a given state.

    Args:
        request: The incoming request.
        story: The story being played.
        state: The current InkRuntimeState.
        transcript: See _play_content_context().
        can_undo: See _play_content_context().
        oob: Mark the partial's own wrapper for an htmx out-of-band swap,
            for a response whose primary target is some other fragment.

    Returns:
        The rendered partial HTML.
    """
    context = _play_content_context(request, story, state, transcript=transcript, can_undo=can_undo)
    context["oob"] = oob
    return render_to_string("interactive_fiction/play_content.jinja", context, request=request, using="Jinja2")


def _build_current_game_state(
    state: InkRuntimeState, previous_raw_state: dict[str, Any] | None, transcript: list[dict[str, object]], engine_state: dict[str, Any]
) -> dict[str, Any]:
    """Build the dict written into CurrentGame.state.

    Args:
        state: The current InkRuntimeState, already advanced to this turn.
        previous_raw_state: The raw dict CurrentGame.state held BEFORE
            this turn was applied, stored verbatim so Undo restores it
            exactly. None for a fresh game.
        transcript: The rolling list of past turns (see
            _append_transcript_entry()), already capped.
        engine_state: The per-API state dict this turn's own
            `bindings_for(story, engine_state)` call mutated. Stored
            verbatim and read back to rebuild the next turn's bindings.

    Returns:
        The dict to store in CurrentGame.state.
    """
    return session_state.build_saved_state(state, previous_raw_state, transcript, engine_state)


def _append_transcript_entry(transcript: list[dict[str, object]], text: str, chosen_label: str | None) -> list[dict[str, object]]:
    """Append one turn to a transcript list, capped at MAX_TRANSCRIPT_TURNS.

    Args:
        transcript: The existing transcript (oldest first).
        text: The text produced by this turn.
        chosen_label: The label of the choice that led to this turn, or
            None for the story's opening turn (no choice preceded it).

    Returns:
        A new list with the entry appended, trimmed to the configured cap
        by dropping the oldest entries first.
    """
    return session_state.append_transcript_entry(transcript, text, chosen_label, cap=settings.MAX_TRANSCRIPT_TURNS)


def _story_play_statuses(user: AbstractUser | AnonymousUser, stories: list[Story]) -> dict[int, str]:
    """Classify each story's play state for the given user.

    Reads straight from CurrentGame.state's JSON rather than reconstructing
    a full InkRuntimeState per story (which would mean loading every
    story's compiled_json + running from_dict() just to check whether it's
    over) — "done" alone is not enough to call a game finished (mirrors
    _play_content_context's own done-and-not-current_choices rule), so both
    keys are read directly out of the stored dict.

    Args:
        user: The requesting user.
        stories: The stories being classified.

    Returns:
        Mapping of story.pk to one of "not_started", "in_progress",
        "finished". Always "not_started" for an anonymous user (no
        CurrentGame rows exist for them).
    """
    if not user.is_authenticated:
        return {story.pk: "not_started" for story in stories}

    games = CurrentGame.objects.filter(user=user, story_id__in=[story.pk for story in stories]).only("story_id", "state")
    statuses = {story.pk: "not_started" for story in stories}
    for game in games:
        finished = bool(game.state.get("done")) and not game.state.get("current_choices")
        statuses[game.story_id] = "finished" if finished else "in_progress"
    return statuses


def _source_gallery_item_sha256(story: Story) -> str | None:
    """Resolve a scanner-ingested story's originating gallery item, if any.

    Lets the play page offer a "View in gallery" link back to the .inkj
    file's own item view (frontend.managers.build_context_info's
    if_story_slug key is the mirror image of this lookup — that one goes
    gallery item -> story, this one goes story -> gallery item).

    Args:
        story: The story being played.

    Returns:
        The originating FileIndex row's unique_sha256, or None for a
        story with no source_fqfn (uploaded via the upload form, not
        scanner-ingested) or whose source file no longer has a live
        FileIndex row (e.g. deleted from disk before the next scan
        tombstones the story).
    """
    if not story.source_fqfn:
        return None
    file_entry = find_game_file_by_path(story.source_fqfn)
    return file_entry.unique_sha256 if file_entry is not None else None


@require_login_if_configured
def library(request: WSGIRequest) -> HttpResponse:
    """Render the (paginated) list of stories the current user may access.

    Args:
        request: The incoming request. GET: "page" (1-indexed, defaults to
            1; out-of-range values clamp to the nearest valid page rather
            than 404ing, matching the gallery listing's own tolerance for
            a stale bookmarked page number).

    Returns:
        A rendered library page listing owned, public, and granted stories
        (public only, for anonymous users), each annotated with its play
        status (not started / continue / finished), and a sidebar
        (mirrors the main gallery's components/sidebar_base.jinja) with
        first/prev/next/last page controls and a page selector — the
        library has no directory tree to navigate, so only pagination and
        a link back to the gallery are needed.
    """
    if request.user.is_authenticated:
        story_qs = Story.objects.filter(Q(owner=request.user) | Q(is_public=True) | Q(grants__user=request.user), is_available=True).distinct()
    else:
        story_qs = Story.objects.filter(is_public=True, is_available=True)
    story_qs = story_qs.defer("compiled_json").order_by("title", "pk")

    per_page = settings.IF_LIBRARY_ITEMS_PER_PAGE
    total_stories = story_qs.count()
    total_pages = max(1, (total_stories + per_page - 1) // per_page)
    try:
        current_page = int(request.GET.get("page", 1))
    except ValueError:
        current_page = 1
    current_page = min(max(current_page, 1), total_pages)

    start = (current_page - 1) * per_page
    stories = list(story_qs[start : start + per_page])

    cover_story_ids = {story.pk for story in stories if story.cover_thumbnail_id}
    play_statuses = _story_play_statuses(request.user, stories)

    context = {
        "stories": stories,
        "cover_story_ids": cover_story_ids,
        "play_statuses": play_statuses,
        "user": request.user,
        "current_page": current_page,
        "total_pages": total_pages,
        "first_url": "?page=1",
        "prev_url": f"?page={current_page - 1}" if current_page > 1 else None,
        "next_url": f"?page={current_page + 1}" if current_page < total_pages else None,
        "last_url": f"?page={total_pages}",
    }
    return render(request, "interactive_fiction/library.jinja", context, using="Jinja2")


@login_required
def play(request: WSGIRequest, slug: str) -> HttpResponse:
    """Load or resume a story's current game (GET) — full page render.

    Starts a fresh InkRuntimeState if the player has no CurrentGame row
    for this story yet; otherwise rehydrates the stored one via
    InkRuntimeState.from_dict() and shows last_turn_text (the text
    produced by the most recent continue_story() call, not a fresh one —
    continue_story() advances the pointer, so it can't be re-called just
    to redisplay a resumed position).

    Args:
        request: The incoming request.
        slug: The story's slug.

    Returns:
        The play page, a redirect to that game's own character-creation
        form (Story.game_new_game_fields non-empty and no CurrentGame
        row exists for this player yet), or a 404-equivalent
        access-denied response.

    Raises:
        Http404: If no accessible Story matches slug (via get_object_or_404).
    """
    story = _get_accessible_story(request, slug)
    if isinstance(story, HttpResponse):
        return story

    # A game that declares plugins is designed around them. Started
    # untrusted it binds nothing and every EXTERNAL falls through to its
    # Ink stub -- it would load and then quietly not work, which is worse
    # than saying so.
    if story.game_required_plugins and not story.is_engine_trusted:
        return render(
            request,
            "interactive_fiction/play_plugins_denied.jinja",
            {"story": story, "user": request.user, "plugin_denied_html": plugin_denied_html(story)},
            using="Jinja2",
            status=409,
        )

    current_game = CurrentGame.objects.filter(user=request.user, story=story).first()
    if current_game is None and story.game_new_game_fields:
        return redirect("if_character_creation", slug=story.slug)
    if current_game is None:
        state, transcript = _start_new_game(request.user, story)
    else:
        try:
            state = _load_game_state(story, current_game, current_game.state.get("engine_state", {}))
        except session_state.SaveFormatError as error:
            return _unreadable_save_response(request, story, error)
        transcript = current_game.state.get("transcript", [])

    user_prefs, _created = UserPreferences.objects.get_or_create(user=request.user)
    context = _play_content_context(
        request, story, state, transcript=transcript, can_undo=bool(current_game and current_game.state.get("previous_state"))
    )
    context["if_font_size"] = user_prefs.if_font_size
    context["if_text_width"] = user_prefs.if_text_width
    context["gallery_item_sha256"] = _source_gallery_item_sha256(story)
    # A game picks one of the engine's own play layouts in its manifest
    # (PLAY_LAYOUT); a story that names none gets the classic single-column
    # page, exactly as before layouts existed.
    layout = play_layout_for(story)
    # A layout with a side panel needs the game to fill it. A game that
    # supplies none simply renders empty sections rather than erroring, so
    # the two choices stay independent of each other.
    panel = game_panel_context(story, current_game.state.get("engine_state", {}) if current_game else {}, state.globals)
    if panel is not None:
        context.update(panel)

    return render(request, layout, context, using="Jinja2")


@login_required
@require_POST
def play_submit(request: WSGIRequest, slug: str) -> HttpResponse:
    """Submit a choice and advance the story by one turn (HTMX partial).

    Enforces the concurrent-tab guard described in the plan: the POST
    must include the turn_count the submitting tab last rendered
    ("turn_count" form field). If it no longer matches the stored row's
    turn_count — another tab already moved the story on — the choice is
    rejected with a "story has moved on" partial instead of being
    silently applied on top of state the tab never actually saw. The
    whole read-check-write sequence runs inside one transaction with a
    row lock (select_for_update) so two concurrent submissions can't both
    pass the guard check against the same stale row.

    Args:
        request: The incoming request. POST body: "choice" (int index
            into current_choices) and "turn_count" (int, the turn the
            submitting tab last rendered).
        slug: The story's slug.

    Returns:
        The rendered play-content partial for the new turn, a 409
        Conflict partial if the concurrent-tab guard rejects the
        submission, or a plain error response for a malformed/out-of
        -range choice.

    Raises:
        Http404: If no accessible Story matches slug.
    """
    story = _get_accessible_story(request, slug)
    if isinstance(story, HttpResponse):
        return story

    try:
        choice_index = int(request.POST["choice"])
        submitted_turn_count = int(request.POST["turn_count"])
    except (KeyError, ValueError):
        return HttpResponse(status=400)

    with transaction.atomic():
        turn = _current_game_for_turn(request, story, submitted_turn_count)
        if isinstance(turn, HttpResponse):
            return turn
        current_game, engine_state, state = turn
        previous_raw_state = current_game.state

        if choice_index < 0 or choice_index >= len(state.current_choices):
            return HttpResponse(status=400)
        chosen_label = state.current_choices[choice_index].text
        state.choose(choice_index)
        state.continue_story()

        transcript = _append_transcript_entry(previous_raw_state.get("transcript", []), state.last_turn_text, chosen_label)
        current_game.state = _build_current_game_state(state, previous_raw_state=previous_raw_state, transcript=transcript, engine_state=engine_state)
        current_game.turn_count = state.turn_count
        current_game.save(update_fields=["state", "turn_count", "updated_at"])

    return HttpResponse(_render_play_content(request, story, state, transcript=transcript, can_undo=True))


@login_required
@require_POST
def play_undo(request: WSGIRequest, slug: str) -> HttpResponse:
    """Undo the last choice, restoring CurrentGame to its previous turn.

    One level only — the restored row's own "previous_state" (whatever it
    held before *that* turn) becomes the new undo target, so a second
    consecutive undo continues walking backward one turn at a time rather
    than jumping straight back to the start; there is no bounded history
    stack. A game with no previous_state (the very first turn) has nothing
    to undo, so the request is rejected with 400 rather than silently
    doing nothing.

    Args:
        request: The incoming request.
        slug: The story's slug.

    Returns:
        The rendered play-content partial for the restored turn, or 400 if
        there is nothing to undo.

    Raises:
        Http404: If no accessible Story or CurrentGame exists.
    """
    story = _get_accessible_story(request, slug)
    if isinstance(story, HttpResponse):
        return story

    with transaction.atomic():
        current_game = get_object_or_404(CurrentGame.objects.select_for_update(), user=request.user, story=story)
        previous_raw_state = current_game.state.get("previous_state")
        if not previous_raw_state:
            return HttpResponse(status=400)

        # Deep-copied for the same reason as play_submit() above: this
        # dict is about to become the new current_game.state verbatim, so
        # nothing built from it (bindings_for()'s stateful closures) may
        # mutate the very dict being restored.
        try:
            state = _load_game_state(story, previous_raw_state, copy.deepcopy(previous_raw_state.get("engine_state", {})))
        except session_state.SaveFormatError as error:
            return _unreadable_save_response(request, story, error)
        current_game.state = previous_raw_state
        current_game.turn_count = state.turn_count
        current_game.save(update_fields=["state", "turn_count", "updated_at"])

    return HttpResponse(
        _render_play_content(
            request, story, state, transcript=previous_raw_state.get("transcript", []), can_undo=bool(previous_raw_state.get("previous_state"))
        )
    )


@login_required
@require_POST
def play_restart(request: WSGIRequest, slug: str) -> HttpResponse:
    """Reset CurrentGame to the story's start, discarding in-flight progress.

    Named SaveState slots are untouched — restart only ever affects the
    single per-(user, story) CurrentGame row, matching the plan's "named
    slots are untouched" requirement. Requires an explicit POST (not a
    plain GET link) so a restart can't happen from an accidental page
    fetch/prefetch.

    Args:
        request: The incoming request.
        slug: The story's slug.

    Returns:
        The rendered play-content partial for the story's fresh opening
        turn, or (Story.game_new_game_fields non-empty) an HTMX redirect
        to that game's own character-creation form instead — a restart
        is a genuine fresh start, so it re-asks the same questions
        play()'s own first-visit branch would.

    Raises:
        Http404: If no accessible Story matches slug.
    """
    story = _get_accessible_story(request, slug)
    if isinstance(story, HttpResponse):
        return story

    if story.game_new_game_fields:
        CurrentGame.objects.filter(user=request.user, story=story).delete()
        response = HttpResponse(status=204)
        response["HX-Redirect"] = reverse("if_character_creation", args=[story.slug])
        return response

    state, transcript = _start_new_game(request.user, story)
    return HttpResponse(_render_play_content(request, story, state, transcript=transcript, can_undo=False))


@login_required
def preferences(request: WSGIRequest) -> HttpResponse:
    """View/edit the current user's Interactive Fiction reader display preferences.

    Extends the existing per-user UserPreferences mechanism
    (user_preferences/models.py) with two IF-specific fields
    (if_font_size, if_text_width) rather than inventing an IF-local
    preferences model — get_or_create() covers a user whose row predates
    this step's migration, matching user_preferences/views.py's own
    defensive pattern (the auto-create signal handles new users going
    forward, but existing rows were created before these fields existed).

    Args:
        request: The incoming request. POST: "if_font_size",
            "if_text_width" (each one of the model field's declared
            choices).

    Returns:
        The preferences form (GET, or POST with an invalid choice); a
        redirect back to the same page on success.
    """
    user_prefs, _created = UserPreferences.objects.get_or_create(user=request.user)

    if request.method == "POST":
        font_size = request.POST.get("if_font_size", "")
        text_width = request.POST.get("if_text_width", "")
        if font_size in _VALID_IF_FONT_SIZES and text_width in _VALID_IF_TEXT_WIDTHS:
            user_prefs.if_font_size = font_size
            user_prefs.if_text_width = text_width
            user_prefs.save(update_fields=["if_font_size", "if_text_width"])
            return redirect("if_preferences")

    return render(request, "interactive_fiction/preferences.jinja", {"preferences": user_prefs, "user": request.user}, using="Jinja2")

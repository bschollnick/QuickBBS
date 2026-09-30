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
layered on top of InkRuntimeState's own serialized fields by
`session_state.build_saved_state()`.

Sibling modules hold the rest of the app's views: story_views.py
(upload/authoring), save_views.py (named save slots), panel_views.py (a
game's side panel). The shared engine-state helpers they import stay here.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from dataclasses import dataclass
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
    Container,
    InkRuntimeState,
    StoryRuntimeError,
    load_list_defs,
    load_story_root,
    start_new_story,
)
from ink_engine.game_panel import (
    choices_beside_panel,
    fill_action_sections,
    fill_followers_sections,
)
from ink_engine.plugin import ListDefs
from interactive_fiction.engine_services import (
    binding_sandbox_for,
    game_panel_context,
    play_layout_for,
    plugin_denied_html,
)
from interactive_fiction.game_saves_database import GameSavesDatabase
from interactive_fiction.images import DjangoMediaResolver
from interactive_fiction.ingestion import find_game_file_by_path
from interactive_fiction.models import (
    LAYOUTS_WITH_PANEL,
    CurrentGame,
    SaveState,
    Story,
    user_can_access,
)
from quickbbs.common import require_login_if_configured
from quickbbs.request_types import signed_in_user
from user_preferences.models import UserPreferences

logger = logging.getLogger(__name__)

# Mirrors UserPreferences.if_font_size/if_text_width's own `choices=`
# (user_preferences/models.py) — kept as plain sets rather than reflecting
# via UserPreferences._meta.get_field(...).choices, since Field.choices is
# typed Optional on the Django stubs (always non-None here, but mypy can't
# know that), and the model's choices rarely change without touching this
# view anyway.
_VALID_IF_FONT_SIZES = {"small", "medium", "large"}

#: Where a player's last character-creation answers are kept, per story
#: slug, so the form can show them again after a restart.
_NEW_GAME_ANSWERS_SESSION_KEY = "if_new_game_answers"
_VALID_IF_TEXT_WIDTHS = {"narrow", "medium", "wide"}

if TYPE_CHECKING:
    from django.contrib.auth.models import _AnyUser, _User


def _compiled_story(story: Story) -> tuple[Container, ListDefs]:
    """Load a story's root container and LIST definitions.

    The root is built lazily: a request reaches a handful of the story's
    knots, and building the rest is work thrown away when it ends.
    """
    return load_story_root(story.compiled_json, full_build=False), load_list_defs(story.compiled_json)


def _new_game_state(story: Story, engine_state: dict[str, Any], initial_globals: dict[str, Any] | None = None) -> InkRuntimeState:
    """Build a fresh InkRuntimeState for a story, run to its first stop point.

    Args:
        story: The story to start.
        engine_state: The session's own mutable `engine_state` dict — passed straight through to
            `engine_services.binding_sandbox_for()`, and mutated in place by any
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
    root, list_defs = _compiled_story(story)
    return start_new_story(
        root,
        list_defs,
        engine_bindings=binding_sandbox_for(story, engine_state),
        initial_globals=initial_globals,
    )


def _start_new_game(user: _User, story: Story, initial_globals: dict[str, Any] | None = None) -> tuple[InkRuntimeState, dict[str, Any]]:
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
        `(state, saved)` — the new game's `InkRuntimeState`, advanced to
        its first stop point, and the state written to its CurrentGame row.
    """
    engine_state: dict[str, Any] = {}
    state = _new_game_state(story, engine_state, initial_globals=initial_globals)
    transcript = _append_transcript_entry([], state.last_turn_text, chosen_label=None)
    saved = session_state.build_saved_state(state, None, transcript, engine_state)
    CurrentGame.objects.update_or_create(user=user, story=story, defaults={"state": saved, "turn_count": state.turn_count})
    return state, saved


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
        The character-creation form page, pre-filled with this player's
        last answers for the story when this session has them (after a
        restart). Nothing is submitted on the player's behalf.

    Raises:
        Http404: If no accessible Story matches slug.
    """
    story = _get_accessible_story(request, slug)
    if isinstance(story, HttpResponse):
        return story
    previous_answers = request.session.get(_NEW_GAME_ANSWERS_SESSION_KEY, {}).get(story.slug)
    context = {"story": story, "user": request.user, "previous_answers": previous_answers}
    return render(request, "interactive_fiction/character_creation.jinja", context, using="Jinja2")


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
    user = signed_in_user(request)
    if CurrentGame.objects.filter(user=user, story=story).exists():
        return redirect("if_play", slug=story.slug)

    # A bare, binding-less state to read the story's own real starting
    # global values from (no EXTERNAL calls fire, no continue_story() —
    # constructing InkRuntimeState only runs its global-decl container),
    # so an "add_to" checkbox field can add to the ACTUAL declared
    # default rather than guessing 0.
    base_globals = InkRuntimeState(*_compiled_story(story)).globals
    initial_globals = answers_to_globals(story.game_new_game_fields, request.POST, story_defaults=base_globals)
    try:
        _start_new_game(user, story, initial_globals=initial_globals)
    except StoryRuntimeError as error:
        return _story_error_response(request, story, error)
    # A checkbox left clear submits nothing, so it is stored as absent.
    answers = {field["var"]: request.POST[field["var"]] for field in story.game_new_game_fields if field["var"] in request.POST}
    request.session[_NEW_GAME_ANSWERS_SESSION_KEY] = {**request.session.get(_NEW_GAME_ANSWERS_SESSION_KEY, {}), story.slug: answers}
    return redirect("if_play", slug=story.slug)


def _stale_turn_response(request: WSGIRequest, story: Story) -> HttpResponse:
    """Render the concurrent-tab guard's 409 partial.

    What a tab sees when `_play_turn()` refuses its submission because
    the row has moved on under it.

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


def _story_error_response(request: WSGIRequest, story: Story, error: StoryRuntimeError) -> HttpResponse:
    """Render the partial for a turn the story stopped with an Ink runtime error.

    Status 200 for an htmx request, which swaps only a 2xx response into
    the page; 500 for a full page load.

    Args:
        request: The incoming request.
        story: The story that stopped.
        error: The engine's error, whose message names where and why.

    Returns:
        The rendered play_story_error.jinja partial.
    """
    logger.error("interactive_fiction.views: story %r stopped with a runtime error: %s", story, error)
    return HttpResponse(
        render_to_string(
            "interactive_fiction/play_story_error.jinja",
            {"story": story, "user": request.user, "reason": str(error)},
            request=request,
            using="Jinja2",
        ),
        status=200 if request.headers.get("HX-Request") == "true" else 500,
    )


@dataclass(slots=True)
class _Turn:
    """One turn in progress on a locked CurrentGame row.

    Attributes:
        current_game: The row, locked for the rest of the transaction.
        engine_state: A deep copy of the row's engine state, which the
            rebuilt bindings mutate in place.
        state: The story rebuilt over `engine_state`.
        previous_raw_state: The row's state before this turn, stored
            verbatim as the undo target.
        transcript: The transcript to save; a step that narrates appends to it.
    """

    current_game: CurrentGame
    engine_state: dict[str, Any]
    state: InkRuntimeState
    previous_raw_state: dict[str, Any]
    transcript: list[dict[str, object]]


def _play_turn[T](request: WSGIRequest, story: Story, step: Callable[[_Turn], T | HttpResponse]) -> tuple[_Turn, T] | HttpResponse:
    """Run one guarded turn: lock the row, check the tab is current, rebuild, `step`, save.

    Shared by every view that changes the story from a tab (`play_submit`,
    `panel_views.play_panel_command`). The POST's "turn_count" is the
    concurrent-tab guard: a tab whose count no longer matches the row is
    refused rather than applied on top of state it never saw. The whole
    sequence is one transaction holding the row lock.

    Args:
        request: The incoming POST, carrying "turn_count".
        story: The story being played.
        step: Changes `turn.state` (and `turn.transcript`, if it narrates),
            returning a value for the caller, or an `HttpResponse` to
            refuse the turn without saving.

    Returns:
        `(turn, step's value)` once saved, or the response to send instead:
        400 for a missing or malformed "turn_count", the 409 stale-tab or
        unreadable-save partial, the story-error partial when the turn
        raises `StoryRuntimeError` (nothing is saved), or `step`'s own
        refusal.

    Raises:
        Http404: The player has no game of this story.
    """
    try:
        submitted_turn_count = int(request.POST["turn_count"])
    except (KeyError, ValueError):
        return HttpResponse(status=400)

    with transaction.atomic():
        current_game = get_object_or_404(CurrentGame.objects.select_for_update(), user=signed_in_user(request), story=story)
        if current_game.turn_count != submitted_turn_count:
            return _stale_turn_response(request, story)
        previous_raw_state = current_game.state
        # A copy: the bindings mutate it as the turn plays, and the row's
        # own state must stay as it was so undo can restore it verbatim.
        engine_state = copy.deepcopy(previous_raw_state.get("engine_state", {}))
        try:
            state = _load_game_state(story, previous_raw_state, engine_state)
        except session_state.SaveFormatError as error:
            return _unreadable_save_response(request, story, error)

        turn = _Turn(current_game, engine_state, state, previous_raw_state, previous_raw_state.get("transcript", []))
        try:
            result = step(turn)
        except StoryRuntimeError as error:
            # Nothing is saved, so the row keeps the turn before the error.
            return _story_error_response(request, story, error)
        if isinstance(result, HttpResponse):
            return result
        saved = session_state.build_saved_state(turn.state, previous_raw_state, turn.transcript, engine_state)
        _save_current_game(current_game, saved, turn.state.turn_count)
    return turn, result


def _save_current_game(current_game: CurrentGame, saved_state: dict[str, Any], turn_count: int) -> None:
    """Write a new state and its turn count onto a CurrentGame row."""
    current_game.state = saved_state
    current_game.turn_count = turn_count
    current_game.save(update_fields=["state", "turn_count", "updated_at"])


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
            call is rebuilding from — passed straight through to
            `engine_services.binding_sandbox_for()`.

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
    root, list_defs = _compiled_story(story)
    raw_state = session_state.read_saved_state(saved if isinstance(saved, dict) else saved.state)
    return InkRuntimeState.from_dict(root, raw_state, list_defs, engine_bindings=binding_sandbox_for(story, engine_state))


def _play_content_context(request: WSGIRequest, story: Story, state: InkRuntimeState, saved: dict[str, Any]) -> dict[str, object]:
    """Build the template context shared by the play page and its partial.

    **`state.done` alone is NOT "the story ended".** The engine sets it at
    any bare "done"/"end" marker, including mid-turn while choices are
    still pending. The story is over only when `done and not
    current_choices`.

    Args:
        request: The incoming request.
        story: The story being played.
        state: The current InkRuntimeState.
        saved: The game's saved state, as `CurrentGame.state` holds it: its
            "transcript" is shown, and Undo is offered when it has a
            "previous_state".

    Returns:
        `session_state.turn_context()`'s own seven keys plus this
        application's "story", "user", "has_quicksave" and
        "has_game_panel", and the game's own panel keys when its layout
        draws a panel. While that panel draws a compass, "choices" leaves
        out the story's movement choice. "image_urls"
        resolves every image:/video: tag active on this turn to a servable
        URL, grouped by kind; a tag the game does not resolve is dropped,
        so a work-in-progress story with placeholder tags still plays.
        Each entry in "choices" is a dict, since a choice can carry its
        own pictures.
    """
    context = session_state.turn_context(
        state,
        resolver=DjangoMediaResolver(story),
        transcript=saved.get("transcript", []),
        can_undo=bool(saved.get("previous_state")),
    )
    # This application's own additions, on top of the shared seven: the
    # template needs the story row, the viewer, and whether the sidebar
    # should offer Quickload.
    context["story"] = story
    context["user"] = request.user
    context["has_quicksave"] = has_quicksave(story.slug, saves_in=GameSavesDatabase(user=signed_in_user(request), story=story))
    panel = _game_panel_context(story, saved, state)
    context["has_game_panel"] = panel is not None
    if panel:
        context.update(panel)
    context["choices"] = choices_beside_panel(context["choices"], panel)
    return context


def _game_panel_context(story: Story, saved: dict[str, Any], state: InkRuntimeState) -> dict[str, Any] | None:
    """Return the game's side-panel data, `{}` if it supplies none, or None when the story's layout draws no panel.

    Action and followers sections come back listed for `state`, with
    their images resolved.
    """
    if play_layout_for(story) not in LAYOUTS_WITH_PANEL:
        return None
    panel = game_panel_context(story, saved.get("engine_state", {}), state.globals)
    resolver = DjangoMediaResolver(story)
    panel = fill_action_sections(panel, state, resolver=resolver)
    panel = fill_followers_sections(panel, state, resolver=resolver)
    return panel or {}


def _render_play_content(
    request: WSGIRequest, story: Story, state: InkRuntimeState, saved: dict[str, Any], *, command_result: str | None = None
) -> str:
    """Render the play-content partial for a given state, plus the game's panel.

    Every turn's response goes through here, so a layout that draws a panel
    gets it refreshed out of band on every turn (`play_panel.jinja` marks
    its own wrapper `hx-swap-oob`).

    Args:
        request: The incoming request.
        story: The story being played.
        state: The current InkRuntimeState.
        saved: See `_play_content_context()`.
        command_result: A panel command's answer. When given, the story
            partial is marked for an out-of-band swap (the response's target
            is the command's own form) and the text goes in the panel's
            detail area; otherwise the panel keeps whatever detail the
            game's panel data supplies.

    Returns:
        The rendered partial HTML, followed by the panel fragment when the
        story's layout draws one.
    """
    context = _play_content_context(request, story, state, saved)
    context["oob"] = command_result is not None
    html = render_to_string("interactive_fiction/play_content.jinja", context, request=request, using="Jinja2")
    if context["has_game_panel"]:
        if command_result is not None:
            context["panel_detail"] = command_result
        html += render_to_string("interactive_fiction/play_panel.jinja", context, request=request, using="Jinja2")
    return html


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


def _story_play_statuses(user: _AnyUser, stories: list[Story]) -> dict[int, str]:
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

    user = signed_in_user(request)
    current_game = CurrentGame.objects.filter(user=user, story=story).first()
    if current_game is None and story.game_new_game_fields:
        return redirect("if_character_creation", slug=story.slug)
    if current_game is None:
        try:
            state, saved = _start_new_game(user, story)
        except StoryRuntimeError as error:
            return _story_error_response(request, story, error)
    else:
        try:
            state = _load_game_state(story, current_game, current_game.state.get("engine_state", {}))
        except session_state.SaveFormatError as error:
            return _unreadable_save_response(request, story, error)
        saved = current_game.state

    user_prefs, _created = UserPreferences.objects.get_or_create(user=user)
    context = _play_content_context(request, story, state, saved)
    context["if_font_size"] = user_prefs.if_font_size
    context["if_text_width"] = user_prefs.if_text_width
    context["gallery_item_sha256"] = _source_gallery_item_sha256(story)
    # A game picks one of the engine's own play layouts in its manifest
    # (PLAY_LAYOUT); a story that names none gets the classic single-column
    # page, exactly as before layouts existed.
    # The game's panel data, if its layout draws one, is already in context
    # (`_play_content_context()`); a game that supplies none gets empty sections.
    return render(request, play_layout_for(story), context, using="Jinja2")


@login_required
@require_POST
def play_submit(request: WSGIRequest, slug: str) -> HttpResponse:
    """Submit a choice and advance the story by one turn (HTMX partial).

    Played through `_play_turn()`, which enforces the concurrent-tab guard.

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
    except (KeyError, ValueError):
        return HttpResponse(status=400)

    def choose(turn: _Turn) -> HttpResponse | None:
        if not 0 <= choice_index < len(turn.state.current_choices):
            return HttpResponse(status=400)
        chosen_label = turn.state.current_choices[choice_index].text
        turn.state.choose(choice_index)
        turn.state.continue_story()
        turn.transcript = _append_transcript_entry(turn.transcript, turn.state.last_turn_text, chosen_label)
        return None

    played = _play_turn(request, story, choose)
    if isinstance(played, HttpResponse):
        return played
    turn, _ = played
    return HttpResponse(_render_play_content(request, story, turn.state, turn.current_game.state))


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
        current_game = get_object_or_404(CurrentGame.objects.select_for_update(), user=signed_in_user(request), story=story)
        previous_raw_state = current_game.state.get("previous_state")
        if not previous_raw_state:
            return HttpResponse(status=400)

        # Deep-copied for the same reason as in `_play_turn()`: this dict
        # becomes the row's state verbatim, so the bindings must not mutate it.
        try:
            state = _load_game_state(story, previous_raw_state, copy.deepcopy(previous_raw_state.get("engine_state", {})))
        except session_state.SaveFormatError as error:
            return _unreadable_save_response(request, story, error)
        _save_current_game(current_game, previous_raw_state, state.turn_count)

    return HttpResponse(_render_play_content(request, story, state, previous_raw_state))


@login_required
@require_POST
def play_restart(request: WSGIRequest, slug: str) -> HttpResponse:
    """Reset CurrentGame to the story's start, discarding in-flight progress.

    Named SaveState slots are untouched: restart affects only the one
    per-(user, story) CurrentGame row. POST-only, so an accidental page
    fetch or prefetch cannot restart a game.

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

    user = signed_in_user(request)
    if story.game_new_game_fields:
        CurrentGame.objects.filter(user=user, story=story).delete()
        response = HttpResponse(status=204)
        response["HX-Redirect"] = reverse("if_character_creation", args=[story.slug])
        return response

    try:
        state, saved = _start_new_game(user, story)
    except StoryRuntimeError as error:
        return _story_error_response(request, story, error)
    return HttpResponse(_render_play_content(request, story, state, saved))


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
    user_prefs, _created = UserPreferences.objects.get_or_create(user=signed_in_user(request))

    if request.method == "POST":
        font_size = request.POST.get("if_font_size", "")
        text_width = request.POST.get("if_text_width", "")
        if font_size in _VALID_IF_FONT_SIZES and text_width in _VALID_IF_TEXT_WIDTHS:
            user_prefs.if_font_size = font_size
            user_prefs.if_text_width = text_width
            user_prefs.save(update_fields=["if_font_size", "if_text_width"])
            return redirect("if_preferences")

    return render(request, "interactive_fiction/preferences.jinja", {"preferences": user_prefs, "user": request.user}, using="Jinja2")

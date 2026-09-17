"""Game side-panel views for the interactive_fiction app.

play_panel_tab()/play_panel_action() are the read-only panel routes (a tab
switch, an Examine); play_panel_command() is the write-capable one (Use,
Cast).
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST

from interactive_fiction.engine_services import (
    game_panel_action,
    game_panel_command,
    game_panel_context,
)
from interactive_fiction.models import CurrentGame
from interactive_fiction.views import (
    _build_current_game_state,
    _current_game_for_turn,
    _get_accessible_story,
    _render_play_content,
)


@login_required
@require_GET
def play_panel_tab(request: WSGIRequest, slug: str, tab_id: str) -> HttpResponse:
    """Re-render a game panel with a different tab showing.

    Switching tabs is pure presentation: the same panel data, drawn with a
    different face selected. It reads no more state than rendering the play
    page does and writes none at all, so it stays a GET and never touches
    the turn loop.

    The template has always issued this request (`play_panel.jinja`'s tab
    buttons target `panel/<tab>/`); the route was simply missing, so every
    tab click answered 404 and the panel's other faces were unreachable.

    Args:
        request: The incoming request.
        slug: The story's slug.
        tab_id: Which of the panel's own tabs to show. A game names these;
            an id the game does not offer falls back to its default face
            rather than erroring.

    Returns:
        The panel fragment, or an empty one for a story with no panel.
        403 if the user may not read this story.

    Raises:
        Http404: If no accessible Story exists.
    """
    story = _get_accessible_story(request, slug)
    if isinstance(story, HttpResponse):
        return story

    current_game = CurrentGame.objects.filter(user=request.user, story=story).first()
    engine_state = current_game.state.get("engine_state", {}) if current_game else {}
    globals_ = current_game.state.get("globals", {}) if current_game else {}
    panel = game_panel_context(story, engine_state, globals_)
    if panel is None:
        return HttpResponse("")

    # The game decides which tabs exist; honour the request only when it
    # names one of them, so a hand-typed id cannot select a face the game
    # never offered.
    if any(tab.get("id") == tab_id for tab in panel.get("panel_tabs", [])):
        panel["panel_active_tab"] = tab_id
        # A game that renders different content per face supplies
        # `panel_sections_by_tab`; one that does not simply keeps the same
        # sections under every tab, exactly as it did before tabs worked.
        by_tab = panel.get("panel_sections_by_tab") or {}
        if tab_id in by_tab:
            panel["panel_sections"] = by_tab[tab_id]
    # A "command" row action's form needs the same turn_count guard token
    # play_submit's own choice form carries, so a tab switch must thread it
    # through exactly like play()'s full page render does.
    context = {"story": story, "turn_count": current_game.turn_count if current_game else -1}
    context.update(panel)
    return HttpResponse(render_to_string("interactive_fiction/play_panel.jinja", context, request=request, using="Jinja2"))


@login_required
@require_GET
def play_panel_action(request: WSGIRequest, slug: str, action_id: str, target_id: str) -> HttpResponse:
    """Run one of a game panel's own row actions and render its answer.

    A panel action is NOT a story action: it answers in the panel and
    leaves the scene exactly where it was. Examining a carried item is the
    motivating case — the original renders an item's description into its
    sidebar without advancing anything (`items.js:1196`) — so this view is
    deliberately read-only: it never touches CurrentGame, never advances a
    turn, and never writes engine_state.

    Anything that genuinely changes the world (using an item, casting a
    spell) goes through `play_panel_command` instead, which gets the same
    real EXTERNAL bindings a story choice does, plus the concurrent-tab
    guard and an undo snapshot.

    Args:
        request: The incoming request.
        slug: The story's slug.
        action_id: Which action the row offered (the game names these).
        target_id: What the action was invoked on.

    Returns:
        An HTML fragment for the panel's detail area, or 403/404 as usual.
        A story with no panel, an action the game does not answer, or an
        unknown target all yield an empty fragment rather than an error —
        a panel must never be able to break the page it lives on.

    Raises:
        Http404: If no accessible Story exists.
    """
    story = _get_accessible_story(request, slug)
    if isinstance(story, HttpResponse):
        return story

    current_game = CurrentGame.objects.filter(user=request.user, story=story).first()
    if current_game is None:
        return HttpResponse("")

    text = game_panel_action(story, current_game.state.get("engine_state", {}), current_game.state.get("globals", {}), action_id, target_id)
    if not text:
        return HttpResponse("")
    return render(request, "interactive_fiction/play_panel_detail.jinja", {"detail_text": text}, using="Jinja2")


@login_required
@require_POST
def play_panel_command(request: WSGIRequest, slug: str, command_id: str, target_id: str) -> HttpResponse:
    """Run one of a game panel's turn-advancing commands (Use/Cast/Give/Drop).

    Unlike `play_panel_action`, this genuinely changes the world: it calls
    `engine_services.game_panel_command`, which hands the game's
    `sidebar.panel_command()` the exact same real bindings
    (`bindings_for(story, engine_state)`) an in-story choice gets, so
    `give_item_now`, `spend_item_use_now`, or any other stateful API's
    binding runs for real. It does NOT call `InkRuntimeState.continue_story()`
    or advance Ink's own `turn_count` — a panel command is not a story
    choice, and faking one would desync `TURNS_SINCE()`/visit-count
    semantics from the player's real position in the story. What it DOES
    give the same guarantees as a story turn: the concurrent-tab guard
    (rejecting a submission from a tab that is not looking at the current
    state), one atomic read-check-write transaction, and an undo snapshot
    so a bad Use can be undone via the existing `play_undo` — the "turn
    loop... still applies" the read-only `play_panel_action` docstring
    points here for.

    Args:
        request: The incoming request. POST body: "turn_count" (int, the
            turn_count the submitting tab last rendered — the same
            concurrent-tab token `play_submit` uses).
        slug: The story's slug.
        command_id: Which command the row offered (the game names these).
        target_id: What the command was invoked on.

    Returns:
        The panel's detail fragment plus an OOB-refreshed panel (so item
        counts/rows reflect the write immediately), a 409 Conflict partial
        if the concurrent-tab guard rejects the submission, or an empty
        fragment for a story with no panel, or a command/target the game
        does not answer.

    Raises:
        Http404: If no accessible Story matches slug.
    """
    story = _get_accessible_story(request, slug)
    if isinstance(story, HttpResponse):
        return story

    try:
        submitted_turn_count = int(request.POST["turn_count"])
    except (KeyError, ValueError):
        return HttpResponse(status=400)

    with transaction.atomic():
        turn = _current_game_for_turn(request, story, submitted_turn_count)
        if isinstance(turn, HttpResponse):
            return turn
        current_game, engine_state, state = turn
        previous_raw_state = current_game.state

        text = game_panel_command(story, engine_state, state.globals, command_id, target_id)
        # A command can unlock a story choice -- giving an item, learning a
        # spell -- and this turn's choices were evaluated before it ran.
        # Source redisplays the whole place for exactly this (`items.js:1261`,
        # `dispPlace()` on a command answering "refresh").
        state.refresh_choices()

        transcript = previous_raw_state.get("transcript", [])
        current_game.state = _build_current_game_state(state, previous_raw_state=previous_raw_state, transcript=transcript, engine_state=engine_state)
        current_game.save(update_fields=["state", "updated_at"])

    # The full panel re-render (its own OOB wrapper, see play_panel.jinja)
    # carries the detail text too — #if-panel-detail is part of that same
    # markup — so one OOB fragment updates the whole panel, item rows and
    # result message together, with no separate detail swap needed.
    panel = game_panel_context(story, engine_state, state.globals)
    panel_context_dict: dict[str, Any] = {"story": story, "turn_count": current_game.turn_count, "panel_detail": text}
    if panel is not None:
        panel_context_dict.update(panel)
        # Re-assert: this command's own result text must win even if the
        # game's own panel dict happens to carry its own "panel_detail" key.
        panel_context_dict["panel_detail"] = text

    # The refreshed choices live in the story column, not the panel, so the
    # response carries both fragments, each OOB-swapped by its own wrapper.
    # Without the second, a command that unlocks a choice updates the panel
    # and leaves the choice list showing what was true before it ran.
    return HttpResponse(
        render_to_string("interactive_fiction/play_panel.jinja", panel_context_dict, request=request, using="Jinja2")
        + _render_play_content(request, story, state, transcript=transcript, can_undo=bool(previous_raw_state.get("previous_state")), oob=True)
    )

"""Game side-panel views for the interactive_fiction app.

play_panel_tab()/play_panel_action() are the read-only panel routes (a tab
switch, an Examine); play_panel_command() is the write-capable one (Use,
Cast), play_take_exit() moves the story through an exit on the panel's
compass, and play_take_action() runs a story action from an action or a
followers section as an interlude -- both fill the same way, and
`find_action()` reads either.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST
from if_session import session_state

from ink_engine.engine import InterludeError
from ink_engine.game_panel import (
    action_sections,
    fill_action_sections,
    fill_followers_sections,
    find_action,
    find_exit,
    followers_sections,
    play_reaction,
)
from ink_engine.travel import take_exit
from interactive_fiction.engine_services import (
    game_panel_action,
    game_panel_command_result,
    game_panel_context,
)
from interactive_fiction.images import DjangoMediaResolver
from interactive_fiction.models import CurrentGame
from interactive_fiction.views import (
    _append_transcript_entry,
    _get_accessible_story,
    _load_game_state,
    _play_turn,
    _render_play_content,
    _Turn,
)
from quickbbs.request_types import signed_in_user


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

    current_game = CurrentGame.objects.filter(user=signed_in_user(request), story=story).first()
    engine_state = current_game.state.get("engine_state", {}) if current_game else {}
    globals_ = current_game.state.get("globals", {}) if current_game else {}
    panel = game_panel_context(story, engine_state, globals_)
    if panel is None:
        return HttpResponse("")
    if current_game is not None and (action_sections(panel) or followers_sections(panel)):
        # Listing an action or followers section evaluates story content, so it needs the story itself.
        try:
            state = _load_game_state(story, current_game, engine_state)
        except session_state.SaveFormatError:
            state = None
        if state is not None:
            resolver = DjangoMediaResolver(story)
            panel = fill_action_sections(panel, state, resolver=resolver) or panel
            panel = fill_followers_sections(panel, state, resolver=resolver) or panel

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

    current_game = CurrentGame.objects.filter(user=signed_in_user(request), story=story).first()
    if current_game is None:
        return HttpResponse("")

    text = game_panel_action(story, current_game.state.get("engine_state", {}), current_game.state.get("globals", {}), action_id, target_id)
    if not text:
        return HttpResponse("")
    return render(request, "interactive_fiction/play_panel_detail.jinja", {"detail_text": text}, using="Jinja2")


@login_required
@require_POST
def play_panel_command(request: WSGIRequest, slug: str, command_id: str, target_id: str) -> HttpResponse:
    """Run one of a game panel's state-changing commands (Use/Cast/Give/Drop).

    Unlike `play_panel_action`, this genuinely changes the world: it calls
    `engine_services.game_panel_command_result`, which hands the game's
    `sidebar.panel_command()` the exact same real bindings
    (`bindings_for(story, engine_state)`) an in-story choice gets, so
    `give_item_now`, `spend_item_use_now`, or any other stateful API's
    binding runs for real. A command answering a message only does not
    advance the story. A command answering a knot has it played as the
    command's reaction (`ink_engine.game_panel.play_reaction()`): a real
    story turn, recorded in the transcript under the answer's label. Either
    way the view gives the same guarantees as a story turn: the concurrent-tab guard
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
        InkPathError: The command's answer names a knot the story does
            not have -- a fault in the game, not the request. The
            transaction rolls back.
    """
    story = _get_accessible_story(request, slug)
    if isinstance(story, HttpResponse):
        return story

    def run_command(turn: _Turn) -> str:
        result = game_panel_command_result(story, turn.engine_state, turn.state.globals, command_id, target_id)
        if play_reaction(turn.state, result) is not None:
            turn.transcript = _append_transcript_entry(turn.transcript, turn.state.last_turn_text, result.label)
        return result.message

    played = _play_turn(request, story, run_command)
    if isinstance(played, HttpResponse):
        return played
    turn, text = played
    # Both fragments are out of band: the story (a reaction's turn, or the
    # same turn) and the panel, whose detail area carries this command's message.
    return HttpResponse(_render_play_content(request, story, turn.state, turn.current_game.state, command_result=text))


@login_required
@require_POST
def play_take_exit(request: WSGIRequest, slug: str) -> HttpResponse:
    """Take one exit from the game panel's compass, as a story turn.

    The exit is looked up in the panel the game gives for this turn, so only
    an exit it offers as passable now can be taken, and the client never
    names a knot. Played through `_play_turn()`, like a story choice: the
    concurrent-tab guard, one transaction, and an undo snapshot.

    Args:
        request: The incoming request. POST body: "exit_id" (the exit's `id`
            in its compass section) and "turn_count" (the concurrent-tab token).
        slug: The story's slug.

    Returns:
        The play-content partial for the new turn with the refreshed panel,
        400 when "exit_id" is missing or names no passable exit, or the 409
        stale-tab partial.

    Raises:
        Http404: If no accessible Story or CurrentGame exists.
        TravelError: The exit's arrival knot does not exist, or the turn
            offers no movement choice -- a fault in the game, not the request.
    """
    story = _get_accessible_story(request, slug)
    if isinstance(story, HttpResponse):
        return story
    exit_id = request.POST.get("exit_id", "")

    def take(turn: _Turn) -> HttpResponse | None:
        exit_ = find_exit(game_panel_context(story, turn.engine_state, turn.state.globals), exit_id)
        if exit_ is None:
            return HttpResponse("That way is not open.", status=400)
        take_exit(turn.state, exit_["arrival_knot"], exit_["travel_text"])
        turn.transcript = _append_transcript_entry(turn.transcript, turn.state.last_turn_text, exit_["label"])
        return None

    played = _play_turn(request, story, take)
    if isinstance(played, HttpResponse):
        return played
    turn, _ = played
    return HttpResponse(_render_play_content(request, story, turn.state, turn.current_game.state))


@login_required
@require_POST
def play_take_action(request: WSGIRequest, slug: str) -> HttpResponse:
    """Run one story action from a panel action or followers section, as an interlude turn.

    The action is looked up in the panel the game gives for this turn,
    freshly listed, so only an action the story offers now can be run and
    the client never names a knot. Played through `_play_turn()`, like a
    story choice: the concurrent-tab guard, one transaction, and an undo
    snapshot.

    Args:
        request: The incoming request. POST body: "group" and "label" (the
            action's group id and label in its section) and "turn_count"
            (the concurrent-tab token).
        slug: The story's slug.

    Returns:
        The play-content partial for the new turn with the refreshed panel,
        400 when the story offers no such action now or has no choices to
        return to, or the 409 stale-tab partial.

    Raises:
        Http404: If no accessible Story or CurrentGame exists.
    """
    story = _get_accessible_story(request, slug)
    if isinstance(story, HttpResponse):
        return story
    group = request.POST.get("group", "")
    label = request.POST.get("label", "")

    def take(turn: _Turn) -> HttpResponse | None:
        panel = game_panel_context(story, turn.engine_state, turn.state.globals)
        panel = fill_action_sections(panel, turn.state)
        panel = fill_followers_sections(panel, turn.state)
        action = find_action(panel, group, label)
        if action is None:
            return HttpResponse("That is not possible now.", status=400)
        try:
            turn.state.start_interlude(action["target"])
        except InterludeError:
            return HttpResponse("That is not possible now.", status=400)
        turn.transcript = _append_transcript_entry(turn.transcript, turn.state.last_turn_text, label)
        return None

    played = _play_turn(request, story, take)
    if isinstance(played, HttpResponse):
        return played
    turn, _ = played
    return HttpResponse(_render_play_content(request, story, turn.state, turn.current_game.state))

"""Core play-loop views for the interactive_fiction app.

Play routes require login unconditionally (django.contrib.auth's
login_required), unlike the rest of the site's gallery views which only gate
behind quickbbs.common.require_login_if_configured. The library view is the
one route that follows the site-wide policy, since its anonymous branch
(Story.objects.filter(is_public=True)) already handles open-browsing installs.

play()/play_submit() are implemented (Step 3): the turn loop reads/writes
CurrentGame.state via InkRuntimeState.to_dict()/from_dict(), and
play_submit() enforces the concurrent-tab guard described in the plan (a
stale tab's submitted turn_count no longer matching the stored row is
rejected rather than silently applied). play_undo()/play_restart() (Step 8)
and the library's play-status annotations (Step 7) build on the same
CurrentGame.state shape, with "transcript"/"previous_state" layered on top
of InkRuntimeState's own serialized fields (see _build_current_game_state()).

Story upload/authoring (Step 4/5: upload(), edit(), story_image(),
story_cover()) lives in story_views.py; named save-slot management (Step 3:
saves(), saves_save(), saves_load(), saves_export(), saves_import()) lives
in save_views.py — both split out of this module 2026-08-16 once it passed
pylint's 1000-line module threshold. A game's own side panel (play_panel_tab(),
play_panel_action(), play_panel_command()) lives in panel_views.py, split
out the same way 2026-09-04. _load_game_state()/_render_play_content()/
_build_current_game_state() stay here and are imported by every sibling
module, since they're the shared engine-state plumbing every view in the
app needs.
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

from interactive_fiction.engine import InkRuntimeState, load_list_defs, load_story_root
from interactive_fiction.engine_services import (
    bindings_for,
    game_panel_context,
    play_layout_for,
)
from interactive_fiction.ingestion import find_inkj_file_by_path
from interactive_fiction.models import (
    CurrentGame,
    SaveState,
    Story,
    StoryImage,
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
        initial_globals: Real Ink VAR values to set before the story's
            own opening `continue_story()` call runs — e.g. a
            character-creation answer (`player_name`, `player_gender`)
            collected by `character_creation_submit()` for a game whose
            manifest declares `Story.game_new_game_fields`. None (the
            default, and the case for every story without such fields)
            leaves the compiled story's own declared VAR defaults
            untouched.

    Returns:
        A new InkRuntimeState, given real EXTERNAL bindings
        (engine_services.bindings_for(story, engine_state),
        claude_docs/plans/external_expansion_IF_engine.md Step 3, extended
        2026-08-23 for stateful APIs) only if story is marked
        Story.is_engine_trusted, and already advanced through its first
        continue_story() call so it's ready to display.
    """
    root = load_story_root(story.compiled_json)
    list_defs = load_list_defs(story.compiled_json)
    state = InkRuntimeState(root, list_defs, engine_bindings=bindings_for(story, engine_state))
    if initial_globals:
        state.globals.update(initial_globals)
    state.continue_story()
    return state


# Titles/words derived purely from the one gender value a "radio_image"
# character-creation field can set — real formulas straight from a
# converted game's own VAR citation comment. The real game asks ONE
# question ("are you a man or a woman?"), never seven — these are computed
# automatically whenever a submitted field sets `player_gender`, not asked
# as separate form fields.
def _compute_derived_gender_vars(gender: str) -> dict[str, Any]:
    """Compute every gender-only title/word VAR derived from one gender choice.

    Args:
        gender: The player's own gender value — the original's `sGender`
            string, one of "man", "woman" or "futa".

    Returns:
        The 6 derived VAR values a game folder's `_globals.ink` (or
        equivalent) declares alongside its own gender value:
        `player_master_title`, `player_lord_title`, `player_sir_title`,
        `player_miss_title`, `player_man_woman_word`, `player_sex_word`.

        All six are "man vs. not a man", and futa counts as not-a-man:
        source's own `getManWoman()` (`people.js:859`) collapses futa to
        "woman". The sex-organ question ("is this body male-sexed?", true
        for a futa too) is NOT derived here — it is a formula over the
        gender value, which the story asks directly.
    """
    is_man = gender == "man"
    return {
        "player_master_title": "Master" if is_man else "Mistress",
        "player_lord_title": "My Lord" if is_man else "My Lady",
        "player_sir_title": "Sir" if is_man else "Ma'am",
        "player_miss_title": "Mr" if is_man else "Miss",
        "player_man_woman_word": "man" if is_man else "woman",
        "player_sex_word": "boy" if is_man else "girl",
    }


def _resolve_radio_image_choice(field: dict[str, Any], post_data: dict[str, str]) -> dict[str, Any]:
    """Resolve one submitted `radio_image` field to its chosen `value` dict.

    Args:
        field: The field's own manifest entry (`options`, `default`).
        post_data: The submitted form data, keyed by the field's own
            `var` name.

    Returns:
        The chosen option's own `value` dict (e.g.
        `{"player_gender": "futa"}`), or an empty dict if the field
        declares no options at all.
    """
    options = field.get("options", [])
    submitted_index = post_data.get(field["var"])
    if submitted_index is not None and submitted_index.isdigit() and int(submitted_index) < len(options):
        return dict(options[int(submitted_index)]["value"])
    default_option = next((opt for opt in options if opt["value"] == field.get("default")), options[0] if options else None)
    return dict(default_option["value"]) if default_option is not None else {}


def _character_creation_globals(story: Story, post_data: dict[str, str], base_globals: dict[str, Any]) -> dict[str, Any]:
    """Resolve one submitted character-creation form into real Ink globals.

    Args:
        story: The story whose `game_new_game_fields` describes the form
            that was submitted.
        post_data: The submitted form data (`request.POST`), keyed by
            each field's own `var` name.
        base_globals: The compiled story's own already-initialized VAR
            defaults (a fresh `InkRuntimeState.globals`, built before
            calling `continue_story()`) — read by an `add_to` checkbox
            field (e.g. a lottery-cash bonus) so it adds to the story's
            REAL declared starting value, not a guessed `0`, in case a
            future field ever changes the base value first.

    Returns:
        Every Ink global to set before the story's first turn: each
        field's own chosen value (a `radio_image` field's `value` is
        itself a dict of `{var_name: value}` pairs, merged in directly),
        plus, for any `radio_image` field whose chosen value sets
        `player_gender`, the 6 real derived title/word VARs
        (`_compute_derived_gender_vars()`) computed automatically — never
        asked as their own separate fields, matching the real game's own
        single gender question. A
        missing/invalid submission for a field falls back to that
        field's own declared `default`.
    """
    result: dict[str, Any] = {}
    additive_fields: list[dict[str, Any]] = []
    for field in story.game_new_game_fields:
        var_name = field["var"]
        field_type = field["type"]
        if field_type == "text":
            result[var_name] = post_data.get(var_name, field.get("default", ""))
        elif field_type == "radio_image":
            result.update(_resolve_radio_image_choice(field, post_data))
        elif field_type == "checkbox":
            submitted = post_data.get(var_name)
            checked = submitted == "on" if submitted is not None else bool(field.get("default", False))
            if "add_to" in field:
                # Deferred until every other field's own value is resolved
                # (see below) so an additive field can add to a base value
                # another field just set, not just the manifest's own
                # static default.
                additive_fields.append({"checked": checked, "add_to": field["add_to"]})
                continue
            result[var_name] = checked
            for linked_var, value_map in field.get("linked_vars", {}).items():
                result[linked_var] = value_map[str(checked)]
    for additive in additive_fields:
        if not additive["checked"]:
            continue
        for target_var, amount in additive["add_to"].items():
            result[target_var] = result.get(target_var, base_globals.get(target_var, 0)) + amount
    if "player_gender" in result:
        result.update(_compute_derived_gender_vars(str(result["player_gender"])))
    return result


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
    story = get_object_or_404(Story, slug=slug, is_available=True)
    if not user_can_access(story, request.user):
        return HttpResponse(status=403)
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
        A redirect to the normal play page, now with a fresh CurrentGame
        row whose opening turn already reflects every submitted answer.

    Raises:
        Http404: If no accessible Story matches slug.
    """
    story = get_object_or_404(Story, slug=slug, is_available=True)
    if not user_can_access(story, request.user):
        return HttpResponse(status=403)

    # A bare, binding-less state to read the story's own real starting
    # global values from (no EXTERNAL calls fire, no continue_story() —
    # constructing InkRuntimeState only runs its global-decl container),
    # so an "add_to" checkbox field can add to the ACTUAL declared
    # default rather than guessing 0.
    base_globals = InkRuntimeState(load_story_root(story.compiled_json), load_list_defs(story.compiled_json)).globals
    initial_globals = _character_creation_globals(story, request.POST, base_globals)
    engine_state: dict[str, Any] = {}
    state = _new_game_state(story, engine_state, initial_globals=initial_globals)
    transcript = _append_transcript_entry([], state.last_turn_text, chosen_label=None)
    CurrentGame.objects.update_or_create(
        user=request.user,
        story=story,
        defaults={
            "state": _build_current_game_state(state, previous_raw_state=None, transcript=transcript, engine_state=engine_state),
            "turn_count": state.turn_count,
        },
    )
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
    state = _load_game_state(story, previous_raw_state, engine_state)
    return current_game, engine_state, state


def _load_game_state(story: Story, saved: CurrentGame | SaveState | dict[str, Any], engine_state: dict[str, Any]) -> InkRuntimeState:
    """Rebuild an InkRuntimeState from a stored CurrentGame/SaveState row or raw state dict.

    Args:
        story: The story the game belongs to (compiled_json must match
            what saved.state was serialized against).
        saved: The stored row (either model — both carry a `state`
            JSONField holding an InkRuntimeState.to_dict() result in the
            identical shape) or a raw state dict directly (Step 8's
            play_undo() passes CurrentGame.state["previous_state"] this way
            — it's already the same shape, with no row to wrap it in).
        engine_state: The session's own mutable `engine_state` dict,
            typically read straight out of the same `saved` dict/row this
            call is rebuilding from (see `_build_current_game_state()`) —
            passed straight through to `engine_services.bindings_for()`.

    Returns:
        The rebuilt InkRuntimeState, given the same real EXTERNAL bindings
        (engine_services.bindings_for(story, engine_state),
        claude_docs/plans/external_expansion_IF_engine.md Step 3, extended
        2026-08-23 for stateful APIs) a fresh game for this same story
        would get — re-derived from story.is_engine_trusted on every
        load, never itself part of the saved state (only each stateful
        API's own DATA is). A path in saved.state that no longer resolves
        against story.compiled_json degrades per InkRuntimeState.from_dict()'s
        own rules (a dropped choice, a null pointer) rather than raising —
        full save-compatibility repair (detecting this and recovering to
        the nearest valid point) is Step 4 scope, not attempted here.
    """
    root = load_story_root(story.compiled_json)
    list_defs = load_list_defs(story.compiled_json)
    raw_state = saved if isinstance(saved, dict) else saved.state
    return InkRuntimeState.from_dict(root, raw_state, list_defs, engine_bindings=bindings_for(story, engine_state))


_MEDIA_TAG_URL_NAMES = {"image:": "if_story_image", "video:": "if_story_video"}


def _current_image_urls(story: Story, state: InkRuntimeState) -> list[str]:
    """Resolve `image: <tag_name>`/`video: <tag_name>` tags active this turn to servable URLs.

    A tag naming a file with no matching StoryImage row is silently
    skipped (per the plan: a work-in-progress story with placeholder tags
    still plays, text-only, rather than erroring).

    Args:
        story: The story being played.
        state: The current InkRuntimeState.

    Returns:
        The if_story_image/if_story_video URL for each resolved tag, in tag
        order.
    """
    tag_names_by_prefix: dict[str, list[str]] = {prefix: [] for prefix in _MEDIA_TAG_URL_NAMES}
    for tag in state.current_tags:
        stripped = tag.strip()
        lowered = stripped.lower()
        for prefix in _MEDIA_TAG_URL_NAMES:
            if lowered.startswith(prefix):
                tag_names_by_prefix[prefix].append(stripped[len(prefix) :].strip())
                break

    all_tag_names = [name for names in tag_names_by_prefix.values() for name in names]
    if not all_tag_names:
        return []

    available = set(story.images.filter(tag_name__in=all_tag_names).values_list("tag_name", flat=True))
    urls: list[str] = []
    for prefix, url_name in _MEDIA_TAG_URL_NAMES.items():
        urls.extend(reverse(url_name, args=[story.slug, name]) for name in tag_names_by_prefix[prefix] if name in available)
    return urls


def _play_content_context(
    request: WSGIRequest, story: Story, state: InkRuntimeState, *, transcript: list[dict[str, object]] | None = None, can_undo: bool = False
) -> dict[str, object]:
    """Build the template context shared by the play page and its partial.

    `state.done` alone is not "the story has genuinely ended" — Section
    3's engine deliberately sets it whenever a bare "done"/"end" marker is
    reached, even mid-turn while choices are still pending (choose()
    clears it again on the next selection), so a `ControlCommand.Done`
    encountered between two sibling choices in the same weave doesn't
    look any different from the real end of the story unless this is
    checked alongside current_choices. The story is only actually over
    when there is nothing left to choose either.

    Args:
        request: The incoming request.
        story: The story being played.
        state: The current InkRuntimeState.
        transcript: Step 8's rolling turn history (oldest first), or None
            if the caller has none to show (e.g. a fresh CurrentGame row
            that hasn't been through _build_current_game_state() yet).
        can_undo: Whether a "previous_state" exists to undo back to
            (Step 8) — False for a story's very first turn.

    Returns:
        The context dict for play_content.jinja (and play.jinja, which
        includes it). "image_urls" resolves every image: tag active on this
        turn (Step 5) to a servable URL — a tag with no matching StoryImage
        row is silently dropped, not surfaced as an error, so a
        work-in-progress story with placeholder tags still plays (per the
        plan).
    """
    return {
        "story": story,
        "text": state.last_turn_text,
        "choices": list(enumerate(c.text for c in state.current_choices)),
        "done": state.done and not state.current_choices,
        "turn_count": state.turn_count,
        "image_urls": _current_image_urls(story, state),
        "transcript": transcript or [],
        "can_undo": can_undo,
        "user": request.user,
    }


def _render_play_content(
    request: WSGIRequest, story: Story, state: InkRuntimeState, *, transcript: list[dict[str, object]] | None = None, can_undo: bool = False
) -> str:
    """Render the play-content partial for a given state.

    Args:
        request: The incoming request.
        story: The story being played.
        state: The current InkRuntimeState.
        transcript: See _play_content_context().
        can_undo: See _play_content_context().

    Returns:
        The rendered partial HTML.
    """
    return render_to_string(
        "interactive_fiction/play_content.jinja",
        _play_content_context(request, story, state, transcript=transcript, can_undo=can_undo),
        request=request,
        using="Jinja2",
    )


def _build_current_game_state(
    state: InkRuntimeState, previous_raw_state: dict[str, Any] | None, transcript: list[dict[str, object]], engine_state: dict[str, Any]
) -> dict[str, Any]:
    """Build the dict written into CurrentGame.state, layering Step 8's
    presentation-history keys on top of InkRuntimeState.to_dict().

    "transcript", "previous_state", and "engine_state" are QuickBBS-level
    bookkeeping, not core engine state — InkRuntimeState.to_dict()/
    from_dict() know nothing about them (from_dict() ignores unrecognized
    keys via its own data.get() reads, and to_dict() naturally omits
    them), so this function is the one place that layers them onto the
    engine's own serialized dict before it goes to the database, and
    _load_game_state()/the views read them back out of the same dict by
    key.

    Args:
        state: The current InkRuntimeState, already advanced to this turn.
        previous_raw_state: The raw dict CurrentGame.state held *before*
            this turn was applied (i.e. before calling state.choose()) —
            stored verbatim so Undo can restore it exactly, including its
            own transcript/previous_state/engine_state keys. None for a
            fresh game (no undo target yet).
        transcript: The rolling list of past turns (see
            _append_transcript_entry()), already capped.
        engine_state: The per-API state dict built/mutated by this same
            turn's own `bindings_for(story, engine_state)` call (see
            `_new_game_state()`/`_load_game_state()`) — e.g. whatever a
            stateful API's own `bind_stateful` closures wrote via
            `set_location()`-style calls during `state.continue_story()`.
            Stored verbatim; `_load_game_state()`'s own caller reads it
            back out under this same key to rebuild the next turn's
            bindings from.

    Returns:
        The dict to store in CurrentGame.state.
    """
    data = state.to_dict()
    data["transcript"] = transcript
    data["previous_state"] = previous_raw_state
    data["engine_state"] = engine_state
    return data


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
    updated = transcript + [{"text": text, "chosen_label": chosen_label}]
    if len(updated) > settings.MAX_TRANSCRIPT_TURNS:
        updated = updated[-settings.MAX_TRANSCRIPT_TURNS :]
    return updated


def _story_play_statuses(user: "AbstractUser | AnonymousUser", stories: list[Story]) -> dict[int, str]:
    """Classify each story's play state for the given user (Step 7/8).

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
    file_entry = find_inkj_file_by_path(story.source_fqfn)
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
        status (Step 7: not started / continue / finished), and a sidebar
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

    cover_story_ids = set(StoryImage.objects.filter(story_id__in=[story.pk for story in stories], is_cover=True).values_list("story_id", flat=True))
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
    story = get_object_or_404(Story, slug=slug, is_available=True)
    if not user_can_access(story, request.user):
        return HttpResponse(status=403)

    current_game = CurrentGame.objects.filter(user=request.user, story=story).first()
    if current_game is None and story.game_new_game_fields:
        return redirect("if_character_creation", slug=story.slug)
    if current_game is None:
        engine_state: dict[str, Any] = {}
        state = _new_game_state(story, engine_state)
        transcript = _append_transcript_entry([], state.last_turn_text, chosen_label=None)
        CurrentGame.objects.create(
            user=request.user,
            story=story,
            state=_build_current_game_state(state, previous_raw_state=None, transcript=transcript, engine_state=engine_state),
            turn_count=state.turn_count,
        )
    else:
        state = _load_game_state(story, current_game, current_game.state.get("engine_state", {}))
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
    story = get_object_or_404(Story, slug=slug, is_available=True)
    if not user_can_access(story, request.user):
        return HttpResponse(status=403)

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
    """Undo the last choice, restoring CurrentGame to its previous turn (Step 8).

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
    story = get_object_or_404(Story, slug=slug, is_available=True)
    if not user_can_access(story, request.user):
        return HttpResponse(status=403)

    with transaction.atomic():
        current_game = get_object_or_404(CurrentGame.objects.select_for_update(), user=request.user, story=story)
        previous_raw_state = current_game.state.get("previous_state")
        if not previous_raw_state:
            return HttpResponse(status=400)

        # Deep-copied for the same reason as play_submit() above: this
        # dict is about to become the new current_game.state verbatim, so
        # nothing built from it (bindings_for()'s stateful closures) may
        # mutate the very dict being restored.
        state = _load_game_state(story, previous_raw_state, copy.deepcopy(previous_raw_state.get("engine_state", {})))
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
    """Reset CurrentGame to the story's start, discarding in-flight progress (Step 8).

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
    story = get_object_or_404(Story, slug=slug, is_available=True)
    if not user_can_access(story, request.user):
        return HttpResponse(status=403)

    if story.game_new_game_fields:
        CurrentGame.objects.filter(user=request.user, story=story).delete()
        response = HttpResponse(status=204)
        response["HX-Redirect"] = reverse("if_character_creation", args=[story.slug])
        return response

    engine_state: dict[str, Any] = {}
    state = _new_game_state(story, engine_state)
    transcript = _append_transcript_entry([], state.last_turn_text, chosen_label=None)
    CurrentGame.objects.update_or_create(
        user=request.user,
        story=story,
        defaults={
            "state": _build_current_game_state(state, previous_raw_state=None, transcript=transcript, engine_state=engine_state),
            "turn_count": state.turn_count,
        },
    )

    return HttpResponse(_render_play_content(request, story, state, transcript=transcript, can_undo=False))


@login_required
def preferences(request: WSGIRequest) -> HttpResponse:
    """View/edit the current user's Interactive Fiction reader display preferences (Step 8).

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

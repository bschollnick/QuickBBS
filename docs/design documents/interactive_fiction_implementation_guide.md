# interactive_fiction — Implementation Guide

**Version:** 2.0
**Author:** Benjamin Schollnick
**Last Updated:** 2026-08-26

**Companion to:** [`interactive_fiction_and_quickbbs.md`](interactive_fiction_and_quickbbs.md)
— read that first for the guiding principles and architecture; this document is the
how-to and build-order companion, covering integration steps, per-model detail, and
what remains to be built.

---

## 1. What this document is

A practical guide to two audiences: a **story author** who wants to get an Ink game
playable inside QuickBBS, and a **developer** picking up the remaining build work.
Where the main design document states *why* the app is shaped the way it is, this
document states *how* to actually do the integration — the concrete steps, the model
fields involved, and the order remaining work needs to happen in.

Status markers used throughout:

- ✅ **Built** — implemented and tested against real data.
- 🚧 **Designed, not built** — the shape below is the intended design; no code exists
  yet, or only scaffolding exists.

---

## 2. Getting a story into QuickBBS — author's guide

### 2.1 Write and compile the story (offline)

1. Write the story in [Inky](https://github.com/inkle/inky), inkle's free Ink
   editor, or in a plain `.ink` text file.
2. Compile it to JSON:
   - In Inky: **File → Export → Export to JSON**.
   - From the command line: `inklecate story.ink` (produces `story.ink.json`).

   Either way, this step happens on the author's own machine. QuickBBS never
   compiles `.ink` source itself — the server only ever reads already-compiled JSON
   (main design document §1.2, §5).
3. Rename the compiled file's extension from `.json` to `.inkj`
   (`story.ink.json` → `story.inkj`). Plain `.json` is not a registered gallery
   extension, and the interactive-fiction scanner only ever looks for `.inkj`.
4. Sanity-check the compiled JSON has the shape the interpreter expects: a top-level
   object with `inkVersion`, `root`, and `listDefs` keys, and an `inkVersion` within
   `SUPPORTED_INK_VERSIONS` (`quickbbs_settings.py`; currently `(21,)`). Inky/`inklecate`
   output already has this shape; this matters mainly if the JSON was produced or
   edited by hand.

### 2.2 Choose an ingestion path — ✅ Built

Both paths run the same validation (§2.4). Every game — regardless of which path
creates its `Story` row — is a **directory** under `Albums/interactive_fiction/`,
containing exactly one mandatory manifest file, `__init__.py`, and the game's
compiled `.inkj` file. One game folder produces exactly one `Story` row; any other
`.inkj` files present in the same folder are ignored, since a compiled Ink file is a
complete, self-contained game rather than a chapter of a larger one.

The manifest declares:

```python
# Albums/interactive_fiction/<game_name>/__init__.py
GAME_TITLE = "..."
GAME_AUTHOR = "..."
REQUIRED_PLUGINS = ["scheduling", "character_occupancy"]  # names from engine_plugins/
MAIN_STORY_FILE = "story.inkj"
NEW_GAME_FIELDS = [...]        # character-creation form field definitions
SOURCE_GAME_VERSION = "..."
```

`ingestion.py` parses this file with `ast.literal_eval` on its top-level assignments
only — it is never imported or executed, because the folder lives in the same
untrusted `Albums/` tree as any other gallery content and must be readable before any
`Story` row exists to grant it engine trust (main design document §1.7).

**Path A — Upload form.** ✅ Built. `story_views.upload()`, gated to
`quickbbs.common.can_upload_story()` (staff/superuser by default). The author uploads
the compiled `.inkj`; QuickBBS validates it (§2.4) and creates a `Story` row with
`owner` set to the uploading user, `is_public=False` by default.

**Path B — Scanner ingestion, from a game folder under `Albums/`.** ✅ Built, two ways:

1. **Batch, via `manage.py scan_if_stories`.** Walks
   `Albums/interactive_fiction/` (and nowhere else in the gallery), then runs
   `interactive_fiction.ingestion.verify_stories()` (drift/removal handling for
   existing games) followed by `interactive_fiction.ingestion.ingest_stories()`
   (creates a `Story` for every game folder not yet ingested), then
   `interactive_fiction.models.sync_engine_apis()` (registers any newly-discovered
   plugin as an `EngineAPI` row, disabled by default). Accepts `--max_count N` to cap
   work per run.
2. **Live, on first browse.** `ingestion.ingest_stories_in_directory()` runs as an
   additive step right after the ordinary gallery scan's `sync_files()`, whenever the
   directory being scanned is a direct child of `Albums/interactive_fiction/` — so a
   game folder becomes playable the moment its directory is visited, without waiting
   for a batch scan.

Either way, the resulting `Story` is owned by the account named in
`IF_SCAN_DEFAULT_OWNER` (`quickbbs_settings.py`; currently `if_librarian`), not by
whoever ran the scan or browsed the directory. Ingestion failure — a missing
manifest, a `MAIN_STORY_FILE` that doesn't match a real tracked gallery file, invalid
compiled content — is never silent: `Story.game_ingestion_error` is set and surfaced
as a filterable column in Django admin, and the row is retried (not recreated) on the
next scan once the problem is fixed.

### 2.3 Publish it

Whichever path created the `Story` row, it starts private (`is_public=False`
for uploads; scanner-ingested games likewise start private unless the manifest or a
subsequent admin edit changes that). To share it:

- Flip `is_public` to make it visible to every authenticated user (and, per the
  library view's anonymous branch, to anonymous visitors too).
- Or grant specific users access individually via `StoryAccess` — managed through
  Django admin only, no self-service form.

A game ingested via the scanner is also visible in ordinary gallery listings as a
directory/file like any other gallery content, but the gallery item's "Play" link
still enforces the same `user_can_access()` check as everything else in this app
(§6.3). Being visible in a listing is not the same as being playable.

### 2.4 What validation actually checks — ✅ Built

Both ingestion paths run the same checks before a `Story` row is created or updated:

- The upload parses as JSON.
- It has the expected top-level Ink structure (`inkVersion`, `root`, `listDefs`).
  A non-empty `listDefs` is fine — LISTs are supported.
- `inkVersion` falls within `SUPPORTED_INK_VERSIONS`; a story compiled against an
  unvalidated Ink version is rejected rather than silently misinterpreted.
- Every `EXTERNAL` function the story declares has a same-named in-story fallback
  function defined. A story with an unbound `EXTERNAL` is rejected, naming the
  missing function(s), rather than accepted and left to fail mid-play — this check
  runs regardless of whether the story will ever be granted engine trust.
- For scanner ingestion specifically: `MAIN_STORY_FILE` must resolve to an
  already-scanned `FileIndex` row (`images.find_file_by_path()`, itself built on
  `DirectoryIndex.search_for_directory()`); an untracked file fails ingestion with an
  explicit "run the gallery scanner first" error rather than being read directly off
  disk.

A file that fails validation is never stored as a `Story` — for scanner ingestion,
the failure is recorded on the row via `Story.game_ingestion_error` and surfaced in
admin, not silently retried forever.

---

## 3. Ink authoring gotchas and host bindings

Verified while converting a large, pre-existing choice-based game into Ink — three
real Ink authoring mistakes surfaced during that conversion, each initially suspected
to be a QuickBBS interpreter bug. All three were checked against the official
`inkjs` reference runtime before touching `engine.py`, and all three turned out to be
correct, documented Ink behavior, reproduced identically by both `inkjs` and
QuickBBS's own interpreter. Nothing in `engine.py` needed to change. These are noted
here as authoring guidance so the next game doesn't lose time on the same three
things.

**Tunnel calls are `-> knot ->`, never `->-> knot`.** `->->` on its own is the *tunnel
return* statement (`POP_TUNNEL` — "pop back to wherever the tunnel was called from"),
not a way to spell "call this knot as a tunnel." Writing `->-> knot` compiles without
a compile error, but produces garbage bytecode — a string-literal push followed by an
unconditional tunnel-pop with no tunnel ever having been pushed — and the official
`inkjs` runtime throws a runtime error on it ("Found tunnel onwards statement, when
expected end of flow"). The correct call site is:

```ink
=== hub ===
-> stats_header ->
Rest of the hub content.

=== stats_header ===
Money: {money}
->->
```

**A `*` choice nested inside a bare `{condition: ...}` text block does not register
as a real choice.** This is a well-known Ink gotcha, not a QuickBBS-specific issue:

```ink
* [Always shown] -> a
{ hasFlag:
* [Only if hasFlag] -> b
}
```

`b`'s choice silently never appears, flag true or not — confirmed against `inkjs`
directly. The correct, documented pattern for a conditionally-visible choice is an
inline condition on the choice itself:

```ink
* [Always shown] -> a
* {hasFlag} [Only if hasFlag] -> b
```

**Use `+` (sticky), not `*` (once-only), for hub/menu choices that lead to
repeatable content.** A `*` choice's once-only pruning is keyed off its *target
container's* visit count, not the hub's — so `* [Talk to a character] -> that_scene`
permanently disappears the moment `that_scene` has been visited once, even if the
player returns to the hub many times over the course of the story. This is correct
Ink semantics (confirmed identical in both `inkjs` and `engine.py`'s
`_process_choice_point`/`_visit_count`), not a bug — `*` truly means "offer this once,
ever." Any menu/hub knot meant to be revisited across turns (a location, a status
screen, a shop) should use `+` for its navigation choices; reserve `*` for choices
that are narratively meant to happen at most once in the whole story.

For standard-Ink authoring rules more generally — choice syntax, structure,
`INCLUDE` scoping, LIST semantics, tunnels and the rest — see
[`Docs/ink_language_guide.md`](../ink_language_guide.md), and inkle's own
reference vendored at `quickbbs/interactive_fiction/ink_reference/`
(`ink_JSON_runtime_format.md` there is the spec `engine.py` implements). The
rest of this section covers what is specific to *this host*: how a story
reaches Python.

### 3.1 EXTERNAL bindings — the failure modes that are silent

`EXTERNAL` is how Ink calls out to the host. Three rules learned the hard way:

**Every `EXTERNAL` needs a fallback stub**, or the story cannot compile
standalone. The stub is also the hazard: if the binding is not actually
wired at runtime, the stub answers instead — `""` for a string, `false` for a
boolean — and **nothing raises**. Presence tests then answer "nobody is
anywhere" and the affected content simply never appears. A binding that is
declared, stubbed, and unwired looks exactly like a binding that works and
reports no.

**Bindings are gated by configuration.** A story receives an API's bindings
only if it has a `StorySystemConfig` row for that API *and* the `EngineAPI` is
enabled (§6.6, §6.7). Both gates are silent when unset. A test harness that
assembles its own module list will therefore produce a *different* binding set
than the running game — always resolve through `engine_services.bindings_for()`,
the real production path.

**An EXTERNAL cannot hold state across calls** in the narrow case where the
host has no place to put it — one-shot facts are better as plain Ink VARs.
This does *not* mean bindings can't take flags as ordinary arguments; passing
state in is fine and normal.

Prefer a **stateful binding over a shadow VAR**: `set_location_now(...)` /
`where_is_now(...)` reading the engine's own store beats a VAR that has to be
kept in sync by hand (§2.4).

**The worst outcome this project had: every binding silently falling through
to its stub, for months.** Two independent enablement gates were unset — the
API's own `is_enabled` flag, and the per-story opt-in table (which returns an
empty binding map when it has *no rows at all*). Every `.py` file, every
`EXTERNAL` declaration, and every descriptor was individually correct.
**Neither gate produces an error when unset.**

The consequence is worth stating plainly: every behaviour previously
"verified against the real engine" had been exercising the dead stub. Check
the wiring, not just the code:

```python
>>> bindings_for(story, {})
{}                        # <- the failure. Should be a dict of callables.
```

**Detect it with an impossible sentinel.** Make the Ink fallback stub return
a value the real binding can never produce (`-1`), then assert the observed
value is not it. That distinguishes "the binding ran" from "the stub ran",
which no ordinary assertion can.

**Watch for binding-name collisions.** If a generic plugin and a
game-specific module bind the same Ink function name, whichever is merged
second silently wins — order-dependent and never intended. Never opt a story
into both.

**An `EXTERNAL` parameter may not share a name with a global VAR:**
`argument 'zali_met': name has already been used for a var`. Grep for
`^VAR <name>` across *all* `.ink` files and recompile the whole corpus before
changing a signature — a single-file compile will not show it.

**An `EXTERNAL` argument may be an arbitrary expression**, which is usually
the fix when no plain boolean VAR exists:

```ink
~ temp p = ash_place_now(n_time, ash_charmed_level == 0)
```

**An `EXTERNAL` cannot supply a non-zero initial value** the way
`VAR x = "Davy"` can — it always starts at the engine's generic default. Seed
it at the character's real first-encounter scene, so nothing can read a wrong
value beforehand. Six wrong-default bugs came from missing this.

### 3.2 Testing that a binding is really wired

A declared-but-unwired `EXTERNAL` falls through to its Ink stub and answers
`""`/`false` forever, so "the tests pass" proves very little on its own. Two
checks that do prove something:

- **Assert each plugin's exact binding list.** Every new binding must be added
  to that assertion, so an accidental removal fails loudly.
- **Give the stub an impossible sentinel.** Have the Ink fallback return a
  value the real binding can never produce (`-1`), then assert the observed
  value is not it. That is what distinguishes "the binding ran" from "the stub
  ran" — no ordinary assertion can. Test the untrusted path too, confirming it
  really does fall through.

### 3.3 Runtime notes — for anyone working on `engine.py`

- **Truncate the output buffer per turn.** Ink's stream is append-only and
  each turn slices from its own start index; serializing the whole history
  grew saved state without bound (34KB → 114KB by turn 600, ~111 bytes/turn,
  69% of it output tokens).
- **Glue lookups are O(n) over the buffer**, so a runaway turn degrades
  quadratically rather than spinning at constant speed — a useful tell when
  diagnosing a hang.
- **Serialize the transient mid-dispatch flags.** Omitting `_eval_run_depth`
  (and `_pending_thread`, `_in_tag`, `_tag_buffer`, `_string_capture_stack`)
  made a snapshot taken mid-function-call resume with the counter reset,
  silently routing the "out" marker through a no-op branch and producing no
  output instead of the interpolated return value.
- **Reset per-turn tags.** Append-only tags leave every `image:` tag ever seen
  "active" for the rest of the story.
- **Port the RNG faithfully.** Shuffle uses a character-sum path hash plus the
  story seed — deliberately simple, matching the C# source.
- String operations are only `+`, `==`, `!=`. `?`/`!?` are LIST-only, which is
  why `not <string>` raises.

---

## 4. Story images and video — ✅ Built

Authors tag a knot, stitch, or line with an image or video reference using a plain
Ink tag:

```ink
=== forest_clearing ===
# image: forest_clearing.jpg
You step into a clearing. Sunlight filters through the leaves.
* [Look up]     -> look_up
* [Keep walking] -> deeper_woods
```

The tag's value (`forest_clearing.jpg`) must match, case-insensitively, the filename
of a real gallery file — a video tag (`# video: clip.mp4`) works the same way. There
is no separate upload step for story images: the referenced file is expected to
already exist as a real gallery file (typically in the same game folder, or wherever
the author places it under `Albums/`) and already be a tracked `FileIndex` row. An
author or an admin links a tag to its file via `images.link_story_image()`, which
creates the `StoryImage` mapping row and eagerly generates the linked file's
thumbnail through the gallery's existing thumbnail engine, rather than deferring
thumbnail generation to the first play request. A tag referenced in the story with no
matching linked image simply renders text-only for that turn — not a hard error, so a
work-in-progress game with placeholder tags still plays while art is pending.

One `StoryImage` per story can be marked `is_cover=True` (enforced by a partial
unique constraint); `Story.cover_image` is a computed property that returns it, not a
stored field. Whichever image is the cover gets a small library-grid thumbnail
generated the same way, via `STORY_COVER_THUMB_SIZE`.

There is no separate content-type whitelist or size cap specific to story images —
because the referenced file is already a scanned gallery file, it has already passed
whatever validation the gallery's own scan applies to that file type, and it is
served back to players through the gallery's existing serving path
(`FileIndex.inline_sendfile`/`async_inline_sendfile`, `ThumbnailFiles.send_thumbnail`),
not a bespoke one.

### 4.1 Two authoring rules that bite

**Tags are per-turn, and the host must reset them.** Ink's tag list is
append-only within a turn; if the host does not clear `current_tags` at the
start of each `continue_story()`, every `image:` tag ever encountered stays
"active" for the rest of the story and the page accumulates stale art.
`engine.py` clears it — this is noted so a reimplementation does not omit it.

**A media tag interpolates, which is what makes one tag serve many variants:**

```ink
# image: {model}/{outfit}/greeting.jpg
```

That is the intended pattern for per-character art. But **a variant VAR chosen
at random must be chosen once and remembered** — `RANDOM()` re-rolls on every
knot visit (see the Ink guide's Randomness section), so re-rolling inside the
tag makes a character change appearance mid-scene. Roll once into a VAR, then
read the VAR from the tag.

After any tag change, re-run `scan_if_stories` and confirm the reconcile still
reports `0 unlinked`; a typo or a rename surfaces there rather than as a
missing image in play.

---

## 5. Playing a story — request flow — ✅ Built

1. **GET `/if/`** — the library view (`views.library`). Lists every `Story` the
   current user can access: owned, public, or explicitly granted, via
   `user_can_access()`. Anonymous visitors see public stories only.
2. **GET `/if/<slug>/`** — the play view (`views.play`), full page. Loads (or
   creates) the player's `CurrentGame` row for this story and renders the current
   turn's text and choices. If the story defines `NEW_GAME_FIELDS`, a player with no
   `CurrentGame` yet is routed through character creation first
   (`/if/<slug>/new-game/`) before a game state is created.
3. **POST `/if/<slug>/play/`** (`views.play_submit`) — submitting a choice. An HTMX
   partial swap: only the story-text-and-choices region re-renders, not the page
   chrome. The view:
   - Rehydrates an `InkRuntimeState` from `CurrentGame.state`, resolving this
     story's real `EXTERNAL` bindings via `engine_services.bindings_for()`
     (trust-gated per main design document §1.7 — re-derived fresh on every load,
     never itself part of the saved state).
   - Calls the interpreter to follow the chosen option and advance to the next
     stopping point (`choose()` then `continue_story()`).
   - Serializes the new state back into `CurrentGame.state`.
   - Compares the submitted `turn_count` against `CurrentGame.turn_count` — a
     denormalized column read via a lightweight `.only("turn_count")` query — and
     rejects a stale submission (a second browser tab that fell behind) with a "story
     has moved on — refresh to continue" response instead of applying it (§6.5).
4. **POST `/if/<slug>/undo/` / `/if/<slug>/restart/`** — one-level undo, and a full
   restart, both built on the same rehydrate/advance/serialize shape.
5. **Save/load** (`/if/<slug>/saves/`, `save_views.py`) — copies `CurrentGame.state`
   into (or out of) a named `SaveState` slot, plus JSON export/import of a single
   slot. Loading a slot never mutates the slot itself.

Every step in this loop is stateless between requests — no process is held open for
a player between their turns (main design document §1.1).

---

## 6. Models

### 6.1 `Story` ✅ Built

The compiled story plus ownership/visibility/trust/game-manifest metadata.

| Field | Type | Notes |
|---|---|---|
| `owner` | FK → user | `DB_CASCADE` |
| `title` | `CharField` | |
| `slug` | `SlugField`, unique | |
| `compiled_json` | `JSONField` | The compiled `.ink.json` content |
| `ink_version` | `CharField` | From the compiled JSON, for compatibility checks |
| `is_public` | `BooleanField`, default `False` | Owner-only by default |
| `is_engine_trusted` | `BooleanField`, default `False` | Admin-only decision gating real EXTERNAL/plugin dispatch (§1.7 of the main design document) — never exposed on any user-facing form |
| `source_fqfn` | `CharField`, blank default | Scanner-ingestion origin path; `""` for upload-form stories |
| `source_sha256` | `CharField`, blank default | For drift detection on scanner verification |
| `is_available` | `BooleanField`, default `True` | `False` when the scanner-ingested source file has vanished (tombstoned, content cleared) |
| `game_author` | `CharField`, blank default | From the game folder's manifest |
| `game_required_plugins` | `JSONField`, default `list` | Plugin names the manifest declares — a declaration, not a grant of trust |
| `game_new_game_fields` | `JSONField`, default `list` | Character-creation form field definitions from the manifest |
| `game_ingestion_error` | `CharField`, blank default | Set when scanner ingestion fails for this game folder; filterable in admin |
| `created_at` / `updated_at` | `DateTimeField` | |

`cover_image` is a computed property (the story's `StoryImage` with `is_cover=True`,
if any) — not a stored field.

Every other query on `Story` besides the actual play/step path (library listing, slot
manager, edit-page metadata, ingestion existence checks) should `.defer("compiled_json")`
or use an explicit `.only()` field list. Postgres TOASTs a value this large
out-of-line, so listing many stories should not force detoasting all of their JSON
just to render a title and cover thumbnail.

### 6.2 `StoryAccess` ✅ Built

Grants one specific user access to a non-public story. The owner always has implicit
access — no row is created for the owner.

| Field | Type | Notes |
|---|---|---|
| `story` | FK → `Story` | `DB_CASCADE` |
| `user` | FK → user | `DB_CASCADE` |
| `granted_at` | `DateTimeField`, auto-add | |

Unique together on `(story, user)`. Managed through Django admin only — no
self-service "add a user by name" form.

### 6.3 `user_can_access()` ✅ Built

A plain function, not a permissions framework:

```python
def user_can_access(story, user) -> bool:
    if not user.is_authenticated:
        return story.is_public
    if story.owner_id == user.id or user.is_superuser:
        return True
    if story.is_public:
        return True
    return story.grants.filter(user=user).exists()
```

The anonymous branch is not optional — the library view's combined query
(`Q(owner=request.user) | Q(is_public=True) | Q(grants__user=request.user)`) raises
if handed an `AnonymousUser`, since FK filters can't accept one. Any view that might
serve an anonymous request must branch before reaching that query, not rely on this
function alone to short-circuit safely.

### 6.4 `StoryImage` ✅ Built

Maps one Ink tag name to one real gallery file. There is no per-story blob storage —
a story image is a reference into the gallery's own `FileIndex`/`ThumbnailFiles`
machinery, not a copy of file bytes belonging to this app (main design document §1.6).

```python
class StoryImage(models.Model):
    story = models.ForeignKey(Story, on_delete=models.DB_CASCADE, related_name="images")
    tag_name = models.CharField(max_length=255, db_index=True)
    file_index = models.ForeignKey(
        "quickbbs.FileIndex", on_delete=models.DB_SET_NULL, null=True,
        related_name="story_images",
    )
    is_cover = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["story", "tag_name"], name="unique_story_image_tag"),
            models.UniqueConstraint(fields=["story"], condition=models.Q(is_cover=True),
                                     name="unique_story_cover_image"),
        ]
```

`on_delete=DB_SET_NULL` on `file_index` means a `StoryImage` row survives its
underlying gallery file being removed — it becomes an unresolvable tag (renders
text-only, same as a tag with no linked image at all) rather than cascading away the
mapping itself.

### 6.5 `CurrentGame` / `SaveState` ✅ Built

```python
class CurrentGame(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DB_CASCADE, related_name="if_current_games")
    story = models.ForeignKey(Story, on_delete=models.DB_CASCADE, related_name="current_games")
    state = models.JSONField()  # InkRuntimeState.to_dict()
    turn_count = models.IntegerField(default=-1)  # denormalized copy of state["turn_count"]
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "story"], name="unique_user_story_current")]


class SaveState(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DB_CASCADE, related_name="if_saves")
    story = models.ForeignKey(Story, on_delete=models.DB_CASCADE, related_name="saves")
    slot = models.PositiveSmallIntegerField()
    label = models.CharField(max_length=100, blank=True)
    state = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "story", "slot"], name="unique_user_story_slot"),
            models.CheckConstraint(condition=models.Q(slot__lt=32), name="savestate_slot_ceiling"),
        ]
```

`slot` is capped by `MAX_SAVE_SLOTS_PER_STORY` (`quickbbs_settings.py`, default 5),
enforced in the view layer; the `CheckConstraint` at 32 is a hard database ceiling
well above any sane configured value, so a view-layer bug can't write slot 99 — it
does not track the actual configured cap.

**Concurrent-tab guard.** Two browser tabs playing the same story share one
`CurrentGame` row. `CurrentGame.turn_count` is a denormalized copy of
`state["turn_count"]`, read via a lightweight `.only("turn_count")` query so the
guard doesn't force detoasting the full state JSON just to compare a number. The play
`POST` includes the `turn_count` the submitting tab last rendered, and the view
compares it against the stored value before applying the choice, rejecting a
mismatch with a "story has moved on — refresh to continue" response instead of a
silent last-writer-wins overwrite.

Both tables serialize `InkRuntimeState.to_dict()` directly — no custom JSON encoder,
since the state is plain dicts/lists/primitives by construction.

### 6.6 `EngineAPI` ✅ Built

One row per plugin `discover_api_descriptors()` finds on disk — the registry an
administrator uses to globally enable or disable a plugin, independent of whether any
individual story is trusted.

| Field | Type | Notes |
|---|---|---|
| `name` | `SlugField`, unique | Matches an `EngineAPIDescriptor.name` |
| `display_name` | `CharField` | |
| `is_enabled` | `BooleanField`, default `False` | Safe-by-default; only `is_enabled` is editable in admin, everything else is scanner-managed |
| `discovered_at` | `DateTimeField`, auto-add | |
| `last_seen_at` | `DateTimeField`, auto | |

`sync_engine_apis()` upserts rows from `discover_api_descriptors()` on every scanner
run; it never deletes a row for a plugin that's temporarily missing from disk, so a
plugin's enabled/disabled decision survives a transient scan gap.

### 6.7 `StorySystemConfig` ✅ Built

One story's configuration for one reusable plugin — narrow per-story side-table,
same shape as `StoryImage`.

| Field | Type | Notes |
|---|---|---|
| `story` | FK → `Story` | `DB_CASCADE` |
| `system_name` | `CharField` | Validated against live `discover_api_descriptors()` in `clean()` — deliberately a plain string, not a closed enum, so a newly-discovered third-party plugin never needs a schema migration to become configurable |
| `config` | `JSONField`, default `dict` | Validated by the matching plugin's own `validate_config` function |
| `updated_at` | `DateTimeField`, auto | |

Unique together on `(story, system_name)`. `save()` always calls `full_clean()`
first, so validation is real for every caller — not only ModelForm/admin paths that
happen to call it themselves.

---

## 7. The plugin/discovery system

### 7.1 `engine_api.py` — the plugin contract ✅ Built

`EngineAPIDescriptor` (frozen dataclass) is the contract a plugin module must satisfy:
`name`, `display_name`, `bindings` (a dict of EXTERNAL-callable functions), an
optional `validate_config`, and — for a plugin that needs per-session state — a
`state_key`, `init_state`, and `bind_stateful`. Any module that defines a module-level
`API: EngineAPIDescriptor` in the generic `engine_plugins/` directory, or inside a
trusted game folder, is discoverable this way — a required-attribute contract, not a
naming convention.

`discover_api_descriptors()` scans both: the generic plugin directory via a normal
dotted import, and every game folder that has at least one `Story` row with
`is_engine_trusted=True` via a real filesystem-path import (`importlib.util
.spec_from_file_location`), since a game folder lives outside the Python package
tree. A game folder's own `.py` files are never imported at all until that trust
check passes.

### 7.2 `engine_services.py` — resolving one story's real bindings ✅ Built

`bindings_for(story, engine_state=None)` is the single function that branches on
`Story.is_engine_trusted`; every other module treats trust as already resolved.
Untrusted stories get `{}` — every `EXTERNAL` call falls back to the story's own Ink
fallback. A trusted story's own declared `StorySystemConfig` rows determine which
plugins actually contribute bindings — a plugin discovered on disk and globally
enabled in `EngineAPI` still contributes nothing to a story that hasn't opted into it.
For a stateful plugin, `bindings_for()` initializes that plugin's state inside the
caller's own `engine_state` dict on first use (`setdefault`), then asks the plugin to
bind its closures against that specific state — so two different players' sessions
for the same trusted story never share plugin state.

### 7.3 `engine_config_schemas.py` — validating plugin config, without eval ✅ Built

Hand-coded validator functions — never a JSON-Schema library, never `eval` or object
construction from the config — for each plugin's `StorySystemConfig.config` shape.
Each plugin's `EngineAPIDescriptor.validate_config` points directly at its own
function; there is no central dispatch-by-name table, since dispatch already happens
through `discover_api_descriptors()`.

### 7.4 `engine_plugins/` — the generic base plugins ✅ Built

Per the main design document's §1.8, each plugin is a plain, stateless-by-convention
module of dataclasses and functions, with no import of any sibling plugin:

- **`character_occupancy.py`** — evaluates a first-match-wins schedule (flags,
  time-of-day ranges, arbitrary story-defined rules) to determine which opaque
  location-id string a character currently occupies. Stateful: exposes
  `set_location_now`/`where_is_now`/`who_is_at_now` as real `EXTERNAL` bindings once a
  trusted story's session state is bound.
- **`location_graph.py`** — a plain reachability graph over opaque location IDs (which
  locations are known, which edges connect them). No concept of a character; no
  `EXTERNAL` bindings of its own — config-schema-only registration.
- **`scheduling.py`** — a minute-based clock (1440 minutes/day) and timed-event
  bookkeeping: `schedule_effect()`/`advance()`/`jump_clock()`, plus day-phase helpers
  (`is_morning`/`is_evening`/etc). Stateless bindings — no per-session state of its
  own.
- **`skills.py`** — a percentile roll-under skill-check mechanic, normalizing any
  0–max_level scale to 0–100, with its own independent RNG seed (deliberately
  separate from the interpreter's own story-level seeded RNG). Provides the mechanic
  as plain functions; unlike the other three plugins it does not register its own
  `EngineAPIDescriptor` — a game wanting skill checks writes its own game-specific
  wrapper (§7.5) that does the registering.

### 7.5 A game's own extension module ✅ Built (mechanism); per-game modules are content, not app code

A base plugin supplies the mechanic; a specific game's own module inside its own game
folder is what actually registers the `EXTERNAL` bindings that game's Ink content
calls — wrapping or extending a base plugin's behavior with whatever is specific to
that game (main design document §1.8). That module is discovered exactly the same way
as any other trusted game-folder Python file (§7.1) — there is no separate mechanism
for "the game's own API" versus "a generic plugin"; the distinction is only which
folder the module lives in and how general its `EngineAPIDescriptor` is.

### 7.6 Where each half's code and tests go — the checkable rule

Main design document §1.9 states the principle; this is the operational form of it,
restated here because it is the part most often forgotten when adding a capability.

**Every reusable capability is built as a pair:**

| | Engine half | Game half |
|---|---|---|
| Module | `interactive_fiction/engine_plugins/<name>.py` | `Albums/interactive_fiction/<game>/<name>.py` |
| Knows | opaque `character_id` / `item_id` / `location_id` strings, numbers, generic shapes | that game's real names, numbers, prose, rules |
| Owns | the mechanic | the catalog, the bindings, the `EngineAPIDescriptor` |
| **Tests** | **`interactive_fiction/tests/`** | **`Albums/interactive_fiction/<game>/tests/`** |

**Why the test split matters as much as the code split.** A test asserting "the mayor
is at city hall on weekday mornings" is a statement about that specific game's
content, not about the scheduling plugin. Filed in `interactive_fiction/tests/`, it
makes the engine's suite fail whenever a game's *story* changes — exactly the
coupling the plugin architecture exists to prevent. An engine test that needs a story
to exercise uses a fixture, never a real game's content.

**Two greps decide whether a capability is really split:**

```bash
# 1. Is any game's test filed with the engine's? (should be empty)
ls quickbbs/interactive_fiction/tests/ | grep -i "<game>"

# 2. Does the engine half name a game's facts anywhere -- executable code,
#    comments, or docstrings? No exclusions: a game's name has no
#    legitimate reason to appear in engine code at all, not even as a
#    path example -- write path examples with a placeholder like <game>.
python3 - <<'EOF'
import pathlib, re
GAME_NAME = "<game>"  # substitute the game folder's real name
for f in sorted(pathlib.Path('quickbbs/interactive_fiction/engine_plugins').glob('*.py')):
    src = f.read_text()
    for i, line in enumerate(src.splitlines(), 1):
        if re.search(re.escape(GAME_NAME), line, re.I):
            print(f'{f.name}:{i}: {line.strip()}')
EOF
```

Both should come back empty: no game-named test filed with the engine's, and no
game-name reference anywhere in an engine plugin's source — not in executable code,
not in a comment, not in a docstring's path example. If either check finds
something, either relocate the test to the game's own `tests/` directory, or
replace the game-specific mention with a generic placeholder.

---

## 8. Settings and infrastructure this app uses

All of the following are live in `quickbbs_settings.py` today:

```python
# Interactive Fiction
MAX_SAVE_SLOTS_PER_STORY = 5          # per-user cap on named save slots per story
MAX_SAVE_FILE_UPLOAD_BYTES = 2_000_000     # cap on an imported save-file upload
MAX_STORY_UPLOAD_BYTES = 20_000_000         # cap on an uploaded compiled story
SUPPORTED_INK_VERSIONS = (21,)               # inkVersion values the interpreter accepts
STORY_IMAGE_CONTENT_TYPES = {...}             # jpeg/png/gif/webp — no SVG
MAX_STORY_IMAGE_UPLOAD_BYTES = 8_000_000       # cap per uploaded/linked image
STORY_COVER_THUMB_SIZE = {"cover": (300, 300)}  # cover thumbnail size
MAX_TRANSCRIPT_TURNS = 200                       # rolling scrollback cap in CurrentGame.state
IF_SCAN_DEFAULT_OWNER = "if_librarian"            # scanner-ingested stories' owner account
IF_LIBRARY_ITEMS_PER_PAGE = 30                     # library pagination
```

`interactive_fiction` is registered in `INSTALLED_APPS`.

**Existing QuickBBS infrastructure this app reuses:**

- `send_file_response` + `sanitize_filename_for_http` (`frontend/serve_up.py`) — for
  save-file export downloads (a JSON attachment with a user-influenced filename,
  where the header-injection sanitizer matters).
- `FileIndex.inline_sendfile`/`async_inline_sendfile` and
  `ThumbnailFiles.send_thumbnail` — the actual serving path for story images/video and
  cover thumbnails, since a `StoryImage` is a reference into these tables, not a
  separate blob store.
- The thumbnail engine's in-memory entry points — for cover thumbnail generation at
  link time, without ever writing to disk first.
- `DirectoryIndex.search_for_directory()` / `files_in_dir()` — for resolving a game
  manifest's declared filenames to real `FileIndex` rows.
- `quickbbs.common.can_upload_story()` — the single shared predicate gating the
  upload form, so loosening it later (a per-user flag, a dedicated permission) is a
  one-line change rather than a hunt through view logic.
- Already installed, no work needed: **allauth** covers login/redirect behind every
  `login_required` gate this app uses; **grappelli** styles the admin registrations
  that already exist; **dbbackup** automatically covers these tables, no separate
  backup wiring required.

---

## 9. What's left

Work remaining, roughly in priority order:

1. **Save-compatibility repair.** A saved game can outlive the story it was saved
   against. Today a stale path degrades per the interpreter's general
   unresolvable-content handling (main design document §1.3) rather than being
   actively detected and recovered — the intended behavior (fall back to the nearest
   still-valid ancestor container, or to the story's start if nothing matches, always
   surfaced to the player) is designed but not implemented.
2. **`ref` parameters in the interpreter.** Ink's pass-by-reference function
   parameters are not implemented anywhere in `engine.py`. Not currently scheduled;
   would be new scope if ever prioritized.

Player conveniences already built (undo, restart, transcript, character creation) and
the core play/save/upload/ingestion loop are complete; the two items above are the
remaining known gaps, not a longer backlog.

---

## 10. Explicitly out of scope

| Item | Why |
|---|---|
| Server-side `.ink` → `.ink.json` compilation | Avoids a native compiler/runtime dependency on the server — see main design document §1.2 |
| Per-story analytics (choice popularity, completion rate) | Not requested |
| Group-based sharing | Considered and declined; `StoryAccess` grants individuals only |
| Multiple rendered sizes for inline story images | Inline images render at one size; only the cover image gets a generated thumbnail variant |
| Story favorites (library star toggle) | Left for later; would be a new model, not a reuse of the gallery's own unused `Favorites` stub |
| Transcript file download/export | The in-page scrollback is in scope; exporting it to a file is a later addition |
| Self-service sharing UI (add-user-by-username, grant list/revoke) | Admin-only grants |
| In-app story deletion | No delete route by design — unpublish or remove-from-disk are the lifecycle paths; hard deletion is a Django-admin-only action |
| Open (non-staff) story uploads | Upload is gated to a single `can_upload_story()` check, deliberately kept as one seam so it can be widened later without touching view logic |
| `ref` parameters in the interpreter | Not implemented in any build phase — see §9 |

---

## 11. Testing checklist

- [x] Interpreter validated against real compiled example stories, compared
      turn-by-turn against real Ink play-mode output
- [x] State serialization round-trips `InkRuntimeState` through
      `to_dict()`/`from_dict()` unchanged, including a LIST-valued variable
- [x] `CurrentGame` auto-updates every turn; saving copies it into a slot; loading a
      slot copies into `CurrentGame` without mutating the slot during subsequent play
- [x] Two browser tabs on the same story: a stale-tab submission is rejected with a
      "story has moved on" response, not silently applied
- [x] Library view under `AnonymousUser` returns public stories only and does not
      raise; play/save routes redirect an anonymous request to login
- [x] A game folder with a missing manifest, a `MAIN_STORY_FILE` mismatch, or invalid
      compiled content fails ingestion loudly (`game_ingestion_error` set, visible in
      admin), never silently skipped or partially created
- [x] `Story.is_engine_trusted` actually gates real Python dispatch: an untrusted
      story's `EXTERNAL` calls always run the in-story Ink fallback even when a
      matching plugin exists and is globally enabled
- [x] Engine/game split holds (§7.6): no `engine_plugins/` module names a specific
      game's facts, and no game-named test file sits in `interactive_fiction/tests/`
      — both checkable with one `grep` each, and clean as of 2026-08-27
- [x] A game's own extension module is only ever imported/executed once its story has
      been marked trusted, never before
- [ ] Save-compatibility repair: loading a slot against a story that was re-uploaded
      with a removed knot falls back to the nearest valid ancestor and tells the
      player, rather than silently degrading (§9, item 1 — not yet built)
- [x] Scanner ingestion: a game folder dropped into `Albums/interactive_fiction/`
      becomes a `Story` owned by `IF_SCAN_DEFAULT_OWNER`; removing its source file
      tombstones the story without cascading away existing saves
- [x] Undo restores the previous turn exactly (state and transcript entry both), one
      level deep — a second undo with no intervening choice is a no-op, not a second
      rollback

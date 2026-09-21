# interactive_fiction and QuickBBS — Design Document

**Version:** 2.0
**Author:** Benjamin Schollnick

**Date Created:** 2026-09-09  
**Last Updated:** 2026-09-20  
**Last Reviewed:** 2026-09-20

**See also:** [`interactive_fiction_implementation_guide.md`](interactive_fiction_implementation_guide.md)
for the step-by-step build plan, per-model field detail, and how-to instructions for
integrating a new Ink story into QuickBBS.

---

## 1. Guiding Principles

### 1.1 A player's turn must not depend on a running process

QuickBBS talks to a browser over ordinary stateless HTTP: a request arrives, a
response goes back, and nothing about the server remembers the player was ever there
until the next request. Spinning up a live interpreter process to compute one turn of
a story, then tearing it down, is wasteful for a single player and becomes a real
scaling problem once a site has many people playing at once — every turn would cost a
process start and stop, not just a computation.

- **The rule.** A story's entire runtime state — position in the story, variables, the
  eval stack, the call stack — is representable as plain data that survives between
  requests, not as a live object graph or a running process.
- **Consequence: Ink's compiled JSON format is the reason it was chosen over other
  interactive-fiction formats.** A compiled Ink story is already just data; the
  interpreter's job is to read that data, read a small saved-state dict, compute one
  turn, and write a new state dict back — a computation, not a session. Formats whose
  runtime model assumes a live process or a persistent in-browser session (a
  Ren'Py-style render loop, a Twine story whose state lives in `localStorage`, a
  Z-machine interpreter that expects a long-lived terminal session) don't fit this
  structure without working against it.
- **Consequence: one request in, one response out.** Playing a turn is read state →
  compute → write state, the same sequence as any other QuickBBS view that reads a row,
  does work, and saves it back — not a special case requiring its own process
  management, worker pool, or session affinity.

### 1.2 No dependency on an interpreter that can go unmaintained out from under the site

Python interactive-fiction ports exist, but none was safe to depend on: the most
visible port on PyPI was archived, and smaller forks are low-activity and unverified.
A gallery application taking a hard runtime dependency on an abandoned package is a
liability that surfaces later, at the worst time — when a security fix or a Python
version bump is needed and the dependency has had no commits in years.

- **The rule.** The interpreter is written against Ink's own documented compiled-JSON
  runtime format — the same format the official C# and JavaScript reference runtimes
  read — not against, or wrapping, any third-party Python port.
- **Consequence: this cost more to build than a straight-branching-only interpreter
  would have.** Supporting Ink's full call-stack feature set (tunnels, functions,
  threads, LISTs, sequences/cycles/shuffles with a seeded RNG) instead of only linear
  branching pushed the build well past what a small script would need. That cost was
  accepted deliberately, in exchange for owning an implementation with no
  third-party Ink runtime behind it, fitting QuickBBS's specific integration
  needs — turn-by-turn state serialization
  mid-story binding of application functions on QuickBBS's own terms rather than a third-party
  port's assumptions about how it would be embedded.
- **Consequence: the server never runs a compiler.** Authors compile `.ink` source to
  JSON offline, using Inky or the `inklecate` command-line tool; QuickBBS only ever
  reads the compiled output. There is no `.NET`/Mono runtime dependency, no subprocess
  execution surface, on the server itself.

### 1.3 An unimplemented or malformed construct degrades the turn, never the request

A compiled story can contain constructs the interpreter doesn't yet implement (an
Ink feature scheduled for a later build phase) or, in principle, malformed content.
Either way, one broken passage in one story must not take down the request serving
it — a player mid-story should see a passage that silently skipped something it
doesn't understand yet, at worst, never an unhandled exception.

- **The rule.** A recognized-but-unimplemented construct is consumed as a no-op or
  falls back to a safe default; a value the interpreter can't act on (a missing
  operand, an out-of-range index) degrades to a default rather than raising. The same
  discipline extends to a saved-state path that no longer resolves against a changed
  story — `InkRuntimeState.from_dict()` drops what it cannot recover (an unresolvable
  call-stack return address, for instance) rather than raising.
- **Consequence: correctness bugs and scope gaps look different in the code.** A
  genuine defect in an implemented feature is fixed at the root cause. A construct
  outside the interpreter's current scope degrades gracefully by design, and stays
  that way until the section of work that implements it lands — the two are never
  conflated by silently swallowing an error that should have been a real fix.
- **Consequence: this must be verified against real content, not assumed.** Whether a
  given construct actually degrades safely — rather than crashing — is only proven by
  running the interpreter against real compiled stories, not by reasoning about the
  code in isolation. The interpreter's test suite includes differential tests that
  compare its output turn-by-turn against real Ink play transcripts, including for a
  large, previously hand-authored story converted into Ink specifically to exercise
  this — hand-authored fixtures alone cover only what their author thought to test.

### 1.4 A silent wrong answer is worse than a stopped turn

Section 1.3 says an unimplemented construct degrades rather than raising. That is right for
a construct the interpreter does not understand, and wrong for a fact the story got
wrong: degrading a bad value produces an answer that is confidently incorrect, and
the player has no way to tell.

- **The rule.** Where a system can distinguish "I do not know" from "this is wrong",
  the wrong case is loud. Placing a character at a location the story never declared
  raises rather than storing it; a story that declares no map at all is simply not
  checked, because there the system genuinely does not know.
- **Each write path is checked separately.** The check runs only when the caller
  passes the declared vocabulary to compare against, and that argument is optional so
  that a story with no map still works. A caller that omits it stores whatever it was
  given. So "a bad location raises" describes the write paths that pass the
  vocabulary, not the system as a whole — every path that can store a value needs it.
- **Why this is not Section 1.3 inverted.** The distinguishing question is whether a plausible
  answer exists. An unimplemented Ink construct has an obvious safe reading — skip it —
  and skipping is visible in the prose. A mistyped location id has no safe reading:
  the store accepts any string, so every later symptom is an empty presence list or a
  false "is X here", each identical to the character legitimately being elsewhere. The
  content gated on that presence simply never appears, for the rest of the playthrough,
  with nothing logged.
- **Consequence: a system that cannot answer must not answer cheaply.** When a cost
  table is present but not yet configured, its lookup returns a price nothing can
  afford rather than zero. Zero is a plausible-looking answer that silently deletes a
  game's resource economy; an unaffordable price closes the choices it guards, which
  a player and an author both notice immediately.
- **Consequence: this is checked at the write, not the read.** A wrong value is
  attributable only at the moment it is stored — afterwards it is indistinguishable
  from a legitimate one, and the code that suffers is somewhere else entirely.

### 1.5 Crash-safety and player intent are different problems, not one feature

Losing progress because a browser tab closed is a different failure than a player
wanting to preserve a specific moment on purpose ("save right before the big
decision"). Solving both with one mechanism forces a bad tradeoff: autosaving into
slots means the player can't fully trust that a slot still holds what they meant
it to, breaking the SAVE/RESTORE expectation every interactive-fiction player already
has; slots alone mean any interruption before the player remembers to save loses
everything since the last explicit save.

- **The rule.** The in-flight game state is auto-saved on every turn, independent of
  and never overwriting the player's own named save slots. Slots only change when the
  player explicitly saves or loads.
- **Consequence: closing the browser never loses more than the choice in flight.** The
  auto-saved state (`CurrentGame`) is always current as of the last completed turn —
  there is no separate "did you remember to save" step for ordinary interruption.
- **Consequence: a named slot means exactly what the player put there.** Nothing
  else — not autosave, not a background process — ever writes into a `SaveState` slot
  the player didn't explicitly save to.

### 1.6 Access control is designed fresh, not retrofitted onto placeholders

QuickBBS has two existing model stubs that gesture at a permissions system —
`Owners` and `Favorites` — but neither has any sharing logic implemented; they are
unused placeholders, not a working foundation. There was nothing usable to extend.

- **The rule.** `interactive_fiction` defines its own owner/public/specific-user
  access model, scoped to this app, rather than building out or routing through the
  existing stubs.
- **Consequence: the access model here is not a precedent QuickBBS-wide.** It solves
  sharing for stories specifically; a future general permissions system for the rest
  of the gallery, if one is ever built, is a separate undertaking that this app's
  model does not attempt to anticipate.

### 1.7 Leverage the gallery's existing infrastructure rather than inventing a parallel one

A story is itself a gallery-visible thing — a game's compiled `.inkj` file, and any
image or video it references, already has an entry in the gallery like any other
scanned file. It follows that a story's assets should draw on infrastructure the
gallery already has (the `FileIndex`/`DirectoryIndex` tables, the thumbnail
decode/verify/resize pipeline, blob serving through the existing streaming path)
rather than the app inventing a second, parallel mechanism for what is structurally
the same problem QuickBBS already solved once.

- **The rule.** A story never stores its own copy of image or video bytes. A story
  image is a mapping row (`StoryImage`) pointing at a real, already-scanned
  `FileIndex` row — the same file the gallery's own browsing views would show for that
  path — not a second copy of the content.
- **Consequence: this design point was reached by building the alternative first and
  proving it unnecessary, not by reasoning it out in advance.** An earlier iteration
  gave `interactive_fiction` its own content-addressed blob table (mirroring
  `ThumbnailFiles`'s field layout) so story images could be evaluated end-to-end without
  waiting on the rest of the gallery's ingestion path to be ready. Once that path was
  proven — a story's images are ordinary files under `Albums/`, scanned and tracked by
  the gallery exactly like everything else — the blob table was redundant with what
  `FileIndex` already provided, and was removed rather than kept alongside it.
- **Consequence: story content is anchored to tracked gallery files, not floating
  copies.** A story's main compiled file, and every image/video it references, has to
  already be a scanned `FileIndex` row before a `Story` can reference it — ingestion
  fails loudly, naming the missing file, rather than accepting an untracked path.

### 1.8 A story's engine-level logic runs as trusted Python only on explicit, per-story authorization

Ink's `EXTERNAL` declarations let a story call out to functions the application provides.
QuickBBS can bind real Python behind an `EXTERNAL` call — but a game folder lives in
the same `Albums/` tree as any other user-suppliable gallery content, and a game
folder's own manifest is data an uploader controls, not a decision an administrator
has made.

- **The rule.** Real Python code — whether the generic reusable plugins under
  `engine_plugins/`, or a game's own extension module living in its own folder — is
  only ever dispatched to for a story whose `Story.is_engine_trusted` flag has been
  set, a decision made by an administrator in Django admin and never exposed on any
  user-facing upload or edit form. A story's manifest can *declare* which plugins it
  wants; declaring is not the same as being granted the ability to execute code, and a
  story that isn't trusted still plays correctly, falling back to each `EXTERNAL`
  call's compiled-in Ink fallback function.
- **Consequence: config discovery and code execution are deliberately different
  steps.** Finding out what plugins exist, and validating a story's declared
  configuration against a plugin's schema, is safe to do unconditionally — none of it
  runs the story's or the plugin's own code as a side effect beyond parsing. Actually
  calling into a plugin's Python during play is the one step gated on trust, because
  it is the one step where a story exerts real influence over server-side execution.
- **Consequence: trust is a record of a human decision, not an inference from
  content.** Nothing about a story's declared manifest, its content, or how it was
  ingested (upload form vs. scanner) automatically grants trust. An administrator
  flipping the flag is the only path — the flag exists specifically so there is always
  a concrete answer to "who approved this story to run code, and when."

### 1.9 Reusable engine capabilities are generic building blocks, extended per game, not one-size-fits-all systems

Different stories that need scheduling, location tracking, or skill checks tend to
need *similar* behavior, but rarely *identical* behavior — one game's idea of "which
characters are diegetically present right now" is shaped by that game's own content
in ways a single hard-coded system can't anticipate for every future story.

- **The rule.** `engine_plugins/` provides base mechanics — schedule evaluation,
  location-graph reachability, timed-event bookkeeping, a percentile skill-check
  roll — as plain, stateless-by-convention functions and dataclasses, deliberately
  decoupled from each other (no plugin imports another plugin's internal types). A
  game that needs more than the base mechanic supplies writes its own extension module
  inside its own game folder, wrapping or extending a base plugin's behavior with
  whatever is specific to that story; that game-specific module is what the story's
  Ink content actually binds `EXTERNAL` calls to, discovered the same way any other
  trusted game-folder module is.
- **Consequence: a base plugin never has to anticipate every game that might use
  it.** Because a game's own extension module is a normal, separately-discoverable
  unit rather than a required subclass or config override baked into the base plugin,
  adding support for one story's particular needs never requires changing
  `engine_plugins/` itself, and never risks breaking a different story already
  depending on that plugin's current interface.
- **Consequence: a plugin depends on another only where the concept genuinely
  requires it, and then in one direction.** Location tracking has no concept of a
  character, and a game wanting only a map never adopts occupancy. The reverse is not
  symmetric: "who is at which location" presupposes a set of locations, so
  character-occupancy reads the map's declared vocabulary and refuses to place anyone
  at a location the story never declared. That dependency is expressed as an ordinary
  state-slot read, not an import — occupancy still has no `location_graph` type in its
  signatures, and a story that declares no map is simply unchecked rather than broken.

  **A check a caller can skip is a check some write path does not get.** The
  vocabulary is passed as a parameter that defaults to "do not check", which is what
  lets a mapless story work at all. The Ink-facing binding passes it; a game's own
  Python code calling the placement API directly is a second write path, and if it
  omits the parameter that path is unchecked. Nothing warns, and the id is stored.
  When a plugin's guard is opt-in, the design owes an answer for every caller, not
  just the one the engine ships.

  The distinction matters because the symmetric reading is wrong in a way that looks
  right: read as "occupancy must not consult the map", it leaves a mistyped location id
  silently accepted, and every later symptom — an empty presence list, a False
  "is X here" — is indistinguishable from the character legitimately being elsewhere.
  Independence is about not FORCING a plugin on a game, not about refusing to check a
  fact the game already declared.

### 1.10 Every capability has two halves, and a test lives with the half it tests

Section 1.9 establishes that engine plugins are generic and games extend them. That split
is easy to state and easy to erode: a single game-specific fact compiled into a base
plugin, or one game-specific test filed with the engine's, and the boundary stops
being real. This principle names the split explicitly and says where each half's
code and tests live, because it is the thing most often forgotten when a new
capability is added.

- **The rule — two halves, always.** A reusable capability is built as a pair:

  | | Engine half | Game half |
  |---|---|---|
  | Lives in | `ink_engine`'s `engine_plugins/<name>.py` | `Albums/interactive_fiction/<game>/<name>.py` |
  | Knows | opaque id strings, numbers, generic data shapes | that game's real names, numbers, prose, and rules |
  | Never contains | any specific story's facts | anything another game would also need |
  | Tests live in | `interactive_fiction/tests/` | `Albums/interactive_fiction/<game>/tests/` |

- **The engine half knows no story.** It handles `character_id`, `item_id`,
  `location_id` as opaque strings and never learns what any of them mean. If a
  reviewer can tell which game a plugin was written for by reading it, the split has
  already failed.
- **The game half is where every real fact lives** — the item catalog, the prices,
  the schedules, the skill names, the starting placements, the `EXTERNAL` bindings
  the story's Ink actually calls, and the `Plugin` that registers them.

  Opacity has a price the game half pays: because ids are compared as strings,
  the engine cannot tell that two of them name one room. Presence answers "is
  this the same string", not "is this the same place", so a room with a second
  id is a second room, and a character placed at one is invisible to a player
  standing in the other. Nothing raises, and the symptom is indistinguishable
  from the character legitimately being elsewhere. Keeping one id per place is
  the game half's job and is worth a test of its own.
- **Consequence: tests follow their half, and the directory is the assertion.** An
  engine test that needs a story to exercise is written against a fixture, not
  against a real game's content; a test that asserts "the mayor is at city hall on
  weekday mornings" is a statement about that specific game and belongs with that
  game. Filing a game-specific test in `interactive_fiction/tests/` makes the
  engine's suite fail when a game's *content* changes, which is exactly the coupling
  this split exists to prevent.
- **Consequence: the boundary is checkable, not just intended.** "Does
  `interactive_fiction/tests/` contain a test named after a game?" and "does
  `engine_plugins/<name>.py` name a game's facts in executable code?" are both
  mechanical checks (implementation guide Section 7.6 gives the exact commands). A
  capability that cannot pass them has not been split, whatever its module layout
  suggests. Note the second check must ignore comments and docstrings: those
  legitimately cite plan filenames and give a game-folder path as an example, and a
  naive `grep` flags them as violations when nothing is wrong.

---

## 2. Purpose

`interactive_fiction` is a QuickBBS app that lets users play Ink-authored interactive
fiction games inside the gallery. It owns:

- **A from-scratch Ink interpreter** (`engine.py`) — reads compiled Ink JSON, walks
  the story's container/instruction tree, and advances one turn at a time, without any
  third-party Ink runtime dependency.
- **Story records** (`Story`) — the compiled JSON plus ownership, visibility, engine
  trust, and game-manifest metadata (author, required plugins, character-creation
  field definitions).
- **A fresh owner/public/specific-user access model** (`StoryAccess`,
  `user_can_access()`) — QuickBBS has no working precedent for this to extend (Section 1.6).
- **Player progress**, split between an always-current auto-saved state
  (`CurrentGame`) and explicit, player-controlled save slots (`SaveState`) (Section 1.5).
- **Story images and video**, referenced by custom Ink tags and resolved to the
  gallery's own tracked `FileIndex` rows (Section 1.7).
- **A discoverable plugin/trust system** (`engine_api.py`, `engine_services.py`
  here; the generic plugins themselves in `ink_engine`) — reusable
  engine-level building blocks a trusted story can extend with its own
  game-specific logic (Section 1.8, Section 1.9).

A game becomes playable one of two ways: an author uploads its compiled JSON through
a form, or its game folder — a directory under `Albums/interactive_fiction/`
containing a manifest and a compiled `.inkj` file — is scanned by the gallery's
existing scan infrastructure the same way any other gallery content is, or picked up
live the first time its directory is browsed.

---

## 3. High-Level Architecture

```
Author's machine (offline)
  Inky editor / inklecate CLI
        │  compiles .ink source
        ▼
  story.ink.json  ──────────────┐
                                 │
                                 │  (A) upload form         (B) game folder under
                                 │      can_upload_story()      Albums/interactive_fiction/
                                 │      gated                   __init__.py + .inkj
                                 ▼                                       │
                    story_views.upload()                  scan_if_stories / live scan
                    validate_story_upload()                 ingestion.ingest_stories()
                                 │                           ingestion.verify_stories()
                                 └──────────────┬────────────────────────┘
                                                 ▼
                                     Story.compiled_json (JSONField)
                          Story.is_engine_trusted (admin-only decision)
                                                 │
              ┌──────────────────────┬───────────┴───────────┬──────────────────────┐
              ▼                      ▼                       ▼                      ▼
    interactive_fiction     interactive_fiction     interactive_fiction    interactive_fiction
    models.py                 engine.py               engine_api.py         views.py /
    Story / StoryAccess       InkRuntimeState          discover_api_        story_views.py /
    user_can_access()         load_story_root()        descriptors()        save_views.py
                               continue_story()/                                  │
                               choose()                        │                  │
                                    ▲                           ▼                  │
                                    │             engine_services.bindings_for()   │
                                    │             (trust-gated EXTERNAL binding)   │
                                    │  reads/writes                    │           │
                                    └──────────────  CurrentGame.state (JSONField) ┘
                                                      SaveState.state (named slots)
```

Playing a turn is: load `Story.compiled_json` → resolve this story's real EXTERNAL
bindings via `engine_services.bindings_for()` (trust-gated per Section 1.8) → rehydrate an
`InkRuntimeState` from the player's saved state dict → advance one step → serialize
the new state back. No step in that path holds a long-lived process open between
requests (Section 1.1).

---

## 4. What's built today

The interpreter (`interactive_fiction/engine.py`) is implemented through the
container/path model, output-stream assembly (text, glue, whitespace), diverts and
choices (including conditional visibility and once-only/sticky pruning), variables
and the full arithmetic/comparison/logic/string operator set, tunnels, functions and
threads, LIST values with their complete operator family, sequences/cycles/shuffles
backed by a seeded RNG port, the remaining visit-count/turn-count/tag operations,
`EXTERNAL` function dispatch to the application's real bindings (falling back to a story's own Ink
fallback when no binding is provided or the story isn't trusted), and full
`to_dict()`/`from_dict()` state serialization — a saved game round-trips through plain
JSON, including a call frame mid-tunnel or mid-function-call and every transient
mid-eval-run flag needed to resume correctly. It is validated against real
`inklecate`-compiled output and real `inklecate`/`inkjs` play transcripts, not only
hand-authored test fixtures (Section 1.3) — the project's standing rule is that an algorithm
this central is checked against real data before being trusted, not spot-checked.

Beyond the interpreter, the full play loop is built: routes are wired and
access-gated, the library view lists accessible games for real, and play, undo,
restart, character creation, save/load/export/import, upload, edit, and image/video
serving are all real, working views — not stubs. A trust-gated plugin/discovery
system (`engine_api.py` and `engine_services.py` here, over `ink_engine`'s own
plugins) lets a game extend
the interpreter with real Python for scheduling, location tracking, character
occupancy, and skill checks, each a generic base a trusted game's own extension module
can wrap. Story images and video are anchored to the gallery's own `FileIndex` rows,
never a separate copy.

Not yet built: **save-compatibility repair.** A saved game can outlive the story it
was saved against (an author re-uploads a revised version, or a scanner-ingested file
changes on disk); today, a stale saved path that no longer resolves degrades per
`InkRuntimeState.from_dict()`'s general unresolvable-content handling (Section 1.3) rather
than being detected and actively recovered to the nearest still-valid point. See the
companion implementation guide for exact status and the build order for what's left.

---

## 5. Caveats and constraints

- **No server-side compilation, ever.** QuickBBS never shells out to `inklecate` or
  any compiler. An author who wants to change a story recompiles offline and
  re-uploads or replaces the file in `Albums/`.
- **`EXTERNAL` functions only reach real Python for a trusted story.** Every game's
  Ink content must declare a same-named in-story fallback function for any `EXTERNAL`
  it calls — validated at ingestion time, so a story with an unbound `EXTERNAL` is
  rejected outright, naming the missing function(s), rather than accepted and left to
  fail mid-play. For an untrusted story that fallback is always what runs; for a
  trusted story, a real Python binding runs instead when one is registered for that
  call (Section 1.8).
- **A saved game can outlive the story it was saved against.** Today this degrades
  per the interpreter's general unresolvable-content handling (Section 1.3) — the intended
  active repair (recovering to the nearest still-valid ancestor container, always
  surfaced to the player, never a silent broken state) is designed but not yet built;
  see the implementation guide.
- **`ref` parameters (pass-by-reference function arguments) are out of scope.** No
  section of the interpreter's build implements Ink's `ref` keyword. A story whose
  logic depends on a function mutating the caller's variable through a `ref`
  parameter will silently operate on a local copy instead — usually harmless, but
  capable of producing a loop that runs far longer than intended if the story's logic
  assumes the mutation actually happened. There is no scheduled section to add `ref`
  support; it would be new scope if ever prioritized.
- **The story JSON is trusted input once uploaded, not sandboxed at runtime.** Upload
  and scanner-ingestion validation reject anything that doesn't parse as compiled Ink
  and anything with an unbound `EXTERNAL`, but the interpreter does not run compiled
  stories in any kind of resource-limited sandbox — a pathological or malicious
  compiled story could, in principle, run for a very long time inside a single
  request. Upload is gated to a single shared predicate
  (`quickbbs.common.can_upload_story`), deliberately kept as one seam so it can be
  loosened later without touching view logic.
- **A game folder's manifest is parsed, never executed, until trust is granted.**
  `ingestion.py` reads a game folder's `__init__.py` manifest via `ast.literal_eval`
  on its top-level assignments, specifically because that file lives in the same
  untrusted `Albums/` tree as any other user-suppliable content and must be readable
  before any `Story` row exists to grant it trust. Only once `Story.is_engine_trusted`
  is set does the game folder's own Python modules ever actually get imported and run
  (Section 1.7).
- **Story images and video, once linked, are a stored-content surface, not a trusted
  one.** They are served back to other users under the site's own origin through the
  gallery's existing serving path, subject to the same content-type and serving
  precautions QuickBBS already applies to any user-supplied binary content.

---

## 6. Module structure

```
interactive_fiction/                  # THIS repo's Django app. The Ink
                                      # interpreter and the generic plugins
                                      # live in the separate ink_engine
                                      # repository, not here.
    __init__.py
    apps.py
    models.py            # Story, StoryAccess, EngineAPI, CurrentGame,
                          # SaveState, user_can_access(), sync_engine_apis()
    engine_api.py          # discover_api_descriptors() — wraps the engine's
                            # discover_plugins() with this application's
                            # trust gate and caching
    engine_services.py      # bindings_for() — the single call site that branches
                             # on Story.is_engine_trusted to assemble a story's
                             # real EXTERNAL bindings
    ingestion.py            # Game-folder discovery, manifest parsing, and
                             # Story creation/drift-verification, anchored to
                             # the gallery's own DirectoryIndex/FileIndex
    images.py                # Resolves an image/video tag to a real FileIndex row
    bundle_media.py           # media served out of a bundled game
    game_saves_database.py     # the database-backed game-saves store
    story_markup.py             # story text to HTML
    signals.py                   # cache invalidation on Story save
    views.py                  # library(), play(), play_submit(), play_undo(),
                               # play_restart(), character_creation(...),
                               # preferences(), and the shared engine-state
                               # plumbing story_views.py/save_views.py import
    story_views.py              # story_image()/story_video()/story_cover(),
                                 # upload(), edit(), and upload/edit validation
    save_views.py                # saves(), saves_save()/saves_load(),
                                  # saves_export()/saves_import()
    panel_views.py                # the game-panel command API
    urls.py                       # all routes registered under the "if/" prefix
    admin.py                       # Story, StoryAccess, EngineAPI,
                                    # CurrentGame, SaveState
    management/commands/
        scan_if_stories.py          # scanner-ingestion entry point: walks
                                     # Albums/interactive_fiction/, verifies then
                                     # ingests, then syncs discovered plugins
        playthrough_harness.py       # scripted playthrough for content checking
    migrations/
    templates/interactive_fiction/
    tests/                            # THIS application's tests. The interpreter's
                                      # own test suite lives in ink_engine.
        test_engine_api.py             # plugin discovery
        test_engine_trust_gate.py       # the trust gate
        test_ingestion.py                # game-folder ingestion and drift
        test_bundle_*.py                  # bundled-game ingestion, integrity,
                                           # media, serving
        test_character_creation.py         # initial-globals seeding
        test_game_saves_database.py         # the database-backed saves store
        test_story_markup.py                 # story text to HTML
        test_views.py                         # routes and access gating
```

**Engine tests only.** Every file above tests the engine half, against
fixtures rather than any real game's content (Section 1.9). A test that asserts
something about a particular story's characters, items, or schedule does
not belong here — it belongs beside that game.

The game half lives outside the app entirely, in the gallery tree:

```
Albums/interactive_fiction/<game>/
    __init__.py           # the manifest: GAME_TITLE, REQUIRED_PLUGINS,
                           # MAIN_STORY_FILE, NEW_GAME_FIELDS, ...
    <story>.inkj           # the compiled story the engine actually runs
    *.ink                   # the story source
    <capability>.py          # this game's half of each engine plugin --
                              # e.g. skills.py, occupancy.py, locations.py,
                              # scheduling.py: the real names, numbers and
                              # rules, plus the EXTERNAL bindings and the
                              # Plugin that registers them
    image_mapping.py           # game data, read AST-only by image_linking
    tests/                      # THIS GAME's tests -- content assertions,
        conftest.py              # binding behaviour, schedule fidelity.
        <game>_test_utils.py      # Never in interactive_fiction/tests/.
        test_<game>_*.py
```

The split is real and clean: the engine's own test directory contains no
game-specific test, and no engine test imports a game module. That is the
state to preserve.

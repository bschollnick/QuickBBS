# Design Documents — Authoring Guideline

**Version:** 1.12  
**Author:** Benjamin Schollnick  
**Last Updated:** 2026-08-07

---

## 0. What this document is

A template and style guide for the design documents in this folder, derived from the
v4.11 rewrite of `frontend_design.md` and the v4.x rewrite of `quickbbs_app_design.md`.
It exists so the next document does not have to rediscover the same conventions by
trial and error.

Two things to keep in mind before writing anything:

- **A design document is not release notes.** It describes the app as it stands and why
  it is shaped that way. It does not track what changed in which version, list known
  bugs, or maintain a cleanup backlog. Those belong in commit history, issues, or
  `claude_docs/`.
- **Never reference or link to a Claude plan document.** No `See claude_docs/plans/...`,
  no bare mention of a plan filename. Plans in `claude_docs/plans/` are working
  artifacts for an AI coding session, not durable references — they can be edited,
  moved, or deleted independently of the design doc, and a reader without access to
  that directory shouldn't hit a dead pointer. If a plan's reasoning matters to the
  design, restate the reasoning in the design doc's own prose instead of citing where
  it came from.
- **The document is written against the code, not against the previous document.** Read
  the current source before revising. Every section is a claim about how the code behaves
  right now, and each one should be verifiable by opening the file it describes.
- **Don't defend against criticism nobody made.** A sentence that exists only to rule
  out an interpretation no reader would arrive at unprompted — "not a response to a
  diagnosed failure," "no leak has actually been confirmed," "not a fix for a
  diagnosed one" — plants the very doubt it's trying to dispel by naming the
  hypothetical failure in order to deny it. State what the mechanism does and on what
  schedule or condition. If there's a real, specific concern it addresses, say that
  concern plainly as a fact, not as a rebuttal.

**Mandatory: this is an interactive process, not a solo drafting exercise.** The code and
its comments tell you *what* the app does; they rarely tell you *why* it was built that
way instead of some other way. That "why" only exists in the author's head. Do not guess
it, and do not infer it silently from the code and move on — **ask**. §2.7 below covers
this in detail for §1 specifically, but the instruction is general: whenever you are
about to state a reason, a motivation, a rejected alternative, or an intended audience,
and you are not certain of it, stop and ask the author rather than writing your best
guess. A design document built on inferred rationale is not a design document — it is a
guess wearing the format of one.

---

## 1. Standard structure

The section order below is the template. Sections may be dropped when an app genuinely
has nothing to say under them, but do not reorder or renumber — the sequence carries
meaning, moving from *why* to *what* to *how*.

| § | Section | Purpose |
|---|---|---|
| — | Title block | Name, version, author, date |
| 1 | **Guiding Principles** | Why the app is shaped this way. Design rationale only. |
| 2 | **Purpose** | What the app is and what it owns |
| 3 | **High-Level Architecture** | ASCII call/flow diagram |
| 4 | **Component Reference** | Per-module, per-function detail — the bulk of the document |
| 5 | *Concurrency / runtime strategy* | Only if the app has a non-obvious execution model |
| 6 | *Caching Architecture* | Table of every cache, if the app caches |
| 7 | *Domain-specific mechanism* | e.g. template selection, filetype resolution |
| 8 | *Key flow walkthrough* | One important end-to-end path, in detail |
| 9 | **Module Structure Summary** | Annotated file tree |
| 10 | **Future Ideas** | Uncommitted directions, with their tensions |

Sections 1–4, 9, and 10 are the load-bearing ones. Sections 5–8 are slots for whatever
that particular app actually needs; number them in sequence and title them for the app.

Separate top-level sections with `---` on its own line.

### 1.1 Companion ERD file

If an app owns one or more Django models (has a `models.py`, or model classes living
in another module the app owns — `quickbbs` splits its models across
`directoryindex.py` and `fileindex.py`, for example), it gets a companion
`<app>_erd.md` file in the same directory: `quickbbs_erd.md`, `frontend_erd.md`,
`cache_watcher_erd.md`, and so on. This is a **separate file**, not a section inside
the main design document — the ERD is a diagram artifact with its own update cadence
(it changes on schema migrations, not on prose rewrites), and keeping it out-of-line
means a schema change doesn't force a re-read of the whole design doc.

- **Title block:** name, "Companion to: `<app>_design.md`" (or "N/A" if no standalone
  design doc exists for that app yet), author, date — same discipline as the main
  document's title block (§9).
- **A Mermaid `erDiagram` block**, not ASCII. This is the one exception to §3's "ASCII
  diagram" rule for architecture — ERDs are a standard notation Mermaid supports
  natively, and forcing box-drawing characters to approximate crow's-foot notation is
  a worse diagram, not a more consistent one.
- **Every field, FK, and cardinality must be verified against the actual model
  source**, the same accuracy discipline as §4.4 — an ERD with a wrong `on_delete`
  behavior or a missing field is actively misleading in a way prose rarely is, because
  a diagram reads as more authoritative than it may actually be.
- **A "Reading the diagram" section below the diagram**, in prose, calling out what
  isn't obvious from the boxes and arrows alone: which relationships are enforced by
  the database (a real FK) versus joined by matching value (a shared hash column, no
  FK) versus a bare function call across app boundaries (no schema relationship at
  all). A diagram that only shows the boxes and arrows leaves the reader to guess which
  kind of "relationship" each line represents — say so explicitly.
- An app that owns no models (like `frontend`) still gets an ERD file, but its diagram
  shows what it *consumes* from other apps' models rather than anything it owns —
  state that plainly in the file's own "What this is" preamble so a reader doesn't go
  looking for a `models.py` that doesn't exist.
- **Attribute-block syntax is stricter than it looks — verify it renders.** Every line
  inside an entity's `{ }` block must be `<type> <name> [PK|FK|UK] ["comment"]`, in
  that order. `FK fieldname "comment"` is invalid — Mermaid parses the first token as
  the *type*, and `FK`/`PK` are only valid in the constraint slot, not the type slot.
  Use the FK column's real type (Django FK columns are `int` unless the field is a
  string-keyed FK like `filetypes.filetype`, which is `string`), then the field's
  `_id`-suffixed column name, then `FK`, then the comment: `int home_directory_id FK
  "-> DirectoryIndex, nullable"`. Render-check every ERD after writing it — a subtle
  syntax error here fails silently as a parse error at view time, not at write time,
  so "I wrote it following the pattern" is not the same as "I confirmed it parses."

### 1.2 System-level dependency diagram, not an ERD

One additional file, `high_level_dependency_diagram.md`, sits above all the per-app
ERDs — but it is deliberately **not** an ERD, and should not be forced into
`erDiagram` syntax. The connections between apps are a mix of real foreign keys,
hash/value-based joins with no FK, and plain function calls across app boundaries;
entity-relationship notation has no vocabulary for that third kind, and stretching
`erDiagram`'s entity-attribute blocks to represent "an app has these models" (rather
than "a table has these columns") produces attribute lines with no real column behind
them — a diagram that looks precise while describing something that isn't actually
schema.

Use a Mermaid **flowchart** (`graph TD`) instead: one node per app, one labeled edge
per dependency, with the edge label naming the dependency kind (real FK, value-match
join, function call) explicitly rather than relying on arrow style alone to carry that
distinction — a solid-vs-dashed convention can flag "enforced by the database" versus
"not," but reserve the actual kind (FK vs. hash-join vs. call) for the label text or
the prose below the diagram, not for a third arrow style that becomes unreadable at
this scale.

Verify every edge by checking cross-app imports (`from quickbbs...`, `from
frontend...`, etc.) across the whole codebase — not by combining the per-app ERDs,
which show ownership within an app but not which other apps reach into it.

**Flowchart node/class names collide with Mermaid keywords silently.** `classDef call
...`, or a node literally named `end`, `class`, `click`, or `subgraph`, breaks the
parser with an error that doesn't point at the actual reserved word — it surfaces as a
generic token-expectation error several lines later. If a `classDef` isn't actually
applied to any node with `:::classname`, delete it rather than leave dead styling code
that's just another way for this to break — a legend in prose below the diagram covers
the same ground without the risk. Render-check the diagram after writing it; don't
assume valid-looking Mermaid syntax renders just because it matches a pattern seen
elsewhere.

### 1.3 Reference something, link to it

**A named thing the reader might want to jump to gets a markdown link, not a bare
mention.** This applies everywhere, not just ERDs — but it's the ERD/dependency-diagram
files where it matters most, since their entire content is cross-references to other
files and other apps. If a sentence says "see `frontend_erd.md`," that's a link, not a
code-formatted filename sitting next to the word "see." If a sentence names an app that
has its own design doc or ERD (`` `frontend` ``, `` `cache_watcher` ``), the *first*
mention of that app in a given paragraph links to the relevant file. If a sentence names
a specific model (`` `CacheStatisticsTracking` ``, `` `DirectoryIndex` ``), it links to
where that model is actually defined and documented — the `#### Fields` heading or
`### 4.N` module heading in the owning app's design doc, not just the file as a whole,
when such a heading exists. The reader should never have to leave the sentence they're
reading, go search a filename or model name by hand, and come back — that defeats the
purpose of writing a cross-referenced document at all.

- **Link on first mention per paragraph**, not every repetition — re-linking
  `` `DirectoryIndex` `` five times in one paragraph is noise, not help. A later mention
  in a different paragraph or section gets linked again, since a reader may have
  arrived there directly (a search result, a table of contents jump) without having
  read the earlier paragraph.
- **Link to the most specific anchor that exists.** `[`DirectoryIndex`](quickbbs_app_design.md#42-directoryindexpy--directoryindex)`
  beats `[`DirectoryIndex`](quickbbs_app_design.md)` when the heading exists — a bare
  file link forces the reader to skim the whole file for the one relevant heading,
  which is the same problem this rule exists to solve, one level up.
- **Verify the anchor resolves** before relying on it — most renderers slugify a
  heading by lowercasing it, stripping punctuation, and replacing spaces with hyphens
  (`` ### 4.2 `directoryindex.py` — `DirectoryIndex` `` becomes
  `#42-directoryindexpy--directoryindex`), but conventions differ slightly across
  renderers (GitHub vs. a static-site generator vs. an editor's preview). When in
  doubt, link to the file and let the section heading's exact text guide the reader
  the rest of the way, rather than guess at a slug that might not match.
- **This is a per-file convention, not a one-time pass.** Every new ERD, design doc
  section, or diagram written after this rule exists should link its references as it
  is written — don't treat linking as a cleanup step to be done later.

### 1.4 Companion exception-taxonomy file

If an app defines custom exception classes, or has standard/Django exceptions that are
part of its actual error-handling *design* rather than incidental try/except, it gets a
companion `<app>_exceptions.md` file — same convention as the ERD file (§1.1), same
directory, named after the app: `quickbbs_exceptions.md`, `thumbnails_exceptions.md`,
and so on. An app with genuinely nothing notable to say (no custom exceptions, no
deliberate standard-exception handling pattern) still gets a short file stating that
plainly — the absence is itself a fact worth documenting, the same way
`user_preferences_erd.md` documents an app that owns no interesting relationships
rather than being skipped.

- **Title block and preamble** follow the ERD convention exactly: name, "Companion
  to: `<app>_design.md`" (linked, or "N/A" if none exists), author, date, then a "What
  this is" paragraph scoping what the file covers.
- **A table of custom exception classes** (omit this section for an app with none):
  class name, what it subclasses, constructor attributes, and the condition that
  causes it — one row per class, linked to its definition site.
- **Raise sites and catch sites, organized per exception**, not per file. A reader
  asking "what happens when `OrphanedThumbnail` is raised" should find every raise
  site and every catch site under that exception's own heading, not scattered across
  a file-by-file walkthrough. For each catch site, state what the catcher actually
  does — re-raise unchanged, convert to an HTTP response, log and continue with a
  safe default, wrap into a different exception type — since that's the fact a reader
  actually needs and the thing most likely to be wrong if guessed rather than read
  from source.
- **Every raise/catch claim must be verified against the actual source**, file and
  line, before being written down — the same accuracy discipline as §4.4, applied to
  exception flow instead of function behavior. An exception taxonomy that gets a catch
  site wrong is worse than no taxonomy, because a reader debugging an error will trust
  it.
- **Stay descriptive, not prescriptive**, unless a project explicitly wants otherwise.
  Document what the code actually does with an exception — don't editorialize about
  whether that's the right design, don't flag inconsistencies as problems inside the
  file itself. If a real inconsistency turns up while researching the file (a raise
  site that doesn't match its sibling's pattern, an app with no error handling at all
  where you'd expect some), that observation goes in a separate list surfaced to the
  user after the docs are written, not into the taxonomy prose — the taxonomy's job is
  to be an accurate map of what is, not a code-review report.
- **The cross-app exception-flow file** (`high_level_exception_flow.md`, if one
  exists) is the exception-taxonomy counterpart to
  `high_level_dependency_diagram.md` (§1.2) — same reasoning for why it's a Mermaid
  flowchart and not an `erDiagram`: an exception crossing an app boundary isn't a
  schema relationship, and different catch sites for the same exception can have
  completely different terminal handling (one converts to an HTTP response, another
  converts to a task-result flag) that a single arrow style can't carry. Label each
  edge with the exception name and, in the prose below, what each side actually does
  with it.

---

## 2. Section 1 — Guiding Principles

This is the section that most distinguishes these documents, and the one most easily
written wrongly. It goes **before** Purpose, because it explains why everything after it
looks the way it does.

### 2.1 What belongs here

Product and design decisions. *Why* something was built this way — the problem it solves,
the alternative that was rejected, the cost that was accepted deliberately.

### 2.2 What does not belong here

**Technology.** Naming a library, a framework feature, or a concurrency model is not a
principle. "The gallery uses HTMX" is a fact about the implementation; "browsing should
feel continuous" is the principle that led to it.

**Method and function names.** Principles are discussed in concepts. Identifiers belong
in §4. The only names that may appear are user-facing ones — things the owner of the
system actually types or sees, such as `Albums/`, `.alias`, `*.link`.

**Numeric or configuration detail.** Describe the concept, not the tuning. "Attention
drives work" — not "priority 50 versus priority 0."

### 2.3 Cross-reference direction

**Section 1 references only other principles.** It never points down into implementation
sections. A principle that needs §4 to be understood is not yet written as a principle.

The reverse is encouraged: §4 and §10 may point *upward* to §1 to explain why a piece of
code exists (e.g. "degrades to a streaming 200 rather than an error — §1.8").

### 2.4 Necessity vs. possibility — say only what's actually claimed

A principle stated as a necessity ("the same work *legitimately belongs* in several
places") is a stronger claim than one stated as a possibility ("the same work *can*
legitimately belong"). Cross-filing being *allowed and unpenalized* is not the same
claim as cross-filing being *required or expected*. When the underlying behavior is
permissive rather than mandatory, write the permissive version — "can," not "does" or
"belongs." Check which one the code and the author's intent actually support before
committing to the stronger phrasing; it is an easy default to overstate.

### 2.5 Shape of a principle

Each principle is `### 1.N` with a title written as a **complete assertion**, not a
topic label:

- ✅ "The filesystem is the source of truth; the database is a cache"
- ✅ "Identical files are the same file"
- ✅ "Degrade to something sensible before failing"
- ❌ "Filesystem handling"
- ❌ "Error strategy"

Body pattern, in roughly this order — use the parts that apply:

1. A sentence or two of plain statement, in the second person where natural ("You
   organize files in `Albums/` with whatever tools you already use").
2. **The problem this solves.** The concrete frustration or failure that motivated it.
   Real numbers from real experience are good here.
3. **The rule.** The invariant stated crisply enough to test a future decision against.
   Name its exceptions explicitly.
4. **Consequence: …** bullets. What necessarily follows. This is where a principle earns
   its place — it should visibly constrain the design.
5. Any closing qualifier, set as a bold lead-in paragraph.

Bold lead-ins (`**The rule.**`, `**Consequence: caches must never outlive the truth.**`)
carry the structure. They let the section be skimmed by claim.

**Phrase "Consequence" and "The rule" bullets positively.** Don't frame a design choice
as "X isn't chosen because of Y" — frame it as "X is chosen because of [positive
reasons]," while still stating the real downside plainly rather than hiding it. "The
database isn't chosen here because it's faster to read from — it's chosen because it
collapses generation into one transactional write" should instead lead with the
positive case (simplifies mechanics, removes invalidation bookkeeping) and state the
downside (medium/large thumbnails don't get the fast-read discount) as a plain
qualifier after, not as the headline. Don't label a stated downside "honest" or
similar — stating it plainly needs no framing that calls attention to its own
truthfulness; that framing implies the alternative (hiding it) was on the table.

Two related patterns, same root cause — over-hedging reads as insincere or negative:
- **Don't use "genuinely" as an intensifier** ("genuinely available," "genuinely
  faster"). It implies the writer expects to be doubted, which undercuts the claim
  rather than strengthening it — just state the fact.
- **Don't describe a fallback path in negative relative terms** ("a slower one that
  always works") when it isn't actually slow in absolute terms. Name it directly (e.g.
  "falls back to the cross-platform thumbnail system"). Reserve comparative language
  ("faster," "slower") for a claim the doc can actually back up.

### 2.6 Principles shared across sibling documents

Some apps sit underneath another already-documented app and implement principles the
other only consumes — `quickbbs` (the data layer) versus `frontend` (the request layer)
is the first case of this.

**The carry-down mechanics below describe a documentation-authorship direction, not a
statement of which app's concerns are more foundational.** `quickbbs` is nominally
treated as the master/founding design document, but that is true only in the sense
that it happened to be written first and principles are currently drafted with
`frontend` as the origin and `quickbbs` carrying them down. In practice the two are
co-leads — neither subordinates the other. When deciding which document "should"
state a principle first, or whether to move a principle between them, treat it as a
discussion between equals: check which layer actually implements/enforces the rule
(the rule below — only carry down what the lower layer actually implements), not
which document is "more foundational." This applies to any future sibling-document
pair with the same layered shape, not only `quickbbs`/`frontend`.

When carrying a principle down:

- **Carry the principle down, don't restate it as new.** Open the app's §1 with a
  sentence naming which sibling document it inherits from and linking to that
  document's §1. Each inherited principle then gets its own `### 1.N` here, opening
  with "Carried down from [sibling §1.N](...)" and a link anchor, not copied prose.
- **Reword for the layer that actually implements it.** The sibling's wording is
  usually framed around what its own layer does (e.g. request handling: "a directory is
  scanned the first time someone visits it"). The layer underneath should reframe the
  same rule around what *it* does (e.g. the data layer: what makes a record valid or
  stale, how invalidation propagates) rather than keep the other layer's framing
  verbatim just because the words still technically apply.
- **Only carry down what the lower layer actually implements or is bound by.** A
  principle the lower layer merely happens to be consistent with, but doesn't itself
  enforce or embody, does not need its own entry — a one-line mention elsewhere is
  enough. Ask the author which principles apply before drafting all of them; do not
  assume every parent principle needs a child entry.
- **New principles specific to the lower layer stand on their own, unlabeled.** Not
  everything is inherited — a layer can (and likely will) have principles the sibling
  document has no equivalent for. Give these a plain `### 1.N` with no "carried down
  from" line.
- **Don't thin the parent document at the same time.** If a principle now lives more
  precisely in the child document, that is a separate, later editing pass on the parent
  — done deliberately, not as a side effect of writing the child.

### 2.7 Deriving the principles — this is an interactive Q&A, not a solo pass

Principles are mined, not invented — from docstrings, comments, and the shape of the
code — but mining only gets you a list of candidates. **Every candidate must then be
put to the author as an actual question and answered before it is written up.** This
is not an optional polish step; treat §1 as blocked on the Q&A, not merely improved by
it.

**A first draft of §1 is not the end of the Q&A — do a second round once real content
exists.** The first pass surfaces the obvious candidates from docstrings and comments.
A second, narrower round, asked after a working draft exists, tends to surface the
sharper material: ask about specific mechanisms already documented in §4 ("why
propagate invalidation upward instead of just the one directory that changed?"), not
just the broad "why does this app exist" questions from the first pass. Several of the
strongest entries in the `quickbbs` rewrite — the reasoning against periodic full
rescans, why an invalidated record is kept rather than deleted, the actual origin of a
stable content-derived identifier — came from this second round, prompted by the
author rather than found unprompted while reading source.

**When an answer states a limitation, check whether the codebase already has an
escape hatch for it before writing the limitation as absolute.** An answer describing
"no scheduled sweep" first read as a plain limitation ("changes made while the server
is down aren't caught until someone browses there"); the author's correction pointed at
an existing management command built for exactly that gap, invoked externally via cron
or after a bulk file operation. The corrected principle is stronger for naming the
escape hatch — it turns "this is a gap" into "this is a deliberate default, and here is
how you override it" — but that only happens if the escape hatch is confirmed rather
than assumed absent.

**Precision in *why* something is stable matters as much as the fact that it is
stable.** A first pass on a content-derived identifier said the benefit was
predictability — knowing an identifier "in advance." The author's correction: the real
property is permanence *after* the record exists, not predictability *before* it does
— a benchmark script hardcodes an identifier once and trusts it will never change,
which is a different (and more defensible) claim than being able to guess it ahead of
time. When a rationale involves a property like "stable," "safe," or "reliable," get
specific about which direction that property holds in — before an event, after it, or
both — rather than let the more impressive-sounding version stand.

**Ask, one question at a time or in a small batch, rather than presenting a finished
draft for approval.** A finished draft invites a rubber-stamp; a question invites the
real reason. Ask about motivation, not mechanism:

- What frustrated you about the alternatives?
- Who is this for, and what do they already have?
- What did you deliberately not build, and why?
- What would you refuse to change even if it were faster?
- Where does it give up, and where does it fall back instead?
- Why this approach and not the more obvious/conventional one?

**If a question gets answered in technology terms, push past it.** "Why does X work
this way?" answered with "because it uses HTMX" is not yet a principle — the follow-up
is "and what did that let you stop worrying about?" or "what were you trying to avoid
by choosing that?". Keep asking until the answer is a problem, a value, or a tradeoff,
not a tool.

**When in doubt about a claim, ask rather than assume.** If you are not sure whether
something was a deliberate choice or an accident of implementation, whether a limit is
load-bearing or incidental, or who the intended audience for a feature really is — ask.
Do not paper over the uncertainty with confident-sounding prose.

**Expect corrections after you write something up, and treat them as more Q&A, not just
edits.** When the author corrects emphasis or wording, that correction is itself new
information about the underlying rationale — apply it to the whole section, not only
the sentence flagged, since the same misreading is usually present in several places,
and ask a follow-up if the correction implies something you haven't captured yet.

---

## 3. Sections 2–3 — Purpose and Architecture

**§2 Purpose** is short. One paragraph identifying the app, then a bulleted list of what
it owns, each entry a bolded noun phrase with a one-line gloss. If the app has a
non-obvious execution model, state it here in a short bolded paragraph and expand later.

Where the current design deliberately reverses an earlier one, say so once, with the
reason. This is the one place history is welcome, because the shape of the code is
otherwise unexplainable — but state the reason in the design doc's own prose rather
than pointing to a plan document (§0's "not release notes" rule extends to this: a
`claude_docs/plans/*.md` file is a working artifact, not something a design doc should
depend on or link to — it isn't guaranteed to keep existing, and the design doc should
be readable without it).

**§3 High-Level Architecture** is a single fenced ASCII diagram: entry point at the top,
routing, then modules with their key functions and a right-aligned annotation column.
Align the annotations. The diagram is a map, not a specification — one line per function,
no prose.

---

## 4. Section 4 — Component Reference

The largest section. `### 4.N` per module, `#### ` per function or class.

### 4.1 Module headings

`### 4.N \`module.py\``, with no descriptive tail after the filename. The tail is
where a one-or-two-word label (a class name, "Central Cache Invalidation") ends up
duplicating or half-explaining what the body already says in full — the fix is not a
better label, it's not needing one. The explanation belongs entirely in the
two-question opening that follows (§4.2), applied to the module as a whole: a **What
does this do?** line and a **What is its purpose?** line. This matters most for a
module that doesn't map to one obvious class — `models.py` re-exporting classes
defined elsewhere, a module that exists only to break an import cycle, a thin
compatibility shim — where a label would either be misleading or would need to
smuggle in a mini-explanation the header format has no room for.

### 4.2 The descriptive register

This is the calibration that took the longest to settle, so it is worth stating precisely.

A one-line restatement of the signature is not enough:

> ❌ "Primary gallery view. Renders a paginated list of subdirectories and files for a
> given URL path."

Nor is a step-by-step narration of the implementation, which duplicates the code and goes
stale:

> ❌ "…creating the index record on the first visit, then reading the layout cache keyed
> by page and directory pk, then hydrating exactly those rows…"

Aim between them: **describe what the function accomplishes and what is notable about how,
without narrating implementation order or naming internal state.** Prefer "creating or
updating the database when visiting the directory" over "creating the index record on the
first visit."

The working pattern:

1. **Two-question opening**, both bolded lead-ins, immediately under the `####` heading:
   - **`**What does this do?**`** — plain language, non-technical, aimed at *why it
     exists / who it's for*. No signature restatement, no identifiers beyond the
     function's own name.
     > "Lets a user find something by name across the whole collection, instead of
     > having to already know which directory it's in."
   - **`**What is its purpose?**`** — the technical/API-level statement: what it is,
     often with a colon, close to a one-line signature gloss.
     > "Search view: finds directories and files whose names match the search text,
     > and presents the combined results as one paginated listing."
   These two lines must say different things. If the "What does this do?" line would
   read as a paraphrase of the "What is its purpose?" line (or vice versa), one of them
   is redundant — cut it back to a single line rather than let them restate each other.
   A trivial or purely mechanical helper (a thin delegation, a one-line formatter) may
   still need both, but keep each to one sentence.
   - **A subtler version of the same mistake: "What is its purpose?" answers "what's
     inside this file" instead of "why does this file exist."** `common.py`'s purpose
     line once read "Hashing, path normalization, and sort-ordering functions used
     throughout the app" — a true sentence, but an inventory of contents, which the
     "What does this do?" line right above it had already conveyed in different words.
     The two lines can pass the "do they say different things" check word-for-word and
     still both be answering the same underlying question. Ask, specifically for the
     purpose line: does this name a *reason this file exists as a separate, shared
     thing* — a reason another module would point at if asked "why didn't you just
     write your own version of this?" — or does it just list what's defined inside?
     "A common location for routines shared across sub-applications, so `frontend` and
     `cache_watcher` both call the same implementation rather than each maintaining
     their own" is a purpose; "hashing, path normalization, and sort-ordering
     functions" is a table of contents wearing a purpose line's punctuation.
2. **A short paragraph on what it does**, in terms a reader who does not know the codebase
   can follow.
3. **A paragraph on what is notable** — the design decision, the cost avoided, the
   guarantee upheld. Reference §1 where it applies.
4. **Then the specifics**: bullets, tables, request-flow blocks, constants, gotchas.

Prose first, mechanism second. A reader should be able to stop after the two-question
opening and the prose that follows it, and have an accurate model.

**Every `####` entry ends with a `---` separator, no exceptions.** Markdown has no
native way to indent a block of prose under its heading, so the separator is what
actually does the job of telling a reader "this entry's discussion has ended" before
the next one starts — without it, consecutive entries run together with nothing but a
heading of the same visual weight to mark the boundary, which is easy to skim past.
Apply this uniformly to every `####` entry in a document, not just the ones that feel
long enough to need it; a one-line entry immediately followed by another one-line
entry needs the separator exactly as much as two long ones do, since the point is a
consistent, predictable boundary a reader can rely on, not a judgment call made fresh
each time.

**Trailing notes go in a bulleted list, not bare paragraphs.** An entry often ends with
one or more short asides that don't belong in the main prose — a deprecation notice, "no
async wrapper exists any more," a prototype-not-dead-code disclaimer, a note that a
sibling variant was removed as dead code. Once there is more than one such aside, or
even just one sitting as the last thing before the `---` separator, put it in a bulleted
list rather than as a sequence of standalone paragraphs. A list signals "these are
independent trailing notes" the way consecutive paragraphs don't — a reader skimming for
the still-current gotchas shouldn't have to parse each paragraph to discover it doesn't
connect to the one before it. This does not apply mid-discussion, where a note is
followed by more related prose before the entry ends — only to notes that are genuinely
the last content in the entry.

### 4.3 Explaining the non-obvious

Where code exists for a reason that is not visible from reading it, explain the reason —
what would happen otherwise. `SizedFileWrapper` is the model: the wrapper is trivial, but
without it the library reads an entire video into memory to learn its length. State the
avoided cost.

### 4.4 Accuracy discipline

- **Conditional behavior stays conditional.** "If any files on the page still lack
  thumbnails, that work is enqueued" — never "thumbnails are generated."
- **Verify before asserting.** Where a claim is checkable — a registered extension, a
  field type, a lookup order — check it. Several errors in the frontend rewrite were
  reasonable-sounding assumptions that the code contradicted.
- **A comment's stated interpretation is not itself verified — check the reasoning,
  not just the fact.** A source comment or docstring can be accurate about a mechanism
  ("hits and misses are counted") while its *interpretation* of that mechanism ("hit
  rate under 80% means grow the cache") doesn't hold in general — a low hit rate can
  equally mean the workload is inherently one-shot, which no cache size fixes. Copying
  the comment's guidance into the design doc repeats the code's own unverified claim
  with the design doc's authority behind it. Trace the actual logic (what causes a
  miss, whether that cause responds to the knob being tuned) before restating a
  comment's advice as fact — quoting is not the same as verifying.
- **Caveats go where they bite**, inline with the feature, not in a separate list.
- **Prioritization is not preemption.** "Gets prioritized over background work" states
  that a task moves ahead in a queue; it does not claim the work happens instantly or
  that a busy worker pool is bypassed. When rewording a queue/priority claim, check
  that the new phrasing doesn't accidentally imply either instant completion or that
  workers are never contended — get the mechanism right in both directions, not just
  the one being corrected.
- **A hedge added to fix one inaccuracy can introduce a different one.** Guarding
  against "sounds instant" by adding "though it still has to wait if busy" can overcorrect
  into implying waiting is the norm. When walking back an overstatement, check the
  replacement doesn't overstate in the opposite direction — the original, unhedged
  phrasing is often already correct once the false implication is removed, without
  needing a new qualifying clause at all.
- **Describe the current implementation, not the one it replaced.** §0 already rules
  out release-notes content generally; this is the specific trap that slips past that
  rule during §4 drafting. "The earlier `X` path — a live queryset with a multi-field
  `Q` object — has been replaced by the cached-list approach above" describes code that
  no longer exists and gives the reader nothing they can check against the current
  source. If two branches of a function look different (e.g. `show_duplicates=True` vs
  `False`), that's worth documenting — but frame it as "these two branches share this
  shape" or "branch A does X, branch B does Y," not as a past-tense narration of what
  branch A used to do before a rewrite. Test: if the sentence would still make sense
  with the removed code deleted from your memory entirely, it's describing the present.
  If it depends on remembering what used to be there, cut it. The one exception is a
  single, dated note that a whole function/file was removed as dead code (helps a
  reader who finds a stale reference elsewhere) — that's a pointer, not a mechanism
  description, and doesn't invite the same confusion.
- **"It was previously defined in X" is release notes, not design.** State where
  something lives now. Where it used to live has no bearing on understanding the
  current design and belongs in commit history, not here.

---

## 5. Sections 5–8 — App-specific mechanisms

Slots for what that app actually needs. Reach for the right form:

- **Tables** for anything enumerable: caches (location / key / backing type / invalidated
  by), template pairs, mode comparisons.
- **ASCII trees** for a flow through several functions, with `←` annotations on the lines
  that need justification.
- **Blockquotes** for a note that the current implementation differs from what a reader
  might expect from an earlier version or the obvious design.
- **Bold lead-in paragraphs** for named sub-behaviors within a flow ("**Race-condition
  check.**").

Every cache gets a row. Every fallback path gets a sentence.

---

## 6. Section 9 — Module Structure Summary

Fenced tree of the app directory, `#` comment on each entry saying what it is. Include
test files with their counts, and mark directories that are **not imported by the app**
(prototypes, deprecated, standalone scripts) explicitly — otherwise a reader assumes
everything listed is live.

---

## 7. Section 10 — Future Ideas

Directions under consideration. Open with an explicit disclaimer that **nothing here is
committed or scheduled** — recorded so the reasoning is not lost, not as a roadmap.

Per idea: bolded name, one-line statement, then what already exists versus what is
missing. Where partial capability exists, say so plainly — it changes whether the item is
a build or a polish.

Close with **"Tensions to resolve first"**: for each idea, which principle it pushes
against and what would have to be decided. This is the section's real value. Be precise
about where the tension actually lies — an idea that appears to violate a principle often
does not, and saying so is more useful than an overstated conflict.

Ideas that raise no principle conflict may be listed in one closing sentence rather than
given their own entries.

---

## 8. Voice and mechanics

- **Second person** for the owner/user; **"the gallery," "the application"** for the
  system. Avoid "we."
- **Present tense** throughout. The document describes what is.
- **Em-dashes** for the qualifying clause that carries the reason.
- **Bold lead-ins** to structure a paragraph run; **inline code** for every identifier,
  path, header, and setting.
- **Concrete over abstract.** "A directory of ten thousand files costs the same as one
  holding twenty" beats "scales independently of directory size."
- **State costs and limits plainly.** What is not supported, what degrades, what was
  deferred — including when the reason is simply that it has not been added yet.
- **No hedging and no salesmanship.** Neither "arguably somewhat faster" nor "blazing
  fast."
- **Define framework/library jargon on first use in a passage.** A term like Django's
  *attname* is precise and worth using, but only if the sentence also says what it
  means (the raw FK column value already in memory, as opposed to the descriptor that
  lazy-loads the related row) — don't assume the reader carries ORM internals.

Phrasings worth reusing:

- "X is an accelerator, never a requirement."
- "Speed never costs correctness."
- "They have simply not been added yet."
- "Degrades to … rather than …"

---

## 9. Working checklist

Before starting:

1. Read every source file in the app, in full.
2. Read the existing design document, if any, and list where it and the code disagree.
3. Mine docstrings and comments for stated rationale — this produces *candidates*, not
   finished principles.
4. **Q&A with the author on the principles, interactively, before drafting §1.** Ask
   about motivation, not mechanism (§2.7). Do not proceed to drafting on the strength of
   an inferred rationale — if a candidate principle's "why" isn't confirmed, ask about it
   before it goes in the document.

While writing:

5. Draft §1 first; the rest follows from it.
6. Keep §1 free of identifiers, technologies, and numbers.
7. Verify each checkable claim against the code or a shell query.
8. Hold §4 to the register in §4.2 — essence, then notable, then specifics.
9. If a rationale needed for §2, §4, or §10 wasn't covered by the §1 Q&A, ask about it
   when you reach that section — don't backfill it with a guess.
10. If the app sits underneath a sibling document, ask which of the sibling's
    principles this layer actually implements before drafting §1 (§2.6) — don't assume
    the answer and carry down everything that seems related.
11. Once §1 has real content, run a second, narrower Q&A round grounded in what §4 now
    documents, not just the original broad questions (§2.7).

Before finishing:

12. **Re-read §1 once more, specifically hunting for identifiers, technologies, and
    numbers** (§2.2) — these slip in during drafting even when the rule is already
    known, especially while explaining a mechanism in more depth than the first pass.
    Do this as its own dedicated pass, not folded into a general read-through.
13. Confirm heading numbers are contiguous and every `§N.N` cross-reference resolves —
    including cross-references *into* a sibling document, and any internal reference
    whose target number shifted because a section was inserted (§2.6's insertion here
    is the example: every later §2.N and its inbound references had to be checked).
14. Confirm no §1 reference points downward into implementation.
15. Bump the version and date in the title block.
16. Re-check any conditional statement that reads as unconditional.
17. Re-check any stated limitation for an existing escape hatch, and any stated
    "stable"/"safe"/"reliable" claim for which direction (before/after) it actually
    holds in (§2.7).

---

## 10. Anti-patterns

Each of these was written and then corrected during the `frontend` or `quickbbs`
rewrites.

| Anti-pattern | Correction |
|---|---|
| Principles framed around technology | Frame around the problem and the decision |
| Method names inside §1 | Concepts only; identifiers live in §4 |
| Priority numbers, batch sizes, tuning in §1 | Describe the concept |
| §1 pointing down into §4 or §8 | Principles reference only principles |
| "Reconciled on every request" | Verify the trigger; it was event-driven |
| "Thumbnails are generated" | "…are enqueued *if* they need to be" |
| A "Known Issues / Cleanup" section | Not a release-notes document; delete it |
| One-line signature restatements in §4 | Essence, then notable, then specifics |
| Implementation-order narration in §4 | Describe accomplishment, not sequence |
| Asserting a fact that felt obvious | Check it; `.md` turned out not to be registered |
| Overstating a tension in §10 | Locate the conflict precisely, or say there is none |
| Field names slipping into §1 while explaining a mechanism in depth | Even a known rule needs a dedicated re-read pass, not just awareness while drafting |
| Restating a stale/ambiguous condition as "the known open gap" | Ask whether it's actually a deliberate tradeoff before writing it up as unresolved |
| Describing a limitation without checking for an existing override | An "absolute" gap ("not caught until someone browses there") turned out to have a management-command escape hatch already built for it |
| Claiming a benefit is "predictable in advance" | The actual property was permanence *after* creation, not predictability *before* it — get the direction of the "stable" claim right |
| Restating a sibling document's principle instead of reframing it for this layer | Same rule, different framing — from what the request layer does, versus from what the data layer does |
| Treating the "master document" one app inherits into as more authoritative in a disagreement | Sibling documents in a layered pair are co-leads — check which layer implements the rule, not which doc is nominally "master" |
| "X isn't chosen here because it's faster to read from — it's chosen because..." | Lead with the positive justification; state the real downside after, as a plain qualifier, not the headline |
| "genuinely available," "genuinely faster" | Drop the intensifier — it implies the reader was expected to doubt the claim |
| "a slower fallback that always works" (no comparison backing "slower") | Name the fallback directly; reserve "faster"/"slower" for a claim the doc can actually back up |
| Stating a permissive behavior as a necessity ("the same work legitimately belongs in several places") | "Can legitimately belong" — cross-filing is allowed, not required |
| "Thumbnails are never generated from a search" | The thumbnail *pre-warm check* is skipped for search, not thumbnail generation itself — a thumbnail still gets made on-demand, if missing, when an item is viewed |
| "Gets warmed ahead of background work" reworded to "has to wait for a worker to free up" | Overcorrected into implying waiting is the norm; queue prioritization is not preemption, and the walk-back shouldn't overstate the opposite failure mode |
| Jargon term (`attname`) used without explaining what it means | Define Django/framework-specific terms inline the first time they're used in a passage, even in a technical-register line |
| Two "What does this do?"-style lines stacked on one `####` heading, restating each other | One plain-language line, one technical line — each says something the other doesn't, not a Q&A pair that duplicates content |
| "The earlier path — [description of removed code] — has been replaced by [current approach]" | Describe only the current branches/behavior; a reader shouldn't need to hold a deleted implementation in mind to follow the sentence |
| "X now lives in Y (it was previously defined in Z)" | "X lives in Y." Where it used to be is commit history, not design |
| Two or more trailing asides (deprecation notice, "no async wrapper any more," prototype disclaimer) left as separate bare paragraphs at the end of an entry | Bullet them — a list signals independent trailing notes the way stacked paragraphs don't |
| A `### 4.N` module header tail ("Re-export Facade") trying to compress an explanation the body already gives in full | Drop the tail — `### 4.N \`module.py\`` — and let the two-question opening carry the explanation once, not twice |
| `####` entries with no `---` separator between them, run together with only a heading to mark the boundary | Every `####` entry ends with `---`, applied uniformly — not just on entries that feel long enough to need it |
| "Hit rate under 80% means the cache is too small," copied from a source comment's stated interpretation | Trace the actual cause of a miss (eviction vs. an inherently one-shot workload) before restating the comment's advice as fact |
| "What is its purpose?" restates the file's contents ("hashing, path normalization, and sort-ordering functions") instead of the reason it exists as a shared file | State why it's separate/shared — who else would otherwise duplicate it — not what's defined inside |
| `FK fieldname "comment"` inside a Mermaid `erDiagram` attribute block | `<type> fieldname FK "comment"` — Mermaid parses the first token as the type; `FK`/`PK` only work in the constraint slot |
| Forcing an app-to-app dependency map (mixed FK/hash-join/function-call) into `erDiagram` notation | Use a Mermaid flowchart (`graph TD`) with labeled edges instead — entity-relationship notation has no vocabulary for "plain function call, no schema relationship" |
| "See `frontend_erd.md`" or `` `CacheStatisticsTracking` `` left as plain code-formatted text | Markdown link to the file, and to the specific heading/anchor where that model is defined, not just code-formatting the name |
| "See `claude_docs/plans/async_simplification.md`" for why a design was reversed | Restate the reasoning in the design doc's own prose; never link to or name a plan document |
| "This restart is a periodic reset, not a response to a diagnosed failure... no leak has actually been confirmed... not a fix for a diagnosed one" | State what the restart does and on what schedule; don't name and deny a failure nobody raised |

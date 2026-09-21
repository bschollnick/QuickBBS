# Ink: A Working Reference

**Date Created:** 2026-09-09  
**Last Updated:** 2026-09-20  
**Last Reviewed:** 2026-09-20

Standard Ink — syntax, structure, and runtime behaviour that holds for any Ink
story, regardless of what you are writing or what runs it.

**Every behavioural claim here was verified by running real `inklecate`**, not
inferred from documentation. Where a claim is subtle, the test that proves it
is included so it can be re-run.

inkle's own *Writing with Ink* is the reference for what Ink **does**; read
this for what it does when you get it subtly wrong. (The headline case below,
1.1, is not covered by inkle at all.)

Two companion documents carry what this one deliberately leaves out:

- **Application and engine concerns** — `EXTERNAL` binding contracts, media
  tags, and notes for anyone implementing an Ink interpreter — live in
  [`interactive_fiction — Implementation Guide`](design%20documents/interactive_fiction_implementation_guide.md).
- **Converting an existing game into Ink** — verifying a port against its
  original source, state-ownership decisions, and audit methodology — is
  out of scope here, and tracked with the conversion itself.

```bash
inklecate -o out.json story.ink            # compile
inklecate -p story.ink                     # compile and play in the terminal
printf '1\n2\n' | inklecate -p story.ink   # feed choices; 1-INDEXED
```

---

## Part 1 — The language

### 1.1 Never write a choice inside a conditional block

**A choice must never be written inside a conditional block.**

```ink
{ COND: + [Label] -> scene }      // WRONG - inner choice list
+ { COND } [Label] -> scene       // RIGHT - guarded outer choice
```

The two read identically to a human and compile differently. The wrapped form
becomes a *nested* choice list, and its once-only/consumed tracking does not
survive re-entering the knot.

Combined with the standard hub idiom — a gather that re-enters its own knot,
plus a scene that diverts back — the story takes the same choice again and
again **inside a single turn**, printing the scene's prose each lap and never
stopping to ask the player anything. The turn never ends. The game hangs.

Proof, in eight lines, against real `inklecate`:

```ink
VAR ok = true
-> main
=== main ===
Hub.
{ ok: * [Wrapped once-only] -> back }
* { ok } [Guarded once-only] -> back
+ [Leave] -> END
=== back ===
(chose)
-> main
```

`inklecate -p` never offers the wrapped choice to the player at all. It
auto-takes it forever:

```
Hub.
* [Wrapped once-only] (chose)
Hub.
* [Wrapped once-only] (chose)
...
```

The guarded choice sitting on the very next line behaves correctly.

Note it is `*` — a **once-only** choice — that loops. Marking a choice `*`
gives no protection here; see section 1.2.

This is worth banning outright rather than policing case by case: the guarded
form is equivalent everywhere, so there is never a reason to write the wrapped
one. A static check over the story text catches it in one pass.

> **Symptom to recognise:** the game stops responding at one specific
> location, CPU pinned, no error, no output. Look for a wrapped choice in the
> hub you were standing in.

### 1.2 Once-only (`*`) vs sticky (`+`)

A `*` choice **does** stay consumed across re-entry, including a round trip
through another knot:

```ink
-> main
=== main ===
Choose.
* [Once-only A] -> back
+ [Sticky B] -> back
+ [Leave] -> END
=== back ===
(chose)
-> main
```

After taking A once it is gone; B stays forever. This is why section 1.1 is
surprising: the wrapped form defeats tracking that otherwise works fine.

**`*` strands players.** A knot whose only exits are once-only leaves a
returning player with nothing to click. Two sub-traps:

- **A gated `+` is not an unconditional exit.** If the `+` guard is false, the
  spent `*`s are all that remain and the knot has *no exit at all*:

  ```ink
  === main ===
  The room.
  * [Look around] -> main
  + { can_leave } [Leave] -> END
  ```

  Take "Look around" with `can_leave` false and Ink stops with
  `RUNTIME ERROR: ran out of content. Do you need a '-> DONE' or '-> END'?`
  A check that only flags knots whose exits are *all* once-only will not
  catch this — the `+` makes it look safe.

- **Reset paths replay spent choices.** Anything that reopens a chain from
  the top finds every `*` in it already consumed.

If you are porting a game whose engine redraws its menu each turn, its
choices are sticky by nature — `+` is the faithful default, and `*` is the
deliberate exception.

### 1.3 `not` binds tighter than comparison

`not X == "y"` parses as `(not X) == "y"`.

With a **string**, this is a hard runtime error, and it fires only when that
line is actually reached — so it compiles, ships, and waits:

```ink
{ not where_is() == "kitchen": ... }
// RUNTIME ERROR: Cannot perform operation '!' on String
```

With a **number**, `not f() > 0` and `not (f() > 0)` both fire — the two agree
at every reachable value, so numeric sites are safe and rewriting them is
churn. Check the actual value range before "fixing" one.

**Always parenthesise:** `not (expr == value)`.

Both failure modes are silent at compile time, so a static check over guard
expressions earns its place.

### 1.4 Structural rules (all compile-time, with exact messages)

| Rule | Error if broken |
|---|---|
| A stitch may not share a name with a VAR | `Stitch 'shop': name has already been used for a var on line 1` |
| A function may not contain a divert | `Functions may not contain diverts, but saw '-> main'` |
| Diverting into a stitch **from outside its knot** needs the full path | silently a loose end / unresolved |

Within a knot, a sibling stitch is reachable by bare name (`-> second`). From
anywhere else it must be `-> knot.stitch`.

**So anything diverted to from another file must be a top-level knot.** Ink
silently binds `= name` as a stitch of whichever knot precedes it — no error
at the declaration. The failure appears far away as `divert target not found`,
or, if the stitch trails the file's last knot, as content that is simply
unreachable with **no error at all**:

```ink
=== shop_floor ===    // globally divertable
= shop_floor          // becomes back_office.shop_floor — not what you meant
```

**Ink has no bitwise operators.** The full arithmetic set is
`+ - * / % mod`. If the game you are converting packs flags into integer
bitfields, do not hand-roll bit arithmetic to preserve a memory-packing
trick that has no meaning in Ink — port one flat named boolean per flag. The
general principle: **port the content, not the storage mechanics.**

**`not` also binds tighter than `?`** — `not present ? alice` silently
inverts. Parenthesise: `not (present ? alice)`.

**Stitches must stay contiguous with their parent knot.** Never insert a new
`=== knot ===` between an existing knot's choices and its own `=` stitches —
it silently reparents them. Recompile after any insertion into a stitched
knot.

**A prose line starting with a keyword becomes code.** A narrative line
beginning `VAR ...` is parsed as a declaration:

```
ERROR: Expected variable name but saw '-in-interpolation and shuffles.'
```

**A `=== function ===` swallows everything until the next `===`.** Dropping
one into the middle of a file therefore captures whatever followed it —
including the file's own `-> start` divert, which then reports
`Functions may not contain diverts`. Put functions after the divert that
starts the story, or at the end of the file. (This bit while writing *this
guide's own* test cases.)

### 1.5 Functions

- A function **may not divert**, but it **may mutate a global** — that is the
  escape hatch for side effects.
- `~ temp x = ...` is scoped to the function/knot; globals are `VAR`.
- **You do not need to capture a return value.** `~ do_thing()` is a valid
  statement even when `do_thing` returns something, and this holds for
  `EXTERNAL` bindings too. This corpus uses `~ temp _unused = do_thing()` at
  2,039 sites; that is a house style, not a requirement.
- **A function that falls off its end returns Void, not `0`.** Interpolating
  it yields nothing: `[{nothing()}]` renders `[]`. An engine that substitutes
  `0` for Void will print a literal `"0"` into the prose.

### 1.6 A story may not begin with a named knot

If the literal first line of the story is `== knot ==`, the compiler is happy
and the story produces **zero playable output** — the entry point is the
top-level flow, and a leading named knot is never entered. Start the file with
`-> start` (or with prose).

This silently ruined two test fixtures here. If a story compiles but prints
nothing at all, check line 1 first.

### 1.7 `-> END` and `-> DONE` on a choice end the GAME

This was the single highest-impact defect class in the conversion, and it is
easy to write by accident because both look like "this branch is finished".

- `-> END` ends the **story**, not the scene.
- `-> DONE` ends the **thread**; with nothing else running the runtime has
  zero choices, which a player sees as "The story has ended."

Verified: a hub offering `+ [Leave via END] -> END` and
`+ [Leave via DONE] -> DONE` produces no further output from either.

An exit choice must divert to a real destination. The faithful target is
usually "the place that hosts this scene" — but **it is per-scene, so a
blanket substitution is wrong**: sending every scene back to "its own hub"
turned "Exit the police station" into a loop back into the police station
(11 such loops had to be repointed at actual streets).

When auditing for this, **survey by what the choice does, not by its
label**: exit-type choices are not all called "Leave" or "Exit" — they are
also "Say goodbye to…", "Head home", "Step out", "Slip away".

`-> END` used as a *placeholder* is the same bug in another form: an
arrest scene ending `-> END` made being arrested an unconditional game over,
with the entire courtroom unreachable.

Legitimate uses: a real, named bad ending that matches one of the source's own
ending states.

**A choice with no label is not a usable choice.** `+ -> somewhere` renders as
a blank entry (or, in `inklecate -p`, no entry at all — the player simply
cannot take it). Seven exits here were unlabelled, one of them the only way
out of the school building; the player saw four labelled doors and one blank
line.

### 1.8 Tunnels lose content silently

```ink
-> sub ->        // call
...
=== sub ===
->->             // return
```

If the target ends in `-> END` (or any plain divert) instead of `->->`,
**everything after the call site is silently dropped** — no error, no warning:

```
Tunnel that forgets to return.
In sub, diverting instead of returning.
[the line after `-> sub ->` never prints]
```

**A tunnel-return choice needs somewhere to return to.** A choice written
`-> scene ->` at the end of a knot that has no gather produces
`Apparent loose end exists where the flow runs out`. Give it a landing stitch:

```ink
= scene_from_hub
-> scene ->
-> hub
```

### 1.9 Alternatives

Verified across repeated visits:

| Syntax | Behaviour | Sequence over 4 visits |
|---|---|---|
| `{a\|b\|c}` | sequence, **sticks on last** | a, b, c, c |
| `{&a\|b\|c}` | cycle, wraps | a, b, c, a |
| `{!a\|b}` | once-only, then **empty** | a, b, ∅, ∅ |
| `{~a\|b\|c}` | shuffle | random without replacement |

Shuffle seeds from the container's path via a simple character-sum hash plus
the story seed — so it is reproducible only if you pin the seed. A runtime
that seeds from the wall clock (as real Ink's C# runtime does) gives different
results for the same save.

### 1.10 Conditionals, truthiness, LIST

- `0` is falsy; a non-empty LIST is truthy.
- **`""` is falsy and any non-empty string is truthy**, so
  `{ where_is("x"): ... }` reads directly as "is x somewhere".
- `{cond: A|B}` is if/else inside text; `- else:` is the block form.
- LIST: `?` tests membership, `LIST_COUNT()` sizes, `+=`/`-=` add and remove.
- Interpolation does **not** work inside a function call's arguments — `{a:x|y}`
  passed as an argument is not evaluated.

**Numbers and strings compare equal across types.** `"5" == 5` is **true**,
in both orders. So a function that returns `"0"` where the story expects `0`
compares equal and the type error never surfaces. Do not rely on a comparison
to catch a wrong return type.

**Floats and integers compare equal too:** `6.0 == 6` is true. That is
usually what you want — a binding returning a float still satisfies an
integer gate — but it means a comparison will not tell you which type you
actually got.

**Spaces inside `{cond:a|b}` become output.** Ink treats them as literal text,
not syntax whitespace:

```ink
A:{flag:Sarah|Angela}.        // renders "A:Sarah."
B:{ flag: Sarah | Angela }.   // renders "B: Sarah ."  <- note the spaces
```

Both compile. Only the spaced one is wrong, and only visibly so in the prose.

**There is no chained multi-branch inline conditional.** Ink has no `?:` and
no `elif` inside `{...}`:

```ink
{n==1:x|n==2:y|z}     // ERROR: Expected one or two alternatives
                      // separated by '|' in inline conditional
{n==1:x|{n==2:y|z}}   // valid - must nest
```

**Nesting then has a hard ceiling.** The compiler dies at **depth 23**:

```
Unhandled exception. System.Exception: Stack overflow in parser state
```

Measured by compiling generated stories at increasing depth — depths 1-22
compile clean. Past a handful of levels a flat block is easier to read than a
nest anyway:

```ink
{ n == 0: L0 }
{ n == 1: L1 }
{ n == 2: L2 }
```

### 1.11 Visit counts

`{knot_name}` is the visit count and increments normally across knots. If a
count looks stuck, suspect a consumed choice rather than a counting quirk —
this was checked before being written down, and the "quirk" turned out not to
exist.

Because `0` is falsy, a bare knot name in a conditional reads as
"have I been here":

```ink
{ room: You have been to the room. | You have never been to the room. }
```

### 1.12 Only the FIRST top-level divert runs

The story follows the first unconditional top-level divert and never returns
to the others. In a multi-file corpus this silently kills per-file entry
points: if the master file has `-> game_introduction` before its `INCLUDE`s,
then every included file's own `-> <character>_start` divert is **dead**.

Note the precise rule: a divert is only dead if it sits **before its file's
first knot**. A column-0 divert further down is ordinary flow — a detector
that ignores that distinction over-reports badly.

### 1.13 `INCLUDE` has no scoping — everything is one namespace

This catches people repeatedly, in three different ways:

- **VARs are corpus-wide.** There is no per-file scope. A scene once hardcoded
  a value on the belief that another file's `tracy_dress` was "not
  cross-referenceable"; it was always readable.
- **A duplicate `VAR` is a hard error, not a silent merge.** Including two
  files that both declare it fails the build.
- **Tags flatten too.** Two files' same-named `# image: pool.jpg` tags
  silently collide. Give every tag a path prefix that is unique per file.

**The dangerous middle case is a local VAR shadowing a global of the same
meaning with a different default.** One file writes its own copy while every
other file reads the shared one, so the change is invisible everywhere except
where it was made. Neither version compiles wrong.

The rule that prevents it: **any VAR read or written by more than one file
belongs in a single shared globals file**, never in one of the participating
files. Then a second file cannot silently declare its own copy — the name is
already taken, and a typo becomes `Unresolved variable` instead of a
permanently-false boolean.

### 1.14 Randomness

- `{a|b|c}` and `{&a|b|c}` involve **no randomness at all** — they are
  `MIN(visit_count, N-1)` and `visit_count % N`. Only `{~a|b|c}` and
  `LIST_RANDOM` use the RNG.
- **`RANDOM()` re-rolls on every knot visit.** For a stable value, hold it in
  a VAR; when an image tag and its prose must agree, hold the roll in a
  `~ temp` so the two cannot disagree.
- **`RANDOM()` is wall-clock seeded**, matching real Ink's C# runtime — so
  two runs of the same test differ, and `inklecate -p` on an unseeded fixture
  differs run to run. Pin a seed or harness numbers are meaningless.

### 1.15 LIST gotchas

```ink
LIST AllCharacters = alice, bob, carol   // the universe of possible members
VAR here = ()                            // the subset currently true
```

One global set re-valued as things move — never one list per location.

**`?` against a group means "contains ALL of them", not "any".** This is the
trap when mechanically replacing `a_here or b_here or c_here`:

```ink
~ here = (alice, bob)
{ here ? (alice, bob, carol): ... }   // NO  - carol is missing
{ (here ? alice) or (here ? carol): ... }   // YES - what you meant
```

Convert to the explicit `or` chain first; only collapse to the group form
after confirming the surrounding logic doesn't mix `and`/`not`. Parenthesise
each `(here ? x)` — it is being dropped into a larger boolean expression.

**A duplicate LIST member under two spellings compiles silently.** Unlike a
duplicate function (a hard error), declaring both `guard_captain` and
`guardcaptain` means one is silently checked and the other silently ignored.
Pick a spelling convention and machine-check it.

**Machine-check member count against write count, in both directions.** A
member never added is permanently absent; an add with no member is a compile
error. Here: 44 members, 44 `+=` sites, verified equal.

### 1.16 `~` needs its own line

```ink
{ flag: ~ here += a }   // ERROR
```
```
You shouldn't use a '~' here - tildas are for logic that's on its own line.
To do inline logic, use { curly braces } instead
```

Use the block form:

```ink
{ flag:
    ~ here += a
}
```

It is easy to write this in bulk — a whole function's worth of conditional
additions at once — and the whole function then fails to compile.

### 1.17 LISTs cannot be iterated

There is no "for each". Anything of the form "every member of this list does
X" must be written as one explicit choice or block per member.

Relatedly, **a plain divert cannot return to its caller** — that is what
tunnels are for (section 1.8). Where a scene must resume one of two different
callers, either use a tunnel or carry an explicit "where to go back to" VAR.

### 1.18 Threads inject choices ahead of the knot's own

`<- other_knot` pulls another knot's choices into this one. The threaded
choices are listed **first**:

```ink
=== main ===
Main choices.
<- extra_choices
+ [Own choice] -> END
```

```
1: Threaded choice
2: Own choice
```

Ordering matters if anything (a test, a walkthrough, a piped `inklecate -p`
script) selects choices by index.

---

### 1.19 Diverts can be assembled programmatically

Inkle documents this (*Writing with Ink*, "Advanced: storing diverts as
variables" and "Advanced: sending divert targets as parameters"): a knot
address is a type of value, written with `->`, that can be stored in a `VAR`,
returned from a function, and passed as a typed parameter. Runtime dispatch
is therefore ordinary Ink, not a workaround:

```ink
=== function target_for(who) ===
{ who == "a":
    ~ return -> charm_a
}
~ return -> charm_none

=== start ===
~ temp where = target_for(picked_now())
-> dispatch(where)

=== dispatch(-> where) ===
-> where
```

This resolves at runtime, including when the id arrives from an `EXTERNAL`
binding and when the pick happens across a choice.

**Two reminders when assembling one.** Both compile, so neither is caught by
a build:

A divert target is not a string. Assigning a string and diverting to it
produces *no output at all* — no error, no text:

```ink
VAR d = "target_b"
-> d            // compiles; emits nothing
```

This also rules out building a target name inside Ink: `~ temp t = who +
"_charm"` followed by `-> t` is the same case. A name assembled at runtime
has to be resolved to a real divert target by the application — an
`EXTERNAL` binding can look the knot up and return one, and Ink then
diverts to it.

A parameter must be declared with `->`. Written without it, the parameter
receives the knot's **read count** rather than its address — inkle notes
this too:

```ink
-> sleep(waking)          // `waking` is a NUMBER here
=== sleep(where) ===      // missing the `->`
Value is {where}          // prints 0
```

Write `=== sleep(-> where) ===` and call `-> sleep(-> waking)`.

**A stored divert cannot be tunnelled to.** `-> knot ->` works with a literal
knot name, but `-> where ->` where `where` holds a divert target compiles and
then emits nothing — the flow does not arrive and does not return:

```ink
VAR w = -> scene
-> w            // works
-> w ->         // compiles; emits nothing
```

This matters when the destination ends in `->->`: entered by a plain `-> w`
it has no tunnel to return from, so the story ends there instead of
continuing. Route to knots that end in a plain divert, or wrap the
destination in a knot of your own that ends the way the caller expects.

**A typed parameter will not take a call inline.** `-> dispatch(target_for(x))`
fails to compile (`expects a divert target ... but saw target_for(x)`); assign
to a `~ temp` first, as above.

---

## Part 2 — Verifying a story

### 2.1 Randomized playthrough is the highest-value test

Drive the compiled story with random choices — say 40 runs of up to 600
steps, fixed seeds — and report steps taken, dead ends and errors. It finds
what unit tests do not: unreachable content, crashes deep in a branch, and
the section 1.1 hang. **Pin the story seed** (the runtime seeds from the wall clock
by default) or failures are unreproducible.

A **dead end** — no choices offered while text is still pending — is a real
defect, distinct from a proper ending.

### 2.2 Debugging a hang

1. `faulthandler.dump_traceback_later(25, exit=True)` gives the stack.
2. Watch the output-token count from a thread. Steady growth with the step
   index frozen = one turn is emitting unboundedly.
3. Print the accumulated text — the repeating passage names the knot.
4. **Reduce to a minimal `.ink` and run it through real `inklecate`.** This is
   the step that decides whether it is an engine bug or a story bug. Here,
   inklecate looped identically, which proved the engine faithful and moved
   the fix into the story.

### 2.3 Recompile after every edit

Not at the end of a batch. Two self-introduced bugs here (a duplicated
`~ return`, a severed stitch chain) were caught only by immediate recompile —
neither was visible in the diff.

Compare against a **known error baseline**, not against zero, and check the
remaining error *set*, not just the count: counts can fall while a new
regression hides among the fixes. Note that a recorded baseline goes stale;
re-verify it rather than trusting a plan's stated number.

---

## Appendix — Checklists

**Before writing a choice**
- [ ] Guard is `+ { cond } [Label]`, never `{ cond: + [Label] }`
- [ ] `not (a == b)` and `not (list ? x)`, parenthesised
- [ ] It has a label — `+ -> target` is unusable
- [ ] It does not divert to `-> END` or `-> DONE` unless it really is an ending
- [ ] Divert into another knot's stitch uses `knot.stitch`
- [ ] A `-> scene ->` tunnel choice has a landing stitch
- [ ] Tunnel targets end in `->->`
- [ ] `*` is deliberate — is there still an exit once it is spent?

**Before adding a VAR**
- [ ] Something actually writes it
- [ ] The name matches every read exactly, and nothing already tracks the same
      fact under another spelling
- [ ] It doesn't collide with a stitch name or an `EXTERNAL` parameter name
- [ ] If two files touch it, it lives in the shared globals file
- [ ] Its sentinel (`0`, `""`, `-1`) cannot collide with a real value
- [ ] It is stored, not derivable from something already tracked

**Before calling it done**
- [ ] Compiles with zero errors *and* zero warnings
- [ ] Randomized playthrough: 0 dead ends, 0 errors
- [ ] Any new static check has been mutation-tested — reintroduce the bug,
      confirm red, restore

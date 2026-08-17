// Section 3 fixture: named knots, an unconditional divert loop back into
// its own knot, once-only pruning of a re-offered choice, and a divert to
// a second named knot. Compiled to section3_gather_loop.ink.json via the
// local inklecate build (claude_docs/tools/ink-reference). Opens with
// "-> room" rather than the knot header directly, matching the Section 2
// fixture-authoring note: inklecate -p never enters a story whose first
// line is a "== knot ==" header.
-> room

== room ==
You are in a room.
* [Look around] -> room
* [Leave] -> outside

== outside ==
You step outside.
-> DONE

// Section 1 fixture: pure navigation, no variables/functions/lists.
// Compiled to section1_simple.ink.json via the local inklecate build
// (claude_docs/tools/ink-reference), matching the plan's dev-machine-only
// test-oracle note in interactive_fiction_ink_engine.md.
//
// NOTE (2026-08-16): this story opens directly with "== start ==" as its
// first line, which inklecate's -p play mode never actually enters (the
// default entry point is top-level content, not the first named knot) —
// harmless here since Section 1's tests only inspect the compiled JSON
// directly and never call -p, but do not reuse this fixture for playback
// tests. See section2_glue.ink for a fixture written to be playable.
== start ==
First line.
Second line.
-> next_knot

== next_knot ==
Third line.
-> END

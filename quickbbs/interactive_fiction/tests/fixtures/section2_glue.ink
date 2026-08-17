// Section 2 fixture: output-stream glue/newline handling, no variables/choices.
// Compiled to section2_glue.ink.json via the local inklecate build
// (claude_docs/tools/ink-reference).
//
// NOTE: content must NOT open with a "== knot ==" header with nothing
// before it — inklecate's default entry point is the top-level flow, and a
// story that starts directly with a named knot header never gets played by
// -p (confirmed empirically 2026-08-16: both this fixture and Section 1's
// fixture originally had this bug, silently unnoticed in Section 1 because
// that section only inspected compiled JSON directly and never needed
// playback). Top-level content plays automatically; no leading divert
// needed as long as the first knot header isn't the very first line.
Hello <>
World, glued across a real newline.

Second paragraph after a real (non-glued) newline.

One <> Two <> Three, three glues on one line.

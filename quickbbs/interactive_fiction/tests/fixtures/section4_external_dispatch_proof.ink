Hand-authored compiled JSON (not run through inklecate) — isolates the
"x()" EXTERNAL-call dispatch path with a fallback whose only effect is a
global-variable write, so the assertion can check "did the call body
actually run" directly rather than through printed text, which the real
inklecate-compiled fixtures in this directory showed can coincidentally
match even when the call is silently skipped.

Ink-equivalent source:

VAR ran = false
~ ran = false
~ MARK_RAN()
-> END

EXTERNAL MARK_RAN()
=== function MARK_RAN()
    ~ ran = true

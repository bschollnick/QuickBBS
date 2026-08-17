// Section 5 fixture: a tunnel that itself tunnels into another knot
// before returning, exercising nested tunnel return addresses.
// Compiled to section5_nested_tunnel.ink.json via the local inklecate
// build (claude_docs/tools/ink-reference).
You start the journey.
-> outer ->
You finish the journey.
-> DONE

== outer ==
Entering the outer tunnel.
-> inner ->
Leaving the outer tunnel.
->->

== inner ==
Entering the inner tunnel.
->->

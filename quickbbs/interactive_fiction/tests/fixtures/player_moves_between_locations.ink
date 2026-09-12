// Two location knots, each registering the PLAYER's own arrival exactly as
// a converted game does. Step 11 (b): where_is("player") must follow the
// player from one to the other -- the regression this plan's Justification
// #2 is about, where presence was answered from a stale store instead of
// the location the player had actually walked into.
EXTERNAL set_location(character_id, location_id)
EXTERNAL where_is(character_id)

-> foyer

=== foyer ===
~ temp _here = set_location("player", "foyer")
You are in the foyer. Player is at: {where_is("player")}
+ [Go to the cellar] -> cellar

=== cellar ===
~ temp _here = set_location("player", "cellar")
You are in the cellar. Player is at: {where_is("player")}
-> DONE

=== function set_location(character_id, location_id) ===
~ return 0

=== function where_is(character_id) ===
~ return ""

EXTERNAL set_location(character_id, location_id)
EXTERNAL where_is(character_id)

~ temp ignored = set_location("traveler", "cellar")
Result: {where_is("traveler")}
-> DONE

=== function set_location(character_id, location_id) ===
~ return 0

=== function where_is(character_id) ===
~ return ""

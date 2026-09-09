EXTERNAL set_location_now(character_id, location_id)
EXTERNAL where_is_now(character_id)

~ temp ignored = set_location_now("traveler", "cellar")
Result: {where_is_now("traveler")}
-> DONE

=== function set_location_now(character_id, location_id) ===
~ return 0

=== function where_is_now(character_id) ===
~ return ""

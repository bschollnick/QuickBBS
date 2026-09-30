VAR destination = -> nowhere
VAR travel_text = ""
VAR current_location = "hall"

-> hall

=== nowhere ===
-> DONE

=== movement ===
{travel_text}
-> destination

=== hall ===
~ current_location = "hall"
You are in the hall.
+ [Wait] -> hall
+ [GO] -> movement

=== garden ===
~ current_location = "garden"
You are in the garden.
+ [Wait] -> garden
+ [GO] -> movement

=== cellar ===
~ current_location = "cellar"
You are in the cellar. It is the end.
-> END

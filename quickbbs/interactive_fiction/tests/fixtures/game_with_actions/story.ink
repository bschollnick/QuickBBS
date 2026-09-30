VAR sam_present = true
VAR chats = 0
VAR scene_shows = 0
-> scene

=== scene ===
~ scene_shows += 1
The shopkeeper eyes you warily.
+ [Browse] You browse. -> scene
+ [Leave] You leave. -> END

=== companion_actions ===
+ {sam_present} [Talk to Sam # group: sam # image: sam-face.png] -> talk_to_sam
+ {sam_present} [Send Sam home # group: sam] -> send_sam_home
+ [Check the time] -> check_time
-> DONE

=== talk_to_sam ===
~ chats += 1
Sam grins.
->->

=== send_sam_home ===
~ sam_present = false
Sam waves and heads home.
->->

=== check_time ===
It is noon.
->->

=== bell_rings ===
~ sam_present = false
The bell rings and Sam leaves.
-> scene

VAR sam_present = true
VAR sam_chatty = true
VAR ada_present = false
-> scene

=== scene ===
The shopkeeper eyes you warily.
+ [Browse] You browse. -> scene
+ [Leave] You leave. -> END

=== function sam_head_shot() ===
~ return "sam-face.png"

=== function ada_head_shot() ===
~ return "ada-face.png"

=== companion_actions ===
+ {sam_present and sam_chatty} [Talk to Sam # group: sam] -> talk_to_sam
-> DONE

=== talk_to_sam ===
Sam grins.
->->

EXTERNAL has_item(item)
EXTERNAL use_item(item)
VAR cellar_visits = 0
-> cellar

=== cellar ===
~ cellar_visits += 1
The cellar is dark.
+ {has_item("lantern")} [Light the lantern] The cellar glows. -> END
+ [Go back up] You climb back up. -> END

=== pack_actions ===
+ {has_item("lantern")} [Lend Sam the lantern # group: sam] -> lend_the_lantern
-> DONE

=== lend_the_lantern ===
~ temp lent = use_item("lantern")
You hand Sam the lantern.
->->

=== function has_item(item) ===
~ return false

=== function use_item(item) ===
~ return false

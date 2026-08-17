VAR flag = false

- (top)
    <- checker(-> top)
    * [A] -> DONE
    * [B] -> DONE

= checker(-> backto)
    * { flag } [Special]
        Special happened.
        -> backto

VAR x = 10
{outer(x)}
-> END

=== function outer(n)
~ temp result = inner(n) + 1
~ return result

=== function inner(n)
~ return n * 2

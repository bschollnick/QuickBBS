VAR count = 0

~ countdown(3)

Count is {count}.

-> END

=== function countdown(n)
{ n > 0:
    ~ count += 1
    ~ countdown(n - 1)
}

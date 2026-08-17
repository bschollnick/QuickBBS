VAR bit1 = false
VAR bit2 = false
VAR bit4 = false
VAR bit8 = false

~ setBits(0, 10, 8)

Bits: {bit1} {bit2} {bit4} {bit8}

-> END

=== function setBits(id, value, binaryValue)
    { value >= binaryValue:
        ~ value -= binaryValue
        {binaryValue:
        - 1: ~ bit1 = true
        - 2: ~ bit2 = true
        - 4: ~ bit4 = true
        - 8: ~ bit8 = true
        }
    }
    { binaryValue > 1:
        ~ setBits(id, value, binaryValue / 2)
    }

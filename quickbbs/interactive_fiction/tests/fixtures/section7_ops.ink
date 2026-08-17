LIST Wallet = Coins, Notes, Cards

VAR w = (Coins, Notes)

Count: {LIST_COUNT(w)}
Min: {LIST_MIN(w)}
Max: {LIST_MAX(w)}
All: {LIST_ALL(w)}
Value: {LIST_VALUE(Cards)}
Inverted: {LIST_INVERT(w)}

{w == (Coins, Notes): Equal!}
{w > (Coins): Greater!}

-> END

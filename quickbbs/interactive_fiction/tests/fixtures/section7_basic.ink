LIST Wallet = Coins, Notes, Cards

VAR w = (Coins)

You have {w}.

~ w += Notes

Now you have {w}.

{ w ? Coins: You still have coins. }

~ w -= Coins

{ w ? Coins: You still have coins. | Coins are gone. }

-> END

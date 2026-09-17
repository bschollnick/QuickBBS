"""`GameSavesDatabase` -- keeps game saves in `SaveState` rows.

Implements `if_session.game_saves.GameSavesProtocol` so the shared slot,
label, export and quicksave logic works against the database. The
library composes what a save contains; this decides only where it lives.

One instance serves one (user, story) pair, so `game_id` is carried for
the Protocol's sake and never used as a lookup key: the pair is already
pinned by the objects this was constructed with, and re-deriving it from
a string would create a second place for the identity to disagree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from if_session.game_saves import QUICKSAVE_SLOT

from interactive_fiction.models import SaveState

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser

    from interactive_fiction.models import Story


class GameSavesDatabase:
    """Game saves as `SaveState` rows, for one user playing one story."""

    def __init__(self, *, user: AbstractUser, story: Story) -> None:
        """Keep saves for `user`'s own play of `story`.

        Args:
            user: Whose saves these are.
            story: Which story they belong to.
        """
        self.user = user
        self.story = story

    def _saves(self) -> Any:
        """Return this user's own saves for this story."""
        return SaveState.objects.filter(user=self.user, story=self.story)

    def read_game_save(self, game_id: str, gamesave_slot: int) -> dict[str, Any] | None:
        """Return the game save in `gamesave_slot`, or None when empty."""
        del game_id  # The user/story pair already names the game.
        row = self._saves().filter(slot=gamesave_slot).first()
        if row is None:
            return None
        return {
            "gamesave_slot": row.slot,
            "label": row.label,
            "saved_at": row.updated_at.isoformat(),
            "turn_count": row.turn_count,
            "state": row.state,
        }

    def write_game_save(self, game_id: str, game_save: dict[str, Any]) -> None:
        """Store `game_save`, replacing whatever its slot held.

        `saved_at` is ignored: `updated_at` is `auto_now`, so the column
        owns the write time. The Protocol says what fields come back from
        a read, not where each one came from.
        """
        del game_id
        self._saves().update_or_create(
            user=self.user,
            story=self.story,
            slot=game_save["gamesave_slot"],
            defaults={
                "state": game_save["state"],
                "label": game_save["label"],
                "turn_count": game_save["turn_count"] if game_save["turn_count"] is not None else -1,
            },
        )

    def delete_game_save(self, game_id: str, gamesave_slot: int) -> None:
        """Delete this save slot's row. Deleting an empty slot is a no-op."""
        del game_id
        self._saves().filter(slot=gamesave_slot).delete()

    def game_save_exists(self, game_id: str, gamesave_slot: int) -> bool:
        """Return whether this save slot holds a row, without loading state."""
        del game_id
        return self._saves().filter(slot=gamesave_slot).exists()

    def summarize_game_saves(self, game_id: str) -> list[dict[str, Any]]:
        """Return a summary per occupied numbered save slot, lowest first.

        Excludes the quicksave, which would otherwise appear in the saves
        list and -- because -1 sorts first -- appear at the top of it.
        `.only()` keeps the JSONB `state` column out of the query, which
        is the whole reason this method exists apart from `read_game_save`.
        """
        del game_id
        rows = (
            self._saves()
            .exclude(slot=QUICKSAVE_SLOT)
            .order_by("slot")
            .only("slot", "label", "turn_count", "updated_at")
        )
        return [
            {
                "gamesave_slot": row.slot,
                "label": row.label,
                "saved_at": row.updated_at.isoformat(),
                "turn_count": row.turn_count,
            }
            for row in rows
        ]

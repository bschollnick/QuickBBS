"""User preferences models for QuickBBS Gallery.

Requires Django 6.1+: `UserPreferences.user` uses `models.DB_CASCADE`, a
DB-enforced `ON DELETE` constraint added in Django 6.1 that doesn't exist on
6.0 or earlier. Downgrading would mean switching back to the classic
`models.CASCADE` (app-level, not DB-enforced) and regenerating migrations.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class UserPreferences(models.Model):
    """
    Store user preferences for QuickBBS Gallery.

    Args:
        user: OneToOne relationship to AUTH_USER_MODEL
        show_duplicates: Whether to show duplicate files in gallery listings
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.DB_CASCADE, related_name="preferences")
    show_duplicates = models.BooleanField(default=False, help_text="Show duplicate files in gallery listings")
    # Interactive Fiction reader display preferences (interactive_fiction
    # Step 8) — extends this existing per-user mechanism (auto-create
    # signal already in place, see signals.py) rather than inventing an
    # IF-local preferences model.
    if_font_size = models.CharField(
        max_length=10,
        choices=[("small", "Small"), ("medium", "Medium"), ("large", "Large")],
        default="medium",
        help_text="Text size for the Interactive Fiction play view",
    )
    if_text_width = models.CharField(
        max_length=10,
        choices=[("narrow", "Narrow"), ("medium", "Medium"), ("wide", "Wide")],
        default="medium",
        help_text="Text column width for the Interactive Fiction play view",
    )

    class Meta:
        """Model metadata."""

        verbose_name = "User Preferences"
        verbose_name_plural = "User Preferences"

    def __str__(self) -> str:
        """
        Return string representation of user preferences.

        Returns:
            String showing username and preferences
        """
        return f"{self.user.username} preferences"

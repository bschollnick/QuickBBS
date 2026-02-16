"""User preferences models for QuickBBS Gallery."""

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

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preferences")
    show_duplicates = models.BooleanField(default=False, help_text="Show duplicate files in gallery listings")

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

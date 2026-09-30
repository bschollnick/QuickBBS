"""Signals for user preferences app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from user_preferences.models import UserPreferences

if TYPE_CHECKING:
    from django.contrib.auth.models import _User

User = get_user_model()


@receiver(post_save, sender=User)
def create_user_preferences(instance: _User, created: bool, **kwargs) -> None:
    """
    Create UserPreferences when a new User is created.

    Args:
        instance: The actual User instance being saved
        created: Boolean indicating if this is a new user
        **kwargs: The signal's other keyword arguments, including `sender`
    """
    if created:
        UserPreferences.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_preferences(instance: _User, **kwargs) -> None:
    """
    Save UserPreferences when User is saved.

    Args:
        instance: The actual User instance being saved
        **kwargs: The signal's other keyword arguments, including `sender`
    """
    # Create preferences if they don't exist (for existing users)
    if not hasattr(instance, "preferences"):
        UserPreferences.objects.create(user=instance)
    else:
        instance.preferences.save()

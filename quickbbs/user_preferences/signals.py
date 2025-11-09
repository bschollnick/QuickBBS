"""Signals for user preferences app."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from user_preferences.models import UserPreferences


@receiver(post_save, sender=User)
def create_user_preferences(sender: type[User], instance: User, created: bool, **kwargs) -> None:
    """
    Create UserPreferences when a new User is created.

    Args:
        sender: The User model class
        instance: The actual User instance being saved
        created: Boolean indicating if this is a new user
        **kwargs: Additional keyword arguments from the signal
    """
    if created:
        UserPreferences.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_preferences(sender: type[User], instance: User, **kwargs) -> None:
    """
    Save UserPreferences when User is saved.

    Args:
        sender: The User model class
        instance: The actual User instance being saved
        **kwargs: Additional keyword arguments from the signal
    """
    # Create preferences if they don't exist (for existing users)
    if not hasattr(instance, "preferences"):
        UserPreferences.objects.create(user=instance)
    else:
        instance.preferences.save()

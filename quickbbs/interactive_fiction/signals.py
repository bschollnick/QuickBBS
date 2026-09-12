"""Signal receivers for the interactive_fiction app."""

from __future__ import annotations

from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver

from interactive_fiction.engine_api import clear_api_descriptor_cache
from interactive_fiction.models import Story


@receiver(post_save, sender=Story)
def _clear_api_descriptor_cache_on_story_save(sender: type[Story], **kwargs: Any) -> None:
    """Drop the cached plugin-discovery result whenever a `Story` is saved.

    `is_engine_trusted` is a plain admin-editable field with no custom
    `save()` override, so `post_save` is the only hook that reliably fires
    on every real change to it, however it happens (admin, shell, future
    code) — cheaper to over-invalidate on every save than to miss one.
    """
    del sender, kwargs
    clear_api_descriptor_cache()

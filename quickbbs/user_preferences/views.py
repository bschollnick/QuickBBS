"""Views for user preferences."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from quickbbs.cache_registry import layout_manager_cache
from user_preferences.models import UserPreferences


@login_required
def toggle_show_duplicates(request: HttpRequest) -> HttpResponse:
    """
    Toggle the show_duplicates preference for the current user.

    Args:
        request: The HTTP request object

    Returns:
        Redirect to the referring page or home
    """
    # Use transaction to ensure immediate commit
    with transaction.atomic():
        # Get or create preferences for the user
        preferences, _created = UserPreferences.objects.get_or_create(user=request.user)

        # Store old value before toggle for selective cache clearing
        old_show_duplicates = preferences.show_duplicates

        # Toggle the setting
        preferences.show_duplicates = not preferences.show_duplicates
        preferences.save()

    # Clear the user's cached preference so the next page load sees the new value
    from frontend.views import _user_pref_cache

    _user_pref_cache.pop(request.user.pk, None)

    # Selectively clear layout_manager_cache entries with the old show_duplicates value.
    # This is more efficient than clearing the entire cache (preserves ~50% of entries).
    # Cache keys are tuples: (page_number, directory_pk, sort_ordering, show_duplicates)
    keys_to_delete = [key for key in list(layout_manager_cache.keys()) if len(key) >= 4 and key[3] == old_show_duplicates]
    for key in keys_to_delete:
        del layout_manager_cache[key]

    # Get the referer URL or default to home
    referer = request.META.get("HTTP_REFERER", "/")

    # Return redirect response with cache-control headers
    response = redirect(referer)

    # Prevent caching of the toggle response
    response["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"

    return response

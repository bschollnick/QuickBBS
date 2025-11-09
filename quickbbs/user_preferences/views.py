"""Views for user preferences."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse

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
        preferences, created = UserPreferences.objects.get_or_create(user=request.user)

        # Toggle the setting
        preferences.show_duplicates = not preferences.show_duplicates
        preferences.save()

    # Clear layout_manager cache to force refresh with new preference
    from frontend.managers import layout_manager_cache

    layout_manager_cache.clear()

    # Return success - JavaScript will handle the page reload
    response = JsonResponse({"success": True, "show_duplicates": preferences.show_duplicates})

    # Prevent caching of the toggle response
    response["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"

    return response

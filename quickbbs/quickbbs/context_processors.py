"""Context processors for the Django (non-Jinja2) template engine.

The Jinja2 engine gets these same values via TEMPLATES["Jinja2"]["OPTIONS"]["constants"]
in settings.py. Django-engine templates (currently just django-allauth's account
pages) need this separate processor since "constants" is a Jinja2-only mechanism.
"""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest


def site_branding(request: HttpRequest) -> dict[str, object]:
    """Expose site name and header image settings to Django-engine templates.

    Args:
        request: The current request (unused, required by context processor signature).

    Returns:
        Dict with site_name and site_header_image_settings for template use.
    """
    return {
        "site_name": settings.SITE_NAME,
        "site_header_image_settings": settings.SITE_HEADER_IMAGE_SETTINGS,
    }

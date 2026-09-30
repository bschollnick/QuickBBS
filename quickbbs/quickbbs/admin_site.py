"""The project's admin site: Django's own, with a vacuum-status widget on its index page."""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest
from django.template.response import TemplateResponse

from quickbbs.tasks import get_vacuum_candidates


class QuickbbsAdminSite(admin.AdminSite):
    """The default admin site, installed as `admin.site` by `quickbbs.apps.QuickbbsAdminConfig`.

    Its index page lists PostgreSQL tables due a vacuum, from the same
    `get_vacuum_candidates()` the weekly_vacuum_check task logs, so the page
    and the logged warning agree.
    """

    def index(self, request: HttpRequest, extra_context: dict[str, Any] | None = None) -> TemplateResponse:
        """Render the admin index with `vacuum_candidates` in its context."""
        return super().index(request, {**(extra_context or {}), "vacuum_candidates": get_vacuum_candidates()})

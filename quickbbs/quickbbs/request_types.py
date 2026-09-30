"""Request types for views: what the middleware adds to every request."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpRequest
from django_htmx.middleware import HtmxDetails

if TYPE_CHECKING:
    from django.contrib.auth.models import _User


class HtmxHttpRequest(WSGIRequest):
    """A request after `django_htmx.middleware.HtmxMiddleware`, which sets `htmx` on every one."""

    htmx: HtmxDetails


def signed_in_user(request: HttpRequest) -> _User:
    """Return the signed-in user behind a `@login_required` view.

    `request.user` is typed as possibly anonymous because the type checker
    cannot see the decorator; checking it here narrows the type once.

    Raises:
        PermissionDenied: The request has no signed-in user.
    """
    if not request.user.is_authenticated:
        raise PermissionDenied("This view requires a signed-in user.")
    return request.user

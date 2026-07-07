"""Middleware that dynamically admits local-network hosts to ALLOWED_HOSTS."""

from django.conf import settings
from django.core.exceptions import PermissionDenied


class FilterHostMiddleware:
    """Admit .local and 192.168.* hosts to ALLOWED_HOSTS; deny everything else.

    Note: This is an old-style middleware (process_request only, no __init__
    with get_response); it is not currently listed in settings.MIDDLEWARE.
    """

    def process_request(self, request):
        """Append trusted local hosts to ALLOWED_HOSTS or raise PermissionDenied.

        Args:
            request: Incoming HttpRequest; HTTP_HOST is inspected.

        Returns:
            None — the request continues through the middleware chain.

        Raises:
            PermissionDenied: If the host is neither a .local name, a
                192.168.* address, nor already in ALLOWED_HOSTS.
        """
        host = request.META.get("HTTP_HOST")
        host = host[0 : host.find(":")]
        if host.endswith(".local"):
            if host not in settings.ALLOWED_HOSTS:
                settings.ALLOWED_HOSTS.append(host)
        elif host[:7] == "192.168":  # if the host starts with 192.168 then add to the allowed hosts
            if host not in settings.ALLOWED_HOSTS:
                settings.ALLOWED_HOSTS.append(host)
        else:
            if host not in settings.ALLOWED_HOSTS:
                raise PermissionDenied
        # print "hosts: %s\n" % settings.ALLOWED_HOSTS
        return None

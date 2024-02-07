"""
Serve Resources, and Static documents from Django
"""

import os.path

from django.conf import settings
from django.http import Http404  # , HttpResponseBadRequest, HttpResponseNotFound,
from django.views.static import serve


# JsonResponse)


def resources(request, pathstr=None) -> object:
    """
    Serve the resources
    """
    if pathstr is not None:
        album_viewing = os.path.join(settings.RESOURCES_PATH, pathstr)
        if not os.path.exists(album_viewing):
            print(f"File Not Found - {album_viewing}")
        return serve(
            request, os.path.basename(album_viewing), os.path.dirname(album_viewing)
        )
    return Http404


def static(request, pathstr=None) -> object:
    """
    Serve the Static Resources
    """
    if pathstr is not None:
        album_viewing = os.path.join(settings.STATIC_PATH, pathstr)
        if not os.path.exists(album_viewing):
            print(f"File Not Found - {album_viewing}")
        return serve(
            request, os.path.basename(album_viewing), os.path.dirname(album_viewing)
        )
    return Http404

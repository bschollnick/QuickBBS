"""
Serve Resources, and Static documents from Django
"""

import os.path

from django.conf import settings
from django.http import Http404
from django.views.static import serve


async def static_or_resources(request, pathstr=None) -> object:
    """
    Serve the resources or static file
    """
    if pathstr is not None:
        album_viewing = os.path.join(settings.RESOURCES_PATH, pathstr)
        try:
            return serve(
                request, os.path.basename(album_viewing), os.path.dirname(album_viewing)
            )
        except IOError:
            print(f"File Not Found - {album_viewing}")
    return Http404

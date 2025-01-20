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
        resource_file = os.path.join(settings.RESOURCES_PATH, pathstr)
        static_file = os.path.join(settings.STATIC_ROOT, pathstr)
        if os.path.exists(resource_file):
            return serve(
                request, os.path.basename(resource_file), os.path.dirname(resource_file)
                )
        else:
            return serve(
                    request, os.path.basename(static_file), os.path.dirname(static_file)
                )
    return Http404

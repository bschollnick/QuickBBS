"""
Serve Resources, and Static documents from Django
"""

import os.path

from django.conf import settings
from django.contrib.staticfiles.finders import find
from django.contrib.staticfiles.views import serve as staticfiles_serve
from django.http import FileResponse, Http404
from django.views.static import serve


def static_or_resources(request, pathstr=None):
    """
    Alternative approach better suited for development environments.

    Uses Django's staticfiles finders which can locate files from multiple
    static directories (including app-specific static folders).
    """
    if pathstr is None:
        raise Http404("No path specified")

    # Then use Django's finder-based static serving (only for DEBUG mode)
    # if settings.DEBUG:
    #     print("A")
    #     # This will check all static file locations configured in STATICFILES_DIRS
    #     return staticfiles_serve(request, pathstr)
    # else:
    # In production, use the collected static files
    static_file = os.path.join(settings.STATIC_ROOT, pathstr)
    if os.path.exists(static_file) and os.path.isfile(static_file):
        return FileResponse(open(static_file, "rb"))
    resource_file = os.path.join(settings.RESOURCES_PATH, pathstr)
    if os.path.exists(resource_file) and os.path.isfile(resource_file):
        return FileResponse(open(resource_file, "rb"))

    raise Http404(f"File {pathstr} not found in resources or static files")

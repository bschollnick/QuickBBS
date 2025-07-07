"""
Serve Resources, and Static documents from Django
"""

import io
import os.path
from datetime import timedelta

from django.conf import settings
from django.contrib.staticfiles.finders import find
from django.contrib.staticfiles.views import serve as staticfiles_serve
from django.http import FileResponse, Http404, HttpResponseNotModified
from django.utils import timezone
from django.views.static import serve
from ranged_fileresponse import RangedFileResponse


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


def send_file_response(
    filename,
    content_to_send,
    mtype,
    attachment,
    last_modified,
    expiration=300,
    request=None,
):
    """
        Output a http response header, for an image attachment.

    Args:

        Returns:
            object::
                The Django response object that contains the attachment and header

        Raises:
            None

        Examples
        --------
        send_thumbnail()

    """
    if not request:
        response = FileResponse(
            content_to_send,
            content_type=mtype,
            as_attachment=attachment,
            filename=filename,
        )
    else:
        response = RangedFileResponse(
            request,
            file=content_to_send,  # , buffering=1024*8),
            content_type=mtype,
            as_attachment=attachment,
            filename=filename,
        )
    # response["Content-Type"] = mtype                  # set in FileResponse
    # response["Content-Length"] = len(self.thumbnail)  # auto set from FileResponse
    response["Cache-Control"] = f"public, max-age={expiration}"
    return response

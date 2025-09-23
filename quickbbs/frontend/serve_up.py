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


def static_or_resources(request, pathstr: str | None = None):
    """
    Serve static or resource files from configured directories.

    Uses Django's staticfiles finders which can locate files from multiple
    static directories (including app-specific static folders).

    :param request: Django request object
    :param pathstr: Path to the static or resource file
    :return: FileResponse containing the requested file
    :raises Http404: If the file is not found in static or resources directories
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
    filename: str,
    content_to_send,
    mtype: str,
    attachment: bool,
    last_modified,
    expiration: int = 300,
    request=None,
):
    """
    Send a file response with appropriate headers and caching.

    :param filename: Name of the file to send
    :param content_to_send: File handle or bytes-like object to send
    :param mtype: MIME type of the file
    :param attachment: Whether to send as attachment (download) or inline
    :param last_modified: Last modified timestamp for the file
    :param expiration: Cache expiration time in seconds (default: 300)
    :param request: Optional Django request object for range requests
    :return: FileResponse or RangedFileResponse with the file content

    Note:
        The file handle passed in content_to_send will be closed automatically
        by the response object. Do not use context managers for file handles.
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

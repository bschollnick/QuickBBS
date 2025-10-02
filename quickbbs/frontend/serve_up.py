"""
Serve Resources, and Static documents from Django
"""

import asyncio
import io
import os.path
from datetime import timedelta

import aiofiles
from asgiref.sync import iscoroutinefunction
from django.conf import settings
from django.contrib.staticfiles.finders import find
from django.contrib.staticfiles.views import serve as staticfiles_serve
from django.http import FileResponse, Http404, HttpResponseNotModified
from django.utils import timezone
from django.views.static import serve
from ranged_fileresponse import RangedFileResponse


def static_or_resources(request, pathstr: str | None = None):
    """
    Serve static or resource files from configured directories (WSGI sync mode).

    Uses Django's staticfiles finders which can locate files from multiple
    static directories (including app-specific static folders).

    Args:
        request: Django request object
        pathstr: Path to the static or resource file

    Returns:
        FileResponse containing the requested file

    Raises:
        Http404: If the file is not found in static or resources directories
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


async def async_static_or_resources(request, pathstr: str | None = None):
    """
    Serve static or resource files from configured directories (ASGI async mode).

    Uses async file I/O for better performance in async contexts.

    Args:
        request: Django request object
        pathstr: Path to the static or resource file

    Returns:
        FileResponse containing the requested file

    Raises:
        Http404: If the file is not found in static or resources directories
    """
    if pathstr is None:
        raise Http404("No path specified")

    # In production, use the collected static files
    static_file = os.path.join(settings.STATIC_ROOT, pathstr)
    if os.path.exists(static_file) and os.path.isfile(static_file):
        async with aiofiles.open(static_file, "rb") as f:
            content = await f.read()
        return FileResponse(io.BytesIO(content))

    resource_file = os.path.join(settings.RESOURCES_PATH, pathstr)
    if os.path.exists(resource_file) and os.path.isfile(resource_file):
        async with aiofiles.open(resource_file, "rb") as f:
            content = await f.read()
        return FileResponse(io.BytesIO(content))

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
    Send a file response with appropriate headers and caching (WSGI sync mode).

    Args:
        filename: Name of the file to send
        content_to_send: File handle or bytes-like object to send
        mtype: MIME type of the file
        attachment: Whether to send as attachment (download) or inline
        last_modified: Last modified timestamp for the file
        expiration: Cache expiration time in seconds (default: 300)
        request: Optional Django request object for range requests

    Returns:
        FileResponse or RangedFileResponse with the file content

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


async def async_send_file_response(
    filename: str,
    filepath: str,
    mtype: str,
    attachment: bool,
    last_modified,
    expiration: int = 300,
    request=None,
):
    """
    Send a file response with appropriate headers and caching (ASGI async mode).

    Uses async file I/O to read file contents without blocking.

    Args:
        filename: Name of the file to send
        filepath: Path to the file to send
        mtype: MIME type of the file
        attachment: Whether to send as attachment (download) or inline
        last_modified: Last modified timestamp for the file
        expiration: Cache expiration time in seconds (default: 300)
        request: Optional Django request object for range requests

    Returns:
        FileResponse or RangedFileResponse with the file content

    Note:
        For async mode, pass the file path instead of file handle.
        The file will be read asynchronously and closed properly.
    """
    # Read file asynchronously
    async with aiofiles.open(filepath, "rb") as f:
        content = await f.read()

    # Create response with in-memory content
    if not request:
        response = FileResponse(
            io.BytesIO(content),
            content_type=mtype,
            as_attachment=attachment,
            filename=filename,
        )
    else:
        response = RangedFileResponse(
            request,
            file=io.BytesIO(content),
            content_type=mtype,
            as_attachment=attachment,
            filename=filename,
        )
    response["Cache-Control"] = f"public, max-age={expiration}"
    return response

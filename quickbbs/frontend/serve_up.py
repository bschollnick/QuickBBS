"""
Serve Resources, and Static documents from Django
"""

import io
import os.path

import aiofiles
from asgiref.sync import sync_to_async
from django.conf import settings
from django.http import FileResponse, Http404
from ranged_fileresponse import RangedFileResponse


def _locate_static_or_resource_file(pathstr: str) -> str | None:
    """
    Locate file in static or resources directories.

    ASYNC-SAFE: Pure function with filesystem checks only

    Args:
        pathstr: Path to the static or resource file

    Returns:
        Absolute path to file if found, None otherwise
    """
    # Check static directory first
    static_file = os.path.join(settings.STATIC_ROOT, pathstr)
    if os.path.exists(static_file) and os.path.isfile(static_file):
        return static_file

    # Check resources directory second
    resource_file = os.path.join(settings.RESOURCES_PATH, pathstr)
    if os.path.exists(resource_file) and os.path.isfile(resource_file):
        return resource_file

    return None


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

    # Locate the file using shared logic
    file_path = _locate_static_or_resource_file(pathstr)
    if file_path:
        return FileResponse(open(file_path, "rb"))

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

    # Locate the file using shared logic
    file_path = _locate_static_or_resource_file(pathstr)
    if file_path:
        async with aiofiles.open(file_path, "rb") as f:
            content = await f.read()
        return FileResponse(io.BytesIO(content))

    raise Http404(f"File {pathstr} not found in resources or static files")


def _build_file_response(content_to_send, filename: str, mtype: str, attachment: bool, expiration: int, request=None):
    """
    Build FileResponse or RangedFileResponse with shared logic.

    ASYNC-SAFE: Pure function with no I/O operations

    Args:
        content_to_send: File handle or bytes-like object to send
        filename: Name of the file to send
        mtype: MIME type of the file
        attachment: Whether to send as attachment (download) or inline
        expiration: Cache expiration time in seconds
        request: Optional Django request object for range requests

    Returns:
        FileResponse or RangedFileResponse with appropriate headers
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
            file=content_to_send,
            content_type=mtype,
            as_attachment=attachment,
            filename=filename,
        )
    response["Cache-Control"] = f"public, max-age={expiration}"
    return response


async def async_send_file_response(filename: str, filepath: str, mtype: str, attachment: bool, expiration: int = 300, request=None):
    """
    Send a file response with appropriate headers and caching (async version).

    Uses sync I/O in thread pool for better performance with OS-cached files.

    Args:
        filename: Name of the file to send
        filepath: Path to the file to send
        mtype: MIME type of the file
        attachment: Whether to send as attachment (download) or inline
        expiration: Cache expiration time in seconds (default: 300)
        request: Optional Django request object for range requests

    Returns:
        FileResponse or RangedFileResponse with the file content
    """

    def _read_file():
        with open(filepath, "rb") as f:
            return f.read()

    # Read file synchronously in thread pool - faster for OS-cached files
    content = await sync_to_async(_read_file)()

    # Use shared response builder with in-memory content
    return _build_file_response(io.BytesIO(content), filename, mtype, attachment, expiration, request)


def send_file_response(filename: str, content_to_send, mtype: str, attachment: bool, expiration: int = 300, request=None):
    """
    Send a file response with appropriate headers and caching (sync version).

    Args:
        filename: Name of the file to send
        content_to_send: File handle or bytes-like object to send
        mtype: MIME type of the file
        attachment: Whether to send as attachment (download) or inline
        expiration: Cache expiration time in seconds (default: 300)
        request: Optional Django request object for range requests

    Returns:
        FileResponse or RangedFileResponse with the file content

    Note:
        The file handle passed in content_to_send will be closed automatically
        by the response object. Do not use context managers for file handles.
    """
    # Use shared response builder
    return _build_file_response(content_to_send, filename, mtype, attachment, expiration, request)

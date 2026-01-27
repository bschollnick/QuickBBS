"""
Serve Resources, and Static documents from Django
"""

import io
import os.path

import aiofiles
from django.conf import settings
from django.http import FileResponse, Http404

# TODO: Examine django-sage-streaming as a replacement for RangedFileResponse
# https://github.com/sageteamorg/django-sage-streaming
from ranged_fileresponse import RangedFileResponse

# Translation table for sanitizing filenames - faster than regex
# Removes: control chars (0x00-0x1F, 0x7F), angle brackets (<>)
# Replaces: semicolon with underscore (header parameter separator)
_SANITIZE_TABLE = str.maketrans(
    {
        ";": "_",
        "<": None,
        ">": None,
        "\x7f": None,
        **{chr(i): None for i in range(0x20)},
    }
)


def sanitize_filename_for_http(filename: str) -> str:
    """
    Sanitize filename for safe use in Content-Disposition headers.

    Removes control characters and characters that could cause header injection.
    This is a simplified version - for full implementation see quickbbs.fileindex.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename safe for HTTP headers
    """
    # Use translate() - faster than regex for character removal/replacement
    filename = filename.translate(_SANITIZE_TABLE).strip()
    return filename or "download.bin"


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
    # SECURITY: Sanitize filename to prevent header injection
    safe_filename = sanitize_filename_for_http(filename)

    if not request:
        response = FileResponse(
            content_to_send,
            content_type=mtype,
            as_attachment=attachment,
            filename=safe_filename,
        )
    else:
        response = RangedFileResponse(
            request,
            file=content_to_send,
            content_type=mtype,
            as_attachment=attachment,
            filename=safe_filename,
        )
    response["Cache-Control"] = f"public, max-age={expiration}"

    # Skip ETag generation to avoid ConditionalGetMiddleware overhead
    # ETags for large files require reading content, which is expensive
    if "ETag" in response:
        del response["ETag"]

    return response


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

"""
Serve Resources, and Static documents from Django
"""

import io
import os
import os.path

import aiofiles
from django.conf import settings
from django.http import FileResponse, Http404, StreamingHttpResponse

# TODO: Examine django-sage-streaming as a replacement for RangedFileResponse
# https://github.com/sageteamorg/django-sage-streaming
from ranged_fileresponse import RangedFileResponse

RANGE_CHUNK_SIZE = 65536  # 64 KB per async read


async def _async_file_range_iterator(path: str, start: int, stop: int):
    """
    Async generator that yields chunks of a file between byte positions.

    Args:
        path: Absolute path to the file.
        start: First byte to send (inclusive).
        stop: Last byte to send (exclusive).

    Yields:
        bytes chunks of up to RANGE_CHUNK_SIZE each.
    """
    async with aiofiles.open(path, "rb") as f:
        await f.seek(start)
        remaining = stop - start
        while remaining > 0:
            chunk = await f.read(min(RANGE_CHUNK_SIZE, remaining))
            if not chunk:
                break
            yield chunk
            remaining -= len(chunk)


def _parse_range_header(header: str, file_size: int) -> tuple[int, int] | None:
    """
    Parse an HTTP Range header and return (start, stop) as a half-open interval.

    Only handles single-range byte requests (the only form browsers send for video).
    Returns None for malformed or unsatisfiable headers.

    Args:
        header: Value of the HTTP Range header (e.g. "bytes=0-1023").
        file_size: Total size of the file in bytes.

    Returns:
        (start, stop) tuple where stop is exclusive, or None if invalid.
    """
    if not header or not header.startswith("bytes="):
        return None
    range_spec = header[6:]
    if "," in range_spec:
        return None  # multipart ranges not supported
    start_str, _, end_str = range_spec.partition("-")
    try:
        if not start_str:
            # suffix form: bytes=-N  (last N bytes)
            start = file_size - int(end_str)
            stop = file_size
        else:
            start = int(start_str)
            stop = int(end_str) + 1 if end_str else file_size
    except ValueError:
        return None
    if start < 0 or start >= file_size or start >= stop:
        return None
    stop = min(stop, file_size)
    return start, stop


def build_async_ranged_response(
    request,
    path: str,
    file_size: int,
    content_type: str,
    filename: str,
    expiration: int,
) -> StreamingHttpResponse:
    """
    Build a memory-efficient async streaming response for ranged video requests.

    Uses an async generator (aiofiles) so Django's ASGI handler can consume it
    chunk-by-chunk without ever loading the full file into memory.  Handles
    both initial full-file requests (no Range header) and byte-range requests
    (Range header present, responds 206 Partial Content).

    Args:
        request: Django request object.
        path: Absolute path to the video file on disk.
        file_size: Size of the file in bytes (from os.fstat — no disk read).
        content_type: MIME type string (e.g. "video/mp4").
        filename: Sanitized filename for Content-Disposition header.
        expiration: Cache-Control max-age in seconds.

    Returns:
        StreamingHttpResponse with appropriate status (200 or 206) and headers.
    """
    safe_filename = sanitize_filename_for_http(filename)
    range_header = request.META.get("HTTP_RANGE", "")
    parsed = _parse_range_header(range_header, file_size) if range_header else None

    if parsed is None:
        # No valid Range header — serve the full file as a streaming 200
        start, stop = 0, file_size
        status = 200
    else:
        start, stop = parsed
        status = 206

    response = StreamingHttpResponse(
        _async_file_range_iterator(path, start, stop),
        status=status,
        content_type=content_type,
    )
    response["Accept-Ranges"] = "bytes"
    response["Content-Length"] = stop - start
    response["Cache-Control"] = f"public, max-age={expiration}"
    if status == 206:
        response["Content-Range"] = f"bytes {start}-{stop - 1}/{file_size}"
    if safe_filename:
        response["Content-Disposition"] = f'inline; filename="{safe_filename}"'
    return response


class SizedFileWrapper:
    """
    Wrap a file handle with a pre-computed `.size` attribute.

    RangedFileResponse (via RangedFileReader) checks for `.size` on the file
    object. If absent, it falls back to ``len(self.f.read())`` — which reads
    the *entire* file into memory just to measure it. For large videos this
    causes memory usage to balloon proportionally to file size.

    Passing the OS-reported file size avoids that read entirely.
    """

    __slots__ = ("_f", "size")

    def __init__(self, file_handle, size: int) -> None:
        """Wrap an open file handle and record its size.

        Args:
            file_handle: Open binary file object to delegate to.
            size: OS-reported file size in bytes.
        """
        self._f = file_handle
        self.size = size

    def read(self, *args):
        """Delegate read() to the wrapped file handle."""
        return self._f.read(*args)

    def seek(self, *args):
        """Delegate seek() to the wrapped file handle."""
        return self._f.seek(*args)

    def tell(self):
        """Delegate tell() to the wrapped file handle."""
        return self._f.tell()

    def close(self):
        """Delegate close() to the wrapped file handle."""
        return self._f.close()

    def __iter__(self):
        return iter(self._f)


def open_sized_file(path: str) -> SizedFileWrapper:
    """
    Open a file for reading and return a SizedFileWrapper.

    Args:
        path: Absolute path to the file.

    Returns:
        SizedFileWrapper with `.size` pre-populated from OS stat.
    """
    fh = open(path, "rb")  # pylint: disable=consider-using-with
    size = os.fstat(fh.fileno()).st_size
    return SizedFileWrapper(fh, size)


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

    Removes control characters and characters that could cause header injection
    or filename confusion. This prevents:
    - HTTP header injection (via newlines, semicolons)
    - Filename truncation (via angle brackets)
    - Control character exploits

    Args:
        filename: Original filename from filesystem

    Returns:
        Sanitized filename safe for HTTP headers

    Example:
        >>> sanitize_filename_for_http("test.pdf")
        'test.pdf'
        >>> sanitize_filename_for_http("file;evil.exe")
        'file_evil.exe'
        >>> sanitize_filename_for_http("<script>alert(1)</script>.txt")
        'scriptalert(1)script.txt'
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

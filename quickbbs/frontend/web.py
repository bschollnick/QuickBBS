"""
Web functionality
"""

import logging
import os
import re

from django.contrib.auth import authenticate, login
from django.http import (
    FileResponse,
    Http404,
    StreamingHttpResponse,
)

# from django.conf import settings
from django.views.decorators.cache import never_cache
from filetypes.models import filetypes

logger = logging.getLogger(__name__)

RANGE_RE = re.compile(r"bytes\s*=\s*(\d+)\s*-\s*(\d*)", re.I)


def verify_login_status(request, force_login=False) -> bool:
    """
    Verify login status, if not logged in redirect to login screen.

    args:
        request (obj) : Django Request object
        force_login (bool) : tbd

    """
    username = request.POST["username"]
    password = request.POST["password"]
    user = authenticate(username=username, password=password)
    if user is not None:
        if user.is_active:
            login(request, user)
            # Redirect to a success page.
        else:
            logger.warning("Login attempt for disabled account: %s", username)
            # Return a 'disabled account' error message
    else:
        logger.warning("Invalid login attempt for username: %s", username)
        # Return an 'invalid login' error message.


def g_option(request, option_name, def_value):
    """
    Return the option from the request.get?

    Args:
        request (obj) : Django Request Object
        option_name (str) : The option name to read from the request
        def_value (str) : The default value to use, if not defined in request.

    returns:
        Str : The string read from the request object (or default value)
    """
    return request.GET.get(option_name, def_value)


@never_cache
def respond_as_attachment(request, file_path, original_filename):
    """
    Send a file as an attachment download response.

    Args:
        request: Django request object
        file_path: Path to the file directory
        original_filename: Name of the file to send

    Returns:
        FileResponse with the file as attachment

    Raises:
        Http404: If the file is not found
    """
    filename = os.path.join(file_path, original_filename)
    fext = os.path.splitext(filename)[1].lower()
    mtype = filetypes.return_filetype(fext).mimetype
    if mtype is None:
        mtype = "application/octet-stream"
    try:
        response = FileResponse(
            open(filename, "rb"),
            content_type=mtype,
            as_attachment=True,
            filename=filename,
        )
        return response
    except FileNotFoundError as exc:
        raise Http404("File not found") from exc


def file_iterator(file_path, chunk_size=8192, offset=0, length=None):
    """
    # https://www.djangotricks.com/tricks/4S7qbNhtUeAD/

    """
    with open(file_path, "rb") as f:
        f.seek(offset, os.SEEK_SET)
        remaining = length
        while True:
            bytes_length = chunk_size if remaining is None else min(remaining, chunk_size)
            data = f.read(bytes_length)
            if not data:
                break
            if remaining:
                remaining -= len(data)
            yield data


def stream_video(request, fqpn, content_type="video/mp4"):
    """
    https://www.djangotricks.com/tricks/Jw4jNwFziSXD/
        request:
    Returns:
    """
    # path = str(settings.BASE_DIR / "data" / "earth.mp4")
    # content_type = "video/mp4"
    range_header = request.headers.get("range", "").strip()
    range_match = RANGE_RE.match(range_header)
    size = os.path.getsize(fqpn)
    logger.debug("Streaming video with content type: %s", content_type)
    if range_match:
        first_byte, last_byte = range_match.groups()
        first_byte = int(first_byte) if first_byte else 0
        last_byte = first_byte + 1024 * 1024 * 8  # The max volume of the response body is 8M per piece
        if last_byte >= size:
            last_byte = size - 1
        length = last_byte - first_byte + 1
        response = StreamingHttpResponse(
            file_iterator(fqpn, offset=first_byte, length=length),
            status=206,
            content_type=content_type,
        )
        response["Content-Range"] = f"bytes {first_byte}-{last_byte}/{size}"

    else:
        response = StreamingHttpResponse(
            file_iterator(fqpn, offset=0, length=size),
            content_type=content_type,
        )
    response["Accept-Ranges"] = "bytes"
    return response

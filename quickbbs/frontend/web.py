"""
Web functionality
"""

import io
import mimetypes
import os
import re
from wsgiref.util import FileWrapper

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.http import FileResponse, StreamingHttpResponse
# from django.conf import settings
from django.views.decorators.cache import never_cache

# from ranged_fileresponse import RangedFileResponse


# import RangedFileResponse
# from ranged_fileresponse.local import RangedLocalFileResponse
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
            print("disabled account")
            # Return a 'disabled account' error message
    else:
        print("Invalid login")
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


# def return_inline_attach(filename, binaryblob):
#     """
#      Output a http response header, for an image attachment.

#     Args:
#          filename (str): Filename of the file to be sent as the attachment name
#          binaryblob (bin): The blob of data that is the image file

#      Returns:
#          object::
#              The Django response object that contains the attachment and header

#      Raises:
#          None

#      Examples
#      --------
#      return_img_attach("test.png", img_data, "JPEG")

#     """
#     return return_img_attach(filename, binaryblob, fext_override="JPEG")


def detect_mobile(request):
    """
    Is this a mobile browser?

    Args:
        request (obj) - Django Request object

    Returns:
        boolean::
            `True` if Mobile is found in the request's META headers
            specifically in HTTP USER AGENT.  If not found, returns False.

    """
    return "Mobile" in request.headers["user-agent"]


def return_img_attach(filename, binaryblob, fext_override=None, use_ranged=False):
    """
     Output a http response header, for an image attachment.

    Args:
         filename (str): Filename of the file to be sent as the attachment name
         binaryblob (bin): The blob of data that is the image file

     Returns:
         object::
             The Django response object that contains the attachment and header

     Raises:
         None

     Examples
     --------
     return_img_attach("test.png", img_data)


    """
    # https://stackoverflow.com/questions/36392510/django-download-a-file
    # https://stackoverflow.com/questions/27712778/
    #               video-plays-in-other-browsers-but-not-safari
    # https://stackoverflow.com/questions/720419/
    #               how-can-i-find-out-whether-a-server-supports-the-range-header
    basename = os.path.splitext(filename)[0]
    if fext_override is not None:
        mimetype_filename = os.path.join(basename, fext_override)
    else:
        mimetype_filename = filename
    #    mtype, encoding = mimetypes.guess_type(filename)
    mtype = mimetypes.guess_type(mimetype_filename)[0]
    if mtype is None:
        mtype = "application/octet-stream"

    if use_ranged:
        response = stream_video(request, filename, content_type=mtype)

    else:
        response = FileResponse(
            io.BytesIO(binaryblob),
            content_type=mtype,
            as_attachment=False,
            filename=filename,
        )
        response["Content-Type"] = mtype
        response["Content-Length"] = len(binaryblob)
    return response


@never_cache
def respond_as_attachment(request, file_path, original_filename):
    filename = os.path.join(file_path, original_filename)
    if os.path.exists(filename):
        mtype = mimetypes.guess_type(filename)[0]
        if mtype is None:
            mtype = "application/octet-stream"
        response = FileResponse(
            open(filename, "rb"),
            content_type=mtype,
            as_attachment=True,
            filename=filename,
        )
    return response


def file_iterator(file_path, chunk_size=8192, offset=0, length=None):
    """
    # https://www.djangotricks.com/tricks/4S7qbNhtUeAD/

    """
    with open(file_path, "rb") as f:
        f.seek(offset, os.SEEK_SET)
        remaining = length
        while True:
            bytes_length = (
                chunk_size if remaining is None else min(remaining, chunk_size)
            )
            data = f.read(bytes_length)
            if not data:
                break
            if remaining:
                remaining -= len(data)
            yield data


# def stream_audio(request):
#     """
#     # https://www.djangotricks.com/tricks/4S7qbNhtUeAD/

#     """
#     path = str(settings.BASE_DIR / "data" / "music.mp3")
#     content_type = "audio/mp3"

#     range_header = request.META.get("HTTP_RANGE", "").strip()
#     range_match = RANGE_RE.match(range_header)
#     size = os.path.getsize(path)

#     if range_match:
#         first_byte, last_byte = range_match.groups()
#         first_byte = int(first_byte) if first_byte else 0
#         last_byte = (
#             first_byte + 1024 * 1024 * 8
#         )  # The max volume of the response body is 8M per piece
#         if last_byte >= size:
#             last_byte = size - 1
#         length = last_byte - first_byte + 1
#         response = StreamingHttpResponse(
#             file_iterator(path, offset=first_byte, length=length),
#             status=206,
#             content_type=content_type,
#         )
#         response["Content-Range"] = f"bytes {first_byte}-{last_byte}/{size}"

#     else:
#         response = StreamingHttpResponse(
#             FileWrapper(open(path, "rb")), content_type=content_type
#         )
#     response["Accept-Ranges"] = "bytes"
#     return response


def stream_video(request, fqpn, content_type="video/mp4"):
    """
    https://www.djangotricks.com/tricks/Jw4jNwFziSXD/
    :param request:
    :return:
    """
    # path = str(settings.BASE_DIR / "data" / "earth.mp4")
    path = fqpn
    # content_type = "video/mp4"
    range_header = request.META.get("HTTP_RANGE", "").strip()
    range_match = RANGE_RE.match(range_header)
    size = os.path.getsize(path)

    if range_match:
        first_byte, last_byte = range_match.groups()
        first_byte = int(first_byte) if first_byte else 0
        last_byte = (
            first_byte + 1024 * 1024 * 8
        )  # The max volume of the response body is 8M per piece
        if last_byte >= size:
            last_byte = size - 1
        length = last_byte - first_byte + 1
        response = StreamingHttpResponse(
            file_iterator(path, offset=first_byte, length=length),
            status=206,
            content_type=content_type,
        )
        response["Content-Range"] = f"bytes {first_byte}-{last_byte}/{size}"

    else:
        response = StreamingHttpResponse(
            file_iterator(path, offset=0, length=size),
            #            FileWrapper(open(path, "rb")),
            content_type=content_type,
        )
    response["Accept-Ranges"] = "bytes"
    return response

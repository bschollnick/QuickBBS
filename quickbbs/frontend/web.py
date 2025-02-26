"""
Web functionality
"""

import io
import mimetypes
import os
import re
from wsgiref.util import FileWrapper

import filetypes
from django.conf import settings
from django.contrib.auth import authenticate, login
from django.http import FileResponse, Http404, StreamingHttpResponse, HttpResponseNotAllowed, HttpResponseBadRequest

# from django.conf import settings
from django.views.decorators.cache import never_cache

from werkzeug.http import parse_range_header
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


# def return_img_attach(filename, binaryblob, fext_override=None, use_ranged=False):
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
#      return_img_attach("test.png", img_data)


#     """
#     # https://stackoverflow.com/questions/36392510/django-download-a-file
#     # https://stackoverflow.com/questions/27712778/
#     #               video-plays-in-other-browsers-but-not-safari
#     # https://stackoverflow.com/questions/720419/
#     #               how-can-i-find-out-whether-a-server-supports-the-range-header
#     basename = os.path.splitext(filename)[0]
#     if fext_override is not None:
#         mimetype_filename = os.path.join(basename, fext_override)
#     else:
#         mimetype_filename = filename

#     fext = os.path.splitext(filename)[1]
#     #    mtype, encoding = mimetypes.guess_type(filename)
#     #mtype = mimetypes.guess_type(mimetype_filename)[0]
#     mtype = FILETYPE_DATA[fext]["mimetype"]
#     if mtype is None:
#         mtype = "application/octet-stream"

#     if use_ranged:
#         response = stream_video(request, filename, content_type=mtype)

#     else:
#         response = FileResponse(
#             io.BytesIO(binaryblob),
#             content_type=mtype,
#             as_attachment=False,
#             filename=filename,
#         )
#         response["Content-Type"] = mtype
#         response["Content-Length"] = len(binaryblob)
#     return response


@never_cache
def respond_as_attachment(request, file_path, original_filename):
    if not filetypes.models.FILETYPE_DATA:
        print("Loading web filetypes")
        filetypes.models.FILETYPE_DATA = filetypes.models.load_filetypes()

    filename = os.path.join(file_path, original_filename)
    fext = os.path.splitext(filename)[1].lower()
    mtype = filetypes.models.FILETYPE_DATA[fext]["mimetype"]
    if mtype is None:
        mtype = "application/octet-stream"
    try:
        #    mtype = mimetypes.guess_type(filename)[0]
        response = FileResponse(
            open(filename, "rb"),
            content_type=mtype,
            as_attachment=True,
            filename=filename,
        )
        return response
    except FileNotFoundError:
        return Http404


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
    # content_type = "video/mp4"
    range_header = request.headers.get("range", "").strip()
    range_match = RANGE_RE.match(range_header)
    size = os.path.getsize(fqpn)
    print("content type:",content_type)
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


# def stream_video(request, fqpn, content_type="video/mp4"):
#     """
# #     https://www.djangotricks.com/tricks/Jw4jNwFziSXD/
# #     :param request:
# #     :return:
# #     """

#     file_size = os.path.getsize(fqpn)
#     if request.method != 'GET':
#         return HttpResponseNotAllowed(['GET'])

#     range_header = request.headers.get("range", "").strip()
#     range_match = RANGE_RE.match(range_header)
#     if range_match:
#         start, end = range_match.groups()
#         start = int(start) if start else 0
#         end = int(end) if end else 0
#         end = end + 1024 * 1024 * 8  # The max volume of the response body is 8M per piece
#         if end >= file_size:
#             end = file_size - 1
#         length = end - start + 1
#     else:
#         return FileResponse(open(fqpn, 'rb'))

# #    range_header = request.headers.get("range", "").strip()
#     # if request.is_secure():
#     #     range_header = request.META.get('HTTPS_RANGE')
#     # else:
#     #     range_header = request.META.get('HTTP_RANGE')

#     # all_headers = request.META
#     # for header, value in all_headers.items():
#     #     print(f"{header}: {value}")
#     # print(range_header)
#     #ranges = parse_range_header(range_header)
# #    if not ranges:
# #        return FileResponse(open(fqpn, 'rb'))
    
#     # For simplicity, handle only single range requests
#  #   start, end = ranges[0]
#     print(start, end)
#     with open(fqpn, 'rb') as file_to_send:
#         file_to_send.seek(start)
#         data = file_to_send.read(end - start + 1)

#     response = FileResponse(data, content_type='application/octet-stream')
#     response['Content-Length'] = len(data)
#     response['Content-Range'] = f'bytes {start}-{end}/{file_size}'
#     response['Accept-Ranges'] = 'bytes'
#     response.status_code = 206  # Partial Content
#     return response


    # try:
    #     return response
    # except OSError:
    #     pass

# def stream_video(request, fqpn, content_type="video/mp4"):
#     print("Confirmed")
#     file_size = os.path.getsize(fqpn)
#     if request.method != 'GET':
#         return HttpResponseNotAllowed(['GET'])

#     range_header = request.META.get('HTTPS_RANGE')
#     if not range_header:
#       return FileResponse(open(fqpn, 'rb'))
    
#     try:
#         ranges = parse_range_header(range_header)
#         print(ranges)
#     except ValueError:
#         return HttpResponseBadRequest('Invalid Range header')

#     if not ranges:
#         return FileResponse(open(fqpn, 'rb'))

#     # For simplicity, handle only single range requests
#     start, end = ranges[0]

#     with open(fqpn, 'rb') as f:
#         f.seek(start)
#         data = f.read(end - start + 1)

#     response = FileResponse(data, content_type='application/octet-stream')
#     response['Content-Length'] = len(data)
#     response['Content-Range'] = f'bytes {start}-{end}/{file_size}'
#     response['Accept-Ranges'] = 'bytes'
#     response.status_code = 206  # Partial Content
#     return response
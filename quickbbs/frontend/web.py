"""
Web functionality
"""

import io
import mimetypes
import os

# from django.conf import settings
from django.contrib.auth import authenticate, login
from django.http import (FileResponse, Http404,  # , StreamingHttpResponse)
                         HttpResponse)
from ranged_fileresponse import RangedFileResponse
#import RangedFileResponse
#from ranged_fileresponse.local import RangedLocalFileResponse

def verify_login_status(request, force_login=False) -> bool:
    """
    Verify login status, if not logged in redirect to login screen.

    args:
        request (obj) : Django Request object
        force_login (bool) : tbd



    """
    username = request.POST['username']
    password = request.POST['password']
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


def return_inline_attach(filename, binaryblob):
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
    return_img_attach("test.png", img_data, "JPEG")

    """
    return return_img_attach(filename, binaryblob, fext_override="JPEG")


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
        mtype = 'application/octet-stream'

    if use_ranged:
        response = RangedFileResponse(request, file=open(filename, 'rb'),
                                      as_attachment=False,
                                      filename=os.path.basename(filename))
        response["Content-Type"] = mtype
        response['Content-Length'] = len(binaryblob)
    #        return response
    else:
        response = FileResponse(io.BytesIO(binaryblob),
                                content_type=mtype,
                                as_attachment=False,
                                filename=filename)
        response["Content-Type"] = mtype
        response['Content-Length'] = len(binaryblob)
    return response


def img_attach_file(filename, fqfn):
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
    response = HttpResponse()
    with open(fqfn, 'rb') as filedata:
        response.write(filedata.read())
    response['Content-Disposition'] = f'attachment; filename={{{filename}}}'
    return response


def file_inline(filename, fqfn):
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
    response = HttpResponse()
    with open(fqfn, 'rb') as filedata:
        response.write(filedata.read())
    response['Content-Disposition'] = f'inline; filename={{{filename}}}'
    return response


def respond_as_inline(request, file_path, original_filename, ranged=False):
    # https://stackoverflow.com/questions/36392510/django-download-a-file
    # https://stackoverflow.com/questions/27712778/
    #       video-plays-in-other-browsers-but-not-safari
    # https://stackoverflow.com/questions/720419/
    # how-can-i-find-out-whether-a-server-supports-the-range-header
    filename = os.path.join(file_path, original_filename)
    if os.path.exists(filename):
        mtype = mimetypes.guess_type(original_filename)[0]
        if mtype is None:
            mtype = 'application/octet-stream'

        with open(filename, 'rb') as fh:
            if ranged:
                response = RangedFileResponse(request, file=open(filename, 'rb'),
                                              as_attachment=False,
                                              filename=original_filename)
                response["Content-Type"] = mtype
            else:
                response = HttpResponse(fh.read(), content_type=mtype)
                response['Content-Disposition'] = f'inline; filename={original_filename}'
        return response
    raise Http404


def respond_as_attachment(request, file_path, original_filename):
    filename = os.path.join(file_path, original_filename)
    if os.path.exists(filename):
        mtype = mimetypes.guess_type(filename)[0]
        if mtype is None:
            mtype = 'application/octet-stream'
        response = FileResponse(open(filename, 'rb'),
                                content_type=mtype,
                                as_attachment=True,
                                filename=filename)
    return response

# coding: utf-8
"""
Web functionality
"""
from __future__ import absolute_import, print_function, unicode_literals

import mimetypes
import os
from django.http import (HttpResponse, Http404)
from django.conf import settings
from django.contrib.auth import authenticate, login
import os


def verify_login_status(request, force_login=False):
    """
    Verify login status
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

    Raises:
        None
    """
    return "Mobile" in request.META["HTTP_USER_AGENT"]

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
    return_img_attach("test.png", img_data)


    """
    response = HttpResponse()
    response.write(binaryblob)
    response['Content-Disposition'] = 'inline;filename={%s}' % filename
    return response

def return_img_attach(filename, binaryblob):
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
    response.write(binaryblob)
    response['Content-Disposition'] = 'attachment; filename={%s}' % filename
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
    response['Content-Disposition'] = 'attachment; filename={%s}' % filename
    return response


def respond_as_inline(request, file_path, original_filename):
    # https://stackoverflow.com/questions/36392510/django-download-a-file
    filename = os.path.join(file_path, original_filename)
    if os.path.exists(filename):
        with open(filename, 'rb') as fh:
            mtype, encoding = mimetypes.guess_type(original_filename)
            if mtype is None:
                mtype = 'application/octet-stream'
            response = HttpResponse(fh.read(), content_type=mtype)
            response['Content-Disposition'] = 'inline; filename=' + os.path.basename(file_path)
            return response
    raise Http404


def respond_as_attachment(request, file_path, original_filename):
#   https://www.djangosnippets.org/snippets/1710/
#   print ("original filename: ", original_filename)
    filename = os.path.join(file_path, original_filename)
    fp = open(filename, 'rb')
    response = HttpResponse(fp.read())
    fp.close()
    mtype, encoding = mimetypes.guess_type(original_filename)
    if mtype is None:
        mtype = 'application/octet-stream'
    response['Content-Type'] = mtype
    response['Content-Length'] = str(os.stat(filename).st_size)
    if encoding is not None:
        response['Content-Encoding'] = encoding
    filename_header = 'filename="%s"' % original_filename
# To inspect details for the below code, see http://greenbytes.de/tech/tc2231/
#     if u'WebKit' in request.META['HTTP_USER_AGENT']:
#         # Safari 3.0 and Chrome 2.0 accepts UTF-8 encoded string directly.
#         filename_header = 'filename=%s' % original_filename.encode('utf-8')
#     elif u'MSIE' in request.META['HTTP_USER_AGENT']:
#         # IE does not support internationalized filename at all.
#         # It can only recognize internationalized URL, so we do the trick
#           via routing rules.
#         filename_header = ''
#     else:
#         # For others like Firefox, we follow RFC2231 (encoding extension
#           in HTTP headers).
#         filename_header = 'filename*=UTF-8\'\'%s' %
#              urllib.quote(original_filename.encode('utf-8'))
    response['Content-Disposition'] = 'attachment; ' + filename_header
    return response

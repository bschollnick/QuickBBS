"""
Downloader Plugin for acparadise.com.
"""
import os
import unidecode
import urllib2

##############################################################################
def is_int(value_to_test):
    """
    Test to see if string is an integer.

    If integer, returns True.
    If not integer, returns False.
    """
    try:
        int(value_to_test)
        return True
    except ValueError:
        return False

def return_int(value_to_test):
    """
    Test to see if string is an integer.

    If integer, returns integer.
    If not integer, returns original value.
    """
    try:
        int(value_to_test)
        return int(value_to_test)
    except ValueError:
        return value_to_test

def fix_doubleslash(fullpathname):
    """
    Remove the Double Slashing that seems to occur.
    """
    while fullpathname.find("//") != -1:
        fullpathname = fullpathname.replace("//", "/")
    return fullpathname


def replace_all(text, dic):
    """
    Helper function for Clean Filename2
    """
    for i, j in dic.iteritems():
        text = text.replace(i, j)
    return text

def pre_slash(path):
    """
    Connivence function to ensure prepended slash to a path
    """
    if path == '':
        path = "/"
        return path

    if path[0] != '/':
        path = '/' + path
    return path

def post_slash(path):
    """
    Connivence function to ensure postpended slash to a path
    """
    if path == '':
        path = "/"
        return path

    if path[-1] != '/':
        path = path +'/'
    return path

def clean_filename2(filename,
                    unicode_filter=True):
    """
    Looking to clean up clean_filename, and make it more generic
    """
    replacements = {'"':"`", "'":"`",
                    ",":"", "#":"",
                    "*":"", "@":"",
                    ":":"-", "|":""}
    filename = replace_all(urllib2.unquote(filename), replacements)
        # Un"quotify" the URL / Filename
    if unicode_filter:
        filename = unidecode.unidecode(filename)
        # de-unicode the filename / url
    filename, fileext = os.path.splitext(filename)
    filename = filename.strip() + fileext.strip()
        # remove extra spaces from filename and file extension.
        # e.g.  "this is the filename .txt" -> "this is the filename.txt"
    return filename

def norm_number(page, max_number):
    """
    Normalize a integer (page).

    * Ensure that it is greater than Zero, and is not None.
        - If Zero, or None, set it to 1

    * if greater than max_number, reset it to be max_number
    """
    if page == None or page < 1:
        page = 1
    elif page > max_number:
        page = max_number
    return page

#import timeit
#test = timeit.timeit ("ensure_prepending_slash2(r'This is a test.txt')",
#                       number=10000000, setup=setup)
#print test

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

    note, exception tracking tests to be slower!
    """
    if value_to_test.isdigit():
        return True
    else:
        return False

def return_int(value_to_test):
    """
    Test to see if string is an integer.

    If integer, returns integer.
    If not integer, returns original value.
    """
    if value_to_test.isdigit():
        return int(value_to_test)
    else:
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

    No significant difference in speed between
    replace_all and multiple_replace.
    """
#    return multiple_replace(dic, text):
    for i, j in dic.iteritems():
        text = text.replace(i, j)
    return text

def multiple_replace(dict, text):
  """ Replace in 'text' all occurences of any key in the given
  dictionary by its corresponding value.  Returns the new string.
  http://code.activestate.com/recipes/81330-single-pass-multiple-replace/
  """

  # Create a regular expression  from the dictionary keys
  regex = re.compile("(%s)" % "|".join(map(re.escape, dict.keys())))

  # For each match, look-up corresponding value in dictionary
  return regex.sub(lambda mo: dict[mo.string[mo.start():mo.end()]], text)

def assure_path_exists(path):
    dir = os.path.dirname(os.path.abspath(path))
    if not os.path.exists(dir):
            os.makedirs(dir)
            return True
    return False

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

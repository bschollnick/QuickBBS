"""
Utility script
--------------
This tries to create a sanitized version of a PDF which has issues
with embedded images.
Assumption is, that input pages only contains images - any text is ignored.
Think of a scanned-in book ...
For each input page, an output PDF page with the same size is generated.
For every image found, a (hopefully) sanitized version is created
and put on same place of the output page.

Stability assessment
--------------------
Will only work if input PDF has at least intact / repairable XREF,
and page tree.

https://github.com/rk700/PyMuPDF/issues/160

Need to upgrade to use fitz.TOOLS.mupdf_warnings() for bad file detection.
"""

from io import BytesIO

# import subprocess
import fitz
from pdfrw import PdfReader, PdfWriter

# import img2pdf
# import pdfkit


def repair_pdf(origname, newname, forced=False):
    """
    Attempt to repair a PDF file.

    Args:

        origname (string): The original filename
        newname (string): The new filename
        forced (boolean): Override damage auto-detection.  If set True,
            the repair will be forcibly done.  If False, auto-detection must
            detect the damage, before it will be fixed.

    Returns:

            Boolean: True, File has been fixed.  False, File is untouched.
    """
    try:
        ifile = open(origname, "rb")
    except FileNotFoundError:
        return "File Not Found"  # File not found

    idata = ifile.read()  # put in memory
    ifile.close()
    ibuffer = BytesIO(idata)  # convert to stream
    try:
        data = PdfReader(ibuffer)
        if not forced:
            return ""  # File did not need to be repaired
    except OSError:  # problem! heal it with PyMuPDF
        pass

    # either an exception occured, or we are being forced to repair

    # print ("Error reading")
    doc = fitz.open("pdf", idata)  # open and save a corrected
    try:
        fixed = doc.write(garbage=3, deflate=1, clean=1)  # version in memory
        doc.close()
        doc = idata = None  # free storage
        ibuffer = BytesIO(fixed)  # convert to stream
        PdfWriter(newname, trailer=PdfReader(ibuffer)).write()
        return True  # File has been Fixed
    except ValueError:
        return False
    # return (False, PdfReader(ibuffer))           # let pdfrw retry


def check_pdf(filename):
    """
    Use the PyMuPDF library to verify the structure of a PDF file.

    Args:
        filename (String): The FQPN filename of the file in question to check

    Returns:
        Tupple:A Tuppple that contains
            * Boolean - Is Clean (True if no issue, False if issue)
            * Generic error message, eg. expected generation number
            * Raw Error message, eg expected generation number (25366 ? obj)

    Generic Error message is filtered, to try to remove changing data, so
     that it can be used in the filtered excel report.

    .. code-block:

        from pdf_utilities import check_pdf
        >>> check_pdf(r"test_samples\\badpdf\\Administrative - 30 - Consent to Treat 02-16-07 - 7712.pdf")
        (False, 'expected generation number', 'expected generation number (25366 ? obj)')
        >>> check_pdf(r"test_samples\\badpdf\\Administrative - 30 - PayPol 05-27-08 - 7713.pdf")
        (False, 'expected generation number', 'expected generation number (17469 ? obj)')
        >>> check_pdf(r"test_samples\\goodpdf\\CCD_extract_101001-00.html.pdf")
        (True, '', '')
        >>> check_pdf(r"test_samples\\goodpdf\\CCD_extract_101002-00.html.pdf")
        (True, '', '')
    """
    raw_errmsg = ""
    errmsg = ""
    errorcode = 0
    try:
        pdffile = fitz.open(filename)
        raw_errmsg = str(fitz.TOOLS.mupdf_warnings())
    except RuntimeError:
        #
        #   A truly fatal error occurred, trap, assuming it's file not found.
        #   (Need to verify FNF is the only condition this applies to.)
        raw_errmsg = "File Not Found"
        errorcode = -1

    if raw_errmsg != "":  # There is an error
        errorcode = 1
        if "(" in raw_errmsg:  # Does it have an (?
            errmsg = raw_errmsg[0 : raw_errmsg.find("(")].strip()
        else:
            errmsg = raw_errmsg
    return (errorcode == 0, errmsg, raw_errmsg)

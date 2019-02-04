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
"""
from io import BytesIO
import fitz
from pdfrw import PdfReader, PdfWriter
import img2pdf

def repair_pdf(origname, newname):
    """
    Attempt to repair a PDF file.
    """
    try:
        ifile = open(origname, "rb")
    except FileNotFoundError:
        return "File Not Found" # File not found

    idata = ifile.read()                    # put in memory
    ifile.close()
    ibuffer = BytesIO(idata)                # convert to stream
    try:
        data = PdfReader(ibuffer)
        return "" # File did not need to be repaired
    except:                                 # problem! heal it with PyMuPDF
        #print ("Error reading")
        doc = fitz.open("pdf", idata)       # open and save a corrected
        try:
            fixed = doc.write(garbage=3, deflate=1, clean=1) # version in memory
            doc.close()
            doc = idata = None                  # free storage
            ibuffer = BytesIO(fixed)                # convert to stream
            PdfWriter(newname, trailer=PdfReader(ibuffer)).write()
            return True # File has been Fixed
        except ValueError:
            return False
        #return (False, PdfReader(ibuffer))           # let pdfrw retry

def check_pdf(filename):
    """
    Use the PyMuPDF library to verify the structure of a PDF file.

    :param filename: The FQPN filename of the file in question to check
    :type filename: String

    :return: A Tuppple that contains
      * Boolean - Is Clean (True if no issue, False if issue)
      * Generic error message, eg. expected generation number
      * Raw Error message, eg expected generation number (25366 ? obj)
    :rtype: Tupple

    Generic Error message is filtered, to try to remove changing data, so
     that it can be used in the filtered excel report.

    .. code-block:: python

        >>> check_pdf(r"test_samples\\badpdf\\Administrative - 30 - Consent to Treat 02-16-07 - 7712.pdf")
        (False, 'expected generation number', 'expected generation number (25366 ? obj)')
        >>> check_pdf(r"test_samples\\badpdf\\Administrative - 30 - PayPol 05-27-08 - 7713.pdf")
        (False, 'expected generation number', 'expected generation number (17469 ? obj)')
        >>> check_pdf(r"test_samples\\goodpdf\\CCD_extract_101001-00.html.pdf")
        (True, '', '')
        >>> check_pdf(r"test_samples\\goodpdf\\CCD_extract_101002-00.html.pdf")
        (True, '', '')
    """
    errmsg = ""
    try:
        pdffile = fitz.open(filename)
        raw_errmsg = pdffile.openErrMsg
        errorcode = pdffile.openErrCode
    except RuntimeError:
        #
        #   A truly fatal error occurred, trap, assuming it's file not found.
        #   (Need to verify FNF is the only condition this applies to.)
        raw_errmsg = "File Not Found"
        errorcode = -1

    if raw_errmsg != "":    # There is an error
        if "(" in raw_errmsg:   # Does it have an (?
            errmsg = raw_errmsg[0:raw_errmsg.find("(")].strip()
        else:
            errmsg = raw_errmsg
    return (errorcode == 0, errmsg, raw_errmsg)
    #return (pdffile.openErrCode == 0, errmsg, pdffile.openErrMsg)

def imgfile_to_pdf(sourcefile, targetfile):
    """
     Use the img2pdf library to create a lossless PDF from an image.

     img2pdf supports:
    | Format                | Colorspace                     |    Result    |
    | --------------------- | ------------------------------ | ------------ |
    | JPEG                  | any                            | direct       |
    | JPEG2000              | any                            | direct       |
    | PNG (non-interlaced)  | any                            | direct       |
    | TIFF (CCITT Group 4)  | monochrome                     | direct       |
    | any                   | any except CMYK and monochrome | PNG Paeth    |
    | any                   | monochrome                     | CCITT Group4 |
    | any                   | CMYK                           | flate        |


    :param sourcefile: The FQPN filename of the file in question to convert
    :type sourcefile: String

    :param sourcefile: The FQPN filename of the file to create
    :type sourcefile: String

    :return: True if converted successfully, otherwise False
    :rtype: Boolean

    Dependency - img2pdf, which has a dependency on Pillow.

    https://gitlab.mister-muffin.de/josch/img2pdf
    https://pypi.org/project/img2pdf/
    """
    try:
        with open(targetfile, "wb") as pdf_output:
            pdf_output.write(img2pdf.convert(sourcefile))
        return True
    except:
        return False

def imgmem_to_pdf(sourcedata, targetfile):
    """
     Use the img2pdf library to create a lossless PDF from an image.

     img2pdf supports:
    | Format                | Colorspace                     |    Result    |
    | --------------------- | ------------------------------ | ------------ |
    | JPEG                  | any                            | direct       |
    | JPEG2000              | any                            | direct       |
    | PNG (non-interlaced)  | any                            | direct       |
    | TIFF (CCITT Group 4)  | monochrome                     | direct       |
    | any                   | any except CMYK and monochrome | PNG Paeth    |
    | any                   | monochrome                     | CCITT Group4 |
    | any                   | CMYK                           | flate        |


    :param sourcedata: A memory blob that contains the data from the image. (eg.
      The image file was read into memory).
    :type sourcedata: Binary blob

    :param sourcefile: The FQPN filename of the file to create
    :type sourcefile: String

    :return: True if converted successfully, otherwise False
    :rtype: Boolean

    Dependency - img2pdf, which has a dependency on Pillow.

    https://gitlab.mister-muffin.de/josch/img2pdf
    https://pypi.org/project/img2pdf/
    """
    try:
        with open(targetfile, "wb") as target:
            target.write(img2pdf.convert(sourcedata))
            return True
    except:
        return False

if __name__ == "__main__":
    pass

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
from __future__ import print_function
from io import BytesIO
from os import path
import os
import subprocess
#import time
import fitz
from pdfrw import PdfReader, PdfWriter
import img2pdf
#import pdfkit

IMAGE_MAGICK_PATH = r"\Program Files\ImageMagick-7.0.8-Q16"

WKHTMLTOPDF_LOCALE = r'c:\program files\wkhtmltopdf\bin'
WKHTMLTOPDF_APP = r'%s\wkhtmltopdf.exe' % WKHTMLTOPDF_LOCALE
WKHTMLTOPDF_CSS = r'%s\wkhtml.css' % WKHTMLTOPDF_LOCALE

#print ("%s\wkhtml.css" % WKHTMLTOPDF_LOCALE)
PDF_KIT_OPTIONS = {'margin-top': '0.25in',
                   'margin-right': '0.25in',
                   'margin-bottom': '0.25in',
                   'margin-left': '0.25in',
                   'page-height':'11in',
                   'page-width':'8.5in',
                   'encoding': "UTF-8",
                   'quiet':''}#,
                   #'user-style-sheet':WKHTMLTOPDF_CSS}

#PDF_KIT_CONFIG = pdfkit.configuration(wkhtmltopdf=r'c:\program files\wkhtmltopdf\bin\wkhtmltopdf.exe')
def get_all_fonts(pdf_doc=None, filename=None):
    """
    pdf_doc  - the pyMuPDF document
    """
#    if pdf_doc == None and filename != None:
#        pdf_doc = fitz.open(filename)
#    elif pdf_doc == None and filename == None:
    if pdf_doc is None and filename is not None:
        pdf_doc = fitz.open(filename)
    elif pdf_doc is None and filename is None:
        return None

    font_list = []
    for pgno in range(0, pdf_doc.pageCount):
        listings = pdf_doc.getPageFontList(pgno)
        for entry in listings:
            if entry[5].upper() not in font_list:
                font_list.append(entry[5].upper())
    return font_list


def remove_font(pdf_doc=None, filename=None, font_name_list=[]):
    """
    Args:
        pdf_doc (PyMuPDF Document):
        font_name (List of Strings) : A list of strings to match for element 5
              - eg. font_list = ['90ms-RKSJ-V', '90ms-RKSJ-H']

    Returns:
        pyMuPDF: The Document container

    Example:

        >>> import pdf_utilities
        >>> filename = r"C:\15383_01-23-2019_g2documentupld_Insurance_Card.pdf"
        >>> import fitz
        >>> doc = fitz.open(filename)
        >>> font_list = ['90ms-RKSJ-V', '90ms-RKSJ-H']
        >>> doc = pdf_utilities.remove_font(doc, font_list)
        >>> doc.save("test2.pdf")

    * xref (int) is the font object number,  # element 0
    * ext (str) font file extension (e.g. ttf, see Font File Extensions), #1
    * type (str) is the font type (like Type1 or TrueType etc.), # element 2
    * basefont (str) is the base font name,                      # element 3
    * name (str) is the reference name (or label), by which the page
                references the font in its contents stream(s)    # element 4
    * encoding (str optional) the font’s character encoding if different
      from its built-in encoding
      (Adobe PDF Reference 1.7, p. 414)  # element 5


    """
 #   if pdf_doc == None and filename != None:
 #       pdf_doc = fitz.open(filename)
#    elif pdf_doc == None and filename == None:
    if pdf_doc is None and filename is not None:
        pdf_doc = fitz.open(filename)
    elif pdf_doc is None and filename is None:
        return None

    font_name_list = [x.upper() for x in font_name_list]
    for pgno in range(0, pdf_doc.pageCount):
        page = pdf_doc.loadPage(pgno)
        listings = page.getFontList()
        for entry in listings:
            if entry[5].upper() in font_name_list:
                pdf_doc._deleteObject(entry[0])
                page._cleanContents()
    return pdf_doc

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

    idata = ifile.read()                    # put in memory
    ifile.close()
    ibuffer = BytesIO(idata)                # convert to stream
    try:
        data = PdfReader(ibuffer)
        if not forced:
            return ""  # File did not need to be repaired
    except IOError:                                 # problem! heal it with PyMuPDF
        pass

    # either an exception occured, or we are being forced to repair

    #print ("Error reading")
    doc = fitz.open("pdf", idata)       # open and save a corrected
    try:
        fixed = doc.write(garbage=3, deflate=1,
                          clean=1)  # version in memory
        doc.close()
        doc = idata = None                  # free storage
        ibuffer = BytesIO(fixed)                # convert to stream
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

    if raw_errmsg != "":    # There is an error
        errorcode = 1
        if "(" in raw_errmsg:   # Does it have an (?
            errmsg = raw_errmsg[0:raw_errmsg.find("(")].strip()
        else:
            errmsg = raw_errmsg
    return (errorcode == 0, errmsg, raw_errmsg)


def fallback_convert_image_to_pdf(sourcefile, targetfile, overwrite=False):
    """
    Last ditch external attempt to convert to PDF using ImageMagick-7.

    Args:
        sourcefile (string) : Fully qualified pathname of the source file
        targetfile (string) : Fully qualified pathname of the target file
        overwrite (boolean) : Allow overwriting if True,
                              deny overwriting if False, default is False.

    Returns:

        Tupple: * The Return Status (boolean), true if no error, False if error
                * Error String
    """
    if os.path.exists(targetfile) and not overwrite:
        return (False, "File Already Exists")
    if not os.path.exists(sourcefile):
        return (False, "Source does not exist")
    results = subprocess.run([r"%s\convert.exe" % IMAGE_MAGICK_PATH,
                              sourcefile, targetfile], capture_output=True)
    return(results.returncode != 0, "(fallback) %s %s" % (results.stdout,
                                                          results.stderr))

def imgfile_to_pdf(sourcefile, targetfile, overwrite=False):
    """
     Use the img2pdf library to create a lossless PDF from an image.

    Args:
        sourcefile (string): The FQPN filename of the file in question
                             to convert
        targetfile (string) : Fully qualified pathname of the target file
        overwrite (boolean) : Allow overwriting if True,
                              deny overwriting if False, default is False.

    Returns:

        Boolean: True if converted successfully, otherwise False


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

    Dependency - img2pdf, which has a dependency on Pillow.

    Note: Assumes that the target directory already exists

    https://gitlab.mister-muffin.de/josch/img2pdf
    https://pypi.org/project/img2pdf/
    """
 #   try:
    if os.path.exists(targetfile) and not overwrite:
        return (False, "File Already Exists")
    if not os.path.exists(sourcefile):
        return (False, "Source does not exist")
    with open(targetfile, "wb") as pdf_output:
        pdf_output.write(img2pdf.convert(sourcefile))
        return (True, "File converted to PDF.")
#    except:
#    return fallback_convert_image_to_pdf(sourcefile, targetfile, overwrite)


def imgmem_to_pdf(sourcedata, targetfile, overwrite=False):
    """
     Use the img2pdf library to create a lossless PDF from an image.

    Args:
        sourcedata (blob): The memory blob that contains the data from the image
            (eg. The image file that was read into memory)

        targetfile (string): The filename to write the image to

        overwrite (boolean): If true, overwrite the (potentially) existing file.

    Returns:
        Boolean: True if converted successfully, otherwise False

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

    Dependency - img2pdf, which has a dependency on Pillow.

    Note: Assumes that the target directory already exists

    https://gitlab.mister-muffin.de/josch/img2pdf
    https://pypi.org/project/img2pdf/
    """
#    try:
    if os.path.exists(targetfile) and not overwrite:
        return (False, "File Already Exists")
    if not os.path.exists(sourcedata):
        return (False, "Source does not exist")
    with open(targetfile, "wb") as target:
        target.write(img2pdf.convert(sourcedata))
        return (True, "File converted to PDF.")
 #   except:
  #      return (False, "Unable to convert")


def htmlfile_to_pdf(input_file, output_file,
                    overwrite=False, landscape=False,
                    height="11in", width="8.5in"):
    """
    html to PDF via wkhtmltopdf.

    Args:

        input_file (string): input filename
        output_file (string): output filename
        overwrite (string): If true, allow overwriting of existing files
        landscape (string): If True, use landscape mode, otherwise portrait
        height (string): The height of the output document
        width (string): The width of the output document

    Returns:

        tupple: (status (boolean), Description(string) )
    """
    input_file = path.abspath(input_file)
    target_dir = os.path.split(output_file)[0]
    os.makedirs(target_dir, exist_ok=True)
    if not os.path.exists(input_file):
        print("No input file")
        return (False, "No input File located.")

    with open(input_file, 'r') as data:

        output_file = path.abspath(output_file)
        if os.path.exists(output_file) and not overwrite:
            print("output file exists")
            return (False, "Output file already exists, overwrite is not allowed.")

        try:
            #text = ''.join(data.readlines())
            #pdfkit.from_string("""<style>thead { display: table-header-group, color: red; }
#tfoot { display: table-row-group }
#tr { page-break-inside: avoid }#
#
#b, strong {color: red;}
#</style>"""+text, output_file, options=PDF_KIT_OPTIONS, configuration=PDF_KIT_CONFIG, css=WKHTMLTOPDF_CSS)
            #print("Portrait")
            options = PDF_KIT_OPTIONS
            options['page-height'] = height
            options['page-width'] = width

            pdfkit.from_file(input_file, output_file, options=options, configuration=PDF_KIT_CONFIG)#, css=WKHTMLTOPDF_CSS)

        except OSError:
            return (False, "Unable to write (WKHTMLtoPDF error)")
        except TypeError:
            return (False, "TypeError: Internal Error")
        return (True, "Document Converted Successfully")

if __name__ == "__main__":
    pass

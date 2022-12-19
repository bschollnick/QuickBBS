import sys

import fitz
# import pdf_utilities
from PIL import Image

repeat = 200

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
        print("Before")
#        print(fitz.TOOLS.mupdf_warnings())
        print("After")
        #raw_errmsg = ""
        raw_errmsg = fitz.TOOLS.mupdf_warnings()
        print("Really after")
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


def return_image_obj(fs_path, memory=False):
    """
    Given a Fully Qualified FileName/Pathname, open the image
    (or PDF) and return the PILLOW object for the image
    Fitz == py


    Args:
        fs_path (str) - File system path
        memory (bool) - Is this to be mapped in memory

    Returns:
        boolean::
            `True` if uuid_to_test is a valid UUID, otherwise `False`.

    Raises:
        obj::
            Pillow image object

    Examples
    --------
    """
    source_image = None
    if os.path.splitext(fs_path)[1][1:].lower() == "pdf":
        results = check_pdf(fs_path)
#        if results[0] == False:
#            pdf_utilities.repair_pdf(fs_path, fs_path)

        print("after : ",results)
        print("Opening")
        pdf_file = fitz.open(fs_path)
        print("Loading page 0")
        pdf_page = pdf_file.loadPage(0)
        pix = pdf_page.getPixmap(alpha=True)#matrix=fitz.Identity, alpha=True)

        try:
            source_image = Image.open(BytesIO(pix.getPNGData()))
        except UserWarning:
            print("UserWarning!")
            source_image = None
    else:
        if not memory:
            source_image = Image.open(fs_path)
        else:
            try:# fs_path is a byte stream
                source_image = Image.open(BytesIO(fs_path))
            except OSError:
                print("IOError")
                log.debug("PIL was unable to identify as an image file")
            except UserWarning:
                print("UserWarning!")
                source_image = None
#        if source_image.mode != "RGB":
#            source_image = source_image.convert('RGB')
    return source_image


for count in range(0, repeat):
    print ("Before check")
    print(count, check_pdf(sys.argv[1]))
    print ("after check")

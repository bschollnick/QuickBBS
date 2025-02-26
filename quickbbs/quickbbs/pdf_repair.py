import sys
from io import BytesIO
from pdfrw import PdfReader
import pymupdf


# ---------------------------------------
# 'Tolerant' PDF reader
# ---------------------------------------
def reader(fname, password=None):
    idata = open(fname, "rb").read()  # read the PDF into memory and
    ibuffer = BytesIO(idata)  # convert to stream
    if password is None:
        try:
            return PdfReader(ibuffer)  # if this works: fine!
        except:
            pass

    print("Damaged")
    # either we need a password or it is a problem-PDF
    # create a repaired / decompressed / decrypted version
    doc = pymupdf.open("pdf", ibuffer)
    if password is not None:  # decrypt if password provided
        rc = doc.authenticate(password)
        if not rc > 0:
            raise ValueError("wrong password")
    c = doc.tobytes(garbage=3, deflate=True)
    del doc  # close & delete doc
    return PdfReader(BytesIO(c))  # let pdfrw retry


# ---------------------------------------
# Main program
# ---------------------------------------
pdf = reader(sys.argv[1], password=None)  # include a password if necessary
print(pdf.Info)
# do further processing

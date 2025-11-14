import sys
from io import BytesIO

import pymupdf
from pdfrw import PdfReader


# ---------------------------------------
# 'Tolerant' PDF reader
# ---------------------------------------
def reader(fname, password=None):
    # Try to read PDF directly from file path (no memory load)
    if password is None:
        try:
            with open(fname, "rb") as f:
                return PdfReader(f)  # if this works: fine!
        except:
            pass

    print("Damaged")
    # either we need a password or it is a problem-PDF
    # create a repaired / decompressed / decrypted version
    # pymupdf can open files directly by path (no need to load into memory)
    doc = pymupdf.open(fname)
    if password is not None:  # decrypt if password provided
        rc = doc.authenticate(password)
        if not rc > 0:
            doc.close()
            raise ValueError("wrong password")
    c = doc.tobytes(garbage=3, deflate=True)
    doc.close()  # explicitly close instead of del
    return PdfReader(BytesIO(c))  # let pdfrw retry


# ---------------------------------------
# Main program
# ---------------------------------------
pdf = reader(sys.argv[1], password=None)  # include a password if necessary
print(pdf.Info)
# do further processing

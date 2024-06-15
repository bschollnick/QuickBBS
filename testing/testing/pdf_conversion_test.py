import fitz
from PIL import Image
from io import BytesIO

test_file = "/Volumes/C-8TB/sorted_downloads/pdf/wp965.pdf"
with fitz.open(test_file) as pdf_file:
    pdf_page = pdf_file.load_page(0)
    # matrix=fitz.Identity, alpha=True)
    pix = pdf_page.get_pixmap(alpha=True)
    try:
        source_image = Image.open(BytesIO(pix.tobytes()))
    except UserWarning:
        print("UserWarning!")
        source_image = None

    source_image.save("testfile.pdf", optimize=True)

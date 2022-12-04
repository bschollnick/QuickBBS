# test PDF extraction to memory

from io import BytesIO

import fitz
from PIL import Image

warnings.simplefilter('ignore', Image.DecompressionBombWarning)
pdf_file=fitz.open("chart.pdf")
pdf_page = pdf_file.loadPage(0)
pix = pdf_page.getPixmap(matrix=fitz.Identify, 
                         colorspace="rgb", 
                         alpha=True)
#testfile=open("test.png", "wb+")
#testfile.write( pix.getPNGData())
#testfile.close()

sourceimage = Image.open(BytesIO(pix.getPNGData()))

def return_image_obj(fs_path):
    fext = os.path.splitxt(fs_path)[1][1:].upper()
    if fext == "PDF":
        pdf_file = fitz.open(fs_path)
        pdf_page = pdf_file.loadPage(0)
        pix = pdf_page.getPixmap(matrix=fitz.Identify, 
                         colorspace="rgb", 
                         alpha=True)
        source_image = Image.open(BytesIO(pix.getPNGData()))
    else:
        source_image = Image.open(fs_path)
        
    if source_image.mode != "RGB":
        source_image = source_image.convert('RGB')
    return source_image

    
# Pdf Utilities

> Auto-generated documentation for [frontend.pdf_utilities](blob/master/frontend/pdf_utilities.py) module.

Utility script
--------------
This tries to create a sanitized version of a PDF which has issues
with embedded images.
Assumption is, that input pages only contains images - any text is ignored.
Think of a scanned-in book ...
For each input page, an output PDF page with the same size is generated.
For every image found, a (hopefully) sanitized version is created
and put on same place of the output page.

- [Quickbbs](../README.md#quickbbs-index) / [Modules](../MODULES.md#quickbbs-modules) / [Frontend](index.md#frontend) / Pdf Utilities
    - [check_pdf](#check_pdf)
    - [fallback_convert_image_to_pdf](#fallback_convert_image_to_pdf)
    - [get_all_fonts](#get_all_fonts)
    - [htmlfile_to_pdf](#htmlfile_to_pdf)
    - [imgfile_to_pdf](#imgfile_to_pdf)
    - [imgmem_to_pdf](#imgmem_to_pdf)
    - [remove_font](#remove_font)
    - [repair_pdf](#repair_pdf)

Stability assessment
--------------------
Will only work if input PDF has at least intact / repairable XREF,
and page tree.

https://github.com/rk700/PyMuPDF/issues/160

Need to upgrade to use fitz.TOOLS.mupdf_warnings() for bad file detection.

#### Attributes

- `PDF_KIT_OPTIONS` - print ("%s\wkhtml.css" % WKHTMLTOPDF_LOCALE): `{'margin-top': '0.25in', 'margin-right': '0.25i...`

## check_pdf

[[find in source code]](blob/master/frontend/pdf_utilities.py#L169)

```python
def check_pdf(filename):
```

Use the PyMuPDF library to verify the structure of a PDF file.

#### Arguments

- `filename` *String* - The FQPN filename of the file in question to check

#### Returns

Tupple:A Tuppple that contains
    * Boolean - Is Clean (True if no issue, False if issue)
    * Generic error message, eg. expected generation number
    * Raw Error message, eg expected generation number (25366 ? obj)

Generic Error message is filtered, to try to remove changing data, so
 that it can be used in the filtered excel report.

.. code-block:

from pdf_utilities import check_pdf

```python
>>> check_pdf(r"test_samples\badpdf\Administrative - 30 - Consent to Treat 02-16-07 - 7712.pdf")
(False, 'expected generation number', 'expected generation number (25366 ? obj)')
>>> check_pdf(r"test_samples\badpdf\Administrative - 30 - PayPol 05-27-08 - 7713.pdf")
(False, 'expected generation number', 'expected generation number (17469 ? obj)')
>>> check_pdf(r"test_samples\goodpdf\CCD_extract_101001-00.html.pdf")
(True, '', '')
>>> check_pdf(r"test_samples\goodpdf\CCD_extract_101002-00.html.pdf")
(True, '', '')

## fallback_convert_image_to_pdf

[[find in source code]](blob/master/frontend/pdf_utilities.py#L219)

```python
def fallback_convert_image_to_pdf(sourcefile, targetfile, overwrite=False):
```

Last ditch external attempt to convert to PDF using ImageMagick-7.

#### Arguments

sourcefile (string) : Fully qualified pathname of the source file
targetfile (string) : Fully qualified pathname of the target file
overwrite (boolean) : Allow overwriting if True,
                      deny overwriting if False, default is False.

#### Returns

- `Tupple` - * The Return Status (boolean), true if no error, False if error
        * Error String

## get_all_fonts

[[find in source code]](blob/master/frontend/pdf_utilities.py#L50)

```python
def get_all_fonts(pdf_doc=None, filename=None):
```

pdf_doc  - the pyMuPDF document

## htmlfile_to_pdf

[[find in source code]](blob/master/frontend/pdf_utilities.py#L334)

```python
def htmlfile_to_pdf(
    input_file,
    output_file,
    overwrite=False,
    landscape=False,
    height='11in',
    width='8.5in',
):
```

html to PDF via wkhtmltopdf.

#### Arguments

- `input_file` *string* - input filename
- `output_file` *string* - output filename
- `overwrite` *string* - If true, allow overwriting of existing files
- `landscape` *string* - If True, use landscape mode, otherwise portrait
- `height` *string* - The height of the output document
- `width` *string* - The width of the output document

#### Returns

- `tupple` - (status (boolean), Description(string) )

## imgfile_to_pdf

[[find in source code]](blob/master/frontend/pdf_utilities.py#L243)

```python
def imgfile_to_pdf(sourcefile, targetfile, overwrite=False):
```

Use the img2pdf library to create a lossless PDF from an image.

#### Arguments

- `sourcefile` *string* - The FQPN filename of the file in question
                     to convert
targetfile (string) : Fully qualified pathname of the target file
overwrite (boolean) : Allow overwriting if True,
                      deny overwriting if False, default is False.

#### Returns

- `Boolean` - True if converted successfully, otherwise False

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

- `Note` - Assumes that the target directory already exists

https://gitlab.mister-muffin.de/josch/img2pdf
https://pypi.org/project/img2pdf/

## imgmem_to_pdf

[[find in source code]](blob/master/frontend/pdf_utilities.py#L289)

```python
def imgmem_to_pdf(sourcedata, targetfile, overwrite=False):
```

Use the img2pdf library to create a lossless PDF from an image.

#### Arguments

- `sourcedata` *blob* - The memory blob that contains the data from the image
    (eg. The image file that was read into memory)

- `targetfile` *string* - The filename to write the image to

- `overwrite` *boolean* - If true, overwrite the (potentially) existing file.

#### Returns

- `Boolean` - True if converted successfully, otherwise False

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

- `Note` - Assumes that the target directory already exists

https://gitlab.mister-muffin.de/josch/img2pdf
https://pypi.org/project/img2pdf/

## remove_font

[[find in source code]](blob/master/frontend/pdf_utilities.py#L71)

```python
def remove_font(pdf_doc=None, filename=None, font_name_list=[]):
```

#### Arguments

pdf_doc (PyMuPDF Document):
font_name (List of Strings) : A list of strings to match for element 5
      - eg. font_list = ['90ms-RKSJ-V', '90ms-RKSJ-H']

#### Returns

- `pyMuPDF` - The Document container

#### Examples

```python
>>> import pdf_utilities
>>> filename = r"C:k83_01-23-2019_g2documentupld_Insurance_Card.pdf"
>>> import fitz
>>> doc = fitz.open(filename)
>>> font_list = ['90ms-RKSJ-V', '90ms-RKSJ-H']
>>> doc = pdf_utilities.remove_font(doc, font_list)
>>> doc.save("test2.pdf")
```

* xref (int) is the font object number,  # element 0
* ext (str) font file extension (e.g. ttf, see Font File Extensions), #1
* type (str) is the font type (like Type1 or TrueType etc.), # element 2
* basefont (str) is the base font name,                      # element 3
* name (str) is the reference name (or label), by which the page
            references the font in its contents stream(s)    # element 4
* encoding (str optional) the font’s character encoding if different
  from its built-in encoding
  (Adobe PDF Reference 1.7, p. 414)  # element 5

## repair_pdf

[[find in source code]](blob/master/frontend/pdf_utilities.py#L121)

```python
def repair_pdf(origname, newname, forced=False):
```

Attempt to repair a PDF file.

#### Arguments

- `origname` *string* - The original filename
- `newname` *string* - The new filename
- `forced` *boolean* - Override damage auto-detection.  If set True,
    the repair will be forcibly done.  If False, auto-detection must
    detect the damage, before it will be fixed.

#### Returns

- `Boolean` - True, File has been fixed.  False, File is untouched.

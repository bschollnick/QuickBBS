# Test Pdf

> Auto-generated documentation for [frontend.test_pdf](blob/master/frontend/test_pdf.py) module.

- [Quickbbs](../README.md#quickbbs-index) / [Modules](../MODULES.md#quickbbs-modules) / [Frontend](index.md#frontend) / Test Pdf
    - [check_pdf](#check_pdf)
    - [return_image_obj](#return_image_obj)

## check_pdf

[[find in source code]](blob/master/frontend/test_pdf.py#L8)

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

## return_image_obj

[[find in source code]](blob/master/frontend/test_pdf.py#L63)

```python
def return_image_obj(fs_path, memory=False):
```

Given a Fully Qualified FileName/Pathname, open the image
(or PDF) and return the PILLOW object for the image
Fitz == py

#### Arguments

fs_path (str) - File system path
memory (bool) - Is this to be mapped in memory

#### Returns

boolean

```python
`True` if uuid_to_test is a valid UUID, otherwise `False`.
```

#### Raises

obj

```python
Pillow image object
```

Examples
--------

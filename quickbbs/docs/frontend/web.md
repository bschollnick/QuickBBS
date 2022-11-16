# Web

> Auto-generated documentation for [frontend.web](blob/master/frontend/web.py) module.

Web functionality

- [Quickbbs](../README.md#quickbbs-index) / [Modules](../MODULES.md#quickbbs-modules) / [Frontend](index.md#frontend) / Web
    - [detect_mobile](#detect_mobile)
    - [file_inline](#file_inline)
    - [g_option](#g_option)
    - [img_attach_file](#img_attach_file)
    - [respond_as_attachment](#respond_as_attachment)
    - [respond_as_inline](#respond_as_inline)
    - [return_img_attach](#return_img_attach)
    - [return_inline_attach](#return_inline_attach)
    - [verify_login_status](#verify_login_status)

## detect_mobile

[[find in source code]](blob/master/frontend/web.py#L41)

```python
def detect_mobile(request):
```

Is this a mobile browser?

#### Arguments

request (obj) - Django Request object

#### Returns

boolean

```python
`True` if Mobile is found in the request's META headers
specifically in HTTP USER AGENT.  If not found, returns False.
```

#### Raises

None

## file_inline

[[find in source code]](blob/master/frontend/web.py#L161)

```python
def file_inline(filename, fqfn):
```

Output a http response header, for an image attachment.

#### Arguments

- `filename` *str* - Filename of the file to be sent as the attachment name
- `binaryblob` *bin* - The blob of data that is the image file

#### Returns

object

```python
The Django response object that contains the attachment and header
```

#### Raises

None

Examples
--------
return_img_attach("test.png", img_data)

## g_option

[[find in source code]](blob/master/frontend/web.py#L35)

```python
def g_option(request, option_name, def_value):
```

Return the option from the request.get?

## img_attach_file

[[find in source code]](blob/master/frontend/web.py#L134)

```python
def img_attach_file(filename, fqfn):
```

Output a http response header, for an image attachment.

#### Arguments

- `filename` *str* - Filename of the file to be sent as the attachment name
- `binaryblob` *bin* - The blob of data that is the image file

#### Returns

object

```python
The Django response object that contains the attachment and header
```

#### Raises

None

Examples
--------
return_img_attach("test.png", img_data)

## respond_as_attachment

[[find in source code]](blob/master/frontend/web.py#L214)

```python
def respond_as_attachment(request, file_path, original_filename):
```

## respond_as_inline

[[find in source code]](blob/master/frontend/web.py#L188)

```python
def respond_as_inline(request, file_path, original_filename, ranged=False):
```

## return_img_attach

[[find in source code]](blob/master/frontend/web.py#L81)

```python
def return_img_attach(
    filename,
    binaryblob,
    fext_override=None,
    use_ranged=False,
):
```

Output a http response header, for an image attachment.

#### Arguments

- `filename` *str* - Filename of the file to be sent as the attachment name
- `binaryblob` *bin* - The blob of data that is the image file

#### Returns

object

```python
The Django response object that contains the attachment and header
```

#### Raises

None

Examples
--------
return_img_attach("test.png", img_data)

## return_inline_attach

[[find in source code]](blob/master/frontend/web.py#L58)

```python
def return_inline_attach(filename, binaryblob):
```

Output a http response header, for an image attachment.

#### Arguments

- `filename` *str* - Filename of the file to be sent as the attachment name
- `binaryblob` *bin* - The blob of data that is the image file

#### Returns

object

```python
The Django response object that contains the attachment and header
```

#### Raises

None

Examples
--------
return_img_attach("test.png", img_data, "JPEG")

## verify_login_status

[[find in source code]](blob/master/frontend/web.py#L17)

```python
def verify_login_status(request, force_login=False):
```

Verify login status

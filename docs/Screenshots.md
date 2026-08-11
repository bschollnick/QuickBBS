Screenshots
===========

A tour of QuickBBS's gallery UI, PDF handling, and video playback.

## Filetype color legend

Every gallery cell is tinted by its filetype, so you can tell at a glance what
you're looking at before the thumbnail even loads. The color comes from the
`color` field on the matching `filetypes` row and is applied as a CSS custom
property per cell (`templates/macros/gallery.jinja`).

These colors are **not hardcoded** — they're just the defaults seeded by
`python manage.py refresh_filetypes` (see `filetypes/management/commands/refresh_filetypes.py`).
Every extension's color is editable per-row in the Django admin (`filetypes`
app) or by adjusting the seed values and re-running `refresh_filetypes`, so
you can freely reassign or add colors to match your own taste or highlight
categories that matter to you. See [`QuickBBS.md`](QuickBBS.md#filetypes)
for full instructions on editing colors, adding new extensions, and where
the configuration lives.

| Color | Default hex | Applies to |
|---|---|---|
| ![#DAEFF5](https://placehold.co/60x20/DAEFF5/DAEFF5.png) | `#DAEFF5` | Directories |
| ![#FAEBF4](https://placehold.co/60x20/FAEBF4/FAEBF4.png) | `#FAEBF4` | Images / graphics, text files |
| ![#FDEDB1](https://placehold.co/60x20/FDEDB1/FDEDB1.png) | `#FDEDB1` | PDFs, links, EPUBs |
| ![#CCCCCC](https://placehold.co/60x20/CCCCCC/CCCCCC.png) | `#CCCCCC` | Movies, audio |
| ![#B2DECE](https://placehold.co/60x20/B2DECE/B2DECE.png) | `#B2DECE` | Archives |
| ![#FEF7DF](https://placehold.co/60x20/FEF7DF/FEF7DF.png) | `#FEF7DF` | HTML files |
| ![#FFFFFF](https://placehold.co/60x20/FFFFFF/E5E5E5.png) | `#FFFFFF` | Unknown/unrecognized files |

You can see this in action in the mixed-content screenshots below — blue
folders, pink images, yellow PDFs, and gray video thumbnails all sitting
side by side in the same directory listing.

## Directory browsing

### Mixed content directory

A directory containing a subfolder, videos, images, and a PDF all at once —
the background color of each cell makes the filetype obvious without reading
the filename or waiting for a thumbnail.

![Mixed directory of content](images/Viewing%20mixed%20directory%20of%20content.png)

Same idea, browsing up a level — folders (blue), a mixed subfolder, an image
gallery, a PDF collection, and a "motivators" folder, all color-coded
consistently:

![Mixed directory of content (parent view)](images/Viewing%20mixed%20directory2%20of%20content.png)

### Image gallery

A directory of images, each cell tinted pink/image-color, with file size and
modified date shown per thumbnail:

![Directory of graphics](images/Viewing%20directory%20of%20graphics.png)

### PDF directory

A directory of PDFs — note the yellow/gold tint shared with links and EPUBs:

![Directory of PDFs](images/Viewing%20directory%20of%20PDFs.png)

## Viewing individual items

### PDF viewer

Thumbnail view of a PDF before opening it:

![Thumbnail of a PDF](images/Viewing%20thumbnail%20of%20PDF.png)
![Thumbnail of a PDF (2)](images/Viewing%20thumbnail%20of%20PDF2.png)

Full-page PDF viewing at 100% zoom, with page navigation:

![PDF viewer at 100%](images/Viewing%20PDF%20%28at%20100%25%29%20in%20PDF%20viewer.png)
![PDF viewer at 100% (2)](images/Viewing%20PDF2%20%28at%20100%25%29%20in%20pdf%20viewer.png)

### Video playback

Thumbnail of a video before playback:

![Movie thumbnail](images/Viewing%20Movie%20thumbnail.png)

Inline video playback, small and large clip sizes:

![Playing a small movie](images/Viewing%20small%20movie%20%28while%20playing%29.png)
![Playing a larger movie](images/Viewing%20a%20larger%20movie%20%28while%20playing%29.png)

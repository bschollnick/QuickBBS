.. Gallery documentation master file, created by
   sphinx-quickstart on Sun Feb 15 15:25:48 2015.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Plugins included with Gallery
===================================

The Gallery (aka QuickBBS) Package is a Web Server, that can serve a multitude
of different file types right out of the box.

It is designed to act as a "Web Gallery" package, so that you can easily access,
and preview the content of the files, as you browse.


.. toctree::
   :titlesonly:
   :maxdepth: 2

Currently, the gallery supports these file formats, via the supplied plugins.

    * BMP           [.BMP, .DIB]
    * GIF           [.GIF]
    * HTML          [.HTM, .HTML]
    * JPG           [.JPG, .JPEG, .JPE, .JIF, .JFIF, .JFI]
    * MARKDOWN      [.MARKDOWN, .MARK, .MD]
    * PDF           [.PDF]
    * PNG           [.PNG]
    * Text Files    [.TXT, .TEXT]

In addition, the gallery software can view "simple" archives (*RAR*, *CBR*, *ZIP*, and *CBZ*
archives).  Gallery will show the archives, as if they were gallery pages.


The plugin framework is based on Yapsy (https://github.com/tibonihoo/yapsy/).


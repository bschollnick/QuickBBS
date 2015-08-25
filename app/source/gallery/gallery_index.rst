.. Gallery documentation master file, created by
   sphinx-quickstart on Sun Feb 15 15:25:48 2015.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Table of Contents
===================

.. toctree::
   :titlesonly:
   :maxdepth: 2

   Gallery - Installation <gallery_install>
   Gallery - URL Schemes <gallery_URLs>
   Gallery - Supported File Types <gallery_supported_filetypes>
   Gallery - Included Plugins <gallery_plugins>
   Gallery - Plugin API <gallery_plugin_api>
   Gallery - Benchmarks <gallery_benchmarks>


What is the Gallery?
===================================

The Gallery (aka QuickBBS) Package is a Web Server, that can serve a multitude
of different file types right out of the box.  I have been asked many times, about
restarting the QuickBBS Bulletin Board software, but I am using this as an exploration
to see what I might be able to do to re-invent the Web Server / Forum board(s) / Wiki environment.

The Gallery package, is a self contained "Image Gallery", so that you can easily access,
and preview the content of the files, as you browse.

The main features at this time, are:

* Thumbnail browsing
    * Thumbnail View
    * Archive Thumbnail View

* File View
    * Single Item View
    * Archive Single Item View

The gallery is a high performance, low resource, design.  It uses the file system as a flat database,
thus preventing the need for an database server, and a caching frontend.

Please note, this does not mean that you can't use a caching frontend, just that it is not strictly necessary.

The gallery can automatically create thumbnails for the following file types:

* BMP           [.BMP, .DIB]
* EPS           [.EPS]
* GIF           [.GIF]
* IM            [.IM]
* JPG           [.JPG, .JPEG, .JPE, .JIF, .JFIF, .JFI]
* MSP           [.MSP]
* PDF           [.PDF]
* PNG           [.PNG]
* PCX           [.PCX]
* PPM           [.PPM, .PGM, .PBM]
* TIFF          [.TIF, .TIFF]

In addition, the gallery software can view "simple" archives (*RAR*, *CBR*, *ZIP*, and *CBZ*
archives).  Gallery will show the archives, as if they were gallery pages.

The following formats, do not support automatic thumbnail creation, but can be viewed through the gallery.

* MARKDOWN      [.MARKDOWN, .MARK, .MD]
* Text Files    [.TXT, .TEXT]
* HTML          [.HTM, .HTML]


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

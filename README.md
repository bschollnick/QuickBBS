QuickBBS Gallery
========

* Please note, I am currently rewriting the archive features of the gallery.  It's almost done, and I hope to have it completely implemented by the end of the week.


What is this
=========
This is the start of a Modern re-interpretation of the QuickBBS Bulletin Board software, for the modern era.

Several times in the past, I have considered revisiting the old QuickBBS Bulletin Board software, but with the rise of the internet, I have never been able to justify it.

Yet I still occassionally get users asking about getting license keys, or copies of the software.  

I have recently been working on some projects that I have considered combining into a re-imagined version of QuickBBS, using modern web based technology.  This is the start of that.  Currently I am working on a Image Gallery / Viewer, which I will be expanding into a more fully featured package.


What's after the Gallery?
===========
After I finish the gallery / viewer, I will either add in a forum, and/or add a wiki or wiki equivalent.


What's the design
=================

The gallery application is intended to be a high performance, low resource, design.  It is a hybrid design using the file system, and a user configurable database.  The database is used to store details about the files, along with their thumbnails.  

How?  A request comes in for a directory to be displayed, the code scans the directory, checking for files.  If the file has not been seen, the Index data is stored for the file.  When a thumbnail request comes in, the application then checks to see if the thumbnail exists, and if not, creates it.

The gallery uses 3 different sizes of thumbnails, Large (Desktop web browser), Medium (Intended for Mobile), and Small (eg. Gallery thumbnails).  Each of the sizes are configurable.  

This is built-upon the Django Python web/cms database framework.  PILLOW, is used for the majority of the thumbnail/image creation, and FITZ is used for PDF thumbnailing.  


The gallery can automatically view the following file types:

* Jpeg - supports automatic thumbnail creation
* Png - supports automatic thumbnail creation
* gif - supports automatic thumbnail creation
* bmp - supports automatic thumbnail creation
* pdf - supports automatic thumbnail creation
* cbz, zip - supports automatic thumbnail creation
* cbr, rar - supports automatic thumbnail creation


Other requirements:
========

* Pillow - Used for Graphical conversions / Thumbnailing
   * libjpeg
   * zlib
   * libtiff
   * libfreetype
   * littlecms
   * libwebp
* Fitz - Used for creating thumbnails for PDF files
* Unrar - Used for accessing RAR files
* Jinja2 is the templating engine


Version 2 vs Version 1
==========

Version two is a significant rewrite of the gallery.  Version 1 was hampered by disk speed issues.

Version 1 was written utilizing only a file system, so it would attempt to cache the directory in memory, and the thumbnails were created on disk, and stored as seperate files.  It worked decently, but had issues with folders that had a significant (eg 3-4K) number of files in them.  In addition:

There were significant issues that impacted the speed of the software.

1) Creating the thumbnails in the webpage view was significantly impacting the speed, and delaying the rendering of the page
  * v2 resolves this by having the thumbnail view contain the code for the thumbnail creation.
  
In addition, I am currently converting the system over to using UUIDs (Universal Unique IDentifier)?  Why?  Because it simplifies the code significantly.  Previously I would have to lookup a file by searching the database by it's FileName, and Pathname.  Now when the Index Data is created, a UUID is created and assigned to it.  

Any reference to that file, is handled by sending the UUID.  

For example:

http://www.example.com/albums/catpixs   - Would give gallery listing of the catpixs directory

http://www.example.com/thumbnail/7109b28a-80f6-4a8f-8b48-ae86e052cdaa?small would produce a small thumbnail for the UUID specified (?medium would produce a medium size, ?large - etc).

http://www.example.com/viewitem/7109b28a-80f6-4a8f-8b48-ae86e052cdaa would display a gallery item view (A single standalone page for that item).

http://www.example.com/view_archive/7109b28a-80f6-4a8f-8b48-ae86e052cdaa would display a gallery listing of the contents of the archive.

http://www.example.com/view_arc_item/7109b28a-80f6-4a8f-8b48-ae86e052cdaa?page=4 would display a gallery item view of File #4 assuming it was a viewable file (eg. PDF, TXT, JPG, PNG, etc).  

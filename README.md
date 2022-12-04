QuickBBS Gallery
========


What is QuickBBS?
=========

This Django based version of QuickBBS, re-interpretation of the original QuickBBS Bulletin Board Software, for 
the modern era. 

Ideally, it will offer:

* Forums
* File Areas / Image Galleries - These are combined, and are mostly complete.
* Wiki Support - Limited support at this time, you can view HTML, Markdown, ASCII Text Files directly in the File Areas.
* TBD


What's the design
=================

The gallery application is intended to be a high performance, low resource, design.  It is a hybrid design using the 
file system, and a user configurable database.  The database is used to store details about the files, along with their
thumbnails.  

How?  A request comes in for a directory to be displayed, the code scans the directory, checking for files.  
If the file has not been seen, the Index data is stored for the file.  When a thumbnail request comes in, 
the application then checks to see if the thumbnail exists, and if not, creates it.

[![](https://mermaid.ink/img/pako:eNp1U8tOwzAQ_JWVT0GCH-gBqY2DxIFS9SEOBFVbZ5NYTexiO4KK8O84TlKghZwi78zs7I79wYTOiE1YYfBQwpqnCvz3RLslvTZkHdzc3ELLpSHhtDmCNnAnK7ItzKK4JLGH3G5jFCVt1wbFXqriqteYnVOVdiAVpL58wWkfopVABSf0IPLQi1zgg0o4gs0hQ0dZC_yZS3uo8AhvtDtgQS-_jNzpRmWdgZ72tw3gP_vOo4XRgqyFuERVkO3o5xbnAfoYxYa8j25BvaOwJ1iS0Caz4-AcHe7QEtyrjN63HoeDzGOQWYwy67KpdwplNSiMAqdzuw05dP1-nHlzdhBcBMF_Av2mtNPpEGRvqXMIuVftum029xx0Du7kxqEpyA0tptNebe6TDev1t2IWjSkkxmjzGxnH0TBOgA_FOD4zBVz7ybr7krxL61rOL9byLzUwbJsk0Yp83t8Fp0FUktRonvNATRJ2zWoyNcrMv4OPrpgyV1JNKZv434xybCqXslR9eig2Tq-OSrCJMw1dsyaEzSX6F1SzSY6Vpc8vj8oXmw?type=png)](https://mermaid.live/edit#pako:eNp1U8tOwzAQ_JWVT0GCH-gBqY2DxIFS9SEOBFVbZ5NYTexiO4KK8O84TlKghZwi78zs7I79wYTOiE1YYfBQwpqnCvz3RLslvTZkHdzc3ELLpSHhtDmCNnAnK7ItzKK4JLGH3G5jFCVt1wbFXqriqteYnVOVdiAVpL58wWkfopVABSf0IPLQi1zgg0o4gs0hQ0dZC_yZS3uo8AhvtDtgQS-_jNzpRmWdgZ72tw3gP_vOo4XRgqyFuERVkO3o5xbnAfoYxYa8j25BvaOwJ1iS0Caz4-AcHe7QEtyrjN63HoeDzGOQWYwy67KpdwplNSiMAqdzuw05dP1-nHlzdhBcBMF_Av2mtNPpEGRvqXMIuVftum029xx0Du7kxqEpyA0tptNebe6TDev1t2IWjSkkxmjzGxnH0TBOgA_FOD4zBVz7ybr7krxL61rOL9byLzUwbJsk0Yp83t8Fp0FUktRonvNATRJ2zWoyNcrMv4OPrpgyV1JNKZv434xybCqXslR9eig2Tq-OSrCJMw1dsyaEzSX6F1SzSY6Vpc8vj8oXmw)

The gallery uses 3 different sizes of thumbnails, Large (Desktop web browser), Medium (Intended for Mobile), and 
Small (eg. Gallery thumbnails).  Each of the sizes is configurable.  

This is built-upon the Django Python web/cms database framework.  
PILLOW, is used for the majority of the thumbnail/image creation, and FITZ is used for PDF thumbnailing.  

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


Version 3
============

The design is similar to Version 2, but I am splitting the Database structure by utilizing Django Apps.  

For example, the File Types are now in the FileTypes application, instead of being in the frontend app.  
I am restructuring the code to use this best practice, and I am expecting to be able to simplify the code in the frontend.
How?  I am moving more logic into the model, for example, the Thumbnails model now includes all of the code to manipulate the
thumbnails, and to Save and Delete thumbnails.

The database tables have been optimized more, and some redundancy has been removed.

The thumbnail tables have been most impacted.

* Index Data - Contains the overall index (e.g. File1, File2, Image1, Image2, Directory1, Directory2, etc)
* Thumbnails_Files - Contains the Index meta container for all Files (But not directories)
* Thumbnails_Dirs  - Contains the Index Meta Container for All Directories (But no files)

What are Thumbnail Index "Meta Containers"?

Unlike before, The thumbnail indexes do not contain the binary data for the Thumbnail, they contain a foreign key to a
Small, Medium, and Large Thumbnail table which does contain the binary data.

[![](https://mermaid.ink/img/pako:eNp9z8EKwjAMBuBXKTlV2F6gB0-7CHrajgVJm2wrtJ3UFpSxd7eyg4hgToH_-yFZwS7EoGBKeJvF0Oko6pwi8ePaYUbRtkeBKIe5BBPR-T077A733BjZB_T-gwY0nr-RtfLC5Er4q4jkGdPEvwgaCJwCOqrnru-ShjxzYA2qrsQjFp816LhViiUv_TNaUDkVbqDcCDN3DuujAdSI_s7bCwJMUnY?type=png)](https://mermaid.live/edit#pako:eNp9z8EKwjAMBuBXKTlV2F6gB0-7CHrajgVJm2wrtJ3UFpSxd7eyg4hgToH_-yFZwS7EoGBKeJvF0Oko6pwi8ePaYUbRtkeBKIe5BBPR-T077A733BjZB_T-gwY0nr-RtfLC5Er4q4jkGdPEvwgaCJwCOqrnru-ShjxzYA2qrsQjFp816LhViiUv_TNaUDkVbqDcCDN3DuujAdSI_s7bCwJMUnY)

Real World Testing needs to be done to see what impact the SmallThumbnail, MediumThumbnail, and LargeThumbnail foreign tables
will have, but I suspect that the speed to the Thumbnail Index would be extremely beneficial. 

There are a few experimental changes being made.

* Eliminating Cached_Exists.  The concept of the Cached_Exist engine was simply to cache the reads to the file system.  The Watchdog system basically eliminates the need for that, and removing the cached_exists engine could dramatically simplify the code.
* Completely embracing the watchdog system for detecting the changes happening in the gallery directories.  It was used in v2 to invalidate the cached_exist cache, but it would be easier to use that watchdog table to detect if we need to read from the file system instead.

But I will need to see if there is a performance degradation with this change.

In addition, as part of the change, I am planning to add code to eliminate left-overs in the database.  For example, situations where the file has removed from the directory, but is still in the database.  The current process has the entire directory removed from the database, and then rescanned to be re-added into the database.
The new logic will only delete or add the elements that need to be added.
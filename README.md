QuickBBS Gallery
========


What is QuickBBS?
=========

This Django based version of QuickBBS, an re-interpretation of the original QuickBBS Bulletin Board Software, for 
the modern era. 

Ideally, it will offer:

* Forums
* File Areas / Image Galleries - These are combined, and are mostly complete.
* Wiki Support - Limited support at this time, you can view HTML, Markdown, and ASCII Text Files directly in the File Areas.  There currently is no 
support for *editing* files at this time.
* TBD?


What's the design
=================

V3 & v2

The gallery application is intended to be a high performance, low resource, design.  It is a hybrid design using the 
file system, and a user configurable database.  The database is used to store details about the files, *along with their
thumbnails*.  That's correct, the thumbnail is stored as a binary blob in the PostgreSQL database for each file.  

Why?  Because creating 3 separate files in the file system for each file (Small, Medium, and Large thumbnails) can be done, but
you'll be limited to the speed of disk IO for the creation, searching for, and sending of the data.  Storing it in the database 
means that the bottle neck is the database, not necessarily your disk.  And these aren't big thumbnails, by default, 200x200, 
740x740, 1024x1024.  

How's it work?  A request comes in for a directory to be displayed, and the database looks up the directory in the database.  If
the directory has been previously scanned the cached data in the database is used, if it has not been previously
cached in the database (or the cache has been invalidated) the code scans the directory, checking for files. 

* If the file(s) are not in the database they will be added
* If the database has file(s) that are not in the directory, they will be removed
* If the file has been changed (Filesize, Last Modified Date) the database will be updated.

The cache is maintained by the Watchdog File System Monitor https://github.com/gorakhargosh/watchdog/.  Watchdog monitors the
entirety of the ALBUMS path, and if any file system changes are detected, the directory's is marked as being eligible to
be rescanned.  The data is not removed from the database, the next time that directory is viewed, it will be 
re-validated against the file system.

[![](https://mermaid.ink/img/pako:eNp1U9Fq4zAQ_JVFTyq0P5CHg8RyoXBJQ5NwcBjCWt7EoraUk2RoqPvvJ8lO2qSNn9a7M6PdHemdSVMRm7C9xUMNa1FoCN-TruhtK9AjPDz8AkS-rru21KiaoXY34HColyVftdg0CQRrLBu6BEjJ51Sprr2JqCr-G-0-Zof8Hypf6F9Hzqd6L5Ql6Y09grHwqBpyPcx4VpN8hZ3bZihr2q4tylel96P27JqqjQeloQjlb5x-zlcSNZzRlyKPptNVJCfWDQkY9zdPnAVfWiPJOchq1HtykX4tv0jQZ55ZQk9xuM2hilGcEV5IGlu5U9PRkRIdjQYFHI4yz0lmeZL5tGtQOAmc826bdhjP-5ILzblRcJkEBV9RGFsa7Ul78AZko0J097NJn1L9dDqa8-Uu7cJpsYvN5kmA2YE_d-mj9yfV6XRQWwS30tqD0zMulDs0eITcWmMvkVnGxzETfCxm2VVTIEyYON6B_E053wvxbV03qYnh-jwfFvJZuF6JEIma5-yetWRbVFV4Xu-xWDBfU0sFm4Swoh12jS9YoT8CFDtvVkct2cTbju5Zly6BUBgeZssmO2xcyB5Q_zXm9P_xH0P-Nos?type=png)](https://mermaid.live/edit#pako:eNp1U9Fq4zAQ_JVFTyq0P5CHg8RyoXBJQ5NwcBjCWt7EoraUk2RoqPvvJ8lO2qSNn9a7M6PdHemdSVMRm7C9xUMNa1FoCN-TruhtK9AjPDz8AkS-rru21KiaoXY34HColyVftdg0CQRrLBu6BEjJ51Sprr2JqCr-G-0-Zof8Hypf6F9Hzqd6L5Ql6Y09grHwqBpyPcx4VpN8hZ3bZihr2q4tylel96P27JqqjQeloQjlb5x-zlcSNZzRlyKPptNVJCfWDQkY9zdPnAVfWiPJOchq1HtykX4tv0jQZ55ZQk9xuM2hilGcEV5IGlu5U9PRkRIdjQYFHI4yz0lmeZL5tGtQOAmc826bdhjP-5ILzblRcJkEBV9RGFsa7Ul78AZko0J097NJn1L9dDqa8-Uu7cJpsYvN5kmA2YE_d-mj9yfV6XRQWwS30tqD0zMulDs0eITcWmMvkVnGxzETfCxm2VVTIEyYON6B_E053wvxbV03qYnh-jwfFvJZuF6JEIma5-yetWRbVFV4Xu-xWDBfU0sFm4Swoh12jS9YoT8CFDtvVkct2cTbju5Zly6BUBgeZssmO2xcyB5Q_zXm9P_xH0P-Nos)

The gallery uses 3 different sizes of thumbnails, Large (Desktop web browser), Medium (Intended for Mobile), and 
Small (eg. Gallery thumbnails).  Each of the sizes is configurable.  

Currently these categories, and file formats / extensions are supported for automatic detection and processing:

* GRAPHIC_FILE_TYPES - [".bmp", ".gif", ".jpg", ".jpeg", ".png", '.webp']
* PDF_FILE_TYPES - [".pdf", ]
* ARCHIVE_FILE_TYPES, which consists of:
   * RAR_FILE_TYPES - [".cbr", ".rar"]
   * ZIP_FILE_TYPES - [".cbz", ".zip"]
* HTML_FILE_TYPES - [".html", ".htm"]
* TEXT_FILE_TYPES - [".txt", ".markdown", ".text"]
* MOVIE_FILE_TYPES - [".mp4", ".mpg", ".mpg4", ".mpeg", ".mpeg4", ".wmv", '.flv', '.avi']
* AUDIO_FILE_TYPES - [".MP3", ]
* BOOK_FILE_TYPES - [".epub", ]
* MARKDOWN_FILE_TYPES - [".markdown", ]

For these types of files, a generic icon will be used, since there is no thumbnail available.

* HTML
* Text
* Audio

For these types of files, currently a generic icon will be used, thumbnail support will be a further enhancement or require a optional feature of the file.

* Epub - A thumbnail is included in the Epub
* Movies - "Your mileage may vary".  A thumbnail is created, but if the frame that is selected does not contain a useful 
thumbnail (e.g. is entirely black, white, or just non-euclidean in nature) then it may not be useful.



Version 2 vs Version 1
==========

Version two is a significant rewrite of the gallery.  Version 1 was hampered by disk speed issues, since there was no disk cache in v1.

Version 1 was written utilizing only a file system, so it would attempt to cache the directory in memory, and the thumbnails 
were created on disk, and stored as seperate files.  It worked decently, but had issues with folders that had a significant 
(eg 3-4K) number of files in them.  In addition:

There were significant issues that impacted the speed of the software.

1) Creating the thumbnails in the webpage view was significantly impacting the speed, and delaying the rendering of the page
  * v2 resolves this by having the thumbnail view contain the code for the thumbnail creation.
  
v2 and v3 use UUIDs (Universal Unique IDentifier) for all objects?  Why?  Because it simplifies the code significantly.  
Previously I would have to lookup a file by searching the database by it's FileName, and Pathname.  Now when the Index Data is 
created, a UUID is created and assigned to it.  All content related to that file is mapped using that UUID, both internally 
and via the web request.  

Any reference to that file, is handled by sending the UUID.  

http://www.example.com/albums/catpixs   - Would give gallery listing of the catpixs directory

http://www.example.com/thumbnail/7109b28a-80f6-4a8f-8b48-ae86e052cdaa?small would produce a small thumbnail for the UUID specified (?medium would produce a medium size, ?large - etc).

http://www.example.com/viewitem/7109b28a-80f6-4a8f-8b48-ae86e052cdaa would display a gallery item view (A single standalone page for that item).

http://www.example.com/view_archive/7109b28a-80f6-4a8f-8b48-ae86e052cdaa would display a gallery listing of the contents of the archive.

http://www.example.com/view_arc_item/7109b28a-80f6-4a8f-8b48-ae86e052cdaa?page=4 would display a gallery item view of File #4 assuming it was a viewable file (eg. PDF, TXT, JPG, PNG, etc).  


Version 3
============

Version 3 is still being worked on, but significant portions of the upgrade have already been added to the MASTER repository.  
The design is similar to Version 2, but many features and functions in the core of v2 are being split into separate Django Apps.  

What is being split into a separate application?

* Cache and Cache Management - Now dramatically simplified in comparison to v2.  A Watchdog monitor is now being used to 
monitor for disk changes in the ALBUMS_PATH.  Any changes will invalidate that directory, and force a rescan.
Cached_Exists, exists no longer!!
* FileTypes
* Frontend - Still contains the program logic, but now calls for the functions in the other apps.
* quickbbs - Configuration is now in quickbbs_settings.py, there is no longer a standalone CFG directory.
* thumbnails - contains the actual code for creating and managing the thumbnails (files and database cache)
   * Please note, do not confuse this for the thumbnails file in the frontend.  That currently contains the 
logic for using the thumbnails apps models, etc.  (I need to rename it to prevent confusion, eventually.)

v3 is roughly 60-70% done, but significant improvements in speed, performance, have been made.

* Index Data - Contains the overall index (e.g. File1, File2, Image1, Image2, Directory1, Directory2, etc)
* Thumbnails_Files - Contains the Index meta container for all Files (But not directories)
* Thumbnails_Dirs  - Contains the Index Meta Container for All Directories (But no files)

What are Thumbnail Index "Meta Containers"?

Unlike before, The thumbnail indexes do not contain the binary data for the Thumbnail, they contain a foreign key to a
Small, Medium, and Large Thumbnail table which does contain the binary data.

[![](https://mermaid.ink/img/pako:eNp9z8EKwjAMBuBXKTlV2F6gB0-7CHrajgVJm2wrtJ3UFpSxd7eyg4hgToH_-yFZwS7EoGBKeJvF0Oko6pwi8ePaYUbRtkeBKIe5BBPR-T077A733BjZB_T-gwY0nr-RtfLC5Er4q4jkGdPEvwgaCJwCOqrnru-ShjxzYA2qrsQjFp816LhViiUv_TNaUDkVbqDcCDN3DuujAdSI_s7bCwJMUnY?type=png)](https://mermaid.live/edit#pako:eNp9z8EKwjAMBuBXKTlV2F6gB0-7CHrajgVJm2wrtJ3UFpSxd7eyg4hgToH_-yFZwS7EoGBKeJvF0Oko6pwi8ePaYUbRtkeBKIe5BBPR-T077A733BjZB_T-gwY0nr-RtfLC5Er4q4jkGdPEvwgaCJwCOqrnru-ShjxzYA2qrsQjFp816LhViiUv_TNaUDkVbqDcCDN3DuujAdSI_s7bCwJMUnY)

Real World Testing needs to be done to see what impact the SmallThumbnail, MediumThumbnail, and LargeThumbnail foreign tables
will have, but I suspect that the speed to the Thumbnail Index would be extremely beneficial. Since at the same time we would
be reducing the size of the record for the index meta container.

There are a few experimental changes being made.

* Eliminating Cached_Exists.  The concept of the Cached_Exist engine was simply to cache the reads to the file system.  The Watchdog system basically eliminates the need for that, and removing the cached_exists engine could dramatically simplify the code.
  * Finished.
* Completely embracing the watchdog system for detecting the changes happening in the gallery directories.  It was used in v2 to invalidate the cached_exist cache, but it would be easier to use that watchdog table to detect if we need to read from the file system instead.
  * Finished.  A tremendous improvement in speed.  The first time an *large* directory of files is seen, there is a noticeable delay,
but after that, the speed is faster than the previous implementation with cached_exists.   

I am still performing code cleanup and removal of old redundant code.  

To Dos:

* investigate HTMX?  Django-HTMX?
* Investigate django-unicorn
  * Appears to be incompatible with using jinja templates
* Continue code cleanup
* Switch over to the v3 structures for templating
* Finish Title Search - Done for Gallery listing, need to update individual item page.
* Repair Archive Gallery & Individual item page(s)
  * It's been broken for a while under v2, I just rewritten it yet.


Version History
================

* Pre-v1 - Based on Twisted Matrix's Twisted Framework
* v1 - Before April of 2014
* v2 - October 30, 2017
* v3 (WIP) - Release date - TBD, started ~ 12/01/2022


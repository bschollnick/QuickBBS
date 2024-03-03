QuickBBS Gallery
========


What is QuickBBS?
=========

This Django based version of QuickBBS, an re-interpretation of the original QuickBBS Bulletin Board Software, for 
the modern era. 

Ideally, it will offer:

* Forums
* File Areas / Image Galleries - These are combined, and are mostly complete.
* Wiki Support - Limited support at this time, you can view HTML, Markdown, and ASCII Text Files directly in the File Areas.  There currently is no support for *editing* files at this time.
* TBD?


What's the design
=================

V3 Design

The gallery application is intended to be a high performance, low resource, design.  It is a hybrid design using the 
file system, and a user configurable database.  The database is used to store details about the files, *along with their
thumbnails*.  That's correct, the thumbnail is stored as a binary blob in the PostgreSQL database for each file.  

Why?  Because creating 3 separate files in the file system for each file (Small, Medium, and Large thumbnails) can be done, but
you'll be limited to the speed of disk IO for the creation, searching for, and sending of the data.  Storing it in the database 
means that the bottle neck is the database, not necessarily your disk.  And these aren't big thumbnails, by default, 200x200, 
740x740, 1024x1024.  

How's it work?  

A web request comes in, and is identified as one of the following:

* File Download
* Thumbnail (for a file)
* Thumbnail (for a directory)
* Thumbnail (for an archive) -- Please note, archive functionality needs to be rebuilt
* Display a gallery / folder 
* Display a File

The cache is maintained by the [Watchdog File System Monitor](https://github.com/gorakhargosh/watchdog/).  Watchdog monitors the
entirety of the ALBUMS path, and if any file system changes are detected, the directory's is marked as being eligible to
be rescanned.  The data is not removed from the database, the next time that directory is viewed, it will be 
re-validated against the file system.

[![](https://mermaid.ink/img/pako:eNqFVF1v6jAM_StWnzqJ_QEergRNJyENhvjQfbi9qkJraESbcJNUGhr779dJW8pgDB5QsH2O7WPjjyBTOQbDYKf5oYAVSyTQ50WUmE5kju_w_PwLOA9XRV1tJBcleHOSyEhJy4U0sKx4WQ5girmoqwF5XrneIdgzYlOqjXlqmJtvJjRmVuljk-TP-fcddjL0BYyJ7i9c0v3GzQL_1WisL_fU0yntezEnGIdRgdketiaNeFZgutI82wu5awsbX0OlsiAkUOpbzGkaLjMu-z6-kryoWuYO7FF3KKDVeuoxs3CuVYbGQFRwuUPj4Nf0Mx_6FkYauUXX3PqQu5frERaYKZ2brmjGLd9wg42kKcXxlubN08w7ml7ZhqEjONtN6jV0-S5sVFw31LknZOESqe2MJofSglWQlYJeTz-NqidsBzUatYNqynZdwJYyu4rW6wkDtb1YLetWrcswGjWcM5qcHwFNfRwyYQ4lP0KstdJfI6MobFv24a0ziq5KA6aoe7cP8bsw9sTYjXR3oR5hTnHciNM7ruVhzEPjOJEPler2QpBebLJIR-GrUvv60C8MxNKe18aH3EjjrHfk6QHu9a1I3vFIJ4q5K9W3BK1azvdYMMd-LpJkCwZBhbriIqd79uGCksAWWGESDOmZ45bXpU2CRH5SKK-tWh5lFgytrnEQ1P6fxASnS1gFwy0vDVnpppGc0-ZG-lP5-R8qXrTM?type=png)](https://mermaid.live/edit#pako:eNp1U9Fq4zAQ_JVFTyq0P5CHg8RyoXBJQ5NwcBjCWt7EoraUk2RoqPvvJ8lO2qSNn9a7M6PdHemdSVMRm7C9xUMNa1FoCN-TruhtK9AjPDz8AkS-rru21KiaoXY34HColyVftdg0CQRrLBu6BEjJ51Sprr2JqCr-G-0-Zof8Hypf6F9Hzqd6L5Ql6Y09grHwqBpyPcx4VpN8hZ3bZihr2q4tylel96P27JqqjQeloQjlb5x-zlcSNZzRlyKPptNVJCfWDQkY9zdPnAVfWiPJOchq1HtykX4tv0jQZ55ZQk9xuM2hilGcEV5IGlu5U9PRkRIdjQYFHI4yz0lmeZL5tGtQOAmc826bdhjP-5ILzblRcJkEBV9RGFsa7Ul78AZko0J097NJn1L9dDqa8-Uu7cJpsYvN5kmA2YE_d-mj9yfV6XRQWwS30tqD0zMulDs0eITcWmMvkVnGxzETfCxm2VVTIEyYON6B_E053wvxbV03qYnh-jwfFvJZuF6JEIma5-yetWRbVFV4Xu-xWDBfU0sFm4Swoh12jS9YoT8CFDtvVkct2cTbju5Zly6BUBgeZssmO2xcyB5Q_zXm9P_xH0P-Nos?bgColor=!white)

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


[Older Version History](Past_Versions.md)

Version 3
============

Version 3 is still being worked on, but significant portions of the upgrade have already been added to the MASTER repository.  

What is being split into a separate application?

* Cache and Cache Management - Now dramatically simplified in comparison to v2.  A Watchdog monitor is now being used to 
monitor for disk changes in the ALBUMS_PATH.  Any changes will invalidate that directory, and force a rescan.  This greatly simplifies the cache management issue.
* FileTypes
* Frontend - Still contains the program logic, but now calls for the functions in the other apps.
* quickbbs - Configuration is now in quickbbs_settings.py, there is no longer a standalone CFG directory.
* thumbnails - contains the actual code for creating and managing the thumbnails (files and database cache)
   * Please note, do not confuse this for the thumbnails file in the frontend.  That currently contains the 
logic for using the thumbnails apps models, etc.  (I need to rename it to prevent confusion, eventually.)


* Index Data - Contains the overall index (e.g. File1, File2, Image1, Image2, Directory1, Directory2, etc)
* Thumbnails_Files - Contains the Index meta container for all Files (But not directories)
* Thumbnails_Dirs  - Contains the Index Meta Container for All Directories (But no files)

What are Thumbnail Index "Meta Containers"?

Unlike before, The thumbnail indexes do not contain the binary data for the Thumbnail, they contain a foreign key to a
Small, Medium, and Large Thumbnail table which does contain the binary data.

[![](https://mermaid.ink/img/pako:eNqNUcsKwjAQ_JWwZ_2BHjxIEQQ96a2Rsm1WG0jSEhNQxH93TUCrgprT7GZmH7MXaHtFUMDB49CJbSmddMfY5HChDYmlU3SSTvBLsC4xYJWguMOdmE5nYttF2zjUpk4_1SPOol0u8MZKyo1FY-rHT5XiJ1PMTd98ka9J6WhH-pz4v8AK_YFG-hR_ysmpF29K7akNvT-PDeJk_cWkvCqTfm6busEELHmLWvGBLvcOEkJHliQUDBXtMZogQborUzGGfnN2LRTBR5pAHBQGKjXyvBaKPZojZ9kcHnqdj55uf70BLMa1Zw?type=png)](https://mermaid.live/edit#pako:eNqNUcsKwjAQ_JWwZ_2BHjxIEQQ96a2Rsm1WG0jSEhNQxH93TUCrgprT7GZmH7MXaHtFUMDB49CJbSmddMfY5HChDYmlU3SSTvBLsC4xYJWguMOdmE5nYttF2zjUpk4_1SPOol0u8MZKyo1FY-rHT5XiJ1PMTd98ka9J6WhH-pz4v8AK_YFG-hR_ysmpF29K7akNvT-PDeJk_cWkvCqTfm6busEELHmLWvGBLvcOEkJHliQUDBXtMZogQborUzGGfnN2LRTBR5pAHBQGKjXyvBaKPZojZ9kcHnqdj55uf70BLMa1Zw)

In v3, the Directories are in a separate table, and the small Thumbnail blob contained within the record.  The File Index still has the foreign table for the Thumbnails to help speed up the searching for specific files.


To Dos:

* investigate HTMX?  Django-HTMX?
* Investigate django-unicorn
  * Appears to be incompatible with using jinja templates
* Continue code cleanup
* Finish Title Search - Done for Gallery listing, need to update individual item page.


Version History
================

* Pre-v1 - Based on Twisted Matrix's Twisted Framework
* v1 - Before April of 2014
* v2 - October 30, 2017
* v3 (WIP) - Release date - TBD, started ~ 12/01/2022
    * (This has taken longer than expected, since I haven't been working on this extensively.)
    * Major changes, finished ~ 03/03/2024 - Mostly testing and minor tweaks at this point.  

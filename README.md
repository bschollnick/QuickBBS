QuickBBS Gallery
========

* Please note, I have started on v2 of the Gallery application.  See below.

This is the start of a Modern re-interpretation of the QuickBBS Bulletin Board software, for the modern era.

Several times in the past, I have considered revisiting the old QuickBBS Bulletin Board software, but with the rise of the internet, I have never been able to justify it.

Yet I still occassionally get users asking about getting license keys, or copies of the software.  

I have recently been working on some projects that I have considered combining into a re-imagined version of QuickBBS, using modern web based technology.

This is the start of that.  Currently I am working on a Image Gallery / Viewer, which I will be expanding into a more fully featured package.  After I finish the gallery / viewer, I plan to next add a wiki or wiki equivalent.

The gallery is a high performance, low resource, design.  It uses the file system as a flat database, thus preventing the
need for a database server, and a caching frontend.  Please note, this does not mean that you can't use a caching frontend, just that it is not strictly necessary.

The gallery can automatically view the following file types:

* Jpeg - supports automatic thumbnail creation
* Png - supports automatic thumbnail creation
* gif - supports automatic thumbnail creation
* bmp - supports automatic thumbnail creation
* pdf - supports automatic thumbnail creation
* cbz, zip - supports automatic thumbnail creation
* cbr, rar - supports automatic thumbnail creation

The following formats, do not support automatic thumbnail creation, but can be viewed through the gallery.

* txt 
* webloc
* epub
* mp4
* html

Installation
========

This is not the formal install method, once I am finished there will be a much more streamlined install process.

If you do not have PIP, Install PIP

1) download get-pip.py securely (http://www.pip-installer.org/en/latest/installing.html)
2) run get-pip.py with administrator access

Other requirements:
========

* Pillow - Used for Graphical conversions / Thumbnailing
   * libjpeg
   * zlib
   * libtiff
   * libfreetype
   * littlecms
   * libwebp
* Jinja Templating Engine
* Ghostscript - Used for creating thumbnails for PDF files
* Unrar - Used for accessing RAR files
* jinja2 is the templating engine
* passlib is used for user account & password management
* txbonjour is used for Bonjour / Zeroconf broadcasting (if turned on).  This allows any Bonjour aware web browser (e.g. desktop safari) to be able to automatically detect, and use the gallery.
   * txbonjour requires pybonjour as a preq. 
* unidecode is used to in normalizing unicode filenames.

Suggested methods for adding these requirements:
========

* install homebrew, if you do not have it installed.  (See http://brew.sh) 
   * ruby -e "$(curl -fsSL https://raw.github.com/mxcl/homebrew/go)"
   * brew doctor
* brew install libjpeg libtiff  webp littlecms
     (littlecms - includes freetype and libpng as dependencies)
* brew install unrar
* Install pillow
   * sudo pip install Pillow
* Install Ghostscript
   * brew install ghostscript

When you install Pillow, you should receive the following messages:
--- TKINTER support available
--- JPEG support available
--- ZLIB (PNG/ZIP) support available
--- TIFF G3/G4 (experimental) support available
--- FREETYPE2 support available
--- LITTLECMS support available
--- WEBP support available
--- WEBPMUX support available

* Other Python preqs:
   * pip install jinja2 passlib pybonjour txbonjour unidecode
   * Download directory_caching, and semantic_url.
      * Both are available from my repository.  I am having issues with PIP downloading. They are searchable in pip, but install fails.

Version 2
==========

Version two is a significant rewrite of the gallery.

While Version one was successful, there were significant issues that impacted the speed of the software.

1) Creating the thumbnails in the webpage view was significantly impacting the speed, and delaying the rendering of the page
  * v2 resolves this by having the thumbnail view contain the code for the thumbnail creation.
  * v2 is using python-thumbnails,  https://github.com/python-thumbnails/python-thumbnails, while there are issues, it appears to be faster, and handles the cache management.  Currently, I am using the straight python code, but I may incorporate the Django code (later).
  
2) I will be looking into converting Directory_Caching into a Django based package, and using the Database.
  * This will be the largest hurdle to overcome, but I believe this is the right step to make this maintainable, and optimize performance.
  

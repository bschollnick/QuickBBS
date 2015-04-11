QuickBBS
========

A Modern re-interpretation of the QuickBBS Bulletin Board software

I have considered revisiting the old QuickBBS Bulletin Board software, but with the rise of the internet,
I have never been able to justify it.  I have never seen a advantage a telnet based BBS versus a modern
web based forum.  Or a simple web server.

But I have been working on some personal projects lately, which I am considering combining into a
re-imagined version of QuickBBS, using modern web based technology.

This is very beta, at this time.

This is not the formal install method, once I am finished there will be a much more streamlined install process.

If you do not have PIP, Install PIP

1) download get-pip.py securely (http://www.pip-installer.org/en/latest/installing.html)
2) run get-pip.py with administrator access

Other requirements:

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

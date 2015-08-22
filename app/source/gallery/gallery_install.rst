.. Gallery documentation master file, created by
   sphinx-quickstart on Sun Feb 15 15:25:48 2015.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Installation
=============

    This is not the formal install method, once I am finished there will be a much more streamlined install process.

    If you do not have PIP, Install PIP

    1) download get-pip.py securely (http://www.pip-installer.org/en/latest/installing.html)
    2) run get-pip.py with administrator access

  Other requirements:
  ====================

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

    Manual Install:
    =================================================

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
          * pip install directory_caching
          * pip install semantic_url


    install script:
    =================================================

    In the /tools directory, you will find 3 scripts.

    These scripts will only install packages that are available via pip.
    So you will need to manually install *ghostscript*, and *unrar*.
    unrar is used for browsing rar files, and ghostscript is used to create the thumbnails
    for PDF files.

    * install_dependencies.sh, will install the necessary dependencies for the gallery.
      By default, pip installs to the Site Packages directory, so you may need superuser accesss (e.g. Sudo install_dependencies.sh).

    * uninstall_dependencies.sh, will have pip uninstall all the dependencies.

    * upgrade_dependencies.sh, will auto-update all of the dependencies.


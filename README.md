QuickBBS
========

A Modern re-interpretation of the QuickBBS Bulletin Board software


I have considered revisiting the old QuickBBS Bulletin Board software, but with the rise of the internet,
I have never been able to justify it.  I have never seen a advantage a telnet based BBS versus a modern
web based forum.  Or a simple web server.

But I have been working on some personal projects lately, which I am considering combining into a
re-imagined version of QuickBBS, using modern web based technology.

This is very beta, at this time.

This is not the formal install
Install PIP

1) download get-pip.py securely # http://www.pip-installer.org/en/latest/installing.html
2) run get-pip.py with administrator access

Other requirements:

* libjpeg
* zlib
* libtiff
* libfreetype
* littlecms
* libwebp
* Cheetah Template Engine

# install homebrew		(See http://brew.sh)

# http://stackoverflow.com/questions/12042537/installing-homebrew-via-shell-script

1) ruby -e "$(curl -fsSL https://raw.github.com/mxcl/homebrew/go)"

2) brew doctor
3) brew install libjpeg libtiff  webp littlecms
#  littlecms		# includes freetype and libpng as dependencies
4) brew install unrar

5) sudo pip install Pillow
6) brew install ghostscript

Should give:

    --- TKINTER support available
    --- JPEG support available
    --- ZLIB (PNG/ZIP) support available
    --- TIFF G3/G4 (experimental) support available
    --- FREETYPE2 support available
    --- LITTLECMS support available
    --- WEBP support available
    --- WEBPMUX support available

5) pip install jinja2 passlib pybonjour txbonjour unidecode
6) Download directory_caching, and semantic_url.
    Both are available from my repository.  I am having issues with PIP downloading.
    They are searchable in pip, but install fails.

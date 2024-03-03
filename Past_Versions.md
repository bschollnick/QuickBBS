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


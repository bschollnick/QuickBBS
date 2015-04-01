"""
Common file types for the Gallery

Contains code, and shortcuts for the filetypes.
"""
import os

filetype_dict = {
    '':      ('FFFFFF', ''),

    'jpeg':  ('FAEBF4', ''),
    'jpg':   ('FAEBF4', ''),
    'png':   ('FAEBF4', ''),
    'gif':   ('FAEBF4', ''),
    'bmp':   ('FAEBF4', ''),

    'pdf':   ('fdedb1', '/resources/adobe-pdf-logo100.png'),
    'txt':   ('fdedb1', '/resources/Web-TML-icon.png'),
    'webloc':('FAEBF4', '/resources/adobe-pdf-logo100.png'),
    'epub':  ('fdedb1', '/resources/adobe-pdf-logo100.png'),

    'dir':   ('DAEFF5', ''),

    'mpg':   ('CCCCCC', '/resources/MovieIcon100.jpg'),
    'mpg4':  ('CCCCCC', '/resources/MovieIcon100.jpg'),
    'mpeg':  ('CCCCCC', '/resources/MovieIcon100.jpg'),
    'mpeg4': ('CCCCCC', '/resources/MovieIcon100.jpg'),

    'htm':   ('fef7df', '/resources/Web-TML-icon.png'),
    'html':  ('fef7df', '/resources/Web-TML-icon.png'),

    'cbz':   ('b2dece', ''),
    'cbr':   ('b2dece', ''), # '/resources/rar_1.png'),
    'rar':   ('b2dece', ''), # '/resources/rar_1.png'),
    'zip':   ('b2dece', '')  # '/resources/zip.gif'),
}

#
#   http://stackoverflow.com/questions/502/
#               get-a-preview-jpeg-of-a-pdf-on-windows
#
graphic_file_types = ['bmp', 'gif', 'jpg', 'jpeg', 'png']
pdf_file_types = ['pdf']
rar_file_types = ['cbr', 'rar']
zip_file_types = ['cbz', 'zip']

archive_file_types = rar_file_types + zip_file_types

files_to_ignore = ['.ds_store',
                   '.htaccess',
                   'thumbs.db',
                   'downloaded_site.webloc',
                   'update_capture.command']

image_safe_files = graphic_file_types + \
    pdf_file_types + archive_file_types

files_to_cache = graphic_file_types + \
    pdf_file_types + archive_file_types

locations = {}
locations["server_root"] = os.path.abspath("")
#locations["albums_root"] = os.path.join(locations["server_root"], "albums")
locations["albums_root"] = r"/Volumes/NewStorage/gallery/"
locations["templates_root"] = os.sep.join(
    [locations["server_root"], "templates"])

locations["resources_root"] = os.sep.join(
    [locations["server_root"], "resources"])

locations["images_root"] = os.sep.join(
    [locations["resources_root"], "images"])

locations["javascript_root"] = os.sep.join(
    [locations["resources_root"], "javascript"])

locations["css_root"] = os.sep.join(
    [locations["resources_root"], "css"])

locations["fonts_root"] = os.sep.join(
    [locations["resources_root"], "fonts"])

#locations["thumbnails_root"] = os.sep.join([locations["server_root"],\
#    "thumbnails"])

locations["thumbnails_root"] = r"/Volumes/NewStorage/gallery/thumbnails"

locations["server_log"] = os.sep.join([locations["server_root"], "server.log"])

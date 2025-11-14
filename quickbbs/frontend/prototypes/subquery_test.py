from django.db.models import F, OuterRef, Subquery, Value
from thumbnails.models import ThumbnailFiles

from quickbbs.models import *

thumb_subquery = ThumbnailFiles.objects.filter(sha256_hash=OuterRef("file_sha256")).count()
dirpath = "/volumes/c-8tb/gallery/quickbbs/albums/hentai_idea/comics/_marvel/spidey/1988601_marvel_|_venom/"
success, dirpath_id = IndexDirs.search_for_directory(dirpath)
db_directories = dirpath_id.dirs_in_dir()
fs_entries = ["test1", "test2", "test3"]
db_data = dirpath_id.files_in_dir().annotate(FileDoesNotExist=Value(F("name") not in fs_entries)).annotate(active_thumbs=Subquery(thumb_subquery))

from django.db.models import F, OuterRef, Subquery, Value
from thumbnails.models import ThumbnailFiles

from quickbbs.directoryindex import DIRECTORYINDEX_SR_FILETYPE_THUMB
from quickbbs.fileindex import FILEINDEX_SR_FILETYPE_HOME_VIRTUAL
from quickbbs.models import *

thumb_subquery = ThumbnailFiles.objects.filter(sha256_hash=OuterRef("file_sha256")).count()
dirpath = "/volumes/c-8tb/gallery/quickbbs/albums/hentai_idea/comics/_marvel/spidey/1988601_marvel_|_venom/"
success, dirpath_id = IndexDirs.search_for_directory(dirpath, DIRECTORYINDEX_SR_FILETYPE_THUMB, ())
db_directories = dirpath_id.dirs_in_dir(select_related=DIRECTORYINDEX_SR_FILETYPE_THUMB, prefetch_related=())
fs_entries = ["test1", "test2", "test3"]
db_data = (
    dirpath_id.files_in_dir(select_related=FILEINDEX_SR_FILETYPE_HOME_VIRTUAL)
    .annotate(FileDoesNotExist=Value(F("name") not in fs_entries))
    .annotate(active_thumbs=Subquery(thumb_subquery))
)

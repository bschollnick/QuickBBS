import datetime
import math
import os
import time
from functools import lru_cache
from itertools import chain
from pathlib import Path

import markdown2
from cache_watcher.models import Cache_Storage
from cachetools import LRUCache, cached
from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.http import (  # HttpResponse,
    Http404,
    HttpRequest,
    HttpResponseBadRequest,
    HttpResponseNotFound,
    JsonResponse,
)
from filetypes.models import load_filetypes  # , filetypes
from frontend.utilities import (
    SORT_MATRIX,
    convert_to_webpath,
    return_breadcrumbs,
    sort_order,
)
from frontend.web import detect_mobile, g_option  # , respond_as_attachment

from quickbbs.models import IndexData

layout_manager_cache = LRUCache(maxsize=500)

build_context_info_cache = LRUCache(maxsize=500)


@cached(build_context_info_cache)
def build_context_info(request: WSGIRequest, unique_file_sha256: str):
    """
    Create the JSON package for item view.  All Json *item* requests come here to
    get their data.

    Parameters
    ----------
    request : Django requests object
    file_sha256 : The SHA256 hash of the item to get the information on.

    Returns
    -------
    JsonResponse : The Json response from the web query.
    """
    if not unique_file_sha256:
        return HttpResponseBadRequest(content="No SHA256 provided.")

    unique_file_sha256 = unique_file_sha256.strip().lower()
    try:
        entry = IndexData.get_by_sha256(unique_file_sha256, unique=True)
    except IndexData.DoesNotExist:
        return HttpResponseBadRequest(content="No entry found.")

    context = {
        "start_time": time.perf_counter(),
        "unique_file_sha256": unique_file_sha256,
        "file_sha256": entry.file_sha256,
        "sort": sort_order(request) if request else 0,
        "html": "",
        "breadcrumbs": "",
        "breadcrumbs_list": [],
        "webpath": entry.fqpndirectory.lower().replace("//", "/"),
        "mobile": detect_mobile(request) if request else False,
    }
    directory_entry = entry.home_directory

    breadcrumbs = return_breadcrumbs(context["webpath"])
    for bcrumb in breadcrumbs:
        context["breadcrumbs"] += f"<li>{bcrumb[2]}</li>"
        context["breadcrumbs_list"].append(bcrumb[2])

    filename = context["webpath"].replace("/", os.sep).replace("//", "/") + entry.name

    if entry.filetype.is_text or entry.filetype.is_markdown:
        with open(filename, "r", encoding="ISO-8859-1") as textfile:
            context["html"] = markdown2.Markdown().convert(
                "\n".join(textfile.readlines())
            )
    if entry.filetype.is_html:
        with open(filename, "r", encoding="utf-8") as htmlfile:
            context["html"] = "<br>".join(htmlfile.readlines())

    pathmaster = Path(os.path.join(entry.fqpndirectory, entry.name))
    context["up_uri"] = convert_to_webpath(str(pathmaster.parent)).rstrip("/")

    all_shas = list(
        directory_entry.files_in_dir(sort=context["sort"])
        .only("unique_sha256")
        .values_list("unique_sha256", flat=True)
    )
    if context["mobile"]:
        context["size"] = "medium"
    else:
        context["size"] = "large"

    try:
        current_page = all_shas.index(unique_file_sha256) + 1
    except ValueError:
        current_page = 1

    context.update(
        {
            "filetype": entry.filetype.__dict__,
            "page": current_page,
            "first_sha": all_shas[0],
            "last_sha": all_shas[len(all_shas) - 1],
            "pagecount": len(
                all_shas
            ),  # item_list.count,  # Switch this to math only, no paginator?
            "sha": entry.unique_sha256,
            "filename": entry.name,
            "filesize": entry.size,
            "duration": entry.duration,
            "is_animated": entry.is_animated,
            "lastmod": entry.lastmod,
            "lastmod_ds": datetime.datetime.fromtimestamp(entry.lastmod).strftime(
                "%m/%d/%y %H:%M:%S"
            ),
            "ft_filename": entry.filetype.icon_filename,
            "download_uri": entry.get_download_url(),
            "next_sha": "",
            "previous_sha": "",
            "dir_link": f'{context["webpath"]}{entry.name}?sort={context["sort"]}',
            "thumbnail_uri": entry.get_thumbnail_url(size=context["size"]),
        }
    )
    context["page_locale"] = int(context["page"] / settings.GALLERY_ITEMS_PER_PAGE) + 1
    # up_uri uses this to return you to the same page offset you were viewing

    # generate next sha pointers, switch this away from paginator?
    if current_page < len(all_shas):
        context["next_sha"] = all_shas[
            current_page
        ]  # current_page is 1-indexed, so this gives us next
    else:
        context["next_sha"] = ""

    if current_page > 1:
        context["previous_sha"] = all_shas[current_page - 2]  # Get the previous item
    else:
        context["previous_sha"] = ""
    print(f"Context built in {time.perf_counter() - context['start_time']} seconds")
    return context


@cached(layout_manager_cache)
def layout_manager(page_number=0, directory=None, sort_ordering=None):
    """
    Optimized layout manager with better performance and readability.
    Used by the new_viewgallery function to manage pagination and data retrieval.
    """
    start_time = time.perf_counter()
    if directory is None:
        raise ValueError("Directory parameter is required")

    chunk_size = settings.GALLERY_ITEMS_PER_PAGE

    # Optimize database queries with select_related/prefetch_related if needed
    # and only fetch what we need
    directories_queryset = directory.dirs_in_dir(sort=sort_ordering)
    files_queryset = directory.files_in_dir(sort=sort_ordering)

    # Get SHA256s in batches instead of loading everything at once
    directories = list(directories_queryset.values_list("dir_fqpn_sha256", flat=True))
    files = list(files_queryset.values_list("unique_sha256", flat=True))

    # Get counts once and cache them
    dirs_count = len(directories)
    files_count = len(files)
    # total_items = dirs_count + files_count

    # Calculate pagination info
    # total_pages = (total_items + chunk_size - 1) // chunk_size  # Ceiling division
    total_pages = max(1, math.ceil((dirs_count + files_count) / chunk_size))
    # Build base output structure
    output = {
        "data": {},
        "page_number": page_number,
        "page_range": list(range(1, total_pages + 1)),
        "dirs_count": dirs_count,
        "chunk_size": chunk_size,
        "files_count": files_count,
        "total_pages": total_pages,
        "numb_of_dirs_on_dir_lastpage": dirs_count % chunk_size,
        "numb_of_files_on_dir_lastpage": chunk_size - (dirs_count % chunk_size),
    }

    # Process pages more efficiently
    file_offset = 0
    for page_cnt in range(total_pages):
        start_idx = chunk_size * page_cnt
        end_idx = chunk_size * (page_cnt + 1)

        # Get directories for this page
        page_directories = directories[start_idx:end_idx]
        dirs_on_page = len(page_directories)

        # Calculate remaining space for files
        files_space = chunk_size - dirs_on_page
        page_files = (
            files[file_offset : file_offset + files_space] if files_space > 0 else []
        )
        files_on_page = len(page_files)

        # Build page data
        output["data"][page_cnt] = {
            "page": page_cnt,
            "directories": page_directories,
            "cnt_dirs": dirs_on_page,
            "files": page_files,
            "cnt_files": files_on_page,
            "total_cnt": dirs_on_page + files_on_page,
        }

        file_offset += files_on_page

    # Add remaining data

    output["all_shas"] = (
        directories + files
    )  # More efficient than itertools.chain for lists
    # Optimize the no_thumbnails query - only fetch SHA256
    output["no_thumbnails"] = list(
        directory.files_in_dir(
            sort=sort_ordering, additional_filters={"new_ftnail__isnull": True}
        ).values_list("file_sha256", flat=True)
    )
    print(f"Layout manager completed in {time.perf_counter() - start_time} seconds")
    return output

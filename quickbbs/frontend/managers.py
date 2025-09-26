import datetime
import math
import os
import time

# from functools import lru_cache
# from itertools import chain
from pathlib import Path

import charset_normalizer

import markdown2

# from cache_watcher.models import Cache_Storage
from cachetools import LRUCache, cached

from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.http import (  # HttpResponse,
    #    Http404,
    #    HttpRequest,
    HttpResponseBadRequest,
    #    HttpResponseNotFound,
    #    JsonResponse,
)

# from filetypes.models import load_filetypes
from frontend.utilities import (
    #    SORT_MATRIX,
    convert_to_webpath,
    return_breadcrumbs,
    sort_order,
)
from frontend.web import detect_mobile  # , g_option

from quickbbs.models import IndexData

layout_manager_cache = LRUCache(maxsize=500)

build_context_info_cache = LRUCache(maxsize=500)

# File size limit for text file processing (1MB)
MAX_TEXT_FILE_SIZE = 1024 * 1024


def get_file_text_encoding(filename: str) -> str:
    """
    Detect the text encoding of a file.

    :param filename: Path to the file to analyze
    :return: Detected encoding string, defaults to 'utf-8' if detection fails
    """
    try:
        with open(filename, "rb") as f:
            raw_data = f.read()
            result = charset_normalizer.from_bytes(raw_data)
            encoding = result.best().encoding
            return encoding if encoding else "utf-8"
    except (OSError, IOError):
        return "utf-8"


@cached(LRUCache(maxsize=1000))
def get_file_text_encoding_cached(filename: str, file_mtime: float) -> str:
    """
    Cache text encoding detection based on filename and modification time.

    :param filename: Path to the file to analyze
    :param file_mtime: File modification time for cache invalidation
    :return: Detected encoding string, defaults to 'utf-8' if detection fails
    """
    return get_file_text_encoding(filename)


@cached(build_context_info_cache)
def build_context_info(request: WSGIRequest, unique_file_sha256: str) -> dict | HttpResponseBadRequest:
    """
    Build context information for item view.

    All item view requests use this function to gather file metadata,
    navigation information, and rendering context.

    :param request: Django WSGIRequest object
    :param unique_file_sha256: The unique SHA256 hash of the item
    :return: Dictionary containing context data or HttpResponseBadRequest on error
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
    # Optimize breadcrumb building with list comprehension and join
    breadcrumb_parts = []
    breadcrumbs_list = []
    for bcrumb in breadcrumbs:
        breadcrumb_parts.append(f"<li>{bcrumb[2]}</li>")
        breadcrumbs_list.append(bcrumb[2])

    context["breadcrumbs"] = "".join(breadcrumb_parts)
    context["breadcrumbs_list"] = breadcrumbs_list

    filename = context["webpath"].replace("/", os.sep).replace("//", "/") + entry.name

    if entry.filetype.is_text or entry.filetype.is_markdown:
        try:
            file_size = os.path.getsize(filename)
            if file_size > MAX_TEXT_FILE_SIZE:
                context["html"] = f"<p><em>File too large to display ({file_size:,} bytes). Maximum size: {MAX_TEXT_FILE_SIZE:,} bytes.</em></p>"
            else:
                file_mtime = os.path.getmtime(filename)
                encoding = get_file_text_encoding_cached(filename, file_mtime)
                # Read with detected encoding - optimized to read entire file at once
                with open(filename, "r", encoding=encoding) as textfile:
                    context["html"] = markdown2.Markdown().convert(textfile.read())
        except (OSError, IOError) as e:
            context["html"] = f"<p><em>Error reading file: {str(e)}</em></p>"

    if entry.filetype.is_html:
        try:
            file_size = os.path.getsize(filename)
            if file_size > MAX_TEXT_FILE_SIZE:
                context["html"] = f"<p><em>File too large to display ({file_size:,} bytes). Maximum size: {MAX_TEXT_FILE_SIZE:,} bytes.</em></p>"
            else:
                file_mtime = os.path.getmtime(filename)
                encoding = get_file_text_encoding_cached(filename, file_mtime)
                # Read with detected encoding - optimized to read entire file at once
                with open(filename, "r", encoding=encoding) as htmlfile:
                    context["html"] = htmlfile.read().replace("\n", "<br>")
        except (OSError, IOError) as e:
            context["html"] = f"<p><em>Error reading file: {str(e)}</em></p>"

    # pathmaster = Path(os.path.join(entry.fqpndirectory, entry.name))
    pathmaster = Path(entry.full_filepathname)
    context["up_uri"] = convert_to_webpath(str(pathmaster.parent)).rstrip("/")

    all_shas = list(
        directory_entry.files_in_dir(sort=context["sort"])
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

    # Cache expensive calculations
    all_shas_count = len(all_shas)
    lastmod_timestamp = entry.lastmod

    context.update(
        {
            "filetype": entry.filetype.__dict__,
            "page": current_page,
            "first_sha": all_shas[0],
            "last_sha": all_shas[all_shas_count - 1],
            "pagecount": all_shas_count,
            "sha": entry.unique_sha256,
            "filename": entry.name,
            "filesize": entry.size,
            "duration": entry.duration,
            "is_animated": entry.is_animated,
            "lastmod": lastmod_timestamp,
            "lastmod_ds": datetime.datetime.fromtimestamp(lastmod_timestamp).strftime(
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

    # generate next sha pointers using cached count
    if current_page < all_shas_count:
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


def calculate_page_bounds(page_number: int, chunk_size: int, dirs_count: int, files_count: int) -> dict:
    """
    Calculate what directories and files belong on this page.

    Args:
        page_number: Current page number (1-indexed)
        chunk_size: Items per page
        dirs_count: Total directory count
        files_count: Total file count

    Returns:
        Dictionary with slice boundaries for directories and files
    """
    start_idx = (page_number - 1) * chunk_size
    end_idx = start_idx + chunk_size

    if start_idx < dirs_count:
        # Page starts with directories
        dirs_start = start_idx
        dirs_end = min(end_idx, dirs_count)
        dirs_on_page = dirs_end - dirs_start

        # Remaining space for files
        files_space = chunk_size - dirs_on_page
        files_start = 0
        files_end = files_space
    else:
        # Page is all files
        dirs_start = dirs_end = 0
        dirs_on_page = 0

        files_start = start_idx - dirs_count
        files_end = files_start + chunk_size

    return {
        'dirs_slice': (dirs_start, dirs_end) if dirs_on_page > 0 else None,
        'files_slice': (files_start, files_end) if files_end > files_start else None,
        'dirs_on_page': dirs_on_page
    }


@cached(layout_manager_cache)
def layout_manager(page_number: int = 1, directory=None, sort_ordering: int | None = None) -> dict:
    """
    Manage gallery layout with optimized database-level pagination.

    Uses database LIMIT/OFFSET for efficient pagination instead of loading
    all items into memory. Only fetches data for the requested page.

    Args:
        page_number: Current page number (1-indexed)
        directory: IndexDirs object representing the directory to layout
        sort_ordering: Sort order to apply (0-2)

    Returns:
        Dictionary containing pagination data and current page items

    Raises:
        ValueError: If directory parameter is None
    """
    start_time = time.perf_counter()
    if directory is None:
        raise ValueError("Directory parameter is required")

    chunk_size = settings.GALLERY_ITEMS_PER_PAGE

    # Get base querysets (no data loaded yet)
    directories_qs = directory.dirs_in_dir(sort=sort_ordering)
    files_qs = directory.files_in_dir(sort=sort_ordering)

    # Get counts efficiently without loading data
    dirs_count = directories_qs.count()
    files_count = files_qs.count()
    total_items = dirs_count + files_count

    # Calculate pagination
    total_pages = max(1, math.ceil(total_items / chunk_size))
    bounds = calculate_page_bounds(page_number, chunk_size, dirs_count, files_count)

    # Fetch ONLY current page data using database slicing
    page_data = {}

    if bounds['dirs_slice']:
        start, end = bounds['dirs_slice']
        page_directories = list(directories_qs[start:end].values_list("dir_fqpn_sha256", flat=True))
        page_data['directories'] = page_directories
        page_data['cnt_dirs'] = len(page_directories)
    else:
        page_data['directories'] = []
        page_data['cnt_dirs'] = 0

    if bounds['files_slice']:
        start, end = bounds['files_slice']
        page_files = list(files_qs[start:end].values_list("unique_sha256", flat=True))
        page_data['files'] = page_files
        page_data['cnt_files'] = len(page_files)
    else:
        page_data['files'] = []
        page_data['cnt_files'] = 0

    page_data['total_cnt'] = page_data['cnt_dirs'] + page_data['cnt_files']
    page_data['page'] = page_number

    # Build optimized output structure - only current page data
    output = {
        "data": page_data,  # Single page data instead of all pages
        "page_number": page_number,
        "dirs_count": dirs_count,
        "chunk_size": chunk_size,
        "files_count": files_count,
        "total_pages": total_pages,
        "numb_of_dirs_on_dir_lastpage": dirs_count % chunk_size,
        "numb_of_files_on_dir_lastpage": chunk_size - (dirs_count % chunk_size),
    }

    # Generate all_shas for current page only (much smaller)
    output["all_shas"] = page_data['directories'] + page_data['files']

    # Optimize the no_thumbnails query - only fetch SHA256
    output["no_thumbnails"] = list(
        directory.files_in_dir(
            sort=sort_ordering, additional_filters={"new_ftnail__isnull": True}
        ).values_list("file_sha256", flat=True)
    )

    print(f"Optimized layout manager completed in {time.perf_counter() - start_time} seconds")
    return output

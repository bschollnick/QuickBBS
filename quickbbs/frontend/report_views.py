"""
Report views for QuickBBS administrative reports.
"""

from __future__ import annotations

from collections import defaultdict

from asgiref.sync import sync_to_async
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from quickbbs.fileindex import FileIndex


async def async_render(
    request: HttpRequest,
    template_name: str,
    context: dict | None = None,
    **kwargs,
) -> HttpResponse:
    """
    Async wrapper for Django's render function.

    Args:
        request: HttpRequest object
        template_name: Template file name
        context: Context dictionary
        **kwargs: Additional arguments for render

    Returns:
        HttpResponse
    """
    return await sync_to_async(render)(request, template_name, context, **kwargs)


@sync_to_async
def _get_duplicate_sha_data() -> dict:
    """
    Query FileIndex for duplicate file_sha256 values with count > 5.

    Returns:
        Dictionary with 'groups' (ordered list of sha groups with files),
        'total_shas' count, and 'total_files' count.
    """
    # Query 1: Get duplicate SHAs with count > 5
    duplicate_shas = (
        FileIndex.objects.filter(
            file_sha256__isnull=False,
            delete_pending=False,
        )
        .values("file_sha256")
        .annotate(dupe_count=Count("file_sha256"))
        .filter(dupe_count__gt=5)
        .order_by("-dupe_count")
    )

    sha_counts = [(d["file_sha256"], d["dupe_count"]) for d in duplicate_shas]

    if not sha_counts:
        return {"groups": [], "total_shas": 0, "total_files": 0}

    sha_list = [s[0] for s in sha_counts]

    # Query 2: Get all file locations for those SHAs in one query
    all_files = (
        FileIndex.objects.filter(
            file_sha256__in=sha_list,
            delete_pending=False,
        )
        .select_related("home_directory")
        .values("file_sha256", "name", "home_directory__fqpndirectory")
        .order_by("home_directory__fqpndirectory", "name")
    )

    # Group files by SHA
    files_by_sha: dict[str, list[dict[str, str]]] = defaultdict(list)
    for f in all_files:
        files_by_sha[f["file_sha256"]].append(
            {
                "name": f["name"],
                "directory": f["home_directory__fqpndirectory"] or "(unknown)",
            }
        )

    # Build ordered result matching count order
    groups = []
    total_files = 0
    for sha, count in sha_counts:
        files = files_by_sha.get(sha, [])
        groups.append(
            {
                "sha256": sha,
                "count": count,
                "files": files,
            }
        )
        total_files += count

    return {
        "groups": groups,
        "total_shas": len(sha_counts),
        "total_files": total_files,
    }


async def duplicate_files_report(request: HttpRequest) -> HttpResponse:
    """
    Display a report of duplicate file SHA256 hashes with count > 5.

    Shows all file_sha256 values appearing more than 5 times in FileIndex,
    sorted by count descending, with the file locations for each.

    Args:
        request: HttpRequest object

    Returns:
        HttpResponse with rendered report
    """
    data = await _get_duplicate_sha_data()

    context = {
        "groups": data["groups"],
        "total_shas": data["total_shas"],
        "total_files": data["total_files"],
    }

    return await async_render(
        request,
        "reports/duplicate_files.jinja",
        context,
        using="Jinja2",
    )

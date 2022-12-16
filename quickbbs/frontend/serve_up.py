import os.path

from django.conf import settings
from django.views.static import serve


def resources(request, pathstr=None):
    """
    Serve the resources
    """
    if pathstr is None:
        return
    album_viewing = os.path.join(settings.RESOURCES_PATH, pathstr)
    if not os.path.exists(album_viewing):
        print("File Not Found - %s" % album_viewing)
    return serve(request, os.path.basename(album_viewing),
                 os.path.dirname(album_viewing))


def static(request, pathstr=None):
    """
    Serve the resources
    """
    if pathstr is None:
        return
    album_viewing = os.path.join(settings.STATIC_PATH, pathstr)
    if not os.path.exists(album_viewing):
        print(f"File Not Found - {album_viewing}")
    return serve(request, os.path.basename(album_viewing),
                 os.path.dirname(album_viewing))

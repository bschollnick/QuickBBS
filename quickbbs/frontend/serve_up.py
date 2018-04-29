from django.views.static import serve
from frontend.config import configdata as configdata
import os.path


def resources(request):
    """
    Serve the resources
    """
    webpath = request.path_info
    album_viewing = configdata["locations"]["resources_path"] +  \
        webpath.replace(r"/resources/", r"/").replace("/", os.sep)
    if not os.path.exists(album_viewing):
        print ("File Not Found - %s" % album_viewing)
    return serve(request, os.path.basename(album_viewing),
                 os.path.dirname(album_viewing))


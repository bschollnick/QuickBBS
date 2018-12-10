from django.views.static import serve
from frontend.config import configdata as configdata
import os.path


def resources(request, pathstr=None):
    """
    Serve the resources
    """
#    print ("resource, pathstr:",pathstr)
#    webpath = request.path_info
#    print ("request.path info:",webpath)
    if pathstr is None:
        return
    album_viewing = os.path.join(configdata["locations"]["resources_path"], pathstr)
#    print ("album_viewing:",album_viewing)
#    album_viewing = configdata["locations"]["resources_path"] +  \
#        webpath.replace(r"/resources/", r"/").replace("/", os.sep)
    if not os.path.exists(album_viewing):
        print ("File Not Found - %s" % album_viewing)
    return serve(request, os.path.basename(album_viewing),
                 os.path.dirname(album_viewing))

def static(request, pathstr=None):
    """
    Serve the resources
    """
    if pathstr is None:
        return
#    webpath = request.path_info
 #   album_viewing = configdata["locations"]["static_path"] +  \
 #       webpath.replace(r"/static/", r"/").replace("/", os.sep)
    album_viewing = os.path.join(configdata["locations"]["static_path"], pathstr)
    if not os.path.exists(album_viewing):
        print ("File Not Found - %s" % album_viewing)
    return serve(request, os.path.basename(album_viewing),
                 os.path.dirname(album_viewing))


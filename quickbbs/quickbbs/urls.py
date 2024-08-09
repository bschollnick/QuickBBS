"""quickbbs URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/1.9/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  url(r'^$', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  url(r'^$', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.conf.urls import url, include
    2. Add a URL to urlpatterns:  url(r'^blog/', include('blog.urls'))
"""

from django.conf import settings

# from django.conf.urls import url
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView

import frontend.serve_up
import frontend.views

urlpatterns = []
if settings.DEBUG_TOOLBAR:
    import debug_toolbar

    urlpatterns += [
        path("__debug__/", include(debug_toolbar.urls)),
    ]

urlpatterns += [
    path("search/", frontend.views.search_viewresults, name="search_viewresults"),
#    re_path("^download/", frontend.views.download_file, name="download"),
    re_path("^download/", frontend.views.download, name="download"),

    # the filename is not used, but is there for web browser to see the expected filename
    # when it was download/<str:uuid>, the web browser would believe the filename was the
    # uuid, and ignore the filename in the download header.
    path("info/<uuid:i_uuid>/", frontend.views.item_info, name="item_info"),
    path(
        "view_item/<uuid:i_uuid>/",
        frontend.views.new_json_viewitem,
        name="new_viewitem",
    ),
    # path(
    #     "view_archive/<uuid:i_uuid>",
    #     frontend.views.new_view_archive,
    #     name="new_view_archive",
    # ),
    # path(
    #     "view_archive_item/<uuid:i_uuid>",
    #     frontend.views.new_archive_item,
    #     name="new_archive_item",
    # ),
    re_path("^albums/", frontend.views.new_viewgallery, name="directories"),
    # path("thumbnails/<uuid:tnail_id>", frontend.views.thumbnails, name="thumbnails"),
    # path(
    #     "thumbnail_file/<uuid:tnail_id>",
    #     frontend.views.thumbnail_file,
    #     name="thumbnail_file",
    # ),
    path(
        "thumbnail_file/<uuid:tnail_id>",
        frontend.views.view_thumbnail,
        name="thumbnail_file",
    ),
    path(
        "thumbnail_directory/<uuid:tnail_id>",
        frontend.views.view_dir_thumbnail,
        name="thumbnail_dir",
    ),
    # path("thumbnails/", frontend.views.thumbnails, name="thumbnailspath"),
    path("resources/<path:pathstr>", frontend.serve_up.resources),
    path("static/<path:pathstr>", frontend.serve_up.static),
    re_path("^test/", frontend.views.test, name="test"),
     path("accounts/", include("allauth.urls")),
    path("grappelli/", include("grappelli.urls")),  # grappelli URLS
    path(r"Admin/", admin.site.urls),
    path(r"", RedirectView.as_view(url="/albums"), name="home"),
    #    path("unicorn/", include("django_unicorn.urls")),
]

# REGISTRATION_OPEN = True

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

import frontend.report_views
import frontend.serve_up
import frontend.views
import thumbnails.views
import user_preferences.views
from django.conf import settings
from django.conf.urls.static import static

# from django.conf.urls import url
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView

urlpatterns = []
if settings.DEBUG_TOOLBAR:
    import debug_toolbar

    urlpatterns += [
        path("__debug__/", include(debug_toolbar.urls)),
    ]

urlpatterns += [
    # Reports
    path("reports/duplicate_files.html", frontend.report_views.duplicate_files_report, name="duplicate_files_report"),
    path("search/", frontend.views.search_viewresults, name="search_viewresults"),
    path(
        "preferences/toggle-duplicates/",
        user_preferences.views.toggle_show_duplicates,
        name="toggle_show_duplicates",
    ),
    #    re_path("^download/", frontend.views.download_file, name="download"),
    # re_path("^download/", frontend.views.download_item, name="download"),
    re_path("^download_file/", frontend.views.download_file, name="download_file"),
    path(
        "view_item/<str:sha256>/",
        frontend.views.htmx_view_item,
        name="view_item",
    ),
    re_path("^albums/", frontend.views.new_viewgallery, name="directories"),
    path(
        "thumbnail2_file/<str:sha256>",
        thumbnails.views.thumbnail2_file,
        name="thumbnail2_file",
    ),
    path(
        "thumbnail2_directory/<str:dir_sha256>",
        thumbnails.views.thumbnail2_dir,
        name="thumbnail2_dir",
    ),
    path(
        "resources/<path:pathstr>",
        frontend.serve_up.static_or_resources,
        name="resources",
    ),
    path("static/<path:pathstr>", frontend.serve_up.static_or_resources, name="static"),
    path("accounts/", include("allauth.urls")),
    path("grappelli/", include("grappelli.urls")),  # grappelli URLS
    path(r"Admin/", admin.site.urls),
    path(r"", RedirectView.as_view(url="/albums"), name="home"),
]

urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
# REGISTRATION_OPEN = True

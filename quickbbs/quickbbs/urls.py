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
from django.urls import include, path, re_path
from django.conf.urls import url
from django.contrib import admin
from django.views.generic import RedirectView
import frontend
import frontend.views
import frontend.serve_up
from django.conf import settings

urlpatterns = []
if settings.DEBUG_TOOLBAR:
    import debug_toolbar
    urlpatterns += [
        url(r'__debug__/', include(debug_toolbar.urls)),
    ]

urlpatterns += [
    path('grappelli/', include('grappelli.urls')), # grappelli URLS
    path(r'Admin/', admin.site.urls),
    path(r'', RedirectView.as_view(url="/albums")),
    #path("download/<uuid:d_uuid>", frontend.views.new_download, name="downloads"),
    path("download/<str:filename>", frontend.views.download, name="newdownloads"),
    path("view_item/<uuid:i_uuid>/", frontend.views.new_viewitem, name="new_viewitem"),
    path('view_archive/<uuid:i_uuid>', frontend.views.new_view_archive, name="new_view_archive"),
    path("view_archive_item/<uuid:i_uuid>", frontend.views.new_archive_item, name="new_archive_item"),
    re_path('^albums/', frontend.views.new_viewgallery),
    path('thumbnails/<uuid:t_url_name>', frontend.views.thumbnails, name="thumbnails"),
    path('thumbnails/', frontend.views.thumbnails, name="thumbnailspath"),
    #re_path('^resources/', frontend.serve_up.resources),
    path('resources/<path:pathstr>', frontend.serve_up.resources),
    path('static/<path:pathstr>', frontend.serve_up.static),
    path('accounts/', include('allauth.urls')),
]

REGISTRATION_OPEN = True

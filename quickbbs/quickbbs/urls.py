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
from django.conf.urls import include, url
from django.contrib import admin
from django.views.generic import RedirectView
import frontend
import frontend.views
import frontend.serve_up
from django.conf import settings
from django.conf.urls import include, url

urlpatterns = []
# if settings.DEBUG_TOOLBAR:
#     import debug_toolbar
#     urlpatterns += [
#         url(r'^__debug__/', include(debug_toolbar.urls)),
#     ]

urlpatterns += [
    url(r'^(?i)admin/', admin.site.urls),
    url(r'^(?i)download/(?P<d_uuid>.+)/',
        frontend.views.new_download,
        name="downloads"),
    url(r'^(?i)albums/', frontend.views.new_viewgallery),
    url(r'^(?i)thumbnails/(?P<t_url_name>.+)',
        frontend.views.thumbnails,
        name="raw thumbnails"),
    url(r'^(?i)resources/', frontend.serve_up.resources),
    url(r'^accounts/', include('allauth.urls')),
    url(r'^$', RedirectView.as_view(url="/albums")),
]

#urlpatterns += [url(r'^silk/', include('silk.urls', namespace='silk'))]

REGISTRATION_OPEN = True

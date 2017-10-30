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
#import django.contrib.auth.views
import frontend, frontend.views

urlpatterns = [
    url(r'^admin/', admin.site.urls),
    url(r'^(?i)albums/', frontend.views.viewgallery),
    url(r'^thumbnails/(?P<T_Url_Name>.+)/', frontend.views.thumbnails, name="raw thumbnails"),
    url(r'^(?i)resources/', frontend.views.resources),
    url(r'^accounts/', include('allauth.urls')),
    url(r'^$', RedirectView.as_view(url="/albums")),
]

REGISTRATION_OPEN = True

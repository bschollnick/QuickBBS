#from __future__ import absolute_import  # Python 2 only
from jinja2 import Environment
#from django.contrib.staticfiles.storage import staticfiles_storage
from django_icons.templatetags.icons import icon_tag
from django.templatetags.static import static
from django.urls import reverse

def environment(**options):
    env = Environment(**options)
    env.globals.update({
       'static': static,
       'url': reverse,
       'icon':icon_tag,
    })
    return env

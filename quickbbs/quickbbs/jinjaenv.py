from django.templatetags.static import static
from django.urls import reverse
from django_icons.templatetags.icons import icon_tag
from jinja2 import Environment


def environment(**options):
    env = Environment(**options)
    env.globals.update({
       'static': static,
       'url': reverse,
       'icon':icon_tag,
    })
    return env

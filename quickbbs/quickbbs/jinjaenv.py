from django.templatetags.static import static
from django.urls import reverse
from django_icons.templatetags.icons import icon_tag
from jinja2 import Environment
from django_unicorn.templatetags.unicorn import unicorn_scripts, unicorn

def environment(**options):
    env = Environment(**options)
    env.globals.update({
        'static': static,
        'url': reverse,
        'icon':icon_tag,
        'unicorn':unicorn,
        'unicorn_scripts':unicorn_scripts,
    })
    return env

"""
Jinja2 environmental setup for Django

TBD: This has changed in later version of Django-jinja

See https://niwi.nz/django-jinja/latest/#_installation

The majority of this can be handled in quickbbs/settings.py
"""
from django.templatetags.static import static
from django.urls import reverse
from django_icons.templatetags.icons import icon_tag
from jinja2 import Environment
from django_unicorn.templatetags.unicorn import unicorn_scripts, unicorn
from django.conf import settings


def environment(**options):
    env = Environment(**options)
    env.globals.update({
        'static': static,
        'url': reverse,
        'icon': icon_tag,
        'unicorn': unicorn,
        'unicorn_scripts': unicorn_scripts,
        'bulma_uri': settings.BULMA_URI,
        'fontawesome_uri': settings.FONTAWESOME_URI,
        'jquery_uri': settings.JQUERY_URI,
    })
    return env

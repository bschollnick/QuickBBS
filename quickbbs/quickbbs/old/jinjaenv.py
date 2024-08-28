"""
Jinja2 environmental setup for Django

TBD: This has changed in later version of Django-jinja

See https://niwi.nz/django-jinja/latest/#_installation

The majority of this can be handled in quickbbs/settings.py
"""

from django.conf import settings
from django.templatetags.static import static
from django.urls import reverse
from django_icons.templatetags.icons import icon_tag
# from django_unicorn.templatetags.unicorn import unicorn_scripts, unicorn
from jinja2 import Environment


def environment(**options):
    """
    The environment function is used to create a Jinja2 environment for rendering
    templates. It sets up the global context with some basic variables that all templates
    need, like `static` and `url`. It also takes care of loading the settings file.

    :param **options: Pass in the settings of the application
    :return: The environment object
    :doc-author: Trelent
    """
    env = Environment(**options)
    env.globals.update(
        {
            #        'static': static,
            #        'url': reverse,
            # 'icon': icon_tag,
            # 'unicorn': unicorn,
            # 'unicorn_scripts': unicorn_scripts,
            #       'bulma_uri': settings.BULMA_URI,
            "fontawesome_uri": settings.FONTAWESOME_URI,
            "jquery_uri": settings.JQUERY_URI,
        }
    )
    return env

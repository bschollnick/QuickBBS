import logging
import os

from .settings import BASE_DIR, DEBUG
import quickbbs.settings as settings

# https://github.com/metakermit/fail-nicely-django
#
# Usage in other modules:
#
#     from djangoproject.logger import log
#     log.info('some output')
#
# Note, doing this manually in other modules results in nicer output:
#
#     import logging
#     log = logging.getLogger(__name__)
#     log.info('some output')

# the basic logger other apps can import
log = logging.getLogger(__name__)

# the minimum reported level
if DEBUG:
    min_level = "DEBUG"
else:
    min_level = "INFO"

# the minimum reported level for Django's modules
# optionally set to DEBUG to see database queries etc.
# or set to min_level to control it using the DEBUG flag
min_django_level = "INFO"
settings.LOGGING_CONFIG = None
# logging dictConfig configuration
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,  # keep Django's default loggers
    "formatters": {
        # see full list of attributes here:
        # https://docs.python.org/3/library/logging.html#logrecord-attributes
        "verbose": {"format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s"},
        "simple": {"format": "%(levelname)s %(message)s"},
        "timestampthread": {
            "format": "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] [%(name)-20.20s]  %(message)s",
        },
    },
    "handlers": {
        "logfile": {
            # optionally raise to INFO to not fill the log file too quickly
            "level": min_level,  # this level or higher goes to the log file
            "class": "logging.handlers.RotatingFileHandler",
            # IMPORTANT: replace with your desired logfile name!
            "filename": os.path.join(BASE_DIR, "quickbbs.log"),
            "maxBytes": 50 * 10**6,  # will 50 MB do?
            "backupCount": 3,  # keep this many extra historical files
            "formatter": "timestampthread",
        },
        "console": {
            #            'level': min_level, # this level or higher goes to the console
            "level": min_level,  # this level or higher goes to the console
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django": {  # configure all of Django's loggers
            "handlers": ["logfile", "console"],
            "level": min_django_level,  # this level or higher goes to the console
            "propagate": False,  # don't propagate further, to avoid duplication
        },
        # root configuration – for all of our own apps
        # (feel free to do separate treatment for e.g. brokenapp vs. sth else)
        "": {
            "handlers": ["logfile", "console"],
            "level": min_level,  # this level or higher goes to the console,
        },
    },
}

logging.config.dictConfig(LOGGING)
logger = logging.getLogger()
logging.getLogger("PIL.PngImagePlugin").setLevel(logging.CRITICAL + 1)
logging.getLogger("PIL.TiffImagePlugin").setLevel(logging.CRITICAL + 1)
logging.getLogger("fsevents").setLevel(logging.CRITICAL + 1)
logger.info(msg="Logging installed")

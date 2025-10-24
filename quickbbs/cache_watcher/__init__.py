""" """

import logging
import signal

logger = logging.getLogger()
from cache_watcher.watchdogmon import watchdog

#
#   Bootstrap by loading the configuration path data
#
__version__ = "3.80"

__author__ = "Benjamin Schollnick"
__email__ = "Benjamin@schollnick.net"

__url__ = "https://github.com/bschollnick/quickbbs"
__license__ = ""

signal.signal(signal.SIGINT, watchdog.shutdown)

""" """

import logging
import signal

logger = logging.getLogger()
from cache_watcher.watchdogmon import watchdog

#
#   Bootstrap by loading the configuration path data
#
signal.signal(signal.SIGINT, watchdog.shutdown)

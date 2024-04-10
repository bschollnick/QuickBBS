"""

"""

import signal
import sys
import logging

logger = logging.getLogger()
logger.info(",".join(sys.argv))
# if "runserver" in sys.argv or "--host" in sys.argv:
from cache_watcher.watchdogmon import watchdog

#
#   Bootstrap by loading the configuration path data
#
signal.signal(signal.SIGINT, watchdog.shutdown)

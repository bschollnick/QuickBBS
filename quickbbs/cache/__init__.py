import signal
import sys
from cache.watchdogmon import watchdog

#
#   Boot strap by loading the configuration path data
#


signal.signal(signal.SIGINT, watchdogmon.watchdog.shutdown)

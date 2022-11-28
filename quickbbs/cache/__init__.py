import signal
import sys


if 'runserver' in sys.argv or "--host" in sys.argv:
    from cache.watchdogmon import watchdog
#
#   Boot strap by loading the configuration path data
#
    signal.signal(signal.SIGINT, watchdogmon.watchdog.shutdown)

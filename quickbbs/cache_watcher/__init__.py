"""Filesystem watchdog that invalidates gallery directory caches when directories change on disk."""

import signal

from cache_watcher.watchdogmon import watchdog

__version__ = "4.1"

__author__ = "Benjamin Schollnick"
__email__ = "Benjamin@schollnick.net"

__url__ = "https://github.com/bschollnick/quickbbs"
__license__ = ""

signal.signal(signal.SIGINT, watchdog.shutdown)

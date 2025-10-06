import logging
import os
import sys
import time

import django

# sys.path.append('/Volumes/C-8TB/Gallery/quickbbs/quickbbs/quickbbs')

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")
django.setup()


# from watchdog.events import FileSystemEventHandler
# from watchdog.observers import Observer
from cache_watcher.django_watchdog import watchdog_manager
from django.conf import settings

logger = logging.getLogger()

__version__ = "1.5"

__author__ = "Benjamin Schollnick"
__email__ = "Benjamin@schollnick.net"

__url__ = "https://github.com/bschollnick/bschollnick"
__license__ = ""


if __name__ == "__main__":
    watchdog_manager.register(
        "albums",
        os.path.join(settings.ALBUMS_PATH, "albums"),
        restart_times=[
            "00:00",
            "1:00",
            "2:00",
            "3:00",
            "4:00",
            "5:00",
            "6:00",
            "7:00",
            "8:00",
            "9:00",
            "10:00",
            "11:00",
            "12:00",
            "13:00",
            "14:00",
            "15:00",
            "16:00",
            "17:00",
            "18:00",
            "19:00",
            "20:00",
            "21:00",
            "22:00",
            "23:00",
        ],  # Restart at midnight and noon
    )
    watchdog_manager.start_all()
    while True:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received, shutting down watchdog manager.")
            watchdog_manager.shutdown()
            sys.exit(0)

# if __name__ == "__main__":
#     import time
#     path = "../../albums"  # Replace with the directory you want to monitor
#     event_handler = TestEventHandlers()
#     observer = Observer()
#     observer.schedule(event_handler, path, recursive=True)
#     observer.start()

#     try:
#         while True:
#             time.sleep(1)
#     except KeyboardInterrupt:
#         observer.stop()
#     observer.join()

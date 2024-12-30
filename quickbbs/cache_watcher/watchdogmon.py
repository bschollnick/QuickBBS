import logging
import os
import sys

from watchdog.events import FileSystemEventHandler  # , PatternMatchingEventHandler
from watchdog.observers import Observer

logger = logging.getLogger()

# from watchdog.events import LoggingEventHandler

__version__ = "1.5"

__author__ = "Benjamin Schollnick"
__email__ = "Benjamin@schollnick.net"

__url__ = "https://github.com/bschollnick/bschollnick"
__license__ = ""


class TestEventHandlers(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            print(f"hey, {event.src_path} has been created!")

    def on_deleted(self, event):
        if event.is_directory:
            print(f"what the f**k! Someone deleted {event.src_path}!")

    def on_modified(self, event):
        if event.is_directory:
            print(f"hey buddy, {event.src_path} has been modified")
            print(event)

    def on_moved(self, event):
        if event.is_directory:
            print(f"ok ok ok, someone moved {event.src_path} to {event.dest_path}")


class watchdog_monitor:
    def __init__(self):
        # logger.info(f"watchdog monitor init")
        pass

    #        self.my_event_handler = None
    #        self.my_observer = Observer()

    def on_event(self, event):
        pass

    def startup(self, monitor_path, event_handler=None):
        logger.info(f"Monitoring : {monitor_path}")
        #        patterns = ["*"]
        ignore_patterns = None
        ignore_directories = False
        case_sensitive = False
        self.my_event_handler = event_handler
        # self.my_event_handler = PatternMatchingEventHandler(
        #     patterns, ignore_patterns, ignore_directories, case_sensitive
        # )

        go_recursively = True
        self.my_observer = Observer()
        self.my_observer.schedule(
            self.my_event_handler, monitor_path, recursive=go_recursively
        )
        self.my_observer.start()

    def shutdown(self, *args):
        if os.environ.get("RUN_MAIN") == "true":
            logger.info("Shutting down")
            self.my_observer.stop()
            self.my_observer.join()
        #    signal.send('system')
        sys.exit(0)  # So runserver does try to exit


watchdog = watchdog_monitor()

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

import signal
import time
import os
import sys

from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

__version__ = '1.5'

__author__ = 'Benjamin Schollnick'
__email__ = 'Benjamin@schollnick.net'

__url__ = 'https://github.com/bschollnick/bschollnick'
__license__ = ''


def on_created(event):
    if event.is_directory:
        print(f"hey, {event.src_path} has been created!")


def on_deleted(event):
    if event.is_directory:
        print(f"what the f**k! Someone deleted {event.src_path}!")


def on_modified(event):
    if event.is_directory:
        print(f"hey buddy, {event.src_path} has been modified")
        print(event)


def on_moved(event):
    if event.is_directory:
        print(f"ok ok ok, someone moved {event.src_path} to {event.dest_path}")


class watchdog_monitor():
    def __init__(self):
        self.my_observer = Observer()
        self.my_event_handler = None

    def on_event(self, event):
        pass

    def startup(self, monitor_path, created=None,
                deleted=None, modified=None,
                moved=None):
        print("Monitoring :", monitor_path)
        patterns = ["*"]
        ignore_patterns = None
        ignore_directories = False
        case_sensitive = False
        self.my_event_handler = PatternMatchingEventHandler(patterns, ignore_patterns,
                                                            ignore_directories,
                                                            case_sensitive)

        self.my_event_handler.on_created = created
        self.my_event_handler.on_deleted = deleted
        self.my_event_handler.on_modified = modified
        self.my_event_handler.on_moved = moved

        go_recursively = True
        self.my_observer = Observer()
        self.my_observer.schedule(self.my_event_handler,
                                  monitor_path,
                                  recursive=go_recursively)

        self.my_observer.start()

    def shutdown(self, *args):
        if os.environ.get('RUN_MAIN') == 'true':
            print("Shutting down")
            self.my_observer.stop()
            self.my_observer.join()
        #    signal.send('system')
        sys.exit(0)  # So runserver does try to exit


watchdog = watchdog_monitor()

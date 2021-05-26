import sys
import os
import os.path
import frontend.config as config
import signal
import time
from frontend.watchdogmon import watchdog
#from frontend.utilities import delete_from_cache_tracking
#
#   Boot strap by loading the configuration path data
#
__version__ = '1.5'

__author__ = 'Benjamin Schollnick'
__email__ = 'Benjamin@schollnick.net'

__url__ = 'https://github.com/bschollnick/bschollnick'
__license__ = ''

here = os.path.dirname(__file__)
cfg_path = os.path.abspath(os.path.join(here, r"../../cfg"))
config.load_data(os.path.join(cfg_path, "paths.ini"))
config.load_data(os.path.join(cfg_path, "settings.ini"))
config.load_data(os.path.join(cfg_path, "filetypes.ini"))

signal.signal(signal.SIGINT, watchdogmon.watchdog.shutdown)
#if os.environ.get('RUN_MAIN'):
#    watchdog.startup(monitor_path=os.path.join(config.configdata["locations"]["albums_path"],
#                                           "albums"), created=watchdogmon.on_created,
#                                           deleted=watchdogmon.on_deleted,
#                                           modified=watchdogmon.on_modified,
#                                           moved=watchdogmon.on_moved)
#import sys

# def on_created(event):
#     print(f"hey, {event.src_path} has been created!")
#
# def on_deleted(event):
#     print(f"what the f**k! Someone deleted {event.src_path}!")
#
# def on_modified(event):
#     print(f"hey buddy, {event.src_path} has been modified")
#
# def on_moved(event):
#     print(f"ok ok ok, someone moved {event.src_path} to {event.dest_path}")
#
# if __name__ == "__main__":
#     patterns = ["*"]
#     ignore_patterns = None
#     ignore_directories = False
#     case_sensitive = True
#     my_event_handler = PatternMatchingEventHandler(patterns, ignore_patterns, ignore_directories, case_sensitive)
#
#     my_event_handler.on_created = on_created
#     my_event_handler.on_deleted = on_deleted
#     my_event_handler.on_modified = on_modified
#     my_event_handler.on_moved = on_moved
#
#     path = sys.argv[1]#"."
#     go_recursively = True
#     my_observer = Observer()
#     my_observer.schedule(my_event_handler, path, recursive=go_recursively)
#
#     my_observer.start()
#     try:
#         while True:
#             time.sleep(1)
#     except KeyboardInterrupt:
#         my_observer.stop()
#         my_observer.join()

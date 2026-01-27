"""Watchdog filesystem monitoring module for QuickBBS cache invalidation.

Example:
    from cache_watcher.watchdogmon import watchdog
    from cache_watcher.models import CacheFileMonitorEventHandler

    # Create event handler
    event_handler = CacheFileMonitorEventHandler()

    # Start monitoring
    watchdog.startup("/path/to/albums", event_handler)

    # Stop monitoring
    watchdog.shutdown()
"""

import logging
import os
import sys

from watchdog.observers import Observer

logger = logging.getLogger()

__version__ = "1.5"

__author__ = "Benjamin Schollnick"
__email__ = "Benjamin@schollnick.net"

__url__ = "https://github.com/bschollnick/bschollnick"
__license__ = ""


# class TestEventHandlers(FileSystemEventHandler):
#     """
#     Test Event Handler to allow visible queues for testing the Watchdog code.
#     """

#     def on_created(self, event):
#         if event.is_directory:
#             print(f"hey, {event.src_path} has been created!")

#     def on_deleted(self, event):
#         if event.is_directory:
#             print(f"what the f**k! Someone deleted {event.src_path}!")

#     def on_modified(self, event):
#         if event.is_directory:
#             print(f"hey buddy, {event.src_path} has been modified")
#             print(event)

#     def on_moved(self, event):
#         if event.is_directory:
#             print(f"ok ok ok, someone moved {event.src_path} to {event.dest_path}")


class WatchdogMonitor:
    """
    Class to monitor a directory for changes, and to call the appropriate event handler.
    In this case (QuickBBS's usage) is to monitor the albums directories and all children directories and
    files for changes.

    If any change to a file or directory is detected, that directory is marked as "dirty" and when accessed
    a rescan is performed.
    """

    __slots__ = ("my_observer", "my_event_handler", "current_watch")

    def __init__(self) -> None:
        """Initialize the watchdog monitor."""
        self.my_observer = None
        self.my_event_handler = None
        self.current_watch = None

    def on_event(self, event) -> None:
        """Handle filesystem events.

        Args:
            event: Filesystem event to process
        """

    def startup(self, monitor_path: str, event_handler=None, force_recreate: bool = False) -> None:
        """
        Start the watchdog observer to monitor filesystem changes.

        :param monitor_path: Path to monitor for filesystem changes
        :param event_handler: Event handler to process filesystem events
        :param force_recreate: If True, stop and recreate the observer (prevents memory leaks)
        :return: None
        """
        logger.info("Monitoring : %s", monitor_path)

        # If force_recreate is True, stop and recreate the observer
        # This prevents memory leaks from accumulated internal state
        if force_recreate and self.my_observer is not None:
            logger.debug("Force recreate requested - stopping existing observer")
            self.stop_observer()

        # If observer already exists, unschedule old handler first
        if self.my_observer is not None and self.current_watch is not None:
            logger.debug("Unscheduling existing event handler")
            self.my_observer.unschedule(self.current_watch)
            self.current_watch = None

        self.my_event_handler = event_handler
        go_recursively = True

        # Create observer if it doesn't exist OR if we just stopped it
        if self.my_observer is None:
            logger.debug("Creating new Observer instance")
            self.my_observer = Observer()
            self.my_observer.start()

        # Schedule the new handler
        self.current_watch = self.my_observer.schedule(self.my_event_handler, monitor_path, recursive=go_recursively)

    def stop_observer(self) -> None:
        """
        Stop the watchdog observer without exiting the process.
        Use this for restarts or cleanup that should not terminate the application.

        :return: None
        """
        if self.my_observer is not None:
            logger.debug("Stopping observer")
            try:
                # Unschedule current watch before stopping
                if self.current_watch is not None:
                    self.my_observer.unschedule(self.current_watch)
                    self.current_watch = None

                # Stop the observer's internal threads
                self.my_observer.stop()
                # Wait for threads to complete (with timeout to prevent hanging)
                self.my_observer.join(timeout=5.0)

                # Check if join timed out
                if self.my_observer.is_alive():
                    logger.warning("Observer threads did not stop within timeout")

                # Clear the observer reference to allow garbage collection
                self.my_observer = None
                self.my_event_handler = None
                logger.debug("Observer stopped and cleaned up")

            except Exception as e:
                logger.error("Error stopping observer: %s", e, exc_info=True)
                # Still clear references even if stop failed
                self.my_observer = None
                self.my_event_handler = None
                self.current_watch = None

    def shutdown(self, *args) -> None:
        """
        Shutdown the watchdog observer and exit the process.
        Use this for full application shutdown.

        :param args: Variable arguments for shutdown handling
        :return: None
        """
        if os.environ.get("RUN_MAIN") == "true":
            logger.info("Shutting down")
            self.stop_observer()
        sys.exit(0)  # So runserver does try to exit


watchdog = WatchdogMonitor()

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

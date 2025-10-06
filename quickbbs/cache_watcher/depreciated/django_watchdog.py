# django_watchdog.py
import atexit
import logging
import os
import os.path
import signal
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import models
from django.utils import timezone
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


# Simple file-based coordination (no Redis needed)
class FileCoordinator:
    """File-based process coordination"""

    def __init__(self, name):
        self.name = name
        self.lock_dir = Path(settings.BASE_DIR) / "tmp" / "watchdog_locks"
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.lock_dir / f"{name}.lock"
        self.process_id = f"{os.getpid()}_{threading.current_thread().ident}"

    def acquire_master(self):
        """Try to become the master process"""
        try:
            if self.lock_file.exists():
                # Check if existing process is still alive
                with open(self.lock_file, "r") as f:
                    existing_pid = f.read().strip().split("_")[0]

                try:
                    # Check if process exists (Unix-like systems)
                    os.kill(int(existing_pid), 0)
                    return False  # Process still exists
                except (OSError, ProcessLookupError, ValueError):
                    # Process doesn't exist, remove stale lock
                    self.lock_file.unlink(missing_ok=True)

            # Create lock file
            with open(self.lock_file, "w") as f:
                f.write(self.process_id)

            return True

        except Exception as e:
            logger.error(f"Failed to acquire master lock: {e}")
            return False

    def release_master(self):
        """Release master status"""
        try:
            if self.lock_file.exists():
                with open(self.lock_file, "r") as f:
                    current_master = f.read().strip()

                if current_master == self.process_id:
                    self.lock_file.unlink()

        except Exception as e:
            logger.error(f"Failed to release master lock: {e}")

    def is_master(self):
        """Check if this process is the master"""
        try:
            if not self.lock_file.exists():
                return False

            with open(self.lock_file, "r") as f:
                master_id = f.read().strip()

            return master_id == self.process_id

        except Exception as e:
            logger.error(f"Failed to check master status: {e}")
            return False


class ScheduledRestartThread:
    """Pure Python scheduling thread"""

    def __init__(self, callback, restart_times):
        self.callback = callback
        self.restart_times = restart_times  # List of "HH:MM" strings
        self.running = False
        self.thread = None
        self._stop_event = threading.Event()

    def start(self):
        """Start the scheduling thread"""
        if self.running:
            return

        self.running = True
        self._stop_event.clear()
        self.thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.thread.start()
        logger.info(f"Scheduler started for times: {self.restart_times}")

    def stop(self):
        """Stop the scheduling thread"""
        self.running = False
        self._stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)

    def _scheduler_loop(self):
        """Main scheduler loop"""
        while self.running and not self._stop_event.is_set():
            try:
                now = datetime.now()
                next_restart = self._get_next_restart_time(now)

                if next_restart:
                    sleep_seconds = (next_restart - now).total_seconds()

                    if sleep_seconds <= 60:  # Within 1 minute
                        logger.info(f"Executing scheduled restart at {next_restart}")
                        self.callback()
                        # Sleep past the minute to avoid duplicate execution
                        self._stop_event.wait(70)
                    else:
                        # Check every minute
                        self._stop_event.wait(60)
                else:
                    # No restart times configured, sleep longer
                    self._stop_event.wait(300)

            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                self._stop_event.wait(60)

    def _get_next_restart_time(self, now):
        """Calculate next restart time"""
        if not self.restart_times:
            return None

        today = now.date()
        restart_datetimes = []

        for time_str in self.restart_times:
            try:
                hour, minute = map(int, time_str.split(":"))
                restart_time = datetime.combine(today, datetime.min.time().replace(hour=hour, minute=minute))

                # If time has passed today, schedule for tomorrow
                if restart_time <= now:
                    restart_time += timedelta(days=1)

                restart_datetimes.append(restart_time)

            except ValueError:
                logger.error(f"Invalid restart time format: {time_str}")

        return min(restart_datetimes) if restart_datetimes else None


class DjangoFileHandler(FileSystemEventHandler):
    """Django-aware file system event handler"""

    def __init__(self, name="default"):
        super().__init__()
        self.name = name
        self.event_count = 0
        self.last_event_time = None

    def on_any_event(self, event):
        """Handle any file system event"""
        if event.is_directory:
            dirpath = os.path.normpath(event.src_path)
        else:
            dirpath = str(Path(os.path.normpath(event.src_path)).parent)
        print(dirpath)
        self._log_event(event.event_type, dirpath)
        # Uncomment these methods if you want to handle specific events
        # self.on_modified(event)
        # self.on_created(event)
        # self.on_deleted(event)

    # Uncomment these methods if you want to handle specific events
    # def on_modified(self, event):
    #     if not event.is_directory:
    #         self._log_event("modified", event.src_path)

    # def on_created(self, event):
    #     if not event.is_directory:
    #         self._log_event("created", event.src_path)

    # def on_deleted(self, event):
    #     if not event.is_directory:
    #         self._log_event("deleted", event.src_path)

    def _log_event(self, event_type, path):
        """Log events and track statistics"""
        self.event_count += 1
        self.last_event_time = timezone.now()
        logger.info(f"[{self.name}] File {event_type}: {path}")


class DjangoWatchdog:
    """Pure Python/Django watchdog with scheduled restarts"""

    _instances = {}
    _lock = threading.Lock()

    def __init__(self, name, watch_path, restart_times=None):
        self.name = name
        self.watch_path = Path(watch_path)
        self.restart_times = restart_times or []
        self.observer = None
        self.handler = DjangoFileHandler(name)
        self.coordinator = FileCoordinator(name)
        self.scheduler = None
        self.running = False

        # Register cleanup on exit
        atexit.register(self.cleanup)

    @classmethod
    def get_instance(cls, name, watch_path, restart_times=None):
        """Singleton pattern per process"""
        with cls._lock:
            if name not in cls._instances:
                cls._instances[name] = cls(name, watch_path, restart_times)
            return cls._instances[name]

    def start_observer(self):
        """Start observer if this process can become master"""
        if not self.coordinator.acquire_master():
            logger.info(f"[{self.name}] Another process is already master")
            return False

        if self.running:
            logger.warning(f"[{self.name}] Observer already running")
            return True

        try:
            # Ensure watch path exists
            if not self.watch_path.exists():
                logger.warning(f"[{self.name}] Watch path doesn't exist: {self.watch_path}")
                self.watch_path.mkdir(parents=True, exist_ok=True)

            # Start observer
            self.observer = Observer()
            self.observer.schedule(self.handler, str(self.watch_path), recursive=True)
            self.observer.start()
            self.running = True

            # Start scheduler if restart times are configured
            if self.restart_times:
                self.scheduler = ScheduledRestartThread(self.restart_observer, self.restart_times)
                self.scheduler.start()

            # Start heartbeat thread to maintain master status
            self._start_heartbeat()

            logger.info(f"[{self.name}] Started monitoring: {self.watch_path}")
            return True

        except Exception as e:
            logger.error(f"[{self.name}] Failed to start observer: {e}")
            self.coordinator.release_master()
            return False

    def stop_observer(self):
        """Stop the observer and cleanup"""
        logger.info(f"[{self.name}] Stopping observer...")
        self.running = False

        # Stop scheduler first
        if self.scheduler:
            logger.info(f"[{self.name}] Stopping scheduler...")
            self.scheduler.stop()
            self.scheduler = None

        # Stop observer with proper timeout handling
        if self.observer:
            if self.observer.is_alive():
                logger.info(f"[{self.name}] Stopping watchdog observer...")
                self.observer.stop()

                # Give it time to stop gracefully
                self.observer.join(timeout=3)

                # Force stop if still alive
                if self.observer.is_alive():
                    logger.warning(f"[{self.name}] Observer didn't stop gracefully, forcing...")
                    try:
                        self.observer.stop()
                        time.sleep(0.5)
                    except:
                        pass

            self.observer = None

        # Release master status
        self.coordinator.release_master()
        logger.info(f"[{self.name}] Stopped monitoring")

    def restart_observer(self):
        """Restart the observer"""
        if not self.coordinator.is_master():
            logger.warning(f"[{self.name}] Cannot restart - not master process")
            return False

        logger.info(f"[{self.name}] Restarting observer...")

        # Stop observer but keep master status
        if self.observer and self.observer.is_alive():
            self.observer.stop()
            self.observer.join(timeout=5)

        # Brief pause
        time.sleep(1)

        # Restart observer
        try:
            self.observer = Observer()
            self.observer.schedule(self.handler, str(self.watch_path), recursive=True)
            self.observer.start()

            logger.info(f"[{self.name}] Observer restarted successfully")
            return True

        except Exception as e:
            logger.error(f"[{self.name}] Failed to restart observer: {e}")
            return False

    def get_status(self):
        """Get current status information"""
        return {
            "name": self.name,
            "watch_path": str(self.watch_path),
            "is_running": self.running and (self.observer and self.observer.is_alive()),
            "is_master": self.coordinator.is_master(),
            "process_id": self.coordinator.process_id,
            "restart_times": self.restart_times,
            "event_count": self.handler.event_count,
            "last_event": (self.handler.last_event_time.isoformat() if self.handler.last_event_time else None),
        }

    def _start_heartbeat(self):
        """Start heartbeat thread to maintain master status"""

        def heartbeat():
            while self.running:
                try:
                    # Check if we should still be running
                    if not self.running:
                        break

                    # Refresh master status every 30 seconds
                    if not self.coordinator.is_master():
                        logger.warning(f"[{self.name}] Lost master status, stopping observer")
                        self.stop_observer()
                        break

                    # Update lock file timestamp
                    if self.coordinator.lock_file.exists():
                        self.coordinator.lock_file.touch()

                    # Use smaller sleep intervals to respond faster to shutdown
                    for _ in range(30):  # 30 seconds total, but check every second
                        if not self.running:
                            break
                        time.sleep(1)

                except Exception as e:
                    logger.error(f"[{self.name}] Heartbeat error: {e}")
                    if self.running:  # Only sleep if still supposed to be running
                        time.sleep(5)

            logger.info(f"[{self.name}] Heartbeat thread stopping")

        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()

    def cleanup(self):
        """Cleanup resources"""
        if hasattr(self, "_cleanup_done"):
            return  # Prevent multiple cleanup calls

        self._cleanup_done = True
        logger.info(f"[{self.name}] Starting cleanup...")

        try:
            self.stop_observer()
            logger.info(f"[{self.name}] Cleanup completed")
        except Exception as e:
            logger.error(f"[{self.name}] Error during cleanup: {e}")


# class Command(BaseCommand):
#     """Django management command to run watchdog

#     Usage: python manage.py run_watchdog --name=my_watchdog --path=/path/to/watch --restart-times=00:00,12:00
#     """
#     help = 'Run file system watchdog with scheduled restarts'

#     def add_arguments(self, parser):
#         parser.add_argument('--name', type=str, default='default', help='Watchdog name')
#         parser.add_argument('--path', type=str, required=True, help='Path to watch')
#         parser.add_argument('--restart-times', type=str, help='Comma-separated times for restart (HH:MM format)')
#         parser.add_argument('--check-interval', type=int, default=10, help='Health check interval in seconds')

#     def handle(self, *args, **options):
#         name = options['name']
#         watch_path = options['path']
#         check_interval = options['check_interval']
#         restart_times = []

#         if options['restart_times']:
#             restart_times = [t.strip() for t in options['restart_times'].split(',')]
#             # Validate time format
#             for time_str in restart_times:
#                 try:
#                     hour, minute = map(int, time_str.split(':'))
#                     if not (0 <= hour <= 23 and 0 <= minute <= 59):
#                         raise ValueError()
#                 except ValueError:
#                     self.stdout.write(
#                         self.style.ERROR(f'Invalid time format: {time_str}. Use HH:MM format.')
#                     )
#                     return

#         watchdog = DjangoWatchdog.get_instance(name, watch_path, restart_times)

#         try:
#             success = watchdog.start_observer()
#             if not success:
#                 self.stdout.write(
#                     self.style.ERROR(f'Failed to start watchdog "{name}"')
#                 )
#                 return

#             self.stdout.write(
#                 self.style.SUCCESS(f'Watchdog "{name}" started successfully')
#             )

#             if restart_times:
#                 self.stdout.write(f'Scheduled restarts at: {", ".join(restart_times)}')

#             self.stdout.write('Press Ctrl+C to stop...')

#             # Main monitoring loop with better exception handling
#             try:
#                 while True:
#                     time.sleep(check_interval)

#                     status = watchdog.get_status()
#                     if not status['is_running']:
#                         self.stdout.write(
#                             self.style.WARNING('Observer stopped, attempting restart...')
#                         )
#                         if not watchdog.start_observer():
#                             self.stdout.write(
#                                 self.style.ERROR('Failed to restart observer')
#                             )
#                             break

#                     # Optional: Print status
#                     if options['verbosity'] >= 2:
#                         self.stdout.write(f'Status: {status}')

#             except KeyboardInterrupt:
#                 self.stdout.write('\nReceived interrupt signal, shutting down...')

#         except KeyboardInterrupt:
#             self.stdout.write('\nReceived interrupt signal during startup...')
#         except Exception as e:
#             self.stdout.write(
#                 self.style.ERROR(f'Error: {e}')
#             )
#         finally:
#             self.stdout.write('Cleaning up...')
#             try:
#                 watchdog.cleanup()
#                 self.stdout.write('Cleanup completed.')
#             except Exception as cleanup_error:
#                 self.stdout.write(
#                     self.style.ERROR(f'Cleanup error: {cleanup_error}')
#                 )


# Django App Integration Helper
class WatchdogManager:
    """Helper class for managing multiple watchdogs in Django apps"""

    def __init__(self):
        self.watchdogs = {}

    def register(self, name, path, restart_times=None):
        """Register a watchdog configuration"""
        watchdog = DjangoWatchdog.get_instance(name, path, restart_times)
        self.watchdogs[name] = watchdog
        return watchdog

    def start_all(self):
        """Start all registered watchdogs"""
        results = {}
        for name, watchdog in self.watchdogs.items():
            results[name] = watchdog.start_observer()
        return results

    def stop_all(self):
        """Stop all registered watchdogs"""
        for watchdog in self.watchdogs.values():
            watchdog.stop_observer()

    def get_status_all(self):
        """Get status for all watchdogs"""
        return {name: wd.get_status() for name, wd in self.watchdogs.items()}


# Global manager instance
watchdog_manager = WatchdogManager()

# # Usage in Django apps.py:
# """
# from django.apps import AppConfig
# import sys

# class YourAppConfig(AppConfig):
#     default_auto_field = 'django.db.models.BigAutoField'
#     name = 'your_app'

#     def ready(self):
#         # Only start in runserver/production, not during migrations
#         if any(cmd in sys.argv for cmd in ['runserver', 'gunicorn']):
#             from .django_watchdog import watchdog_manager

#             # Register watchdogs
#             watchdog_manager.register(
#                 'media_files',
#                 '/path/to/media',
#                 restart_times=['00:00', '12:00']  # Restart at midnight and noon
#             )

#             watchdog_manager.register(
#                 'static_files',
#                 '/path/to/static',
#                 restart_times=['06:00']  # Restart at 6 AM
#             )

#             # Start all watchdogs
#             watchdog_manager.start_all()
# """

# # Simple Django views for monitoring (optional)
# from django.http import JsonResponse
# from django.views.decorators.http import require_http_methods

# @require_http_methods(["GET"])
# def watchdog_status_view(request):
#     """Simple status endpoint"""
#     try:
#         status = watchdog_manager.get_status_all()
#         return JsonResponse({'watchdogs': status})
#     except Exception as e:
#         return JsonResponse({'error': str(e)}, status=500)

# @require_http_methods(["POST"])
# def restart_watchdog_view(request, name):
#     """Manual restart endpoint"""
#     try:
#         if name in watchdog_manager.watchdogs:
#             success = watchdog_manager.watchdogs[name].restart_observer()
#             return JsonResponse({'success': success, 'message': f'Restart {"successful" if success else "failed"}'})
#         else:
#             return JsonResponse({'error': 'Watchdog not found'}, status=404)
#     except Exception as e:
#         return JsonResponse({'error': str(e)}, status=500)

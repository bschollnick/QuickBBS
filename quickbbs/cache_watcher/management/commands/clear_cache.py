# from cache.models import Cache_Storage
from cache_watcher.models import fs_Cache_Tracking
from django.core.management.base import BaseCommand


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear_cache",
            action="store_true",
            help="Clear the Filesystem Cache",
        )

    def handle(self, *args, **options):
        # ...
        fs_Cache_Tracking.clear_all_records()

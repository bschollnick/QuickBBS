from django.core.management.base import BaseCommand

from cache.models import Cache_Storage


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('--clear_cache',
                            action='store_true',
                            help='Clear the Filesystem Cache',
                            )

    def handle(self, *args, **options):
        # ...
        Cache_Storage.clear_all_records()

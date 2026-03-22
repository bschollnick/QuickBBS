"""
Project-wide pytest configuration for QuickBBS.

This conftest.py is discovered automatically by pytest because it sits at
the root of testpaths (quickbbs/) defined in pytest.ini.  Fixtures defined
here are available to every test file in the project without importing.
"""

import signal
import pytest
from django.conf import settings
from django.core.management import call_command


def pytest_configure(config):
    # cache_watcher/__init__.py registers watchdog.shutdown as the SIGINT handler,
    # which calls sys.exit(0). Restore the default handler so pytest's own Ctrl+C
    # handling works correctly and doesn't abort mid-test-setup.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    """
    Abort immediately if the configured database name does not look like a
    test database.  This is a hard safety guard — if the Django test runner
    has not redirected connections to a test-prefixed database, we refuse to
    run rather than risk truncating production data.

    TransactionTestCase (and Django's test runner generally) issues TRUNCATE
    against every table it touches.  Running that against a production database
    is catastrophic and irreversible.
    """
    db_name = settings.DATABASES.get("default", {}).get("NAME", "")
    test_name = settings.DATABASES.get("default", {}).get("TEST", {}).get("NAME", f"test_{db_name}")

    # The database name at runtime during pytest must start with "test_".
    # If it matches the production name exactly, abort hard.
    if db_name and not db_name.startswith("test_") and db_name == db_name:
        # We can't check the *active* connection name here (Django hasn't
        # set it up yet), but we can verify the TEST key is configured.
        if not test_name.startswith("test_"):
            pytest.exit(
                f"SAFETY ABORT: Configured test database name '{test_name}' does not "
                f"start with 'test_'. Refusing to run tests to protect production data. "
                f"Set DATABASES['default']['TEST']['NAME'] to a name starting with 'test_'.",
                returncode=3,
            )


@pytest.fixture(scope="session", autouse=True)
def django_db_setup(django_db_setup, django_db_blocker):
    # The parameter name must match the base fixture it overrides.
    # pytest-django requires this so it can inject and extend the base fixture.
    # pylint: disable=redefined-outer-name
    """Ensure the filetypes table is populated once per test session.

    Also force-reloads the in-memory filetype cache. AppConfig.ready() calls
    load_filetypes() at startup against an empty test DB, caching an empty dict.
    After refresh_filetypes populates the table, load_filetypes(force=True) clears
    that stale cache so subsequent callers see the real data.
    """
    from filetypes.models import load_filetypes

    with django_db_blocker.unblock():
        call_command("refresh_filetypes")
        load_filetypes(force=True)

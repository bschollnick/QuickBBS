"""Test runner that performs the same setup a new database requires."""

from __future__ import annotations

from typing import Any

from django.core.management import call_command
from django.test.runner import DiscoverRunner

from filetypes.models import load_filetypes


class QuickBBSTestRunner(DiscoverRunner):
    """Seed the filetypes table into every freshly created test database.

    `refresh_filetypes` is a required setup step on a new database — the
    rows come from the settings extension lists, not from a migration — so
    a test database built from migrations alone has none, and any code
    reaching `filetypes.return_filetype()` raises KeyError.
    """

    def setup_databases(self, **kwargs: Any) -> list[tuple[Any, str, bool]]:
        old_config = super().setup_databases(**kwargs)
        call_command("refresh_filetypes")
        # The lookup dict is a module-level cache, and anything that read it
        # before the seed holds an empty one.
        load_filetypes(force=True)
        return old_config

"""Classify the process Django is starting in, so per-server start-up work runs once."""

from __future__ import annotations

import os
import sys
from typing import Literal

type ServerRole = Literal["not_a_server", "dev_server", "production_server"]

#: Set to "1" by the start_*.sh scripts that launch an ASGI server.
SERVER_ENVIRONMENT_VARIABLE = "QUICKBBS_SERVER"

_DEV_SERVER_COMMANDS = ("runserver", "runserver_plus")


def server_role() -> ServerRole:
    """Return the role of the current process.

    - ``"dev_server"``: the reloader child of ``manage.py runserver`` or
      ``runserver_plus``, where ``RUN_MAIN`` or ``WERKZEUG_RUN_MAIN`` is ``"true"``.
    - ``"production_server"``: a process started with ``QUICKBBS_SERVER=1`` in its
      environment, as the start scripts for granian, gunicorn, hypercorn and uvicorn
      set. Every worker gets this role, so work that must run once across workers
      needs its own election.
    - ``"not_a_server"``: everything else, including other management commands,
      the dev server's reloader parent, pytest, scripts and MCP servers.
    """
    if sys.argv[0].endswith("manage.py") and len(sys.argv) > 1:
        is_reloader_child = (os.environ.get("WERKZEUG_RUN_MAIN") or os.environ.get("RUN_MAIN")) == "true"
        return "dev_server" if sys.argv[1] in _DEV_SERVER_COMMANDS and is_reloader_child else "not_a_server"
    return "production_server" if os.environ.get(SERVER_ENVIRONMENT_VARIABLE) == "1" else "not_a_server"

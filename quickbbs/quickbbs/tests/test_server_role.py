"""`server_role()` classifies a process from its argv and the dev-server reloader variables."""

from __future__ import annotations

import pytest

from quickbbs.server_role import server_role


@pytest.mark.parametrize(
    ("argv", "environment", "expected"),
    [
        (["manage.py", "migrate"], {}, "not_a_server"),
        (["manage.py", "runserver"], {}, "not_a_server"),
        (["manage.py", "runserver"], {"RUN_MAIN": "true"}, "dev_server"),
        (["manage.py", "runserver_plus"], {"WERKZEUG_RUN_MAIN": "true"}, "dev_server"),
        (["manage.py", "migrate"], {"QUICKBBS_SERVER": "1"}, "not_a_server"),
        (["/usr/local/bin/gunicorn", "quickbbs.asgi:application"], {"QUICKBBS_SERVER": "1"}, "production_server"),
        (["/usr/local/bin/gunicorn", "quickbbs.asgi:application"], {}, "not_a_server"),
        (["/venv/lib/python3.14/site-packages/pytest/__main__.py"], {}, "not_a_server"),
        (["/venv/bin/django-ai-boost", "--settings", "quickbbs.settings"], {}, "not_a_server"),
        (["manage.py"], {}, "not_a_server"),
    ],
)
def test_server_role(monkeypatch, argv, environment, expected):
    """Each argv and environment pair maps to its role."""
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.delenv("RUN_MAIN", raising=False)
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    monkeypatch.delenv("QUICKBBS_SERVER", raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    assert server_role() == expected

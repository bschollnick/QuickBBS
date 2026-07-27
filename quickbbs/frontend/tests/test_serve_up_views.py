"""Web-layer tests for frontend/serve_up.py — static_or_resources via Django test Client."""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest
from django.test import Client, TestCase, override_settings

pytestmark = pytest.mark.web


class TestStaticOrResources(TestCase):
    """static_or_resources via /resources/<path> and /static/<path>"""

    def setUp(self) -> None:
        self.client = Client()
        self.resources_dir = tempfile.mkdtemp()
        self.static_dir = tempfile.mkdtemp()
        with open(os.path.join(self.resources_dir, "logo.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\nfake-resource-bytes")
        with open(os.path.join(self.static_dir, "admin.css"), "w", encoding="utf-8") as f:
            f.write("body { color: red; }")
        self._settings_override = override_settings(
            RESOURCES_PATH=self.resources_dir,
            STATIC_ROOT=self.static_dir,
        )
        self._settings_override.enable()

    def tearDown(self) -> None:
        self._settings_override.disable()
        shutil.rmtree(self.resources_dir, ignore_errors=True)
        shutil.rmtree(self.static_dir, ignore_errors=True)

    def test_serves_file_from_resources(self):
        """A file present under RESOURCES_PATH is served with 200."""
        response = self.client.get("/resources/logo.png", secure=True)
        assert response.status_code == 200
        assert b"".join(response.streaming_content) == b"\x89PNG\r\n\x1a\nfake-resource-bytes"

    def test_serves_file_from_static(self):
        """A file present only under STATIC_ROOT is served with 200."""
        response = self.client.get("/static/admin.css", secure=True)
        assert response.status_code == 200

    def test_unknown_file_returns_404(self):
        """A path that doesn't exist in either directory returns 404."""
        response = self.client.get("/resources/does_not_exist.png", secure=True)
        assert response.status_code == 404

    def test_path_traversal_returns_404(self):
        """A traversal attempt cannot escape RESOURCES_PATH/STATIC_ROOT."""
        response = self.client.get("/resources/../../../../etc/passwd", secure=True)
        assert response.status_code in (404, 400)

    def test_resources_shadows_static_duplicate(self):
        """When the same relative path exists in both dirs, resources/ wins."""
        with open(os.path.join(self.resources_dir, "shared.txt"), "w", encoding="utf-8") as f:
            f.write("from resources")
        with open(os.path.join(self.static_dir, "shared.txt"), "w", encoding="utf-8") as f:
            f.write("from static")
        response = self.client.get("/resources/shared.txt", secure=True)
        assert response.status_code == 200
        content = b"".join(response.streaming_content)
        assert content == b"from resources"

    def test_sets_cache_control_and_last_modified(self):
        """Response carries a public max-age Cache-Control and a Last-Modified header."""
        response = self.client.get("/resources/logo.png", secure=True)
        assert response.status_code == 200
        assert response["Cache-Control"] == "public, max-age=300"
        assert "Last-Modified" in response

    def test_conditional_get_returns_304(self):
        """A repeat request with If-Modified-Since gets a 304, not a re-transfer."""
        first = self.client.get("/resources/logo.png", secure=True)
        assert first.status_code == 200
        second = self.client.get(
            "/resources/logo.png",
            secure=True,
            HTTP_IF_MODIFIED_SINCE=first["Last-Modified"],
        )
        assert second.status_code == 304

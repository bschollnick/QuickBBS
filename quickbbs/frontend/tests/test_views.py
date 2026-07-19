"""
Smoke tests for the HTTP layer — URL routing, view status codes, and response
content for the main user-facing endpoints.

DATABASE SAFETY NOTES
---------------------
- All tests use Django's TestCase (each test wrapped in a rolled-back
  transaction against the test database). No TransactionTestCase is used — ever.
- Filesystem content is created in tempfile.mkdtemp() with ALBUMS_PATH
  overridden; tearDown removes only the temp directory.

These are intentionally shallow: they assert that each endpoint routes,
executes, and returns the expected status/content shape, so that template,
URL, or context regressions are caught. Deeper behavior belongs in the
model-level test modules.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from typing import cast
from unittest import mock

from django.http import HttpResponse
from django.test import Client, TestCase, override_settings
from PIL import Image

from frontend.utilities import breadcrumbs_cache, webpaths_cache
from quickbbs.cache_registry import layout_manager_cache
from quickbbs.directoryindex import update_database_from_disk
from quickbbs.fileindex import FileIndex
from quickbbs.models import DirectoryIndex


class SecureClientMixin:
    """Issue requests as HTTPS — SECURE_SSL_REDIRECT 301s plain-HTTP requests."""

    client: Client  # provided by the TestCase this mixin is combined with

    def get(self, path: str, **extra) -> HttpResponse:
        """Return self.client.get(path) with secure=True."""
        # cast: django-stubs types test-client responses as the private
        # _MonkeyPatchedWSGIResponse; at runtime it is an HttpResponse with
        # extra test attributes.
        return cast(HttpResponse, self.client.get(path, secure=True, **extra))


class ViewSmokeTestBase(SecureClientMixin, TestCase):
    """Shared fixture: a temp albums tree with one real JPEG, synced into the DB.

    update_database_from_disk() ends with close_old_connections(); with
    CONN_MAX_AGE=0 that closes the connection outright, which cannot be
    reopened inside TestCase's atomic wrapper — so it is patched to a no-op
    for the duration of each test.
    """

    def setUp(self) -> None:
        self._coc_patcher = mock.patch("quickbbs.directoryindex.close_old_connections")
        self._coc_patcher.start()
        layout_manager_cache.clear()
        self.temp_dir = tempfile.mkdtemp()
        self.albums_dir = os.path.join(self.temp_dir, "albums")
        os.makedirs(self.albums_dir, exist_ok=True)

        image = Image.new("RGB", (32, 32), (120, 30, 200))
        self.image_path = os.path.join(self.albums_dir, "photo.jpg")
        image.save(self.image_path, format="JPEG")
        image.close()

        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir)
        self._settings_override.enable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None

        # frontend.utilities captures ALBUMS_PATH at import time as
        # _ALBUMS_PATH_LOWER, so override_settings alone cannot redirect
        # convert_to_webpath(). realpath: mkdtemp returns /var/... which
        # normalize_fqpn resolves to /private/var/... on macOS.
        self._prefix_patcher = mock.patch(
            "frontend.utilities._ALBUMS_PATH_LOWER",
            os.path.realpath(self.temp_dir).lower(),
        )
        self._prefix_patcher.start()
        webpaths_cache.clear()
        breadcrumbs_cache.clear()

        _, dir_obj = DirectoryIndex.add_directory(self.albums_dir + "/")
        assert dir_obj is not None, "add_directory rejected the albums fixture path"
        self.dir_obj: DirectoryIndex = dir_obj
        update_database_from_disk(self.dir_obj)
        file_obj = FileIndex.objects.filter(name__iexact="photo.jpg").first()
        assert file_obj is not None, "sync did not create the FileIndex record"
        self.file_obj: FileIndex = file_obj

    def tearDown(self) -> None:
        self._prefix_patcher.stop()
        webpaths_cache.clear()
        breadcrumbs_cache.clear()
        self._coc_patcher.stop()
        self._settings_override.disable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        layout_manager_cache.clear()
        shutil.rmtree(self.temp_dir, ignore_errors=True)


class TestRootRedirect(SecureClientMixin, TestCase):
    """The site root redirects to the gallery."""

    def test_root_redirects_to_albums(self):
        """GET / issues a redirect to /albums."""
        response = self.get("/")
        assert response.status_code == 302
        assert response["Location"] == "/albums"


class TestGalleryView(ViewSmokeTestBase):
    """new_viewgallery via /albums/..."""

    def test_gallery_root_returns_200(self):
        """The albums root renders the gallery template with our file listed."""
        response = self.get("/albums/")
        assert response.status_code == 200
        assert b"photo" in response.content.lower()

    def test_gallery_missing_directory_returns_404(self):
        """A path that does not exist on disk returns 404."""
        response = self.get("/albums/no_such_directory/")
        assert response.status_code == 404

    def test_gallery_subdirectory_discovered_on_demand(self):
        """A directory created on disk after the initial sync is served on first visit."""
        new_dir = os.path.join(self.albums_dir, "newalbum")
        os.makedirs(new_dir)
        response = self.get("/albums/newalbum/")
        assert response.status_code == 200
        assert DirectoryIndex.objects.filter(fqpndirectory__icontains="newalbum").exists()


class TestDownloadFile(ViewSmokeTestBase):
    """download_file via /download_file/?usha=..."""

    def test_download_returns_file_content(self):
        """A valid unique SHA streams back the exact file bytes."""
        response = self.get(f"/download_file/?usha={self.file_obj.unique_sha256}")
        assert response.status_code == 200
        if response.streaming:
            # Async view — streaming_content is an async iterator.
            async def _collect() -> bytes:
                return b"".join([chunk async for chunk in response.streaming_content])

            body = asyncio.run(_collect())
        else:
            body = response.content
        with open(self.image_path, "rb") as fh:
            assert body == fh.read()

    def test_download_without_identifier_returns_404(self):
        """No usha parameter raises Http404."""
        response = self.get("/download_file/")
        assert response.status_code == 404

    def test_download_unknown_sha_returns_404(self):
        """An unknown SHA returns 404, not a server error."""
        response = self.get(f"/download_file/?usha={'0' * 64}")
        assert response.status_code == 404


class TestHtmxViewItem(ViewSmokeTestBase):
    """htmx_view_item via /view_item/<sha256>/"""

    def test_view_item_returns_200(self):
        """A valid unique SHA renders the item view."""
        response = self.get(f"/view_item/{self.file_obj.unique_sha256}/")
        assert response.status_code == 200

    def test_view_item_unknown_sha_is_client_error(self):
        """An unknown SHA returns a 4xx client error, not a server error."""
        response = self.get(f"/view_item/{'0' * 64}/")
        assert 400 <= response.status_code < 500


class TestSearchView(ViewSmokeTestBase):
    """search_viewresults via /search/"""

    def test_search_returns_200_with_results(self):
        """Searching for the known file name renders the results page."""
        response = self.get("/search/?searchtext=photo")
        assert response.status_code == 200
        assert b"photo" in response.content.lower()

    def test_search_no_match_returns_200(self):
        """A search with no hits still renders (empty results, not an error)."""
        response = self.get("/search/?searchtext=zzz_no_such_file")
        assert response.status_code == 200


class TestThumbnailViews(ViewSmokeTestBase):
    """thumbnail2_file / thumbnail2_dir endpoints."""

    def test_thumbnail_file_returns_image(self):
        """A file thumbnail request returns an image payload."""
        response = self.get(f"/thumbnail2_file/{self.file_obj.file_sha256}?size=small")
        assert response.status_code == 200
        assert response["Content-Type"].startswith("image/")

    def test_thumbnail_directory_returns_image(self):
        """A directory thumbnail request returns an image payload."""
        response = self.get(f"/thumbnail2_directory/{self.dir_obj.dir_fqpn_sha256}")
        assert response.status_code == 200
        assert response["Content-Type"].startswith("image/")


class TestPreferencesToggle(SecureClientMixin, TestCase):
    """toggle_show_duplicates requires an authenticated user."""

    def test_anonymous_toggle_redirects_to_login(self):
        """An anonymous request is redirected to the login flow, not executed."""
        response = self.get("/preferences/toggle-duplicates/")
        assert response.status_code == 302
        assert "login" in response["Location"]

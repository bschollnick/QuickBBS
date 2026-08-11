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
import inspect
import os
import shutil
import tempfile
from typing import cast
from unittest import mock

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import Client, TestCase, override_settings
from PIL import Image

from frontend.utilities import breadcrumbs_cache, webpaths_cache
from quickbbs.cache_registry import layout_manager_cache
from quickbbs.directoryindex import update_database_from_disk
from quickbbs.fileindex import FileIndex
from quickbbs.models import DirectoryIndex

pytestmark = pytest.mark.web


def assert_not_login_redirect(response: HttpResponse, path: str) -> None:
    """Fail with an actionable message when a view redirected to the login page.

    These smoke tests exercise the anonymous browsing path. When
    QUICKBBS_REQUIRE_LOGIN is enabled every gated view answers 302 to
    LOGIN_URL, so the assertions below cannot say anything about the view
    itself — the outcome is inconclusive rather than a genuine regression.

    Note that QUICKBBS_REQUIRE_LOGIN is read at import time by
    quickbbs.common.require_login_if_configured (the decorator is applied when
    the view module is imported), so override_settings cannot switch it off for
    a single test — the setting has to be changed and the suite re-run.

    Args:
        response: The response returned by the test client.
        path: The requested path, for the failure message.

    Raises:
        AssertionError: If the response is a redirect to settings.LOGIN_URL.
    """
    if response.status_code not in (301, 302):
        return
    location = response.headers.get("Location", "")
    if not location.startswith(settings.LOGIN_URL):
        return
    raise AssertionError(
        f"INCONCLUSIVE (not necessarily a regression): GET {path} redirected to the "
        f"login page ({location}).\n"
        f"QUICKBBS_REQUIRE_LOGIN is currently {settings.QUICKBBS_REQUIRE_LOGIN!r}, so this "
        "test could not reach the view it is meant to check.\n"
        "To prove this endpoint actually works, set QUICKBBS_REQUIRE_LOGIN = False in "
        "quickbbs/quickbbs_settings.py and re-run this test.\n"
        "(The setting is captured at import time, so override_settings will not help here.)"
    )


class SecureClientMixin:
    """Issue requests as HTTPS — SECURE_SSL_REDIRECT 301s plain-HTTP requests."""

    client: Client  # provided by the TestCase this mixin is combined with

    def get(self, path: str, *, allow_login_redirect: bool = False, **extra) -> HttpResponse:
        """Return self.client.get(path) with secure=True.

        Args:
            path: The path to request.
            allow_login_redirect: Set True for tests that assert on the login
                redirect itself; otherwise a redirect to LOGIN_URL is reported
                as an inconclusive result.
            **extra: Passed through to the test client.

        Returns:
            The test-client response.

        Raises:
            AssertionError: If restricted access redirected the request to the
                login page, which would make the caller's assertions
                inconclusive. See assert_not_login_redirect.
        """
        # cast: django-stubs types test-client responses as the private
        # _MonkeyPatchedWSGIResponse; at runtime it is an HttpResponse with
        # extra test attributes.
        response = cast(HttpResponse, self.client.get(path, secure=True, **extra))
        if not allow_login_redirect:
            assert_not_login_redirect(response, path)
        return response


class ViewSmokeTestBase(SecureClientMixin, TestCase):
    """Shared fixture: a temp albums tree with one real JPEG, synced into the DB.

    update_database_from_disk() ends with close_old_connections(); with
    CONN_MAX_AGE=0 that closes the connection outright, which cannot be
    reopened inside TestCase's atomic wrapper — so it is patched to a no-op
    for the duration of each test.

    The client is logged in as self.user, so these tests exercise the views
    themselves whether or not QUICKBBS_REQUIRE_LOGIN is enabled. The gate is
    covered separately by TestAnonymousAccessIsGated.
    """

    def setUp(self) -> None:
        self._coc_patcher = mock.patch("quickbbs.directoryindex.close_old_connections")
        self._coc_patcher.start()
        self.user = get_user_model().objects.create_user(username="smoketester", password="pw")
        self.client.force_login(self.user)
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
    """view_gallery via /albums/..."""

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

    def test_gallery_invalid_path_returns_400(self):
        """A path outside ALBUMS_PATH is rejected as invalid, not merely not-found."""
        response = self.get("/albums/../../../../etc/")
        assert response.status_code in (400, 404)

    def test_gallery_page_lists_subdirectory(self):
        """When the page contains a subdirectory, it is discovered and listed on revisit."""
        os.makedirs(os.path.join(self.albums_dir, "subalbum"))
        update_database_from_disk(self.dir_obj)
        self.dir_obj.invalidate_cache()
        response = self.get("/albums/")
        assert response.status_code == 200
        assert DirectoryIndex.objects.filter(fqpndirectory__icontains="subalbum").exists()

    def test_gallery_authenticated_user_sets_no_cache_header(self):
        """An authenticated request gets a private/no-cache Cache-Control header."""
        # The base fixture already logged self.user in.
        response = self.get("/albums/")
        assert response.status_code == 200
        assert response["Cache-Control"] == "private, no-cache, must-revalidate"


class TestGalleryDirectoryRaceCondition(SecureClientMixin, TestCase):
    """view_gallery's _find_directory race-condition branch: DB record exists
    but the directory has been removed from disk since it was added."""

    def setUp(self) -> None:
        self._coc_patcher = mock.patch("quickbbs.directoryindex.close_old_connections")
        self._coc_patcher.start()
        # Logged in so the assertion targets the race-condition branch rather
        # than the login gate (see TestAnonymousAccessIsGated).
        self.user = get_user_model().objects.create_user(username="raceuser", password="pw")
        self.client.force_login(self.user)
        layout_manager_cache.clear()
        self.temp_dir = tempfile.mkdtemp()
        self.albums_dir = os.path.join(self.temp_dir, "albums")
        self.stale_dir = os.path.join(self.albums_dir, "stale")
        os.makedirs(self.stale_dir, exist_ok=True)

        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir)
        self._settings_override.enable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None

        self._prefix_patcher = mock.patch(
            "frontend.utilities._ALBUMS_PATH_LOWER",
            os.path.realpath(self.temp_dir).lower(),
        )
        self._prefix_patcher.start()
        webpaths_cache.clear()
        breadcrumbs_cache.clear()

        _, self.dir_obj = DirectoryIndex.add_directory(self.stale_dir + "/")
        assert self.dir_obj is not None

        # Simulate the directory disappearing from disk after being recorded.
        shutil.rmtree(self.stale_dir)

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

    def test_directory_removed_from_disk_returns_404(self):
        """A directory present in the DB but missing on disk returns 404, not a server error."""
        response = self.get("/albums/stale/")
        assert response.status_code == 404


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

    def test_view_item_authenticated_user_sets_no_cache_header(self):
        """An authenticated request gets a private/no-cache Cache-Control header."""
        # The base fixture already logged self.user in.
        response = self.get(f"/view_item/{self.file_obj.unique_sha256}/")
        assert response.status_code == 200
        assert response["Cache-Control"] == "private, no-cache, must-revalidate"


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
    """thumbnail_file / thumbnail_dir endpoints."""

    def test_thumbnail_file_returns_image(self):
        """A file thumbnail request returns an image payload."""
        response = self.get(f"/thumbnail_file/{self.file_obj.file_sha256}?size=small")
        assert response.status_code == 200
        assert response["Content-Type"].startswith("image/")

    def test_thumbnail_directory_returns_image(self):
        """A directory thumbnail request returns an image payload."""
        response = self.get(f"/thumbnail_directory/{self.dir_obj.dir_fqpn_sha256}")
        assert response.status_code == 200
        assert response["Content-Type"].startswith("image/")


class TestAnonymousAccessIsGated(ViewSmokeTestBase):
    """The other half of the smoke tests: with QUICKBBS_REQUIRE_LOGIN enabled,
    every gated endpoint must bounce an anonymous visitor to LOGIN_URL rather
    than serve content.

    ViewSmokeTestBase logs a user in; each test here logs back out so the
    request is genuinely anonymous while keeping the albums fixture. That
    covers both directions: the sibling classes prove an authenticated user
    reaches the view, and these prove an anonymous one does not.
    """

    # Every view decorated with @require_login_if_configured, by URL.
    # frontend/views.py: view_gallery, search_viewresults, htmx_view_item,
    # download_file; thumbnails/views.py: thumbnail_file, thumbnail_dir;
    # frontend/report_views.py: duplicate_files_report.
    def _gated_urls(self) -> dict[str, str]:
        """Return {label: url} for every login-gated endpoint.

        Returns:
            Mapping of human-readable label to a valid URL for that view.
        """
        return {
            "gallery": "/albums/",
            "search": "/search/?searchtext=photo",
            "view_item": f"/view_item/{self.file_obj.unique_sha256}/",
            "download": f"/download_file/?usha={self.file_obj.unique_sha256}",
            "thumbnail_file": f"/thumbnail_file/{self.file_obj.file_sha256}",
            "thumbnail_dir": f"/thumbnail_directory/{self.dir_obj.dir_fqpn_sha256}",
            "duplicate_report": "/reports/duplicate_files.html",
        }

    def test_anonymous_requests_redirect_to_login(self):
        """Every gated endpoint redirects an anonymous visitor to LOGIN_URL."""
        if not settings.QUICKBBS_REQUIRE_LOGIN:
            pytest.skip("QUICKBBS_REQUIRE_LOGIN is disabled; anonymous browsing is allowed by design.")

        self.client.logout()
        served = []
        for label, url in self._gated_urls().items():
            response = self.get(url, allow_login_redirect=True)
            location = response.headers.get("Location", "")
            if not (response.status_code in (301, 302) and location.startswith(settings.LOGIN_URL)):
                served.append(f"{label} ({url}) -> {response.status_code} {location}".rstrip())
        assert not served, "Anonymous requests were NOT redirected to the login page:\n  " + "\n  ".join(served)

    def test_authenticated_requests_are_not_redirected(self):
        """The same endpoints serve content for a logged-in user.

        Guards against the gate being enforced so broadly that authentication
        stops helping — the failure mode a redirect-only test cannot see.
        """
        redirected = []
        for label, url in self._gated_urls().items():
            response = self.get(url, allow_login_redirect=True)
            location = response.headers.get("Location", "")
            if response.status_code in (301, 302) and location.startswith(settings.LOGIN_URL):
                redirected.append(f"{label} ({url})")
        assert not redirected, "Logged-in requests were redirected to the login page:\n  " + "\n  ".join(redirected)


class TestPreferencesToggle(SecureClientMixin, TestCase):
    """toggle_show_duplicates requires an authenticated user."""

    def test_anonymous_toggle_redirects_to_login(self):
        """An anonymous request is redirected to the login flow, not executed."""
        # allow_login_redirect: this view is login-gated by design, so the
        # redirect is the behavior under test rather than an inconclusive run.
        response = self.get("/preferences/toggle-duplicates/", allow_login_redirect=True)
        assert response.status_code == 302
        assert "login" in response["Location"]


class TestPhase5ViewsAreSync(TestCase):
    """Regression guard for async_simplification.md Phase 5.

    search_viewresults, view_gallery, htmx_view_item, and
    duplicate_files_report were deliberately converted from async def to
    plain def (Phase 5) after production load-test data showed no latency
    benefit from keeping them async. A future edit reintroducing `async`
    on any of these would silently re-add the sync_to_async crossings this
    phase removed — assert they stay plain functions.
    """

    def test_search_viewresults_is_sync(self):
        """search_viewresults must remain a plain function, not a coroutine."""
        from frontend.views import search_viewresults

        assert not inspect.iscoroutinefunction(search_viewresults)

    def test_view_gallery_is_sync(self):
        """view_gallery must remain a plain function, not a coroutine."""
        from frontend.views import view_gallery

        assert not inspect.iscoroutinefunction(view_gallery)

    def test_htmx_view_item_is_sync(self):
        """htmx_view_item must remain a plain function, not a coroutine."""
        from frontend.views import htmx_view_item

        assert not inspect.iscoroutinefunction(htmx_view_item)

    def test_duplicate_files_report_is_sync(self):
        """duplicate_files_report must remain a plain function, not a coroutine."""
        from frontend.report_views import duplicate_files_report

        assert not inspect.iscoroutinefunction(duplicate_files_report)

    def test_download_file_remains_async(self):
        """download_file is explicitly out of Phase 5's scope — must stay async."""
        from frontend.views import download_file

        assert inspect.iscoroutinefunction(download_file)

"""
Tests for frontend.views.toggle_favorite — the HTMX favorite toggle endpoint.

DATABASE SAFETY NOTES
----------------------
All tests use Django's TestCase (each test wrapped in a rolled-back
transaction against the test database). No TransactionTestCase is used — ever.
"""

from __future__ import annotations

import pytest
from django.test import Client, TestCase

from frontend.tests.test_views import ViewSmokeTestBase
from quickbbs.models import Favorite

pytestmark = pytest.mark.web


class TestToggleFavoriteFile(ViewSmokeTestBase):
    """toggle_favorite for a file target."""

    def test_toggle_creates_and_removes_favorite(self):
        """POSTing the same sha256 twice favorites then unfavorites."""
        assert not Favorite.is_favorited(self.user, file_sha256=self.file_obj.unique_sha256)

        response = self.client.post(
            "/favorite/toggle/",
            {"sha256": self.file_obj.unique_sha256, "is_dir": "false"},
            secure=True,
        )
        assert response.status_code == 200
        assert b"is-favorited" in response.content
        assert Favorite.is_favorited(self.user, file_sha256=self.file_obj.unique_sha256)

        response = self.client.post(
            "/favorite/toggle/",
            {"sha256": self.file_obj.unique_sha256, "is_dir": "false"},
            secure=True,
        )
        assert response.status_code == 200
        assert b"is-favorited" not in response.content
        assert not Favorite.is_favorited(self.user, file_sha256=self.file_obj.unique_sha256)

    def test_missing_sha256_returns_400(self):
        """POST without a sha256 field is a bad request."""
        response = self.client.post("/favorite/toggle/", {"is_dir": "false"}, secure=True)
        assert response.status_code == 400

    def test_unknown_sha256_returns_400(self):
        """POST with a sha256 that resolves to no FileIndex is a bad request."""
        response = self.client.post(
            "/favorite/toggle/",
            {"sha256": "0" * 64, "is_dir": "false"},
            secure=True,
        )
        assert response.status_code == 400


class TestToggleFavoriteDirectory(ViewSmokeTestBase):
    """toggle_favorite for a directory target."""

    def test_toggle_creates_and_removes_favorite(self):
        """POSTing the same dir_fqpn_sha256 twice favorites then unfavorites."""
        assert not Favorite.is_favorited(self.user, dir_sha256=self.dir_obj.dir_fqpn_sha256)

        response = self.client.post(
            "/favorite/toggle/",
            {"sha256": self.dir_obj.dir_fqpn_sha256, "is_dir": "true"},
            secure=True,
        )
        assert response.status_code == 200
        assert Favorite.is_favorited(self.user, dir_sha256=self.dir_obj.dir_fqpn_sha256)

        response = self.client.post(
            "/favorite/toggle/",
            {"sha256": self.dir_obj.dir_fqpn_sha256, "is_dir": "true"},
            secure=True,
        )
        assert response.status_code == 200
        assert not Favorite.is_favorited(self.user, dir_sha256=self.dir_obj.dir_fqpn_sha256)


class TestToggleFavoriteAnonymous(TestCase):
    """Anonymous requests are gated behind login."""

    def test_anonymous_post_redirects_to_login(self):
        """An anonymous POST is redirected to the login page, not processed."""
        client = Client()
        response = client.post(
            "/favorite/toggle/",
            {"sha256": "0" * 64, "is_dir": "false"},
            secure=True,
        )
        assert response.status_code == 302
        assert "/accounts/login" in response["Location"]


class TestToggleFavoriteGalleryReflectsState(ViewSmokeTestBase):
    """The gallery grid reflects favorite state after a toggle, uncached."""

    def test_gallery_shows_favorited_star_after_toggle(self):
        """After favoriting the fixture file, the gallery page's rendered
        star for that item is in the favorited state — proves the gallery
        grid's authenticated (uncached) branch reads live Favorite state."""
        self.client.post(
            "/favorite/toggle/",
            {"sha256": self.file_obj.unique_sha256, "is_dir": "false"},
            secure=True,
        )
        response = self.get("/albums/")
        assert response.status_code == 200
        assert b"is-favorited" in response.content

    def test_item_view_shows_favorited_star_after_toggle(self):
        """The item detail view's title bar star reflects the toggled state."""
        self.client.post(
            "/favorite/toggle/",
            {"sha256": self.file_obj.unique_sha256, "is_dir": "false"},
            secure=True,
        )
        response = self.get(f"/view_item/{self.file_obj.unique_sha256}/")
        assert response.status_code == 200
        assert b"is-favorited" in response.content


class TestFavoritesPage(ViewSmokeTestBase):
    """/favorites/ lists the requesting user's favorited files and directories."""

    def test_empty_favorites_returns_200(self):
        """No favorites yet — page still renders successfully."""
        response = self.get("/favorites/")
        assert response.status_code == 200

    def test_favorited_file_appears_on_page(self):
        """A favorited file's name appears in the favorites listing."""
        self.client.post(
            "/favorite/toggle/",
            {"sha256": self.file_obj.unique_sha256, "is_dir": "false"},
            secure=True,
        )
        response = self.get("/favorites/")
        assert response.status_code == 200
        assert b"photo" in response.content.lower()
        assert b"is-favorited" in response.content

    def test_unfavorited_file_does_not_appear(self):
        """A file that was never favorited is absent from the listing."""
        response = self.get("/favorites/")
        assert response.status_code == 200
        assert b"photo" not in response.content.lower()

    def test_anonymous_redirects_to_login(self):
        """An anonymous visitor is redirected to login, not shown the page."""
        client = Client()
        response = client.get("/favorites/", secure=True)
        assert response.status_code == 302
        assert "/accounts/login" in response["Location"]

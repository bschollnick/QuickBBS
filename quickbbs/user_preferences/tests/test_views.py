"""Tests for user_preferences/views.py — toggle_show_duplicates."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from frontend.views import _user_pref_cache
from quickbbs.cache_registry import layout_manager_cache
from user_preferences.models import UserPreferences

pytestmark = pytest.mark.web


class TestToggleShowDuplicates(TestCase):
    """toggle_show_duplicates via /preferences/toggle-duplicates/"""

    def setUp(self) -> None:
        self.client = Client()
        self.user = get_user_model().objects.create_user(username="prefuser", password="pw")
        _user_pref_cache.clear()
        layout_manager_cache.clear()

    def tearDown(self) -> None:
        _user_pref_cache.clear()
        layout_manager_cache.clear()

    def test_anonymous_redirects_to_login(self):
        """An unauthenticated request is redirected to the login flow."""
        response = self.client.get("/preferences/toggle-duplicates/", secure=True)
        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_toggle_flips_preference_from_false_to_true(self):
        """A toggle flips a default-False preference to True.

        Note: a post_save signal on User auto-creates UserPreferences
        (show_duplicates=False by default), so no row is created here — only flipped.
        """
        self.client.force_login(self.user)
        assert UserPreferences.objects.get(user=self.user).show_duplicates is False
        self.client.get("/preferences/toggle-duplicates/", secure=True)
        prefs = UserPreferences.objects.get(user=self.user)
        assert prefs.show_duplicates is True

    def test_toggle_flips_preference_back_to_false(self):
        """A second toggle flips an existing True preference back to False."""
        # force_login() triggers User.save(), and save_user_preferences()
        # re-saves instance.preferences from its (stale) cached state — so
        # log in *before* flipping to True, not after.
        self.client.force_login(self.user)
        prefs = UserPreferences.objects.get(user=self.user)
        prefs.show_duplicates = True
        prefs.save()
        self.client.get("/preferences/toggle-duplicates/", secure=True)
        prefs.refresh_from_db()
        assert prefs.show_duplicates is False

    def test_redirects_to_referer(self):
        """The response redirects to HTTP_REFERER when present."""
        self.client.force_login(self.user)
        response = self.client.get(
            "/preferences/toggle-duplicates/",
            secure=True,
            HTTP_REFERER="/albums/somewhere/",
        )
        assert response.status_code == 302
        assert response["Location"] == "/albums/somewhere/"

    def test_redirects_to_root_without_referer(self):
        """The response redirects to '/' when no HTTP_REFERER is present."""
        self.client.force_login(self.user)
        response = self.client.get("/preferences/toggle-duplicates/", secure=True)
        assert response.status_code == 302
        assert response["Location"] == "/"

    def test_response_has_no_cache_headers(self):
        """The toggle response is marked non-cacheable."""
        self.client.force_login(self.user)
        response = self.client.get("/preferences/toggle-duplicates/", secure=True)
        assert response["Cache-Control"] == "no-cache, no-store, must-revalidate, max-age=0"
        assert response["Pragma"] == "no-cache"
        assert response["Expires"] == "0"

    def test_toggle_clears_user_pref_cache_entry(self):
        """The user's entry in _user_pref_cache is purged so the next load re-queries."""
        _user_pref_cache[self.user.pk] = False
        self.client.force_login(self.user)
        self.client.get("/preferences/toggle-duplicates/", secure=True)
        assert _user_pref_cache.get(self.user.pk) is None

    def test_toggle_purges_matching_layout_cache_entries(self):
        """layout_manager_cache entries keyed with the old show_duplicates value are purged."""
        old_key = (1, 42, 0, False)
        other_key = (1, 42, 0, True)
        layout_manager_cache[old_key] = {"stale": True}
        layout_manager_cache[other_key] = {"fresh": True}
        self.client.force_login(self.user)
        self.client.get("/preferences/toggle-duplicates/", secure=True)
        assert old_key not in layout_manager_cache
        assert other_key in layout_manager_cache

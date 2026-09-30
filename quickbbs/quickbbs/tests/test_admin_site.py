"""The project's admin site replaces Django's default and adds the vacuum widget."""

from __future__ import annotations

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from quickbbs.admin_site import QuickbbsAdminSite

pytestmark = pytest.mark.web


class AdminSiteTests(TestCase):
    """`admin.site` is `QuickbbsAdminSite`, and its index page carries the widget's data."""

    def test_the_default_admin_site_is_the_project_site(self) -> None:
        """`QuickbbsAdminConfig` installs the project site as `admin.site`."""
        self.assertIsInstance(admin.site, QuickbbsAdminSite)

    def test_the_admin_index_carries_the_vacuum_candidates(self) -> None:
        """The index view adds `vacuum_candidates` for the template's widget."""
        user = get_user_model().objects.create_superuser("admin_site_test", "admin@example.com", "unused-password")
        self.client.force_login(user)
        response = self.client.get(reverse("admin:index"), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("vacuum_candidates", response.context)

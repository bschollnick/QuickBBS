"""Tests for frontend/report_views.py — duplicate-files report (api helper + web view)."""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest
from django.test import Client, TestCase, override_settings

from filetypes.models import filetypes
from frontend.report_views import _get_duplicate_sha_data
from quickbbs.models import DirectoryIndex, FileIndex


def _get_ft(fileext: str) -> filetypes:
    """Return filetypes object for a given extension."""
    return filetypes.objects.get(fileext=fileext)


def _sha(prefix: str) -> str:
    """Return a 64-char hex-like string padded with zeros."""
    return (prefix + "0" * 64)[:64]


def _make_fileindex(directory: DirectoryIndex, name: str, file_sha: str, unique_sha: str, ft: filetypes) -> FileIndex:
    """Create a minimal FileIndex record without touching the filesystem."""
    return FileIndex.objects.create(
        home_directory=directory,
        name=name,
        file_sha256=file_sha,
        unique_sha256=unique_sha,
        lastscan=0.0,
        lastmod=0.0,
        filetype=ft,
        delete_pending=False,
        is_generic_icon=False,
    )


class DuplicateReportTestBase(TestCase):
    """Common tempdir/ALBUMS_PATH setup plus a >5-duplicate FileIndex fixture."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.temp_dir, "albums"), exist_ok=True)
        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir)
        self._settings_override.enable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        _, self.dir_obj = DirectoryIndex.add_directory(os.path.join(self.temp_dir, "albums") + "/")
        assert self.dir_obj is not None
        ft = _get_ft(".txt")

        # 6 files sharing one SHA — triggers the dupe_count__gt=5 filter.
        self.dup_sha = _sha("dup")
        for i in range(6):
            _make_fileindex(self.dir_obj, f"dup_{i}.txt", self.dup_sha, _sha(f"u{i}"), ft)

        # A file with a unique SHA — must not appear in the report.
        _make_fileindex(self.dir_obj, "unique.txt", _sha("solo"), _sha("usolo"), ft)

    def tearDown(self) -> None:
        self._settings_override.disable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)


@pytest.mark.api
class TestGetDuplicateShaData(DuplicateReportTestBase):
    """api-layer: _get_duplicate_sha_data aggregation logic."""

    def test_no_duplicates_returns_empty(self):
        """When no SHA appears more than 5 times, an empty result is returned."""
        FileIndex.objects.filter(file_sha256=self.dup_sha).delete()
        result = _get_duplicate_sha_data()
        assert result == {"groups": [], "total_shas": 0, "total_files": 0}

    def test_duplicate_group_included(self):
        """A SHA appearing 6 times is reported as one group with 6 files."""
        result = _get_duplicate_sha_data()
        assert result["total_shas"] == 1
        assert result["total_files"] == 6
        assert len(result["groups"]) == 1
        group = result["groups"][0]
        assert group["sha256"] == self.dup_sha
        assert group["count"] == 6
        assert len(group["files"]) == 6

    def test_unique_file_excluded(self):
        """A file whose SHA is not duplicated is not included in any group."""
        result = _get_duplicate_sha_data()
        all_names = {f["name"] for group in result["groups"] for f in group["files"]}
        assert "unique.txt" not in all_names


@pytest.mark.web
class TestDuplicateFilesReportView(DuplicateReportTestBase):
    """web-layer: duplicate_files_report via /reports/duplicate_files.html"""

    def setUp(self) -> None:
        super().setUp()
        self.client = Client()

    def test_report_returns_200(self):
        """The report page renders successfully."""
        response = self.client.get("/reports/duplicate_files.html", secure=True)
        assert response.status_code == 200

    def test_report_shows_duplicate_sha(self):
        """The rendered report includes the duplicated SHA256."""
        response = self.client.get("/reports/duplicate_files.html", secure=True)
        assert self.dup_sha.encode() in response.content

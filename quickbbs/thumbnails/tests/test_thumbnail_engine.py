"""
Tests for the Django-side thumbnail integration: the app's wiring of the engine
config, the creation-time whitecheck, and the shared all-white detector's use
from the scan command.

Backend selection, fork-safety hooks, and the detector's own pixel logic are
covered without Django in thumbnails/engine/tests/test_engine.py.

DATABASE SAFETY NOTES
---------------------
- All tests use Django's TestCase (transaction rolled back per test).
- No TransactionTestCase is used — ever.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from unittest import mock

import pytest
from django.test import TestCase, override_settings
from PIL import Image

from thumbnails.models import (
    THUMBNAILFILES_PR_FILEINDEX_FILETYPE,
    ThumbnailFiles,
    _is_suspect_all_white,
    is_all_white_thumbnail,
)

pytestmark = pytest.mark.api

IMAGE_SIZES = {"small": (200, 200), "medium": (740, 740), "large": (1024, 1024)}


def _jpeg_bytes(color: tuple[int, int, int] | int, mode: str = "RGB", size: tuple[int, int] = (200, 200)) -> bytes:
    """Return an in-memory JPEG of a solid color."""
    img = Image.new(mode, size, color)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=55)
    img.close()
    return buffer.getvalue()


def _gradient_jpeg_bytes(size: tuple[int, int] = (200, 200)) -> bytes:
    """Return an in-memory JPEG with non-uniform pixel content."""
    img = Image.new("RGB", size)
    img.putdata([(x % 256, (x * 7) % 256, (x * 13) % 256) for x in range(size[0] * size[1])])
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    img.close()
    return buffer.getvalue()


# ===========================================================================
# Settings-gated suspect check and shared-detector wiring
# ===========================================================================


class TestAllWhiteDetector(TestCase):
    """_is_suspect_all_white's settings-driven size gate, and detector reuse.

    The detector's own pixel logic is covered in the engine's Django-free
    suite; these cases exist because they depend on Django settings or on
    QuickBBS wiring.
    """

    def test_suspect_gate_true_for_small_white_blob(self):
        """A small all-white blob is flagged as suspect GPU corruption."""
        blob = _jpeg_bytes((255, 255, 255))
        assert len(blob) < 2500  # sanity: below SMALL_THUMBNAIL_SAFEGUARD_SIZE
        assert _is_suspect_all_white(blob) is True

    def test_suspect_gate_false_above_safeguard_size(self):
        """Blobs at/above the safeguard size are never decoded or flagged.

        JPEG decoders ignore trailing bytes after the EOI marker, so padding a
        white JPEG past the threshold yields a valid-but-large all-white blob.
        """
        padded = _jpeg_bytes((255, 255, 255)) + b"\x00" * 4000
        assert _is_suspect_all_white(padded) is False

    def test_scan_command_uses_shared_detector(self):
        """Guards against the detection logic being re-inlined in scan.py."""
        from quickbbs.management.commands import scan

        assert scan.is_all_white_thumbnail is is_all_white_thumbnail


# ===========================================================================
# Creation-time whitecheck (MAC_OPTIMIZATION_WHITECHECK)
# ===========================================================================


class TestWhitecheckGate(TestCase):
    """get_or_create_thumbnail_record honors MAC_OPTIMIZATION_WHITECHECK."""

    def setUp(self):
        from filetypes.models import filetypes
        from quickbbs.models import DirectoryIndex, FileIndex

        # ALBUMS_PATH must cover the temp directory or add_directory rejects it
        # (albums-root enforcement) and the FileIndex ends up orphaned.
        self.temp_dir = tempfile.mkdtemp()
        self.albums_dir = os.path.join(self.temp_dir, "albums")
        os.makedirs(self.albums_dir, exist_ok=True)
        self._settings_override = override_settings(ALBUMS_PATH=self.temp_dir)
        self._settings_override.enable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        _, self.dir_obj = DirectoryIndex.add_directory(self.albums_dir + "/")
        self.sha = "f" * 64
        self.file_obj = FileIndex.objects.create(
            home_directory=self.dir_obj,
            name="white.jpg",
            file_sha256=self.sha,
            unique_sha256="e" * 64,
            lastscan=0.0,
            lastmod=0.0,
            filetype=filetypes.objects.get(fileext=".jpg"),
            delete_pending=False,
            is_generic_icon=False,
        )
        self.white = _jpeg_bytes((255, 255, 255))
        self.normal = _gradient_jpeg_bytes()

    def tearDown(self):
        from quickbbs.models import DirectoryIndex

        self._settings_override.disable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _generate(self) -> ThumbnailFiles:
        return ThumbnailFiles.get_or_create_thumbnail_record(
            self.sha,
            suppress_save=True,
            prefetch_related_thumbnail=THUMBNAILFILES_PR_FILEINDEX_FILETYPE,
            select_related_fileindex=("filetype",),
        )

    @override_settings(MAC_OPTIMIZATION_WHITECHECK=False)
    def test_whitecheck_disabled_stores_white_result(self):
        """With the gate off (default), an all-white result is kept as-is."""
        white_result = {"small": self.white, "medium": self.white, "large": self.white}
        with mock.patch("thumbnails.models.create_thumbnails_from_path", return_value=white_result) as generator:
            thumbnail = self._generate()
        assert generator.call_count == 1
        assert bytes(thumbnail.small_thumb) == self.white

    @override_settings(MAC_OPTIMIZATION_WHITECHECK=True)
    def test_whitecheck_regenerates_once_and_logs(self):
        """With the gate on, a white result triggers one logged retry via the
        cross-platform backend, and the retry's output is stored."""
        white_result = {"small": self.white, "medium": self.white, "large": self.white}
        normal_result = {"small": self.normal, "medium": self.normal, "large": self.normal}
        with mock.patch(
            "thumbnails.models.create_thumbnails_from_path",
            side_effect=[white_result, normal_result],
        ) as generator:
            with self.assertLogs("thumbnails.models", level="WARNING") as captured:
                thumbnail = self._generate()

        assert generator.call_count == 2
        assert generator.call_args_list[1].kwargs["backend"] == "image"
        assert any("All-white thumbnail detected" in message for message in captured.output)
        assert bytes(thumbnail.small_thumb) == self.normal

    @override_settings(MAC_OPTIMIZATION_WHITECHECK=True)
    def test_whitecheck_accepts_retry_result_even_if_still_white(self):
        """The retry result is used unconditionally — no second check, no loop."""
        white_result = {"small": self.white, "medium": self.white, "large": self.white}
        with mock.patch(
            "thumbnails.models.create_thumbnails_from_path",
            side_effect=[white_result, dict(white_result)],
        ) as generator:
            thumbnail = self._generate()
        assert generator.call_count == 2
        assert bytes(thumbnail.small_thumb) == self.white

    @override_settings(MAC_OPTIMIZATION_WHITECHECK=True)
    def test_whitecheck_skips_normal_results(self):
        """A non-white result passes through without any retry."""
        normal_result = {"small": self.normal, "medium": self.normal, "large": self.normal}
        with mock.patch("thumbnails.models.create_thumbnails_from_path", return_value=normal_result) as generator:
            thumbnail = self._generate()
        assert generator.call_count == 1
        assert bytes(thumbnail.small_thumb) == self.normal

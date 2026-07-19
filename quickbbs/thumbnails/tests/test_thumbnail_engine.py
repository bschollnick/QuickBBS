"""
Tests for the thumbnail engine's MACINTOSH_OPTIMIZATIONS gating, fork-safety
hooks, and the shared all-white thumbnail detector / creation-time whitecheck.

DATABASE SAFETY NOTES
---------------------
- All tests use Django's TestCase (transaction rolled back per test).
- No TransactionTestCase is used — ever.
- Backend/processor caches are cleared around gating tests so cached backend
  instances never leak between tests or into other test modules.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from unittest import mock, skipUnless

from django.test import TestCase, override_settings
from PIL import Image

from thumbnails import thumbnail_engine
from thumbnails.models import (
    THUMBNAILFILES_PR_FILEINDEX_FILETYPE,
    ThumbnailFiles,
    _is_suspect_all_white,
    is_all_white_thumbnail,
)
from thumbnails.thumbnail_engine import (
    FastImageProcessor,
    _check_core_image_available,
    clear_backend_caches,
    is_apple_silicon,
    macintosh_optimizations_enabled,
)

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
# MACINTOSH_OPTIMIZATIONS gating in _create_backend
# ===========================================================================


class TestMacintoshOptimizationsGate(TestCase):
    """The auto-selecting backend cases honor settings.MACINTOSH_OPTIMIZATIONS."""

    def setUp(self):
        clear_backend_caches(force_gc=False)

    def tearDown(self):
        clear_backend_caches(force_gc=False)

    @override_settings(MACINTOSH_OPTIMIZATIONS=False)
    def test_helper_reads_setting_false(self):
        """Helper returns False when the setting is False."""
        assert macintosh_optimizations_enabled() is False

    @override_settings(MACINTOSH_OPTIMIZATIONS=True)
    def test_helper_reads_setting_true(self):
        """Helper returns True when the setting is True."""
        assert macintosh_optimizations_enabled() is True

    @override_settings(MACINTOSH_OPTIMIZATIONS=False)
    def test_auto_resolves_to_pil_when_disabled(self):
        """backend="auto" uses PIL when the optimizations are disabled."""
        processor = FastImageProcessor(IMAGE_SIZES, backend="auto")
        assert processor.current_backend == "ImageBackend"

    @override_settings(MACINTOSH_OPTIMIZATIONS=False)
    def test_corevideo_falls_back_to_ffmpeg_when_disabled(self):
        """backend="corevideo" uses FFmpeg when the optimizations are disabled."""
        processor = FastImageProcessor(IMAGE_SIZES, backend="corevideo")
        assert processor.current_backend == "VideoBackend"

    @override_settings(MACINTOSH_OPTIMIZATIONS=False)
    def test_pdf_falls_back_to_pymupdf_when_disabled(self):
        """backend="pdf" uses PyMuPDF when the optimizations are disabled."""
        processor = FastImageProcessor(IMAGE_SIZES, backend="pdf")
        assert processor.current_backend == "PDFBackend"

    @skipUnless(
        _check_core_image_available() and is_apple_silicon(),
        "Core Image backend requires Apple Silicon macOS with pyobjc",
    )
    @override_settings(MACINTOSH_OPTIMIZATIONS=True)
    def test_auto_uses_coreimage_when_enabled(self):
        """backend="auto" selects Core Image when enabled on Apple Silicon."""
        processor = FastImageProcessor(IMAGE_SIZES, backend="auto")
        assert processor.current_backend == "CoreImageBackend"

    @override_settings(MACINTOSH_OPTIMIZATIONS=True)
    def test_explicit_image_backend_unaffected_by_setting(self):
        """Explicit backend="image" is never redirected by the setting."""
        processor = FastImageProcessor(IMAGE_SIZES, backend="image")
        assert processor.current_backend == "ImageBackend"


# ===========================================================================
# os.register_at_fork hooks
# ===========================================================================


class TestForkHooks(TestCase):
    """The fork hooks reset caches/locks so a forked child cannot deadlock or
    reuse a backend whose Metal ports died with the parent."""

    def tearDown(self):
        clear_backend_caches(force_gc=False)

    def test_fork_reset_child_clears_caches_and_replaces_locks(self):
        """Child hook empties both caches and installs fresh lock objects."""
        thumbnail_engine._processor_cache["sentinel"] = object()
        FastImageProcessor._backend_cache["sentinel"] = object()
        old_processor_lock = thumbnail_engine._processor_lock
        old_backend_lock = FastImageProcessor._backend_lock

        thumbnail_engine._fork_reset_child()

        assert not thumbnail_engine._processor_cache
        assert not FastImageProcessor._backend_cache
        assert thumbnail_engine._processor_lock is not old_processor_lock
        assert FastImageProcessor._backend_lock is not old_backend_lock
        assert not thumbnail_engine._processor_lock.locked()
        assert not FastImageProcessor._backend_lock.locked()

    def test_fork_acquire_then_parent_release_leaves_locks_free(self):
        """before + after_in_parent hooks are a balanced acquire/release pair."""
        thumbnail_engine._fork_acquire_locks()
        assert thumbnail_engine._processor_lock.locked()
        assert FastImageProcessor._backend_lock.locked()

        thumbnail_engine._fork_release_locks_parent()
        assert not thumbnail_engine._processor_lock.locked()
        assert not FastImageProcessor._backend_lock.locked()


# ===========================================================================
# Shared all-white detector
# ===========================================================================


class TestAllWhiteDetector(TestCase):
    """is_all_white_thumbnail / _is_suspect_all_white behavior."""

    def test_all_white_rgb_jpeg_detected(self):
        """A solid white RGB JPEG is detected as all-white."""
        assert is_all_white_thumbnail(_jpeg_bytes((255, 255, 255))) is True

    def test_all_white_grayscale_jpeg_detected(self):
        """A solid white L-mode JPEG is detected as all-white."""
        assert is_all_white_thumbnail(_jpeg_bytes(255, mode="L")) is True

    def test_normal_image_not_detected(self):
        """An image with varied pixel content is not all-white."""
        assert is_all_white_thumbnail(_gradient_jpeg_bytes()) is False

    def test_solid_black_not_detected(self):
        """A solid black image is not all-white."""
        assert is_all_white_thumbnail(_jpeg_bytes((0, 0, 0))) is False

    def test_none_and_empty_blobs_are_false(self):
        """None/empty blobs are treated as not-all-white, not an error."""
        assert is_all_white_thumbnail(None) is False
        assert is_all_white_thumbnail(b"") is False

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

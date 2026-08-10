"""Tests for the framework-independent thumbnail engine.

These tests import nothing from Django and touch no database — they exercise
the engine exactly as an external consumer of the library would. The Django
integration tests live in ``thumbnails/tests/test_thumbnail_engine.py``.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from thumbnails import engine as engine_pkg
from thumbnails.engine import (
    FastImageProcessor,
    clear_backend_caches,
    config,
    is_all_white_thumbnail,
)
from thumbnails.engine.engine import (
    _check_core_image_available,
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


@pytest.fixture(name="clean_caches")
def _clean_caches():
    """Clear backend/processor caches around a test so instances never leak."""
    clear_backend_caches(force_gc=False)
    yield
    clear_backend_caches(force_gc=False)


@pytest.fixture(name="mac_optimizations")
def _mac_optimizations():
    """Return a setter for config.macintosh_optimizations that restores the original."""
    original = config.macintosh_optimizations

    def _set(value: bool) -> None:
        config.macintosh_optimizations = value

    yield _set
    config.macintosh_optimizations = original


# ===========================================================================
# macintosh_optimizations gating in _create_backend
# ===========================================================================


@pytest.mark.usefixtures("clean_caches")
class TestMacintoshOptimizationsGate:
    """The auto-selecting backend cases honor config.macintosh_optimizations."""

    def test_helper_reads_config_false(self, mac_optimizations):
        """Helper returns False when the config flag is False."""
        mac_optimizations(False)
        assert macintosh_optimizations_enabled() is False

    def test_helper_reads_config_true(self, mac_optimizations):
        """Helper returns True when the config flag is True."""
        mac_optimizations(True)
        assert macintosh_optimizations_enabled() is True

    def test_auto_resolves_to_pil_when_disabled(self, mac_optimizations):
        """backend="auto" uses PIL when the optimizations are disabled."""
        mac_optimizations(False)
        assert FastImageProcessor(IMAGE_SIZES, backend="auto").current_backend == "ImageBackend"

    def test_corevideo_falls_back_to_ffmpeg_when_disabled(self, mac_optimizations):
        """backend="corevideo" uses FFmpeg when the optimizations are disabled."""
        mac_optimizations(False)
        assert FastImageProcessor(IMAGE_SIZES, backend="corevideo").current_backend == "VideoBackend"

    def test_pdf_falls_back_to_pymupdf_when_disabled(self, mac_optimizations):
        """backend="pdf" uses PyMuPDF when the optimizations are disabled."""
        mac_optimizations(False)
        assert FastImageProcessor(IMAGE_SIZES, backend="pdf").current_backend == "PDFBackend"

    @pytest.mark.skipif(
        not (_check_core_image_available() and is_apple_silicon()),
        reason="Core Image backend requires Apple Silicon macOS with pyobjc",
    )
    def test_auto_uses_coreimage_when_enabled(self, mac_optimizations):
        """backend="auto" selects Core Image when enabled on Apple Silicon."""
        mac_optimizations(True)
        assert FastImageProcessor(IMAGE_SIZES, backend="auto").current_backend == "CoreImageBackend"

    def test_explicit_image_backend_unaffected_by_config(self, mac_optimizations):
        """Explicit backend="image" is never redirected by the config flag."""
        mac_optimizations(True)
        assert FastImageProcessor(IMAGE_SIZES, backend="image").current_backend == "ImageBackend"


# ===========================================================================
# os.register_at_fork hooks
# ===========================================================================


@pytest.mark.usefixtures("clean_caches")
class TestForkHooks:
    """The fork hooks reset caches/locks so a forked child cannot deadlock or
    reuse a backend whose Metal ports died with the parent."""

    def test_fork_reset_child_clears_caches_and_replaces_locks(self):
        """Child hook empties both caches and installs fresh lock objects."""
        engine_pkg.engine._processor_cache["sentinel"] = object()
        FastImageProcessor._backend_cache["sentinel"] = object()
        old_processor_lock = engine_pkg.engine._processor_lock
        old_backend_lock = FastImageProcessor._backend_lock

        engine_pkg.engine._fork_reset_child()

        assert not engine_pkg.engine._processor_cache
        assert not FastImageProcessor._backend_cache
        assert engine_pkg.engine._processor_lock is not old_processor_lock
        assert FastImageProcessor._backend_lock is not old_backend_lock
        assert not engine_pkg.engine._processor_lock.locked()
        assert not FastImageProcessor._backend_lock.locked()

    def test_fork_acquire_then_parent_release_leaves_locks_free(self):
        """before + after_in_parent hooks are a balanced acquire/release pair."""
        engine_pkg.engine._fork_acquire_locks()
        assert engine_pkg.engine._processor_lock.locked()
        assert FastImageProcessor._backend_lock.locked()

        engine_pkg.engine._fork_release_locks_parent()
        assert not engine_pkg.engine._processor_lock.locked()
        assert not FastImageProcessor._backend_lock.locked()


# ===========================================================================
# Shared all-white detector
# ===========================================================================


class TestAllWhiteDetector:
    """is_all_white_thumbnail behavior."""

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

    def test_memoryview_accepted(self):
        """A memoryview (as read from a binary column) decodes the same as bytes."""
        assert is_all_white_thumbnail(memoryview(_jpeg_bytes((255, 255, 255)))) is True

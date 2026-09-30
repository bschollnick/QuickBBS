"""Tests for the framework-independent thumbnail engine.

These tests import nothing from Django and touch no database — they exercise
the engine exactly as an external consumer of the library would. The Django
integration tests live in ``thumbnails/tests/test_thumbnail_engine.py``.
"""

from __future__ import annotations

import io
from typing import ClassVar

import pytest
from PIL import Image

from thumbnails import engine as engine_pkg
from thumbnails.engine import (
    FastImageProcessor,
    PDFProcessingError,
    ThumbnailResult,
    UnsupportedFormatError,
    VideoProcessingError,
    clear_backend_caches,
    config,
    create_thumbnails_from_bytes,
    create_thumbnails_from_path,
    get_video_info,
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


# These tests exercise the engine's private fork hooks, caches and locks directly.
@pytest.mark.usefixtures("clean_caches")
class TestForkHooks:  # pylint: disable=protected-access
    """The fork hooks reset caches/locks so a forked child cannot deadlock or
    reuse a backend whose Metal ports died with the parent."""

    def test_fork_reset_child_clears_caches_and_replaces_locks(self):
        """Child hook empties both caches and installs fresh lock objects."""
        engine_pkg.engine._processor_cache["sentinel"] = object()
        engine_pkg.engine._backend_cache["sentinel"] = object()
        old_processor_lock = engine_pkg.engine._processor_lock
        old_backend_lock = engine_pkg.engine._backend_lock

        engine_pkg.engine._fork_reset_child()

        assert not engine_pkg.engine._processor_cache
        assert not engine_pkg.engine._backend_cache
        assert engine_pkg.engine._processor_lock is not old_processor_lock
        assert engine_pkg.engine._backend_lock is not old_backend_lock
        assert not engine_pkg.engine._processor_lock.locked()
        assert not engine_pkg.engine._backend_lock.locked()

    def test_fork_acquire_then_parent_release_leaves_locks_free(self):
        """before + after_in_parent hooks are a balanced acquire/release pair."""
        engine_pkg.engine._fork_acquire_locks()
        assert engine_pkg.engine._processor_lock.locked()
        assert engine_pkg.engine._backend_lock.locked()

        engine_pkg.engine._fork_release_locks_parent()
        assert not engine_pkg.engine._processor_lock.locked()
        assert not engine_pkg.engine._backend_lock.locked()


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


class TestThumbnailResult:
    """Every backend answers a `ThumbnailResult`: images by size name, plus format."""

    SIZES: ClassVar[dict[str, tuple[int, int]]] = {"small": (32, 32), "large": (64, 64)}

    def _png(self) -> bytes:
        """Return a 200x100 red PNG."""
        buffer = io.BytesIO()
        Image.new("RGB", (200, 100), "red").save(buffer, format="PNG")
        return buffer.getvalue()

    def test_an_image_gives_images_by_size_and_its_format(self):
        """An image backend returns one JPEG per size name and no duration."""
        result = create_thumbnails_from_bytes(self._png(), self.SIZES, output="JPEG", backend="image")
        assert isinstance(result, ThumbnailResult)
        assert sorted(result.images) == ["large", "small"]
        assert all(image[:3] == b"\xff\xd8\xff" for image in result.images.values())
        assert result.format == "JPEG"
        assert result.duration is None

    def test_a_pdf_gives_the_same_result(self):
        """A PDF backend returns the same result as an image backend."""
        pymupdf = pytest.importorskip("pymupdf")
        document = pymupdf.open()
        document.new_page(width=200, height=100)
        result = create_thumbnails_from_bytes(document.tobytes(), self.SIZES, output="PNG", backend="pymupdf")
        assert isinstance(result, ThumbnailResult)
        assert sorted(result.images) == ["large", "small"]
        assert result.format == "PNG"
        assert result.duration is None


class TestBackendSelection:
    """Each selector picks the backend its rule names; "auto" survives a failed construction."""

    @pytest.fixture
    def macos(self, monkeypatch):
        """Return a setter that fakes the machine's macOS acceleration, framework availability and CPU."""

        def set_machine(*, optimized: bool, available: bool, apple_silicon: bool) -> None:
            monkeypatch.setattr(engine_pkg.engine, "macintosh_optimizations_enabled", lambda: optimized)
            for check in ("_check_core_image_available", "_check_avfoundation_available", "_check_pdfkit_available"):
                monkeypatch.setattr(engine_pkg.engine, check, lambda: available)
            monkeypatch.setattr(engine_pkg.engine, "is_apple_silicon", lambda: apple_silicon)

        return set_machine

    @pytest.mark.parametrize(
        ("selector", "on_accelerated_mac", "elsewhere"),
        [
            ("auto", "coreimage", "image"),
            ("corevideo", "corevideo", "video"),
            ("pdf", "pdfkit", "pymupdf"),
            ("pdfkit", "pdfkit", "pymupdf"),
            ("image", "image", "image"),
            ("video", "video", "video"),
            ("pymupdf", "pymupdf", "pymupdf"),
        ],
    )
    def test_a_selector_chooses_by_machine(self, macos, selector, on_accelerated_mac, elsewhere):
        """A selector names the accelerated backend on an Apple Silicon Mac and the portable one elsewhere."""
        macos(optimized=True, available=True, apple_silicon=True)
        assert engine_pkg.engine._BACKEND_RULES[selector]() == on_accelerated_mac  # pylint: disable=protected-access
        macos(optimized=False, available=False, apple_silicon=False)
        assert engine_pkg.engine._BACKEND_RULES[selector]() == elsewhere  # pylint: disable=protected-access

    def test_an_explicit_core_image_request_raises_when_unavailable(self, macos):
        """Asking for "coreimage" by name raises ImportError when Core Image is missing."""
        macos(optimized=True, available=False, apple_silicon=True)
        with pytest.raises(ImportError):
            FastImageProcessor({"small": (8, 8)}, backend="coreimage")._create_backend()  # pylint: disable=protected-access

    def test_auto_falls_back_to_pil_when_core_image_cannot_start(self, macos, monkeypatch):
        """ "auto" uses the PIL backend when the Core Image backend raises during construction."""
        macos(optimized=True, available=True, apple_silicon=True)
        real_class = engine_pkg.engine._backend_class  # pylint: disable=protected-access

        def no_metal_device():
            raise RuntimeError("no Metal device")

        monkeypatch.setattr(engine_pkg.engine, "_backend_class", lambda name: no_metal_device if name == "coreimage" else real_class(name))
        backend = FastImageProcessor({"small": (8, 8)}, backend="auto")._create_backend()  # pylint: disable=protected-access
        assert type(backend).__name__ == "ImageBackend"

    def test_an_unknown_selector_is_refused(self):
        """An unrecognised backend name raises UnsupportedFormatError."""
        with pytest.raises(UnsupportedFormatError):
            FastImageProcessor({"small": (8, 8)}, backend="bogus")  # type: ignore[arg-type]


class TestPDFBackendErrors:
    """PyMuPDF failures surface as the engine's own exceptions."""

    def test_unreadable_bytes_raise_pdf_processing_error(self):
        """Bytes that are not a PDF raise PDFProcessingError."""
        pytest.importorskip("pymupdf")
        with pytest.raises(PDFProcessingError):
            create_thumbnails_from_bytes(b"not a pdf", {"small": (8, 8)}, output="PNG", backend="pymupdf")

    def test_a_missing_file_raises_file_not_found(self, tmp_path):
        """A path that does not exist raises FileNotFoundError."""
        pytest.importorskip("pymupdf")
        with pytest.raises(FileNotFoundError):
            create_thumbnails_from_path(str(tmp_path / "missing.pdf"), {"small": (8, 8)}, output="PNG", backend="pymupdf")


class TestVideoInfoFallback:
    """`get_video_info` retries with the ffmpeg probe when the platform probe cannot read a file."""

    @staticmethod
    def _no_video_tracks(path: str) -> dict:
        raise VideoProcessingError("No video tracks found in file", file_path=path)

    @staticmethod
    def _ffmpeg_probe(path: str) -> dict:
        return {"duration": 2.0, "path": path}

    def test_a_platform_probe_failure_falls_back_to_ffmpeg(self, monkeypatch):
        """A MediaProcessingError from AVFoundation is retried with ffmpeg."""
        monkeypatch.setattr(engine_pkg.engine, "_resolve_video_info_impl", lambda: self._no_video_tracks)
        monkeypatch.setattr(engine_pkg.engine, "_ffmpeg_video_info", lambda: self._ffmpeg_probe)
        assert get_video_info("clip.wmv") == {"duration": 2.0, "path": "clip.wmv"}

    def test_an_ffmpeg_failure_is_raised(self, monkeypatch):
        """When the resolved probe already is ffmpeg, its error propagates."""
        monkeypatch.setattr(engine_pkg.engine, "_resolve_video_info_impl", lambda: self._no_video_tracks)
        monkeypatch.setattr(engine_pkg.engine, "_ffmpeg_video_info", lambda: self._no_video_tracks)
        with pytest.raises(VideoProcessingError):
            get_video_info("broken.mp4")


def test_core_image_raises_file_not_found_for_a_missing_file(tmp_path):
    """Core Image reports a missing file as FileNotFoundError, like every other backend."""
    if not _check_core_image_available():
        pytest.skip("Core Image is not available")
    with pytest.raises(FileNotFoundError):
        create_thumbnails_from_path(str(tmp_path / "missing.png"), {"small": (8, 8)}, output="PNG", backend="coreimage")

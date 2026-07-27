"""Pure-function unit tests for frontend/serve_up.py — no DB, no Django Client."""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest
from django.test import SimpleTestCase

from frontend.serve_up import (
    SizedFileWrapper,
    _parse_range_header,
    _safe_join,
    open_sized_file,
)

pytestmark = pytest.mark.api


class TestParseRangeHeader(SimpleTestCase):
    """Tests for _parse_range_header."""

    def test_no_header_returns_none(self):
        """Empty header string returns None."""
        assert _parse_range_header("", 1000) is None

    def test_missing_bytes_prefix_returns_none(self):
        """Header not starting with 'bytes=' is rejected."""
        assert _parse_range_header("items=0-10", 1000) is None

    def test_multi_range_rejected(self):
        """Comma-separated multi-range requests are not supported."""
        assert _parse_range_header("bytes=0-10,20-30", 1000) is None

    def test_simple_range(self):
        """A standard 'bytes=start-end' range returns the half-open interval."""
        assert _parse_range_header("bytes=0-99", 1000) == (0, 100)

    def test_open_ended_range(self):
        """A range with no end (bytes=N-) extends to file_size."""
        assert _parse_range_header("bytes=500-", 1000) == (500, 1000)

    def test_suffix_range(self):
        """Suffix form 'bytes=-N' returns the last N bytes of the file."""
        assert _parse_range_header("bytes=-100", 1000) == (900, 1000)

    def test_malformed_range_returns_none(self):
        """Non-numeric range values return None."""
        assert _parse_range_header("bytes=abc-def", 1000) is None

    def test_start_beyond_file_size_returns_none(self):
        """A start position at or beyond file_size is unsatisfiable."""
        assert _parse_range_header("bytes=1000-1100", 1000) is None

    def test_start_after_stop_returns_none(self):
        """A start position at or after the computed stop is unsatisfiable."""
        assert _parse_range_header("bytes=500-100", 1000) is None

    def test_stop_clamped_to_file_size(self):
        """A requested end beyond file_size is clamped to file_size."""
        assert _parse_range_header("bytes=0-9999", 1000) == (0, 1000)

    def test_negative_start_returns_none(self):
        """A negative start (suffix longer than the file) returns None."""
        assert _parse_range_header("bytes=-9999", 1000) is None


class TestSafeJoin(SimpleTestCase):
    """Tests for _safe_join — path-traversal guard."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.temp_dir, "sub"), exist_ok=True)
        with open(os.path.join(self.temp_dir, "sub", "file.txt"), "w", encoding="utf-8") as f:
            f.write("hello")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_plain_relative_path_resolves(self):
        """A simple relative path under base resolves to the joined path."""
        result = _safe_join(self.temp_dir, "sub/file.txt")
        assert result == os.path.realpath(os.path.join(self.temp_dir, "sub", "file.txt"))

    def test_traversal_outside_base_returns_none(self):
        """A '../' sequence that escapes base returns None."""
        result = _safe_join(self.temp_dir, "../../../../etc/passwd")
        assert result is None

    def test_traversal_within_base_resolves(self):
        """A '../' sequence that stays inside base still resolves normally."""
        result = _safe_join(self.temp_dir, "sub/../sub/file.txt")
        assert result == os.path.realpath(os.path.join(self.temp_dir, "sub", "file.txt"))

    def test_base_itself_resolves(self):
        """An empty relative path resolves to base itself."""
        result = _safe_join(self.temp_dir, "")
        assert result == os.path.realpath(self.temp_dir)


class TestSizedFileWrapper(SimpleTestCase):
    """Tests for SizedFileWrapper delegation."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.file_path = os.path.join(self.temp_dir, "data.bin")
        with open(self.file_path, "wb") as f:
            f.write(b"0123456789")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_size_precomputed(self):
        """The wrapper exposes the OS-reported size without reading the file."""
        with open(self.file_path, "rb") as fh:
            wrapper = SizedFileWrapper(fh, 10)
            assert wrapper.size == 10

    def test_read_delegates(self):
        """read() delegates to the wrapped file handle."""
        with open(self.file_path, "rb") as fh:
            wrapper = SizedFileWrapper(fh, 10)
            assert wrapper.read(4) == b"0123"

    def test_seek_and_tell_delegate(self):
        """seek()/tell() delegate to the wrapped file handle."""
        with open(self.file_path, "rb") as fh:
            wrapper = SizedFileWrapper(fh, 10)
            wrapper.seek(5)
            assert wrapper.tell() == 5
            assert wrapper.read() == b"56789"

    def test_iter_delegates(self):
        """__iter__ delegates to the wrapped file handle."""
        with open(self.file_path, "rb") as fh:
            wrapper = SizedFileWrapper(fh, 10)
            chunks = list(iter(wrapper))
            assert b"".join(chunks) == b"0123456789"

    def test_close_delegates(self):
        """close() delegates to and actually closes the wrapped file handle."""
        fh = open(self.file_path, "rb")  # pylint: disable=consider-using-with
        wrapper = SizedFileWrapper(fh, 10)
        wrapper.close()
        assert fh.closed


class TestOpenSizedFile(SimpleTestCase):
    """Tests for open_sized_file."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.file_path = os.path.join(self.temp_dir, "data.bin")
        with open(self.file_path, "wb") as f:
            f.write(b"x" * 42)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_returns_wrapper_with_correct_size(self):
        """open_sized_file returns a SizedFileWrapper with size from os.fstat."""
        wrapper = open_sized_file(self.file_path)
        try:
            assert isinstance(wrapper, SizedFileWrapper)
            assert wrapper.size == 42
        finally:
            wrapper.close()

    def test_returns_readable_handle(self):
        """The wrapped handle can be read from."""
        wrapper = open_sized_file(self.file_path)
        try:
            assert wrapper.read() == b"x" * 42
        finally:
            wrapper.close()

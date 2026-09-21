"""Pure-function unit tests for frontend/serve_up.py — no DB, no Django Client."""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest
from django.test import RequestFactory, SimpleTestCase

from frontend.serve_up import (
    SizedFileWrapper,
    _parse_range_header,
    _safe_join,
    open_sized_file,
    send_file_response,
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


class TestRangedFileResponse(SimpleTestCase):
    """Ranged downloads through `send_file_response`.

    A media player asks for byte ranges rather than the whole file, so a
    wrong offset or length here is a video that will not seek. These
    drive the real response and read the bytes back, rather than testing
    the header parser alone.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.file_path = os.path.join(self.temp_dir, "clip.bin")
        # 1024 bytes whose value at every offset is known, so a returned
        # slice can be compared against the exact expected bytes.
        self.data = bytes(range(256)) * 4
        with open(self.file_path, "wb") as handle:
            handle.write(self.data)
        self.factory = RequestFactory()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _send(self, range_header: str | None):
        """Return the response for one request, with or without a Range."""
        extra = {"HTTP_RANGE": range_header} if range_header else {}
        return send_file_response(
            "clip.bin",
            open(self.file_path, "rb"),  # the response closes it
            "application/octet-stream",
            False,
            request=self.factory.get("/media/clip.bin", **extra),
        )

    @staticmethod
    def _body(response) -> bytes:
        return b"".join(response.streaming_content)

    def test_no_range_header_sends_the_whole_file(self):
        """Without a Range header the response is an ordinary 200."""
        response = self._send(None)
        assert response.status_code == 200
        assert self._body(response) == self.data

    def test_a_leading_range_returns_exactly_those_bytes(self):
        """`bytes=0-99` returns the first 100 bytes, not 99 or 101."""
        response = self._send("bytes=0-99")
        assert response.status_code == 206
        assert response["Content-Range"] == f"bytes 0-99/{len(self.data)}"
        assert response["Content-Length"] == "100"
        assert self._body(response) == self.data[0:100]

    def test_a_mid_file_range_returns_the_right_slice(self):
        """A range starting inside the file seeks rather than re-reading."""
        response = self._send("bytes=100-199")
        assert response.status_code == 206
        assert response["Content-Range"] == f"bytes 100-199/{len(self.data)}"
        assert self._body(response) == self.data[100:200]

    def test_an_open_ended_range_runs_to_the_end(self):
        """`bytes=500-` sends everything from 500 onwards."""
        response = self._send("bytes=500-")
        assert response.status_code == 206
        assert response["Content-Range"] == f"bytes 500-1023/{len(self.data)}"
        assert self._body(response) == self.data[500:]

    def test_a_suffix_range_returns_the_final_bytes(self):
        """`bytes=-100` means the LAST 100 bytes, not the first 100."""
        response = self._send("bytes=-100")
        assert response.status_code == 206
        assert response["Content-Range"] == f"bytes 924-1023/{len(self.data)}"
        assert self._body(response) == self.data[-100:]

    def test_a_single_byte_range_is_one_byte(self):
        """`bytes=0-0` is a one-byte range, the form a player uses to probe."""
        response = self._send("bytes=0-0")
        assert response.status_code == 206
        assert response["Content-Length"] == "1"
        assert self._body(response) == self.data[0:1]

    def test_a_range_past_the_end_is_refused(self):
        """A range starting beyond the file answers 416, not 206."""
        response = self._send("bytes=5000-6000")
        assert response.status_code == 416

    def test_a_ranged_response_advertises_range_support(self):
        """`Accept-Ranges: bytes` is what tells a player it may seek."""
        response = self._send("bytes=0-99")
        assert response["Accept-Ranges"] == "bytes"

    def test_the_ranges_reassemble_into_the_original_file(self):
        """Consecutive ranges cover the file exactly once, with no gap or
        overlap -- which is what a resumed download depends on."""
        first = self._body(self._send("bytes=0-511"))
        second = self._body(self._send("bytes=512-1023"))
        assert first + second == self.data

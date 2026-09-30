"""SHA256 hashing on the shared thread pool agrees with hashing one file at a time."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.test import override_settings

from quickbbs.common import _SHA_EXECUTOR, _batch_compute_file_shas, get_file_sha

pytestmark = pytest.mark.api


@override_settings(SHA256_PARALLEL_THRESHOLD=2)
def test_the_pool_hashes_exactly_as_one_at_a_time(tmp_path: Path) -> None:
    paths = []
    for index in range(6):
        path = tmp_path / f"file_{index}.bin"
        path.write_bytes(bytes([index]) * (1000 + index))
        paths.append(str(path))

    assert _batch_compute_file_shas(paths) == {path: get_file_sha(path) for path in paths}


def test_a_shut_down_pool_is_recreated_on_next_use() -> None:
    first = _SHA_EXECUTOR.get()
    _SHA_EXECUTOR.shutdown()
    second = _SHA_EXECUTOR.get()
    assert second is not first
    assert second.submit(sum, [1, 2]).result() == 3

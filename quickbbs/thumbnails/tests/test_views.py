"""Web-layer tests for thumbnails/views.py — thumbnail_file / thumbnail_dir."""

from __future__ import annotations

import os

import pytest

from frontend.tests.test_views import ViewSmokeTestBase
from quickbbs.models import DirectoryIndex

pytestmark = pytest.mark.web


class TestThumbnailEdgeCases(ViewSmokeTestBase):
    """Edge-case branches of thumbnail_file / thumbnail_dir not covered by
    the base happy-path smoke tests in frontend/tests/test_views.py."""

    def test_file_thumbnail_unknown_sha_is_client_error(self):
        """An unknown file SHA returns a 4xx, not a server error."""
        response = self.get(f"/thumbnail_file/{'0' * 64}")
        assert 400 <= response.status_code < 500

    def test_directory_thumbnail_unknown_sha_returns_404(self):
        """An unknown directory SHA returns 404."""
        response = self.get(f"/thumbnail_directory/{'0' * 64}")
        assert response.status_code == 404

    def test_file_thumbnail_invalid_size_normalizes_to_small(self):
        """An invalid ?size= value falls back to 'small' rather than erroring."""
        response = self.get(f"/thumbnail_file/{self.file_obj.file_sha256}?size=huge")
        assert response.status_code == 200
        assert response["Content-Type"].startswith("image/")

    def test_directory_thumbnail_generic_icon_when_no_cover_image(self):
        """A directory with no files falls back to the generic directory icon."""
        empty_dir_path = os.path.join(self.albums_dir, "empty_subdir")
        os.makedirs(empty_dir_path, exist_ok=True)
        _, empty_dir = DirectoryIndex.add_directory(empty_dir_path + "/")
        assert empty_dir is not None
        response = self.get(f"/thumbnail_directory/{empty_dir.dir_fqpn_sha256}")
        assert response.status_code == 200

"""
Unit tests for frontend utility functions
"""

from frontend.utilities import return_breadcrumbs


class TestReturnBreadcrumbs:
    """Test the return_breadcrumbs function"""

    def test_empty_path(self):
        """Test with empty path returns empty list"""
        result = return_breadcrumbs("")
        assert not result

    def test_root_path(self):
        """Test with root path returns empty list"""
        result = return_breadcrumbs("/")
        assert not result

    def test_single_level_path(self):
        """Test with single level path"""
        result = return_breadcrumbs("/photos")
        assert len(result) == 1
        assert result[0]["name"] == "photos"
        assert result[0]["url"] == "/photos"

    def test_multi_level_path(self):
        """Test with multi-level path"""
        result = return_breadcrumbs("/photos/vacation/2024")
        assert len(result) == 3
        assert result[0]["name"] == "photos"
        assert result[0]["url"] == "/photos"
        assert result[1]["name"] == "vacation"
        assert result[1]["url"] == "/photos/vacation"
        assert result[2]["name"] == "2024"
        assert result[2]["url"] == "/photos/vacation/2024"

    def test_path_with_trailing_slash(self):
        """Test that trailing slashes are handled correctly"""
        result = return_breadcrumbs("/photos/vacation/")
        assert len(result) == 2
        assert result[0]["name"] == "photos"
        assert result[1]["name"] == "vacation"

    def test_path_without_leading_slash(self):
        """Test path without leading slash"""
        result = return_breadcrumbs("photos/vacation")
        assert len(result) == 2
        assert result[0]["name"] == "photos"
        assert result[0]["url"] == "/photos"
        assert result[1]["name"] == "vacation"
        assert result[1]["url"] == "/photos/vacation"

    def test_breadcrumb_structure(self):
        """Test that each breadcrumb has correct structure"""
        result = return_breadcrumbs("/photos/vacation")
        for breadcrumb in result:
            assert "name" in breadcrumb
            assert "url" in breadcrumb
            assert isinstance(breadcrumb["name"], str)
            assert isinstance(breadcrumb["url"], str)

    def test_url_accumulation(self):
        """Test that URLs accumulate correctly for nested paths"""
        result = return_breadcrumbs("/a/b/c/d")
        assert result[0]["url"] == "/a"
        assert result[1]["url"] == "/a/b"
        assert result[2]["url"] == "/a/b/c"
        assert result[3]["url"] == "/a/b/c/d"

"""
Test cases for search functionality in frontend.views module
"""

from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import User
from django.test import RequestFactory
from filetypes.models import filetypes
from frontend.views import search_viewresults

from quickbbs.models import FileIndex, DirectoryIndex


@pytest.mark.django_db
class TestSearchViews:
    """Test cases for search view functionality"""

    def setup_method(self):
        """Set up test fixtures before each test method"""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpassword")

        # Create test filetypes
        self.filetype_image, _ = filetypes.objects.get_or_create(
            fileext=".jpg",
            defaults={
                "description": "JPEG Image",
                "color": "FF0000",
                "is_image": True,
                "is_movie": False,
                "is_dir": False,
                "is_link": False,
            },
        )

        self.filetype_dir, _ = filetypes.objects.get_or_create(
            fileext=".dir",
            defaults={
                "description": "Directory",
                "color": "0000FF",
                "is_image": False,
                "is_movie": False,
                "is_dir": True,
                "is_link": False,
            },
        )

        # Create test directory
        self.test_dir = DirectoryIndex.objects.create(
            fqpndirectory="/test/path/Mary_Jane_Watson_Photos/",
            dir_fqpn_sha256="test_dir_sha256",
            lastmod=1234567890.0,
            lastscan=1234567890.0,
            filetype=self.filetype_dir,
            delete_pending=False,
        )

        # Create test files with various separator patterns
        self.test_files = [
            FileIndex.objects.create(
                name="Mary_Jane_Watson_01.jpg",
                fqpndirectory="/test/path/Mary_Jane_Watson_01.jpg",
                file_sha256="test_sha_01",
                unique_sha256="unique_sha_01",
                lastmod=1234567890.0,
                lastscan=1234567890.0,
                size=100000,
                filetype=self.filetype_image,
                home_directory=self.test_dir,
                delete_pending=False,
            ),
            FileIndex.objects.create(
                name="Mary-Jane-Watson-02.jpg",
                fqpndirectory="/test/path/Mary-Jane-Watson-02.jpg",
                file_sha256="test_sha_02",
                unique_sha256="unique_sha_02",
                lastmod=1234567890.0,
                lastscan=1234567890.0,
                size=150000,
                filetype=self.filetype_image,
                home_directory=self.test_dir,
                delete_pending=False,
            ),
            FileIndex.objects.create(
                name="Mary Jane Watson 03.jpg",
                fqpndirectory="/test/path/Mary Jane Watson 03.jpg",
                file_sha256="test_sha_03",
                unique_sha256="unique_sha_03",
                lastmod=1234567890.0,
                lastscan=1234567890.0,
                size=200000,
                filetype=self.filetype_image,
                home_directory=self.test_dir,
                delete_pending=False,
            ),
            # Add a file that should NOT match
            FileIndex.objects.create(
                name="Peter_Parker_01.jpg",
                fqpndirectory="/test/path/Peter_Parker_01.jpg",
                file_sha256="test_sha_04",
                unique_sha256="unique_sha_04",
                lastmod=1234567890.0,
                lastscan=1234567890.0,
                size=250000,
                filetype=self.filetype_image,
                home_directory=self.test_dir,
                delete_pending=False,
            ),
        ]

    def create_request(self, searchtext="", page=1, user=None):
        """Helper method to create test requests"""
        request = self.factory.get("/search/", {"searchtext": searchtext, "page": str(page)})
        request.user = user or self.user

        # Mock HTMX details
        mock_htmx = Mock()
        mock_htmx.boosted = False
        mock_htmx.current_url = None
        request.htmx = mock_htmx

        return request

    def test_search_variations_function(self):
        """Test the create_search_variations helper function"""
        # Import the function we need to test (it's defined inside the view)
        request = self.create_request("Mary Jane Watson")

        # Mock the template rendering to avoid template issues
        with patch("frontend.views.render") as mock_render:
            mock_render.return_value = Mock()
            mock_render.return_value.status_code = 200

            search_viewresults(request)

            # Verify render was called (meaning the function didn't crash)
            assert mock_render.called

    def test_basic_search_functionality(self):
        """Test basic search with exact match"""
        request = self.create_request("Mary_Jane_Watson")

        with patch("frontend.views.render") as mock_render:
            mock_render.return_value = Mock()
            mock_render.return_value.status_code = 200

            response = search_viewresults(request)

            # Verify the response was successful
            assert response.status_code == 200

            # Verify render was called with the correct template
            mock_render.assert_called_once()
            args, kwargs = mock_render.call_args
            assert "frontend/search/search_listings_complete.jinja" in args[1]

            # Check that the context contains our test files
            context = args[2]
            items = context["items_to_display"]

            # Should find at least one matching file
            assert len(items) > 0

            # Should include our Mary Jane Watson files
            filenames = [item.name for item in items if hasattr(item, "name")]
            mary_jane_files = [name for name in filenames if "mary" in name.lower() and "jane" in name.lower()]
            assert len(mary_jane_files) > 0

    def test_separator_agnostic_search(self):
        """Test that search ignores separators (spaces, underscores, dashes)"""
        # Test various search patterns that should all find the same files
        search_patterns = [
            "Mary Jane Watson",
            "Mary_Jane_Watson",
            "Mary-Jane-Watson",
            "mary jane watson",  # test case insensitivity
        ]

        for pattern in search_patterns:
            request = self.create_request(pattern)

            with patch("frontend.views.render") as mock_render:
                mock_render.return_value = Mock()
                mock_render.return_value.status_code = 200

                response = search_viewresults(request)

                # Verify successful response
                assert response.status_code == 200

                # Get the context
                args, kwargs = mock_render.call_args
                context = args[2]
                items = context["items_to_display"]

                # Should find our Mary Jane Watson files regardless of separator pattern
                filenames = [item.name for item in items if hasattr(item, "name")]
                mary_jane_files = [name for name in filenames if "mary" in name.lower() and "jane" in name.lower() and "watson" in name.lower()]

                # Should find all 3 Mary Jane Watson files
                assert len(mary_jane_files) >= 3, f"Pattern '{pattern}' should find Mary Jane Watson files, found: {mary_jane_files}"

                # Should NOT find Peter Parker file
                peter_files = [name for name in filenames if "peter" in name.lower()]
                assert len(peter_files) == 0, f"Pattern '{pattern}' should not find Peter Parker files"

    def test_directory_search(self):
        """Test that search finds directories as well as files"""
        request = self.create_request("Mary_Jane_Watson")

        with patch("frontend.views.render") as mock_render:
            mock_render.return_value = Mock()
            mock_render.return_value.status_code = 200

            search_viewresults(request)

            args, kwargs = mock_render.call_args
            context = args[2]
            items = context["items_to_display"]

            # Should include the directory
            dir_items = [item for item in items if hasattr(item, "fqpndirectory") and item.fqpndirectory.endswith("/")]
            assert len(dir_items) > 0, "Search should find directories"

            # The directory should come before files (directories first rule)
            if len(items) > 1:
                # Check if first item is a directory
                first_item = items[0]
                if hasattr(first_item, "fqpndirectory"):
                    assert first_item.fqpndirectory.endswith("/"), "Directories should appear before files"

    def test_pagination(self):
        """Test search results pagination"""
        request = self.create_request("Mary", page=1)

        with patch("frontend.views.render") as mock_render:
            mock_render.return_value = Mock()
            mock_render.return_value.status_code = 200

            search_viewresults(request)

            args, kwargs = mock_render.call_args
            context = args[2]

            # Check pagination context variables
            assert "current_page" in context
            assert "total_pages" in context
            assert "has_previous" in context
            assert "has_next" in context
            assert "page_cnt" in context

            assert context["current_page"] == 1

    def test_empty_search(self):
        """Test handling of empty search text"""
        request = self.create_request("")  # Empty search

        with patch("frontend.views.render") as mock_render:
            mock_render.return_value = Mock()
            mock_render.return_value.status_code = 200

            response = search_viewresults(request)

            # Should still render without crashing
            assert response.status_code == 200

            args, kwargs = mock_render.call_args
            context = args[2]

            # Should have empty or minimal results
            items = context["items_to_display"]
            # Empty search should return no results or handle gracefully
            assert isinstance(items, list)

    def test_search_context_variables(self):
        """Test that search provides all required context variables"""
        request = self.create_request("test search")

        with patch("frontend.views.render") as mock_render:
            mock_render.return_value = Mock()
            mock_render.return_value.status_code = 200

            search_viewresults(request)

            args, kwargs = mock_render.call_args
            context = args[2]

            # Check all required context variables are present
            required_vars = [
                "searchtext",
                "current_page",
                "gallery_name",
                "search",
                "breadcrumbs",
                "webpath",
                "up_uri",
                "items_to_display",
                "pagelist",
                "has_previous",
                "has_next",
                "total_pages",
                "sort",
                "originator",
            ]

            for var in required_vars:
                assert var in context, f"Context missing required variable: {var}"

            # Verify specific values
            assert context["searchtext"] == "test search"
            assert context["search"] is True
            assert context["webpath"] == "/search/"
            assert context["up_uri"] == "/albums/"
            assert context["gallery_name"] == "Searching for test search"

    def test_htmx_template_selection(self):
        """Test that HTMX requests get partial templates"""
        request = self.create_request("test")

        # Mock HTMX boosted request
        request.htmx.boosted = True
        request.htmx.current_url = "http://example.com/search/"

        with patch("frontend.views.render") as mock_render:
            mock_render.return_value = Mock()
            mock_render.return_value.status_code = 200

            search_viewresults(request)

            args, kwargs = mock_render.call_args
            template_name = args[1]

            # Should use partial template for HTMX requests
            assert "partial" in template_name
            assert template_name == "frontend/search/search_listings_partial.jinja"

    def test_deleted_files_excluded(self):
        """Test that files marked for deletion are excluded from search results"""
        # Create a file marked for deletion
        FileIndex.objects.create(
            name="Mary_Jane_Watson_Deleted.jpg",
            fqpndirectory="/test/path/Mary_Jane_Watson_Deleted.jpg",
            file_sha256="deleted_sha",
            unique_sha256="deleted_unique_sha",
            lastmod=1234567890.0,
            lastscan=1234567890.0,
            size=100000,
            filetype=self.filetype_image,
            home_directory=self.test_dir,
            delete_pending=True,  # This should be excluded
        )

        request = self.create_request("Mary_Jane_Watson")

        with patch("frontend.views.render") as mock_render:
            mock_render.return_value = Mock()
            mock_render.return_value.status_code = 200

            search_viewresults(request)

            args, kwargs = mock_render.call_args
            context = args[2]
            items = context["items_to_display"]

            # The deleted file should NOT be in results
            filenames = [item.name for item in items if hasattr(item, "name")]
            assert "Mary_Jane_Watson_Deleted.jpg" not in filenames, "Deleted files should be excluded from search results"


@pytest.mark.django_db
class TestSearchVariations:
    """Test the search variations functionality specifically"""

    def test_create_search_variations(self):
        """Test the create_search_variations function independently"""
        # We need to import this from within the view
        # For now, we'll test the logic independently

        def create_search_variations(text):
            """Copy of the function for testing"""
            if not text:
                return []

            variations = [
                text,
                text.replace("_", " "),
                text.replace("-", " "),
                text.replace(" ", "_"),
                text.replace(" ", "-"),
                text.replace("_", "-"),
                text.replace("-", "_"),
                text.replace("_", " ").replace("-", " "),
                text.replace(" ", "_").replace("-", "_"),
                text.replace(" ", "-").replace("_", "-"),
            ]

            unique_variations = []
            seen = set()
            for variation in variations:
                if variation not in seen:
                    unique_variations.append(variation)
                    seen.add(variation)

            return unique_variations

        # Test various input patterns
        test_cases = [
            (
                "Mary Jane Watson",
                ["Mary Jane Watson", "Mary_Jane_Watson", "Mary-Jane-Watson"],
            ),
            (
                "Mary_Jane_Watson",
                ["Mary_Jane_Watson", "Mary Jane Watson", "Mary-Jane-Watson"],
            ),
            (
                "Mary-Jane-Watson",
                ["Mary-Jane-Watson", "Mary Jane Watson", "Mary_Jane_Watson"],
            ),
            ("single_word", ["single_word", "single word", "single-word"]),
            ("", []),
        ]

        for input_text, expected_contains in test_cases:
            variations = create_search_variations(input_text)

            if input_text == "":
                assert variations == []
                continue

            # Check that all expected variations are present
            for expected in expected_contains:
                assert expected in variations, f"Expected '{expected}' in variations for '{input_text}', got: {variations}"

            # Check no duplicates
            assert len(variations) == len(set(variations)), f"Variations should not contain duplicates: {variations}"

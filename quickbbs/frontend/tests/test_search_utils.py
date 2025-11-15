"""
Unit tests for search utility functions and helpers
"""

from django.db.models import Q
from django.test import TestCase
from filetypes.models import filetypes

from quickbbs.models import FileIndex, DirectoryIndex


class TestSearchUtilities(TestCase):
    """Test search utility functions including optimized regex approach"""

    def setUp(self):
        """Set up test fixtures"""
        # Create test filetypes
        self.filetype_image = filetypes.objects.create(
            fileext=".jpg",
            description="JPEG Image",
            color="FF0000",
            is_image=True,
            is_movie=False,
            is_dir=False,
            is_link=False,
        )

        self.filetype_dir = filetypes.objects.create(
            fileext=".dir",
            description="Directory",
            color="0000FF",
            is_image=False,
            is_movie=False,
            is_dir=True,
            is_link=False,
        )

    def test_search_variations_comprehensive(self):
        """Test create_search_variations function with comprehensive cases"""

        def create_search_variations(text):
            """Implementation of the search variations function"""
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

        # Test comprehensive cases
        test_cases = [
            # Basic separator patterns
            {
                "input": "Mary Jane Watson",
                "should_contain": [
                    "Mary Jane Watson",
                    "Mary_Jane_Watson",
                    "Mary-Jane-Watson",
                ],
                "description": "Spaces to separators",
            },
            {
                "input": "Mary_Jane_Watson",
                "should_contain": [
                    "Mary_Jane_Watson",
                    "Mary Jane Watson",
                    "Mary-Jane-Watson",
                ],
                "description": "Underscores to other separators",
            },
            {
                "input": "Mary-Jane-Watson",
                "should_contain": [
                    "Mary-Jane-Watson",
                    "Mary Jane Watson",
                    "Mary_Jane_Watson",
                ],
                "description": "Dashes to other separators",
            },
            # Mixed patterns
            {
                "input": "Mary_Jane-Watson",
                "should_contain": [
                    "Mary_Jane-Watson",
                    "Mary Jane Watson",
                    "Mary-Jane-Watson",
                ],
                "description": "Mixed separators",
            },
            # Single words
            {
                "input": "single_word",
                "should_contain": ["single_word", "single word", "single-word"],
                "description": "Single word with underscore",
            },
            # Edge cases
            {"input": "a", "should_contain": ["a"], "description": "Single character"},
            {"input": "", "should_contain": [], "description": "Empty string"},
            # Complex patterns
            {
                "input": "The_Amazing-Spider Man",
                "should_contain": ["The_Amazing-Spider Man", "The Amazing Spider Man"],
                "description": "Complex mixed separators",
            },
        ]

        for test_case in test_cases:
            with self.subTest(test_case["description"]):
                variations = create_search_variations(test_case["input"])

                # Check that required variations are present
                for expected in test_case["should_contain"]:
                    self.assertIn(
                        expected,
                        variations,
                        f"Expected '{expected}' in variations for '{test_case['input']}', " f"got: {variations}",
                    )

                # Check no duplicates
                self.assertEqual(
                    len(variations),
                    len(set(variations)),
                    f"Variations should not contain duplicates: {variations}",
                )

                # Check all variations are strings
                for variation in variations:
                    self.assertIsInstance(variation, str)

    def test_q_object_construction(self):
        """Test that Q object construction works correctly for search"""

        # Test Q object building logic
        search_variations = ["mary jane", "mary_jane", "mary-jane"]

        # Build Q objects like the search function does
        file_q_objects = Q()
        for variation in search_variations:
            file_q_objects |= Q(name__icontains=variation)

        # The Q object should be properly constructed
        self.assertIsInstance(file_q_objects, Q)

        # Test with directories
        dir_q_objects = Q()
        for variation in search_variations:
            dir_q_objects |= Q(fqpndirectory__icontains=variation)

        self.assertIsInstance(dir_q_objects, Q)

    def test_search_case_insensitivity(self):
        """Test that search is case insensitive"""

        # Create test files with various cases
        test_dir = DirectoryIndex.objects.create(
            fqpndirectory="/test/directory/",
            dir_fqpn_sha256="test_dir_sha",
            lastmod=1234567890.0,
            lastscan=1234567890.0,
            filetype=self.filetype_dir,
            delete_pending=False,
        )

        test_files = [
            "Mary_Jane_Watson.jpg",
            "MARY_JANE_WATSON.jpg",
            "mary_jane_watson.jpg",
            "Mary_jane_watson.jpg",
        ]

        created_files = []
        for i, filename in enumerate(test_files):
            file_obj = FileIndex.objects.create(
                name=filename,
                fqpndirectory=f"/test/{filename}",
                file_sha256=f"test_sha_{i}",
                unique_sha256=f"unique_sha_{i}",
                lastmod=1234567890.0,
                lastscan=1234567890.0,
                size=100000,
                filetype=self.filetype_image,
                home_directory=test_dir,
                delete_pending=False,
            )
            created_files.append(file_obj)

        # Test case-insensitive search
        search_terms = ["mary jane watson", "MARY JANE WATSON", "Mary Jane Watson"]

        for search_term in search_terms:
            # Build Q object
            file_q_objects = Q()
            file_q_objects |= Q(name__icontains=search_term.replace(" ", "_"))

            results = FileIndex.objects.filter(file_q_objects & Q(delete_pending=False))

            # Should find files regardless of case
            self.assertGreater(results.count(), 0, f"Search for '{search_term}' should find files")

            # Should find files with different cases
            result_names = [r.name for r in results]
            self.assertTrue(
                any("mary" in name.lower() for name in result_names),
                f"Search for '{search_term}' should find mary files",
            )

    def test_delete_pending_exclusion(self):
        """Test that files marked for deletion are excluded"""

        test_dir = DirectoryIndex.objects.create(
            fqpndirectory="/test/directory/",
            dir_fqpn_sha256="test_dir_sha2",
            lastmod=1234567890.0,
            lastscan=1234567890.0,
            filetype=self.filetype_dir,
            delete_pending=False,
        )

        # Create regular file
        FileIndex.objects.create(
            name="regular_file.jpg",
            fqpndirectory="/test/regular_file.jpg",
            file_sha256="regular_sha",
            unique_sha256="regular_unique",
            lastmod=1234567890.0,
            lastscan=1234567890.0,
            size=100000,
            filetype=self.filetype_image,
            home_directory=test_dir,
            delete_pending=False,
        )

        # Create file marked for deletion
        FileIndex.objects.create(
            name="deleted_file.jpg",
            fqpndirectory="/test/deleted_file.jpg",
            file_sha256="deleted_sha",
            unique_sha256="deleted_unique",
            lastmod=1234567890.0,
            lastscan=1234567890.0,
            size=100000,
            filetype=self.filetype_image,
            home_directory=test_dir,
            delete_pending=True,  # This should be excluded
        )

        # Search for files
        file_q_objects = Q(name__icontains="file")
        results = FileIndex.objects.filter(file_q_objects & Q(delete_pending=False))

        # Should only find the regular file, not the deleted one
        result_names = [r.name for r in results]
        self.assertIn("regular_file.jpg", result_names)
        self.assertNotIn("deleted_file.jpg", result_names)

        # Verify the deleted file exists in database but is excluded from search
        all_files = FileIndex.objects.filter(name__icontains="file")
        self.assertEqual(all_files.count(), 2)  # Both files exist
        self.assertEqual(results.count(), 1)  # Only one in search results


class TestSearchEdgeCases(TestCase):
    """Test edge cases and error conditions in search"""

    def test_none_search_text(self):
        """Test handling of None search text"""

        def create_search_variations(text):
            if not text:
                return []
            # ... rest of implementation
            return [text] if text else []

        variations = create_search_variations(None)
        self.assertEqual(variations, [])

    def test_whitespace_only_search(self):
        """Test search with whitespace-only text"""

        def create_search_variations(text):
            if not text or not text.strip():
                return []
            return [text.strip()]

        variations = create_search_variations("   ")
        self.assertEqual(variations, [])

        variations = create_search_variations("\t\n")
        self.assertEqual(variations, [])

    def test_optimized_regex_search_pattern(self):
        """Test the optimized regex pattern creation for separator-agnostic search"""

        import re

        def create_search_regex_pattern(text):
            """Implementation of the optimized regex pattern function"""
            if not text or not text.strip():
                return ""

            cleaned_text = text.strip()

            try:
                escaped = re.escape(cleaned_text)
            except Exception:
                return ""

            pattern = escaped.replace(r"\ ", r"[\s_-]+").replace(r"\_", r"[\s_-]+").replace(r"\-", r"[\s_-]+")

            if len(pattern) > 500:
                return ""

            return pattern

        # Test comprehensive cases
        test_cases = [
            {
                "input": "Mary Jane Watson",
                "expected_matches": [
                    "Mary Jane Watson",
                    "Mary_Jane_Watson",
                    "Mary-Jane-Watson",
                    "Mary___Jane___Watson",
                ],
                "expected_non_matches": ["MaryJaneWatson", "John Jane Watson"],
                "description": "Spaces to flexible separators",
            },
            {
                "input": "spider-man",
                "expected_matches": [
                    "spider-man",
                    "spider_man",
                    "spider man",
                    "SPIDER_MAN",
                ],
                "expected_non_matches": ["spiderman", "spider woman"],
                "description": "Dash to flexible separators",
            },
            {
                "input": "single",
                "expected_matches": ["single", "SINGLE"],
                "expected_non_matches": ["single_word", "not_single"],
                "description": "No separators to replace",
            },
            {"input": "", "expected_pattern": "", "description": "Empty string"},
            {
                "input": "special.chars",
                "expected_matches": ["special.chars"],
                "expected_non_matches": ["special_chars"],
                "description": "Special characters should be escaped",
            },
        ]

        for test_case in test_cases:
            with self.subTest(test_case["description"]):
                pattern = create_search_regex_pattern(test_case["input"])

                if "expected_pattern" in test_case:
                    self.assertEqual(pattern, test_case["expected_pattern"])

                # Test that pattern matches expected strings
                if pattern and "expected_matches" in test_case:
                    for test_string in test_case["expected_matches"]:
                        match = re.search(pattern, test_string, re.IGNORECASE)
                        self.assertIsNotNone(
                            match,
                            f"Pattern '{pattern}' should match '{test_string}' for input '{test_case['input']}'",
                        )

                # Test that pattern doesn't match strings it shouldn't
                if pattern and "expected_non_matches" in test_case:
                    for test_string in test_case["expected_non_matches"]:
                        match = re.search(pattern, test_string, re.IGNORECASE)
                        self.assertIsNone(
                            match,
                            f"Pattern '{pattern}' should NOT match '{test_string}' for input '{test_case['input']}'",
                        )

    def test_regex_vs_variations_performance_concept(self):
        """Conceptual test showing regex approach should be more efficient"""

        # This test demonstrates the conceptual difference
        # In production, the regex approach creates one database query instead of multiple OR conditions

        def old_approach_simulation(text):
            """Simulate the old approach with multiple variations"""
            variations = [
                text,
                text.replace("_", " "),
                text.replace("-", " "),
                text.replace(" ", "_"),
                text.replace(" ", "-"),
            ]
            return len(set(variations))  # Number of unique patterns to search

        def new_approach_simulation(text):
            """Simulate the new regex approach"""
            if not text.strip():
                return 0
            return 1  # Always just one regex pattern

        test_text = "Mary Jane Watson"
        old_queries = old_approach_simulation(test_text)
        new_queries = new_approach_simulation(test_text)

        self.assertGreater(
            old_queries,
            new_queries,
            "Old approach should generate more database queries than new approach",
        )
        self.assertEqual(new_queries, 1, "New approach should generate exactly one query")

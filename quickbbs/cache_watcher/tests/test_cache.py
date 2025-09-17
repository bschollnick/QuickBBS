print("a")
import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
print ("B")
print("A")
# Try different import approaches
try:
    print("B")
    from cache_watcher.models import fs_Cache_Tracking
except ImportError:
    print("C")
    try:
        print("D")

        from ..models import fs_Cache_Tracking
    except ImportError:
        print("E")

        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from models import fs_Cache_Tracking


@pytest.mark.django_db
class TestFsCacheTrackingModel:
    """Test suite for fs_Cache_Tracking model"""

    def test_model_creation_with_defaults(self):
        """Test creating a model instance with default values"""
        cache_entry = fs_Cache_Tracking.objects.create()
        
        assert cache_entry.directory_sha256 is None
        assert cache_entry.DirName == ""
        assert cache_entry.lastscan == 0
        assert cache_entry.invalidated is False

    def test_model_creation_with_values(self):
        """Test creating a model instance with specific values"""
        test_sha = "a" * 64  # 64-character SHA256
        test_dirname = "/test/directory"
        test_timestamp = time.time()
        
        cache_entry = fs_Cache_Tracking.objects.create(
            directory_sha256=test_sha,
            DirName=test_dirname,
            lastscan=test_timestamp,
            invalidated=True
        )
        
        assert cache_entry.directory_sha256 == test_sha
        assert cache_entry.DirName == test_dirname
        assert cache_entry.lastscan == test_timestamp
        assert cache_entry.invalidated is True

    def test_unique_constraint_on_directory_sha256(self):
        """Test that directory_sha256 must be unique"""
        test_sha = "a" * 64
        
        # Create first entry
        fs_Cache_Tracking.objects.create(directory_sha256=test_sha)
        
        # Attempt to create duplicate should raise IntegrityError
        with pytest.raises(IntegrityError):
            fs_Cache_Tracking.objects.create(directory_sha256=test_sha)

    def test_directory_sha256_max_length(self):
        """Test that directory_sha256 respects max_length constraint"""
        # SHA256 should be exactly 64 characters
        valid_sha = "a" * 64
        cache_entry = fs_Cache_Tracking.objects.create(directory_sha256=valid_sha)
        assert len(cache_entry.directory_sha256) == 64

    def test_dirname_max_length(self):
        """Test DirName max_length constraint"""
        long_dirname = "a" * 384  # Exactly at the limit
        cache_entry = fs_Cache_Tracking.objects.create(DirName=long_dirname)
        assert len(cache_entry.DirName) == 384

    def test_model_indexes_exist(self):
        """Test that the expected database indexes exist"""
        # This test verifies the Meta.indexes configuration
        # In a real scenario, you might check the database schema
        meta = fs_Cache_Tracking._meta
        index_names = [idx.name for idx in meta.indexes]
        
        # Check that our composite index exists
        composite_index_exists = any(
            set(idx.fields) == {"directory_sha256", "invalidated"}
            for idx in meta.indexes
        )
        assert composite_index_exists


@pytest.mark.django_db
class TestFsCacheTrackingStaticMethods:
    """Test static methods of fs_Cache_Tracking model"""

    def test_clear_all_records_empty_database(self):
        """Test clearing records when database is empty"""
        result = fs_Cache_Tracking.clear_all_records()
        assert result == 0

    def test_clear_all_records_with_data(self):
        """Test clearing records with existing data"""
        # Create some test records
        for i in range(3):
            fs_Cache_Tracking.objects.create(
                directory_sha256=f"{'a' * 63}{i}",
                DirName=f"/test/dir_{i}",
                invalidated=False
            )
        
        # Verify records exist and are not invalidated
        assert fs_Cache_Tracking.objects.filter(invalidated=False).count() == 3
        
        # Clear all records
        result = fs_Cache_Tracking.clear_all_records()
        
        # Verify all records are now invalidated
        assert result == 3
        assert fs_Cache_Tracking.objects.filter(invalidated=False).count() == 0
        assert fs_Cache_Tracking.objects.filter(invalidated=True).count() == 3

    @patch('cache_watcher.models.logger')  # Update import path
    def test_clear_all_records_with_exception(self, mock_logger):
        """Test clear_all_records handles exceptions gracefully"""
        with patch.object(fs_Cache_Tracking.objects, 'all') as mock_all:
            mock_queryset = Mock()
            mock_queryset.update.side_effect = Exception("Database error")
            mock_all.return_value = mock_queryset
            
            result = fs_Cache_Tracking.clear_all_records()
            
            assert result == 0
            mock_logger.error.assert_called_once()


@pytest.mark.django_db
class TestFsCacheTrackingInstanceMethods:
    """Test instance methods of fs_Cache_Tracking model"""

    def setup_method(self):
        """Set up test fixtures"""
        self.cache_instance = fs_Cache_Tracking()
        self.test_dirname = "/test/directory"
        self.test_sha = "a" * 64

    @patch('cache_watcher.models.get_dir_sha')  # Update import path
    @patch('cache_watcher.models.time.time')
    def test_add_to_cache_new_entry(self, mock_time, mock_get_dir_sha):
        """Test adding a new directory to cache"""
        mock_time.return_value = 1234567890.0
        mock_get_dir_sha.return_value = self.test_sha
        
        result = self.cache_instance.add_to_cache(self.test_dirname)
        
        assert result is not None
        assert result.directory_sha256 == self.test_sha
        assert result.DirName == self.test_dirname
        assert result.lastscan == 1234567890.0
        assert result.invalidated is False

    @patch('cache_watcher.models.get_dir_sha')
    @patch('cache_watcher.models.time.time')
    def test_add_to_cache_update_existing(self, mock_time, mock_get_dir_sha):
        """Test updating an existing directory in cache"""
        # Create existing entry
        existing_entry = fs_Cache_Tracking.objects.create(
            directory_sha256=self.test_sha,
            DirName=self.test_dirname,
            lastscan=1000000000.0,
            invalidated=True
        )
        
        mock_time.return_value = 1234567890.0
        mock_get_dir_sha.return_value = self.test_sha
        
        result = self.cache_instance.add_to_cache(self.test_dirname)
        
        # Refresh from database
        existing_entry.refresh_from_db()
        
        assert result.id == existing_entry.id  # Same record
        assert result.lastscan == 1234567890.0  # Updated timestamp
        assert result.invalidated is False  # Reset invalidated flag

    @patch('cache_watcher.models.get_dir_sha')
    @patch('cache_watcher.models.logger')
    def test_add_to_cache_with_exception(self, mock_logger, mock_get_dir_sha):
        """Test add_to_cache handles exceptions gracefully"""
        mock_get_dir_sha.side_effect = Exception("SHA generation error")
        
        result = self.cache_instance.add_to_cache(self.test_dirname)
        
        assert result is None
        mock_logger.error.assert_called_once()

    def test_sha_exists_in_cache_true(self):
        """Test sha_exists_in_cache returns True for valid, non-invalidated entry"""
        fs_Cache_Tracking.objects.create(
            directory_sha256=self.test_sha,
            invalidated=False
        )
        
        result = self.cache_instance.sha_exists_in_cache(self.test_sha)
        assert result is True

    def test_sha_exists_in_cache_false_invalidated(self):
        """Test sha_exists_in_cache returns False for invalidated entry"""
        fs_Cache_Tracking.objects.create(
            directory_sha256=self.test_sha,
            invalidated=True
        )
        
        result = self.cache_instance.sha_exists_in_cache(self.test_sha)
        assert result is False

    def test_sha_exists_in_cache_false_not_found(self):
        """Test sha_exists_in_cache returns False for non-existent entry"""
        result = self.cache_instance.sha_exists_in_cache(self.test_sha)
        assert result is False

    @patch('cache_watcher.models.logger')
    def test_sha_exists_in_cache_with_exception(self, mock_logger):
        """Test sha_exists_in_cache handles exceptions gracefully"""
        with patch.object(fs_Cache_Tracking.objects, 'filter') as mock_filter:
            mock_filter.side_effect = Exception("Database error")
            
            result = self.cache_instance.sha_exists_in_cache(self.test_sha)
            
            assert result is False
            mock_logger.error.assert_called_once()

    @patch('cache_watcher.models.time.time')
    @patch('quickbbs.models.IndexDirs')
    def test_remove_from_cache_sha_success(self, mock_index_dirs, mock_time):
        """Test successful removal from cache by SHA"""
        mock_time.return_value = 1234567890.0
        
        # Mock IndexDirs.objects.get to return a directory
        mock_directory = Mock()
        mock_index_dirs.objects.get.return_value = mock_directory
        mock_index_dirs.DoesNotExist = Exception  # Mock the exception class
        
        # Create initial cache entry
        fs_Cache_Tracking.objects.create(
            directory_sha256=self.test_sha,
            invalidated=False,
            lastscan=1000000000.0
        )
        
        result = self.cache_instance.remove_from_cache_sha(self.test_sha)
        
        assert result is True
        
        # Verify cache entry was updated
        updated_entry = fs_Cache_Tracking.objects.get(directory_sha256=self.test_sha)
        assert updated_entry.invalidated is True
        assert updated_entry.lastscan == 1234567890.0
        
        # Verify directory methods were called
        mock_directory.invalidate_thumb.assert_called_once()
        mock_directory.save.assert_called_once()

    @patch('cache_watcher.models.time.time')
    @patch('quickbbs.models.IndexDirs')
    def test_remove_from_cache_sha_no_directory(self, mock_index_dirs, mock_time):
        """Test removal when IndexDirs entry doesn't exist"""
        mock_time.return_value = 1234567890.0
        mock_index_dirs.DoesNotExist = Exception
        mock_index_dirs.objects.get.side_effect = mock_index_dirs.DoesNotExist
        
        result = self.cache_instance.remove_from_cache_sha(self.test_sha)
        
        assert result is True
        
        # Verify cache entry was still created/updated
        cache_entry = fs_Cache_Tracking.objects.get(directory_sha256=self.test_sha)
        assert cache_entry.invalidated is True

    @patch('cache_watcher.models.get_dir_sha')
    def test_remove_from_cache_name_success(self, mock_get_dir_sha):
        """Test successful removal from cache by directory name"""
        mock_get_dir_sha.return_value = self.test_sha
        
        with patch.object(self.cache_instance, 'remove_from_cache_sha') as mock_remove_sha:
            mock_remove_sha.return_value = True
            
            result = self.cache_instance.remove_from_cache_name(self.test_dirname)
            
            assert result is True
            mock_get_dir_sha.assert_called_once_with(self.test_dirname)
            mock_remove_sha.assert_called_once_with(self.test_sha)

    @patch('cache_watcher.models.get_dir_sha')
    @patch('cache_watcher.models.logger')
    def test_remove_from_cache_name_exception(self, mock_logger, mock_get_dir_sha):
        """Test remove_from_cache_name handles exceptions"""
        mock_get_dir_sha.side_effect = Exception("SHA generation error")
        
        result = self.cache_instance.remove_from_cache_name(self.test_dirname)
        
        assert result is False
        mock_logger.error.assert_called_once()

    @patch('cache_watcher.models.close_old_connections')
    @patch('cache_watcher.models.get_dir_sha')
    @patch('cache_watcher.models.time.time')
    @patch('quickbbs.models.IndexDirs')
    def test_remove_multiple_from_cache_success(self, mock_index_dirs, mock_time, 
                                              mock_get_dir_sha, mock_close_connections):
        """Test successful removal of multiple directories"""
        mock_time.return_value = 1234567890.0
        
        # Setup test data
        dir_names = ["/test/dir1", "/test/dir2", "/test/dir3"]
        sha_values = ["a" * 64, "b" * 64, "c" * 64]
        
        def side_effect(dirname):
            return sha_values[dir_names.index(dirname)]
        mock_get_dir_sha.side_effect = side_effect
        
        # Create cache entries
        for sha in sha_values:
            fs_Cache_Tracking.objects.create(
                directory_sha256=sha,
                invalidated=False,
                lastscan=1000000000.0
            )
        
        # Mock IndexDirs queryset
        mock_directories = [Mock() for _ in range(3)]
        for i, mock_dir in enumerate(mock_directories):
            mock_dir.dir_fqpn_sha256 = sha_values[i]
        
        mock_index_dirs.objects.filter.return_value = mock_directories
        
        result = self.cache_instance.remove_multiple_from_cache(dir_names)
        
        assert result is True
        
        # Verify all entries were invalidated
        invalidated_count = fs_Cache_Tracking.objects.filter(invalidated=True).count()
        assert invalidated_count == 3

    def test_remove_multiple_from_cache_empty_list(self):
        """Test remove_multiple_from_cache with empty list"""
        result = self.cache_instance.remove_multiple_from_cache([])
        assert result is False

    def test_remove_multiple_from_cache_none_input(self):
        """Test remove_multiple_from_cache with None input"""
        result = self.cache_instance.remove_multiple_from_cache(None)
        assert result is False

    @patch('frontend.views.layout_manager')
    @patch('frontend.views.layout_manager_cache', {})
    @patch('cache_watcher.models.hashkey')
    def test_clear_layout_cache(self, mock_hashkey, mock_layout_manager):
        """Test _clear_layout_cache method"""
        # Setup mock layout manager response
        mock_layout_manager.return_value = {"total_pages": 3}
        
        # Setup mock hashkey to return different keys for each page
        mock_hashkey.side_effect = lambda **kwargs: f"key_page_{kwargs['page_number']}"
        
        # Add some keys to the cache
        from frontend.views import layout_manager_cache
        layout_manager_cache.update({
            "key_page_1": "data1",
            "key_page_2": "data2",
            "key_page_3": "data3",
            "other_key": "other_data"
        })
        
        mock_directory = Mock()
        
        # Call the method
        self.cache_instance._clear_layout_cache(mock_directory)
        
        # Verify layout_manager was called correctly
        mock_layout_manager.assert_called_once_with(directory=mock_directory, sort_ordering=0)
        
        # Verify hashkey was called for each page
        assert mock_hashkey.call_count == 3
        
        # Verify specific keys were removed from cache
        assert "key_page_1" not in layout_manager_cache
        assert "key_page_2" not in layout_manager_cache
        assert "key_page_3" not in layout_manager_cache
        assert "other_key" in layout_manager_cache  # Should remain

    @patch('frontend.views.layout_manager')
    @patch('cache_watcher.models.logger')
    def test_clear_layout_cache_exception(self, mock_logger, mock_layout_manager):
        """Test _clear_layout_cache handles exceptions"""
        mock_layout_manager.side_effect = Exception("Layout error")
        mock_directory = Mock()
        
        # Should not raise exception
        self.cache_instance._clear_layout_cache(mock_directory)
        
        # Should log the error
        mock_logger.error.assert_called_once()


@pytest.mark.django_db
class TestFsCacheTrackingEdgeCases:
    """Test edge cases and error conditions"""

    def test_blank_values_allowed(self):
        """Test that blank values are properly handled"""
        cache_entry = fs_Cache_Tracking.objects.create(
            directory_sha256="",  # Empty string should be allowed
            DirName="",
        )
        
        assert cache_entry.directory_sha256 == ""
        assert cache_entry.DirName == ""

    def test_null_directory_sha256_allowed(self):
        """Test that null values are allowed for directory_sha256"""
        cache_entry = fs_Cache_Tracking.objects.create(directory_sha256=None)
        assert cache_entry.directory_sha256 is None

    def test_multiple_null_values_allowed(self):
        """Test that multiple entries with null directory_sha256 are allowed"""
        # Should be able to create multiple entries with null SHA
        entry1 = fs_Cache_Tracking.objects.create(directory_sha256=None, DirName="dir1")
        entry2 = fs_Cache_Tracking.objects.create(directory_sha256=None, DirName="dir2")
        
        assert entry1.directory_sha256 is None
        assert entry2.directory_sha256 is None
        assert entry1.id != entry2.id

    def test_lastscan_negative_value(self):
        """Test that negative values are allowed for lastscan"""
        cache_entry = fs_Cache_Tracking.objects.create(lastscan=-1.0)
        assert cache_entry.lastscan == -1.0

    def test_lastscan_very_large_value(self):
        """Test that very large timestamp values are handled"""
        large_timestamp = 9999999999.999
        cache_entry = fs_Cache_Tracking.objects.create(lastscan=large_timestamp)
        assert cache_entry.lastscan == large_timestamp


# Integration test for database queries
@pytest.mark.django_db
class TestFsCacheTrackingQueries:
    """Test database query performance and correctness"""

    def test_index_usage_composite_query(self):
        """Test that composite index is used for common queries"""
        # Create test data
        for i in range(10):
            fs_Cache_Tracking.objects.create(
                directory_sha256=f"{'a' * 63}{i}",
                invalidated=i % 2 == 0  # Mix of True/False
            )
        
        # Query that should use the composite index
        results = fs_Cache_Tracking.objects.filter(
            directory_sha256="a" * 63 + "5",
            invalidated=False
        )
        
        assert results.count() == 0  # This specific combo doesn't exist
        
        # Query for existing combo
        results = fs_Cache_Tracking.objects.filter(
            directory_sha256="a" * 63 + "4",
            invalidated=True
        )
        
        assert results.count() == 1

    def test_bulk_operations_performance(self):
        """Test performance of bulk operations"""
        # Create many entries
        entries = []
        for i in range(100):
            entries.append(fs_Cache_Tracking(
                directory_sha256=f"{'a' * 63}{i:01d}",
                DirName=f"/test/dir_{i}",
                invalidated=False
            ))
        
        fs_Cache_Tracking.objects.bulk_create(entries)
        
        # Test bulk update
        sha_list = [f"{'a' * 63}{i:01d}" for i in range(0, 100, 2)]  # Even numbers
        
        with transaction.atomic():
            updated_count = fs_Cache_Tracking.objects.filter(
                directory_sha256__in=sha_list
            ).update(invalidated=True)
        
        assert updated_count == 50
        
        # Verify the update
        invalidated_count = fs_Cache_Tracking.objects.filter(invalidated=True).count()
        assert invalidated_count == 50
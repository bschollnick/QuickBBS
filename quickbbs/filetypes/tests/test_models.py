import io
import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.db import IntegrityError
from django.conf import settings

from filetypes.models import (
    filetypes,
    get_ftype_dict,
    return_identifier,
    load_filetypes,
    FILETYPE_DATA
)


@pytest.mark.django_db
class TestFiletypesModel:
    """Test suite for filetypes model"""

    def setup_method(self):
        """Set up test fixtures"""
        filetypes.filetype_exists_by_ext.cache_clear()
        filetypes.return_any_icon_filename.cache_clear()
        filetypes.return_filetype.cache_clear()

    def test_model_creation_with_defaults(self):
        """Test creating a filetype with default values"""
        ft = filetypes.objects.create(fileext=".test")

        assert ft.fileext == ".test"
        assert ft.generic is False
        assert ft.icon_filename == ""
        assert ft.color == "000000"
        assert ft.filetype == 0
        assert ft.mimetype == "application/octet-stream"
        assert ft.is_image is False
        assert ft.is_archive is False
        assert ft.is_pdf is False
        assert ft.is_movie is False
        assert ft.is_audio is False
        assert ft.is_dir is False
        assert ft.is_text is False
        assert ft.is_html is False
        assert ft.is_markdown is False
        assert ft.is_link is False

    def test_model_creation_with_values(self):
        """Test creating a filetype with specific values"""
        ft = filetypes.objects.create(
            fileext=".jpg",
            generic=False,
            icon_filename="test.png",
            color="FF0000",
            filetype=1,
            mimetype="image/jpeg",
            is_image=True
        )

        assert ft.fileext == ".jpg"
        assert ft.generic is False
        assert ft.icon_filename == "test.png"
        assert ft.color == "FF0000"
        assert ft.filetype == 1
        assert ft.mimetype == "image/jpeg"
        assert ft.is_image is True

    def test_unique_constraint_on_fileext(self):
        """Test that fileext must be unique"""
        filetypes.objects.create(fileext=".jpg")

        with pytest.raises(IntegrityError):
            filetypes.objects.create(fileext=".jpg")

    def test_fileext_is_primary_key(self):
        """Test that fileext is the primary key"""
        ft = filetypes.objects.create(fileext=".test")
        assert ft.pk == ".test"

    def test_str_representation(self):
        """Test string representation of filetype"""
        ft = filetypes.objects.create(fileext=".test")
        assert str(ft) == ".test"

    def test_unicode_representation(self):
        """Test unicode representation of filetype"""
        ft = filetypes.objects.create(fileext=".test")
        assert ft.__unicode__() == ".test"

    def test_fileext_max_length(self):
        """Test fileext max_length constraint"""
        max_ext = "a" * 10
        ft = filetypes.objects.create(fileext=max_ext)
        assert len(ft.fileext) == 10

    def test_icon_filename_max_length(self):
        """Test icon_filename max_length constraint"""
        long_filename = "a" * 384
        ft = filetypes.objects.create(fileext=".test", icon_filename=long_filename)
        assert len(ft.icon_filename) == 384

    def test_color_max_length(self):
        """Test color max_length constraint"""
        ft = filetypes.objects.create(fileext=".test", color="FFFFFF")
        assert len(ft.color) == 6

    def test_mimetype_max_length(self):
        """Test mimetype max_length constraint"""
        long_mimetype = "a" * 128
        ft = filetypes.objects.create(fileext=".test", mimetype=long_mimetype)
        assert len(ft.mimetype) == 128

    def test_thumbnail_binary_field(self):
        """Test thumbnail can store binary data"""
        binary_data = b"test binary data"
        ft = filetypes.objects.create(fileext=".test", thumbnail=binary_data)
        assert ft.thumbnail == binary_data

    def test_all_boolean_flags(self):
        """Test all boolean flags can be set independently"""
        ft = filetypes.objects.create(
            fileext=".test",
            is_image=True,
            is_archive=True,
            is_pdf=True,
            is_movie=True,
            is_audio=True,
            is_dir=True,
            is_text=True,
            is_html=True,
            is_markdown=True,
            is_link=True
        )

        assert ft.is_image is True
        assert ft.is_archive is True
        assert ft.is_pdf is True
        assert ft.is_movie is True
        assert ft.is_audio is True
        assert ft.is_dir is True
        assert ft.is_text is True
        assert ft.is_html is True
        assert ft.is_markdown is True
        assert ft.is_link is True


@pytest.mark.django_db
class TestFiletypesStaticMethods:
    """Test static methods of filetypes model"""

    def setup_method(self):
        """Set up test fixtures"""
        filetypes.filetype_exists_by_ext.cache_clear()
        filetypes.return_any_icon_filename.cache_clear()
        filetypes.return_filetype.cache_clear()

    def test_filetype_exists_by_ext_true(self):
        """Test filetype_exists_by_ext returns True for existing filetype"""
        filetypes.objects.create(fileext=".jpg")

        assert filetypes.filetype_exists_by_ext(".jpg") is True

    def test_filetype_exists_by_ext_false(self):
        """Test filetype_exists_by_ext returns False for non-existing filetype"""
        assert filetypes.filetype_exists_by_ext(".nonexistent") is False

    def test_filetype_exists_by_ext_normalizes_lowercase(self):
        """Test filetype_exists_by_ext normalizes to lowercase"""
        filetypes.objects.create(fileext=".jpg")

        assert filetypes.filetype_exists_by_ext(".JPG") is True
        assert filetypes.filetype_exists_by_ext(".Jpg") is True

    def test_filetype_exists_by_ext_adds_dot(self):
        """Test filetype_exists_by_ext adds dot if missing"""
        filetypes.objects.create(fileext=".jpg")

        assert filetypes.filetype_exists_by_ext("jpg") is True

    def test_filetype_exists_by_ext_strips_whitespace(self):
        """Test filetype_exists_by_ext strips whitespace"""
        filetypes.objects.create(fileext=".jpg")

        assert filetypes.filetype_exists_by_ext("  .jpg  ") is True

    def test_filetype_exists_by_ext_empty_string(self):
        """Test filetype_exists_by_ext returns False for empty string"""
        assert filetypes.filetype_exists_by_ext("") is False

    def test_filetype_exists_by_ext_none(self):
        """Test filetype_exists_by_ext returns False for None"""
        assert filetypes.filetype_exists_by_ext(None) is False

    def test_filetype_exists_by_ext_unknown(self):
        """Test filetype_exists_by_ext returns False for 'unknown'"""
        assert filetypes.filetype_exists_by_ext("unknown") is False

    def test_filetype_exists_by_ext_caching(self):
        """Test filetype_exists_by_ext uses caching"""
        filetypes.objects.create(fileext=".jpg")

        result1 = filetypes.filetype_exists_by_ext(".jpg")
        result2 = filetypes.filetype_exists_by_ext(".jpg")

        assert result1 == result2 == True

    @patch('filetypes.models.settings.IMAGES_PATH', '/test/images')
    def test_return_any_icon_filename_success(self):
        """Test return_any_icon_filename returns correct path"""
        filetypes.objects.create(fileext=".jpg", icon_filename="test.png")

        result = filetypes.return_any_icon_filename(".jpg")
        assert result == "/test/images/test.png"

    def test_return_any_icon_filename_no_icon(self):
        """Test return_any_icon_filename returns None for empty icon_filename"""
        filetypes.objects.create(fileext=".jpg", icon_filename="")

        result = filetypes.return_any_icon_filename(".jpg")
        assert result is None

    def test_return_any_icon_filename_normalizes_extension(self):
        """Test return_any_icon_filename normalizes extension"""
        filetypes.objects.create(fileext=".jpg", icon_filename="test.png")

        result1 = filetypes.return_any_icon_filename("JPG")
        result2 = filetypes.return_any_icon_filename(".jpg")
        result3 = filetypes.return_any_icon_filename("  .JPG  ")

        assert result1 == result2 == result3

    def test_return_any_icon_filename_empty_string_uses_none(self):
        """Test return_any_icon_filename uses .none for empty string"""
        filetypes.objects.create(fileext=".none", icon_filename="default.png")

        with patch('filetypes.models.settings.IMAGES_PATH', '/test'):
            result = filetypes.return_any_icon_filename("")
            assert result == "/test/default.png"

    def test_return_any_icon_filename_unknown_uses_none(self):
        """Test return_any_icon_filename uses .none for 'unknown'"""
        filetypes.objects.create(fileext=".none", icon_filename="default.png")

        with patch('filetypes.models.settings.IMAGES_PATH', '/test'):
            result = filetypes.return_any_icon_filename("unknown")
            assert result == "/test/default.png"

    def test_return_filetype_success(self):
        """Test return_filetype returns correct filetype object"""
        ft = filetypes.objects.create(fileext=".jpg", is_image=True)

        result = filetypes.return_filetype(".jpg")
        assert result.fileext == ".jpg"
        assert result.is_image is True

    def test_return_filetype_normalizes_extension(self):
        """Test return_filetype normalizes extension"""
        ft = filetypes.objects.create(fileext=".jpg")

        result1 = filetypes.return_filetype("JPG")
        result2 = filetypes.return_filetype(".jpg")
        result3 = filetypes.return_filetype("  .JPG  ")

        assert result1 == result2 == result3

    def test_return_filetype_empty_string_uses_none(self):
        """Test return_filetype uses .none for empty string"""
        ft = filetypes.objects.create(fileext=".none")

        result = filetypes.return_filetype("")
        assert result.fileext == ".none"

    def test_return_filetype_adds_dot(self):
        """Test return_filetype adds dot if missing"""
        ft = filetypes.objects.create(fileext=".jpg")

        result = filetypes.return_filetype("jpg")
        assert result.fileext == ".jpg"

    def test_return_filetype_caching(self):
        """Test return_filetype uses caching"""
        ft = filetypes.objects.create(fileext=".jpg")

        result1 = filetypes.return_filetype(".jpg")
        result2 = filetypes.return_filetype(".jpg")

        assert result1 == result2


@pytest.mark.django_db
class TestFiletypesSendThumbnail:
    """Test send_thumbnail method"""

    def setup_method(self):
        """Set up test fixtures"""
        self.test_thumbnail = b"test image data"
        self.ft = filetypes.objects.create(
            fileext=".jpg",
            icon_filename="test.jpg",
            mimetype="image/jpeg",
            thumbnail=self.test_thumbnail
        )

    @patch('filetypes.models.send_file_response')
    def test_send_thumbnail_calls_send_file_response(self, mock_send_file):
        """Test send_thumbnail calls send_file_response correctly"""
        self.ft.send_thumbnail()

        mock_send_file.assert_called_once()
        call_kwargs = mock_send_file.call_args[1]

        assert call_kwargs['filename'] == "test.jpg"
        assert isinstance(call_kwargs['content_to_send'], io.BytesIO)
        assert call_kwargs['mtype'] == "image/jpeg"
        assert call_kwargs['attachment'] is False
        assert call_kwargs['last_modified'] is None
        assert call_kwargs['expiration'] == 300

    @patch('filetypes.models.send_file_response')
    def test_send_thumbnail_with_no_mimetype(self, mock_send_file):
        """Test send_thumbnail uses default mimetype when None"""
        ft = filetypes.objects.create(
            fileext=".test",
            icon_filename="test.png",
            mimetype=None,
            thumbnail=b"data"
        )

        ft.send_thumbnail()

        call_kwargs = mock_send_file.call_args[1]
        assert call_kwargs['mtype'] == "image/jpeg"

    @patch('filetypes.models.send_file_response')
    def test_send_thumbnail_content_is_bytesio(self, mock_send_file):
        """Test send_thumbnail sends thumbnail as BytesIO"""
        self.ft.send_thumbnail()

        call_kwargs = mock_send_file.call_args[1]
        content = call_kwargs['content_to_send']

        assert isinstance(content, io.BytesIO)
        assert content.read() == self.test_thumbnail


@pytest.mark.django_db
class TestGetFtypeDict:
    """Test get_ftype_dict function"""

    def setup_method(self):
        """Set up test fixtures"""
        get_ftype_dict.cache_clear()

    def test_get_ftype_dict_returns_dictionary(self):
        """Test get_ftype_dict returns a dictionary"""
        result = get_ftype_dict()
        assert isinstance(result, dict)

    def test_get_ftype_dict_empty_database(self):
        """Test get_ftype_dict with empty database"""
        result = get_ftype_dict()
        assert result == {}

    def test_get_ftype_dict_with_data(self):
        """Test get_ftype_dict returns all filetypes"""
        ft1 = filetypes.objects.create(fileext=".jpg")
        ft2 = filetypes.objects.create(fileext=".png")
        ft3 = filetypes.objects.create(fileext=".gif")

        result = get_ftype_dict()

        assert len(result) == 3
        assert ".jpg" in result
        assert ".png" in result
        assert ".gif" in result

    def test_get_ftype_dict_keyed_by_primary_key(self):
        """Test get_ftype_dict is keyed by primary key (fileext)"""
        ft = filetypes.objects.create(fileext=".jpg", is_image=True)

        result = get_ftype_dict()

        assert result[".jpg"].fileext == ".jpg"
        assert result[".jpg"].is_image is True

    def test_get_ftype_dict_caching(self):
        """Test get_ftype_dict uses caching"""
        filetypes.objects.create(fileext=".jpg")

        result1 = get_ftype_dict()
        result2 = get_ftype_dict()

        assert result1 == result2


class TestReturnIdentifier:
    """Test return_identifier function"""

    def test_return_identifier_lowercase(self):
        """Test return_identifier converts to lowercase"""
        result = return_identifier("JPG")
        assert result == "jpg"

    def test_return_identifier_strips_whitespace(self):
        """Test return_identifier strips whitespace"""
        result = return_identifier("  jpg  ")
        assert result == "jpg"

    def test_return_identifier_lowercase_and_strip(self):
        """Test return_identifier both lowercases and strips"""
        result = return_identifier("  JPG  ")
        assert result == "jpg"

    def test_return_identifier_with_dot(self):
        """Test return_identifier preserves dot"""
        result = return_identifier(".JPG")
        assert result == ".jpg"

    def test_return_identifier_empty_string(self):
        """Test return_identifier handles empty string"""
        result = return_identifier("")
        assert result == ""




@pytest.mark.django_db
class TestLoadFiletypes:
    """Test load_filetypes function"""

    def setup_method(self):
        """Set up test fixtures"""
        import filetypes.models
        filetypes.models.FILETYPE_DATA = {}
        get_ftype_dict.cache_clear()

    def test_load_filetypes_populates_global(self):
        """Test load_filetypes populates FILETYPE_DATA"""
        filetypes.objects.create(fileext=".jpg")

        result = load_filetypes()

        import filetypes.models
        assert filetypes.models.FILETYPE_DATA != {}
        assert ".jpg" in result

    def test_load_filetypes_returns_cached_data(self):
        """Test load_filetypes returns cached data without force"""
        filetypes.objects.create(fileext=".jpg")

        result1 = load_filetypes()
        filetypes.objects.create(fileext=".png")
        result2 = load_filetypes()

        assert ".jpg" in result2
        assert ".png" not in result2

    def test_load_filetypes_force_reload(self):
        """Test load_filetypes force reloads data"""
        filetypes.objects.create(fileext=".jpg")

        result1 = load_filetypes()
        filetypes.objects.create(fileext=".png")
        result2 = load_filetypes(force=True)

        assert ".jpg" in result2
        assert ".png" in result2

    @patch('filetypes.models.get_ftype_dict')
    @patch('builtins.print')
    def test_load_filetypes_handles_exception(self, mock_print, mock_get_ftype):
        """Test load_filetypes handles exceptions gracefully"""
        mock_get_ftype.side_effect = Exception("Database error")

        import filetypes.models
        filetypes.models.FILETYPE_DATA = {}

        result = load_filetypes()

        mock_print.assert_called()
        assert result == {}

    @patch('builtins.print')
    def test_load_filetypes_logs_loading_message(self, mock_print):
        """Test load_filetypes prints loading message"""
        import filetypes.models
        filetypes.models.FILETYPE_DATA = {}

        load_filetypes()

        mock_print.assert_any_call("Loading FileType data from database...")


@pytest.mark.django_db
class TestFiletypesIndexes:
    """Test database indexes on filetypes model"""

    def test_model_has_indexes(self):
        """Test that expected indexes exist on model"""
        meta = filetypes._meta

        indexed_fields = [field.name for field in meta.fields if field.db_index]

        expected_indexed = [
            'fileext',  # Primary key, automatically indexed
            'generic',
            'icon_filename',
            'filetype',
            'is_image',
            'is_archive',
            'is_pdf',
            'is_movie',
            'is_audio',
            'is_dir',
            'is_text',
            'is_html',
            'is_markdown',
            'is_link'
        ]

        for field in expected_indexed:
            assert field in indexed_fields or field == 'fileext'


@pytest.mark.django_db
class TestFiletypesEdgeCases:
    """Test edge cases and error conditions"""

    def test_null_mimetype_allowed(self):
        """Test that null mimetype is allowed"""
        ft = filetypes.objects.create(fileext=".test", mimetype=None)
        assert ft.mimetype is None

    def test_null_thumbnail_allowed(self):
        """Test that null thumbnail is allowed"""
        ft = filetypes.objects.create(fileext=".test", thumbnail=None)
        assert ft.thumbnail is None

    def test_empty_thumbnail_bytes(self):
        """Test empty bytes for thumbnail"""
        ft = filetypes.objects.create(fileext=".test", thumbnail=b"")
        assert ft.thumbnail == b""

    def test_negative_filetype(self):
        """Test negative filetype value"""
        ft = filetypes.objects.create(fileext=".test", filetype=-1)
        assert ft.filetype == -1

    def test_large_filetype(self):
        """Test large filetype value"""
        ft = filetypes.objects.create(fileext=".test", filetype=999999)
        assert ft.filetype == 999999

    def test_special_characters_in_fileext(self):
        """Test special characters in fileext"""
        ft = filetypes.objects.create(fileext=".te$t")
        assert ft.fileext == ".te$t"

    def test_fileext_with_multiple_dots(self):
        """Test fileext with multiple dots"""
        ft = filetypes.objects.create(fileext=".tar.gz")
        assert ft.fileext == ".tar.gz"
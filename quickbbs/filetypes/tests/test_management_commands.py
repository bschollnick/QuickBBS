import pytest
import pathlib
from unittest.mock import Mock, patch, MagicMock, call
from io import StringIO
from django.core.management import call_command
from django.test import TestCase

from filetypes.management.commands.refresh_filetypes import Command
from filetypes.models import filetypes


@pytest.mark.django_db
class TestRefreshFiletypesCommand:
    """Test suite for refresh-filetypes management command"""

    def setup_method(self):
        """Set up test fixtures"""
        filetypes.objects.all().delete()
        self.command = Command()

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_refresh_filetypes_movie_types(self, mock_path, mock_settings):
        """Test refresh_filetypes creates movie file types"""
        mock_settings.MOVIE_FILE_TYPES = ['.mp4', '.avi']
        mock_settings.FTYPES = {'movie': 1}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        self.command.refresh_filetypes()

        assert filetypes.objects.filter(fileext='.mp4').exists()
        assert filetypes.objects.filter(fileext='.avi').exists()

        mp4 = filetypes.objects.get(fileext='.mp4')
        assert mp4.is_movie is True
        assert mp4.icon_filename == "MovieIcon100.jpg"
        assert mp4.filetype == 1
        assert mp4.generic is False

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_refresh_filetypes_audio_types(self, mock_path, mock_settings):
        """Test refresh_filetypes creates audio file types"""
        mock_settings.AUDIO_FILE_TYPES = ['.mp3', '.wav']
        mock_settings.MOVIE_FILE_TYPES = []
        mock_settings.ARCHIVE_FILE_TYPES = []
        mock_settings.HTML_FILE_TYPES = []
        mock_settings.GRAPHIC_FILE_TYPES = []
        mock_settings.TEXT_FILE_TYPES = []
        mock_settings.MARKDOWN_FILE_TYPES = []
        mock_settings.LINK_FILE_TYPES = []
        mock_settings.FTYPES = {'audio': 2}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        self.command.refresh_filetypes()

        mp3 = filetypes.objects.get(fileext='.mp3')
        assert mp3.is_audio is True
        assert mp3.generic is True
        assert mp3.filetype == 2

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_refresh_filetypes_archive_types(self, mock_path, mock_settings):
        """Test refresh_filetypes creates archive file types"""
        mock_settings.ARCHIVE_FILE_TYPES = ['.zip', '.rar']
        mock_settings.MOVIE_FILE_TYPES = []
        mock_settings.AUDIO_FILE_TYPES = []
        mock_settings.HTML_FILE_TYPES = []
        mock_settings.GRAPHIC_FILE_TYPES = []
        mock_settings.TEXT_FILE_TYPES = []
        mock_settings.MARKDOWN_FILE_TYPES = []
        mock_settings.LINK_FILE_TYPES = []
        mock_settings.FTYPES = {'archive': 3}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        self.command.refresh_filetypes()

        zip_ft = filetypes.objects.get(fileext='.zip')
        assert zip_ft.is_archive is True
        assert zip_ft.icon_filename == "1431973824_compressed.png"
        assert zip_ft.color == "b2dece"

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_refresh_filetypes_html_types(self, mock_path, mock_settings):
        """Test refresh_filetypes creates HTML file types"""
        mock_settings.HTML_FILE_TYPES = ['.html', '.htm']
        mock_settings.MOVIE_FILE_TYPES = []
        mock_settings.AUDIO_FILE_TYPES = []
        mock_settings.ARCHIVE_FILE_TYPES = []
        mock_settings.GRAPHIC_FILE_TYPES = []
        mock_settings.TEXT_FILE_TYPES = []
        mock_settings.MARKDOWN_FILE_TYPES = []
        mock_settings.LINK_FILE_TYPES = []
        mock_settings.FTYPES = {'html': 4}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        self.command.refresh_filetypes()

        html = filetypes.objects.get(fileext='.html')
        assert html.is_html is True
        assert html.is_text is False
        assert html.icon_filename == "1431973779_html.png"

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_refresh_filetypes_graphic_types(self, mock_path, mock_settings):
        """Test refresh_filetypes creates graphic file types"""
        mock_settings.GRAPHIC_FILE_TYPES = ['.jpg', '.png']
        mock_settings.MOVIE_FILE_TYPES = []
        mock_settings.AUDIO_FILE_TYPES = []
        mock_settings.ARCHIVE_FILE_TYPES = []
        mock_settings.HTML_FILE_TYPES = []
        mock_settings.TEXT_FILE_TYPES = []
        mock_settings.MARKDOWN_FILE_TYPES = []
        mock_settings.LINK_FILE_TYPES = []
        mock_settings.FTYPES = {'image': 5}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        self.command.refresh_filetypes()

        jpg = filetypes.objects.get(fileext='.jpg')
        assert jpg.is_image is True
        assert jpg.generic is False
        assert jpg.color == "FAEBF4"

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_refresh_filetypes_text_types(self, mock_path, mock_settings):
        """Test refresh_filetypes creates text file types"""
        mock_settings.TEXT_FILE_TYPES = ['.txt', '.log']
        mock_settings.MOVIE_FILE_TYPES = []
        mock_settings.AUDIO_FILE_TYPES = []
        mock_settings.ARCHIVE_FILE_TYPES = []
        mock_settings.HTML_FILE_TYPES = []
        mock_settings.GRAPHIC_FILE_TYPES = []
        mock_settings.MARKDOWN_FILE_TYPES = []
        mock_settings.LINK_FILE_TYPES = []
        mock_settings.FTYPES = {'image': 5}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        self.command.refresh_filetypes()

        txt = filetypes.objects.get(fileext='.txt')
        assert txt.is_text is True
        assert txt.icon_filename == "1431973815_text.PNG"

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_refresh_filetypes_markdown_types(self, mock_path, mock_settings):
        """Test refresh_filetypes creates markdown file types"""
        mock_settings.MARKDOWN_FILE_TYPES = ['.md', '.markdown']
        mock_settings.MOVIE_FILE_TYPES = []
        mock_settings.AUDIO_FILE_TYPES = []
        mock_settings.ARCHIVE_FILE_TYPES = []
        mock_settings.HTML_FILE_TYPES = []
        mock_settings.GRAPHIC_FILE_TYPES = []
        mock_settings.TEXT_FILE_TYPES = []
        mock_settings.LINK_FILE_TYPES = []
        mock_settings.FTYPES = {'image': 5}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        self.command.refresh_filetypes()

        md = filetypes.objects.get(fileext='.md')
        assert md.is_markdown is True
        assert md.is_text is False

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_refresh_filetypes_link_types(self, mock_path, mock_settings):
        """Test refresh_filetypes creates link file types"""
        mock_settings.LINK_FILE_TYPES = ['.url', '.webloc']
        mock_settings.MOVIE_FILE_TYPES = []
        mock_settings.AUDIO_FILE_TYPES = []
        mock_settings.ARCHIVE_FILE_TYPES = []
        mock_settings.HTML_FILE_TYPES = []
        mock_settings.GRAPHIC_FILE_TYPES = []
        mock_settings.TEXT_FILE_TYPES = []
        mock_settings.MARKDOWN_FILE_TYPES = []
        mock_settings.FTYPES = {'link': 6}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        self.command.refresh_filetypes()

        url = filetypes.objects.get(fileext='.url')
        assert url.is_link is True
        assert url.icon_filename == "redirecting-link.png"

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_refresh_filetypes_pdf_type(self, mock_path, mock_settings):
        """Test refresh_filetypes creates PDF file type"""
        mock_settings.MOVIE_FILE_TYPES = []
        mock_settings.AUDIO_FILE_TYPES = []
        mock_settings.ARCHIVE_FILE_TYPES = []
        mock_settings.HTML_FILE_TYPES = []
        mock_settings.GRAPHIC_FILE_TYPES = []
        mock_settings.TEXT_FILE_TYPES = []
        mock_settings.MARKDOWN_FILE_TYPES = []
        mock_settings.LINK_FILE_TYPES = []
        mock_settings.FTYPES = {'image': 5}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        self.command.refresh_filetypes()

        pdf = filetypes.objects.get(fileext='.pdf')
        assert pdf.is_pdf is True
        assert pdf.generic is False
        assert pdf.color == "FDEDB1"

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_refresh_filetypes_epub_type(self, mock_path, mock_settings):
        """Test refresh_filetypes creates EPUB file type"""
        mock_settings.MOVIE_FILE_TYPES = []
        mock_settings.AUDIO_FILE_TYPES = []
        mock_settings.ARCHIVE_FILE_TYPES = []
        mock_settings.HTML_FILE_TYPES = []
        mock_settings.GRAPHIC_FILE_TYPES = []
        mock_settings.TEXT_FILE_TYPES = []
        mock_settings.MARKDOWN_FILE_TYPES = []
        mock_settings.LINK_FILE_TYPES = []
        mock_settings.FTYPES = {'epub': 7}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        self.command.refresh_filetypes()

        epub = filetypes.objects.get(fileext='.epub')
        assert epub.icon_filename == "epub-logo.gif"
        assert epub.filetype == 7

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_refresh_filetypes_dir_type(self, mock_path, mock_settings):
        """Test refresh_filetypes creates directory file type"""
        mock_settings.MOVIE_FILE_TYPES = []
        mock_settings.AUDIO_FILE_TYPES = []
        mock_settings.ARCHIVE_FILE_TYPES = []
        mock_settings.HTML_FILE_TYPES = []
        mock_settings.GRAPHIC_FILE_TYPES = []
        mock_settings.TEXT_FILE_TYPES = []
        mock_settings.MARKDOWN_FILE_TYPES = []
        mock_settings.LINK_FILE_TYPES = []
        mock_settings.FTYPES = {'dir': 8}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        self.command.refresh_filetypes()

        dir_ft = filetypes.objects.get(fileext='.dir')
        assert dir_ft.is_dir is True
        assert dir_ft.icon_filename == "1431973840_folder.png"
        assert dir_ft.color == "DAEFF5"

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_refresh_filetypes_none_type(self, mock_path, mock_settings):
        """Test refresh_filetypes creates .none file type"""
        mock_settings.MOVIE_FILE_TYPES = []
        mock_settings.AUDIO_FILE_TYPES = []
        mock_settings.ARCHIVE_FILE_TYPES = []
        mock_settings.HTML_FILE_TYPES = []
        mock_settings.GRAPHIC_FILE_TYPES = []
        mock_settings.TEXT_FILE_TYPES = []
        mock_settings.MARKDOWN_FILE_TYPES = []
        mock_settings.LINK_FILE_TYPES = []
        mock_settings.FTYPES = {'unknown': 9}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        self.command.refresh_filetypes()

        none_ft = filetypes.objects.get(fileext='.none')
        assert none_ft.icon_filename == "1431973807_fileicon_bg.png"
        assert none_ft.filetype == 9
        assert none_ft.color == "FFFFFF"

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_refresh_filetypes_update_existing(self, mock_path, mock_settings):
        """Test refresh_filetypes updates existing file types"""
        mock_settings.MOVIE_FILE_TYPES = ['.mp4']
        mock_settings.AUDIO_FILE_TYPES = []
        mock_settings.ARCHIVE_FILE_TYPES = []
        mock_settings.HTML_FILE_TYPES = []
        mock_settings.GRAPHIC_FILE_TYPES = []
        mock_settings.TEXT_FILE_TYPES = []
        mock_settings.MARKDOWN_FILE_TYPES = []
        mock_settings.LINK_FILE_TYPES = []
        mock_settings.FTYPES = {'movie': 1}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"new_image_data"
        mock_path.return_value = mock_path_instance

        filetypes.objects.create(
            fileext='.mp4',
            is_movie=False,
            thumbnail=b"old_data"
        )

        self.command.refresh_filetypes()

        mp4 = filetypes.objects.get(fileext='.mp4')
        assert mp4.is_movie is True
        assert mp4.thumbnail == b"new_image_data"

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    @patch('filetypes.management.commands.refresh_filetypes.guess_type')
    def test_refresh_filetypes_mimetype_guessing(self, mock_guess_type, mock_path, mock_settings):
        """Test refresh_filetypes guesses mimetypes correctly"""
        mock_settings.MOVIE_FILE_TYPES = ['.mp4']
        mock_settings.AUDIO_FILE_TYPES = []
        mock_settings.ARCHIVE_FILE_TYPES = []
        mock_settings.HTML_FILE_TYPES = []
        mock_settings.GRAPHIC_FILE_TYPES = []
        mock_settings.TEXT_FILE_TYPES = []
        mock_settings.MARKDOWN_FILE_TYPES = []
        mock_settings.LINK_FILE_TYPES = []
        mock_settings.FTYPES = {'movie': 1}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        mock_guess_type.return_value = ('video/mp4', None)

        self.command.refresh_filetypes()

        mock_guess_type.assert_called()
        mp4 = filetypes.objects.get(fileext='.mp4')
        assert mp4.mimetype == 'video/mp4'

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_refresh_filetypes_link_special_case(self, mock_path, mock_settings):
        """Test refresh_filetypes handles .link special case"""
        mock_settings.LINK_FILE_TYPES = []
        mock_settings.MOVIE_FILE_TYPES = []
        mock_settings.AUDIO_FILE_TYPES = []
        mock_settings.ARCHIVE_FILE_TYPES = []
        mock_settings.HTML_FILE_TYPES = []
        mock_settings.GRAPHIC_FILE_TYPES = []
        mock_settings.TEXT_FILE_TYPES = []
        mock_settings.MARKDOWN_FILE_TYPES = []
        mock_settings.FTYPES = {'link': 6}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        self.command.refresh_filetypes()

        link = filetypes.objects.get(fileext='.link')
        assert link.is_link is True

    def test_command_handle_method(self):
        """Test command handle method"""
        out = StringIO()

        with patch.object(Command, 'refresh_filetypes') as mock_refresh:
            call_command('refresh-filetypes', '--refresh-filetypes', stdout=out)

            mock_refresh.assert_called_once()

    def test_command_add_arguments(self):
        """Test command adds correct arguments"""
        parser = Mock()

        self.command.add_arguments(parser)

        parser.add_argument.assert_called_once_with(
            "--refresh-filetypes",
            action="store_true",
            help="Add, Refresh and revise the FileType table",
        )


@pytest.mark.django_db
class TestRefreshFiletypesCommandIntegration:
    """Integration tests for refresh-filetypes command"""

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_full_refresh_creates_all_types(self, mock_path, mock_settings):
        """Test full refresh creates all expected file types"""
        mock_settings.MOVIE_FILE_TYPES = ['.mp4']
        mock_settings.AUDIO_FILE_TYPES = ['.mp3']
        mock_settings.ARCHIVE_FILE_TYPES = ['.zip']
        mock_settings.HTML_FILE_TYPES = ['.html']
        mock_settings.GRAPHIC_FILE_TYPES = ['.jpg']
        mock_settings.TEXT_FILE_TYPES = ['.txt']
        mock_settings.MARKDOWN_FILE_TYPES = ['.md']
        mock_settings.LINK_FILE_TYPES = ['.url']
        mock_settings.FTYPES = {
            'movie': 1, 'audio': 2, 'archive': 3,
            'html': 4, 'image': 5, 'link': 6,
            'epub': 7, 'dir': 8, 'unknown': 9
        }
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        command = Command()
        command.refresh_filetypes()

        expected_types = [
            '.mp4', '.mp3', '.zip', '.html', '.jpg',
            '.txt', '.md', '.url', '.link', '.pdf',
            '.epub', '.dir', '.none'
        ]

        for ext in expected_types:
            assert filetypes.objects.filter(fileext=ext).exists(), f"{ext} should exist"

    @patch('filetypes.management.commands.refresh_filetypes.settings')
    @patch('filetypes.management.commands.refresh_filetypes.pathlib.Path')
    def test_refresh_is_idempotent(self, mock_path, mock_settings):
        """Test refresh can be run multiple times safely"""
        mock_settings.MOVIE_FILE_TYPES = ['.mp4']
        mock_settings.AUDIO_FILE_TYPES = []
        mock_settings.ARCHIVE_FILE_TYPES = []
        mock_settings.HTML_FILE_TYPES = []
        mock_settings.GRAPHIC_FILE_TYPES = []
        mock_settings.TEXT_FILE_TYPES = []
        mock_settings.MARKDOWN_FILE_TYPES = []
        mock_settings.LINK_FILE_TYPES = []
        mock_settings.FTYPES = {'movie': 1}
        mock_settings.ICONS_PATH = '/test/icons'

        mock_path_instance = Mock()
        mock_path_instance.read_bytes.return_value = b"image_data"
        mock_path.return_value = mock_path_instance

        command = Command()
        command.refresh_filetypes()
        count1 = filetypes.objects.count()

        command.refresh_filetypes()
        count2 = filetypes.objects.count()

        assert count1 == count2
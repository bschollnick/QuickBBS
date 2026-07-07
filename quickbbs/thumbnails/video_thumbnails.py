"""FFMPEG backend for video thumbnail generation."""

import io
from fractions import Fraction
from pathlib import Path
from typing import Any

import ffmpeg
from PIL import Image

try:
    from .Abstractbase_thumbnails import AbstractBackend
    from .exceptions import UnsupportedFormatError, VideoProcessingError
    from .pil_thumbnails import ImageBackend, convert_image_for_format
except ImportError:
    from Abstractbase_thumbnails import AbstractBackend
    from exceptions import UnsupportedFormatError, VideoProcessingError
    from pil_thumbnails import ImageBackend, convert_image_for_format


class VideoBackend(AbstractBackend):
    """FFMPEG backend for video thumbnail generation.

    Uses ffmpeg-python to extract frames from video files and processes
    them using the PIL backend for thumbnail generation.
    Includes optimization for backend reuse.

    Example:
        >>> backend = VideoBackend()
        >>> thumbs = backend.process_from_file(
        ...     "/albums/clips/sample.mp4",
        ...     sizes={"small": (200, 200), "large": (1024, 1024)},
        ...     output_format="JPEG",
        ...     quality=85,
        ... )
        >>> sorted(thumbs)
        ['duration', 'format', 'large', 'small']
    """

    __slots__ = ("_image_backend",)

    def __init__(self):
        # Cache ImageBackend instance for reuse
        self._image_backend = ImageBackend()

    def process_from_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """
        Process a video file and generate thumbnails from a frame at its midpoint.

        Extracts a single frame at half the video's duration via FFmpeg, then
        resizes it to each requested size using the PIL image backend.

        Args:
            file_path: Path to the video file.
            sizes: Dictionary mapping size names to (width, height) tuples.
            output_format: Output format (JPEG, PNG, WEBP).
            quality: Image quality (1-100).

        Returns:
            Dictionary with 'duration' (float seconds), 'format' (the output
            format string), and one entry per size name mapping to the
            thumbnail bytes.

        Raises:
            FileNotFoundError: If the video file does not exist.
            VideoProcessingError: If FFmpeg cannot probe the file or extract a frame.
        """
        output = {}
        video_data = _get_video_info(file_path)
        output["duration"] = video_data["duration"]
        height, width = video_data["height"], video_data["width"]
        capture_time = int(video_data["duration"] / 2)  # Capture at half the duration
        thumbnail = _generate_thumbnail_to_pil(file_path, time_offset=capture_time, width=width, height=height)
        pillow_output = self._image_backend._process_pil_image(thumbnail, sizes, output_format, quality)
        output["format"] = output_format
        output.update(pillow_output)
        return output

    def process_from_memory(
        self,
        image_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """
        Process an image from memory and generate thumbnails.

        Args:
            image_bytes: Image data as bytes.
            sizes: Dictionary mapping size names to (width, height) tuples.
            output_format: Output format (JPEG, PNG, WEBP).
            quality: Image quality (1-100).

        Returns:
            Dictionary mapping size names to thumbnail bytes.
        """
        with Image.open(io.BytesIO(image_bytes)) as img:
            return self._process_pil_image(img, sizes, output_format, quality)

    def process_data(
        self,
        pil_image: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """
        Process a PIL Image object and generate thumbnails.

        Args:
            pil_image: PIL Image object to process.
            sizes: Dictionary mapping size names to (width, height) tuples.
            output_format: Output format (JPEG, PNG, WEBP).
            quality: Image quality (1-100).

        Returns:
            Dictionary mapping size names to thumbnail bytes.
        """
        img_copy = pil_image.copy()
        return self._process_pil_image(img_copy, sizes, output_format, quality)


def _generate_thumbnail_to_pil(
    video_path: str,
    time_offset: str | int = "00:00:10",
    width: int = 320,
    height: int = 240,
) -> Image.Image:
    """
    Generate a thumbnail from a video file and return it as a PIL Image.

    Extracts a single MJPEG frame via FFmpeg at the requested time offset,
    scaled to fit within width x height (aspect ratio preserved, padded
    with black to the exact dimensions).

    Args:
        video_path: Path to the input video file.
        time_offset: Time position to capture thumbnail (format: HH:MM:SS
            string, or seconds as an int).
        width: Thumbnail width in pixels.
        height: Thumbnail height in pixels.

    Returns:
        PIL Image object of the extracted video frame.

    Raises:
        FileNotFoundError: If the video file does not exist.
        VideoProcessingError: If FFmpeg exits with an error or produces no
            frame data (e.g. corrupt stream, seek past the last frame).
    """
    video_path = Path(video_path)

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    try:
        # Use ffmpeg with hardware-accelerated scaling to extract frame at target size
        process = (
            ffmpeg.input(str(video_path), ss=time_offset)
            .filter("scale", width, height, force_original_aspect_ratio="decrease")
            .filter("pad", width, height, -1, -1, "black")
            .output("pipe:", vframes=1, format="image2", vcodec="mjpeg", qscale=2)
            .run_async(pipe_stdout=True, pipe_stderr=True, quiet=True)
        )

        # Read the raw image data
        raw_data, stderr = process.communicate()

        if process.returncode != 0:
            raise VideoProcessingError(
                f"FFmpeg error: {stderr.decode(errors='replace')}",
                file_path=str(video_path),
            )

        # FFmpeg can exit 0 without emitting a frame (corrupt stream, seek past
        # the last decodable frame). Raise with ffmpeg's stderr instead of
        # letting PIL fail on empty bytes with a misleading
        # "cannot identify image file <_io.BytesIO>" error.
        if not raw_data:
            raise VideoProcessingError(
                f"FFmpeg produced no frame data: {stderr.decode(errors='replace')}",
                file_path=str(video_path),
            )

        # Create PIL Image from JPEG data
        image = Image.open(io.BytesIO(raw_data))

        return image

    except ffmpeg.Error as e:
        raise VideoProcessingError(f"FFmpeg error: {e}", file_path=str(video_path)) from e


# def _generate_multiple_thumbnails_pil(video_path, count=5, width=320, height=240):
#     """
#     Generate multiple thumbnails at different time intervals as PIL Images.

#     Args:
#         video_path (str): Path to the input video file
#         count (int): Number of thumbnails to generate
#         width (int): Thumbnail width
#         height (int): Thumbnail height

#     Returns:
#         list: List of tuples (time_offset, PIL.Image)
#     """
#     video_path = Path(video_path)

#     if not video_path.exists():
#         raise FileNotFoundError(f"Video file not found: {video_path}")

#     # Get video duration
#     try:
#         probe = ffmpeg.probe(str(video_path))
#         duration = float(probe["streams"][0]["duration"])
#     except (ffmpeg.Error, KeyError):
#         duration = 300  # Fallback duration

#     thumbnails = []

#     for i in range(count):
#         # Calculate time offset
#         time_offset_seconds = (duration / (count + 1)) * (i + 1)
#         time_str = f"{int(time_offset_seconds // 3600):02d}:"\
#           f"{int((time_offset_seconds % 3600) // 60):02d}:{int(time_offset_seconds % 60):02d}"

#         try:
#             image = generate_thumbnail_to_pil(
#                 video_path, time_offset=time_str, width=width, height=height
#             )
#             thumbnails.append((time_str, image))

#         except Exception as e:
#             print(f"Error generating thumbnail {i+1}: {e}")
#             continue

#     return thumbnails


def _get_video_info(video_path: str) -> dict[str, Any]:
    """
    Get basic information about a video file using ffprobe.

    Args:
        video_path: Path to the video file.

    Returns:
        Dictionary with keys 'duration' (float seconds), 'width', 'height'
        (ints), 'fps' (float), 'codec' (codec name string), and 'format'
        (container format string).

    Raises:
        VideoProcessingError: If the ffprobe call fails or the file contains
            no video stream.

    Example:
        >>> info = _get_video_info("/albums/clips/sample.mp4")
        >>> info["duration"], info["codec"]
        (66.7, 'h264')
    """
    try:
        probe = ffmpeg.probe(str(video_path))
        video_stream = next(
            (stream for stream in probe["streams"] if stream["codec_type"] == "video"),
            None,
        )

        if video_stream is None:
            raise VideoProcessingError("No video stream found", file_path=str(video_path))

        fps_fraction = Fraction(video_stream["r_frame_rate"])

        info = {
            "duration": float(probe["format"]["duration"]),
            "width": int(video_stream["width"]),
            "height": int(video_stream["height"]),
            "fps": float(fps_fraction),
            "codec": video_stream["codec_name"],
            "format": probe["format"]["format_name"],
        }

        return info

    except ffmpeg.Error as e:
        raise VideoProcessingError(f"Error getting video info: {e}", file_path=str(video_path)) from e


def _pil_to_binary(image: Image.Image, img_format: str = "JPEG", quality: int = 85) -> bytes:
    """
    Convert a PIL Image to binary data.

    Args:
        image: PIL Image object to convert.
        img_format: Output format (JPEG, PNG, or WEBP).
        quality: Quality for JPEG/WEBP (1-100). Ignored for PNG.

    Returns:
        Binary image data as bytes.

    Raises:
        UnsupportedFormatError: If a format other than JPEG, PNG, or WEBP
            is specified.
    """
    output_buffer = io.BytesIO()

    # Convert image to appropriate color mode for target format
    image = convert_image_for_format(image, img_format)

    if img_format.upper() == "JPEG":
        image.save(output_buffer, format="JPEG", quality=quality, optimize=True)
    elif img_format.upper() == "PNG":
        image.save(output_buffer, format="PNG", optimize=True)
    elif img_format.upper() == "WEBP":
        image.save(output_buffer, format="WEBP", quality=quality, optimize=True)
    else:
        raise UnsupportedFormatError(img_format)

    binary_data = output_buffer.getvalue()
    output_buffer.close()

    return binary_data


# Example usage
if __name__ == "__main__":
    # Single thumbnail
    # try:
    #     video_file = "sample_video.mp4"  # Replace with your video file
    #     thumbnail_path = _generate_thumbnail(video_file, time_offset="00:01:30")
    #     print(f"Thumbnail generated: {thumbnail_path}")

    #     # Multiple thumbnails
    #     thumbnails = _generate_multiple_thumbnails(video_file, count=3)
    #     print(f"Generated {len(thumbnails)} thumbnails")

    #     # Video info
    #     info = _get_video_info(video_file)
    #     print(f"Video info: {info}")

    # except Exception as e:
    #     print(f"Error: {e}")
    video_file = "test.mp4"
    processor = VideoBackend()
    result = processor.process_from_file(
        video_file,
        sizes={"small": (320, 240), "medium": (640, 480), "large": (1280, 720)},
        output_format="PNG",
        quality=85,
    )
    print(result.keys())
    print(f"Duration: {result['duration']} seconds")
    print(f"Format: {result['format']}")
    print(f"size of small thumbnail: {len(result['small'])} bytes")
    print(f"size of medium thumbnail: {len(result['medium'])} bytes")
    print(f"size of large thumbnail: {len(result['large'])} bytes")
    # print(output)

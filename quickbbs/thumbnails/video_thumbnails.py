import io
from pathlib import Path

import ffmpeg
from PIL import Image

try:
    from .Abstractbase_thumbnails import AbstractBackend
    from .pil_thumbnails import ImageBackend
except ImportError:
    from Abstractbase_thumbnails import AbstractBackend
    from pil_thumbnails import ImageBackend


class VideoBackend(AbstractBackend):
    """FFMPEG backend for cross-platform image processing."""

    def process_from_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        output = {}
        video_data = _get_video_info(file_path)
        output["duration"] = video_data["duration"]
        height, width = video_data["height"], video_data["width"]
        capture_time = int(video_data["duration"] / 2)  # Capture at half the duration
        thumbnail = _generate_thumbnail_to_pil(
            file_path, time_offset=capture_time, width=width, height=height
        )
        converter = ImageBackend()
        pillow_output = converter._process_pil_image(
            thumbnail, sizes, output_format, quality
        )
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
        with Image.open(io.BytesIO(image_bytes)) as img:
            return self._process_pil_image(img, sizes, output_format, quality)

    def process_data(
        self,
        pil_image: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        img_copy = pil_image.copy()
        return self._process_pil_image(img_copy, sizes, output_format, quality)


def _generate_thumbnail_to_pil(
    video_path, time_offset="00:00:10", width=320, height=240
):
    """
    Generate a thumbnail from a video file and return it as a PIL Image.

    Args:
        video_path (str): Path to the input video file
        time_offset (str): Time position to capture thumbnail (format: HH:MM:SS)
        width (int): Thumbnail width in pixels
        height (int): Thumbnail height in pixels

    Returns:
        PIL.Image: PIL Image object
    """
    video_path = Path(video_path)

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    try:
        # Use ffmpeg to extract frame to stdout as PNG data
        process = (
            ffmpeg.input(str(video_path), ss=time_offset)
            .output("pipe:", vframes=1, format="image2", vcodec="png")
            .run_async(pipe_stdout=True, pipe_stderr=True, quiet=True)
        )

        # Read the raw image data
        raw_data, stderr = process.communicate()

        if process.returncode != 0:
            raise Exception(f"FFmpeg error: {stderr.decode()}")

        # Create PIL Image from raw data
        image = Image.open(io.BytesIO(raw_data))

        # Resize if needed
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.LANCZOS)

        return image

    except ffmpeg.Error as e:
        raise Exception(f"FFmpeg error: {e}")


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


def _get_video_info(video_path):
    """
    Get basic information about a video file.

    Args:
        video_path (str): Path to the video file

    Returns:
        dict: Video information
    """
    try:
        probe = ffmpeg.probe(str(video_path))
        video_stream = next(
            (stream for stream in probe["streams"] if stream["codec_type"] == "video"),
            None,
        )

        if video_stream is None:
            raise Exception("No video stream found")

        info = {
            "duration": float(probe["format"]["duration"]),
            "width": int(video_stream["width"]),
            "height": int(video_stream["height"]),
            "fps": eval(video_stream["r_frame_rate"]),
            "codec": video_stream["codec_name"],
            "format": probe["format"]["format_name"],
        }

        return info

    except ffmpeg.Error as e:
        raise Exception(f"Error getting video info: {e}")


def _pil_to_binary(image, format="JPEG", quality=85):
    """
    Convert PIL Image to binary data when needed.

    Args:
        image (PIL.Image): PIL Image object
        format (str): Output format ('JPEG', 'PNG', 'WEBP')
        quality (int): Quality for JPEG/WEBP (1-100)

    Returns:
        bytes: Binary image data
    """
    output_buffer = io.BytesIO()

    if format.upper() == "JPEG":
        # Convert RGBA to RGB for JPEG compatibility
        if image.mode in ("RGBA", "LA"):
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(
                image, mask=image.split()[-1] if image.mode == "RGBA" else None
            )
            image = background
        image.save(output_buffer, format="JPEG", quality=quality, optimize=True)
    elif format.upper() == "PNG":
        image.save(output_buffer, format="PNG", optimize=True)
    elif format.upper() == "WEBP":
        image.save(output_buffer, format="WEBP", quality=quality, optimize=True)
    else:
        raise ValueError(f"Unsupported format: {format}")

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
    output = processor.process_from_file(
        video_file,
        sizes={"small": (320, 240), "medium": (640, 480), "large": (1280, 720)},
        output_format="PNG",
        quality=85,
    )
    print(output.keys())
    print(f"Duration: {output['duration']} seconds")
    print(f"Format: {output['format']}")
    print(f"size of small thumbnail: {len(output['small'])} bytes")
    print(f"size of medium thumbnail: {len(output['medium'])} bytes")
    print(f"size of large thumbnail: {len(output['large'])} bytes")
    # print(output)

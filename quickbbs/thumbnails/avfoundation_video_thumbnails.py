"""AVFoundation backend for video thumbnail generation (macOS native)."""

# pylint: disable=no-name-in-module  # pyobjc uses dynamic imports

import io
from pathlib import Path

from PIL import Image

# Try to import AVFoundation and related macOS frameworks
try:
    from AVFoundation import (
        AVAsset,
        AVAssetImageGenerator,
        AVAssetImageGeneratorApertureModeCleanAperture,
    )
    from CoreMedia import CMTimeMake
    from Foundation import NSURL, NSData
    from Quartz import (
        CGImageDestinationAddImage,
        CGImageDestinationCreateWithData,
        CGImageDestinationFinalize,
        CIContext,
        CIImage,
        UTType,
    )

    AVFOUNDATION_AVAILABLE = True
except ImportError:
    AVFOUNDATION_AVAILABLE = False

try:
    from .Abstractbase_thumbnails import AbstractBackend
    from .core_image_thumbnails import CoreImageBackend
except ImportError:
    from Abstractbase_thumbnails import AbstractBackend
    from core_image_thumbnails import CoreImageBackend


class AVFoundationVideoBackend(AbstractBackend):
    """AVFoundation backend for video thumbnail generation.

    Uses macOS native AVFoundation framework to extract frames from video files
    and processes them using Core Image for GPU-accelerated thumbnail generation.
    """

    def __init__(self):
        """Initialize AVFoundation video backend.

        :raises ImportError: If AVFoundation is not available (non-macOS)
        """
        if not AVFOUNDATION_AVAILABLE:
            raise ImportError("AVFoundation not available. This backend requires macOS with pyobjc-framework-avfoundation.")

        # Prevent dock icon from appearing (AVFoundation can trigger AppKit in some cases)
        try:
            from AppKit import (
                NSApplication,
                NSApplicationActivationPolicyProhibited,
            )

            app = NSApplication.sharedApplication()
            app.setActivationPolicy_(NSApplicationActivationPolicyProhibited)
        except ImportError:
            pass  # AppKit not available

        # Cache CoreImageBackend instance for reuse
        self._image_backend = CoreImageBackend()

    def process_from_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """Process video file and generate thumbnails using AVFoundation.

        :Args:
            file_path: Path to video file
            sizes: Dictionary mapping size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        :return: Dictionary with 'duration', 'format', and size-keyed thumbnail bytes
        :raises FileNotFoundError: If video file doesn't exist
        :raises RuntimeError: If video processing fails
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Video file not found: {file_path}")

        output = {}

        # Get video metadata
        video_data = _get_video_info(str(file_path))
        output["duration"] = video_data["duration"]

        # Calculate capture time (middle of video)
        capture_time = video_data["duration"] / 2.0

        # Extract frame as CIImage using AVFoundation
        ci_image = _extract_frame_as_ciimage(str(file_path), capture_time)

        # Process using Core Image backend for GPU-accelerated thumbnails
        # pylint: disable=protected-access
        image_output = self._image_backend._process_ci_image(ci_image, sizes, output_format, quality)

        output["format"] = output_format
        output.update(image_output)

        return output

    def process_from_memory(
        self,
        image_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """Process image from memory and generate thumbnails.

        Note: This delegates to Core Image backend as AVFoundation
        works with video files, not image data.

        :Args:
            image_bytes: Image data as bytes
            sizes: Dictionary mapping size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        :return: Dictionary mapping size names to thumbnail bytes
        """
        return self._image_backend.process_from_memory(image_bytes, sizes, output_format, quality)

    def process_data(
        self,
        pil_image: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """Process PIL Image object and generate thumbnails.

        Note: This delegates to Core Image backend.

        :Args:
            pil_image: PIL Image object to process
            sizes: Dictionary mapping size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        :return: Dictionary mapping size names to thumbnail bytes
        """
        return self._image_backend.process_data(pil_image, sizes, output_format, quality)


def _extract_frame_as_ciimage(video_path: str, time_offset: float) -> "CIImage":
    """Extract a single frame from video as CIImage using AVFoundation.

    :Args:
        video_path: Path to the input video file
        time_offset: Time position in seconds to capture thumbnail

    :return: CIImage object of the video frame
    :raises RuntimeError: If frame extraction fails
    """
    # Create URL for video file
    file_url = NSURL.fileURLWithPath_(video_path)

    # Load video asset
    asset = AVAsset.assetWithURL_(file_url)

    if asset is None:
        raise RuntimeError(f"Could not load video asset from {video_path}")

    # Create image generator
    generator = AVAssetImageGenerator.assetImageGeneratorWithAsset_(asset)

    # Configure generator for best quality
    generator.setAppliesPreferredTrackTransform_(True)  # Handle rotation
    generator.setApertureMode_(AVAssetImageGeneratorApertureModeCleanAperture)  # Clean aperture mode

    # Create CMTime for requested timestamp
    time_scale = 600  # Standard timescale for video
    time_value = int(time_offset * time_scale)
    requested_time = CMTimeMake(time_value, time_scale)

    # Extract frame
    try:
        # copyCGImageAtTime_actualTime_error_ returns (CGImage, actualTime) and raises on error
        extraction_result = generator.copyCGImageAtTime_actualTime_error_(requested_time, None, None)

        if extraction_result is None or len(extraction_result) < 1:
            raise RuntimeError("Failed to extract frame from video")

        # Result is (CGImage, actualTime)
        cg_image = extraction_result[0]

        if cg_image is None:
            raise RuntimeError("Failed to extract frame from video")

        # Convert CGImage to CIImage
        ci_image = CIImage.imageWithCGImage_(cg_image)

        # Clean up CGImage (important for memory management)
        del cg_image

        return ci_image

    except Exception as e:
        raise RuntimeError(f"Error extracting frame: {e}") from e
    finally:
        # Clean up generator
        generator = None
        asset = None


def _get_video_info(video_path: str) -> dict[str, any]:
    """Get basic information about a video file using AVFoundation.

    :Args:
        video_path: Path to the video file

    :return: Dictionary containing video metadata (duration, width, height, fps, codec, format)
    :raises RuntimeError: If video info extraction fails
    """
    # Create URL for video file
    file_url = NSURL.fileURLWithPath_(video_path)

    # Load video asset
    asset = AVAsset.assetWithURL_(file_url)

    if asset is None:
        raise RuntimeError(f"Could not load video asset from {video_path}")

    try:
        # Get duration
        duration_cmtime = asset.duration()
        duration = float(duration_cmtime.value) / float(duration_cmtime.timescale)

        # Get video tracks
        video_tracks = asset.tracksWithMediaType_("vide")  # 'vide' is the media type for video

        if not video_tracks or len(video_tracks) == 0:
            raise RuntimeError("No video tracks found in file")

        video_track = video_tracks[0]

        # Get video dimensions
        natural_size = video_track.naturalSize()
        width = int(natural_size.width)
        height = int(natural_size.height)

        # Get frame rate
        nominal_frame_rate = video_track.nominalFrameRate()

        # Get format descriptions for codec info
        format_descriptions = video_track.formatDescriptions()
        codec = "unknown"
        if format_descriptions and len(format_descriptions) > 0:
            # This is a simplified approach - format descriptions are complex
            codec = str(format_descriptions[0])

        info = {
            "duration": duration,
            "width": width,
            "height": height,
            "fps": float(nominal_frame_rate),
            "codec": codec,
            "format": "video",  # AVFoundation doesn't expose container format as easily
        }

        return info

    except Exception as e:
        raise RuntimeError(f"Error getting video info: {e}") from e
    finally:
        # Clean up
        asset = None


def _extract_frame_as_pil(video_path: str, time_offset: float, width: int = 320, height: int = 240) -> Image.Image:  # pylint: disable=unused-argument
    """Extract a frame from video as PIL Image (for compatibility).

    This function provides compatibility with the FFmpeg-based implementation
    but is less efficient than using _extract_frame_as_ciimage directly.

    :Args:
        video_path: Path to the input video file
        time_offset: Time position in seconds to capture thumbnail
        width: Target width (for reference, actual scaling done by Core Image)
        height: Target height (for reference, actual scaling done by Core Image)

    :return: PIL Image object of the video frame
    :raises RuntimeError: If frame extraction fails
    """
    # Extract as CIImage
    ci_image = _extract_frame_as_ciimage(video_path, time_offset)

    # Render to PNG bytes using Core Image context
    context = CIContext.context()
    extent = ci_image.extent()
    cg_image = context.createCGImage_fromRect_(ci_image, extent)

    if cg_image is None:
        raise RuntimeError("Failed to render CIImage to CGImage")

    try:
        # Convert to PNG data
        output_data = NSData.data().mutableCopy()
        uti_type = UTType.typeWithIdentifier_("public.png")
        destination = CGImageDestinationCreateWithData(output_data, uti_type.identifier(), 1, None)

        if destination is None:
            raise RuntimeError("Failed to create image destination")

        try:
            CGImageDestinationAddImage(destination, cg_image, None)

            if not CGImageDestinationFinalize(destination):
                raise RuntimeError("Failed to finalize image destination")

            # Convert to PIL Image
            image_bytes = bytes(output_data)
            image = Image.open(io.BytesIO(image_bytes))

            return image

        finally:
            del destination

    finally:
        del cg_image


# Example usage and testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python avfoundation_video_thumbnails.py <video_file>")
        sys.exit(1)

    video_file = sys.argv[1]

    if not Path(video_file).exists():
        print(f"Error: Video file not found: {video_file}")
        sys.exit(1)

    try:
        # Test video info extraction
        print("=" * 60)
        print("Video Information")
        print("=" * 60)
        video_info = _get_video_info(video_file)
        print(f"Duration: {video_info['duration']:.2f} seconds")
        print(f"Dimensions: {video_info['width']}x{video_info['height']}")
        print(f"Frame Rate: {video_info['fps']:.2f} fps")
        print(f"Codec: {video_info['codec']}")
        print()

        # Test thumbnail generation
        print("=" * 60)
        print("Generating Thumbnails")
        print("=" * 60)
        backend = AVFoundationVideoBackend()
        result = backend.process_from_file(
            video_file,
            sizes={"small": (200, 200), "medium": (740, 740), "large": (1024, 1024)},
            output_format="JPEG",
            quality=85,
        )

        print(f"Duration: {result['duration']:.2f} seconds")
        print(f"Format: {result['format']}")
        print(f"Small thumbnail: {len(result['small']):,} bytes")
        print(f"Medium thumbnail: {len(result['medium']):,} bytes")
        print(f"Large thumbnail: {len(result['large']):,} bytes")

        # Optional: Save thumbnails for visual inspection
        for size_name, data in result.items():
            if size_name in ("small", "medium", "large"):
                output_path = f"test_thumb_{size_name}.jpg"
                with open(output_path, "wb") as f:
                    f.write(data)
                print(f"Saved {size_name} thumbnail to {output_path}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

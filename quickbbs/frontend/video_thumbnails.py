import ffmpeg
import os
from pathlib import Path

def generate_thumbnail(video_path, output_path=None, time_offset="00:00:10", width=320, height=240):
    """
    Generate a thumbnail from a video file.
    
    Args:
        video_path (str): Path to the input video file
        output_path (str): Path for the output thumbnail (optional)
        time_offset (str): Time position to capture thumbnail (format: HH:MM:SS)
        width (int): Thumbnail width in pixels
        height (int): Thumbnail height in pixels
    
    Returns:
        str: Path to the generated thumbnail
    """
    video_path = Path(video_path)
    
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    # Generate output path if not provided
    if output_path is None:
        output_path = video_path.with_suffix('.jpg')
    
    try:
        # Create thumbnail using ffmpeg
        (
            ffmpeg
            .input(str(video_path), ss=time_offset)
            .output(str(output_path), vframes=1, s=f'{width}x{height}')
            .overwrite_output()
            .run(quiet=True)
        )
        
        return str(output_path)
        
    except ffmpeg.Error as e:
        raise Exception(f"FFmpeg error: {e}")

def generate_multiple_thumbnails(video_path, output_dir=None, count=5, width=320, height=240):
    """
    Generate multiple thumbnails at different time intervals.
    
    Args:
        video_path (str): Path to the input video file
        output_dir (str): Directory for output thumbnails
        count (int): Number of thumbnails to generate
        width (int): Thumbnail width
        height (int): Thumbnail height
    
    Returns:
        list: Paths to generated thumbnails
    """
    video_path = Path(video_path)
    
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    # Get video duration
    try:
        probe = ffmpeg.probe(str(video_path))
        duration = float(probe['streams'][0]['duration'])
    except (ffmpeg.Error, KeyError):
        # Fallback duration if probe fails
        duration = 300  # 5 minutes
    
    # Setup output directory
    if output_dir is None:
        output_dir = video_path.parent / f"{video_path.stem}_thumbnails"
    
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)
    
    thumbnails = []
    
    for i in range(count):
        # Calculate time offset for each thumbnail
        time_offset = (duration / (count + 1)) * (i + 1)
        time_str = f"{int(time_offset // 3600):02d}:{int((time_offset % 3600) // 60):02d}:{int(time_offset % 60):02d}"
        
        output_path = output_dir / f"thumb_{i+1:02d}.jpg"
        
        try:
            (
                ffmpeg
                .input(str(video_path), ss=time_str)
                .output(str(output_path), vframes=1, s=f'{width}x{height}')
                .overwrite_output()
                .run(quiet=True)
            )
            
            thumbnails.append(str(output_path))
            
        except ffmpeg.Error as e:
            print(f"Error generating thumbnail {i+1}: {e}")
            continue
    
    return thumbnails

def get_video_info(video_path):
    """
    Get basic information about a video file.
    
    Args:
        video_path (str): Path to the video file
    
    Returns:
        dict: Video information
    """
    try:
        probe = ffmpeg.probe(str(video_path))
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        
        if video_stream is None:
            raise Exception("No video stream found")
        
        info = {
            'duration': float(probe['format']['duration']),
            'width': int(video_stream['width']),
            'height': int(video_stream['height']),
            'fps': eval(video_stream['r_frame_rate']),
            'codec': video_stream['codec_name'],
            'format': probe['format']['format_name']
        }
        
        return info
        
    except ffmpeg.Error as e:
        raise Exception(f"Error getting video info: {e}")

# Example usage
if __name__ == "__main__":
    # Single thumbnail
    try:
        video_file = "sample_video.mp4"  # Replace with your video file
        thumbnail_path = generate_thumbnail(video_file, time_offset="00:01:30")
        print(f"Thumbnail generated: {thumbnail_path}")
        
        # Multiple thumbnails
        thumbnails = generate_multiple_thumbnails(video_file, count=3)
        print(f"Generated {len(thumbnails)} thumbnails")
        
        # Video info
        info = get_video_info(video_file)
        print(f"Video info: {info}")
        
    except Exception as e:
        print(f"Error: {e}")
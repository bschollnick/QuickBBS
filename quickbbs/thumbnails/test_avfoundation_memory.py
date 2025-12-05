"""Test memory usage during AVFoundation video thumbnail generation.

This script tests for memory leaks by generating thumbnails repeatedly
and measuring memory growth. With proper autorelease pool management,
memory growth should be minimal.

Usage:
    python test_avfoundation_memory.py [video_file] [iterations]

    If video_file is not provided, uses 'test.mp4' in current directory.
    If iterations is not provided, defaults to 100.

Expected Results (AFTER autorelease pool fixes):
    - Total growth: <50 MB after 100 videos
    - Average growth: <500 KB per video
    - Memory should stabilize after initial warmup

Before Fixes (without autorelease pools):
    - Total growth: 500+ MB after 100 videos
    - Average growth: 5+ MB per video
    - Memory continues to grow unbounded
"""

import resource
import sys
from pathlib import Path


def measure_memory_mb():
    """
    Get current memory usage in MB (macOS).

    Returns:
        float: Memory usage in megabytes
    """
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # macOS returns ru_maxrss in bytes, convert to MB
    return usage.ru_maxrss / (1024 * 1024)


def test_memory_leak(video_file: str, iterations: int = 100):
    """
    Test memory growth during video thumbnail generation.

    Args:
        video_file: Path to test video file
        iterations: Number of thumbnails to generate (default: 100)
    """
    video_path = Path(video_file)

    if not video_path.exists():
        print(f"Error: Video file not found: {video_file}")
        print("\nPlease provide a valid video file path:")
        print(f"  python {Path(__file__).name} /path/to/video.mp4 [iterations]")
        sys.exit(1)

    # Import backend (after file check to avoid unnecessary import errors)
    try:
        from avfoundation_video_thumbnails import AVFoundationVideoBackend
    except ImportError as e:
        print(f"Error: Could not import AVFoundation backend: {e}")
        print("\nThis test requires macOS with PyObjC frameworks installed.")
        sys.exit(1)

    # Define thumbnail sizes (same as production)
    SIZES = {"large": (1024, 1024), "medium": (740, 740), "small": (200, 200)}

    print("=" * 70)
    print("AVFoundation Video Thumbnail Memory Leak Test")
    print("=" * 70)
    print(f"Test video:   {video_path}")
    print(f"Iterations:   {iterations}")
    print(f"Sizes:        {SIZES}")
    print("-" * 70)

    # Initialize backend
    try:
        backend = AVFoundationVideoBackend()
    except Exception as e:
        print(f"Error: Failed to initialize AVFoundation backend: {e}")
        sys.exit(1)

    # Warmup run (not counted)
    print("\nWarmup: Generating initial thumbnail...")
    try:
        backend.process_from_file(str(video_path), SIZES, "JPEG", 85)
        print("Warmup complete.\n")
    except Exception as e:
        print(f"Error during warmup: {e}")
        sys.exit(1)

    # Measure starting memory after warmup
    start_memory = measure_memory_mb()
    print(f"Starting memory: {start_memory:.1f} MB")
    print()

    # Generate thumbnails and track memory
    report_interval = max(1, iterations // 10)  # Report 10 times

    for i in range(iterations):
        try:
            result = backend.process_from_file(str(video_path), SIZES, "JPEG", 85)

            # Verify thumbnails were created
            if "small" not in result or "medium" not in result or "large" not in result:
                print(f"Warning: Incomplete thumbnail set at iteration {i + 1}")

        except Exception as e:
            print(f"Error at iteration {i + 1}: {e}")
            continue

        # Report progress periodically
        if (i + 1) % report_interval == 0:
            current = measure_memory_mb()
            growth = current - start_memory
            avg_growth = growth / (i + 1)

            print(
                f"After {i + 1:4d} videos: "
                f"{current:6.1f} MB "
                f"(growth: {growth:5.1f} MB, "
                f"avg: {avg_growth * 1000:.2f} KB/video)"
            )

    # Final measurements
    end_memory = measure_memory_mb()
    total_growth = end_memory - start_memory
    avg_per_video = total_growth / iterations

    print()
    print("=" * 70)
    print("RESULTS:")
    print("=" * 70)
    print(f"  Total iterations:     {iterations}")
    print(f"  Starting memory:      {start_memory:.1f} MB")
    print(f"  Ending memory:        {end_memory:.1f} MB")
    print(f"  Total growth:         {total_growth:.1f} MB")
    print(f"  Avg per video:        {avg_per_video * 1000:.2f} KB")
    print("=" * 70)

    # Evaluation
    print()
    if avg_per_video > 0.5:  # More than 500KB per video
        print("⚠️  HIGH MEMORY GROWTH - Likely leak present")
        print("    Expected: <500 KB per video")
        print("    Actual:   {:.2f} KB per video".format(avg_per_video * 1000))
        print()
        print("    Possible causes:")
        print("    - Autorelease pools not properly implemented")
        print("    - Missing autorelease_pool() wrappers")
        print("    - Backend caching not being cleared")
    elif avg_per_video > 0.1:  # 100-500KB per video
        print("⚠️  MODERATE MEMORY GROWTH - Some accumulation occurring")
        print("    Expected: <100 KB per video")
        print("    Actual:   {:.2f} KB per video".format(avg_per_video * 1000))
        print()
        print("    This may be acceptable but should be monitored.")
    else:
        print("✅  LOW MEMORY GROWTH - Memory management working well")
        print("    Average growth: {:.2f} KB per video (excellent!)".format(avg_per_video * 1000))

    print()


if __name__ == "__main__":
    # Parse command line arguments
    video_file = "test.mp4"
    iterations = 100

    if len(sys.argv) > 1:
        video_file = sys.argv[1]

    if len(sys.argv) > 2:
        try:
            iterations = int(sys.argv[2])
            if iterations < 1:
                print("Error: Iterations must be at least 1")
                sys.exit(1)
        except ValueError:
            print(f"Error: Invalid iterations value: {sys.argv[2]}")
            sys.exit(1)

    test_memory_leak(video_file, iterations)

#!/usr/bin/env python3
"""
Benchmark script for comparing thumbnail generation backends.

This script benchmarks Core Image vs PIL/Pillow thumbnail generation performance
by running repeated iterations and collecting detailed timing statistics.

Usage:
    cd thumbnails/benchmarks
    python thumbnail_benchmarks.py

Requirements:
    - test.png (test image file in benchmarks directory)
    - Optional: test.mp4, test.pdf for video/PDF benchmarks
"""

from __future__ import annotations

import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

# Add parent directory to path for imports
BENCHMARKS_DIR = Path(__file__).parent
THUMBNAILS_DIR = BENCHMARKS_DIR.parent
sys.path.insert(0, str(THUMBNAILS_DIR.parent))

# Import after path modification
from thumbnails.thumbnail_engine import (
    AVFOUNDATION_AVAILABLE,
    CORE_IMAGE_AVAILABLE,
    PDFKIT_AVAILABLE,
    create_thumbnails_from_path,
)

# ============================================================================
# Configuration
# ============================================================================

# Number of iterations for each benchmark
ITERATIONS = 100

# Test files (should be in benchmarks directory)
TEST_IMAGES = ["small_test.jpg", "medium_test.jpg", "large_test.png"]
TEST_VIDEO = "test.mp4"
TEST_PDF = "test.pdf"

# Thumbnail sizes
IMAGE_SIZES = {"large": (1024, 1024), "medium": (740, 740), "small": (200, 200)}

# Output quality
JPEG_QUALITY = 85

# Save output files (disable for pure speed test)
SAVE_OUTPUT = True

# Output directory for test files
OUTPUT_DIR = "test_output"

# Global output file for logging (set in main())
_output_file: TextIO | None = None


# ============================================================================
# Utility Functions
# ============================================================================


def tee_print(message: str = "") -> None:
    """
    Print to both console and output file.

    Args:
        message: Message to print
    """
    print(message)
    if _output_file:
        _output_file.write(message + "\n")
        _output_file.flush()


def format_time(seconds: float) -> str:
    """
    Format time in human-readable format.

    Args:
        seconds: Time in seconds

    Returns:
        Formatted string (e.g., "1.234s" or "123.4ms")
    """
    if seconds >= 1.0:
        return f"{seconds:.3f}s"
    elif seconds >= 0.001:
        return f"{seconds * 1000:.1f}ms"
    else:
        return f"{seconds * 1_000_000:.1f}µs"


def calculate_statistics(times: list[float]) -> dict[str, float]:
    """
    Calculate statistics from timing data.

    Args:
        times: List of timing measurements in seconds

    Returns:
        Dictionary with min, max, mean, median, stdev statistics
    """
    return {
        "min": min(times),
        "max": max(times),
        "mean": statistics.mean(times),
        "median": statistics.median(times),
        "stdev": statistics.stdev(times) if len(times) > 1 else 0.0,
    }


def print_statistics(backend_name: str, total_time: float, times: list[float]) -> None:
    """
    Print formatted statistics for a benchmark run.

    Args:
        backend_name: Name of the backend (e.g., "PIL", "Core Image")
        total_time: Total execution time in seconds
        times: List of individual iteration times
    """
    stats = calculate_statistics(times)

    tee_print(f"\n{'=' * 70}")
    tee_print(f"{backend_name} Results")
    tee_print(f"{'=' * 70}")
    tee_print(f"Total iterations:     {len(times):,}")
    tee_print(f"Total time:           {format_time(total_time)}")
    tee_print(f"Average per iter:     {format_time(stats['mean'])}")
    tee_print(f"Median per iter:      {format_time(stats['median'])}")
    tee_print(f"Min per iter:         {format_time(stats['min'])}")
    tee_print(f"Max per iter:         {format_time(stats['max'])}")
    tee_print(f"Std deviation:        {format_time(stats['stdev'])}")
    tee_print(f"Throughput:           {len(times) / total_time:.1f} images/sec")


def save_thumbnails(thumbnails: dict[str, bytes], prefix: str, iteration: int) -> None:
    """
    Save thumbnail images to disk.

    Args:
        thumbnails: Dictionary mapping size names to binary data
        prefix: Filename prefix (e.g., "pil", "coreimage")
        iteration: Iteration number for unique filenames
    """
    if not SAVE_OUTPUT:
        return

    # Ensure output directory exists
    output_path = Path(OUTPUT_DIR)
    output_path.mkdir(exist_ok=True)

    for size, data in thumbnails.items():
        if size in ["small", "medium", "large"]:
            filename = output_path / f"{prefix}_iter{iteration:04d}_{size}.jpg"
            with open(filename, "wb") as f:
                f.write(data)


# ============================================================================
# Benchmark Functions
# ============================================================================


def benchmark_backend(backend_name: str, backend_type: str, test_file: str, iterations: int) -> tuple[float, list[float]]:
    """
    Benchmark a specific thumbnail generation backend.

    Args:
        backend_name: Display name for the backend
        backend_type: Backend type string ("image", "coreimage", "video", etc.)
        test_file: Path to test file
        iterations: Number of iterations to run

    Returns:
        Tuple of (total_time, list_of_iteration_times)
    """
    tee_print(f"\nBenchmarking {backend_name}...")
    tee_print(f"  Backend:     {backend_type}")
    tee_print(f"  Test file:   {test_file}")
    tee_print(f"  Iterations:  {iterations:,}")

    iteration_times = []
    start_total = time.perf_counter()

    for i in range(iterations):
        start_iter = time.perf_counter()

        try:
            thumbnails = create_thumbnails_from_path(test_file, IMAGE_SIZES, output="JPEG", quality=JPEG_QUALITY, backend=backend_type)

            # Optionally save first and last iteration for verification
            if SAVE_OUTPUT and (i == 0 or i == iterations - 1):
                save_thumbnails(thumbnails, backend_type.lower(), i)

        except Exception as e:  # pylint: disable=broad-exception-caught
            tee_print(f"  ERROR on iteration {i}: {e}")
            continue

        end_iter = time.perf_counter()
        iteration_times.append(end_iter - start_iter)

        # Progress indicator every 100 iterations
        if (i + 1) % 100 == 0:
            tee_print(f"  Progress: {i + 1:,}/{iterations:,} iterations...")

    end_total = time.perf_counter()
    total_time = end_total - start_total

    return total_time, iteration_times


def benchmark_image_backends(test_image: str, iterations: int) -> dict[str, Any]:
    """
    Benchmark image processing backends (PIL vs Core Image).

    Args:
        test_image: Path to test image file
        iterations: Number of iterations per backend

    Returns:
        Dictionary with benchmark results
    """
    results = {}

    # Test PIL backend
    tee_print("\n" + "=" * 70)
    tee_print("PIL/Pillow Backend")
    tee_print("=" * 70)
    pil_total, pil_times = benchmark_backend("PIL/Pillow", "image", test_image, iterations)
    print_statistics("PIL/Pillow", pil_total, pil_times)
    results["pil"] = {"total": pil_total, "times": pil_times}

    # Test Core Image backend (if available)
    if CORE_IMAGE_AVAILABLE:
        tee_print("\n" + "=" * 70)
        tee_print("Core Image Backend (macOS)")
        tee_print("=" * 70)
        ci_total, ci_times = benchmark_backend("Core Image", "coreimage", test_image, iterations)
        print_statistics("Core Image", ci_total, ci_times)
        results["coreimage"] = {"total": ci_total, "times": ci_times}

        # Comparison
        tee_print("\n" + "=" * 70)
        tee_print("Comparison: Core Image vs PIL")
        tee_print("=" * 70)
        speedup = pil_total / ci_total
        tee_print(f"Core Image total time:  {format_time(ci_total)}")
        tee_print(f"PIL total time:         {format_time(pil_total)}")
        tee_print(f"Speedup:                {speedup:.2f}x")

        ci_avg = statistics.mean(ci_times)
        pil_avg = statistics.mean(pil_times)
        avg_speedup = pil_avg / ci_avg
        tee_print(f"\nCore Image avg/iter:    {format_time(ci_avg)}")
        tee_print(f"PIL avg/iter:           {format_time(pil_avg)}")
        tee_print(f"Avg speedup:            {avg_speedup:.2f}x")
    else:
        tee_print("\n[!] Core Image not available on this system")

    return results


def benchmark_video_backends(test_video: str, iterations: int) -> dict[str, Any]:
    """
    Benchmark video processing backends (FFmpeg vs AVFoundation).

    Args:
        test_video: Path to test video file
        iterations: Number of iterations per backend

    Returns:
        Dictionary with benchmark results
    """
    results = {}

    tee_print("\n" + "=" * 70)
    tee_print("Video Backends")
    tee_print("=" * 70)

    # Test FFmpeg backend
    ffmpeg_total, ffmpeg_times = benchmark_backend("FFmpeg", "video", test_video, iterations)
    print_statistics("FFmpeg", ffmpeg_total, ffmpeg_times)
    results["ffmpeg"] = {"total": ffmpeg_total, "times": ffmpeg_times}

    # Test AVFoundation backend (if available)
    if AVFOUNDATION_AVAILABLE:
        av_total, av_times = benchmark_backend("AVFoundation", "corevideo", test_video, iterations)
        print_statistics("AVFoundation", av_total, av_times)
        results["avfoundation"] = {"total": av_total, "times": av_times}

        # Comparison
        tee_print("\n" + "=" * 70)
        tee_print("Comparison: AVFoundation vs FFmpeg")
        tee_print("=" * 70)
        speedup = ffmpeg_total / av_total
        tee_print(f"AVFoundation total:  {format_time(av_total)}")
        tee_print(f"FFmpeg total:        {format_time(ffmpeg_total)}")
        tee_print(f"Speedup:             {speedup:.2f}x")
    else:
        tee_print("\n[!] AVFoundation not available on this system")

    return results


def benchmark_pdf_backends(test_pdf: str, iterations: int) -> dict[str, Any]:
    """
    Benchmark PDF processing backends (PyMuPDF vs PDFKit).

    Args:
        test_pdf: Path to test PDF file
        iterations: Number of iterations per backend

    Returns:
        Dictionary with benchmark results
    """
    results = {}

    tee_print("\n" + "=" * 70)
    tee_print("PDF Backends")
    tee_print("=" * 70)

    # Test PyMuPDF backend (always available)
    pymupdf_total, pymupdf_times = benchmark_backend("PyMuPDF", "pymupdf", test_pdf, iterations)
    print_statistics("PyMuPDF", pymupdf_total, pymupdf_times)
    results["pymupdf"] = {"total": pymupdf_total, "times": pymupdf_times}

    # Test PDFKit backend (if available)
    if PDFKIT_AVAILABLE:
        pdfkit_total, pdfkit_times = benchmark_backend("PDFKit", "pdfkit", test_pdf, iterations)
        print_statistics("PDFKit", pdfkit_total, pdfkit_times)
        results["pdfkit"] = {"total": pdfkit_total, "times": pdfkit_times}

        # Comparison
        tee_print("\n" + "=" * 70)
        tee_print("Comparison: PDFKit vs PyMuPDF")
        tee_print("=" * 70)
        speedup = pymupdf_total / pdfkit_total
        tee_print(f"PDFKit total:    {format_time(pdfkit_total)}")
        tee_print(f"PyMuPDF total:   {format_time(pymupdf_total)}")
        tee_print(f"Speedup:         {speedup:.2f}x")
    else:
        tee_print("\n[!] PDFKit not available on this system")

    return results


# ============================================================================
# Main
# ============================================================================


def main() -> None:
    """Run thumbnail generation benchmarks."""
    global _output_file  # pylint: disable=global-statement

    # Create output directory
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(exist_ok=True)

    # Create timestamped log file
    timestamp = datetime.now().strftime("%Y_%m_%d_%H-%M-%S")
    log_filename = f"thumbnail_benchmarks_{timestamp}.txt"
    _output_file = open(log_filename, "w", encoding="utf-8")  # pylint: disable=consider-using-with

    tee_print("=" * 70)
    tee_print("Thumbnail Generation Backend Benchmarks")
    tee_print("=" * 70)
    tee_print(f"Log file: {log_filename}")
    tee_print(f"Output directory: {OUTPUT_DIR}")
    tee_print("=" * 70)
    tee_print(f"Iterations per backend: {ITERATIONS:,}")
    tee_print(f"Thumbnail sizes: {IMAGE_SIZES}")
    tee_print(f"JPEG quality: {JPEG_QUALITY}")
    tee_print(f"Working directory: {Path.cwd()}")
    tee_print()
    tee_print("Backend Availability:")
    tee_print(f"  Core Image:     {CORE_IMAGE_AVAILABLE}")
    tee_print(f"  AVFoundation:   {AVFOUNDATION_AVAILABLE}")
    tee_print(f"  PDFKit:         {PDFKIT_AVAILABLE}")

    # Check for test images and run benchmarks on each
    missing_images = [img for img in TEST_IMAGES if not Path(img).exists()]

    if missing_images:
        tee_print(f"\n[!] WARNING: {len(missing_images)} test image(s) not found:")
        for img in missing_images:
            tee_print(f"    - {img}")
        tee_print("    Continuing with available images...")

    available_images = [img for img in TEST_IMAGES if Path(img).exists()]

    if not available_images:
        tee_print("\n[!] ERROR: No test images found in current directory")
        tee_print("    Please place at least one of these images in the benchmarks directory:")
        for img in TEST_IMAGES:
            tee_print(f"    - {img}")
        sys.exit(1)

    # Run image backend benchmarks for each available test image
    for test_image in available_images:
        tee_print(f"\n{'=' * 70}")
        tee_print(f"Testing with: {test_image}")
        tee_print(f"{'=' * 70}")
        benchmark_image_backends(test_image, ITERATIONS)

    # Run video backend benchmarks (if test file exists)
    if Path(TEST_VIDEO).exists():
        benchmark_video_backends(TEST_VIDEO, ITERATIONS)
    else:
        tee_print(f"\n[!] Skipping video benchmarks - '{TEST_VIDEO}' not found")

    # Run PDF backend benchmarks (if test file exists)
    if Path(TEST_PDF).exists():
        benchmark_pdf_backends(TEST_PDF, ITERATIONS)
    else:
        tee_print(f"\n[!] Skipping PDF benchmarks - '{TEST_PDF}' not found")

    tee_print("\n" + "=" * 70)
    tee_print("Benchmarks Complete")
    tee_print("=" * 70)

    # Close log file
    if _output_file:
        tee_print(f"\nBenchmark results saved to: {log_filename}")
        _output_file.close()


if __name__ == "__main__":
    main()

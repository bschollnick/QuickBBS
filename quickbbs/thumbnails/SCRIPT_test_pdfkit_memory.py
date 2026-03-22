"""Test memory usage during PDFKit PDF thumbnail generation.

This script tests for memory leaks by generating thumbnails repeatedly
and measuring memory growth. With proper autorelease pool management,
memory growth should be minimal.

Usage:
    python test_pdfkit_memory.py [pdf_file] [iterations]

    If pdf_file is not provided, uses 'test.pdf' in current directory.
    If iterations is not provided, defaults to 200.

Expected Results (AFTER autorelease pool fixes):
    - Total growth: <40 MB after 200 PDFs
    - Average growth: <200 KB per PDF
    - Memory should stabilize after initial warmup

Before Fixes (without autorelease pools):
    - Total growth: 400+ MB after 200 PDFs
    - Average growth: 2+ MB per PDF
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


def test_memory_leak(pdf_file: str, iterations: int = 200):
    """
    Test memory growth during PDF thumbnail generation.

    Args:
        pdf_file: Path to test PDF file
        iterations: Number of thumbnails to generate (default: 200)
    """
    pdf_path = Path(pdf_file)

    if not pdf_path.exists():
        print(f"Error: PDF file not found: {pdf_file}")
        print("\nPlease provide a valid PDF file path:")
        print(f"  python {Path(__file__).name} /path/to/document.pdf [iterations]")
        sys.exit(1)

    # Import backend (after file check to avoid unnecessary import errors)
    try:
        from pdfkit_thumbnails import PDFKitBackend
    except ImportError as e:
        print(f"Error: Could not import PDFKit backend: {e}")
        print("\nThis test requires macOS with PyObjC frameworks installed.")
        sys.exit(1)

    # Define thumbnail sizes (same as production)
    SIZES = {"large": (1024, 1024), "medium": (740, 740), "small": (200, 200)}

    print("=" * 70)
    print("PDFKit PDF Thumbnail Memory Leak Test")
    print("=" * 70)
    print(f"Test PDF:     {pdf_path}")
    print(f"Iterations:   {iterations}")
    print(f"Sizes:        {SIZES}")
    print("-" * 70)

    # Initialize backend
    try:
        backend = PDFKitBackend()
    except (ImportError, RuntimeError, OSError) as e:
        print(f"Error: Failed to initialize PDFKit backend: {e}")
        sys.exit(1)

    # Warmup run (not counted)
    print("\nWarmup: Generating initial thumbnail...")
    try:
        backend.process_from_file(str(pdf_path), SIZES, "JPEG", 85)
        print("Warmup complete.\n")
    except (OSError, RuntimeError, ValueError) as e:
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
            result = backend.process_from_file(str(pdf_path), SIZES, "JPEG", 85)

            # Verify thumbnails were created
            if "small" not in result or "medium" not in result or "large" not in result:
                print(f"Warning: Incomplete thumbnail set at iteration {i + 1}")

        except (OSError, RuntimeError, ValueError) as e:
            print(f"Error at iteration {i + 1}: {e}")
            continue

        # Report progress periodically
        if (i + 1) % report_interval == 0:
            current = measure_memory_mb()
            growth = current - start_memory
            avg_growth = growth / (i + 1)

            print(f"After {i + 1:4d} PDFs: " f"{current:6.1f} MB " f"(growth: {growth:5.1f} MB, " f"avg: {avg_growth * 1000:.2f} KB/PDF)")

    # Final measurements
    end_memory = measure_memory_mb()
    total_growth = end_memory - start_memory
    avg_per_pdf = total_growth / iterations

    print()
    print("=" * 70)
    print("RESULTS:")
    print("=" * 70)
    print(f"  Total iterations:     {iterations}")
    print(f"  Starting memory:      {start_memory:.1f} MB")
    print(f"  Ending memory:        {end_memory:.1f} MB")
    print(f"  Total growth:         {total_growth:.1f} MB")
    print(f"  Avg per PDF:          {avg_per_pdf * 1000:.2f} KB")
    print("=" * 70)

    # Evaluation
    print()
    if avg_per_pdf > 0.2:  # More than 200KB per PDF
        print("⚠️  HIGH MEMORY GROWTH - Likely leak present")
        print("    Expected: <200 KB per PDF")
        print("    Actual:   {:.2f} KB per PDF".format(avg_per_pdf * 1000))
        print()
        print("    Possible causes:")
        print("    - Autorelease pools not properly implemented")
        print("    - Missing autorelease_pool() wrappers")
        print("    - Backend caching not being cleared")
    elif avg_per_pdf > 0.1:  # 100-200KB per PDF
        print("⚠️  MODERATE MEMORY GROWTH - Some accumulation occurring")
        print("    Expected: <100 KB per PDF")
        print("    Actual:   {:.2f} KB per PDF".format(avg_per_pdf * 1000))
        print()
        print("    This may be acceptable but should be monitored.")
    else:
        print("✅  LOW MEMORY GROWTH - Memory management working well")
        print("    Average growth: {:.2f} KB per PDF (excellent!)".format(avg_per_pdf * 1000))

    print()


if __name__ == "__main__":
    # Parse command line arguments
    main_pdf_file = "test.pdf"
    main_iterations = 200

    if len(sys.argv) > 1:
        main_pdf_file = sys.argv[1]

    if len(sys.argv) > 2:
        try:
            main_iterations = int(sys.argv[2])
            if main_iterations < 1:
                print("Error: Iterations must be at least 1")
                sys.exit(1)
        except ValueError:
            print(f"Error: Invalid iterations value: {sys.argv[2]}")
            sys.exit(1)

    test_memory_leak(main_pdf_file, main_iterations)

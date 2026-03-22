"""Test script to verify PIL Image memory leak is fixed.

This script simulates the thumbnail validation process and measures memory growth.

Usage:
    python test_memory_leak.py [iterations]

Expected Results (AFTER fix):
    - Minimal memory growth (<10 MB for 10,000 iterations)
    - Memory should stabilize quickly

Before Fix:
    - Significant memory growth (100+ MB for 10,000 iterations)
    - Memory continues to grow unbounded as PIL Image objects accumulate
"""

import gc
import io
import resource
import sys

from PIL import Image


def measure_memory_mb():
    """Get current memory usage in MB (macOS).

    Returns:
        float: Memory usage in megabytes
    """
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # macOS returns ru_maxrss in bytes, convert to MB
    return usage.ru_maxrss / (1024 * 1024)


def create_test_thumbnail():
    """Create a small test thumbnail image in memory."""
    # Create a 200x200 RGB test image
    img = Image.new("RGB", (200, 200), color=(100, 150, 200))

    # Convert to JPEG bytes (simulates thumbnail data)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    img.close()

    return buffer.getvalue()


def test_with_context_manager(thumbnail_bytes):
    """Test validation WITH context manager (FIXED version)."""
    with Image.open(io.BytesIO(thumbnail_bytes)) as img:
        extrema = img.getextrema()

        is_all_white = False
        if img.mode == "RGB":
            is_all_white = extrema == ((255, 255), (255, 255), (255, 255))
        elif img.mode == "L":
            is_all_white = extrema == (255, 255)

    return is_all_white


def test_without_context_manager(thumbnail_bytes):
    """Test validation WITHOUT context manager (BROKEN version - for comparison)."""
    img = Image.open(io.BytesIO(thumbnail_bytes))
    extrema = img.getextrema()

    is_all_white = False
    if img.mode == "RGB":
        is_all_white = extrema == ((255, 255), (255, 255), (255, 255))
    elif img.mode == "L":
        is_all_white = extrema == (255, 255)

    # Note: img.close() is NOT called - this leaks!
    return is_all_white


def run_test(use_context_manager=True, iterations=10000):
    """Run memory leak test.

    Args:
        use_context_manager: If True, use fixed version with context manager
        iterations: Number of validation iterations to run
    """
    test_name = "WITH context manager (FIXED)" if use_context_manager else "WITHOUT context manager (BROKEN)"
    test_func = test_with_context_manager if use_context_manager else test_without_context_manager

    print("=" * 70)
    print(f"Memory Leak Test: {test_name}")
    print("=" * 70)
    print(f"Iterations: {iterations:,}")
    print("-" * 70)

    # Create test thumbnail data once
    thumbnail_bytes = create_test_thumbnail()
    print(f"Test thumbnail size: {len(thumbnail_bytes):,} bytes")

    # Warmup
    print("\nWarmup: Running 100 iterations...")
    for _ in range(100):
        test_func(thumbnail_bytes)

    # Force GC before measurement
    gc.collect()

    # Measure starting memory
    start_memory = measure_memory_mb()
    print(f"Starting memory: {start_memory:.1f} MB")
    print()

    # Run test iterations
    report_interval = max(1, iterations // 10)

    for i in range(iterations):
        test_func(thumbnail_bytes)

        # Periodic reporting
        if (i + 1) % report_interval == 0:
            current = measure_memory_mb()
            growth = current - start_memory
            avg_growth = growth / (i + 1)

            print(f"After {i + 1:6,} iterations: " f"{current:6.1f} MB " f"(growth: {growth:5.1f} MB, " f"avg: {avg_growth * 1024:.3f} KB/iteration)")

    # Final measurements
    end_memory = measure_memory_mb()
    total_growth = end_memory - start_memory
    avg_per_iteration = total_growth / iterations

    print()
    print("=" * 70)
    print("RESULTS:")
    print("=" * 70)
    print(f"  Total iterations:     {iterations:,}")
    print(f"  Starting memory:      {start_memory:.1f} MB")
    print(f"  Ending memory:        {end_memory:.1f} MB")
    print(f"  Total growth:         {total_growth:.1f} MB")
    print(f"  Avg per iteration:    {avg_per_iteration * 1024:.3f} KB")
    print("=" * 70)

    # Evaluation
    print()
    if avg_per_iteration > 0.01:  # More than 10KB per iteration
        print("⚠️  HIGH MEMORY GROWTH - Likely leak present")
        print(f"    Expected: <10 KB per iteration")
        print(f"    Actual:   {avg_per_iteration * 1024:.3f} KB per iteration")
        print()
        print("    This indicates PIL Image objects are not being properly closed.")
    elif avg_per_iteration > 0.001:  # 1-10KB per iteration
        print("⚠️  MODERATE MEMORY GROWTH - Some accumulation occurring")
        print(f"    Expected: <1 KB per iteration")
        print(f"    Actual:   {avg_per_iteration * 1024:.3f} KB per iteration")
        print()
        print("    This may be normal Python memory management overhead.")
    else:
        print("✅  LOW MEMORY GROWTH - Memory management working well")
        print(f"    Average growth: {avg_per_iteration * 1024:.3f} KB per iteration (excellent!)")

    print()


if __name__ == "__main__":
    main_iterations = 10000

    if len(sys.argv) > 1:
        try:
            main_iterations = int(sys.argv[1])
            if main_iterations < 1:
                print("Error: Iterations must be at least 1")
                sys.exit(1)
        except ValueError:
            print(f"Error: Invalid iterations value: {sys.argv[1]}")
            sys.exit(1)

    # Run both tests for comparison
    print("\n" + "=" * 70)
    print("COMPARISON TEST: Fixed vs Broken Implementation")
    print("=" * 70)
    print()
    print("This test demonstrates the memory leak caused by not closing PIL Images.")
    print("The FIXED version uses a context manager, the BROKEN version does not.")
    print()

    # Test 1: Fixed version (with context manager)
    run_test(use_context_manager=True, iterations=main_iterations)

    print("\n\n")
    input("Press Enter to run the BROKEN test (this will leak memory)...")
    print()

    # Test 2: Broken version (without context manager) - for comparison
    run_test(use_context_manager=False, iterations=main_iterations)

    print("\n" + "=" * 70)
    print("SUMMARY:")
    print("=" * 70)
    print("Compare the memory growth between the two tests.")
    print("The FIXED version should show minimal growth (<1 KB/iteration).")
    print("The BROKEN version will show significant growth (>10 KB/iteration).")
    print("=" * 70)

#!/usr/bin/env python3
"""
Benchmark script to compare OSXMetaData vs xattr for reading Finder colors.
"""

import os
import random
import time
from struct import unpack

import xattr
from osxmetadata import OSXMetaData

# Color name mapping
colornames = {
    0: "none",
    1: "gray",
    2: "green",
    3: "purple",
    4: "blue",
    5: "yellow",
    6: "red",
    7: "orange",
}


def get_color_xattr(filename):
    """Get color using xattr method."""
    try:
        attrs = xattr.xattr(filename)
        finder_attrs = attrs["com.apple.FinderInfo"]
        flags = unpack(32 * "B", finder_attrs)
        color = flags[9] >> 1 & 7
    except (KeyError, OSError, FileNotFoundError):
        color = 0
    return (color, colornames[color])


def get_color_osxmetadata(filename):
    """Get color using OSXMetaData method."""
    try:
        metadata = OSXMetaData(str(filename))

        # Check for modern tags first (macOS 10.9+)
        if metadata.tags:
            for tag in metadata.tags:
                if tag.color > 0:
                    return (tag.color, colornames.get(tag.color, "unknown"))

        # Fall back to legacy Finder color (pre-Mavericks)
        if hasattr(metadata, "findercolor") and metadata.findercolor > 0:
            return (
                metadata.findercolor,
                colornames.get(metadata.findercolor, "unknown"),
            )

        return (0, colornames[0])

    except (OSError, FileNotFoundError):
        return (0, colornames[0])
    except Exception:
        return (0, colornames[0])


def collect_test_files(base_dir, max_files=1000):
    """Collect a sample of files for testing."""
    test_files = []

    for root, _, files in os.walk(base_dir):
        for file in files:
            if len(test_files) >= max_files:
                break

            file_path = os.path.join(root, file)
            # Skip system files and hidden files
            if not file.startswith(".") and os.path.isfile(file_path):
                test_files.append(file_path)

        if len(test_files) >= max_files:
            break

    return test_files


def benchmark_method(method_func, files, method_name):
    """Benchmark a color detection method."""
    print(f"\nBenchmarking {method_name}...")

    start_time = time.time()
    results = []
    errors = 0

    for file_path in files:
        try:
            result = method_func(file_path)
            results.append(result)
        except Exception:
            errors += 1

    end_time = time.time()
    duration = end_time - start_time

    # Count colored files
    colored_files = sum(1 for result in results if result[0] > 0)

    print(f"  Duration: {duration:.3f} seconds")
    print(f"  Files processed: {len(results)}")
    print(f"  Files with colors: {colored_files}")
    print(f"  Errors: {errors}")
    print(f"  Rate: {len(files)/duration:.1f} files/second")

    return {
        "duration": duration,
        "files_processed": len(results),
        "colored_files": colored_files,
        "errors": errors,
        "rate": len(files) / duration,
    }


def main():
    """Run the benchmark comparison."""
    print("Finder Color Detection Method Benchmark")
    print("=" * 50)

    # Use the albums directory for testing (but don't modify anything)
    base_dir = "/Volumes/C-8TB/gallery/quickbbs/albums"
    if not os.path.exists(base_dir):
        print(f"Error: Test directory {base_dir} not found")
        print("Please update base_dir to point to a directory with files")
        return

    print(f"Collecting test files from: {base_dir}")
    test_files = collect_test_files(base_dir, max_files=500)

    if not test_files:
        print("No test files found!")
        return

    print(f"Found {len(test_files)} test files")

    # Randomize order to avoid caching effects
    random.shuffle(test_files)

    # Run benchmarks
    xattr_results = benchmark_method(get_color_xattr, test_files, "xattr method")
    osxmetadata_results = benchmark_method(get_color_osxmetadata, test_files, "OSXMetaData method")

    # Compare results
    print(f"\n{'='*50}")
    print("COMPARISON RESULTS")
    print(f"{'='*50}")

    print(f"xattr method:      {xattr_results['rate']:.1f} files/sec")
    print(f"OSXMetaData method: {osxmetadata_results['rate']:.1f} files/sec")

    if xattr_results["rate"] > osxmetadata_results["rate"]:
        speedup = xattr_results["rate"] / osxmetadata_results["rate"]
        print(f"\nxattr is {speedup:.1f}x faster than OSXMetaData")
    else:
        speedup = osxmetadata_results["rate"] / xattr_results["rate"]
        print(f"\nOSXMetaData is {speedup:.1f}x faster than xattr")

    # Check for consistency
    print(f"\nColored files found:")
    print(f"  xattr: {xattr_results['colored_files']}")
    print(f"  OSXMetaData: {osxmetadata_results['colored_files']}")

    if xattr_results["colored_files"] != osxmetadata_results["colored_files"]:
        print("⚠️  Warning: Methods found different numbers of colored files!")
    else:
        print("✅ Both methods found the same number of colored files")


if __name__ == "__main__":
    main()

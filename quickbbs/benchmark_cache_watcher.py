"""
Timing benchmark for fs_Cache_Tracking read operations.

Focuses on real-world read patterns used throughout the application
to establish baseline performance metrics and track optimization impact.
"""

import os
import random
import time
from datetime import datetime
from typing import Callable

# Benchmark configuration
BENCHMARK_ITERATIONS = 500  # Number of iterations per benchmark operation

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")

# Enable DEBUG mode to track SQL queries
os.environ["DJANGO_DEBUG"] = "1"

django.setup()

from django.conf import settings
from django.db import connection, reset_queries

# Ensure DEBUG is True for query tracking
settings.DEBUG = True

from cache_watcher.models import fs_Cache_Tracking


class BenchmarkResult:
    """Store benchmark results with timing statistics."""

    def __init__(self, name: str):
        self.name = name
        self.times: list[float] = []
        self.query_count: int = 0
        self.max_query_count: int = 0
        self.result_count: int = 0

    def add_timing(self, elapsed: float, query_count: int, result_count: int = 0) -> None:
        """Add a timing result."""
        self.times.append(elapsed)
        self.query_count = query_count  # Last iteration's count
        self.max_query_count = max(self.max_query_count, query_count)  # Track maximum
        self.result_count = result_count

    @property
    def avg_time(self) -> float:
        """Get average execution time in milliseconds."""
        return sum(self.times) / len(self.times) if self.times else 0

    @property
    def min_time(self) -> float:
        """Get minimum execution time in milliseconds."""
        return min(self.times) if self.times else 0

    @property
    def max_time(self) -> float:
        """Get maximum execution time in milliseconds."""
        return max(self.times) if self.times else 0

    def __str__(self) -> str:
        """Format benchmark result as string."""
        return (
            f"{self.name:70s} | "
            f"Avg: {self.avg_time:9.4f}ms | "
            f"Min: {self.min_time:9.4f}ms | "
            f"Max: {self.max_time:9.4f}ms | "
            f"Q: {self.max_query_count:3d} | "
            f"R: {self.result_count:5d}"
        )


def benchmark_query(
    name: str, query_func: Callable, iterations: int = BENCHMARK_ITERATIONS, samples: list = None
) -> BenchmarkResult:
    """
    Benchmark a database query function.

    Args:
        name: Name of the benchmark
        query_func: Function that executes the query (takes sample as argument)
        iterations: Number of iterations to run
        samples: List of sample data to randomly choose from (if None, query_func takes no args)

    Returns:
        BenchmarkResult with timing statistics
    """
    result = BenchmarkResult(name)

    for i in range(iterations):
        reset_queries()
        start = time.perf_counter()

        # Execute query and force evaluation
        if samples is not None:
            sample = random.choice(samples)
            queryset = query_func(sample)
        else:
            queryset = query_func()

        if hasattr(queryset, "__iter__") and not isinstance(queryset, (str, dict)):
            result_count = len(list(queryset))
        elif isinstance(queryset, (int, bool)):
            result_count = queryset
        else:
            result_count = 1

        elapsed = (time.perf_counter() - start) * 1000
        query_count = len(connection.queries)

        result.add_timing(elapsed, query_count, result_count)

    return result


def run_fs_cache_tracking_read_benchmarks() -> list[BenchmarkResult]:
    """Run benchmarks for fs_Cache_Tracking read operations using existing methods."""
    print("\n" + "=" * 150)
    print("FS_CACHE_TRACKING READ BENCHMARKS (Using Existing Methods)")
    print("=" * 150)

    results: list[BenchmarkResult] = []

    # Get 25 random sample cache entries for testing
    sample_entries = list(fs_Cache_Tracking.objects.order_by("?")[:25])
    if not sample_entries:
        print("No cache entries found in database. Skipping fs_Cache_Tracking benchmarks.")
        return results

    print(f"Using {len(sample_entries)} random cache entry samples for testing...")

    # Create an instance for calling instance methods
    cache_instance = fs_Cache_Tracking()

    # 1. Check if SHA exists in cache (not invalidated)
    results.append(
        benchmark_query(
            "cache.sha_exists_in_cache(sha)",
            lambda e: cache_instance.sha_exists_in_cache(e.directory_sha256),
            samples=sample_entries,
        )
    )

    # 2. Remove from cache by SHA (marks as invalidated)
    results.append(
        benchmark_query(
            "cache.remove_from_cache_sha(sha)",
            lambda e: cache_instance.remove_from_cache_sha(e.directory_sha256),
            samples=sample_entries,
        )
    )

    # 3. Remove from cache by name (calls remove_from_cache_sha internally)
    results.append(
        benchmark_query(
            "cache.remove_from_cache_name(dir_name)",
            lambda e: cache_instance.remove_from_cache_name(e.DirName),
            samples=sample_entries,
        )
    )

    # 4. Add to cache (or update existing entry)
    results.append(
        benchmark_query(
            "cache.add_to_cache(dir_name)",
            lambda e: cache_instance.add_to_cache(e.DirName),
            samples=sample_entries,
        )
    )

    # 5. Bulk remove multiple directories from cache
    # Create a small list of directory names for bulk testing
    dir_names = [e.DirName for e in sample_entries[:5]]
    results.append(
        benchmark_query(
            "cache.remove_multiple_from_cache(dir_names[5])",
            lambda: cache_instance.remove_multiple_from_cache(dir_names),
        )
    )

    return results


def main() -> None:
    """Run all benchmarks and display results."""
    output_lines = []

    def print_and_capture(msg):
        """Print to console and capture for file output."""
        print(msg)
        output_lines.append(msg)

    print_and_capture("\n" + "=" * 150)
    print_and_capture("CACHE WATCHER DATABASE READ PERFORMANCE BENCHMARKS - BASELINE METRICS")
    print_and_capture("=" * 150)
    print_and_capture(f"Benchmark Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print_and_capture(f"DEBUG mode: {settings.DEBUG}")
    print_and_capture(f"Running benchmarks with {BENCHMARK_ITERATIONS} iterations per operation...")
    print_and_capture("Legend: Avg/Min/Max (milliseconds) | Q (SQL queries) | R (results returned)")

    # Run all benchmark suites
    cache_tracking_results = run_fs_cache_tracking_read_benchmarks()

    # Display all results
    print_and_capture("\n" + "=" * 150)
    print_and_capture("FS_CACHE_TRACKING RESULTS")
    print_and_capture("=" * 150)
    for result in cache_tracking_results:
        print_and_capture(str(result))

    # Calculate totals for fs_Cache_Tracking
    if cache_tracking_results:
        total_avg = sum(r.avg_time for r in cache_tracking_results)
        total_min = sum(r.min_time for r in cache_tracking_results)
        total_max = sum(r.max_time for r in cache_tracking_results)
        total_queries = sum(r.max_query_count for r in cache_tracking_results)
        print_and_capture("-" * 150)
        print_and_capture(
            f"{'TOTALS':70s} | "
            f"Avg: {total_avg:9.4f}ms | "
            f"Min: {total_min:9.4f}ms | "
            f"Max: {total_max:9.4f}ms | "
            f"Q: {total_queries:3d} | "
            f"R: {'---':>5s}"
        )

    print_and_capture("\n" + "=" * 150)
    print_and_capture("BENCHMARK COMPLETE")
    print_and_capture("=" * 150)
    print_and_capture("\nNotes:")
    print_and_capture("- Re-run this benchmark after making optimizations to compare performance")
    print_and_capture("- Lower query counts (Q) indicate better optimization")
    print_and_capture("- Lower times indicate faster execution")
    print_and_capture("- First run may be slower due to cache warming")

    # Save results to file
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    output_filename = f"cache_watcher_models_{timestamp}.txt"
    output_path = os.path.join(os.path.dirname(__file__), "tests", output_filename)

    # Ensure tests directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w") as f:
        # Write benchmark results
        f.write("\n".join(output_lines))
        f.write("\n\n")
        f.write("=" * 150 + "\n")
        f.write("CACHE_WATCHER/MODELS.PY SNAPSHOT (for reference)\n")
        f.write("=" * 150 + "\n\n")

        # Append models.py contents
        models_path = os.path.join(os.path.dirname(__file__), "cache_watcher", "models.py")
        with open(models_path, "r") as models_file:
            f.write(models_file.read())

    print(f"\nBenchmark results saved to: {output_path}")


if __name__ == "__main__":
    main()

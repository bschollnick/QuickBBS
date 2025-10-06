"""
Timing benchmark for IndexData and IndexDirs read operations.

Focuses on real-world read patterns used throughout the application
to establish baseline performance metrics and track optimization impact.
"""

import os
import random
import time
from datetime import datetime
from typing import Any, Callable

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

from django.test import RequestFactory

from quickbbs.models import IndexData, IndexDirs, indexdirs_cache, indexdata_cache, indexdata_download_cache


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


def benchmark_query(name: str, query_func: Callable, iterations: int = BENCHMARK_ITERATIONS, samples: list = None) -> BenchmarkResult:
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
        # Clear caches every 25 iterations
        if i % 25 == 0:
            indexdirs_cache.clear()
            indexdata_cache.clear()
            indexdata_download_cache.clear()

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


def run_indexdirs_read_benchmarks() -> list[BenchmarkResult]:
    """Run benchmarks for IndexDirs read operations using existing methods."""
    print("\n" + "=" * 150)
    print("INDEXDIRS READ BENCHMARKS (Using Existing Methods)")
    print("=" * 150)

    results: list[BenchmarkResult] = []

    # Clear all caches before loading samples
    indexdirs_cache.clear()
    indexdata_cache.clear()
    indexdata_download_cache.clear()

    # Get 25 random sample directories for testing
    sample_dirs = list(IndexDirs.objects.filter(delete_pending=False).order_by('?')[:25])
    if not sample_dirs:
        print("No directories found in database. Skipping IndexDirs benchmarks.")
        return results

    print(f"Using {len(sample_dirs)} random directory samples for testing...")

    # 1. Search for directory by SHA256 (cached method)
    results.append(
        benchmark_query(
            "IndexDirs.search_for_directory_by_sha(sha)",
            lambda d: IndexDirs.search_for_directory_by_sha(d.dir_fqpn_sha256),
            samples=sample_dirs,
        )
    )

    # 2. Search for directory by FQPN (calls search_by_sha internally)
    results.append(
        benchmark_query(
            "IndexDirs.search_for_directory(fqpn)",
            lambda d: IndexDirs.search_for_directory(d.fqpndirectory),
            samples=sample_dirs,
        )
    )

    # 3. Get subdirectories using dirs_in_dir() method
    results.append(
        benchmark_query(
            "dir.dirs_in_dir(sort=0)",
            lambda d: list(d.dirs_in_dir(sort=0)),
            samples=sample_dirs,
        )
    )

    # 4. Get files using files_in_dir() method
    results.append(
        benchmark_query(
            "dir.files_in_dir(sort=0)",
            lambda d: list(d.files_in_dir(sort=0)),
            samples=sample_dirs,
        )
    )

    # 5. Get file count
    results.append(
        benchmark_query(
            "dir.get_file_counts()",
            lambda d: d.get_file_counts(),
            samples=sample_dirs,
        )
    )

    # 6. Get directory count
    results.append(
        benchmark_query(
            "dir.get_dir_counts()",
            lambda d: d.get_dir_counts(),
            samples=sample_dirs,
        )
    )

    # 7. Get count breakdown (all file types)
    results.append(
        benchmark_query(
            "dir.get_count_breakdown()",
            lambda d: d.get_count_breakdown(),
            samples=sample_dirs,
        )
    )

    # 8. Check if files exist
    results.append(
        benchmark_query(
            "dir.do_files_exist()",
            lambda d: d.do_files_exist(),
            samples=sample_dirs,
        )
    )

    # 9. Get parent directory
    results.append(
        benchmark_query(
            "dir.return_parent_directory()",
            lambda d: d.return_parent_directory(),
            samples=sample_dirs,
        )
    )

    # 10. Property access: virtual_directory
    results.append(
        benchmark_query(
            "dir.virtual_directory (property)",
            lambda d: d.virtual_directory,
            samples=sample_dirs,
        )
    )

    # 11. Property access: name
    results.append(
        benchmark_query(
            "dir.name (property)",
            lambda d: d.name,
            samples=sample_dirs,
        )
    )

    # 12. Get view URL
    results.append(
        benchmark_query(
            "dir.get_view_url()",
            lambda d: d.get_view_url(),
            samples=sample_dirs,
        )
    )

    # 13. Get thumbnail URL
    results.append(
        benchmark_query(
            "dir.get_thumbnail_url()",
            lambda d: d.get_thumbnail_url(),
            samples=sample_dirs,
        )
    )

    # 14. Get background color (accesses filetype FK)
    results.append(
        benchmark_query(
            "dir.get_bg_color()",
            lambda d: d.get_bg_color(),
            samples=sample_dirs,
        )
    )

    # 15. Return by SHA256 list (batch operation)
    sha_list = list(IndexDirs.objects.filter(delete_pending=False).values_list("dir_fqpn_sha256", flat=True)[:10])
    if sha_list:
        results.append(
            benchmark_query(
                "IndexDirs.return_by_sha256_list(sha_list, sort=0)",
                lambda: list(IndexDirs.return_by_sha256_list(sha_list, sort=0)),
            )
        )

    return results


def run_indexdata_read_benchmarks() -> list[BenchmarkResult]:
    """Run benchmarks for IndexData read operations using existing methods."""
    print("\n" + "=" * 150)
    print("INDEXDATA READ BENCHMARKS (Using Existing Methods)")
    print("=" * 150)

    results: list[BenchmarkResult] = []

    # Clear all caches before loading samples
    indexdirs_cache.clear()
    indexdata_cache.clear()
    indexdata_download_cache.clear()

    # Get 25 random sample files for testing
    sample_files = list(IndexData.objects.filter(delete_pending=False).order_by('?')[:25])
    if not sample_files:
        print("No files found in database. Skipping IndexData benchmarks.")
        return results
    
    # Clear all caches before loading samples
    indexdirs_cache.clear()
    indexdata_cache.clear()
    indexdata_download_cache.clear()

    print(f"Using {len(sample_files)} random file samples for testing...")

    # 1. Get by SHA256 (cached method, unique=True)
    results.append(
        benchmark_query(
            "IndexData.get_by_sha256(sha, unique=True)",
            lambda f: IndexData.get_by_sha256(f.unique_sha256, unique=True),
            samples=sample_files,
        )
    )

    # 2. Get by SHA256 (cached method, unique=False)
    def get_by_sha_with_fallback(f):
        try:
            return IndexData.get_by_sha256(f.file_sha256, unique=False)
        except IndexData.MultipleObjectsReturned:
            # Fall back to unique SHA if file_sha256 has duplicates
            return IndexData.get_by_sha256(f.unique_sha256, unique=True)

    results.append(
        benchmark_query(
            "IndexData.get_by_sha256(sha, unique=False)",
            get_by_sha_with_fallback,
            samples=sample_files,
        )
    )

    # 3. Get for download (optimized cached method)
    results.append(
        benchmark_query(
            "IndexData.get_by_sha256_for_download(sha, unique=True)",
            lambda f: IndexData.get_by_sha256_for_download(f.unique_sha256, unique=True),
            samples=sample_files,
        )
    )

    # 4. Get by filters - skip due to cache incompatibility with dict args
    # The @cached decorator doesn't support dict parameters (unhashable)
    # This would need refactoring to support benchmarking
    # results.append(
    #     benchmark_query(
    #         "IndexData.get_by_filters(filetype__is_graphic=True)",
    #         lambda: list(IndexData.get_by_filters(additional_filters={"filetype__is_graphic": True})[:50]),
    #     )
    # )

    # 5. Count identical files
    results.append(
        benchmark_query(
            "IndexData.return_identical_files_count(sha)",
            lambda f: IndexData.return_identical_files_count(f.file_sha256),
            samples=sample_files,
        )
    )

    # 6. List all identical files
    results.append(
        benchmark_query(
            "IndexData.return_list_all_identical_files_by_sha(sha)",
            lambda f: list(IndexData.return_list_all_identical_files_by_sha(f.file_sha256)),
            samples=sample_files,
        )
    )

    # 7. Get identical file entries (values query)
    results.append(
        benchmark_query(
            "IndexData.get_identical_file_entries_by_sha(sha)",
            lambda f: list(IndexData.get_identical_file_entries_by_sha(f.file_sha256)),
            samples=sample_files,
        )
    )

    # 8. Return by SHA256 list (batch operation)
    sha_list = list(IndexData.objects.filter(delete_pending=False).values_list("file_sha256", flat=True)[:10])
    if sha_list:
        results.append(
            benchmark_query(
                "IndexData.return_by_sha256_list(sha_list, sort=0)",
                lambda: list(IndexData.return_by_sha256_list(sha_list, sort=0)),
            )
        )

    # 9. Property: fqpndirectory (accesses home_directory FK)
    results.append(
        benchmark_query(
            "file.fqpndirectory (property)",
            lambda f: f.fqpndirectory,
            samples=sample_files,
        )
    )

    # 10. Property: full_filepathname
    results.append(
        benchmark_query(
            "file.full_filepathname (property)",
            lambda f: f.full_filepathname,
            samples=sample_files,
        )
    )

    # 11. Get webpath
    results.append(
        benchmark_query(
            "file.get_webpath()",
            lambda f: f.get_webpath(),
            samples=sample_files,
        )
    )

    # 12. Get background color (accesses filetype FK)
    results.append(
        benchmark_query(
            "file.get_bg_color()",
            lambda f: f.get_bg_color(),
            samples=sample_files,
        )
    )

    # 13. Get view URL
    results.append(
        benchmark_query(
            "file.get_view_url()",
            lambda f: f.get_view_url(),
            samples=sample_files,
        )
    )

    # 14. Get thumbnail URL
    results.append(
        benchmark_query(
            "file.get_thumbnail_url(size='small')",
            lambda f: f.get_thumbnail_url(size="small"),
            samples=sample_files,
        )
    )

    # 15. Get download URL
    results.append(
        benchmark_query(
            "file.get_download_url()",
            lambda f: f.get_download_url(),
            samples=sample_files,
        )
    )

    # 16. inline_sendfile (non-ranged) - actual file send operation
    # Create a mock request for testing
    factory = RequestFactory()
    mock_request = factory.get('/download/test.jpg')

    results.append(
        benchmark_query(
            "file.inline_sendfile(request, ranged=False)",
            lambda f: f.inline_sendfile(mock_request, ranged=False),
            samples=sample_files,
            iterations=300,
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
    print_and_capture("DATABASE READ PERFORMANCE BENCHMARKS - BASELINE METRICS")
    print_and_capture("=" * 150)
    print_and_capture(f"Benchmark Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print_and_capture(f"DEBUG mode: {settings.DEBUG}")
    print_and_capture(f"Running benchmarks with {BENCHMARK_ITERATIONS} iterations per operation...")
    print_and_capture("Legend: Avg/Min/Max (milliseconds) | Q (SQL queries) | R (results returned)")

    # Run all benchmark suites
    indexdirs_results = run_indexdirs_read_benchmarks()
    indexdata_results = run_indexdata_read_benchmarks()

    # Display all results
    print_and_capture("\n" + "=" * 150)
    print_and_capture("INDEXDIRS RESULTS")
    print_and_capture("=" * 150)
    for result in indexdirs_results:
        print_and_capture(str(result))

    # Calculate totals for IndexDirs
    if indexdirs_results:
        total_avg = sum(r.avg_time for r in indexdirs_results)
        total_min = sum(r.min_time for r in indexdirs_results)
        total_max = sum(r.max_time for r in indexdirs_results)
        total_queries = sum(r.max_query_count for r in indexdirs_results)
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
    print_and_capture("INDEXDATA RESULTS")
    print_and_capture("=" * 150)
    for result in indexdata_results:
        print_and_capture(str(result))

    # Calculate totals for IndexData
    if indexdata_results:
        total_avg = sum(r.avg_time for r in indexdata_results)
        total_min = sum(r.min_time for r in indexdata_results)
        total_max = sum(r.max_time for r in indexdata_results)
        total_queries = sum(r.max_query_count for r in indexdata_results)
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
    timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
    output_filename = f"quickbbs_models_{timestamp}.txt"
    output_path = os.path.join(os.path.dirname(__file__), "tests", output_filename)

    # Ensure tests directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w') as f:
        # Write benchmark results
        f.write('\n'.join(output_lines))
        f.write('\n\n')
        f.write("=" * 150 + '\n')
        f.write("QUICKBBS/MODELS.PY SNAPSHOT (for reference)\n")
        f.write("=" * 150 + '\n\n')

        # Append models.py contents
        models_path = os.path.join(os.path.dirname(__file__), "quickbbs", "models.py")
        with open(models_path, 'r') as models_file:
            f.write(models_file.read())

    print(f"\nBenchmark results saved to: {output_path}")


if __name__ == "__main__":
    main()

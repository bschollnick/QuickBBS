#!/usr/bin/env python3
"""
Locust load testing configuration for QuickBBS download endpoints.

This file defines the load testing behavior for file download endpoints,
mimicking Apache Benchmark (ab) tests with configurable users and requests.

This version uses httpx instead of requests to support HTTP/2 protocol testing.

Usage:
    # Run with wrapper script (recommended):
    python run_download_benchmark.py

    # Run directly with Locust CLI:
    locust -f locustfile_downloads.py --host=http://localhost:8888 \
           --users=50 --spawn-rate=50 --run-time=1m --headless

Requirements:
    - locust (installed via poetry add locust --group dev)
    - httpx[http2] (installed via poetry add "httpx[http2]" --group dev)
    - Running QuickBBS server on localhost:8888
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from locust import TaskSet, User, between, events, task

# Global variable to track size validation results
_size_validation_stats = {
    "total_downloads": 0,
    "successful_validations": 0,
    "size_mismatches": 0,
    "no_validation": 0,  # Downloads without expected_size specified
    "details": [],  # List of individual validation results
    "by_file": {},  # Per-file breakdown: {file_name: {total, successful, mismatches}}
}


class HttpxClient:
    """
    Custom HTTP client using httpx with HTTP/2 support.

    This wraps httpx.Client and provides Locust-compatible interface
    for request statistics tracking.
    """

    def __init__(self, base_url: str, verify: bool = True, http2: bool = True):
        """
        Initialize httpx client.

        Args:
            base_url: Base URL for requests
            verify: Whether to verify SSL certificates
            http2: Whether to enable HTTP/2
        """
        self.base_url = base_url
        self._client = httpx.Client(
            base_url=base_url,
            verify=verify,
            http2=http2,
            # Timeouts for large file downloads
            # connect: time to establish connection
            # read: time to read response data (important for large files!)
            # write: time to send request
            # pool: time waiting for connection from pool
            timeout=httpx.Timeout(
                timeout=60.0,  # Overall timeout
                connect=10.0,  # Connection timeout
                read=60.0,  # Read timeout (10MB @ 1MB/s = ~10s, add buffer)
                write=30.0,  # Write timeout
                pool=5.0,  # Pool timeout
            ),
            # Limit concurrent connections to avoid overwhelming server
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
            ),
        )

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        name: str | None = None,
        catch_response: bool = False,
        expected_size: int | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Make GET request and report stats to Locust.

        Args:
            path: URL path
            params: Query parameters
            name: Name for stats (defaults to path)
            catch_response: Whether to catch response for manual success/failure
            expected_size: Expected file size in bytes for validation (optional)
            **kwargs: Additional httpx arguments

        Returns:
            httpx.Response object
        """
        url = path
        request_name = name or path
        start_time = time.time()
        response = None
        exception = None
        response_length = 0
        actual_bytes_read = 0

        # Build full URL for logging
        full_url = f"{self.base_url}{url}"
        if params:
            param_str = "&".join(f"{k}={v}" for k, v in params.items())
            full_url = f"{full_url}?{param_str}"

        print(f"[REQUEST] {request_name}: {full_url}")

        try:
            # Stream the response to properly handle large files
            with self._client.stream("GET", url, params=params, **kwargs) as stream_response:
                response = stream_response  # Keep reference

                # IMPORTANT: Read the stream in chunks to prevent CancelledError
                # This ensures we consume the entire response before closing connection
                try:
                    # Read entire response body in chunks and count actual bytes
                    for chunk in stream_response.iter_bytes(chunk_size=65536):
                        actual_bytes_read += len(chunk)

                    # Use actual bytes read for Locust statistics (more accurate than header)
                    response_length = actual_bytes_read

                    # Get content length from headers for comparison
                    header_content_length = int(stream_response.headers.get("content-length", 0))

                    # Log file size info
                    print(
                        f"[RESPONSE] {request_name}: Status={stream_response.status_code}, "
                        f"Content-Length={header_content_length:,} bytes, "
                        f"Actual Read={actual_bytes_read:,} bytes"
                    )

                    # Validate file size if expected_size provided
                    global _size_validation_stats
                    _size_validation_stats["total_downloads"] += 1

                    # Initialize per-file stats if first time seeing this file
                    if request_name not in _size_validation_stats["by_file"]:
                        _size_validation_stats["by_file"][request_name] = {
                            "total": 0,
                            "successful": 0,
                            "mismatches": 0,
                            "expected_bytes": expected_size,
                        }

                    # Update per-file counts
                    _size_validation_stats["by_file"][request_name]["total"] += 1

                    if expected_size is not None:
                        if actual_bytes_read != expected_size:
                            error_msg = f"Size mismatch! Expected {expected_size:,} bytes, got {actual_bytes_read:,} bytes"
                            print(f"[ERROR] {request_name}: {error_msg}")
                            exception = ValueError(error_msg)
                            _size_validation_stats["size_mismatches"] += 1
                            _size_validation_stats["by_file"][request_name]["mismatches"] += 1
                            _size_validation_stats["details"].append(
                                {
                                    "name": request_name,
                                    "expected_bytes": expected_size,
                                    "actual_bytes": actual_bytes_read,
                                    "status": "SIZE_MISMATCH",
                                    "timestamp": time.time(),
                                }
                            )
                        else:
                            print(f"[VALIDATED] {request_name}: Size matches expected {expected_size:,} bytes ✓")
                            _size_validation_stats["successful_validations"] += 1
                            _size_validation_stats["by_file"][request_name]["successful"] += 1
                            _size_validation_stats["details"].append(
                                {
                                    "name": request_name,
                                    "expected_bytes": expected_size,
                                    "actual_bytes": actual_bytes_read,
                                    "status": "OK",
                                    "timestamp": time.time(),
                                }
                            )
                    else:
                        _size_validation_stats["no_validation"] += 1

                    # Check status after reading body
                    stream_response.raise_for_status()

                except httpx.HTTPStatusError as status_error:
                    exception = status_error
                    response_length = 0
                    print(f"[ERROR] {request_name}: HTTP {status_error.response.status_code}")
                except Exception as read_error:
                    # If we can't read the body, treat as exception
                    exception = read_error
                    response_length = 0
                    print(f"[ERROR] {request_name}: {type(read_error).__name__}: {read_error}")

        except httpx.HTTPStatusError as e:
            exception = e
            response = e.response
            response_length = 0
            print(f"[ERROR] {request_name}: HTTP {e.response.status_code}")
        except Exception as e:
            exception = e
            response = None
            response_length = 0
            print(f"[ERROR] {request_name}: {type(e).__name__}: {e}")

        # Calculate response time
        response_time = (time.time() - start_time) * 1000  # ms

        # Report to Locust
        if response is not None:
            if exception:
                events.request.fire(
                    request_type="GET",
                    name=request_name,
                    response_time=response_time,
                    response_length=response_length,
                    exception=exception,
                    context={},
                )
            else:
                events.request.fire(
                    request_type="GET",
                    name=request_name,
                    response_time=response_time,
                    response_length=response_length,
                    response=response,
                    context={},
                )
        else:
            # No response (connection error, etc.)
            events.request.fire(
                request_type="GET",
                name=request_name,
                response_time=response_time,
                response_length=0,
                exception=exception,
                context={},
            )

        if exception and not catch_response:
            raise exception

        return response

    def close(self) -> None:
        """Close the httpx client."""
        self._client.close()


@events.test_start.add_listener
def on_test_start(environment, **kwargs):  # pylint: disable=unused-argument
    """
    Event listener that runs once at the start of the test.

    Initializes validation tracking for the benchmark run.

    NOTE: Warmup now happens BEFORE Locust starts (in run_download_benchmark.py),
    so Locust's timer only measures actual benchmark traffic with no dead time.

    Args:
        environment: Locust environment (required by event listener signature)
        **kwargs: Additional arguments from event system
    """
    global _size_validation_stats

    # Reset validation stats for new test run
    _size_validation_stats = {
        "total_downloads": 0,
        "successful_validations": 0,
        "size_mismatches": 0,
        "no_validation": 0,
        "details": [],
        "by_file": {},
    }

    print("\n" + "=" * 80)
    print("📊 LOCUST BENCHMARK STARTING")
    print("=" * 80)
    print("Warmup already completed by run_download_benchmark.py")
    print("Timer starts NOW - all requests will be counted in statistics")
    print("=" * 80 + "\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """
    Event listener that runs once at the end of the test.

    Saves size validation statistics to a JSON file for reporting.
    """
    global _size_validation_stats

    def format_bytes(bytes_value):
        """Format bytes in human-readable format."""
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_value < 1024.0:
                return f"{bytes_value:.2f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.2f} TB"

    # Save validation stats to file
    validation_file = Path("benchmark_results/size_validation.json")
    validation_file.parent.mkdir(exist_ok=True)

    with open(validation_file, "w", encoding="utf-8") as f:
        json.dump(_size_validation_stats, f, indent=2)

    print("\n" + "=" * 80)
    print("SIZE VALIDATION SUMMARY")
    print("=" * 80)
    print(f"Total Downloads:          {_size_validation_stats['total_downloads']:,}")
    print(f"Successful Validations:   {_size_validation_stats['successful_validations']:,}")
    print(f"Size Mismatches:          {_size_validation_stats['size_mismatches']:,}")
    print(f"No Validation (no size):  {_size_validation_stats['no_validation']:,}")

    if _size_validation_stats["total_downloads"] > 0:
        success_rate = (_size_validation_stats["successful_validations"] / _size_validation_stats["total_downloads"]) * 100
        print(f"Validation Success Rate:  {success_rate:.1f}%")

    # Print per-file breakdown with Locust statistics
    if _size_validation_stats["by_file"]:
        print("\n" + "-" * 80)
        print("PER-FILE BREAKDOWN:")
        print("-" * 80)

        # Get Locust stats for each endpoint
        stats_dict = {}
        for stat_entry in environment.stats.entries.values():
            stats_dict[stat_entry.name] = stat_entry

        for file_name, stats in sorted(_size_validation_stats["by_file"].items()):
            print(f"\n{file_name}:")

            # File size validation
            if stats["expected_bytes"]:
                print(f"  Expected size:     {format_bytes(stats['expected_bytes'])} ({stats['expected_bytes']:,} bytes)")
            else:
                print(f"  Expected size:     N/A")

            print(f"  Total downloads:   {stats['total']:,}")
            print(f"  Successful:        {stats['successful']:,}")
            print(f"  Mismatches:        {stats['mismatches']:,}")

            if stats["total"] > 0:
                file_success_rate = (stats["successful"] / stats["total"]) * 100
                print(f"  Success rate:      {file_success_rate:.1f}%")

            # Add Locust statistics if available
            if file_name in stats_dict:
                locust_stats = stats_dict[file_name]
                print(f"  Locust Statistics:")
                print(f"    Requests:        {locust_stats.num_requests:,}")
                print(f"    Failures:        {locust_stats.num_failures:,}")
                print(f"    Avg size:        {format_bytes(locust_stats.avg_content_length)}")

                # Calculate transfer speed (per request)
                if locust_stats.avg_response_time > 0:
                    transfer_speed = locust_stats.avg_content_length / (locust_stats.avg_response_time / 1000)
                    print(f"    Transfer speed:  {format_bytes(transfer_speed)}/sec")

                print(f"    Avg latency:     {locust_stats.avg_response_time:.0f} ms")
                print(f"    Median latency:  {locust_stats.median_response_time:.0f} ms")

    print(f"\nDetailed validation results saved to: {validation_file}")
    print("=" * 80 + "\n")


class DownloadTaskSet(TaskSet):
    """
    Task set for file download benchmarks.

    Tests three download endpoints with different file sizes (1MB, 5MB, 10MB)
    to measure transfer speeds, latency, and failure rates.
    """

    @task(1)
    def download_1mb(self) -> None:
        """
        Download 1MB test file.

        Endpoint: /download_file/test1.txt
        Expected size: 1,048,576 bytes (1 MiB)
        """
        self.client.get(
            "/download_file/test1.txt",
            params={"usha": "448a74873dc4bc1eb3d3afe4f9fc13f4d0ac24f8bfd8d93d241600afb3189264"},
            name="1MB Download",
            expected_size=1048576,
        )

    @task(1)
    def download_5mb(self) -> None:
        """
        Download 5MB test file.

        Endpoint: /download_file/test5.txt
        Expected size: 5,242,880 bytes (5 MiB)
        """
        self.client.get(
            "/download_file/test5.txt",
            params={"usha": "7671461fdb80a0f6292c720f5b35cf7be4d75e210569c738e5bf399b065eae4e"},
            name="5MB Download",
            expected_size=5242880,
        )

    @task(1)
    def download_10mb(self) -> None:
        """
        Download 10MB test file.

        Endpoint: /download_file/test10.txt
        Expected size: 10,485,760 bytes (10 MiB)
        """
        self.client.get(
            "/download_file/test10.txt",
            params={"usha": "3ad1f3dcea9a38bd0ff082045ae9a07305834f792c3368b71f68a45454298bfb"},
            name="10MB Download",
            expected_size=10485760,
        )


class DownloadUser(User):
    """
    Simulated user for download load testing.

    Uses custom httpx client with HTTP/2 support instead of requests.

    Attributes:
        tasks: The task set to execute (DownloadTaskSet)
        wait_time: Time between requests (1-2 seconds for controlled rate)
        host: Target server URL (set via --host CLI parameter)
    """

    tasks = [DownloadTaskSet]

    # Wait 1-2 seconds between requests to control request rate
    # This helps achieve target request counts without overshooting
    wait_time = between(1, 2)

    def __init__(self, environment):
        """
        Initialize user with custom httpx client.

        Args:
            environment: Locust environment
        """
        super().__init__(environment)

        # Determine SSL verification setting
        verify_ssl = os.getenv("LOCUST_INSECURE", "0") != "1"

        # Create httpx client with HTTP/2 support
        self.client = HttpxClient(
            base_url=self.host,
            verify=verify_ssl,
            http2=True,  # Enable HTTP/2
        )

    def on_start(self) -> None:
        """
        Initialize the user session.

        Server detection and warmup now happen in run_download_benchmark.py
        BEFORE Locust starts, so this method no longer needs to do anything.
        """
        # Warmup and server detection moved to run_download_benchmark.py wrapper
        # to ensure Locust timer only measures actual benchmark traffic

    def on_stop(self) -> None:
        """Clean up httpx client on user stop."""
        self.client.close()

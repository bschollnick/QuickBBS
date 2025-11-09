#!/usr/bin/env python3
"""
Wrapper script to run Locust download benchmarks with Apache Benchmark-like output.

This script runs Locust load tests on download endpoints and generates results
that are comparable to Apache Benchmark (ab) output, including:
- Transfer time
- Transfer speed (MB/s)
- Requests per second
- Latency percentiles (50th, 90th, 95th, 99th)
- Failure count

Usage:
    python run_download_benchmark.py [--host HOST] [--users USERS] [--requests REQUESTS]

Examples:
    # Use defaults (localhost:8888, 50 users, 200 requests)
    python run_download_benchmark.py

    # Custom parameters
    python run_download_benchmark.py --host http://localhost:8000 --users 100 --requests 500
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


def parse_server_workers(server_type: str) -> dict[str, Any]:
    """
    Parse server worker count and configuration from start script.

    Args:
        server_type: Server type ("hypercorn", "uvicorn", or "gunicorn")

    Returns:
        Dictionary with worker configuration or empty dict if not found
    """
    script_map = {
        "hypercorn": "start_hypercorn_http2.sh",
        "uvicorn": "start_uvicorn_http2.sh",
        "gunicorn": "start_gunicorn_http2.sh",
    }

    script_name = script_map.get(server_type.lower())
    if not script_name:
        return {}

    script_path = Path(__file__).parent / script_name
    if not script_path.exists():
        return {}

    config = {}

    try:
        with open(script_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                # Parse WORKERS="<number>"
                if line.startswith("WORKERS="):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    config["workers"] = int(value)

                # Parse WORKER_CLASS (gunicorn specific)
                elif line.startswith("WORKER_CLASS="):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    config["worker_class"] = value

                # Parse TIMEOUT (gunicorn specific)
                elif line.startswith("TIMEOUT="):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    config["timeout"] = int(value)

    except (OSError, ValueError):
        return {}

    return config


def parse_database_config() -> dict[str, Any]:
    """
    Parse database configuration from settings.py.

    Returns:
        Dictionary with database configuration details
    """
    settings_path = Path(__file__).parent / "quickbbs" / "settings.py"
    if not settings_path.exists():
        return {}

    config = {}

    try:
        with open(settings_path, encoding="utf-8") as f:
            content = f.read()

        # Extract CONN_MAX_AGE value
        import re

        conn_max_age_match = re.search(r'"CONN_MAX_AGE":\s*(\d+|None)', content)
        if conn_max_age_match:
            value = conn_max_age_match.group(1)
            config["conn_max_age"] = None if value == "None" else int(value)

        # Extract pool settings
        pool_settings = {}
        pool_pattern = r'"pool":\s*\{([^}]+)\}'
        pool_match = re.search(pool_pattern, content, re.DOTALL)
        if pool_match:
            pool_content = pool_match.group(1)
            # Extract individual pool settings
            for setting in ["min_size", "max_size", "max_lifetime", "max_idle", "timeout"]:
                setting_match = re.search(rf'"{setting}":\s*(\d+)', pool_content)
                if setting_match:
                    pool_settings[setting] = int(setting_match.group(1))

        if pool_settings:
            config["pool"] = pool_settings

    except (OSError, ValueError):
        return {}

    return config


def run_warmup_sequence(host: str, insecure: bool = False) -> dict[str, Any]:
    """
    Run warmup sequence BEFORE starting Locust benchmark.

    This warms up:
    - OS file cache
    - Database query cache
    - Application caches
    - HTTP connections

    Args:
        host: Target host URL
        insecure: Disable SSL certificate verification

    Returns:
        Server configuration dictionary
    """
    print("\n" + "=" * 80)
    print("PRE-BENCHMARK WARMUP SEQUENCE")
    print("=" * 80)
    print("This warmup happens BEFORE Locust starts its timer.")
    print("Warmup requests are NOT counted in benchmark statistics.\n")

    # Determine SSL verification
    verify_ssl = not insecure

    # Create httpx client for warmup
    client = httpx.Client(
        base_url=host,
        verify=verify_ssl,
        http2=True,
        timeout=httpx.Timeout(30.0),
    )

    # Files to warm up (name, usha, expected_size)
    warmup_files = [
        ("test1.txt", "448a74873dc4bc1eb3d3afe4f9fc13f4d0ac24f8bfd8d93d241600afb3189264", 1048576),
        ("test5.txt", "7671461fdb80a0f6292c720f5b35cf7be4d75e210569c738e5bf399b065eae4e", 5242880),
        ("test10.txt", "3ad1f3dcea9a38bd0ff082045ae9a07305834f792c3368b71f68a45454298bfb", 10485760),
    ]

    # Warmup Phase 1
    print("🔥 WARMUP PHASE 1/2")
    print("-" * 80)
    total_warmup = 0
    for filename, usha, expected_size in warmup_files:
        print(f"\nWarming up {filename} ({format_bytes(expected_size)})...")
        for i in range(10):  # Increased from 3 to 10 to match 50 concurrent users
            try:
                url = f"/download_file/{filename}"
                params = {"usha": usha}
                start = time.time()

                response = client.get(url, params=params)
                response.raise_for_status()
                bytes_read = len(response.content)
                elapsed = (time.time() - start) * 1000

                print(f"  Fetch {i+1}/10: {bytes_read:,} bytes in {elapsed:.0f}ms")
                total_warmup += 1

            except Exception as e:
                print(f"  Warning: Warmup request failed: {e}")

    print(f"\nPhase 1 complete: {total_warmup} requests completed")

    # Wait between warmup phases
    print("\n⏳ Waiting 5 seconds before second warmup...")
    time.sleep(5)

    # # Warmup Phase 2
    # print("\n🔥 WARMUP PHASE 2/2")
    # print("-" * 80)
    # total_warmup = 0
    # for filename, usha, expected_size in warmup_files:
    #     print(f"\nWarming up {filename} ({format_bytes(expected_size)})...")
    #     for i in range(10):  # Increased from 3 to 10 to match 50 concurrent users
    #         try:
    #             url = f"/download_file/{filename}"
    #             params = {"usha": usha}
    #             start = time.time()

    #             response = client.get(url, params=params)
    #             response.raise_for_status()
    #             bytes_read = len(response.content)
    #             elapsed = (time.time() - start) * 1000

    #             print(f"  Fetch {i+1}/10: {bytes_read:,} bytes in {elapsed:.0f}ms")
    #             total_warmup += 1

    #         except Exception as e:
    #             print(f"  Warning: Warmup request failed: {e}")

    # print(f"\nPhase 2 complete: {total_warmup} requests completed")

    # Detect server configuration
    print("\n" + "=" * 80)
    print("DETECTING SERVER CONFIGURATION...")
    print("=" * 80)

    server_info = {}
    try:
        response = client.get(
            "/download_file/test1.txt",
            params={"usha": "448a74873dc4bc1eb3d3afe4f9fc13f4d0ac24f8bfd8d93d241600afb3189264"},
        )
        response.raise_for_status()

        server_info["server"] = response.headers.get("Server", "Unknown")
        server_info["http_protocol"] = getattr(response, "http_version", "HTTP/1.1")
        server_info["alt_svc"] = response.headers.get("Alt-Svc", None)
        server_info["connection"] = response.headers.get("Connection", "Unknown")

        # Detect server type from Server header (e.g., "hypercorn-h2" -> "hypercorn")
        server_name = server_info["server"].lower()
        if "hypercorn" in server_name:
            server_type = "hypercorn"
        elif "uvicorn" in server_name:
            server_type = "uvicorn"
        elif "gunicorn" in server_name:
            server_type = "gunicorn"
        else:
            server_type = None

        # Parse worker configuration from start script
        if server_type:
            worker_config = parse_server_workers(server_type)
            if worker_config:
                # Store all worker config
                server_info.update(worker_config)
            else:
                server_info["workers"] = "Unknown"
        else:
            server_info["workers"] = "Unknown"

        # Parse database configuration
        db_config = parse_database_config()
        if db_config:
            server_info["database"] = db_config

        print(f"Server: {server_info['server']}")
        print(f"Protocol: {server_info['http_protocol']}")
        print(f"Workers: {server_info.get('workers', 'Unknown')}")

        # Print gunicorn-specific config if available
        if "worker_class" in server_info:
            print(f"Worker Class: {server_info['worker_class']}")
        if "timeout" in server_info:
            print(f"Worker Timeout: {server_info['timeout']}s")

        print(f"Alt-Svc: {server_info['alt_svc']}")

        # Print database configuration
        if "database" in server_info:
            print("\nDatabase Configuration:")
            db = server_info["database"]
            if "conn_max_age" in db:
                conn_max_age_str = str(db["conn_max_age"]) if db["conn_max_age"] is not None else "None (pool managed)"
                print(f"  CONN_MAX_AGE: {conn_max_age_str}")
            if "pool" in db:
                print(f"  Connection Pool:")
                pool = db["pool"]
                if "min_size" in pool:
                    print(f"    Min size: {pool['min_size']}")
                if "max_size" in pool:
                    print(f"    Max size: {pool['max_size']}")
                if "max_lifetime" in pool:
                    print(f"    Max lifetime: {pool['max_lifetime']}s")
                if "max_idle" in pool:
                    print(f"    Max idle: {pool['max_idle']}s")
                if "timeout" in pool:
                    print(f"    Timeout: {pool['timeout']}s")

    except Exception as e:
        print(f"Warning: Server detection failed: {e}")
        server_info["server"] = "Unknown"
        server_info["http_protocol"] = "Unknown"
        server_info["error"] = str(e)

    client.close()

    print("\n✅ Warmup complete!")
    print("=" * 80)
    print("📊 STARTING LOCUST BENCHMARK - Timer starts NOW")
    print("=" * 80 + "\n")

    return server_info


def parse_args() -> argparse.Namespace:
    """
    Parse command line arguments.

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(description="Run Locust download benchmarks with Apache Benchmark-like output")
    parser.add_argument(
        "--host",
        default="http://localhost:8888",
        help="Target host URL (default: http://localhost:8888)",
    )
    parser.add_argument(
        "--users",
        type=int,
        default=50,
        help="Number of concurrent users (default: 50)",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=200,
        help="Total number of requests (default: 200)",
    )
    parser.add_argument(
        "--spawn-rate",
        type=int,
        default=10,
        help="User spawn rate per second (default: 10 for gradual ramp-up)",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark_results",
        help="Output directory for results (default: benchmark_results)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable SSL certificate verification (for self-signed certs)",
    )
    return parser.parse_args()


def run_locust_benchmark(
    host: str,
    users: int,
    requests: int,
    spawn_rate: int,
    output_dir: Path,
    timestamp: str,
    insecure: bool = False,
) -> tuple[int, str, str]:
    """
    Run Locust benchmark and capture output.

    Args:
        host: Target host URL
        users: Number of concurrent users
        requests: Total number of requests
        spawn_rate: User spawn rate per second
        output_dir: Directory for output files
        timestamp: Timestamp string for filenames
        insecure: Disable SSL certificate verification

    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    # Benchmark duration - warmup happens BEFORE this in run_warmup_sequence()
    # Locust timer starts AFTER warmup completes, so this is pure benchmark time
    run_time_seconds = 30

    csv_prefix = output_dir / f"benchmark_{timestamp}"

    cmd = [
        "locust",
        "-f",
        "locustfile_downloads.py",
        "--host",
        host,
        "--users",
        str(users),
        "--spawn-rate",
        str(spawn_rate),
        "--run-time",
        f"{run_time_seconds}s",
        "--headless",
        "--csv",
        str(csv_prefix),
        "--html",
        str(output_dir / f"benchmark_{timestamp}.html"),
        "--only-summary",
    ]

    print(f"Running Locust benchmark: {' '.join(cmd)}")
    print(f"Target: {host}")
    print(f"Users: {users}")
    print(f"Spawn rate: {spawn_rate} users/sec")
    print(f"Expected requests: ~{requests}")
    print(f"Benchmark duration: {run_time_seconds}s")
    print(f"SSL verification: {'disabled' if insecure else 'enabled'}")
    print(f"Output files: {csv_prefix}_*.csv")
    print()

    # Set up environment for subprocess
    env = os.environ.copy()
    if insecure:
        env["LOCUST_INSECURE"] = "1"

    result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)

    return result.returncode, result.stdout, result.stderr


def parse_csv_results(csv_prefix: str) -> dict[str, Any]:
    """
    Parse Locust CSV output files and calculate statistics.

    Args:
        csv_prefix: Path prefix for CSV files (without _stats.csv suffix)

    Returns:
        Dictionary with parsed statistics
    """
    stats_file = f"{csv_prefix}_stats.csv"

    results: dict[str, Any] = {
        "endpoints": {},
        "total": {},
        "timestamp": datetime.now().isoformat(),
    }

    # Parse main stats file
    if Path(stats_file).exists():
        with open(stats_file, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row["Name"]
                if name == "Aggregated":
                    results["total"] = {
                        "requests": int(row["Request Count"]),
                        "failures": int(row["Failure Count"]),
                        "median_ms": float(row["Median Response Time"]),
                        "p90_ms": float(row["90%"]),
                        "p95_ms": float(row["95%"]),
                        "p99_ms": float(row["99%"]),
                        "avg_ms": float(row["Average Response Time"]),
                        "min_ms": float(row["Min Response Time"]),
                        "max_ms": float(row["100%"]),  # Use 100th percentile (true max)
                        "rps": float(row["Requests/s"]),
                        "avg_size_bytes": float(row["Average Content Size"]),
                    }
                else:
                    results["endpoints"][name] = {
                        "requests": int(row["Request Count"]),
                        "failures": int(row["Failure Count"]),
                        "median_ms": float(row["Median Response Time"]),
                        "p90_ms": float(row["90%"]),
                        "p95_ms": float(row["95%"]),
                        "p99_ms": float(row["99%"]),
                        "avg_ms": float(row["Average Response Time"]),
                        "min_ms": float(row["Min Response Time"]),
                        "max_ms": float(row["100%"]),  # Use 100th percentile (true max)
                        "rps": float(row["Requests/s"]),
                        "avg_size_bytes": float(row["Average Content Size"]),
                    }

    return results


def format_bytes(bytes_value: float) -> str:
    """
    Format bytes in human-readable format.

    Args:
        bytes_value: Size in bytes

    Returns:
        Formatted string (e.g., "1.5 MB")
    """
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} TB"


def print_summary(results: dict[str, Any], host: str, users: int) -> None:
    """
    Print benchmark summary in Apache Benchmark style.

    Args:
        results: Parsed results dictionary
        host: Target host URL
        users: Number of concurrent users
    """
    total = results["total"]

    print("\n" + "=" * 80)
    print("BENCHMARK SUMMARY (Apache Benchmark Style)")
    print("=" * 80)
    print(f"Server:              {host}")

    # Display detected server configuration
    if "server_config" in results:
        server_config = results["server_config"]
        server_name = server_config.get("server", "Unknown")
        http_protocol = server_config.get("http_protocol", "Unknown")
        workers = server_config.get("workers", "Unknown")
        print(f"Server Software:     {server_name}")
        print(f"HTTP Protocol:       {http_protocol}")
        print(f"Server Workers:      {workers}")

        # Display gunicorn-specific configuration
        if "worker_class" in server_config:
            print(f"Worker Class:        {server_config['worker_class']}")
        if "timeout" in server_config:
            print(f"Worker Timeout:      {server_config['timeout']}s")

        # Display database configuration
        if "database" in server_config:
            db = server_config["database"]
            print()
            print("Database Configuration:")
            if "conn_max_age" in db:
                conn_max_age = db["conn_max_age"]
                if conn_max_age is None:
                    print(f"  CONN_MAX_AGE:      None (pool managed)")
                else:
                    print(f"  CONN_MAX_AGE:      {conn_max_age}s")
            if "pool" in db:
                pool = db["pool"]
                print(
                    f"  Connection Pool:   min={pool.get('min_size', 'N/A')}, max={pool.get('max_size', 'N/A')}, "
                    f"lifetime={pool.get('max_lifetime', 'N/A')}s, idle={pool.get('max_idle', 'N/A')}s"
                )

    print()
    print(f"Concurrency Level:   {users}")
    print(f"Complete requests:   {total['requests']:,}")
    print(f"Failed requests:     {total['failures']:,}")

    # Display size validation results if available
    if "size_validation" in results:
        validation = results["size_validation"]
        print()
        print("File Size Validation (Overall):")
        print(f"  Total downloads:        {validation['total_downloads']:,}")
        print(f"  Successful (correct):   {validation['successful_validations']:,}")
        print(f"  Incomplete (mismatch):  {validation['size_mismatches']:,}")
        if validation.get("no_validation", 0) > 0:
            print(f"  No validation (no expected size): {validation['no_validation']:,}")
        if validation["total_downloads"] > 0:
            success_rate = (validation["successful_validations"] / validation["total_downloads"]) * 100
            print(f"  Success rate:           {success_rate:.1f}%")

        # Display per-file breakdown
        if "by_file" in validation and validation["by_file"]:
            print()
            print("  Per-File Breakdown:")
            for file_name, stats in sorted(validation["by_file"].items()):
                print(f"    {file_name}:")
                if stats.get("expected_bytes"):
                    print(f"      Expected size:   {format_bytes(stats['expected_bytes'])} ({stats['expected_bytes']:,} bytes)")
                else:
                    print(f"      Expected size:   N/A")
                print(f"      Downloads:       {stats['total']:,} total, {stats['successful']:,} OK, {stats['mismatches']:,} failed")
                if stats["total"] > 0:
                    file_success_rate = (stats["successful"] / stats["total"]) * 100
                    print(f"      Success rate:    {file_success_rate:.1f}%")

    print()
    print(f"Requests per second: {total['rps']:.2f} [#/sec] (mean)")
    print(f"Transfer rate:       {format_bytes(total['avg_size_bytes'] * total['rps'])}/sec")
    print()

    print("Connection Times (ms)")
    print(f"              min    mean   median   p90    p95    p99    max")
    print(
        f"Total:     {total['min_ms']:7.0f} {total['avg_ms']:7.0f} {total['median_ms']:7.0f} "
        f"{total['p90_ms']:7.0f} {total['p95_ms']:7.0f} {total['p99_ms']:7.0f} {total['max_ms']:7.0f}"
    )
    print()

    print("Per-Endpoint Statistics:")
    print("-" * 80)
    for endpoint_name, stats in results["endpoints"].items():
        print(f"\n{endpoint_name}:")
        print(f"  Requests:      {stats['requests']:,}")
        print(f"  Failures:      {stats['failures']:,}")
        print(f"  Avg size:      {format_bytes(stats['avg_size_bytes'])}")

        # Calculate per-request transfer speed (MB/s per download)
        if stats["avg_ms"] > 0:
            transfer_speed_bytes_per_sec = stats["avg_size_bytes"] / (stats["avg_ms"] / 1000)
            print(f"  Transfer speed: {format_bytes(transfer_speed_bytes_per_sec)}/sec (per request)")

        print(f"  Transfer rate:  {format_bytes(stats['avg_size_bytes'] * stats['rps'])}/sec (aggregate)")
        print(f"  RPS:            {stats['rps']:.2f}")
        print(f"  Latency:")
        print(f"    Median:       {stats['median_ms']:.0f} ms")
        print(f"    90th %ile:    {stats['p90_ms']:.0f} ms")
        print(f"    95th %ile:    {stats['p95_ms']:.0f} ms")
        print(f"    99th %ile:    {stats['p99_ms']:.0f} ms")

    print()
    print("=" * 80)


def save_json_results(results: dict[str, Any], output_file: Path) -> None:
    """
    Save results as JSON for historical comparison.

    Args:
        results: Results dictionary to save
        output_file: Output JSON file path
    """
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to: {output_file}")


def generate_enhanced_html_report(results: dict[str, Any], output_file: Path, host: str, users: int) -> None:
    """
    Generate enhanced HTML report with size validation and performance data.

    Args:
        results: Parsed results dictionary
        output_file: Output HTML file path
        host: Target host URL
        users: Number of concurrent users
    """
    total = results["total"]
    server_config = results.get("server_config", {})
    validation = results.get("size_validation", {})

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Download Benchmark Report - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
            padding: 20px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
            margin-bottom: 30px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
            margin-bottom: 15px;
            padding-bottom: 8px;
            border-bottom: 2px solid #ecf0f1;
        }}
        h3 {{
            color: #7f8c8d;
            margin-top: 20px;
            margin-bottom: 10px;
        }}
        .metadata {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
            padding: 20px;
            background: #ecf0f1;
            border-radius: 5px;
        }}
        .metadata-item {{
            display: flex;
            flex-direction: column;
        }}
        .metadata-label {{
            font-weight: 600;
            color: #7f8c8d;
            font-size: 0.9em;
            margin-bottom: 5px;
        }}
        .metadata-value {{
            font-size: 1.1em;
            color: #2c3e50;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .stat-card.success {{
            background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
        }}
        .stat-card.warning {{
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        }}
        .stat-card.info {{
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
        }}
        .stat-label {{
            font-size: 0.9em;
            opacity: 0.9;
            margin-bottom: 5px;
        }}
        .stat-value {{
            font-size: 2em;
            font-weight: bold;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            background: white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        th {{
            background: #34495e;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
        }}
        td {{
            padding: 12px;
            border-bottom: 1px solid #ecf0f1;
        }}
        tr:hover {{
            background: #f8f9fa;
        }}
        .file-section {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            border-left: 4px solid #3498db;
        }}
        .file-header {{
            font-size: 1.2em;
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 15px;
        }}
        .file-stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
        }}
        .file-stat {{
            background: white;
            padding: 12px;
            border-radius: 5px;
            border-left: 3px solid #3498db;
        }}
        .file-stat-label {{
            font-size: 0.85em;
            color: #7f8c8d;
            margin-bottom: 4px;
        }}
        .file-stat-value {{
            font-size: 1.1em;
            font-weight: 600;
            color: #2c3e50;
        }}
        .success-badge {{
            background: #27ae60;
            color: white;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
        }}
        .failure-badge {{
            background: #e74c3c;
            color: white;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
        }}
        .timestamp {{
            text-align: right;
            color: #95a5a6;
            font-size: 0.9em;
            margin-top: 30px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Download Benchmark Report</h1>

        <div class="metadata">
            <div class="metadata-item">
                <div class="metadata-label">Target Server</div>
                <div class="metadata-value">{host}</div>
            </div>
            <div class="metadata-item">
                <div class="metadata-label">Server Software</div>
                <div class="metadata-value">{server_config.get('server', 'Unknown')}</div>
            </div>
            <div class="metadata-item">
                <div class="metadata-label">HTTP Protocol</div>
                <div class="metadata-value">{server_config.get('http_protocol', 'Unknown')}</div>
            </div>
            <div class="metadata-item">
                <div class="metadata-label">Server Workers</div>
                <div class="metadata-value">{server_config.get('workers', 'Unknown')}</div>
            </div>
"""

    # Add gunicorn-specific configuration if available
    if "worker_class" in server_config:
        html_content += f"""
            <div class="metadata-item">
                <div class="metadata-label">Worker Class</div>
                <div class="metadata-value">{server_config['worker_class']}</div>
            </div>
"""
    if "timeout" in server_config:
        html_content += f"""
            <div class="metadata-item">
                <div class="metadata-label">Worker Timeout</div>
                <div class="metadata-value">{server_config['timeout']}s</div>
            </div>
"""

    html_content += f"""
            <div class="metadata-item">
                <div class="metadata-label">Concurrent Users</div>
                <div class="metadata-value">{users}</div>
            </div>
        </div>
"""

    # Add database configuration section if available
    if "database" in server_config:
        db = server_config["database"]
        html_content += """
        <h2>💾 Database Configuration</h2>
        <div class="metadata">
"""
        if "conn_max_age" in db:
            conn_max_age = db["conn_max_age"]
            conn_max_age_str = "None (pool managed)" if conn_max_age is None else f"{conn_max_age}s"
            html_content += f"""
            <div class="metadata-item">
                <div class="metadata-label">CONN_MAX_AGE</div>
                <div class="metadata-value">{conn_max_age_str}</div>
            </div>
"""
        if "pool" in db:
            pool = db["pool"]
            html_content += f"""
            <div class="metadata-item">
                <div class="metadata-label">Pool Min Size</div>
                <div class="metadata-value">{pool.get('min_size', 'N/A')}</div>
            </div>
            <div class="metadata-item">
                <div class="metadata-label">Pool Max Size</div>
                <div class="metadata-value">{pool.get('max_size', 'N/A')}</div>
            </div>
            <div class="metadata-item">
                <div class="metadata-label">Pool Max Lifetime</div>
                <div class="metadata-value">{pool.get('max_lifetime', 'N/A')}s</div>
            </div>
            <div class="metadata-item">
                <div class="metadata-label">Pool Max Idle</div>
                <div class="metadata-value">{pool.get('max_idle', 'N/A')}s</div>
            </div>
            <div class="metadata-item">
                <div class="metadata-label">Pool Timeout</div>
                <div class="metadata-value">{pool.get('timeout', 'N/A')}s</div>
            </div>
"""
        html_content += """
        </div>
"""

    html_content += f"""
        <h2>📈 Overall Performance</h2>
        <div class="stats-grid">
            <div class="stat-card info">
                <div class="stat-label">Total Requests</div>
                <div class="stat-value">{total['requests']:,}</div>
            </div>
            <div class="stat-card {'warning' if total['failures'] > 0 else 'success'}">
                <div class="stat-label">Failed Requests</div>
                <div class="stat-value">{total['failures']:,}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Requests/Second</div>
                <div class="stat-value">{total['rps']:.2f}</div>
            </div>
            <div class="stat-card success">
                <div class="stat-label">Transfer Rate</div>
                <div class="stat-value">{format_bytes(total['avg_size_bytes'] * total['rps'])}/s</div>
            </div>
        </div>
"""

    # Size Validation Summary
    if validation:
        success_rate = 0
        if validation["total_downloads"] > 0:
            success_rate = (validation["successful_validations"] / validation["total_downloads"]) * 100

        html_content += f"""
        <h2>✅ File Size Validation</h2>
        <div class="stats-grid">
            <div class="stat-card info">
                <div class="stat-label">Total Downloads</div>
                <div class="stat-value">{validation['total_downloads']:,}</div>
            </div>
            <div class="stat-card success">
                <div class="stat-label">Successful</div>
                <div class="stat-value">{validation['successful_validations']:,}</div>
            </div>
            <div class="stat-card {'warning' if validation['size_mismatches'] > 0 else 'info'}">
                <div class="stat-label">Mismatches</div>
                <div class="stat-value">{validation['size_mismatches']:,}</div>
            </div>
            <div class="stat-card {'success' if success_rate >= 95 else 'warning'}">
                <div class="stat-label">Success Rate</div>
                <div class="stat-value">{success_rate:.1f}%</div>
            </div>
        </div>
"""

    # Connection Times Table
    html_content += f"""
        <h2>⏱️ Connection Times (milliseconds)</h2>
        <table>
            <thead>
                <tr>
                    <th>Metric</th>
                    <th>Min</th>
                    <th>Mean</th>
                    <th>Median</th>
                    <th>90th %ile</th>
                    <th>95th %ile</th>
                    <th>99th %ile</th>
                    <th>Max</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><strong>Total</strong></td>
                    <td>{total['min_ms']:.0f}</td>
                    <td>{total['avg_ms']:.0f}</td>
                    <td>{total['median_ms']:.0f}</td>
                    <td>{total['p90_ms']:.0f}</td>
                    <td>{total['p95_ms']:.0f}</td>
                    <td>{total['p99_ms']:.0f}</td>
                    <td>{total['max_ms']:.0f}</td>
                </tr>
            </tbody>
        </table>
"""

    # Per-File Breakdown
    if validation and "by_file" in validation and validation["by_file"]:
        html_content += """
        <h2>📁 Per-File Breakdown</h2>
"""

        for file_name, stats in sorted(validation["by_file"].items()):
            # Get corresponding endpoint stats if available
            endpoint_stats = results["endpoints"].get(file_name, {})

            file_success_rate = 0
            if stats["total"] > 0:
                file_success_rate = (stats["successful"] / stats["total"]) * 100

            expected_size_str = format_bytes(stats["expected_bytes"]) if stats.get("expected_bytes") else "N/A"

            # Calculate transfer speed
            transfer_speed_str = "N/A"
            if endpoint_stats.get("avg_ms", 0) > 0 and endpoint_stats.get("avg_size_bytes", 0) > 0:
                transfer_speed = endpoint_stats["avg_size_bytes"] / (endpoint_stats["avg_ms"] / 1000)
                transfer_speed_str = f"{format_bytes(transfer_speed)}/sec"

            html_content += f"""
        <div class="file-section">
            <div class="file-header">{file_name}</div>
            <div class="file-stats">
                <div class="file-stat">
                    <div class="file-stat-label">Expected Size</div>
                    <div class="file-stat-value">{expected_size_str}</div>
                </div>
                <div class="file-stat">
                    <div class="file-stat-label">Total Downloads</div>
                    <div class="file-stat-value">{stats['total']:,}</div>
                </div>
                <div class="file-stat">
                    <div class="file-stat-label">Successful</div>
                    <div class="file-stat-value">{stats['successful']:,} <span class="success-badge">{file_success_rate:.1f}%</span></div>
                </div>
                <div class="file-stat">
                    <div class="file-stat-label">Mismatches</div>
                    <div class="file-stat-value">{stats['mismatches']:,} {'<span class="failure-badge">Failed</span>' if stats['mismatches'] > 0 else ''}</div>
                </div>
"""

            # Add Locust statistics if available
            if endpoint_stats:
                html_content += f"""
                <div class="file-stat">
                    <div class="file-stat-label">Avg Size (Actual)</div>
                    <div class="file-stat-value">{format_bytes(endpoint_stats.get('avg_size_bytes', 0))}</div>
                </div>
                <div class="file-stat">
                    <div class="file-stat-label">Transfer Speed</div>
                    <div class="file-stat-value">{transfer_speed_str}</div>
                </div>
                <div class="file-stat">
                    <div class="file-stat-label">Requests/Sec</div>
                    <div class="file-stat-value">{endpoint_stats.get('rps', 0):.2f}</div>
                </div>
                <div class="file-stat">
                    <div class="file-stat-label">Median Latency</div>
                    <div class="file-stat-value">{endpoint_stats.get('median_ms', 0):.0f} ms</div>
                </div>
                <div class="file-stat">
                    <div class="file-stat-label">95th Percentile</div>
                    <div class="file-stat-value">{endpoint_stats.get('p95_ms', 0):.0f} ms</div>
                </div>
"""

            html_content += """
            </div>
        </div>
"""

    # Per-Endpoint Statistics Table
    if results.get("endpoints"):
        html_content += """
        <h2>📊 Detailed Endpoint Statistics</h2>
        <table>
            <thead>
                <tr>
                    <th>Endpoint</th>
                    <th>Requests</th>
                    <th>Failures</th>
                    <th>Avg Size</th>
                    <th>Transfer Speed</th>
                    <th>RPS</th>
                    <th>Median (ms)</th>
                    <th>95th %ile (ms)</th>
                </tr>
            </thead>
            <tbody>
"""

        for endpoint_name, stats in sorted(results["endpoints"].items()):
            transfer_speed = "N/A"
            if stats.get("avg_ms", 0) > 0:
                speed_bytes_per_sec = stats["avg_size_bytes"] / (stats["avg_ms"] / 1000)
                transfer_speed = f"{format_bytes(speed_bytes_per_sec)}/sec"

            html_content += f"""
                <tr>
                    <td><strong>{endpoint_name}</strong></td>
                    <td>{stats['requests']:,}</td>
                    <td>{stats['failures']:,}</td>
                    <td>{format_bytes(stats['avg_size_bytes'])}</td>
                    <td>{transfer_speed}</td>
                    <td>{stats['rps']:.2f}</td>
                    <td>{stats['median_ms']:.0f}</td>
                    <td>{stats['p95_ms']:.0f}</td>
                </tr>
"""

        html_content += """
            </tbody>
        </table>
"""

    # Footer
    html_content += f"""
        <div class="timestamp">
            Generated on {datetime.now().strftime("%Y-%m-%d at %H:%M:%S")}
        </div>
    </div>
</body>
</html>
"""

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Enhanced HTML report generated: {output_file}")


def main() -> int:
    """
    Run benchmark and generate results.

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    args = parse_args()

    # Use spawn rate from args (default is 10 for gradual ramp-up)
    spawn_rate = args.spawn_rate

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)

    # Generate timestamp for this run
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Run warmup sequence BEFORE starting Locust
    # This ensures Locust's timer only measures actual benchmark traffic
    server_config = run_warmup_sequence(args.host, args.insecure)

    # Save server info to file for Locust to read (even though warmup already detected it)
    server_info_file = output_dir / "server_info.json"
    with open(server_info_file, "w", encoding="utf-8") as f:
        json.dump(server_config, f, indent=2)

    # Run benchmark - timer starts NOW, after warmup completes
    return_code, stdout, stderr = run_locust_benchmark(args.host, args.users, args.requests, spawn_rate, output_dir, timestamp, args.insecure)

    # Print Locust output
    if stdout:
        print(stdout)
    if stderr:
        print("STDERR:", stderr, file=sys.stderr)

    if return_code != 0:
        print(f"Error: Locust exited with code {return_code}", file=sys.stderr)
        return return_code

    # Parse results
    csv_prefix = output_dir / f"benchmark_{timestamp}"
    results = parse_csv_results(str(csv_prefix))

    if not results.get("total"):
        print("Error: Could not parse benchmark results", file=sys.stderr)
        return 1

    # Load server information captured by Locust
    server_info_file = output_dir / "server_info.json"
    if server_info_file.exists():
        try:
            with open(server_info_file, encoding="utf-8") as f:
                results["server_config"] = json.load(f)
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Warning: Could not load server info: {e}", file=sys.stderr)
            results["server_config"] = {"server": "Unknown", "http_protocol": "Unknown"}
    else:
        results["server_config"] = {"server": "Unknown", "http_protocol": "Unknown"}

    # Load size validation results captured by Locust
    validation_file = output_dir / "size_validation.json"
    if validation_file.exists():
        try:
            with open(validation_file, encoding="utf-8") as f:
                results["size_validation"] = json.load(f)
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Warning: Could not load size validation stats: {e}", file=sys.stderr)

    # Save JSON results for comparison
    json_file = output_dir / f"benchmark_{timestamp}.json"
    save_json_results(results, json_file)

    # Generate enhanced HTML report
    enhanced_html_file = output_dir / f"benchmark_{timestamp}_enhanced.html"
    generate_enhanced_html_report(results, enhanced_html_file, args.host, args.users)

    # Print summary
    print_summary(results, args.host, args.users)

    print(f"\nDetailed results available:")
    print(f"  Locust HTML:       {csv_prefix}.html (standard Locust report)")
    print(f"  Enhanced HTML:     {enhanced_html_file} (with validation data)")
    print(f"  JSON data:         {json_file}")
    print(f"  CSV files:         {csv_prefix}_*.csv")
    if validation_file.exists():
        print(f"  Size validation:   {validation_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

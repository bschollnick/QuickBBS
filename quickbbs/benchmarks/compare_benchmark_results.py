#!/usr/bin/env python3
"""
Compare multiple Locust benchmark results to track performance changes over time.

This script reads JSON benchmark results and displays comparison tables showing
how performance metrics have changed between runs.

Usage:
    # Compare latest two runs
    python compare_benchmark_results.py

    # Compare specific runs
    python compare_benchmark_results.py benchmark_20250124_120000.json benchmark_20250124_130000.json

    # Compare latest N runs
    python compare_benchmark_results.py --last 5

    # List all available results
    python compare_benchmark_results.py --list
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    """
    Parse command line arguments.

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(description="Compare Locust benchmark results over time")
    parser.add_argument(
        "files",
        nargs="*",
        help="JSON result files to compare (default: latest 2)",
    )
    parser.add_argument(
        "--results-dir",
        default="benchmark_results",
        help="Directory containing results (default: benchmark_results)",
    )
    parser.add_argument(
        "--last",
        type=int,
        help="Compare last N results",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available result files",
    )
    return parser.parse_args()


def find_result_files(results_dir: Path, count: int | None = None) -> list[Path]:
    """
    Find JSON result files in directory.

    Args:
        results_dir: Directory to search
        count: Number of latest files to return (None = all)

    Returns:
        List of result file paths, sorted by modification time (newest first)
    """
    json_files = sorted(
        results_dir.glob("benchmark_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if count is not None:
        return json_files[:count]
    return json_files


def load_result(file_path: Path) -> dict[str, Any] | None:
    """
    Load benchmark result from JSON file.

    Args:
        file_path: Path to JSON result file

    Returns:
        Result dictionary or None on error
    """
    try:
        with open(file_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error loading {file_path}: {e}", file=sys.stderr)
        return None


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


def format_percent_change(old_value: float, new_value: float) -> str:
    """
    Format percentage change between two values.

    Args:
        old_value: Original value
        new_value: New value

    Returns:
        Formatted string with percentage and direction indicator
    """
    if old_value == 0:
        return "N/A"

    change = ((new_value - old_value) / old_value) * 100
    if change > 0:
        return f"+{change:.1f}%"
    elif change < 0:
        return f"{change:.1f}%"
    else:
        return "0.0%"


def print_comparison_header(result_files: list[Path]) -> None:
    """
    Print comparison header with file names and timestamps.

    Args:
        result_files: List of result file paths
    """
    print("=" * 100)
    print("BENCHMARK COMPARISON")
    print("=" * 100)
    print()
    print("Comparing results:")
    for i, path in enumerate(result_files, 1):
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        print(f"  [{i}] {path.name} ({mtime.strftime('%Y-%m-%d %H:%M:%S')})")
    print()


def compare_server_config(results: list[dict[str, Any]]) -> None:
    """
    Compare server configuration across multiple results.

    Args:
        results: List of result dictionaries
    """
    print("Server Configuration:")
    print("-" * 100)

    # Check if any results have server config
    has_config = any("server_config" in r for r in results)
    if not has_config:
        print("  No server configuration information available")
        print("-" * 100)
        print()
        return

    # Header
    header = f"{'Setting':<25}"
    for i in range(len(results)):
        header += f" | Run {i+1:2d}{'':>20}"
    print(header)
    print("-" * 100)

    # Server configuration fields
    config_fields = [
        ("Server Software", "server"),
        ("HTTP Protocol", "http_protocol"),
        ("Connection Type", "connection"),
        ("Alt-Svc Header", "alt_svc"),
    ]

    for field_name, key in config_fields:
        row = f"{field_name:<25}"
        values = []

        for result in results:
            server_config = result.get("server_config", {})
            value = server_config.get(key, "Unknown")

            # Handle None values for optional fields
            if value is None:
                value = "N/A"

            values.append(value)
            row += f" | {str(value):>24}"

        # Mark if configuration changed
        if len(set(values)) > 1:
            row += " ⚠️  CHANGED"

        print(row)

    print("-" * 100)
    print()


def compare_metrics(results: list[dict[str, Any]]) -> None:
    """
    Compare key metrics across multiple results.

    Args:
        results: List of result dictionaries
    """
    if len(results) < 2:
        print("Need at least 2 results to compare")
        return

    print("Overall Performance Comparison:")
    print("-" * 100)

    # Header
    header = f"{'Metric':<25}"
    for i in range(len(results)):
        header += f" | Run {i+1:2d}{'':>12}"
    if len(results) > 1:
        header += " | Change"
    print(header)
    print("-" * 100)

    # Extract totals
    totals = [r.get("total", {}) for r in results]

    metrics = [
        ("Requests", "requests", "{:,}", False),
        ("Failures", "failures", "{:,}", False),
        ("Requests/sec", "rps", "{:.2f}", True),
        ("Avg Latency (ms)", "avg_ms", "{:.1f}", False),
        ("Median Latency (ms)", "median_ms", "{:.1f}", False),
        ("P95 Latency (ms)", "p95_ms", "{:.1f}", False),
        ("P99 Latency (ms)", "p99_ms", "{:.1f}", False),
        ("Transfer rate", "avg_size_bytes", None, True),
    ]

    for metric_name, key, fmt, higher_is_better in metrics:
        row = f"{metric_name:<25}"

        values = []
        for total in totals:
            value = total.get(key, 0)
            values.append(value)

            if key == "avg_size_bytes":
                # Special handling for transfer rate
                rps = total.get("rps", 0)
                transfer_rate = value * rps
                row += f" | {format_bytes(transfer_rate):>16}"
            elif fmt:
                row += f" | {fmt.format(value):>16}"
            else:
                row += f" | {value:>16}"

        # Add change indicator for latest vs baseline
        if len(values) > 1:
            if key == "avg_size_bytes":
                old_rate = values[0] * totals[0].get("rps", 0)
                new_rate = values[-1] * totals[-1].get("rps", 0)
                change = format_percent_change(old_rate, new_rate)
            else:
                change = format_percent_change(values[0], values[-1])

            # Add performance indicator
            if change != "N/A" and change != "0.0%":
                if higher_is_better:
                    indicator = "✓" if "+" in change else "✗"
                else:
                    indicator = "✗" if "+" in change else "✓"
                row += f" | {change:>8} {indicator}"
            else:
                row += f" | {change:>8}  "

        print(row)

    print("-" * 100)
    print()


def compare_endpoints(results: list[dict[str, Any]]) -> None:
    """
    Compare per-endpoint metrics across results.

    Args:
        results: List of result dictionaries
    """
    # Get all unique endpoint names
    all_endpoints = set()
    for result in results:
        all_endpoints.update(result.get("endpoints", {}).keys())

    if not all_endpoints:
        print("No endpoint data available")
        return

    print("Per-Endpoint Performance:")
    print("-" * 100)

    for endpoint in sorted(all_endpoints):
        print(f"\n{endpoint}:")
        print("-" * 100)

        header = f"{'Metric':<20}"
        for i in range(len(results)):
            header += f" | Run {i+1:2d}{'':>10}"
        if len(results) > 1:
            header += " | Change"
        print(header)
        print("-" * 100)

        endpoint_stats = [r.get("endpoints", {}).get(endpoint, {}) for r in results]

        metrics = [
            ("Requests", "requests", "{:,}"),
            ("Failures", "failures", "{:,}"),
            ("RPS", "rps", "{:.2f}"),
            ("Median (ms)", "median_ms", "{:.1f}"),
            ("P95 (ms)", "p95_ms", "{:.1f}"),
            ("P99 (ms)", "p99_ms", "{:.1f}"),
        ]

        for metric_name, key, fmt in metrics:
            row = f"{metric_name:<20}"

            values = []
            for stats in endpoint_stats:
                value = stats.get(key, 0)
                values.append(value)
                row += f" | {fmt.format(value):>14}"

            # Add change indicator
            if len(values) > 1:
                change = format_percent_change(values[0], values[-1])
                row += f" | {change:>8}"

            print(row)

    print("-" * 100)


def list_results(results_dir: Path) -> None:
    """
    List all available result files.

    Args:
        results_dir: Directory containing results
    """
    files = find_result_files(results_dir)

    if not files:
        print(f"No benchmark results found in {results_dir}")
        return

    print(f"Available benchmark results in {results_dir}:")
    print("-" * 80)
    print(f"{'Filename':<40} {'Date':<20} {'Requests':<10} {'RPS':<10}")
    print("-" * 80)

    for path in files:
        result = load_result(path)
        if result:
            total = result.get("total", {})
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            print(f"{path.name:<40} {mtime.strftime('%Y-%m-%d %H:%M:%S'):<20} " f"{total.get('requests', 0):<10,} {total.get('rps', 0):<10.2f}")

    print("-" * 80)
    print(f"Total: {len(files)} result file(s)")


def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    args = parse_args()
    results_dir = Path(args.results_dir)

    if not results_dir.exists():
        print(f"Error: Results directory not found: {results_dir}", file=sys.stderr)
        return 1

    # Handle --list flag
    if args.list:
        list_results(results_dir)
        return 0

    # Determine which files to compare
    if args.files:
        result_files = [Path(f) for f in args.files]
    elif args.last:
        result_files = find_result_files(results_dir, args.last)
    else:
        # Default: compare latest 2
        result_files = find_result_files(results_dir, 2)

    if not result_files:
        print(f"No result files found in {results_dir}", file=sys.stderr)
        return 1

    if len(result_files) < 2:
        print("Need at least 2 result files to compare", file=sys.stderr)
        print(f"Found only: {result_files[0].name}")
        print("\nRun another benchmark first, or use --list to see available results")
        return 1

    # Load results
    results = []
    for path in result_files:
        result = load_result(path)
        if result:
            results.append(result)
        else:
            print(f"Skipping {path.name} due to load error", file=sys.stderr)

    if len(results) < 2:
        print("Need at least 2 valid results to compare", file=sys.stderr)
        return 1

    # Print comparison
    print_comparison_header(result_files)
    compare_server_config(results)
    compare_metrics(results)
    compare_endpoints(results)

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Compare two QuickBBS benchmark logs produced by run_hey.sh.

Each log contains one or more RUN blocks (test1.bin, test2.bin, ...) with a
labelled Summary of seven metrics. This tool parses two logs -- a BASELINE
(old) and a CANDIDATE (new) -- and reports the per-metric delta and percent
change for every run present in both, annotating whether the candidate
improved or regressed.

Usage:
    ./hey_compare.py BASELINE.log CANDIDATE.log
    ./hey_compare.py                     # auto-pick two newest logs in logs/
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from dataclasses import dataclass

# Metric label -> direction. 1 = higher is better, -1 = lower is better,
# 0 = informational (no better/worse judgement).
METRICS: dict[str, int] = {
    "Total Time": -1,
    "Slowest": -1,
    "Fastest": -1,
    "Average": -1,
    "Requests/sec": 1,
    "Total Data": 0,
    "Size/request": 0,
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG_DIR = os.environ.get("LOG_DIR", os.path.join(SCRIPT_DIR, "logs"))

_RUN_RE = re.compile(r"^ RUN:\s+(\S+)")
_METRIC_RE = re.compile(r"^\s+(.+?)\s*:\s*([0-9][0-9.]*)")


@dataclass
class Comparison:
    """A single metric compared across baseline and candidate."""

    metric: str
    baseline: float | None
    candidate: float | None
    direction: int

    @property
    def delta(self) -> float | None:
        """Return candidate minus baseline, or None if a value is missing."""
        if self.baseline is None or self.candidate is None:
            return None
        return self.candidate - self.baseline

    @property
    def pct(self) -> float | None:
        """Return the percent change from baseline, or None if unavailable."""
        if self.delta is None or self.baseline is None or self.baseline == 0:
            return None
        return (self.delta / self.baseline) * 100.0

    @property
    def result(self) -> str:
        """Return a verdict: BETTER/WORSE, FASTER/SLOWER, 'same', or '-'."""
        if self.direction == 0:
            return "-"
        if self.delta is None:
            return "-"
        if self.delta == 0:
            return "same"
        improved = (self.direction == 1 and self.delta > 0) or (self.direction == -1 and self.delta < 0)
        if self.direction == 1:
            return "BETTER" if improved else "WORSE"
        return "FASTER" if improved else "SLOWER"


def parse_log(path: str) -> dict[str, dict[str, float]]:
    """Parse a run_hey.sh log into {run_name: {metric: value}}.

    Args:
        path: Filesystem path to a benchmark log.

    Returns:
        A mapping of run name to a mapping of metric label to numeric value.
        Only the leading numeric portion of each value is kept (units and
        "n/a" entries are dropped).
    """
    runs: dict[str, dict[str, float]] = {}
    current: str | None = None

    with open(path, encoding="utf-8") as handle:
        for line in handle:
            run_match = _RUN_RE.match(line)
            if run_match:
                current = run_match.group(1)
                runs.setdefault(current, {})
                continue
            if current is None:
                continue
            metric_match = _METRIC_RE.match(line)
            if not metric_match:
                continue
            label, raw = metric_match.group(1), metric_match.group(2)
            if label in METRICS:
                runs[current][label] = float(raw)

    return runs


def resolve_logs(args: argparse.Namespace) -> tuple[str, str]:
    """Determine the baseline and candidate log paths.

    Args:
        args: Parsed command-line arguments.

    Returns:
        A (baseline, candidate) tuple of readable log paths.

    Raises:
        SystemExit: If explicit paths are unreadable or auto-selection cannot
            find two logs in the log directory.
    """
    if args.baseline and args.candidate:
        baseline, candidate = args.baseline, args.candidate
    else:
        pattern = os.path.join(args.log_dir, "hey-*.log")
        found = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        if len(found) < 2:
            sys.exit(f"Error: need two logs in {args.log_dir} (found {len(found)}).\n" f"Usage: {sys.argv[0]} BASELINE.log CANDIDATE.log")
        candidate, baseline = found[0], found[1]

    for path in (baseline, candidate):
        if not os.access(path, os.R_OK):
            sys.exit(f"Error: cannot read log '{path}'.")
    return baseline, candidate


def fmt(value: float | None, suffix: str = "") -> str:
    """Format an optional numeric value for display, or 'n/a' if missing.

    Whole numbers (e.g. byte counts) render as plain integers rather than in
    scientific notation; fractional values keep up to four decimal places.

    Args:
        value: The number to format, or None.
        suffix: Optional trailing unit string.

    Returns:
        The formatted value, or "n/a" when value is None.
    """
    if value is None:
        return "n/a"
    if value == int(value):
        return f"{int(value)}{suffix}"
    return f"{value:.4f}{suffix}"


def report(baseline: str, candidate: str) -> None:
    """Print a per-run, per-metric comparison of two benchmark logs.

    Args:
        baseline: Path to the baseline (old) log.
        candidate: Path to the candidate (new) log.
    """
    base_data = parse_log(baseline)
    cand_data = parse_log(candidate)

    print("===============================================================")
    print(" QuickBBS Benchmark Comparison")
    print(f"   BASELINE  : {baseline}")
    print(f"   CANDIDATE : {candidate}")
    print("===============================================================\n")

    runs = sorted(set(base_data) | set(cand_data))
    if not runs:
        print(" No RUN blocks found in either log.")
        return

    header = f"   {'Metric':<14}{'Baseline':>14}{'Candidate':>14}{'Delta':>14}{'Change':>11}  {'Result'}"

    for run in runs:
        print("---------------------------------------------------------------")
        print(f" RUN: {run}")
        print("---------------------------------------------------------------")
        print(header)

        base_metrics = base_data.get(run, {})
        cand_metrics = cand_data.get(run, {})
        for metric, direction in METRICS.items():
            comp = Comparison(
                metric=metric,
                baseline=base_metrics.get(metric),
                candidate=cand_metrics.get(metric),
                direction=direction,
            )
            pct = f"{comp.pct:+.2f}%" if comp.pct is not None else "n/a"
            if comp.delta is None:
                delta = "n/a"
            elif comp.delta == int(comp.delta):
                delta = f"{int(comp.delta):+d}"
            else:
                delta = f"{comp.delta:+.4f}"
            print(f"   {metric:<14}{fmt(comp.baseline):>14}{fmt(comp.candidate):>14}" f"{delta:>14}{pct:>11}  {comp.result}")
        print()

    print("===============================================================")
    print(" Legend: BETTER/FASTER = candidate improved over baseline.")
    print("         WORSE/SLOWER  = candidate regressed. '-' = informational.")
    print("===============================================================")


def main() -> None:
    """Parse arguments and run the comparison report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", nargs="?", help="Baseline (old) log file.")
    parser.add_argument("candidate", nargs="?", help="Candidate (new) log file.")
    parser.add_argument(
        "--log-dir",
        default=DEFAULT_LOG_DIR,
        help="Directory to auto-select logs from when paths are omitted.",
    )
    args = parser.parse_args()

    if bool(args.baseline) != bool(args.candidate):
        parser.error("provide both BASELINE and CANDIDATE, or neither.")

    baseline, candidate = resolve_logs(args)
    report(baseline, candidate)


if __name__ == "__main__":
    main()

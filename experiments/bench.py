#!/usr/bin/env python3
"""Benchmark driver: run several experimental variants against several test
cases through the existing Docker-sandboxed checker, and print a comparison
table.

Reuses the safety mechanism already built into scripts/bench_experiment.sh
(backup real file -> copy variant in -> run checker -> restore original,
via an EXIT trap) for every (variant, test-case) pair, so part_a.py/part_b.py
are never left mutated even if this script is interrupted. This script is
the repo's own trusted code -- it only orchestrates calls into the existing
sandboxed checker invocation, it does not itself need sandboxing, and it
does not reimplement any verification/objective logic.

Usage:
    python3 experiments/bench.py --config experiments/bench_config_a_fast.json

Config file: a JSON object with:
    "target": "part_a.py" or "part_b.py"
    "part": "a" or "b"
    "variants": {"label": "experiments/part_a_foo.py", ...}
    "tests": "suite_002/test1.csv,suite_003/test8.csv,..."   (comma-separated,
             same syntax as run_checker.sh's TESTS)
    "jobs": 6
    "cpus": 8

Prints one row per variant with: PASS/FAIL/SUBOPTIMAL/MATCHED counts, total
wall time, and (if available) objective-vs-model gaps. A "baseline" label
(pointing at the real, unmodified part_a.py/part_b.py) is always run first
for comparison if present in the config, or can be added automatically via
--include-baseline.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCH_SCRIPT = REPO_ROOT / "scripts" / "bench_experiment.sh"

RESULT_LINE = re.compile(
    r"^[AB] (?P<case>\S+): (?P<result>\S+)"
    r"(?: objective=(?P<objective>\S+))?"
    r"(?: model_objective=(?P<model>\S+))?"
    r" seconds=(?P<seconds>[\d.]+)"
)


def run_one(variant_path: str, target: str, part: str, tests: str, jobs: int, cpus: int) -> dict:
    """Run one variant through bench_experiment.sh and parse its output."""
    env_overrides = {
        "VARIANT": variant_path,
        "TARGET": target,
        "PART": part,
        "TESTS": tests,
        "JOBS": str(jobs),
        "CPUS": str(cpus),
    }
    import os

    env = os.environ.copy()
    env.update(env_overrides)

    proc = subprocess.run(
        [str(BENCH_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    output = proc.stdout + proc.stderr

    rows = []
    for line in output.splitlines():
        m = RESULT_LINE.match(line)
        if m:
            rows.append(m.groupdict())

    return {"raw": output, "rows": rows}


def summarize(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    total_seconds = 0.0
    gaps = []
    for row in rows:
        counts[row["result"]] = counts.get(row["result"], 0) + 1
        total_seconds += float(row["seconds"])
        if row.get("objective") and row.get("model") and row["objective"] != "None":
            try:
                obj = int(row["objective"])
                model = int(row["model"])
                gaps.append(obj - model)
            except ValueError:
                pass
    summary = {
        "counts": counts,
        "total_seconds": round(total_seconds, 1),
        "n": len(rows),
    }
    if gaps:
        summary["avg_gap"] = round(sum(gaps) / len(gaps), 1)
    return summary


def run_baseline(target: str, part: str, tests: str, jobs: int, cpus: int) -> dict:
    """Run the checker directly against the real, unmodified target file
    (no swap needed) for a baseline comparison row."""
    import os

    env = os.environ.copy()
    env.update({"PART": part, "TESTS": tests, "JOBS": str(jobs), "CPUS": str(cpus)})
    proc = subprocess.run(
        [str(REPO_ROOT / "scripts" / "run_checker.sh")],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    output = proc.stdout + proc.stderr
    rows = [m.groupdict() for line in output.splitlines() if (m := RESULT_LINE.match(line))]
    return {"raw": output, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="path to a JSON config file")
    parser.add_argument(
        "--include-baseline",
        action="store_true",
        help="also run the real, unmodified target file as a 'baseline' row",
    )
    parser.add_argument("--verbose", action="store_true", help="print raw checker output too")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text())
    target = config["target"]
    part = config["part"]
    tests = config["tests"]
    jobs = config.get("jobs", 4)
    cpus = config.get("cpus", 6)
    variants: dict[str, str] = config["variants"]

    results: dict[str, dict] = {}

    if args.include_baseline:
        print(f"[bench] running baseline ({target}, unmodified)...", file=sys.stderr)
        result = run_baseline(target, part, tests, jobs, cpus)
        results["baseline"] = result
        if args.verbose:
            print(result["raw"])

    for label, variant_path in variants.items():
        print(f"[bench] running {label} ({variant_path})...", file=sys.stderr)
        result = run_one(variant_path, target, part, tests, jobs, cpus)
        results[label] = result
        if args.verbose:
            print(result["raw"])

    print()
    print(f"{'variant':<28} {'n':>4} {'counts':<40} {'total_s':>9} {'avg_gap':>9}")
    print("-" * 95)
    for label, result in results.items():
        summary = summarize(result["rows"])
        counts_str = " ".join(f"{k}={v}" for k, v in sorted(summary["counts"].items()))
        avg_gap = summary.get("avg_gap", "-")
        print(
            f"{label:<28} {summary['n']:>4} {counts_str:<40} "
            f"{summary['total_seconds']:>9} {avg_gap!s:>9}"
        )

    # Per-case breakdown, to see exactly which cases each variant fixes.
    print()
    all_cases = sorted({row["case"] for result in results.values() for row in result["rows"]})
    header = f"{'case':<32}" + "".join(f"{label:<20}" for label in results)
    print(header)
    print("-" * len(header))
    for case in all_cases:
        line = f"{case:<32}"
        for label, result in results.items():
            match = next((r for r in result["rows"] if r["case"] == case), None)
            cell = match["result"] if match else "?"
            line += f"{cell:<20}"
        print(line)


if __name__ == "__main__":
    main()

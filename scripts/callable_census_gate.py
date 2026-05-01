"""CI gate: callable coverage census.

Scans all veilbreakers_terrain/handlers/*.py for function/method definitions,
cross-references against GRADES_VERIFIED.csv, and fails if uncovered callables
exceed the locked baseline count (ratchet mechanism).

Usage:
    python scripts/callable_census_gate.py                 # check against lock
    python scripts/callable_census_gate.py --update        # write new lock baseline
    python scripts/callable_census_gate.py --report        # print full uncovered list
    python scripts/callable_census_gate.py --strict-zero   # fail unless every callable is graded

Exit codes:
    0  — covered or at/below baseline
    1  — coverage regression (uncovered count exceeds baseline)
    2  — lock file missing and --update not given; run --update first
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

try:
    from grade_audit_shared import collect_callables
except ModuleNotFoundError:
    from scripts.grade_audit_shared import collect_callables

CSV_PATH = Path(__file__).resolve().parent.parent / "docs" / "aaa-audit" / "GRADES_VERIFIED.csv"
LOCK_PATH = Path(__file__).resolve().parent / "callable_census_gate.lock"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CallableEntry:
    filename: str
    func_name: str
    qualified_name: str
    lineno: int


@dataclass
class CensusResult:
    total_callables: int
    graded_callables: int
    uncovered: List[CallableEntry] = field(default_factory=list)

    @property
    def uncovered_count(self) -> int:
        return len(self.uncovered)

    @property
    def coverage_pct(self) -> float:
        if self.total_callables == 0:
            return 100.0
        return 100.0 * self.graded_callables / self.total_callables


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _load_graded_set() -> Set[Tuple[str, str]]:
    """Return grade coverage keys with qualified and simple-name support."""
    graded: Set[Tuple[str, str]] = set()
    if not CSV_PATH.exists():
        print(f"WARNING: GRADES_VERIFIED.csv not found at {CSV_PATH}", file=sys.stderr)
        return graded
    with CSV_PATH.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            file_name = (row.get("File") or "").strip()
            function_name = (row.get("Function") or "").strip()
            if not file_name or not function_name:
                continue
            graded.add((file_name, function_name))
            graded.add((file_name, function_name.split(".")[-1]))
    return graded


# ---------------------------------------------------------------------------
# Census
# ---------------------------------------------------------------------------

def run_census() -> CensusResult:
    graded = _load_graded_set()
    all_callables = [
        CallableEntry(
            filename=callable_def.file,
            func_name=callable_def.simple_name,
            qualified_name=callable_def.qualified_name,
            lineno=callable_def.lineno,
        )
        for callable_def in collect_callables(include_init=False)
    ]

    uncovered = [
        e for e in all_callables
        if (e.filename, e.qualified_name) not in graded and (e.filename, e.func_name) not in graded
    ]

    return CensusResult(
        total_callables=len(all_callables),
        graded_callables=len(all_callables) - len(uncovered),
        uncovered=uncovered,
    )


# ---------------------------------------------------------------------------
# Lock file helpers
# ---------------------------------------------------------------------------

def _read_lock() -> Dict:
    if not LOCK_PATH.exists():
        return {}
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _write_lock(result: CensusResult) -> None:
    payload = {
        "baseline_uncovered": result.uncovered_count,
        "total_callables": result.total_callables,
        "graded_callables": result.graded_callables,
        "coverage_pct": round(result.coverage_pct, 2),
    }
    LOCK_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Lock written: {LOCK_PATH}")
    print(f"  baseline_uncovered = {result.uncovered_count}")
    print(f"  total_callables    = {result.total_callables}")
    print(f"  coverage_pct       = {result.coverage_pct:.1f}%")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_report(result: CensusResult) -> None:
    print("\nCallable Census Report")
    print(f"  Total callables : {result.total_callables}")
    print(f"  Graded          : {result.graded_callables}")
    print(f"  Uncovered       : {result.uncovered_count}")
    print(f"  Coverage        : {result.coverage_pct:.1f}%")
    if result.uncovered:
        print(f"\nUncovered callables ({result.uncovered_count}):")
        for e in sorted(result.uncovered, key=lambda x: (x.filename, x.lineno)):
            print(f"  {e.filename}:{e.lineno}  {e.func_name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="Write the current uncovered count as the ratchet baseline.")
    parser.add_argument("--report", action="store_true", help="Print the full callable census report.")
    parser.add_argument(
        "--strict-zero",
        action="store_true",
        help="Fail unless every scanned callable has an explicit grade row. This is the AAA readiness gate.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    update_mode = args.update
    report_mode = args.report or args.strict_zero

    result = run_census()

    if report_mode or update_mode:
        _print_report(result)

    if args.strict_zero:
        if result.uncovered:
            print(
                f"FAIL: strict callable coverage requires 0 uncovered callables; "
                f"found {result.uncovered_count}.",
                file=sys.stderr,
            )
            return 1
        print("PASS: strict callable coverage has 0 uncovered callables.")
        return 0

    if update_mode:
        _write_lock(result)
        return 0

    lock = _read_lock()
    if not lock:
        print(
            "ERROR: Lock file missing. Run with --update to establish baseline.",
            file=sys.stderr,
        )
        return 2

    baseline = lock["baseline_uncovered"]
    current = result.uncovered_count

    print(f"Callable census: {current} uncovered / {result.total_callables} total "
          f"({result.coverage_pct:.1f}% graded)  [baseline: {baseline}]")

    if current > baseline:
        delta = current - baseline
        print(
            f"FAIL: {delta} new uncovered callable(s) since baseline. "
            "Add entries to GRADES_VERIFIED.csv or run --update to reset baseline.",
            file=sys.stderr,
        )
        if not report_mode:
            _print_report(result)
        return 1

    if current < baseline:
        print(f"  Coverage improved by {baseline - current} callable(s). Run --update to tighten baseline.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""AST scan: find test functions with no assert/raise/pytest.raises across all test files.

Exit codes
----------
0 — no zero-assert test functions found, or ``--strict`` was not set (report-only mode)
1 — one or more zero-assert test functions found (only when ``--strict`` is set)
2 — script failure (e.g. tests directory not found)

Flags
-----
--strict       exit 1 when zero-assert tests exist (default: exit 0 with report only)
--report-only  always exit 0; only emit the report file / stdout summary (default behaviour)
--tests-dir    override the scanned directory (default: ``<repo_root>/veilbreakers_terrain/tests``)
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Derive repo root from this file's location:  scripts/audits/audit_zero_asserts.py
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_TESTS_DIR = _REPO_ROOT / "veilbreakers_terrain" / "tests"
_REPORT_DIR = _REPO_ROOT / "output" / "verification"


def has_assertion(node: ast.AST) -> bool:
    """Walk the function body looking for assert / Raise / pytest.raises / pytest.fail."""
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            return True
        if isinstance(child, ast.Raise):
            return True
        if isinstance(child, ast.With):
            # pytest.raises(...) context manager
            for item in child.items:
                ce = item.context_expr
                if isinstance(ce, ast.Call):
                    f = ce.func
                    if isinstance(f, ast.Attribute) and f.attr in ("raises", "warns"):
                        return True
                    if isinstance(f, ast.Name) and f.id in ("raises", "warns"):
                        return True
        if isinstance(child, ast.Call):
            f = child.func
            # pytest.fail(...) / pytest.skip(...) / pytest.xfail(...)
            if isinstance(f, ast.Attribute) and f.attr in ("fail", "skip", "xfail", "exit"):
                return True
            if isinstance(f, ast.Name) and f.id in ("fail",):
                return True
            # self.assertX(...) unittest style
            if isinstance(f, ast.Attribute) and f.attr.startswith("assert"):
                return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find test functions with no assertion/raise/pytest.raises.",
    )
    parser.add_argument(
        "--tests-dir",
        type=Path,
        default=_DEFAULT_TESTS_DIR,
        help="Root directory to scan for test_*.py files (default: %(default)s).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Exit 1 when zero-assert tests are found (CI gate mode).",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        default=False,
        help="Always exit 0; only emit the report (equivalent to omitting --strict).",
    )
    args = parser.parse_args()

    tests_dir: Path = args.tests_dir
    if not tests_dir.is_dir():
        print(f"ERROR: tests directory not found: {tests_dir}", file=sys.stderr)
        sys.exit(2)

    zero_assert: list[tuple[str, str, int]] = []
    test_fn_count = 0
    test_file_count = 0
    for path in sorted(tests_dir.rglob("test_*.py")):
        test_file_count += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("test_"):
                    continue
                test_fn_count += 1
                if not has_assertion(node):
                    # as_posix() so the path is forward-slash on Windows too —
                    # otherwise the committed JSON diffs per OS.
                    rel = path.relative_to(tests_dir.parent.parent).as_posix()
                    zero_assert.append((rel, node.name, node.lineno))

    print(f"Total test files scanned: {test_file_count}")
    print(f"Total test functions:     {test_fn_count}")
    print(f"Zero-assert test count:   {len(zero_assert)}")
    print()

    by_file: dict[str, list[tuple[str, int]]] = {}
    if zero_assert:
        for f, name, line in zero_assert:
            by_file.setdefault(f, []).append((name, line))
        print("Zero-assert tests by file:")
        for f in sorted(by_file):
            print(f"  {f}  ({len(by_file[f])} tests)")
            for name, line in by_file[f][:5]:
                print(f"    L{line}: {name}")
            if len(by_file[f]) > 5:
                print(f"    ... +{len(by_file[f]) - 5} more")

    # Emit deterministic JSON report to output/verification/.
    # Three normalisations keep the committed artifact byte-identical across
    # Windows/Linux/CI runners so it does not diff on every machine:
    #   - tests_dir → POSIX path relative to the repo root
    #   - no run timestamp in the payload (would diff every invocation);
    #     the wall-clock time is still printed to stdout for ad-hoc use.
    #   - zero_assert_tests list explicitly sorted by (file, line), and
    #     json.dumps(sort_keys=True) for alphabetical top-level field order,
    #     so output stays stable across Python versions / AST walk changes.
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        tests_dir_rel = tests_dir.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        # tests_dir lives outside the repo (custom --tests-dir); keep as-is.
        tests_dir_rel = str(tests_dir)
    zero_assert_sorted = sorted(zero_assert, key=lambda row: (row[0], row[2], row[1]))
    report = {
        "tests_dir": tests_dir_rel,
        "test_files_scanned": test_file_count,
        "test_functions_total": test_fn_count,
        "zero_assert_count": len(zero_assert_sorted),
        "zero_assert_tests": [
            {"file": f, "function": name, "line": line}
            for f, name, line in zero_assert_sorted
        ],
    }
    print(f"\nRun timestamp: {datetime.now(timezone.utc).isoformat()}")
    report_path = _REPORT_DIR / "audit_zero_asserts.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nReport written to: {report_path}")

    if args.report_only or not args.strict:
        sys.exit(0)
    sys.exit(1 if zero_assert else 0)


if __name__ == "__main__":
    main()

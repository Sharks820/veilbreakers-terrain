"""Static audit of test guardrails, stale patterns, and timing-heavy coverage.

Outputs:
- output/spreadsheet/TEST_GUARDRAIL_AUDIT_2026_04_19.csv
- docs/aaa-audit/TEST_GUARDRAIL_AUDIT_2026_04_19.md
"""

from __future__ import annotations

import ast
import csv
from collections import Counter
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "veilbreakers_terrain" / "tests"
OUTPUT_DIR = REPO_ROOT / "output" / "spreadsheet"
OUTPUT_CSV = OUTPUT_DIR / "TEST_GUARDRAIL_AUDIT_2026_04_19.csv"
OUTPUT_MD = REPO_ROOT / "docs" / "aaa-audit" / "TEST_GUARDRAIL_AUDIT_2026_04_19.md"


class TestGuardrailVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.test_count = 0
        self.skip_calls = 0
        self.xfail_calls = 0
        self.sleep_calls = 0
        self.perf_counter_calls = 0
        self.monkeypatch_tests = 0
        self.command_handlers_refs = 0
        self.dispatch_refs = 0
        self.resolve_command_refs = 0
        self.loc_handlers_refs = 0
        self.approx_calls = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        if node.name.startswith("test_"):
            self.test_count += 1
            if any(arg.arg == "monkeypatch" for arg in node.args.args):
                self.monkeypatch_tests += 1
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        if node.name.startswith("test_"):
            self.test_count += 1
            if any(arg.arg == "monkeypatch" for arg in node.args.args):
                self.monkeypatch_tests += 1
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if node.id == "COMMAND_HANDLERS":
            self.command_handlers_refs += 1
        elif node.id == "dispatch":
            self.dispatch_refs += 1
        elif node.id == "resolve_command":
            self.resolve_command_refs += 1
        elif node.id == "_LOC_HANDLERS":
            self.loc_handlers_refs += 1
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "pytest":
                if node.func.attr == "skip":
                    self.skip_calls += 1
                elif node.func.attr == "xfail":
                    self.xfail_calls += 1
                elif node.func.attr == "approx":
                    self.approx_calls += 1
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "time":
                if node.func.attr == "sleep":
                    self.sleep_calls += 1
                elif node.func.attr == "perf_counter":
                    self.perf_counter_calls += 1
        elif isinstance(node.func, ast.Name):
            if node.func.id == "skip":
                self.skip_calls += 1
            elif node.func.id == "xfail":
                self.xfail_calls += 1
            elif node.func.id == "approx":
                self.approx_calls += 1
        self.generic_visit(node)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def classify_tags(row: dict) -> str:
    tags: list[str] = []
    if int(row["skip_calls"]) > 0 or int(row["xfail_calls"]) > 0:
        tags.append("conditional_or_skip_heavy")
    if int(row["sleep_calls"]) > 0:
        tags.append("sleep_based")
    if int(row["perf_counter_calls"]) > 0:
        tags.append("timing_threshold")
    if int(row["monkeypatch_tests"]) > 0:
        tags.append("patched_smoke")
    if (
        int(row["command_handlers_refs"]) > 0
        or int(row["dispatch_refs"]) > 0
        or int(row["resolve_command_refs"]) > 0
        or int(row["loc_handlers_refs"]) > 0
    ):
        tags.append("dispatch_mapping_heavy")
    if int(row["approx_calls"]) >= max(10, int(row["test_count"]) // 2):
        tags.append("threshold_assert_heavy")
    return ",".join(tags)


def top_rows(rows: Iterable[dict], key: str, limit: int = 10) -> list[dict]:
    return sorted(rows, key=lambda row: (int(row[key]), row["file"]), reverse=True)[:limit]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        visitor = TestGuardrailVisitor()
        visitor.visit(ast.parse(read_text(path), filename=str(path)))
        row = {
            "file": path.relative_to(REPO_ROOT).as_posix(),
            "test_count": str(visitor.test_count),
            "skip_calls": str(visitor.skip_calls),
            "xfail_calls": str(visitor.xfail_calls),
            "sleep_calls": str(visitor.sleep_calls),
            "perf_counter_calls": str(visitor.perf_counter_calls),
            "monkeypatch_tests": str(visitor.monkeypatch_tests),
            "command_handlers_refs": str(visitor.command_handlers_refs),
            "dispatch_refs": str(visitor.dispatch_refs),
            "resolve_command_refs": str(visitor.resolve_command_refs),
            "loc_handlers_refs": str(visitor.loc_handlers_refs),
            "approx_calls": str(visitor.approx_calls),
        }
        row["guardrail_tags"] = classify_tags(row)
        rows.append(row)

    fieldnames = [
        "file",
        "test_count",
        "skip_calls",
        "xfail_calls",
        "sleep_calls",
        "perf_counter_calls",
        "monkeypatch_tests",
        "command_handlers_refs",
        "dispatch_refs",
        "resolve_command_refs",
        "loc_handlers_refs",
        "approx_calls",
        "guardrail_tags",
    ]
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    tag_counter = Counter()
    for row in rows:
        for tag in filter(None, row["guardrail_tags"].split(",")):
            tag_counter[tag] += 1

    lines = [
        "# Test Guardrail Audit",
        "",
        "Audit date: 2026-04-19",
        "",
        "## Totals",
        "",
        f"- Test files scanned: `{len(rows)}`",
        f"- Static test functions discovered: `{sum(int(row['test_count']) for row in rows)}`",
        f"- Files with skip/xfail patterns: `{tag_counter['conditional_or_skip_heavy']}`",
        f"- Files with timing thresholds: `{tag_counter['timing_threshold']}`",
        f"- Files with sleep-based assertions: `{tag_counter['sleep_based']}`",
        f"- Files heavy on dispatch/registration mapping: `{tag_counter['dispatch_mapping_heavy']}`",
        f"- Files with monkeypatch-driven smoke paths: `{tag_counter['patched_smoke']}`",
        "",
        "## Highest Skip / Conditional Files",
        "",
    ]
    for row in top_rows(rows, "skip_calls"):
        if int(row["skip_calls"]) <= 0 and int(row["xfail_calls"]) <= 0:
            continue
        lines.append(
            f"- `{row['file']}`: tests=`{row['test_count']}`, skip=`{row['skip_calls']}`, xfail=`{row['xfail_calls']}`"
        )
    lines.extend(["", "## Highest Timing / Slow-Risk Files", ""])
    for row in top_rows(rows, "perf_counter_calls"):
        if int(row["perf_counter_calls"]) <= 0 and int(row["sleep_calls"]) <= 0:
            continue
        lines.append(
            f"- `{row['file']}`: perf_counter=`{row['perf_counter_calls']}`, sleep=`{row['sleep_calls']}`, tags=`{row['guardrail_tags'] or 'none'}`"
        )
    lines.extend(["", "## Highest Dispatch / Mapping Files", ""])
    for row in sorted(
        rows,
        key=lambda item: (
            int(item["command_handlers_refs"])
            + int(item["dispatch_refs"])
            + int(item["resolve_command_refs"])
            + int(item["loc_handlers_refs"]),
            item["file"],
        ),
        reverse=True,
    )[:10]:
        mapping_refs = (
            int(row["command_handlers_refs"])
            + int(row["dispatch_refs"])
            + int(row["resolve_command_refs"])
            + int(row["loc_handlers_refs"])
        )
        if mapping_refs <= 0:
            continue
        lines.append(
            f"- `{row['file']}`: mapping_refs=`{mapping_refs}`, tests=`{row['test_count']}`, tags=`{row['guardrail_tags'] or 'none'}`"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `conditional_or_skip_heavy`: test outcomes depend on generated terrain content or optional runtime state; useful, but coverage can silently disappear.",
            "- `timing_threshold`: tests assert elapsed time directly; they are useful only when the threshold matches current performance budgets.",
            "- `sleep_based`: tests enforce concurrency using wall-clock sleeps; strong signal for behavior, but inefficient and brittle.",
            "- `dispatch_mapping_heavy`: tests mostly protect exposure and naming stability rather than deep behavior.",
            "- `patched_smoke`: tests intentionally stub heavy code paths to keep wiring coverage fast; they should not be mistaken for full semantic verification.",
        ]
    )
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

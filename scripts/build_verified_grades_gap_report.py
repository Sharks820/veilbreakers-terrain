"""Build a deterministic callable-to-grade coverage audit for grade CSV sheets.

Why this exists:
- `coverage_gap_analysis.py` key-collides on repeated function names across files.
- It skips handlers/__init__.py runtime bridge callables.
- It does not separate *ungraded* from *stale* rows with enough detail.

Outputs:
- output/spreadsheet/GRADES_GAP_AUDIT_<grade_stem>_<YYYY_MM_DD>.csv
- output/spreadsheet/GRADES_GAP_SUMMARY_<grade_stem>_<YYYY_MM_DD>.md
"""

from __future__ import annotations

import ast
import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
HANDLERS_DIR = REPO_ROOT / "veilbreakers_terrain" / "handlers"
DEFAULT_GRADES_CSV = REPO_ROOT / "docs" / "aaa-audit" / "GRADES.csv"
OUT_DIR = REPO_ROOT / "output" / "spreadsheet"
DATE_TAG = datetime.now(timezone.utc).strftime("%Y_%m_%d")


@dataclass(frozen=True)
class CallableDef:
    file: str
    qualified_name: str
    simple_name: str
    lineno: int
    kind: str


class CallableVisitor(ast.NodeVisitor):
    def __init__(self, file_name: str) -> None:
        self.file_name = file_name
        self.class_stack: List[str] = []
        self.rows: List[CallableDef] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._record(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._record(node)
        self.generic_visit(node)

    def _record(self, node: ast.AST) -> None:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        if node.name.startswith("__") and node.name.endswith("__"):
            return
        container = self.class_stack[-1] if self.class_stack else ""
        qualified = f"{container}.{node.name}" if container else node.name
        kind = "method" if container else "function"
        self.rows.append(
            CallableDef(
                file=self.file_name,
                qualified_name=qualified,
                simple_name=node.name,
                lineno=node.lineno,
                kind=kind,
            )
        )


def collect_callables() -> List[CallableDef]:
    callables: List[CallableDef] = []
    for py in sorted(HANDLERS_DIR.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"), filename=str(py))
        visitor = CallableVisitor(py.name)
        visitor.visit(tree)
        callables.extend(visitor.rows)
    return callables


def collect_classes() -> Dict[str, set[str]]:
    classes_by_file: Dict[str, set[str]] = defaultdict(set)
    for py in sorted(HANDLERS_DIR.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes_by_file[py.name].add(node.name)
    return classes_by_file


def read_grade_rows(grades_csv: Path) -> List[dict]:
    with grades_csv.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _norm(v: str) -> str:
    return (v or "").strip()


def map_grades(rows: Iterable[dict]) -> Tuple[Dict[Tuple[str, str], dict], Dict[str, List[dict]]]:
    by_exact: Dict[Tuple[str, str], dict] = {}
    by_name: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        file_name = _norm(row.get("File", ""))
        fn = _norm(row.get("Function", ""))
        if not file_name or not fn:
            continue
        by_exact[(file_name, fn)] = row
        by_name[fn].append(row)
    return by_exact, by_name


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--grade-file",
        type=Path,
        default=DEFAULT_GRADES_CSV,
        help=(
            "Path to grade CSV source. Defaults to docs/aaa-audit/GRADES.csv "
            "(the original baseline sheet)."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    grades_csv = args.grade_file
    if not grades_csv.is_absolute():
        grades_csv = (REPO_ROOT / grades_csv).resolve()
    if not grades_csv.exists():
        raise FileNotFoundError(f"Grade CSV not found: {grades_csv}")

    grade_stem = grades_csv.stem.upper()
    out_csv = OUT_DIR / f"GRADES_GAP_AUDIT_{grade_stem}_{DATE_TAG}.csv"
    out_md = OUT_DIR / f"GRADES_GAP_SUMMARY_{grade_stem}_{DATE_TAG}.md"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    callables = collect_callables()
    classes_by_file = collect_classes()
    grade_rows = read_grade_rows(grades_csv)
    grades_exact, grades_by_name = map_grades(grade_rows)

    audit_rows: List[dict] = []
    stale_rows: List[dict] = []
    stale_class_rows: List[dict] = []

    callable_keys = {(c.file, c.simple_name) for c in callables}

    for c in sorted(callables, key=lambda x: (x.file, x.lineno, x.qualified_name)):
        status = "MISSING"
        matched = None

        if (c.file, c.simple_name) in grades_exact:
            matched = grades_exact[(c.file, c.simple_name)]
            status = "GRADED"
        else:
            same_name_rows = grades_by_name.get(c.simple_name, [])
            if len(same_name_rows) == 1:
                matched = same_name_rows[0]
                status = "NAME_ONLY_MATCH"
            elif len(same_name_rows) > 1:
                status = "AMBIGUOUS_NAME_MATCH"

        final_grade = _norm((matched or {}).get("FINAL GRADE", ""))
        r9 = _norm((matched or {}).get("R9 Phase7-14 Consensus", ""))

        audit_rows.append(
            {
                "file": c.file,
                "line": c.lineno,
                "kind": c.kind,
                "callable": c.qualified_name,
                "simple_name": c.simple_name,
                "grade_match_status": status,
                "final_grade": final_grade,
                "r9_consensus": r9,
                "aaa_equivalent": _norm((matched or {}).get("AAA Equivalent", "")),
                "weakness": _norm((matched or {}).get("Weakness", "")),
                "upgrade": _norm((matched or {}).get("Upgrade", "")),
            }
        )

    for row in grade_rows:
        file_name = _norm(row.get("File", ""))
        fn = _norm(row.get("Function", ""))
        if file_name and fn and (file_name, fn) not in callable_keys:
            if fn in classes_by_file.get(file_name, set()):
                stale_class_rows.append(row)
            else:
                stale_rows.append(row)

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(audit_rows[0].keys()))
        writer.writeheader()
        writer.writerows(audit_rows)

    coverage = Counter(r["grade_match_status"] for r in audit_rows)
    grade_dist = Counter(r["final_grade"] or "(blank)" for r in audit_rows)
    top_missing = Counter(r["file"] for r in audit_rows if r["grade_match_status"] != "GRADED")

    lines = [
        "# GRADES Verified Gap Summary",
        "",
        f"- Grade source CSV: `{grades_csv.relative_to(REPO_ROOT)}`",
        f"- UTC date tag: `{DATE_TAG}`",
        f"- Total handler callables: **{len(audit_rows)}**",
        f"- Exact graded callables: **{coverage['GRADED']}**",
        f"- Name-only matches (needs explicit file-level row): **{coverage['NAME_ONLY_MATCH']}**",
        f"- Ambiguous name matches (manual disambiguation required): **{coverage['AMBIGUOUS_NAME_MATCH']}**",
        f"- Missing callable grades: **{coverage['MISSING']}**",
        f"- Stale grade rows (in CSV but no longer in code): **{len(stale_rows)}**",
        f"- Class rows in CSV (tracked but non-callable by this audit): **{len(stale_class_rows)}**",
        "",
        "## Final grade distribution (exact+heuristic matches)",
        "",
    ]

    for grade, count in sorted(grade_dist.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- {grade}: {count}")

    lines.extend([
        "",
        "## Files with most non-exact coverage",
        "",
    ])
    for file, count in top_missing.most_common(20):
        lines.append(f"- {file}: {count}")

    if stale_rows:
        lines.extend(["", "## Top stale grade rows", ""])
        for row in stale_rows[:20]:
            lines.append(f"- {row.get('File','').strip()}::{row.get('Function','').strip()}")

    if stale_class_rows:
        lines.extend(["", "## CSV class rows (not counted as callables)", ""])
        for row in stale_class_rows[:20]:
            lines.append(f"- {row.get('File','').strip()}::{row.get('Function','').strip()}")

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"wrote {out_csv}")
    print(f"wrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

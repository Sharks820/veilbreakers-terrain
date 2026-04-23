"""Build a deterministic callable-to-grade coverage audit for grade CSV sheets."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from grade_audit_shared import (
    DEFAULT_GRADE_FILE,
    REPO_ROOT,
    build_grade_index,
    collect_callables,
    collect_classes,
    latest_grade,
    norm,
    read_grade_rows,
    resolve_grade_match,
)


OUT_DIR = REPO_ROOT / "output" / "spreadsheet"
DATE_TAG = datetime.now(timezone.utc).strftime("%Y_%m_%d")
AUDIT_FIELDNAMES = [
    "file",
    "line",
    "kind",
    "callable",
    "simple_name",
    "grade_match_status",
    "match_mode",
    "current_grade",
    "r9_consensus",
    "final_grade",
    "aaa_equivalent",
    "weakness",
    "upgrade",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--grade-file",
        type=Path,
        default=DEFAULT_GRADE_FILE,
        help="Path to the grade CSV source. Defaults to docs/aaa-audit/GRADES_VERIFIED.csv.",
    )
    return parser.parse_args()


def _relative_grade_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


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

    callables = collect_callables(include_init=True)
    classes_by_file = collect_classes(include_init=True)
    grade_rows = read_grade_rows(grades_csv)
    grade_index = build_grade_index(grade_rows)

    live_qualified = {(c.file, c.qualified_name) for c in callables}
    live_simple = {(c.file, c.simple_name) for c in callables}

    audit_rows: List[dict] = []
    stale_rows: List[dict] = []
    stale_class_rows: List[dict] = []

    for callable_def in sorted(callables, key=lambda item: (item.file, item.lineno, item.qualified_name)):
        match = resolve_grade_match(callable_def, grade_index)
        matched_row = match.row or {}
        audit_rows.append(
            {
                "file": callable_def.file,
                "line": callable_def.lineno,
                "kind": callable_def.kind,
                "callable": callable_def.qualified_name,
                "simple_name": callable_def.simple_name,
                "grade_match_status": match.status,
                "match_mode": match.match_mode,
                "current_grade": latest_grade(matched_row),
                "r9_consensus": norm(matched_row.get("R9 Phase7-14 Consensus", "")),
                "final_grade": norm(matched_row.get("FINAL GRADE", "")),
                "aaa_equivalent": norm(matched_row.get("AAA Equivalent", "")),
                "weakness": norm(matched_row.get("Weakness", "")),
                "upgrade": norm(matched_row.get("Upgrade", "")),
            }
        )

    for row in grade_rows:
        file_name = norm(row.get("File", ""))
        function_name = norm(row.get("Function", ""))
        if not file_name or not function_name:
            continue
        if (file_name, function_name) in live_qualified or (file_name, function_name) in live_simple:
            continue
        if function_name in classes_by_file.get(file_name, set()):
            stale_class_rows.append(row)
        else:
            stale_rows.append(row)

    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=AUDIT_FIELDNAMES)
        writer.writeheader()
        writer.writerows(audit_rows)

    coverage = Counter(row["grade_match_status"] for row in audit_rows)
    grade_dist = Counter(
        row["current_grade"] or "(blank)"
        for row in audit_rows
        if row["grade_match_status"] in {"GRADED", "NAME_ONLY_MATCH"}
    )
    top_non_exact = Counter(
        row["file"] for row in audit_rows if row["grade_match_status"] != "GRADED"
    )

    lines = [
        f"# {grade_stem} Gap Summary",
        "",
        f"- Grade source CSV: `{_relative_grade_path(grades_csv)}`",
        f"- UTC date tag: `{DATE_TAG}`",
        f"- Total handler callables: **{len(audit_rows)}**",
        f"- Exact graded callables: **{coverage['GRADED']}**",
        f"- Name-only matches (needs explicit file-level row): **{coverage['NAME_ONLY_MATCH']}**",
        f"- Ambiguous same-file grade rows: **{coverage['AMBIGUOUS_FILE_MATCH']}**",
        f"- Ambiguous name matches (manual disambiguation required): **{coverage['AMBIGUOUS_NAME_MATCH']}**",
        f"- Missing callable grades: **{coverage['MISSING']}**",
        f"- Stale grade rows (in CSV but no longer in code): **{len(stale_rows)}**",
        f"- Class rows in CSV (tracked but non-callable by this audit): **{len(stale_class_rows)}**",
        "",
        "## Current grade distribution (matched rows only)",
        "",
    ]

    for grade, count in sorted(grade_dist.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {grade}: {count}")

    lines.extend(
        [
            "",
            "## Files with most non-exact coverage",
            "",
        ]
    )
    for file_name, count in top_non_exact.most_common(20):
        lines.append(f"- {file_name}: {count}")

    if stale_rows:
        lines.extend(["", "## Top stale grade rows", ""])
        for row in stale_rows[:20]:
            lines.append(f"- {norm(row.get('File', ''))}::{norm(row.get('Function', ''))}")

    if stale_class_rows:
        lines.extend(["", "## CSV class rows (not counted as callables)", ""])
        for row in stale_class_rows[:20]:
            lines.append(f"- {norm(row.get('File', ''))}::{norm(row.get('Function', ''))}")

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"wrote {out_csv}")
    print(f"wrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""One-shot updater: adds R10 Opus-Wave10 Grade + R10 Opus-Wave10 Notes columns
to docs/aaa-audit/GRADES_VERIFIED.csv from WAVE10_CALLABLE_GRADES_2026_04_27.json.

For graded callables that already exist (match on file basename + function),
fills the new columns. For new callables, appends new rows.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "docs" / "aaa-audit" / "GRADES_VERIFIED.csv"
JSON_PATH = ROOT / "docs" / "aaa-audit" / "WAVE10_CALLABLE_GRADES_2026_04_27.json"


def main() -> int:
    findings = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    # Index findings by (basename, function)
    by_key: dict[tuple[str, str], dict] = {}
    for f in findings:
        bn = Path(f["file"]).name
        by_key[(bn, f["function"])] = f

    # Read CSV
    with CSV_PATH.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        rows = list(reader)

    header = rows[0]
    # Add new columns if not present
    new_cols = ["R10 Opus-Wave10 Grade", "R10 Opus-Wave10 Notes"]
    cols_added = []
    for col in new_cols:
        if col not in header:
            header.append(col)
            cols_added.append(col)

    # Pad existing data rows to match new header width
    width = len(header)
    for r in rows[1:]:
        while len(r) < width:
            r.append("")

    # Find column indices
    idx_file = header.index("File")
    idx_func = header.index("Function")
    idx_grade = header.index("R10 Opus-Wave10 Grade")
    idx_notes = header.index("R10 Opus-Wave10 Notes")

    # Update existing rows; track which keys we've covered
    covered: set[tuple[str, str]] = set()
    updated = 0
    for r in rows[1:]:
        if len(r) < 3:
            continue
        bn = (r[idx_file] or "").strip()
        fn = (r[idx_func] or "").strip()
        key = (bn, fn)
        if key in by_key:
            f = by_key[key]
            note = (
                f"grade={f['grade']}; severity={f['severity']}; "
                f"strength={f['strength'][:120]}; "
                f"weakness={f['weakness'][:140]}; "
                f"upgrade={f['upgrade'][:120]}"
            ).replace("\n", " ").replace("\r", " ")
            r[idx_grade] = f["grade"]
            r[idx_notes] = note
            covered.add(key)
            updated += 1

    # Find max # to continue numbering
    max_num = 0
    for r in rows[1:]:
        try:
            n = int(r[0])
            if n > max_num:
                max_num = n
        except (ValueError, IndexError):
            pass

    # Append new rows for findings not in CSV
    appended = 0
    for key, f in by_key.items():
        if key in covered:
            continue
        max_num += 1
        bn = Path(f["file"]).name
        new_row = [""] * width
        new_row[0] = str(max_num)
        new_row[idx_file] = bn
        new_row[idx_func] = f["function"]
        # Line column
        if "Line" in header:
            new_row[header.index("Line")] = str(f["line"])
        new_row[idx_grade] = f["grade"]
        note = (
            f"grade={f['grade']}; severity={f['severity']}; "
            f"strength={f['strength'][:120]}; "
            f"weakness={f['weakness'][:140]}; "
            f"upgrade={f['upgrade'][:120]}"
        ).replace("\n", " ").replace("\r", " ")
        new_row[idx_notes] = note
        # Set FINAL GRADE if blank too
        if "FINAL GRADE" in header:
            new_row[header.index("FINAL GRADE")] = f["grade"]
        rows.append(new_row)
        appended += 1

    # Write back
    with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
        writer.writerows(rows)

    print(f"Cols added: {cols_added}")
    print(f"Rows updated: {updated}")
    print(f"Rows appended: {appended}")
    print(f"Total findings: {len(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

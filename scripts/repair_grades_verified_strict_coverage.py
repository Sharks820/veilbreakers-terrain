"""Repair GRADES_VERIFIED.csv so live callable coverage is explicit.

This is a mechanical ledger repair, not an upgrade claim. It removes stale
non-callable rows from the active grade CSV and adds explicit low-grade blocker
rows for live callables that are missing, ambiguous, or matched only by global
simple-name fallback.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

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


def _row_number(row: dict[str, str]) -> int:
    raw = norm(row.get("#", ""))
    try:
        return int(raw)
    except ValueError:
        return 0


def _build_backfill_row(
    fieldnames: list[str],
    *,
    row_number: int,
    file_name: str,
    function_name: str,
    line: int,
    match_status: str,
) -> dict[str, str]:
    row = {field: "" for field in fieldnames}
    row["#"] = str(row_number)
    row["File"] = file_name
    row["Function"] = function_name
    row["Line"] = str(line)
    row["FINAL GRADE"] = "D+"
    row["Dispute Reason"] = "R14 strict callable ledger backfill; not an AAA quality approval."
    row["Evidence"] = (
        "Live callable exists but lacked exact grade coverage or had ambiguous coverage "
        f"({match_status}). Added so strict gates can track it explicitly."
    )
    row["AAA Equivalent"] = "No"
    row["Strength"] = "Callable is live in handler AST and now has explicit ledger coverage."
    row["Weakness"] = "Missing direct behavior proof, visual proof, and AAA acceptance evidence."
    row["Upgrade"] = "Add direct behavior tests, shipped-surface wiring proof, visual/live artifact proof, and regrade only after evidence passes."
    row["Severity"] = "BLOCKER"
    row["R9 Phase7-14 Consensus"] = "D+"
    row["R10 GPT-5.5 AAA Regrade"] = "D+"
    row["R10 Verification Status"] = "BLOCKER_REVIEW_REQUIRED"
    row["R10 Notes"] = (
        "R14 backfill row: explicit coverage only. Do not treat as quality pass "
        "or production readiness."
    )
    return row


def _mark_blocker_grade(row: dict[str, str], *, reason: str) -> None:
    row["FINAL GRADE"] = "D+"
    row["R9 Phase7-14 Consensus"] = "D+"
    row["AAA Equivalent"] = "No"
    row["Severity"] = "BLOCKER"
    row["R10 GPT-5.5 AAA Regrade"] = "D+"
    row["R10 Verification Status"] = "BLOCKER_REVIEW_REQUIRED"
    existing = norm(row.get("R10 Notes", ""))
    note = f"R14 strict ledger repair: {reason}. Not a quality pass."
    row["R10 Notes"] = f"{existing} | {note}" if existing else note


def repair() -> tuple[int, int, Path]:
    grade_path = DEFAULT_GRADE_FILE
    with grade_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        original_rows = list(reader)

    callables = collect_callables(include_init=True)
    live_qualified = {(c.file, c.qualified_name) for c in callables}
    live_simple = {(c.file, c.simple_name) for c in callables}
    classes_by_file = collect_classes(include_init=True)

    kept_rows: list[dict[str, str]] = []
    removed_rows: list[dict[str, str]] = []
    for row in original_rows:
        file_name = norm(row.get("File", ""))
        function_name = norm(row.get("Function", ""))
        if not file_name or not function_name:
            kept_rows.append(row)
            continue
        if (file_name, function_name) in live_qualified or (file_name, function_name) in live_simple:
            if not latest_grade(row):
                _mark_blocker_grade(row, reason="live callable row had no accepted grade token")
            kept_rows.append(row)
            continue
        if function_name in classes_by_file.get(file_name, set()):
            kept_rows.append(row)
            continue
        removed_rows.append(row)

    grade_index = build_grade_index(kept_rows)
    next_number = max((_row_number(row) for row in kept_rows), default=0) + 1
    added_rows: list[dict[str, str]] = []
    for callable_def in sorted(callables, key=lambda item: (item.file, item.lineno, item.qualified_name)):
        match = resolve_grade_match(callable_def, grade_index)
        if match.status == "GRADED":
            continue
        row = _build_backfill_row(
            fieldnames,
            row_number=next_number,
            file_name=callable_def.file,
            function_name=callable_def.qualified_name,
            line=callable_def.lineno,
            match_status=match.status,
        )
        kept_rows.append(row)
        added_rows.append(row)
        grade_index = build_grade_index(kept_rows)
        next_number += 1

    for index, row in enumerate(kept_rows, start=1):
        row["#"] = str(index)

    timestamp = datetime.now(timezone.utc).strftime("%Y_%m_%d_%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    removed_path = OUT_DIR / f"GRADES_VERIFIED_STALE_ROWS_REMOVED_{timestamp}.csv"
    with removed_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(removed_rows)

    with grade_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept_rows)

    return len(removed_rows), len(added_rows), removed_path


def main() -> int:
    removed, added, removed_path = repair()
    print(f"removed stale rows: {removed}")
    print(f"added explicit blocker rows: {added}")
    print(f"stale row archive: {removed_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

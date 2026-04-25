"""Split R12 strict below-B rows into manual review batches."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "aaa-audit" / "R12_STRICT_BELOW_B_ACTION_PLAN.csv"
OUT_DIR = ROOT / "docs" / "aaa-audit" / "manual_review_batches"
MAX_ROWS = 250


def batch_key(row: dict[str, str]) -> str:
    file_path = row["File"]
    domain = row["R12 Domain"]
    if domain != "generic":
        return domain
    if file_path.startswith("scripts/"):
        return "generic_script"
    if "/handlers/" in file_path:
        return "generic_runtime_handler"
    return "generic_other"


def main() -> None:
    rows = list(csv.DictReader(SOURCE.open(encoding="utf-8")))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[batch_key(row)].append(row)

    fieldnames = list(rows[0].keys()) if rows else []
    manifest: list[dict[str, str]] = []
    for group, group_rows in sorted(groups.items()):
        for index in range(0, len(group_rows), MAX_ROWS):
            chunk = group_rows[index:index + MAX_ROWS]
            batch_name = f"R13_batch_{group}_{index // MAX_ROWS + 1:02d}.csv"
            batch_path = OUT_DIR / batch_name
            with batch_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(chunk)
            manifest.append({
                "batch": batch_name,
                "group": group,
                "rows": str(len(chunk)),
            })

    with (OUT_DIR / "MANIFEST.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["batch", "group", "rows"])
        writer.writeheader()
        writer.writerows(manifest)

    print(f"R13 manual review batches: {len(manifest)}")
    for item in manifest:
        print(f"{item['batch']}: {item['rows']}")


if __name__ == "__main__":
    main()

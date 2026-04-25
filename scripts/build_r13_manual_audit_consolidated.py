"""Consolidate R13 row-level manual review artifacts."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_CSV = ROOT / "docs" / "aaa-audit" / "R13_FULL_MANUAL_CALLABLE_REVIEW.csv"
STRICT_OUT_CSV = ROOT / "docs" / "aaa-audit" / "R13_FULL_MANUAL_CALLABLE_REVIEW_STRICT_OUTPUT_GATE.csv"
OUT_MD = ROOT / "docs" / "aaa-audit" / "R13_FULL_MANUAL_CALLABLE_REVIEW_SUMMARY.md"

SOURCES = [
    (
        "local_generic_script_other",
        ROOT / "docs" / "aaa-audit" / "R13_LOCAL_MANUAL_REVIEW_GENERIC_SCRIPT_OTHER.csv",
    ),
    (
        "generic_runtime_handler_01_02",
        ROOT / "docs" / "aaa-audit" / "manual_review_batches" / "R13_manual_review_generic_runtime_handler_01_02_row_level.csv",
    ),
    (
        "generic_runtime_handler_03_04",
        ROOT / "docs" / "aaa-audit" / "manual_review_batches" / "R13_manual_review_generic_runtime_handler_03_04_completed.csv",
    ),
    (
        "validation_tooling_lod",
        ROOT / "docs" / "aaa-audit" / "manual_review_batches" / "R13_manual_audit_review_rows_validation_tooling_lod.csv",
    ),
    (
        "water_roads_paths",
        ROOT / "docs" / "aaa-audit" / "manual_review_batches" / "R13_manual_review_water_roads_paths_completed.csv",
    ),
    (
        "terrain_shape_cliffs",
        ROOT / "docs" / "aaa-audit" / "manual_review_batches" / "R13_manual_review_terrain_shape_cliffs_completed.csv",
    ),
    (
        "scatter_biome_materials",
        ROOT / "docs" / "aaa-audit" / "manual_review_batches" / "R13_manual_review_scatter_biome_materials_completed.csv",
    ),
]

FIELDNAMES = [
    "Review Source",
    "File",
    "Qualified Name",
    "Current R12 Grade",
    "Manual Grade",
    "Action",
    "Evidence Summary",
    "Best Practice Gap",
    "Output Proof Present",
    "Strict AAA Output Grade",
    "Strict AAA Output Gate",
]

VISUAL_TERRAIN_B_PRODUCERS = {
    ("veilbreakers_terrain/handlers/environment.py", "handle_generate_terrain"),
    ("veilbreakers_terrain/handlers/environment.py", "handle_generate_terrain_tile"),
    ("veilbreakers_terrain/handlers/environment.py", "handle_create_cave_entrance"),
    ("veilbreakers_terrain/handlers/terrain_audio_zones.py", "pass_audio_zones"),
    ("veilbreakers_terrain/handlers/terrain_caves.py", "pass_caves"),
    ("veilbreakers_terrain/handlers/terrain_caves.py", "handle_generate_cave"),
    ("veilbreakers_terrain/handlers/terrain_cliffs.py", "pass_cliffs"),
    ("veilbreakers_terrain/handlers/terrain_cloud_shadow.py", "pass_cloud_shadow"),
    ("veilbreakers_terrain/handlers/terrain_decal_placement.py", "pass_decals"),
    ("veilbreakers_terrain/handlers/terrain_fog_masks.py", "pass_fog_masks"),
    ("veilbreakers_terrain/handlers/terrain_framing.py", "pass_framing"),
    ("veilbreakers_terrain/handlers/terrain_gameplay_zones.py", "pass_gameplay_zones"),
    ("veilbreakers_terrain/handlers/terrain_god_ray_hints.py", "pass_god_ray_hints"),
}


def pick(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name, "")
        if value:
            return value
    return ""


def infer_output_proof(row: dict[str, str]) -> str:
    explicit = pick(row, "Output Proof Present")
    if explicit:
        return explicit
    text = " ".join([
        pick(row, "Evidence Summary", "R13 Evidence"),
        pick(row, "Best Practice Gap", "R13 Best Practice Gap"),
        pick(row, "Action", "R13 Manual Action"),
    ]).lower()
    if "proof=n" in text or "live visual" in text or "golden" in text:
        return "No"
    return "No"


def strict_output_gate(row: dict[str, str]) -> tuple[str, str]:
    grade = row["Manual Grade"]
    if grade != "B":
        return grade, "BELOW_B_REMEDIATION_REQUIRED"
    key = (row["File"], row["Qualified Name"])
    if key in VISUAL_TERRAIN_B_PRODUCERS:
        return "C+", "LIVE_VISUAL_ENGINE_OUTPUT_PROOF_REQUIRED"
    return grade, "PASSED_NONVISUAL_OR_CONTRACT_OUTPUT_GATE"


def normalize_row(source: str, row: dict[str, str]) -> dict[str, str]:
    normalized = {
        "Review Source": source,
        "File": pick(row, "File"),
        "Qualified Name": pick(row, "Qualified Name"),
        "Current R12 Grade": pick(row, "Current R12 Grade", "R12 Strict Grade"),
        "Manual Grade": pick(row, "Manual Grade", "R13 Manual Grade"),
        "Action": pick(row, "Action", "R13 Manual Action"),
        "Evidence Summary": pick(row, "Evidence Summary", "R13 Evidence"),
        "Best Practice Gap": pick(row, "Best Practice Gap", "R13 Best Practice Gap"),
        "Output Proof Present": infer_output_proof(row),
    }
    strict_grade, strict_gate = strict_output_gate(normalized)
    normalized["Strict AAA Output Grade"] = strict_grade
    normalized["Strict AAA Output Gate"] = strict_gate
    return normalized


def main() -> None:
    rows: list[dict[str, str]] = []
    source_counts: Counter[str] = Counter()
    for source, path in SOURCES:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                normalized = normalize_row(source, row)
                if not normalized["File"] or not normalized["Qualified Name"]:
                    raise ValueError(f"Bad row in {path}: {row}")
                rows.append(normalized)
                source_counts[source] += 1

    key_counts = Counter((row["File"], row["Qualified Name"]) for row in rows)
    duplicates = [key for key, count in key_counts.items() if count > 1]
    if duplicates:
        raise ValueError(f"Duplicate reviewed rows found: {duplicates[:10]}")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    with STRICT_OUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    grade_counts = Counter(row["Manual Grade"] for row in rows)
    strict_grade_counts = Counter(row["Strict AAA Output Grade"] for row in rows)
    strict_gate_counts = Counter(row["Strict AAA Output Gate"] for row in rows)
    action_counts = Counter(row["Action"] for row in rows)
    output_counts = Counter(row["Output Proof Present"] for row in rows)
    b_rows = [row for row in rows if row["Manual Grade"] == "B"]
    strict_b_rows = [row for row in rows if row["Strict AAA Output Grade"] == "B"]
    visual_gate_rows = [
        row for row in rows
        if row["Strict AAA Output Gate"] == "LIVE_VISUAL_ENGINE_OUTPUT_PROOF_REQUIRED"
    ]
    b_without_output = [row for row in b_rows if row["Output Proof Present"].lower() != "yes"]

    lines = [
        "# R13 Full Manual Callable Review Summary",
        "",
        "This consolidates the row-level R13 manual review for every non-test below-B row from R12.",
        "A B grade is not accepted for visual/terrain-producing callables without output proof.",
        "",
        f"- Total rows reviewed: {len(rows)}",
        f"- Duplicate row keys: {len(duplicates)}",
        f"- B rows: {len(b_rows)}",
        f"- Strict AAA output-gated B rows: {len(strict_b_rows)}",
        f"- Visual/terrain rows downgraded from B until live proof exists: {len(visual_gate_rows)}",
        f"- B rows missing output proof: {len(b_without_output)}",
        "",
        "## Rows By Review Source",
    ]
    for source, count in source_counts.items():
        lines.append(f"- {source}: {count}")
    lines.extend(["", "## Manual Grades"])
    for grade, count in sorted(grade_counts.items()):
        lines.append(f"- {grade}: {count}")
    lines.extend(["", "## Strict AAA Output Grades"])
    for grade, count in sorted(strict_grade_counts.items()):
        lines.append(f"- {grade}: {count}")
    lines.extend(["", "## Strict Output Gates"])
    for gate, count in strict_gate_counts.most_common():
        lines.append(f"- {gate}: {count}")
    lines.extend(["", "## Output Proof"])
    for proof, count in sorted(output_counts.items()):
        lines.append(f"- {proof}: {count}")
    lines.extend(["", "## Actions"])
    for action, count in action_counts.most_common():
        lines.append(f"- {action}: {count}")
    lines.extend([
        "",
        "## Strict Interpretation",
        "",
        "Most rows remain below B because they lack direct production-output proof. "
        "For water, roads, cliffs, scatter, terrain shape, materials, validation, and LOD/export, "
        "the recurring blocker is not just wiring; it is missing live generated artifacts, "
        "render/engine evidence, seam checks, and visual golden validation tied to the callable's claim.",
    ])
    if strict_b_rows:
        lines.extend(["", "## Strict B Rows"])
        for row in strict_b_rows:
            lines.append(
                f"- {row['File']}::{row['Qualified Name']} "
                f"(output_proof={row['Output Proof Present']})"
            )
    if visual_gate_rows:
        lines.extend(["", "## Downgraded Until Live Visual/Engine Proof"])
        for row in visual_gate_rows:
            lines.append(
                f"- {row['File']}::{row['Qualified Name']} "
                f"(manual={row['Manual Grade']}, strict={row['Strict AAA Output Grade']})"
            )

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_CSV.relative_to(ROOT)} ({len(rows)} rows)")
    print(f"wrote {STRICT_OUT_CSV.relative_to(ROOT)}")
    print(f"wrote {OUT_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

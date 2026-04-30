"""Build a file-level audit of test guardrails, staleness, and wiring quality."""

from __future__ import annotations

import csv
import argparse
import subprocess
from collections import Counter
from pathlib import Path
from typing import Dict


REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "veilbreakers_terrain" / "tests"
OUTPUT_DIR = REPO_ROOT / "output" / "spreadsheet"
DATE_TAG = "2026_04_19"
OUTPUT_CSV = OUTPUT_DIR / f"TEST_GUARDRAIL_AUDIT_{DATE_TAG}.csv"
OUTPUT_MD = OUTPUT_DIR / f"TEST_GUARDRAIL_SUMMARY_{DATE_TAG}.md"


PATTERNS = {
    "legacy_alias": ("blender_addon.handlers",),
    "mock_heavy": ("MagicMock", "Mock(", "patch(", "monkeypatch"),
    "source_introspection": (".read_text(", "open(", "inspect.getsource"),
    "registry_surface": ("COMMAND_HANDLERS",),
    "skip_or_xfail": ("pytest.skip", "@pytest.mark.skip", "@pytest.mark.xfail"),
    "run_pass": (".run_pass(",),
    "command_handlers_exec": ("COMMAND_HANDLERS[",),
    "validate_tile_seams": ("validate_tile_seams(",),
}


MANUAL_NOTES: Dict[str, Dict[str, str]] = {
    "veilbreakers_terrain/tests/contract/test_terrain_contracts.py": {
        "label": "structure_only",
        "priority": "P1",
        "notes": "Good contract smoke coverage, but it validates YAML/files/functions by source inspection rather than runtime behavior.",
    },
    "veilbreakers_terrain/tests/test_vb_toolkit_primitives_available.py": {
        "label": "structure_only",
        "priority": "P1",
        "notes": "Packaging smoke plus source-text grep. Useful for file presence, weak for callable behavior.",
    },
    "veilbreakers_terrain/tests/test_world_map_light_atmosphere.py": {
        "label": "live_guardrail",
        "priority": "P0",
        "notes": "Live handler execution with terrain-aware heightmap, mask, density, cell-size, and weather wrapper coverage.",
    },
    "veilbreakers_terrain/tests/test_road_coastline_terrain_features.py": {
        "label": "live_guardrail_expensive",
        "priority": "P1",
        "notes": "Exercises real generators, but runtime cost is high for a dispatch-surface test file (~24.7s in current sample run).",
    },
    "veilbreakers_terrain/tests/test_terrain_materials.py": {
        "label": "broad_fast_logic",
        "priority": "P2",
        "notes": "Large file, but current runtime is efficient (~0.47s for 396 collected tests). Not a priority inefficiency target.",
    },
    "veilbreakers_terrain/tests/test_terrain_chunking.py": {
        "label": "live_guardrail",
        "priority": "P0",
        "notes": "Current compute_chunk_lod integer contract is verified; downsampling behavior is covered through _downsample_heightmap callers.",
    },
    "veilbreakers_terrain/tests/test_terrain_checkpoints.py": {
        "label": "live_guardrail",
        "priority": "P0",
        "notes": "High-value runtime guardrail that currently catches a real Windows NPZ temp-path failure.",
    },
    "veilbreakers_terrain/tests/test_terrain_cliffs.py": {
        "label": "live_guardrail",
        "priority": "P0",
        "notes": "High-value pass-level guardrail currently blocked by undeclared cliff channel writes.",
    },
    "veilbreakers_terrain/tests/test_terrain_caves.py": {
        "label": "live_guardrail",
        "priority": "P0",
        "notes": "High-value pass-level guardrail currently blocked by undeclared cave channels and archetype drift.",
    },
    "veilbreakers_terrain/tests/test_terrain_waterfalls.py": {
        "label": "live_guardrail",
        "priority": "P0",
        "notes": "High-value pass-level guardrail currently blocked by undeclared waterfall velocity and mist behavior drift.",
    },
    "veilbreakers_terrain/tests/test_cross_feature.py": {
        "label": "soft_guardrail",
        "priority": "P1",
        "notes": "Cross-feature invariants are useful, but skip paths make it soft instead of fail-closed.",
    },
    "veilbreakers_terrain/tests/test_bundle_r.py": {
        "label": "soft_guardrail",
        "priority": "P2",
        "notes": "Good protocol/runtime-safety coverage, but at least one gate is skipped and the suite still rides the blender_addon alias shim.",
    },
}


def collect_counts() -> Counter:
    proc = subprocess.run(
        ["pytest", "--collect-only", "-q"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "pytest collection failed while building test guardrail audit:\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
    counts: Counter = Counter()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("veilbreakers_terrain/tests/") or "::" not in line:
            continue
        counts[line.split("::", 1)[0]] += 1
    return counts


def default_label(flags: dict[str, bool]) -> str:
    if flags["run_pass"] or flags["command_handlers_exec"] or flags["validate_tile_seams"]:
        return "live_guardrail"
    if flags["source_introspection"] and not flags["registry_surface"]:
        return "structure_only"
    if flags["registry_surface"]:
        return "registry_surface"
    if flags["mock_heavy"]:
        return "mock_plumbing"
    if flags["skip_or_xfail"]:
        return "soft_guardrail"
    return "logic_guardrail"


def default_priority(label: str) -> str:
    if label in {"live_guardrail_stale_api", "live_guardrail", "mixed_runtime_and_stale"}:
        return "P0"
    if label in {"soft_guardrail", "structure_only", "live_guardrail_expensive"}:
        return "P1"
    return "P2"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict-quality",
        action="store_true",
        help="Fail if stale, mixed-stale, or uncollected test files are present.",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    collected_counts = collect_counts()
    rows = []
    label_counts: Counter = Counter()

    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        flags = {
            label: any(needle in text for needle in needles)
            for label, needles in PATTERNS.items()
        }
        label = default_label(flags)
        priority = default_priority(label)
        notes = ""
        if flags["legacy_alias"]:
            notes = "Uses blender_addon alias shim; this weakens packaging-surface confidence."
        if rel in MANUAL_NOTES:
            label = MANUAL_NOTES[rel]["label"]
            priority = MANUAL_NOTES[rel]["priority"]
            notes = MANUAL_NOTES[rel]["notes"]

        label_counts[label] += 1
        rows.append(
            {
                "test_file": rel,
                "collected_tests": str(collected_counts.get(rel, 0)),
                "label": label,
                "priority": priority,
                "legacy_alias": "yes" if flags["legacy_alias"] else "no",
                "mock_heavy": "yes" if flags["mock_heavy"] else "no",
                "source_introspection": "yes" if flags["source_introspection"] else "no",
                "registry_surface": "yes" if flags["registry_surface"] else "no",
                "skip_or_xfail": "yes" if flags["skip_or_xfail"] else "no",
                "run_pass": "yes" if flags["run_pass"] else "no",
                "command_handlers_exec": "yes" if flags["command_handlers_exec"] else "no",
                "validate_tile_seams": "yes" if flags["validate_tile_seams"] else "no",
                "notes": notes,
            }
        )

    fieldnames = list(rows[0].keys()) if rows else []
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    total_files = len(rows)
    total_tests = sum(int(row["collected_tests"]) for row in rows)
    lines = [
        "# Test Guardrail Summary",
        "",
        "Audit date: 2026-04-19",
        f"Output CSV: `{OUTPUT_CSV}`",
        "",
        "## Totals",
        "",
        f"- Test files scanned: `{total_files}`",
        f"- Collected tests mapped to files: `{total_tests}`",
        f"- Files using legacy `blender_addon` alias: `{sum(row['legacy_alias'] == 'yes' for row in rows)}`",
        f"- Files with source-introspection checks: `{sum(row['source_introspection'] == 'yes' for row in rows)}`",
        f"- Files with registry-surface checks: `{sum(row['registry_surface'] == 'yes' for row in rows)}`",
        f"- Files with skip/xfail gates: `{sum(row['skip_or_xfail'] == 'yes' for row in rows)}`",
        "",
        "Label distribution:",
    ]
    for label, count in sorted(label_counts.items()):
        lines.append(f"- `{label}`: `{count}`")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `live_guardrail`: executes real runtime code or pass logic and should generally be fixed, not retired.",
            "- `live_guardrail_stale_api`: valuable guardrail, but its asserted contract no longer matches the code path it is testing.",
            "- `mixed_runtime_and_stale`: combines useful execution coverage with stale thresholds or wrapper-only expectations.",
            "- `structure_only`: source/file contract check; useful as smoke coverage but insufficient as behavioral proof.",
            "- `mock_plumbing`: validates argument threading and dispatch more than semantics.",
            "- `soft_guardrail`: important invariant, but skip/xfail paths reduce enforcement strength.",
            "- `live_guardrail_expensive`: useful runtime coverage that should be reviewed for fixture/runtime cost.",
        ]
    )
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {OUTPUT_CSV}")
    print(f"Wrote {OUTPUT_MD}")

    stale_rows = [
        row for row in rows
        if row["label"] in {"live_guardrail_stale_api", "mixed_runtime_and_stale"}
    ]
    uncollected_rows = [row for row in rows if int(row["collected_tests"]) == 0]
    if args.strict_quality and (stale_rows or uncollected_rows):
        for row in stale_rows:
            print(f"STALE_TEST_GUARDRAIL: {row['test_file']} [{row['label']}] {row['notes']}")
        for row in uncollected_rows:
            print(f"UNWIRED_TEST_FILE: {row['test_file']} collected_tests=0")
        raise SystemExit(1)


if __name__ == "__main__":
    main()

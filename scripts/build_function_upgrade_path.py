"""Generate a function-by-function upgrade path toward A-grade quality."""

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
    latest_grade,
    norm,
    read_grade_rows,
    resolve_grade_match,
)


OUT_DIR = REPO_ROOT / "output" / "spreadsheet"
DATE_TAG = datetime.now(timezone.utc).strftime("%Y_%m_%d")
OUT_CSV = OUT_DIR / f"FUNCTION_UPGRADE_PATH_TO_A_{DATE_TAG}.csv"
OUT_MD = OUT_DIR / f"FUNCTION_UPGRADE_PATH_TO_A_{DATE_TAG}.md"
CSV_FIELDNAMES = [
    "file",
    "line",
    "callable",
    "kind",
    "domain",
    "current_grade",
    "target_grade",
    "status",
    "priority",
    "match_mode",
    "best_practice_focus",
    "known_weakness",
    "existing_upgrade_hint",
    "upgrade_path",
    "validation_gates",
    "research_refs",
]
TARGET_A_GRADES = {"A", "A-", "A+"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--grade-file",
        type=Path,
        default=DEFAULT_GRADE_FILE,
        help="Path to the grade CSV source. Defaults to docs/aaa-audit/GRADES_VERIFIED.csv.",
    )
    return parser.parse_args()


def _domain(file_name: str, fn: str) -> str:
    token = f"{file_name.lower()}::{fn.lower()}"
    if any(key in token for key in ["noise", "fbm", "perlin", "simplex"]):
        return "noise"
    if any(key in token for key in ["erosion", "weather", "strata", "geology", "karst", "glacial"]):
        return "geomorph"
    if any(key in token for key in ["water", "river", "coast", "pool", "foam", "mist", "drainage", "hydro"]):
        return "hydrology"
    if any(key in token for key in ["road", "navmesh", "path", "astar", "bridge"]):
        return "pathing"
    if any(key in token for key in ["scatter", "vegetation", "wildlife", "ecotone", "biome"]):
        return "ecology"
    if any(key in token for key in ["material", "shader", "palette", "decal", "color"]):
        return "materials"
    if any(key in token for key in ["mesh", "lod", "uv", "normal", "vertex"]):
        return "mesh"
    if any(key in token for key in ["bundle", "pipeline", "pass", "registr", "checkpoint", "protocol"]):
        return "pipeline"
    if any(key in token for key in ["validate", "audit", "quality", "determin", "golden", "test"]):
        return "validation"
    return "generic"


DOMAIN_GUIDANCE = {
    "noise": (
        "Spectral calibration + domain warp + deterministic seeds",
        "Calibrate octave energy to reference terrain spectra; add domain warp and ridge variants; enforce seed-stability golden tests.",
    ),
    "geomorph": (
        "Physically informed landform evolution",
        "Use process-based erosion and weathering constraints, mass-conservation checks, and geomorph plausibility validators.",
    ),
    "hydrology": (
        "Flow-consistent hydrograph and channel geometry",
        "Enforce downhill continuity, discharge-aware widths and depths, and water-feature chain completeness tests.",
    ),
    "pathing": (
        "Cost-field realism + traversal constraints",
        "Apply slope and curvature penalties, road-class contracts, and bridge or ford decisions backed by deterministic path tests.",
    ),
    "ecology": (
        "Biome-coupled distribution realism",
        "Use blue-noise placement with species competition, exclusion, and climate or elevation constraints validated statistically.",
    ),
    "materials": (
        "Physically based material layering",
        "Adopt PBR-safe channel mixing, triplanar and UV consistency, and profile-bound texture budget enforcement.",
    ),
    "mesh": (
        "Topology quality + LOD stability",
        "Protect silhouette and feature edges, enforce normal and tangent correctness, and validate LOD transition error budgets.",
    ),
    "pipeline": (
        "Contract-driven orchestration reliability",
        "Harden produced and consumed channel contracts, rollback integrity, and explicit pass dependency tests.",
    ),
    "validation": (
        "Gate quality with measurable thresholds",
        "Convert heuristic checks into explicit pass or fail metrics, visual diffs, and reproducibility locks.",
    ),
    "generic": (
        "Robust API + correctness + testability",
        "Strengthen input validation, explicit invariants, deterministic behavior, and coverage across edge and corner cases.",
    ),
}


DOMAIN_RESEARCH = {
    "noise": [
        "https://docs.world-creator.com/",
        "https://www.ea.com/frostbite/news/terrain-in-battlefield-3-a-modern-complete-and-scalable-system",
    ],
    "geomorph": [
        "https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode",
        "https://docs.quadspinner.com/Reference/Erosion/Erosion.html",
        "https://help.world-machine.com/topic/device-thermalerosion/",
    ],
    "hydrology": [
        "https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode",
        "https://help.world-machine.com/topic/device-flowrestructure/",
        "https://docs.quadspinner.com/Reference/Erosion/Erosion.html",
    ],
    "pathing": [
        "https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-in-unreal-engine",
        "https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview",
    ],
    "ecology": [
        "https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-pcg-biome-core-and-sample-plugins-in-unreal-engine?application_version=5.6",
        "https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-in-unreal-engine",
        "https://www.world-machine.com/features.php",
    ],
    "materials": [
        "https://www.ubisoft.com/en-us/studio/laforge/news/1i3YOvQX2iArLlScBPqBZs/generative-base-material-an-open-source-prototype-for-pbr-material-estimation-debuting-at-siggraph-asia-2025",
        "https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-in-unreal-engine",
    ],
    "mesh": [
        "https://dev.epicgames.com/documentation/en-us/unreal-engine/geometry-scripting-through-blueprints-in-unreal-engine",
        "https://www.ea.com/frostbite/news/adaptive-hardware-accelerated-terrain-tessellation",
    ],
    "pipeline": [
        "https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-in-unreal-engine",
        "https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview",
    ],
    "validation": [
        "https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-in-unreal-engine",
        "https://help.world-machine.com/topic/build-4046-hurricane-ridge-final/",
    ],
    "generic": [
        "https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-in-unreal-engine",
        "https://docs.world-creator.com/",
    ],
}


def _priority(current_grade: str, status: str) -> str:
    if status == "MISSING" or not current_grade:
        return "P0"
    if current_grade in {"F", "D", "D+", "C-", "C", "C+"}:
        return "P0"
    if current_grade in {"B-", "B", "B+"}:
        return "P1"
    if current_grade in TARGET_A_GRADES:
        return "P3"
    return "P2"


def _status(current_grade: str) -> str:
    if not current_grade:
        return "MISSING"
    if current_grade in TARGET_A_GRADES:
        return "AT_OR_ABOVE_TARGET"
    return "BELOW_TARGET"


def _upgrade_steps(domain: str, current_grade: str, weakness: str, upgrade: str) -> str:
    focus, baseline = DOMAIN_GUIDANCE[domain]
    parts = [
        f"1) {focus}.",
        f"2) {baseline}",
        "3) Add deterministic unit and integration tests with edge and corner cases.",
        "4) Add performance budget checks and fail CI on regressions.",
        "5) Add visual or golden regression artifacts where applicable.",
    ]
    if weakness:
        parts.append(f"Known gap: {weakness}")
    if upgrade:
        parts.append(f"Targeted upgrade hint: {upgrade}")
    if current_grade in TARGET_A_GRADES:
        parts.append("Maintenance mode: preserve grade with regression gates and benchmark locks.")
    return " ".join(parts)


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

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    callables = collect_callables(include_init=True)
    grade_index = build_grade_index(read_grade_rows(grades_csv))

    rows: List[dict] = []
    by_priority: Counter[str] = Counter()
    by_domain: Counter[str] = Counter()

    for callable_def in sorted(callables, key=lambda item: (item.file, item.lineno, item.qualified_name)):
        match = resolve_grade_match(callable_def, grade_index)
        matched_row = match.row or {}
        current_grade = latest_grade(matched_row)
        domain = _domain(callable_def.file, callable_def.qualified_name)
        status = _status(current_grade)
        priority = _priority(current_grade, status)
        by_priority[priority] += 1
        by_domain[domain] += 1

        weakness = norm(matched_row.get("Weakness", ""))
        upgrade = norm(matched_row.get("Upgrade", ""))
        focus, _ = DOMAIN_GUIDANCE[domain]

        rows.append(
            {
                "file": callable_def.file,
                "line": callable_def.lineno,
                "callable": callable_def.qualified_name,
                "kind": callable_def.kind,
                "domain": domain,
                "current_grade": current_grade,
                "target_grade": "A",
                "status": status,
                "priority": priority,
                "match_mode": match.match_mode,
                "best_practice_focus": focus,
                "known_weakness": weakness,
                "existing_upgrade_hint": upgrade,
                "upgrade_path": _upgrade_steps(domain, current_grade, weakness, upgrade),
                "validation_gates": "determinism|perf_budget|golden_visual|contract_tests",
                "research_refs": "|".join(DOMAIN_RESEARCH[domain]),
            }
        )

    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# Function-by-Function Upgrade Path to A",
        "",
        f"- Grade source: `{_relative_grade_path(grades_csv)}`",
        f"- Total callables planned: **{len(rows)}**",
        f"- P0 (missing/C-range and below): **{by_priority['P0']}**",
        f"- P1 (B-range): **{by_priority['P1']}**",
        f"- P2 (other/non-standard): **{by_priority['P2']}**",
        f"- P3 (already A-range): **{by_priority['P3']}**",
        "",
        "## Domain distribution",
        "",
    ]
    for domain, count in by_domain.most_common():
        lines.append(f"- {domain}: {count}")

    lines.extend(["", "## Domain research references", ""])
    for domain, refs in DOMAIN_RESEARCH.items():
        lines.append(f"- {domain}: " + "; ".join(refs))

    lines.extend(
        [
            "",
            "## Execution order",
            "",
            "1) Complete all P0 callables first with correctness and determinism gates.",
            "2) Raise P1 callables with domain-specific best-practice upgrades.",
            "3) Lock P3 callables using regression, performance, and golden CI protections.",
            "4) Re-grade and re-run this planner until P0=0 and P1=0.",
        ]
    )

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"wrote {OUT_CSV}")
    print(f"wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

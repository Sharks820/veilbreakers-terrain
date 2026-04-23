"""Generate a function-by-function upgrade path toward A-grade quality.

This script creates a per-callable plan (one row per callable) using:
- live callable inventory from handlers/*.py
- optional grade coverage from GRADES_VERIFIED.csv (or another source)
- deterministic domain best-practice templates keyed by module/function semantics

Outputs:
- output/spreadsheet/FUNCTION_UPGRADE_PATH_TO_A_<YYYY_MM_DD>.csv
- output/spreadsheet/FUNCTION_UPGRADE_PATH_TO_A_<YYYY_MM_DD>.md
"""

from __future__ import annotations

import ast
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
HANDLERS_DIR = REPO_ROOT / "veilbreakers_terrain" / "handlers"
GRADES_CSV = REPO_ROOT / "docs" / "aaa-audit" / "GRADES_VERIFIED.csv"
OUT_DIR = REPO_ROOT / "output" / "spreadsheet"
DATE_TAG = datetime.now(timezone.utc).strftime("%Y_%m_%d")
OUT_CSV = OUT_DIR / f"FUNCTION_UPGRADE_PATH_TO_A_{DATE_TAG}.csv"
OUT_MD = OUT_DIR / f"FUNCTION_UPGRADE_PATH_TO_A_{DATE_TAG}.md"

A_GRADES = {"A", "A-", "A+"}


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
    out: List[CallableDef] = []
    for py in sorted(HANDLERS_DIR.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"), filename=str(py))
        v = CallableVisitor(py.name)
        v.visit(tree)
        out.extend(v.rows)
    return out


def read_grade_rows(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _norm(v: str) -> str:
    return (v or "").strip()


def map_grades(rows: Iterable[dict]) -> Dict[Tuple[str, str], dict]:
    out: Dict[Tuple[str, str], dict] = {}
    for row in rows:
        file_name = _norm(row.get("File", ""))
        fn = _norm(row.get("Function", ""))
        if file_name and fn:
            out[(file_name, fn)] = row
    return out


def _domain(file_name: str, fn: str) -> str:
    token = f"{file_name.lower()}::{fn.lower()}"
    if any(k in token for k in ["noise", "fbm", "perlin", "simplex"]):
        return "noise"
    if any(k in token for k in ["erosion", "weather", "strata", "geology", "karst", "glacial"]):
        return "geomorph"
    if any(k in token for k in ["water", "river", "coast", "pool", "foam", "mist", "drainage", "hydro"]):
        return "hydrology"
    if any(k in token for k in ["road", "navmesh", "path", "astar", "bridge"]):
        return "pathing"
    if any(k in token for k in ["scatter", "vegetation", "wildlife", "ecotone", "biome"]):
        return "ecology"
    if any(k in token for k in ["material", "shader", "palette", "decal", "color"]):
        return "materials"
    if any(k in token for k in ["mesh", "lod", "uv", "normal", "vertex"]):
        return "mesh"
    if any(k in token for k in ["bundle", "pipeline", "pass", "registr", "checkpoint", "protocol"]):
        return "pipeline"
    if any(k in token for k in ["validate", "audit", "quality", "determin", "golden", "test"]):
        return "validation"
    return "generic"


DOMAIN_GUIDANCE = {
    "noise": (
        "Spectral calibration + domain-warp + deterministic seeds",
        "Calibrate octave energy to reference terrain spectra; add domain warp and ridge variants; enforce seed-stability golden tests.",
    ),
    "geomorph": (
        "Physically-informed landform evolution",
        "Use process-based erosion/weathering constraints, mass conservation checks, and geomorph plausibility validators.",
    ),
    "hydrology": (
        "Flow-consistent hydrograph and channel geometry",
        "Enforce downhill continuity, discharge-aware widths/depths, and water-feature chain completeness tests.",
    ),
    "pathing": (
        "Cost-field realism + traversal constraints",
        "Apply slope/curvature penalties, road class contracts, and bridge/ford decisions backed by deterministic path tests.",
    ),
    "ecology": (
        "Biome-coupled distribution realism",
        "Use blue-noise placement with species competition/exclusion and climate/elevation constraints validated statistically.",
    ),
    "materials": (
        "Physically based material layering",
        "Adopt PBR-safe channel mixing, triplanar/UV consistency, and profile-bound texture budget enforcement.",
    ),
    "mesh": (
        "Topology quality + LOD stability",
        "Protect silhouette/feature edges, enforce normal/tangent correctness, and validate LOD transition error budgets.",
    ),
    "pipeline": (
        "Contract-driven orchestration reliability",
        "Harden produced/consumed channel contracts, rollback/checkpoint integrity, and explicit pass dependency tests.",
    ),
    "validation": (
        "Gate quality with measurable thresholds",
        "Convert heuristic checks into explicit pass/fail metrics, visual diffs, and reproducibility locks.",
    ),
    "generic": (
        "Robust API + correctness + testability",
        "Strengthen input validation, explicit invariants, deterministic behavior, and coverage across edge/corner cases.",
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


def _priority(final_grade: str, status: str) -> str:
    if status == "MISSING" or not final_grade:
        return "P0"
    if final_grade in {"F", "D", "D+", "C-", "C", "C+"}:
        return "P0"
    if final_grade in {"B-", "B", "B+"}:
        return "P1"
    if final_grade in A_GRADES:
        return "P3"
    return "P2"


def _status(final_grade: str) -> str:
    if not final_grade:
        return "MISSING"
    if final_grade in A_GRADES:
        return "AT_OR_ABOVE_TARGET"
    return "BELOW_TARGET"


def _upgrade_steps(domain: str, final_grade: str, weakness: str, upgrade: str) -> str:
    pillar, baseline = DOMAIN_GUIDANCE[domain]
    parts = [
        f"1) {pillar}.",
        f"2) {baseline}",
        "3) Add deterministic unit + integration tests with edge/corner cases.",
        "4) Add performance budget checks (time+memory) and fail CI on regressions.",
        "5) Add visual/golden regression artifacts for terrain outputs where applicable.",
    ]
    if weakness:
        parts.append(f"Known gap: {weakness}")
    if upgrade:
        parts.append(f"Targeted upgrade hint: {upgrade}")
    if final_grade in A_GRADES:
        parts.append("Maintenance mode: preserve grade with regression gates and benchmark locks.")
    return " ".join(parts)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    callables = collect_callables()
    grade_rows = read_grade_rows(GRADES_CSV)
    grade_map = map_grades(grade_rows)

    rows: List[dict] = []
    by_priority: Counter[str] = Counter()
    by_domain: Counter[str] = Counter()

    for c in sorted(callables, key=lambda x: (x.file, x.lineno, x.qualified_name)):
        g = grade_map.get((c.file, c.simple_name), {})
        final_grade = _norm(g.get("FINAL GRADE", ""))
        domain = _domain(c.file, c.qualified_name)
        status = _status(final_grade)
        priority = _priority(final_grade, status)
        by_priority[priority] += 1
        by_domain[domain] += 1

        weakness = _norm(g.get("Weakness", ""))
        upgrade = _norm(g.get("Upgrade", ""))
        pillar, _ = DOMAIN_GUIDANCE[domain]

        rows.append(
            {
                "file": c.file,
                "line": c.lineno,
                "callable": c.qualified_name,
                "kind": c.kind,
                "domain": domain,
                "current_final_grade": final_grade,
                "target_grade": "A",
                "status": status,
                "priority": priority,
                "best_practice_focus": pillar,
                "known_weakness": weakness,
                "existing_upgrade_hint": upgrade,
                "upgrade_path": _upgrade_steps(domain, final_grade, weakness, upgrade),
                "validation_gates": "determinism|perf_budget|golden_visual|contract_tests",
                "research_refs": "|".join(DOMAIN_RESEARCH[domain]),
            }
        )

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    lines = [
        "# Function-by-Function Upgrade Path to A",
        "",
        f"- Grade source: `{GRADES_CSV.relative_to(REPO_ROOT)}`",
        f"- Total callables planned: **{len(rows)}**",
        f"- P0 (missing/C/D/F): **{by_priority['P0']}**",
        f"- P1 (B-range): **{by_priority['P1']}**",
        f"- P2 (other/non-standard): **{by_priority['P2']}**",
        f"- P3 (already A-range): **{by_priority['P3']}**",
        "",
        "## Domain distribution",
        "",
    ]
    for domain, count in by_domain.most_common():
        lines.append(f"- {domain}: {count}")

    lines.extend([
        "",
        "## Domain research references",
        "",
    ])
    for domain, refs in DOMAIN_RESEARCH.items():
        lines.append(f"- {domain}: " + "; ".join(refs))

    lines.extend([
        "",
        "## Execution order",
        "",
        "1) Complete all P0 callables first with correctness + determinism gates.",
        "2) Raise P1 callables with domain-specific best-practice upgrades.",
        "3) Lock P3 callables using regression/perf/golden CI protections.",
        "4) Re-grade and re-run this planner until P0=0 and P1=0.",
    ])

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"wrote {OUT_CSV}")
    print(f"wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

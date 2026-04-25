"""Build R11 research-grounded callable audit for the whole Python codebase.

This audit is separate from ``GRADES_VERIFIED.csv``. It grades every parsed
Python function/class against an explicit AAA procedural-terrain benchmark
matrix, then records the reason for each cap.
"""

from __future__ import annotations

import ast
import csv
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "aaa-audit"
CSV_OUT = OUT_DIR / "R11_RESEARCH_AAA_CALLABLE_AUDIT.csv"
SUMMARY_OUT = OUT_DIR / "R11_RESEARCH_AAA_CALLABLE_AUDIT_SUMMARY.md"
REFS_OUT = OUT_DIR / "R11_DEDICATED_RESEARCH_REFERENCES_2026_04_24.md"
BELOW_B_OUT = OUT_DIR / "R11_BELOW_B_REMEDIATION_BACKLOG.csv"
STRICT_BELOW_B_OUT = OUT_DIR / "R11_STRICT_BELOW_B_REMAINING.csv"
LIVE_TEST_PLAN_OUT = OUT_DIR / "R11_B_FLOOR_LIVE_TEST_PLAN.md"
WIRING_CSV = ROOT / "output" / "spreadsheet" / "CALLABLE_WIRING_AUDIT_2026_04_19.csv"


RESEARCH_SOURCES = [
    {
        "id": "UE_PCG",
        "title": "Unreal Engine PCG Framework / biome generation",
        "url": "https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview?application_version=5.6",
        "standard": "Graph-driven procedural tools for assets, biomes, and entire worlds; designer iteration is a first-class requirement.",
    },
    {
        "id": "HOUDINI_HEIGHTFIELDS",
        "title": "SideFX Houdini Heightfields and terrains",
        "url": "https://www.sidefx.com/docs/houdini/heightfields/index.html",
        "standard": "Layered heightfields, masks, paintable controls, erosion, conversion to geometry for vertical detail, and scatter on vertical areas.",
    },
    {
        "id": "HOUDINI_ERODE",
        "title": "SideFX HeightField Erode",
        "url": "https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode.html",
        "standard": "Hydraulic and thermal erosion at controllable feature scales; rainfall/weathering, bank angle, flow/debris/sediment outputs, spatial masks.",
    },
    {
        "id": "GAEA_EROSION",
        "title": "QuadSpinner Gaea Erosion",
        "url": "https://docs.gaea.app/using-gaea/crafting-the-surface/erosion",
        "standard": "Believable terrain comes from erosion layered with other processes, selective processing, downcutting, and deposits.",
    },
    {
        "id": "GAEA_TERRAINS",
        "title": "QuadSpinner Gaea terrain tools",
        "url": "https://www.quadspinner.com/Gaea/Terrains",
        "standard": "Rock/sandstone/limestone tools, strata, sediment, fractures, protruding outcrops, draw/mask nodes, and volume-preserving surface detail.",
    },
    {
        "id": "FROSTBITE_TERRAIN",
        "title": "Frostbite Battlefield 3 terrain system",
        "url": "https://www.ea.com/frostbite/news/terrain-in-battlefield-3-a-modern-complete-and-scalable-system",
        "standard": "Large open-world terrain requires hierarchy, high resolution at distance, in-game editing, procedural virtual texture caching, prioritization, and streaming.",
    },
]


DOMAIN_RULES = {
    "terrain_shape": {
        "refs": "HOUDINI_HEIGHTFIELDS|GAEA_TERRAINS|GAEA_EROSION|FROSTBITE_TERRAIN",
        "required": "Layered macro/meso/micro landforms, art-directed masks, erosion/deposition, cliff/foothill/flatland family controls, tiled visual goldens.",
        "cap": "B",
    },
    "cliffs": {
        "refs": "HOUDINI_HEIGHTFIELDS|GAEA_TERRAINS",
        "required": "Real strata/fractures/outcrops/talus, vertical-detail geometry or assets, material projection, and rendered readability proof.",
        "cap": "B",
    },
    "water": {
        "refs": "HOUDINI_ERODE|GAEA_EROSION|HOUDINI_HEIGHTFIELDS",
        "required": "Carved bed before surface, banks, shelves, spillways, held basins, wet material borders, flow/debris/sediment channels, seam proof.",
        "cap": "B+",
    },
    "roads_paths": {
        "refs": "UE_PCG|HOUDINI_HEIGHTFIELDS",
        "required": "Terrain deformation, shoulders, drainage, worn material blending, spline/path authoring, biome-aware side dressing, rendered proof.",
        "cap": "B+",
    },
    "biome_transition": {
        "refs": "UE_PCG|HOUDINI_HEIGHTFIELDS",
        "required": "Shared ecotone masks that drive height, materials, scatter density, atmosphere, and gameplay together; no abrupt start/stop.",
        "cap": "B",
    },
    "scatter_foliage": {
        "refs": "UE_PCG|HOUDINI_HEIGHTFIELDS|FROSTBITE_TERRAIN",
        "required": "Ecological density falloffs, forest core/edge/sparse bands, asset LODs, batching/streaming, slope/moisture constraints, visual proof.",
        "cap": "B+",
    },
    "materials": {
        "refs": "HOUDINI_HEIGHTFIELDS|GAEA_TERRAINS|FROSTBITE_TERRAIN",
        "required": "8-12+ layered PBR terrain stack, triplanar/height blends, macro variation, wetness/sediment integration, engine import/render proof.",
        "cap": "B+",
    },
    "lod_streaming_export": {
        "refs": "FROSTBITE_TERRAIN|UE_PCG",
        "required": "World hierarchy, streaming, virtual texture/cache strategy, screen-error budgets, engine import smoke tests.",
        "cap": "A-",
    },
    "validation_visual": {
        "refs": "FROSTBITE_TERRAIN|UE_PCG",
        "required": "Golden rendered terrain families, adjacent-tile seam proof, engine import gates, pixel/readability metrics.",
        "cap": "B+",
    },
    "tooling_wiring": {
        "refs": "UE_PCG|FROSTBITE_TERRAIN",
        "required": "Graph/tool exposure, deterministic callable contracts, runtime wiring, clear failure modes, designer iteration path.",
        "cap": "B+",
    },
    "generic": {
        "refs": "UE_PCG",
        "required": "Runtime relevance, tests, deterministic behavior, and clear integration into terrain/world generation.",
        "cap": "B",
    },
}

GRADE_ORDER = ["F", "D", "D+", "C", "C+", "B-", "B", "B+", "A-", "A"]
GRADE_RANK = {grade: idx for idx, grade in enumerate(GRADE_ORDER)}

LIVETEST_FLOOR = "B"

SUPPORT_FUNCTIONS = {
    "__getattr__",
    "__init__",
    "__post_init__",
    "__repr__",
    "__str__",
    "as_dict",
    "copy",
    "from_dict",
    "items",
    "keys",
    "register",
    "to_dict",
    "validate",
    "values",
    "world_region_dimensions",
}

SUPPORT_PREFIXES = (
    "_",
    "get_",
    "set_",
    "resolve_",
    "sample_",
)

TOOLING_FILE_STEMS = {
    "__init__",
    "blender_capability_bridge",
    "socket_server",
    "terrain_master_registrar",
    "terrain_pipeline",
}

SUPPORT_FILE_STEMS = {
    "_biome_grammar",
    "_mesh_bridge",
    "_terrain_noise",
    "mesh",
    "procedural_materials",
    "road_network",
    "terrain_blender_safety",
    "terrain_dirty_tracking",
    "terrain_foliage_catalog",
    "terrain_hot_reload",
    "terrain_iteration_metrics",
    "terrain_live_preview",
    "terrain_mask_cache",
    "terrain_master_registrar",
    "terrain_materials",
    "terrain_negative_space",
    "terrain_readability_bands",
    "terrain_region_exec",
    "terrain_semantics",
    "terrain_validation",
    "terrain_water_variants",
    "vegetation_lsystem",
}


@dataclass(frozen=True)
class CallableRow:
    file: str
    qualname: str
    function: str
    line: int
    kind: str
    scope: str


def cap_grade(grade: str, cap: str) -> str:
    return grade if GRADE_RANK[grade] <= GRADE_RANK[cap] else cap


def git_files() -> list[Path]:
    commands = (
        ["git", "ls-files", "*.py"],
        ["git", "ls-files", "--others", "--exclude-standard", "*.py"],
    )
    files: list[Path] = []
    seen: set[Path] = set()
    for cmd in commands:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            path = (ROOT / line.strip()).resolve()
            try:
                rel = path.relative_to(ROOT)
            except ValueError:
                continue
            if any(part in {".git", ".pr5-worktree", "__pycache__", ".pytest_cache"} for part in rel.parts):
                continue
            if rel.parts and rel.parts[0] in {"output", "node_modules", ".venv", "venv"}:
                continue
            if path not in seen and path.exists():
                files.append(path)
                seen.add(path)
    return sorted(files)


def classify_scope(rel: Path) -> str:
    parts = set(rel.parts)
    if "tests" in parts or rel.name.startswith("test_"):
        return "test"
    if rel.parts and rel.parts[0] == "scripts":
        return "script"
    if "handlers" in parts:
        return "runtime_handler"
    if "src" in parts:
        return "runtime_src"
    return "runtime_other"


def collect_callables() -> list[CallableRow]:
    rows: list[CallableRow] = []
    for path in git_files():
        rel = path.relative_to(ROOT)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(rel))
        except SyntaxError:
            continue

        scope = classify_scope(rel)

        def walk(body: Iterable[ast.stmt], prefix: tuple[str, ...] = ()) -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    qual = (*prefix, node.name)
                    rows.append(CallableRow(str(rel).replace("\\", "/"), ".".join(qual), node.name, node.lineno, "class", scope))
                    walk(node.body, qual)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qual = (*prefix, node.name)
                    kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
                    if prefix:
                        kind = "method" if prefix[-1][:1].isupper() else "nested_function"
                    rows.append(CallableRow(str(rel).replace("\\", "/"), ".".join(qual), node.name, node.lineno, kind, scope))
                    walk(node.body, qual)

        walk(tree.body)
    return rows


def load_wiring() -> dict[tuple[str, str], dict[str, str]]:
    if not WIRING_CSV.exists():
        return {}
    with WIRING_CSV.open(newline="", encoding="utf-8-sig") as handle:
        return {
            (row["file"], row["function"]): row
            for row in csv.DictReader(handle)
        }


def infer_domain(row: CallableRow) -> str:
    file_stem = Path(row.file).stem.lower()
    text = f"{file_stem} {row.qualname} {row.function}".lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))

    def has(*words: str) -> bool:
        normalized = text.replace(".", "_").replace("-", "_")
        return any(
            word in tokens
            or f"_{word}_" in f"_{normalized}_"
            or ("_" in word and word in normalized)
            for word in words
        )

    if file_stem in TOOLING_FILE_STEMS or has("capability", "handler", "command", "socket", "mcp", "pipeline"):
        return "tooling_wiring"
    if row.function in {"register", "unregister", "__getattr__"}:
        return "tooling_wiring"
    if row.function in {"__init__", "to_dict", "from_dict", "as_dict", "validate"}:
        return "generic"
    if has("cliff", "canyon", "ridge", "rock_face", "outcrop", "talus"):
        return "cliffs"
    if has("water", "river", "stream", "lake", "basin", "shore", "bank", "wetland", "waterfall", "spring"):
        return "water"
    if has("road", "path", "trail", "bridge"):
        return "roads_paths"
    if has("biome", "ecotone", "transition", "forest_edge", "forest", "marsh", "swamp"):
        return "biome_transition"
    if has("scatter", "vegetation", "foliage", "grass", "tree", "bush", "forest", "asset"):
        return "scatter_foliage"
    if has("material", "splat", "texture", "pbr", "triplanar", "shader"):
        return "materials"
    if has("validate", "visual", "qa", "golden", "render", "screenshot", "readability"):
        return "validation_visual"
    if has("height", "heightmap", "mountain", "hill", "flat", "erosion", "noise", "world"):
        return "terrain_shape"
    if has("lod", "streaming", "unity_export", "export", "chunk", "world_partition"):
        return "lod_streaming_export"
    return "generic"


def is_structural_support(row: CallableRow) -> bool:
    """Return True for callables whose quality is proved by their callers.

    The R11 audit parses classes and nested helpers in addition to top-level
    runtime handlers. Static wiring scans do not expose classes as command
    surfaces, so grading those as orphaned feature generators creates false
    below-B rows. Their live-test floor is B when importable and covered by
    the surrounding runtime/tests; product-facing functions still need wiring
    and visual evidence.
    """
    if row.kind == "class":
        return True
    if row.kind == "nested_function":
        return True
    if row.function in SUPPORT_FUNCTIONS:
        return True
    if row.kind == "method" and row.function.startswith("_"):
        return True
    if row.kind == "method" and not row.function.startswith(("handle_", "pass_")):
        return True
    if row.function.startswith(SUPPORT_PREFIXES):
        return True
    if Path(row.file).stem.lower() in SUPPORT_FILE_STEMS and not row.function.startswith(("handle_", "pass_")):
        return True
    return False


def has_test_or_runtime_evidence(wiring_row: dict[str, str] | None) -> bool:
    if not wiring_row:
        return False
    keys = (
        "non_test_direct_calls",
        "non_test_attr_calls",
        "non_test_attr_reads",
        "test_direct_calls",
        "test_attr_calls",
        "test_attr_reads",
    )
    for key in keys:
        try:
            if int(wiring_row.get(key, "0") or "0") > 0:
                return True
        except ValueError:
            continue
    return bool(wiring_row.get("runtime_exposure", "").strip() not in {"", "none"})


def remediation_category(row: CallableRow, grade: str, wiring_row: dict[str, str] | None) -> str:
    if row.scope == "test":
        return "TEST_NOT_SHIPPED"
    if GRADE_RANK.get(grade, 99) >= GRADE_RANK[LIVETEST_FLOOR]:
        return "MEETS_B_FLOOR"
    if is_structural_support(row):
        return "RECLASSIFY_SUPPORT_HELPER"
    if wiring_row and wiring_row.get("status") == "orphan_candidate":
        return "WIRE_OR_REGISTER"
    if wiring_row and wiring_row.get("status") == "test_only_or_unwired":
        return "WIRE_OR_REGISTER" if row.function.startswith("handle_") else "ADD_DIRECT_RUNTIME_TEST"
    if not wiring_row:
        return "WIRE_OR_REGISTER" if not row.function.startswith("_") else "ADD_DIRECT_RUNTIME_TEST"
    return "LIVE_VISUAL_GOLDEN_REQUIRED"


def live_test_floor_grade(row: CallableRow, grade: str, category: str, wiring_row: dict[str, str] | None) -> str:
    if row.scope == "test":
        return "N/A"
    if GRADE_RANK.get(grade, 99) >= GRADE_RANK[LIVETEST_FLOOR]:
        return grade
    if category == "RECLASSIFY_SUPPORT_HELPER":
        return LIVETEST_FLOOR
    if wiring_row and wiring_row.get("status") == "test_only_or_unwired" and has_test_or_runtime_evidence(wiring_row):
        return LIVETEST_FLOOR
    return grade


def grade_row(row: CallableRow, wiring: dict[tuple[str, str], dict[str, str]]) -> tuple[str, str, str]:
    domain = infer_domain(row)
    rule = DOMAIN_RULES[domain]
    grade = rule["cap"]
    findings: list[str] = [f"Benchmarked against {rule['refs']}: {rule['required']}"]

    if row.scope == "test":
        return "N/A", "test_callable", "Test/support callable; not graded as shipped terrain feature."

    if row.scope == "script":
        grade = cap_grade(grade, "B")
        findings.append("Script callable: useful tooling, but not runtime terrain quality unless wired into a required gate.")

    file_name = Path(row.file).name
    wiring_row = wiring.get((file_name, row.function))
    if is_structural_support(row):
        grade = cap_grade(grade, "B")
        findings.append("Structural support callable: live quality is proven through its parent runtime surface, not as an independent terrain feature.")
    if wiring_row:
        status = wiring_row.get("status", "")
        findings.append(f"Wiring scan status: {status}.")
        if status == "runtime_primary":
            grade = cap_grade(grade, rule["cap"])
        elif status == "helper_reachable":
            grade = cap_grade(grade, rule["cap"])
        elif status == "test_only_or_unwired":
            if not is_structural_support(row):
                grade = cap_grade(grade, "B-")
                findings.append("Capped: direct runtime path not proven by scanner.")
        elif status == "orphan_candidate":
            if not is_structural_support(row):
                grade = cap_grade(grade, "C+")
                findings.append("Capped: no proven non-test/runtime caller.")
        elif status == "uninvoked_registrar":
            if not is_structural_support(row):
                grade = cap_grade(grade, "C+")
                findings.append("Capped: registrar not proven invoked.")
    elif row.scope == "runtime_handler":
        if not is_structural_support(row):
            grade = cap_grade(grade, "C+")
            findings.append("Capped: no row in callable wiring audit.")
    elif row.scope in {"runtime_other", "runtime_src"}:
        grade = cap_grade(grade, "B")
        findings.append("Non-handler runtime callable: not expected in handler wiring audit; capped at B until direct/live tests cover it.")

    if domain in {"terrain_shape", "cliffs", "water", "roads_paths", "biome_transition", "scatter_foliage", "materials"}:
        grade = cap_grade(grade, rule["cap"])
        findings.append("Visual/live-output grade ceiling applied: no required dark-medieval open-world golden render evidence.")

    confidence = "medium"
    if row.scope == "runtime_handler" and not wiring_row:
        confidence = "low"
    if wiring_row and wiring_row.get("status") in {"runtime_primary", "helper_reachable"}:
        confidence = "medium-high"
    return grade, confidence, " ".join(findings)


def write_refs() -> None:
    lines = [
        "# R11 Dedicated AAA Terrain Research References — 2026-04-24",
        "",
        "This file is the reference base used by `scripts/build_r11_research_aaa_callable_audit.py`.",
        "The target is dark-medieval, RPG-style, large open-world terrain: mountains, cliffs, hills, flats, streams, rivers, roads/pathways, forest edges, biome transitions, scatter, materials, and validation.",
        "",
        "## Sources",
        "",
    ]
    for source in RESEARCH_SOURCES:
        lines.extend([
            f"### {source['id']}: {source['title']}",
            f"- URL: {source['url']}",
            f"- Applied standard: {source['standard']}",
            "",
        ])
    lines.extend([
        "## R11 Grade Meaning",
        "",
        "- `A`: Runtime-shipped, visually proven, engine/import-proven, and comparable to the cited AAA/tool standards.",
        "- `A-`: Strong implementation with runtime wiring and tests, but missing one major AAA proof such as rendered goldens or engine import smoke.",
        "- `B+`: Solid algorithm/runtime surface, but visible/live-output gaps remain.",
        "- `B`: Works structurally, but output quality is not AAA.",
        "- `B-`: Test-only, weakly wired, or missing production proof.",
        "- `C+` or lower: orphaned, missing wiring evidence, placeholder, degraded, or not a shipped terrain feature.",
        "",
    ])
    REFS_OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_refs()
    wiring = load_wiring()
    callables = collect_callables()
    fieldnames = [
        "File",
        "Qualified Name",
        "Function",
        "Line",
        "Kind",
        "Scope",
        "R11 Domain",
        "Research Refs",
        "R11 Required AAA Evidence",
        "R11 Grade",
        "R11 B-Floor Grade",
        "R11 Remediation Category",
        "R11 Confidence",
        "R11 Findings",
    ]
    out_rows: list[dict[str, str]] = []
    for row in callables:
        domain = infer_domain(row)
        rule = DOMAIN_RULES[domain]
        grade, confidence, findings = grade_row(row, wiring)
        wiring_row = wiring.get((Path(row.file).name, row.function))
        remediation = remediation_category(row, grade, wiring_row)
        b_floor_grade = live_test_floor_grade(row, grade, remediation, wiring_row)
        out_rows.append({
            "File": row.file,
            "Qualified Name": row.qualname,
            "Function": row.function,
            "Line": str(row.line),
            "Kind": row.kind,
            "Scope": row.scope,
            "R11 Domain": domain,
            "Research Refs": rule["refs"],
            "R11 Required AAA Evidence": rule["required"],
            "R11 Grade": grade,
            "R11 B-Floor Grade": b_floor_grade,
            "R11 Remediation Category": remediation,
            "R11 Confidence": confidence,
            "R11 Findings": findings,
        })

    with CSV_OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    strict_below_b_rows = [
        row for row in out_rows
        if row["Scope"] != "test"
        and GRADE_RANK.get(row["R11 Grade"], 99) < GRADE_RANK[LIVETEST_FLOOR]
    ]
    below_b_rows = [
        row for row in out_rows
        if row["Scope"] != "test"
        and GRADE_RANK.get(row["R11 B-Floor Grade"], 99) < GRADE_RANK[LIVETEST_FLOOR]
    ]
    with STRICT_BELOW_B_OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(strict_below_b_rows)
    with BELOW_B_OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(below_b_rows)

    by_grade = Counter(row["R11 Grade"] for row in out_rows)
    by_b_floor = Counter(row["R11 B-Floor Grade"] for row in out_rows)
    by_domain = Counter(row["R11 Domain"] for row in out_rows)
    by_scope = Counter(row["Scope"] for row in out_rows)
    by_remediation = Counter(row["R11 Remediation Category"] for row in out_rows)
    summary = [
        "# R11 Research-Grounded AAA Callable Audit Summary",
        "",
        f"- Total parsed Python callables/classes: {len(out_rows)}",
        f"- CSV: `{CSV_OUT.relative_to(ROOT)}`",
        f"- Strict below-B remaining: `{STRICT_BELOW_B_OUT.relative_to(ROOT)}`",
        f"- Provisional live-test B-floor backlog: `{BELOW_B_OUT.relative_to(ROOT)}`",
        f"- References: `{REFS_OUT.relative_to(ROOT)}`",
        "",
        "## Grade Distribution",
        "",
    ]
    for grade, count in by_grade.most_common():
        summary.append(f"- `{grade}`: {count}")
    summary.extend(["", "## B-Floor Grade Distribution", ""])
    for grade, count in by_b_floor.most_common():
        summary.append(f"- `{grade}`: {count}")
    summary.extend(["", "## Remediation Distribution", ""])
    for category, count in by_remediation.most_common():
        summary.append(f"- `{category}`: {count}")
    summary.extend(["", "## Domain Distribution", ""])
    for domain, count in by_domain.most_common():
        summary.append(f"- `{domain}`: {count}")
    summary.extend(["", "## Scope Distribution", ""])
    for scope, count in by_scope.most_common():
        summary.append(f"- `{scope}`: {count}")
    summary.extend([
        "",
        "## R11 Bottom Line",
        "",
        f"Strict non-test callables still below B: `{len(strict_below_b_rows)}`.",
        f"Provisional live-test B-floor rows still below B after support-helper reclassification: `{len(below_b_rows)}`.",
        "The provisional B-floor is not a claim that every callable was independently optimized to AAA quality.",
        "It means structural classes, nested helpers, and private support methods were not treated as standalone terrain products. Strict below-B rows still require targeted wiring, direct runtime tests, live visual golden proof, or deprecation before a true verified B claim.",
    ])
    SUMMARY_OUT.write_text("\n".join(summary), encoding="utf-8")

    live_plan = [
        "# R11 B-Floor Live Test Plan",
        "",
        "Target: separate product-facing terrain risks from support-helper audit noise before live testing.",
        "",
        "Important: this plan does not prove every callable is independently AAA B. Strict below-B rows remain in `R11_STRICT_BELOW_B_REMAINING.csv`; the B-floor CSV only shows rows still below B after support-helper reclassification.",
        "",
        "## Required Live Scenes",
        "",
        "- River and stream scene: carved bed below water surface, asymmetric banks, shelves, wet margins, flow direction colors, seam continuity across adjacent tiles.",
        "- Mountain/cliff scene: macro mountain massing, cliff strata/fracture/talus masks, foothill-to-flatland transition, no blocky height noise.",
        "- Road/path scene: terrain deformation, shoulders, drainage cuts, worn material blend, path spline proof across slopes and flats.",
        "- Scatter/forest scene: forest core, edge, sparse transition, grass species variation, slope/moisture gating, no abrupt biome cut lines.",
        "- Material scene: triplanar cliff/wet rock proof, macro color breakup, sediment/wetness borders, texture stretch check.",
        "",
        "## Verification Gates",
        "",
        "- Regenerate callable wiring: `python scripts\\scan_callable_wiring.py`.",
        "- Regenerate R11 audit: `python scripts\\build_r11_research_aaa_callable_audit.py`.",
        "- Focused tests: `python -m pytest veilbreakers_terrain\\tests\\test_aaa_water_scatter.py veilbreakers_terrain\\tests\\test_terrain_wiring_integration.py veilbreakers_terrain\\tests\\test_terrain_pipeline_smoke.py veilbreakers_terrain\\tests\\test_visual_testing_readiness.py -q`.",
        "- Remaining remediation CSV must be reviewed at `docs\\aaa-audit\\R11_BELOW_B_REMEDIATION_BACKLOG.csv`.",
    ]
    LIVE_TEST_PLAN_OUT.write_text("\n".join(live_plan), encoding="utf-8")

    print(f"R11 callables audited: {len(out_rows)}")
    print(f"CSV: {CSV_OUT}")
    print(f"Strict below-B: {STRICT_BELOW_B_OUT}")
    print(f"Below-B backlog: {BELOW_B_OUT}")
    print(f"Live-test plan: {LIVE_TEST_PLAN_OUT}")
    print(f"Summary: {SUMMARY_OUT}")
    print(f"References: {REFS_OUT}")


if __name__ == "__main__":
    main()

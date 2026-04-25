"""Build R12 strict AAA terrain-generator audit.

This audit intentionally does not inherit the R11 "B-floor" optimism.  It
grades every parsed Python callable against strict research-backed terrain
generator evidence. If a callable lacks direct runtime wiring, direct tests,
and live/visual proof appropriate to its domain, it is downgraded.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from build_r11_research_aaa_callable_audit import (
    GRADE_RANK,
    ROOT,
    collect_callables,
    infer_domain,
    is_structural_support,
    load_wiring,
)


OUT_DIR = ROOT / "docs" / "aaa-audit"
CSV_OUT = OUT_DIR / "R12_STRICT_AAA_GENERATOR_AUDIT.csv"
SUMMARY_OUT = OUT_DIR / "R12_STRICT_AAA_GENERATOR_AUDIT_SUMMARY.md"
REFS_OUT = OUT_DIR / "R12_STRICT_RESEARCH_REFERENCES_2026_04_25.md"
BELOW_B_OUT = OUT_DIR / "R12_STRICT_BELOW_B_ACTION_PLAN.csv"
PLAN_OUT = OUT_DIR / "R12_STRICT_DOMAIN_REMEDIATION_PLAN.md"


RESEARCH_SOURCES = [
    {
        "id": "UE_PCG",
        "title": "Unreal Engine 5.6 Procedural Content Generation Framework",
        "url": "https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview?application_version=5.6",
        "applies": "Graph-driven generation, designer-facing controls, biome/asset workflows, deterministic runtime exposure.",
    },
    {
        "id": "UE_PCG_BIOME",
        "title": "Unreal Engine PCG Biome Core and Sample Plugins",
        "url": "https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-pcg-biome-core-and-sample-plugins-in-unreal-engine?application_version=5.6",
        "applies": "Attribute tables, feedback loops, recursive subgraphs, runtime hierarchical generation for biomes.",
    },
    {
        "id": "HOUDINI_ERODE",
        "title": "SideFX HeightField Erode",
        "url": "https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode.html",
        "applies": "Multi-scale hydraulic/thermal erosion, rainfall/weathering, erodability masks, sediment/debris/flow/flowdir outputs.",
    },
    {
        "id": "GAEA_EROSION2",
        "title": "QuadSpinner Gaea Erosion2",
        "url": "https://docs.gaea.app/reference/nodes/simulate/erosion2.html",
        "applies": "Advanced hydraulic erosion with downcutting, deposition, orographic effects, deterministic performance.",
    },
    {
        "id": "FROSTBITE_TERRAIN",
        "title": "Frostbite Battlefield 3 Terrain System",
        "url": "https://www.ea.com/frostbite/news/terrain-in-battlefield-3-a-modern-complete-and-scalable-system",
        "applies": "Hierarchy, high resolution at distance, realtime editing, procedural virtual texture cache, streaming/prioritization.",
    },
    {
        "id": "INFINIGEN",
        "title": "Princeton VL Infinigen",
        "url": "https://github.com/princeton-vl/infinigen",
        "applies": "Procedural natural-world generator with configurable cameras, generated assets/materials, fluid simulation, export paths.",
    },
    {
        "id": "SIMPLE_HYDROLOGY",
        "title": "SimpleHydrology",
        "url": "https://github.com/weigert/SimpleHydrology",
        "applies": "Particle hydrology extending hydraulic erosion to streams, pools, deterministic flooding, momentum/discharge maps.",
    },
    {
        "id": "WORLDENGINE",
        "title": "WorldEngine",
        "url": "https://github.com/Mindwerks/worldengine",
        "applies": "Plate simulation, rain shadow, erosion, humidity, permeability, Holdridge life-zone biomes.",
    },
    {
        "id": "MAPGEN2",
        "title": "Red Blob Games Mapgen2",
        "url": "https://www.redblobgames.com/maps/mapgen2/",
        "applies": "Polygon maps, water bodies, river networks, biome distribution, explicit design constraints.",
    },
    {
        "id": "FASTNOISELITE",
        "title": "FastNoise Lite",
        "url": "https://github.com/Auburn/FastNoiseLite/wiki/Documentation",
        "applies": "Seeded coherent noise, bounded outputs, frequency/noise-type controls, deterministic defaults.",
    },
]


DOMAIN_BEST_PRACTICES = {
    "terrain_shape": (
        "Use deterministic seeded coherent noise with macro/meso/micro layers; "
        "drive mountains/hills/flats/cliffs from explicit terrain family controls; "
        "apply multi-scale erosion/deposition masks; verify tiled seams and rendered landform readability."
    ),
    "cliffs": (
        "Generate cliff faces with strata/fracture/talus/outcrop masks; avoid heightmap-only vertical smearing; "
        "prove silhouette, scale, projection/triplanar materials, and foothill transitions in rendered goldens."
    ),
    "water": (
        "Carve beds/banks before water surfaces; solve basins/spillways/outflow; export flow/flowdir/sediment/wetness masks; "
        "verify seam continuity, held water levels, material margins, and live renders."
    ),
    "roads_paths": (
        "Route splines/paths against slope and obstacles; deform terrain with shoulders/drainage/worn blends; "
        "prove path continuity, biome-aware side dressing, and rendered road-to-terrain integration."
    ),
    "biome_transition": (
        "Use shared ecotone masks for height, materials, scatter, water, atmosphere, and gameplay; "
        "avoid abrupt scatter/material stops; verify transitions in multi-biome live scenes."
    ),
    "scatter_foliage": (
        "Use species catalogs, density falloffs, forest core/edge/sparse bands, slope/moisture/altitude constraints, "
        "LOD/instancing/export budgets, and rendered grass/tree variety proof."
    ),
    "materials": (
        "Use layered PBR terrain materials with triplanar/height blends, macro color breakup, wetness/sediment integration, "
        "texel-density checks, and engine/render import proof."
    ),
    "lod_streaming_export": (
        "Use world hierarchy, deterministic chunking, screen-error/LOD budgets, virtual texture/cache strategy, "
        "engine import smoke tests, and streaming performance gates."
    ),
    "validation_visual": (
        "Use rendered golden scenes, adjacent-tile seam proof, pixel/readability metrics, engine import gates, "
        "and fail-closed validator wiring."
    ),
    "tooling_wiring": (
        "Expose deterministic command/pass contracts with clear errors, no silent fallbacks, dispatch tests, "
        "and designer iteration surfaces comparable to PCG graph tools."
    ),
    "generic": (
        "Prove runtime relevance, deterministic behavior, direct tests, caller wiring, typed contracts, "
        "and no dead/orphan code before claiming generator quality."
    ),
}


DOMAIN_REFS = {
    "terrain_shape": "HOUDINI_ERODE|GAEA_EROSION2|WORLDENGINE|FASTNOISELITE|FROSTBITE_TERRAIN",
    "cliffs": "HOUDINI_ERODE|GAEA_EROSION2|INFINIGEN",
    "water": "HOUDINI_ERODE|GAEA_EROSION2|SIMPLE_HYDROLOGY|MAPGEN2",
    "roads_paths": "UE_PCG|HOUDINI_ERODE|FROSTBITE_TERRAIN",
    "biome_transition": "UE_PCG_BIOME|WORLDENGINE|MAPGEN2",
    "scatter_foliage": "UE_PCG|INFINIGEN|FROSTBITE_TERRAIN",
    "materials": "HOUDINI_ERODE|GAEA_EROSION2|INFINIGEN|FROSTBITE_TERRAIN",
    "lod_streaming_export": "FROSTBITE_TERRAIN|INFINIGEN",
    "validation_visual": "FROSTBITE_TERRAIN|INFINIGEN",
    "tooling_wiring": "UE_PCG|FROSTBITE_TERRAIN",
    "generic": "UE_PCG|FASTNOISELITE",
}


PRODUCT_DOMAINS = {
    "terrain_shape",
    "cliffs",
    "water",
    "roads_paths",
    "biome_transition",
    "scatter_foliage",
    "materials",
    "lod_streaming_export",
    "validation_visual",
}


def grade_min(left: str, right: str) -> str:
    return left if GRADE_RANK[left] <= GRADE_RANK[right] else right


def count_int(row: dict[str, str], key: str) -> int:
    try:
        return int(row.get(key, "0") or "0")
    except ValueError:
        return 0


def evidence(row, wiring_row: dict[str, str] | None) -> dict[str, bool | str]:
    status = wiring_row.get("status", "") if wiring_row else "missing_wiring_row"
    runtime = status in {"runtime_primary", "helper_reachable"}
    command_or_pass = status == "runtime_primary"
    tests = False
    non_test_calls = False
    if wiring_row:
        tests = any(
            count_int(wiring_row, key) > 0
            for key in ("test_direct_calls", "test_attr_calls", "test_attr_reads")
        )
        non_test_calls = any(
            count_int(wiring_row, key) > 0
            for key in ("non_test_direct_calls", "non_test_attr_calls", "non_test_attr_reads")
        )
    return {
        "status": status,
        "runtime": runtime,
        "command_or_pass": command_or_pass,
        "tests": tests,
        "non_test_calls": non_test_calls,
        # No row is allowed to claim live visual proof automatically. This is
        # intentionally strict; Blender/live artifacts must be attached by a
        # future audited visual-golden matrix.
        "live_visual": False,
        "engine_import": False,
    }


def remediation_for(domain: str, ev: dict[str, bool | str], support: bool) -> str:
    if not ev["runtime"]:
        return "WIRE_OR_DEPRECATE"
    if not ev["tests"]:
        return "ADD_DIRECT_TESTS"
    if domain in PRODUCT_DOMAINS and not ev["live_visual"]:
        return "ADD_LIVE_VISUAL_GOLDEN"
    if domain == "lod_streaming_export" and not ev["engine_import"]:
        return "ADD_ENGINE_IMPORT_OR_STREAMING_GATE"
    if support:
        return "PROVE_PARENT_CONTRACT_OR_INLINE"
    return "REVIEW_FOR_B"


def strict_grade(row, wiring_row: dict[str, str] | None) -> tuple[str, str, str]:
    if row.scope == "test":
        return "N/A", "test_callable", "Test/support callable, not a shipped generator item."

    domain = infer_domain(row)
    ev = evidence(row, wiring_row)
    support = is_structural_support(row)
    findings: list[str] = []

    if not wiring_row:
        grade = "D+"
        findings.append("No callable-wiring row; runtime path is unproven.")
    elif ev["status"] == "orphan_candidate":
        grade = "D+"
        findings.append("Wiring scan marks this as orphan_candidate.")
    elif ev["status"] in {"test_only_or_unwired", "uninvoked_registrar", "registrar_declared_only"}:
        grade = "C"
        findings.append(f"Wiring scan status is {ev['status']}; production path is not proven.")
    elif ev["runtime"] and ev["tests"]:
        grade = "C+"
        findings.append("Runtime/test evidence exists, but strict AAA evidence is incomplete.")
    elif ev["runtime"]:
        grade = "C"
        findings.append("Runtime path exists, but direct test evidence is missing.")
    else:
        grade = "D+"
        findings.append("No acceptable strict evidence was found.")

    if support:
        grade = grade_min(grade, "C+")
        findings.append("Structural/helper callable: cannot exceed C+ without direct contract tests and parent-surface proof.")

    if domain in PRODUCT_DOMAINS:
        if ev["runtime"] and ev["tests"] and ev["live_visual"]:
            grade = grade_min(grade, "B")
            findings.append("Live visual proof present.")
        else:
            grade = grade_min(grade, "C+")
            findings.append("Product terrain domain lacks attached live visual golden/render proof.")

    if domain == "lod_streaming_export" and not ev["engine_import"]:
        grade = grade_min(grade, "C+")
        findings.append("LOD/export domain lacks engine import or streaming gate proof.")

    if row.scope == "script":
        grade = grade_min(grade, "C+")
        findings.append("Script/tooling callable is capped without CI gate integration.")

    return grade, remediation_for(domain, ev, support), " ".join(findings)


def write_refs() -> None:
    lines = [
        "# R12 Strict AAA Terrain Research References - 2026-04-25",
        "",
        "Context7 was requested but no Context7 MCP/tool resource is exposed in this session; this audit uses web/GitHub primary-source research available to Codex.",
        "",
        "## Sources",
        "",
    ]
    for source in RESEARCH_SOURCES:
        lines.extend([
            f"### {source['id']}: {source['title']}",
            f"- URL: {source['url']}",
            f"- Audit standard: {source['applies']}",
            "",
        ])
    lines.extend([
        "## Strict Grade Rule",
        "",
        "- `B` requires runtime wiring, direct tests, and domain-appropriate live visual/engine proof for product terrain surfaces.",
        "- `C+` means the callable may be useful and tested, but lacks true AAA terrain-generator evidence.",
        "- `C` means runtime or production reachability is weak.",
        "- `D+` means orphaned/missing wiring/no acceptable strict evidence.",
        "",
    ])
    REFS_OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_refs()
    wiring = load_wiring()
    rows = collect_callables()
    fieldnames = [
        "File",
        "Qualified Name",
        "Function",
        "Line",
        "Kind",
        "Scope",
        "R12 Domain",
        "Research Refs",
        "Best Practice Baseline",
        "R12 Strict Grade",
        "R12 Remediation",
        "Wiring Status",
        "R12 Findings",
    ]
    out_rows: list[dict[str, str]] = []
    for row in rows:
        domain = infer_domain(row)
        wiring_row = wiring.get((Path(row.file).name, row.function))
        grade, remediation, findings = strict_grade(row, wiring_row)
        out_rows.append({
            "File": row.file,
            "Qualified Name": row.qualname,
            "Function": row.function,
            "Line": str(row.line),
            "Kind": row.kind,
            "Scope": row.scope,
            "R12 Domain": domain,
            "Research Refs": DOMAIN_REFS[domain],
            "Best Practice Baseline": DOMAIN_BEST_PRACTICES[domain],
            "R12 Strict Grade": grade,
            "R12 Remediation": remediation,
            "Wiring Status": wiring_row.get("status", "missing_wiring_row") if wiring_row else "missing_wiring_row",
            "R12 Findings": findings,
        })

    with CSV_OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    below_b = [
        row for row in out_rows
        if row["Scope"] != "test"
        and GRADE_RANK.get(row["R12 Strict Grade"], 99) < GRADE_RANK["B"]
    ]
    with BELOW_B_OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(below_b)

    by_grade = Counter(row["R12 Strict Grade"] for row in out_rows)
    by_non_test_grade = Counter(row["R12 Strict Grade"] for row in out_rows if row["Scope"] != "test")
    by_remediation = Counter(row["R12 Remediation"] for row in below_b)
    by_domain = Counter(row["R12 Domain"] for row in below_b)
    summary = [
        "# R12 Strict AAA Generator Audit Summary",
        "",
        f"- Total parsed Python callables/classes: `{len(out_rows)}`",
        f"- Non-test strict below-B rows: `{len(below_b)}`",
        f"- CSV: `{CSV_OUT.relative_to(ROOT)}`",
        f"- Below-B action plan: `{BELOW_B_OUT.relative_to(ROOT)}`",
        f"- References: `{REFS_OUT.relative_to(ROOT)}`",
        "",
        "## Grade Distribution",
        "",
    ]
    for grade, count in by_grade.most_common():
        summary.append(f"- `{grade}`: {count}")
    summary.extend(["", "## Non-Test Grade Distribution", ""])
    for grade, count in by_non_test_grade.most_common():
        summary.append(f"- `{grade}`: {count}")
    summary.extend(["", "## Below-B Remediation Distribution", ""])
    for remediation, count in by_remediation.most_common():
        summary.append(f"- `{remediation}`: {count}")
    summary.extend(["", "## Below-B Domain Distribution", ""])
    for domain, count in by_domain.most_common():
        summary.append(f"- `{domain}`: {count}")
    summary.extend([
        "",
        "## Bottom Line",
        "",
        "This strict audit rejects the previous provisional B-floor as a verified quality claim.",
        "No product terrain surface is allowed to keep B without direct runtime/test evidence and live visual or engine proof attached to the audit.",
    ])
    SUMMARY_OUT.write_text("\n".join(summary), encoding="utf-8")

    plan = [
        "# R12 Strict Domain Remediation Plan",
        "",
        "This is the implementation plan produced from the strict audit. It is intentionally not a grade inflation sheet.",
        "",
        "## Immediate Rule",
        "",
        "No product terrain callable returns to `B` until the audit row has runtime wiring, direct tests, and live visual or engine proof where applicable.",
        "",
        "## Work Waves",
        "",
        "1. `WIRE_OR_DEPRECATE`: remove dead/orphan generator surfaces or wire them into command/pass/runtime paths with fail-closed errors.",
        "2. `ADD_DIRECT_TESTS`: add deterministic unit/integration tests for every callable that remains reachable.",
        "3. `ADD_LIVE_VISUAL_GOLDEN`: build Blender/live golden scenes for water, mountains, cliffs, roads, scatter, materials, and biome transitions.",
        "4. `PROVE_PARENT_CONTRACT_OR_INLINE`: either prove helper behavior through parent-surface tests or inline/delete the helper.",
        "5. `REVIEW_FOR_B`: manually inspect remaining C+ rows after evidence is attached.",
        "",
        "## Domain Baselines",
        "",
    ]
    for domain, baseline in DOMAIN_BEST_PRACTICES.items():
        domain_rows = [row for row in below_b if row["R12 Domain"] == domain]
        if not domain_rows:
            continue
        remediation_counts = Counter(row["R12 Remediation"] for row in domain_rows)
        plan.append(f"### {domain} ({len(domain_rows)} below-B rows)")
        plan.append("")
        plan.append(f"Best practice: {baseline}")
        plan.append("")
        plan.append("Remediation counts:")
        for remediation, count in remediation_counts.most_common():
            plan.append(f"- `{remediation}`: {count}")
        plan.append("")
    PLAN_OUT.write_text("\n".join(plan), encoding="utf-8")

    print(f"R12 strict callables audited: {len(out_rows)}")
    print(f"Strict below-B non-test rows: {len(below_b)}")
    print(f"CSV: {CSV_OUT}")
    print(f"Below-B action plan: {BELOW_B_OUT}")
    print(f"Domain remediation plan: {PLAN_OUT}")
    print(f"Summary: {SUMMARY_OUT}")
    print(f"References: {REFS_OUT}")


if __name__ == "__main__":
    main()

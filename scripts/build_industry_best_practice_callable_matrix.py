"""Generate an industry-practice upgrade matrix for every terrain callable.

This is stricter than the grade-only upgrade path. Every discovered handler
callable receives a domain, best-practice contract, required setup rules,
anti-patterns to block, validation gates, and output artifacts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
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
except ModuleNotFoundError:
    from scripts.grade_audit_shared import (
        DEFAULT_GRADE_FILE,
        REPO_ROOT,
        build_grade_index,
        collect_callables,
        latest_grade,
        norm,
        read_grade_rows,
        resolve_grade_match,
    )


DATE_TAG = datetime.now(timezone.utc).strftime("%Y_%m_%d")
OUT_DIR = REPO_ROOT / "output" / "spreadsheet"
OUT_CSV = OUT_DIR / f"INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_{DATE_TAG}.csv"
OUT_MD = OUT_DIR / f"INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_{DATE_TAG}.md"
VERIFICATION_MATRIX = REPO_ROOT / "output" / "verification" / "CALLABLE_VERIFICATION_MATRIX.csv"
GUARDRAIL_REPORT = REPO_ROOT / "output" / "verification" / "TERRAIN_BEST_PRACTICE_GUARDRAIL_REPORT.json"

FIELDNAMES = [
    "file",
    "line",
    "callable",
    "kind",
    "domain",
    "subdomain",
    "criticality",
    "current_grade",
    "grade_status",
    "match_mode",
    "upgrade_tier",
    "verification_risk_level",
    "verification_evidence_types",
    "best_practice_authorities",
    "best_practice_contract",
    "when_to_use",
    "do_not_use_for",
    "required_callable_setup",
    "upgrade_actions",
    "validation_gates",
    "anti_patterns_to_block",
    "required_output_artifacts",
    "implementation_phase",
]


def _repo_relative_posix(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

A_GRADES = {"A+", "A", "A-"}
B_GRADES = {"B+", "B", "B-"}


DOMAIN_RULES = {
    "terrain_pipeline": {
        "authorities": "Houdini heightfield layers;Gaea build graph/ports;World Machine device graph;Unreal PCG graph debug",
        "contract": "All generation routes through canonical pass DAG with typed inputs, produced/consumed channels, seed provenance, and manifest output.",
        "when": "Use when orchestrating terrain passes, registering handlers, validating dependencies, checkpointing, or emitting build provenance.",
        "not": "Do not use for direct mesh/material/scatter authoring unless it calls the proper domain callable.",
        "setup": "Register callable behind handler/MCP surface only when it has contract docs, tests, and manifest provenance.",
        "actions": "Remove bypass paths; add pass dependency tests; require TerrainMaskStack or typed manifest input/output.",
        "gates": "contract_tests|dispatch_tests|callable_census|determinism|manifest_schema",
        "block": "one_shot_scene_build|hidden_global_state|unregistered_handler|spreadsheet_grade_without_test",
        "artifacts": "pass_dag.json|terrain_generation_manifest.json|callable_provenance.json",
        "phase": "Phase 0-1",
        "criticality": "critical",
    },
    "heightfield_geomorph": {
        "authorities": "Houdini HeightField Erode/Mask by Feature;Gaea Erosion2;World Machine erosion/thermal erosion",
        "contract": "Heightfield operations preserve meter units, emit masks/layers for erosion, deposits, sediment, flow, slope, curvature, talus, and strata.",
        "when": "Use when modifying terrain elevation, deriving landform masks, erosion/weathering, cliffs, caves, strata, talus, or geology features.",
        "not": "Do not use to fake final material color, scatter props, or create water surfaces without hydrology contracts.",
        "setup": "Inputs must declare cell size, units, seed, edge policy, and region/tile context.",
        "actions": "Emit reusable physical layers; validate mass/height ranges; add seam tests for tiled execution.",
        "gates": "unit_tests|mass_or_range_checks|tile_seam_tests|golden_heightfield",
        "block": "normalized_height_without_units|destructive_height_mutation_without_delta|visual_only_landform",
        "artifacts": "height_m.exr|erosion_wear.exr|deposition.exr|sediment.exr|talus_mask.exr|strata_mask.exr",
        "phase": "Phase 1,7",
        "criticality": "critical",
    },
    "hydrology": {
        "authorities": "World Machine water depth/velocity;Houdini flow layers;Gaea flow/wear/deposits;World Creator river graph",
        "contract": "Water systems expose surface elevation, depth, flow direction, velocity/speed, accumulation, discharge, foam, mist, wetness, and seam continuity.",
        "when": "Use when creating or validating rivers, lakes, basins, wetlands, waterfalls, foam, mist, caustics, flow direction, velocity, or water export metadata.",
        "not": "Do not use for decorative flat planes, terrain-only valleys, or foliage placement except through derived wetness/water-edge masks.",
        "setup": "Every water callable declares cell size, water units, downhill convention, edge contracts, and depth semantics.",
        "actions": "Split water_mask into physical channels; wire graph segments; test braided/confluence/seam cases.",
        "gates": "hydrology_contract|depth_tests|velocity_tests|flow_direction_tests|seam_continuity|swimmable_depth",
        "block": "flat_water_plane_only|single_water_mask_as_depth|radial_foam_without_flow|paper_thin_river",
        "artifacts": "water_surface_elevation_m.exr|water_depth_m.exr|flow_direction_xy.exr|flow_speed_mps.exr|foam_mask.exr|mist_mask.exr",
        "phase": "Phase 2-3",
        "criticality": "critical",
    },
    "scatter_ecology": {
        "authorities": "World Creator InstanceInfo/DetailInfo;Unreal PCG point data;Blender Geometry Nodes point scatter;Maya Bifrost/XGen",
        "contract": "Scatter emits typed point tables with position, normal, orient, scale, density, seed, prototype, species, biome, masks, LOD, and wind metadata.",
        "when": "Use when distributing foliage, rocks, props, debris, wildlife hints, biome details, exact instances, or dense detail layers.",
        "not": "Do not use for asset generation, material blending, or terrain shaping; consume those domains as masks/prototypes instead.",
        "setup": "Callable must choose exact-instance or dense-detail mode and record all source masks and exclusions.",
        "actions": "Canonicalize scatter path; convert provider/import formats to ScatterPointTable; enforce runtime altitude/slope/water checks.",
        "gates": "point_schema|density_stats|blue_noise_or_distribution|collision_or_exclusion|asset_manifest|lod_budget",
        "block": "copy_pasted_meshes|hidden_random_scatter|scatter_without_provenance|audit_only_safety",
        "artifacts": "scatter_points.parquet|scatter_manifest.json|detail_splatmaps|instance_pointcloud.csv",
        "phase": "Phase 4,9B",
        "criticality": "critical",
    },
    "foliage_assets": {
        "authorities": "SpeedTree generators/zones/LOD/billboards/wind;Maya XGen descriptions;World Creator object collections",
        "contract": "Vegetation assets declare species, biome constraints, scale, slope/wetness tolerance, LODs, billboard/impostor strategy, wind, collision, and fallback status.",
        "when": "Use when selecting, validating, cataloging, or resolving vegetation/prop prototypes for scatter and export.",
        "not": "Do not use to place instances directly or bypass scatter point-table validation.",
        "setup": "Generated or imported assets enter only through provider-neutral catalog validation.",
        "actions": "Cover catalog callables; validate LOD/wind/PBR metadata; separate prototype records from scatter instances.",
        "gates": "asset_schema|lod_paths|impostor_presence|wind_profile|scale_axis_validation|catalog_resolution",
        "block": "provider_specific_runtime_logic|raw_asset_without_lod|speciesless_asset|unbounded_scale",
        "artifacts": "asset_manifest.json|prototype_catalog.json|lod_report.json",
        "phase": "Phase 5",
        "criticality": "high",
    },
    "terrain_texturing": {
        "authorities": "Houdini texture layers;Adobe Substance material graphs;Quixel/Megascans PBR;Unreal/Unity height blends",
        "contract": "Texture layers separate normalized material weights from PBR maps, color space, height blending, tiling, texel density, weathering, and displacement policy.",
        "when": "Use when building terrain material weights, splatmaps, PBR maps, Substance/Quixel-style layers, shader metadata, or texture QA.",
        "not": "Do not use to change terrain height, scatter assets, or hide missing hydrology/geology channels behind color noise.",
        "setup": "Callable must preserve base color, normal, roughness, height/displacement, AO, metallic/mask maps, color-space metadata, and source masks.",
        "actions": "Add TerrainTextureLayerStack; wire Substance/Quixel-style maps; validate non-color data and height-blend inputs.",
        "gates": "pbr_channel_presence|weight_sum|texel_density|color_space|normal_map|height_blend|visual_debug_maps",
        "block": "flat_color_only|slope_only_texture_selection|missing_normal_roughness_height_ao|wrong_color_space",
        "artifacts": "material_weights.exr|base_color.png|normal.png|roughness.png|height.png|ao.png|texture_manifest.json",
        "phase": "Phase 6,9C,9D",
        "criticality": "critical",
    },
    "mesh_blender": {
        "authorities": "Blender Python API;Blender Geometry Nodes named attributes;Blender MCP execution pattern",
        "contract": "Blender operations expose typed recipes for heightfield meshes, named attributes, materials, scatter instances, water layers, screenshots, and scene-read QA.",
        "when": "Use when applying validated terrain artifacts inside Blender, reading scene state, creating mesh attributes, importing GLB, or capturing visual proof.",
        "not": "Do not use raw bpy as the primary procedural terrain generator when a typed pipeline/domain callable should own the logic.",
        "setup": "Raw bpy execution is debug/admin only; production callables need typed payload schemas and audit logs.",
        "actions": "Add recipe-level MCP handlers; validate scene state after each recipe; log screenshots and changed objects.",
        "gates": "dispatch_tests|blender_optional_tests|scene_read_contract|screenshot_qa|attribute_presence",
        "block": "unchecked_raw_bpy|silent_scene_mutation|missing_named_attributes|no_screenshot_proof",
        "artifacts": "blender_recipe_log.json|scene_contract.json|viewport_capture.png|attribute_report.json",
        "phase": "Phase 9",
        "criticality": "high",
    },
    "pathing_roads": {
        "authorities": "World Creator path/river splines;Unreal PCG graphs;cost-field road planning",
        "contract": "Paths and roads use cost fields with slope, curvature, water crossings, bridges/fords, road class, and cell-size-aware grading.",
        "when": "Use when generating roads, paths, bridges, fords, navmesh traversal, splines, or path masks.",
        "not": "Do not use as generic river generation or terrain erosion; hand off water intersections to hydrology.",
        "setup": "Callable declares coordinate units, cell size, slope budget, traversal class, and crossing policy.",
        "actions": "Route production roads through rich road network; demote legacy A* to fallback; add bridge/ford contracts.",
        "gates": "path_cost_tests|cell_size_tests|slope_budget|water_crossing|determinism",
        "block": "legacy_astar_as_primary|unitless_grade|road_water_overlap_without_bridge|line_carve_only",
        "artifacts": "road_graph.json|path_spline.dae|road_mask.exr|crossing_manifest.json",
        "phase": "Phase 8",
        "criticality": "high",
    },
    "external_ai_assets": {
        "authorities": "Hyper3D Rodin API;provider-neutral asset pipeline;PBR asset validation",
        "contract": "AI asset providers are replaceable async sources whose outputs pass mesh, scale, UV, PBR, texture, collision, LOD, and license validation before cataloging.",
        "when": "Use when submitting, polling, downloading, validating, or ingesting external AI-generated 3D asset packages such as Rodin outputs.",
        "not": "Do not use to generate terrain heightfields, water networks, material weights, scatter maps, or direct scene placement.",
        "setup": "Callable never lets provider output bypass terrain, scatter, material, or Blender safety contracts.",
        "actions": "Add provider-neutral interface; optional Rodin adapter; package inspection; catalog ingestion after validation.",
        "gates": "async_state_tests|download_schema|mesh_validation|pbr_validation|scale_axis|license_metadata",
        "block": "provider_specific_core_logic|unvalidated_generated_glb|asset_direct_to_scene|missing_license_source",
        "artifacts": "external_asset_task.json|asset_validation_report.json|catalog_entry.json",
        "phase": "Phase 9E",
        "criticality": "medium",
    },
    "export_runtime": {
        "authorities": "Unity TerrainData/Terrain Lit;World Creator export contracts;World Machine tiled exports;USD/DCC manifest practices",
        "contract": "Exports preserve height, masks, point tables, material layers, water data, LODs, prototypes, instances, shader metadata, and QA reports.",
        "when": "Use when writing Unity/engine/DCC manifests, packed maps, runtime metadata, shader inputs, particle specs, or round-trip export proof.",
        "not": "Do not use to invent missing source channels at export time; fail if upstream artifacts are absent.",
        "setup": "Callable writes structured manifests with units, ranges, channel names, scale factors, and consumer-specific packing rules.",
        "actions": "Cover export helpers; validate Unity/Blender manifests; add packed texture/channel semantics.",
        "gates": "manifest_schema|unity_contract|scale_factor|roundtrip_read|artifact_presence",
        "block": "export_without_units|beauty_only_export|lost_pbr_channels|lost_scatter_prototypes",
        "artifacts": "unity_manifest.json|terrain_generation_manifest.json|water_shader_manifest.json|particle_emitters.json",
        "phase": "Phase 10",
        "criticality": "critical",
    },
    "validation_qa": {
        "authorities": "Unreal PCG debug;Houdini node/layer inspection;visual diff/golden QA;contract-first CI",
        "contract": "Validation callables must prove channels, scene state, artifacts, determinism, visual output, performance, and low-spec compatibility.",
        "when": "Use when checking correctness, quality, determinism, performance, golden snapshots, scene readback, issue codes, or release readiness.",
        "not": "Do not use as a substitute for fixing missing domain outputs; validators should fail closed.",
        "setup": "Callable must emit explicit issue codes and fail closed for missing proof.",
        "actions": "Convert heuristic checks to measurable gates; add golden snapshots; add channel debug renders.",
        "gates": "issue_codes|golden_visual|performance_budget|determinism|low_spec|artifact_schema",
        "block": "warning_only_for_blockers|screenshot_without_channel_manifest|unmeasured_quality_claim",
        "artifacts": "qa_report.json|golden_snapshot_manifest.json|visual_diff.png|channel_debug_contact_sheet.png",
        "phase": "Phase 11-12",
        "criticality": "critical",
    },
    "generic": {
        "authorities": "General production Python;contract-first procedural pipelines",
        "contract": "Callable has typed inputs, deterministic behavior where applicable, clear invariants, direct tests, and no hidden production bypass.",
        "when": "Use only for small shared helpers or compatibility functions after checking whether a specific terrain domain callable is more appropriate.",
        "not": "Do not let generic helpers become production terrain behavior without a domain contract and tests.",
        "setup": "Add direct behavior tests, edge cases, invalid input tests, and integration tests if exposed.",
        "actions": "Document invariants; add coverage; connect to a domain contract or mark internal/compatibility.",
        "gates": "direct_tests|invalid_input|determinism_when_seeded|coverage|integration_if_exposed",
        "block": "untested_helper|silent_exception|ambiguous_units|hidden_side_effects",
        "artifacts": "test_evidence|callable_matrix_row",
        "phase": "Phase 0",
        "criticality": "medium",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grade-file", type=Path, default=DEFAULT_GRADE_FILE)
    return parser.parse_args()


def _contains(token: str, keys: Iterable[str]) -> bool:
    return any(key in token for key in keys)


def classify(file_name: str, callable_name: str) -> tuple[str, str]:
    token = f"{file_name.lower()}::{callable_name.lower()}"
    if "terrain_scatter_points.py" in token:
        return "scatter_ecology", "point_distribution"
    if "terrain_path_contracts.py" in token:
        return "pathing_roads", "path_network"
    if _contains(token, ["unity", "export", "manifest", "raw", "shader_manifest", "particle_emitter"]):
        return "export_runtime", "engine_export"
    if _contains(token, ["visual", "qa", "diff", "golden", "validate", "audit", "quality", "determin", "readiness", "linter", "saliency"]):
        return "validation_qa", "quality_gate"
    if _contains(token, ["water", "river", "coast", "lake", "pool", "foam", "mist", "drainage", "hydro", "flow", "discharge", "caustic", "wet_rock", "waterfall"]):
        return "hydrology", "water_system"
    if _contains(token, ["material", "texture", "shader", "palette", "quixel", "substance", "pbr", "roughness", "normal", "height_blend", "macro_color", "stochastic"]):
        return "terrain_texturing", "material_layering"
    if _contains(token, ["scatter", "vegetation", "foliage", "wildlife", "ecotone", "biome", "grass", "tree", "lsystem"]):
        if _contains(token, ["catalog", "asset", "lod", "impostor", "billboard", "species"]):
            return "foliage_assets", "asset_catalog"
        return "scatter_ecology", "point_distribution"
    if _contains(token, ["asset", "model", "gltf", "glb", "fbx", "rodin", "external_model"]):
        return "external_ai_assets", "asset_provider"
    if _contains(token, ["blender", "bpy", "bmesh", "viewport", "scene_read", "mcp", "mesh_object"]):
        return "mesh_blender", "dcc_bridge"
    if _contains(token, ["mesh", "lod", "uv", "vertex", "normal", "tangent", "sdf", "boolean"]):
        return "mesh_blender", "mesh_quality"
    if _contains(token, ["road", "navmesh", "path", "astar", "bridge", "clothoid"]):
        return "pathing_roads", "path_network"
    if _contains(token, ["erosion", "weather", "strata", "geology", "karst", "glacial", "cliff", "cave", "talus", "repose", "noise", "fbm", "terrain_world", "height", "slope", "curvature"]):
        return "heightfield_geomorph", "landform_layers"
    if _contains(token, ["bundle", "pipeline", "pass", "registr", "checkpoint", "protocol", "controller", "mask_stack", "twelve_step", "region"]):
        return "terrain_pipeline", "orchestration"
    return "generic", "general"


def grade_status(grade: str, verification_risk: str = "") -> str:
    if verification_risk == "LOW":
        return "VERIFIED_LOW_RISK"
    if not grade:
        return "MISSING_GRADE"
    if grade in A_GRADES:
        return "LOCK_WITH_REGRESSION_GATES"
    if grade in B_GRADES:
        return "UPGRADE_FROM_B_RANGE"
    return "BLOCKER_OR_LOW_GRADE"


def upgrade_tier(grade: str, domain: str, verification_risk: str = "") -> str:
    if verification_risk == "LOW":
        return "P3"
    if domain in {"hydrology", "terrain_texturing", "export_runtime", "validation_qa", "terrain_pipeline"} and grade not in A_GRADES:
        return "P0"
    if not grade:
        return "P0"
    if grade in {"F", "D", "D+", "C-", "C", "C+"}:
        return "P0"
    if grade in B_GRADES:
        return "P1"
    return "P3"


def load_verification_index(path: Path = VERIFICATION_MATRIX) -> dict[tuple[str, str], dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    out: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        file_name = norm(row.get("File", ""))
        callable_name = norm(row.get("Callable", ""))
        if file_name and callable_name:
            out[(file_name, callable_name)] = row
    return out


def main() -> int:
    args = parse_args()
    grade_file = args.grade_file
    if not grade_file.is_absolute():
        grade_file = (REPO_ROOT / grade_file).resolve()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    grade_index = build_grade_index(read_grade_rows(grade_file))
    verification_index = load_verification_index()
    callables = collect_callables(include_init=True)

    rows: list[dict[str, str | int]] = []
    by_domain: Counter[str] = Counter()
    by_tier: Counter[str] = Counter()
    by_status: Counter[str] = Counter()

    for callable_def in sorted(callables, key=lambda item: (item.file, item.lineno, item.qualified_name)):
        match = resolve_grade_match(callable_def, grade_index)
        matched_row = match.row or {}
        grade = latest_grade(matched_row)
        verification_row = verification_index.get((callable_def.file, callable_def.qualified_name), {})
        verification_risk = norm(verification_row.get("RiskLevel", ""))
        verification_evidence = norm(verification_row.get("EvidenceTypes", ""))
        domain, subdomain = classify(callable_def.file, callable_def.qualified_name)
        rule = DOMAIN_RULES[domain]
        status = grade_status(grade, verification_risk)
        tier = upgrade_tier(grade, domain, verification_risk)
        by_domain[domain] += 1
        by_tier[tier] += 1
        by_status[status] += 1

        weakness = norm(matched_row.get("Weakness", ""))
        upgrade = norm(matched_row.get("Upgrade", ""))
        upgrade_actions = rule["actions"]
        if weakness:
            upgrade_actions += f" Existing weakness to resolve: {weakness}"
        if upgrade:
            upgrade_actions += f" Prior audit hint: {upgrade}"

        rows.append(
            {
                "file": callable_def.file,
                "line": callable_def.lineno,
                "callable": callable_def.qualified_name,
                "kind": callable_def.kind,
                "domain": domain,
                "subdomain": subdomain,
                "criticality": rule["criticality"],
                "current_grade": grade,
                "grade_status": status,
                "match_mode": match.match_mode,
                "upgrade_tier": tier,
                "verification_risk_level": verification_risk,
                "verification_evidence_types": verification_evidence,
                "best_practice_authorities": rule["authorities"],
                "best_practice_contract": rule["contract"],
                "when_to_use": rule["when"],
                "do_not_use_for": rule["not"],
                "required_callable_setup": rule["setup"],
                "upgrade_actions": upgrade_actions,
                "validation_gates": rule["gates"],
                "anti_patterns_to_block": rule["block"],
                "required_output_artifacts": rule["artifacts"],
                "implementation_phase": rule["phase"],
            }
        )

    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    csv_fingerprint = _sha256_file(OUT_CSV)
    lines = [
        "# Industry Best-Practice Callable Matrix",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        "- Tool: `scripts/build_industry_best_practice_callable_matrix.py`",
        "- Coverage scope: `industry_best_practice_matrix`",
        "- Inclusion rules: one row per live callable discovered by `collect_callables()` and joined to grade/verification evidence; generated output folders are excluded.",
        f"- Grade source: `{_repo_relative_posix(grade_file)}`",
        f"- Source inventory artifact: `{_repo_relative_posix(GUARDRAIL_REPORT)}`",
        f"- Source inventory fingerprint: `sha256:{csv_fingerprint}`",
        f"- Total callables covered: **{len(rows)}**",
        f"- Output CSV: `{_repo_relative_posix(OUT_CSV)}`",
        "- Reconciliation note: callable-census and guardrail totals can differ when non-matrix or generated callables are excluded by their own scopes.",
        "",
        "## Upgrade Tiers",
        "",
    ]
    for tier, count in sorted(by_tier.items()):
        lines.append(f"- {tier}: {count}")

    lines.extend(["", "## Grade Status", ""])
    for status, count in by_status.most_common():
        lines.append(f"- {status}: {count}")

    lines.extend(["", "## Domain Coverage", ""])
    for domain, count in by_domain.most_common():
        rule = DOMAIN_RULES[domain]
        lines.append(f"- {domain}: {count} callables; gates `{rule['gates']}`; phase {rule['phase']}")

    lines.extend(
        [
            "",
            "## Required Use",
            "",
            "Every terrain implementation worker must consult the CSV row for each callable they touch.",
            "A callable is not complete until its row's contract, setup, validation gates, anti-pattern blockers, and required artifacts are satisfied or explicitly documented as not applicable with a test.",
            "P0 rows are blockers. P1 rows are quality upgrades. P3 rows are regression-lock rows and must not be weakened.",
        ]
    )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"wrote {OUT_CSV}")
    print(f"wrote {OUT_MD}")
    print(f"covered {len(rows)} callables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

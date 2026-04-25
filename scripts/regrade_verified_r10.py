"""Add a current R10 verification/regrade pass to GRADES_VERIFIED.csv.

The R10 pass is intentionally conservative: historical AAA claims are carried
forward only when the current callable still exists, wiring exposure is known,
and line evidence is not stale. It does not overwrite older audit columns.
"""

from __future__ import annotations

import ast
import csv
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "docs" / "aaa-audit" / "GRADES_VERIFIED.csv"
WIRING_PATH = ROOT / "output" / "spreadsheet" / "CALLABLE_WIRING_AUDIT_2026_04_19.csv"
HANDLERS = ROOT / "veilbreakers_terrain" / "handlers"

R10_GRADE = "R10 GPT-5.5 AAA Regrade"
R10_STATUS = "R10 Verification Status"
R10_NOTES = "R10 Notes"

GRADE_ORDER = ["F", "D-", "D", "D+", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+"]
GRADE_RANK = {g: i for i, g in enumerate(GRADE_ORDER)}
GRADE_RE = re.compile(r"\b(A\+|A-|A|B\+|B-|B|C\+|C-|C|D\+|D-|D|F)\b")


def parse_grade(*values: str) -> str:
    for value in values:
        match = GRADE_RE.search(value or "")
        if match:
            return match.group(1)
    return "C+"


def cap_grade(grade: str, cap: str) -> str:
    if GRADE_RANK.get(grade, 0) <= GRADE_RANK[cap]:
        return grade
    return cap


def line_map() -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for path in HANDLERS.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        rel = path.name
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out[(rel, node.name)] = int(node.lineno)
    return out


def tracked_files() -> set[str]:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "veilbreakers_terrain/handlers/*.py"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
    except Exception:
        return set()
    return {Path(line.strip()).name for line in proc.stdout.splitlines() if line.strip()}


def wiring_rows() -> dict[tuple[str, str], dict[str, str]]:
    if not WIRING_PATH.exists():
        return {}
    with WIRING_PATH.open(newline="", encoding="utf-8-sig") as handle:
        return {
            (row["file"], row["function"]): row
            for row in csv.DictReader(handle)
        }


SPECIAL_REGRADES: dict[tuple[str, str], tuple[str, str]] = {
    ("_terrain_world.py", "generate_world_heightmap"): ("B", "Live/AAA comparator: spectral composition exists, but current mountains/cliffs/hills still read as procedural noise rather than art-directed terrain; no golden render proof."),
    ("_terrain_world.py", "pass_macro_world"): ("A-", "AAA comparator: strong macro generator; continental bias is not a tectonic/river-basin model."),
    ("_terrain_world.py", "pass_generate_high_freq_detail"): ("B+", "AAA comparator: useful high-frequency detail; not geology/material-aware micro-displacement."),
    ("_terrain_world.py", "pass_composite_hmap"): ("A-", "AAA comparator: clean low/high recomposition; needs mask-aware suppression for roads/water/hero zones."),
    ("_terrain_world.py", "pass_erosion"): ("A-", "AAA comparator: analytical, hydraulic, thermal, and stream-power erosion; still CPU/offline rather than Gaea/Houdini-interactive."),
    ("_terrain_erosion.py", "apply_hydraulic_erosion_masks"): ("A-", "AAA comparator: good masked droplet solver; not a GPU/grid water-sediment simulation."),
    ("_terrain_erosion.py", "compute_stream_power_erosion"): ("A-", "AAA comparator: strong stream-power implementation; needs tiled basin/reference DEM validation."),
    ("_water_network.py", "priority_flood_d8"): ("A-", "AAA comparator: tested priority-flood hydrology; needs larger tiled watershed validation."),
    ("_water_network.py", "detect_lakes"): ("A-", "AAA comparator: improved lake detection; lacks persistent lake volume/seasonal spillway lifecycle."),
    ("_water_network.py", "detect_waterfalls"): ("A-", "AAA comparator: good candidate logic; not a complete fluid/mesh cascade generator."),
    ("terrain_waterfalls.py", "pass_waterfalls"): ("A-", "AAA comparator: strong waterfall pass; water still mostly masks/metadata, not full volumetric authoring."),
    ("terrain_water_variants.py", "pass_water_variants"): ("B+", "AAA comparator: broad water variants; detector fallback and partial hot-spring/braided wiring cap confidence."),
    ("terrain_materials_v2.py", "default_dark_fantasy_rules"): ("B+", "AAA comparator: five terrain channels; needs richer scanned PBR layer stack and texture-array proof."),
    ("terrain_materials_v2.py", "compute_slope_material_weights"): ("B+", "AAA comparator: vectorized/tested weights; hard gates and placeholder perturbation cap shader quality."),
    ("terrain_materials_v2.py", "pass_materials"): ("A-", "AAA comparator: active material pass; needs engine import/render validation before A."),
    ("environment_scatter.py", "_scatter_pass"): ("A-", "AAA comparator: strong species Poisson and constraints; lacks GPU/HISM chunking and ecological feedback."),
    ("environment_scatter.py", "handle_scatter_vegetation"): ("B+", "AAA comparator: public handler fixed to preserve concrete species; handler-scale Blender loops cap production grade."),
    ("vegetation_system.py", "compute_vegetation_placement"): ("B+", "AAA comparator: good placement logic; normalized-height assumptions and brute-force sampling cap grade."),
    ("vegetation_system.py", "scatter_biome_vegetation"): ("B+", "AAA comparator: ecotone support; max-instance truncation and missing chunked batching cap grade."),
    ("lod_pipeline.py", "decimate_preserving_silhouette"): ("A-", "AAA comparator: QEM-based LOD; lacks meshoptimizer/Nanite-style screen-error proof."),
    ("lod_pipeline.py", "generate_lod_chain"): ("A-", "AAA comparator: good asset LOD chain; not terrain clipmap/streaming LOD."),
    ("terrain_horizon_lod.py", "pass_horizon_lod"): ("A-", "AAA comparator: wired horizon helper; not a complete terrain streaming system."),
    ("terrain_unity_export.py", "export_unity_manifest"): ("A-", "AAA comparator: comprehensive Unity export; still needs Unity import/render smoke as ship evidence."),
    ("terrain_validation.py", "validate_tile_seam_continuity"): ("B+", "AAA comparator: neighbor seam checks exist; needs adjacent-tile golden tests across erosion/material/scatter outputs."),
    ("terrain_validation.py", "pass_validation_full"): ("A-", "AAA comparator: active validation suite; visual/engine import gates are not required yet."),
    ("environment.py", "handle_generate_terrain_tile"): ("B", "Live/AAA comparator: runtime tile generation is wired, but current visible mountains/cliffs/hills/flat regions are not AAA-shaped; needs visual goldens and landform art direction."),
    ("environment.py", "handle_generate_world_terrain"): ("B", "Live/AAA comparator: orchestration works, but output quality is still below AAA procedural terrain without terrain-family visual acceptance tests."),
    ("environment.py", "_apply_river_profile_to_heightmap"): ("B+", "Live/AAA comparator: carves a thalweg and banks, but still needs proof against visible river-bank renders and multi-tile water integration."),
    ("environment.py", "_build_level_water_surface_from_terrain"): ("B", "Live/AAA comparator: derives a terrain mask, but level water can still read like a sheet unless paired with basin carving and shoreline proof."),
    ("environment.py", "handle_carve_water_basin"): ("B+", "Live/AAA comparator: priority-flood basin/rim/outflow logic exists, but lake hold/spillway visuals need render-backed verification."),
    ("environment.py", "handle_create_water"): ("B+", "Live/AAA comparator: path rivers now auto-carve banks when terrain_name is supplied, but sheet-water regressions remain possible for level/fallback water without basin proof."),
    ("environment.py", "handle_carve_river"): ("B+", "Live/AAA comparator: river carving is wired and banked, but stream/rivulet visual integration, material wet edges, and multi-tile proof are not AAA yet."),
    ("environment.py", "handle_generate_road"): ("B+", "Live/AAA comparator: road/path grading is wired, but believable worn edges, terrain-material blending, and path-to-biome transition renders are not proven."),
    ("environment.py", "_paint_road_mask_on_terrain"): ("B", "Live/AAA comparator: writes a path mask, but mask painting alone does not prove natural path shoulders or texture blending."),
    ("environment.py", "_apply_road_profile_to_heightmap"): ("B", "Live/AAA comparator: road profile deforms terrain, but needs render proof for embankments, drainage, and non-abrupt shoulders."),
    ("_terrain_depth.py", "generate_cliff_face_mesh"): ("B", "Live/AAA comparator: cliff mesh generator has strata/UV intent, but live cliffs/mountains still read weak without integrated terrain shaping and material proof."),
    ("_terrain_depth.py", "detect_cliff_edges"): ("B", "Live/AAA comparator: detects steep edges, but cliff placement/transition quality is not visually proven."),
    ("_terrain_depth.py", "generate_biome_transition_mesh"): ("B", "Live/AAA comparator: transition mesh/SDF exists, but forest/environment start-stop smoothing is not proven in the runtime world scatter path."),
}

KNOWN_FAILURE_CAPS: dict[tuple[str, str], tuple[str, str]] = {
    ("animation_environment.py", "generate_trap_trigger_keyframes"): ("C+", "Known execution-audit behavior failure."),
    ("terrain_chunking.py", "compute_chunk_lod"): ("C", "Known API drift in execution audit."),
    ("terrain_checkpoints.py", "save_checkpoint"): ("C+", "Known checkpoint output/I/O failure."),
    ("_terrain_noise.py", "generate_heightmap"): ("B-", "Known severe performance miss."),
    ("terrain_banded.py", "pass_banded_macro"): ("C+", "Known numeric invariant failures."),
    ("terrain_materials.py", "compute_world_splatmap_weights"): ("C+", "Known behavior drift."),
    ("terrain_saliency.py", "pass_saliency_refine"): ("C+", "Known noop semantics drift."),
    ("terrain_karst.py", "pass_karst"): ("D+", "Runtime pass remains low-grade until karst pipeline is upgraded."),
    ("terrain_glacial.py", "pass_glacial"): ("C", "Runtime pass remains degraded without R9/current verification."),
}

NEW_ROWS = [
    ("_terrain_world.py", "pass_generate_low_freq_hmap"),
    ("_terrain_world.py", "pass_generate_high_freq_detail"),
    ("_terrain_world.py", "pass_composite_hmap"),
    ("_terrain_erosion.py", "compute_stream_power_erosion"),
    ("_water_network.py", "priority_flood_d8"),
    ("terrain_waterfalls.py", "pass_emit_particle_systems"),
    ("blender_capability_bridge.py", "bmesh_op"),
    ("blender_capability_bridge.py", "modifier_add"),
    ("blender_capability_bridge.py", "modifier_apply"),
    ("blender_capability_bridge.py", "modifier_remove"),
    ("blender_capability_bridge.py", "modifier_list"),
    ("blender_capability_bridge.py", "uv_project"),
    ("blender_capability_bridge.py", "set_render_engine"),
    ("blender_capability_bridge.py", "render_still"),
    ("blender_capability_bridge.py", "collection_create"),
    ("blender_capability_bridge.py", "collection_link_object"),
    ("blender_capability_bridge.py", "parent_set"),
    ("blender_capability_bridge.py", "empty_create"),
    ("blender_capability_bridge.py", "geometry_nodes_create_group"),
    ("blender_capability_bridge.py", "geometry_nodes_add_node"),
    ("blender_capability_bridge.py", "geometry_nodes_link_sockets"),
    ("blender_capability_bridge.py", "geometry_nodes_assign_to_object"),
    ("blender_capability_bridge.py", "geometry_nodes_dump"),
    ("blender_capability_bridge.py", "addon_enable"),
    ("blender_capability_bridge.py", "addon_disable"),
]


def main() -> None:
    lines = line_map()
    tracked = tracked_files()
    wiring = wiring_rows()

    with CSV_PATH.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for col in (R10_GRADE, R10_STATUS, R10_NOTES):
        if col not in fieldnames:
            fieldnames.append(col)

    seen = {(row.get("File", ""), row.get("Function", "")) for row in rows}
    next_index = max(int(row.get("#") or 0) for row in rows) + 1 if rows else 1
    for file_name, function in NEW_ROWS:
        if (file_name, function) in seen:
            continue
        row = {name: "" for name in fieldnames}
        row["#"] = str(next_index)
        row["File"] = file_name
        row["Function"] = function
        row["Line"] = str(lines.get((file_name, function), ""))
        row["AAA Equivalent"] = "AAA terrain/runtime callable comparator"
        row["Severity"] = "important"
        rows.append(row)
        seen.add((file_name, function))
        next_index += 1

    updates = 0
    degraded = 0
    for row in rows:
        key = (row.get("File", ""), row.get("Function", ""))
        file_name, function = key
        base = parse_grade(
            row.get("R9 Phase7-14 Consensus", ""),
            row.get("FINAL GRADE", ""),
            row.get("R8 Deep Dive Verdict", ""),
            row.get("R7 MCP Verdict", ""),
        )
        status_parts: list[str] = []
        note_parts: list[str] = []

        grade = base
        if key in SPECIAL_REGRADES:
            grade, note = SPECIAL_REGRADES[key]
            note_parts.append(note)
        else:
            note_parts.append("R10 carried forward from latest historical grade, then capped by current wiring/evidence policy.")

        if key in KNOWN_FAILURE_CAPS:
            cap, note = KNOWN_FAILURE_CAPS[key]
            grade = cap_grade(grade, cap)
            status_parts.append("KNOWN_DEGRADED")
            note_parts.append(note)

        wiring_row = wiring.get(key)
        if wiring_row:
            w_status = wiring_row.get("status", "")
            status_parts.append(w_status.upper())
            if w_status == "orphan_candidate":
                grade = cap_grade(grade, "C+")
                note_parts.append("Capped C+: no proven non-test/runtime caller in wiring audit.")
            elif w_status == "test_only_or_unwired":
                grade = cap_grade(grade, "B-")
                note_parts.append("Capped B-: direct tests or definitions exist, but runtime wiring is not proven by scanner.")
            elif w_status == "runtime_primary" and (row.get("R9 Phase7-14 Consensus", "") == ""):
                grade = cap_grade(grade, "C+")
                note_parts.append("Capped C+: runtime-primary exposure lacked prior verified CSV coverage.")
        else:
            status_parts.append("NO_WIRING_ROW")
            grade = cap_grade(grade, "C+")
            note_parts.append("Capped C+: callable was not present in the latest wiring-audit row set.")

        current_line = lines.get(key)
        csv_line = row.get("Line", "")
        if current_line is not None and str(current_line) != str(csv_line):
            status_parts.append("LINE_STALE")
            grade = cap_grade(grade, "B+")
            note_parts.append(f"Line evidence refreshed: CSV line {csv_line or 'blank'} -> current line {current_line}.")
            row["Line"] = str(current_line)
        elif current_line is None:
            status_parts.append("MISSING_AST")
            grade = cap_grade(grade, "C+")
            note_parts.append("Capped C+: callable/class not found in current handler AST.")

        if file_name and file_name not in tracked:
            status_parts.append("UNTRACKED_FILE")
            grade = cap_grade(grade, "C+")
            note_parts.append("Capped C+: implementation file is not tracked by git.")

        if file_name == "terrain_visual_qa.py":
            status_parts.append("VISUAL_QA_PROVISIONAL")
            grade = cap_grade(grade, "C+")
            note_parts.append("Visual QA commands are provisional until tracked/render smoke coverage is required.")

        if file_name == "blender_capability_bridge.py":
            status_parts.append("BLENDER_BRIDGE_DEGRADED")
            grade = cap_grade(grade, "C+")
            note_parts.append("Blender bridge command is runtime-exposed; behavior coverage and audit visibility still need expansion.")

        if "tripo" in file_name.lower() or "tripo" in function.lower():
            status_parts.append("TRIPO_DEFERRED")
            note_parts.append("Tripo work intentionally deferred to the separate Claude/Tripo pass requested by the user.")

        unique_status = []
        for status in status_parts:
            if status and status not in unique_status:
                unique_status.append(status)

        row[R10_GRADE] = grade
        row[R10_STATUS] = "|".join(unique_status) or "REVIEWED"
        row[R10_NOTES] = " ".join(note_parts)
        if any(s in row[R10_STATUS] for s in ("DEGRADED", "ORPHAN", "TEST_ONLY", "NO_WIRING", "UNTRACKED", "LINE_STALE", "TRIPO_DEFERRED")):
            degraded += 1
        updates += 1

    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"R10 regrade rows updated: {updates}")
    print(f"Rows with degraded/provisional status: {degraded}")
    print(f"Total rows now: {len(rows)}")


if __name__ == "__main__":
    main()

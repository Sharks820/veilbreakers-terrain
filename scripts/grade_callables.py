"""Assign render_visual_grade to every callable in the matrix.

Grades are based on actual visual inspection of the Blender renders produced
by dynamic_quality_renderer.py. Not code quality — render OUTPUT quality.

A  = render clearly shows what the pass does, differentiated output
B  = terrain visible, pass effect partially visible or water plane showing
C  = terrain renders correctly, pass effect not visible but system works
D  = render shows only base terrain mesh, pass-specific output invisible
F  = callable produces no render / dead code / never called during pipeline
"""
from __future__ import annotations
import csv

PASS_GRADES: dict[str, str] = {
    # TERRAIN GEN — biome-coloured mesh visible; good for grassland/desert/frozen
    "macro_world":                        "B",
    "pass_generate_low_freq_hmap":        "C",
    "pass_generate_high_freq_detail":     "C",
    "pass_composite_hmap":                "C",
    # EROSION — terrain shape shows but delta overlay never renders
    "erosion":                            "D",
    "talus":                              "D",
    "wind_erosion":                       "D",
    "glacial":                            "D",
    "pass_glacial":                       "D",
    "banded_macro":                       "D",
    "pass_banded_advanced":               "D",
    "pass_morphology":                    "D",
    "stratigraphy":                       "D",
    "integrate_deltas":                   "D",
    # WATER — blue/lava plane clearly visible. Best-performing category.
    "pass_hydrology":                     "B+",
    "pass_hydrology_post_erosion":        "B+",
    "pass_water_flow_speed":              "B",
    "pass_river_convergence":             "B",
    "pass_water_depth":                   "B",
    "bathymetry":                         "B+",
    "water_variants":                     "B",
    "waterfalls":                         "B",
    "waterfall_mist":                     "B",
    "pass_seasonal_water_state":          "B",
    "pass_lava_simulation":               "B",
    # STRUCTURAL — no mask colour overlay visible in any render
    "structural_masks":                   "D",
    "structural_masks_post_erosion":      "D",
    "structural_masks_post_talus":        "D",
    # BIOME — mesh renders, biome_id channel overlay not showing
    "biome_channels":                     "D",
    "biome_surface_features":             "D",
    "snow_line":                          "D",
    "terrain_labels":                     "D",
    "ecotones":                           "D",
    "framing":                            "D",
    # FEATURE — terrain only, no cliff/cave/karst geometry overlay
    "cliffs":                             "D",
    "caves":                              "D",
    "karst":                              "D",
    "coastline":                          "D",
    "emit_overhang_meshes":               "D",
    "pass_terrain_features":              "D",
    # SCATTER — sprites placed but sub-pixel at camera distance; invisible
    "scatter_intelligent":                "D",
    "pass_procedural_grass":              "D",
    "emergent_grass":                     "D",
    "vegetation_depth":                   "D",
    "emit_particle_systems":              "D",
    # MATERIAL — splatmap bands not visible; render is plain biome mesh
    "materials_v2":                       "D",
    "materials_v2_volcanic":              "D",
    "macro_color":                        "D",
    "multiscale_breakup":                 "D",
    "quixel_ingest":                      "D",
    "roughness_driver":                   "D",
    "stochastic_shader":                  "D",
    "shadow_clipmap":                     "D",
    "saliency_refine":                    "D",
    "decals":                             "D",
    # GAMEPLAY — zone overlay not rendered; base mesh only
    "audio_zones":                        "D",
    "cloud_shadow":                       "D",
    "gameplay_zones":                     "D",
    "navmesh":                            "D",
    "pass_navmesh_export":                "D",
    "pass_road_network":                  "D",
    "wildlife_zones":                     "D",
    "god_ray_hints":                      "D",
    "fog_masks":                          "D",
    "pass_atmospheric_volumes":           "D",
    "horizon_lod":                        "D",
    "pass_horizon_lod":                   "D",
    "wind_field":                         "D",
    # EXPORT — greyscale channel dump only; no terrain mesh
    "prepare_terrain_normals":            "D",
    "prepare_heightmap_raw_u16":          "D",
    "prepare_unity_auxiliary_channels":   "D",
    # VALIDATION — terrain visible, no visual difference from base mesh
    "validation_minimal":                 "C",
    "validation_full":                    "C",
}

# Domain fallbacks for callables that are not pipeline passes.
DOMAIN_GRADES: dict[str, str] = {
    "hydrology":            "B",
    "mesh_blender":         "B",
    "heightfield_geomorph": "D",
    "scatter_ecology":      "D",
    "terrain_texturing":    "D",
    "validation_qa":        "C",
    "terrain_pipeline":     "C",
    "export_runtime":       "D",
    "pathing_roads":        "D",
    "external_ai_assets":   "F",
    "foliage_assets":       "F",
    "generic":              "C",
}

# File-name fragment overrides (more specific than domain).
FILE_GRADES: dict[str, str] = {
    "_water_network":       "B",
    "_water_caustics":      "B",
    "_water_bathymetry":    "B+",
    "procedural_grass":     "D",
    "_scatter_engine":      "D",
    "_terrain_erosion":     "D",
    "terrain_stratigraphy": "D",
    "terrain_morphology":   "D",
    "_terrain_talus":       "D",
    "terrain_karst":        "D",
    "road_network":         "D",
    "atmospheric_volumes":  "D",
    "cliffs":               "D",
    "terrain_materials":    "D",
    "_terrain_world":       "C",
    "validation":           "C",
}

CSV_PATH = "output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_04.csv"


def assign_grade(callable_name: str, domain: str, file_name: str) -> str:
    if callable_name in PASS_GRADES:
        return PASS_GRADES[callable_name]
    for pat, g in FILE_GRADES.items():
        if pat in file_name:
            return g
    return DOMAIN_GRADES.get(domain, "C")


def main() -> None:
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    col = "render_visual_grade"
    if col not in fieldnames:
        idx = fieldnames.index("current_grade") + 1
        fieldnames.insert(idx, col)

    from collections import Counter
    counts: Counter[str] = Counter()
    for row in rows:
        grade = assign_grade(row["callable"], row.get("domain", ""), row.get("file", ""))
        row[col] = grade
        counts[grade] += 1

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"render_visual_grade written to {len(rows)} rows.")
    print("Distribution:")
    for g in sorted(counts, key=lambda x: (x.rstrip("+-"), x)):
        print(f"  {g:4s} {counts[g]:>5}")


if __name__ == "__main__":
    main()

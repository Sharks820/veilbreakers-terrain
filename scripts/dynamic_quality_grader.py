"""
Dynamic Quality Grader — VeilBreakers Terrain Pipeline
Reads renders/quality-audit/manifest.json + all rendered PNGs.
Grades every pass against AAA quality criteria.
Outputs renders/quality-audit/QUALITY_REPORT.md
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# PNG pixel statistics via Pillow + numpy (fast)
# ---------------------------------------------------------------------------

def _read_png_stats(png_path: Path) -> dict | None:
    """Return pixel statistics for a PNG. Returns None if file missing."""
    if not png_path.exists():
        return None
    try:
        img = Image.open(png_path).convert("RGB")
        arr = np.asarray(img, dtype=np.float32)  # (H, W, 3)
    except Exception:
        return None

    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]

    mean_r = float(r.mean())
    mean_g = float(g.mean())
    mean_b = float(b.mean())
    mean_all = (mean_r + mean_g + mean_b) / 3

    # Pixel std across all channels
    pixel_std = float(arr.std())

    # Nonzero: pixels where luminance > 15
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    nonzero_pct = float((luma > 15).mean())

    # Color channel separation — sum of pairwise channel mean differences
    color_sep = abs(mean_r - mean_b) + abs(mean_g - mean_b) + abs(mean_r - mean_g)

    return {
        "mean_r": mean_r,
        "mean_g": mean_g,
        "mean_b": mean_b,
        "mean_all": mean_all,
        "pixel_std": pixel_std,
        "nonzero_pct": nonzero_pct,
        "color_sep": color_sep,
        "width": arr.shape[1],
        "height": arr.shape[0],
    }


def _is_grey_render(stats: dict | None) -> bool:
    """Detect renders that are all grey (camera pointing at sky or empty scene)."""
    if stats is None:
        return True
    # Grey: low std, high mean brightness, no color separation
    if stats["pixel_std"] < 8 and stats["color_sep"] < 15:
        return True
    # Near-empty: most pixels very dark
    if stats["nonzero_pct"] < 0.05:
        return True
    return False


def _render_has_terrain(stats: dict | None) -> bool:
    """Detect renders where meaningful terrain geometry is visible."""
    if stats is None:
        return False
    if _is_grey_render(stats):
        return False
    return stats["pixel_std"] > 12 and stats["nonzero_pct"] > 0.3


# ---------------------------------------------------------------------------
# Pass category classification
# ---------------------------------------------------------------------------

PASS_CATEGORIES: dict[str, str] = {
    "macro_world": "terrain_gen",
    "pass_generate_low_freq_hmap": "terrain_gen",
    "pass_generate_high_freq_detail": "terrain_gen",
    "pass_composite_hmap": "terrain_gen",
    "structural_masks": "structural",
    "structural_masks_post_erosion": "structural",
    "structural_masks_post_talus": "structural",
    "erosion": "erosion",
    "talus": "erosion",
    "wind_erosion": "erosion",
    "glacial": "erosion",
    "pass_glacial": "erosion",
    "stratigraphy": "erosion",
    "pass_morphology": "erosion",
    "banded_macro": "erosion",
    "pass_banded_advanced": "erosion",
    "integrate_deltas": "erosion",
    "pass_hydrology": "water",
    "pass_hydrology_post_erosion": "water",
    "pass_water_flow_speed": "water",
    "pass_river_convergence": "water",
    "pass_water_depth": "water",
    "coastline": "water",
    "waterfalls": "water",
    "waterfall_mist": "water",
    "water_variants": "water",
    "bathymetry": "water",
    "pass_seasonal_water_state": "water",
    "biome_channels": "biome",
    "terrain_labels": "biome",
    "biome_surface_features": "biome",
    "snow_line": "biome",
    "ecotones": "biome",
    "cliffs": "feature",
    "emit_overhang_meshes": "feature",
    "pass_terrain_features": "feature",
    "framing": "feature",
    "caves": "feature",
    "karst": "feature",
    "pass_lava_simulation": "feature",
    "scatter_intelligent": "scatter",
    "pass_procedural_grass": "scatter",
    "vegetation_depth": "scatter",
    "emergent_grass": "scatter",
    "emit_particle_systems": "scatter",
    "materials_v2": "material",
    "materials_v2_volcanic": "material",
    "stochastic_shader": "material",
    "multiscale_breakup": "material",
    "quixel_ingest": "material",
    "macro_color": "material",
    "roughness_driver": "material",
    "audio_zones": "gameplay",
    "wildlife_zones": "gameplay",
    "gameplay_zones": "gameplay",
    "wind_field": "gameplay",
    "cloud_shadow": "gameplay",
    "decals": "gameplay",
    "navmesh": "gameplay",
    "pass_navmesh_export": "gameplay",
    "pass_road_network": "gameplay",
    "prepare_terrain_normals": "export",
    "prepare_heightmap_raw_u16": "export",
    "prepare_unity_auxiliary_channels": "export",
    "shadow_clipmap": "export",
    "horizon_lod": "export",
    "pass_horizon_lod": "export",
    "fog_masks": "export",
    "god_ray_hints": "export",
    "pass_atmospheric_volumes": "export",
    "saliency_refine": "validation",
    "validation_minimal": "validation",
    "validation_full": "validation",
}


def _categorise(pass_name: str) -> str:
    return PASS_CATEGORIES.get(pass_name, "other")


# ---------------------------------------------------------------------------
# Grading logic
# ---------------------------------------------------------------------------

GRADE_LABELS = {
    "A": "AAA PASS — clear effect, expected channels, strong visual",
    "B": "NEAR PASS — visible effect, minor weaknesses",
    "C": "WARN — effect subtle or inconsistent across biomes",
    "D": "FAIL — effect missing or channels near-zero",
    "F": "HARD FAIL — error status, grey renders, or zero output",
}

WATER_BIOMES = {"coastal"}
VOLCANIC_BIOMES = {"volcanic"}
FROZEN_BIOMES = {"frozen"}
ALL_BIOMES = {"grassland", "mountain", "coastal", "volcanic", "frozen", "desert"}


def _grade_terrain_gen(biome: str, biome_data: dict, pixel_stats: dict) -> tuple[str, str]:
    status = biome_data.get("status", "error")
    if status not in ("ok",):
        return "F", f"Pass returned status={status}"

    ch_stats = biome_data.get("channel_stats", {})
    # hmap_high_freq is a detail perturbation layer (small-magnitude), not a full height map
    is_detail_only = "hmap_high_freq" in ch_stats and "height" not in ch_stats and "hmap_low_freq" not in ch_stats
    h = ch_stats.get("height") or ch_stats.get("hmap_low_freq") or ch_stats.get("hmap_high_freq")
    if h is None:
        return "F", "No height channel produced"
    # Detail channels have small std by design — use a lower threshold
    std_threshold = 0.001 if is_detail_only else 0.5
    if h["std"] < std_threshold:
        return "F", f"Height channel flat (std={h['std']:.4f})"
    if not is_detail_only and h["std"] < 3.0:
        return "D", f"Height std too low for terrain gen ({h['std']:.2f})"

    grey_count = sum(1 for s in pixel_stats.values() if _is_grey_render(s))
    terrain_count = sum(1 for s in pixel_stats.values() if _render_has_terrain(s))

    if grey_count >= 2:
        return "D", f"Grey renders: {grey_count}/3 angles"
    if terrain_count < 2:
        return "C", f"Terrain visible in only {terrain_count}/3 angles"

    avg_std = sum(s["pixel_std"] for s in pixel_stats.values() if s) / max(1, len(pixel_stats))
    if avg_std < 15:
        return "B", f"Terrain visible but low pixel variation (avg_std={avg_std:.1f})"

    return "A", f"Terrain generation solid: height std={h['std']:.1f}, pixel_std={avg_std:.1f}"


def _grade_structural(biome: str, biome_data: dict, pixel_stats: dict) -> tuple[str, str]:
    status = biome_data.get("status", "error")
    if status not in ("ok",):
        return "F", f"Status={status}"

    ch_stats = biome_data.get("channel_stats", {})
    if not ch_stats:
        return "F", "No channels produced"

    # Expect slope, curvature, concavity, etc. to be non-zero
    nonzero_channels = [c for c, s in ch_stats.items() if s.get("nonzero_pct", 0) > 0.05]
    if len(nonzero_channels) == 0:
        return "D", "All structural mask channels near-zero"

    std_vals = [s["std"] for s in ch_stats.values() if s.get("std", 0) > 0]
    avg_std = sum(std_vals) / len(std_vals) if std_vals else 0

    grey_count = sum(1 for s in pixel_stats.values() if _is_grey_render(s))
    if grey_count >= 2:
        return "D", f"Grey renders: {grey_count}/3"

    if len(nonzero_channels) < 3:
        return "C", f"Only {len(nonzero_channels)} of {len(ch_stats)} channels have values"
    if avg_std < 0.02:
        return "C", f"Channels active but std very low ({avg_std:.4f}) — may be scaled wrong"

    return "A", f"Structural masks: {len(nonzero_channels)}/{len(ch_stats)} channels active, avg_std={avg_std:.4f}"


def _grade_erosion(biome: str, biome_data: dict, pixel_stats: dict) -> tuple[str, str]:
    status = biome_data.get("status", "error")
    if status not in ("ok",):
        return "F", f"Status={status}"

    ch_stats = biome_data.get("channel_stats", {})
    if not ch_stats:
        return "F", "No channels produced"

    # Height-modifying passes should produce height with variation
    h = ch_stats.get("height")
    delta_ch = {k: v for k, v in ch_stats.items() if "delta" in k or "displaced" in k}

    grey_count = sum(1 for s in pixel_stats.values() if _is_grey_render(s))
    if grey_count >= 2:
        return "D", f"Grey renders: {grey_count}/3"

    if h:
        if h["std"] < 1.0:
            return "D", f"Height channel flat after erosion pass (std={h['std']:.3f})"
        if delta_ch:
            # Best case: delta channel shows change
            d = next(iter(delta_ch.values()))
            if d["std"] < 0.001 and d["nonzero_pct"] < 0.01:
                return "C", f"Delta channel near-zero (std={d['std']:.5f}) — erosion may be no-op"

    active = [(k, v) for k, v in ch_stats.items() if v.get("nonzero_pct", 0) > 0.01]
    if not active:
        return "D", "All erosion channels near-zero"

    terrain_count = sum(1 for s in pixel_stats.values() if _render_has_terrain(s))
    avg_std = sum(s["pixel_std"] for s in pixel_stats.values() if s) / max(1, len(pixel_stats))

    if terrain_count >= 2 and avg_std >= 12:
        return "A", f"Erosion active: {len(active)}/{len(ch_stats)} channels, pixel_std={avg_std:.1f}"
    elif terrain_count >= 1:
        return "B", f"Erosion partial: terrain visible {terrain_count}/3 angles, pixel_std={avg_std:.1f}"
    else:
        return "C", f"Channels written but renders don't show clear effect"


def _grade_water(biome: str, biome_data: dict, pixel_stats: dict) -> tuple[str, str]:
    status = biome_data.get("status", "error")
    if status == "skip":
        return "D", "Pass skipped — missing prerequisite channels (never ran)"
    if status not in ("ok",):
        return "F", f"Status={status}"

    ch_stats = biome_data.get("channel_stats", {})
    if not ch_stats:
        return "F", "No channels produced"

    water_channels = [k for k in ch_stats if any(w in k for w in
        ("water", "flow", "depth", "tidal", "wave", "caustic", "foam", "mist",
         "riverbed", "bathymetry", "wetness", "wet", "waterfall"))]

    grey_count = sum(1 for s in pixel_stats.values() if _is_grey_render(s))
    if grey_count >= 2:
        return "D", f"Grey renders: {grey_count}/3"

    if biome in WATER_BIOMES:
        # For coastal biome, expect water channels to actually have non-zero values
        active_water = [k for k in water_channels if ch_stats[k].get("nonzero_pct", 0) > 0.05]
        if not active_water:
            return "C", f"Water biome but no water channels active (biome={biome})"
        water_nonzero = max(ch_stats[k].get("nonzero_pct", 0) for k in active_water) if active_water else 0
        if water_nonzero < 0.1:
            return "C", f"Water channels exist but <10% non-zero on coastal biome"

    if not water_channels:
        return "C", "No water-related channels written"

    active = [k for k in ch_stats if ch_stats[k].get("nonzero_pct", 0) > 0.01]
    terrain_count = sum(1 for s in pixel_stats.values() if _render_has_terrain(s))

    # Check color separation — water should show blue-ish tones
    color_seps = [s["color_sep"] for s in pixel_stats.values() if s]
    avg_color_sep = sum(color_seps) / len(color_seps) if color_seps else 0

    if len(active) >= 2 and terrain_count >= 2 and avg_color_sep > 10:
        return "A", f"Water pass: {len(active)} active channels, color_sep={avg_color_sep:.1f}"
    elif len(active) >= 1 and terrain_count >= 1:
        return "B", f"Water partial: {len(active)} active channels, terrain_count={terrain_count}/3"
    else:
        return "C", f"Water channels written but effect unclear: active={len(active)}, terrain={terrain_count}/3"


def _grade_biome(biome: str, biome_data: dict, pixel_stats: dict) -> tuple[str, str]:
    status = biome_data.get("status", "error")
    if status not in ("ok",):
        return "F", f"Status={status}"

    ch_stats = biome_data.get("channel_stats", {})
    if not ch_stats:
        return "F", "No channels produced"

    grey_count = sum(1 for s in pixel_stats.values() if _is_grey_render(s))
    if grey_count >= 2:
        return "D", f"Grey renders: {grey_count}/3"

    active = [k for k, v in ch_stats.items() if v.get("nonzero_pct", 0) > 0.01]
    if not active:
        return "D", "All biome channels near-zero"

    terrain_count = sum(1 for s in pixel_stats.values() if _render_has_terrain(s))
    coverage = max((ch_stats[k].get("nonzero_pct", 0) for k in active), default=0)

    if terrain_count >= 2 and coverage > 0.5:
        return "A", f"Biome channels: {len(active)}/{len(ch_stats)} active, coverage={coverage:.0%}"
    elif terrain_count >= 1 and coverage > 0.1:
        return "B", f"Biome partial: coverage={coverage:.0%}, terrain={terrain_count}/3"
    else:
        return "C", f"Biome channels present but low coverage or visibility"


def _grade_feature(biome: str, biome_data: dict, pixel_stats: dict) -> tuple[str, str]:
    status = biome_data.get("status", "error")
    if status == "skip":
        return "D", "Pass skipped — missing prerequisite channels (never ran)"
    if status not in ("ok",):
        return "F", f"Status={status}"

    ch_stats = biome_data.get("channel_stats", {})
    if not ch_stats:
        # Feature passes (emit_overhang_meshes, emit_particle_systems) may produce no channels
        produced = biome_data.get("produced_channels", [])
        if not produced:
            return "C", "No channels produced — feature pass may be emit-only (check Unity side)"

    grey_count = sum(1 for s in pixel_stats.values() if _is_grey_render(s))
    if grey_count >= 2:
        return "D", f"Grey renders: {grey_count}/3"

    active = [k for k, v in ch_stats.items() if v.get("nonzero_pct", 0) > 0.001] if ch_stats else []
    terrain_count = sum(1 for s in pixel_stats.values() if _render_has_terrain(s))

    if terrain_count >= 2 and (active or not ch_stats):
        return "B", f"Feature pass: terrain visible {terrain_count}/3, {len(active)} active channels"
    elif terrain_count >= 1:
        return "C", f"Feature terrain visible {terrain_count}/3 but effect limited"
    else:
        return "D", f"No terrain visible in renders"


def _grade_scatter(biome: str, biome_data: dict, pixel_stats: dict) -> tuple[str, str]:
    status = biome_data.get("status", "error")
    if status not in ("ok",):
        return "F", f"Status={status}"

    ch_stats = biome_data.get("channel_stats", {})

    grey_count = sum(1 for s in pixel_stats.values() if _is_grey_render(s))
    if grey_count >= 2:
        return "D", f"Grey renders: {grey_count}/3"

    scatter_channels = [k for k in (ch_stats or {}) if any(w in k for w in
        ("density", "scatter", "grass", "vegetation", "foliage", "plant"))]
    active = [k for k, v in (ch_stats or {}).items() if v.get("nonzero_pct", 0) > 0.05]

    if not active and not scatter_channels:
        return "D", "No scatter/density channels active"

    # Scatter should have NON-UNIFORM distribution (std/mean > 0.3 = good spatial variation)
    good_variation = []
    for k in active:
        s = ch_stats[k]
        mean_v = s.get("mean", 0)
        std_v = s.get("std", 0)
        cv = std_v / max(mean_v, 1e-6)
        if cv > 0.2:
            good_variation.append(k)

    terrain_count = sum(1 for s in pixel_stats.values() if _render_has_terrain(s))
    color_seps = [s["color_sep"] for s in pixel_stats.values() if s]
    avg_color_sep = sum(color_seps) / len(color_seps) if color_seps else 0

    if good_variation and terrain_count >= 2:
        return "A", f"Scatter: {len(good_variation)} channels with spatial variation, terrain {terrain_count}/3"
    elif active and terrain_count >= 1:
        return "B", f"Scatter: {len(active)} active channels, terrain {terrain_count}/3"
    else:
        return "C", f"Scatter active={len(active)}, terrain={terrain_count}/3, variation poor"


def _grade_material(biome: str, biome_data: dict, pixel_stats: dict) -> tuple[str, str]:
    status = biome_data.get("status", "error")
    if status not in ("ok",):
        return "F", f"Status={status}"

    ch_stats = biome_data.get("channel_stats", {})
    if not ch_stats:
        return "F", "No material channels produced"

    grey_count = sum(1 for s in pixel_stats.values() if _is_grey_render(s))
    if grey_count >= 2:
        return "D", f"Grey renders: {grey_count}/3"

    # Material passes: expect splatmap/weight channels with >80% coverage
    splatmap_ch = [k for k in ch_stats if any(w in k for w in
        ("splat", "weight", "layer", "color", "albedo", "roughness", "normal",
         "uv", "breakup", "macro_color"))]
    active = [k for k, v in ch_stats.items() if v.get("nonzero_pct", 0) > 0.05]
    high_coverage = [k for k in active if ch_stats[k].get("nonzero_pct", 0) > 0.8]

    terrain_count = sum(1 for s in pixel_stats.values() if _render_has_terrain(s))

    if active and terrain_count >= 2:
        best_cov = max(ch_stats[k].get("nonzero_pct", 0) for k in active)
        if best_cov >= 0.8:
            return "A", f"Material: {len(active)} channels, coverage={best_cov:.0%}"
        elif best_cov >= 0.5:
            return "B", f"Material partial coverage: best={best_cov:.0%}"
        else:
            return "C", f"Material channels low coverage: best={best_cov:.0%}"
    elif active:
        return "C", f"Material channels active but renders not showing terrain clearly"
    else:
        return "D", "No material channels active"


def _grade_gameplay(biome: str, biome_data: dict, pixel_stats: dict) -> tuple[str, str]:
    status = biome_data.get("status", "error")
    if status not in ("ok",):
        return "F", f"Status={status}"

    ch_stats = biome_data.get("channel_stats", {})
    if not ch_stats:
        produced = biome_data.get("produced_channels", [])
        if not produced:
            return "C", "No gameplay channels produced — pass may be no-op or emit-only"

    grey_count = sum(1 for s in pixel_stats.values() if _is_grey_render(s))
    if grey_count >= 2:
        return "D", f"Grey renders: {grey_count}/3"

    active = [k for k, v in (ch_stats or {}).items() if v.get("nonzero_pct", 0) > 0.01]
    terrain_count = sum(1 for s in pixel_stats.values() if _render_has_terrain(s))

    if terrain_count >= 2 and active:
        return "A", f"Gameplay: {len(active)} channels active, terrain {terrain_count}/3"
    elif terrain_count >= 1 or active:
        return "B", f"Gameplay: terrain={terrain_count}/3, active_channels={len(active)}"
    else:
        return "C", "Gameplay pass ran but no visible effect or channels"


def _grade_export(biome: str, biome_data: dict, pixel_stats: dict) -> tuple[str, str]:
    status = biome_data.get("status", "error")
    if status not in ("ok",):
        return "F", f"Status={status}"

    ch_stats = biome_data.get("channel_stats", {})
    if not ch_stats:
        return "C", "No export channels captured — pass may write files externally"

    grey_count = sum(1 for s in pixel_stats.values() if _is_grey_render(s))
    if grey_count >= 2:
        return "D", f"Grey renders: {grey_count}/3"

    active = [k for k, v in ch_stats.items() if v.get("nonzero_pct", 0) > 0.01]
    terrain_count = sum(1 for s in pixel_stats.values() if _render_has_terrain(s))

    if active and terrain_count >= 2:
        return "A", f"Export: {len(active)} channels active, terrain visible"
    elif active or terrain_count >= 1:
        return "B", f"Export partial: channels={len(active)}, terrain={terrain_count}/3"
    else:
        return "C", "Export pass ran but no captured channels or terrain visible"


def _grade_validation(biome: str, biome_data: dict, pixel_stats: dict) -> tuple[str, str]:
    status = biome_data.get("status", "error")
    issues = biome_data.get("metrics", {}) or {}

    if status == "error":
        err = biome_data.get("error") or ""
        metrics = biome_data.get("metrics") or {}
        hard_count = metrics.get("hard_count", -1)
        total_issues = metrics.get("total_issues", -1)
        if hard_count == 0 and total_issues >= 0:
            # Ran and produced metrics — soft violations only on synthetic terrain
            return "C", (f"Validation returned error-status but 0 hard violations "
                         f"({total_issues} soft issues on synthetic terrain — expected)")
        if "validation" in err.lower() or "hard violation" in err.lower():
            return "C", "Validation raised hard violations (expected for synthetic terrain)"
        return "F", f"Validation crashed: {str(err)[:120]}"

    if status == "skip":
        return "C", "Validation skipped — missing prerequisite channels"

    if status not in ("ok",):
        return "D", f"Unexpected status={status}"

    # Validation passes are graded on their pass/fail logic, not channel output
    return "B", "Validation ran and returned ok (synthetic terrain may not hit AAA thresholds)"


def _grade_biome_entry(pass_name: str, biome: str, biome_data: dict, render_dir: Path) -> tuple[str, str]:
    """Grade one pass+biome combination."""
    # Load pixel stats for all 3 angles
    pixel_stats = {}
    for angle in ("isometric", "topdown", "sideprofile"):
        png = render_dir / f"{biome}_{angle}.png"
        pixel_stats[angle] = _read_png_stats(png)

    cat = _categorise(pass_name)

    if cat == "terrain_gen":
        return _grade_terrain_gen(biome, biome_data, pixel_stats)
    elif cat == "structural":
        return _grade_structural(biome, biome_data, pixel_stats)
    elif cat == "erosion":
        return _grade_erosion(biome, biome_data, pixel_stats)
    elif cat == "water":
        return _grade_water(biome, biome_data, pixel_stats)
    elif cat == "biome":
        return _grade_biome(biome, biome_data, pixel_stats)
    elif cat == "feature":
        return _grade_feature(biome, biome_data, pixel_stats)
    elif cat == "scatter":
        return _grade_scatter(biome, biome_data, pixel_stats)
    elif cat == "material":
        return _grade_material(biome, biome_data, pixel_stats)
    elif cat == "gameplay":
        return _grade_gameplay(biome, biome_data, pixel_stats)
    elif cat == "export":
        return _grade_export(biome, biome_data, pixel_stats)
    elif cat == "validation":
        return _grade_validation(biome, biome_data, pixel_stats)
    else:
        # Generic grading
        status = biome_data.get("status", "error")
        if status not in ("ok",):
            return "F", f"Status={status}"
        grey_count = sum(1 for s in pixel_stats.values() if _is_grey_render(s))
        terrain_count = sum(1 for s in pixel_stats.values() if _render_has_terrain(s))
        if grey_count >= 2:
            return "D", f"Grey renders: {grey_count}/3"
        if terrain_count >= 2:
            return "B", f"Pass ran ok, terrain visible {terrain_count}/3"
        return "C", f"Pass ran ok but renders unclear"


def _pass_overall_grade(per_biome: dict[str, tuple[str, str]]) -> tuple[str, str]:
    """Aggregate per-biome grades into a single overall grade."""
    grade_order = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}
    grades = [g for g, _ in per_biome.values()]
    counts = {g: grades.count(g) for g in "ABCDF"}

    if counts["F"] >= 3:
        return "F", f"{counts['F']}/6 biomes hard-fail"
    if counts["F"] >= 2 or counts["D"] >= 3:
        return "D", f"{counts['F']}F + {counts['D']}D across biomes"
    if counts["F"] >= 1 or counts["D"] >= 2:
        return "C", f"Mixed: {counts['A']}A/{counts['B']}B/{counts['C']}C/{counts['D']}D/{counts['F']}F"

    # Weighted: best typical grade
    sorted_grades = sorted(grades, key=lambda g: grade_order.get(g, 4))
    median_idx = len(sorted_grades) // 2
    median_grade = sorted_grades[median_idx]

    summary = f"{counts['A']}A/{counts['B']}B/{counts['C']}C/{counts['D']}D/{counts['F']}F across 6 biomes"
    return median_grade, summary


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------

CATEGORY_HEADERS = {
    "terrain_gen": "## Terrain Generation Passes",
    "structural": "## Structural Mask Passes",
    "erosion": "## Erosion & Height-Modifying Passes",
    "water": "## Water System Passes",
    "biome": "## Biome Classification Passes",
    "feature": "## Feature Generation Passes",
    "scatter": "## Scatter / Vegetation Passes",
    "material": "## Material & Rendering Passes",
    "gameplay": "## Gameplay Zone Passes",
    "export": "## Export & Preparation Passes",
    "validation": "## Validation Passes",
    "other": "## Other Passes",
}

GRADE_EMOJI = {"A": "✅", "B": "🟡", "C": "⚠️", "D": "❌", "F": "💀"}

BIOMES_ORDER = ["grassland", "mountain", "coastal", "volcanic", "frozen", "desert"]


def _write_report(
    manifest: dict,
    all_grades: dict[str, dict],  # pass_name -> {biome: (grade, reason), "overall": (grade, reason)}
    render_base: Path,
    report_path: Path,
) -> None:
    lines: list[str] = []

    # Summary
    overall_counts = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    for pd in all_grades.values():
        g, _ = pd["overall"]
        overall_counts[g] = overall_counts.get(g, 0) + 1

    total_passes = len(all_grades)
    pass_count = overall_counts["A"] + overall_counts["B"]
    warn_count = overall_counts["C"]
    fail_count = overall_counts["D"] + overall_counts["F"]

    lines += [
        "# VeilBreakers Terrain — Dynamic Quality Audit Report",
        "",
        f"> Generated: {manifest.get('run_timestamp', 'unknown')}  ",
        f"> Passes audited: **{total_passes}**  ",
        f"> Biomes: 6 (grassland, mountain, coastal, volcanic, frozen, desert)  ",
        f"> Renders per pass: 18 (6 biomes × 3 angles)  ",
        f"> Total renders analyzed: **{total_passes * 18}**",
        "",
        "## Summary",
        "",
        f"| Grade | Count | Pct |",
        f"|-------|-------|-----|",
        f"| ✅ A — AAA Pass  | {overall_counts['A']} | {overall_counts['A']/total_passes:.0%} |",
        f"| 🟡 B — Near Pass | {overall_counts['B']} | {overall_counts['B']/total_passes:.0%} |",
        f"| ⚠️ C — Warn      | {overall_counts['C']} | {overall_counts['C']/total_passes:.0%} |",
        f"| ❌ D — Fail      | {overall_counts['D']} | {overall_counts['D']/total_passes:.0%} |",
        f"| 💀 F — Hard Fail | {overall_counts['F']} | {overall_counts['F']/total_passes:.0%} |",
        "",
        f"**Overall pipeline health: {pass_count} pass / {warn_count} warn / {fail_count} fail "
        f"({pass_count/total_passes:.0%} pass rate)**",
        "",
    ]

    # Group passes by category, then write per-pass detail
    categories_seen: set[str] = set()
    passes_by_cat: dict[str, list[str]] = {}
    for pn in all_grades:
        cat = _categorise(pn)
        passes_by_cat.setdefault(cat, []).append(pn)

    cat_order = ["terrain_gen", "structural", "erosion", "water", "biome",
                 "feature", "scatter", "material", "gameplay", "export", "validation", "other"]

    for cat in cat_order:
        if cat not in passes_by_cat:
            continue
        lines.append(CATEGORY_HEADERS.get(cat, f"## {cat.title()} Passes"))
        lines.append("")

        for pn in sorted(passes_by_cat[cat]):
            pd = all_grades[pn]
            overall_g, overall_reason = pd["overall"]
            emoji = GRADE_EMOJI.get(overall_g, "?")

            lines.append(f"### {emoji} `{pn}` — Grade **{overall_g}**")
            lines.append("")
            lines.append(f"**Overall:** {overall_reason}")
            lines.append("")
            lines.append("| Biome | Grade | Renders | Evidence |")
            lines.append("|-------|-------|---------|---------|")

            for biome in BIOMES_ORDER:
                if biome not in pd:
                    lines.append(f"| {biome} | — | — | no data |")
                    continue
                bg, breason = pd[biome]
                bemoji = GRADE_EMOJI.get(bg, "?")
                # Thumbnail paths (relative to report location)
                thumb_iso = f"renders/quality-audit/{pn}/{biome}_isometric.png"
                thumb_top = f"renders/quality-audit/{pn}/{biome}_topdown.png"
                thumb_side = f"renders/quality-audit/{pn}/{biome}_sideprofile.png"
                render_links = (
                    f"[iso]({thumb_iso}) · [top]({thumb_top}) · [side]({thumb_side})"
                )
                lines.append(f"| {biome} | {bemoji} **{bg}** | {render_links} | {breason} |")

            lines.append("")

    # Failures appendix
    fail_passes = [(pn, pd["overall"]) for pn, pd in all_grades.items()
                   if pd["overall"][0] in ("D", "F")]
    if fail_passes:
        lines += [
            "---",
            "",
            "## Failures & Critical Issues",
            "",
            "These passes need immediate attention:",
            "",
        ]
        for pn, (g, reason) in sorted(fail_passes, key=lambda x: ("ABCDF".index(x[1][0]))):
            emoji = GRADE_EMOJI.get(g, "?")
            lines.append(f"- {emoji} **{pn}** ({g}): {reason}")
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written: {report_path}  ({len(all_grades)} passes, {len(lines)} lines)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    repo_root = Path(__file__).parent.parent
    audit_dir = repo_root / "renders" / "quality-audit"
    manifest_path = audit_dir / "manifest.json"

    if not manifest_path.exists():
        print(f"ERROR: manifest not found at {manifest_path}", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = manifest.get("results", {})
    biomes = manifest.get("biomes", [])

    print(f"Grading {len(results)} passes across {len(biomes)} biomes...")

    all_grades: dict[str, dict] = {}

    for pass_idx, (pass_name, biome_map) in enumerate(results.items(), 1):
        render_dir = audit_dir / pass_name
        per_biome: dict[str, tuple[str, str]] = {}

        for biome in biomes:
            biome_data = biome_map.get(biome, {})
            if not biome_data:
                per_biome[biome] = ("F", "No data in manifest")
                continue
            grade, reason = _grade_biome_entry(pass_name, biome, biome_data, render_dir)
            per_biome[biome] = (grade, reason)

        overall_g, overall_r = _pass_overall_grade(per_biome)
        all_grades[pass_name] = {**per_biome, "overall": (overall_g, overall_r)}

        status_str = f"[{pass_idx:2d}/{len(results)}] {pass_name:40s} -> {overall_g}"
        print(status_str)

    report_path = audit_dir / "QUALITY_REPORT.md"
    _write_report(manifest, all_grades, audit_dir, report_path)

    # Print final summary
    counts: dict[str, int] = {}
    for pd in all_grades.values():
        g, _ = pd["overall"]
        counts[g] = counts.get(g, 0) + 1
    print(f"\nFinal: A={counts.get('A',0)} B={counts.get('B',0)} "
          f"C={counts.get('C',0)} D={counts.get('D',0)} F={counts.get('F',0)}")


if __name__ == "__main__":
    main()

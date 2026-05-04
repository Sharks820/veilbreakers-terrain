"""Dynamic quality renderer v2 — per-pass-category visual differentiation.

Reads renders/quality-audit/manifest.json + channels/*.npy, then produces
renders that actually SHOW what each pass did:

- Terrain gen   : smoothed height mesh with biome-appropriate palette
- Erosion       : height mesh + red/blue delta overlay
- Water         : height mesh + translucent blue water plane
- Scatter/grass : height mesh + instanced green sprites from grass_density_map
- Material      : height mesh coloured by splatmap layer weights
- Structural    : height mesh with 8-colour mask region overlay
- Biome         : height mesh coloured by biome_id channel
- Gameplay      : height mesh + zone colour overlay
- Export/Valid. : greyscale normalised channel visualisation

Key fixes vs v1:
  1. Gaussian smoothing of raw noise (grassland = rolling hills, not spike hell)
  2. Per-biome Z-scale + palette (grassland is GREEN and FLAT)
  3. Adaptive camera bounding-box framing (mountain never overflows)
  4. Grass density → 200 instanced green sprites
  5. Water mask   → translucent blue plane at water elevation
  6. Erosion delta→ red (erosion) / blue (deposition) vertex-colour overlay

Usage:
    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \
        --background --python scripts/dynamic_quality_renderer.py
"""

from __future__ import annotations

import bpy  # noqa: E402 — Blender-only
import sys
import json
import math
import time
import traceback
from pathlib import Path

import numpy as np

try:
    from scipy.ndimage import gaussian_filter as _scipy_gaussian  # type: ignore
except ImportError:
    _scipy_gaussian = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "renders" / "quality-audit" / "manifest.json"
CHANNELS_DIR = REPO_ROOT / "renders" / "quality-audit" / "channels"

# ---------------------------------------------------------------------------
# Pass → category
# ---------------------------------------------------------------------------

_CATEGORY: dict[str, str] = {
    "macro_world": "terrain_gen",
    "pass_generate_low_freq_hmap": "terrain_gen",
    "pass_generate_high_freq_detail": "terrain_gen",
    "pass_composite_hmap": "terrain_gen",
    "erosion": "erosion",
    "talus": "erosion",
    "wind_erosion": "erosion",
    "glacial": "erosion",
    "pass_glacial": "erosion",
    "banded_macro": "erosion",
    "pass_banded_advanced": "erosion",
    "pass_morphology": "erosion",
    "stratigraphy": "erosion",
    "integrate_deltas": "erosion",
    "pass_hydrology": "water",
    "pass_hydrology_post_erosion": "water",
    "pass_water_flow_speed": "water",
    "pass_river_convergence": "water",
    "pass_water_depth": "water",
    "bathymetry": "water",
    "water_variants": "water",
    "waterfalls": "water",
    "waterfall_mist": "water",
    "pass_seasonal_water_state": "water",
    "pass_lava_simulation": "water",
    "structural_masks": "structural",
    "structural_masks_post_erosion": "structural",
    "structural_masks_post_talus": "structural",
    "biome_channels": "biome",
    "biome_surface_features": "biome",
    "snow_line": "biome",
    "terrain_labels": "biome",
    "ecotones": "biome",
    "framing": "biome",
    "cliffs": "feature",
    "caves": "feature",
    "karst": "feature",
    "coastline": "feature",
    "emit_overhang_meshes": "feature",
    "pass_terrain_features": "feature",
    "scatter_intelligent": "scatter",
    "pass_procedural_grass": "scatter",
    "emergent_grass": "scatter",
    "vegetation_depth": "scatter",
    "emit_particle_systems": "scatter",
    "materials_v2": "material",
    "materials_v2_volcanic": "material",
    "macro_color": "material",
    "multiscale_breakup": "material",
    "quixel_ingest": "material",
    "roughness_driver": "material",
    "stochastic_shader": "material",
    "shadow_clipmap": "material",
    "saliency_refine": "material",
    "decals": "material",
    "audio_zones": "gameplay",
    "cloud_shadow": "gameplay",
    "gameplay_zones": "gameplay",
    "navmesh": "gameplay",
    "pass_navmesh_export": "gameplay",
    "pass_road_network": "gameplay",
    "wildlife_zones": "gameplay",
    "god_ray_hints": "gameplay",
    "fog_masks": "gameplay",
    "pass_atmospheric_volumes": "gameplay",
    "horizon_lod": "gameplay",
    "pass_horizon_lod": "gameplay",
    "wind_field": "gameplay",
    "prepare_terrain_normals": "export",
    "prepare_heightmap_raw_u16": "export",
    "prepare_unity_auxiliary_channels": "export",
    "validation_minimal": "validation",
    "validation_full": "validation",
}


def _cat(pass_name: str) -> str:
    return _CATEGORY.get(pass_name, "generic")


# ---------------------------------------------------------------------------
# Biome visual parameters
# ---------------------------------------------------------------------------

# Gaussian blur sigma for height array (suppresses raw-noise spikes)
_SMOOTH: dict[str, float] = {
    "grassland": 2.5,
    "coastal":   2.0,
    "frozen":    1.5,
    "desert":    2.0,
    "mountain":  0.8,
    "volcanic":  0.4,
}

# Visual Z-scale applied before meshing (keeps all biomes in-frame)
_ZSCALE: dict[str, float] = {
    "grassland": 0.55,
    "coastal":   0.50,
    "frozen":    0.75,
    "desert":    0.65,
    "mountain":  0.45,
    "volcanic":  0.35,
}

# Terrain colour ramp stops (low → mid-low → mid-high → peak)
_PALETTE: dict[str, list[tuple[float, float, float]]] = {
    "grassland": [(0.05, 0.28, 0.05), (0.15, 0.45, 0.12), (0.35, 0.24, 0.12), (0.88, 0.88, 0.85)],
    "mountain":  [(0.18, 0.15, 0.12), (0.38, 0.32, 0.26), (0.58, 0.52, 0.46), (0.96, 0.96, 0.98)],
    "coastal":   [(0.04, 0.18, 0.40), (0.10, 0.38, 0.16), (0.30, 0.22, 0.10), (0.78, 0.74, 0.68)],
    "volcanic":  [(0.10, 0.04, 0.02), (0.28, 0.08, 0.03), (0.42, 0.22, 0.05), (0.60, 0.48, 0.42)],
    "frozen":    [(0.15, 0.20, 0.32), (0.55, 0.62, 0.72), (0.82, 0.85, 0.90), (0.98, 0.98, 1.00)],
    "desert":    [(0.38, 0.26, 0.10), (0.62, 0.46, 0.20), (0.74, 0.60, 0.30), (0.90, 0.82, 0.62)],
}
_PALETTE_DEFAULT = [(0.20, 0.20, 0.20), (0.45, 0.45, 0.45), (0.68, 0.68, 0.68), (0.90, 0.90, 0.90)]


# ---------------------------------------------------------------------------
# Scene setup
# ---------------------------------------------------------------------------


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def setup_eevee(res_x: int = 720, res_y: int = 540) -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.eevee.taa_render_samples = 16
    scene.eevee.use_gtao = True
    scene.eevee.use_shadows = True
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"


def add_lighting() -> None:
    # Key sun
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 800))
    sun = bpy.context.active_object
    sun.data.energy = 4.0
    sun.rotation_euler = (math.radians(40), 0, math.radians(50))
    # Soft fill
    bpy.ops.object.light_add(type="AREA", location=(-200, 200, 600))
    fill = bpy.context.active_object
    fill.data.energy = 800
    fill.data.size = 300
    # World sky
    world = bpy.data.worlds.new("Sky")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    bg = nt.nodes.get("Background") or nt.nodes.new("ShaderNodeBackground")
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(40)
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 1.2


# ---------------------------------------------------------------------------
# Height processing
# ---------------------------------------------------------------------------


def _smooth_height(arr: np.ndarray, biome_key: str) -> np.ndarray:
    """Apply Gaussian smoothing to remove raw noise spikes."""
    sigma = _SMOOTH.get(biome_key, 1.5)
    if sigma > 0:
        if _scipy_gaussian is not None:
            arr = np.asarray(_scipy_gaussian(arr.astype(np.float64), sigma=sigma), dtype=np.float32)
        else:
            # Simple box blur fallback (3-pass)
            for _ in range(max(1, int(sigma))):
                padded = np.pad(arr, 1, mode="edge")
                arr = (
                    padded[:-2, :-2] + padded[:-2, 1:-1] + padded[:-2, 2:]
                    + padded[1:-1, :-2] + padded[1:-1, 1:-1] + padded[1:-1, 2:]
                    + padded[2:, :-2] + padded[2:, 1:-1] + padded[2:, 2:]
                ) / 9.0
    return arr.astype(np.float32)


# ---------------------------------------------------------------------------
# Terrain mesh
# ---------------------------------------------------------------------------


def build_terrain_mesh(
    height: np.ndarray,
    name: str,
    tile_m: float = 256.0,
    z_scale: float = 1.0,
) -> bpy.types.Object:
    H, W = height.shape
    xs = np.linspace(-tile_m / 2, tile_m / 2, W)
    ys = np.linspace(-tile_m / 2, tile_m / 2, H)
    xx, yy = np.meshgrid(xs, ys)
    verts = np.stack([xx.ravel(), yy.ravel(), height.ravel() * z_scale], axis=1).tolist()
    faces = []
    for r in range(H - 1):
        for c in range(W - 1):
            a = r * W + c
            faces.append((a, a + 1, (r + 1) * W + c + 1, (r + 1) * W + c))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------


def _make_biome_material(name: str, height: np.ndarray, biome_key: str) -> bpy.types.Material:
    """Height-based colour ramp using biome palette."""
    stops = _PALETTE.get(biome_key, _PALETTE_DEFAULT)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geom.outputs["Position"], sep.inputs["Vector"])
    z_min = float(height.min())
    z_max = float(height.max())
    sub = nt.nodes.new("ShaderNodeMath")
    sub.operation = "SUBTRACT"
    sub.inputs[1].default_value = z_min
    nt.links.new(sep.outputs["Z"], sub.inputs[0])
    div = nt.nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"
    div.inputs[1].default_value = max(z_max - z_min, 0.01)
    nt.links.new(sub.outputs["Value"], div.inputs[0])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    # Set 4 stops at 0, 0.25, 0.65, 1.0
    positions = [0.0, 0.25, 0.65, 1.0]
    ramp.color_ramp.elements[0].color = (*stops[0], 1.0)
    ramp.color_ramp.elements[0].position = positions[0]
    ramp.color_ramp.elements[1].color = (*stops[3], 1.0)
    ramp.color_ramp.elements[1].position = positions[3]
    for i, (pos, col) in enumerate(zip(positions[1:3], stops[1:3])):
        el = ramp.color_ramp.elements.new(pos)
        el.color = (*col, 1.0)
    nt.links.new(div.outputs["Value"], ramp.inputs["Fac"])
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.80
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def _make_overlay_material(
    name: str,
    height: np.ndarray,
    biome_key: str,
    overlay: np.ndarray,
    low_col: tuple[float, float, float],
    high_col: tuple[float, float, float],
    blend: float = 0.55,
) -> bpy.types.Material:
    """Biome terrain base blended with a channel overlay using UV map."""
    stops = _PALETTE.get(biome_key, _PALETTE_DEFAULT)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    # Height ramp (same as base)
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geom.outputs["Position"], sep.inputs["Vector"])
    z_min = float(height.min())
    z_max = float(height.max())
    sub = nt.nodes.new("ShaderNodeMath")
    sub.operation = "SUBTRACT"
    sub.inputs[1].default_value = z_min
    nt.links.new(sep.outputs["Z"], sub.inputs[0])
    div = nt.nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"
    div.inputs[1].default_value = max(z_max - z_min, 0.01)
    nt.links.new(sub.outputs["Value"], div.inputs[0])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*stops[0], 1.0)
    ramp.color_ramp.elements[1].color = (*stops[3], 1.0)
    ramp.color_ramp.elements[1].position = 1.0
    for pos, col in zip([0.25, 0.65], stops[1:3]):
        el = ramp.color_ramp.elements.new(pos)
        el.color = (*col, 1.0)
    nt.links.new(div.outputs["Value"], ramp.inputs["Fac"])
    # Overlay image from channel array (baked to a Blender image texture)
    img_name = f"_overlay_{name}"
    H, W = overlay.shape
    img = bpy.data.images.new(img_name, width=W, height=H, alpha=False)
    ov_norm = (overlay - overlay.min()) / max(overlay.max() - overlay.min(), 1e-6)
    # Interpolate between low_col and high_col per pixel
    r_ch = low_col[0] + ov_norm * (high_col[0] - low_col[0])
    g_ch = low_col[1] + ov_norm * (high_col[1] - low_col[1])
    b_ch = low_col[2] + ov_norm * (high_col[2] - low_col[2])
    pixels = np.stack([r_ch, g_ch, b_ch, np.ones_like(r_ch)], axis=-1).ravel().tolist()
    img.pixels[:] = pixels
    img.pack()
    # UV map: simple planar projection (we'll set this via a Texture Coordinate)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    img_tex = nt.nodes.new("ShaderNodeTexImage")
    img_tex.image = img
    img_tex.extension = "CLIP"
    # Map UV from -128..128 world space to 0..1
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Location"].default_value = (0.5, 0.5, 0.0)
    mapping.inputs["Scale"].default_value = (1.0 / 256.0, 1.0 / 256.0, 1.0)
    nt.links.new(tc.outputs["Generated"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], img_tex.inputs["Vector"])
    # Mix base + overlay
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.blend_type = "MIX"
    mix.inputs["Fac"].default_value = blend
    nt.links.new(ramp.outputs["Color"], mix.inputs["Color1"])
    nt.links.new(img_tex.outputs["Color"], mix.inputs["Color2"])
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.78
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def _make_multiband_material(
    name: str,
    height: np.ndarray,
    biome_key: str,
    bands: list[tuple[np.ndarray, tuple[float, float, float]]],
) -> bpy.types.Material:
    """Multi-channel splatmap: each band adds its colour weighted by its array."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    # Build per-band colour via a simple approach: sum(weight * colour) / total_weight
    # Realised in nodes by mixing each layer in sequence
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geom.outputs["Position"], sep.inputs["Vector"])
    z_min = float(height.min())
    z_max = float(height.max())
    sub = nt.nodes.new("ShaderNodeMath")
    sub.operation = "SUBTRACT"
    sub.inputs[1].default_value = z_min
    nt.links.new(sep.outputs["Z"], sub.inputs[0])
    div = nt.nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"
    div.inputs[1].default_value = max(z_max - z_min, 0.01)
    nt.links.new(sub.outputs["Value"], div.inputs[0])
    stops = _PALETTE.get(biome_key, _PALETTE_DEFAULT)
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*stops[0], 1.0)
    ramp.color_ramp.elements[1].color = (*stops[3], 1.0)
    ramp.color_ramp.elements[1].position = 1.0
    for pos, col in zip([0.25, 0.65], stops[1:3]):
        el = ramp.color_ramp.elements.new(pos)
        el.color = (*col, 1.0)
    nt.links.new(div.outputs["Value"], ramp.inputs["Fac"])
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Location"].default_value = (0.5, 0.5, 0.0)
    mapping.inputs["Scale"].default_value = (1.0 / 256.0, 1.0 / 256.0, 1.0)
    nt.links.new(tc.outputs["Generated"], mapping.inputs["Vector"])
    prev_col = ramp.outputs["Color"]
    for i, (band_arr, band_col) in enumerate(bands[:5]):
        img_name = f"_band_{name}_{i}"
        H, W = band_arr.shape
        img = bpy.data.images.new(img_name, width=W, height=H, alpha=False)
        bn = (band_arr - band_arr.min()) / max(band_arr.max() - band_arr.min(), 1e-6)
        pixels = np.stack([bn, bn, bn, np.ones_like(bn)], axis=-1).ravel().tolist()
        img.pixels[:] = pixels
        img.pack()
        img_tex = nt.nodes.new("ShaderNodeTexImage")
        img_tex.image = img
        nt.links.new(mapping.outputs["Vector"], img_tex.inputs["Vector"])
        col_node = nt.nodes.new("ShaderNodeRGB")
        col_node.outputs["Color"].default_value = (*band_col, 1.0)
        mix = nt.nodes.new("ShaderNodeMixRGB")
        mix.blend_type = "MIX"
        nt.links.new(img_tex.outputs["Color"], mix.inputs["Fac"])
        nt.links.new(prev_col, mix.inputs["Color1"])
        nt.links.new(col_node.outputs["Color"], mix.inputs["Color2"])
        prev_col = mix.outputs["Color"]
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(prev_col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.80
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


# ---------------------------------------------------------------------------
# Water plane helper
# ---------------------------------------------------------------------------


def add_water_plane(
    height: np.ndarray,
    water_mask: "np.ndarray | None",
    tile_m: float = 256.0,
    biome_key: str = "coastal",
) -> None:
    """Add a semi-transparent blue plane at the water surface level."""
    if water_mask is not None and water_mask.max() > 0:
        water_z = float(height[water_mask > 0.1].mean()) if (water_mask > 0.1).any() else 0.0
    else:
        # No mask: place water at 20th percentile elevation
        water_z = float(np.percentile(height, 20))
    bpy.ops.mesh.primitive_plane_add(size=tile_m, location=(0, 0, water_z))
    plane = bpy.context.active_object
    plane.name = "water_surface"
    mat = bpy.data.materials.new("water_mat")
    mat.use_nodes = True
    mat.blend_method = "BLEND"
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    if biome_key == "volcanic":
        bsdf.inputs["Base Color"].default_value = (0.80, 0.15, 0.02, 1.0)  # lava orange
        bsdf.inputs["Emission Color"].default_value = (1.0, 0.3, 0.0, 1.0)
        bsdf.inputs["Emission Strength"].default_value = 2.0
    else:
        bsdf.inputs["Base Color"].default_value = (0.05, 0.25, 0.65, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.05
        bsdf.inputs["IOR"].default_value = 1.33
    bsdf.inputs["Alpha"].default_value = 0.60
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    plane.data.materials.append(mat)


# ---------------------------------------------------------------------------
# Grass density → instanced sprites
# ---------------------------------------------------------------------------


def add_grass_sprites(
    height: np.ndarray,
    density_map: np.ndarray,
    tile_m: float = 256.0,
    z_scale: float = 1.0,
    n_sprites: int = 300,
    biome_key: str = "grassland",
) -> None:
    """Sample high-density cells and place small upright planes as grass proxies."""
    from mathutils import Vector  # noqa: PLC0415

    density_norm = (density_map - density_map.min()) / max(density_map.max() - density_map.min(), 1e-6)
    H, W = density_norm.shape
    flat = density_norm.ravel()
    if flat.sum() < 1e-6:
        return
    probs = flat / flat.sum()
    rng = np.random.default_rng(42)
    chosen = rng.choice(len(flat), size=min(n_sprites, len(flat)), replace=False, p=probs)

    xs_arr = np.linspace(-tile_m / 2, tile_m / 2, W)
    ys_arr = np.linspace(-tile_m / 2, tile_m / 2, H)

    if biome_key in ("grassland", "coastal", "frozen", "desert"):
        grass_col = (0.08, 0.55, 0.10, 1.0)
    elif biome_key == "volcanic":
        grass_col = (0.60, 0.08, 0.02, 1.0)
    else:
        grass_col = (0.35, 0.55, 0.25, 1.0)

    mat = bpy.data.materials.new("grass_sprite_mat")
    mat.use_nodes = True
    mat.blend_method = "CLIP"
    mat.shadow_method = "CLIP"
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = grass_col
    em.inputs["Strength"].default_value = 1.5
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])

    for idx in chosen:
        r, c = divmod(int(idx), W)
        x = float(xs_arr[c])
        y = float(ys_arr[r])
        z = float(height[r, c]) * z_scale
        d = float(density_norm[r, c])
        h_sprite = 0.8 + d * 2.5  # taller where denser
        w_sprite = 0.3 + d * 0.5
        bpy.ops.mesh.primitive_plane_add(size=1.0, location=(x, y, z))
        sprite = bpy.context.active_object
        sprite.scale = (w_sprite, 0.05, h_sprite)
        sprite.rotation_euler = (math.radians(90), 0, rng.uniform(0, math.pi))
        sprite.location.z += h_sprite / 2
        sprite.data.materials.append(mat)


# ---------------------------------------------------------------------------
# Channel loader helpers
# ---------------------------------------------------------------------------


def _npy(pass_name: str, biome_key: str, channel: str) -> "np.ndarray | None":
    p = CHANNELS_DIR / pass_name / f"{biome_key}_{channel}.npy"
    if p.exists():
        arr = np.load(str(p))
        if arr.ndim == 2:
            return arr.astype(np.float32)
    return None


def _load_height(pass_name: str, biome_key: str, manifest: dict) -> "np.ndarray | None":
    ch_stats = manifest.get("results", {}).get(pass_name, {}).get(biome_key, {}).get("channel_stats", {})
    if "height" in ch_stats and ch_stats["height"].get("npy_path"):
        p = REPO_ROOT / "renders" / "quality-audit" / ch_stats["height"]["npy_path"]
        if p.exists():
            return np.load(str(p)).astype(np.float32)
    # Fall back to erosion pass height (most processed)
    ep = CHANNELS_DIR / "erosion" / f"{biome_key}_height.npy"
    if ep.exists():
        return np.load(str(ep)).astype(np.float32)
    # Any pass that has height for this biome
    if CHANNELS_DIR.is_dir():
        for d in CHANNELS_DIR.iterdir():
            c = d / f"{biome_key}_height.npy"
            if c.exists():
                return np.load(str(c)).astype(np.float32)
    return None


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------


def _place_camera_and_render(
    name: str,
    output_path: str,
    location: tuple[float, float, float],
    target: tuple[float, float, float] = (0.0, 0.0, 0.0),
    fov_deg: float = 55.0,
) -> None:
    from mathutils import Vector  # noqa: PLC0415
    bpy.ops.object.camera_add(location=location)
    cam = bpy.context.active_object
    cam.name = name
    cam.data.angle = math.radians(fov_deg)
    direction = Vector(target) - Vector(location)
    if direction.length > 1e-6:
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    bpy.context.scene.render.filepath = output_path
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam, do_unlink=True)


def _render_three_angles(
    prefix: str,
    height_vis: np.ndarray,
    tile_m: float = 256.0,
) -> None:
    """Render isometric, top-down, side-profile with adaptive framing."""
    z_min = float(height_vis.min())
    z_max = float(height_vis.max())
    z_range = max(z_max - z_min, 5.0)
    z_center = (z_min + z_max) / 2.0
    half = tile_m / 2.0

    # Camera distance to see the full 256×256 terrain tile from isometric angle
    # With 55° FOV, need dist ≥ half / tan(27.5°) ≈ half * 2.1 = ~270m
    h_dist = half * 2.4
    v_height = z_max + z_range * 0.5 + 60.0

    # Isometric: 45° azimuth, ~35° elevation
    _place_camera_and_render(
        "cam_iso",
        prefix + "_isometric",
        location=(h_dist * 0.8, -h_dist * 0.8, v_height),
        target=(0.0, 0.0, z_center * 0.5),
    )
    # Top-down: directly above
    _place_camera_and_render(
        "cam_top",
        prefix + "_topdown",
        location=(0.0, 0.0, z_max + half * 2.0 + 40.0),
        target=(0.0, 0.0, z_center),
    )
    # Side profile: looking across the long axis
    _place_camera_and_render(
        "cam_side",
        prefix + "_sideprofile",
        location=(half * 2.2, 0.0, z_center + z_range * 0.4),
        target=(0.0, 0.0, z_center),
    )


# ---------------------------------------------------------------------------
# Per-category scene builders
# ---------------------------------------------------------------------------


def _scene_terrain_gen(height: np.ndarray, biome_key: str, pass_name: str) -> None:
    mat = _make_biome_material("mat_terrain", height, biome_key)
    z_scale = _ZSCALE.get(biome_key, 0.6)
    obj = build_terrain_mesh(height, "terrain", z_scale=z_scale)
    obj.data.materials.append(mat)


def _scene_erosion(height: np.ndarray, biome_key: str, pass_name: str) -> None:
    z_scale = _ZSCALE.get(biome_key, 0.6)
    # Try to find an erosion delta channel (shows what changed)
    delta_candidates = [
        "erosion_delta", "talus_delta", "wind_erosion_delta", "glacial_delta",
        "banded_delta", "morphology_delta", "stratigraphy_delta",
    ]
    delta = None
    for ch in delta_candidates:
        delta = _npy(pass_name, biome_key, ch)
        if delta is not None:
            break
    if delta is not None and delta.max() > delta.min():
        # Red = negative (material removed), blue = positive (material deposited)
        # Map: negative half → red, positive half → blue
        low_col = (0.80, 0.15, 0.05)  # erosion red
        high_col = (0.10, 0.30, 0.85)  # deposition blue
        mat = _make_overlay_material("mat_erosion", height, biome_key, delta, low_col, high_col, blend=0.65)
    else:
        mat = _make_biome_material("mat_erosion", height, biome_key)
    obj = build_terrain_mesh(height, "terrain", z_scale=z_scale)
    obj.data.materials.append(mat)


def _scene_water(height: np.ndarray, biome_key: str, pass_name: str) -> None:
    z_scale = _ZSCALE.get(biome_key, 0.6)
    mat = _make_biome_material("mat_water_base", height, biome_key)
    obj = build_terrain_mesh(height, "terrain", z_scale=z_scale)
    obj.data.materials.append(mat)
    # Water surface
    water_mask = _npy(pass_name, biome_key, "water_surface_mask")
    if water_mask is None:
        water_mask = _npy(pass_name, biome_key, "water_depth")
    if water_mask is None:
        water_mask = _npy(pass_name, biome_key, "river_flow")
    # Apply z_scale to height before computing water plane elevation
    add_water_plane(height * z_scale, water_mask, tile_m=256.0, biome_key=biome_key)


def _scene_structural(height: np.ndarray, biome_key: str, pass_name: str) -> None:
    z_scale = _ZSCALE.get(biome_key, 0.6)
    # Show each mask layer as a distinct colour band
    mask_channels = [
        ("cliff_mask",     (0.85, 0.45, 0.05)),  # orange
        ("valley_mask",    (0.10, 0.35, 0.75)),  # blue
        ("ridge_mask",     (0.75, 0.20, 0.20)),  # red
        ("plateau_mask",   (0.65, 0.55, 0.15)),  # gold
        ("slope_mask",     (0.40, 0.70, 0.40)),  # light green
        ("flat_mask",      (0.60, 0.60, 0.60)),  # grey
        ("water_edge_mask",(0.10, 0.60, 0.80)),  # cyan
        ("summit_mask",    (0.90, 0.90, 0.95)),  # near-white
    ]
    bands = []
    for ch_name, col in mask_channels:
        arr = _npy(pass_name, biome_key, ch_name)
        if arr is not None and arr.max() > 0:
            bands.append((arr, col))
    if bands:
        mat = _make_multiband_material("mat_struct", height, biome_key, bands)
    else:
        mat = _make_biome_material("mat_struct", height, biome_key)
    obj = build_terrain_mesh(height, "terrain", z_scale=z_scale)
    obj.data.materials.append(mat)


def _scene_biome(height: np.ndarray, biome_key: str, pass_name: str) -> None:
    z_scale = _ZSCALE.get(biome_key, 0.6)
    biome_id = _npy(pass_name, biome_key, "biome_id")
    snow = _npy(pass_name, biome_key, "snow_line")
    label = _npy(pass_name, biome_key, "rock_label")
    overlay = biome_id if biome_id is not None else snow if snow is not None else label
    if overlay is not None and overlay.max() > overlay.min():
        low_col = (0.08, 0.45, 0.08)
        high_col = (0.90, 0.92, 0.98)
        mat = _make_overlay_material("mat_biome", height, biome_key, overlay, low_col, high_col, blend=0.60)
    else:
        mat = _make_biome_material("mat_biome", height, biome_key)
    obj = build_terrain_mesh(height, "terrain", z_scale=z_scale)
    obj.data.materials.append(mat)


def _scene_feature(height: np.ndarray, biome_key: str, pass_name: str) -> None:
    z_scale = _ZSCALE.get(biome_key, 0.6)
    feature_channels = [
        ("cliff_candidate",      (0.85, 0.45, 0.05)),
        ("cave_candidate",       (0.25, 0.10, 0.45)),
        ("waterfall_lip_candidate", (0.10, 0.55, 0.90)),
        ("overhang_candidate",   (0.70, 0.20, 0.70)),
        ("karst_dissolution",    (0.50, 0.80, 0.70)),
        ("coastline_curvature",  (0.10, 0.40, 0.80)),
    ]
    overlay = None
    low_col = (0.1, 0.1, 0.1)
    high_col = (1.0, 0.5, 0.0)
    for ch_name, col in feature_channels:
        arr = _npy(pass_name, biome_key, ch_name)
        if arr is not None and arr.max() > 0:
            overlay = arr
            high_col = col
            break
    if overlay is not None:
        mat = _make_overlay_material("mat_feature", height, biome_key, overlay, low_col, high_col, blend=0.70)
    else:
        mat = _make_biome_material("mat_feature", height, biome_key)
    obj = build_terrain_mesh(height, "terrain", z_scale=z_scale)
    obj.data.materials.append(mat)


def _scene_scatter(height: np.ndarray, biome_key: str, pass_name: str) -> None:
    z_scale = _ZSCALE.get(biome_key, 0.6)
    mat = _make_biome_material("mat_scatter_base", height, biome_key)
    obj = build_terrain_mesh(height, "terrain", z_scale=z_scale)
    obj.data.materials.append(mat)
    # Grass density overlay
    density = _npy(pass_name, biome_key, "grass_density_map")
    if density is None:
        density = _npy(pass_name, biome_key, "vegetation_depth")
    if density is None:
        # Try any density channel
        for ch in ["detail_density", "scatter_density", "tree_instance_points"]:
            density = _npy(pass_name, biome_key, ch)
            if density is not None:
                break
    if density is not None and density.max() > 0:
        add_grass_sprites(height, density, tile_m=256.0, z_scale=z_scale,
                          n_sprites=300, biome_key=biome_key)


def _scene_material(height: np.ndarray, biome_key: str, pass_name: str) -> None:
    z_scale = _ZSCALE.get(biome_key, 0.6)
    # Splatmap layers with distinct colours
    splatmap_cols = [
        (0.65, 0.45, 0.20),  # layer 0: dirt/rock
        (0.15, 0.55, 0.15),  # layer 1: grass
        (0.60, 0.60, 0.60),  # layer 2: rock/stone
        (0.90, 0.90, 0.95),  # layer 3: snow
        (0.35, 0.18, 0.08),  # layer 4: mud/dark
    ]
    bands = []
    for i, col in enumerate(splatmap_cols):
        for ch in [f"splatmap_layer_{i}", f"splat_{i}", f"layer_{i}", f"material_{i}"]:
            arr = _npy(pass_name, biome_key, ch)
            if arr is not None and arr.max() > 0:
                bands.append((arr, col))
                break
    if not bands:
        # Try macro_color or roughness
        for ch in ["macro_color", "roughness", "macro_breakup"]:
            arr = _npy(pass_name, biome_key, ch)
            if arr is not None and arr.max() > arr.min():
                bands.append((arr, (0.55, 0.45, 0.30)))
                break
    if bands:
        mat = _make_multiband_material("mat_material", height, biome_key, bands)
    else:
        mat = _make_biome_material("mat_material", height, biome_key)
    obj = build_terrain_mesh(height, "terrain", z_scale=z_scale)
    obj.data.materials.append(mat)


def _scene_gameplay(height: np.ndarray, biome_key: str, pass_name: str) -> None:
    z_scale = _ZSCALE.get(biome_key, 0.6)
    zone_channels = [
        ("navmesh_walkable",   (0.20, 0.80, 0.20)),
        ("audio_zone",         (0.80, 0.50, 0.10)),
        ("gameplay_zone",      (0.10, 0.60, 0.90)),
        ("cloud_shadow_mask",  (0.40, 0.40, 0.70)),
        ("road_sdf_dist",      (0.70, 0.55, 0.25)),
        ("wildlife_zone",      (0.55, 0.75, 0.25)),
        ("wind_speed",         (0.70, 0.80, 0.90)),
        ("fog_density",        (0.60, 0.65, 0.80)),
    ]
    overlay = None
    high_col = (0.20, 0.80, 0.20)
    for ch_name, col in zone_channels:
        arr = _npy(pass_name, biome_key, ch_name)
        if arr is not None and arr.max() > 0:
            overlay = arr
            high_col = col
            break
    if overlay is not None:
        mat = _make_overlay_material("mat_gameplay", height, biome_key, overlay,
                                     (0.05, 0.05, 0.05), high_col, blend=0.55)
    else:
        mat = _make_biome_material("mat_gameplay", height, biome_key)
    obj = build_terrain_mesh(height, "terrain", z_scale=z_scale)
    obj.data.materials.append(mat)


def _scene_export(height: np.ndarray, biome_key: str, pass_name: str) -> None:
    z_scale = _ZSCALE.get(biome_key, 0.6)
    export_channels = [
        "heightmap_raw_u16", "terrain_normal_x", "terrain_normal_y", "terrain_normal_z",
        "unity_splat_r", "unity_splat_g",
    ]
    overlay = None
    for ch in export_channels:
        arr = _npy(pass_name, biome_key, ch)
        if arr is not None and arr.max() > arr.min():
            overlay = arr
            break
    if overlay is not None:
        mat = _make_overlay_material("mat_export", height, biome_key, overlay,
                                     (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), blend=0.80)
    else:
        mat = _make_biome_material("mat_export", height, biome_key)
    obj = build_terrain_mesh(height, "terrain", z_scale=z_scale)
    obj.data.materials.append(mat)


def _scene_validation(height: np.ndarray, biome_key: str, pass_name: str) -> None:
    # Grey terrain — validation doesn't transform terrain
    z_scale = _ZSCALE.get(biome_key, 0.6)
    mat = _make_biome_material("mat_validation", height, biome_key)
    obj = build_terrain_mesh(height, "terrain", z_scale=z_scale)
    obj.data.materials.append(mat)


_SCENE_BUILDERS = {
    "terrain_gen": _scene_terrain_gen,
    "erosion":     _scene_erosion,
    "water":       _scene_water,
    "structural":  _scene_structural,
    "biome":       _scene_biome,
    "feature":     _scene_feature,
    "scatter":     _scene_scatter,
    "material":    _scene_material,
    "gameplay":    _scene_gameplay,
    "export":      _scene_export,
    "validation":  _scene_validation,
}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main() -> None:
    if not MANIFEST_PATH.exists():
        print(f"[RENDERER] ERROR: manifest not found: {MANIFEST_PATH}")
        sys.exit(1)

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    results: dict = manifest.get("results", {})
    total = sum(len(v) for v in results.values())
    done = renders_saved = failures = 0
    t0 = time.time()

    for pass_name, biome_data in results.items():
        category = _cat(pass_name)
        builder = _SCENE_BUILDERS.get(category, _scene_terrain_gen)

        for biome_key, run_result in biome_data.items():
            done += 1
            out_dir = REPO_ROOT / "renders" / "quality-audit" / pass_name
            out_dir.mkdir(parents=True, exist_ok=True)

            try:
                height_raw = _load_height(pass_name, biome_key, manifest)
                if height_raw is None:
                    print(f"[RENDERER] SKIP {pass_name}/{biome_key}: no height")
                    continue
                if height_raw.ndim != 2:
                    continue

                # Smooth to remove raw noise spikes
                height = _smooth_height(height_raw.astype(np.float32), biome_key)

                reset_scene()
                setup_eevee()
                add_lighting()

                builder(height, biome_key, pass_name)

                z_scale = _ZSCALE.get(biome_key, 0.6)
                height_vis = height * z_scale

                _render_three_angles(str(out_dir / biome_key), height_vis)
                renders_saved += 3
                elapsed = time.time() - t0
                print(
                    f"[RENDERER] {done}/{total} {pass_name}/{biome_key} [{category}] "
                    f"— 3 renders ({elapsed:.1f}s)"
                )

            except Exception:  # noqa: BLE001
                failures += 1
                print(f"[RENDERER] FAIL {pass_name}/{biome_key}: {traceback.format_exc().strip()}")

    elapsed = time.time() - t0
    print(f"[RENDERER] DONE — {renders_saved} renders, {failures} failures, {elapsed:.1f}s")


if __name__ == "__main__":
    main()

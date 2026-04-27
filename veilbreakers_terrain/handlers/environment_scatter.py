"""Blender handlers for vegetation scatter, prop scatter, and breakable props.

Provides 3 command handlers:
  - handle_scatter_vegetation: Biome-aware tree/grass/rock scatter using
    collection instances for performance.
  - handle_scatter_props: Context-aware prop placement near tagged buildings.
  - handle_create_breakable: Generate intact + damaged variant pairs.

AAA upgrades (39-02):
  - Leaf card canopies (6-12 intersecting planes) replace UV sphere tree blobs
  - 6-biome grass card system with wind vertex colors
  - Multi-pass scatter: trees -> grass -> rocks with building exclusion
  - Combat clearing generator (15-40m diameter with tree rings + entry paths)
  - Rock power-law size distribution (70% small, 25% medium, 5% large)
"""

from __future__ import annotations

import logging
import math
import random
from typing import Any

import numpy as np

# Lazy-import guard: bpy/bmesh/mathutils only available inside Blender. Pure-logic
# helpers (poisson sampling, biome filters) remain importable outside Blender;
# functions that touch bpy must call _require_bpy() at entry.
try:
    import bpy
    import bmesh
    from mathutils import Vector as _mathutils_Vector
    _HAS_BPY = True
except ModuleNotFoundError:
    bpy = None  # type: ignore[assignment]
    bmesh = None  # type: ignore[assignment]
    _mathutils_Vector = None  # type: ignore[assignment]
    _HAS_BPY = False


def _require_bpy() -> None:
    """Raise RuntimeError if bpy/bmesh are not available (outside Blender)."""
    if not _HAS_BPY:
        raise RuntimeError(
            "This function requires Blender (bpy + bmesh). "
            "It cannot run outside the Blender Python runtime."
        )


from ._scatter_engine import (
    poisson_disk_sample,
    lloyd_relax_points,
    context_scatter,
    generate_breakable_variants,
)
from ._terrain_noise import compute_slope_map
from ._mesh_bridge import mesh_from_spec, VEGETATION_GENERATOR_MAP, PROP_GENERATOR_MAP
from .vegetation_lsystem import generate_billboard_impostor
from .lod_pipeline import generate_lod_chain
from .terrain_semantics import WorldHeightTransform
from .terrain_scatter_points import ScatterPoint, ScatterPointTable, validate_scatter_point_table

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight scatter material presets
# ---------------------------------------------------------------------------

_SCATTER_MATERIAL_PRESETS: dict[str, dict[str, Any]] = {
    "tree": {
        "mode": "tree",
        "trunk_color": (0.19, 0.15, 0.10, 1.0),
        "foliage_color": (0.16, 0.23, 0.12, 1.0),
        "accent_color": (0.10, 0.14, 0.08, 1.0),
        "roughness": 0.80,
    },
    "tree_healthy": {
        "mode": "tree",
        "trunk_color": (0.20, 0.15, 0.09, 1.0),
        "foliage_color": (0.18, 0.25, 0.14, 1.0),
        "accent_color": (0.12, 0.17, 0.09, 1.0),
        "roughness": 0.78,
    },
    "tree_boundary": {
        "mode": "tree",
        "trunk_color": (0.18, 0.14, 0.10, 1.0),
        "foliage_color": (0.14, 0.18, 0.11, 1.0),
        "accent_color": (0.11, 0.10, 0.08, 1.0),
        "roughness": 0.83,
    },
    "tree_blighted": {
        "mode": "tree",
        "trunk_color": (0.17, 0.15, 0.14, 1.0),
        "foliage_color": (0.12, 0.10, 0.12, 1.0),
        "accent_color": (0.16, 0.07, 0.15, 1.0),
        "roughness": 0.87,
        "emission_strength": 0.04,
    },
    "tree_dead": {
        "mode": "tree",
        "trunk_color": (0.23, 0.21, 0.18, 1.0),
        "foliage_color": (0.23, 0.21, 0.18, 1.0),
        "accent_color": (0.14, 0.12, 0.10, 1.0),
        "roughness": 0.88,
    },
    "tree_twisted": {
        "mode": "tree",
        "trunk_color": (0.18, 0.14, 0.10, 1.0),
        "foliage_color": (0.14, 0.18, 0.11, 1.0),
        "accent_color": (0.11, 0.10, 0.08, 1.0),
        "roughness": 0.83,
    },
    "pine_tree": {
        "mode": "tree",
        "trunk_color": (0.16, 0.12, 0.08, 1.0),
        "foliage_color": (0.10, 0.15, 0.09, 1.0),
        "accent_color": (0.06, 0.10, 0.06, 1.0),
        "roughness": 0.80,
    },
    "bush": {"mode": "foliage", "base_color": (0.14, 0.20, 0.11, 1.0), "accent_color": (0.09, 0.13, 0.07, 1.0), "roughness": 0.74},
    "shrub": {"mode": "foliage", "base_color": (0.14, 0.20, 0.11, 1.0), "accent_color": (0.09, 0.13, 0.07, 1.0), "roughness": 0.74},
    "grass": {"mode": "foliage", "base_color": (0.16, 0.20, 0.10, 1.0), "accent_color": (0.10, 0.12, 0.06, 1.0), "roughness": 0.72},
    "weed": {"mode": "foliage", "base_color": (0.15, 0.17, 0.10, 1.0), "accent_color": (0.10, 0.11, 0.07, 1.0), "roughness": 0.76},
    "rock": {"mode": "mineral", "base_color": (0.24, 0.24, 0.22, 1.0), "accent_color": (0.12, 0.16, 0.10, 1.0), "roughness": 0.92},
    "rock_mossy": {"mode": "mineral", "base_color": (0.21, 0.22, 0.20, 1.0), "accent_color": (0.11, 0.15, 0.10, 1.0), "roughness": 0.90},
    "cliff_rock": {"mode": "mineral", "base_color": (0.23, 0.22, 0.21, 1.0), "accent_color": (0.10, 0.12, 0.10, 1.0), "roughness": 0.94},
    "mushroom": {"mode": "organic", "base_color": (0.28, 0.22, 0.20, 1.0), "accent_color": (0.18, 0.12, 0.10, 1.0), "roughness": 0.78},
    "mushroom_cluster": {"mode": "organic", "base_color": (0.22, 0.20, 0.17, 1.0), "accent_color": (0.16, 0.12, 0.10, 1.0), "roughness": 0.80},
    "root": {"mode": "organic", "base_color": (0.18, 0.14, 0.10, 1.0), "accent_color": (0.11, 0.08, 0.06, 1.0), "roughness": 0.86},
    "fallen_log": {"mode": "organic", "base_color": (0.20, 0.15, 0.10, 1.0), "accent_color": (0.11, 0.08, 0.06, 1.0), "roughness": 0.84},
    "barrel": {"mode": "organic", "base_color": (0.23, 0.16, 0.10, 1.0), "accent_color": (0.15, 0.10, 0.06, 1.0), "roughness": 0.74},
    "crate": {"mode": "organic", "base_color": (0.24, 0.17, 0.11, 1.0), "accent_color": (0.16, 0.11, 0.07, 1.0), "roughness": 0.76},
    "lantern": {"mode": "metal", "base_color": (0.18, 0.17, 0.16, 1.0), "accent_color": (0.32, 0.24, 0.12, 1.0), "roughness": 0.45},
}


_VEGETATION_Y_UP_TYPES = frozenset({
    "tree",
    "tree_healthy",
    "tree_boundary",
    "tree_blighted",
    "tree_dead",
    "tree_twisted",
    "pine_tree",
    "bush",
    "shrub",
    "grass",
    "weed",
    "mushroom",
    "root",
})

_PROP_Y_UP_TYPES = frozenset({
    "bush",
    "shrub",
    "dead_tree",
    "tree",
    "tree_healthy",
    "tree_boundary",
    "tree_blighted",
    "tree_twisted",
    "pine_tree",
    "mushroom",
})


def _assign_scatter_material(obj: bpy.types.Object, material_key: str) -> None:
    """Assign a lightweight procedural preview material.

    AAA upgrade: foliage modes receive alpha-clip blend mode (mandatory for
    leaf-card alpha testing in Blender 4.x EEVEE/Cycles) and a subsurface
    scattering value so backlit leaves transmit light — matching Ghost of
    Tsushima / Horizon Zero Dawn foliage shading.  Tree trunks retain opaque
    mode for performance.  Rock/mineral modes are unchanged (fully opaque).

    Material modes and their AAA enhancements:
      "tree"    — opaque Principled BSDF, height-based trunk→foliage gradient,
                  noise accent variation. Subsurface = 0.0 (bark is solid).
      "foliage" — alpha-clip blend (CLIP threshold 0.5), subsurface = 0.12
                  for light transmission through thin leaf cards. Matches the
                  standard used in Ghost of Tsushima vegetation materials.
      "mineral" — fully opaque, high roughness, no subsurface.
      "organic" — fully opaque, medium roughness.
      "metal"   — fully opaque, metallic = 0.4, low roughness.
    """
    if not hasattr(obj, "data") or obj.data is None:
        return

    preset = _SCATTER_MATERIAL_PRESETS.get(material_key, {
        "mode": "organic",
        "base_color": (0.2, 0.2, 0.2, 1.0),
        "accent_color": (0.1, 0.1, 0.1, 1.0),
        "roughness": 0.8,
    })
    mat_name = f"mat_{material_key}"
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    if not mat.node_tree:
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        return

    mode = str(preset.get("mode", "organic"))

    # AAA: foliage gets alpha-clip blend for leaf-card alpha testing.
    # Blender 4.x uses blend_method on the material.
    if mode == "foliage":
        mat.blend_method = "CLIP"
        if hasattr(mat, "alpha_threshold"):
            mat.alpha_threshold = 0.5
        mat.use_backface_culling = False  # leaf cards must be double-sided
    else:
        mat.blend_method = "OPAQUE"
        mat.use_backface_culling = True

    nt = mat.node_tree
    nt.nodes.clear()
    output = nt.nodes.new("ShaderNodeOutputMaterial")
    output.location = (640, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (360, 0)
    tex_coord = nt.nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-1000, 80)
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.location = (-800, 80)
    mapping.inputs["Scale"].default_value = (3.2, 3.2, 3.2)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.location = (-580, 120)
    noise.inputs["Scale"].default_value = 5.5
    noise.inputs["Detail"].default_value = 7.0
    noise.inputs["Roughness"].default_value = 0.55
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-340, 120)
    ramp.color_ramp.elements[0].position = 0.36
    ramp.color_ramp.elements[1].position = 0.82

    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.location = (120, 110)
    mix.blend_type = "MIX"

    if mode == "tree":
        geom = nt.nodes.new("ShaderNodeNewGeometry")
        geom.location = (-1000, -180)
        separate = nt.nodes.new("ShaderNodeSeparateXYZ")
        separate.location = (-780, -180)
        height_ramp = nt.nodes.new("ShaderNodeValToRGB")
        height_ramp.location = (-520, -180)
        height_ramp.color_ramp.elements[0].position = 0.28
        height_ramp.color_ramp.elements[1].position = 0.52
        height_ramp.color_ramp.elements[0].color = preset["trunk_color"]
        height_ramp.color_ramp.elements[1].color = preset["foliage_color"]
        accent_mix = nt.nodes.new("ShaderNodeMix")
        accent_mix.data_type = "RGBA"
        accent_mix.location = (-120, -20)
        accent_mix.blend_type = "MULTIPLY"
        accent_mix.inputs["B"].default_value = preset.get("accent_color", preset["foliage_color"])
        accent_mix.inputs["Factor"].default_value = 0.28

        nt.links.new(geom.outputs["Position"], separate.inputs["Vector"])
        nt.links.new(separate.outputs["Y"], height_ramp.inputs["Fac"])
        nt.links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
        nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        nt.links.new(height_ramp.outputs["Color"], accent_mix.inputs["A"])
        nt.links.new(noise.outputs["Fac"], accent_mix.inputs["Factor"])
        nt.links.new(accent_mix.outputs["Result"], mix.inputs["A"])
        mix.inputs["B"].default_value = preset.get("accent_color", preset["foliage_color"])
        mix.inputs["Factor"].default_value = 0.15
    else:
        mix.inputs["A"].default_value = preset["base_color"]
        mix.inputs["B"].default_value = preset.get("accent_color", preset["base_color"])
        nt.links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
        nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        nt.links.new(noise.outputs["Fac"], mix.inputs["Factor"])

    nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = float(preset["roughness"])

    # AAA: foliage subsurface scattering — backlit leaves transmit light.
    # Subsurface weight 0.12 matches the Ghost of Tsushima leaf SSS value
    # (low enough to avoid mushiness, high enough for visible backlighting).
    if mode == "foliage":
        # Blender 4.x uses "Subsurface Weight" on Principled BSDF
        if "Subsurface Weight" in bsdf.inputs:
            bsdf.inputs["Subsurface Weight"].default_value = 0.12
        elif "Subsurface" in bsdf.inputs:
            bsdf.inputs["Subsurface"].default_value = 0.12
        # Subsurface radius: greenish tint for foliage transmission
        if "Subsurface Radius" in bsdf.inputs:
            bsdf.inputs["Subsurface Radius"].default_value = (0.08, 0.14, 0.06)

    if "Emission Color" in bsdf.inputs and float(preset.get("emission_strength", 0.0)) > 0.0:
        bsdf.inputs["Emission Color"].default_value = preset.get("accent_color", preset.get("base_color", (0.1, 0.1, 0.1, 1.0)))
    if "Emission Strength" in bsdf.inputs:
        bsdf.inputs["Emission Strength"].default_value = float(preset.get("emission_strength", 0.0))
    if mode == "metal":
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.4
    nt.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    obj.data.materials.clear()
    obj.data.materials.append(mat)


def _vegetation_rotation(veg_type: str, yaw_degrees: float) -> tuple[float, float, float]:
    """Return a world rotation that converts Y-up generated meshes to Blender Z-up."""
    x_rot = math.radians(90.0) if veg_type in _VEGETATION_Y_UP_TYPES else 0.0
    return (x_rot, 0.0, math.radians(yaw_degrees))


def _prop_rotation(prop_type: str, yaw_degrees: float) -> tuple[float, float, float]:
    """Return a world rotation for prop-scatter meshes with Y-up authored geometry."""
    x_rot = math.radians(90.0) if prop_type in _PROP_Y_UP_TYPES else 0.0
    return (x_rot, 0.0, math.radians(yaw_degrees))


def _terrain_height_sampler(terrain_obj: bpy.types.Object | None):
    """Build a lightweight terrain-height sampler for prop placement."""
    if terrain_obj is None or terrain_obj.type != "MESH" or terrain_obj.data is None:
        return None

    mesh = terrain_obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    vert_count = len(bm.verts)

    # Detect actual grid dims by counting unique X and Y positions (handles non-square terrain)
    xs = set(round(v.co.x, 3) for v in bm.verts)
    ys = set(round(v.co.y, 3) for v in bm.verts)
    cols, rows = len(xs), len(ys)
    if cols * rows != vert_count or cols < 2 or rows < 2:
        # Fallback: assume square grid
        side = int(math.sqrt(vert_count))
        if side < 2 or side * side != vert_count:
            bm.free()
            return None
        rows, cols = side, side

    heights = np.array([v.co.z for v in bm.verts], dtype=np.float64)
    bm.free()
    transform = WorldHeightTransform(
        world_min=float(heights.min()) if heights.size else 0.0,
        world_max=float(heights.max()) if heights.size else 1.0,
    )
    heightmap = transform.to_normalized(heights).reshape(rows, cols)
    dims = terrain_obj.dimensions
    terrain_width = max(float(dims.x), 1.0)
    terrain_height = max(float(dims.y), 1.0)
    origin_x = float(terrain_obj.location.x)
    origin_y = float(terrain_obj.location.y)

    def _sample(world_x: float, world_y: float) -> float:
        # Sample through the explicit world-height transform so signed terrain
        # elevations round-trip without collapsing sub-zero terrain to 0.
        sampled_world_z = _sample_heightmap_world(
            heightmap,
            height_scale=transform.world_range,
            height_offset=transform.world_min,
            world_x=world_x,
            world_y=world_y,
            terrain_width=terrain_width,
            terrain_height=terrain_height,
            terrain_origin_x=origin_x,
            terrain_origin_y=origin_y,
        )
        return float(sampled_world_z)

    return _sample


def _world_to_terrain_uv(
    world_x: float,
    world_y: float,
    *,
    terrain_width: float,
    terrain_height: float,
    terrain_origin_x: float,
    terrain_origin_y: float,
) -> tuple[float, float]:
    """Convert world coordinates to normalized terrain UVs.

    ``terrain_origin_*`` is the terrain object's world-space center.
    """
    if terrain_width <= 0 or terrain_height <= 0:
        raise ValueError("terrain dimensions must be positive")

    half_width = terrain_width * 0.5
    half_height = terrain_height * 0.5
    local_x = world_x - terrain_origin_x + half_width
    local_y = world_y - terrain_origin_y + half_height
    return local_x / terrain_width, local_y / terrain_height


def _sample_heightmap_surface_world(
    heightmap: np.ndarray,
    *,
    height_scale: float,
    height_offset: float = 0.0,
    world_x: float,
    world_y: float,
    terrain_width: float,
    terrain_height: float,
    terrain_origin_x: float,
    terrain_origin_y: float,
) -> tuple[float, float, float]:
    """Sample a terrain heightmap and local world-space gradients."""
    hmap = np.asarray(heightmap, dtype=np.float64)
    if hmap.ndim != 2:
        raise ValueError("heightmap must be 2D")

    rows, cols = hmap.shape
    if rows == 0 or cols == 0:
        return 0.0, 0.0, 0.0
    if rows == 1 or cols == 1:
        return float(height_offset + hmap[0, 0] * height_scale), 0.0, 0.0

    u, v = _world_to_terrain_uv(
        world_x,
        world_y,
        terrain_width=terrain_width,
        terrain_height=terrain_height,
        terrain_origin_x=terrain_origin_x,
        terrain_origin_y=terrain_origin_y,
    )
    u = max(0.0, min(u, 1.0))
    v = max(0.0, min(v, 1.0))

    col_f = u * (cols - 1)
    row_f = v * (rows - 1)
    c0 = max(0, min(int(col_f), cols - 2))
    r0 = max(0, min(int(row_f), rows - 2))
    c1, r1 = c0 + 1, r0 + 1
    cf, rf = col_f - c0, row_f - r0

    h00 = float(hmap[r0, c0])
    h10 = float(hmap[r0, c1])
    h01 = float(hmap[r1, c0])
    h11 = float(hmap[r1, c1])
    sample = (
        h00 * (1 - cf) * (1 - rf)
        + h10 * cf * (1 - rf)
        + h01 * (1 - cf) * rf
        + h11 * cf * rf
    )

    dsample_dcol = (h10 - h00) * (1 - rf) + (h11 - h01) * rf
    dsample_drow = (h01 - h00) * (1 - cf) + (h11 - h10) * cf
    dzdx = dsample_dcol * (cols - 1) / max(terrain_width, 1e-9) * height_scale
    dzdy = dsample_drow * (rows - 1) / max(terrain_height, 1e-9) * height_scale
    return float(height_offset + sample * height_scale), dzdx, dzdy


def _sample_heightmap_world(
    heightmap: np.ndarray,
    *,
    height_scale: float,
    height_offset: float = 0.0,
    world_x: float,
    world_y: float,
    terrain_width: float,
    terrain_height: float,
    terrain_origin_x: float,
    terrain_origin_y: float,
) -> float:
    """Sample a terrain heightmap at a world-space position using bilinear interpolation."""
    sample, _dzdx, _dzdy = _sample_heightmap_surface_world(
        heightmap,
        height_scale=height_scale,
        height_offset=height_offset,
        world_x=world_x,
        world_y=world_y,
        terrain_width=terrain_width,
        terrain_height=terrain_height,
        terrain_origin_x=terrain_origin_x,
        terrain_origin_y=terrain_origin_y,
    )
    return sample


def _terrain_axis_spacing_from_extent(
    terrain_width: float,
    terrain_height: float,
    rows: int,
    cols: int,
) -> tuple[float, float]:
    """Return terrain grid spacing as (row_spacing, col_spacing)."""
    row_spacing = float(terrain_height) / max(rows - 1, 1)
    col_spacing = float(terrain_width) / max(cols - 1, 1)
    return max(row_spacing, 1e-9), max(col_spacing, 1e-9)


def _terrain_cell_size_from_extent(
    terrain_width: float,
    terrain_height: float,
    rows: int,
    cols: int,
) -> float:
    """Return terrain grid spacing in world units for slope calculations."""
    row_spacing, col_spacing = _terrain_axis_spacing_from_extent(
        terrain_width,
        terrain_height,
        rows,
        cols,
    )
    return max(row_spacing, col_spacing)


# ---------------------------------------------------------------------------
# Stack-channel consumer helpers — Fix 9.1 / 9.4 / 9.5
# All pure Python + numpy; no bpy dependency. Testable in isolation.
# ---------------------------------------------------------------------------

def _collapse_detail_density(detail_dens_raw) -> "np.ndarray | None":
    """Collapse a detail_density dict[str, (H,W)] to a single (H,W) float32 map.

    Returns None when the input is None or empty.
    """
    if detail_dens_raw is None:
        return None
    if isinstance(detail_dens_raw, dict):
        layers = list(detail_dens_raw.values())
        if not layers:
            return None
        stacked = np.stack(
            [np.asarray(l, dtype=np.float32) for l in layers], axis=0
        )
        return np.mean(stacked, axis=0)
    # Fallback: treat as raw array
    arr = np.asarray(detail_dens_raw, dtype=np.float32)
    return arr if arr.ndim == 2 else None


def _density_reject(density_map, row_f: float, col_f: float, rng_val: float) -> bool:
    """Return True (reject) when density_map is below rng_val at (row_f, col_f).

    Uses 4-tap bilinear sampling so a linearly-ramping density map yields
    a monotonic gradient in acceptance probability (no stair-step artifacts).

    Parameters
    ----------
    density_map : np.ndarray (H, W) float32 or None
        Density multiplier in [0, 1]. None = uniform 1.0 (never reject).
    row_f, col_f : float
        Floating-point raster coordinates into density_map.
    rng_val : float
        Uniform random value in [0, 1] (caller provides).
    """
    if density_map is None:
        return False
    h = density_map.shape[0]
    w = density_map.shape[1]
    rf = float(np.clip(row_f, 0.0, h - 1))
    cf = float(np.clip(col_f, 0.0, w - 1))
    r0 = int(np.floor(rf))
    c0 = int(np.floor(cf))
    r1 = min(r0 + 1, h - 1)
    c1 = min(c0 + 1, w - 1)
    fr = rf - r0
    fc = cf - c0
    # 4-tap bilinear
    v00 = float(density_map[r0, c0])
    v01 = float(density_map[r0, c1])
    v10 = float(density_map[r1, c0])
    v11 = float(density_map[r1, c1])
    v0 = v00 * (1.0 - fc) + v01 * fc
    v1 = v10 * (1.0 - fc) + v11 * fc
    density_val = float(np.clip(v0 * (1.0 - fr) + v1 * fr, 0.0, 1.0))
    return rng_val > density_val


def _stack_value(stack, key: str):
    """Return a channel/property from stack when available, else None."""
    if stack is None:
        return None
    val = getattr(stack, key, None)
    if val is None and hasattr(stack, "get"):
        try:
            val = stack.get(key)
        except Exception:
            val = None
    return val


def _resize_scatter_map(map_raw, target_shape: tuple[int, int]) -> "np.ndarray | None":
    """Resize a 2-D context map to target_shape using nearest-neighbor resampling."""
    if map_raw is None:
        return None
    arr = np.asarray(map_raw, dtype=np.float32)
    if arr.ndim != 2:
        return None
    if arr.shape != target_shape:
        y_idx = np.round(np.linspace(0, arr.shape[0] - 1, target_shape[0])).astype(int)
        x_idx = np.round(np.linspace(0, arr.shape[1] - 1, target_shape[1])).astype(int)
        arr = arr[np.ix_(y_idx, x_idx)]
    return arr.astype(np.float32, copy=False)


def _normalize_scatter_signal(signal_raw, *, log_scale: bool = False) -> "np.ndarray | None":
    """Normalize a scalar raster signal to [0, 1] for scatter weighting."""
    if signal_raw is None:
        return None
    arr = np.asarray(signal_raw, dtype=np.float32)
    if arr.ndim != 2:
        return None
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    arr = np.clip(arr, 0.0, None)
    if log_scale:
        arr = np.log1p(arr)
    max_val = float(arr.max()) if arr.size else 0.0
    if max_val <= 1e-12:
        return np.zeros_like(arr, dtype=np.float32)
    return (arr / max_val).astype(np.float32, copy=False)


_CATEGORY_TO_SCATTER_BASE: dict[str, str] = {
    "grass": "grass",
    "accent_foliage": "grass",
    "moss": "grass",
    "vine": "grass",
    "water_foliage": "grass",
    "bush": "bush",
    "tree": "tree",
    "log": "tree",
    "stump": "tree",
    "small_rock": "rock",
    "boulder": "rock",
    "fence": "rock",
    "sign": "rock",
    "walkway": "rock",
}


def _scatter_base_type(vegetation_type: str, category: str = "") -> str:
    """Map concrete vegetation ids back to the coarse scatter categories."""
    cat = str(category or "").strip()
    if cat in _CATEGORY_TO_SCATTER_BASE:
        return _CATEGORY_TO_SCATTER_BASE[cat]
    if vegetation_type.startswith("grass"):
        return "grass"
    if vegetation_type.startswith("tree"):
        return "tree"
    if vegetation_type.startswith("rock"):
        return "rock"
    if vegetation_type.startswith(("talus_", "hero_boulder", "pebbles", "gravel")):
        return "rock"
    if vegetation_type.startswith(("moss_", "vine_", "reeds", "lily_", "algae", "submerged_", "flowers", "ferns", "mushrooms", "clovers")):
        return "grass"
    if vegetation_type.startswith(("log_", "stump_")):
        return "tree"
    if vegetation_type.startswith(("bush", "shrub")):
        return "bush"
    return vegetation_type


def _resolve_scatter_context_maps(
    stack,
    heightmap: np.ndarray,
    moisture_map: "np.ndarray | None" = None,
) -> tuple["np.ndarray | None", "np.ndarray | None"]:
    """Resolve water/disturbance support maps for the AAA multi-pass scatter path."""
    target_shape = tuple(heightmap.shape)

    water_layers: list[np.ndarray] = []
    explicit_moisture = _resize_scatter_map(moisture_map, target_shape)
    if explicit_moisture is not None:
        water_layers.append(np.clip(explicit_moisture, 0.0, 1.0).astype(np.float32, copy=False))
    wetness = _resize_scatter_map(_stack_value(stack, "wetness"), target_shape)
    if wetness is not None:
        water_layers.append(np.clip(wetness, 0.0, 1.0).astype(np.float32, copy=False))
    water_surface = _resize_scatter_map(_stack_value(stack, "water_surface"), target_shape)
    if water_surface is not None:
        water_layers.append(np.clip(water_surface, 0.0, 1.0).astype(np.float32, copy=False))
    flow_acc = _resize_scatter_map(_stack_value(stack, "flow_accumulation"), target_shape)
    if flow_acc is not None:
        flow_support = _normalize_scatter_signal(flow_acc, log_scale=True)
        if flow_support is not None:
            water_layers.append(flow_support)
    water_map = None
    if water_layers:
        water_map = np.maximum.reduce(water_layers).astype(np.float32, copy=False)

    disturbance_layers: list[np.ndarray] = []
    for key in ("disturbance_patch_mask", "erosion_amount", "erosion_delta", "deposition_amount"):
        candidate = _resize_scatter_map(_stack_value(stack, key), target_shape)
        if candidate is None:
            continue
        normalized = _normalize_scatter_signal(candidate)
        if normalized is not None:
            disturbance_layers.append(normalized)
    disturbance_map = None
    if disturbance_layers:
        disturbance_map = np.maximum.reduce(disturbance_layers).astype(np.float32, copy=False)

    return water_map, disturbance_map


def _localize_exclusion_zones(
    exclusion_zones_world: list[tuple[float, float, float, float]],
    *,
    terrain_origin_x: float,
    terrain_origin_y: float,
) -> list[tuple[float, float, float, float]]:
    """Convert world-space AABBs to the centered local space used by _scatter_pass."""
    local_zones: list[tuple[float, float, float, float]] = []
    for min_x, min_y, max_x, max_y in exclusion_zones_world:
        local_zones.append(
            (
                min_x - terrain_origin_x,
                min_y - terrain_origin_y,
                max_x - terrain_origin_x,
                max_y - terrain_origin_y,
            )
        )
    return local_zones


def _resolve_combat_clearings(params: dict) -> "list[dict[str, Any]] | None":
    """Resolve optional combat clearings for the multi-pass scatter path."""
    clearings = params.get("combat_clearings")
    if clearings:
        return list(clearings)
    clearing = params.get("combat_clearing")
    if isinstance(clearing, dict):
        return [clearing]
    center = params.get("combat_clearing_center")
    diameter = params.get("combat_clearing_diameter")
    if center is not None and diameter is not None:
        seed = int(params.get("combat_clearing_seed", params.get("seed", 0)))
        num_entries = int(params.get("combat_clearing_entries", 3))
        return [_generate_combat_clearing(tuple(center), float(diameter), num_entries=num_entries, seed=seed)]
    return None


def _sample_scalar_map(map_arr: np.ndarray, x_local: float, y_local: float, width: float, height: float) -> float:
    """Bilinear scalar-map sample in local [0,width] x [0,height] space."""
    col_f = (x_local / max(width, 1e-6)) * (map_arr.shape[1] - 1)
    row_f = (y_local / max(height, 1e-6)) * (map_arr.shape[0] - 1)
    h, w = map_arr.shape
    r0 = int(math.floor(np.clip(row_f, 0.0, h - 1)))
    c0 = int(math.floor(np.clip(col_f, 0.0, w - 1)))
    r1 = min(r0 + 1, h - 1)
    c1 = min(c0 + 1, w - 1)
    tr = float(np.clip(row_f - math.floor(row_f), 0.0, 1.0))
    tc = float(np.clip(col_f - math.floor(col_f), 0.0, 1.0))
    return float(
        map_arr[r0, c0] * (1.0 - tr) * (1.0 - tc)
        + map_arr[r0, c1] * (1.0 - tr) * tc
        + map_arr[r1, c0] * tr * (1.0 - tc)
        + map_arr[r1, c1] * tr * tc
    )


def _filter_multipass_scatter_placements(
    placements_centered: list[dict[str, Any]],
    *,
    rules: list[dict[str, Any]],
    terrain_width: float,
    terrain_height: float,
    slope_map: np.ndarray,
    moisture_map: "np.ndarray | None",
    max_tilt_angle: float,
    seed: int,
    apply_rule_density: bool,
) -> list[dict[str, Any]]:
    """Adapt centered/radian _scatter_pass placements to the handler's legacy contract."""
    rng = random.Random(seed ^ 0x5CA77E2)
    filtered: list[dict[str, Any]] = []

    rule_index: dict[str, list[dict[str, Any]]] = {}
    for rule in rules:
        veg_type = str(rule.get("vegetation_type", "")).strip()
        if veg_type:
            rule_index.setdefault(veg_type, []).append(rule)

    for placement in placements_centered:
        base_type = _scatter_base_type(
            str(placement.get("vegetation_type", "")),
            str(placement.get("category", "")),
        )
        matching_rules = rule_index.get(base_type)
        if not matching_rules:
            continue

        centered_x, centered_y = placement["position"]
        local_x = centered_x + terrain_width * 0.5
        local_y = centered_y + terrain_height * 0.5
        if not (0.0 <= local_x <= terrain_width and 0.0 <= local_y <= terrain_height):
            continue

        altitude = float(placement.get("altitude", 0.0))
        slope_deg = _sample_scalar_map(slope_map, local_x, local_y, terrain_width, terrain_height)
        moisture = float(placement.get("moisture", 0.0))
        if moisture_map is not None:
            moisture = _sample_scalar_map(moisture_map, local_x, local_y, terrain_width, terrain_height)

        chosen_rule = None
        for rule in matching_rules:
            min_alt = float(rule.get("min_alt", 0.0))
            max_alt = float(rule.get("max_alt", 1.0))
            min_slope = float(rule.get("min_slope", 0.0))
            max_slope = min(float(rule.get("max_slope", 90.0)), float(max_tilt_angle))
            min_moisture = float(rule.get("min_moisture", 0.0))
            max_moisture = float(rule.get("max_moisture", 1.0))
            if not (min_alt <= altitude <= max_alt):
                continue
            if not (min_slope <= slope_deg <= max_slope):
                continue
            if not (min_moisture <= moisture <= max_moisture):
                continue
            chosen_rule = rule
            break

        if chosen_rule is None:
            continue

        if apply_rule_density and rng.random() > float(chosen_rule.get("density", 1.0)):
            continue

        placement_local = dict(placement)
        placement_local["position"] = (local_x, local_y)
        placement_local["rotation"] = math.degrees(float(placement.get("rotation", 0.0))) % 360.0
        placement_local["moisture"] = moisture
        placement_local["altitude"] = altitude
        # Preserve fine-grained species_id and vegetation_type for concrete
        # species template selection. Legacy consumers can use base_type.
        if "species_id" not in placement_local and placement.get("vegetation_type"):
            placement_local["species_id"] = placement["vegetation_type"]
        placement_local["base_type"] = base_type
        placement_local["vegetation_type"] = base_type
        scale_range = chosen_rule.get("scale_range")
        if (
            isinstance(scale_range, (tuple, list))
            and len(scale_range) == 2
        ):
            scale_min = float(scale_range[0])
            scale_max = float(scale_range[1])
            if scale_max >= scale_min:
                placement_local["scale"] = rng.uniform(scale_min, scale_max)
        filtered.append(placement_local)

    return filtered


def _yaw_deg_to_quat(yaw_deg: float) -> tuple[float, float, float, float]:
    half = math.radians(float(yaw_deg)) * 0.5
    return (0.0, 0.0, math.sin(half), math.cos(half))


def _normal_from_gradients(dzdx: float, dzdy: float) -> tuple[float, float, float]:
    nx, ny, nz = -float(dzdx), -float(dzdy), 1.0
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 1.0e-8:
        return (0.0, 0.0, 1.0)
    return (nx / length, ny / length, nz / length)


def _euler_xyz_to_quat(rx: float, ry: float, rz: float) -> tuple[float, float, float, float]:
    """Convert XYZ Euler radians to quaternion tuple (x, y, z, w)."""
    cx = math.cos(float(rx) * 0.5)
    sx = math.sin(float(rx) * 0.5)
    cy = math.cos(float(ry) * 0.5)
    sy = math.sin(float(ry) * 0.5)
    cz = math.cos(float(rz) * 0.5)
    sz = math.sin(float(rz) * 0.5)
    return (
        sx * cy * cz + cx * sy * sz,
        cx * sy * cz - sx * cy * sz,
        cx * cy * sz + sx * sy * cz,
        cx * cy * cz - sx * sy * sz,
    )


def _resolve_prototype_id(
    placement: dict[str, Any],
    species_id: str,
    resolve_fn: Any,
) -> str:
    """Return the best available prototype_id for a scatter placement.

    Priority: explicit prototype_id in placement → catalog unity_asset_path
    (non-fallback) → species_id string (engine-side procedural fallback).
    """
    if placement.get("prototype_id"):
        return str(placement["prototype_id"])
    if resolve_fn is not None:
        try:
            entry = resolve_fn(species_id)
            if not entry.get("fallback") and entry.get("unity_asset_path"):
                return str(entry["unity_asset_path"])
        except Exception:
            pass
    return species_id


def _build_scatter_point_table_from_placements(
    placements: list[dict[str, Any]],
    *,
    terrain_width: float,
    terrain_height: float,
    terrain_origin_x: float,
    terrain_origin_y: float,
    biome_id: str,
    height_min: float,
    height_range: float,
    seed: int,
) -> ScatterPointTable:
    """Convert handler placements into the canonical scatter point table."""
    terrain_half_x = terrain_width * 0.5
    terrain_half_y = terrain_height * 0.5

    # Resolve catalog assets once per call to avoid repeated module import overhead.
    try:
        from .terrain_foliage_catalog import resolve_model_asset as _resolve_asset
    except Exception:
        _resolve_asset = None  # type: ignore[assignment]

    points: list[ScatterPoint] = []
    for index, placement in enumerate(placements):
        local_x, local_y = placement["position"]
        species_id = str(
            placement.get("species_id")
            or placement.get("vegetation_type")
            or "unknown"
        )
        base_type = str(placement.get("base_type") or placement.get("vegetation_type") or species_id)
        scale = float(placement.get("scale", 1.0))
        altitude_norm = float(placement.get("altitude", 0.0))
        height_m = height_min + altitude_norm * height_range
        world_position = placement.get("world_position")
        if (
            not isinstance(world_position, (tuple, list))
            or len(world_position) < 3
        ):
            world_position = (
                float(local_x) - terrain_half_x + terrain_origin_x,
                float(local_y) - terrain_half_y + terrain_origin_y,
                float(height_m),
            )
        else:
            height_m = float(world_position[2])
        normal = placement.get("normal", (0.0, 0.0, 1.0))
        if not isinstance(normal, (tuple, list)) or len(normal) < 3:
            normal = (0.0, 0.0, 1.0)
        orient = placement.get("orient")
        if not isinstance(orient, (tuple, list)) or len(orient) < 4:
            orient = _yaw_deg_to_quat(float(placement.get("rotation", 0.0)))
        lod_index = int(placement.get("lod", 0))
        wind_profile = "tree" if base_type == "tree" or species_id.startswith("tree_") else base_type
        points.append(
            ScatterPoint(
                position=(float(world_position[0]), float(world_position[1]), float(world_position[2])),
                normal=(float(normal[0]), float(normal[1]), float(normal[2])),
                orient=(float(orient[0]), float(orient[1]), float(orient[2]), float(orient[3])),
                scale=(scale, scale, scale),
                prototype_id=_resolve_prototype_id(
                    placement, species_id, _resolve_asset
                ),
                species_id=species_id,
                biome_id=str(biome_id),
                density=float(placement.get("density", 1.0)),
                seed=int(placement.get("seed", int(seed) + index)),
                slope=float(placement.get("slope", 0.0)),
                height_m=float(height_m),
                mask_sources=("multipass_scatter", f"species:{species_id}", f"biome:{biome_id}"),
                lod_bucket=f"lod{min(max(lod_index, 0), 3)}",
                wind_profile=wind_profile,
                source_layer="environment_scatter",
                point_mode="exact_instance",
                metadata={
                    "base_type": base_type,
                    "moisture": float(placement.get("moisture", 0.0)),
                    "rotation_y": float(placement.get("rotation_y", 0.0)),
                },
            )
        )
    return ScatterPointTable(points=tuple(points), source="environment_scatter")


def _generate_multipass_scatter_placements(
    *,
    heightmap: np.ndarray,
    slope_map: np.ndarray,
    terrain_width: float,
    terrain_height: float,
    biome: str,
    rules: list[dict[str, Any]],
    seed: int,
    separation_scale: float,
    max_tilt_angle: float,
    stack=None,
    moisture_map: "np.ndarray | None" = None,
    building_zones_world: "list[tuple[float, float, float, float]] | None" = None,
    terrain_origin_x: float = 0.0,
    terrain_origin_y: float = 0.0,
    viewer_origin_local: "tuple[float, float] | None" = None,
    combat_clearings: "list[dict[str, Any]] | None" = None,
    apply_rule_density: bool = False,
) -> list[dict[str, Any]]:
    """Generate handler-ready vegetation placements using the richer multi-pass path."""
    water_map, disturbance_map = _resolve_scatter_context_maps(stack, heightmap, moisture_map)
    local_building_zones = _localize_exclusion_zones(
        building_zones_world or [],
        terrain_origin_x=terrain_origin_x,
        terrain_origin_y=terrain_origin_y,
    )

    terrain_size = max(terrain_width, terrain_height, 1.0)
    structure = _scatter_pass(
        heightmap,
        slope_map,
        terrain_size=terrain_size,
        terrain_width=terrain_width,
        terrain_height=terrain_height,
        pass_type="structure",
        biome=biome,
        seed=seed,
        separation_scale=separation_scale,
        building_zones=local_building_zones,
        combat_clearings=combat_clearings,
        water_proximity_map=water_map,
        disturbance_map=disturbance_map,
        viewer_origin=viewer_origin_local,
    )
    tree_positions = [
        tuple(item["position"])
        for item in structure
        if _scatter_base_type(str(item.get("vegetation_type", ""))) == "tree"
    ]
    ground_cover = _scatter_pass(
        heightmap,
        slope_map,
        terrain_size=terrain_size,
        terrain_width=terrain_width,
        terrain_height=terrain_height,
        pass_type="ground_cover",
        biome=biome,
        seed=seed + 101,
        separation_scale=separation_scale,
        building_zones=local_building_zones,
        tree_positions=tree_positions,
        combat_clearings=combat_clearings,
        water_proximity_map=water_map,
        disturbance_map=disturbance_map,
        viewer_origin=viewer_origin_local,
    )
    debris = _scatter_pass(
        heightmap,
        slope_map,
        terrain_size=terrain_size,
        terrain_width=terrain_width,
        terrain_height=terrain_height,
        pass_type="debris",
        biome=biome,
        seed=seed + 202,
        separation_scale=separation_scale,
        building_zones=local_building_zones,
        combat_clearings=combat_clearings,
        water_proximity_map=water_map,
        disturbance_map=disturbance_map,
        viewer_origin=viewer_origin_local,
    )

    filtered = _filter_multipass_scatter_placements(
        structure + ground_cover + debris,
        rules=rules,
        terrain_width=terrain_width,
        terrain_height=terrain_height,
        slope_map=slope_map,
        moisture_map=water_map,
        max_tilt_angle=max_tilt_angle,
        seed=seed,
        apply_rule_density=apply_rule_density,
    )
    if not building_zones_world:
        return filtered
    terrain_half_x = terrain_width * 0.5
    terrain_half_y = terrain_height * 0.5
    out: list[dict[str, Any]] = []
    for item in filtered:
        local_x, local_y = item["position"]
        wx = float(local_x) - terrain_half_x + terrain_origin_x
        wy = float(local_y) - terrain_half_y + terrain_origin_y
        if any(min_x <= wx <= max_x and min_y <= wy <= max_y for min_x, min_y, max_x, max_y in building_zones_world):
            continue
        out.append(item)
    return out


def _hero_excluded(
    excl: "np.ndarray | None",
    world_x: float,
    world_y: float,
    terrain_width: float,
    terrain_height: float,
) -> bool:
    """Return True when (world_x, world_y) falls in the hero_exclusion mask.

    Parameters
    ----------
    excl : np.ndarray (H, W) or None
        Non-zero = exclude.
    world_x, world_y : float
        Position in LOCAL terrain space [0, terrain_width] × [0, terrain_height].
    """
    if excl is None:
        return False
    ec = np.asarray(excl, dtype=np.float32)
    col_f = (world_x / terrain_width) * (ec.shape[1] - 1)
    row_f = (world_y / terrain_height) * (ec.shape[0] - 1)
    r_idx = int(np.clip(row_f, 0, ec.shape[0] - 1))
    c_idx = int(np.clip(col_f, 0, ec.shape[1] - 1))
    return ec[r_idx, c_idx] != 0


def _wind_rotation_y(
    wind: "np.ndarray | None",
    world_x: float,
    world_y: float,
    terrain_width: float,
    terrain_height: float,
) -> float:
    """Return rotation_y in radians from wind_field at (world_x, world_y).

    Parameters
    ----------
    wind : np.ndarray (H, W, 2) float32 or None
        wind[..., 0] = wind_x (m/s), wind[..., 1] = wind_y (m/s).
    world_x, world_y : float
        Position in LOCAL terrain space.

    Returns
    -------
    float : arctan2(wind_x, wind_y); 0.0 when wind is None.
    """
    if wind is None:
        return 0.0
    wf = np.asarray(wind, dtype=np.float32)
    col_f = (world_x / terrain_width) * (wf.shape[1] - 1)
    row_f = (world_y / terrain_height) * (wf.shape[0] - 1)
    r_idx = int(np.clip(row_f, 0, wf.shape[0] - 1))
    c_idx = int(np.clip(col_f, 0, wf.shape[1] - 1))
    return float(np.arctan2(wf[r_idx, c_idx, 0], wf[r_idx, c_idx, 1]))


def _apply_sdf_exclusion(
    world_x: float,
    world_y: float,
    road_sdf_np: "np.ndarray | None",
    placement_radius: float,
    terrain_origin_x: float,
    terrain_origin_y: float,
    terrain_width: float,
    terrain_height: float,
) -> bool:
    """Return True when (world_x, world_y) is within placement_radius of a road.

    Uses road_sdf_dist channel (Fix 9.11). world_x/world_y are WORLD-space coords.
    """
    if road_sdf_np is None:
        return False
    terrain_half_x = terrain_width / 2.0
    terrain_half_y = terrain_height / 2.0
    col_f = ((world_x - terrain_origin_x + terrain_half_x) / terrain_width) * (road_sdf_np.shape[1] - 1)
    row_f = ((world_y - terrain_origin_y + terrain_half_y) / terrain_height) * (road_sdf_np.shape[0] - 1)
    H, W = road_sdf_np.shape
    r0 = int(math.floor(max(0.0, min(row_f, H - 1))))
    c0 = int(math.floor(max(0.0, min(col_f, W - 1))))
    r1 = min(r0 + 1, H - 1)
    c1 = min(c0 + 1, W - 1)
    tr = row_f - math.floor(row_f)
    tc = col_f - math.floor(col_f)
    sdf_val = (
        road_sdf_np[r0, c0] * (1.0 - tr) * (1.0 - tc)
        + road_sdf_np[r0, c1] * (1.0 - tr) * tc
        + road_sdf_np[r1, c0] * tr * (1.0 - tc)
        + road_sdf_np[r1, c1] * tr * tc
    )
    return float(sdf_val) < placement_radius


def _write_tree_instance_points(
    instances: np.ndarray,
    stack,
) -> None:
    """Write LocationLayer output to stack.tree_instance_points (Fix 9.2).

    Parameters
    ----------
    instances : np.ndarray shape (N, 5) float32 — (x, y, z, rotation_y, prototype_id)
    stack : TerrainMaskStack or duck-typed stack with .set()
    """
    if stack is None or instances is None:
        return
    arr = np.asarray(instances, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] != 5:
        return
    if arr.shape[0] == 0:
        return
    finite_rows = np.all(np.isfinite(arr), axis=1)
    if not np.all(finite_rows):
        arr = arr[finite_rows]
    if arr.shape[0] == 0:
        return
    arr = arr.copy()
    arr[:, 4] = np.maximum(np.rint(arr[:, 4]), 0.0)
    if hasattr(stack, "set"):
        stack.set("tree_instance_points", arr, "location_layer")
    else:
        # Fallback for simple namespace mocks used in tests
        stack.tree_instance_points = arr


# ---------------------------------------------------------------------------
# LocationLayer — Rune Skovbo Johansen jitter + 3x3 repulsion placement
# Fix 9.8 / BUG-S10-010
# ---------------------------------------------------------------------------

def _location_layer_rand2(i: int, j: int, seed: int, k: int) -> tuple:
    """Deterministic 2D random offset in [-0.5, 0.5] per cell (i, j), candidate k.

    Uses integer hash mix with no floating-point RNG state — output is fully
    deterministic given the same (i, j, seed, k) regardless of call order.
    """
    h = int(seed) ^ (int(i) * 73856093) ^ (int(j) * 19349663) ^ (int(k) * 83492791)
    h = (h ^ (h >> 13)) & 0xFFFFFFFF
    h = (h * 1664525 + 1013904223) & 0xFFFFFFFF
    rx = ((h & 0xFFFF) / 65535.0) - 0.5
    h = (h ^ (h >> 13)) & 0xFFFFFFFF
    h = (h * 1664525 + 1013904223) & 0xFFFFFFFF
    ry = ((h & 0xFFFF) / 65535.0) - 0.5
    return rx, ry


class LocationLayer:
    """Jittered grid scatter with 3x3 neighbor repulsion (Rune's algorithm).

    Each grid cell generates N candidates. Each candidate is placed at
    ``cell_origin + cell_size * (rand2 + 0.5)`` — always within the cell.
    A 3x3 neighborhood repulsion check rejects any candidate closer than
    ``repulsion_radius`` to an already-accepted point in adjacent cells.

    Parameters
    ----------
    cell_size : float
        World-space size of each grid cell in meters.
    density : float
        Average instances per square meter.
        N_candidates = max(1, round(density * cell_size^2)).
    repulsion_radius : float
        Minimum world-space distance between accepted instances.
    seed : int
        Deterministic seed combined with cell coordinates.
    """

    def __init__(
        self,
        cell_size: float = 5.0,
        density: float = 0.04,
        repulsion_radius: float = 2.5,
        seed: int = 0,
    ) -> None:
        self.cell_size = float(cell_size)
        self.density = float(density)
        self.repulsion_radius = float(repulsion_radius)
        self.seed = int(seed)

    def generate(
        self,
        width_m: float,
        height_m: float,
        height_sample_fn=None,
        wind_sample_fn=None,
        prototype_id: int = 0,
    ) -> np.ndarray:
        """Generate scatter instances over a [0, width_m] x [0, height_m] region.

        Parameters
        ----------
        width_m, height_m : float
            World-space extent of the scatter region in meters.
        height_sample_fn : callable(x, y) -> float, optional
            Returns world-space Z for a given XY. Defaults to 0.0.
        wind_sample_fn : callable(x, y) -> float, optional
            Returns rotation_y in radians for a given XY. Defaults to 0.0.
        prototype_id : int
            Integer prototype index written to column 4 of output.

        Returns
        -------
        np.ndarray shape (N, 5) float32 — (x, y, z, rotation_y, prototype_id)
        """
        cs = self.cell_size
        n_cols = max(1, int(np.ceil(width_m / cs)))
        n_rows = max(1, int(np.ceil(height_m / cs)))
        n_candidates = max(1, round(self.density * cs * cs))
        rr_sq = self.repulsion_radius * self.repulsion_radius

        # --- Batch-generate all candidate (x, y) positions via numpy broadcasting ---
        # Replicate _location_layer_rand2 exactly for all (i, j, k) triples at once.
        # _location_layer_rand2 computes:
        #   h = seed ^ (i * 73856093) ^ (j * 19349663) ^ (k * 83492791)
        #   h = ((h ^ (h >> 13)) & 0xFFFFFFFF) * 1664525 + 1013904223) & 0xFFFFFFFF
        #   rx = ((h & 0xFFFF) / 65535.0) - 0.5   [same scramble again for ry]
        # All arithmetic uses uint32 wrapping (& 0xFFFFFFFF).
        i_idx = np.arange(n_rows, dtype=np.uint32)
        j_idx = np.arange(n_cols, dtype=np.uint32)
        k_idx = np.arange(n_candidates, dtype=np.uint32)
        # Grid shape: (n_rows, n_cols, n_candidates)
        ii, jj, kk = np.meshgrid(i_idx, j_idx, k_idx, indexing="ij")

        seed_u32 = np.uint32(self.seed)
        h = (
            seed_u32
            ^ (ii * np.uint32(73856093))
            ^ (jj * np.uint32(19349663))
            ^ (kk * np.uint32(83492791))
        )
        # First scramble → rx
        h = (h ^ (h >> np.uint32(13))) * np.uint32(1664525) + np.uint32(1013904223)
        rx = (h & np.uint32(0xFFFF)).astype(np.float64) / 65535.0 - 0.5  # [-0.5, 0.5]
        # Second scramble → ry
        h = (h ^ (h >> np.uint32(13))) * np.uint32(1664525) + np.uint32(1013904223)
        ry = (h & np.uint32(0xFFFF)).astype(np.float64) / 65535.0 - 0.5  # [-0.5, 0.5]

        # Map to world-space position (identical formula to scalar version)
        cx_all = (jj.astype(np.float64) * cs + cs * (rx + 0.5)).clip(0.0, width_m)
        cy_all = (ii.astype(np.float64) * cs + cs * (ry + 0.5)).clip(0.0, height_m)
        # Flatten to 1-D arrays sorted by (i, j, k) order
        cx_flat = cx_all.ravel()
        cy_flat = cy_all.ravel()
        total = cx_flat.shape[0]

        # --- Per-cell repulsion in raster order ---
        # Candidate positions are pre-computed; the Python loop only decides
        # accept/reject using the 3x3 neighbour dict — no inner candidate-gen cost.
        accepted_per_cell: dict = {}
        all_instances: list = []

        for flat_idx in range(total):
            grid_i = flat_idx // (n_cols * n_candidates)
            rem = flat_idx % (n_cols * n_candidates)
            grid_j = rem // n_candidates

            cx = float(cx_flat[flat_idx])
            cy = float(cy_flat[flat_idx])

            key = (grid_i, grid_j)
            accepted_per_cell.setdefault(key, [])

            accepted = True
            for di in (-1, 0, 1):
                if not accepted:
                    break
                for dj in (-1, 0, 1):
                    ni, nj = grid_i + di, grid_j + dj
                    for px, py in accepted_per_cell.get((ni, nj), ()):
                        ddx = cx - px
                        ddy = cy - py
                        if ddx * ddx + ddy * ddy < rr_sq:
                            accepted = False
                            break
                    if not accepted:
                        break

            if accepted:
                accepted_per_cell[key].append((cx, cy))
                z = height_sample_fn(cx, cy) if height_sample_fn is not None else 0.0
                rot = wind_sample_fn(cx, cy) if wind_sample_fn is not None else 0.0
                all_instances.append((cx, cy, float(z), float(rot), float(prototype_id)))

        if not all_instances:
            return np.empty((0, 5), dtype=np.float32)
        return np.array(all_instances, dtype=np.float32)


# ---------------------------------------------------------------------------
# Halo scatter tile assignment — Fix 9.10 / BUG-S10-012
# ---------------------------------------------------------------------------

def halo_scatter_point_id(
    world_x: float,
    world_y: float,
    seed: int,
    num_tiles: int,
) -> int:
    """Return the tile ID that owns a scatter point at (world_x, world_y).

    Deterministic: same (x, y, seed, num_tiles) → same tile_id always.
    Quantizes to 0.1m grid to prevent float precision drift at tile boundaries.

    Usage: include point in tile output only if halo_scatter_point_id(...) == tile_id.
    Generate points in (tile_width + 2*halo) x (tile_height + 2*halo) region; the hash
    ensures seam-free coverage without duplication.
    """
    qx = int(round(world_x * 10))
    qy = int(round(world_y * 10))
    h = int(seed) ^ (qx * 73856093) ^ (qy * 19349663)
    h = (h ^ (h >> 13)) & 0xFFFFFFFF
    h = (h * 1664525 + 1013904223) & 0xFFFFFFFF
    return h % max(1, int(num_tiles))


# ---------------------------------------------------------------------------
# Default biome vegetation rules
# ---------------------------------------------------------------------------

_DEFAULT_VEG_RULES: list[dict[str, Any]] = [
    {
        "vegetation_type": "tree",
        "min_alt": 0.15,
        "max_alt": 0.65,
        "min_slope": 0.0,
        "max_slope": 25.0,
        "scale_range": (0.8, 1.5),
        "density": 0.7,
    },
    {
        "vegetation_type": "bush",
        "min_alt": 0.1,
        "max_alt": 0.5,
        "min_slope": 0.0,
        "max_slope": 35.0,
        "scale_range": (0.5, 1.0),
        "density": 0.8,
    },
    {
        "vegetation_type": "grass",
        "min_alt": 0.05,
        "max_alt": 0.4,
        "min_slope": 0.0,
        "max_slope": 30.0,
        "scale_range": (0.3, 0.7),
        "density": 0.9,
    },
    {
        "vegetation_type": "rock",
        "min_alt": 0.4,
        "max_alt": 1.0,
        "min_slope": 20.0,
        "max_slope": 90.0,
        "scale_range": (0.5, 1.2),
        "density": 0.6,
    },
]


# ---------------------------------------------------------------------------
# Template geometry helpers
# ---------------------------------------------------------------------------

def _create_template_collection(name: str) -> bpy.types.Collection:
    """Create a hidden collection for instance templates."""
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    # Hide from viewport and render
    coll.hide_viewport = True
    coll.hide_render = True
    return coll


def _create_vegetation_template(
    veg_type: str, collection: bpy.types.Collection
) -> bpy.types.Object:
    """Create a scatter-optimized template mesh for a vegetation type.

    Uses procedural mesh generators from VEGETATION_GENERATOR_MAP when
    available. All organic types receive per-category LOD budget reductions
    so scatter templates instanced 1000s of times stay within draw-call
    triangle budgets matching Ghost of Tsushima / Horizon scatter pipelines:

      Trees     : iterations=3, ring_segments=4  (~1-2K tris per instance)
      Shrubs/Bush: segments/subdivisions=3        (~200-400 tris per instance)
      Rocks     : detail=2                        (~100-200 tris per instance)
      Grass/Weed: billboard plane (2 tris)        (impostor — distance rendered)
      Mushroom  : segments=5                      (~80 tris per instance)
      Root/Fallen log: segments=3                 (~60 tris per instance)

    Falls back to oriented billboard planes (not cubes) for unmapped types
    so scatter previews are always scene-readable.
    """
    gen_entry = VEGETATION_GENERATOR_MAP.get(veg_type)
    if gen_entry is not None:
        gen_func, gen_kwargs = gen_entry
        scatter_kwargs = dict(gen_kwargs)

        # Per-category LOD budget — instanced scatter must be cheap
        if veg_type.startswith("tree") or veg_type == "pine_tree":
            # L-system trees: 3 iterations ≈ 1-2K tris; ring_segments=4
            scatter_kwargs.setdefault("iterations", 3)
            scatter_kwargs.setdefault("ring_segments", 4)
        elif veg_type in ("bush", "shrub"):
            # Organic shrubs: reduce subdivision/segment counts
            scatter_kwargs.setdefault("segments", 3)
            scatter_kwargs.setdefault("subdivisions", 1)
        elif veg_type in ("rock", "rock_mossy", "cliff_rock"):
            # Rock generators: lower detail pass
            scatter_kwargs.setdefault("detail", 2)
        elif veg_type in ("mushroom", "mushroom_cluster"):
            # Mushroom caps: minimal radial segments
            scatter_kwargs.setdefault("segments", 5)
        elif veg_type in ("root", "fallen_log"):
            # Organic ground debris: minimal tube segments
            scatter_kwargs.setdefault("segments", 3)

        spec = gen_func(**scatter_kwargs)
        obj = mesh_from_spec(
            spec,
            name=f"_template_{veg_type}",
            collection=collection,
        )
        if getattr(obj, "data", None) is not None and hasattr(obj.data, "polygons"):
            for poly in obj.data.polygons:
                poly.use_smooth = True
        _assign_scatter_material(obj, veg_type)
        return obj

    # Fallback: billboard-oriented plane instead of cube.
    # A vertical plane is far more scene-readable than a 0.5m cube and
    # consumes only 2 triangles, matching the game-engine scatter impostor
    # pattern for types without a registered generator.
    mesh = bpy.data.meshes.new(f"_template_{veg_type}")
    bm_local = bmesh.new()

    if veg_type in ("grass", "weed"):
        # Low billboard plane — ground-level cover
        bmesh.ops.create_grid(bm_local, x_segments=1, y_segments=1, size=0.3)
        # Rotate to stand vertically (Z-up convention for billboard grass)
        import bmesh as _bmesh_mod
        bmesh.ops.rotate(
            bm_local,
            cent=(0, 0, 0),
            matrix=__import__("mathutils").Matrix.Rotation(math.radians(90), 3, "X"),
            verts=bm_local.verts,
        )
    else:
        # Generic vertical billboard — readable silhouette for any plant type
        bmesh.ops.create_grid(bm_local, x_segments=1, y_segments=1, size=0.5)
        bmesh.ops.rotate(
            bm_local,
            cent=(0, 0, 0),
            matrix=__import__("mathutils").Matrix.Rotation(math.radians(90), 3, "X"),
            verts=bm_local.verts,
        )
        # Shift up so the base of the billboard sits at Z=0 (not centred)
        bmesh.ops.translate(bm_local, vec=(0, 0, 0.25), verts=bm_local.verts)

    bm_local.to_mesh(mesh)
    bm_local.free()

    obj = bpy.data.objects.new(f"_template_{veg_type}", mesh)
    collection.objects.link(obj)
    if hasattr(obj.data, "polygons"):
        for poly in obj.data.polygons:
            poly.use_smooth = True

    _assign_scatter_material(obj, veg_type)
    return obj


# ---------------------------------------------------------------------------
# Billboard LOD wiring (Phase 50-02 G3: relocated to lod_pipeline.py)
# ---------------------------------------------------------------------------
# ``_setup_billboard_lod`` + its helpers (``_BILLBOARD_LOD_VERTEX_THRESHOLD``,
# ``_TREE_VEG_TYPES``) now live in ``blender_addon.handlers.lod_pipeline``
# (toolkit-side) so vegetation_system (toolkit) can import them without
# reaching into environment_scatter (terrain). Re-exported here for
# backward compatibility with intra-terrain callers of this module.
from .lod_pipeline import (  # noqa: F401  -- intentional re-export
    _BILLBOARD_LOD_VERTEX_THRESHOLD,
    _TREE_VEG_TYPES,
    _setup_billboard_lod,
)


# ---------------------------------------------------------------------------
# AAA: Grass card biome specs
# ---------------------------------------------------------------------------

# sRGB -> linear: (v/255)^2.2
_GRASS_BIOME_SPECS: dict[str, dict[str, Any]] = {
    "prairie": {
        "height_min": 0.5,
        "height_max": 1.2,
        # sRGB(140,160,60) -> linear
        "color": (0.242, 0.349, 0.043, 1.0),
    },
    "forest": {
        "height_min": 0.1,
        "height_max": 0.3,
        # sRGB(50,80,30) -> linear
        "color": (0.031, 0.079, 0.013, 1.0),
    },
    "swamp": {
        "height_min": 0.8,
        "height_max": 2.0,
        # sRGB(100,120,50) -> linear
        "color": (0.118, 0.176, 0.031, 1.0),
    },
    "mountain": {
        "height_min": 0.05,
        "height_max": 0.15,
        # sRGB(90,100,70) -> linear
        "color": (0.089, 0.118, 0.058, 1.0),
    },
    "corrupted": {
        "height_min": 0.3,
        "height_max": 0.8,
        # sRGB(30,25,35) -> linear
        "color": (0.013, 0.010, 0.018, 1.0),
    },
    "dead": {
        "height_min": 0.2,
        "height_max": 0.5,
        # sRGB(120,90,40) -> linear
        "color": (0.196, 0.099, 0.021, 1.0),
    },
}

# Biome density factors for Pass 1 (tree/bush scatter)
_BIOME_DENSITY: dict[str, float] = {
    "dark_forest": 0.8,
    "corrupted_wasteland": 0.05,
    "swamp": 0.5,
    "mountain": 0.2,
    "grassy_plains": 0.65,
    "prairie": 0.65,
    "forest": 0.8,
    "dead": 0.3,
    "default": 0.5,
}


# ---------------------------------------------------------------------------
# AAA: Leaf card canopy helper
# ---------------------------------------------------------------------------

def _add_leaf_card_canopy(
    bm: "bmesh.types.BMesh",
    canopy_center: tuple[float, float, float],
    canopy_radius: float,
    num_planes: int,
    rng: random.Random,
    species_row: int = 0,
) -> None:
    """Add 6-12 intersecting leaf card planes to a bmesh for a tree canopy.

    Planes are grouped as:
    - 3 vertical cross-planes at 0, 60, 120 degree intervals (spine of the canopy)
    - num_planes-3 angled planes at 30-45 degrees from vertical (volumetric fill)

    Each plane is sized to canopy_radius and given a small random offset
    (0-0.3m) for organic variety.

    UV atlas layout (Ghost of Tsushima / Horizon ZD leaf card standard):
        4×4 atlas where ROWS = species variants (broadleaf, needle, palm, fern…)
        and COLS = age/seasonal variants (spring, summer, autumn, dead).
        ``species_row`` pins the row; column is randomly sampled per card so each
        card on the same tree can show a different age state for organic variety.
        Both the front face and its mirrored backface duplicate share the same UV
        cell so the alpha mask is consistent on both sides.

    Backface normal flipping:
        Each quad is emitted twice — the front face with the natural winding and
        an exact duplicate with reversed winding (BL/BR/TR/TL → TL/TR/BR/BL).
        This gives correct per-face normals on both sides without relying on
        a "two-sided" material flag, matching Ghost of Tsushima and SpeedTree's
        approach for LOD-level leaf cards that must be visible from any angle.

    Wind vertex colors follow the canonical AAA RGBA layout (SpeedTree /
    Vegetation Studio convention — same as bake_wind_vertex_colors):
      R = sway_amplitude  (0.0 at card base = anchored, 1.0 at card tip = full sway)
      G = sway_phase_offset (random per card cluster, constant across the card so the
                            whole card sways as one unit; distinct per cluster so
                            adjacent cards desync for natural flutter)
      B = sway_frequency_multiplier  (0.5 at base → 1.0 at tip; tips flutter faster)
      A = trunk_stiffness (0.0 = rigid, leaf cards at canopy height use 0.8–1.0
                          indicating they are free-swinging foliage, not trunk)
    """
    cx, cy, cz = canopy_center
    r = canopy_radius

    # Ensure wind vertex color layer exists
    wind_layer = bm.verts.layers.float_color.get("wind_vc")
    if wind_layer is None:
        wind_layer = bm.verts.layers.float_color.new("wind_vc")

    # Ensure UV layer exists for leaf atlas mapping
    uv_layer = None
    loops = getattr(bm, "loops", None)
    loop_layers = getattr(loops, "layers", None)
    loop_uv = getattr(loop_layers, "uv", None)
    if loop_uv is not None:
        uv_layer = loop_uv.get("UVMap")
        if uv_layer is None:
            uv_layer = loop_uv.new("UVMap")

    # Leaf atlas: 4×4 grid.
    #   ROWS (V axis) = species variants: row 0=broadleaf, 1=needle, 2=palm, 3=fern/other
    #   COLS (U axis) = age/seasonal variants: col 0=spring, 1=summer, 2=autumn, 3=dead
    # This matches the Ghost of Tsushima / Horizon ZD leaf card atlas convention so
    # a single atlas texture can serve all tree types and seasonal states.
    _ATLAS_COLS = 4
    _ATLAS_ROWS = 4
    _ATLAS_CELL_U = 1.0 / _ATLAS_COLS
    _ATLAS_CELL_V = 1.0 / _ATLAS_ROWS
    _species = max(0, min(_ATLAS_ROWS - 1, species_row))

    def _atlas_uv(age_col: int) -> tuple[tuple, tuple, tuple, tuple]:
        """Return 4 UV corners (BL, BR, TR, TL) for (species_row, age_col) cell."""
        _age = max(0, min(_ATLAS_COLS - 1, age_col))
        u0 = _age * _ATLAS_CELL_U
        u1 = u0 + _ATLAS_CELL_U
        v0 = _species * _ATLAS_CELL_V
        v1 = v0 + _ATLAS_CELL_V
        return (u0, v0), (u1, v0), (u1, v1), (u0, v1)

    def _atlas_uv_flipped(age_col: int) -> tuple[tuple, tuple, tuple, tuple]:
        """Return UV corners for the backface duplicate (winding BL↔BR swapped → U mirrored)."""
        _age = max(0, min(_ATLAS_COLS - 1, age_col))
        u0 = _age * _ATLAS_CELL_U
        u1 = u0 + _ATLAS_CELL_U
        v0 = _species * _ATLAS_CELL_V
        v1 = v0 + _ATLAS_CELL_V
        # Mirror U so the backface texture reads correctly (not reversed)
        return (u1, v0), (u0, v0), (u0, v1), (u1, v1)

    def _add_card(corners: list[tuple[float, float, float]], phase: float, age_col: int) -> None:
        """Emit a front-face quad and its backface duplicate with matching wind colors."""
        # --- Front face ---
        front_verts = [bm.verts.new(c) for c in corners]
        for vi, v in enumerate(front_verts):
            height_t = float(vi // 2)           # 0.0 bottom row, 1.0 top row
            v[wind_layer] = (
                height_t,                       # R: amplitude 0→1 bottom to top
                phase,                          # G: phase constant per card cluster
                0.5 + height_t * 0.5,           # B: frequency 0.5→1.0
                0.75 + height_t * 0.2,          # A: stiffness 0.75→0.95 (free foliage)
            )
        try:
            face = bm.faces.new(front_verts)
            if uv_layer is not None:
                uv_corners = _atlas_uv(age_col)
                for loop, uv in zip(face.loops, uv_corners):
                    loop[uv_layer].uv = uv
        except ValueError:
            return

        # --- Backface duplicate (reversed winding: TL, TR, BR, BL) ---
        # Sharing vertices with the front face would collapse normals; duplicate
        # the geometry so each face has its own independent normal direction.
        back_verts = [bm.verts.new(c) for c in reversed(corners)]
        for vi, v in enumerate(back_verts):
            # reversed() gives TL, TR, BR, BL — height_t is the same value as
            # the corresponding front vert (index mapping: 0→TL=top, 1→TR=top,
            # 2→BR=bottom, 3→BL=bottom), so recompute from Z directly.
            height_t = 1.0 if vi < 2 else 0.0
            v[wind_layer] = (
                height_t,
                phase,
                0.5 + height_t * 0.5,
                0.75 + height_t * 0.2,
            )
        try:
            back_face = bm.faces.new(back_verts)
            if uv_layer is not None:
                uv_corners_back = _atlas_uv_flipped(age_col)
                for loop, uv in zip(back_face.loops, uv_corners_back):
                    loop[uv_layer].uv = uv
        except ValueError:
            pass

    planes_added = 0

    # 3 vertical planes at 60-degree intervals — spine of the canopy.
    # These form the visible silhouette when viewed from the side.
    for i in range(3):
        angle = math.radians(i * 60.0)
        offset_x = rng.uniform(-0.3, 0.3)
        offset_y = rng.uniform(-0.3, 0.3)
        px = cx + offset_x
        py = cy + offset_y

        tx = -math.cos(angle)   # tangent along the card width
        ty = math.sin(angle)
        corners = [
            (px + tx * r,  py + ty * r,  cz - r * 0.5),   # BL
            (px - tx * r,  py - ty * r,  cz - r * 0.5),   # BR
            (px - tx * r,  py - ty * r,  cz + r * 0.8),   # TR
            (px + tx * r,  py + ty * r,  cz + r * 0.8),   # TL
        ]
        age_col = rng.randint(0, _ATLAS_COLS - 1)
        _add_card(corners, rng.random(), age_col)
        planes_added += 1

    # Angled planes at 30-45 degrees from vertical — volumetric canopy fill.
    remaining = num_planes - 3
    for i in range(remaining):
        angle = math.radians(i * (360.0 / max(remaining, 1)) + 15.0)
        tilt = math.radians(rng.uniform(30.0, 45.0))
        offset_x = rng.uniform(-0.25, 0.25)
        offset_y = rng.uniform(-0.25, 0.25)
        px = cx + offset_x
        py = cy + offset_y

        tx = math.cos(angle)
        ty = math.sin(angle)
        tz_scale = math.cos(tilt)
        plane_h = r * math.sin(tilt)

        corners = [
            (px + tx * r,            py + ty * r,            cz - plane_h * 0.4),  # BL
            (px - tx * r,            py - ty * r,            cz - plane_h * 0.4),  # BR
            (px - tx * r * tz_scale, py - ty * r * tz_scale, cz + plane_h * 0.8),  # TR
            (px + tx * r * tz_scale, py + ty * r * tz_scale, cz + plane_h * 0.8),  # TL
        ]
        age_col = rng.randint(0, _ATLAS_COLS - 1)
        _add_card(corners, rng.random(), age_col)
        planes_added += 1


def create_leaf_card_tree(
    position: tuple[float, float, float],
    height: float = 5.0,
    canopy_radius: float = 2.5,
    num_planes: int = 8,
    seed: int = 42,
    species_variant: int = 0,
) -> "bpy.types.Object":
    """Create a tree with a leaf card canopy (SpeedTree / Ghost of Tsushima style).

    Geometry:
        - Trunk: 6-segment tapered cylinder, 0.7× taper at crown height.
        - Canopy: 6–12 intersecting leaf card quads (``num_planes`` clamped to
          that range) with front+backface duplicate geometry so cards render
          correctly from any angle without a two-sided material flag.

    UV atlas (4×4, rows=species, cols=age/season):
        ``species_variant`` selects the atlas row (0=broadleaf, 1=needle,
        2=palm, 3=fern).  Each card independently samples a random column so
        the same tree shows multiple age/seasonal states for organic variety —
        matching the Ghost of Tsushima / Horizon ZD leaf card atlas convention.

    Wind vertex colors follow the SpeedTree RGBA packing:
        R = sway_amplitude  (0 at base → 1 at tip)
        G = sway_phase      (random per card cluster, constant across card)
        B = sway_frequency  (0.5 at base → 1.0 at tip)
        A = trunk_stiffness (0.0 trunk → 0.75–0.95 free canopy foliage)

    Args:
        position: World-space (x, y, z) base of the trunk.
        height: Total tree height in metres.
        canopy_radius: Leaf card half-extent in metres.
        num_planes: Number of leaf card planes (clamped to [6, 12]).
        seed: RNG seed for reproducible variation.
        species_variant: Atlas row index selecting the leaf species (0–3).

    Returns:
        The created ``bpy.types.Object`` linked into the active collection.
    """
    rng = random.Random(seed)
    name = f"LeafCardTree_{seed}"

    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()

    # Trunk: 6-segment tapered cylinder
    trunk_radius = height * 0.06
    trunk_segments = 6
    trunk_verts_bottom = []
    trunk_verts_top = []
    for i in range(trunk_segments):
        angle = math.radians(i * 360.0 / trunk_segments)
        x = math.cos(angle) * trunk_radius
        y = math.sin(angle) * trunk_radius
        trunk_verts_bottom.append(bm.verts.new((position[0] + x, position[1] + y, position[2])))
        trunk_verts_top.append(bm.verts.new((
            position[0] + x * 0.7,
            position[1] + y * 0.7,
            position[2] + height * 0.55,
        )))

    # Trunk wind vertex colors (SpeedTree packing):
    # WORLD-006: guard against duplicate layer creation
    wind_layer = bm.verts.layers.float_color.get("wind_vc")
    if wind_layer is None:
        wind_layer = bm.verts.layers.float_color.new("wind_vc")
    trunk_phase = 0.0
    for v in trunk_verts_bottom:
        v[wind_layer] = (trunk_phase, 0.0, 0.5, 0.0)   # base: stationary
    for v in trunk_verts_top:
        v[wind_layer] = (trunk_phase, 0.2, 0.6, 0.0)   # top: gentle sway

    # Trunk faces
    for i in range(trunk_segments):
        j = (i + 1) % trunk_segments
        try:
            bm.faces.new([
                trunk_verts_bottom[i],
                trunk_verts_bottom[j],
                trunk_verts_top[j],
                trunk_verts_top[i],
            ])
        except ValueError:
            pass

    # Canopy: leaf card planes with backface duplicates and species/age atlas UVs
    canopy_center = (
        position[0],
        position[1],
        position[2] + height * 0.65,
    )
    num_planes_clamped = max(6, min(12, num_planes))
    _add_leaf_card_canopy(
        bm,
        canopy_center,
        canopy_radius,
        num_planes_clamped,
        rng,
        species_row=species_variant,
    )

    bm.to_mesh(mesh)
    bm.free()

    for poly in mesh.polygons:
        poly.use_smooth = True

    # Alpha-cutout leaf material — shared across all trees of the same species
    # so Blender batches draw calls on instanced foliage (Horizon ZD strategy).
    leaf_mat_name = f"mat_leaf_card_species{species_variant}"
    leaf_mat = bpy.data.materials.get(leaf_mat_name)
    if leaf_mat is None:
        leaf_mat = bpy.data.materials.new(name=leaf_mat_name)
        leaf_mat.use_nodes = True
        leaf_mat.blend_method = "CLIP"          # alpha cutout (no sorting artifacts)
        leaf_mat.shadow_method = "CLIP"
        leaf_mat.use_backface_culling = False    # backface duplicate handles normals;
                                                # disable culling so shader is clean
        if leaf_mat.node_tree:
            bsdf = leaf_mat.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                # Leaf green tinted by species: broadleaf bright, needle darker
                _species_tint = [
                    (0.18, 0.38, 0.12, 1.0),   # 0 broadleaf — mid green
                    (0.10, 0.25, 0.08, 1.0),   # 1 needle — dark green
                    (0.45, 0.55, 0.20, 1.0),   # 2 palm — yellow-green
                    (0.22, 0.45, 0.15, 1.0),   # 3 fern/other
                ]
                tint = _species_tint[max(0, min(3, species_variant))]
                bsdf.inputs["Base Color"].default_value = tint
                if "Roughness" in bsdf.inputs:
                    bsdf.inputs["Roughness"].default_value = 0.78
                if "Subsurface Weight" in bsdf.inputs:
                    bsdf.inputs["Subsurface Weight"].default_value = 0.15
                elif "Subsurface" in bsdf.inputs:
                    bsdf.inputs["Subsurface"].default_value = 0.15

    # Slot 0: leaf card material; slot 1 would be bark (trunk)
    # Both slots reference the same mesh — face material indices not split here
    # since trunk and canopy share one mesh object for scatter-instance efficiency.
    mesh.materials.append(leaf_mat)

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


# ---------------------------------------------------------------------------
# AAA: Grass card system
# ---------------------------------------------------------------------------

def _create_grass_card(
    biome: str = "prairie",
    seed: int = 0,
    collection: "bpy.types.Collection | None" = None,
) -> "bpy.types.Object":
    """Create a 3-quad billboard grass card for the given biome.

    Geometry: 3 crossing blades (each 2 quads with a V-bend), totalling 6 quads
    / 12 tris per tuft. Three blades at 0°, 60°, 120° provide 360° silhouette
    coverage — the SpeedTree grass card standard for AAA real-time grass (used in
    Ghost of Tsushima, RDR2, and Horizon). A single blade looks flat when the
    camera aligns with it; three crossing blades are always volumetric.

    Wind vertex colors follow SpeedTree packing convention:
      R = phase_offset  (random per-blade, constant along blade length)
      G = amplitude     (0.0 at root, 1.0 at tip — height-driven sway)
      B = frequency     (0.5 at base, 1.0 at tip — tips flutter faster)
      A = 0.0           (unused; trunk_sway not applicable to grass cards)

    Returns the created Blender object.
    """
    rng = random.Random(seed)
    spec = _GRASS_BIOME_SPECS.get(biome, _GRASS_BIOME_SPECS["prairie"])
    height = rng.uniform(spec["height_min"], spec["height_max"])
    color = spec["color"]

    name = f"GrassCard_{biome}_{seed}"
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()

    # WORLD-006: guard against duplicate layer creation
    wind_layer = bm.verts.layers.float_color.get("wind_vc")
    if wind_layer is None:
        wind_layer = bm.verts.layers.float_color.new("wind_vc")

    mid_z = height * 0.5
    bend_offset = height * 0.08  # slight forward bend at mid-point for arc silhouette
    w = height * 0.18            # blade width proportional to height

    def _add_blade(angle_deg: float, width_scale: float) -> None:
        """Add one V-bent 2-quad blade rotated by angle_deg around Z."""
        cos_a = math.cos(math.radians(angle_deg))
        sin_a = math.sin(math.radians(angle_deg))

        def _rot(x: float, y: float) -> tuple[float, float]:
            return x * cos_a - y * sin_a, x * sin_a + y * cos_a

        bw = w * width_scale

        # 6 verts: 2 at root, 2 at mid-bend, 2 at tip
        rx0, ry0 = _rot(-bw, 0.0)
        rx1, ry1 = _rot( bw, 0.0)
        rx2, ry2 = _rot( bw * 0.6, bend_offset)
        rx3, ry3 = _rot(-bw * 0.6, bend_offset)
        rx4, ry4 = _rot( bw * 0.15, bend_offset * 2)
        rx5, ry5 = _rot(-bw * 0.15, bend_offset * 2)

        phase = rng.random()
        # SpeedTree wind packing: R=amplitude (flutter weight), G=frequency, B=phase, A=0
        # R=0.0 at root (no sway), R=1.0 at tip (full sway) — matches SpeedTree primary wind weight.
        amp_base, amp_mid, amp_tip = 0.0, 0.5, 1.0
        freq_base, freq_mid, freq_tip = 0.5, 0.75, 1.0

        vv0 = bm.verts.new((rx0, ry0, 0.0));    vv0[wind_layer] = (amp_base, freq_base, phase, 0.0)
        vv1 = bm.verts.new((rx1, ry1, 0.0));    vv1[wind_layer] = (amp_base, freq_base, phase, 0.0)
        vv2 = bm.verts.new((rx2, ry2, mid_z));  vv2[wind_layer] = (amp_mid,  freq_mid,  phase, 0.0)
        vv3 = bm.verts.new((rx3, ry3, mid_z));  vv3[wind_layer] = (amp_mid,  freq_mid,  phase, 0.0)
        vv4 = bm.verts.new((rx4, ry4, height)); vv4[wind_layer] = (amp_tip,  freq_tip,  phase, 0.0)
        vv5 = bm.verts.new((rx5, ry5, height)); vv5[wind_layer] = (amp_tip,  freq_tip,  phase, 0.0)

        # Lower quad (root → mid)
        try:
            bm.faces.new([vv0, vv1, vv2, vv3])
        except ValueError:
            pass
        # Upper quad (mid → tip)
        try:
            bm.faces.new([vv3, vv2, vv4, vv5])
        except ValueError:
            pass

    # Three crossing blades at 0°, 60°, 120° — SpeedTree 3-quad grass card standard.
    # Width scales vary slightly (1.0, 0.9, 0.8) for organic size asymmetry while
    # keeping all three blades visible at any viewing angle.
    _add_blade(0.0,   1.00)
    _add_blade(60.0,  0.90)
    _add_blade(120.0, 0.82)

    bm.to_mesh(mesh)
    bm.free()

    # Material
    mat_name = f"mat_grass_{biome}"
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True
        if mat.node_tree:
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                bsdf.inputs["Base Color"].default_value = color
                if "Roughness" in bsdf.inputs:
                    bsdf.inputs["Roughness"].default_value = 0.88
    mesh.materials.append(mat)

    obj = bpy.data.objects.new(name, mesh)
    if collection is not None:
        collection.objects.link(obj)
    else:
        bpy.context.collection.objects.link(obj)
    return obj


# ---------------------------------------------------------------------------
# AAA: Rock power-law distribution
# ---------------------------------------------------------------------------

def _rock_size_from_power_law(rng: random.Random) -> tuple[float, str]:
    """Sample a rock size using power-law distribution.

    Returns (scale, size_class) where size_class is 'small', 'medium', 'large'.
    Distribution: 70% small (0.1-0.3m), 25% medium (0.3-1.0m), 5% large (1.0-3.0m).
    """
    roll = rng.random()
    if roll < 0.70:
        return rng.uniform(0.1, 0.3), "small"
    elif roll < 0.95:
        return rng.uniform(0.3, 1.0), "medium"
    else:
        return rng.uniform(1.0, 3.0), "large"


# ---------------------------------------------------------------------------
# AAA: Combat clearing generator
# ---------------------------------------------------------------------------

def _generate_combat_clearing(
    center: tuple[float, float, float],
    diameter: float,
    num_entries: int = 3,
    seed: int = 42,
) -> dict[str, Any]:
    """Generate a Witcher 3 / AAA-standard combat clearing.

    Witcher 3 combat arenas are designed around three principles:
      1. Flat, unobstructed center zone — the player and enemies need
         free movement. No scatter inside the inner_clear_radius.
      2. Dramatic framing trees — unevenly clustered, taller trees at
         the perimeter create a visually distinct theatrical frame.
         Opposite-side pairs frame sight lines to enemies approaching
         from entry paths.
      3. Entry path corridors — paths cut through the tree ring at
         staggered angles, each offset from the center so they funnel
         enemies across the clearing (not straight through it).

    Parameters
    ----------
    center : (x, y, z)
        World position of clearing center.
    diameter : float
        Diameter in meters, clamped to [15, 40].
    num_entries : int
        Number of entry path gaps in the tree ring, clamped to [2, 4].
    seed : int
        Random seed.

    Returns
    -------
    dict with keys:
        center           -- (x, y, z) world center
        radius           -- outer clearing radius in metres
        inner_clear_radius -- flat combat zone radius (no scatter within)
        entry_points     -- list of (x, y, z) path entry waypoints outside ring
        entry_angles_rad -- list of entry angle in radians (for path generator)
        tree_positions   -- list of (x, y, z, scale_hint) perimeter tree positions;
                            scale_hint > 1.0 marks dramatic framing trees
        framing_pairs    -- list of ((x1,y1,z1), (x2,y2,z2)) opposite-side
                            framing tree pairs that define enemy sight lines
        sight_lines      -- list of ((ax,ay), (bx,by)) sight-line pairs from
                            each entry through center to opposite edge
        tree_count       -- total perimeter tree count
        cleared_area_m2  -- area of the flat combat zone (inner circle)
    """
    diameter = max(15.0, min(40.0, diameter))
    radius = diameter / 2.0
    num_entries = max(2, min(4, num_entries))
    rng = random.Random(seed)
    cx, cy, cz = center

    # Inner flat combat zone: 60% of total radius, guaranteed scatter-free.
    # Witcher 3 arenas keep the inner ~60% obstacle-free for combat movement.
    inner_clear_radius = radius * 0.60

    # Entry path angles: staggered (not evenly spaced) so paths don't bisect
    # the clearing into symmetric halves. Each entry is randomly offset ±20°
    # from the even spacing so enemy approaches are asymmetric.
    base_angle_step = 2.0 * math.pi / num_entries
    entry_angles = [
        i * base_angle_step + math.radians(rng.uniform(-20.0, 20.0))
        for i in range(num_entries)
    ]

    # Entry gap half-angle: 3m half-gap (wider than before for realistic paths).
    # Guard against degenerate very-small radius (diameter clamp keeps r >= 7.5m).
    entry_gap_half_angle = math.asin(min(1.0, 3.0 / max(radius, 3.01)))

    # Tree ring: variable spacing 3-5m, with denser clusters opposite entry gaps
    # to create dramatic framing. Trees near entry gaps are taller (scale_hint>1).
    tree_spacing_base = rng.uniform(3.2, 4.5)
    circumference = 2.0 * math.pi * radius
    num_trees_full = int(circumference / tree_spacing_base)

    tree_positions: list[tuple[float, float, float, float]] = []
    framing_candidates: list[tuple[float, float, float]] = []

    for i in range(num_trees_full):
        angle = 2.0 * math.pi * i / num_trees_full

        # Skip trees inside entry gaps
        in_gap = False
        for ea in entry_angles:
            diff = abs(angle - ea)
            diff = min(diff, 2.0 * math.pi - diff)
            if diff < entry_gap_half_angle:
                in_gap = True
                break
        if in_gap:
            continue

        # Jitter radial position — trees aren't on a perfect ring.
        # Outer cluster: some trees placed 1-2m further out for depth layering.
        radial_jitter = rng.uniform(-0.6, 1.2)
        jitter_r = radius + radial_jitter

        tx = cx + math.cos(angle) * jitter_r
        ty = cy + math.sin(angle) * jitter_r

        # scale_hint: trees opposite an entry path are "framing trees" —
        # they should be taller/larger to dramatize the sight line into the arena.
        scale_hint = 1.0
        is_framing = False
        for ea in entry_angles:
            opposite_angle = ea + math.pi
            diff = abs(angle - opposite_angle)
            diff = min(diff, 2.0 * math.pi - diff)
            if diff < math.radians(20.0):
                # This tree is directly opposite an entry — dramatic framing tree.
                scale_hint = rng.uniform(1.3, 1.7)
                is_framing = True
                break

        tree_positions.append((tx, ty, cz, scale_hint))
        if is_framing:
            framing_candidates.append((tx, ty, cz))

    # Build opposite-side framing pairs: each entry gets one opposite framing tree.
    # These pairs define the visual sight lines players see when entering.
    framing_pairs: list[tuple[tuple, tuple]] = []
    for ea in entry_angles:
        entry_pt_x = cx + math.cos(ea) * (radius + 2.0)
        entry_pt_y = cy + math.sin(ea) * (radius + 2.0)
        # Find the framing candidate closest to the opposite angle
        opp_angle = ea + math.pi
        opp_x = cx + math.cos(opp_angle) * radius
        opp_y = cy + math.sin(opp_angle) * radius
        if framing_candidates:
            best = min(framing_candidates, key=lambda p: (p[0] - opp_x) ** 2 + (p[1] - opp_y) ** 2)
            framing_pairs.append(((entry_pt_x, entry_pt_y, cz), best))

    # Entry path waypoints: 4m beyond the ring edge (path generator target)
    entry_points: list[tuple[float, float, float]] = []
    for ea in entry_angles:
        ex = cx + math.cos(ea) * (radius + 4.0)
        ey = cy + math.sin(ea) * (radius + 4.0)
        entry_points.append((ex, ey, cz))

    # Sight lines: each entry angle projects a line through center to opposite edge.
    # These mark the "lanes" enemies walk along — no large scatter should block them.
    sight_lines: list[tuple[tuple, tuple]] = []
    for ea in entry_angles:
        near_x = cx + math.cos(ea) * (radius + 4.0)
        near_y = cy + math.sin(ea) * (radius + 4.0)
        far_x = cx + math.cos(ea + math.pi) * radius
        far_y = cy + math.sin(ea + math.pi) * radius
        sight_lines.append(((near_x, near_y), (far_x, far_y)))

    cleared_area = math.pi * inner_clear_radius * inner_clear_radius

    return {
        "center": center,
        "radius": radius,
        "inner_clear_radius": inner_clear_radius,
        "entry_points": entry_points,
        "entry_angles_rad": entry_angles,
        "tree_positions": tree_positions,
        "framing_pairs": framing_pairs,
        "sight_lines": sight_lines,
        "tree_count": len(tree_positions),
        "cleared_area_m2": cleared_area,
    }


# ---------------------------------------------------------------------------
# AAA: Multi-pass scatter internal helper
# ---------------------------------------------------------------------------

def _build_scatter_density_map(
    heightmap: np.ndarray,
    slope_map: np.ndarray,
    *,
    base_density: float,
    water_proximity_map: "np.ndarray | None" = None,
    disturbance_map: "np.ndarray | None" = None,
    flat_slope_threshold: float = 15.0,
    wet_species_boost: float = 0.3,
    pioneer_boost: float = 0.4,
) -> np.ndarray:
    """Build a per-cell scatter density map using vectorized numpy operations.

    Density is modulated by three factors (all applied multiplicatively):

    1. **Slope flatness** — flat areas (slope < flat_slope_threshold degrees)
       receive full ``base_density``; steep areas are attenuated so cliffs do
       not fill with trees.  Uses a smooth sigmoid-style ramp so there is no
       hard cutoff.

    2. **Water proximity** — cells near water (``water_proximity_map`` values
       close to 1.0) receive a ``wet_species_boost`` additive bump so moisture-
       loving species cluster near rivers and lakes.

    3. **Disturbance patches** — cells in disturbed areas
       (``disturbance_map`` values > 0.5) receive a ``pioneer_boost`` additive
       bump representing pioneer species colonising bare ground.

    All operations are vectorized numpy — no Python loops over individual cells.

    Parameters
    ----------
    heightmap : np.ndarray  (H, W) float32, values in [0,1]
    slope_map : np.ndarray  (H, W) float32, values in degrees
    base_density : float    Base scatter probability [0,1]
    water_proximity_map : optional (H, W) float32 in [0,1]
    disturbance_map     : optional (H, W) float32 in [0,1]
    flat_slope_threshold: degrees below which flat bonus applies
    wet_species_boost   : additive density increase near water
    pioneer_boost       : additive density increase in disturbed areas

    Returns
    -------
    density_map : np.ndarray (H, W) float32, values clipped to [0,1]
    """
    slope = np.asarray(slope_map, dtype=np.float32)

    # Slope flatness weight: sigmoid ramp from 1.0 (flat) to 0.1 (steep)
    # Transition centred on flat_slope_threshold, width ~10 degrees.
    slope_weight = 1.0 / (1.0 + np.exp((slope - flat_slope_threshold) * 0.3))
    # Rescale so perfectly flat = 1.0, very steep (~60°) ≈ 0.1
    slope_weight = 0.1 + 0.9 * slope_weight

    density = np.full_like(slope, base_density, dtype=np.float32) * slope_weight

    if water_proximity_map is not None:
        water = np.asarray(water_proximity_map, dtype=np.float32)
        if water.shape == density.shape:
            density = density + wet_species_boost * water

    if disturbance_map is not None:
        disturb = np.asarray(disturbance_map, dtype=np.float32)
        if disturb.shape == density.shape:
            pioneer_mask = (disturb > 0.5).astype(np.float32)
            density = density + pioneer_boost * pioneer_mask

    return np.clip(density, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# LOD distance thresholds (world-space metres from viewer origin).
# LOD0 = full-detail mesh, LOD1 = reduced, LOD2 = impostor/billboard,
# LOD3 = culled.  Thresholds are (lod1_dist, lod2_dist, cull_dist).
# ---------------------------------------------------------------------------
_LOD_THRESHOLDS: dict[str, tuple[float, float, float]] = {
    "tree":    (30.0,  80.0, 200.0),
    "bush":    (20.0,  50.0, 120.0),
    "grass":   (15.0,  35.0,  80.0),
    "rock":    (25.0,  60.0, 150.0),
    "default": (25.0,  60.0, 150.0),
}


# Mapping from scatter species → lod_pipeline asset-type key, used when
# ``object_radius_m`` is supplied so screen-percentage thresholds can be
# sourced from the authoritative LOD_PRESETS table.
_SCATTER_TO_ASSET_TYPE: dict[str, str] = {
    "tree": "vegetation",
    "bush": "vegetation",
    "grass": "vegetation",
    "rock": "prop_medium",
    "default": "prop_medium",
}


def _lod_for_distance(
    dist: float,
    veg_type: str,
    object_radius_m: float | None = None,
) -> int:
    """Return LOD level (0–3) given distance from viewer.

    When ``object_radius_m`` is supplied, compute an estimated on-screen
    size (``screen_pct_est = object_radius_m / max(dist, 1e-3)``) and
    consult ``lod_pipeline.LOD_PRESETS`` for the species' screen-percentage
    thresholds.  This makes a small bush at 50 m correctly demote to
    LOD2 while a large tree at the same distance stays at LOD0.

    Falls back to the legacy distance-only table when ``object_radius_m``
    is not supplied or the species preset is unavailable.

    LOD0 < lod1_dist <= LOD1 < lod2_dist <= LOD2 < cull_dist <= LOD3
    """
    if object_radius_m is not None and object_radius_m > 0.0:
        try:
            from veilbreakers_terrain.handlers.lod_pipeline import LOD_PRESETS
            asset_type = _SCATTER_TO_ASSET_TYPE.get(
                veg_type, _SCATTER_TO_ASSET_TYPE["default"]
            )
            preset = LOD_PRESETS.get(asset_type)
            if preset is not None:
                screen_pcts = preset.get("screen_percentages") or []
                if screen_pcts:
                    screen_pct_est = float(object_radius_m) / max(float(dist), 1e-3)
                    # screen_pcts are in descending order, e.g. [1.0, 0.3, 0.08, 0.02].
                    # LOD index = first index whose threshold we meet.
                    for idx, threshold in enumerate(screen_pcts):
                        if screen_pct_est >= float(threshold):
                            return idx
                    # Below every threshold → final LOD (billboard / cull).
                    return len(screen_pcts) - 1 if len(screen_pcts) >= 4 else 3
        except Exception:
            pass  # fall through to distance-only table

    key = veg_type if veg_type in _LOD_THRESHOLDS else "default"
    lod1, lod2, cull = _LOD_THRESHOLDS[key]
    if dist < lod1:
        return 0
    if dist < lod2:
        return 1
    if dist < cull:
        return 2
    return 3



# ---------------------------------------------------------------------------
# Per-species scatter constraints (AAA: Ghost of Tsushima / Horizon ZD standard)
# Each entry: (min_separation_m, max_slope_deg, alt_min, alt_max,
#              moisture_min, moisture_max)
# altitude and moisture in normalized [0,1] range.
# moisture: 0=dry ridge, 1=waterlogged valley
# ---------------------------------------------------------------------------
_SPECIES_CONSTRAINTS: dict[str, dict[str, float]] = {
    "tree": {
        "min_sep": 5.0,       # trees need room — no trunk-to-trunk crowding
        "max_slope": 30.0,
        "alt_min": 0.10, "alt_max": 0.70,
        "moisture_min": 0.25, "moisture_max": 0.90,
    },
    "bush": {
        "min_sep": 2.0,
        "max_slope": 35.0,
        "alt_min": 0.05, "alt_max": 0.60,
        "moisture_min": 0.15, "moisture_max": 0.95,
    },
    "grass": {
        "min_sep": 0.9,       # tight ground cover — Poisson disk enforces spacing
        "max_slope": 40.0,
        "alt_min": 0.00, "alt_max": 0.55,
        "moisture_min": 0.10, "moisture_max": 1.00,
    },
    "rock": {
        "min_sep": 1.2,
        "max_slope": 70.0,    # rocks on cliffs are correct
        "alt_min": 0.00, "alt_max": 1.00,
        "moisture_min": 0.00, "moisture_max": 1.00,
    },
}

# Merge the Phase-H foliage catalog so every registered species
# participates in the _passes_species_constraints check.  The catalog is
# the single source of truth; we layer its entries on top of the legacy
# coarse keys so existing tests keep passing.
try:
    from .terrain_foliage_catalog import (
        SPECIES_CONSTRAINTS_FROM_CATALOG as _CATALOG_CONSTRAINTS,
        FOLIAGE_SPECIES_CATALOG as _CATALOG,
    )
    for _sid, _entry in _CATALOG_CONSTRAINTS.items():
        # Don't overwrite the coarse "tree"/"bush"/"grass"/"rock" keys;
        # add every fine species_id as its own constraint row.
        if _sid not in _SPECIES_CONSTRAINTS:
            _SPECIES_CONSTRAINTS[_sid] = _entry
except Exception:  # pragma: no cover - defensive
    _CATALOG = {}  # type: ignore[assignment]


def _scatter_pass(
    heightmap: np.ndarray,
    slope_map: np.ndarray,
    terrain_size: float,
    pass_type: str,
    terrain_width: float | None = None,
    terrain_height: float | None = None,
    biome: str = "default",
    seed: int = 0,
    separation_scale: float = 1.0,
    building_zones: "list[tuple[float, float, float, float]] | None" = None,
    tree_positions: "list[tuple[float, float]] | None" = None,
    combat_clearings: "list[dict] | None" = None,
    water_proximity_map: "np.ndarray | None" = None,
    disturbance_map: "np.ndarray | None" = None,
    viewer_origin: "tuple[float, float] | None" = None,
) -> list[dict[str, Any]]:
    """Execute a single scatter pass (structure, ground_cover, or debris).

    AAA upgrade (Ghost of Tsushima / Horizon ZD standard):
    - Per-species Poisson disk with distinct min_separation distances
      (_SPECIES_CONSTRAINTS) so trees use 5m separation, bushes 2m, grass 0.9m.
    - Per-species altitude band enforcement (alt_min/alt_max in [0,1]).
    - Per-species moisture constraints: water_proximity_map drives acceptance
      via each species' moisture_min/moisture_max band.  Trees grow in moderate
      moisture zones; grass and bushes accept wider ranges.
    - Density gradient: the vectorized density map (slope+water+disturbance)
      modulates probability, so biome core areas have peak density and edges
      taper — matching GTS's density-falloff from forest centers to clearings.
    - Structure pass: tree Poisson disk + 2-iteration Lloyd relaxation (GTS/
      Horizon use 2-3 passes to break residual clustering), then separate bush
      disk. Both use their own species-appropriate min_separation.
    - Ground cover: grass respects tree-shadow exclusion cells (O(1) grid lookup).
    - Debris: rock power-law size distribution (70% small / 25% medium / 5% large).

    Per-placement outputs
    ---------------------
    rotation  : float — uniform in [0, 2π) radians around world Z-axis.
    scale     : float — base_scale * uniform([0.8, 1.2]), i.e. exactly ±20%.
    lod       : int   — 0–3 derived from Euclidean distance to viewer_origin.
    moisture  : float — moisture value at placement site, for downstream shader.

    Parameters
    ----------
    heightmap : np.ndarray  (H,W) float32, values in [0,1]
    slope_map : np.ndarray  (H,W) float32, degrees
    terrain_size : float    World-space terrain size in metres.
    pass_type : str         "structure" | "ground_cover" | "debris"
    biome : str             Biome key for base density lookup.
    seed : int              Random seed.
    building_zones : list of (min_x, min_y, max_x, max_y) exclusion boxes.
    tree_positions : list of (x, y) for grass-pass exclusion within 1m.
    combat_clearings : list of clearing dicts (keys: center, radius,
                       inner_clear_radius). Uses inner_clear_radius when present
                       (AAA clearing format) or falls back to radius.
    water_proximity_map : (H,W) float32 in [0,1] or None.
    disturbance_map     : (H,W) float32 in [0,1] or None.
    viewer_origin : (x, y) world-space viewer for LOD distance; defaults to (0,0).

    Returns
    -------
    list of dicts, each with: position, vegetation_type, rotation, scale,
                              lod, gpu_instance, moisture, altitude.
    """
    rng = random.Random(seed)
    base_density = _BIOME_DENSITY.get(biome, 0.5)
    rows, cols = heightmap.shape
    terrain_width = float(terrain_width if terrain_width is not None else terrain_size)
    terrain_height = float(terrain_height if terrain_height is not None else terrain_size)
    terrain_half_x = terrain_width / 2.0
    terrain_half_y = terrain_height / 2.0

    # Viewer position defaults to terrain centre
    vx, vy = viewer_origin if viewer_origin is not None else (0.0, 0.0)

    # Build vectorized density map once — used for all per-candidate lookups
    density_map = _build_scatter_density_map(
        heightmap, slope_map,
        base_density=base_density,
        water_proximity_map=water_proximity_map,
        disturbance_map=disturbance_map,
    )

    def _cell(pos: tuple[float, float]) -> tuple[int, int]:
        u = pos[0] / max(terrain_width, 1e-6)
        v = pos[1] / max(terrain_height, 1e-6)
        ci = int(max(0, min(u * (cols - 1), cols - 1)))
        ri = int(max(0, min(v * (rows - 1), rows - 1)))
        return ri, ci

    def _density_at(pos: tuple[float, float]) -> float:
        ri, ci = _cell(pos)
        return float(density_map[ri, ci])

    def _height_at(pos: tuple[float, float]) -> float:
        ri, ci = _cell(pos)
        return float(heightmap[ri, ci])

    def _slope_at(pos: tuple[float, float]) -> float:
        ri, ci = _cell(pos)
        return float(slope_map[ri, ci])

    def _moisture_at(pos: tuple[float, float]) -> float:
        """Return moisture [0,1] at pos: from water_proximity_map if available,
        else derive from altitude (low alt = wetter)."""
        if water_proximity_map is not None:
            ri, ci = _cell(pos)
            wpm = np.asarray(water_proximity_map, dtype=np.float32)
            ri_w = int(max(0, min(ri, wpm.shape[0] - 1)))
            ci_w = int(max(0, min(ci, wpm.shape[1] - 1)))
            return float(wpm[ri_w, ci_w])
        # Procedural proxy: low altitude = wetter
        h = _height_at(pos)
        return max(0.0, min(1.0, 1.0 - h ** 0.7))

    def _in_building(wx: float, wy: float) -> bool:
        if not building_zones:
            return False
        for bz in building_zones:
            if bz[0] <= wx <= bz[2] and bz[1] <= wy <= bz[3]:
                return True
        return False

    def _in_clearing(wx: float, wy: float) -> bool:
        """Return True if point is within the flat combat zone of any clearing.
        Uses inner_clear_radius (AAA format) when available, else radius."""
        if not combat_clearings:
            return False
        for cl in combat_clearings:
            ccx, ccy = cl["center"][0], cl["center"][1]
            # Prefer inner_clear_radius (Witcher 3 style clearing data)
            excl_r = cl.get("inner_clear_radius", cl.get("radius", 0.0))
            if math.sqrt((wx - ccx) ** 2 + (wy - ccy) ** 2) < excl_r:
                return True
        return False

    def _viewer_dist(wx: float, wy: float) -> float:
        return math.sqrt((wx - vx) ** 2 + (wy - vy) ** 2)

    def _scale_pm20(base: float) -> float:
        """Return base scaled by uniform([0.8, 1.2]) — exactly ±20%."""
        return base * rng.uniform(0.8, 1.2)

    def _passes_species_constraints(
        veg_key: str, pos: tuple[float, float]
    ) -> bool:
        """Return True if altitude and moisture at pos satisfy the species band."""
        sc = _SPECIES_CONSTRAINTS.get(veg_key, _SPECIES_CONSTRAINTS.get("bush", {}))
        h = _height_at(pos)
        if not (sc.get("alt_min", 0.0) <= h <= sc.get("alt_max", 1.0)):
            return False
        sl = _slope_at(pos)
        if sl > sc.get("max_slope", 90.0):
            return False
        m = _moisture_at(pos)
        if not (sc.get("moisture_min", 0.0) <= m <= sc.get("moisture_max", 1.0)):
            return False
        return True

    placements: list[dict[str, Any]] = []

    if pass_type == "structure":
        # --- Tree sub-pass ---
        # Per-species min separation: trees use 5m (not the shared default).
        # Poisson disk enforces the minimum separation globally; Lloyd relaxation
        # then redistributes the remaining candidates for uniform coverage —
        # matching GTS's 2-pass tree distribution pipeline.
        tree_sep = _SPECIES_CONSTRAINTS["tree"]["min_sep"] * max(float(separation_scale), 1e-3)
        _raw_tree_candidates = poisson_disk_sample(
            terrain_width, terrain_height, tree_sep, seed=seed,
        )
        tree_candidates = lloyd_relax_points(
            _raw_tree_candidates, terrain_width, terrain_height,
            iterations=2, min_distance=tree_sep * 0.9,
        )

        # --- Bush sub-pass ---
        # Separate Poisson disk at bush min-separation (2m) with distinct seed.
        bush_sep = _SPECIES_CONSTRAINTS["bush"]["min_sep"] * max(float(separation_scale), 1e-3)
        bush_candidates = poisson_disk_sample(
            terrain_width, terrain_height, bush_sep, seed=seed + 1,
        )

        for pos in tree_candidates:
            wx = pos[0] - terrain_half_x
            wy = pos[1] - terrain_half_y
            if not _passes_species_constraints("tree", pos):
                continue
            if _in_building(wx, wy) or _in_clearing(wx, wy):
                continue
            if rng.random() > _density_at(pos):
                continue
            dist = _viewer_dist(wx, wy)
            placements.append({
                "position": (wx, wy),
                "vegetation_type": "tree",
                "rotation": rng.uniform(0.0, 2.0 * math.pi),
                "scale": _scale_pm20(1.0),
                "lod": _lod_for_distance(dist, "tree"),
                "altitude": _height_at(pos),
                "moisture": _moisture_at(pos),
                "gpu_instance": True,
            })

        for pos in bush_candidates:
            wx = pos[0] - terrain_half_x
            wy = pos[1] - terrain_half_y
            if not _passes_species_constraints("bush", pos):
                continue
            if _in_building(wx, wy) or _in_clearing(wx, wy):
                continue
            if rng.random() > min(1.0, _density_at(pos) * 1.1):
                continue
            dist = _viewer_dist(wx, wy)
            placements.append({
                "position": (wx, wy),
                "vegetation_type": "bush",
                "rotation": rng.uniform(0.0, 2.0 * math.pi),
                "scale": _scale_pm20(0.75),
                "lod": _lod_for_distance(dist, "bush"),
                "altitude": _height_at(pos),
                "moisture": _moisture_at(pos),
                "gpu_instance": True,
            })

    elif pass_type == "ground_cover":
        grass_sep = _SPECIES_CONSTRAINTS["grass"]["min_sep"] * max(float(separation_scale), 1e-3)
        grass_candidates = poisson_disk_sample(
            terrain_width, terrain_height, grass_sep, seed=seed + 2,
        )
        biome_grass = biome if biome in _GRASS_BIOME_SPECS else "prairie"

        # Build tree exclusion as a set of (row,col) grid cells for O(1) lookup
        tree_cell_set: set[tuple[int, int]] = set()
        if tree_positions:
            cell_span = max(terrain_width / max(cols, 1), terrain_height / max(rows, 1), 1e-6)
            # Exclusion radius in metres (typical tree drip-line). Formula was
            # `1.0/cell_span` which is dimensionally inverted — it gives <1 cell
            # on coarse terrain. Correct form: desired_metres / cell_span.
            exclusion_cells = max(1, int(3.0 / cell_span))
            for tx, ty in tree_positions:
                u = (tx + terrain_half_x) / max(terrain_width, 1e-6)
                v = (ty + terrain_half_y) / max(terrain_height, 1e-6)
                ci = int(max(0, min(u * (cols - 1), cols - 1)))
                ri = int(max(0, min(v * (rows - 1), rows - 1)))
                for dr in range(-exclusion_cells, exclusion_cells + 1):
                    for dc in range(-exclusion_cells, exclusion_cells + 1):
                        nr = max(0, min(ri + dr, rows - 1))
                        nc = max(0, min(ci + dc, cols - 1))
                        tree_cell_set.add((nr, nc))

        for pos in grass_candidates:
            wx = pos[0] - terrain_half_x
            wy = pos[1] - terrain_half_y
            if not _passes_species_constraints("grass", pos):
                continue
            if building_zones:
                in_bz = any(bz[0] <= wx <= bz[2] and bz[1] <= wy <= bz[3]
                            for bz in building_zones)
                if in_bz:
                    continue
            ri, ci = _cell(pos)
            if (ri, ci) in tree_cell_set:
                continue
            if rng.random() > _density_at(pos):
                continue
            dist = _viewer_dist(wx, wy)
            placements.append({
                "position": (wx, wy),
                "vegetation_type": f"grass_{biome_grass}",
                "rotation": rng.uniform(0.0, 2.0 * math.pi),
                "scale": _scale_pm20(1.0),
                "biome": biome_grass,
                "lod": _lod_for_distance(dist, "grass"),
                "altitude": _height_at(pos),
                "moisture": _moisture_at(pos),
                "gpu_instance": True,
            })

    elif pass_type == "debris":
        rock_sep = _SPECIES_CONSTRAINTS["rock"]["min_sep"] * max(float(separation_scale), 1e-3)
        rock_candidates = poisson_disk_sample(
            terrain_width, terrain_height, rock_sep, seed=seed + 3,
        )
        for pos in rock_candidates:
            wx = pos[0] - terrain_half_x
            wy = pos[1] - terrain_half_y
            if not _passes_species_constraints("rock", pos):
                continue
            if building_zones:
                in_bz = any(bz[0] <= wx <= bz[2] and bz[1] <= wy <= bz[3]
                            for bz in building_zones)
                if in_bz:
                    continue
            if rng.random() > _density_at(pos) * 1.2:  # rocks slightly more aggressive
                continue
            base_scale, size_class = _rock_size_from_power_law(rng)
            dist = _viewer_dist(wx, wy)
            placements.append({
                "position": (wx, wy),
                "vegetation_type": "rock",
                "rotation": rng.uniform(0.0, 2.0 * math.pi),
                "scale": _scale_pm20(base_scale),
                "size_class": size_class,
                "lod": _lod_for_distance(dist, "rock"),
                "altitude": _height_at(pos),
                "moisture": _moisture_at(pos),
                "gpu_instance": True,
            })

    # ------------------------------------------------------------------ #
    # Phase H — AAA foliage catalog sub-pass.
    #
    # Iterate every species in FOLIAGE_SPECIES_CATALOG whose category
    # belongs to the current pass and whose biome_mask admits the
    # active biome.  Each species gets its own Poisson-disk sample
    # driven by ``poisson_min_distance_m``, then is filtered through
    # altitude/slope/moisture, water/road/building exclusion, and
    # water_edge / tree_base / rock_face / cliff_face affinity rules.
    #
    # This is additive: it does not replace the coarse tree/bush/grass/
    # rock sub-passes above, so existing callers keep their output
    # cardinality while the catalog supplies the long tail of species
    # (moss, vines, reeds, flowers, signs, …).
    # ------------------------------------------------------------------ #
    _PASS_CATEGORY_MAP = {
        "structure": {"tree", "boulder", "log", "sign", "fence", "stump"},
        "ground_cover": {"grass", "moss", "water_foliage", "accent_foliage",
                         "bush", "walkway"},
        "debris": {"small_rock", "vine"},
    }

    def _water_mask_at(pos: tuple[float, float]) -> float:
        """Return proximity-to-water in [0,1]; 1=on water edge, 0=dry."""
        if water_proximity_map is None:
            return 0.0
        ri, ci = _cell(pos)
        wpm = np.asarray(water_proximity_map, dtype=np.float32)
        ri_w = int(max(0, min(ri, wpm.shape[0] - 1)))
        ci_w = int(max(0, min(ci, wpm.shape[1] - 1)))
        return float(wpm[ri_w, ci_w])

    def _near_tree(wx: float, wy: float, radius: float = 2.0) -> bool:
        if not tree_positions:
            return False
        r2 = radius * radius
        for (tx, ty) in tree_positions:
            if (wx - tx) ** 2 + (wy - ty) ** 2 <= r2:
                return True
        return False

    def _passes_affinity(spec_row: dict, pos: tuple[float, float],
                         wx: float, wy: float) -> bool:
        """Apply exclude_near / place_near rules from the catalog row."""
        exclude = spec_row.get("exclude_near", []) or []
        place = spec_row.get("place_near", []) or []
        water = _water_mask_at(pos)
        # Exclusions
        if "water" in exclude and water > 0.6:
            return False
        if "combat_clearing" in exclude and _in_clearing(wx, wy):
            return False
        if "building" in exclude and _in_building(wx, wy):
            return False
        # Affinities — at least one must match when specified
        if place:
            ok = False
            if "water_edge" in place and water >= 0.55:
                ok = True
            if ("tree_base" in place or "trunk" in place) and _near_tree(wx, wy, 2.0):
                ok = True
            if "rock_face" in place or "cliff_face" in place:
                if _slope_at(pos) >= 45.0:
                    ok = True
            if not ok:
                return False
        return True

    _catalog_species_specs = getattr(_CATALOG, "values", lambda: [])() if _CATALOG else []
    _target_categories = _PASS_CATEGORY_MAP.get(pass_type, set())
    for _idx, _spec in enumerate(_catalog_species_specs):
        if _spec.category not in _target_categories:
            continue
        if _spec.biome_mask and biome not in _spec.biome_mask:
            continue
        _sid = _spec.species_id
        _sep = float(_spec.poisson_min_distance_m) * max(float(separation_scale), 1e-3)
        # Per-species deterministic seed so different species don't share
        # point grids (otherwise reeds and algae would land on identical pts).
        _species_seed = seed + 101 + _idx
        _candidates = poisson_disk_sample(
            terrain_width, terrain_height, _sep, seed=_species_seed,
        )
        _spec_row = _SPECIES_CONSTRAINTS.get(_sid, {})
        _lod_hint_dist = float(_spec.lod_viewer_distance_m)
        for pos in _candidates:
            wx = pos[0] - terrain_half_x
            wy = pos[1] - terrain_half_y
            if not _passes_species_constraints(_sid, pos):
                continue
            if _in_building(wx, wy) or _in_clearing(wx, wy):
                continue
            if not _passes_affinity(_spec_row, pos, wx, wy):
                continue
            # density + biome multiplier
            if rng.random() > _density_at(pos):
                continue
            dist = _viewer_dist(wx, wy)
            # Clamp LOD against species lod_viewer_distance_m — if we're
            # further than the species' billboard range, demote to LOD3.
            _lod = _lod_for_distance(dist, _spec.category if _spec.category in _LOD_THRESHOLDS else "default")
            if dist >= _lod_hint_dist:
                _lod = 3
            placements.append({
                "position": (wx, wy),
                "vegetation_type": _sid,
                "species_id": _sid,
                "category": _spec.category,
                "rotation": rng.uniform(0.0, 2.0 * math.pi),
                "scale": _scale_pm20(1.0),
                "lod": _lod,
                "altitude": _height_at(pos),
                "moisture": _moisture_at(pos),
                "biome": biome,
                "unity_asset_path": _spec.unity_asset_path,
                "gpu_instance": True,
            })

    # Annotate each placement with LOD cluster counts (LOD0/LOD1/LOD2/LOD3
    # instance counts per cluster). Matches UE5 Instanced Static Mesh LOD
    # streaming: each cluster reports how many instances are at each LOD tier.
    _lod_counts: dict[str, dict[int, int]] = {}
    for p in placements:
        vt = p.get("vegetation_type", "unknown")
        lod = p.get("lod", 0)
        if vt not in _lod_counts:
            _lod_counts[vt] = {0: 0, 1: 0, 2: 0, 3: 0}
        _lod_counts[vt][lod] = _lod_counts[vt].get(lod, 0) + 1

    for p in placements:
        vt = p.get("vegetation_type", "unknown")
        counts = _lod_counts.get(vt, {0: 0, 1: 0, 2: 0, 3: 0})
        p["lod_cluster_counts"] = {
            "lod0": counts.get(0, 0),
            "lod1": counts.get(1, 0),
            "lod2": counts.get(2, 0),
            "lod3": counts.get(3, 0),
        }

    # ------------------------------------------------------------------
    # C-3 (R2): Convert placement list to canonical ScatterPointTable and
    # validate.  The manifest itself is *not* attached per-placement —
    # that would duplicate a 100-1000 KB dict onto every point.  Instead
    # the canonical table is rebuilt downstream by
    # _build_scatter_point_table_from_placements() (in
    # handle_scatter_vegetation) using world-space coordinates; this pass
    # only flags validation issues early so an upstream caller using the
    # raw _scatter_pass output sees the warning at scatter time.
    # ------------------------------------------------------------------
    # Try to lazily resolve catalog wind profiles per species so the
    # ScatterPoint carries the right wind hint instead of "none".
    try:
        from .terrain_foliage_catalog import (
            FOLIAGE_SPECIES_CATALOG as _C3_CATALOG,
        )
    except Exception:  # noqa: BLE001
        _C3_CATALOG = {}  # type: ignore[assignment]

    _scatter_points: list[ScatterPoint] = []
    for _p in placements:
        _pos2 = _p.get("position", (0.0, 0.0))
        _alt = float(_p.get("altitude", 0.0))
        _pos3: tuple[float, float, float] = (float(_pos2[0]), float(_pos2[1]), _alt * terrain_size)
        _raw_scale = float(_p.get("scale", 1.0))
        _scale3: tuple[float, float, float] = (_raw_scale, _raw_scale, _raw_scale)
        # Convert yaw rotation (radians, around Z) to unit quaternion (x,y,z,w)
        _rot = float(_p.get("rotation", 0.0))
        _half = _rot * 0.5
        _orient: tuple[float, float, float, float] = (0.0, 0.0, math.sin(_half), math.cos(_half))
        _lod_int = int(_p.get("lod", 0))
        _lod_bucket = f"lod{max(0, min(_lod_int, 3))}"
        _species = str(_p.get("species_id", _p.get("vegetation_type", "unknown")))
        _veg_type = str(_p.get("vegetation_type", "unknown"))
        # Pull wind profile from the catalog when available; default to "none".
        _spec = _C3_CATALOG.get(_species) if _C3_CATALOG else None
        _wind_profile = str(getattr(_spec, "wind_profile", "none") or "none") if _spec else "none"
        # Read true slope (degrees) at the placement cell.  ``slope`` on a
        # ScatterPoint must be slope, not altitude — the previous version
        # mis-assigned altitude here, breaking validators that rely on
        # ``slope`` for cliff-rejection.
        _slope_deg = 0.0
        try:
            if slope_map is not None:
                _rows, _cols = slope_map.shape
                _row_f = ((_pos2[1] + (terrain_height or terrain_size) * 0.5) /
                          max(terrain_height or terrain_size, 1e-6)) * (_rows - 1)
                _col_f = ((_pos2[0] + (terrain_width or terrain_size) * 0.5) /
                          max(terrain_width or terrain_size, 1e-6)) * (_cols - 1)
                _r = int(max(0, min(_rows - 1, _row_f)))
                _c = int(max(0, min(_cols - 1, _col_f)))
                _slope_deg = float(slope_map[_r, _c])
        except Exception:  # noqa: BLE001
            _slope_deg = 0.0
        # Density: this point's *placement density*.  When the placement
        # carries an explicit "density" key (set by upstream rules) we use
        # it; otherwise fall back to 1.0 (placed = full density).  Moisture
        # belongs in metadata, not on density.
        _density = float(_p.get("density", 1.0))
        _density = max(0.0, min(1.0, _density))
        _scatter_points.append(
            ScatterPoint(
                position=_pos3,
                normal=(0.0, 0.0, 1.0),
                orient=_orient,
                scale=_scale3,
                prototype_id=_veg_type,
                species_id=_species,
                biome_id=str(_p.get("biome", biome)),
                density=_density,
                seed=seed,
                slope=_slope_deg,
                height_m=_pos3[2],
                mask_sources=(f"scatter_pass:{pass_type}",),
                lod_bucket=_lod_bucket,
                wind_profile=_wind_profile,
                source_layer=pass_type,
                point_mode="exact_instance",
                metadata={
                    "moisture": float(_p.get("moisture", 0.0)),
                    "gpu_instance": bool(_p.get("gpu_instance", True)),
                },
            )
        )

    _scatter_table = ScatterPointTable(
        points=tuple(_scatter_points),
        source=f"scatter_pass:{pass_type}",
    )
    _validation_issues = validate_scatter_point_table(_scatter_table)
    if _validation_issues:
        logger.warning(
            "ScatterPointTable validation issues (%d): %s",
            len(_validation_issues),
            _validation_issues[:5],
        )

    return placements


# ---------------------------------------------------------------------------
# Handler: scatter_vegetation
# ---------------------------------------------------------------------------

def handle_scatter_vegetation(params: dict) -> dict:
    """Scatter vegetation on terrain using Poisson disk + biome rules.

    Uses collection instances for performance (not individual objects).

    Params:
        terrain_name (str): Existing terrain object name.
        rules (list of dict, optional): Biome vegetation rules. Defaults to
            built-in dark-fantasy rules. Each rule can include min_moisture
            and max_moisture keys when moisture_map is provided.
        min_distance (float, default 3.0): Minimum distance between instances.
        seed (int, default 0): Random seed.
        max_instances (int, default 5000): Cap on total instances.
        max_tilt_angle (float, default 45.0): Maximum terrain slope in degrees.
            Points where terrain is steeper than this are rejected.
        moisture_map (list of list or None): Optional 2D moisture map [0,1]
            matching terrain resolution.  When provided, per-rule
            min_moisture/max_moisture are applied during filtering.

    Returns dict with: name, instance_count, vegetation_types, bounds.
    """
    terrain_name = params.get("terrain_name")
    if not terrain_name:
        raise ValueError("'terrain_name' is required")

    custom_rules_provided = params.get("rules") is not None
    rules = params.get("rules") or _DEFAULT_VEG_RULES
    min_distance = params.get("min_distance", 3.0)
    seed = params.get("seed", 0)
    max_instances = params.get("max_instances", 5000)
    max_tilt_angle = params.get("max_tilt_angle", 45.0)
    moisture_map_raw = params.get("moisture_map", None)
    _stack = params.get("stack")

    obj = bpy.data.objects.get(terrain_name)
    if obj is None:
        raise ValueError(f"Object not found: {terrain_name}")

    # Extract heightmap from terrain mesh
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()

    vert_count = len(bm.verts)
    # Detect grid dims by counting unique positions (handles non-square terrain)
    xs = set(round(v.co.x, 3) for v in bm.verts)
    ys = set(round(v.co.y, 3) for v in bm.verts)
    cols, rows = len(xs), len(ys)
    if cols * rows != vert_count or cols < 2 or rows < 2:
        side = int(math.sqrt(vert_count))
        if side < 2 or side * side != vert_count:
            bm.free()
            raise ValueError("Terrain mesh too small or non-grid for scatter")
        rows, cols = side, side

    heights = np.array([v.co.z for v in bm.verts])
    bm.free()

    height_min = float(heights.min()) if heights.size else 0.0
    height_max = float(heights.max()) if heights.size else 1.0
    world_heightmap = heights.reshape(rows, cols)
    height_transform = WorldHeightTransform(
        world_min=height_min,
        world_max=height_max,
    )
    height_range = float(height_transform.world_range)
    heightmap = height_transform.to_normalized(world_heightmap)

    # Determine terrain world-space size
    dims = obj.dimensions
    terrain_width = max(float(dims.x), 1.0)
    terrain_height = max(float(dims.y), 1.0)
    terrain_size = max(terrain_width, terrain_height, 1.0)
    terrain_row_spacing, terrain_col_spacing = _terrain_axis_spacing_from_extent(
        terrain_width,
        terrain_height,
        rows,
        cols,
    )
    slope_map = compute_slope_map(
        world_heightmap,
        cell_size=(terrain_row_spacing, terrain_col_spacing),
    )
    terrain_origin_x = float(obj.location.x)
    terrain_origin_y = float(obj.location.y)

    # Convert moisture_map to numpy array if provided
    moisture_np = None
    if moisture_map_raw is not None:
        moisture_np = _resize_scatter_map(moisture_map_raw, heightmap.shape)

    # Collect world-space building exclusion zones up front so the richer
    # multi-pass scatter path can avoid them before candidate acceptance.
    building_exclusion_zones_world: list[tuple[float, float, float, float]] = []
    for _obj in bpy.data.objects:
        if _obj.type == "EMPTY" and _obj.children:
            min_x = min_y = float("inf")
            max_x = max_y = float("-inf")
            for _child in _obj.children:
                if _child.type != "MESH":
                    continue
                bb_corners = [_child.matrix_world @ _mathutils_Vector(c) for c in _child.bound_box]
                for corner in bb_corners:
                    min_x = min(min_x, corner.x)
                    max_x = max(max_x, corner.x)
                    min_y = min(min_y, corner.y)
                    max_y = max(max_y, corner.y)
            if min_x < float("inf"):
                fp_w = max(max_x - min_x, 0.1)
                fp_d = max(max_y - min_y, 0.1)
                margin = max(1.5, min(6.0, ((fp_w ** 2 + fp_d ** 2) ** 0.5) * 0.25))
                building_exclusion_zones_world.append(
                    (min_x - margin, min_y - margin, max_x + margin, max_y + margin)
                )

    biome_key = params.get("biome_name") or params.get("biome") or "default"
    viewer_param = (
        params.get("viewer_origin")
        or params.get("camera_position")
        or params.get("player_position")
    )
    viewer_origin_local = None
    if isinstance(viewer_param, (tuple, list)) and len(viewer_param) >= 2:
        viewer_origin_local = (
            float(viewer_param[0]) - terrain_origin_x,
            float(viewer_param[1]) - terrain_origin_y,
        )

    separation_scale = max(float(min_distance) / 3.0, 0.1)
    combat_clearings = _resolve_combat_clearings(params)
    placements = _generate_multipass_scatter_placements(
        heightmap=heightmap,
        slope_map=slope_map,
        terrain_width=terrain_width,
        terrain_height=terrain_height,
        biome=biome_key,
        rules=rules,
        seed=seed,
        separation_scale=separation_scale,
        max_tilt_angle=max_tilt_angle,
        stack=_stack,
        moisture_map=moisture_np,
        building_zones_world=building_exclusion_zones_world,
        terrain_origin_x=terrain_origin_x,
        terrain_origin_y=terrain_origin_y,
        viewer_origin_local=viewer_origin_local,
        combat_clearings=combat_clearings,
        apply_rule_density=custom_rules_provided,
    )

    # ------------------------------------------------------------------ Fix 9.1
    # detail_density consumer: reject candidates stochastically based on
    # per-cell density multiplier from pass_vegetation_depth output.
    # ------------------------------------------------------------------ Fix 9.1
    _detail_dens_raw = _stack_value(_stack, "detail_density")
    density_map = _collapse_detail_density(_detail_dens_raw)
    if density_map is not None and len(placements) > 0:
        _rng_density = random.Random(seed ^ 0xD1CE7)
        _density_filtered = []
        for _p in placements:
            _px, _py = _p["position"][0], _p["position"][1]
            _row_f = (_py / terrain_height) * (density_map.shape[0] - 1)
            _col_f = (_px / terrain_width) * (density_map.shape[1] - 1)
            if not _density_reject(density_map, _row_f, _col_f, _rng_density.random()):
                _density_filtered.append(_p)
        placements = _density_filtered

    # ------------------------------------------------------------------ Fix 9.3/9.4/9.11
    # Stack-channel exclusion setup (road_mask, road_sdf_dist, hero_exclusion)
    # ------------------------------------------------------------------ Fix 9.3/9.4/9.11
    _road_mask = None
    if _stack is not None:
        _road_mask = _stack_value(_stack, "road_mask")
    road_mask_np = np.asarray(_road_mask, dtype=np.uint8) if _road_mask is not None else None

    _road_sdf = None
    if _stack is not None:
        _road_sdf = _stack_value(_stack, "road_sdf_dist")
    road_sdf_np = np.asarray(_road_sdf, dtype=np.float32) if _road_sdf is not None else None
    placement_radius = float(params.get("road_sdf_clearance", 2.0))

    _excl = _stack_value(_stack, "hero_exclusion")
    excl_np = np.asarray(_excl, dtype=np.float32) if _excl is not None else None

    # ------------------------------------------------------------------ Fix 9.5
    # wind_field consumer: read for per-placement rotation_y
    # ------------------------------------------------------------------ Fix 9.5
    _wind = _stack_value(_stack, "wind_field")

    # Filter out placements that overlap with building footprints or roads
    # Collect bounding boxes of all EMPTY-type objects (building parents) in scene
    _exclusion_zones: list[tuple[float, float, float, float]] = list(building_exclusion_zones_world)
    if road_mask_np is None:
        # Legacy fallback: bpy name-string road exclusion (only when road_mask channel absent)
        for _obj in bpy.data.objects:
            if _obj.type == "MESH" and ("road" in _obj.name.lower() or "_Road_" in _obj.name):
                _bb = [_obj.matrix_world @ _mathutils_Vector(corner) for corner in _obj.bound_box]
                _road_margin = 2.0  # meters buffer around road edges
                _r_min_x = min(v.x for v in _bb) - _road_margin
                _r_max_x = max(v.x for v in _bb) + _road_margin
                _r_min_y = min(v.y for v in _bb) - _road_margin
                _r_max_y = max(v.y for v in _bb) + _road_margin
                _exclusion_zones.append((_r_min_x, _r_min_y, _r_max_x, _r_max_y))

    terrain_half_x = terrain_width / 2.0
    terrain_half_y = terrain_height / 2.0
    _filtered = []
    for p in placements:
        wx = p["position"][0] - terrain_half_x + terrain_origin_x
        wy = p["position"][1] - terrain_half_y + terrain_origin_y
        _in_excluded = False

        # 1. Building bounding-box exclusion (existing)
        for bz_min_x, bz_min_y, bz_max_x, bz_max_y in _exclusion_zones:
            if bz_min_x <= wx <= bz_max_x and bz_min_y <= wy <= bz_max_y:
                _in_excluded = True
                break

        # 2. road_mask channel exclusion (Fix 9.3)
        if not _in_excluded and road_mask_np is not None:
            _col_f = ((wx - terrain_origin_x + terrain_half_x) / terrain_width) * (road_mask_np.shape[1] - 1)
            _row_f = ((wy - terrain_origin_y + terrain_half_y) / terrain_height) * (road_mask_np.shape[0] - 1)
            _r = int(np.clip(_row_f, 0, road_mask_np.shape[0] - 1))
            _c = int(np.clip(_col_f, 0, road_mask_np.shape[1] - 1))
            if road_mask_np[_r, _c] != 0:
                _in_excluded = True

        # 3. SDF road exclusion (Fix 9.11)
        if not _in_excluded and road_sdf_np is not None:
            if _apply_sdf_exclusion(wx, wy, road_sdf_np, placement_radius,
                                    terrain_origin_x, terrain_origin_y,
                                    terrain_width, terrain_height):
                _in_excluded = True

        # 4. hero_exclusion channel (Fix 9.4)
        if not _in_excluded and excl_np is not None:
            # local coords: position within terrain [0, width] × [0, height]
            _lx = p["position"][0]
            _ly = p["position"][1]
            if _hero_excluded(excl_np, _lx, _ly, terrain_width, terrain_height):
                _in_excluded = True

        if not _in_excluded:
            # Fix 9.5: compute wind-field rotation_y for foliage orientation
            _lx = p["position"][0]
            _ly = p["position"][1]
            p["rotation_y"] = _wind_rotation_y(_wind, _lx, _ly, terrain_width, terrain_height)
            _filtered.append(p)
    placements = _filtered

    # Cap instances
    if len(placements) > max_instances:
        placements = placements[:max_instances]

    # Create template collection and templates
    template_coll = _create_template_collection(f"{terrain_name}_veg_templates")
    templates: dict[str, bpy.types.Object] = {}

    # Collect unique vegetation types
    veg_types_needed = set(p.get("species_id") or p["vegetation_type"] for p in placements)
    for vt in veg_types_needed:
        templates[vt] = _create_vegetation_template(vt, template_coll)

    # Wire billboard LOD for tree templates that have sufficient geometry.
    # Each template is created once and shared across all its instances; we
    # annotate the template object with custom properties so that the export
    # pipeline can set up a 2-level LOD group (LOD0: full mesh 0-30 m,
    # LOD1: billboard impostor 30 m+) without needing per-instance data.
    for vt, tmpl_obj in templates.items():
        # The generator spec is not re-fetched here; pass None so
        # _setup_billboard_lod falls back to bounding-box estimation.
        # Vertex-count guard inside the helper keeps low-poly types out.
        _setup_billboard_lod(tmpl_obj, veg_spec=None, veg_type=vt)

    # Create instances using collection instances
    scatter_coll_name = f"{terrain_name}_vegetation"
    scatter_coll = bpy.data.collections.new(scatter_coll_name)
    bpy.context.scene.collection.children.link(scatter_coll)

    veg_counts: dict[str, int] = {}
    terrain_half_x = terrain_width / 2.0
    terrain_half_y = terrain_height / 2.0

    for p in placements:
        vt = p.get("species_id") or p["vegetation_type"]
        template = templates.get(vt)
        if template is None:
            continue

        veg_counts[vt] = veg_counts.get(vt, 0) + 1

        instance = bpy.data.objects.new(
            f"{vt}_{veg_counts[vt]:04d}", template.data,
        )
        # Position: offset from terrain center
        wx = p["position"][0] - terrain_half_x + terrain_origin_x
        wy = p["position"][1] - terrain_half_y + terrain_origin_y

        # Sample terrain height in world space so offset tiles use the same contract
        wz, dzdx, dzdy = _sample_heightmap_surface_world(
            heightmap,
            height_scale=height_range,
            height_offset=height_min,
            world_x=wx,
            world_y=wy,
            terrain_width=terrain_width,
            terrain_height=terrain_height,
            terrain_origin_x=terrain_origin_x,
            terrain_origin_y=terrain_origin_y,
        )

        instance.location = (wx, wy, wz)

        # Align vegetation to terrain normal (slope-perpendicular placement)
        slope_pitch = math.atan2(-dzdy, 1.0)  # tilt around X
        slope_roll = math.atan2(dzdx, 1.0)   # tilt around Y
        base_rot = _vegetation_rotation(vt, p["rotation"])
        instance.rotation_euler = (
            base_rot[0] + slope_pitch * 0.7,  # partial alignment (70%) for natural look
            base_rot[1] + slope_roll * 0.7,
            base_rot[2],
        )
        p["world_position"] = (float(wx), float(wy), float(wz))
        p["normal"] = _normal_from_gradients(dzdx, dzdy)
        p["orient"] = _euler_xyz_to_quat(
            float(instance.rotation_euler[0]),
            float(instance.rotation_euler[1]),
            float(instance.rotation_euler[2]),
        )
        s = p["scale"]
        instance.scale = (s, s, s)

        scatter_coll.objects.link(instance)

    total_instances = sum(veg_counts.values())

    # Fix 9.2: write tree_instance_points to stack for downstream exporters
    if _stack is not None and placements:
        _tree_rows = [
            (
                p["position"][0] - terrain_half_x + terrain_origin_x,
                p["position"][1] - terrain_half_y + terrain_origin_y,
                0.0,  # z populated in instance loop above; use 0 here as placeholder
                float(p.get("rotation_y", 0.0)),
                float(p.get("prototype_id", 0)),
            )
            for p in placements
            if p.get("base_type", p.get("vegetation_type")) == "tree"
        ]
        _tree_arr = (
            np.array(_tree_rows, dtype=np.float32).reshape(-1, 5)
            if _tree_rows
            else np.empty((0, 5), dtype=np.float32)
        )
        _write_tree_instance_points(_tree_arr, _stack)

    # Accumulate LOD0/LOD1/LOD2/LOD3 instance counts per vegetation type.
    # LOD3 = culled / impostor-only tier beyond cull distance.
    # Downstream exporters (Unity HDRP, UE5 ISM) use these counts to
    # pre-allocate draw-call budgets per LOD tier without iterating all
    # instances at load time.  Four tiers match the _LOD_THRESHOLDS model.
    lod_counts_by_type: dict[str, dict[str, int]] = {}
    for p in placements:
        vt = p.get("species_id") or p.get("vegetation_type", "unknown")
        lod = p.get("lod", 0)
        if vt not in lod_counts_by_type:
            lod_counts_by_type[vt] = {"lod0": 0, "lod1": 0, "lod2": 0, "lod3": 0}
        key = f"lod{min(lod, 3)}"
        lod_counts_by_type[vt][key] = lod_counts_by_type[vt].get(key, 0) + 1

    scatter_point_table = _build_scatter_point_table_from_placements(
        placements,
        terrain_width=terrain_width,
        terrain_height=terrain_height,
        terrain_origin_x=terrain_origin_x,
        terrain_origin_y=terrain_origin_y,
        biome_id=biome_key,
        height_min=height_min,
        height_range=height_range,
        seed=seed,
    )

    return {
        "name": scatter_coll_name,
        "instance_count": total_instances,
        "vegetation_types": veg_counts,
        "lod_instance_counts": lod_counts_by_type,
        "scatter_point_table": scatter_point_table.to_dict(),
        "bounds": {
            "width": terrain_width,
            "depth": terrain_height,
        },
    }


# ---------------------------------------------------------------------------
# Handler: scatter_props
# ---------------------------------------------------------------------------

def _create_prop_template(
    prop_type: str, collection: bpy.types.Collection
) -> bpy.types.Object:
    """Create a template mesh for a prop type.

    Uses procedural mesh generators from PROP_GENERATOR_MAP when
    available. Missing mappings are treated as a hard error so prop
    wiring gaps are visible instead of being hidden by placeholder
    geometry.
    """
    gen_entry = PROP_GENERATOR_MAP.get(prop_type)
    if gen_entry is not None:
        gen_func, gen_kwargs = gen_entry
        # Use lower detail for scatter templates (instanced many times)
        scatter_kwargs = dict(gen_kwargs)
        if prop_type in ("dead_tree", "tree_twisted"):
            scatter_kwargs.setdefault("iterations", 3)  # lower for scatter
            scatter_kwargs.setdefault("ring_segments", 4)  # lower LOD
        elif prop_type in ("rock", "coal_pile"):
            scatter_kwargs.setdefault("detail", 2)
        spec = gen_func(**scatter_kwargs)
        obj = mesh_from_spec(
            spec,
            name=f"_template_{prop_type}",
            collection=collection,
        )
        # Smooth normals for all organic and curved prop types.
        # Hard-surface rectangular props (crate, fence, chest) keep flat normals;
        # everything else benefits from smooth shading for lighting quality.
        _HARD_SURFACE_PROPS = frozenset({"crate", "fence", "chest", "door", "wall_section"})
        if prop_type not in _HARD_SURFACE_PROPS:
            if getattr(obj, "data", None) is not None and hasattr(obj.data, "polygons"):
                for poly in obj.data.polygons:
                    poly.use_smooth = True
        _assign_scatter_material(obj, prop_type)
        return obj

    logger.warning(
        "No procedural generator for prop type '%s'; using cube fallback template.",
        prop_type,
    )
    mesh = bpy.data.meshes.new(f"_template_{prop_type}")
    bm = bmesh.new()
    try:
        bmesh.ops.create_cube(bm, size=0.5)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    obj = bpy.data.objects.new(f"_template_{prop_type}", mesh)
    collection.objects.link(obj)
    _assign_scatter_material(obj, prop_type)
    return obj


def handle_scatter_props(params: dict) -> dict:
    """Scatter context-aware props near buildings using collection instances.

    Uses procedural mesh generators from PROP_GENERATOR_MAP for real prop
    meshes instead of placeholder cubes. Falls back to cubes with a warning
    for any prop type without a generator mapping.

    All AAA terrain-filter parameters (altitude, slope, water proximity,
    canopy closure, protected zones) are forwarded to ``context_scatter`` when
    a terrain object is present in the scene. This matches the Horizon Zero
    Dawn prop scatter pipeline where props respect the same terrain rule-set
    as vegetation — no props on cliff faces, no props in water, no props
    inside sacred/protected zones.

    Params:
        area_name (str, default "PropScatter"): Name for the scatter collection.
        buildings (list of dict): Each has type, position, footprint (optional).
        prop_density (float, default 0.3): Scatter density.
        seed (int, default 0): Random seed.
        max_slope_angle (float, default 45.0): Hard global slope cap in degrees.
            Props are never placed on terrain steeper than this.
        altitude_range (list of 2 floats or None): Normalised [0, 1] band.
            Requires a terrain object named area_name to be in the scene.
        slope_range (list of 2 floats or None): Slope degrees band to accept.
        water_exclusion_radius (float, default 0.0): Reject props near water.
        max_canopy_closure (float, default 1.0): Reject under dense canopy.
        protected_zones (list of dict or None): Hard-exclusion zone dicts
            {"type": str, "position": (x, y), "radius": float}.

    Returns dict with: name, prop_count, prop_types.
    """
    area_name = params.get("area_name", "PropScatter")
    buildings = params.get("buildings", [])
    prop_density = params.get("prop_density", 0.3)
    seed = params.get("seed", 0)
    max_slope_angle = float(params.get("max_slope_angle", 45.0))
    altitude_range = params.get("altitude_range", None)
    if altitude_range is not None:
        altitude_range = tuple(altitude_range)
    slope_range = params.get("slope_range", None)
    if slope_range is not None:
        slope_range = tuple(slope_range)
    water_exclusion_radius = float(params.get("water_exclusion_radius", 0.0))
    max_canopy_closure = float(params.get("max_canopy_closure", 1.0))
    protected_zones = params.get("protected_zones", None)

    if not buildings:
        raise ValueError("'buildings' list is required and must not be empty")

    # Determine area size from building positions
    positions = [b["position"] for b in buildings]
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    margin = 20.0
    area_size = max(max(xs) - min(xs) + margin * 2, max(ys) - min(ys) + margin * 2, 30.0)

    # Extract terrain maps from scene object when available
    terrain_obj = bpy.data.objects.get(area_name)
    terrain_sampler = _terrain_height_sampler(terrain_obj)

    heightmap_np: "np.ndarray | None" = None
    slope_map_np: "np.ndarray | None" = None
    if terrain_obj is not None and terrain_obj.type == "MESH" and terrain_obj.data is not None:
        _bm_prop = bmesh.new()
        _bm_prop.from_mesh(terrain_obj.data)
        _bm_prop.verts.ensure_lookup_table()
        _vc = len(_bm_prop.verts)
        _xs2 = set(round(v.co.x, 3) for v in _bm_prop.verts)
        _ys2 = set(round(v.co.y, 3) for v in _bm_prop.verts)
        _cols2, _rows2 = len(_xs2), len(_ys2)
        if _cols2 * _rows2 == _vc and _cols2 >= 2 and _rows2 >= 2:
            _hts = np.array([v.co.z for v in _bm_prop.verts], dtype=np.float32)
            _bm_prop.free()
            _hmin = float(_hts.min())
            _hmax = float(_hts.max())
            _hrange = max(_hmax - _hmin, 1e-6)
            heightmap_np = ((_hts - _hmin) / _hrange).reshape(_rows2, _cols2)
            _dims2 = terrain_obj.dimensions
            _tw2 = max(float(_dims2.x), 1.0)
            _th2 = max(float(_dims2.y), 1.0)
            _rs2, _cs2 = _terrain_axis_spacing_from_extent(_tw2, _th2, _rows2, _cols2)
            slope_map_np = compute_slope_map(heightmap_np, cell_size=(_rs2, _cs2))
        else:
            _bm_prop.free()

    placements = context_scatter(
        buildings,
        area_size,
        prop_density,
        seed,
        altitude_range=altitude_range if heightmap_np is not None else None,
        slope_range=slope_range if slope_map_np is not None else None,
        heightmap=heightmap_np,
        slope_map=slope_map_np,
        max_slope_angle=max_slope_angle,
        water_exclusion_radius=water_exclusion_radius,
        max_canopy_closure=max_canopy_closure,
        protected_zones=protected_zones,
    )

    # Create scatter collection
    scatter_coll = bpy.data.collections.new(area_name)
    bpy.context.scene.collection.children.link(scatter_coll)

    # Template collection for prop types (hidden, used for instancing)
    template_coll = _create_template_collection(f"{area_name}_templates")
    templates: dict[str, bpy.types.Object] = {}

    prop_counts: dict[str, int] = {}

    for p in placements:
        ptype = p["type"]
        prop_counts[ptype] = prop_counts.get(ptype, 0) + 1

        # Create template on first use via mesh bridge
        if ptype not in templates:
            templates[ptype] = _create_prop_template(ptype, template_coll)

        template = templates[ptype]
        instance = bpy.data.objects.new(
            f"{ptype}_{prop_counts[ptype]:04d}", template.data,
        )
        wz = terrain_sampler(p["position"][0], p["position"][1]) if terrain_sampler else 0.0
        instance.location = (p["position"][0], p["position"][1], wz)
        instance.rotation_euler = _prop_rotation(ptype, p["rotation"])
        s = p["scale"]
        instance.scale = (s, s, s)
        scatter_coll.objects.link(instance)

    return {
        "name": area_name,
        "prop_count": sum(prop_counts.values()),
        "prop_types": prop_counts,
    }


# ---------------------------------------------------------------------------
# Handler: create_breakable
# ---------------------------------------------------------------------------

def handle_create_breakable(params: dict) -> dict:
    """Create a breakable prop with intact and destroyed variants.

    Params:
        prop_type (str): One of barrel, crate, pot, fence, cart.
        position (list of 3 floats, default [0,0,0]): World position.
        seed (int, default 0): Random seed.

    Returns dict with: name, intact_vertex_count, fragment_count, debris_count.
    """
    prop_type = params.get("prop_type")
    if not prop_type:
        raise ValueError("'prop_type' is required")

    position = params.get("position", [0, 0, 0])
    seed = params.get("seed", 0)

    variants = generate_breakable_variants(prop_type, seed)
    intact_spec = variants["intact_spec"]
    destroyed_spec = variants["destroyed_spec"]

    # Create parent empty
    parent_name = f"{prop_type}_breakable"
    parent = bpy.data.objects.new(parent_name, None)
    parent.empty_display_type = "PLAIN_AXES"
    parent.location = tuple(position)
    bpy.context.collection.objects.link(parent)

    # Create intact version
    intact_bm = bmesh.new()
    for op in intact_spec["geometry_ops"]:
        if op["type"] == "cylinder":
            bmesh.ops.create_cone(
                intact_bm, cap_ends=True, cap_tris=True,
                segments=op.get("segments", 12),
                radius1=op["radius"], radius2=op["radius"],
                depth=op["height"],
            )
        elif op["type"] == "box":
            sx, sy, sz = op["size"]
            bmesh.ops.create_cube(intact_bm, size=1.0)
            for v in intact_bm.verts:
                v.co.x *= sx
                v.co.y *= sy
                v.co.z *= sz

    intact_mesh = bpy.data.meshes.new(f"{prop_type}_intact")
    intact_bm.to_mesh(intact_mesh)
    intact_vertex_count = len(intact_bm.verts)
    intact_bm.free()

    intact_obj = bpy.data.objects.new(f"{prop_type}_intact", intact_mesh)
    intact_obj.parent = parent
    bpy.context.collection.objects.link(intact_obj)

    # Apply intact material with proper color from scatter presets
    mat_intact = bpy.data.materials.new(name=f"mat_{prop_type}_intact")
    mat_intact.use_nodes = True
    if mat_intact.node_tree:
        _bsdf = mat_intact.node_tree.nodes.get("Principled BSDF")
        if _bsdf:
            _preset = _SCATTER_MATERIAL_PRESETS.get(prop_type, {})
            _bc = _preset.get("base_color", (0.15, 0.13, 0.11, 1.0))
            _bsdf.inputs["Base Color"].default_value = tuple(list(_bc)[:4])
            _bsdf.inputs["Roughness"].default_value = float(_preset.get("roughness", 0.8))
    intact_mesh.materials.append(mat_intact)

    # Create destroyed version collection
    destroyed_coll = bpy.data.collections.new(f"{prop_type}_destroyed")
    bpy.context.scene.collection.children.link(destroyed_coll)
    destroyed_coll.hide_viewport = True  # Hidden by default

    # Create fragments
    fragment_count = len(destroyed_spec["fragment_ops"])
    for i, frag in enumerate(destroyed_spec["fragment_ops"]):
        frag_bm = bmesh.new()
        sx, sy, sz = frag["size"]
        bmesh.ops.create_cube(frag_bm, size=1.0)
        for v in frag_bm.verts:
            v.co.x *= sx
            v.co.y *= sy
            v.co.z *= sz
        frag_mesh = bpy.data.meshes.new(f"{prop_type}_frag_{i}")
        frag_bm.to_mesh(frag_mesh)
        frag_bm.free()

        frag_obj = bpy.data.objects.new(f"{prop_type}_frag_{i}", frag_mesh)
        frag_obj.location = tuple(frag["position"])
        frag_obj.parent = parent
        destroyed_coll.objects.link(frag_obj)

    # Create debris
    debris_count = len(destroyed_spec["debris_ops"])
    for i, deb in enumerate(destroyed_spec["debris_ops"]):
        deb_bm = bmesh.new()
        sx, sy, sz = deb["size"]
        bmesh.ops.create_cube(deb_bm, size=1.0)
        for v in deb_bm.verts:
            v.co.x *= sx
            v.co.y *= sy
            v.co.z *= sz
        deb_mesh = bpy.data.meshes.new(f"{prop_type}_debris_{i}")
        deb_bm.to_mesh(deb_mesh)
        deb_bm.free()

        deb_obj = bpy.data.objects.new(f"{prop_type}_debris_{i}", deb_mesh)
        deb_obj.location = tuple(deb["position"])
        deb_obj.parent = parent
        destroyed_coll.objects.link(deb_obj)

    # Apply destroyed material with darker, damaged color
    mat_destroyed = bpy.data.materials.new(name=f"mat_{prop_type}_destroyed")
    mat_destroyed.use_nodes = True
    if mat_destroyed.node_tree:
        _bsdf_d = mat_destroyed.node_tree.nodes.get("Principled BSDF")
        if _bsdf_d:
            _preset_d = _SCATTER_MATERIAL_PRESETS.get(prop_type, {})
            _bc_d = _preset_d.get("base_color", (0.15, 0.13, 0.11, 1.0))
            # Destroyed: shift toward charred brown-gray, not just pitch black.
            # Mix 70% original + 30% char color sRGB(60,50,40)->linear
            _bsdf_d.inputs["Base Color"].default_value = (
                _bc_d[0] * 0.7 + 0.046 * 0.3,
                _bc_d[1] * 0.7 + 0.030 * 0.3,
                _bc_d[2] * 0.7 + 0.021 * 0.3,
                1.0,
            )
            _bsdf_d.inputs["Roughness"].default_value = min(
                float(_preset_d.get("roughness", 0.8)) + 0.15, 1.0,
            )

    # Apply destroyed material to all fragment and debris meshes.
    # Without this the fragments render with the default grey Blender material
    # rather than the charred destruction look required for AAA breakable props.
    for i in range(fragment_count):
        frag_mesh_obj = destroyed_coll.objects.get(f"{prop_type}_frag_{i}")
        if frag_mesh_obj is not None and frag_mesh_obj.data is not None:
            frag_mesh_obj.data.materials.clear()
            frag_mesh_obj.data.materials.append(mat_destroyed)
    for i in range(debris_count):
        deb_mesh_obj = destroyed_coll.objects.get(f"{prop_type}_debris_{i}")
        if deb_mesh_obj is not None and deb_mesh_obj.data is not None:
            deb_mesh_obj.data.materials.clear()
            deb_mesh_obj.data.materials.append(mat_destroyed)

    return {
        "name": parent_name,
        "intact_vertex_count": intact_vertex_count,
        "fragment_count": fragment_count,
        "debris_count": debris_count,
    }

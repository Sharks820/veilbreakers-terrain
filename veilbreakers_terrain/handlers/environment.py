"""Environment handlers for terrain generation, biome painting, water, and export.

Provides terrain/environment command handlers:
  - handle_generate_terrain: Heightmap -> bmesh grid terrain mesh
  - handle_generate_terrain_tile: World-space tiled terrain mesh
  - handle_generate_world_terrain: Multi-tile world region generation
  - handle_paint_terrain: Slope/altitude biome rules -> material slot assignment
  - handle_carve_river: River channel carving along A* path
  - handle_generate_road: A-to-B road with proper grading
  - handle_create_water: Lake/ocean/pond plane with shoreline
  - handle_export_heightmap: 16-bit Unity RAW export
  - handle_export_unity_bundle: Unity terrain bundle export + descriptor bridge
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import warnings
import zlib
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

import numpy as np

from .terrain_protocol import enforce_protocol

# Lazy-import guard: bpy/bmesh only available inside Blender. Modules that
# transitively import this file outside Blender (tests, CI) must not crash at
# import time; guarded functions raise RuntimeError at call time instead.
bpy: Any = None
bmesh: Any = None
try:
    import bpy as _bpy
    import bmesh as _bmesh
    bpy = _bpy
    bmesh = _bmesh
except ModuleNotFoundError:
    pass
_HAS_BPY = bpy is not None and bmesh is not None


def _require_bpy() -> None:
    """Raise RuntimeError if bpy/bmesh are not available (outside Blender)."""
    if not _HAS_BPY:
        raise RuntimeError(
            "This function requires Blender (bpy + bmesh). "
            "It cannot run outside the Blender Python runtime."
        )


logger = logging.getLogger(__name__)

GLOBAL_LOG_FLOW_NORM = 12.0

__all__ = [
    "_normalize_altitude_for_rule_range",
    "_point_segment_distance_2d",
    "_require_bpy",
]

from ._terrain_noise import (  # noqa: E402
    generate_heightmap,
    carve_river_path,
    generate_road_path_grid_legacy,
    _theoretical_max_amplitude,
    TERRAIN_PRESETS,
    BIOME_RULES,
)
from ._terrain_world import (  # noqa: E402
    erode_world_heightmap,
    generate_world_heightmap,
)
# NOTE: extract_tile and world_region_dimensions were removed from this import
# because they are only used by the deprecated handle_generate_world_terrain.
# They remain available in _terrain_world for direct import if needed.
from .terrain_materials import compute_world_splatmap_weights  # noqa: E402
from .terrain_features import generate_waterfall  # noqa: E402
from .terrain_waterfalls_volumetric import (  # noqa: E402
    build_waterfall_functional_object_names,
    enforce_functional_object_naming,
)
from ._water_network import WaterNetwork  # noqa: E402
from .road_network import compute_road_network  # noqa: E402
from .terrain_semantics import TerrainMaskStack, WorldHeightTransform  # noqa: E402
from .terrain_path_contracts import (  # noqa: E402
    PathNetworkContract,
    PathSegmentContract,
    infer_continuation_edge,
    material_stack_for_path,
    validate_path_network_contract,
)


# ---------------------------------------------------------------------------
# POI mask rasterization (pure logic — no bpy required)
# ---------------------------------------------------------------------------


def rasterize_poi_mask(
    stack: "TerrainMaskStack",
    pois: Sequence[Sequence[float]],
    radius_m: float = 20.0,
) -> np.ndarray:
    """Rasterize a list of POI world-space positions into a (H, W) float32 mask.

    Each POI within ``radius_m`` metres contributes 1.0 at its centre,
    decaying linearly to 0.0 at the radius boundary. Overlapping POIs take
    the maximum of their contributions.

    T-14-04-01 mitigation: cap POI list at 1000 entries to prevent
    O(N * H * W) blow-up from unbounded POI injection.

    Parameters
    ----------
    stack : TerrainMaskStack
        Must have ``height`` populated (for shape) and ``cell_size`` set.
    pois : list of (world_x, world_y) or (world_x, world_y, ...) tuples
    radius_m : float
        Influence radius in world metres. Default 20.0.

    Side effect
    -----------
    Calls ``stack.set("poi_mask", mask, "rasterize_poi_mask")`` before returning.
    """
    if len(pois) > 1000:
        raise ValueError(
            f"rasterize_poi_mask: poi list length {len(pois)} exceeds cap of 1000 "
            "entries (T-14-04-01 DoS mitigation). Split into batches."
        )

    h_arr = np.asarray(stack.height)
    H, W = h_arr.shape
    cs = float(stack.cell_size) if stack.cell_size else 1.0
    ox = float(stack.world_origin_x)
    oy = float(stack.world_origin_y)

    mask = np.zeros((H, W), dtype=np.float32)
    radius_cells = max(1, int(math.ceil(radius_m / cs)))

    row_grid, col_grid = np.mgrid[0:H, 0:W].astype(np.float64)

    for poi in pois:
        wx = float(poi[0])
        wy = float(poi[1])
        # Convert world position to fractional cell indices
        col_c = (wx - ox) / cs - 0.5
        row_c = (wy - oy) / cs - 0.5

        r0 = max(0, int(row_c) - radius_cells - 1)
        r1 = min(H, int(row_c) + radius_cells + 2)
        c0 = max(0, int(col_c) - radius_cells - 1)
        c1 = min(W, int(col_c) + radius_cells + 2)

        dist = np.sqrt(
            ((row_grid[r0:r1, c0:c1] - row_c) * cs) ** 2
            + ((col_grid[r0:r1, c0:c1] - col_c) * cs) ** 2
        )
        contribution = np.clip(1.0 - dist / max(radius_m, 1e-9), 0.0, 1.0).astype(np.float32)
        mask[r0:r1, c0:c1] = np.maximum(mask[r0:r1, c0:c1], contribution)

    stack.set("poi_mask", mask, "rasterize_poi_mask")
    return mask


# ---------------------------------------------------------------------------
# Validation helpers (pure logic -- testable without Blender)
# ---------------------------------------------------------------------------

_VALID_TERRAIN_TYPES = frozenset(TERRAIN_PRESETS.keys())
_VALID_EROSION_MODES = frozenset({"none", "hydraulic", "thermal", "both"})
_MAX_RESOLUTION = 4096  # 8192 can OOM Blender; 4096 is practical AAA limit
_MIN_WATER_ELEVATION_M = 0.04  # prevents Z-fighting with terrain mesh
_DEFAULT_NOISE_SCALE_FACTORS: dict[str, float] = {
    "mountains": 0.24,
    "hills": 0.32,
    "plains": 0.55,
    "volcanic": 0.22,
    "canyon": 0.20,
    "cliffs": 0.18,
    "flat": 0.70,
    "coastal": 0.35,
    "swamp": 0.50,
    "chaotic": 0.16,
}
_TARGET_RELIEF_COVERAGE: dict[str, float] = {
    "mountains": 0.92,
    "hills": 0.68,
    "plains": 0.24,
    "volcanic": 0.95,
    "canyon": 0.88,
    "cliffs": 0.90,
    "flat": 0.12,
    "coastal": 0.56,
    "swamp": 0.18,
    "chaotic": 1.00,
}
_MAX_RELIEF_BOOST: dict[str, float] = {
    "mountains": 4.0,
    "hills": 2.6,
    "plains": 1.6,
    "volcanic": 4.0,
    "canyon": 3.5,
    "cliffs": 4.2,
    "flat": 1.4,
    "coastal": 3.0,
    "swamp": 2.0,
    "chaotic": 4.5,
}
_SPIKE_PRONE_TERRAIN = frozenset({"mountains", "volcanic", "cliffs", "chaotic"})


def _vector_xyz(vec: Any) -> tuple[float, float, float]:
    """Return ``(x, y, z)`` from a Blender vector-like object or tuple."""
    if hasattr(vec, "x") and hasattr(vec, "y") and hasattr(vec, "z"):
        return float(vec.x), float(vec.y), float(vec.z)
    return float(vec[0]), float(vec[1]), float(vec[2])


# Phase 50-02 G2: _detect_grid_dims / _detect_grid_dims_from_vertices
# relocated to veilbreakers_terrain.procedural_meshes (toolkit primitive).
# Re-exported here for backward compatibility with intra-terrain callers
# (lines 2667, 3681, 4149, 4317, 5047, 5211 of this file).
from ..procedural_meshes import (  # noqa: E402, F401  -- intentional post-imports re-export
    _detect_grid_dims,
    _detect_grid_dims_from_vertices,
)


def _object_world_xyz(obj: Any, local_co: Any) -> tuple[float, float, float]:
    """Resolve a local mesh coordinate to world space with safe fallbacks."""
    matrix_world = getattr(obj, "matrix_world", None)
    if matrix_world is not None:
        try:
            world_co = matrix_world @ local_co
            return _vector_xyz(world_co)
        except Exception as exc:
            logger.warning("Optional subsystem matrix_world_transform failed (non-fatal): %s", exc)

    x, y, z = _vector_xyz(local_co)
    location = getattr(obj, "location", None)
    if location is None:
        return x, y, z
    lx, ly, lz = _vector_xyz(location)
    return x + lx, y + ly, z + lz


def _run_height_solver_in_world_space(
    heightmap: np.ndarray,
    solver: Callable[..., tuple[list[tuple[int, int]], np.ndarray]],
    /,
    **solver_kwargs: Any,
) -> tuple[list[tuple[int, int]], np.ndarray, WorldHeightTransform]:
    """Run a normalized terrain-path solver while preserving world-unit heights.

    ``carve_river_path`` and ``generate_road_path`` still operate in a
    normalized ``[0, 1]`` domain. This adapter preserves signed/negative
    elevations by explicitly normalizing with ``WorldHeightTransform`` and
    restoring the world-unit result after the solver returns.
    """
    world_heightmap = np.asarray(heightmap, dtype=np.float64)
    if world_heightmap.ndim != 2:
        raise ValueError("heightmap must be a 2D array")

    transform = WorldHeightTransform(
        world_min=float(world_heightmap.min()) if world_heightmap.size else 0.0,
        world_max=float(world_heightmap.max()) if world_heightmap.size else 0.0,
    )
    normalized = np.clip(transform.to_normalized(world_heightmap), 0.0, 1.0)
    path, solved = solver(normalized, **solver_kwargs)
    restored = transform.from_normalized(np.asarray(solved, dtype=np.float64))
    return path, restored, transform


def _coerce_optional_grid_channel(
    value: Any,
    *,
    expected_shape: tuple[int, int],
) -> np.ndarray | None:
    """Return an optional 2-D float32 channel when it matches the terrain grid."""
    if value is None:
        return None
    arr = np.asarray(value, dtype=np.float32)
    if arr.ndim != 2 or tuple(arr.shape) != tuple(expected_shape):
        return None
    finite = arr[np.isfinite(arr)]
    replace_hi = float(finite.max()) if finite.size else 1.0
    cleaned = np.nan_to_num(arr, nan=0.0, posinf=replace_hi, neginf=0.0)
    np.maximum(cleaned, 0.0, out=cleaned)
    return np.ascontiguousarray(cleaned, dtype=np.float32)


def _resolve_road_cost_context(
    params: dict[str, Any],
    *,
    heightmap: np.ndarray,
) -> tuple[np.ndarray | None, str | None]:
    """Resolve the cost context used by the public road handler."""
    explicit_cost_map = _coerce_optional_grid_channel(
        params.get("road_cost_map", params.get("cost_map")),
        expected_shape=heightmap.shape,
    )
    if explicit_cost_map is not None:
        return explicit_cost_map.astype(np.float32, copy=False), "explicit_cost_map"

    rock_hardness = _coerce_optional_grid_channel(
        params.get("rock_hardness"),
        expected_shape=heightmap.shape,
    )
    water_surface = _coerce_optional_grid_channel(
        params.get("water_surface"),
        expected_shape=heightmap.shape,
    )
    if rock_hardness is None and water_surface is None:
        return None, None

    # Reuse the same road-cost synthesis as the canonical tiled world path.
    from .terrain_twelve_step import _build_road_cost_map

    sources: list[str] = []
    if rock_hardness is not None:
        sources.append("rock_hardness")
    if water_surface is not None:
        sources.append("water_surface")
    return (
        _build_road_cost_map(
            heightmap,
            rock_hardness=rock_hardness,
            water_surface=water_surface,
        ),
        "+".join(sources),
    )


def _normalize_altitude_for_rule_range(
    altitude_z: float,
    *,
    range_min: float,
    range_max: float,
) -> float:
    """Map a world/local Z value into the biome-rule altitude domain [0, 1]."""
    span = max(float(range_max) - float(range_min), 1e-9)
    normalized = (float(altitude_z) - float(range_min)) / span
    return max(0.0, min(1.0, normalized))


def _resolve_noise_sampling_scale(
    terrain_size: float,
    terrain_type: str,
    explicit_noise_scale: float | None = None,
) -> float:
    """Resolve a terrain noise sampling scale independent from footprint size."""
    if explicit_noise_scale is not None:
        resolved = float(explicit_noise_scale)
        if resolved <= 0.0:
            raise ValueError("noise_scale must be positive")
        return resolved

    factor = _DEFAULT_NOISE_SCALE_FACTORS.get(terrain_type, 0.25)
    return max(float(terrain_size) * factor, 24.0)


def _enforce_generate_terrain_protocol(
    params: dict[str, Any],
    *,
    resolution: int,
    scale: float,
    seed: int,
) -> None:
    """Fail closed on public terrain generation unless opt-outs are explicit."""
    if params.get("enforce_protocol", True) is False:
        return

    from .terrain_protocol import ProtocolGate
    from .terrain_semantics import BBox, TerrainIntentState, TerrainMaskStack, TerrainPipelineState

    tile_size = max(int(resolution) - 1, 1)
    cell_size = float(scale) / float(tile_size)
    object_location = tuple(params.get("object_location", (0.0, 0.0, 0.0)))
    world_origin_x = float(object_location[0]) - float(scale) * 0.5
    world_origin_y = float(object_location[1]) - float(scale) * 0.5
    region = BBox(
        min_x=world_origin_x,
        min_y=world_origin_y,
        max_x=world_origin_x + float(scale),
        max_y=world_origin_y + float(scale),
    )
    mask_stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=cell_size,
        world_origin_x=world_origin_x,
        world_origin_y=world_origin_y,
        tile_x=int(params.get("tile_x", 0)),
        tile_y=int(params.get("tile_y", 0)),
        height=np.zeros((int(resolution), int(resolution)), dtype=np.float64),
    )
    intent = TerrainIntentState(
        seed=int(seed),
        region_bounds=region,
        tile_size=tile_size,
        cell_size=cell_size,
        quality_profile=str(params.get("quality_profile", "aaa_open_world")),
        composition_hints=dict(params.get("composition_hints") or {}),
    )
    state = TerrainPipelineState(intent=intent, mask_stack=mask_stack)
    state.viewport_vantage = params.get("viewport_vantage")

    ProtocolGate.rule_2_sync_to_user_viewport(
        state,
        out_of_view_ok=bool(params.get("out_of_view_ok", False)),
    )
    ProtocolGate.rule_4_real_geometry_not_vertex_tricks(params)
    ProtocolGate.rule_5_smallest_diff_per_iteration(
        state,
        cells_affected=int(params.get("cells_affected", mask_stack.height.size)),
        objects_affected=int(params.get("objects_affected", 0)),
        bulk_edit=bool(params.get("bulk_edit", False)),
    )
    ProtocolGate.rule_6_surface_vs_interior_classification(params)


def _enhance_heightmap_relief(
    heightmap: np.ndarray,
    *,
    terrain_type: str,
) -> np.ndarray:
    """Stretch terrain relief without destroying the existing macro patterning."""
    arr = np.asarray(heightmap, dtype=np.float64)
    if arr.size == 0:
        return arr

    target_span = _TARGET_RELIEF_COVERAGE.get(terrain_type, 0.6)
    low = float(np.percentile(arr, 5.0))
    high = float(np.percentile(arr, 95.0))
    current_span = high - low
    if current_span <= 1e-6 or current_span >= target_span:
        return arr

    center = 0.0 if low < 0.0 < high else (low + high) * 0.5
    scale = min(
        target_span / current_span,
        _MAX_RELIEF_BOOST.get(terrain_type, 2.0),
    )
    return (arr - center) * scale + center


def _temper_heightmap_spikes(
    heightmap: np.ndarray,
    *,
    terrain_type: str,
) -> np.ndarray:
    """Compress isolated needle peaks so mountain terrain reads as landforms, not spikes."""
    arr = np.asarray(heightmap, dtype=np.float64)
    if arr.size == 0 or terrain_type not in _SPIKE_PRONE_TERRAIN:
        return arr

    upper_start = float(np.percentile(arr, 96.0))
    upper_extreme = float(np.percentile(arr, 99.7))
    if upper_extreme <= upper_start + 1e-6:
        return arr

    upper_span = max(upper_extreme - upper_start, 1e-6)
    padded = np.pad(arr, 1, mode="edge")
    neighborhood_mean = (
        padded[0:-2, 0:-2]
        + padded[0:-2, 1:-1]
        + padded[0:-2, 2:]
        + padded[1:-1, 0:-2]
        + padded[1:-1, 1:-1]
        + padded[1:-1, 2:]
        + padded[2:, 0:-2]
        + padded[2:, 1:-1]
        + padded[2:, 2:]
    ) / 9.0

    result = arr.copy()
    upper_mask = arr > upper_start
    compressed = upper_start + upper_span * np.tanh((arr - upper_start) / upper_span)
    result[upper_mask] = compressed[upper_mask]

    spike_mask = arr > float(np.percentile(arr, 99.15))
    if np.any(spike_mask):
        result[spike_mask] = (
            neighborhood_mean[spike_mask] * 0.72
            + result[spike_mask] * 0.28
        )

    result = result * 0.88 + neighborhood_mean * 0.12
    return result


# ---------------------------------------------------------------------------
# VeilBreakers biome presets
# ---------------------------------------------------------------------------

# Erosion iteration policy: any preset with erosion enabled MUST use at least
# 5000 iterations.  Values below 5000 produce no visible erosion channels and
# defeat the purpose of the simulation pass.  Mountain/extreme biomes may use
# higher values (e.g. 8000-10000) for deeper carving.
VB_BIOME_PRESETS: dict[str, dict[str, Any]] = {
    "thornwood_forest": {
        "terrain_type": "hills",
        "resolution": 512,
        "height_scale": 15.0,
        "erosion": True,
        "erosion_iterations": 5000,
        "seed": None,  # random
        "scatter_rules": [
            {"asset": "tree_healthy", "density": 0.24, "min_distance": 4.5, "scale_range": [1.0, 1.9]},
            {"asset": "tree_boundary", "density": 0.14, "min_distance": 4.0, "scale_range": [0.9, 1.8]},
            {"asset": "tree_blighted", "density": 0.05, "min_distance": 5.5, "scale_range": [0.8, 1.4]},
            {"asset": "shrub", "density": 0.24, "min_distance": 2.0, "scale_range": [0.7, 1.2]},
            {"asset": "grass", "density": 0.35, "min_distance": 1.2, "scale_range": [0.6, 1.0]},
            {"asset": "rock_mossy", "density": 0.10, "min_distance": 3.0, "scale_range": [0.7, 1.3]},
            {"asset": "root", "density": 0.07, "min_distance": 2.6, "scale_range": [0.7, 1.1]},
            {"asset": "mushroom_cluster", "density": 0.05, "min_distance": 1.8, "scale_range": [0.45, 0.9]},
            {"asset": "fallen_log", "density": 0.02, "min_distance": 8.0, "scale_range": [0.8, 1.2]},
        ],
    },
    "corrupted_swamp": {
        "terrain_type": "flat",
        "resolution": 512,
        "height_scale": 5.0,
        "erosion": True,
        "erosion_iterations": 5000,
        "seed": None,
        "scatter_rules": [
            {"asset": "dead_tree", "density": 0.2, "min_distance": 4.0, "scale_range": [0.6, 1.0]},
            {"asset": "poison_pool", "density": 0.1, "min_distance": 8.0, "scale_range": [1.0, 2.0]},
            {"asset": "vine_cluster", "density": 0.3, "min_distance": 2.0, "scale_range": [0.5, 1.5]},
            {"asset": "spore_pod", "density": 0.15, "min_distance": 3.0, "scale_range": [0.3, 0.8]},
        ],
    },
    "mountain_pass": {
        "terrain_type": "mountains",
        "resolution": 512,
        "height_scale": 40.0,
        "erosion": True,
        "erosion_iterations": 5000,
        "seed": None,
        "default_season": "winter",
        "scatter_rules": [
            {"asset": "boulder", "density": 0.18, "min_distance": 5.0, "scale_range": [0.9, 2.8]},
            {"asset": "rock_mossy", "density": 0.16, "min_distance": 3.4, "scale_range": [0.8, 1.8]},
            {"asset": "pine_tree", "density": 0.11, "min_distance": 7.5, "scale_range": [0.9, 1.4]},
            {"asset": "tree_boundary", "density": 0.04, "min_distance": 8.0, "scale_range": [0.85, 1.25]},
            {"asset": "shrub", "density": 0.18, "min_distance": 2.1, "scale_range": [0.7, 1.1]},
            {"asset": "grass", "density": 0.14, "min_distance": 1.4, "scale_range": [0.5, 0.9]},
            {"asset": "fallen_log", "density": 0.03, "min_distance": 9.0, "scale_range": [0.85, 1.15]},
        ],
        "season_profiles": {
            "summer": {
                "scatter_rules": [
                    {"asset": "boulder", "density": 0.20, "min_distance": 5.0, "scale_range": [0.9, 3.0]},
                    {"asset": "rock_mossy", "density": 0.18, "min_distance": 3.4, "scale_range": [0.8, 1.9]},
                    {"asset": "pine_tree", "density": 0.11, "min_distance": 7.5, "scale_range": [0.9, 1.5]},
                    {"asset": "tree_boundary", "density": 0.05, "min_distance": 8.0, "scale_range": [0.85, 1.3]},
                    {"asset": "shrub", "density": 0.26, "min_distance": 2.0, "scale_range": [0.7, 1.2]},
                    {"asset": "grass", "density": 0.24, "min_distance": 1.3, "scale_range": [0.55, 1.0]},
                    {"asset": "fallen_log", "density": 0.04, "min_distance": 9.0, "scale_range": [0.85, 1.2]},
                ],
            },
            "winter": {
                "scatter_rules": [
                    {"asset": "boulder", "density": 0.18, "min_distance": 5.0, "scale_range": [0.9, 3.0]},
                    {"asset": "rock_mossy", "density": 0.14, "min_distance": 3.8, "scale_range": [0.8, 1.8]},
                    {"asset": "pine_tree", "density": 0.10, "min_distance": 8.0, "scale_range": [0.95, 1.45]},
                    {"asset": "tree_boundary", "density": 0.04, "min_distance": 8.5, "scale_range": [0.85, 1.25]},
                    {"asset": "shrub", "density": 0.10, "min_distance": 2.5, "scale_range": [0.7, 1.0]},
                    {"asset": "grass", "density": 0.06, "min_distance": 1.7, "scale_range": [0.5, 0.85]},
                    {"asset": "fallen_log", "density": 0.03, "min_distance": 9.5, "scale_range": [0.85, 1.2]},
                    {"asset": "snow_patch", "density": 0.18, "min_distance": 5.5, "scale_range": [1.1, 2.8]},
                ],
            },
        },
    },
    "ruined_fortress": {
        "terrain_type": "hills",
        "resolution": 257,
        "height_scale": 12.0,
        "erosion": True,
        "erosion_iterations": 5000,
        "seed": None,
        "scatter_rules": [
            {"asset": "rubble_pile", "density": 0.35, "min_distance": 2.0, "scale_range": [0.5, 1.5]},
            {"asset": "broken_pillar", "density": 0.1, "min_distance": 5.0, "scale_range": [0.8, 1.5]},
            {"asset": "wall_fragment", "density": 0.15, "min_distance": 4.0, "scale_range": [0.6, 1.2]},
            {"asset": "dead_tree", "density": 0.08, "min_distance": 6.0, "scale_range": [0.8, 1.2]},
            {"asset": "iron_fence", "density": 0.05, "min_distance": 7.0, "scale_range": [1.0, 1.0]},
        ],
    },
    "abandoned_village": {
        "terrain_type": "plains",
        "resolution": 257,
        "height_scale": 6.0,
        "erosion": False,
        "erosion_iterations": 0,
        "seed": None,
        "scatter_rules": [
            {"asset": "collapsed_roof", "density": 0.15, "min_distance": 6.0, "scale_range": [0.8, 1.2]},
            {"asset": "broken_cart", "density": 0.08, "min_distance": 8.0, "scale_range": [0.8, 1.0]},
            {"asset": "barrel", "density": 0.2, "min_distance": 3.0, "scale_range": [0.6, 1.0]},
            {"asset": "crate", "density": 0.2, "min_distance": 3.0, "scale_range": [0.5, 0.9]},
            {"asset": "weed_patch", "density": 0.3, "min_distance": 2.0, "scale_range": [0.4, 1.0]},
        ],
    },
    "veil_crack_zone": {
        "terrain_type": "chaotic",
        "resolution": 257,
        "height_scale": 20.0,
        "erosion": False,
        "erosion_iterations": 0,
        "seed": None,
        "scatter_rules": [
            {"asset": "crystal_shard", "density": 0.3, "min_distance": 2.0, "scale_range": [0.3, 2.0]},
            {"asset": "void_tendril", "density": 0.1, "min_distance": 5.0, "scale_range": [0.5, 1.5]},
            {"asset": "floating_rock", "density": 0.15, "min_distance": 4.0, "scale_range": [0.5, 3.0]},
            {"asset": "corruption_pool", "density": 0.08, "min_distance": 8.0, "scale_range": [1.0, 2.0]},
        ],
    },
    "underground_dungeon": {
        "terrain_type": "flat",
        "resolution": 257,
        "height_scale": 2.0,
        "erosion": False,
        "erosion_iterations": 0,
        "seed": None,
        "scatter_rules": [
            {"asset": "stalagmite", "density": 0.15, "min_distance": 3.0, "scale_range": [0.5, 1.5]},
            {"asset": "bone_pile", "density": 0.1, "min_distance": 4.0, "scale_range": [0.3, 0.8]},
            {"asset": "cobweb", "density": 0.2, "min_distance": 2.0, "scale_range": [0.5, 1.0]},
            {"asset": "torch_sconce", "density": 0.05, "min_distance": 8.0, "scale_range": [1.0, 1.0]},
        ],
    },
    "sacred_shrine": {
        "terrain_type": "plains",
        "resolution": 257,
        "height_scale": 4.0,
        "erosion": False,
        "erosion_iterations": 0,
        "seed": None,
        "scatter_rules": [
            {"asset": "stone_lantern", "density": 0.1, "min_distance": 5.0, "scale_range": [0.8, 1.2]},
            {"asset": "offering_bowl", "density": 0.08, "min_distance": 6.0, "scale_range": [0.6, 1.0]},
            {"asset": "prayer_flag", "density": 0.12, "min_distance": 4.0, "scale_range": [0.8, 1.0]},
            {"asset": "moss_patch", "density": 0.25, "min_distance": 2.0, "scale_range": [0.5, 1.5]},
            {"asset": "cherry_blossom", "density": 0.06, "min_distance": 7.0, "scale_range": [1.0, 1.8]},
        ],
    },
    "battlefield": {
        "terrain_type": "hills",
        "resolution": 257,
        "height_scale": 8.0,
        "erosion": False,
        "erosion_iterations": 0,
        "seed": None,
        "scatter_rules": [
            {"asset": "broken_weapon", "density": 0.3, "min_distance": 2.0, "scale_range": [0.5, 1.0]},
            {"asset": "shield_fragment", "density": 0.2, "min_distance": 2.5, "scale_range": [0.4, 0.8]},
            {"asset": "bone_pile", "density": 0.15, "min_distance": 3.0, "scale_range": [0.5, 1.2]},
            {"asset": "banner_torn", "density": 0.05, "min_distance": 8.0, "scale_range": [1.0, 1.5]},
            {"asset": "crater", "density": 0.08, "min_distance": 6.0, "scale_range": [1.0, 2.0]},
        ],
    },
    "cemetery": {
        "terrain_type": "flat",
        "resolution": 257,
        "height_scale": 3.0,
        "erosion": False,
        "erosion_iterations": 0,
        "seed": None,
        "scatter_rules": [
            {"asset": "gravestone", "density": 0.5, "min_distance": 2.0, "scale_range": [0.8, 1.2]},
            {"asset": "dead_tree", "density": 0.08, "min_distance": 8.0, "scale_range": [1.0, 2.0]},
            {"asset": "iron_fence", "density": 0.1, "min_distance": 3.0, "scale_range": [1.0, 1.0]},
            {"asset": "fog_emitter", "density": 0.05, "min_distance": 10.0, "scale_range": [1.0, 1.0]},
        ],
    },
}


_EXTERNAL_MODEL_PROMPTS: dict[str, dict[str, Any]] = {
    "boulder": {
        "prompt": "low poly alpine boulder, grassy summer cliff biome, weathered stone, subtle moss, game ready environment prop",
        "asset_class": "rock_large",
        "suggested_max_vertices": 1800,
    },
    "rock_mossy": {
        "prompt": "low poly mossy cliff rock, alpine summer environment, broken stone slab, game ready scatter prop",
        "asset_class": "rock_medium",
        "suggested_max_vertices": 1200,
    },
    "pine_tree": {
        "prompt": "low poly alpine pine tree, summer mountain pass, readable silhouette, optimized for mass placement",
        "asset_class": "tree_conifer",
        "suggested_max_vertices": 2500,
    },
    "tree_boundary": {
        "prompt": "low poly windswept mountain tree, sparse summer foliage, alpine cliff edge biome, optimized for distance placement",
        "asset_class": "tree_boundary",
        "suggested_max_vertices": 2200,
    },
    "shrub": {
        "prompt": "low poly alpine shrub clump, grassy cliff biome in july, dark green leaves, game ready ground scatter",
        "asset_class": "shrub",
        "suggested_max_vertices": 700,
    },
    "grass": {
        "prompt": "low poly alpine grass tuft cluster, july mountain pass, damp green blades, optimized ground cover",
        "asset_class": "ground_cover",
        "suggested_max_vertices": 240,
    },
    "fallen_log": {
        "prompt": "low poly fallen mountain log, weathered bark, grassy cliff biome, game ready environment scatter prop",
        "asset_class": "deadwood",
        "suggested_max_vertices": 900,
    },
    # Dark-forest biome assets
    "tree_healthy": {
        "prompt": "low poly healthy broadleaf forest tree, dark fantasy woodland, dense canopy, game ready scatter prop",
        "asset_class": "tree_conifer",
        "suggested_max_vertices": 2400,
    },
    "tree_blighted": {
        "prompt": "low poly blighted dead tree, dark fantasy corrupted forest, twisted bare branches, game ready environment prop",
        "asset_class": "tree_boundary",
        "suggested_max_vertices": 1600,
    },
    "root": {
        "prompt": "low poly gnarled surface root cluster, dark forest floor, twisted wood, game ready ground scatter prop",
        "asset_class": "deadwood",
        "suggested_max_vertices": 600,
    },
    "mushroom_cluster": {
        "prompt": "low poly glowing mushroom cluster, dark fantasy forest floor, bioluminescent caps, game ready scatter prop",
        "asset_class": "ground_cover",
        "suggested_max_vertices": 480,
    },
    # Corrupted marsh biome assets
    "dead_tree": {
        "prompt": "low poly dead leafless tree, corrupted dark fantasy swamp, rotting bark, game ready environment scatter prop",
        "asset_class": "tree_boundary",
        "suggested_max_vertices": 1400,
    },
    "poison_pool": {
        "prompt": "low poly toxic pool prop, corrupted marsh biome, bubbling green liquid surface, game ready flat scatter",
        "asset_class": "ground_cover",
        "suggested_max_vertices": 320,
    },
    "vine_cluster": {
        "prompt": "low poly tangled vine cluster, corrupted swamp environment, hanging tendrils, game ready prop",
        "asset_class": "shrub",
        "suggested_max_vertices": 560,
    },
    "spore_pod": {
        "prompt": "low poly alien spore pod, corrupted marsh biome, dark fantasy fungal growth, game ready prop",
        "asset_class": "ground_cover",
        "suggested_max_vertices": 280,
    },
    # Alpine winter-only asset
    "snow_patch": {
        "prompt": "low poly snow drift patch, alpine winter mountain biome, crisp white surface decal geometry, game ready scatter",
        "asset_class": "ground_cover",
        "suggested_max_vertices": 160,
    },
    # Ruined village / town assets
    "rubble_pile": {
        "prompt": "low poly stone rubble debris pile, ruined medieval village, broken masonry, game ready environment prop",
        "asset_class": "rock_medium",
        "suggested_max_vertices": 800,
    },
    "broken_pillar": {
        "prompt": "low poly broken stone pillar, ruined ancient settlement, weathered marble, game ready scatter prop",
        "asset_class": "rock_large",
        "suggested_max_vertices": 960,
    },
    "wall_fragment": {
        "prompt": "low poly collapsed stone wall section, ruined village, cracked mortar, game ready environment scatter",
        "asset_class": "rock_medium",
        "suggested_max_vertices": 720,
    },
    "iron_fence": {
        "prompt": "low poly rusted iron fence segment, ruined settlement, dark fantasy environment, game ready prop",
        "asset_class": "deadwood",
        "suggested_max_vertices": 380,
    },
    "collapsed_roof": {
        "prompt": "low poly collapsed timber roof section, ruined medieval building, broken tiles, game ready scatter prop",
        "asset_class": "deadwood",
        "suggested_max_vertices": 640,
    },
    "broken_cart": {
        "prompt": "low poly broken wooden cart, ruined market town, dark fantasy setting, game ready environment prop",
        "asset_class": "deadwood",
        "suggested_max_vertices": 520,
    },
    "barrel": {
        "prompt": "low poly weathered wooden barrel, ruined village environment, dark fantasy setting, game ready prop",
        "asset_class": "rock_medium",
        "suggested_max_vertices": 320,
    },
    "crate": {
        "prompt": "low poly broken wooden crate, ruined settlement, dark fantasy environment, game ready scatter prop",
        "asset_class": "rock_medium",
        "suggested_max_vertices": 240,
    },
    "weed_patch": {
        "prompt": "low poly overgrown weed and thistle patch, ruined urban environment, dark fantasy tone, game ready ground scatter",
        "asset_class": "ground_cover",
        "suggested_max_vertices": 280,
    },
    # Void rift biome assets
    "crystal_shard": {
        "prompt": "low poly corrupted crystal shard, void rift dark fantasy environment, glowing purple facets, game ready scatter prop",
        "asset_class": "rock_medium",
        "suggested_max_vertices": 480,
    },
    "void_tendril": {
        "prompt": "low poly void energy tendril, dark fantasy eldritch environment, writhing dark matter, game ready prop",
        "asset_class": "shrub",
        "suggested_max_vertices": 560,
    },
    "floating_rock": {
        "prompt": "low poly levitating rock fragment, void rift biome, dark fantasy environment, game ready scatter prop",
        "asset_class": "rock_large",
        "suggested_max_vertices": 1200,
    },
    "corruption_pool": {
        "prompt": "low poly corruption energy pool, void rift dark fantasy biome, glowing dark fluid surface, game ready prop",
        "asset_class": "ground_cover",
        "suggested_max_vertices": 320,
    },
    # Cave biome assets
    "stalagmite": {
        "prompt": "low poly cave stalagmite, underground dungeon environment, dripping mineral formation, game ready scatter prop",
        "asset_class": "rock_medium",
        "suggested_max_vertices": 560,
    },
    "bone_pile": {
        "prompt": "low poly scattered bone pile, dark fantasy dungeon or battlefield, old bleached bones, game ready scatter prop",
        "asset_class": "ground_cover",
        "suggested_max_vertices": 360,
    },
    "cobweb": {
        "prompt": "low poly cave cobweb mesh, dark fantasy dungeon environment, thin silk strands, game ready prop",
        "asset_class": "ground_cover",
        "suggested_max_vertices": 180,
    },
    "torch_sconce": {
        "prompt": "low poly wall torch sconce, dark fantasy dungeon, iron bracket, flame particle socket, game ready prop",
        "asset_class": "deadwood",
        "suggested_max_vertices": 280,
    },
    # Shrine / sacred biome assets
    "stone_lantern": {
        "prompt": "low poly ornate stone lantern, dark fantasy ancient shrine, weathered granite, game ready environment prop",
        "asset_class": "rock_medium",
        "suggested_max_vertices": 480,
    },
    "offering_bowl": {
        "prompt": "low poly stone offering bowl, dark fantasy shrine biome, mossy ceremonial vessel, game ready scatter prop",
        "asset_class": "rock_medium",
        "suggested_max_vertices": 240,
    },
    "prayer_flag": {
        "prompt": "low poly worn prayer flag on a pole, dark fantasy sacred site, faded textile, game ready prop",
        "asset_class": "shrub",
        "suggested_max_vertices": 220,
    },
    "moss_patch": {
        "prompt": "low poly thick moss ground patch, ancient shrine biome, lush dark green surface, game ready scatter decal",
        "asset_class": "ground_cover",
        "suggested_max_vertices": 200,
    },
    "cherry_blossom": {
        "prompt": "low poly cherry blossom tree, dark fantasy sacred shrine biome, pale pink petals, game ready scatter prop",
        "asset_class": "tree_boundary",
        "suggested_max_vertices": 1800,
    },
    # Battlefield biome assets
    "broken_weapon": {
        "prompt": "low poly broken sword and spear fragments, dark fantasy battlefield, rusted metal, game ready scatter prop",
        "asset_class": "ground_cover",
        "suggested_max_vertices": 280,
    },
    "shield_fragment": {
        "prompt": "low poly shattered shield fragment, dark fantasy battlefield, wood and iron, game ready scatter prop",
        "asset_class": "ground_cover",
        "suggested_max_vertices": 240,
    },
    "banner_torn": {
        "prompt": "low poly torn battle banner on broken pole, dark fantasy battlefield, frayed cloth, game ready prop",
        "asset_class": "shrub",
        "suggested_max_vertices": 320,
    },
    "crater": {
        "prompt": "low poly explosion crater, dark fantasy battlefield biome, upturned earth and debris, game ready ground prop",
        "asset_class": "rock_medium",
        "suggested_max_vertices": 480,
    },
    # Graveyard biome assets
    "gravestone": {
        "prompt": "low poly weathered gravestone, dark fantasy cemetery, carved stone, aged inscription, game ready scatter prop",
        "asset_class": "rock_medium",
        "suggested_max_vertices": 400,
    },
    "fog_emitter": {
        "prompt": "low poly ground fog emitter anchor stone, dark fantasy graveyard, cracked ritual slab, game ready particle anchor prop",
        "asset_class": "ground_cover",
        "suggested_max_vertices": 120,
    },
}


def _sanitize_scatter_scale_range(raw_value: Any) -> list[float]:
    """Return a finite, ascending, positive 2-item scale range."""
    if isinstance(raw_value, (list, tuple)) and len(raw_value) >= 2:
        lo = float(raw_value[0])
        hi = float(raw_value[1])
    else:
        lo = hi = 1.0
    if not math.isfinite(lo):
        lo = 1.0
    if not math.isfinite(hi):
        hi = lo
    lo = max(lo, 0.05)
    hi = max(hi, 0.05)
    if lo > hi:
        lo, hi = hi, lo
    return [lo, hi]


def _infer_model_asset_class(asset_name: str, rule: dict[str, Any]) -> str:
    explicit = str(rule.get("asset_class", "")).strip()
    if explicit:
        return explicit

    lowered = asset_name.lower()
    if any(token in lowered for token in ("pine", "fir", "spruce", "conifer")):
        return "tree_conifer"
    if any(token in lowered for token in ("tree", "oak", "birch", "blossom")):
        return "tree_boundary"
    if any(token in lowered for token in ("boulder", "cliff", "monolith", "spire")):
        return "rock_large"
    if any(token in lowered for token in ("rock", "stone", "lantern", "gravestone", "crater")):
        return "rock_medium"
    if any(token in lowered for token in ("log", "stump", "branch", "snag", "deadwood")):
        return "deadwood"
    if any(token in lowered for token in ("grass", "moss", "flower", "fern", "reed", "lily", "leaf")):
        return "ground_cover"
    if any(token in lowered for token in ("bush", "shrub", "sapling", "banner", "flag", "vine")):
        return "shrub"
    return "ground_cover"


def _build_model_fallback_prompt_info(
    asset_name: str,
    biome_name: str,
    season: str,
    rule: dict[str, Any],
) -> dict[str, Any]:
    asset_class = _infer_model_asset_class(asset_name, rule)
    readable_name = asset_name.replace("_", " ").replace("-", " ").strip() or "environment prop"
    biome_label = biome_name.replace("_", " ").strip() or "fantasy wilderness"
    season_label = season.replace("_", " ").strip() if season else "summer"
    usage_hint = {
        "tree_conifer": "conifer scatter tree",
        "tree_boundary": "hero scatter tree",
        "rock_large": "large environment rock",
        "rock_medium": "environment stone prop",
        "deadwood": "deadwood scatter prop",
        "ground_cover": "ground cover scatter prop",
        "shrub": "shrub scatter prop",
    }.get(asset_class, "environment prop")
    raw_max_vertices = float(rule.get("suggested_max_vertices", 0) or 0)
    if not math.isfinite(raw_max_vertices):
        raw_max_vertices = 0.0
    max_vertices = max(
        96,
        int(raw_max_vertices),
    )
    if max_vertices <= 96:
        max_vertices = {
            "tree_conifer": 1800,
            "tree_boundary": 1600,
            "rock_large": 900,
            "rock_medium": 480,
            "deadwood": 320,
            "ground_cover": 180,
            "shrub": 260,
        }.get(asset_class, 220)
    return {
        "prompt": (
            f"low poly {readable_name}, {season_label} {biome_label} biome, "
            f"{usage_hint}, game ready environment asset"
        ),
        "asset_class": asset_class,
        "suggested_max_vertices": max_vertices,
        "preferred_source": "external_model_fallback",
    }


def _build_external_model_environment_manifest(
    biome_name: str,
    scatter_rules: list[dict[str, Any]],
    *,
    season: str | None = None,
    scene_bounds: dict[str, float] | None = None,
    terrain_height_scale: float = 20.0,
) -> list[dict[str, Any]]:
    """Build a provider-neutral model asset manifest from biome scatter rules.

    B+ upgrade: full manifest including mesh assets, material assignments,
    LOD specs, environment lighting hints, and scene bounds. Comparable to
    the asset-manifest format used by Far Cry 6 / UE5 World Partition for
    streaming environment dressing.

    Each manifest entry now includes:
        mesh_assets       — ordered list of LOD mesh descriptors (LOD0-LOD3)
        material_slots    — material channel assignments per asset class
        lod_distances     — screen-space transition distances (metres)
        lighting_hints    — environment lighting category and shadow mode
        scene_bounds      — world AABB of the tile/scene (from caller)
        collision_profile — simplified collision shape for the asset class

    Args:
        biome_name: Biome identifier string.
        scatter_rules: List of scatter-rule dicts from the biome preset.
        season: Season override ("summer", "winter", "autumn", "spring").
        scene_bounds: Dict with x_min, y_min, x_max, y_max, z_min, z_max
            for the scene/tile. Embedded verbatim in every manifest entry.
        terrain_height_scale: World-space vertical scale of the terrain (m).
            Used to derive z_min/z_max when scene_bounds is not provided.

    Returns:
        List of manifest dicts, one per scatter rule, each containing full
        LOD/material/lighting spec.
    """
    # LOD distance table by asset class (metres at 1080p, UE5 reference values)
    _LOD_DISTANCES: dict[str, list[float]] = {
        "rock_large":    [0.0, 15.0, 40.0, 80.0],
        "rock_medium":   [0.0, 12.0, 30.0, 60.0],
        "tree_conifer":  [0.0, 20.0, 60.0, 120.0],
        "tree_boundary": [0.0, 25.0, 70.0, 140.0],
        "shrub":         [0.0, 10.0, 25.0, 50.0],
        "ground_cover":  [0.0,  8.0, 18.0, 35.0],
        "deadwood":      [0.0, 12.0, 30.0, 60.0],
    }

    # Material channel assignments per asset class
    _MATERIAL_SLOTS: dict[str, list[str]] = {
        "rock_large":    ["albedo", "normal", "roughness", "ao"],
        "rock_medium":   ["albedo", "normal", "roughness", "ao"],
        "tree_conifer":  ["albedo", "normal", "roughness", "opacity_mask"],
        "tree_boundary": ["albedo", "normal", "roughness", "opacity_mask"],
        "shrub":         ["albedo", "normal", "opacity_mask"],
        "ground_cover":  ["albedo", "opacity_mask"],
        "deadwood":      ["albedo", "normal", "roughness"],
    }

    # Collision profile per asset class
    _COLLISION: dict[str, str] = {
        "rock_large":    "convex_hull",
        "rock_medium":   "box",
        "tree_conifer":  "capsule",
        "tree_boundary": "capsule",
        "shrub":         "none",
        "ground_cover":  "none",
        "deadwood":      "box",
    }

    # Lighting hint per asset class
    _LIGHTING: dict[str, dict[str, str]] = {
        "rock_large":    {"category": "opaque_static",    "shadow": "static"},
        "rock_medium":   {"category": "opaque_static",    "shadow": "static"},
        "tree_conifer":  {"category": "masked_vegetation","shadow": "dynamic"},
        "tree_boundary": {"category": "masked_vegetation","shadow": "dynamic"},
        "shrub":         {"category": "masked_vegetation","shadow": "none"},
        "ground_cover":  {"category": "masked_vegetation","shadow": "none"},
        "deadwood":      {"category": "opaque_static",    "shadow": "static"},
    }

    resolved_season = season or "summer"
    resolved_bounds = scene_bounds or {
        "x_min": 0.0, "y_min": 0.0, "z_min": 0.0,
        "x_max": 256.0, "y_max": 256.0, "z_max": float(terrain_height_scale),
    }

    manifest: list[dict[str, Any]] = []
    for rule in scatter_rules:
        asset_name = str(rule.get("asset", "")).strip()
        if not asset_name:
            continue
        prompt_info = _EXTERNAL_MODEL_PROMPTS.get(asset_name)
        if prompt_info is None:
            prompt_info = _build_model_fallback_prompt_info(
                asset_name,
                biome_name,
                resolved_season,
                rule,
            )

        asset_class = prompt_info["asset_class"]
        max_verts = int(prompt_info["suggested_max_vertices"])
        lod_distances = _LOD_DISTANCES.get(asset_class, [0.0, 15.0, 40.0, 80.0])
        scatter_density = float(rule.get("density", 0.0))
        if not math.isfinite(scatter_density):
            scatter_density = 0.0
        min_distance = float(rule.get("min_distance", 0.0))
        if not math.isfinite(min_distance):
            min_distance = 0.0

        # LOD mesh descriptors: vertex budget halves at each LOD level
        mesh_assets = []
        for lod_idx, lod_dist in enumerate(lod_distances):
            lod_verts = max(8, max_verts // (2 ** lod_idx))
            mesh_assets.append({
                "lod": lod_idx,
                "lod_start_dist_m": lod_dist,
                "suggested_max_vertices": lod_verts,
                "mesh_format": "glb",
            })

        manifest.append({
            "asset": asset_name,
            "asset_class": asset_class,
            "preferred_source": str(prompt_info.get("preferred_source", "external_model")),
            "prompt": prompt_info["prompt"],
            "biome": biome_name,
            "season": resolved_season,
            "suggested_max_vertices": max_verts,
            "scatter_density": max(0.0, scatter_density),
            "min_distance": max(0.0, min_distance),
            "scale_range": _sanitize_scatter_scale_range(rule.get("scale_range", [1.0, 1.0])),
            # B+ additions
            "mesh_assets": mesh_assets,
            "material_slots": _MATERIAL_SLOTS.get(asset_class, ["albedo", "normal"]),
            "lod_distances": lod_distances,
            "lighting_hints": _LIGHTING.get(asset_class, {"category": "opaque_static", "shadow": "static"}),
            "collision_profile": _COLLISION.get(asset_class, "box"),
            "scene_bounds": dict(resolved_bounds),
        })
    return manifest


def _apply_biome_season_profile(
    preset: dict[str, Any],
    season: str | None,
) -> dict[str, Any]:
    """Overlay season-specific biome data when a profile exists."""
    profiles = preset.get("season_profiles")
    if not isinstance(profiles, dict):
        if season:
            preset["season"] = season
        return preset

    resolved_season = season or preset.get("default_season")
    if resolved_season and resolved_season in profiles:
        override = profiles[resolved_season]
        for key, value in override.items():
            preset[key] = value
        preset["season"] = resolved_season
    elif resolved_season:
        preset["season"] = resolved_season
    return preset


def get_vb_biome_preset(
    biome_name: str,
    season: str | None = None,
) -> dict[str, Any] | None:
    """Return a copy of the VB biome preset for *biome_name*, or None.

    The returned dict contains terrain generation parameters (terrain_type,
    resolution, height_scale, erosion, erosion_iterations, seed) and
    scatter_rules for post-terrain vegetation/prop placement.

    Pure logic -- no bpy dependency.
    """
    preset = VB_BIOME_PRESETS.get(biome_name)
    if preset is None:
        return None
    # Return a deep-ish copy so callers can mutate without affecting the preset
    import copy
    resolved = copy.deepcopy(preset)
    resolved = _apply_biome_season_profile(resolved, season)
    if (
        "scatter_rules" in resolved
        and "external_model_asset_manifest" not in resolved
    ):
        resolved["external_model_asset_manifest"] = _build_external_model_environment_manifest(
            biome_name,
            resolved.get("scatter_rules", []),
            season=resolved.get("season") or season,
        )
    return resolved


def _validate_terrain_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize terrain generation parameters.

    Raises ValueError for invalid parameters. Returns normalized dict.
    Pure logic -- no bpy dependency.
    """
    resolution = params.get("resolution", 257)
    terrain_type = params.get("terrain_type", "mountains")
    erosion = params.get("erosion", "none")

    if resolution > _MAX_RESOLUTION:
        raise ValueError(
            f"Resolution {resolution} exceeds maximum {_MAX_RESOLUTION}. "
            f"Use resolution <= {_MAX_RESOLUTION} to avoid memory issues."
        )
    if resolution < 3:
        raise ValueError(
            f"Resolution {resolution} is too small. Minimum is 3."
        )

    if terrain_type not in _VALID_TERRAIN_TYPES:
        raise ValueError(
            f"Unknown terrain_type '{terrain_type}'. "
            f"Valid types: {sorted(_VALID_TERRAIN_TYPES)}"
        )

    if erosion not in _VALID_EROSION_MODES:
        raise ValueError(
            f"Unknown erosion mode '{erosion}'. "
            f"Valid modes: {sorted(_VALID_EROSION_MODES)}"
        )

    return {
        "name": params.get("name", "Terrain"),
        "resolution": resolution,
        "terrain_type": terrain_type,
        "scale": params.get("scale", 100.0),
        "noise_scale": params.get("noise_scale"),
        "height_scale": params.get("height_scale", 20.0),
        "seed": params.get("seed", 0),
        "octaves": params.get("octaves"),
        "persistence": params.get("persistence"),
        "lacunarity": params.get("lacunarity"),
        "erosion": erosion,
        "erosion_iterations": params.get("erosion_iterations", 5000),
    }


def _resolve_terrain_tile_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize tiled terrain generation parameters."""
    tile_x = int(params.get("tile_x", 0))
    tile_y = int(params.get("tile_y", 0))
    cell_size = float(params.get("cell_size", 1.0))
    if cell_size <= 0:
        raise ValueError("cell_size must be positive")

    tile_size_raw = params.get("tile_size")
    resolution_raw = params.get("resolution")
    if tile_size_raw is None and resolution_raw is None:
        tile_size = 256
        resolution = tile_size + 1
    elif tile_size_raw is None:
        if resolution_raw is None:
            raise ValueError("resolution is required when tile_size is omitted")
        resolution = int(resolution_raw)
        tile_size = resolution - 1
    elif resolution_raw is None:
        tile_size = int(tile_size_raw)
        resolution = tile_size + 1
    else:
        tile_size = int(tile_size_raw)
        resolution = int(resolution_raw)
        if resolution != tile_size + 1:
            raise ValueError(
                "resolution must equal tile_size + 1 for tiled terrain generation"
            )

    if tile_size < 1:
        raise ValueError("tile_size must be positive")
    if resolution < 2:
        raise ValueError("resolution must be at least 2")

    terrain_size = float(tile_size * cell_size)
    world_origin_x = float(
        params.get("world_origin_x", tile_x * terrain_size)
    )
    world_origin_y = float(
        params.get("world_origin_y", tile_y * terrain_size)
    )

    name = params.get("name", f"Terrain_{tile_x}_{tile_y}")
    return {
        "name": name,
        "tile_x": tile_x,
        "tile_y": tile_y,
        "tile_size": tile_size,
        "resolution": resolution,
        "cell_size": cell_size,
        "world_origin_x": world_origin_x,
        "world_origin_y": world_origin_y,
        "terrain_size": terrain_size,
        "object_location": (
            world_origin_x + terrain_size / 2.0,
            world_origin_y + terrain_size / 2.0,
            0.0,
        ),
    }


def _export_heightmap_raw(
    heightmap: np.ndarray,
    flip_vertical: bool = True,
    value_range: tuple[float, float] | None = None,
) -> bytes:
    """Convert a heightmap to 16-bit little-endian RAW bytes.

    Pure logic -- no file I/O. Returns raw bytes suitable for writing
    to a .raw file for Unity Terrain import.

    Parameters
    ----------
    heightmap : np.ndarray
        2D array of height values.
    flip_vertical : bool
        Flip rows for Unity coordinate system compatibility.
    value_range : tuple[float, float] | None
        Optional shared export range ``(min, max)`` used to normalize heights.
        When omitted, the input array's local min/max are used.

    Returns
    -------
    bytes
        16-bit unsigned little-endian binary data.
    """
    hmap = np.asarray(heightmap, dtype=np.float64)
    if hmap.ndim != 2:
        raise ValueError(f"heightmap must be a 2D array, got shape {hmap.shape}")
    if hmap.size == 0:
        raise ValueError("heightmap must not be empty")
    if not np.isfinite(hmap).all():
        raise ValueError("heightmap contains non-finite values")
    hmap = hmap.copy()

    # Normalize to [0, 1]
    if value_range is not None:
        hmin, hmax = float(value_range[0]), float(value_range[1])
    else:
        hmin, hmax = float(hmap.min()), float(hmap.max())
    if not np.isfinite((hmin, hmax)).all():
        raise ValueError("value_range must contain finite bounds")
    if hmax - hmin > 1e-10:
        hmap = np.clip((hmap - hmin) / (hmax - hmin), 0.0, 1.0)
    else:
        hmap = np.zeros_like(hmap)

    if flip_vertical:
        hmap = np.flipud(hmap)

    # Convert to uint16 (0-65535)
    hmap_u16 = np.rint(hmap * 65535.0).astype("<u2", copy=False)

    return np.ascontiguousarray(hmap_u16).tobytes()


def _export_splatmap_raw(
    splatmap: np.ndarray,
    flip_vertical: bool = True,
) -> bytes:
    """Convert a 4-channel splatmap to 8-bit RGBA RAW bytes."""
    weights = np.asarray(splatmap, dtype=np.float64).copy()
    if weights.ndim != 3 or weights.shape[2] < 4:
        raise ValueError("splatmap must be a 3D array with at least 4 channels")
    weights = np.nan_to_num(weights, nan=0.0, posinf=0.0, neginf=0.0)

    rgba = np.clip(weights[:, :, :4], 0.0, None)
    totals = rgba.sum(axis=2, keepdims=True)
    safe_totals = np.where(totals > 1e-9, totals, 1.0)
    rgba = np.divide(rgba, safe_totals, out=np.zeros_like(rgba), where=safe_totals > 1e-9)
    empty_pixels = totals[:, :, 0] <= 1e-9
    if np.any(empty_pixels):
        rgba[empty_pixels] = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)

    if flip_vertical:
        rgba = np.flipud(rgba)

    rgba_u8 = np.rint(np.clip(rgba, 0.0, 1.0) * 255.0).astype(np.uint8)
    return rgba_u8.tobytes()


def _export_world_tile_artifacts(
    *,
    export_dir: str | Path,
    tile_name: str,
    heightmap: np.ndarray,
    splatmap: np.ndarray | None = None,
    flip_vertical: bool = True,
    height_range: tuple[float, float] | None = None,
) -> dict[str, str]:
    """Write world-tile RAW artifacts and return their file paths."""
    output_dir = Path(export_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, str] = {}
    heightmap_path = output_dir / f"{tile_name}_heightmap.raw"
    heightmap_path.write_bytes(
        _export_heightmap_raw(
            heightmap,
            flip_vertical=flip_vertical,
            value_range=height_range,
        )
    )
    result["heightmap_path"] = str(heightmap_path)

    if splatmap is not None:
        alphamap_path = output_dir / f"{tile_name}_alphamap.raw"
        alphamap_path.write_bytes(_export_splatmap_raw(splatmap, flip_vertical=flip_vertical))
        result["alphamap_path"] = str(alphamap_path)

    return result


def _write_json_manifest(path: str | Path, payload: dict[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        # T0.5-8b (Y04 v3 §P.8.2): allow_nan=False — loud-at-source per
        # ZZ4-A6 R3 for the environment-handler JSON manifest hop.
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
        newline="\n",
    )
    return str(target)


def _cleanup_written_artifacts(paths: Iterable[Any]) -> None:
    """Best-effort cleanup for partially exported tile/world artifacts."""
    for path in paths:
        if not path:
            continue
        if not isinstance(path, (str, Path)):
            logger.debug("artifact cleanup skipped for non-path value %r", path)
            continue
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            logger.debug("artifact cleanup skipped for %s", path, exc_info=True)


def _resolve_height_range(
    params: dict[str, Any],
    heightmap: np.ndarray,
    *,
    allow_local_fallback: bool = True,
) -> tuple[float, float] | None:
    """Resolve a consistent height range for splatmap normalization.

    Returns ``None`` when the caller did not provide an explicit range
    and ``allow_local_fallback=False``. This is critical for tiled-world
    exports: if every tile were allowed to fall back to its own local
    min/max, each tile would normalize independently and produce visible
    seams in Unity. Tiled exports must either supply an explicit world
    range via ``height_range`` / ``height_range_min/max`` or accept that
    this function will return ``None`` and force the caller to handle
    the missing range deliberately.

    Callers that want the legacy behavior (local min/max fallback) pass
    ``allow_local_fallback=True`` (the default).
    """
    height_range = params.get("height_range")
    if height_range is not None:
        if isinstance(height_range, (list, tuple)) and len(height_range) >= 2:
            return float(height_range[0]), float(height_range[1])
        raise ValueError("height_range must be a 2-item sequence when provided")

    height_range_min = params.get("height_range_min")
    height_range_max = params.get("height_range_max")
    if height_range_min is not None and height_range_max is not None:
        return float(height_range_min), float(height_range_max)

    if not allow_local_fallback:
        return None

    hmap = np.asarray(heightmap, dtype=np.float64)
    if hmap.size == 0:
        return 0.0, 1.0
    return float(hmap.min()), float(hmap.max())


def _resolve_export_height_range(
    params: dict[str, Any],
    heightmap: np.ndarray,
) -> tuple[float, float] | None:
    """Resolve an optional shared export range for heightmap RAW output.

    Tiled worlds demand a SHARED range across all tiles so the exported
    16-bit RAW heightmaps line up at Unity's tile boundaries. If the
    caller set ``tiled_world`` / ``use_global_height_range`` without an
    explicit range, we must NOT fall back to this tile's local min/max
    — that is the root cause of the per-tile seam bug flagged by the
    Gemini + GPT-5.4 consensus review.
    """
    if params.get("tiled_world") or params.get("use_global_height_range"):
        resolved = _resolve_height_range(
            params, heightmap, allow_local_fallback=False
        )
        if resolved is None:
            raise ValueError(
                "tiled_world / use_global_height_range requires an explicit "
                "'height_range' (or 'height_range_min' + 'height_range_max') "
                "parameter. Falling back to per-tile min/max would normalize "
                "each tile independently and create visible seams in Unity."
            )
        return resolved

    # Non-tiled export path — only return an explicit range when one is
    # present; otherwise the caller may skip height-range metadata.
    return _resolve_height_range(params, heightmap, allow_local_fallback=False)


def _terrain_grid_to_world_xy(
    row: int,
    col: int,
    *,
    rows: int,
    cols: int,
    terrain_size: float | None = None,
    terrain_width: float | None = None,
    terrain_height: float | None = None,
    terrain_origin_x: float,
    terrain_origin_y: float,
) -> tuple[float, float]:
    """Convert a terrain grid cell to a world-space XY position.

    ``terrain_origin_*`` is the terrain object's world-space center.
    """
    if rows < 2 or cols < 2:
        return terrain_origin_x, terrain_origin_y

    width = float(terrain_width if terrain_width is not None else terrain_size if terrain_size is not None else 0.0)
    height = float(terrain_height if terrain_height is not None else terrain_size if terrain_size is not None else 0.0)
    width = max(width, 1e-9)
    height = max(height, 1e-9)

    x = terrain_origin_x + (col / max(cols - 1, 1)) * width - width * 0.5
    y = terrain_origin_y + (row / max(rows - 1, 1)) * height - height * 0.5
    return x, y


def _resolve_water_path_points(
    *,
    path_points_raw: Any,
    terrain_origin_x: float,
    terrain_origin_y: float,
    fallback_depth: float,
    water_level: float,
) -> list[tuple[float, float, float]]:
    """Resolve explicit or fallback water spline points in world space.

    Every returned point is a guaranteed 3-tuple (x, y, z). Explicit
    ``path_points_raw`` entries may be supplied as 2D (x, y) pairs —
    in which case Z is filled from ``water_level`` — or 3D (x, y, z)
    triples. Any other arity raises ``ValueError`` so callers fail fast
    rather than sending half-initialized tuples into downstream mesh
    generation (Gemini consensus finding).
    """
    if path_points_raw is None:
        path_points_seq: list[Any] = []
    else:
        try:
            path_points_seq = list(path_points_raw)
        except TypeError as exc:
            raise ValueError(
                f"path_points_raw must be an iterable of 2D/3D points, got {type(path_points_raw).__name__}"
            ) from exc

    if path_points_seq:
        if len(path_points_seq) < 2:
            raise ValueError(
                "path_points_raw must contain at least 2 points when provided; "
                f"got {len(path_points_seq)}"
            )
        result: list[tuple[float, float, float]] = []
        for i, pt in enumerate(path_points_seq):
            try:
                pt_seq = list(pt)
            except TypeError as exc:
                raise ValueError(
                    f"path_points[{i}] is not iterable: {pt!r}"
                ) from exc
            if len(pt_seq) == 2:
                x_val, y_val = float(pt_seq[0]), float(pt_seq[1])
                z_val = float(water_level)
            elif len(pt_seq) >= 3:
                x_val = float(pt_seq[0])
                y_val = float(pt_seq[1])
                z_val = float(pt_seq[2])
            else:
                raise ValueError(
                    f"path_points[{i}] must have 2 (x,y) or 3 (x,y,z) "
                    f"components, got {len(pt_seq)}: {pt!r}"
                )
            if not (
                math.isfinite(x_val)
                and math.isfinite(y_val)
                and math.isfinite(z_val)
            ):
                raise ValueError(
                    f"path_points[{i}] contains non-finite coordinates: {pt!r}"
                )
            result.append((x_val, y_val, z_val))
        return result

    return [
        (terrain_origin_x, terrain_origin_y - fallback_depth / 2.0, water_level),
        (terrain_origin_x, terrain_origin_y + fallback_depth / 2.0, water_level),
    ]


def _smooth_river_path_points(
    path_points: list[tuple[float, float, float]],
    *,
    smoothing_passes: int = 3,
    min_spacing_world: float | None = None,
    enforce_monotonic_z: bool = False,
) -> list[tuple[float, float, float]]:
    """Resample a river centerline with spline interpolation."""
    canonical_points: list[tuple[float, float, float]] = []
    for x, y, z in path_points:
        px = float(x)
        py = float(y)
        pz = float(z)
        if not (math.isfinite(px) and math.isfinite(py) and math.isfinite(pz)):
            continue
        if canonical_points:
            prev_x, prev_y, prev_z = canonical_points[-1]
            if abs(px - prev_x) <= 1e-9 and abs(py - prev_y) <= 1e-9:
                canonical_points[-1] = (prev_x, prev_y, min(prev_z, pz))
                continue
        canonical_points.append((px, py, pz))

    path_points = canonical_points
    if len(path_points) < 3:
        return [(float(x), float(y), float(z)) for x, y, z in path_points]

    points = np.asarray(path_points, dtype=np.float64)
    raw_xy = points[:, :2]
    raw_segment_lengths = np.linalg.norm(np.diff(raw_xy, axis=0), axis=1)
    total_length = float(raw_segment_lengths.sum())
    if total_length <= 1e-9:
        return [(float(x), float(y), float(z)) for x, y, z in path_points]

    if min_spacing_world is None:
        positive_segments = raw_segment_lengths[raw_segment_lengths > 1e-9]
        if positive_segments.size:
            inferred_spacing = float(np.median(positive_segments))
        else:
            inferred_spacing = total_length / max(len(path_points) - 1, 1)
        min_spacing_world = max(inferred_spacing * 0.42, 0.35)
    else:
        min_spacing_world = max(float(min_spacing_world), 0.35)

    padded = np.vstack((points[0], points, points[-1]))
    segment_count = len(points) - 1
    samples_per_segment = max(6, min(20, int(max(total_length / max(segment_count, 1), min_spacing_world) / max(min_spacing_world, 1e-6)) + smoothing_passes * 2))

    dense: list[np.ndarray] = [points[0]]
    for segment_index in range(1, len(padded) - 2):
        p0 = padded[segment_index - 1]
        p1 = padded[segment_index]
        p2 = padded[segment_index + 1]
        p3 = padded[segment_index + 2]
        for step in range(1, samples_per_segment + 1):
            t = step / samples_per_segment
            t2 = t * t
            t3 = t2 * t
            sample = 0.5 * (
                (2.0 * p1)
                + (-p0 + p2) * t
                + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
                + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
            )
            dense.append(sample)

    filtered: list[np.ndarray] = [dense[0]]
    accumulated = 0.0
    for sample in dense[1:]:
        segment_len = float(np.linalg.norm(sample[:2] - filtered[-1][:2]))
        accumulated += segment_len
        if accumulated + 1e-9 < float(min_spacing_world):
            continue
        filtered.append(sample)
        accumulated = 0.0
    if np.linalg.norm(filtered[-1][:2] - points[-1][:2]) > 1e-6:
        filtered.append(points[-1])

    max_sample_count = len(path_points)
    if len(filtered) > max_sample_count:
        # Select from the dense spline array with a half-step offset so we
        # land on interior spline-interpolated positions rather than the
        # original control points (which sit at exact segment boundaries).
        n_dense = len(dense)
        half_step = (n_dense - 1) / max(max_sample_count * 2, 1)
        raw_indices = np.linspace(half_step, n_dense - 1 - half_step, max_sample_count - 2)
        interior = [dense[int(round(idx))] for idx in raw_indices]
        filtered = [dense[0]] + interior + [points[-1]]

    smoothed = np.asarray(filtered, dtype=np.float64)
    if enforce_monotonic_z and len(smoothed) > 1:
        min_drop = max(total_length * 1e-5, 1e-4)
        max_drop = max(0.45, min(float(min_spacing_world) * 0.75, 1.2))
        for idx in range(1, len(smoothed)):
            if smoothed[idx, 2] >= smoothed[idx - 1, 2]:
                smoothed[idx, 2] = smoothed[idx - 1, 2] - min_drop
            elif smoothed[idx, 2] < smoothed[idx - 1, 2] - max_drop:
                smoothed[idx, 2] = smoothed[idx - 1, 2] - max_drop

    deduped: list[tuple[float, float, float]] = []
    for sample in smoothed:
        point = (float(sample[0]), float(sample[1]), float(sample[2]))
        if deduped:
            prev_x, prev_y, prev_z = deduped[-1]
            if abs(point[0] - prev_x) <= 1e-9 and abs(point[1] - prev_y) <= 1e-9:
                deduped[-1] = (prev_x, prev_y, min(prev_z, point[2]))
                continue
        deduped.append(point)

    return deduped


def _estimate_tile_height_range(
    terrain_type: str,
    *,
    octaves: int | None = None,
    persistence: float | None = None,
) -> tuple[float, float]:
    """Estimate a deterministic height range for standalone tile exports."""
    preset = TERRAIN_PRESETS.get(terrain_type, TERRAIN_PRESETS["mountains"])
    octaves = int(octaves if octaves is not None else preset["octaves"])
    persistence = float(
        persistence if persistence is not None else preset["persistence"]
    )
    amplitude = _theoretical_max_amplitude(octaves, persistence)
    amplitude *= float(preset.get("amplitude_scale", 1.0))
    post = str(preset.get("post_process", "none"))

    if post in ("power", "step"):
        return (0.0, 1.0)
    if post == "crater":
        crater_depth = float(preset.get("crater_depth", 0.4))
        return (-0.3 * amplitude - crater_depth, 0.7 + 0.3 * amplitude)
    if post == "canyon":
        ridge_strength = float(preset.get("ridge_strength", 0.7))
        return (-amplitude * (1.0 - ridge_strength), 1.0)
    return (-amplitude, amplitude)


def _create_terrain_mesh_from_heightmap(
    *,
    name: str,
    heightmap: np.ndarray,
    terrain_size: float,
    height_scale: float,
    seed: int,
    terrain_type: str,
    object_location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    cliff_overlays_enabled: bool = True,
    cliff_threshold_deg: float = 60.0,
    controller_cliff_placements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a terrain mesh object from a heightmap and optional cliff overlays."""
    rows, cols = heightmap.shape

    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()

    # Create UV layer BEFORE create_grid so calc_uvs has somewhere to write.
    # Without this, calc_uvs=True silently produces nothing (verified bug).
    _ = bm.loops.layers.uv.new("UVMap")

    bmesh.ops.create_grid(
        bm,
        x_segments=cols - 1,
        y_segments=rows - 1,
        size=terrain_size / 2.0,
        calc_uvs=True,
    )

    bm.verts.ensure_lookup_table()

    # Transfer grid topology to mesh first, then batch-write Z via foreach_set.
    bm.to_mesh(mesh)
    vertex_count = len(bm.verts)
    bm.free()

    # Batch bilinear interpolation: read all positions at once, compute Z numpy.
    n_verts = len(mesh.vertices)
    co_flat = np.empty(n_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co_flat)
    co = co_flat.reshape(n_verts, 3)
    u_arr = (co[:, 0] + terrain_size / 2.0) / terrain_size
    v_arr = (co[:, 1] + terrain_size / 2.0) / terrain_size
    col_f = u_arr * (cols - 1)
    row_f = v_arr * (rows - 1)
    c0 = np.clip(col_f.astype(np.int32), 0, cols - 2)
    r0 = np.clip(row_f.astype(np.int32), 0, rows - 2)
    c1 = c0 + 1
    r1 = r0 + 1
    cf = (col_f - c0).astype(np.float32)
    rf = (row_f - r0).astype(np.float32)
    hmap = np.asarray(heightmap, dtype=np.float32)
    h_interp = (
        hmap[r0, c0] * (1.0 - cf) * (1.0 - rf)
        + hmap[r0, c1] * cf * (1.0 - rf)
        + hmap[r1, c0] * (1.0 - cf) * rf
        + hmap[r1, c1] * cf * rf
    )
    co_flat[2::3] = h_interp * float(height_scale)
    mesh.vertices.foreach_set("co", co_flat)

    if hasattr(mesh, "polygons"):
        for poly in mesh.polygons:
            poly.use_smooth = True

    obj = bpy.data.objects.new(name, mesh)
    obj.location = object_location
    bpy.context.collection.objects.link(obj)

    cliff_placements: list[dict[str, Any]] = []
    if cliff_overlays_enabled:
        from ._terrain_depth import detect_cliff_edges, generate_cliff_face_mesh

        if controller_cliff_placements is not None:
            cliff_placements = list(controller_cliff_placements)
        else:
            cliff_placements = detect_cliff_edges(
                heightmap,
                slope_threshold_deg=cliff_threshold_deg,
                min_cluster_size=4,
                terrain_size=terrain_size,
                height_scale=height_scale,
            )
        for i, cp in enumerate(cliff_placements):
            cliff_mesh_spec = generate_cliff_face_mesh(
                width=cp["width"],
                height=cp["height"],
                seed=seed + i + 1000,
            )
            cliff_mesh = bpy.data.meshes.new(f"{name}_Cliff_{i}")
            cliff_bm = bmesh.new()
            for vert_data in cliff_mesh_spec["vertices"]:
                cliff_bm.verts.new(vert_data)
            cliff_bm.verts.ensure_lookup_table()
            for face_data in cliff_mesh_spec["faces"]:
                try:
                    cliff_bm.faces.new([cliff_bm.verts[vi] for vi in face_data])
                except (ValueError, IndexError):
                    pass
            cliff_bm.to_mesh(cliff_mesh)
            cliff_bm.free()

            cliff_obj = bpy.data.objects.new(f"{name}_Cliff_{i}", cliff_mesh)
            bpy.context.collection.objects.link(cliff_obj)
            # --- Parent first, THEN set transform ---
            # The legacy order (location → parent) silently offset cliffs
            # on non-origin tiles: Blender's Python parent assignment
            # does not auto-adjust matrix_parent_inverse, so a world-space
            # location set before parenting was reinterpreted as local
            # after parenting and the visual world position drifted by
            # whatever the parent's world offset was. The fix is to
            # establish the parent relationship first with
            # ``matrix_parent_inverse`` forced to identity, then write the
            # transform — which is now unambiguously terrain-local. The
            # positions returned by ``detect_cliff_edges`` are already
            # in terrain-local coordinates (grid-center mapped to
            # [-tw/2, +tw/2]) and Z is already multiplied by
            # ``height_scale`` inside ``detect_cliff_edges`` — no further
            # scaling here.
            cliff_obj.parent = obj
            mpi = getattr(cliff_obj, "matrix_parent_inverse", None)
            if mpi is not None and hasattr(mpi, "identity"):
                mpi.identity()
            cliff_obj.location = (
                cp["position"][0],
                cp["position"][1],
                cp["position"][2],
            )
            cliff_obj.rotation_euler = tuple(cp["rotation"])

    return {
        "object": obj,
        "name": obj.name,
        "vertex_count": vertex_count,
        "cliff_overlays": len(cliff_placements),
        "hero_cliff_overlays": sum(
            1 for cp in cliff_placements
            if str(cp.get("tier", "secondary")) == "hero"
        ),
        "terrain_size": terrain_size,
        "object_location": tuple(obj.location),
        "terrain_type": terrain_type,
    }


def _cliff_structures_to_overlay_placements(
    heightmap: np.ndarray,
    cliffs: list[Any],
    *,
    terrain_size: float | tuple[float, float],
    height_scale: float,
) -> list[dict[str, Any]]:
    """Convert Bundle B cliff structures into overlay placements."""
    heightmap = np.asarray(heightmap, dtype=np.float64)
    rows, cols = heightmap.shape
    if rows == 0 or cols == 0:
        return []

    if isinstance(terrain_size, (tuple, list)):
        if len(terrain_size) < 2:
            raise ValueError("terrain_size tuple must contain width and height")
        terrain_width = max(float(terrain_size[0]), 1e-9)
        terrain_height = max(float(terrain_size[1]), 1e-9)
    else:
        terrain_width = terrain_height = max(float(terrain_size), 1e-9)

    row_spacing = terrain_height / max(rows - 1, 1)
    col_spacing = terrain_width / max(cols - 1, 1)
    grad_y, grad_x = np.gradient(heightmap, row_spacing, col_spacing)

    placements: list[dict[str, Any]] = []
    for cliff in cliffs:
        face_mask = np.asarray(getattr(cliff, "face_mask", None), dtype=bool)
        if face_mask.size == 0 or not face_mask.any():
            continue

        cells = np.argwhere(face_mask)
        r_min, c_min = cells.min(axis=0)
        r_max, c_max = cells.max(axis=0)
        r_center = (r_min + r_max) / 2.0
        c_center = (c_min + c_max) / 2.0

        wx = (c_center / max(cols - 1, 1) - 0.5) * terrain_width
        wy = (r_center / max(rows - 1, 1) - 0.5) * terrain_height
        ri = int(np.clip(r_center, 0, rows - 1))
        ci = int(np.clip(c_center, 0, cols - 1))
        wz = float(heightmap[ri, ci]) * float(height_scale)

        face_angle = math.atan2(float(grad_y[ri, ci]), float(grad_x[ri, ci]))
        width_x = (c_max - c_min + 1) * col_spacing
        width_y = (r_max - r_min + 1) * row_spacing
        width = max(width_x, width_y, 2.0)
        raw_height_range = float(
            heightmap[cells[:, 0], cells[:, 1]].max()
            - heightmap[cells[:, 0], cells[:, 1]].min()
        )
        cliff_height = max(raw_height_range * float(height_scale), 2.0)

        placements.append(
            {
                "cliff_id": str(getattr(cliff, "cliff_id", f"cliff_{len(placements):02d}")),
                "tier": str(getattr(cliff, "tier", "secondary")),
                "position": [wx, wy, wz],
                "rotation": [0.0, 0.0, face_angle],
                "width": width,
                "height": cliff_height,
                "cell_count": int(getattr(cliff, "cell_count", int(cells.shape[0]))),
            }
        )

    return placements


# ---------------------------------------------------------------------------
# Handler: generate_terrain
# ---------------------------------------------------------------------------

def handle_generate_terrain(params: dict[str, Any]) -> dict[str, Any]:
    """Generate a terrain mesh from noise heightmap with optional erosion.

    Params:
        name (str, default "Terrain"): Object name.
        resolution (int, default 257): Grid resolution (vertices per side).
        terrain_type (str, default "mountains"): One of 10 terrain presets,
            or a VeilBreakers biome name (e.g. "thornwood_forest").
            When a biome name is given, its preset parameters are applied
            as defaults, overrideable by explicit params.
        scale (float, default 100.0): Noise sampling scale.
        height_scale (float, default 20.0): Vertical scale multiplier.
        seed (int, default 0): Random seed.
        octaves, persistence, lacunarity: Override preset values.
        erosion (str, default "none"): none|hydraulic|thermal|both.
        erosion_iterations (int, default 5000): Erosion iteration count.

    Returns dict with: name, vertex_count, terrain_type, resolution,
        height_scale, erosion_applied, and optionally biome_preset
        and scatter_rules when a VB biome preset was used.
    """
    # Check if terrain_type is a VB biome preset name
    requested_biome_name = str(params.get("terrain_type", ""))
    biome_preset = get_vb_biome_preset(
        requested_biome_name,
        season=params.get("season"),
    )
    if biome_preset is not None:
        # Build effective params: preset defaults, overridden by explicit params
        effective: dict[str, Any] = {}
        effective["terrain_type"] = biome_preset["terrain_type"]
        effective["resolution"] = biome_preset["resolution"]
        effective["height_scale"] = biome_preset["height_scale"]
        if biome_preset.get("erosion"):
            effective["erosion"] = "hydraulic"
            effective["erosion_iterations"] = biome_preset.get("erosion_iterations", 5000)
        else:
            effective["erosion"] = "none"
        # Explicit params override preset defaults (except terrain_type which
        # was the biome name -- we already resolved the real terrain_type).
        # Note: preset seed is intentionally NOT applied -- caller's seed
        # (or downstream default) always takes precedence.
        for key in ("name", "resolution", "height_scale", "scale", "seed",
                     "octaves", "persistence", "lacunarity", "erosion",
                     "erosion_iterations"):
            if key in params:
                effective[key] = params[key]
        # Keep the original terrain_type param out so validation uses the
        # resolved terrain_type from the biome preset
        params = effective

    use_controller = bool(params.get("use_controller", True))

    logger.info("Generating terrain (type=%s, use_controller=%s)",
                params.get("terrain_type", "mountains"), use_controller)
    validated = _validate_terrain_params(params)

    name = validated["name"]
    resolution = validated["resolution"]
    terrain_type = validated["terrain_type"]
    scale = validated["scale"]
    noise_scale = _resolve_noise_sampling_scale(
        terrain_size=scale,
        terrain_type=terrain_type,
        explicit_noise_scale=validated["noise_scale"],
    )
    height_scale = validated["height_scale"]
    seed = validated["seed"]
    erosion = validated["erosion"]
    erosion_iters = validated["erosion_iterations"]

    _enforce_generate_terrain_protocol(
        params,
        resolution=resolution,
        scale=scale,
        seed=seed,
    )

    # --- Controller path: controller state is the terrain source of truth ---
    if use_controller:
        object_location = _coerce_point3(
            params.get("object_location"),
            (0.0, 0.0, 0.0),
        )
        scene_read_payload = params.get("scene_read")
        if scene_read_payload is not None and not isinstance(scene_read_payload, dict):
            scene_read_payload = None
        cave_candidates = []
        if isinstance(scene_read_payload, dict):
            for entry in scene_read_payload.get("cave_candidates", ()) or ():
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    cave_candidates.append(
                        (
                            float(entry[0]),
                            float(entry[1]),
                            float(entry[2]) if len(entry) >= 3 else 0.0,
                        )
                    )
        quality_profile_name = str(params.get("quality_profile", "aaa_open_world"))
        is_preview = quality_profile_name in ("preview", "mobile", "low")
        composition_hints = dict(params.get("composition_hints") or {})
        controller_apply_caves = bool(params.get("controller_apply_caves", False))
        if controller_apply_caves:
            composition_hints["controller_apply_caves"] = True
        if params.get("skip_scatter", False):
            composition_hints["skip_scatter"] = True
        if params.get("waterfalls", True) is False:
            composition_hints["waterfalls"] = False

        controller_params = {
            "tile_size": max(resolution - 1, 1),
            "cell_size": float(scale) / max(resolution - 1, 1),
            "seed": seed,
            "terrain_type": terrain_type,
            "scale": noise_scale,
            "world_origin_x": float(object_location[0]) - float(scale) * 0.5,
            "world_origin_y": float(object_location[1]) - float(scale) * 0.5,
            "composition_hints": composition_hints,
            "quality_profile": quality_profile_name,
            "bulk_edit": True,
            "cells_affected": resolution * resolution,
            "enforce_protocol": params.get("enforce_protocol", True),
            "out_of_view_ok": bool(params.get("out_of_view_ok", False)),
        }
        if params.get("viewport_vantage") is not None:
            controller_params["viewport_vantage"] = params.get("viewport_vantage")

        needs_scene_read = (
            erosion in ("hydraulic", "thermal", "both")
            or bool(cave_candidates)
            or not is_preview
        )
        if needs_scene_read:
            controller_scene_read = dict(scene_read_payload or {})
            controller_scene_read.setdefault("timestamp", 0.0)
            controller_scene_read.setdefault("reviewer", "compose_map")
            if cave_candidates:
                controller_scene_read["cave_candidates"] = cave_candidates
            if not is_preview:
                controller_scene_read.setdefault(
                    "success_criteria",
                    ("production_content_pipeline",),
                )
            controller_params["scene_read"] = controller_scene_read
        if erosion in ("hydraulic", "thermal", "both"):
            controller_params["erosion_profile"] = (
                composition_hints.get("erosion_profile")
                or composition_hints.get("climate")
                or ("arid" if erosion == "thermal" else "temperate")
            )
        if params.get("pipeline") is not None:
            controller_params["pipeline"] = list(params.get("pipeline") or [])

        controller_run = _execute_terrain_pipeline(controller_params)
        if controller_run.get("ok") is False:
            raise RuntimeError(
                "TerrainPassController protocol gate rejected env_generate_terrain: "
                + str(controller_run.get("message") or controller_run.get("error"))
            )
        cave_pipeline_fallback = False
        controller_state = controller_run["state"]
        controller_results = controller_run["results"]
        failed_passes = [
            result.pass_name
            for result in controller_results
            if result.status == "failed"
        ]
        if failed_passes:
            raise RuntimeError(
                "TerrainPassController failed before mesh generation"
                + f" (failed passes: {', '.join(failed_passes)})"
            )

        heightmap = np.asarray(controller_state.mask_stack.height, dtype=np.float64).copy()
        erosion_applied = erosion in ("hydraulic", "thermal", "both")

        # Apply flatten zones for building foundations (MESH-05)
        flatten_zones = params.get("flatten_zones", None)
        if flatten_zones:
            from .terrain_advanced import flatten_multiple_zones
            heightmap = flatten_multiple_zones(heightmap, flatten_zones)
            controller_state.mask_stack.set("height", heightmap, "flatten_multiple_zones")
            controller_state.mask_stack.height_min_m = float(heightmap.min()) if heightmap.size else 0.0
            controller_state.mask_stack.height_max_m = float(heightmap.max()) if heightmap.size else 0.0

        heightmap = _enhance_heightmap_relief(heightmap, terrain_type=terrain_type)
        heightmap = _temper_heightmap_spikes(heightmap, terrain_type=terrain_type)

        terrain_size = scale
        controller_cliff_placements: list[dict[str, Any]] | None = None
        if params.get("cliff_overlays", True) and controller_state.mask_stack.cliff_candidate is not None:
            from .terrain_cliffs import carve_cliff_system

            controller_cliffs = carve_cliff_system(
                controller_state,
                region=None,
                candidate_mask=np.asarray(controller_state.mask_stack.cliff_candidate, dtype=bool),
            )
            controller_cliff_placements = _cliff_structures_to_overlay_placements(
                heightmap,
                controller_cliffs,
                terrain_size=terrain_size,
                height_scale=height_scale,
            )
        terrain_result = _create_terrain_mesh_from_heightmap(
            name=name,
            heightmap=heightmap,
            terrain_size=terrain_size,
            height_scale=height_scale,
            seed=seed,
            terrain_type=terrain_type,
            object_location=object_location,
            cliff_overlays_enabled=params.get("cliff_overlays", True),
            cliff_threshold_deg=params.get("cliff_threshold_deg", 60.0),
            controller_cliff_placements=controller_cliff_placements,
        )

        result = {
            "name": terrain_result["name"],
            "vertex_count": terrain_result["vertex_count"],
            "terrain_type": terrain_type,
            "resolution": resolution,
            "height_scale": height_scale,
            "noise_scale": noise_scale,
            "erosion_applied": erosion_applied,
            "cliff_overlays": terrain_result["cliff_overlays"],
            "hero_cliff_overlays": terrain_result.get("hero_cliff_overlays", 0),
            "flatten_zones_applied": len(flatten_zones) if flatten_zones else 0,
            "has_moisture_map": False,
            "controller_used": True,
            "controller_ok": not failed_passes,
            "controller_passes": [r.pass_name for r in controller_results],
            "heightmap": heightmap.tolist(),
            "tile_size": max(resolution - 1, 1),
            "cell_size": float(scale) / max(resolution - 1, 1),
            "world_origin_x": float(object_location[0]) - float(scale) * 0.5,
            "world_origin_y": float(object_location[1]) - float(scale) * 0.5,
            "water_network_present": getattr(controller_state, "water_network", None) is not None,
        }
        if cave_candidates:
            result["cave_candidates"] = [list(c) for c in cave_candidates]
            result["cave_mask_present"] = bool(
                controller_state.mask_stack.get("cave_candidate") is not None
            )
            result["cave_pipeline_fallback"] = cave_pipeline_fallback
            result["cave_pipeline_deferred"] = not controller_apply_caves
        if biome_preset is not None:
            result["biome_preset"] = requested_biome_name
            result["scatter_rules"] = biome_preset.get("scatter_rules", [])
        return result

    # --- Legacy path (default): inline heightmap generation + erosion ---
    # Auto-scale erosion: minimum 150K droplets for AAA-quality river channels
    # and natural-looking drainage (Skyrim/Valhalla uses 150K+ for visible features)
    if erosion in ("hydraulic", "both") and erosion_iters < 150000:
        erosion_iters = max(150000, resolution * resolution // 2)

    # Domain warp params (organic terrain features)
    warp_strength = params.get("warp_strength", 0.4)  # default organic
    warp_scale = params.get("warp_scale", 0.5)

    # Generate heightmap
    heightmap = generate_heightmap(
        width=resolution,
        height=resolution,
        scale=noise_scale,
        octaves=validated["octaves"],
        persistence=validated["persistence"],
        lacunarity=validated["lacunarity"],
        seed=seed,
        terrain_type=terrain_type,
        warp_strength=warp_strength,
        warp_scale=warp_scale,
    )

    # Apply erosion
    erosion_applied = False
    if erosion in ("hydraulic", "both") or erosion in ("thermal", "both"):
        erosion_result = erode_world_heightmap(
            heightmap,
            hydraulic_iterations=erosion_iters if erosion in ("hydraulic", "both") else 0,
            thermal_iterations=max(erosion_iters // 50, 5) if erosion in ("thermal", "both") else 0,
            seed=seed,
        )
        heightmap = erosion_result["heightmap"]
        erosion_applied = True

    # Apply flatten zones for building foundations (MESH-05)
    flatten_zones = params.get("flatten_zones", None)
    if flatten_zones:
        from .terrain_advanced import flatten_multiple_zones
        heightmap = flatten_multiple_zones(heightmap, flatten_zones)

    heightmap = _enhance_heightmap_relief(heightmap, terrain_type=terrain_type)
    heightmap = _temper_heightmap_spikes(heightmap, terrain_type=terrain_type)

    # Compute moisture map from flow accumulation (for splatmap painting)
    moisture_map = None
    if erosion_applied:
        from .terrain_advanced import compute_flow_map
        flow_result = compute_flow_map(heightmap)
        flow_acc = np.asarray(flow_result["flow_accumulation"], dtype=np.float64)
        # Normalize flow accumulation to [0, 1] using log scale
        log_flow = np.nan_to_num(np.log1p(np.maximum(flow_acc, 0.0)), nan=0.0, posinf=GLOBAL_LOG_FLOW_NORM, neginf=0.0)
        moisture_map = np.clip(log_flow / GLOBAL_LOG_FLOW_NORM, 0.0, 1.0)

    terrain_size = scale
    # Fix L2: respect caller-supplied object_location instead of hardcoding origin
    object_location = _coerce_point3(
        params.get("object_location"),
        (0.0, 0.0, 0.0),
    )
    terrain_result = _create_terrain_mesh_from_heightmap(
        name=name,
        heightmap=heightmap,
        terrain_size=terrain_size,
        height_scale=height_scale,
        seed=seed,
        terrain_type=terrain_type,
        object_location=object_location,
        cliff_overlays_enabled=params.get("cliff_overlays", True),
        cliff_threshold_deg=params.get("cliff_threshold_deg", 60.0),
    )

    result = {
        "name": terrain_result["name"],
        "vertex_count": terrain_result["vertex_count"],
        "terrain_type": terrain_type,
        "resolution": resolution,
        "height_scale": height_scale,
        "noise_scale": noise_scale,
        "erosion_applied": erosion_applied,
        "cliff_overlays": terrain_result["cliff_overlays"],
        "flatten_zones_applied": len(flatten_zones) if flatten_zones else 0,
        "has_moisture_map": moisture_map is not None,
    }
    if biome_preset is not None:
        result["biome_preset"] = requested_biome_name
        result["scatter_rules"] = biome_preset.get("scatter_rules", [])
    return result


# ---------------------------------------------------------------------------
# Handler: generate_terrain_tile
# ---------------------------------------------------------------------------

def handle_generate_terrain_tile(params: dict[str, Any]) -> dict[str, Any]:
    """Generate a single world-space terrain tile."""
    logger.info("Generating tiled terrain")

    resolved = _resolve_terrain_tile_params(params)
    name = resolved["name"]
    tile_x = resolved["tile_x"]
    tile_y = resolved["tile_y"]
    tile_size = resolved["tile_size"]
    resolution = resolved["resolution"]
    cell_size = resolved["cell_size"]
    world_origin_x = resolved["world_origin_x"]
    world_origin_y = resolved["world_origin_y"]
    terrain_size = resolved["terrain_size"]
    object_location = resolved["object_location"]

    terrain_type = params.get("terrain_type", "mountains")
    scale = float(params.get("scale", 100.0))
    height_scale = float(params.get("height_scale", 20.0))
    seed = int(params.get("seed", 0))
    octaves = params.get("octaves")
    persistence = params.get("persistence")
    lacunarity = params.get("lacunarity")
    erosion = params.get("erosion", "none")
    erosion_iters = int(params.get("erosion_iterations", 5000))
    warp_strength = float(params.get("warp_strength", 0.4))
    warp_scale = float(params.get("warp_scale", 0.5))
    world_center_x = params.get("world_center_x")
    world_center_y = params.get("world_center_y")
    cliff_overlays_enabled = bool(params.get("cliff_overlays", True))
    cliff_threshold = float(params.get("cliff_threshold_deg", 60.0))
    erosion_margin = max(0, int(params.get("erosion_margin", 0)))
    biome_name = params.get("biome_name", params.get("terrain_type", "thornwood_forest"))
    export_splatmaps = bool(params.get("export_splatmaps", True))
    export_root = Path(
        params.get("export_dir")
        or params.get("output_dir")
        or Path("Temp") / "VB_TerrainExports" / name
    )
    world_id = str(params.get("world_id", params.get("world_name", "unknown")))
    batch_id = params.get("batch_id")

    world_width = tile_size + 1 + (2 * erosion_margin)
    world_height = tile_size + 1 + (2 * erosion_margin)
    padded_origin_x = world_origin_x - erosion_margin * cell_size
    padded_origin_y = world_origin_y - erosion_margin * cell_size

    heightmap = generate_world_heightmap(
        width=world_width,
        height=world_height,
        scale=scale,
        world_origin_x=padded_origin_x,
        world_origin_y=padded_origin_y,
        cell_size=cell_size,
        seed=seed,
        terrain_type=terrain_type,
        normalize=False,
        warp_strength=warp_strength,
        warp_scale=warp_scale,
        octaves=octaves,
        persistence=persistence,
        lacunarity=lacunarity,
        world_center_x=world_center_x,
        world_center_y=world_center_y,
    )

    # Apply neighbor seam boundary conditions before erosion and reapply them
    # after height mutations. Direction names use numpy grid convention shared
    # by terrain_chunking/TerrainMaskStack: north=row 0, south=row -1,
    # west=col 0, east=col -1.
    # neighbor_edges is an optional dict: {"north": [...], "south": [...],
    # "east": [...], "west": [...]} where each value is a 1-D list/array of
    # height floats matching the tile's W (north/south) or H (east/west) size.
    _neighbor_edges = params.get("neighbor_edges") or {}
    def _apply_neighbor_edge_locks(heightmap_in: np.ndarray) -> np.ndarray:
        _BLEND_W = [1.0, 0.6, 0.2]
        _H, _W = heightmap_in.shape
        for _dir, _edge_raw in _neighbor_edges.items():
            _edge = np.asarray(_edge_raw, dtype=np.float32)
            if _dir == "north" and _edge.shape == (_W,):
                heightmap_in[0, :] = _edge
                for _off, _w in enumerate(_BLEND_W[1:], 1):
                    if _off < _H:
                        heightmap_in[_off, :] = _w * _edge + (1.0 - _w) * heightmap_in[_off, :]
            elif _dir == "south" and _edge.shape == (_W,):
                heightmap_in[-1, :] = _edge
                for _off, _w in enumerate(_BLEND_W[1:], 1):
                    if _H - 1 - _off >= 0:
                        heightmap_in[_H - 1 - _off, :] = _w * _edge + (1.0 - _w) * heightmap_in[_H - 1 - _off, :]
            elif _dir == "east" and _edge.shape == (_H,):
                heightmap_in[:, -1] = _edge
                for _off, _w in enumerate(_BLEND_W[1:], 1):
                    if _W - 1 - _off >= 0:
                        heightmap_in[:, _W - 1 - _off] = _w * _edge + (1.0 - _w) * heightmap_in[:, _W - 1 - _off]
            elif _dir == "west" and _edge.shape == (_H,):
                heightmap_in[:, 0] = _edge
                for _off, _w in enumerate(_BLEND_W[1:], 1):
                    if _off < _W:
                        heightmap_in[:, _off] = _w * _edge + (1.0 - _w) * heightmap_in[:, _off]
        return heightmap_in

    if _neighbor_edges:
        heightmap = _apply_neighbor_edge_locks(heightmap)

    erosion_applied = False
    if erosion in ("hydraulic", "both"):
        heightmap = erode_world_heightmap(
            heightmap,
            hydraulic_iterations=erosion_iters,
            thermal_iterations=0,
            seed=seed,
        )["heightmap"]
        erosion_applied = True
    if erosion in ("thermal", "both"):
        heightmap = erode_world_heightmap(
            heightmap,
            hydraulic_iterations=0,
            thermal_iterations=max(erosion_iters // 50, 5),
            seed=seed,
        )["heightmap"]
        erosion_applied = True

    if erosion_margin > 0:
        heightmap = heightmap[
            erosion_margin : erosion_margin + tile_size + 1,
            erosion_margin : erosion_margin + tile_size + 1,
        ]
    if _neighbor_edges:
        heightmap = _apply_neighbor_edge_locks(heightmap)

    flatten_zones = params.get("flatten_zones", None)
    if flatten_zones:
        from .terrain_advanced import flatten_multiple_zones
        heightmap = flatten_multiple_zones(heightmap, flatten_zones)
        if _neighbor_edges:
            heightmap = _apply_neighbor_edge_locks(heightmap)

    # Ask _resolve_height_range without local fallback; fall back to the
    # per-terrain-type estimator only when no explicit range was supplied.
    # This is clean "single source of truth" for range resolution and fixes
    # the duplicate key-presence check (Gemini consensus finding).
    height_range = _resolve_height_range(
        params, heightmap, allow_local_fallback=False
    )
    if height_range is None:
        height_range = _estimate_tile_height_range(
            terrain_type,
            octaves=octaves,
            persistence=persistence,
        )

    moisture_map = None
    splatmap = None
    if export_splatmaps:
        from .terrain_advanced import compute_flow_map

        flow_result = compute_flow_map(heightmap)
        flow_acc = np.asarray(flow_result["flow_accumulation"], dtype=np.float64)
        log_flow = np.nan_to_num(np.log1p(np.maximum(flow_acc, 0.0)), nan=0.0, posinf=GLOBAL_LOG_FLOW_NORM, neginf=0.0)
        moisture_map = np.clip(log_flow / GLOBAL_LOG_FLOW_NORM, 0.0, 1.0)

        splatmap = compute_world_splatmap_weights(
            heightmap,
            biome_name=biome_name,
            cell_size=cell_size,
            moisture_map=moisture_map,
            height_range=height_range,
        )

    terrain_result = _create_terrain_mesh_from_heightmap(
        name=name,
        heightmap=heightmap,
        terrain_size=terrain_size,
        height_scale=height_scale,
        seed=seed,
        terrain_type=terrain_type,
        object_location=object_location,
        cliff_overlays_enabled=cliff_overlays_enabled,
        cliff_threshold_deg=cliff_threshold,
    )

    result = {
        "name": terrain_result["name"],
        "tile_x": tile_x,
        "tile_y": tile_y,
        "tile_size": tile_size,
        "resolution": resolution,
        "cell_size": cell_size,
        "world_origin_x": world_origin_x,
        "world_origin_y": world_origin_y,
        "terrain_type": terrain_type,
        "height_scale": height_scale,
        "vertex_count": terrain_result["vertex_count"],
        "cliff_overlays": terrain_result["cliff_overlays"],
        "erosion_applied": erosion_applied,
        "erosion_margin": erosion_margin,
        "flatten_zones_applied": len(flatten_zones) if flatten_zones else 0,
        "object_location": terrain_result["object_location"],
        "terrain_size": terrain_size,
        "grid_x": tile_x,
        "grid_y": tile_y,
        "position": [world_origin_x, 0.0, world_origin_y],
        "size": [terrain_size, height_scale, terrain_size],
        "height_range": [height_range[0], height_range[1]],
        "export_dir": str(export_root),
    }
    result.update(
        _export_world_tile_artifacts(
            export_dir=export_root,
            tile_name=name,
            heightmap=heightmap,
            splatmap=splatmap if export_splatmaps else None,
            height_range=height_range,
        )
    )

    from .terrain_chunking import build_tile_seam_contract

    seam_contract = build_tile_seam_contract(
        heightmap,
        tile_x=tile_x,
        tile_y=tile_y,
        cell_size=cell_size,
        world_origin_x=world_origin_x,
        world_origin_y=world_origin_y,
        world_id=world_id,
        batch_id=str(batch_id) if batch_id is not None else None,
    )
    tile_manifest = {
        "schema_version": "1.0",
        "world_id": world_id,
        "batch_id": None if batch_id is None else str(batch_id),
        "tile_name": terrain_result["name"],
        "tile_x": tile_x,
        "tile_y": tile_y,
        "tile_size": tile_size,
        "resolution": resolution,
        "cell_size": cell_size,
        "world_origin_x": world_origin_x,
        "world_origin_y": world_origin_y,
        "terrain_size": terrain_size,
        "terrain_type": terrain_type,
        "seed": seed,
        "height_range": [height_range[0], height_range[1]],
        "heightmap_path": result.get("heightmap_path"),
        "alphamap_path": result.get("alphamap_path"),
        "seam_contract": seam_contract,
    }
    tile_manifest_path = export_root / f"{name}_tile_manifest.json"
    result["seam_contract"] = seam_contract
    try:
        result["tile_manifest_path"] = _write_json_manifest(tile_manifest_path, tile_manifest)
    except Exception:
        _cleanup_written_artifacts(
            [
                result.get("heightmap_path"),
                result.get("alphamap_path"),
                tile_manifest_path,
            ]
        )
        raise
    return result


# ---------------------------------------------------------------------------
# Handler: generate_world_terrain
# ---------------------------------------------------------------------------

def handle_generate_world_terrain(params: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper over tile generation for legacy world-terrain callers.

    AAA upgrade: full timing metrics, pass_name, affected_cells, error isolation
    per tile (failed tiles are collected and reported rather than crashing the
    whole batch), and a structured world_bounds summary for downstream Unity
    streaming setup. Comparable to UE5 World Partition multi-tile cook.

    Params:
        name (str): Base object name. Default "WorldTerrain".
        tile_x / start_tile_x (int): Starting tile X index.
        tile_y / start_tile_y (int): Starting tile Y index.
        tiles_x / world_tiles_x (int): Number of tiles along X. Default 1.
        tiles_y / world_tiles_y (int): Number of tiles along Y. Default 1.
        (All other params forwarded verbatim to handle_generate_terrain_tile.)

    Returns dict with: name, tile_count, tiles_x, tiles_y, tiles, ok,
        failed_tile_count, total_vertex_count, world_bounds,
        affected_cells, duration_seconds, pass_name,
        compatibility_mode, deprecated_command.
    """
    _t0 = time.perf_counter()
    base_name = str(params.get("name", "WorldTerrain"))
    world_id = str(params.get("world_id", base_name))
    start_tile_x = int(params.get("tile_x", params.get("start_tile_x", 0)))
    start_tile_y = int(params.get("tile_y", params.get("start_tile_y", 0)))
    tiles_x = max(1, int(params.get("tiles_x", params.get("world_tiles_x", 1))))
    tiles_y = max(1, int(params.get("tiles_y", params.get("world_tiles_y", 1))))
    batch_id = str(
        params.get(
            "batch_id",
            f"{base_name}_{start_tile_x}_{start_tile_y}_{tiles_x}x{tiles_y}",
        )
    )
    first_tile = _resolve_terrain_tile_params(
        {
            **params,
            "tile_x": start_tile_x,
            "tile_y": start_tile_y,
        }
    )
    terrain_size = float(first_tile["terrain_size"])
    requested_world_bounds = {
        "min_x": float(first_tile["world_origin_x"]),
        "min_y": float(first_tile["world_origin_y"]),
        "max_x": float(first_tile["world_origin_x"]) + terrain_size * tiles_x,
        "max_y": float(first_tile["world_origin_y"]) + terrain_size * tiles_y,
    }

    tile_results: list[dict[str, Any]] = []
    failed_tiles: list[dict[str, Any]] = []
    total_vertex_count = 0
    total_affected_cells = 0

    for offset_y in range(tiles_y):
        for offset_x in range(tiles_x):
            tile_x = start_tile_x + offset_x
            tile_y = start_tile_y + offset_y
            tile_params = dict(params)
            tile_params["tile_x"] = tile_x
            tile_params["tile_y"] = tile_y
            tile_params["world_id"] = world_id
            tile_params["batch_id"] = batch_id
            neighbor_edges: dict[str, Any] = dict(tile_params.get("neighbor_edges") or {})
            west_tile = next(
                (
                    t for t in tile_results
                    if int(t.get("tile_x", -999999)) == tile_x - 1
                    and int(t.get("tile_y", -999999)) == tile_y
                    and t.get("heightmap_path")
                ),
                None,
            )
            north_tile = next(
                (
                    t for t in tile_results
                    if int(t.get("tile_x", -999999)) == tile_x
                    and int(t.get("tile_y", -999999)) == tile_y - 1
                    and t.get("heightmap_path")
                ),
                None,
            )
            try:
                if west_tile is not None and "west" not in neighbor_edges:
                    west_h = np.load(west_tile["heightmap_path"])
                    neighbor_edges["west"] = np.asarray(west_h)[:, -1].tolist()
                if north_tile is not None and "north" not in neighbor_edges:
                    north_h = np.load(north_tile["heightmap_path"])
                    neighbor_edges["north"] = np.asarray(north_h)[-1, :].tolist()
            except Exception as exc:
                logger.warning(
                    "handle_generate_world_terrain: failed to load neighbor edge for tile (%d,%d): %s",
                    tile_x, tile_y, exc,
                )
            if neighbor_edges:
                tile_params["neighbor_edges"] = neighbor_edges
            if tiles_x > 1 or tiles_y > 1:
                tile_params["name"] = f"{base_name}_{tile_x}_{tile_y}"
            else:
                tile_params["name"] = base_name
            try:
                tile_result = handle_generate_terrain_tile(tile_params)
                tile_results.append(tile_result)
                total_vertex_count += int(tile_result.get("vertex_count", 0))
                total_affected_cells += int(tile_result.get("vertex_count", 0))
            except Exception as exc:
                logger.warning(
                    "handle_generate_world_terrain: tile (%d,%d) failed: %s",
                    tile_x, tile_y, exc,
                )
                failed_tiles.append({
                    "tile_x": tile_x,
                    "tile_y": tile_y,
                    "error": str(exc),
                })

    # Compute world bounds from successful tiles
    successful_world_bounds: dict[str, float] | None = None
    if tile_results:
        all_x_origins = [float(t.get("world_origin_x", 0.0)) for t in tile_results]
        all_y_origins = [float(t.get("world_origin_y", 0.0)) for t in tile_results]
        tile_sizes = [float(t.get("terrain_size", t.get("tile_size", 256))) for t in tile_results]
        successful_world_bounds = {
            "min_x": min(all_x_origins),
            "min_y": min(all_y_origins),
            "max_x": max(ox + ts for ox, ts in zip(all_x_origins, tile_sizes)),
            "max_y": max(oy + ts for oy, ts in zip(all_y_origins, tile_sizes)),
        }

    batch_manifest_path: str | None = None
    frontier_tiles: list[dict[str, int]] = []
    batch_manifest_error: str | None = None
    if tile_results:
        from .terrain_chunking import build_tile_batch_manifest

        tile_contracts = [
            contract
            for contract in (
                tile.get("seam_contract") for tile in tile_results
            )
            if isinstance(contract, dict)
        ]
        if tile_contracts:
            batch_manifest = build_tile_batch_manifest(
                tile_contracts,
                world_id=world_id,
                batch_id=batch_id,
            )
            frontier_set = {
                (int(tile["tile_x"]), int(tile["tile_y"]))
                for tile in batch_manifest.get("frontier_tiles", ())
            }
            frontier_set.update(
                (int(tile["tile_x"]), int(tile["tile_y"]))
                for tile in failed_tiles
            )
            frontier_tiles = [
                {"tile_x": coords[0], "tile_y": coords[1]}
                for coords in sorted(frontier_set, key=lambda item: (item[1], item[0]))
            ]
            batch_manifest["frontier_tiles"] = frontier_tiles
            batch_export_root = Path(
                params.get("export_dir")
                or params.get("output_dir")
                or Path("Temp") / "VB_TerrainExports" / base_name
            )
            batch_manifest_target = batch_export_root / "world_batch_manifest.json"
            try:
                batch_manifest_path = _write_json_manifest(
                    batch_manifest_target,
                    batch_manifest,
                )
            except Exception as exc:
                batch_manifest_error = str(exc)
                _cleanup_written_artifacts([batch_manifest_target])
                logger.warning(
                    "handle_generate_world_terrain: batch manifest write failed: %s",
                    exc,
                )
    elif failed_tiles:
        frontier_tiles = [
            {"tile_x": int(tile["tile_x"]), "tile_y": int(tile["tile_y"])}
            for tile in failed_tiles
        ]

    _duration = time.perf_counter() - _t0

    if len(tile_results) == 1 and not failed_tiles:
        result = dict(tile_results[0])
        result["compatibility_mode"] = "world_to_tile_wrapper"
        result["deprecated_command"] = True
        result["ok"] = batch_manifest_error is None
        result["failed_tile_count"] = 0
        result.setdefault("affected_cells", total_affected_cells)
        result.setdefault("duration_seconds", round(_duration, 4))
        result["pass_name"] = "generate_world_terrain"
        result["world_id"] = world_id
        result["batch_id"] = batch_id
        result["batch_manifest_path"] = batch_manifest_path
        result["batch_manifest_error"] = batch_manifest_error
        result["frontier_tiles"] = frontier_tiles
        result["world_bounds"] = requested_world_bounds
        result["successful_world_bounds"] = successful_world_bounds
        return result

    return {
        "name": base_name,
        "world_id": world_id,
        "batch_id": batch_id,
        "deprecated_command": True,
        "compatibility_mode": "world_to_tile_wrapper",
        "tile_count": len(tile_results),
        "tiles_x": tiles_x,
        "tiles_y": tiles_y,
        "tiles": tile_results,
        "ok": len(failed_tiles) == 0 and batch_manifest_error is None,
        "failed_tile_count": len(failed_tiles),
        "failed_tiles": failed_tiles,
        "total_vertex_count": total_vertex_count,
        "world_bounds": requested_world_bounds,
        "successful_world_bounds": successful_world_bounds,
        "batch_manifest_path": batch_manifest_path,
        "batch_manifest_error": batch_manifest_error,
        "frontier_tiles": frontier_tiles,
        # AAA metrics
        "affected_cells": total_affected_cells,
        "duration_seconds": round(_duration, 4),
        "pass_name": "generate_world_terrain",
    }


# ---------------------------------------------------------------------------
# Bundle A handler: run_terrain_pass
# ---------------------------------------------------------------------------


def _execute_terrain_pipeline(params: dict[str, Any]) -> dict[str, Any]:
    """Execute a terrain pass or pipeline and return live controller state."""
    # Local imports to avoid circular dependency at module load.
    from .terrain_master_registrar import register_all_terrain_passes
    from .terrain_pipeline import TerrainPassController, build_default_pass_sequence
    from .terrain_semantics import (
        BBox,
        ProtectedZoneSpec,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
        TerrainSceneRead,
        UnknownPassError,
        WaterSystemSpec,
    )

    requested_pipeline = params.get("pipeline")
    requested_passes = list(requested_pipeline) if requested_pipeline is not None else []
    if not requested_passes:
        pass_name = params.get("pass_name")
        if pass_name:
            requested_passes = [str(pass_name)]
        else:
            _qp_name = str(params.get("quality_profile", "aaa_open_world"))
            _is_preview_qp = _qp_name in ("preview", "mobile", "low")
            requested_passes = [
                "pass_generate_low_freq_hmap",
                "terrain_labels",
                "structural_masks",
                "pass_generate_high_freq_detail",
                "pass_composite_hmap",
                "validation_minimal" if _is_preview_qp else "validation_full",
            ]
            if params.get("scene_read") is not None:
                requested_passes[3:3] = ["pass_hydrology", "erosion"]

    # Ensure all requested passes are registered even for direct callers
    # importing this module without the handlers package side effects.
    missing_passes = [
        pass_name for pass_name in requested_passes
        if pass_name not in TerrainPassController.PASS_REGISTRY
    ]
    if missing_passes or not TerrainPassController.PASS_REGISTRY:
        register_all_terrain_passes(strict=not bool(TerrainPassController.PASS_REGISTRY))
        still_missing = [
            pass_name for pass_name in requested_passes
            if pass_name not in TerrainPassController.PASS_REGISTRY
        ]
        if still_missing:
            raise UnknownPassError(
                f"Terrain pipeline requested unregistered passes after registrar load: {still_missing}"
            )

    tile_size = int(params.get("tile_size", 64))
    cell_size = float(params.get("cell_size", 1.0))
    seed = int(params.get("seed", 0))
    tile_x = int(params.get("tile_x", 0))
    tile_y = int(params.get("tile_y", 0))
    world_origin_x = float(params.get("world_origin_x", 0.0))
    world_origin_y = float(params.get("world_origin_y", 0.0))

    # Resolve region bounds
    def _to_bbox(value: Any) -> Optional[BBox]:
        if value is None:
            return None
        if isinstance(value, BBox):
            bbox = value
            coords = np.array([bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y], dtype=np.float64)
        elif isinstance(value, dict):
            coords = np.array(
                [
                    float(value["min_x"]),
                    float(value["min_y"]),
                    float(value["max_x"]),
                    float(value["max_y"]),
                ],
                dtype=np.float64,
            )
        elif isinstance(value, (list, tuple)) and len(value) == 4:
            coords = np.array(
                [float(value[0]), float(value[1]), float(value[2]), float(value[3])],
                dtype=np.float64,
            )
        else:
            raise ValueError(f"region bounds must be dict|list[4]|BBox, got {type(value)}")
        if not np.isfinite(coords).all():
            raise ValueError("region bounds must contain only finite coordinates")
        if coords[2] < coords[0] or coords[3] < coords[1]:
            raise ValueError("region bounds must satisfy max >= min on both axes")
        if isinstance(value, BBox):
            return value
        return BBox(
            min_x=float(coords[0]),
            min_y=float(coords[1]),
            max_x=float(coords[2]),
            max_y=float(coords[3]),
        )

    region_bounds = _to_bbox(params.get("region_bounds")) or BBox(
        min_x=world_origin_x,
        min_y=world_origin_y,
        max_x=world_origin_x + tile_size * cell_size,
        max_y=world_origin_y + tile_size * cell_size,
    )
    region = _to_bbox(params.get("region"))

    # Protected zones — reject malformed entries early with a clear error.
    protected_zones: list[ProtectedZoneSpec] = []
    for i, pz in enumerate(params.get("protected_zones", []) or []):
        bounds_raw = pz.get("bounds")
        if bounds_raw is None:
            raise ValueError(
                f"protected_zones[{i}]: 'bounds' is required (dict|list[4]|BBox)"
            )
        bounds = _to_bbox(bounds_raw)
        if bounds is None:
            raise ValueError(
                f"protected_zones[{i}]: 'bounds' must resolve to a BBox, got {bounds_raw!r}"
            )
        protected_zones.append(
            ProtectedZoneSpec(
                zone_id=str(pz.get("zone_id", f"zone_{i}")),
                bounds=bounds,
                kind=str(pz.get("kind", "generic")),
                allowed_mutations=frozenset(pz.get("allowed_mutations", []) or []),
                forbidden_mutations=frozenset(pz.get("forbidden_mutations", []) or []),
                description=str(pz.get("description", "")),
            )
        )

    # Scene read (accept any non-None value as satisfying the requirement)
    scene_read_raw = params.get("scene_read")
    scene_read: Optional[TerrainSceneRead] = None
    viewport_vantage = params.get("viewport_vantage")
    if scene_read_raw is not None:
        from .terrain_scene_read import capture_scene_read, get_extended_metadata

        scene_read = capture_scene_read(
            reviewer=str(scene_read_raw.get("reviewer", "unknown")),
            focal_point_hint=tuple(scene_read_raw.get("focal_point", (0.0, 0.0, 0.0))),
            major_landforms=tuple(scene_read_raw.get("major_landforms", ()) or ()),
            hero_features_present=tuple(scene_read_raw.get("hero_features_present", ()) or ()),
            hero_features_missing=tuple(scene_read_raw.get("hero_features_missing", ()) or ()),
            waterfall_chains=tuple(scene_read_raw.get("waterfall_chains", ()) or ()),
            cave_candidates=tuple(
                tuple(entry)
                for entry in (scene_read_raw.get("cave_candidates", ()) or ())
                if isinstance(entry, (list, tuple)) and len(entry) >= 2
            ),
            protected_zones_in_region=tuple(z.zone_id for z in protected_zones),
            edit_scope=region or region_bounds,
            success_criteria=tuple(scene_read_raw.get("success_criteria", ()) or ()),
            viewport_vantage=scene_read_raw.get("viewport_vantage", viewport_vantage),
            addon_version=(
                tuple(scene_read_raw.get("addon_version"))
                if scene_read_raw.get("addon_version") is not None
                else None
            ),
            terrain_content_hash=scene_read_raw.get("terrain_content_hash"),
            lockable_anchors=tuple(scene_read_raw.get("lockable_anchors", ()) or ()),
        )
        scene_read_ext = get_extended_metadata(scene_read) or {}
        viewport_vantage = scene_read_ext.get("viewport_vantage", viewport_vantage)

    # Build or accept heightmap
    height_raw = params.get("height")
    if height_raw is not None:
        height = np.asarray(height_raw, dtype=np.float64)
    else:
        from ._terrain_noise import generate_heightmap

        height = np.asarray(
            generate_heightmap(
                tile_size + 1,
                tile_size + 1,
                scale=float(params.get("scale", 100.0)),
                world_origin_x=world_origin_x,
                world_origin_y=world_origin_y,
                cell_size=cell_size,
                seed=seed,
                terrain_type=str(params.get("terrain_type", "mountains")),
                normalize=False,
            ),
            dtype=np.float64,
        )

    mask_stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=cell_size,
        world_origin_x=world_origin_x,
        world_origin_y=world_origin_y,
        tile_x=tile_x,
        tile_y=tile_y,
        height=height,
    )

    water_system_raw = params.get("water_system_spec")
    if not isinstance(water_system_raw, dict):
        water_system_raw = {}
    hero_waterfalls_raw = water_system_raw.get("hero_waterfalls", params.get("hero_waterfalls", ()))
    if isinstance(hero_waterfalls_raw, str):
        hero_waterfalls = (hero_waterfalls_raw,)
    else:
        hero_waterfalls = tuple(str(entry) for entry in (hero_waterfalls_raw or ()) if str(entry))
    water_system_spec = WaterSystemSpec(
        network_seed=int(water_system_raw.get("network_seed", seed)),
        min_drainage_area=float(water_system_raw.get("min_drainage_area", params.get("min_drainage_area", 500.0))),
        river_threshold=float(water_system_raw.get("river_threshold", params.get("river_threshold", 2000.0))),
        lake_min_area=float(water_system_raw.get("lake_min_area", params.get("lake_min_area", 100.0))),
        meander_amplitude=float(water_system_raw.get("meander_amplitude", params.get("meander_amplitude", 0.0))),
        bank_asymmetry=float(water_system_raw.get("bank_asymmetry", params.get("bank_asymmetry", 0.0))),
        tidal_range=float(water_system_raw.get("tidal_range", params.get("tidal_range", 0.0))),
        hero_waterfalls=hero_waterfalls,
        braided_channels=bool(water_system_raw.get("braided_channels", params.get("braided_channels", False))),
        estuaries=bool(water_system_raw.get("estuaries", params.get("estuaries", False))),
        karst_springs=bool(water_system_raw.get("karst_springs", params.get("karst_springs", False))),
        perched_lakes=bool(water_system_raw.get("perched_lakes", params.get("perched_lakes", False))),
        hot_springs=bool(water_system_raw.get("hot_springs", params.get("hot_springs", False))),
        wetlands=bool(water_system_raw.get("wetlands", params.get("wetlands", False))),
        seasonal_state=str(water_system_raw.get("seasonal_state", params.get("seasonal_state", "normal"))),
    )

    composition_hints = dict(params.get("composition_hints") or {})
    quality_profile = str(params.get("quality_profile", "aaa_open_world"))

    intent = TerrainIntentState(
        seed=seed,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=cell_size,
        protected_zones=tuple(protected_zones),
        water_system_spec=water_system_spec,
        quality_profile=quality_profile,
        noise_profile=str(params.get("noise_profile", params.get("terrain_type", "mountains"))),
        erosion_profile=str(
            params.get("erosion_profile")
            or composition_hints.get("erosion_profile")
            or composition_hints.get("climate")
            or "temperate"
        ),
        scene_read=scene_read,
        composition_hints=composition_hints,
    )

    state = TerrainPipelineState(intent=intent, mask_stack=mask_stack)
    state.viewport_vantage = viewport_vantage
    try:
        state.water_network = WaterNetwork.from_heightmap(
            height,
            cell_size=cell_size,
            world_origin_x=world_origin_x,
            world_origin_y=world_origin_y,
            tile_size=tile_size,
            min_drainage_area=water_system_spec.min_drainage_area,
            river_threshold=water_system_spec.river_threshold,
            lake_min_area=water_system_spec.lake_min_area,
            seed=water_system_spec.network_seed,
        )
    except Exception as water_network_exc:
        logger.debug(
            "Terrain pipeline water network generation skipped: %s",
            water_network_exc,
            exc_info=True,
        )

    # --- Protocol enforcement (Bundle R, Addendum 1.A.2) -------------------
    # Every production mutation handler MUST route through ProtocolGate.
    # Callers that cannot attach a full scene/vantage (unit tests, CLI dev
    # runs) opt out via ``enforce_protocol=False`` in params.
    if bool(params.get("enforce_protocol", False)):
        from .terrain_protocol import ProtocolGate, ProtocolViolation

        try:
            ProtocolGate.rule_1_observe_before_calculate(state)
            ProtocolGate.rule_2_sync_to_user_viewport(
                state,
                out_of_view_ok=bool(params.get("out_of_view_ok", False)),
            )
            ProtocolGate.rule_3_lock_reference_empties(state)
            ProtocolGate.rule_4_real_geometry_not_vertex_tricks(params)
            ProtocolGate.rule_5_smallest_diff_per_iteration(
                state,
                cells_affected=int(params.get("cells_affected", 0)),
                objects_affected=int(params.get("objects_affected", 0)),
                bulk_edit=bool(params.get("bulk_edit", False)),
            )
            ProtocolGate.rule_6_surface_vs_interior_classification(params)
            ProtocolGate.rule_7_plugin_usage(params)
        except ProtocolViolation as exc:
            return {
                "ok": False,
                "error": "protocol_violation",
                "message": str(exc),
            }

    controller = TerrainPassController(state)

    # Bind the controller so pass_validation_full can trigger rollback on
    # hard failures (Fix M4 — previously the module-global was never set in
    # production, making rollback dead outside tests).
    from .terrain_validation import bind_active_controller

    bind_active_controller(controller)

    pass_name = params.get("pass_name")
    pipeline = params.get("pipeline")

    unity_export_opt_out = bool(composition_hints.get("unity_export_opt_out", False))

    if pipeline is None and pass_name is None:
        pipeline = build_default_pass_sequence(intent)

    if pipeline is not None:
        pipeline = list(pipeline)
        if (
            any(pass_name in pipeline for pass_name in ("cliffs", "caves"))
            and "emit_overhang_meshes" not in pipeline
        ):
            insert_at = next(
                (
                    idx
                    for idx, pipeline_pass in enumerate(pipeline)
                    if pipeline_pass.startswith("validation_")
                ),
                len(pipeline),
            )
            pipeline.insert(insert_at, "emit_overhang_meshes")
        if (
            "waterfalls" in pipeline
            and "emit_particle_systems" not in pipeline
        ):
            insert_at = next(
                (
                    idx
                    for idx, pipeline_pass in enumerate(pipeline)
                    if pipeline_pass.startswith("validation_")
                ),
                len(pipeline),
            )
            pipeline.insert(insert_at, "emit_particle_systems")
        if "validation_full" in pipeline and not unity_export_opt_out:
            scene_read_enabled = getattr(intent, "scene_read", None) is not None
            ordered_prereqs = (
                *(("water_variants", "bathymetry", "pass_water_depth") if scene_read_enabled else ()),
                *((
                    "waterfalls",
                    "emit_particle_systems",
                    "pass_morphology",
                    "integrate_deltas",
                    "materials_v2",
                    "emit_overhang_meshes",
                    "scatter_intelligent",
                    "pass_horizon_lod",
                ) if scene_read_enabled else ("materials_v2",)),
                "pass_navmesh_export",
                "prepare_terrain_normals",
                "prepare_heightmap_raw_u16",
                "prepare_unity_auxiliary_channels",
            )
            insert_at = min(
                [
                    pipeline.index(existing)
                    for existing in (*ordered_prereqs, "validation_full")
                    if existing in pipeline
                ]
            )
            for prereq in ordered_prereqs:
                if prereq not in pipeline:
                    pipeline.insert(insert_at, prereq)
                    insert_at += 1

    requested_after_injection = list(pipeline) if pipeline is not None else [str(pass_name)]
    missing_after_injection = [
        pipeline_pass
        for pipeline_pass in requested_after_injection
        if pipeline_pass not in TerrainPassController.PASS_REGISTRY
    ]
    if missing_after_injection:
        register_all_terrain_passes(strict=False)
        still_missing_after_injection = [
            pipeline_pass
            for pipeline_pass in requested_after_injection
            if pipeline_pass not in TerrainPassController.PASS_REGISTRY
        ]
        if still_missing_after_injection:
            raise UnknownPassError(
                "Terrain pipeline contains unregistered passes after canonical injection: "
                f"{still_missing_after_injection}"
            )

    try:
        if pipeline is not None:
            results = controller.run_pipeline(
                pass_sequence=pipeline,
                region=region,
                checkpoint=bool(params.get("checkpoint", False)),
            )
        else:
            results = [
                controller.run_pass(
                    str(pass_name),
                    region=region,
                    checkpoint=bool(params.get("checkpoint", False)),
                )
            ]
    finally:
        # Unbind the controller to prevent stale references from leaking
        # across calls (Fix M4).
        bind_active_controller(None)

    return {
        "controller": controller,
        "state": state,
        "mask_stack": mask_stack,
        "results": results,
        "tile_x": tile_x,
        "tile_y": tile_y,
        "pipeline": pipeline,
        "pass_name": pass_name,
    }


def handle_run_terrain_pass(params: dict[str, Any]) -> dict[str, Any]:
    """Run a registered terrain pass via ``TerrainPassController``.

    Required params:
        pass_name (str)  — name of a registered pass (e.g. "macro_world")
        tile_size (int)  — cells per tile edge
        cell_size (float)
        seed (int)

    Optional params:
        tile_x (int=0), tile_y (int=0)
        world_origin_x (float=0.0), world_origin_y (float=0.0)
        region_bounds (dict|list) — BBox for the intent region
        region (dict|list) — BBox for scoped execution
        protected_zones (list[dict])
        scene_read (dict)  — presence signals that scene-read requirement is met
        height (list[list[float]]|np.ndarray) — optional pre-built heightmap
        terrain_type (str), scale (float) — for generating initial height
        erosion_profile (str)
        pipeline (list[str]) — pass sequence
        pass_name=... with pipeline=None runs a single pass

    Default behavior:
        - with ``scene_read``: ``macro_world -> structural_masks -> erosion -> validation_minimal``
        - without ``scene_read``: ``macro_world -> structural_masks -> validation_minimal``

    Returns:
        dict with ``ok``, ``results`` (list of PassResult dicts),
        ``content_hash``, ``populated_channels``.
    """
    execution_params = dict(params)
    execution_params.setdefault("enforce_protocol", True)
    execution = _execute_terrain_pipeline(execution_params)
    if execution.get("ok") is False:
        return execution
    mask_stack = execution["mask_stack"]
    results = execution["results"]

    def _serialize(pr: Any) -> dict[str, Any]:
        return {
            "pass_name": pr.pass_name,
            "status": pr.status,
            "duration_seconds": pr.duration_seconds,
            "produced_channels": list(pr.produced_channels),
            "consumed_channels": list(pr.consumed_channels),
            "metrics": pr.metrics,
            "seed_used": pr.seed_used,
            "content_hash_before": pr.content_hash_before,
            "content_hash_after": pr.content_hash_after,
            "issues": [
                {"code": i.code, "severity": i.severity, "message": i.message}
                for i in pr.issues
            ],
        }

    return {
        "ok": all(r.status == "ok" for r in results),
        "results": [_serialize(r) for r in results],
        "content_hash": mask_stack.compute_hash(),
        "populated_channels": sorted(mask_stack.populated_by_pass.keys()),
        "tile_x": execution["tile_x"],
        "tile_y": execution["tile_y"],
    }


def handle_generate_waterfall(params: dict[str, Any]) -> dict[str, Any]:
    """Generate a waterfall from water-network context when available.

    The legacy terrain-feature mesh generator remains available only via an
    explicit opt-in fallback flag; public terrain-water authoring should
    supply a heightmap so the waterfall is derived from hydrologic context.
    """
    def _coerce_facing_direction(raw_value: Any) -> tuple[float, float]:
        if isinstance(raw_value, (list, tuple)) and len(raw_value) >= 2:
            dx = float(raw_value[0])
            dy = float(raw_value[1])
            if math.isfinite(dx) and math.isfinite(dy):
                mag = math.hypot(dx, dy)
                if mag > 1e-6:
                    return dx / mag, dy / mag
        return 0.0, -1.0

    facing_direction: tuple[float, float] = _coerce_facing_direction(
        params.get("facing_direction")
    )
    require_heightmap_context = bool(params.get("require_heightmap_context", False))
    allow_legacy_geometry_fallback = bool(params.get("allow_legacy_geometry_fallback", False))
    heightmap_raw = params.get("heightmap")
    if heightmap_raw is None and (require_heightmap_context or not allow_legacy_geometry_fallback):
        raise ValueError(
            "env_generate_waterfall requires heightmap/water-network context; "
            "pass allow_legacy_geometry_fallback=True to opt into the deprecated geometry fallback"
        )
    if heightmap_raw is not None:
        heightmap = np.asarray(heightmap_raw, dtype=np.float64)
        if heightmap.ndim != 2:
            raise ValueError("heightmap must be a 2D array")

        tile_size = int(params.get("tile_size", max(min(heightmap.shape) - 1, 1)))
        cell_size = float(params.get("cell_size", 1.0))
        tile_x = int(params.get("tile_x", 0))
        tile_y = int(params.get("tile_y", 0))
        network = WaterNetwork.from_heightmap(
            heightmap,
            cell_size=cell_size,
            world_origin_x=float(params.get("world_origin_x", 0.0)),
            world_origin_y=float(params.get("world_origin_y", 0.0)),
            tile_size=tile_size,
            min_drainage_area=float(params.get("min_drainage_area", 500.0)),
            river_threshold=float(params.get("river_threshold", 2000.0)),
            lake_min_area=float(params.get("lake_min_area", 100.0)),
            seed=int(params.get("seed", 42)),
        )
        features = network.get_tile_water_features(
            tile_x,
            tile_y,
            tile_size=tile_size,
            cell_size=cell_size,
        )
        waterfalls = features.get("waterfalls", [])
        if not waterfalls:
            raise ValueError("No waterfall candidates were detected in the supplied tile")

        chosen = waterfalls[0]
        requested_location = params.get("location")
        if (
            len(waterfalls) > 1
            and isinstance(requested_location, (list, tuple))
            and len(requested_location) >= 3
        ):
            target_x = float(requested_location[0])
            target_y = float(requested_location[1])
            target_z = float(requested_location[2])

            def _candidate_score(candidate: dict[str, Any]) -> float:
                best = float("inf")
                for anchor_key in ("top", "bottom"):
                    anchor = candidate.get(anchor_key)
                    if not isinstance(anchor, (list, tuple)) or len(anchor) < 3:
                        continue
                    dx = float(anchor[0]) - target_x
                    dy = float(anchor[1]) - target_y
                    dz = float(anchor[2]) - target_z
                    best = min(best, dx * dx + dy * dy + dz * dz)
                return best

            chosen = min(waterfalls, key=_candidate_score)
        top = chosen.get("top")
        bottom = chosen.get("bottom")
        if params.get("facing_direction") is None and isinstance(top, (list, tuple)) and isinstance(bottom, (list, tuple)):
            facing_direction = _coerce_facing_direction(
                (
                    float(bottom[0]) - float(top[0]),
                    float(bottom[1]) - float(top[1]),
                )
            )
        fallback = generate_waterfall(
            height=max(float(chosen["drop"]), 1.0),
            width=max(float(chosen["width"]), 1.0),
            pool_radius=max(float(params.get("pool_radius", chosen["width"] * 1.5)), 1.0),
            num_steps=int(params.get("num_steps", 3)),
            has_cave_behind=bool(params.get("has_cave_behind", True)),
            seed=int(params.get("seed", 42)),
            facing_direction=facing_direction,
        )
        fallback["authoring_path"] = "water_network_derived"
        fallback["waterfall_feature"] = chosen
        fallback["waterfall_candidates"] = len(waterfalls)
        result = fallback
    else:
        legacy = generate_waterfall(
            height=params.get("height", 10.0),
            width=params.get("width", 3.0),
            pool_radius=params.get("pool_radius", 4.0),
            num_steps=params.get("num_steps", 3),
            has_cave_behind=params.get("has_cave_behind", True),
            seed=params.get("seed", 42),
            facing_direction=facing_direction,
        )
        legacy["authoring_path"] = "legacy_geometry_fallback"
        legacy["warning"] = (
            "env_generate_waterfall used deprecated geometry fallback; "
            "supply heightmap/water-network context instead."
        )
        result = legacy

    mesh_payload = result.get("mesh", {})
    object_name_raw = params.get("name") or params.get("object_name")
    mesh_spec = {
        "vertices": list(mesh_payload.get("vertices", []) or []),
        "faces": list(mesh_payload.get("faces", []) or []),
        "material_ids": list(result.get("material_indices", []) or []),
        "metadata": {
            "name": str(object_name_raw or "Waterfall"),
            "category": "terrain_feature",
            "feature_kind": "waterfall",
        },
    }
    if not mesh_spec["vertices"] or not mesh_spec["faces"]:
        return result

    location_raw = params.get("location", (0.0, 0.0, 0.0))
    location = (
        float(location_raw[0]) if len(location_raw) >= 1 else 0.0,
        float(location_raw[1]) if len(location_raw) >= 2 else 0.0,
        float(location_raw[2]) if len(location_raw) >= 3 else 0.0,
    )
    chain_id = _resolve_waterfall_chain_id(
        result,
        object_name=object_name_raw,
        fallback_location=location,
    )
    functional_objects = build_waterfall_functional_object_names(chain_id)
    authored_names_raw = params.get("functional_object_names")
    authored_names = [
        str(name)
        for name in authored_names_raw
        if str(name).strip()
    ] if isinstance(authored_names_raw, (list, tuple)) else functional_objects.as_list()
    result["functional_object_chain_id"] = chain_id
    result["functional_objects"] = {
        "river_surface": functional_objects.river_surface,
        "sheet_volume": functional_objects.sheet_volume,
        "impact_pool": functional_objects.impact_pool,
        "foam_layer": functional_objects.foam_layer,
        "mist_volume": functional_objects.mist_volume,
        "splash_particles": functional_objects.splash_particles,
        "wet_rock_material_zone": functional_objects.wet_rock_material_zone,
    }
    result["functional_object_names"] = functional_objects.as_list()
    result["functional_object_positions"] = _infer_waterfall_functional_positions(
        result,
        origin=location,
    )
    result["functional_object_contract_issues"] = _serialize_validation_issues(
        enforce_functional_object_naming(authored_names, chain_id)
    )
    result["functional_objects_materialized"] = False
    result["functional_objects_created"] = []

    if not object_name_raw and not bool(params.get("materialize_object", False)):
        return result

    rotation_raw = params.get("rotation", (0.0, 0.0, 0.0))
    rotation = (
        float(rotation_raw[0]) if len(rotation_raw) >= 1 else 0.0,
        float(rotation_raw[1]) if len(rotation_raw) >= 2 else 0.0,
        float(rotation_raw[2]) if len(rotation_raw) >= 3 else float(params.get("rotation_z", 0.0)),
    )
    parent_name = params.get("parent_name")
    parent_obj = bpy.data.objects.get(str(parent_name)) if parent_name and _HAS_BPY else None

    obj = _create_mesh_object_from_spec(
        mesh_spec,
        object_name=str(object_name_raw or "Waterfall"),
        location=location,
        rotation=rotation,
        parent=parent_obj,
    )
    if obj is not None and not isinstance(obj, dict):
        try:
            mat = _ensure_water_material(
                f"{obj.name}_Water",
                preview_fast=bool(params.get("preview_fast", False)),
                surface_only=True,
            )
            if mat is not None and hasattr(obj.data, "materials"):
                obj.data.materials.clear()
                obj.data.materials.append(mat)
        except Exception:
            logger.debug("Failed to assign waterfall material to %s", getattr(obj, "name", object_name_raw), exc_info=True)
        try:
            created_names = _publish_waterfall_functional_objects(
                result["functional_objects"],
                positions=result["functional_object_positions"],
                parent=obj,
                render_object_name=getattr(obj, "name", str(object_name_raw or "Waterfall")),
            )
            result["functional_objects_materialized"] = bool(created_names)
            result["functional_objects_created"] = created_names
            # Materialise actual volumetric mist object at the mist anchor position.
            mist_pos = result.get("functional_object_positions", {}).get("mist_volume")
            if mist_pos is not None:
                _materialise_mist_volume(
                    mist_pos,
                    parent=obj,
                    height_m=float(result.get("height", 3.0)),
                )
        except Exception:
            logger.debug(
                "Failed to publish waterfall functional objects for %s",
                getattr(obj, "name", object_name_raw),
                exc_info=True,
            )

    result["name"] = getattr(obj, "name", str(object_name_raw or "Waterfall"))
    result["object_created"] = obj is not None
    return result


def handle_stitch_terrain_edges(params: dict[str, Any]) -> dict[str, Any]:
    """Stitch the seam between two adjacent terrain tiles by averaging shared edge Z values.

    AAA upgrade: deterministic per-vertex averaging (no wall-clock time), protected
    zone enforcement (vertices inside a protected zone keep their original Z),
    batch foreach_set write-back for performance, and full metrics reporting.
    Comparable to UE5 World Partition landscape tile edge-stitching.

    Protected zone semantics:
        Any seam vertex whose world-space XY position falls inside a protected
        zone retains its original Z value. The partner vertex is also left
        unmodified to avoid introducing a one-sided step. The count of such
        skipped pairs is reported as ``protected_vertices_skipped``.

    Params:
        terrain_a (str): First terrain object name (the tile that has the shared edge).
        terrain_b (str): Adjacent terrain object name.
        direction (str): "east" | "west" | "north" | "south" — which shared edge.
        tolerance (float, default 1e-4): Position snapping tolerance for edge detection.
        protected_zones (list of dict): Optional BBox dicts; vertices inside are skipped.
        blend_weight_a (float, default 0.5): Weight of terrain_a Z in the blend.
            0.0 = terrain_b wins; 1.0 = terrain_a wins; 0.5 = average (default).

    Returns dict with: status, terrain_a, terrain_b, direction, matched_vertices,
        max_delta, protected_vertices_skipped, duration_seconds, pass_name,
        affected_cells.
    """
    _t0 = time.perf_counter()

    terrain_a_name = params.get("terrain_a") or params.get("terrain_name_a")
    terrain_b_name = params.get("terrain_b") or params.get("terrain_name_b")
    if not terrain_a_name or not terrain_b_name:
        raise ValueError(
            "'terrain_a' and 'terrain_b' are required — supply both tile object names"
        )

    direction = str(params.get("direction", "east")).lower().strip()
    _VALID_DIRECTIONS = frozenset({"east", "west", "north", "south", "right", "left", "top", "bottom"})
    if direction not in _VALID_DIRECTIONS:
        raise ValueError(
            f"direction '{direction}' is not valid. "
            f"Use one of: {sorted(_VALID_DIRECTIONS)}"
        )

    tolerance = float(params.get("tolerance", 1e-4))
    blend_weight_a = max(0.0, min(1.0, float(params.get("blend_weight_a", 0.5))))
    blend_weight_b = 1.0 - blend_weight_a

    obj_a = bpy.data.objects.get(terrain_a_name)
    obj_b = bpy.data.objects.get(terrain_b_name)
    if obj_a is None:
        raise ValueError(f"Object not found: '{terrain_a_name}'")
    if obj_b is None:
        raise ValueError(f"Object not found: '{terrain_b_name}'")
    if obj_a.type != "MESH":
        raise ValueError(
            f"'{terrain_a_name}' is type '{obj_a.type}', expected 'MESH'"
        )
    if obj_b.type != "MESH":
        raise ValueError(
            f"'{terrain_b_name}' is type '{obj_b.type}', expected 'MESH'"
        )

    # -----------------------------------------------------------------------
    # Protected zone lookup — build world-space AABB list once.
    # -----------------------------------------------------------------------
    raw_protected_zones = params.get("protected_zones") or []
    pz_aabbs: list[tuple[float, float, float, float]] = []  # (min_x, min_y, max_x, max_y)
    for pz in raw_protected_zones:
        bounds = pz.get("bounds")
        if not isinstance(bounds, dict):
            continue
        pz_aabbs.append((
            float(bounds.get("min_x", -1e18)),
            float(bounds.get("min_y", -1e18)),
            float(bounds.get("max_x",  1e18)),
            float(bounds.get("max_y",  1e18)),
        ))

    def _in_protected_zone(wx: float, wy: float) -> bool:
        for bmin_x, bmin_y, bmax_x, bmax_y in pz_aabbs:
            if bmin_x <= wx <= bmax_x and bmin_y <= wy <= bmax_y:
                return True
        return False

    def _edge_vertices(obj: Any, edge: str) -> list[tuple[float, int, float, float]]:
        """Return sorted [(axis_val, vertex_index, world_x, world_y), ...] for an edge."""
        mesh = obj.data
        n = len(mesh.vertices)
        if n == 0:
            return []
        co_flat = np.empty(n * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", co_flat)
        co = co_flat.reshape(n, 3)
        # Apply object world transform (location only — no scale/rotation assumed on terrain tiles)
        lx = float(obj.location.x) if hasattr(obj, "location") else 0.0
        ly = float(obj.location.y) if hasattr(obj, "location") else 0.0
        xs = co[:, 0] + lx
        ys = co[:, 1] + ly
        min_x, max_x = float(xs.min()), float(xs.max())
        min_y, max_y = float(ys.min()), float(ys.max())

        norm_edge = edge.lower().strip()
        if norm_edge in ("east", "right"):
            mask = np.abs(xs - max_x) <= tolerance
            axis_vals = ys
        elif norm_edge in ("west", "left"):
            mask = np.abs(xs - min_x) <= tolerance
            axis_vals = ys
        elif norm_edge in ("north", "top"):
            mask = np.abs(ys - max_y) <= tolerance
            axis_vals = xs
        elif norm_edge in ("south", "bottom"):
            mask = np.abs(ys - min_y) <= tolerance
            axis_vals = xs
        else:
            raise ValueError(f"Unrecognised edge direction '{edge}'")

        indices = np.where(mask)[0]
        result = [
            (float(axis_vals[i]), int(i), float(xs[i]), float(ys[i]))
            for i in indices
        ]
        return sorted(result, key=lambda item: item[0])

    # Resolve canonical edge names from direction
    if direction in ("east", "right"):
        edge_a, edge_b = "east", "west"
    elif direction in ("west", "left"):
        edge_a, edge_b = "west", "east"
    elif direction in ("north", "top"):
        edge_a, edge_b = "north", "south"
    else:
        edge_a, edge_b = "south", "north"

    verts_a = _edge_vertices(obj_a, edge_a)
    verts_b = _edge_vertices(obj_b, edge_b)

    if not verts_a:
        _duration = time.perf_counter() - _t0
        return {
            "status": "error",
            "message": f"No seam vertices found on '{terrain_a_name}' edge '{edge_a}'",
            "direction": direction,
            "terrain_a": terrain_a_name,
            "terrain_b": terrain_b_name,
            "matched_vertices": 0,
            "max_delta": 0.0,
            "protected_vertices_skipped": 0,
            "affected_cells": 0,
            "duration_seconds": round(time.perf_counter() - _t0, 4),
            "pass_name": "stitch_terrain_edges",
        }

    if len(verts_a) != len(verts_b):
        raise ValueError(
            f"Terrain edge vertex counts do not match: "
            f"'{terrain_a_name}' edge '{edge_a}' has {len(verts_a)} vertices, "
            f"'{terrain_b_name}' edge '{edge_b}' has {len(verts_b)} vertices. "
            "Ensure both tiles have the same resolution."
        )

    # -----------------------------------------------------------------------
    # Batch read Z values for both meshes via foreach_get.
    # -----------------------------------------------------------------------
    mesh_a = obj_a.data
    mesh_b = obj_b.data
    n_a = len(mesh_a.vertices)
    n_b = len(mesh_b.vertices)
    co_a_flat = np.empty(n_a * 3, dtype=np.float32)
    co_b_flat = np.empty(n_b * 3, dtype=np.float32)
    mesh_a.vertices.foreach_get("co", co_a_flat)
    mesh_b.vertices.foreach_get("co", co_b_flat)

    matched = 0
    max_delta = 0.0
    protected_vertices_skipped = 0

    for (_, idx_a, wx_a, wy_a), (_, idx_b, wx_b, wy_b) in zip(verts_a, verts_b):
        za = float(co_a_flat[idx_a * 3 + 2])
        zb = float(co_b_flat[idx_b * 3 + 2])
        delta = abs(za - zb)
        max_delta = max(max_delta, delta)

        # Skip if either vertex falls in a protected zone
        if _in_protected_zone(wx_a, wy_a) or _in_protected_zone(wx_b, wy_b):
            protected_vertices_skipped += 1
            continue

        blended = za * blend_weight_a + zb * blend_weight_b
        co_a_flat[idx_a * 3 + 2] = blended
        co_b_flat[idx_b * 3 + 2] = blended
        matched += 1

    # Batch write back — one foreach_set per mesh
    mesh_a.vertices.foreach_set("co", co_a_flat)
    mesh_b.vertices.foreach_set("co", co_b_flat)
    mesh_a.update()
    mesh_b.update()

    _duration = time.perf_counter() - _t0
    return {
        "status": "success",
        "terrain_a": terrain_a_name,
        "terrain_b": terrain_b_name,
        "direction": direction,
        "matched_vertices": matched,
        "max_delta": round(max_delta, 6),
        "protected_vertices_skipped": protected_vertices_skipped,
        "blend_weight_a": blend_weight_a,
        # AAA metrics
        "affected_cells": matched,
        "duration_seconds": round(_duration, 4),
        "pass_name": "stitch_terrain_edges",
    }


# ---------------------------------------------------------------------------
# Handler: paint_terrain
# ---------------------------------------------------------------------------

def handle_paint_terrain(params: dict[str, Any]) -> dict[str, Any]:
    """Auto-paint terrain with biome materials based on slope/altitude rules.

    B+ upgrade: pressure-falloff brush for soft material boundaries, multi-
    channel RGBA vertex-color layer blending (up to 4 biome channels packed
    into a single RGBA vertex-color attribute), and undo-stack support via
    Blender's mesh.update() + bpy.ops.ed.undo_push().

    The brush model works as follows:
        - Each face gets a hard material-slot assignment (unchanged behaviour).
        - Additionally, a vertex-color attribute "BiomeWeights" (RGBA) is
          written where each channel encodes the blend weight for up to 4
          biome zones. This attribute drives shader-side splatmap blending.
        - The pressure-falloff brush: faces near a biome boundary receive a
          smoothstep-blended weight rather than a hard 0/1, controlled by
          ``brush_falloff_deg`` (slope) and ``brush_falloff_alt`` (altitude).
          This matches MicroSplat's splatmap painting approach.

    Params:
        name (str): Existing terrain object name.
        biome_rules (list of dict, optional): Biome rules with name, material,
            min_alt, max_alt, min_slope, max_slope. Defaults to BIOME_RULES.
        height_range (2-item sequence, optional): Explicit altitude range.
        height_scale (float, default 20.0): Legacy Z-scale fallback.
        brush_falloff_deg (float, default 5.0): Slope width of the falloff
            zone in degrees. Faces within this margin of a slope boundary
            receive a blended weight rather than a hard assignment.
        brush_falloff_alt (float, default 0.05): Altitude-band falloff width
            in normalised [0,1] units. Same concept as brush_falloff_deg.
        write_vertex_colors (bool, default True): Write the "BiomeWeights"
            RGBA vertex-color attribute for shader-side blending.
        undo_push (bool, default False): Push an undo step after painting.
            Only works inside an interactive Blender session; silently ignored
            when called from tests or headless scripts.

    Returns dict with:
        name, material_count, biome_rules_applied,
        vertex_color_layer (name of the written attribute or None),
        faces_painted (count of faces whose material was assigned).
    """
    logger.info("Painting terrain biomes")
    _t0 = time.perf_counter()
    name = params.get("name")
    if not name:
        raise ValueError("'name' is required")

    biome_rules = params.get("biome_rules") or BIOME_RULES
    height_scale = float(params.get("height_scale", 20.0))
    brush_falloff_deg = float(params.get("brush_falloff_deg", 5.0))
    brush_falloff_alt = float(params.get("brush_falloff_alt", 0.05))
    write_vertex_colors = bool(params.get("write_vertex_colors", True))
    undo_push = bool(params.get("undo_push", False))

    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object not found: {name}")
    if obj.type != "MESH":
        raise ValueError(f"Object '{name}' is type '{obj.type}', expected 'MESH'")

    mesh = obj.data

    # Create material slots with proper Base Color from biome rules
    for rule in biome_rules:
        mat_name = rule.get("material", rule["name"])
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            mat = bpy.data.materials.new(name=mat_name)
            mat.use_nodes = True
            if mat.node_tree:
                bsdf = mat.node_tree.nodes.get("Principled BSDF")
                if bsdf:
                    base_color = rule.get("base_color")
                    if base_color:
                        bc = list(base_color)
                        while len(bc) < 4:
                            bc.append(1.0)
                        bsdf.inputs["Base Color"].default_value = tuple(bc[:4])
                    roughness = rule.get("roughness")
                    if roughness is not None:
                        bsdf.inputs["Roughness"].default_value = roughness
        mesh.materials.append(mat)

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()

    explicit_range = params.get("height_range")
    if isinstance(explicit_range, (list, tuple)) and len(explicit_range) >= 2:
        altitude_min = float(explicit_range[0])
        altitude_max = float(explicit_range[1])
    else:
        altitude_min = float(params.get("height_range_min", 0.0))
        altitude_max = float(params.get("height_range_max", 0.0))
        if altitude_max <= altitude_min:
            if bm.verts:
                z_values = [float(v.co.z) for v in bm.verts]
                altitude_min = min(z_values)
                altitude_max = max(z_values)
            else:
                altitude_min = 0.0
                altitude_max = height_scale if height_scale > 0.0 else 1.0

    centers_z = np.array([face.calc_center_median().z for face in bm.faces], dtype=np.float64)
    normals_z = np.array([face.normal.z for face in bm.faces], dtype=np.float64)

    alt_span = max(altitude_max - altitude_min, 1e-9)
    altitude_arr = np.clip((centers_z - altitude_min) / alt_span, 0.0, 1.0)
    slope_arr = np.degrees(np.arccos(np.clip(normals_z, -1.0, 1.0)))

    n_rules = len(biome_rules)
    min_alts   = np.array([r.get("min_alt",   0.0)  for r in biome_rules], dtype=np.float64)
    max_alts   = np.array([r.get("max_alt",   1.0)  for r in biome_rules], dtype=np.float64)
    min_slopes = np.array([r.get("min_slope", 0.0)  for r in biome_rules], dtype=np.float64)
    max_slopes = np.array([r.get("max_slope", 90.0) for r in biome_rules], dtype=np.float64)

    # Hard pass: (N_faces, N_rules) boolean matrix
    both_pass = (
        (altitude_arr[:, None] >= min_alts[None, :])
        & (altitude_arr[:, None] <= max_alts[None, :])
        & (slope_arr[:, None] >= min_slopes[None, :])
        & (slope_arr[:, None] <= max_slopes[None, :])
    )
    material_idx_arr = np.argmax(both_pass, axis=1).astype(np.int32)

    # ------------------------------------------------------------------
    # Pressure-falloff brush: compute per-face per-rule blend weights
    # using smoothstep inside the falloff margin at each boundary.
    # Weights are then packed into an RGBA vertex-color layer (4 channels
    # = up to 4 biome layers; additional rules share the nearest channel).
    # ------------------------------------------------------------------
    n_faces = len(bm.faces)
    blend_weights = np.zeros((n_faces, n_rules), dtype=np.float32)

    def _smoothstep_np(t: np.ndarray) -> np.ndarray:
        t = np.clip(t, 0.0, 1.0)
        return t * t * (3.0 - 2.0 * t)

    for ri in range(n_rules):
        # Altitude weight with falloff at band edges
        alt_lo_dist = altitude_arr - min_alts[ri]
        alt_hi_dist = max_alts[ri] - altitude_arr
        falloff_alt = max(brush_falloff_alt, 1e-6)
        w_alt_lo = _smoothstep_np(alt_lo_dist / falloff_alt)
        w_alt_hi = _smoothstep_np(alt_hi_dist / falloff_alt)
        w_alt = w_alt_lo * w_alt_hi

        # Slope weight with falloff at band edges
        sl_lo_dist = slope_arr - min_slopes[ri]
        sl_hi_dist = max_slopes[ri] - slope_arr
        falloff_sl = max(brush_falloff_deg, 1e-3)
        w_sl_lo = _smoothstep_np(sl_lo_dist / falloff_sl)
        w_sl_hi = _smoothstep_np(sl_hi_dist / falloff_sl)
        w_sl = w_sl_lo * w_sl_hi

        blend_weights[:, ri] = (w_alt * w_sl).astype(np.float32)

    # Normalise across rules so weights sum to 1 per face
    weight_sum = blend_weights.sum(axis=1, keepdims=True)
    weight_sum = np.where(weight_sum < 1e-9, 1.0, weight_sum)
    blend_weights /= weight_sum

    bm.to_mesh(mesh)
    bm.free()
    mesh.polygons.foreach_set("material_index", material_idx_arr)

    # ------------------------------------------------------------------
    # Write multi-channel RGBA vertex-color attribute "BiomeWeights".
    # Blender 4.x uses mesh.color_attributes (not vertex_colors).
    # We pack up to 4 rule channels into RGBA.  Rules 5+ are silently
    # mapped to the nearest of the 4 channels via argmax.
    # ------------------------------------------------------------------
    vc_layer_name: str | None = None
    if write_vertex_colors and n_faces > 0:
        try:
            _VCA = "BiomeWeights"
            # Remove stale attribute if it exists
            existing = mesh.color_attributes.get(_VCA)
            if existing is not None:
                mesh.color_attributes.remove(existing)
            ca = mesh.color_attributes.new(name=_VCA, type="FLOAT_COLOR", domain="FACE")
            # Build (N_faces, 4) RGBA array — pack first 4 channels
            rgba = np.zeros((n_faces, 4), dtype=np.float32)
            for ch in range(min(4, n_rules)):
                rgba[:, ch] = blend_weights[:, ch]
            # Flatten to (N_faces * 4,) for foreach_set
            ca.data.foreach_set("color", rgba.flatten())
            vc_layer_name = _VCA
        except Exception as exc:
            logger.debug("BiomeWeights vertex-color write failed: %s", exc)

    mesh.update()

    # Undo stack push (best-effort; silently skipped outside interactive session)
    if undo_push:
        try:
            bpy.ops.ed.undo_push(message=f"Paint Terrain: {name}")
        except Exception as exc:
            logger.warning("Optional subsystem undo_push failed (non-fatal): %s", exc)

    _duration = time.perf_counter() - _t0
    return {
        "name": obj.name,
        "material_count": len(mesh.materials),
        "biome_rules_applied": n_rules,
        "vertex_color_layer": vc_layer_name,
        "faces_painted": int(n_faces),
        # AAA metrics
        "affected_cells": int(n_faces),
        "duration_seconds": round(_duration, 4),
        "pass_name": "paint_terrain",
    }


# ---------------------------------------------------------------------------
# Handler: carve_river
# ---------------------------------------------------------------------------

def handle_carve_river(params: dict[str, Any]) -> dict[str, Any]:
    """Carve a river channel on an existing terrain mesh using D8 flow routing.

    Uses a multi-segment A* path solver through the normalized heightmap with
    world-height transform preservation. The carved channel is applied via a
    cosine-bellcurve cross-section profile (not straight-line interpolation).
    Protected zones are never written to — any path cell that falls inside a
    protected zone is skipped during mesh write-back.

    Params:
        terrain_name (str): Existing terrain object name.
        source (list of 2 ints): Start grid coordinate [row, col].
        destination (list of 2 ints): End grid coordinate [row, col].
        waypoints (list of [row, col]): Optional intermediate grid waypoints.
        width (int, default 2): Channel width in cells.
        depth (float, default 0.05): Channel depth.
        seed (int, default 0): Random seed.
        protected_zones (list of dict): Optional zone dicts with 'bounds'
            (BBox-like) that forbid terrain writes.

    Returns dict with: name, path_length, depth, path_cells, path_points,
        bed_points, waypoint_count, affected_cells, duration_seconds,
        pass_name, protected_cells_skipped.
    """
    logger.info("Carving river on terrain")
    _t0 = time.perf_counter()
    terrain_name = params.get("terrain_name")
    if not terrain_name:
        raise ValueError("'terrain_name' is required")

    source = tuple(params.get("source", [0, 0]))
    destination = tuple(params.get("destination", [0, 0]))
    waypoint_cells = [
        tuple(point[:2])
        for point in (params.get("waypoints") or [])
        if isinstance(point, (list, tuple)) and len(point) >= 2
    ]
    width = params.get("width", 2)
    depth = params.get("depth", 0.05)
    seed = params.get("seed", 0)

    # Manning-based width: if flow_accumulation is supplied, override static width.
    flow_acc = params.get("flow_accumulation")
    if flow_acc is not None:
        try:
            from ._water_network import compute_river_width
            cell_size_m = float(params.get("cell_size_m", 1.0))
            width_m = compute_river_width(float(flow_acc))
            width = max(1, int(round(width_m / cell_size_m)))
        except Exception as exc:
            logger.warning("Optional subsystem compute_river_width failed (non-fatal): %s", exc)

    obj = bpy.data.objects.get(terrain_name)
    if obj is None:
        raise ValueError(f"Object not found: {terrain_name}")

    # Extract heightmap from mesh vertex Z
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()

    # WORLD-004: Detect actual grid dimensions (robust to non-square terrain)
    rows, cols = _detect_grid_dims(bm)

    # Extract world-unit heights. Preserve signed ranges when routing through
    # the normalized A* solver to avoid corrupting negative-elevation worlds.
    heights = np.array([v.co.z for v in bm.verts], dtype=np.float64)
    heightmap = heights.reshape(rows, cols)
    transform = WorldHeightTransform(
        world_min=float(heightmap.min()) if heightmap.size else 0.0,
        world_max=float(heightmap.max()) if heightmap.size else 0.0,
    )
    height_span = max(transform.world_max - transform.world_min, 1e-6)
    normalized_depth = max(0.0, min(float(depth) / height_span, 0.45))

    routed_cells = [source, *waypoint_cells, destination]
    working_heightmap = heightmap.copy()
    full_path: list[tuple[int, int]] = []
    for segment_index, (segment_source, segment_dest) in enumerate(zip(routed_cells, routed_cells[1:])):
        segment_path, segment_carved, _ = _run_height_solver_in_world_space(
            working_heightmap,
            carve_river_path,
            source=segment_source,
            dest=segment_dest,
            width=width,
            depth=normalized_depth,
            seed=seed + segment_index,
        )
        working_heightmap = _apply_river_profile_to_heightmap(
            base_heightmap=working_heightmap,
            carved_heightmap=segment_carved,
            path=segment_path,
            width_cells=float(width),
            depth_world=float(depth),
        )
        if full_path and segment_path and segment_path[0] == full_path[-1]:
            full_path.extend(segment_path[1:])
        else:
            full_path.extend(segment_path)
    path = full_path
    carved = working_heightmap

    # -----------------------------------------------------------------------
    # Protected zone mask — cells inside any protected zone are never written.
    # -----------------------------------------------------------------------
    protected_cells_skipped = 0
    protected_zone_mask: np.ndarray | None = None
    raw_protected_zones = params.get("protected_zones") or []
    if raw_protected_zones:
        terrain_width_pz = obj.dimensions.x if obj.dimensions.x > 0 else 100.0
        terrain_height_pz = obj.dimensions.y if obj.dimensions.y > 0 else terrain_width_pz
        ox_pz = float(obj.location.x) - terrain_width_pz * 0.5
        oy_pz = float(obj.location.y) - terrain_height_pz * 0.5
        cs_x_pz = terrain_width_pz / max(cols - 1, 1)
        cs_y_pz = terrain_height_pz / max(rows - 1, 1)
        protected_zone_mask = np.zeros((rows, cols), dtype=bool)
        for pz in raw_protected_zones:
            bounds = pz.get("bounds")
            if not isinstance(bounds, dict):
                continue
            bmin_x = float(bounds.get("min_x", -1e18))
            bmin_y = float(bounds.get("min_y", -1e18))
            bmax_x = float(bounds.get("max_x",  1e18))
            bmax_y = float(bounds.get("max_y",  1e18))
            c_lo = max(0, int(math.floor((bmin_x - ox_pz) / max(cs_x_pz, 1e-9))))
            c_hi = min(cols - 1, int(math.ceil((bmax_x - ox_pz) / max(cs_x_pz, 1e-9))))
            r_lo = max(0, int(math.floor((bmin_y - oy_pz) / max(cs_y_pz, 1e-9))))
            r_hi = min(rows - 1, int(math.ceil((bmax_y - oy_pz) / max(cs_y_pz, 1e-9))))
            if c_lo <= c_hi and r_lo <= r_hi:
                protected_zone_mask[r_lo:r_hi + 1, c_lo:c_hi + 1] = True

    # Apply carved heightmap back to mesh — batch via foreach_set (no Python loop).
    # Build a copy of the original heights and overwrite only non-protected cells.
    carved_flat = carved.flatten()
    original_flat = np.array([v.co.z for v in bm.verts], dtype=np.float64)
    if protected_zone_mask is not None:
        pz_flat = protected_zone_mask.flatten()
        write_mask = ~pz_flat
        protected_cells_skipped = int(pz_flat.sum())
        carved_flat = np.where(write_mask, carved_flat, original_flat)

    affected_cells = int(np.sum(np.abs(carved_flat - original_flat) > 1e-9))

    # Write Z values back to mesh — fully vectorised, zero Python vertex loop.
    # 1. Flush bmesh to the mesh so vertex count / order is canonical.
    bm.to_mesh(mesh)
    bm.free()
    # 2. Batch-read all vertex co (x, y, z) via foreach_get — one C-speed call.
    n_verts = len(mesh.vertices)
    co_final = np.empty(n_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co_final)
    # 3. Overwrite only the Z channel (index 2, stride 3) with numpy slice — O(N) numpy op.
    n_write = min(n_verts, len(carved_flat))
    co_final[2::3][:n_write] = carved_flat[:n_write].astype(np.float32)
    # 4. Batch-write all vertex co back — one C-speed call.
    mesh.vertices.foreach_set("co", co_final)
    mesh.update()

    terrain_width = obj.dimensions.x if obj.dimensions.x > 0 else 100.0
    terrain_height = obj.dimensions.y if obj.dimensions.y > 0 else terrain_width
    terrain_origin_x = obj.location.x
    terrain_origin_y = obj.location.y
    surface_levels = _derive_river_surface_levels(
        base_heightmap=heightmap,
        carved_heightmap=carved,
        path=path,
        depth_world=float(depth),
    )
    path_points = []
    bed_points = []
    for level, (row, col) in zip(surface_levels, path):
        world_x, world_y = _terrain_grid_to_world_xy(
            row,
            col,
            rows=rows,
            cols=cols,
            terrain_width=terrain_width,
            terrain_height=terrain_height,
            terrain_origin_x=terrain_origin_x,
            terrain_origin_y=terrain_origin_y,
        )
        bed_points.append([world_x, world_y, float(carved[row, col])])
        path_points.append([world_x, world_y, float(level)])

    path_points = _smooth_river_path_points(
        [tuple(point) for point in path_points],
        enforce_monotonic_z=True,
    )
    bed_points = _smooth_river_path_points(
        [tuple(point) for point in bed_points],
        enforce_monotonic_z=False,
    )

    _duration = time.perf_counter() - _t0
    return {
        "name": terrain_name,
        "path_length": len(path),
        "depth": depth,
        "path_cells": [list(cell) for cell in path],
        "path_points": path_points,
        "bed_points": bed_points,
        "waypoint_count": len(waypoint_cells),
        # AAA metrics
        "affected_cells": affected_cells,
        "protected_cells_skipped": protected_cells_skipped,
        "duration_seconds": round(_duration, 4),
        "pass_name": "carve_river",
    }


# ---------------------------------------------------------------------------
# Road helpers
# ---------------------------------------------------------------------------

def _clamp01(value: float) -> float:
    """Clamp a scalar float to [0, 1].

    Accepts any numeric type by coercing through float(); raises TypeError
    for non-numeric inputs rather than silently returning a wrong value.
    Used throughout road/river profile math — must be zero-overhead.
    """
    return max(0.0, min(1.0, float(value)))


def _smootherstep(value: float) -> float:
    """Smootherstep C2-continuous transition (Ken Perlin / UE5 convention).

    Returns 0 for value <= 0, 1 for value >= 1, with zero first and second
    derivative at both endpoints.  Stronger S-curve than smoothstep; avoids
    the perceptible inflection that Hermite smoothstep shows in terrain blend
    zones.  Formula: 6t^5 - 15t^4 + 10t^3 (Perlin 2002).
    """
    x = _clamp01(value)
    return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)


def _point_segment_distance_2d(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> tuple[float, float]:
    """Return (distance, projection_t) from a point to a 2D segment."""
    abx = bx - ax
    aby = by - ay
    denom = abx * abx + aby * aby
    if denom <= 1e-9:
        return math.hypot(px - ax, py - ay), 0.0
    t = ((px - ax) * abx + (py - ay) * aby) / denom
    t = _clamp01(t)
    cx = ax + abx * t
    cy = ay + aby * t
    return math.hypot(px - cx, py - cy), t


def _terrain_world_xy_to_grid_rc(
    world_x: float,
    world_y: float,
    *,
    rows: int,
    cols: int,
    terrain_width: float,
    terrain_height: float,
    terrain_origin_x: float,
    terrain_origin_y: float,
) -> tuple[int, int]:
    """Inverse of ``_terrain_grid_to_world_xy`` with bounds clamping."""
    if rows < 2 or cols < 2:
        return 0, 0

    width = max(float(terrain_width), 1e-9)
    height = max(float(terrain_height), 1e-9)
    row = int(round(((float(world_y) - float(terrain_origin_y)) / height + 0.5) * (rows - 1)))
    col = int(round(((float(world_x) - float(terrain_origin_x)) / width + 0.5) * (cols - 1)))
    return (
        max(0, min(rows - 1, row)),
        max(0, min(cols - 1, col)),
    )


def _fill_grid_path_gaps(path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Insert unit grid steps so every path hop stays 8-connected."""
    if len(path) < 2:
        return [(int(r), int(c)) for r, c in path]

    filled = [(int(path[0][0]), int(path[0][1]))]
    for raw_r1, raw_c1 in path[1:]:
        r1 = int(raw_r1)
        c1 = int(raw_c1)
        while abs(r1 - filled[-1][0]) > 1 or abs(c1 - filled[-1][1]) > 1:
            r0, c0 = filled[-1]
            step_r = 0 if r1 == r0 else (1 if r1 > r0 else -1)
            step_c = 0 if c1 == c0 else (1 if c1 > c0 else -1)
            filled.append((r0 + step_r, c0 + step_c))
        if (r1, c1) != filled[-1]:
            filled.append((r1, c1))
    return filled


def _extract_road_network_centerline_points(network_result: dict[str, Any]) -> list[tuple[float, float, float]]:
    """Return an ordered world-space centreline from a road-network result."""
    points: list[tuple[float, float, float]] = []

    def _coerce_point(raw_point: Any) -> tuple[float, float, float] | None:
        if not isinstance(raw_point, (list, tuple)) or len(raw_point) < 2:
            return None
        x = float(raw_point[0])
        y = float(raw_point[1])
        z = float(raw_point[2]) if len(raw_point) >= 3 else 0.0
        if not math.isfinite(x) or not math.isfinite(y) or not math.isfinite(z):
            return None
        return (x, y, z)

    for route in network_result.get("routes", []) or []:
        raw_points = route.get("points") if isinstance(route, dict) else None
        if not raw_points:
            continue
        route_points = [
            point
            for pt in raw_points
            for point in [_coerce_point(pt)]
            if point is not None
        ]
        if not route_points:
            continue
        if points and all(math.isclose(points[-1][axis], route_points[0][axis], abs_tol=1e-6) for axis in range(3)):
            points.extend(route_points[1:])
        else:
            points.extend(route_points)

    if points:
        return points

    for raw_start, raw_end, *_rest in network_result.get("segments", []) or []:
        start = _coerce_point(raw_start)
        end = _coerce_point(raw_end)
        if start is None or end is None:
            continue
        if not points:
            points.append(start)
        elif not all(math.isclose(points[-1][axis], start[axis], abs_tol=1e-6) for axis in range(3)):
            points.append(start)
        points.append(end)
    return points


def _grid_path_from_world_centerline(
    world_points: list[tuple[float, float, float]],
    *,
    rows: int,
    cols: int,
    terrain_width: float,
    terrain_height: float,
    terrain_origin_x: float,
    terrain_origin_y: float,
) -> list[tuple[int, int]]:
    """Project a world-space centreline onto the terrain grid."""
    if not world_points:
        return []

    coarse_path: list[tuple[int, int]] = []
    for world_x, world_y, _world_z in world_points:
        rc = _terrain_world_xy_to_grid_rc(
            world_x,
            world_y,
            rows=rows,
            cols=cols,
            terrain_width=terrain_width,
            terrain_height=terrain_height,
            terrain_origin_x=terrain_origin_x,
            terrain_origin_y=terrain_origin_y,
        )
        if not coarse_path or rc != coarse_path[-1]:
            coarse_path.append(rc)
    return _fill_grid_path_gaps(coarse_path)


def _grade_road_path_in_world_space(
    heightmap: np.ndarray,
    path: list[tuple[int, int]],
    *,
    width: int,
    grade_strength: float,
    max_grade_degrees: float = 15.0,
    cell_size: float = 1.0,
) -> np.ndarray:
    """Apply the legacy road centreline grading pass in world-height space.

    After blending toward target heights, the centreline elevation is swept
    to clamp the rise/run between adjacent samples to ``tan(max_grade_degrees)``.
    A smoothing pass distributes excess rise over surrounding samples so that
    the clamp produces a ramp rather than a knife-edge.

    Parameters
    ----------
    max_grade_degrees : float
        Maximum allowable grade in degrees.  Defaults to 15 (arterial);
        use 20 for local roads.
    cell_size : float
        World-space distance between adjacent grid cells (metres).  Used
        to translate the path-sample spacing into a physical run for
        grade calculations.  Defaults to 1.0.
    """
    world_heightmap = np.asarray(heightmap, dtype=np.float64)
    if world_heightmap.ndim != 2:
        raise ValueError("heightmap must be a 2D array")

    if not path:
        return world_heightmap.copy()

    transform = WorldHeightTransform(
        world_min=float(world_heightmap.min()) if world_heightmap.size else 0.0,
        world_max=float(world_heightmap.max()) if world_heightmap.size else 0.0,
    )
    snapshot = np.clip(transform.to_normalized(world_heightmap), 0.0, 1.0)
    result = snapshot.copy()
    rows, cols = result.shape
    half_w = max(int(math.ceil(float(width) * 0.5)), 0)

    # ------------------------------------------------------------------
    # Pre-compute a max-grade-constrained centreline elevation profile
    # (operating in world-height space so the clamp is physically correct).
    # ------------------------------------------------------------------
    max_grade_rad = math.radians(max(0.0, float(max_grade_degrees)))
    max_tan = math.tan(max_grade_rad) if max_grade_rad > 0.0 else 0.0
    cs = max(float(cell_size), 1e-6)

    # Valid centreline samples + their world-height values.
    valid_idx: list[int] = []
    world_vals: list[float] = []
    for i, (r, c) in enumerate(path):
        if 0 <= r < rows and 0 <= c < cols:
            valid_idx.append(i)
            world_vals.append(float(world_heightmap[r, c]))

    clamped_world: dict[int, float] = {}
    if len(valid_idx) >= 2 and max_tan > 0.0:
        centre_arr = np.array(world_vals, dtype=np.float64)

        # Run-length between consecutive valid samples in metres.
        runs = np.empty(len(valid_idx) - 1, dtype=np.float64)
        for k in range(len(valid_idx) - 1):
            r0, c0 = path[valid_idx[k]]
            r1, c1 = path[valid_idx[k + 1]]
            runs[k] = max(math.hypot(r1 - r0, c1 - c0) * cs, 1e-6)

        # Forward + backward clamp sweep (bidirectional) so the constrained
        # profile matches from either endpoint.  Repeat until stable.
        for _sweep in range(8):
            changed = False
            # Forward sweep
            for k in range(len(centre_arr) - 1):
                dz = centre_arr[k + 1] - centre_arr[k]
                max_dz = max_tan * runs[k]
                if dz > max_dz:
                    centre_arr[k + 1] = centre_arr[k] + max_dz
                    changed = True
                elif dz < -max_dz:
                    centre_arr[k + 1] = centre_arr[k] - max_dz
                    changed = True
            # Backward sweep
            for k in range(len(centre_arr) - 2, -1, -1):
                dz = centre_arr[k + 1] - centre_arr[k]
                max_dz = max_tan * runs[k]
                if dz > max_dz:
                    centre_arr[k] = centre_arr[k + 1] - max_dz
                    changed = True
                elif dz < -max_dz:
                    centre_arr[k] = centre_arr[k + 1] + max_dz
                    changed = True
            if not changed:
                break

        # Smoothing pass (3-tap) so the clamp produces a ramp rather than
        # a knife-edge.  Interior only; endpoints preserved.
        if len(centre_arr) >= 3:
            smoothed = centre_arr.copy()
            smoothed[1:-1] = 0.25 * centre_arr[:-2] + 0.5 * centre_arr[1:-1] + 0.25 * centre_arr[2:]
            # Re-enforce the clamp after smoothing.
            for k in range(len(smoothed) - 1):
                dz = smoothed[k + 1] - smoothed[k]
                max_dz = max_tan * runs[k]
                if dz > max_dz:
                    smoothed[k + 1] = smoothed[k] + max_dz
                elif dz < -max_dz:
                    smoothed[k + 1] = smoothed[k] - max_dz
            centre_arr = smoothed

        for k, i in enumerate(valid_idx):
            clamped_world[i] = float(centre_arr[k])

    # Build per-path-sample target heights in normalised space.
    for i, (r, c) in enumerate(path):
        if not (0 <= r < rows and 0 <= c < cols):
            continue
        if i in clamped_world:
            world_h = clamped_world[i]
            # Convert world height back to normalised space for the blend.
            target_h = float(np.clip(transform.to_normalized(
                np.array([[world_h]], dtype=np.float64)
            )[0, 0], 0.0, 1.0))
        else:
            target_h = float(snapshot[r, c])

        for dr in range(-half_w, half_w + 1):
            for dc in range(-half_w, half_w + 1):
                nr = r + dr
                nc = c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    dist = math.sqrt(dr * dr + dc * dc)
                    if dist <= half_w + 0.5:
                        falloff = 1.0 - dist / (half_w + 1.0)
                        blend = float(grade_strength) * falloff
                        current = float(result[nr, nc])
                        result[nr, nc] = current * (1.0 - blend) + target_h * blend

    return transform.from_normalized(np.clip(result, 0.0, 1.0))


def _solve_road_path_with_network(
    heightmap: np.ndarray,
    waypoints: list[tuple[int, int]],
    *,
    terrain_width: float,
    terrain_height: float,
    terrain_origin_x: float,
    terrain_origin_y: float,
    cost_map: np.ndarray | None,
    seed: int,
    rdp_epsilon: float,
) -> tuple[list[tuple[int, int]], dict[str, Any]]:
    """Solve the production road route through the richer road-network path."""
    rows, cols = heightmap.shape
    world_waypoints: list[tuple[float, float, float]] = []
    for raw_row, raw_col in waypoints:
        row = max(0, min(rows - 1, int(raw_row)))
        col = max(0, min(cols - 1, int(raw_col)))
        world_x, world_y = _terrain_grid_to_world_xy(
            row,
            col,
            rows=rows,
            cols=cols,
            terrain_width=terrain_width,
            terrain_height=terrain_height,
            terrain_origin_x=terrain_origin_x,
            terrain_origin_y=terrain_origin_y,
        )
        world_waypoints.append((world_x, world_y, float(heightmap[row, col])))

    network_result = compute_road_network(
        world_waypoints,
        seed=int(seed),
        heightmap=np.asarray(heightmap, dtype=np.float64),
        cost_map=cost_map,
        use_astar=True,
        rdp_epsilon=float(rdp_epsilon),
        terrain_bounds=(
            float(terrain_origin_x) - float(terrain_width) * 0.5,
            float(terrain_origin_y) - float(terrain_height) * 0.5,
            float(terrain_origin_x) + float(terrain_width) * 0.5,
            float(terrain_origin_y) + float(terrain_height) * 0.5,
        ),
        connection_strategy="chain",
    )
    centerline = _extract_road_network_centerline_points(network_result)
    path = _grid_path_from_world_centerline(
        centerline,
        rows=rows,
        cols=cols,
        terrain_width=terrain_width,
        terrain_height=terrain_height,
        terrain_origin_x=terrain_origin_x,
        terrain_origin_y=terrain_origin_y,
    )
    if len(path) < 2:
        raise ValueError("road_network produced fewer than 2 grid path points")
    return path, network_result


def _apply_road_profile_to_heightmap(
    heightmap: np.ndarray,
    path: list[tuple[int, int]],
    *,
    width_cells: float,
    grade_strength: float,
    crown_height_m: float,
    shoulder_width_cells: float,
    ditch_depth_m: float,
    protected_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Apply a crown-and-ditch deformation profile around the solved road path.

    Args:
        protected_mask: Optional boolean array (same shape as heightmap).
            Cells where True are never written — original heights are preserved.
    """
    original = np.asarray(heightmap, dtype=np.float64)
    result = original.copy()
    if len(path) < 2:
        return result

    road_half_width = max(float(width_cells) * 0.5, 0.75)
    shoulder_width = max(float(shoulder_width_cells), 1.0)
    outer_radius = road_half_width + shoulder_width
    grade = max(0.15, min(float(grade_strength), 1.0))

    def _ss(x: np.ndarray) -> np.ndarray:
        return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)

    for (r0, c0), (r1, c1) in zip(path, path[1:]):
        center_h0 = float(result[r0, c0])
        center_h1 = float(result[r1, c1])
        r_min = max(0, int(math.floor(min(r0, r1) - outer_radius)))
        r_max = min(result.shape[0] - 1, int(math.ceil(max(r0, r1) + outer_radius)))
        c_min = max(0, int(math.floor(min(c0, c1) - outer_radius)))
        c_max = min(result.shape[1] - 1, int(math.ceil(max(c0, c1) + outer_radius)))

        rr = np.arange(r_min, r_max + 1, dtype=np.float64)[:, np.newaxis]
        cc = np.arange(c_min, c_max + 1, dtype=np.float64)[np.newaxis, :]

        abr = float(r1 - r0)
        abc = float(c1 - c0)
        denom = abr * abr + abc * abc
        if denom <= 1e-9:
            dist = np.sqrt((rr - r0) ** 2 + (cc - c0) ** 2)
            t_arr = np.zeros_like(dist)
        else:
            t_arr = np.clip(((rr - r0) * abr + (cc - c0) * abc) / denom, 0.0, 1.0)
            dist = np.sqrt(
                (rr - (r0 + abr * t_arr)) ** 2 + (cc - (c0 + abc * t_arr)) ** 2
            )

        center_height = center_h0 + (center_h1 - center_h0) * t_arr

        center_t = np.clip(dist / max(road_half_width, 1e-6), 0.0, 1.0)
        ss_c = _ss(center_t)
        target_crown = center_height + crown_height_m * (1.0 - ss_c)
        blend_crown = grade * (0.45 + 0.55 * (1.0 - ss_c))

        shoulder_t = np.clip((dist - road_half_width) / max(shoulder_width, 1e-6), 0.0, 1.0)
        target_ditch = center_height - ditch_depth_m * np.sin(shoulder_t * math.pi)
        blend_ditch = grade * 0.35 * (1.0 - _ss(shoulder_t))

        in_crown = dist <= road_half_width
        target = np.where(in_crown, target_crown, target_ditch)
        blend = np.where(in_crown, blend_crown, blend_ditch)

        patch = result[r_min : r_max + 1, c_min : c_max + 1]
        result[r_min : r_max + 1, c_min : c_max + 1] = np.where(
            dist <= outer_radius,
            patch * (1.0 - blend) + target * blend,
            patch,
        )

    # Protected zone enforcement — revert writes inside protected cells
    if protected_mask is not None and protected_mask.any():
        result = np.where(protected_mask, original, result)

    return result


def _build_road_mask_and_sdf(
    path: list[tuple[int, int]],
    *,
    shape: tuple[int, int],
    width_cells: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Build the road surface mask and road-distance field for a solved path."""
    def _fill_gaps(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
        if len(points) < 2:
            return points
        filled = [points[0]]
        for r1, c1 in points[1:]:
            while abs(r1 - filled[-1][0]) > 1 or abs(c1 - filled[-1][1]) > 1:
                r0, c0 = filled[-1]
                step_r = 0 if r1 == r0 else (1 if r1 > r0 else -1)
                step_c = 0 if c1 == c0 else (1 if c1 > c0 else -1)
                filled.append((r0 + step_r, c0 + step_c))
            filled.append((r1, c1))
        return filled

    rows, cols = shape
    road_mask = np.zeros((rows, cols), dtype=np.uint8)
    road_sdf = np.zeros((rows, cols), dtype=np.float32)
    if not path:
        return road_mask, road_sdf

    filled_path = _fill_gaps(path)
    path_arr = np.array(
        [(r, c) for r, c in filled_path if 0 <= r < rows and 0 <= c < cols],
        dtype=np.float64,
    )
    if len(path_arr) == 0:
        return road_mask, road_sdf

    rr, cc = np.mgrid[0:rows, 0:cols]
    query_pts = np.stack([rr.ravel(), cc.ravel()], axis=1).astype(np.float64)
    road_half_width = max(float(width_cells) * 0.5, 0.75)

    try:
        from scipy.ndimage import distance_transform_edt
        from scipy.spatial import KDTree as _KDTree

        tree = _KDTree(path_arr)
        dist_raw, _nearest = tree.query(query_pts, k=1)
        dist_flat = np.asarray(dist_raw, dtype=np.float64)
        dist_map = dist_flat.reshape(rows, cols)
        road_mask = (dist_map <= road_half_width).astype(np.uint8)
        road_sdf = np.asarray(
            distance_transform_edt((1 - road_mask).astype(np.uint8)),
            dtype=np.float32,
        )
        return road_mask, road_sdf
    except ImportError:
        dist_map = np.full((rows, cols), np.inf, dtype=np.float64)
        for pr, pc in path_arr:
            dist_map = np.minimum(dist_map, np.hypot(rr - pr, cc - pc))
        road_mask = (dist_map <= road_half_width).astype(np.uint8)

        road_cells = np.argwhere(road_mask > 0)
        if road_cells.size == 0:
            return road_mask, road_sdf

        road_sdf_float = np.full((rows, cols), np.inf, dtype=np.float64)
        for pr, pc in road_cells:
            road_sdf_float = np.minimum(road_sdf_float, np.hypot(rr - pr, cc - pc))
        return road_mask, road_sdf_float.astype(np.float32)


def _apply_river_profile_to_heightmap(
    *,
    base_heightmap: np.ndarray,
    carved_heightmap: np.ndarray,
    path: list[tuple[int, int]],
    width_cells: float,
    depth_world: float,
    bank_width_cells: float | None = None,
) -> np.ndarray:
    """Shape a readable channel with actual banks around the solved river path."""
    result = np.minimum(
        np.asarray(base_heightmap, dtype=np.float64),
        np.asarray(carved_heightmap, dtype=np.float64),
    ).copy()
    if len(path) < 2:
        return result

    channel_half_width = max(float(width_cells) * 0.5, 1.0)
    bank_width = max(
        float(bank_width_cells) if bank_width_cells is not None else channel_half_width * 1.85,
        2.0,
    )
    outer_radius = channel_half_width + bank_width
    center_depth = max(float(depth_world), channel_half_width * 0.55, 0.9)
    thalweg_half_width = max(channel_half_width * 0.42, 0.75)

    def _ss(x: np.ndarray) -> np.ndarray:
        return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)

    def _seg_dist(rr: np.ndarray, cc: np.ndarray, r0: int, c0: int, r1: int, c1: int):
        abr = float(r1 - r0)
        abc = float(c1 - c0)
        denom = abr * abr + abc * abc
        if denom <= 1e-9:
            return np.sqrt((rr - r0) ** 2 + (cc - c0) ** 2), np.zeros_like(rr)
        t = np.clip(((rr - r0) * abr + (cc - c0) * abc) / denom, 0.0, 1.0)
        dist = np.sqrt((rr - (r0 + abr * t)) ** 2 + (cc - (c0 + abc * t)) ** 2)
        return dist, t

    base_hmap = np.asarray(base_heightmap, dtype=np.float64)

    for (r0, c0), (r1, c1) in zip(path, path[1:]):
        bank_h0 = float(base_hmap[r0, c0])
        bank_h1 = float(base_hmap[r1, c1])
        r_min = max(0, int(math.floor(min(r0, r1) - outer_radius)))
        r_max = min(result.shape[0] - 1, int(math.ceil(max(r0, r1) + outer_radius)))
        c_min = max(0, int(math.floor(min(c0, c1) - outer_radius)))
        c_max = min(result.shape[1] - 1, int(math.ceil(max(c0, c1) + outer_radius)))

        rr = np.arange(r_min, r_max + 1, dtype=np.float64)[:, np.newaxis]
        cc = np.arange(c_min, c_max + 1, dtype=np.float64)[np.newaxis, :]
        dist, t_arr = _seg_dist(rr, cc, r0, c0, r1, c1)
        bank_height = bank_h0 + (bank_h1 - bank_h0) * t_arr

        inner_t = np.clip(dist / max(channel_half_width, 1e-6), 0.0, 1.0)
        target_inner = bank_height - center_depth * (1.0 - _ss(inner_t))
        thalweg_t = np.clip(dist / max(thalweg_half_width, 1e-6), 0.0, 1.0)
        target_inner = target_inner - np.where(
            dist <= thalweg_half_width,
            center_depth * 0.22 * (1.0 - _ss(thalweg_t)),
            0.0,
        )

        outer_t = np.clip((dist - channel_half_width) / max(bank_width, 1e-6), 0.0, 1.0)
        target_outer = bank_height - center_depth * 0.34 * (1.0 - _ss(outer_t))

        target = np.where(dist <= channel_half_width, target_inner, target_outer)
        patch = result[r_min : r_max + 1, c_min : c_max + 1]
        result[r_min : r_max + 1, c_min : c_max + 1] = np.where(
            dist <= outer_radius, np.minimum(patch, target), patch
        )

    padded = np.pad(result, 1, mode="edge")
    neighborhood_mean = (
        padded[0:-2, 0:-2]
        + padded[0:-2, 1:-1]
        + padded[0:-2, 2:]
        + padded[1:-1, 0:-2]
        + padded[1:-1, 1:-1]
        + padded[1:-1, 2:]
        + padded[2:, 0:-2]
        + padded[2:, 1:-1]
        + padded[2:, 2:]
    ) / 9.0
    thalweg_inner = channel_half_width * 0.42
    smooth_denom = max(outer_radius - thalweg_inner, 1e-6)
    for (r0, c0), (r1, c1) in zip(path, path[1:]):
        r_min = max(0, int(math.floor(min(r0, r1) - outer_radius)))
        r_max = min(result.shape[0] - 1, int(math.ceil(max(r0, r1) + outer_radius)))
        c_min = max(0, int(math.floor(min(c0, c1) - outer_radius)))
        c_max = min(result.shape[1] - 1, int(math.ceil(max(c0, c1) + outer_radius)))

        rr = np.arange(r_min, r_max + 1, dtype=np.float64)[:, np.newaxis]
        cc = np.arange(c_min, c_max + 1, dtype=np.float64)[np.newaxis, :]
        dist, _ = _seg_dist(rr, cc, r0, c0, r1, c1)

        bank_t = np.clip((dist - thalweg_inner) / smooth_denom, 0.0, 1.0)
        smooth_weight = 0.10 + 0.22 * (1.0 - _ss(bank_t))
        active = (dist <= outer_radius) & (dist > thalweg_inner)

        patch = result[r_min : r_max + 1, c_min : c_max + 1]
        nm = neighborhood_mean[r_min : r_max + 1, c_min : c_max + 1]
        result[r_min : r_max + 1, c_min : c_max + 1] = np.where(
            active,
            patch * (1.0 - smooth_weight) + nm * smooth_weight,
            patch,
        )

    return result


def _derive_river_surface_levels(
    *,
    base_heightmap: np.ndarray,
    carved_heightmap: np.ndarray,
    path: list[tuple[int, int]],
    depth_world: float,
) -> list[float]:
    """Return a monotonic downhill water-surface profile for a carved river."""
    if not path:
        return []

    minimum_cover = max(float(depth_world) * 0.42, 0.12)
    candidates = []
    for row, col in path:
        base_height = float(base_heightmap[row, col])
        bed_height = float(carved_heightmap[row, col])
        channel_depth = max(base_height - bed_height, 0.0)
        surface_height = bed_height + max(channel_depth * 0.72, minimum_cover)
        candidates.append(surface_height)

    levels = list(candidates)
    min_drop_per_step = max(float(depth_world) * 0.004, 0.001)
    max_drop_per_step = max(0.45, min(float(depth_world) * 0.18, 1.2))
    for idx in range(1, len(levels)):
        max_allowed = levels[idx - 1] - min_drop_per_step
        min_allowed = levels[idx - 1] - max_drop_per_step
        levels[idx] = min(levels[idx], max_allowed)
        levels[idx] = max(levels[idx], min_allowed)

    return levels


def _carve_river_banks_into_terrain(
    *,
    terrain_obj: Any,
    path_points: list[tuple[float, float, float]],
    width_world: float,
    depth_world: float | None = None,
    bank_width_world: float | None = None,
) -> dict[str, Any]:
    """Carve a path-based river bed into the terrain mesh before adding water.

    This is the authoring bridge that prevents ``handle_create_water`` from
    producing a glass sheet over untouched terrain. It maps the world-space
    river path to the regular terrain grid, applies the existing banked river
    profile, and writes the lowered bed back to the terrain mesh.
    """
    mesh = getattr(terrain_obj, "data", None)
    vertices = list(getattr(mesh, "vertices", []) or [])
    if len(vertices) < 4 or len(path_points) < 2:
        return {"terrain_carved": False, "terrain_carve_reason": "insufficient_geometry"}

    rows, cols = _detect_grid_dims_from_vertices(vertices)
    if rows < 2 or cols < 2 or rows * cols != len(vertices):
        return {"terrain_carved": False, "terrain_carve_reason": "non_grid_terrain"}

    dims = getattr(terrain_obj, "dimensions", None)
    loc = getattr(terrain_obj, "location", None)
    try:
        terrain_width = max(float(getattr(dims, "x")), 1e-6)
        terrain_height = max(float(getattr(dims, "y")), 1e-6)
        origin_x = float(getattr(loc, "x", 0.0))
        origin_y = float(getattr(loc, "y", 0.0))
    except (TypeError, ValueError):
        return {"terrain_carved": False, "terrain_carve_reason": "invalid_transform"}

    col_scale = (cols - 1) / terrain_width
    row_scale = (rows - 1) / terrain_height
    min_x = origin_x - terrain_width * 0.5
    min_y = origin_y - terrain_height * 0.5
    path_rc: list[tuple[int, int]] = []
    for wx, wy, _wz in path_points:
        col = int(round((float(wx) - min_x) * col_scale))
        row = int(round((float(wy) - min_y) * row_scale))
        row = max(0, min(rows - 1, row))
        col = max(0, min(cols - 1, col))
        if not path_rc or path_rc[-1] != (row, col):
            path_rc.append((row, col))

    if len(path_rc) < 2:
        return {"terrain_carved": False, "terrain_carve_reason": "path_collapsed_to_one_cell"}

    cell_size = max((terrain_width / max(cols - 1, 1) + terrain_height / max(rows - 1, 1)) * 0.5, 1e-6)
    width_cells = max(float(width_world) / cell_size, 2.0)
    bank_width_cells = (
        max(float(bank_width_world) / cell_size, 1.5)
        if bank_width_world is not None
        else None
    )
    carve_depth = max(
        float(depth_world) if depth_world is not None else float(width_world) * 0.32,
        0.65,
    )
    base_heightmap = np.asarray([float(v.co.z) for v in vertices], dtype=np.float64).reshape(rows, cols)
    carved = _apply_river_profile_to_heightmap(
        base_heightmap=base_heightmap,
        carved_heightmap=base_heightmap,
        path=path_rc,
        width_cells=width_cells,
        depth_world=carve_depth,
        bank_width_cells=bank_width_cells,
    )
    delta = base_heightmap - carved
    affected = int(np.count_nonzero(np.abs(delta) > 1e-5))
    if affected <= 0:
        return {"terrain_carved": False, "terrain_carve_reason": "no_height_change"}

    flat = carved.reshape(-1)
    for idx, vert in enumerate(vertices):
        vert.co.z = float(flat[idx])
    if mesh is not None and hasattr(mesh, "update"):
        mesh.update()

    return {
        "terrain_carved": True,
        "terrain_carve_affected_cells": affected,
        "terrain_carve_depth": carve_depth,
        "terrain_carve_width_cells": width_cells,
    }


def _sample_path_indices(
    path: list[tuple[int, int]],
    *,
    min_spacing_cells: float,
    forced_indices: set[int] | None = None,
) -> list[int]:
    """Down-sample a dense grid path while preserving mandatory boundary indices."""
    if len(path) <= 2:
        return list(range(len(path)))

    forced = set(forced_indices or set())
    forced.update({0, len(path) - 1})
    sampled = [0]
    last_r, last_c = path[0]
    for idx in range(1, len(path) - 1):
        r, c = path[idx]
        if idx in forced or math.hypot(r - last_r, c - last_c) >= max(min_spacing_cells, 1.0):
            if sampled[-1] != idx:
                sampled.append(idx)
                last_r, last_c = r, c
    if sampled[-1] != len(path) - 1:
        sampled.append(len(path) - 1)
    return sampled


def _collect_bridge_spans(
    path: list[tuple[int, int]],
    *,
    base_heightmap: np.ndarray,
    graded_heightmap: np.ndarray,
    water_level: float | None,
    width_m: float,
    rows: int,
    cols: int,
    terrain_width: float,
    terrain_height: float,
    terrain_origin_x: float,
    terrain_origin_y: float,
) -> list[dict[str, Any]]:
    """Return bridge span descriptors for contiguous over-water road sections."""
    if water_level is None or len(path) < 2:
        return []

    spans: list[dict[str, Any]] = []
    start_idx: int | None = None
    end_idx: int | None = None
    for idx, (row, col) in enumerate(path):
        if float(base_heightmap[row, col]) < float(water_level):
            if start_idx is None:
                start_idx = idx
            end_idx = idx
        elif start_idx is not None and end_idx is not None:
            spans.append({"start_index": start_idx, "end_index": end_idx})
            start_idx = None
            end_idx = None
    if start_idx is not None and end_idx is not None:
        spans.append({"start_index": start_idx, "end_index": end_idx})

    resolved: list[dict[str, Any]] = []
    for span in spans:
        start_index = max(0, span["start_index"] - 1)
        end_index = min(len(path) - 1, span["end_index"] + 1)
        if end_index <= start_index:
            continue
        r0, c0 = path[start_index]
        r1, c1 = path[end_index]
        x0, y0 = _terrain_grid_to_world_xy(
            r0,
            c0,
            rows=rows,
            cols=cols,
            terrain_width=terrain_width,
            terrain_height=terrain_height,
            terrain_origin_x=terrain_origin_x,
            terrain_origin_y=terrain_origin_y,
        )
        x1, y1 = _terrain_grid_to_world_xy(
            r1,
            c1,
            rows=rows,
            cols=cols,
            terrain_width=terrain_width,
            terrain_height=terrain_height,
            terrain_origin_x=terrain_origin_x,
            terrain_origin_y=terrain_origin_y,
        )
        deck_z = max(
            float(water_level),
            float(graded_heightmap[r0, c0]),
            float(graded_heightmap[r1, c1]),
        )
        max_water_depth_m = 0.0
        for sample_index in range(start_index, end_index + 1):
            sr, sc = path[sample_index]
            max_water_depth_m = max(
                max_water_depth_m,
                float(water_level) - float(base_heightmap[sr, sc]),
            )
        clearance = max(0.75, 0.22 + max(width_m, 0.0) * 0.05, max_water_depth_m * 0.5)
        deck_z += clearance
        span_length = math.hypot(x1 - x0, y1 - y0)
        style = "rope" if width_m <= 2.5 and span_length >= 8.0 else "stone_arch"
        resolved.append(
            {
                "start_index": start_index,
                "end_index": end_index,
                "style": style,
                "material_key": "plank_floor" if style == "rope" else "cobblestone_floor",
                "start_pos": (x0, y0, deck_z),
                "end_pos": (x1, y1, deck_z),
                "clearance": clearance,
                "water_depth_m": max(0.0, max_water_depth_m),
            }
        )
    return resolved


def _build_generated_road_path_contract(
    *,
    terrain_name: str,
    full_path_world: list[tuple[float, float, float]],
    bridge_spans: list[dict[str, Any]],
    terrain_bounds: tuple[float, float, float, float],
    surface_key: str,
    road_width_m: float,
    max_grade_degrees: float,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Build an AI-readable path/road/bridge contract for env_generate_road."""
    max_grade = math.tan(math.radians(float(max_grade_degrees)))
    segment_type = "path" if str(surface_key).lower() in {"trail", "path", "dirt_path", "dirt"} else "road"
    segments: list[PathSegmentContract] = []
    if len(full_path_world) >= 2:
        points = tuple(
            (float(x), float(y), float(z))
            for x, y, z in full_path_world
        )
        min_x, min_y, max_x, max_y = terrain_bounds
        edge_tolerance = max(1.0, min(max_x - min_x, max_y - min_y) * 0.02)
        segments.append(
            PathSegmentContract(
                segment_id="route_0",
                segment_type=segment_type,  # type: ignore[arg-type]
                points=points,
                width_m=float(road_width_m),
                material_stack=material_stack_for_path(surface_key),
                continuation_edge=infer_continuation_edge(
                    points,
                    terrain_bounds,
                    tolerance_m=edge_tolerance,
                ),
                max_grade=max_grade,
                metadata={"surface": surface_key, "terrain_name": terrain_name},
            )
        )

        for bridge_index, span in enumerate(bridge_spans):
            bridge_points = (
                tuple(float(v) for v in span["start_pos"]),
                tuple(float(v) for v in span["end_pos"]),
            )
            bridge_span_m = math.dist(bridge_points[0], bridge_points[1])
            segments.append(
                PathSegmentContract(
                    segment_id=f"bridge_{bridge_index}",
                    segment_type="bridge",
                    points=bridge_points,  # type: ignore[arg-type]
                    width_m=max(float(road_width_m) * 0.92, 1.25),
                    material_stack=material_stack_for_path(
                        str(span.get("style", surface_key)),
                        bridge=True,
                    ),
                    continuation_edge=infer_continuation_edge(
                        bridge_points,  # type: ignore[arg-type]
                        terrain_bounds,
                        tolerance_m=edge_tolerance,
                    ),
                    crosses_water=True,
                    water_depth_m=float(span.get("water_depth_m", 0.0)),
                    bridge_required=True,
                    bridge_span_m=bridge_span_m,
                    bridge_clearance_m=float(span.get("clearance", 0.75)),
                    max_grade=max_grade,
                    metadata={
                        "surface": surface_key,
                        "style": str(span.get("style", "")),
                        "material_key": str(span.get("material_key", "")),
                    },
                )
            )

    network = PathNetworkContract(
        node_id=str(terrain_name),
        segments=tuple(segments),
    )
    return network.to_dict(), validate_path_network_contract(network)


def _ensure_grounded_road_material(material_name: str, road_material_key: str) -> Any:
    """Return a simple non-speckled road material suited for terrain review."""
    mat = bpy.data.materials.get(material_name)
    if mat is None:
        mat = bpy.data.materials.new(name=material_name)
    mat.use_nodes = True
    if hasattr(mat, "blend_method"):
        mat.blend_method = "OPAQUE"
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "OPAQUE"

    presets = {
        "mud": {
            "base_color": (0.11, 0.08, 0.06, 1.0),
            "roughness": 0.58,
            "specular": 0.42,
            "bump_strength": 0.014,
            "noise_scale": 2.8,
        },
        "trail": {
            "base_color": (0.13, 0.11, 0.09, 1.0),
            "roughness": 0.94,
            "specular": 0.03,
            "bump_strength": 0.0,
            "noise_scale": 0.0,
        },
        "dirt": {
            "base_color": (0.16, 0.13, 0.10, 1.0),
            "roughness": 0.91,
            "specular": 0.06,
            "bump_strength": 0.0,
            "noise_scale": 0.0,
        },
    }
    preset = presets.get(road_material_key, presets["dirt"])

    if mat.node_tree:
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        output = nodes.new("ShaderNodeOutputMaterial")
        output.location = (320, 0)
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (80, 0)
        links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

        base_color = bsdf.inputs.get("Base Color")
        if base_color is not None:
            base_color.default_value = preset["base_color"]
        roughness = bsdf.inputs.get("Roughness")
        if roughness is not None:
            roughness.default_value = preset["roughness"]
        specular = bsdf.inputs.get("Specular IOR Level") or bsdf.inputs.get("Specular")
        if specular is not None:
            specular.default_value = preset["specular"]

        noise_raw = preset.get("noise_scale", 0.0)
        bump_raw = preset.get("bump_strength", 0.0)
        noise_scale = float(noise_raw) if isinstance(noise_raw, (int, float)) else 0.0
        bump_strength = float(bump_raw) if isinstance(bump_raw, (int, float)) else 0.0
        if noise_scale > 0.0 and bump_strength > 0.0:
            texcoord = nodes.new("ShaderNodeTexCoord")
            texcoord.location = (-760, -120)
            mapping = nodes.new("ShaderNodeMapping")
            mapping.location = (-560, -120)
            mapping.inputs["Scale"].default_value = (0.9, 3.2, 1.0)
            links.new(texcoord.outputs["Object"], mapping.inputs["Vector"])

            noise = nodes.new("ShaderNodeTexNoise")
            noise.location = (-340, -120)
            noise.inputs["Scale"].default_value = preset["noise_scale"]
            noise.inputs["Detail"].default_value = 0.65
            noise.inputs["Roughness"].default_value = 0.18
            links.new(mapping.outputs["Vector"], noise.inputs["Vector"])

            bump = nodes.new("ShaderNodeBump")
            bump.location = (-100, -140)
            bump.inputs["Strength"].default_value = preset["bump_strength"]
            bump.inputs["Distance"].default_value = 0.01
            links.new(noise.outputs["Fac"], bump.inputs["Height"])
            normal_input = bsdf.inputs.get("Normal")
            if normal_input is not None:
                links.new(bump.outputs["Normal"], normal_input)

    return mat


def _paint_road_mask_on_terrain(
    terrain_obj: Any,
    path_world: list[tuple[float, float, float]],
    *,
    road_half_width: float,
    shoulder_width: float,
    surface_key: str = "dirt",
) -> None:
    """Paint the canonical terrain splatmap layer so roads read in preview/export."""
    mesh = getattr(terrain_obj, "data", None)
    if mesh is None or not hasattr(mesh, "loops") or not hasattr(mesh, "vertices"):
        return

    layer_name = "VB_TerrainSplatmap"
    attr = mesh.color_attributes.get(layer_name)
    created_attr = False
    if attr is None:
        attr = mesh.color_attributes.new(name=layer_name, type="FLOAT_COLOR", domain="CORNER")
        created_attr = True

    if attr is None or len(path_world) < 2:
        return

    total_radius = max(road_half_width + shoulder_width, 1e-6)
    surface = str(surface_key or "dirt").strip().lower()
    target_palette = {
        "trail": (0.90, 0.07, 0.02, 0.01),
        "path": (0.90, 0.07, 0.02, 0.01),
        "dirt": (0.86, 0.10, 0.03, 0.01),
        "dirt_path": (0.88, 0.08, 0.03, 0.01),
        "mud": (0.34, 0.10, 0.01, 0.55),
        "muddy": (0.34, 0.10, 0.01, 0.55),
        "gravel": (0.26, 0.54, 0.14, 0.06),
        "stone": (0.22, 0.58, 0.16, 0.04),
        "cobblestone_floor": (0.20, 0.60, 0.16, 0.04),
        "cobblestone": (0.20, 0.60, 0.16, 0.04),
    }
    target_color = np.asarray(target_palette.get(surface, target_palette["dirt"]), dtype=np.float32)
    matrix_world = getattr(terrain_obj, "matrix_world", None)

    n_loops = len(attr.data)
    n_verts = len(mesh.vertices)

    # Batch-read all vertex local positions.
    vco_flat = np.empty(n_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", vco_flat)
    vco_local = vco_flat.reshape(n_verts, 3).astype(np.float64)

    if matrix_world is not None:
        try:
            mat = np.array(
                [[matrix_world[r][c] for c in range(4)] for r in range(4)], dtype=np.float64
            )
            vco_world = (vco_local @ mat[:3, :3].T) + mat[:3, 3]
        except Exception:
            vco_world = vco_local
    else:
        vco_world = vco_local

    # Vectorized min distance from N points to any path segment.
    seg_a = np.array([[p[0], p[1]] for p in path_world[:-1]], dtype=np.float64)
    seg_b = np.array([[p[0], p[1]] for p in path_world[1:]], dtype=np.float64)
    ab = seg_b - seg_a
    ab_sq = np.maximum((ab * ab).sum(axis=1), 1e-12)

    def _min_dist_to_path(px: np.ndarray, py: np.ndarray) -> np.ndarray:
        t = (
            (px[:, None] - seg_a[None, :, 0]) * ab[None, :, 0]
            + (py[:, None] - seg_a[None, :, 1]) * ab[None, :, 1]
        ) / ab_sq[None, :]
        t = np.clip(t, 0.0, 1.0)
        cpx = seg_a[None, :, 0] + t * ab[None, :, 0]
        cpy = seg_a[None, :, 1] + t * ab[None, :, 1]
        dx = px[:, None] - cpx
        dy = py[:, None] - cpy
        return np.sqrt((dx * dx + dy * dy).min(axis=1))

    def _ss(x: np.ndarray) -> np.ndarray:
        return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)

    # Per-loop world positions (for both distance passes).
    loop_vi = np.empty(n_loops, dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loop_vi)
    lx = vco_world[loop_vi, 0]
    ly = vco_world[loop_vi, 1]
    loop_min_dists = _min_dist_to_path(lx, ly)

    # Polygon centers via reduceat over contiguous loop positions.
    polygons = getattr(mesh, "polygons", None)
    if polygons and len(polygons) > 0:
        poly_ls = np.empty(len(polygons), dtype=np.int32)
        poly_lt = np.empty(len(polygons), dtype=np.int32)
        polygons.foreach_get("loop_start", poly_ls)
        polygons.foreach_get("loop_total", poly_lt)
        poly_cx = np.add.reduceat(lx, poly_ls) / poly_lt.astype(np.float64)
        poly_cy = np.add.reduceat(ly, poly_ls) / poly_lt.astype(np.float64)
        poly_min_dists = _min_dist_to_path(poly_cx, poly_cy)
    else:
        poly_ls = poly_lt = np.empty(0, dtype=np.int32)
        poly_min_dists = np.empty(0, dtype=np.float64)

    # Batch-read existing loop colors (zeros if freshly created attribute).
    colors_flat = np.zeros(n_loops * 4, dtype=np.float32)
    if not created_attr:
        attr.data.foreach_get("color", colors_flat)
    colors = colors_flat.reshape(n_loops, 4)

    def _apply_blend_vec(loop_indices: np.ndarray, masks: np.ndarray) -> None:
        if len(loop_indices) == 0:
            return
        m = masks.astype(np.float32)[:, None]
        cur = colors[loop_indices].copy()
        bad = ~np.isfinite(cur).all(axis=1) | (cur.sum(axis=1) <= 1e-6)
        cur[bad] = 0.0
        mixed = cur * (1.0 - m) + target_color[None, :] * m
        totals = mixed.sum(axis=1, keepdims=True)
        mixed = np.where(totals > 1e-6, mixed / np.where(totals > 1e-6, totals, 1.0), mixed)
        colors[loop_indices] = mixed.astype(np.float32)

    # Polygon pass: blend per-polygon mask into all loops of each active polygon.
    for pi in range(len(poly_min_dists)):
        md = float(poly_min_dists[pi])
        if md > total_radius * 1.12:
            continue
        t_v = float(np.clip(md / max(total_radius * 1.08, 1e-6), 0.0, 1.0))
        pm = float(1.0 - _ss(np.array([t_v], dtype=np.float32))[0])
        if pm <= 0.0:
            continue
        s = int(poly_ls[pi])
        cnt = int(poly_lt[pi])
        _apply_blend_vec(np.arange(s, s + cnt, dtype=np.int32), np.full(cnt, pm * 0.78, dtype=np.float32))

    # Per-loop pass: blend per-loop vertex distance.
    act = loop_min_dists <= total_radius
    if act.any():
        act_idx = np.where(act)[0].astype(np.int32)
        t_vals = np.clip(loop_min_dists[act_idx] / max(total_radius, 1e-6), 0.0, 1.0).astype(np.float32)
        _apply_blend_vec(act_idx, 1.0 - _ss(t_vals))

    attr.data.foreach_set("color", colors_flat)


def _road_clothoid_ease(t: float) -> float:
    """Euler-spiral (clothoid) width easing over the first/last 20% of a segment.

    A clothoid transition provides smooth curvature change from straight to curved
    sections — the same math used in real road engineering (AASHTO Green Book) and
    reproduced in UE5 Landmass road tool.  Within the easing zone the effective
    half-width is scaled by a smootherstep so the road cross-section narrows to 0
    at its endpoints and reaches full width at the 20% mark.  This avoids the
    abrupt edge-line kink that linear interpolation produces at each A* waypoint.

    Args:
        t: Normalised position along the segment [0, 1].

    Returns:
        Width scale factor in [0, 1].  1.0 in the middle 60 %, smootherstep
        transition in the outer 20 % zones on each end.
    """
    _EASE_ZONE = 0.20  # 20 % easing at each end (AASHTO transition-curve standard)
    if t <= _EASE_ZONE:
        s = t / _EASE_ZONE  # remap [0, EASE_ZONE] -> [0, 1]
    elif t >= 1.0 - _EASE_ZONE:
        s = (1.0 - t) / _EASE_ZONE  # remap [1-EASE_ZONE, 1] -> [1, 0]
    else:
        return 1.0
    # Smootherstep C2-continuous (Perlin 2002): 6s^5 - 15s^4 + 10s^3
    s = max(0.0, min(1.0, s))
    return s * s * s * (s * (s * 6.0 - 15.0) + 10.0)


def _build_road_strip_geometry(
    points: list[tuple[float, float, float]],
    *,
    half_width: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int, int]]]:
    """Build a road strip with Euler-spiral (clothoid) easing at segment ends.

    Each cross-section's half-width is modulated by a smootherstep over the
    first and last 20 % of the strip so curvature transitions gracefully
    rather than kinking at waypoints — matching real road engineering practice
    (AASHTO Green Book transition-curve standard) and UE5 Landmass behaviour.
    """
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    n = len(points)
    if n < 2:
        return vertices, faces

    total_len = 0.0
    seg_lengths: list[float] = [0.0]
    for i in range(1, n):
        dl = math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
        total_len += dl
        seg_lengths.append(total_len)

    for idx, (px, py, pz) in enumerate(points):
        if idx == 0:
            dx = points[1][0] - px
            dy = points[1][1] - py
        elif idx == n - 1:
            dx = px - points[idx - 1][0]
            dy = py - points[idx - 1][1]
        else:
            dx = points[idx + 1][0] - points[idx - 1][0]
            dy = points[idx + 1][1] - points[idx - 1][1]
        seg_len = max(math.hypot(dx, dy), 1e-6)

        # Clothoid easing: normalised arc position along the full strip
        t = seg_lengths[idx] / max(total_len, 1e-9)
        ease = _road_clothoid_ease(t)
        hw = half_width * ease

        nx = -dy / seg_len * hw
        ny = dx / seg_len * hw
        vertices.append((px + nx, py + ny, pz))
        vertices.append((px - nx, py - ny, pz))
        if idx > 0:
            base = idx * 2
            faces.append((base - 2, base - 1, base + 1, base))
    return vertices, faces


def _create_bridge_object_from_spec(
    spec: dict[str, Any],
    *,
    object_name: str,
    parent: Any | None,
    material_key: str,
) -> Any | None:
    """Materialize a bridge mesh spec into Blender and assign a lightweight material."""
    mesh_data = bpy.data.meshes.new(object_name)
    mesh_data.from_pydata(spec.get("vertices", []), [], spec.get("faces", []))
    mesh_data.update()
    obj = bpy.data.objects.new(object_name, mesh_data)
    bpy.context.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
        mpi = getattr(obj, "matrix_parent_inverse", None)
        if mpi is not None and hasattr(parent, "matrix_world"):
            try:
                obj.matrix_parent_inverse = parent.matrix_world.inverted()
            except Exception:
                if hasattr(mpi, "identity"):
                    mpi.identity()

    from .procedural_materials import create_procedural_material

    try:
        mat = create_procedural_material(object_name, material_key)
        if mat is not None:
            mesh_data.materials.append(mat)
    except Exception as exc:
        logger.warning("Optional subsystem create_procedural_material failed (non-fatal): %s", exc)
    return obj


def _create_mesh_object_from_spec(
    spec: dict[str, Any],
    *,
    object_name: str,
    location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    parent: Any | None = None,
    material_key: str | None = None,
) -> Any | None:
    """Materialize a generic MeshSpec into Blender for terrain hero features."""
    from ._mesh_bridge import mesh_from_spec
    from .procedural_materials import create_procedural_material

    obj = mesh_from_spec(
        spec,
        name=object_name,
        location=location,
        rotation=rotation,
        parent=parent,
    )
    if obj is None or isinstance(obj, dict):
        return obj

    if material_key:
        try:
            mat = create_procedural_material(object_name, material_key)
            if mat is not None and hasattr(obj.data, "materials"):
                obj.data.materials.clear()
                obj.data.materials.append(mat)
        except Exception as exc:
            logger.warning("Optional subsystem create_procedural_material failed (non-fatal): %s", exc)
    return obj


def _sanitize_waterfall_chain_id(raw_value: Any) -> str:
    """Return a stable lowercase chain id suitable for WF_<chain>_<suffix> names."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(raw_value or "").strip().lower()).strip("_")
    return cleaned or "waterfall"


def _serialize_validation_issues(issues: list[Any]) -> list[dict[str, Any]]:
    """Convert ValidationIssue-like objects into plain dicts for handler results."""
    serialized: list[dict[str, Any]] = []
    for issue in issues:
        serialized.append(
            {
                "code": str(getattr(issue, "code", "")),
                "severity": str(getattr(issue, "severity", "")),
                "location": list(getattr(issue, "location", ()) or ()),
                "affected_feature": getattr(issue, "affected_feature", None),
                "message": str(getattr(issue, "message", "")),
                "remediation": getattr(issue, "remediation", None),
            }
        )
    return serialized


def _coerce_point3(raw_value: Any, fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    """Coerce a point-like value into XYZ floats, falling back when invalid."""
    if isinstance(raw_value, (list, tuple)) and len(raw_value) >= 3:
        try:
            return (
                float(raw_value[0]),
                float(raw_value[1]),
                float(raw_value[2]),
            )
        except (TypeError, ValueError):
            pass
    return fallback


def _offset_point3(
    point: tuple[float, float, float],
    offset: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Translate a local XYZ point by a world-space offset."""
    return (
        float(point[0]) + float(offset[0]),
        float(point[1]) + float(offset[1]),
        float(point[2]) + float(offset[2]),
    )


def _resolve_waterfall_chain_id(
    result: dict[str, Any],
    *,
    object_name: Any,
    fallback_location: tuple[float, float, float],
) -> str:
    """Derive a deterministic chain id from runtime waterfall data."""
    feature = result.get("waterfall_feature")
    if isinstance(feature, dict):
        explicit_chain = feature.get("chain_id")
        if explicit_chain:
            return _sanitize_waterfall_chain_id(explicit_chain)
        top = feature.get("top")
        if isinstance(top, (list, tuple)) and len(top) >= 2:
            return _sanitize_waterfall_chain_id(
                f"{int(float(top[0]) * 100)}_{int(float(top[1]) * 100)}"
            )
    if object_name:
        return _sanitize_waterfall_chain_id(object_name)
    return _sanitize_waterfall_chain_id(
        f"{int(float(fallback_location[0]) * 100)}_"
        f"{int(float(fallback_location[1]) * 100)}_"
        f"{int(float(fallback_location[2]) * 100)}"
    )


def _infer_waterfall_functional_positions(
    result: dict[str, Any],
    *,
    origin: tuple[float, float, float],
) -> dict[str, list[float]]:
    """Infer stable world-space anchors for the 7 functional waterfall objects."""
    dims_raw = result.get("dimensions", {})
    dims = dims_raw if isinstance(dims_raw, dict) else {}
    height = max(float(dims.get("height", 1.0)), 1.0)

    feature = result.get("waterfall_feature")
    feature_top = feature.get("top") if isinstance(feature, dict) else None
    feature_bottom = feature.get("bottom") if isinstance(feature, dict) else None
    top = _coerce_point3(feature_top, (origin[0], origin[1], origin[2] + height))
    bottom = _coerce_point3(feature_bottom, origin)

    pool_info_raw = result.get("pool", {})
    pool_info = pool_info_raw if isinstance(pool_info_raw, dict) else {}
    pool_center = _offset_point3(
        _coerce_point3(pool_info.get("center"), (0.0, 0.0, 0.0)),
        origin,
    )
    splash_zone_raw = result.get("splash_zone", {})
    splash_zone = splash_zone_raw if isinstance(splash_zone_raw, dict) else {}
    splash_center = _offset_point3(
        _coerce_point3(splash_zone.get("center"), pool_center),
        origin,
    )

    if feature_bottom is not None:
        pool_center = bottom
        splash_center = bottom

    mid_point = (
        (top[0] + bottom[0]) * 0.5,
        (top[1] + bottom[1]) * 0.5,
        (top[2] + bottom[2]) * 0.5,
    )
    wet_rock_center = (
        (mid_point[0] + pool_center[0]) * 0.5,
        (mid_point[1] + pool_center[1]) * 0.5,
        (mid_point[2] + pool_center[2]) * 0.5,
    )

    return {
        "river_surface": [float(top[0]), float(top[1]), float(top[2])],
        "sheet_volume": [float(mid_point[0]), float(mid_point[1]), float(mid_point[2])],
        "impact_pool": [float(pool_center[0]), float(pool_center[1]), float(pool_center[2])],
        "foam_layer": [float(splash_center[0]), float(splash_center[1]), float(splash_center[2])],
        "mist_volume": [
            float(splash_center[0]),
            float(splash_center[1]),
            float(splash_center[2] + max(height * 0.08, 0.75)),
        ],
        "splash_particles": [
            float(pool_center[0]),
            float(pool_center[1]),
            float(pool_center[2] + max(height * 0.04, 0.35)),
        ],
        "wet_rock_material_zone": [
            float(wet_rock_center[0]),
            float(wet_rock_center[1]),
            float(wet_rock_center[2]),
        ],
    }


def _publish_waterfall_functional_objects(
    object_names: dict[str, str],
    *,
    positions: dict[str, list[float]],
    parent: Any | None,
    render_object_name: str | None,
) -> list[str]:
    """Materialize named waterfall anchors as empties for downstream lookup."""
    if bpy is None:
        return []

    created: list[str] = []
    collection = bpy.context.collection
    if parent is not None:
        user_collections = getattr(parent, "users_collection", None)
        if user_collections:
            collection = user_collections[0]

    for role, object_name in object_names.items():
        anchor = bpy.data.objects.get(object_name)
        if anchor is None:
            anchor = bpy.data.objects.new(object_name, None)
            collection.objects.link(anchor)
        if hasattr(anchor, "empty_display_type"):
            anchor.empty_display_type = "PLAIN_AXES"
        if hasattr(anchor, "empty_display_size"):
            anchor.empty_display_size = 0.45 if role == "sheet_volume" else 0.30
        anchor.location = tuple(float(v) for v in positions.get(role, (0.0, 0.0, 0.0)))
        if parent is not None:
            anchor.parent = parent
            matrix_parent_inverse = getattr(anchor, "matrix_parent_inverse", None)
            if matrix_parent_inverse is not None and hasattr(parent, "matrix_world"):
                try:
                    anchor.matrix_parent_inverse = parent.matrix_world.inverted()
                except Exception:
                    if hasattr(matrix_parent_inverse, "identity"):
                        matrix_parent_inverse.identity()
        anchor["vb_waterfall_role"] = role
        if render_object_name:
            anchor["vb_render_object"] = str(render_object_name)
        created.append(anchor.name)

    return created


def _materialise_mist_volume(
    mist_pos: Sequence[float],
    *,
    parent: Any | None = None,
    height_m: float = 3.0,
    collection: Any | None = None,
) -> Any | None:
    """Create a volumetric mist mesh at *mist_pos* using PrincipalVolume shader.

    The mist volume is a cube scaled to approximate the spray cone above a
    waterfall impact pool. Returns the Blender object or None when bpy is
    unavailable. The object is parented to *parent* when provided so it
    moves with the waterfall.
    """
    if bpy is None:
        return None
    try:
        import bmesh as _bmesh

        context_obj: Any = getattr(bpy, "context", None)
        col = collection or getattr(context_obj and context_obj.collection, "", None)
        if col is None and context_obj is not None:
            col = context_obj.collection

        # Half-extent: 60% of drop height for width, 40% for vertical rise
        hw = max(0.4, float(height_m) * 0.60)
        hh = max(0.3, float(height_m) * 0.40)

        mesh_data = bpy.data.meshes.new("MistVolume_mesh")
        bm = _bmesh.new()
        _bmesh.ops.create_cube(bm, size=1.0)
        bm.to_mesh(mesh_data)
        bm.free()

        mist_obj = bpy.data.objects.new("WaterfallMist", mesh_data)
        mist_obj.location = tuple(float(v) for v in mist_pos[:3])
        mist_obj.scale = (hw, hw, hh)
        if col is not None:
            col.objects.link(mist_obj)
        if parent is not None:
            mist_obj.parent = parent
            mat_inv = getattr(mist_obj, "matrix_parent_inverse", None)
            if mat_inv is not None and hasattr(parent, "matrix_world"):
                try:
                    mist_obj.matrix_parent_inverse = parent.matrix_world.inverted()
                except Exception as exc:
                    logger.warning("Optional subsystem mist_volume_matrix_parent_inverse failed (non-fatal): %s", exc)

        # Volume scatter material for waterfall mist
        mat = bpy.data.materials.new("MistVolume_mat")
        mat.use_nodes = True
        if mat.node_tree:
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links
            nodes.clear()
            out = nodes.new("ShaderNodeOutputMaterial")
            out.location = (300, 0)
            vol = nodes.new("ShaderNodeVolumePrincipled")
            vol.location = (100, 0)
            vol.inputs["Density"].default_value = 0.04
            vol.inputs["Anisotropy"].default_value = 0.30
            if vol.inputs.get("Scatter Color") is not None:
                vol.inputs["Scatter Color"].default_value = (0.95, 0.97, 1.0, 1.0)
            links.new(vol.outputs["Volume"], out.inputs["Volume"])
        mesh_data.materials.append(mat)
        mist_obj["vb_waterfall_role"] = "mist_volume"
        return mist_obj
    except Exception:
        return None


def handle_create_cave_entrance(params: dict[str, Any]) -> dict[str, Any]:
    """Create a terrain-facing cave entrance mesh object from the pure generator.

    AAA upgrade: slope validation, valley-orientation routing, protected zone
    enforcement, CliffStructure-compatible mesh spec embedded in the return
    dict for downstream physics/nav-mesh use. Comparable to UE5 cave-entrance
    placement in World Partition with NavMesh obstacle registration.

    Slope validation:
        If ``terrain_name`` is provided, the terrain slope at the entrance
        location is sampled from the mesh heightmap. Entrances on slopes >
        ``max_slope_deg`` (default 70°) are flagged as infeasible in the
        return dict but still created (callers may override).

    Valley orientation:
        If ``valley_direction_rad`` is not provided but ``terrain_name`` is,
        the handler estimates the nearest downhill direction from the entrance
        location using the heightmap gradient and passes it to the generator
        so the arch faces down-valley.

    Protected zone enforcement:
        If the requested location falls inside any protected zone declared in
        ``protected_zones``, the entrance is NOT created and the return dict
        carries ``placement_blocked=True`` with a ``blocked_by_zone`` key
        identifying the offending zone. This matches UE5 World Partition
        zone-exclusion semantics.

    Params:
        name (str): Object name.
        width, height, depth (float): Entrance dimensions.
        style (str): "natural" | "carved".
        seed (int): Random seed (must be deterministic — no wall-clock use).
        location (list[float]): [x, y, z] world position.
        rotation_z (float): Z-rotation override (radians). If provided,
            overrides valley-derived orientation.
        terrain_edge_height (float): Z offset for terrain-level flush.
        parent_name (str | None): Parent object name.
        material_key (str): Material key ("stone", etc.).
        arch_segments (int): Arch subdivision count.
        overhang_factor (float): Arch crown overhang fraction [0, 0.4].
        terrain_name (str | None): If set, used for slope sampling and
            valley-direction estimation.
        max_slope_deg (float, default 70.0): Slope above which placement is
            flagged infeasible.
        valley_direction_rad (float | None): Explicit valley bearing (rad).
            When None and terrain_name is provided, estimated from gradient.
        protected_zones (list of dict): Optional zone dicts with 'bounds'
            (BBox-like) and 'zone_id'. Placement inside a zone is blocked.

    Returns dict with:
        name, style, width, height, depth, rotation_z, location,
        parent_name, entrance_yaw_rad, overhang_m, stalactite_count,
        slope_deg, placement_feasible, placement_blocked, blocked_by_zone,
        valley_direction_rad, arch_spec (CliffStructure-compatible mesh spec
        with width/height/depth/overhang/vertex_count/nav_blocker_radius),
        affected_cells, duration_seconds, pass_name.
    """
    from ._terrain_depth import generate_cave_entrance_mesh

    _t0 = time.perf_counter()

    object_name = str(params.get("name", "CaveEntrance"))
    width = float(params.get("width", 5.5))
    height = float(params.get("height", 4.6))
    depth = float(params.get("depth", 5.5))
    style = str(params.get("style", "natural"))
    seed = int(params.get("seed", 0))
    location_raw = params.get("location", (0.0, 0.0, 0.0))
    terrain_edge_height = float(params.get("terrain_edge_height", 0.0))
    parent_name = params.get("parent_name")
    overhang_factor = float(params.get("overhang_factor", 0.18))
    max_slope_deg = float(params.get("max_slope_deg", 70.0))
    terrain_name = params.get("terrain_name")
    allowed_styles = {"natural", "carved"}

    if style not in allowed_styles:
        raise ValueError(
            f"style must be one of {sorted(allowed_styles)}, got {style!r}"
        )

    if not (0.0 <= overhang_factor <= 0.4):
        raise ValueError(
            f"overhang_factor {overhang_factor} out of valid range [0, 0.4]; "
            "values > 0.4 produce inverted arch geometry."
        )
    if width <= 0.0 or height <= 0.0 or depth <= 0.0:
        raise ValueError(
            f"width/height/depth must all be positive, got "
            f"width={width}, height={height}, depth={depth}"
        )
    if not math.isfinite(max_slope_deg) or max_slope_deg < 0.0:
        raise ValueError(
            f"max_slope_deg must be a finite non-negative value, got {max_slope_deg}"
        )

    try:
        location_seq = list(location_raw)
    except TypeError as exc:
        raise ValueError(
            f"location must be an iterable with 2 or 3 coordinates, got {location_raw!r}"
        ) from exc
    if len(location_seq) < 2:
        raise ValueError(
            f"location must have at least 2 coordinates, got {location_raw!r}"
        )

    location = (
        float(location_seq[0]),
        float(location_seq[1]),
        float(location_seq[2]) if len(location_seq) >= 3 else 0.0,
    )
    if not all(math.isfinite(coord) for coord in location):
        raise ValueError(f"location contains non-finite coordinates: {location_raw!r}")

    # ----------------------------------------------------------------
    # Protected zone enforcement — block placement before any bpy work.
    # ----------------------------------------------------------------
    placement_blocked = False
    blocked_by_zone: str | None = None
    raw_protected_zones = params.get("protected_zones") or []
    for pz in raw_protected_zones:
        bounds = pz.get("bounds")
        if not isinstance(bounds, dict):
            continue
        bmin_x = float(bounds.get("min_x", -1e18))
        bmin_y = float(bounds.get("min_y", -1e18))
        bmax_x = float(bounds.get("max_x",  1e18))
        bmax_y = float(bounds.get("max_y",  1e18))
        if bmin_x <= location[0] <= bmax_x and bmin_y <= location[1] <= bmax_y:
            placement_blocked = True
            blocked_by_zone = str(pz.get("zone_id", "unknown"))
            break

    if placement_blocked:
        _duration = time.perf_counter() - _t0
        return {
            "name": object_name,
            "style": style,
            "width": width,
            "height": height,
            "depth": depth,
            "rotation_z": 0.0,
            "location": [round(location[0], 4), round(location[1], 4), round(location[2], 4)],
            "parent_name": None,
            "placement_blocked": True,
            "blocked_by_zone": blocked_by_zone,
            "placement_feasible": False,
            "affected_cells": 0,
            "duration_seconds": round(_duration, 4),
            "pass_name": "create_cave_entrance",
        }

    # ----------------------------------------------------------------
    # Slope sampling and valley-direction estimation from terrain mesh
    # ----------------------------------------------------------------
    sampled_slope_deg = 0.0
    valley_direction_rad = params.get("valley_direction_rad")
    if valley_direction_rad is not None:
        valley_direction_rad = float(valley_direction_rad)
        if not math.isfinite(valley_direction_rad):
            raise ValueError(
                f"valley_direction_rad must be finite when provided, got {valley_direction_rad}"
            )

    if terrain_name and _HAS_BPY:
        terrain_obj = bpy.data.objects.get(str(terrain_name))
        if terrain_obj is not None and terrain_obj.type == "MESH":
            try:
                t_mesh = terrain_obj.data
                t_bm = bmesh.new()
                t_bm.from_mesh(t_mesh)
                t_bm.verts.ensure_lookup_table()
                t_rows, t_cols = _detect_grid_dims(t_bm)
                t_heights = np.array([v.co.z for v in t_bm.verts], dtype=np.float64).reshape(t_rows, t_cols)
                t_bm.free()

                tw = terrain_obj.dimensions.x if terrain_obj.dimensions.x > 0 else 100.0
                th = terrain_obj.dimensions.y if terrain_obj.dimensions.y > 0 else tw
                ox = float(terrain_obj.location.x) - tw * 0.5
                oy = float(terrain_obj.location.y) - th * 0.5
                cs_x = tw / max(t_cols - 1, 1)
                cs_y = th / max(t_rows - 1, 1)

                # Find grid cell nearest to entrance location
                grid_col = int((location[0] - ox) / cs_x)
                grid_row = int((location[1] - oy) / cs_y)
                grid_col = max(1, min(t_cols - 2, grid_col))
                grid_row = max(1, min(t_rows - 2, grid_row))

                # Local slope: central-difference gradient across 4 cardinal neighbours
                dz_dx = (t_heights[grid_row, grid_col + 1] - t_heights[grid_row, grid_col - 1]) / (2.0 * cs_x)
                dz_dy = (t_heights[grid_row + 1, grid_col] - t_heights[grid_row - 1, grid_col]) / (2.0 * cs_y)
                grad_mag = math.sqrt(dz_dx ** 2 + dz_dy ** 2)
                sampled_slope_deg = math.degrees(math.atan(grad_mag))

                # Valley direction = downhill gradient bearing
                if valley_direction_rad is None and grad_mag > 1e-6:
                    # Downhill = negative gradient direction
                    valley_direction_rad = math.atan2(-dz_dy, -dz_dx)
            except Exception as exc:
                logger.debug("Cave entrance terrain sampling failed: %s", exc)

    if valley_direction_rad is None:
        valley_direction_rad = float(params.get("rotation_z", 0.0))

    # rotation_z: use explicit override if provided, otherwise derive from valley bearing
    rotation_z_override = params.get("rotation_z")
    if rotation_z_override is not None:
        rotation_z = float(rotation_z_override)
        if not math.isfinite(rotation_z):
            raise ValueError(
                f"rotation_z must be finite when provided, got {rotation_z}"
            )
    else:
        # entrance_yaw = valley_direction + π (face down-valley)
        rotation_z = (valley_direction_rad + math.pi) % (2.0 * math.pi)

    parent_obj = bpy.data.objects.get(str(parent_name)) if parent_name and _HAS_BPY else None
    spec = generate_cave_entrance_mesh(
        width=width,
        height=height,
        depth=depth,
        arch_segments=int(params.get("arch_segments", 14)),
        terrain_edge_height=terrain_edge_height,
        style=style,
        seed=seed,
        valley_direction_rad=valley_direction_rad,
        slope_deg=sampled_slope_deg,
        overhang_factor=overhang_factor,
    )
    obj = _create_mesh_object_from_spec(
        spec,
        object_name=object_name,
        location=location,
        rotation=(0.0, 0.0, rotation_z),
        parent=parent_obj,
        material_key=str(params.get("material_key", "stone")),
    )

    meta = spec.get("metadata", {})
    placement_feasible = sampled_slope_deg <= max_slope_deg
    vertex_count = len(spec.get("vertices", []))
    overhang_m = meta.get("overhang_m", round(overhang_factor * width, 4))
    # Nav-blocker radius: half the entrance diagonal + a small clearance margin.
    nav_blocker_radius = round(math.sqrt(width ** 2 + height ** 2) * 0.5 + 0.5, 3)

    _duration = time.perf_counter() - _t0
    return {
        "name": object_name if isinstance(obj, dict) else getattr(obj, "name", object_name),
        "style": style,
        "width": width,
        "height": height,
        "depth": depth,
        "rotation_z": round(rotation_z, 6),
        "location": [round(location[0], 4), round(location[1], 4), round(location[2], 4)],
        "parent_name": getattr(parent_obj, "name", None),
        "placement_blocked": False,
        "blocked_by_zone": None,
        # Slope + orientation diagnostics
        "entrance_yaw_rad": round(rotation_z, 6),
        "valley_direction_rad": round(valley_direction_rad % (2.0 * math.pi), 6),
        "overhang_m": overhang_m,
        "stalactite_count": meta.get("stalactite_count", 0),
        "slope_deg": round(sampled_slope_deg, 2),
        "placement_feasible": placement_feasible,
        # CliffStructure-compatible arch spec for downstream physics / nav-mesh
        "arch_spec": {
            "width": width,
            "height": height,
            "depth": depth,
            "overhang_factor": overhang_factor,
            "overhang_m": overhang_m,
            "spring_z": terrain_edge_height + height * 0.5,
            "apex_z": terrain_edge_height + height,
            "vertex_count": vertex_count,
            "nav_blocker_radius": nav_blocker_radius,
            "style": style,
            "seed": seed,
        },
        # AAA metrics
        "affected_cells": 1,
        "duration_seconds": round(_duration, 4),
        "pass_name": "create_cave_entrance",
    }


# ---------------------------------------------------------------------------
# Handler: generate_road
# ---------------------------------------------------------------------------

def handle_generate_road(params: dict[str, Any]) -> dict[str, Any]:
    """Generate a road between waypoints on terrain with grading.

    Params:
        terrain_name (str): Existing terrain object name.
        waypoints (list of [row, col]): Ordered waypoints.
        width (int, default 3): Road width in cells.
        grade_strength (float, default 0.8): Flattening intensity.
        seed (int, default 0): Random seed.
        rock_hardness (2D array): Optional normalized hard-rock channel.
        water_surface (2D array): Optional normalized water channel.
        road_cost_map/cost_map (2D array): Optional explicit routing cost grid.

    Returns dict with: name, path_length, width.
    """
    logger.info("Generating road on terrain")
    _t0 = time.perf_counter()
    terrain_name = params.get("terrain_name")
    if not terrain_name:
        raise ValueError("'terrain_name' is required")

    waypoints = [(int(wp[0]), int(wp[1])) for wp in params.get("waypoints", [(0, 0), (0, 0)])]
    width = int(params.get("width", 3))
    grade_strength = params.get("grade_strength", 0.8)
    seed = params.get("seed", 0)
    mask_stack = params.get("mask_stack")
    requested_surface = str(params.get("surface", params.get("material_key", "dirt"))).strip().lower()
    raw_protected_zones = params.get("protected_zones") or []
    road_material_key = {
        "dirt": "dirt",
        "dirt_path": "dirt",
        "trail": "trail",
        "path": "trail",
        "mud": "mud",
        "muddy": "mud",
        "gravel": "cobblestone_floor",
        "stone": "cobblestone_floor",
        "cobblestone": "cobblestone_floor",
        "cobblestone_floor": "cobblestone_floor",
        "main_road": "cobblestone_floor",
    }.get(requested_surface, "dirt")

    obj = bpy.data.objects.get(terrain_name)
    if obj is None:
        raise ValueError(f"Object not found: {terrain_name}")

    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()

    # WORLD-004: Detect actual grid dimensions (robust to non-square terrain)
    rows, cols = _detect_grid_dims(bm)

    heights = np.array([v.co.z for v in bm.verts], dtype=np.float64)
    heightmap = heights.reshape(rows, cols)

    # Convert width from meters to grid cells if it looks like meters
    terrain_width = obj.dimensions.x if obj.dimensions.x > 0 else 100.0
    terrain_height = obj.dimensions.y if obj.dimensions.y > 0 else terrain_width
    cell_size_x = terrain_width / max(cols - 1, 1)
    cell_size_y = terrain_height / max(rows - 1, 1)
    cell_size = (cell_size_x + cell_size_y) * 0.5
    if width > 10:  # likely specified in meters, not cells
        width = max(1, int(width / cell_size))

    road_cost_map, road_cost_source = _resolve_road_cost_context(
        params,
        heightmap=heightmap,
    )

    # ------------------------------------------------------------------
    # Protected zone mask (grid-space, for _apply_road_profile_to_heightmap)
    # ------------------------------------------------------------------
    _ox = float(obj.location.x)
    _oy = float(obj.location.y)
    _tw = max(float(terrain_width), 1e-9)
    _th = max(float(terrain_height), 1e-9)
    _col_w = _ox + np.arange(cols, dtype=np.float64) / max(cols - 1, 1) * _tw - _tw * 0.5
    _row_w = _oy + np.arange(rows, dtype=np.float64) / max(rows - 1, 1) * _th - _th * 0.5
    road_pz_mask = np.zeros((rows, cols), dtype=bool)
    protected_cells_skipped = 0
    if raw_protected_zones:
        for pz in raw_protected_zones:
            pz_x0 = float(pz.get("x_min", pz.get("x0", -1e9)))
            pz_x1 = float(pz.get("x_max", pz.get("x1",  1e9)))
            pz_y0 = float(pz.get("y_min", pz.get("y0", -1e9)))
            pz_y1 = float(pz.get("y_max", pz.get("y1",  1e9)))
            road_pz_mask |= (
                (_col_w[np.newaxis, :] >= pz_x0) & (_col_w[np.newaxis, :] <= pz_x1)
                & (_row_w[:, np.newaxis] >= pz_y0) & (_row_w[:, np.newaxis] <= pz_y1)
            )

    road_route_rdp_epsilon = float(params.get("rdp_epsilon", max(cell_size * 0.5, 0.75)))
    road_routing_method = "legacy_grid"
    _road_strict = os.environ.get("VEILBREAKERS_ROAD_STRICT", "1").strip() != "0"
    _road_fallback_reason: str = ""
    try:
        path, road_network_result = _solve_road_path_with_network(
            heightmap,
            waypoints,
            terrain_width=terrain_width,
            terrain_height=terrain_height,
            terrain_origin_x=_ox,
            terrain_origin_y=_oy,
            cost_map=road_cost_map,
            seed=seed,
            rdp_epsilon=road_route_rdp_epsilon,
        )
        max_grade_degrees = float(params.get("max_grade_degrees", 15.0))
        graded = _grade_road_path_in_world_space(
            heightmap,
            path,
            width=width,
            grade_strength=float(grade_strength),
            max_grade_degrees=max_grade_degrees,
            cell_size=float(cell_size),
        )
        road_routing_method = str(road_network_result.get("routing_method", "astar_24dir"))
        print("[roads] using AAA 24-dir A* routing (VEILBREAKERS_ROAD_STRICT=1)", flush=True)
    except (LookupError, ValueError, RuntimeError) as _road_exc:
        if _road_strict:
            raise
        _road_fallback_reason = f"{type(_road_exc).__name__}: {_road_exc}"
        logger.warning(
            "Road-network route solve failed for %s; falling back to legacy grid solver",
            terrain_name,
            exc_info=True,
        )
        road_routing_method = "legacy_fallback"
        warnings.warn(
            "VEILBREAKERS_ROAD_STRICT=0: using legacy grid-space A* road routing; "
            "set VEILBREAKERS_ROAD_STRICT=1 (default) for AAA 24-dir routing",
            DeprecationWarning,
            stacklevel=2,
        )
        path, graded, _ = _run_height_solver_in_world_space(
            heightmap,
            generate_road_path_grid_legacy,
            waypoints=waypoints,
            width=width,
            grade_strength=grade_strength,
            seed=seed,
            cost_map=road_cost_map,
            # ``cell_size`` is now required by the legacy helper — plumb the
            # terrain's world spacing so Rune's slope penalty scales correctly
            # on non-1m tiles (P2-8 narrowing).
            cell_size=float(cell_size),
        )
        max_grade_degrees = float(params.get("max_grade_degrees", 15.0))

    water_level_raw = params.get("water_level")
    water_level = float(water_level_raw) if water_level_raw is not None else None
    terrain_only_surfaces = {"trail", "path", "dirt_path", "dirt"}
    low_profile_surfaces = set(terrain_only_surfaces)
    allow_bridges = bool(
        params.get(
            "allow_bridges",
            water_level is not None or requested_surface not in terrain_only_surfaces,
        )
    )
    crown_height_m = max(cell_size * 0.04, 0.03)
    ditch_depth_m = max(cell_size * 0.10, 0.08)
    if requested_surface in terrain_only_surfaces:
        crown_height_m *= 0.35
        ditch_depth_m *= 0.28
    elif requested_surface in low_profile_surfaces:
        crown_height_m *= 0.62
        ditch_depth_m *= 0.55
    shoulder_width_cells = max(1.5, width * 0.65)
    graded_pre = graded.copy()
    graded = _apply_road_profile_to_heightmap(
        graded,
        path,
        width_cells=float(width),
        grade_strength=float(grade_strength),
        crown_height_m=crown_height_m,
        shoulder_width_cells=shoulder_width_cells,
        ditch_depth_m=ditch_depth_m,
        protected_mask=road_pz_mask if road_pz_mask.any() else None,
    )
    if road_pz_mask.any():
        protected_cells_skipped = int((road_pz_mask & (graded != graded_pre)).sum())
    road_mask, road_sdf_dist = _build_road_mask_and_sdf(
        path,
        shape=heightmap.shape,
        width_cells=float(width),
    )
    if mask_stack is not None and hasattr(mask_stack, "set"):
        mask_stack.set("road_mask", road_mask.astype(np.float32), "generate_road")
        mask_stack.set("road_sdf_dist", road_sdf_dist.astype(np.float32), "generate_road")

    # Write graded Z values — fully vectorised, zero Python vertex loop.
    # 1. Flush bmesh to mesh to make vertex count canonical.
    bm.to_mesh(mesh)
    bm.free()
    mesh_vertices = getattr(mesh, "vertices", None)
    if (
        mesh_vertices is not None
        and hasattr(mesh_vertices, "foreach_get")
        and hasattr(mesh_vertices, "foreach_set")
    ):
        # 2. Batch-read all vertex co via foreach_get.
        n_verts = len(mesh_vertices)
        co_road = np.empty(n_verts * 3, dtype=np.float32)
        mesh_vertices.foreach_get("co", co_road)
        # 3. Overwrite Z channel with numpy stride-slice — no Python loop.
        graded_flat = graded.flatten()
        n_write = min(n_verts, len(graded_flat))
        co_road[2::3][:n_write] = graded_flat[:n_write].astype(np.float32)
        # 4. Batch-write back.
        mesh_vertices.foreach_set("co", co_road)
    if hasattr(mesh, "update"):
        mesh.update()

    road_mesh_name = f"{terrain_name}_Road"
    terrain_obj = bpy.data.objects.get(terrain_name)
    terrain_width = terrain_obj.dimensions.x if terrain_obj and terrain_obj.dimensions.x > 0 else 100.0
    terrain_height = terrain_obj.dimensions.y if terrain_obj and terrain_obj.dimensions.y > 0 else terrain_width
    cell_size_x = terrain_width / max(cols - 1, 1)
    cell_size_y = terrain_height / max(rows - 1, 1)
    cell_size = (cell_size_x + cell_size_y) * 0.5
    terrain_origin_x = terrain_obj.location.x if terrain_obj else 0.0
    terrain_origin_y = terrain_obj.location.y if terrain_obj else 0.0
    road_half_width = width * cell_size * 0.5
    road_width_world = max(width * cell_size, cell_size)
    shoulder_width_world = max(cell_size * shoulder_width_cells, road_half_width * 0.65)

    full_path_world = [
        (
            *_terrain_grid_to_world_xy(
                row,
                col,
                rows=rows,
                cols=cols,
                terrain_width=terrain_width,
                terrain_height=terrain_height,
                terrain_origin_x=terrain_origin_x,
                terrain_origin_y=terrain_origin_y,
            ),
            float(graded[row, col]) + (0.01 if requested_surface in low_profile_surfaces else 0.03),
        )
        for row, col in path
    ]
    _paint_road_mask_on_terrain(
        terrain_obj,
        full_path_world,
        road_half_width=road_half_width,
        shoulder_width=shoulder_width_world,
        surface_key=requested_surface,
    )

    bridge_spans = _collect_bridge_spans(
        path,
        base_heightmap=heightmap,
        graded_heightmap=graded,
        water_level=water_level if allow_bridges else None,
        width_m=road_width_world,
        rows=rows,
        cols=cols,
        terrain_width=terrain_width,
        terrain_height=terrain_height,
        terrain_origin_x=terrain_origin_x,
        terrain_origin_y=terrain_origin_y,
    )
    path_network_contract, path_network_contract_issues = _build_generated_road_path_contract(
        terrain_name=terrain_name,
        full_path_world=full_path_world,
        bridge_spans=bridge_spans,
        terrain_bounds=(
            float(terrain_origin_x) - float(terrain_width) * 0.5,
            float(terrain_origin_y) - float(terrain_height) * 0.5,
            float(terrain_origin_x) + float(terrain_width) * 0.5,
            float(terrain_origin_y) + float(terrain_height) * 0.5,
        ),
        surface_key=requested_surface,
        road_width_m=road_width_world,
        max_grade_degrees=max_grade_degrees,
    )
    bridge_mask = [False] * len(path)
    forced_indices: set[int] = set()
    for span in bridge_spans:
        forced_indices.update({span["start_index"], span["end_index"]})
        for idx in range(span["start_index"], span["end_index"] + 1):
            if 0 <= idx < len(bridge_mask):
                bridge_mask[idx] = True

    sampled_indices = _sample_path_indices(
        path,
        min_spacing_cells=(
            max(width * 0.35, 1.0)
            if requested_surface in low_profile_surfaces
            else max(width * 0.75, 2.0)
        ),
        forced_indices=forced_indices,
    )

    if requested_surface in terrain_only_surfaces and not bool(params.get("force_mesh_overlay", False)):
        _duration = time.perf_counter() - _t0
        result = {
            "name": terrain_name,
            "road_mesh_name": None,
            "path_length": len(path),
            "width": width,
            "road_width_m": road_width_world,
            "road_vertex_count": 0,
            "surface": requested_surface,
            "surface_mode": "terrain_only",
            "bridge_count": len(bridge_spans),
            "bridge_span_count": len(bridge_spans),
            "bridge_object_names": [],
            "road_mask_shape": list(road_mask.shape),
            "road_mask_nonzero": int(road_mask.sum()),
            "terrain_cost_context_used": road_cost_map is not None,
            "terrain_cost_source": road_cost_source,
            "road_routing_method": road_routing_method,
            "path_network_contract": path_network_contract,
            "path_network_contract_issues": path_network_contract_issues,
            "protected_cells_skipped": protected_cells_skipped,
            "affected_cells": len(path),
            "duration_seconds": round(_duration, 4),
            "pass_name": "generate_road",
        }
        if _road_fallback_reason:
            result["fallback_reason"] = _road_fallback_reason
        if bool(params.get("return_road_channels", False)):
            result["road_mask"] = road_mask.tolist()
            result["road_sdf_dist"] = road_sdf_dist.tolist()
        return result

    chunks: list[list[int]] = []
    current_chunk: list[int] = []
    for idx in sampled_indices:
        if bridge_mask[idx]:
            if len(current_chunk) >= 2:
                chunks.append(current_chunk)
            current_chunk = []
            continue
        if current_chunk:
            lo = min(current_chunk[-1], idx)
            hi = max(current_chunk[-1], idx)
            if any(bridge_mask[lo: hi + 1]):
                if len(current_chunk) >= 2:
                    chunks.append(current_chunk)
                current_chunk = [idx]
            else:
                current_chunk.append(idx)
        else:
            current_chunk = [idx]
    if len(current_chunk) >= 2:
        chunks.append(current_chunk)

    road_vertices: list[tuple[float, float, float]] = []
    road_faces: list[tuple[int, int, int, int]] = []
    for chunk in chunks:
        chunk_points = [full_path_world[idx] for idx in chunk]
        chunk_vertices, chunk_faces = _build_road_strip_geometry(
            chunk_points,
            half_width=road_half_width,
        )
        base_index = len(road_vertices)
        road_vertices.extend(chunk_vertices)
        road_faces.extend(
            (
                base_index + face[0],
                base_index + face[1],
                base_index + face[2],
                base_index + face[3],
            )
            for face in chunk_faces
        )

    road_mesh_data = bpy.data.meshes.new(road_mesh_name)
    road_mesh_data.from_pydata(road_vertices, [], road_faces)
    road_mesh_data.update()
    for poly in getattr(road_mesh_data, "polygons", []):
        poly.use_smooth = True

    road_obj = bpy.data.objects.new(road_mesh_name, road_mesh_data)
    bpy.context.collection.objects.link(road_obj)
    if terrain_obj is not None:
        road_obj.parent = terrain_obj
        mpi = getattr(road_obj, "matrix_parent_inverse", None)
        if mpi is not None and hasattr(terrain_obj, "matrix_world"):
            try:
                road_obj.matrix_parent_inverse = terrain_obj.matrix_world.inverted()
            except Exception:
                if hasattr(mpi, "identity"):
                    mpi.identity()

    road_mat = _ensure_grounded_road_material(
        f"Road_{road_material_key.title()}",
        road_material_key,
    )
    road_mesh_data.materials.append(road_mat)

    bridge_object_names: list[str] = []
    if bridge_spans:
        from ._terrain_depth import generate_terrain_bridge_mesh

        for bridge_index, span in enumerate(bridge_spans):
            bridge_spec = generate_terrain_bridge_mesh(
                start_pos=span["start_pos"],
                end_pos=span["end_pos"],
                width=max(road_width_world * 0.92, 1.25),
                style=span["style"],
                seed=seed + 500 + bridge_index,
            )
            bridge_obj = _create_bridge_object_from_spec(
                bridge_spec,
                object_name=f"{road_mesh_name}_Bridge_{bridge_index}",
                parent=terrain_obj,
                material_key=span["material_key"],
            )
            if bridge_obj is not None:
                bridge_object_names.append(bridge_obj.name)

    _duration = time.perf_counter() - _t0
    result = {
        "name": terrain_name,
        "road_mesh_name": road_obj.name,
        "path_length": len(path),
        "width": width,
        "road_width_m": road_width_world,
        "road_vertex_count": len(road_mesh_data.vertices),
        "surface": requested_surface,
        "bridge_count": len(bridge_object_names),
        "bridge_span_count": len(bridge_spans),
        "bridge_object_names": bridge_object_names,
        "splatmap_layer": "VB_TerrainSplatmap",
        "road_mask_shape": list(road_mask.shape),
        "road_mask_nonzero": int(road_mask.sum()),
        "terrain_cost_context_used": road_cost_map is not None,
        "terrain_cost_source": road_cost_source,
        "road_routing_method": road_routing_method,
        "path_network_contract": path_network_contract,
        "path_network_contract_issues": path_network_contract_issues,
        "protected_cells_skipped": protected_cells_skipped,
        "affected_cells": len(path),
        "duration_seconds": round(_duration, 4),
        "pass_name": "generate_road",
    }
    if _road_fallback_reason:
        result["fallback_reason"] = _road_fallback_reason
    if bool(params.get("return_road_channels", False)):
        result["road_mask"] = road_mask.tolist()
        result["road_sdf_dist"] = road_sdf_dist.tolist()
    return result


def _ensure_water_material(
    material_name: str,
    *,
    preview_fast: bool,
    surface_only: bool = False,
) -> Any:
    """Create or update the canonical water material."""
    mat = bpy.data.materials.get(material_name)
    if mat is None:
        mat = bpy.data.materials.new(name=material_name)
    mat.use_nodes = True
    mat.use_backface_culling = False
    if hasattr(mat, "blend_method"):
        mat.blend_method = "OPAQUE" if surface_only else "BLEND"
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "NONE"
    if hasattr(mat, "use_transparent_shadow"):
        mat.use_transparent_shadow = False if surface_only else True
    if hasattr(mat, "show_transparent_back"):
        mat.show_transparent_back = False if surface_only else True
    if hasattr(mat, "use_transparency_overlap"):
        mat.use_transparency_overlap = False if surface_only else True
    if hasattr(mat, "surface_render_method") and surface_only:
        try:
            mat.surface_render_method = "DITHERED"
        except Exception as exc:
            logger.warning("Optional subsystem surface_render_method failed (non-fatal): %s", exc)
    if hasattr(mat, "use_screen_refraction"):
        mat.use_screen_refraction = not surface_only
    if hasattr(mat, "refraction_depth"):
        mat.refraction_depth = 0.0 if surface_only else 0.8
    if mat.node_tree:
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()
        output = nodes.new("ShaderNodeOutputMaterial")
        output.location = (360, 0)
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (160, 0)
        links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

        base_color = bsdf.inputs.get("Base Color")
        if base_color:
            if surface_only:
                base_color.default_value = (0.30, 0.63, 0.72, 1.0)
            else:
                base_color.default_value = (0.12, 0.27, 0.26, 1.0)

        try:
            vcol = nodes.new("ShaderNodeVertexColor")
            vcol.location = (-920, 0)
            vcol.layer_name = "flow_vc"

            separate = nodes.new("ShaderNodeSeparateColor")
            separate.location = (-700, 0)
            separate.mode = "RGB"
            vcol_color = vcol.outputs.get("Color") if hasattr(vcol, "outputs") else None
            separate_color = separate.inputs.get("Color") if hasattr(separate, "inputs") else None
            if vcol_color is not None and separate_color is not None:
                links.new(vcol_color, separate_color)

            foam_ramp = nodes.new("ShaderNodeValToRGB")
            foam_ramp.location = (-480, -180)
            if hasattr(foam_ramp, "color_ramp"):
                foam_ramp.color_ramp.elements[0].position = 0.42
                foam_ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
                foam_ramp.color_ramp.elements[1].position = 0.82
                foam_ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
            vcol_alpha = vcol.outputs.get("Alpha") if hasattr(vcol, "outputs") else None
            foam_fac = foam_ramp.inputs.get("Fac") if hasattr(foam_ramp, "inputs") else None
            if vcol_alpha is not None and foam_fac is not None:
                links.new(vcol_alpha, foam_fac)

            deep_color = nodes.new("ShaderNodeRGB")
            deep_color.location = (-480, 140)
            deep_color.outputs["Color"].default_value = (
                (0.18, 0.42, 0.50, 1.0)
                if surface_only
                else (0.05, 0.16, 0.20, 1.0)
            )
            shallow_color = nodes.new("ShaderNodeRGB")
            shallow_color.location = (-480, 60)
            shallow_color.outputs["Color"].default_value = (
                (0.36, 0.72, 0.80, 1.0)
                if surface_only
                else (0.15, 0.33, 0.31, 1.0)
            )
            foam_color = nodes.new("ShaderNodeRGB")
            foam_color.location = (-480, -20)
            foam_color.outputs["Color"].default_value = (
                (0.90, 0.94, 0.93, 1.0)
                if surface_only
                else (0.82, 0.86, 0.84, 1.0)
            )

            shallow_mix = nodes.new("ShaderNodeMix")
            shallow_mix.data_type = "RGBA"
            shallow_mix.location = (-220, 100)
            shallow_mix.blend_type = "MIX"
            shallow_mix.inputs["Factor"].default_value = 0.0
            separate_red = separate.outputs.get("Red") if hasattr(separate, "outputs") else None
            shallow_fac = shallow_mix.inputs.get("Factor") if hasattr(shallow_mix, "inputs") else None
            if separate_red is not None and shallow_fac is not None:
                # The red flow_vc channel is authored as a shallow-water cue.
                links.new(separate_red, shallow_fac)
            if shallow_mix.inputs.get("A") is not None:
                links.new(deep_color.outputs["Color"], shallow_mix.inputs["A"])
            if shallow_mix.inputs.get("B") is not None:
                links.new(shallow_color.outputs["Color"], shallow_mix.inputs["B"])

            foam_mix = nodes.new("ShaderNodeMix")
            foam_mix.data_type = "RGBA"
            foam_mix.location = (0, 40)
            foam_mix.blend_type = "MIX"
            foam_color_socket = foam_ramp.outputs.get("Color") if hasattr(foam_ramp, "outputs") else None
            if foam_color_socket is not None and foam_mix.inputs.get("Factor") is not None:
                links.new(foam_color_socket, foam_mix.inputs["Factor"])
            if shallow_mix.outputs.get("Result") is not None and foam_mix.inputs.get("A") is not None:
                links.new(shallow_mix.outputs["Result"], foam_mix.inputs["A"])
            if foam_mix.inputs.get("B") is not None:
                links.new(foam_color.outputs["Color"], foam_mix.inputs["B"])

            if base_color and foam_mix.outputs.get("Result") is not None:
                links.new(foam_mix.outputs["Result"], base_color)
        except Exception as exc:
            # Test stubs expose a smaller node API surface; keep the readable
            # fallback tint instead of failing material creation outright.
            logger.warning("Optional subsystem water_foam_node_wiring failed (non-fatal): %s", exc)
        rough = bsdf.inputs.get("Roughness")
        if rough:
            if surface_only:
                rough.default_value = 0.10 if preview_fast else 0.13
            else:
                rough.default_value = 0.035 if preview_fast else 0.05
        ior = bsdf.inputs.get("IOR")
        if ior:
            ior.default_value = 1.12 if surface_only else 1.333
        alpha = bsdf.inputs.get("Alpha")
        if alpha:
            if surface_only:
                alpha.default_value = 1.0
            else:
                alpha.default_value = 0.78 if preview_fast else 0.72
        trans = bsdf.inputs.get("Transmission Weight") or bsdf.inputs.get("Transmission")
        if trans:
            if surface_only:
                trans.default_value = 0.0
            else:
                trans.default_value = 0.78 if preview_fast else 0.90
        spec = bsdf.inputs.get("Specular IOR Level") or bsdf.inputs.get("Specular")
        if spec:
            spec.default_value = 0.46 if surface_only else 0.55

        if not surface_only:
            try:
                absorption = nodes.new("ShaderNodeVolumeAbsorption")
                absorption.location = (150, -180)
                absorption.inputs["Color"].default_value = (0.03, 0.09, 0.11, 1.0)
                absorption.inputs["Density"].default_value = 0.08 if preview_fast else 0.12
                if output.inputs.get("Volume") is not None:
                    links.new(absorption.outputs["Volume"], output.inputs["Volume"])
            except Exception as exc:
                logger.warning("Optional subsystem water_volume_absorption_node failed (non-fatal): %s", exc)

        if surface_only:
            try:
                emission = nodes.new("ShaderNodeEmission")
                emission.location = (160, -150)
                emission.inputs["Color"].default_value = (0.10, 0.24, 0.30, 1.0)
                emission.inputs["Strength"].default_value = 0.35 if preview_fast else 0.28
                add_shader = nodes.new("ShaderNodeAddShader")
                add_shader.location = (320, -40)
                links.new(bsdf.outputs["BSDF"], add_shader.inputs[0])
                links.new(emission.outputs["Emission"], add_shader.inputs[1])
                links.new(add_shader.outputs["Shader"], output.inputs["Surface"])
            except Exception as exc:
                logger.warning("Optional subsystem water_emission_node failed (non-fatal): %s", exc)

        noise_tex = nodes.new("ShaderNodeTexNoise")
        noise_tex.location = (-220, -220)
        if surface_only:
            noise_tex.inputs["Scale"].default_value = 7.0 if preview_fast else 10.0
        else:
            noise_tex.inputs["Scale"].default_value = 11.0 if preview_fast else 18.0
        noise_tex.inputs["Detail"].default_value = 3.2
        noise_tex.inputs["Roughness"].default_value = 0.36
        bump_node = nodes.new("ShaderNodeBump")
        bump_node.location = (20, -200)
        if surface_only:
            bump_node.inputs["Strength"].default_value = 0.004 if preview_fast else 0.007
        else:
            bump_node.inputs["Strength"].default_value = 0.012 if preview_fast else 0.022
        bump_node.inputs["Distance"].default_value = 0.008
        links.new(noise_tex.outputs["Fac"], bump_node.inputs["Height"])
        normal_input = bsdf.inputs.get("Normal")
        if normal_input:
            links.new(bump_node.outputs["Normal"], normal_input)

        # Riverbed caustics: Voronoi-distance emission that fakes refracted light
        # patterns on the riverbed. Only wired for full-volume water (not surface_only
        # preview mode). Strength 0.06 is just above perceptible without oversaturating.
        if not surface_only:
            try:
                caus_coord = nodes.new("ShaderNodeTexCoord")
                caus_coord.location = (-640, -400)
                caus_vor = nodes.new("ShaderNodeTexVoronoi")
                caus_vor.location = (-440, -400)
                if hasattr(caus_vor, "voronoi_dimensions"):
                    caus_vor.voronoi_dimensions = "3D"
                caus_vor.inputs["Scale"].default_value = 6.0
                if caus_vor.inputs.get("Randomness") is not None:
                    caus_vor.inputs["Randomness"].default_value = 0.85
                links.new(caus_coord.outputs["Generated"], caus_vor.inputs["Vector"])
                caus_ramp = nodes.new("ShaderNodeValToRGB")
                caus_ramp.location = (-220, -400)
                if hasattr(caus_ramp, "color_ramp"):
                    caus_ramp.color_ramp.elements[0].position = 0.50
                    caus_ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
                    caus_ramp.color_ramp.elements[1].position = 0.72
                    caus_ramp.color_ramp.elements[1].color = (0.22, 0.32, 0.38, 1.0)
                dist_out = caus_vor.outputs.get("Distance")
                if dist_out is not None and caus_ramp.inputs.get("Fac") is not None:
                    links.new(dist_out, caus_ramp.inputs["Fac"])
                caus_emit = nodes.new("ShaderNodeEmission")
                caus_emit.location = (10, -380)
                caus_emit.inputs["Strength"].default_value = 0.06
                if caus_ramp.outputs.get("Color") is not None:
                    links.new(caus_ramp.outputs["Color"], caus_emit.inputs["Color"])
                caus_add = nodes.new("ShaderNodeAddShader")
                caus_add.location = (200, -200)
                links.new(bsdf.outputs["BSDF"], caus_add.inputs[0])
                links.new(caus_emit.outputs["Emission"], caus_add.inputs[1])
                links.new(caus_add.outputs["Shader"], output.inputs["Surface"])
            except Exception as exc:
                logger.warning("Optional subsystem water_caustic_node_wiring failed (non-fatal): %s", exc)

    return mat


def _apply_water_object_settings(obj: Any, *, surface_only: bool) -> None:
    """Disable shadow-heavy viewport behavior on live water objects."""
    if obj is None:
        return
    try:
        obj.display_type = "TEXTURED"
    except Exception as exc:
        logger.warning("Optional subsystem water_display_type failed (non-fatal): %s", exc)
    for attr, value in (
        ("visible_shadow", False),
        ("is_shadow_catcher", False),
    ):
        if hasattr(obj, attr):
            try:
                setattr(obj, attr, value)
            except Exception as exc:
                logger.warning("Optional subsystem water_obj_attr_%s failed (non-fatal): %s", attr, exc)
    cycles_visibility = getattr(obj, "cycles_visibility", None)
    if cycles_visibility is not None and hasattr(cycles_visibility, "shadow"):
        try:
            cycles_visibility.shadow = False
        except Exception as exc:
            logger.warning("Optional subsystem cycles_visibility_shadow failed (non-fatal): %s", exc)
    if surface_only:
        try:
            obj.color = (1.0, 1.0, 1.0, 1.0)
        except Exception as exc:
            logger.warning("Optional subsystem water_obj_color failed (non-fatal): %s", exc)


def _build_terrain_world_height_sampler(terrain_obj: Any) -> Callable[[float, float], float] | None:
    """Return a bilinear world-space height sampler for regular-grid terrain meshes."""
    terrain_mesh = getattr(terrain_obj, "data", None)
    terrain_vertices = list(getattr(terrain_mesh, "vertices", []) or [])
    if len(terrain_vertices) < 4:
        return None

    rows, cols = _detect_grid_dims_from_vertices(terrain_vertices)
    if rows < 2 or cols < 2 or rows * cols != len(terrain_vertices):
        return None

    world_points = [
        _object_world_xyz(terrain_obj, getattr(vert, "co", vert))
        for vert in terrain_vertices
    ]
    xs = [point[0] for point in world_points]
    ys = [point[1] for point in world_points]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    heights = np.asarray([point[2] for point in world_points], dtype=np.float64).reshape(rows, cols)

    def _sample(world_x: float, world_y: float) -> float:
        col_f = ((float(world_x) - min_x) / span_x) * max(cols - 1, 1)
        row_f = ((float(world_y) - min_y) / span_y) * max(rows - 1, 1)
        col_f = max(0.0, min(float(cols - 1), col_f))
        row_f = max(0.0, min(float(rows - 1), row_f))

        c0 = min(int(math.floor(col_f)), cols - 1)
        r0 = min(int(math.floor(row_f)), rows - 1)
        c1 = min(c0 + 1, cols - 1)
        r1 = min(r0 + 1, rows - 1)
        cf = col_f - c0
        rf = row_f - r0

        h00 = float(heights[r0, c0])
        h10 = float(heights[r0, c1])
        h01 = float(heights[r1, c0])
        h11 = float(heights[r1, c1])
        return (
            h00 * (1.0 - cf) * (1.0 - rf)
            + h10 * cf * (1.0 - rf)
            + h01 * (1.0 - cf) * rf
            + h11 * cf * rf
        )

    return _sample


def _resolve_river_bank_contact(
    *,
    terrain_height_sampler: Callable[[float, float], float] | None,
    center_x: float,
    center_y: float,
    surface_z: float,
    normal_x: float,
    normal_y: float,
    default_half_width: float,
    side_sign: float,
) -> tuple[float, float]:
    """Solve a cross-section bank edge against the terrain height field."""
    if terrain_height_sampler is None:
        return float(default_half_width), float(surface_z)

    def _safe_sample(sample_x: float, sample_y: float) -> float | None:
        try:
            sampled = float(terrain_height_sampler(sample_x, sample_y))
        except Exception:
            return None
        if not math.isfinite(sampled):
            return None
        return sampled

    target_clearance = 0.035
    max_dist = max(float(default_half_width) * 1.55, 1.25)
    steps = 16

    prev_dist = 0.0
    prev_height = _safe_sample(
        center_x + normal_x * side_sign * prev_dist,
        center_y + normal_y * side_sign * prev_dist,
    )
    if prev_height is None:
        return float(default_half_width), float(surface_z)
    prev_delta = prev_height - float(surface_z)
    best_dist = prev_dist
    best_height = prev_height
    best_score = abs(prev_delta - target_clearance)

    for step in range(1, steps + 1):
        dist = max_dist * (step / steps)
        sample_x = center_x + normal_x * side_sign * dist
        sample_y = center_y + normal_y * side_sign * dist
        terrain_z = _safe_sample(sample_x, sample_y)
        if terrain_z is None:
            continue
        delta = terrain_z - float(surface_z)
        score = abs(delta - target_clearance)
        if score < best_score:
            best_score = score
            best_dist = dist
            best_height = terrain_z

        if delta >= target_clearance:
            if prev_delta < target_clearance and abs(delta - prev_delta) > 1e-6:
                blend = max(
                    0.0,
                    min(1.0, (target_clearance - prev_delta) / (delta - prev_delta)),
                )
                resolved_dist = prev_dist + (dist - prev_dist) * blend
                resolved_height = prev_height + (terrain_z - prev_height) * blend
                return float(resolved_dist), float(resolved_height)
            return float(dist), float(terrain_z)

        prev_dist = dist
        prev_height = terrain_z
        prev_delta = delta

    return max(0.08, float(best_dist)), float(best_height)


def _resolve_river_terminal_width_scale(
    ring_index: int,
    ring_count: int,
    *,
    taper_rings: int,
    min_scale: float = 0.12,
) -> float:
    """Return a width multiplier that narrows exposed river terminals."""
    if ring_count <= 2 or taper_rings <= 0:
        return 1.0

    usable_taper = min(
        max(int(taper_rings), 0),
        max((int(ring_count) - 1) // 2, 0),
    )
    if usable_taper <= 0:
        return 1.0

    taper_scale = 1.0
    for distance_to_end in (int(ring_index), int(ring_count) - 1 - int(ring_index)):
        if distance_to_end > usable_taper:
            continue
        if distance_to_end <= 0:
            local_scale = float(min_scale)
        else:
            blend = _smootherstep(distance_to_end / max(float(usable_taper), 1.0))
            local_scale = float(min_scale) + (1.0 - float(min_scale)) * blend
        taper_scale = min(taper_scale, local_scale)

    return max(float(min_scale), min(1.0, float(taper_scale)))


def _boundary_edges_from_faces(faces: list[tuple[int, ...]]) -> list[tuple[int, int]]:
    """Return boundary edges for a manifold-ish quad/tri face list."""
    edge_counts: dict[tuple[int, int], int] = {}
    for face in faces:
        if len(face) < 2:
            continue
        for start, end in zip(face, (*face[1:], face[0])):
            key = (min(start, end), max(start, end))
            edge_counts[key] = edge_counts.get(key, 0) + 1
    return [edge for edge, count in edge_counts.items() if count == 1]


def _build_level_water_surface_from_terrain(
    *,
    name: str,
    terrain_obj: Any,
    water_level: float,
    material_name: str,
    preview_fast: bool,
    mask_center: tuple[float, float] | None = None,
    mask_radius: float | None = None,
    mask_aspect_y: float = 1.0,
    surface_only: bool = False,
) -> dict[str, Any]:
    """Create a level water surface that follows the submerged terrain footprint."""
    terrain_mesh = getattr(terrain_obj, "data", None)
    terrain_vertices = list(getattr(terrain_mesh, "vertices", []) or [])
    if len(terrain_vertices) < 4:
        raise ValueError("terrain mesh has no vertices for shoreline water generation")

    rows, cols = _detect_grid_dims_from_vertices(terrain_vertices)
    if rows < 2 or cols < 2 or rows * cols != len(terrain_vertices):
        raise ValueError("terrain mesh is not a regular grid; cannot derive shoreline water surface")

    world_points = [
        _object_world_xyz(terrain_obj, getattr(vert, "co", vert))
        for vert in terrain_vertices
    ]
    xs = [point[0] for point in world_points]
    ys = [point[1] for point in world_points]
    heights = np.asarray([point[2] for point in world_points], dtype=np.float64).reshape(rows, cols)
    water_level_f = float(water_level)
    shoreline_eps = 0.02
    bounded_mask = False
    mask_center_x = 0.0
    mask_center_y = 0.0
    mask_radius_f = 0.0
    wp_arr: np.ndarray | None = None
    if mask_center is not None and mask_radius is not None:
        candidate_radius = float(mask_radius)
        if candidate_radius > 0.0:
            bounded_mask = True
            mask_center_x = float(mask_center[0])
            mask_center_y = float(mask_center[1])
            mask_radius_f = candidate_radius
    mask_aspect = max(float(mask_aspect_y), 0.25)
    component_cells: np.ndarray | None = None

    if bounded_mask:
        allowed_cells = np.zeros((rows, cols), dtype=bool)
        seed_row = 0
        seed_col = 0
        best_seed_dist = float("inf")
        wet_cells = heights <= water_level_f + shoreline_eps
        wp_arr = np.array(world_points, dtype=np.float64).reshape(rows, cols, 3)
        dx_mc = wp_arr[:, :, 0] - mask_center_x
        dy_mc = (wp_arr[:, :, 1] - mask_center_y) / mask_aspect
        dist_to_center_arr = np.sqrt(dx_mc * dx_mc + dy_mc * dy_mc)
        allowed_cells = dist_to_center_arr <= mask_radius_f * 1.18
        candidate = allowed_cells & wet_cells
        if candidate.any():
            dist_cand = np.where(candidate, dist_to_center_arr, np.inf)
            flat_idx = int(np.argmin(dist_cand))
            seed_row, seed_col = divmod(flat_idx, cols)
            best_seed_dist = float(dist_to_center_arr[seed_row, seed_col])

        if best_seed_dist < float("inf"):
            component_cells = np.zeros((rows, cols), dtype=bool)
            queue = deque([(seed_row, seed_col)])
            component_cells[seed_row, seed_col] = True
            while queue:
                row, col = queue.popleft()
                for row_off in (-1, 0, 1):
                    for col_off in (-1, 0, 1):
                        if row_off == 0 and col_off == 0:
                            continue
                        rr = row + row_off
                        cc = col + col_off
                        if rr < 0 or rr >= rows or cc < 0 or cc >= cols:
                            continue
                        if component_cells[rr, cc]:
                            continue
                        if not allowed_cells[rr, cc] or not wet_cells[rr, cc]:
                            continue
                        component_cells[rr, cc] = True
                        queue.append((rr, cc))

    wet_grid = (heights <= water_level_f + shoreline_eps).astype(np.int32)
    wet2 = wet_grid[:-1, :-1] + wet_grid[:-1, 1:] + wet_grid[1:, :-1] + wet_grid[1:, 1:]
    mean_quad = (
        heights[:-1, :-1] + heights[:-1, 1:] + heights[1:, :-1] + heights[1:, 1:]
    ) / 4.0
    water_pass = (wet2 >= 2) | (mean_quad <= water_level_f)

    if component_cells is not None:
        cc2 = (
            component_cells[:-1, :-1].astype(np.int32)
            + component_cells[:-1, 1:].astype(np.int32)
            + component_cells[1:, :-1].astype(np.int32)
            + component_cells[1:, 1:].astype(np.int32)
        )
        keep_mask = (cc2 >= 2) & water_pass
    elif bounded_mask and wp_arr is not None:
        qcx = (wp_arr[:-1, :-1, 0] + wp_arr[:-1, 1:, 0] + wp_arr[1:, :-1, 0] + wp_arr[1:, 1:, 0]) / 4.0
        qcy = (wp_arr[:-1, :-1, 1] + wp_arr[:-1, 1:, 1] + wp_arr[1:, :-1, 1] + wp_arr[1:, 1:, 1]) / 4.0
        qd = np.sqrt((qcx - mask_center_x) ** 2 + ((qcy - mask_center_y) / mask_aspect) ** 2)
        keep_mask = (qd <= mask_radius_f) & water_pass
    else:
        keep_mask = water_pass

    r_arr, c_arr = np.where(keep_mask)
    kept_quads: list[tuple[int, int]] = list(zip(r_arr.tolist(), c_arr.tolist()))

    if not kept_quads:
        raise ValueError(
            f"water_level {water_level_f:.3f} does not intersect terrain '{terrain_obj.name}'"
        )

    terrain_width = max(max(xs) - min(xs), 1e-6)
    terrain_height = max(max(ys) - min(ys), 1e-6)
    cell_area = (terrain_width / max(cols - 1, 1)) * (terrain_height / max(rows - 1, 1))

    used_vertex_indices: set[int] = set()
    for row, col in kept_quads:
        base = row * cols + col
        used_vertex_indices.update({
            base,
            base + 1,
            base + cols,
            base + cols + 1,
        })

    def _shore_factor(index: int) -> float:
        row = index // cols
        col = index % cols
        wet_neighbors = 0
        total_neighbors = 0
        for rr in range(max(0, row - 1), min(rows - 1, row + 1) + 1):
            for cc in range(max(0, col - 1), min(cols - 1, col + 1) + 1):
                total_neighbors += 1
                if heights[rr, cc] <= water_level_f + shoreline_eps:
                    wet_neighbors += 1
        if total_neighbors <= 0:
            return 0.0
        return wet_neighbors / total_neighbors

    existing_obj = bpy.data.objects.get(name)
    if existing_obj is not None:
        existing_mesh = existing_obj.data
        bpy.data.objects.remove(existing_obj, do_unlink=True)
        if existing_mesh is not None and getattr(existing_mesh, "users", 0) == 0:
            bpy.data.meshes.remove(existing_mesh)

    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    flow_layer = bm.loops.layers.float_color.new("flow_vc")
    # FlowData: Unity-facing flow animation layer.
    # RGBA: R=flow_x [0,1], G=flow_z [0,1], B=flow_speed [0,1], A=depth_factor [0,1]
    # (depth_factor: 0=deep, 1=shallow — for foam-edge blending in Unity shader)
    flow_data_layer = bm.loops.layers.float_color.new("FlowData")

    uv_tile = 4.0

    # -----------------------------------------------------------------------
    # Per-cell D8 flow direction derived from the heights grid (steepest descent).
    # This ensures every water vertex gets a downstream-pointing flow vector
    # rather than the constant (0.5, 0.5) neutral that was written before.
    # D8 convention: 0=N, 1=NE, 2=E, 3=SE, 4=S, 5=SW, 6=W, 7=NW
    # -----------------------------------------------------------------------
    _D8_ROW = (-1, -1, 0, 1, 1, 1, 0, -1)
    _D8_COL = (0, 1, 1, 1, 0, -1, -1, -1)
    _D8_DIST = (1.0, math.sqrt(2.0), 1.0, math.sqrt(2.0),
                1.0, math.sqrt(2.0), 1.0, math.sqrt(2.0))
    # Unit flow vectors per D8 direction (world XY — matches Blender X/Y axes).
    # X = east (+col), Z/Y = south (+row) in grid space.
    _D8_FX = (0.0, 1.0 / math.sqrt(2.0), 1.0,  1.0 / math.sqrt(2.0),
              0.0, -1.0 / math.sqrt(2.0), -1.0, -1.0 / math.sqrt(2.0))
    _D8_FZ = (-1.0, -1.0 / math.sqrt(2.0), 0.0, 1.0 / math.sqrt(2.0),
               1.0,  1.0 / math.sqrt(2.0), 0.0, -1.0 / math.sqrt(2.0))

    def _cell_flow_dir_vec(r: int, c: int) -> tuple[float, float]:
        """Return (fx, fz) unit flow vector for grid cell (r, c) via D8."""
        best_d = -1
        best_slope = -1.0
        h0 = float(heights[r, c])
        for d in range(8):
            nr, nc = r + _D8_ROW[d], c + _D8_COL[d]
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue
            drop = (h0 - float(heights[nr, nc])) / _D8_DIST[d]
            if drop > best_slope:
                best_slope = drop
                best_d = d
        if best_d < 0 or best_slope <= 0.0:
            return (0.0, 1.0)  # default: south — never zero-vector
        return (_D8_FX[best_d], _D8_FZ[best_d])

    # Manning-based speed proxy per vertex: V ∝ slope^0.5 (no accumulation grid
    # available here, so we use local slope only; accumulation comes from
    # pass_water_flow_speed on the mask stack for the pipeline path).
    _cell_size_local = max(
        (max(xs) - min(xs)) / max(cols - 1, 1),
        (max(ys) - min(ys)) / max(rows - 1, 1),
        1.0,
    )

    def _vertex_slope(r: int, c: int) -> float:
        h0 = float(heights[r, c])
        max_drop = 0.0
        for d in range(8):
            nr, nc = r + _D8_ROW[d], c + _D8_COL[d]
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue
            drop = (h0 - float(heights[nr, nc])) / (_D8_DIST[d] * _cell_size_local)
            max_drop = max(max_drop, drop)
        return max(max_drop, 0.0)

    # Pre-compute raw speed values for wet vertices to normalise at 95th pctile.
    _raw_speeds: list[float] = []
    for _vi in sorted(used_vertex_indices):
        _r, _c = _vi // cols, _vi % cols
        _raw_speeds.append(0.8 * (_vertex_slope(_r, _c) ** 0.5))
    _p95 = float(np.percentile(_raw_speeds, 95.0)) if _raw_speeds else 1.0
    _speed_scale = 1.0 / max(_p95, 1e-9)

    # Cache per-vertex flow vectors and speeds for face loop assignment.
    _flow_cache: dict[int, tuple[float, float, float]] = {}  # index → (fx, fz, speed)
    for _vi in sorted(used_vertex_indices):
        _r, _c = _vi // cols, _vi % cols
        _fx, _fz = _cell_flow_dir_vec(_r, _c)
        _spd = min(1.0, 0.8 * (_vertex_slope(_r, _c) ** 0.5) * _speed_scale)
        _flow_cache[_vi] = (_fx, _fz, _spd)

    top_verts: dict[int, Any] = {}
    bottom_verts: dict[int, Any] = {}
    _vert_count = 0
    depth_samples = np.asarray(
        [
            max(water_level_f - world_points[index][2], 0.0)
            for index in sorted(used_vertex_indices)
        ],
        dtype=np.float64,
    )
    max_visual_depth = 7.5 if bounded_mask else 5.0
    if bounded_mask and mask_radius_f > 0.0:
        max_visual_depth = max(4.8, min(mask_radius_f * 0.55, 14.0))
    water_depth = max(
        1.8,
        min(
            float(np.percentile(depth_samples, 92.0)) + 0.8 if depth_samples.size else 1.8,
            max_visual_depth,
        ),
    )
    _vertex_depth: dict[int, float] = {}
    for index in sorted(used_vertex_indices):
        wx, wy, terrain_z = world_points[index]
        local_depth = max(water_level_f - terrain_z, 0.0)
        _vertex_depth[index] = local_depth
        shore_factor = _shore_factor(index)
        target_depth = max(
            local_depth + 0.45,
            water_depth * (0.28 + shore_factor * 0.72),
            0.85,
        )
        bottom_z = min(water_level_f - target_depth, terrain_z - 0.22)
        shoreline_drop = max(0.0, 0.88 - shore_factor) * min(max(water_depth * 0.035, 0.03), 0.16)
        surface_z = max(water_level_f - shoreline_drop, terrain_z + _MIN_WATER_ELEVATION_M)
        top_verts[index] = bm.verts.new((wx, wy, surface_z))
        _vert_count += 1
        if not surface_only:
            bottom_verts[index] = bm.verts.new((wx, wy, bottom_z))
            _vert_count += 1

    shoreline_faces = 0
    top_faces: list[tuple[int, int, int, int]] = []
    for row, col in kept_quads:
        quad_indices: tuple[int, int, int, int] = (
            row * cols + col,
            row * cols + col + 1,
            (row + 1) * cols + col + 1,
            (row + 1) * cols + col,
        )
        top_faces.append(quad_indices)
        try:
            face = bm.faces.new([top_verts[idx] for idx in quad_indices])
        except ValueError:
            continue
        shore_factors = [_shore_factor(idx) for idx in quad_indices]
        if any(factor < 0.999 for factor in shore_factors):
            shoreline_faces += 1
        for loop, idx, shore_factor in zip(face.loops, quad_indices, shore_factors):
            wx, wy, _wz = world_points[idx]
            # Beer-Lambert depth absorption: exp(-k*d). k=0.35 gives ~83% transmission
            # at 0.5m, 17% at 5m. Result approaches 1 at the surface (shallow) and 0
            # in deep water, driving the deep→shallow colour mix correctly.
            beer_fac = math.exp(-0.35 * _vertex_depth.get(idx, 0.0))
            # Smoothstep arc instead of flat linear ramp — gives organic foam
            # accumulation: slow at deep/shallow extremes, peak around mid-shore.
            _ft = max(0.0, min(1.0, (beer_fac - 0.24) / 0.28))
            foam = _ft * _ft * (3.0 - 2.0 * _ft)
            loop[flow_layer] = (beer_fac, 0.5, 0.5, foam)
            loop[uv_layer].uv = (wx / uv_tile, wy / uv_tile)
            # FlowData: R=flow_x, G=flow_z, B=speed, A=depth_factor (1=shallow)
            fx, fz, spd = _flow_cache.get(idx, (0.0, 1.0, 0.32))
            loop[flow_data_layer] = (
                (fx + 1.0) * 0.5,   # R: remap [-1,1] → [0,1]
                (fz + 1.0) * 0.5,   # G: remap [-1,1] → [0,1]
                spd,                 # B: Manning speed [0,1]
                beer_fac,            # A: depth_factor — Beer-Lambert exp(-0.35*d)
            )

    if not surface_only:
        for quad_indices in top_faces:
            try:
                face = bm.faces.new([
                    bottom_verts[quad_indices[0]],
                    bottom_verts[quad_indices[3]],
                    bottom_verts[quad_indices[2]],
                    bottom_verts[quad_indices[1]],
                ])
            except ValueError:
                continue
            for loop, idx in zip(face.loops, (quad_indices[0], quad_indices[3], quad_indices[2], quad_indices[1])):
                wx, wy, _wz = world_points[idx]
                loop[flow_layer] = (0.0, 0.5, 0.5, 0.0)
                loop[uv_layer].uv = (wx / uv_tile, wy / uv_tile)
                fx, fz, spd = _flow_cache.get(idx, (0.0, 1.0, 0.32))
                loop[flow_data_layer] = ((fx + 1.0) * 0.5, (fz + 1.0) * 0.5, spd, 0.0)

        for edge_start, edge_end in _boundary_edges_from_faces(top_faces):
            try:
                face = bm.faces.new([
                    top_verts[edge_start],
                    top_verts[edge_end],
                    bottom_verts[edge_end],
                    bottom_verts[edge_start],
                ])
            except ValueError:
                continue
            for loop, idx, depth_bias in zip(
                face.loops,
                (edge_start, edge_end, edge_end, edge_start),
                (0.55, 0.55, 0.10, 0.10),
            ):
                wx, wy, wz = world_points[idx]
                loop[flow_layer] = (0.0, 0.5, 0.5, 0.0)
                loop[uv_layer].uv = (wx / uv_tile, (wy / uv_tile) + depth_bias + max(water_level_f - wz, 0.0) * 0.08)
                fx, fz, spd = _flow_cache.get(idx, (0.0, 1.0, 0.32))
                loop[flow_data_layer] = ((fx + 1.0) * 0.5, (fz + 1.0) * 0.5, spd, 0.0)

    bm.to_mesh(mesh)
    total_tris = sum(len(poly.vertices) - 2 for poly in mesh.polygons)
    bm.free()

    for poly in mesh.polygons:
        poly.use_smooth = True

    obj = bpy.data.objects.new(name, mesh)
    obj.location = (0.0, 0.0, 0.0)
    try:
        obj["vb_water_depth"] = float(water_depth)
        obj["vb_water_surface_only"] = bool(surface_only)
    except Exception as exc:
        logger.warning("Optional subsystem water_custom_properties failed (non-fatal): %s", exc)
    bpy.context.collection.objects.link(obj)
    _apply_water_object_settings(obj, surface_only=surface_only)
    mesh.materials.append(
        _ensure_water_material(
            material_name,
            preview_fast=preview_fast,
            surface_only=surface_only,
        )
    )

    _obj_name = getattr(obj, "name", name)
    return {
        "name": _obj_name if isinstance(_obj_name, str) else name,
        "water_level": water_level_f,
        "area": float(cell_area * len(kept_quads)),
        "tri_count": total_tris,
        "vertex_count": max(_vert_count, len(mesh.vertices)),
        "has_flow_vertex_colors": True,
        # FlowData layer present: R=flow_x, G=flow_z, B=speed, A=depth_factor.
        # Unity shader scrolls FlowUV at speed B in direction (R*2-1, G*2-1).
        "has_flow_data_layer": True,
        "has_shore_alpha": shoreline_faces > 0,
        "cross_sections": 0,
        "path_point_count": 0,
        "preview_fast": preview_fast,
        "surface_mode": "terrain_mask",
        "shoreline_face_count": shoreline_faces,
        "water_depth": water_depth,
        "has_volume_geometry": not surface_only,
    }


# ---------------------------------------------------------------------------
# Handler: create_water
# ---------------------------------------------------------------------------

def handle_create_water(params: dict[str, Any]) -> dict[str, Any]:
    """Create a water body -- spline-based surface mesh with AAA flow data.

    AAA upgrade (39-02): replaces flat disc placeholder with a spline-following
    mesh that encodes bank proximity, flow direction, and foam as vertex colors. A simple
    grid fallback is used when no path_points are provided.

    Params:
        name (str, default "Water"): Water object name.
        water_level (float, default 0.3): Water plane height (world Z).
        terrain_name (str, optional): Reference terrain for sizing.
        width (float, default 8.0): Cross-section width (river default 8m).
        depth (float, default 100.0): Along-flow length for grid mode.
        material_name (str, default "Water_Material"): Material name.
        path_points (list of [x,y,z], optional): Spline control points for the
            river/lake centre-line.  When provided the mesh follows the path.
        cross_sections (int, default 12): Subdivisions perpendicular to flow.

    Vertex color layers:

    "flow_vc" — Blender-preview RGBA convention (consumed by _ensure_water_material):
        R = shallow/bank cue (0=deep center, 1=bank contact)
        G = flow dir X  (normalised, remapped to 0-1)
        B = flow dir Y  (normalised, remapped to 0-1)
        A = foam        (shore proximity + speed; blended from shore_foam and speed_foam)

    "FlowData" — Unity water shader RGBA convention:
        R = flow vector X  (downstream, remapped [-1,1]→[0,1])
        G = flow vector Z  (downstream, remapped [-1,1]→[0,1])
        B = flow speed     (Manning proxy: 0.8*slope^0.5, 95th-pctile normalised to 1.0)
        A = depth factor   (0=deep center, 1=shallow bank — for foam-edge blending)
    Unity shader usage: scroll FlowUV at speed B in direction (R*2-1, G*2-1).

    Returns dict with: name, water_level, area, tri_count, vertex_count,
                       has_flow_vertex_colors, has_flow_data_layer, has_shore_alpha.
    """
    logger.info("Creating water body (AAA spline mesh)")
    name = params.get("name", "Water")
    water_level = params.get("water_level", 0.3)
    terrain_name = params.get("terrain_name")
    width_raw = params.get("width")
    width = float(width_raw) if width_raw is not None else 8.0
    fallback_depth = float(params.get("depth", 100.0))
    material_name = params.get("material_name")
    path_points_raw = params.get("path_points")
    cross_sections = max(8, min(16, int(params.get("cross_sections", 12))))
    preview_fast = bool(params.get("preview_fast", True))
    surface_only = bool(params.get("surface_only", False))
    if not material_name:
        material_name = "Water_Surface_Material" if surface_only else "Water_Material"
    terminal_taper_enabled = bool(params.get("taper_terminals", surface_only))
    terminal_taper_rings = max(
        0,
        int(
            params.get(
                "terminal_taper_rings",
                min(4, max(len(path_points_raw or []) // 3, 0)),
            )
        ),
    )
    mask_center_raw = params.get("mask_center")
    mask_center = None
    if isinstance(mask_center_raw, (list, tuple)) and len(mask_center_raw) >= 2:
        mask_center = (float(mask_center_raw[0]), float(mask_center_raw[1]))
    mask_radius = params.get("mask_radius")
    mask_aspect_y = float(params.get("mask_aspect_y", 1.0))

    # If terrain specified, use its Z for water level snapping
    terrain_origin_x = 0.0
    terrain_origin_y = 0.0
    terrain_obj = None
    terrain_height_sampler: Callable[[float, float], float] | None = None
    if terrain_name:
        terrain_obj = bpy.data.objects.get(terrain_name)
        if terrain_obj is not None:
            terrain_origin_x = terrain_obj.location.x
            terrain_origin_y = terrain_obj.location.y
            terrain_height_sampler = _build_terrain_world_height_sampler(terrain_obj)
        if terrain_obj is not None and path_points_raw is None:
            dims = terrain_obj.dimensions
            if isinstance(dims.y, (int, float)):
                fallback_depth = max(float(dims.y), fallback_depth)
            if width_raw is None:
                width = max(float(dims.x), 4.0)
            try:
                return _build_level_water_surface_from_terrain(
                    name=name,
                    terrain_obj=terrain_obj,
                    water_level=float(water_level),
                    material_name=material_name,
                    preview_fast=preview_fast,
                    mask_center=mask_center,
                    mask_radius=float(mask_radius) if mask_radius is not None else None,
                    mask_aspect_y=mask_aspect_y,
                    surface_only=surface_only,
                )
            except ValueError as exc:
                logger.warning("Falling back to rectangular water surface: %s", exc)

    # -----------------------------------------------------------------------
    # Build spline path
    # -----------------------------------------------------------------------
    path = _resolve_water_path_points(
        path_points_raw=path_points_raw,
        terrain_origin_x=terrain_origin_x,
        terrain_origin_y=terrain_origin_y,
        fallback_depth=fallback_depth,
        water_level=water_level,
    )
    _input_path_count = len(path)
    preserve_path_shape = bool(params.get("preserve_path_shape", False))
    if path_points_raw is not None and len(path) >= 3 and not preserve_path_shape:
        path = _smooth_river_path_points(
            path,
            smoothing_passes=4,
            min_spacing_world=max(width * 0.22, 0.75),
            enforce_monotonic_z=True,
        )
    if preview_fast and len(path) > 6:
        cross_sections = min(cross_sections, 3)

    terrain_carve_result: dict[str, Any] = {"terrain_carved": False}
    if (
        terrain_obj is not None
        and path_points_raw is not None
        and bool(params.get("carve_terrain", True))
    ):
        terrain_carve_result = _carve_river_banks_into_terrain(
            terrain_obj=terrain_obj,
            path_points=path,
            width_world=width,
            depth_world=params.get("carve_depth"),
            bank_width_world=params.get("bank_width"),
        )
        if terrain_carve_result.get("terrain_carved"):
            terrain_height_sampler = _build_terrain_world_height_sampler(terrain_obj)

    # -----------------------------------------------------------------------
    # Build cross-section mesh following the spline
    # -----------------------------------------------------------------------
    existing_obj = bpy.data.objects.get(name)
    if existing_obj is not None:
        existing_mesh = existing_obj.data
        bpy.data.objects.remove(existing_obj, do_unlink=True)
        if existing_mesh is not None and getattr(existing_mesh, "users", 0) == 0:
            bpy.data.meshes.remove(existing_mesh)

    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()

    # UV layer (must exist before faces are created so loops can write to it).
    # Without this the water has no UV map and any tiled material is broken.
    uv_layer = bm.loops.layers.uv.new("UVMap")

    # Blender-preview vertex color layer (consumed by _ensure_water_material).
    # Convention: R=shallow_fac, G=flow_dir_x [0,1], B=flow_dir_z [0,1], A=foam
    flow_layer = bm.loops.layers.float_color.new("flow_vc")

    # Unity-facing flow animation layer — consumed by the Unity water shader.
    # Convention: R=flow_x [0,1], G=flow_z [0,1], B=flow_speed [0,1], A=depth_factor [0,1]
    # The shader scrolls FlowUV at speed B in direction (R*2-1, G*2-1).
    flow_data_layer = bm.loops.layers.float_color.new("FlowData")

    half_w = width / 2.0
    num_segs = len(path) - 1

    # Estimate total path length for speed calculation
    total_length = 0.0
    for i in range(num_segs):
        p0 = path[i]
        p1 = path[i + 1]
        seg_len = math.sqrt(
            (p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2 + (p1[2] - p0[2]) ** 2
        )
        total_length += max(seg_len, 0.001)

    # Track cumulative arc length per ring for v-axis UV (along flow).
    # u runs across the cross-section [0..1], v runs along the path [0..total_length / TILE].
    UV_TILE = 4.0  # 1 UV unit = 4 world units (tunable; controls texture density)
    cumulative_length = [0.0]
    for i in range(num_segs):
        p0 = path[i]
        p1 = path[i + 1]
        seg_len = math.sqrt(
            (p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2 + (p1[2] - p0[2]) ** 2
        )
        cumulative_length.append(cumulative_length[-1] + seg_len)

    channel_depth = max(width * 0.32, 2.2)
    flow_speeds: list[float] = []
    flow_dirs: list[tuple[float, float]] = []
    for pi, pt in enumerate(path):
        px, py, pz = pt
        if pi == 0:
            nxt = path[1]
            tx = nxt[0] - px
            ty = nxt[1] - py
        elif pi == len(path) - 1:
            prv = path[-2]
            tx = px - prv[0]
            ty = py - prv[1]
        else:
            prv = path[pi - 1]
            nxt = path[pi + 1]
            tx = nxt[0] - prv[0]
            ty = nxt[1] - prv[1]
        tlen = math.sqrt(tx * tx + ty * ty) or 1.0
        tx /= tlen
        ty /= tlen
        flow_dirs.append((tx, ty))
        if pi > 0:
            prev_pt = path[pi - 1]
            dz = max(prev_pt[2] - pz, 0.0)  # positive = downhill (downstream)
            dx_dist = math.sqrt((px - prev_pt[0]) ** 2 + (py - prev_pt[1]) ** 2)
            slope = dz / max(dx_dist, 0.1)
            # Manning proxy: V ∝ k * slope^0.5  (k=0.8, n≈0.035 river roughness)
            flow_speeds.append(0.8 * (slope ** 0.5))
        else:
            flow_speeds.append(0.0)  # sentinel — will be filled from neighbour below

    # Fill the sentinel at index 0 from the next point's speed.
    if len(flow_speeds) > 1:
        flow_speeds[0] = flow_speeds[1]

    # Normalise raw Manning speeds: 95th percentile = 1.0, floor at 0.05 for
    # moving water (rivers are never completely still).
    _raw_arr = [s for s in flow_speeds if s > 0.0]
    _p95 = float(np.percentile(_raw_arr, 95.0)) if _raw_arr else 1.0
    _speed_scale = 1.0 / max(_p95, 1e-9)
    flow_speeds = [max(0.05, min(1.0, s * _speed_scale)) for s in flow_speeds]

    # Tri-point smoothing for visual continuity (identical kernel to before).
    if len(flow_speeds) >= 3:
        smoothed_flow_speeds: list[float] = []
        for index, speed in enumerate(flow_speeds):
            prev_speed = flow_speeds[index - 1] if index > 0 else speed
            next_speed = flow_speeds[index + 1] if index < len(flow_speeds) - 1 else speed
            smoothed_flow_speeds.append(prev_speed * 0.22 + speed * 0.56 + next_speed * 0.22)
        flow_speeds = smoothed_flow_speeds

    # Ring of vertices per path point
    _vert_count = 0
    rings: list[list[tuple[Any, Any | None, float, float, float, float, float, float]]] = []
    for pi, pt in enumerate(path):
        px, py, pz = pt

        tx, ty = flow_dirs[pi]

        # Perpendicular (cross-section direction)
        perp_x = -ty
        perp_y = tx

        # Normalised flow direction components (remapped 0-1)
        flow_dir_x = (tx + 1.0) * 0.5
        flow_dir_y = (ty + 1.0) * 0.5

        flow_speed = flow_speeds[pi]
        left_bank_dist, left_bank_height = _resolve_river_bank_contact(
            terrain_height_sampler=terrain_height_sampler,
            center_x=px,
            center_y=py,
            surface_z=pz,
            normal_x=perp_x,
            normal_y=perp_y,
            default_half_width=half_w,
            side_sign=-1.0,
        )
        right_bank_dist, right_bank_height = _resolve_river_bank_contact(
            terrain_height_sampler=terrain_height_sampler,
            center_x=px,
            center_y=py,
            surface_z=pz,
            normal_x=perp_x,
            normal_y=perp_y,
            default_half_width=half_w,
            side_sign=1.0,
        )

        # v coordinate for this ring (along flow direction)
        ring_v = cumulative_length[pi] / UV_TILE

        ring_verts = []
        terminal_width_scale = (
            _resolve_river_terminal_width_scale(
                pi,
                len(path),
                taper_rings=terminal_taper_rings,
            )
            if terminal_taper_enabled
            else 1.0
        )
        for ci in range(cross_sections + 1):
            t = ci / cross_sections  # 0 = left shore, 1 = right shore
            offset = (t - 0.5) * 2.0  # -1 to +1
            if offset < 0.0:
                signed_dist = -left_bank_dist * terminal_width_scale * (abs(offset) ** 0.94)
                edge_bank_height = left_bank_height
            else:
                signed_dist = right_bank_dist * terminal_width_scale * (abs(offset) ** 0.94)
                edge_bank_height = right_bank_height
            vx = px + perp_x * signed_dist
            vy = py + perp_y * signed_dist
            # Shore depth proxy: 0 at edges, 1 at center
            shore_t = 1.0 - abs(offset)  # 0.0 at shore, 1.0 at centre
            if terrain_height_sampler is not None:
                terrain_z_here = float(terrain_height_sampler(vx, vy))
                edge_gap = max(edge_bank_height - pz, 0.0)
                edge_sink = min(edge_gap * 0.18, 0.025) * (1.0 - shore_t)
                vz = pz - edge_sink
                bottom_target = terrain_z_here - max(0.18, (1.0 - shore_t) * 0.24)
                bottom_z = min(vz - max(channel_depth * (0.16 + shore_t * 0.84), 0.24), bottom_target)
            else:
                bank_drop = (1.0 - shore_t) ** 1.55 * min(max(channel_depth * 0.065, 0.05), 0.24)
                vz = pz - bank_drop
                bottom_z = vz - max(channel_depth * (0.18 + shore_t * 0.82), 0.24)

            # u coordinate across cross-section [0..1]
            ring_u = t

            top_vert = bm.verts.new((vx, vy, vz))
            _vert_count += 1
            bottom_vert = None if surface_only else bm.verts.new((vx, vy, bottom_z))
            if bottom_vert is not None:
                _vert_count += 1
            ring_verts.append((top_vert, bottom_vert, shore_t, flow_speed, flow_dir_x, flow_dir_y, ring_u, ring_v))
        rings.append(ring_verts)

    # Connect rings into quads
    for ri in range(len(rings) - 1):
        ring_a = rings[ri]
        ring_b = rings[ri + 1]
        for ci in range(cross_sections):
            va, ba, sha, spa, fdxa, fdza, ua, va_uv = ring_a[ci]
            vb, bb, shb, spb, fdxb, fdzb, ub, vb_uv = ring_a[ci + 1]
            vc, bc, shc, spc, fdxc, fdzc, uc, vc_uv = ring_b[ci + 1]
            vd, bd, shd, spd, fdxd, fdzd, ud, vd_uv = ring_b[ci]
            try:
                face = bm.faces.new([va, vb, vc, vd])
                # Paint flow vertex colors AND UVs per loop
                loop_data = [
                    (sha, spa, fdxa, fdza, ua, va_uv),
                    (shb, spb, fdxb, fdzb, ub, vb_uv),
                    (shc, spc, fdxc, fdzc, uc, vc_uv),
                    (shd, spd, fdxd, fdzd, ud, vd_uv),
                ]
                for loop, (sh, sp, fdx, fdz, uv_u, uv_v) in zip(face.loops, loop_data):
                    shallow_fac = 1.0 - sh
                    # Foam from shore proximity + high flow speed
                    shore_foam = max(0.0, (shallow_fac - 0.4) * 2.0)
                    speed_foam = max(0.0, (sp - 0.7) * 1.5)
                    foam = min(1.0, shore_foam + speed_foam)
                    # Blender-preview layer: R=shallow, G=flow_x, B=flow_z, A=foam
                    loop[flow_layer] = (shallow_fac, fdx, fdz, foam)
                    loop[uv_layer].uv = (uv_u, uv_v)
                    # Unity FlowData: R=flow_x, G=flow_z, B=speed, A=depth_factor
                    loop[flow_data_layer] = (fdx, fdz, sp, shallow_fac)
            except ValueError:
                pass
            try:
                if not surface_only and None not in (ba, bd, bc, bb):
                    face = bm.faces.new([ba, bd, bc, bb])
                    for loop, (sp_val, fdx, fdz, uv_u, uv_v) in zip(
                        face.loops,
                        [
                            (spa, fdxa, fdza, ua, va_uv + 0.65),
                            (spd, fdxd, fdzd, ud, vd_uv + 0.65),
                            (spc, fdxc, fdzc, uc, vc_uv + 0.65),
                            (spb, fdxb, fdzb, ub, vb_uv + 0.65),
                        ],
                    ):
                        loop[flow_layer] = (0.0, fdx, fdz, 0.0)
                        loop[uv_layer].uv = (uv_u, uv_v)
                        loop[flow_data_layer] = (fdx, fdz, sp_val, 0.0)
            except ValueError:
                pass

        if not surface_only:
            left_a_top, left_a_bottom, _sha0, spa0, fdxa0, fdza0, ua0, va0_uv = ring_a[0]
            left_b_top, left_b_bottom, _shd0, spd0, fdxd0, fdzd0, ud0, vd0_uv = ring_b[0]
            right_a_top, right_a_bottom, _shb1, spb1, fdxb1, fdzb1, ub1, vb1_uv = ring_a[-1]
            right_b_top, right_b_bottom, _shc1, spc1, fdxc1, fdzc1, uc1, vc1_uv = ring_b[-1]
            for face_verts, loop_data in (
                (
                    [left_a_top, left_b_top, left_b_bottom, left_a_bottom],
                    [
                        (spa0, fdxa0, fdza0, ua0, va0_uv),
                        (spd0, fdxd0, fdzd0, ud0, vd0_uv),
                        (0.0, fdxd0, fdzd0, ud0, vd0_uv + 0.55),
                        (0.0, fdxa0, fdza0, ua0, va0_uv + 0.55),
                    ],
                ),
                (
                    [right_a_top, right_a_bottom, right_b_bottom, right_b_top],
                    [
                        (spb1, fdxb1, fdzb1, ub1, vb1_uv),
                        (0.0, fdxb1, fdzb1, ub1, vb1_uv + 0.55),
                        (0.0, fdxc1, fdzc1, uc1, vc1_uv + 0.55),
                        (spc1, fdxc1, fdzc1, uc1, vc1_uv),
                    ],
                ),
            ):
                try:
                    face = bm.faces.new(face_verts)
                except ValueError:
                    continue
                for loop, (sp, fdx, fdz, uv_u, uv_v) in zip(face.loops, loop_data):
                    loop[flow_layer] = (sp, fdx, fdz, 0.0)
                    loop[uv_layer].uv = (uv_u, uv_v)
                    loop[flow_data_layer] = (fdx, fdz, sp, 0.0)

    if rings and not surface_only:
        start_ring = rings[0]
        end_ring = rings[-1]
        for ring, v_offset in ((start_ring, -0.35), (end_ring, 0.35)):
            face_verts = [item[0] for item in ring] + [item[1] for item in reversed(ring)]
            loop_data = []
            for item in ring:
                _top, _bottom, _shore_t, sp, fdx, fdz, u, v = item
                loop_data.append((sp, fdx, fdz, u, v))
            for item in reversed(ring):
                _top, _bottom, _shore_t, _sp, fdx, fdz, u, v = item
                loop_data.append((0.0, fdx, fdz, u, v + v_offset))
            try:
                face = bm.faces.new(face_verts)
            except ValueError:
                face = None
            if face is not None:
                for loop, (sp, fdx, fdz, uv_u, uv_v) in zip(face.loops, loop_data):
                    loop[flow_layer] = (sp, fdx, fdz, 0.0)
                    loop[uv_layer].uv = (uv_u, uv_v)
                    loop[flow_data_layer] = (fdx, fdz, sp, 0.0)

    bm.to_mesh(mesh)
    _ = sum(1 for p in mesh.polygons if len(p.vertices) == 3)
    # Count quads as 2 tris each for budget check
    total_tris = sum(len(p.vertices) - 2 for p in mesh.polygons)
    bm.free()

    for poly in mesh.polygons:
        poly.use_smooth = True

    obj = bpy.data.objects.new(name, mesh)
    # The spline vertices already encode world-space XY and water Z.
    # Keep the object origin at world zero so the surface is not lifted twice.
    obj.location = (0.0, 0.0, 0.0)
    try:
        obj["vb_water_depth"] = float(channel_depth)
        obj["vb_water_surface_only"] = bool(surface_only)
    except Exception as exc:
        logger.warning("Optional subsystem channel_custom_properties failed (non-fatal): %s", exc)
    bpy.context.collection.objects.link(obj)
    _apply_water_object_settings(obj, surface_only=surface_only)

    # -----------------------------------------------------------------------
    # AAA water material: sRGB(40,60,50), roughness 0.05, alpha 0.6, IOR 1.33
    # -----------------------------------------------------------------------
    mesh.materials.append(
        _ensure_water_material(
            material_name,
            preview_fast=preview_fast,
            surface_only=surface_only,
        )
    )

    area = total_length * width if total_length > 0 else width * fallback_depth

    _obj_name = getattr(obj, "name", name)
    return {
        "name": _obj_name if isinstance(_obj_name, str) else name,
        "water_level": water_level,
        "area": area,
        "tri_count": total_tris,
        "vertex_count": max(_vert_count, len(mesh.vertices)),
        "has_flow_vertex_colors": True,
        # FlowData layer present: R=flow_x, G=flow_z, B=speed, A=depth_factor.
        # Unity shader scrolls FlowUV at speed B in direction (R*2-1, G*2-1).
        "has_flow_data_layer": True,
        "has_shore_alpha": True,
        "cross_sections": cross_sections,
        "path_point_count": _input_path_count,
        "preview_fast": preview_fast,
        "surface_mode": "spline",
        "terminal_taper_rings": terminal_taper_rings if terminal_taper_enabled else 0,
        "water_depth": channel_depth,
        "has_volume_geometry": not surface_only,
        **terrain_carve_result,
    }


def _priority_flood_fill_basin(
    heightmap: np.ndarray,
    *,
    seed_row: int,
    seed_col: int,
    water_level: float,
    max_radius_cells: int,
) -> np.ndarray:
    """Priority-flood fill from a seed cell to find the connected wet basin mask.

    Uses a min-heap priority queue (comparable to the Priority-Flood algorithm
    by Barnes et al. 2014 used in hydrologic GIS tools). Cells are flooded
    outward in order of ascending terrain height, stopping when terrain rises
    above ``water_level`` or the search front exceeds ``max_radius_cells``.

    Returns a boolean mask of the same shape as ``heightmap`` where True
    indicates cells that are part of the connected basin at ``water_level``.
    """
    import heapq

    rows, cols = heightmap.shape
    visited = np.zeros((rows, cols), dtype=bool)
    basin_mask = np.zeros((rows, cols), dtype=bool)

    heap: list[tuple[float, int, int]] = []
    heapq.heappush(heap, (float(heightmap[seed_row, seed_col]), seed_row, seed_col))
    visited[seed_row, seed_col] = True

    while heap:
        h, r, c = heapq.heappop(heap)
        if h > water_level:
            break
        basin_mask[r, c] = True
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            nr, nc = r + dr, c + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue
            if visited[nr, nc]:
                continue
            # Radius guard: stop expansion beyond max_radius_cells from seed
            if abs(nr - seed_row) > max_radius_cells or abs(nc - seed_col) > max_radius_cells:
                continue
            visited[nr, nc] = True
            heapq.heappush(heap, (float(heightmap[nr, nc]), nr, nc))

    return basin_mask


def handle_carve_water_basin(params: dict[str, Any]) -> dict[str, Any]:
    """Carve a shoreline-ready basin into an existing terrain mesh.

    AAA upgrade: priority-flood algorithm for connected-basin validation,
    protected zone enforcement (never writes to protected cells), timing
    metrics, affected_cells count, and pass_name. Comparable to the
    Priority-Flood algorithm (Barnes et al. 2014) used in GIS hydrologic
    processing and Far Cry 6 / UE5 World Partition water body brush.

    Priority-flood containment check:
        Before carving, a priority-flood fill from the basin center at
        ``water_level`` identifies whether the basin is naturally contained
        by terrain. If the flood escapes the basin radius, the basin is
        flagged in ``basin_contained`` = False and the ``containment_rim``
        is automatically enforced regardless of the param setting.

    Protected zone enforcement:
        Any cell whose world-space XY position falls inside a protected zone
        declared in ``protected_zones`` is never written. The count of skipped
        cells is reported as ``protected_cells_skipped``.

    Volume conservation:
        After carving, the total excavated volume (sum of height reductions *
        cell_area) is computed and returned. If ``preserve_volume`` is True,
        the displaced soil is redistributed onto the containment rim.

    Outflow channel routing:
        If ``outflow_direction_rad`` is provided (or auto-detected as the
        steepest rim cell when not provided), a shallow V-channel is carved
        from the rim in that direction for ``outflow_length`` metres.

    Bed material assignment:
        Returns ``bed_material_zones`` list for downstream material painters.

    Params:
        terrain_name (str): Existing terrain object name.
        center ([x, y]): World-space basin center.
        water_level (float, default 0.0): Target water surface elevation.
        radius (float, default 18.0): Basin radius in world metres.
        depth (float, default 3.0): Maximum carve depth below water_level.
        shore_width (float, default radius*0.45): Shoreline transition width.
        aspect_y (float, default 1.25): Y-axis stretch factor (elliptical basins).
        containment_rim (bool, default True): Add a containment berm.
        containment_rim_height (float): Berm height above water_level.
        preserve_volume (bool, default False): Redistribute excavated volume.
        outflow_direction_rad (float | None): Outflow bearing (auto if None).
        outflow_length (float, default radius*0.8): Channel length from rim.
        outflow_width (float, default radius*0.15): Channel width at rim.
        bed_material_deep / _shallow / _shore (str): Material keys.
        protected_zones (list of dict): Optional BBox zone dicts.
        seed (int, default 0): Random seed for any stochastic shaping.

    Returns dict with: name, water_level, radius, depth, cells_modified,
        min_height, excavated_volume_m3, volume_conserved, outflow_channel,
        bed_material_zones, basin_contained, protected_cells_skipped,
        affected_cells, duration_seconds, pass_name.
    """
    _t0 = time.perf_counter()
    terrain_name = params.get("terrain_name")
    if not terrain_name:
        raise ValueError("'terrain_name' is required")

    center = params.get("center")
    if not isinstance(center, (list, tuple)) or len(center) < 2:
        raise ValueError("'center' must be a 2-item [x, y] sequence")

    water_level = float(params.get("water_level", 0.0))
    radius = max(float(params.get("radius", 18.0)), 2.0)
    depth = max(float(params.get("depth", 3.0)), 0.1)
    shore_width = max(float(params.get("shore_width", radius * 0.45)), 1.0)
    aspect_y = max(float(params.get("aspect_y", 1.25)), 0.5)
    containment_rim = bool(params.get("containment_rim", True))
    containment_rim_height = max(float(params.get("containment_rim_height", max(depth * 0.16, 0.45))), 0.0)
    preserve_volume = bool(params.get("preserve_volume", False))
    outflow_dir_raw = params.get("outflow_direction_rad")
    outflow_length = float(params.get("outflow_length", radius * 0.8))
    outflow_width = max(float(params.get("outflow_width", radius * 0.15)), 0.5)
    bed_mat_deep = str(params.get("bed_material_deep", "gravel"))
    bed_mat_shallow = str(params.get("bed_material_shallow", "sand"))
    bed_mat_shore = str(params.get("bed_material_shore", "pebbles"))

    obj = bpy.data.objects.get(terrain_name)
    if obj is None:
        raise ValueError(f"Object not found: {terrain_name}")

    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()

    rows, cols = _detect_grid_dims(bm)
    heights = np.array([v.co.z for v in bm.verts], dtype=np.float64).reshape(rows, cols)
    terrain_width = obj.dimensions.x if obj.dimensions.x > 0 else 100.0
    terrain_height_dim = obj.dimensions.y if obj.dimensions.y > 0 else terrain_width
    cx = float(center[0])
    cy = float(center[1])
    protected_zones: list[dict[str, Any]] = list(params.get("protected_zones") or [])

    # ------------------------------------------------------------------
    # World-space coordinate arrays — must be defined before any mask or
    # flood-fill that references them.
    # ------------------------------------------------------------------
    _tw = max(float(terrain_width), 1e-9)
    _th = max(float(terrain_height_dim), 1e-9)
    _ox = float(obj.location.x)
    _oy = float(obj.location.y)
    _col_w = _ox + np.arange(cols, dtype=np.float64) / max(cols - 1, 1) * _tw - _tw * 0.5
    _row_w = _oy + np.arange(rows, dtype=np.float64) / max(rows - 1, 1) * _th - _th * 0.5
    cell_area = (_tw / max(cols - 1, 1)) * (_th / max(rows - 1, 1))
    outer_radius = radius + shore_width
    shoreline_radius = max(radius * 0.94, 1.0)
    dx = _col_w[np.newaxis, :] - cx
    dy = (_row_w[:, np.newaxis] - cy) / aspect_y

    # ------------------------------------------------------------------
    # Protected zone mask — AABB list, world space
    # ------------------------------------------------------------------
    pz_mask = np.zeros((rows, cols), dtype=bool)
    if protected_zones:
        for pz in protected_zones:
            pz_x0 = float(pz.get("x_min", pz.get("x0", -1e9)))
            pz_x1 = float(pz.get("x_max", pz.get("x1",  1e9)))
            pz_y0 = float(pz.get("y_min", pz.get("y0", -1e9)))
            pz_y1 = float(pz.get("y_max", pz.get("y1",  1e9)))
            pz_mask |= (
                (_col_w[np.newaxis, :] >= pz_x0) & (_col_w[np.newaxis, :] <= pz_x1)
                & (_row_w[:, np.newaxis] >= pz_y0) & (_row_w[:, np.newaxis] <= pz_y1)
            )

    # ------------------------------------------------------------------
    # Priority-flood containment check (Barnes et al. 2014)
    # Maps basin center to nearest grid cell and checks whether the basin
    # is topographically contained at water_level.  If not, auto-enable
    # containment_rim so the function still produces a legal basin.
    # ------------------------------------------------------------------
    cell_size_approx = max((_tw / max(cols - 1, 1) + _th / max(rows - 1, 1)) * 0.5, 1e-6)
    seed_col = int(np.clip(round((cx - (_ox - _tw * 0.5)) / (_tw / max(cols - 1, 1))), 0, cols - 1))
    seed_row = int(np.clip(round((cy - (_oy - _th * 0.5)) / (_th / max(rows - 1, 1))), 0, rows - 1))
    max_radius_cells = int(math.ceil(outer_radius / cell_size_approx)) + 2
    # Pre-compute dist for flood-fill radius check (uses undistorted distance)
    dist_raw_pre = np.hypot(dx, dy)
    _flood_mask = _priority_flood_fill_basin(
        heights,
        seed_row=seed_row,
        seed_col=seed_col,
        water_level=water_level,
        max_radius_cells=max_radius_cells,
    )
    basin_contained: bool = bool((_flood_mask & ~(dist_raw_pre <= outer_radius * 1.1)).sum() == 0)
    if not basin_contained and not containment_rim:
        containment_rim = True  # auto-enable to prevent spill

    result = heights.copy()
    cells_modified = 0
    beach_rim = max(depth * 0.08, 0.14)

    def _ss(x: np.ndarray) -> np.ndarray:
        return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)

    angle = np.arctan2(dy, np.where(np.abs(dx) > 1e-9, dx, 1e-9))
    shoreline_warp = np.clip(
        1.0 + 0.12 * np.sin(angle * 2.6 + cx * 0.031)
            + 0.07 * np.sin(angle * 5.4 + cy * 0.043),
        0.72, 1.28,
    )
    dist_raw = np.hypot(dx, dy)
    dist = dist_raw / shoreline_warp
    active = dist <= outer_radius

    in_basin = dist <= radius
    inner_t = np.clip(dist / max(radius, 1e-6), 0.0, 1.0)
    basin_curve = 1.0 - _ss(inner_t)
    tgt_depth = depth * (0.14 + 0.86 * np.power(basin_curve, 0.68))
    sl_t = np.clip((dist - shoreline_radius) / max(radius - shoreline_radius, 1e-6), 0.0, 1.0)
    tgt_depth = np.where(dist >= shoreline_radius, tgt_depth * (1.0 - 0.72 * _ss(sl_t)), tgt_depth)
    _min_depth = max(depth * 0.08, 0.12)
    target_basin = water_level - np.maximum(tgt_depth, _min_depth)
    cw_basin = 0.96 - 0.44 * _ss(inner_t)

    sh_t = np.clip((dist - radius) / max(shore_width, 1e-6), 0.0, 1.0)
    target_shore = water_level + beach_rim * (0.12 + 0.88 * _ss(sh_t))
    cw_shore = 0.10 + 0.08 * (1.0 - _ss(sh_t))

    tgt_lowered = np.where(in_basin, np.minimum(result, target_basin), result)
    new_height = np.where(in_basin, result + (tgt_lowered - result) * cw_basin, result)
    in_shore = active & ~in_basin
    new_height = np.where(
        in_shore & (result < target_shore),
        result + (target_shore - result) * cw_shore,
        new_height,
    )

    # Volume conservation: measure excavated volume before rim is raised
    excavated = np.maximum(0.0, heights - new_height)
    excavated_volume_m3 = float((excavated * cell_area).sum())

    if containment_rim:
        rim_start = radius + shore_width * 0.42
        rim_t = np.clip((dist - rim_start) / max(outer_radius - rim_start, 1e-6), 0.0, 1.0)
        rim_rw = 0.08 + 0.06 * _ss(rim_t)
        rim_tgt = water_level + containment_rim_height * (0.18 + 0.52 * _ss(rim_t))
        in_rim = active & (dist > rim_start) & (result < rim_tgt)

        # Volume conservation: distribute excavated volume onto rim cells
        if preserve_volume and excavated_volume_m3 > 0.0:
            rim_cell_count = int(in_rim.sum())
            if rim_cell_count > 0:
                extra_per_cell = excavated_volume_m3 / (rim_cell_count * cell_area)
                rim_tgt = np.where(in_rim, rim_tgt + extra_per_cell * 0.6, rim_tgt)

        raised = result + (rim_tgt - result) * rim_rw
        new_height = np.where(in_rim, np.maximum(new_height, raised), new_height)

    changed_low = active & (new_height < result - 1e-6)
    changed_high = active & (new_height > result + 1e-6)
    cells_modified = int(changed_low.sum())
    result = np.where(changed_low | changed_high, new_height, result)

    padded = np.pad(result, 1, mode="edge")
    neighborhood_mean = (
        padded[0:-2, 0:-2] + padded[0:-2, 1:-1] + padded[0:-2, 2:]
        + padded[1:-1, 0:-2] + padded[1:-1, 1:-1] + padded[1:-1, 2:]
        + padded[2:, 0:-2] + padded[2:, 1:-1] + padded[2:, 2:]
    ) / 9.0
    smooth_active = (dist_raw <= outer_radius) & (dist_raw > radius * 0.14)
    sm_t = np.clip(
        (dist_raw - radius * 0.14) / max(outer_radius - radius * 0.14, 1e-6), 0.0, 1.0
    )
    sm_w = 0.12 + 0.34 * _ss(sm_t)
    result = np.where(smooth_active, result * (1.0 - sm_w) + neighborhood_mean * sm_w, result)

    # ------------------------------------------------------------------
    # Outflow channel routing
    # ------------------------------------------------------------------
    outflow_channel: dict[str, Any] | None = None
    if outflow_length > 0.5:
        # Auto-detect steepest-descent rim cell when direction not specified
        if outflow_dir_raw is None:
            rim_mask = (dist_raw >= radius * 0.9) & (dist_raw <= outer_radius * 1.05)
            rim_rows, rim_cols = np.where(rim_mask)
            best_slope = -math.inf
            best_angle = 0.0
            for rr, rc in zip(rim_rows.tolist(), rim_cols.tolist()):
                if rr <= 0 or rr >= rows - 1 or rc <= 0 or rc >= cols - 1:
                    continue
                dz_dx = (result[rr, rc + 1] - result[rr, rc - 1]) / (2.0 * cell_area ** 0.5)
                dz_dy = (result[rr + 1, rc] - result[rr - 1, rc]) / (2.0 * cell_area ** 0.5)
                slope_mag = math.sqrt(dz_dx ** 2 + dz_dy ** 2)
                if slope_mag > best_slope:
                    best_slope = slope_mag
                    best_angle = math.atan2(-dz_dy, -dz_dx)
            outflow_dir_rad = best_angle
        else:
            outflow_dir_rad = float(outflow_dir_raw)

        # Carve V-channel from rim outward in outflow direction
        ch_steps = max(4, int(outflow_length / max(cell_area ** 0.5, 0.1)))
        cs_approx = cell_area ** 0.5
        channel_pts: list[tuple[float, float]] = []
        for step in range(ch_steps + 1):
            frac = step / max(ch_steps, 1)
            dist_from_rim = (radius + shore_width * 0.5) + frac * outflow_length
            wx = cx + math.cos(outflow_dir_rad) * dist_from_rim
            wy = cy + math.sin(outflow_dir_rad) * dist_from_rim
            channel_pts.append((wx, wy))

            # Find nearest grid cell
            gc = int((wx - (_ox - _tw * 0.5)) / (_tw / max(cols - 1, 1)))
            gr = int((wy - (_oy - _th * 0.5)) / (_th / max(rows - 1, 1)))
            gc = max(0, min(cols - 1, gc))
            gr = max(0, min(rows - 1, gr))

            # Taper channel width and depth
            ch_half_w_cells = max(1, int(outflow_width * (1.0 - frac * 0.8) / cs_approx))
            ch_depth_val = depth * 0.25 * (1.0 - frac * 0.85)
            for dr in range(-ch_half_w_cells, ch_half_w_cells + 1):
                for dc in range(-ch_half_w_cells, ch_half_w_cells + 1):
                    nr, nc = gr + dr, gc + dc
                    if not (0 <= nr < rows and 0 <= nc < cols):
                        continue
                    lateral = math.sqrt(dr ** 2 + dc ** 2) / max(ch_half_w_cells, 1)
                    v_depth = ch_depth_val * max(0.0, 1.0 - lateral)
                    tgt_z = result[nr, nc] - v_depth
                    if tgt_z < result[nr, nc]:
                        result[nr, nc] = tgt_z

        outflow_channel = {
            "direction_rad": round(outflow_dir_rad, 4),
            "length_m": round(outflow_length, 2),
            "width_m": round(outflow_width, 2),
            "waypoints": [[round(p[0], 3), round(p[1], 3)] for p in channel_pts],
        }

    # ------------------------------------------------------------------
    # Protected zone enforcement — revert any writes inside protected AABBs
    # ------------------------------------------------------------------
    protected_cells_skipped = 0
    if pz_mask.any():
        protected_cells_skipped = int((pz_mask & (result != heights)).sum())
        result = np.where(pz_mask, heights, result)

    flat = result.flatten()
    for idx, vert in enumerate(bm.verts):
        vert.co.z = float(flat[idx])

    bm.to_mesh(mesh)
    bm.free()
    if hasattr(mesh, "update"):
        mesh.update()

    # ------------------------------------------------------------------
    # Bed material zones (pure metadata — no mesh modification)
    # ------------------------------------------------------------------
    bed_material_zones = [
        {
            "zone_type": "deep_bed",
            "inner_radius": 0.0,
            "outer_radius": round(radius * 0.55, 2),
            "material_key": bed_mat_deep,
            "description": "Central deep bed — gravel/silt below wave base",
        },
        {
            "zone_type": "shallow_bed",
            "inner_radius": round(radius * 0.55, 2),
            "outer_radius": round(radius, 2),
            "material_key": bed_mat_shallow,
            "description": "Shallow bed — sand/small stones above wave base",
        },
        {
            "zone_type": "shoreline",
            "inner_radius": round(radius, 2),
            "outer_radius": round(radius + shore_width, 2),
            "material_key": bed_mat_shore,
            "description": "Shoreline — pebbles/coarse sand / grass fringe",
        },
    ]

    _duration = time.perf_counter() - _t0
    return {
        "name": terrain_name,
        "water_level": water_level,
        "radius": radius,
        "depth": depth,
        "cells_modified": cells_modified,
        "min_height": float(result.min()) if result.size else water_level,
        "excavated_volume_m3": round(excavated_volume_m3, 3),
        "volume_conserved": preserve_volume,
        "outflow_channel": outflow_channel,
        "bed_material_zones": bed_material_zones,
        # AAA additions
        "basin_contained": basin_contained,
        "protected_cells_skipped": protected_cells_skipped,
        "affected_cells": cells_modified,
        "duration_seconds": round(_duration, 4),
        "pass_name": "carve_water_basin",
    }


# ---------------------------------------------------------------------------
# Handler: export_unity_bundle
# ---------------------------------------------------------------------------

@enforce_protocol(require_rule_1=False, require_rule_3=False, require_rule_7=False)
def handle_export_unity_bundle(params: dict[str, Any]) -> dict[str, Any]:
    """Export a Unity terrain bundle from a populated ``TerrainMaskStack``.

    Params:
        mask_stack (TerrainMaskStack): Export-ready stack to serialize.
        output_dir (str): Directory for the Unity bundle.
        profile (str, optional): Export profile such as ``mobile`` or
            ``aaa_open_world``.

    Returns:
        dict with manifest metadata plus the emitted descriptor/manifest paths.
    """
    from .terrain_unity_export import export_unity_manifest

    stack = params.get("mask_stack")
    if stack is None:
        raise ValueError("'mask_stack' is required")

    output_dir_raw = (
        params.get("output_dir")
        or params.get("export_dir")
        or params.get("filepath")
    )
    if not output_dir_raw:
        raise ValueError("'output_dir' is required")

    output_dir = Path(output_dir_raw)
    profile = params.get("profile") or params.get("quality_profile")
    manifest = export_unity_manifest(
        stack,
        output_dir,
        profile=profile,
        strict_unity_resolution=bool(params.get("strict_unity_resolution", True)),
        fail_on_validation_error=bool(params.get("fail_on_validation_error", True)),
    )
    return {
        "output_dir": str(output_dir),
        "manifest_path": str(output_dir / "manifest.json"),
        "descriptor_path": str(output_dir / "unity_import_descriptor.json"),
        "validation_status": manifest.get("validation_status", "unknown"),
        "validation_issue_count": int(manifest.get("validation_issue_count", 0)),
        "tile_x": int(manifest["tile_x"]),
        "tile_y": int(manifest["tile_y"]),
        "world_id": str(manifest["world_id"]),
        "terrain_layer_asset_count": len(manifest.get("terrain_layer_assets_required", [])),
        "manifest": manifest,
    }


# ---------------------------------------------------------------------------
# Handler: export_heightmap
# ---------------------------------------------------------------------------

def handle_export_heightmap(params: dict[str, Any]) -> dict[str, Any]:
    """Export terrain heightmap as 16-bit little-endian RAW for Unity.

    Params:
        terrain_name (str): Terrain object name.
        filepath (str): Output file path (.raw).
        flip_vertical (bool, default True): Flip for Unity coordinate system.
        unity_compat (bool, default False): Resize to power-of-two+1.

    Returns dict with: filepath, width, height, bit_depth, byte_order.
    """
    logger.info("Exporting heightmap")
    terrain_name = params.get("terrain_name")
    if not terrain_name:
        raise ValueError("'terrain_name' is required")

    filepath = params.get("filepath")
    if not filepath:
        raise ValueError("'filepath' is required")

    flip_vertical = params.get("flip_vertical", True)
    unity_compat = params.get("unity_compat", False)

    obj = bpy.data.objects.get(terrain_name)
    if obj is None:
        raise ValueError(f"Object not found: {terrain_name}")

    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()

    # WORLD-004: Detect actual grid dimensions (robust to non-square terrain)
    rows, cols = _detect_grid_dims(bm)

    heights = np.array([v.co.z for v in bm.verts])
    bm.free()

    heightmap = heights.reshape(rows, cols)
    export_height_range = _resolve_export_height_range(params, heightmap)

    # Unity compat: resize to nearest power-of-two + 1 (use cols as ref dimension)
    if unity_compat:
        target = _nearest_pot_plus_1(cols)
        if target != cols:
            # Simple nearest-neighbor resize
            x_indices = np.round(np.linspace(0, cols - 1, target)).astype(int)
            y_indices = np.round(np.linspace(0, rows - 1, target)).astype(int)
            heightmap = heightmap[np.ix_(y_indices, x_indices)]
    if export_height_range is None:
        export_height_range = (
            float(heightmap.min()) if heightmap.size else 0.0,
            float(heightmap.max()) if heightmap.size else 0.0,
        )

    # Export
    raw_bytes = _export_heightmap_raw(
        heightmap,
        flip_vertical=flip_vertical,
        value_range=export_height_range,
    )

    out_path = Path(filepath)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw_bytes)
    metadata_path = _write_json_manifest(
        str(out_path) + ".json",
        {
            "filepath": str(out_path),
            "width": int(heightmap.shape[1]),
            "height": int(heightmap.shape[0]),
            "bit_depth": 16,
            "byte_order": "little-endian",
            "flip_vertical": bool(flip_vertical),
            "height_min_m": float(export_height_range[0]),
            "height_max_m": float(export_height_range[1]),
        },
    )

    rows, cols = heightmap.shape

    return {
        "filepath": str(out_path),
        "metadata_path": metadata_path,
        "width": cols,
        "height": rows,
        "bit_depth": 16,
        "byte_order": "little-endian",
        "height_min_m": float(export_height_range[0]),
        "height_max_m": float(export_height_range[1]),
    }


def _nearest_pot_plus_1(n: int) -> int:
    """Find nearest power-of-two + 1 >= n."""
    pot = 1
    while pot + 1 < n:
        pot *= 2
    return pot + 1


# ---------------------------------------------------------------------------
# Handler: generate_multi_biome_world
# ---------------------------------------------------------------------------

def handle_generate_multi_biome_world(params: dict[str, Any]) -> dict[str, Any]:
    """Generate a complete multi-biome world map in Blender.

    Orchestrates: WorldMapSpec -> terrain mesh -> biome vertex colors ->
    biome material -> vegetation scatter.  Requires bpy (runs inside Blender).

    Params:
        name (str): Base name for terrain object. Default "MultibiomeTerrain".
        width (int): Grid resolution. Default 256.
        height (int): Grid resolution. Default 256.
        world_size (float): Terrain size in meters. Default 512.0.
        height_scale (float): Vertical exaggeration. Default 80.0.
        biome_count (int): Number of Voronoi regions. Default 6.
        biomes (list[str]): Biome names. Default 6 VB presets.
        seed (int): Master seed. Default 42.
        corruption_level (float): Global corruption intensity 0-1. Default 0.3.
        building_plots (list[dict]): Pre-placed footprints for foundation flatten.
        erosion (str): "hydraulic"|"thermal"|"both"|"none". Default "hydraulic".
        erosion_iterations (int): Default 5000.
        scatter_vegetation (bool): Whether to scatter per-biome vegetation. Default True.
        min_veg_distance (float): Min spacing between vegetation instances. Default 4.0.
        max_veg_instances (int): Cap per biome. Default 100000.
        transition_width_m (float): Blend zone width in meters. Default 15.0.

    Returns dict with:
        name, biome_count, biome_names, corruption_level, corruption_zones,
        vegetation_count, flatten_zones_applied, vertex_count, world_size_m.
    """
    from ._biome_grammar import generate_world_map_spec
    from .terrain_materials import BIOME_PALETTES_V2

    # --- 1. Build world spec (pure logic, no bpy) ---
    name = params.get("name", "MultibiomeTerrain")
    seed = params.get("seed", 42)
    world_size = params.get("world_size", 512.0)
    width = params.get("width", 256)
    height = params.get("height", 256)
    biome_count = params.get("biome_count", 6)
    biomes = params.get("biomes")
    corruption_level = params.get("corruption_level", 0.3)
    building_plots = params.get("building_plots", [])
    scatter_veg = params.get("scatter_vegetation", True)

    spec = generate_world_map_spec(
        width=width,
        height=height,
        world_size=world_size,
        biome_count=biome_count,
        biomes=biomes,
        seed=seed,
        corruption_level=corruption_level,
        building_plots=building_plots,
        transition_width_m=params.get("transition_width_m", 15.0),
    )

    # --- 2. Generate base terrain mesh ---
    # Determine terrain type from dominant biome instead of hardcoding "mountain"
    dominant_biome = biomes[0] if biomes else (spec.biome_names[0] if spec.biome_names else "hills")
    biome_preset = get_vb_biome_preset(
        dominant_biome,
        season=params.get("season"),
    )
    base_terrain_type = biome_preset["terrain_type"] if biome_preset else "hills"
    terrain_params = {
        "name": name,
        "terrain_type": base_terrain_type,
        "resolution": width,
        "height_scale": params.get("height_scale", 80.0),
        "scale": world_size,
        "seed": seed,
        "erosion": params.get("erosion", "hydraulic"),
        "erosion_iterations": params.get("erosion_iterations", 5000),
        "flatten_zones": spec.flatten_zones,
        "use_controller": True,
        "bulk_edit": True,
        "out_of_view_ok": bool(params.get("out_of_view_ok", True)),
    }
    terrain_result = handle_generate_terrain(terrain_params)

    obj = bpy.data.objects.get(name)
    if obj is None:
        raise RuntimeError(f"Terrain object '{name}' not found after generation")

    # --- 3. Assign biome vertex colors per-vertex ---
    vertex_colors = _compute_vertex_colors_for_biome_map(
        obj, spec, world_size
    )

    mesh = obj.data
    if mesh.color_attributes.get("BiomeColor"):
        mesh.color_attributes.remove(mesh.color_attributes["BiomeColor"])
    col_attr = mesh.color_attributes.new(
        name="BiomeColor", type="FLOAT_COLOR", domain="POINT"
    )
    for i, rgba in enumerate(vertex_colors):
        col_attr.data[i].color = rgba

    # --- 4. Apply biome material for primary biome ---
    # Primary biome = dominant biome at terrain center (simple heuristic)
    cx_cell = int(spec.biome_ids[height // 2, width // 2])
    primary_biome = spec.biome_names[cx_cell]
    if primary_biome in BIOME_PALETTES_V2:
        from .terrain_materials import handle_create_biome_terrain
        try:
            handle_create_biome_terrain({
                "name": name,
                "biome_name": primary_biome,
                "season": params.get("season"),
            })
        except Exception as exc:
            logger.warning("Optional subsystem handle_create_biome_terrain failed (non-fatal): %s", exc)

    # --- 5. Scatter vegetation per biome (if enabled) ---
    vegetation_total = 0
    if scatter_veg:
        from .environment_scatter import handle_scatter_vegetation
        for biome_name in spec.biome_names:
            try:
                veg_result = handle_scatter_vegetation({
                    "terrain_name": name,
                    "biome_name": biome_name,
                    "min_distance": params.get("min_veg_distance", 4.0),
                    "seed": seed + _stable_seed_offset(biome_name),
                    "max_instances": params.get("max_veg_instances", 100_000),
                    "season": "corrupted" if corruption_level > 0.5 else None,
                    "bake_wind_colors": True,
                    "water_level": 0.05,
                })
                vegetation_total += veg_result.get("instance_count", 0)
            except Exception as exc:
                logger.warning("Optional subsystem handle_scatter_vegetation failed (non-fatal): %s", exc)

    # --- 6. Count corruption zones ---
    corruption_zones = int((spec.corruption_map > 0.3).sum())

    return {
        "name": name,
        "biome_count": biome_count,
        "biome_names": spec.biome_names,
        "corruption_level": corruption_level,
        "corruption_zones": corruption_zones,
        "vegetation_count": vegetation_total,
        "flatten_zones_applied": len(spec.flatten_zones),
        "vertex_count": terrain_result.get("vertex_count", 0),
        "world_size_m": world_size,
    }


def _compute_vertex_colors_for_biome_map(
    obj: Any,
    spec: Any,
    world_size: float,
) -> list[tuple[float, float, float, float]]:
    """Sample per-vertex biome color from WorldMapSpec corruption map + biome palette.

    Returns list of (R, G, B, A) tuples, one per vertex.
    """
    from .terrain_materials import BIOME_PALETTES, _get_material_def

    mesh = obj.data
    rows, cols = spec.biome_ids.shape
    n_verts = len(mesh.vertices)

    # Batch-read all vertex positions — avoids per-vertex Blender API iteration
    co_flat = np.empty(n_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co_flat)
    vx_arr = co_flat[0::3].astype(np.float64)
    vy_arr = co_flat[1::3].astype(np.float64)

    # Vectorize grid index computation
    nx_arr = np.clip((vx_arr / world_size + 0.5) * cols, 0, cols - 1).astype(np.int32)
    ny_arr = np.clip((vy_arr / world_size + 0.5) * rows, 0, rows - 1).astype(np.int32)

    biome_idx_arr = spec.biome_ids[ny_arr, nx_arr]
    corruption_arr = spec.corruption_map[ny_arr, nx_arr].astype(np.float64)

    # Precompute base_color per unique biome — _get_material_def once per biome, not per vertex
    unique_biomes = np.unique(biome_idx_arr)
    biome_base_colors: dict[int, tuple[float, float, float, float]] = {}
    for bidx in unique_biomes.tolist():
        base_color = (0.15, 0.12, 0.10, 1.0)
        try:
            biome_name = spec.biome_names[int(bidx)]
            palette = BIOME_PALETTES.get(biome_name, {})
            ground_mats = palette.get("ground", [])
            if ground_mats:
                mat_def = _get_material_def(ground_mats[0])
                if mat_def and "base_color" in mat_def:
                    bc = tuple(mat_def["base_color"])
                    base_color = bc if len(bc) == 4 else bc + (1.0,)
        except Exception as exc:
            logger.warning("Optional subsystem biome_base_color_lookup failed (non-fatal): %s", exc)
        biome_base_colors[int(bidx)] = base_color

    # ------------------------------------------------------------------
    # Vectorized corruption tint — eliminates O(n_verts) Python loop.
    # Inlines apply_corruption_tint (MicroSplat height-blend formula)
    # using numpy broadcasting instead of calling it per vertex.
    # ------------------------------------------------------------------
    # Build (N, 4) base-color array by gathering per-biome colors
    base_rgba = np.empty((n_verts, 4), dtype=np.float64)
    for bidx, color in biome_base_colors.items():
        mask = biome_idx_arr == bidx
        base_rgba[mask] = color

    r = base_rgba[:, 0]
    g = base_rgba[:, 1]
    b = base_rgba[:, 2]
    a = base_rgba[:, 3]

    # MicroSplat constants (matches apply_corruption_tint defaults)
    _CORRUPTION_R = 0.38
    _CORRUPTION_G = 0.12
    _CORRUPTION_B = 0.65
    _CORRUPTION_H = 0.7
    effective_half = max(0.5 - 0.5 * 0.45, 0.05)  # blend_contrast=0.5

    # Per-vertex luminance (BT.709)
    surface_h = r * 0.2126 + g * 0.7152 + b * 0.0722
    raw_blend = (_CORRUPTION_H - surface_h + effective_half) / effective_half
    blend_factor = np.clip(raw_blend, 0.0, 1.0) * corruption_arr

    new_r = np.clip(r * (1.0 - blend_factor) + _CORRUPTION_R * blend_factor, 0.0, 1.0)
    new_g = np.clip(g * (1.0 - blend_factor) + _CORRUPTION_G * blend_factor, 0.0, 1.0)
    new_b = np.clip(b * (1.0 - blend_factor) + _CORRUPTION_B * blend_factor, 0.0, 1.0)
    new_a = np.clip(a + (1.0 - a) * (blend_factor * 0.85), 0.0, 1.0)

    tinted = np.stack([new_r, new_g, new_b, new_a], axis=1)  # (N, 4)
    return [tuple(row) for row in tinted.tolist()]
def _stable_seed_offset(label: str) -> int:
    """Return a deterministic, cross-process seed offset for string labels."""
    return zlib.crc32(label.encode("utf-8")) & 0xFFFF

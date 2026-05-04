"""Per-biome vegetation quality system for VeilBreakers dark fantasy environments.

Provides biome-specific vegetation sets (trees, rocks, ground cover), Poisson
disk placement with slope/height filtering, wind vertex color computation for
Unity shader integration, and seasonal material variants.

All compute_* functions are pure-logic (no bpy/bmesh) for testability.
The biome vegetation materializer wires pure placement logic into Blender
scene creation for world-generation callers.

Biomes:
  - thornwood_forest: Mixed healthy-to-blighted forest edge progression
  - corrupted_swamp: Sparse dead trees, mushroom clusters, scattered boulders
  - mountain_pass: Dark pines, heavy boulders, rare crystals
  - cemetery: Hanging willows, moss, gravestones
  - ashen_wastes: Charred stumps, obsidian rocks, ember plants
  - frozen_hollows: Ice-covered pines, frozen boulders, frost lichen
  - blighted_mire: Mangrove roots, toxic mushrooms, sludge rocks
  - ruined_citadel: Overgrown vines, crumbled stone, corrupted saplings
  - desert: Dead brush, cacti-shaped rocks, tumbleweeds
  - coastal: Sea grass, coastal scrub, driftwood
  - grasslands: Tall grass, wildflowers, lone trees
  - mushroom_forest: Giant mushrooms, bioluminescent ground cover, spore clusters
  - crystal_cavern: Crystal growths, mineral formations
  - deep_forest: Massive ancient trees, thick ferns, hanging moss
"""

from __future__ import annotations

import math
import random
import warnings
from functools import partial
from typing import Any, Callable

import numpy as np
from numpy.typing import NDArray

from .terrain_biome_registry import CANONICAL_BIOME_IDS  # noqa: F401 — re-exported for callers
from .terrain_math import stack_world_to_cell
from .terrain_rng import make_rng as _make_rng

_world_to_cell = partial(stack_world_to_cell, rounding="floor")

# ---------------------------------------------------------------------------
# Canonical wind vertex color layout
# ---------------------------------------------------------------------------

# Wind vertex color layout: R=sway_strength, G=sway_frequency, B=phase_offset, A=trunk_sway
WIND_COLOR_LAYOUT = "R:sway_strength G:sway_frequency B:phase_offset A:trunk_sway"

# ---------------------------------------------------------------------------
# Per-biome vegetation configuration
# ---------------------------------------------------------------------------

BIOME_VEGETATION_SETS: dict[str, dict[str, list[dict[str, Any]]]] = {
    "thornwood_forest": {
        "trees": [
            {"type": "tree", "style": "veil_healthy", "density": 0.16, "scale_range": (1.2, 2.6)},
            {"type": "tree", "style": "veil_boundary", "density": 0.10, "scale_range": (1.0, 2.0)},
            {"type": "tree", "style": "veil_blighted", "density": 0.04, "scale_range": (0.8, 1.5)},
        ],
        "ground_cover": [
            {"type": "fern", "density": 0.36, "scale_range": (0.2, 0.5)},
            {"type": "moss", "density": 0.30, "scale_range": (0.3, 0.6)},
            {"type": "grass", "style": "dark_floor", "density": 0.22, "scale_range": (0.2, 0.45)},
        ],
        "rocks": [
            {"type": "rock", "style": "boulder", "density": 0.1, "scale_range": (0.3, 1.0)},
            {"type": "rock", "style": "root_boulder", "density": 0.04, "scale_range": (0.7, 1.6)},
        ],
    },
    "corrupted_swamp": {
        "trees": [
            {"type": "tree", "style": "dead_twisted", "density": 0.2, "scale_range": (0.6, 1.3)},
        ],
        "ground_cover": [
            {"type": "mushroom", "style": "cluster", "density": 0.3, "scale_range": (0.2, 0.6)},
        ],
        "rocks": [
            {"type": "rock", "style": "boulder", "density": 0.05, "scale_range": (0.3, 0.8)},
        ],
    },
    "mountain_pass": {
        "trees": [
            {"type": "tree", "style": "dark_pine", "density": 0.15, "scale_range": (1.0, 2.0)},
        ],
        "ground_cover": [],
        "rocks": [
            {"type": "rock", "style": "boulder", "density": 0.2, "scale_range": (0.5, 2.0)},
            {"type": "rock", "style": "crystal", "density": 0.03, "scale_range": (0.3, 0.8)},
        ],
    },
    "cemetery": {
        "trees": [
            {"type": "tree", "style": "willow_hanging", "density": 0.05, "scale_range": (1.2, 2.5)},
        ],
        "ground_cover": [
            {"type": "moss", "density": 0.3, "scale_range": (0.2, 0.4)},
        ],
        "rocks": [
            {"type": "gravestone", "style": "tombstone", "density": 0.15, "scale_range": (0.5, 1.0)},
        ],
    },
    "ashen_wastes": {
        "trees": [
            {"type": "tree", "style": "charred_stump", "density": 0.08, "scale_range": (0.4, 1.0)},
        ],
        "ground_cover": [
            {"type": "ember_plant", "density": 0.15, "scale_range": (0.1, 0.3)},
        ],
        "rocks": [
            {"type": "rock", "style": "obsidian", "density": 0.12, "scale_range": (0.3, 1.2)},
            {"type": "rock", "style": "volcanic", "density": 0.06, "scale_range": (0.5, 1.5)},
        ],
    },
    "frozen_hollows": {
        "trees": [
            {"type": "tree", "style": "ice_pine", "density": 0.12, "scale_range": (1.0, 2.2)},
        ],
        "ground_cover": [
            {"type": "frost_lichen", "density": 0.25, "scale_range": (0.1, 0.3)},
        ],
        "rocks": [
            {"type": "rock", "style": "frozen_boulder", "density": 0.15, "scale_range": (0.5, 1.8)},
            {"type": "rock", "style": "ice_crystal", "density": 0.04, "scale_range": (0.3, 0.7)},
        ],
    },
    "blighted_mire": {
        "trees": [
            {"type": "tree", "style": "mangrove_root", "density": 0.18, "scale_range": (0.7, 1.4)},
        ],
        "ground_cover": [
            {"type": "mushroom", "style": "toxic", "density": 0.2, "scale_range": (0.15, 0.4)},
        ],
        "rocks": [
            {"type": "rock", "style": "sludge_rock", "density": 0.08, "scale_range": (0.3, 0.9)},
        ],
    },
    "ruined_citadel": {
        "trees": [
            {"type": "tree", "style": "corrupted_sapling", "density": 0.06, "scale_range": (0.3, 0.8)},
        ],
        "ground_cover": [
            {"type": "vine", "density": 0.35, "scale_range": (0.3, 0.8)},
            {"type": "moss", "density": 0.2, "scale_range": (0.2, 0.5)},
        ],
        "rocks": [
            {"type": "rock", "style": "crumbled_stone", "density": 0.18, "scale_range": (0.3, 1.0)},
        ],
    },
    "desert": {
        "trees": [
            {"type": "bush", "style": "dead_brush", "density": 0.06, "scale_range": (0.3, 0.7)},
        ],
        "ground_cover": [
            {"type": "tumbleweed", "density": 0.04, "scale_range": (0.2, 0.5)},
        ],
        "rocks": [
            {"type": "rock", "style": "cactus_rock", "density": 0.08, "scale_range": (0.5, 1.5)},
            {"type": "rock", "style": "wind_eroded", "density": 0.05, "scale_range": (0.4, 1.2)},
        ],
    },
    "coastal": {
        "trees": [
            {"type": "bush", "style": "coastal_scrub", "density": 0.10, "scale_range": (0.3, 0.8)},
        ],
        "ground_cover": [
            {"type": "grass", "style": "sea_grass", "density": 0.25, "scale_range": (0.2, 0.5)},
        ],
        "rocks": [
            {"type": "rock", "style": "driftwood", "density": 0.08, "scale_range": (0.3, 1.0)},
            {"type": "rock", "style": "sea_worn", "density": 0.10, "scale_range": (0.3, 0.9)},
        ],
    },
    "grasslands": {
        "trees": [
            {"type": "tree", "style": "lone_windswept", "density": 0.03, "scale_range": (1.5, 3.0)},
        ],
        "ground_cover": [
            {"type": "grass", "style": "tall_grass", "density": 0.50, "scale_range": (0.3, 0.8)},
            {"type": "flower", "style": "wildflower", "density": 0.15, "scale_range": (0.1, 0.3)},
        ],
        "rocks": [
            {"type": "rock", "style": "field_stone", "density": 0.04, "scale_range": (0.3, 0.8)},
        ],
    },
    "mushroom_forest": {
        "trees": [
            {"type": "mushroom", "style": "giant_mushroom", "density": 0.12, "scale_range": (1.0, 3.0)},
            {"type": "mushroom", "style": "shelf_mushroom", "density": 0.08, "scale_range": (0.3, 0.8)},
        ],
        "ground_cover": [
            {"type": "moss", "style": "bioluminescent", "density": 0.30, "scale_range": (0.1, 0.3)},
            {"type": "mushroom", "style": "spore_cluster", "density": 0.20, "scale_range": (0.1, 0.4)},
        ],
        "rocks": [
            {"type": "rock", "style": "fungal_log", "density": 0.06, "scale_range": (0.4, 1.0)},
        ],
    },
    "crystal_cavern": {
        "trees": [],
        "ground_cover": [
            {"type": "crystal", "style": "small_growth", "density": 0.20, "scale_range": (0.2, 0.6)},
        ],
        "rocks": [
            {"type": "rock", "style": "crystal_cluster", "density": 0.15, "scale_range": (0.5, 2.0)},
            {"type": "rock", "style": "mineral_formation", "density": 0.10, "scale_range": (0.3, 1.2)},
        ],
    },
    "deep_forest": {
        "trees": [
            {"type": "tree", "style": "ancient_oak", "density": 0.07, "scale_range": (2.0, 4.5)},
            {"type": "tree", "style": "veil_boundary", "density": 0.09, "scale_range": (1.8, 3.8)},
            {"type": "tree", "style": "veil_blighted", "density": 0.05, "scale_range": (1.3, 2.6)},
        ],
        "ground_cover": [
            {"type": "fern", "style": "thick_fern", "density": 0.40, "scale_range": (0.3, 0.7)},
            {"type": "moss", "style": "hanging_moss", "density": 0.30, "scale_range": (0.2, 0.6)},
            {"type": "root", "style": "surface_root", "density": 0.14, "scale_range": (0.4, 1.0)},
        ],
        "rocks": [
            {"type": "rock", "style": "root_boulder", "density": 0.08, "scale_range": (0.5, 1.5)},
        ],
    },
}


# ---------------------------------------------------------------------------
# Seasonal material variant configuration
# ---------------------------------------------------------------------------

_SEASONAL_VARIANTS: dict[str, dict[str, Any]] = {
    "summer": {
        "color_tint": (0.0, 0.0, 0.0),
        "saturation_mult": 1.0,
        "leaf_density": 1.0,
        "roughness_offset": 0.0,
        "description": "Full foliage, standard colors",
    },
    "autumn": {
        "color_tint": (0.3, 0.15, -0.1),
        "saturation_mult": 1.2,
        "leaf_density": 0.7,
        "roughness_offset": 0.05,
        "description": "Orange/red tint, reduced foliage",
    },
    "winter": {
        "color_tint": (0.1, 0.1, 0.15),
        "saturation_mult": 0.5,
        "leaf_density": 0.1,
        "roughness_offset": -0.1,
        "description": "Desaturated, bare branches, frost",
    },
    "corrupted": {
        "color_tint": (0.15, -0.1, 0.2),
        "saturation_mult": 0.8,
        "leaf_density": 0.4,
        "roughness_offset": 0.1,
        "description": "Purple tint, withered foliage",
    },
}


# ---------------------------------------------------------------------------
# Slope / height constraints
# ---------------------------------------------------------------------------

_MAX_TREE_SLOPE_DEGREES = 45.0
_MAX_GROUND_COVER_SLOPE_DEGREES = 55.0
_MAX_ROCK_SLOPE_DEGREES = 75.0
_DEFAULT_WATER_LEVEL = 0.05  # Normalized height below which nothing grows


def _max_slope_for_category(category: str) -> float:
    """Return the maximum slope in degrees for a vegetation category."""
    if category == "trees":
        return _MAX_TREE_SLOPE_DEGREES
    elif category == "ground_cover":
        return _MAX_GROUND_COVER_SLOPE_DEGREES
    elif category == "rocks":
        return _MAX_ROCK_SLOPE_DEGREES
    return _MAX_GROUND_COVER_SLOPE_DEGREES


# ---------------------------------------------------------------------------
# Pure-logic compute functions
# ---------------------------------------------------------------------------

def compute_vegetation_placement(
    terrain_vertices: list[tuple[float, float, float]],
    terrain_faces: list[tuple[int, ...]],
    terrain_normals: list[tuple[float, float, float]],
    biome_name: str,
    area_bounds: tuple[float, float, float, float],
    seed: int = 42,
    min_distance: float = 3.0,
    water_level: float = _DEFAULT_WATER_LEVEL,
    exclusion_zones: list[dict[str, Any]] | None = None,
    moisture_map: Any | None = None,
    competition_radius: float = 0.0,
    lod_distances: list[float] | None = None,
    camera_position: tuple[float, float, float] | None = None,
    adjacent_biome_entries: list[tuple[str, dict[str, Any]]] | None = None,
    ecotone_alpha_fn: Any | None = None,
) -> list[dict[str, Any]]:
    """Compute vegetation placements for a biome on terrain geometry.

    Pure-logic function -- no Blender dependency.

    Uses Bridson Poisson-disk sampling for blue-noise base distribution with
    3-tier hierarchical LOD density modulation:
      - Near-field  (< lod_distances[0]): dense sampling (0.6× min_distance)
        for full-detail individual plant placements.
      - Mid-field   (< lod_distances[1]): base sampling (1.0× min_distance)
        for cluster-level placements.
      - Far-field   (>= lod_distances[1]): coarse sampling (1.8× min_distance)
        for impostor/billboard placements.

    Each placement is tagged with a ``lod_hint`` field (0/1/2) so
    ``build_vegetation_placement_spec`` can use it as a distance tiebreaker.

    Per-candidate filters are applied in order:
      1. Exclusion zones (buildings, roads).
      2. Water-level rejection (below normalised water height).
      3. Moisture filter: each species has optional ``min_moisture`` /
         ``max_moisture`` bounds [0, 1].  A procedural moisture proxy is
         derived from normalised height (low altitude = wetter) unless an
         explicit ``moisture_map`` array is supplied.
      4. Altitude filter: biome entries may carry ``min_altitude`` /
         ``max_altitude`` [0, 1] bounds for altitudinal banding (e.g. treeline).
      5. Slope filter: category-level slope caps (trees < 45°, rocks < 75°).
      6. Species competition: when ``competition_radius > 0``, already-placed
         instances of a different species within that radius suppress a new
         placement.  This creates ecologically plausible species clusters and
         avoids unnatural interleaving.
      7. Density probability roll (modulated by LOD tier density factor).

    Parameters
    ----------
    terrain_vertices : list of (x, y, z) tuples
        Terrain mesh vertex positions.
    terrain_faces : list of index tuples
        Face index lists (reserved for future triangle-based sampling).
    terrain_normals : list of (nx, ny, nz) tuples
        Per-vertex normals for slope calculation.
    biome_name : str
        Key into BIOME_VEGETATION_SETS.
    area_bounds : (min_x, min_y, max_x, max_y)
        World-space scatter rectangle.
    seed : int
        Random seed for deterministic generation.
    min_distance : float
        Minimum distance between placed vegetation instances (Poisson disk r).
    water_level : float
        Water rejection threshold. Values in [0, 1] are interpreted as a
        normalised fraction of the current terrain height range; values outside
        that range are interpreted as world-space metres.
    exclusion_zones : list of dict or None
        PROP-004 -- axis-aligned rectangular no-plant zones.
    moisture_map : array-like or None
        Optional 2-D array of moisture values in [0, 1] with shape (rows, cols)
        covering the area_bounds rectangle.  When None, moisture is estimated
        from normalised height (low = wet, high = dry).
    competition_radius : float
        If > 0, a new instance is suppressed when an already-placed instance of a
        *different* species exists within this radius.  Set to 0 (default) to
        disable competition.  Typical value: ``min_distance * 1.5``.
    lod_distances : list of float or None
        [near_m, mid_m] LOD boundary distances from ``camera_position``.
        Defaults to [30.0, 80.0] — matching a typical AAA outdoor scene where
        full-density near-field extends 30 m and cluster mid-field to 80 m.
    camera_position : (x, y, z) or None
        Reference camera / player position for LOD tier assignment.
        When None, defaults to the geometric centre of area_bounds.
    adjacent_biome_entries : list of (category, entry_dict) or None
        Pre-built entry list from a neighbouring biome for ecotone mixing.
        Passed in by ``scatter_biome_vegetation`` when ecotone mode is active.
    ecotone_alpha_fn : callable(wx, wy) -> float or None
        Function returning [0.0, 1.0] primary-biome weight at world position.
        0.0 = entirely adjacent biome; 1.0 = entirely primary biome.
        Passed in by ``scatter_biome_vegetation`` when ecotone mode is active.

    Returns
    -------
    list of dict
        Each dict has: position (x, y, z), type, style, scale, rotation,
        category, moisture, lod_hint.
    """
    if biome_name not in BIOME_VEGETATION_SETS:
        raise ValueError(
            f"Unknown biome '{biome_name}'. "
            f"Valid biomes: {sorted(BIOME_VEGETATION_SETS.keys())}"
        )

    biome = BIOME_VEGETATION_SETS[biome_name]
    rng = random.Random(seed)

    min_x, min_y, max_x, max_y = area_bounds
    width = max_x - min_x
    depth = max_y - min_y

    if width <= 0 or depth <= 0:
        return []

    if not terrain_vertices:
        return []

    # ------------------------------------------------------------------
    # Height / slope grid for fast nearest-vertex queries
    # ------------------------------------------------------------------
    heights = [v[2] for v in terrain_vertices]
    min_h = min(heights)
    max_h = max(heights)
    has_height_variation = max_h > min_h
    height_range = max_h - min_h if has_height_variation else 1.0
    water_level_f = float(water_level)
    water_level_world = (
        float(min_h) + water_level_f * float(height_range)
        if 0.0 <= water_level_f <= 1.0
        else water_level_f
    )

    vertex_arr = np.asarray(terrain_vertices, dtype=np.float64)
    normal_arr = np.asarray(terrain_normals, dtype=np.float64)
    x_axis = np.unique(vertex_arr[:, 0])
    y_axis = np.unique(vertex_arr[:, 1])
    use_raster_sample = (
        normal_arr.shape == (len(terrain_vertices), 3)
        and x_axis.size * y_axis.size == len(terrain_vertices)
    )
    height_grid: NDArray[np.float64] | None = None
    slope_grid: NDArray[np.float64] | None = None

    if use_raster_sample:
        x_lookup = {float(x): i for i, x in enumerate(x_axis.tolist())}
        y_lookup = {float(y): i for i, y in enumerate(y_axis.tolist())}
        height_grid = np.empty((y_axis.size, x_axis.size), dtype=np.float64)
        normal_grid = np.empty((y_axis.size, x_axis.size, 3), dtype=np.float64)
        filled = np.zeros((y_axis.size, x_axis.size), dtype=bool)

        for i, (vx, vy, vz) in enumerate(terrain_vertices):
            row = y_lookup[float(vy)]
            col = x_lookup[float(vx)]
            height_grid[row, col] = float(vz)
            normal_grid[row, col] = normal_arr[i]
            filled[row, col] = True

        use_raster_sample = bool(np.all(filled))
        if use_raster_sample:
            normal_len = np.linalg.norm(normal_grid, axis=2)
            nz_norm = np.ones_like(normal_len)
            valid_normals = normal_len > 1e-12
            nz_norm[valid_normals] = np.clip(
                np.abs(normal_grid[:, :, 2][valid_normals]) / normal_len[valid_normals],
                0.0,
                1.0,
            )
            slope_grid = np.degrees(np.arccos(nz_norm))

    grid_res = max(1, int(math.sqrt(len(terrain_vertices))))
    cell_w = width / grid_res if grid_res > 0 else width
    cell_d = depth / grid_res if grid_res > 0 else depth

    vertex_grid: dict[tuple[int, int], list[int]] = {}
    if not use_raster_sample:
        for i, (vx, vy, _vz) in enumerate(terrain_vertices):
            gi = int((vx - min_x) / cell_w) if cell_w > 0 else 0
            gj = int((vy - min_y) / cell_d) if cell_d > 0 else 0
            gi = max(0, min(gi, grid_res - 1))
            gj = max(0, min(gj, grid_res - 1))
            vertex_grid.setdefault((gi, gj), []).append(i)

    def _nearest_axis_index(axis: NDArray[Any], value: float) -> int:
        idx = int(np.searchsorted(axis, value))
        if idx <= 0:
            return 0
        if idx >= axis.size:
            return int(axis.size - 1)
        left = idx - 1
        if abs(value - float(axis[left])) <= abs(float(axis[idx]) - value):
            return left
        return idx

    def _sample_terrain(px: float, py: float) -> tuple[float, float, float, float]:
        """Sample (normalised_height, world_z, slope_degrees, moisture)."""
        if use_raster_sample and height_grid is not None and slope_grid is not None:
            ri = _nearest_axis_index(y_axis, py)
            ci = _nearest_axis_index(x_axis, px)
            vz = float(height_grid[ri, ci])
            norm_height = (vz - min_h) / height_range
            slope_deg = float(slope_grid[ri, ci])
        else:
            gi = int((px - min_x) / cell_w) if cell_w > 0 else 0
            gj = int((py - min_y) / cell_d) if cell_d > 0 else 0
            gi = max(0, min(gi, grid_res - 1))
            gj = max(0, min(gj, grid_res - 1))

            best_idx = -1
            best_dist_sq = float("inf")
            for di in range(-1, 2):
                for dj in range(-1, 2):
                    ni, nj = gi + di, gj + dj
                    for vi in vertex_grid.get((ni, nj), []):
                        vx, vy, _vz2 = terrain_vertices[vi]
                        dsq = (px - vx) ** 2 + (py - vy) ** 2
                        if dsq < best_dist_sq:
                            best_dist_sq = dsq
                            best_idx = vi

            if best_idx < 0:
                fallback_z = float(min_h) + 0.5 * float(height_range)
                return 0.5, fallback_z, 0.0, 0.5

            _vx, _vy, vz = terrain_vertices[best_idx]
            vz = float(vz)
            norm_height = (vz - min_h) / height_range

            nx, ny, nz = terrain_normals[best_idx]
            normal_len = math.sqrt(nx * nx + ny * ny + nz * nz)
            if normal_len > 1e-12:
                nz_norm = max(0.0, min(1.0, abs(nz) / normal_len))
                slope_deg = math.degrees(math.acos(nz_norm))
            else:
                slope_deg = 0.0

        # Moisture: use explicit map if available, else derive from altitude.
        # Low altitude -> wetter (rivers, valleys); high altitude -> drier.
        if moisture_map is not None:
            try:
                rows = len(moisture_map)
                cols = len(moisture_map[0])
                mi = max(0, min(int((py - min_y) / depth * rows), rows - 1))
                mj = max(0, min(int((px - min_x) / width * cols), cols - 1))
                moisture = float(moisture_map[mi][mj])
            except (IndexError, TypeError):
                moisture = max(0.0, min(1.0, 1.0 - norm_height))
        else:
            moisture = max(0.0, min(1.0, 1.0 - norm_height ** 0.7))

        return norm_height, float(vz), slope_deg, moisture

    # ------------------------------------------------------------------
    # LOD tier boundaries — AAA hierarchical density control
    # Near-field: dense individual plants (0.6× spacing)
    # Mid-field:  cluster-level base density (1.0× spacing)
    # Far-field:  sparse impostor/billboard pass (1.8× spacing)
    # ------------------------------------------------------------------
    from ._scatter_engine import poisson_disk_sample

    _lod_d = list(lod_distances) if lod_distances else [30.0, 80.0]
    _lod_d = _lod_d + [80.0] * max(0, 2 - len(_lod_d))
    lod_near_m = float(_lod_d[0])
    lod_mid_m  = float(_lod_d[1])

    # Camera reference for LOD distance calc; default to area centre.
    if camera_position is not None:
        cam_x = float(camera_position[0])
        cam_y = float(camera_position[1])
    else:
        cam_x = min_x + width * 0.5
        cam_y = min_y + depth * 0.5

    # LOD tier definitions: (lod_hint, min_distance_multiplier, density_factor)
    # density_factor > 1.0 means more attempts/denser; < 1.0 means sparser.
    _LOD_TIERS: list[tuple[int, float, float]] = [
        (0, 0.6, 1.4),   # near-field: tight spacing, high density — individual plants
        (1, 1.0, 1.0),   # mid-field:  base spacing, base density — clusters
        (2, 1.8, 0.55),  # far-field:  loose spacing, low density — impostors
    ]

    # ------------------------------------------------------------------
    # Build weighted entry list for density-based selection.
    # Merge adjacent biome entries when ecotone mode is active.
    # ------------------------------------------------------------------
    primary_entries: list[tuple[str, dict[str, Any]]] = []
    for category in ("trees", "ground_cover", "rocks"):
        for entry in biome.get(category, []):
            primary_entries.append((category, entry))

    if not primary_entries:
        return []

    # Adjacent biome entries (ecotone mixing) — provided by scatter_biome_vegetation
    adj_entries: list[tuple[str, dict[str, Any]]] = list(adjacent_biome_entries) if adjacent_biome_entries else []

    total_primary_density = sum(e["density"] for _, e in primary_entries)
    total_adj_density = sum(e["density"] for _, e in adj_entries) if adj_entries else 0.0

    # ------------------------------------------------------------------
    # Competition grid: coarse spatial hash of placed instance species.
    # Only used when competition_radius > 0.
    # ------------------------------------------------------------------
    comp_cell = max(competition_radius, min_distance)
    placed_species: dict[tuple[int, int], list[tuple[str, float, float]]] = {}

    def _competition_blocked(wx: float, wy: float, species_type: str) -> bool:
        """Return True if a competing species is within competition_radius."""
        if competition_radius <= 0:
            return False
        ci = int((wx - min_x) / comp_cell)
        cj = int((wy - min_y) / comp_cell)
        for di in range(-2, 3):
            for dj in range(-2, 3):
                for sp_type, sx, sy in placed_species.get((ci + di, cj + dj), []):
                    if sp_type != species_type:
                        dist_sq = (wx - sx) ** 2 + (wy - sy) ** 2
                        if dist_sq < competition_radius ** 2:
                            return True
        return False

    def _register_placed(wx: float, wy: float, species_type: str) -> None:
        ci = int((wx - min_x) / comp_cell)
        cj = int((wy - min_y) / comp_cell)
        placed_species.setdefault((ci, cj), []).append((species_type, wx, wy))

    # ------------------------------------------------------------------
    # AAA 3-tier hierarchical placement loop.
    # Each LOD tier generates its own Poisson-disk point set with
    # tier-specific spacing so near-field detail tapers gracefully into
    # far-field impostors without any hard density step.
    # ------------------------------------------------------------------
    placements: list[dict[str, Any]] = []

    for lod_hint, sep_mult, density_factor in _LOD_TIERS:
        tier_min_dist = min_distance * sep_mult
        tier_seed = seed + lod_hint * 1000  # distinct seed per tier for blue-noise variety
        raw_points = poisson_disk_sample(width, depth, tier_min_dist, seed=tier_seed)

        for rx_pt, ry_pt in raw_points:
            wx = rx_pt + min_x
            wy = ry_pt + min_y

            # Assign point to a LOD tier by distance from camera.
            # Only process points that belong to *this* tier.
            cam_dist = math.sqrt((wx - cam_x) ** 2 + (wy - cam_y) ** 2)
            if lod_hint == 0 and cam_dist >= lod_near_m:
                continue
            if lod_hint == 1 and not (lod_near_m <= cam_dist < lod_mid_m):
                continue
            if lod_hint == 2 and cam_dist < lod_mid_m:
                continue

            norm_h, terrain_z, slope_deg, moisture = _sample_terrain(wx, wy)

            # 1. Exclusion zones
            if exclusion_zones:
                in_exclusion = False
                for ez in exclusion_zones:
                    if (ez.get("min_x", -1e9) <= wx <= ez.get("max_x", 1e9)
                            and ez.get("min_y", -1e9) <= wy <= ez.get("max_y", 1e9)):
                        in_exclusion = True
                        break
                if in_exclusion:
                    continue

            # 2. Water level filter
            if has_height_variation and terrain_z < water_level_world:
                continue

            # 3. Ecotone alpha: determine whether this position should draw
            # from primary biome entries, adjacent biome entries, or both.
            # ecotone_alpha_fn returns primary-biome weight [0,1].
            # 0.0 = full adjacent, 1.0 = full primary.
            alpha_fn = ecotone_alpha_fn
            use_ecotone = bool(adj_entries and alpha_fn is not None)
            if alpha_fn is not None and use_ecotone:
                primary_alpha = float(alpha_fn(wx, wy))
                primary_alpha = max(0.0, min(1.0, primary_alpha))
            else:
                primary_alpha = 1.0

            # Blend entry pools: if primary_alpha < 0.5 draw from adjacent, else primary.
            # In the blend zone (0.2–0.8) we probabilistically mix both pools.
            if use_ecotone and primary_alpha < 0.2:
                active_entries = adj_entries
                active_total = total_adj_density if total_adj_density > 0 else 1.0
            elif use_ecotone and primary_alpha < 0.8:
                # Ecotone blend zone: randomly pick which pool to sample from
                if rng.random() < primary_alpha:
                    active_entries = primary_entries
                    active_total = total_primary_density
                else:
                    active_entries = adj_entries
                    active_total = total_adj_density if total_adj_density > 0 else 1.0
            else:
                active_entries = primary_entries
                active_total = total_primary_density

            # 4. Species selection with density weights
            roll = rng.uniform(0.0, active_total)
            cumulative = 0.0
            selected_cat: str | None = None
            selected_entry: dict[str, Any] | None = None

            for cat, entry in active_entries:
                cumulative += entry["density"]
                if roll <= cumulative:
                    selected_cat = cat
                    selected_entry = entry
                    break

            if selected_entry is None:
                selected_cat, selected_entry = active_entries[-1]

            assert selected_cat is not None  # for type checker

            # 5. Altitude filter (optional per-entry bounds)
            alt_min = selected_entry.get("min_altitude", 0.0)
            alt_max = selected_entry.get("max_altitude", 1.0)
            if not (alt_min <= norm_h <= alt_max):
                continue

            # 6. Moisture filter (optional per-entry bounds)
            moist_min = selected_entry.get("min_moisture", 0.0)
            moist_max = selected_entry.get("max_moisture", 1.0)
            if not (moist_min <= moisture <= moist_max):
                continue

            # 7. Slope filter by category
            max_slope = _max_slope_for_category(selected_cat)
            if slope_deg > max_slope:
                continue

            # 8. Species competition — suppress if a competing species is too close
            species_key = selected_entry.get("style", selected_entry["type"])
            if _competition_blocked(wx, wy, species_key):
                continue

            # 9. Density probability roll — modulated by LOD tier density factor.
            # Near-field points are more aggressively accepted (density_factor > 1);
            # far-field points are thinned (density_factor < 1).
            effective_density = min(1.0, selected_entry["density"] * density_factor)
            if rng.random() > effective_density:
                continue

            # Compute scale and rotation
            scale_range = selected_entry.get("scale_range", (0.8, 1.2))
            scale = rng.uniform(scale_range[0], scale_range[1])
            rotation = rng.uniform(0.0, 360.0)

            wz = min_h + norm_h * height_range

            placements.append({
                "position": (wx, wy, wz),
                "type": selected_entry["type"],
                "style": selected_entry.get("style", "default"),
                "scale": scale,
                "rotation": rotation,
                "category": selected_cat,
                "moisture": moisture,
                "lod_hint": lod_hint,
            })

            _register_placed(wx, wy, species_key)

    return placements


def compute_wind_vertex_colors(
    vertices: list[tuple[float, float, float]],
    trunk_center: tuple[float, float] | None = None,
    ground_level: float | None = None,
) -> list[tuple[float, float, float]]:
    """Compute per-vertex wind sway colors for Unity wind shader integration.

    Pure-logic function -- no Blender dependency.

    Channel mapping (see WIND_COLOR_LAYOUT):
      R = sway_strength   — distance from trunk center, normalized [0, 1]
      G = sway_frequency  — height from ground, normalized [0, 1]
      B = phase_offset    — spatial hash for desynchronized per-vertex motion [0, 1]

    Parameters
    ----------
    vertices : list of (x, y, z)
        Mesh vertex positions.
    trunk_center : (x, y) or None
        XY center of the trunk. If None, computed as centroid of
        lowest-height vertices.
    ground_level : float or None
        Z height of the ground. If None, uses minimum vertex Z.

    Returns
    -------
    list of (r, g, b)
        Per-vertex color tuples with values clamped to [0, 1].
    """
    if not vertices:
        return []

    # Determine ground level
    z_values = [v[2] for v in vertices]
    min_z = min(z_values)
    max_z = max(z_values)
    height_range = max_z - min_z if max_z > min_z else 1.0

    if ground_level is None:
        ground_level = min_z

    # Determine trunk center from bottom vertices
    if trunk_center is None:
        threshold = min_z + height_range * 0.1
        bottom_verts = [(v[0], v[1]) for v in vertices if v[2] <= threshold]
        if bottom_verts:
            cx = sum(v[0] for v in bottom_verts) / len(bottom_verts)
            cy = sum(v[1] for v in bottom_verts) / len(bottom_verts)
            trunk_center = (cx, cy)
        else:
            cx = sum(v[0] for v in vertices) / len(vertices)
            cy = sum(v[1] for v in vertices) / len(vertices)
            trunk_center = (cx, cy)

    # Compute maximum XY distance for normalization
    max_dist = 0.0
    for vx, vy, _vz in vertices:
        d = math.sqrt((vx - trunk_center[0]) ** 2 + (vy - trunk_center[1]) ** 2)
        if d > max_dist:
            max_dist = d
    if max_dist <= 0:
        max_dist = 1.0

    colors: list[tuple[float, float, float]] = []

    for vx, vy, vz in vertices:
        # R: sway_strength — distance from trunk center
        dist = math.sqrt((vx - trunk_center[0]) ** 2 + (vy - trunk_center[1]) ** 2)
        r = min(1.0, max(0.0, dist / max_dist))

        # G: sway_frequency — height from ground
        g = min(1.0, max(0.0, (vz - ground_level) / height_range))

        # B: phase_offset — spatial hash for desynchronized per-vertex motion
        phase_hash = math.sin(vx * 12.9898 + vy * 78.233 + vz * 37.719) * 43758.5453
        b = min(1.0, max(0.0, phase_hash - math.floor(phase_hash)))

        colors.append((r, g, b))

    return colors


def get_seasonal_variant(
    vegetation_type: str,
    season: str,
) -> dict[str, Any]:
    """Get modified material parameters for a seasonal variant.

    Pure-logic function -- no Blender dependency.

    Parameters
    ----------
    vegetation_type : str
        Type of vegetation (tree, mushroom, fern, moss, rock, etc.)
    season : str
        One of: summer, autumn, winter, corrupted.

    Returns
    -------
    dict with:
        color_tint: (r, g, b) additive color offset
        saturation_mult: float saturation multiplier
        leaf_density: float [0, 1] leaf coverage
        roughness_offset: float additive roughness change
        description: str human-readable description
        affects_leaves: bool whether foliage is affected
        affects_bark: bool whether bark/trunk is affected
    """
    if season not in _SEASONAL_VARIANTS:
        raise ValueError(
            f"Unknown season '{season}'. "
            f"Valid seasons: {sorted(_SEASONAL_VARIANTS.keys())}"
        )

    base = dict(_SEASONAL_VARIANTS[season])

    # Vegetation-type-specific adjustments
    is_foliage = vegetation_type in ("tree", "fern", "vine", "moss", "bush")
    is_fungi = vegetation_type in ("mushroom",)
    is_mineral = vegetation_type in ("rock", "gravestone", "crystal")

    base["affects_leaves"] = is_foliage
    base["affects_bark"] = vegetation_type == "tree"

    if is_mineral:
        # Rocks and stones are less affected by seasons
        base["color_tint"] = (
            base["color_tint"][0] * 0.3,
            base["color_tint"][1] * 0.3,
            base["color_tint"][2] * 0.3,
        )
        base["saturation_mult"] = 1.0 + (base["saturation_mult"] - 1.0) * 0.2
        base["leaf_density"] = 1.0  # Rocks don't lose leaves
        base["affects_leaves"] = False

    if is_fungi:
        # Mushrooms are less affected by seasons but react to corruption
        if season == "corrupted":
            base["color_tint"] = (0.2, -0.15, 0.3)  # Stronger purple
            base["saturation_mult"] = 1.3
        else:
            base["color_tint"] = (
                base["color_tint"][0] * 0.5,
                base["color_tint"][1] * 0.5,
                base["color_tint"][2] * 0.5,
            )
            base["leaf_density"] = 1.0  # Mushrooms don't lose caps

    if season == "winter" and is_foliage:
        # Extra frost effect on foliage
        base["roughness_offset"] = -0.15  # Smoother ice/frost surface

    return base


# ---------------------------------------------------------------------------
# Biome vegetation materializer
# ---------------------------------------------------------------------------

def _create_biome_vegetation_template(
    vegetation_type: str,
    collection: Any,
) -> Any:
    """Create a reusable mesh template for a biome vegetation type."""
    from ._mesh_bridge import mesh_from_spec, resolve_generator

    gen_entry = resolve_generator("vegetation", vegetation_type)
    if gen_entry is None:
        gen_entry = resolve_generator("prop", vegetation_type)
    if gen_entry is None:
        raise ValueError(f"No mesh generator found for vegetation type '{vegetation_type}'")

    gen_func, gen_kwargs = gen_entry
    spec = gen_func(**gen_kwargs)
    return mesh_from_spec(
        spec,
        name=f"_template_{vegetation_type}",
        collection=collection,
    )


def build_vegetation_placement_spec(
    placements: list[dict[str, Any]],
    biome_name: str,
    lod_distances: list[float] | None = None,
    camera_position: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    """Build a placement specification dict from raw placement list.

    Pure-logic function — no Blender dependency.  Enriches each placement
    with:
      - ``lod_level``: LOD tier (0–3) based on distance from ``camera_position``
        (or from area centre when no camera is given) and the ``lod_distances``
        thresholds.  LOD0 = closest / highest detail; LOD3 = furthest / impostor.
      - ``mesh_name``: canonical species key in the form ``"type_style"`` for
        use as the GPU-instancing mesh identifier.
      - Density per species as a summary ``species_density`` table in the spec.

    LOD distance thresholds (metres from camera):
      LOD0: d < lod_distances[0]    — full mesh, full detail
      LOD1: d < lod_distances[1]    — reduced mesh
      LOD2: d < lod_distances[2]    — billboard card
      LOD3: d >= lod_distances[2]   — impostor sprite

    Defaults: [15, 35, 60] metres (matches UE5/Unity typical outdoor scenes).

    Args:
        placements: Output of ``compute_vegetation_placement``.
        biome_name: Biome identifier (for metadata).
        lod_distances: [lod1_m, lod2_m, lod3_m] distance cutoffs.
        camera_position: (x, y, z) world position of reference camera.
            When None, uses the geometric centre of all placements.

    Returns:
        dict with:
          ``placements``: enriched list of placement dicts.
          ``biome``: biome name.
          ``instance_count``: total instance count.
          ``species_density``: dict mapping species key → count.
          ``lod_distribution``: dict mapping lod_level → count.
          ``lod_distances``: the thresholds used.
    """
    if lod_distances is None:
        lod_distances = [15.0, 35.0, 60.0]

    # Fill in LOD distances to always have 3 values
    ld = list(lod_distances) + [60.0] * max(0, 3 - len(lod_distances))
    d0, d1, d2 = float(ld[0]), float(ld[1]), float(ld[2])

    # Reference camera position (default: centroid of placements)
    if camera_position is not None:
        cam_x, cam_y, cam_z = float(camera_position[0]), float(camera_position[1]), float(camera_position[2])
    elif placements:
        cam_x = sum(p["position"][0] for p in placements) / len(placements)
        cam_y = sum(p["position"][1] for p in placements) / len(placements)
        cam_z = sum(p["position"][2] for p in placements) / len(placements)
    else:
        cam_x, cam_y, cam_z = 0.0, 0.0, 0.0

    species_density: dict[str, int] = {}
    lod_distribution: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
    enriched: list[dict[str, Any]] = []

    for p in placements:
        mesh_name = f"{p.get('type', 'unknown')}_{p.get('style', 'default')}"

        # Distance from reference camera
        px, py, pz = p["position"]
        dist = math.sqrt((px - cam_x) ** 2 + (py - cam_y) ** 2 + (pz - cam_z) ** 2)

        # LOD tier assignment.
        # ``lod_hint`` (0/1/2) from compute_vegetation_placement encodes which
        # hierarchical sampling tier produced this point.  Use it as a floor so
        # far-field impostors (lod_hint=2) are never promoted back to LOD0 even
        # when they happen to land close to the camera reference point.
        lod_hint = int(p.get("lod_hint", 0))
        if dist < d0:
            lod_level = 0
        elif dist < d1:
            lod_level = 1
        elif dist < d2:
            lod_level = 2
        else:
            lod_level = 3
        # Clamp to the minimum tier implied by the sampling pass.
        # This prevents a coarsely-sampled far-field point from being
        # rendered as a full LOD0 mesh just because the camera moved.
        lod_level = max(lod_level, lod_hint)

        species_density[mesh_name] = species_density.get(mesh_name, 0) + 1
        lod_distribution[lod_level] = lod_distribution.get(lod_level, 0) + 1

        ep = dict(p)
        ep["mesh_name"] = mesh_name
        ep["lod_level"] = lod_level
        ep["distance_from_camera"] = dist
        enriched.append(ep)

    return {
        "placements": enriched,
        "biome": biome_name,
        "instance_count": len(enriched),
        "species_density": species_density,
        "lod_distribution": lod_distribution,
        "lod_distances": [d0, d1, d2],
    }


def build_biome_density_map(
    stack: Any,
    biome_name: str,
) -> "dict[str, Any]":
    """Build a per-species density map from a TerrainMaskStack and write it.

    Reads ``stack.get("biome_id")`` (uint8/int (H,W) array where each cell
    holds the canonical biome integer ID) to assign per-biome density
    values for every species in ``BIOME_VEGETATION_SETS[biome_name]``.

    The resulting ``density_map`` is a ``Dict[str, np.ndarray]`` where:
      - keys are species type strings (e.g. ``"tree"``, ``"fern"``, ``"rock"``)
      - values are float32 (H, W) arrays: density probability for that species
        at each cell, derived from the biome definition for cells that belong
        to ``biome_name`` (all other cells get 0.0).

    Writes the map to ``stack.detail_density`` via
    ``stack.set("detail_density", density_map, "vegetation_system")`` so that
    ``environment_scatter.py`` can read it without a fallback.

    Parameters
    ----------
    stack : TerrainMaskStack
        Tile mask stack to read ``biome_id`` from and write ``detail_density``
        to.  Must have a populated ``height`` field; ``biome_id`` may be None
        (function returns an empty map in that case).
    biome_name : str
        Primary biome key into ``BIOME_VEGETATION_SETS``.

    Returns
    -------
    dict[str, np.ndarray]
        The density map written to the stack (may be empty if ``biome_id`` is
        not populated or ``biome_name`` is unknown).
    """
    if biome_name not in BIOME_VEGETATION_SETS:
        return {}

    h_arr = np.asarray(stack.height, dtype=np.float32)
    H, W = h_arr.shape

    biome_id_arr = stack.get("biome_id") if hasattr(stack, "get") else getattr(stack, "biome_id", None)

    # Collect all species entries across categories for this biome.
    biome = BIOME_VEGETATION_SETS[biome_name]
    all_entries: list[dict[str, Any]] = []
    for category in ("trees", "ground_cover", "rocks"):
        for entry in biome.get(category, []):
            all_entries.append(entry)

    if not all_entries:
        return {}

    density_map: dict[str, Any] = {}

    if biome_id_arr is not None:
        # Determine which cells belong to this biome. Numeric IDs follow the
        # canonical insertion order of BIOME_VEGETATION_SETS.
        bid_arr = np.asarray(biome_id_arr)
        numeric_id = list(BIOME_VEGETATION_SETS.keys()).index(biome_name)
        if bid_arr.shape == (H, W):
            biome_mask = (bid_arr == numeric_id).astype(np.float32)
        else:
            # biome_id populated but no numeric mapping — treat full tile as
            # this biome (caller may supply a single-biome tile).
            biome_mask = np.ones((H, W), dtype=np.float32)
    else:
        # No biome_id: assume entire tile is this biome.
        biome_mask = np.ones((H, W), dtype=np.float32)

    for entry in all_entries:
        species_key = entry.get("style", entry["type"])
        density_val = float(entry.get("density", 0.0))
        # Each cell's density = biome_mask * species_density_value.
        # Cells outside this biome get 0.0 density.
        density_arr = (biome_mask * density_val).astype(np.float32)
        # When multiple entries share the same species key, accumulate (cap at 1.0).
        if species_key in density_map:
            density_map[species_key] = np.clip(
                density_map[species_key] + density_arr, 0.0, 1.0
            )
        else:
            density_map[species_key] = density_arr

    if density_map:
        stack.set("detail_density", density_map, "vegetation_system")

    return density_map


def scatter_biome_vegetation(
    params: dict[str, Any],
) -> dict[str, Any]:
    """Materialize per-biome vegetation on terrain using quality placement.

    Combines biome vegetation sets with Poisson disk sampling, slope/height/
    moisture filtering, species competition zones, hierarchical LOD density,
    and ecotone boundary blending.

    Params:
        terrain_name (str): Existing terrain object name.
        biome_name (str): Key into BIOME_VEGETATION_SETS.
        min_distance (float, default 3.0): Minimum distance between instances.
        seed (int, default 42): Random seed.
        max_instances (int, default 100000): Cap on total instances.
        season (str, optional): Season variant (summer/autumn/winter/corrupted).
        bake_wind_colors (bool, default False): Whether to compute wind vertex
            colors on tree instances.
        water_level (float, default 0.05): Normalised height below which nothing
            is placed.
        exclusion_zones (list of dict, optional): PROP-004 -- axis-aligned
            rectangular zones where no vegetation is placed.  Each dict has
            keys ``min_x``, ``min_y``, ``max_x``, ``max_y`` (world space).
        lod_distances (list of float, optional): PROP-003 -- distance
            thresholds [near_m, mid_m, far_m] for LOD group tagging.
            Defaults to [30.0, 80.0, 200.0].  The first two values drive
            hierarchical density tiers in compute_vegetation_placement; all
            three are forwarded to build_vegetation_placement_spec.
        competition_radius (float, default 0.0): Species competition exclusion
            radius.  When > 0, suppresses a new placement when a competing
            species occupies the zone.  Typical: min_distance * 1.5.
        moisture_map: Optional 2-D array of moisture values [0,1].
        adjacent_biome (str, optional): Name of the biome on the opposite side
            of the ecotone boundary.  Must be a key in BIOME_VEGETATION_SETS.
            When set, species from both biomes are blended in the transition
            zone.
        ecotone_blend_width (float, default 20.0): Width in world units of the
            ecotone blend zone.  Species from both biomes are mixed within this
            band.  Outside the band, only the primary (or adjacent) biome
            appears.
        ecotone_axis (str, default "x"): Axis perpendicular to the ecotone
            boundary — "x" means the boundary runs along Y, "y" means along X.
        ecotone_boundary (float, optional): World-space coordinate along
            ecotone_axis where the boundary midpoint lies.  Defaults to the
            centre of the area_bounds.
        spec_only (bool, default False): When True, skip all bpy operations and
            return the placement spec dict directly (for testing / export).
        camera_position (list of 3 floats, optional): Reference player/camera
            position for LOD tier distance calculations.
        stack (TerrainMaskStack, optional): When provided, biome-defined density
            values are written to ``stack.detail_density`` via
            ``build_biome_density_map`` so that environment_scatter.py reads
            the correct per-biome densities instead of falling back to defaults.

    Returns dict with: name, instance_count, vegetation_types, biome, season,
                       lod_distribution, species_density.
    """
    warnings.warn(
        "scatter_biome_vegetation is deprecated; use handle_scatter_vegetation",
        DeprecationWarning,
        stacklevel=2,
    )
    biome_name = params.get("biome_name")
    if not biome_name:
        raise ValueError("'biome_name' is required")

    # Optional TerrainMaskStack — when provided, biome density is written to
    # stack.detail_density so environment_scatter.py reads real values.
    _mask_stack = params.get("stack")

    min_distance = float(params.get("min_distance", 3.0))
    seed = int(params.get("seed", 42))
    max_instances = int(params.get("max_instances", 100_000))
    season = params.get("season")
    bake_wind_colors: bool = bool(params.get("bake_wind_colors", False))
    water_level = float(params.get("water_level", _DEFAULT_WATER_LEVEL))
    exclusion_zones: list[dict[str, Any]] = params.get("exclusion_zones") or []
    lod_distances: list[float] = params.get("lod_distances") or [30.0, 80.0, 200.0]
    competition_radius = float(params.get("competition_radius", 0.0))
    moisture_map = params.get("moisture_map")
    spec_only: bool = bool(params.get("spec_only", False))
    camera_pos_raw = params.get("camera_position")
    camera_position: tuple[float, float, float] | None = (
        tuple(camera_pos_raw[:3]) if camera_pos_raw else None  # type: ignore[assignment]
    )

    # ------------------------------------------------------------------
    # Ecotone boundary blending parameters.
    # When adjacent_biome is set we construct an ecotone_alpha_fn that
    # returns the primary-biome weight [0,1] at any world XY position.
    # The transition is a smooth-step ramp centred on ecotone_boundary
    # and spanning ecotone_blend_width.
    # H-1: prefer per-cell ecotone_blend_weights channel produced by pass_ecotones.
    # ------------------------------------------------------------------
    adjacent_biome: str | None = params.get("adjacent_biome")
    _ecotone_channel = (
        _mask_stack.get("ecotone_blend_weights") if _mask_stack is not None else None
    )
    _use_channel_blend: bool = _ecotone_channel is not None
    ecotone_blend_width: float = float(params.get("ecotone_blend_width", 20.0))
    ecotone_axis: str = str(params.get("ecotone_axis", "x")).lower()

    adj_entries: list[tuple[str, dict[str, Any]]] = []
    _ecotone_mid: list[float] = [
        float(params["ecotone_boundary"])
    ] if "ecotone_boundary" in params else []
    ecotone_alpha_fn: Callable[[float, float], float] | None = None

    if adjacent_biome and adjacent_biome in BIOME_VEGETATION_SETS:
        adj_biome_data = BIOME_VEGETATION_SETS[adjacent_biome]
        for cat in ("trees", "ground_cover", "rocks"):
            for entry in adj_biome_data.get(cat, []):
                adj_entries.append((cat, entry))

        # ecotone_boundary: midpoint coordinate along ecotone_axis.
        # Will be resolved after we know area_bounds (see below).
        # Store as a mutable container so the closure can capture it.
        _half_blend = ecotone_blend_width * 0.5

        def _smoothstep(t: float) -> float:
            """Smoothstep [0,1] — eliminates visible hard boundary."""
            t = max(0.0, min(1.0, t))
            return t * t * (3.0 - 2.0 * t)

        def _ecotone_alpha(wx: float, wy: float) -> float:
            """Return primary-biome weight [0,1] at world position."""
            if _use_channel_blend and _mask_stack is not None:
                iy, ix = _world_to_cell(_mask_stack, float(wx), float(wy))
                ch = np.asarray(_ecotone_channel)
                if ch.ndim == 3 and ch.shape[2] > 0:
                    return float(np.clip(ch[iy, ix, 0], 0.0, 1.0))
            coord = wx if ecotone_axis == "x" else wy
            mid = _ecotone_mid[0]
            # Signed distance from boundary midpoint.
            # Positive side = primary biome, negative = adjacent biome.
            signed_dist = coord - mid
            if signed_dist >= _half_blend:
                return 1.0  # fully in primary biome
            if signed_dist <= -_half_blend:
                return 0.0  # fully in adjacent biome
            # Normalise to [0,1] and smooth-step
            t = (signed_dist + _half_blend) / ecotone_blend_width
            return _smoothstep(t)

        ecotone_alpha_fn = _ecotone_alpha

    # ------------------------------------------------------------------
    # Pure-logic spec mode — no Blender required
    # ------------------------------------------------------------------
    if spec_only:
        terrain_vertices: list[tuple[float, float, float]] = params.get("terrain_vertices") or []
        terrain_normals: list[tuple[float, float, float]] = params.get("terrain_normals") or []
        terrain_faces: list[tuple[int, ...]] = params.get("terrain_faces") or []
        area_bounds: tuple[float, float, float, float] = params.get("area_bounds") or (0.0, 0.0, 100.0, 100.0)

        if not terrain_vertices:
            # Synthesize a flat terrain if no geometry supplied
            terrain_vertices = [
                (area_bounds[0], area_bounds[1], 0.0),
                (area_bounds[2], area_bounds[1], 0.0),
                (area_bounds[2], area_bounds[3], 0.0),
                (area_bounds[0], area_bounds[3], 0.0),
            ]
            terrain_normals = [(0.0, 0.0, 1.0)] * 4
            terrain_faces = [(0, 1, 2, 3)]

        # Resolve ecotone boundary midpoint to area centre if not specified.
        if adj_entries and ecotone_alpha_fn is not None:
            if not _ecotone_mid:
                mid_x = (area_bounds[0] + area_bounds[2]) * 0.5
                mid_y = (area_bounds[1] + area_bounds[3]) * 0.5
                _ecotone_mid.append(mid_x if ecotone_axis == "x" else mid_y)

        placements = compute_vegetation_placement(
            terrain_vertices,
            terrain_faces,
            terrain_normals,
            biome_name,
            area_bounds,
            seed=seed,
            min_distance=min_distance,
            water_level=water_level,
            exclusion_zones=exclusion_zones,
            moisture_map=moisture_map,
            competition_radius=competition_radius,
            lod_distances=lod_distances[:2] if len(lod_distances) >= 2 else lod_distances,
            camera_position=camera_position,
            adjacent_biome_entries=adj_entries if adj_entries else None,
            ecotone_alpha_fn=ecotone_alpha_fn,
        )

        if len(placements) > max_instances:
            placements = placements[:max_instances]

        spec = build_vegetation_placement_spec(
            placements,
            biome_name=biome_name,
            lod_distances=lod_distances,
            camera_position=camera_position,
        )

        if season:
            spec["season"] = season
        if adjacent_biome:
            spec["adjacent_biome"] = adjacent_biome
            spec["ecotone_blend_width"] = ecotone_blend_width

        # Write biome density to stack so environment_scatter reads real values.
        if _mask_stack is not None:
            build_biome_density_map(_mask_stack, biome_name)

        return spec

    # ------------------------------------------------------------------
    # Blender materializer mode
    # ------------------------------------------------------------------
    try:
        import bpy
        import bmesh
    except ImportError as exc:
        raise RuntimeError("scatter_biome_vegetation requires Blender") from exc

    terrain_name = params.get("terrain_name")
    if not terrain_name:
        raise ValueError("'terrain_name' is required")

    obj = bpy.data.objects.get(terrain_name)
    if obj is None:
        raise ValueError(f"Object not found: {terrain_name}")

    # Extract terrain geometry
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.normal_update()

    bm_terrain_vertices = [(v.co.x, v.co.y, v.co.z) for v in bm.verts]
    bm_terrain_normals = [(v.normal.x, v.normal.y, v.normal.z) for v in bm.verts]
    bm_terrain_faces = [tuple(v.index for v in f.verts) for f in bm.faces]
    bm.free()

    dims = obj.dimensions
    loc = obj.location
    half_x = dims.x / 2.0
    half_y = dims.y / 2.0
    area_bounds = (
        loc.x - half_x,
        loc.y - half_y,
        loc.x + half_x,
        loc.y + half_y,
    )

    # Resolve ecotone boundary midpoint to area centre if not specified.
    if adj_entries and ecotone_alpha_fn is not None:
        if not _ecotone_mid:
            mid_x = (area_bounds[0] + area_bounds[2]) * 0.5
            mid_y = (area_bounds[1] + area_bounds[3]) * 0.5
            _ecotone_mid.append(mid_x if ecotone_axis == "x" else mid_y)

    placements = compute_vegetation_placement(
        bm_terrain_vertices,
        bm_terrain_faces,
        bm_terrain_normals,
        biome_name,
        area_bounds,
        seed=seed,
        min_distance=min_distance,
        water_level=water_level,
        exclusion_zones=exclusion_zones,
        moisture_map=moisture_map,
        competition_radius=competition_radius,
        lod_distances=lod_distances[:2] if len(lod_distances) >= 2 else lod_distances,
        camera_position=camera_position,
        adjacent_biome_entries=adj_entries if adj_entries else None,
        ecotone_alpha_fn=ecotone_alpha_fn,
    )

    if len(placements) > max_instances:
        placements = placements[:max_instances]

    # Enrich with LOD assignments
    spec = build_vegetation_placement_spec(
        placements,
        biome_name=biome_name,
        lod_distances=lod_distances,
        camera_position=camera_position,
    )
    enriched_placements = spec["placements"]

    scatter_coll_name = f"{terrain_name}_{biome_name}_vegetation"
    scatter_coll = bpy.data.collections.new(scatter_coll_name)
    bpy.context.scene.collection.children.link(scatter_coll)

    template_coll = bpy.data.collections.new(f"{scatter_coll_name}_templates")
    bpy.context.scene.collection.children.link(template_coll)
    templates: dict[str, Any] = {}

    veg_counts: dict[str, int] = {}
    from .lod_pipeline import _setup_billboard_lod

    veg_types_needed = set(p["type"] for p in enriched_placements)
    for veg_type in veg_types_needed:
        templates[veg_type] = _create_biome_vegetation_template(veg_type, template_coll)
        if veg_type == "tree":
            _setup_billboard_lod(templates[veg_type], veg_spec=None, veg_type=veg_type)
            if bake_wind_colors:
                mesh_data = templates[veg_type].data
                tree_verts = [(v.co.x, v.co.y, v.co.z) for v in mesh_data.vertices]
                wind_colors = compute_wind_vertex_colors(tree_verts)
                if "WindColor" in mesh_data.color_attributes:
                    mesh_data.color_attributes.remove(mesh_data.color_attributes["WindColor"])
                attr = mesh_data.color_attributes.new(
                    name="WindColor", type="FLOAT_COLOR", domain="CORNER"
                )
                n_loops = len(mesh_data.loops)
                rgba = np.zeros((n_loops, 4), dtype=np.float32)
                for poly in mesh_data.polygons:
                    for loop_idx, vert_idx in zip(poly.loop_indices, poly.vertices):
                        r, g, b = wind_colors[vert_idx]
                        rgba[loop_idx, 0] = r
                        rgba[loop_idx, 1] = g
                        rgba[loop_idx, 2] = b
                        rgba[loop_idx, 3] = 0.0
                attr.data.foreach_set("color", rgba.ravel())

    for p in enriched_placements:
        veg_key = p.get("mesh_name", f"{p['type']}_{p['style']}")
        veg_counts[veg_key] = veg_counts.get(veg_key, 0) + 1

        template = templates.get(p["type"])
        if template is None:
            continue

        instance = bpy.data.objects.new(
            f"{veg_key}_{veg_counts[veg_key]:04d}",
            template.data,
        )
        instance.location = p["position"]
        s = p["scale"]
        instance.scale = (s, s, s)
        instance.rotation_euler = (0, 0, math.radians(p["rotation"]))

        # Tag LOD distances: trees get billboard pipeline, others get custom props.
        lod_level = p.get("lod_level", 0)
        if p.get("category") != "trees":
            _ld = list(lod_distances) + [0.0] * max(0, 3 - len(lod_distances))
            instance["lod0_distance"] = float(_ld[0])
            instance["lod1_distance"] = float(_ld[1])
            instance["lod2_distance"] = float(_ld[2])
            instance["lod_enabled"] = True
            instance["lod_level"] = lod_level

        scatter_coll.objects.link(instance)

    total_instances = sum(veg_counts.values())

    result: dict[str, Any] = {
        "name": scatter_coll_name,
        "instance_count": total_instances,
        "vegetation_types": veg_counts,
        "biome": biome_name,
        "species_density": spec["species_density"],
        "lod_distribution": spec["lod_distribution"],
    }

    if season:
        result["season"] = season
    if adjacent_biome:
        result["adjacent_biome"] = adjacent_biome
        result["ecotone_blend_width"] = ecotone_blend_width

    # Write biome density to stack so environment_scatter reads real values.
    if _mask_stack is not None:
        build_biome_density_map(_mask_stack, biome_name)

    # Emit foliage placement manifest when requested.
    # See docs/FOLIAGE_MANIFEST_PIPELINE.md for the current schema.
    if params.get("emit_manifest"):
        mesh_library_path = params.get("mesh_library_path")
        if mesh_library_path is None:
            raise ValueError(
                "emit_manifest=True requires 'mesh_library_path' in params"
            )
        from pathlib import Path as _Path

        mesh_library = load_mesh_library(mesh_library_path)
        manifest = build_foliage_placement_manifest(
            spec=spec,
            mesh_library=mesh_library,
            stack=_mask_stack,
            biome_name=biome_name,
            season=season,
        )
        manifest_out_path = params.get("manifest_out_path")
        if manifest_out_path is None:
            manifest_out_path = (
                _Path(mesh_library_path).parent / "foliage_placement_manifest.json"
            )
        write_foliage_placement_manifest(manifest, manifest_out_path)
        result["manifest_path"] = str(manifest_out_path)

    return result


# ===========================================================================
# Foliage placement manifest emission.
#
# Pure-logic, Blender-free helpers that translate the placement spec produced
# by :func:`build_vegetation_placement_spec` into the Unity Terrain /
# GPU-instancing manifest documented in ``docs/FOLIAGE_MANIFEST_PIPELINE.md``.
# Schema version: 1.0.
# ===========================================================================


def load_mesh_library(library_path: "str | Any") -> dict[str, dict[str, Any]]:
    """Load the Assets/Foliage manifest of pre-authored mesh assets.

    The library file is a JSON sidecar in the foliage assets directory that
    artists update when they add or remove FBX files.

    Returns:
        dict keyed by ``species_key`` (e.g. ``"tree_veil_healthy"``) to a
        dict with at least ``mesh_asset_path``, ``lod_meshes``, ``category``
        and ``unity_render_mode``. Unknown / missing fields are left intact
        so the manifest can grow forward-compatibly.

    Raises:
        FileNotFoundError: if the path does not exist.
        ValueError: if the file is not valid JSON or the structure is wrong.
    """
    import json as _json
    from pathlib import Path as _Path

    p = _Path(library_path)
    if not p.is_file():
        raise FileNotFoundError(f"mesh library not found: {p}")
    try:
        raw = _json.loads(p.read_text(encoding="utf-8"))
    except _json.JSONDecodeError as exc:
        raise ValueError(f"mesh library {p} is not valid JSON: {exc}") from exc

    if isinstance(raw, dict) and "species" in raw:
        species = raw["species"]
    elif isinstance(raw, list):
        species = {entry["species_key"]: entry for entry in raw if "species_key" in entry}
    elif isinstance(raw, dict):
        species = raw
    else:
        raise ValueError(f"mesh library {p} has unrecognised structure")

    required = ("mesh_asset_path", "category")
    out: dict[str, dict[str, Any]] = {}
    for key, entry in species.items():
        if not isinstance(entry, dict):
            raise ValueError(f"mesh library entry for {key!r} is not a dict")
        for field in required:
            if field not in entry:
                raise ValueError(
                    f"mesh library entry {key!r} missing required field {field!r}"
                )
        # Defaults for optional fields so manifest emission stays simple.
        entry.setdefault("lod_meshes", [])
        entry.setdefault("atlas_path", None)
        entry.setdefault("unity_render_mode", "terrain_tree")
        entry.setdefault("render_batch_key", key)
        entry.setdefault("wind_color_baked", False)
        entry.setdefault("physics_collider", "none")
        out[str(key)] = entry
    return out


def _derive_cliff_sdf_m(stack: Any) -> "Any | None":
    """Compute a per-cell signed-distance-from-cliff in metres."""
    if stack is None:
        return None
    if not hasattr(stack, "get"):
        return None
    cliff = stack.get("cliff_label")
    if cliff is None:
        return None
    try:
        from scipy.ndimage import distance_transform_edt as _edt  # type: ignore
    except Exception:
        return None
    cell_size = float(getattr(stack, "cell_size", 1.0) or 1.0)
    arr = np.asarray(cliff)
    return np.asarray(_edt(arr == 0), dtype=np.float32) * cell_size


def _derive_water_edge_sdf_m(stack: Any) -> "Any | None":
    """Compute distance-from-water in metres using bathymetry."""
    if stack is None:
        return None
    if not hasattr(stack, "get"):
        return None
    bathy = stack.get("bathymetry")
    if bathy is None:
        return None
    try:
        from scipy.ndimage import distance_transform_edt as _edt  # type: ignore
    except Exception:
        return None
    cell_size = float(getattr(stack, "cell_size", 1.0) or 1.0)
    return (
        np.asarray(_edt(np.asarray(bathy, dtype=np.float32) <= 0), dtype=np.float32)
        * cell_size
    )


def build_foliage_placement_manifest(
    spec: dict[str, Any],
    mesh_library: dict[str, dict[str, Any]],
    stack: Any,
    *,
    biome_name: str,
    season: str | None = None,
    schema_version: str = "1.0",
    sdf_road_min_m: float = 1.5,
    sdf_cliff_min_m: float = 0.8,
    water_edge_min_m: float = 0.5,
    lod_distances_m: list[float] | None = None,
) -> dict[str, Any]:
    """Convert a placement spec into the Wave 5 manifest schema.

    Args:
        spec: Output of :func:`build_vegetation_placement_spec` — must
            contain ``placements`` with ``position``, ``rotation``,
            ``scale``, ``mesh_name`` (= species key) per entry.
        mesh_library: Output of :func:`load_mesh_library`.
        stack: TerrainMaskStack (optional). When provided, SDF exclusion
            is applied against ``road_sdf_dist`` / ``cliff_label`` /
            ``bathymetry`` and positions are normalised into Unity's
            0..1 terrain space.
        biome_name: Primary biome name embedded in the manifest.
        season: Optional season variant string.
        schema_version: Pinned for forward compatibility.
        sdf_road_min_m / sdf_cliff_min_m / water_edge_min_m: SDF
            exclusion thresholds in metres. See research doc for
            rationale.
        lod_distances_m: 4-element [lod0_m, lod1_m, lod2_m, lod3_m]; we
            default to the VeilBreakers scale (15/35/60/200 m).

    Returns:
        The manifest dict, ready for :func:`write_foliage_placement_manifest`.
    """
    import time as _time

    if lod_distances_m is None:
        lod_distances_m = [15.0, 35.0, 60.0, 200.0]

    placements = list(spec.get("placements", []))

    # Build mesh_library list, only species we actually have entries for.
    species_seen: list[str] = []
    species_to_id: dict[str, int] = {}
    library_entries: list[dict[str, Any]] = []
    dropped_species: set[str] = set()
    for p in placements:
        species_key = p.get("mesh_name") or f"{p.get('type', 'unknown')}_{p.get('style', 'default')}"
        if species_key in species_to_id:
            continue
        if species_key not in mesh_library:
            dropped_species.add(species_key)
            continue
        entry = dict(mesh_library[species_key])
        entry["mesh_id"] = len(library_entries)
        entry["species_key"] = species_key
        library_entries.append(entry)
        species_to_id[species_key] = entry["mesh_id"]
        species_seen.append(species_key)

    if dropped_species:
        # Don't crash — Wave 5 says warn and drop.
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "Dropping placements for species without mesh_library entries: %s",
            sorted(dropped_species),
        )

    # Stack-derived exclusion SDFs (computed lazily; None when no stack).
    cliff_sdf = _derive_cliff_sdf_m(stack)
    water_sdf = _derive_water_edge_sdf_m(stack)
    road_sdf = stack.get("road_sdf_dist") if stack is not None else None
    hero_excl = stack.get("hero_exclusion") if stack is not None else None

    # Terrain extents for normalised position.
    if stack is not None and getattr(stack, "height", None) is not None:
        h, w = stack.height.shape
        cell_size = float(getattr(stack, "cell_size", 1.0) or 1.0)
        ox = float(getattr(stack, "world_origin_x", 0.0) or 0.0)
        oy = float(getattr(stack, "world_origin_y", 0.0) or 0.0)
        extent_x = w * cell_size
        extent_y = h * cell_size
        height_min = float(stack.height.min())
        height_max = float(stack.height.max())
        height_span = max(height_max - height_min, 1e-6)
        tile_x = int(getattr(stack, "tile_x", 0) or 0)
        tile_y = int(getattr(stack, "tile_y", 0) or 0)
        tile_size = int(getattr(stack, "tile_size", w) or w)
    else:
        h = w = 1024
        cell_size = 1.0
        ox = oy = 0.0
        extent_x = extent_y = 1024.0
        height_min = 0.0
        height_max = 100.0
        height_span = 100.0
        tile_x = tile_y = 0
        tile_size = 1024

    instances: list[dict[str, Any]] = []
    species_density: dict[str, int] = {}
    lod_distribution: dict[str, int] = {"0": 0, "1": 0, "2": 0, "3": 0}

    for p in placements:
        species_key = p.get("mesh_name") or f"{p.get('type', 'unknown')}_{p.get('style', 'default')}"
        if species_key not in species_to_id:
            continue
        wx, wy, wz = p["position"]

        # SDF exclusions.
        if stack is not None:
            iy, ix = _world_to_cell(stack, float(wx), float(wy))
            if road_sdf is not None and float(road_sdf[iy, ix]) < sdf_road_min_m:
                continue
            if cliff_sdf is not None and float(cliff_sdf[iy, ix]) < sdf_cliff_min_m:
                continue
            if water_sdf is not None and float(water_sdf[iy, ix]) < water_edge_min_m:
                continue
            if hero_excl is not None and float(hero_excl[iy, ix]) > 0.5:
                continue

        # Normalised position for Unity TerrainData.SetTreeInstances.
        norm_x = max(0.0, min(1.0, (float(wx) - ox) / max(extent_x, 1e-6)))
        norm_z = max(0.0, min(1.0, (float(wy) - oy) / max(extent_y, 1e-6)))
        norm_y = max(0.0, min(1.0, (float(wz) - height_min) / height_span))

        scale = float(p.get("scale", 1.0))
        rotation_deg = float(p.get("rotation", 0.0))
        rotation_rad = math.radians(rotation_deg)
        lod_level = int(p.get("lod_level", 0))

        instances.append(
            {
                "i": len(instances),
                "mesh_id": species_to_id[species_key],
                "position_world": [float(wx), float(wy), float(wz)],
                "position_terrain_norm": [norm_x, norm_y, norm_z],
                "rotation_y_rad": rotation_rad,
                "scale": scale,
                "scale_xyz": [scale, scale, scale],
                "lod_level": lod_level,
                "lod_hint_sampler_tier": int(p.get("lod_hint", 0)),
                "biome": p.get("biome") or biome_name,
                "category": p.get("category") or library_entries[species_to_id[species_key]].get("category"),
                "moisture": float(p.get("moisture", 0.0)),
                "tint_rgb": list(p.get("tint_rgb", [1.0, 1.0, 1.0])),
                "color_variation_seed": int(p.get("color_variation_seed") or int(
                    _make_rng(tile_x, tile_y, int(float(wx) * 1000), int(float(wy) * 1000)).integers(2**31)
                )),
            }
        )
        species_density[species_key] = species_density.get(species_key, 0) + 1
        lod_distribution[str(lod_level)] = lod_distribution.get(str(lod_level), 0) + 1

    return {
        "schema_version": schema_version,
        "generated_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        "terrain": {
            "tile_x": tile_x,
            "tile_y": tile_y,
            "tile_size": tile_size,
            "cell_size": cell_size,
            "world_origin": [ox, oy],
            "world_extent": [extent_x, extent_y],
            "height_min_m": height_min,
            "height_max_m": height_max,
        },
        "biome": biome_name,
        "season": season,
        "lod_distances_m": lod_distances_m,
        "camera_reference": list(spec.get("camera_position") or [extent_x * 0.5, extent_y * 0.5, 0.0]),
        "mesh_library": library_entries,
        "instances": instances,
        "instance_count": len(instances),
        "species_density": species_density,
        "lod_distribution": lod_distribution,
        "exclusion_sources": {
            "road_sdf_min_m": sdf_road_min_m,
            "cliff_sdf_min_m": sdf_cliff_min_m,
            "water_edge_min_m": water_edge_min_m,
            "hero_exclusion_used": hero_excl is not None,
            "poi_radius_used_m": 0.0,
        },
    }


def write_foliage_placement_manifest(manifest: dict[str, Any], out_path: Any) -> Any:
    """Atomic JSON write (tmp + rename). Returns the written :class:`Path`."""
    import json as _json
    import os as _os
    import string as _string
    import random as _random
    from pathlib import Path as _Path

    p = _Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    suffix = "".join(_random.choices(_string.ascii_letters + _string.digits, k=8))
    tmp = p.with_name(f".{p.name}.{suffix}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        _json.dump(manifest, fh, indent=2, sort_keys=True)
    _os.replace(tmp, p)
    return p

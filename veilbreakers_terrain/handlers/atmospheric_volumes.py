"""Atmospheric volume props system for biome-appropriate ambient effects.

NO bpy/bmesh imports. Fully testable without Blender.

Computes placement positions and parameters for volumetric effects
(fog, dust, fireflies, god rays, smoke, spore clouds, void shimmer)
based on biome type, area bounds, and density rules.

Provides:
  - ATMOSPHERIC_VOLUMES: 7 volume type definitions
  - BIOME_ATMOSPHERE_RULES: Per-biome volume assignments
  - compute_atmospheric_placements: Generate volume placements for a biome
  - compute_volume_mesh_spec: Generate mesh spec for a volume shape
  - estimate_atmosphere_performance: Estimate GPU cost of volumes
"""

from __future__ import annotations

import math
import random
from typing import Any, Optional

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _NUMPY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Volume Type Definitions -- 7 types
# ---------------------------------------------------------------------------

ATMOSPHERIC_VOLUMES: dict[str, dict[str, Any]] = {
    "ground_fog": {
        "shape": "box",
        "density": 0.3,
        "height": 1.5,
        "color": (0.7, 0.7, 0.8),
        "opacity": 0.4,
        "animation": "drift",
        "animation_speed": 0.3,
        "particle_type": None,
    },
    "dust_motes": {
        "shape": "box",
        "density": 0.1,
        "height": 3.0,
        "color": (0.8, 0.75, 0.6),
        "opacity": 0.15,
        "animation": "float",
        "animation_speed": 0.02,
        "particle_type": "point",
    },
    "fireflies": {
        "shape": "sphere",
        "density": 0.05,
        "height": 2.5,
        "color": (0.8, 1.0, 0.5),
        "opacity": 0.8,
        "animation": "wander",
        "animation_speed": 0.5,
        "particle_type": "emissive",
        "emission_strength": 5.0,
    },
    "god_rays": {
        "shape": "cone",
        "density": 0.2,
        "height": 15.0,
        "color": (1.0, 0.95, 0.8),
        "opacity": 0.25,
        "animation": "pulse",
        "animation_speed": 0.1,
        "particle_type": None,
        "direction": "down",
    },
    "smoke_plume": {
        "shape": "cone",
        "density": 0.4,
        "height": 10.0,
        "color": (0.3, 0.3, 0.3),
        "opacity": 0.5,
        "animation": "rise",
        "animation_speed": 1.0,
        "particle_type": None,
        "direction": "up",
    },
    "spore_cloud": {
        "shape": "sphere",
        "density": 0.15,
        "height": 3.0,
        "color": (0.5, 0.7, 0.3),
        "opacity": 0.3,
        "animation": "float",
        "animation_speed": 0.1,
        "particle_type": "point",
    },
    "void_shimmer": {
        "shape": "sphere",
        "density": 0.1,
        "height": 4.0,
        "color": (0.3, 0.1, 0.5),
        "opacity": 0.35,
        "animation": "distortion",
        "animation_speed": 0.5,
        "particle_type": None,
        "distortion": True,
    },
}


# ---------------------------------------------------------------------------
# Biome -> Atmosphere Rules
# ---------------------------------------------------------------------------

BIOME_ATMOSPHERE_RULES: dict[str, list[dict[str, Any]]] = {
    "dark_forest": [
        {"volume": "ground_fog", "coverage": 0.6, "min_count": 3},
        {"volume": "dust_motes", "coverage": 0.3, "min_count": 2},
        {"volume": "god_rays", "coverage": 0.1, "min_count": 1},
        {"volume": "fireflies", "coverage": 0.2, "min_count": 1},
    ],
    "corrupted_swamp": [
        {"volume": "ground_fog", "coverage": 0.8, "min_count": 4},
        {"volume": "spore_cloud", "coverage": 0.4, "min_count": 2},
        {"volume": "void_shimmer", "coverage": 0.1, "min_count": 1},
    ],
    "volcanic_wastes": [
        {"volume": "smoke_plume", "coverage": 0.5, "min_count": 3},
        {"volume": "dust_motes", "coverage": 0.3, "min_count": 2},
    ],
    "frozen_peaks": [
        {"volume": "ground_fog", "coverage": 0.4, "min_count": 2},
        {"volume": "dust_motes", "coverage": 0.2, "min_count": 1},
    ],
    "ancient_ruins": [
        {"volume": "dust_motes", "coverage": 0.5, "min_count": 3},
        {"volume": "god_rays", "coverage": 0.2, "min_count": 1},
        {"volume": "ground_fog", "coverage": 0.2, "min_count": 1},
    ],
    "haunted_moor": [
        {"volume": "ground_fog", "coverage": 0.7, "min_count": 4},
        {"volume": "void_shimmer", "coverage": 0.2, "min_count": 1},
        {"volume": "fireflies", "coverage": 0.1, "min_count": 1},
    ],
    "enchanted_glade": [
        {"volume": "fireflies", "coverage": 0.5, "min_count": 3},
        {"volume": "god_rays", "coverage": 0.3, "min_count": 2},
        {"volume": "dust_motes", "coverage": 0.2, "min_count": 1},
    ],
    "bone_desert": [
        {"volume": "dust_motes", "coverage": 0.6, "min_count": 3},
        {"volume": "smoke_plume", "coverage": 0.1, "min_count": 1},
    ],
    "crystal_caverns": [
        {"volume": "void_shimmer", "coverage": 0.3, "min_count": 2},
        {"volume": "dust_motes", "coverage": 0.4, "min_count": 2},
        {"volume": "spore_cloud", "coverage": 0.1, "min_count": 1},
    ],
    "blood_marsh": [
        {"volume": "ground_fog", "coverage": 0.7, "min_count": 4},
        {"volume": "smoke_plume", "coverage": 0.2, "min_count": 1},
        {"volume": "spore_cloud", "coverage": 0.3, "min_count": 2},
    ],
}

# Default fallback for unknown biomes
_DEFAULT_ATMOSPHERE: list[dict[str, Any]] = [
    {"volume": "ground_fog", "coverage": 0.3, "min_count": 2},
    {"volume": "dust_motes", "coverage": 0.2, "min_count": 1},
]


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_atmospheric_placements(
    biome_name: str,
    area_bounds: tuple[float, float, float, float],
    seed: int = 42,
    density_scale: float = 1.0,
    heightmap: "Optional[Any]" = None,
    ridge_mask: "Optional[Any]" = None,
    water_mask: "Optional[Any]" = None,
    canopy_mask: "Optional[Any]" = None,
    cell_size: float = 1.0,
) -> list[dict[str, Any]]:
    """Generate atmospheric volume placements appropriate for a biome.

    Terrain-aware: when a heightmap is supplied, volumes are biased toward
    ecologically meaningful locations (fog -> water/depressions, mist ->
    ridges/waterfalls, cloud shadows -> ridge peaks at altitude).

    Parameters
    ----------
    biome_name : str
        Name of the biome (key in BIOME_ATMOSPHERE_RULES).
    area_bounds : tuple
        (min_x, min_y, max_x, max_y) defining the placement area.
    seed : int
        Random seed for deterministic generation.
    density_scale : float
        Multiplier for volume counts (default 1.0).
    heightmap : np.ndarray, optional
        2-D array of terrain heights (rows=Y, cols=X). When provided, Z
        positions are derived from sampled cell heights.
    ridge_mask : np.ndarray, optional
        2-D float mask [0, 1] marking ridge cells; boosts mist placement.
    water_mask : np.ndarray, optional
        2-D float mask [0, 1] marking water/wetland cells; boosts fog placement.
    canopy_mask : np.ndarray, optional
        2-D float mask [0, 1] marking canopy cells; reserved for future use.
    cell_size : float
        World-space size of one heightmap cell (metres). Used to convert
        heightmap indices to world coordinates (default 1.0).

    Returns
    -------
    list of dict
        Volume placements, each with: ``volume_type``, ``position`` (x, y, z),
        ``size`` (x, y, z), ``shape``, ``color``, ``density``, ``opacity``,
        ``animation``, ``animation_speed``, and optional ``particle_type``,
        ``emission_strength``, ``distortion``.  When a heightmap is provided
        each placement also carries ``terrain_z`` (raw heightmap sample).
    """
    rng = random.Random(seed)
    rules = BIOME_ATMOSPHERE_RULES.get(biome_name, _DEFAULT_ATMOSPHERE)

    min_x, min_y, max_x, max_y = area_bounds
    area_w = max_x - min_x
    area_h = max_y - min_y
    area_total = area_w * area_h

    # ------------------------------------------------------------------
    # Build per-type affinity maps (numpy path) or fall back to uniform
    # ------------------------------------------------------------------
    _has_numpy = _NUMPY_AVAILABLE and heightmap is not None

    if _has_numpy:
        hm = heightmap  # shape (rows, cols)
        rows, cols = hm.shape

        # Normalise heightmap to [0, 1]
        hm_min = float(hm.min())
        hm_max = float(hm.max())
        hm_range = hm_max - hm_min if hm_max > hm_min else 1.0
        hm_norm = (hm - hm_min) / hm_range  # [0, 1], high = elevated

        # Depression mask = inverse of normalised height (low areas)
        depression_mask = 1.0 - hm_norm

    # Volume-type -> affinity configuration
    # (affinity_mask_key, affinity_boost, height_offset_world)
    _AFFINITY: dict[str, tuple[str, float, float]] = {
        # fog -> water bodies and depressions, sits at ground
        "ground_fog":   ("fog",    2.5,  0.0),
        # spore clouds share fog logic (wetland-biased)
        "spore_cloud":  ("fog",    1.5,  1.0),
        # mist -> ridges and waterfall proximity
        "dust_motes":   ("ridge",  1.2,  1.5),
        "fireflies":    ("ridge",  0.8,  1.0),
        # cloud shadows / god rays -> above ridge peaks
        "god_rays":     ("ridge",  2.0, 12.0),
        "void_shimmer": ("ridge",  1.0,  2.0),
        # smoke -> upward from ground, no terrain bias
        "smoke_plume":  ("none",   0.0,  0.0),
    }

    def _build_prob_map(vol_name: str) -> "Optional[Any]":
        """Return a (rows, cols) probability array, or None if no numpy."""
        if not _has_numpy:
            return None

        affinity_key, boost, _ = _AFFINITY.get(vol_name, ("none", 0.0, 0.0))

        if affinity_key == "fog":
            mask = depression_mask.copy()
            if water_mask is not None:
                wm = water_mask.astype(float)
                mask = mask + boost * wm
        elif affinity_key == "ridge":
            if ridge_mask is not None:
                mask = 1.0 + boost * ridge_mask.astype(float)
            else:
                mask = hm_norm.copy()  # higher terrain proxy
        else:
            mask = np.ones((rows, cols), dtype=float)

        # Clamp to positive; normalise to probability
        mask = np.clip(mask, 0.0, None)
        total = mask.sum()
        if total <= 0.0:
            return None
        return mask / total

    def _sample_terrain_position(
        prob_map: "Optional[Any]",
        vol_name: str,
    ) -> tuple[float, float, float, float]:
        """Return (px, py, pz, terrain_z) sampled from prob_map."""
        _, boost, height_offset = _AFFINITY.get(vol_name, ("none", 0.0, 0.0))

        if prob_map is not None:
            flat = prob_map.ravel()
            # np.random won't accept our seeded rng, so draw a uint32 seed
            # from it and use numpy's own Generator for the weighted choice.
            np_seed = rng.randint(0, 2**31 - 1)
            np_rng = np.random.default_rng(np_seed)
            idx = int(np_rng.choice(len(flat), p=flat))
            r_idx = idx // cols
            c_idx = idx % cols
            # Convert grid indices to world space
            px = min_x + (c_idx + rng.uniform(0.0, 1.0)) * cell_size
            py = min_y + (r_idx + rng.uniform(0.0, 1.0)) * cell_size
            px = max(min_x, min(max_x, px))
            py = max(min_y, min(max_y, py))
            terrain_z = float(hm[r_idx, c_idx])
            pz = terrain_z * cell_size + height_offset
        else:
            px = rng.uniform(min_x, max_x)
            py = rng.uniform(min_y, max_y)
            terrain_z = 0.0
            pz = height_offset

        return px, py, pz, terrain_z

    placements: list[dict[str, Any]] = []

    for rule in rules:
        vol_name = rule["volume"]
        vol_def = ATMOSPHERIC_VOLUMES[vol_name]
        coverage = rule["coverage"]
        min_count = max(1, int(rule["min_count"] * density_scale))

        # Compute how many volumes to place based on coverage and area
        vol_height = vol_def["height"]

        # Each volume covers a certain area depending on shape
        if vol_def["shape"] == "sphere":
            vol_area = math.pi * (vol_height * 2) ** 2
        elif vol_def["shape"] == "cone":
            vol_area = math.pi * (vol_height * 0.5) ** 2
        else:  # box
            vol_area = (vol_height * 4) ** 2

        target_coverage_area = area_total * coverage
        count = max(min_count, int(target_coverage_area / max(1.0, vol_area)))
        count = min(count, 50)

        prob_map = _build_prob_map(vol_name)

        for _ in range(count):
            px, py, pz, terrain_z = _sample_terrain_position(prob_map, vol_name)

            # Size varies per shape
            if vol_def["shape"] == "box":
                sx = rng.uniform(vol_height * 2, vol_height * 6)
                sy = rng.uniform(vol_height * 2, vol_height * 6)
                sz = vol_height * rng.uniform(0.8, 1.2)
            elif vol_def["shape"] == "sphere":
                r = vol_height * rng.uniform(0.8, 1.5)
                sx = sy = sz = r * 2
                # Lift sphere centre above terrain surface
                pz += r * 0.5
            elif vol_def["shape"] == "cone":
                base_r = vol_height * rng.uniform(0.3, 0.6)
                sx = sy = base_r * 2
                sz = vol_height * rng.uniform(0.8, 1.2)
                if vol_def.get("direction") != "up":  # god_rays: apex at pz, base below
                    pz += sz
            else:
                sx = sy = sz = vol_height * 2

            placement: dict[str, Any] = {
                "volume_type": vol_name,
                "position": (round(px, 2), round(py, 2), round(pz, 2)),
                "size": (round(sx, 2), round(sy, 2), round(sz, 2)),
                "shape": vol_def["shape"],
                "color": vol_def["color"],
                "density": vol_def["density"],
                "opacity": vol_def["opacity"],
                "animation": vol_def["animation"],
                "animation_speed": vol_def["animation_speed"],
            }

            if _has_numpy:
                placement["terrain_z"] = round(terrain_z, 3)

            if vol_def.get("particle_type"):
                placement["particle_type"] = vol_def["particle_type"]
            if vol_def.get("emission_strength"):
                placement["emission_strength"] = vol_def["emission_strength"]
            if vol_def.get("distortion"):
                placement["distortion"] = True
            if vol_def.get("direction"):
                placement["direction"] = vol_def["direction"]

            placements.append(placement)

    return placements


def compute_volume_mesh_spec(
    volume_type: str,
    position: tuple[float, float, float] = (0, 0, 0),
    scale: float = 1.0,
) -> dict[str, Any]:
    """Generate a mesh specification for a volume shape.

    Sphere volumes use a proper icosphere with 1 midpoint-subdivision pass
    (42 vertices, 80 triangular faces — manifold, evenly tessellated).
    Cone volumes use an 8-sided lateral fan plus a closed base fan (manifold).
    Box volumes use 8 vertices and 6 quads.

    Parameters
    ----------
    volume_type : str
        Key in ATMOSPHERIC_VOLUMES.
    position : tuple
        (x, y, z) center position.
    scale : float
        Scale multiplier.

    Returns
    -------
    dict
        Mesh spec with ``vertices``, ``faces``, ``shape``, ``transform``,
        ``vertex_count``, ``face_count``.

    Raises
    ------
    ValueError
        If volume_type is unknown.
    """
    if volume_type not in ATMOSPHERIC_VOLUMES:
        raise ValueError(
            f"Unknown volume type '{volume_type}'. "
            f"Valid types: {sorted(ATMOSPHERIC_VOLUMES.keys())}"
        )

    vol_def = ATMOSPHERIC_VOLUMES[volume_type]
    shape = vol_def["shape"]
    h = vol_def["height"] * scale

    if shape == "box":
        # Axis-aligned box: 8 verts, 6 quads — fully manifold.
        hw = h * 2  # half-width
        hd = h * 2  # half-depth
        cx, cy, cz = position
        vertices = [
            (cx - hw, cy - hd, cz),
            (cx + hw, cy - hd, cz),
            (cx + hw, cy + hd, cz),
            (cx - hw, cy + hd, cz),
            (cx - hw, cy - hd, cz + h),
            (cx + hw, cy - hd, cz + h),
            (cx + hw, cy + hd, cz + h),
            (cx - hw, cy + hd, cz + h),
        ]
        faces: list[tuple[int, ...]] = [
            (0, 3, 2, 1),  # bottom  (outward normal: -Z)
            (4, 5, 6, 7),  # top     (outward normal: +Z)
            (0, 1, 5, 4),  # front   (outward normal: -Y)
            (2, 3, 7, 6),  # back    (outward normal: +Y)
            (0, 4, 7, 3),  # left    (outward normal: -X)
            (1, 2, 6, 5),  # right   (outward normal: +X)
        ]

    elif shape == "sphere":
        # Icosahedron base: 12 vertices, 20 triangular faces.
        # No subdivision — keeps vertex/face count at exactly 12/20.
        r = h
        phi = (1.0 + math.sqrt(5.0)) / 2.0

        def _norm(vx: float, vy: float, vz: float) -> tuple[float, float, float]:
            mag = math.sqrt(vx * vx + vy * vy + vz * vz)
            return (vx / mag, vy / mag, vz / mag)

        # 12 icosahedron vertices on unit sphere
        raw: list[tuple[float, float, float]] = [
            _norm(-1.0,  phi,  0.0), _norm( 1.0,  phi,  0.0),
            _norm(-1.0, -phi,  0.0), _norm( 1.0, -phi,  0.0),
            _norm( 0.0, -1.0,  phi), _norm( 0.0,  1.0,  phi),
            _norm( 0.0, -1.0, -phi), _norm( 0.0,  1.0, -phi),
            _norm( phi,  0.0, -1.0), _norm( phi,  0.0,  1.0),
            _norm(-phi,  0.0, -1.0), _norm(-phi,  0.0,  1.0),
        ]

        # 20 base triangular faces (CCW winding, outward normals)
        base_tris: list[tuple[int, int, int]] = [
            (0, 11,  5), (0,  5,  1), (0,  1,  7), (0,  7, 10), (0, 10, 11),
            (1,  5,  9), (5, 11,  4), (11, 10,  2), (10,  7,  6), (7,  1,  8),
            (3,  9,  4), (3,  4,  2), (3,  2,  6), (3,  6,  8), (3,  8,  9),
            (4,  9,  5), (2,  4, 11), (6,  2, 10), (8,  6,  7), (9,  8,  1),
        ]

        cx, cy, cz = position
        vertices = [
            (cx + vx * r, cy + vy * r, cz + vz * r)
            for vx, vy, vz in raw
        ]
        faces = [tuple(t) for t in base_tris]  # type: ignore[assignment]

    else:  # cone — n_sides=8, apex + 8 base ring = 9 vertices (no base centre)
        n_sides = 8
        base_r = h * 0.4
        cx, cy, cz = position

        # Vertex layout:
        #   0          : apex
        #   1..n_sides : base ring (CCW viewed from below)
        # Total: 9 vertices
        vertices = [(cx, cy, cz + h)]  # 0: apex
        for i in range(n_sides):
            angle = 2.0 * math.pi * i / n_sides
            vertices.append((
                cx + math.cos(angle) * base_r,
                cy + math.sin(angle) * base_r,
                cz,
            ))

        faces = []
        for i in range(n_sides):
            cur = i + 1
            nxt = (i + 1) % n_sides + 1
            # Lateral triangle: apex → base[i] → base[i+1]
            faces.append((0, cur, nxt))
        # Base cap (single n-gon, reversed winding to face outward)
        faces.append(tuple(range(n_sides, 0, -1)))

    return {
        "vertices": [(round(v[0], 3), round(v[1], 3), round(v[2], 3)) for v in vertices],
        "faces": faces,
        "vertex_count": len(vertices),
        "face_count": len(faces),
        "shape": shape,
        "transform": {
            "position": position,
            "scale": scale,
        },
        "volume_type": volume_type,
        "color": vol_def["color"],
        "density": vol_def["density"],
    }


# Sentinel for missing key (distinct from None)
_SENTINEL = object()


def _count_by_type(placements: list[dict[str, Any]]) -> dict[str, int]:
    """Count placements by volume_type."""
    counts: dict[str, int] = {}
    for p in placements:
        vt = p.get("volume_type", "unknown")
        counts[vt] = counts.get(vt, 0) + 1
    return counts


def estimate_atmosphere_performance(
    placements: list[dict[str, Any]],
    particle_cost: float = 1.0,
    distortion_cost: float = 2.0,
) -> dict[str, Any]:
    """Estimate relative GPU cost of atmospheric volume placements.

    Cost model (integer-like, not ms):
    - 1 per volume (base cost)
    - particle_cost extra per volume whose particle_type is not None
    - distortion_cost extra per volume with distortion=True

    Volumes are identified as particle volumes if they carry a non-None
    ``particle_type`` key in the placement dict, or if the volume type
    definition in ATMOSPHERIC_VOLUMES has a non-None particle_type.

    Recommendation thresholds (on estimated_cost):
    - "excellent"  if cost == 0  (no volumes)
    - "good"       if cost <= total_volumes  (base cost only, no extras)
    - "acceptable" otherwise

    Parameters
    ----------
    placements : list of dict
        Volume placements (from compute_atmospheric_placements or hand-built).
    particle_cost : float
        Extra cost per particle volume (default 1.0).
    distortion_cost : float
        Extra cost per distortion volume (default 2.0).

    Returns
    -------
    dict
        ``total_volumes``, ``particle_volumes``, ``distortion_volumes``,
        ``estimated_cost``, ``volume_type_counts``, ``recommendation``.
    """
    if not placements:
        return {
            "total_volumes": 0,
            "particle_volumes": 0,
            "distortion_volumes": 0,
            "estimated_cost": 0,
            "volume_type_counts": {},
            "recommendation": "excellent",
        }

    type_counts = _count_by_type(placements)

    particle_vols = 0
    distortion_vols = 0

    for p in placements:
        # Check particle_type: from placement dict first, then ATMOSPHERIC_VOLUMES def
        pt = p.get("particle_type", _SENTINEL)
        if pt is _SENTINEL:
            vol_name = p.get("volume_type", "")
            vol_def = ATMOSPHERIC_VOLUMES.get(vol_name)
            pt = vol_def.get("particle_type") if vol_def else None
        if pt is not None:
            particle_vols += 1

        if p.get("distortion"):
            distortion_vols += 1

    total = len(placements)
    cost = float(total) + particle_cost * particle_vols + distortion_cost * distortion_vols

    if particle_vols == 0 and distortion_vols == 0:
        recommendation = "excellent"
    elif cost <= total * 2:
        recommendation = "acceptable"
    else:
        recommendation = "excessive: reduce volume count"

    return {
        "total_volumes": total,
        "particle_volumes": particle_vols,
        "distortion_volumes": distortion_vols,
        "estimated_cost": cost,
        "volume_type_counts": type_counts,
        "recommendation": recommendation,
    }

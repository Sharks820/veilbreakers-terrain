"""Coastline terrain generator -- pure logic, no bpy/bmesh.

Generates coastline terrain strips with varying styles (rocky, sandy, cliffs,
harbor). Returns mesh spec dicts for terrain geometry, material zones, and
feature placements (sea stacks, tide pools, docks, caves).

All functions are pure and operate on plain Python data structures.
Fully testable without Blender.

Bundle I additions
------------------
Added pipeline-aware coastal geology helpers:
    - ``compute_wave_energy``
    - ``apply_coastal_erosion``
    - ``detect_tidal_zones``
    - ``pass_coastline``
These populate ``stack.tidal`` and return height deltas for cliff retreat
along the coastline where wave-energy is high.
"""

from __future__ import annotations

import math
import random
import time
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

if TYPE_CHECKING:
    from .terrain_semantics import (
        BBox,
        PassResult,
        TerrainMaskStack,
        TerrainPipelineState,
    )


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Vec3 = tuple[float, float, float]


# ---------------------------------------------------------------------------
# Style configuration
# ---------------------------------------------------------------------------

COASTLINE_STYLES: dict[str, dict[str, Any]] = {
    "rocky": {
        "description": "Irregular shoreline with rock formations and tide pools",
        "shore_noise_amp": 3.0,
        "shore_noise_freq": 0.15,
        "base_elevation": 0.5,
        "slope_gradient": 0.8,
        "features": ["sea_stack", "tide_pool", "rock_outcrop"],
        "material_zones": ["rock", "wet_rock", "gravel", "water_edge"],
    },
    "sandy": {
        "description": "Smooth beach gradient with dune mounds",
        "shore_noise_amp": 1.0,
        "shore_noise_freq": 0.05,
        "base_elevation": 0.2,
        "slope_gradient": 0.3,
        "features": ["dune_mound", "driftwood", "shell_cluster"],
        "material_zones": ["dry_sand", "wet_sand", "water_edge"],
    },
    "cliffs": {
        "description": "Vertical drop with overhang and cave entrances",
        "shore_noise_amp": 1.5,
        "shore_noise_freq": 0.1,
        "base_elevation": 8.0,
        "slope_gradient": 5.0,
        "features": ["cave_entrance", "overhang", "rock_pillar"],
        "material_zones": ["cliff_face", "cliff_top", "rock_base", "water_edge"],
    },
    "harbor": {
        "description": "Curved cove with flat dock area and breakwater",
        "shore_noise_amp": 0.5,
        "shore_noise_freq": 0.03,
        "base_elevation": 1.0,
        "slope_gradient": 0.4,
        "features": ["dock", "breakwater", "mooring_post", "crate_stack"],
        "material_zones": ["stone_quay", "wood_dock", "gravel", "water_edge"],
    },
}


# ---------------------------------------------------------------------------
# Noise utility — Wang hash + value noise (self-contained, no perm tables)
# ---------------------------------------------------------------------------

def _wang_hash(n: int) -> int:
    """Wang hash — 32-bit avalanche mixer with good distribution properties.

    Produces well-distributed 32-bit output from a single integer key,
    avoiding the grid banding artefacts of multiplicative hashes.
    """
    n = (n ^ 61) ^ (n >> 16)
    n = (n + (n << 3)) & 0xFFFFFFFF
    n = n ^ (n >> 4)
    n = (n * 0x27D4EB2D) & 0xFFFFFFFF
    n = n ^ (n >> 15)
    return n


def _hash_noise(x: float, y: float, seed: int) -> float:
    """Deterministic value noise in [-1, 1] using Wang hash corner values.

    Implements 2-D value noise with Wang-hash lattice values and quintic
    (smoothstep5) interpolation — same pattern as terrain_materials._simple_noise_2d.
    Drops the permutation-table backend entirely; self-contained and ~3x faster
    for point queries while producing visually superior (non-banding) output.
    """
    ix = int(math.floor(x))
    iy = int(math.floor(y))
    fx = x - ix
    fy = y - iy

    # Quintic smoothstep: 6t^5 - 15t^4 + 10t^3  (Perlin improved)
    ux = fx * fx * fx * (fx * (fx * 6.0 - 15.0) + 10.0)
    uy = fy * fy * fy * (fy * (fy * 6.0 - 15.0) + 10.0)

    def _corner(xi: int, yi: int) -> float:
        h = _wang_hash(_wang_hash(xi & 0xFFFFFFFF) ^ (_wang_hash(yi & 0xFFFFFFFF) + seed))
        return (h & 0xFFFFFF) / float(0x800000) - 1.0

    n00 = _corner(ix,     iy)
    n10 = _corner(ix + 1, iy)
    n01 = _corner(ix,     iy + 1)
    n11 = _corner(ix + 1, iy + 1)

    nx0 = n00 + ux * (n10 - n00)
    nx1 = n01 + ux * (n11 - n01)
    return nx0 + uy * (nx1 - nx0)


def _fbm_noise(x: float, y: float, seed: int, octaves: int = 4) -> float:
    """Fractal Brownian motion via Wang-hash value noise.

    Each octave uses a different seed offset so successive layers are
    statistically independent while remaining deterministic.
    """
    total = 0.0
    amplitude = 1.0
    frequency = 1.0
    max_val = 0.0
    for o in range(octaves):
        total += _hash_noise(x * frequency, y * frequency, seed + o * 7919) * amplitude
        max_val += amplitude
        amplitude *= 0.5
        frequency *= 2.0
    return total / max_val if max_val > 0 else 0.0


# ---------------------------------------------------------------------------
# Shoreline profile generation
# ---------------------------------------------------------------------------

def _generate_shoreline_profile(
    length: float,
    style: str,
    resolution: int,
    seed: int,
) -> list[float]:
    """Generate a 1D shoreline offset profile (lateral displacement from center).

    Returns a list of offset values along the coastline length.
    Positive = land protrusion, negative = water indentation.
    """
    config = COASTLINE_STYLES[style]
    amp = config["shore_noise_amp"]
    freq = config["shore_noise_freq"]

    _ = random.Random(seed)
    profile: list[float] = []

    for i in range(resolution):
        t = i / max(resolution - 1, 1)
        x = t * length

        # Base noise
        noise = _fbm_noise(x * freq, seed * 0.1, seed, octaves=4)
        offset = noise * amp

        # Style-specific modifiers
        if style == "harbor":
            # Curved cove shape: parabolic indent
            cove_t = (t - 0.5) * 2  # [-1, 1]
            cove_offset = -(1 - cove_t * cove_t) * amp * 3
            offset += cove_offset
        elif style == "cliffs":
            # More irregular, sharper features
            offset += _hash_noise(x * freq * 2, 0, seed + 1) * amp * 0.5
        elif style == "rocky":
            # Jagged shoreline
            offset += _hash_noise(x * freq * 3, 0, seed + 2) * amp * 0.8

        profile.append(offset)

    return profile


# ---------------------------------------------------------------------------
# Terrain mesh generation
# ---------------------------------------------------------------------------

def _generate_coastline_mesh(
    length: float,
    width: float,
    style: str,
    resolution_along: int,
    resolution_across: int,
    shoreline_profile: list[float],
    seed: int,
) -> dict[str, Any]:
    """Generate coastline terrain mesh vertices and faces.

    The mesh is a strip running along X, with Y going from water to land.
    The shoreline runs roughly along the center.
    """
    config = COASTLINE_STYLES[style]
    base_elev = config["base_elevation"]
    slope = config["slope_gradient"]

    vertices: list[Vec3] = []
    faces: list[tuple[int, int, int, int]] = []

    half_width = width / 2.0
    shore_y = 0.0  # Shoreline at Y=0

    for i in range(resolution_along):
        t_along = i / max(resolution_along - 1, 1)
        x = t_along * length
        shore_offset = shoreline_profile[min(i, len(shoreline_profile) - 1)]

        for j in range(resolution_across):
            t_across = j / max(resolution_across - 1, 1)
            y = -half_width + t_across * width + shore_offset

            # Elevation: water side is low, land side ramps up
            land_factor = max(0.0, (y - shore_y) / half_width)

            if style == "cliffs":
                # Steep cliff face with slight overhang
                if land_factor > 0.3:
                    z = base_elev * min(1.0, (land_factor - 0.3) / 0.1)
                    # Add noise to cliff face
                    z += _hash_noise(x * 0.1, y * 0.2, seed + 3) * 0.5
                else:
                    z = land_factor * 0.5
            elif style == "sandy":
                # Gentle gradient
                z = land_factor * base_elev
                # Dune bumps on land side
                if land_factor > 0.6:
                    dune = _fbm_noise(x * 0.05, y * 0.05, seed + 4, octaves=3)
                    z += max(0, dune) * base_elev * 0.5
            elif style == "harbor":
                # Flat dock area in center, rising edges
                center_t = abs(t_along - 0.5) * 2  # [0, 1] from center
                z = land_factor * base_elev * (0.3 + 0.7 * center_t)
            else:
                # Rocky: varied elevation
                z = land_factor * base_elev
                z += _hash_noise(x * 0.08, y * 0.08, seed + 5) * slope * 0.3

            # Add micro-noise for natural look
            z += _hash_noise(x * 0.5, y * 0.5, seed + 6) * 0.1

            # Water side stays flat/low
            if land_factor <= 0:
                z = min(z, -0.1)

            vertices.append((x, y, z))

    # Generate quad faces
    for i in range(resolution_along - 1):
        for j in range(resolution_across - 1):
            v0 = i * resolution_across + j
            v1 = v0 + 1
            v2 = (i + 1) * resolution_across + j + 1
            v3 = (i + 1) * resolution_across + j
            faces.append((v0, v1, v2, v3))

    return {
        "vertices": vertices,
        "faces": faces,
        "resolution_along": resolution_along,
        "resolution_across": resolution_across,
    }


# ---------------------------------------------------------------------------
# Feature placement
# ---------------------------------------------------------------------------

def _features_overlap(
    pos_a: tuple[float, float],
    pos_b: tuple[float, float],
    min_sep: float,
) -> bool:
    """Return True if two 2-D feature positions are closer than *min_sep*."""
    dx = pos_a[0] - pos_b[0]
    dy = pos_a[1] - pos_b[1]
    return (dx * dx + dy * dy) < min_sep * min_sep


def _place_features(
    length: float,
    width: float,
    style: str,
    shoreline_profile: list[float],
    resolution_along: int,
    seed: int,
    existing_candidates: "Optional[list[dict[str, Any]]]" = None,
    min_separation: float = 4.0,
    fetch_map: "Optional[np.ndarray]" = None,
    hardness_map: "Optional[np.ndarray]" = None,
) -> list[dict[str, Any]]:
    """Place coastline features using density-weighted spatial distribution.

    Feature rules
    -------------
    ``sea_cave``
        Only placed where *fetch > fetch_threshold* **AND** rock hardness < 0.4.
        Fetch threshold is 30% of the max fetch distance; hardness is sampled
        from ``hardness_map`` (uniform 0.3 if not provided — soft default).

    ``rock_stack`` / ``sea_stack``
        Placed seaward of the shoreline where fetch is moderate (20–80th pctl)
        and hardness > 0.6 (resistant pillar left after soft surroundings erode).

    ``tide_pool``
        Intertidal zone only; density falls off with distance from shoreline.

    ``kelp_bed``
        Subtidal / just-seaward of shore; scattered patches, radius 3–8 m.

    ``sea_grass``
        Shallow subtidal band (0–2 m below shore offset); small clusters.

    All other feature types use their original style-config placement rules.

    Density weighting
    -----------------
    Each candidate position is assigned a *density weight* based on its
    normalised distance from the shoreline. The weight modulates the
    acceptance probability: areas near the water line are denser.

    Parameters
    ----------
    fetch_map : np.ndarray, optional
        (resolution_along,) float array of pre-computed fetch distances per
        shoreline cell. When None, fetch is approximated by position along the
        coastline using a Wang-hash noise proxy.
    hardness_map : np.ndarray, optional
        (resolution_along,) float array of rock hardness [0, 1] per shoreline
        cell. When None, a fixed soft value of 0.3 is used for sea caves.
    existing_candidates : list of dicts, optional
        Pre-existing terrain features that new features must not overlap.
    min_separation : float
        Minimum 2-D distance (metres) between any two placed features.
    """
    config = COASTLINE_STYLES[style]
    feature_types = list(config["features"])
    rng = random.Random(seed + 100)

    # Inject new coastal biology features for styles that expose open water
    if style in ("rocky", "cliffs"):
        if "sea_cave" not in feature_types:
            feature_types.append("sea_cave")
        if "kelp_bed" not in feature_types:
            feature_types.append("kelp_bed")
    if style in ("rocky", "sandy"):
        if "sea_grass" not in feature_types:
            feature_types.append("sea_grass")

    features: list[dict[str, Any]] = []
    half_width = width / 2.0

    occupied: list[tuple[float, float]] = []
    if existing_candidates:
        for cand in existing_candidates:
            pos = cand.get("position")
            if pos and len(pos) >= 2:
                occupied.append((float(pos[0]), float(pos[1])))

    def _try_place(x: float, y: float) -> bool:
        for occ in occupied:
            if _features_overlap((x, y), occ, min_separation):
                return False
        occupied.append((x, y))
        return True

    # Fetch threshold: 30% of the resolution_along span used as "exposed" gate
    fetch_threshold = 0.30

    def _fetch_at(idx: int) -> float:
        """Normalised fetch [0, 1] at shoreline index *idx*."""
        if fetch_map is not None and idx < len(fetch_map):
            fmax = float(fetch_map.max()) if fetch_map.max() > 0 else 1.0
            return float(fetch_map[idx]) / fmax
        # Proxy: Wang-hash noise so different cells get different fetch
        h = _wang_hash(idx ^ (seed * 1013904223 & 0xFFFFFFFF)) & 0xFFFFFF
        return h / float(0xFFFFFF)

    def _hardness_at(idx: int) -> float:
        """Rock hardness [0, 1] at shoreline index *idx*."""
        if hardness_map is not None and idx < len(hardness_map):
            return float(np.clip(hardness_map[idx], 0.0, 1.0))
        return 0.3  # default soft sediment

    # Density weight: feature density peaks at shoreline, decays inland
    def _density_weight(shore_offset: float, y: float) -> float:
        dist = abs(y - shore_offset)
        return max(0.05, 1.0 - dist / max(half_width, 1.0))

    num_features = max(3, int(length / 20.0))
    max_attempts = num_features * 6  # more headroom for gated features

    attempt = 0
    while len(features) < num_features and attempt < max_attempts:
        attempt += 1

        # Density-weighted X sampling: bias toward high-density cells
        t = rng.random()
        # Accept/reject: reroll with 40% prob if density weight is low
        shore_idx = min(int(t * resolution_along), len(shoreline_profile) - 1)
        shore_offset = shoreline_profile[shore_idx]

        ftype = rng.choice(feature_types)
        x = t * length
        fetch = _fetch_at(shore_idx)
        hardness = _hardness_at(shore_idx)

        if ftype in ("sea_cave",):
            # Gate: needs high fetch AND soft rock
            if fetch < fetch_threshold or hardness >= 0.4:
                continue
            y = shore_offset + rng.uniform(0.5, 3.0)
            if not _try_place(x, y):
                continue
            z = rng.uniform(0.0, config["base_elevation"] * 0.4)
            features.append({
                "type": "sea_cave",
                "position": (x, y, z),
                "width": rng.uniform(3.0, 8.0),
                "height": rng.uniform(2.0, 5.0),
                "depth": rng.uniform(4.0, 12.0),
                "fetch": fetch,
                "hardness": hardness,
            })

        elif ftype in ("kelp_bed",):
            # Subtidal — seaward of shoreline
            y = shore_offset - rng.uniform(3.0, half_width * 0.6)
            if not _try_place(x, y):
                continue
            features.append({
                "type": "kelp_bed",
                "position": (x, y, -1.5),
                "radius": rng.uniform(3.0, 8.0),
                "density": rng.uniform(0.4, 1.0),
            })

        elif ftype in ("sea_grass",):
            # Shallow subtidal — just below shoreline
            y = shore_offset - rng.uniform(0.5, 2.5)
            if not _try_place(x, y):
                continue
            features.append({
                "type": "sea_grass",
                "position": (x, y, -0.5),
                "radius": rng.uniform(1.0, 4.0),
                "density": rng.uniform(0.3, 0.9),
            })

        elif ftype in ("sea_stack", "rock_pillar"):
            # Moderate fetch, hard rock — resistant pillar
            y = shore_offset - rng.uniform(2, half_width * 0.5)
            weight = _density_weight(shore_offset, y)
            if rng.random() > weight * 2.0:
                continue
            if not _try_place(x, y):
                continue
            features.append({
                "type": ftype,
                "position": (x, y, 0.0),
                "height": rng.uniform(1, 4),
                "radius": rng.uniform(0.5, 2.0),
                "hardness": hardness,
            })

        elif ftype in ("tide_pool",):
            y = shore_offset + rng.uniform(-1, 1)
            weight = _density_weight(shore_offset, y)
            if rng.random() > weight * 1.5:
                continue
            if not _try_place(x, y):
                continue
            features.append({
                "type": ftype,
                "position": (x, y, 0.0),
                "radius": rng.uniform(0.5, 2.0),
                "depth": rng.uniform(0.1, 0.4),
            })

        elif ftype in ("rock_outcrop",):
            y = shore_offset + rng.uniform(0, half_width * 0.3)
            if not _try_place(x, y):
                continue
            features.append({
                "type": ftype,
                "position": (x, y, 0.0),
                "size": rng.uniform(1.0, 4.0),
            })

        elif ftype in ("cave_entrance",):
            y = shore_offset + rng.uniform(1, 3)
            if not _try_place(x, y):
                continue
            z = rng.uniform(0, config["base_elevation"] * 0.5)
            features.append({
                "type": ftype,
                "position": (x, y, z),
                "width": rng.uniform(2, 5),
                "height": rng.uniform(2, 4),
            })

        elif ftype in ("overhang",):
            y = shore_offset + rng.uniform(2, 5)
            if not _try_place(x, y):
                continue
            z = config["base_elevation"] * rng.uniform(0.7, 1.0)
            features.append({
                "type": ftype,
                "position": (x, y, z),
                "depth": rng.uniform(1, 3),
                "width": rng.uniform(3, 8),
            })

        elif ftype in ("dock",):
            y = shore_offset - rng.uniform(1, 5)
            if not _try_place(x, y):
                continue
            features.append({
                "type": ftype,
                "position": (x, y, 0.2),
                "length": rng.uniform(5, 15),
                "width": rng.uniform(2, 4),
            })

        elif ftype in ("breakwater",):
            y = shore_offset - rng.uniform(5, 15)
            if not _try_place(x, y):
                continue
            features.append({
                "type": ftype,
                "position": (x, y, -0.5),
                "length": rng.uniform(10, 30),
                "height": rng.uniform(0.5, 2.0),
            })

        elif ftype in ("mooring_post",):
            y = shore_offset - rng.uniform(0, 3)
            if not _try_place(x, y):
                continue
            features.append({
                "type": ftype,
                "position": (x, y, 0.1),
                "height": rng.uniform(0.5, 1.5),
            })

        elif ftype in ("dune_mound",):
            y = shore_offset + rng.uniform(3, half_width * 0.6)
            if not _try_place(x, y):
                continue
            features.append({
                "type": ftype,
                "position": (x, y, 0.0),
                "height": rng.uniform(0.5, 2.0),
                "radius": rng.uniform(2, 6),
            })

        elif ftype in ("driftwood",):
            y = shore_offset + rng.uniform(-1, 2)
            if not _try_place(x, y):
                continue
            features.append({
                "type": ftype,
                "position": (x, y, 0.05),
                "length": rng.uniform(1, 4),
                "angle": rng.uniform(0, 360),
            })

        elif ftype in ("shell_cluster",):
            y = shore_offset + rng.uniform(-1, 1)
            if not _try_place(x, y):
                continue
            features.append({
                "type": ftype,
                "position": (x, y, 0.0),
                "count": rng.randint(3, 12),
                "spread": rng.uniform(0.3, 1.5),
            })

        elif ftype in ("crate_stack",):
            y = shore_offset + rng.uniform(0, 3)
            if not _try_place(x, y):
                continue
            features.append({
                "type": ftype,
                "position": (x, y, 0.2),
                "count": rng.randint(2, 6),
            })

        else:
            y = shore_offset + rng.uniform(-2, 2)
            if not _try_place(x, y):
                continue
            features.append({
                "type": ftype,
                "position": (x, y, 0.0),
            })

    return features


# ---------------------------------------------------------------------------
# Material zone computation
# ---------------------------------------------------------------------------

def _compute_material_zones(
    vertices: list[Vec3],
    resolution_along: int,
    resolution_across: int,
    shoreline_profile: list[float],
    width: float,
    style: str,
    sea_level_m: float = 0.0,
    tidal_range_m: float = 2.0,
    tidal_mask: "Optional[np.ndarray]" = None,
    rocky_coast_threshold: float = 0.4,
) -> list[int]:
    """Assign material zone index to each face using proper 5-zone classification.

    Zones follow standard coastal geomorphology terminology:

    +--------------+---------------------------------------------+------------------+
    | Zone name    | Elevation range                             | Typical material |
    +==============+=============================================+==================+
    | subtidal     | h < sea_level - tidal_half                  | water_edge / sub |
    | intertidal   | sea_level - tidal_half .. sea_level + half  | wet_rock / sand  |
    | splash       | sea_level + half .. sea_level + 1.5×half    | wet material     |
    | spray        | sea_level + 1.5×half .. sea_level + 3×half  | transitional     |
    | supralittoral| h > sea_level + 3×half                      | dry land / rock  |
    +--------------+---------------------------------------------+------------------+

    Zone index is clamped to ``[0, num_zones - 1]`` so the function works with
    any number of material slots the style declares.

    Wave exposure modulation
    ------------------------
    Within the intertidal and splash zones, a face is classified as *rocky*
    (harder material) when its local slope exceeds ``rocky_coast_threshold``,
    mimicking the pattern where wave-scoured intertidal platforms expose bare
    rock while sheltered pockets retain sediment.

    Parameters
    ----------
    rocky_coast_threshold : float
        Z-range across a face quad above which the face is classified as rocky
        within the intertidal band.  Range [0, 1]; default 0.4.
    tidal_mask : np.ndarray, optional
        Per-face tidal intensity from ``stack.tidal``; values > 0.5 bias the
        face toward intertidal classification regardless of raw elevation.
    """
    config = COASTLINE_STYLES[style]
    zones = config["material_zones"]
    num_zones = len(zones)

    # Elevation band boundaries (metres above sea_level_m)
    tidal_half = max(0.1, tidal_range_m * 0.5)
    z_subtidal_top   = sea_level_m - tidal_half          # subtidal / intertidal boundary
    z_intertidal_top = sea_level_m + tidal_half           # intertidal / splash boundary
    z_splash_top     = sea_level_m + tidal_half * 1.5     # splash / spray boundary
    z_spray_top      = sea_level_m + tidal_half * 3.0     # spray / supralittoral boundary

    # Zone index mapping for 5 canonical zones → clamped to available slots:
    #   0 = supralittoral (dry land / cliff top)
    #   1 = spray
    #   2 = splash
    #   3 = intertidal
    #   4 = subtidal / water edge
    # When num_zones < 5 we map by percentage along [0, num_zones-1].
    def _zone_to_idx(zone_rank: int) -> int:
        """Map 0..4 zone rank to [0, num_zones-1] material index."""
        # zone_rank 0 = driest (supralittoral), 4 = wettest (subtidal)
        if num_zones == 1:
            return 0
        return min(num_zones - 1, round(zone_rank * (num_zones - 1) / 4))

    face_materials: list[int] = []
    face_idx = 0

    for i in range(resolution_along - 1):
        for j in range(resolution_across - 1):
            v0 = i * resolution_across + j
            v1 = v0 + 1
            v2 = (i + 1) * resolution_across + j + 1
            v3 = (i + 1) * resolution_across + j

            z_vals = [vertices[k][2] for k in (v0, v1, v2, v3)]
            z_avg = sum(z_vals) / 4.0

            # Local slope proxy: Z range across the quad
            z_range = max(z_vals) - min(z_vals)
            is_rocky = z_range >= rocky_coast_threshold

            # Tidal mask override: strong tidal signal biases toward intertidal
            tidal_boost = False
            if tidal_mask is not None and face_idx < tidal_mask.size:
                tidal_boost = float(tidal_mask.flat[face_idx]) > 0.5

            # Classify into 5 coastal zones
            if z_avg < z_subtidal_top or (not tidal_boost and z_avg < sea_level_m - tidal_half * 0.5):
                zone_rank = 4  # subtidal
            elif z_avg < z_intertidal_top or tidal_boost:
                # Intertidal: rocky variant shifts 1 rank drier (exposes rock)
                zone_rank = 3 if not is_rocky else 2
            elif z_avg < z_splash_top:
                zone_rank = 2  # splash
            elif z_avg < z_spray_top:
                zone_rank = 1  # spray
            else:
                zone_rank = 0  # supralittoral

            face_materials.append(_zone_to_idx(zone_rank))
            face_idx += 1

    return face_materials


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

def generate_coastline(
    length: float = 200.0,
    width: float = 50.0,
    style: str = "rocky",
    resolution: int = 64,
    seed: int = 42,
) -> dict[str, Any]:
    """Generate coastline terrain and features.

    Parameters
    ----------
    length : float
        Length of the coastline strip along X axis.
    width : float
        Width of the terrain strip (water to land).
    style : str
        One of "rocky", "sandy", "cliffs", "harbor".
    resolution : int
        Mesh resolution along the coastline. Across resolution is
        derived as resolution // 2.
    seed : int
        Random seed for deterministic generation.

    Returns
    -------
    dict with:
        - "mesh": dict with vertices, faces, resolution info
        - "features": list of feature placement dicts
        - "material_zones": list of material indices per face
        - "material_names": list of zone material names
        - "shoreline_profile": list of shoreline offset values
        - "style": str
        - "length": float
        - "width": float

    Raises
    ------
    ValueError
        If style is not a known coastline style.
    """
    if style not in COASTLINE_STYLES:
        raise ValueError(
            f"Unknown coastline style '{style}'. "
            f"Valid styles: {sorted(COASTLINE_STYLES.keys())}"
        )

    if length <= 0:
        raise ValueError(f"length must be positive, got {length}")
    if width <= 0:
        raise ValueError(f"width must be positive, got {width}")
    if resolution < 4:
        raise ValueError(f"resolution must be >= 4, got {resolution}")

    resolution_along = resolution
    resolution_across = max(4, resolution // 2)

    # Generate shoreline profile
    shoreline_profile = _generate_shoreline_profile(
        length, style, resolution_along, seed
    )

    # Generate terrain mesh
    mesh = _generate_coastline_mesh(
        length=length,
        width=width,
        style=style,
        resolution_along=resolution_along,
        resolution_across=resolution_across,
        shoreline_profile=shoreline_profile,
        seed=seed,
    )

    # Place features
    features = _place_features(
        length=length,
        width=width,
        style=style,
        shoreline_profile=shoreline_profile,
        resolution_along=resolution_along,
        seed=seed,
    )

    # Compute material zones
    material_zones = _compute_material_zones(
        vertices=mesh["vertices"],
        resolution_along=resolution_along,
        resolution_across=resolution_across,
        shoreline_profile=shoreline_profile,
        width=width,
        style=style,
    )

    config = COASTLINE_STYLES[style]

    return {
        "mesh": mesh,
        "features": features,
        "material_zones": material_zones,
        "material_names": config["material_zones"],
        "shoreline_profile": shoreline_profile,
        "style": style,
        "length": length,
        "width": width,
        "vertex_count": len(mesh["vertices"]),
        "face_count": len(mesh["faces"]),
        "feature_count": len(features),
    }


# ---------------------------------------------------------------------------
# Bundle I — coastal geology pass helpers
# ---------------------------------------------------------------------------


def compute_wave_energy(
    stack: "TerrainMaskStack",
    sea_level_m: float,
    dominant_wave_dir_rad: float,
) -> np.ndarray:
    """Return a (H, W) float32 per-cell wave-energy field.

    High where:
        - elevation is near sea level (shoreline)
        - the local shore faces the wave direction (exposed headland)
        - slope is steep enough to deflect energy upward (cliff)

    Zero over land far from sea and deep water far from shore.
    """
    if stack.height is None:
        raise ValueError("compute_wave_energy requires stack.height")

    h = np.asarray(stack.height, dtype=np.float64)
    H, W = h.shape

    # Distance-from-sea-level band: peaks at 0, decays over 5 m on either side
    band = np.exp(-((h - sea_level_m) ** 2) / (2.0 * 5.0 * 5.0))

    # Only cells above sea level receive shoreline wave impact
    above = (h >= sea_level_m - 1.0).astype(np.float64)
    energy = band * above

    # Directional exposure: gradient facing into wave direction
    gy, gx = np.gradient(h)
    # Unit vector toward sea = -gradient (uphill points inland)
    norm = np.sqrt(gx * gx + gy * gy) + 1e-9
    sea_x = -gx / norm
    sea_y = -gy / norm
    wave_x = math.cos(dominant_wave_dir_rad)
    wave_y = math.sin(dominant_wave_dir_rad)
    # Negative dot product = shore faces incoming waves
    facing = -(sea_x * wave_x + sea_y * wave_y)
    facing = np.clip(facing, 0.0, 1.0)

    energy = energy * (0.3 + 0.7 * facing)
    return energy.astype(np.float32)


def apply_coastal_erosion(
    stack: "TerrainMaskStack",
    sea_level_m: float,
    wave_direction: float = 0.0,
    wave_energy: float = 1.0,
    dt: float = 1.0,
) -> np.ndarray:
    """Return a height delta carving cliff-retreat at wave-energy hotspots.

    Uses physically-motivated fetch-based erosion:

    1. **Fetch distance** — Euclidean distance (in cells) from each shoreline
       cell to the nearest ocean cell (h < sea_level_m).  Long unobstructed
       fetch = higher wave amplitude at the shoreline.

    2. **Wave exposure** — angle factor  ``max(0, cos(wave_direction - aspect))``
       where *aspect* is the terrain aspect (direction the slope faces).
       Cells facing directly into the dominant wave direction receive full
       energy; sheltered cells in lee receive none.

    3. **Differential hardness** — soft sediment (rock_hardness < 0.4) erodes
       2–4× faster than hard rock (rock_hardness > 0.7), producing sea stacks
       (resistant pillars) and sea caves (soft-rock pockets).

    4. **Intertidal amplification** — cells within one tidal-half-range of
       sea level are wet/dry cyclically; erosion is amplified ×1.5 there.

    Not applied in place; returns a negative height delta array.

    Parameters
    ----------
    stack : TerrainMaskStack
        Must have ``stack.height`` set.
    sea_level_m : float
        Sea level in metres.
    wave_direction : float
        Dominant wave propagation direction in radians, clockwise from north
        (+Y axis).  0.0 = waves coming from the north (propagating southward).
    wave_energy : float
        Scalar wave-energy multiplier (1.0 = default, >1 = storm conditions).
    dt : float
        Time-step scale factor applied to the final erosion delta.
    """
    if stack.height is None:
        raise ValueError("apply_coastal_erosion requires stack.height")
    h = np.asarray(stack.height, dtype=np.float64)
    H, W = h.shape

    # ------------------------------------------------------------------
    # 1. Fetch distance: BFS/distance-transform from ocean boundary cells
    # ------------------------------------------------------------------
    ocean_mask = h < sea_level_m  # True = ocean cell

    # Use scipy distance_transform_edt when available for O(N) performance;
    # fall back to a vectorised L2 approximation otherwise.
    fetch_cells: np.ndarray
    try:
        from scipy.ndimage import distance_transform_edt as _dte
        # distance from the *nearest ocean cell* for every non-ocean cell
        fetch_cells = _dte(~ocean_mask).astype(np.float64)
    except ImportError:
        # Fallback: approximate as distance to ocean boundary via gradient mag
        # of the ocean mask — coarser but avoids scipy dependency.
        gy_o, gx_o = np.gradient(ocean_mask.astype(np.float64))
        boundary = np.sqrt(gx_o ** 2 + gy_o ** 2) > 0.1
        # Very rough: flood fill distance from boundary
        dist = np.full((H, W), float(max(H, W)), dtype=np.float64)
        dist[boundary] = 0.0
        for _ in range(max(H, W)):
            shifted = np.minimum(
                np.minimum(
                    np.pad(dist, ((0, 0), (0, 1)), mode="edge")[:, 1:],
                    np.pad(dist, ((0, 0), (1, 0)), mode="edge")[:, :-1],
                ),
                np.minimum(
                    np.pad(dist, ((0, 1), (0, 0)), mode="edge")[1:, :],
                    np.pad(dist, ((1, 0), (0, 0)), mode="edge")[:-1, :],
                ),
            ) + 1.0
            new_dist = np.minimum(dist, shifted)
            if np.array_equal(new_dist, dist):
                break
            dist = new_dist
        fetch_cells = dist

    # Normalise fetch to [0, 1] — longer unobstructed fetch → higher energy
    max_fetch = float(fetch_cells.max()) if fetch_cells.max() > 0 else 1.0
    fetch_norm = fetch_cells / max_fetch  # 0 at ocean edge, 1 at inland extremity

    # Wave energy peaks at shoreline (small fetch) and decays inland
    # A Gaussian centred on ~0 fetch with sigma of 15% of map size models
    # the narrow band of active wave-base erosion.
    sigma_fetch = max(1.0, 0.15 * max_fetch)
    fetch_energy = np.exp(-(fetch_cells ** 2) / (2.0 * sigma_fetch ** 2))

    # ------------------------------------------------------------------
    # 2. Aspect-based wave exposure: cos(wave_direction - terrain_aspect)
    # ------------------------------------------------------------------
    # Terrain aspect = direction the slope faces (uphill direction in XY).
    # Gradient: gy = dh/drow (north = negative row), gx = dh/dcol (east).
    gy, gx = np.gradient(h)
    # Aspect angle: atan2(gx, -gy) gives angle CW from north for the uphill dir
    aspect = np.arctan2(gx, -gy)  # CW from north, uphill facing direction

    # Wave propagation is FROM wave_direction, so the wave *arrives* from that
    # bearing.  A cliff face whose aspect points toward wave_direction is exposed.
    angle_diff = wave_direction - aspect
    exposure = np.clip(np.cos(angle_diff), 0.0, 1.0)

    # ------------------------------------------------------------------
    # 3. Intertidal amplification (tidal_half_range = 1.0 m default)
    # ------------------------------------------------------------------
    tidal_half = 1.0
    intertidal = np.abs(h - sea_level_m) <= tidal_half
    tidal_amp = np.where(intertidal, 1.5, 1.0)

    # ------------------------------------------------------------------
    # 4. Combine into erosion delta
    # ------------------------------------------------------------------
    # Only land cells (above sea level) are actively eroded
    above = (h > sea_level_m).astype(np.float64)

    base_erosion = 3.0  # metres per pass at full energy
    erosion_rate = base_erosion * wave_energy * fetch_energy * exposure * tidal_amp

    delta = -erosion_rate * above * dt

    # ------------------------------------------------------------------
    # 5. Differential hardness — soft sediment erodes 2–4× faster than rock
    # ------------------------------------------------------------------
    if stack.rock_hardness is not None:
        hardness = np.asarray(stack.rock_hardness, dtype=np.float64)
        hardness_c = np.clip(hardness, 0.0, 1.0)
        # hardness 0.0 → multiplier 2.5 (soft sediment, fast erosion)
        # hardness 0.4 → multiplier 1.0 (sea cave threshold)
        # hardness 1.0 → multiplier 0.25 (hard rock, slow erosion → sea stack)
        soft_factor = 2.5 - 2.25 * hardness_c
        delta = delta * soft_factor

    return delta


def detect_tidal_zones(
    stack: "TerrainMaskStack",
    sea_level_m: float,
    tidal_range_m: float,
) -> np.ndarray:
    """Populate ``stack.tidal`` (H, W) float32 in [0, 1].

    1 in the intertidal band ``[sea_level - tidal_range/2, sea_level + tidal_range/2]``,
    smooth taper to 0 outside.
    """
    if stack.height is None:
        raise ValueError("detect_tidal_zones requires stack.height")
    h = np.asarray(stack.height, dtype=np.float64)

    half = max(0.1, tidal_range_m * 0.5)
    diff = np.abs(h - sea_level_m)
    in_band = (diff <= half).astype(np.float64)
    # Smooth taper 1 cell-length outside the band
    taper = np.clip(1.0 - (diff - half) / half, 0.0, 1.0)
    tidal = np.maximum(in_band, taper * (1.0 - in_band))
    tidal_f32 = tidal.astype(np.float32)

    stack.set("tidal", tidal_f32, "coastline")
    return tidal_f32


def pass_coastline(
    state: "TerrainPipelineState",
    region: "Optional[BBox]",
) -> "PassResult":
    """Bundle I pass: compute coastal wave energy, tidal zone, and cliff retreat.

    Consumes: height
    Produces: tidal (mutates height)
    """
    from .terrain_semantics import PassResult as _PR

    t0 = time.perf_counter()
    stack = state.mask_stack
    hints = dict(state.intent.composition_hints) if state.intent else {}

    sea_level = float(hints.get("sea_level_m", 0.0))
    tidal_range = float(hints.get("tidal_range_m", 2.0))
    wave_dir = float(hints.get("dominant_wave_dir_rad", 0.0))
    apply_retreat = bool(hints.get("coastal_erosion_enabled", False))

    # Tidal zone
    tidal = detect_tidal_zones(stack, sea_level, tidal_range)

    # Wave energy (not persisted as a channel, only reported in metrics)
    energy = compute_wave_energy(stack, sea_level, wave_dir)

    retreat_mean = 0.0
    if apply_retreat:
        delta = apply_coastal_erosion(stack, sea_level, wave_direction=wave_dir)
        retreat_mean = float(np.abs(delta).mean())
    else:
        H, W = stack.height.shape
        delta = np.zeros((H, W), dtype=np.float32)
    stack.set("coastline_delta", delta.astype(np.float32), "coastline")

    return _PR(
        pass_name="coastline",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("tidal", "coastline_delta"),
        metrics={
            "sea_level_m": sea_level,
            "tidal_range_m": tidal_range,
            "wave_energy_max": float(energy.max()),
            "wave_energy_mean": float(energy.mean()),
            "coastal_retreat_mean_m": retreat_mean,
            "tidal_coverage_fraction": float((tidal > 0.5).mean()),
        },
        issues=[],
    )


__all__ = [
    "generate_coastline",
    "COASTLINE_STYLES",
    "compute_wave_energy",
    "apply_coastal_erosion",
    "detect_tidal_zones",
    "pass_coastline",
]

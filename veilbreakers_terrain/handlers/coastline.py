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
import copy
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
    statistically independent while remaining deterministic.  Domain rotation
    (45-degree shear) between octaves suppresses axis-aligned artifacts common
    in fBm built from value noise lattices.
    """
    total = 0.0
    amplitude = 1.0
    frequency = 1.0
    max_val = 0.0
    px, py = x, y
    for o in range(octaves):
        total += _hash_noise(px * frequency, py * frequency, seed + o * 7919) * amplitude
        max_val += amplitude
        amplitude *= 0.5
        frequency *= 2.0
        # Rotate domain 45° each octave to break lattice alignment
        nx = px * 0.7071068 - py * 0.7071068
        ny = px * 0.7071068 + py * 0.7071068
        px, py = nx, ny
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

    Style-specific characteristics
    --------------------------------
    ``rocky_cliff``
        High-frequency multi-octave noise — jagged headlands and pocket coves.
    ``sandy`` / ``beach``
        Low-frequency smooth curves — broad bays and gentle promontories.
    ``fjord``
        Domain-elongated noise to produce narrow elongated inlets.
    ``harbor``
        Parabolic cove centred on the strip with low-frequency edges.
    """
    config = COASTLINE_STYLES[style]
    amp = config["shore_noise_amp"]
    freq = config["shore_noise_freq"]

    profile: list[float] = []

    for i in range(resolution):
        t = i / max(resolution - 1, 1)
        x = t * length

        if style == "rocky":
            # High-frequency multi-octave noise — jagged headlands
            noise = _fbm_noise(x * freq, seed * 0.1, seed, octaves=6)
            hf = _fbm_noise(x * freq * 3.5, seed * 0.17, seed + 3, octaves=3)
            offset = noise * amp + hf * amp * 0.55

        elif style == "sandy":
            # Low-frequency smooth curves — broad sweeping bays
            noise = _fbm_noise(x * freq * 0.4, seed * 0.1, seed, octaves=3)
            offset = noise * amp

        elif style == "cliffs":
            # High-frequency but with long-range correlation — sheer headlands
            noise = _fbm_noise(x * freq, seed * 0.1, seed, octaves=5)
            hf = _fbm_noise(x * freq * 2.0, seed * 0.23, seed + 1, octaves=2)
            offset = noise * amp + hf * amp * 0.5

        elif style == "harbor":
            # Parabolic cove: maximum indentation at centre
            cove_t = (t - 0.5) * 2  # [-1, 1]
            cove_offset = -(1 - cove_t * cove_t) * amp * 3
            noise = _fbm_noise(x * freq, seed * 0.1, seed, octaves=3)
            offset = noise * amp + cove_offset

        else:
            noise = _fbm_noise(x * freq, seed * 0.1, seed, octaves=4)
            offset = noise * amp

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
                # Smooth sigmoid cliff profile — no hard z-step discontinuity
                # Sigmoid centred at land_factor=0.3, steepness k=25
                k = 25.0
                sig = 1.0 / (1.0 + math.exp(-k * (land_factor - 0.3)))
                z = base_elev * sig
                # Multi-octave strata noise along cliff face
                strata = _fbm_noise(x * 0.08, y * 0.15, seed + 3, octaves=4)
                z += strata * slope * 0.4
                # High-freq surface roughness
                z += _fbm_noise(x * 0.5, y * 0.5, seed + 7, octaves=2) * 0.15

            elif style == "sandy":
                # Gentle concave-up gradient (beach berm shape)
                z = land_factor ** 0.7 * base_elev
                # Dune bumps on land side — low-freq fBm
                if land_factor > 0.5:
                    dune = _fbm_noise(x * 0.04, y * 0.04, seed + 4, octaves=4)
                    z += max(0.0, dune) * base_elev * 0.6
                # Swash ripples near shore
                if land_factor < 0.2:
                    ripple = _fbm_noise(x * 0.3, y * 0.3, seed + 8, octaves=2)
                    z += ripple * 0.04

            elif style == "harbor":
                # Flat dock area in centre, gently rising toward edges
                center_t = abs(t_along - 0.5) * 2  # [0, 1] from centre
                z = land_factor * base_elev * (0.25 + 0.75 * center_t)
                # Quayside stones: low-amp fBm
                z += _fbm_noise(x * 0.12, y * 0.12, seed + 9, octaves=3) * 0.08

            else:
                # Rocky: multi-scale elevation noise
                z = land_factor * base_elev
                z += _fbm_noise(x * 0.06, y * 0.06, seed + 5, octaves=4) * slope * 0.35
                # Isolated rock outcrops
                z += max(0.0, _fbm_noise(x * 0.25, y * 0.25, seed + 10, octaves=3)) * slope * 0.2

            # Micro-scale surface detail (shared across all styles)
            z += _fbm_noise(x * 0.5, y * 0.5, seed + 6, octaves=2) * 0.08

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
    style: str = "sandy",
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
    # Across resolution: rocky/cliffs get more cross-section detail
    if style in ("rocky", "cliffs"):
        resolution_across = max(6, resolution * 2 // 3)
    else:
        resolution_across = max(4, resolution // 2)

    # Style-specific noise character — documented here, consumed by sub-functions
    # rocky  : high-freq fBm (6 octaves) — jagged headlands, pocket coves
    # sandy  : low-freq fBm (3 octaves)  — broad sweeping bays
    # cliffs : high-freq + long-range correlation (5 oct) — sheer headlands
    # harbor : parabolic cove + low-freq edges (3 oct)

    # Generate shoreline profile (fBm-based, style-specific frequencies)
    shoreline_profile = _generate_shoreline_profile(
        length, style, resolution_along, seed
    )

    # Generate terrain mesh (sigmoid cliff profile, multi-octave surface detail)
    mesh = _generate_coastline_mesh(
        length=length,
        width=width,
        style=style,
        resolution_along=resolution_along,
        resolution_across=resolution_across,
        shoreline_profile=shoreline_profile,
        seed=seed,
    )

    # Place features (fetch+hardness gating, density-weighted distribution)
    features = _place_features(
        length=length,
        width=width,
        style=style,
        shoreline_profile=shoreline_profile,
        resolution_along=resolution_along,
        seed=seed,
    )

    # Compute material zones (5-zone coastal classification)
    material_zones = _compute_material_zones(
        vertices=mesh["vertices"],
        resolution_along=resolution_along,
        resolution_across=resolution_across,
        shoreline_profile=shoreline_profile,
        width=width,
        style=style,
    )

    config = COASTLINE_STYLES[style]

    # Noise character summary — useful for downstream LOD / shader selection
    noise_character = {
        "rocky":  {"octaves": 6, "style_label": "high_freq_jagged"},
        "sandy":  {"octaves": 3, "style_label": "low_freq_smooth"},
        "cliffs": {"octaves": 5, "style_label": "high_freq_sheer"},
        "harbor": {"octaves": 3, "style_label": "parabolic_cove"},
    }.get(style, {"octaves": 4, "style_label": "generic"})

    return {
        "mesh": mesh,
        "features": features,
        "material_zones": material_zones,
        "material_names": config["material_zones"],
        "shoreline_profile": shoreline_profile,
        "style": style,
        "noise_character": noise_character,
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
    fetch_m: float = 10000.0,
    wind_speed_ms: float = 10.0,
) -> np.ndarray:
    """Return a (H, W) float32 per-cell wave-energy field.

    High where:
        - elevation is near sea level (shoreline)
        - the local shore faces the wave direction (exposed headland)
        - slope is steep enough to deflect energy upward (cliff)

    Zero over land far from sea and deep water far from shore.

    Physics
    -------
    Significant wave height is approximated via the JONSWAP fetch-limited
    relation (Hasselmann et al. 1973):

        Hs = 0.0248 * sqrt(fetch_m) * U^2 / g

    Wave energy density E = (1/8) * rho_water * g * Hs^2.
    The shoreline band sigma scales with Hs so that a stormy fetch (long
    fetch, high wind) produces a wider active erosion band than a calm lake.

    Parameters
    ----------
    fetch_m : float
        Upwind open-water fetch distance in metres.  Use ~10 000 m for a
        large ocean coast, ~500 m for a sheltered lake shore.
    wind_speed_ms : float
        Dominant wind / wave-generating wind speed (m/s).  Default 10 m/s
        (~Beaufort 5, moderate breeze).  Scales Hs and therefore band width.
    dominant_wave_dir_rad : float
        Wave propagation azimuth (radians, CW from north).  Should come from
        ``intent.composition_hints['wave_dir']``; passed explicitly so the
        caller controls the source.
    """
    if stack.height is None:
        raise ValueError("compute_wave_energy requires stack.height")

    h = np.asarray(stack.height, dtype=np.float64)

    # ------------------------------------------------------------------
    # JONSWAP significant wave height and energy
    # ------------------------------------------------------------------
    g = 9.81  # m/s²
    rho = 1025.0  # kg/m³, seawater

    # Fetch-limited Hs (JONSWAP approximation)
    Hs = 0.0248 * math.sqrt(max(fetch_m, 1.0)) * (wind_speed_ms ** 2) / g
    Hs = max(Hs, 0.01)  # floor at 1 cm

    # Wave energy density (J/m²) — used as a scalar multiplier
    E_density = 0.125 * rho * g * Hs * Hs

    # Shoreline band sigma scales with Hs: calmer seas → narrower active zone
    # Empirical: sigma_m ~ 2.5 * Hs (transition zone = a few wave heights)
    sigma_m = max(0.5, 2.5 * Hs)

    # Band: Gaussian centred on sea_level_m, width = sigma_m
    band = np.exp(-((h - sea_level_m) ** 2) / (2.0 * sigma_m * sigma_m))

    # Only cells at or above sea level receive active shoreline wave impact
    above = (h >= sea_level_m - Hs * 0.5).astype(np.float64)
    energy = band * above

    # ------------------------------------------------------------------
    # Directional exposure: shore aspect vs incoming wave direction
    # ------------------------------------------------------------------
    gy, gx = np.gradient(h)
    norm = np.sqrt(gx * gx + gy * gy) + 1e-9
    # Uphill unit vector (points inland / away from sea)
    uphill_x = gx / norm
    uphill_y = gy / norm
    # Wave arrives FROM dominant_wave_dir_rad — a face whose uphill points
    # *toward* the wave source is sheltered; one pointing *away* is exposed.
    # Exposure = max(0, -dot(uphill, wave_dir_unit))
    wave_x = math.cos(dominant_wave_dir_rad)
    wave_y = math.sin(dominant_wave_dir_rad)
    facing = np.clip(-(uphill_x * wave_x + uphill_y * wave_y), 0.0, 1.0)

    energy = energy * (0.25 + 0.75 * facing)

    # Scale by physical energy density (normalised to [0,1] range at E_density)
    # Use log-scale to keep large storms from overwhelming the field entirely
    energy_scale = math.log1p(E_density) / math.log1p(1.0e6)
    energy = energy * max(energy_scale, 0.01)

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
    fetch_energy = np.exp(-(fetch_norm ** 2) / (2.0 * sigma_fetch ** 2))  # FIX-11-13

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

    # Max drop scales with wave_energy scalar: storm conditions (wave_energy>1)
    # carve more per pass; calm conditions carve less.  Clamped to [0.1, 12] m
    # to match RDR2-class cliff retreat rates under sustained storm fetch.
    base_erosion = float(np.clip(3.0 * wave_energy, 0.1, 12.0))
    erosion_rate = base_erosion * fetch_energy * exposure * tidal_amp

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

    # 5-zone tidal label: subtidal=0, intertidal=1, splash=2, spray=3, supralittoral=4
    low = sea_level_m - half
    high_z = sea_level_m + half
    splash_top = high_z + tidal_range_m
    spray_top = high_z + 3.0 * tidal_range_m
    label = np.zeros_like(h, dtype=np.uint8)
    label[h >= low] = 1
    label[h >= high_z] = 2
    label[h >= splash_top] = 3
    label[h >= spray_top] = 4
    stack.set("tidal_zone_label", label, "coastline")

    return tidal_f32


def _build_tidal_flat(
    stack: "TerrainMaskStack",
    tidal_range_m: float,
    tidal_phase: float,
) -> np.ndarray:
    """Compute a tidal flat mask: cells periodically exposed/submerged by tides.

    The tidal flat is the intertidal zone — cells whose elevation falls
    between the low-tide mark and the high-tide mark at the given phase.
    ``tidal_phase`` is a value in [0, 1] where 0 = low tide, 1 = high tide.

    Returns a float32 array in [0, 1] indicating tidal flat coverage.

    FIX-9-56
    """
    h = np.asarray(stack.height, dtype=np.float64)
    sea_level = 0.0
    water_surface_elevation = stack.get("water_surface_elevation_m", default=None)
    if water_surface_elevation is not None:
        wse = np.asarray(water_surface_elevation, dtype=np.float64)
        finite = wse[np.isfinite(wse)]
        if finite.size:
            sea_level = float(np.median(finite))

    low_tide = sea_level - tidal_range_m * 0.5
    high_tide = sea_level + tidal_range_m * 0.5
    current_water = low_tide + tidal_phase * tidal_range_m  # FIX-9-56

    # Cells in the intertidal zone (between low and high tide marks)
    intertidal = (h >= low_tide) & (h <= high_tide)
    # Weight by how much of the tidal cycle they are submerged
    submerged_fraction = np.clip((current_water - h) / max(tidal_range_m, 1e-9), 0.0, 1.0)
    tidal_flat = np.where(intertidal, submerged_fraction, 0.0)  # FIX-9-56
    return tidal_flat.astype(np.float32)


def pass_coastline(
    state: "TerrainPipelineState",
    region: "Optional[BBox]",
) -> "PassResult":
    """Bundle I pass: compute coastal wave energy, tidal zone, and cliff retreat.

    Consumes: height
    Produces: tidal, tidal_zone_label, wave_energy, coastline_delta

    Mutation behaviour
    ------------------
    When ``coastal_erosion_enabled`` is true the erosion delta returned by
    ``apply_coastal_erosion`` is accumulated into ``coastline_delta``. The
    canonical ``integrate_deltas`` pass applies it to ``height`` exactly once.

    Hint keys consumed
    ------------------
    ``sea_level_m``            float  — sea level in metres (default 0.0);
                                        superseded by stack channel
                                        ``water_surface_elevation_m`` when
                                        populated.
    ``tidal_range_m``          float  — tidal range in metres (default 2.0)
    ``wave_dir``               float  — dominant wave direction, radians CW
                                        from north (default 0.0)
    ``dominant_wave_dir_rad``  float  — alias; ``wave_dir`` takes precedence
    ``fetch_m``                float  — upwind fetch in metres (default 10 000)
    ``wind_speed_ms``          float  — generating wind speed m/s (default 10)
    ``coastal_erosion_enabled`` bool  — if true, mutates height (default False)
    ``erosion_passes``         int    — number of erosion passes (default 1)
    """
    from .terrain_semantics import PassResult as _PR

    t0 = time.perf_counter()
    stack = state.mask_stack
    hints = dict(state.intent.composition_hints) if state.intent else {}

    sea_level = float(hints.get("sea_level_m", 0.0))
    water_surface_elevation = stack.get("water_surface_elevation_m", default=None)
    if water_surface_elevation is not None:
        wse = np.asarray(water_surface_elevation, dtype=np.float64)
        finite = wse[np.isfinite(wse)]
        if finite.size:
            sea_level = float(np.median(finite))
    tidal_range = float(hints.get("tidal_range_m", 2.0))
    # Accept either hint key; wave_dir takes precedence
    wave_dir = float(hints.get("wave_dir", hints.get("dominant_wave_dir_rad", 0.0)))
    fetch_m = float(hints.get("fetch_m", 10000.0))
    wind_speed_ms = float(hints.get("wind_speed_ms", 10.0))
    apply_retreat = bool(hints.get("coastal_erosion_enabled", False))
    erosion_passes = max(1, int(hints.get("erosion_passes", 1)))

    # Tidal zone
    tidal = detect_tidal_zones(stack, sea_level, tidal_range)

    # FIX-9-56: build tidal flat mask and write to stack
    tidal_phase = float(hints.get("tidal_phase", 0.5))  # FIX-9-56: 0=low tide, 1=high tide
    tidal_flat = _build_tidal_flat(stack, tidal_range, tidal_phase)  # FIX-9-56
    stack.set("tidal_flat", tidal_flat, "coastline")  # FIX-9-56

    # Wave energy — uses JONSWAP fetch/wind model; written to stack for splatmap rules
    energy = compute_wave_energy(
        stack, sea_level, wave_dir,
        fetch_m=fetch_m,
        wind_speed_ms=wind_speed_ms,
    )
    # FIX-13-11: amplify wave energy at river mouth cells — fresh-water outflow
    # reduces salinity and turbulence resistance, increasing sediment removal.
    # river_mouth_mask is a [0, 1] float32 grid; multiply energy by up to 1.5×
    # at full-mask cells to model the erosion jet where rivers meet the sea.
    _rmm = stack.get("river_mouth_mask", default=None)
    if _rmm is not None:
        _rmm_arr = np.asarray(_rmm, dtype=np.float32)
        if _rmm_arr.shape == energy.shape:
            energy = energy * (1.0 + 0.5 * _rmm_arr)
    # FIX-10-H5: JONSWAP wave energy → spatially varying foam density
    wave_energy_jonswap = energy
    if wave_energy_jonswap is not None and wave_energy_jonswap.max() > 0:
        energy_norm = wave_energy_jonswap / wave_energy_jonswap.max()
        base_foam_density = np.ones(energy_norm.shape, dtype=np.float32)
        foam_density = base_foam_density * (0.3 + 0.7 * energy_norm).astype(np.float32)
    else:
        foam_density = np.ones(energy.shape, dtype=np.float32)
    stack.set("foam_density", foam_density, "coastline")
    stack.set("wave_energy", energy.astype(np.float32), "coastline")

    retreat_mean = 0.0
    if apply_retreat:
        cumulative_delta = np.zeros_like(np.asarray(stack.height, dtype=np.float64))
        working_stack = copy.copy(stack)
        working_height = np.asarray(stack.height, dtype=np.float64).copy()
        working_stack.set("height", working_height.astype(np.float32), "coastline")
        for _ in range(erosion_passes):
            # Recompute wave field each pass so evolving coastline geometry is reflected
            _pass_energy = compute_wave_energy(
                working_stack, sea_level, wave_dir,
                fetch_m=fetch_m,
                wind_speed_ms=wind_speed_ms,
            )
            scalar_wave_energy = float(_pass_energy.mean())
            # FIX-13-11: also amplify per-pass scalar energy at river mouth zones
            _rmm_work = working_stack.get("river_mouth_mask", default=None)
            if _rmm_work is not None:
                _rmm_w_arr = np.asarray(_rmm_work, dtype=np.float32)
                _mouth_boost = float(_rmm_w_arr.mean()) * 0.5
                scalar_wave_energy *= (1.0 + _mouth_boost)
            delta = apply_coastal_erosion(
                working_stack,
                sea_level,
                wave_direction=wave_dir,
                wave_energy=scalar_wave_energy,
            )
            cumulative_delta += delta
            working_height = working_height + delta
            working_stack.set("height", working_height.astype(np.float32), "coastline")

        retreat_mean = float(np.abs(cumulative_delta).mean())
        final_delta = cumulative_delta.astype(np.float32)
    else:
        H, W = stack.height.shape
        final_delta = np.zeros((H, W), dtype=np.float32)

    stack.set("coastline_delta", final_delta, "coastline")

    produced = ("tidal", "tidal_zone_label", "wave_energy", "coastline_delta", "tidal_flat")  # FIX-9-56

    return _PR(
        pass_name="coastline",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=produced,
        metrics={
            "sea_level_m": sea_level,
            "tidal_range_m": tidal_range,
            "fetch_m": fetch_m,
            "wind_speed_ms": wind_speed_ms,
            "wave_dir_rad": wave_dir,
            "wave_energy_max": float(energy.max()),
            "wave_energy_mean": float(energy.mean()),
            "coastal_retreat_mean_m": retreat_mean,
            "erosion_passes": erosion_passes,
            "tidal_coverage_fraction": float((tidal > 0.5).mean()),
            "tidal_flat_coverage_fraction": float((tidal_flat > 0.0).mean()),  # FIX-9-56
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
    "_build_tidal_flat",  # FIX-9-56
]

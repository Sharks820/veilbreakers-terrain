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

from ._terrain_noise import _make_noise_generator

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
# Noise utility (gradient noise via project's permutation-table backend)
# ---------------------------------------------------------------------------

# Module-level generator cache keyed by seed to avoid rebuilding permutation
# tables on every call.
_noise_gen_cache: dict[int, Any] = {}


def _get_noise_gen(seed: int) -> Any:
    """Return a cached noise generator for *seed*."""
    if seed not in _noise_gen_cache:
        _noise_gen_cache[seed] = _make_noise_generator(seed)
    return _noise_gen_cache[seed]


def _hash_noise(x: float, y: float, seed: int) -> float:
    """Deterministic gradient noise in [-1, 1].

    Replaces the old sin-hash (which produced visually repetitive banding)
    with proper 2-D gradient noise from the project's permutation-table
    backend (_terrain_noise._make_noise_generator).  Output range is
    approximately [-1, 1], same contract as the old implementation.
    """
    gen = _get_noise_gen(seed)
    xs = np.array([x], dtype=np.float64)
    ys = np.array([y], dtype=np.float64)
    return float(gen.noise2_array(xs, ys)[0])


def _fbm_noise(x: float, y: float, seed: int, octaves: int = 4) -> float:
    """Fractal Brownian motion noise via gradient noise."""
    total = 0.0
    amplitude = 1.0
    frequency = 1.0
    max_val = 0.0
    # Use a single generator per seed; vary frequency spatially instead of
    # mixing in a per-octave seed offset (avoids re-allocating perm tables).
    gen = _get_noise_gen(seed)
    for _ in range(octaves):
        xs = np.array([x * frequency], dtype=np.float64)
        ys = np.array([y * frequency], dtype=np.float64)
        total += float(gen.noise2_array(xs, ys)[0]) * amplitude
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
) -> list[dict[str, Any]]:
    """Place coastline features (sea stacks, tide pools, docks, etc.).

    Parameters
    ----------
    existing_candidates : list of dicts, optional
        Pre-existing terrain features (e.g. ``cave_candidate``,
        ``cliff_candidate``) that new features must not overlap.  Each dict
        must have a ``"position"`` key with an (x, y[, z]) tuple.
    min_separation : float
        Minimum 2-D distance (metres) between any two placed features and
        between a new feature and any existing candidate.  Default 4.0 m.
    """
    config = COASTLINE_STYLES[style]
    feature_types = config["features"]
    rng = random.Random(seed + 100)

    features: list[dict[str, Any]] = []
    half_width = width / 2.0

    # Seed the occupied list from pre-existing candidates so new features
    # respect cave/cliff positions already baked into the terrain.
    occupied: list[tuple[float, float]] = []
    if existing_candidates:
        for cand in existing_candidates:
            pos = cand.get("position")
            if pos and len(pos) >= 2:
                occupied.append((float(pos[0]), float(pos[1])))

    def _try_place(x: float, y: float) -> bool:
        """Return True and register position if no overlap, else False."""
        for occ in occupied:
            if _features_overlap((x, y), occ, min_separation):
                return False
        occupied.append((x, y))
        return True

    # Number of features scales with coastline length
    num_features = max(3, int(length / 20.0))
    # Allow extra candidates so rejections don't starve the feature count
    max_attempts = num_features * 4

    attempt = 0
    while len(features) < num_features and attempt < max_attempts:
        attempt += 1
        ftype = rng.choice(feature_types)
        t = rng.random()
        x = t * length
        idx = min(int(t * resolution_along), len(shoreline_profile) - 1)
        shore_offset = shoreline_profile[idx]

        if ftype in ("sea_stack", "rock_pillar"):
            y = shore_offset - rng.uniform(2, half_width * 0.5)
            if not _try_place(x, y):
                continue
            z = rng.uniform(1, 4)
            features.append({
                "type": ftype,
                "position": (x, y, 0.0),
                "height": z,
                "radius": rng.uniform(0.5, 2.0),
            })
        elif ftype in ("tide_pool",):
            y = shore_offset + rng.uniform(-1, 1)
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
    """Assign material zone index to each face.

    Zone boundaries are derived from actual vertex elevation relative to
    ``sea_level_m`` and ``tidal_range_m``, not from fixed lateral offsets.
    If ``tidal_mask`` (from ``stack.tidal``) is provided it refines the
    intertidal band assignment.

    Parameters
    ----------
    rocky_coast_threshold : float
        Slope magnitude above which a face is classified as rocky rather than
        sandy within the intertidal zone.  Computed from vertex Z deltas.
        Range [0, 1]; default 0.4.
    """
    config = COASTLINE_STYLES[style]
    zones = config["material_zones"]
    num_zones = len(zones)

    # Tidal band limits in elevation
    tidal_half = max(0.1, tidal_range_m * 0.5)
    sub_tidal_top = sea_level_m - tidal_half       # below this = sub-tidal / water
    tidal_top = sea_level_m + tidal_half            # above this = splash / land
    # splash zone extends a further half tidal range above the intertidal band
    splash_top = tidal_top + tidal_half

    face_materials: list[int] = []

    for i in range(resolution_along - 1):
        for j in range(resolution_across - 1):
            v0 = i * resolution_across + j
            v1 = v0 + 1
            v2 = (i + 1) * resolution_across + j + 1
            v3 = (i + 1) * resolution_across + j

            z_vals = [vertices[k][2] for k in (v0, v1, v2, v3)]
            z_avg = sum(z_vals) / 4.0

            # Local slope from Z range across the face quad (crude but fast)
            z_range = max(z_vals) - min(z_vals)
            is_rocky = z_range >= rocky_coast_threshold

            # Zone assignment based on elevation bands
            if z_avg < sub_tidal_top:
                # Sub-tidal / water edge
                mat_idx = num_zones - 1
            elif z_avg < tidal_top:
                # Intertidal band — wet rock vs wet sand
                if is_rocky and num_zones >= 3:
                    # rocky styles: prefer wet_rock (index 1) over water_edge
                    mat_idx = min(1, num_zones - 2)
                else:
                    mat_idx = max(0, num_zones - 2)
            elif z_avg < splash_top:
                # Splash zone — mid ground material
                mat_idx = min(1, num_zones - 1)
            else:
                # Inland / dry land
                mat_idx = 0

            face_materials.append(mat_idx)

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

    Not applied in place.

    Parameters
    ----------
    stack : TerrainMaskStack
        Must have ``stack.height`` set.
    sea_level_m : float
        Sea level in metres.
    wave_direction : float
        Dominant wave direction in radians, clockwise from north (+Y axis).
        0.0 = waves coming from the north.
    wave_energy : float
        Scalar wave-energy multiplier (1.0 = default, >1 = storm conditions).
    dt : float
        Time-step scale factor applied to the final erosion delta.
    """
    if stack.height is None:
        raise ValueError("apply_coastal_erosion requires stack.height")
    h = np.asarray(stack.height, dtype=np.float64)

    energy = compute_wave_energy(stack, sea_level_m, wave_direction).astype(
        np.float64
    )

    # Only erode cells above sea level
    above = (h > sea_level_m).astype(np.float64)

    # Directional exposure: coastal outward normal vs. wave propagation vector.
    # wave_direction is clockwise from north (+Y), so:
    #   wave_vec[0] = sin(wave_direction)  (east component)
    #   wave_vec[1] = cos(wave_direction)  (north component)
    wave_vec = np.array([np.sin(wave_direction), np.cos(wave_direction)])

    # Heightmap gradient: gy = north gradient, gx = east gradient
    gy, gx = np.gradient(h)
    grad_norm = np.sqrt(gx * gx + gy * gy) + 1e-9
    # Outward coastal normal points seaward (downhill = toward water)
    normal_x = -gx / grad_norm
    normal_y = -gy / grad_norm

    # local_exposure: how directly the shore faces the incoming waves.
    # dot(outward_normal, wave_vec) > 0 means the shore opens toward the waves.
    local_exposure = np.clip(
        normal_x * wave_vec[0] + normal_y * wave_vec[1],
        0.0,
        1.0,
    )

    # Base erosion rate scaled by wave_energy and local exposure
    base_erosion = 3.0  # metres per pass at full energy
    erosion_rate = base_erosion * wave_energy * local_exposure

    delta = -energy * above * erosion_rate * dt

    # Softer rock erodes more
    if stack.rock_hardness is not None:
        hardness = np.asarray(stack.rock_hardness, dtype=np.float64)
        delta = delta * (1.0 - 0.7 * np.clip(hardness, 0.0, 1.0))

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
        delta = apply_coastal_erosion(stack, sea_level)
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

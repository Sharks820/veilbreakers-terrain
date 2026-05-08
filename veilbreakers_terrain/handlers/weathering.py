"""Weathering and structural-settling utilities for assembled meshes.

Provides:
  - WEATHERING_PRESETS: named preset configurations
  - _compute_bounding_box(): axis-aligned bounding box dict
  - compute_weathered_vertex_colors(): physically-based weathering progression
    (fresh → stained → patinated → crumbling → moss-covered)
  - apply_structural_settling(): subsidence and tilt from soil compaction
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Tuple
from .terrain_pipeline import derive_pass_seed

# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

WEATHERING_PRESETS: Dict[str, Dict] = {
    "light": {
        "dirt_accumulation": 0.05,
        "edge_wear": 0.10,
        "surface_roughness": 0.08,
        "color_shift": 0.03,
        "moss_coverage": 0.02,
        # Weathering age factor: 0 = very fresh, 1 = ancient
        # Light preset = recently placed / maintained structure
        "age_factor": 0.15,
    },
    "medium": {
        "dirt_accumulation": 0.20,
        "edge_wear": 0.35,
        "surface_roughness": 0.25,
        "color_shift": 0.12,
        "moss_coverage": 0.10,
        "age_factor": 0.45,
    },
    "heavy": {
        "dirt_accumulation": 0.55,
        "edge_wear": 0.75,
        "surface_roughness": 0.60,
        "color_shift": 0.30,
        "moss_coverage": 0.35,
        "age_factor": 0.85,
    },
}

# ---------------------------------------------------------------------------
# Weathering stage definitions
# ---------------------------------------------------------------------------

# Five-stage linear progression model.
# Each stage occupies a fraction of the [0, 1] age axis.
# At each stage boundary, the RGBA vertex color shifts toward the stage color.
#
# Stage 0: fresh      — clean material color, no alteration
# Stage 1: stained    — water marks, iron bleed, tannin streaks (orange-brown tint)
# Stage 2: patinated  — oxidation crust, calcium carbonate bloom (grey-green tint)
# Stage 3: crumbling  — surface spalling, exposed aggregate (warm grey, rough)
# Stage 4: moss-covered — biological colonisation dominates (deep green-black)
#
# Colors are RGBA multipliers blended into the base_color using stage weight.
# A value of (1, 1, 1, 1) = no change; lower values darken/tint the channel.
_WEATHERING_STAGES: List[Dict] = [
    {
        "name": "fresh",
        "age_start": 0.00,
        "age_end": 0.15,
        # Multiplier applied to base_color channels
        "color_mul": (1.00, 1.00, 1.00, 1.00),
        # Additive RGB tint (added on top of multiplied base)
        "color_add": (0.00, 0.00, 0.00),
        "roughness_boost": 0.0,
    },
    {
        "name": "stained",
        "age_start": 0.10,
        "age_end": 0.40,
        # Water staining darkens, adds orange-brown iron oxide tint
        "color_mul": (0.85, 0.78, 0.70, 1.00),
        "color_add": (0.06, 0.03, 0.00),
        "roughness_boost": 0.05,
    },
    {
        "name": "patinated",
        "age_start": 0.30,
        "age_end": 0.60,
        # Oxidation crust: grey-green, slight blue-green on metal, chalky whites
        "color_mul": (0.72, 0.76, 0.68, 1.00),
        "color_add": (0.04, 0.06, 0.03),
        "roughness_boost": 0.15,
    },
    {
        "name": "crumbling",
        "age_start": 0.55,
        "age_end": 0.80,
        # Spalling and aggregate exposure: warm grey, darker overall
        "color_mul": (0.60, 0.58, 0.55, 1.00),
        "color_add": (0.02, 0.02, 0.02),
        "roughness_boost": 0.35,
    },
    {
        "name": "moss_covered",
        "age_start": 0.72,
        "age_end": 1.00,
        # Biological colonisation: deep green-black, very dark
        "color_mul": (0.35, 0.42, 0.28, 1.00),
        "color_add": (0.01, 0.04, 0.01),
        "roughness_boost": 0.55,
    },
]


def _stage_weight(age: float, stage_start: float, stage_end: float) -> float:
    """Smooth tent weight for a weathering stage at a given age value.

    Returns 1.0 at the midpoint of [stage_start, stage_end], fading to 0.0
    at the endpoints.  Uses a raised-cosine (Hann) shape so transitions
    between stages are C1-smooth with no discontinuous jumps.

    Args:
        age: Per-vertex age value in [0, 1].
        stage_start: Age at which this stage begins to activate.
        stage_end: Age at which this stage finishes activating.

    Returns:
        Weight in [0, 1].
    """
    if stage_end <= stage_start:
        return 0.0
    t = (age - stage_start) / (stage_end - stage_start)
    t = max(0.0, min(1.0, t))
    # Raised cosine: smooth fade in [0,1] → weight peak at t=0.5
    return 0.5 - 0.5 * math.cos(math.pi * t * 2.0) if t <= 0.5 else 0.5 + 0.5 * math.cos(math.pi * (t - 0.5) * 2.0)


# ---------------------------------------------------------------------------
# Bounding box
# ---------------------------------------------------------------------------


def _compute_bounding_box(
    verts: List[Tuple[float, float, float]],
) -> Dict[str, float]:
    """Return axis-aligned bounding box of *verts*.

    Returns a dict with keys: min_x, max_x, min_y, max_y, min_z, max_z.
    """
    if not verts:
        return {
            "min_x": 0.0, "max_x": 0.0,
            "min_y": 0.0, "max_y": 0.0,
            "min_z": 0.0, "max_z": 0.0,
        }
    xs = [float(v[0]) for v in verts]
    ys = [float(v[1]) for v in verts]
    zs = [float(v[2]) for v in verts]
    return {
        "min_x": min(xs), "max_x": max(xs),
        "min_y": min(ys), "max_y": max(ys),
        "min_z": min(zs), "max_z": max(zs),
    }


# ---------------------------------------------------------------------------
# Vertex color weathering helpers
# ---------------------------------------------------------------------------


def _compute_edge_convexity(
    mesh_data: dict,
) -> List[float]:
    """Compute per-vertex convexity score in [-1, 1] from normals and geometry.

    Positive → convex (exposed corner), negative → concave (crevice).
    Result is cached via the _cached_convexity parameter in the public API.
    """
    vertices = mesh_data["vertices"]
    edges = mesh_data["edges"]
    vertex_normals = mesh_data["vertex_normals"]
    n = len(vertices)
    convexity = [0.0] * n

    for edge in edges:
        a, b = edge[0], edge[1]
        na = vertex_normals[a]
        nb_v = vertex_normals[b]
        # curvature = 1 - dot(na, nb): 0 for flat, +2 for opposing normals.
        curvature = 1.0 - (
            float(na[0]) * float(nb_v[0])
            + float(na[1]) * float(nb_v[1])
            + float(na[2]) * float(nb_v[2])
        )
        convexity[a] += curvature
        convexity[b] += curvature

    max_abs = max((abs(c) for c in convexity), default=1.0)
    if max_abs > 1e-12:
        convexity = [c / max_abs for c in convexity]
    return convexity


def _compute_slope_aspect(
    vertices: List[Tuple[float, float, float]],
    vertex_normals: List[Tuple[float, float, float]],
) -> Tuple[List[float], List[float]]:
    """Compute per-vertex slope (radians) and aspect (radians) from vertex normals.

    Blender 4.5 is Z-up.  The surface normal encodes both slope and aspect:
      slope  = arccos(clamp(nz, 0, 1))         (angle from vertical)
      aspect = atan2(nx, -ny)                   (compass bearing of downslope direction;
                                                 -ny so aspect=0 faces north)

    Returns (slopes, aspects) — lists parallel to *vertices*.
    """
    slopes: List[float] = []
    aspects: List[float] = []
    for n in vertex_normals:
        nx, ny, nz = float(n[0]), float(n[1]), float(n[2])
        nz_clamped = max(0.0, min(1.0, nz))
        slope = math.acos(nz_clamped)
        aspect = math.atan2(nx, -ny)
        slopes.append(slope)
        aspects.append(aspect)
    return slopes, aspects


def _smooth_channel(
    values: List[float],
    vertices: List[Tuple[float, float, float]],
    sigma_world: float = 2.0,
) -> List[float]:
    """Gaussian-smooth a per-vertex scalar channel using scipy if available.

    Falls back to the raw values when scipy is absent.
    *sigma_world* is the blur radius in world-space units.
    """
    n = len(values)
    if n < 4:
        return list(values)

    try:
        import numpy as np
        from scipy.ndimage import gaussian_filter, distance_transform_edt

        xs = [float(v[0]) for v in vertices]
        ys = [float(v[1]) for v in vertices]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max_x - min_x if (max_x - min_x) > 1e-6 else 1.0
        span_y = max_y - min_y if (max_y - min_y) > 1e-6 else 1.0

        grid_w = min(256, max(4, int(math.sqrt(n))))
        grid_h = min(256, max(4, int(math.sqrt(n))))
        grid = np.zeros((grid_h, grid_w), dtype=np.float64)
        weight = np.zeros((grid_h, grid_w), dtype=np.float64)

        for i in range(n):
            gx = int((xs[i] - min_x) / span_x * (grid_w - 1))
            gy = int((ys[i] - min_y) / span_y * (grid_h - 1))
            gx = max(0, min(grid_w - 1, gx))
            gy = max(0, min(grid_h - 1, gy))
            grid[gy, gx] += values[i]
            weight[gy, gx] += 1.0

        mask = weight > 0
        grid[mask] /= weight[mask]

        if not mask.all():
            _, idx = distance_transform_edt(~mask, return_indices=True)
            grid[~mask] = grid[idx[0][~mask], idx[1][~mask]]

        cell_size_x = span_x / (grid_w - 1) if grid_w > 1 else span_x
        cell_size_y = span_y / (grid_h - 1) if grid_h > 1 else span_y
        pixel_sigma = sigma_world / max(cell_size_x, cell_size_y)
        pixel_sigma = max(0.5, pixel_sigma)

        smoothed = gaussian_filter(grid, sigma=pixel_sigma)

        result: List[float] = []
        for i in range(n):
            gx = int((xs[i] - min_x) / span_x * (grid_w - 1))
            gy = int((ys[i] - min_y) / span_y * (grid_h - 1))
            gx = max(0, min(grid_w - 1, gx))
            gy = max(0, min(grid_h - 1, gy))
            result.append(float(smoothed[gy, gx]))
        return result

    except ImportError:
        return list(values)


# ---------------------------------------------------------------------------
# Vertex color weathering — 5-stage progression model
# ---------------------------------------------------------------------------


def compute_weathered_vertex_colors(
    mesh_data: dict,
    base_color: Tuple[float, float, float, float],
    preset_name: str = "medium",
    _cached_convexity: Optional[List[float]] = None,
) -> List[Tuple[float, float, float, float]]:
    """Return per-vertex RGBA colors encoding a 5-stage physical weathering progression.

    Weathering Progression Model
    ----------------------------
    Vertices do not age uniformly.  Local terrain signals determine how far
    along the weathering curve each vertex sits:

      Stage 0 — fresh:        Clean surface.  No discolouration.
      Stage 1 — stained:      Water-wash iron-oxide streaks, tannin bleed,
                               dark tide lines.  Orange-brown tint, slight
                               roughness increase.
      Stage 2 — patinated:    Oxidation crust (rust on iron, verdigris on
                               copper, calcium carbonate bloom on stone).
                               Grey-green tint, noticeably rougher surface.
      Stage 3 — crumbling:    Surface spalling, aggregate exposure,
                               micro-fracture networks.  Warm grey, very rough.
      Stage 4 — moss-covered: Biological colonisation dominates — lichen,
                               moss, biofilm.  Deep green-black, soft texture.

    Per-vertex age computation
    --------------------------
    A scalar ``age`` value in [0, 1] is computed per vertex by combining:

      age_base   — from the preset ``age_factor`` (0=fresh, 1=ancient).
      age_local  — terrain modifier that accelerates or retards weathering:
                    +  concave hollows collect moisture → faster ageing
                    +  north-facing (low cos aspect) → slower drying → faster bio
                    +  high elevation → more UV + freeze-thaw → faster mineral
                    −  convex exposed ridges resist bio but weather mineralically
                    −  low slope flat tops (water drains away) → slower bio

    The per-vertex ``age`` is then mapped to blended stage colors via the
    ``_WEATHERING_STAGES`` table using smooth raised-cosine weights so
    transitions between stages are C1-continuous.

    Channel encoding (RGBA output)
    --------------------------------
    R, G, B = blended stage color (multiplier × base_color + additive tint)
    A       = base_color alpha, passed through unchanged.

    Smoothing
    ---------
    The age scalar is Gaussian-smoothed before stage mapping to ensure
    weathering patches are spatially coherent (not per-vertex noise).

    Parameters
    ----------
    mesh_data:
        Dict with keys: vertices, faces, face_normals, vertex_normals, edges.
    base_color:
        RGBA tuple (r, g, b, a) in [0, 1].  Alpha is passed through.
    preset_name:
        Key in WEATHERING_PRESETS.
    _cached_convexity:
        Optional pre-computed convexity list.  When provided, output is
        deterministic and identical to the uncached call.

    Returns
    -------
    List of (r, g, b, a) tuples — one per vertex, all channels in [0, 1].
    """
    preset = WEATHERING_PRESETS[preset_name]
    vertices = mesh_data["vertices"]
    vertex_normals = mesh_data["vertex_normals"]
    n = len(vertices)

    if n == 0:
        return []

    # Convexity: positive = exposed ridge, negative = crevice/concave.
    if _cached_convexity is not None:
        convexity = list(_cached_convexity)
    else:
        convexity = _compute_edge_convexity(mesh_data)

    # Height normalization (Z-up).
    zs = [float(v[2]) for v in vertices]
    min_z = min(zs)
    max_z = max(zs)
    z_range = max_z - min_z if (max_z - min_z) > 1e-12 else 1.0

    # Slope and aspect.
    slopes, aspects = _compute_slope_aspect(vertices, vertex_normals)

    # ---- Per-vertex age computation -----------------------------------------
    # age_base comes from the preset; age_local modulates within ±0.3.
    age_base = float(preset.get("age_factor", 0.45))

    raw_age: List[float] = []
    for i in range(n):
        slope_t = slopes[i] / (math.pi / 2.0)          # 0=flat, 1=vertical
        concavity = max(0.0, -convexity[i])             # 0 on ridges, 1 in hollows
        convex = max(0.0, convexity[i])                 # 0 in hollows, 1 on ridges
        height_t = (zs[i] - min_z) / z_range
        north_factor = 0.5 - 0.5 * math.cos(aspects[i])  # 0=south, 1=north

        # Local age modifiers:
        # concave hollows age faster (moisture retention)
        # north-facing ages faster (slower drying → bio growth)
        # high elevation ages faster mineralically (UV + freeze-thaw)
        # convex exposed ridges age slower biologically (wind-dried)
        age_local = (
            concavity * 0.25          # hollow = wetter = faster bio/mineral
            + north_factor * 0.15     # north-facing = slower dry = more bio
            + height_t * 0.10         # high = more UV/freeze-thaw
            - convex * 0.15           # ridge = wind-dried = slower bio
            - (1.0 - slope_t) * 0.05  # flat top = drains = slower
        )
        age = max(0.0, min(1.0, age_base + age_local))
        raw_age.append(age)

    # Gaussian-smooth the age field so weathering patches are spatially coherent.
    smooth_sigma = 3.5
    smoothed_age = _smooth_channel(raw_age, vertices, sigma_world=smooth_sigma)

    # ---- Stage blending -------------------------------------------------
    br, bg, bb, ba = (float(c) for c in base_color)

    result: List[Tuple[float, float, float, float]] = []
    for i in range(n):
        age = max(0.0, min(1.0, smoothed_age[i]))

        # Accumulate blended color from all overlapping stages.
        # Stages have overlapping age ranges; weights sum to ≈1 at most ages.
        total_weight = 0.0
        blended_r = 0.0
        blended_g = 0.0
        blended_b = 0.0

        for stage in _WEATHERING_STAGES:
            w = _stage_weight(age, stage["age_start"], stage["age_end"])
            if w < 1e-6:
                continue
            mr, mg, mb, _ = stage["color_mul"]
            ar, ag, ab = stage["color_add"]
            # Stage color = base_color * multiplier + additive tint
            sr = br * mr + ar
            sg = bg * mg + ag
            sb = bb * mb + ab
            blended_r += sr * w
            blended_g += sg * w
            blended_b += sb * w
            total_weight += w

        # Normalise by total weight; fall back to base_color if no stage matched.
        if total_weight > 1e-6:
            inv_w = 1.0 / total_weight
            r = max(0.0, min(1.0, blended_r * inv_w))
            g = max(0.0, min(1.0, blended_g * inv_w))
            b = max(0.0, min(1.0, blended_b * inv_w))
        else:
            r, g, b = br, bg, bb

        result.append((r, g, b, max(0.0, min(1.0, ba))))

    return result


# ---------------------------------------------------------------------------
# Structural settling — subsidence + tilt from compaction
# ---------------------------------------------------------------------------


def apply_structural_settling(
    verts: List[Tuple[float, float, float]],
    strength: float = 0.01,
    seed: int = 42,
    _cached_bbox: Optional[Dict[str, float]] = None,
    dt: float = 1.0,
    steps: int = 3,
    k: float = 0.08,
) -> List[Tuple[float, float, float]]:
    """Simulate compaction-driven subsidence and differential-settlement tilt.

    Physical Model
    --------------
    Two independent deformation mechanisms are combined:

    1. Subsidence (vertical compaction)
    ------------------------------------
    Loose granular material (soil, gravel, rubble infill) consolidates
    under self-weight over time.  The settlement magnitude scales with
    the vertical load, approximated here as proportional to the height
    of overburden above the local terrain surface.

    Differential subsidence: cells with softer substrate (proxied by
    lower local height — hollows that accumulated soft sediment) subside
    more than cells on bedrock outcrops (local maxima).  This produces
    the characteristic "dish" shape of a settled foundation.

        delta_z_subsidence[i] = -strength * load_factor[i]
                               * (1 + softness_factor[i] * 1.5)

    where:
        load_factor   = normalised overburden height (0 at min_z, 1 at max_z)
        softness_factor = 1 - (local_z - neighbourhood_mean_z) / z_range
                          (cells below their neighbours = soft sediment)

    2. Tilt from differential settlement
    -------------------------------------
    When two adjacent parts of a structure settle by different amounts,
    the intervening section tilts.  In the grid formulation this means
    the X and Y displacements of each vertex are shifted proportionally
    to the local settlement gradient:

        dx_tilt[i] = tilt_factor * d(delta_z)/dx
        dy_tilt[i] = tilt_factor * d(delta_z)/dy

    where tilt_factor is proportional to ``strength`` and a ``k``-scaled
    lateral stiffness coefficient.  This causes the tops of poorly
    supported walls to lean toward the areas of maximum subsidence —
    exactly the "leaning tower" effect seen in compaction-settled ruins.

    3. Creep diffusion (legacy, retained)
    --------------------------------------
    The original slope^2-diffusion model is still applied as a third
    pass to smooth out the discrete-grid artifacts from the subsidence
    and tilt steps.  ``steps`` iterations of anisotropic diffusion are
    run with a much-reduced magnitude (0.2x) so creep is a secondary
    correction, not the primary deformation.

    Parameters
    ----------
    verts:
        List of (x, y, z) position tuples (Blender Z-up world space).
    strength:
        Global scale on total displacement.  0.01 ≈ 1 cm max settling
        for fresh scatter; 0.15 ≈ 15 cm for ancient, heavily settled ruins.
    seed:
        RNG seed for spatial noise on softness factor (deterministic).
    _cached_bbox:
        Optional pre-computed bounding box.
    dt:
        Time-step per creep diffusion iteration.
    steps:
        Number of creep diffusion iterations (post-subsidence smoothing).
    k:
        Creep coefficient (slope^2 diffusivity) and tilt stiffness scale.

    Returns
    -------
    List of (x, y, z) tuples with subsidence + tilt + creep applied.
    """
    if not verts:
        return []

    if _cached_bbox is not None:
        bbox = _cached_bbox
    else:
        bbox = _compute_bounding_box(verts)

    min_x, max_x = bbox["min_x"], bbox["max_x"]
    min_y, max_y = bbox["min_y"], bbox["max_y"]
    min_z, max_z = bbox["min_z"], bbox["max_z"]

    span_x = max_x - min_x if (max_x - min_x) > 1e-12 else 1.0
    span_y = max_y - min_y if (max_y - min_y) > 1e-12 else 1.0
    z_range = max_z - min_z if (max_z - min_z) > 1e-12 else 1.0

    n = len(verts)
    grid_w = min(256, max(4, int(math.sqrt(n))))
    grid_h = min(256, max(4, int(math.sqrt(n))))
    cell_dx = span_x / (grid_w - 1) if grid_w > 1 else span_x
    cell_dy = span_y / (grid_h - 1) if grid_h > 1 else span_y

    # ---- Rasterise vertices onto heightmap ----------------------------------
    rng = random.Random(derive_pass_seed(seed, "weathering.apply_structural_settling", 0, 0, None))

    try:
        import numpy as np

        h = np.zeros((grid_h, grid_w), dtype=np.float64)
        weight = np.zeros((grid_h, grid_w), dtype=np.float64)

        for v in verts:
            gx = int((float(v[0]) - min_x) / span_x * (grid_w - 1))
            gy = int((float(v[1]) - min_y) / span_y * (grid_h - 1))
            gx = max(0, min(grid_w - 1, gx))
            gy = max(0, min(grid_h - 1, gy))
            h[gy, gx] += float(v[2])
            weight[gy, gx] += 1.0

        filled_mask = weight > 0
        h[filled_mask] /= weight[filled_mask]

        # Fill empty cells with mean of filled.
        mean_h = float(h[filled_mask].mean()) if filled_mask.any() else (min_z + max_z) * 0.5
        h[~filled_mask] = mean_h

        # ---- 1. Subsidence: differential vertical compaction ----------------
        # Neighbourhood mean height (3×3 box filter approximation via shifts).
        _h_pad = np.pad(h, 1, mode="edge")
        h_nbhd = (
            _h_pad[:-2, 1:-1] + _h_pad[2:, 1:-1]
            + _h_pad[1:-1, :-2] + _h_pad[1:-1, 2:]
        ) / 4.0
        # np.pad edge mode prevents toroidal tile-seam contamination

        # softness_factor: cells below neighbourhood mean = soft sediment (→ 1)
        #                  cells above neighbourhood mean = bedrock (→ 0)
        softness = np.clip((h_nbhd - h) / z_range * 4.0 + 0.5, 0.0, 1.0)

        # Add spatially correlated noise to softness (deterministic via seed).
        noise = np.zeros((grid_h, grid_w), dtype=np.float64)
        for gy in range(grid_h):
            for gx in range(grid_w):
                # Low-frequency noise: sample at 1/8 resolution and bilinear
                noise[gy, gx] = rng.gauss(0.0, 0.12)
        softness = np.clip(softness + noise * 0.2, 0.0, 1.0)

        # Load factor = normalised height (overburden proxy).
        load_factor = np.clip((h - min_z) / z_range, 0.0, 1.0)

        # Vertical subsidence displacement (negative = downward).
        delta_z_sub = -strength * load_factor * (1.0 + softness * 1.5)

        # ---- 2. Tilt: lateral displacement from settlement gradient ----------
        # Gradient of the subsidence field = tilt direction.
        # Cells adjacent to a large subsidence pit tilt toward it.
        tilt_scale = strength * k * 3.0

        # Central-difference gradient of delta_z_sub.
        grad_x = np.zeros_like(delta_z_sub)
        grad_y = np.zeros_like(delta_z_sub)
        grad_x[:, 1:-1] = (delta_z_sub[:, 2:] - delta_z_sub[:, :-2]) / (2.0 * cell_dx)
        grad_x[:, 0] = (delta_z_sub[:, 1] - delta_z_sub[:, 0]) / cell_dx
        grad_x[:, -1] = (delta_z_sub[:, -1] - delta_z_sub[:, -2]) / cell_dx
        grad_y[1:-1, :] = (delta_z_sub[2:, :] - delta_z_sub[:-2, :]) / (2.0 * cell_dy)
        grad_y[0, :] = (delta_z_sub[1, :] - delta_z_sub[0, :]) / cell_dy
        grad_y[-1, :] = (delta_z_sub[-1, :] - delta_z_sub[-2, :]) / cell_dy

        # Lateral tilt displacement: proportional to settlement gradient.
        # Positive gradient (subsiding neighbours to the +x side) → positive
        # tilt shift in x (lean toward subsiding side).
        delta_x_tilt = tilt_scale * grad_x
        delta_y_tilt = tilt_scale * grad_y

        # Apply subsidence to heightmap for creep-diffusion input.
        h_settled = h + delta_z_sub

        # ---- 3. Creep diffusion (secondary smoothing pass) ------------------
        for _ in range(steps):
            dh_dx = np.zeros_like(h_settled)
            dh_dy = np.zeros_like(h_settled)
            dh_dx[:, 1:-1] = (h_settled[:, 2:] - h_settled[:, :-2]) / (2.0 * cell_dx)
            dh_dx[:, 0] = (h_settled[:, 1] - h_settled[:, 0]) / cell_dx
            dh_dx[:, -1] = (h_settled[:, -1] - h_settled[:, -2]) / cell_dx
            dh_dy[1:-1, :] = (h_settled[2:, :] - h_settled[:-2, :]) / (2.0 * cell_dy)
            dh_dy[0, :] = (h_settled[1, :] - h_settled[0, :]) / cell_dy
            dh_dy[-1, :] = (h_settled[-1, :] - h_settled[-2, :]) / cell_dy

            slope_sq = dh_dx ** 2 + dh_dy ** 2
            D = k * slope_sq * 0.2  # attenuated: creep is secondary here

            lap = np.zeros_like(h_settled)
            lap[1:-1, 1:-1] = (
                h_settled[1:-1, 2:] + h_settled[1:-1, :-2]
                + h_settled[2:, 1:-1] + h_settled[:-2, 1:-1]
                - 4.0 * h_settled[1:-1, 1:-1]
            )
            Fdx = D * dh_dx
            Fdy = D * dh_dy
            div_F = np.zeros_like(h_settled)
            div_F[:, 1:-1] += (Fdx[:, 2:] - Fdx[:, :-2]) / (2.0 * cell_dx)
            div_F[1:-1, :] += (Fdy[2:, :] - Fdy[:-2, :]) / (2.0 * cell_dy)
            delta = dt * (0.3 * lap + 0.7 * div_F)
            h_range = float(h_settled.max() - h_settled.min()) if h_settled.max() > h_settled.min() else 1.0
            delta = np.clip(delta, -0.2 * h_range, 0.2 * h_range)
            h_settled = h_settled + delta

        # ---- Sample back per vertex -----------------------------------------
        result: List[Tuple[float, float, float]] = []
        for v in verts:
            gx = int((float(v[0]) - min_x) / span_x * (grid_w - 1))
            gy = int((float(v[1]) - min_y) / span_y * (grid_h - 1))
            gx = max(0, min(grid_w - 1, gx))
            gy = max(0, min(grid_h - 1, gy))

            new_z = float(h_settled[gy, gx])
            # Scale total z delta by strength (subsidence already uses strength,
            # but re-scale so caller's strength=0.01 gives ≈1 cm total).
            delta_z = (new_z - float(v[2])) * strength
            # Tilt: lateral displacement proportional to local settlement gradient.
            dx_t = float(delta_x_tilt[gy, gx])
            dy_t = float(delta_y_tilt[gy, gx])

            result.append((
                float(v[0]) + dx_t,
                float(v[1]) + dy_t,
                float(v[2]) + delta_z,
            ))
        return result

    except ImportError:
        # Pure-Python fallback: subsidence only (no numpy tilt computation).
        grid = [[0.0] * grid_w for _ in range(grid_h)]
        weight_g = [[0.0] * grid_w for _ in range(grid_h)]

        for v in verts:
            gx = int((float(v[0]) - min_x) / span_x * (grid_w - 1))
            gy = int((float(v[1]) - min_y) / span_y * (grid_h - 1))
            gx = max(0, min(grid_w - 1, gx))
            gy = max(0, min(grid_h - 1, gy))
            grid[gy][gx] += float(v[2])
            weight_g[gy][gx] += 1.0

        total_h = 0.0
        filled = 0
        for gy in range(grid_h):
            for gx in range(grid_w):
                if weight_g[gy][gx] > 0.0:
                    grid[gy][gx] /= weight_g[gy][gx]
                    total_h += grid[gy][gx]
                    filled += 1
        mean_h = total_h / filled if filled > 0 else (min_z + max_z) * 0.5
        for gy in range(grid_h):
            for gx in range(grid_w):
                if weight_g[gy][gx] == 0.0:
                    grid[gy][gx] = mean_h

        # Subsidence: differential settlement (soft cells subside more).
        sub_delta = [[0.0] * grid_w for _ in range(grid_h)]
        for gy in range(grid_h):
            for gx in range(grid_w):
                z_val = grid[gy][gx]
                load_f = (z_val - min_z) / z_range
                # Neighbourhood mean for softness.
                nbhd_sum = 0.0
                nbhd_cnt = 0
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        nr, nc = gy + dr, gx + dc
                        if 0 <= nr < grid_h and 0 <= nc < grid_w:
                            nbhd_sum += grid[nr][nc]
                            nbhd_cnt += 1
                nbhd_mean = nbhd_sum / nbhd_cnt if nbhd_cnt > 0 else z_val
                softness = max(0.0, min(1.0, (nbhd_mean - z_val) / z_range * 4.0 + 0.5))
                sub_delta[gy][gx] = -strength * load_f * (1.0 + softness * 1.5)

        # Tilt: compute settlement gradient via finite differences.
        tilt_x = [[0.0] * grid_w for _ in range(grid_h)]
        tilt_y = [[0.0] * grid_w for _ in range(grid_h)]
        tilt_scale = strength * k * 3.0
        for gy in range(1, grid_h - 1):
            for gx in range(1, grid_w - 1):
                gx_grad = (sub_delta[gy][gx + 1] - sub_delta[gy][gx - 1]) / (2.0 * cell_dx)
                gy_grad = (sub_delta[gy + 1][gx] - sub_delta[gy - 1][gx]) / (2.0 * cell_dy)
                tilt_x[gy][gx] = tilt_scale * gx_grad
                tilt_y[gy][gx] = tilt_scale * gy_grad

        # Creep diffusion.
        h = [row[:] for row in grid]
        for gy in range(grid_h):
            for gx in range(grid_w):
                h[gy][gx] += sub_delta[gy][gx]

        for _ in range(steps):
            new_h = [row[:] for row in h]
            for gy in range(1, grid_h - 1):
                for gx in range(1, grid_w - 1):
                    dhdx = (h[gy][gx + 1] - h[gy][gx - 1]) / (2.0 * cell_dx)
                    dhdy = (h[gy + 1][gx] - h[gy - 1][gx]) / (2.0 * cell_dy)
                    slope_sq = dhdx * dhdx + dhdy * dhdy
                    D = k * slope_sq * 0.2
                    lap = (
                        h[gy][gx + 1] + h[gy][gx - 1]
                        + h[gy + 1][gx] + h[gy - 1][gx]
                        - 4.0 * h[gy][gx]
                    )
                    new_h[gy][gx] = h[gy][gx] + dt * D * lap
            h = new_h

        result_py: List[Tuple[float, float, float]] = []
        for v in verts:
            gx = int((float(v[0]) - min_x) / span_x * (grid_w - 1))
            gy = int((float(v[1]) - min_y) / span_y * (grid_h - 1))
            gx = max(0, min(grid_w - 1, gx))
            gy = max(0, min(grid_h - 1, gy))
            new_z = h[gy][gx]
            delta_z = (new_z - float(v[2])) * strength
            result_py.append((
                float(v[0]) + tilt_x[gy][gx],
                float(v[1]) + tilt_y[gy][gx],
                float(v[2]) + delta_z,
            ))
        return result_py

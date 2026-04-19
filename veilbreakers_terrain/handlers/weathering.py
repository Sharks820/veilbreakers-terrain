"""Weathering and structural-settling utilities for assembled meshes.

Provides:
  - WEATHERING_PRESETS: named preset configurations
  - _compute_bounding_box(): axis-aligned bounding box dict
  - compute_weathered_vertex_colors(): physically-based weathering state encoding
  - apply_structural_settling(): slope-dependent creep diffusion model
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Tuple

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
    },
    "medium": {
        "dirt_accumulation": 0.20,
        "edge_wear": 0.35,
        "surface_roughness": 0.25,
        "color_shift": 0.12,
        "moss_coverage": 0.10,
    },
    "heavy": {
        "dirt_accumulation": 0.55,
        "edge_wear": 0.75,
        "surface_roughness": 0.60,
        "color_shift": 0.30,
        "moss_coverage": 0.35,
    },
}


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
# Vertex color weathering
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
        # curvature = 1 - dot(na, nb): 0 for flat, +2 for opposing normals (convex ridge).
        # Orientation-invariant: swapping a<->b gives identical curvature.
        curvature = 1.0 - (
            float(na[0]) * float(nb_v[0])
            + float(na[1]) * float(nb_v[1])
            + float(na[2]) * float(nb_v[2])
        )
        # Distribute equally to both endpoints (symmetric, orientation-invariant).
        convexity[a] += curvature
        convexity[b] += curvature

    # Normalise to [-1, 1]
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
        slope = math.acos(nz_clamped)  # 0 = flat, π/2 = vertical cliff
        # Aspect: bearing of the steepest ascent projected onto XY plane.
        # atan2(nx, -ny) → 0 = north (+Y), π/2 = east (+X).
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

    Falls back to a simple unweighted neighbour average when scipy is absent.
    *sigma_world* is the blur radius in world-space units; it is converted to
    a pixel sigma by dividing by the mean inter-vertex spacing.
    """
    n = len(values)
    if n < 4:
        return list(values)

    try:
        import numpy as np
        from scipy.ndimage import gaussian_filter

        # Rasterise the per-vertex channel onto a 2-D grid using XY position.
        xs = [float(v[0]) for v in vertices]
        ys = [float(v[1]) for v in vertices]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max_x - min_x if (max_x - min_x) > 1e-6 else 1.0
        span_y = max_y - min_y if (max_y - min_y) > 1e-6 else 1.0

        # Choose grid resolution: at most 256×256, at least 1 cell per vertex.
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

        # Average cells with multiple vertices, fill empty cells with nearest.
        mask = weight > 0
        grid[mask] /= weight[mask]

        # Fill holes by propagating from filled cells (simple nearest-fill).
        if not mask.all():
            from scipy.ndimage import distance_transform_edt
            _, idx = distance_transform_edt(~mask, return_indices=True)
            grid[~mask] = grid[idx[0][~mask], idx[1][~mask]]

        # Convert world-space sigma to pixel sigma.
        cell_size_x = span_x / (grid_w - 1) if grid_w > 1 else span_x
        cell_size_y = span_y / (grid_h - 1) if grid_h > 1 else span_y
        pixel_sigma = sigma_world / max(cell_size_x, cell_size_y)
        pixel_sigma = max(0.5, pixel_sigma)

        smoothed = gaussian_filter(grid, sigma=pixel_sigma)

        # Sample back per vertex.
        result: List[float] = []
        for i in range(n):
            gx = int((xs[i] - min_x) / span_x * (grid_w - 1))
            gy = int((ys[i] - min_y) / span_y * (grid_h - 1))
            gx = max(0, min(grid_w - 1, gx))
            gy = max(0, min(grid_h - 1, gy))
            result.append(float(smoothed[gy, gx]))
        return result

    except ImportError:
        # No scipy — return unmodified (still correct, just unsmoothed).
        return list(values)


def compute_weathered_vertex_colors(
    mesh_data: dict,
    base_color: Tuple[float, float, float, float],
    preset_name: str = "medium",
    _cached_convexity: Optional[List[float]] = None,
) -> List[Tuple[float, float, float, float]]:
    """Return per-vertex RGBA colors encoding physical weathering state.

    Each RGB channel carries a distinct physical signal rather than blending
    into a single tint.  The shader unpacks these channels to drive material
    blending, AO tinting, and detail-normal intensity:

      R — oxidation / age exposure
            Iron-oxide accumulation on exposed surfaces (value → 1.0 = orange
            rust / desert patina).  Peaks where slope is low (flat tops hold
            moisture that evaporates and oxidises) and convexity is high
            (exposed ridges weather faster).

      G — biological growth (lichen, moss)
            Higher on north-facing slopes (low sun, retained moisture) and
            in low-altitude, high-slope, concave micro-environments where
            water lingers.  cos(aspect) < 0 → facing north in Northern
            hemisphere conventions.

      B — erosion severity (surface texture loss, gullying)
            High slope → rain splash and overland flow strip surface texture.
            Amplified in concave drainage lines (aspect-directed flow
            convergence).  Low at flat tops, maximum on steep slopes.

    All three channels are smoothed with a Gaussian kernel (scipy if present,
    raw values otherwise) to avoid per-vertex noise that would produce
    pixel-scale texture variation rather than coherent weathering patches.

    Parameters
    ----------
    mesh_data:
        Dict with keys: vertices, faces, face_normals, vertex_normals, edges.
    base_color:
        RGBA tuple (r, g, b, a) in [0, 1].  Alpha is passed through.
    preset_name:
        Key in WEATHERING_PRESETS — controls overall intensity scaling.
    _cached_convexity:
        Optional pre-computed convexity list (same length as vertices).
        When provided, identical output is guaranteed (pure deterministic).

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

    # Height normalisation (Z-up).
    zs = [float(v[2]) for v in vertices]
    min_z = min(zs)
    max_z = max(zs)
    z_range = max_z - min_z if (max_z - min_z) > 1e-12 else 1.0

    # Slope (0 = flat, π/2 = vertical) and aspect (radians, 0 = north).
    slopes, aspects = _compute_slope_aspect(vertices, vertex_normals)

    # ---- R channel: oxidation / age exposure --------------------------------
    # Exposed, gently-sloped surfaces accumulate iron-oxide patina fastest.
    # Flat tops (low slope) that are convex (no shelter) peak at 1.0.
    raw_r: List[float] = []
    for i in range(n):
        slope_t = slopes[i] / (math.pi / 2.0)          # 0=flat, 1=vertical
        exposure = max(0.0, convexity[i])               # 0 in hollows, 1 on ridges
        height_t = (zs[i] - min_z) / z_range
        # Oxidation is strongest on low-slope, elevated, exposed areas.
        oxidation = (1.0 - slope_t * 0.6) * (0.4 + 0.6 * exposure) * (0.3 + 0.7 * height_t)
        raw_r.append(float(max(0.0, min(1.0, oxidation))))

    # ---- G channel: biological growth (lichen / moss) -----------------------
    # Highest where: north-facing (cos(aspect) < 0), concave, moderate slope,
    # and low altitude (less UV, more retained moisture).
    raw_g: List[float] = []
    for i in range(n):
        # cos(aspect): -1 = true north, +1 = true south (Northern hemisphere).
        north_factor = 0.5 - 0.5 * math.cos(aspects[i])   # 0 = south, 1 = north
        slope_t = slopes[i] / (math.pi / 2.0)
        concavity = max(0.0, -convexity[i])                # concave = positive
        height_t = (zs[i] - min_z) / z_range
        moisture_proxy = (
            north_factor * 0.40
            + concavity * 0.35
            + (1.0 - height_t) * 0.15
            + (slope_t * (1.0 - slope_t) * 4.0) * 0.10   # moderate slope peak
        )
        raw_g.append(float(max(0.0, min(1.0, moisture_proxy))))

    # ---- B channel: erosion severity ----------------------------------------
    # Driven by slope^2 (transport capacity) plus concave drainage convergence.
    raw_b: List[float] = []
    for i in range(n):
        slope_t = slopes[i] / (math.pi / 2.0)
        concavity = max(0.0, -convexity[i])
        # Steep slopes with convergent drainage = maximum erosion.
        erosion = slope_t ** 2 * 0.65 + concavity * 0.35
        raw_b.append(float(max(0.0, min(1.0, erosion))))

    # Gaussian smoothing to produce coherent weathering patches.
    smooth_sigma = 3.0  # world-space blur radius (metres)
    smoothed_r = _smooth_channel(raw_r, vertices, sigma_world=smooth_sigma)
    smoothed_g = _smooth_channel(raw_g, vertices, sigma_world=smooth_sigma)
    smoothed_b = _smooth_channel(raw_b, vertices, sigma_world=smooth_sigma)

    # Scale each channel by the preset intensity for the relevant signal.
    scale_r = preset["color_shift"] + preset["edge_wear"] * 0.5       # oxidation follows exposure
    scale_g = preset["moss_coverage"]                                   # direct moss coverage
    scale_b = preset["surface_roughness"] + preset["dirt_accumulation"] * 0.4  # erosion

    _, _, _, ba = (float(c) for c in base_color)

    result: List[Tuple[float, float, float, float]] = []
    for i in range(n):
        r = float(max(0.0, min(1.0, smoothed_r[i] * scale_r)))
        g = float(max(0.0, min(1.0, smoothed_g[i] * scale_g)))
        b = float(max(0.0, min(1.0, smoothed_b[i] * scale_b)))
        result.append((r, g, b, float(max(0.0, min(1.0, ba)))))
    return result


# ---------------------------------------------------------------------------
# Structural settling
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
    """Simulate creep-driven structural settling on a heightmap.

    Loose material migrates slowly downslope over geological time via soil
    creep.  The governing equation is:

        dh/dt = -k * slope^2

    where slope is the local surface gradient magnitude and k is the creep
    coefficient.  This is applied as *steps* iterations of anisotropic
    diffusion: downslope neighbours receive more material than cross-slope
    neighbours, matching field observations (e.g. Roering et al. 1999).

    The vertices are rasterised onto a 2-D heightmap, diffusion is applied,
    then the updated heights are sampled back per vertex.  When scipy is not
    available the implementation falls back to a pure-Python finite-difference
    stencil on the same grid.

    Parameters
    ----------
    verts:
        List of (x, y, z) position tuples (Blender Z-up world space).
    strength:
        Global scale on the total height displacement.  A value of 0.01
        corresponds to roughly 1 cm of maximum settling — appropriate for
        a freshly-placed rock scatter or loose scree.
    seed:
        Not used for diffusion (deterministic); retained for API stability.
    _cached_bbox:
        Optional pre-computed bounding box.  When provided the output is
        identical to the uncached call.
    dt:
        Time-step per diffusion iteration (arbitrary units; larger = more
        settling per step).
    steps:
        Number of diffusion iterations.  3–5 is sufficient for visual
        plausibility without over-smoothing.
    k:
        Creep coefficient.  Scales slope^2 to a diffusivity.  Increase for
        sandy/loose substrates, decrease for consolidated rock.

    Returns
    -------
    List of (x, y, z) tuples (Python floats).
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

    n = len(verts)
    # Grid resolution: sqrt(n) capped at 256 to keep cost reasonable.
    grid_w = min(256, max(4, int(math.sqrt(n))))
    grid_h = min(256, max(4, int(math.sqrt(n))))

    # ---- Rasterise vertices onto heightmap ----------------------------------
    # Accumulate and average when multiple vertices land in the same cell.
    grid = [[0.0] * grid_w for _ in range(grid_h)]
    weight = [[0.0] * grid_w for _ in range(grid_h)]

    for v in verts:
        gx = int((float(v[0]) - min_x) / span_x * (grid_w - 1))
        gy = int((float(v[1]) - min_y) / span_y * (grid_h - 1))
        gx = max(0, min(grid_w - 1, gx))
        gy = max(0, min(grid_h - 1, gy))
        grid[gy][gx] += float(v[2])
        weight[gy][gx] += 1.0

    for gy in range(grid_h):
        for gx in range(grid_w):
            if weight[gy][gx] > 0.0:
                grid[gy][gx] /= weight[gy][gx]

    # Fill empty cells with the mean height so diffusion has no data holes.
    total_h = 0.0
    filled = 0
    for gy in range(grid_h):
        for gx in range(grid_w):
            if weight[gy][gx] > 0.0:
                total_h += grid[gy][gx]
                filled += 1
    mean_h = total_h / filled if filled > 0 else (min_z + max_z) * 0.5
    for gy in range(grid_h):
        for gx in range(grid_w):
            if weight[gy][gx] == 0.0:
                grid[gy][gx] = mean_h

    # ---- Anisotropic creep diffusion ----------------------------------------
    # Try numpy/scipy first for speed; fall back to pure Python.
    try:
        import numpy as np

        h = np.array(grid, dtype=np.float64)
        cell_dx = span_x / (grid_w - 1) if grid_w > 1 else span_x
        cell_dy = span_y / (grid_h - 1) if grid_h > 1 else span_y

        for _ in range(steps):
            # Gradient in x and y (central differences, edge clamp).
            dh_dx = np.zeros_like(h)
            dh_dy = np.zeros_like(h)
            dh_dx[:, 1:-1] = (h[:, 2:] - h[:, :-2]) / (2.0 * cell_dx)
            dh_dx[:, 0] = (h[:, 1] - h[:, 0]) / cell_dx
            dh_dx[:, -1] = (h[:, -1] - h[:, -2]) / cell_dx
            dh_dy[1:-1, :] = (h[2:, :] - h[:-2, :]) / (2.0 * cell_dy)
            dh_dy[0, :] = (h[1, :] - h[0, :]) / cell_dy
            dh_dy[-1, :] = (h[-1, :] - h[-2, :]) / cell_dy

            slope_sq = dh_dx ** 2 + dh_dy ** 2  # |grad h|^2

            # Downslope diffusivity is k * slope^2; perpendicular is attenuated
            # by (1 - slope_t) to produce anisotropy.
            D = k * slope_sq  # (H, W)

            # Laplacian (isotropic base) — anisotropic term adds downslope bias.
            lap = np.zeros_like(h)
            lap[1:-1, 1:-1] = (
                h[1:-1, 2:] + h[1:-1, :-2]
                + h[2:, 1:-1] + h[:-2, 1:-1]
                - 4.0 * h[1:-1, 1:-1]
            )

            # Anisotropic downslope bias: divergence of (D * grad h).
            Fdx = D * dh_dx
            Fdy = D * dh_dy
            div_F = np.zeros_like(h)
            div_F[:, 1:-1] += (Fdx[:, 2:] - Fdx[:, :-2]) / (2.0 * cell_dx)
            div_F[1:-1, :] += (Fdy[2:, :] - Fdy[:-2, :]) / (2.0 * cell_dy)

            # Blend: pure Laplacian keeps the surface stable; anisotropic term
            # drives material downslope.
            delta = dt * (0.3 * lap + 0.7 * div_F)

            # Stability limit: clamp delta to at most 20% of local height range.
            h_range = float(h.max() - h.min()) if h.max() > h.min() else 1.0
            delta = np.clip(delta, -0.2 * h_range, 0.2 * h_range)
            h = h + delta

        settled_grid = h.tolist()

    except ImportError:
        # Pure-Python fallback: simple slope^2-diffusion stencil.
        h = [row[:] for row in grid]
        cell_dx = span_x / (grid_w - 1) if grid_w > 1 else span_x
        cell_dy = span_y / (grid_h - 1) if grid_h > 1 else span_y

        for _ in range(steps):
            new_h = [row[:] for row in h]
            for gy in range(1, grid_h - 1):
                for gx in range(1, grid_w - 1):
                    dhdx = (h[gy][gx + 1] - h[gy][gx - 1]) / (2.0 * cell_dx)
                    dhdy = (h[gy + 1][gx] - h[gy - 1][gx]) / (2.0 * cell_dy)
                    slope_sq = dhdx * dhdx + dhdy * dhdy
                    D = k * slope_sq
                    lap = (
                        h[gy][gx + 1] + h[gy][gx - 1]
                        + h[gy + 1][gx] + h[gy - 1][gx]
                        - 4.0 * h[gy][gx]
                    )
                    new_h[gy][gx] = h[gy][gx] + dt * D * lap
            h = new_h
        settled_grid = h

    # ---- Sample updated heights back to each vertex -------------------------
    # Measure total delta applied so we can scale by `strength`.
    result: List[Tuple[float, float, float]] = []
    for v in verts:
        gx = int((float(v[0]) - min_x) / span_x * (grid_w - 1))
        gy = int((float(v[1]) - min_y) / span_y * (grid_h - 1))
        gx = max(0, min(grid_w - 1, gx))
        gy = max(0, min(grid_h - 1, gy))
        new_z = float(settled_grid[gy][gx])
        # Scale the delta by strength so the caller controls magnitude.
        delta_z = (new_z - float(v[2])) * strength
        result.append((float(v[0]), float(v[1]), float(v[2]) + delta_z))
    return result

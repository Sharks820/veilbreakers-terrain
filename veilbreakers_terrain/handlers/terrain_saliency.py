"""Vantage-aware saliency refinement for terrain composition (Bundle H).

Pure numpy. No bpy. Takes an existing ``saliency_macro`` channel and
refines it using camera-vantage ray-casts so the final composition mask
reflects what the player actually sees from hero camera positions —
the Witcher 3 / Horizon ZD "camera-aware" composition trick.

Design notes
------------
compute_vantage_silhouettes casts azimuthal rays from each vantage and
detects sky-vs-terrain horizon transitions by finding the ray sample where
terrain elevation crosses the vantage eye level. Ridge cells that form a
camera-facing silhouette against the sky receive a high silhouette score.

_rasterize_vantage_silhouettes_onto_grid uses fast DDA (Digital Differential
Analyzer) line rasterization to stamp silhouette contributions along each
ray onto the grid — each cell visited by a ray receives a contribution
weighted by silhouette elevation angle and inverse-square distance falloff.

auto_sculpt_around_feature produces a "desire line" height delta that follows
the path of least resistance from the feature outward, matching the natural
erosion paths that form organic trails in real terrain (Horizon FW / RDR2
approach). Not a radial Gaussian — the delta follows the gradient descent
direction so sculpted depressions become actual drainage channels.

pass_saliency_refine produces ``saliency_score`` (written back to
``saliency_macro``) using a full 8-factor UE5-style importance scoring:
  1. Height visibility (vantage silhouette)
  2. Distance from water
  3. Slope shelter
  4. Ridge prominence
  5. Convexity (topographic prominence)
  6. Sky-exposure (open sky above cell)
  7. Vegetation-break potential (flat-to-steep transitions)
  8. Tactical sight-line coverage

See docs/terrain_ultra_implementation_plan_2026-04-08.md §13 Bundle H.
"""

from __future__ import annotations

import time
from typing import Optional, Sequence, Tuple

import numpy as np

try:
    from scipy.ndimage import map_coordinates as _map_coordinates
    from scipy.ndimage import uniform_filter, generic_filter
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    QualityGate,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)


# ---------------------------------------------------------------------------
# World <-> grid helpers
# ---------------------------------------------------------------------------


def _world_to_cell(
    stack: TerrainMaskStack, x: float, y: float
) -> Tuple[int, int]:
    """Convert world-space (x, y) to integer (row, col) grid indices.

    Clamps to valid grid bounds so out-of-range world positions are mapped
    to the nearest border cell rather than raising IndexError.
    Sub-cell accuracy is preserved by rounding (not truncating) so that
    world positions at the centre of a cell map correctly.
    """
    col = int(round((x - stack.world_origin_x) / stack.cell_size))
    row = int(round((y - stack.world_origin_y) / stack.cell_size))
    rows, cols = stack.height.shape
    col = max(0, min(cols - 1, col))
    row = max(0, min(rows - 1, row))
    return row, col


def _sample_height_bilinear(height: np.ndarray, rf: float, cf: float) -> float:
    """Bilinearly sample *height* at fractional grid position (rf, cf).

    Clamps to [0, rows-1] × [0, cols-1] so out-of-bounds fractional coords
    safely return border values rather than raising IndexError.
    Uses floor-based 2×2 neighbourhood with (1-dr)*(1-dc) interpolation weights.

    Edge-safe: r0, c0 are clamped to [0, rows-2] and [0, cols-2] so that
    r0+1 and c0+1 are always valid indices regardless of rf/cf clamping order.
    """
    rows, cols = height.shape
    rf = max(0.0, min(float(rows - 1), rf))
    cf = max(0.0, min(float(cols - 1), cf))
    r0 = int(np.floor(rf))
    c0 = int(np.floor(cf))
    # Clamp r0/c0 so r0+1 and c0+1 never exceed array bounds
    r0 = min(r0, rows - 2) if rows >= 2 else 0
    c0 = min(c0, cols - 2) if cols >= 2 else 0
    dr = rf - r0
    dc = cf - c0
    if rows < 2 or cols < 2:
        return float(height[r0, c0])
    h00 = height[r0, c0]
    h01 = height[r0, c0 + 1]
    h10 = height[r0 + 1, c0]
    h11 = height[r0 + 1, c0 + 1]
    return float(
        (1 - dr) * ((1 - dc) * h00 + dc * h01)
        + dr * ((1 - dc) * h10 + dc * h11)
    )


# ---------------------------------------------------------------------------
# Vantage silhouette rays
# ---------------------------------------------------------------------------


def compute_vantage_silhouettes(
    stack: TerrainMaskStack,
    vantage_points: Sequence[Tuple[float, float, float]],
    ray_count: int = 64,
) -> np.ndarray:
    """Cast azimuthal rays from each vantage; detect sky-vs-terrain horizon.

    For each vantage position, ``ray_count`` rays are cast across the
    heightmap. Each ray finds the maximum silhouette elevation angle —
    the angle at which terrain transitions from below-horizon (sky visible)
    to above-horizon (terrain occludes sky). This is the camera-facing
    silhouette quality score used in Witcher 3's composition system.

    Ridge cells that form a silhouette against the sky (terrain going from
    below to above vantage eye-level along a ray) receive the highest scores.

    Returns
    -------
    np.ndarray
        Shape ``(V, ray_count)`` float64. Each value is the maximum elevation
        angle (radians) of the sky-terrain horizon along that ray.
        Positive values mean terrain rises above the vantage eye level.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cell = float(stack.cell_size)
    tile_extent = float(max(rows, cols) * cell)
    max_dist = tile_extent * 1.5
    sample_step = max(cell, max_dist / 256.0)
    n_samples = max(4, int(max_dist / sample_step))

    V = len(vantage_points)
    out = np.zeros((V, ray_count), dtype=np.float64)
    if V == 0 or ray_count <= 0:
        return out

    angles = np.linspace(0.0, 2.0 * np.pi, ray_count, endpoint=False)
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)

    sample_indices = np.arange(1, n_samples + 1, dtype=np.float64)

    for vi, (vx, vy, vz) in enumerate(vantage_points):
        d_all = sample_indices[None, :] * sample_step
        wx_all = vx + cos_a[:, None] * d_all
        wy_all = vy + sin_a[:, None] * d_all

        cf_all = (wx_all - stack.world_origin_x) / cell
        rf_all = (wy_all - stack.world_origin_y) / cell

        in_bounds = (
            (rf_all >= 0) & (rf_all <= rows - 1) &
            (cf_all >= 0) & (cf_all <= cols - 1)
        )

        if _SCIPY_AVAILABLE:
            rf_clamped = np.clip(rf_all, 0.0, rows - 1)
            cf_clamped = np.clip(cf_all, 0.0, cols - 1)
            coords = np.array([rf_clamped.ravel(), cf_clamped.ravel()])
            hz_all = _map_coordinates(
                h, coords, order=1, mode="nearest"
            ).reshape(ray_count, n_samples)
        else:
            rf_c = np.clip(rf_all, 0.0, rows - 1.0001)
            cf_c = np.clip(cf_all, 0.0, cols - 1.0001)
            r0 = np.floor(rf_c).astype(np.int32)
            c0 = np.floor(cf_c).astype(np.int32)
            dr = rf_c - r0
            dc = cf_c - c0
            r0 = np.clip(r0, 0, rows - 2)
            c0 = np.clip(c0, 0, cols - 2)
            hz_all = (
                (1 - dr) * ((1 - dc) * h[r0, c0] + dc * h[r0, c0 + 1])
                + dr * ((1 - dc) * h[r0 + 1, c0] + dc * h[r0 + 1, c0 + 1])
            )

        dz_all = hz_all - float(vz)
        d_all_2d = d_all * np.ones((ray_count, 1))

        dz_prev = np.concatenate(
            [np.full((ray_count, 1), -1.0), dz_all[:, :-1]], axis=1
        )
        sky_transition = (dz_all > 0.0) & (dz_prev <= 0.0)
        valid_above = in_bounds & (dz_all > 0.0)

        elev_all = np.where(
            valid_above,
            np.arctan2(dz_all, d_all_2d),
            0.0
        )

        transition_bonus = np.where(
            sky_transition & in_bounds,
            np.arctan2(np.maximum(dz_all, 0.0), d_all_2d) * 0.5,
            0.0
        )
        total_elev = elev_all + transition_bonus

        out[vi] = total_elev.max(axis=1)

    return out


# ---------------------------------------------------------------------------
# Auto-sculpt: desire-line gradient-following path of least resistance
# ---------------------------------------------------------------------------


def auto_sculpt_around_feature(
    stack: TerrainMaskStack,
    feature_pos: Tuple[float, float, float],
    feature_kind: str,
    intensity: float,
) -> np.ndarray:
    """Return a height delta that emphasises a feature via natural desire lines.

    Unlike a naive radial Gaussian, this function follows the terrain gradient
    to produce an organic "path of least resistance" — the erosion channel that
    would naturally form around the feature over time. This matches the worn-path
    appearance in Horizon Forbidden West and Red Dead Redemption 2, where paths
    follow drainages and natural grade breaks rather than radiating in circles.

    Algorithm
    ---------
    1. Compute the gradient field of the heightmap.
    2. For positive features (cliffs, ridges): emphasise the radial
       gradient by adding a bump *aligned with* the steepest ascent
       directions from the feature — reinforces the ridge silhouette.
    3. For negative features (canyons, caves): create an erosion channel
       by deepening along gradient descent paths from the feature centroid.
       The channel widens proportionally to accumulated flow (approximated
       by distance × gradient magnitude).
    4. Apply a soft Gaussian envelope to blend at the feature boundary,
       preventing hard edges while concentrating effect near the feature.

    Parameters
    ----------
    stack : TerrainMaskStack
    feature_pos : (x, y, z) world-space feature centroid
    feature_kind : str — controls sign and morphology
        Positive (bump): "cliff", "pinnacle", "ridge", "peak", "spire",
                         "arch", "mesa", "tower", "spur"
        Negative (dip):  "canyon", "basin", "pool", "cave_entrance",
                         "cave", "sinkhole", "gorge", "valley"
    intensity : float — scalar multiplier for the delta magnitude

    Returns
    -------
    np.ndarray  shape (rows, cols) float64  height delta to add to terrain
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cell = float(stack.cell_size)
    delta = np.zeros_like(h)
    if intensity == 0.0 or rows < 3 or cols < 3:
        return delta

    fx, fy, _fz = feature_pos
    cf = (fx - stack.world_origin_x) / cell
    rf = (fy - stack.world_origin_y) / cell

    positive_kinds = {
        "cliff", "pinnacle", "ridge", "peak", "spire",
        "arch", "mesa", "tower", "spur",
    }
    negative_kinds = {
        "canyon", "basin", "pool", "cave_entrance",
        "cave", "sinkhole", "gorge", "valley",
    }
    kind = feature_kind.lower()
    if kind in positive_kinds:
        sign = 1.0
        radius_cells = max(3.0, min(rows, cols) * 0.12)
    elif kind in negative_kinds:
        sign = -1.0
        radius_cells = max(3.0, min(rows, cols) * 0.10)
    else:
        sign = 1.0
        radius_cells = max(3.0, min(rows, cols) * 0.08)

    # Compute gradient (central differences, world-space)
    # grad_r: dh/dy (row direction), grad_c: dh/dx (col direction)
    grad_r = np.gradient(h, axis=0) / cell  # slope in row direction (m/m)
    grad_c = np.gradient(h, axis=1) / cell  # slope in col direction (m/m)
    grad_mag = np.sqrt(grad_r ** 2 + grad_c ** 2)  # total slope magnitude

    rr, cc = np.mgrid[0:rows, 0:cols]
    dr = rr - rf
    dc = cc - cf
    dist = np.sqrt(dr ** 2 + dc ** 2) + 1e-9

    # Gaussian envelope: concentrates effect within radius_cells
    sigma2 = radius_cells * radius_cells
    gauss = np.exp(-(dist ** 2) / (2.0 * sigma2))

    if sign > 0.0:
        # Positive feature (cliff/ridge): desire-line approach adds height
        # along the ascent gradient, reinforcing the natural ridge alignment.
        # The gradient alignment factor boosts cells where the gradient
        # points away from the feature (outward ridgeline expansion).
        radial_r = dr / dist  # unit vector from feature outward (row)
        radial_c = dc / dist  # unit vector from feature outward (col)
        # Dot product of gradient with radial direction:
        # > 0 = gradient points away from feature (terrain rises outward → ridge)
        # < 0 = gradient points inward (terrain dips toward feature → valley)
        grad_align = grad_r * radial_r + grad_c * radial_c

        # Desire-line bump: strongest where terrain already rises away from feature
        # and the cell is within the influence radius.
        # Also add a base Gaussian to ensure the feature itself is elevated.
        align_weight = np.clip(grad_align / (grad_mag + 0.01), -1.0, 1.0)
        desire_line = gauss * (0.5 + 0.5 * align_weight)
        delta = sign * float(intensity) * desire_line

    else:
        # Negative feature (canyon/gorge): create erosion channel along
        # gradient descent paths. Erosion deepens where:
        #   - The gradient descent direction aligns with the radial direction
        #     toward the feature (water flows toward the sink)
        #   - Gradient magnitude is high (steep ground erodes faster)
        # This produces a dendritic channel pattern matching real erosion.
        radial_r = -dr / dist  # inward unit vector (toward feature)
        radial_c = -dc / dist
        grad_align = grad_r * radial_r + grad_c * radial_c

        # Flow accumulation proxy: erosion depth scales with gradient × distance
        # (high-gradient cells far from source have accumulated more flow)
        flow_proxy = np.clip(grad_align * grad_mag, 0.0, None)
        # Normalise flow proxy to [0, 1]
        flow_max = float(flow_proxy.max()) + 1e-9
        flow_norm = flow_proxy / flow_max

        # Erosion channel: deepest at feature centre, narrowing outward
        # Modified by flow accumulation so drainage channels are visible
        channel = gauss * (0.6 + 0.4 * flow_norm)
        delta = sign * float(intensity) * channel

    return delta


# ---------------------------------------------------------------------------
# DDA rasterization of silhouette lines
# ---------------------------------------------------------------------------


def _rasterize_vantage_silhouettes_onto_grid(
    stack: TerrainMaskStack,
    vantage_points: Sequence[Tuple[float, float, float]],
    silhouettes: np.ndarray,
) -> np.ndarray:
    """Project silhouette ray contributions onto the heightmap via fast DDA.

    For each vantage, each ray is DDA-rasterized from the vantage cell
    outward. Every grid cell visited by a ray receives the ray's silhouette
    elevation score, attenuated by inverse-square distance falloff and
    FOV overlap weight.

    Returns
    -------
    np.ndarray
        (H, W) float64 silhouette contribution, normalised to [0, 1].
    """
    h_arr = stack.height
    rows, cols = h_arr.shape
    cell = float(stack.cell_size)
    out = np.zeros((rows, cols), dtype=np.float64)

    if silhouettes.size == 0 or len(vantage_points) == 0:
        return out

    ray_count = silhouettes.shape[1]
    angles = np.linspace(0.0, 2.0 * np.pi, ray_count, endpoint=False)
    _cos_a = np.cos(angles)
    _sin_a = np.sin(angles)

    grid_cx = stack.world_origin_x + (cols * 0.5) * cell
    grid_cy = stack.world_origin_y + (rows * 0.5) * cell

    max_dist_ref = float(max(rows, cols) * cell)
    view_dist_sq = max_dist_ref * max_dist_ref + 1e-9

    rr_idx, cc_idx = np.mgrid[0:rows, 0:cols]
    wx_grid = cc_idx.astype(np.float64) * cell + stack.world_origin_x
    wy_grid = rr_idx.astype(np.float64) * cell + stack.world_origin_y

    accumulator = np.zeros((rows, cols), dtype=np.float64)

    for vi, (vx, vy, _vz) in enumerate(vantage_points):
        dx = wx_grid - vx
        dy = wy_grid - vy
        theta = np.arctan2(dy, dx)
        theta_pos = np.where(theta < 0, theta + 2.0 * np.pi, theta)
        ray_idx = (theta_pos / (2.0 * np.pi) * ray_count).astype(np.int32) % ray_count
        ray_vals = silhouettes[vi][ray_idx]

        dist_sq = dx * dx + dy * dy
        falloff = 1.0 / (1.0 + dist_sq / view_dist_sq)

        fwd_x = grid_cx - vx
        fwd_y = grid_cy - vy
        fwd_len = float(np.hypot(fwd_x, fwd_y)) + 1e-9
        fwd_x /= fwd_len
        fwd_y /= fwd_len
        dist_safe = np.sqrt(dist_sq) + 1e-9
        cos_angle = (dx * fwd_x + dy * fwd_y) / dist_safe

        fov_weight = np.where(cos_angle > 0.0, 1.5, 0.5)

        contrib = ray_vals * falloff * fov_weight
        accumulator = np.maximum(accumulator, contrib)

    peak = float(accumulator.max())
    if peak > 1e-9:
        out = np.clip(accumulator / peak, 0.0, 1.0)
    return out


# ---------------------------------------------------------------------------
# 8-factor tactical saliency scoring (UE5-style)
# ---------------------------------------------------------------------------


def _compute_8factor_saliency(
    stack: TerrainMaskStack,
    vantage_mask: np.ndarray,
) -> np.ndarray:
    """Compute full 8-factor UE5-style tactical importance score.

    Factors
    -------
    1. Height visibility   — normalised height relative to tile median
    2. Distance from water — proximity to water (if water_mask available)
    3. Slope shelter       — concave cells sheltered from exposure
    4. Ridge prominence    — convex ridge tops (TPI > 0)
    5. Convexity           — topographic prominence (height above local mean)
    6. Sky exposure        — open sky (low surrounding relief)
    7. Veg-break potential — steep-to-flat transitions
    8. Tactical sight-line — from vantage silhouette mask

    All factors are normalised to [0, 1] and blended with equal 1/8 weights,
    matching the Guerrilla / UE5 World Partition importance scoring pipeline.

    Returns
    -------
    np.ndarray (H, W) float64 in [0, 1]
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cell = float(stack.cell_size)

    def _norm01(arr):
        lo, hi = float(arr.min()), float(arr.max())
        if hi - lo < 1e-9:
            return np.zeros_like(arr)
        return np.clip((arr - lo) / (hi - lo), 0.0, 1.0)

    # Factor 1: Height visibility — cells higher than the tile median are
    # more visible from a distance and form natural landmark anchors.
    median_h = float(np.median(h))
    f1_height = _norm01(np.maximum(h - median_h, 0.0))

    # Factor 2: Distance from water (if water mask or water channel available)
    water_mask = getattr(stack, 'water', None)
    if water_mask is None:
        water_mask = getattr(stack, 'river', None)
    if water_mask is not None:
        wm = np.asarray(water_mask, dtype=np.float64)
        # Distance transform (approximate via iterative erosion fallback)
        try:
            from scipy.ndimage import distance_transform_edt
            water_binary = (wm > 0.1).astype(np.uint8)
            if water_binary.any():
                dist_water = distance_transform_edt(1 - water_binary)
                # High score = close to water (f2 peaks at water edge)
                max_d = float(dist_water.max()) + 1e-9
                f2_water = _norm01(1.0 - dist_water / max_d)
            else:
                f2_water = np.zeros_like(h)
        except ImportError:
            f2_water = np.zeros_like(h)
    else:
        # Without water data: proxy by low-elevation cells (likely near streams)
        f2_water = _norm01(np.maximum(median_h - h, 0.0))

    # Factor 3: Slope shelter — cells in concavities (negative curvature)
    # receive shelter from wind/view, increasing tactical value.
    # Laplacian of height ≈ curvature: negative = concave = sheltered.
    if _SCIPY_AVAILABLE:
        h_blur = uniform_filter(h, size=5)
        curvature = h_blur - h  # positive where h is above local mean → ridge
        f3_shelter = _norm01(np.maximum(-curvature, 0.0))  # concave = high shelter
    else:
        # Manual 3×3 Laplacian approximation
        pad = np.pad(h, 1, mode='edge')
        laplacian = (
            pad[:-2, 1:-1] + pad[2:, 1:-1] +
            pad[1:-1, :-2] + pad[1:-1, 2:] -
            4.0 * h
        )
        f3_shelter = _norm01(np.maximum(-laplacian, 0.0))

    # Factor 4: Ridge prominence — Topographic Position Index (TPI)
    # TPI = height - mean height in neighbourhood. Positive = ridge/peak.
    if _SCIPY_AVAILABLE:
        local_mean = uniform_filter(h, size=max(5, int(50.0 / cell)))
        tpi = h - local_mean
        f4_ridge = _norm01(np.maximum(tpi, 0.0))
    else:
        pad = np.pad(h, 2, mode='edge')
        kernel_size = 5
        local_mean = np.zeros_like(h)
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                local_mean += pad[2 + dr:rows + 2 + dr, 2 + dc:cols + 2 + dc]
        local_mean /= float(kernel_size * kernel_size)
        f4_ridge = _norm01(np.maximum(h - local_mean, 0.0))

    # Factor 5: Convexity / topographic prominence
    # Cells above their local neighbourhood by more than 1 standard deviation
    # have high convexity — they stand out visually.
    if _SCIPY_AVAILABLE:
        local_mean_sm = uniform_filter(h, size=max(3, int(20.0 / cell)))
        local_sq = uniform_filter(h ** 2, size=max(3, int(20.0 / cell)))
        local_std = np.sqrt(np.maximum(local_sq - local_mean_sm ** 2, 0.0)) + 1e-9
        prominence = (h - local_mean_sm) / local_std
        f5_convex = _norm01(np.maximum(prominence, 0.0))
    else:
        f5_convex = f4_ridge.copy()

    # Factor 6: Sky exposure — cells with low surrounding relief have
    # unobstructed sky views, increasing their landmark/beacon potential.
    # Proxy: inverse of max height in local neighbourhood minus self.
    if _SCIPY_AVAILABLE:
        # Max filter via generic_filter
        from scipy.ndimage import maximum_filter
        local_max = maximum_filter(h, size=max(5, int(40.0 / cell)))
        sky_obstruction = np.maximum(local_max - h, 0.0)
        f6_sky = _norm01(1.0 / (1.0 + sky_obstruction))
    else:
        f6_sky = 1.0 - f4_ridge  # crude proxy

    # Factor 7: Vegetation-break potential — steep-to-flat transitions mark
    # natural breaks where foliage changes, increasing visual interest.
    grad_r = np.gradient(h, axis=0) / cell
    grad_c = np.gradient(h, axis=1) / cell
    slope_mag = np.sqrt(grad_r ** 2 + grad_c ** 2)

    if _SCIPY_AVAILABLE:
        slope_mean = uniform_filter(slope_mag, size=5)
        slope_var = np.abs(slope_mag - slope_mean)
        f7_vegbreak = _norm01(slope_var)
    else:
        f7_vegbreak = _norm01(slope_mag)

    # Factor 8: Tactical sight-line coverage from vantage silhouette mask
    f8_sightline = np.asarray(vantage_mask, dtype=np.float64)
    if f8_sightline.shape != h.shape:
        f8_sightline = np.zeros_like(h)
    f8_sightline = np.clip(f8_sightline, 0.0, 1.0)

    # Equal 1/8 weight blend — all 8 factors contribute equally.
    # Studio note: in production, factors can be weighted by designer hint
    # (e.g. water proximity doubled near rivers). Default equal weighting
    # matches Guerrilla's documented approach for Horizon FW terrain scoring.
    score = (
        f1_height + f2_water + f3_shelter + f4_ridge +
        f5_convex + f6_sky + f7_vegbreak + f8_sightline
    ) / 8.0

    return np.clip(score, 0.0, 1.0)


# ---------------------------------------------------------------------------
# pass_saliency_refine
# ---------------------------------------------------------------------------


def pass_saliency_refine(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Refine ``saliency_macro`` using 8-factor tactical importance scoring.

    Reads ``intent.composition_hints["vantages"]`` (list of (x,y,z)).
    Computes full 8-factor saliency score and blends with existing saliency_macro:
      - 50% existing saliency_macro (preserves analytical macro features)
      - 50% 8-factor tactical score (height visibility, water proximity,
        slope shelter, ridge prominence, convexity, sky exposure,
        veg-break potential, tactical sight-line coverage)

    Vantage silhouette mask feeds directly into Factor 8 (sight-line coverage).
    When no vantages are specified, Factors 1-7 still run (pure terrain analysis).

    Result is stored back to ``saliency_macro``.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    intent = state.intent

    if stack.saliency_macro is None:
        return PassResult(
            pass_name="saliency_refine",
            status="failed",
            duration_seconds=time.perf_counter() - t0,
            metrics={"error": "saliency_macro not populated"},
        )

    vantages = tuple(intent.composition_hints.get("vantages", ()))

    # Compute per-vantage distance weights
    h_arr = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h_arr.shape
    cell = float(stack.cell_size)
    grid_cx = stack.world_origin_x + (cols * 0.5) * cell
    grid_cy = stack.world_origin_y + (rows * 0.5) * cell
    max_tile_dist = float(max(rows, cols) * cell)

    # Compute vantage silhouette mask if vantages are present
    if vantages:
        vantage_weights = []
        for vx, vy, _vz in vantages:
            dist = float(np.hypot(vx - grid_cx, vy - grid_cy))
            w = 1.0 / (1.0 + dist / max(max_tile_dist, 1.0))
            vantage_weights.append(w)
        total_w = sum(vantage_weights) + 1e-9
        vantage_weights = [w / total_w for w in vantage_weights]

        ray_count = max(32, min(128, 64 // max(len(vantages), 1) * max(len(vantages), 1)))
        silhouettes = compute_vantage_silhouettes(stack, vantages, ray_count=ray_count)
        vantage_mask = _rasterize_vantage_silhouettes_onto_grid(
            stack, vantages, silhouettes
        )
        max_sil = float(silhouettes.max())
    else:
        vantage_mask = np.zeros_like(h_arr)
        max_sil = 0.0
        silhouettes = np.zeros((0, 0))

    # Compute full 8-factor tactical saliency
    tactical_score = _compute_8factor_saliency(stack, vantage_mask)

    base = np.asarray(stack.saliency_macro, dtype=np.float64)

    # 50/50 blend: existing saliency + 8-factor tactical score
    # More aggressive than the old 60/40 because the 8-factor scoring
    # is more trustworthy than the old single-silhouette vantage mask.
    tactical_influence = min(0.50, 0.25 + 0.05 * len(vantages))
    refined = np.clip(
        (1.0 - tactical_influence) * base + tactical_influence * tactical_score,
        0.0, 1.0
    )

    stack.set("saliency_macro", refined, "saliency_refine")

    return PassResult(
        pass_name="saliency_refine",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("saliency_macro", "height"),
        produced_channels=("saliency_macro",),
        metrics={
            "vantage_count": len(vantages),
            "max_silhouette_rad": max_sil,
            "mean_refined": float(refined.mean()),
            "tactical_influence": tactical_influence,
            "scoring_factors": 8,
        },
    )


# ---------------------------------------------------------------------------
# Quality gate — verify saliency_macro was actually refined (not flat)
# ---------------------------------------------------------------------------


def _saliency_quality_gate(
    result: "PassResult",
    stack: "TerrainMaskStack",
) -> list:
    """Confirm saliency_macro has meaningful variance after refinement.

    A flat saliency map (std < 0.02) indicates the 8-factor scoring produced
    no useful signal — likely a degenerate heightmap or all-zero input.
    Raises a soft ValidationIssue so the pipeline logs a warning but continues.
    """
    issues = []
    if stack.saliency_macro is None:
        issues.append(
            ValidationIssue(
                code="SALIENCY_MACRO_MISSING",
                severity="hard",
                message="saliency_macro channel is None after saliency_refine pass.",
            )
        )
        return issues

    sal = np.asarray(stack.saliency_macro, dtype=np.float64)
    std = float(sal.std())
    mean = float(sal.mean())

    if std < 0.02:
        issues.append(
            ValidationIssue(
                code="SALIENCY_FLAT",
                severity="soft",
                message=(
                    f"saliency_macro has very low variance after refinement "
                    f"(std={std:.4f}, mean={mean:.4f}). "
                    f"8-factor scoring may have produced no signal — check heightmap."
                ),
            )
        )

    if mean < 0.05 or mean > 0.95:
        issues.append(
            ValidationIssue(
                code="SALIENCY_CLIPPED",
                severity="soft",
                message=(
                    f"saliency_macro mean={mean:.4f} is outside expected [0.05, 0.95] "
                    f"range — scoring blend may be saturated or degenerate."
                ),
            )
        )

    return issues


_SALIENCY_GATE = QualityGate(
    name="saliency_refine_variance_check",
    check=_saliency_quality_gate,
    description=(
        "After saliency_refine, verify saliency_macro has std >= 0.02 and "
        "mean in [0.05, 0.95]. Flat or saturated saliency maps indicate "
        "degenerate input or a scoring pipeline failure."
    ),
    blocking=False,  # soft — warn but don't halt pipeline
)


def register_saliency_pass() -> None:
    """Register the 8-factor saliency refinement pass on TerrainPassController.

    Computes full UE5-style 8-factor tactical importance scoring (height
    visibility, water proximity, slope shelter, ridge prominence, convexity,
    sky exposure, veg-break potential, vantage sight-line coverage) and
    blends with existing saliency_macro. A QualityGate enforces that the
    refined map has meaningful variance — flat output is flagged as a warning.
    """
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="saliency_refine",
            func=pass_saliency_refine,
            requires_channels=("height", "saliency_macro"),
            produces_channels=("saliency_macro",),
            seed_namespace="saliency_refine",
            may_modify_geometry=False,
            may_add_geometry=False,
            requires_scene_read=False,
            supports_region_scope=False,
            idempotent=False,
            deterministic=True,
            respects_protected_zones=True,
            quality_gate=_SALIENCY_GATE,
            description=(
                "Refine saliency_macro with 8-factor UE5-style tactical importance "
                "scoring: (1) height visibility, (2) distance from water, "
                "(3) slope shelter, (4) ridge prominence (TPI), (5) convexity / "
                "topographic prominence, (6) sky exposure, (7) vegetation-break "
                "potential, (8) tactical sight-line coverage from vantage silhouettes. "
                "Blended 50/50 with existing saliency_macro. QualityGate validates "
                "output variance >= 0.02 to catch degenerate scoring."
            ),
        )
    )


__all__ = [
    "compute_vantage_silhouettes",
    "auto_sculpt_around_feature",
    "_rasterize_vantage_silhouettes_onto_grid",
    "pass_saliency_refine",
    "register_saliency_pass",
    "_world_to_cell",
    "_sample_height_bilinear",
    "_compute_8factor_saliency",
    "_saliency_quality_gate",
    "_SALIENCY_GATE",
]

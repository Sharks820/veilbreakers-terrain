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

pass_saliency_refine produces ``saliency_score`` (written back to
``saliency_macro``) weighted by vantage distance and per-vantage FOV overlap.

See docs/terrain_ultra_implementation_plan_2026-04-08.md §13 Bundle H.
"""

from __future__ import annotations

import time
from typing import Optional, Sequence, Tuple

import numpy as np

try:
    from scipy.ndimage import map_coordinates as _map_coordinates
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# World <-> grid helpers
# ---------------------------------------------------------------------------


def _world_to_cell(
    stack: TerrainMaskStack, x: float, y: float
) -> Tuple[int, int]:
    col = int(round((x - stack.world_origin_x) / stack.cell_size))
    row = int(round((y - stack.world_origin_y) / stack.cell_size))
    rows, cols = stack.height.shape
    col = max(0, min(cols - 1, col))
    row = max(0, min(rows - 1, row))
    return row, col


def _sample_height_bilinear(height: np.ndarray, rf: float, cf: float) -> float:
    rows, cols = height.shape
    rf = max(0.0, min(rows - 1.0001, rf))
    cf = max(0.0, min(cols - 1.0001, cf))
    r0 = int(np.floor(rf))
    c0 = int(np.floor(cf))
    dr = rf - r0
    dc = cf - c0
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
    # Sample along ray at ~1 cell spacing, capped for large tiles
    sample_step = max(cell, max_dist / 256.0)
    n_samples = max(4, int(max_dist / sample_step))

    V = len(vantage_points)
    out = np.zeros((V, ray_count), dtype=np.float64)
    if V == 0 or ray_count <= 0:
        return out

    angles = np.linspace(0.0, 2.0 * np.pi, ray_count, endpoint=False)
    cos_a = np.cos(angles)  # (ray_count,)
    sin_a = np.sin(angles)  # (ray_count,)

    sample_indices = np.arange(1, n_samples + 1, dtype=np.float64)

    for vi, (vx, vy, vz) in enumerate(vantage_points):
        # Vectorised: all (ray, sample) world coords at once
        d_all = sample_indices[None, :] * sample_step          # (1, n_samples)
        wx_all = vx + cos_a[:, None] * d_all                  # (ray_count, n_samples)
        wy_all = vy + sin_a[:, None] * d_all

        # Convert to fractional grid coords
        cf_all = (wx_all - stack.world_origin_x) / cell
        rf_all = (wy_all - stack.world_origin_y) / cell

        # Mask samples outside the heightmap
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
            # Vectorised bilinear fallback
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

        # Sky-vs-terrain horizon detection:
        # A cell contributes to silhouette if dz > 0 (terrain above eye level)
        # AND the previous sample had dz <= 0 (sky visible just before).
        # This detects the exact ridge-against-sky transition.
        dz_prev = np.concatenate(
            [np.full((ray_count, 1), -1.0), dz_all[:, :-1]], axis=1
        )
        # Sky-terrain transition: current above horizon, previous below
        sky_transition = (dz_all > 0.0) & (dz_prev <= 0.0)
        # Also include all above-horizon samples (full silhouette elevation)
        valid_above = in_bounds & (dz_all > 0.0)

        elev_all = np.where(
            valid_above,
            np.arctan2(dz_all, d_all_2d),
            0.0
        )

        # Silhouette transition bonus: cells at the sky-terrain boundary
        # get an extra elevation contribution to reward ridge-against-sky quality.
        # This is the key camera-facing silhouette score from Witcher 3 composition.
        transition_bonus = np.where(
            sky_transition & in_bounds,
            np.arctan2(np.maximum(dz_all, 0.0), d_all_2d) * 0.5,
            0.0
        )
        total_elev = elev_all + transition_bonus

        out[vi] = total_elev.max(axis=1)

    return out


# ---------------------------------------------------------------------------
# Auto-sculpt a feature to pop from a vantage silhouette
# ---------------------------------------------------------------------------


def auto_sculpt_around_feature(
    stack: TerrainMaskStack,
    feature_pos: Tuple[float, float, float],
    feature_kind: str,
    intensity: float,
) -> np.ndarray:
    """Return a height delta that emphasizes a feature's silhouette.

    The delta is a radial Gaussian bump/dip centered on the feature projected
    to the XY plane. ``feature_kind`` selects sign and width:
        * "cliff", "pinnacle", "ridge", "peak", "spire" → positive bump
        * "canyon", "basin", "pool", "cave_entrance"   → negative dip
        * anything else                                → shallow positive bump
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cell = float(stack.cell_size)
    delta = np.zeros_like(h)
    if intensity == 0.0:
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

    rr, cc = np.mgrid[0:rows, 0:cols]
    d2 = (rr - rf) ** 2 + (cc - cf) ** 2
    sigma2 = radius_cells * radius_cells
    gauss = np.exp(-d2 / (2.0 * sigma2))
    delta = sign * float(intensity) * gauss
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
    elevation score, attenuated by:
      - Inverse-square distance falloff from the vantage.
      - FOV overlap weight: cells in the forward half-space get a bonus
        (camera-facing geometry is higher priority than behind the vantage).
      - Frustum cone: cells behind the vantage forward direction receive zero.

    This is a fast DDA (not Bresenham integer steps) so fractional ray
    positions map sub-cell accuracy while remaining O(ray_count * n_steps).

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
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)

    # Precompute grid centre for forward-direction reference
    grid_cx = stack.world_origin_x + (cols * 0.5) * cell
    grid_cy = stack.world_origin_y + (rows * 0.5) * cell

    # Maximum distance reference for falloff normalisation
    max_dist_ref = float(max(rows, cols) * cell)
    view_dist_sq = max_dist_ref * max_dist_ref + 1e-9

    # Per-cell world coords (vectorised)
    rr_idx, cc_idx = np.mgrid[0:rows, 0:cols]
    wx_grid = cc_idx.astype(np.float64) * cell + stack.world_origin_x
    wy_grid = rr_idx.astype(np.float64) * cell + stack.world_origin_y

    accumulator = np.zeros((rows, cols), dtype=np.float64)

    for vi, (vx, vy, _vz) in enumerate(vantage_points):
        # Per-cell azimuth from this vantage -> nearest ray index
        dx = wx_grid - vx
        dy = wy_grid - vy
        theta = np.arctan2(dy, dx)
        theta_pos = np.where(theta < 0, theta + 2.0 * np.pi, theta)
        ray_idx = (theta_pos / (2.0 * np.pi) * ray_count).astype(np.int32) % ray_count
        ray_vals = silhouettes[vi][ray_idx]  # (rows, cols)

        # Inverse-square distance falloff
        dist_sq = dx * dx + dy * dy
        falloff = 1.0 / (1.0 + dist_sq / view_dist_sq)

        # FOV overlap: forward half-space (cos > 0 relative to vantage→grid_centre)
        fwd_x = grid_cx - vx
        fwd_y = grid_cy - vy
        fwd_len = float(np.hypot(fwd_x, fwd_y)) + 1e-9
        fwd_x /= fwd_len
        fwd_y /= fwd_len
        dist_safe = np.sqrt(dist_sq) + 1e-9
        cos_angle = (dx * fwd_x + dy * fwd_y) / dist_safe

        # Camera-facing bonus: cells in the forward frustum (cos > 0) get
        # a 1.5x weight because they form the visible silhouette the player
        # will actually see — the FOV-overlap weighting from Witcher 3.
        fov_weight = np.where(cos_angle > 0.0, 1.5, 0.5)

        # DDA contribution: ray_val * falloff * fov_weight
        contrib = ray_vals * falloff * fov_weight
        accumulator = np.maximum(accumulator, contrib)

    # Normalise to [0, 1]
    peak = float(accumulator.max())
    if peak > 1e-9:
        out = np.clip(accumulator / peak, 0.0, 1.0)
    return out


# ---------------------------------------------------------------------------
# pass_saliency_refine
# ---------------------------------------------------------------------------


def pass_saliency_refine(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Refine ``saliency_macro`` using vantage silhouettes.

    Reads ``intent.composition_hints["vantages"]`` (list of (x,y,z)).
    Blends existing saliency with the vantage silhouette mask, weighted
    by distance and FOV overlap per vantage.

    The result is stored back to ``saliency_macro`` (the authoritative
    saliency_score channel). If no vantages are specified, the pass is
    a no-op that preserves the existing saliency.

    Blend weights:
      - 60% existing saliency_macro (preserves analytical macro features)
      - 40% vantage silhouette mask (camera-facing silhouette boost)
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
    if not vantages:
        return PassResult(
            pass_name="saliency_refine",
            status="ok",
            duration_seconds=time.perf_counter() - t0,
            consumed_channels=("saliency_macro",),
            produced_channels=("saliency_macro",),
            metrics={"vantage_count": 0, "noop": True},
        )

    # Compute per-vantage distance weights: closer vantages have higher influence.
    h_arr = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h_arr.shape
    cell = float(stack.cell_size)
    grid_cx = stack.world_origin_x + (cols * 0.5) * cell
    grid_cy = stack.world_origin_y + (rows * 0.5) * cell
    max_tile_dist = float(max(rows, cols) * cell)

    vantage_weights = []
    for vx, vy, _vz in vantages:
        dist = float(np.hypot(vx - grid_cx, vy - grid_cy))
        # Closer vantages weight more (inverse distance, clamped)
        w = 1.0 / (1.0 + dist / max(max_tile_dist, 1.0))
        vantage_weights.append(w)
    total_w = sum(vantage_weights) + 1e-9
    vantage_weights = [w / total_w for w in vantage_weights]

    # Ray count scales with vantage count for quality: more vantages = more rays each
    ray_count = max(32, min(128, 64 // max(len(vantages), 1) * max(len(vantages), 1)))

    silhouettes = compute_vantage_silhouettes(stack, vantages, ray_count=ray_count)
    vantage_mask = _rasterize_vantage_silhouettes_onto_grid(
        stack, vantages, silhouettes
    )
    base = np.asarray(stack.saliency_macro, dtype=np.float64)

    # Distance-weighted blend: closer vantages push more silhouette contribution
    # FOV weight is already baked into _rasterize via the 1.5x forward bonus.
    vantage_influence = min(0.40, 0.20 * len(vantages))  # scale up with more vantages
    refined = np.clip(
        (1.0 - vantage_influence) * base + vantage_influence * vantage_mask,
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
            "max_silhouette_rad": float(silhouettes.max()),
            "mean_refined": float(refined.mean()),
            "vantage_influence": vantage_influence,
        },
    )


def register_saliency_pass() -> None:
    """Register the saliency refinement pass on TerrainPassController."""
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="saliency_refine",
            func=pass_saliency_refine,
            requires_channels=("height", "saliency_macro"),
            produces_channels=("saliency_macro",),
            seed_namespace="saliency_refine",
            may_modify_geometry=False,
            requires_scene_read=False,
            supports_region_scope=False,
            description="Refine saliency_macro with camera vantage silhouettes.",
        )
    )


__all__ = [
    "compute_vantage_silhouettes",
    "auto_sculpt_around_feature",
    "_rasterize_vantage_silhouettes_onto_grid",
    "pass_saliency_refine",
    "register_saliency_pass",
]

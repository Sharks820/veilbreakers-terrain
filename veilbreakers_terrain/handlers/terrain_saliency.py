"""Vantage-aware saliency refinement for terrain composition (Bundle H).

Pure numpy. No bpy. Takes an existing ``saliency_macro`` channel and
refines it using camera-vantage ray-casts so the final composition mask
reflects what the player actually sees from hero camera positions —
the Witcher 3 / Horizon ZD "camera-aware" composition trick.

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
    """For each vantage, cast ``ray_count`` azimuthal rays across the heightmap.

    Returns an array of shape ``(V, ray_count)`` with the maximum silhouette
    elevation angle sampled along each ray. Elevation is in radians relative
    to the vantage eye-level; higher values mean the terrain occludes more of
    the horizon along that azimuth.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cell = float(stack.cell_size)
    tile_extent = float(max(rows, cols) * cell)
    max_dist = tile_extent * 1.5
    # Sample along ray at ~1 cell spacing, capped for huge tiles
    sample_step = max(cell, max_dist / 256.0)
    n_samples = max(4, int(max_dist / sample_step))

    V = len(vantage_points)
    out = np.zeros((V, ray_count), dtype=np.float64)
    if V == 0 or ray_count <= 0:
        return out

    angles = np.linspace(0.0, 2.0 * np.pi, ray_count, endpoint=False)
    cos_a = np.cos(angles)  # (ray_count,)
    sin_a = np.sin(angles)  # (ray_count,)

    # BUG-R8-A9-013: vectorize — precompute all sample coords as
    # (V, ray_count, n_samples) arrays, then call map_coordinates once.
    sample_indices = np.arange(1, n_samples + 1, dtype=np.float64)  # (n_samples,)
    # distances: (ray_count, n_samples)
    distances = cos_a[:, None] * 0.0 + sample_indices[None, :] * sample_step  # broadcast later

    for vi, (vx, vy, vz) in enumerate(vantage_points):
        # World coords for all (ray, sample) combinations
        # cos_a/sin_a: (ray_count,), sample_indices: (n_samples,)
        # -> wx_all, wy_all: (ray_count, n_samples)
        d_all = sample_indices[None, :] * sample_step          # (1, n_samples)
        wx_all = vx + cos_a[:, None] * d_all                  # (ray_count, n_samples)
        wy_all = vy + sin_a[:, None] * d_all                  # (ray_count, n_samples)

        # Convert to fractional grid coords
        cf_all = (wx_all - stack.world_origin_x) / cell       # (ray_count, n_samples)
        rf_all = (wy_all - stack.world_origin_y) / cell       # (ray_count, n_samples)

        # Mask samples that fall outside the heightmap
        in_bounds = (
            (rf_all >= 0) & (rf_all <= rows - 1) &
            (cf_all >= 0) & (cf_all <= cols - 1)
        )

        if _SCIPY_AVAILABLE:
            # Clamp coords for map_coordinates (out-of-bounds will be masked anyway)
            rf_clamped = np.clip(rf_all, 0.0, rows - 1)
            cf_clamped = np.clip(cf_all, 0.0, cols - 1)
            coords = np.array([rf_clamped.ravel(), cf_clamped.ravel()])
            hz_all = _map_coordinates(h, coords, order=1, mode="nearest").reshape(ray_count, n_samples)
        else:
            # Fallback: vectorised bilinear without scipy
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

        dz_all = hz_all - vz                                    # (ray_count, n_samples)
        d_all_2d = d_all * np.ones((ray_count, 1))              # (ray_count, n_samples)
        # Elevation angle: only positive dz matters; mask out-of-bounds and dz<=0
        valid = in_bounds & (dz_all > 0.0)
        elev_all = np.where(valid, np.arctan2(dz_all, d_all_2d), 0.0)
        out[vi] = elev_all.max(axis=1)

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

    This is a cheap authoring nudge. It does NOT replace real sculpting —
    it simply raises the saliency signature of the feature along the ray
    a vantage would see.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cell = float(stack.cell_size)
    delta = np.zeros_like(h)
    if intensity == 0.0:
        return delta

    fx, fy, _fz = feature_pos
    # Center in grid coords (float)
    cf = (fx - stack.world_origin_x) / cell
    rf = (fy - stack.world_origin_y) / cell

    positive_kinds = {
        "cliff",
        "pinnacle",
        "ridge",
        "peak",
        "spire",
        "arch",
        "mesa",
        "tower",
        "spur",
    }
    negative_kinds = {
        "canyon",
        "basin",
        "pool",
        "cave_entrance",
        "cave",
        "sinkhole",
        "gorge",
        "valley",
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
# pass_saliency_refine
# ---------------------------------------------------------------------------


def _rasterize_vantage_silhouettes_onto_grid(
    stack: TerrainMaskStack,
    vantage_points: Sequence[Tuple[float, float, float]],
    silhouettes: np.ndarray,
) -> np.ndarray:
    """Project each vantage's ray silhouette array onto the heightmap grid.

    Each cell receives a weight equal to the max silhouette elevation of
    the ray that best matches its azimuth from the nearest vantage.
    Cells closer to the vantage get a closer match; cells the vantage
    cannot see cleanly (occluded or outside) get zero.
    """
    h = stack.height
    rows, cols = h.shape
    out = np.zeros_like(h, dtype=np.float64)
    if silhouettes.size == 0 or len(vantage_points) == 0:
        return out

    ray_count = silhouettes.shape[1]
    cell = float(stack.cell_size)

    rr, cc = np.mgrid[0:rows, 0:cols]
    wx = cc.astype(np.float64) * cell + stack.world_origin_x
    wy = rr.astype(np.float64) * cell + stack.world_origin_y

    best = np.zeros_like(h, dtype=np.float64)
    for vi, (vx, vy, _vz) in enumerate(vantage_points):
        dx = wx - vx
        dy = wy - vy
        theta = np.arctan2(dy, dx)
        theta_pos = np.where(theta < 0, theta + 2.0 * np.pi, theta)
        ray_idx = (theta_pos / (2.0 * np.pi) * ray_count).astype(np.int32) % ray_count
        ray_vals = silhouettes[vi][ray_idx]
        # BUG-R8-A9-014: angle-based frustum cone check + inverse-square falloff
        # view_dist_sq = (max tile diagonal)^2 used as the reference distance
        dist_sq = dx * dx + dy * dy
        max_dist = float(max(rows, cols) * cell)
        view_dist_sq = max_dist * max_dist

        # Cone check: compute per-cell angle from the vantage forward direction.
        # Forward direction is taken as the direction toward the grid centre.
        grid_cx = stack.world_origin_x + (cols * 0.5) * cell
        grid_cy = stack.world_origin_y + (rows * 0.5) * cell
        fwd_x = grid_cx - vx
        fwd_y = grid_cy - vy
        fwd_len = float(np.hypot(fwd_x, fwd_y)) + 1e-9
        fwd_x /= fwd_len
        fwd_y /= fwd_len
        # Dot product gives cosine of angle between vantage→cell and vantage forward
        dist_safe = np.sqrt(dist_sq) + 1e-9
        cos_angle = (dx * fwd_x + dy * fwd_y) / dist_safe
        # Half-angle cone of 90° (cos > 0) — cells behind vantage get zero weight
        in_frustum = cos_angle > 0.0

        # Inverse-square falloff within cone
        falloff = np.where(in_frustum, 1.0 / (1.0 + dist_sq / (view_dist_sq + 1e-9)), 0.0)
        best = np.maximum(best, ray_vals * falloff)

    # Normalize to 0..1 relative to the max elevation seen
    peak = float(best.max()) if best.size else 0.0
    if peak > 0.0:
        out = np.clip(best / peak, 0.0, 1.0)
    return out


def pass_saliency_refine(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Refine ``saliency_macro`` using vantage silhouettes.

    Reads ``intent.composition_hints["vantages"]`` (list of (x,y,z)).
    Blends 60% existing saliency + 40% vantage silhouette mask.
    If no vantages are specified, the pass is a no-op that keeps the
    existing saliency and reports an info metric.
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

    silhouettes = compute_vantage_silhouettes(stack, vantages, ray_count=64)
    vantage_mask = _rasterize_vantage_silhouettes_onto_grid(
        stack, vantages, silhouettes
    )
    base = np.asarray(stack.saliency_macro, dtype=np.float64)
    refined = np.clip(0.6 * base + 0.4 * vantage_mask, 0.0, 1.0)

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
    "pass_saliency_refine",
    "register_saliency_pass",
]

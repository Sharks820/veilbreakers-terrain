"""Bundle L — terrain_horizon_lod.

Builds ultra-low-resolution horizon silhouette data from the tile's
heightfield, preserving peak silhouettes via max-pool downsampling to
below 1/64 of the source resolution. Also supports ray-cast horizon
profile sampling from a vantage position (for skybox mask generation).

This module is pure numpy — no bpy. All coordinates are Z-up, world
meters. The outputs are stored on ``stack.lod_bias`` (per-cell LOD
importance) as the Unity-consumable channel.
"""

from __future__ import annotations

import time
from typing import Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# Silhouette-preserving downsample
# ---------------------------------------------------------------------------


def compute_horizon_lod(
    stack: TerrainMaskStack,
    target_res: int,
) -> np.ndarray:
    """Downsample ``stack.height`` to ``target_res`` while preserving silhouette.

    The downsample factor is chosen so the output resolution is strictly
    less than ``1/64`` of the source tile resolution, with a ceiling of
    ``target_res``. Each output cell takes the **maximum** elevation of the
    corresponding source block — this preserves ridge silhouettes (the
    horizon profile) rather than averaging them away.

    Parameters
    ----------
    stack:
        Mask stack containing the source heightfield.
    target_res:
        Requested output side length, in cells. Clamped so the final
        resolution is always ``<= source_res // 64``.

    Returns
    -------
    np.ndarray
        2-D float32 silhouette-preserving LOD heightmap, shape
        ``(out_res, out_res)``.
    """
    if stack.height is None:
        raise ValueError("compute_horizon_lod requires stack.height")
    h = np.asarray(stack.height, dtype=np.float64)
    if h.ndim != 2:
        raise ValueError(f"height must be 2D, got shape {h.shape}")

    src_h, src_w = h.shape
    src_min = min(src_h, src_w)
    # Hard ceiling: output < 1/64 of source.
    hard_cap = max(1, src_min // 64)
    out_res = max(1, min(int(target_res), hard_cap))

    # Block-pool: the step size in source cells per output cell.
    # Use ceil so every source row/col is covered.
    block_h = max(1, int(np.ceil(src_h / out_res)))
    block_w = max(1, int(np.ceil(src_w / out_res)))

    out = np.empty((out_res, out_res), dtype=np.float32)
    for i in range(out_res):
        r0 = i * block_h
        r1 = min(src_h, r0 + block_h)
        if r0 >= r1:
            r0 = max(0, src_h - 1)
            r1 = src_h
        for j in range(out_res):
            c0 = j * block_w
            c1 = min(src_w, c0 + block_w)
            if c0 >= c1:
                c0 = max(0, src_w - 1)
                c1 = src_w
            out[i, j] = float(h[r0:r1, c0:c1].max())
    return out


# ---------------------------------------------------------------------------
# Ray-cast horizon profile
# ---------------------------------------------------------------------------


def build_horizon_skybox_mask(
    stack: TerrainMaskStack,
    vantage_pos: Optional[Tuple[float, float, float]] = None,
    ray_count: int = 360,
) -> np.ndarray:
    """Build a 360-sample horizon elevation map from a vantage point.

    For each azimuth angle (sampled at 360 increments = 1° resolution by
    default), traces a ray from the vantage outward along that azimuth and
    records the maximum elevation angle subtended by the terrain silhouette
    along that ray.  This is the classic "horizon map" used by skybox
    masking, ambient occlusion baking, and far-terrain LOD systems.

    Algorithm
    ---------
    Analytical approach (vectorised, no per-ray loop):

    1.  Compute world-space (dx, dy, dz) from every grid cell to the
        vantage, where dz = h[cell] - vantage_z.
    2.  For each cell, compute:
          azimuth  = atan2(dy, dx)            in [-pi, pi]
          elev     = atan2(dz, horiz_dist)    in [-pi/2, pi/2]
    3.  Bin every cell into the nearest azimuth slot (0 … ray_count-1).
    4.  For each slot, take the maximum elevation angle seen (terrain
        silhouette is the highest point that blocks the sky).
    5.  Cells at the vantage position (dist ~ 0) are excluded.

    The result is a ``ray_count``-element float32 array of elevation angles
    in radians, one per azimuth degree bin.  Negative values mean the
    horizon dips below horizontal (open sky); positive means terrain rises
    above eye level in that direction.

    If ``vantage_pos`` is None the vantage is placed at the centre of the
    playable area (stack centre) at mean terrain height.

    Parameters
    ----------
    stack:
        Source height stack.
    vantage_pos:
        (x, y, z) world-space meters (Z-up).  None → tile centre.
    ray_count:
        Number of azimuth bins.  Default 360 = 1° per bin.

    Returns
    -------
    np.ndarray
        float32 shape ``(ray_count,)`` — horizon elevation angle (radians)
        per azimuth bin, index 0 = due east, increasing CCW.
    """
    if stack.height is None:
        raise ValueError("build_horizon_skybox_mask requires stack.height")
    if ray_count < 4:
        raise ValueError(f"ray_count must be >= 4, got {ray_count}")

    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cell = float(stack.cell_size)
    ox = float(stack.world_origin_x)
    oy = float(stack.world_origin_y)

    # Default vantage: centre of tile at mean terrain height
    if vantage_pos is None:
        vx = ox + cols * cell * 0.5
        vy = oy + rows * cell * 0.5
        vz = float(h.mean())
    else:
        vx, vy, vz = float(vantage_pos[0]), float(vantage_pos[1]), float(vantage_pos[2])

    # World-space coordinates of every cell centre (vectorised meshgrid).
    js = np.arange(cols, dtype=np.float64)
    is_ = np.arange(rows, dtype=np.float64)
    wx = ox + (js + 0.5) * cell          # shape (cols,)
    wy = oy + (is_ + 0.5) * cell         # shape (rows,)
    gx, gy = np.meshgrid(wx, wy)         # both (rows, cols)

    dx = gx - vx    # east component
    dy = gy - vy    # north component
    dz = h - vz     # vertical component

    horiz_dist = np.sqrt(dx * dx + dy * dy)

    # Exclude the vantage cell itself (horiz_dist ~ 0 produces spurious angles).
    valid = horiz_dist >= (cell * 0.5)

    # Elevation angle to each cell (radians).
    elev = np.arctan2(dz, np.where(valid, horiz_dist, 1.0))

    # Azimuth angle to each cell: atan2(dy, dx) in [-pi, pi].
    # Map to bin index in [0, ray_count).
    azimuth = np.arctan2(dy, dx)
    bins = ((azimuth + np.pi) / (2.0 * np.pi) * ray_count).astype(np.int32)
    bins = np.clip(bins, 0, ray_count - 1)

    # Initialise horizon at -pi/2 (looking straight down = no terrain visible).
    profile = np.full((ray_count,), -np.pi * 0.5, dtype=np.float32)

    # Per-bin maximum elevation via np.maximum.at (unbuffered scatter-max).
    flat_bins = bins[valid].ravel()
    flat_elev = elev[valid].ravel().astype(np.float32)
    np.maximum.at(profile, flat_bins, flat_elev)

    return profile


# ---------------------------------------------------------------------------
# Pass wrapper
# ---------------------------------------------------------------------------


def pass_horizon_lod(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle L pass: build horizon LOD + set lod_bias channel.

    Contract
    --------
    Consumes: ``height``
    Produces: ``lod_bias``
    Respects protected zones: no (read-only on height; writes LOD metadata)
    Requires scene read: no
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    hints = state.intent.composition_hints if state.intent else {}

    src_shape = stack.height.shape
    src_min = min(src_shape)
    target_res = int(hints.get("horizon_lod_target_res", max(1, src_min // 64)))
    # Guard: always strictly <= 1/64 of source.
    target_res = max(1, min(target_res, max(1, src_min // 64)))

    lod_map = compute_horizon_lod(stack, target_res)

    # Build a per-cell lod_bias channel: cells at high elevation (ridge /
    # silhouette cells) get higher priority. We use the silhouette-preserving
    # max-pool to drive a 0..1 bias across the full-resolution grid via
    # nearest-neighbour upsample.
    out_res = lod_map.shape[0]
    row_idx = (np.arange(src_shape[0]) * out_res // max(1, src_shape[0])).clip(0, out_res - 1)
    col_idx = (np.arange(src_shape[1]) * out_res // max(1, src_shape[1])).clip(0, out_res - 1)
    upsampled = lod_map[np.ix_(row_idx, col_idx)]
    lo = float(upsampled.min())
    hi = float(upsampled.max())
    if hi - lo < 1e-9:
        bias = np.zeros_like(upsampled, dtype=np.float32)
    else:
        bias = ((upsampled - lo) / (hi - lo)).astype(np.float32)
    stack.set("lod_bias", bias, "horizon_lod")

    # ------------------------------------------------------------------
    # Horizon skybox mask — 360 azimuth samples (1° per bin) from the
    # centre of the playable area.  The resulting elevation-angle array
    # is stored as the "horizon_elevation_angles" stack channel so
    # downstream passes (ambient occlusion, skybox masking, fog) can
    # consume it directly without re-computing.
    # ------------------------------------------------------------------
    vantage_hint = hints.get("horizon_skybox_vantages", None)
    if vantage_hint:
        primary_vantage: Optional[Tuple[float, float, float]] = tuple(vantage_hint[0])  # type: ignore[arg-type]
        all_vantages = list(vantage_hint)
    else:
        cs_f = float(stack.cell_size)
        cx = float(stack.world_origin_x) + src_shape[1] * cs_f * 0.5
        cy = float(stack.world_origin_y) + src_shape[0] * cs_f * 0.5
        cz = float(stack.height.mean())
        primary_vantage = (cx, cy, cz)
        all_vantages = [primary_vantage]

    # Always use 360 samples (1° bins) — the spec-mandated resolution.
    ray_count = int(hints.get("horizon_skybox_ray_count", 360))
    ray_count = max(4, ray_count)

    # Compute and store the primary horizon elevation angle array.
    horizon_angles = build_horizon_skybox_mask(
        stack, vantage_pos=primary_vantage, ray_count=ray_count
    )
    stack.set("horizon_elevation_angles", horizon_angles, "horizon_lod")

    # Also compute profiles for any additional vantages (metrics only).
    skybox_profiles = [horizon_angles.tolist()]
    for vp in all_vantages[1:]:
        skybox_profiles.append(
            build_horizon_skybox_mask(stack, vantage_pos=tuple(vp), ray_count=ray_count).tolist()  # type: ignore[arg-type]
        )

    # Determinism-friendly ratio guard.
    ratio = float(out_res) / float(max(1, src_min))
    return PassResult(
        pass_name="horizon_lod",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("lod_bias", "horizon_elevation_angles"),
        metrics={
            "source_res": int(src_min),
            "target_res": int(out_res),
            "ratio_source_over_target": float(1.0 / ratio) if ratio > 0 else 0.0,
            "ratio_target_over_source": ratio,
            "silhouette_max_m": float(lod_map.max()),
            "silhouette_min_m": float(lod_map.min()),
            "horizon_ray_count": ray_count,
            "horizon_elevation_max_rad": float(horizon_angles.max()),
            "horizon_elevation_min_rad": float(horizon_angles.min()),
            "horizon_skybox_profiles": skybox_profiles,
            "horizon_skybox_vantage_count": len(all_vantages),
        },
    )


def register_bundle_l_horizon_lod_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="horizon_lod",
            func=pass_horizon_lod,
            requires_channels=("height",),
            produces_channels=("lod_bias", "horizon_elevation_angles"),
            seed_namespace="horizon_lod",
            requires_scene_read=False,
            description="Bundle L: silhouette-preserving far-terrain LOD + 360-sample horizon map",
        )
    )


__all__ = [
    "compute_horizon_lod",
    "build_horizon_skybox_mask",
    "pass_horizon_lod",
    "register_bundle_l_horizon_lod_pass",
]

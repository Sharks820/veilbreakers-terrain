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

    # Vectorised max-pool via reshape+max — no Python per-cell loop.
    # Pad height to exact multiples of (block_h, block_w) so reshape is exact.
    pad_h = (block_h - src_h % block_h) % block_h
    pad_w = (block_w - src_w % block_w) % block_w
    if pad_h > 0 or pad_w > 0:
        # Pad by repeating the last row/column (silhouette-safe: max-pool keeps
        # the highest sample so neutral padding = min value is incorrect; we
        # use edge padding to avoid introducing spurious peaks).
        h_pad = np.pad(h, ((0, pad_h), (0, pad_w)), mode="edge")
    else:
        h_pad = h
    padded_h, padded_w = h_pad.shape

    # Reshape into (out_res, block_h, out_res, block_w), then max over blocks.
    # The reshape is exact because padded dims are exact multiples of blocks.
    blocks = h_pad.reshape(out_res, block_h, out_res, block_w)
    # Max over the two block axes (1 and 3 after reshape)
    out = blocks.max(axis=(1, 3)).astype(np.float32)
    return out


# ---------------------------------------------------------------------------
# Ray-cast horizon profile
# ---------------------------------------------------------------------------


def _sample_height_bilinear(
    height: np.ndarray,
    row_f: np.ndarray,
    col_f: np.ndarray,
) -> np.ndarray:
    """Sample the heightfield at fractional grid coordinates."""
    rows, cols = height.shape
    row0 = np.floor(row_f).astype(np.int32)
    col0 = np.floor(col_f).astype(np.int32)
    row0 = np.clip(row0, 0, rows - 1)
    col0 = np.clip(col0, 0, cols - 1)
    row1 = np.clip(row0 + 1, 0, rows - 1)
    col1 = np.clip(col0 + 1, 0, cols - 1)
    tr = row_f - row0
    tc = col_f - col0

    h00 = height[row0, col0]
    h01 = height[row0, col1]
    h10 = height[row1, col0]
    h11 = height[row1, col1]

    top = h00 * (1.0 - tc) + h01 * tc
    bottom = h10 * (1.0 - tc) + h11 * tc
    return top * (1.0 - tr) + bottom * tr


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
    Ray-marched horizon scan:

    1.  For each azimuth sample, march outward from the vantage in fixed
        world-space increments.
    2.  Bilinearly sample the terrain height at each step on that ray.
    3.  Compute the elevation angle from the vantage to the sampled point.
    4.  Keep the maximum elevation angle reached along that ray.

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

    profile = np.full((ray_count,), -np.pi * 0.5, dtype=np.float32)
    step = max(cell * 0.5, 1e-3)
    corners = np.array(
        [
            (ox, oy),
            (ox + cols * cell, oy),
            (ox, oy + rows * cell),
            (ox + cols * cell, oy + rows * cell),
        ],
        dtype=np.float64,
    )
    max_distance = float(
        np.sqrt((corners[:, 0] - vx) ** 2 + (corners[:, 1] - vy) ** 2).max()
    ) + step
    distances = np.arange(step, max_distance + step, step, dtype=np.float64)
    if distances.size == 0:
        return profile

    for idx in range(ray_count):
        angle = (2.0 * np.pi * idx) / ray_count
        xs = vx + np.cos(angle) * distances
        ys = vy + np.sin(angle) * distances
        col_f = (xs - ox) / cell - 0.5
        row_f = (ys - oy) / cell - 0.5
        valid = (
            (col_f >= 0.0)
            & (col_f <= cols - 1)
            & (row_f >= 0.0)
            & (row_f <= rows - 1)
        )
        if not np.any(valid):
            continue

        sample_heights = _sample_height_bilinear(h, row_f[valid], col_f[valid])
        elev = np.arctan2(sample_heights - vz, distances[valid])
        if elev.size:
            profile[idx] = np.float32(np.max(elev))

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

    for name in ("horizon_lod", "pass_horizon_lod"):
        TerrainPassController.register_pass(
            PassDefinition(
                name=name,
                func=pass_horizon_lod,
                requires_channels=("height",),
                produces_channels=("lod_bias", "horizon_elevation_angles"),
                overrides=("lod_bias", "horizon_elevation_angles") if name == "pass_horizon_lod" else (),
                seed_namespace=name,
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

"""Terrain chunking for open-world streaming with LOD support.

Splits large heightmaps into streamable chunks, generates LOD levels via
bilinear downsampling, computes neighbor references for edge stitching,
and exports metadata for Unity's terrain streaming system.

All functions are pure Python/numpy with NO bpy dependency — fully testable
outside Blender.

Provides:
  - compute_terrain_chunks: Main chunking + LOD pipeline
  - compute_chunk_lod: Single-chunk LOD downsample
  - compute_streaming_distances: Per-LOD streaming distance recommendations
  - export_chunks_metadata: JSON export for Unity integration

Scope note — relationship to :mod:`lod_pipeline`
------------------------------------------------
This module's LOD is **heightmap LOD**: bilinear downsample of a 2-D scalar
field (height values). It feeds Unity's terrain streaming, which handles
heightmap tessellation at render time.

:mod:`lod_pipeline` is **mesh LOD**: Quadric-Error-Metrics edge-collapse
decimation of explicit (vertex, face) mesh data for scatter assets (props,
trees, vegetation, hero objects). Mesh LOD uses silhouette preservation and
asset-type presets (``LOD_PRESETS``) that are meaningless for heightmaps.

The two LOD systems are intentionally disconnected. Heightmaps do not go
through ``generate_lod_chain``; scatter meshes do not go through
``compute_chunk_lod``. Wiring them would be incorrect — bilinear downsample
cannot preserve character silhouettes, and QEM decimation makes no sense on
a regular heightmap grid.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# LOD downsample
# ---------------------------------------------------------------------------


def compute_chunk_lod(
    heightmap_chunk: list[list[float]],
    target_resolution: int,
    *,
    camera_distance: float | None = None,
    chunk_world_size: float = 64.0,
    fov_degrees: float = 60.0,
    target_px: float = 1.0,
    screen_height_px: float = 1080.0,
) -> list[list[float]]:
    """Compute the LOD level for a chunk and return its downsampled heightmap.

    LOD level is derived from the standard screen-space formula used in
    Houdini/Unreal:

        screen_size_px = chunk_world_size / (dist * tan(fov_half)) * screen_height_px
        lod_level       = floor(log2(screen_size_px / target_px))

    The computed lod_level then selects the downsampling factor
    (chunk_size >> lod_level, minimum 2 samples).  When ``camera_distance``
    is None the function defaults to LOD 0 (full resolution), matching the
    "always load highest detail when distance is unknown" convention.

    Args:
        heightmap_chunk: 2D array of height values (rows x cols).
        target_resolution: Maximum output resolution (used as LOD-0 size).
            The actual output size may be smaller depending on the computed
            LOD level.
        camera_distance: Distance from camera to chunk centre in world metres.
            None → LOD 0 (no downsampling beyond target_resolution).
        chunk_world_size: World-space side length of the chunk in metres.
        fov_degrees: Vertical field of view in degrees.
        target_px: Target number of pixels per terrain sample at LOD 0.
            Larger values → more aggressive LOD transitions.
        screen_height_px: Vertical screen resolution used to convert
            world-space to screen-space pixels.

    Returns:
        Downsampled 2D height array.
    """
    src_rows = len(heightmap_chunk)
    if src_rows == 0:
        return []
    src_cols = len(heightmap_chunk[0])

    if target_resolution <= 0:
        return []

    # --- Determine LOD level -------------------------------------------
    lod_level = 0
    if camera_distance is not None and camera_distance > 0.0:
        fov_half_rad = math.radians(fov_degrees * 0.5)
        tan_fov_half = math.tan(fov_half_rad)
        if tan_fov_half > 0.0:
            screen_size_px = (
                chunk_world_size / (camera_distance * tan_fov_half)
            ) * screen_height_px
            if screen_size_px > 0.0 and target_px > 0.0:
                lod_level = max(0, int(math.floor(math.log2(target_px / max(screen_size_px, 1e-12)))))

    # Apply LOD: each level halves the resolution (minimum 2)
    effective_res = max(2, target_resolution >> lod_level)

    if src_rows <= effective_res and src_cols <= effective_res:
        return [list(row) for row in heightmap_chunk]

    result: list[list[float]] = []
    for tr in range(effective_res):
        row_out: list[float] = []
        src_r = tr * (src_rows - 1) / max(effective_res - 1, 1)
        for tc in range(effective_res):
            src_c = tc * (src_cols - 1) / max(effective_res - 1, 1)
            r0 = int(math.floor(src_r))
            r1 = min(r0 + 1, src_rows - 1)
            c0 = int(math.floor(src_c))
            c1 = min(c0 + 1, src_cols - 1)
            fr = src_r - r0
            fc = src_c - c0
            top = heightmap_chunk[r0][c0] * (1.0 - fc) + heightmap_chunk[r0][c1] * fc
            bot = heightmap_chunk[r1][c0] * (1.0 - fc) + heightmap_chunk[r1][c1] * fc
            row_out.append(top * (1.0 - fr) + bot * fr)
        result.append(row_out)
    return result


# ---------------------------------------------------------------------------
# Streaming distance computation
# ---------------------------------------------------------------------------


def compute_streaming_distances(
    chunk_world_size: float,
    lod_levels: int,
    lod_scale: float = 2.0,
    base_multiplier: float = 2.0,
    max_streaming_distance_m: float | None = None,
) -> dict[int, float]:
    """Compute recommended streaming distances per LOD level.

    Distances follow a geometric progression starting from
    ``chunk_world_size * base_multiplier``:

        dist[lod] = chunk_world_size * base_multiplier * lod_scale ^ lod

    This matches the convention used in Unreal Engine's HLOD / streaming
    volume setup: each LOD band is ``lod_scale`` times farther than the
    previous, giving exponentially coarser detail with distance.

    Args:
        chunk_world_size: World-space size of a single chunk (metres, square).
        lod_levels: Number of LOD levels to compute distances for.
        lod_scale: Geometric ratio between successive LOD distances (default
            2.0 — each band doubles).  Must be > 1.0.
        base_multiplier: Scale factor applied to ``chunk_world_size`` for
            the LOD-0 outer boundary (default 2.0).
        max_streaming_distance_m: Hard cap on any single LOD's distance.
            Distances beyond this are clamped.  None = no cap.

    Returns:
        Dict mapping LOD index (int) to the maximum streaming distance in
        metres for that LOD.  LOD 0 is the highest-detail, shortest-distance
        band; higher indices are lower detail and farther away.

    Raises:
        ValueError: If ``lod_scale`` <= 1.0 or ``lod_levels`` < 1.
    """
    if lod_scale <= 1.0:
        raise ValueError(f"lod_scale must be > 1.0, got {lod_scale}")
    if lod_levels < 1:
        raise ValueError(f"lod_levels must be >= 1, got {lod_levels}")

    distances: dict[int, float] = {}
    for i in range(lod_levels):
        dist = chunk_world_size * base_multiplier * (lod_scale ** i)
        if max_streaming_distance_m is not None:
            dist = min(dist, float(max_streaming_distance_m))
        distances[i] = dist
    return distances


# ---------------------------------------------------------------------------
# Main chunking pipeline
# ---------------------------------------------------------------------------


def compute_terrain_chunks(
    heightmap: list[list[float]],
    chunk_size: int = 64,
    overlap: int = 1,
    lod_levels: int = 4,
    world_scale: float = 1.0,
    world_origin: tuple[float, float] | None = None,
    overlap_cells: int | None = None,
) -> dict[str, Any]:
    """Split a terrain heightmap into streamable chunks with LOD.

    Divides the heightmap into a grid of ``chunk_size x chunk_size`` tiles.
    Each chunk extends ``overlap_cells`` samples into its neighbours on every
    edge so adjacent chunks share identical border samples, enabling seamless
    seam-free tiling in Unity's terrain streaming system.

    The ``overlap`` parameter is kept for backward compatibility and is
    treated as an alias for ``overlap_cells`` when ``overlap_cells`` is None.

    Args:
        heightmap: 2D array of height values. Must be at least
            ``chunk_size x chunk_size``.
        chunk_size: Number of samples per chunk side (before overlap).
            Must be a power of 2 for clean LOD halving.
        overlap: Legacy overlap parameter (number of border samples).
            Ignored when ``overlap_cells`` is provided explicitly.
        lod_levels: Number of LOD levels per chunk.  LOD 0 is full
            resolution; each subsequent level halves the resolution.
        world_scale: Metres per heightmap sample.
        world_origin: Optional world-space origin (x, y) of the heightmap.
        overlap_cells: Number of cells each chunk extends into its neighbours
            on every edge.  When None, falls back to ``overlap``.

    Returns:
        Dict with:
          ``chunks``: list of ChunkSpec dicts, each with:
            - ``grid_x``, ``grid_y``: Grid position
            - ``heightmap``: 2D sub-array including overlap border
            - ``bounds``: ``(min_x, min_y, max_x, max_y)`` — logical area
              *excluding* overlap, in world metres
            - ``bounds_with_overlap``: ``(min_x, min_y, max_x, max_y)``
              including the overlap border in world metres
            - ``overlap_cells``: number of cells of overlap on each edge
            - ``lods``: list of LOD dicts with ``resolution``, ``heightmap``,
              ``vertex_count``
            - ``neighbor_chunks``: dict with ``north``, ``south``, ``east``,
              ``west`` neighbour grid coords (or ``None``)
          ``metadata``: summary information about the full terrain.
    """
    total_rows = len(heightmap)
    if total_rows == 0:
        return {"chunks": [], "metadata": _empty_metadata()}
    total_cols = len(heightmap[0])
    if total_cols == 0:
        return {"chunks": [], "metadata": _empty_metadata()}

    if world_origin is None:
        origin_x, origin_y = 0.0, 0.0
    else:
        if len(world_origin) != 2:
            raise ValueError("world_origin must be a 2-tuple of (x, y)")
        origin_x = float(world_origin[0])
        origin_y = float(world_origin[1])

    # Resolve overlap_cells: explicit arg wins, then legacy overlap param
    ov = int(overlap_cells) if overlap_cells is not None else int(overlap)
    if ov < 0:
        raise ValueError(f"overlap_cells must be >= 0, got {ov}")

    # Number of chunks in each direction
    grid_cols = max(1, total_cols // chunk_size)
    grid_rows = max(1, total_rows // chunk_size)

    chunk_world_size = chunk_size * world_scale
    overlap_world = ov * world_scale

    chunks: list[dict[str, Any]] = []
    total_verts_lod0 = 0

    for gy in range(grid_rows):
        for gx in range(grid_cols):
            # Logical (non-overlapped) sample range
            r_core_start = gy * chunk_size
            r_core_end = (gy + 1) * chunk_size
            c_core_start = gx * chunk_size
            c_core_end = (gx + 1) * chunk_size

            # Overlap-extended sample range (clamped to array bounds)
            r_start = max(0, r_core_start - ov)
            r_end = min(total_rows, r_core_end + ov)
            c_start = max(0, c_core_start - ov)
            c_end = min(total_cols, c_core_end + ov)

            # Extract sub-array (includes overlap border)
            sub_heightmap: list[list[float]] = []
            for r in range(r_start, r_end):
                sub_heightmap.append(list(heightmap[r][c_start:c_end]))

            # World-space bounds: logical area (no overlap)
            min_x = origin_x + gx * chunk_world_size
            min_y = origin_y + gy * chunk_world_size
            max_x = origin_x + (gx + 1) * chunk_world_size
            max_y = origin_y + (gy + 1) * chunk_world_size

            # World-space bounds including overlap
            min_x_ov = min_x - (r_core_start - r_start) * world_scale
            min_y_ov = min_y - (c_core_start - c_start) * world_scale
            max_x_ov = max_x + (r_end - r_core_end) * world_scale
            max_y_ov = max_y + (c_end - c_core_end) * world_scale

            # Generate LOD levels
            lods: list[dict[str, Any]] = []
            for lod in range(lod_levels):
                target_res = max(2, chunk_size >> lod)
                if lod == 0:
                    lod_hmap = [list(row) for row in sub_heightmap]
                    lod_res = len(sub_heightmap)
                    lod_res_cols = len(sub_heightmap[0]) if lod_res > 0 else 0
                    vert_count = lod_res * lod_res_cols
                else:
                    lod_hmap = compute_chunk_lod(sub_heightmap, target_res)
                    lod_res = len(lod_hmap)
                    lod_res_cols = len(lod_hmap[0]) if lod_res > 0 else 0
                    vert_count = lod_res * lod_res_cols

                lods.append(
                    {
                        "lod_level": lod,
                        "resolution": target_res if lod > 0 else (
                            len(sub_heightmap[0]) if sub_heightmap else 0
                        ),
                        "heightmap": lod_hmap,
                        "vertex_count": vert_count,
                    }
                )

            if lods:
                total_verts_lod0 += lods[0]["vertex_count"]

            # Neighbour references
            neighbors: dict[str, tuple[int, int] | None] = {
                "north": (gx, gy - 1) if gy > 0 else None,
                "south": (gx, gy + 1) if gy < grid_rows - 1 else None,
                "west": (gx - 1, gy) if gx > 0 else None,
                "east": (gx + 1, gy) if gx < grid_cols - 1 else None,
            }

            chunks.append(
                {
                    "grid_x": gx,
                    "grid_y": gy,
                    "heightmap": sub_heightmap,
                    "bounds": (min_x, min_y, max_x, max_y),
                    "bounds_with_overlap": (min_x_ov, min_y_ov, max_x_ov, max_y_ov),
                    "overlap_cells": ov,
                    "world_origin": (origin_x, origin_y),
                    "lods": lods,
                    "neighbor_chunks": neighbors,
                }
            )

    streaming_dist = compute_streaming_distances(chunk_world_size, lod_levels)

    metadata: dict[str, Any] = {
        "total_chunks": len(chunks),
        "grid_size": (grid_cols, grid_rows),
        "chunk_world_size": chunk_world_size,
        "overlap_cells": ov,
        "overlap_world_m": overlap_world,
        "world_origin": (origin_x, origin_y),
        "total_vertices_lod0": total_verts_lod0,
        "streaming_distance_lod": streaming_dist,
        "chunk_size_samples": chunk_size,
        "overlap": ov,
        "lod_levels": lod_levels,
        "heightmap_size": (total_cols, total_rows),
    }

    return {"chunks": chunks, "metadata": metadata}


# ---------------------------------------------------------------------------
# Metadata export
# ---------------------------------------------------------------------------


def export_chunks_metadata(
    chunks_result: dict[str, Any],
    output_format: str = "json",
) -> str:
    """Export chunk layout as JSON for Unity terrain streaming system.

    Strips the heavy heightmap data and exports only the structural
    metadata: grid positions, bounds, LOD info, neighbor refs, and
    streaming distances.

    Args:
        chunks_result: Output from :func:`compute_terrain_chunks`.
        output_format: Currently only ``'json'`` is supported.

    Returns:
        JSON string (pretty-printed) with chunk layout metadata.
    """
    metadata = chunks_result.get("metadata", {})

    # Build lightweight chunk entries (no heightmap data)
    chunk_entries: list[dict[str, Any]] = []
    for chunk in chunks_result.get("chunks", []):
        lod_summary = []
        for lod in chunk.get("lods", []):
            lod_summary.append(
                {
                    "lod_level": lod["lod_level"],
                    "resolution": lod["resolution"],
                    "vertex_count": lod["vertex_count"],
                }
            )

        chunk_entries.append(
            {
                "grid_x": chunk["grid_x"],
                "grid_y": chunk["grid_y"],
                "bounds": chunk["bounds"],
                "lod_count": len(lod_summary),
                "lods": lod_summary,
                "neighbor_chunks": chunk["neighbor_chunks"],
            }
        )

    export_data = {
        "terrain_metadata": metadata,
        "chunks": chunk_entries,
    }

    # Convert streaming_distance_lod keys from int to str for JSON compat
    if "streaming_distance_lod" in export_data["terrain_metadata"]:
        sd = export_data["terrain_metadata"]["streaming_distance_lod"]
        export_data["terrain_metadata"]["streaming_distance_lod"] = {
            str(k): v for k, v in sd.items()
        }

    return json.dumps(export_data, indent=2)


def validate_tile_seams(
    tile_a: list[list[float]],
    tile_b: list[list[float]],
    direction: str = "east",
    tolerance: float = 1e-6,
) -> dict[str, Any]:
    """Validate that two adjacent tiles share matching seam samples.

    Args:
        tile_a: First tile heightmap.
        tile_b: Adjacent tile heightmap.
        direction: Relative direction of tile_b from tile_a.
        tolerance: Maximum allowed absolute delta for a seam sample.

    Returns:
        Dict describing seam agreement.
    """
    arr_a = np.asarray(tile_a, dtype=np.float64)
    arr_b = np.asarray(tile_b, dtype=np.float64)

    if arr_a.size == 0 or arr_b.size == 0:
        return {
            "match": False,
            "direction": direction,
            "sample_count": 0,
            "max_delta": None,
            "mean_delta": None,
            "channel_count": 0,
            "per_channel_max_delta": None,
            "per_channel_mean_delta": None,
            "error": "empty tile input",
        }
    if arr_a.ndim < 2 or arr_b.ndim < 2:
        return {
            "match": False,
            "direction": direction,
            "sample_count": 0,
            "max_delta": None,
            "mean_delta": None,
            "channel_count": 0,
            "per_channel_max_delta": None,
            "per_channel_mean_delta": None,
            "error": "tile input must have at least 2 dimensions",
        }

    rows_a, cols_a = arr_a.shape[:2]
    rows_b, cols_b = arr_b.shape[:2]
    channel_shape_a = arr_a.shape[2:]
    channel_shape_b = arr_b.shape[2:]

    if channel_shape_a != channel_shape_b:
        return {
            "match": False,
            "direction": direction,
            "sample_count": 0,
            "max_delta": None,
            "mean_delta": None,
            "channel_count": 0,
            "per_channel_max_delta": None,
            "per_channel_mean_delta": None,
            "error": "channel shape mismatch",
        }

    if direction in {"east", "west"}:
        if rows_a != rows_b:
            return {
                "match": False,
                "direction": direction,
                "sample_count": 0,
                "max_delta": None,
                "mean_delta": None,
                "error": "row count mismatch",
            }
        edge_a = arr_a[:, cols_a - 1, ...]
        edge_b = arr_b[:, 0, ...]
    elif direction in {"north", "south"}:
        if cols_a != cols_b:
            return {
                "match": False,
                "direction": direction,
                "sample_count": 0,
                "max_delta": None,
                "mean_delta": None,
                "error": "column count mismatch",
            }
        edge_a = arr_a[rows_a - 1, :, ...]
        edge_b = arr_b[0, :, ...]
    else:
        raise ValueError("direction must be one of: east, west, north, south")

    delta = np.abs(edge_a - edge_b)
    delta_samples = delta.reshape(delta.shape[0], -1)
    per_channel_max = delta.max(axis=0)
    per_channel_mean = delta.mean(axis=0)
    max_delta = float(delta_samples.max()) if delta_samples.size else 0.0
    mean_delta = float(delta_samples.mean()) if delta_samples.size else 0.0
    channel_count = int(np.prod(channel_shape_a)) if channel_shape_a else 1

    return {
        "match": max_delta <= tolerance,
        "direction": direction,
        "sample_count": int(delta.shape[0]),
        "max_delta": max_delta,
        "mean_delta": mean_delta,
        "channel_count": channel_count,
        "per_channel_max_delta": np.asarray(per_channel_max).reshape(-1).tolist(),
        "per_channel_mean_delta": np.asarray(per_channel_mean).reshape(-1).tolist(),
        "tolerance": tolerance,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _empty_metadata() -> dict[str, Any]:
    """Return an empty metadata dict for degenerate inputs."""
    return {
        "total_chunks": 0,
        "grid_size": (0, 0),
        "chunk_world_size": 0.0,
        "world_origin": (0.0, 0.0),
        "total_vertices_lod0": 0,
        "streaming_distance_lod": {},
        "chunk_size_samples": 0,
        "overlap": 0,
        "lod_levels": 0,
        "heightmap_size": (0, 0),
    }

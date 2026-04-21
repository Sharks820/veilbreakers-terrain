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

import hashlib
import json
import math
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# LOD downsample
# ---------------------------------------------------------------------------


def _downsample_heightmap(
    heightmap_chunk: list[list[float]],
    target_resolution: int,
) -> list[list[float]]:
    """Bilinear downsample a 2-D heightmap to ``target_resolution × target_resolution``.

    Args:
        heightmap_chunk: 2D list of height values (rows × cols).
        target_resolution: Output resolution (square).

    Returns:
        Downsampled 2D height list of shape (target_resolution, target_resolution).
        Returns the original copy if the input is already <= target_resolution.
        Returns [] for empty input or target_resolution <= 0.
    """
    src_rows = len(heightmap_chunk)
    if src_rows == 0:
        return []
    src_cols = len(heightmap_chunk[0])

    if target_resolution <= 0:
        return []

    if src_rows <= target_resolution and src_cols <= target_resolution:
        return [list(row) for row in heightmap_chunk]

    effective_res = target_resolution
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


def compute_chunk_lod(
    heightmap_chunk: list[list[float]],
    target_resolution: int,
    *,
    camera_distance: float | None = None,
    chunk_world_size: float = 64.0,
    fov_degrees: float = 60.0,
    target_px: float = 1.0,
    screen_height_px: float = 1080.0,
) -> int:
    """Return the integer LOD level appropriate for a chunk at a given distance.

    LOD level is derived from the standard screen-space formula:

        screen_size_px = chunk_world_size / (dist * tan(fov_half)) * screen_height_px
        lod_level       = floor(log2(target_px / screen_size_px))

    When ``camera_distance`` is None the function returns 0 (full detail),
    matching the "always load highest detail when distance is unknown"
    convention.

    To obtain the downsampled heightmap for a given LOD level, use
    ``_downsample_heightmap(chunk, target_resolution >> lod_level)`` or
    call ``_downsample_heightmap`` directly.

    Args:
        heightmap_chunk: 2D array of height values (rows x cols).
        target_resolution: LOD-0 target resolution (used for computing
            the effective resolution at the returned LOD level).
        camera_distance: Distance from camera to chunk centre in world metres.
            None → LOD 0.
        chunk_world_size: World-space side length of the chunk in metres.
        fov_degrees: Vertical field of view in degrees.
        target_px: Target pixels per terrain sample at LOD 0.
        screen_height_px: Vertical screen resolution in pixels.

    Returns:
        Integer LOD level (0 = full detail, higher = coarser).
    """
    lod_level = 0
    if camera_distance is not None and camera_distance > 0.0:
        fov_half_rad = math.radians(fov_degrees * 0.5)
        tan_fov_half = math.tan(fov_half_rad)
        if tan_fov_half > 0.0:
            screen_size_px = (
                chunk_world_size / (camera_distance * tan_fov_half)
            ) * screen_height_px
            if screen_size_px > 0.0 and target_px > 0.0:
                lod_level = max(
                    0,
                    int(math.floor(math.log2(target_px / max(screen_size_px, 1e-12)))),
                )
    return lod_level


# ---------------------------------------------------------------------------
# Streaming distance computation
# ---------------------------------------------------------------------------


def compute_streaming_distances(
    chunk_world_size: float,
    lod_levels: int,
    lod_scale: float = 2.0,
    base_multiplier: float = 2.0,
    max_streaming_distance_m: float | None = None,
    terrain_feature_size_m: float | None = None,
) -> dict[int, float]:
    """Compute recommended streaming distances per LOD level.

    Distances follow a geometric progression starting from
    ``chunk_world_size * base_multiplier``:

        dist[lod] = chunk_world_size * base_multiplier * lod_scale ^ lod

    This matches the convention used in Unreal Engine's HLOD / streaming
    volume setup: each LOD band is ``lod_scale`` times farther than the
    previous, giving exponentially coarser detail with distance.

    **Feature-size awareness** (AAA requirement):
    Large terrain features — cliff faces, ridge lines, hero rock formations —
    must remain readable at greater distances than the raw chunk geometry
    would imply.  When ``terrain_feature_size_m`` is provided the LOD-0
    streaming distance is raised so that a feature of that world-space diameter
    subtends at least 5 % of the vertical screen at 60 FPS (standard Unreal
    streaming heuristic: dist_min = feature_size / 0.05 / tan(30°), simplified
    here as ``feature_size * 11.5``).  Subsequent LOD bands scale from that
    adjusted base.

    For example:
      - A 10 m cliff face needs LOD-0 visible to ~115 m — standard 2× chunk
        multiplier for a 32 m chunk gives only 64 m, so the feature-size
        floor raises it to 115 m.
      - A 150 m mountain ridge needs LOD-0 visible to ~1725 m — far beyond
        the raw chunk budget, so all LOD distances are scaled up proportionally.

    Args:
        chunk_world_size: World-space size of a single chunk (metres, square).
        lod_levels: Number of LOD levels to compute distances for.
        lod_scale: Geometric ratio between successive LOD distances (default
            2.0 — each band doubles).  Must be > 1.0.
        base_multiplier: Scale factor applied to ``chunk_world_size`` for
            the LOD-0 outer boundary (default 2.0).
        max_streaming_distance_m: Hard cap on any single LOD's distance.
            Distances beyond this are clamped.  None = no cap.
        terrain_feature_size_m: Diameter of the largest terrain feature (m)
            that must remain readable at LOD 0.  When provided the LOD-0
            distance is raised to a minimum of
            ``terrain_feature_size_m * 11.5`` so the feature occupies at
            least ~5 % of screen height at the streaming boundary.
            None = no feature-size adjustment (backward-compatible behaviour).

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

    # Base LOD-0 distance from chunk size and multiplier
    base_dist = chunk_world_size * base_multiplier

    # Feature-size floor: ensure the feature stays readable at LOD-0 boundary.
    # The constant 11.5 ≈ 1 / (0.05 * tan(60°/2)) — derived from the 5 %
    # screen-height readability threshold at a 60° vertical FoV.
    if terrain_feature_size_m is not None and terrain_feature_size_m > 0.0:
        feature_dist_floor = float(terrain_feature_size_m) * 11.5
        base_dist = max(base_dist, feature_dist_floor)

    distances: dict[int, float] = {}
    for i in range(lod_levels):
        dist = base_dist * (lod_scale ** i)
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
    terrain_feature_size_m: float | None = None,
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
        terrain_feature_size_m: Diameter of the largest terrain feature (m)
            that must remain visible at LOD 0 (e.g. a 50 m cliff face, a
            150 m ridge). When supplied, LOD streaming distances are raised
            so the feature subtends at least 5 % of screen height at the
            LOD-0 streaming boundary — preventing large features from
            unexpectedly popping to lower LOD while still readable.
            Passed directly to ``compute_streaming_distances``.
            None = no feature-size adjustment (backward-compatible).

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
          ``metadata``: summary information about the full terrain, including
            ``terrain_feature_size_m`` when provided.
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

    # Number of chunks in each direction — use math.ceil so trailing cells
    # (e.g. the last 1 row when total_rows == chunk_size + 1) are not dropped.
    # The final chunk's r_end / c_end is already clamped to total_rows/total_cols
    # via min(total_rows, r_core_end + ov) in the loop below, so no OOB risk.
    grid_cols = max(1, math.ceil(total_cols / chunk_size))
    grid_rows = max(1, math.ceil(total_rows / chunk_size))

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
            min_x_ov = min_x - (c_core_start - c_start) * world_scale
            min_y_ov = min_y - (r_core_start - r_start) * world_scale
            max_x_ov = max_x + (c_end - c_core_end) * world_scale
            max_y_ov = max_y + (r_end - r_core_end) * world_scale

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
                    lod_hmap = _downsample_heightmap(sub_heightmap, target_res)
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

    streaming_dist = compute_streaming_distances(
        chunk_world_size,
        lod_levels,
        terrain_feature_size_m=terrain_feature_size_m,
    )

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
        "terrain_feature_size_m": terrain_feature_size_m,
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
        "seam_manifest": build_chunk_seam_manifest(chunks_result),
    }

    # Convert streaming_distance_lod keys from int to str for JSON compat
    if "streaming_distance_lod" in export_data["terrain_metadata"]:
        sd = export_data["terrain_metadata"]["streaming_distance_lod"]
        export_data["terrain_metadata"]["streaming_distance_lod"] = {
            str(k): v for k, v in sd.items()
        }

    return json.dumps(export_data, indent=2)


def build_tile_seam_contract(
    heightmap: list[list[float]] | np.ndarray,
    *,
    tile_x: int,
    tile_y: int,
    cell_size: float,
    world_origin_x: float,
    world_origin_y: float,
    world_id: str = "unknown",
    batch_id: str | None = None,
    neighbor_tiles: dict[str, tuple[int, int] | None] | None = None,
) -> dict[str, Any]:
    """Build a persistent seam contract for one exported tile.

    The contract is intentionally lightweight but durable:
    tile/world identity, world bounds, edge hashes, edge samples, corner values,
    and the expected neighbour tile coordinates. This is the data needed to
    resume batch generation later and verify that a newly generated tile still
    fits the already-exported batch.
    """
    arr = np.asarray(heightmap, dtype=np.float64)
    if arr.ndim < 2:
        raise ValueError("heightmap must have at least 2 dimensions")
    if arr.size == 0:
        raise ValueError("heightmap must not be empty")

    rows, cols = arr.shape[:2]
    tile_extent_x = max(cols - 1, 0) * float(cell_size)
    tile_extent_y = max(rows - 1, 0) * float(cell_size)
    tile_key = f"{int(tile_x)},{int(tile_y)}"

    if neighbor_tiles is None:
        neighbor_tiles = {
            "north": (int(tile_x), int(tile_y) - 1),
            "south": (int(tile_x), int(tile_y) + 1),
            "west": (int(tile_x) - 1, int(tile_y)),
            "east": (int(tile_x) + 1, int(tile_y)),
        }

    edges = {
        "north": arr[0, ...],
        "south": arr[rows - 1, ...],
        "west": arr[:, 0, ...],
        "east": arr[:, cols - 1, ...],
    }
    corners = {
        "north_west": _coerce_jsonable_edge_samples(arr[0, 0, ...]),
        "north_east": _coerce_jsonable_edge_samples(arr[0, cols - 1, ...]),
        "south_west": _coerce_jsonable_edge_samples(arr[rows - 1, 0, ...]),
        "south_east": _coerce_jsonable_edge_samples(arr[rows - 1, cols - 1, ...]),
    }

    return {
        "schema_version": "1.0",
        "world_id": str(world_id),
        "batch_id": None if batch_id is None else str(batch_id),
        "tile_key": tile_key,
        "tile_coords": [int(tile_x), int(tile_y)],
        "grid_shape": [int(rows), int(cols)],
        "cell_size": float(cell_size),
        "world_origin": [float(world_origin_x), float(world_origin_y)],
        "world_bounds": {
            "min_x": float(world_origin_x),
            "min_y": float(world_origin_y),
            "max_x": float(world_origin_x + tile_extent_x),
            "max_y": float(world_origin_y + tile_extent_y),
        },
        "neighbor_tiles": {
            direction: None if coords is None else [int(coords[0]), int(coords[1])]
            for direction, coords in neighbor_tiles.items()
        },
        "corner_heights": corners,
        "edge_contracts": {
            direction: {
                "sample_count": int(edge.shape[0]) if edge.ndim >= 1 else 1,
                "channel_count": int(np.prod(edge.shape[1:])) if edge.ndim > 1 else 1,
                "sha256": _hash_edge_samples(edge),
                "samples": _coerce_jsonable_edge_samples(edge),
            }
            for direction, edge in edges.items()
        },
        "height_sha256": _hash_edge_samples(arr),
    }


def _blend_locked_edges(
    values: np.ndarray,
    *,
    north_edge: Any,
    south_edge: Any,
    east_edge: Any,
    west_edge: Any,
) -> np.ndarray:
    """Return a seam-locked copy of a 2-D field."""
    h = np.asarray(values).copy()
    if h.ndim != 2:
        return h

    if not np.issubdtype(h.dtype, np.floating):
        h = h.astype(np.float32, copy=False)

    H, W = h.shape
    _BLEND_WEIGHTS = [1.0, 0.6, 0.2]

    if north_edge is not None:
        edge = np.asarray(north_edge, dtype=h.dtype)
        if edge.shape == (W,):
            h[0, :] = edge
            for offset, w in enumerate(_BLEND_WEIGHTS[1:], start=1):
                row = offset
                if row < H:
                    h[row, :] = w * edge + (1.0 - w) * h[row, :]

    if south_edge is not None:
        edge = np.asarray(south_edge, dtype=h.dtype)
        if edge.shape == (W,):
            h[-1, :] = edge
            for offset, w in enumerate(_BLEND_WEIGHTS[1:], start=1):
                row = H - 1 - offset
                if row >= 0:
                    h[row, :] = w * edge + (1.0 - w) * h[row, :]

    if east_edge is not None:
        edge = np.asarray(east_edge, dtype=h.dtype)
        if edge.shape == (H,):
            h[:, -1] = edge
            for offset, w in enumerate(_BLEND_WEIGHTS[1:], start=1):
                col = W - 1 - offset
                if col >= 0:
                    h[:, col] = w * edge + (1.0 - w) * h[:, col]

    if west_edge is not None:
        edge = np.asarray(west_edge, dtype=h.dtype)
        if edge.shape == (H,):
            h[:, 0] = edge
            for offset, w in enumerate(_BLEND_WEIGHTS[1:], start=1):
                col = offset
                if col < W:
                    h[:, col] = w * edge + (1.0 - w) * h[:, col]

    return h


def apply_seam_boundary_conditions(
    stack: Any,
    *,
    channels: tuple[str, ...] = ("height",),
) -> None:
    """Lock tile border rows/cols to neighbor edge values with a 3-cell blend.

    Reads the ``north_edge``, ``south_edge``, ``east_edge``, ``west_edge``
    fields on a ``TerrainMaskStack`` (populated via
    ``stack.import_neighbor_edge()``) and enforces them on the requested
    2-D channels so that erosion, materials, and scatter passes see a
    continuous surface across tile boundaries.

    Border enforcement:
      - ``north_edge`` (shape ``(W,)``): locks ``height[0, :]`` to the
        south border of the tile to the north.
      - ``south_edge`` (shape ``(W,)``): locks ``height[-1, :]`` to the
        north border of the tile to the south.
      - ``east_edge``  (shape ``(H,)``): locks ``height[:, -1]``.
      - ``west_edge``  (shape ``(H,)``): locks ``height[:, 0]``.

    After locking the border row/col a 3-cell weighted blend is applied
    inward from the border so interior values transition smoothly rather
    than stepping abruptly:

        weights = [1.0, 0.6, 0.2]  (border cell → interior)

    The blend blends each locked border cell toward the original interior
    value using linear interpolation:
        ``blended[i] = w * border_val + (1 - w) * original[i]``

    Only edges where the corresponding field is not ``None`` are modified.
    The function uses ``object.__setattr__`` to bypass the stack's
    provenance-warning guard (same pattern as ``import_neighbor_edge``).

    Parameters
    ----------
    stack : TerrainMaskStack
        Tile stack to enforce seam conditions on. Modified in-place.
    channels : tuple[str, ...], optional
        Stack fields to seam-lock. Defaults to ``("height",)``. Any missing
        or non-2-D channels are ignored.
    """
    north_edge = getattr(stack, "north_edge", None)
    south_edge = getattr(stack, "south_edge", None)
    east_edge = getattr(stack, "east_edge", None)
    west_edge = getattr(stack, "west_edge", None)

    mutated = False
    for channel in tuple(dict.fromkeys(str(ch) for ch in channels)):
        arr = getattr(stack, channel, None)
        if arr is None:
            continue
        arr_np = np.asarray(arr)
        if arr_np.ndim != 2:
            continue

        blended = _blend_locked_edges(
            arr_np,
            north_edge=north_edge,
            south_edge=south_edge,
            east_edge=east_edge,
            west_edge=west_edge,
        )
        if np.array_equal(arr_np, blended):
            continue

        # Write back via object.__setattr__ to avoid provenance-guard warning;
        # this is an in-place seam correction, not a new producer claiming the
        # channel.
        object.__setattr__(stack, channel, blended)
        mutated = True

    if mutated:
        object.__setattr__(stack, "content_hash", None)
        height = getattr(stack, "height", None)
        if height is not None:
            height_np = np.asarray(height, dtype=np.float64)
            object.__setattr__(
                stack,
                "height_min_m",
                float(height_np.min()) if height_np.size else 0.0,
            )
            object.__setattr__(
                stack,
                "height_max_m",
                float(height_np.max()) if height_np.size else 0.0,
            )


def build_tile_batch_manifest(
    tile_contracts: list[dict[str, Any]],
    *,
    world_id: str = "unknown",
    batch_id: str | None = None,
) -> dict[str, Any]:
    """Aggregate tile seam contracts into a resumable world-batch manifest."""
    by_coords: dict[tuple[int, int], dict[str, Any]] = {}
    for contract in tile_contracts:
        coords_raw = contract.get("tile_coords", (0, 0))
        coords = (int(coords_raw[0]), int(coords_raw[1]))
        by_coords[coords] = contract

    adjacency: list[dict[str, Any]] = []
    frontier: set[tuple[int, int]] = set()

    for coords, contract in by_coords.items():
        tx, ty = coords
        neighbors = contract.get("neighbor_tiles", {})
        edge_contracts = contract.get("edge_contracts", {})
        for direction in ("north", "south", "west", "east"):
            neighbor_raw = neighbors.get(direction)
            if neighbor_raw is None:
                continue
            neighbor_coords = (int(neighbor_raw[0]), int(neighbor_raw[1]))
            if neighbor_coords not in by_coords:
                frontier.add(neighbor_coords)
        for direction, delta in (
            ("east", (1, 0, "west")),
            ("south", (0, 1, "north")),
        ):
            neighbor_raw = neighbors.get(direction)
            if neighbor_raw is None:
                continue
            neighbor_coords = (int(neighbor_raw[0]), int(neighbor_raw[1]))
            neighbor_contract = by_coords.get(neighbor_coords)
            if neighbor_contract is None:
                adjacency.append(
                    {
                        "tile_a": [tx, ty],
                        "tile_b": [neighbor_coords[0], neighbor_coords[1]],
                        "direction": direction,
                        "status": "missing_neighbor",
                    }
                )
                continue

            opposite = delta[2]
            edge_a = edge_contracts.get(direction, {})
            edge_b = neighbor_contract.get("edge_contracts", {}).get(opposite, {})
            match = edge_a.get("sha256") == edge_b.get("sha256")
            adjacency.append(
                {
                    "tile_a": [tx, ty],
                    "tile_b": [neighbor_coords[0], neighbor_coords[1]],
                    "direction": direction,
                    "status": "matched" if match else "mismatch",
                    "edge_hash_a": edge_a.get("sha256"),
                    "edge_hash_b": edge_b.get("sha256"),
                }
            )

    sorted_tiles = sorted(by_coords.items(), key=lambda item: (item[0][1], item[0][0]))
    return {
        "schema_version": "1.0",
        "world_id": str(world_id),
        "batch_id": None if batch_id is None else str(batch_id),
        "tile_count": len(sorted_tiles),
        "tiles": [contract for _, contract in sorted_tiles],
        "adjacency": adjacency,
        "frontier_tiles": [
            {"tile_x": int(coords[0]), "tile_y": int(coords[1])}
            for coords in sorted(frontier, key=lambda item: (item[1], item[0]))
        ],
    }


def build_chunk_seam_manifest(
    chunks_result: dict[str, Any],
    *,
    world_id: str = "unknown",
    batch_id: str | None = None,
) -> dict[str, Any]:
    """Build a resumable seam manifest from ``compute_terrain_chunks`` output."""
    metadata = chunks_result.get("metadata", {})
    chunk_size_samples = int(metadata.get("chunk_size_samples", 0) or 0)
    chunk_world_size = float(metadata.get("chunk_world_size", 0.0) or 0.0)
    world_scale = (
        chunk_world_size / float(chunk_size_samples)
        if chunk_size_samples > 0 and chunk_world_size > 0.0
        else 1.0
    )

    tile_contracts: list[dict[str, Any]] = []
    for chunk in chunks_result.get("chunks", []):
        core = _extract_chunk_core_heightmap(chunk, world_scale)
        bounds = chunk.get("bounds", (0.0, 0.0, 0.0, 0.0))
        tile_contracts.append(
            build_tile_seam_contract(
                core,
                tile_x=int(chunk.get("grid_x", 0)),
                tile_y=int(chunk.get("grid_y", 0)),
                cell_size=world_scale,
                world_origin_x=float(bounds[0]),
                world_origin_y=float(bounds[1]),
                world_id=world_id,
                batch_id=batch_id,
            )
        )

    return build_tile_batch_manifest(
        tile_contracts,
        world_id=world_id,
        batch_id=batch_id,
    )


def validate_tile_seams(
    tile_a: list[list[float]],
    tile_b: list[list[float]],
    direction: str = "east",
    tolerance: float = 1e-4,
) -> dict[str, Any]:
    """Validate that two adjacent tiles share matching seam samples.

    Each channel value at the shared border must match within ``tolerance``
    (absolute).  The default tolerance is 1e-4 — the AAA VeilBreakers ship
    spec for cross-tile seam agreement.  This is intentionally looser than
    floating-point epsilon (1e-6) to accommodate bilinear-resampling
    rounding across tiles authored at different passes while still catching
    real seam cracks visible at player scale.

    All channels present in a 3-D tile (height + additional layers in the
    third axis) are checked independently; per-channel max/mean deltas are
    returned so authors can identify which channel is mismatched.

    Args:
        tile_a: First tile heightmap (2-D or 3-D list of floats).
        tile_b: Adjacent tile heightmap (same shape convention as tile_a).
        direction: Relative direction of tile_b from tile_a.
            One of ``"east"``, ``"west"``, ``"north"``, ``"south"``.
        tolerance: Maximum allowed absolute delta for a seam sample
            (default 1e-4 per AAA spec).

    Returns:
        Dict describing seam agreement, including ``match`` bool,
        ``max_delta``, ``mean_delta``, per-channel breakdowns, and
        ``tolerance`` used.
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

    if direction == "east":
        # tile_b is the EAST neighbor of tile_a:
        # right edge of A (last col) must match left edge of B (col 0).
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
    elif direction == "west":
        # tile_b is the WEST neighbor of tile_a:
        # left edge of A (col 0) must match right edge of B (last col).
        if rows_a != rows_b:
            return {
                "match": False,
                "direction": direction,
                "sample_count": 0,
                "max_delta": None,
                "mean_delta": None,
                "error": "row count mismatch",
            }
        edge_a = arr_a[:, 0, ...]
        edge_b = arr_b[:, cols_b - 1, ...]
    elif direction == "south":
        # tile_b is the SOUTH neighbor of tile_a:
        # bottom edge of A (last row) must match top edge of B (row 0).
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
    elif direction == "north":
        # tile_b is the NORTH neighbor of tile_a:
        # top edge of A (row 0) must match bottom edge of B (last row).
        if cols_a != cols_b:
            return {
                "match": False,
                "direction": direction,
                "sample_count": 0,
                "max_delta": None,
                "mean_delta": None,
                "error": "column count mismatch",
            }
        edge_a = arr_a[0, :, ...]
        edge_b = arr_b[rows_b - 1, :, ...]
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


def _coerce_jsonable_edge_samples(edge: np.ndarray) -> Any:
    arr = np.asarray(edge, dtype=np.float64)
    if arr.ndim == 0:
        return float(arr)
    if arr.ndim == 1:
        return arr.tolist()
    return arr.reshape(arr.shape[0], -1).tolist()


def _hash_edge_samples(edge: np.ndarray) -> str:
    arr = np.ascontiguousarray(np.asarray(edge, dtype="<f8"))
    return hashlib.sha256(arr.tobytes()).hexdigest()


def _extract_chunk_core_heightmap(
    chunk: dict[str, Any],
    world_scale: float,
) -> np.ndarray:
    arr = np.asarray(chunk.get("heightmap", []), dtype=np.float64)
    if arr.ndim < 2 or arr.size == 0:
        return arr

    bounds = chunk.get("bounds", (0.0, 0.0, 0.0, 0.0))
    bounds_ov = chunk.get("bounds_with_overlap", bounds)
    left_pad = max(0, int(round((float(bounds[0]) - float(bounds_ov[0])) / world_scale)))
    top_pad = max(0, int(round((float(bounds[1]) - float(bounds_ov[1])) / world_scale)))
    right_pad = max(0, int(round((float(bounds_ov[2]) - float(bounds[2])) / world_scale)))
    bottom_pad = max(0, int(round((float(bounds_ov[3]) - float(bounds[3])) / world_scale)))

    row_end = arr.shape[0] - bottom_pad if bottom_pad > 0 else arr.shape[0]
    col_end = arr.shape[1] - right_pad if right_pad > 0 else arr.shape[1]
    return arr[top_pad:row_end, left_pad:col_end, ...]


def _compute_tile_contracts(
    tile_origin: tuple[float, float],
    tile_size_m: float,
    line_start: tuple[float, float],
    line_end: tuple[float, float],
) -> list[float]:
    """Return parametric t-values where a line segment crosses the tile AABB edges.

    Uses the parametric slab test (Smits' method):
        t = (boundary - start) / (end - start)
    for each of the 4 AABB edges. Returns all t in [0, 1] where the segment
    intersects an edge of the tile, with the additional constraint that the
    crossing point lies within the tile boundary on the perpendicular axis.

    Fix 7.12: replaces any bounding-box approximation with exact AABB slab
    intersection so road/river segments that merely clip tile corners are
    correctly identified.

    Args:
        tile_origin: (x0, y0) bottom-left corner of tile in world space.
        tile_size_m: Tile side length in meters (tile is a square).
        line_start: (sx, sy) segment start in world space.
        line_end: (ex, ey) segment end in world space.

    Returns:
        Sorted list of unique t values in [0, 1] at AABB edge crossings.
        Empty list if the segment does not intersect the tile boundary.
    """
    x0, y0 = tile_origin
    x1, y1 = x0 + tile_size_m, y0 + tile_size_m
    sx, sy = line_start
    ex, ey = line_end

    dx = ex - sx
    dy = ey - sy

    ts: list[float] = []
    EPS = 1e-9

    # Slab test on X axis (left and right edges of tile)
    if abs(dx) > EPS:
        for bx in (x0, x1):
            t = (bx - sx) / dx
            if 0.0 <= t <= 1.0:
                py = sy + t * dy
                if y0 <= py <= y1:
                    ts.append(t)

    # Slab test on Y axis (bottom and top edges of tile)
    if abs(dy) > EPS:
        for by in (y0, y1):
            t = (by - sy) / dy
            if 0.0 <= t <= 1.0:
                px = sx + t * dx
                if x0 <= px <= x1:
                    ts.append(t)

    # Deduplicate (corners touched by both axes) and sort
    return sorted({round(t, 9) for t in ts})

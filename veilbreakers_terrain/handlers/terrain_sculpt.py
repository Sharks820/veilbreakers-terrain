"""Terrain sculpting handler for precise vertex-level terrain editing (GAP-09).

Provides:
- handle_sculpt_terrain: Sculpt terrain mesh at specific world coordinates.
- Pure-logic brush/falloff math (testable without Blender).

Operations:
  raise   -- displace vertices upward within radius with falloff
  lower   -- displace vertices downward
  smooth  -- average vertex heights within radius (Laplacian smooth on Z)
  flatten -- set vertices to average height within radius
  stamp   -- apply a heightmap pattern at position

All brush math is in pure functions for testability.
"""

from __future__ import annotations

import math

import numpy as np

try:
    from scipy import ndimage as _scipy_ndimage
    _SCIPY_AVAILABLE = True
except ImportError:
    _scipy_ndimage = None  # type: ignore[assignment]
    _SCIPY_AVAILABLE = False

import bmesh
import bpy


# ---------------------------------------------------------------------------
# Pure-logic brush helpers (testable without Blender)
# ---------------------------------------------------------------------------

# Falloff functions: distance [0..1] -> strength [0..1]
# All callables accept a scalar float and return float.
_FALLOFF_FUNCTIONS = {
    "smooth":   lambda d: float(0.5 * (1.0 + math.cos(math.pi * d))) if d < 1.0 else 0.0,
    "linear":   lambda d: float(max(0.0, 1.0 - d)) if d < 1.0 else 0.0,
    "gaussian": lambda d: float(math.exp(-4.0 * d * d)) if d < 1.0 else 0.0,
    "sphere":   lambda d: float(max(0.0, 1.0 - d * d)) if d < 1.0 else 0.0,
    # Legacy aliases kept for backward compatibility
    "sharp":    lambda d: float(max(0.0, 1.0 - d * d)) if d < 1.0 else 0.0,
    "constant": lambda d: 1.0 if d < 1.0 else 0.0,
}


def get_falloff_value(distance_normalized: float, falloff: str = "smooth") -> float:
    """Compute falloff strength for a normalized distance [0..1].

    Supports: "smooth" (cosine), "linear", "gaussian", "sphere" (1-(d/r)^2),
    "sharp" (alias for sphere), "constant".

    Args:
        distance_normalized: Distance from brush center divided by radius (0=center, 1=edge).
        falloff: Falloff curve name.

    Returns:
        Falloff strength clamped to [0..1].
    """
    fn = _FALLOFF_FUNCTIONS.get(falloff)
    if fn is None:
        raise ValueError(
            f"Unknown falloff: {falloff!r}. Valid: {sorted(_FALLOFF_FUNCTIONS)}"
        )
    # Clamp input to [0, 1] before applying falloff, result also clamped.
    d = float(min(max(distance_normalized, 0.0), 1.0))
    return float(min(max(fn(d), 0.0), 1.0))


def compute_brush_weights(
    vert_positions_2d: list[tuple[float, float]],
    brush_center: tuple[float, float],
    brush_radius: float,
    falloff: str = "smooth",
    normalize: bool = False,
) -> list[tuple[int, float]]:
    """Compute per-vertex brush weights using a vectorized numpy falloff kernel.

    Only considers XY distance (terrain is sculpted vertically).

    Falloff types: "smooth" (cosine), "linear", "gaussian", "sphere",
    "sharp" (alias sphere), "constant".

    Args:
        vert_positions_2d: List of (x, y) positions for each vertex.
        brush_center: (bx, by) center of the brush in world XY.
        brush_radius: Brush radius in world units.
        falloff: Falloff curve name.
        normalize: If True, normalize so all weights sum to 1.0.

    Returns:
        List of (vertex_index, weight) tuples for vertices within radius.
        Only vertices with weight > 0 are included.
    """
    if brush_radius <= 0 or len(vert_positions_2d) == 0:
        return []

    # Vectorized distance computation
    pts = np.asarray(vert_positions_2d, dtype=np.float64)  # (N, 2)
    bx, by = float(brush_center[0]), float(brush_center[1])
    cx = np.array([bx, by], dtype=np.float64)

    diff = pts - cx                          # (N, 2)
    dist = np.sqrt((diff ** 2).sum(axis=1))  # (N,)
    norm_dist = dist / float(brush_radius)   # [0..inf]

    in_radius = norm_dist < 1.0
    if not in_radius.any():
        return []

    indices = np.where(in_radius)[0]
    nd_in = norm_dist[indices]

    fn = _FALLOFF_FUNCTIONS.get(falloff)
    if fn is None:
        raise ValueError(
            f"Unknown falloff: {falloff!r}. Valid: {sorted(_FALLOFF_FUNCTIONS)}"
        )

    # Vectorize the scalar falloff function
    weights_in = np.array([fn(float(d)) for d in nd_in], dtype=np.float64)
    weights_in = np.clip(weights_in, 0.0, 1.0)

    positive = weights_in > 0.0
    if not positive.any():
        return []

    indices = indices[positive]
    weights_in = weights_in[positive]

    if normalize:
        total = weights_in.sum()
        if total > 0.0:
            weights_in = weights_in / total

    return [(int(i), float(w)) for i, w in zip(indices, weights_in)]


def compute_raise_displacements(
    vert_heights: list[float],
    weights: list[tuple[int, float]],
    strength: float,
    brush_size: float = 1.0,
    max_height: float = float("inf"),
) -> dict[int, float]:
    """Compute Z displacements for 'raise' operation.

    Displacement = weight * strength * brush_size, clamped to max_height.

    Args:
        vert_heights: Current Z values for all vertices.
        weights: (index, weight) tuples from compute_brush_weights.
        strength: Displacement multiplier.
        brush_size: Brush radius, scales displacement magnitude.
        max_height: Ceiling; displaced values are clamped below this.

    Returns:
        Dict mapping vertex index -> new Z value.
    """
    result: dict[int, float] = {}
    for idx, w in weights:
        delta = w * float(strength) * float(brush_size)
        new_z = float(vert_heights[idx]) + delta
        if max_height < float("inf"):
            new_z = min(new_z, float(max_height))
        result[idx] = new_z
    return result


def compute_lower_displacements(
    vert_heights: list[float],
    weights: list[tuple[int, float]],
    strength: float,
    brush_size: float = 1.0,
    min_height: float = float("-inf"),
) -> dict[int, float]:
    """Compute Z displacements for 'lower' operation.

    Displacement = -(weight * strength * brush_size), clamped to min_height floor.

    Args:
        vert_heights: Current Z values for all vertices.
        weights: (index, weight) tuples from compute_brush_weights.
        strength: Displacement magnitude.
        brush_size: Brush radius, scales displacement magnitude.
        min_height: Floor; displaced values are clamped above this.

    Returns:
        Dict mapping vertex index -> new Z value.
    """
    result: dict[int, float] = {}
    for idx, w in weights:
        delta = w * float(strength) * float(brush_size)
        new_z = float(vert_heights[idx]) - delta
        if min_height > float("-inf"):
            new_z = max(new_z, float(min_height))
        result[idx] = new_z
    return result


def compute_smooth_displacements(
    vert_positions: list[tuple[float, float, float]],
    adjacency: dict[int, list[int]],
    weights: list[tuple[int, float]],
    smooth_strength: float = 1.0,
    hmap_grid: np.ndarray | None = None,
) -> dict[int, float]:
    """Compute Z displacements for 'smooth' operation.

    Uses diffusion-based (Laplacian) smoothing:
        lap[i]   = avg_neighbor_z[i] - z[i]          (unweighted Laplacian)
        delta[i] = brush_weight[i] * smooth_strength * lap[i]

    When ``hmap_grid`` is provided (a 2-D numpy array matching a regular grid)
    scipy.ndimage.uniform_filter is used for the Laplacian, which is faster
    and avoids boundary bias. Otherwise falls back to the adjacency-list path.

    Args:
        vert_positions: Full (x, y, z) positions for all vertices.
        adjacency: Dict mapping vertex index to neighbor vertex indices.
        weights: (index, weight) tuples from compute_brush_weights.
        smooth_strength: Blend factor in [0..1] (1 = full Laplacian step).
        hmap_grid: Optional 2-D float array for scipy fast path.

    Returns:
        Dict mapping vertex index -> new Z value.
    """
    result: dict[int, float] = {}
    weight_map = dict(weights)
    affected = set(weight_map.keys())

    if _SCIPY_AVAILABLE and hmap_grid is not None:
        # Fast path: uniform_filter Laplacian on the full grid.
        grid = np.asarray(hmap_grid, dtype=np.float64)
        smoothed = _scipy_ndimage.uniform_filter(grid, size=3, mode="reflect")
        lap_grid = smoothed - grid  # Laplacian residual
        rows, cols = grid.shape
        for idx in affected:
            current_z = float(vert_positions[idx][2])
            row = min(rows - 1, max(0, int(idx // cols)))
            col = min(cols - 1, max(0, int(idx % cols)))
            lap = float(lap_grid[row, col])
            w = weight_map[idx]
            result[idx] = current_z + w * float(smooth_strength) * lap
    else:
        # Adjacency-list Laplacian (vertex-mesh path).
        for idx in affected:
            neighbors = adjacency.get(idx, [])
            if not neighbors:
                continue
            avg_z = sum(float(vert_positions[n][2]) for n in neighbors) / len(neighbors)
            current_z = float(vert_positions[idx][2])
            w = weight_map[idx]
            lap = avg_z - current_z
            result[idx] = current_z + w * float(smooth_strength) * lap

    return result


def compute_flatten_displacements(
    vert_heights: list[float],
    weights: list[tuple[int, float]],
    target_height: float | None = None,
    flatten_strength: float = 1.0,
) -> dict[int, float]:
    """Compute Z displacements for 'flatten' operation.

    Each affected vertex moves toward a target height:
        delta[i] = brush_weight[i] * flatten_strength * (target_height - z[i])

    Target height defaults to the brush-weighted average of heights inside the
    brush (proper Houdini-style flatten), or can be specified explicitly.

    Args:
        vert_heights: Current Z values for all vertices.
        weights: (index, weight) tuples from compute_brush_weights.
        target_height: Explicit target Z. If None, computed as weighted average.
        flatten_strength: Blend factor in [0..1].

    Returns:
        Dict mapping vertex index -> new Z value.
    """
    if not weights:
        return {}

    if target_height is None:
        # Brush-weighted average height (numerically stable)
        indices = [idx for idx, _ in weights]
        ws = np.array([w for _, w in weights], dtype=np.float64)
        hs = np.array([float(vert_heights[idx]) for idx in indices], dtype=np.float64)
        total_w = ws.sum()
        target_height = float(np.dot(ws, hs) / total_w) if total_w > 0.0 else float(np.mean(hs))

    target = float(target_height)
    strength = float(flatten_strength)
    result: dict[int, float] = {}
    for idx, w in weights:
        current = float(vert_heights[idx])
        result[idx] = current + w * strength * (target - current)
    return result


def compute_stamp_displacements(
    vert_positions_2d: list[tuple[float, float]],
    vert_heights: list[float],
    weights: list[tuple[int, float]],
    brush_center: tuple[float, float],
    brush_radius: float,
    heightmap: list[list[float]],
    stamp_strength: float = 1.0,
) -> dict[int, float]:
    """Compute Z displacements for 'stamp' operation.

    Samples the stamp heightmap with bilinear interpolation and applies:
        delta[i] = brush_weight[i] * stamp_strength * bilinear_sample(uv)

    Args:
        vert_positions_2d: (x, y) for each vertex.
        vert_heights: Current Z values.
        weights: Brush weights.
        brush_center: Center of the stamp in world XY.
        brush_radius: Radius of the stamp area.
        heightmap: 2D grid of height values [row][col], normalized [0..1].
        stamp_strength: Scale factor for the heightmap values.

    Returns:
        Dict mapping vertex index -> new Z value.
    """
    if not weights or not heightmap:
        return {}

    rows = len(heightmap)
    cols = len(heightmap[0]) if rows > 0 else 0
    if rows == 0 or cols == 0:
        return {}

    # Convert heightmap to numpy for bilinear sampling
    hm = np.asarray(heightmap, dtype=np.float64)  # (rows, cols)

    bx, by = float(brush_center[0]), float(brush_center[1])
    inv_diam = 1.0 / (2.0 * float(brush_radius))
    result: dict[int, float] = {}

    for idx, w in weights:
        vx, vy = vert_positions_2d[idx]
        # Map vertex position to heightmap UV [0..1]
        u = ((vx - bx) + brush_radius) * inv_diam
        v = ((vy - by) + brush_radius) * inv_diam
        u = float(min(max(u, 0.0), 1.0))
        v = float(min(max(v, 0.0), 1.0))

        # Bilinear interpolation
        fx = u * (cols - 1)
        fy = v * (rows - 1)
        x0 = int(fx)
        y0 = int(fy)
        x1 = min(x0 + 1, cols - 1)
        y1 = min(y0 + 1, rows - 1)
        tx = fx - x0
        ty = fy - y0

        h00 = hm[y0, x0]
        h10 = hm[y0, x1]
        h01 = hm[y1, x0]
        h11 = hm[y1, x1]
        h_val = (
            h00 * (1.0 - tx) * (1.0 - ty)
            + h10 * tx * (1.0 - ty)
            + h01 * (1.0 - tx) * ty
            + h11 * tx * ty
        )

        result[idx] = float(vert_heights[idx]) + h_val * float(stamp_strength) * w

    return result


# ---------------------------------------------------------------------------
# Blender handler (requires bpy + bmesh at runtime)
# ---------------------------------------------------------------------------


def _build_adjacency(bm_obj) -> dict[int, list[int]]:
    """Build vertex adjacency map from a bmesh object."""
    adj: dict[int, list[int]] = {}
    for v in bm_obj.verts:
        adj[v.index] = [e.other_vert(v).index for e in v.link_edges]
    return adj


def handle_sculpt_terrain(params: dict) -> dict:
    """Sculpt terrain at specific coordinates (GAP-09).

    Params:
        terrain_name: str -- Name of the terrain mesh object.
        position: [x, y] -- Center of brush in world XY.
        radius: float -- Brush radius.
        strength: float -- Displacement amount.
        brush_mode / operation: str -- "raise" | "lower" | "smooth" | "flatten" | "stamp".
        falloff: str -- "smooth" | "linear" | "gaussian" | "sphere" | "constant" (default "smooth").
        heightmap: list[list[float]] -- 2D height grid for stamp operation.
        height_min: float -- Terrain floor for clip (default -inf).
        height_max: float -- Terrain ceiling for clip (default inf).

    Returns dict with operation details and affected vertex count.
    """
    terrain_name = params.get("terrain_name")
    obj = bpy.data.objects.get(terrain_name)
    if not obj or obj.type != "MESH":
        raise ValueError(f"Terrain mesh object not found: {terrain_name}")

    position = params.get("position", [0, 0])
    radius = float(params.get("radius", 5.0))
    strength = float(params.get("strength", 1.0))
    # Accept both "brush_mode" (new) and "operation" (legacy key)
    operation = str(params.get("brush_mode", params.get("operation", "raise")))
    falloff = str(params.get("falloff", "smooth"))
    heightmap = params.get("heightmap")
    height_min = float(params.get("height_min", float("-inf")))
    height_max = float(params.get("height_max", float("inf")))

    valid_ops = ("raise", "lower", "smooth", "flatten", "stamp")
    if operation not in valid_ops:
        raise ValueError(
            f"Unknown terrain sculpt operation: {operation!r}. Valid: {valid_ops}"
        )

    brush_center = (float(position[0]), float(position[1]))

    bm = bmesh.new()
    new_heights: dict[int, float] = {}
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()

        # Extract vertex data
        positions_2d = [(v.co.x, v.co.y) for v in bm.verts]
        positions_3d = [(v.co.x, v.co.y, v.co.z) for v in bm.verts]
        heights = [v.co.z for v in bm.verts]

        # Compute brush weights using the upgraded kernel
        weights = compute_brush_weights(positions_2d, brush_center, radius, falloff)

        if not weights:
            return {
                "terrain_name": terrain_name,
                "operation": operation,
                "affected_vertices": 0,
                "detail": "No vertices within brush radius",
            }

        # Dispatch to the correct compute function
        if operation == "raise":
            new_heights = compute_raise_displacements(
                heights, weights, strength,
                brush_size=1.0, max_height=height_max,
            )
        elif operation == "lower":
            new_heights = compute_lower_displacements(
                heights, weights, strength,
                brush_size=1.0, min_height=height_min,
            )
        elif operation == "smooth":
            adjacency = _build_adjacency(bm)
            new_heights = compute_smooth_displacements(
                positions_3d, adjacency, weights, smooth_strength=strength,
            )
        elif operation == "flatten":
            new_heights = compute_flatten_displacements(
                heights, weights, flatten_strength=strength,
            )
        elif operation == "stamp":
            if not heightmap:
                raise ValueError("heightmap parameter required for stamp operation")
            new_heights = compute_stamp_displacements(
                positions_2d, heights, weights, brush_center, radius, heightmap, strength
            )

        # Apply displacement atomically and clip to terrain bounds
        for idx, new_z in new_heights.items():
            clamped = float(np.clip(new_z, height_min, height_max))
            bm.verts[idx].co.z = clamped
            new_heights[idx] = clamped  # keep result consistent

        # Mark dirty region (update normals + mesh)
        bm.normal_update()
        bm.to_mesh(obj.data)
        obj.data.update()

        # Tag dirty bounding box so scene updates pick up the change
        try:
            obj.data.tag = True
        except AttributeError:
            pass

    finally:
        bm.free()

    return {
        "terrain_name": terrain_name,
        "operation": operation,
        "affected_vertices": len(new_heights),
        "brush_center": list(brush_center),
        "brush_radius": radius,
        "strength": strength,
        "falloff": falloff,
        "height_min": height_min,
        "height_max": height_max,
    }

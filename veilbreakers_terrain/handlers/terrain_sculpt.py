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

# Lazy-import guard: brush falloff math is pure-Python and testable without
# Blender, but handle_sculpt_terrain needs bpy/bmesh. Guard the imports so
# transitive imports outside Blender do not crash.
try:
    import bmesh
    import bpy
    _HAS_BPY = True
except ModuleNotFoundError:
    bmesh = None  # type: ignore[assignment]
    bpy = None  # type: ignore[assignment]
    _HAS_BPY = False


def _require_bpy() -> None:
    """Raise RuntimeError if bpy/bmesh are not available (outside Blender)."""
    if not _HAS_BPY:
        raise RuntimeError(
            "This function requires Blender (bpy + bmesh). "
            "It cannot run outside the Blender Python runtime."
        )


# ---------------------------------------------------------------------------
# Pure-logic brush helpers (testable without Blender)
# ---------------------------------------------------------------------------

# Falloff functions: normalized distance d in [0..1] -> strength in [0..1].
# All callables accept a scalar float and return a float already in [0..1].
#
# Curve definitions match AAA DCC conventions (Houdini, ZBrush, Blender):
#   smooth  — smoothstep Hermite S-curve  3d²-2d³     (C1-continuous, AAA default)
#   linear  — straight ramp               1-d
#   sphere  — spherical cap               √(1-d²)     (circular cross-section falloff)
#   root    — square-root ramp            √(1-d)      (slower-to-fade, soft edge)
#   sharp   — quadratic concave           1-d²        (fast fade from center)
#   gaussian— Gaussian bell               exp(-4d²)   (narrow peak, ZBrush Clay)
#   constant— hard-edge flat top          1.0 inside  (useful for debug / uniform)
_FALLOFF_FUNCTIONS: dict[str, object] = {
    "smooth":   lambda d: float(2.0 * d * d * d - 3.0 * d * d + 1.0) if d < 1.0 else 0.0,
    "linear":   lambda d: float(1.0 - d) if d < 1.0 else 0.0,
    "sphere":   lambda d: float(math.sqrt(max(0.0, 1.0 - d * d))) if d < 1.0 else 0.0,
    "root":     lambda d: float(math.sqrt(max(0.0, 1.0 - d))) if d < 1.0 else 0.0,
    "sharp":    lambda d: float(max(0.0, 1.0 - d * d)) if d < 1.0 else 0.0,
    "gaussian": lambda d: float(math.exp(-4.0 * d * d)) if d < 1.0 else 0.0,
    "constant": lambda d: 1.0 if d < 1.0 else 0.0,
}


def get_falloff_value(distance_normalized: float, falloff: str = "smooth") -> float:
    """Compute falloff strength for a normalized distance in [0, 1].

    Curve library (matches Houdini / ZBrush / Blender brush-curve presets):

    +-----------+--------------------+-------------------------------------+
    | Name      | Formula            | Character                           |
    +-----------+--------------------+-------------------------------------+
    | smooth    | 3d²-2d³            | Hermite smoothstep — C1, AAA default|
    | linear    | 1-d                | Straight ramp                       |
    | sphere    | √(1-d²)            | Circular cross-section              |
    | root      | √(1-d)             | Slow fade, soft outer edge          |
    | sharp     | 1-d²               | Fast fade from center outward       |
    | gaussian  | exp(-4d²)          | Narrow bell peak (ZBrush Clay)      |
    | constant  | 1 inside, 0 at rim | Hard-edge flat top                  |
    +-----------+--------------------+-------------------------------------+

    All curves are guaranteed to return exactly 0.0 at d ≥ 1 and 1.0 at d = 0
    (smooth/sphere/root/sharp/linear) or near-1 (gaussian).

    Args:
        distance_normalized: Euclidean distance from brush center divided by
            brush radius.  Values outside [0, 1] are clamped before lookup.
        falloff: Curve name from the table above.

    Returns:
        Falloff strength clamped to [0, 1].
    """
    fn = _FALLOFF_FUNCTIONS.get(falloff)
    if fn is None:
        raise ValueError(
            f"Unknown falloff: {falloff!r}. Valid: {sorted(_FALLOFF_FUNCTIONS)}"
        )
    # Clamp input to [0, 1] before applying falloff, result also clamped.
    d = float(min(max(distance_normalized, 0.0), 1.0))
    return float(min(max(fn(d), 0.0), 1.0))


def _build_falloff_lut(falloff: str, lut_size: int = 1024) -> np.ndarray:
    """Pre-sample a falloff curve into a 1-D float64 LUT of *lut_size* bins.

    Index 0 corresponds to d=0 (brush centre), index lut_size-1 to d→1⁻.
    The extra sentinel at index lut_size is set to 0.0 so that bilinear
    look-ups never read past the array end.

    Args:
        falloff: Curve name recognised by ``_FALLOFF_FUNCTIONS``.
        lut_size: Number of evenly spaced samples across [0, 1).

    Returns:
        float64 array of shape (lut_size + 1,).
    """
    fn = _FALLOFF_FUNCTIONS.get(falloff)
    if fn is None:
        raise ValueError(
            f"Unknown falloff: {falloff!r}. Valid: {sorted(_FALLOFF_FUNCTIONS)}"
        )
    d_vals = np.linspace(0.0, 1.0, lut_size, endpoint=False)
    lut = np.array([fn(float(d)) for d in d_vals], dtype=np.float64)
    lut = np.clip(lut, 0.0, 1.0)
    # Sentinel: value at exactly d=1 is 0
    lut = np.append(lut, 0.0)
    return lut


def _sample_falloff_lut(lut: np.ndarray, norm_dist: np.ndarray) -> np.ndarray:
    """Bilinear (linear) sub-bin interpolation into a pre-sampled falloff LUT.

    Treats the LUT as a piecewise-linear curve sampled at uniform d intervals.
    For each normalized distance value the two bracketing LUT bins are read and
    the result is the weighted blend — identical in principle to the bilinear
    sub-pixel sampling used in GPU texture filtering and in Houdini / UE's
    brush-weight kernels.

    Args:
        lut: Pre-built array from ``_build_falloff_lut`` of shape (N+1,).
        norm_dist: 1-D float64 array of normalized distances in [0, 1).

    Returns:
        float64 array of the same shape as *norm_dist*, values in [0, 1].
    """
    lut_size = len(lut) - 1  # sentinel excluded from bin count
    # Map [0,1) -> [0, lut_size)
    frac_idx = norm_dist * lut_size          # float index
    lo = np.floor(frac_idx).astype(np.int64)
    lo = np.clip(lo, 0, lut_size - 1)
    hi = lo + 1  # hi is at most lut_size (the sentinel index)
    t = frac_idx - lo.astype(np.float64)     # fractional part in [0, 1)
    return lut[lo] * (1.0 - t) + lut[hi] * t


def compute_brush_weights(
    vert_positions_2d: list[tuple[float, ...]] | np.ndarray,
    brush_center: tuple[float, ...],
    brush_radius: float,
    falloff: str = "smooth",
    normalize: bool = False,
    pressure: float = 1.0,
) -> list[tuple[int, float]]:
    """Compute per-vertex brush weights with bilinear sub-cell LUT sampling.

    Projects onto XY plane (terrain sculpting is vertical).  Accepts both 2-D
    ``(x, y)`` and 3-D ``(x, y, z)`` vertex arrays; the Z component is ignored
    for distance calculation.

    **Bilinear sub-cell sampling** — the falloff curve is pre-sampled into a
    1024-bin LUT and each vertex's normalized distance is mapped to a fractional
    LUT index.  The two bracketing bins are blended with the fractional
    remainder (exactly as GPU bilinear texture filtering works), eliminating the
    quantisation banding that arises from evaluating the curve function once per
    vertex at coarse grid positions.  This matches the brush-weight kernel used
    in Houdini heightfield brushes and UE Landscape tool.

    The optional ``pressure`` parameter (tablet pen pressure or equivalent,
    in [0..1]) uniformly scales all output weights after the LUT look-up.

    Falloff types: "smooth" (smoothstep), "linear", "sphere", "root", "sharp",
    "gaussian", "constant".

    Args:
        vert_positions_2d: List/array of (x, y[, z]) positions for each vertex.
        brush_center: (bx, by[, bz]) center of the brush; only XY is used.
        brush_radius: Brush radius in world units.
        falloff: Falloff curve name.
        normalize: If True, normalize so all weights sum to 1.0 (before
            pressure scaling).
        pressure: Pen/tablet pressure in [0..1]; multiplied into every weight.

    Returns:
        List of (vertex_index, weight) tuples for vertices within radius.
        Only vertices with weight > 0 are included.
    """
    if brush_radius <= 0 or len(vert_positions_2d) == 0:
        return []

    # Validate falloff name early so the error is clear.
    if falloff not in _FALLOFF_FUNCTIONS:
        raise ValueError(
            f"Unknown falloff: {falloff!r}. Valid: {sorted(_FALLOFF_FUNCTIONS)}"
        )

    # Vectorized XY-only distance computation — works for 2-D and 3-D input.
    pts = np.asarray(vert_positions_2d, dtype=np.float64)
    pts_xy = pts[:, :2]
    cx = np.asarray(brush_center, dtype=np.float64)[:2]

    dist = np.linalg.norm(pts_xy - cx, axis=1)   # (N,) Euclidean XY distance
    norm_dist = dist / float(brush_radius)         # normalised to [0, ∞)

    in_radius = norm_dist < 1.0
    if not in_radius.any():
        return []

    indices = np.where(in_radius)[0]
    nd_in = norm_dist[indices]  # all < 1.0

    # Build a 1024-bin LUT and sample with bilinear sub-cell interpolation.
    lut = _build_falloff_lut(falloff, lut_size=1024)
    weights_in = _sample_falloff_lut(lut, nd_in)
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

    # Apply pressure scaling (tablet pen pressure or equivalent).
    weights_in = weights_in * float(np.clip(pressure, 0.0, 1.0))

    return [(int(i), float(w)) for i, w in zip(indices, weights_in)]


def compute_raise_displacements(
    vert_heights: list[float],
    weights: list[tuple[int, float]],
    strength: float,
    brush_size: float = 1.0,
    max_height: float = float("inf"),
    use_normal: bool = False,
    vert_normals: list[tuple[float, float, float]] | None = None,
) -> dict[int, float]:
    """Compute Z displacements for 'raise' operation.

    Displacement = weight * strength * brush_size, clamped to max_height.

    When ``use_normal`` is True the displacement is projected along each
    vertex's surface normal rather than world-Z.  ``vert_normals`` must be
    supplied in that case; each entry is the ``(nx, ny, nz)`` unit normal for
    the corresponding vertex.  Only the Z component of the offset is recorded
    (the dict still stores new *height* values), which keeps the return type
    identical to the non-normal path while producing physically correct
    vertical movement for sloped surfaces.

    Args:
        vert_heights: Current Z values for all vertices.
        weights: (index, weight) tuples from compute_brush_weights.
        strength: Displacement multiplier.
        brush_size: Brush radius, scales displacement magnitude.
        max_height: Ceiling; displaced values are clamped below this.
        use_normal: When True, displace along the vertex normal direction
            instead of world Z.
        vert_normals: Per-vertex surface normals ``(nx, ny, nz)``. Required
            when ``use_normal`` is True; silently ignored otherwise.

    Returns:
        Dict mapping vertex index -> new Z value.
    """
    result: dict[int, float] = {}
    for idx, w in weights:
        base_delta = w * float(strength) * float(brush_size)
        if use_normal and vert_normals is not None:
            nx, ny, nz = vert_normals[idx]
            # Scale the full normal displacement vector and take only its Z
            # contribution so height-map storage stays consistent.
            norm_len = math.sqrt(nx * nx + ny * ny + nz * nz)
            if norm_len > 1e-8:
                nz_unit = nz / norm_len
            else:
                nz_unit = 1.0
            delta = base_delta * nz_unit
        else:
            delta = base_delta
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
    floor_clamp: float | None = None,
) -> dict[int, float]:
    """Compute Z displacements for 'lower' operation.

    Displacement = -(weight * strength * brush_size), clamped to a floor.

    Two floor parameters are available and the *strictest* (highest) value
    always wins:

    * ``min_height`` — legacy per-call floor (e.g. terrain height_min from
      the sculpt handler).
    * ``floor_clamp`` — explicit hard floor, useful to prevent vertices from
      being pushed below a world reference level (e.g. 0.0 for sea level or
      below a collision plane).  Defaults to ``None`` (no additional clamp).

    Setting neither leaves behaviour identical to the original
    (unclamped subtraction).

    Args:
        vert_heights: Current Z values for all vertices.
        weights: (index, weight) tuples from compute_brush_weights.
        strength: Displacement magnitude.
        brush_size: Brush radius, scales displacement magnitude.
        min_height: Soft floor; displaced values are clamped above this.
        floor_clamp: Hard world-space floor.  When provided, no vertex will
            be lowered below this value regardless of strength or brush size.

    Returns:
        Dict mapping vertex index -> new Z value.
    """
    # Resolve the effective floor: strictest of min_height and floor_clamp.
    effective_floor: float = float("-inf")
    if min_height > float("-inf"):
        effective_floor = float(min_height)
    if floor_clamp is not None:
        effective_floor = max(effective_floor, float(floor_clamp))

    result: dict[int, float] = {}
    for idx, w in weights:
        delta = w * float(strength) * float(brush_size)
        new_z = float(vert_heights[idx]) - delta
        if effective_floor > float("-inf"):
            new_z = max(new_z, effective_floor)
        result[idx] = new_z
    return result


def compute_smooth_displacements(
    vert_positions: list[tuple[float, float, float]],
    adjacency: dict[int, list[int]],
    weights: list[tuple[int, float]],
    smooth_strength: float = 1.0,
    hmap_grid: np.ndarray | None = None,
    faces: list[tuple[int, ...]] | None = None,
    iterations: int = 1,
    brush_radius: float | None = None,
) -> dict[int, float]:
    """Compute Z displacements for 'smooth' operation (Gaussian-weighted Laplacian).

    Uses a **Gaussian-weighted neighbourhood average** — each neighbour's
    contribution is weighted by exp(-d²/2σ²) where d is its 3-D distance from
    the central vertex and σ = brush_radius/3 (or the mean edge-length/3 when
    brush_radius is not supplied).  This matches ZBrush Smooth and Houdini's
    heightfield-smooth operator, both of which use Gaussian kernels rather than
    simple box or inverse-distance averages.

    Compared with a box average:
    * The Gaussian kernel concentrates influence on the closest neighbours,
      preserving sharp ridges better at low strength values.
    * It does not produce the "staircase" artefact that uniform Laplacian
      smoothing introduces on irregular quad-dominant meshes.

    Multiple Jacobi iterations are supported via ``iterations`` (default 1 to
    preserve backward compatibility with existing tests).  Each additional pass
    re-applies the Gaussian smooth to the updated positions, producing a result
    similar to iterative Laplacian relaxation at low cost.

    When ``faces`` is provided the adjacency dict is rebuilt from those faces
    (more accurate than a stale caller-supplied dict).

    When ``hmap_grid`` is provided and scipy is available, a fast Gaussian grid
    path is used instead of the adjacency-list kernel.

    Args:
        vert_positions: Full (x, y, z) positions for all vertices.
        adjacency: Dict mapping vertex index to neighbour vertex indices.
            Used as fallback when ``faces`` is None.
        weights: (index, weight) tuples from compute_brush_weights.
        smooth_strength: Blend factor in [0..1] (1.0 = full Gaussian step).
        hmap_grid: Optional 2-D float array for the scipy fast path (Z only).
        faces: Optional list of face vertex-index tuples for adjacency rebuild.
        iterations: Number of Gaussian smoothing passes (default 1).
        brush_radius: Brush radius in world units; sets σ = radius/3.
            When None the σ is estimated from the mean 1-ring edge length.

    Returns:
        Dict mapping vertex index -> new Z value.
    """
    weight_map = dict(weights)
    affected = set(weight_map.keys())

    # ------------------------------------------------------------------
    # Rebuild adjacency from faces when provided (more accurate).
    # ------------------------------------------------------------------
    if faces is not None:
        adj: dict[int, list[int]] = {}
        for face in faces:
            for i, vi in enumerate(face):
                nbrs = adj.setdefault(vi, [])
                for j, vj in enumerate(face):
                    if i != j and vj not in nbrs:
                        nbrs.append(vj)
        adjacency = adj

    # ------------------------------------------------------------------
    # Fast path: scipy Gaussian grid smooth (Z only).
    # ------------------------------------------------------------------
    if _SCIPY_AVAILABLE and hmap_grid is not None:
        grid = np.asarray(hmap_grid, dtype=np.float64)
        # σ in grid cells: default radius/3 expressed as grid cells, or 1.0
        sigma_cells = (float(brush_radius) / 3.0) if brush_radius else 1.0
        sigma_cells = max(sigma_cells, 0.3)
        smoothed = _scipy_ndimage.gaussian_filter(
            grid, sigma=sigma_cells, mode="reflect"
        )
        lap_grid = smoothed - grid
        rows, cols = grid.shape
        result: dict[int, float] = {}
        for idx in affected:
            current_z = float(vert_positions[idx][2])
            row = min(rows - 1, max(0, int(idx // cols)))
            col = min(cols - 1, max(0, int(idx % cols)))
            lap = float(lap_grid[row, col])
            w = weight_map[idx]
            result[idx] = current_z + w * float(smooth_strength) * lap
        return result

    # ------------------------------------------------------------------
    # Adjacency-list path: Gaussian-weighted Laplacian over XYZ.
    # ------------------------------------------------------------------
    pts = np.array(vert_positions, dtype=np.float64)  # (V, 3)
    iters = max(1, int(iterations))
    strength = float(smooth_strength)

    # Estimate σ: use brush_radius/3 if given, else mean 1-ring edge length/3.
    if brush_radius is not None and brush_radius > 0.0:
        sigma = float(brush_radius) / 3.0
    else:
        # Sample mean edge length across affected vertices.
        edge_lengths: list[float] = []
        for idx in affected:
            nbrs = adjacency.get(idx, [])
            if nbrs:
                center = pts[idx]
                for ni in nbrs:
                    edge_lengths.append(float(np.linalg.norm(pts[ni] - center)))
        sigma = (float(np.mean(edge_lengths)) / 3.0) if edge_lengths else 1.0
    sigma = max(sigma, 1e-8)
    two_sigma2 = 2.0 * sigma * sigma  # denominator for exp(-d²/2σ²)

    updated: set[int] = set()

    for _ in range(iters):
        new_pts = pts.copy()
        for idx in affected:
            neighbors = adjacency.get(idx, [])
            if not neighbors:
                continue

            updated.add(idx)
            center = pts[idx]                          # (3,)
            nbr_positions = pts[list(neighbors)]       # (K, 3)

            # Gaussian weights: g_k = exp(-||center - nbr_k||² / 2σ²)
            diffs = nbr_positions - center             # (K, 3)
            dists_sq = np.einsum("ij,ij->i", diffs, diffs)  # (K,) squared distances
            gauss_w = np.exp(-dists_sq / two_sigma2)   # (K,)
            total_gw = gauss_w.sum()
            if total_gw < 1e-12:
                continue
            gauss_w /= total_gw

            # Gaussian-weighted centroid and Laplacian vector
            weighted_avg = gauss_w @ nbr_positions     # (3,)
            laplacian = weighted_avg - center          # (3,)

            brush_w = weight_map[idx]
            new_pts[idx] = center + brush_w * strength * laplacian

        pts = new_pts

    return {idx: float(pts[idx, 2]) for idx in updated}


def compute_flatten_displacements(
    vert_heights: list[float],
    weights: list[tuple[int, float]],
    target_height: float | None = None,
    flatten_strength: float = 1.0,
    vert_positions: list[tuple[float, float, float]] | None = None,
) -> dict[int, float]:
    """Compute Z displacements for 'flatten' operation.

    Each affected vertex moves toward a *best-fit plane* rather than a single
    average height, which eliminates the low-frequency waviness that the old
    unweighted-mean approach introduced on sloped or curved terrain.

    **Plane fit algorithm** (weighted least-squares via SVD):
    1. Compute the brush-weight-centroid of the affected vertex positions.
    2. Centre the positions around that centroid.
    3. Form the weighted scatter matrix ``A = V^T W V`` and decompose with SVD.
    4. The right singular vector for the smallest singular value is the
       best-fit plane normal.
    5. Each vertex's target height is its projection back onto the plane
       through the centroid along the plane normal.

    The plane fit requires 3-D positions (``vert_positions``).  When they are
    not supplied the function falls back to the original brush-weighted average
    height (scalar target), preserving backward compatibility with callers that
    only pass heights.

    Args:
        vert_heights: Current Z values for all vertices.
        weights: (index, weight) tuples from compute_brush_weights.
        target_height: Explicit target Z.  When provided, skips plane fit and
            uses this constant as the target (useful for "flatten to cursor"
            workflows).
        flatten_strength: Blend factor in [0..1].
        vert_positions: Full (x, y, z) positions for all vertices.  When
            supplied (and ``target_height`` is None) a weighted SVD plane fit
            is used instead of the scalar weighted-mean fallback.

    Returns:
        Dict mapping vertex index -> new Z value.
    """
    if not weights:
        return {}

    strength = float(flatten_strength)

    # ------------------------------------------------------------------
    # Determine target height / target plane for each vertex.
    # ------------------------------------------------------------------
    if target_height is not None:
        # Explicit scalar target — simple constant-plane flatten.
        target = float(target_height)
        result: dict[int, float] = {}
        for idx, w in weights:
            current = float(vert_heights[idx])
            result[idx] = current + w * strength * (target - current)
        return result

    indices = [idx for idx, _ in weights]
    ws = np.array([w for _, w in weights], dtype=np.float64)  # (K,)

    if vert_positions is not None:
        # ------------------------------------------------------------------
        # Weighted least-squares plane fit (SVD).
        # ------------------------------------------------------------------
        verts = np.array(
            [vert_positions[i] for i in indices], dtype=np.float64
        )  # (K, 3)

        # Weighted centroid.
        total_w = ws.sum()
        if total_w <= 0.0:
            total_w = 1.0
        centroid = np.average(verts, weights=ws, axis=0)  # (3,)

        verts_c = verts - centroid  # (K, 3) centred

        # Weighted scatter matrix A = V^T diag(w) V  →  (3, 3)
        W = np.diag(ws / total_w)
        scatter = verts_c.T @ W @ verts_c

        _, _, Vt = np.linalg.svd(scatter)
        normal = Vt[-1]  # (3,) smallest singular vector = plane normal

        # Avoid degenerate normal (e.g. all verts coplanar in XY).
        nz = normal[2]
        if abs(nz) < 1e-6:
            # Fall back to Z-normal (horizontal plane) through centroid.
            normal = np.array([0.0, 0.0, 1.0])
            nz = 1.0

        # Target Z for vertex i: project (v_i - centroid) onto plane, then
        # recover the Z coordinate that lies on the plane.
        #   plane equation:  normal . (p - centroid) = 0
        #   solve for p_z:   p_z = centroid_z - (nx*(px-cx) + ny*(py-cy)) / nz
        result = {}
        for k, idx in enumerate(indices):
            w = ws[k]
            px, py, pz = float(vert_positions[idx][0]), float(vert_positions[idx][1]), float(vert_heights[idx])
            plane_z = float(centroid[2]) - (
                normal[0] * (px - float(centroid[0]))
                + normal[1] * (py - float(centroid[1]))
            ) / nz
            result[idx] = pz + w * strength * (plane_z - pz)
        return result

    # ------------------------------------------------------------------
    # Fallback: brush-weighted average height (no 3-D positions available).
    # ------------------------------------------------------------------
    hs = np.array([float(vert_heights[i]) for i in indices], dtype=np.float64)
    total_w = ws.sum()
    avg_h = float(np.dot(ws, hs) / total_w) if total_w > 0.0 else float(np.mean(hs))

    result = {}
    for idx, w in weights:
        current = float(vert_heights[idx])
        result[idx] = current + w * strength * (avg_h - current)
    return result


def compute_stamp_displacements(
    vert_positions_2d: list[tuple[float, float]],
    vert_heights: list[float],
    weights: list[tuple[int, float]],
    brush_center: tuple[float, float],
    brush_radius: float,
    heightmap: list[list[float]],
    stamp_strength: float = 1.0,
    blend_mode: str = "add",
    feather: float = 0.0,
) -> dict[int, float]:
    """Compute Z displacements for 'stamp' operation with blend modes and feathering.

    Samples the stamp heightmap with bilinear interpolation, then composites
    the sampled value onto the terrain using one of four blend modes — matching
    the blend operations available in Houdini heightfield-stamp, ZBrush Alpha
    stamp, and UE Landscape stamp brush.

    **Blend modes:**

    +----------+----------------------------------------------------------+
    | Mode     | Formula                                                  |
    +----------+----------------------------------------------------------+
    | add      | new_z = current_z + w * strength * h_val  (default)      |
    | replace  | new_z = lerp(current_z, h_val * strength, w)             |
    | max      | new_z = max(current_z, current_z + w * strength * h_val) |
    | min      | new_z = min(current_z, current_z + w * strength * h_val) |
    +----------+----------------------------------------------------------+

    **Feathering:** When ``feather > 0`` the effective brush weight is
    attenuated toward the outer rim.  The weight is multiplied by a smoothstep
    ramp over the outermost ``feather`` fraction of the brush radius, producing
    a smooth zero-crossing at the edge.  ``feather=0`` (default) disables this
    and preserves the original behaviour.

    Args:
        vert_positions_2d: (x, y) for each vertex.
        vert_heights: Current Z values.
        weights: (index, weight) tuples from compute_brush_weights.
        brush_center: Center of the stamp in world XY.
        brush_radius: Radius of the stamp area.
        heightmap: 2D grid of height values [row][col], normalised [0..1].
        stamp_strength: Scale factor for the heightmap values.
        blend_mode: Compositing mode — "add", "replace", "max", or "min".
        feather: Feather width as a fraction of brush radius in [0, 1).
            0 = no feathering; 0.2 = fade over outer 20 % of the radius.

    Returns:
        Dict mapping vertex index -> new Z value.
    """
    if not weights or not heightmap:
        return {}

    rows = len(heightmap)
    cols = len(heightmap[0]) if rows > 0 else 0
    if rows == 0 or cols == 0:
        return {}

    valid_modes = ("add", "replace", "max", "min")
    if blend_mode not in valid_modes:
        raise ValueError(
            f"Unknown stamp blend_mode: {blend_mode!r}. Valid: {valid_modes}"
        )

    # Convert heightmap to numpy for bilinear sampling.
    hm = np.asarray(heightmap, dtype=np.float64)  # (rows, cols)

    bx, by = float(brush_center[0]), float(brush_center[1])
    br = float(brush_radius)
    inv_diam = 1.0 / (2.0 * br)
    s = float(stamp_strength)
    feather_f = float(np.clip(feather, 0.0, 0.999))
    inner_edge = 1.0 - feather_f  # normalised radius where feather begins

    result: dict[int, float] = {}

    for idx, raw_w in weights:
        vx, vy = vert_positions_2d[idx]

        # ---- Feathering -----------------------------------------------
        # Attenuate the brush weight in the outer feather band using a
        # smoothstep ramp so the stamp fades smoothly to zero at the rim.
        if feather_f > 0.0:
            norm_d = math.sqrt((vx - bx) ** 2 + (vy - by) ** 2) / br
            norm_d = min(max(norm_d, 0.0), 1.0)
            if norm_d > inner_edge:
                # Remap norm_d from [inner_edge, 1] -> t in [0, 1], then
                # apply inverted smoothstep so weight fades 1→0.
                t = (norm_d - inner_edge) / feather_f
                fade = 1.0 - (3.0 * t * t - 2.0 * t * t * t)
                w = raw_w * fade
            else:
                w = raw_w
        else:
            w = raw_w

        # ---- Bilinear heightmap sample ---------------------------------
        u = ((vx - bx) + br) * inv_diam
        v = ((vy - by) + br) * inv_diam
        u = float(min(max(u, 0.0), 1.0))
        v = float(min(max(v, 0.0), 1.0))

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
        h_val = float(
            h00 * (1.0 - tx) * (1.0 - ty)
            + h10 * tx * (1.0 - ty)
            + h01 * (1.0 - tx) * ty
            + h11 * tx * ty
        )

        # ---- Blend mode -----------------------------------------------
        current_z = float(vert_heights[idx])
        delta = w * s * h_val

        if blend_mode == "add":
            new_z = current_z + delta
        elif blend_mode == "replace":
            # Lerp current_z toward (h_val * strength) by brush weight.
            new_z = current_z + w * (s * h_val - current_z)
        elif blend_mode == "max":
            new_z = max(current_z, current_z + delta)
        else:  # "min"
            new_z = min(current_z, current_z + delta)

        result[idx] = new_z

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
    """Sculpt terrain at specific world-space coordinates (GAP-09).

    All five sculpt modes are dispatched here.  The incoming ``position`` is in
    **world space**; the function converts it to the object's **local space**
    via the inverse of the object's world matrix before querying vertex
    distances.  This ensures brushes placed on rotated / scaled terrain objects
    work correctly — a gap in the previous implementation that caused visible
    mis-registration on any non-identity-transform terrain.

    Params:
        terrain_name: str -- Name of the terrain mesh object.
        position: [x, y] or [x, y, z] -- Brush centre in **world** space.
            Only XY (local, after transform) is used for distance queries.
        radius: float -- Brush radius in world units.
        strength: float -- Displacement magnitude / blend factor.
        brush_mode / operation: str -- One of:
            "raise" | "lower" | "smooth" | "flatten" | "stamp"
        falloff: str -- "smooth" | "linear" | "sphere" | "root" | "sharp" |
            "gaussian" | "constant"  (default "smooth").
        blend_mode: str -- For "stamp" only: "add" | "replace" | "max" | "min"
            (default "add").
        feather: float -- For "stamp" only: feather width fraction [0, 1)
            (default 0.0 = no feathering).
        heightmap: list[list[float]] -- 2D height grid for stamp operation.
        height_min: float -- Terrain floor (default -inf).
        height_max: float -- Terrain ceiling (default +inf).

    Returns:
        dict with operation details and affected vertex count.
    """
    terrain_name = params.get("terrain_name")
    obj = bpy.data.objects.get(terrain_name)
    if not obj or obj.type != "MESH":
        raise ValueError(f"Terrain mesh object not found: {terrain_name}")

    position = params.get("position", [0, 0])
    radius = float(params.get("radius", 5.0))
    strength = float(params.get("strength", 1.0))
    # Accept both "brush_mode" (new) and "operation" (legacy key).
    operation = str(params.get("brush_mode", params.get("operation", "raise")))
    falloff = str(params.get("falloff", "smooth"))
    heightmap = params.get("heightmap")
    height_min = float(params.get("height_min", float("-inf")))
    height_max = float(params.get("height_max", float("inf")))
    blend_mode = str(params.get("blend_mode", "add"))
    feather = float(params.get("feather", 0.0))

    valid_ops = ("raise", "lower", "smooth", "flatten", "stamp")
    if operation not in valid_ops:
        raise ValueError(
            f"Unknown terrain sculpt operation: {operation!r}. Valid: {valid_ops}"
        )

    # ------------------------------------------------------------------
    # World → local transform for the brush centre.
    #
    # Blender stores vertex coordinates in *object local* space inside
    # bmesh, so every distance query must happen in local space.  We
    # invert the object's 4×4 world matrix and apply it to the incoming
    # world-space position.  The radius is scaled by the object's uniform
    # scale factor (average of the three axis scales) so that a "5 m"
    # brush covers 5 m of terrain regardless of object scale.
    # ------------------------------------------------------------------
    world_pos_x = float(position[0])
    world_pos_y = float(position[1])
    world_pos_z = float(position[2]) if len(position) > 2 else 0.0

    mw = obj.matrix_world          # 4×4 Matrix
    mw_inv = mw.inverted()

    import mathutils  # available inside Blender; guarded below
    world_pt = mathutils.Vector((world_pos_x, world_pos_y, world_pos_z))
    local_pt = mw_inv @ world_pt

    # Approximate local-space radius: divide by the average absolute scale.
    scale_x = abs(mw[0][0])
    scale_y = abs(mw[1][1])
    scale_z = abs(mw[2][2])
    # Use the XY mean for the horizontal radius conversion.
    avg_scale_xy = (scale_x + scale_y) / 2.0 if (scale_x + scale_y) > 0 else 1.0
    local_radius = radius / avg_scale_xy if avg_scale_xy > 1e-8 else radius

    brush_center = (float(local_pt.x), float(local_pt.y))

    bm = bmesh.new()
    new_heights: dict[int, float] = {}
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()

        # Extract local-space vertex data.
        positions_2d = [(v.co.x, v.co.y) for v in bm.verts]
        positions_3d = [(v.co.x, v.co.y, v.co.z) for v in bm.verts]
        heights = [v.co.z for v in bm.verts]

        # Compute brush weights using bilinear LUT kernel.
        weights = compute_brush_weights(
            positions_2d, brush_center, local_radius, falloff
        )

        if not weights:
            return {
                "terrain_name": terrain_name,
                "operation": operation,
                "affected_vertices": 0,
                "detail": "No vertices within brush radius",
            }

        # ------------------------------------------------------------------
        # Dispatch to the per-operation compute function.
        # ------------------------------------------------------------------
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
                positions_3d, adjacency, weights,
                smooth_strength=strength,
                brush_radius=local_radius,
            )
        elif operation == "flatten":
            # Pass full 3-D positions so the SVD plane-fit path is used
            # rather than the simpler weighted-mean fallback.
            new_heights = compute_flatten_displacements(
                heights, weights,
                flatten_strength=strength,
                vert_positions=positions_3d,
            )
        elif operation == "stamp":
            if not heightmap:
                raise ValueError("heightmap parameter required for stamp operation")
            new_heights = compute_stamp_displacements(
                positions_2d, heights, weights,
                brush_center, local_radius, heightmap,
                stamp_strength=strength,
                blend_mode=blend_mode,
                feather=feather,
            )

        # ------------------------------------------------------------------
        # Apply displacements atomically; clip to terrain bounds.
        # ------------------------------------------------------------------
        for idx, new_z in new_heights.items():
            clamped = float(np.clip(new_z, height_min, height_max))
            bm.verts[idx].co.z = clamped
            new_heights[idx] = clamped

        # Rebuild normals and push back to the mesh datablock.
        bm.normal_update()
        bm.to_mesh(obj.data)
        obj.data.update()

        # Tag dirty bounding box so viewport / physics pick up the change.
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
        "brush_center_world": [world_pos_x, world_pos_y],
        "brush_center_local": list(brush_center),
        "brush_radius": radius,
        "local_radius": local_radius,
        "strength": strength,
        "falloff": falloff,
        "height_min": height_min,
        "height_max": height_max,
    }

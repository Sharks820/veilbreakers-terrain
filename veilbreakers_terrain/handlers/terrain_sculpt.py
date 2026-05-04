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

import importlib
import math
from collections.abc import Callable
from collections.abc import Sequence
from typing import Any
from typing import Protocol
from typing import cast

import numpy as np

try:
    from scipy import ndimage as _scipy_ndimage
except ImportError:
    _scipy_ndimage = None  # type: ignore[assignment]
_scipy_available = _scipy_ndimage is not None

# Lazy-import guard: brush falloff math is pure-Python and testable without
# Blender, but handle_sculpt_terrain needs bpy/bmesh. Guard the imports so
# transitive imports outside Blender do not crash.
try:
    bmesh = importlib.import_module("bmesh")
    bpy = importlib.import_module("bpy")
except ModuleNotFoundError:
    bmesh = None
    bpy = None
_has_bpy = bmesh is not None and bpy is not None


class _BMeshLike(Protocol):
    verts: Any


def _falloff_smooth(d: float) -> float:
    return float(2.0 * d * d * d - 3.0 * d * d + 1.0) if d < 1.0 else 0.0


def _falloff_linear(d: float) -> float:
    return float(1.0 - d) if d < 1.0 else 0.0


def _falloff_sphere(d: float) -> float:
    return float(math.sqrt(max(0.0, 1.0 - d * d))) if d < 1.0 else 0.0


def _falloff_root(d: float) -> float:
    return float(math.sqrt(max(0.0, 1.0 - d))) if d < 1.0 else 0.0


def _falloff_sharp(d: float) -> float:
    return float(max(0.0, 1.0 - d * d)) if d < 1.0 else 0.0


def _falloff_gaussian(d: float) -> float:
    return float(math.exp(-4.0 * d * d)) if d < 1.0 else 0.0


def _falloff_constant(d: float) -> float:
    return 1.0 if d < 1.0 else 0.0


def _require_bpy() -> None:
    """Raise RuntimeError if bpy/bmesh are not available (outside Blender)."""
    if not _has_bpy:
        raise RuntimeError(
            "This function requires Blender (bpy + bmesh). "
            "It cannot run outside the Blender Python runtime."
        )


def _param_float(params: dict[str, object], key: str, default: float) -> float:
    value = params.get(key)
    return float(default if value is None else cast(Any, value))


def _param_str(params: dict[str, object], key: str, default: str) -> str:
    value = params.get(key)
    return str(default if value is None else value)


def _brush_operation(params: dict[str, object]) -> str:
    value = params.get("brush_mode", params.get("operation", "raise"))
    return str(value)


def _position_xyz(value: object) -> tuple[float, float, float]:
    if value is None:
        return (0.0, 0.0, 0.0)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("position must be a sequence of at least two numbers")
    position = cast(Sequence[object], value)
    if len(position) < 2:
        raise ValueError("position must contain at least x and y")
    return (
        float(cast(Any, position[0])),
        float(cast(Any, position[1])),
        float(cast(Any, position[2])) if len(position) > 2 else 0.0,
    )


def _heightmap_from_param(value: object) -> list[list[float]] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("heightmap must be a 2D numeric sequence")

    rows: list[list[float]] = []
    for row_value in cast(Sequence[object], value):
        if not isinstance(row_value, Sequence) or isinstance(row_value, (str, bytes)):
            raise ValueError("heightmap must be a 2D numeric sequence")
        rows.append([float(cast(Any, cell)) for cell in cast(Sequence[object], row_value)])
    return rows


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
_FALLOFF_FUNCTIONS: dict[str, Callable[[float], float]] = {
    "smooth": _falloff_smooth,
    "linear": _falloff_linear,
    "sphere": _falloff_sphere,
    "root": _falloff_root,
    "sharp": _falloff_sharp,
    "gaussian": _falloff_gaussian,
    "constant": _falloff_constant,
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

    Vectorized construction: the six named curves that have closed-form
    numpy-native expressions are evaluated in a single vectorized pass.
    Only the lambda-backed dispatch runs via a list comprehension (used once
    at LUT build time, not per vertex).

    Args:
        falloff: Curve name recognised by ``_FALLOFF_FUNCTIONS``.
        lut_size: Number of evenly spaced samples across [0, 1).

    Returns:
        float64 array of shape (lut_size + 1,).
    """
    if falloff not in _FALLOFF_FUNCTIONS:
        raise ValueError(
            f"Unknown falloff: {falloff!r}. Valid: {sorted(_FALLOFF_FUNCTIONS)}"
        )
    d = np.linspace(0.0, 1.0, lut_size, endpoint=False)  # (lut_size,) in [0, 1)

    # Vectorized evaluation of each named curve — avoids per-element Python calls.
    if falloff == "smooth":
        lut = 2.0 * d * d * d - 3.0 * d * d + 1.0           # Hermite smoothstep
    elif falloff == "linear":
        lut = 1.0 - d
    elif falloff == "sphere":
        lut = np.sqrt(np.maximum(0.0, 1.0 - d * d))
    elif falloff == "root":
        lut = np.sqrt(np.maximum(0.0, 1.0 - d))
    elif falloff == "sharp":
        lut = np.maximum(0.0, 1.0 - d * d)
    elif falloff == "gaussian":
        lut = np.exp(-4.0 * d * d)
    else:  # "constant"
        lut = np.ones(lut_size, dtype=np.float64)

    lut = np.clip(lut, 0.0, 1.0)
    # Sentinel: value at exactly d=1 is 0
    lut = np.append(lut, 0.0)
    return lut.astype(np.float64)


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
    vert_positions_2d: Sequence[Sequence[float]] | np.ndarray,
    brush_center: Sequence[float],
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
    target_surface_z: float | None = None,
    slope_mask: np.ndarray | None = None,
    curvature_mask: np.ndarray | None = None,
    protected_zone_mask: np.ndarray | None = None,
    slope_threshold: float = 1.0,
    curvature_threshold: float = 1.0,
) -> dict[int, float]:
    """Compute Z displacements for 'raise' operation — vectorized numpy.

    Uses a **signed-distance-field displacement** when ``target_surface_z`` is
    provided: the displacement magnitude at each vertex is proportional to the
    signed distance  ``target_surface_z - current_z`` rather than a raw
    strength scalar.  This drives vertices smoothly toward a target elevation
    plane (the same model used by ZBrush Inflate-by-SDF and UE Landscape
    Flatten-raise hybrid).  Without ``target_surface_z`` the classic
    ``weight * strength * brush_size`` formula applies.

    **Slope/curvature masking** — when ``slope_mask`` or ``curvature_mask``
    arrays are supplied the displacement at vertex ``i`` is additionally
    multiplied by ``slope_mask[i]`` (expected in [0, 1]) and
    ``curvature_mask[i]`` (expected in [0, 1]).  Values above their respective
    thresholds clamp the mask contribution to zero, suppressing raise on very
    steep or highly curved regions (matching Houdini heightfield-paint masking).

    **Protected zones** — ``protected_zone_mask[i] == True`` sets the final
    displacement to zero regardless of other parameters (e.g. roads, rivers,
    spawn-point exclusions stored in the terrain protocol).

    All hot-path math is **vectorized numpy** — no Python loops over vertices.

    Args:
        vert_heights: Current Z values for all vertices (N-length).
        weights: (index, weight) tuples from compute_brush_weights.
        strength: Displacement multiplier (or SDF scale when target provided).
        brush_size: Brush radius; multiplies displacement in non-SDF mode.
        max_height: Ceiling; displaced values are clamped below this.
        use_normal: When True, project displacement along vertex normal's Z
            component rather than world-Z (only affects non-SDF path).
        vert_normals: Per-vertex surface normals ``(nx, ny, nz)``.  Required
            when ``use_normal`` is True.
        target_surface_z: Optional target elevation.  When supplied, SDF
            displacement = weight * strength * (target_surface_z - current_z),
            giving a smooth drive toward the surface with Hermite falloff.
        slope_mask: Per-vertex float array in [0, 1]; high values suppress
            raise on steep faces.  Compared to slope_threshold.
        curvature_mask: Per-vertex float array in [0, 1]; high values suppress
            raise on convex/concave peaks.  Compared to curvature_threshold.
        protected_zone_mask: Boolean per-vertex array; True = locked, no change.
        slope_threshold: Mask values above this fraction suppress displacement.
        curvature_threshold: Mask values above this fraction suppress displacement.

    Returns:
        Dict mapping vertex index -> new Z value.  Only affected vertices
        with non-zero displacement are included.
    """
    if not weights:
        return {}

    # ------------------------------------------------------------------
    # Vectorize: unpack weight list into parallel numpy arrays.
    # ------------------------------------------------------------------
    indices_np = np.array([i for i, _ in weights], dtype=np.int64)
    ws_np = np.array([w for _, w in weights], dtype=np.float64)

    heights_np = np.asarray(vert_heights, dtype=np.float64)
    current_z = heights_np[indices_np]

    s = float(strength)
    bs = float(brush_size)

    # ------------------------------------------------------------------
    # SDF vs raw displacement.
    # ------------------------------------------------------------------
    if target_surface_z is not None:
        # Signed distance from current Z to target plane.
        sdf = float(target_surface_z) - current_z
        # Hermite cubic: smoothly damp large distances so the brush doesn't
        # hyperextend.  sdf_norm = sdf / (sdf_max + ε); apply 3t²-2t³.
        sdf_max = np.max(np.abs(sdf)) + 1e-8
        t = np.clip(np.abs(sdf) / sdf_max, 0.0, 1.0)
        hermite = 3.0 * t * t - 2.0 * t * t * t   # smooth toward 1.0
        delta = ws_np * s * np.sign(sdf) * hermite * sdf_max
    else:
        base_delta = ws_np * s * bs
        if use_normal and vert_normals is not None:
            normals_np = np.asarray(vert_normals, dtype=np.float64)  # (N, 3)
            nz_col = normals_np[indices_np, 2]                        # (K,)
            norms = np.linalg.norm(normals_np[indices_np], axis=1)    # (K,)
            safe = norms > 1e-8
            nz_unit = np.where(safe, nz_col / np.where(safe, norms, 1.0), 1.0)
            delta = base_delta * nz_unit
        else:
            delta = base_delta

    # ------------------------------------------------------------------
    # Slope / curvature masking — multiply delta by per-vertex mask value.
    # ------------------------------------------------------------------
    if slope_mask is not None:
        sm = np.asarray(slope_mask, dtype=np.float64)[indices_np]
        slope_factor = np.where(sm > float(slope_threshold), 0.0, 1.0 - sm / max(float(slope_threshold), 1e-8))
        delta = delta * slope_factor

    if curvature_mask is not None:
        cm = np.asarray(curvature_mask, dtype=np.float64)[indices_np]
        curv_factor = np.where(cm > float(curvature_threshold), 0.0, 1.0 - cm / max(float(curvature_threshold), 1e-8))
        delta = delta * curv_factor

    # ------------------------------------------------------------------
    # Compute new Z and clamp to max_height ceiling.
    # ------------------------------------------------------------------
    new_z = current_z + delta
    if max_height < float("inf"):
        new_z = np.minimum(new_z, float(max_height))

    # ------------------------------------------------------------------
    # Protected zone masking: zero displacement for locked vertices.
    # ------------------------------------------------------------------
    if protected_zone_mask is not None:
        pz = np.asarray(protected_zone_mask, dtype=bool)[indices_np]
        new_z = np.where(pz, current_z, new_z)

    # Return only vertices where new_z actually changed.
    changed = np.abs(new_z - current_z) > 1e-12
    return {int(indices_np[k]): float(new_z[k]) for k in np.where(changed)[0]}


def compute_lower_displacements(
    vert_heights: list[float],
    weights: list[tuple[int, float]],
    strength: float,
    brush_size: float = 1.0,
    min_height: float = float("-inf"),
    floor_clamp: float | None = None,
    target_surface_z: float | None = None,
    slope_mask: np.ndarray | None = None,
    curvature_mask: np.ndarray | None = None,
    protected_zone_mask: np.ndarray | None = None,
    slope_threshold: float = 1.0,
    curvature_threshold: float = 1.0,
) -> dict[int, float]:
    """Compute Z displacements for 'lower' (dig) operation — vectorized numpy.

    Mirrors ``compute_raise_displacements`` but drives vertices downward.

    Two floor parameters are available and the *strictest* (highest) value
    always wins:

    * ``min_height`` — legacy per-call floor (e.g. terrain height_min from
      the sculpt handler).
    * ``floor_clamp`` — explicit hard floor preventing vertices from being
      pushed below a world reference level (e.g. 0.0 for sea level).

    **SDF mode** — when ``target_surface_z`` is provided the displacement
    is the signed distance ``current_z - target_surface_z`` with Hermite
    damping, mirroring the raise SDF but driving downward.  Without it the
    classic ``weight * strength * brush_size`` subtraction applies.

    **Slope/curvature masking** and **protected zone clipping** behave
    identically to ``compute_raise_displacements``.

    All hot-path math is **vectorized numpy** — no Python loops over vertices.

    Args:
        vert_heights: Current Z values for all vertices.
        weights: (index, weight) tuples from compute_brush_weights.
        strength: Displacement magnitude (positive = lower).
        brush_size: Brush radius, scales displacement magnitude.
        min_height: Soft floor; displaced values are clamped above this.
        floor_clamp: Hard world-space floor.
        target_surface_z: Optional target elevation for SDF-mode lowering.
        slope_mask: Per-vertex float [0, 1]; high values suppress lowering.
        curvature_mask: Per-vertex float [0, 1]; high values suppress lowering.
        protected_zone_mask: Boolean per-vertex array; True = locked.
        slope_threshold: Mask values above this suppress displacement.
        curvature_threshold: Mask values above this suppress displacement.

    Returns:
        Dict mapping vertex index -> new Z value.
    """
    if not weights:
        return {}

    # Resolve the effective floor: strictest of min_height and floor_clamp.
    effective_floor: float = float("-inf")
    if min_height > float("-inf"):
        effective_floor = float(min_height)
    if floor_clamp is not None:
        effective_floor = max(effective_floor, float(floor_clamp))

    # ------------------------------------------------------------------
    # Vectorize: unpack weight list into parallel numpy arrays.
    # ------------------------------------------------------------------
    indices_np = np.array([i for i, _ in weights], dtype=np.int64)
    ws_np = np.array([w for _, w in weights], dtype=np.float64)

    heights_np = np.asarray(vert_heights, dtype=np.float64)
    current_z = heights_np[indices_np]

    s = float(strength)
    bs = float(brush_size)

    # ------------------------------------------------------------------
    # SDF vs raw displacement.
    # ------------------------------------------------------------------
    if target_surface_z is not None:
        # Signed distance from current Z down to target plane.
        sdf = current_z - float(target_surface_z)
        sdf_max = np.max(np.abs(sdf)) + 1e-8
        t = np.clip(np.abs(sdf) / sdf_max, 0.0, 1.0)
        hermite = 3.0 * t * t - 2.0 * t * t * t
        delta = ws_np * s * np.sign(sdf) * hermite * sdf_max
    else:
        delta = ws_np * s * bs

    # ------------------------------------------------------------------
    # Slope / curvature masking.
    # ------------------------------------------------------------------
    if slope_mask is not None:
        sm = np.asarray(slope_mask, dtype=np.float64)[indices_np]
        slope_factor = np.where(sm > float(slope_threshold), 0.0, 1.0 - sm / max(float(slope_threshold), 1e-8))
        delta = delta * slope_factor

    if curvature_mask is not None:
        cm = np.asarray(curvature_mask, dtype=np.float64)[indices_np]
        curv_factor = np.where(cm > float(curvature_threshold), 0.0, 1.0 - cm / max(float(curvature_threshold), 1e-8))
        delta = delta * curv_factor

    # ------------------------------------------------------------------
    # Compute new Z: subtract delta, clamp to floor.
    # ------------------------------------------------------------------
    new_z = current_z - delta
    if effective_floor > float("-inf"):
        new_z = np.maximum(new_z, effective_floor)

    # ------------------------------------------------------------------
    # Protected zone masking.
    # ------------------------------------------------------------------
    if protected_zone_mask is not None:
        pz = np.asarray(protected_zone_mask, dtype=bool)[indices_np]
        new_z = np.where(pz, current_z, new_z)

    changed = np.abs(new_z - current_z) > 1e-12
    return {int(indices_np[k]): float(new_z[k]) for k in np.where(changed)[0]}


def compute_smooth_displacements(
    vert_positions: Sequence[Sequence[float]],
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
    if _scipy_available and hmap_grid is not None:
        grid = np.asarray(hmap_grid, dtype=np.float64)
        # σ in grid cells: default radius/3 expressed as grid cells, or 1.0
        sigma_cells = (float(brush_radius) / 3.0) if brush_radius else 1.0
        sigma_cells = max(sigma_cells, 0.3)
        if _scipy_ndimage is None:
            raise RuntimeError("scipy ndimage unavailable despite availability check")
        scipy_ndimage = cast(Any, _scipy_ndimage)
        gaussian_filter = cast(Callable[..., np.ndarray], scipy_ndimage.gaussian_filter)
        smoothed = gaussian_filter(
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
    protected_zone_mask: np.ndarray | None = None,
    slope_mask: np.ndarray | None = None,
    slope_threshold: float = 1.0,
) -> dict[int, float]:
    """Compute Z displacements for 'flatten' operation — vectorized numpy.

    Each affected vertex moves toward a *best-fit plane* rather than a single
    average height, which eliminates the low-frequency waviness that the old
    unweighted-mean approach introduced on sloped or curved terrain.

    **Plane fit algorithm** (weighted least-squares via SVD):
    1. Compute the brush-weight-centroid of the affected vertex positions.
    2. Centre the positions around that centroid.
    3. Form the weighted scatter matrix ``A = V^T W V`` and decompose with SVD.
    4. The right singular vector for the smallest singular value is the
       best-fit plane normal.
    5. Each vertex's target Z is its projection back onto the fitted plane
       through the centroid.

    The plane fit requires 3-D positions (``vert_positions``).  When they are
    not supplied the function falls back to the brush-weighted average height
    (scalar target), preserving backward compatibility.

    **Protected zone clipping** — ``protected_zone_mask[i] == True`` prevents
    any change to vertex ``i``, regardless of other parameters.

    **Slope masking** — ``slope_mask[i]`` in [0, 1] attenuates flatten on
    steep faces, matching Houdini heightfield-paint masking.

    All hot-path math is **vectorized numpy** — no Python loops over vertices.

    Args:
        vert_heights: Current Z values for all vertices.
        weights: (index, weight) tuples from compute_brush_weights.
        target_height: Explicit target Z.  When provided, skips plane fit and
            uses this constant as the target (useful for "flatten to cursor").
        flatten_strength: Blend factor in [0..1].
        vert_positions: Full (x, y, z) positions for all vertices.  When
            supplied (and ``target_height`` is None) a weighted SVD plane fit
            is used instead of the scalar weighted-mean fallback.
        protected_zone_mask: Boolean per-vertex array; True = locked.
        slope_mask: Per-vertex float [0, 1]; high values suppress flatten.
        slope_threshold: Mask values above this suppress displacement.

    Returns:
        Dict mapping vertex index -> new Z value.
    """
    if not weights:
        return {}

    strength = float(flatten_strength)
    indices = np.array([i for i, _ in weights], dtype=np.int64)
    ws = np.array([w for _, w in weights], dtype=np.float64)  # (K,)

    heights_np = np.asarray(vert_heights, dtype=np.float64)
    current_z = heights_np[indices]  # (K,)

    # ------------------------------------------------------------------
    # Determine target Z for each affected vertex.
    # ------------------------------------------------------------------
    if target_height is not None:
        # Explicit scalar target — constant-plane flatten, fully vectorized.
        plane_z = np.full_like(current_z, float(target_height))
    elif vert_positions is not None:
        # ------------------------------------------------------------------
        # Weighted least-squares plane fit (SVD), fully vectorized.
        # ------------------------------------------------------------------
        verts = np.array(
            [vert_positions[i] for i in indices.tolist()], dtype=np.float64
        )  # (K, 3)

        total_w = ws.sum()
        if total_w <= 0.0:
            total_w = 1.0
        centroid = np.average(verts, weights=ws, axis=0)  # (3,)
        verts_c = verts - centroid                          # (K, 3) centred

        # Weighted scatter matrix A = V^T diag(w/sum) V → (3, 3)
        w_norm = ws / total_w
        # Efficient: A = (verts_c * w_norm[:, None]).T @ verts_c
        scatter = (verts_c * w_norm[:, None]).T @ verts_c

        _, _, Vt = np.linalg.svd(scatter)
        normal = Vt[-1]  # (3,) smallest singular vector = plane normal

        nz = normal[2]
        if abs(nz) < 1e-6:
            normal = np.array([0.0, 0.0, 1.0])
            nz = 1.0

        # Vectorized plane projection:
        # plane_z = centroid_z - (nx*(px-cx) + ny*(py-cy)) / nz
        px = verts[:, 0]
        py = verts[:, 1]
        plane_z = float(centroid[2]) - (
            normal[0] * (px - float(centroid[0]))
            + normal[1] * (py - float(centroid[1]))
        ) / nz
    else:
        # Fallback: brush-weighted average height.
        total_w = ws.sum()
        avg_h = float(np.dot(ws, current_z) / total_w) if total_w > 0.0 else float(np.mean(current_z))
        plane_z = np.full_like(current_z, avg_h)

    # ------------------------------------------------------------------
    # Blend: new_z = current_z + w * strength * (plane_z - current_z)
    # ------------------------------------------------------------------
    blend = ws * strength
    new_z = current_z + blend * (plane_z - current_z)

    # ------------------------------------------------------------------
    # Slope masking.
    # ------------------------------------------------------------------
    if slope_mask is not None:
        sm = np.asarray(slope_mask, dtype=np.float64)[indices]
        slope_factor = np.where(sm > float(slope_threshold), 0.0, 1.0 - sm / max(float(slope_threshold), 1e-8))
        new_z = current_z + (new_z - current_z) * slope_factor

    # ------------------------------------------------------------------
    # Protected zone masking.
    # ------------------------------------------------------------------
    if protected_zone_mask is not None:
        pz = np.asarray(protected_zone_mask, dtype=bool)[indices]
        new_z = np.where(pz, current_z, new_z)

    # Return all affected vertices — flatten callers expect every brush vertex
    # in the result (including those already at the target plane) so the
    # bmesh write-back loop can apply consistent height assignment.
    return {int(indices[k]): float(new_z[k]) for k in range(len(indices))}


def compute_stamp_displacements(
    vert_positions_2d: Sequence[Sequence[float]],
    vert_heights: list[float],
    weights: list[tuple[int, float]],
    brush_center: Sequence[float],
    brush_radius: float,
    heightmap: list[list[float]],
    stamp_strength: float = 1.0,
    blend_mode: str = "add",
    feather: float = 0.0,
) -> dict[int, float]:
    """Compute Z displacements for 'stamp' operation — fully vectorized numpy.

    Samples the stamp heightmap with **bilinear interpolation** across all
    affected vertices simultaneously, then composites the sampled values using
    one of four blend modes.  The entire function operates on numpy arrays with
    zero Python loops over vertices, matching the vectorized stamp kernels in
    Houdini heightfield-stamp, ZBrush Alpha stamp, and UE Landscape stamp brush.

    **Bilinear sampling** — UV coordinates for all affected vertices are
    computed in one broadcast operation.  Floor indices and fractional parts are
    extracted with ``np.floor``; the four surrounding texels are gathered with
    advanced integer indexing and blended via the standard bilinear formula
    ``(1-tx)(1-ty)*h00 + tx(1-ty)*h10 + (1-tx)ty*h01 + tx·ty*h11``.

    **Feathering** — when ``feather > 0`` a smoothstep ramp is applied over the
    outermost fraction of the brush radius in a single vectorized ``np.where``
    call.  No conditional branch per vertex.

    **Blend modes:**

    +----------+----------------------------------------------------------+
    | Mode     | Formula (vectorized)                                     |
    +----------+----------------------------------------------------------+
    | add      | new_z = current_z + w * strength * h_val  (default)      |
    | replace  | new_z = lerp(current_z, h_val * strength, w)             |
    | max      | new_z = np.maximum(current_z, current_z + delta)         |
    | min      | new_z = np.minimum(current_z, current_z + delta)         |
    +----------+----------------------------------------------------------+

    Args:
        vert_positions_2d: (x, y) for each vertex.
        vert_heights: Current Z values for all vertices.
        weights: (index, weight) tuples from compute_brush_weights.
        brush_center: Center of the stamp in world XY.
        brush_radius: Radius of the stamp area in world units.
        heightmap: 2D grid of height values [row][col], normalised [0..1].
        stamp_strength: Scale factor applied to all sampled heightmap values.
        blend_mode: Compositing mode — "add", "replace", "max", or "min".
        feather: Feather width as a fraction of brush radius in [0, 1).
            0 = no feathering; 0.2 = fade over outer 20 % of the radius.

    Returns:
        Dict mapping vertex index -> new Z value.  Only vertices with a
        non-zero displacement are included.
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

    # ------------------------------------------------------------------
    # Unpack weight list into parallel numpy arrays — zero Python loops.
    # ------------------------------------------------------------------
    indices_np = np.array([i for i, _ in weights], dtype=np.int64)   # (K,)
    ws_np = np.array([w for _, w in weights], dtype=np.float64)       # (K,)

    # Gather vertex XY positions and current heights for affected set.
    pts = np.asarray(vert_positions_2d, dtype=np.float64)             # (N, 2)
    vx = pts[indices_np, 0]                                            # (K,)
    vy = pts[indices_np, 1]                                            # (K,)
    heights_np = np.asarray(vert_heights, dtype=np.float64)
    current_z = heights_np[indices_np]                                 # (K,)

    bx = float(brush_center[0])
    by = float(brush_center[1])
    br = float(brush_radius)
    s = float(stamp_strength)
    feather_f = float(np.clip(feather, 0.0, 0.999))

    # ------------------------------------------------------------------
    # Feathering: vectorized smoothstep over outer feather band.
    # fade(d) = 1 - smoothstep(t)  where t = (d - inner) / feather
    # Applied as a weight multiplier; inner band stays at 1.0.
    # ------------------------------------------------------------------
    if feather_f > 0.0:
        inner_edge = 1.0 - feather_f
        norm_d = np.sqrt((vx - bx) ** 2 + (vy - by) ** 2) / br
        norm_d = np.clip(norm_d, 0.0, 1.0)
        in_feather = norm_d > inner_edge
        t_feather = np.where(
            in_feather,
            np.clip((norm_d - inner_edge) / feather_f, 0.0, 1.0),
            0.0,
        )
        fade = 1.0 - (3.0 * t_feather * t_feather - 2.0 * t_feather * t_feather * t_feather)
        ws_np = ws_np * fade

    # ------------------------------------------------------------------
    # Bilinear heightmap sampling — fully vectorized.
    #
    # UV in [0, 1]: map vertex XY offset from brush center into stamp space.
    # fx, fy: floating-point texel coordinates in [0, cols-1] / [0, rows-1].
    # Gather h00, h10, h01, h11 via fancy indexing; blend with tx/ty.
    # ------------------------------------------------------------------
    inv_diam = 1.0 / (2.0 * br)
    u = np.clip(((vx - bx) + br) * inv_diam, 0.0, 1.0)               # (K,)
    v = np.clip(((vy - by) + br) * inv_diam, 0.0, 1.0)               # (K,)

    hm = np.asarray(heightmap, dtype=np.float64)                      # (rows, cols)

    fx = u * (cols - 1)                                                # (K,) float col
    fy = v * (rows - 1)                                                # (K,) float row
    x0 = np.clip(np.floor(fx).astype(np.int64), 0, cols - 2)         # (K,) int
    y0 = np.clip(np.floor(fy).astype(np.int64), 0, rows - 2)         # (K,) int
    x1 = x0 + 1                                                        # (K,) always valid
    y1 = y0 + 1                                                        # (K,) always valid
    tx = fx - x0.astype(np.float64)                                   # (K,) fraction
    ty = fy - y0.astype(np.float64)                                   # (K,) fraction

    # Gather four surrounding texels via advanced indexing.
    h00 = hm[y0, x0]
    h10 = hm[y0, x1]
    h01 = hm[y1, x0]
    h11 = hm[y1, x1]

    h_val = (
        h00 * (1.0 - tx) * (1.0 - ty)
        + h10 * tx * (1.0 - ty)
        + h01 * (1.0 - tx) * ty
        + h11 * tx * ty
    )  # (K,) bilinearly interpolated heightmap values

    # ------------------------------------------------------------------
    # Blend mode application — all vectorized.
    # ------------------------------------------------------------------
    delta = ws_np * s * h_val

    if blend_mode == "add":
        new_z = current_z + delta
    elif blend_mode == "replace":
        # Lerp: current_z + w * (target - current_z), target = h_val * strength
        new_z = current_z + ws_np * (s * h_val - current_z)
    elif blend_mode == "max":
        new_z = np.maximum(current_z, current_z + delta)
    else:  # "min"
        new_z = np.minimum(current_z, current_z + delta)

    # Return only vertices where the height actually changed.
    changed = np.abs(new_z - current_z) > 1e-12
    return {int(indices_np[k]): float(new_z[k]) for k in np.where(changed)[0]}


# ---------------------------------------------------------------------------
# Blender handler (requires bpy + bmesh at runtime)
# ---------------------------------------------------------------------------


def _build_adjacency(bm_obj: _BMeshLike) -> dict[int, list[int]]:
    """Build 8-connected vertex adjacency map from a bmesh object.

    **8-connectivity (Moore neighbourhood)** — the returned adjacency includes
    both edge-sharing neighbours (4-connected, via ``link_edges``) *and*
    face-diagonal neighbours discovered by walking each linked face's vertex
    loop.  This matches the Moore-8 kernel used by ZBrush, Houdini heightfield
    smooth, and UE Landscape brush weight propagation:

    * 4-connected (edge only): vertex shares a mesh edge with neighbour.
    * 8-connected (face diagonal): vertex shares a *face* but not necessarily
      an edge with neighbour (diagonal of a quad or distant tri vertex).

    For a regular quad-grid terrain mesh (the dominant case) this adds the four
    diagonal neighbours for every interior vertex, giving the full 8-connected
    stencil.  For irregular meshes it includes all co-face vertices, which is
    strictly more connected than 4-connectivity and matches the "all vertices in
    the 1-ring face set" definition used by ZBrush's topology-smooth kernel.

    The result is deduplicated and sorted for determinism; the vertex itself is
    never included in its own neighbour list.

    Args:
        bm_obj: An active bmesh (``bmesh.BMesh``) with ``ensure_lookup_table``
            already called.

    Returns:
        Dict mapping vertex index (int) → sorted list of neighbour indices.
    """
    adj: dict[int, list[int]] = {}
    for v in bm_obj.verts:
        vi = v.index
        neighbours: set[int] = set()
        # 4-connected: direct edge neighbours.
        for e in v.link_edges:
            neighbours.add(e.other_vert(v).index)
        # 8-connected: all co-face vertices (includes diagonals on quads).
        for f in v.link_faces:
            for fv in f.verts:
                if fv.index != vi:
                    neighbours.add(fv.index)
        adj[vi] = sorted(neighbours)
    return adj


def handle_sculpt_terrain(params: dict[str, object]) -> dict[str, object]:
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
    _require_bpy()
    if bpy is None or bmesh is None:
        raise RuntimeError("Blender modules unavailable after runtime guard")

    bpy_module = cast(Any, bpy)
    bmesh_module = cast(Any, bmesh)

    terrain_name = params.get("terrain_name")
    obj = bpy_module.data.objects.get(terrain_name)
    if not obj or obj.type != "MESH":
        raise ValueError(f"Terrain mesh object not found: {terrain_name}")

    world_pos_x, world_pos_y, world_pos_z = _position_xyz(params.get("position"))
    radius = _param_float(params, "radius", 5.0)
    strength = _param_float(params, "strength", 1.0)
    # Accept both "brush_mode" (new) and "operation" (legacy key).
    operation = _brush_operation(params)
    falloff = _param_str(params, "falloff", "smooth")
    heightmap = _heightmap_from_param(params.get("heightmap"))
    height_min = _param_float(params, "height_min", float("-inf"))
    height_max = _param_float(params, "height_max", float("inf"))
    blend_mode = _param_str(params, "blend_mode", "add")
    feather = _param_float(params, "feather", 0.0)

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
    mw = obj.matrix_world          # 4×4 Matrix
    mw_inv = mw.inverted()

    mathutils = cast(Any, importlib.import_module("mathutils"))
    world_pt = mathutils.Vector((world_pos_x, world_pos_y, world_pos_z))
    local_pt = mw_inv @ world_pt

    # Approximate local-space radius: divide by the average absolute scale.
    scale_x = abs(mw[0][0])
    scale_y = abs(mw[1][1])
    # Use the XY mean for the horizontal radius conversion.
    avg_scale_xy = (scale_x + scale_y) / 2.0 if (scale_x + scale_y) > 0 else 1.0
    local_radius = radius / avg_scale_xy if avg_scale_xy > 1e-8 else radius

    brush_center = (float(local_pt.x), float(local_pt.y))

    bm = bmesh_module.new()
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

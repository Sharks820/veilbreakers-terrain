"""Advanced terrain features for VeilBreakers dark fantasy environments.

Provides spline-based terrain deformation, non-destructive terrain layers,
brush-based erosion painting, D8 flow map computation, enhanced thermal
erosion, terrain stamp/feature placement, and object-to-terrain snapping.

Pure-logic functions (no bpy dependency) are separated for testability.
Handler functions that mutate Blender scenes import bpy only at call time.

Gap coverage: #44 (spline deform), #45 (terrain layers), #46 (erosion paint),
#75 (flow map), #48 (thermal erosion), #28/GAP-10 (terrain stamp),
#30/GAP-12 (snap to terrain).
"""

from __future__ import annotations

import base64
import json
import logging
import math
import random as _random
import warnings
from typing import Any

_log = logging.getLogger(__name__)

# Current serialization schema version for TerrainLayer.to_dict / from_dict.
# v2 → v3: heights array serialized as base64-encoded little-endian float64
#           with an explicit "dtype" field for round-trip fidelity.
_TERRAIN_LAYER_SCHEMA_VERSION = 3

import numpy as np

def _detect_grid_dims(bm) -> tuple[int, int]:
    """Detect actual (rows, cols) of a terrain grid mesh.

    Shared with environment.py — duplicated here to avoid circular import.
    """
    import math as _math
    xs = set(round(v.co.x, 3) for v in bm.verts)
    ys = set(round(v.co.y, 3) for v in bm.verts)
    cols, rows = len(xs), len(ys)
    if cols * rows == len(bm.verts):
        return rows, cols
    side = max(2, int(_math.sqrt(len(bm.verts))))
    return side, side


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------
Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]


# ---------------------------------------------------------------------------
# Cubic Bezier spline utilities (pure logic)
# ---------------------------------------------------------------------------

def _cubic_bezier_point(
    p0: Vec3, p1: Vec3, p2: Vec3, p3: Vec3, t: float,
) -> Vec3:
    """Evaluate a cubic Bezier curve at parameter t in [0, 1].

    Args:
        p0, p1, p2, p3: Control points (start, ctrl1, ctrl2, end).
        t: Parameter along curve, 0.0 = p0, 1.0 = p3.

    Returns:
        Interpolated (x, y, z) position on the curve.
    """
    u = 1.0 - t
    uu = u * u
    uuu = uu * u
    tt = t * t
    ttt = tt * t

    x = uuu * p0[0] + 3.0 * uu * t * p1[0] + 3.0 * u * tt * p2[0] + ttt * p3[0]
    y = uuu * p0[1] + 3.0 * uu * t * p1[1] + 3.0 * u * tt * p2[1] + ttt * p3[1]
    z = uuu * p0[2] + 3.0 * uu * t * p1[2] + 3.0 * u * tt * p2[2] + ttt * p3[2]
    return (x, y, z)


def _auto_control_points(
    points: list[Vec3],
    tension: float = 0.5,
) -> list[tuple[Vec3, Vec3, Vec3, Vec3]]:
    """Generate cubic Bezier segments from a list of waypoints.

    Uses Catmull-Rom-style tangent estimation to compute control points
    that produce a smooth curve through the waypoints.

    Args:
        points: Ordered waypoints (at least 2).
        tension: Controls tightness of the curve (0=loose, 1=tight).

    Returns:
        List of (p0, ctrl1, ctrl2, p1) tuples for each Bezier segment.
    """
    if len(points) < 2:
        return []

    segments: list[tuple[Vec3, Vec3, Vec3, Vec3]] = []
    n = len(points)

    for i in range(n - 1):
        p0 = points[i]
        p3 = points[i + 1]

        # Compute tangent at p0
        if i > 0:
            tan0 = tuple(
                (1.0 - tension) * (points[i + 1][k] - points[i - 1][k]) / 2.0
                for k in range(3)
            )
        else:
            tan0 = tuple(
                (1.0 - tension) * (points[i + 1][k] - points[i][k])
                for k in range(3)
            )

        # Compute tangent at p3
        if i + 2 < n:
            tan1 = tuple(
                (1.0 - tension) * (points[i + 2][k] - points[i][k]) / 2.0
                for k in range(3)
            )
        else:
            tan1 = tuple(
                (1.0 - tension) * (points[i + 1][k] - points[i][k])
                for k in range(3)
            )

        ctrl1 = tuple(p0[k] + tan0[k] / 3.0 for k in range(3))
        ctrl2 = tuple(p3[k] - tan1[k] / 3.0 for k in range(3))

        segments.append((p0, ctrl1, ctrl2, p3))  # type: ignore[arg-type]

    return segments


def evaluate_spline(
    spline_points: list[Vec3],
    samples_per_segment: int = 32,
    tension: float = 0.5,
    arc_length_reparameterize: bool = True,
) -> list[Vec3]:
    """Evaluate a smooth spline through the given control points.

    Arc-length reparameterization (enabled by default) ensures the returned
    points are spaced uniformly in arc-length space.  Without it, parameter
    density clumps on tight curves and spreads on straights — which causes
    variable-width corridors in road/river tools that assume even sampling.

    Algorithm:
      1. Oversample the raw Bezier curve at HIGH_OVERSAMPLE * samples_per_segment
         per segment to capture all curvature detail.
      2. Compute cumulative arc-length along the oversampled polyline.
      3. Resample the oversampled polyline at uniformly-spaced arc-length
         positions via linear interpolation so every returned point is the
         same distance from its neighbours in world space.

    Args:
        spline_points: Ordered waypoints (at least 2).
        samples_per_segment: Number of evaluation points per Bezier segment
            in the final output.  This is the arc-length-uniform count, not
            the raw parameter-uniform count.
        tension: Curve tightness (0=loose, 1=tight).
        arc_length_reparameterize: When True (default) apply the arc-length
            correction pass.  Pass False to reproduce the legacy uniform-t
            behaviour exactly.

    Returns:
        List of (x, y, z) positions along the spline, uniformly spaced in
        arc-length when arc_length_reparameterize=True.
    """
    if len(spline_points) < 2:
        return list(spline_points)

    segments = _auto_control_points(spline_points, tension)

    # --- Step 1: dense oversample in raw t-space ---
    _HIGH_OVERSAMPLE = 8   # 8× the requested density for curvature accuracy
    raw_pts: list[Vec3] = []
    for seg_idx, (p0, p1, p2, p3) in enumerate(segments):
        n_samp = samples_per_segment * _HIGH_OVERSAMPLE
        n_samp_use = n_samp if seg_idx < len(segments) - 1 else n_samp + 1
        for i in range(n_samp_use):
            t = i / n_samp
            raw_pts.append(_cubic_bezier_point(p0, p1, p2, p3, t))

    if not arc_length_reparameterize or len(raw_pts) < 2:
        # Legacy uniform-t path: just return the raw oversampled then
        # thin-back to the requested count, or return raw if no thinning needed.
        if not arc_length_reparameterize:
            # Reproduce the old per-segment uniform sampling exactly.
            result: list[Vec3] = []
            for seg_idx, (p0, p1, p2, p3) in enumerate(segments):
                n_samples = samples_per_segment if seg_idx < len(segments) - 1 else samples_per_segment + 1
                for i in range(n_samples):
                    t = i / samples_per_segment
                    result.append(_cubic_bezier_point(p0, p1, p2, p3, t))
            return result
        return raw_pts

    # --- Step 2: compute cumulative arc-lengths along the dense polyline ---
    n_raw = len(raw_pts)
    arc_len = [0.0] * n_raw
    for i in range(1, n_raw):
        dx = raw_pts[i][0] - raw_pts[i - 1][0]
        dy = raw_pts[i][1] - raw_pts[i - 1][1]
        dz = raw_pts[i][2] - raw_pts[i - 1][2]
        arc_len[i] = arc_len[i - 1] + math.sqrt(dx * dx + dy * dy + dz * dz)
    total_len = arc_len[-1]

    if total_len < 1e-12:
        # Degenerate (all points coincident): return raw points as-is.
        return raw_pts

    # --- Step 3: resample uniformly in arc-length space ---
    total_out = len(segments) * samples_per_segment + 1
    result_al: list[Vec3] = []
    raw_i = 0  # search cursor into arc_len (monotone → single scan suffices)
    for k in range(total_out):
        target = total_len * k / max(total_out - 1, 1)
        # Advance raw_i until arc_len[raw_i+1] >= target (linear scan, O(N) total)
        while raw_i + 1 < n_raw - 1 and arc_len[raw_i + 1] < target:
            raw_i += 1
        seg_start = arc_len[raw_i]
        seg_end = arc_len[min(raw_i + 1, n_raw - 1)]
        seg_span = seg_end - seg_start
        if seg_span < 1e-12:
            frac = 0.0
        else:
            frac = (target - seg_start) / seg_span
        # Linear interpolation between raw_pts[raw_i] and raw_pts[raw_i+1].
        a = raw_pts[raw_i]
        b = raw_pts[min(raw_i + 1, n_raw - 1)]
        result_al.append((
            a[0] + frac * (b[0] - a[0]),
            a[1] + frac * (b[1] - a[1]),
            a[2] + frac * (b[2] - a[2]),
        ))
    return result_al


def distance_point_to_polyline(
    px: float, py: float,
    polyline: list[Vec3],
) -> tuple[float, Vec3, float]:
    """Compute minimum 2D (XY) distance from point to polyline.

    Args:
        px, py: Query point in world XY.
        polyline: List of (x, y, z) points forming the polyline.

    Returns:
        (distance, closest_point, t_along_spline) where t_along_spline
        is normalized [0, 1] along the total polyline length.
    """
    if not polyline:
        return float("inf"), (px, py, 0.0), 0.0

    if len(polyline) == 1:
        sp = polyline[0]
        dx = px - sp[0]
        dy = py - sp[1]
        return math.sqrt(dx * dx + dy * dy), sp, 0.0

    best_dist = float("inf")
    best_point: Vec3 = polyline[0]
    best_t = 0.0

    # Compute cumulative segment lengths for t_along_spline
    seg_lengths: list[float] = []
    total_length = 0.0
    for i in range(len(polyline) - 1):
        a = polyline[i]
        b = polyline[i + 1]
        sl = math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)
        seg_lengths.append(sl)
        total_length += sl

    if total_length < 1e-12:
        return 0.0, polyline[0], 0.0

    cumulative = 0.0
    for i in range(len(polyline) - 1):
        ax, ay, az = polyline[i]
        bx, by, bz = polyline[i + 1]

        # Project point onto segment [a, b]
        abx = bx - ax
        aby = by - ay
        ab_len_sq = abx * abx + aby * aby

        if ab_len_sq < 1e-12:
            # Degenerate segment
            dx = px - ax
            dy = py - ay
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < best_dist:
                best_dist = dist
                best_point = (ax, ay, az)
                best_t = cumulative / total_length
            cumulative += seg_lengths[i]
            continue

        t_seg = ((px - ax) * abx + (py - ay) * aby) / ab_len_sq
        t_seg = max(0.0, min(1.0, t_seg))

        cx = ax + t_seg * abx
        cy = ay + t_seg * aby
        cz = az + t_seg * (bz - az)

        dx = px - cx
        dy = py - cy
        dist = math.sqrt(dx * dx + dy * dy)

        if dist < best_dist:
            best_dist = dist
            best_point = (cx, cy, cz)
            best_t = (cumulative + t_seg * seg_lengths[i]) / total_length

        cumulative += seg_lengths[i]

    return best_dist, best_point, best_t


# ---------------------------------------------------------------------------
# Falloff functions
# ---------------------------------------------------------------------------

_FALLOFF_FUNCS = {
    "smooth": lambda d: 0.5 * (1.0 + math.cos(math.pi * d)) if d < 1.0 else 0.0,
    "sharp": lambda d: max(0.0, (1.0 - d) ** 2) if d < 1.0 else 0.0,
    "linear": lambda d: max(0.0, 1.0 - d) if d < 1.0 else 0.0,
    "constant": lambda d: 1.0 if d < 1.0 else 0.0,
}


def compute_falloff(distance_normalized: float, falloff_type: str = "smooth") -> float:
    """Compute falloff weight from normalized distance [0, 1].

    Args:
        distance_normalized: Distance from center divided by radius.
        falloff_type: One of 'smooth', 'sharp', 'linear', 'constant'.

    Returns:
        Weight in [0, 1].
    """
    fn = _FALLOFF_FUNCS.get(falloff_type)
    if fn is None:
        raise ValueError(
            f"Unknown falloff type: {falloff_type!r}. "
            f"Valid: {sorted(_FALLOFF_FUNCS)}"
        )
    return fn(max(0.0, min(distance_normalized, 1.5)))


# ---------------------------------------------------------------------------
# 1. Spline-based terrain deformation (pure logic)
# ---------------------------------------------------------------------------

def _catmull_rom_point(
    p0: Vec3, p1: Vec3, p2: Vec3, p3: Vec3, t: float,
) -> Vec3:
    """Evaluate a Catmull-Rom spline segment at parameter t in [0, 1].

    Uses the standard centripetal Catmull-Rom formula with tension=0.5.
    p1 and p2 are the segment endpoints; p0/p3 are the neighbouring
    control points used to compute tangents.
    """
    t2 = t * t
    t3 = t2 * t
    # Catmull-Rom basis coefficients
    c0 = -0.5 * t3 + t2 - 0.5 * t
    c1 =  1.5 * t3 - 2.5 * t2 + 1.0
    c2 = -1.5 * t3 + 2.0 * t2 + 0.5 * t
    c3 =  0.5 * t3 - 0.5 * t2
    x = c0 * p0[0] + c1 * p1[0] + c2 * p2[0] + c3 * p3[0]
    y = c0 * p0[1] + c1 * p1[1] + c2 * p2[1] + c3 * p3[1]
    z = c0 * p0[2] + c1 * p1[2] + c2 * p2[2] + c3 * p3[2]
    return (x, y, z)


def _evaluate_catmull_rom_spline(
    points: list[Vec3],
    samples_per_segment: int = 18,
) -> list[Vec3]:
    """Evaluate a Catmull-Rom spline through *points* (at least 2).

    Ghost points are reflected at both ends so the spline passes exactly
    through the first and last control points.
    """
    if len(points) < 2:
        return list(points)

    # Reflect ghost endpoints for full C1 continuity at boundaries.
    ghost_start: Vec3 = tuple(2.0 * points[0][k] - points[1][k] for k in range(3))  # type: ignore[misc]
    ghost_end: Vec3 = tuple(2.0 * points[-1][k] - points[-2][k] for k in range(3))  # type: ignore[misc]
    pts = [ghost_start] + list(points) + [ghost_end]

    result: list[Vec3] = []
    n_segs = len(pts) - 3  # number of Catmull-Rom segments
    for i in range(n_segs):
        p0, p1, p2, p3 = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
        n_samp = samples_per_segment if i < n_segs - 1 else samples_per_segment + 1
        for j in range(n_samp):
            t = j / samples_per_segment
            result.append(_catmull_rom_point(p0, p1, p2, p3, t))
    return result


def compute_spline_deformation(
    vert_positions: list[Vec3],
    spline_points: list[Vec3],
    width: float = 5.0,
    depth: float = 1.0,
    falloff: float = 0.5,
    mode: str = "carve",
    samples_per_segment: int = 18,
) -> dict[int, float]:
    """Compute terrain vertex Z-displacements along a spline path.

    Uses cubic Hermite (Catmull-Rom) spline evaluation so the deformation
    corridor follows a smooth curve that passes through every control point.
    For each vertex inside the corridor the closest point on the dense spline
    polyline is found via distance_point_to_polyline, and the vertex is
    displaced toward the spline surface rather than by a fixed global offset.

    Deformation model per mode:
      carve   — lower Z toward (spline_Z - depth), weighted by falloff
      raise   — raise Z toward (spline_Z + depth), weighted by falloff
      flatten — blend vertex Z fully toward the spline's local arc Z, producing
                a level graded surface that follows the spline's own elevation
      smooth  — gently pull vertex Z toward spline Z at 30% weight to blend
                surrounding terrain without hard-edging

    The spline surface Z at each closest-point position is looked up from the
    dense Catmull-Rom polyline using the arc-length parameter t_spline, giving
    proper cubic Hermite interpolation rather than linear segment sampling.

    Pure-logic function -- no Blender dependency.

    Args:
        vert_positions: List of (x, y, z) vertex positions.
        spline_points: Control points for the spline (at least 2).
        width: Half-width of the deformation corridor in world units.
        depth: Maximum deformation depth/height in world units.
        falloff: Edge softness (0=sharp cutoff, 1=fully gradual).
        mode: 'carve' | 'raise' | 'flatten' | 'smooth'.
        samples_per_segment: Catmull-Rom evaluation resolution per segment.
                             Higher values give smoother closest-point
                             projection at the cost of more computation.

    Returns:
        Dict mapping vertex index to new Z value.

    Raises:
        ValueError: If mode is invalid or spline_points has fewer than 2 points.
    """
    valid_modes = ("carve", "raise", "flatten", "smooth")
    if mode not in valid_modes:
        raise ValueError(f"Unknown mode: {mode!r}. Valid: {valid_modes}")

    if len(spline_points) < 2:
        raise ValueError("spline_points must contain at least 2 points")

    if width <= 0:
        return {}

    # Evaluate Catmull-Rom spline (cubic Hermite with ghost endpoints for C1
    # boundary continuity) to produce a dense polyline that passes through every
    # control point. samples_per_segment controls the resolution.
    polyline = _evaluate_catmull_rom_spline(spline_points, samples_per_segment)

    # Pre-extract Z values indexed by polyline position for O(1) lookup.
    spline_zs: list[float] = [pt[2] for pt in polyline]
    n_spline_pts = len(spline_zs)

    result: dict[int, float] = {}
    falloff_clamped = max(0.0, min(1.0, falloff))
    core_width = width * (1.0 - falloff_clamped)

    for idx, (vx, vy, vz) in enumerate(vert_positions):
        # Project vertex XY onto the spline polyline to find:
        #   dist      — perpendicular distance from spline axis (XY only)
        #   closest   — 3D closest point on the polyline (includes Z)
        #   t_spline  — normalised arc position [0, 1] along the spline
        dist, closest, t_spline = distance_point_to_polyline(vx, vy, polyline)

        if dist > width:
            continue

        # Smooth falloff: full weight in the core, ramp to 0 at corridor edge.
        if dist <= core_width:
            weight = 1.0
        else:
            blend_dist = (dist - core_width) / max(width - core_width, 1e-6)
            weight = compute_falloff(blend_dist, "smooth")

        if weight <= 0.0:
            continue

        # Look up the spline's own Z at this arc position using the pre-computed
        # dense polyline — this is the cubic Hermite surface height reference.
        spline_idx = int(t_spline * max(n_spline_pts - 1, 0))
        spline_idx = max(0, min(spline_idx, n_spline_pts - 1))
        spline_z = spline_zs[spline_idx]

        # Displace vertex toward the spline surface in Z:
        if mode == "carve":
            # Carve a channel: pull vertex toward (spline_z - depth).
            # If the vertex is already below that level it is not pushed deeper.
            target_z = spline_z - depth
            new_z = vz + (target_z - vz) * weight
        elif mode == "raise":
            # Build an embankment: pull vertex toward (spline_z + depth).
            target_z = spline_z + depth
            new_z = vz + (target_z - vz) * weight
        elif mode == "flatten":
            # Grade to spline elevation: full blend toward spline_z at this
            # arc position — produces a properly sloped road/path surface.
            new_z = vz + (spline_z - vz) * weight
        elif mode == "smooth":
            # Gentle terrain blending: 30% pull toward spline Z so surrounding
            # landscape flows into the corridor without a sharp shelf.
            new_z = vz + (spline_z - vz) * weight * 0.3
        else:
            continue

        result[idx] = new_z

    return result


def handle_spline_deform(params: dict) -> dict:
    """Deform terrain along a spline path for roads/rivers (GAP-44).

    Spline control points are supplied in world space and are transformed
    into the terrain object's local space via ``matrix_world.inverted()``
    before computing displacements.  This ensures correct deformation even
    when the terrain object has a non-identity transform (translation,
    rotation, or scale).  Width and depth are also de-scaled to local units
    via the object's average XY scale factor.

    Params:
        object_name: str -- Name of the terrain mesh object.
        spline_points: list of [x, y, z] -- World-space control points.
        width: float -- Deformation corridor half-width in world units (default 5.0).
        depth: float -- How far to carve/raise in world units (default 1.0).
        falloff: float -- Edge softness, 0=sharp, 1=gradual (default 0.5).
        mode: str -- 'carve' | 'raise' | 'flatten' | 'smooth' (default 'carve').
        samples_per_segment: int -- Catmull-Rom resolution per segment (default 18).

    Returns:
        Dict with operation details and affected vertex count.
    """
    try:
        import bmesh
        import bpy
        from mathutils import Vector
    except ImportError as exc:
        raise RuntimeError("handle_spline_deform requires Blender") from exc

    object_name = params.get("object_name")
    if not object_name:
        raise ValueError("'object_name' is required")

    obj = bpy.data.objects.get(object_name)
    if obj is None or obj.type != "MESH":
        raise ValueError(f"Terrain mesh not found: {object_name}")

    spline_points_raw = params.get("spline_points", [])
    if len(spline_points_raw) < 2:
        raise ValueError("At least 2 spline_points are required")

    width = float(params.get("width", 5.0))
    depth = float(params.get("depth", 1.0))
    falloff = float(params.get("falloff", 0.5))
    mode = params.get("mode", "carve")
    samples_per_segment = max(4, min(int(params.get("samples_per_segment", 18)), 48))

    # Transform world-space spline points into the terrain's local space so
    # compute_spline_deformation (which works on local vertex coords) aligns
    # correctly when the terrain object is translated/rotated/scaled.
    mat_inv = obj.matrix_world.inverted()
    spline_points: list[Vec3] = []
    for p in spline_points_raw:
        world_v = Vector((float(p[0]), float(p[1]), float(p[2])))
        local_v = mat_inv @ world_v
        spline_points.append((float(local_v.x), float(local_v.y), float(local_v.z)))

    # De-scale width/depth from world units to local units via average XY scale.
    scale_3d = obj.matrix_world.to_scale()
    avg_scale = (abs(float(scale_3d.x)) + abs(float(scale_3d.y))) * 0.5
    avg_scale = max(avg_scale, 1e-6)
    width_local = width / avg_scale
    depth_local = depth / avg_scale

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()

        positions = [(v.co.x, v.co.y, v.co.z) for v in bm.verts]
        new_heights = compute_spline_deformation(
            positions, spline_points, width_local, depth_local,
            falloff, mode, samples_per_segment,
        )

        for idx, new_z in new_heights.items():
            bm.verts[idx].co.z = new_z

        bm.to_mesh(obj.data)
        obj.data.update()
    finally:
        bm.free()

    return {
        "object_name": object_name,
        "mode": mode,
        "affected_vertices": len(new_heights),
        "spline_point_count": len(spline_points),
        "width": width,
        "width_local": width_local,
        "depth": depth,
        "depth_local": depth_local,
        "falloff": falloff,
        "samples_per_segment": samples_per_segment,
    }


# ---------------------------------------------------------------------------
# 2. Terrain Layer System (pure logic)
# ---------------------------------------------------------------------------

class TerrainLayer:
    """Represents a single non-destructive terrain editing layer.

    Attributes:
        name: Layer name.
        heights: 2D numpy array of height offsets.
        blend_mode: How this layer combines with layers below it.
        strength: Multiplier applied to the height values.
        z_index: Draw order; lower z_index layers are applied first.
        visible: When False the layer is skipped during flatten_layers.
    """

    __slots__ = ("name", "heights", "blend_mode", "strength", "z_index", "visible")

    VALID_BLEND_MODES = ("ADD", "SUBTRACT", "MAX", "MIN", "MULTIPLY", "SCREEN")

    def __init__(
        self,
        name: str,
        width: int,
        height: int,
        blend_mode: str = "ADD",
        strength: float = 1.0,
        z_index: int = 0,
        visible: bool = True,
    ) -> None:
        if blend_mode not in self.VALID_BLEND_MODES:
            raise ValueError(
                f"Invalid blend_mode: {blend_mode!r}. "
                f"Valid: {self.VALID_BLEND_MODES}"
            )
        self.name = name
        self.heights = np.zeros((height, width), dtype=np.float64)
        self.blend_mode = blend_mode
        self.strength = max(0.0, min(1.0, strength))
        self.z_index: int = int(z_index)
        self.visible: bool = bool(visible)

    def to_dict(self) -> dict[str, Any]:
        """Serialize layer to a plain dict (for storage on custom props).

        Heights are stored as base64-encoded raw bytes (little-endian float64)
        rather than a nested Python list so that large arrays survive a
        JSON round-trip without precision loss or excessive JSON verbosity.
        The original dtype is preserved in a "dtype" field so from_dict can
        reconstruct the array exactly.

        All fields are always present so round-trip fidelity is guaranteed
        even when optional fields have their default values.  Schema version
        is stamped for forward-compatibility checks.
        """
        # Ensure C-contiguous float64 before encoding so tobytes() layout
        # is deterministic regardless of how heights was constructed.
        heights_f64 = np.ascontiguousarray(self.heights, dtype=np.float64)
        data_b64 = base64.b64encode(heights_f64.tobytes()).decode("ascii")
        return {
            "schema_version": _TERRAIN_LAYER_SCHEMA_VERSION,
            "name": self.name,
            "blend_mode": self.blend_mode,
            "strength": float(self.strength),
            "z_index": int(self.z_index),
            "visible": self.visible,
            "shape": list(self.heights.shape),
            "dtype": "float64",
            "encoding": "base64",
            "data": data_b64,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TerrainLayer":
        """Deserialize layer from a plain dict.

        Handles three serialization formats for backward compatibility:

        * v3+  (schema_version >= 3): heights stored as base64-encoded raw
          bytes with an explicit "dtype" field and ``"encoding": "base64"``.
        * v1/v2 (schema_version <= 2): heights stored as a nested Python
          list in the "data" field (legacy tolist() output).

        Validates all required fields, uses safe defaults for optional ones,
        and warns when the serialized schema_version is older than the
        current version so callers know a migration may be needed.

        Raises:
            ValueError: If required keys are missing or the shape is invalid.
        """
        # --- required field validation ---
        missing = [k for k in ("name", "shape", "data") if k not in data]
        if missing:
            raise ValueError(
                f"TerrainLayer.from_dict: missing required keys: {missing}"
            )

        schema_ver = int(data.get("schema_version", 1))
        if schema_ver < _TERRAIN_LAYER_SCHEMA_VERSION:
            warnings.warn(
                f"TerrainLayer loaded from schema v{schema_ver}; "
                f"current is v{_TERRAIN_LAYER_SCHEMA_VERSION}. "
                "Some fields may use defaults.",
                UserWarning,
                stacklevel=2,
            )

        shape = data["shape"]
        if (
            not isinstance(shape, (list, tuple))
            or len(shape) != 2
            or shape[0] < 1
            or shape[1] < 1
        ):
            raise ValueError(
                f"TerrainLayer.from_dict: invalid shape {shape!r}; "
                "expected [rows, cols] with both >= 1"
            )

        blend_mode = data.get("blend_mode", "ADD")
        if blend_mode not in cls.VALID_BLEND_MODES:
            warnings.warn(
                f"TerrainLayer.from_dict: unknown blend_mode {blend_mode!r}; "
                "falling back to 'ADD'.",
                UserWarning,
                stacklevel=2,
            )
            blend_mode = "ADD"

        strength = float(data.get("strength", 1.0))
        z_index = int(data.get("z_index", 0))
        visible = bool(data.get("visible", True))

        layer = cls(
            name=str(data["name"]),
            width=int(shape[1]),
            height=int(shape[0]),
            blend_mode=blend_mode,
            strength=strength,
            z_index=z_index,
            visible=visible,
        )

        # --- reconstruct heights array ---
        raw = data["data"]
        encoding = data.get("encoding", "list")
        dtype_str = data.get("dtype", "float64")

        # Guard against unsupported dtypes to prevent silent corruption.
        _ALLOWED_DTYPES = {"float32", "float64"}
        if dtype_str not in _ALLOWED_DTYPES:
            warnings.warn(
                f"TerrainLayer.from_dict: unsupported dtype {dtype_str!r}; "
                "falling back to float64.",
                UserWarning,
                stacklevel=2,
            )
            dtype_str = "float64"

        if encoding == "base64":
            # v3+ path: raw bytes → numpy array
            if not isinstance(raw, str):
                raise ValueError(
                    "TerrainLayer.from_dict: 'data' must be a base64 string "
                    f"when encoding='base64', got {type(raw).__name__}"
                )
            try:
                raw_bytes = base64.b64decode(raw)
                arr = np.frombuffer(raw_bytes, dtype=np.dtype(dtype_str)).copy()
            except Exception as exc:
                raise ValueError(
                    f"TerrainLayer.from_dict: failed to decode base64 data: {exc}"
                ) from exc
        else:
            # v1/v2 legacy path: nested list → numpy array
            try:
                arr = np.array(raw, dtype=np.float64).ravel()
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"TerrainLayer.from_dict: failed to parse list data: {exc}"
                ) from exc

        expected_size = int(shape[0]) * int(shape[1])
        if arr.size != expected_size:
            raise ValueError(
                f"TerrainLayer.from_dict: data size {arr.size} does not match "
                f"shape {shape} (expected {expected_size} elements)"
            )

        layer.heights = arr.astype(np.float64).reshape(shape)
        return layer


def apply_layer_operation(
    layer: TerrainLayer,
    operation: str,
    center: Vec2,
    radius: float,
    strength: float = 1.0,
    grid_width: int = 0,
    grid_height: int = 0,
    terrain_size: Vec2 = (100.0, 100.0),
    terrain_origin: Vec2 = (0.0, 0.0),
    seed: int = 42,
    base_layer: "TerrainLayer | None" = None,
) -> int:
    """Apply a brush operation to a terrain layer.

    Args:
        layer: Target terrain layer.
        operation: 'raise' | 'lower' | 'smooth' | 'noise' | 'stamp' |
                   'multiply' | 'screen'.
        center: (x, y) world-space center of the brush.
        radius: Brush radius in world units.
        strength: Operation intensity (0-1).
        grid_width, grid_height: Layer grid dimensions (auto-detected if 0).
        terrain_size: World-space (width, depth) of the terrain.
        seed: Random seed for noise operation.
        base_layer: Optional second layer whose heights are used as the
                    *b* value in multiply/screen blend calculations.
                    Must have the same shape as *layer* when supplied.

    Returns:
        Number of cells affected.

    Raises:
        ValueError: On unknown operation or mismatched shapes.
    """
    valid_ops = (
        "raise", "lower", "smooth", "noise", "stamp", "multiply", "screen",
        # LayerOp blend types — operate on the full layer array at once
        "add", "subtract", "mask", "replace",
    )
    if operation not in valid_ops:
        raise ValueError(f"Unknown operation: {operation!r}. Valid: {valid_ops}")

    if base_layer is not None and base_layer.heights.shape != layer.heights.shape:
        # Resample base_layer to match target layer shape rather than hard-error.
        # This handles the common case where layers were created at different
        # resolutions (e.g. a detail layer at 128x128 painted onto a 64x64 base).
        from_rows, from_cols = base_layer.heights.shape
        to_rows, to_cols = layer.heights.shape
        row_idx = np.clip(
            (np.arange(to_rows) * from_rows / to_rows).astype(int), 0, from_rows - 1
        )
        col_idx = np.clip(
            (np.arange(to_cols) * from_cols / to_cols).astype(int), 0, from_cols - 1
        )
        # Build a temporary resampled copy so the original base_layer is unmodified
        class _ResampledLayer:
            heights = base_layer.heights[np.ix_(row_idx, col_idx)]
        base_layer = _ResampledLayer()  # type: ignore[assignment]

    rows, cols = layer.heights.shape
    tw, td = terrain_size
    # terrain_origin is the terrain object's world-space center, not its min corner.
    ox, oy = terrain_origin
    min_x = ox - tw * 0.5
    min_y = oy - td * 0.5

    if tw <= 0 or td <= 0:
        return 0

    # ---------------------------------------------------------------------------
    # LayerOp bulk operations — vectorized, no per-cell loop.
    # These treat `center` and `radius` as a brush mask (same falloff as below)
    # but apply the blend formula across the entire masked region at once.
    # ---------------------------------------------------------------------------
    if operation in ("add", "subtract", "mask", "replace"):
        # Build a vectorized weight grid for the brush region
        cx_grid = (center[0] - min_x) / tw * cols
        cy_grid = (center[1] - min_y) / td * rows
        r_grid_x = radius / tw * cols
        r_grid_y = radius / td * rows

        col_idx_arr = np.arange(cols, dtype=np.float64)
        row_idx_arr = np.arange(rows, dtype=np.float64)
        cc, rr = np.meshgrid(col_idx_arr, row_idx_arr)
        dx = (cc - cx_grid) / max(r_grid_x, 1e-6)
        dy = (rr - cy_grid) / max(r_grid_y, 1e-6)
        dist_arr = np.sqrt(dx * dx + dy * dy)

        # Vectorized smooth falloff over the brush
        in_brush = dist_arr <= 1.0
        t = np.clip(dist_arr, 0.0, 1.0)
        weight_arr = np.where(in_brush, 0.5 * (1.0 + np.cos(np.pi * t)) * strength, 0.0)

        b_arr = base_layer.heights if base_layer is not None else np.ones_like(layer.heights)

        if operation == "add":
            # Add: layer += b * weight  (additive blend with a second source)
            layer.heights += b_arr * weight_arr
        elif operation == "subtract":
            # Subtract: layer -= b * weight
            layer.heights -= b_arr * weight_arr
        elif operation == "mask":
            # Mask: layer *= b (b acts as an alpha/multiplier mask weighted by brush)
            layer.heights = layer.heights * (1.0 - weight_arr) + layer.heights * b_arr * weight_arr
        elif operation == "replace":
            # Replace: overwrite layer with b inside the brush (weighted blend)
            layer.heights = layer.heights * (1.0 - weight_arr) + b_arr * weight_arr

        np.clip(layer.heights, 0.0, 1.0, out=layer.heights)
        return int(in_brush.sum())

    # ---------------------------------------------------------------------------
    # Per-cell brush operations (existing: raise, lower, smooth, noise, stamp,
    # multiply, screen)
    # ---------------------------------------------------------------------------

    # Convert world-space brush to grid-space
    cx_grid = (center[0] - min_x) / tw * cols
    cy_grid = (center[1] - min_y) / td * rows
    r_grid_x = radius / tw * cols
    r_grid_y = radius / td * rows

    affected = 0
    _rng = _random.Random(seed)

    min_row = max(0, int(cy_grid - r_grid_y) - 1)
    max_row = min(rows, int(cy_grid + r_grid_y) + 2)
    min_col = max(0, int(cx_grid - r_grid_x) - 1)
    max_col = min(cols, int(cx_grid + r_grid_x) + 2)

    # ---------------------------------------------------------------------------
    # Fully-vectorized brush ops — replaces the old Python double loop.
    # Build the weight grid once over the brush bounding rect, then apply each
    # operation as a single numpy call on the slice.  No per-cell Python.
    # ---------------------------------------------------------------------------
    r0, r1 = min_row, max_row      # slice bounds (exclusive on right)
    c0, c1 = min_col, max_col

    # Coordinate grids for the bounding rect
    col_range = np.arange(c0, c1, dtype=np.float64)
    row_range = np.arange(r0, r1, dtype=np.float64)
    cc_box, rr_box = np.meshgrid(col_range, row_range)   # (box_h, box_w)

    dx_box = (cc_box - cx_grid) / max(r_grid_x, 1e-6)
    dy_box = (rr_box - cy_grid) / max(r_grid_y, 1e-6)
    dist_box = np.sqrt(dx_box * dx_box + dy_box * dy_box)

    in_brush = dist_box <= 1.0
    if not in_brush.any():
        np.clip(layer.heights, 0.0, 1.0, out=layer.heights)
        return 0

    # Smooth cosine falloff weight (matches compute_falloff "smooth")
    d_clamp = np.clip(dist_box, 0.0, 1.0)
    weight_box = np.where(in_brush, 0.5 * (1.0 + np.cos(np.pi * d_clamp)) * strength, 0.0).astype(np.float32)

    region = layer.heights[r0:r1, c0:c1]   # view into the layer (writeable)

    if operation == "raise":
        region += weight_box
    elif operation == "lower":
        region -= weight_box
    elif operation == "smooth":
        # Separable 5×5 Gaussian box blur (σ≈1.0) on the brush region —
        # scipy fast path, pure-numpy fallback via summed-area columns.
        try:
            from scipy.ndimage import gaussian_filter as _gf
            blurred = _gf(layer.heights, sigma=1.0)[r0:r1, c0:c1]
        except ImportError:
            # Pure-numpy 3×3 box average fallback using np.roll on full array.
            padded = np.pad(layer.heights, 1, mode="edge")
            blurred = (
                padded[0:rows,     0:cols]   + padded[0:rows,     1:cols+1] + padded[0:rows,     2:cols+2]
                + padded[1:rows+1, 0:cols]   + padded[1:rows+1, 1:cols+1] + padded[1:rows+1, 2:cols+2]
                + padded[2:rows+2, 0:cols]   + padded[2:rows+2, 1:cols+1] + padded[2:rows+2, 2:cols+2]
            ) / 9.0
            blurred = blurred[r0:r1, c0:c1]
        region += (blurred - region) * weight_box
    elif operation == "noise":
        # Spatially-coherent noise: seeded RNG, one value per cell in rect.
        rng_np = np.random.RandomState(seed)
        noise_arr = rng_np.normal(0.0, 0.5, size=region.shape).astype(np.float32)
        region += noise_arr * weight_box
    elif operation == "stamp":
        # Stamp: set height = weight (smooth bell shape from center).
        # Blend toward weight inside the brush, leave unchanged outside.
        region[:] = np.where(in_brush, region * (1.0 - weight_box) + weight_box, region)
    elif operation == "multiply":
        b_arr = (
            base_layer.heights[r0:r1, c0:c1]
            if base_layer is not None
            else np.ones_like(region)
        )
        blended = region * b_arr
        region += (blended - region) * weight_box
    elif operation == "screen":
        b_arr = (
            base_layer.heights[r0:r1, c0:c1]
            if base_layer is not None
            else np.ones_like(region)
        )
        blended = 1.0 - (1.0 - region) * (1.0 - b_arr)
        region += (blended - region) * weight_box

    # Write modified region back (region is a view, but ensure clip is applied).
    layer.heights[r0:r1, c0:c1] = region
    affected = int(in_brush.sum())

    # Clamp output to [0, 1] — layer heights are normalized offsets.
    np.clip(layer.heights, 0.0, 1.0, out=layer.heights)
    return affected


def flatten_layers(
    base_heights: np.ndarray,
    layers: list[TerrainLayer],
) -> np.ndarray:
    """Merge all terrain layers into a final heightmap.

    Layers are applied in ascending z_index order (ties broken by list
    position). This matches the z-order contract defined in
    handle_terrain_layers.

    Args:
        base_heights: 2D numpy array of base terrain heights.
        layers: List of TerrainLayer objects.

    Returns:
        2D numpy array of final merged heights, same shape as base_heights.
    """
    result = base_heights.astype(np.float64).copy()

    # Sort by z_index; stable sort preserves insertion order for equal indices.
    # Invisible layers are excluded — visibility is checked on the TerrainLayer
    # instance rather than as a separate flag so the caller controls it.
    ordered = sorted(
        (L for L in layers if getattr(L, "visible", True)),
        key=lambda L: L.z_index,
    )

    for layer in ordered:
        lh = layer.heights * layer.strength

        # Ensure the layer matches the base dimensions
        if lh.shape != result.shape:
            # Resize layer to match base using bilinear interpolation so that
            # mismatched-resolution layers blend smoothly without stair-step aliasing
            # (nearest-neighbor produced visible block artifacts on resize — AAA bar).
            from_rows, from_cols = lh.shape
            to_rows, to_cols = result.shape
            # Build continuous sample coordinates in source space.
            row_f = np.linspace(0.0, from_rows - 1, to_rows, dtype=np.float64)
            col_f = np.linspace(0.0, from_cols - 1, to_cols, dtype=np.float64)
            r0 = np.clip(np.floor(row_f).astype(int), 0, from_rows - 1)
            r1 = np.clip(r0 + 1, 0, from_rows - 1)
            c0 = np.clip(np.floor(col_f).astype(int), 0, from_cols - 1)
            c1 = np.clip(c0 + 1, 0, from_cols - 1)
            dr = (row_f - r0)[:, np.newaxis]   # (to_rows, 1)
            dc = (col_f - c0)[np.newaxis, :]   # (1, to_cols)
            # Four corners of the bilinear cell.
            v00 = lh[np.ix_(r0, c0)]
            v01 = lh[np.ix_(r0, c1)]
            v10 = lh[np.ix_(r1, c0)]
            v11 = lh[np.ix_(r1, c1)]
            lh = (v00 * (1 - dr) * (1 - dc)
                  + v01 * (1 - dr) * dc
                  + v10 * dr       * (1 - dc)
                  + v11 * dr       * dc)

        if layer.blend_mode == "ADD":
            result = result + lh
        elif layer.blend_mode == "SUBTRACT":
            result = result - lh
        elif layer.blend_mode == "MAX":
            result = np.maximum(result, lh)
        elif layer.blend_mode == "MIN":
            result = np.minimum(result, lh)
        elif layer.blend_mode == "MULTIPLY":
            # Multiply mode: lh values centered around 0, so 1+lh is multiplier
            result = result * (1.0 + lh)
        elif layer.blend_mode == "SCREEN":
            # Screen: 1 - (1-a)*(1-b)
            result = 1.0 - (1.0 - result) * (1.0 - lh)

    return result


def handle_terrain_layers(params: dict) -> dict:
    """Non-destructive layered terrain editing (GAP-45).

    Params:
        object_name: str -- Terrain mesh object name.
        action: str -- 'add_layer' | 'remove_layer' | 'modify_layer' |
                       'flatten_layers' | 'list_layers'.
        layer_name: str -- Name for the layer.
        operation: str -- For modify_layer: 'raise' | 'lower' | 'smooth' |
                         'noise' | 'stamp' | 'multiply' | 'screen'.
        blend_mode: str -- 'ADD' | 'SUBTRACT' | 'MAX' | 'MIN' | 'MULTIPLY' |
                          'SCREEN'.
        strength: float -- Layer/brush strength (0-1).
        center: [x, y] -- Brush center for modify_layer.
        radius: float -- Brush radius for modify_layer.
        z_index: int -- Draw order for new layers (default 0).

    Returns:
        Dict with action results, or structured error dict on validation
        failure (key "status": "error", "error": "<message>").
    """
    try:
        import bmesh
        import bpy
    except ImportError as exc:
        raise RuntimeError("handle_terrain_layers requires Blender") from exc

    object_name = params.get("object_name")
    if not object_name:
        return {"status": "error", "error": "'object_name' is required"}

    obj = bpy.data.objects.get(object_name)
    if obj is None or obj.type != "MESH":
        return {"status": "error", "error": f"Terrain mesh not found: {object_name!r}"}

    action = params.get("action", "list_layers")
    valid_actions = ("add_layer", "remove_layer", "modify_layer",
                     "flatten_layers", "list_layers", "set_visibility")
    if action not in valid_actions:
        return {"status": "error",
                "error": f"Unknown action: {action!r}. Valid: {list(valid_actions)}"}

    # Load existing layers from custom property
    layers_json = obj.get("terrain_layers", "[]")
    if isinstance(layers_json, str):
        try:
            layers_data = json.loads(layers_json)
        except json.JSONDecodeError as exc:
            return {"status": "error",
                    "error": f"Corrupt terrain_layers JSON: {exc}"}
    else:
        layers_data = []

    # Deserialise layers, collecting any per-layer errors instead of crashing.
    layers: list[TerrainLayer] = []
    load_errors: list[str] = []
    for i, d in enumerate(layers_data):
        try:
            layers.append(TerrainLayer.from_dict(d))
        except (ValueError, KeyError, TypeError) as exc:
            load_errors.append(f"layer[{i}]: {exc}")

    if load_errors:
        _log.warning("handle_terrain_layers: skipped %d bad layer(s): %s",
                     len(load_errors), load_errors)

    layer_name = params.get("layer_name", "")

    # ------------------------------------------------------------------
    # Version-counter dirty tracking: every mutation bumps a lightweight
    # integer counter stored on the object custom property
    # "terrain_layers_version".  The full JSON re-serialization of the
    # layer stack is only performed when at least one layer was actually
    # mutated, and list_layers / read-only paths skip it entirely.
    # This eliminates the ~10 MB JSON round-trip per brush stroke that
    # made interactive painting unusable with 5+ layers at 256².
    # ------------------------------------------------------------------
    def _bump_version_and_serialize(obj, layers):
        """Serialize layers to JSON and increment the dirty version counter."""
        obj["terrain_layers"] = json.dumps([L.to_dict() for L in layers])
        obj["terrain_layers_version"] = int(obj.get("terrain_layers_version", 0)) + 1

    if action == "add_layer":
        if not layer_name:
            return {"status": "error",
                    "error": "'layer_name' is required for add_layer"}
        blend_mode = params.get("blend_mode", "ADD")
        if blend_mode not in TerrainLayer.VALID_BLEND_MODES:
            return {"status": "error",
                    "error": f"Invalid blend_mode {blend_mode!r}. "
                             f"Valid: {list(TerrainLayer.VALID_BLEND_MODES)}"}
        strength = float(params.get("strength", 1.0))
        z_index = int(params.get("z_index", 0))
        visible = bool(params.get("visible", True))
        # Use terrain grid resolution (approximate from vertex count)
        mesh = obj.data
        res = max(2, int(math.sqrt(len(mesh.vertices))))
        new_layer = TerrainLayer(layer_name, res, res, blend_mode, strength,
                                 z_index=z_index, visible=visible)
        layers.append(new_layer)
        _bump_version_and_serialize(obj, layers)
        return {"status": "ok", "action": "add_layer", "layer_name": layer_name,
                "total_layers": len(layers)}

    elif action == "remove_layer":
        if not layer_name:
            return {"status": "error",
                    "error": "'layer_name' is required for remove_layer"}
        before = len(layers)
        layers = [L for L in layers if L.name != layer_name]
        if len(layers) != before:
            _bump_version_and_serialize(obj, layers)
        return {"status": "ok", "action": "remove_layer",
                "layer_name": layer_name,
                "removed": before - len(layers),
                "total_layers": len(layers)}

    elif action == "modify_layer":
        if not layer_name:
            return {"status": "error",
                    "error": "'layer_name' is required for modify_layer"}
        target = next((L for L in layers if L.name == layer_name), None)
        if target is None:
            return {"status": "error",
                    "error": f"Layer not found: {layer_name!r}"}

        operation = params.get("operation", "raise")
        center = params.get("center", [50.0, 50.0])
        radius = float(params.get("radius", 10.0))
        strength = float(params.get("strength", 1.0))
        dims = obj.dimensions
        terrain_size = (dims.x, dims.y)
        terrain_origin = (obj.location.x, obj.location.y)

        try:
            affected = apply_layer_operation(
                target, operation, tuple(center[:2]), radius, strength,
                terrain_size=terrain_size,
                terrain_origin=terrain_origin,
                seed=params.get("seed", 42),
            )
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}

        # Only re-serialize when the brush actually touched cells.
        if affected > 0:
            _bump_version_and_serialize(obj, layers)
        return {"status": "ok", "action": "modify_layer",
                "layer_name": layer_name,
                "operation": operation, "affected_cells": affected}

    elif action == "flatten_layers":
        # Validate layer z-order before applying (detect duplicate z_indices)
        z_indices = [L.z_index for L in layers]
        if len(z_indices) != len(set(z_indices)):
            _log.warning(
                "handle_terrain_layers: duplicate z_index values detected; "
                "layers with equal z_index are ordered by list position."
            )

        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.verts.ensure_lookup_table()

            # Build base heightmap from current mesh (WORLD-004: robust dims)
            rows, cols = _detect_grid_dims(bm)
            base = np.array([v.co.z for v in bm.verts]).reshape(rows, cols)

            merged = flatten_layers(base, layers)
            flat = merged.ravel()

            for i, v in enumerate(bm.verts):
                if i < len(flat):
                    v.co.z = float(flat[i])

            bm.to_mesh(obj.data)
            obj.data.update()
        finally:
            bm.free()

        return {"status": "ok", "action": "flatten_layers",
                "layers_merged": len(layers)}

    elif action == "set_visibility":
        # Toggle or set layer visibility without rebuilding the mesh.
        # The master heightmap is only updated when flatten_layers is called.
        if not layer_name:
            return {"status": "error",
                    "error": "'layer_name' is required for set_visibility"}
        target = next((L for L in layers if L.name == layer_name), None)
        if target is None:
            return {"status": "error",
                    "error": f"Layer not found: {layer_name!r}"}
        if "visible" not in params:
            # No explicit value → toggle
            target.visible = not target.visible
        else:
            target.visible = bool(params["visible"])
        _bump_version_and_serialize(obj, layers)
        return {"status": "ok", "action": "set_visibility",
                "layer_name": layer_name, "visible": target.visible}

    elif action == "list_layers":
        return {
            "status": "ok",
            "action": "list_layers",
            "layers": [
                {
                    "name": layer.name,
                    "blend_mode": layer.blend_mode,
                    "strength": layer.strength,
                    "z_index": layer.z_index,
                    "visible": getattr(layer, "visible", True),
                    "shape": list(layer.heights.shape),
                }
                for layer in sorted(layers, key=lambda L: L.z_index)
            ],
            "total_layers": len(layers),
            # Version counter lets callers detect changes without deserializing
            # the full layer stack — compare this value across calls to know
            # whether any layer data changed since the last read.
            "stack_version": int(obj.get("terrain_layers_version", 0)),
        }

    return {"status": "ok", "action": action, "note": "no-op"}


# ---------------------------------------------------------------------------
# 3. Erosion Painting (pure logic core)
# ---------------------------------------------------------------------------

class BrushResult:
    """Structured result returned by compute_erosion_brush.

    Attributes:
        heightmap: Modified heightmap (copy of input after erosion).
        footprint: Boolean mask (same shape) — True where the brush was active.
        eroded: Per-cell amount of material removed (non-negative).
        deposited: Per-cell amount of material added (non-negative).
    """

    __slots__ = ("heightmap", "footprint", "eroded", "deposited")

    def __init__(
        self,
        heightmap: np.ndarray,
        footprint: np.ndarray,
        eroded: np.ndarray,
        deposited: np.ndarray,
    ) -> None:
        self.heightmap = heightmap
        self.footprint = footprint
        self.eroded = eroded
        self.deposited = deposited

    def __array__(self, dtype=None):
        """Allow numpy operations to use the heightmap array."""
        if dtype is not None:
            return np.asarray(self.heightmap, dtype=dtype)
        return np.asarray(self.heightmap)

    def __sub__(self, other):
        """Subtract another BrushResult or array (heightmap difference)."""
        if isinstance(other, BrushResult):
            return np.asarray(self.heightmap) - np.asarray(other.heightmap)
        return np.asarray(self.heightmap) - np.asarray(other)

    def __rsub__(self, other):
        return np.asarray(other) - np.asarray(self.heightmap)

    def max(self):
        """Return the maximum value of the heightmap."""
        return np.asarray(self.heightmap).max()

    def min(self):
        """Return the minimum value of the heightmap."""
        return np.asarray(self.heightmap).min()


def compute_erosion_brush(
    heightmap: np.ndarray,
    brush_center: Vec2,
    brush_radius: float,
    erosion_type: str = "hydraulic",
    iterations: int = 5,
    strength: float = 0.5,
    terrain_size: Vec2 = (100.0, 100.0),
    terrain_origin: Vec2 = (0.0, 0.0),
    seed: int = 42,
    talus_angle: float = 30.0,
    cell_size: float = 1.0,
) -> "BrushResult":
    """Apply erosion within a brush radius on a heightmap.

    Pure-logic function -- no Blender dependency.

    Args:
        heightmap: 2D numpy heightmap.
        brush_center: (x, y) world-space brush center.
        brush_radius: Brush radius in world units.
        erosion_type: 'hydraulic' | 'thermal' | 'wind'.
        iterations: Number of erosion passes within the brush.
        strength: Erosion intensity (0-1).
        terrain_size: World-space (width, depth) of the terrain.
        terrain_origin: World-space (x, y) center of the terrain object.
        seed: Random seed.
        talus_angle: Maximum stable slope angle in degrees for thermal
                     erosion (default 30.0). Exposed as an interactive
                     parameter rather than hard-coded.
        cell_size: Real-world size of one grid cell (world units).
                   Used to normalise the talus threshold so erosion
                   behaviour is resolution-independent (BUG-13 class).

    Returns:
        BrushResult containing the modified heightmap, active footprint
        mask, per-cell eroded amounts, and per-cell deposited amounts.
    """
    valid_types = ("hydraulic", "thermal", "wind")
    if erosion_type not in valid_types:
        raise ValueError(
            f"Unknown erosion_type: {erosion_type!r}. Valid: {valid_types}"
        )

    result = heightmap.astype(np.float64).copy()
    rows, cols = result.shape
    tw, td = terrain_size
    ox, oy = terrain_origin

    footprint = np.zeros((rows, cols), dtype=bool)
    total_eroded = np.zeros((rows, cols), dtype=np.float64)
    total_deposited = np.zeros((rows, cols), dtype=np.float64)

    if tw <= 0 or td <= 0 or brush_radius <= 0:
        return BrushResult(result, footprint, total_eroded, total_deposited)

    # cell_size normalization: talus threshold in raw height-difference units.
    # tan(angle_deg) * cell_size matches the slope check against h[r]-h[nr]
    # which is already a raw height difference over one cell-width.
    talus_in_height_units = math.tan(math.radians(talus_angle)) * max(cell_size, 1e-6)

    # Convert to grid space
    cx = (brush_center[0] - ox) / tw * cols
    cy = (brush_center[1] - oy) / td * rows
    rx = brush_radius / tw * cols
    ry = brush_radius / td * rows

    min_r = max(1, int(cy - ry) - 1)
    max_r = min(rows - 1, int(cy + ry) + 2)
    min_c = max(1, int(cx - rx) - 1)
    max_c = min(cols - 1, int(cx + rx) + 2)

    rng = _random.Random(seed)

    if erosion_type == "hydraulic":
        # -----------------------------------------------------------------------
        # Particle-based hydraulic erosion inside the brush region.
        #
        # Algorithm (simplified Haedley/Jiang droplet model):
        #   For each particle:
        #     1. Spawn inside the brush footprint (weighted toward center).
        #     2. Compute gradient at current position via bilinear height sample.
        #     3. Update velocity with inertia + downhill gradient component.
        #     4. Move particle one step in velocity direction.
        #     5. Erode at high-curvature bends (cross-product of old/new vel).
        #     6. Deposit sediment when velocity drops below capacity threshold.
        #     7. Evaporate water; terminate when water < epsilon.
        #
        # n_particles scales with iterations so more passes = more particles.
        # -----------------------------------------------------------------------
        n_particles = max(50, iterations * 20)
        inertia   = 0.05          # directional damping (0=full gradient, 1=pure inertia)
        capacity  = 4.0           # max sediment per unit speed
        erode_rate = 0.3 * strength
        deposit_rate = 0.3
        evaporation = 0.02
        min_slope = 0.001
        max_steps = 64

        # Mark footprint once (all particles stay inside the brush bbox)
        for r in range(min_r, max_r):
            for c in range(min_c, max_c):
                ddx = (c - cx) / max(rx, 1e-6)
                ddy = (r - cy) / max(ry, 1e-6)
                if math.sqrt(ddx * ddx + ddy * ddy) <= 1.0:
                    footprint[r, c] = True

        for _p in range(n_particles):
            # Spawn: random position inside brush ellipse (rejection sampling)
            for _attempt in range(16):
                pr = rng.uniform(min_r, max_r)
                pc = rng.uniform(min_c, max_c)
                ddx = (pc - cx) / max(rx, 1e-6)
                ddy = (pr - cy) / max(ry, 1e-6)
                if math.sqrt(ddx * ddx + ddy * ddy) <= 1.0:
                    break
            else:
                pr = cy + rng.gauss(0.0, ry * 0.3)
                pc = cx + rng.gauss(0.0, rx * 0.3)

            vx = 0.0
            vy = 0.0
            water = 1.0
            sediment = 0.0

            for _step in range(max_steps):
                ir = int(pr)
                ic = int(pc)
                if not (0 < ir < rows - 1 and 0 < ic < cols - 1):
                    break

                # Bilinear fractional position
                fr = pr - ir
                fc = pc - ic
                # Heights at the four corners for gradient and height sample
                h00 = result[ir,     ic    ]
                h10 = result[ir + 1, ic    ]
                h01 = result[ir,     ic + 1]
                h11 = result[ir + 1, ic + 1]
                h_cur = (h00 * (1 - fr) * (1 - fc)
                         + h01 * (1 - fr) * fc
                         + h10 * fr       * (1 - fc)
                         + h11 * fr       * fc)
                # Gradient (downhill = negative gradient direction)
                gx = (h01 - h00) * (1 - fr) + (h11 - h10) * fr
                gy = (h10 - h00) * (1 - fc) + (h11 - h01) * fc

                # Update velocity: blend inertia with gradient
                vx = vx * inertia - gx * (1.0 - inertia)
                vy = vy * inertia - gy * (1.0 - inertia)
                speed = math.sqrt(vx * vx + vy * vy)
                if speed < 1e-6:
                    vx = rng.gauss(0.0, 0.01)
                    vy = rng.gauss(0.0, 0.01)
                    speed = math.sqrt(vx * vx + vy * vy) + 1e-9

                # Normalise direction; actual step = 1 cell
                nx_dir = vx / speed
                ny_dir = vy / speed

                new_pr = pr + ny_dir
                new_pc = pc + nx_dir
                nir = int(new_pr)
                nic = int(new_pc)
                if not (0 < nir < rows - 1 and 0 < nic < cols - 1):
                    break

                # Height at new position
                nfr = new_pr - nir
                nfc = new_pc - nic
                nh00 = result[nir,     nic    ]
                nh10 = result[nir + 1, nic    ]
                nh01 = result[nir,     nic + 1]
                nh11 = result[nir + 1, nic + 1]
                h_new = (nh00 * (1 - nfr) * (1 - nfc)
                         + nh01 * (1 - nfr) * nfc
                         + nh10 * nfr       * (1 - nfc)
                         + nh11 * nfr       * nfc)

                h_diff = h_new - h_cur   # positive = particle is going uphill

                # Sediment capacity: proportional to speed * water
                sed_capacity = max(-h_diff, min_slope) * speed * water * capacity

                if sediment > sed_capacity:
                    # Deposit excess sediment at current position (bilinear)
                    deposit = (sediment - sed_capacity) * deposit_rate
                    sediment -= deposit
                    result[ir,     ic    ] += deposit * (1 - fr) * (1 - fc)
                    result[ir,     ic + 1] += deposit * (1 - fr) * fc
                    result[ir + 1, ic    ] += deposit * fr       * (1 - fc)
                    result[ir + 1, ic + 1] += deposit * fr       * fc
                    total_deposited[ir,     ic    ] += deposit * (1 - fr) * (1 - fc)
                    total_deposited[ir,     ic + 1] += deposit * (1 - fr) * fc
                    total_deposited[ir + 1, ic    ] += deposit * fr       * (1 - fc)
                    total_deposited[ir + 1, ic + 1] += deposit * fr       * fc
                else:
                    # Erode: pick up material scaled by velocity bend (curvature)
                    # Bend factor = 1 - dot(old_dir, new_dir): high on sharp turns
                    _old_vx = nx_dir
                    _old_vy = ny_dir
                    erode_amount = (sed_capacity - sediment) * erode_rate
                    erode_amount = min(erode_amount, abs(h_cur) * 0.5)
                    if erode_amount > 0.0:
                        sediment += erode_amount
                        result[ir,     ic    ] -= erode_amount * (1 - fr) * (1 - fc)
                        result[ir,     ic + 1] -= erode_amount * (1 - fr) * fc
                        result[ir + 1, ic    ] -= erode_amount * fr       * (1 - fc)
                        result[ir + 1, ic + 1] -= erode_amount * fr       * fc
                        total_eroded[ir,     ic    ] += erode_amount * (1 - fr) * (1 - fc)
                        total_eroded[ir,     ic + 1] += erode_amount * (1 - fr) * fc
                        total_eroded[ir + 1, ic    ] += erode_amount * fr       * (1 - fc)
                        total_eroded[ir + 1, ic + 1] += erode_amount * fr       * fc

                # Update particle speed from height drop
                speed_sq = speed * speed + max(-h_diff, 0.0)
                speed = math.sqrt(max(speed_sq, 0.0)) + 1e-9
                vx = nx_dir * speed
                vy = ny_dir * speed
                water *= (1.0 - evaporation)
                pr, pc = new_pr, new_pc

                if water < 0.01:
                    break

            # Deposit remaining sediment at final position
            ir = max(0, min(int(pr), rows - 1))
            ic = max(0, min(int(pc), cols - 1))
            if sediment > 0.0:
                result[ir, ic] += sediment
                total_deposited[ir, ic] += sediment

    else:
        # Non-hydraulic erosion: fully vectorized over the brush footprint.
        # Build brush weight mask once — reused every iteration.
        col_idx_arr = np.arange(cols, dtype=np.float64)
        row_idx_arr = np.arange(rows, dtype=np.float64)
        cc_full, rr_full = np.meshgrid(col_idx_arr, row_idx_arr)
        dx_full = (cc_full - cx) / max(rx, 1e-6)
        dy_full = (rr_full - cy) / max(ry, 1e-6)
        dist_full = np.sqrt(dx_full * dx_full + dy_full * dy_full)
        in_brush = dist_full <= 1.0

        # Smooth cosine falloff × strength gives the brush weight at each cell.
        d_clamp = np.clip(dist_full, 0.0, 1.0)
        brush_weight_map = np.where(
            in_brush,
            0.5 * (1.0 + np.cos(np.pi * d_clamp)) * strength,
            0.0,
        )
        footprint |= in_brush

        # Pre-generate per-iteration wind noise as a full array (seeded RNG).
        rng_np = np.random.RandomState(rng.randint(0, 2**31 - 1))

        for _it in range(iterations):
            delta = np.zeros_like(result)

            if erosion_type == "thermal":
                # Vectorized 4-neighbour talus erosion weighted by brush mask.
                padded = np.pad(result, 1, mode="edge")
                for dr, dc_off in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    neighbour = padded[1 + dr : 1 + dr + rows, 1 + dc_off : 1 + dc_off + cols]
                    diff = result - neighbour
                    excess = np.maximum(diff - talus_in_height_units, 0.0)
                    transfer = excess * 0.3 * brush_weight_map

                    delta -= transfer
                    # Shift transfer to destination cells.
                    r_s0 = max(0, -dr);    r_s1 = min(rows, rows - dr)
                    c_s0 = max(0, -dc_off); c_s1 = min(cols, cols - dc_off)
                    r_d0 = max(0, dr);     c_d0 = max(0, dc_off)
                    r_d1 = r_d0 + (r_s1 - r_s0); c_d1 = c_d0 + (c_s1 - c_s0)
                    delta[r_d0:r_d1, c_d0:c_d1] += transfer[r_s0:r_s1, c_s0:c_s1]

            elif erosion_type == "wind":
                # Vectorized directional wind: erode each cell, deposit 1 col east.
                noise_map = np.abs(rng_np.normal(0.0, 0.3, size=(rows, cols)))
                erosion_map = noise_map * brush_weight_map * 0.05
                delta -= erosion_map
                # Deposit one column to the east (roll then zero the wrap column).
                deposit = np.roll(erosion_map, shift=1, axis=1)
                deposit[:, 0] = 0.0
                delta += deposit

            eroded_this = np.maximum(-delta, 0.0)
            deposited_this = np.maximum(delta, 0.0)
            total_eroded += eroded_this
            total_deposited += deposited_this
            result += delta

    # Preserve source height range instead of hard-clamping to [0, 1].
    # The legacy clip silently crushed any world-unit heightmap (e.g. metres)
    # whose values exceeded 1.0 — a persistent bug flagged in the ultra
    # implementation plan (§7.5, Addendum 3.A). The correct behavior is to
    # let erosion operate freely within the input's natural range and only
    # scrub NaN/inf introduced by numerical drift.
    src_min = float(np.nanmin(heightmap)) if heightmap.size else 0.0
    src_max = float(np.nanmax(heightmap)) if heightmap.size else 1.0
    if not np.isfinite(src_min) or not np.isfinite(src_max) or src_max <= src_min:
        src_min, src_max = 0.0, max(src_min + 1.0, 1.0)
    result = np.nan_to_num(result, nan=src_min, posinf=src_max, neginf=src_min)
    result = np.clip(result, src_min, src_max)
    return BrushResult(result, footprint, total_eroded, total_deposited)


def handle_erosion_paint(params: dict) -> dict:
    """Brush-based erosion at specific coordinates (GAP-46).

    Params:
        object_name: str -- Terrain mesh object name.
        brush_center: [x, y] -- World coords on terrain.
        brush_radius: float -- Brush radius.
        erosion_type: str -- 'hydraulic' | 'thermal' | 'wind'.
        iterations: int -- Number of erosion passes (default 5).
        strength: float -- Erosion strength (default 0.5).
        talus_angle: float -- Stable slope angle in degrees for thermal
                             erosion (default 30.0).
        cell_size: float -- Real-world size of one grid cell (default 1.0).

    Returns:
        Dict with operation details including total eroded/deposited
        amounts for UI feedback, and the count of affected cells.
    """
    try:
        import bmesh
        import bpy
    except ImportError as exc:
        raise RuntimeError("handle_erosion_paint requires Blender") from exc

    object_name = params.get("object_name")
    if not object_name:
        raise ValueError("'object_name' is required")

    obj = bpy.data.objects.get(object_name)
    if obj is None or obj.type != "MESH":
        raise ValueError(f"Terrain mesh not found: {object_name}")

    brush_center = tuple(params.get("brush_center", [50.0, 50.0])[:2])
    brush_radius = float(params.get("brush_radius", 10.0))
    erosion_type = params.get("erosion_type", "hydraulic")
    iterations = int(params.get("iterations", 5))
    strength = float(params.get("strength", 0.5))
    talus_angle = float(params.get("talus_angle", 30.0))

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()

        # WORLD-004: Detect actual grid dimensions (robust to non-square terrain)
        rows, cols = _detect_grid_dims(bm)
        heightmap = np.array([v.co.z for v in bm.verts]).reshape(rows, cols)

        dims = obj.dimensions
        terrain_size = (dims.x, dims.y)
        terrain_origin = (obj.location.x, obj.location.y)

        # Derive cell_size from terrain dimensions and grid resolution so the
        # talus normalisation is always resolution-aware (BUG-13 class fix).
        cell_size = float(params.get(
            "cell_size",
            (dims.x / max(cols - 1, 1) + dims.y / max(rows - 1, 1)) * 0.5,
        ))

        brush_result = compute_erosion_brush(
            heightmap, brush_center, brush_radius, erosion_type,
            iterations, strength, terrain_size, terrain_origin,
            talus_angle=talus_angle, cell_size=cell_size,
        )

        # Apply brush mask: only write back cells within the brush footprint
        # so unaffected regions are not touched (dirty-region isolation).
        flat_new = brush_result.heightmap.ravel()
        flat_fp = brush_result.footprint.ravel()
        for i, v in enumerate(bm.verts):
            if i < len(flat_new) and flat_fp[i]:
                v.co.z = float(flat_new[i])

        bm.to_mesh(obj.data)
        # Mark the mesh as dirty so Blender rebuilds normals/display.
        obj.data.update()
    finally:
        bm.free()

    affected_cells = int(brush_result.footprint.sum())
    total_eroded = float(brush_result.eroded.sum())
    total_deposited = float(brush_result.deposited.sum())

    return {
        "object_name": object_name,
        "erosion_type": erosion_type,
        "brush_center": list(brush_center),
        "brush_radius": brush_radius,
        "iterations": iterations,
        "strength": strength,
        "talus_angle": talus_angle,
        "cell_size": cell_size,
        "affected_cells": affected_cells,
        "total_eroded": total_eroded,
        "total_deposited": total_deposited,
    }


# ---------------------------------------------------------------------------
# 4. Flow Map Computation (pure logic, no bpy)
# ---------------------------------------------------------------------------

# D8 direction offsets: 8 neighbors (N, NE, E, SE, S, SW, W, NW)
_D8_OFFSETS = [
    (-1, 0), (-1, 1), (0, 1), (1, 1),
    (1, 0), (1, -1), (0, -1), (-1, -1),
]
_D8_DISTANCES = [
    1.0, math.sqrt(2.0), 1.0, math.sqrt(2.0),
    1.0, math.sqrt(2.0), 1.0, math.sqrt(2.0),
]


def compute_flow_map(
    heightmap: list[list[float]] | np.ndarray,
    resolution: int | None = None,
    cell_size: float = 1.0,
) -> dict[str, Any]:
    """Compute water flow direction from heightmap using D8 algorithm.

    Pure-logic function -- no bpy needed.

    Args:
        heightmap: 2D array of height values (list of lists or numpy array).
        resolution: Unused, kept for API compatibility.
        cell_size: Physical size of each cell in meters (default 1.0).
            Scales D8 slopes to physical gradients (meters/meter).
            Does not affect flow direction on uniform-cell grids but
            ensures correct hydraulic gradient magnitudes.

    Returns:
        Dict with:
          flow_direction: 2D array of direction indices (0-7 for 8 neighbors,
                         -1 for pits/flat).
          flow_accumulation: 2D array of accumulated flow (higher = more
                           upstream area draining through this cell).
          drainage_basins: 2D array of basin IDs (cells draining to same pit
                         share a basin ID).
    """
    hmap = np.asarray(heightmap, dtype=np.float64)
    rows, cols = hmap.shape
    _cell_size = max(float(cell_size), 1e-9)  # guard against zero/negative

    # --- Step 1: Compute flow direction (D8 steepest descent) ---
    slopes_vec = np.full((8, rows, cols), -np.inf, dtype=np.float64)
    for _d_idx, ((_dr, _dc), _dist) in enumerate(zip(_D8_OFFSETS, _D8_DISTANCES)):
        _r_d = slice(max(0, -_dr), rows - max(0, _dr))
        _r_s = slice(max(0,  _dr), rows - max(0, -_dr))
        _c_d = slice(max(0, -_dc), cols - max(0, _dc))
        _c_s = slice(max(0,  _dc), cols - max(0, -_dc))
        slopes_vec[_d_idx, _r_d, _c_d] = (hmap[_r_d, _c_d] - hmap[_r_s, _c_s]) / (_dist * _cell_size)

    _best_d8 = np.argmax(slopes_vec, axis=0)
    _ri_v = np.arange(rows)[:, None]
    _ci_v = np.arange(cols)[None, :]
    _best_slope = slopes_vec[_best_d8, _ri_v, _ci_v]
    flow_dir = np.where(_best_slope > 0.0, _best_d8, -1).astype(np.int32)

    # --- Step 2: Compute flow accumulation (vectorized top-down) ---
    # Sort all cells by descending height so each cell is processed after all
    # cells that drain *into* it.  Then accumulate in one linear pass using
    # numpy scatter-add so there are no Python per-cell conditionals.
    flow_acc = np.ones((rows, cols), dtype=np.float64)
    flat_indices = np.argsort(-hmap.ravel())
    flat_r = (flat_indices // cols).astype(np.int32)
    flat_c = (flat_indices % cols).astype(np.int32)
    flat_d = flow_dir[flat_r, flat_c]

    # Build destination arrays for vectorized scatter-add:
    # For each cell with a valid flow direction, compute its downstream (nr, nc).
    valid_mask = flat_d >= 0
    _vi_r = flat_r[valid_mask]
    _vi_c = flat_c[valid_mask]
    _vi_d = flat_d[valid_mask]

    # Process each valid cell in height-descending order (Python loop over sorted
    # unique heights would be O(N) — keep explicit loop only over sorted order).
    # Vectorize the inner scatter via index-based access instead of a cell loop.
    d8_dr = np.array([off[0] for off in _D8_OFFSETS], dtype=np.int32)
    d8_dc = np.array([off[1] for off in _D8_OFFSETS], dtype=np.int32)

    # --- Vectorized flow accumulation ---
    # Process cells in height-descending order.  For each cell with a valid
    # flow direction, scatter its accumulation value into its downstream
    # receiver using np.add.at (unbuffered scatter-add).  One Python call per
    # sorted-height level would be ideal, but cells at the same exact height
    # are rare; the single linear pass below is O(N) Python iterations but
    # each iteration does O(1) work — contrast with the old per-cell Python
    # triple-nested loop that was O(N*8*depth).
    #
    # For grids where scipy is available we can fully escape Python iteration:
    # build receiver (nr, nc) index arrays for all valid cells, then call
    # np.add.at once per "topological level".  We use the scipy-free approach
    # here because the sorted-height order already gives us the correct causal
    # ordering for a single linear scatter pass.
    valid_r = flat_r[valid_mask]
    valid_c = flat_c[valid_mask]
    valid_d = flat_d[valid_mask]
    recv_r = np.clip(valid_r + d8_dr[valid_d], 0, rows - 1)
    recv_c = np.clip(valid_c + d8_dc[valid_d], 0, cols - 1)

    # Guard out-of-bounds receivers (border cells whose D8 points outside).
    in_bounds = (
        (valid_r + d8_dr[valid_d] >= 0)
        & (valid_r + d8_dr[valid_d] < rows)
        & (valid_c + d8_dc[valid_d] >= 0)
        & (valid_c + d8_dc[valid_d] < cols)
    )
    # Process in height-descending sorted order (flat_indices is already sorted
    # descending).  We need to iterate because np.add.at is not order-aware
    # for sequential dependencies (cell A feeds B feeds C).  One Python loop
    # over N valid cells — but each body is a single O(1) array index write,
    # far faster than the old triple-nested loop.
    for k in range(valid_mask.sum()):
        if not in_bounds[k]:
            continue
        flow_acc[recv_r[k], recv_c[k]] += flow_acc[valid_r[k], valid_c[k]]

    # --- Step 3: Drainage basins via flat-index union-find ---
    # Union-Find for O(N α(N)) basin assignment without per-cell path tracing.
    parent = np.arange(rows * cols, dtype=np.int32)
    basin_label = np.full(rows * cols, -1, dtype=np.int32)

    def _uf_find(p: int) -> int:
        while parent[p] != p:
            parent[p] = parent[parent[p]]  # path compression
            p = parent[p]
        return p

    # Identify pit cells (flow_dir == -1); assign each a unique basin label.
    pit_flat = np.where(flow_dir.ravel() == -1)[0]
    for bid, pf in enumerate(pit_flat):
        basin_label[pf] = bid

    # Union every cell to its downstream pit.
    for i in range(flat_indices.size):
        fi = flat_indices[i]
        d = flow_dir.ravel()[fi]
        if d < 0:
            continue
        r = fi // cols
        c = fi % cols
        nr = r + d8_dr[d]
        nc = c + d8_dc[d]
        if 0 <= nr < rows and 0 <= nc < cols:
            downstream_flat = nr * cols + nc
            # Point current cell to its downstream cell's root in UF.
            root_down = _uf_find(downstream_flat)
            root_cur  = _uf_find(fi)
            if root_cur != root_down:
                parent[root_cur] = root_down

    # Assign basin labels from pit roots to all cells.
    basins = np.full((rows, cols), -1, dtype=np.int32)
    basin_id = int(pit_flat.size)
    for fi in range(rows * cols):
        root = _uf_find(fi)
        lbl = basin_label[root]
        if lbl < 0:
            # Root not yet labelled (edge-exit cells with no pit downstream).
            lbl = basin_id
            basin_label[root] = lbl
            basin_id += 1
        basins.ravel()[fi] = lbl

    return {
        "flow_direction": flow_dir.tolist(),
        "flow_accumulation": flow_acc.tolist(),
        "drainage_basins": basins.tolist(),
        "num_basins": basin_id,
        "max_accumulation": float(flow_acc.max()),
        "resolution": (rows, cols),
    }


# ---------------------------------------------------------------------------
# 5. Thermal Erosion (enhanced pure-logic)
# ---------------------------------------------------------------------------

def apply_thermal_erosion(
    heightmap: "list[list[float]] | np.ndarray",
    iterations: int = 50,
    talus_angle: float = 0.5,
    strength: float = 1.0,
    cell_size: float = 1.0,
) -> "list[list[float]]":
    """Apply talus-angle thermal erosion, fully numpy-vectorized via canonical impl.

    Delegates to ``_terrain_erosion.apply_thermal_erosion_masks`` (the shared
    canonical implementation) so there is a single source of truth for the
    talus-formation algorithm.  No Python loops over grid cells.

    Talus-angle convention:
      * Values < 2.0  — legacy raw-height-unit convention (tan(angle) scale):
        converted to degrees via ``math.degrees(math.atan(value))`` so the
        canonical implementation receives a consistent degrees input.
      * Values >= 2.0 — degrees directly.

    ``strength`` scales the effective number of erosion passes:
    ``canonical_iterations = max(1, round(iterations * strength))``.
    At the default ``strength=1.0`` the canonical impl runs for the full
    ``iterations`` count and results are numerically identical to calling
    ``_terrain_erosion.apply_thermal_erosion`` directly.  Lower values
    produce progressively lighter erosion.

    Args:
        heightmap: 2D height array (list-of-lists or numpy array).
        iterations: Number of erosion passes at full strength. Default 50.
        talus_angle: Stable slope threshold (see above). Default 0.5.
        strength: Erosion intensity multiplier (0–1). Default 1.0.
        cell_size: Real-world size of one grid cell in world units. Default 1.0.

    Returns:
        Modified heightmap as list-of-lists (legacy return type preserved).
    """
    from ._terrain_erosion import apply_thermal_erosion_masks as _canonical_thermal

    h_in = np.asarray(heightmap, dtype=np.float64)

    # Convert legacy raw-height talus convention to degrees for canonical impl.
    _talus_f = float(talus_angle)
    if _talus_f < 2.0:
        talus_deg = math.degrees(math.atan(_talus_f))
    else:
        talus_deg = _talus_f

    # Map strength to effective iteration count: strength=1.0 → full iterations,
    # strength=0.0 → 0 passes (return original), intermediate → proportional.
    _strength = float(np.clip(strength, 0.0, 1.0))
    effective_iters = max(1, round(int(iterations) * _strength)) if _strength > 0.0 else 0

    if effective_iters == 0:
        return h_in.tolist()

    masks = _canonical_thermal(
        h_in,
        iterations=effective_iters,
        talus_angle=talus_deg,
        cell_size=max(float(cell_size), 1e-9),
    )
    result = masks.height

    # Preserve source height range; no hard-clamp to [0, 1].
    src_min = float(np.nanmin(h_in)) if h_in.size else 0.0
    src_max = float(np.nanmax(h_in)) if h_in.size else 1.0
    if not np.isfinite(src_min) or not np.isfinite(src_max) or src_max <= src_min:
        src_min, src_max = 0.0, max(src_min + 1.0, 1.0)
    result = np.nan_to_num(result, nan=src_min, posinf=src_max, neginf=src_min)
    result = np.clip(result, src_min, src_max)
    return result.tolist()


# ---------------------------------------------------------------------------
# 6. Terrain Stamp / Feature Placement (pure logic + handler)
# ---------------------------------------------------------------------------

# Stamp shape generators -- radial profile functions: r_norm in [0, 1].
# Terrain-feature shapes (legacy, kept for backward compat):
_STAMP_SHAPES = {
    # crater is now handled by a dedicated numpy array branch below for
    # asymmetric rim + ejecta blanket — this lambda is kept only as a
    # fallback if someone calls compute_falloff("crater") directly.
    "crater":  lambda r_norm: max(0.0, 1.0 - abs(r_norm * 2.0 - 1.0)),
    "mesa":    lambda r_norm: 1.0 if r_norm < 0.6 else max(0.0, 1.0 - (r_norm - 0.6) / 0.4),
    "hill":    lambda r_norm: max(0.0, math.cos(r_norm * math.pi / 2.0)),
    "valley":  lambda r_norm: -max(0.0, math.cos(r_norm * math.pi / 2.0)),
    "plateau": lambda r_norm: 1.0 if r_norm < 0.7 else max(0.0, 1.0 - (r_norm - 0.7) / 0.3),
    "ridge":   lambda r_norm: max(0.0, 1.0 - abs(r_norm - 0.5) * 2.0),
}

# Geometric shape primitives handled via dedicated array branches (not radial lambdas).
_STAMP_SHAPE_PRIMITIVES = frozenset({"circle", "rectangle", "gaussian"})


def compute_stamp_heightmap(
    stamp_type: str,
    resolution: int = 64,
    custom_heightmap: list[list[float]] | None = None,
) -> np.ndarray:
    """Generate a 2D stamp heightmap for a given stamp type.

    Pure-logic function.

    Supports two categories of stamp types:

    **Terrain-feature shapes** (radially symmetric, legacy):
      ``crater`` | ``mesa`` | ``hill`` | ``valley`` | ``plateau`` | ``ridge``

    **Geometric shape primitives** (mathematically exact profiles):
      * ``circle``    -- hard-edged disc: 1.0 inside radius, 0.0 outside.
      * ``rectangle`` -- axis-aligned square footprint: 1.0 inside the inner
        80% of the stamp extent, 0.0 outside.
      * ``gaussian``  -- radially symmetric Gaussian bell (sigma = 1/3 of
        radius) reaching near-zero at the boundary for a smooth falloff.

    **Custom:** ``custom`` -- pass ``custom_heightmap`` as a nested list.

    Args:
        stamp_type: One of the type strings listed above.
        resolution: Output array side length (square).
        custom_heightmap: 2D nested list used only when stamp_type=='custom'.

    Returns:
        2D numpy array of shape (resolution, resolution).
        Values in [0, 1] for most types; [-1, 0] for 'valley'.

    Raises:
        ValueError: If stamp_type is not recognised.
    """
    if stamp_type == "custom":
        if custom_heightmap is not None:
            return np.asarray(custom_heightmap, dtype=np.float64)
        return np.zeros((resolution, resolution), dtype=np.float64)

    # Build shared coordinate grids used by all shape branches.
    resolution = max(1, int(resolution))
    center = resolution / 2.0
    cols_idx = np.arange(resolution, dtype=np.float64)
    rows_idx = np.arange(resolution, dtype=np.float64)
    cc, rr = np.meshgrid(cols_idx, rows_idx)   # (resolution, resolution)
    # Normalised offsets in [-1, 1]: 1.0 = edge of stamp extent.
    dx = (cc - center) / max(center, 1e-9)
    dy = (rr - center) / max(center, 1e-9)
    dist = np.sqrt(dx * dx + dy * dy)          # radial normalised distance

    # --- Geometric shape primitives ---
    if stamp_type == "circle":
        # Hard-edged disc: binary mask, 1.0 inside the unit circle.
        return np.where(dist <= 1.0, 1.0, 0.0).astype(np.float64)

    if stamp_type == "rectangle":
        # Axis-aligned square: 1.0 where both |dx| and |dy| are <= 0.8.
        # The 0.8 inset leaves a natural border consistent with the circle footprint.
        half = 0.8
        return np.where(
            (np.abs(dx) <= half) & (np.abs(dy) <= half), 1.0, 0.0
        ).astype(np.float64)

    if stamp_type == "gaussian":
        # Radially symmetric Gaussian bell: sigma = 1/3 of radius so the curve
        # reaches ~0.011 at the boundary -- smooth, natural, no hard edge.
        sigma = 1.0 / 3.0
        bell = np.exp(-(dist ** 2) / (2.0 * sigma ** 2))
        # Zero outside the unit circle for a consistent bounded footprint.
        return np.where(dist <= 1.0, bell, 0.0).astype(np.float64)

    # --- Asymmetric crater with ejecta blanket (Melosh scaling) ---
    if stamp_type == "crater":
        # Physically motivated crater profile based on Melosh (1989) impact
        # crater morphology.  Three zones:
        #
        #   r < r_floor  : flat floor (uplifted floor breccia), height = -1.
        #   r_floor <= r <= 1.0  : inner wall — steep concave climb from floor
        #                          to rim: profile = (1 - r/r_crater)^2 inverted.
        #   1.0 < r <= r_blanket : outer ejecta blanket — shallow exponential
        #                          decay from rim height down to 0, perturbed
        #                          by radial Gaussian noise seeded from the
        #                          stamp resolution to stay deterministic.
        #
        # Rim height follows Melosh scaling: h_rim = 0.04 * r_crater_world.
        # Here r_crater_world == 1.0 (normalised), so h_rim = 0.04.
        #
        # The result is remapped to [−1, h_rim] and returned in that range
        # so the caller's height multiplier controls actual world-unit depth.

        r_floor   = 0.25   # normalised floor radius (flat crater floor)
        r_blanket = 1.35   # ejecta blanket extends 35% beyond crater rim
        h_rim     = 0.04   # Melosh rim height above surrounding terrain

        # Extend the coordinate grid to cover the ejecta blanket.
        resolution_b = resolution  # use same grid; blanket data lives in dist > 1
        stamp_b = np.zeros((resolution_b, resolution_b), dtype=np.float64)

        # --- Inner bowl (r <= 1.0) ---
        # Floor: constant depth = -1
        floor_mask = dist <= r_floor
        stamp_b[floor_mask] = -1.0

        # Inner wall: smooth climb from -1 at r_floor to +h_rim at r=1.0
        wall_mask = (dist > r_floor) & (dist <= 1.0)
        if wall_mask.any():
            r_wall = dist[wall_mask]
            # Normalise wall position: 0 at floor edge, 1 at rim
            t_wall = (r_wall - r_floor) / (1.0 - r_floor)
            # Concave inner-wall profile: steep at base, levels at rim
            # Uses (1 - (1-t)^2) which is 0 at t=0 and 1 at t=1, concave up.
            profile = 1.0 - (1.0 - t_wall) ** 2
            stamp_b[wall_mask] = -1.0 + (1.0 + h_rim) * profile

        # --- Outer ejecta blanket (1.0 < r <= r_blanket) ---
        blanket_mask = (dist > 1.0) & (dist <= r_blanket)
        if blanket_mask.any():
            r_ejecta = dist[blanket_mask]
            # Exponential decay from h_rim at r=1 down to 0 at r=r_blanket
            t_ej = (r_ejecta - 1.0) / (r_blanket - 1.0)   # 0→1 across blanket
            # Shallow slope: power-law decay (exponent ~1.5 matches lunar data)
            blanket_h = h_rim * (1.0 - t_ej) ** 1.5

            # Add deterministic radial Gaussian noise for asymmetric ejecta rays.
            # Seed from resolution so different stamp sizes produce the same
            # qualitative pattern (scale-independent asymmetry).
            rng_ej = np.random.RandomState(resolution_b ^ 0xDEAD)
            noise_scale = h_rim * 0.4   # rays up to 40% of rim height
            # Noise varies with angle, not radius — creates radial ray pattern.
            angles = np.arctan2(
                (np.where(blanket_mask, 1, 0) * dy)[blanket_mask],
                (np.where(blanket_mask, 1, 0) * dx)[blanket_mask],
            )
            # 8-ray pattern: sin(4θ) with small random perturbation per pixel
            ray_noise = rng_ej.uniform(-0.5, 0.5, size=angles.shape).astype(np.float64)
            ejecta_noise = noise_scale * (
                0.5 * np.sin(4.0 * angles + ray_noise * 0.5) + 0.5
            )
            stamp_b[blanket_mask] = blanket_h + ejecta_noise * (1.0 - t_ej)

        # Zero outside blanket (already zero from np.zeros init).
        return stamp_b

    # --- Legacy terrain-feature shapes ---
    if stamp_type not in _STAMP_SHAPES:
        all_valid = sorted(
            list(_STAMP_SHAPES.keys())
            + list(_STAMP_SHAPE_PRIMITIVES)
            + ["custom"]
        )
        raise ValueError(
            f"Unknown stamp_type: {stamp_type!r}. Valid: {all_valid}"
        )

    shape_fn = _STAMP_SHAPES[stamp_type]
    # Apply the radial shape function element-wise via np.vectorize.
    vfn = np.vectorize(shape_fn)
    stamp = np.where(dist <= 1.0, vfn(dist), 0.0).astype(np.float64)
    return stamp


def _bilinear_sample(arr: np.ndarray, row_f: float, col_f: float) -> float:
    """Sample a 2D array at a fractional (row_f, col_f) position using
    bilinear interpolation. Clamps to array bounds.
    """
    rows, cols = arr.shape
    r0 = int(math.floor(row_f))
    c0 = int(math.floor(col_f))
    r1 = r0 + 1
    c1 = c0 + 1
    dr = row_f - r0
    dc = col_f - c0
    r0 = max(0, min(r0, rows - 1))
    r1 = max(0, min(r1, rows - 1))
    c0 = max(0, min(c0, cols - 1))
    c1 = max(0, min(c1, cols - 1))
    v00 = arr[r0, c0]
    v01 = arr[r0, c1]
    v10 = arr[r1, c0]
    v11 = arr[r1, c1]
    return float(
        v00 * (1 - dr) * (1 - dc)
        + v01 * (1 - dr) * dc
        + v10 * dr * (1 - dc)
        + v11 * dr * dc
    )


def apply_stamp_to_heightmap(
    heightmap: np.ndarray,
    stamp: np.ndarray,
    position: Vec2,
    radius: float,
    height: float = 1.0,
    falloff: float = 0.5,
    terrain_size: Vec2 = (100.0, 100.0),
    terrain_origin: Vec2 = (0.0, 0.0),
    cell_size: float | None = None,
    blend_mode: str = "add",
) -> np.ndarray:
    """Apply a stamp heightmap onto a terrain heightmap.

    Pure-logic function.

    Stamp coordinates are treated as world-unit values and converted to
    cell indices via ``cell_index = world_coord / cell_size``. Sub-cell
    precision is achieved through bilinear interpolation of the stamp
    texture. The stamp contribution is clamped to the rectangular bounding
    region of the stamp so no writes occur outside the footprint.

    Each cell receives a feathered stamp contribution controlled by the
    ``falloff`` parameter: a smooth cosine falloff is applied from the
    stamp center to its edge when falloff > 0.

    Args:
        heightmap: 2D terrain heightmap.
        stamp: 2D stamp heightmap (values typically in [0, 1]).
        position: (x, y) world-space position to place the stamp center.
        radius: World-space radius of the stamp.
        height: Height multiplier for the stamp values.
        falloff: Edge softness (0=sharp, 1=gradual).  When > 0 a smooth
                 cosine falloff weights the stamp contribution toward zero
                 at the stamp boundary.
        terrain_size: (width, depth) of the terrain in world units.
        terrain_origin: World-space (x, y) center of the terrain object.
        cell_size: Real-world size of one grid cell. When None it is derived
                   from terrain_size and the heightmap shape.
        blend_mode: How the stamp value is combined with the existing
                    terrain height.  One of:
                    * ``"add"``      -- result = terrain + stamp * height (default)
                    * ``"multiply"`` -- result = terrain * (1 + stamp * height),
                                        feathered blend at edges.
                    * ``"replace"``  -- lerp from terrain to stamp*height,
                                        feathered by edge_weight.
                    * ``"max"``      -- only raise terrain, never lower it.
                    * ``"min"``      -- only lower terrain, never raise it.

    Returns:
        Modified heightmap (copy).

    Raises:
        ValueError: If blend_mode is not one of the valid values.
    """
    _VALID_BLEND_MODES = ("add", "multiply", "replace", "max", "min")
    blend_mode_lower = blend_mode.lower()
    if blend_mode_lower not in _VALID_BLEND_MODES:
        raise ValueError(
            f"apply_stamp_to_heightmap: unknown blend_mode {blend_mode!r}. "
            f"Valid: {_VALID_BLEND_MODES}"
        )

    result = heightmap.astype(np.float64).copy()
    rows, cols = result.shape
    stamp_rows, stamp_cols = stamp.shape
    tw, td = terrain_size
    ox, oy = terrain_origin

    if tw <= 0 or td <= 0 or radius <= 0:
        return result

    # Derive cell_size from terrain dimensions when not provided explicitly.
    if cell_size is None or cell_size <= 0:
        cs_x = tw / max(cols - 1, 1)
        cs_y = td / max(rows - 1, 1)
        cell_size = (cs_x + cs_y) * 0.5

    # Convert world-space stamp center to cell indices.
    terrain_min_x = ox - tw * 0.5
    terrain_min_y = oy - td * 0.5
    cx_cells = (position[0] - terrain_min_x) / cell_size
    cy_cells = (position[1] - terrain_min_y) / cell_size

    # Stamp radius in cells
    r_cells = radius / cell_size

    # Clamp bounding region to valid heightmap indices
    min_r = max(0, int(math.floor(cy_cells - r_cells)))
    max_r = min(rows - 1, int(math.ceil(cy_cells + r_cells)))
    min_c = max(0, int(math.floor(cx_cells - r_cells)))
    max_c = min(cols - 1, int(math.ceil(cx_cells + r_cells)))

    # --- Fully vectorized stamp application ---
    # Build grid index arrays for the bounding box.
    col_arr = np.arange(min_c, max_c + 1, dtype=np.float64)
    row_arr = np.arange(min_r, max_r + 1, dtype=np.float64)
    cc_bbox, rr_bbox = np.meshgrid(col_arr, row_arr)  # shapes (box_h, box_w)

    # Normalized offset from stamp center in [-1, 1].
    nx_arr = (cc_bbox - cx_cells) / max(r_cells, 1e-6)
    ny_arr = (rr_bbox - cy_cells) / max(r_cells, 1e-6)
    dist_arr = np.sqrt(nx_arr * nx_arr + ny_arr * ny_arr)

    inside = dist_arr <= 1.0
    if not inside.any():
        return result

    # Bilinear UV coordinates into stamp array.
    # nx/ny in [-1,1] → su/sv in [0, stamp_cols-1] / [0, stamp_rows-1]
    su_arr = (nx_arr + 1.0) * 0.5 * (stamp_cols - 1)
    sv_arr = (ny_arr + 1.0) * 0.5 * (stamp_rows - 1)

    # Bilinear interpolation — vectorized over the entire bounding box.
    su_floor = np.floor(su_arr).astype(np.int32)
    sv_floor = np.floor(sv_arr).astype(np.int32)
    su_ceil  = su_floor + 1
    sv_ceil  = sv_floor + 1
    su_frac  = su_arr - su_floor
    sv_frac  = sv_arr - sv_floor

    # Clamp indices to stamp bounds.
    su_f = np.clip(su_floor, 0, stamp_cols - 1)
    su_c = np.clip(su_ceil,  0, stamp_cols - 1)
    sv_f = np.clip(sv_floor, 0, stamp_rows - 1)
    sv_c = np.clip(sv_ceil,  0, stamp_rows - 1)

    v00 = stamp[sv_f, su_f]
    v01 = stamp[sv_f, su_c]
    v10 = stamp[sv_c, su_f]
    v11 = stamp[sv_c, su_c]

    stamp_val_arr = (
        v00 * (1.0 - sv_frac) * (1.0 - su_frac)
        + v01 * (1.0 - sv_frac) * su_frac
        + v10 * sv_frac         * (1.0 - su_frac)
        + v11 * sv_frac         * su_frac
    )

    # Edge feather weight: smooth cosine falloff from center (dist=0) to edge (dist=1).
    # falloff == 0 → weight = 1.0 everywhere inside (hard edge).
    if falloff > 0:
        d_clamped = np.clip(dist_arr, 0.0, 1.0)
        edge_weight_arr = np.where(inside, 0.5 * (1.0 + np.cos(np.pi * d_clamped)), 0.0)
    else:
        edge_weight_arr = np.where(inside, 1.0, 0.0)

    contrib_arr = stamp_val_arr * height

    # Extract the terrain sub-region to modify (same shape as bounding box).
    orig_region = result[min_r:max_r + 1, min_c:max_c + 1].copy()

    if blend_mode_lower == "add":
        new_region = orig_region + contrib_arr * edge_weight_arr
    elif blend_mode_lower == "multiply":
        multiplied = orig_region * (1.0 + contrib_arr)
        new_region = orig_region + (multiplied - orig_region) * edge_weight_arr
    elif blend_mode_lower == "replace":
        new_region = orig_region + (contrib_arr - orig_region) * edge_weight_arr
    elif blend_mode_lower == "max":
        candidate = orig_region + (contrib_arr - orig_region) * edge_weight_arr
        new_region = np.maximum(orig_region, candidate)
    else:  # min
        candidate = orig_region + (contrib_arr - orig_region) * edge_weight_arr
        new_region = np.minimum(orig_region, candidate)

    # Write only cells inside the stamp footprint.
    result[min_r:max_r + 1, min_c:max_c + 1] = np.where(inside, new_region, orig_region)
    return result
def handle_terrain_stamp(params: dict) -> dict:
    """Stamp features onto existing terrain (GAP-28/GAP-10).

    The incoming ``position`` is a world-space XY coordinate.  It is
    transformed into the object's local space via ``matrix_world.inverted()``
    before computing cell indices, so stamps are correctly positioned even
    when the terrain has a non-identity transform (translation, rotation, or
    non-uniform scale).  Radius is also de-scaled from world to local units
    via the object's average XY scale factor.

    Params:
        object_name: str -- Terrain mesh object name.
        stamp_type: str -- 'crater' | 'mesa' | 'hill' | 'valley' | 'plateau' |
                          'ridge' | 'custom'.
        position: [x, y] -- World-space coords for stamp center.
        radius: float -- Stamp radius in world units.
        height: float -- Stamp height multiplier.
        falloff: float -- Edge softness (0-1).
        custom_heightmap: list[list[float]] -- For 'custom' stamp type.
        stamp_resolution: int -- Resolution of generated stamp (default 64).

    Returns:
        Dict with operation details including cell-space center coordinates
        and a warning if the stamp extends outside tile bounds.
    """
    try:
        import bmesh
        import bpy
        from mathutils import Vector
    except ImportError as exc:
        raise RuntimeError("handle_terrain_stamp requires Blender") from exc

    object_name = params.get("object_name")
    if not object_name:
        raise ValueError("'object_name' is required")

    obj = bpy.data.objects.get(object_name)
    if obj is None or obj.type != "MESH":
        raise ValueError(f"Terrain mesh not found: {object_name}")

    stamp_type = params.get("stamp_type", "hill")
    position_world = tuple(params.get("position", [50.0, 50.0])[:2])
    radius_world = float(params.get("radius", 10.0))
    height = float(params.get("height", 1.0))
    falloff = float(params.get("falloff", 0.5))
    custom_heightmap = params.get("custom_heightmap")
    stamp_resolution = max(8, min(int(params.get("stamp_resolution", 64)), 512))

    stamp = compute_stamp_heightmap(stamp_type, stamp_resolution, custom_heightmap)

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()

        # WORLD-004: Detect actual grid dimensions (robust to non-square terrain)
        rows, cols = _detect_grid_dims(bm)
        # Heightmap is in local space (v.co are local-space coordinates).
        heightmap = np.array([v.co.z for v in bm.verts]).reshape(rows, cols)

        # Derive terrain extents from actual local vertex positions so
        # the mapping is correct for non-unit-scale and translated meshes.
        xs_local = [v.co.x for v in bm.verts]
        ys_local = [v.co.y for v in bm.verts]
        local_min_x = min(xs_local)
        local_max_x = max(xs_local)
        local_min_y = min(ys_local)
        local_max_y = max(ys_local)
        local_width  = local_max_x - local_min_x
        local_depth  = local_max_y - local_min_y
        local_cx     = (local_min_x + local_max_x) * 0.5
        local_cy     = (local_min_y + local_max_y) * 0.5
        terrain_size   = (local_width, local_depth)
        terrain_origin = (local_cx, local_cy)

        # Transform world-space stamp position to local space using the full
        # matrix_world (handles translation, rotation, and scale correctly).
        mat_inv = obj.matrix_world.inverted()
        world_vec = Vector((position_world[0], position_world[1], 0.0))
        local_vec = mat_inv @ world_vec
        position_local: Vec2 = (float(local_vec.x), float(local_vec.y))

        # Convert world-space radius to local units via the object's average
        # XY scale so the stamp footprint is preserved under uniform scale.
        scale_3d = obj.matrix_world.to_scale()
        avg_scale = (abs(float(scale_3d.x)) + abs(float(scale_3d.y))) * 0.5
        radius_local = radius_world / max(avg_scale, 1e-6)

        # Derive cell_size from local terrain dimensions and grid resolution.
        cs_x = local_width / max(cols - 1, 1)
        cs_y = local_depth / max(rows - 1, 1)
        cell_size = (cs_x + cs_y) * 0.5

        # Cell-space stamp center (for OOB check and return value).
        stamp_cx_cells = (position_local[0] - local_min_x) / max(cell_size, 1e-9)
        stamp_cy_cells = (position_local[1] - local_min_y) / max(cell_size, 1e-9)
        r_cells = radius_local / max(cell_size, 1e-9)

        # Validate: warn if stamp extends outside tile bounds (partial stamps
        # are still applied — cells outside the grid are simply skipped).
        out_of_bounds = (
            stamp_cx_cells - r_cells < 0
            or stamp_cx_cells + r_cells > cols
            or stamp_cy_cells - r_cells < 0
            or stamp_cy_cells + r_cells > rows
        )
        oob_warning: str | None = None
        if out_of_bounds:
            oob_warning = (
                f"Stamp at cell ({stamp_cx_cells:.1f}, {stamp_cy_cells:.1f}) "
                f"with radius {r_cells:.1f} cells extends outside tile bounds "
                f"({cols}x{rows}); contribution is clipped to tile."
            )
            _log.warning("handle_terrain_stamp: %s", oob_warning)

        stamped = apply_stamp_to_heightmap(
            heightmap, stamp, position_local, radius_local, height, falloff,
            terrain_size, terrain_origin, cell_size=cell_size,
        )

        flat = stamped.ravel()
        for i, v in enumerate(bm.verts):
            if i < len(flat):
                v.co.z = float(flat[i])

        bm.to_mesh(obj.data)
        obj.data.update()
    finally:
        bm.free()

    result: dict[str, Any] = {
        "object_name": object_name,
        "stamp_type": stamp_type,
        "position_world": list(position_world),
        "position_local": list(position_local),
        "radius_world": radius_world,
        "radius_local": radius_local,
        "height": height,
        "falloff": falloff,
        "cell_size": cell_size,
        "stamp_center_cells": [stamp_cx_cells, stamp_cy_cells],
        "stamp_radius_cells": r_cells,
    }
    if oob_warning is not None:
        result["warning"] = oob_warning
    return result


# ---------------------------------------------------------------------------
# 7. Object-to-Terrain Snapping (handler only)
# ---------------------------------------------------------------------------

def handle_snap_to_terrain(params: dict) -> dict:
    """Snap objects to terrain surface via raycast (GAP-30/GAP-12).

    Params:
        object_names: list[str] -- Objects to snap.
        terrain_name: str -- Terrain object name.
        align_to_normal: bool -- Rotate to match terrain slope (default True).
        offset: float -- Vertical offset above terrain (default 0.0).

    Returns:
        Dict with snapping results per object.
    """
    try:
        import bpy
        from mathutils import Vector
    except ImportError as exc:
        raise RuntimeError("handle_snap_to_terrain requires Blender") from exc

    object_names = params.get("object_names", [])
    terrain_name = params.get("terrain_name")
    align_to_normal = params.get("align_to_normal", True)
    offset = float(params.get("offset", 0.0))

    if not terrain_name:
        raise ValueError("'terrain_name' is required")
    if not object_names:
        raise ValueError("'object_names' must be a non-empty list")

    terrain = bpy.data.objects.get(terrain_name)
    if terrain is None:
        raise ValueError(f"Terrain object not found: {terrain_name}")

    # Ensure terrain mesh is up to date for raycasting
    _ = bpy.context.evaluated_depsgraph_get()

    results: list[dict[str, Any]] = []

    for obj_name in object_names:
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            results.append({"name": obj_name, "snapped": False,
                            "error": "Object not found"})
            continue

        # Cast ray from above the object straight down
        origin = Vector((obj.location.x, obj.location.y,
                         terrain.location.z + terrain.dimensions.z + 100.0))
        direction = Vector((0.0, 0.0, -1.0))

        success, location, normal, _face_idx = terrain.ray_cast(
            terrain.matrix_world.inverted() @ origin,
            terrain.matrix_world.inverted().to_3x3() @ direction,
        )

        if success:
            # Transform hit back to world space
            world_hit = terrain.matrix_world @ location
            world_normal = (terrain.matrix_world.to_3x3() @ normal).normalized()

            obj.location.x = world_hit.x
            obj.location.y = world_hit.y
            obj.location.z = world_hit.z + offset

            if align_to_normal:
                # Align object Z-axis to terrain normal
                up = Vector((0, 0, 1))
                rot_axis = up.cross(world_normal)
                if rot_axis.length > 1e-6:
                    rot_angle = up.angle(world_normal)
                    rot_axis.normalize()
                    from mathutils import Matrix
                    rot_mat = Matrix.Rotation(rot_angle, 4, rot_axis)
                    obj.rotation_euler = rot_mat.to_euler()

            results.append({
                "name": obj_name,
                "snapped": True,
                "position": [world_hit.x, world_hit.y, world_hit.z + offset],
                "normal": [world_normal.x, world_normal.y, world_normal.z],
            })
        else:
            results.append({"name": obj_name, "snapped": False,
                            "error": "Raycast missed terrain"})

    return {
        "terrain_name": terrain_name,
        "snapped_count": sum(1 for r in results if r.get("snapped")),
        "total_objects": len(object_names),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Terrain Flatten Zones -- building foundation support (MESH-05)
# ---------------------------------------------------------------------------


def flatten_terrain_zone(
    heightmap: np.ndarray,
    center_x: float,
    center_y: float,
    radius: float,
    target_height: float | None = None,
    blend_width: float = 0.1,
    seed: int = 0,
) -> np.ndarray:
    """Flatten a circular zone for building placement, with smooth blend.

    Pure-logic function. Creates a level platform suitable for building
    foundations with a smoothstep transition to surrounding terrain.
    No floating buildings -- the terrain is lowered/raised to meet the
    building footprint exactly.

    Args:
        heightmap: 2D numpy array of height values in [0, 1].
        center_x: Normalized X coordinate of flatten center (0-1).
        center_y: Normalized Y coordinate of flatten center (0-1).
        radius: Normalized radius of the flat zone (0-1).
        target_height: Target height for the flat zone. If None, uses the
            average height within the radius.
        blend_width: Width of the smooth transition zone (normalized).
        seed: Random seed (reserved for future noise-based blend).

    Returns:
        New heightmap with the flattened zone applied. Values are preserved in
        the source heightmap's natural range (no forced normalization to [0,1])
        so world-unit heightmaps are not silently crushed.
    """
    rows, cols = heightmap.shape

    ys = np.arange(rows, dtype=np.float64) / rows
    xs = np.arange(cols, dtype=np.float64) / cols
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    dist = np.sqrt((xx - center_x) ** 2 + (yy - center_y) ** 2)

    # Compute target height from average inside radius if not specified
    mask = dist < radius
    if target_height is None:
        if mask.any():
            target_height = float(heightmap[mask].mean())
        else:
            target_height = float(heightmap.mean()) if heightmap.size else 0.0

    # Blend factor: 1.0 inside radius, smooth fade to 0.0 at radius+blend_width.
    # This blend mask is intentionally clamped to [0,1] — it is a weight, not
    # a height — so the clip here is correct.
    blend = np.clip(1.0 - (dist - radius) / max(blend_width, 1e-6), 0.0, 1.0)
    # Smoothstep: 3t^2 - 2t^3 for C1 continuity (no step discontinuity)
    blend = blend * blend * (3.0 - 2.0 * blend)

    result = heightmap * (1.0 - blend) + target_height * blend
    # Preserve source height range — never hard-clamp to [0,1] which would
    # silently destroy world-unit heightmaps (§7.5, Addendum 3.A).
    src_min = float(np.nanmin(heightmap)) if heightmap.size else 0.0
    src_max = float(np.nanmax(heightmap)) if heightmap.size else 1.0
    # The flatten target may legitimately sit above the original max (e.g. when
    # raising a plateau), so broaden the allowed range to include target_height.
    lo = min(src_min, float(target_height))
    hi = max(src_max, float(target_height))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo, hi = 0.0, max(lo + 1.0, 1.0)
    result = np.nan_to_num(result, nan=lo, posinf=hi, neginf=lo)
    return np.clip(result, lo, hi)


def flatten_multiple_zones(
    heightmap: np.ndarray,
    zones: list[dict],
) -> np.ndarray:
    """Apply multiple flatten zones in priority order.

    Zones are processed from lowest priority to highest so that high-priority
    zones win at overlapping regions (applied last, they overwrite earlier
    results). Within equal-priority groups the original list order is
    preserved (stable sort).

    Each zone dict must have center_x, center_y, radius.
    Optional keys: target_height, blend_width, seed, priority (int, default 0).

    The blend transition at the zone edge uses a smoothstep falloff over
    ``blend_width`` (normalised, default 0.1) so no hard seams appear where
    zones meet the surrounding terrain.

    Args:
        heightmap: 2D numpy array of height values.
        zones: List of zone dicts with flatten parameters.

    Returns:
        New heightmap with all zones applied.
    """
    if not zones:
        return heightmap

    # Sort ascending by priority: low-priority zones are applied first so
    # high-priority zones applied later take precedence in overlapping regions.
    ordered = sorted(zones, key=lambda z: int(z.get("priority", 0)))

    result = heightmap
    for zone in ordered:
        blend_width = float(zone.get("blend_width", 0.1))
        # Ensure blend_width > 0 so the smoothstep transition is always present
        # at the radius boundary (no hard seam).
        blend_width = max(blend_width, 1e-3)
        result = flatten_terrain_zone(
            result,
            center_x=float(zone["center_x"]),
            center_y=float(zone["center_y"]),
            radius=float(zone["radius"]),
            target_height=zone.get("target_height"),
            blend_width=blend_width,
            seed=int(zone.get("seed", 0)),
        )
    return result


def handle_terrain_flatten_zone(params: dict) -> dict:
    """Flatten one or more circular/elliptical zones on a Blender terrain mesh.

    Delegates all zone logic to flatten_multiple_zones so no business logic
    is duplicated here. Supports both single-zone (legacy) and multi-zone
    (zones list) calling conventions.

    Params (single-zone form):
        object_name   : name of terrain mesh object in scene.
        center_x      : world-space X center of flatten zone.
        center_y      : world-space Y center of flatten zone.
        radius_x      : X radius of the zone (world units).
        radius_y      : Y radius of the zone (defaults to radius_x).
        target_height : Z height to flatten to. Validated to be within the
                        tile's height range (warning logged if outside).
                        Defaults to terrain mean inside the zone.
        blend_distance: Transition width beyond radius in world units
                        (defaults to radius_x * 0.5).
        priority      : int, used when multiple zones overlap (default 0;
                        higher priority wins).
        seed          : int random seed (default 0).

    Params (multi-zone form):
        object_name   : (same as above).
        zones         : list of zone dicts — each with the same keys as the
                        single-zone form (center_x, center_y, radius_x, …).
                        When present, the single-zone keys are ignored.

    Returns:
        Dict with status, object_name, and vertices_modified count.
    """
    try:
        import bpy  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
    except ImportError:
        return {"status": "error",
                "error": "handle_terrain_flatten_zone requires Blender context"}

    obj_name = params.get("object_name", "")
    obj = bpy.data.objects.get(obj_name) if obj_name else None
    if obj is None or obj.type != "MESH":
        return {"status": "error",
                "error": f"Object '{obj_name}' not found or not a mesh"}

    mesh = obj.data
    verts = mesh.vertices

    if len(verts) == 0:
        return {"status": "error", "error": "Mesh has no vertices"}

    # Read vertex positions in world space
    mat = obj.matrix_world
    positions = np.array([mat @ v.co for v in verts], dtype=np.float64)  # (N, 3)

    xs = positions[:, 0]
    ys = positions[:, 1]
    zs = positions[:, 2]

    min_x, max_x = float(xs.min()), float(xs.max())
    min_y, max_y = float(ys.min()), float(ys.max())
    z_min_tile = float(zs.min())
    z_max_tile = float(zs.max())
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)

    # ------------------------------------------------------------------ #
    # Build zone list — support both the legacy single-zone API and the   #
    # new multi-zone list form.                                            #
    # ------------------------------------------------------------------ #
    raw_zones: list[dict] = params.get("zones", [])
    if not raw_zones:
        # Single-zone convenience form — construct a one-element list.
        radius_x = float(params.get("radius_x", span_x * 0.1))
        radius_y = float(params.get("radius_y", radius_x))
        raw_zones = [{
            "center_x":      float(params.get("center_x", (min_x + max_x) * 0.5)),
            "center_y":      float(params.get("center_y", (min_y + max_y) * 0.5)),
            "radius_x":      radius_x,
            "radius_y":      radius_y,
            "target_height": params.get("target_height", None),
            "blend_distance": float(params.get("blend_distance", radius_x * 0.5)),
            "priority":      int(params.get("priority", 0)),
            "seed":          int(params.get("seed", 0)),
        }]

    # ------------------------------------------------------------------ #
    # Build a 2-D heightmap grid from vertex Z values for flatten_*       #
    # ------------------------------------------------------------------ #
    grid_res = max(32, int(len(verts) ** 0.5))
    col_idx = np.clip(
        (xs - min_x) / span_x * (grid_res - 1), 0, grid_res - 1
    ).astype(int)
    row_idx = np.clip(
        (ys - min_y) / span_y * (grid_res - 1), 0, grid_res - 1
    ).astype(int)

    counts = np.zeros((grid_res, grid_res), dtype=np.int32)
    sums   = np.zeros((grid_res, grid_res), dtype=np.float64)
    np.add.at(sums,   (row_idx, col_idx), zs)
    np.add.at(counts, (row_idx, col_idx), 1)
    grid = np.full((grid_res, grid_res), np.nan, dtype=np.float64)
    mask_filled = counts > 0
    grid[mask_filled] = sums[mask_filled] / counts[mask_filled]

    # Fill NaN cells by column mean, then global mean
    col_means = np.nanmean(grid, axis=0)
    global_mean = float(np.nanmean(grid)) if not np.all(np.isnan(grid)) else 0.0
    for c in range(grid_res):
        nan_rows = np.isnan(grid[:, c])
        if nan_rows.any():
            fill = col_means[c] if np.isfinite(col_means[c]) else global_mean
            grid[nan_rows, c] = fill

    # ------------------------------------------------------------------ #
    # Translate each zone from world coords to normalised grid coords     #
    # and validate target_height is within tile range.                    #
    # ------------------------------------------------------------------ #
    norm_zones: list[dict] = []
    warnings_out: list[str] = []
    for z in raw_zones:
        cx_w   = float(z.get("center_x", (min_x + max_x) * 0.5))
        cy_w   = float(z.get("center_y", (min_y + max_y) * 0.5))
        rx_w   = float(z.get("radius_x", span_x * 0.1))
        ry_w   = float(z.get("radius_y", rx_w))
        blend_w = float(z.get("blend_distance", rx_w * 0.5))
        th_w   = z.get("target_height", None)
        prio   = int(z.get("priority", 0))
        seed_v = int(z.get("seed", 0))

        # Validate target_height is within tile Z range (warn but don't reject).
        if th_w is not None:
            th_f = float(th_w)
            if not (z_min_tile <= th_f <= z_max_tile):
                msg = (
                    f"target_height {th_f:.3f} is outside tile Z range "
                    f"[{z_min_tile:.3f}, {z_max_tile:.3f}]; "
                    "terrain will be raised/lowered beyond existing extremes."
                )
                _log.warning("handle_terrain_flatten_zone: %s", msg)
                warnings_out.append(msg)

        # Convert world coords to normalised [0, 1] grid coordinates.
        norm_cx    = (cx_w - min_x) / span_x
        norm_cy    = (cy_w - min_y) / span_y
        flat_radius = ((rx_w / span_x) + (ry_w / span_y)) * 0.5
        norm_blend = blend_w / min(span_x, span_y)

        # target_height stays as world-Z; flatten_terrain_zone works directly
        # in the grid's Z domain (no normalization needed because the grid
        # stores raw Z values, not [0,1]-normalised heights).
        norm_zones.append({
            "center_x":     norm_cx,
            "center_y":     norm_cy,
            "radius":       flat_radius,
            "target_height": float(th_w) if th_w is not None else None,
            "blend_width":  max(norm_blend, 1e-3),
            "priority":     prio,
            "seed":         seed_v,
        })

    # ------------------------------------------------------------------ #
    # Apply all zones via flatten_multiple_zones (priority-ordered).      #
    # ------------------------------------------------------------------ #
    flattened_grid = flatten_multiple_zones(grid, norm_zones)

    # ------------------------------------------------------------------ #
    # Map grid delta back to each vertex in local space.                  #
    # ------------------------------------------------------------------ #
    orig_sample = grid[row_idx, col_idx]
    flat_sample = flattened_grid[row_idx, col_idx]
    delta_z = flat_sample - orig_sample

    mat_inv = mat.inverted()
    for i, v in enumerate(verts):
        if delta_z[i] == 0.0:
            continue
        world_pos = mat @ v.co
        world_pos.z += delta_z[i]
        local_pos = mat_inv @ world_pos
        v.co.z = local_pos.z

    mesh.update()

    result: dict[str, Any] = {
        "status": "success",
        "object_name": obj_name,
        "vertices_modified": len(verts),
        "zones_applied": len(norm_zones),
    }
    if warnings_out:
        result["warnings"] = warnings_out
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Pure-logic / data helpers
    "evaluate_spline",
    "distance_point_to_polyline",
    "compute_falloff",
    "compute_spline_deformation",
    "TerrainLayer",
    "apply_layer_operation",
    "flatten_layers",
    "BrushResult",
    "compute_erosion_brush",
    "compute_flow_map",
    "apply_thermal_erosion",
    "compute_stamp_heightmap",
    "apply_stamp_to_heightmap",
    "flatten_terrain_zone",
    "flatten_multiple_zones",
    # Handler functions — wired into COMMAND_HANDLERS via handlers/__init__.py
    "handle_spline_deform",
    "handle_terrain_layers",
    "handle_erosion_paint",
    "handle_terrain_stamp",
    "handle_snap_to_terrain",
    "handle_terrain_flatten_zone",
]

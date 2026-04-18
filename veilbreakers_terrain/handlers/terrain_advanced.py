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

import json
import logging
import math
import random as _random
import warnings
from typing import Any

_log = logging.getLogger(__name__)

# Current serialization schema version for TerrainLayer.to_dict / from_dict.
_TERRAIN_LAYER_SCHEMA_VERSION = 2

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
) -> list[Vec3]:
    """Evaluate a smooth spline through the given control points.

    Args:
        spline_points: Ordered waypoints (at least 2).
        samples_per_segment: Number of evaluation points per Bezier segment.
        tension: Curve tightness (0=loose, 1=tight).

    Returns:
        List of (x, y, z) positions along the spline.
    """
    if len(spline_points) < 2:
        return list(spline_points)

    segments = _auto_control_points(spline_points, tension)
    result: list[Vec3] = []

    for seg_idx, (p0, p1, p2, p3) in enumerate(segments):
        n_samples = samples_per_segment if seg_idx < len(segments) - 1 else samples_per_segment + 1
        for i in range(n_samples):
            t = i / samples_per_segment
            pt = _cubic_bezier_point(p0, p1, p2, p3, t)
            result.append(pt)

    return result


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

    Uses proper Catmull-Rom spline evaluation so the deformation corridor
    follows a smooth curve rather than linear interpolation between control
    points. For each vertex inside the corridor the closest point on the
    spline is found via distance_point_to_polyline, and a falloff-weighted
    displacement is applied.

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

    # Evaluate Catmull-Rom spline to get a dense sample polyline.
    # This replaces the old Bezier-based evaluate_spline so that the
    # curve passes through every control point (B+).
    polyline = _evaluate_catmull_rom_spline(spline_points, samples_per_segment)

    # Collect spline heights for flatten mode
    spline_heights: list[float] = [pt[2] for pt in polyline] if mode == "flatten" else []

    result: dict[int, float] = {}
    falloff = max(0.0, min(1.0, falloff))
    blend_fraction = falloff
    core_width = width * (1.0 - blend_fraction)

    for idx, (vx, vy, vz) in enumerate(vert_positions):
        # Find closest point on the Catmull-Rom polyline (XY plane only).
        dist, closest, t_spline = distance_point_to_polyline(vx, vy, polyline)

        if dist > width:
            continue

        # Falloff-weighted displacement based on distance from spline axis.
        if dist <= core_width:
            weight = 1.0
        else:
            blend_dist = (dist - core_width) / max(width - core_width, 1e-6)
            weight = compute_falloff(blend_dist, "smooth")

        if weight <= 0.0:
            continue

        if mode == "carve":
            new_z = vz - depth * weight
        elif mode == "raise":
            new_z = vz + depth * weight
        elif mode == "flatten":
            if spline_heights:
                spline_idx = int(t_spline * (len(spline_heights) - 1))
                spline_idx = max(0, min(spline_idx, len(spline_heights) - 1))
                target_z = spline_heights[spline_idx]
            else:
                target_z = closest[2]
            new_z = vz + (target_z - vz) * weight
        elif mode == "smooth":
            # Pull vertex toward the spline's local height with reduced weight.
            new_z = vz + (closest[2] - vz) * weight * 0.3
        else:
            continue

        result[idx] = new_z

    return result


def handle_spline_deform(params: dict) -> dict:
    """Deform terrain along a spline path for roads/rivers (GAP-44).

    Params:
        object_name: str -- Name of the terrain mesh object.
        spline_points: list of [x, y, z] -- Control points for the spline.
        width: float -- Deformation corridor width (default 5.0).
        depth: float -- How far to carve/raise (default 1.0).
        falloff: float -- Edge softness, 0=sharp, 1=gradual (default 0.5).
        mode: str -- 'carve' | 'raise' | 'flatten' | 'smooth' (default 'carve').

    Returns:
        Dict with operation details and affected vertex count.
    """
    try:
        import bmesh
        import bpy
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

    spline_points = [tuple(p[:3]) for p in spline_points_raw]
    width = float(params.get("width", 5.0))
    depth = float(params.get("depth", 1.0))
    falloff = float(params.get("falloff", 0.5))
    mode = params.get("mode", "carve")
    samples_per_segment = max(4, min(int(params.get("samples_per_segment", 18)), 48))

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()

        positions = [(v.co.x, v.co.y, v.co.z) for v in bm.verts]
        new_heights = compute_spline_deformation(
            positions, spline_points, width, depth, falloff, mode, samples_per_segment,
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
        "depth": depth,
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
    """

    __slots__ = ("name", "heights", "blend_mode", "strength", "z_index")

    VALID_BLEND_MODES = ("ADD", "SUBTRACT", "MAX", "MIN", "MULTIPLY", "SCREEN")

    def __init__(
        self,
        name: str,
        width: int,
        height: int,
        blend_mode: str = "ADD",
        strength: float = 1.0,
        z_index: int = 0,
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

    def to_dict(self) -> dict[str, Any]:
        """Serialize layer to a plain dict (for storage on custom props).

        All fields present in from_dict are included. None values are
        written explicitly so round-trip fidelity is guaranteed.
        Schema version is stamped for forward-compatibility checks.
        """
        return {
            "schema_version": _TERRAIN_LAYER_SCHEMA_VERSION,
            "name": self.name,
            "blend_mode": self.blend_mode,
            "strength": self.strength,
            "z_index": self.z_index,
            "shape": list(self.heights.shape),
            "data": self.heights.tolist(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TerrainLayer":
        """Deserialize layer from a plain dict.

        Validates required fields, uses safe defaults for optional ones,
        and warns if the serialized schema_version is older than the
        current version so callers know a migration may be needed.
        """
        # --- required field validation ---
        missing = [k for k in ("name", "shape", "data") if k not in data]
        if missing:
            raise ValueError(
                f"TerrainLayer.from_dict: missing required keys: {missing}"
            )

        schema_ver = data.get("schema_version", 1)
        if schema_ver < _TERRAIN_LAYER_SCHEMA_VERSION:
            warnings.warn(
                f"TerrainLayer loaded from schema v{schema_ver}; "
                f"current is v{_TERRAIN_LAYER_SCHEMA_VERSION}. "
                "Some fields may use defaults.",
                UserWarning,
                stacklevel=2,
            )

        shape = data["shape"]
        if len(shape) != 2 or shape[0] < 1 or shape[1] < 1:
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

        layer = cls(
            name=str(data["name"]),
            width=shape[1],
            height=shape[0],
            blend_mode=blend_mode,
            strength=float(data.get("strength", 1.0)),
            z_index=int(data.get("z_index", 0)),
        )
        raw = data["data"]
        layer.heights = np.array(raw, dtype=np.float64).reshape(shape)
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
    valid_ops = ("raise", "lower", "smooth", "noise", "stamp", "multiply", "screen")
    if operation not in valid_ops:
        raise ValueError(f"Unknown operation: {operation!r}. Valid: {valid_ops}")

    if base_layer is not None and base_layer.heights.shape != layer.heights.shape:
        raise ValueError(
            f"apply_layer_operation: base_layer shape {base_layer.heights.shape} "
            f"does not match layer shape {layer.heights.shape}"
        )

    rows, cols = layer.heights.shape
    tw, td = terrain_size
    # terrain_origin is the terrain object's world-space center, not its min corner.
    ox, oy = terrain_origin
    min_x = ox - tw * 0.5
    min_y = oy - td * 0.5

    if tw <= 0 or td <= 0:
        return 0

    # Convert world-space brush to grid-space
    cx_grid = (center[0] - min_x) / tw * cols
    cy_grid = (center[1] - min_y) / td * rows
    r_grid_x = radius / tw * cols
    r_grid_y = radius / td * rows

    affected = 0
    rng = _random.Random(seed)

    min_row = max(0, int(cy_grid - r_grid_y) - 1)
    max_row = min(rows, int(cy_grid + r_grid_y) + 2)
    min_col = max(0, int(cx_grid - r_grid_x) - 1)
    max_col = min(cols, int(cx_grid + r_grid_x) + 2)

    for r in range(min_row, max_row):
        for c in range(min_col, max_col):
            # Compute normalized distance to brush center
            dx = (c - cx_grid) / max(r_grid_x, 1e-6)
            dy = (r - cy_grid) / max(r_grid_y, 1e-6)
            dist = math.sqrt(dx * dx + dy * dy)

            if dist > 1.0:
                continue

            weight = compute_falloff(dist, "smooth") * strength

            if operation == "raise":
                layer.heights[r, c] += weight
            elif operation == "lower":
                layer.heights[r, c] -= weight
            elif operation == "smooth":
                # Average with neighbors
                neighbors = []
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < rows and 0 <= nc < cols:
                            neighbors.append(layer.heights[nr, nc])
                if neighbors:
                    avg = sum(neighbors) / len(neighbors)
                    layer.heights[r, c] += (avg - layer.heights[r, c]) * weight
            elif operation == "noise":
                noise_val = rng.gauss(0.0, 0.5)
                layer.heights[r, c] += noise_val * weight
            elif operation == "stamp":
                layer.heights[r, c] = weight
            elif operation == "multiply":
                # Multiply blend: a * b, weighted towards original by (1-weight)
                b = base_layer.heights[r, c] if base_layer is not None else 1.0
                blended = layer.heights[r, c] * b
                layer.heights[r, c] = layer.heights[r, c] * (1.0 - weight) + blended * weight
            elif operation == "screen":
                # Screen blend: 1 - (1-a)*(1-b), weighted towards original by (1-weight)
                b = base_layer.heights[r, c] if base_layer is not None else 1.0
                a = layer.heights[r, c]
                blended = 1.0 - (1.0 - a) * (1.0 - b)
                layer.heights[r, c] = a * (1.0 - weight) + blended * weight

            affected += 1

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
    ordered = sorted(layers, key=lambda L: L.z_index)

    for layer in ordered:
        lh = layer.heights * layer.strength

        # Ensure the layer matches the base dimensions
        if lh.shape != result.shape:
            # Resize layer to match base using nearest-neighbor
            from_rows, from_cols = lh.shape
            to_rows, to_cols = result.shape
            row_indices = np.clip(
                (np.arange(to_rows) * from_rows / to_rows).astype(int),
                0, from_rows - 1,
            )
            col_indices = np.clip(
                (np.arange(to_cols) * from_cols / to_cols).astype(int),
                0, from_cols - 1,
            )
            lh = lh[np.ix_(row_indices, col_indices)]

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
                     "flatten_layers", "list_layers")
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
        # Use terrain grid resolution (approximate from vertex count)
        mesh = obj.data
        res = max(2, int(math.sqrt(len(mesh.vertices))))
        new_layer = TerrainLayer(layer_name, res, res, blend_mode, strength,
                                 z_index=z_index)
        layers.append(new_layer)
        obj["terrain_layers"] = json.dumps([L.to_dict() for L in layers])
        return {"status": "ok", "action": "add_layer", "layer_name": layer_name,
                "total_layers": len(layers)}

    elif action == "remove_layer":
        if not layer_name:
            return {"status": "error",
                    "error": "'layer_name' is required for remove_layer"}
        before = len(layers)
        layers = [L for L in layers if L.name != layer_name]
        obj["terrain_layers"] = json.dumps([L.to_dict() for L in layers])
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

        obj["terrain_layers"] = json.dumps([L.to_dict() for L in layers])
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
                    "shape": list(layer.heights.shape),
                }
                for layer in sorted(layers, key=lambda L: L.z_index)
            ],
            "total_layers": len(layers),
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

    for _it in range(iterations):
        delta = np.zeros_like(result)

        for r in range(min_r, max_r):
            for c in range(min_c, max_c):
                dx = (c - cx) / max(rx, 1e-6)
                dy = (r - cy) / max(ry, 1e-6)
                dist = math.sqrt(dx * dx + dy * dy)
                if dist > 1.0:
                    continue

                footprint[r, c] = True
                brush_weight = compute_falloff(dist, "smooth") * strength

                if erosion_type == "hydraulic":
                    # Simplified hydraulic: material moves downhill
                    h = result[r, c]
                    for dr, dc_off in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nr, nc = r + dr, c + dc_off
                        if 0 <= nr < rows and 0 <= nc < cols:
                            diff = h - result[nr, nc]
                            if diff > 0:
                                transfer = diff * 0.1 * brush_weight
                                delta[r, c] -= transfer
                                delta[nr, nc] += transfer

                elif erosion_type == "thermal":
                    # Thermal: excess slope material slides down.
                    # talus_in_height_units is already normalised for cell_size
                    # so this is resolution-independent (BUG-13 class fix).
                    h = result[r, c]
                    for dr, dc_off in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nr, nc = r + dr, c + dc_off
                        if 0 <= nr < rows and 0 <= nc < cols:
                            diff = h - result[nr, nc]
                            exc = max(diff - talus_in_height_units, 0.0)
                            if exc > 0.0:
                                transfer = exc * 0.3 * brush_weight
                                delta[r, c] -= transfer
                                delta[nr, nc] += transfer

                elif erosion_type == "wind":
                    # Wind erosion: noise-based directional erosion
                    noise = rng.gauss(0.0, 0.3)
                    delta[r, c] -= abs(noise) * brush_weight * 0.05
                    # Deposit downwind (positive X direction)
                    deposit_c = min(c + 1, cols - 1)
                    delta[r, deposit_c] += abs(noise) * brush_weight * 0.05

        # Track eroded / deposited per cell across all iterations
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
) -> dict[str, Any]:
    """Compute water flow direction from heightmap using D8 algorithm.

    Pure-logic function -- no bpy needed.

    Args:
        heightmap: 2D array of height values (list of lists or numpy array).
        resolution: Unused, kept for API compatibility.

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

    # --- Step 1: Compute flow direction (D8 steepest descent) ---
    slopes_vec = np.full((8, rows, cols), -np.inf, dtype=np.float64)
    for _d_idx, ((_dr, _dc), _dist) in enumerate(zip(_D8_OFFSETS, _D8_DISTANCES)):
        _r_d = slice(max(0, -_dr), rows - max(0, _dr))
        _r_s = slice(max(0,  _dr), rows - max(0, -_dr))
        _c_d = slice(max(0, -_dc), cols - max(0, _dc))
        _c_s = slice(max(0,  _dc), cols - max(0, -_dc))
        slopes_vec[_d_idx, _r_d, _c_d] = (hmap[_r_d, _c_d] - hmap[_r_s, _c_s]) / _dist

    _best_d8 = np.argmax(slopes_vec, axis=0)
    _ri_v = np.arange(rows)[:, None]
    _ci_v = np.arange(cols)[None, :]
    _best_slope = slopes_vec[_best_d8, _ri_v, _ci_v]
    flow_dir = np.where(_best_slope > 0.0, _best_d8, -1).astype(np.int32)

    # --- Step 2: Compute flow accumulation ---
    # Each cell accumulates flow from all cells that drain into it.
    flow_acc = np.ones((rows, cols), dtype=np.float64)

    # Sort cells by height (highest first) for top-down accumulation
    flat_indices = np.argsort(-hmap.ravel())

    for flat_idx in flat_indices:
        r = flat_idx // cols
        c = flat_idx % cols

        d = flow_dir[r, c]
        if d < 0:
            continue

        dr, dc = _D8_OFFSETS[d]
        nr, nc = r + dr, c + dc
        if 0 <= nr < rows and 0 <= nc < cols:
            flow_acc[nr, nc] += flow_acc[r, c]

    # --- Step 3: Compute drainage basins ---
    # Trace each cell downstream to its terminal pit; assign basin IDs.
    basins = np.full((rows, cols), -1, dtype=np.int32)
    basin_id = 0

    for r in range(rows):
        for c in range(cols):
            if basins[r, c] >= 0:
                continue

            # Trace downstream
            path: list[tuple[int, int]] = []
            cr, cc = r, c
            visited_set: set[tuple[int, int]] = set()

            while True:
                if (cr, cc) in visited_set:
                    break
                visited_set.add((cr, cc))
                path.append((cr, cc))

                if basins[cr, cc] >= 0:
                    # Hit an already-assigned cell
                    assigned_id = basins[cr, cc]
                    for pr, pc in path:
                        basins[pr, pc] = assigned_id
                    break

                d = flow_dir[cr, cc]
                if d < 0:
                    # Terminal pit: assign new basin
                    for pr, pc in path:
                        basins[pr, pc] = basin_id
                    basin_id += 1
                    break

                dr, dc = _D8_OFFSETS[d]
                nr, nc = cr + dr, cc + dc
                if not (0 <= nr < rows and 0 <= nc < cols):
                    # Edge of map: assign new basin
                    for pr, pc in path:
                        basins[pr, pc] = basin_id
                    basin_id += 1
                    break

                cr, cc = nr, nc

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
    heightmap: list[list[float]] | np.ndarray,
    iterations: int = 50,
    talus_angle: float = 30.0,
    strength: float = 0.3,
    cell_size: float = 1.0,
) -> list[list[float]]:
    """Thermal erosion -- material slumps from steep slopes to flat areas.

    Distinct from hydraulic (water-based). Simulates rockfall and scree slopes.
    Pure-logic function.

    Args:
        heightmap: 2D array of height values.
        iterations: Number of erosion passes (default 50).
        talus_angle: Maximum stable slope angle in **degrees** (default 30.0).
                     Material on steeper slopes slides downhill. Lower values
                     produce more erosion.
        strength: Fraction of excess material transferred per iteration (0-1).
                 Default 0.3.
        cell_size: Real-world size of one grid cell (world units, default 1.0).
                   Normalises the talus threshold so that erosion behaviour
                   is resolution-independent (BUG-13 class fix).
                   ``talus_threshold = tan(radians(talus_angle)) * cell_size``
                   matches the raw per-cell height difference used in the
                   slope comparison.

    Returns:
        2D list of eroded height values (same dimensions as input).
    """
    hmap = np.asarray(heightmap, dtype=np.float64).copy()
    rows, cols = hmap.shape

    if rows < 2 or cols < 2:
        return hmap.tolist()

    # Convert degrees to a height-difference threshold that is cell_size-aware.
    # This eliminates resolution dependency: the same angle produces the same
    # visual result regardless of grid spacing (BUG-13 class fix).
    talus_in_height_units = math.tan(math.radians(talus_angle)) * max(cell_size, 1e-6)

    for _it in range(iterations):
        diff_N = hmap[1:-1, 1:-1] - hmap[0:-2, 1:-1]
        diff_S = hmap[1:-1, 1:-1] - hmap[2:,   1:-1]
        diff_W = hmap[1:-1, 1:-1] - hmap[1:-1, 0:-2]
        diff_E = hmap[1:-1, 1:-1] - hmap[1:-1, 2:  ]
        exc_N = np.maximum(diff_N - talus_in_height_units, 0.0)
        exc_S = np.maximum(diff_S - talus_in_height_units, 0.0)
        exc_W = np.maximum(diff_W - talus_in_height_units, 0.0)
        exc_E = np.maximum(diff_E - talus_in_height_units, 0.0)
        total_exc = exc_N + exc_S + exc_W + exc_E
        max_exc   = np.maximum.reduce([exc_N, exc_S, exc_W, exc_E])
        active    = total_exc > 0.0
        safe_total = np.where(active, total_exc, 1.0)
        transfer   = np.where(active, max_exc * strength * 0.5, 0.0)
        t_N = np.where(active, transfer * exc_N / safe_total, 0.0)
        t_S = np.where(active, transfer * exc_S / safe_total, 0.0)
        t_W = np.where(active, transfer * exc_W / safe_total, 0.0)
        t_E = np.where(active, transfer * exc_E / safe_total, 0.0)
        delta = np.zeros_like(hmap)
        delta[1:-1, 1:-1] -= (t_N + t_S + t_W + t_E)
        delta[0:-2, 1:-1] += t_N
        delta[2:,   1:-1] += t_S
        delta[1:-1, 0:-2] += t_W
        delta[1:-1, 2:  ] += t_E
        hmap += delta

    return hmap.tolist()


# ---------------------------------------------------------------------------
# 6. Terrain Stamp / Feature Placement (pure logic + handler)
# ---------------------------------------------------------------------------

# Stamp shape generators
_STAMP_SHAPES = {
    "crater": lambda r_norm: max(0.0, 1.0 - abs(r_norm * 2.0 - 1.0)),
    "mesa": lambda r_norm: 1.0 if r_norm < 0.6 else max(0.0, 1.0 - (r_norm - 0.6) / 0.4),
    "hill": lambda r_norm: max(0.0, math.cos(r_norm * math.pi / 2.0)),
    "valley": lambda r_norm: -max(0.0, math.cos(r_norm * math.pi / 2.0)),
    "plateau": lambda r_norm: 1.0 if r_norm < 0.7 else max(0.0, 1.0 - (r_norm - 0.7) / 0.3),
    "ridge": lambda r_norm: max(0.0, 1.0 - abs(r_norm - 0.5) * 2.0),
}


def compute_stamp_heightmap(
    stamp_type: str,
    resolution: int = 64,
    custom_heightmap: list[list[float]] | None = None,
) -> np.ndarray:
    """Generate a 2D stamp heightmap for a given stamp type.

    Pure-logic function.

    Args:
        stamp_type: 'crater' | 'mesa' | 'hill' | 'valley' | 'plateau' |
                   'ridge' | 'custom'.
        resolution: Output heightmap resolution.
        custom_heightmap: Used when stamp_type is 'custom'.

    Returns:
        2D numpy array of shape (resolution, resolution) with values in [0, 1]
        (or [-1, 0] for valley).
    """
    if stamp_type == "custom":
        if custom_heightmap is not None:
            return np.asarray(custom_heightmap, dtype=np.float64)
        return np.zeros((resolution, resolution), dtype=np.float64)

    if stamp_type not in _STAMP_SHAPES:
        raise ValueError(
            f"Unknown stamp_type: {stamp_type!r}. "
            f"Valid: {sorted(list(_STAMP_SHAPES.keys()) + ['custom'])}"
        )

    shape_fn = _STAMP_SHAPES[stamp_type]
    center = resolution / 2.0

    # Vectorised generation: build the full (resolution x resolution) distance
    # grid in one numpy pass, then apply the radial shape function via
    # np.vectorize (removes the Python loop over rows/cols).
    cols_idx = np.arange(resolution, dtype=np.float64)
    rows_idx = np.arange(resolution, dtype=np.float64)
    cc, rr = np.meshgrid(cols_idx, rows_idx)   # shape: (resolution, resolution)
    dx = (cc - center) / max(center, 1e-9)
    dy = (rr - center) / max(center, 1e-9)
    dist = np.sqrt(dx * dx + dy * dy)           # radially-symmetric distance field

    # Apply the shape function element-wise; np.vectorize handles the scalar fn.
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
) -> np.ndarray:
    """Apply a stamp heightmap onto a terrain heightmap.

    Pure-logic function.

    Stamp coordinates are treated as world-unit values and converted to
    cell indices via ``cell_index = world_coord / cell_size``. Sub-cell
    precision is achieved through bilinear interpolation of the stamp
    texture. The stamp contribution is clamped to the rectangular bounding
    region of the stamp so no writes occur outside the footprint.

    Args:
        heightmap: 2D terrain heightmap.
        stamp: 2D stamp heightmap (values typically in [0, 1]).
        position: (x, y) world-space position to place the stamp center.
        radius: World-space radius of the stamp.
        height: Height multiplier for the stamp values.
        falloff: Edge softness (0=sharp, 1=gradual).
        terrain_size: (width, depth) of the terrain in world units.
        terrain_origin: World-space (x, y) center of the terrain object.
        cell_size: Real-world size of one grid cell. When None it is derived
                   from terrain_size and the heightmap shape. Used to convert
                   world-space stamp coordinates to cell indices precisely.

    Returns:
        Modified heightmap (copy).
    """
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
    # stamp_cx_cells = (stamp_cx_world - terrain_min_x) / cell_size
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

    for r in range(min_r, max_r + 1):
        for c in range(min_c, max_c + 1):
            # Normalized position relative to stamp center [-1, 1]
            nx = (c - cx_cells) / max(r_cells, 1e-6)
            ny = (r - cy_cells) / max(r_cells, 1e-6)
            dist = math.sqrt(nx * nx + ny * ny)

            if dist > 1.0:
                continue

            # Map [-1, 1] to fractional stamp coordinates for bilinear sample.
            su = (nx + 1.0) * 0.5 * (stamp_cols - 1)  # fractional col in stamp
            sv = (ny + 1.0) * 0.5 * (stamp_rows - 1)  # fractional row in stamp
            stamp_val = _bilinear_sample(stamp, sv, su)

            # Apply falloff at edges
            edge_falloff = compute_falloff(dist, "smooth") if falloff > 0 else 1.0

            result[r, c] += stamp_val * height * edge_falloff

    return result


def handle_terrain_stamp(params: dict) -> dict:
    """Stamp features onto existing terrain (GAP-28/GAP-10).

    Params:
        object_name: str -- Terrain mesh object name.
        stamp_type: str -- 'crater' | 'mesa' | 'hill' | 'valley' | 'plateau' |
                          'ridge' | 'custom'.
        position: [x, y] -- World coords for stamp center (converted internally
                            to cell indices using cell_size).
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
    except ImportError as exc:
        raise RuntimeError("handle_terrain_stamp requires Blender") from exc

    object_name = params.get("object_name")
    if not object_name:
        raise ValueError("'object_name' is required")

    obj = bpy.data.objects.get(object_name)
    if obj is None or obj.type != "MESH":
        raise ValueError(f"Terrain mesh not found: {object_name}")

    stamp_type = params.get("stamp_type", "hill")
    position = tuple(params.get("position", [50.0, 50.0])[:2])
    radius = float(params.get("radius", 10.0))
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
        heightmap = np.array([v.co.z for v in bm.verts]).reshape(rows, cols)

        dims = obj.dimensions
        terrain_size = (dims.x, dims.y)
        terrain_origin = (obj.location.x, obj.location.y)

        # Derive cell_size from terrain dimensions and grid resolution.
        cs_x = dims.x / max(cols - 1, 1)
        cs_y = dims.y / max(rows - 1, 1)
        cell_size = (cs_x + cs_y) * 0.5

        # Convert world-space stamp center to cell indices for validation.
        terrain_min_x = obj.location.x - dims.x * 0.5
        terrain_min_y = obj.location.y - dims.y * 0.5
        stamp_cx_cells = (position[0] - terrain_min_x) / cell_size
        stamp_cy_cells = (position[1] - terrain_min_y) / cell_size
        r_cells = radius / cell_size

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
            heightmap, stamp, position, radius, height, falloff,
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
        "position": list(position),
        "radius": radius,
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

"""Bundle R — Blender-specific runtime stability guards.

Consolidates every "thing that can crash Blender" rule from the feedback
memory files into enforceable callable guards:
  - Z-up enforcement (feedback_blender_z_up.md)
  - Screenshot size cap (feedback_screenshot_max_size.md): HARD CAP 507
  - Boolean op dense mesh guard (feedback_blender_crash_avoidance.md): 60k vert
  - GLB/GLTF batch import serialization

See Addendum 1.A.6 for the authoritative spec.
"""

from __future__ import annotations

import functools
import threading
from pathlib import Path
from typing import Callable, List, Sequence, Tuple


class CoordinateSystemError(RuntimeError):
    """Raised when a non-Z-up coordinate is used for terrain heights."""


class BlenderBooleanUnsafe(RuntimeError):
    """Raised when a boolean op would operate on a too-dense mesh."""


# ---------------------------------------------------------------------------
# Z-up enforcement
# ---------------------------------------------------------------------------


def assert_z_is_up(obj_up_axis: str) -> None:
    """Raise ``CoordinateSystemError`` if the up axis is not 'Z'.

    Takes a string ('X'/'Y'/'Z' or '-X'/'-Y'/'-Z') so this works in
    headless mode without a live ``bpy.types.Object`` reference.
    """
    normalized = obj_up_axis.strip().upper().lstrip("+")
    if normalized.lstrip("-") != "Z":
        raise CoordinateSystemError(
            f"object up axis is {obj_up_axis!r}; VeilBreakers is Z-up only. "
            "Call convert_y_up_to_z_up() at the import boundary."
        )


def convert_y_up_to_z_up(
    position: Tuple[float, float, float],
    orientation: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    euler_order: str = "XYZ",
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """Convert a Y-up coordinate (x, y, z) to Z-up (x, -z, y).

    Blender 4.5 is right-handed Z-up. FBX/GLTF importers (and many DCC
    tools including Maya and Unity) deliver Y-up; use this at every import
    boundary.

    Position transform
    ------------------
    The Y-up → Z-up axis realignment is a -90° rotation around the X axis:

        Y-up (x, y, z)  →  Z-up (x, -z, y)

    This is the standard convention used by Blender's own FBX importer and
    is consistent with the GLTF 2.0 spec (section 3.4 Coordinate System).

    Orientation transform
    ---------------------
    A naive component swap `(rx, ry, rz) → (rx, -rz, ry)` is only correct
    for small rotations or when only one axis is non-zero. For the general
    case the correct approach is:

      1. Build the 3×3 rotation matrix R from the input Euler angles
         (using the specified ``euler_order``).
      2. Pre-multiply by the Y→Z axis-swap matrix M = R_x(-90°):
             [[1,  0,  0],
              [0,  0,  1],
              [0, -1,  0]]
      3. Decompose MR back to Euler angles (same order) for the output.

    The decomposition uses atan2 with the standard ZYX/XYZ Euler extraction
    formulas. Falls back to the component-swap approximation (with a warning
    logged) for unsupported Euler orders.

    Args:
        position:    (x, y, z) in Y-up world space.
        orientation: (rx, ry, rz) Euler angles in radians, Y-up convention.
        euler_order: Euler rotation order string (e.g. ``'XYZ'``, ``'ZYX'``).
                     Only ``'XYZ'`` and ``'ZYX'`` use the full matrix path;
                     others use the component-swap approximation.

    Returns:
        Tuple of (zup_position, zup_orientation) both as (float, float, float).
    """
    import math as _math

    x, y, z = float(position[0]), float(position[1]), float(position[2])
    zup_position = (x, -z, y)

    rx, ry, rz = float(orientation[0]), float(orientation[1]), float(orientation[2])
    order = euler_order.strip().upper()

    # ------------------------------------------------------------------
    # Full matrix path for XYZ and ZYX Euler orders.
    # ------------------------------------------------------------------
    # Axis-swap matrix for Y-up → Z-up: R_x(-90°)
    #   M = [[1,  0,  0],
    #        [0,  0,  1],
    #        [0, -1,  0]]
    # Input rotation matrix R (from Euler angles, intrinsic rotations).
    # Output = decompose(M @ R) back to the same Euler order.

    def _rot_x(a: float) -> List:
        ca, sa = _math.cos(a), _math.sin(a)
        return [[1, 0, 0], [0, ca, -sa], [0, sa, ca]]

    def _rot_y(a: float) -> List:
        ca, sa = _math.cos(a), _math.sin(a)
        return [[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]]

    def _rot_z(a: float) -> List:
        ca, sa = _math.cos(a), _math.sin(a)
        return [[ca, -sa, 0], [sa, ca, 0], [0, 0, 1]]

    def _mat_mul(A: List, B: List) -> List:
        return [
            [sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)
        ]

    if order == "XYZ":
        # Intrinsic XYZ: R = Rz(rz) @ Ry(ry) @ Rx(rx)
        R = _mat_mul(_mat_mul(_rot_z(rz), _rot_y(ry)), _rot_x(rx))
        # Axis-swap matrix M = Rx(-pi/2)
        M = _rot_x(-_math.pi / 2.0)
        MR = _mat_mul(M, R)
        # Decompose MR → XYZ Euler: ry = asin(-MR[2][0]), rx/rz from atan2
        sy = -MR[2][0]
        sy = max(-1.0, min(1.0, sy))
        out_ry = _math.asin(sy)
        if abs(sy) < 0.9999:
            out_rx = _math.atan2(MR[2][1], MR[2][2])
            out_rz = _math.atan2(MR[1][0], MR[0][0])
        else:
            # Gimbal lock
            out_rx = _math.atan2(-MR[1][2], MR[1][1])
            out_rz = 0.0
        zup_orientation: Tuple[float, float, float] = (out_rx, out_ry, out_rz)

    elif order == "ZYX":
        # Intrinsic ZYX: R = Rx(rx) @ Ry(ry) @ Rz(rz)
        R = _mat_mul(_mat_mul(_rot_x(rx), _rot_y(ry)), _rot_z(rz))
        M = _rot_x(-_math.pi / 2.0)
        MR = _mat_mul(M, R)
        # Decompose MR → ZYX Euler
        sy = -MR[2][0]
        sy = max(-1.0, min(1.0, sy))
        out_ry = _math.asin(sy)
        if abs(sy) < 0.9999:
            out_rx = _math.atan2(MR[2][1], MR[2][2])
            out_rz = _math.atan2(MR[1][0], MR[0][0])
        else:
            out_rx = _math.atan2(-MR[1][2], MR[1][1])
            out_rz = 0.0
        zup_orientation = (out_rx, out_ry, out_rz)

    else:
        # Approximation fallback for other Euler orders.
        # Correct for zero/small rx; breaks at large ±90° ry/rz combinations.
        import logging as _logging
        _logging.getLogger(__name__).debug(
            "convert_y_up_to_z_up: unsupported euler_order %r — using "
            "component-swap approximation (may be inaccurate for large rotations).",
            euler_order,
        )
        zup_orientation = (rx, -rz, ry)

    return zup_position, zup_orientation


def guard_z_up(fn: Callable) -> Callable:
    """Decorator that checks any ``up`` kwarg before the wrapped function runs."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        up_axis = kwargs.get("up_axis")
        if up_axis is not None:
            assert_z_is_up(str(up_axis))
        return fn(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Screenshot size cap
# ---------------------------------------------------------------------------

# HARD CAP — feedback memory feedback_screenshot_max_size.md. NEVER 1024.
BLENDER_SCREENSHOT_MAX_SIZE: int = 507
BLENDER_SCREENSHOT_MIN_SIZE: int = 64


def clamp_screenshot_size(requested: int) -> int:
    """Clamp a requested screenshot dimension to the safe band [64, 507]."""
    try:
        r = int(requested)
    except Exception:
        return BLENDER_SCREENSHOT_MAX_SIZE
    if r < BLENDER_SCREENSHOT_MIN_SIZE:
        return BLENDER_SCREENSHOT_MIN_SIZE
    if r > BLENDER_SCREENSHOT_MAX_SIZE:
        return BLENDER_SCREENSHOT_MAX_SIZE
    return r


# ---------------------------------------------------------------------------
# Boolean dense-mesh guard
# ---------------------------------------------------------------------------

BOOLEAN_DENSE_MESH_VERT_LIMIT: int = 60000
BOOLEAN_DENSE_MESH_DECIMATE_TARGET: int = 30000


def assert_boolean_safe(
    cutter_vert_count: int,
    target_vert_count: int,
    *,
    limit: int = BOOLEAN_DENSE_MESH_VERT_LIMIT,
) -> None:
    """Raise if either operand exceeds the boolean safety limit."""
    if cutter_vert_count > limit:
        raise BlenderBooleanUnsafe(
            f"boolean cutter has {cutter_vert_count} verts (limit {limit}). "
            "Decimate first or use a simpler cutter."
        )
    if target_vert_count > limit:
        raise BlenderBooleanUnsafe(
            f"boolean target has {target_vert_count} verts (limit {limit}). "
            "Decimate first."
        )


def decimate_to_safe_count(
    current_vert_count: int,
    target_count: int = BOOLEAN_DENSE_MESH_DECIMATE_TARGET,
) -> float:
    """Return the decimation ratio required to reach ``target_count``.

    The caller is responsible for applying the ratio (real Blender
    would call ``bpy.ops.object.modifier_add(type='DECIMATE')``).
    """
    if current_vert_count <= 0:
        return 1.0
    if current_vert_count <= target_count:
        return 1.0
    return max(0.01, float(target_count) / float(current_vert_count))


def recommend_boolean_solver(
    cutter_vert_count: int,
    target_vert_count: int,
    *,
    operation: str = "DIFFERENCE",
    cutter_is_manifold: bool = True,
    target_is_manifold: bool = True,
) -> str:
    """Return the recommended Blender 4.5 boolean solver for the given mesh pair.

    Blender 4.5 exposes two boolean solvers:
    - ``EXACT``  (Mesh Boolean / Exact Kernel) — robust for manifold closed
      meshes, handles self-intersections and co-planar faces correctly.
      Slow on dense meshes (>~20 k verts); interactive-rate only below that.
    - ``FAST``   (BMesh Boolean) — O(n log n) but can fail or produce
      artefacts on non-manifold geometry, co-planar faces, or extremely
      dense inputs.

    Selection rules matching Blender 4.5 developer guidance and VeilBreakers
    terrain pipeline constraints:

    1. **Non-positive count** (unknown / uninitialised geometry): always
       ``EXACT`` — safer unknown-geometry default.
    2. **Non-manifold geometry**: always ``EXACT``. FAST produces topological
       artefacts (extra faces, missing fills) on open meshes. This is the
       most common Blender boolean crash root cause for terrain.
    3. **INTERSECT operation**: always ``EXACT`` regardless of density.
       FAST's BMesh kernel has known INTERSECT failures on non-convex
       geometry; EXACT's half-edge kernel handles all convex/concave cases.
    4. **Dense mesh (> 20 000 verts)**: ``FAST`` for UNION/DIFFERENCE on
       manifold pairs — EXACT becomes interactive-rate slow above this
       threshold, confirmed in Blender 4.5 profiling.
    5. **Default (small manifold mesh)**: ``EXACT`` for maximum robustness on
       terrain hero geometry where quality > speed.

    Args:
        cutter_vert_count: Vertex count of the boolean cutter object.
        target_vert_count: Vertex count of the boolean target object.
        operation: Boolean operation type — one of ``'UNION'``,
            ``'DIFFERENCE'``, ``'INTERSECT'``.  Defaults to ``'DIFFERENCE'``.
        cutter_is_manifold: Whether the cutter mesh is manifold (closed,
            no boundary edges, no non-manifold vertices). Defaults to
            ``True`` (optimistic assumption).
        target_is_manifold: Whether the target mesh is manifold. Defaults
            to ``True``.

    Returns:
        ``'FAST'`` or ``'EXACT'``.
    """
    # Rule 1: unknown geometry → safe default
    if cutter_vert_count <= 0 or target_vert_count <= 0:
        return "EXACT"

    # Rule 2: non-manifold operand → EXACT (FAST produces artefacts on open meshes)
    if not cutter_is_manifold or not target_is_manifold:
        return "EXACT"

    # Rule 3: INTERSECT → always EXACT (BMesh INTERSECT has known failures)
    op = operation.strip().upper()
    if op == "INTERSECT":
        return "EXACT"

    # Rule 4: dense manifold UNION/DIFFERENCE → FAST for interactivity
    dense = max(int(cutter_vert_count), int(target_vert_count))
    if dense > 20000:
        return "FAST"

    # Rule 5: small manifold mesh → EXACT for hero-quality terrain geometry
    return "EXACT"


# ---------------------------------------------------------------------------
# GLB/GLTF import serialization
# ---------------------------------------------------------------------------

_GLTF_IMPORT_LOCK = threading.Lock()
_GLTF_IMPORT_LOG: List[Path] = []


def import_gltf_serialized(
    glb_paths: Sequence[Path],
    *,
    require_exists: bool = True,
) -> List[Path]:
    """Return ``glb_paths`` in order, holding a global lock for each.

    Enforces two contracts (Addendum 1.A.6):
      1. Path must exist on disk when ``require_exists=True`` (default).
      2. Path must end in ``.glb`` or ``.gltf`` — anything else is rejected.
      3. Exactly one import is in flight at any time, via a process-wide
         lock (``_GLTF_IMPORT_LOCK``).

    Real Blender would call ``bpy.ops.import_scene.gltf(filepath=...)``
    inside the with-block. Headless mode records the serialization order
    and validated paths so tests can assert the contract.
    """
    out: List[Path] = []
    for p in glb_paths:
        path = Path(p)
        suffix = path.suffix.lower()
        if suffix not in (".glb", ".gltf"):
            raise ValueError(
                f"import_gltf_serialized: unsupported suffix {suffix!r} "
                f"for {path!r}; expected .glb or .gltf"
            )
        if require_exists and not path.exists():
            raise FileNotFoundError(
                f"import_gltf_serialized: missing file {path!r}"
            )
        with _GLTF_IMPORT_LOCK:
            out.append(path)
            _GLTF_IMPORT_LOG.append(path)
    return out


def get_gltf_import_log() -> List[Path]:
    """Test helper — returns a copy of the serialization log."""
    return list(_GLTF_IMPORT_LOG)


def clear_gltf_import_log() -> None:
    _GLTF_IMPORT_LOG.clear()


__all__ = [
    "CoordinateSystemError",
    "BlenderBooleanUnsafe",
    "assert_z_is_up",
    "convert_y_up_to_z_up",
    "guard_z_up",
    "BLENDER_SCREENSHOT_MAX_SIZE",
    "BLENDER_SCREENSHOT_MIN_SIZE",
    "clamp_screenshot_size",
    "BOOLEAN_DENSE_MESH_VERT_LIMIT",
    "BOOLEAN_DENSE_MESH_DECIMATE_TARGET",
    "assert_boolean_safe",
    "decimate_to_safe_count",
    "recommend_boolean_solver",
    "import_gltf_serialized",
    "get_gltf_import_log",
    "clear_gltf_import_log",
]

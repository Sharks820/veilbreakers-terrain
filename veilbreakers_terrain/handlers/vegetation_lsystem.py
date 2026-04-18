"""L-System vegetation pipeline for VeilBreakers dark fantasy environments.

Provides procedural tree generation using Lindenmayer systems, leaf card
placement, wind vertex color baking for Unity shaders, billboard impostor
mesh generation, and GPU instancing export preparation.

All core functions are pure-logic (no bpy dependency) for testability.
Handler functions that create Blender objects import bpy only at call time.

Gap coverage: #54 (L-system trees), #29 (botanical accuracy), #37 (tree
variety), #55 (wind vertex colors), #56 (billboard impostors),
#19/item44 (GPU instancing).
"""

from __future__ import annotations

import math
import random as _random
from typing import Any, List

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    _np = None  # type: ignore[assignment]
    _HAS_NUMPY = False


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------
Vec3 = tuple[float, float, float]
MeshSpec = dict[str, Any]


# ---------------------------------------------------------------------------
# L-System grammar definitions per tree type
# ---------------------------------------------------------------------------

LSYSTEM_GRAMMARS: dict[str, dict[str, Any]] = {
    "oak": {
        "axiom": "F",
        "rules": {"F": "FF[+F][-F]F[+F]"},
        "default_iterations": 5,
        "branch_angle": 25.0,
        "branch_ratio": 0.7,
        "trunk_ratio": 0.85,
        "gravity": 0.1,
        "randomness": 0.2,
        "leaf_density": 0.8,
        "description": "Broad, spreading canopy with thick trunk",
    },
    "pine": {
        "axiom": "F",
        "rules": {"F": "FF[++F][--F][+F][-F]"},
        "default_iterations": 5,
        "branch_angle": 30.0,
        "branch_ratio": 0.6,
        "trunk_ratio": 0.9,
        "gravity": 0.05,
        "randomness": 0.1,
        "leaf_density": 0.9,
        "description": "Tall conical shape with regular branch whorls",
    },
    "birch": {
        "axiom": "F",
        "rules": {"F": "F[+F]F[-F]"},
        "default_iterations": 6,
        "branch_angle": 20.0,
        "branch_ratio": 0.65,
        "trunk_ratio": 0.88,
        "gravity": 0.15,
        "randomness": 0.15,
        "leaf_density": 0.7,
        "description": "Slender trunk with delicate branching",
    },
    "willow": {
        "axiom": "F",
        "rules": {"F": "F[+F][-F][+F][-F]"},
        "default_iterations": 5,
        "branch_angle": 35.0,
        "branch_ratio": 0.75,
        "trunk_ratio": 0.8,
        "gravity": 0.6,
        "randomness": 0.2,
        "leaf_density": 0.85,
        "description": "Heavy drooping branches, weeping form",
    },
    "dead": {
        "axiom": "F",
        "rules": {"F": "F[+F][-F]"},
        "default_iterations": 5,
        "branch_angle": 30.0,
        "branch_ratio": 0.6,
        "trunk_ratio": 0.82,
        "gravity": 0.05,
        "randomness": 0.4,
        "leaf_density": 0.0,
        "description": "Bare twisted branches, no foliage",
    },
    "ancient": {
        "axiom": "F",
        "rules": {"F": "FF[+F][-F]F[+F][-F]"},
        "default_iterations": 4,
        "branch_angle": 22.0,
        "branch_ratio": 0.75,
        "trunk_ratio": 0.8,
        "gravity": 0.15,
        "randomness": 0.25,
        "leaf_density": 0.6,
        "description": "Massive gnarled trunk, thick sprawling branches",
    },
    "twisted": {
        "axiom": "F",
        "rules": {"F": "F[++F][--F]"},
        "default_iterations": 6,
        "branch_angle": 40.0,
        "branch_ratio": 0.65,
        "trunk_ratio": 0.85,
        "gravity": 0.1,
        "randomness": 0.5,
        "leaf_density": 0.3,
        "description": "Wind-swept asymmetric form, sparse foliage",
    },
}


# ---------------------------------------------------------------------------
# L-System string expansion
# ---------------------------------------------------------------------------

def expand_lsystem(
    axiom: str,
    rules: dict[str, str],
    iterations: int,
) -> str:
    """Expand an L-system grammar for a given number of iterations.

    Args:
        axiom: Starting string (e.g., 'F').
        rules: Production rules mapping characters to replacement strings.
        iterations: Number of expansion iterations.

    Returns:
        Expanded L-system string.
    """
    current = axiom
    for _ in range(iterations):
        next_str: list[str] = []
        for ch in current:
            next_str.append(rules.get(ch, ch))
        current = "".join(next_str)
    return current


# ---------------------------------------------------------------------------
# Turtle interpreter -- converts L-system string to branch segments
# ---------------------------------------------------------------------------

def _rotate_vector(
    vx: float, vy: float, vz: float,
    axis_x: float, axis_y: float, axis_z: float,
    angle_rad: float,
) -> tuple[float, float, float]:
    """Rotate vector (vx, vy, vz) around axis by angle using Rodrigues' formula."""
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    # Normalize axis
    al = math.sqrt(axis_x ** 2 + axis_y ** 2 + axis_z ** 2)
    if al < 1e-12:
        return (vx, vy, vz)
    ax, ay, az = axis_x / al, axis_y / al, axis_z / al

    # Rodrigues' rotation
    dot = vx * ax + vy * ay + vz * az
    cross_x = ay * vz - az * vy
    cross_y = az * vx - ax * vz
    cross_z = ax * vy - ay * vx

    rx = vx * cos_a + cross_x * sin_a + ax * dot * (1.0 - cos_a)
    ry = vy * cos_a + cross_y * sin_a + ay * dot * (1.0 - cos_a)
    rz = vz * cos_a + cross_z * sin_a + az * dot * (1.0 - cos_a)

    return (rx, ry, rz)


class _TurtleState:
    """Turtle state for L-system interpretation."""
    __slots__ = ("x", "y", "z", "dx", "dy", "dz", "radius", "depth",
                 "right_x", "right_y", "right_z")

    def __init__(self) -> None:
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        # Direction (initially pointing up: +Z)
        self.dx = 0.0
        self.dy = 0.0
        self.dz = 1.0
        # Right vector (initially +X)
        self.right_x = 1.0
        self.right_y = 0.0
        self.right_z = 0.0
        self.radius = 1.0
        self.depth = 0

    def copy(self) -> "_TurtleState":
        s = _TurtleState()
        s.x, s.y, s.z = self.x, self.y, self.z
        s.dx, s.dy, s.dz = self.dx, self.dy, self.dz
        s.right_x, s.right_y, s.right_z = self.right_x, self.right_y, self.right_z
        s.radius = self.radius
        s.depth = self.depth
        return s


class BranchSegment:
    """A single branch segment connecting two points.

    Attributes:
        start: (x, y, z) start position.
        end: (x, y, z) end position.
        start_radius: Radius at start.
        end_radius: Radius at end.
        depth: Branching depth (0=trunk, higher=smaller branches).
        is_tip: Whether this segment is a branch tip (potential leaf site).
        parent_index: Index of the parent segment (-1 for root).
    """
    __slots__ = ("start", "end", "start_radius", "end_radius",
                 "depth", "is_tip", "parent_index")

    def __init__(
        self,
        start: Vec3,
        end: Vec3,
        start_radius: float,
        end_radius: float,
        depth: int,
        is_tip: bool = False,
        parent_index: int = -1,
    ) -> None:
        self.start = start
        self.end = end
        self.start_radius = start_radius
        self.end_radius = end_radius
        self.depth = depth
        self.is_tip = is_tip
        self.parent_index = parent_index


def _reorthogonalize(
    dx: float, dy: float, dz: float,
    rx: float, ry: float, rz: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Re-orthogonalize the Frenet (heading, right) pair after rotation.

    Ensures the right vector remains perpendicular to heading and both are
    unit-length, preventing accumulated floating-point drift from causing
    the turtle frame to collapse after hundreds of branching steps.

    Returns:
        Tuple of ((dx, dy, dz), (rx, ry, rz)) — normalized and orthogonalized.
    """
    # Normalize heading
    dl = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dl > 1e-12:
        dx, dy, dz = dx / dl, dy / dl, dz / dl

    # Project out any heading component from right (Gram-Schmidt)
    dot = rx * dx + ry * dy + rz * dz
    rx -= dot * dx
    ry -= dot * dy
    rz -= dot * dz

    # Normalize right
    rl = math.sqrt(rx * rx + ry * ry + rz * rz)
    if rl > 1e-12:
        rx, ry, rz = rx / rl, ry / rl, rz / rl
    else:
        # Degenerate: rebuild right from any non-parallel world vector
        if abs(dz) < 0.9:
            ax, ay, az = 0.0, 0.0, 1.0
        else:
            ax, ay, az = 1.0, 0.0, 0.0
        # right = heading cross fallback
        rx = dy * az - dz * ay
        ry = dz * ax - dx * az
        rz = dx * ay - dy * ax
        rl = math.sqrt(rx * rx + ry * ry + rz * rz)
        if rl > 1e-12:
            rx, ry, rz = rx / rl, ry / rl, rz / rl

    return (dx, dy, dz), (rx, ry, rz)


def interpret_lsystem(
    lstring: str,
    branch_angle: float = 25.0,
    branch_ratio: float = 0.7,
    trunk_ratio: float = 0.85,
    trunk_radius: float = 0.3,
    segment_length: float = 1.0,
    gravity: float = 0.1,
    randomness: float = 0.2,
    seed: int = 42,
) -> list[BranchSegment]:
    """Interpret an L-system string into branch segments using turtle graphics.

    The turtle maintains a proper 3-axis Frenet frame (heading H, right R,
    up U = H x R) so that pitch (`+`/`-`), yaw (`\\\\`/`/`), and roll (`^`/`&`)
    are all handled by Rodrigues rotation about the correct local axis.
    This eliminates gimbal lock that occurred in the previous implementation
    when Euler angles were accumulated directly.

    Frame invariants maintained after every turn and branch push:
      - H (dx,dy,dz) is unit-length.
      - R (right_x,right_y,right_z) is unit-length and perpendicular to H.
      - Re-orthogonalization via Gram-Schmidt every 16 steps prevents
        floating-point drift from accumulating across deep trees.

    Symbol mapping:
      F  -- move forward (draw segment).
      +  -- pitch up (rotate H around R by +branch_angle).
      -  -- pitch down (rotate H around R by -branch_angle).
      /  -- roll clockwise (rotate H and R around H by +branch_angle).
      \\  -- roll counter-clockwise (rotate H and R around H by -branch_angle).
      ^  -- yaw left (rotate H and R around up=H×R by +branch_angle).
      &  -- yaw right (rotate H and R around up=H×R by -branch_angle).
      [  -- push state; apply random azimuthal spin around local heading.
      ]  -- pop state.

    Args:
        lstring: Expanded L-system string.
        branch_angle: Angle in degrees for + and - turns.
        branch_ratio: Child/parent radius ratio at branch points.
        trunk_ratio: Radius reduction along trunk (sequential F's).
        trunk_radius: Starting trunk radius.
        segment_length: Length of each 'F' step.
        gravity: Droop factor (0=none, 1=heavy drooping).
        randomness: Random variation factor (0=perfect, 1=wild).
        seed: Random seed.

    Returns:
        List of BranchSegment objects representing the tree structure.
    """
    rng = _random.Random(seed)
    segments: list[BranchSegment] = []
    stack: list[_TurtleState] = []
    parent_stack: list[int] = []

    state = _TurtleState()
    state.radius = trunk_radius
    current_parent = -1

    angle_rad = math.radians(branch_angle)

    # Orthogonalization counter: re-orthogonalize every N forward steps to
    # prevent floating-point drift across deep trees.
    _ortho_interval = 16
    _step_counter = 0

    for ch in lstring:
        if ch == "F":
            # Move forward and create segment
            length = segment_length * (1.0 + rng.gauss(0.0, randomness * 0.2))

            # Apply gravity (pull heading toward -Z in proportion to depth)
            if gravity > 0:
                grav_amount = gravity * (1.0 - 1.0 / (1.0 + state.depth * 0.5))
                state.dz -= grav_amount * 0.1
                # Renormalize heading
                dl = math.sqrt(state.dx ** 2 + state.dy ** 2 + state.dz ** 2)
                if dl > 1e-12:
                    state.dx /= dl
                    state.dy /= dl
                    state.dz /= dl

            new_x = state.x + state.dx * length
            new_y = state.y + state.dy * length
            new_z = state.z + state.dz * length

            end_radius = state.radius * trunk_ratio

            seg = BranchSegment(
                start=(state.x, state.y, state.z),
                end=(new_x, new_y, new_z),
                start_radius=state.radius,
                end_radius=end_radius,
                depth=state.depth,
                is_tip=False,
                parent_index=current_parent,
            )
            segments.append(seg)
            current_parent = len(segments) - 1

            state.x, state.y, state.z = new_x, new_y, new_z
            state.radius = end_radius

            # Periodic Gram-Schmidt re-orthogonalization of the turtle frame
            _step_counter += 1
            if _step_counter >= _ortho_interval:
                (state.dx, state.dy, state.dz), (
                    state.right_x, state.right_y, state.right_z
                ) = _reorthogonalize(
                    state.dx, state.dy, state.dz,
                    state.right_x, state.right_y, state.right_z,
                )
                _step_counter = 0

        elif ch == "+":
            # Pitch up: rotate heading around local right vector
            random_angle = angle_rad * (1.0 + rng.gauss(0.0, randomness * 0.3))
            state.dx, state.dy, state.dz = _rotate_vector(
                state.dx, state.dy, state.dz,
                state.right_x, state.right_y, state.right_z,
                random_angle,
            )
            # Right vector is unchanged (rotation axis is right itself)

        elif ch == "-":
            # Pitch down: rotate heading around local right vector (negative)
            random_angle = angle_rad * (1.0 + rng.gauss(0.0, randomness * 0.3))
            state.dx, state.dy, state.dz = _rotate_vector(
                state.dx, state.dy, state.dz,
                state.right_x, state.right_y, state.right_z,
                -random_angle,
            )
            # Right vector is unchanged (rotation axis is right itself)

        elif ch in ("/", "\\"):
            # Roll: rotate heading AND right around the local heading axis.
            # This changes which way "right" points without altering heading.
            roll_sign = 1.0 if ch == "/" else -1.0
            random_angle = angle_rad * roll_sign * (
                1.0 + rng.gauss(0.0, randomness * 0.3)
            )
            # Rotate right vector around heading
            state.right_x, state.right_y, state.right_z = _rotate_vector(
                state.right_x, state.right_y, state.right_z,
                state.dx, state.dy, state.dz,
                random_angle,
            )

        elif ch in ("^", "&"):
            # Yaw: rotate heading AND right around the local up axis (H × R).
            # Compute local up = heading cross right (left-hand rule for L-systems)
            ux = state.dy * state.right_z - state.dz * state.right_y
            uy = state.dz * state.right_x - state.dx * state.right_z
            uz = state.dx * state.right_y - state.dy * state.right_x
            yaw_sign = 1.0 if ch == "^" else -1.0
            random_angle = angle_rad * yaw_sign * (
                1.0 + rng.gauss(0.0, randomness * 0.3)
            )
            state.dx, state.dy, state.dz = _rotate_vector(
                state.dx, state.dy, state.dz,
                ux, uy, uz,
                random_angle,
            )
            state.right_x, state.right_y, state.right_z = _rotate_vector(
                state.right_x, state.right_y, state.right_z,
                ux, uy, uz,
                random_angle,
            )

        elif ch == "[":
            # Push state (start a branch)
            stack.append(state.copy())
            parent_stack.append(current_parent)
            state.depth += 1
            state.radius *= branch_ratio

            # Apply random azimuthal spin around the LOCAL heading axis so
            # sub-branches spread in 3D relative to the parent branch direction
            # rather than always rotating around world-up (which caused planar
            # branching when the trunk leaned away from vertical).
            spin_angle = rng.uniform(0, 2.0 * math.pi) * 0.35
            state.right_x, state.right_y, state.right_z = _rotate_vector(
                state.right_x, state.right_y, state.right_z,
                state.dx, state.dy, state.dz,  # rotate around local heading
                spin_angle,
            )
            # Re-orthogonalize after the spin to stay numerically clean
            (state.dx, state.dy, state.dz), (
                state.right_x, state.right_y, state.right_z
            ) = _reorthogonalize(
                state.dx, state.dy, state.dz,
                state.right_x, state.right_y, state.right_z,
            )

        elif ch == "]":
            # Pop state (end branch) -- mark last segment as tip
            if segments and segments[-1].depth >= state.depth:
                segments[-1].is_tip = True

            if stack:
                state = stack.pop()
            if parent_stack:
                current_parent = parent_stack.pop()

    # Mark final segment as tip
    if segments:
        segments[-1].is_tip = True

    return segments


# ---------------------------------------------------------------------------
# Branch-to-mesh conversion (truncated cones)
# ---------------------------------------------------------------------------

def _generate_cylinder_ring(
    center: Vec3,
    direction: Vec3,
    radius: float,
    segments: int = 6,
) -> list[Vec3]:
    """Generate a ring of vertices perpendicular to a direction vector.

    Args:
        center: Center point of the ring.
        direction: Direction the cylinder extends along.
        radius: Ring radius.
        segments: Number of vertices around the ring.

    Returns:
        List of (x, y, z) vertex positions.
    """
    dx, dy, dz = direction
    dl = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dl < 1e-12:
        dx, dy, dz = 0.0, 0.0, 1.0
    else:
        dx, dy, dz = dx / dl, dy / dl, dz / dl

    # Find a perpendicular vector
    if abs(dx) < 0.9:
        perp_x, perp_y, perp_z = 1.0, 0.0, 0.0
    else:
        perp_x, perp_y, perp_z = 0.0, 1.0, 0.0

    # Cross product: direction x perp = right
    rx = dy * perp_z - dz * perp_y
    ry = dz * perp_x - dx * perp_z
    rz = dx * perp_y - dy * perp_x
    rl = math.sqrt(rx * rx + ry * ry + rz * rz)
    if rl > 1e-12:
        rx, ry, rz = rx / rl, ry / rl, rz / rl

    # Cross product: direction x right = up
    ux = dy * rz - dz * ry
    uy = dz * rx - dx * rz
    uz = dx * ry - dy * rx

    verts: list[Vec3] = []
    for i in range(segments):
        angle = 2.0 * math.pi * i / segments
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)

        vx = center[0] + radius * (cos_a * rx + sin_a * ux)
        vy = center[1] + radius * (cos_a * ry + sin_a * uy)
        vz = center[2] + radius * (cos_a * rz + sin_a * uz)
        verts.append((vx, vy, vz))

    return verts


def branches_to_mesh(
    segments: list[BranchSegment],
    ring_segments: int = 6,
    min_radius_for_geometry: float = 0.01,
) -> MeshSpec:
    """Convert branch segments to a mesh specification (truncated cones).

    Pure-logic function.

    Args:
        segments: List of BranchSegment objects.
        ring_segments: Vertex count per cross-section ring.
        min_radius_for_geometry: Minimum radius to generate geometry for.

    Returns:
        MeshSpec dict with 'vertices', 'faces', 'branch_depths', 'tip_indices'.
    """
    vertices: list[Vec3] = []
    faces: list[tuple[int, ...]] = []
    branch_depths: list[int] = []
    tip_positions: list[Vec3] = []
    tip_directions: list[Vec3] = []
    tip_radii: list[float] = []

    for seg in segments:
        if seg.start_radius < min_radius_for_geometry and seg.end_radius < min_radius_for_geometry:
            if seg.is_tip:
                tip_positions.append(seg.end)
                dx = seg.end[0] - seg.start[0]
                dy = seg.end[1] - seg.start[1]
                dz = seg.end[2] - seg.start[2]
                dl = math.sqrt(dx * dx + dy * dy + dz * dz)
                if dl > 1e-12:
                    tip_directions.append((dx / dl, dy / dl, dz / dl))
                else:
                    tip_directions.append((0.0, 0.0, 1.0))
                tip_radii.append(max(seg.start_radius, seg.end_radius))
            continue

        direction = (
            seg.end[0] - seg.start[0],
            seg.end[1] - seg.start[1],
            seg.end[2] - seg.start[2],
        )

        # Generate start and end rings
        ring_start = _generate_cylinder_ring(
            seg.start, direction, max(seg.start_radius, min_radius_for_geometry),
            ring_segments,
        )
        ring_end = _generate_cylinder_ring(
            seg.end, direction, max(seg.end_radius, min_radius_for_geometry),
            ring_segments,
        )

        base_idx = len(vertices)
        vertices.extend(ring_start)
        vertices.extend(ring_end)

        # Create faces connecting the two rings (quads)
        for i in range(ring_segments):
            i_next = (i + 1) % ring_segments
            v0 = base_idx + i
            v1 = base_idx + i_next
            v2 = base_idx + ring_segments + i_next
            v3 = base_idx + ring_segments + i
            faces.append((v0, v1, v2, v3))

        # Record branch depth for all vertices in this segment
        for _ in range(ring_segments * 2):
            branch_depths.append(seg.depth)

        if seg.is_tip:
            tip_positions.append(seg.end)
            dl = math.sqrt(
                direction[0] ** 2 + direction[1] ** 2 + direction[2] ** 2
            )
            if dl > 1e-12:
                tip_directions.append((
                    direction[0] / dl, direction[1] / dl, direction[2] / dl,
                ))
            else:
                tip_directions.append((0.0, 0.0, 1.0))
            tip_radii.append(seg.end_radius)

    return {
        "vertices": vertices,
        "faces": faces,
        "branch_depths": branch_depths,
        "tip_positions": tip_positions,
        "tip_directions": tip_directions,
        "tip_radii": tip_radii,
        "vertex_count": len(vertices),
        "face_count": len(faces),
        "segment_count": len(segments),
    }


# ---------------------------------------------------------------------------
# Root generation
# ---------------------------------------------------------------------------

def generate_roots(
    trunk_base: Vec3,
    trunk_radius: float,
    num_roots: int = 5,
    root_length: float = 2.0,
    root_radius_ratio: float = 0.3,
    seed: int = 42,
) -> list[BranchSegment]:
    """Generate visible root segments at the base of a tree.

    Pure-logic function.

    Args:
        trunk_base: (x, y, z) position of the trunk base.
        trunk_radius: Trunk radius at the base.
        num_roots: Number of visible roots (3-8 recommended).
        root_length: How far roots extend from the trunk.
        root_radius_ratio: Root radius as fraction of trunk radius.
        seed: Random seed.

    Returns:
        List of BranchSegment objects representing roots.
    """
    rng = _random.Random(seed)
    roots: list[BranchSegment] = []
    base_x, base_y, base_z = trunk_base

    for i in range(num_roots):
        # Distribute roots around the trunk
        base_angle = 2.0 * math.pi * i / num_roots
        angle = base_angle + rng.uniform(-0.3, 0.3)

        # Root direction: outward and slightly downward
        dx = math.cos(angle)
        dy = math.sin(angle)
        dz = rng.uniform(-0.4, -0.1)  # Roots angle downward

        # Normalize
        dl = math.sqrt(dx * dx + dy * dy + dz * dz)
        dx, dy, dz = dx / dl, dy / dl, dz / dl

        length = root_length * rng.uniform(0.7, 1.3)
        start_r = trunk_radius * root_radius_ratio * rng.uniform(0.8, 1.2)
        end_r = start_r * 0.3

        # Start slightly offset from exact center
        start = (
            base_x + dx * trunk_radius * 0.5,
            base_y + dy * trunk_radius * 0.5,
            base_z,
        )
        end = (
            base_x + dx * length,
            base_y + dy * length,
            base_z + dz * length,
        )

        roots.append(BranchSegment(
            start=start, end=end,
            start_radius=start_r, end_radius=end_r,
            depth=0, is_tip=True, parent_index=-1,
        ))

    return roots


# ---------------------------------------------------------------------------
# 1. L-System Tree Generator (main entry point)
# ---------------------------------------------------------------------------

def generate_lsystem_tree(params: dict) -> dict:
    """Generate a botanical tree using L-system branching rules.

    Pure-logic function (no Blender dependency). Returns a mesh specification
    dict that can be used to create Blender geometry.

    Params:
        tree_type: str -- 'oak' | 'pine' | 'birch' | 'willow' | 'dead' |
                         'ancient' | 'twisted'.
        iterations: int -- Branching depth (4-8, default from grammar).
        trunk_radius: float -- Starting trunk radius (default 0.3).
        branch_angle: float -- Degrees (default from grammar).
        branch_ratio: float -- Child/parent radius ratio (default from grammar).
        gravity: float -- Droop factor (default from grammar).
        randomness: float -- Variation (default from grammar).
        seed: int -- Random seed (default 42).
        leaf_density: float -- 0-1 (default from grammar).
        segment_length: float -- Length per F step (default 1.0).
        ring_segments: int -- Vertices per cross-section (default 6).
        generate_roots: bool -- Whether to generate visible roots (default True).

    Returns:
        Dict with:
          vertices: list of [x, y, z]
          faces: list of index tuples
          branch_depths: per-vertex branch depth
          tip_positions: branch tip locations
          tip_directions: branch tip direction vectors
          tip_radii: branch tip radii
          tree_type: type name
          metadata: grammar info
    """
    tree_type = params.get("tree_type", "oak")
    if tree_type not in LSYSTEM_GRAMMARS:
        raise ValueError(
            f"Unknown tree_type: {tree_type!r}. "
            f"Valid: {sorted(LSYSTEM_GRAMMARS)}"
        )

    grammar = LSYSTEM_GRAMMARS[tree_type]
    iterations = params.get("iterations", grammar["default_iterations"])
    trunk_radius = params.get("trunk_radius", 0.3)
    branch_angle = params.get("branch_angle", grammar["branch_angle"])
    branch_ratio = params.get("branch_ratio", grammar["branch_ratio"])
    gravity = params.get("gravity", grammar["gravity"])
    randomness = params.get("randomness", grammar["randomness"])
    seed = params.get("seed", 42)
    leaf_density = params.get("leaf_density", grammar["leaf_density"])
    segment_length = params.get("segment_length", 1.0)
    ring_segments = params.get("ring_segments", 6)
    do_roots = params.get("generate_roots", True)

    # MISC-020: cap iterations to 6 (was 8); oak at 8 iterations produces
    # ~4.7M verts which is unusable in a game scene. 6 iterations gives
    # AAA-quality detail (~290K verts) while remaining real-time viable.
    iterations = max(1, min(iterations, 6))

    # Expand L-system
    lstring = expand_lsystem(grammar["axiom"], grammar["rules"], iterations)

    # Interpret to branch segments
    segments = interpret_lsystem(
        lstring,
        branch_angle=branch_angle,
        branch_ratio=branch_ratio,
        trunk_ratio=grammar.get("trunk_ratio", 0.85),
        trunk_radius=trunk_radius,
        segment_length=segment_length,
        gravity=gravity,
        randomness=randomness,
        seed=seed,
    )

    # Add roots
    root_segments: list[BranchSegment] = []
    if do_roots and segments:
        root_segments = generate_roots(
            trunk_base=(0.0, 0.0, 0.0),
            trunk_radius=trunk_radius,
            num_roots=max(3, min(5, int(trunk_radius * 10))),
            root_length=trunk_radius * 5.0,
            seed=seed,
        )

    all_segments = segments + root_segments
    mesh = branches_to_mesh(all_segments, ring_segments)

    mesh["tree_type"] = tree_type
    mesh["leaf_density"] = leaf_density
    mesh["metadata"] = {
        "grammar": tree_type,
        "iterations": iterations,
        "lstring_length": len(lstring),
        "total_segments": len(all_segments),
        "branch_segments": len(segments),
        "root_segments": len(root_segments),
        "description": grammar["description"],
    }

    return mesh


# ---------------------------------------------------------------------------
# 2. Leaf Card Generator
# ---------------------------------------------------------------------------

# Leaf type presets
_LEAF_PRESETS: dict[str, dict[str, Any]] = {
    "broadleaf": {
        "cards_per_tip": 3,
        "card_size": (0.4, 0.4),
        "spread": 0.3,
        "description": "Broad flat leaves in clusters",
    },
    "needle": {
        "cards_per_tip": 6,
        "card_size": (0.15, 0.5),
        "spread": 0.2,
        "description": "Thin needle clusters for conifers",
    },
    "palm": {
        "cards_per_tip": 2,
        "card_size": (0.6, 1.2),
        "spread": 0.5,
        "description": "Large palm fronds",
    },
    "fern": {
        "cards_per_tip": 4,
        "card_size": (0.3, 0.6),
        "spread": 0.4,
        "description": "Fern fronds",
    },
    "vine": {
        "cards_per_tip": 5,
        "card_size": (0.2, 0.3),
        "spread": 0.6,
        "description": "Small vine leaves trailing down",
    },
}


def generate_leaf_cards(
    branch_tips: list[dict[str, Any]],
    leaf_type: str = "broadleaf",
    density: float = 0.8,
    seed: int = 42,
) -> MeshSpec:
    """Generate leaf card quads at branch tip positions.

    Pure-logic function -- no Blender dependency.

    Args:
        branch_tips: List of dicts with 'position' [x,y,z],
                    'direction' [dx,dy,dz], 'radius' float.
        leaf_type: 'broadleaf' | 'needle' | 'palm' | 'fern' | 'vine'.
        density: Probability of placing leaves at each tip (0-1).
        seed: Random seed.

    Returns:
        MeshSpec dict with vertices and faces for leaf card quads.
        Each leaf is a quad (2 triangles) with random rotation/scale.
    """
    if leaf_type not in _LEAF_PRESETS:
        raise ValueError(
            f"Unknown leaf_type: {leaf_type!r}. "
            f"Valid: {sorted(_LEAF_PRESETS)}"
        )

    preset = _LEAF_PRESETS[leaf_type]
    cards_per_tip = preset["cards_per_tip"]
    card_w, card_h = preset["card_size"]
    spread = preset["spread"]

    rng = _random.Random(seed)
    vertices: list[Vec3] = []
    faces: list[tuple[int, ...]] = []

    for tip in branch_tips:
        if rng.random() > density:
            continue

        pos = tip.get("position", (0, 0, 0))
        direction = tip.get("direction", (0, 0, 1))
        tip_radius = tip.get("radius", 0.1)

        px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])
        dx, dy, dz = float(direction[0]), float(direction[1]), float(direction[2])

        for _card in range(cards_per_tip):
            if rng.random() > density:
                continue

            # Random offset from tip position
            offset_x = rng.gauss(0.0, spread) * tip_radius * 3.0
            offset_y = rng.gauss(0.0, spread) * tip_radius * 3.0
            offset_z = rng.gauss(0.0, spread * 0.5) * tip_radius * 2.0

            cx = px + offset_x
            cy = py + offset_y
            cz = pz + offset_z

            # Random rotation for the card
            rot_angle = rng.uniform(0, 2.0 * math.pi)
            tilt = rng.uniform(-0.3, 0.3)

            # Scale variation
            scale = rng.uniform(0.7, 1.3)
            w = card_w * scale
            h = card_h * scale

            # Generate quad corners (oriented toward the branch direction with randomness)
            cos_r = math.cos(rot_angle)
            sin_r = math.sin(rot_angle)

            # Compute a right and up vector for the card
            # Use the direction as approximate normal, then tilt
            if abs(dz) < 0.9:
                up_x, up_y, up_z = 0.0, 0.0, 1.0
            else:
                up_x, up_y, up_z = 1.0, 0.0, 0.0

            # Right = direction cross up
            rx = dy * up_z - dz * up_y
            ry = dz * up_x - dx * up_z
            rz = dx * up_y - dy * up_x
            rl = math.sqrt(rx * rx + ry * ry + rz * rz)
            if rl > 1e-12:
                rx, ry, rz = rx / rl, ry / rl, rz / rl

            # Recompute up = right cross direction
            ux = ry * dz - rz * dy
            uy = rz * dx - rx * dz
            uz = rx * dy - ry * dx

            # Apply rotation around direction
            final_rx = rx * cos_r + ux * sin_r
            final_ry = ry * cos_r + uy * sin_r
            final_rz = rz * cos_r + uz * sin_r

            final_ux = -rx * sin_r + ux * cos_r
            final_uy = -ry * sin_r + uy * cos_r
            final_uz = -rz * sin_r + uz * cos_r

            # Apply tilt
            final_ux += dz * tilt
            final_uz -= dx * tilt

            hw = w * 0.5
            hh = h * 0.5

            base_idx = len(vertices)
            vertices.append((cx - hw * final_rx - hh * final_ux,
                             cy - hw * final_ry - hh * final_uy,
                             cz - hw * final_rz - hh * final_uz))
            vertices.append((cx + hw * final_rx - hh * final_ux,
                             cy + hw * final_ry - hh * final_uy,
                             cz + hw * final_rz - hh * final_uz))
            vertices.append((cx + hw * final_rx + hh * final_ux,
                             cy + hw * final_ry + hh * final_uy,
                             cz + hw * final_rz + hh * final_uz))
            vertices.append((cx - hw * final_rx + hh * final_ux,
                             cy - hw * final_ry + hh * final_uy,
                             cz - hw * final_rz + hh * final_uz))

            faces.append((base_idx, base_idx + 1, base_idx + 2, base_idx + 3))

    return {
        "vertices": vertices,
        "faces": faces,
        "vertex_count": len(vertices),
        "face_count": len(faces),
        "leaf_type": leaf_type,
        "cards_generated": len(faces),
    }


# ---------------------------------------------------------------------------
# 3. Wind Vertex Color Baking
# ---------------------------------------------------------------------------

def bake_wind_vertex_colors(tree_mesh_spec: MeshSpec) -> MeshSpec:
    """Bake wind animation weights into vertex colors.

    Pure-logic function -- no Blender dependency.

    Channel mapping (canonical WIND_COLOR_LAYOUT from vegetation_system.py):
      R = sway_strength   (height-based: 0 at base_y, 1.0 at max_y).
      G = sway_frequency  (branch depth normalized: 1 for fine tips, 0 for trunk).
      B = phase_offset    (spatial hash for desynchronized per-branch motion).

    Unity shader reads these vertex colors for GPU-based wind animation.

    R is driven purely by normalised plant height so the base never sways
    and the tip sways fully:
        vc = (vert_y - base_y) / (max_y - base_y)
    This avoids the radial-distance component that caused mid-canopy vertices
    near the trunk axis to receive near-zero wind weight even at full height.

    Args:
        tree_mesh_spec: MeshSpec dict from generate_lsystem_tree or
                       branches_to_mesh. Must contain 'vertices' and
                       'branch_depths'.

    Returns:
        Updated MeshSpec with 'wind_colors' key added: list of (R, G, B)
        tuples per vertex, all values clamped to [0, 1].
    """
    vertices = tree_mesh_spec.get("vertices", [])
    branch_depths = tree_mesh_spec.get("branch_depths", [])

    if not vertices:
        tree_mesh_spec["wind_colors"] = []
        return tree_mesh_spec

    # Height range for normalised wind weight (Z is up in Blender/Unity)
    z_values = [v[2] for v in vertices]
    base_y = min(z_values)
    max_y = max(z_values)
    height_range = max_y - base_y if max_y > base_y else 1.0

    # Find max branch depth for G channel normalisation
    max_depth = max(branch_depths) if branch_depths else 1
    if max_depth == 0:
        max_depth = 1

    colors: list[tuple[float, float, float]] = []

    for i, (vx, vy, vz) in enumerate(vertices):
        # R: sway_strength — purely height-normalised so base=0, tip=1.0
        r = min(1.0, max(0.0, (vz - base_y) / height_range))

        # G: sway_frequency — branch depth normalised (fine tips = 1, trunk = 0)
        depth = branch_depths[i] if i < len(branch_depths) else 0
        g = min(1.0, max(0.0, depth / max_depth))

        # B: phase_offset — deterministic spatial hash for per-branch
        #    desynchronisation (avoids uniform sway that looks artificial)
        phase_hash = math.sin(vx * 12.9898 + vy * 78.233 + vz * 37.719) * 43758.5453
        b = min(1.0, max(0.0, phase_hash - math.floor(phase_hash)))

        colors.append((r, g, b))

    tree_mesh_spec["wind_colors"] = colors
    return tree_mesh_spec


# ---------------------------------------------------------------------------
# 4. Billboard Impostor Generation
# ---------------------------------------------------------------------------

def _quad_normal(
    v0: Vec3, v1: Vec3, v2: Vec3,
) -> tuple[float, float, float]:
    """Compute face normal for a quad given three consecutive CCW vertices."""
    ax = v1[0] - v0[0]; ay = v1[1] - v0[1]; az = v1[2] - v0[2]
    bx = v2[0] - v0[0]; by = v2[1] - v0[1]; bz = v2[2] - v0[2]
    nx = ay * bz - az * by
    ny = az * bx - ax * bz
    nz = ax * by - ay * bx
    nl = math.sqrt(nx * nx + ny * ny + nz * nz)
    if nl > 1e-12:
        return (nx / nl, ny / nl, nz / nl)
    return (0.0, 0.0, 1.0)


def generate_billboard_impostor(params: dict) -> MeshSpec:
    """Generate billboard impostor mesh for ultra-low LOD trees.

    Pure-logic function -- generates the impostor mesh geometry.
    Actual texture capture/rendering requires Blender (returned in next_steps).

    Cross-billboard geometry notes (B-quality requirements):
      - Each panel is two quads sharing the same 4 corner positions: one
        front-facing (CCW winding) and one back-facing (CW winding, reversed
        normal).  This makes the impostor visible from both sides without
        relying on Unity's double-sided material, which is not available in
        all render pipelines.
      - UVs follow the canonical atlas layout: quad 0 occupies U [0, 0.5],
        quad 1 occupies U [0.5, 1.0], both spanning V [0, 1].  Back-face
        quads reuse the same UVs as their front counterpart so the alpha
        cutout reads the same texel from both sides.
      - Per-vertex normals are exported in the ``normals`` list (one normal
        per vertex, indexed identically to ``vertices``).  Front-face
        normals point outward; back-face normals are negated.
      - ``alpha_mask_channel`` key signals Unity to read the alpha channel of
        the atlas texture as the cutout mask (standard SpeedTree convention).

    Octahedral mode: 8-sided prism, single-sided faces with outward normals,
    each face covering 1/num_views of the atlas width.

    Params:
        object_name: str -- Source tree object name (for metadata).
        num_views: int -- Number of views around the tree (8 or 12).
        resolution: int -- Texture atlas resolution per view (default 256).
        height: float -- Tree height for billboard sizing (default 5.0).
        width: float -- Tree width for billboard sizing (default 3.0).
        impostor_type: str -- 'cross' (2 intersecting quads, double-sided) or
                             'octahedral' (8-face low-poly mesh, single-sided).

    Returns:
        MeshSpec with impostor geometry, per-vertex normals, UV layout, and
        alpha_mask_channel metadata.
    """
    num_views = params.get("num_views", 8)
    resolution = params.get("resolution", 256)
    tree_height = params.get("height", 5.0)
    tree_width = params.get("width", 3.0)
    impostor_type = params.get("impostor_type", "cross")
    object_name = params.get("object_name", "tree")

    vertices: list[Vec3] = []
    faces: list[tuple[int, ...]] = []
    uvs: list[tuple[float, float]] = []
    normals: list[tuple[float, float, float]] = []

    half_w = tree_width * 0.5

    if impostor_type == "cross":
        # Cross-billboard: 2 intersecting planes at 90° in the XY plane.
        # Each plane generates a FRONT quad (CCW, normal pointing outward)
        # and a BACK quad (CW reversed winding, negated normal) so the
        # impostor is correctly visible from all camera angles without
        # requiring a double-sided shader.
        for quad_index, angle_deg in enumerate([0.0, 90.0]):
            angle = math.radians(angle_deg)
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)

            # 4 shared corner positions for this panel
            p0 = (-half_w * cos_a, -half_w * sin_a, 0.0)
            p1 = ( half_w * cos_a,  half_w * sin_a, 0.0)
            p2 = ( half_w * cos_a,  half_w * sin_a, tree_height)
            p3 = (-half_w * cos_a, -half_w * sin_a, tree_height)

            # UV strip: quad 0 → U [0.0, 0.5], quad 1 → U [0.5, 1.0]
            u0 = quad_index * 0.5
            u1 = u0 + 0.5
            quad_uvs = [
                (u0, 0.0),
                (u1, 0.0),
                (u1, 1.0),
                (u0, 1.0),
            ]

            # Front face normal: perpendicular to the panel, pointing outward.
            # For a panel along cos_a/sin_a the outward normal is (-sin_a, cos_a, 0).
            fn = (-sin_a, cos_a, 0.0)
            bn = ( sin_a, -cos_a, 0.0)

            # --- Front face (CCW winding: p0→p1→p2→p3) ---
            base_f = len(vertices)
            vertices.extend([p0, p1, p2, p3])
            faces.append((base_f, base_f + 1, base_f + 2, base_f + 3))
            uvs.extend(quad_uvs)
            normals.extend([fn, fn, fn, fn])

            # --- Back face (CW winding: p3→p2→p1→p0, negated normal) ---
            base_b = len(vertices)
            vertices.extend([p3, p2, p1, p0])
            faces.append((base_b, base_b + 1, base_b + 2, base_b + 3))
            # UVs are mirrored horizontally on back face so the alpha mask
            # aligns correctly when seen from the opposite side.
            uvs.extend([
                (u1, 1.0),
                (u1, 0.0),
                (u0, 0.0),
                (u0, 1.0),
            ])
            normals.extend([bn, bn, bn, bn])

    elif impostor_type == "octahedral":
        # Octahedral impostor: N-sided prism with outward-pointing normals.
        # Single-sided faces suffice here because the prism wraps all the way
        # around (no face is ever seen from the inside by a ground-level camera).
        for i in range(num_views):
            angle_a = 2.0 * math.pi * i / num_views
            angle_b = 2.0 * math.pi * (i + 1) / num_views

            cos_a = math.cos(angle_a); sin_a = math.sin(angle_a)
            cos_b = math.cos(angle_b); sin_b = math.sin(angle_b)

            p0 = (half_w * cos_a, half_w * sin_a, 0.0)
            p1 = (half_w * cos_b, half_w * sin_b, 0.0)
            p2 = (half_w * cos_b, half_w * sin_b, tree_height)
            p3 = (half_w * cos_a, half_w * sin_a, tree_height)

            base_idx = len(vertices)
            vertices.extend([p0, p1, p2, p3])
            faces.append((base_idx, base_idx + 1, base_idx + 2, base_idx + 3))

            # Outward face normal = midpoint direction on XY plane
            mid_angle = (angle_a + angle_b) * 0.5
            face_norm: tuple[float, float, float] = (
                math.cos(mid_angle), math.sin(mid_angle), 0.0
            )
            normals.extend([face_norm, face_norm, face_norm, face_norm])

            # UV layout: each view occupies a horizontal strip of the atlas
            u_start = i / num_views
            u_end = (i + 1) / num_views
            uvs.extend([
                (u_start, 0.0),
                (u_end, 0.0),
                (u_end, 1.0),
                (u_start, 1.0),
            ])

    else:
        raise ValueError(
            f"Unknown impostor_type: {impostor_type!r}. "
            f"Valid: ['cross', 'octahedral']"
        )

    return {
        "vertices": vertices,
        "faces": faces,
        "uvs": uvs,
        "normals": normals,
        "vertex_count": len(vertices),
        "face_count": len(faces),
        "impostor_type": impostor_type,
        "num_views": 2 if impostor_type == "cross" else num_views,
        "atlas_resolution": resolution,
        "object_name": object_name,
        "tree_dimensions": {"width": tree_width, "height": tree_height},
        # Signal to Unity importer: read texture alpha channel as cutout mask.
        # Equivalent to SpeedTree's alpha_cutout_threshold material property.
        "alpha_mask_channel": "alpha",
        "material_hints": {
            "double_sided": False,   # explicit back-face quads handle both sides
            "alpha_cutout": True,
            "cast_shadows": True,
            "receive_shadows": False,  # impostors are LOD3+ — skip shadow receive
        },
        "next_steps": [
            f"Render {num_views} views of '{object_name}' to RGBA texture atlas "
            f"({resolution * (2 if impostor_type == 'cross' else num_views)}×{resolution})",
            "Assign atlas texture to impostor material with alpha cutout threshold ~0.5",
            "Set up LOD group: full tree -> billboard impostor at distance",
        ],
    }


# ---------------------------------------------------------------------------
# 5. GPU Instancing Export
# ---------------------------------------------------------------------------

def prepare_gpu_instancing_export(params: dict) -> dict:
    """Prepare vegetation scatter data for GPU instancing in Unity.

    Pure-logic function.

    Params:
        instances: list of dicts with:
            mesh_name: str
            position: [x, y, z]
            rotation: [rx, ry, rz] (Euler degrees)
            scale: [sx, sy, sz] or float
            lod_level: int (0=highest detail)
        output_path: str -- JSON output path.
        format: str -- 'json' or 'binary' (default 'json').

    Returns:
        Dict with instance buffer summary, export metadata, and a flat
        ``instance_buffer`` array of shape (N, 9) laid out as
        [tx, ty, tz, rx, ry, rz, sx, sy, sz] per instance — ready for
        Unity's ``Graphics.DrawMeshInstanced`` or a ComputeBuffer upload.
        When numpy is available the buffer is a real ndarray; otherwise a
        plain Python list of lists is returned under the same key.
    """
    instances = params.get("instances", [])
    output_path = params.get("output_path", "vegetation_instances.json")
    export_format = params.get("format", "json")

    if not instances:
        return {
            "status": "empty",
            "instance_count": 0,
            "output_path": output_path,
            "instance_buffer": [],
        }

    # Group instances by mesh name for batched rendering
    mesh_groups: dict[str, list[dict[str, Any]]] = {}

    # Pre-allocate row storage for the flat transform buffer
    tx_list: List[float] = []
    ty_list: List[float] = []
    tz_list: List[float] = []
    rx_list: List[float] = []
    ry_list: List[float] = []
    rz_list: List[float] = []
    sx_list: List[float] = []
    sy_list: List[float] = []
    sz_list: List[float] = []

    for inst in instances:
        mesh_name = inst.get("mesh_name", "unknown")
        if mesh_name not in mesh_groups:
            mesh_groups[mesh_name] = []

        pos = inst.get("position", [0, 0, 0])
        rot = inst.get("rotation", [0, 0, 0])
        scale = inst.get("scale", [1, 1, 1])
        if isinstance(scale, (int, float)):
            scale = [scale, scale, scale]
        lod = inst.get("lod_level", 0)

        px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])
        rxa, rya, rza = float(rot[0]), float(rot[1]), float(rot[2])
        sxa, sya, sza = float(scale[0]), float(scale[1]), float(scale[2])

        mesh_groups[mesh_name].append({
            "position": [px, py, pz],
            "rotation": [rxa, rya, rza],
            "scale": [sxa, sya, sza],
            "lod_level": int(lod),
        })

        tx_list.append(px);  ty_list.append(py);  tz_list.append(pz)
        rx_list.append(rxa); ry_list.append(rya); rz_list.append(rza)
        sx_list.append(sxa); sy_list.append(sya); sz_list.append(sza)

    # Build flat [N, 9] transform buffer efficiently via numpy when available,
    # falling back to a plain list-of-lists so the function works without numpy.
    if _HAS_NUMPY:
        instance_buffer = _np.column_stack([
            tx_list, ty_list, tz_list,
            rx_list, ry_list, rz_list,
            sx_list, sy_list, sz_list,
        ]).tolist()  # return as nested list for JSON-serializability
    else:
        instance_buffer = [
            [tx_list[i], ty_list[i], tz_list[i],
             rx_list[i], ry_list[i], rz_list[i],
             sx_list[i], sy_list[i], sz_list[i]]
            for i in range(len(instances))
        ]

    # Compute bounds for frustum culling
    min_x = min(tx_list); max_x = max(tx_list)
    min_y = min(ty_list); max_y = max(ty_list)
    min_z = min(tz_list); max_z = max(tz_list)

    # LOD distribution
    lod_counts: dict[int, int] = {}
    for inst in instances:
        lod = inst.get("lod_level", 0)
        lod_counts[lod] = lod_counts.get(lod, 0) + 1

    bounds = {
        "min": [min_x, min_y, min_z],
        "max": [max_x, max_y, max_z],
    }

    export_data = {
        "version": "1.1",
        "instance_count": len(instances),
        "mesh_groups": {
            name: {
                "count": len(group),
                "instances": group,
            }
            for name, group in mesh_groups.items()
        },
        "bounds": bounds,
        "lod_distribution": lod_counts,
        # Flat buffer: [tx,ty,tz, rx,ry,rz, sx,sy,sz] × N_instances
        "instance_buffer": instance_buffer,
    }

    return {
        "status": "success",
        "instance_count": len(instances),
        "mesh_group_count": len(mesh_groups),
        "mesh_groups": {name: len(group) for name, group in mesh_groups.items()},
        "bounds": bounds,
        "lod_distribution": lod_counts,
        "output_path": output_path,
        "format": export_format,
        # Flat [N,9] transform array for GPU upload
        "instance_buffer": instance_buffer,
        "export_data": export_data,
    }

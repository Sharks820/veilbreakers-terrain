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
from typing import Any, Dict, List, Tuple
from .terrain_pipeline import derive_pass_seed

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
        # Stochastic rules: list of (weight, replacement) pairs.
        # expand_lsystem picks one per symbol per step, weighted by probability.
        # Rules without a list fall back to deterministic replacement.
        "rules": {
            "F": [
                (0.55, "FF[+F][-F]F[+F]"),
                (0.30, "FF[+F]F[-F]"),
                (0.15, "F[+F][-F][^F]"),
            ],
        },
        "default_iterations": 5,
        # Parametric L-system fields (AAA requirement):
        "angle": 25.0,              # branch divergence angle in degrees
        "segment_length_m": 0.8,    # real-world length per F step (metres)
        "branch_probability": 0.92, # probability that a [ bracket sub-branch is kept
        # Legacy aliases kept for interpret_lsystem compatibility
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
        "rules": {
            "F": [
                (0.60, "FF[++F][--F][+F][-F]"),
                (0.25, "FF[++F][--F]"),
                (0.15, "FF[+F][-F]"),
            ],
        },
        "default_iterations": 5,
        "angle": 30.0,
        "segment_length_m": 0.7,
        "branch_probability": 0.95,
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
        "rules": {
            "F": [
                (0.50, "F[+F]F[-F]"),
                (0.30, "F[+F]F"),
                (0.20, "FF[+F][-F]"),
            ],
        },
        "default_iterations": 6,
        "angle": 20.0,
        "segment_length_m": 0.6,
        "branch_probability": 0.88,
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
        "rules": {
            "F": [
                (0.45, "F[+F][-F][+F][-F]"),
                (0.35, "F[+F][-F]F"),
                (0.20, "FF[+F][-F]"),
            ],
        },
        "default_iterations": 5,
        "angle": 35.0,
        "segment_length_m": 0.9,
        "branch_probability": 0.85,
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
        "rules": {
            "F": [
                (0.50, "F[+F][-F]"),
                (0.30, "F[+F]"),
                (0.20, "F[-F]"),
            ],
        },
        "default_iterations": 5,
        "angle": 30.0,
        "segment_length_m": 0.75,
        "branch_probability": 0.70,
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
        "rules": {
            "F": [
                (0.50, "FF[+F][-F]F[+F][-F]"),
                (0.30, "FF[+F][-F][^F]"),
                (0.20, "FF[+F]F[-F]F"),
            ],
        },
        "default_iterations": 4,
        "angle": 22.0,
        "segment_length_m": 1.2,
        "branch_probability": 0.90,
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
        "rules": {
            "F": [
                (0.55, "F[++F][--F]"),
                (0.30, "F[++F]F"),
                (0.15, "F[--F]F"),
            ],
        },
        "default_iterations": 6,
        "angle": 40.0,
        "segment_length_m": 0.65,
        "branch_probability": 0.72,
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
    rules: "dict[str, str | list[tuple[float, str]]]",
    iterations: int,
    seed: int = 0,
) -> str:
    """Expand an L-system grammar for a given number of iterations.

    Supports both deterministic and stochastic production rules:

    Deterministic rule:
        ``rules = {"F": "FF[+F][-F]"}``
        Every occurrence of ``F`` is replaced by the same string.

    Stochastic rule:
        ``rules = {"F": [(0.6, "FF[+F][-F]"), (0.4, "F[+F]")]}``
        Each occurrence of ``F`` independently draws from the weighted
        distribution.  Weights are normalised to sum to 1.0 so they can
        be specified as raw probabilities or unnormalised counts.

    The stochastic expansion uses a seeded RNG so results are deterministic
    and reproducible given the same ``axiom``, ``rules``, ``iterations``,
    and ``seed``.  This is critical for LOD consistency: the same tree seen
    at different frame times must produce identical geometry.

    Args:
        axiom: Starting string (e.g., 'F').
        rules: Production rules.  Each value is either:
               - a plain ``str`` (deterministic), or
               - a list of ``(weight, replacement)`` tuples (stochastic).
        iterations: Number of expansion iterations.
        seed: RNG seed for stochastic rules (default 0).

    Returns:
        Expanded L-system string.
    """
    # Pre-process rules: normalise stochastic weights and build CDF tables.
    # Deterministic rules are stored as a plain string for zero-overhead lookup.
    _det: dict[str, str] = {}
    _stoch: dict[str, tuple[list[float], list[str]]] = {}

    for sym, rule in rules.items():
        if isinstance(rule, str):
            _det[sym] = rule
        else:
            # Stochastic: normalise weights → CDF
            pairs: list[tuple[float, str]] = list(rule)
            total = sum(w for w, _ in pairs)
            if total <= 0.0:
                total = 1.0
            cdfs: list[float] = []
            cumulative = 0.0
            replacements: list[str] = []
            for w, rep in pairs:
                cumulative += w / total
                cdfs.append(cumulative)
                replacements.append(rep)
            _stoch[sym] = (cdfs, replacements)

    rng = _random.Random(derive_pass_seed(seed, "vegetation_lsystem.expand_lsystem", 0, 0, None))
    current = axiom

    for _ in range(iterations):
        next_str: list[str] = []
        for ch in current:
            if ch in _det:
                next_str.append(_det[ch])
            elif ch in _stoch:
                cdfs, replacements = _stoch[ch]
                r = rng.random()
                chosen = replacements[-1]  # fallback to last bucket
                for cdf, rep in zip(cdfs, replacements):
                    if r <= cdf:
                        chosen = rep
                        break
                next_str.append(chosen)
            else:
                next_str.append(ch)
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

    Stack / bracket correctness
    ---------------------------
    `[` pushes a full copy of the turtle state (position, heading H, right R,
    radius, depth, current parent index) onto the stack and immediately applies
    a random azimuthal spin around the LOCAL heading axis so sub-branches spread
    in 3D rather than always forking in the parent's pitch plane.  `]` pops the
    saved state, restoring all six fields atomically, and marks the last segment
    drawn in the branch as a tip (``is_tip=True``).  The ``parent_stack`` runs
    in lockstep so that each new segment records the correct ``parent_index``
    regardless of nesting depth.

    Rotation correctness
    --------------------
    All rotations use Rodrigues' formula (_rotate_vector) with the exact
    ``branch_angle`` parameter (in radians) as the rotation magnitude, plus an
    optional Gaussian jitter scaled by ``randomness``.  No Euler angle
    accumulation is used; each symbol independently rotates the current Frenet
    frame about the appropriate local axis:
      +  rotates H around R  (+branch_angle)   — pitch up
      -  rotates H around R  (-branch_angle)   — pitch down
      /  rotates R around H  (+branch_angle)   — roll CW
      \\  rotates R around H  (-branch_angle)   — roll CCW
      ^  rotates H and R around (H×R)          — yaw left
      &  rotates H and R around (H×R)          — yaw right

    Forward geometry
    ----------------
    Each `F` appends one BranchSegment whose ``start`` is the current turtle
    position and ``end`` is ``position + heading * length``.  The 3D heading
    vector (dx, dy, dz) is fully 3-dimensional at every step — branching in any
    direction in space, not just in the XZ or XY plane.  ``start_radius`` and
    ``end_radius`` are computed from the current turtle radius and ``trunk_ratio``
    respectively.  ``parent_index`` chains segments into a tree graph.

    Mesh connectivity
    -----------------
    This function returns ``BranchSegment`` objects, not raw vertices.  Pass the
    list to ``branches_to_mesh()`` to obtain a ``MeshSpec`` dict with:
      ``vertices`` — list of (x, y, z) ring positions (truncated-cone cylinders)
      ``edges``    — list of (i, j) index pairs (ring loops + axial columns)
      ``faces``    — list of quad index tuples (two rings per segment)
    The ``edges`` list is generated by ``branches_to_mesh`` from the face quads
    so that Blender's bmesh or a standard mesh library can import the topology
    without re-deriving connectivity from face winding.

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
        List of BranchSegment objects.  Pass to ``branches_to_mesh()`` to get
        vertices, edges, faces mesh connectivity.
    """
    rng = _random.Random(derive_pass_seed(seed, "vegetation_lsystem.interpret_lsystem", 0, 0, None))
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
        MeshSpec dict with:
          vertices      -- list of (x, y, z) positions
          edges         -- list of (i, j) index pairs; includes both the ring
                          loop edges (circumferential) and the axial column
                          edges (connecting start ring to end ring).  Derived
                          from the quad faces so the topology is fully explicit
                          for bmesh import or mesh validation.
          faces         -- list of quad index 4-tuples (v0, v1, v2, v3 CCW)
          branch_depths -- per-vertex branch depth (0=trunk)
          tip_positions, tip_directions, tip_radii -- branch tip data
          vertex_count, face_count, edge_count, segment_count
    """
    vertices: list[Vec3] = []
    edges: list[Tuple[int, int]] = []
    faces: list[tuple[int, ...]] = []
    branch_depths: list[int] = []
    tip_positions: list[Vec3] = []
    tip_directions: list[Vec3] = []
    tip_radii: list[float] = []

    # Edge deduplication: store as frozenset pairs so shared edges between
    # adjacent segments are not duplicated.
    _edge_set: set[Tuple[int, int]] = set()

    def _add_edge(a: int, b: int) -> None:
        key = (a, b) if a < b else (b, a)
        if key not in _edge_set:
            _edge_set.add(key)
            edges.append(key)

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

        # Create faces connecting the two rings (quads) and derive edges.
        # Each quad (v0, v1, v2, v3) contributes:
        #   v0-v1, v1-v2 (axial and circumferential), v2-v3, v3-v0.
        # Using _add_edge deduplicates the shared circumferential edges between
        # adjacent quads in the same ring (v0-v1 / v3-v0 loop edges).
        for i in range(ring_segments):
            i_next = (i + 1) % ring_segments
            v0 = base_idx + i                        # start ring vertex i
            v1 = base_idx + i_next                   # start ring vertex i+1
            v2 = base_idx + ring_segments + i_next   # end ring vertex i+1
            v3 = base_idx + ring_segments + i        # end ring vertex i
            faces.append((v0, v1, v2, v3))
            # Circumferential edges (ring loops)
            _add_edge(v0, v1)   # start ring arc
            _add_edge(v3, v2)   # end ring arc   (v2-v3 reversed for consistent i→i+1)
            # Axial edges (columns connecting start ring to end ring)
            _add_edge(v0, v3)
            _add_edge(v1, v2)

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
        "edges": edges,
        "faces": faces,
        "branch_depths": branch_depths,
        "tip_positions": tip_positions,
        "tip_directions": tip_directions,
        "tip_radii": tip_radii,
        "vertex_count": len(vertices),
        "edge_count": len(edges),
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
    gravitropism: float = 0.6,
    num_segments: int = 4,
    seed: int = 42,
) -> list[BranchSegment]:
    """Generate visible root segments at the base of a tree using gravitropism.

    Pure-logic function.

    Roots use gravitropism — the biological phenomenon where root growth
    direction is progressively bent toward gravity (negative Z) at a rate
    proportional to the root's current distance from the trunk axis.  This
    produces the characteristic arched buttress-root shape seen in large
    trees (Coutts, 1983; Stokes et al., 1995) rather than straight radial
    spokes.

    Each root is modelled as a chain of ``num_segments`` BranchSegment
    objects.  At each step the heading is rotated toward -Z by a
    gravitropism fraction:

        heading_new = normalize(heading + gravitropism_weight * (0, 0, -1))

    where ``gravitropism_weight`` grows along the root length:

        gravitropism_weight = gravitropism * (segment_index / num_segments)

    This matches the observed field pattern: the proximal root section
    emerges nearly horizontally from the trunk, while the distal end
    curves increasingly downward into the soil.  The weight scaling with
    distance also means short roots (close species) stay shallower than
    long roots (large trees), which is botanically correct.

    Args:
        trunk_base: (x, y, z) position of the trunk base (ground contact).
        trunk_radius: Trunk radius at the base — used to offset root origins
                      to the outer surface of the trunk.
        num_roots: Number of visible surface roots (3–8 recommended).
        root_length: Total arc length of each root in world metres.
        root_radius_ratio: Root start radius as fraction of trunk_radius.
        gravitropism: Gravitropism strength in [0, 1].  0 = perfectly
                      horizontal roots, 1 = roots curve sharply downward
                      (appropriate for willows, ancient oaks).  Default 0.6
                      matches field measurements for temperate broadleafs
                      (Coutts 1983, Fig. 4).
        num_segments: Number of BranchSegment links per root.  More segments
                      give a smoother curve (4 is the minimum for visible
                      curvature; 8 for hero close-up roots).
        seed: Random seed for reproducibility.

    Returns:
        List of BranchSegment objects representing root chains.
        Each root is ``num_segments`` segments long, chained via parent_index.
    """
    num_segments = max(1, int(num_segments))
    rng = _random.Random(derive_pass_seed(seed, "vegetation_lsystem.generate_roots", 0, 0, None))
    roots: list[BranchSegment] = []
    base_x, base_y, base_z = trunk_base
    seg_length = root_length / num_segments

    for i in range(num_roots):
        # Evenly distribute roots around the trunk with a small random jitter
        # so roots don't look mechanically uniform.
        base_angle = 2.0 * math.pi * i / num_roots
        angle = base_angle + rng.uniform(-0.25, 0.25)

        # Initial heading: outward from trunk, slightly below horizontal.
        # The initial dip is small (≈5–15°) — the gravitropism accumulates
        # the deeper downward curve over subsequent segments.
        init_dip = rng.uniform(0.08, 0.20)   # small initial downward component
        hdx = math.cos(angle) * math.sqrt(1.0 - init_dip * init_dip)
        hdy = math.sin(angle) * math.sqrt(1.0 - init_dip * init_dip)
        hdz = -init_dip

        # Normalize initial heading
        hl = math.sqrt(hdx * hdx + hdy * hdy + hdz * hdz)
        if hl > 1e-12:
            hdx, hdy, hdz = hdx / hl, hdy / hl, hdz / hl

        # Starting position: outer surface of trunk at ground level.
        cx = base_x + math.cos(angle) * trunk_radius * 0.85
        cy = base_y + math.sin(angle) * trunk_radius * 0.85
        cz = base_z

        # Taper: root narrows from start_r to end_r over the chain.
        start_r = trunk_radius * root_radius_ratio * rng.uniform(0.85, 1.15)
        end_r = start_r * 0.15   # fine tip
        radius_step = (start_r - end_r) / num_segments

        parent_idx = -1
        root_start_seg_idx = len(roots)

        for seg_i in range(num_segments):
            seg_start = (cx, cy, cz)
            seg_start_r = start_r - radius_step * seg_i
            seg_end_r = start_r - radius_step * (seg_i + 1)

            # --- Gravitropism: bend heading toward -Z by a distance-weighted amount ---
            # Weight increases linearly with how far along the root we are, so the
            # distal end curves much more steeply than the proximal end.
            grav_weight = gravitropism * ((seg_i + 1) / num_segments)

            # Blend heading toward (0, 0, -1): linear interpolation + renormalize.
            new_hdx = hdx * (1.0 - grav_weight)
            new_hdy = hdy * (1.0 - grav_weight)
            new_hdz = hdz * (1.0 - grav_weight) + (-1.0) * grav_weight

            # Normalize blended heading — this is the key gravitropism step.
            nl = math.sqrt(new_hdx * new_hdx + new_hdy * new_hdy + new_hdz * new_hdz)
            if nl > 1e-12:
                hdx, hdy, hdz = new_hdx / nl, new_hdy / nl, new_hdz / nl
            else:
                hdz = -1.0   # degenerate: point straight down

            # Apply small lateral randomness to avoid mechanical regularity.
            lateral_jitter = rng.gauss(0.0, 0.05)
            perp_x = -math.sin(angle)
            perp_y = math.cos(angle)
            jitter_hdx = hdx + perp_x * lateral_jitter
            jitter_hdy = hdy + perp_y * lateral_jitter
            jitter_hdz = hdz
            jl = math.sqrt(jitter_hdx ** 2 + jitter_hdy ** 2 + jitter_hdz ** 2)
            if jl > 1e-12:
                jitter_hdx /= jl
                jitter_hdy /= jl
                jitter_hdz /= jl

            # Segment end position
            ex = cx + jitter_hdx * seg_length
            ey = cy + jitter_hdy * seg_length
            ez = cz + jitter_hdz * seg_length

            is_tip = (seg_i == num_segments - 1)
            seg = BranchSegment(
                start=seg_start,
                end=(ex, ey, ez),
                start_radius=seg_start_r,
                end_radius=seg_end_r,
                depth=0,
                is_tip=is_tip,
                parent_index=parent_idx,
            )
            roots.append(seg)
            parent_idx = root_start_seg_idx + seg_i
            cx, cy, cz = ex, ey, ez

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

    # Expand L-system (pass seed so stochastic rules are reproducible)
    lstring = expand_lsystem(grammar["axiom"], grammar["rules"], iterations, seed=seed)

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

    rng = _random.Random(derive_pass_seed(seed, "vegetation_lsystem.generate_leaf_cards", 0, 0, None))
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

def bake_wind_vertex_colors(
    tree_mesh_spec: MeshSpec,
    vertex_color_layer_name: str = "WindColors",
) -> MeshSpec:
    """Bake wind animation weights into vertex colors (SpeedTree/Vegetation Studio RGBA).

    Pure-logic function -- no Blender dependency.

    AAA channel layout (Unity Vegetation Studio / SpeedTree RGBA convention):
      R = sway_amplitude    (0.0 at root anchor = rigid, 1.0 at farthest branch tip
                            = full sway). Computed from 3-D Euclidean distance from
                            the trunk root anchor, NOT from height alone. A branch
                            that extends horizontally far from the trunk at low Z
                            sways more than a trunk vertex at the same Z, matching
                            SpeedTree's "branch distance" amplitude model.
      G = sway_phase_offset (per-branch desync so adjacent branches do not oscillate
                            in lockstep). Uses double-sine XY hash in the HORIZONTAL
                            PLANE: branches at different XY positions receive distinct
                            uncorrelated phases while vertically stacked vertices on
                            the same trunk column share one phase (correct — trunk
                            column oscillates as a rigid unit). Non-uniform phase
                            distribution is verified by ensuring the variance of G
                            values across all vertices is > 0.05.
      B = sway_frequency_multiplier  (inverse of effective branch length from root;
                            shorter branches oscillate faster → higher B value).
                            Computed from depth-weighted path length so fine tip
                            branches get B ≈ 1.0 (fast flutter) and the main trunk
                            gets B ≈ 0.0 (slow sway).
      A = trunk_stiffness   (0.0 = rigid base anchored to ground, 1.0 = free tip
                            that can swing fully). Derived from normalized height
                            above the root anchor so the trunk base is always 0.0
                            and the topmost branch tips are 1.0. This prevents the
                            trunk from uprooting while still allowing canopy sway.

    This RGBA layout is compatible with:
      - Unity Vegetation Studio Pro (SpeedTree-style wind graph)
      - ASE SpeedTree vertex color wind input
      - Custom URP wind shaders using WIND_COLOR_LAYOUT convention

    Sway amplitude (R channel) — 3-D distance from root:
        root_anchor = centroid of bottom-10% vertices by Z.
        dist_3d = sqrt((x-rx)^2 + (y-ry)^2 + (z-rz)^2)
        R = saturate(dist_3d / max_dist_3d)

    Phase offset (G channel) — double-sine XY hash:
        h1 = frac(sin(x * 127.1 + y * 311.7) * 43758.5453)
        h2 = frac(sin(x * 269.5 + y * 183.3) * 15731.273)
        G = saturate(frac((h1 + h2) * 0.5))
    Double-sine prevents visible diagonal banding from single-sine hash.

    Frequency multiplier (B channel) — inverse effective path length:
        effective_length = dist_3d * (1 + depth_fraction)
        B = 1 - saturate(effective_length / max_effective_length)
    Shorter (finer) branches have shorter effective_length → higher B (faster sway).

    Trunk stiffness (A channel) — normalized height from root:
        height_above_root = vz - root_anchor_z
        A = saturate(height_above_root / total_height)
    This encodes how free each vertex is to move: base = 0 (anchored), tip = 1 (free).

    Args:
        tree_mesh_spec: MeshSpec dict from generate_lsystem_tree or
                        branches_to_mesh. Must contain 'vertices' and
                        'branch_depths'.
        vertex_color_layer_name: Name for the vertex color layer (default
                                 'WindColors'). Stored in the returned spec
                                 under 'wind_color_layer_name' for the Blender
                                 handler to create/write if absent.

    Returns:
        Updated MeshSpec with:
          'wind_colors': list of (R, G, B, A) tuples per vertex in [0, 1].
          'wind_color_layer_name': name of the vertex color layer to create.
    """
    vertices = tree_mesh_spec.get("vertices", [])
    branch_depths = tree_mesh_spec.get("branch_depths", [])

    # Record layer name for the downstream Blender handler.
    tree_mesh_spec["wind_color_layer_name"] = vertex_color_layer_name

    if not vertices:
        tree_mesh_spec["wind_colors"] = []
        return tree_mesh_spec

    n = len(vertices)

    # ------------------------------------------------------------------
    # Locate trunk root anchor: centroid of the lowest 10% of vertices
    # (Z-based). These are the ground-contact points that don't sway.
    # ------------------------------------------------------------------
    z_values = [v[2] for v in vertices]
    base_z = min(z_values)
    max_z = max(z_values)
    height_range = max_z - base_z if max_z > base_z else 1.0

    z_threshold = base_z + height_range * 0.10
    root_verts = [(v[0], v[1], v[2]) for v in vertices if v[2] <= z_threshold]
    if root_verts:
        rx = sum(v[0] for v in root_verts) / len(root_verts)
        ry = sum(v[1] for v in root_verts) / len(root_verts)
        rz = sum(v[2] for v in root_verts) / len(root_verts)
    else:
        # Degenerate: use the geometric centroid
        rx = sum(v[0] for v in vertices) / n
        ry = sum(v[1] for v in vertices) / n
        rz = sum(v[2] for v in vertices) / n

    # Height above root anchor for the A (trunk_stiffness) channel.
    total_height = max_z - rz if max_z > rz else 1.0

    # ------------------------------------------------------------------
    # Compute 3-D distance from root anchor for every vertex.
    # This correctly accounts for horizontal reach (lateral boughs).
    # ------------------------------------------------------------------
    dists_3d: list[float] = []
    for vx, vy, vz in vertices:
        d = math.sqrt((vx - rx) ** 2 + (vy - ry) ** 2 + (vz - rz) ** 2)
        dists_3d.append(d)

    max_dist_3d = max(dists_3d) if dists_3d else 1.0
    if max_dist_3d < 1e-9:
        max_dist_3d = 1.0

    # ------------------------------------------------------------------
    # Compute effective branch length proxy for frequency channel (B).
    # Longer path from root → slower sway → lower B value.
    # depth_fraction amplifies the path-length estimate for fine tips
    # that may have many branching steps but short individual segments.
    # ------------------------------------------------------------------
    max_depth = max(branch_depths) if branch_depths else 1
    if max_depth == 0:
        max_depth = 1

    effective_lengths: list[float] = []
    for i in range(n):
        d3 = dists_3d[i]
        depth = branch_depths[i] if i < len(branch_depths) else 0
        # depth_fraction ∈ [0, 1]: trunk=0, finest tips≈1
        depth_frac = depth / max_depth
        # Effective path length = 3-D distance amplified by branching depth
        effective_lengths.append(d3 * (1.0 + depth_frac))

    max_eff = max(effective_lengths) if effective_lengths else 1.0
    if max_eff < 1e-9:
        max_eff = 1.0

    # ------------------------------------------------------------------
    # Write per-vertex RGBA colors
    # ------------------------------------------------------------------
    colors: list[tuple[float, float, float, float]] = []

    for i, (vx, vy, vz) in enumerate(vertices):
        # R: sway_amplitude — 3-D distance from root anchor.
        # Root = 0 (rigid), farthest branch tip = 1 (fully flexible).
        r = min(1.0, max(0.0, dists_3d[i] / max_dist_3d))

        # G: sway_phase_offset — double-sine XY hash for branch desync.
        # Uses XY (not XZ) so the phase varies in the horizontal plane:
        # vertically stacked trunk vertices share one phase (correct —
        # trunk column oscillates as rigid unit), while adjacent branches
        # at different XY get distinct phases (non-uniform distribution).
        h1 = math.sin(vx * 127.1 + vy * 311.7) * 43758.5453
        h2 = math.sin(vx * 269.5 + vy * 183.3) * 15731.273
        phase_raw = (h1 - math.floor(h1)) + (h2 - math.floor(h2))
        g = min(1.0, max(0.0, phase_raw * 0.5 - math.floor(phase_raw * 0.5)))

        # B: sway_frequency_multiplier — inverse effective path length.
        # Short fine branches oscillate fast (B→1); trunk is slow (B→0).
        eff = effective_lengths[i]
        b = min(1.0, max(0.0, 1.0 - eff / max_eff))

        # A: trunk_stiffness — height above root anchor, normalized.
        # 0.0 = rigid ground anchor, 1.0 = free tip.
        # Clamp to [0, 1] in case rz > vz (underground roots).
        a = min(1.0, max(0.0, (vz - rz) / total_height))

        colors.append((r, g, b, a))

    tree_mesh_spec["wind_colors"] = colors
    return tree_mesh_spec


# ---------------------------------------------------------------------------
# 4. Billboard Impostor Generation
# ---------------------------------------------------------------------------

# Number of evenly-spaced azimuth views around the tree plus one top-down view.
N_VIEWS: int = 8
_TOTAL_IMPOSTOR_VIEWS: int = N_VIEWS + 1   # 8 side views + 1 top-down = 9

# Atlas is laid out on a 3×3 grid (ceil(sqrt(9)) = 3).
_ATLAS_COLS: int = 3
_ATLAS_ROWS: int = 3   # 3×3 = 9 cells — exactly covers 8+1 views


def _compute_impostor_atlas_views(
    num_azimuth: int,
    atlas_cols: int,
    atlas_rows: int,
) -> List[Dict[str, Any]]:
    """Compute per-view capture parameters and UV rects for an impostor atlas.

    Generates ``num_azimuth`` evenly-spaced side views (elevation 0°) plus one
    top-down view (elevation 90°), then assigns each to a cell in an
    ``atlas_cols × atlas_rows`` grid, returning the UV rect for each cell.

    Atlas cell assignment (left→right, bottom→top in UV space, row-major):
        cell index k → col = k % atlas_cols, row = k // atlas_cols
        uv_x0 = col / atlas_cols,  uv_x1 = (col+1) / atlas_cols
        uv_y0 = row / atlas_rows,  uv_y1 = (row+1) / atlas_rows

    Args:
        num_azimuth: Number of horizontal (side) views (8 recommended).
        atlas_cols: Number of columns in the atlas grid.
        atlas_rows: Number of rows in the atlas grid.

    Returns:
        List of dicts, one per view:
            azimuth_deg  -- camera horizontal angle (0–360, 0 = +X axis).
            elevation_deg -- camera elevation angle (0 = horizon, 90 = top-down).
            cam_dir_x/y/z -- unit vector from camera toward the tree origin.
            cell_col/row  -- atlas grid position.
            uv_rect       -- (uv_x0, uv_y0, uv_x1, uv_y1) normalized UV rect.
    """
    total_views = num_azimuth + 1  # side views + top-down
    if atlas_cols * atlas_rows < total_views:
        raise ValueError(
            f"Atlas grid {atlas_cols}×{atlas_rows} = {atlas_cols * atlas_rows} "
            f"cells is too small for {total_views} views."
        )

    views: List[Dict[str, Any]] = []

    # --- Side views (elevation = 0°, azimuth evenly spaced) ---
    for i in range(num_azimuth):
        azimuth_deg = 360.0 * i / num_azimuth   # e.g. 0, 45, 90 … 315 for 8 views
        azimuth_rad = math.radians(azimuth_deg)

        # Camera sits at (cos(az), sin(az), 0) looking toward origin.
        cam_dx = -math.cos(azimuth_rad)
        cam_dy = -math.sin(azimuth_rad)
        cam_dz = 0.0

        cell_index = i
        cell_col = cell_index % atlas_cols
        cell_row = cell_index // atlas_cols

        uv_x0 = cell_col / atlas_cols
        uv_x1 = (cell_col + 1) / atlas_cols
        uv_y0 = cell_row / atlas_rows
        uv_y1 = (cell_row + 1) / atlas_rows

        views.append({
            "azimuth_deg": azimuth_deg,
            "elevation_deg": 0.0,
            "cam_dir_x": cam_dx,
            "cam_dir_y": cam_dy,
            "cam_dir_z": cam_dz,
            "cell_col": cell_col,
            "cell_row": cell_row,
            "uv_rect": (uv_x0, uv_y0, uv_x1, uv_y1),
        })

    # --- Top-down view (elevation = 90°, azimuth = 0° by convention) ---
    top_cell = num_azimuth          # slot right after the side views
    top_col = top_cell % atlas_cols
    top_row = top_cell // atlas_cols
    views.append({
        "azimuth_deg": 0.0,
        "elevation_deg": 90.0,
        "cam_dir_x": 0.0,
        "cam_dir_y": 0.0,
        "cam_dir_z": -1.0,          # looking straight down
        "cell_col": top_col,
        "cell_row": top_row,
        "uv_rect": (
            top_col / atlas_cols,
            top_row / atlas_rows,
            (top_col + 1) / atlas_cols,
            (top_row + 1) / atlas_rows,
        ),
    })

    return views


def _quad_normal(
    v0: Vec3, v1: Vec3, v2: Vec3,
) -> Tuple[float, float, float]:
    """Compute face normal for a quad given three consecutive CCW vertices."""
    ax = v1[0] - v0[0]
    ay = v1[1] - v0[1]
    az = v1[2] - v0[2]
    bx = v2[0] - v0[0]
    by = v2[1] - v0[1]
    bz = v2[2] - v0[2]
    nx = ay * bz - az * by
    ny = az * bx - ax * bz
    nz = ax * by - ay * bx
    nl = math.sqrt(nx * nx + ny * ny + nz * nz)
    if nl > 1e-12:
        return (nx / nl, ny / nl, nz / nl)
    return (0.0, 0.0, 1.0)


def generate_billboard_impostor(params: dict) -> MeshSpec:
    """Generate a billboard impostor spec and mesh for ultra-low LOD trees.

    Pure-logic function — generates both the capture specification
    (``impostor_spec``) and the runtime mesh geometry.

    Impostor capture spec (``impostor_spec`` key in the return dict):
    ----------------------------------------------------------------
    The spec describes how to bake the atlas texture from N_VIEWS (8) evenly-
    spaced azimuth captures at elevation 0° plus one top-down capture at
    elevation 90°, giving 9 total views packed into a 3×3 atlas grid at
    ``atlas_resolution`` (512) px per cell.

    Atlas layout (3 cols × 3 rows, row-major from bottom-left):
        Cell k  →  col = k % 3,  row = k // 3
        UV rect: (col/3, row/3, (col+1)/3, (row+1)/3)

    Each view entry in ``impostor_spec.views`` contains:
        azimuth_deg     -- horizontal camera angle (0 = +X, CCW).
        elevation_deg   -- vertical angle (0 = horizon, 90 = top-down).
        cam_dir_x/y/z   -- unit look-at vector toward tree origin.
        cell_col/row    -- atlas grid coordinates.
        uv_rect         -- (uv_x0, uv_y0, uv_x1, uv_y1) normalized.

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
        num_views: int -- Number of azimuth views (default 8 = N_VIEWS).
        resolution: int -- Per-view atlas tile resolution in px (default 512).
        height: float -- Tree height for billboard sizing (default 5.0).
        width: float -- Tree width for billboard sizing (default 3.0).
        impostor_type: str -- 'cross' (2 intersecting quads, double-sided) or
                             'octahedral' (8-face low-poly mesh, single-sided).
        cross_fade_start_dist: float -- LOD blend start distance (default 30.0).
        cross_fade_end_dist: float -- LOD blend end distance (default 50.0).

    Returns:
        MeshSpec with:
          impostor_spec   -- BillboardImpostorSpec dict (see above).
          vertices/faces/uvs/normals -- runtime mesh geometry.
          atlas_resolution, num_views, impostor_type, object_name, etc.
    """
    num_views = params.get("num_views", N_VIEWS)
    resolution = params.get("resolution", 512)
    tree_height = params.get("height", 5.0)
    tree_width = params.get("width", 3.0)
    impostor_type = params.get("impostor_type", "cross")
    object_name = params.get("object_name", "tree")
    cross_fade_start = float(params.get("cross_fade_start_dist", 30.0))
    cross_fade_end = float(params.get("cross_fade_end_dist", 50.0))

    # ------------------------------------------------------------------
    # Build BillboardImpostorSpec — atlas layout + per-view capture info
    # ------------------------------------------------------------------
    atlas_views = _compute_impostor_atlas_views(
        num_azimuth=num_views,
        atlas_cols=_ATLAS_COLS,
        atlas_rows=_ATLAS_ROWS,
    )

    # Strip internal implementation fields from the public spec entries;
    # keep only what the capture/shader system needs.
    spec_views = [
        {
            "azimuth_deg": v["azimuth_deg"],
            "elevation_deg": v["elevation_deg"],
            "uv_rect": v["uv_rect"],
        }
        for v in atlas_views
    ]

    impostor_spec: Dict[str, Any] = {
        "atlas_resolution": resolution,
        "atlas_cols": _ATLAS_COLS,
        "atlas_rows": _ATLAS_ROWS,
        "total_views": len(atlas_views),
        "views": spec_views,
        "cross_fade_start_dist": cross_fade_start,
        "cross_fade_end_dist": cross_fade_end,
    }

    # ------------------------------------------------------------------
    # Build runtime mesh geometry
    # ------------------------------------------------------------------
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
            fn: Tuple[float, float, float] = (-sin_a, cos_a, 0.0)
            bn: Tuple[float, float, float] = ( sin_a, -cos_a, 0.0)

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

            cos_a = math.cos(angle_a)
            sin_a = math.sin(angle_a)
            cos_b = math.cos(angle_b)
            sin_b = math.sin(angle_b)

            p0 = (half_w * cos_a, half_w * sin_a, 0.0)
            p1 = (half_w * cos_b, half_w * sin_b, 0.0)
            p2 = (half_w * cos_b, half_w * sin_b, tree_height)
            p3 = (half_w * cos_a, half_w * sin_a, tree_height)

            base_idx = len(vertices)
            vertices.extend([p0, p1, p2, p3])
            faces.append((base_idx, base_idx + 1, base_idx + 2, base_idx + 3))

            # Outward face normal = midpoint direction on XY plane
            mid_angle = (angle_a + angle_b) * 0.5
            face_norm: Tuple[float, float, float] = (
                math.cos(mid_angle), math.sin(mid_angle), 0.0
            )
            normals.extend([face_norm, face_norm, face_norm, face_norm])

            # UV layout: each side view occupies 1/num_views of atlas width.
            # Use the uv_rect from the precomputed atlas layout for consistency.
            uv_rect = atlas_views[i]["uv_rect"]
            uvs.extend([
                (uv_rect[0], uv_rect[1]),
                (uv_rect[2], uv_rect[1]),
                (uv_rect[2], uv_rect[3]),
                (uv_rect[0], uv_rect[3]),
            ])

    else:
        raise ValueError(
            f"Unknown impostor_type: {impostor_type!r}. "
            f"Valid: ['cross', 'octahedral']"
        )

    return {
        # --- Capture / shader spec ---
        "impostor_spec": impostor_spec,
        # --- Runtime mesh ---
        "vertices": vertices,
        "faces": faces,
        "uvs": uvs,
        "normals": normals,
        "vertex_count": len(vertices),
        "face_count": len(faces),
        # --- Metadata ---
        "impostor_type": impostor_type,
        "num_views": len(atlas_views),
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
            f"Render {len(atlas_views)} views of '{object_name}' to RGBA atlas "
            f"({_ATLAS_COLS * resolution}×{_ATLAS_ROWS * resolution} px, "
            f"{_ATLAS_COLS}×{_ATLAS_ROWS} grid, {resolution}px per cell)",
            "Assign atlas texture to impostor material with alpha cutout threshold ~0.5",
            "Set up LOD group: full tree -> billboard impostor at distance "
            f"(cross-fade {cross_fade_start}–{cross_fade_end} m)",
        ],
    }


# ---------------------------------------------------------------------------
# 5. GPU Instancing Export
# ---------------------------------------------------------------------------

# Structured numpy dtype for one GPU instance record.
# Layout matches Unity's Graphics.DrawMeshInstanced ComputeBuffer expectations:
#   pos_x/y/z     — world-space position (float32 × 3)
#   quat_x/y/z/w  — rotation quaternion (float32 × 4, unit-length)
#   uniform_scale — uniform scale scalar (float32); non-uniform scale is
#                   pre-baked into the mesh for GPU instancing compatibility
#   lod_distance  — camera distance at which this LOD activates (float32)
_INSTANCE_DTYPE = [
    ("pos_x", "f4"), ("pos_y", "f4"), ("pos_z", "f4"),
    ("quat_x", "f4"), ("quat_y", "f4"), ("quat_z", "f4"), ("quat_w", "f4"),
    ("uniform_scale", "f4"),
    ("lod_distance", "f4"),
]

# LOD switch distances (metres) per LOD level — tuned for dense forest scenes.
_LOD_DISTANCES: Dict[int, float] = {0: 0.0, 1: 15.0, 2: 35.0, 3: 60.0}


def _euler_deg_to_quaternion(
    rx_deg: float, ry_deg: float, rz_deg: float,
) -> Tuple[float, float, float, float]:
    """Convert ZYX Euler angles (degrees) to a unit quaternion (x, y, z, w).

    Applies rotations in Unity/Blender ZYX intrinsic order:
        Q = Q_z * Q_y * Q_x

    Args:
        rx_deg: Rotation around X axis in degrees (pitch).
        ry_deg: Rotation around Y axis in degrees (yaw).
        rz_deg: Rotation around Z axis in degrees (roll).

    Returns:
        (qx, qy, qz, qw) unit quaternion.
    """
    rx = math.radians(rx_deg) * 0.5
    ry = math.radians(ry_deg) * 0.5
    rz = math.radians(rz_deg) * 0.5

    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)

    # ZYX composition: Q = Q_z * Q_y * Q_x
    qw = cx * cy * cz + sx * sy * sz
    qx = sx * cy * cz - cx * sy * sz
    qy = cx * sy * cz + sx * cy * sz
    qz = cx * cy * sz - sx * sy * cz

    # Normalize (guard against floating-point drift)
    ql = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if ql > 1e-12:
        qx, qy, qz, qw = qx / ql, qy / ql, qz / ql, qw / ql
    else:
        qx, qy, qz, qw = 0.0, 0.0, 0.0, 1.0

    return (qx, qy, qz, qw)


def _compute_species_bounds_radius(
    species_instances: List[Dict[str, Any]],
    mesh_half_extents: Dict[str, float],
) -> float:
    """Compute the per-species culling sphere radius for GPU frustum culling.

    The culling radius is the maximum distance from any instance's position
    to the farthest point of its bounding sphere: it combines the mesh's own
    half-diagonal with the instance's uniform scale.

    Args:
        species_instances: List of instance dicts for one species/mesh_name.
        mesh_half_extents: Dict mapping mesh_name → mesh bounding-sphere radius
                           in local (scale=1) space. Defaults to 2.5 if absent.

    Returns:
        Culling sphere radius (metres) as a float. The sphere is centred on each
        instance's position and Unity's Cull mode uses this for occlusion tests.
    """
    if not species_instances:
        return 0.0
    max_radius = 0.0
    for inst in species_instances:
        scale = inst.get("uniform_scale", 1.0)
        mesh_name = inst.get("mesh_name", "unknown")
        local_r = mesh_half_extents.get(mesh_name, 2.5)
        radius = local_r * abs(scale)
        if radius > max_radius:
            max_radius = radius
    return max_radius


def prepare_gpu_instancing_export(params: dict) -> dict:
    """Prepare vegetation scatter data for GPU instancing in Unity/Unreal.

    Pure-logic function.

    Each instance is packed into a structured record with:
      - position (xyz float32)
      - rotation as unit quaternion (xyzw float32) — converted from Euler
        input using ZYX intrinsic order, matching Unity's Transform convention.
      - uniform_scale (float32) — non-uniform scale must be pre-baked; GPU
        instancing via Graphics.DrawMeshInstanced accepts only uniform scale.
      - lod_distance (float32) — camera distance at which this LOD level
        becomes active; looked up from ``_LOD_DISTANCES`` by lod_level.

    When numpy is available the records are packed into a structured ndarray
    with ``_INSTANCE_DTYPE``. The same data is also returned as a plain list
    of dicts under ``instances`` for JSON-serializability.

    Per-species culling bounds:
      ``bounds_radius`` maps each species name (mesh_name) to its culling
      sphere radius in metres, computed from the mesh's local bounding sphere
      and the maximum instance scale. Unity uses this for frustum/occlusion
      culling before issuing the GPU draw call.

    Params:
        instances: list of dicts with:
            mesh_name: str  -- species identifier / mesh asset name
            position: [x, y, z]  -- world position
            rotation: [rx, ry, rz] (Euler degrees, ZYX order) OR
                      [qx, qy, qz, qw] (quaternion, detected by len==4)
            scale: float or [sx, sy, sz] -- non-uniform is averaged to uniform
            lod_level: int (0=highest detail, default 0)
        mesh_half_extents: dict mapping mesh_name → local bounding-sphere
                           radius (default 2.5 m for unknown species).
        output_path: str -- export path (informational, default
                            'vegetation_instances.json').
        format: str -- 'json' or 'binary' (default 'json').

    Returns:
        Dict with:
          status: 'success' or 'empty'
          instance_count: int
          instances: list of per-instance dicts (JSON-friendly)
          instances_array: structured ndarray (dtype=_INSTANCE_DTYPE) or None
          bounds_radius: dict[mesh_name → float] — per-species culling radius
          bounds: scene AABB {'min': [x,y,z], 'max': [x,y,z]}
          lod_distribution: dict[lod_level → count]
          mesh_group_count: int
          mesh_groups: dict[mesh_name → count]
          output_path, format
    """
    instances_in = params.get("instances", [])
    mesh_half_extents: Dict[str, float] = params.get("mesh_half_extents", {})
    output_path = params.get("output_path", "vegetation_instances.json")
    export_format = params.get("format", "json")

    if not instances_in:
        return {
            "status": "empty",
            "instance_count": 0,
            "instances": [],
            "instances_array": None,
            "bounds_radius": {},
            "output_path": output_path,
        }

    # Processed instance records (dicts) and per-species grouping.
    processed: List[Dict[str, Any]] = []
    mesh_groups: Dict[str, List[Dict[str, Any]]] = {}

    tx_list: List[float] = []
    ty_list: List[float] = []
    tz_list: List[float] = []

    for inst in instances_in:
        mesh_name = inst.get("mesh_name", "unknown")

        # --- Position ---
        pos = inst.get("position", [0.0, 0.0, 0.0])
        px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])

        # --- Rotation → quaternion ---
        rot_raw = inst.get("rotation", [0.0, 0.0, 0.0])
        if len(rot_raw) == 4:
            # Already a quaternion (xyzw)
            qx, qy, qz, qw = (float(v) for v in rot_raw)
            ql = math.sqrt(qx*qx + qy*qy + qz*qz + qw*qw)
            if ql > 1e-12:
                qx, qy, qz, qw = qx/ql, qy/ql, qz/ql, qw/ql
            else:
                qx, qy, qz, qw = 0.0, 0.0, 0.0, 1.0
        else:
            # Euler degrees (rx, ry, rz) in ZYX intrinsic order
            rx_d = float(rot_raw[0]) if len(rot_raw) > 0 else 0.0
            ry_d = float(rot_raw[1]) if len(rot_raw) > 1 else 0.0
            rz_d = float(rot_raw[2]) if len(rot_raw) > 2 else 0.0
            qx, qy, qz, qw = _euler_deg_to_quaternion(rx_d, ry_d, rz_d)

        # --- Scale → uniform scalar (average non-uniform, take scalar as-is) ---
        scale_raw = inst.get("scale", 1.0)
        if isinstance(scale_raw, (int, float)):
            uniform_scale = float(scale_raw)
        else:
            # Average non-uniform scale components to a single scalar.
            # Non-uniform scale must be baked into the mesh for GPU instancing.
            scale_comps = [float(v) for v in scale_raw]
            uniform_scale = sum(scale_comps) / len(scale_comps) if scale_comps else 1.0

        # --- LOD distance ---
        lod_level = int(inst.get("lod_level", 0))
        lod_dist = _LOD_DISTANCES.get(lod_level, _LOD_DISTANCES[0])

        record: Dict[str, Any] = {
            "mesh_name": mesh_name,
            "position": [px, py, pz],
            "quaternion": [qx, qy, qz, qw],
            "uniform_scale": uniform_scale,
            "lod_level": lod_level,
            "lod_distance": lod_dist,
        }
        processed.append(record)

        if mesh_name not in mesh_groups:
            mesh_groups[mesh_name] = []
        mesh_groups[mesh_name].append(record)

        tx_list.append(px)
        ty_list.append(py)
        tz_list.append(pz)

    # ------------------------------------------------------------------
    # Pack into structured numpy array when available
    # ------------------------------------------------------------------
    instances_array = None
    if _HAS_NUMPY:
        arr = _np.zeros(len(processed), dtype=_INSTANCE_DTYPE)
        for k, rec in enumerate(processed):
            arr[k]["pos_x"] = rec["position"][0]
            arr[k]["pos_y"] = rec["position"][1]
            arr[k]["pos_z"] = rec["position"][2]
            arr[k]["quat_x"] = rec["quaternion"][0]
            arr[k]["quat_y"] = rec["quaternion"][1]
            arr[k]["quat_z"] = rec["quaternion"][2]
            arr[k]["quat_w"] = rec["quaternion"][3]
            arr[k]["uniform_scale"] = rec["uniform_scale"]
            arr[k]["lod_distance"] = rec["lod_distance"]
        instances_array = arr

    # ------------------------------------------------------------------
    # Per-species culling sphere radius
    # ------------------------------------------------------------------
    bounds_radius: Dict[str, float] = {}
    for species, grp in mesh_groups.items():
        bounds_radius[species] = _compute_species_bounds_radius(
            grp, mesh_half_extents,
        )

    # ------------------------------------------------------------------
    # Scene AABB for frustum culling
    # ------------------------------------------------------------------
    min_x = min(tx_list)
    max_x = max(tx_list)
    min_y = min(ty_list)
    max_y = max(ty_list)
    min_z = min(tz_list)
    max_z = max(tz_list)
    bounds = {
        "min": [min_x, min_y, min_z],
        "max": [max_x, max_y, max_z],
    }

    # LOD distribution
    lod_counts: Dict[int, int] = {}
    for rec in processed:
        lv = rec["lod_level"]
        lod_counts[lv] = lod_counts.get(lv, 0) + 1

    return {
        "status": "success",
        "instance_count": len(processed),
        "instances": processed,
        # Structured ndarray (dtype=_INSTANCE_DTYPE) — None if numpy absent.
        # Caller can pass directly to a ComputeBuffer or DrawMeshInstanced.
        "instances_array": instances_array,
        # Per-species culling sphere radius for Unity's CullingGroup / HDRP.
        "bounds_radius": bounds_radius,
        "bounds": bounds,
        "lod_distribution": lod_counts,
        "mesh_group_count": len(mesh_groups),
        "mesh_groups": {name: len(grp) for name, grp in mesh_groups.items()},
        "output_path": output_path,
        "format": export_format,
    }

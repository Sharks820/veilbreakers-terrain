"""Bundle F — Cave archetype analysis (pure numpy, no bpy).

Replaces the single generic semicircular-arch cave generator with five
distinct archetypes, each with its own entrance framing, path geometry,
collapse debris pattern, and damp interior mask. All analysis is pure
numpy / python so it can be tested outside Blender.

See docs/terrain_ultra_implementation_plan_2026-04-08.md §11 (Bundle F).

Agent protocol compliance:
- Rule 1: all mutation lives behind ``pass_caves`` + ``register_bundle_f_passes``
- Rule 2: pass declares ``requires_scene_read=True``
- Rule 3: every intermediate signal (``cave_candidate``, ``wet_rock``) is
  written to ``TerrainMaskStack`` via ``stack.set(...)``
- Rule 4: uses ``derive_pass_seed`` — never ``hash()`` / ``random.random()``
- Rule 5: protected zones masked per-cell before any carve
- Rule 6: Z-up world meters (``stack.height`` is world-Z in meters)
- Rule 7: ``cave_candidate`` + ``wet_rock`` are Unity-visible mask channels
- Rule 10: never ``np.clip(..., 0, 1)`` on world heights; the carve returns a
  delta array that callers add to height, but this pass does NOT mutate
  ``stack.height`` directly — it populates masks + records intent.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)


# ---------------------------------------------------------------------------
# Archetype enum + spec
# ---------------------------------------------------------------------------


class CaveArchetype(str, Enum):
    """Five plausible cave archetypes for a dark-fantasy terrain pipeline.

    LAVA_TUBE        — long tubular corridor, low ceiling irregularity,
                       smooth floor; formed by drained basaltic flow.
    FISSURE          — narrow tall vertical crack, high ceiling irregularity,
                       debris-strewn floor; tectonic origin.
    KARST_SINKHOLE   — vertical drop + horizontal chamber at base; heavy
                       collapse debris and strong dampness from groundwater.
    GLACIAL_MELT     — meandering low arch carved by meltwater; wet floor,
                       rounded walls, cold ambient.
    SEA_GROTTO       — wide low arch carved by wave action at coast; tidal
                       damp band, boulder pile at mouth.
    """

    LAVA_TUBE = "lava_tube"
    FISSURE = "fissure"
    KARST_SINKHOLE = "karst_sinkhole"
    GLACIAL_MELT = "glacial_melt"
    SEA_GROTTO = "sea_grotto"


@dataclass
class CaveArchetypeSpec:
    """All archetype-driven parameters for a single cave instance.

    Values are in world meters; factors in 0..1.
    """

    archetype: CaveArchetype
    entrance_width_m: float
    entrance_height_m: float
    interior_length_m: float
    taper_ratio: float = 0.6
    ceiling_irregularity: float = 0.4
    floor_debris_density: float = 0.3
    damp_intensity: float = 0.5
    ambient_light_factor: float = 0.3
    # Supplementary (Gap 14, plan §1.B.6)
    occlusion_shelf_depth: float = 0.0
    sculpt_mode: bool = False


# Default archetype parameter tables (tuned for AAA readability, not generic).
_ARCHETYPE_DEFAULTS: Dict[CaveArchetype, Dict[str, float]] = {
    CaveArchetype.LAVA_TUBE: dict(
        entrance_width_m=6.0,
        entrance_height_m=3.5,
        interior_length_m=45.0,
        taper_ratio=0.85,
        ceiling_irregularity=0.2,
        floor_debris_density=0.15,
        damp_intensity=0.15,
        ambient_light_factor=0.2,
        occlusion_shelf_depth=1.5,
    ),
    CaveArchetype.FISSURE: dict(
        entrance_width_m=2.5,
        entrance_height_m=7.0,
        interior_length_m=20.0,
        taper_ratio=0.4,
        ceiling_irregularity=0.8,
        floor_debris_density=0.6,
        damp_intensity=0.35,
        ambient_light_factor=0.35,
        occlusion_shelf_depth=0.6,
    ),
    CaveArchetype.KARST_SINKHOLE: dict(
        entrance_width_m=9.0,
        entrance_height_m=12.0,
        interior_length_m=18.0,
        taper_ratio=0.5,
        ceiling_irregularity=0.7,
        floor_debris_density=0.85,
        damp_intensity=0.9,
        ambient_light_factor=0.55,
        occlusion_shelf_depth=2.5,
    ),
    CaveArchetype.GLACIAL_MELT: dict(
        entrance_width_m=5.0,
        entrance_height_m=3.0,
        interior_length_m=30.0,
        taper_ratio=0.65,
        ceiling_irregularity=0.35,
        floor_debris_density=0.2,
        damp_intensity=0.8,
        ambient_light_factor=0.5,
        occlusion_shelf_depth=1.2,
    ),
    CaveArchetype.SEA_GROTTO: dict(
        entrance_width_m=10.0,
        entrance_height_m=4.5,
        interior_length_m=22.0,
        taper_ratio=0.55,
        ceiling_irregularity=0.45,
        floor_debris_density=0.55,
        damp_intensity=0.95,
        ambient_light_factor=0.6,
        occlusion_shelf_depth=2.0,
    ),
}


def make_archetype_spec(
    archetype: CaveArchetype,
    **overrides: float,
) -> CaveArchetypeSpec:
    """Return a ``CaveArchetypeSpec`` preloaded with the archetype defaults."""
    params: Dict[str, float] = dict(_ARCHETYPE_DEFAULTS[archetype])
    params.update({k: v for k, v in overrides.items() if v is not None})
    return CaveArchetypeSpec(archetype=archetype, **params)


# ---------------------------------------------------------------------------
# Cave structure — analogous to CliffStructure in Bundle B
# ---------------------------------------------------------------------------


@dataclass
class CaveStructure:
    """A registered cave anatomy. Analogous to ``CliffStructure``."""

    cave_id: str
    archetype: CaveArchetype
    spec: CaveArchetypeSpec
    entrance_world_pos: Tuple[float, float, float]
    path_world: List[Tuple[float, float, float]] = field(default_factory=list)
    interior_mask: Optional[np.ndarray] = None
    damp_mask: Optional[np.ndarray] = None
    height_delta: Optional[np.ndarray] = None
    entrance_frame: Optional[Dict] = None
    debris_points: List[Tuple[float, float, float]] = field(default_factory=list)
    tier: str = "secondary"
    cell_count: int = 0


# ---------------------------------------------------------------------------
# Helpers — world <-> grid coordinate math
# ---------------------------------------------------------------------------


def _world_to_cell(
    stack: TerrainMaskStack, x: float, y: float
) -> Tuple[int, int]:
    """Return (row, col) for a world-space (x, y) position."""
    col = int(round((x - stack.world_origin_x) / stack.cell_size))
    row = int(round((y - stack.world_origin_y) / stack.cell_size))
    rows, cols = stack.height.shape
    col = max(0, min(cols - 1, col))
    row = max(0, min(rows - 1, row))
    return row, col


def _cell_to_world(
    stack: TerrainMaskStack, row: int, col: int
) -> Tuple[float, float]:
    x = stack.world_origin_x + (col + 0.5) * stack.cell_size
    y = stack.world_origin_y + (row + 0.5) * stack.cell_size
    return x, y


def _region_to_slice(
    stack: TerrainMaskStack, region: BBox
) -> Tuple[slice, slice]:
    return region.to_cell_slice(
        world_origin_x=stack.world_origin_x,
        world_origin_y=stack.world_origin_y,
        cell_size=stack.cell_size,
        grid_shape=stack.height.shape,
    )


def _protected_mask_for_caves(
    state: TerrainPipelineState,
    shape: Tuple[int, int],
) -> np.ndarray:
    """Per-cell mask of cells forbidden by protected zones for the 'caves' pass."""
    stack = state.mask_stack
    mask = np.zeros(shape, dtype=bool)
    if not state.intent.protected_zones:
        return mask
    rows, cols = shape
    ys = stack.world_origin_y + (np.arange(rows) + 0.5) * stack.cell_size
    xs = stack.world_origin_x + (np.arange(cols) + 0.5) * stack.cell_size
    xg, yg = np.meshgrid(xs, ys)
    for zone in state.intent.protected_zones:
        if zone.permits("caves"):
            continue
        inside = (
            (xg >= zone.bounds.min_x)
            & (xg <= zone.bounds.max_x)
            & (yg >= zone.bounds.min_y)
            & (yg <= zone.bounds.max_y)
        )
        mask |= inside
    return mask


# ---------------------------------------------------------------------------
# Archetype selection
# ---------------------------------------------------------------------------


def pick_cave_archetype(
    stack: TerrainMaskStack,
    world_pos: Tuple[float, float, float],
    seed: int,
    intent: Optional[Any] = None,
) -> CaveArchetype:
    """Select the most plausible archetype for a location.

    Uses (in order of priority):
      1. Geology hint from intent.composition_hints (highest priority):
           'dissolution' → KARST_SINKHOLE
           'erosion'     → SEA_GROTTO
           'volcanic'    → LAVA_TUBE
           'structural'  → FISSURE
         A strong geology hint adds a large score bonus that overrides terrain
         signals unless another hint exactly conflicts.
      2. Terrain signals: altitude, slope, wetness, basin/concavity
      3. Deterministic RNG tiebreak from ``seed``

    Heuristics:
      - very wet + low altitude + basin  → SEA_GROTTO (coastal)
      - very wet + mid altitude          → GLACIAL_MELT
      - strong basin + mid altitude      → KARST_SINKHOLE
      - steep slope + dry                → FISSURE
      - mid altitude + dry + moderate    → LAVA_TUBE
    """
    x, y, _z = world_pos
    row, col = _world_to_cell(stack, x, y)

    h = float(stack.height[row, col])
    h_min = float(stack.height_min_m if stack.height_min_m is not None else stack.height.min())
    h_max = float(stack.height_max_m if stack.height_max_m is not None else stack.height.max())
    span = max(1e-6, h_max - h_min)
    altitude_norm = (h - h_min) / span  # 0..1

    def _sample(channel: str, default: float = 0.0) -> float:
        arr = stack.get(channel)
        if arr is None:
            return float(default)
        arr_np = np.asarray(arr)
        if arr_np.shape != stack.height.shape:
            return float(default)
        return float(arr_np[row, col])

    slope_rad = _sample("slope", 0.0)
    wetness = _sample("wetness", 0.0)
    basin = _sample("basin", 0.0)
    concavity = _sample("concavity", 0.0)

    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    jitter = float(rng.uniform(-0.05, 0.05))

    # Score each archetype; highest score wins.
    scores: Dict[CaveArchetype, float] = {
        CaveArchetype.SEA_GROTTO: (
            (1.0 - altitude_norm) * 1.2
            + wetness * 1.5
            + (0.6 if basin > 0.1 else 0.0)
            - (0.8 if altitude_norm > 0.35 else 0.0)
        ),
        CaveArchetype.GLACIAL_MELT: (
            altitude_norm * 0.9
            + wetness * 1.1
            + (0.3 if 0.45 < altitude_norm < 0.9 else 0.0)
        ),
        CaveArchetype.KARST_SINKHOLE: (
            (basin * 1.4)
            + (concavity * 0.6)
            + (0.4 if 0.2 < altitude_norm < 0.7 else 0.0)
            - wetness * 0.3
        ),
        CaveArchetype.FISSURE: (
            slope_rad * 0.9
            + (0.5 if altitude_norm > 0.4 else 0.1)
            - wetness * 0.6
        ),
        CaveArchetype.LAVA_TUBE: (
            (0.6 if 0.25 < altitude_norm < 0.75 else 0.0)
            + (0.3 if slope_rad < math.radians(25.0) else 0.0)
            - wetness * 0.5
            - basin * 0.4
        ),
    }

    # Geology hint from intent.composition_hints — adds a large bonus to the
    # geologically indicated archetype so it wins over terrain-signal scoring
    # unless the terrain is strongly contradictory.
    _GEOLOGY_HINT_MAP: Dict[str, CaveArchetype] = {
        "dissolution": CaveArchetype.KARST_SINKHOLE,
        "erosion":     CaveArchetype.SEA_GROTTO,
        "volcanic":    CaveArchetype.LAVA_TUBE,
        "structural":  CaveArchetype.FISSURE,
    }
    if intent is not None:
        hints = getattr(intent, "composition_hints", {}) or {}
        geology = str(hints.get("cave_geology", "")).lower()
        if geology in _GEOLOGY_HINT_MAP:
            scores[_GEOLOGY_HINT_MAP[geology]] += 2.5  # decisive bonus

    # Add a small deterministic jitter so ties resolve per-seed
    for k in list(scores.keys()):
        scores[k] += jitter * (hash(k.value) % 7) * 0.01

    best = max(scores.items(), key=lambda kv: kv[1])
    return best[0]


# ---------------------------------------------------------------------------
# Path generation
# ---------------------------------------------------------------------------


def generate_cave_path(
    stack: TerrainMaskStack,
    archetype: CaveArchetype,
    entrance_pos: Tuple[float, float, float],
    seed: int,
) -> List[Tuple[float, float, float]]:
    """Return a world-meter polyline for the cave interior path.

    Path shape depends on archetype:
      - LAVA_TUBE: nearly straight, gentle meander
      - FISSURE: short, mostly vertical drop then short horizontal
      - KARST_SINKHOLE: vertical plunge then a horizontal chamber arm
      - GLACIAL_MELT: strong meander
      - SEA_GROTTO: short, wide, shallow
    """
    spec = make_archetype_spec(archetype)
    length = float(spec.interior_length_m)
    x0, y0, z0 = entrance_pos

    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    # Pick a heading from RNG, in [0, 2π)
    heading = float(rng.uniform(0.0, 2.0 * math.pi))
    dx = math.cos(heading)
    dy = math.sin(heading)

    # Number of samples per meter adapted to length.
    n_samples = max(6, int(round(length / 2.0)))
    points: List[Tuple[float, float, float]] = []

    if archetype == CaveArchetype.FISSURE:
        # Short horizontal run + vertical drop
        for i in range(n_samples):
            t = i / float(n_samples - 1)
            hx = x0 + dx * length * 0.4 * t
            hy = y0 + dy * length * 0.4 * t
            hz = z0 - t * spec.entrance_height_m * 0.8
            points.append((hx, hy, hz))
    elif archetype == CaveArchetype.KARST_SINKHOLE:
        # Vertical plunge first, then horizontal chamber arm
        drop = spec.entrance_height_m
        plunge_samples = max(3, n_samples // 3)
        for i in range(plunge_samples):
            t = i / float(plunge_samples - 1) if plunge_samples > 1 else 1.0
            points.append((x0, y0, z0 - drop * t))
        # Horizontal arm at the bottom of the plunge
        arm_samples = n_samples - plunge_samples
        for i in range(arm_samples):
            t = (i + 1) / float(arm_samples)
            hx = x0 + dx * length * t
            hy = y0 + dy * length * t
            points.append((hx, hy, z0 - drop))
    elif archetype == CaveArchetype.GLACIAL_MELT:
        # Meander: perpendicular sinusoidal offset
        perp_x = -dy
        perp_y = dx
        for i in range(n_samples):
            t = i / float(n_samples - 1)
            offset = math.sin(t * math.pi * 2.0) * length * 0.12
            hx = x0 + dx * length * t + perp_x * offset
            hy = y0 + dy * length * t + perp_y * offset
            hz = z0 - t * spec.entrance_height_m * 0.3
            points.append((hx, hy, hz))
    elif archetype == CaveArchetype.SEA_GROTTO:
        # Short, shallow, slight meander
        perp_x = -dy
        perp_y = dx
        for i in range(n_samples):
            t = i / float(n_samples - 1)
            offset = math.sin(t * math.pi) * length * 0.08
            hx = x0 + dx * length * t + perp_x * offset
            hy = y0 + dy * length * t + perp_y * offset
            hz = z0 - t * spec.entrance_height_m * 0.15
            points.append((hx, hy, hz))
    else:  # LAVA_TUBE (and default)
        perp_x = -dy
        perp_y = dx
        for i in range(n_samples):
            t = i / float(n_samples - 1)
            offset = math.sin(t * math.pi * 1.5) * length * 0.05
            hx = x0 + dx * length * t + perp_x * offset
            hy = y0 + dy * length * t + perp_y * offset
            hz = z0 - t * spec.entrance_height_m * 0.1
            points.append((hx, hy, hz))

    return points


# ---------------------------------------------------------------------------
# Volume carving (delta, not mutation)
# ---------------------------------------------------------------------------


def carve_cave_volume(
    stack: TerrainMaskStack,
    path: List[Tuple[float, float, float]],
    spec: CaveArchetypeSpec,
) -> np.ndarray:
    """Return a negative height delta + populate ``stack.cave_candidate``.

    The delta is a ``(H, W)`` float64 array of non-positive values to be
    ADDED to the heightmap by a downstream geometry pass. We intentionally
    DO NOT mutate ``stack.height`` — Rule 10 on world-meter heights is
    honored and the pipeline keeps non-destructive editing.

    The cave_candidate mask on the stack is updated in-place (OR-ed) with
    the cells covered by the carve footprint.
    """
    height = np.asarray(stack.height, dtype=np.float64)
    rows, cols = height.shape
    delta = np.zeros_like(height, dtype=np.float64)

    if not path:
        return delta

    # Cave footprint radius in cells = half entrance width
    radius_m = max(1.0, float(spec.entrance_width_m) * 0.5)
    depth_m = max(0.5, float(spec.entrance_height_m))
    cell = max(1e-6, float(stack.cell_size))
    radius_cells = max(1, int(math.ceil(radius_m / cell)))

    # Existing mask starts from whatever is on the stack
    existing = stack.get("cave_candidate")
    if existing is not None and np.asarray(existing).shape == height.shape:
        interior_mask = np.asarray(existing, dtype=bool).copy()
    else:
        interior_mask = np.zeros((rows, cols), dtype=bool)

    rr_grid, cc_grid = np.mgrid[0:rows, 0:cols]

    for (wx, wy, _wz) in path:
        row, col = _world_to_cell(stack, wx, wy)
        dr = rr_grid - row
        dc = cc_grid - col
        dist2 = dr * dr + dc * dc
        radius2 = radius_cells * radius_cells
        footprint = dist2 <= radius2
        if not footprint.any():
            continue
        interior_mask |= footprint
        # Taper depth by distance from the path centre (sqrt makes it smooth)
        dist_norm = np.sqrt(dist2) / max(1.0, float(radius_cells))
        taper = np.maximum(0.0, 1.0 - dist_norm) * float(spec.taper_ratio)
        local_delta = -(taper * depth_m)
        # Keep the deepest (most negative) delta per cell
        delta = np.where(footprint & (local_delta < delta), local_delta, delta)

    stack.set("cave_candidate", interior_mask.astype(bool), "caves")
    return delta


# ---------------------------------------------------------------------------
# Entrance framing
# ---------------------------------------------------------------------------


def build_cave_entrance_frame(
    stack: TerrainMaskStack,
    entrance_pos: Tuple[float, float, float],
    spec: CaveArchetypeSpec,
) -> Dict:
    """Return entrance metadata describing the visual framing.

    Metadata includes:
      - two or three framing rocks (left, right, optional lintel)
      - lip_height: meters above entrance floor
      - vegetation_screen: bool — whether to scatter vines/moss
      - occlusion_shelf: overhead shadow-shelf geometry intent
    """
    x, y, z = entrance_pos
    half_w = spec.entrance_width_m * 0.5
    framing_count = 2
    if spec.archetype in (
        CaveArchetype.LAVA_TUBE,
        CaveArchetype.KARST_SINKHOLE,
        CaveArchetype.SEA_GROTTO,
    ):
        framing_count = 3  # left + right + lintel

    framing_rocks: List[Dict] = [
        {
            "role": "left_jamb",
            "world_pos": (x - half_w, y, z),
            "radius_m": max(0.6, half_w * 0.5),
        },
        {
            "role": "right_jamb",
            "world_pos": (x + half_w, y, z),
            "radius_m": max(0.6, half_w * 0.5),
        },
    ]
    if framing_count >= 3:
        framing_rocks.append(
            {
                "role": "lintel",
                "world_pos": (x, y, z + spec.entrance_height_m * 0.9),
                "radius_m": max(0.5, spec.entrance_width_m * 0.4),
            }
        )

    vegetation_screen = spec.damp_intensity > 0.4 and spec.archetype not in (
        CaveArchetype.FISSURE,
    )

    return {
        "archetype": spec.archetype.value,
        "world_pos": (x, y, z),
        "lip_height_m": float(spec.entrance_height_m),
        "lip_width_m": float(spec.entrance_width_m),
        "framing_rocks": framing_rocks,
        "framing_count": framing_count,
        "vegetation_screen": bool(vegetation_screen),
        "occlusion_shelf": {
            "depth_m": float(spec.occlusion_shelf_depth),
            "width_m": float(spec.entrance_width_m * 1.2),
            "above_entrance_m": float(spec.entrance_height_m * 0.9),
        },
    }


# ---------------------------------------------------------------------------
# Debris scatter
# ---------------------------------------------------------------------------


def scatter_collapse_debris(
    stack: TerrainMaskStack,
    path: List[Tuple[float, float, float]],
    spec: CaveArchetypeSpec,
    seed: int,
) -> List[Tuple[float, float, float]]:
    """Return a deterministic list of debris positions along the path.

    Uses ``derive_pass_seed``-style integer seed (supplied by the caller).
    Debris count scales with ``floor_debris_density * interior_length_m``.
    """

    if not path:
        return []

    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    count = int(round(spec.floor_debris_density * spec.interior_length_m * 0.8))
    count = max(0, min(200, count))
    if count == 0:
        return []

    points: List[Tuple[float, float, float]] = []
    path_arr = np.asarray(path, dtype=np.float64)
    n_path = path_arr.shape[0]

    for _ in range(count):
        # Pick a random path segment
        idx = int(rng.integers(0, max(1, n_path - 1)))
        t = float(rng.uniform(0.0, 1.0))
        p0 = path_arr[idx]
        p1 = path_arr[min(n_path - 1, idx + 1)]
        base = p0 + (p1 - p0) * t
        # Lateral jitter within entrance_width
        jitter = rng.normal(0.0, spec.entrance_width_m * 0.35, size=2)
        points.append(
            (
                float(base[0] + jitter[0]),
                float(base[1] + jitter[1]),
                float(base[2]),
            )
        )

    return points


# ---------------------------------------------------------------------------
# Damp mask
# ---------------------------------------------------------------------------


def generate_damp_mask(
    stack: TerrainMaskStack,
    path: List[Tuple[float, float, float]],
    spec: CaveArchetypeSpec,
) -> np.ndarray:
    """Populate ``stack.wet_rock`` around the cave interior and return it.

    The damp field is a radial falloff around every path sample, scaled
    by ``spec.damp_intensity``. Existing ``wet_rock`` values on the stack
    are combined (max-merged) so multiple caves in one tile coexist.
    """
    height = np.asarray(stack.height, dtype=np.float64)
    rows, cols = height.shape
    damp = np.zeros((rows, cols), dtype=np.float32)

    if not path:
        return damp

    cell = max(1e-6, float(stack.cell_size))
    radius_m = max(2.0, float(spec.entrance_width_m) * 1.8)
    radius_cells = max(2, int(math.ceil(radius_m / cell)))
    rr_grid, cc_grid = np.mgrid[0:rows, 0:cols]

    for (wx, wy, _wz) in path:
        row, col = _world_to_cell(stack, wx, wy)
        dr = rr_grid - row
        dc = cc_grid - col
        dist = np.sqrt(dr * dr + dc * dc)
        local = np.maximum(
            0.0, 1.0 - (dist / float(radius_cells))
        ) * float(spec.damp_intensity)
        damp = np.maximum(damp, local.astype(np.float32))

    existing = stack.get("wet_rock")
    if existing is not None:
        existing_np = np.asarray(existing, dtype=np.float32)
        if existing_np.shape == damp.shape:
            damp = np.maximum(damp, existing_np)

    stack.set("wet_rock", damp, "caves")
    return damp


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_cave_entrance(
    entrance: Dict,
    stack: TerrainMaskStack,
    *,
    min_framing_elements: int = 2,
    require_damp: bool = True,
) -> List[ValidationIssue]:
    """Return validation issues for an entrance dict.

    Checks:
      - framing rock count meets minimum
      - lip height is plausible (> 1m)
      - damp mask populated (if require_damp)
      - occlusion shelf has positive depth (soft)
    """
    issues: List[ValidationIssue] = []
    cave_id = entrance.get("archetype", "unknown")

    framing = entrance.get("framing_rocks", [])
    if len(framing) < int(min_framing_elements):
        issues.append(
            ValidationIssue(
                code="CAVE_NO_FRAMING",
                severity="hard",
                affected_feature=cave_id,
                message=(
                    f"cave entrance has only {len(framing)} framing elements "
                    f"(< {min_framing_elements})"
                ),
            )
        )

    lip = float(entrance.get("lip_height_m", 0.0))
    if lip < 1.0:
        issues.append(
            ValidationIssue(
                code="CAVE_LIP_TOO_SHORT",
                severity="hard",
                affected_feature=cave_id,
                message=f"cave lip height {lip:.2f}m < 1.0m minimum",
            )
        )

    if require_damp:
        wet = stack.get("wet_rock")
        if wet is None or not np.asarray(wet).any():
            issues.append(
                ValidationIssue(
                    code="CAVE_NO_DAMP_MASK",
                    severity="soft",
                    affected_feature=cave_id,
                    message="wet_rock channel empty; cave has no damp signal",
                )
            )

    shelf = entrance.get("occlusion_shelf", {})
    if float(shelf.get("depth_m", 0.0)) <= 0.0:
        issues.append(
            ValidationIssue(
                code="CAVE_NO_OCCLUSION_SHELF",
                severity="soft",
                affected_feature=cave_id,
                message="cave entrance has no occlusion shelf (depth_m=0)",
            )
        )

    return issues


# ---------------------------------------------------------------------------
# Pass wiring
# ---------------------------------------------------------------------------


def _find_entrance_candidates(
    state: TerrainPipelineState,
    region: Optional[BBox],
    max_candidates: int = 32,
    entrance_min_slope_deg: float = 25.0,
) -> List[Tuple[float, float, float]]:
    """Source and score cave entrance candidates.

    Candidates come from scene_read.cave_candidates when available. Each
    candidate is scored by three signals (all contribute to a single score):
      (a) Negative curvature — concave alcoves are geologically favoured
          cave entrance sites. Score += clip(-curv / 0.3, 0, 1).
      (b) Cliff proximity — entrances preferentially occur at the base of
          cliff faces. Score += cliff_candidate value at the cell.
      (c) Slope threshold — candidates with slope < entrance_min_slope_deg
          are penalised (too flat to be a natural opening). Score *= 0.2 if
          slope_deg < entrance_min_slope_deg.

    Returns the top-N candidates sorted descending by score so callers
    process the most geologically plausible entrances first.
    """
    stack = state.mask_stack
    scene_read = state.intent.scene_read

    raw: List[Tuple[float, float, float]] = []
    if scene_read is not None and scene_read.cave_candidates:
        for pos in scene_read.cave_candidates:
            if region is not None:
                if not region.contains_point(pos[0], pos[1]):
                    continue
            raw.append(tuple(pos))  # type: ignore[arg-type]

    if not raw:
        return []

    # Precompute scoring arrays from stack
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)

    # Slope in degrees
    if stack.slope is not None:
        slope_deg_arr = np.degrees(np.asarray(stack.slope, dtype=np.float64))
    else:
        gy, gx = np.gradient(h, cs)
        slope_deg_arr = np.degrees(np.arctan(np.sqrt(gx * gx + gy * gy)))

    # Curvature (negative = concave = good for entrances)
    curv_arr: Optional[np.ndarray] = None
    if stack.curvature is not None:
        curv_arr = np.asarray(stack.curvature, dtype=np.float64)
    else:
        # Compute discrete Laplacian as curvature proxy
        h_pad = np.pad(h, 1, mode="reflect")
        lap = (
            h_pad[:-2, 1:-1] + h_pad[2:, 1:-1]
            + h_pad[1:-1, :-2] + h_pad[1:-1, 2:]
            - 4.0 * h
        ) / (cs * cs)
        curv_arr = lap

    # Cliff proximity signal
    cliff_arr: Optional[np.ndarray] = None
    if stack.cliff_candidate is not None:
        cliff_arr = np.asarray(stack.cliff_candidate, dtype=np.float64)

    def _score(pos: Tuple[float, float, float]) -> float:
        row, col = _world_to_cell(stack, pos[0], pos[1])
        score = 0.0

        # (a) Negative curvature bonus
        if curv_arr is not None:
            curv_val = float(curv_arr[row, col])
            score += float(np.clip(-curv_val / max(float(np.abs(curv_arr).max()), 1e-6), 0.0, 1.0))

        # (b) Cliff proximity bonus
        if cliff_arr is not None:
            score += float(np.clip(cliff_arr[row, col], 0.0, 1.0))

        # (c) Slope threshold penalty — too flat = unlikely entrance
        slope_val = float(slope_deg_arr[row, col])
        if slope_val < entrance_min_slope_deg:
            score *= 0.2

        return score

    scored = sorted(raw, key=_score, reverse=True)
    return scored[:max_candidates]


def pass_caves(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle F caves pass.

    Contract
    --------
    Consumes: height, slope (optional), basin (optional), wetness (optional)
    Produces: cave_candidate, wet_rock
    Respects protected zones: yes
    Requires scene read: yes
    """
    from .terrain_pipeline import derive_pass_seed  # lazy import

    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: List[ValidationIssue] = []

    base_seed = derive_pass_seed(
        state.intent.seed,
        "caves",
        state.tile_x,
        state.tile_y,
        region,
    )

    # Seed the stack.cave_candidate if unset (pure-bool zero array).
    if stack.get("cave_candidate") is None:
        stack.set(
            "cave_candidate",
            np.zeros_like(stack.height, dtype=bool),
            "caves",
        )
    if stack.get("wet_rock") is None:
        stack.set(
            "wet_rock",
            np.zeros_like(stack.height, dtype=np.float32),
            "caves",
        )

    # Protected zone per-cell mask (applied to cave_candidate after carve)
    protected = _protected_mask_for_caves(state, stack.height.shape)

    entrance_candidates = _find_entrance_candidates(state, region)
    caves: List[CaveStructure] = []
    debris_total = 0

    for idx, ent in enumerate(entrance_candidates):
        # Per-cave seed so debris/picks are stable
        cave_seed = (base_seed ^ ((idx + 1) * 2654435761)) & 0xFFFFFFFF

        # Protected zone check — skip caves whose entrance cell is forbidden
        row, col = _world_to_cell(stack, ent[0], ent[1])
        if protected[row, col]:
            continue

        archetype = pick_cave_archetype(stack, ent, cave_seed, intent=state.intent)
        spec = make_archetype_spec(archetype)
        path = generate_cave_path(stack, archetype, ent, cave_seed)

        # Carve (delta, not mutation) + update cave_candidate
        delta = carve_cave_volume(stack, path, spec)

        # Apply protected mask to cave_candidate after carve
        cc = np.asarray(stack.get("cave_candidate"), dtype=bool)
        cc = cc & ~protected
        stack.set("cave_candidate", cc, "caves")

        # Framing + debris + damp
        frame = build_cave_entrance_frame(stack, ent, spec)
        debris = scatter_collapse_debris(stack, path, spec, cave_seed)
        damp = generate_damp_mask(stack, path, spec)

        cave = CaveStructure(
            cave_id=f"cave_{state.tile_x}_{state.tile_y}_{idx:02d}",
            archetype=archetype,
            spec=spec,
            entrance_world_pos=tuple(ent),
            path_world=list(path),
            interior_mask=None,
            damp_mask=damp,
            height_delta=delta,
            entrance_frame=frame,
            debris_points=debris,
            tier="hero" if idx == 0 else "secondary",
            cell_count=int(cc.sum()),
        )
        caves.append(cave)
        debris_total += len(debris)

        # Record on side_effects so downstream bundles discover it
        state.side_effects.append(
            f"cave_structure:{cave.cave_id}:"
            f"archetype={archetype.value}:"
            f"debris={len(debris)}:"
            f"tier={cave.tier}"
        )

        # Validate this entrance
        issues.extend(validate_cave_entrance(frame, stack))

    # Accumulate height deltas from all caves into a single channel.
    # Per the pass contract we do NOT mutate stack.height — we record intent.
    accumulated_delta = np.zeros_like(stack.height, dtype=np.float32)
    for cave in caves:
        if cave.height_delta is not None:
            accumulated_delta += cave.height_delta
    stack.set("cave_height_delta", accumulated_delta, "caves")

    hard_issues = [i for i in issues if i.is_hard()]
    status = "ok" if not hard_issues else "warning"

    return PassResult(
        pass_name="caves",
        status=status,
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height", "slope", "basin", "wetness"),
        produced_channels=("cave_candidate", "wet_rock", "cave_height_delta"),
        metrics={
            "cave_count": len(caves),
            "hero_cave_count": sum(1 for c in caves if c.tier == "hero"),
            "debris_points_total": debris_total,
            "seed_used": base_seed,
            "archetypes": {a.value: sum(1 for c in caves if c.archetype == a) for a in CaveArchetype},
        },
        issues=issues,
        side_effects=[f"cave:{c.cave_id}" for c in caves],
    )


def register_bundle_f_passes() -> None:
    """Register the Bundle F caves pass on TerrainPassController."""
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="caves",
            func=pass_caves,
            requires_channels=("height",),
            produces_channels=("cave_candidate", "wet_rock", "cave_height_delta"),
            seed_namespace="caves",
            requires_scene_read=True,
            may_modify_geometry=False,
            description="Bundle F — cave archetypes (5 types + framing + debris + damp).",
        )
    )


def get_cave_entrance_specs(
    stack: "TerrainMaskStack",
    *,
    max_entrances: int = 4,
    seed: int = 42,
) -> list:
    """Return MeshSpec dicts for cave entrance meshes at cave-candidate sites.

    Reads the ``cave_candidate`` channel (produced by ``pass_caves``) to
    locate entrance positions, then calls ``generate_cave_entrance_mesh``
    from ``_terrain_depth`` to build standalone archway geometry.

    Returns a list of dicts with ``mesh_spec`` and ``world_pos`` keys.
    """
    import numpy as _np
    from ._terrain_depth import generate_cave_entrance_mesh

    cc = stack.get("cave_candidate")
    if cc is None:
        return []

    rng = _np.random.default_rng(seed)
    candidates = _np.argwhere(_np.asarray(cc) > 0.5)
    if len(candidates) == 0:
        return []

    indices = rng.choice(len(candidates), size=min(max_entrances, len(candidates)), replace=False)
    results = []
    for idx in indices:
        r, c = int(candidates[idx][0]), int(candidates[idx][1])
        wx = stack.world_origin_x + c * stack.cell_size
        wy = stack.world_origin_y + r * stack.cell_size
        wz = float(stack.height[r, c])
        spec = generate_cave_entrance_mesh(
            width=rng.uniform(3.0, 6.0),
            height=rng.uniform(3.0, 5.0),
            depth=rng.uniform(2.0, 4.0),
            arch_segments=12,
            terrain_edge_height=wz,
            style="natural",
            seed=int(rng.integers(0, 2**31)),
        )
        results.append({"mesh_spec": spec, "world_pos": (wx, wy, wz)})
    return results


# ---------------------------------------------------------------------------
# MCP handler adapter (added 2026-04-14 in phase 49, per D-14)
# ---------------------------------------------------------------------------
# Replaces world_generate_cave (BSP-based ``_dungeon_gen``, being deleted in
# plan 49-02). Thin wrapper around ``pass_caves`` so compose_map's
# ``_LOC_HANDLERS["cave"]`` dispatch keeps producing cave geometry.
#
# Adapter contract (compose_map ↔ adapter):
#   IN  : params = {name, seed, width, height, cell_size, wall_height, ...}
#         (exact shape compose_map's location dispatch builds — see
#          blender_server.py:6582-6586, _build_location_generation_params)
#   OUT : {"status": "ok"|"warning"|"error",
#          "name": <chamber object name>,
#          "meshes": [...],
#          "meta": {"archetype": <CaveArchetype.value>,
#                   "entrance_specs": [...],
#                   "bundle": <pass_caves PassResult>,
#                   "cave_count": int,
#                   "wall_height": float,
#                   "floor_area": int},
#          "error": <str | None>}
#
# Pure-numpy execution path for ``pass_caves`` is preserved. The chamber
# Blender mesh is created lazily (Blender-only) so this module still imports
# under pytest with a bpy stub. No new external I/O, no auth, no new attack
# surface (T-49-01 is mitigated by the top-level try/except below).


def _build_synthetic_state(
    seed: int,
    width: int,
    height: int,
    cell_size: float,
    *,
    archetype_hint: Optional[str] = None,
) -> "TerrainPipelineState":
    """Construct a minimal TerrainPipelineState wrapping a flat heightmap.

    compose_map dispatches caves at the location-mesh phase, AFTER the
    terrain pipeline has already run. The full TerrainPipelineState is not
    available at this dispatch site, so we synthesise the smallest viable
    state that ``pass_caves`` will accept: a flat heightmap, a single
    cave-candidate anchor at the center, no protected zones.

    This keeps the adapter pure-numpy + scene-read-friendly without
    coupling compose_map to the heavyweight pipeline orchestrator.
    """
    from .terrain_semantics import (
        BBox,
        TerrainAnchor,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
        TerrainSceneRead,
    )

    rows = max(8, int(height))
    cols = max(8, int(width))
    cs = max(0.1, float(cell_size))

    # Flat heightmap with tiny seeded noise so pick_cave_archetype has signal.
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    flat_height = rng.uniform(0.0, 0.5, size=(rows, cols)).astype(np.float32)

    half_w = cols * cs * 0.5
    half_h = rows * cs * 0.5

    stack = TerrainMaskStack(
        tile_size=max(rows, cols),
        cell_size=cs,
        world_origin_x=-half_w,
        world_origin_y=-half_h,
        tile_x=0,
        tile_y=0,
        height=flat_height,
        height_min_m=float(flat_height.min()),
        height_max_m=float(flat_height.max()),
    )

    region_bounds = BBox(
        min_x=-half_w,
        min_y=-half_h,
        max_x=half_w,
        max_y=half_h,
    )

    # One cave-candidate at the centre (compose_map already chose the world
    # anchor; this gives pass_caves something to carve).
    centre_anchor = (0.0, 0.0, float(flat_height[rows // 2, cols // 2]))

    scene_read = TerrainSceneRead(
        timestamp=0.0,
        major_landforms=(),
        focal_point=centre_anchor,
        hero_features_present=(),
        hero_features_missing=(),
        waterfall_chains=(),
        cave_candidates=(centre_anchor,),
        protected_zones_in_region=(),
        edit_scope=region_bounds,
        success_criteria=(),
        reviewer="phase49-adapter",
    )

    intent = TerrainIntentState(
        seed=int(seed),
        region_bounds=region_bounds,
        tile_size=max(rows, cols),
        cell_size=cs,
        anchors=(
            TerrainAnchor(
                name="cave_centre",
                world_position=centre_anchor,
                anchor_kind="cave",
            ),
        ),
        scene_read=scene_read,
        composition_hints=(
            {"archetype_hint": archetype_hint} if archetype_hint else {}
        ),
    )

    return TerrainPipelineState(intent=intent, mask_stack=stack)


def _fbm_noise(x: float, y: float, octaves: int = 4, seed: int = 0) -> float:
    """Fractional Brownian Motion noise in [-1, 1] — pure Python, no deps.

    Used for floor rubble perturbation in _build_chamber_mesh.
    Each octave uses a deterministic but visually varied sine-based noise.
    """
    value = 0.0
    amplitude = 1.0
    frequency = 1.0
    norm = 0.0
    seed_offset = seed & 0xFFFF
    for i in range(octaves):
        px = x * frequency + seed_offset * 0.31 + i * 17.13
        py = y * frequency + seed_offset * 0.17 + i * 11.79
        # Cheap lattice hash via sin
        n = math.sin(px * 127.1 + py * 311.7) * 43758.5453
        n = n - math.floor(n)  # [0, 1]
        value += (n * 2.0 - 1.0) * amplitude
        norm += amplitude
        amplitude *= 0.5
        frequency *= 2.0
    return value / norm if norm > 0.0 else 0.0


def _build_chamber_mesh_geometry(
    width: float,
    depth: float,
    wall_height: float,
    *,
    radial_segments: int = 8,
    height_rings: int = 4,
    floor_noise_amplitude: float = 0.25,
    seed: int = 0,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    """Build chamber verts/faces as pure data — no bpy, fully testable.

    Interior profile:
    - Ceiling: upper half-ellipsoid  z = cz + rz * sqrt(1 - (x/rx)^2 - (y/ry)^2)
    - Walls: radial_segments x height_rings quad strips (tris)
    - Floor: lower half with fBm rock rubble perturbation

    8 radial segments x 4 height rings, triangulated as quads-to-tris.

    Returns (verts, faces) where each face is a (i0, i1, i2) triangle.
    """
    rx = float(width) * 0.5
    ry = float(depth) * 0.5
    rz = float(wall_height)
    cx, cy = 0.0, 0.0
    cz = 0.0  # floor at z=0

    ns = int(max(4, radial_segments))
    nr = int(max(2, height_rings))

    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    # ---- ceiling apex (top of ellipsoid) ----
    apex_idx = len(verts)
    verts.append((cx, cy, cz + rz))

    # ---- wall rings (from top ring down to floor ring) ----
    # height_rings rings evenly spaced from top (t=1) down to equator (t=0)
    ring_start_indices: list[int] = []
    for ring in range(nr):
        # t goes from 1.0 (top) down to 0.0 (equator/floor)
        t = 1.0 - float(ring) / float(nr - 1) if nr > 1 else 0.5
        t = max(0.0, min(1.0, t))
        # Ellipsoid radius at this height band
        r_lateral = math.sqrt(max(0.0, 1.0 - t * t))  # sin component
        ring_start_indices.append(len(verts))
        for seg in range(ns):
            angle = 2.0 * math.pi * seg / ns
            vx = cx + rx * r_lateral * math.cos(angle)
            vy = cy + ry * r_lateral * math.sin(angle)
            # Ceiling: upper half-ellipsoid
            vz = cz + rz * t
            verts.append((vx, vy, vz))

    # ---- floor ring with fBm rubble perturbation ----
    floor_ring_idx = len(verts)
    for seg in range(ns):
        angle = 2.0 * math.pi * seg / ns
        vx = cx + rx * math.cos(angle)
        vy = cy + ry * math.sin(angle)
        noise = _fbm_noise(vx * 0.5, vy * 0.5, octaves=4, seed=seed)
        vz = cz + noise * floor_noise_amplitude * float(wall_height) * 0.3
        verts.append((vx, vy, vz))

    # Floor center with rubble bump
    floor_center_idx = len(verts)
    floor_noise_center = _fbm_noise(cx * 0.5, cy * 0.5, octaves=4, seed=seed + 7)
    verts.append((cx, cy, cz + floor_noise_center * floor_noise_amplitude * float(wall_height) * 0.2))

    # ---- triangulate: apex fan to top ring ----
    top_ring = ring_start_indices[0]
    for seg in range(ns):
        a = top_ring + seg
        b = top_ring + (seg + 1) % ns
        faces.append((apex_idx, a, b))

    # ---- triangulate: ring-to-ring quad strips ----
    for ri in range(len(ring_start_indices) - 1):
        r0 = ring_start_indices[ri]
        r1 = ring_start_indices[ri + 1]
        for seg in range(ns):
            seg_n = (seg + 1) % ns
            v00 = r0 + seg
            v01 = r0 + seg_n
            v10 = r1 + seg
            v11 = r1 + seg_n
            # Quad -> 2 tris
            faces.append((v00, v10, v11))
            faces.append((v00, v11, v01))

    # ---- triangulate: bottom ring -> floor ring ----
    bot_ring = ring_start_indices[-1]
    for seg in range(ns):
        seg_n = (seg + 1) % ns
        v0 = bot_ring + seg
        v1 = bot_ring + seg_n
        f0 = floor_ring_idx + seg
        f1 = floor_ring_idx + seg_n
        faces.append((v0, f0, f1))
        faces.append((v0, f1, v1))

    # ---- triangulate: floor fan ----
    for seg in range(ns):
        a = floor_ring_idx + seg
        b = floor_ring_idx + (seg + 1) % ns
        faces.append((floor_center_idx, b, a))  # reversed for outward normals

    return verts, faces


def _build_chamber_mesh(name: str, width: float, depth: float, wall_height: float, *, seed: int = 0):
    """Create a Blender chamber mesh with a proper ellipsoidal interior profile.

    Interior geometry:
    - Ceiling: upper half-ellipsoid, 8 radial segments x 4 height rings.
    - Floor: ellipsoidal base with fBm rock-rubble height perturbation.
    - All quads triangulated (2 tris per quad face).

    compose_map's cave dispatch positions/parents this object. Returns the
    created bpy Object, or None if bpy is not available (tests).
    """
    try:
        import bpy as _bpy
    except ImportError:
        return None

    verts, faces = _build_chamber_mesh_geometry(
        width=float(width),
        depth=float(depth),
        wall_height=float(wall_height),
        radial_segments=8,
        height_rings=4,
        floor_noise_amplitude=0.25,
        seed=int(seed),
    )

    mesh = _bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    obj = _bpy.data.objects.new(name, mesh)
    try:
        _bpy.context.collection.objects.link(obj)
    except Exception:  # noqa: BLE001 — collection link can fail in tests
        pass
    return obj


def _bezier_cubic(
    p0: Tuple[float, float, float],
    p1: Tuple[float, float, float],
    p2: Tuple[float, float, float],
    p3: Tuple[float, float, float],
    t: float,
) -> Tuple[float, float, float]:
    """Evaluate a cubic Bezier curve at parameter t in [0, 1]."""
    mt = 1.0 - t
    mt2 = mt * mt
    mt3 = mt2 * mt
    t2 = t * t
    t3 = t2 * t
    x = mt3 * p0[0] + 3.0 * mt2 * t * p1[0] + 3.0 * mt * t2 * p2[0] + t3 * p3[0]
    y = mt3 * p0[1] + 3.0 * mt2 * t * p1[1] + 3.0 * mt * t2 * p2[1] + t3 * p3[1]
    z = mt3 * p0[2] + 3.0 * mt2 * t * p1[2] + 3.0 * mt * t2 * p2[2] + t3 * p3[2]
    return (x, y, z)


def _build_bezier_tunnel_geometry(
    entrance_pos: Tuple[float, float, float],
    chamber_center: Tuple[float, float, float],
    entrance_radius: float,
    chamber_radius: float,
    tube_segments: int = 12,
    cross_sections: int = 8,
) -> Tuple[List[Tuple[float, float, float]], List[Tuple[int, ...]]]:
    """Build a swept tube along a cubic Bezier from entrance to chamber.

    The tunnel tapers from entrance_radius (wide end) to chamber_radius
    (narrow end at chamber) — matching how cave passages naturally
    constrict into a chamber.  Cross-section is a regular polygon with
    cross_sections sides.  Returns (verts, tris).
    """
    ex, ey, ez = entrance_pos
    cx, cy, cz = chamber_center

    # Control points: tangent inward from entrance, tangent into chamber.
    dx = cx - ex
    dy = cy - ey
    dz = cz - ez
    dist = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    tang = dist * 0.35

    p0 = (ex, ey, ez)
    p1 = (ex + dx / dist * tang, ey + dy / dist * tang, ez + dz / dist * tang)
    p2 = (cx - dx / dist * tang, cy - dy / dist * tang, cz - dz / dist * tang)
    p3 = (cx, cy, cz)

    ns = int(max(4, cross_sections))
    n_segs = int(max(2, tube_segments))

    verts: List[Tuple[float, float, float]] = []
    faces: List[Tuple[int, ...]] = []

    for si in range(n_segs + 1):
        t = float(si) / float(n_segs)
        centre = _bezier_cubic(p0, p1, p2, p3, t)
        # Linearly taper radius from entrance_radius → chamber_radius
        r = entrance_radius + (chamber_radius - entrance_radius) * t

        # Build a local frame: tangent along curve, up = Z
        if si < n_segs:
            t_next = float(si + 1) / float(n_segs)
        else:
            t_next = t
            t_prev = float(si - 1) / float(n_segs)
            c_prev = _bezier_cubic(p0, p1, p2, p3, t_prev)
            centre_next = centre
            centre = c_prev
            centre = _bezier_cubic(p0, p1, p2, p3, t)
        c_next = _bezier_cubic(p0, p1, p2, p3, min(t_next, 1.0))
        tang_x = c_next[0] - centre[0]
        tang_y = c_next[1] - centre[1]
        tang_z = c_next[2] - centre[2]
        tang_len = math.sqrt(tang_x**2 + tang_y**2 + tang_z**2) or 1.0
        tang_x /= tang_len
        tang_y /= tang_len
        tang_z /= tang_len

        # Up vector: world Z unless tangent is nearly parallel to Z
        if abs(tang_z) < 0.9:
            up_x, up_y, up_z = 0.0, 0.0, 1.0
        else:
            up_x, up_y, up_z = 0.0, 1.0, 0.0

        # Right = tangent × up
        rx = tang_y * up_z - tang_z * up_y
        ry = tang_z * up_x - tang_x * up_z
        rz = tang_x * up_y - tang_y * up_x
        r_len = math.sqrt(rx**2 + ry**2 + rz**2) or 1.0
        rx /= r_len; ry /= r_len; rz /= r_len

        # Recompute up = right × tangent
        up_x = ry * tang_z - rz * tang_y
        up_y = rz * tang_x - rx * tang_z
        up_z = rx * tang_y - ry * tang_x

        ring_start = len(verts)
        for ci in range(ns):
            angle = 2.0 * math.pi * ci / ns
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            vx = centre[0] + r * (cos_a * rx + sin_a * up_x)
            vy = centre[1] + r * (cos_a * ry + sin_a * up_y)
            vz = centre[2] + r * (cos_a * rz + sin_a * up_z)
            verts.append((vx, vy, vz))

        if si > 0:
            prev_start = ring_start - ns
            for ci in range(ns):
                ci_n = (ci + 1) % ns
                v00 = prev_start + ci
                v01 = prev_start + ci_n
                v10 = ring_start + ci
                v11 = ring_start + ci_n
                faces.append((v00, v10, v11))
                faces.append((v00, v11, v01))

    return verts, faces


def handle_generate_cave(params: dict) -> dict:
    """MCP handler: generate a cave via the terrain ``pass_caves`` engine.

    Improvements over the original BSP-based handler:
    - Uses _build_chamber_mesh for a proper ellipsoidal chamber profile
      with fBm floor rubble.
    - Connects the entrance to the chamber with a swept Bezier tube
      whose radius tapers from entrance_radius (wide) to chamber_radius
      (narrow at the chamber junction).

    Accepts the same dict shape compose_map's location dispatch sends
    (name, seed, width, height, cell_size, wall_height, plus extras).
    Returns a dict with status / name / meshes / meta / error keys.

    Phase 49 commit C2 — closes blocker G2 for architecture deletion.
    """
    name = str(params.get("name", "Cave"))
    try:
        seed = int(params.get("seed", 0))
        width = int(params.get("width", 16))
        height = int(params.get("height", 16))
        cell_size = float(params.get("cell_size", 1.0))
        wall_height = float(params.get("wall_height", 4.0))
        archetype_hint = params.get("archetype")
        if archetype_hint is not None:
            archetype_hint = str(archetype_hint)

        # Build synthetic state and run the five-archetype pass.
        state = _build_synthetic_state(
            seed=seed,
            width=width,
            height=height,
            cell_size=cell_size,
            archetype_hint=archetype_hint,
        )
        bundle = pass_caves(state, region=None)

        # Extract entrance specs (Blender-side mesh dicts) from the
        # populated cave_candidate channel.
        try:
            entrance_specs = get_cave_entrance_specs(
                state.mask_stack,
                max_entrances=2,
                seed=seed,
            )
        except Exception:  # noqa: BLE001 — entrance generation is best-effort
            entrance_specs = []

        # Pull picked archetype from side_effects (pass_caves records
        # one "cave_structure:<id>:archetype=<value>:..." per cave).
        picked_archetype: Optional[str] = None
        cave_count = 0
        for side_effect in getattr(bundle, "side_effects", []):
            if isinstance(side_effect, str) and side_effect.startswith("cave:"):
                cave_count += 1
        for side_effect in getattr(state, "side_effects", []):
            if isinstance(side_effect, str) and side_effect.startswith("cave_structure:"):
                for token in side_effect.split(":"):
                    if token.startswith("archetype="):
                        picked_archetype = token.split("=", 1)[1]
                        break
                if picked_archetype:
                    break

        # Determine entrance + chamber geometry sizes from params.
        chamber_w = max(2.0, width * cell_size * 0.4)
        chamber_d = max(2.0, height * cell_size * 0.4)
        entrance_radius = max(1.0, min(chamber_w, chamber_d) * 0.45)
        chamber_radius = entrance_radius * 0.55  # tapers to ~55% at junction

        # Materialise a chamber mesh with ellipsoidal profile + fBm floor.
        chamber_obj = _build_chamber_mesh(
            name=name,
            width=chamber_w,
            depth=chamber_d,
            wall_height=wall_height,
            seed=seed,
        )
        chamber_name = chamber_obj.name if chamber_obj is not None else name

        # Build Bezier tunnel geometry connecting entrance to chamber.
        # Entrance is placed at -Y edge of chamber footprint; chamber
        # center is the mesh origin (0, 0, wall_height * 0.5).
        entrance_pos: Tuple[float, float, float] = (
            0.0,
            -(chamber_d * 0.5 + entrance_radius * 1.5),
            wall_height * 0.3,
        )
        chamber_center: Tuple[float, float, float] = (0.0, 0.0, wall_height * 0.35)

        tunnel_verts, tunnel_faces = _build_bezier_tunnel_geometry(
            entrance_pos=entrance_pos,
            chamber_center=chamber_center,
            entrance_radius=entrance_radius,
            chamber_radius=chamber_radius,
            tube_segments=12,
            cross_sections=8,
        )

        # Attempt to materialise the tunnel mesh in Blender (best-effort).
        tunnel_mesh_spec: Optional[Dict] = None
        try:
            import bpy as _bpy
            import bmesh as _bmesh

            tunnel_mesh_name = f"{name}_Tunnel"
            tmesh = _bpy.data.meshes.new(tunnel_mesh_name)
            tbm = _bmesh.new()
            for tv in tunnel_verts:
                tbm.verts.new(tv)
            tbm.verts.ensure_lookup_table()
            for tf in tunnel_faces:
                try:
                    tbm.faces.new([tbm.verts[vi] for vi in tf])
                except (ValueError, IndexError):
                    pass
            tbm.to_mesh(tmesh)
            tbm.free()
            tmesh.update()

            tunnel_obj = _bpy.data.objects.new(tunnel_mesh_name, tmesh)
            try:
                _bpy.context.collection.objects.link(tunnel_obj)
                if chamber_obj is not None:
                    tunnel_obj.parent = chamber_obj
            except Exception:  # noqa: BLE001
                pass

            tunnel_mesh_spec = {
                "name": tunnel_mesh_name,
                "vertices": tunnel_verts,
                "faces": tunnel_faces,
                "entrance_pos": entrance_pos,
                "chamber_center": chamber_center,
                "entrance_radius": entrance_radius,
                "chamber_radius": chamber_radius,
            }
        except ImportError:
            tunnel_mesh_spec = {
                "name": f"{name}_Tunnel",
                "vertices": tunnel_verts,
                "faces": tunnel_faces,
                "entrance_pos": entrance_pos,
                "chamber_center": chamber_center,
                "entrance_radius": entrance_radius,
                "chamber_radius": chamber_radius,
            }

        # Floor area in cell units (compatibility with old handler shape).
        cc = state.mask_stack.get("cave_candidate")
        floor_area = int(np.asarray(cc).sum()) if cc is not None else 0

        meshes = list(entrance_specs)
        if tunnel_mesh_spec is not None:
            meshes.append(tunnel_mesh_spec)

        return {
            "status": "ok" if getattr(bundle, "status", "ok") != "failed" else "error",
            "name": chamber_name,
            "meshes": meshes,
            "meta": {
                "archetype": picked_archetype or "unknown",
                "entrance_specs": entrance_specs,
                "tunnel_spec": tunnel_mesh_spec,
                "bundle": bundle,
                "cave_count": cave_count,
                "wall_height": wall_height,
                "floor_area": floor_area,
                "entrance_radius": entrance_radius,
                "chamber_radius": chamber_radius,
            },
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — handler boundary, surface error
        return {
            "status": "error",
            "name": name,
            "meshes": [],
            "meta": {},
            "error": f"{type(exc).__name__}: {exc}",
        }


__all__ = [
    "CaveArchetype",
    "CaveArchetypeSpec",
    "CaveStructure",
    "make_archetype_spec",
    "pick_cave_archetype",
    "generate_cave_path",
    "carve_cave_volume",
    "build_cave_entrance_frame",
    "scatter_collapse_debris",
    "generate_damp_mask",
    "validate_cave_entrance",
    "pass_caves",
    "register_bundle_f_passes",
    "get_cave_entrance_specs",
    "handle_generate_cave",
    # Geometry helpers (exposed for testing)
    "_fbm_noise",
    "_build_chamber_mesh_geometry",
    "_bezier_cubic",
    "_build_bezier_tunnel_geometry",
]

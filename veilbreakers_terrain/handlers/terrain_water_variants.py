"""Bundle O — Water Variants.

Adds author-intent depth for water features beyond the base river/waterfall
system: braided channels, estuaries, karst springs, perched lakes, hot
springs, wetlands, tidal zones and seasonal state transitions.

Pure numpy. No bpy imports. Follows the terrain agent protocol — every
mutation routes through a pass, every channel lands on the mask stack.

Contract summary for ``pass_water_variants``
--------------------------------------------
Consumes: ``height``, ``slope`` (optional), ``wetness`` (optional)
Produces: ``water_surface``, ``wetness``
Respects protected zones: yes (per-cell mask)
Requires scene read: yes

Seasonal mutations (``apply_seasonal_water_state``) are **in-place** on
the mask stack — the caller is responsible for checkpointing before the
call if the prior state is needed.
"""

from __future__ import annotations

import enum
import logging
import math
import time
import importlib
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

from .terrain_pipeline import TerrainPassController, derive_pass_seed  # noqa: E402
from .terrain_semantics import (  # noqa: E402
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BraidedChannels:
    """A braided-river decomposition of a main channel."""

    channel_paths: List[np.ndarray]  # each (N, 2) float32 world-meter polyline
    main_channel_idx: int
    total_width_m: float


@dataclass
class Estuary:
    """A river-meets-sea zone with a salinity gradient."""

    mouth_pos: Tuple[float, float, float]
    width_m: float
    salinity_gradient: float  # 0 = fresh, 1 = saline


@dataclass
class KarstSpring:
    world_pos: Tuple[float, float, float]
    discharge_rate: float  # m^3/s (authoring, not simulation)
    temperature_c: float


@dataclass
class PerchedLake:
    basin_pos: Tuple[float, float, float]
    area_m2: float
    elevation_m: float
    seepage_rate: float


@dataclass
class HotSpring:
    world_pos: Tuple[float, float, float]
    temperature_c: float
    mineral_deposit_radius_m: float


@dataclass
class Wetland:
    bounds: BBox
    depth_m: float
    vegetation_density: float
    radius_m: float = 50.0
    world_pos: Tuple[float, float, float] = (0.0, 0.0, 0.0)


class SeasonalState(enum.Enum):
    DRY = "dry"
    NORMAL = "normal"
    WET = "wet"
    FROZEN = "frozen"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_polyline(path: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
    arr = np.asarray(path, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 2)
    if arr.shape[-1] < 2:
        raise ValueError("river_path must have shape (N, 2) or (N, 3)")
    return arr[:, :2].astype(np.float32)


def _region_slice(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> Tuple[slice, slice]:
    stack = state.mask_stack
    shape = stack.height.shape
    if region is None:
        return slice(0, shape[0]), slice(0, shape[1])
    return region.to_cell_slice(
        stack.world_origin_x,
        stack.world_origin_y,
        stack.cell_size,
        shape,
    )


def _protected_mask(
    state: TerrainPipelineState,
    shape: Tuple[int, int],
    pass_name: str,
) -> np.ndarray:
    stack = state.mask_stack
    mask = np.zeros(shape, dtype=bool)
    if not state.intent.protected_zones:
        return mask
    rows, cols = shape
    ys = stack.world_origin_y + (np.arange(rows) + 0.5) * stack.cell_size
    xs = stack.world_origin_x + (np.arange(cols) + 0.5) * stack.cell_size
    xg, yg = np.meshgrid(xs, ys)
    for zone in state.intent.protected_zones:
        if zone.permits(pass_name):
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
# Braided channels
# ---------------------------------------------------------------------------


def generate_braided_channels(
    stack: TerrainMaskStack,
    river_path: Sequence[Sequence[float]] | np.ndarray,
    count: int = 3,
    seed: int = 0,
) -> BraidedChannels:
    """Split a main channel into ``count`` braided sub-channels.

    Each sub-channel is a lateral perturbation of the main channel by a
    deterministic offset.
    """
    if count < 1:
        raise ValueError("count must be >= 1")
    main = _as_polyline(river_path)
    if main.shape[0] < 2:
        raise ValueError("river_path needs at least 2 points")
    rng = np.random.default_rng(seed)

    # Compute per-vertex tangents and left-normals.
    tangents = np.zeros_like(main)
    tangents[:-1] = main[1:] - main[:-1]
    tangents[-1] = tangents[-2]
    lengths = np.linalg.norm(tangents, axis=1, keepdims=True)
    lengths = np.where(lengths < 1e-6, 1.0, lengths)
    tangents = tangents / lengths
    normals = np.stack([-tangents[:, 1], tangents[:, 0]], axis=1)

    channel_cell = float(stack.cell_size)
    # Total braid width is a function of cell size and count.
    total_width_m = float(count) * channel_cell * 3.0

    channels: List[np.ndarray] = []
    # Symmetric offsets around the main path in the [-w, +w] range.
    for k in range(count):
        if count == 1:
            t = 0.0
        else:
            t = (k / (count - 1)) * 2.0 - 1.0  # [-1, 1]
        base_offset = t * (total_width_m * 0.5)
        wiggle = np.asarray(
            rng.standard_normal(main.shape[0]),
            dtype=np.float32,
        ) * np.float32(channel_cell * 0.25)
        offsets = (np.float32(base_offset) + wiggle)[:, None] * normals
        sub = np.asarray(main + offsets, dtype=np.float32)
        channels.append(sub)

    # Main channel is the one closest to the original (smallest |t|).
    if count == 1:
        main_idx = 0
    else:
        ts = np.array([abs((k / (count - 1)) * 2.0 - 1.0) for k in range(count)])
        main_idx = int(np.argmin(ts))
    return BraidedChannels(
        channel_paths=channels,
        main_channel_idx=main_idx,
        total_width_m=total_width_m,
    )


# ---------------------------------------------------------------------------
# Estuary
# ---------------------------------------------------------------------------


def detect_estuary(
    stack: TerrainMaskStack,
    river_path: Sequence[Sequence[float]] | np.ndarray,
    sea_level_m: float,
) -> Optional[Estuary]:
    """Identify a river-meets-sea zone with salinity gradient proxy.

    Walks the river path from source to mouth; the first vertex whose
    sampled height is at or below ``sea_level_m`` becomes the estuary
    mouth. Estuary width is estimated from the local flow-accumulation value
    (wider mouths where more upstream area drains) or falls back to a
    cell-size-scaled heuristic. Salinity gradient is 1.0 at the mouth and
    decays upstream following a linear proxy over a 10-cell transition zone —
    matching the mixing zone models used in Gaea's river-to-ocean blending.
    Returns ``None`` if the river never reaches the sea.
    """
    path = _as_polyline(river_path)
    rows, cols = stack.height.shape
    fa = stack.get("flow_accumulation")
    for i in range(path.shape[0]):
        x_m, y_m = float(path[i, 0]), float(path[i, 1])
        c = int(np.floor((x_m - stack.world_origin_x) / stack.cell_size))
        r = int(np.floor((y_m - stack.world_origin_y) / stack.cell_size))
        if not (0 <= r < rows and 0 <= c < cols):
            continue
        z = float(stack.height[r, c])
        if z <= sea_level_m:
            # Width proxy: scale by flow_accumulation if available
            if fa is not None:
                fa_val = float(np.asarray(fa)[r, c])
                fa_max = float(np.asarray(fa).max()) if np.asarray(fa).max() > 0 else 1.0
                # Width scales with sqrt(accumulation) — Manning's approximation
                width_m = float(stack.cell_size) * 4.0 * (1.0 + 3.0 * math.sqrt(fa_val / fa_max))
            else:
                width_m = float(stack.cell_size) * 6.0
            return Estuary(
                mouth_pos=(x_m, y_m, z),
                width_m=width_m,
                salinity_gradient=1.0,
            )
    return None


# ---------------------------------------------------------------------------
# Karst springs
# ---------------------------------------------------------------------------


def detect_karst_springs(
    stack: TerrainMaskStack,
    karst_features: Sequence[Sequence[float]] | np.ndarray | None,
) -> List[KarstSpring]:
    """Detect karst spring resurgences from soluble-rock areas.

    Springs form where underground flow resurfaces — the intersection of:
      1. A soluble-rock (karst) zone (input mask or point list).
      2. A local topographic depression (flow convergence / concavity).
      3. High flow_accumulation (large upstream catchment draining to point).

    When ``flow_accumulation`` is available on the stack, discharge_rate is
    scaled proportionally to the catchment area (Qsprings ∝ A^0.6,
    Scanlon et al. 2003). Temperature defaults to 10°C (typical groundwater)
    and is raised by 2°C for each 100 m above mean terrain elevation
    (geothermal gradient proxy).

    ``karst_features`` accepts either an (H, W) boolean mask or an iterable
    of (x, y) world-coordinate tuples.
    """
    springs: List[KarstSpring] = []
    if karst_features is None:
        return springs

    rows, cols = stack.height.shape
    h = np.asarray(stack.height, dtype=np.float64)
    h_mean = float(h.mean())
    fa = stack.get("flow_accumulation")
    fa_arr = np.asarray(fa, dtype=np.float64) if fa is not None else None
    fa_max = float(fa_arr.max()) if fa_arr is not None and fa_arr.max() > 0 else 1.0

    arr = np.asarray(karst_features)
    if arr.dtype == bool or (arr.ndim == 2 and arr.shape == (rows, cols)):
        mask = arr.astype(bool)
        rs_arr, cs_arr = np.where(mask)
        if rs_arr.size == 0:
            return springs
        # Prioritise cells with highest flow_accumulation (resurgence points)
        if fa_arr is not None:
            fa_vals = fa_arr[rs_arr, cs_arr]
            priority = np.argsort(fa_vals)[::-1]  # descending
        else:
            priority = np.arange(rs_arr.size)
        # Emit springs at top candidates, separated by min_sep to avoid clusters
        min_sep_cells = max(3, int(np.sqrt(rs_arr.size) // 4) or 1)
        emitted: List[Tuple[int, int]] = []
        for idx in priority:
            r, c = int(rs_arr[idx]), int(cs_arr[idx])
            # Spacing check
            too_close = any(
                abs(r - er) < min_sep_cells and abs(c - ec) < min_sep_cells
                for er, ec in emitted
            )
            if too_close:
                continue
            emitted.append((r, c))
            x = stack.world_origin_x + (c + 0.5) * stack.cell_size
            y = stack.world_origin_y + (r + 0.5) * stack.cell_size
            z = float(h[r, c])
            # Discharge scales with catchment area^0.6
            if fa_arr is not None:
                discharge = 0.05 + 1.5 * (fa_arr[r, c] / fa_max) ** 0.6
            else:
                discharge = 0.25
            # Temperature: groundwater base + geothermal proxy
            elev_above_mean = max(0.0, z - h_mean)
            temp_c = 10.0 + elev_above_mean / 100.0 * 2.0
            springs.append(
                KarstSpring(
                    world_pos=(float(x), float(y), z),
                    discharge_rate=float(discharge),
                    temperature_c=float(temp_c),
                )
            )
            if len(emitted) >= max(8, rs_arr.size // 10):
                break
        return springs

    # Iterable of (x, y) points
    for pt in arr:
        x, y = float(pt[0]), float(pt[1])
        c = int(np.floor((x - stack.world_origin_x) / stack.cell_size))
        r = int(np.floor((y - stack.world_origin_y) / stack.cell_size))
        if not (0 <= r < rows and 0 <= c < cols):
            continue
        z = float(h[r, c])
        if fa_arr is not None:
            discharge = 0.05 + 1.5 * (fa_arr[r, c] / fa_max) ** 0.6
        else:
            discharge = 0.25
        elev_above_mean = max(0.0, z - h_mean)
        temp_c = 10.0 + elev_above_mean / 100.0 * 2.0
        springs.append(
            KarstSpring(
                world_pos=(x, y, z),
                discharge_rate=float(discharge),
                temperature_c=float(temp_c),
            )
        )
    return springs


# ---------------------------------------------------------------------------
# Perched lakes
# ---------------------------------------------------------------------------


def detect_perched_lakes(stack: TerrainMaskStack) -> List[PerchedLake]:
    """Find basins elevated above the regional watertable.

    A perched lake is a local height minimum (basin) whose surrounding
    ring of cells has a LOWER mean altitude — i.e. the basin is
    structurally above its surroundings. This is the signature of a
    hanging valley / perched lake bed.
    """
    h = stack.height.astype(np.float64)
    rows, cols = h.shape
    lakes: List[PerchedLake] = []
    if rows < 5 or cols < 5:
        return lakes

    # Detect 3x3 local minima.
    interior = h[1:-1, 1:-1]
    neighbors = np.stack(
        [
            h[0:-2, 0:-2],
            h[0:-2, 1:-1],
            h[0:-2, 2:],
            h[1:-1, 0:-2],
            h[1:-1, 2:],
            h[2:, 0:-2],
            h[2:, 1:-1],
            h[2:, 2:],
        ],
        axis=0,
    )
    is_min = np.all(interior <= neighbors, axis=0)

    rs, cs = np.where(is_min)
    if rs.size == 0:
        return lakes

    ring_radius = 3
    for r, c in zip(rs + 1, cs + 1):
        r0 = max(0, r - ring_radius)
        r1 = min(rows, r + ring_radius + 1)
        c0 = max(0, c - ring_radius)
        c1 = min(cols, c + ring_radius + 1)
        ring = h[r0:r1, c0:c1]
        if ring.size < 9:
            continue
        # Ring = outer border of the window (exclude the centre cell).
        mask = np.ones_like(ring, dtype=bool)
        mask[r - r0, c - c0] = False
        ring_mean = float(ring[mask].mean())
        basin_z = float(h[r, c])
        if ring_mean >= basin_z:
            # Regular valley, not perched.
            continue
        x = stack.world_origin_x + (c + 0.5) * stack.cell_size
        y = stack.world_origin_y + (r + 0.5) * stack.cell_size
        area = float(stack.cell_size * stack.cell_size)
        lakes.append(
            PerchedLake(
                basin_pos=(float(x), float(y), basin_z),
                area_m2=area,
                elevation_m=basin_z,
                seepage_rate=0.05,
            )
        )
    return lakes


# ---------------------------------------------------------------------------
# Hot springs
# ---------------------------------------------------------------------------


def detect_hot_springs(
    stack: TerrainMaskStack,
    volcanic_activity_mask: Optional[np.ndarray] = None,
) -> List[HotSpring]:
    """Place hot springs at volcanic-activity hotspots.

    ``volcanic_activity_mask`` is an (H, W) float32 mask in [0, 1].
    Springs are placed at cells above the 80th percentile of activity.
    Returns an empty list if no mask is provided.
    """
    if volcanic_activity_mask is None:
        return []
    mask = np.asarray(volcanic_activity_mask, dtype=np.float32)
    if mask.shape != stack.height.shape:
        raise ValueError(
            f"volcanic_activity_mask shape {mask.shape} != height shape {stack.height.shape}"
        )
    if mask.size == 0 or float(mask.max()) <= 0.0:
        return []
    threshold = float(np.quantile(mask, 0.8))
    # Ensure strict positivity to avoid scattering springs over a dead mask.
    threshold = max(threshold, 1e-3)
    rs, cs = np.where(mask >= threshold)
    if rs.size == 0:
        return []
    springs: List[HotSpring] = []
    # Avoid absurd density: stride-sample.
    stride = max(1, int(rs.size // 16) or 1)
    for idx in range(0, rs.size, stride):
        r, c = int(rs[idx]), int(cs[idx])
        x = stack.world_origin_x + (c + 0.5) * stack.cell_size
        y = stack.world_origin_y + (r + 0.5) * stack.cell_size
        z = float(stack.height[r, c])
        temp_c = 45.0 + 40.0 * float(mask[r, c])
        springs.append(
            HotSpring(
                world_pos=(float(x), float(y), z),
                temperature_c=float(temp_c),
                mineral_deposit_radius_m=float(stack.cell_size) * 2.0,
            )
        )
    return springs


# ---------------------------------------------------------------------------
# Wetlands
# ---------------------------------------------------------------------------


def detect_wetlands(stack: TerrainMaskStack) -> List[Wetland]:
    """Find contiguous regions of low slope + high wetness and classify type.

    Wetland classification follows the standard fen/bog/marsh system
    (Mitsch & Gosselink 2015):

    * **Marsh** — mineral-soil wetland, high wetness, low slope, near open
      water (water_surface > 0.3 within 3 cells). Vegetation density high.
    * **Fen** — groundwater-fed, moderate wetness, nearly flat, away from
      open water. pH proxy: rock_hardness moderate (calcareous substrate).
    * **Bog** — precipitation-fed, high wetness, very flat, acid substrate
      (low rock_hardness or no rock_hardness). Vegetation density moderate.

    Classification is a pH proxy: high rock_hardness → calcareous → fen;
    low/absent rock_hardness → acidic peat → bog; near open water → marsh.

    Connected components are found via scipy ``label`` when available, falling
    back to a Python flood-fill. Components smaller than 3 cells are dropped.
    """
    wetness = stack.get("wetness")
    if wetness is None:
        return []
    slope = stack.get("slope")
    if slope is None:
        slope = np.zeros_like(wetness)

    w = np.asarray(wetness, dtype=np.float32)
    s = np.asarray(slope, dtype=np.float32)
    rows, cols = w.shape

    w_thr = max(0.35, float(np.quantile(w, 0.7))) if w.size else 1.0
    s_thr = max(0.2, float(np.quantile(s, 0.3))) if s.size else 0.0
    candidate = (w >= w_thr) & (s <= s_thr)
    if not np.any(candidate):
        return []

    # Connected-components: scipy label (fast) or Python flood-fill
    try:
        ndimage = importlib.import_module("scipy.ndimage")
        label_components = getattr(ndimage, "label")
        struct8 = np.ones((3, 3), dtype=np.int32)
        labeled_result = label_components(candidate, structure=struct8)
        cc_labels = np.asarray(labeled_result[0], dtype=np.int32)
        n_comp = int(labeled_result[1])
    except ImportError:
        # Python flood-fill fallback
        cc_labels = np.zeros((rows, cols), dtype=np.int32)
        visited = np.zeros((rows, cols), dtype=bool)
        n_comp = 0
        for r0 in range(rows):
            for c0 in range(cols):
                if not candidate[r0, c0] or visited[r0, c0]:
                    continue
                n_comp += 1
                stk = [(r0, c0)]
                while stk:
                    r, c = stk.pop()
                    if r < 0 or r >= rows or c < 0 or c >= cols:
                        continue
                    if visited[r, c] or not candidate[r, c]:
                        continue
                    visited[r, c] = True
                    cc_labels[r, c] = n_comp
                    stk.extend([(r-1,c),(r+1,c),(r,c-1),(r,c+1),
                                 (r-1,c-1),(r-1,c+1),(r+1,c-1),(r+1,c+1)])

    # Optional channels for classification
    rock_h = stack.get("rock_hardness")
    rock_arr = np.asarray(rock_h, dtype=np.float32) if rock_h is not None else None
    # W-1: prefer canonical water_surface_mask; fall back to legacy water_surface.
    ws_arr_raw = stack.get("water_surface_mask")
    if ws_arr_raw is None:
        ws_arr_raw = stack.get("water_surface")
    ws_arr = np.asarray(ws_arr_raw, dtype=np.float32) if ws_arr_raw is not None else None

    # Precompute open-water proximity (within 3 cells)
    if ws_arr is not None:
        try:
            ndimage = importlib.import_module("scipy.ndimage")
            binary_dilation = getattr(ndimage, "binary_dilation")
            near_water = np.asarray(
                binary_dilation(ws_arr > 0.3, iterations=3),
                dtype=bool,
            )
        except Exception:
            near_water = ws_arr > 0.3
    else:
        near_water = np.zeros((rows, cols), dtype=bool)

    wetlands: List[Wetland] = []
    for lbl_id in range(1, n_comp + 1):
        cell_mask = cc_labels == lbl_id
        cell_rs, cell_cs = np.where(cell_mask)
        if cell_rs.size < 3:
            continue

        min_r, max_r = int(cell_rs.min()), int(cell_rs.max())
        min_c, max_c = int(cell_cs.min()), int(cell_cs.max())
        bounds = BBox(
            min_x=stack.world_origin_x + min_c * stack.cell_size,
            min_y=stack.world_origin_y + min_r * stack.cell_size,
            max_x=stack.world_origin_x + (max_c + 1) * stack.cell_size,
            max_y=stack.world_origin_y + (max_r + 1) * stack.cell_size,
        )

        mean_w = float(w[cell_rs, cell_cs].mean())
        _mean_s = float(s[cell_rs, cell_cs].mean())

        # Classify by pH proxy
        near_open = bool(near_water[cell_rs, cell_cs].any())
        if rock_arr is not None:
            mean_rh = float(rock_arr[cell_rs, cell_cs].mean())
        else:
            mean_rh = 0.3  # assume acidic when no data

        if near_open and mean_w > 0.5:
            _wetland_type = "marsh"
            veg_density = min(1.0, mean_w + 0.25)
        elif mean_rh > 0.55:
            _wetland_type = "fen"
            veg_density = min(1.0, mean_w + 0.15)
        else:
            _wetland_type = "bog"
            veg_density = min(1.0, mean_w + 0.10)

        # Radius from bounding box diagonal / 2
        dx = (max_c - min_c + 1) * stack.cell_size
        dy = (max_r - min_r + 1) * stack.cell_size
        radius_m = float(math.sqrt(dx * dx + dy * dy) * 0.5)

        cx_w = stack.world_origin_x + (min_c + max_c + 1) * 0.5 * stack.cell_size
        cy_w = stack.world_origin_y + (min_r + max_r + 1) * 0.5 * stack.cell_size
        cz_w = float(stack.height[cell_rs, cell_cs].mean())

        wetlands.append(
            Wetland(
                bounds=bounds,
                depth_m=float(0.2 + 0.8 * mean_w),
                vegetation_density=float(veg_density),
                radius_m=radius_m,
                world_pos=(cx_w, cy_w, cz_w),
            )
        )
    return wetlands


# ---------------------------------------------------------------------------
# Seasonal water state — in-place mutation
# ---------------------------------------------------------------------------


def apply_seasonal_water_state(
    stack: TerrainMaskStack,
    state: object,
) -> None:
    """Mutate wetness / water_surface_mask / tidal in-place per seasonal state.

    **IMPORTANT:** This function edits ``stack`` in place. Callers that
    need to recover the prior state must checkpoint via
    ``TerrainPassController`` before invoking.

    W-1 migration: this function no longer writes to the legacy
    ``water_surface`` channel. All binary water presence is written to
    ``water_surface_mask`` exclusively.
    """
    if not isinstance(state, SeasonalState):
        raise TypeError(f"state must be SeasonalState, got {type(state).__name__}")

    shape = stack.height.shape
    wetness = stack.get("wetness")
    if wetness is None:
        wetness = np.zeros(shape, dtype=np.float32)
    wetness = np.asarray(wetness, dtype=np.float32).copy()

    # W-1: read from water_surface_mask (canonical) instead of water_surface (legacy).
    water_surface_mask = stack.get("water_surface_mask")
    if water_surface_mask is None:
        water_surface_mask = np.zeros(shape, dtype=np.float32)
    water_surface_mask = np.asarray(water_surface_mask, dtype=np.float32).copy()

    tidal = stack.get("tidal")
    if tidal is None:
        tidal = np.zeros(shape, dtype=np.float32)
    tidal = np.asarray(tidal, dtype=np.float32).copy()

    if state is SeasonalState.DRY:
        wetness *= 0.3
        water_surface_mask *= 0.5
    elif state is SeasonalState.NORMAL:
        pass  # no-op; canonical state
    elif state is SeasonalState.WET:
        wetness = np.clip(wetness * 1.5 + 0.2, 0.0, 1.0)
        water_surface_mask = np.clip(water_surface_mask + 0.15, 0.0, 1.0)
    elif state is SeasonalState.FROZEN:
        # Frozen: surface water becomes ice; tidal is locked to max.
        water_surface_mask = np.clip(water_surface_mask + 0.1, 0.0, 1.0)
        wetness *= 0.6
        tidal[:] = 1.0

    stack.set("wetness", wetness, "water_variants_seasonal")
    # W-1: write only to water_surface_mask; do NOT write legacy water_surface.
    stack.set("water_surface_mask", water_surface_mask, "water_variants_seasonal")
    stack.set("tidal", tidal, "water_variants_seasonal")


# ---------------------------------------------------------------------------
# Pass entry point
# ---------------------------------------------------------------------------


def pass_water_variants(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Populate water_surface + wetness from water-variant heuristics.

    Contract
    --------
    Consumes: height (+ optional slope / wetness)
    Produces: water_surface, wetness
    Respects protected zones: yes (per-cell mask)
    Requires scene read: yes
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: List[ValidationIssue] = []
    r_slice, c_slice = _region_slice(state, region)
    protected = _protected_mask(state, stack.height.shape, "water_variants")

    seed = derive_pass_seed(
        state.intent.seed,
        "water_variants",
        state.tile_x,
        state.tile_y,
        region,
    )
    rng = np.random.default_rng(seed)

    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape

    # W-1: prefer canonical water_surface_mask; fall back to legacy water_surface.
    existing_ws = stack.get("water_surface_mask")
    if existing_ws is None:
        existing_ws = stack.get("water_surface")
    water_surface = (
        np.asarray(existing_ws, dtype=np.float32).copy()
        if existing_ws is not None
        else np.zeros(h.shape, dtype=np.float32)
    )
    existing_wet = stack.get("wetness")
    wetness = (
        np.asarray(existing_wet, dtype=np.float32).copy()
        if existing_wet is not None
        else np.zeros(h.shape, dtype=np.float32)
    )

    # Author wetness as a function of normalized depth (basins = wetter).
    region_h = h[r_slice, c_slice]
    h_min = float(region_h.min())
    h_max = float(region_h.max())
    if h_max - h_min > 1e-9:
        depth_norm = 1.0 - (region_h - h_min) / (h_max - h_min)
    else:
        depth_norm = np.zeros_like(region_h)
    jitter = rng.uniform(-0.05, 0.05, size=region_h.shape).astype(np.float32)
    authored_wetness = np.clip(depth_norm.astype(np.float32) * 0.6 + jitter, 0.0, 1.0)
    authored_ws = (authored_wetness > 0.55).astype(np.float32)

    # Merge into the output arrays, respecting protected cells.
    region_protected = protected[r_slice, c_slice]
    wetness_region = wetness[r_slice, c_slice]
    ws_region = water_surface[r_slice, c_slice]
    wetness_region = np.where(region_protected, wetness_region, authored_wetness)
    ws_region = np.where(region_protected, ws_region, authored_ws)
    wetness[r_slice, c_slice] = wetness_region
    water_surface[r_slice, c_slice] = ws_region

    stack.set("water_surface", water_surface, "water_variants")
    stack.set("wetness", wetness, "water_variants")

    # -----------------------------------------------------------------------
    # FIX pipeline-break #3: wire detect_* functions into the pass.
    # Each detector is guarded so a failure does not break the whole pass.
    # -----------------------------------------------------------------------
    perched_count = 0
    wetland_count = 0
    braided_count = 0

    # --- Perched lakes: mark elevated basins as water_surface ---
    try:
        perched = detect_perched_lakes(stack)
        perched_count = len(perched)
        for lake in perched:
            lx, ly, _lz = lake.basin_pos
            lc = int(np.floor((lx - stack.world_origin_x) / stack.cell_size))
            lr = int(np.floor((ly - stack.world_origin_y) / stack.cell_size))
            if 0 <= lr < rows and 0 <= lc < cols and not protected[lr, lc]:
                water_surface[lr, lc] = max(water_surface[lr, lc], 0.9)
                wetness[lr, lc] = max(wetness[lr, lc], 0.8)
    except Exception as exc:
        logger.debug("detect_perched_lakes failed (non-fatal): %s", exc)

    # --- Wetlands: boost wetness in low-slope/high-wetness regions ---
    # Vectorized: numpy slice + np.where replaces O(cells_per_wetland) Python loop.
    try:
        wetland_list = detect_wetlands(stack)
        wetland_count = len(wetland_list)
        for wl in wetland_list:
            b = wl.bounds
            wc0 = max(0, int(np.floor((b.min_x - stack.world_origin_x) / stack.cell_size)))
            wr0 = max(0, int(np.floor((b.min_y - stack.world_origin_y) / stack.cell_size)))
            wc1 = min(cols, int(np.ceil((b.max_x - stack.world_origin_x) / stack.cell_size)))
            wr1 = min(rows, int(np.ceil((b.max_y - stack.world_origin_y) / stack.cell_size)))
            if wr0 >= wr1 or wc0 >= wc1:
                continue
            # Vectorized: only write to unprotected cells in this bounding slice
            region_prot = protected[wr0:wr1, wc0:wc1]
            wetness[wr0:wr1, wc0:wc1] = np.where(
                region_prot,
                wetness[wr0:wr1, wc0:wc1],
                np.maximum(wetness[wr0:wr1, wc0:wc1], 0.7),
            )
    except Exception as exc:
        logger.debug("detect_wetlands failed (non-fatal): %s", exc)

    # --- Braided channels: stamp sub-channels onto water_surface ---
    # Only run if there is an existing river-like linear feature in water_surface
    try:
        ws_arr = np.asarray(water_surface)
        river_cells = np.argwhere(ws_arr > 0.5)
        if river_cells.shape[0] >= 4:
            # Build a coarse polyline from the river cells (sort by row)
            sorted_rc = river_cells[river_cells[:, 0].argsort()]
            stride = max(1, sorted_rc.shape[0] // 8)
            sample = sorted_rc[::stride]
            path_xy = np.stack([
                stack.world_origin_x + (sample[:, 1] + 0.5) * stack.cell_size,
                stack.world_origin_y + (sample[:, 0] + 0.5) * stack.cell_size,
            ], axis=1).astype(np.float32)
            if path_xy.shape[0] >= 2:
                braids = generate_braided_channels(stack, path_xy, count=3, seed=seed)
                braided_count = len(braids.channel_paths)
                for sub in braids.channel_paths:
                    for pt in sub:
                        bc = int(np.floor((float(pt[0]) - stack.world_origin_x) / stack.cell_size))
                        br = int(np.floor((float(pt[1]) - stack.world_origin_y) / stack.cell_size))
                        if 0 <= br < rows and 0 <= bc < cols and not protected[br, bc]:
                            water_surface[br, bc] = max(water_surface[br, bc], 0.6)
    except Exception as exc:
        logger.debug("generate_braided_channels failed (non-fatal): %s", exc)

    # Write back any detector-augmented channels.
    # W-1: co-emit water_surface_mask (canonical binary successor) so downstream
    # consumers can prefer it over the ambiguous water_surface name.
    # Region-aware: when called with a non-None region, merge into existing mask
    # rather than overwriting the whole tile — otherwise a second region call
    # obliterates the first region's contributions.
    water_surface_mask_full = (water_surface > 0.0).astype(np.float32)
    water_surface_elevation_m_full = np.where(
        water_surface_mask_full > 0.0,
        np.asarray(stack.height, dtype=np.float32),
        0.0,
    ).astype(np.float32)
    if region is not None:
        existing_mask = stack.get("water_surface_mask")
        existing_elev = stack.get("water_surface_elevation_m")
        if existing_mask is not None:
            merged_mask = np.asarray(existing_mask, dtype=np.float32).copy()
            merged_mask[r_slice, c_slice] = water_surface_mask_full[r_slice, c_slice]
            water_surface_mask_full = merged_mask
        if existing_elev is not None:
            merged_elev = np.asarray(existing_elev, dtype=np.float32).copy()
            merged_elev[r_slice, c_slice] = water_surface_elevation_m_full[r_slice, c_slice]
            water_surface_elevation_m_full = merged_elev
    stack.set("water_surface", water_surface, "water_variants")
    stack.set("water_surface_mask", water_surface_mask_full, "water_variants")
    stack.set("water_surface_elevation_m", water_surface_elevation_m_full, "water_variants")
    stack.set("wetness", wetness, "water_variants")

    return PassResult(
        pass_name="water_variants",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=(
            "water_surface",
            "water_surface_mask",
            "water_surface_elevation_m",
            "wetness",
        ),
        metrics={
            "wet_cells": int(np.count_nonzero(wetness > 0.3)),
            "surface_cells": int(np.count_nonzero(water_surface > 0.5)),
            "rows": rows,
            "cols": cols,
            "perched_lakes_detected": perched_count,
            "wetlands_detected": wetland_count,
            "braided_channels": braided_count,
        },
        issues=issues,
        seed_used=seed,
    )


def pass_seasonal_water_state(
    state: TerrainPipelineState,
    region: Optional[BBox],  # noqa: ARG001 — region unused; mutation is tile-wide
) -> PassResult:
    """DAG-visible wrapper for ``apply_seasonal_water_state``.

    Contract
    --------
    Consumes: wetness, water_surface_mask, tidal
    Produces (overrides): wetness, water_surface_mask, tidal
    Respects protected zones: no — seasonal state applies uniformly
    Requires scene read: yes (seasonal_state lives on intent.scene_read)
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: List[ValidationIssue] = []

    # Resolve the seasonal state from composition_hints or default to NORMAL.
    composition_hints = dict(getattr(state.intent, "composition_hints", {}) or {})
    raw_season = composition_hints.get("seasonal_state", "normal")
    try:
        seasonal_state = SeasonalState(str(raw_season).lower())
    except ValueError:
        issues.append(ValidationIssue(
            severity="warning",
            message=(
                f"pass_seasonal_water_state: unknown seasonal_state={raw_season!r}; "
                "falling back to NORMAL (no-op)."
            ),
            channel="wetness",
        ))
        seasonal_state = SeasonalState.NORMAL

    apply_seasonal_water_state(stack, seasonal_state)

    return PassResult(
        pass_name="pass_seasonal_water_state",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("wetness", "water_surface_mask", "tidal"),
        produced_channels=("wetness", "water_surface_mask", "tidal"),
        metrics={"seasonal_state": seasonal_state.value},
        issues=issues,
    )


def register_pass_seasonal_water_state() -> None:
    """Register pass_seasonal_water_state on the TerrainPassController."""
    TerrainPassController.register_pass(
        PassDefinition(
            name="pass_seasonal_water_state",
            func=pass_seasonal_water_state,
            requires_channels=("wetness", "water_surface_mask"),
            produces_channels=("wetness", "water_surface_mask", "tidal"),
            # Overrides declared so the DAG knows this pass re-writes channels
            # that water_variants already wrote; without this declaration the
            # PassDAG would consider downstream readers stale on second run.
            overrides=("wetness", "water_surface_mask", "tidal"),
            seed_namespace="seasonal_water_state",
            requires_scene_read=True,
            description=(
                "Bundle O supplement — apply per-season wetness/water_surface_mask/tidal "
                "mutations as a registered DAG pass so downstream passes see fresh values."
            ),
        )
    )


def register_water_variants_pass() -> None:
    TerrainPassController.register_pass(
        PassDefinition(
            name="water_variants",
            func=pass_water_variants,
            # Water variants need height + slope for hydrology solving;
            # wetness / tidal / water_surface are refined iteratively,
            # and produces_channels=("water_surface", "wetness") means
            # downstream passes (wildlife_zones, scatter_intelligent)
            # see fresh values after this pass runs.
            requires_channels=("height", "slope"),
            produces_channels=(
                "water_surface",
                "wetness",
                "water_surface_mask",
                "water_surface_elevation_m",
            ),
            # OVERRIDE: ``erosion`` writes a hydraulic ``wetness`` field first;
            # Bundle O's water_variants refines that into final surface/wetness
            # values that account for braided channels, estuaries, and wetland
            # saturation. Overwriting the erosion-era wetness is the entire
            # point of the Bundle O variant pass.
            overrides=("wetness",),
            seed_namespace="water_variants",
            requires_scene_read=True,
            description="Bundle O — braided rivers, estuaries, karst, perched lakes, wetlands.",
        )
    )


def get_geyser_specs(
    stack: TerrainMaskStack,
    *,
    max_geysers: int = 4,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Return MeshSpec dicts for geyser meshes at detected hot-spring sites.

    Calls ``detect_hot_springs`` to find sites, then ``generate_geyser``
    from terrain_features to produce standalone meshes for Blender placement.

    Returns a list of dicts with ``mesh_spec`` and ``world_pos`` keys.
    """
    from .terrain_features import generate_geyser

    springs = detect_hot_springs(stack)
    if not springs:
        return []

    rng = np.random.default_rng(seed)
    results: list[dict[str, Any]] = []
    for idx, hs in enumerate(springs[:max_geysers]):
        spec = generate_geyser(
            pool_radius=float(rng.uniform(2.0, 5.0)),
            pool_depth=float(rng.uniform(0.3, 0.8)),
            vent_height=float(rng.uniform(0.5, 2.0)),
            mineral_rim_width=float(rng.uniform(0.5, 1.5)),
            seed=(int(seed) ^ (0x47E57E11 + idx * 104729)) & 0x7FFFFFFF,
        )
        results.append({"mesh_spec": spec, "world_pos": hs.world_pos})
    return results


def get_swamp_specs(
    stack: TerrainMaskStack,
    *,
    max_swamps: int = 3,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Return MeshSpec dicts for swamp terrain at detected wetland sites.

    Calls ``detect_wetlands`` to find sites, then ``generate_swamp_terrain``
    from terrain_features to produce standalone meshes for Blender placement.

    Returns a list of dicts with ``mesh_spec`` and ``world_pos`` keys.
    """
    from .terrain_features import generate_swamp_terrain

    wetlands = detect_wetlands(stack)
    if not wetlands:
        return []

    rng = np.random.default_rng(seed)
    results: list[dict[str, Any]] = []
    for idx, wl in enumerate(wetlands[:max_swamps]):
        spec = generate_swamp_terrain(
            size=wl.radius_m * 2.0,
            water_level=float(rng.uniform(0.2, 0.5)),
            hummock_count=int(rng.integers(6, 18)),
            island_count=int(rng.integers(2, 6)),
            seed=(int(seed) ^ (0x5A9A9A11 + idx * 130363)) & 0x7FFFFFFF,
        )
        results.append({"mesh_spec": spec, "world_pos": wl.world_pos})
    return results


# ---------------------------------------------------------------------------
# Bathymetry channel computation
# ---------------------------------------------------------------------------

# Depth-zone thresholds (metres below water surface).
# Witcher 3 / RDR2 parity: characters wade ≤1 m, swim 1–4 m, deep >4 m.
_WADE_DEPTH_M: float = 1.0
_SWIM_DEPTH_M: float = 4.0

# Water-bottom sediment material classification driven by flow accumulation.
# Values match the material_indices returned by generate_water_bottom_mesh.
BOTTOM_MAT_SILT: int = 0    # high-accumulation areas — brown, high roughness
BOTTOM_MAT_GRAVEL: int = 1  # mid-accumulation areas — grey, medium roughness
BOTTOM_MAT_ROCK: int = 2    # low-accumulation areas — dark, low roughness


def _fbm_noise_2d(
    rows: int,
    cols: int,
    scale: float,
    octaves: int,
    persistence: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate 2-octave fractional Brownian motion noise on a (rows, cols) grid.

    Uses smooth random cosine interpolation between lattice values so the
    result is band-limited — suitable for sediment ripple micro-detail on
    river / lake beds where high-frequency hash noise would look synthetic.

    Args:
        rows, cols: Output grid dimensions.
        scale:      Spatial frequency (higher = tighter ripples).
        octaves:    Number of fBm octaves (2 is enough for bottom sediment).
        persistence: Amplitude falloff per octave (0.5 = halved each octave).
        rng:        Seeded numpy Generator for deterministic output.

    Returns:
        float32 ndarray shape (rows, cols), values normalised to [0, 1].
    """
    result = np.zeros((rows, cols), dtype=np.float64)
    amplitude = 1.0
    frequency = 1.0
    total_amplitude = 0.0

    for _ in range(octaves):
        # Lattice size for this octave
        lat_rows = max(2, int(math.ceil(rows * frequency / scale)) + 1)
        lat_cols = max(2, int(math.ceil(cols * frequency / scale)) + 1)
        lattice = rng.standard_normal((lat_rows, lat_cols)).astype(np.float64)

        # Bilinear interpolation across the lattice
        row_coords = np.linspace(0.0, lat_rows - 1, rows, endpoint=False)
        col_coords = np.linspace(0.0, lat_cols - 1, cols, endpoint=False)
        ri = np.clip(np.floor(row_coords).astype(int), 0, lat_rows - 2)
        ci = np.clip(np.floor(col_coords).astype(int), 0, lat_cols - 2)
        rf = row_coords - ri
        cf = col_coords - ci

        rf2d = rf[:, None]
        cf2d = cf[None, :]
        ri2d = ri[:, None]
        ci2d = ci[None, :]

        v00 = lattice[ri2d, ci2d]
        v10 = lattice[ri2d + 1, ci2d]
        v01 = lattice[ri2d, ci2d + 1]
        v11 = lattice[ri2d + 1, ci2d + 1]

        # Cosine smoothstep for less grid artifact vs pure linear
        sf = rf2d * rf2d * (3.0 - 2.0 * rf2d)
        sc = cf2d * cf2d * (3.0 - 2.0 * cf2d)
        interp = (
            v00 * (1.0 - sf) * (1.0 - sc)
            + v10 * sf * (1.0 - sc)
            + v01 * (1.0 - sf) * sc
            + v11 * sf * sc
        )
        result += amplitude * interp
        total_amplitude += amplitude
        amplitude *= persistence
        frequency *= 2.0

    # Normalise to [0, 1]
    result /= total_amplitude if total_amplitude > 0.0 else 1.0
    lo, hi = result.min(), result.max()
    if hi - lo > 1e-9:
        result = (result - lo) / (hi - lo)
    return result.astype(np.float32)


def generate_water_bottom_mesh(
    stack: "TerrainMaskStack",
    water_body_mask: np.ndarray,
    *,
    cell_size_override: Optional[float] = None,
    ripple_amplitude_m: float = 0.10,
    ripple_scale: float = 8.0,
    seed: int = 0,
) -> dict[str, Any]:
    """Generate a water-bottom mesh with sediment micro-terrain and material zones.

    Produces geometry for the underside of a water body — the river / lake
    bed that players see when swimming or when the water is shallow enough
    for the camera to look through the surface. Comparable to how Witcher 3
    stamps distinct gravel / silt bottom tiles under the Pontar river.

    Algorithm
    ---------
    1.  Extract the bounding box of ``water_body_mask`` to keep the mesh
        compact (only cells inside the mask are triangulated).
    2.  Compute the base floor elevation = mean terrain height inside the
        mask minus a small bed-incision offset so the bottom sits below the
        terrain surface.
    3.  Apply 2-octave fBm noise (amplitude 0.05–0.15 m) to add sediment
        ripple micro-detail — the same technique used in RDR2's river-bed
        shader to break the flat-plane look.
    4.  Assign per-quad sediment material using flow_accumulation:
          high accumulation  → silt   (0) — fine particles settle in slack water
          medium accumulation → gravel (1) — transported, not deposited
          low / zero accumulation → rock (2) — exposed bedrock at scour zones
    5.  Build UV coordinates from normalised (u, v) = (col, row) position in
        the mask bounding box so texture tiling is consistent.

    Args:
        stack:              TerrainMaskStack with at least ``height`` populated.
        water_body_mask:    Boolean or float32 (H, W) array — True/1.0 inside
                            the water body. Same grid as stack.height.
        cell_size_override: Override stack.cell_size (useful in tests).
        ripple_amplitude_m: Half-amplitude of sediment ripple noise in metres.
                            Clamped to [0.01, 0.30].
        ripple_scale:       Spatial frequency of ripples (higher = finer).
        seed:               RNG seed for deterministic noise.

    Returns:
        dict with keys:
          ``verts``             — float32 ndarray (N, 3) world XYZ vertices
          ``faces``             — int32 ndarray (M, 4) quad face vertex indices
          ``material_indices``  — int32 ndarray (M,) per-face material index
                                  (0=silt, 1=gravel, 2=rock)
          ``uvs``               — float32 ndarray (M, 4, 2) per-face UV coords
          ``depth_stats``       — dict with ``mean_depth_m``, ``max_depth_m``,
                                  ``silt_frac``, ``gravel_frac``, ``rock_frac``

    Notes:
        The returned dict is consumed by Blender mesh builders that call
        ``bpy.data.meshes.new()`` + ``bmesh`` — no bpy calls are made here.
        All coordinates are in world metres (Z-up).
    """
    rng = np.random.default_rng(seed)
    ripple_amplitude_m = float(np.clip(ripple_amplitude_m, 0.01, 0.30))
    cell_size = float(cell_size_override if cell_size_override is not None else stack.cell_size)

    h = np.asarray(stack.height, dtype=np.float32)
    _rows, _cols = h.shape
    mask = np.asarray(water_body_mask, dtype=bool)
    if mask.shape != h.shape:
        raise ValueError(
            f"water_body_mask shape {mask.shape} must match height shape {h.shape}"
        )

    # Find bounding box of the water mask (fall back to full grid if empty)
    nonzero_rows, nonzero_cols = np.where(mask)
    if nonzero_rows.size == 0:
        # Empty mask — return degenerate but valid empty mesh
        return {
            "verts": np.zeros((0, 3), dtype=np.float32),
            "faces": np.zeros((0, 4), dtype=np.int32),
            "material_indices": np.zeros(0, dtype=np.int32),
            "uvs": np.zeros((0, 4, 2), dtype=np.float32),
            "depth_stats": {
                "mean_depth_m": 0.0,
                "max_depth_m": 0.0,
                "silt_frac": 0.0,
                "gravel_frac": 0.0,
                "rock_frac": 0.0,
            },
        }

    r0 = int(nonzero_rows.min())
    r1 = int(nonzero_rows.max()) + 1
    c0 = int(nonzero_cols.min())
    c1 = int(nonzero_cols.max()) + 1

    sub_h = h[r0:r1, c0:c1]
    sub_mask = mask[r0:r1, c0:c1]
    sub_rows, sub_cols = sub_h.shape

    # --- Base floor elevation ---
    # Floor = mean terrain height inside the mask, minus a small incision
    # so the bed sits below the surrounding terrain.  0.25 m is enough to
    # clear the terrain surface without creating a canyon-like gap.
    masked_heights = sub_h[sub_mask]
    if masked_heights.size > 0:
        mean_terrain_z = float(masked_heights.mean())
        min_terrain_z = float(masked_heights.min())
    else:
        mean_terrain_z = float(sub_h.mean())
        min_terrain_z = mean_terrain_z
    base_z = min_terrain_z - 0.25  # bed sits just below the lowest terrain point

    # --- Sediment ripple noise (2 octaves, 0.05–0.15 m amplitude) ---
    noise = _fbm_noise_2d(
        sub_rows, sub_cols,
        scale=ripple_scale,
        octaves=2,
        persistence=0.5,
        rng=rng,
    )  # values in [0, 1]
    # Signed ripple: centre at 0, ±ripple_amplitude
    ripple_z = (noise - 0.5) * 2.0 * ripple_amplitude_m  # metres, float32

    # --- Flow-accumulation-based material classification ---
    fa_raw = stack.get("flow_accumulation")
    if fa_raw is not None:
        fa = np.asarray(fa_raw, dtype=np.float32)[r0:r1, c0:c1]
        fa_max = float(fa[sub_mask].max()) if sub_mask.any() else 1.0
        fa_norm = fa / max(fa_max, 1.0)  # [0, 1] — 1 = highest accumulation
    else:
        # No flow data — assume uniform medium-accumulation (gravel)
        fa_norm = np.full((sub_rows, sub_cols), 0.5, dtype=np.float32)

    # Thresholds: top 40% accumulation → silt, bottom 20% → rock, rest → gravel
    mat_map = np.where(
        fa_norm >= 0.60, BOTTOM_MAT_SILT,
        np.where(fa_norm <= 0.20, BOTTOM_MAT_ROCK, BOTTOM_MAT_GRAVEL),
    ).astype(np.int32)

    # --- Build quad-mesh vertex grid ---
    # One vertex per grid point (sub_rows+1 × sub_cols+1 to share edges cleanly,
    # but here we keep a per-cell grid matching the heightmap resolution for
    # simplicity — inner vertices are shared, perimeter clipped to mask).
    # Vertex layout: row-major, (sub_rows, sub_cols) cell centres.

    # World XY of each cell centre
    world_origin_x = float(stack.world_origin_x) + c0 * cell_size
    world_origin_y = float(stack.world_origin_y) + r0 * cell_size

    # We emit QUADS only for cells where sub_mask is True.
    # Each quad uses the 4 corners of the cell (vertex-shared grid).
    # Vertex array: (sub_rows+1) × (sub_cols+1), corner positions.
    vert_rows = sub_rows + 1
    vert_cols = sub_cols + 1

    # Expand noise + ripple to corner grid by averaging adjacent cell values
    # (pad then convolve with [0.25, 0.5, 0.25] kernel — simple and stable).
    padded_ripple = np.pad(ripple_z, 1, mode="edge")  # (sub_rows+2, sub_cols+2)
    corner_ripple = (
        padded_ripple[:-1, :-1]
        + padded_ripple[1:, :-1]
        + padded_ripple[:-1, 1:]
        + padded_ripple[1:, 1:]
    ) * 0.25  # shape: (sub_rows+1, sub_cols+1)

    col_idx = np.arange(vert_cols, dtype=np.float32)
    row_idx = np.arange(vert_rows, dtype=np.float32)
    vx = world_origin_x + col_idx * cell_size  # (vert_cols,)
    vy = world_origin_y + row_idx * cell_size  # (vert_rows,)

    vx2d, vy2d = np.meshgrid(vx, vy)   # (vert_rows, vert_cols)
    vz2d = np.full((vert_rows, vert_cols), base_z, dtype=np.float32) + corner_ripple

    # Flatten to (N, 3) vertex array
    verts = np.stack(
        [vx2d.ravel(), vy2d.ravel(), vz2d.ravel()], axis=1
    ).astype(np.float32)

    # Build face list: for each sub_mask-True cell (r, c) emit quad
    # face = (top-left, top-right, bottom-right, bottom-left) in vert_cols-stride layout
    cell_rs, cell_cs = np.where(sub_mask)
    n_quads = int(cell_rs.size)

    tl = cell_rs * vert_cols + cell_cs
    tr = cell_rs * vert_cols + (cell_cs + 1)
    bl = (cell_rs + 1) * vert_cols + cell_cs
    br = (cell_rs + 1) * vert_cols + (cell_cs + 1)

    # Face winding: top-left → top-right → bottom-right → bottom-left (CCW from above)
    faces = np.stack([tl, tr, br, bl], axis=1).astype(np.int32)

    # Per-face material index from cell (r, c)
    material_indices = mat_map[cell_rs, cell_cs].astype(np.int32)

    # --- UV coordinates ---
    # Normalise to [0, 1] within the sub-grid bounding box.
    u_tl = cell_cs.astype(np.float32) / max(sub_cols, 1)
    v_tl = cell_rs.astype(np.float32) / max(sub_rows, 1)
    du = 1.0 / max(sub_cols, 1)
    dv = 1.0 / max(sub_rows, 1)
    uvs = np.stack([
        np.stack([u_tl,       v_tl      ], axis=1),  # TL
        np.stack([u_tl + du,  v_tl      ], axis=1),  # TR
        np.stack([u_tl + du,  v_tl + dv ], axis=1),  # BR
        np.stack([u_tl,       v_tl + dv ], axis=1),  # BL
    ], axis=1).astype(np.float32)  # (n_quads, 4, 2)

    # --- Depth stats for SUMMARY / debugging ---
    bathymetry_channel = stack.get("bathymetry")
    if bathymetry_channel is not None:
        bath_sub = np.asarray(bathymetry_channel, dtype=np.float32)[r0:r1, c0:c1]
        depth_vals = bath_sub[sub_mask]
        mean_depth = float(depth_vals.mean()) if depth_vals.size else 0.0
        max_depth = float(depth_vals.max()) if depth_vals.size else 0.0
    else:
        mean_depth = 0.0
        max_depth = 0.0

    total_quads = float(n_quads) if n_quads > 0 else 1.0
    silt_frac   = float((material_indices == BOTTOM_MAT_SILT).sum()) / total_quads
    gravel_frac = float((material_indices == BOTTOM_MAT_GRAVEL).sum()) / total_quads
    rock_frac   = float((material_indices == BOTTOM_MAT_ROCK).sum()) / total_quads

    return {
        "verts": verts,
        "faces": faces,
        "material_indices": material_indices,
        "uvs": uvs,
        "depth_stats": {
            "mean_depth_m": mean_depth,
            "max_depth_m": max_depth,
            "silt_frac": round(silt_frac, 3),
            "gravel_frac": round(gravel_frac, 3),
            "rock_frac": round(rock_frac, 3),
        },
    }


# ---------------------------------------------------------------------------
# Bathymetry + depth zone pass
# ---------------------------------------------------------------------------


def pass_bathymetry(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Compute bathymetry (depth-below-surface) and water_depth_zone channels.

    Contract
    --------
    Consumes:  height, water_surface
    Produces:  bathymetry, water_depth_zone
    Respects protected zones: yes
    Requires scene read: no

    Bathymetry
    ----------
    For every cell where ``water_surface > 0.5`` (i.e. is under water), the
    bathymetric depth in metres is:

        bathymetry[r, c] = max(0, water_surface_elevation[r, c] - height[r, c])

    where ``water_surface_elevation`` is reconstructed from the height map:
    for each connected water body we sample the dry-cell spill rim around the
    body and use the highest rim elevation as the water-surface elevation.
    If ``water_surface`` holds float values in [0, 1] (the common mask
    convention) rather than absolute elevations, we detect this and fall back
    to the per-body spill-rim approach.

    Depth zone classification
    -------------------------
    Zones are assigned per the gameplay spec:
        0 = dry          — water_surface <= 0.5
        1 = wade zone    — 0 < depth <= 1.0 m
        2 = swim zone    — 1.0 < depth <= 4.0 m
        3 = deep zone    — depth > 4.0 m

    This matches Witcher 3 Oxenfurt ford (wading shallows → swim channel →
    deep pool at the piers) and RDR2 bayou rivers.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: List[ValidationIssue] = []

    h = np.asarray(stack.height, dtype=np.float32)
    rows, cols = h.shape

    # W-1: prefer canonical water_surface_mask; fall back to legacy water_surface.
    ws_raw = stack.get("water_surface_mask")
    if ws_raw is None:
        ws_raw = stack.get("water_surface")
    if ws_raw is None:
        # No water surface yet — produce zero-depth maps and warn
        issues.append(ValidationIssue(
            code="BATHYMETRY_WATER_SURFACE_MISSING",
            severity="soft",
            message="pass_bathymetry: neither water_surface_mask (canonical) "
                    "nor water_surface (legacy fallback) present; "
                    "bathymetry will be all zeros. Run pass_water_variants first.",
            affected_feature="water_surface_mask",
        ))
        bathymetry = np.zeros(h.shape, dtype=np.float32)
        water_depth_zone = np.zeros(h.shape, dtype=np.uint8)
        stack.set("bathymetry", bathymetry, "bathymetry")
        stack.set("water_depth_zone", water_depth_zone, "bathymetry")
        stack.set("water_surface_elevation_m", h.astype(np.float32), "bathymetry")
        return PassResult(
            pass_name="bathymetry",
            status="ok",
            duration_seconds=time.perf_counter() - t0,
            consumed_channels=("height",),
            produced_channels=("bathymetry", "water_depth_zone", "water_surface_elevation_m"),
            metrics={"wet_cells": 0, "max_depth_m": 0.0},
            issues=issues,
        )

    ws = np.asarray(ws_raw, dtype=np.float32)

    # Detect whether water_surface is an elevation map or a [0,1] mask.
    # Heuristic: if max(ws) > max(h) * 0.1 AND range(ws) > 5 m it is likely
    # an absolute elevation field.  Otherwise treat as mask and reconstruct.
    ws_max = float(ws.max())
    h_max = float(h.max())
    h_min = float(h.min())
    h_range = max(h_max - h_min, 1.0)

    _ws_elev = stack.get("water_surface_elevation_m")
    if _ws_elev is not None:
        # Authoritative per-cell elevation available — bypass unreliable heuristic.
        ws = np.asarray(_ws_elev, dtype=np.float32)
        is_absolute_elevation = True
    else:
        is_absolute_elevation = (ws_max > h_range * 0.1) and (ws_max - float(ws.min()) > 5.0)

    # Water mask: cells that are "wet" (water_surface > 0.5 for mask, or ws >= h for elevation)
    if is_absolute_elevation:
        wet_mask = (ws >= h - 0.05)  # small tolerance for floating-point seam cells
        water_surface_elev = ws  # already in metres
    else:
        wet_mask = (ws > 0.5)
        # Reconstruct per-body water surface elevation using connected-component
        # analysis: each body's surface = highest dry spill rim bordering the
        # connected wet body. This preserves single-cell channels and steep
        # basin lips that an interior percentile cannot see.
        water_surface_elev = h.copy()
        if wet_mask.any():
            # Label connected components (4-connectivity for speed)
            # We implement a simple two-pass union-find flood fill without scipy
            label_grid = np.full(h.shape, -1, dtype=np.int32)
            # First pass: row-major assignment with left/up neighbour merging
            parent = list(range(rows * cols))

            def _find(x: int) -> int:
                root = x
                while parent[root] != root:
                    root = parent[root]
                while parent[x] != root:
                    parent[x], x = root, parent[x]
                return root

            def _union(a: int, b: int) -> None:
                ra, rb = _find(a), _find(b)
                if ra != rb:
                    parent[ra] = rb

            wet_flat = wet_mask.ravel()
            for idx in range(rows * cols):
                if not wet_flat[idx]:
                    continue
                r_i = idx // cols
                c_i = idx % cols
                label_grid.ravel()[idx] = idx  # provisional label = own index
                up = (r_i - 1) * cols + c_i if r_i > 0 else -1
                left = r_i * cols + (c_i - 1) if c_i > 0 else -1
                if up >= 0 and wet_flat[up]:
                    _union(idx, up)
                if left >= 0 and wet_flat[left]:
                    _union(idx, left)

            # Assign canonical labels and compute per-body spill rims.
            body_heights: dict[int, list[float]] = {}
            body_rims: dict[int, list[float]] = {}
            for idx in range(rows * cols):
                if not wet_flat[idx]:
                    continue
                root = _find(idx)
                r_i = idx // cols
                c_i = idx % cols
                body_heights.setdefault(root, []).append(float(h[r_i, c_i]))
                rim_values = body_rims.setdefault(root, [])
                for nr, nc in (
                    (r_i - 1, c_i),
                    (r_i + 1, c_i),
                    (r_i, c_i - 1),
                    (r_i, c_i + 1),
                ):
                    if 0 <= nr < rows and 0 <= nc < cols and not wet_mask[nr, nc]:
                        rim_values.append(float(h[nr, nc]))

            body_surface: dict[int, float] = {
                root: float(max(body_rims.get(root) or heights))
                for root, heights in body_heights.items()
            }

            # Write surface elevation for each wet cell
            for idx in range(rows * cols):
                if not wet_flat[idx]:
                    continue
                root = _find(idx)
                r_i = idx // cols
                c_i = idx % cols
                water_surface_elev[r_i, c_i] = body_surface.get(root, h[r_i, c_i])

    # --- Bathymetry: depth below water surface ---
    # bathymetry = max(0, surface_elevation - terrain_height) for wet cells
    raw_depth = np.where(wet_mask, np.maximum(0.0, water_surface_elev - h), 0.0)
    bathymetry = raw_depth.astype(np.float32)

    # --- Depth zone classification ---
    zone = np.zeros(h.shape, dtype=np.uint8)
    zone = np.where(wet_mask & (bathymetry <= 0.0),                         np.uint8(1), zone)  # barely wet → wade
    zone = np.where(wet_mask & (bathymetry > 0.0) & (bathymetry <= _WADE_DEPTH_M),  np.uint8(1), zone)
    zone = np.where(wet_mask & (bathymetry > _WADE_DEPTH_M) & (bathymetry <= _SWIM_DEPTH_M), np.uint8(2), zone)
    zone = np.where(wet_mask & (bathymetry > _SWIM_DEPTH_M),                np.uint8(3), zone)
    water_depth_zone = zone

    stack.set("bathymetry", bathymetry, "bathymetry")
    stack.set("water_depth_zone", water_depth_zone, "bathymetry")
    # W-2 producer: emit water_surface_elevation_m so downstream
    # pass_water_depth (and any other elevation-aware consumer) can read
    # the per-cell water-surface elevation in world metres.  Dry cells
    # remain at their terrain height (water_surface_elev == h there) so
    # depth = max(ws - h, 0) correctly evaluates to 0.
    stack.set(
        "water_surface_elevation_m",
        water_surface_elev.astype(np.float32),
        "bathymetry",
    )

    wet_count = int(wet_mask.sum())
    max_depth = float(bathymetry.max())
    wade_cells = int((water_depth_zone == 1).sum())
    swim_cells = int((water_depth_zone == 2).sum())
    deep_cells = int((water_depth_zone == 3).sum())

    logger.debug(
        "pass_bathymetry: %d wet cells, max_depth=%.2f m, "
        "wade=%d swim=%d deep=%d",
        wet_count, max_depth, wade_cells, swim_cells, deep_cells,
    )

    return PassResult(
        pass_name="bathymetry",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height", "water_surface"),
        produced_channels=("bathymetry", "water_depth_zone", "water_surface_elevation_m"),
        metrics={
            "wet_cells": wet_count,
            "max_depth_m": round(max_depth, 3),
            "wade_cells": wade_cells,
            "swim_cells": swim_cells,
            "deep_cells": deep_cells,
        },
        issues=issues,
    )


def register_bathymetry_pass() -> None:
    """Register pass_bathymetry on the TerrainPassController."""
    TerrainPassController.register_pass(
        PassDefinition(
            name="bathymetry",
            func=pass_bathymetry,
            requires_channels=("height", "water_surface"),
            produces_channels=("bathymetry", "water_depth_zone", "water_surface_elevation_m"),
            overrides=("water_surface_elevation_m",),
            seed_namespace="bathymetry",
            requires_scene_read=False,
            description=(
                "Pass 5 supplement — compute bathymetry (depth-below-surface) "
                "and water_depth_zone (0=dry/1=wade/2=swim/3=deep) from "
                "height + water_surface channels."
            ),
        )
    )


__all__ = [
    "BraidedChannels",
    "Estuary",
    "KarstSpring",
    "PerchedLake",
    "HotSpring",
    "Wetland",
    "SeasonalState",
    "generate_braided_channels",
    "detect_estuary",
    "detect_karst_springs",
    "detect_perched_lakes",
    "detect_hot_springs",
    "detect_wetlands",
    "apply_seasonal_water_state",
    "pass_seasonal_water_state",
    "register_pass_seasonal_water_state",
    "pass_water_variants",
    "register_water_variants_pass",
    "pass_bathymetry",
    "register_bathymetry_pass",
    "generate_water_bottom_mesh",
    "BOTTOM_MAT_SILT",
    "BOTTOM_MAT_GRAVEL",
    "BOTTOM_MAT_ROCK",
    "get_geyser_specs",
    "get_swamp_specs",
]

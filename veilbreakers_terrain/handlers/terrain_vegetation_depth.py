"""Bundle O — Vegetation Depth.

Four-layer vegetation stratification (canopy / understory / shrub /
ground cover) with edge effects, disturbance patches, clearings,
fallen logs, cultivated zones and allelopathic exclusion.

Writes ``stack.detail_density`` (dict channel) — this is the Unity
contract that the ``TerrainData.SetDetailLayer`` importer reads.

Pure numpy. No bpy imports.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .terrain_pipeline import TerrainPassController, derive_pass_seed
from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)

try:
    import scipy.ndimage as _ndimage
    _SCIPY_OK = True
except ImportError:  # pragma: no cover
    _ndimage = None  # type: ignore
    _SCIPY_OK = False


# ---------------------------------------------------------------------------
# Enums + dataclasses
# ---------------------------------------------------------------------------


class VegetationLayer(enum.Enum):
    CANOPY = "canopy"
    UNDERSTORY = "understory"
    SHRUB = "shrub"
    GROUND_COVER = "ground_cover"


@dataclass
class VegetationLayers:
    """Four stratified density arrays, all (H, W) float32 in [0, 1]."""

    canopy_density: np.ndarray
    understory_density: np.ndarray
    shrub_density: np.ndarray
    ground_cover_density: np.ndarray

    def as_dict(self) -> Dict[str, np.ndarray]:
        return {
            "canopy": self.canopy_density,
            "understory": self.understory_density,
            "shrub": self.shrub_density,
            "ground_cover": self.ground_cover_density,
        }


@dataclass
class DisturbancePatch:
    bounds: BBox
    kind: str  # "fire" | "windthrow" | "flood"
    age_years: float
    recovery_progress: float  # 0 = fresh, 1 = fully recovered
    centroid: Tuple[float, float] = (0.0, 0.0)  # world-space (x, y)
    area_cells: int = 0


@dataclass
class Clearing:
    center: Tuple[float, float]
    radius_m: float
    kind: str  # "natural" | "human"


@dataclass
class FallenLogSpec:
    """A single fallen log traced downslope.

    Backward-compatible with the old ``(x, y, rotation_radians)`` tuple
    protocol: ``x, y, rot = log_spec`` still works via ``__iter__``.
    """

    start_world: Tuple[float, float]   # world-space (x, y) of uphill end
    end_world: Tuple[float, float]     # world-space (x, y) of downhill end
    length_cells: int                  # number of cells along the path
    rotation_radians: float            # rough bearing of the log

    def __iter__(self):
        """Yield (x, y, rotation_radians) for tuple-unpack backward compat."""
        yield self.start_world[0]
        yield self.start_world[1]
        yield self.rotation_radians


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _normalize(arr: np.ndarray) -> np.ndarray:
    """Min-max normalize to [0, 1] as float32, NaN-safe.

    Uses nanmin/nanmax so NaN cells don't contaminate the range.
    Returns a zero array when all finite values are identical.
    """
    arr = np.asarray(arr, dtype=np.float32)
    lo = float(np.nanmin(arr))
    hi = float(np.nanmax(arr))
    if hi == lo:
        return np.zeros_like(arr)
    return (arr - lo) / (hi - lo)


# ---------------------------------------------------------------------------
# 4-layer vegetation
# ---------------------------------------------------------------------------


def compute_vegetation_layers(
    stack: TerrainMaskStack,
    biome: str = "dark_fantasy_default",
) -> VegetationLayers:
    """Stratify vegetation into four layers driven by terrain signals.

    Drivers
    -------
    - canopy: low slope + moderate altitude + not too wet
    - understory: canopy proxy but denser in wetter + lower altitude
    - shrub: moderate slope (up to ~0.6), lower canopy areas
    - ground_cover: near-ubiquitous at low slopes, boosted by wetness

    If optional channels (slope, wetness, wind_field) are absent, they
    default to zeros — vegetation still produces a valid (but bland)
    stratification.
    """
    h = np.asarray(stack.height, dtype=np.float32)
    shape = h.shape
    slope = stack.get("slope")
    wetness = stack.get("wetness")
    wind = stack.get("wind_field")

    slope_n = _normalize(np.asarray(slope)) if slope is not None else np.zeros(shape, dtype=np.float32)
    wet_n = _normalize(np.asarray(wetness)) if wetness is not None else np.zeros(shape, dtype=np.float32)
    alt_n = _normalize(h)

    if wind is not None:
        wind_arr = np.asarray(wind, dtype=np.float32)
        if wind_arr.ndim == 3:
            wind_mag = np.linalg.norm(wind_arr, axis=-1)
        else:
            wind_mag = np.abs(wind_arr)
        wind_n = _normalize(wind_mag)
    else:
        wind_n = np.zeros(shape, dtype=np.float32)

    # Biome scalar tweaks
    biome_scale = {
        "dark_fantasy_default": (1.0, 1.0, 1.0, 1.0),
        "tundra": (0.3, 0.4, 0.6, 0.9),
        "swamp": (0.8, 1.1, 1.0, 1.2),
        "desert": (0.1, 0.2, 0.3, 0.4),
    }
    cs, us, ss, gs = biome_scale.get(biome, (1.0, 1.0, 1.0, 1.0))

    # Canopy: low slope, mid altitude, moderate wetness. Tall trees shun
    # exposed windy ridges.
    canopy = (
        (1.0 - slope_n)
        * (1.0 - np.abs(alt_n - 0.4) * 1.2).clip(0.0, 1.0)
        * (1.0 - wind_n * 0.6)
    ).clip(0.0, 1.0) * cs

    # Understory: thrives below canopy, esp. where wetter and lower.
    understory = (
        canopy * 0.7 + wet_n * 0.4 + (1.0 - alt_n) * 0.2
    ).clip(0.0, 1.0) * us

    # Shrubs: moderate slopes, transitional zones between canopy and rock.
    shrub = (
        (1.0 - np.abs(slope_n - 0.35) * 1.6).clip(0.0, 1.0)
        * (1.0 - canopy * 0.5)
    ).clip(0.0, 1.0) * ss

    # Ground cover: almost everywhere on gentle slopes, amplified by wetness.
    ground_cover = (
        ((1.0 - slope_n).clip(0.0, 1.0) * 0.7 + wet_n * 0.4)
    ).clip(0.0, 1.0) * gs

    return VegetationLayers(
        canopy_density=canopy.astype(np.float32),
        understory_density=understory.astype(np.float32),
        shrub_density=shrub.astype(np.float32),
        ground_cover_density=ground_cover.astype(np.float32),
    )


# ---------------------------------------------------------------------------
# Disturbance patches
# ---------------------------------------------------------------------------


def detect_disturbance_patches(
    stack: TerrainMaskStack,
    seed: int,
    kinds: Tuple[str, ...] = ("fire", "windthrow", "flood"),
    disturbance_slope_threshold: float = 0.4,
    disturbance_erosion_threshold: float = 0.3,
    min_patch_area: int = 4,
    intent=None,
) -> List[DisturbancePatch]:
    """Identify disturbance patches from terrain signals and authored intent.

    A cell is disturbed when any of:
    (a) slope > disturbance_slope_threshold,
    (b) erosion_amount on the stack > disturbance_erosion_threshold,
    (c) it falls inside a manual DisturbancePatch entry on intent.

    Connected components (4-connected) are labelled; components smaller than
    min_patch_area cells are discarded. Each surviving component becomes one
    DisturbancePatch whose kind is assigned round-robin from ``kinds``.
    """
    height = np.asarray(stack.height, dtype=np.float32)
    rows, cols = height.shape
    disturbed = np.zeros((rows, cols), dtype=bool)

    # (a) slope-driven disturbance
    slope = stack.get("slope")
    if slope is not None:
        slope_arr = np.asarray(slope, dtype=np.float32)
    else:
        # Derive slope from height via central differences when channel absent
        dy = np.gradient(height, stack.cell_size, axis=0)
        dx = np.gradient(height, stack.cell_size, axis=1)
        slope_arr = np.sqrt(dx ** 2 + dy ** 2, dtype=np.float32)
    disturbed |= slope_arr > disturbance_slope_threshold

    # (b) erosion-driven disturbance
    erosion = stack.get("erosion_amount")
    if erosion is not None:
        erosion_arr = np.asarray(erosion, dtype=np.float32)
        disturbed |= erosion_arr > disturbance_erosion_threshold

    # (c) authored intent patches
    if intent is not None:
        manual = getattr(intent, "disturbance_patches", None) or []
        for mp in manual:
            r_sl, c_sl = mp.bounds.to_cell_slice(
                stack.world_origin_x,
                stack.world_origin_y,
                stack.cell_size,
                (rows, cols),
            )
            disturbed[r_sl, c_sl] = True

    if not np.any(disturbed):
        return []

    # Label connected components
    if _SCIPY_OK:
        labelled, num_labels = _ndimage.label(disturbed)
    else:
        # Fallback: simple 4-connected labelling via union-find
        labelled = np.zeros((rows, cols), dtype=np.int32)
        _label_id = 0
        for r in range(rows):
            for c in range(cols):
                if not disturbed[r, c]:
                    continue
                # look at left and up neighbours
                left = labelled[r, c - 1] if c > 0 else 0
                up = labelled[r - 1, c] if r > 0 else 0
                if left == 0 and up == 0:
                    _label_id += 1
                    labelled[r, c] = _label_id
                elif left != 0 and up == 0:
                    labelled[r, c] = left
                elif up != 0 and left == 0:
                    labelled[r, c] = up
                else:
                    labelled[r, c] = min(left, up)
                    labelled[labelled == max(left, up)] = min(left, up)
        num_labels = int(labelled.max())

    patches: List[DisturbancePatch] = []
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)

    # Max patch area before splitting: ~10% of tile prevents one giant component
    # from eating the whole result list.
    max_component_cells = max(min_patch_area * 4, (rows * cols) // 10)

    for label_idx in range(1, num_labels + 1):
        comp = labelled == label_idx
        area_cells = int(comp.sum())
        if area_cells < min_patch_area:
            continue

        comp_rs, comp_cs = np.where(comp)

        if area_cells <= max_component_cells:
            # Small component: emit as a single patch directly
            candidate_groups = [(comp_rs, comp_cs)]
        else:
            # Large component: seed-controlled random sub-sampling.
            # Draw several random anchor cells from within the component and
            # emit a small patch around each. Number of sub-patches scales
            # with sqrt(area) so big regions still get many events.
            n_sub = max(2, int(np.sqrt(area_cells / max_component_cells)) + 2)
            patch_half = max(2, int(np.sqrt(max_component_cells) // 2))
            chosen = rng.integers(0, area_cells, size=n_sub)
            candidate_groups = []
            for ci in chosen:
                cr, cc = int(comp_rs[ci]), int(comp_cs[ci])
                r0 = max(0, cr - patch_half)
                r1 = min(rows - 1, cr + patch_half)
                c0 = max(0, cc - patch_half)
                c1 = min(cols - 1, cc + patch_half)
                sub_rs = np.arange(r0, r1 + 1)
                sub_cs = np.arange(c0, c1 + 1)
                sgr, sgc = np.meshgrid(sub_rs, sub_cs, indexing="ij")
                candidate_groups.append((sgr.ravel(), sgc.ravel()))

        for sub_rs, sub_cs in candidate_groups:
            r_min, r_max = int(sub_rs.min()), int(sub_rs.max())
            c_min, c_max = int(sub_cs.min()), int(sub_cs.max())

            cx_world = float(stack.world_origin_x + (sub_cs.mean() + 0.5) * stack.cell_size)
            cy_world = float(stack.world_origin_y + (sub_rs.mean() + 0.5) * stack.cell_size)

            bounds = BBox(
                min_x=float(stack.world_origin_x + c_min * stack.cell_size),
                min_y=float(stack.world_origin_y + r_min * stack.cell_size),
                max_x=float(stack.world_origin_x + (c_max + 1) * stack.cell_size),
                max_y=float(stack.world_origin_y + (r_max + 1) * stack.cell_size),
            )

            kind = str(kinds[len(patches) % len(kinds)])
            age = float(rng.uniform(0.5, 40.0))
            recovery = float(min(1.0, age / 40.0))

            patches.append(
                DisturbancePatch(
                    bounds=bounds,
                    kind=kind,
                    age_years=age,
                    recovery_progress=recovery,
                    centroid=(cx_world, cy_world),
                    area_cells=int(sub_rs.size),
                )
            )

    return patches


# ---------------------------------------------------------------------------
# Clearings
# ---------------------------------------------------------------------------


def place_clearings(
    stack: TerrainMaskStack,
    intent,
    count_per_km2: float = 2.0,
    seed: int = 0,
    clearing_max_slope: float = 0.25,
    clearing_radius_cells: float = 6.0,
    min_separation_cells: float = 12.0,
    detail_density: Optional[Dict[str, np.ndarray]] = None,
) -> List[Clearing]:
    """Place clearings in low-slope, cliff-distant areas with soft-edged carving.

    Algorithm
    ---------
    1. Score cells: ``clearing_score = (1 - norm_slope) * (1 - cliff_proximity)``.
    2. Weighted random sampling (no-replacement) for ``target`` candidate cells.
    3. Enforce minimum separation between accepted clearing centres.
    4. Carve a soft-edged circle into each layer of ``detail_density``
       (if provided): ``density *= max(0, 1 - (dist/radius)^2)``.
    """
    rows, cols = stack.height.shape
    world_w = cols * stack.cell_size
    world_h = rows * stack.cell_size
    area_km2 = (world_w * world_h) / 1_000_000.0
    target = max(1, int(round(count_per_km2 * max(area_km2, 0.001))))

    namespace = "vegetation_clearings"
    base_seed = int(seed) if seed else int(getattr(intent, "seed", 0) or 0)
    pass_seed = derive_pass_seed(
        base_seed,
        namespace,
        int(stack.tile_x),
        int(stack.tile_y),
        None,
    )
    rng = np.random.default_rng(pass_seed)

    # --- Build clearing score map ---
    slope = stack.get("slope")
    if slope is not None:
        slope_arr = np.asarray(slope, dtype=np.float32)
    else:
        # Derive slope from height via central differences
        h = np.asarray(stack.height, dtype=np.float32)
        dy = np.gradient(h, stack.cell_size, axis=0)
        dx = np.gradient(h, stack.cell_size, axis=1)
        slope_arr = np.sqrt(dx ** 2 + dy ** 2)

    slope_ok = (slope_arr <= clearing_max_slope).astype(np.float32)

    # Cliff proximity: use cliff mask if available, else use steep slope proxy
    cliff = stack.get("cliff_mask")
    if cliff is not None:
        cliff_arr = np.asarray(cliff, dtype=np.float32)
    else:
        cliff_arr = (slope_arr > 0.6).astype(np.float32)

    # Distance transform from cliff cells — normalised to [0, 1]
    if _SCIPY_OK:
        cliff_bool = cliff_arr > 0.5
        if np.any(cliff_bool):
            dist_from_cliff = _ndimage.distance_transform_edt(~cliff_bool).astype(np.float32)
        else:
            dist_from_cliff = np.ones((rows, cols), dtype=np.float32) * max(rows, cols)
    else:
        # Fallback: approximate via morphological expansion count
        cliff_bool = cliff_arr > 0.5
        dist_from_cliff = np.zeros((rows, cols), dtype=np.float32)
        frontier = cliff_bool.copy()
        step = 0
        remaining = ~cliff_bool
        while np.any(remaining):
            step += 1
            expanded = np.zeros_like(frontier)
            expanded[1:, :] |= frontier[:-1, :]
            expanded[:-1, :] |= frontier[1:, :]
            expanded[:, 1:] |= frontier[:, :-1]
            expanded[:, :-1] |= frontier[:, 1:]
            new_cells = expanded & remaining
            dist_from_cliff[new_cells] = step
            remaining &= ~new_cells
            frontier = new_cells
            if step > max(rows, cols):
                break

    cliff_proximity = 1.0 - _normalize(dist_from_cliff)  # high near cliffs

    score = slope_ok * (1.0 - cliff_proximity)
    score_flat = score.ravel()
    total_score = float(score_flat.sum())
    if total_score < 1e-9:
        # No viable cells — fall back to uniform random
        score_flat = np.ones(rows * cols, dtype=np.float32)
        total_score = float(score_flat.sum())

    probs = score_flat / total_score

    min_sep = int(min_separation_cells)
    min_radius = float(max(stack.cell_size * clearing_radius_cells * 0.5, 5.0))
    max_radius = float(max(min_radius * 2.0, 15.0))

    clearings: List[Clearing] = []
    accepted_rc: List[Tuple[int, int]] = []

    # Draw candidates without replacement using reservoir-style weighted sampling
    n_candidates = min(target * 40, rows * cols)
    try:
        flat_indices = rng.choice(rows * cols, size=n_candidates, replace=False, p=probs)
    except ValueError:
        flat_indices = rng.integers(0, rows * cols, size=n_candidates)

    for flat_idx in flat_indices:
        if len(clearings) >= target:
            break
        r = int(flat_idx) // cols
        c = int(flat_idx) % cols

        # Check minimum separation
        too_close = False
        for pr, pc in accepted_rc:
            if abs(r - pr) < min_sep and abs(c - pc) < min_sep:
                dist_rc = np.hypot(r - pr, c - pc)
                if dist_rc < min_sep:
                    too_close = True
                    break
        if too_close:
            continue

        cx = float(stack.world_origin_x + (c + 0.5) * stack.cell_size)
        cy = float(stack.world_origin_y + (r + 0.5) * stack.cell_size)
        radius = float(rng.uniform(min_radius, max_radius))
        kind = "natural" if (len(clearings) % 2 == 0) else "human"
        clearings.append(Clearing(center=(cx, cy), radius_m=radius, kind=kind))
        accepted_rc.append((r, c))

        # Carve soft-edged circle into detail_density layers
        if detail_density is not None:
            radius_cells = radius / stack.cell_size
            r0 = max(0, int(r - radius_cells) - 1)
            r1 = min(rows, int(r + radius_cells) + 2)
            c0 = max(0, int(c - radius_cells) - 1)
            c1 = min(cols, int(c + radius_cells) + 2)
            rr = np.arange(r0, r1).reshape(-1, 1)
            cc = np.arange(c0, c1).reshape(1, -1)
            dist_sq = ((rr - r) ** 2 + (cc - c) ** 2) / max(radius_cells ** 2, 1e-9)
            falloff = np.maximum(0.0, 1.0 - dist_sq).astype(np.float32)
            suppress = 1.0 - falloff
            for layer_arr in detail_density.values():
                layer_arr[r0:r1, c0:c1] *= suppress

    return clearings


# ---------------------------------------------------------------------------
# Fallen logs
# ---------------------------------------------------------------------------


def place_fallen_logs(
    stack: TerrainMaskStack,
    forest_mask: np.ndarray,
    seed: int,
    log_steps: int = 9,
    log_density_value: float = 0.85,
    detail_density: Optional[Dict[str, np.ndarray]] = None,
) -> List[FallenLogSpec]:
    """Trace fallen logs downslope within the forest mask.

    Algorithm
    ---------
    For each log:
    1. Pick a start cell on a gentle slope inside the forest.
    2. Walk ``log_steps`` steps using greedy steepest-descent (8-connected).
    3. Build a line mask along the path and mark those cells in
       ``detail_density["ground_cover"]`` (if provided) with
       ``log_density_value``.
    4. Return a FallenLogSpec for each log with endpoints and length.
    """
    mask = np.asarray(forest_mask, dtype=bool)
    if mask.shape != stack.height.shape:
        raise ValueError(
            f"forest_mask shape {mask.shape} != height shape {stack.height.shape}"
        )
    rs, cs = np.where(mask)
    if rs.size == 0:
        return []

    pass_seed = derive_pass_seed(
        int(seed),
        "vegetation_logs",
        int(stack.tile_x),
        int(stack.tile_y),
        None,
    )
    rng = np.random.default_rng(pass_seed)

    height = np.asarray(stack.height, dtype=np.float32)
    rows, cols = height.shape

    # Slope to filter start cells — prefer gentle slopes for fallen logs
    dy = np.gradient(height, stack.cell_size, axis=0)
    dx = np.gradient(height, stack.cell_size, axis=1)
    slope = np.sqrt(dx ** 2 + dy ** 2)

    slope_ok = slope[rs, cs] < 0.45
    eligible_rs = rs[slope_ok]
    eligible_cs = cs[slope_ok]
    if eligible_rs.size == 0:
        eligible_rs, eligible_cs = rs, cs

    target = max(1, eligible_rs.size // 40)
    min_dist_cells = 2.5
    logs: List[FallenLogSpec] = []
    start_cells_used: List[Tuple[int, int]] = []

    attempts = 0
    max_attempts = target * 30

    # Ground cover layer for stamping, if available
    gc_layer = None
    if detail_density is not None:
        gc_layer = detail_density.get("ground_cover")

    while len(logs) < target and attempts < max_attempts:
        attempts += 1
        idx = int(rng.integers(0, eligible_rs.size))
        sr, sc = int(eligible_rs[idx]), int(eligible_cs[idx])

        # Minimum separation between log starts
        too_close = False
        for pr, pc in start_cells_used:
            if np.hypot(sr - pr, sc - pc) < min_dist_cells * 2:
                too_close = True
                break
        if too_close:
            continue

        # Greedy 8-connected downhill walk
        path: List[Tuple[int, int]] = [(sr, sc)]
        cr, cc = sr, sc
        for _ in range(log_steps):
            best_h = height[cr, cc]
            best_r, best_c = cr, cc
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = cr + dr, cc + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        if height[nr, nc] < best_h:
                            best_h = height[nr, nc]
                            best_r, best_c = nr, nc
            if best_r == cr and best_c == cc:
                break  # local minimum — stop tracing
            cr, cc = best_r, best_c
            path.append((cr, cc))

        if len(path) < 2:
            continue

        # Stamp log into ground_cover density
        if gc_layer is not None:
            for pr, pc in path:
                gc_layer[pr, pc] = float(
                    np.clip(log_density_value, 0.0, 1.0)
                )

        start_r, start_c = path[0]
        end_r, end_c = path[-1]
        start_world = (
            float(stack.world_origin_x + (start_c + 0.5) * stack.cell_size),
            float(stack.world_origin_y + (start_r + 0.5) * stack.cell_size),
        )
        end_world = (
            float(stack.world_origin_x + (end_c + 0.5) * stack.cell_size),
            float(stack.world_origin_y + (end_r + 0.5) * stack.cell_size),
        )
        rotation = float(np.arctan2(
            end_world[1] - start_world[1],
            end_world[0] - start_world[0],
        ))
        logs.append(
            FallenLogSpec(
                start_world=start_world,
                end_world=end_world,
                length_cells=len(path),
                rotation_radians=rotation,
            )
        )
        start_cells_used.append((sr, sc))

    return logs


# ---------------------------------------------------------------------------
# Edge effects
# ---------------------------------------------------------------------------


def apply_edge_effects(
    vegetation: VegetationLayers,
    forest_mask: np.ndarray,
    edge_width_cells: int = 4,
    edge_boost_factor: float = 0.35,
    biome_boundary_mask: Optional[np.ndarray] = None,
) -> VegetationLayers:
    """Boost vegetation density in the strip along forest / biome boundaries.

    Algorithm
    ---------
    1. Compute boundary via ``scipy.ndimage.morphological_gradient`` on
       ``forest_mask`` (or ``biome_boundary_mask`` when given), which gives
       the outer edge of the forest.
    2. Build an edge strip where distance-to-boundary < edge_width_cells.
    3. Boost understory and shrub density inside the strip by
       ``edge_boost_factor``.

    Falls back to manual 4-connected dilation when scipy is unavailable.
    """
    shape = vegetation.canopy_density.shape

    # Choose the source mask for boundary detection
    if biome_boundary_mask is not None:
        src_mask = np.asarray(biome_boundary_mask, dtype=np.uint8)
    else:
        src_mask = np.asarray(forest_mask, dtype=np.uint8)

    if src_mask.shape != shape:
        raise ValueError("boundary mask shape must match vegetation layers")

    if _SCIPY_OK:
        # morphological_gradient = dilation - erosion; non-zero pixels are boundary
        boundary = _ndimage.morphological_gradient(src_mask, size=3).astype(bool)
        # Distance from boundary for every cell
        if np.any(boundary):
            dist_from_boundary = _ndimage.distance_transform_edt(~boundary).astype(np.float32)
        else:
            dist_from_boundary = np.full(shape, float(max(shape)), dtype=np.float32)
    else:
        # Fallback: treat non-zero pixels of src_mask as "boundary seed"
        boundary = src_mask > 0
        dist_from_boundary = np.full(shape, float(max(shape)), dtype=np.float32)
        dist_from_boundary[boundary] = 0.0
        current = boundary.copy()
        for step in range(1, edge_width_cells + 2):
            expanded = np.zeros_like(current)
            expanded[1:, :] |= current[:-1, :]
            expanded[:-1, :] |= current[1:, :]
            expanded[:, 1:] |= current[:, :-1]
            expanded[:, :-1] |= current[:, 1:]
            new_cells = expanded & (dist_from_boundary == float(max(shape)))
            dist_from_boundary[new_cells] = float(step)
            current = expanded

    edge_strip = dist_from_boundary < edge_width_cells

    # Linearly taper boost: full at boundary, zero at edge_width_cells
    taper = np.where(
        edge_strip,
        1.0 - dist_from_boundary / float(edge_width_cells),
        0.0,
    ).astype(np.float32)

    boost = taper * edge_boost_factor

    return VegetationLayers(
        canopy_density=vegetation.canopy_density.copy(),
        understory_density=np.clip(
            vegetation.understory_density + boost, 0.0, 1.0
        ).astype(np.float32),
        shrub_density=np.clip(
            vegetation.shrub_density + boost * 0.75, 0.0, 1.0
        ).astype(np.float32),
        ground_cover_density=vegetation.ground_cover_density.copy(),
    )


# ---------------------------------------------------------------------------
# Cultivated zones
# ---------------------------------------------------------------------------


def apply_cultivated_zones(
    vegetation: VegetationLayers,
    cultivation_mask: np.ndarray,
    intent=None,
    cultivated_density: float = 0.9,
    row_spacing: int = 4,
) -> VegetationLayers:
    # Ensure cultivated_density survives the float64→float32 cast without
    # rounding below the requested value (np.float32(0.9) < 0.9 in Python).
    _f32 = np.float32(cultivated_density)
    if float(_f32) < cultivated_density:
        cultivated_density = float(np.nextafter(_f32, np.float32(1.0)))
    """Override vegetation in cultivated zones from intent or a mask.

    (a) Clears natural vegetation inside each zone's bounding box.
    (b) Stamps cultivated species density in a row pattern:
        ``density[row::row_spacing, :] = cultivated_density``
        within each zone, giving an agricultural / structured appearance.

    When intent provides ``composition_hints['cultivated_zones']`` (a list
    of BBox-like objects with ``bounds``/``to_cell_slice``), those zones are
    processed individually. Otherwise the boolean ``cultivation_mask`` is
    used as a single zone covering the entire mask.
    """
    base_mask = np.asarray(cultivation_mask, dtype=bool)
    shape = vegetation.canopy_density.shape
    if base_mask.shape != shape:
        raise ValueError("cultivation_mask shape must match vegetation layers")

    # Use float64 working arrays so scalar assignments like 0.9 survive
    # without float32 rounding (np.float32(0.9) < 0.9 in Python float space).
    canopy = vegetation.canopy_density.astype(np.float64)
    understory = vegetation.understory_density.astype(np.float64)
    shrub = vegetation.shrub_density.astype(np.float64)
    ground = vegetation.ground_cover_density.astype(np.float64)

    # Resolve zone list from intent composition hints
    zones_from_intent = []
    if intent is not None:
        hints = getattr(intent, "composition_hints", None) or {}
        zones_from_intent = hints.get("cultivated_zones", [])

    if zones_from_intent:
        for zone in zones_from_intent:
            # Resolve cell slice from zone — support both BBox and objects with .bounds
            if hasattr(zone, "to_cell_slice"):
                z_bbox = zone
            elif hasattr(zone, "bounds"):
                z_bbox = zone.bounds
            else:
                continue

            # Need stack-like origin/cell_size — fall back to operating on full mask
            # zones without coordinate context are applied to the full array; callers
            # that have a stack should call this via pass_vegetation_depth.
            # Here we honour the presence of a ``stack`` attribute on intent if set.
            stack = getattr(intent, "_stack", None)
            if stack is not None:
                r_sl, c_sl = z_bbox.to_cell_slice(
                    stack.world_origin_x,
                    stack.world_origin_y,
                    stack.cell_size,
                    shape,
                )
            else:
                r_sl, c_sl = slice(None), slice(None)

            rows_in_zone = range(*r_sl.indices(shape[0]))

            # (a) Clear natural vegetation; fill ground with baseline cultivated density
            canopy[r_sl, c_sl] = 0.05
            understory[r_sl, c_sl] = 0.02
            shrub[r_sl, c_sl] = 0.05
            ground[r_sl, c_sl] = float(cultivated_density)

            # (b) Boost crop-row cells to 1.0 for structured row-pattern appearance
            for row_idx in rows_in_zone:
                if row_idx % row_spacing == 0:
                    ground[row_idx, c_sl] = 1.0
    else:
        # Fall back to the boolean mask as a single zone
        rows_count, cols_count = shape
        canopy[base_mask] = 0.05
        understory[base_mask] = 0.02
        shrub[base_mask] = 0.05
        # Baseline: whole mask gets cultivated_density
        ground[base_mask] = float(cultivated_density)

        # Boost crop rows to 1.0 within the mask
        for row_idx in range(rows_count):
            if row_idx % row_spacing == 0:
                row_in_mask = base_mask[row_idx, :]
                ground[row_idx, row_in_mask] = 1.0

    return VegetationLayers(
        canopy_density=canopy.astype(np.float32),
        understory_density=understory.astype(np.float32),
        shrub_density=shrub.astype(np.float32),
        ground_cover_density=ground.astype(np.float32),
    )


# ---------------------------------------------------------------------------
# Allelopathic exclusion
# ---------------------------------------------------------------------------


def apply_allelopathic_exclusion(
    vegetation: VegetationLayers,
    species_density_dict: Optional[Dict[str, np.ndarray]] = None,
    allelopathic_species: Optional[List[str]] = None,
    allelopathy_radius_cells: int = 5,
    suppression_weight: float = 0.7,
    # Legacy two-mask interface kept for backward compat
    species_a_mask: Optional[np.ndarray] = None,
    species_b_mask: Optional[np.ndarray] = None,
) -> VegetationLayers:
    """Suppress neighboring species density around allelopathic plants.

    Dict interface (preferred)
    --------------------------
    ``species_density_dict``: mapping of species name -> (H, W) density array.
    ``allelopathic_species``: names of species that suppress others.

    For each allelopathic species S:
    - Convolve its density map with a circular suppression kernel of radius
      ``allelopathy_radius_cells`` using ``scipy.ndimage.uniform_filter``
      (or a manual box-filter fallback).
    - For every OTHER species T, multiply its density by
      ``1 - suppression_weight * convolved_suppressor``.

    The four VegetationLayers channels are updated in-place via the
    ``species_density_dict`` values (canopy/understory/shrub/ground_cover).

    Legacy interface
    ----------------
    When ``species_a_mask``/``species_b_mask`` are provided instead,
    the original two-mask suppression behaviour is used unchanged.
    """
    shape = vegetation.canopy_density.shape

    # --- Legacy two-mask path ---
    # Triggered when: species_density_dict is None, OR when the caller passed
    # ndarrays positionally (old signature was (vegetation, a_mask, b_mask)).
    # In the positional case, species_density_dict holds a_mask and
    # allelopathic_species holds b_mask.
    if species_density_dict is None or isinstance(species_density_dict, np.ndarray):
        if isinstance(species_density_dict, np.ndarray):
            # Positional legacy call: remap to named slots
            _a_raw = species_density_dict
            _b_raw = allelopathic_species if isinstance(allelopathic_species, np.ndarray) else species_b_mask
        else:
            _a_raw = species_a_mask
            _b_raw = species_b_mask
        a = np.asarray(_a_raw, dtype=np.float32) if _a_raw is not None else np.zeros(shape, dtype=np.float32)
        b = np.asarray(_b_raw, dtype=np.float32) if _b_raw is not None else np.zeros(shape, dtype=np.float32)
        if a.shape != shape:
            raise ValueError("species_a_mask shape mismatch")
        if b.shape != shape:
            raise ValueError("species_b_mask shape mismatch")
        suppression = np.clip(b, 0.0, 1.0)
        understory = (vegetation.understory_density * (1.0 - suppression * 0.8)).astype(np.float32)
        shrub = (vegetation.shrub_density * (1.0 - suppression * 0.7)).astype(np.float32)
        ground_cover = (vegetation.ground_cover_density * (1.0 - suppression * 0.6)).astype(np.float32)
        return VegetationLayers(
            canopy_density=vegetation.canopy_density.copy(),
            understory_density=understory,
            shrub_density=shrub,
            ground_cover_density=ground_cover,
        )

    # --- Dict / per-species path ---
    if allelopathic_species is None:
        allelopathic_species = list(species_density_dict.keys())

    # Work on mutable copies keyed by name
    densities: Dict[str, np.ndarray] = {
        k: np.asarray(v, dtype=np.float32).copy()
        for k, v in species_density_dict.items()
    }

    kernel_size = max(3, int(allelopathy_radius_cells * 2 + 1))

    for suppressor_name in allelopathic_species:
        if suppressor_name not in densities:
            continue
        suppressor_map = densities[suppressor_name]

        # Convolve suppressor density to build influence field
        if _SCIPY_OK:
            suppression_field = _ndimage.uniform_filter(
                suppressor_map.astype(np.float64),
                size=kernel_size,
            ).astype(np.float32)
        else:
            # Manual row-then-column box filter fallback
            tmp = suppressor_map.copy()
            half = kernel_size // 2
            # Row-wise cumsum
            cs = np.cumsum(tmp, axis=1)
            row_filtered = np.zeros_like(tmp)
            row_filtered[:, half:-half] = (cs[:, kernel_size - 1:] - np.hstack([np.zeros((tmp.shape[0], 1)), cs[:, :-kernel_size]])) / kernel_size
            # Col-wise cumsum
            cs2 = np.cumsum(row_filtered, axis=0)
            suppression_field = np.zeros_like(tmp)
            suppression_field[half:-half, :] = (cs2[kernel_size - 1:, :] - np.vstack([np.zeros((1, tmp.shape[1])), cs2[:-kernel_size, :]])) / kernel_size

        suppression_field = np.clip(suppression_field, 0.0, 1.0)

        # Suppress all other species
        for target_name, target_map in densities.items():
            if target_name == suppressor_name:
                continue
            densities[target_name] = np.clip(
                target_map * (1.0 - suppression_weight * suppression_field),
                0.0,
                1.0,
            ).astype(np.float32)

    # Write back to VegetationLayers channels
    canopy = densities.get("canopy", vegetation.canopy_density.copy())
    understory = densities.get("understory", vegetation.understory_density.copy())
    shrub = densities.get("shrub", vegetation.shrub_density.copy())
    ground_cover = densities.get("ground_cover", vegetation.ground_cover_density.copy())

    return VegetationLayers(
        canopy_density=canopy.astype(np.float32),
        understory_density=understory.astype(np.float32),
        shrub_density=shrub.astype(np.float32),
        ground_cover_density=ground_cover.astype(np.float32),
    )


# ---------------------------------------------------------------------------
# Pass entry point
# ---------------------------------------------------------------------------


def pass_vegetation_depth(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Write 4-layer vegetation density into ``stack.detail_density``.

    Contract
    --------
    Consumes: height (+ optional slope, wetness, wind_field)
    Produces: detail_density (dict with canopy/understory/shrub/ground_cover)
    Respects protected zones: yes
    Requires scene read: yes
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: List[ValidationIssue] = []
    r_slice, c_slice = _region_slice(state, region)
    protected = _protected_mask(state, stack.height.shape, "vegetation_depth")

    seed = derive_pass_seed(
        state.intent.seed,
        "vegetation_depth",
        state.tile_x,
        state.tile_y,
        region,
    )

    hints = dict(state.intent.composition_hints) if state.intent else {}
    biome = getattr(state.intent, "biome_rules", None) or "dark_fantasy_default"
    layers = compute_vegetation_layers(stack, biome=biome)

    # --- Layer modifiers ---
    if hints.get("veg_edge_effects", True):
        biome_arr = stack.get("biome_id")
        forest_arr = stack.get("forest_mask")
        # Build biome boundary mask if biome_id is available
        biome_boundary = None
        if biome_arr is not None:
            ba = np.asarray(biome_arr, dtype=np.int32)
            boundary = np.zeros(ba.shape, dtype=bool)
            boundary[1:, :] |= ba[1:, :] != ba[:-1, :]
            boundary[:-1, :] |= ba[:-1, :] != ba[1:, :]
            boundary[:, 1:] |= ba[:, 1:] != ba[:, :-1]
            boundary[:, :-1] |= ba[:, :-1] != ba[:, 1:]
            biome_boundary = boundary.astype(np.uint8)
        # Forest mask: use channel if available, else derive from canopy
        if forest_arr is not None:
            fmask = np.asarray(forest_arr, dtype=np.uint8)
        else:
            fmask = (layers.canopy_density > 0.35).astype(np.uint8)
        layers = apply_edge_effects(
            layers,
            forest_mask=fmask,
            biome_boundary_mask=biome_boundary,
        )

    if hints.get("veg_cultivated_zones", False):
        cult = stack.get("gameplay_zone")
        if cult is not None:
            cult_mask = np.asarray(cult, dtype=np.int32) == 2
            # Attach stack to intent so apply_cultivated_zones can resolve BBox coords
            _intent = state.intent
            _intent._stack = stack  # type: ignore[attr-defined]
            layers = apply_cultivated_zones(layers, cult_mask, intent=_intent)

    if hints.get("veg_allelopathic_exclusion", True):
        species_dict = layers.as_dict()
        # Canopy is the default allelopathic suppressor (tall trees = walnut/pine)
        layers = apply_allelopathic_exclusion(
            layers,
            species_density_dict=species_dict,
            allelopathic_species=["canopy"],
        )

    # --- Feature generators (results stored in metrics) ---
    disturbance_patches: List = []
    if hints.get("veg_disturbance_patches", False):
        disturbance_patches = detect_disturbance_patches(
            stack, seed, intent=state.intent
        )

    # Build shared detail_density dict for clearings + logs to stamp into
    existing = stack.detail_density or {}
    merged: Dict[str, np.ndarray] = {k: np.asarray(v).copy() for k, v in existing.items()}
    keys = ("canopy", "understory", "shrub", "ground_cover")
    sources = (
        layers.canopy_density,
        layers.understory_density,
        layers.shrub_density,
        layers.ground_cover_density,
    )
    for key, src in zip(keys, sources):
        prev = merged.get(key)
        if prev is None or prev.shape != src.shape:
            prev = np.zeros_like(src)
        target_arr = prev.copy()
        region_src = src[r_slice, c_slice]
        region_protected = protected[r_slice, c_slice]
        region_prev = prev[r_slice, c_slice]
        region_out = np.where(region_protected, region_prev, region_src).astype(np.float32)
        target_arr[r_slice, c_slice] = region_out
        merged[key] = target_arr.astype(np.float32)

    clearings: List = []
    if hints.get("veg_clearings", False):
        clearings = place_clearings(
            stack, state.intent, seed=seed, detail_density=merged
        )

    fallen_logs: List = []
    if hints.get("veg_fallen_logs", False):
        forest_mask = merged.get("canopy", layers.canopy_density) > 0.3
        fallen_logs = place_fallen_logs(
            stack, forest_mask, seed, detail_density=merged
        )

    stack.detail_density = merged
    stack.populated_by_pass["detail_density"] = "vegetation_depth"

    total_density = float(
        sum(float(arr.mean()) for arr in merged.values() if arr.size)
    )

    return PassResult(
        pass_name="vegetation_depth",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("detail_density",),
        metrics={
            "layers": len(merged),
            "mean_density_sum": total_density,
            "biome": biome,
            "disturbance_patch_count": len(disturbance_patches),
            "clearing_count": len(clearings),
            "fallen_log_count": len(fallen_logs),
        },
        issues=issues,
        seed_used=seed,
    )


def register_vegetation_depth_pass() -> None:
    TerrainPassController.register_pass(
        PassDefinition(
            name="vegetation_depth",
            func=pass_vegetation_depth,
            requires_channels=("height",),
            produces_channels=("detail_density",),
            seed_namespace="vegetation_depth",
            requires_scene_read=True,
            description="Bundle O — 4-layer vegetation stratification.",
        )
    )


__all__ = [
    "VegetationLayer",
    "VegetationLayers",
    "DisturbancePatch",
    "Clearing",
    "FallenLogSpec",
    "compute_vegetation_layers",
    "detect_disturbance_patches",
    "place_clearings",
    "place_fallen_logs",
    "apply_edge_effects",
    "apply_cultivated_zones",
    "apply_allelopathic_exclusion",
    "pass_vegetation_depth",
    "register_vegetation_depth_pass",
]

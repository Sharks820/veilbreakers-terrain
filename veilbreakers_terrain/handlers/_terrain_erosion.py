"""Pure-logic hydraulic and thermal erosion on numpy heightmap arrays.

Bundle A refactor: the new ``*_masks`` entry points return rich
``ErosionMasks`` / ``ThermalErosionMasks`` dataclasses exposing every
intermediate signal (erosion_amount, deposition_amount, wetness, drainage,
bank_instability, talus). The legacy ``apply_hydraulic_erosion`` /
``apply_thermal_erosion`` functions remain as compat wrappers that return
only the eroded ``np.ndarray`` clamped to the source range (preserving
existing callers and tests).

NO bpy/bmesh imports. All functions accept numpy arrays and return numpy
arrays (or ErosionMasks containing numpy arrays) of the same shape.
Fully testable without Blender.

Provides:
  - apply_hydraulic_erosion      (legacy np.ndarray return)
  - apply_hydraulic_erosion_masks (new, returns ErosionMasks)
  - apply_thermal_erosion        (legacy np.ndarray return)
  - apply_thermal_erosion_masks  (new, returns ThermalErosionMasks)
  - ErosionMasks, ThermalErosionMasks dataclasses
"""

from __future__ import annotations

import math
import random as _random
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ErosionMasks:
    """Complete output of droplet-based hydraulic erosion.

    All fields share the heightmap shape (H, W). ``height`` is NOT clipped
    to the input range — it holds the true world-unit eroded surface.
    """

    height: np.ndarray
    erosion_amount: np.ndarray      # per-cell net material removed (>= 0)
    deposition_amount: np.ndarray   # per-cell net material added (>= 0)
    wetness: np.ndarray             # accumulated droplet water-step contact
    drainage: np.ndarray            # log1p of droplet pass-through count
    bank_instability: np.ndarray    # curvature magnitude where wetness > 0
    # Addendum 1 D.1 — sediment accumulation & pool deepening
    sediment_accumulation_at_base: np.ndarray = field(default=None)  # type: ignore[assignment]
    pool_deepening_delta: np.ndarray = field(default=None)           # type: ignore[assignment]
    ridge_map: Optional[np.ndarray] = None  # analytical erosion ridge map (-1 crease, +1 ridge)
    metrics: dict = field(default_factory=dict)


@dataclass
class ThermalErosionMasks:
    """Complete output of talus-angle thermal erosion.

    All fields share the heightmap shape (H, W).

    Fields
    ------
    height : np.ndarray
        Eroded heightmap after all iterations.
    talus : np.ndarray
        Accumulated material moved per cell (sum of |transfer| across all
        iterations). Non-negative.
    erosion_depth : np.ndarray
        Per-cell total height removed by thermal erosion (>= 0). Equal to
        max(0, h_in - height) at cells where material was transported away.
    deposition_depth : np.ndarray
        Per-cell total height added by thermal redeposition (>= 0). Equal to
        max(0, height - h_in) at cells where material was received.
    flow_accumulation : np.ndarray
        Proxy for cumulative material flux: sum of material received by each
        cell weighted by the number of contributing upslope neighbours.
        Computed as the running tally of ``amount`` deposited into each cell
        across all iterations and directions.
    metrics : dict
    """

    height: np.ndarray
    talus: np.ndarray               # accumulated material moved per cell
    erosion_depth: np.ndarray = field(default=None)    # type: ignore[assignment]
    deposition_depth: np.ndarray = field(default=None) # type: ignore[assignment]
    flow_accumulation: np.ndarray = field(default=None)# type: ignore[assignment]
    metrics: dict = field(default_factory=dict)


@dataclass
class ErosionConfig:
    """Configuration for erosion operations.

    Covers both the analytical erosion filter (runevision/lpmitchell port,
    fields: strength … frequency) and droplet-based hydraulic erosion
    (Olsen 2004 / Lague particle model, fields: particle_count …
    hardness_factor).  Per-biome overrides are supported by lerping two
    configs at boundaries.

    Analytical filter fields (12)
    -----------------------------
    strength, gully_weight, detail, rounding, ridge_rounding, onset,
    assumed_slope, normalization, fade_amplitude, exit_slope_threshold,
    cell_scale, octave_count, frequency.

    Hydraulic particle fields (7)
    -----------------------------
    particle_count : int
        Number of water droplets to simulate per erosion pass (default 4000).
        Olsen (2004) recommends ≥ 1000 for 256² maps; scale proportionally.
    rain_amount : float
        Initial water volume per droplet (default 1.0). Analogous to rainfall
        intensity; controls how much material each droplet can carry.
    evaporation_rate : float
        Fraction of water lost per simulation step (default 0.01).
        Range [0, 1]; 0.01 → ~63 % of water remains after 50 steps.
    sediment_capacity_factor : float
        Scales the maximum sediment a droplet can carry (default 4.0).
        Benes (2006) grid-based equivalent: silt transport capacity.
        Higher values → deeper channels, more pronounced erosion.
    erosion_rate : float
        Fraction of capacity deficit eroded per step (default 0.3).
        Range [0, 1]; controls how aggressively sediment is picked up.
    deposition_rate : float
        Fraction of sediment excess deposited per step (default 0.3).
        Range [0, 1]; controls how quickly sediment settles out.
    hardness_factor : float
        Erodibility multiplier applied globally (default 1.0). Values < 1
        simulate harder rock (less erodible); > 1 = soft sediment. Overridden
        cell-by-cell when an erodibility_map is supplied to the erosion call.
    """

    # --- Analytical filter ---
    strength: float = 0.5
    gully_weight: float = 1.0
    detail: float = 0.5
    rounding: float = 0.0        # crease rounding: lifts valley bottoms toward zero
    ridge_rounding: float = 0.0  # ridge rounding: attenuates sharp peak tops
    onset: float = 0.0
    assumed_slope: float = 0.0
    normalization: float = 0.4
    fade_amplitude: float = 0.6
    exit_slope_threshold: float = 0.0075
    cell_scale: float = 1.0
    octave_count: int = 4
    frequency: float = 1.0

    # --- Hydraulic particle (Olsen 2004 / Lague) ---
    particle_count: int = 4000
    rain_amount: float = 1.0
    evaporation_rate: float = 0.01
    sediment_capacity_factor: float = 4.0
    erosion_rate: float = 0.3
    deposition_rate: float = 0.3
    hardness_factor: float = 1.0


@dataclass
class AnalyticalErosionResult:
    """Output of the analytical erosion filter.

    All array fields share the heightmap shape (H, W).

    Fields
    ------
    height_delta : np.ndarray
        Per-point additive height offset from erosion.
    ridge_map : np.ndarray
        -1 on creases (rivers), +1 on ridges.
    gradient_x : np.ndarray
        Analytical dh/dx after all octaves.
    gradient_z : np.ndarray
        Analytical dh/dz after all octaves.
    erosion_depth : np.ndarray
        Absolute depth of material removed per point: max(0, -height_delta).
        Zero where height_delta >= 0 (net deposition or neutral).
    deposition_depth : np.ndarray
        Absolute thickness of material deposited per point: max(0, height_delta).
        Zero where height_delta <= 0 (net erosion or neutral).
    flow_accumulation : np.ndarray
        Proxy for drainage area: ridge_map remapped so creases (rivers, -1)
        map to 1.0 and ridges (+1) map to 0.0.  Provides a dimensionless
        flow-accumulation signal usable for river-channel masking without
        a separate D8 solver pass.
    metrics : dict
    """

    height_delta: np.ndarray       # per-point height offset from erosion
    ridge_map: np.ndarray           # -1 creases, +1 ridges
    gradient_x: np.ndarray          # analytical dh/dx
    gradient_z: np.ndarray          # analytical dh/dz
    erosion_depth: np.ndarray = field(default=None)    # type: ignore[assignment]
    deposition_depth: np.ndarray = field(default=None) # type: ignore[assignment]
    flow_accumulation: np.ndarray = field(default=None)# type: ignore[assignment]
    metrics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Hydraulic erosion — new masks entry point
# ---------------------------------------------------------------------------


def apply_hydraulic_erosion_masks(
    heightmap: np.ndarray,
    iterations: int = 1000,
    seed: int = 0,
    inertia: float = 0.05,
    capacity: float = 4.0,
    deposition: float = 0.3,
    erosion_rate: float = 0.3,
    evaporation: float = 0.01,
    min_slope: float = 0.01,
    radius: int = 3,
    max_lifetime: int = 30,
    height_range: Optional[float] = None,
    *,
    hero_exclusion: Optional[np.ndarray] = None,
    erodibility_map: Optional[np.ndarray] = None,
    erosion_mask: Optional[np.ndarray] = None,
    deposition_mask: Optional[np.ndarray] = None,
    erosion_mask_threshold: float = 0.5,
    deposition_mask_threshold: float = 0.5,
) -> ErosionMasks:
    """Apply droplet-based hydraulic erosion with per-channel spatial masks.

    Extends droplet erosion with two spatial control maps matching Houdini's
    HeightField Erode SOP ``Erodibility`` and ``Deposition`` layers:

    - ``erosion_mask``: float [0,1] per-cell map. Erosion is permitted only
      where ``erosion_mask > erosion_mask_threshold``. Cells below the
      threshold are erosion-protected (soft rock / hero zones). The mask
      multiplies the per-cell ``_erod_scale`` if erodibility_map is also set.
    - ``deposition_mask``: float [0,1] per-cell map. Deposition is permitted
      only where ``deposition_mask > deposition_mask_threshold``. Confines
      alluvial fan / delta deposition to target basin/valley zones.

    When a mask is None, that channel is unrestricted (all-ones equivalent).

    The extra ``hero_exclusion`` boolean mask overrides both erosion and
    deposition at the cell level regardless of the above masks.

    The returned ``height`` is NOT clipped — it reflects the true
    world-unit eroded surface including any out-of-source-range values.

    Parameters
    ----------
    erosion_mask : np.ndarray (H, W) float [0, 1] or None
        Spatial mask controlling where erosion is permitted.
        Values <= erosion_mask_threshold → erosion blocked at that cell.
    deposition_mask : np.ndarray (H, W) float [0, 1] or None
        Spatial mask controlling where deposition is permitted.
        Values <= deposition_mask_threshold → deposition blocked at that cell.
    erosion_mask_threshold : float
        Threshold above which erosion is permitted (default 0.5).
    deposition_mask_threshold : float
        Threshold above which deposition is permitted (default 0.5).

    Returns
    -------
    ErosionMasks
        Contains height plus erosion_amount, deposition_amount, wetness,
        drainage, bank_instability, and a metrics dict with
        erosion_mask_applied and deposition_mask_applied flags.
    """
    h_in = np.asarray(heightmap, dtype=np.float64)
    result = h_in.copy()
    rows, cols = result.shape
    rng = _random.Random(seed)
    requested_iterations = max(0, int(iterations))
    simulated_iterations = requested_iterations
    small_tile_iteration_cap = requested_iterations
    cell_count = max(1, rows * cols)
    if requested_iterations > 0 and cell_count < 1024 * 1024:
        tile_scale = math.sqrt(cell_count / float(1024 * 1024))
        representative_budget = int(round(50000 * tile_scale))
        small_tile_iteration_cap = max(2048, min(8192, representative_budget))
        simulated_iterations = min(requested_iterations, small_tile_iteration_cap)

    source_min = float(h_in.min()) if h_in.size else 0.0
    source_max = float(h_in.max()) if h_in.size else 0.0
    input_range = (
        float(height_range)
        if height_range is not None
        else max(source_max - source_min, 1e-12)
    )
    effective_min_slope = min_slope * max(input_range, 1e-12)

    erosion_amount = np.zeros_like(result, dtype=np.float64)
    deposition_amount = np.zeros_like(result, dtype=np.float64)
    wetness = np.zeros_like(result, dtype=np.float64)
    drainage_count = np.zeros_like(result, dtype=np.float64)

    if hero_exclusion is not None:
        hero_mask = np.asarray(hero_exclusion, dtype=bool)
        if hero_mask.shape != result.shape:
            raise ValueError(
                f"hero_exclusion shape {hero_mask.shape} does not match "
                f"heightmap shape {result.shape}"
            )
    else:
        hero_mask = None

    if erodibility_map is not None:
        erod_arr = np.asarray(erodibility_map, dtype=np.float64)
        if erod_arr.shape != result.shape:
            raise ValueError(
                f"erodibility_map shape {erod_arr.shape} does not match "
                f"heightmap shape {result.shape}"
            )
        # Erodibility is a normalized multiplier, not an absolute stream-power K.
        # Values outside [0, 1] are clamped so callers cannot amplify droplets
        # into a terrain-flattening pass.
        _erod_scale = np.clip(erod_arr, 0.0, 1.0)
    else:
        _erod_scale = None

    # Validate and store per-channel spatial masks
    _erosion_mask: Optional[np.ndarray] = None
    if erosion_mask is not None:
        _erosion_mask = np.asarray(erosion_mask, dtype=np.float64)
        if _erosion_mask.shape != result.shape:
            raise ValueError(
                f"erosion_mask shape {_erosion_mask.shape} does not match "
                f"heightmap shape {result.shape}"
            )

    _deposition_mask: Optional[np.ndarray] = None
    if deposition_mask is not None:
        _deposition_mask = np.asarray(deposition_mask, dtype=np.float64)
        if _deposition_mask.shape != result.shape:
            raise ValueError(
                f"deposition_mask shape {_deposition_mask.shape} does not match "
                f"heightmap shape {result.shape}"
            )

    for _ in range(simulated_iterations):
        px = rng.random() * (cols - 2) + 0.5
        py = rng.random() * (rows - 2) + 0.5
        dx_dir = 0.0
        dy_dir = 0.0
        speed = 1.0
        water = 1.0
        sediment = 0.0

        for _step in range(max_lifetime):
            ix = int(px)
            iy = int(py)

            if ix < 1 or ix >= cols - 2 or iy < 1 or iy >= rows - 2:
                break

            fx = px - ix
            fy = py - iy

            h00 = result[iy, ix]
            h10 = result[iy, ix + 1]
            h01 = result[iy + 1, ix]
            h11 = result[iy + 1, ix + 1]

            grad_x = (h10 - h00) * (1 - fy) + (h11 - h01) * fy
            grad_y = (h01 - h00) * (1 - fx) + (h11 - h10) * fx

            dx_dir = dx_dir * inertia - grad_x * (1 - inertia)
            dy_dir = dy_dir * inertia - grad_y * (1 - inertia)

            length = math.sqrt(dx_dir * dx_dir + dy_dir * dy_dir)
            if length < 1e-10:
                angle = rng.random() * 2 * math.pi
                dx_dir = math.cos(angle)
                dy_dir = math.sin(angle)
            else:
                dx_dir /= length
                dy_dir /= length

            new_px = px + dx_dir
            new_py = py + dy_dir

            nix = int(new_px)
            niy = int(new_py)
            if nix < 0 or nix >= cols - 1 or niy < 0 or niy >= rows - 1:
                break

            new_fx = new_px - nix
            new_fy = new_py - niy
            new_h = (
                result[niy, nix] * (1 - new_fx) * (1 - new_fy)
                + result[niy, min(nix + 1, cols - 1)] * new_fx * (1 - new_fy)
                + result[min(niy + 1, rows - 1), nix] * (1 - new_fx) * new_fy
                + result[min(niy + 1, rows - 1), min(nix + 1, cols - 1)]
                * new_fx
                * new_fy
            )
            old_h = (
                h00 * (1 - fx) * (1 - fy)
                + h10 * fx * (1 - fy)
                + h01 * (1 - fx) * fy
                + h11 * fx * fy
            )
            h_diff = new_h - old_h

            c = max(-h_diff, effective_min_slope) * speed * water * capacity

            # Record wetness and drainage at current cell
            wetness[iy, ix] += water
            drainage_count[iy, ix] += 1.0

            # Hero-exclusion: skip this droplet-cell if ANY of the 4
            # bilinear-corner cells is inside a protected zone.
            skip_cell = False
            if hero_mask is not None:
                if (
                    bool(hero_mask[iy, ix])
                    or bool(hero_mask[iy, min(ix + 1, cols - 1)])
                    or bool(hero_mask[min(iy + 1, rows - 1), ix])
                    or bool(hero_mask[min(iy + 1, rows - 1), min(ix + 1, cols - 1)])
                ):
                    skip_cell = True

            # Per-channel mask checks (evaluated per droplet step)
            can_erode = not skip_cell
            can_deposit = not skip_cell
            if _erosion_mask is not None:
                if float(_erosion_mask[iy, ix]) <= erosion_mask_threshold:
                    can_erode = False
            if _deposition_mask is not None:
                if float(_deposition_mask[iy, ix]) <= deposition_mask_threshold:
                    can_deposit = False

            if sediment > c or h_diff > 0:
                if h_diff > 0:
                    deposit_amount = min(sediment, h_diff)
                else:
                    deposit_amount = (sediment - c) * deposition
                if not can_deposit:
                    deposit_amount = 0.0
                sediment -= deposit_amount
                if deposit_amount != 0.0:
                    _deposit(result, ix, iy, fx, fy, deposit_amount)
                    _deposit(deposition_amount, ix, iy, fx, fy, deposit_amount)
            else:
                erode_amount = min((c - sediment) * erosion_rate, -h_diff)
                erode_amount = max(erode_amount, 0.0)
                if _erod_scale is not None:
                    erode_amount *= float(_erod_scale[iy, ix])
                if not can_erode:
                    erode_amount = 0.0
                sediment += erode_amount
                if erode_amount != 0.0:
                    _erode_brush(result, ix, iy, erode_amount, radius, rows, cols)
                    _erode_brush(
                        erosion_amount,
                        ix,
                        iy,
                        -erode_amount,  # negate so erosion_amount accumulates positively
                        radius,
                        rows,
                        cols,
                    )

            normalized_h_diff = h_diff / max(input_range, 1e-12)
            speed = math.sqrt(max(speed * speed + normalized_h_diff, 0.01))
            water *= (1 - evaporation)

            px = new_px
            py = new_py

            if water < 0.001:
                # Mass conservation (Benes et al. 2006): deposit remaining
                # sediment at the particle's FINAL position (new_px, new_py)
                # rather than the pre-move cell.  The prior implementation
                # used (ix, iy, fx, fy) which are still the PRE-move indices,
                # silently shifting mass one cell upstream each evaporation
                # and producing cumulative drift at high iteration counts.
                if sediment > 0.0:
                    fix_i = int(new_px)
                    fiy_i = int(new_py)
                    if 1 <= fix_i < cols - 2 and 1 <= fiy_i < rows - 2:
                        ffx = new_px - fix_i
                        ffy = new_py - fiy_i
                        _deposit(result, fix_i, fiy_i, ffx, ffy, sediment)
                        _deposit(deposition_amount, fix_i, fiy_i, ffx, ffy, sediment)
                break

    # drainage → log1p of droplet count
    drainage = np.log1p(drainage_count)

    # bank_instability: local curvature (Laplacian) where wetness > 0
    padded = np.pad(result, 1, mode="edge")
    d2dx2 = padded[1:-1, 2:] - 2.0 * result + padded[1:-1, :-2]
    d2dy2 = padded[2:, 1:-1] - 2.0 * result + padded[:-2, 1:-1]
    curvature = d2dx2 + d2dy2
    bank_instability = np.where(wetness > 0.0, np.abs(curvature), 0.0)

    # Normalize wetness to 0..1 (relative)
    max_wet = float(wetness.max()) if wetness.size else 0.0
    wetness_norm = wetness / max_wet if max_wet > 0.0 else wetness

    # Addendum 1 D.1 — derive sediment accumulation and pool deepening
    padded_h = np.pad(result, 1, mode="edge")
    grad_x = padded_h[1:-1, 2:] - padded_h[1:-1, :-2]
    grad_y = padded_h[2:, 1:-1] - padded_h[:-2, 1:-1]
    slope_mag = np.sqrt(grad_x ** 2 + grad_y ** 2)
    inv_slope = 1.0 / (1.0 + slope_mag)
    sediment_accumulation_at_base = deposition_amount * inv_slope

    height_delta = h_in - result  # positive where material was removed
    if wetness_norm.size > 0:
        wet_median = float(np.median(wetness_norm))
    else:
        wet_median = 0.0
    pool_mask = wetness_norm > max(wet_median, 0.01)
    pool_deepening_delta = np.where(pool_mask, np.maximum(height_delta, 0.0), 0.0)

    return ErosionMasks(
        height=result,
        erosion_amount=erosion_amount,
        deposition_amount=deposition_amount,
        wetness=wetness_norm,
        drainage=drainage,
        bank_instability=bank_instability,
        sediment_accumulation_at_base=sediment_accumulation_at_base,
        pool_deepening_delta=pool_deepening_delta,
        metrics={
            "iterations": int(simulated_iterations),
            "iterations_requested": int(requested_iterations),
            "iteration_cap_applied": bool(simulated_iterations != requested_iterations),
            "small_tile_iteration_cap": int(small_tile_iteration_cap),
            "source_min": source_min,
            "source_max": source_max,
            "input_range": input_range,
            "max_wetness": max_wet,
            "total_erosion": float(erosion_amount.sum()),
            "total_deposition": float(deposition_amount.sum()),
            "total_sediment_at_base": float(sediment_accumulation_at_base.sum()),
            "total_pool_deepening": float(pool_deepening_delta.sum()),
            "erosion_mask_applied": _erosion_mask is not None,
            "deposition_mask_applied": _deposition_mask is not None,
        },
    )


def apply_hydraulic_erosion(
    heightmap: np.ndarray,
    iterations: int = 1000,
    seed: int = 0,
    inertia: float = 0.05,
    capacity: float = 4.0,
    deposition: float = 0.3,
    erosion_rate: float = 0.3,
    evaporation: float = 0.01,
    min_slope: float = 0.01,
    radius: int = 3,
    max_lifetime: int = 30,
    height_range: Optional[float] = None,
) -> np.ndarray:
    """Legacy compat wrapper — returns the eroded heightmap np.ndarray only.

    Clamps output to the source value range for behavior parity with
    pre-Bundle-A callers. New code should call ``apply_hydraulic_erosion_masks``.
    """
    h_in = np.asarray(heightmap, dtype=np.float64)
    source_min = float(h_in.min()) if h_in.size else 0.0
    source_max = float(h_in.max()) if h_in.size else 0.0
    masks = apply_hydraulic_erosion_masks(
        h_in,
        iterations=iterations,
        seed=seed,
        inertia=inertia,
        capacity=capacity,
        deposition=deposition,
        erosion_rate=erosion_rate,
        evaporation=evaporation,
        min_slope=min_slope,
        radius=radius,
        max_lifetime=max_lifetime,
        height_range=height_range,
    )
    return np.clip(masks.height, source_min, source_max)


def _deposit(
    hmap: np.ndarray, ix: int, iy: int, fx: float, fy: float, amount: float
) -> None:
    """Deposit material at (ix, iy) using bilinear weights."""
    rows, cols = hmap.shape
    if iy < 0 or iy >= rows - 1 or ix < 0 or ix >= cols - 1:
        return
    hmap[iy, ix] += amount * (1 - fx) * (1 - fy)
    hmap[iy, ix + 1] += amount * fx * (1 - fy)
    hmap[iy + 1, ix] += amount * (1 - fx) * fy
    hmap[iy + 1, ix + 1] += amount * fx * fy


@lru_cache(maxsize=32)
def _brush_kernel(radius: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Cached circular erosion brush offsets and linear falloff weights."""
    radius = max(0, int(radius))
    dy_values: list[int] = []
    dx_values: list[int] = []
    weights: list[float] = []
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            dist = math.hypot(dx, dy)
            if dist <= radius:
                weight = max(0.0, radius - dist)
                if weight > 0.0:
                    dy_values.append(dy)
                    dx_values.append(dx)
                    weights.append(weight)
    return (
        np.asarray(dy_values, dtype=np.int32),
        np.asarray(dx_values, dtype=np.int32),
        np.asarray(weights, dtype=np.float64),
    )


def _talus_smooth_local(
    hmap: np.ndarray,
    cx: int,
    cy: int,
    radius: int,
    rows: int,
    cols: int,
    talus_thresh: float,
    passes: int,
) -> None:
    """Vectorized local 4-neighbour talus relaxation over brush bounds."""
    y0 = max(0, cy - radius)
    y1 = min(rows, cy + radius + 1)
    x0 = max(0, cx - radius)
    x1 = min(cols, cx + radius + 1)
    if y1 - y0 < 2 or x1 - x0 < 2:
        return

    sub = hmap[y0:y1, x0:x1]
    for _ in range(passes):
        delta = np.zeros_like(sub)
        for src, dst in (
            ((slice(1, None), slice(None)), (slice(None, -1), slice(None))),
            ((slice(None, -1), slice(None)), (slice(1, None), slice(None))),
            ((slice(None), slice(1, None)), (slice(None), slice(None, -1))),
            ((slice(None), slice(None, -1)), (slice(None), slice(1, None))),
        ):
            diff = sub[src] - sub[dst]
            transfer = np.maximum(diff - talus_thresh, 0.0) * 0.25
            delta[src] -= transfer
            delta[dst] += transfer
        sub += delta


def _erode_brush(
    hmap: np.ndarray,
    cx: int,
    cy: int,
    amount: float,
    radius: int,
    rows: int,
    cols: int,
    *,
    sediment_capacity: float = 1.0,
    talus_smooth_passes: int = 1,
) -> None:
    """Brush-based erosion kernel with radius falloff, sediment capacity, and talus smoothing.

    Improvements over the simple linear-falloff brush:

    1. **Sediment-capacity falloff** — the effective erode amount at each
       cell is scaled by ``sediment_capacity`` (0–1). A cell at full capacity
       receives a reduced erosion contribution (``amount * w * sediment_capacity``).
       This prevents unrealistically deep single-droplet channels and produces
       the rounded channel cross-section characteristic of real river beds.

    2. **Talus smoothing pass** — after the main brush deposit/erode, optional
       1-ring talus smoothing redistributes extreme local height differences
       within the brush footprint. This replicates Houdini HeightField Erode's
       ``Talus Resting Angle`` post-step, softening sharp brush edges and
       producing natural slope transitions at channel banks.

    3. **Distance kernel** — uses ``max(0, radius - dist)`` linear falloff
       (identical to Sebastian Lague's reference implementation), ensuring
       the brush is zero at exactly ``radius`` cells distance.

    When called on ``result`` with positive ``amount`` the brush removes
    material. When called on ``erosion_amount`` with negative ``amount``
    it accumulates absolute removed values (so erosion_amount ≥ 0).

    Parameters
    ----------
    hmap : np.ndarray
        Heightmap array modified in-place.
    cx, cy : int
        Centre cell of the erosion brush.
    amount : float
        Total amount to distribute. Positive → removes from hmap.
    radius : int
        Brush radius in cells.
    rows, cols : int
        Heightmap dimensions for bounds checking.
    sediment_capacity : float
        Capacity factor [0, 1]. 1.0 = full erosion; lower values reduce
        erosion proportionally (soft-capacity cutoff for bank protection).
    talus_smooth_passes : int
        Number of 1-ring talus redistribution passes after the brush
        (default 1). 0 disables smoothing for maximum performance.
    """
    # Clamp capacity
    cap = max(0.0, min(1.0, sediment_capacity))
    effective_amount = amount * cap
    dy_arr, dx_arr, weight_arr = _brush_kernel(radius)
    if weight_arr.size == 0 or effective_amount == 0.0:
        return

    ny = cy + dy_arr
    nx = cx + dx_arr
    valid = (ny >= 0) & (ny < rows) & (nx >= 0) & (nx < cols)
    if not np.any(valid):
        return

    valid_weights = weight_arr[valid]
    total_weight = float(valid_weights.sum())
    if total_weight <= 0.0:
        return

    hmap[ny[valid], nx[valid]] -= (effective_amount / total_weight) * valid_weights

    # --- Talus smoothing passes within the brush footprint ---
    # Redistribute height differences that exceed a local talus threshold.
    # The threshold is set proportional to the brush radius so larger brushes
    # produce smoother banks.
    if talus_smooth_passes > 0 and radius >= 1:
        talus_thresh = abs(amount) / max(total_weight, 1.0) * 0.5
        _talus_smooth_local(hmap, cx, cy, radius, rows, cols, talus_thresh, talus_smooth_passes)


# ---------------------------------------------------------------------------
# Thermal erosion — new masks entry point
# ---------------------------------------------------------------------------


def apply_thermal_erosion_masks(
    heightmap: np.ndarray,
    iterations: int = 10,
    talus_angle: float = 32.0,
    cell_size: float = 1.0,
) -> ThermalErosionMasks:
    """Apply talus-angle thermal erosion and return ThermalErosionMasks.

    Implements bidirectional proportional transport (Musgrave 1989 / d'Amaral
    variant): at each cell, material in excess of the talus threshold is
    transferred proportionally to ALL downslope neighbours, not just the
    steepest one.  This produces natural fan spread and avoids the single-
    channel artefact of max-only redistribution.

    Algorithm per iteration
    -----------------------
    1. For each of 8 neighbours, compute slope excess above ``talus_threshold``
       (= tan(talus_angle)) in world units / cell_size diagonal.
    2. For each source cell ``i``, sum all positive excess values across
       neighbours: ``total_excess[i]``.
    3. Transfer half the maximum excess as the total budget: ``transfer[i]
       = max_excess[i] * 0.5``.  This conservative factor prevents
       over-transfer oscillations between iterations.
    4. Each neighbour receives a fraction of the budget proportional to its
       individual excess / total_excess:
           amount[i→j] = transfer[i] * excess[i→j] / total_excess[i]
    5. Accumulate deltas bidirectionally: subtract from source, add to
       destination.

    Talus angle default
    -------------------
    32° is the median natural angle of repose for loose rock / scree
    (USGS: 30–35° for dry rock fragments, 25–35° for mixed debris).
    40° was the legacy default — too steep for realistic terrain; reduces
    to 32° here per AAA spec.

    Parameters
    ----------
    heightmap : np.ndarray
        Input (H, W) heightmap.
    iterations : int
        Number of thermal erosion passes (default 10).
    talus_angle : float
        Angle of repose in degrees (default 32.0 — dry rock scree).
    cell_size : float
        World-space distance between cells (metres, default 1.0).

    Returns
    -------
    ThermalErosionMasks
        Contains height, talus, erosion_depth, deposition_depth,
        flow_accumulation, and a metrics dict.
    """
    h_in = np.asarray(heightmap, dtype=np.float64)
    result = h_in.copy()
    rows, cols = result.shape

    sample_spacing = max(float(cell_size), 1e-9)
    talus_threshold = math.tan(math.radians(talus_angle))

    # 8-neighbour offsets and their distances (diagonal = sqrt(2))
    offsets = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            dist = math.sqrt(dr * dr + dc * dc)
            offsets.append((dr, dc, dist))

    talus_accumulated = np.zeros_like(result, dtype=np.float64)
    # flow_accumulation: running tally of material received by each cell
    flow_accum = np.zeros_like(result, dtype=np.float64)

    for _iteration in range(iterations):
        delta = np.zeros_like(result)
        padded = np.pad(result, 1, mode="edge")

        accumulated_total_excess = np.zeros_like(result)
        accumulated_max_excess = np.zeros_like(result)
        neighbor_excess: list[tuple[int, int, np.ndarray]] = []

        for dr, dc, dist in offsets:
            shifted = padded[1 + dr : 1 + dr + rows, 1 + dc : 1 + dc + cols]
            slope = (result - shifted) / (dist * sample_spacing)
            # Only count downslope excess (result > shifted, i.e. slope > 0)
            excess = np.maximum(slope - talus_threshold, 0.0)
            accumulated_total_excess += excess
            accumulated_max_excess = np.maximum(accumulated_max_excess, excess)
            neighbor_excess.append((dr, dc, excess))

        has_transfer = accumulated_total_excess > 0
        # Conservative transfer: half of the steepest excess avoids oscillation
        transfer = accumulated_max_excess * 0.5

        iteration_moved = np.zeros_like(result)

        for dr, dc, excess in neighbor_excess:
            with np.errstate(divide="ignore", invalid="ignore"):
                # Proportional fraction: each neighbour gets share of budget
                # proportional to its own excess / total_excess.
                fraction = np.where(
                    has_transfer, excess / accumulated_total_excess, 0.0
                )
            amount = transfer * fraction * has_transfer

            delta -= amount
            iteration_moved += amount

            # Shift amount to destination cells (source offset by (dr, dc))
            r_src_start = max(0, -dr)
            r_src_end = min(rows, rows - dr)
            c_src_start = max(0, -dc)
            c_src_end = min(cols, cols - dc)
            r_dst_start = max(0, dr)
            c_dst_start = max(0, dc)
            r_dst_end = r_dst_start + (r_src_end - r_src_start)
            c_dst_end = c_dst_start + (c_src_end - c_src_start)

            recv_slice = amount[r_src_start:r_src_end, c_src_start:c_src_end]
            delta[r_dst_start:r_dst_end, c_dst_start:c_dst_end] += recv_slice
            flow_accum[r_dst_start:r_dst_end, c_dst_start:c_dst_end] += recv_slice

        result += delta
        talus_accumulated += iteration_moved

    # Derive erosion_depth and deposition_depth from net height change
    net_change = result - h_in
    erosion_depth = np.maximum(-net_change, 0.0)    # where material was removed
    deposition_depth = np.maximum(net_change, 0.0)  # where material was received

    return ThermalErosionMasks(
        height=result,
        talus=talus_accumulated,
        erosion_depth=erosion_depth,
        deposition_depth=deposition_depth,
        flow_accumulation=flow_accum,
        metrics={
            "iterations": int(iterations),
            "talus_angle": float(talus_angle),
            "cell_size": float(cell_size),
            "total_talus_moved": float(talus_accumulated.sum()),
            "total_erosion_depth": float(erosion_depth.sum()),
            "total_deposition_depth": float(deposition_depth.sum()),
        },
    )


def apply_thermal_erosion(
    heightmap: np.ndarray,
    iterations: int = 10,
    talus_angle: float = 32.0,
    cell_size: float = 1.0,
) -> np.ndarray:
    """Legacy compat wrapper — returns eroded heightmap only, clamped to source range."""
    h_in = np.asarray(heightmap, dtype=np.float64)
    source_min = float(h_in.min()) if h_in.size else 0.0
    source_max = float(h_in.max()) if h_in.size else 0.0
    masks = apply_thermal_erosion_masks(
        h_in,
        iterations=iterations,
        talus_angle=talus_angle,
        cell_size=cell_size,
    )
    return np.clip(masks.height, source_min, source_max)


# ---------------------------------------------------------------------------
# Stream-Power Law solver (Fix 12.2 — Cordonnier 2016 ε-topological-order)
# ---------------------------------------------------------------------------


def compute_stream_power_erosion(
    dem: np.ndarray,
    *,
    K_scalar: float = 0.001,
    m: float = 0.5,
    n: float = 1.0,
    uplift_rate: float = 0.001,
    dt: float = 1000.0,
    steps: int = 50,
    cell_size: float = 1.0,
    erodibility_map: Optional[np.ndarray] = None,
    drainage_area: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Stream-Power Law O(n) implicit solver.

    Implements Cordonnier 2016 ε-topological-order: cells are processed
    from lowest to highest elevation per step, ensuring each cell's
    upstream area is already resolved before the cell updates.

    The inner per-step SPL update is vectorized via level-set BFS: cells
    are bucketed by depth in the receiver tree, and each bucket is solved
    with a single numpy advanced-indexing update because every cell in the
    bucket depends only on cells already resolved in shallower buckets.
    Python overhead drops from O(n) scalar iterations to O(max_depth)
    bucket passes (roughly O(sqrt(n)) for well-drained DEMs).

    Parameters
    ----------
    dem : np.ndarray
        2D heightmap (H, W) float32/float64.
    K_scalar : float
        Uniform erodibility fallback when erodibility_map is None.
    m : float
        Drainage area exponent (default 0.5).
    n : float
        Slope exponent (default 1.0).
    uplift_rate : float
        Rock uplift rate (heightmap units/step, default 0.001).
    dt : float
        Time step in years (default 1000.0).
    steps : int
        Number of solver iterations (default 50).
    cell_size : float
        World-space size per cell (metres).
    erodibility_map : np.ndarray, optional
        Per-cell K values, shape (H, W).
    drainage_area : np.ndarray, optional
        Per-cell drainage area (number of upstream cells). When None,
        uniform area of 1.0 is used.

    Returns
    -------
    np.ndarray
        Eroded DEM same shape and dtype as input.
    """
    h = np.asarray(dem, dtype=np.float64).copy()
    rows, cols = h.shape

    # Build erodibility array
    if erodibility_map is not None:
        K = np.asarray(erodibility_map, dtype=np.float64)
        if K.shape != h.shape:
            raise ValueError(
                f"erodibility_map shape {K.shape} must match dem shape {h.shape}"
            )
    else:
        K = np.full(h.shape, K_scalar, dtype=np.float64)

    # Build drainage area array
    if drainage_area is not None:
        A = np.asarray(drainage_area, dtype=np.float64)
        if A.shape != h.shape:
            raise ValueError(
                f"drainage_area shape {A.shape} must match dem shape {h.shape}"
            )
    else:
        A = np.ones(h.shape, dtype=np.float64)

    # Convert upstream contributing-cell counts into world-space drainage area
    # before applying the stream-power exponent. This keeps cell_size changes
    # physically meaningful instead of silently treating a 10 m tile and a 1 m
    # tile as the same catchment.
    A_world = np.maximum(A, 1.0) * float(cell_size) * float(cell_size)
    A_m = np.power(A_world, m)

    # 8-neighbor direction offsets and distances
    _SQRT2 = 1.4142135623730951
    _dy8 = np.array([-1, -1, -1,  0,  0,  1,  1,  1], dtype=np.int32)
    _dx8 = np.array([-1,  0,  1, -1,  1, -1,  0,  1], dtype=np.int32)
    _dd8 = np.array([_SQRT2, 1.0, _SQRT2, 1.0, 1.0, _SQRT2, 1.0, _SQRT2])

    def _build_receivers(h_flat: np.ndarray) -> tuple:
        """Return (receiver, recv_dist) for steepest-descent D8 flow.

        Returns
        -------
        receiver : (N,) int32
            Flat index of each cell's steepest downslope receiver.
            Self-loop means the cell is an outlet.
        recv_dist : (N,) float64
            World-space distance from cell to its receiver (cell_size * diagonal).
        """
        n_cells = rows * cols
        flat_idx = np.arange(n_cells, dtype=np.int32)
        receiver = flat_idx.copy()
        best_slope = np.zeros(n_cells, dtype=np.float64)
        recv_dist = np.full(n_cells, cell_size, dtype=np.float64)

        for d in range(8):
            nr = np.arange(rows, dtype=np.int32)[:, None] + _dy8[d]
            nc = np.arange(cols, dtype=np.int32)[None, :] + _dx8[d]
            valid = ((nr >= 0) & (nr < rows) & (nc >= 0) & (nc < cols)).ravel()
            # P2-2: mask indices to valid range BEFORE gathering so the dummy
            # read never touches out-of-bounds cells. Any cell flagged invalid
            # below is overwritten with -inf slope and excluded from updates;
            # the masked gather means no wasted read at index 0.
            nidx_raw = (nr * cols + nc).ravel()
            nidx_safe = np.where(valid, nidx_raw, flat_idx)  # self-gather sentinel
            # Slope to neighbor: positive when neighbor is lower than self.
            # Self-gather at invalid cells yields slope = 0 which is then
            # overwritten with -inf via the validity mask.
            gathered = h_flat[nidx_safe]
            slope_d = np.where(
                valid,
                (h_flat - gathered) / (cell_size * _dd8[d]),
                -np.inf,
            )
            update = slope_d > best_slope
            best_slope = np.where(update, slope_d, best_slope)
            receiver = np.where(update & valid, nidx_raw, receiver)
            recv_dist = np.where(
                update & valid,
                cell_size * _dd8[d],
                recv_dist,
            )

        return receiver, recv_dist

    n_cells = rows * cols
    flat_idx = np.arange(n_cells, dtype=np.int32)
    h_flat = h.ravel().copy()
    K_flat = K.ravel()
    A_m_flat = A_m.ravel()
    uplift_flat = np.full(n_cells, uplift_rate, dtype=np.float64)

    for _ in range(steps):
        receiver, recv_dist = _build_receivers(h_flat)

        # --- Vectorized implicit SPL update via pointer-jumping affine
        # composition (Cordonnier 2016 §4).
        #
        # The implicit update is an affine recurrence along the receiver tree:
        #     h_new[i] = a[i] + b[i] * h_new[receiver[i]]
        # where
        #     c[i]     = dt * K[i] * A_m[i] / recv_dist[i]
        #     a[i]     = (h[i] + dt*U[i]) / (1 + c[i])
        #     b[i]     = c[i] / (1 + c[i])
        # Outlets have receiver[i] == i and are resolved by
        #     h_new[i] = h[i] + dt*U[i]  (equivalent to setting a=h+dt*U, b=0).
        #
        # Composing affine maps along a chain i -> r -> r(r) -> ...:
        #     h_new[i] = a_k[i] + b_k[i] * h_new[r^k(i)]
        # where pointer-jumping doubles the chain length each step:
        #     r2       = r[r]                       (2-hop receivers)
        #     a_new[i] = a[i] + b[i] * a[r[i]]
        #     b_new[i] = b[i] * b[r[i]]
        # After ceil(log2(max_depth)) iterations every cell's effective
        # receiver is an outlet (self-loop), and h_new[i] = a[i] + b[i]*h[i]
        # for outlet i -- but we initialize outlets with a=h+dt*U, b=0 so
        # the affine chain collapses to h_new[i] = a[i] directly.
        # Total work: O(n log n) numpy ops -- roughly 10-12 pointer jumps on
        # a 513x513 tile.
        coeff = dt * K_flat * A_m_flat / np.maximum(recv_dist, 1e-9)
        uplift_term = dt * uplift_flat
        is_outlet = receiver == flat_idx

        # Per-cell affine coefficients
        denom = 1.0 + coeff
        a = (h_flat + uplift_term) / denom
        b = coeff / denom
        # Outlets: force the closed-form h_new = h + dt*U by setting b=0 and
        # a = h + dt*U. This makes the pointer-jump composition terminate
        # correctly regardless of the outlet's self-loop receiver.
        a = np.where(is_outlet, h_flat + uplift_term, a)
        b = np.where(is_outlet, 0.0, b)

        # Pointer-jumping: double the chain length until every cell's
        # effective receiver is an outlet (b_eff stays 0 once we hit one).
        eff_recv = receiver.copy()
        # Safety bound: ceil(log2(N)) + 2 guarantees termination even on
        # pathological linear chains up to length N.
        max_jumps = int(np.ceil(np.log2(max(n_cells, 2)))) + 2
        for _jump in range(max_jumps):
            parent = eff_recv
            # a' = a + b * a[parent];  b' = b * b[parent]
            a = a + b * a[parent]
            b = b * b[parent]
            new_recv = eff_recv[parent]
            if np.array_equal(new_recv, eff_recv):
                break  # tree fully collapsed to outlets
            eff_recv = new_recv

        # After convergence: b == 0 everywhere (all chains terminate at an
        # outlet whose b was forced to 0), so h_new = a.
        h_flat = a

    return h_flat.reshape(rows, cols).astype(dem.dtype)


__all__ = [
    "ErosionMasks",
    "ThermalErosionMasks",
    "ErosionConfig",
    "AnalyticalErosionResult",
    "apply_hydraulic_erosion",
    "apply_hydraulic_erosion_masks",
    "apply_thermal_erosion",
    "apply_thermal_erosion_masks",
    "compute_stream_power_erosion",
]

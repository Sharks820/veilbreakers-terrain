"""Canonical world-space terrain helpers + Bundle A pass functions.

This module is the terrain authority for tiled world generation. It keeps the
logic pure-Python / numpy-only so it can be tested without Blender.

Bundle A adds four pass functions consumed by ``TerrainPassController``:

    pass_macro_world        — seed the mask stack height channel
    pass_structural_masks   — populate slope/curvature/ridge/basin/saliency
    pass_erosion            — populate erosion / wetness / drainage / talus
    pass_validation_minimal — emit a minimal PassResult with sanity metrics

Existing helpers (``sample_world_height``, ``generate_world_heightmap``,
``extract_tile``, ``validate_tile_seams``, ``erode_world_heightmap``,
``world_region_dimensions``) remain unchanged for backward compat.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import numpy as np

from ._terrain_erosion import (
    ErosionConfig,
    apply_hydraulic_erosion,
    apply_hydraulic_erosion_masks,
    apply_thermal_erosion,
    apply_thermal_erosion_masks,
    compute_stream_power_erosion,
)
from .terrain_erosion_filter import apply_analytical_erosion
from ._terrain_noise import generate_heightmap
from .terrain_advanced import compute_flow_map
from .terrain_semantics import (
    BBox,
    PassResult,
    TerrainPipelineState,
    ValidationIssue,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase 12.1 — low/high-freq split constants
# ---------------------------------------------------------------------------

LOW_FREQ_OCTAVES: int = 3    # octaves 0-2 → large-scale shape
HIGH_FREQ_OCTAVES: int = 5   # octaves 3-7 → micro-detail (total 8 - LOW_FREQ_OCTAVES)
DETAIL_SCALE: float = 0.2    # high-freq adds 20% amplitude on top of eroded base


def _sample_single_height(
    world_x: float,
    world_y: float,
    *,
    scale: float,
    cell_size: float,
    seed: int,
    terrain_type: str,
    normalize: bool,
    **kwargs: Any,
) -> float:
    """Evaluate a single deterministic terrain sample without building a full window."""
    sample = generate_heightmap(
        1,
        1,
        scale=scale,
        world_origin_x=world_x,
        world_origin_y=world_y,
        cell_size=cell_size,
        seed=seed,
        terrain_type=terrain_type,
        normalize=normalize,
        **kwargs,
    )
    return float(np.asarray(sample, dtype=np.float64)[0, 0])


def sample_world_height(
    world_x: float,
    world_y: float,
    *,
    width: int = 1,
    height: int = 1,
    scale: float = 100.0,
    cell_size: float = 1.0,
    seed: int = 0,
    terrain_type: str = "mountains",
    normalize: bool = False,
    **kwargs: Any,
) -> float:
    """Sample a deterministic height at a world coordinate."""
    if width == 1 and height == 1:
        return _sample_single_height(
            world_x,
            world_y,
            scale=scale,
            cell_size=cell_size,
            seed=seed,
            terrain_type=terrain_type,
            normalize=normalize,
            **kwargs,
        )
    hmap = generate_world_heightmap(
        width=width,
        height=height,
        scale=scale,
        world_origin_x=world_x,
        world_origin_y=world_y,
        cell_size=cell_size,
        seed=seed,
        terrain_type=terrain_type,
        normalize=normalize,
        **kwargs,
    )
    return float(np.asarray(hmap, dtype=np.float64)[0, 0])


def generate_world_heightmap(
    width: int,
    height: int,
    *,
    scale: float = 100.0,
    world_origin_x: float = 0.0,
    world_origin_y: float = 0.0,
    cell_size: float = 1.0,
    seed: int = 0,
    terrain_type: str = "mountains",
    normalize: bool = False,
    world_center_x: float | None = None,
    world_center_y: float | None = None,
    **kwargs: Any,
) -> np.ndarray:
    """Generate a rectangular world-space heightmap window.

    The default ``normalize=False`` path keeps the world-space sample contract
    deterministic and tile-safe. Callers that need legacy behavior can opt into
    ``normalize=True``.
    """
    return generate_heightmap(
        width,
        height,
        scale=scale,
        world_origin_x=world_origin_x,
        world_origin_y=world_origin_y,
        cell_size=cell_size,
        normalize=normalize,
        seed=seed,
        terrain_type=terrain_type,
        world_center_x=world_center_x,
        world_center_y=world_center_y,
        **kwargs,
    )


def extract_tile(
    world_heightmap: np.ndarray,
    tile_x: int,
    tile_y: int,
    tile_size: int,
) -> np.ndarray:
    """Extract a tile from a world array using shared edge vertices."""
    hmap = np.asarray(world_heightmap, dtype=np.float64)
    if hmap.ndim < 2:
        raise ValueError("world_heightmap must have at least 2 dimensions")

    row_start = tile_y * tile_size
    col_start = tile_x * tile_size
    row_end = row_start + tile_size + 1
    col_end = col_start + tile_size + 1

    tile = hmap[row_start:row_end, col_start:col_end, ...]
    expected = (tile_size + 1, tile_size + 1)
    if tile.shape[:2] != expected:
        raise ValueError(
            f"Tile ({tile_x}, {tile_y}) with size {tile_size} is out of bounds "
            f"for world heightmap shape {hmap.shape}; got {tile.shape}, expected {expected}."
        )
    return tile.copy()


def validate_tile_seams(
    tiles: dict[tuple[int, int], np.ndarray],
    *,
    atol: float = 1e-6,
) -> dict[str, Any]:
    """Validate shared-edge equality for a set of extracted tiles."""
    issues: list[str] = []
    max_delta = 0.0
    channel_count = 1

    for (tx, ty), tile in tiles.items():
        tile_arr = np.asarray(tile, dtype=np.float64)
        if tile_arr.ndim < 2:
            issues.append(f"tile ({tx}, {ty}) must have at least 2 dimensions")
            continue
        channel_count = max(channel_count, int(np.prod(tile_arr.shape[2:]) or 1))

        east = tiles.get((tx + 1, ty))
        if east is not None:
            east_arr = np.asarray(east, dtype=np.float64)
            if east_arr.shape[:2] != tile_arr.shape[:2] or east_arr.shape[2:] != tile_arr.shape[2:]:
                issues.append(f"tile ({tx}, {ty}) east neighbor shape mismatch")
            else:
                delta = np.max(np.abs(tile_arr[:, -1, ...] - east_arr[:, 0, ...]))
                max_delta = max(max_delta, float(delta))
                if delta > atol:
                    issues.append(f"east seam mismatch at ({tx}, {ty}) -> ({tx + 1}, {ty}): {delta:.8f}")

        north = tiles.get((tx, ty + 1))
        if north is not None:
            north_arr = np.asarray(north, dtype=np.float64)
            if north_arr.shape[:2] != tile_arr.shape[:2] or north_arr.shape[2:] != tile_arr.shape[2:]:
                issues.append(f"tile ({tx}, {ty}) north neighbor shape mismatch")
            else:
                delta = np.max(np.abs(tile_arr[-1, :, ...] - north_arr[0, :, ...]))
                max_delta = max(max_delta, float(delta))
                if delta > atol:
                    issues.append(f"north seam mismatch at ({tx}, {ty}) -> ({tx}, {ty + 1}): {delta:.8f}")

    return {
        "seam_ok": not issues,
        "max_edge_delta": max_delta,
        "issues": issues,
        "tile_count": len(tiles),
        "channel_count": channel_count,
    }


def erode_world_heightmap(
    heightmap: np.ndarray,
    *,
    hydraulic_iterations: int = 1000,
    thermal_iterations: int = 0,
    seed: int = 0,
    talus_angle: float = 40.0,
    cell_size: float = 1.0,
) -> dict[str, Any]:
    """Erode a world heightmap as a single region, then return metadata.

    The erosion backends operate on arbitrary numeric ranges. This wrapper
    keeps the full world region intact, applies erosion in the source domain,
    and returns the eroded world heightmap plus flow metadata.
    """
    hmap = np.asarray(heightmap, dtype=np.float64)
    if hmap.ndim != 2:
        raise ValueError("heightmap must be 2D")
    if hmap.size == 0:
        return {
            "heightmap": hmap.copy(),
            "flow_map": {
                "flow_direction": [],
                "flow_accumulation": [],
                "drainage_basins": [],
                "num_basins": 0,
                "max_accumulation": 0.0,
                "resolution": (0, 0),
            },
            "source_min": 0.0,
            "source_max": 0.0,
            "height_range": 0.0,
        }

    source_min = float(hmap.min())
    source_max = float(hmap.max())
    height_range = source_max - source_min
    if height_range <= 1e-12:
        return {
            "heightmap": hmap.copy(),
            "flow_map": {
                "flow_direction": np.zeros_like(hmap, dtype=np.int32).tolist(),
                "flow_accumulation": np.ones_like(hmap, dtype=np.float64).tolist(),
                "drainage_basins": np.zeros_like(hmap, dtype=np.int32).tolist(),
                "num_basins": 0,
                "max_accumulation": 1.0,
                "resolution": hmap.shape,
            },
            "source_min": source_min,
            "source_max": source_max,
            "height_range": 0.0,
        }

    eroded = hmap

    if hydraulic_iterations > 0:
        eroded = apply_hydraulic_erosion(
            eroded,
            iterations=hydraulic_iterations,
            seed=seed,
            height_range=height_range,
        )

    if thermal_iterations > 0:
        eroded = np.asarray(
            apply_thermal_erosion(
                eroded,
                iterations=thermal_iterations,
                talus_angle=talus_angle,
                cell_size=cell_size,
            ),
            dtype=np.float64,
        )

    # Compute flow on the eroded world-region heightfield before splitting.
    flow_map = compute_flow_map(eroded)

    return {
        "heightmap": eroded,
        "flow_map": flow_map,
        "source_min": source_min,
        "source_max": source_max,
        "height_range": height_range,
    }


def world_region_dimensions(
    tile_count_x: int,
    tile_count_y: int,
    tile_size: int,
) -> tuple[int, int]:
    """Return world sample dimensions for a tiled region."""
    if tile_count_x < 1 or tile_count_y < 1 or tile_size < 1:
        raise ValueError("tile_count_x, tile_count_y, and tile_size must be positive")
    return tile_count_y * tile_size + 1, tile_count_x * tile_size + 1


# ---------------------------------------------------------------------------
# Phase 12.1 pass functions — low/high-freq split
# ---------------------------------------------------------------------------


def _terrain_type_from_intent(intent) -> str:
    """Resolve terrain_type string from intent.noise_profile."""
    noise_profile = (intent.noise_profile if intent else None) or "dark_fantasy_default"
    terrain_type_map = {
        "dark_fantasy_default": "mountains",
        "temperate": "mountains",
        "arid": "desert",
        "arctic": "mountains",
        "coastal": "coastal",
    }
    return terrain_type_map.get(str(noise_profile), "mountains")


def pass_generate_low_freq_hmap(
    state: TerrainPipelineState,
    region: Optional[BBox],
    deterministic_seed_override: Optional[int] = None,
    low_freq_octaves: int = LOW_FREQ_OCTAVES,
) -> PassResult:
    """Pass: generate base heightmap using low octaves only (large-scale shape).

    Produces both 'height' (initial value for downstream compat) and
    'hmap_low_freq' (the erosion-ready base).
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    intent = state.intent
    seed = int(
        deterministic_seed_override
        if deterministic_seed_override is not None
        else (intent.seed if intent else 0)
    )

    tile_size = int(stack.tile_size)
    cell_size = float(stack.cell_size)
    world_origin_x = float(stack.world_origin_x)
    world_origin_y = float(stack.world_origin_y)
    terrain_type = _terrain_type_from_intent(intent)

    hmap_low = generate_world_heightmap(
        width=tile_size,
        height=tile_size,
        scale=float(tile_size) * cell_size,
        world_origin_x=world_origin_x,
        world_origin_y=world_origin_y,
        cell_size=cell_size,
        seed=seed,
        terrain_type=terrain_type,
        octaves=low_freq_octaves,
    ).astype(np.float32)

    stack.set("hmap_low_freq", hmap_low, "pass_generate_low_freq_hmap")
    stack.set("height", hmap_low, "pass_generate_low_freq_hmap")

    elapsed = time.perf_counter() - t0
    return PassResult(
        pass_name="pass_generate_low_freq_hmap",
        status="ok",
        duration_seconds=elapsed,
        produced_channels=("height", "hmap_low_freq"),
        metrics={"elapsed_s": elapsed},
    )


def pass_generate_high_freq_detail(
    state: TerrainPipelineState,
    region: Optional[BBox],
    deterministic_seed_override: Optional[int] = None,
    high_freq_octaves: int = HIGH_FREQ_OCTAVES,
) -> PassResult:
    """Pass: generate high-frequency micro-detail noise band.

    Independent of pass_erosion. Combined by pass_composite_hmap after erosion.
    Uses a seed offset (+1) from the base heightmap seed so detail is
    decorrelated from the base shape.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    intent = state.intent
    seed = int(
        deterministic_seed_override
        if deterministic_seed_override is not None
        else (intent.seed if intent else 0)
    )

    tile_size = int(stack.tile_size)
    cell_size = float(stack.cell_size)
    world_origin_x = float(stack.world_origin_x)
    world_origin_y = float(stack.world_origin_y)
    terrain_type = _terrain_type_from_intent(intent)

    # Use seed+1 to decorrelate high-freq from base; use 2x finer scale
    hmap_high = generate_world_heightmap(
        width=tile_size,
        height=tile_size,
        scale=float(tile_size) * cell_size * 0.5,
        world_origin_x=world_origin_x,
        world_origin_y=world_origin_y,
        cell_size=cell_size,
        seed=seed + 1,
        terrain_type=terrain_type,
        octaves=high_freq_octaves,
        normalize=True,
    ).astype(np.float32)

    # Center high-freq around 0 (normalize is [0,1], shift to [-0.5, 0.5])
    hmap_high = hmap_high - 0.5

    stack.set("hmap_high_freq", hmap_high, "pass_generate_high_freq_detail")

    elapsed = time.perf_counter() - t0
    return PassResult(
        pass_name="pass_generate_high_freq_detail",
        status="ok",
        duration_seconds=elapsed,
        produced_channels=("hmap_high_freq",),
        metrics={"elapsed_s": elapsed},
    )


def pass_composite_hmap(
    state: TerrainPipelineState,
    region: Optional[BBox],
    deterministic_seed_override: Optional[int] = None,
    detail_scale: float = DETAIL_SCALE,
) -> PassResult:
    """Pass: composite eroded low-freq base + high-freq detail into final height.

    final_height = hmap_low_freq + hmap_high_freq * detail_scale

    Runs AFTER pass_erosion (which modified hmap_low_freq via stack.height).
    detail_scale is exposed as a parameter for quality profile control.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    low = stack.get("hmap_low_freq")
    high = stack.get("hmap_high_freq")

    if low is None:
        raise RuntimeError(
            "pass_composite_hmap: hmap_low_freq not populated; "
            "run pass_generate_low_freq_hmap first"
        )
    if high is None:
        raise RuntimeError(
            "pass_composite_hmap: hmap_high_freq not populated; "
            "run pass_generate_high_freq_detail first"
        )

    low = np.asarray(low, dtype=np.float32)
    high = np.asarray(high, dtype=np.float32)

    final_height = low + high * detail_scale

    stack.set("height", final_height, "pass_composite_hmap")

    elapsed = time.perf_counter() - t0
    return PassResult(
        pass_name="pass_composite_hmap",
        status="ok",
        duration_seconds=elapsed,
        produced_channels=("height",),
        metrics={"elapsed_s": elapsed, "detail_scale": detail_scale},
    )


# ---------------------------------------------------------------------------
# Bundle A pass functions
# ---------------------------------------------------------------------------


def _region_slice(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> tuple[slice, slice]:
    """Resolve a BBox to (row_slice, col_slice) for the current mask stack."""
    stack = state.mask_stack
    if region is None:
        h = stack.height
        return slice(0, h.shape[0]), slice(0, h.shape[1])
    return region.to_cell_slice(
        world_origin_x=stack.world_origin_x,
        world_origin_y=stack.world_origin_y,
        cell_size=stack.cell_size,
        grid_shape=stack.height.shape,
    )


def _protected_mask(
    state: TerrainPipelineState,
    shape: tuple[int, int],
    pass_name: str,
) -> np.ndarray:
    """Build a boolean mask of cells under a protected zone that forbids this pass."""
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


def pass_macro_world(
    state: TerrainPipelineState,
    region: Optional[BBox],
    deterministic_seed_override: Optional[int] = None,
) -> PassResult:
    """Pass 1: generate or confirm the base height field on the mask stack.

    Upgrade notes (B-→B+):
    - When the mask stack has no height (or has a flat/zero placeholder),
      this pass now GENERATES the heightmap via ``generate_world_heightmap``
      driven by the authoring intent.  It is no longer a validator-only stub.
    - If ``state.intent.heightmap_source`` is set (a Path to a pre-baked
      heightmap), that file is loaded instead of noise-generating.
    - The noise stack reads ``intent.noise_profile``, ``intent.seed``, and
      tile coordinates from the mask stack for deterministic, tile-safe output.
    - Pass still succeeds when height was pre-populated (e.g. by tests or
      a preset restore) — existing data is not overwritten.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: list[ValidationIssue] = []

    intent = state.intent
    seed = int(deterministic_seed_override if deterministic_seed_override is not None
               else (intent.seed if intent else 0))

    # Determine whether we need to generate height from scratch.
    needs_generate = stack.height is None or stack.height.size == 0

    # Also regenerate if the existing height is a flat/zero placeholder
    # (max - min < epsilon), which indicates state construction filled it
    # with zeros rather than real terrain data.
    if not needs_generate and stack.height is not None:
        h_range = float(stack.height.max()) - float(stack.height.min())
        if h_range < 1e-6:
            needs_generate = True

    if needs_generate:
        tile_size = int(stack.tile_size)

        # Check for a pre-baked heightmap source on the intent
        heightmap_source = getattr(intent, "heightmap_source", None) if intent else None
        if heightmap_source is not None:
            from pathlib import Path as _Path
            src = _Path(heightmap_source)
            if src.exists():
                try:
                    loaded = np.load(str(src))
                    if isinstance(loaded, np.ndarray):
                        hmap = loaded.astype(np.float32)
                    else:
                        # .npz archive — expect key "height"
                        hmap = loaded["height"].astype(np.float32)
                    stack.set("height", hmap, "macro_world")
                except Exception as exc:
                    issues.append(ValidationIssue(
                        code="MACRO_HEIGHTMAP_SOURCE_FAILED",
                        severity="soft",
                        message=f"Failed to load heightmap_source '{src}': {exc}. Falling back to noise.",
                    ))
                    heightmap_source = None  # fall through to noise generation

        if heightmap_source is None:
            # Generate via the macro_world noise stack.
            # terrain_type is taken from noise_profile; default to "mountains"
            # for the dark-fantasy aesthetic.
            noise_profile = (intent.noise_profile if intent else None) or "dark_fantasy_default"
            terrain_type_map = {
                "dark_fantasy_default": "mountains",
                "temperate": "mountains",
                "arid": "desert",
                "arctic": "mountains",
                "coastal": "coastal",
            }
            terrain_type = terrain_type_map.get(str(noise_profile), "mountains")

            # World-space origin from tile coordinates and cell_size
            cell_size = float(stack.cell_size)
            world_origin_x = float(stack.world_origin_x)
            world_origin_y = float(stack.world_origin_y)

            hmap = generate_world_heightmap(
                width=tile_size,
                height=tile_size,
                scale=float(tile_size) * cell_size,
                world_origin_x=world_origin_x,
                world_origin_y=world_origin_y,
                cell_size=cell_size,
                seed=seed,
                terrain_type=terrain_type,
                normalize=False,
            ).astype(np.float32)

            # Fix 7.20b: raw noise output is in ~[-0.5, 0.5] (normalized noise
            # basis), but world-space heights need to be in metres. Scale to a
            # meaningful range per terrain type. Mountains → 200 m vertical range,
            # desert → 80 m, coastal → 60 m. This keeps the tile-safe,
            # seam-consistent coordinate contract while producing useful elevations.
            _HEIGHT_SCALE = {
                "mountains": 200.0,
                "desert": 80.0,
                "coastal": 60.0,
            }.get(terrain_type, 150.0)
            h_range_raw = float(hmap.max()) - float(hmap.min())
            if h_range_raw < 1.0 and h_range_raw > 1e-9:
                hmap = hmap * (_HEIGHT_SCALE / h_range_raw)
            elif h_range_raw <= 1e-9:
                # Degenerate flat output — generate minimal relief via seed-based offset
                rng_fb = np.random.default_rng(seed ^ 0xDEAD)
                hmap = rng_fb.uniform(0.0, _HEIGHT_SCALE, hmap.shape).astype(np.float32)

            stack.set("height", hmap, "macro_world")
            # Fix 12.1 backward compat: macro_world also populates hmap_low_freq
            # so tests using macro_world → erosion continue to work when
            # erosion.requires_channels includes "hmap_low_freq".
            stack.set("hmap_low_freq", hmap, "macro_world")
            issues.append(ValidationIssue(
                code="MACRO_HEIGHT_GENERATED",
                severity="info",
                message=(
                    f"pass_macro_world generated height via noise "
                    f"(terrain_type={terrain_type!r}, seed={seed}, "
                    f"tile_size={tile_size})."
                ),
            ))

    if stack.height is None or stack.height.size == 0:
        issues.append(
            ValidationIssue(
                code="MACRO_NO_HEIGHT",
                severity="hard",
                message="mask stack has no height channel after generation attempt",
            )
        )
        return PassResult(
            pass_name="macro_world",
            status="failed",
            duration_seconds=time.perf_counter() - t0,
            issues=issues,
        )

    # Ensure height is tracked as populated by this pass
    stack.populated_by_pass.setdefault("height", "macro_world")

    # Fix 12.1 backward compat: always ensure hmap_low_freq is populated
    # (covers the case where height was pre-populated and needs_generate=False).
    if stack.get("hmap_low_freq") is None:
        stack.set("hmap_low_freq", stack.height, "macro_world")

    soft_issues = [i for i in issues if not i.is_hard()]
    return PassResult(
        pass_name="macro_world",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        produced_channels=("height", "hmap_low_freq"),
        metrics={
            "height_min": float(stack.height.min()),
            "height_max": float(stack.height.max()),
            "height_mean": float(stack.height.mean()),
            "shape": tuple(stack.height.shape),
            "generated": needs_generate,
        },
        issues=soft_issues,
    )


def pass_structural_masks(
    state: TerrainPipelineState,
    region: Optional[BBox],
    deterministic_seed_override: Optional[int] = None,
) -> PassResult:
    """Pass 2: populate slope, curvature, concavity, convexity, ridge, basin, saliency."""
    t0 = time.perf_counter()
    # Lazy import to dodge potential circularity during module load
    from . import terrain_masks

    stack = state.mask_stack
    terrain_masks.compute_base_masks(
        stack.height,
        stack.cell_size,
        (stack.tile_x, stack.tile_y),
        stack=stack,
        pass_name="structural_masks",
    )

    return PassResult(
        pass_name="structural_masks",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=(
            "slope",
            "curvature",
            "concavity",
            "convexity",
            "ridge",
            "basin",
            "saliency_macro",
        ),
        metrics={
            "max_slope_deg": float(np.degrees(stack.slope.max())),
            "mean_slope_deg": float(np.degrees(stack.slope.mean())),
            "ridge_fraction": float(stack.ridge.mean()),
            "basin_count": int(np.unique(stack.basin).size - (1 if 0 in stack.basin else 0)),
        },
    )


def pass_erosion(
    state: TerrainPipelineState,
    region: Optional[BBox],
    deterministic_seed_override: Optional[int] = None,
) -> PassResult:
    """Pass 3: run hydraulic + thermal erosion, populate erosion masks.

    Respects protected zones via a hero_exclusion mask derived from the
    intent's protected_zones list. Supports region scoping — only cells
    inside ``region`` are mutated; cells outside are restored from the
    pre-pass height snapshot.
    """
    # Lazy import to break circular dependency at module load
    from .terrain_pipeline import derive_pass_seed

    t0 = time.perf_counter()
    stack = state.mask_stack
    intent = state.intent

    # Use the protocol-mandated deterministic seed derivation so cross-tile
    # runs produce DIFFERENT erosion patterns under the same intent seed.
    if deterministic_seed_override is not None:
        seed = deterministic_seed_override
    else:
        seed = derive_pass_seed(
            intent.seed,
            "erosion",
            stack.tile_x,
            stack.tile_y,
            region,
        )
    profile = intent.erosion_profile or "temperate"

    profile_params = {
        "temperate": dict(iterations=400, talus_angle=40.0),
        "arid": dict(iterations=200, talus_angle=45.0),
        "alpine": dict(iterations=600, talus_angle=35.0),
    }.get(profile, dict(iterations=400, talus_angle=40.0))

    # Fix 12.3: Variable erodibility from rock_hardness channel
    _K_BASE: float = 0.001           # soft sediment baseline
    _K_STRATA_SCALE: float = -0.0008 # hard rock reduces erodibility (granite ≈ 0.0002)
    rock_hardness = stack.get("rock_hardness")
    if rock_hardness is not None:
        K_map: Optional[np.ndarray] = np.clip(
            _K_BASE + np.asarray(rock_hardness, dtype=np.float64) * _K_STRATA_SCALE,
            1e-6,  # minimum erodibility — never zero (prevents divide issues)
            None,
        ).astype(np.float32)
    else:
        K_map = None  # compute_stream_power_erosion will use K_scalar=_K_BASE

    # Fix 12.1: erode the low-freq base only; fall back to full height if split
    # not yet run (backward compat for tests that invoke pass_erosion in isolation).
    _low = stack.get("hmap_low_freq")
    if _low is None:
        logger.warning(
            "pass_erosion: hmap_low_freq not populated — falling back to stack.height "
            "(run pass_generate_low_freq_hmap first for full Fix 12.1 behavior)"
        )
    h_before = (_low if _low is not None else stack.height).copy()

    # Combine hero_exclusion + protected-zone mask
    protected = _protected_mask(state, h_before.shape, "erosion")
    if stack.hero_exclusion is not None:
        combined_exclusion = protected | stack.hero_exclusion.astype(bool)
    else:
        combined_exclusion = protected

    hero_arg = combined_exclusion if combined_exclusion.any() else None

    # --- Analytical erosion (chunk-parallel, deterministic) ---
    # Derive an ErosionConfig from the erosion profile
    analytical_cfg_map = {
        "temperate": ErosionConfig(strength=0.5, gully_weight=1.0, octave_count=4),
        "arid": ErosionConfig(strength=0.7, gully_weight=1.2, octave_count=3, fade_amplitude=0.4),
        "alpine": ErosionConfig(strength=0.4, gully_weight=0.8, octave_count=5, fade_amplitude=0.8),
    }
    analytical_cfg = analytical_cfg_map.get(profile, ErosionConfig())

    analytical_result = apply_analytical_erosion(
        h_before,
        analytical_cfg,
        seed=seed,
        cell_size=stack.cell_size,
    )

    # BUG-99: Apply rock_hardness K modifier to analytical erosion delta.
    # Only active when stratigraphy has run (strat_erosion_delta present) —
    # preserves backward compat for tests that invoke pass_erosion in isolation
    # without a preceding pass_stratigraphy.
    analytical_delta = analytical_result.height_delta
    if rock_hardness is not None and stack.get("strat_erosion_delta") is not None:
        k_mod = 1.0 - 0.7 * np.clip(
            np.asarray(rock_hardness, dtype=np.float64)[
                :analytical_delta.shape[0], :analytical_delta.shape[1]
            ],
            0.0, 1.0,
        )
        analytical_delta = analytical_delta * k_mod

    # Apply analytical height delta
    h_after_analytical = h_before + analytical_delta

    # Store ridge map on the mask stack
    ridge_out = analytical_result.ridge_map
    if region is not None:
        r_s, c_s = _region_slice(state, region)
        scoped_ridge = np.zeros_like(ridge_out)
        scoped_ridge[r_s, c_s] = ridge_out[r_s, c_s]
        ridge_out = scoped_ridge
    if protected.any():
        ridge_out = np.where(protected, 0.0, ridge_out)
    stack.set("ridge", ridge_out, "erosion")

    # --- Hydraulic erosion (secondary refinement on analytical output) ---
    hydro = apply_hydraulic_erosion_masks(
        h_after_analytical,
        iterations=profile_params["iterations"],
        seed=seed,
        hero_exclusion=hero_arg,
    )
    # --- Thermal erosion (smooths sharp analytical features) ---
    thermal = apply_thermal_erosion_masks(
        hydro.height,
        iterations=6,
        talus_angle=profile_params["talus_angle"],
        cell_size=stack.cell_size,
    )

    new_height = thermal.height

    # Region scoping: restore cells outside the region from the pre-pass snapshot.
    r_slice, c_slice = _region_slice(state, region)
    if region is not None:
        scoped = h_before.copy()
        scoped[r_slice, c_slice] = new_height[r_slice, c_slice]
        new_height = scoped

        # Also scope the mask channels
        def _scope(arr: np.ndarray) -> np.ndarray:
            out = np.zeros_like(arr)
            out[r_slice, c_slice] = arr[r_slice, c_slice]
            return out

        erosion_amount_out = _scope(hydro.erosion_amount)
        deposition_amount_out = _scope(hydro.deposition_amount)
        wetness_out = _scope(hydro.wetness)
        drainage_out = _scope(hydro.drainage)
        bank_instability_out = _scope(hydro.bank_instability)
        talus_out = _scope(thermal.talus)
    else:
        erosion_amount_out = hydro.erosion_amount
        deposition_amount_out = hydro.deposition_amount
        wetness_out = hydro.wetness
        drainage_out = hydro.drainage
        bank_instability_out = hydro.bank_instability
        talus_out = thermal.talus

    # Enforce protected zones: revert those cells to the pre-pass snapshot
    if protected.any():
        new_height = np.where(protected, h_before, new_height)
        erosion_amount_out = np.where(protected, 0.0, erosion_amount_out)
        deposition_amount_out = np.where(protected, 0.0, deposition_amount_out)
        wetness_out = np.where(protected, 0.0, wetness_out)
        drainage_out = np.where(protected, 0.0, drainage_out)
        bank_instability_out = np.where(protected, 0.0, bank_instability_out)
        talus_out = np.where(protected, 0.0, talus_out)

    # Fix 12.2: Stream-Power Law solver (Cordonnier 2016 ε-topological-order)
    # Requires flow_accumulation from Phase 7 Priority-Flood. Falls back to
    # uniform drainage_area if channel not yet populated.
    flow_accum = stack.get("flow_accumulation")
    if flow_accum is None:
        logger.warning(
            "pass_erosion: flow_accumulation channel not populated — "
            "stream-power solver using uniform drainage_area (Phase 7 Priority-Flood not yet run). "
            "Wire Fix 7.3 to enable full SPL incision."
        )

    new_height = compute_stream_power_erosion(
        new_height,
        K_scalar=_K_BASE,
        m=0.5,
        n=1.0,
        uplift_rate=0.001,
        dt=1000.0,
        steps=50,
        cell_size=float(stack.cell_size),
        erodibility_map=K_map,
        drainage_area=flow_accum,
    )

    # Re-apply region scoping after SPL (SPL operates on whole array)
    if region is not None:
        spl_scoped = h_before.copy()
        spl_scoped[r_slice, c_slice] = new_height[r_slice, c_slice]
        new_height = spl_scoped

    # Re-apply protected zone masking after SPL
    if protected.any():
        new_height = np.where(protected, h_before, new_height)

    # BUG-99 (part 2): Apply rock_hardness K modifier to the full erosion delta
    # (analytical + hydraulic + thermal + SPL combined).  Hard rock (hardness→1.0)
    # gets k_mod→0.3 meaning only 30% of the net height change is kept; soft rock
    # (hardness→0.0) keeps 100%.  Guard: only active when stratigraphy ran first
    # (strat_erosion_delta present).
    if rock_hardness is not None and stack.get("strat_erosion_delta") is not None:
        rh_arr = np.asarray(rock_hardness, dtype=np.float64)
        rh_arr = rh_arr[:new_height.shape[0], :new_height.shape[1]]
        k_mod_full = 1.0 - 0.7 * np.clip(rh_arr, 0.0, 1.0)
        full_delta = new_height - h_before
        new_height = h_before + full_delta * k_mod_full

    stack.set("height", new_height, "erosion")
    # Fix 12.1: also update hmap_low_freq so pass_composite_hmap sees the eroded base
    stack.set("hmap_low_freq", new_height, "erosion")
    stack.set("erosion_amount", erosion_amount_out, "erosion")
    stack.set("deposition_amount", deposition_amount_out, "erosion")
    stack.set("wetness", wetness_out, "erosion")
    stack.set("drainage", drainage_out, "erosion")
    stack.set("bank_instability", bank_instability_out, "erosion")
    stack.set("talus", talus_out, "erosion")

    return PassResult(
        pass_name="erosion",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=(
            "height",
            "ridge",
            "erosion_amount",
            "deposition_amount",
            "wetness",
            "drainage",
            "bank_instability",
            "talus",
        ),
        metrics={
            "profile": profile,
            "hydraulic_iterations": profile_params["iterations"],
            "thermal_iterations": 6,
            "total_erosion": float(erosion_amount_out.sum()),
            "total_deposition": float(deposition_amount_out.sum()),
            "total_talus": float(talus_out.sum()),
            "protected_cells": int(protected.sum()),
            "region_scoped": region is not None,
        },
    )


def pass_validation_minimal(
    state: TerrainPipelineState,
    region: Optional[BBox],
    deterministic_seed_override: Optional[int] = None,
) -> PassResult:
    """Pass 4: emit a minimal validation report over the mask stack.

    Checks:
      - height channel is finite everywhere
      - slope channel exists
      - no NaN/inf in any populated channel
    Any violation downgrades status to "failed".
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: list[ValidationIssue] = []

    if not np.all(np.isfinite(stack.height)):
        issues.append(
            ValidationIssue(
                code="HEIGHT_NONFINITE",
                severity="hard",
                message="height channel contains NaN or inf",
            )
        )

    for ch in ("slope", "curvature", "wetness", "drainage"):
        arr = stack.get(ch)
        if arr is None:
            continue
        arr_np = np.asarray(arr)
        if arr_np.size == 0:
            continue
        if not np.all(np.isfinite(arr_np)):
            issues.append(
                ValidationIssue(
                    code=f"{ch.upper()}_NONFINITE",
                    severity="hard",
                    message=f"{ch} channel contains NaN or inf",
                )
            )

    status = "failed" if any(i.is_hard() for i in issues) else "ok"

    return PassResult(
        pass_name="validation_minimal",
        status=status,
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height", "slope"),
        issues=issues,
        metrics={
            "populated_channels": sorted(stack.populated_by_pass.keys()),
            "hard_issues": sum(1 for i in issues if i.is_hard()),
        },
    )

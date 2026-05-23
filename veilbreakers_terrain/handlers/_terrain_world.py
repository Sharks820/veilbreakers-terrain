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
import math
import time
from typing import Any, Optional, cast

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
    TerrainIntentState,
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
    sample = generate_world_heightmap(
        width=1,
        height=1,
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
    """Sample a deterministic height at a world coordinate.

    Always routes through ``generate_world_heightmap`` so the 3-layer
    macro+meso+micro blend is identical regardless of window size — a single
    point query returns the same value as the same point queried inside a
    larger window.
    """
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

    Produces a three-scale spectral composition matching World Machine /
    Gaea's Mountains+Hills+Rocks node stack:

      - **Macro** (continental / tectonic scale): very-low-frequency fBm
        (0.5–2 octaves worth of signal) — sets the broad mountain ranges,
        basins, and plateau plateaus that span hundreds of kilometres.
        Uses ``scale * 4`` so one cycle spans ~4× the tile width.
        Weight: 0.60.

      - **Meso** (mountain / valley scale): medium-frequency fBm (4–6
        octaves) — defines individual ridges, peaks, and valley corridors.
        Uses the supplied ``scale`` unchanged.
        Weight: 0.30.

      - **Micro** (local surface detail): high-frequency fBm (3–4 octaves,
        finer scale) — adds rocky surface variation, ledges, and grain.
        Uses ``scale * 0.2`` so one cycle is ~20 % of tile width.
        Weight: 0.10.

    Each band uses an independent seed (``seed``, ``seed ^ 0x6A3C1F2D``,
    ``seed ^ 0xB5E7A09C``) so the three layers are decorrelated and do not
    reinforce each other's patterns.

    The ``normalize=False`` default preserves the world-space sample
    contract (deterministic, tile-safe seams). Pass ``normalize=True`` for
    the legacy per-tile [0, 1] path.
    """
    # --- strip kwargs that generate_heightmap does not accept ----------------
    # world_center_x / world_center_y are forwarded; unknown keys are dropped
    # to avoid TypeError inside generate_heightmap.
    _fwd_keys = {
        "octaves", "persistence", "lacunarity",
        "warp_strength", "warp_scale",
    }
    fwd_kwargs = {k: v for k, v in kwargs.items() if k in _fwd_keys}

    # Non-octave kwargs forwarded to all three layers (persistence, lacunarity,
    # warp_strength, warp_scale).  Octave count is fixed per-layer so we exclude
    # "octaves" here to avoid "multiple values for keyword argument" errors.
    _non_octave_kwargs = {k: v for k, v in fwd_kwargs.items() if k != "octaves"}
    # The meso layer uses the caller's preferred octave count if supplied,
    # otherwise defaults to 5 (medium-detail mountain/valley scale).
    _meso_octaves = int(fwd_kwargs["octaves"]) if "octaves" in fwd_kwargs else 5

    # -------------------------------------------------------------------------
    # Macro layer — tectonic / continental scale
    # Fixed 2 octaves at 4× the tile scale → broad elevation envelope
    # -------------------------------------------------------------------------
    macro = generate_heightmap(
        width,
        height,
        scale=scale * 4.0,
        world_origin_x=world_origin_x,
        world_origin_y=world_origin_y,
        cell_size=cell_size,
        normalize=normalize,
        seed=seed,
        terrain_type=terrain_type,
        world_center_x=world_center_x,
        world_center_y=world_center_y,
        octaves=2,
        **_non_octave_kwargs,
    )

    # -------------------------------------------------------------------------
    # Meso layer — mountain / valley scale
    # Medium octaves (4–6) at the standard tile scale → ridge / valley form
    # -------------------------------------------------------------------------
    meso_seed = seed ^ 0x6A3C1F2D
    meso = generate_heightmap(
        width,
        height,
        scale=scale,
        world_origin_x=world_origin_x,
        world_origin_y=world_origin_y,
        cell_size=cell_size,
        normalize=normalize,
        seed=meso_seed,
        terrain_type=terrain_type,
        world_center_x=world_center_x,
        world_center_y=world_center_y,
        octaves=_meso_octaves,
        **_non_octave_kwargs,
    )

    # -------------------------------------------------------------------------
    # Micro layer — local surface detail
    # Fixed 4 octaves at 0.2× scale → rocky grain and ledge texture
    # -------------------------------------------------------------------------
    micro_seed = seed ^ 0xB5E7A09C
    micro = generate_heightmap(
        width,
        height,
        scale=scale * 0.2,
        world_origin_x=world_origin_x,
        world_origin_y=world_origin_y,
        cell_size=cell_size,
        normalize=normalize,
        seed=micro_seed,
        terrain_type=terrain_type,
        world_center_x=world_center_x,
        world_center_y=world_center_y,
        octaves=4,
        **_non_octave_kwargs,
    )

    # -------------------------------------------------------------------------
    # Blend — 0.6 macro + 0.3 meso + 0.1 micro
    # All three arrays share shape (height, width); combine as float64 to
    # avoid precision loss before any downstream normalization.
    # -------------------------------------------------------------------------
    macro_f = np.asarray(macro, dtype=np.float64)
    meso_f  = np.asarray(meso,  dtype=np.float64)
    micro_f = np.asarray(micro, dtype=np.float64)

    composite = 0.6 * macro_f + 0.3 * meso_f + 0.1 * micro_f

    return composite


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
    hydraulic_iterations: int = 50_000,
    thermal_iterations: int = 0,
    seed: int = 0,
    talus_angle: float = 40.0,
    cell_size: float = 1.0,
    snowline: float = 0.72,
    aeolian_floor: float = 0.25,
) -> dict[str, Any]:
    """Erode a world heightmap with altitude-zoned erosion types.

    Applies three geologically distinct erosion processes keyed to altitude,
    matching World Machine's ``Erosion`` node zone-split and Houdini's
    HeightField Erode SOP preset layers:

      - **Glacial zone** (height > snowline): Thermal erosion with a low talus
        angle (28 deg) simulating glacial plucking and freeze-thaw shattering.
        Produces U-shaped cirque valleys and sharp arêtes.
      - **Fluvial zone** (aeolian_floor < height ≤ snowline): Full
        particle-based hydraulic erosion (Olsen 2004).  Produces V-shaped
        valleys, alluvial fans, and coherent drainage networks.
      - **Aeolian zone** (height ≤ aeolian_floor): Light thermal erosion at
        high talus angle (50 deg) simulating wind-driven sand transport in
        lowland basins and coastal flats.

    Each zone is eroded independently on a masked copy of the heightmap, then
    blended back using a soft linear ramp (0.05 normalised height overlap) to
    avoid sharp zone boundaries.

    Args:
        snowline: Normalised height threshold above which glacial erosion
            dominates.  Default 0.72 ≈ ~72% of the tile's height range,
            matching typical high-alpine snowline position.
        aeolian_floor: Normalised height threshold below which aeolian erosion
            dominates.  Default 0.25.

    Implements Olsen (2004) particle-based hydraulic erosion at AAA quality:
    50,000 particles minimum — matching Gaea's default erosion particle count
    and sufficient to produce geologically plausible channel networks,
    alluvial fans, and sediment redistribution on a 512x512 tile.
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

    # --- Normalise to [0, 1] for zone thresholding ---
    hmap_norm = (hmap - source_min) / height_range  # [0, 1]

    # --- Zone blend weights (soft linear ramp, 0.05 overlap) ---
    _RAMP = 0.05
    # Glacial weight: 1.0 above snowline, 0.0 below (snowline - ramp)
    w_glacial = np.clip((hmap_norm - (snowline - _RAMP)) / _RAMP, 0.0, 1.0)
    # Aeolian weight: 1.0 below aeolian_floor, 0.0 above (aeolian_floor + ramp)
    w_aeolian = np.clip(((aeolian_floor + _RAMP) - hmap_norm) / _RAMP, 0.0, 1.0)
    # Fluvial weight: middle band, complement of glacial + aeolian
    w_fluvial = np.clip(1.0 - w_glacial - w_aeolian, 0.0, 1.0)

    # --- Glacial erosion (thermal, low talus = 28 deg) ---
    glacial_iters = max(1, thermal_iterations) if thermal_iterations > 0 else 8
    eroded_glacial = np.asarray(
        apply_thermal_erosion(
            hmap,
            iterations=glacial_iters,
            talus_angle=28.0,
            cell_size=cell_size,
        ),
        dtype=np.float64,
    )

    # --- Fluvial erosion (full particle hydraulics) ---
    if hydraulic_iterations > 0:
        eroded_fluvial = apply_hydraulic_erosion(
            hmap,
            iterations=hydraulic_iterations,
            seed=seed,
            height_range=height_range,
        )
    else:
        eroded_fluvial = hmap.copy()

    # Optional thermal smoothing on fluvial output
    if thermal_iterations > 0:
        eroded_fluvial = np.asarray(
            apply_thermal_erosion(
                eroded_fluvial,
                iterations=thermal_iterations,
                talus_angle=talus_angle,
                cell_size=cell_size,
            ),
            dtype=np.float64,
        )

    # --- Aeolian erosion (thermal, high talus = 50 deg) ---
    aeolian_iters = max(1, thermal_iterations) if thermal_iterations > 0 else 4
    eroded_aeolian = np.asarray(
        apply_thermal_erosion(
            hmap,
            iterations=aeolian_iters,
            talus_angle=50.0,
            cell_size=cell_size,
        ),
        dtype=np.float64,
    )

    # --- Blend zones ---
    eroded = (
        w_glacial * eroded_glacial
        + w_fluvial * eroded_fluvial
        + w_aeolian * eroded_aeolian
    )

    # Compute flow on the eroded world-region heightfield before splitting.
    flow_map = compute_flow_map(eroded)

    return {
        "heightmap": eroded,
        "flow_map": flow_map,
        "source_min": source_min,
        "source_max": source_max,
        "height_range": height_range,
        "zone_weights": {
            "glacial": float(w_glacial.mean()),
            "fluvial": float(w_fluvial.mean()),
            "aeolian": float(w_aeolian.mean()),
        },
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


def _terrain_type_from_intent(intent: TerrainIntentState | None) -> str:
    """Resolve terrain_type string from intent.noise_profile."""
    noise_profile = (
        str(intent.noise_profile)
        if intent is not None and intent.noise_profile
        else "dark_fantasy_default"
    )
    profile = str(noise_profile).strip().lower()
    terrain_type_map = {
        "dark_fantasy_default": "mountains",
        "temperate": "mountains",
        "arid": "desert",
        "arctic": "mountains",
        "coastal": "coastal",
        "mountain": "mountains",
        "mountains": "mountains",
        "hill": "hills",
        "hills": "hills",
        "foothills": "hills",
        "plain": "plains",
        "plains": "plains",
        "flat": "flat",
        "flatland": "flat",
        "cliff": "cliffs",
        "cliffs": "cliffs",
        "canyon": "canyon",
        "desert": "desert",
        "volcanic": "volcanic",
        "swamp": "swamp",
        "wetland": "swamp",
    }
    if profile in terrain_type_map:
        return terrain_type_map[profile]
    if profile.startswith("terrain:"):
        terrain_type = profile.split(":", 1)[1].strip()
        if terrain_type:
            return terrain_type
    return "mountains"


def _apply_post_height_seams(
    stack: Any,
    *channels: str,
) -> None:
    """Re-apply imported neighbor seam constraints after a height mutation."""
    if not any(
        getattr(stack, edge_name, None) is not None
        for edge_name in ("north_edge", "south_edge", "east_edge", "west_edge")
    ):
        return

    from .terrain_chunking import apply_seam_boundary_conditions

    apply_seam_boundary_conditions(stack, channels=tuple(channels) or ("height",))


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

    rows, cols = stack.height.shape
    cell_size = float(stack.cell_size)
    world_origin_x = float(stack.world_origin_x)
    world_origin_y = float(stack.world_origin_y)
    terrain_type = _terrain_type_from_intent(intent)
    hints: dict[str, Any] = dict(intent.composition_hints or {})

    existing_low = stack.get("hmap_low_freq")
    reused_existing = existing_low is not None
    if reused_existing:
        hmap_low = np.asarray(existing_low, dtype=np.float32).copy()
    else:
        hmap_low = generate_world_heightmap(
            width=cols,
            height=rows,
            scale=float(max(rows, cols)) * cell_size,
            world_origin_x=world_origin_x,
            world_origin_y=world_origin_y,
            cell_size=cell_size,
            seed=seed,
            terrain_type=terrain_type,
            octaves=low_freq_octaves,
        ).astype(np.float32)
        dem_cfg = hints.get("dem_source")
        if dem_cfg:
            from .terrain_dem_import import DEMSource, import_dem_tile

            if isinstance(dem_cfg, DEMSource):
                dem_source = dem_cfg
            elif isinstance(dem_cfg, dict):
                dem_map = cast(dict[str, Any], dem_cfg)
                dem_source = DEMSource(
                    source_type=str(dem_map.get("source_type", "synthetic")),
                    url_or_path=str(dem_map.get("url_or_path", "")),
                    resolution_m=float(dem_map.get("resolution_m", cell_size)),
                )
            else:
                dem_source = DEMSource(
                    source_type="synthetic",
                    url_or_path=str(dem_cfg),
                    resolution_m=cell_size,
                )
            dem_tile = import_dem_tile(
                dem_source,
                intent.region_bounds,
                target_shape=hmap_low.shape,
                apply_egm96_offset=bool(hints.get("dem_apply_egm96_offset", False)),
            )
            h_min = float(np.min(hmap_low))
            h_max = float(np.max(hmap_low))
            h_range = max(h_max - h_min, 1.0)
            dem_scaled = h_min + np.asarray(dem_tile.heightmap, dtype=np.float32) * h_range
            blend = float(np.clip(hints.get("dem_blend_weight", 1.0), 0.0, 1.0))
            hmap_low = ((1.0 - blend) * hmap_low + blend * dem_scaled).astype(np.float32)

    stack.set("hmap_low_freq", hmap_low, "pass_generate_low_freq_hmap")
    stack.set("height", hmap_low, "pass_generate_low_freq_hmap")
    _apply_post_height_seams(stack, "height", "hmap_low_freq")

    elapsed = time.perf_counter() - t0
    return PassResult(
        pass_name="pass_generate_low_freq_hmap",
        status="ok",
        duration_seconds=elapsed,
        produced_channels=("height", "hmap_low_freq"),
        metrics={
            "elapsed_s": elapsed,
            "generated": not reused_existing,
            "reused_existing": reused_existing,
            "dem_blended": bool(hints.get("dem_source")),
        },
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

    rows, cols = stack.height.shape
    cell_size = float(stack.cell_size)
    world_origin_x = float(stack.world_origin_x)
    world_origin_y = float(stack.world_origin_y)
    terrain_type = _terrain_type_from_intent(intent)

    # Use seed+1 to decorrelate high-freq from base; use 2x finer scale
    hmap_high = generate_world_heightmap(
        width=cols,
        height=rows,
        scale=float(max(rows, cols)) * cell_size * 0.5,
        world_origin_x=world_origin_x,
        world_origin_y=world_origin_y,
        cell_size=cell_size,
        seed=seed + 1,
        terrain_type=terrain_type,
        octaves=high_freq_octaves,
        normalize=False,
    ).astype(np.float32)

    # OpenSimplex/Perlin have zero mean by construction — per-tile mean
    # subtraction varies slightly across tiles and breaks seams.

    stack.set("hmap_high_freq", hmap_high, "pass_generate_high_freq_detail")
    _apply_post_height_seams(stack, "hmap_high_freq")

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
    _apply_post_height_seams(stack, "height")

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
    # HOTFIX-7d (Verifier A #13): unified schema-tolerant resolver.
    # PR #126 (coderabbit T7): use _zone_permits so dict-shaped zones don't crash.
    from ._protected_zones import _resolve_protected_zone_aabb, _zone_permits

    stack = state.mask_stack
    mask = np.zeros(shape, dtype=bool)
    if not state.intent.protected_zones:
        return mask

    rows, cols = shape
    ys = stack.world_origin_y + (np.arange(rows) + 0.5) * stack.cell_size
    xs = stack.world_origin_x + (np.arange(cols) + 0.5) * stack.cell_size
    xg, yg = np.meshgrid(xs, ys)

    for zone in state.intent.protected_zones:
        if _zone_permits(zone, pass_name):
            continue
        min_x, min_y, max_x, max_y = _resolve_protected_zone_aabb(zone)
        inside = (
            (xg >= min_x)
            & (xg <= max_x)
            & (yg >= min_y)
            & (yg <= max_y)
        )
        mask |= inside
    return mask


def pass_macro_world(
    state: TerrainPipelineState,
    region: Optional[BBox],
    deterministic_seed_override: Optional[int] = None,
) -> PassResult:
    """Pass 1: generate the base height field and apply tectonic-scale biasing.

    Upgraded from B+ to A:
    - Generates the full macro/meso/micro composite heightmap via
      ``generate_world_heightmap`` (which now performs 3-scale spectral
      composition) rather than a single-scale noise call.
    - After generation (or when height was pre-populated), applies a
      **continental plate elevation bias** derived from
      ``intent.composition_hints``:

        ``continent_center_x``, ``continent_center_y`` (normalised [0, 1]
          tile coordinates, default 0.5 each) — peak of the continental mass.
        ``continent_radius`` (normalised, default 0.5) — Gaussian sigma of
          the continental dome.
        ``continent_amplitude`` (metres, default 60 % of the terrain vertical
          range) — how much the continent raises the centre relative to the
          oceanic margins.

      The bias is a radially-symmetric Gaussian dome centred on the specified
      point.  It is applied *additively* to the heightmap and the result is
      stored back to both ``height`` and ``hmap_low_freq``.  When no hints are
      provided the pass behaves identically to the previous implementation
      (zero bias, no change to the heightmap).

    - If ``state.intent.heightmap_source`` is set (a Path to a pre-baked
      heightmap), that file is loaded instead of noise-generating.
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
    needs_generate = stack.height.size == 0

    # Also regenerate if the existing height is a flat/zero placeholder
    # (max - min < epsilon), which indicates state construction filled it
    # with zeros rather than real terrain data.
    if not needs_generate:
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
                    # T0-7 (Y04 v3 §P.8.1 ord 0k, partial): allow_pickle=False
                    # — heightmap_source is a user-supplied path; pickle
                    # loads enable arbitrary code execution.
                    loaded = np.load(str(src), allow_pickle=False)
                    if isinstance(loaded, np.ndarray):
                        hmap = np.asarray(loaded, dtype=np.float32)
                    else:
                        # .npz archive — expect key "height"
                        hmap = np.asarray(loaded["height"], dtype=np.float32)
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

            # B15-P0-01 / Phase A D6-7: single canonical rescale.
            #
            # Resolution order (hint always wins when valid, regardless of magnitude):
            #   1. ``intent.composition_hints["target_height_range_m"]``  (canonical authoring path)
            #   2. ``_HEIGHT_SCALE_DEFAULTS[terrain_type]``               (per-type fallback)
            #
            # Prior to this fix the per-type ``_HEIGHT_SCALE`` was applied
            # unconditionally and the FIX-B14-9 block at :994 then RE-rescaled
            # when ``target_height_range_m`` was provided. That double-rescale
            # invalidated any height-dependent channel derived between the two
            # rescales, and made the per-type scale the de-facto canonical even
            # though the spec calls ``target_height_range_m`` the canonical
            # authoring knob (B15-P0-01).
            #
            # Now: when ``target_height_range_m`` is provided AND parses to a
            # positive float, it wins (even if smaller than the per-type
            # default). Anything else — None, missing, non-numeric, zero,
            # negative — falls back to the per-type default. The FIX-B14-9
            # block at :994 below remains as a downstream rescale event
            # emitter for telemetry; with the canonical rescale already
            # applied here it is effectively idempotent on identical inputs.
            #
            # Per-type fallback ranges (Fix 7.20b lineage): mountains 200m,
            # desert 80m, coastal 60m, default 150m. Raw noise basis is
            # ~[-0.5, 0.5]; affine remap brings it to [0, _height_scale].
            _HEIGHT_SCALE_DEFAULTS = {
                "mountains": 200.0,
                "desert": 80.0,
                "coastal": 60.0,
            }
            # Note: ``intent`` is already non-None at this point (guarded by
            # the enclosing ``if heightmap_source is None`` branch reached only
            # when intent was bound and noise generation is the live path).
            # Pyright strict knows this, so we elide the redundant
            # ``is not None`` check that would otherwise add a
            # ``reportUnnecessaryComparison`` to the strict baseline.
            _intent_hints = intent.composition_hints or {}
            _intent_target_range = _intent_hints.get("target_height_range_m")
            # Defensive parse: composition_hints is `Dict[str, Any]` so the
            # value may be a non-numeric string, list, dict, etc. Treat any
            # parse failure or non-positive result as "not provided" and fall
            # back to the per-type default rather than letting the pass crash
            # with TypeError/ValueError on malformed authoring input.
            _height_scale = _HEIGHT_SCALE_DEFAULTS.get(terrain_type, 150.0)
            if _intent_target_range is not None:
                try:
                    _parsed_target = float(_intent_target_range)
                except (TypeError, ValueError):
                    _parsed_target = -1.0
                if _parsed_target > 0.0:
                    _height_scale = _parsed_target
            h_range_raw = float(hmap.max()) - float(hmap.min())
            if h_range_raw > 1e-9:
                # Affine remap: [min, max] → [0, _height_scale]
                hmap = ((hmap - float(hmap.min())) / h_range_raw * _height_scale).astype(np.float32)
            else:
                # Degenerate flat output — generate minimal relief via seed-based offset.
                # T1-11: namespace the caller seed via derive_pass_seed so two
                # different tiles/regions hitting the degenerate fallback do
                # not collapse to the same relief. The 0xDEAD subkey separates
                # this stream from any other macro_world use of the same seed.
                from .terrain_rng import derive_pass_seed as _derive_pass_seed
                rng_fb = np.random.default_rng(
                    _derive_pass_seed(
                        int(seed) ^ 0xDEAD,
                        "terrain_world.pass_macro_world.degenerate_fallback",
                        stack.tile_x,  # HOTFIX-7f C1: was 0 — each tile must
                        stack.tile_y,  # derive a DIFFERENT fallback RNG stream.
                        None,
                    )
                )
                hmap = rng_fb.uniform(0.0, _height_scale, hmap.shape).astype(np.float32)

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

    if stack.height.size == 0:
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

    # -------------------------------------------------------------------------
    # FIX-B14-9: Height rescale — applied FIRST, before any channel derivation.
    #
    # If ``target_height_range_m`` is provided in composition_hints, rescale
    # the heightmap so its full range matches the requested value.  This MUST
    # run before the continental bias and before any downstream channel
    # derivation (cliff_mask, water_surface_elevation_m, splatmap weights) so
    # that all those channels are derived from already-rescaled heights.
    #
    # Without this ordering guarantee a caller that sets a target vertical
    # range would get cliff thresholds, water elevations, and splatmap weights
    # computed against the unscaled (raw noise) heights, then have the height
    # silently rescaled under them — invalidating every height-dependent mask.
    # -------------------------------------------------------------------------
    hints = (intent.composition_hints if intent is not None else {}) or {}
    _target_range_m = hints.get("target_height_range_m")
    if _target_range_m is not None:
        _target_range_m = float(_target_range_m)
        if _target_range_m > 0.0:
            _raw = np.asarray(stack.height, dtype=np.float64)
            _raw_min = float(_raw.min())
            _raw_max = float(_raw.max())
            _raw_range = _raw_max - _raw_min
            if _raw_range > 1e-9:
                # Rescale: preserve minimum, scale range to target.
                _rescaled = (_raw - _raw_min) / _raw_range * _target_range_m + _raw_min
                _rescaled = _rescaled.astype(np.float32)
                stack.set("height", _rescaled, "macro_world")
                stack.set("hmap_low_freq", _rescaled, "macro_world")
                issues.append(ValidationIssue(
                    code="MACRO_HEIGHT_RESCALED",
                    severity="info",
                    message=(
                        f"Height rescaled: raw_range={_raw_range:.2f}m → "
                        f"target_range={_target_range_m:.2f}m."
                    ),
                ))

    # -------------------------------------------------------------------------
    # Continental plate elevation bias (tectonic-scale macro feature)
    # -------------------------------------------------------------------------
    # Read authoring hints from composition_hints.  All keys are optional —
    # when absent the bias is zero and the heightmap is left unchanged.
    # hints already bound in the FIX-B14-9 rescale block above.
    continent_cx_norm = float(hints.get("continent_center_x", 0.5))
    continent_cy_norm = float(hints.get("continent_center_y", 0.5))
    continent_radius_norm = float(hints.get("continent_radius", 0.5))

    hmap_bias = np.asarray(stack.height, dtype=np.float64)
    _h, _w = hmap_bias.shape
    _h_range = float(hmap_bias.max()) - float(hmap_bias.min())
    continent_amplitude = float(
        hints.get("continent_amplitude", _h_range * 0.6)
    )

    # Only apply the bias when a meaningful amplitude is specified
    # (non-zero, or when the author explicitly set continent_center keys).
    _has_continent_hint = (
        "continent_center_x" in hints
        or "continent_center_y" in hints
        or "continent_amplitude" in hints
    )
    if _has_continent_hint and continent_amplitude > 0.0:
        # Build Gaussian dome centred at (cx_px, cy_px) in pixel coordinates.
        # continent_radius_norm=0.5 → sigma = 0.5 × min(H, W) pixels.
        cx_px = continent_cx_norm * (_w - 1)
        cy_px = continent_cy_norm * (_h - 1)
        sigma_px = continent_radius_norm * float(min(_h, _w))
        sigma_px = max(sigma_px, 1.0)  # guard zero-division

        rows_px = np.arange(_h, dtype=np.float64).reshape(-1, 1)
        cols_px = np.arange(_w, dtype=np.float64).reshape(1, -1)
        dist_sq = (rows_px - cy_px) ** 2 + (cols_px - cx_px) ** 2
        continent_dome = continent_amplitude * np.exp(
            -dist_sq / (2.0 * sigma_px ** 2)
        )

        hmap_biased = (hmap_bias + continent_dome).astype(np.float32)
        stack.set("height", hmap_biased, "macro_world")
        stack.set("hmap_low_freq", hmap_biased, "macro_world")

        issues.append(ValidationIssue(
            code="MACRO_CONTINENT_BIAS_APPLIED",
            severity="info",
            message=(
                f"Continental plate bias applied: center=({continent_cx_norm:.2f}, "
                f"{continent_cy_norm:.2f}), sigma={continent_radius_norm:.2f}, "
                f"amplitude={continent_amplitude:.1f}m."
            ),
        ))

    _apply_post_height_seams(stack, "height", "hmap_low_freq")

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
            "continent_bias_applied": _has_continent_hint,
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
    hero_exclusion = _protected_mask(state, stack.height.shape, "structural_masks")
    stack.set("hero_exclusion", hero_exclusion.astype(np.float32), "structural_masks")
    slope = stack.slope
    ridge = stack.ridge
    basin = stack.basin
    if slope is None or ridge is None or basin is None:
        return PassResult(
            pass_name="structural_masks",
            status="failed",
            duration_seconds=time.perf_counter() - t0,
            consumed_channels=("height",),
            issues=[
                ValidationIssue(
                    code="STRUCTURAL_MASKS_MISSING_OUTPUT",
                    severity="hard",
                    message="compute_base_masks did not populate slope, ridge, and basin channels",
                )
            ],
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
            "hero_exclusion",
        ),
        metrics={
            "max_slope_deg": float(np.degrees(slope.max())),
            "mean_slope_deg": float(np.degrees(slope.mean())),
            "ridge_fraction": float(ridge.mean()),
            "basin_count": int(np.unique(basin).size - (1 if 0 in basin else 0)),
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
    profile = str(intent.erosion_profile or "temperate")
    quality_name = getattr(intent, "quality_profile", None) or "aaa_open_world"
    try:
        from .terrain_quality_profiles import load_quality_profile

        quality = load_quality_profile(str(quality_name))
    except Exception:  # noqa: BLE001 - fall back to project default profile
        from .terrain_quality_profiles import load_quality_profile

        quality = load_quality_profile("aaa_open_world")

    # Actual iteration count — no implicit multiplier. See FIX-B14-10.
    # Profile values (mobile=250, standard=2500, high_fidelity=12500,
    # aaa_open_world=50000) are the real droplet counts; tile_scale below
    # keeps per-cell density sane on sub-1024² fixtures.
    quality_hydraulic = max(1, int(quality.hydraulic_erosion_iterations))
    quality_thermal = max(0, int(quality.thermal_erosion_iterations))
    cell_count = max(1, int(stack.height.size))
    reference_cell_count = 1024 * 1024
    tile_scale = min(1.0, math.sqrt(cell_count / reference_cell_count))
    scaled_hydraulic = int(round(quality_hydraulic * tile_scale))
    hydraulic_floor = min(quality_hydraulic, max(1, cell_count // 64))
    hydraulic_iterations = max(
        1,
        min(quality_hydraulic, max(scaled_hydraulic, hydraulic_floor)),
    )
    climate_params: dict[str, float] = {
        "temperate": dict(iteration_scale=1.0, talus_offset=7.0),
        "arid":      dict(iteration_scale=0.8, talus_offset=12.0),
        "alpine":    dict(iteration_scale=1.2, talus_offset=2.0),
    }.get(profile, dict(iteration_scale=1.0, talus_offset=7.0))
    erosion_iterations = max(
        1,
        int(round(hydraulic_iterations * climate_params["iteration_scale"])),
    )
    thermal_iterations = int(quality_thermal)
    talus_angle = float(quality.talus_angle_degrees) + float(climate_params["talus_offset"])
    profile_params: dict[str, int | float | str] = {
        "iterations": erosion_iterations,
        "thermal_iterations": thermal_iterations,
        "talus_angle": talus_angle,
        "quality_profile": quality.name,
        "hydraulic_iteration_ceiling": quality_hydraulic,
        "hydraulic_reference_cell_count": reference_cell_count,
    }

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
    structural_ridge = stack.get("ridge")
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
    # The hardness channel is itself sufficient to modulate erosion; gating
    # this on stratigraphy made the channel inert in isolated pass_erosion
    # runs and broke the intended contract for callers that provide hardness
    # without the optional stratigraphy pre-pass.
    analytical_delta = analytical_result.height_delta
    if rock_hardness is not None:
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
    ridge_out = np.asarray(analytical_result.ridge_map, dtype=np.float32)
    if structural_ridge is not None:
        structural_ridge_arr = np.asarray(structural_ridge, dtype=np.float32)
        ridge_out = np.where(
            structural_ridge_arr > 0.0,
            np.maximum(ridge_out, structural_ridge_arr),
            ridge_out,
        )
    if region is not None:
        r_s, c_s = _region_slice(state, region)
        scoped_ridge = np.zeros_like(ridge_out)
        scoped_ridge[r_s, c_s] = ridge_out[r_s, c_s]
        ridge_out = scoped_ridge
    if protected.any():
        ridge_out = np.where(protected, 0.0, ridge_out)
    # Keep structural_masks as the sole declared DAG producer for ``ridge``
    # (raw analytical ridge field). ``pass_erosion`` publishes its refined
    # variant under the dedicated ``ridge_eroded`` channel so provenance and
    # PassDAG ownership stay explicit — downstream consumers that want the
    # gully-reinforced field should prefer ``ridge_eroded`` and fall back to
    # ``ridge`` when it is absent.
    stack.set("ridge_eroded", np.ascontiguousarray(ridge_out), "erosion")

    # --- Hydraulic erosion (secondary refinement on analytical output) ---
    hydraulic_erodibility = None
    if K_map is not None:
        hydraulic_erodibility = np.clip(K_map / _K_BASE, 0.0, 1.0).astype(np.float32)

    hydro = apply_hydraulic_erosion_masks(
        h_after_analytical,
        iterations=erosion_iterations,
        seed=seed,
        hero_exclusion=hero_arg,
        erodibility_map=hydraulic_erodibility,
    )
    # --- Thermal erosion (smooths sharp analytical features) ---
    thermal = apply_thermal_erosion_masks(
        hydro.height,
        iterations=thermal_iterations,
        talus_angle=talus_angle,
        cell_size=stack.cell_size,
    )

    new_height = thermal.height

    # Region scoping: restore cells outside the region from the pre-pass snapshot.
    r_slice, c_slice = _region_slice(state, region)
    sediment_base_out = getattr(hydro, "sediment_accumulation_at_base", None)
    pool_deepening_out = getattr(hydro, "pool_deepening_delta", None)
    if sediment_base_out is None:
        sediment_base_out = np.zeros_like(h_before, dtype=np.float64)
    if pool_deepening_out is None:
        pool_deepening_out = np.zeros_like(h_before, dtype=np.float64)

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
        sediment_base_out = _scope(np.asarray(sediment_base_out))
        pool_deepening_out = _scope(np.asarray(pool_deepening_out))
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
        sediment_base_out = np.where(protected, 0.0, sediment_base_out)
        pool_deepening_out = np.where(protected, 0.0, pool_deepening_out)

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

    # Apply the post-analytical hardness reduction only to the downstream
    # hydraulic / thermal / SPL delta. Analytical erosion already consumed the
    # hardness modifier above; re-scaling from h_before would double-attenuate
    # that component whenever stratigraphy is present.
    if rock_hardness is not None and stack.get("strat_erosion_delta") is not None:
        rh_arr = np.asarray(rock_hardness, dtype=np.float64)
        rh_arr = rh_arr[:new_height.shape[0], :new_height.shape[1]]
        k_mod_full = 1.0 - 0.7 * np.clip(rh_arr, 0.0, 1.0)
        downstream_delta = new_height - h_after_analytical
        new_height = h_after_analytical + downstream_delta * k_mod_full

    stack.set("height", new_height, "erosion")
    # Fix 12.1: also update hmap_low_freq so pass_composite_hmap sees the eroded base
    stack.set("hmap_low_freq", new_height, "erosion")
    stack.set("erosion_amount", erosion_amount_out, "erosion")
    stack.set("deposition_amount", deposition_amount_out, "erosion")
    stack.set("wetness", wetness_out, "erosion")
    stack.set("drainage", drainage_out, "erosion")
    stack.set("bank_instability", bank_instability_out, "erosion")
    stack.set("talus", talus_out, "erosion")
    stack.set(
        "sediment_accumulation_at_base",
        np.asarray(sediment_base_out, dtype=np.float32),
        "erosion",
    )
    stack.set(
        "pool_deepening_delta",
        np.asarray(pool_deepening_out, dtype=np.float32),
        "erosion",
    )
    _apply_post_height_seams(stack, "height", "hmap_low_freq")

    # Sediment mass-balance metric (AAA spec): ratio of total redeposited
    # material to total eroded material.  A healthy simulation is 0.6–0.95;
    # below 0.1 indicates sediment is being discarded rather than redeposited
    # (mass conservation violation); above 1.0 indicates a net deposition
    # bias (common when analytical erosion deposits more than it removes).
    _total_erosion = float(erosion_amount_out.sum())
    _total_deposition = float(deposition_amount_out.sum())
    _mass_balance_ratio = (
        _total_deposition / _total_erosion if _total_erosion > 1e-9 else 0.0
    )

    return PassResult(
        pass_name="erosion",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("hmap_low_freq",),
        produced_channels=(
            "height",
            "erosion_amount",
            "deposition_amount",
            "wetness",
            "drainage",
            "bank_instability",
            "talus",
            "ridge_eroded",
        ),
        metrics={
            "profile": profile,
            "quality_profile": profile_params["quality_profile"],
            "hydraulic_iterations": profile_params["iterations"],
            "hydraulic_iteration_ceiling": profile_params["hydraulic_iteration_ceiling"],
            "hydraulic_reference_cell_count": profile_params["hydraulic_reference_cell_count"],
            "thermal_iterations": profile_params["thermal_iterations"],
            "total_erosion": _total_erosion,
            "total_deposition": _total_deposition,
            "sediment_mass_balance_ratio": _mass_balance_ratio,
            "total_talus": float(talus_out.sum()),
            "protected_cells": int(protected.sum()),
            "region_scoped": region is not None,
            "structural_ridge_fraction_input": (
                float(np.asarray(structural_ridge, dtype=np.float32).mean())
                if structural_ridge is not None
                else 0.0
            ),
        },
    )


def pass_validation_minimal(
    state: TerrainPipelineState,
    region: Optional[BBox],
    deterministic_seed_override: Optional[int] = None,
) -> PassResult:
    """Pass 4: emit a minimal validation report over the mask stack.

    Checks (AAA spec — matches Houdini HeightField Cook validation and
    World Machine tile export verifier):

      1. Finite check — height channel has no NaN or inf (hard failure).
      2. Height range — the tile must have at least 0.1 % of the expected
         world-scale range; a flat tile (range < 1e-4 of tile_size) is a
         soft warning indicating the macro pass may not have run.
      3. Seam-readiness — height must be defined on all four edges (no zeros
         on the boundary for non-coastal terrain) so neighbouring tiles can
         stitch without seam artefacts.  Emits a soft warning.
      4. Channel NaN sweep — slope, curvature, wetness, drainage checked for
         non-finite values (hard failure per channel).
      5. Sediment mass balance — if both erosion_amount and deposition_amount
         are populated, the ratio |total_deposition / total_erosion| is checked.
         A ratio < 0.05 (< 5 % of eroded material redeposited) is a soft
         warning indicating the erosion pass may be discarding sediment.

    Any hard violation downgrades status to "failed".
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: list[ValidationIssue] = []

    # 1. Finite check
    if not np.all(np.isfinite(stack.height)):
        issues.append(
            ValidationIssue(
                code="HEIGHT_NONFINITE",
                severity="hard",
                message="height channel contains NaN or inf",
            )
        )

    # 2. Height range check
    h_arr = np.asarray(stack.height, dtype=np.float64)
    h_min = float(h_arr.min()) if h_arr.size else 0.0
    h_max = float(h_arr.max()) if h_arr.size else 0.0
    h_range = h_max - h_min
    tile_size = int(stack.tile_size)
    # Minimum meaningful range: 0.1 % of tile_size metres (or 0.001 for
    # dimensionless normalised tiles).  A perfectly flat output means the
    # macro heightmap pass produced no relief.
    min_range_threshold = max(tile_size * 0.001, 1e-4)
    if h_range < min_range_threshold:
        issues.append(
            ValidationIssue(
                code="HEIGHT_RANGE_TOO_SMALL",
                severity="soft",
                message=(
                    f"height range {h_range:.6f} is below minimum threshold "
                    f"{min_range_threshold:.6f} — tile may be flat/uninitialized."
                ),
            )
        )

    # 3. Seam-readiness: all four border rows/cols must be finite and non-zero
    # (zero border suggests the heightmap was not generated edge-to-edge).
    if h_arr.ndim == 2 and h_arr.shape[0] >= 2 and h_arr.shape[1] >= 2:
        border = np.concatenate([
            h_arr[0, :], h_arr[-1, :],
            h_arr[:, 0], h_arr[:, -1],
        ])
        if not np.all(np.isfinite(border)):
            issues.append(
                ValidationIssue(
                    code="BORDER_NONFINITE",
                    severity="hard",
                    message="height border cells contain NaN or inf — tile seam will be corrupt.",
                )
            )
        elif np.all(border == 0.0):
            issues.append(
                ValidationIssue(
                    code="BORDER_ALL_ZERO",
                    severity="soft",
                    message=(
                        "all four height border edges are exactly zero — "
                        "heightmap may not have been generated edge-to-edge, "
                        "risking seam artefacts with neighbouring tiles."
                    ),
                )
            )

    # 4. Channel NaN sweep
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

    # 5. Sediment mass balance
    erosion_arr = stack.get("erosion_amount")
    deposition_arr = stack.get("deposition_amount")
    mass_balance_ratio: float | None = None
    if erosion_arr is not None and deposition_arr is not None:
        total_erosion = float(np.asarray(erosion_arr).sum())
        total_deposition = float(np.asarray(deposition_arr).sum())
        if total_erosion > 1e-9:
            mass_balance_ratio = total_deposition / total_erosion
            if mass_balance_ratio < 0.05:
                issues.append(
                    ValidationIssue(
                        code="EROSION_MASS_BALANCE_LOW",
                        severity="soft",
                        message=(
                            f"sediment mass balance ratio {mass_balance_ratio:.4f} "
                            f"(deposition/erosion) is below 0.05 — erosion pass may "
                            f"be discarding sediment rather than redepositing it."
                        ),
                    )
                )

    status = "failed" if any(i.is_hard() for i in issues) else "ok"

    metrics: dict[str, Any] = {
        "populated_channels": sorted(stack.populated_by_pass.keys()),
        "hard_issues": sum(1 for i in issues if i.is_hard()),
        "soft_issues": sum(1 for i in issues if not i.is_hard()),
        "height_min": h_min,
        "height_max": h_max,
        "height_range": h_range,
    }
    if mass_balance_ratio is not None:
        metrics["sediment_mass_balance_ratio"] = mass_balance_ratio

    return PassResult(
        pass_name="validation_minimal",
        status=status,
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height", "slope"),
        issues=issues,
        metrics=metrics,
    )

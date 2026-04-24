"""Bundle K — terrain_macro_color.

Computes a (H, W, 3) float32 macro-color mask blending biome palette with
altitude and wetness modulations. Populates ``stack.macro_color`` for
Unity shader consumption (driven into a 2D lookup texture).

Dark-fantasy palette: desaturated earth tones, mossy greens, ashen peaks,
cold blue-grey waters.
"""

from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


# Biome id -> base RGB (float32 0..1). Dark-fantasy-tuned.
DARK_FANTASY_PALETTE: Dict[int, Tuple[float, float, float]] = {
    0: (0.32, 0.30, 0.24),   # lowland_earth: desaturated umber
    1: (0.22, 0.30, 0.18),   # forest: mossy green
    2: (0.45, 0.42, 0.32),   # grassland: dry olive
    3: (0.38, 0.34, 0.28),   # rocky_slope: weathered stone
    4: (0.50, 0.49, 0.47),   # highland_ash: ashen grey
    5: (0.82, 0.83, 0.88),   # snowcap: cold off-white
    6: (0.18, 0.22, 0.26),   # bog: dark blue-grey
    7: (0.28, 0.25, 0.20),   # scorched: burnt umber
}

DEFAULT_BIOME_ID = 0


def _resolve_palette(palette: Optional[Dict]) -> Dict[int, Tuple[float, float, float]]:
    if palette is None:
        return DARK_FANTASY_PALETTE
    out: Dict[int, Tuple[float, float, float]] = {}
    for k, v in palette.items():
        try:
            ki = int(k)
        except (TypeError, ValueError):
            continue
        arr = tuple(float(x) for x in v)
        if len(arr) != 3:
            continue
        out[ki] = arr  # type: ignore[assignment]
    if not out:
        return DARK_FANTASY_PALETTE
    return out


def _resolve_strata_color_map(stack: TerrainMaskStack) -> Optional[np.ndarray]:
    """Return (H, W, 3) float64 per-cell strata palette color, or None.

    Reads ``strata_cross_section`` (from the stratigraphy pass): each cell's
    surface material_id indexes into the layer_table's ``color_rgb``. The
    result is stacked into an (H, W, 3) array suitable for palette blending
    in ``compute_macro_color`` — producing Elden Ring-style banded cliffs
    where different rock strata show their geological color.

    Returns ``None`` when the cross-section channel is absent or malformed.
    """
    wrapper = stack.get("strata_cross_section")
    if wrapper is None:
        return None
    # Channel is stored as a (1,)-shape object array around the dict
    try:
        if isinstance(wrapper, np.ndarray) and wrapper.dtype == object:
            cs = wrapper[0] if wrapper.size > 0 else None
        elif isinstance(wrapper, dict):
            cs = wrapper
        else:
            cs = None
    except Exception:
        cs = None
    if not isinstance(cs, dict):
        return None

    layer_table = cs.get("layer_table")
    surface_mat_id = cs.get("surface_material_id")
    if not layer_table or surface_mat_id is None:
        return None

    # Build a (N_layers, 3) palette and index by surface_material_id
    try:
        palette = np.asarray(
            [list(L.get("color_rgb", (0.5, 0.5, 0.5)))[:3] for L in layer_table],
            dtype=np.float64,
        )
    except Exception:
        return None
    if palette.ndim != 2 or palette.shape[1] != 3 or palette.shape[0] == 0:
        return None

    try:
        surf = np.asarray(surface_mat_id, dtype=np.int64)
    except Exception:
        return None
    if surf.ndim != 2:
        return None
    # Shape must match the height grid
    if stack.height is not None and surf.shape != np.asarray(stack.height).shape:
        return None
    surf = np.clip(surf, 0, palette.shape[0] - 1)
    return palette[surf]  # (H, W, 3) float64


def compute_macro_color(
    stack: TerrainMaskStack,
    palette: Optional[Dict] = None,
) -> np.ndarray:
    """Return (H, W, 3) float32 macro-color map.

    Blend model:
        base = palette[biome_id]
        darken for wetness (wet ground darker)
        blue-shift for snow_line_factor (when altitude crosses snow line)
        altitude gradient: higher = slightly cooler/desaturated
    """
    if stack.height is None:
        raise ValueError("compute_macro_color requires stack.height")

    pal = _resolve_palette(palette)
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape

    hmin = float(stack.height_min_m) if stack.height_min_m is not None else float(h.min())
    hmax = float(stack.height_max_m) if stack.height_max_m is not None else float(h.max())
    hspan = max(hmax - hmin, 1e-6)
    h_norm = (h - hmin) / hspan  # 0..1

    # Base color: resolve per-cell biome id or default
    biome = stack.get("biome_id")
    color = np.zeros((rows, cols, 3), dtype=np.float64)
    default_rgb = np.array(pal.get(DEFAULT_BIOME_ID, (0.3, 0.3, 0.3)), dtype=np.float64)
    color[:] = default_rgb.reshape(1, 1, 3)
    if biome is not None:
        biome_arr = np.asarray(biome).astype(np.int32, copy=False)
        for bid, rgb in pal.items():
            mask = biome_arr == bid
            if np.any(mask):
                color[mask] = np.array(rgb, dtype=np.float64)

    # Wetness darkens (wet ground darker + slight blue-grey shift, matching
    # UE5 Landscape wet-surface material response)
    wet = stack.get("wetness")
    if wet is not None:
        wet_arr = np.clip(np.asarray(wet, dtype=np.float64), 0.0, 1.0)[..., None]
        # darken up to 35%; also shift toward cool blue-grey for standing water
        wet_tint = np.array([0.20, 0.22, 0.28], dtype=np.float64).reshape(1, 1, 3)
        color = color * (1.0 - 0.35 * wet_arr) + wet_tint * (0.15 * wet_arr)

    # Erosion bleaching: eroded cells → paler, sandier (exposed fresh rock/soil
    # is lighter before weathering; matches Gaea's erosion color export)
    erosion = stack.get("erosion_amount")
    if erosion is not None:
        er = np.clip(np.asarray(erosion, dtype=np.float64), 0.0, 1.0)[..., None]
        bleach_target = np.array([0.62, 0.58, 0.50], dtype=np.float64).reshape(1, 1, 3)
        color = color * (1.0 - 0.25 * er) + bleach_target * (0.25 * er)

    # Deposition staining: deposited sediment → muddy ochre tones
    deposition = stack.get("deposition_amount")
    if deposition is not None:
        dep = np.clip(np.asarray(deposition, dtype=np.float64), 0.0, 1.0)[..., None]
        mud_target = np.array([0.38, 0.32, 0.22], dtype=np.float64).reshape(1, 1, 3)
        color = color * (1.0 - 0.30 * dep) + mud_target * (0.30 * dep)

    # Stratigraphy palette blend: per-cell surface strata color lookup.
    # Elden Ring-style banded cliffs: the surface rock stratum stamps its
    # geological palette color through the biome base, blended by
    # ``strata_color_weight`` (defaults to 0.55 — strong but not replacing
    # biome entirely so slope/wetness still read).
    strata_color_weight = 0.55
    strata_rgb = _resolve_strata_color_map(stack)
    if strata_rgb is not None:
        color = color * (1.0 - strata_color_weight) + strata_rgb * strata_color_weight

    # Stratigraphy can stamp additive RGB shifts for oxidised intrusions.
    albedo_shift = stack.get("albedo_shift_rgb")
    if albedo_shift is not None:
        shift_arr = np.asarray(albedo_shift, dtype=np.float64)
        if shift_arr.shape == color.shape:
            color = color + shift_arr

    # Altitude cool shift (Z-up): above 0.7 h_norm shift toward blue-grey
    alt_mix = np.clip((h_norm - 0.6) / 0.4, 0.0, 1.0)[..., None]
    cool_target = np.array([0.55, 0.58, 0.65], dtype=np.float64).reshape(1, 1, 3)
    color = color * (1.0 - alt_mix * 0.4) + cool_target * alt_mix * 0.4

    # Snow line overlay
    snow = stack.get("snow_line_factor")
    if snow is not None:
        snow_arr = np.clip(np.asarray(snow, dtype=np.float64), 0.0, 1.0)[..., None]
        snow_rgb = np.array([0.86, 0.88, 0.92], dtype=np.float64).reshape(1, 1, 3)
        color = color * (1.0 - snow_arr) + snow_rgb * snow_arr

    return np.clip(color, 0.0, 1.0).astype(np.float32)


def pass_macro_color(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle K pass: macro color mask.

    Consumes: height (+ optional biome_id, wetness, snow_line_factor)
    Produces: macro_color
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    hints = state.intent.composition_hints if state.intent else {}
    palette = hints.get("macro_color_palette")

    color = compute_macro_color(stack, palette=palette)
    stack.set("macro_color", color, "macro_color")

    return PassResult(
        pass_name="macro_color",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("macro_color",),
        metrics={
            "rgb_mean": [float(color[..., i].mean()) for i in range(3)],
            "rgb_std": [float(color[..., i].std()) for i in range(3)],
            "palette_size": len(_resolve_palette(palette)),
            "strata_palette_applied": bool(
                _resolve_strata_color_map(stack) is not None
            ),
        },
        issues=[],
    )


def register_bundle_k_macro_color_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="macro_color",
            func=pass_macro_color,
            requires_channels=("height",),
            produces_channels=("macro_color",),
            seed_namespace="macro_color",
            requires_scene_read=False,
            description="Bundle K: macro color map from biome/wetness/altitude",
        )
    )


__all__ = [
    "DARK_FANTASY_PALETTE",
    "compute_macro_color",
    "_resolve_strata_color_map",
    "pass_macro_color",
    "register_bundle_k_macro_color_pass",
]

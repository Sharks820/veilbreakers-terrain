"""Bundle K — terrain_macro_color.

Computes a (H, W, 3) float32 macro-color mask blending biome palette with
altitude and wetness modulations. Populates ``stack.macro_color`` for
Unity shader consumption (driven into a 2D lookup texture).

Dark-fantasy palette: desaturated earth tones, mossy greens, ashen peaks,
cold blue-grey waters.

Phase C D28-29 (spec PR #31 + #32):
    PR #31 — pass declaration ``requires_channels`` / ``consumed_channels``
        expanded from ``("height",)`` to the 8 channels actually consulted
        below (height, biome_id, wetness, erosion_amount, deposition_amount,
        albedo_shift_rgb, snow_line_factor, strata_cross_section). Topo-sort
        will now place macro_color after producers of these 8 channels.

    PR #32 — ``DARK_FANTASY_PALETTE`` widened from biome IDs 0-7 to the full
        14-bucket palette (IDs 0-13) used at macro_color generation time.
        The 14 palette buckets are *render-time* biome IDs — distinct from
        the 18 canonical narrative biome names in
        ``terrain_biome_registry.CANONICAL_BIOME_IDS``. See
        ``BIOME_BUCKET_MAP_18_TO_14`` below for the canonical name →
        palette bucket lookup.

    PR #55 review fix (threads #1 / #4 — Codex + Copilot):
        ``stack.biome_id`` from ``pass_compute_biome_channels`` stores
        Voronoi-cell indices in ``[0, biome_count)`` — i.e. positions in
        ``spec.biome_names`` — NOT canonical palette bucket IDs in
        ``[0, 14)``. Without translation, a default tile whose Voronoi
        cell 0 maps to ``thornwood_forest`` paints with palette bucket 0
        (umber/lowland_earth) instead of bucket 1 (forest mossy green),
        and 18-biome runs silently fall through for cells 14-17.

        Fix: ``pass_compute_biome_channels`` now stamps
        ``stack.biome_names`` (the ordered Voronoi-index list) onto the
        stack alongside ``biome_id``. ``compute_macro_color`` builds an
        int32 LUT via ``_build_voronoi_to_bucket_lut`` to translate each
        cell's Voronoi index → canonical biome name → palette bucket
        before lookup. When ``biome_names`` is absent (legacy direct-call
        tests), ``biome_id`` is interpreted as already-bucketed for
        backwards compat.

User-task ambiguity reconciliation (2026-05-08):
    The Phase C task brief described "macro_color expand to 8-channel output
    (RGB + 5 masks)". The authoritative spec (`docs/superpowers/specs/
    2026-05-05-biome-render-rebuild-design.md` rows for PR #31/#32) instead
    specifies "expand `consumed_channels` declaration from 1 to the 8 input
    channels the pass already reads" + "extend palette to 14 entries". This
    file follows the SPEC interpretation; the brief's "8-channel output"
    reading was a mis-paraphrase of "8 channels consumed". Macro_color stays
    RGB-3 on disk (unchanged ABI for Unity shader / lookup texture).
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# Dark-fantasy 14-bucket palette (spec PR #32)
# ---------------------------------------------------------------------------
#
# Biome id -> base RGB (float32 0..1). Dark-fantasy-tuned. Keys 0-7 are the
# pre-existing palette (umber→burnt umber); keys 8-13 are the spec PR #32
# additions covering the remaining 6 biomes referenced by the world-grammar
# producer (volcanic, frozen, desert, jungle_wet, marsh, ash_plain). Total 14
# entries — biome IDs outside this range fall through to ``DEFAULT_BIOME_ID``
# (0 / lowland_earth umber), NOT to neutral grey.
DARK_FANTASY_PALETTE: Dict[int, Tuple[float, float, float]] = {
    0:  (0.32, 0.30, 0.24),   # lowland_earth: desaturated umber
    1:  (0.22, 0.30, 0.18),   # forest: mossy green
    2:  (0.45, 0.42, 0.32),   # grassland: dry olive
    3:  (0.38, 0.34, 0.28),   # rocky_slope: weathered stone
    4:  (0.50, 0.49, 0.47),   # highland_ash: ashen grey
    5:  (0.82, 0.83, 0.88),   # snowcap: cold off-white
    6:  (0.18, 0.22, 0.26),   # bog: dark blue-grey
    7:  (0.28, 0.25, 0.20),   # scorched: burnt umber
    8:  (0.36, 0.18, 0.14),   # volcanic: oxidised iron-red basalt
    9:  (0.74, 0.78, 0.82),   # frozen: pale glacier blue-white
    10: (0.78, 0.66, 0.42),   # desert: warm sand ochre
    11: (0.20, 0.34, 0.22),   # jungle_wet: deep saturated green
    12: (0.30, 0.28, 0.22),   # marsh: muddy umber-olive
    13: (0.55, 0.52, 0.48),   # ash_plain: pale ashen grey
}

# Number of palette buckets (asserted by tests).
PALETTE_BUCKET_COUNT = 14

DEFAULT_BIOME_ID = 0


# ---------------------------------------------------------------------------
# 18-canonical-biome-name -> 14-render-bucket map (spec PR #32)
# ---------------------------------------------------------------------------
#
# The world-grammar emits 18 narrative biome names (see
# ``terrain_biome_registry.CANONICAL_BIOME_IDS``). At macro_color generation
# time these collapse onto 14 *render-time* palette buckets — multiple
# narrative biomes share a bucket when they read identically at the macro
# scale (e.g. ruined_fortress, ruined_citadel, abandoned_village all share
# the rocky_slope/weathered-stone macro tone).
#
# Bucket indices match ``DARK_FANTASY_PALETTE`` keys 0..13.
#
# IMPORTANT (PR #55 review): the lookup is by canonical NAME, not by raw
# numeric ``biome_id``. ``stack.biome_id`` holds Voronoi-cell indices in
# ``[0, biome_count)``, which are positions in ``stack.biome_names``. The
# translation chain is:
#     biome_names[stack.biome_id[r, c]]  ->  BIOME_BUCKET_MAP_18_TO_14  ->
#     DARK_FANTASY_PALETTE[bucket]
# ``compute_macro_color`` builds this as an int32 LUT once per call — see
# ``_build_voronoi_to_bucket_lut`` below.
BIOME_BUCKET_MAP_18_TO_14: Dict[str, int] = {
    # Lowland / earth (bucket 0 — umber)
    "battlefield":        0,
    # Forest (bucket 1 — mossy green)
    "thornwood_forest":   1,
    "deep_forest":        1,
    # Grassland (bucket 2 — dry olive)
    "grasslands":         2,
    # Rocky slope / ruins (bucket 3 — weathered stone)
    "ruined_citadel":     3,
    "ruined_fortress":    3,
    "abandoned_village":  3,
    "cemetery":           3,
    # Highland ash (bucket 4 — ashen grey)
    "mountain_pass":      4,
    # Snowcap (bucket 5 — cold off-white)
    "frozen_hollows":     5,
    # Bog / dark wet (bucket 6 — dark blue-grey)
    "corrupted_swamp":    6,
    "blighted_mire":      6,
    # Scorched (bucket 7 — burnt umber)
    "ashen_wastes":       7,
    # Volcanic (bucket 8 — iron red)
    "veil_crack_zone":    8,
    # Bucket 9 (pale glacier blue / frozen variant) is reserved for future
    # frozen-tundra variants (e.g. v1.1 FrozenTundra biome). Currently unused
    # — every canonical biome above already has a bucket. Tests pin "exactly
    # 14 buckets defined" but allow the bucket-9 slot to be empty in the
    # 18-to-14 lookup.
    # Desert (bucket 10 — warm sand)
    "desert":             10,
    # Jungle / mushroom (bucket 11 — saturated green)
    "mushroom_forest":    11,
    # Coastal / marsh (bucket 12 — muddy)
    "coastal":            12,
    # Crystal cavern (bucket 13 — pale ashen — exotic light source neutral)
    "crystal_cavern":     13,
}


def _build_voronoi_to_bucket_lut(
    biome_names: Optional[Sequence[str]],
) -> Optional[np.ndarray]:
    """Return an int32 LUT mapping Voronoi-cell index -> 14-palette bucket.

    PR #55 review fix (threads #1 / #4 — Codex + Copilot):

    ``stack.biome_id`` stores Voronoi-cell indices in [0, biome_count) — these
    are positions in ``spec.biome_names``, NOT canonical palette bucket IDs in
    [0, 14). Without translation, a default tile whose Voronoi cell 0 maps to
    ``thornwood_forest`` paints with palette bucket 0 (umber/lowland_earth)
    instead of bucket 1 (forest mossy green). Worse, an 18-biome run's IDs
    14-17 silently fall through to the default.

    The LUT translates by canonical name: ``biome_names[i]`` -> bucket via
    ``BIOME_BUCKET_MAP_18_TO_14``. Cells whose canonical name is missing from
    the bucket map fall back to ``DEFAULT_BIOME_ID``. Returns ``None`` when
    no name list is available (callers then use the legacy raw-id path —
    this preserves backwards compat for tests / call sites that set
    ``biome_id`` directly to palette bucket indices).
    """
    if biome_names is None:
        return None
    try:
        names_list: List[str] = [str(n) for n in biome_names]
    except (TypeError, ValueError):
        return None
    if not names_list:
        return None
    lut = np.empty(len(names_list), dtype=np.int32)
    for i, nm in enumerate(names_list):
        bucket = BIOME_BUCKET_MAP_18_TO_14.get(nm)
        if bucket is None:
            # Unknown / non-canonical biome name -> fall back to umber.
            bucket = DEFAULT_BIOME_ID
        lut[i] = int(bucket)
    return lut


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
    biome_names: Optional[Sequence[str]] = None,
) -> np.ndarray:
    """Return (H, W, 3) float32 macro-color map.

    Args:
        stack: Mask stack with ``height`` (required) and the soft-read
            channels listed in ``MACRO_COLOR_CONSUMED_CHANNELS``.
        palette: Optional override for ``DARK_FANTASY_PALETTE``.
        biome_names: Ordered list of canonical biome names matching the
            Voronoi indices stored in ``stack.biome_id`` (i.e.
            ``biome_names[stack.biome_id[r, c]]`` is the canonical name of
            the biome at cell (r, c)). When provided, the per-cell ID is
            translated through ``BIOME_BUCKET_MAP_18_TO_14`` to the 14-bucket
            render palette. When omitted, ``stack.biome_names`` is consulted
            (set by ``pass_compute_biome_channels``); failing that, ``biome_id``
            values are interpreted as already-bucketed palette indices —
            preserving the legacy contract used by direct-call tests.

    Blend model:
        base = palette[bucket(biome_id)]
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
        # PR #55 review fix (threads #1 / #4): translate Voronoi-index
        # biome_id -> 14-bucket palette index when a biome_names list is
        # available (either passed in or stamped onto the stack by
        # pass_compute_biome_channels). Falls back to raw biome_id values
        # when no names list is available — preserves the legacy contract
        # for tests that set biome_id directly to palette bucket indices.
        names_for_lut: Optional[Sequence[str]] = biome_names
        if names_for_lut is None:
            names_for_lut = getattr(stack, "biome_names", None)
        lut = _build_voronoi_to_bucket_lut(names_for_lut)
        if lut is not None:
            # Clamp out-of-range Voronoi indices to default bucket (defends
            # against biome_id values >= len(biome_names)).
            clamped = np.clip(biome_arr, 0, len(lut) - 1)
            bucket_arr = lut[clamped].astype(np.int32, copy=False)
        else:
            bucket_arr = biome_arr
        for bid, rgb in pal.items():
            mask = bucket_arr == bid
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


# ---------------------------------------------------------------------------
# Pass-contract declaration (spec PR #31)
# ---------------------------------------------------------------------------
#
# The 8 channels ``compute_macro_color`` actually consults at runtime. Spec
# row PR #31 explicitly enumerates these — they were previously declared
# only as ``("height",)`` which broke topo-sort placement (macro_color could
# run before producers of biome_id / wetness / erosion_amount /
# deposition_amount / albedo_shift_rgb / snow_line_factor /
# strata_cross_section, leading to silent fall-through to default values).
#
# Order is canonical-spec order; tests pin exact tuple equality.
MACRO_COLOR_CONSUMED_CHANNELS: Tuple[str, ...] = (
    "height",
    "biome_id",
    "wetness",
    "erosion_amount",
    "deposition_amount",
    "albedo_shift_rgb",
    "snow_line_factor",
    "strata_cross_section",
)


def pass_macro_color(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle K pass: macro color mask.

    Consumes (8 channels — spec PR #31):
        height, biome_id, wetness, erosion_amount, deposition_amount,
        albedo_shift_rgb, snow_line_factor, strata_cross_section
    Produces:
        macro_color  (H, W, 3) float32

    All non-height channel reads are guarded (``stack.get(...)`` returns
    ``None`` when absent, in which case that modulation step is skipped).
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    hints = state.intent.composition_hints if state.intent else {}
    palette = hints.get("macro_color_palette")
    # PR #55 review fix (threads #1 / #4): pull biome_names off the stack
    # (stamped by pass_compute_biome_channels) so the Voronoi-index ->
    # 14-bucket palette translation runs. Falls back to None when absent
    # (legacy direct-call sites that set biome_id to palette indices).
    biome_names = getattr(stack, "biome_names", None)

    color = compute_macro_color(stack, palette=palette, biome_names=biome_names)
    stack.set("macro_color", color, "macro_color")

    return PassResult(
        pass_name="macro_color",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        # PR #31: declare all 8 channels actually read so the DAG sees the
        # truth. Soft reads (everything except height) are guarded inside
        # compute_macro_color so the pass still runs when they are absent.
        consumed_channels=MACRO_COLOR_CONSUMED_CHANNELS,
        produced_channels=("macro_color",),
        metrics={
            "rgb_mean": [float(color[..., i].mean()) for i in range(3)],
            "rgb_std": [float(color[..., i].std()) for i in range(3)],
            "palette_size": len(_resolve_palette(palette)),
            "strata_palette_applied": bool(
                _resolve_strata_color_map(stack) is not None
            ),
            "biome_bucket_remap_applied": bool(biome_names is not None),
        },
        issues=[],
    )


def register_bundle_k_macro_color_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="macro_color",
            func=pass_macro_color,
            # PR #31: ``height`` is the only HARD requirement (raises if
            # absent). The other 7 channels are soft reads — declared as
            # ``optional_channels`` so the DAG schedules their producers
            # before macro_color when registered, but doesn't block the
            # pipeline when they're absent (e.g. unit tests with bare
            # height-only stacks).
            requires_channels=("height",),
            optional_channels=(
                "biome_id",
                "wetness",
                "erosion_amount",
                "deposition_amount",
                "albedo_shift_rgb",
                "snow_line_factor",
                "strata_cross_section",
            ),
            produces_channels=("macro_color",),
            seed_namespace="macro_color",
            requires_scene_read=False,
            description=(
                "Bundle K: macro color map from biome/wetness/altitude/"
                "erosion/deposition/strata/snow (8 input channels per "
                "spec PR #31). 14-bucket palette per spec PR #32."
            ),
        )
    )


__all__ = [
    "BIOME_BUCKET_MAP_18_TO_14",
    "DARK_FANTASY_PALETTE",
    "DEFAULT_BIOME_ID",
    "MACRO_COLOR_CONSUMED_CHANNELS",
    "PALETTE_BUCKET_COUNT",
    "compute_macro_color",
    "_build_voronoi_to_bucket_lut",
    "_resolve_strata_color_map",
    "pass_macro_color",
    "register_bundle_k_macro_color_pass",
]

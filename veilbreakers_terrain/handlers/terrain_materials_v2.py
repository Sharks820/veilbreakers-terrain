"""Bundle B — Slope/altitude/curvature/wetness-driven material rules.

Replaces biome-name keyed material assignment with vectorised per-cell
splatmap weights driven by the mask stack. DOES NOT modify the legacy
``terrain_materials`` module — it coexists as ``_v2`` so old tests stay
green while Bundle B callers opt in.

Agent protocol compliance:
- Rule 3: writes ``splatmap_weights_layer`` + ``material_weights`` to
  the ``TerrainMaskStack``
- Rule 6: altitude gates are world meters on the Z axis (stack.height)
- Rule 7: ``splatmap_weights_layer`` is the Unity consumer channel
- Rule 10: no ``np.clip(..., 0, 1)`` on world heights (only on weights)
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MaterialChannel:
    """A single material layer in the splatmap.

    Each channel declares an envelope over slope / altitude / curvature /
    wetness. The weight for each cell is the product of smoothstep ramps
    inside each envelope. All thresholds are world-unit (radians for
    slope, world meters for altitude).
    """

    channel_id: str
    base_color_hex: str = "#808080"
    roughness: float = 0.8
    metallic: float = 0.0
    triplanar: bool = False
    # Slope envelope (radians)
    slope_min_rad: float = 0.0
    slope_max_rad: float = math.pi / 2.0
    slope_falloff_rad: float = math.radians(5.0)
    # Altitude envelope (world meters, Z up)
    altitude_min_m: float = -1e9
    altitude_max_m: float = 1e9
    altitude_falloff_m: float = 5.0
    # Curvature envelope (unitless, signed Laplacian)
    curvature_min: float = -1e9
    curvature_max: float = 1e9
    # Wetness envelope (0..1)
    wetness_min: float = 0.0
    wetness_max: float = 1.0
    # Base multiplier — higher = channel "wins" in overlap regions
    base_weight: float = 1.0


@dataclass
class MaterialRuleSet:
    """Ordered tuple of MaterialChannel layers + a default fallback layer.

    The ``default_channel_id`` identifies the layer that picks up cells
    where every rule returned zero weight. It must be present in
    ``channels``.
    """

    channels: Tuple[MaterialChannel, ...] = field(default_factory=tuple)
    default_channel_id: str = "ground"

    def __post_init__(self) -> None:
        ids = [c.channel_id for c in self.channels]
        if len(ids) != len(set(ids)):
            raise ValueError(f"MaterialRuleSet channel_ids must be unique: {ids}")
        if self.default_channel_id not in ids:
            raise ValueError(
                f"default_channel_id={self.default_channel_id!r} "
                f"not in channels {ids}"
            )

    def index_of(self, channel_id: str) -> int:
        for i, c in enumerate(self.channels):
            if c.channel_id == channel_id:
                return i
        raise KeyError(channel_id)


# ---------------------------------------------------------------------------
# Default rules
# ---------------------------------------------------------------------------


def default_dark_fantasy_rules() -> MaterialRuleSet:
    """Return the default Bundle B rule set: 5 channels.

    ground   — low slope, any altitude (the fallback)
    cliff    — high slope, triplanar
    scree    — moderate slope, low altitude, near the base of cliffs
    wet_rock — any slope with wetness > 0.3
    snow     — altitude > snow line
    """
    channels = (
        MaterialChannel(
            channel_id="ground",
            base_color_hex="#5a4e3a",
            roughness=0.9,
            triplanar=False,
            slope_min_rad=0.0,
            slope_max_rad=math.radians(30.0),
            slope_falloff_rad=math.radians(8.0),
            base_weight=1.0,
        ),
        MaterialChannel(
            channel_id="cliff",
            base_color_hex="#3c3630",
            roughness=0.85,
            triplanar=True,
            slope_min_rad=math.radians(40.0),
            slope_max_rad=math.pi / 2.0,
            slope_falloff_rad=math.radians(10.0),
            base_weight=1.2,
        ),
        MaterialChannel(
            channel_id="scree",
            base_color_hex="#6b6055",
            roughness=0.95,
            triplanar=False,
            slope_min_rad=math.radians(25.0),
            slope_max_rad=math.radians(45.0),
            slope_falloff_rad=math.radians(6.0),
            altitude_max_m=200.0,
            altitude_falloff_m=20.0,
            base_weight=0.8,
        ),
        MaterialChannel(
            channel_id="wet_rock",
            base_color_hex="#2c2a28",
            roughness=0.35,
            triplanar=True,
            slope_min_rad=math.radians(15.0),
            slope_max_rad=math.pi / 2.0,
            slope_falloff_rad=math.radians(8.0),
            wetness_min=0.3,
            wetness_max=1.0,
            base_weight=1.5,
        ),
        MaterialChannel(
            channel_id="snow",
            base_color_hex="#e8ecef",
            roughness=0.6,
            triplanar=False,
            slope_min_rad=0.0,
            slope_max_rad=math.radians(50.0),
            slope_falloff_rad=math.radians(8.0),
            altitude_min_m=250.0,
            altitude_falloff_m=30.0,
            base_weight=1.3,
        ),
    )
    return MaterialRuleSet(channels=channels, default_channel_id="ground")


# ---------------------------------------------------------------------------
# Triplanar projection (Fix 7.16 / BUG-116 / REQ-P7-007)
# ---------------------------------------------------------------------------


def triplanar_blend(
    normal: np.ndarray,
    pos: np.ndarray,
    noise_fn: "Callable[[np.ndarray], np.ndarray]",
    sharpness: float = 4.0,
) -> np.ndarray:
    """Triplanar noise blend weighted by surface normal.

    Eliminates Z-only texture stretching on steep surfaces. The blend weights
    are: w = abs(normal)^sharpness, normalised to sum=1 per cell.

    Args:
        normal: (H, W, 3) float32 surface normals, world-space.
        pos: (H, W, 3) float32 world-space XYZ positions.
        noise_fn: Callable accepting (N, 2) float64 UV coords, returning (N,) float.
        sharpness: Exponent for normal-based weight sharpening. Default 4.0.
            Higher values tighten the blend toward the dominant axis.

    Returns:
        (H, W) float32 blended noise values.

    Reference: Fix 7.16 / BUG-116 / CONTEXT.md triplanar formula.
    Formula: w = |n|^e / sum(|n|^e); blend = w.x*f(yz) + w.y*f(xz) + w.z*f(xy)
    """
    normal = np.asarray(normal, dtype=np.float64)
    pos = np.asarray(pos, dtype=np.float64)

    w = np.abs(normal) ** sharpness                    # (H, W, 3)
    w_sum = w.sum(axis=2, keepdims=True).clip(1e-9, None)
    w = w / w_sum                                       # normalised

    H, W = normal.shape[:2]

    # Three projection planes: YZ, XZ, XY
    yz_coords = pos[..., 1:3].reshape(-1, 2).astype(np.float64)
    xz_coords = pos[..., [0, 2]].reshape(-1, 2).astype(np.float64)
    xy_coords = pos[..., :2].reshape(-1, 2).astype(np.float64)

    n_yz = np.asarray(noise_fn(yz_coords)).reshape(H, W)
    n_xz = np.asarray(noise_fn(xz_coords)).reshape(H, W)
    n_xy = np.asarray(noise_fn(xy_coords)).reshape(H, W)

    blend = (w[..., 0] * n_yz + w[..., 1] * n_xz + w[..., 2] * n_xy)
    return blend.astype(np.float32)


# ---------------------------------------------------------------------------
# Normal-z rock mask helpers (Fix 10.1 / REQ-P10-002)
# ---------------------------------------------------------------------------

ROCK_NORMAL_THRESHOLD: float = 0.65
"""Surface normal z-component below this threshold → classify as rock face.
Replaces the former slope > slope_threshold check (Fix 10.1 / REQ-P10-002).
Handles overhangs and cave ceilings correctly; slope threshold cannot.
"""


def compute_normal_z(heightmap: np.ndarray) -> np.ndarray:
    """Return the z-component of the unit surface normal for every cell.

    Uses numpy gradient (consistent with existing codebase convention).
    Result is in [0, 1]: 1.0 = perfectly flat, approaching 0 = vertical wall.

    Formula (from CONTEXT.md Fix 10.1):
        dy, dx = np.gradient(heightmap)
        denom  = np.sqrt(dx**2 + dy**2 + 1.0)
        normal_z = 1.0 / denom

    NaN/Inf in heightmap are replaced with 0 before gradient (T-10-02-01).
    """
    h = np.nan_to_num(np.asarray(heightmap, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    dy, dx = np.gradient(h)
    denom = np.sqrt(dx ** 2 + dy ** 2 + 1.0)
    return np.clip(1.0 / denom, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Brucks height-blend (Fix 10.6 / REQ-P10-003)
# ---------------------------------------------------------------------------


def apply_brucks_blend(
    blend_alpha: np.ndarray,
    rock_height_factor: np.ndarray,
    dirt_height_factor: float = 0.5,
    contrast: float = 0.2,
) -> "Tuple[np.ndarray, np.ndarray]":
    """Brucks height-blend for rock/dirt boundary (Fix 10.6 / REQ-P10-003).

    Rock strata 'poke through' dirt based on strata band height.
    Eliminates the flat uniform paint-over look at material boundaries.

    Formula (from CONTEXT.md Fix 10.6):
        ma     = max(rock_height_factor + (1-blend_alpha),
                     dirt_height_factor + blend_alpha) - contrast
        b_rock = max(rock_height_factor + (1-blend_alpha) - ma, 0)
        b_dirt = max(dirt_height_factor + blend_alpha - ma, 0)

    Args:
        blend_alpha: float32 array [0..1], current analytical blend weight
                     (0 = fully dirt, 1 = fully rock).
        rock_height_factor: float32 array, strata band height from stratigraphy
                            pass (stack.get("strata_height"), fallback 0.5).
        dirt_height_factor: scalar, uniform soft material constant (default 0.5).
        contrast: scalar, boundary sharpness (default 0.2).

    Returns:
        (b_rock, b_dirt) — unnormalised weight arrays; caller divides by sum+1e-8.
    """
    rock_h = np.asarray(rock_height_factor, dtype=np.float64)
    d_h = float(dirt_height_factor)
    alpha = np.asarray(blend_alpha, dtype=np.float64)
    c = float(contrast)

    rock_contrib = rock_h + (1.0 - alpha)
    dirt_contrib = d_h + alpha
    ma = np.maximum(rock_contrib, dirt_contrib) - c
    b_rock = np.maximum(rock_contrib - ma, 0.0).astype(np.float32)
    b_dirt = np.maximum(dirt_contrib - ma, 0.0).astype(np.float32)
    return b_rock, b_dirt


# ---------------------------------------------------------------------------
# Snow line factor (Fix 10.5 / REQ-P10-006)
# ---------------------------------------------------------------------------


def compute_snow_line_factor(
    height: np.ndarray,
    slope: np.ndarray,
    climate_params: Optional[dict] = None,
) -> np.ndarray:
    """Compute snow line coverage factor per cell (Fix 10.5 / REQ-P10-006).

    Returns float32 array in [0..1]. High values = snow-eligible altitude.

    Formula (from CONTEXT.md Fix 10.5):
        snow_alt   = climate_params.get("snow_altitude", 0.7)   # 0-1 normalized
        snow_width = climate_params.get("snow_transition", 0.1)
        base       = 1.0 / (1.0 + exp(-(height - snow_alt) / snow_width))  # sigmoid
        slope_mod  = 1.0 - 0.3 * abs(sin(slope))  # reduce on steep slopes
        return base * slope_mod

    Args:
        height:        float32 (H,W), normalized 0-1 height values.
        slope:         float32 (H,W), slope in radians.
        climate_params: dict with optional keys snow_altitude (default 0.7)
                        and snow_transition (default 0.1).

    Guards (T-10-02-02): snow_width clamped to [1e-6, inf] to avoid /0.
    Guards (T-10-02-04): snow_altitude clamped to [0,1]; snow_transition to [0.01, 0.5].
    """
    if climate_params is None:
        climate_params = {}
    snow_alt = float(np.clip(climate_params.get("snow_altitude", 0.7), 0.0, 1.0))
    snow_width = float(np.clip(climate_params.get("snow_transition", 0.1), 0.01, 0.5))
    h = np.asarray(height, dtype=np.float64)
    s = np.asarray(slope, dtype=np.float64)
    base = 1.0 / (1.0 + np.exp(-(h - snow_alt) / snow_width))
    slope_mod = 1.0 - 0.3 * np.abs(np.sin(s))
    return (base * slope_mod).astype(np.float32)


# ---------------------------------------------------------------------------
# Ridge → ravine material (Fix 10.3 / REQ-P10-004)
# ---------------------------------------------------------------------------

RAVINE_THRESHOLD: float = 0.0
"""Ridge channel value below this → erosion channel (ravine). Drives wetter drainage material.
Fix 10.3: ridge channel produced by erosion is now consumed by the materials system.
"""


# ---------------------------------------------------------------------------
# Macro color multiply (Fix 10.8 / REQ-P10-004)
# ---------------------------------------------------------------------------


def sample_macro_color(
    world_x: np.ndarray,
    world_z: np.ndarray,
    macro_texture: np.ndarray,
    tile_size_m: float = 512.0,
) -> np.ndarray:
    """Sample a 64x64 authored macro color texture in world-space XZ (Fix 10.8).

    The texture tiles every tile_size_m metres. Returns (H, W, 3) float32 RGB
    where H×W matches the input world_x / world_z arrays.

    Args:
        world_x:       (H, W) float32, world X coordinates per cell.
        world_z:       (H, W) float32, world Z coordinates per cell.
        macro_texture: (tex_h, tex_w, 3) float32 authored RGB texture, values [0..1].
        tile_size_m:   World-space extent of one full texture tile, metres.

    Guard (T-10-03-03): non-(N,M,3) macro_texture should be handled by caller.
    """
    tex_h, tex_w = macro_texture.shape[:2]
    # Wrap world coordinates into [0, 1) then map to texel indices
    u = ((world_x / tile_size_m) % 1.0)
    v = ((world_z / tile_size_m) % 1.0)
    ui = np.clip((u * tex_w).astype(np.int32), 0, tex_w - 1)
    vi = np.clip((v * tex_h).astype(np.int32), 0, tex_h - 1)
    return macro_texture[vi, ui, :].astype(np.float32)


# ---------------------------------------------------------------------------
# SDF road edge blending (Fix 10.9 / REQ-P10-005)
# ---------------------------------------------------------------------------

ROAD_EDGE_FADE_WIDTH: float = 2.0
"""Distance in metres over which the road-gravel splatmap fades to terrain base.
Fix 10.9 / REQ-P10-005. Requires road_sdf_dist channel from Phase 8 Fix 8.13.
"""


def apply_sdf_road_blend(
    weights: np.ndarray,
    road_sdf_dist: np.ndarray,
    rules: "MaterialRuleSet",
    road_channel_id: str = "scree",
    edge_fade_width: float = ROAD_EDGE_FADE_WIDTH,
) -> np.ndarray:
    """Blend road-gravel splatmap against terrain base using SDF edge weight (Fix 10.9).

    Formula (from CONTEXT.md Fix 10.9):
        edge_weight = saturate(1.0 - road_sdf_dist / edge_fade_width)

    where saturate = np.clip(..., 0.0, 1.0).

    Cells within edge_fade_width of a road get their road_channel_id weight
    blended toward 1.0 proportionally. All other weights are compressed to fill
    the remainder (1.0 - edge_weight), keeping the per-cell sum = 1.0.

    Args:
        weights:        (H, W, L) float32, current splatmap weights (sum=1 per cell).
        road_sdf_dist:  (H, W) float32, signed distance in metres from road.
                        0 = on road, positive = off road.
        rules:          MaterialRuleSet, used to resolve road_channel_id index.
        road_channel_id: Channel ID to boost at road edges. Defaults to "scree".
        edge_fade_width: Fade distance in metres. Default 2.0.
                        Guard (T-10-03-02): clamped to minimum 1e-6.

    Returns:
        Modified (H, W, L) float32 weights, sum=1 per cell.
    """
    try:
        road_idx = rules.index_of(road_channel_id)
    except KeyError:
        return weights  # No road channel in this rule set; return unchanged.

    ew = max(float(edge_fade_width), 1e-6)  # T-10-03-02: guard /0
    sdf = np.asarray(road_sdf_dist, dtype=np.float32)
    # saturate(1.0 - road_sdf_dist / edge_fade_width)
    edge_weight = np.clip(1.0 - sdf / ew, 0.0, 1.0)  # (H, W)

    w = weights.copy()
    L = w.shape[2]

    # Boost road_channel to edge_weight; compress all other channels proportionally.
    other_mask = np.ones(L, dtype=bool)
    other_mask[road_idx] = False
    other_w = w[:, :, other_mask]         # (H, W, L-1)

    # Sum of non-road weights before rescaling
    other_sum = other_w.sum(axis=2)        # (H, W)
    # Scale factor for other weights: (1 - edge_weight) / (other_sum + eps)
    scale = np.where(
        other_sum > 1e-9,
        (1.0 - edge_weight) / (other_sum + 1e-9),
        0.0,
    )                                      # (H, W)

    # Write updated values back
    w[:, :, road_idx] = edge_weight
    other_indices = np.where(other_mask)[0]
    for i, oi in enumerate(other_indices):
        w[:, :, oi] = (other_w[:, :, i] * scale).astype(np.float32)

    return w.astype(np.float32)


# ---------------------------------------------------------------------------
# Weight computation
# ---------------------------------------------------------------------------


def _smoothstep_band(
    value: np.ndarray,
    lo: float,
    hi: float,
    falloff: float,
) -> np.ndarray:
    """Return a [0,1] mask that is 1 inside [lo, hi] and ramps to 0 over falloff."""
    f = max(float(falloff), 1e-9)
    # Ramp up on the low side, ramp down on the high side
    up = np.clip((value - (lo - f)) / f, 0.0, 1.0)
    down = np.clip(((hi + f) - value) / f, 0.0, 1.0)
    return up * down


def compute_slope_material_weights(
    stack: TerrainMaskStack,
    rules: Optional[MaterialRuleSet] = None,
) -> np.ndarray:
    """Return (H, W, L) float32 splatmap weights, normalized to sum=1.

    Fully vectorized — no Python per-cell loops. Computes each channel's
    envelope in parallel using numpy broadcast, then normalizes weights
    across the layer axis.
    """
    if rules is None:
        rules = default_dark_fantasy_rules()

    slope = stack.get("slope")
    if slope is None:
        raise KeyError("compute_slope_material_weights requires 'slope' on the stack")
    slope = np.asarray(slope, dtype=np.float64)
    height = np.asarray(stack.height, dtype=np.float64)

    curvature = stack.get("curvature")
    if curvature is None:
        curvature = np.zeros_like(slope)
    else:
        curvature = np.asarray(curvature, dtype=np.float64)

    wetness = stack.get("wetness")
    if wetness is None:
        wetness = np.zeros_like(slope)
    else:
        wetness = np.asarray(wetness, dtype=np.float64)

    L = len(rules.channels)
    H, W = slope.shape
    weights = np.zeros((H, W, L), dtype=np.float32)

    # Fix 10.1 (REQ-P10-002): Compute surface normal z-component for rock masking.
    # normal_z < ROCK_NORMAL_THRESHOLD → rock face (replaces slope threshold).
    surface_normal_z = compute_normal_z(stack.height)

    # Fix 10.4 (REQ-P10-006): Read snow_line_factor for top-facing snow mask.
    snow_line_factor = stack.get("snow_line_factor")

    for idx, ch in enumerate(rules.channels):
        # Fix 10.1: For triplanar/rock channels, use normal_z instead of slope.
        if ch.triplanar:
            # normal_z < ROCK_NORMAL_THRESHOLD indicates a rock face.
            # Map to [0,1] weight using a smoothstep over a 0.1 transition band.
            rock_normal_w = np.clip(
                (ROCK_NORMAL_THRESHOLD - surface_normal_z.astype(np.float64)) / 0.1 + 1.0,
                0.0, 1.0
            )
            slope_w = rock_normal_w
        else:
            slope_w = _smoothstep_band(
                slope, ch.slope_min_rad, ch.slope_max_rad, ch.slope_falloff_rad
            )
        alt_w = _smoothstep_band(
            height, ch.altitude_min_m, ch.altitude_max_m, ch.altitude_falloff_m
        )
        curv_w = np.where(
            (curvature >= ch.curvature_min) & (curvature <= ch.curvature_max),
            1.0,
            0.0,
        )
        wet_w = np.where(
            (wetness >= ch.wetness_min) & (wetness <= ch.wetness_max),
            1.0,
            0.0,
        )
        combined = ch.base_weight * slope_w * alt_w * curv_w * wet_w

        # Triplanar blend perturbation for steep-surface materials (Fix 7.16)
        if ch.triplanar:
            # Default sin-based noise_fn (Phase 11 will inject proper OpenSimplex2S)
            def _default_noise(uv: np.ndarray) -> np.ndarray:
                return np.sin(uv[:, 0] * 3.7 + uv[:, 1] * 2.1) * 0.5 + 0.5

            h_arr = np.asarray(stack.height, dtype=np.float64)
            H_s, W_s = h_arr.shape
            r_idx, c_idx = np.mgrid[0:H_s, 0:W_s]
            pos_3d = np.stack([
                c_idx.astype(np.float64),
                r_idx.astype(np.float64),
                h_arr,
            ], axis=2)
            normals_3d = np.zeros((H_s, W_s, 3), dtype=np.float64)
            normals_3d[..., 2] = 1.0  # default up-normal

            # Tilt normals for steep cells using slope channel
            if slope is not None:
                steep = slope > math.radians(45.0)
                normals_3d[steep, 0] = 0.7
                normals_3d[steep, 2] = 0.7

            noise_perturb = triplanar_blend(normals_3d, pos_3d, _default_noise)
            # Apply as a subtle multiplicative perturbation [0.8, 1.2]
            combined = combined * (0.8 + 0.4 * noise_perturb)

        weights[:, :, idx] = combined.astype(np.float32)

    # Fix 10.4 (REQ-P10-006): Top-facing snow mask — normal.z > 0.9 AND above snow line.
    # Applied BEFORE Brucks blend and label overrides so labels can still override snow.
    if snow_line_factor is not None:
        snow_mask = (surface_normal_z > 0.9).astype(np.float32) * np.asarray(
            snow_line_factor, dtype=np.float32
        )
        try:
            snow_idx = rules.index_of("snow")
            weights[:, :, snow_idx] = snow_mask
        except KeyError:
            pass  # No snow channel in this rule set; skip silently.

    # Fix 10.6 (REQ-P10-003): Brucks height-blend at rock/dirt boundary.
    # Rock strata poke through dirt according to strata band height.
    try:
        cliff_idx = rules.index_of("cliff")
        ground_idx = rules.index_of("ground")
        strata_h = stack.get("strata_height")
        if strata_h is not None:
            rock_h_factor = np.asarray(strata_h, dtype=np.float32)
            blend_alpha = weights[:, :, cliff_idx].copy()
            b_rock, b_dirt = apply_brucks_blend(
                blend_alpha=blend_alpha,
                rock_height_factor=rock_h_factor,
            )
            total_bd = b_rock + b_dirt + 1e-8
            weights[:, :, cliff_idx] = (b_rock / total_bd).astype(np.float32)
            weights[:, :, ground_idx] = (b_dirt / total_bd).astype(np.float32)
    except KeyError:
        pass  # rule set doesn't have cliff or ground channel; skip silently

    # Fix 10.3: Ridge → ravine material blend.
    # Negative ridge values = erosion channels. Apply darker/wetter drainage material.
    ridge = stack.get("ridge")
    if ridge is not None:
        ridge_arr = np.asarray(ridge, dtype=np.float32)
        ravine_mask = (ridge_arr < RAVINE_THRESHOLD).astype(np.float32)
        if ravine_mask.any():
            try:
                wet_idx = rules.index_of("wet_rock")
                # Ravine depth below threshold drives additional wet_rock weight.
                # np.clip already guards against ridge values far outside [-1,1] (T-10-03-04)
                ravine_depth = np.clip(-ridge_arr, 0.0, 1.0)
                ravine_weight = ravine_mask * ravine_depth
                weights[:, :, wet_idx] = np.clip(
                    weights[:, :, wet_idx] + ravine_weight, 0.0, 1.0
                ).astype(np.float32)
            except KeyError:
                pass  # No wet_rock channel in this rule set; skip silently.
        # Re-normalize after ravine blend injection (labeled cells will re-override below)
        total_rv = weights.sum(axis=2, keepdims=True)
        total_rv = np.where(total_rv > 1e-9, total_rv, 1.0)
        weights = (weights / total_rv).astype(np.float32)

    # --- Structural label overrides (Fix 10.10 / REQ-P10-001) ---
    # Feature generators stamp labels during generation; labels take priority over
    # analytical slope classification. Labeled cells skip the analytical path.
    rock_label   = stack.get("rock_label")    # float32 mask [0..1]
    gravel_label = stack.get("gravel_label")  # float32 mask [0..1]
    water_label  = stack.get("water_label")   # float32 mask [0..1]
    cliff_label  = stack.get("cliff_label")   # float32 mask [0..1]
    has_labels = any(lbl is not None for lbl in (rock_label, gravel_label, water_label, cliff_label))

    if has_labels:
        # Map label channel → splatmap layer index.
        # Only assign if the target channel_id exists in the rule set.
        _label_channel_map = {
            "rock_label":   ("cliff",),     # rock structural label → cliff material
            "gravel_label": ("scree",),     # gravel structural label → scree material
            "water_label":  ("wet_rock",),  # water structural label → wet_rock material
            "cliff_label":  ("cliff",),     # cliff structural label → cliff material
        }
        label_arrays = {
            "rock_label":   rock_label,
            "gravel_label": gravel_label,
            "water_label":  water_label,
            "cliff_label":  cliff_label,
        }
        for label_key, target_ids in _label_channel_map.items():
            lbl = label_arrays[label_key]
            if lbl is None:
                continue
            lbl = np.asarray(lbl, dtype=np.float32)
            labeled = lbl > 0.5  # boolean mask of labeled cells
            if not labeled.any():
                continue
            for target_id in target_ids:
                try:
                    tidx = rules.index_of(target_id)
                except KeyError:
                    continue
                # For labeled cells: zero all layers, then set the target layer to 1.0
                weights[labeled, :] = 0.0
                weights[labeled, tidx] = 1.0

    # Build all_labeled mask for conditional normalization
    if has_labels:
        all_labeled = np.zeros((H, W), dtype=bool)
        for label_key, lbl in label_arrays.items():
            if lbl is not None:
                all_labeled |= (np.asarray(lbl, dtype=np.float32) > 0.5)
        unlabeled = ~all_labeled
    else:
        unlabeled = np.ones((H, W), dtype=bool)

    # Fallback: any unlabeled cell whose total weight is 0 gets 1.0 on the default layer
    total = weights.sum(axis=2)
    default_idx = rules.index_of(rules.default_channel_id)
    empty = (total <= 1e-9) & unlabeled
    if empty.any():
        weights[empty, default_idx] = 1.0
        total = weights.sum(axis=2)

    # Normalize unlabeled cells only (labeled cells are already sum=1.0)
    norm_denom = np.where(unlabeled, total, 1.0)
    weights[unlabeled] = (weights[unlabeled] / norm_denom[unlabeled, np.newaxis])

    # Fix 10.9 (REQ-P10-005): SDF road edge blending — LAST operation.
    # Requires road_sdf_dist channel from Phase 8 Fix 8.13.
    # Gracefully skips if channel absent (Phase 8 not yet run). (T-10-03-01)
    road_sdf_dist = stack.get("road_sdf_dist")
    if road_sdf_dist is not None:
        weights = apply_sdf_road_blend(weights, road_sdf_dist, rules)

    return weights.astype(np.float32)


# ---------------------------------------------------------------------------
# Pass wiring
# ---------------------------------------------------------------------------


def pass_materials(
    state: TerrainPipelineState,
    region: Optional[BBox],
    *,
    rules: Optional[MaterialRuleSet] = None,
) -> PassResult:
    """Bundle B materials pass.

    Contract
    --------
    Consumes: slope, height, curvature (optional), wetness (optional)
    Produces: splatmap_weights_layer, material_weights
    Respects protected zones: yes (region mask only)
    Requires scene read: no
    """
    from .terrain_pipeline import derive_pass_seed

    t0 = time.perf_counter()
    stack = state.mask_stack

    seed = derive_pass_seed(
        state.intent.seed,
        "materials_v2",
        state.tile_x,
        state.tile_y,
        region,
    )

    if rules is None:
        rules = default_dark_fantasy_rules()

    new_weights = compute_slope_material_weights(stack, rules)

    # Region scoping: preserve existing weights outside the region
    if region is not None:
        existing = stack.get("splatmap_weights_layer")
        r_slice, c_slice = region.to_cell_slice(
            world_origin_x=stack.world_origin_x,
            world_origin_y=stack.world_origin_y,
            cell_size=stack.cell_size,
            grid_shape=stack.height.shape,
        )
        if existing is not None and np.asarray(existing).shape == new_weights.shape:
            merged = np.asarray(existing, dtype=np.float32).copy()
            merged[r_slice, c_slice, :] = new_weights[r_slice, c_slice, :]
            new_weights = merged
        else:
            # No prior weights — zero outside region, new weights inside
            merged = np.zeros_like(new_weights)
            merged[r_slice, c_slice, :] = new_weights[r_slice, c_slice, :]
            # Leave outside cells as zero-sum (downstream code can treat
            # that as "not authored yet")
            new_weights = merged

    stack.set("splatmap_weights_layer", new_weights, "materials_v2")
    stack.set("material_weights", new_weights, "materials_v2")

    # Aggregate metrics
    per_layer_coverage = new_weights.mean(axis=(0, 1))
    dominant = int(per_layer_coverage.argmax())
    metrics = {
        "layer_count": int(new_weights.shape[2]),
        "layer_ids": [c.channel_id for c in rules.channels],
        "dominant_layer": rules.channels[dominant].channel_id,
        "dominant_coverage": float(per_layer_coverage[dominant]),
        "seed_used": seed,
    }
    for i, c in enumerate(rules.channels):
        metrics[f"coverage_{c.channel_id}"] = float(per_layer_coverage[i])

    return PassResult(
        pass_name="materials_v2",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("slope", "height"),
        produced_channels=("splatmap_weights_layer", "material_weights"),
        metrics=metrics,
    )


def register_bundle_b_material_passes() -> None:
    """Register the Bundle B materials pass on TerrainPassController."""
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="materials_v2",
            func=pass_materials,
            # Materials are derived from slope + altitude + curvature; wetness
            # is a soft input consumed via stack.get(...) when available.
            # NOTE: produces_channels overlaps with quixel_ingest — that
            # overlap is intentional (quixel_ingest overrides materials_v2
            # for photoscanned biomes, see terrain_quixel_ingest.py).
            requires_channels=("slope", "height", "curvature"),
            produces_channels=("splatmap_weights_layer", "material_weights"),
            seed_namespace="materials_v2",
            requires_scene_read=False,
            may_modify_geometry=False,
            description="Bundle B — slope/altitude/wetness-driven splatmap materials.",
        )
    )


__all__ = [
    "MaterialChannel",
    "MaterialRuleSet",
    "default_dark_fantasy_rules",
    "ROCK_NORMAL_THRESHOLD",
    "compute_normal_z",
    "apply_brucks_blend",
    "compute_snow_line_factor",
    "RAVINE_THRESHOLD",
    "sample_macro_color",
    "ROAD_EDGE_FADE_WIDTH",
    "apply_sdf_road_blend",
    "compute_slope_material_weights",
    "pass_materials",
    "register_bundle_b_material_passes",
]

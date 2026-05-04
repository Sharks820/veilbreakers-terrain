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
from collections.abc import Mapping
from dataclasses import dataclass, field
from numbers import Real
from typing import TYPE_CHECKING, Callable, Optional, Tuple, cast

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    ValidationIssue,
    TerrainMaskStack,
    TerrainPipelineState,
)

if TYPE_CHECKING:
    from .terrain_materials_ext import MaterialChannelExt


HintMap = Mapping[str, object]


def _coerce_float(raw: object, default: float) -> float:
    if isinstance(raw, (str, Real)):
        try:
            return float(raw)
        except ValueError:
            return default
    return default


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
    # Lava proximity envelope (0..1 scalar; 1.0 = active lava core)
    lava_prox_min: float = 0.0
    lava_prox_max: float = 1.0
    # Base multiplier — higher = channel "wins" in overlap regions
    base_weight: float = 1.0
    # Optional hard override order. Higher priority wins in cells where
    # multiple priority channels contribute non-zero weight.
    priority: int = 0


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

    def priority_order(self) -> Tuple[int, ...]:
        """Return channel indices sorted by priority desc, stable by declaration."""
        return tuple(
            idx for idx, _ch in sorted(
                enumerate(self.channels),
                key=lambda item: (-int(item[1].priority), item[0]),
            )
        )


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
            priority=5,
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


def caldera_volcanic_rules() -> MaterialRuleSet:
    """Return a 5-channel volcanic rule set with hard-stamped lava cells."""
    channels = (
        MaterialChannel(
            channel_id="ash_floor",
            base_color_hex="#2a2320",
            roughness=0.93,
            triplanar=False,
            slope_min_rad=0.0,
            slope_max_rad=math.radians(22.0),
            slope_falloff_rad=math.radians(6.0),
            altitude_max_m=80.0,
            altitude_falloff_m=15.0,
            base_weight=1.1,
        ),
        MaterialChannel(
            channel_id="basalt_rock",
            base_color_hex="#1c1a18",
            roughness=0.88,
            triplanar=False,
            slope_min_rad=0.0,
            slope_max_rad=math.radians(50.0),
            slope_falloff_rad=math.radians(8.0),
            base_weight=1.0,
        ),
        MaterialChannel(
            channel_id="scree_rubble",
            base_color_hex="#3d3428",
            roughness=0.96,
            triplanar=True,
            slope_min_rad=math.radians(30.0),
            slope_max_rad=math.pi / 2.0,
            slope_falloff_rad=math.radians(8.0),
            base_weight=0.9,
        ),
        MaterialChannel(
            channel_id="lava_hot",
            base_color_hex="#6e1500",
            roughness=0.72,
            triplanar=False,
            slope_min_rad=0.0,
            slope_max_rad=math.radians(20.0),
            slope_falloff_rad=math.radians(5.0),
            lava_prox_min=0.35,
            lava_prox_max=1.0,
            base_weight=2.5,
            priority=10,
        ),
        MaterialChannel(
            channel_id="rim_summit",
            base_color_hex="#141210",
            roughness=0.90,
            triplanar=False,
            slope_min_rad=0.0,
            slope_max_rad=math.radians(40.0),
            slope_falloff_rad=math.radians(8.0),
            altitude_min_m=300.0,
            altitude_falloff_m=25.0,
            base_weight=1.4,
        ),
    )
    return MaterialRuleSet(channels=channels, default_channel_id="basalt_rock")


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


def compute_normal_z(heightmap: np.ndarray, cell_size_m: float = 1.0) -> np.ndarray:
    """Return the z-component of the unit surface normal for every cell.

    Uses numpy gradient divided by world-space cell size.
    Result is in [0, 1]: 1.0 = perfectly flat, approaching 0 = vertical wall.

    Formula (from CONTEXT.md Fix 10.1):
        dy, dx = np.gradient(heightmap)
        dy /= cell_size_m
        dx /= cell_size_m
        denom  = np.sqrt(dx**2 + dy**2 + 1.0)
        normal_z = 1.0 / denom

    NaN/Inf in heightmap are replaced with 0 before gradient (T-10-02-01).
    """
    h = np.nan_to_num(np.asarray(heightmap, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    cell_size = max(float(cell_size_m), 1e-9)
    dy, dx = np.gradient(h)
    dy = dy / cell_size
    dx = dx / cell_size
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
    climate_params: Optional[HintMap] = None,
    normal_z: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Compute snow line coverage factor per cell (Fix 10.5 / REQ-P10-006).

    Returns float32 array in [0..1]. High values = snow-eligible altitude.

    When normal_z is supplied (recommended), uses it directly as the top-face
    weight — matching Horizon Zero Dawn / Ghost of Tsushima snow accumulation
    (snow collects on surfaces facing up, not just flat slopes).

    Formula:
        base       = sigmoid((height - snow_alt) / snow_width)
        slope_mod  = normal_z * 0.8 + 0.2           # if normal_z provided
                   = 1.0 - 0.3 * abs(sin(slope))    # legacy fallback
        return base * slope_mod

    Args:
        height:        float32 (H,W), normalized 0-1 height values.
        slope:         float32 (H,W), slope in radians.
        climate_params: dict with optional keys snow_altitude (default 0.7)
                        and snow_transition (default 0.1).
        normal_z:      float32 (H,W) in [0,1], Z component of surface normal.
                        1.0 = flat/top-facing, 0.0 = vertical. When provided,
                        replaces the abs(sin(slope)) approximation.

    Guards (T-10-02-02): snow_width clamped to [1e-6, inf] to avoid /0.
    Guards (T-10-02-04): snow_altitude clamped to [0,1]; snow_transition to [0.01, 0.5].
    """
    if climate_params is None:
        climate_params = {}

    snow_alt_raw = climate_params.get("snow_altitude", 0.7)
    snow_alt_value = _coerce_float(snow_alt_raw, 0.7)
    snow_alt = min(max(snow_alt_value, 0.0), 1.0)

    snow_width_raw = climate_params.get("snow_transition", 0.1)
    snow_width_value = _coerce_float(snow_width_raw, 0.1)
    snow_width = min(max(snow_width_value, 0.01), 0.5)
    h = np.asarray(height, dtype=np.float64)
    base = 1.0 / (1.0 + np.exp(-(h - snow_alt) / snow_width))
    if normal_z is not None:
        nz = np.clip(np.asarray(normal_z, dtype=np.float64), 0.0, 1.0)
        slope_mod = nz * 0.8 + 0.2  # 0.2 minimum so even vertical faces get trace snow
    else:
        s = np.asarray(slope, dtype=np.float64)
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
    # Vectorized: broadcast scale (H, W) over all non-road channels at once
    w[:, :, other_mask] = (other_w * scale[:, :, np.newaxis]).astype(np.float32)

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

    lava_prox = stack.get("lava_prox")
    if lava_prox is None:
        lava_prox = np.zeros_like(slope)
    else:
        lava_prox = np.asarray(lava_prox, dtype=np.float64)

    L = len(rules.channels)
    H, W = slope.shape
    weights = np.zeros((H, W, L), dtype=np.float32)

    # Fix 10.1 (REQ-P10-002): Compute surface normal z-component for rock masking.
    # normal_z < ROCK_NORMAL_THRESHOLD → rock face (replaces slope threshold).
    surface_normal_z = compute_normal_z(stack.height, cell_size_m=float(getattr(stack, "cell_size", 1.0)))

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
        lava_prox_w = _smoothstep_band(
            lava_prox, ch.lava_prox_min, ch.lava_prox_max, falloff=0.05
        )
        combined = ch.base_weight * slope_w * alt_w * curv_w * wet_w * lava_prox_w

        # Triplanar blend perturbation for steep-surface materials (Fix 7.16)
        if ch.triplanar:
            # Default sin-based noise_fn (Phase 11 will inject proper OpenSimplex2S)
            def _default_noise(uv: np.ndarray) -> np.ndarray:
                return np.sin(uv[:, 0] * 3.7 + uv[:, 1] * 2.1) * 0.5 + 0.5

            h_arr = np.asarray(stack.height, dtype=np.float64)
            H_s, W_s = h_arr.shape
            r_idx, c_idx = np.mgrid[0:H_s, 0:W_s]
            # E-5: use world-space XYZ so triplanar UVs tile uniformly across tiles
            _cs = float(stack.cell_size)
            world_x = c_idx.astype(np.float64) * _cs + float(stack.world_origin_x)
            world_z = r_idx.astype(np.float64) * _cs + float(stack.world_origin_y)
            pos_3d = np.stack([world_x, h_arr, world_z], axis=2)
            normals_3d = np.zeros((H_s, W_s, 3), dtype=np.float64)
            normals_3d[..., 2] = 1.0  # default up-normal

            # Tilt normals for steep cells using slope channel
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

    priority_indices = [idx for idx, ch in enumerate(rules.channels) if int(ch.priority) > 0]
    if priority_indices:
        claimed = np.zeros((H, W), dtype=bool)
        priority_weights = weights.copy()
        weights[:, :, :] = 0.0
        for idx in rules.priority_order():
            if idx not in priority_indices:
                continue
            mask = (priority_weights[:, :, idx] > 1e-9) & (~claimed)
            if mask.any():
                weights[mask, idx] = priority_weights[mask, idx]
                claimed |= mask
        if (~claimed).any():
            weights[~claimed, :] = priority_weights[~claimed, :]

    # Fix 10.6 (REQ-P10-003): Brucks height-blend at rock/dirt boundary.
    # Rock strata poke through dirt according to strata band height.
    try:
        cliff_idx = rules.index_of("cliff")
        ground_idx = rules.index_of("ground")
        scree_idx: int | None = None
        orig_cliff = weights[:, :, cliff_idx].copy()
        orig_scree: np.ndarray | None = None
        try:
            scree_idx = rules.index_of("scree")
            orig_scree = weights[:, :, scree_idx].copy()
            rock_boundary_weight = np.maximum(orig_cliff, orig_scree)
        except KeyError:
            rock_boundary_weight = orig_cliff
        strata_h = stack.get("strata_height")
        if strata_h is not None:
            rock_h_factor = np.asarray(strata_h, dtype=np.float32)
            blend_alpha = rock_boundary_weight.copy()
            b_rock, b_dirt = apply_brucks_blend(
                blend_alpha=blend_alpha,
                rock_height_factor=rock_h_factor,
            )
            total_bd = b_rock + b_dirt + 1e-8
            b_rock_norm = (b_rock / total_bd).astype(np.float32)
            weights[:, :, ground_idx] = (b_dirt / total_bd).astype(np.float32)
            if scree_idx is not None and orig_scree is not None:
                # FIX-7-14: distribute b_rock proportionally between cliff and scree
                sum_cliff_scree = orig_cliff + orig_scree + 1e-9
                weights[:, :, cliff_idx] = (b_rock_norm * (orig_cliff / sum_cliff_scree)).astype(np.float32)
                weights[:, :, scree_idx] = (b_rock_norm * (orig_scree / sum_cliff_scree)).astype(np.float32)
            else:
                weights[:, :, cliff_idx] = b_rock_norm
    except KeyError:
        pass  # rule set doesn't have cliff or ground channel; skip silently

    # Fix 10.3: Ridge → ravine material blend.
    # Negative ridge values = erosion channels. Apply darker/wetter drainage material.
    # Prefer the erosion-refined ridge field when available so ravines carved by
    # pass_erosion get their wet_rock uplift even when ``ridge`` still holds the
    # raw structural values from ``pass_structural_masks``.
    ridge = stack.get("ridge_eroded")
    if ridge is None:
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
    rock_label         = stack.get("rock_label")          # float32 mask [0..1]
    gravel_label       = stack.get("gravel_label")        # float32 mask [0..1]
    water_label        = stack.get("water_label")         # float32 mask [0..1]
    cliff_label        = stack.get("cliff_label")         # float32 mask [0..1]
    water_surface_mask = stack.get("water_surface_mask")  # float32 binary [0,1]
    wet_rock_splash    = stack.get("wet_rock")            # pass_waterfalls spray mask
    label_arrays: dict[str, object | None] = {
        "rock_label": rock_label,
        "gravel_label": gravel_label,
        "water_label": water_label,
        "cliff_label": cliff_label,
        "water_surface_mask": water_surface_mask,
        "wet_rock_splash": wet_rock_splash,
    }
    has_labels = any(lbl is not None for lbl in (
        rock_label,
        gravel_label,
        water_label,
        cliff_label,
        water_surface_mask,
        wet_rock_splash,
    ))

    if has_labels:
        # Map label channel → splatmap layer index.
        # Only assign if the target channel_id exists in the rule set.
        _label_channel_map = {
            "rock_label":         ("cliff",),     # rock structural label -> cliff material
            "gravel_label":       ("scree",),     # gravel structural label -> scree material
            "water_label":        ("wet_rock",),  # water structural label -> wet_rock material
            "cliff_label":        ("cliff",),     # cliff structural label -> cliff material
            "water_surface_mask": ("wet_rock",),  # binary water mask -> wet_rock material
            "wet_rock_splash":    ("wet_rock",),  # waterfall spray mask -> wet_rock material
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


_DEFAULT_HEIGHT_BLEND_GAMMAS = {
    "ground": 0.95,
    "cliff": 1.15,
    "scree": 0.85,
    "wet_rock": 0.70,
    "snow": 2.20,
}


def _float_hint(
    hints: HintMap,
    key: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = _coerce_float(hints.get(key, default), default)
    if minimum is not None:
        value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


def _optional_float_hint(hints: HintMap, key: str) -> float | None:
    raw = hints.get(key)
    if raw is None:
        return None
    return _coerce_float(raw, 0.0)


def _mapping_hint(hints: HintMap, key: str) -> dict[str, object]:
    raw = hints.get(key)
    if isinstance(raw, Mapping):
        typed_raw = cast("Mapping[object, object]", raw)
        return {str(k): v for k, v in typed_raw.items()}
    return {}


def _string_set_hint(hints: HintMap, key: str) -> set[str]:
    raw = hints.get(key)
    if isinstance(raw, (list, tuple, set)):
        typed_raw = cast("list[object] | tuple[object, ...] | set[object]", raw)
        return {str(item) for item in typed_raw}
    return set()


def _resolve_height_blend_gammas(
    rules: MaterialRuleSet,
    hints: HintMap,
) -> Tuple[float, ...]:
    overrides = _mapping_hint(hints, "material_height_blend_gamma")
    gammas: list[float] = []
    for ch in rules.channels:
        gamma = overrides.get(
            ch.channel_id,
            _DEFAULT_HEIGHT_BLEND_GAMMAS.get(ch.channel_id, 1.0),
        )
        gammas.append(max(_coerce_float(gamma, 1.0), 1e-6))
    return tuple(gammas)


def _apply_region_mask(
    base_weight_map: np.ndarray,
    weight_map: np.ndarray,
    region_mask: np.ndarray,
) -> np.ndarray:
    """Blend authored material weights through a region mask instead of multiplying.

    ``region_mask`` is [0, 1]: 0 keeps the base map, 1 takes the new map. This
    avoids zeroing or darkening weights at region boundaries.
    """
    base = np.asarray(base_weight_map, dtype=np.float32)
    authored = np.asarray(weight_map, dtype=np.float32)
    mask = np.asarray(region_mask, dtype=np.float32)
    if base.shape != authored.shape:
        raise ValueError("_apply_region_mask requires matching base and weight shapes")
    if mask.shape != base.shape[:2]:
        raise ValueError("_apply_region_mask mask shape must match weight map HxW")
    mask3 = np.clip(mask, 0.0, 1.0)[:, :, np.newaxis]
    return ((1.0 - mask3) * base + mask3 * authored).astype(np.float32)


def _build_material_channel_exts(
    rules: MaterialRuleSet,
    hints: HintMap,
) -> list["MaterialChannelExt"]:
    from .terrain_materials_ext import MaterialChannelExt

    gamma_map = dict(zip(
        (ch.channel_id for ch in rules.channels),
        _resolve_height_blend_gammas(rules, hints),
    ))
    density_overrides = _mapping_hint(hints, "material_texel_density_m")
    hero_ids = _string_set_hint(hints, "hero_material_ids")
    channels: list[MaterialChannelExt] = []
    for ch in rules.channels:
        default_density = 512.0 if ch.triplanar else 256.0
        if ch.channel_id in hero_ids:
            default_density = max(default_density, 1024.0)
        density_raw = density_overrides.get(ch.channel_id, default_density)
        texel_density = _coerce_float(density_raw, default_density)
        channels.append(
            MaterialChannelExt(
                base=ch,
                height_blend_gamma=gamma_map[ch.channel_id],
                texel_density_m=texel_density,
                roughness=ch.roughness,
                metallic=ch.metallic,
                triplanar=ch.triplanar,
            )
        )
    return channels


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

    hints: HintMap = state.intent.composition_hints or {}

    new_weights = compute_slope_material_weights(stack, rules)
    issues: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    from .terrain_materials_ext import (
        compute_height_blended_weights,
        validate_cliff_silhouette_area,
        validate_texel_density_coherency,
    )

    material_exts = _build_material_channel_exts(rules, hints)
    height_blend_gammas = tuple(ch.height_blend_gamma for ch in material_exts)
    if any(abs(gamma - 1.0) > 1e-6 for gamma in height_blend_gammas):
        new_weights = compute_height_blended_weights(new_weights, stack.height, height_blend_gammas)

    texel_issues = validate_texel_density_coherency(
        material_exts,
        max_ratio=_float_hint(hints, "material_texel_density_max_ratio", 2.0),
    )
    for issue in texel_issues:
        (issues if issue.is_hard() else warnings).append(issue)

    hero_cliff_coverage = _optional_float_hint(hints, "hero_cliff_pixel_coverage_fraction")
    if hero_cliff_coverage is not None:
        for issue in validate_cliff_silhouette_area(hero_cliff_coverage, tier="hero"):
            (issues if issue.is_hard() else warnings).append(issue)
    secondary_cliff_coverage = _optional_float_hint(hints, "secondary_cliff_pixel_coverage_fraction")
    if secondary_cliff_coverage is not None:
        for issue in validate_cliff_silhouette_area(secondary_cliff_coverage, tier="secondary"):
            (issues if issue.is_hard() else warnings).append(issue)

    # Region scoping: blend via a region mask so boundaries preserve base weights
    if region is not None:
        existing = stack.get("splatmap_weights_layer")
        r_slice, c_slice = region.to_cell_slice(
            world_origin_x=stack.world_origin_x,
            world_origin_y=stack.world_origin_y,
            cell_size=stack.cell_size,
            grid_shape=stack.height.shape,
        )
        region_mask = np.zeros(new_weights.shape[:2], dtype=np.float32)
        region_mask[r_slice, c_slice] = 1.0
        if existing is not None and np.asarray(existing).shape == new_weights.shape:
            new_weights = _apply_region_mask(existing, new_weights, region_mask)
        else:
            # No prior weights — zero outside region, new weights inside
            merged = _apply_region_mask(np.zeros_like(new_weights), new_weights, region_mask)
            # Leave outside cells as zero-sum (downstream code can treat
            # that as "not authored yet")
            new_weights = merged

    stack.set("splatmap_weights_layer", new_weights, "materials_v2")
    stack.set("material_weights", new_weights, "materials_v2")

    # E-2: ambient_occlusion_bake from curvature concavity proxy
    _curvature = stack.get("curvature")
    if _curvature is not None:
        _ao = np.clip(0.5 + 0.5 * np.tanh(np.asarray(_curvature, dtype=np.float32) * 2.0), 0.0, 1.0)
        stack.set("ambient_occlusion_bake", _ao.astype(np.float32), "materials_v2")

    # E-3: terrain_displacement from blended per-layer displacement amplitudes
    _disp = np.zeros(new_weights.shape[:2], dtype=np.float32)
    for _i, _ch in enumerate(rules.channels):
        _base_disp = float(getattr(_ch, "displacement_amplitude_m", 0.05))
        _disp += new_weights[..., _i].astype(np.float32) * _base_disp
    stack.set("terrain_displacement", _disp, "materials_v2")

    # E-1: build TerrainTextureLayerStack for downstream Unity export and quixel_ingest
    from .terrain_texture_layer_stack import TerrainTextureLayerStack, TextureLayer
    _layer_stack = TerrainTextureLayerStack()
    for _i, _ch in enumerate(rules.channels):
        _layer_stack.add_layer(TextureLayer(
            layer_id=_ch.channel_id,
            terrain_mask_source="splatmap_weights_layer",
            weight_map=new_weights[..., _i].astype(np.float32),
            metallic=float(_ch.metallic),
            tiling_scale=float(getattr(_ch, "tiling_scale", 1.0)),
            texel_density_m=float(getattr(_ch, "texel_density_m", 0.1)),
            color_space="sRGB",
        ))
    state.texture_layer_stack = _layer_stack

    # Aggregate metrics
    per_layer_coverage = new_weights.mean(axis=(0, 1))
    dominant = int(per_layer_coverage.argmax())
    metrics: dict[str, object] = {
        "layer_count": int(new_weights.shape[2]),
        "layer_ids": [c.channel_id for c in rules.channels],
        "dominant_layer": rules.channels[dominant].channel_id,
        "dominant_coverage": float(per_layer_coverage[dominant]),
        "seed_used": seed,
    }
    for i, c in enumerate(rules.channels):
        metrics[f"coverage_{c.channel_id}"] = float(per_layer_coverage[i])
    metrics["height_blend_enabled"] = True
    metrics["height_blend_gammas"] = {
        c.channel_id: float(g)
        for c, g in zip(rules.channels, height_blend_gammas)
    }
    metrics["texel_density_issue_count"] = len(texel_issues)
    metrics["material_warning_count"] = len(warnings)

    status = "ok"
    if issues:
        status = "failed"
    elif warnings:
        status = "warning"

    return PassResult(
        pass_name="materials_v2",
        status=status,
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("slope", "height"),
        produced_channels=("splatmap_weights_layer", "material_weights", "ambient_occlusion_bake", "terrain_displacement"),
        metrics=metrics,
        issues=issues,
        warnings=warnings,
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
            requires_channels=("slope", "height"),
            optional_channels=("curvature", "wetness"),
            produces_channels=("splatmap_weights_layer", "material_weights", "ambient_occlusion_bake", "terrain_displacement"),
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
    "caldera_volcanic_rules",
    "ROCK_NORMAL_THRESHOLD",
    "compute_normal_z",
    "apply_brucks_blend",
    "compute_snow_line_factor",
    "RAVINE_THRESHOLD",
    "sample_macro_color",
    "ROAD_EDGE_FADE_WIDTH",
    "apply_sdf_road_blend",
    "compute_slope_material_weights",
    "_apply_region_mask",
    "pass_materials",
    "register_bundle_b_material_passes",
]

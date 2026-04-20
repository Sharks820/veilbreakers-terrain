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
    SUB_CANOPY = "sub_canopy"    # renamed from understory for clarity; alias kept
    UNDERSTORY = "sub_canopy"    # backward-compat alias
    SHRUB = "shrub"
    GROUND_COVER = "ground_cover"


@dataclass
class VegetationLayers:
    """Four-layer vertical profile density arrays, all (H, W) float32 in [0, 1].

    Vertical profile (top → ground):
        canopy       — main closed-canopy stratum (15–30 m)
        sub_canopy   — shade-tolerant trees and tall shrubs (5–15 m)
        shrub        — woody shrubs and saplings (0.5–5 m)
        ground_cover — herbs, ferns, mosses (<0.5 m)

    ``sub_canopy`` is the canonical internal name; ``understory`` remains a
    backward-compatibility alias for callers and persisted detail-density maps.
    """

    canopy_density: np.ndarray
    sub_canopy_density: np.ndarray
    shrub_density: np.ndarray
    ground_cover_density: np.ndarray

    # Backward-compat property so code accessing .understory_density still works.
    @property
    def understory_density(self) -> np.ndarray:
        return self.sub_canopy_density

    def as_dict(self) -> Dict[str, np.ndarray]:
        return {
            "canopy": self.canopy_density,
            "understory": self.sub_canopy_density,  # alias for legacy consumers
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
    """Min-max normalize to [0, 1] as float32.

    Standard [0, 1] min-max normalization with epsilon guard so the
    denominator never collapses to zero on a flat array.  Uses a
    per-array epsilon (1e-7 * |mean| or absolute 1e-7, whichever is
    larger) so near-zero constant arrays don't get exaggerated noise.
    """
    arr = np.asarray(arr, dtype=np.float32)
    lo = float(arr.min())
    hi = float(arr.max())
    rng = hi - lo
    eps = max(1e-7, 1e-7 * abs(float(arr.mean())))
    if rng < eps:
        # Flat array — return zeros (no information to preserve).
        return np.zeros_like(arr)
    return ((arr - lo) / rng).astype(np.float32)


# ---------------------------------------------------------------------------
# 4-layer vegetation (AAA vertical profile)
# ---------------------------------------------------------------------------


def compute_vegetation_layers(
    stack: TerrainMaskStack,
    biome: str = "dark_fantasy_default",
) -> VegetationLayers:
    """Stratify vegetation into a four-layer vertical profile driven by terrain signals.

    Vertical profile (canopy → ground)
    -----------------------------------
    canopy      — main closed-canopy stratum.  Low slope + mid altitude +
                  wind shelter.  Tall trees shun exposed ridges.

    sub_canopy  — shade-tolerant trees and tall shrubs (formerly "understory").
                  Light availability is computed via Beer-Lambert attenuation
                  through the canopy layer: T = exp(-k_sc * canopy_raw * canopy_radius_scale).
                  This means dense canopy strongly suppresses sub-canopy, matching
                  real forest ecology (shade-intolerant species cannot establish
                  under a closed canopy crown).

    shrub       — woody shrubs and saplings in the transitional zone between
                  canopy and open rock/cliff.  Peaks at moderate slopes where
                  full-canopy trees cannot establish.  Further suppressed by
                  sub_canopy via Beer-Lambert: T_shrub = exp(-k_s * sub_canopy_raw).

    ground_cover — herbs, ferns, mosses.  Light reaching the ground floor is
                   attenuated through both canopy and sub_canopy layers.
                   T_gc = exp(-k_gc * (canopy_raw + 0.4 * sub_canopy_raw)).
                   Wetness boosts hygrophilous species independently of light.

    Species-specific canopy radius
    ------------------------------
    The Beer-Lambert extinction coefficient k is modulated by ``canopy_radius_scale``
    derived from the stack channel ``canopy_species_radius_m`` (if present):
        - Small-crowned species (radius < 4 m) transmit more light: k scales down
        - Large-crowned species (radius > 8 m) create deep shade: k scales up
    When the channel is absent, a neutral radius of 6 m is assumed (k = 1.0).

    Biome multipliers
    -----------------
    Each biome returns a 4-tuple (c_scale, sc_scale, s_scale, g_scale) that
    scales the corresponding layer density.  Multipliers > 1.0 boost,
    < 1.0 suppress.  Missing biomes fall back to all-1.0.

    Absent channels
    ---------------
    If optional channels (slope, wetness, wind_field) are absent they default
    to zeros — stratification still produces valid (if bland) densities.
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

    # Biome scalar tweaks: (canopy, sub_canopy, shrub, ground_cover)
    biome_scale: Dict[str, Tuple[float, float, float, float]] = {
        "dark_fantasy_default": (1.0,  1.0,  1.0,  1.0),
        "tundra":               (0.3,  0.4,  0.6,  0.9),
        "swamp":                (0.8,  1.1,  1.0,  1.2),
        "desert":               (0.1,  0.2,  0.3,  0.4),
        "temperate_forest":     (1.0,  1.0,  0.8,  1.0),
        "boreal":               (0.9,  0.7,  0.6,  1.0),
    }
    cs, scs, ss, gs = biome_scale.get(biome, (1.0, 1.0, 1.0, 1.0))

    # ---- Species-specific canopy radius → Beer-Lambert extinction coefficients ---
    # Default neutral radius 6 m.  Species with larger crowns create deeper shade.
    # k = 1.0 at 6 m, scales by (radius / 6) so a 12 m crown doubles extinction.
    _NEUTRAL_RADIUS_M = 6.0
    canopy_radius_raw = stack.get("canopy_species_radius_m")
    if canopy_radius_raw is not None:
        radius_arr = np.asarray(canopy_radius_raw, dtype=np.float32)
        if radius_arr.shape == shape:
            # Clamp to [1.0, 20.0] to avoid degenerate coefficients.
            radius_arr = np.clip(radius_arr, 1.0, 20.0)
            canopy_radius_scale = (radius_arr / _NEUTRAL_RADIUS_M).astype(np.float32)
        else:
            canopy_radius_scale = np.ones(shape, dtype=np.float32)
    else:
        canopy_radius_scale = np.ones(shape, dtype=np.float32)

    # ---- Canopy: low slope, mid altitude, wind shelter ---------------------
    # Peak around alt_n = 0.4 (mid-slope foothills).  Wind exposure suppresses
    # by up to 60 % at maximum wind speed.
    canopy_raw = (
        (1.0 - slope_n)
        * (1.0 - np.abs(alt_n - 0.4) * 1.2).clip(0.0, 1.0)
        * (1.0 - wind_n * 0.6)
    ).clip(0.0, 1.0)
    canopy = (canopy_raw * cs).clip(0.0, 1.0).astype(np.float32)

    # ---- Sub-canopy: Beer-Lambert light transmission through canopy ----------
    # Light reaching sub-canopy: T_sc = exp(-k_sc * canopy_raw * canopy_radius_scale)
    # k_sc = 1.5 → under a full closed canopy (canopy_raw=1.0) transmission ≈ 22 %
    # Large-crowned species shade more strongly; small crowns let more light through.
    # Wetness and lower altitude boost sub-canopy independently (shade-tolerant
    # species are often hydrophilous and prefer valley micro-climates).
    _k_sc = 1.5
    canopy_transmission_sc = np.exp(
        -_k_sc * canopy_raw * canopy_radius_scale
    ).astype(np.float32)
    sub_canopy_raw = (
        canopy_transmission_sc * 0.8   # primary: light availability
        + wet_n * 0.35                  # secondary: moisture
        + (1.0 - alt_n) * 0.15         # tertiary: low-altitude preference
    ).clip(0.0, 1.0)
    sub_canopy = (sub_canopy_raw * scs).clip(0.0, 1.0).astype(np.float32)

    # ---- Shrubs: moderate slopes, transitional zone -------------------------
    # Centred on slope_n ≈ 0.35 with a width of ~0.625 normalised units.
    # Light reaching shrub layer is attenuated by sub_canopy (k_s = 0.9).
    _k_s = 0.9
    sub_canopy_transmission_s = np.exp(-_k_s * sub_canopy_raw).astype(np.float32)
    shrub = (
        (1.0 - np.abs(slope_n - 0.35) * 1.6).clip(0.0, 1.0)
        * (1.0 - canopy_raw * 0.5)
        * (sub_canopy_transmission_s * 0.6 + 0.4)  # 40% floor: shrubs on edges
    ).clip(0.0, 1.0)
    shrub = (shrub * ss).clip(0.0, 1.0).astype(np.float32)

    # ---- Ground cover: full Beer-Lambert through canopy + sub_canopy ----------
    # T_gc = exp(-k_gc * (canopy_raw * canopy_radius_scale + 0.4 * sub_canopy_raw))
    # k_gc = 1.2.  Under a full closed canopy: transmission ≈ 30 %.
    # Wetness adds independently (hygrophilous herbs thrive regardless of light).
    _k_gc = 1.2
    ground_transmission = np.exp(
        -_k_gc * (canopy_raw * canopy_radius_scale + 0.4 * sub_canopy_raw)
    ).astype(np.float32)
    ground_cover = (
        ground_transmission * 0.7
        + wet_n * 0.4
    ).clip(0.0, 1.0)
    ground_cover = (ground_cover * gs).clip(0.0, 1.0).astype(np.float32)

    return VegetationLayers(
        canopy_density=canopy,
        sub_canopy_density=sub_canopy,
        shrub_density=shrub,
        ground_cover_density=ground_cover,
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
    """Identify disturbance patches using terrain signals AND temporal/proxy change detection.

    Detection signals (AAA multi-source approach)
    ---------------------------------------------
    (a) Slope-driven disturbance — high gradient indicates mass-wasting, landslide
        scars, or storm-felling corridors.

    (b) Erosion channel — explicit erosion_amount field flags flood channels and
        wash-out zones.

    (c) Geology / hardness — soft rock (hardness < 0.25) paired with moderate slope
        indicates prone-to-slumping substrate.

    (d) Temporal / proxy change detection — AAA games need disturbance to look
        *caused*, not random.  Four proxy-change signals detect where the land
        surface has evidently changed relative to a stable reference:

        (d1) Height-delta proxy: ``height_delta`` channel on stack (e.g. DoD —
             Digital elevation model of Difference from two surveys).  Cells
             where |delta| > 0.5 m are flagged as actively changed.  When the
             channel is absent, a synthetic delta is derived from the Laplacian
             of the current height field: high Laplacian magnitude (pits and
             peaks relative to neighbours) indicates terrain that is geomorpho-
             logically fresh rather than equilibrium-smoothed.

        (d2) NDVI-proxy drop: ``vegetation_index`` channel (e.g. NDVI raster).
             Cells with vegetation_index < 0.15 inside otherwise vegetated zones
             (where the neighbourhood mean is > 0.35) indicate canopy removal —
             exactly the signal of fire scars, clear-cuts, and windthrow gaps.
             When absent, low-canopy cells surrounded by high-canopy cells from
             the detail_density map are used as a proxy.

        (d3) Surface-roughness anomaly: local variance of the height field
             (3×3 neighbourhood std dev).  Freshly disturbed terrain is rougher
             than stable equilibrium surfaces.  Cells where roughness z-score
             > 1.5 are added to the disturbed mask.

        (d4) Flow-accumulation / convergence index: cells at topographic
             convergence points (flow accumulation channel or computed from
             height curvature) that also show erosion flags indicate active
             flood-regime disturbance.

    (e) Authored intent patches — manual DisturbancePatch entries override
        everything and force cells to disturbed.

    Kind assignment per patch
    -------------------------
    After labelling connected components, each patch is classified by majority
    signal:
      - Temporal delta (d1/d2) dominant + low elevation  → "flood"
      - NDVI drop dominant                               → "fire"
      - Slope + soft substrate                           → "windthrow"
      - Roughness anomaly + high slope                   → "windthrow"
      - Default round-robin across ``kinds``

    Age and recovery
    ----------------
    When a ``height_delta`` channel is present, age is estimated from the delta
    magnitude (larger deltas = more recent, less recovered).  Otherwise age is
    drawn from U[0.5, 40] years.  Recovery progress = saturate(age / 40).
    """
    height = np.asarray(stack.height, dtype=np.float32)
    rows, cols = height.shape
    disturbed = np.zeros((rows, cols), dtype=bool)

    # Confidence maps: accumulated score per cell for kind classification.
    # Higher score in a channel → that kind is more likely for this patch.
    _score_flood = np.zeros((rows, cols), dtype=np.float32)
    _score_fire = np.zeros((rows, cols), dtype=np.float32)
    _score_windthrow = np.zeros((rows, cols), dtype=np.float32)

    # -------------------------------------------------------------------------
    # (a) Slope-driven disturbance
    # -------------------------------------------------------------------------
    slope_raw = stack.get("slope")
    if slope_raw is not None:
        slope_arr = np.asarray(slope_raw, dtype=np.float32)
    else:
        dy = np.gradient(height, stack.cell_size, axis=0)
        dx = np.gradient(height, stack.cell_size, axis=1)
        slope_arr = np.sqrt(dx ** 2 + dy ** 2).astype(np.float32)

    steep = slope_arr > disturbance_slope_threshold
    disturbed |= steep
    _score_windthrow += steep.astype(np.float32) * 0.4

    # -------------------------------------------------------------------------
    # (b) Erosion-driven disturbance
    # -------------------------------------------------------------------------
    erosion_arr: Optional[np.ndarray] = None
    erosion_raw = stack.get("erosion_amount")
    if erosion_raw is not None:
        erosion_arr = np.asarray(erosion_raw, dtype=np.float32)
        eroded = erosion_arr > disturbance_erosion_threshold
        disturbed |= eroded
        _score_flood += eroded.astype(np.float32) * 0.5

    # -------------------------------------------------------------------------
    # (c) Geology / hardness
    # -------------------------------------------------------------------------
    hardness_arr: Optional[np.ndarray] = None
    geology_raw = stack.get("hardness") or stack.get("geology")
    if geology_raw is not None:
        hardness_arr = np.asarray(geology_raw, dtype=np.float32)
        soft_rock = hardness_arr < 0.25
        soft_steep = soft_rock & (slope_arr > disturbance_slope_threshold * 0.5)
        disturbed |= soft_steep
        _score_windthrow += soft_steep.astype(np.float32) * 0.3

    # -------------------------------------------------------------------------
    # (d1) Temporal proxy — height delta (DoD or Laplacian-of-height surrogate)
    # -------------------------------------------------------------------------
    height_delta_arr: Optional[np.ndarray] = None
    hdelta_raw = stack.get("height_delta")
    if hdelta_raw is not None:
        height_delta_arr = np.abs(np.asarray(hdelta_raw, dtype=np.float32))
    else:
        # Synthetic delta: magnitude of the discrete Laplacian (second derivative
        # of height).  High Laplacian = geomorphologically fresh pits/peaks.
        # Use a 3×3 stencil: Laplacian ≈ sum of 4-neighbours - 4*centre.
        lap = np.zeros_like(height)
        lap[1:-1, 1:-1] = (
            height[1:-1, 2:] + height[1:-1, :-2]
            + height[2:, 1:-1] + height[:-2, 1:-1]
            - 4.0 * height[1:-1, 1:-1]
        )
        height_delta_arr = np.abs(lap).astype(np.float32)

    # Threshold: cells where delta > mean + 1.5*std are "recently changed".
    hd_mean = float(height_delta_arr.mean())
    hd_std = float(height_delta_arr.std()) if float(height_delta_arr.std()) > 1e-9 else 1.0
    temporal_changed = height_delta_arr > (hd_mean + 1.5 * hd_std)
    disturbed |= temporal_changed
    # Temporal change near valleys/low areas → flood; elsewhere neutral.
    alt_n_local = _normalize(height)
    _score_flood += (temporal_changed & (alt_n_local < 0.4)).astype(np.float32) * 0.4
    _score_windthrow += (temporal_changed & (alt_n_local >= 0.4)).astype(np.float32) * 0.2

    # -------------------------------------------------------------------------
    # (d2) NDVI-proxy drop — vegetation index channel or canopy-density proxy
    # -------------------------------------------------------------------------
    veg_index_raw = stack.get("vegetation_index") or stack.get("ndvi")
    ndvi_drop_mask = np.zeros((rows, cols), dtype=bool)
    if veg_index_raw is not None:
        veg_idx = np.asarray(veg_index_raw, dtype=np.float32)
        # Neighbourhood mean using a 5×5 box filter (or fallback)
        if _SCIPY_OK:
            nbhd_mean = _ndimage.uniform_filter(veg_idx, size=5)
        else:
            # Simple shift-average fallback
            nbhd_mean = (
                np.roll(veg_idx, 2, axis=0) + np.roll(veg_idx, -2, axis=0)
                + np.roll(veg_idx, 2, axis=1) + np.roll(veg_idx, -2, axis=1)
                + veg_idx
            ) / 5.0
        # NDVI drop: locally low index surrounded by high-index neighbours
        ndvi_drop_mask = (veg_idx < 0.15) & (nbhd_mean > 0.35)
        disturbed |= ndvi_drop_mask
        _score_fire += ndvi_drop_mask.astype(np.float32) * 0.6

    # -------------------------------------------------------------------------
    # (d3) Surface-roughness anomaly — local height std dev
    # -------------------------------------------------------------------------
    if _SCIPY_OK:
        h_sq_mean = _ndimage.uniform_filter(height ** 2, size=3)
        h_mean_sq = _ndimage.uniform_filter(height, size=3) ** 2
        roughness = np.sqrt(np.maximum(0.0, h_sq_mean - h_mean_sq)).astype(np.float32)
    else:
        # Variance via shift arithmetic (cheap 3×3 approximation)
        h_s = height
        nbhd = (
            np.roll(h_s, 1, 0) + np.roll(h_s, -1, 0)
            + np.roll(h_s, 1, 1) + np.roll(h_s, -1, 1)
        ) / 4.0
        roughness = np.abs(h_s - nbhd).astype(np.float32)

    r_mean = float(roughness.mean())
    r_std = float(roughness.std()) if float(roughness.std()) > 1e-9 else 1.0
    rough_anomaly = roughness > (r_mean + 1.5 * r_std)
    # Only count roughness anomaly as disturbance when also steep (avoids
    # flagging flat boulder fields that are ecologically stable).
    rough_disturbed = rough_anomaly & steep
    disturbed |= rough_disturbed
    _score_windthrow += rough_disturbed.astype(np.float32) * 0.25

    # -------------------------------------------------------------------------
    # (d4) Flow convergence — flow_accumulation channel or curvature proxy
    # -------------------------------------------------------------------------
    flow_raw = stack.get("flow_accumulation")
    if flow_raw is not None:
        flow_arr = np.asarray(flow_raw, dtype=np.float32)
        f_mean = float(flow_arr.mean())
        f_std = float(flow_arr.std()) if float(flow_arr.std()) > 1e-9 else 1.0
        high_flow = flow_arr > (f_mean + 2.0 * f_std)
        convergence_disturbed = high_flow & (
            erosion_arr is not None
            and erosion_arr > disturbance_erosion_threshold * 0.5
            if erosion_arr is not None
            else high_flow
        )
        disturbed |= convergence_disturbed
        _score_flood += convergence_disturbed.astype(np.float32) * 0.5

    # -------------------------------------------------------------------------
    # (e) Authored intent patches
    # -------------------------------------------------------------------------
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

    # -------------------------------------------------------------------------
    # Label connected components (4-connected)
    # -------------------------------------------------------------------------
    if _SCIPY_OK:
        labelled, num_labels = _ndimage.label(disturbed)
    else:
        labelled = np.zeros((rows, cols), dtype=np.int32)
        _label_id = 0
        for r in range(rows):
            for c in range(cols):
                if not disturbed[r, c]:
                    continue
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
    allowed_kinds = tuple(k for k in kinds if k in ("fire", "windthrow", "flood"))
    if not allowed_kinds:
        allowed_kinds = ("fire", "windthrow", "flood")

    max_component_cells = max(min_patch_area * 4, (rows * cols) // 10)

    for label_idx in range(1, num_labels + 1):
        comp = labelled == label_idx
        area_cells = int(comp.sum())
        if area_cells < min_patch_area:
            continue

        comp_rs, comp_cs = np.where(comp)

        if area_cells <= max_component_cells:
            candidate_groups = [(comp_rs, comp_cs)]
        else:
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
                sub_rs_g = np.arange(r0, r1 + 1)
                sub_cs_g = np.arange(c0, c1 + 1)
                sgr, sgc = np.meshgrid(sub_rs_g, sub_cs_g, indexing="ij")
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

            # --- Multi-signal kind classification ---
            # Sum the per-kind confidence scores across the patch cells.
            fire_score = float(_score_fire[sub_rs, sub_cs].mean())
            flood_score = float(_score_flood[sub_rs, sub_cs].mean())
            wind_score = float(_score_windthrow[sub_rs, sub_cs].mean())

            # Also apply legacy per-patch signal checks for robustness.
            patch_slope_mean = float(slope_arr[sub_rs, sub_cs].mean())
            erosion_mean = (
                float(erosion_arr[sub_rs, sub_cs].mean())
                if erosion_arr is not None else 0.0
            )
            hardness_mean = (
                float(hardness_arr[sub_rs, sub_cs].mean())
                if hardness_arr is not None else 0.5
            )
            if erosion_mean > disturbance_erosion_threshold * 1.2:
                flood_score += 0.5
            if patch_slope_mean > disturbance_slope_threshold * 0.8 and hardness_mean < 0.35:
                wind_score += 0.4

            best_score = max(fire_score, flood_score, wind_score)
            if best_score < 0.05:
                kind = str(allowed_kinds[len(patches) % len(allowed_kinds)])
            elif fire_score >= flood_score and fire_score >= wind_score:
                kind = "fire"
            elif flood_score >= wind_score:
                kind = "flood"
            else:
                kind = "windthrow"
            if kind not in allowed_kinds:
                kind = str(allowed_kinds[0])

            # Age estimation: when height_delta channel present, larger delta
            # implies more recent disturbance (less time for recovery).
            if hdelta_raw is not None:
                delta_mean = float(np.abs(np.asarray(hdelta_raw, dtype=np.float32))[sub_rs, sub_cs].mean())
                # Map delta magnitude to age: 0 delta → old (40 yrs), large → recent (0.5 yrs).
                delta_norm = min(1.0, delta_mean / max(hd_mean + 3 * hd_std, 1e-6))
                age = float(0.5 + (1.0 - delta_norm) * 39.5)
            else:
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
    """Place clearings via Bridson Poisson-disk sampling within viable mask.

    Algorithm (SpeedTree/Houdini scatter quality)
    ---------------------------------------------
    1. Score cells: ``clearing_score = (1 - norm_slope) * (1 - cliff_proximity)``.
    2. Build a viable boolean mask from the score map (score > 0).
    3. **Bridson's algorithm** (k=30 retries per active sample):
       - Seed one random viable cell.
       - Active list: while non-empty, pick a random active cell, emit up to k
         candidate points uniformly in the annulus [r, 2r] around it.
       - Accept a candidate only if it is (a) inside the viable mask and
         (b) farther than ``min_separation_cells`` from every accepted centre.
       - Per-clearing radius drawn from U[min_radius, max_radius] — the minimum
         separation is set to ``min_radius * 2`` so clearings never overlap.
    4. Carve a soft-edged circle (1 - (d/r)^2) into each ``detail_density``
       layer for each accepted clearing.

    Returns at most ``target`` Clearing objects; may return fewer when the
    viable area is small.
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
        h = np.asarray(stack.height, dtype=np.float32)
        dy = np.gradient(h, stack.cell_size, axis=0)
        dx = np.gradient(h, stack.cell_size, axis=1)
        slope_arr = np.sqrt(dx ** 2 + dy ** 2).astype(np.float32)

    slope_ok = (slope_arr <= clearing_max_slope).astype(np.float32)

    cliff = stack.get("cliff_mask")
    if cliff is not None:
        cliff_arr = np.asarray(cliff, dtype=np.float32)
    else:
        cliff_arr = (slope_arr > 0.6).astype(np.float32)

    if _SCIPY_OK:
        cliff_bool = cliff_arr > 0.5
        if np.any(cliff_bool):
            dist_from_cliff = _ndimage.distance_transform_edt(~cliff_bool).astype(np.float32)
        else:
            dist_from_cliff = np.ones((rows, cols), dtype=np.float32) * max(rows, cols)
    else:
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

    cliff_proximity = 1.0 - _normalize(dist_from_cliff)
    score = slope_ok * (1.0 - cliff_proximity)

    # Viable mask: only cells with positive score may host a clearing centre.
    viable = score > 0.0
    viable_flat = viable.ravel()
    viable_indices = np.where(viable_flat)[0]
    if viable_indices.size == 0:
        # Fallback to fully open grid when no viable cells exist.
        viable_indices = np.arange(rows * cols)

    min_radius = float(max(stack.cell_size * clearing_radius_cells * 0.5, 5.0))
    max_radius = float(max(min_radius * 2.0, 15.0))

    # Poisson-disk minimum separation in cells (ensure radii never overlap).
    r_min_cells = min_separation_cells  # also = 2 * (min_radius / cell_size) at defaults

    # --- Bridson's algorithm (k=30) ---
    # Grid cell size for the background grid = r / sqrt(2) so each grid cell
    # contains at most one sample.
    grid_cell = r_min_cells / np.sqrt(2.0)
    grid_rows = max(1, int(np.ceil(rows / grid_cell)))
    grid_cols = max(1, int(np.ceil(cols / grid_cell)))

    background: Dict[Tuple[int, int], Tuple[float, float]] = {}  # grid_ij -> (r, c)

    def _grid_key(pr: float, pc: float) -> Tuple[int, int]:
        return int(pr / grid_cell), int(pc / grid_cell)

    def _is_valid(pr: float, pc: float) -> bool:
        """Check Poisson-disk distance constraint via background grid."""
        gi, gj = _grid_key(pr, pc)
        for di in range(-2, 3):
            for dj in range(-2, 3):
                nb = background.get((gi + di, gj + dj))
                if nb is not None and np.hypot(pr - nb[0], pc - nb[1]) < r_min_cells:
                    return False
        return True

    clearings: List[Clearing] = []
    active: List[Tuple[float, float]] = []

    # Seed with one random viable cell.
    seed_flat = viable_indices[int(rng.integers(0, viable_indices.size))]
    seed_r = float(seed_flat // cols)
    seed_c = float(seed_flat % cols)
    active.append((seed_r, seed_c))
    background[_grid_key(seed_r, seed_c)] = (seed_r, seed_c)

    k = 30  # Bridson retry count
    while active and len(clearings) < target:
        # Pick a random active sample.
        active_idx = int(rng.integers(0, len(active)))
        ar, ac = active[active_idx]
        found_child = False

        for _ in range(k):
            # Sample uniformly in annulus [r_min_cells, 2*r_min_cells].
            angle = float(rng.uniform(0.0, 2.0 * np.pi))
            dist = float(rng.uniform(r_min_cells, 2.0 * r_min_cells))
            nr = ar + dist * np.sin(angle)
            nc = ac + dist * np.cos(angle)

            # Bounds check.
            if not (0 <= nr < rows and 0 <= nc < cols):
                continue
            # Viable mask check.
            if not viable[int(nr), int(nc)]:
                continue
            # Poisson-disk distance check.
            if not _is_valid(nr, nc):
                continue

            # Accept this candidate.
            background[_grid_key(nr, nc)] = (nr, nc)
            active.append((nr, nc))
            found_child = True

            ir, ic = int(nr), int(nc)
            cx = float(stack.world_origin_x + (ic + 0.5) * stack.cell_size)
            cy = float(stack.world_origin_y + (ir + 0.5) * stack.cell_size)
            radius = float(rng.uniform(min_radius, max_radius))
            kind = "natural" if (len(clearings) % 2 == 0) else "human"
            clearings.append(Clearing(center=(cx, cy), radius_m=radius, kind=kind))

            # Carve soft-edged circle into detail_density layers.
            if detail_density is not None:
                radius_cells = radius / stack.cell_size
                r0 = max(0, int(nr - radius_cells) - 1)
                r1 = min(rows, int(nr + radius_cells) + 2)
                c0 = max(0, int(nc - radius_cells) - 1)
                c1 = min(cols, int(nc + radius_cells) + 2)
                rr = np.arange(r0, r1).reshape(-1, 1)
                cc = np.arange(c0, c1).reshape(1, -1)
                dist_sq = ((rr - nr) ** 2 + (cc - nc) ** 2) / max(radius_cells ** 2, 1e-9)
                falloff = np.maximum(0.0, 1.0 - dist_sq).astype(np.float32)
                suppress = (1.0 - falloff).astype(np.float32)
                for layer_arr in detail_density.values():
                    layer_arr[r0:r1, c0:c1] *= suppress

            if len(clearings) >= target:
                break

        if not found_child:
            # Remove exhausted active sample.
            active.pop(active_idx)

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

    Algorithm (SpeedTree/Houdini scatter quality)
    ---------------------------------------------
    For each log:
    1. Pick a start cell on a gentle slope inside the forest.
    2. Determine per-log length and diameter from species-realistic RNG:
       - length: U[4, 18] cells (≈ 8–36 m at 2 m/cell — storm-felled tree range)
       - diameter: U[0.3, 1.2] m (sapling → mature trunk)
    3. Orient the log along the **local slope aspect** (downhill bearing) at
       the start cell, derived from ``np.gradient`` of the height field.
       The long axis is the downslope direction; a jitter of ±15° is applied
       via the RNG to avoid all logs being perfectly aligned.
    4. Walk ``actual_steps`` steps (clamped to [2, log_steps + length//2])
       using greedy steepest-descent (8-connected).
    5. Stamp path cells into ``detail_density["ground_cover"]`` with
       ``log_density_value``.
    6. Return a FallenLogSpec for each accepted log.

    Diameter is stored in ``FallenLogSpec.rotation_radians`` field comment but
    also accessible via the ``length_cells`` / ``rotation_radians`` attributes.
    A ``diameter_m`` attribute is injected dynamically for downstream users.
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

    # Slope and aspect from height gradient (used for log orientation)
    dy = np.gradient(height, stack.cell_size, axis=0)
    dx = np.gradient(height, stack.cell_size, axis=1)
    slope = np.sqrt(dx ** 2 + dy ** 2)

    # aspect_rad: downhill bearing (direction water would flow)
    # arctan2(-dy, -dx) points toward steepest descent in grid space.
    aspect_rad = np.arctan2(-dy, -dx).astype(np.float32)

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

        # --- Per-log variation (species-realistic) ---
        log_length_cells = int(rng.integers(4, 19))   # 4–18 cells
        log_diameter_m = float(rng.uniform(0.3, 1.2))  # 0.3–1.2 m

        # Slope aspect at start cell gives primary downhill bearing.
        base_aspect = float(aspect_rad[sr, sc])
        jitter = float(rng.uniform(-np.pi / 12.0, np.pi / 12.0))  # ±15°
        oriented_aspect = base_aspect + jitter

        # Greedy 8-connected downhill walk, length capped to log_length_cells
        actual_steps = min(log_steps + log_length_cells // 2, log_length_cells)
        path: List[Tuple[int, int]] = [(sr, sc)]
        cr, cc = sr, sc
        for _ in range(actual_steps):
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

        # Stamp log into ground_cover density (width ~ diameter_m / cell_size cells)
        if gc_layer is not None:
            half_w = max(0, int(round(log_diameter_m / stack.cell_size / 2.0)))
            for pr, pc in path:
                for wr in range(-half_w, half_w + 1):
                    for wc in range(-half_w, half_w + 1):
                        rr2, cc2 = pr + wr, pc + wc
                        if 0 <= rr2 < rows and 0 <= cc2 < cols:
                            gc_layer[rr2, cc2] = float(
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
        # Final rotation uses actual path endpoints; falls back to oriented
        # aspect when path is degenerate (start == end).
        if start_world != end_world:
            rotation = float(np.arctan2(
                end_world[1] - start_world[1],
                end_world[0] - start_world[0],
            ))
        else:
            rotation = oriented_aspect

        spec = FallenLogSpec(
            start_world=start_world,
            end_world=end_world,
            length_cells=len(path),
            rotation_radians=rotation,
        )
        # Inject diameter as a dynamic attribute for downstream consumers.
        spec.diameter_m = log_diameter_m  # type: ignore[attr-defined]
        logs.append(spec)
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
    """Apply forest-edge species-diversity gradient across all four layers.

    Ecology basis (Forman 1995 / SpeedTree edge scattering)
    --------------------------------------------------------
    Forest edges are the most species-diverse zones: light penetration,
    moisture gradients, and seed dispersal combine to push understory,
    shrub, and ground cover density higher than either the forest interior
    or the open field.  Canopy density drops at the edge (trees are
    shorter and more wind-thrown at margins).

    Algorithm
    ---------
    1. Detect the forest boundary via ``scipy.ndimage.morphological_gradient``
       on ``forest_mask`` (or ``biome_boundary_mask`` when given).
    2. Compute EDT distance from every cell to the nearest boundary pixel.
    3. Build a linearly tapered weight:
         ``taper = max(0, 1 - dist / edge_width_cells)``
       This is non-zero only inside the edge strip.
    4. Apply per-layer boosts that model the real diversity gradient:
       - understory  : +edge_boost_factor        (peak diversity, dense shrubs)
       - shrub       : +edge_boost_factor * 0.80  (light-demanding shrubs thrive)
       - ground_cover: +edge_boost_factor * 0.50  (forbs, ferns along edge)
       - canopy      : −edge_boost_factor * 0.30  (trees thinner / shorter at edge)
    All outputs are clipped to [0, 1].

    Falls back to manual 4-connected BFS distance when scipy is unavailable.
    """
    shape = vegetation.canopy_density.shape

    if biome_boundary_mask is not None:
        src_mask = np.asarray(biome_boundary_mask, dtype=np.uint8)
    else:
        src_mask = np.asarray(forest_mask, dtype=np.uint8)

    if src_mask.shape != shape:
        raise ValueError("boundary mask shape must match vegetation layers")

    if _SCIPY_OK:
        boundary = _ndimage.morphological_gradient(src_mask, size=3).astype(bool)
        if np.any(boundary):
            dist_from_boundary = _ndimage.distance_transform_edt(~boundary).astype(np.float32)
        else:
            dist_from_boundary = np.full(shape, float(max(shape)), dtype=np.float32)
    else:
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

    # Linear taper: 1.0 at boundary pixel, 0.0 at edge_width_cells distance.
    taper = np.clip(
        1.0 - dist_from_boundary / float(max(edge_width_cells, 1)),
        0.0,
        1.0,
    ).astype(np.float32)

    boost = taper * edge_boost_factor

    # Species-diversity gradient per layer (4-layer vertical profile)
    return VegetationLayers(
        # Canopy thins at the edge — wind exposure and light competition.
        canopy_density=np.clip(
            vegetation.canopy_density - boost * 0.30, 0.0, 1.0
        ).astype(np.float32),
        # Sub-canopy (formerly understory) peaks at edge — max light + shelter.
        sub_canopy_density=np.clip(
            vegetation.sub_canopy_density + boost, 0.0, 1.0
        ).astype(np.float32),
        # Shrubs thrive in the transition zone.
        shrub_density=np.clip(
            vegetation.shrub_density + boost * 0.80, 0.0, 1.0
        ).astype(np.float32),
        # Ground cover (forbs, ferns) benefits from edge light.
        ground_cover_density=np.clip(
            vegetation.ground_cover_density + boost * 0.50, 0.0, 1.0
        ).astype(np.float32),
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
    """Override vegetation in cultivated zones with agricultural row pattern.

    Agricultural land classification drives row spacing
    ---------------------------------------------------
    When ``intent.composition_hints['cultivated_zones']`` is a list of zone
    objects, each zone may carry a ``land_class`` attribute (str) that maps
    to a canonical row spacing and crop-row density:

      "grain_field"    → row_spacing=3,  row_density=1.00  (wheat/barley, tight rows)
      "root_crop"      → row_spacing=5,  row_density=0.95  (potatoes, wide beds)
      "orchard"        → row_spacing=7,  row_density=0.85  (trees, wide spacing)
      "kitchen_garden" → row_spacing=2,  row_density=1.00  (dense kitchen plots)
      <default>        → uses the ``row_spacing`` / ``cultivated_density`` params

    Algorithm
    ---------
    (a) Clear natural vegetation inside each zone (canopy→0.05, understory→0.02,
        shrub→0.05, ground→cultivated_density).
    (b) Stamp crop rows: ``ground[row_idx, zone_cols] = row_density`` for every
        row_idx that is a multiple of zone_row_spacing within the zone.
    (c) Add a soft inter-row suppression: non-crop rows get
        ``ground *= 0.65`` to create visible ploughed furrow contrast.

    When no intent zones are provided, the boolean ``cultivation_mask`` is
    used as a single zone with the caller-supplied row_spacing.
    """
    # Ensure cultivated_density survives the float64→float32 cast without
    # rounding below the requested value (np.float32(0.9) < 0.9 in Python).
    _f32 = np.float32(cultivated_density)
    if float(_f32) < cultivated_density:
        cultivated_density = float(np.nextafter(_f32, np.float32(1.0)))

    base_mask = np.asarray(cultivation_mask, dtype=bool)
    shape = vegetation.canopy_density.shape
    if base_mask.shape != shape:
        raise ValueError("cultivation_mask shape must match vegetation layers")

    # Land-class → (row_spacing, row_density) lookup table
    _LAND_CLASS_PARAMS: Dict[str, Tuple[int, float]] = {
        "grain_field":    (3,  1.00),
        "root_crop":      (5,  0.95),
        "orchard":        (7,  0.85),
        "kitchen_garden": (2,  1.00),
    }

    # Use float64 working arrays so scalar assignments like 0.9 survive
    # without float32 rounding (np.float32(0.9) < 0.9 in Python float space).
    canopy = vegetation.canopy_density.astype(np.float64)
    sub_canopy = vegetation.sub_canopy_density.astype(np.float64)
    shrub = vegetation.shrub_density.astype(np.float64)
    ground = vegetation.ground_cover_density.astype(np.float64)

    # Resolve zone list from intent composition hints
    zones_from_intent = []
    if intent is not None:
        hints = getattr(intent, "composition_hints", None) or {}
        zones_from_intent = hints.get("cultivated_zones", [])

    def _apply_zone(r_sl: slice, c_sl: slice, zone_row_spacing: int, row_density: float) -> None:
        rows_in_zone = range(*r_sl.indices(shape[0]))

        canopy[r_sl, c_sl] = 0.05
        sub_canopy[r_sl, c_sl] = 0.02
        shrub[r_sl, c_sl] = 0.05
        ground[r_sl, c_sl] = float(cultivated_density)

        # (b) Crop rows boosted to row_density
        # (c) Inter-row furrows suppressed to 65 % of cultivated_density
        for row_idx in rows_in_zone:
            if row_idx % zone_row_spacing == 0:
                ground[row_idx, c_sl] = float(row_density)
            else:
                # Ploughed furrow — darker, less cover than the seedbed baseline
                ground[row_idx, c_sl] = float(cultivated_density) * 0.65

    if zones_from_intent:
        for zone in zones_from_intent:
            if hasattr(zone, "to_cell_slice"):
                z_bbox = zone
            elif hasattr(zone, "bounds"):
                z_bbox = zone.bounds
            else:
                continue

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

            # Per-zone land-class lookup
            land_class = getattr(zone, "land_class", None) or ""
            if land_class in _LAND_CLASS_PARAMS:
                z_spacing, z_density = _LAND_CLASS_PARAMS[land_class]
            else:
                z_spacing, z_density = row_spacing, float(cultivated_density)

            _apply_zone(r_sl, c_sl, z_spacing, z_density)
    else:
        # Fallback: boolean mask as single zone (full-array row slice).
        rows_count, _ = shape
        canopy[base_mask] = 0.05
        sub_canopy[base_mask] = 0.02
        shrub[base_mask] = 0.05
        ground[base_mask] = float(cultivated_density)

        # Boost crop rows to 1.0 within the mask
        for row_idx in range(rows_count):
            if row_idx % row_spacing == 0:
                row_in_mask = base_mask[row_idx, :]
                ground[row_idx, row_in_mask] = 1.0

    return VegetationLayers(
        canopy_density=canopy.astype(np.float32),
        sub_canopy_density=sub_canopy.astype(np.float32),
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

    The vegetation layers are updated in-place via the ``species_density_dict``
    values (canopy/understory/shrub/ground_cover).

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
        sub_canopy = (vegetation.sub_canopy_density * (1.0 - suppression * 0.8)).astype(np.float32)
        shrub = (vegetation.shrub_density * (1.0 - suppression * 0.7)).astype(np.float32)
        ground_cover = (vegetation.ground_cover_density * (1.0 - suppression * 0.6)).astype(np.float32)
        return VegetationLayers(
            canopy_density=vegetation.canopy_density.copy(),
            sub_canopy_density=sub_canopy,
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

    for suppressor_name in allelopathic_species:
        if suppressor_name not in densities:
            continue
        suppressor_map = densities[suppressor_name]

        # --- EDT-based exponential falloff (AAA quality) ---
        # 1. Threshold the suppressor density to get source cells (>0.3).
        # 2. EDT gives exact Euclidean distance from every cell to the nearest
        #    source cell.
        # 3. Falloff = exp(-dist / radius) — matches walnut/pine allelopathy
        #    research: strongest suppression near the trunk, decays smoothly.
        # 4. Scale to [0, suppression_weight] and multiply into target densities.
        source_mask = suppressor_map > 0.3

        if _SCIPY_OK and np.any(source_mask):
            dist_to_source = _ndimage.distance_transform_edt(~source_mask).astype(np.float32)
            # exp(-dist / radius): 1.0 at source cells, decays to ~0.14 at 2× radius
            radius = float(max(allelopathy_radius_cells, 1.0))
            suppression_field = np.exp(-dist_to_source / radius).astype(np.float32)
        elif np.any(source_mask):
            # Fallback without scipy: BFS distance in cells, then exponential
            dist_to_source = np.full(suppressor_map.shape, float(allelopathy_radius_cells * 4), dtype=np.float32)
            dist_to_source[source_mask] = 0.0
            current = source_mask.copy()
            for step in range(1, int(allelopathy_radius_cells * 4) + 1):
                expanded = np.zeros_like(current)
                expanded[1:, :] |= current[:-1, :]
                expanded[:-1, :] |= current[1:, :]
                expanded[:, 1:] |= current[:, :-1]
                expanded[:, :-1] |= current[:, 1:]
                new_cells = expanded & (dist_to_source == float(allelopathy_radius_cells * 4))
                if not np.any(new_cells):
                    break
                dist_to_source[new_cells] = float(step)
                current = new_cells
            radius = float(max(allelopathy_radius_cells, 1.0))
            suppression_field = np.exp(-dist_to_source / radius).astype(np.float32)
        else:
            # No source cells — no suppression
            suppression_field = np.zeros_like(suppressor_map)

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

    # Write back to VegetationLayers channels (4-layer public contract).
    canopy = densities.get("canopy", vegetation.canopy_density.copy())
    sub_canopy = densities.get("understory", vegetation.sub_canopy_density.copy())
    shrub = densities.get("shrub", vegetation.shrub_density.copy())
    ground_cover = densities.get("ground_cover", vegetation.ground_cover_density.copy())

    return VegetationLayers(
        canopy_density=canopy.astype(np.float32),
        sub_canopy_density=sub_canopy.astype(np.float32),
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
    # apply_edge_effects: always run — forest_mask channel activates biome-boundary
    # mode; falls back to a canopy-derived mask when channel is absent.
    if hints.get("veg_edge_effects", True) or stack.get("forest_mask") is not None:
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

    # apply_cultivated_zones: run when hint is set OR gameplay_zone channel present
    if hints.get("veg_cultivated_zones", False) or stack.get("gameplay_zone") is not None:
        cult = stack.get("gameplay_zone")
        if cult is not None:
            cult_mask = np.asarray(cult, dtype=np.int32) == 2
            # Attach stack to intent so apply_cultivated_zones can resolve BBox coords
            _intent = state.intent
            _intent._stack = stack  # type: ignore[attr-defined]
            layers = apply_cultivated_zones(layers, cult_mask, intent=_intent)

    # apply_allelopathic_exclusion: always run — canopy acts as default suppressor;
    # if species_density channel is present on the stack, use it as well.
    if hints.get("veg_allelopathic_exclusion", True) or stack.get("species_density") is not None:
        species_dict = layers.as_dict()
        # Merge in any per-species density channels from the stack
        stack_species = stack.get("species_density")
        if stack_species is not None and isinstance(stack_species, dict):
            species_dict.update(
                {k: np.asarray(v, dtype=np.float32) for k, v in stack_species.items()}
            )
        # Canopy is the default allelopathic suppressor (tall trees = walnut/pine)
        layers = apply_allelopathic_exclusion(
            layers,
            species_density_dict=species_dict,
            allelopathic_species=["canopy"],
        )

    # --- Feature generators (results stored in metrics) ---
    # detect_disturbance_patches: run when hint is set OR slope/erosion channels present
    disturbance_patches: List = []
    if (
        hints.get("veg_disturbance_patches", False)
        or stack.get("slope") is not None
        or stack.get("erosion_amount") is not None
    ):
        disturbance_patches = detect_disturbance_patches(
            stack, seed, intent=state.intent
        )

    # Build shared detail_density dict for clearings + logs to stamp into.
    # Preserve the canonical public keys only; normalize older alias names.
    existing = stack.detail_density or {}
    merged: Dict[str, np.ndarray] = {}
    if "canopy" in existing:
        merged["canopy"] = np.asarray(existing["canopy"]).copy()
    if "understory" in existing:
        merged["understory"] = np.asarray(existing["understory"]).copy()
    elif "sub_canopy" in existing:
        merged["understory"] = np.asarray(existing["sub_canopy"]).copy()
    if "shrub" in existing:
        merged["shrub"] = np.asarray(existing["shrub"]).copy()
    if "ground_cover" in existing:
        merged["ground_cover"] = np.asarray(existing["ground_cover"]).copy()
    keys = ("canopy", "understory", "shrub", "ground_cover")
    sources = (
        layers.canopy_density,
        layers.sub_canopy_density,
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

    # place_clearings: run when hint is set OR cliff_mask/slope channel present
    clearings: List = []
    if (
        hints.get("veg_clearings", False)
        or stack.get("cliff_mask") is not None
        or stack.get("slope") is not None
    ):
        clearings = place_clearings(
            stack, state.intent, seed=seed, detail_density=merged
        )

    # place_fallen_logs: run when hint is set OR forest_mask channel present
    fallen_logs: List = []
    if hints.get("veg_fallen_logs", False) or stack.get("forest_mask") is not None:
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


# ---------------------------------------------------------------------------
# Emergent grass pass — Fix 9.9 / BUG-S10-011
# ---------------------------------------------------------------------------

GRASS_DENSITY_SCALE: float = 5.0
"""Unity Detail Cards per m^2 at full splatmap grass weight."""

_GRASS_SPLAT_INDEX: int = 0
"""Index into splatmap_weights_layer for the grass proxy layer (ground = 0).
Replace with a structural label index after Fix 10.10 lands.
"""


def compute_emergent_grass_density(
    splatmap: np.ndarray,
    grass_idx: int = _GRASS_SPLAT_INDEX,
) -> np.ndarray:
    """Derive grass density from splatmap ground weight (Fix 9.9).

    Parameters
    ----------
    splatmap : np.ndarray shape (H, W, L) float32
        Splatmap weights — each layer sums to 1.0 per cell.
    grass_idx : int
        Layer index used as grass proxy (default 0 = ground layer).

    Returns
    -------
    np.ndarray shape (H, W) float32 — Unity Detail Card density per m^2.
    Returns zeros when splatmap is invalid or grass_idx out of range.
    """
    weights = np.asarray(splatmap, dtype=np.float32)
    if weights.ndim != 3 or weights.shape[2] <= grass_idx:
        H = int(weights.shape[0]) if weights.ndim >= 1 else 1
        W = int(weights.shape[1]) if weights.ndim >= 2 else 1
        return np.zeros((H, W), dtype=np.float32)
    return (weights[..., grass_idx] * GRASS_DENSITY_SCALE).astype(np.float32)


def pass_emergent_grass(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Write grass_density_map to stack from splatmap weights (Fix 9.9).

    Consumes: splatmap_weights_layer
    Produces: grass_density_map (float32 H×W texture for Unity SetDetailLayer)
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    splatmap = stack.get("splatmap_weights_layer")

    if splatmap is None:
        return PassResult(
            pass_name="emergent_grass",
            status="skipped",
            issues=[],
            duration_seconds=time.perf_counter() - t0,
            consumed_channels=("splatmap_weights_layer",),
            produced_channels=("grass_density_map",),
            metrics={},
        )

    grass_map = compute_emergent_grass_density(splatmap)
    stack.set("grass_density_map", grass_map, "emergent_grass")

    return PassResult(
        pass_name="emergent_grass",
        status="ok",
        issues=[],
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("splatmap_weights_layer",),
        produced_channels=("grass_density_map",),
        metrics={"grass_density_mean": float(grass_map.mean())},
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
    # Fix 9.9 — emergent grass
    "GRASS_DENSITY_SCALE",
    "compute_emergent_grass_density",
    "pass_emergent_grass",
]

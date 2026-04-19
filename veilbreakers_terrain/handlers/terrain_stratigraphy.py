"""Bundle I — terrain_stratigraphy.

Stratigraphic rock layering: each tile has an ordered stack of
``StratigraphyLayer`` with hardness, thickness, dip, azimuth, rock type,
geological age, color, and strike.  The pass populates
``stack.strata_orientation`` (H, W, 3 unit vector) and
``stack.rock_hardness`` (H, W float32) based on which layer the cell's
elevation falls into.

AAA features implemented:
  * N=5-9 default sedimentary/metamorphic/igneous layers with full geological
    attributes (rock_type, age_ma, color_rgb, strike_angle_rad).
  * Fourier fold deformation: z_fold = z + A*sin(2π*x/λ + φ)*exp(-|y-y0|/w)
    with geologically plausible amplitude and wavelength sampling.
  * Angular unconformity detection: where erosion depth exceeds a strata band,
    truncation angle = asin(clip(erosion_depth / thickness, -1, 1)) is written
    into the unconformity_mask channel.
  * Igneous dike/intrusion simulation: elliptical cross-section, +0.3 saturation
    red-channel bake (oxidised iron staining) into an albedo_shift channel.
  * Hardness-coupled erosion: h_eroded = h_original − erosion_depth*(1−hardness)
    producing differential erosion, mesa profiles, and potential overhangs.
  * Strata cross-section JSON export (strata_cross_section) for Unity material
    assignment — per-cell surface layer_id + material_id lookup table.

Pure numpy, no bpy. Z-up, world meters. All seeding is deterministic via
``derive_pass_seed``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class StratigraphyLayer:
    """One rock stratum in a stratigraphic stack.

    hardness       : float in [0, 1] — 0 = loose sediment, 1 = indurated caprock
    thickness_m    : world-meter vertical thickness of the layer
    dip_rad        : angle from horizontal (0 = flat, pi/4 = 45° tilted)
    azimuth_rad    : compass bearing of dip direction (0 = +X, pi/2 = +Y)
    rock_type      : geological classification string — "sedimentary",
                     "metamorphic", or "igneous"
    age_ma         : geological age in mega-annum (Ma).  Deeper = older.
    color_rgb      : (R, G, B) float tuple in [0, 1] — visualiser / Unity LUT
    strike_angle_rad : azimuth of the strike line (perpendicular to dip direction)
    color_hex      : optional hex tag kept for backward compat; derived from
                     color_rgb if not supplied explicitly
    """

    layer_id: str
    hardness: float
    thickness_m: float
    dip_rad: float = 0.0
    azimuth_rad: float = 0.0
    rock_type: str = "sedimentary"
    age_ma: float = 0.0
    color_rgb: Tuple[float, float, float] = (0.5, 0.5, 0.5)
    strike_angle_rad: float = 0.0
    color_hex: str = "#888888"

    def __post_init__(self) -> None:
        if not (0.0 <= self.hardness <= 1.0):
            raise ValueError(
                f"StratigraphyLayer.hardness must be in [0,1], got {self.hardness}"
            )
        if self.thickness_m <= 0.0:
            raise ValueError(
                f"StratigraphyLayer.thickness_m must be > 0, got {self.thickness_m}"
            )
        valid_types = {"sedimentary", "metamorphic", "igneous"}
        if self.rock_type not in valid_types:
            raise ValueError(
                f"StratigraphyLayer.rock_type must be one of {valid_types}, "
                f"got {self.rock_type!r}"
            )
        # Ensure color_rgb is a 3-tuple of floats in [0, 1]
        r, g, b = self.color_rgb
        self.color_rgb = (
            float(np.clip(r, 0.0, 1.0)),
            float(np.clip(g, 0.0, 1.0)),
            float(np.clip(b, 0.0, 1.0)),
        )


@dataclass
class StratigraphyStack:
    """Ordered stratigraphic column, bottom-to-top.

    ``base_elevation_m`` is the world-Z elevation (meters) of the bottom
    of layer 0. ``layers[0]`` is the oldest / deepest rock; subsequent
    layers sit on top of it.
    """

    base_elevation_m: float = 0.0
    layers: List[StratigraphyLayer] = field(default_factory=list)

    def total_thickness(self) -> float:
        return float(sum(L.thickness_m for L in self.layers))

    def layer_for_elevation(self, elevation_m: float) -> Optional[StratigraphyLayer]:
        """Return the stratum whose world-Z band contains ``elevation_m``.

        Cells above the top of the stack return the topmost layer; cells
        below the base return the bottom layer. This makes the function
        total — every elevation maps to some layer.
        """
        if not self.layers:
            return None
        z = elevation_m - self.base_elevation_m
        if z <= 0.0:
            return self.layers[0]
        running = 0.0
        for layer in self.layers:
            running += layer.thickness_m
            if z <= running:
                return layer
        return self.layers[-1]


# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------


def compute_strata_orientation(
    stack: TerrainMaskStack,
    strat_stack: StratigraphyStack,
) -> np.ndarray:
    """Populate ``stack.strata_orientation`` (H, W, 3 unit vector).

    The orientation vector is the bedding-plane normal in world space,
    derived from the dip + azimuth of the layer each cell belongs to.
    Horizontal strata (dip = 0) yield ``(0, 0, 1)``; dipped strata tilt
    proportionally in the azimuth direction.
    """
    if stack.height is None:
        raise ValueError("compute_strata_orientation requires stack.height")
    if not strat_stack.layers:
        raise ValueError("StratigraphyStack must have at least one layer")

    h = np.asarray(stack.height, dtype=np.float64)
    H, W = h.shape
    orientation = np.zeros((H, W, 3), dtype=np.float32)

    # Build a per-layer band lookup once (fast path). We vectorize by
    # classifying each cell's (elev - base) into a layer index via
    # cumulative thicknesses.
    thicks = np.array([L.thickness_m for L in strat_stack.layers], dtype=np.float64)
    bounds = np.concatenate(([0.0], np.cumsum(thicks)))  # length N+1
    dips = np.array([L.dip_rad for L in strat_stack.layers], dtype=np.float64)
    azs = np.array([L.azimuth_rad for L in strat_stack.layers], dtype=np.float64)

    z = (h - strat_stack.base_elevation_m).clip(min=0.0)
    # np.searchsorted gives the index of the first bound > z. Subtract 1
    # and clip to [0, N-1] so cells above the top use the top layer.
    idx = np.searchsorted(bounds, z, side="right") - 1
    idx = np.clip(idx, 0, len(strat_stack.layers) - 1)

    cell_dip = dips[idx]
    cell_az = azs[idx]

    # Bedding-plane normal: start with +Z, rotate by dip around axis
    # perpendicular to azimuth. Equivalent closed form:
    #   n = (sin(dip)*cos(az), sin(dip)*sin(az), cos(dip))
    sin_d = np.sin(cell_dip)
    cos_d = np.cos(cell_dip)
    nx = sin_d * np.cos(cell_az)
    ny = sin_d * np.sin(cell_az)
    nz = cos_d

    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    norm = np.where(norm < 1e-9, 1.0, norm)
    orientation[..., 0] = (nx / norm).astype(np.float32)
    orientation[..., 1] = (ny / norm).astype(np.float32)
    orientation[..., 2] = (nz / norm).astype(np.float32)

    stack.set("strata_orientation", orientation, "stratigraphy")
    return orientation


def compute_rock_hardness(
    stack: TerrainMaskStack,
    strat_stack: StratigraphyStack,
) -> np.ndarray:
    """Populate ``stack.rock_hardness`` from elevation → layer mapping.

    Returns a (H, W) float32 array in [0, 1]. Cells at elevations
    inside harder layers carry higher values, so downstream passes
    (erosion, cliffs) can modulate their rates.
    """
    if stack.height is None:
        raise ValueError("compute_rock_hardness requires stack.height")
    if not strat_stack.layers:
        raise ValueError("StratigraphyStack must have at least one layer")

    h = np.asarray(stack.height, dtype=np.float64)
    thicks = np.array([L.thickness_m for L in strat_stack.layers], dtype=np.float64)
    bounds = np.concatenate(([0.0], np.cumsum(thicks)))
    hardness_vals = np.array(
        [L.hardness for L in strat_stack.layers], dtype=np.float64
    )

    z = (h - strat_stack.base_elevation_m).clip(min=0.0)
    idx = np.searchsorted(bounds, z, side="right") - 1
    idx = np.clip(idx, 0, len(strat_stack.layers) - 1)

    hardness = hardness_vals[idx].astype(np.float32)
    stack.set("rock_hardness", hardness, "stratigraphy")
    return hardness


def apply_differential_erosion(
    stack: TerrainMaskStack,
    strat_stack: Optional["StratigraphyStack"] = None,
    *,
    max_erosion_fraction: float = 0.12,
    undercutting_strength: float = 0.4,
) -> np.ndarray:
    """Compute a height delta where different rock strata erode at different rates.

    Implements the AAA hardness-erosion coupling formula:

        h_eroded = h_original - erosion_depth * (1 - hardness)

    which means hard rock (hardness→1) barely erodes; soft rock (hardness→0)
    takes the full erosion depth.  This is the same formulation used in Houdini
    Heightfield Erode's "erodability" parameter.

    Additional modelling on top of the base coupling:

    1. **Per-cell erosion depth** — derived from topographic exposure.  Cells
       above their 3×3 neighbourhood mean are more exposed (exposed → up to
       1.5× base); sheltered hollows receive 0.5×.

    2. **Exposure multiplier** — clipped relief gradient maps to [0.5, 1.5].

    3. **Undercutting** — where the hardness immediately above a cell is higher
       than the cell itself, an additional undercut delta is added proportional
       to the hardness contrast and ``undercutting_strength``.  This produces
       overhanging ledges and mesa profiles at stratum boundaries.

    4. **Scale** — the combined rate is normalised so the maximum erosion equals
       ``max_erosion_fraction * relief_span``.  Valley floors are not eroded
       further (relief_norm weight).

    This function does NOT modify ``stack.height`` in place; the caller
    applies the returned delta via ``stack.set``.

    Args:
        stack: Must have both ``height`` and ``rock_hardness`` populated.
        strat_stack: Optional stratigraphic column (unused in current impl;
            retained for API compatibility — undercutting is estimated from
            the hardness gradient alone when None).
        max_erosion_fraction: Maximum erosion as a fraction of total terrain
            relief.  Default 0.12 (12%).
        undercutting_strength: Weight [0, 1] applied to the undercutting
            term.  0 = no undercutting; 1 = full undercutting amplitude.

    Returns:
        (H, W) float64 ndarray of signed metre deltas (all values ≤ 0).

    Raises:
        ValueError: If ``stack.rock_hardness`` or ``stack.height`` is None.
    """
    if stack.rock_hardness is None:
        raise ValueError(
            "apply_differential_erosion requires stack.rock_hardness "
            "(call compute_rock_hardness first)"
        )
    if stack.height is None:
        raise ValueError("apply_differential_erosion requires stack.height")

    hardness = np.asarray(stack.rock_hardness, dtype=np.float64)
    h = np.asarray(stack.height, dtype=np.float64)
    H, W = hardness.shape

    # ------------------------------------------------------------------
    # 1. Topographic exposure depth — base erosion depth per cell
    #    Cells above local mean are exposed; sheltered cells erode less.
    # ------------------------------------------------------------------
    neighbourhood_mean = np.zeros_like(h)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            neighbourhood_mean += np.roll(np.roll(h, dr, axis=0), dc, axis=1)
    neighbourhood_mean /= 9.0

    relative_exposure = h - neighbourhood_mean
    exp_span = float(np.abs(relative_exposure).max())
    if exp_span < 1e-6:
        exp_span = 1.0
    # Map to [0.5, 1.5]: exposed → 1.5, sheltered → 0.5
    exposure_mult = 1.0 + np.clip(relative_exposure / exp_span, -0.5, 0.5)

    # ------------------------------------------------------------------
    # 2. AAA hardness-erosion coupling (Houdini Heightfield reference):
    #    delta = -erosion_depth * (1 - hardness)
    #    erosion_depth here is exposure_mult (normalised to [0.5, 1.5]).
    #    Hard rock (hardness=1) → delta=0; soft rock (hardness=0) → full depth.
    # ------------------------------------------------------------------
    erosion_rate = exposure_mult * (1.0 - hardness)

    # ------------------------------------------------------------------
    # 3. Undercutting: soft layer directly under a hard layer cap
    #    Proxy: where hardness increases sharply going upward (positive
    #    vertical gradient of hardness), the soft cell is being undercut.
    # ------------------------------------------------------------------
    hardness_above = np.roll(hardness, -1, axis=0)  # cell one row "higher"
    hardness_contrast = np.clip(hardness_above - hardness, 0.0, 1.0)
    soft = np.clip(1.0 - hardness, 0.0, 1.0)
    undercut = undercutting_strength * soft * hardness_contrast

    # ------------------------------------------------------------------
    # 4. Scale combined rate to physical metres
    # ------------------------------------------------------------------
    combined_rate = erosion_rate + undercut

    rate_max = float(combined_rate.max())
    if rate_max < 1e-9:
        return np.zeros((H, W), dtype=np.float64)
    combined_rate /= rate_max

    hmin = float(h.min())
    relief_span = float(h.max() - hmin)
    if relief_span < 1e-6:
        relief_span = 1.0

    # Scale by local height above minimum so valley floors don't erode further.
    relief_norm = np.clip((h - hmin) / relief_span, 0.0, 1.0)

    max_drop = max_erosion_fraction * relief_span
    delta = -combined_rate * relief_norm * max_drop
    return delta.astype(np.float64)


def simulate_fold_deformation(
    stack: TerrainMaskStack,
    strat_stack: StratigraphyStack,
    *,
    rng: Optional[np.random.Generator] = None,
    amplitude_m: Optional[float] = None,
    wavelength_m: Optional[float] = None,
    phase_rad: Optional[float] = None,
    fold_axis_y0_frac: float = 0.5,
    decay_width_frac: float = 0.3,
) -> np.ndarray:
    """Apply Fourier fold deformation to stack heights (AAA req #3).

    Simulates regional tectonic folding using the closed-form:

        z_fold(x, y) = z(x, y)
            + A * sin(2π * x / λ + φ) * exp(-|y - y0| / w)

    where:
      * A  = fold amplitude (metres) — sampled from [0.5, 3.0]× relief if None
      * λ  = fold wavelength (metres) — sampled from [0.3, 0.8]× tile_width
      * φ  = phase offset — uniform in [0, 2π) if None
      * y0 = fold axis lateral position (world metres along Y axis)
      * w  = exponential decay half-width (metres) — controls fold extent

    The function modifies stack.height in-place (the fold is a permanent
    structural deformation, not a delta channel) and returns the (H, W)
    deformation delta so callers can track cumulative changes.

    Args:
        stack: Must have ``height`` populated.
        strat_stack: Used to read the dip_rad of the dominant layer as a
            proxy for pre-existing structural tilt (influences amplitude).
        rng: Seeded numpy Generator for deterministic sampling.
        amplitude_m: Override fold amplitude in metres.  When None, sampled
            from geologically plausible range.
        wavelength_m: Override fold wavelength in metres.  When None, sampled.
        phase_rad: Override fold phase.  When None, sampled uniformly.
        fold_axis_y0_frac: Fractional position of fold axis along Y (0→1).
            Default 0.5 = centre of tile.
        decay_width_frac: Exponential decay half-width as fraction of tile
            height in world metres.  Default 0.3.

    Returns:
        (H, W) float64 delta array of the applied deformation.
    """
    if stack.height is None:
        raise ValueError("simulate_fold_deformation requires stack.height")

    h = np.asarray(stack.height, dtype=np.float64)
    H, W = h.shape

    if rng is None:
        rng = np.random.default_rng(0)

    # World-space X and Y coordinate grids
    tile_width_m = W * stack.cell_size
    tile_height_m = H * stack.cell_size

    xs = np.arange(W, dtype=np.float64) * stack.cell_size
    ys = np.arange(H, dtype=np.float64) * stack.cell_size

    # Geologically plausible amplitude: 2–8 % of terrain relief, clamped
    relief = float(h.max() - h.min())
    if relief < 1.0:
        relief = 1.0
    if amplitude_m is None:
        amplitude_m = float(rng.uniform(0.02, 0.08) * relief)

    if wavelength_m is None:
        wavelength_m = float(rng.uniform(0.3, 0.8) * tile_width_m)
    wavelength_m = max(wavelength_m, stack.cell_size * 4)  # minimum 4 cells

    if phase_rad is None:
        phase_rad = float(rng.uniform(0.0, 2.0 * np.pi))

    fold_axis_y0_m = fold_axis_y0_frac * tile_height_m
    decay_width_m = max(decay_width_frac * tile_height_m, stack.cell_size * 2)

    # Vectorised fold: shape (H, W)
    # sin term varies along X; exp decay varies along Y
    sin_term = np.sin(2.0 * np.pi * xs[np.newaxis, :] / wavelength_m + phase_rad)
    exp_decay = np.exp(-np.abs(ys[:, np.newaxis] - fold_axis_y0_m) / decay_width_m)

    delta = amplitude_m * sin_term * exp_decay  # (H, W)

    stack.height = (h + delta).astype(stack.height.dtype)
    return delta.astype(np.float64)


def detect_unconformities(
    stack: TerrainMaskStack,
    strat_stack: StratigraphyStack,
    erosion_delta: np.ndarray,
) -> np.ndarray:
    """Detect angular unconformity surfaces and populate ``unconformity_mask`` (AAA req #2).

    An angular unconformity occurs where erosion removes enough material to
    truncate one or more strata, exposing the underlying tilted beds.

    Algorithm:
      For each cell, compute the erosion depth from ``erosion_delta``.
      If abs(erosion_depth) exceeds the thickness of the surface stratum,
      the bed is truncated.  The truncation angle (geological bedding-plane
      discordance) is:

          truncation_angle_rad = arcsin(clip(|erosion_depth| / thickness, 0, 1))

      Cells where truncation occurs (truncation_angle > 0.1 rad ≈ 6°) are
      marked in the returned unconformity mask (0 = conformable, 1 = angular
      unconformity).

    The mask is stored in ``stack`` under the channel name
    ``"unconformity_mask"`` with provenance "stratigraphy".

    Args:
        stack: Must have ``height`` and ``rock_hardness`` populated.
        strat_stack: Provides per-layer thicknesses.
        erosion_delta: (H, W) negative delta array (output of
            ``apply_differential_erosion``).

    Returns:
        (H, W) float32 unconformity mask in [0, 1].
    """
    if stack.height is None:
        raise ValueError("detect_unconformities requires stack.height")
    if not strat_stack.layers:
        return np.zeros(stack.height.shape, dtype=np.float32)

    h = np.asarray(stack.height, dtype=np.float64)
    H, W = h.shape
    erosion_depth = np.abs(np.asarray(erosion_delta, dtype=np.float64))

    # Build per-layer thickness array indexed by layer idx
    thicks = np.array([L.thickness_m for L in strat_stack.layers], dtype=np.float64)
    bounds = np.concatenate(([0.0], np.cumsum(thicks)))

    # Identify which layer each cell's surface elevation sits in
    z = (h - strat_stack.base_elevation_m).clip(min=0.0)
    idx = np.searchsorted(bounds, z, side="right") - 1
    idx = np.clip(idx, 0, len(strat_stack.layers) - 1)

    # Per-cell stratum thickness
    cell_thickness = thicks[idx]

    # Truncation angle per cell
    ratio = np.clip(erosion_depth / np.where(cell_thickness < 1e-6, 1e-6, cell_thickness), 0.0, 1.0)
    truncation_angle = np.arcsin(ratio)  # [0, π/2]

    # Unconformity threshold: ≥ 6° = 0.1047 rad
    UNCONFORMITY_THRESHOLD_RAD = 0.1047
    unconformity_mask = (truncation_angle >= UNCONFORMITY_THRESHOLD_RAD).astype(np.float32)

    stack.set("unconformity_mask", unconformity_mask, "stratigraphy")
    return unconformity_mask


def simulate_intrusions(
    stack: TerrainMaskStack,
    strat_stack: StratigraphyStack,
    *,
    rng: Optional[np.random.Generator] = None,
    n_intrusions: int = 3,
    width_range_m: Tuple[float, float] = (0.5, 5.0),
    albedo_iron_stain_strength: float = 0.3,
) -> np.ndarray:
    """Simulate igneous dike/intrusion features (AAA req #4).

    Models N sub-vertical igneous intrusions (dikes) with:
      * Elliptical cross-section in (X, Z) — width 0.5–5 m (configurable),
        height spanning the full stack thickness.
      * Baked albedo shift: +``albedo_iron_stain_strength`` saturation in the
        red channel (oxidised iron staining from hydrothermal alteration along
        the intrusion contact).
      * Hardness bump: intrusive rock sets local hardness to 0.85–0.95
        (dolerite to gabbro range) within the dike footprint.

    The function populates two channels on ``stack``:
      ``"intrusion_mask"``   — float32 (H, W) 0..1 dike presence weight
      ``"albedo_shift_rgb"`` — float32 (H, W, 3) per-channel additive shift

    Returns the ``intrusion_mask`` array.

    Args:
        stack: Must have ``height`` and ``rock_hardness`` populated.
        strat_stack: Used for vertical extent of dike placement.
        rng: Seeded numpy Generator.
        n_intrusions: Number of dikes to place.
        width_range_m: (min, max) dike half-width in metres.
        albedo_iron_stain_strength: Red-channel saturation shift for iron
            staining.  Gaea reference: 0.2–0.4 typical.

    Returns:
        (H, W) float32 intrusion_mask.
    """
    if stack.height is None:
        raise ValueError("simulate_intrusions requires stack.height")

    h = np.asarray(stack.height, dtype=np.float64)
    H, W = h.shape

    if rng is None:
        rng = np.random.default_rng(1)

    intrusion_mask = np.zeros((H, W), dtype=np.float32)
    albedo_shift = np.zeros((H, W, 3), dtype=np.float32)

    # World-space grids
    xs = np.arange(W, dtype=np.float64) * stack.cell_size
    ys = np.arange(H, dtype=np.float64) * stack.cell_size

    tile_width_m = W * stack.cell_size
    tile_height_m = H * stack.cell_size

    w_min, w_max = width_range_m
    for _ in range(n_intrusions):
        # Dike centre X position — random across tile width
        cx = float(rng.uniform(0.1, 0.9) * tile_width_m)
        # Dike half-width (ellipse semi-axis in X)
        a = float(rng.uniform(w_min, w_max))
        # Dike half-height = half tile height (extends full depth, vertical)
        b = tile_height_m * 0.5

        # Slight sub-vertical dip (0–10°) in X as dike azimuth variation
        dip_x = float(rng.uniform(-0.1, 0.1)) * tile_height_m  # horizontal lean

        # Ellipse distance in (X, Y) world space
        dx = xs[np.newaxis, :] - cx
        # Apply sub-vertical lean: shift x by (y/b)*dip_x
        dy_frac = (ys[:, np.newaxis] - tile_height_m * 0.5) / max(b, 1e-6)
        dx_adj = dx - dy_frac * dip_x

        # Ellipse test: (dx/a)^2 ≤ 1
        footprint = np.clip(1.0 - (dx_adj / max(a, 1e-6)) ** 2, 0.0, 1.0)
        # Smooth mask: sqrt gives elliptical falloff weight
        weight = np.sqrt(footprint).astype(np.float32)

        intrusion_mask = np.maximum(intrusion_mask, weight)

        # Albedo shift: oxidised iron staining (+red saturation)
        # Additive in [0, albedo_iron_stain_strength] on R channel
        # Slight desaturation on G/B channels (complement of red boost)
        albedo_shift[..., 0] += weight * albedo_iron_stain_strength          # R+
        albedo_shift[..., 1] -= weight * albedo_iron_stain_strength * 0.15   # G-
        albedo_shift[..., 2] -= weight * albedo_iron_stain_strength * 0.15   # B-

    # Clamp albedo shift to safe range
    albedo_shift = np.clip(albedo_shift, -1.0, 1.0).astype(np.float32)

    # Harden intrusion cells: set rock_hardness to 0.88 (dolerite) where present
    if stack.rock_hardness is not None:
        rh = np.asarray(stack.rock_hardness, dtype=np.float32)
        INTRUSION_HARDNESS = 0.88
        rh = np.where(intrusion_mask > 0.5, INTRUSION_HARDNESS, rh)
        stack.set("rock_hardness", rh, "stratigraphy")

    stack.set("intrusion_mask", intrusion_mask, "stratigraphy")
    stack.set("albedo_shift_rgb", albedo_shift, "stratigraphy")
    return intrusion_mask


def export_strata_cross_section(
    stack: TerrainMaskStack,
    strat_stack: StratigraphyStack,
) -> Dict:
    """Build strata cross-section dict for Unity material assignment (AAA req #6).

    Produces a JSON-serialisable dictionary (and stores it on stack as the
    channel ``"strata_cross_section"``) with:

      * ``"layer_table"``: ordered list of layer dicts, each with:
          - ``layer_id``    : str
          - ``material_id`` : int (0-based, stable index for Unity LUT)
          - ``rock_type``   : str
          - ``hardness``    : float
          - ``age_ma``      : float
          - ``color_rgb``   : [R, G, B] float list
      * ``"surface_material_id"``: (H, W) int32 flat array encoded as nested
          list — each cell holds the material_id of the layer visible at
          surface elevation.  Unity consumer reads this as TerrainLayer index.
      * ``"tile_metadata"``: dict with tile_size, cell_size, world_origin_x,
          world_origin_y, tile_x, tile_y.

    The per-cell surface layer is computed from ``stack.height`` using the
    same ``searchsorted`` lookup as ``compute_rock_hardness``.

    Returns the cross-section dict.  The dict is also stored on the stack
    under the key ``"strata_cross_section"`` (as a JSON-encoded bytes object
    stored in a (1,)-shape object array so the existing channel mechanism
    can hold it).

    Args:
        stack: Must have ``height`` populated.
        strat_stack: Provides the layer stack.

    Returns:
        dict with keys ``layer_table``, ``surface_material_id``,
        ``tile_metadata``.
    """
    if stack.height is None:
        raise ValueError("export_strata_cross_section requires stack.height")

    h = np.asarray(stack.height, dtype=np.float64)

    # Build stable material_id mapping (index in layers list)
    layer_table = []
    for mat_id, L in enumerate(strat_stack.layers):
        layer_table.append({
            "layer_id":    L.layer_id,
            "material_id": mat_id,
            "rock_type":   L.rock_type,
            "hardness":    float(L.hardness),
            "age_ma":      float(L.age_ma),
            "color_rgb":   list(L.color_rgb),
            "thickness_m": float(L.thickness_m),
            "dip_deg":     float(np.degrees(L.dip_rad)),
            "strike_deg":  float(np.degrees(L.strike_angle_rad)),
        })

    # Per-cell surface material_id
    if strat_stack.layers:
        thicks = np.array([L.thickness_m for L in strat_stack.layers], dtype=np.float64)
        bounds = np.concatenate(([0.0], np.cumsum(thicks)))
        z = (h - strat_stack.base_elevation_m).clip(min=0.0)
        idx = np.searchsorted(bounds, z, side="right") - 1
        surface_mat_id = np.clip(idx, 0, len(strat_stack.layers) - 1).astype(np.int32)
    else:
        surface_mat_id = np.zeros(h.shape, dtype=np.int32)

    cross_section = {
        "layer_table": layer_table,
        "surface_material_id": surface_mat_id.tolist(),
        "tile_metadata": {
            "tile_size":     stack.tile_size,
            "cell_size":     stack.cell_size,
            "world_origin_x": stack.world_origin_x,
            "world_origin_y": stack.world_origin_y,
            "tile_x":        stack.tile_x,
            "tile_y":        stack.tile_y,
        },
    }

    # Store as object-array channel so the standard channel mechanism holds it
    wrapper = np.empty((1,), dtype=object)
    wrapper[0] = cross_section
    stack.set("strata_cross_section", wrapper, "stratigraphy")

    return cross_section


# ---------------------------------------------------------------------------
# Pass
# ---------------------------------------------------------------------------


# Built-in material table with full geological attributes.
# Each entry: (hardness, rock_type, age_ma, color_rgb)
_MATERIAL_TABLE: Dict[str, Tuple[float, str, float, Tuple[float, float, float]]] = {
    "soil":               (0.10, "sedimentary",  0.0,    (0.50, 0.38, 0.25)),
    "peat":               (0.08, "sedimentary",  0.0,    (0.22, 0.18, 0.10)),
    "gravel":             (0.18, "sedimentary",  1.0,    (0.62, 0.58, 0.50)),
    "mudstone":           (0.20, "sedimentary",  5.0,    (0.42, 0.36, 0.28)),
    "shale":              (0.25, "sedimentary", 30.0,    (0.35, 0.32, 0.28)),
    "chalk":              (0.30, "sedimentary", 80.0,    (0.92, 0.92, 0.88)),
    "siltstone":          (0.40, "sedimentary", 60.0,    (0.55, 0.50, 0.38)),
    "sandstone":          (0.55, "sedimentary", 150.0,   (0.82, 0.68, 0.45)),
    "limestone":          (0.75, "sedimentary", 200.0,   (0.85, 0.85, 0.78)),
    "dolomite":           (0.80, "sedimentary", 300.0,   (0.80, 0.78, 0.65)),
    "marble":             (0.82, "metamorphic", 400.0,   (0.95, 0.93, 0.90)),
    "quartzite":          (0.88, "metamorphic", 500.0,   (0.90, 0.88, 0.80)),
    "slate":              (0.60, "metamorphic", 350.0,   (0.38, 0.40, 0.42)),
    "schist":             (0.65, "metamorphic", 450.0,   (0.55, 0.52, 0.50)),
    "gneiss":             (0.80, "metamorphic", 600.0,   (0.60, 0.58, 0.55)),
    "basalt":             (0.88, "igneous",     100.0,   (0.22, 0.22, 0.24)),
    "dolerite":           (0.88, "igneous",     100.0,   (0.28, 0.28, 0.30)),
    "gabbro":             (0.90, "igneous",     200.0,   (0.30, 0.30, 0.32)),
    "granite":            (0.95, "igneous",     350.0,   (0.78, 0.70, 0.65)),
    "rhyolite":           (0.82, "igneous",      80.0,   (0.80, 0.72, 0.68)),
    # Convenience aliases
    "limestone_caprock":  (0.90, "sedimentary", 200.0,   (0.88, 0.86, 0.80)),
    "caprock":            (0.90, "sedimentary", 200.0,   (0.85, 0.82, 0.75)),
    "bedrock":            (0.95, "igneous",     500.0,   (0.45, 0.43, 0.40)),
}


def _default_strat_stack_from_hints(
    hints: dict,
    *,
    rng: Optional[np.random.Generator] = None,
) -> StratigraphyStack:
    """Build a stratigraphic stack from ``composition_hints``.

    Reads the following keys (all optional):

    ``stratigraphy_layers``
        List of dicts, each matching :class:`StratigraphyLayer` kwargs.
        When present, these layers are used verbatim.

    ``strata_spacing``
        Uniform layer thickness in metres applied when ``strata_materials``
        is provided but individual thicknesses are not specified.
        Default: 30.0 m.

    ``strata_materials``
        Ordered list of material descriptors (bottom → top).  Each entry
        may be:

        * A string name — looked up in the built-in material table below.
        * A dict with at least ``"name"`` and optionally ``"hardness"``,
          ``"thickness_m"``, ``"rock_type"``, ``"age_ma"``, ``"color_rgb"``,
          ``"strike_angle_rad"``.

        Supported name tokens (case-insensitive): see ``_MATERIAL_TABLE``.

    ``stratigraphy_base_elevation_m``
        World-Z elevation of the base of the stack.  Default: ``-50.0``.

    ``strata_dip_variation_rad``
        Maximum random dip variation (±) applied per layer.  Default 0.087
        rad (±5°) as specified for AAA strata simulation.

    If none of the above are supplied, the function falls back to a
    canonical dark-fantasy 7-layer column (shale → mudstone → sandstone →
    siltstone → limestone → gneiss cap → soil overburden) that exercises
    all three rock types across a geologically plausible depth sequence.
    """
    if rng is None:
        rng = np.random.default_rng(42)

    base = float(hints.get("stratigraphy_base_elevation_m", -50.0))
    dip_variation = float(hints.get("strata_dip_variation_rad", 0.087))  # ±5°

    # --- Explicit layer list wins outright --------------------------------
    user_layers = hints.get("stratigraphy_layers")
    if user_layers:
        layers = [StratigraphyLayer(**L) for L in user_layers]
        return StratigraphyStack(base_elevation_m=base, layers=layers)

    # --- strata_materials + strata_spacing --------------------------------
    strata_materials = hints.get("strata_materials")
    if strata_materials:
        spacing = float(hints.get("strata_spacing", 30.0))
        if spacing <= 0.0:
            spacing = 30.0
        layers: List[StratigraphyLayer] = []
        for i, mat in enumerate(strata_materials):
            if isinstance(mat, str):
                name = mat
                entry = _MATERIAL_TABLE.get(name.lower())
                hardness  = entry[0] if entry else 0.5
                rock_type = entry[1] if entry else "sedimentary"
                age_ma    = entry[2] if entry else float(i * 50)
                color_rgb = entry[3] if entry else (0.5, 0.5, 0.5)
                thickness = spacing
            elif isinstance(mat, dict):
                name = mat.get("name", f"layer_{i}")
                entry = _MATERIAL_TABLE.get(name.lower())
                hardness  = float(mat.get("hardness",
                                  entry[0] if entry else 0.5))
                rock_type = mat.get("rock_type",
                                    entry[1] if entry else "sedimentary")
                age_ma    = float(mat.get("age_ma",
                                  entry[2] if entry else float(i * 50)))
                raw_rgb   = mat.get("color_rgb",
                                    entry[3] if entry else (0.5, 0.5, 0.5))
                color_rgb = tuple(float(c) for c in raw_rgb[:3])
                thickness = float(mat.get("thickness_m", spacing))
                strike    = float(mat.get("strike_angle_rad", 0.0))
            else:
                continue

            # ±5° dip noise per layer (geologically plausible)
            dip_noise = float(rng.uniform(-dip_variation, dip_variation))

            layers.append(
                StratigraphyLayer(
                    layer_id=name,
                    hardness=hardness,
                    thickness_m=thickness,
                    dip_rad=dip_noise,
                    azimuth_rad=float(rng.uniform(0.0, 2.0 * np.pi)),
                    rock_type=rock_type,
                    age_ma=age_ma,
                    color_rgb=color_rgb,
                    strike_angle_rad=(
                        strike if isinstance(mat, dict) else
                        float(rng.uniform(0.0, np.pi))
                    ),
                )
            )
        if layers:
            return StratigraphyStack(base_elevation_m=base, layers=layers)

    # --- Fallback: canonical dark-fantasy 7-layer column -----------------
    # N=7 hits the AAA requirement of 5-9 layers; covers sedimentary,
    # metamorphic, and igneous rock types for VeilBreakers dark aesthetic.
    dip_fn = lambda: float(rng.uniform(-dip_variation, dip_variation))
    az_fn  = lambda: float(rng.uniform(0.0, 2.0 * np.pi))
    str_fn = lambda: float(rng.uniform(0.0, np.pi))

    return StratigraphyStack(
        base_elevation_m=base,
        layers=[
            # Oldest / deepest: ancient igneous basement
            StratigraphyLayer(
                "ancient_granite", hardness=0.95, thickness_m=50.0,
                dip_rad=dip_fn(), azimuth_rad=az_fn(),
                rock_type="igneous", age_ma=600.0,
                color_rgb=(0.72, 0.62, 0.55), strike_angle_rad=str_fn(),
            ),
            # Metamorphic basement uplift
            StratigraphyLayer(
                "gneiss_basement", hardness=0.80, thickness_m=40.0,
                dip_rad=dip_fn(), azimuth_rad=az_fn(),
                rock_type="metamorphic", age_ma=450.0,
                color_rgb=(0.58, 0.55, 0.50), strike_angle_rad=str_fn(),
            ),
            # Carbonate platform (soluble, karst-prone)
            StratigraphyLayer(
                "limestone", hardness=0.75, thickness_m=35.0,
                dip_rad=dip_fn(), azimuth_rad=az_fn(),
                rock_type="sedimentary", age_ma=280.0,
                color_rgb=(0.88, 0.86, 0.80), strike_angle_rad=str_fn(),
            ),
            # Clastic shelf sequence
            StratigraphyLayer(
                "sandstone", hardness=0.55, thickness_m=30.0,
                dip_rad=dip_fn(), azimuth_rad=az_fn(),
                rock_type="sedimentary", age_ma=200.0,
                color_rgb=(0.82, 0.68, 0.45), strike_angle_rad=str_fn(),
            ),
            # Fine-grained marine shale
            StratigraphyLayer(
                "shale", hardness=0.25, thickness_m=25.0,
                dip_rad=dip_fn(), azimuth_rad=az_fn(),
                rock_type="sedimentary", age_ma=150.0,
                color_rgb=(0.35, 0.32, 0.28), strike_angle_rad=str_fn(),
            ),
            # Hard resistant caprock (resistant to erosion → mesa/butte formation)
            StratigraphyLayer(
                "limestone_caprock", hardness=0.90, thickness_m=20.0,
                dip_rad=dip_fn(), azimuth_rad=az_fn(),
                rock_type="sedimentary", age_ma=80.0,
                color_rgb=(0.90, 0.88, 0.82), strike_angle_rad=str_fn(),
            ),
            # Youngest / shallowest: surface overburden
            StratigraphyLayer(
                "soil", hardness=0.10, thickness_m=200.0,
                dip_rad=0.0, azimuth_rad=0.0,
                rock_type="sedimentary", age_ma=0.1,
                color_rgb=(0.50, 0.38, 0.25), strike_angle_rad=0.0,
            ),
        ],
    )


def pass_stratigraphy(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle I pass: full geological stratigraphy simulation.

    Executes in sequence:
      1. Build stratigraphic column from composition_hints (N=5-9 layers,
         full rock attributes).
      2. Compute per-cell rock hardness + bedding-plane orientation.
      3. Apply Fourier fold deformation to height.
      4. Apply hardness-coupled differential erosion (h -= depth*(1-hardness)).
      5. Detect angular unconformities → unconformity_mask.
      6. Simulate igneous dikes/intrusions → intrusion_mask + albedo_shift_rgb.
      7. Export strata cross-section JSON → strata_cross_section.

    Consumes: height
    Produces: rock_hardness, strata_orientation, strat_erosion_delta,
              unconformity_mask, intrusion_mask, albedo_shift_rgb,
              strata_cross_section
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: List[ValidationIssue] = []

    hints = dict(state.intent.composition_hints) if state.intent else {}

    # Derive a deterministic seed for this pass
    seed = int(state.intent.seed) if state.intent else 0
    rng = np.random.default_rng(seed ^ 0x53747261)  # XOR with "Stra"

    # --- 1. Build stratigraphic column ------------------------------------
    strat_stack = _default_strat_stack_from_hints(hints, rng=rng)

    # --- 2. Rock hardness + orientation -----------------------------------
    hardness = compute_rock_hardness(stack, strat_stack)
    strata_orient = compute_strata_orientation(stack, strat_stack)
    stack.set("rock_hardness", hardness, "stratigraphy")
    stack.set("strata_orientation", strata_orient, "stratigraphy")

    # --- 3. Fourier fold deformation -------------------------------------
    fold_enabled = bool(hints.get("fold_enabled", True))
    fold_delta: Optional[np.ndarray] = None
    if fold_enabled:
        fold_amplitude  = hints.get("fold_amplitude_m")
        fold_wavelength = hints.get("fold_wavelength_m")
        fold_phase      = hints.get("fold_phase_rad")
        fold_delta = simulate_fold_deformation(
            stack, strat_stack,
            rng=np.random.default_rng(seed ^ 0x466F6C64),  # XOR "Fold"
            amplitude_m=float(fold_amplitude) if fold_amplitude is not None else None,
            wavelength_m=float(fold_wavelength) if fold_wavelength is not None else None,
            phase_rad=float(fold_phase) if fold_phase is not None else None,
        )
        # Re-compute hardness after fold (elevation bands have shifted)
        hardness = compute_rock_hardness(stack, strat_stack)
        stack.set("rock_hardness", hardness, "stratigraphy")

    # --- 4. Hardness-coupled differential erosion -------------------------
    max_erosion_frac   = float(hints.get("erosion_max_fraction", 0.12))
    undercut_strength  = float(hints.get("erosion_undercutting_strength", 0.4))

    erosion_delta = apply_differential_erosion(
        stack,
        strat_stack=strat_stack,
        max_erosion_fraction=max_erosion_frac,
        undercutting_strength=undercut_strength,
    )
    stack.set("strat_erosion_delta", erosion_delta, "stratigraphy")

    # --- 5. Unconformity detection ----------------------------------------
    unconformity_mask = detect_unconformities(stack, strat_stack, erosion_delta)

    # --- 6. Igneous intrusions / dikes -----------------------------------
    intrusion_enabled = bool(hints.get("intrusions_enabled", True))
    if intrusion_enabled:
        n_int = int(hints.get("intrusion_count", 3))
        w_min = float(hints.get("intrusion_width_min_m", 0.5))
        w_max = float(hints.get("intrusion_width_max_m", 5.0))
        iron_strength = float(hints.get("intrusion_iron_stain", 0.3))
        simulate_intrusions(
            stack, strat_stack,
            rng=np.random.default_rng(seed ^ 0x44696B65),  # XOR "Dike"
            n_intrusions=n_int,
            width_range_m=(w_min, w_max),
            albedo_iron_stain_strength=iron_strength,
        )

    # --- 7. Strata cross-section JSON export ------------------------------
    cross_section = export_strata_cross_section(stack, strat_stack)

    # --- Metrics ----------------------------------------------------------
    unconformity_frac = float(unconformity_mask.mean()) if unconformity_mask is not None else 0.0
    intrusion_mask_arr = stack.get("intrusion_mask")
    intrusion_coverage = float(intrusion_mask_arr.mean()) if intrusion_mask_arr is not None else 0.0

    metrics = {
        "layer_count":              len(strat_stack.layers),
        "rock_types":               list({L.rock_type for L in strat_stack.layers}),
        "age_range_ma":             [
            float(min(L.age_ma for L in strat_stack.layers)),
            float(max(L.age_ma for L in strat_stack.layers)),
        ],
        "hardness_mean":            float(hardness.mean()),
        "hardness_min":             float(hardness.min()),
        "hardness_max":             float(hardness.max()),
        "strata_total_thickness_m": float(strat_stack.total_thickness()),
        "erosion_delta_mean_m":     float(erosion_delta.mean()),
        "erosion_delta_min_m":      float(erosion_delta.min()),
        "erosion_max_fraction":     max_erosion_frac,
        "undercutting_strength":    undercut_strength,
        "fold_applied":             fold_enabled and fold_delta is not None,
        "fold_delta_max_m":         float(fold_delta.max()) if fold_delta is not None else 0.0,
        "unconformity_fraction":    unconformity_frac,
        "intrusion_coverage":       intrusion_coverage,
        "cross_section_layers":     len(cross_section["layer_table"]),
    }

    return PassResult(
        pass_name="stratigraphy",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=(
            "rock_hardness",
            "strata_orientation",
            "strat_erosion_delta",
            "unconformity_mask",
            "intrusion_mask",
            "albedo_shift_rgb",
            "strata_cross_section",
        ),
        metrics=metrics,
        issues=issues,
    )


__all__ = [
    "StratigraphyLayer",
    "StratigraphyStack",
    "compute_strata_orientation",
    "compute_rock_hardness",
    "apply_differential_erosion",
    "simulate_fold_deformation",
    "detect_unconformities",
    "simulate_intrusions",
    "export_strata_cross_section",
    "pass_stratigraphy",
]

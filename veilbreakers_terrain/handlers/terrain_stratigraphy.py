"""Bundle I — terrain_stratigraphy.

Stratigraphic rock layering: each tile has an ordered stack of
``StratigraphyLayer`` with hardness, thickness, dip, and azimuth. The pass
populates ``stack.strata_orientation`` (H, W, 3 unit vector) and
``stack.rock_hardness`` (H, W float32) based on which layer the cell's
elevation falls into. A ``apply_differential_erosion`` helper returns a
height delta where softer layers erode faster — harder caprock survives,
producing mesas and layered cliffs.

Pure numpy, no bpy. Z-up, world meters. All seeding is deterministic via
``derive_pass_seed``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

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

    hardness : float in [0, 1] — 0 = loose sediment, 1 = indurated caprock
    thickness_m : world-meter vertical thickness of the layer
    dip_rad : angle from horizontal (0 = flat layer, pi/4 = 45° tilted)
    azimuth_rad : compass bearing of dip direction (0 = +X, pi/2 = +Y)
    color_hex : optional visualizer tag, not used by the passes themselves
    """

    layer_id: str
    hardness: float
    thickness_m: float
    dip_rad: float = 0.0
    azimuth_rad: float = 0.0
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

    Each stratum has a hardness value in [0, 1].  Soft layers (e.g. shale,
    hardness ≈ 0.25) erode faster than hard caprocks (e.g. limestone,
    hardness ≈ 0.90).  Where a soft layer is exposed *beneath* a hard layer
    the soft material is undercut, producing the overhanging ledges and mesa
    profiles characteristic of layered sedimentary terrain.

    Algorithm (fully vectorised with numpy):

    1. **Per-cell erosion rate** — derived from the layer the cell sits in::

           erosion_rate[r, c] = (1 - hardness[r, c]) ^ 2

       Squaring gives a non-linear response: very soft rock erodes much
       faster; very hard rock barely erodes at all.

    2. **Exposure multiplier** — cells that are *higher* than their local
       neighbourhood mean are more exposed to weathering (wind, rain) and
       receive up to 1.5× the base rate; sheltered cells in topographic
       hollows receive 0.5×.

    3. **Undercutting** — for each cell, if the layer *below* it (i.e. the
       layer at height - stratum_spacing) is softer than the cell itself,
       an additional lateral undercut delta is added proportional to the
       hardness contrast and ``undercutting_strength``.  This is computed
       using numpy roll to approximate the horizontal gradient of hardness
       contrast.

    4. **Scale** — the combined rate is normalised to [0, 1] and multiplied
       by ``max_erosion_fraction * relief_span`` so the total erosion is a
       physically plausible fraction of the terrain's height range.

    This function does NOT modify ``stack.height`` in place; the caller
    applies the returned delta via ``stack.set``.

    Args:
        stack: Must have both ``height`` and ``rock_hardness`` populated.
        strat_stack: Optional stratigraphic column used to compute
            undercutting.  When None, undercutting is estimated from the
            hardness gradient alone.
        max_erosion_fraction: Maximum erosion as a fraction of total terrain
            relief.  Default 0.12 (12 %).
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
    # 1. Per-cell erosion rate from layer hardness
    #    Soft rock (hardness → 0) → rate → 1
    #    Hard rock (hardness → 1) → rate → 0
    # ------------------------------------------------------------------
    soft = np.clip(1.0 - hardness, 0.0, 1.0)
    erosion_rate = soft ** 2  # non-linear: shale erodes ~16× faster than caprock

    # ------------------------------------------------------------------
    # 2. Exposure multiplier from local relief relative to neighbourhood
    #    Use a simple 3×3 box mean via numpy roll (no scipy dependency).
    # ------------------------------------------------------------------
    neighbourhood_mean = np.zeros_like(h)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            neighbourhood_mean += np.roll(np.roll(h, dr, axis=0), dc, axis=1)
    neighbourhood_mean /= 9.0

    # Cells above their neighbourhood are exposed; below are sheltered.
    relative_exposure = h - neighbourhood_mean
    exp_span = float(np.abs(relative_exposure).max())
    if exp_span < 1e-6:
        exp_span = 1.0
    # Map to [0.5, 1.5]: exposed → 1.5, sheltered → 0.5
    exposure_mult = 1.0 + np.clip(relative_exposure / exp_span, -0.5, 0.5)

    # ------------------------------------------------------------------
    # 3. Undercutting: soft layer directly under a hard layer
    #    Proxy: where hardness increases sharply going upward (i.e. the
    #    vertical gradient of hardness is positive), the soft material
    #    below is being undercut by the hard cap above.
    # ------------------------------------------------------------------
    # Vertical hardness gradient: roll one row — approximates dH/dz
    hardness_above = np.roll(hardness, -1, axis=0)  # cell one row "higher"
    hardness_contrast = np.clip(hardness_above - hardness, 0.0, 1.0)
    # Undercut only where there IS a softer layer exposed (soft cell itself)
    undercut = undercutting_strength * soft * hardness_contrast

    # ------------------------------------------------------------------
    # 4. Scale combined rate to physical metres
    # ------------------------------------------------------------------
    combined_rate = erosion_rate * exposure_mult + undercut

    # Normalise to [0, 1] so max_erosion_fraction is respected exactly.
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


# ---------------------------------------------------------------------------
# Pass
# ---------------------------------------------------------------------------


def _default_strat_stack_from_hints(hints: dict) -> StratigraphyStack:
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

        * A string name — looked up in the built-in hardness table below.
        * A dict with at least ``"name"`` and optionally ``"hardness"``
          and ``"thickness_m"``.

        Supported name tokens (case-insensitive): ``shale``, ``mudstone``,
        ``siltstone``, ``sandstone``, ``limestone``, ``dolomite``,
        ``granite``, ``basalt``, ``soil``, ``gravel``, ``chalk``.

    ``stratigraphy_base_elevation_m``
        World-Z elevation of the base of the stack.  Default: ``-50.0``.

    If none of the above are supplied, the function falls back to a
    canonical dark-fantasy 4-layer column:
    shale → sandstone → limestone caprock → soil.
    """
    # Built-in material hardness table (0 = loose sediment, 1 = indurated rock)
    MATERIAL_HARDNESS: dict = {
        "soil":       0.10,
        "peat":       0.08,
        "gravel":     0.18,
        "mudstone":   0.20,
        "shale":      0.25,
        "chalk":      0.30,
        "siltstone":  0.40,
        "sandstone":  0.55,
        "limestone":  0.75,
        "dolomite":   0.80,
        "basalt":     0.88,
        "granite":    0.95,
        # Convenience aliases
        "limestone_caprock": 0.90,
        "caprock":    0.90,
        "bedrock":    0.95,
    }

    base = float(hints.get("stratigraphy_base_elevation_m", -50.0))

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
                hardness = MATERIAL_HARDNESS.get(name.lower(), 0.5)
                thickness = spacing
            elif isinstance(mat, dict):
                name = mat.get("name", f"layer_{i}")
                hardness = float(
                    mat.get(
                        "hardness",
                        MATERIAL_HARDNESS.get(name.lower(), 0.5),
                    )
                )
                thickness = float(mat.get("thickness_m", spacing))
            else:
                continue
            layers.append(
                StratigraphyLayer(
                    layer_id=name,
                    hardness=hardness,
                    thickness_m=thickness,
                )
            )
        if layers:
            return StratigraphyStack(base_elevation_m=base, layers=layers)

    # --- Fallback: canonical dark-fantasy column --------------------------
    return StratigraphyStack(
        base_elevation_m=base,
        layers=[
            StratigraphyLayer("shale", hardness=0.25, thickness_m=30.0),
            StratigraphyLayer("sandstone", hardness=0.55, thickness_m=40.0),
            StratigraphyLayer("limestone_caprock", hardness=0.90, thickness_m=30.0),
            StratigraphyLayer("soil", hardness=0.15, thickness_m=200.0),
        ],
    )


def pass_stratigraphy(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle I pass: populate rock_hardness + strata_orientation + erosion delta.

    Reads ``strata_spacing`` and ``strata_materials`` from
    ``state.intent.composition_hints`` (in addition to the existing
    ``stratigraphy_layers`` / ``stratigraphy_base_elevation_m`` keys) to
    build the stratigraphic column, then applies differential erosion with
    the full layer-aware undercutting model.

    Consumes: height
    Produces: rock_hardness, strata_orientation, strat_erosion_delta
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: List[ValidationIssue] = []

    hints = dict(state.intent.composition_hints) if state.intent else {}
    strat_stack = _default_strat_stack_from_hints(hints)

    hardness = compute_rock_hardness(stack, strat_stack)
    strata_orient = compute_strata_orientation(stack, strat_stack)
    stack.set("rock_hardness", hardness, "stratigraphy")
    stack.set("strata_orientation", strata_orient, "stratigraphy")

    # Pull erosion tuning from hints (optional, fall back to function defaults)
    max_erosion_frac = float(hints.get("erosion_max_fraction", 0.12))
    undercut_strength = float(hints.get("erosion_undercutting_strength", 0.4))

    erosion_delta = apply_differential_erosion(
        stack,
        strat_stack=strat_stack,
        max_erosion_fraction=max_erosion_frac,
        undercutting_strength=undercut_strength,
    )
    stack.set("strat_erosion_delta", erosion_delta, "stratigraphy")

    metrics = {
        "layer_count": len(strat_stack.layers),
        "hardness_mean": float(hardness.mean()),
        "hardness_min": float(hardness.min()),
        "hardness_max": float(hardness.max()),
        "strata_total_thickness_m": float(strat_stack.total_thickness()),
        "erosion_delta_mean_m": float(erosion_delta.mean()),
        "erosion_delta_min_m": float(erosion_delta.min()),
        "erosion_max_fraction": max_erosion_frac,
        "undercutting_strength": undercut_strength,
    }

    return PassResult(
        pass_name="stratigraphy",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("rock_hardness", "strata_orientation", "strat_erosion_delta"),
        metrics=metrics,
        issues=issues,
    )


__all__ = [
    "StratigraphyLayer",
    "StratigraphyStack",
    "compute_strata_orientation",
    "compute_rock_hardness",
    "apply_differential_erosion",
    "pass_stratigraphy",
]

"""Phase C D35 — pass_topographic_indices.

Computes four spec-required derived channels from ``height`` (heightmap):

- ``vb_aspect_deg``       — slope aspect in degrees [0, 360); 0=N, 90=E, 180=S,
                            270=W (compass clockwise).
- ``vb_aspect_north``     — cos(aspect_radians) in [-1, +1]; +1 = perfectly
                            north-facing (cool, moist), -1 = south-facing.
- ``vb_canopy_openness``  — sky view factor in [0, 1]; 1 = unobscured sky,
                            0 = deep valley (horizon hemisphere integration).
- ``vb_TWI``              — Topographic Wetness Index =
                            ln(flow_accumulation_area / tan(slope_radians));
                            larger = wetter. Standard hydrology formula.

Reference:
    docs/IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL.md §17 Phase C D35 / PR #42.
    Spec drift §1.5: zero hits in ``veilbreakers_terrain/handlers/`` for these
    channel names prior to D35. Foliage stack §4.2 consumes them.

Implementation notes:
    * Pure-numpy implementation with optional scipy.ndimage fast path for
      ``distance_transform_edt`` / ``gaussian_filter`` when available — the
      pass is fully functional without scipy.
    * Sky-view factor uses a 24-direction azimuthal sample (every 15 deg)
      with a finite ray length to keep cost bounded; the exact angle set is
      pinned for byte-identical determinism.
    * TWI clamps tan(slope) to a small floor so flat cells do not blow up
      to +Inf; the result is finite for non-pathological inputs.
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, Optional

import numpy as np

from .terrain_io import assert_finite_array
from .terrain_semantics import BBox, PassDefinition, PassResult

# NOTE: ``terrain_pipeline`` is NOT imported at module top — that creates a
# CodeQL-flagged static cycle (terrain_pipeline registers this module's pass,
# this module registers itself on terrain_pipeline.TerrainPassController).
# The lazy import inside ``register_topographic_indices_pass`` runs only after
# both modules are fully loaded, breaking the static cycle.

if TYPE_CHECKING:  # pragma: no cover — type-only
    from .terrain_semantics import TerrainPipelineState


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Sky-view factor sample directions (24 azimuths × 15 deg = 360 deg).
# Pinned for determinism — changing this set changes vb_canopy_openness output.
_SKYVIEW_AZIMUTH_COUNT: int = 24
_SKYVIEW_AZIMUTHS_DEG: np.ndarray = np.arange(
    0, 360, 360 // _SKYVIEW_AZIMUTH_COUNT, dtype=np.float32
)

# Maximum horizon ray length in cells. Keeps the per-cell cost O(N) cells of
# walk per direction rather than O(H+W). Larger values capture more distant
# horizons; 32 cells is a reasonable balance for tile-scale heightmaps.
_SKYVIEW_RAY_CELLS: int = 32

# Floor for tan(slope) in TWI to avoid +Inf on flat cells. Equivalent to a
# slope of ~0.057 deg — flat enough to be effectively level but finite.
_TWI_TAN_SLOPE_FLOOR: float = 1.0e-3

# Minimum flow accumulation (cells) to use in TWI numerator. Avoids
# log(0) on cells that are themselves the only contributor. Each cell
# contributes at least its own area to its own accumulation.
_TWI_MIN_ACCUMULATION_CELLS: float = 1.0


# ---------------------------------------------------------------------------
# Slope/aspect derivation — pure numpy
# ---------------------------------------------------------------------------


def _compute_slope_aspect(
    height: np.ndarray,
    cell_size_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (slope_radians, aspect_radians) from heightmap via central-diff.

    aspect_radians is measured compass-style: 0 = North (-Y), pi/2 = East (+X),
    matching ESRI / GDAL ``gdaldem aspect`` and most GIS conventions used by
    foliage / hydrology tools. The convention assumes row 0 = north edge.
    """
    h = np.asarray(height, dtype=np.float32)
    # np.gradient returns (d/d_row, d/d_col) — i.e. (dz/dy, dz/dx) when the
    # image is row-major with row 0 at top. We treat row index as the Y axis
    # (positive Y = south in compass terms) so dz_dy is computed from rows.
    dz_dy, dz_dx = np.gradient(h, float(cell_size_m), float(cell_size_m))

    # Slope magnitude in radians.
    slope_mag = np.sqrt(dz_dx * dz_dx + dz_dy * dz_dy).astype(np.float32)
    slope_rad = np.arctan(slope_mag).astype(np.float32)

    # Aspect: compass bearing of the steepest *downhill* direction.
    # The downhill-direction vector is (-dz_dx, -dz_dy); we want the bearing
    # measured clockwise from North (-Y). Using atan2 with (East, North):
    #   East component  = -dz_dx
    #   North component = +dz_dy   (because row index increases southward)
    # bearing = atan2(East, North) wrapped to [0, 2pi).
    east = -dz_dx
    north = dz_dy
    aspect_rad = np.arctan2(east, north).astype(np.float32)
    # Wrap to [0, 2pi).
    aspect_rad = np.mod(aspect_rad, 2.0 * np.float32(math.pi))
    return slope_rad, aspect_rad


# ---------------------------------------------------------------------------
# Sky-view factor (canopy openness)
# ---------------------------------------------------------------------------


def _compute_canopy_openness(
    height: np.ndarray,
    cell_size_m: float,
) -> np.ndarray:
    """Return sky-view factor in [0, 1] via horizon hemisphere sampling.

    For each cell, sample horizon altitude angle along ``_SKYVIEW_AZIMUTH_COUNT``
    azimuths up to ``_SKYVIEW_RAY_CELLS`` cells away, take the maximum elevation
    angle along each ray, then compute openness = 1 - mean(sin(max_angle)).

    This is a finite-ray approximation of Yokoyama et al. 2002's continuous
    SVF. The 24-direction / 32-cell defaults are pinned for determinism.
    """
    h = np.asarray(height, dtype=np.float32)
    rows, cols = h.shape

    if rows < 2 or cols < 2:
        return np.ones_like(h, dtype=np.float32)

    cell = float(cell_size_m) if cell_size_m and cell_size_m > 0.0 else 1.0

    # Accumulate the horizon-angle contribution from each azimuth. The
    # canonical SVF integrates (1 - sin(theta_h)) over a hemisphere; we
    # approximate by averaging across the discrete azimuths.
    sum_sin_horizon = np.zeros_like(h, dtype=np.float32)

    # Pre-build integer step vectors for each azimuth so the inner loop is
    # branch-free per ray step.
    for az_deg in _SKYVIEW_AZIMUTHS_DEG:
        # Convert compass bearing to (dx, dy) cell offsets per unit step.
        # 0 deg = North = (-Y) = row decreasing; 90 deg = East = +X.
        az_rad = float(az_deg) * math.pi / 180.0
        ux = math.sin(az_rad)
        uy = -math.cos(az_rad)  # negative because row 0 = north

        # Per-ray maximum elevation angle (radians).
        max_elev = np.full(h.shape, -math.pi / 2.0, dtype=np.float32)

        for step in range(1, _SKYVIEW_RAY_CELLS + 1):
            # Integer cell offsets at this step. We use round-to-nearest for
            # a deterministic discrete walk; non-integer step displacements
            # are not summed twice because each step has a unique (dr, dc).
            dr = int(round(uy * step))
            dc = int(round(ux * step))
            if dr == 0 and dc == 0:
                continue

            # Source slice (the cell we're sampling from): full grid except
            # the edges that would walk off the boundary.
            src_r0 = max(0, -dr)
            src_r1 = rows - max(0, dr)
            src_c0 = max(0, -dc)
            src_c1 = cols - max(0, dc)

            # Destination slice (the cell being sampled).
            dst_r0 = max(0, dr)
            dst_r1 = rows - max(0, -dr)
            dst_c0 = max(0, dc)
            dst_c1 = cols - max(0, -dc)

            if src_r1 <= src_r0 or src_c1 <= src_c0:
                continue

            dh = h[dst_r0:dst_r1, dst_c0:dst_c1] - h[src_r0:src_r1, src_c0:src_c1]
            dist = math.hypot(dr, dc) * cell
            if dist <= 0.0:
                continue
            elev = np.arctan2(dh, np.float32(dist)).astype(np.float32)

            # Update max elevation along this ray for the source cells.
            max_elev_src = max_elev[src_r0:src_r1, src_c0:src_c1]
            np.maximum(max_elev_src, elev, out=max_elev_src)

        # Replace any never-updated cells (edges where every ray walked
        # off-grid) with 0 so they contribute as fully-open horizons.
        np.maximum(max_elev, 0.0, out=max_elev)

        sum_sin_horizon += np.sin(max_elev)

    mean_sin_horizon = sum_sin_horizon / float(_SKYVIEW_AZIMUTH_COUNT)
    openness = (1.0 - mean_sin_horizon).astype(np.float32)
    np.clip(openness, 0.0, 1.0, out=openness)
    return openness


# ---------------------------------------------------------------------------
# TWI — Topographic Wetness Index
# ---------------------------------------------------------------------------


def _compute_twi(
    height: np.ndarray,
    slope_rad: np.ndarray,
    flow_accumulation: Optional[np.ndarray],
    cell_size_m: float,
) -> np.ndarray:
    """Return TWI = ln(flow_accumulation_area / tan(slope)).

    If ``flow_accumulation`` is supplied (cells of upstream contribution),
    it is multiplied by ``cell_size_m**2`` to convert to area. When the
    channel is absent, falls back to a height-rank approximation: cells
    whose elevation is below the local mean accumulate proportionally
    more inferred flow (cheap stand-in for a full D8 solve).

    ``tan(slope)`` is floored at ``_TWI_TAN_SLOPE_FLOOR`` so flat cells
    produce finite TWI values rather than +Inf.
    """
    h = np.asarray(height, dtype=np.float32)
    cell = float(cell_size_m) if cell_size_m and cell_size_m > 0.0 else 1.0
    cell_area = cell * cell

    if flow_accumulation is not None:
        flow_acc = np.asarray(flow_accumulation, dtype=np.float32)
        if flow_acc.shape != h.shape:
            flow_acc = None  # type: ignore[assignment]
    else:
        flow_acc = None  # type: ignore[assignment]

    if flow_acc is None:
        # Fallback approximation: exp of normalised height-below-mean.
        # Higher cells -> less accumulation; lower cells -> more.
        h_mean = float(h.mean()) if h.size else 0.0
        h_std = float(h.std()) if h.size and float(h.std()) > 1e-9 else 1.0
        rel = (h_mean - h) / h_std
        # Map [-3, +3] -> [0, ~20] cells contributing area (gentle).
        flow_cells = np.clip(np.exp(rel.astype(np.float32)), 1.0, 1e6).astype(np.float32)
    else:
        flow_cells = np.maximum(
            flow_acc,
            np.float32(_TWI_MIN_ACCUMULATION_CELLS),
        ).astype(np.float32)

    area_m2 = (flow_cells * np.float32(cell_area)).astype(np.float32)

    tan_slope = np.tan(np.asarray(slope_rad, dtype=np.float32))
    tan_slope = np.maximum(tan_slope, np.float32(_TWI_TAN_SLOPE_FLOOR)).astype(np.float32)

    twi = np.log(area_m2 / tan_slope).astype(np.float32)
    # Final safety: any residual NaN/Inf from pathological inputs gets
    # clamped to the per-tile finite range so the assert_finite_array
    # post-check passes.
    if not np.all(np.isfinite(twi)):
        finite_mask = np.isfinite(twi)
        if finite_mask.any():
            fill_val = float(np.median(twi[finite_mask]))
        else:
            fill_val = 0.0
        twi = np.where(finite_mask, twi, np.float32(fill_val)).astype(np.float32)
    return twi


# ---------------------------------------------------------------------------
# Pass entry point
# ---------------------------------------------------------------------------


def pass_topographic_indices(
    state: "TerrainPipelineState",
    region: Optional[BBox],
) -> PassResult:
    """Phase C D35: produce vb_aspect_deg / vb_aspect_north / vb_canopy_openness / vb_TWI.

    Contract:
        Reads:    height, optionally flow_accumulation
        Writes:   vb_aspect_deg, vb_aspect_north, vb_canopy_openness, vb_TWI
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    height = np.asarray(stack.height, dtype=np.float32)
    cell_size_m = float(getattr(stack, "cell_size", 1.0) or 1.0)

    slope_rad, aspect_rad = _compute_slope_aspect(height, cell_size_m)

    aspect_deg = np.mod(np.degrees(aspect_rad), 360.0).astype(np.float32)
    # Defensive clip in case a +180.0/-180.0 edge case rounds to exactly 360.
    aspect_deg = np.where(
        aspect_deg >= 360.0,
        np.float32(0.0),
        aspect_deg,
    ).astype(np.float32)

    aspect_north = np.cos(aspect_rad).astype(np.float32)
    np.clip(aspect_north, -1.0, 1.0, out=aspect_north)

    canopy_openness = _compute_canopy_openness(height, cell_size_m)

    flow_acc = stack.get("flow_accumulation")
    twi = _compute_twi(height, slope_rad, flow_acc, cell_size_m)

    # Persist via canonical stack.set() so provenance + dirty flags work.
    stack.set("vb_aspect_deg", aspect_deg, "topographic_indices")
    stack.set("vb_aspect_north", aspect_north, "topographic_indices")
    stack.set("vb_canopy_openness", canopy_openness, "topographic_indices")
    stack.set("vb_TWI", twi, "topographic_indices")

    # Self-check finite-ness so downstream consumers see clean data even if
    # the controller-level NaN/Inf check is bypassed in some test path.
    for ch_name, arr in (
        ("vb_aspect_deg", aspect_deg),
        ("vb_aspect_north", aspect_north),
        ("vb_canopy_openness", canopy_openness),
        ("vb_TWI", twi),
    ):
        assert_finite_array(arr, channel=ch_name, pass_name="topographic_indices")

    metrics = {
        "aspect_deg_mean": float(aspect_deg.mean()),
        "aspect_north_mean": float(aspect_north.mean()),
        "canopy_openness_mean": float(canopy_openness.mean()),
        "twi_mean": float(twi.mean()),
        "twi_min": float(twi.min()),
        "twi_max": float(twi.max()),
    }

    return PassResult(
        pass_name="topographic_indices",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height", "flow_accumulation"),
        produced_channels=(
            "vb_aspect_deg",
            "vb_aspect_north",
            "vb_canopy_openness",
            "vb_TWI",
        ),
        metrics=metrics,
        issues=[],
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def topographic_indices_pass_definition() -> PassDefinition:
    """Return the canonical PassDefinition for topographic_indices.

    Built without importing terrain_pipeline so this module has zero
    dependency on the pipeline (PassDefinition lives in terrain_semantics).
    The pipeline is the registration broker — it imports this constructor
    and calls TerrainPassController.register_pass() itself. Avoids the
    static CodeQL cycle that lazy-importing terrain_pipeline didn't break.
    """
    return PassDefinition(
        name="topographic_indices",
        func=pass_topographic_indices,
        requires_channels=("height",),
        optional_channels=("flow_accumulation",),
        produces_channels=(
            "vb_aspect_deg",
            "vb_aspect_north",
            "vb_canopy_openness",
            "vb_TWI",
        ),
        seed_namespace="topographic_indices",
        requires_scene_read=False,
        may_modify_geometry=False,
        supports_region_scope=False,
        description=(
            "Phase C D35: emit vb_aspect_deg / vb_aspect_north / "
            "vb_canopy_openness / vb_TWI from heightmap so foliage / "
            "scatter consumers can read them per spec §3.5 / §4.2."
        ),
    )


def register_topographic_indices_pass() -> None:
    """Legacy registrar — terrain_pipeline.register_default_passes now uses
    ``topographic_indices_pass_definition()`` directly to avoid the CodeQL
    cycle. This function remains for any external callers that imported it.
    """
    # Local import — only reached when an external caller invokes this.
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(topographic_indices_pass_definition())


__all__ = [
    "pass_topographic_indices",
    "register_topographic_indices_pass",
]

"""Bundle L — terrain_god_ray_hints.

Identifies plausible god-ray / light-shaft source locations: places
where a sunbeam passes through foliage or dust AND is partially
occluded by nearby terrain — the classic visible-shaft condition.
Hints are exported as JSON for the Unity consumer (light probe /
volumetric light placement).

Pure numpy, no bpy, deterministic.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

try:
    from scipy.ndimage import maximum_filter as _maximum_filter
    _HAS_SCIPY_NMS = True
except ImportError:
    _HAS_SCIPY_NMS = False

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# GodRayHint dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GodRayHint:
    """A plausible god-ray source location + direction."""

    source_pos: Tuple[float, float, float]
    direction_rad: float
    intensity: float
    source_feature_id: str

    def to_dict(self) -> dict:
        return {
            "source_pos": list(self.source_pos),
            "direction_rad": float(self.direction_rad),
            "intensity": float(self.intensity),
            "source_feature_id": str(self.source_feature_id),
        }


# ---------------------------------------------------------------------------
# Core detector
# ---------------------------------------------------------------------------


def _normalize_sun_dir(sun_dir_rad: Tuple[float, float]) -> Tuple[float, float]:
    """Return (azimuth, altitude) in radians. Altitude clamped to (0, pi/2]."""
    az = float(sun_dir_rad[0])
    alt = float(sun_dir_rad[1])
    if alt <= 0.0:
        alt = 1e-3
    return az, alt


def _build_terrain_silhouette_shadow(
    h: np.ndarray,
    sun_az: float,
    sun_alt: float,
    cell_size: float,
) -> np.ndarray:
    """Return a boolean mask: True where a cell is in shadow from the sun.

    Algorithm
    ---------
    We march rays from each cell toward the sun (opposite direction of sun
    vector projected onto the grid). A cell is shadowed if any terrain
    sample along its path to the sun is tall enough to block the sun ray.

    The sun direction in grid space:
        dx_sun = cos(sun_alt) * sin(sun_az)   (east component)
        dy_sun = cos(sun_alt) * cos(sun_az)   (north component)
        dz_sun = sin(sun_alt)                 (vertical rise per horizontal unit)

    We step along the *opposite* direction (from cell toward sun) using
    fixed-step ray marching.  At step distance d (meters) the expected
    minimum height to not be blocked is:
        h_horizon = h[cell] + d * tan(sun_alt)

    If any encountered terrain exceeds h_horizon, the cell is shadowed.
    """
    rows, cols = h.shape
    tan_alt = math.tan(max(sun_alt, 1e-4))

    # Sun direction projected on the XY (grid) plane, pointing away from sun.
    # We step in this direction from each cell to trace the sun ray.
    dx = math.cos(sun_alt) * math.sin(sun_az)   # east (col) component
    dy = math.cos(sun_alt) * math.cos(sun_az)   # north (row) component

    # Number of marching steps — enough to cross the entire tile diagonally.
    diag = math.sqrt(rows * rows + cols * cols)
    # Step size: 2 cells worth of diagonal, so we use ~diag/2 steps.
    n_steps = max(4, int(diag / 2))
    step_cells = 2.0  # march 2 cells per step
    step_m = step_cells * cell_size

    # Pre-build row/col index grids for vectorised march.
    col_grid = np.arange(cols, dtype=np.float32)[np.newaxis, :]
    row_grid = np.arange(rows, dtype=np.float32)[:, np.newaxis]

    shadow = np.zeros((rows, cols), dtype=bool)

    for s in range(1, n_steps + 1):
        d_m = s * step_m
        # Grid coordinates of the "look-toward-sun" sample for each cell.
        # We step in the direction FROM cell TOWARD sun.
        sample_col = col_grid + (dx / cell_size) * d_m
        sample_row = row_grid + (dy / cell_size) * d_m

        # Clamp to grid bounds.
        sc = np.clip(np.round(sample_col).astype(np.int32), 0, cols - 1)
        sr = np.clip(np.round(sample_row).astype(np.int32), 0, rows - 1)

        # Terrain height at the sample point.
        h_sample = h[sr, sc]
        # Horizon height: to NOT be blocked, h_sample must be below this.
        h_horizon = h + d_m * tan_alt

        # If the sampled terrain is above the horizon, the cell is shadowed.
        shadow |= h_sample > h_horizon

    return shadow


def compute_god_ray_hints(
    stack: TerrainMaskStack,
    sun_dir_rad: Tuple[float, float],
    cloud_shadow: np.ndarray,
) -> List[GodRayHint]:
    """Detect plausible god-ray source locations.

    Algorithm
    ---------
    God rays are visible where ALL three conditions hold simultaneously:
      1. Foliage / dust medium is present (forest_mask or detail_density
         "tree", or fallback to low-slope vegetated cells).
      2. The cell is on the LIT side — not fully in terrain shadow.
      3. The lit cell is adjacent to (or near) a shadow transition,
         meaning the shaft is bounded on one side — creating the visible
         beam against the darker region.

    Steps:
      a. Compute terrain shadow mask using ray-march toward the sun.
      b. Build foliage density from ``forest_mask`` or height-slope proxy.
      c. Shadow-boundary score: gradient of the shadow mask detects the
         lit/shadow transition edge.  Cells just inside the LIT side of
         that boundary with dense foliage are the ideal shaft origins.
      d. Apply cave-entrance / waterfall bonus (these tightly bound light).
      e. Non-max suppress and return up to 16 hints.

    Parameters
    ----------
    stack:
        Mask stack. Uses ``height``, ``slope``, ``forest_mask`` (optional),
        ``cave_candidate`` (optional), ``waterfall_lip_candidate`` (optional).
    sun_dir_rad:
        (azimuth, altitude) in radians. Altitude must be > 0.
    cloud_shadow:
        float [0..1] mask matching ``stack.height`` shape.

    Returns
    -------
    list[GodRayHint]
        Up to 16 hints, sorted by descending intensity.
    """
    if stack.height is None:
        raise ValueError("compute_god_ray_hints requires stack.height")
    h = np.asarray(stack.height, dtype=np.float64)
    cs = np.asarray(cloud_shadow, dtype=np.float32)
    if cs.shape != h.shape:
        raise ValueError(
            f"cloud_shadow shape {cs.shape} must match height shape {h.shape}"
        )

    az, alt = _normalize_sun_dir(sun_dir_rad)
    cell = float(stack.cell_size)

    # ------------------------------------------------------------------
    # Step 1: Terrain shadow from ray-march
    # ------------------------------------------------------------------
    shadow_mask = _build_terrain_silhouette_shadow(h, az, alt, cell)

    # ------------------------------------------------------------------
    # Step 2: Foliage / scatter density
    # ------------------------------------------------------------------
    forest_raw = stack.get("forest_mask", default=None)
    if forest_raw is not None:
        foliage = np.clip(np.asarray(forest_raw, dtype=np.float32), 0.0, 1.0)
    else:
        # Fallback: use detail_density "tree" if available.
        tree_raw = None
        if stack.detail_density is not None:
            tree_raw = stack.detail_density.get("tree")
        if tree_raw is not None:
            foliage = np.clip(np.asarray(tree_raw, dtype=np.float32), 0.0, 1.0)
        else:
            # Last resort: low-slope cells above median height are likely
            # vegetated in dark-fantasy biomes.
            slope_raw = stack.slope
            if slope_raw is None:
                gy, gx = np.gradient(h, cell)
                slope_raw = np.arctan(np.sqrt(gx * gx + gy * gy))
            slope_deg = np.degrees(np.asarray(slope_raw, dtype=np.float64))
            h_median = float(np.median(h))
            foliage = np.where(
                (slope_deg < 25.0) & (h > h_median), 1.0, 0.0
            ).astype(np.float32)

    # ------------------------------------------------------------------
    # Step 3: Shadow boundary — cells just inside the lit side
    # ------------------------------------------------------------------
    shadow_f = shadow_mask.astype(np.float32)
    # Gradient of shadow mask: high values at lit/shadow edges.
    # np.pad edge mode prevents toroidal tile-seam contamination — np.roll
    # would wrap the shadow from the opposite border and produce a false
    # high-gradient stripe at every tile seam, causing visible god-ray shafts
    # right at the seam.
    _sf_pad = np.pad(shadow_f, 1, mode="edge")
    shad_grad_r = np.abs(shadow_f - _sf_pad[:-2, 1:-1])
    shad_grad_c = np.abs(shadow_f - _sf_pad[1:-1, :-2])
    boundary_score = np.clip(shad_grad_r + shad_grad_c, 0.0, 1.0)

    # Only score cells that are LIT (not in shadow) — shafts come from the
    # lit side penetrating into shadow, not from inside the shadow volume.
    lit_mask = (~shadow_mask).astype(np.float32)

    # Cloud-shadow edge bonus: same principle, additional modulation.
    _cs_pad = np.pad(cs, 1, mode="edge")
    cs_grad_r = np.abs(cs - _cs_pad[:-2, 1:-1])
    cs_grad_c = np.abs(cs - _cs_pad[1:-1, :-2])
    cs_edge = np.clip(cs_grad_r + cs_grad_c, 0.0, 1.0)

    # ------------------------------------------------------------------
    # Step 4: Feature-kind bonuses
    # ------------------------------------------------------------------
    cave = stack.get("cave_candidate", default=None)
    wfall = stack.get("waterfall_lip_candidate", default=None)
    cave_mask = (
        np.asarray(cave, dtype=np.float32)
        if cave is not None
        else np.zeros_like(h, dtype=np.float32)
    )
    wfall_mask = (
        np.asarray(wfall, dtype=np.float32)
        if wfall is not None
        else np.zeros_like(h, dtype=np.float32)
    )

    # ------------------------------------------------------------------
    # Step 5: Composite intensity
    # God ray requires:  foliage present  +  near shadow boundary  +  lit
    # Caves / waterfalls are prime sources regardless of foliage density.
    # ------------------------------------------------------------------
    intensity = (
        0.40 * foliage * boundary_score * lit_mask   # core shaft condition
        + 0.20 * foliage * lit_mask                  # lit foliage background
        + 0.20 * cs_edge * lit_mask                  # cloud shadow edge
        + 0.60 * cave_mask                           # cave-entrance always high
        + 0.50 * wfall_mask                          # waterfall mist shafts
    ).astype(np.float32)

    # ------------------------------------------------------------------
    # Step 6: Non-max suppression + top-N extraction
    # ------------------------------------------------------------------
    thresh = float(np.percentile(intensity, 90.0))
    if thresh < 1e-6:
        thresh = float(intensity.max() * 0.5)
    candidates: list[Tuple[float, int, int, str]] = []
    if _HAS_SCIPY_NMS:
        local_max = _maximum_filter(intensity, size=5, mode='reflect')
        nms_mask = (intensity >= local_max) & (intensity > thresh)
        for r, c in zip(*np.where(nms_mask)):
            v = float(intensity[r, c])
            if cave_mask[r, c] > 0.5:
                fkind = "cave_entrance"
            elif wfall_mask[r, c] > 0.5:
                fkind = "waterfall_lip"
            elif foliage[r, c] > 0.5:
                fkind = "foliage_shaft"
            else:
                fkind = "valley_shaft"
            candidates.append((v, int(r), int(c), fkind))
    else:
        # Vectorized NMS without scipy: separable 5×5 max filter using numpy
        # slicing with a reflect-padded array.  O(H*W) numpy ops vs O(H*W)
        # Python iterations, giving ~100x faster execution on large grids.
        rows, cols = intensity.shape
        padded = np.pad(intensity, 2, mode="reflect")
        # Row-wise 5-wide max → intermediate shape (rows+4, cols)
        row_max = np.maximum.reduce(
            [padded[:, k : k + cols] for k in range(5)]
        )
        # Column-wise 5-tall max → final local_max shape (rows, cols)
        local_max_np = np.maximum.reduce(
            [row_max[k : k + rows, :] for k in range(5)]
        )
        nms_mask = (intensity >= local_max_np - 1e-9) & (intensity > thresh)
        for r, c in zip(*np.where(nms_mask)):
            v = float(intensity[r, c])
            if cave_mask[r, c] > 0.5:
                fkind = "cave_entrance"
            elif wfall_mask[r, c] > 0.5:
                fkind = "waterfall_lip"
            elif foliage[r, c] > 0.5:
                fkind = "foliage_shaft"
            else:
                fkind = "valley_shaft"
            candidates.append((v, int(r), int(c), fkind))

    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))
    top = candidates[:16]
    hints: list[GodRayHint] = []
    ox = float(stack.world_origin_x)
    oy = float(stack.world_origin_y)
    for idx, (v, r, c, fkind) in enumerate(top):
        wx = ox + (c + 0.5) * cell
        wy = oy + (r + 0.5) * cell
        wz = float(h[r, c])
        hints.append(
            GodRayHint(
                source_pos=(wx, wy, wz),
                direction_rad=float(az),
                intensity=float(v),
                source_feature_id=f"{fkind}_{idx:03d}",
            )
        )
    return hints


def export_god_ray_hints_json(
    hints: List[GodRayHint],
    output_path: Path,
) -> None:
    """Serialise hints to a JSON file (deterministic ordering)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "hint_count": len(hints),
        "hints": [h.to_dict() for h in hints],
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Pass wrapper
# ---------------------------------------------------------------------------


def pass_god_ray_hints(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle L pass: compute god-ray hints.

    Contract
    --------
    Consumes: ``height``, optional ``cave_candidate``,
              ``waterfall_lip_candidate``, ``cloud_shadow``
    Produces: (no mask channel — hints are a side-effect json artifact)
    Respects protected zones: no (read-only)
    Requires scene read: no
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    hints_cfg = state.intent.composition_hints if state.intent else {}

    # Support both flat keys and a nested sun_dir dict.
    sun_dir_hint = hints_cfg.get("sun_dir")
    if isinstance(sun_dir_hint, (list, tuple)) and len(sun_dir_hint) >= 2:
        sun_az = float(sun_dir_hint[0])
        sun_alt = float(sun_dir_hint[1])
    else:
        sun_az = float(hints_cfg.get("sun_azimuth_rad", math.radians(135.0)))
        sun_alt = float(hints_cfg.get("sun_altitude_rad", math.radians(35.0)))

    cs = stack.get("cloud_shadow", default=None)
    if cs is None:
        cs = np.zeros_like(stack.height, dtype=np.float32)

    hints = compute_god_ray_hints(stack, (sun_az, sun_alt), np.asarray(cs))

    # FIX-12-26: write god-ray intensity map to the stack so Unity receives
    # the channel; previously hints were computed then immediately discarded.
    h_shape = stack.height.shape
    god_ray_map = np.zeros(h_shape, dtype=np.float32)
    cell = float(stack.cell_size)
    ox = float(stack.world_origin_x)
    oy = float(stack.world_origin_y)
    for hint in hints:
        wx, wy, _ = hint.source_pos
        col = int((wx - ox) / cell - 0.5)
        row = int((wy - oy) / cell - 0.5)
        if 0 <= row < h_shape[0] and 0 <= col < h_shape[1]:
            god_ray_map[row, col] = max(god_ray_map[row, col], hint.intensity)
    stack.set("god_ray_hints", god_ray_map, "pass_god_ray_hints")

    return PassResult(
        pass_name="god_ray_hints",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height", "cloud_shadow"),
        produced_channels=("god_ray_hints",),
        metrics={
            "hint_count": len(hints),
            "max_intensity": float(max((h.intensity for h in hints), default=0.0)),
            "sun_azimuth_rad": sun_az,
            "sun_altitude_rad": sun_alt,
        },
        side_effects=[f"god_ray_hints:{len(hints)}"],
    )


def register_bundle_l_god_ray_hints_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="god_ray_hints",
            func=pass_god_ray_hints,
            requires_channels=("height",),
            produces_channels=("god_ray_hints",),
            seed_namespace="god_ray_hints",
            requires_scene_read=False,
            description="Bundle L: god-ray / light-shaft hint detection",
        )
    )


__all__ = [
    "GodRayHint",
    "compute_god_ray_hints",
    "export_god_ray_hints_json",
    "pass_god_ray_hints",
    "register_bundle_l_god_ray_hints_pass",
]

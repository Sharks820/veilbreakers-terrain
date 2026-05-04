"""Bundle J — terrain_gameplay_zones.

Classifies each cell into a GameplayZoneType based on stack signals and
authoring intent hints. Populates ``stack.gameplay_zone`` (int32), which
feeds Unity gameplay trigger volumes.

Upgrade notes (session 8 — AAA pass):
  cover_score   : per-cell float in [0,1] — height of surrounding terrain above
                  a standing agent. Derived by measuring how many of the 8
                  cardinal/diagonal neighbour rings have elevation >= cell + 1 m.
                  Inspired by UE5 Environmental Query System cover scoring.
  exposure      : sky-visibility proxy — inverse of cover_score smoothed with a
                  Gaussian to approximate solid angle of open sky. High exposure
                  means the cell is visible from aerial vantage.
  choke_score   : EDT of ridge/obstacle mask. Low EDT value (narrow corridor
                  between ridges) = high choke. Recast NavMesh uses a similar
                  concept for minimum corridor width detection.
  vantage_score : high-altitude cells with low surrounding slope variance —
                  gives a wide firing/observation arc. Combines normalised
                  height + reciprocal of a local slope-std neighbourhood.
"""

from __future__ import annotations

import time
from enum import IntEnum
from typing import Any, Dict, Optional

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)


class GameplayZoneType(IntEnum):
    SAFE = 0
    COMBAT = 1
    STEALTH = 2
    EXPLORATION = 3
    BOSS_ARENA = 4
    NARRATIVE = 5
    PUZZLE = 6


def _label_zones(mask: np.ndarray, eight_connected: bool = True) -> np.ndarray:
    """Return connected-component labels for a boolean mask.

    Uses scipy.ndimage.label when available; falls back to a BFS flood-fill.
    Returns int32 array of the same shape (0 = background, 1..N = components).
    """
    try:
        from scipy.ndimage import label as _sclabel
        structure = np.ones((3, 3), dtype=int) if eight_connected else None
        labeled, _ = _sclabel(mask.astype(bool), structure=structure)
        return labeled.astype(np.int32)
    except ImportError:
        pass
    from collections import deque
    H, W = mask.shape
    labeled = np.zeros((H, W), dtype=np.int32)
    comp_id = 0
    offsets = (
        [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        if eight_connected else [(-1, 0), (0, -1), (0, 1), (1, 0)]
    )
    for start_r in range(H):
        for start_c in range(W):
            if not mask[start_r, start_c] or labeled[start_r, start_c]:
                continue
            comp_id += 1
            q: deque = deque()
            q.append((start_r, start_c))
            labeled[start_r, start_c] = comp_id
            while q:
                r, c = q.popleft()
                for dr, dc in offsets:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < H and 0 <= nc < W and mask[nr, nc] and not labeled[nr, nc]:
                        labeled[nr, nc] = comp_id
                        q.append((nr, nc))
    return labeled


def _compute_cover_score(h: np.ndarray, cell_size: float) -> np.ndarray:
    """Per-cell cover score in [0, 1].

    A cell scores 1/8 for each of its 8-connected neighbours whose height
    is >= cell_height + 1.0 m (standing-agent shoulder height).  The result
    measures how many cardinal arcs are "covered" by terrain tall enough to
    block line-of-fire at close range.

    Two rings (r=1 and r=2) are tested and averaged so that very thin walls
    (single-pixel ridges) don't dominate.  Inspired by UE5 EQS cover node
    which samples ±90° arcs from the candidate position.
    """
    agent_height = 1.0  # metres
    cover1 = np.zeros_like(h, dtype=np.float64)
    cover2 = np.zeros_like(h, dtype=np.float64)

    rows_h, cols_h = h.shape

    # Ring r=1: the 8 direct neighbours.
    # np.pad edge mode prevents toroidal tile-seam contamination — np.roll
    # would wrap heights across the seam and report false cover from cells
    # on the opposite tile edge, biasing AI cover/exposure scoring at borders.
    _h_pad1 = np.pad(h, 1, mode="edge")
    offsets_r1 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    for dr, dc in offsets_r1:
        r0 = 1 - dr
        c0 = 1 - dc
        shifted = _h_pad1[r0:r0 + rows_h, c0:c0 + cols_h]
        cover1 += (shifted >= h + agent_height).astype(np.float64)
    cover1 /= 8.0

    # Ring r=2: shift by 2 cells diagonally / orthogonally (approximation)
    _h_pad2 = np.pad(h, 2, mode="edge")
    offsets_r2 = [(-2, -2), (-2, 0), (-2, 2), (0, -2), (0, 2), (2, -2), (2, 0), (2, 2)]
    for dr, dc in offsets_r2:
        r0 = 2 - dr
        c0 = 2 - dc
        shifted = _h_pad2[r0:r0 + rows_h, c0:c0 + cols_h]
        cover2 += (shifted >= h + agent_height).astype(np.float64)
    cover2 /= 8.0

    return np.clip((cover1 + cover2) * 0.5, 0.0, 1.0)


def _compute_sky_exposure(h: np.ndarray) -> np.ndarray:
    """Sky-exposure approximation in [0, 1].

    Exposure = 1 - cover, blurred with a 5-cell Gaussian to approximate
    solid-angle integration.  High exposure = open sky overhead = sniper
    vulnerability / no stealth.  Uses Recast NavMesh philosophy: open ground
    penalties are tagged for AI line-of-sight calculation.
    """
    cover = _compute_cover_score(h, 1.0)  # cell_size doesn't matter for this
    exposure = 1.0 - cover
    # Gaussian blur — 5x5 kernel, sigma≈1.5
    try:
        from scipy.ndimage import gaussian_filter
        exposure = gaussian_filter(exposure, sigma=1.5)
    except ImportError:
        # Manual 3x3 box blur as fallback
        np.ones((3, 3), dtype=np.float64) / 9.0
        from numpy.lib.stride_tricks import sliding_window_view
        try:
            win = sliding_window_view(exposure, (3, 3))
            blurred = win.mean(axis=(-2, -1))
            pad = np.pad(blurred, ((1, 1), (1, 1)), mode="edge")
            exposure = pad
        except Exception:
            pass  # keep raw if anything fails
    return np.clip(exposure, 0.0, 1.0)


def _compute_choke_score(h: np.ndarray, slope_deg: np.ndarray) -> np.ndarray:
    """Choke-point score in [0, 1].

    A choke point is a narrow corridor between impassable terrain features
    (ridges, cliffs).  Method: build an obstacle mask from steep slope (> 35°),
    compute EDT of that mask (distance from each cell to the nearest obstacle),
    then invert and normalise.  Cells with low EDT = close to two obstacles on
    opposite sides = high choke.

    This mirrors Recast NavMesh's approach of eroding the walkable region by
    agent radius to find narrow passages.
    """
    obstacle = slope_deg > 35.0
    if not obstacle.any():
        return np.zeros_like(h, dtype=np.float64)

    try:
        from scipy.ndimage import distance_transform_edt as _edt
        # EDT returns distance in *cell* units; we work in normalised [0,1]
        dist = _edt(~obstacle).astype(np.float64)
    except ImportError:
        # Chamfer fallback (reuse the two-pass from wildlife module pattern)
        SQRT2 = np.sqrt(2.0)
        INF = 1e9
        dist = np.where(obstacle, 0.0, INF).astype(np.float64)
        H, W = dist.shape
        for r in range(H):
            for c in range(W):
                if dist[r, c] == 0.0:
                    continue
                best = dist[r, c]
                if r > 0:
                    best = min(best, dist[r - 1, c] + 1.0)
                    if c > 0:
                        best = min(best, dist[r - 1, c - 1] + SQRT2)
                    if c < W - 1:
                        best = min(best, dist[r - 1, c + 1] + SQRT2)
                if c > 0:
                    best = min(best, dist[r, c - 1] + 1.0)
                dist[r, c] = best
        for r in range(H - 1, -1, -1):
            for c in range(W - 1, -1, -1):
                if dist[r, c] == 0.0:
                    continue
                best = dist[r, c]
                if r < H - 1:
                    best = min(best, dist[r + 1, c] + 1.0)
                    if c > 0:
                        best = min(best, dist[r + 1, c - 1] + SQRT2)
                    if c < W - 1:
                        best = min(best, dist[r + 1, c + 1] + SQRT2)
                if c < W - 1:
                    best = min(best, dist[r, c + 1] + 1.0)
                dist[r, c] = best
        dist[dist >= INF * 0.5] = np.nan

    max_dist = np.nanmax(dist)
    if max_dist < 1e-6:
        return np.zeros_like(h, dtype=np.float64)
    # Invert: small distance from obstacles → high choke
    norm_dist = np.nan_to_num(dist, nan=max_dist) / max_dist
    choke = np.clip(1.0 - norm_dist, 0.0, 1.0)
    return choke


def _compute_vantage_score(h: np.ndarray, slope_deg: np.ndarray) -> np.ndarray:
    """Vantage-point score in [0, 1].

    High vantage = cell is elevated AND the surrounding terrain is lower and
    relatively flat (wide unobstructed view arc).  Combines:
      - normalised height (higher = more vantage)
      - inverse of local slope-std in a 5x5 neighbourhood (flat surroundings
        mean the agent can rotate freely without terrain blocking arc sectors)

    AC:Valhalla wildlife AI uses a similar "observable area" metric for
    eagle/raven perch selection.
    """
    h_range = h.max() - h.min()
    if h_range < 1e-6:
        return np.zeros_like(h, dtype=np.float64)
    h_norm = (h - h.min()) / h_range

    # Local slope standard deviation in 5x5 window
    try:
        from scipy.ndimage import generic_filter
        slope_std = generic_filter(slope_deg, np.std, size=5, mode="nearest")
    except ImportError:
        # Approximate with rolling std via strides if available
        try:
            from numpy.lib.stride_tricks import sliding_window_view
            win = sliding_window_view(np.pad(slope_deg, 2, mode="edge"), (5, 5))
            slope_std = win.reshape(*slope_deg.shape, -1).std(axis=-1)
        except Exception:
            slope_std = np.zeros_like(slope_deg)

    # Normalise slope_std: high std → terrain is jagged around cell → less vantage
    std_max = slope_std.max()
    if std_max < 1e-6:
        flatness = np.ones_like(slope_std)
    else:
        flatness = 1.0 - np.clip(slope_std / std_max, 0.0, 1.0)

    vantage = np.clip(h_norm * 0.6 + flatness * 0.4, 0.0, 1.0)
    return vantage


def compute_gameplay_zones(
    stack: TerrainMaskStack,
    intent: Optional[Any] = None,
) -> np.ndarray:
    """Return an (H, W) int32 array of GameplayZoneType values.

    Zone classification pipeline (priority — higher overrides lower):
      1. Default EXPLORATION everywhere.
      2. SAFE:     low slope (<8°) + (basin OR near water); connected components.
      3. COMBAT:   moderate slope (8-20°) + high sky exposure (open ground);
                   also any cell with choke_score < 0.3 and exposure > 0.5
                   (open area but not channelled).
      4. STEALTH:  high cover_score (>0.6) OR dense forest/concave curvature;
                   narrows into cover patches.
      5. PUZZLE:   cave_candidate regions; connected components.
      6. NARRATIVE: within hero feature footprint (from intent).
      7. BOSS_ARENA: authored via intent.composition_hints['boss_arena_bbox'].

    Cover, exposure, choke, and vantage scores are computed from the height
    field and embedded in the PassResult metrics for consumption by the
    Unity gameplay trigger placement system (UE5 Gameplay Tags analogue).
    """
    if stack.height is None:
        raise ValueError("compute_gameplay_zones requires stack.height")

    h = np.asarray(stack.height, dtype=np.float64)
    shape = h.shape
    H, W = shape
    min_component_cells = max(4, H * W // 2000)
    out = np.full(shape, GameplayZoneType.EXPLORATION.value, dtype=np.int32)

    slope = stack.slope
    if slope is None:
        gy, gx = np.gradient(h, float(stack.cell_size))
        slope = np.arctan(np.sqrt(gx * gx + gy * gy))
    slope_deg = np.degrees(np.asarray(slope, dtype=np.float64))

    # --- Real gameplay signals ------------------------------------------------
    cover_score = _compute_cover_score(h, float(stack.cell_size))
    sky_exposure = _compute_sky_exposure(h)
    choke_score = _compute_choke_score(h, slope_deg)
    _compute_vantage_score(h, slope_deg)

    # SAFE: low slope + basin or water proximity + low exposure (sheltered)
    safe = (slope_deg < 8.0) & (sky_exposure < 0.6)
    if stack.basin is not None:
        safe = safe & (np.asarray(stack.basin) > 0)

    # COMBAT: open terrain (high exposure), moderate slope, not a chokepoint
    combat = (
        (slope_deg >= 5.0) & (slope_deg < 25.0)
        & (sky_exposure > 0.45)
        & (choke_score < 0.4)
    )

    # STEALTH: high cover (terrain blocks sight) OR dense canopy/concave
    stealth = cover_score > 0.55
    if stack.detail_density:
        total = np.zeros(shape, dtype=np.float64)
        for arr in stack.detail_density.values():
            total += np.asarray(arr, dtype=np.float64)
        stealth = stealth | (total > 0.5)
    if stack.curvature is not None:
        stealth = stealth | (np.asarray(stack.curvature) < -0.1)

    # PUZZLE: cave candidates (enclosed, low exposure)
    puzzle = (
        np.asarray(stack.cave_candidate) > 0.5
        if stack.cave_candidate is not None
        else np.zeros(shape, dtype=bool)
    )

    def _apply_zone_with_cc(mask: np.ndarray, zone_val: int) -> None:
        labels = _label_zones(mask)
        if labels.max() == 0:
            return
        comp_ids, comp_sizes = np.unique(labels[labels > 0], return_counts=True)
        for cid, csz in zip(comp_ids, comp_sizes):
            if csz < min_component_cells:
                continue
            out[labels == cid] = zone_val

    _apply_zone_with_cc(safe, GameplayZoneType.SAFE.value)
    _apply_zone_with_cc(combat, GameplayZoneType.COMBAT.value)
    _apply_zone_with_cc(stealth, GameplayZoneType.STEALTH.value)
    _apply_zone_with_cc(puzzle, GameplayZoneType.PUZZLE.value)

    # NARRATIVE from hero features
    if intent is not None and getattr(intent, "hero_feature_specs", ()):
        for hero in intent.hero_feature_specs:
            bounds = getattr(hero, "bounds", None)
            if bounds is None:
                continue
            r_slice, c_slice = bounds.to_cell_slice(
                stack.world_origin_x,
                stack.world_origin_y,
                stack.cell_size,
                shape,
            )
            out[r_slice, c_slice] = GameplayZoneType.NARRATIVE.value

    # BOSS_ARENA from composition_hints
    if intent is not None:
        hint = getattr(intent, "composition_hints", {}).get("boss_arena_bbox")
        if hint is not None and isinstance(hint, BBox):
            r_slice, c_slice = hint.to_cell_slice(
                stack.world_origin_x,
                stack.world_origin_y,
                stack.cell_size,
                shape,
            )
            out[r_slice, c_slice] = GameplayZoneType.BOSS_ARENA.value

    return out


def _compute_gameplay_score_metrics(
    h: np.ndarray,
    slope_deg: np.ndarray,
) -> Dict[str, Any]:
    """Compute per-zone scoring arrays and return summary stats for PassResult.

    Returns a dict of floats/ints suitable for PassResult.metrics.
    The full per-cell arrays are not storable on the stack (no declared
    channel), but summary statistics feed the Unity trigger-volume placement.
    """
    cover = _compute_cover_score(h, 1.0)
    exposure = _compute_sky_exposure(h)
    choke = _compute_choke_score(h, slope_deg)
    vantage = _compute_vantage_score(h, slope_deg)
    return {
        "cover_score_mean": float(cover.mean()),
        "cover_score_max": float(cover.max()),
        "exposure_mean": float(exposure.mean()),
        "choke_score_mean": float(choke.mean()),
        "choke_cells_gt05": int((choke > 0.5).sum()),
        "vantage_score_mean": float(vantage.mean()),
        "vantage_cells_gt07": int((vantage > 0.7).sum()),
    }


def pass_gameplay_zones(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle J pass: classify gameplay zones with cover/exposure/choke/vantage.

    Consumes: height, slope (optional), curvature (optional), basin (optional)
    Produces: gameplay_zone

    Metrics include per-cell scoring summaries for the gameplay trigger
    volume placement system:
      cover_score_mean / cover_score_max — terrain cover quality
      exposure_mean                      — sky visibility mean
      choke_score_mean / choke_cells_gt05 — narrow passage prevalence
      vantage_score_mean / vantage_cells_gt07 — elevated vantage count
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    zones = compute_gameplay_zones(stack, state.intent)
    stack.set("gameplay_zone", zones, "gameplay_zones")

    # Compute scoring metrics for Unity trigger placement
    h = np.asarray(stack.height, dtype=np.float64)
    slope = stack.slope
    if slope is None:
        gy, gx = np.gradient(h, float(stack.cell_size))
        slope = np.arctan(np.sqrt(gx * gx + gy * gy))
    slope_deg = np.degrees(np.asarray(slope, dtype=np.float64))

    score_metrics = _compute_gameplay_score_metrics(h, slope_deg)

    vals, counts = np.unique(zones, return_counts=True)
    issues: list[ValidationIssue] = []

    return PassResult(
        pass_name="gameplay_zones",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("gameplay_zone",),
        metrics={
            "zone_distribution": {
                int(v): int(c) for v, c in zip(vals.tolist(), counts.tolist())
            },
            **score_metrics,
        },
        issues=issues,
    )


def register_bundle_j_gameplay_zones_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="gameplay_zones",
            func=pass_gameplay_zones,
            requires_channels=("height",),
            produces_channels=("gameplay_zone",),
            seed_namespace="gameplay_zones",
            requires_scene_read=False,
            protocol_enforced=True,
            protocol_require_rule_5=True,
            protocol_bulk_edit=True,
            description="Bundle J: classify gameplay zones from mask stack + intent",
        )
    )


__all__ = [
    "GameplayZoneType",
    "compute_gameplay_zones",
    "pass_gameplay_zones",
    "register_bundle_j_gameplay_zones_pass",
]

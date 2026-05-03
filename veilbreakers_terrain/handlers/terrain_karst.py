"""Bundle I — terrain_karst.

Karst hydrology: detects soluble-rock regions (using rock_hardness as a
proxy for limestone) and spawns karst features — sinkholes, cenotes,
disappearing streams, poljes. ``carve_karst_features`` returns a height
delta for the caller to apply.

Pure numpy, no bpy. Z-up, world meters.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

import logging

logger = logging.getLogger(__name__)

from .terrain_pipeline import derive_pass_seed
from .terrain_semantics import (
    BBox,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class SinkholeSpec:
    """Full specification for a sinkhole mesh, used by get_sinkhole_specs.

    wall_angle: steepness of collapse wall in degrees (typical 65–80°).
    floor_depth: total vertical depth from rim to flat floor in metres.
    collapse_stage: "fresh" (sharp rim, no rubble), "weathered" (rounded
        rim, rubble apron), or "flooded" (water at base, algae rim).
    """

    radius_m: float
    wall_angle: float = 70.0
    floor_depth: float = 0.0  # computed as radius_m * 0.6 if not set
    has_bottom_cave: bool = False
    wall_roughness: float = 0.5
    rubble_density: float = 0.35
    collapse_stage: str = "weathered"  # "fresh" | "weathered" | "flooded"

    def __post_init__(self) -> None:
        if self.floor_depth <= 0.0:
            self.floor_depth = self.radius_m * 0.6
        valid_stages = ("fresh", "weathered", "flooded")
        if self.collapse_stage not in valid_stages:
            raise ValueError(
                f"collapse_stage must be one of {valid_stages}, "
                f"got {self.collapse_stage!r}"
            )


@dataclass
class KarstFeature:
    """One karst landform instance."""

    feature_id: str
    kind: str  # "sinkhole" | "disappearing_stream" | "cenote" | "polje"
    world_pos: Tuple[float, float, float]
    radius_m: float

    def __post_init__(self) -> None:
        valid = ("sinkhole", "disappearing_stream", "cenote", "polje")
        if self.kind not in valid:
            raise ValueError(
                f"KarstFeature.kind must be one of {valid}, got {self.kind!r}"
            )
        if self.radius_m <= 0.0:
            raise ValueError(
                f"KarstFeature.radius_m must be > 0, got {self.radius_m}"
            )


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_karst_candidates(
    stack: TerrainMaskStack,
    hardness_threshold: float = 0.5,
) -> List[KarstFeature]:
    """Return karst candidate features from soluble-rock regions.

    Detection pipeline
    ------------------
    1. **Hardness gate** — restricts candidates to limestone-ish rock
       (hardness in [0.4, hardness_threshold + 0.15]).  Values outside
       this band are too soft (alluvium) or too hard (granite) to develop
       karst.

    2. **Curvature signal** — computes Gaussian curvature of the heightmap
       using correct second-derivative operators (single np.gradient call
       per input array to avoid redundant computation and index-aliasing
       bugs).  Negative Gaussian curvature marks concave dissolution hollows
       where surface water ponds and infiltrates.  Mean curvature is also
       computed; strongly negative mean curvature (bowl shape) is used as a
       secondary classifier for cenotes and poljes.

    3. **Flow-sink proxy** — local depressions (cells lower than the 5×5
       neighbourhood minimum + 0.1 m) are preferential karst initiation
       sites because surface water drains underground at these points.

    4. **Poisson-disk sampling** — feature sites are distributed with a
       minimum world-space separation of max(8 cells, H//8) × cell_size so
       nearby features don't overlap.  Separation scales with tile size.

    5. **Feature classification**:
       - ``cenote``            — deep local sink (> 0.4 × local relief) in
                                 the lowest 20% of tile elevation; water
                                 table commonly exposed at base.
       - ``polje``             — large shallow depression (mean curvature
                                 strongly negative over a 5×5 window) in
                                 the lower 35% of tile elevation.
       - ``disappearing_stream`` — gentle gradient point with high upslope
                                 area (flow-accumulation proxy) in the
                                 karst-prone zone; stream loses flow
                                 underground.
       - ``sinkhole``          — default for all remaining candidates.

    6. **Radius estimation** — radius is scaled by local relief depth
       (deeper sinks = larger radius, matching real doline morphometry:
       r ≈ 2.5 × depth^0.6 for collapse dolines per Williams 1983).
       Clamped to [2 × cell_size, 0.05 × tile_width] so it stays within
       the tile.
    """
    if stack.rock_hardness is None:
        return []
    if stack.height is None:
        return []

    hardness = np.asarray(stack.rock_hardness, dtype=np.float64)
    h = np.asarray(stack.height, dtype=np.float64)
    H, W = h.shape
    cs = float(stack.cell_size)

    # Bug-fix 1: guard against degenerate tiles
    if H < 5 or W < 5:
        return []

    # Karst-prone mask: limestone-ish hardness (not too hard, not too soft)
    limestone_mask = (hardness >= 0.4) & (hardness <= hardness_threshold + 0.15)
    if not limestone_mask.any():
        return []

    # ------------------------------------------------------------------
    # Curvature: 2nd derivatives of the heightmap.
    # Bug-fix 2: the original code called np.gradient(dh_dx, cs) TWICE —
    # once to get d2h/dx2 and once to get d2h/dxdy.  np.gradient returns
    # ALL axes simultaneously; calling it twice is redundant and masks a
    # subtle aliasing bug (same array, same result, wasted allocation).
    # Correct approach: call once and unpack both output axes.
    # ------------------------------------------------------------------
    dh_dy, dh_dx = np.gradient(h, cs)

    # d2h_dy2 = ∂²h/∂y²,  d2h_dydx = ∂²h/(∂y∂x) — from dh_dy
    d2h_dy2, d2h_dydx = np.gradient(dh_dy, cs)

    # d2h_dxdy = ∂²h/(∂x∂y),  d2h_dx2 = ∂²h/∂x² — from dh_dx
    d2h_dxdy, d2h_dx2 = np.gradient(dh_dx, cs)

    # Gaussian curvature numerator (simplified for near-flat terrain):
    # K ≈ (∂²h/∂x² · ∂²h/∂y² − (∂²h/∂x∂y)²) / (1 + (∂h/∂x)² + (∂h/∂y)²)²
    denom = np.maximum(1e-12, (1.0 + dh_dx ** 2 + dh_dy ** 2) ** 2)
    gaussian_curv = (d2h_dx2 * d2h_dy2 - d2h_dxdy ** 2) / denom

    # Mean curvature (bowl strength): H_m = −(∂²h/∂x² + ∂²h/∂y²) / 2
    # Negative mean curvature = locally concave (depression).
    mean_curv = -(d2h_dx2 + d2h_dy2) / 2.0

    # High negative Gaussian curvature → saddle/concave dissolution zone
    curvature_prone = gaussian_curv < -1e-6

    # Combined mask: limestone hardness + curvature signal
    karst_mask = limestone_mask & curvature_prone
    if not karst_mask.any():
        # Fallback to hardness-only if curvature produces no candidates
        karst_mask = limestone_mask.copy()

    # ------------------------------------------------------------------
    # Flow-accumulation proxy: simple D8 upslope area via numpy.
    # Count cells whose gradient vector points toward each cell.
    # We use a fast 8-neighbour upstream-count approximation: cells where
    # the local gradient magnitude is low (flat catchment) accumulate more
    # surface flow before it infiltrates — those are disappearing-stream
    # candidates.
    # ------------------------------------------------------------------
    grad_mag = np.sqrt(dh_dx ** 2 + dh_dy ** 2)
    # Normalise to [0, 1]; low gradient = high-accumulation proxy
    gm_max = float(grad_mag.max()) or 1.0
    flow_accum_proxy = 1.0 - (grad_mag / gm_max)  # high = flat, likely accumulating

    # ------------------------------------------------------------------
    # Tile-level statistics for feature classification.
    # Bug-fix 3: the original code used h.min()/h.max() for both the
    # polje test and no other stats — but h.max() − h.min() can be zero
    # on flat tiles, and the 0.25-threshold was arbitrary.  We now compute
    # per-tile relief and use percentile-based thresholds.
    # ------------------------------------------------------------------
    h_min = float(h.min())
    h_max = float(h.max())
    tile_relief = float(h_max - h_min) or 1.0
    # Elevation percentile thresholds for feature classification
    low20_z = h_min + 0.20 * tile_relief   # bottom 20% of elevation
    low35_z = h_min + 0.35 * tile_relief   # bottom 35% — polje zone

    # ------------------------------------------------------------------
    # Poisson-disk sampling with corrected minimum separation.
    # Bug-fix 4: original min_sep used H//16 pixel counts × cs, giving a
    # cell-count-dependent separation that was too coarse for small tiles.
    # New formula: max(8 cells, H//8) × cs ensures adequate coverage.
    # ------------------------------------------------------------------
    from ._scatter_engine import poisson_disk_sample

    features: List[KarstFeature] = []
    min_sep_cells = max(8, H // 8)
    min_sep = float(min_sep_cells) * cs
    tile_w = W * cs
    tile_d = H * cs
    _seed = (int(stack.tile_x) * 1000003 + int(stack.tile_y)) & 0x7FFFFFFF
    candidates = poisson_disk_sample(tile_w, tile_d, min_sep, seed=_seed)

    fid = 0
    margin = 2  # 5×5 window needs r±2, c±2
    for lx, ly in candidates:
        c = int(round(lx / cs))
        r = int(round(ly / cs))
        if not (margin <= r < H - margin and margin <= c < W - margin):
            continue
        if not karst_mask[r, c]:
            continue

        # Local 5×5 neighbourhood statistics
        window = h[r - 2 : r + 3, c - 2 : c + 3]
        win_min = float(window.min())
        win_max = float(window.max())
        local_relief = win_max - win_min  # local depth of the depression

        # Reject cells that are NOT near the local minimum.
        # FIX-10-3: tile-relative threshold replaces absolute 0.1 m.
        # 0.001 * tile_relief scales with terrain height range so the gate fires
        # consistently on both flat and steep tiles.
        dissolution_threshold = 0.001 * (h_max - h_min)  # FIX-10-3
        if h[r, c] > win_min + dissolution_threshold:
            continue  # not a local minimum — skip

        center_z = float(h[r, c])

        # ------------------------------------------------------------------
        # Feature classification.
        # Bug-fix 5: original code classified "cenote" by hardness > threshold,
        # which was geologically wrong (cenotes form in soluble limestone, not
        # harder rock) and only fired for a tiny hardness band [threshold,
        # threshold+0.15].  New classification uses elevation and curvature
        # context:
        #
        # cenote  — deep sink (local_relief > 0.4×tile_relief) in low zone;
        #           water table exposed (bottom 20% elevation).
        # polje   — gentle large basin; strongly negative mean curvature over
        #           the 5×5 window AND in bottom 35% elevation.
        # disappearing_stream — low gradient (flow accumulating) candidate
        #           that is NOT a sink — stream loses flow underground here.
        # sinkhole — all remaining candidates.
        # ------------------------------------------------------------------
        local_mean_curv = float(mean_curv[r - 2 : r + 3, c - 2 : c + 3].mean())

        if center_z <= low20_z and local_relief > 0.4 * tile_relief:
            kind = "cenote"
        elif center_z <= low35_z and local_mean_curv < -1e-5:
            kind = "polje"
        elif flow_accum_proxy[r, c] > 0.85 and local_relief < 0.1 * tile_relief:
            # Flat high-accumulation cell — surface water likely drains underground
            kind = "disappearing_stream"
        else:
            kind = "sinkhole"

        # ------------------------------------------------------------------
        # Radius estimation.
        # Bug-fix 6: original code used a fixed radius of 2 × cell_size for
        # every feature.  Real doline morphometry (Williams 1983) gives:
        #   r ≈ 2.5 × depth^0.6   (collapse dolines, depth in metres)
        # We use local_relief as a depth proxy.  Clamp to [2cs, 5% of tile].
        # ------------------------------------------------------------------
        if local_relief > 0.01:
            raw_radius = 2.5 * (local_relief ** 0.6)
        else:
            raw_radius = cs * 3.0
        radius = float(
            max(cs * 2.0, min(raw_radius, tile_w * 0.05))
        )

        wx = stack.world_origin_x + c * cs
        wy = stack.world_origin_y + r * cs
        wz = center_z
        features.append(
            KarstFeature(
                feature_id=f"karst_{fid}",
                kind=kind,
                world_pos=(wx, wy, wz),
                radius_m=radius,
            )
        )
        fid += 1
    return features


# ---------------------------------------------------------------------------
# Carving
# ---------------------------------------------------------------------------


def _compose_uvala(base_delta: np.ndarray, depression_delta: np.ndarray) -> np.ndarray:
    """Additive uvala composition for overlapping karst depressions.

    Depression deltas are signed: values below zero carve downward. Additive
    composition preserves compound-basin depth when dolines overlap; using
    ``minimum`` alone drops all but the deepest depression and creates phantom
    "completed" uvalas with no combined carve.
    """
    return np.asarray(base_delta, dtype=np.float64) + np.minimum(
        0.0,
        np.asarray(depression_delta, dtype=np.float64),
    )


def carve_karst_features(
    stack: TerrainMaskStack,
    features: List[KarstFeature],
) -> np.ndarray:
    """Return a height delta carving the given karst features.

    Fully vectorised via numpy — no per-cell Python loops.

    Feature profiles
    ----------------
    **Sinkhole / cenote** — steep-walled bowl with flat floor:
      - Floor zone (inner 35% of radius): full depth, flat.
      - Wall zone: depth = D * cos(wall_t * pi/2)^p where p encodes wall_angle
        (p = 1/tan(wall_angle) + 0.5). High wall_angle (72 deg) => near-vertical
        walls as seen in cenotes and collapse dolines.
      - Profile is slightly elliptical (1.2x in the collapse-orientation axis)
        so each feature has a unique collapse direction based on a hash of its
        world position.
    **Uvala** — when sinkholes overlap, their signed depression deltas compose
      additively via ``base + min(0, depression)`` so compound basins deepen
      instead of merely selecting the deepest single source.
    **Polje** — flat-floored shallow basin using a superellipse (n=4) profile:
      near-flat interior with a sharp rim transition, aspect ratio 2.5:1
      matching real karstic poljes.
    **Disappearing stream** — no height delta (handled by hydrology bundle).
    """
    if stack.height is None:
        raise ValueError("carve_karst_features requires stack.height")
    H, W = stack.height.shape
    delta = np.zeros((H, W), dtype=np.float64)
    cs = float(stack.cell_size)

    if not features:
        return delta

    # Pre-build coordinate grids — reused for every feature
    rr, cc = np.mgrid[0:H, 0:W].astype(np.float64)

    for fid_idx, f in enumerate(features):
        cx = (f.world_pos[0] - stack.world_origin_x) / cs
        cy = (f.world_pos[1] - stack.world_origin_y) / cs
        rad_cells = max(1.0, f.radius_m / cs)

        # Deterministic per-feature orientation (hash of world position)
        orient_seed = (
            int(f.world_pos[0] * 100) ^ int(f.world_pos[1] * 100)
            ^ (fid_idx * 2654435761)
        ) & 0xFFFF
        orient_rad = math.radians(float(orient_seed % 360))
        cos_o = math.cos(orient_rad)
        sin_o = math.sin(orient_rad)

        dr = rr - cy
        dc = cc - cx

        if f.kind in ("sinkhole", "cenote"):
            # Rotate into collapse frame + slight ellipticity (1.2x across-axis)
            dr_rot = dr * cos_o + dc * sin_o
            dc_rot = (-dr * sin_o + dc * cos_o) * 1.2
            dist_norm = np.sqrt(dr_rot ** 2 + dc_rot ** 2) / rad_cells

            wall_angle_deg = 72.0 if f.kind == "cenote" else 68.0
            floor_frac = 0.35
            total_depth = f.radius_m * (1.4 if f.kind == "cenote" else 0.6)
            wall_p = 1.0 / math.tan(math.radians(wall_angle_deg)) + 0.5

            wall_t = np.clip(
                (dist_norm - floor_frac) / (1.0 - floor_frac), 0.0, 1.0
            )
            depth_arr = np.where(
                dist_norm <= floor_frac,
                total_depth,
                total_depth * np.cos(wall_t * (math.pi * 0.5)) ** wall_p,
            )
            # Zero outside the feature radius
            depth_arr = np.where(dist_norm < 1.0, depth_arr, 0.0)
            delta = _compose_uvala(delta, -depth_arr)

        elif f.kind == "polje":
            # Superellipse (n=4): near-flat interior, sharp rim, elongated 2.5:1
            depth_scale = f.radius_m * 0.25
            aspect = 2.5
            dist_super = (
                (np.abs(dr) / rad_cells) ** 4
                + (np.abs(dc) / (rad_cells * aspect)) ** 4
            )
            # Smooth falloff at the rim
            t_blend = np.clip(1.0 - dist_super ** 0.25, 0.0, 1.0)
            depth_arr = depth_scale * t_blend
            inside = dist_super < 1.0
            delta = np.where(inside, _compose_uvala(delta, -depth_arr), delta)

    return delta


def _place_cave_entrances(
    slope_arr: np.ndarray,
    doline_mask: np.ndarray,
    cliff_mask: np.ndarray,
) -> np.ndarray:
    """Place cave entrance candidates at steep cells adjacent to dolines. FIX-9-53

    Previous implementation targeted doline rim elevation (flat surface), so
    entrances appeared on horizontal rims rather than cliff faces — visually
    wrong and unreachable by player navigation.  This version intersects:

      * steep cells (slope > 35°, matching natural karst cliff angles)
      * cells adjacent to a doline depression (binary dilation of doline_mask)
      * cells within an existing cliff mask

    The result is a float32 mask (0 or 1) suitable for stacking.set().

    Parameters
    ----------
    slope_arr : np.ndarray (H, W)
        Slope in radians (or degrees — threshold 0.61 rad ≈ 35°).
    doline_mask : np.ndarray (H, W)
        Non-zero where doline depressions were detected.
    cliff_mask : np.ndarray (H, W)
        Non-zero where cliffs exist.
    """
    import scipy.ndimage as ndi

    steep = np.asarray(slope_arr) > 0.61  # > ~35 degrees
    doline_adj = ndi.binary_dilation(np.asarray(doline_mask) > 0)
    return (steep & doline_adj & (np.asarray(cliff_mask) > 0)).astype(np.float32)


# ---------------------------------------------------------------------------
# Pass
# ---------------------------------------------------------------------------


def pass_karst(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle I pass: detect + carve karst features.

    Consumes: height, rock_hardness
    Produces: karst_delta. No-feature tiles write a zero delta so downstream
    integrators and DAG contracts do not silently skip a required output.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    hints = dict(state.intent.composition_hints) if state.intent else {}
    hardness_threshold = float(hints.get("karst_hardness_threshold", 0.6))
    enabled = bool(hints.get("karst_enabled", True))

    features: List[KarstFeature] = []
    delta_mean = 0.0
    if enabled and stack.rock_hardness is not None:
        features = detect_karst_candidates(stack, hardness_threshold)
        if features:
            delta = carve_karst_features(stack, features)
            stack.set("karst_delta", delta.astype(np.float32), "karst")
            delta_mean = float(np.abs(delta).mean())
    if stack.get("karst_delta", default=None) is None:
        stack.set("karst_delta", np.zeros_like(stack.height, dtype=np.float32), "karst")

    # FIX-9-53: place cave entrances after doline_mask is available
    _doline_mask = stack.get("karst_delta")  # karst_delta non-zero at doline sites
    _cliff_mask = stack.get("cliff_mask")
    if (
        _doline_mask is not None
        and _cliff_mask is not None
        and stack.height is not None
    ):
        import numpy as _np
        _slope_arr = stack.get("slope")
        if _slope_arr is None:
            # Approximate slope from height gradient (radians)
            _gy, _gx = _np.gradient(stack.height.astype(np.float32))
            _slope_arr = _np.arctan(_np.sqrt(_gx ** 2 + _gy ** 2))
        cave_entrance_mask = _place_cave_entrances(
            _slope_arr, _doline_mask, _cliff_mask
        )
        stack.set("cave_entrance_mask", cave_entrance_mask, "terrain_karst")
    elif stack.height is not None:
        stack.set(
            "cave_entrance_mask",
            np.zeros_like(stack.height, dtype=np.float32),
            "terrain_karst",
        )

    _ = derive_pass_seed(
        state.intent.seed, "karst", state.tile_x, state.tile_y, region
    )

    return PassResult(
        pass_name="karst",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height", "rock_hardness"),
        produced_channels=("karst_delta", "cave_entrance_mask"),
        metrics={
            "feature_count": len(features),
            "mean_delta_m": delta_mean,
            "hardness_threshold": hardness_threshold,
            "enabled": enabled,
        },
        issues=[],
    )


def get_sinkhole_specs(
    stack: TerrainMaskStack,
    *,
    max_sinkholes: int = 5,
    seed: int = 42,
) -> list:
    """Return SinkholeSpec dicts for sinkhole meshes at karst-detected sites.

    Calls ``detect_karst_candidates`` to find sinkhole/cenote locations.
    Returns a list of dicts with ``sinkhole_spec`` (SinkholeSpec), ``mesh_spec``
    (from terrain_features.generate_sinkhole if available), and ``world_pos``.

    Each SinkholeSpec contains the complete spec including wall_angle and
    floor_depth fields required for AAA-quality mesh generation.
    """
    features = detect_karst_candidates(stack)
    sinkholes = [f for f in features if f.kind in ("sinkhole", "cenote")]
    if not sinkholes:
        return []

    rng = np.random.default_rng(seed)
    results = []
    for f in sinkholes[:max_sinkholes]:
        wall_roughness = float(rng.uniform(0.3, 0.7))
        rubble_density = float(rng.uniform(0.2, 0.5))
        is_cenote = f.kind == "cenote"

        # collapse_stage: cenotes are always flooded; others vary by radius
        # (larger sinkholes have had more time to weather and fill with water)
        if is_cenote:
            collapse_stage = "flooded"
        elif f.radius_m > 15.0:
            collapse_stage = "weathered"
        else:
            # Small fresh sinkholes: 60% weathered, 40% fresh
            collapse_stage = "fresh" if rng.random() < 0.4 else "weathered"

        # Full SinkholeSpec with wall_angle, floor_depth, and collapse_stage
        sinkhole_spec = SinkholeSpec(
            radius_m=f.radius_m,
            wall_angle=72.0 if is_cenote else 68.0,
            floor_depth=f.radius_m * (1.4 if is_cenote else 0.6),
            has_bottom_cave=is_cenote,
            wall_roughness=wall_roughness,
            rubble_density=rubble_density,
            collapse_stage=collapse_stage,
        )

        # Attempt to get a mesh spec from terrain_features (best-effort)
        mesh_spec = None
        try:
            from .terrain_features import generate_sinkhole
            mesh_spec = generate_sinkhole(
                radius=f.radius_m,
                depth=sinkhole_spec.floor_depth,
                wall_roughness=wall_roughness,
                has_bottom_cave=is_cenote,
                rubble_density=rubble_density,
                seed=int(rng.integers(0, 2**31)),
            )
        except Exception:
            logger.debug("generate_sinkhole_mesh_spec failed for feature %s", getattr(f, 'world_pos', '?'), exc_info=True)

        results.append({
            "sinkhole_spec": sinkhole_spec,
            "mesh_spec": mesh_spec,
            "world_pos": f.world_pos,
        })
    return results


__all__ = [
    "SinkholeSpec",
    "KarstFeature",
    "detect_karst_candidates",
    "_compose_uvala",
    "carve_karst_features",
    "_place_cave_entrances",
    "pass_karst",
    "get_sinkhole_specs",
]

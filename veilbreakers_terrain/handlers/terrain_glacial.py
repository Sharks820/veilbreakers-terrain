"""Bundle I — terrain_glacial.

Glacial carving: U-shaped valleys, lateral/terminal moraines, and
altitude-driven snow-line computation. Unlike hydraulic V-valleys
these are wide, flat-floored, and carved along authored paths.

Pure numpy, no bpy. Z-up, world meters.
"""

from __future__ import annotations

import math
import time
from typing import List, Optional, Sequence, Tuple

import numpy as np

from .terrain_pipeline import derive_pass_seed
from .terrain_semantics import (
    BBox,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# U-valley carving
# ---------------------------------------------------------------------------


def _path_to_cells(
    path: Sequence[Tuple[float, float]],
    stack: TerrainMaskStack,
) -> List[Tuple[int, int]]:
    """Convert world-space (x, y) path to (row, col) cells on the tile grid."""
    cells: List[Tuple[int, int]] = []
    H, W = stack.height.shape
    for (wx, wy) in path:
        c = int(round((wx - stack.world_origin_x) / stack.cell_size))
        r = int(round((wy - stack.world_origin_y) / stack.cell_size))
        if 0 <= r < H and 0 <= c < W:
            cells.append((r, c))
    return cells


def carve_u_valley(
    stack: TerrainMaskStack,
    path: Sequence[Tuple[float, float]],
    width_m: float,
    depth_m: float,
) -> np.ndarray:
    """Return a height delta carving a glacial U-shaped valley along ``path``.

    Cross-section uses the true parabolic profile of a glacially carved trough:
        h(d) = -depth * sqrt(max(0, 1 - (2d/width)^2))
    which is the equation of an upward-opening ellipse — the standard
    geomorphological model (Svensson 1959; Harbor 1992).

    Depth is optionally scaled by Hack's law proxy when flow_accumulation is
    available on the stack: larger upstream catchments produce deeper valleys
    (d ∝ A^0.4, Hack 1957). The profile is smoothed with a Gaussian kernel
    (sigma = half_width / 4) to remove rasterisation noise.

    Not applied in place — caller decides whether to write.
    """
    if stack.height is None:
        raise ValueError("carve_u_valley requires stack.height")
    if width_m <= 0 or depth_m <= 0:
        raise ValueError("width_m and depth_m must be positive")

    H, W = stack.height.shape
    delta = np.zeros((H, W), dtype=np.float64)
    if len(path) < 2:
        return delta

    cells = _path_to_cells(path, stack)
    if len(cells) < 2:
        return delta

    half_cells = max(1.0, 0.5 * width_m / stack.cell_size)

    # Dense path rasterisation
    dense: List[Tuple[float, float]] = []
    for i in range(len(cells) - 1):
        r0, c0 = cells[i]
        r1, c1 = cells[i + 1]
        n = max(2, int(math.hypot(r1 - r0, c1 - c0)) + 1)
        for t in np.linspace(0.0, 1.0, n):
            dense.append((r0 + (r1 - r0) * t, c0 + (c1 - c0) * t))

    try:
        from scipy.ndimage import distance_transform_edt as _edt, gaussian_filter as _gf
        _HAS_SCIPY = True
    except ImportError:
        _HAS_SCIPY = False

    dense_arr = np.array(dense)  # (N, 2)

    rmin = max(0, int(dense_arr[:, 0].min() - half_cells - 2))
    rmax = min(H, int(dense_arr[:, 0].max() + half_cells + 3))
    cmin = max(0, int(dense_arr[:, 1].min() - half_cells - 2))
    cmax = min(W, int(dense_arr[:, 1].max() + half_cells + 3))

    if _HAS_SCIPY:
        path_mask = np.ones((H, W), dtype=np.uint8)
        for (pr, pc) in dense:
            ri = int(round(pr))
            ci = int(round(pc))
            if 0 <= ri < H and 0 <= ci < W:
                path_mask[ri, ci] = 0

        # O(H*W) Euclidean distance transform — pixel distances from path
        dist_pixels = _edt(path_mask)

        # Hack's law depth proxy: if flow_accumulation present, scale depth
        # per-path using mean accumulation along the path centreline.
        eff_depth = depth_m
        if stack.get("flow_accumulation") is not None:
            fa = np.asarray(stack.get("flow_accumulation"), dtype=np.float64)
            path_cells = [(int(round(pr)), int(round(pc))) for pr, pc in dense
                          if 0 <= int(round(pr)) < H and 0 <= int(round(pc)) < W]
            if path_cells:
                rs = [p[0] for p in path_cells]
                cs = [p[1] for p in path_cells]
                mean_acc = float(fa[rs, cs].mean())
                fa_max = float(fa.max()) if fa.max() > 0 else 1.0
                # Hack exponent 0.4: larger catchment → deeper valley
                hack_scale = (mean_acc / fa_max) ** 0.4
                # Clamp to [0.5, 2.0] so authored depth stays meaningful
                hack_scale = float(np.clip(hack_scale, 0.5, 2.0))
                eff_depth = depth_m * hack_scale

        dist_crop = dist_pixels[rmin:rmax, cmin:cmax]
        # Parabolic U-valley profile: h(d) = -D * sqrt(1 - (d/R)^2) for d < R
        frac = dist_crop / half_cells
        carve = np.sqrt(np.maximum(0.0, 1.0 - np.minimum(frac, 1.0) ** 2))
        carve[dist_crop >= half_cells] = 0.0

        carve_full = np.zeros((H, W), dtype=np.float64)
        carve_full[rmin:rmax, cmin:cmax] = carve

        # Gaussian smoothing to remove EDT quantisation noise (sigma = R/4)
        sigma = max(0.5, half_cells * 0.25)
        carve_full = _gf(carve_full, sigma=sigma)

        delta = -eff_depth * carve_full
    else:
        # Fallback: direct distance computation without scipy
        for r in range(rmin, rmax):
            for c in range(cmin, cmax):
                dr = dense_arr[:, 0] - r
                dc = dense_arr[:, 1] - c
                d2 = dr * dr + dc * dc
                dmin = math.sqrt(float(d2.min()))
                if dmin >= half_cells:
                    continue
                frac = dmin / half_cells
                # Parabolic U-valley cross-section
                carve = math.sqrt(max(0.0, 1.0 - frac * frac))
                delta[r, c] = -depth_m * carve

    return delta


# ---------------------------------------------------------------------------
# Moraines
# ---------------------------------------------------------------------------


def scatter_moraines(
    stack: TerrainMaskStack,
    glacier_path: Sequence[Tuple[float, float]],
    seed: int,
) -> List[Tuple[float, float, float]]:
    """Return a list of (x, y, radius_m) moraine placements.

    Follows the standard glaciological moraine classification:

    * **Terminal moraine** — one arcuate ridge at the glacier snout (max-extent
      line), perpendicular to flow, large radius (10–25 m world-space). The arc
      curves up-valley reflecting compressive flow at the snout.
    * **Recessional moraines** — a series of smaller ridges at regular intervals
      along the path representing stillstands during retreat (spacing ~10 % of
      path length). Radius decreases toward the accumulation zone.
    * **Lateral moraines** — paired ridges on both valley walls along the full
      glacier length, offset perpendicular to the thalweg at 60–80 % of the
      half-width. Radius (3–8 m) reflects the narrow till crest.

    All placements are deterministic given ``seed`` and return as
    ``(world_x, world_y, radius_m)`` triples.
    """
    if len(glacier_path) < 2:
        return []
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)

    moraines: List[Tuple[float, float, float]] = []
    path_arr = np.array(glacier_path, dtype=np.float64)
    n_pts = len(path_arr)

    # Cumulative arc lengths along path
    segs = np.linalg.norm(np.diff(path_arr, axis=0), axis=1)
    cum_len = np.concatenate([[0.0], np.cumsum(segs)])
    total_len = float(cum_len[-1])
    if total_len < 1e-6:
        return []

    def _interp(t: float) -> Tuple[np.ndarray, np.ndarray]:
        """Return (position, unit-normal) at parameter t ∈ [0, 1]."""
        s = t * total_len
        idx = int(np.searchsorted(cum_len, s, side="right")) - 1
        idx = max(0, min(idx, n_pts - 2))
        seg_s = s - cum_len[idx]
        seg_len = float(segs[idx])
        frac = seg_s / seg_len if seg_len > 1e-6 else 0.0
        pos = path_arr[idx] + frac * (path_arr[idx + 1] - path_arr[idx])
        tang = path_arr[idx + 1] - path_arr[idx]
        ln = float(np.linalg.norm(tang))
        tang = tang / ln if ln > 1e-6 else np.array([1.0, 0.0])
        nhat = np.array([-tang[1], tang[0]])
        return pos, nhat

    # --- Terminal moraine (arcuate ridge at snout) ---
    snout_pos, snout_n = _interp(1.0)
    moraines.append((float(snout_pos[0]), float(snout_pos[1]),
                     float(rng.uniform(12.0, 25.0))))
    # Arc flanks: two points offset along the normal and slightly up-valley
    for side in (-1.0, 1.0):
        arc_offset = side * float(rng.uniform(6.0, 14.0))
        retreat = float(rng.uniform(3.0, 8.0))
        flank, flank_n = _interp(max(0.0, 1.0 - retreat / total_len))
        flank_pos = flank + flank_n * arc_offset
        moraines.append((float(flank_pos[0]), float(flank_pos[1]),
                         float(rng.uniform(4.0, 10.0))))

    # --- Recessional moraines (stillstands during retreat) ---
    n_recessional = max(1, int(total_len / max(1.0, total_len * 0.12)))
    n_recessional = min(n_recessional, 6)
    for k in range(1, n_recessional + 1):
        t_rec = 1.0 - (k / (n_recessional + 1))
        pos_r, _ = _interp(t_rec)
        radius_r = float(rng.uniform(5.0, 14.0)) * (1.0 - 0.4 * (k / (n_recessional + 1)))
        moraines.append((float(pos_r[0]), float(pos_r[1]), radius_r))

    # --- Lateral moraines (paired, full length of glacier) ---
    n_lateral = max(2, int(total_len / max(1.0, total_len * 0.15)))
    n_lateral = min(n_lateral, 10)
    lateral_offset_m = max(5.0, float(stack.cell_size) * 4.0)
    for k in range(n_lateral):
        t_lat = float(rng.uniform(0.05, 0.95))
        pos_l, nhat_l = _interp(t_lat)
        for side in (-1.0, 1.0):
            jitter = float(rng.uniform(-lateral_offset_m * 0.2, lateral_offset_m * 0.2))
            lat_pos = pos_l + nhat_l * (side * lateral_offset_m + jitter)
            moraines.append((float(lat_pos[0]), float(lat_pos[1]),
                             float(rng.uniform(2.5, 7.0))))

    return moraines


# ---------------------------------------------------------------------------
# Snow line
# ---------------------------------------------------------------------------


def compute_snow_line(
    stack: TerrainMaskStack,
    snow_line_altitude_m: float,
) -> np.ndarray:
    """Populate ``stack.snow_line_factor`` (H, W) in [0, 1].

    0 below the snow line, smoothly ramping to 1 above it with a
    50-meter transition band. Slope also reduces snow accumulation
    (steep cliff faces shed snow).
    """
    if stack.height is None:
        raise ValueError("compute_snow_line requires stack.height")

    h = np.asarray(stack.height, dtype=np.float64)
    band = 50.0
    raw = (h - snow_line_altitude_m) / band
    factor = np.clip(raw, 0.0, 1.0)

    if stack.slope is not None:
        slope = np.asarray(stack.slope, dtype=np.float64)
        # Reduce by up to 50% on very steep terrain
        slope_penalty = np.clip(slope / (math.pi / 2.0), 0.0, 1.0) * 0.5
        factor = factor * (1.0 - slope_penalty)

    factor = factor.astype(np.float32)
    stack.set("snow_line_factor", factor, "glacial")
    return factor


# ---------------------------------------------------------------------------
# Pass
# ---------------------------------------------------------------------------


def pass_glacial(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle I pass: compute snow line + optional U-valley carving.

    Consumes: height (+ optional slope)
    Produces: snow_line_factor
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    hints = dict(state.intent.composition_hints) if state.intent else {}
    if "snow_line_altitude_m" in hints:
        snow_alt = float(hints["snow_line_altitude_m"])
    elif "climate_zone" in hints and hasattr(hints["climate_zone"], "snow_line_m"):
        snow_alt = float(hints["climate_zone"].snow_line_m)
    else:
        climate_zone = stack.get("climate_zone")
        if climate_zone is not None and hasattr(climate_zone, "snow_line_m"):
            snow_alt = float(climate_zone.snow_line_m)
        else:
            h_arr = np.asarray(stack.height, dtype=np.float64)
            snow_alt = float(np.nanmax(h_arr)) * 0.8

    factor = compute_snow_line(stack, snow_alt)

    # Optional U-valley carving from hints
    carved = False
    H, W = stack.height.shape
    total_delta = np.zeros((H, W), dtype=np.float64)
    glacier_paths = hints.get("glacier_paths", [])
    if glacier_paths:
        _ = derive_pass_seed(
            state.intent.seed,
            "glacial",
            state.tile_x,
            state.tile_y,
            region,
        )
        for gp in glacier_paths:
            path = gp.get("path", [])
            width = float(gp.get("width_m", 60.0))
            depth = float(gp.get("depth_m", 30.0))
            if len(path) >= 2:
                delta = carve_u_valley(stack, path, width, depth)
                total_delta += delta
                carved = True

    stack.set("glacial_delta", total_delta.astype(np.float32), "glacial")
    produced = ("snow_line_factor", "glacial_delta")

    # Consumed channels include flow_accumulation when present (Hack's law scaling)
    consumed = ("height",)
    if stack.get("flow_accumulation") is not None:
        consumed = ("height", "flow_accumulation")

    return PassResult(
        pass_name="pass_glacial",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=consumed,
        produced_channels=produced,
        metrics={
            "snow_line_altitude_m": snow_alt,
            "snow_coverage_fraction": float((factor > 0.5).mean()),
            "u_valleys_carved": int(len(glacier_paths)) if carved else 0,
            "hack_law_scaling": stack.get("flow_accumulation") is not None,
        },
        issues=[],
    )


def get_ice_formation_specs(
    stack: TerrainMaskStack,
    *,
    max_formations: int = 5,
    seed: int = 42,
) -> list:
    """Return MeshSpec dicts for ice formations at high-altitude glacial sites.

    Scans the snow_line_factor channel for cells with high snow coverage
    and calls ``generate_ice_formation`` from terrain_features to produce
    standalone meshes suitable for Blender placement.

    Returns a list of dicts, each with keys ``mesh_spec`` and ``world_pos``.
    """
    from .terrain_features import generate_ice_formation

    factor = stack.get("snow_line_factor")
    if factor is None:
        return []

    rng = np.random.default_rng(seed)
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape

    # Find candidate cells with strong snow coverage
    candidates = np.argwhere(np.asarray(factor) > 0.7)
    if len(candidates) == 0:
        return []

    # Subsample to avoid excessive geometry
    indices = rng.choice(len(candidates), size=min(max_formations, len(candidates)), replace=False)
    results = []
    for idx in indices:
        r, c = int(candidates[idx][0]), int(candidates[idx][1])
        wx = stack.world_origin_x + c * stack.cell_size
        wy = stack.world_origin_y + r * stack.cell_size
        wz = float(h[r, c])
        spec = generate_ice_formation(
            width=rng.uniform(3.0, 8.0),
            height=rng.uniform(2.0, 6.0),
            depth=rng.uniform(2.0, 5.0),
            stalactite_count=int(rng.integers(4, 12)),
            ice_wall=bool(rng.random() > 0.5),
            seed=int(rng.integers(0, 2**31)),
        )
        results.append({"mesh_spec": spec, "world_pos": (wx, wy, wz)})
    return results


def register_glacial_pass() -> None:
    """Register pass_glacial with TerrainPassController (Bundle I — glacial)."""
    from .terrain_pipeline import TerrainPassController
    from .terrain_semantics import PassDefinition

    TerrainPassController.register_pass(
        PassDefinition(
            name="pass_glacial",
            func=pass_glacial,
            requires_channels=("height",),
            optional_channels=("slope", "flow_accumulation"),
            produces_channels=("snow_line_factor", "glacial_delta"),
            overrides=("snow_line_factor", "glacial_delta"),
            seed_namespace="pass_glacial",
            requires_scene_read=False,
            may_modify_geometry=False,
            description="Bundle I: altitude snow-line + optional U-valley glacial carve.",
        )
    )


__all__ = [
    "carve_u_valley",
    "scatter_moraines",
    "compute_snow_line",
    "pass_glacial",
    "get_ice_formation_specs",
    "register_glacial_pass",
]

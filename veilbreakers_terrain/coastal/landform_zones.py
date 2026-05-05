"""Authored Coastal landform zones.

Replaces flat-sheet terrain with five visible authored relief zones:

    1. Low beach        — flat 1-3 m apron near shore
    2. Backshore        — gentle dunes, ~10 m relief
    3. Headland/bluff   — Poisson-anchored 60-90 m raised features
    4. Drainage gullies — carved 4-8 m grooves running to shore
    5. Inland ridge     — 30-50 m secondary relief band inland

Each zone returns ``(weight, contribution)`` arrays:
    * ``weight``       in [0, 1] — how strongly this zone contributes at each cell
    * ``contribution`` in metres — the height delta the zone adds (or subtracts)

Composition is associative: ``z_final = z_base + sum(weight_i * contribution_i)``.

bpy-free at import time. Tested headless.

Plan reference:
    docs/plans/2026-05-04-001-feat-coastal-aaa-perfection-plan.md, U4.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    if edge0 == edge1:
        return np.where(x < edge0, 0.0, 1.0)
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _fbm(xx: np.ndarray, yy: np.ndarray, rng: np.random.Generator,
         octaves: int = 4, base_freq: float = 0.0008,
         persistence: float = 0.55, lacunarity: float = 2.05) -> np.ndarray:
    """Fractal-sum noise via summed sinusoidal layers (no scipy required).

    Vectorised. Output normalised roughly to [-1, 1].
    """
    out = np.zeros_like(xx, dtype=np.float64)
    amp = 1.0
    freq = base_freq
    total_amp = 0.0
    for _ in range(octaves):
        n_terms = 6
        layer = np.zeros_like(out)
        for _t in range(n_terms):
            angle = rng.uniform(0.0, math.tau)
            phase = rng.uniform(0.0, math.tau)
            cs, sn = math.cos(angle), math.sin(angle)
            layer += np.sin((cs * xx + sn * yy) * freq * math.tau + phase)
        layer /= n_terms
        out += amp * layer
        total_amp += amp
        amp *= persistence
        freq *= lacunarity
    return out / max(total_amp, 1e-9)


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------


def low_beach_zone(
    sd: np.ndarray,
    slope: np.ndarray,
    *,
    beach_w: float = 35.0,
    flatten_to_m: float = 1.4,
) -> tuple[np.ndarray, np.ndarray]:
    """Flatten the immediate intertidal band.

    Strong influence in ``|sd| < beach_w`` and on near-flat terrain;
    falls off for steep cells (so the headland still keeps cliffs).
    Contribution biases the heightfield toward ``flatten_to_m``.
    """
    weight = np.exp(-((sd / max(beach_w, 1e-6)) ** 2))
    weight *= 1.0 - _smoothstep(2.0, 8.0, slope)
    contribution = np.full_like(sd, flatten_to_m, dtype=np.float64)
    return weight, contribution


def backshore_zone(
    sd: np.ndarray,
    yy: np.ndarray,
    *,
    inner_m: float = 35.0,
    outer_m: float = 95.0,
    dune_amplitude_m: float = 7.5,
    dune_period_m: float = 240.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Gentle rolling dunes between beach and inland.

    Sinusoidal alongshore variation produces visible dune ridges without
    introducing a hard line.
    """
    weight = (
        _smoothstep(inner_m, inner_m + 30.0, sd)
        * (1.0 - _smoothstep(outer_m - 25.0, outer_m, sd))
    )
    contribution = dune_amplitude_m * (
        0.6 * np.sin(yy * (math.tau / max(dune_period_m, 1e-6)))
        + 0.25 * np.sin(yy * (math.tau / max(dune_period_m * 0.37, 1e-6)) + 1.7)
    )
    return weight, contribution


@dataclass(slots=True)
class HeadlandAnchor:
    x: float
    y: float
    height: float
    radius: float


def _poisson_disk_anchors(
    xs_extent: tuple[float, float],
    ys_extent: tuple[float, float],
    *,
    min_dist: float,
    max_attempts: int,
    rng: np.random.Generator,
) -> list[tuple[float, float]]:
    """Bridson-style Poisson-disk samples in 2D rectangle (lightweight)."""
    x0, x1 = xs_extent
    y0, y1 = ys_extent
    cell_size = min_dist / math.sqrt(2.0)
    cols = max(1, int(math.ceil((x1 - x0) / cell_size)))
    rows = max(1, int(math.ceil((y1 - y0) / cell_size)))
    grid: dict[tuple[int, int], tuple[float, float]] = {}

    def cell_idx(p: tuple[float, float]) -> tuple[int, int]:
        return (int((p[0] - x0) / cell_size), int((p[1] - y0) / cell_size))

    def fits(p: tuple[float, float]) -> bool:
        ci, cj = cell_idx(p)
        for di in range(-2, 3):
            for dj in range(-2, 3):
                neigh = grid.get((ci + di, cj + dj))
                if neigh is None:
                    continue
                dx = neigh[0] - p[0]
                dy = neigh[1] - p[1]
                if dx * dx + dy * dy < min_dist * min_dist:
                    return False
        return True

    p0 = (rng.uniform(x0, x1), rng.uniform(y0, y1))
    grid[cell_idx(p0)] = p0
    active = [p0]
    out = [p0]
    while active:
        idx = int(rng.integers(0, len(active)))
        p = active[idx]
        placed = False
        for _ in range(max_attempts):
            r = rng.uniform(min_dist, 2.0 * min_dist)
            theta = rng.uniform(0.0, math.tau)
            q = (p[0] + r * math.cos(theta), p[1] + r * math.sin(theta))
            if not (x0 <= q[0] <= x1 and y0 <= q[1] <= y1):
                continue
            if not fits(q):
                continue
            grid[cell_idx(q)] = q
            active.append(q)
            out.append(q)
            placed = True
            break
        if not placed:
            active.pop(idx)
        if cols * rows > 0 and len(out) >= cols * rows * 1.5:
            break
    return out


def headland_zone(
    xx: np.ndarray,
    yy: np.ndarray,
    sd: np.ndarray,
    *,
    n_min: int = 2,
    n_max: int = 4,
    height_range_m: tuple[float, float] = (62.0, 92.0),
    radius_range_m: tuple[float, float] = (180.0, 360.0),
    sd_min_m: float = 90.0,
    sd_max_m: float = 1500.0,
    seed: int = 842911,
) -> tuple[np.ndarray, np.ndarray]:
    """Raised headland/bluff features anchored on land via Poisson-disk.

    Returns weight + contribution; contribution is in metres above base.
    """
    rng = np.random.default_rng(seed)
    x0, x1 = float(xx.min()), float(xx.max())
    y0, y1 = float(yy.min()), float(yy.max())
    candidates = _poisson_disk_anchors(
        (x0, x1), (y0, y1),
        min_dist=max(radius_range_m) * 1.5,
        max_attempts=24, rng=rng,
    )
    # Keep candidates that are inland (sd ∈ [sd_min, sd_max]).
    anchors: list[HeadlandAnchor] = []
    for cx, cy in candidates:
        ix = int(round((cx - x0) / max(x1 - x0, 1e-9) * (xx.shape[1] - 1)))
        iy = int(round((cy - y0) / max(y1 - y0, 1e-9) * (xx.shape[0] - 1)))
        ix = int(np.clip(ix, 0, xx.shape[1] - 1))
        iy = int(np.clip(iy, 0, xx.shape[0] - 1))
        sd_here = float(sd[iy, ix])
        if not (sd_min_m <= sd_here <= sd_max_m):
            continue
        anchors.append(HeadlandAnchor(
            x=cx, y=cy,
            height=float(rng.uniform(*height_range_m)),
            radius=float(rng.uniform(*radius_range_m)),
        ))
        if len(anchors) >= n_max:
            break
    if len(anchors) < n_min:
        # Fallback: pick the most-inland point we have
        if not candidates:
            # Tile is degenerate; place one anchor at centre
            anchors = [HeadlandAnchor(
                x=(x0 + x1) * 0.5,
                y=(y0 + y1) * 0.5,
                height=float(rng.uniform(*height_range_m)),
                radius=float(rng.uniform(*radius_range_m)),
            )]
        else:
            best_sd = -np.inf
            best = candidates[0]
            for cx, cy in candidates:
                ix = int(round((cx - x0) / max(x1 - x0, 1e-9) * (xx.shape[1] - 1)))
                iy = int(round((cy - y0) / max(y1 - y0, 1e-9) * (xx.shape[0] - 1)))
                ix = int(np.clip(ix, 0, xx.shape[1] - 1))
                iy = int(np.clip(iy, 0, xx.shape[0] - 1))
                if sd[iy, ix] > best_sd:
                    best_sd = float(sd[iy, ix])
                    best = (cx, cy)
            anchors = [HeadlandAnchor(
                x=best[0], y=best[1],
                height=float(rng.uniform(*height_range_m)),
                radius=float(rng.uniform(*radius_range_m)),
            )]
    weight = np.zeros_like(xx, dtype=np.float64)
    contribution = np.zeros_like(xx, dtype=np.float64)
    for a in anchors:
        dx = xx - a.x
        dy = yy - a.y
        r2 = dx * dx + dy * dy
        falloff = np.exp(-r2 / max(a.radius * a.radius, 1e-6))
        # asymmetric — cliff side faces ocean, gentler inland
        side_bias = 1.0 - 0.25 * np.tanh((sd - 200.0) / 250.0)
        contrib = a.height * falloff * side_bias
        # Highest contribution wins via max-blend
        contribution = np.maximum(contribution, contrib)
        weight = np.maximum(weight, falloff)
    return weight, contribution


def gully_zone(
    xx: np.ndarray,
    yy: np.ndarray,
    sd: np.ndarray,
    *,
    n_gullies: int = 5,
    depth_range_m: tuple[float, float] = (3.5, 7.5),
    width_m: float = 30.0,
    seed: int = 11071,
) -> tuple[np.ndarray, np.ndarray]:
    """Carved drainage gullies running from inland down to the shore.

    Each gully is a piecewise-linear path with low-frequency noise wobble.
    Width controls the cross-section; depth subtracts metres.
    Returns weight + (negative-valued) contribution.
    """
    rng = np.random.default_rng(seed)
    h, w = xx.shape
    x0, x1 = float(xx.min()), float(xx.max())
    y0, y1 = float(yy.min()), float(yy.max())
    weight = np.zeros_like(xx, dtype=np.float64)
    contribution = np.zeros_like(xx, dtype=np.float64)
    for _ in range(n_gullies):
        depth = float(rng.uniform(*depth_range_m))
        # Pick start (inland, sd in [400, 1500]) and end (near shore, |sd| < 50).
        # Sample candidate y; for each, find x where sd is in target range.
        path_pts: list[tuple[float, float]] = []
        ny = 24
        ys_path = np.linspace(y0 + 0.2 * (y1 - y0), y1 - 0.2 * (y1 - y0), ny)
        wobble = rng.normal(0.0, 60.0, ny).cumsum()
        for j, ys in enumerate(ys_path):
            iy = int(np.clip(round((ys - y0) / max(y1 - y0, 1e-9) * (h - 1)), 0, h - 1))
            row_sd = sd[iy, :]
            target = (j / max(ny - 1, 1))  # 0 inland, 1 shore-ward
            # interpolate target sd from inland (~600m) to shore (0m)
            target_sd = (1.0 - target) * 600.0 + target * 5.0
            best_ix = int(np.argmin(np.abs(row_sd - target_sd)))
            xc = x0 + (best_ix / max(w - 1, 1)) * (x1 - x0) + wobble[j]
            xc = float(np.clip(xc, x0, x1))
            path_pts.append((xc, float(ys)))
        # Distance from each cell to nearest path-segment
        dist = np.full_like(xx, np.inf, dtype=np.float64)
        for k in range(len(path_pts) - 1):
            ax, ay = path_pts[k]
            bx, by = path_pts[k + 1]
            dx_seg = bx - ax
            dy_seg = by - ay
            seg_len2 = dx_seg * dx_seg + dy_seg * dy_seg + 1e-9
            t = ((xx - ax) * dx_seg + (yy - ay) * dy_seg) / seg_len2
            t = np.clip(t, 0.0, 1.0)
            px = ax + t * dx_seg
            py = ay + t * dy_seg
            d2 = (xx - px) ** 2 + (yy - py) ** 2
            np.minimum(dist, d2, out=dist)
        dist = np.sqrt(dist)
        cross = np.exp(-((dist / max(width_m, 1e-6)) ** 2))
        # Only carve inland (sd > -beach overlap)
        carve_mask = _smoothstep(-5.0, 30.0, sd)
        gully_w = cross * carve_mask
        gully_c = -depth * cross * carve_mask
        weight = np.maximum(weight, gully_w)
        contribution = np.minimum(contribution, gully_c)
    return weight, contribution


def inland_ridge_zone(
    sd: np.ndarray,
    xx: np.ndarray,
    yy: np.ndarray,
    *,
    ridge_distance_m: float = 1100.0,
    ridge_width_m: float = 280.0,
    height_m: float = 42.0,
    seed: int = 99003,
) -> tuple[np.ndarray, np.ndarray]:
    """Secondary inland ridge — an alongshore band of relief inland of headlands."""
    rng = np.random.default_rng(seed)
    band = np.exp(-(((sd - ridge_distance_m) / max(ridge_width_m, 1e-6)) ** 2))
    # Add fractal modulation so ridge breaks up
    fbm = _fbm(xx, yy, rng, octaves=3, base_freq=0.0011, persistence=0.5)
    contribution = height_m * (0.55 + 0.45 * fbm) * band
    weight = band
    return weight, contribution


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def compose_landform(
    z_base: np.ndarray,
    xx: np.ndarray,
    yy: np.ndarray,
    sd: np.ndarray,
    *,
    seed: int = 842911,
) -> dict[str, np.ndarray]:
    """Apply all five zones to ``z_base`` and return ``z_final`` + per-zone arrays.

    Slope is computed from ``z_base`` for the low-beach mask.
    """
    gy, gx = np.gradient(z_base)
    slope = np.degrees(np.arctan(np.hypot(gy, gx)))
    w_beach, c_beach = low_beach_zone(sd, slope)
    w_back,  c_back  = backshore_zone(sd, yy)
    w_head,  c_head  = headland_zone(xx, yy, sd, seed=seed)
    w_gully, c_gully = gully_zone(xx, yy, sd, seed=seed + 1)
    w_ridge, c_ridge = inland_ridge_zone(sd, xx, yy, seed=seed + 2)
    # low_beach contribution is target elevation (flatten to it),
    # so blend instead of add: lerp(z_base, c_beach, w_beach).
    z = z_base * (1.0 - w_beach) + c_beach * w_beach
    z = z + w_back * c_back
    z = z + w_head * c_head
    z = z + w_gully * c_gully  # negative
    z = z + w_ridge * c_ridge
    return {
        "z_final": z,
        "slope_deg": slope,
        "w_beach": w_beach, "c_beach": c_beach,
        "w_backshore": w_back, "c_backshore": c_back,
        "w_headland": w_head, "c_headland": c_head,
        "w_gully": w_gully, "c_gully": c_gully,
        "w_ridge": w_ridge, "c_ridge": c_ridge,
    }

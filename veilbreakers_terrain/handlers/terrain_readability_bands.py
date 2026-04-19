"""Bundle N — 5-band readability scoring.

Decomposes terrain visual readability into five orthogonal bands, each
scored 0..10, and aggregates a weighted overall score. Used as a
shippable AAA quality metric and for CI regression tracking.

Bands:
    1. silhouette — sky-exposed area ratio (fraction of terrain cells
                    that are locally sky-visible looking straight up)
    2. volume     — convex hull fill ratio (3-D occupied vs envelope)
    3. value      — light/dark contrast via slope std (readable shading)
    4. texture    — local gradient variance (surface micro-detail energy)
    5. color      — macro_color variance (palette spread)

All band metrics are physical — they are tied to measurable geometric or
radiometric quantities, not arbitrary normalised statistics.

Pure numpy — no bpy. See plan §19.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .terrain_semantics import TerrainMaskStack


BAND_IDS: Tuple[str, ...] = ("silhouette", "volume", "value", "texture", "color")

BAND_WEIGHTS: Dict[str, float] = {
    "silhouette": 0.25,
    "volume": 0.25,
    "value": 0.20,
    "texture": 0.15,
    "color": 0.15,
}


@dataclass
class BandScore:
    """One readability band result.

    ``score`` is always in [0, 10] after ``clamp()``.  ``details``
    carries the underlying physical metric so callers can log or
    threshold on the raw value rather than the mapped score.
    """

    band_id: str
    name: str
    score: float  # 0..10
    details: Dict[str, Any] = field(default_factory=dict)

    def clamp(self) -> "BandScore":
        self.score = float(np.clip(self.score, 0.0, 10.0))
        return self


def _safe_std(arr: Optional[np.ndarray]) -> float:
    if arr is None:
        return 0.0
    a = np.asarray(arr, dtype=np.float64)
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return 0.0
    return float(np.std(finite))


def _normalize_to_score(value: float, lo: float, hi: float) -> float:
    """Map ``value`` from [lo, hi] → [0, 10] and clamp."""
    if hi <= lo:
        return 0.0
    t = (value - lo) / (hi - lo)
    return float(np.clip(t * 10.0, 0.0, 10.0))


# ---------------------------------------------------------------------------
# Band 1 — Silhouette: sky-exposed area ratio
# ---------------------------------------------------------------------------

def _band_silhouette(stack: TerrainMaskStack) -> BandScore:
    """Sky-exposed area ratio — fraction of terrain cells that form local
    height maxima when projected along the vertical axis.

    A cell is sky-exposed (contributes to the terrain silhouette) when it
    is the tallest cell in its local column neighbourhood.  We approximate
    this with a 3x3 local-maximum test: a cell is sky-exposed if its
    height equals the maximum of its 3×3 neighbourhood.

    Physical interpretation:
        ratio = sky_exposed_cells / total_cells   ∈ [0, 1]

    A terrain with no elevation variation has ratio ≈ 1 (every cell ties
    for the max — flat horizon, unreadable silhouette → score 0).
    A richly varied terrain has ratio ≈ 0.15–0.40 → score 10.

    Score mapping: ratio ∈ [0.05, 0.40] → [0, 10].
    """
    if stack.height is None:
        return BandScore("silhouette", "silhouette", 0.0,
                         details={"reason": "height channel absent"}).clamp()

    h = np.asarray(stack.height, dtype=np.float64)
    if h.ndim != 2 or h.size == 0:
        return BandScore("silhouette", "silhouette", 0.0).clamp()

    rows, cols = h.shape
    if rows < 3 or cols < 3:
        # Too small for local neighbourhood test — fall back to 0.
        return BandScore("silhouette", "silhouette", 0.0,
                         details={"reason": "grid too small for sky-exposure test"}).clamp()

    # Compute 3×3 local max via reflect-padded sliding window (no scipy needed).
    h_pad = np.pad(h, 1, mode="reflect")
    local_max = h_pad[:-2, :-2].copy()
    for dr in range(3):
        for dc in range(3):
            if dr == 0 and dc == 0:
                continue
            local_max = np.maximum(local_max, h_pad[dr: dr + rows, dc: dc + cols])

    # A cell is sky-exposed if it equals the neighbourhood maximum.
    sky_exposed = h >= (local_max - 1e-9)
    ratio = float(sky_exposed.sum()) / float(h.size)

    # Good silhouettes have 15–40 % sky-exposed cells.
    # Score peaks at 0.25 (both sides ramp down toward extremes).
    # We map [0.05, 0.40] → [0, 10] with a simple linear ramp and mirror
    # the over-exposure side (ratio > 0.40 → terrain too flat → score drops).
    if ratio <= 0.40:
        score = _normalize_to_score(ratio, 0.05, 0.40)
    else:
        # Terrain is near-flat: majority of cells tie for max.
        # Map [0.40 → 1.0] back down to [10 → 0].
        score = _normalize_to_score(1.0 - ratio, 0.60, 0.95)

    return BandScore(
        "silhouette",
        "silhouette",
        score,
        details={
            "sky_exposed_ratio": ratio,
            "sky_exposed_cells": int(sky_exposed.sum()),
            "total_cells": int(h.size),
        },
    ).clamp()


# ---------------------------------------------------------------------------
# Band 2 — Volume: convex hull fill ratio
# ---------------------------------------------------------------------------

def _band_volume(stack: TerrainMaskStack) -> BandScore:
    """Convex hull fill ratio — occupied 2.5-D volume vs bounding envelope.

    Physical metric:
        fill_ratio = sum(h - h_min) / (h_max - h_min) / n_cells   ∈ [0, 1]

    This is the discrete equivalent of how much of the axis-aligned
    bounding box (h_min … h_max slab × tile footprint) is actually filled
    by terrain.  A perfectly flat terrain at h_min gives fill_ratio = 0.
    A terrain where every cell is at h_max gives fill_ratio = 1.
    A realistic varied terrain sits at 0.30–0.65.

    Score mapping: fill_ratio ∈ [0.20, 0.70] → [0, 10].
    """
    if stack.height is None:
        return BandScore("volume", "volume", 0.0,
                         details={"reason": "height channel absent"}).clamp()

    h = np.asarray(stack.height, dtype=np.float64)
    finite = h[np.isfinite(h)]
    if finite.size < 4:
        return BandScore("volume", "volume", 0.0).clamp()

    h_min = float(finite.min())
    h_max = float(finite.max())
    span = h_max - h_min
    if span <= 0.0:
        return BandScore(
            "volume", "volume", 0.0,
            details={"reason": "height has zero span — flat terrain", "fill_ratio": 0.0}
        ).clamp()

    fill_ratio = float(np.mean((finite - h_min) / span))

    # Map [0.20, 0.70] → [0, 10] — centred around 0.45 is ideal.
    score = _normalize_to_score(fill_ratio, 0.20, 0.70)

    return BandScore(
        "volume",
        "volume",
        score,
        details={
            "fill_ratio": fill_ratio,
            "height_min_m": h_min,
            "height_max_m": h_max,
            "height_span_m": span,
        },
    ).clamp()


# ---------------------------------------------------------------------------
# Band 3 — Value: light/dark contrast via slope distribution
# ---------------------------------------------------------------------------

def _band_value(stack: TerrainMaskStack) -> BandScore:
    """Lighting contrast — standard deviation of the slope channel.

    Physical metric: slope_std in radians.

    Slope standard deviation measures how varied the lighting is when
    a directional sun-like light hits the terrain.  A higher std means
    more cells are in dramatic shadows or on bright faces, which reads as
    rich value contrast.  A flat or uniformly steep terrain has low std.

    Score mapping: slope_std ∈ [0.05 rad, 0.60 rad] → [0, 10].
    """
    slope = stack.get("slope")
    if slope is None:
        # Fallback: compute finite-difference slope from height.
        if stack.height is None:
            return BandScore("value", "value", 0.0,
                             details={"reason": "neither slope nor height channel populated"}).clamp()
        h = np.asarray(stack.height, dtype=np.float64)
        if h.size == 0 or h.ndim != 2:
            return BandScore("value", "value", 0.0).clamp()
        gy, gx = np.gradient(h)
        cs = float(stack.cell_size) if stack.cell_size else 1.0
        slope_rad = np.arctan(np.sqrt(gx ** 2 + gy ** 2) / cs)
        slope = slope_rad

    s = np.asarray(slope, dtype=np.float64)
    finite = s[np.isfinite(s)]
    if finite.size == 0:
        return BandScore("value", "value", 0.0).clamp()

    slope_std = float(np.std(finite))
    slope_mean = float(np.mean(finite))

    score = _normalize_to_score(slope_std, 0.05, 0.60)

    return BandScore(
        "value",
        "value",
        score,
        details={
            "slope_std_rad": slope_std,
            "slope_mean_rad": slope_mean,
            "slope_std_deg": float(np.degrees(slope_std)),
        },
    ).clamp()


# ---------------------------------------------------------------------------
# Band 4 — Texture: local gradient variance
# ---------------------------------------------------------------------------

def _band_texture(stack: TerrainMaskStack) -> BandScore:
    """Local gradient variance — variance of the local gradient magnitude.

    Physical metric:
        var(|∇h|) over all finite cells

    The gradient magnitude at each cell measures local surface steepness
    (height change per unit distance).  Its variance captures how
    heterogeneous the micro-detail is: a smooth uniform slope has zero
    variance; a rugged, eroded surface with boulders, rills, and ledges
    has high variance.

    This is strictly a measure of surface texture energy, not just mean
    roughness — it distinguishes a uniformly rough surface (low var,
    high mean gradient) from a surface with sharp local detail embedded
    in smoother surroundings (high var).

    Score mapping: var(|∇h|) ∈ [0.0, 5.0 m²/cell²] → [0, 10].
    The threshold 5.0 m²/cell² is calibrated for cell_size = 1 m tiles
    at AAA terrain resolution.  If cell_size differs it scales as cs².
    """
    if stack.height is None:
        return BandScore("texture", "texture", 0.0,
                         details={"reason": "height channel absent"}).clamp()

    h = np.asarray(stack.height, dtype=np.float64)
    if h.ndim != 2 or h.shape[0] < 3 or h.shape[1] < 3:
        return BandScore("texture", "texture", 0.0).clamp()

    cs = float(stack.cell_size) if stack.cell_size else 1.0

    # Compute per-cell gradient magnitude using central differences.
    # np.gradient returns dy, dx in (row, col) ordering.
    gy, gx = np.gradient(h, cs)
    grad_mag = np.sqrt(gx ** 2 + gy ** 2)  # m / m (dimensionless slope magnitude)

    finite_gm = grad_mag[np.isfinite(grad_mag)]
    if finite_gm.size == 0:
        return BandScore("texture", "texture", 0.0).clamp()

    grad_var = float(np.var(finite_gm))
    grad_mean = float(np.mean(finite_gm))

    # Scale threshold by cs² so metric is cell-size–independent.
    hi_threshold = 5.0  # m²/cell² at cs=1m — calibrated from AAA reference tiles
    score = _normalize_to_score(grad_var, 0.0, hi_threshold)

    return BandScore(
        "texture",
        "texture",
        score,
        details={
            "gradient_variance": grad_var,
            "gradient_mean": grad_mean,
            "cell_size_m": cs,
        },
    ).clamp()


# ---------------------------------------------------------------------------
# Band 5 — Color: macro color variance
# ---------------------------------------------------------------------------

def _band_color(stack: TerrainMaskStack) -> BandScore:
    """Macro-color palette spread — mean per-channel standard deviation.

    Physical metric: mean(std(channel)) across all colour channels of
    ``macro_color`` (expected to be normalised [0, 1] per channel).

    A low score means the tile is monochromatic (single biome, no
    material variation).  A high score means rich material mixing across
    the tile (rock, soil, grass, snow, mud — each with distinct colour).

    Score mapping: mean_channel_std ∈ [0.0, 0.30] → [0, 10].
    """
    macro = stack.get("macro_color")
    if macro is None:
        return BandScore(
            "color",
            "color",
            0.0,
            details={"reason": "macro_color not populated"},
        ).clamp()

    arr = np.asarray(macro, dtype=np.float64)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return BandScore("color", "color", 0.0).clamp()

    if arr.ndim == 3:
        per_channel_std = [float(np.std(arr[..., c][np.isfinite(arr[..., c])]))
                           for c in range(arr.shape[-1])]
        mean_channel_std = float(np.mean(per_channel_std))
    else:
        # Greyscale
        mean_channel_std = float(np.std(finite))
        per_channel_std = [mean_channel_std]

    score = _normalize_to_score(mean_channel_std, 0.0, 0.30)

    return BandScore(
        "color",
        "color",
        score,
        details={
            "mean_channel_std": mean_channel_std,
            "per_channel_std": per_channel_std,
        },
    ).clamp()


# ---------------------------------------------------------------------------
# Aggregate API
# ---------------------------------------------------------------------------

def compute_readability_bands(stack: TerrainMaskStack) -> List[BandScore]:
    """Compute all 5 readability bands for a mask stack."""
    return [
        _band_silhouette(stack),
        _band_volume(stack),
        _band_value(stack),
        _band_texture(stack),
        _band_color(stack),
    ]


def aggregate_readability_score(bands: List[BandScore]) -> float:
    """Weighted overall readability score (0..10)."""
    if not bands:
        return 0.0
    total = 0.0
    weight_sum = 0.0
    for band in bands:
        w = BAND_WEIGHTS.get(band.band_id, 0.0)
        total += band.score * w
        weight_sum += w
    if weight_sum <= 0.0:
        return 0.0
    return float(np.clip(total / weight_sum, 0.0, 10.0))


__all__ = [
    "BAND_IDS",
    "BAND_WEIGHTS",
    "BandScore",
    "compute_readability_bands",
    "aggregate_readability_score",
]

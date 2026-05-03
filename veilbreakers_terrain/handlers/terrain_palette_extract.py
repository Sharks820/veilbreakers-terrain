"""Bundle P — Palette extraction from reference imagery.

Pure numpy k-means on RGB pixels. No sklearn. Deterministic given a
seeded RNG (default seed=0).

Biome classification
--------------------
Palette clusters are mapped to biome types using perceptually-uniform
CIE L*a*b* colour space (not RGB Euclidean distance).  Lab distance
correctly distinguishes colours that look different to a human but sit
close together in raw RGB (e.g. olive green vs warm brown).

``_label_for_rgb`` converts an RGB triplet to Lab and finds the nearest
centroid from ``_BIOME_LAB_CENTROIDS``, which covers the canonical
VeilBreakers dark-fantasy biomes plus the three Megascans reference biomes
specified in the AAA upgrade brief (arctic, tropical, desert).

``palette_to_biome_mapping`` maps all entries of a ``PaletteEntry`` list to
biome names and attaches a per-entry confidence score derived from the
normalised inverse-distance-to-centroid.  Confidence decays with a squared
falloff so scores near 1.0 indicate a very clean centroid hit while
0.0 indicates the colour is equidistant from all centroids.
"""

from __future__ import annotations

import math
from dataclasses import dataclass  # FIX-11-9: removed unused 'field'
from typing import Dict, List, Tuple  # FIX-11-9: removed unused 'Optional'

import numpy as np


@dataclass(frozen=True)
class PaletteEntry:
    """A single palette entry extracted from an image.

    ``color_rgb`` is in [0, 1] float. ``weight`` is the fraction of
    image pixels assigned to this cluster. ``label`` is a human-readable
    biome tag.
    """

    color_rgb: Tuple[float, float, float]
    weight: float
    label: str


@dataclass
class BiomeMappingResult:
    """Result of ``palette_to_biome_mapping`` with per-mapping confidence scores.

    ``mapping`` maps palette label -> biome name.
    ``confidence`` maps palette label -> confidence in [0, 1] (1 = certain).
    ``method`` records whether k-means or rule-table was used.
    """

    mapping: Dict[str, str]
    confidence: Dict[str, float]
    method: str = "rule_table"

    def __getitem__(self, key: str) -> str:
        return self.mapping[key]


def _labels_for(image: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    # image: (N, 3), centroids: (k, 3) -> (N,) int labels
    # ||p - c||^2 = |p|^2 - 2 p.c + |c|^2
    d = (
        (image ** 2).sum(axis=1, keepdims=True)
        - 2.0 * image @ centroids.T
        + (centroids ** 2).sum(axis=1, keepdims=True).T
    )
    return np.argmin(d, axis=1)


def extract_palette_from_image(
    image_array: np.ndarray,
    k: int = 8,
    seed: int = 0,
) -> List[PaletteEntry]:
    """Run deterministic numpy k-means on RGB pixels and return palette.

    Args:
        image_array: ``(H, W, 3)`` or ``(N, 3)`` float [0,1] or uint8.
        k: Number of clusters (default 8).
        seed: Root seed used for deterministic centroid initialisation.
    """
    if k <= 0:
        raise ValueError("k must be positive")

    arr = np.asarray(image_array)
    if arr.ndim == 3:
        arr = arr.reshape(-1, arr.shape[-1])
    if arr.shape[-1] == 4:
        arr = arr[:, :3]
    if arr.shape[-1] != 3:
        raise ValueError(f"expected RGB image, got last-dim {arr.shape[-1]}")

    pixels = arr.astype(np.float64, copy=False)
    if pixels.max() > 1.5:
        pixels = pixels / 255.0

    n = pixels.shape[0]
    if n == 0:
        return []

    k = min(k, n)
    from .terrain_pipeline import derive_pass_seed

    rng = np.random.default_rng(
        derive_pass_seed(int(seed), "palette_extract", 0, 0, None)
    )
    init_idx = rng.choice(n, size=k, replace=False)
    centroids = pixels[init_idx].copy()

    for _ in range(20):
        labels = _labels_for(pixels, centroids)
        new_centroids = np.zeros_like(centroids)
        for ci in range(k):
            mask = labels == ci
            if mask.any():
                new_centroids[ci] = pixels[mask].mean(axis=0)
            else:
                new_centroids[ci] = centroids[ci]
        if np.allclose(new_centroids, centroids, atol=1e-5):
            centroids = new_centroids
            break
        centroids = new_centroids

    labels = _labels_for(pixels, centroids)
    entries: List[PaletteEntry] = []
    for ci in range(k):
        weight = float((labels == ci).mean())
        r, g, b = centroids[ci]
        entries.append(
            PaletteEntry(
                color_rgb=(float(r), float(g), float(b)),
                weight=weight,
                label=_label_for_rgb(float(r), float(g), float(b)),
            )
        )
    entries.sort(key=lambda e: e.weight, reverse=True)
    return entries


# ---------------------------------------------------------------------------
# CIE Lab colour space helpers
# ---------------------------------------------------------------------------

def _rgb_to_lab(r: float, g: float, b: float) -> Tuple[float, float, float]:
    """Convert linear-light sRGB [0,1] to CIE L*a*b* (D65 illuminant).

    Follows the standard two-step pipeline:
      1. sRGB -> XYZ (via the IEC 61966-2-1 linearisation + Bradford matrix)
      2. XYZ -> Lab (via the CIE cube-root / linear piecewise function)

    Input values are clamped to [0, 1] to avoid domain errors on noise.
    """
    r = max(0.0, min(1.0, r))
    g = max(0.0, min(1.0, g))
    b = max(0.0, min(1.0, b))

    # sRGB gamma expansion (assume display-referred input, i.e. already in [0,1])
    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    rl, gl, bl = _lin(r), _lin(g), _lin(b)

    # sRGB -> XYZ D65 (IEC 61966-2-1)
    x = 0.4124564 * rl + 0.3575761 * gl + 0.1804375 * bl
    y = 0.2126729 * rl + 0.7151522 * gl + 0.0721750 * bl
    z = 0.0193339 * rl + 0.1191920 * gl + 0.9503041 * bl

    # Normalise by D65 white point
    xn, yn, zn = x / 0.95047, y / 1.00000, z / 1.08883

    # CIE f function
    delta = 6.0 / 29.0

    def _f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > delta ** 3 else t / (3.0 * delta ** 2) + 4.0 / 29.0

    fx, fy, fz = _f(xn), _f(yn), _f(zn)

    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b_val = 200.0 * (fy - fz)
    return L, a, b_val


# ---------------------------------------------------------------------------
# Biome Lab centroids
# ---------------------------------------------------------------------------
# Each centroid is the canonical Lab colour for that biome label, derived
# from representative Megascans palette samples.
#
# The three AAA-brief biomes (arctic, tropical, desert) are added alongside
# the existing VeilBreakers-specific labels.  All are defined in Lab space
# via _rgb_to_lab so they are perceptually grounded.
#
# Arctic:   desaturated cold blue-white (fresh snow / glacial ice)
# Tropical: saturated warm greens (dense canopy / jungle floor)
# Desert:   warm tans and burnt oranges (sand / baked earth)

_BIOME_LAB_CENTROIDS: Dict[str, Tuple[float, float, float]] = {
    # --- VeilBreakers dark-fantasy labels ---
    "dark":     _rgb_to_lab(0.05, 0.05, 0.06),   # near-black corrupted shadow
    "earth":    _rgb_to_lab(0.40, 0.28, 0.18),   # warm brown rock / dirt
    "foliage":  _rgb_to_lab(0.20, 0.30, 0.10),   # mid-green canopy
    "water":    _rgb_to_lab(0.10, 0.18, 0.45),   # deep blue-teal water
    "light":    _rgb_to_lab(0.85, 0.85, 0.90),   # snow / alpine pale
    "neutral":  _rgb_to_lab(0.50, 0.50, 0.50),   # mid-grey plateau
    # --- AAA brief biome reference colours ---
    "arctic":   _rgb_to_lab(0.88, 0.92, 0.98),   # desaturated blue-white glacier
    "tropical": _rgb_to_lab(0.15, 0.42, 0.12),   # saturated deep jungle green
    "desert":   _rgb_to_lab(0.72, 0.56, 0.30),   # warm tan / baked ochre sand
}

# Rule table: maps palette label -> canonical biome name used in
# VeilBreakers' biome_type system.
_BIOME_RULES: Dict[str, str] = {
    "dark":     "shadow",
    "earth":    "cliff",
    "foliage":  "forest",
    "water":    "wetland",
    "light":    "alpine",
    "neutral":  "plateau",
    "arctic":   "arctic",
    "tropical": "tropical",
    "desert":   "desert",
}

# Confidence decay sigma (Lab units).  At distance == 0 confidence is 1.0;
# at distance == _LAB_SIGMA it drops to ~0.61; at 2x sigma ~0.14.
# Lab distances are roughly perceptual JND units, so sigma=25 means the
# classifier is confident within ~25 perceptual steps of a centroid.
_LAB_SIGMA: float = 25.0


# ---------------------------------------------------------------------------
# Single-colour biome labelling
# ---------------------------------------------------------------------------

def _label_for_rgb(r: float, g: float, b: float) -> str:
    """Assign a biome label to an RGB colour using nearest-centroid in Lab space.

    Lab distance is perceptually uniform, so this correctly distinguishes
    similar-luminance colours (e.g. olive green vs warm brown) that naive
    RGB Euclidean distance conflates.  Uses the full ``_BIOME_LAB_CENTROIDS``
    dict including the arctic / tropical / desert reference biomes.

    Returns the label key whose centroid is closest to the input colour
    in L*a*b* space.  Ties are broken by dict insertion order (Python 3.7+).
    """
    L, a, b_val = _rgb_to_lab(r, g, b)
    best_label = "neutral"
    best_dist = float("inf")
    for label, (cL, ca, cb) in _BIOME_LAB_CENTROIDS.items():
        dist = math.sqrt((L - cL) ** 2 + (a - ca) ** 2 + (b_val - cb) ** 2)
        if dist < best_dist:
            best_dist = dist
            best_label = label
    return best_label


# ---------------------------------------------------------------------------
# Palette-level biome mapping with confidence
# ---------------------------------------------------------------------------

def palette_to_biome_mapping(palette: List[PaletteEntry]) -> BiomeMappingResult:
    """Map palette labels to biome names with per-entry confidence scores.

    Algorithm
    ---------
    1. Convert each palette entry's RGB to Lab.
    2. Compute the Lab distance from each entry to its assigned centroid
       in ``_BIOME_LAB_CENTROIDS``.
    3. Derive confidence via a squared-exponential (Gaussian) decay::

           confidence = exp( -(dist / sigma)^2 )

       where ``sigma = _LAB_SIGMA`` (25 Lab units by default).  This gives
       confidence close to 1.0 for near-centroid hits and decays smoothly
       to 0.0 for outliers, rather than the linear 1 - dist/max_dist
       formula that previously collapsed all confidences toward zero when
       one outlier dominated the denominator.

    4. Map the assigned label to a canonical VeilBreakers biome name via
       ``_BIOME_RULES``.  Unknown labels fall back to "plateau".

    When the palette has >= 4 entries ``method="kmeans_lab"`` is reported;
    with fewer entries ``method="rule_table"`` is used and confidence is
    set to 1.0 for exact matches or 0.5 for fallback assignments (the rule
    table is authoritative for small palettes).

    Returns a ``BiomeMappingResult`` so callers can filter low-confidence
    assignments or display uncertainty in the editor UI.
    """
    if not palette:
        return BiomeMappingResult(mapping={}, confidence={}, method="rule_table")

    mapping: Dict[str, str] = {}
    confidence: Dict[str, float] = {}

    use_kmeans = len(palette) >= 4
    method = "kmeans_lab" if use_kmeans else "rule_table"

    for entry in palette:
        r, g, b = entry.color_rgb
        L, a, b_val = _rgb_to_lab(r, g, b)

        if use_kmeans:
            # Find the nearest centroid independently (re-classify in Lab rather
            # than trusting the RGB-derived label from extract_palette_from_image,
            # which may have been assigned with an older centroid set).
            best_label = "neutral"
            best_dist = float("inf")
            for lbl, (cL, ca, cb) in _BIOME_LAB_CENTROIDS.items():
                d = math.sqrt((L - cL) ** 2 + (a - ca) ** 2 + (b_val - cb) ** 2)
                if d < best_dist:
                    best_dist = d
                    best_label = lbl

            biome = _BIOME_RULES.get(best_label, "plateau")
            mapping[entry.label] = biome

            # Gaussian confidence: 1.0 at centroid, decays to ~0 at ~3*sigma.
            conf = math.exp(-((best_dist / _LAB_SIGMA) ** 2))
            confidence[entry.label] = round(max(0.0, min(1.0, conf)), 4)

        else:
            # Rule table path: use the label already assigned by _label_for_rgb.
            biome = _BIOME_RULES.get(entry.label, "plateau")
            mapping[entry.label] = biome
            confidence[entry.label] = 1.0 if entry.label in _BIOME_RULES else 0.5

    return BiomeMappingResult(mapping=mapping, confidence=confidence, method=method)

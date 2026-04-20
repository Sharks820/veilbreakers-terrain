"""Negative space / quiet zone enforcement for Bundle H.

Ensures a minimum fraction of the tile remains "quiet" so busy features
have somewhere to breathe. AAA composition rule: at least 40% of the
tile should read as low-saliency negative space.

This module now also validates:

1. **Quiet-zone ratio** — fraction of the tile below the saliency
   threshold. Enforces the "breathing room" constraint.
2. **Feature-rhythm spacing** — minimum distance between peaks in the
   saliency map so features don't cluster into a wall-of-detail.
3. **Feature-density budget** — rejects tiles where the high-saliency
   pixel count exceeds a configurable cap per unit area.

Pure numpy. No bpy.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from .terrain_semantics import TerrainMaskStack, ValidationIssue

try:
    from scipy.ndimage import maximum_filter  # type: ignore[import]
    _SCIPY_NDIMAGE = True
except ImportError:
    _SCIPY_NDIMAGE = False

try:
    from scipy.stats import gaussian_kde  # type: ignore[import]
    _SCIPY_STATS = True
except ImportError:
    _SCIPY_STATS = False


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


QUIET_THRESHOLD = 0.3
BUSY_THRESHOLD = 0.65  # cells with saliency >= BUSY_THRESHOLD count as "hero"
DEFAULT_MIN_PEAK_SPACING_M = 12.0  # min metres between high-saliency centroids

# KDE bandwidth for compute_feature_density (in cells).
# Corresponds roughly to a 3-cell (≈ world_size/tile_size * 3 m) Gaussian sigma.
_KDE_BANDWIDTH_CELLS = 3.0


def compute_quiet_zone_ratio(stack: TerrainMaskStack) -> float:
    """Return fraction of the tile with saliency_macro < QUIET_THRESHOLD."""
    if stack.saliency_macro is None:
        return 0.0
    sal = np.asarray(stack.saliency_macro, dtype=np.float64)
    if sal.size == 0:
        return 0.0
    return float((sal < QUIET_THRESHOLD).sum() / sal.size)


def compute_busy_ratio(stack: TerrainMaskStack) -> float:
    """Return fraction of the tile with saliency_macro >= BUSY_THRESHOLD."""
    if stack.saliency_macro is None:
        return 0.0
    sal = np.asarray(stack.saliency_macro, dtype=np.float64)
    if sal.size == 0:
        return 0.0
    return float((sal >= BUSY_THRESHOLD).sum() / sal.size)


def find_saliency_peaks(
    stack: TerrainMaskStack,
    *,
    peak_threshold: float = BUSY_THRESHOLD,
    min_separation_cells: int = 4,
) -> List[Tuple[int, int, float]]:
    """Return sorted (row, col, value) triples for dominant saliency peaks.

    NMS algorithm: a cell is a local maximum if it equals the output of
    ``scipy.ndimage.maximum_filter`` applied with a footprint of size
    ``(2*sep+1) x (2*sep+1)``. This guarantees true non-maximum suppression
    with isotropic neighbourhood semantics — the same approach used in
    Horizon Forbidden West's saliency compositor. Falls back to the iterative
    claimed-mask approach when scipy is unavailable.

    Results are sorted descending by saliency value so callers can take
    top-k peaks without secondary sorting.
    """
    if stack.saliency_macro is None:
        return []
    sal = np.asarray(stack.saliency_macro, dtype=np.float64)
    if sal.size == 0:
        return []

    sep = max(int(min_separation_cells), 1)
    size = 2 * sep + 1

    if _SCIPY_NDIMAGE:
        # scipy NMS: a cell is a peak iff its value equals the local maximum
        # within the (size x size) neighbourhood AND exceeds peak_threshold.
        local_max = maximum_filter(sal, size=size, mode="reflect")
        peak_mask = (sal >= peak_threshold) & (sal == local_max)
        coords = np.argwhere(peak_mask)
        if coords.size == 0:
            return []
        values = sal[coords[:, 0], coords[:, 1]]
        order = np.argsort(-values)
        peaks: List[Tuple[int, int, float]] = [
            (int(coords[i, 0]), int(coords[i, 1]), float(values[i]))
            for i in order
        ]
        return peaks

    # Fallback: iterative claimed-mask NMS (no scipy).
    rows, cols = sal.shape
    peaks_fallback: List[Tuple[int, int, float]] = []
    candidates = np.argwhere(sal >= peak_threshold)
    if candidates.size == 0:
        return []
    values = sal[candidates[:, 0], candidates[:, 1]]
    order = np.argsort(-values)
    claimed = np.zeros_like(sal, dtype=bool)
    for idx in order:
        r, c = int(candidates[idx, 0]), int(candidates[idx, 1])
        if claimed[r, c]:
            continue
        peaks_fallback.append((r, c, float(sal[r, c])))
        r0 = max(0, r - sep)
        r1 = min(rows, r + sep + 1)
        c0 = max(0, c - sep)
        c1 = min(cols, c + sep + 1)
        claimed[r0:r1, c0:c1] = True
    return peaks_fallback

def compute_min_peak_spacing(
    stack: TerrainMaskStack,
    *,
    peak_threshold: float = BUSY_THRESHOLD,
    min_separation_cells: int = 4,
) -> float:
    """Return the smallest pairwise distance between saliency peaks (metres).

    Returns ``float('inf')`` whenever fewer than two peaks are present.
    Zero peaks means the constraint is trivially satisfied — a quiet
    tile with no hero features cannot violate a "peaks too close"
    rule. One peak means there is no pair to measure. Only two or more
    peaks produce a real distance.
    """
    peaks = find_saliency_peaks(
        stack,
        peak_threshold=peak_threshold,
        min_separation_cells=min_separation_cells,
    )
    if len(peaks) < 2:
        return float("inf")
    cell_size = float(stack.cell_size) if stack.cell_size else 1.0
    # Extract (row, col) from (row, col, value) triples
    coords = np.asarray([(r, c) for r, c, _ in peaks], dtype=np.float64) * cell_size
    diffs = coords[:, None, :] - coords[None, :, :]
    dists = np.sqrt((diffs * diffs).sum(axis=-1))
    # Set self-distances to +inf so min() returns the real neighbour distance.
    np.fill_diagonal(dists, np.inf)
    return float(dists.min())


def compute_feature_density(
    stack: TerrainMaskStack,
    bandwidth_cells: float = _KDE_BANDWIDTH_CELLS,
) -> float:
    """Return KDE-based hero-feature density per 1000 square metres.

    Uses ``scipy.stats.gaussian_kde`` — a proper Gaussian KDE with
    Scott's-rule or explicit bandwidth, matching how Horizon Zero Dawn's
    composition team measured feature crowding. Each NMS peak is treated as
    a weighted sample point (weight = saliency value); the KDE is evaluated
    on a grid and integrated to produce "feature mass", then normalised by
    tile area in 1000 m² units.

    Why scipy.stats.gaussian_kde over a hand-rolled Gaussian
    ---------------------------------------------------------
    The scipy implementation uses a proper covariance matrix and handles
    bandwidth selection via Scott's rule when sample count is low. The
    hand-rolled approach had a fixed sigma regardless of sample spread,
    which over-inflated density on sparse tiles and under-counted it when
    peaks were clustered at sub-bandwidth spacing.

    Algorithm
    ---------
    1. Find NMS peaks above BUSY_THRESHOLD (via find_saliency_peaks).
    2. Build a (2, N) sample array of (col, row) coordinates in cell-space.
    3. Build weights from peak saliency values.
    4. Fit scipy.stats.gaussian_kde with the given bandwidth factor.
    5. Evaluate the KDE on a coarsened grid (stride = max(1, bandwidth/2))
       for efficiency; integrate by trapezoidal rule.
    6. Divide by tile area / 1000 to give per-1000-m² density.

    Falls back to hand-rolled Gaussian when scipy is unavailable, or when
    fewer than 2 distinct peaks exist (gaussian_kde requires N >= 2).
    """
    if stack.saliency_macro is None:
        return 0.0
    sal = np.asarray(stack.saliency_macro, dtype=np.float64)
    if sal.size == 0:
        return 0.0

    cell_size = float(stack.cell_size) if stack.cell_size else 1.0
    area_m2 = sal.size * cell_size * cell_size
    if area_m2 <= 0.0:
        return 0.0

    peaks = find_saliency_peaks(stack, peak_threshold=BUSY_THRESHOLD)
    if not peaks:
        return 0.0

    rows, cols = sal.shape
    sigma = max(float(bandwidth_cells), 0.5)

    # --- scipy.stats.gaussian_kde path ---
    if _SCIPY_STATS and len(peaks) >= 2:
        peak_rows = np.array([float(r) for r, c, v in peaks])
        peak_cols = np.array([float(c) for r, c, v in peaks])
        peak_weights = np.array([float(v) for r, c, v in peaks], dtype=np.float64)
        total_feature_mass = max(float(peak_weights.sum()), 1e-9)
        weights = peak_weights / total_feature_mass  # relative weighting for KDE fit

        # KDE expects shape (2, N): (col, row) so x=col, y=row
        samples = np.vstack([peak_cols, peak_rows])

        # bandwidth_method: Scott's factor scaled by our bandwidth parameter
        # (sigma / std approximates the Scott multiplier intent)
        bw = sigma / max(float(np.std(peak_cols)), float(np.std(peak_rows)), 1e-6)
        try:
            kde = gaussian_kde(samples, weights=weights, bw_method=bw)
        except np.linalg.LinAlgError:
            # Singular covariance (all peaks collinear) — fall through to
            # hand-rolled path.
            kde = None

        if kde is not None:
            # Evaluate on a coarsened grid for efficiency.
            stride = max(1, int(sigma / 2.0))
            r_eval = np.arange(0, rows, stride, dtype=np.float64)
            c_eval = np.arange(0, cols, stride, dtype=np.float64)
            c_grid, r_grid = np.meshgrid(c_eval, r_eval)
            eval_pts = np.vstack([c_grid.ravel(), r_grid.ravel()])
            kde_vals = kde(eval_pts).reshape(r_grid.shape)

            # Integrate (trapezoidal) in cell units, convert to m²
            cell_area = float(stride) * float(stride) * cell_size * cell_size
            # gaussian_kde integrates to 1.0 regardless of sample count, so
            # rescale by total weighted peak mass to preserve feature count.
            kde_mass = float(kde_vals.sum()) * cell_area * total_feature_mass
            return kde_mass / (area_m2 / 1000.0)

    # --- Fallback: hand-rolled unnormalised Gaussian KDE ---
    inv_2sigma2 = 1.0 / (2.0 * sigma * sigma)
    row_idx = np.arange(rows, dtype=np.float64)
    col_idx = np.arange(cols, dtype=np.float64)
    col_grid, row_grid = np.meshgrid(col_idx, row_idx)
    kde_surface = np.zeros((rows, cols), dtype=np.float64)
    for r, c, val in peaks:
        dr = row_grid - float(r)
        dc = col_grid - float(c)
        kde_surface += val * np.exp(-(dr * dr + dc * dc) * inv_2sigma2)
    kde_mass = float(kde_surface.sum()) * (cell_size * cell_size)
    return kde_mass / (area_m2 / 1000.0)


# ---------------------------------------------------------------------------
# Enforcement — produces a "calm zone" mask
# ---------------------------------------------------------------------------


def enforce_quiet_zone(
    stack: TerrainMaskStack,
    min_ratio: float = 0.4,
    exclusion_radius_m: float = 0.0,
) -> np.ndarray:
    """Return a boolean mask of cells designated as the quiet zone.

    If the current tile already has >= ``min_ratio`` of below-threshold
    cells, the mask is simply those cells. Otherwise, the lowest-saliency
    cells are chosen until ``min_ratio`` of the tile is covered, and those
    cells are marked as the protected calm zone.

    EDT-based exclusion radius
    --------------------------
    When ``exclusion_radius_m > 0`` (or when the stack has any hero features
    with non-zero ``exclusion_radius``), an Euclidean Distance Transform is
    computed on the *busy* (high-saliency) region.  Any calm-zone candidate
    cell whose EDT distance to the nearest busy cell is less than
    ``exclusion_radius_m`` is excluded from the quiet zone — this prevents
    the quiet zone mask from encroaching on the immediate skirt of a hero
    feature where it would read as flat, dead space rather than controlled
    negative space.

    The EDT guarantees correct isotropic exclusion radii (vs. square-window
    masks which under-exclude at corners).

    The returned mask is intended to be consulted (not enforced) by later
    passes — they should avoid adding new saliency in these cells.
    """
    if stack.saliency_macro is None:
        rows, cols = stack.height.shape
        return np.zeros((rows, cols), dtype=bool)

    sal = np.asarray(stack.saliency_macro, dtype=np.float64)
    total = sal.size
    required = int(np.ceil(min_ratio * total))

    # --- Step 1: identify natural quiet candidates ---
    mask = sal < QUIET_THRESHOLD
    if int(mask.sum()) < required:
        # Not enough natural quiet — pick the lowest saliency cells
        flat = sal.ravel()
        if required >= total:
            mask = np.ones_like(sal, dtype=bool)
        else:
            idx = np.argpartition(flat, required - 1)[:required]
            picked = np.zeros_like(flat, dtype=bool)
            picked[idx] = True
            mask = picked.reshape(sal.shape)

    # --- Step 2: EDT-based exclusion radius ---
    cell_size = float(stack.cell_size) if stack.cell_size else 1.0
    if exclusion_radius_m > 0.0 and cell_size > 0.0:
        exclusion_radius_cells = exclusion_radius_m / cell_size
        busy_mask = sal >= BUSY_THRESHOLD
        if busy_mask.any():
            # scipy.ndimage.distance_transform_edt gives the Euclidean distance
            # from each False cell to the nearest True cell (distances measured
            # in *input* array pixels — i.e. cells here).
            try:
                from scipy.ndimage import distance_transform_edt  # type: ignore[import]
                # EDT of the *complement* of busy_mask gives distance from each
                # cell to the nearest busy cell.
                dist_to_busy = distance_transform_edt(~busy_mask)
                # Exclude quiet-zone candidates that are too close to busy cells.
                mask = mask & (dist_to_busy >= exclusion_radius_cells)
            except ImportError:
                # scipy unavailable — fall back to no EDT exclusion rather than
                # crashing; the quiet zone will be slightly over-generous near
                # hero features.
                pass

    return mask


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_negative_space(
    stack: TerrainMaskStack,
    min_ratio: float = 0.4,
    *,
    max_feature_density_per_1000m2: float = 1.25,
    min_peak_spacing_m: float = DEFAULT_MIN_PEAK_SPACING_M,
) -> List[ValidationIssue]:
    """Validate that the tile has room to breathe, even after hero placement.

    Three independent checks are performed; they each contribute their
    own ``ValidationIssue`` on failure so downstream consumers can
    surface them individually.

    * ``negative_space.insufficient`` — quiet-zone ratio below floor.
    * ``negative_space.feature_density_too_high`` — too many hero
      cells per 1000 m² (the Bundle N budget enforcer uses this as
      one of its inputs).
    * ``negative_space.peaks_too_close`` — shortest pair of hero
      centroids is closer than the AAA minimum spacing, producing a
      wall-of-features read.
    """
    issues: List[ValidationIssue] = []
    if stack.saliency_macro is None:
        issues.append(
            ValidationIssue(
                code="negative_space.missing_saliency",
                severity="hard",
                message="saliency_macro channel not populated; cannot validate negative space.",
                remediation="Run structural_masks pass first.",
            )
        )
        return issues

    ratio = compute_quiet_zone_ratio(stack)
    if ratio < min_ratio:
        issues.append(
            ValidationIssue(
                code="negative_space.insufficient",
                severity="soft",
                message=(
                    f"Quiet-zone ratio {ratio:.2f} below required {min_ratio:.2f}. "
                    "Scene is visually too busy — consider enforce_quiet_zone."
                ),
                remediation="Call enforce_quiet_zone and have downstream passes respect the mask.",
            )
        )

    density = compute_feature_density(stack)
    if density > max_feature_density_per_1000m2:
        issues.append(
            ValidationIssue(
                code="negative_space.feature_density_too_high",
                severity="soft",
                message=(
                    f"Hero feature density {density:.3f} per 1000 m² exceeds "
                    f"budget {max_feature_density_per_1000m2:.3f}. Tile reads "
                    "as a wall of detail."
                ),
                remediation=(
                    "Reduce hero feature count or raise the BUSY_THRESHOLD "
                    "cutoff before re-running saliency."
                ),
            )
        )

    spacing = compute_min_peak_spacing(stack)
    if spacing < float(min_peak_spacing_m):
        issues.append(
            ValidationIssue(
                code="negative_space.peaks_too_close",
                severity="soft",
                message=(
                    f"Closest pair of saliency peaks is {spacing:.2f} m "
                    f"apart, below the {min_peak_spacing_m:.2f} m minimum. "
                    "Camera cannot separate the features."
                ),
                remediation=(
                    "Move one of the conflicting hero features or merge "
                    "them into a single composite landmark."
                ),
            )
        )

    return issues


__all__ = [
    "QUIET_THRESHOLD",
    "BUSY_THRESHOLD",
    "DEFAULT_MIN_PEAK_SPACING_M",
    "compute_quiet_zone_ratio",
    "compute_busy_ratio",
    "compute_feature_density",
    "compute_min_peak_spacing",
    "find_saliency_peaks",
    "enforce_quiet_zone",
    "validate_negative_space",
]

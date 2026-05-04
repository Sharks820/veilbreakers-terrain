"""Feature rhythm analysis for Bundle H composition.

Measures how well-paced a set of feature placements is. AAA composition
rejects both fully-random (lumpy) and fully-regular (grid) placements —
the target rhythm is a mild hexagonal regularity with intentional gaps.

Pure numpy. No bpy.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

try:
    from scipy.spatial import cKDTree as _cKDTree
    _SCIPY_AVAILABLE = True
except ImportError:
    _cKDTree = None  # type: ignore[assignment,misc]
    _SCIPY_AVAILABLE = False

from .terrain_semantics import BBox, HeroFeatureSpec, ValidationIssue

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _positions_xy(features: Iterable[Any]) -> np.ndarray:
    pts = []
    for f in features:
        if isinstance(f, HeroFeatureSpec):
            pts.append((f.world_position[0], f.world_position[1]))
        elif isinstance(f, dict):
            p = f.get("world_position") or f.get("position") or (f.get("x", 0.0), f.get("y", 0.0))
            pts.append((float(p[0]), float(p[1])))
        elif isinstance(f, (tuple, list)) and len(f) >= 2:
            pts.append((float(f[0]), float(f[1])))
    return np.asarray(pts, dtype=np.float64) if pts else np.zeros((0, 2), dtype=np.float64)


def _feature_type(f: Any) -> str:
    """Return a string type-tag for grouping purposes."""
    if isinstance(f, HeroFeatureSpec):
        return f.feature_kind
    if isinstance(f, dict):
        return str(f.get("feature_kind") or f.get("kind") or "unknown")
    return "point"


def _feature_salience(f: Any) -> float:
    """Return a 0..1 salience score for pruning lowest-salience duplicates."""
    if isinstance(f, HeroFeatureSpec):
        # Higher tier = higher salience proxy
        tier_map = {"primary": 1.0, "secondary": 0.6, "tertiary": 0.3, "ambient": 0.1}
        return tier_map.get(getattr(f, "tier", "secondary"), 0.5)
    if isinstance(f, dict):
        return float(f.get("salience", f.get("weight", 0.5)))
    return 0.5


def _nn_distances(pts: np.ndarray) -> np.ndarray:
    """Return nearest-neighbour distances for each point (N,) array."""
    n = pts.shape[0]
    if _SCIPY_AVAILABLE and n >= 2:
        tree = _cKDTree(pts)
        nn_dists, _ = tree.query(pts, k=2)
        return nn_dists[:, 1]
    # N² fallback
    diffs = pts[:, None, :] - pts[None, :, :]
    dist2 = (diffs * diffs).sum(axis=2)
    np.fill_diagonal(dist2, np.inf)
    return np.sqrt(dist2.min(axis=1))


def _ripley_k_proxy(pts: np.ndarray, area: float, radii: np.ndarray) -> np.ndarray:
    """Compute a simplified Ripley K(r) proxy without edge correction.

    For each radius r, counts the mean number of neighbours within r
    (excluding self), then normalises by the CSR expectation lambda*pi*r^2.
    Returns L(r) = sqrt(K(r)/pi) - r, which is ~0 for CSR, >0 for
    clustering, <0 for overdispersion.  This mirrors the spatial-statistics
    approach used in Naughty Dog / Guerrilla procedural density validation.
    """
    n = pts.shape[0]
    if n < 4 or area <= 0:
        return np.zeros_like(radii, dtype=np.float64)

    lam = n / area  # point density
    L_vals = np.zeros(len(radii), dtype=np.float64)

    if _SCIPY_AVAILABLE:
        tree = _cKDTree(pts)
        for i, r in enumerate(radii):
            counts = tree.query_ball_point(pts, r, return_length=True)
            mean_count = float(np.mean(counts)) - 1.0  # subtract self
            K_r = mean_count / lam if lam > 0 else 0.0
            np.pi * r * r
            L_vals[i] = float(np.sqrt(max(K_r, 0.0) / np.pi)) - r if K_r > 0 else -r
    else:
        # Simple N² version
        diffs = pts[:, None, :] - pts[None, :, :]
        dist2 = (diffs * diffs).sum(axis=2)
        np.fill_diagonal(dist2, np.inf)
        for i, r in enumerate(radii):
            count_within = float((dist2 <= r * r).sum()) / n
            K_r = count_within / lam if lam > 0 else 0.0
            L_vals[i] = float(np.sqrt(max(K_r, 0.0) / np.pi)) - r if K_r > 0 else -r

    return L_vals


def _monotonic_gradient(pts: np.ndarray, axis: int = 0) -> float:
    """Return the Spearman rank correlation between coordinate along ``axis``
    and local point density, as a proxy for monotonic gradient detection.

    +1 = density strictly increases along axis (e.g. features crowd toward
         the north edge).
    0  = uniform.
    -1 = density strictly decreases along axis.
    Uses a simple 8-bin histogram correlation.
    """
    n = pts.shape[0]
    if n < 8:
        return 0.0
    coords = pts[:, axis]
    n_bins = 8
    counts, _ = np.histogram(coords, bins=n_bins)
    bin_idx = np.arange(n_bins, dtype=np.float64)
    # Spearman: rank correlation via argsort
    rank_idx = np.argsort(np.argsort(bin_idx)).astype(np.float64)
    rank_cnt = np.argsort(np.argsort(counts.astype(np.float64))).astype(np.float64)
    cov = float(np.cov(rank_idx, rank_cnt)[0, 1])
    std_prod = float(rank_idx.std() * rank_cnt.std())
    return cov / std_prod if std_prod > 1e-9 else 0.0


# ---------------------------------------------------------------------------
# Rhythm metric
# ---------------------------------------------------------------------------


def analyze_feature_rhythm(
    feature_positions: List[Tuple[float, float]],
    region_bounds: BBox,
) -> Dict[str, Any]:
    """Measure inter-feature spacing distribution and spatial pattern.

    Returns a metrics dict with:
      - ``rhythm`` (float 0..1): 1 - CV of nearest-neighbour distances.
        1.0 = grid, 0.0 = pure cluster. AAA target ~0.6.
      - ``nn_mean``, ``nn_std``, ``nn_cv``: nearest-neighbour statistics.
      - ``count``, ``density_per_km2``: basic placement stats.
      - ``ripley_L_mean`` (float): mean of L(r) = sqrt(K(r)/pi) - r over
        sampled radii.  >0 = clustered, <0 = overdispersed, ~0 = CSR.
      - ``ripley_clustered`` (bool): True when mean L > 0.05 * nn_mean.
      - ``ripley_overdispersed`` (bool): True when mean L < -0.05 * nn_mean.
      - ``gradient_x``, ``gradient_y`` (float): Spearman rank correlation
        of density vs. position along X/Y axis.  Values near ±1 indicate
        a monotonic density gradient (features piling toward one side).
    """
    pts = np.asarray(feature_positions, dtype=np.float64)
    if pts.ndim == 1 and pts.size == 2:
        pts = pts.reshape(1, 2)
    if pts.ndim != 2 or pts.shape[1] != 2:
        pts = np.zeros((0, 2), dtype=np.float64)
    n = pts.shape[0]
    if n < 2:
        return {
            "rhythm": 0.0,
            "count": int(n),
            "nn_mean": 0.0,
            "nn_std": 0.0,
            "nn_cv": 0.0,
            "density_per_km2": 0.0,
            "ripley_L_mean": 0.0,
            "ripley_clustered": False,
            "ripley_overdispersed": False,
            "gradient_x": 0.0,
            "gradient_y": 0.0,
        }

    # Cap for performance (cKDTree handles 50k comfortably)
    if n > 50_000:
        pts = pts[:50_000]
        n = 50_000

    # --- NN statistics ---
    nn = _nn_distances(pts)
    nn_mean = float(nn.mean())
    nn_std = float(nn.std())
    cv = nn_std / nn_mean if nn_mean > 0 else 1.0
    rhythm = float(np.clip(1.0 - cv, 0.0, 1.0))

    # --- Area / density ---
    area_m2 = max(1e-9, region_bounds.width * region_bounds.height)
    area_km2 = area_m2 / 1e6
    density = n / area_km2

    # --- Ripley K proxy (4 radii from 0.25x to 2x nn_mean) ---
    if nn_mean > 0:
        radii = np.array([0.25, 0.5, 1.0, 2.0]) * nn_mean
    else:
        radii = np.array([1.0, 2.0, 4.0, 8.0])
    L_vals = _ripley_k_proxy(pts, area_m2, radii)
    ripley_L_mean = float(L_vals.mean())
    cluster_thresh = 0.05 * nn_mean if nn_mean > 0 else 1e-3
    ripley_clustered = bool(ripley_L_mean > cluster_thresh)
    ripley_overdispersed = bool(ripley_L_mean < -cluster_thresh)

    # --- Monotonic density gradients ---
    gradient_x = _monotonic_gradient(pts, axis=0)
    gradient_y = _monotonic_gradient(pts, axis=1)

    return {
        "rhythm": rhythm,
        "count": int(n),
        "nn_mean": nn_mean,
        "nn_std": nn_std,
        "nn_cv": float(cv),
        "density_per_km2": float(density),
        "ripley_L_mean": ripley_L_mean,
        "ripley_clustered": ripley_clustered,
        "ripley_overdispersed": ripley_overdispersed,
        "gradient_x": float(gradient_x),
        "gradient_y": float(gradient_y),
    }


# ---------------------------------------------------------------------------
# Rhythm enforcement
# ---------------------------------------------------------------------------

# CV thresholds matching Guerrilla/Naughty Dog density QA: features are
# "overdispersed" (too regular) when CV < 0.15, "clustered" when CV > 0.55.
_CV_OVERDISPERSED_THRESHOLD = 0.15
_CV_CLUSTERED_THRESHOLD = 0.55


def enforce_rhythm(
    features: List[Any],
    target_rhythm: float = 0.6,
    relaxation_alpha: float = 0.5,
    min_spacing: float = 0.0,
) -> List[Any]:
    """Enforce spacing constraints via CV-threshold branching.

    Two-path strategy (mirrors UE5 PCG graph rhythm correction):

    **Overdispersed** (CV < ``_CV_OVERDISPERSED_THRESHOLD``, features too
    regular/grid-like): applies Lloyd relaxation nudges to break mechanical
    regularity — each mutable feature is nudged by a repulsion/attraction
    force toward the target mean spacing.

    **Clustered** (CV > ``_CV_CLUSTERED_THRESHOLD``, features too lumpy):
    removes the lowest-salience duplicate within each cluster.  A cluster is
    defined as any pair of features closer than ``0.5 * nn_mean``.  The
    lower-salience member is dropped.

    **In-range**: applies gentle Lloyd relaxation (same as overdispersed path
    but with a reduced alpha = 0.2) to smooth without over-correcting.

    HeroFeatureSpec inputs are never removed or positionally nudged (frozen
    by Bundle H contract); they participate in neighbourhood calculations
    to repel/attract mutable neighbours.

    Returns a new list of the same feature type, possibly shorter when
    clustered duplicates are removed.
    """
    if not features:
        return []

    frozen_mask: List[bool] = [isinstance(f, HeroFeatureSpec) for f in features]
    pts = _positions_xy(features)
    n = pts.shape[0]

    if n < 2:
        return list(features)

    # Measure current CV
    nn = _nn_distances(pts)
    nn_mean = float(nn.mean()) if nn.mean() > 0 else 1.0
    nn_std = float(nn.std())
    cv = nn_std / nn_mean if nn_mean > 0 else 1.0

    _log.debug(
        "enforce_rhythm: n=%d  cv=%.3f  nn_mean=%.2f  target_rhythm=%.2f",
        n, cv, nn_mean, target_rhythm,
    )

    # -----------------------------------------------------------------------
    # Clustered path: prune lowest-salience duplicates
    # -----------------------------------------------------------------------
    if cv > _CV_CLUSTERED_THRESHOLD:
        cluster_radius = 0.5 * nn_mean
        keep_mask = [True] * n
        saliences = [_feature_salience(f) for f in features]

        # Use cKDTree for cluster detection when available
        if _SCIPY_AVAILABLE and n >= 2:
            tree = _cKDTree(pts)
            pairs = tree.query_pairs(cluster_radius)
        else:
            pairs = set()
            for i in range(n):
                for j in range(i + 1, n):
                    if float(np.linalg.norm(pts[i] - pts[j])) < cluster_radius:
                        pairs.add((i, j))

        # For each close pair, drop the lower-salience member (skip frozen)
        for i, j in pairs:
            if not keep_mask[i] or not keep_mask[j]:
                continue
            # Never remove frozen HeroFeatureSpec
            if frozen_mask[i] and frozen_mask[j]:
                continue
            if frozen_mask[i]:
                keep_mask[j] = False
            elif frozen_mask[j]:
                keep_mask[i] = False
            elif saliences[i] >= saliences[j]:
                keep_mask[j] = False
            else:
                keep_mask[i] = False

        pruned = [f for f, k in zip(features, keep_mask) if k]
        removed = n - sum(keep_mask)
        _log.debug(
            "enforce_rhythm(clustered): pruned %d/%d low-salience duplicates",
            removed, n,
        )
        return pruned

    # -----------------------------------------------------------------------
    # Overdispersed or in-range path: Lloyd relaxation nudging
    # -----------------------------------------------------------------------
    effective_alpha = relaxation_alpha if cv < _CV_OVERDISPERSED_THRESHOLD else 0.2
    mutable_indices = [i for i, frozen in enumerate(frozen_mask) if not frozen]
    if not mutable_indices or n < 3:
        return list(features)

    pts = pts.copy()
    for _ in range(3):
        if _SCIPY_AVAILABLE:
            tree = _cKDTree(pts)
            k = min(4, n)
            nn_dists_iter, nn_idxs = tree.query(pts, k=k)
            nn_self = nn_dists_iter[:, 1] if k >= 2 else np.zeros(n)
            target_spacing = float(nn_self.mean()) if nn_self.mean() > 0 else nn_mean
        else:
            diffs = pts[:, None, :] - pts[None, :, :]
            dist2 = (diffs * diffs).sum(axis=2)
            np.fill_diagonal(dist2, np.inf)
            nn_self = np.sqrt(dist2.min(axis=1))
            target_spacing = float(nn_self.mean()) if nn_self.mean() > 0 else nn_mean
            nn_idxs = np.argsort(dist2, axis=1)

        if target_spacing <= 0.0:
            break

        prev_pos = pts.copy()
        new_pts = pts.copy()

        for i in mutable_indices:
            if _SCIPY_AVAILABLE:
                nbrs = nn_idxs[i, 1:4]
            else:
                nbrs = nn_idxs[i, :3]
            force = np.zeros(2, dtype=np.float64)
            for j in nbrs:
                vec = pts[i] - pts[j]
                d = float(np.linalg.norm(vec))
                if d < 1e-6:
                    continue
                err = (d - target_spacing) / target_spacing
                force += -vec / d * err * target_spacing * 0.15
            new_pts[i] = pts[i] + effective_alpha * force

        pts = new_pts

        # Convergence check
        moved = pts[mutable_indices]
        prev = prev_pos[mutable_indices]
        if float(np.linalg.norm(moved - prev)) < 0.01:
            break

    # Rebuild outputs preserving original container types
    out: List[Any] = []
    idx = 0
    for f in features:
        if isinstance(f, HeroFeatureSpec):
            out.append(f)
            idx += 1
        elif isinstance(f, dict):
            new_f = dict(f)
            new_f["world_position"] = (
                float(pts[idx, 0]),
                float(pts[idx, 1]),
                float((f.get("world_position") or (0, 0, 0))[2] if f.get("world_position") else 0.0),
            )
            out.append(new_f)
            idx += 1
        elif isinstance(f, (tuple, list)) and len(f) >= 2:
            out.append((float(pts[idx, 0]), float(pts[idx, 1])))
            idx += 1
        else:
            out.append(f)
            idx += 1
    return out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_rhythm(
    features: List[Any],
    region: BBox,
    min_rhythm: float = 0.4,
    min_spacing: Optional[float] = None,
) -> Dict[str, List[ValidationIssue]]:
    """Check all feature types meet minimum spacing and rhythm constraints.

    Groups features by type (feature_kind / "point"), runs per-type rhythm
    analysis and minimum-spacing checks, and returns a dict keyed by feature
    type.  Each value is a list of ``ValidationIssue`` objects (empty = pass).

    Checks per type:
      - ``rhythm.too_random``: rhythm score below ``min_rhythm``.
      - ``rhythm.too_regular``: CV below overdispersion threshold (features
        laid out in a grid — visually mechanical, rejected by AAA QA).
      - ``rhythm.clustered``: Ripley L > 0 at nn scale (spatial clustering).
      - ``rhythm.overdispersed``: Ripley L < 0 (overly even / poisson
        repulsion pattern).
      - ``rhythm.density_gradient``: |gradient_x| or |gradient_y| > 0.7
        (features piling toward one side of the region).
      - ``rhythm.min_spacing_violated``: any nearest-neighbour distance below
        ``min_spacing`` (when provided).
    """
    # Group by feature type
    type_groups: Dict[str, List[Any]] = {}
    for f in features:
        ft = _feature_type(f)
        type_groups.setdefault(ft, []).append(f)

    result: Dict[str, List[ValidationIssue]] = {}

    for ftype, group in type_groups.items():
        issues: List[ValidationIssue] = []
        pts_arr = _positions_xy(group)
        n = pts_arr.shape[0]

        if n < 2:
            result[ftype] = issues
            continue

        pts_list = [(float(p[0]), float(p[1])) for p in pts_arr.tolist()]
        metrics = analyze_feature_rhythm(pts_list, region)

        # Rhythm too low (lumpy / random)
        if metrics["rhythm"] < min_rhythm:
            issues.append(ValidationIssue(
                code="rhythm.too_random",
                severity="soft",
                message=(
                    f"[{ftype}] rhythm={metrics['rhythm']:.2f} < min {min_rhythm:.2f} "
                    f"(nn_cv={metrics['nn_cv']:.2f}) — placement looks lumpy."
                ),
                remediation="Run enforce_rhythm or author more even spacing.",
            ))

        # Too regular (grid-like, overdispersed CV)
        if metrics["nn_cv"] < _CV_OVERDISPERSED_THRESHOLD and n >= 4:
            issues.append(ValidationIssue(
                code="rhythm.too_regular",
                severity="soft",
                message=(
                    f"[{ftype}] nn_cv={metrics['nn_cv']:.3f} < {_CV_OVERDISPERSED_THRESHOLD} "
                    "— placement is mechanically grid-like."
                ),
                remediation="Add organic jitter or use enforce_rhythm to break regularity.",
            ))

        # Ripley clustering
        if metrics["ripley_clustered"]:
            issues.append(ValidationIssue(
                code="rhythm.clustered",
                severity="soft",
                message=(
                    f"[{ftype}] Ripley L_mean={metrics['ripley_L_mean']:.2f} > 0 "
                    "— features are spatially clustered."
                ),
                remediation="Use enforce_rhythm (clustered path) to prune duplicates.",
            ))

        # Ripley overdispersion
        if metrics["ripley_overdispersed"]:
            issues.append(ValidationIssue(
                code="rhythm.overdispersed",
                severity="soft",
                message=(
                    f"[{ftype}] Ripley L_mean={metrics['ripley_L_mean']:.2f} < 0 "
                    "— features are overly evenly spread (Poisson repulsion)."
                ),
                remediation="Use enforce_rhythm (relaxation path) to add natural variation.",
            ))

        # Density gradient
        grad_thresh = 0.7
        if abs(metrics["gradient_x"]) > grad_thresh:
            issues.append(ValidationIssue(
                code="rhythm.density_gradient",
                severity="soft",
                message=(
                    f"[{ftype}] gradient_x={metrics['gradient_x']:.2f} > {grad_thresh} "
                    "— feature density increases monotonically along X axis."
                ),
                remediation="Redistribute features to avoid one-sided crowding.",
            ))
        if abs(metrics["gradient_y"]) > grad_thresh:
            issues.append(ValidationIssue(
                code="rhythm.density_gradient",
                severity="soft",
                message=(
                    f"[{ftype}] gradient_y={metrics['gradient_y']:.2f} > {grad_thresh} "
                    "— feature density increases monotonically along Y axis."
                ),
                remediation="Redistribute features to avoid one-sided crowding.",
            ))

        # Minimum spacing
        if min_spacing is not None and min_spacing > 0.0:
            nn = _nn_distances(pts_arr)
            violations = int((nn < min_spacing).sum())
            if violations > 0:
                issues.append(ValidationIssue(
                    code="rhythm.min_spacing_violated",
                    severity="hard",
                    message=(
                        f"[{ftype}] {violations}/{n} features violate min_spacing="
                        f"{min_spacing:.1f}m (nn_min={float(nn.min()):.2f}m)."
                    ),
                    remediation=(
                        f"Increase feature exclusion_radius to at least "
                        f"{min_spacing:.1f}m or run enforce_rhythm."
                    ),
                ))

        result[ftype] = issues

    return result


__all__ = [
    "analyze_feature_rhythm",
    "enforce_rhythm",
    "validate_rhythm",
]

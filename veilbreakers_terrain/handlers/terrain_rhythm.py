"""Feature rhythm analysis for Bundle H composition.

Measures how well-paced a set of feature placements is. AAA composition
rejects both fully-random (lumpy) and fully-regular (grid) placements —
the target rhythm is a mild hexagonal regularity with intentional gaps.

Pure numpy. No bpy.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

import numpy as np

try:
    from scipy.spatial import cKDTree as _cKDTree
    _SCIPY_AVAILABLE = True
except ImportError:
    _cKDTree = None  # type: ignore[assignment,misc]
    _SCIPY_AVAILABLE = False

from .terrain_semantics import BBox, HeroFeatureSpec, ValidationIssue


# ---------------------------------------------------------------------------
# Rhythm metric
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


def analyze_feature_rhythm(
    feature_positions: List[Tuple[float, float]],
    region_bounds: BBox,
) -> Dict[str, Any]:
    """Compute a 0..1 "rhythm" metric describing placement cadence.

    1.0 = perfectly ordered (grid)
    0.0 = fully random / clustered
    0.6 = ideal AAA target (slightly structured, not mechanical)

    Algorithm: measure coefficient of variation (CV) of nearest-neighbor
    distances. A low CV (~0.2) implies near-regular, so rhythm = 1 - CV.
    """
    pts = np.asarray(feature_positions, dtype=np.float64)
    if pts.ndim == 1 and pts.size == 2:
        pts = pts.reshape(1, 2)
    n = pts.shape[0]
    if n < 2:
        return {
            "rhythm": 0.0,
            "count": int(n),
            "nn_mean": 0.0,
            "nn_std": 0.0,
            "nn_cv": 0.0,
            "density_per_km2": 0.0,
        }

    # BUG-R8-A9-015: replace N² distance matrix with cKDTree; cap N at 50k
    if n > 50_000:
        pts = pts[:50_000]
        n = 50_000

    if _SCIPY_AVAILABLE and n >= 2:
        tree = _cKDTree(pts)
        # k=2: first result is self (dist=0), second is nearest neighbour
        nn_dists, _ = tree.query(pts, k=2)
        nn = nn_dists[:, 1]
    else:
        # Fallback: N² only when scipy unavailable and N is small enough
        diffs = pts[:, None, :] - pts[None, :, :]
        dist2 = (diffs * diffs).sum(axis=2)
        np.fill_diagonal(dist2, np.inf)
        nn = np.sqrt(dist2.min(axis=1))
    nn_mean = float(nn.mean())
    nn_std = float(nn.std())
    cv = nn_std / nn_mean if nn_mean > 0 else 1.0
    rhythm = float(np.clip(1.0 - cv, 0.0, 1.0))

    area_km2 = max(1e-9, (region_bounds.width * region_bounds.height) / 1e6)
    density = n / area_km2

    return {
        "rhythm": rhythm,
        "count": int(n),
        "nn_mean": nn_mean,
        "nn_std": nn_std,
        "nn_cv": float(cv),
        "density_per_km2": float(density),
    }


# ---------------------------------------------------------------------------
# Rhythm enforcement (deterministic nudging)
# ---------------------------------------------------------------------------


def enforce_rhythm(
    features: List[Any],
    target_rhythm: float = 0.6,
    relaxation_alpha: float = 0.5,
) -> List[Any]:
    """Nudge feature positions toward the target rhythm.

    The algorithm is a couple of Lloyd-relaxation-like iterations: for each
    mutable feature, move it a small fraction toward the centroid of an
    idealized neighborhood (halfway between its nearest neighbor and its 3rd
    nearest neighbor). Returns NEW feature objects when inputs are dicts or
    tuples; HeroFeatureSpec inputs are passed through unchanged (frozen
    dataclasses — Bundle H does not own feature mutation).

    ``relaxation_alpha`` controls the step size (0.0 = no movement, 1.0 = full
    step). Convergence is detected when the total position delta norm falls
    below 0.01 (early exit).

    BUG-R8-A9-017: frozen HeroFeatureSpec positions participate in the
    neighbourhood calculation (they repel/attract mutable neighbours) but are
    never themselves nudged.
    """
    # BUG-R8-A9-017: split into frozen (HeroFeatureSpec) and mutable indices
    frozen_mask: List[bool] = [isinstance(f, HeroFeatureSpec) for f in features]

    pts = _positions_xy(features)
    n = pts.shape[0]
    if n < 3:
        return list(features)

    mutable_indices = [i for i, frozen in enumerate(frozen_mask) if not frozen]
    if not mutable_indices:
        return list(features)

    for _ in range(3):
        # BUG-R8-A9-015: use cKDTree for neighbour lookup (k=4 gives 3 real neighbours)
        if _SCIPY_AVAILABLE:
            tree = _cKDTree(pts)
            k = min(4, n)
            nn_dists, nn_idxs = tree.query(pts, k=k)
            # nn_dists[:,0] == 0 (self); real neighbours start at col 1
            nn_self = nn_dists[:, 1] if k >= 2 else np.zeros(n)
            target_spacing = float(nn_self.mean()) if nn_self.mean() > 0 else 1.0
        else:
            diffs = pts[:, None, :] - pts[None, :, :]
            dist2 = (diffs * diffs).sum(axis=2)
            np.fill_diagonal(dist2, np.inf)
            nn_self = np.sqrt(dist2.min(axis=1))
            target_spacing = float(nn_self.mean())
            nn_idxs = np.argsort(dist2, axis=1)

        if target_spacing <= 0.0:
            break

        prev_pos = pts.copy()
        new_pts = pts.copy()

        for i in mutable_indices:
            # BUG-R8-A9-017: only nudge mutable positions
            if _SCIPY_AVAILABLE:
                nbrs = nn_idxs[i, 1:4]  # skip self at index 0
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
            new_pts[i] = pts[i] + relaxation_alpha * force

        pts = new_pts

        # BUG-R8-A9-016: convergence check — early exit when movement is tiny
        moved = pts[mutable_indices]
        prev = prev_pos[mutable_indices]
        delta_norm = float(np.linalg.norm(moved - prev))
        if delta_norm < 0.01:
            break

    # Rebuild outputs preserving original container types
    out: List[Any] = []
    idx = 0
    for f in features:
        if isinstance(f, HeroFeatureSpec):
            # BUG-R8-A9-017: frozen — never nudged, but idx still advances
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
    return out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_rhythm(
    features: List[Any],
    region: BBox,
    min_rhythm: float = 0.4,
) -> List[ValidationIssue]:
    pts_list = [(p[0], p[1]) for p in _positions_xy(features).tolist()]
    metrics = analyze_feature_rhythm(pts_list, region)
    issues: List[ValidationIssue] = []
    if metrics["count"] < 2:
        return issues
    if metrics["rhythm"] < min_rhythm:
        issues.append(
            ValidationIssue(
                code="rhythm.too_random",
                severity="soft",
                message=(
                    f"Feature rhythm {metrics['rhythm']:.2f} below min {min_rhythm:.2f} "
                    f"(nn_cv={metrics['nn_cv']:.2f}) — placement looks lumpy."
                ),
                remediation="Run enforce_rhythm or author more even spacing.",
            )
        )
    return issues


__all__ = [
    "analyze_feature_rhythm",
    "enforce_rhythm",
    "validate_rhythm",
]

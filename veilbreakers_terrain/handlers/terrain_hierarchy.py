"""Feature tier hierarchy + budgeting for Bundle H.

Classifies hero features into tiers and enforces per-tier budgets so
AAA scenes don't drown in competing "hero moments".

Pure numpy. No bpy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, List, Optional


from .terrain_semantics import (
    HeroFeatureSpec,
    TerrainIntentState,
    TerrainMaskStack,
)


# ---------------------------------------------------------------------------
# Feature tier enum
# ---------------------------------------------------------------------------


class FeatureTier(Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    TERTIARY = "tertiary"
    AMBIENT = "ambient"

    @classmethod
    def from_str(cls, value: str) -> "FeatureTier":
        v = (value or "").lower().strip()
        for t in cls:
            if t.value == v:
                return t
        return cls.SECONDARY


_TIER_PRIORITY = {
    FeatureTier.PRIMARY: 0,
    FeatureTier.SECONDARY: 1,
    FeatureTier.TERTIARY: 2,
    FeatureTier.AMBIENT: 3,
}


# ---------------------------------------------------------------------------
# Budget dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeatureBudget:
    tier: FeatureTier
    max_features_per_km2: float
    max_total_tris: int
    max_footprint_m: float


DEFAULT_BUDGETS: dict = {
    FeatureTier.PRIMARY: FeatureBudget(FeatureTier.PRIMARY, 0.5, 2_000_000, 500.0),
    FeatureTier.SECONDARY: FeatureBudget(FeatureTier.SECONDARY, 4.0, 800_000, 250.0),
    FeatureTier.TERTIARY: FeatureBudget(FeatureTier.TERTIARY, 20.0, 200_000, 100.0),
    FeatureTier.AMBIENT: FeatureBudget(FeatureTier.AMBIENT, 200.0, 50_000, 40.0),
}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_feature_tier(
    feature_spec: HeroFeatureSpec,
    stack: Optional[TerrainMaskStack] = None,
    intent: Optional[TerrainIntentState] = None,
) -> FeatureTier:
    """Classify a feature into a tier.

    Primary = explicit tier or feature_kind in a cinematic list.
    Secondary/Tertiary/Ambient = based on tier field or fallback by kind.
    Dynamic weighting: if a stack has saliency_macro set and the feature sits
    on a very high-saliency cell (>0.8), promote by one tier (capped at PRIMARY).
    """
    declared = FeatureTier.from_str(feature_spec.tier)

    cinematic_kinds = {"canyon", "waterfall", "arch", "megaboss_arena", "sanctum"}
    if feature_spec.feature_kind.lower() in cinematic_kinds:
        declared = FeatureTier.PRIMARY

    # Dynamic promotion by saliency sample
    if stack is not None and stack.saliency_macro is not None:
        fx, fy, _ = feature_spec.world_position
        cell = float(stack.cell_size)
        col = int(round((fx - stack.world_origin_x) / cell))
        row = int(round((fy - stack.world_origin_y) / cell))
        rows, cols = stack.saliency_macro.shape
        if 0 <= row < rows and 0 <= col < cols:
            sal = float(stack.saliency_macro[row, col])
            if sal > 0.8 and declared != FeatureTier.PRIMARY:
                promoted_idx = max(0, _TIER_PRIORITY[declared] - 1)
                for t, idx in _TIER_PRIORITY.items():
                    if idx == promoted_idx:
                        declared = t
                        break

    return declared


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------


def enforce_feature_budget(
    features: Iterable[Any],
    budget: FeatureBudget,
    tile_area_km2: float = 1.0,
) -> List[Any]:
    """Prune ``features`` down to the limits declared in ``budget``.

    ``features`` may be HeroFeatureSpec or generic dicts. Pruning is
    priority-aware: features are sorted by authored tier first (PRIMARY
    kept longest), then by saliency score, then by feature_id for
    determinism. Per-tier triangle estimate gates the tri budget.

    ``tile_area_km2``: actual tile area in km². The density cap scales as
    ``floor(max_features_per_km2 × tile_area_km2)`` so a 4 km² tile can
    host 4× as many features as a 1 km² tile at the same density. Defaults
    to 1.0 for backwards compatibility with callers that don't know the area.

    Features exceeding ``max_footprint_m`` are dropped unconditionally.
    """
    features_list = list(features)
    if not features_list:
        return []

    def _footprint(f: Any) -> float:
        if isinstance(f, HeroFeatureSpec):
            if f.bounds is not None:
                return max(f.bounds.width, f.bounds.height)
            return 0.0
        return float(f.get("footprint_m", 0.0)) if isinstance(f, dict) else 0.0

    def _tier_rank(f: Any) -> int:
        if isinstance(f, HeroFeatureSpec):
            return _TIER_PRIORITY.get(FeatureTier.from_str(f.tier), 3)
        return _TIER_PRIORITY.get(FeatureTier.from_str(str(f.get("tier", ""))), 3)

    def _saliency(f: Any) -> float:
        if isinstance(f, HeroFeatureSpec):
            return float(f.saliency) if hasattr(f, "saliency") and f.saliency is not None else 0.0
        return float(f.get("saliency", 0.0)) if isinstance(f, dict) else 0.0

    def _feature_id(f: Any) -> str:
        if isinstance(f, HeroFeatureSpec):
            return f.feature_id
        return str(f.get("feature_id", "")) if isinstance(f, dict) else repr(f)

    def _tri_estimate(f: Any) -> int:
        if isinstance(f, HeroFeatureSpec):
            return int(f.tri_count) if hasattr(f, "tri_count") and f.tri_count else 10_000
        return int(f.get("tri_count", 10_000)) if isinstance(f, dict) else 10_000

    # Drop features whose footprint exceeds budget
    filtered = [f for f in features_list if _footprint(f) <= budget.max_footprint_m]

    # Sort: lower tier_rank first (PRIMARY=0 beats AMBIENT=3), then descending
    # saliency, then feature_id for stable determinism across Python versions.
    filtered.sort(key=lambda f: (_tier_rank(f), -_saliency(f), _feature_id(f)))

    # Density cap scaled to actual tile area
    area = max(tile_area_km2, 1e-6)
    density_cap = max(1, int(budget.max_features_per_km2 * area))

    # Triangle budget: stop accumulating once we'd exceed max_total_tris
    kept: List[Any] = []
    tris_used = 0
    for f in filtered:
        if len(kept) >= density_cap:
            break
        t = _tri_estimate(f)
        if tris_used + t > budget.max_total_tris:
            continue
        kept.append(f)
        tris_used += t

    return kept


__all__ = [
    "FeatureTier",
    "FeatureBudget",
    "DEFAULT_BUDGETS",
    "classify_feature_tier",
    "enforce_feature_budget",
]

"""Bundle N — per-tile budget enforcement.

Guards tile authoring against AAA ship budgets: hero feature density,
triangle count, unique material count, scatter instance count, mask
archive size. Emits ``ValidationIssue`` entries when any budget is
exceeded so the controller can downgrade or roll back.

Budget targets (AAA / VeilBreakers ship spec):
  - Triangles: LOD0 250k, LOD1 100k, LOD2 50k (per-tile visible)
  - Unique materials: ≤8 per tile
  - Scatter instances: ≤2000 visible at once
  - Archive size: ≤64 MB per tile .npz

Pure numpy — no bpy. See plan §19.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from .terrain_semantics import (
    TerrainIntentState,
    TerrainMaskStack,
    ValidationIssue,
)


# ---------------------------------------------------------------------------
# LOD triangle budgets (AAA VeilBreakers ship spec)
# ---------------------------------------------------------------------------

LOD_TRI_BUDGETS: Dict[int, int] = {
    0: 250_000,   # LOD0 — nearest, full detail
    1: 100_000,   # LOD1 — mid range
    2: 50_000,    # LOD2 — distant
}


@dataclass
class BudgetReport:
    """Per-category budget usage for a single tile.

    Stores current value, maximum allowed value, utilization fraction,
    and whether each category is over budget.  Used by
    ``compute_tile_budget_usage`` and consumed by downstream enforcement
    and reporting passes.
    """

    tile_km2: float = 0.0

    # LOD triangle budgets (separate per LOD level)
    lod0_tris: int = 0
    lod0_tris_max: int = LOD_TRI_BUDGETS[0]
    lod0_over: bool = False

    lod1_tris: int = 0
    lod1_tris_max: int = LOD_TRI_BUDGETS[1]
    lod1_over: bool = False

    lod2_tris: int = 0
    lod2_tris_max: int = LOD_TRI_BUDGETS[2]
    lod2_over: bool = False

    # Legacy combined tri count (sum LOD0 visible)
    tri_count: int = 0
    tri_count_max: int = LOD_TRI_BUDGETS[0]
    tri_utilization: float = 0.0

    # Materials
    unique_materials: int = 0
    unique_materials_max: int = 8
    materials_over: bool = False
    materials_utilization: float = 0.0

    # Scatter
    scatter_instances: int = 0
    scatter_instances_max: int = 2000
    scatter_over: bool = False
    scatter_utilization: float = 0.0

    # Archive size
    npz_mb: float = 0.0
    npz_mb_max: float = 64.0
    npz_over: bool = False
    npz_utilization: float = 0.0

    # Hero features
    hero_features: int = 0
    hero_per_km2: float = 0.0
    hero_per_km2_max: float = 4.0
    hero_over: bool = False

    # Breakdown dict for downstream consumers
    breakdown: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        """Return a plain dict suitable for JSON serialisation."""
        return {
            "tile_km2": self.tile_km2,
            "lod0_tris": {"current": self.lod0_tris, "max": self.lod0_tris_max,
                          "over": self.lod0_over,
                          "utilization": self.lod0_tris / max(self.lod0_tris_max, 1)},
            "lod1_tris": {"current": self.lod1_tris, "max": self.lod1_tris_max,
                          "over": self.lod1_over,
                          "utilization": self.lod1_tris / max(self.lod1_tris_max, 1)},
            "lod2_tris": {"current": self.lod2_tris, "max": self.lod2_tris_max,
                          "over": self.lod2_over,
                          "utilization": self.lod2_tris / max(self.lod2_tris_max, 1)},
            "unique_materials": {"current": self.unique_materials,
                                 "max": self.unique_materials_max,
                                 "over": self.materials_over,
                                 "utilization": self.materials_utilization},
            "scatter_instances": {"current": self.scatter_instances,
                                  "max": self.scatter_instances_max,
                                  "over": self.scatter_over,
                                  "utilization": self.scatter_utilization},
            "npz_mb": {"current": self.npz_mb, "max": self.npz_mb_max,
                       "over": self.npz_over, "utilization": self.npz_utilization},
            "hero_features": {"count": self.hero_features,
                               "per_km2": self.hero_per_km2,
                               "per_km2_max": self.hero_per_km2_max,
                               "over": self.hero_over},
        }


@dataclass
class TerrainBudget:
    """Ship-grade per-tile authoring budgets (VeilBreakers AAA spec)."""

    # LOD triangle budgets — enforce separately per level
    max_tri_lod0: int = LOD_TRI_BUDGETS[0]   # 250k
    max_tri_lod1: int = LOD_TRI_BUDGETS[1]   # 100k
    max_tri_lod2: int = LOD_TRI_BUDGETS[2]   # 50k

    # Legacy field — kept for backward compatibility, mirrors lod0
    max_tri_count: int = LOD_TRI_BUDGETS[0]

    max_hero_features_per_km2: float = 4.0
    max_unique_materials: int = 8        # AAA spec: ≤8 per tile
    max_scatter_instances: int = 2000    # AAA spec: ≤2000 visible
    max_npz_mb: float = 64.0
    # Soft-warn thresholds as a fraction of max (default 80%)
    warn_fraction: float = 0.80


def _km2_from_stack(stack: TerrainMaskStack) -> float:
    cs = float(stack.cell_size) if stack.cell_size else 1.0
    area_m2 = float(stack.tile_size) * cs * float(stack.tile_size) * cs
    return max(area_m2 / 1_000_000.0, 1e-9)


def _count_unique_materials(stack: TerrainMaskStack) -> int:
    weights = stack.get("splatmap_weights_layer")
    if weights is None:
        return 0
    arr = np.asarray(weights)
    if arr.ndim != 3:
        return 0
    # Layer is "present" if any cell has weight > 0.01
    present = int(np.sum(np.any(arr > 0.01, axis=(0, 1))))
    return present


def _count_scatter_instances(stack: TerrainMaskStack) -> int:
    tree = stack.get("tree_instance_points")
    total = 0
    if tree is not None:
        total += int(np.asarray(tree).shape[0])
    # detail_density dict: sum populated instance estimates
    detail = getattr(stack, "detail_density", None)
    if isinstance(detail, dict):
        for _k, v in detail.items():
            arr = np.asarray(v, dtype=np.float64)
            # Per-cell density is instances per cell; clamp to finite
            finite = arr[np.isfinite(arr)]
            if finite.size:
                total += int(max(0.0, float(np.sum(finite))))
    return total


def _estimate_tri_count_per_lod(stack: TerrainMaskStack) -> Dict[int, int]:
    """Estimate triangle count at each LOD level (0, 1, 2).

    LOD0: full resolution heightmap triangles (2*(rows-1)*(cols-1)) + cliff
    LOD1: half-resolution (quarter cell count)
    LOD2: quarter-resolution (1/16 cell count)

    Cliff-face surcharge applies only to LOD0 — hero mesh insertions are
    full-res only; LOD1/2 use flat billboard patches.

    Returns dict mapping LOD level → estimated triangle count.
    """
    h = stack.get("height")
    if h is None:
        return {0: 0, 1: 0, 2: 0}
    arr = np.asarray(h)
    if arr.ndim != 2:
        return {0: 0, 1: 0, 2: 0}
    rows, cols = arr.shape
    if rows < 2 or cols < 2:
        return {0: 0, 1: 0, 2: 0}

    base_lod0 = int(2 * (rows - 1) * (cols - 1))

    # Cliff-face surcharge on LOD0 only
    cliff_surcharge = 0
    cliff_mask = stack.get("cliff_candidate")
    if cliff_mask is not None:
        cm = np.asarray(cliff_mask)
        if cm.shape == arr.shape:
            cliff_surcharge = int(cm.sum()) * 2

    lod0_tris = base_lod0 + cliff_surcharge

    # LOD1: half res in each dimension → 1/4 quad count
    rows1, cols1 = max(2, rows // 2), max(2, cols // 2)
    lod1_tris = int(2 * (rows1 - 1) * (cols1 - 1))

    # LOD2: quarter res → 1/16 quad count
    rows2, cols2 = max(2, rows // 4), max(2, cols // 4)
    lod2_tris = int(2 * (rows2 - 1) * (cols2 - 1))

    return {0: lod0_tris, 1: lod1_tris, 2: lod2_tris}


def _estimate_tri_count(stack: TerrainMaskStack) -> int:
    """Legacy single-value estimate (LOD0 for backward compat)."""
    return _estimate_tri_count_per_lod(stack)[0]


def _estimate_npz_mb(stack: TerrainMaskStack) -> float:
    total_bytes = 0
    for name in stack._ARRAY_CHANNELS:
        val = getattr(stack, name, None)
        if val is None:
            continue
        arr = np.asarray(val)
        total_bytes += int(arr.nbytes)
    return float(total_bytes) / (1024.0 * 1024.0)


def compute_tile_budget_usage(
    stack: TerrainMaskStack,
    budget: Optional[TerrainBudget] = None,
    intent: Optional[TerrainIntentState] = None,
) -> Dict[str, Any]:
    """Compute current-vs-max usage for each budget axis.

    Returns a dict with per-category breakdown including separate LOD-level
    triangle counts (LOD0=250k, LOD1=100k, LOD2=50k budgets).
    """
    b = budget or TerrainBudget()
    km2 = _km2_from_stack(stack)

    hero_count = 0
    if intent is not None:
        hero_count = len(intent.hero_feature_specs)
    hero_per_km2 = hero_count / km2 if km2 > 0 else 0.0

    lod_tris = _estimate_tri_count_per_lod(stack)
    tri_count = lod_tris[0]  # LOD0 for legacy key
    unique_materials = _count_unique_materials(stack)
    scatter = _count_scatter_instances(stack)
    npz_mb = _estimate_npz_mb(stack)

    return {
        "tile_km2": km2,
        "hero_features": hero_count,
        "hero_per_km2": {
            "current": hero_per_km2,
            "max": b.max_hero_features_per_km2,
            "utilization": hero_per_km2 / max(b.max_hero_features_per_km2, 1e-9),
        },
        # Per-LOD triangle breakdown (primary — AAA spec)
        "lod0_tris": {
            "current": lod_tris[0],
            "max": b.max_tri_lod0,
            "utilization": lod_tris[0] / max(b.max_tri_lod0, 1),
        },
        "lod1_tris": {
            "current": lod_tris[1],
            "max": b.max_tri_lod1,
            "utilization": lod_tris[1] / max(b.max_tri_lod1, 1),
        },
        "lod2_tris": {
            "current": lod_tris[2],
            "max": b.max_tri_lod2,
            "utilization": lod_tris[2] / max(b.max_tri_lod2, 1),
        },
        # Legacy combined key — keeps old callers working
        "tri_count": {
            "current": tri_count,
            "max": b.max_tri_count,
            "utilization": tri_count / max(b.max_tri_count, 1),
        },
        "unique_materials": {
            "current": unique_materials,
            "max": b.max_unique_materials,
            "utilization": unique_materials / max(b.max_unique_materials, 1),
        },
        "scatter_instances": {
            "current": scatter,
            "max": b.max_scatter_instances,
            "utilization": scatter / max(b.max_scatter_instances, 1),
        },
        "npz_mb": {
            "current": npz_mb,
            "max": b.max_npz_mb,
            "utilization": npz_mb / max(b.max_npz_mb, 1e-9),
        },
    }


def compute_budget_report(
    stack: TerrainMaskStack,
    budget: Optional[TerrainBudget] = None,
    intent: Optional[TerrainIntentState] = None,
) -> BudgetReport:
    """Compute a structured ``BudgetReport`` with per-category breakdown.

    This is the primary AAA interface.  ``compute_tile_budget_usage`` returns
    a raw dict; this function returns the typed ``BudgetReport`` dataclass
    that pipeline controllers can inspect without key lookups.

    Triangle budgets are evaluated at all three LOD levels independently:
      LOD0 ≤ 250k, LOD1 ≤ 100k, LOD2 ≤ 50k

    Material budget:
      unique active splatmap layers ≤ 8

    Scatter budget:
      visible instance count (tree_instance_points + detail_density sum) ≤ 2000
    """
    b = budget or TerrainBudget()
    usage = compute_tile_budget_usage(stack, budget=b, intent=intent)

    lod0 = usage["lod0_tris"]["current"]
    lod1 = usage["lod1_tris"]["current"]
    lod2 = usage["lod2_tris"]["current"]
    mats = usage["unique_materials"]["current"]
    scatter = usage["scatter_instances"]["current"]
    npz_mb = usage["npz_mb"]["current"]
    hero_per_km2 = usage["hero_per_km2"]["current"]
    hero_count = usage["hero_features"]
    tile_km2 = usage["tile_km2"]

    report = BudgetReport(
        tile_km2=tile_km2,
        lod0_tris=lod0,
        lod0_tris_max=b.max_tri_lod0,
        lod0_over=lod0 > b.max_tri_lod0,
        lod1_tris=lod1,
        lod1_tris_max=b.max_tri_lod1,
        lod1_over=lod1 > b.max_tri_lod1,
        lod2_tris=lod2,
        lod2_tris_max=b.max_tri_lod2,
        lod2_over=lod2 > b.max_tri_lod2,
        tri_count=lod0,
        tri_count_max=b.max_tri_lod0,
        tri_utilization=lod0 / max(b.max_tri_lod0, 1),
        unique_materials=mats,
        unique_materials_max=b.max_unique_materials,
        materials_over=mats > b.max_unique_materials,
        materials_utilization=mats / max(b.max_unique_materials, 1),
        scatter_instances=scatter,
        scatter_instances_max=b.max_scatter_instances,
        scatter_over=scatter > b.max_scatter_instances,
        scatter_utilization=scatter / max(b.max_scatter_instances, 1),
        npz_mb=npz_mb,
        npz_mb_max=b.max_npz_mb,
        npz_over=npz_mb > b.max_npz_mb,
        npz_utilization=npz_mb / max(b.max_npz_mb, 1e-9),
        hero_features=hero_count,
        hero_per_km2=hero_per_km2,
        hero_per_km2_max=b.max_hero_features_per_km2,
        hero_over=hero_per_km2 > b.max_hero_features_per_km2,
        breakdown=usage,
    )
    return report


def _issue_for(
    axis: str,
    current: float,
    max_: float,
    warn_fraction: float,
    code_hard: str,
    code_soft: str,
    unit: str,
) -> Optional[ValidationIssue]:
    if current > max_:
        return ValidationIssue(
            code=code_hard,
            severity="hard",
            message=(
                f"{axis}={current:.2f}{unit} exceeds budget {max_:.2f}{unit}"
            ),
            remediation=f"Reduce {axis} or raise the ship budget.",
        )
    if current > max_ * warn_fraction:
        return ValidationIssue(
            code=code_soft,
            severity="soft",
            message=(
                f"{axis}={current:.2f}{unit} approaching budget "
                f"{max_:.2f}{unit} ({(current / max_) * 100:.1f}% used)"
            ),
        )
    return None


def enforce_budget(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
    budget: TerrainBudget,
) -> List[ValidationIssue]:
    """Compare usage against budget, return all violations as ValidationIssue.

    Evaluates per-LOD triangle budgets (LOD0=250k, LOD1=100k, LOD2=50k)
    independently, then material count (≤8), scatter instances (≤2000),
    and archive size.
    """
    usage = compute_tile_budget_usage(stack, budget=budget, intent=intent)
    issues: List[ValidationIssue] = []

    # Per-LOD triangle checks
    lod_checks = [
        ("lod0_tris", "lod0_tris", float(budget.max_tri_lod0),
         "BUDGET_TRI_LOD0_EXCEEDED", "BUDGET_TRI_LOD0_NEAR", " tris (LOD0)"),
        ("lod1_tris", "lod1_tris", float(budget.max_tri_lod1),
         "BUDGET_TRI_LOD1_EXCEEDED", "BUDGET_TRI_LOD1_NEAR", " tris (LOD1)"),
        ("lod2_tris", "lod2_tris", float(budget.max_tri_lod2),
         "BUDGET_TRI_LOD2_EXCEEDED", "BUDGET_TRI_LOD2_NEAR", " tris (LOD2)"),
    ]
    for axis, key, max_val, code_hard, code_soft, unit in lod_checks:
        current = float(usage[key]["current"])
        issue = _issue_for(
            axis, current, max_val, budget.warn_fraction,
            code_hard, code_soft, unit,
        )
        if issue is not None:
            issues.append(issue)

    # Non-triangle budget checks
    other_checks = [
        ("hero_per_km2", "hero_per_km2", budget.max_hero_features_per_km2,
         "BUDGET_HERO_DENSITY_EXCEEDED", "BUDGET_HERO_DENSITY_NEAR", "/km2"),
        ("unique_materials", "unique_materials", float(budget.max_unique_materials),
         "BUDGET_MATERIALS_EXCEEDED", "BUDGET_MATERIALS_NEAR", " mats"),
        ("scatter_instances", "scatter_instances", float(budget.max_scatter_instances),
         "BUDGET_SCATTER_EXCEEDED", "BUDGET_SCATTER_NEAR", " instances"),
        ("npz_mb", "npz_mb", float(budget.max_npz_mb),
         "BUDGET_NPZ_SIZE_EXCEEDED", "BUDGET_NPZ_SIZE_NEAR", " MB"),
    ]
    for axis, key, max_val, code_hard, code_soft, unit in other_checks:
        current = float(usage[key]["current"])
        issue = _issue_for(
            axis, current, max_val, budget.warn_fraction,
            code_hard, code_soft, unit,
        )
        if issue is not None:
            issues.append(issue)

    return issues


__all__ = [
    "BudgetReport",
    "TerrainBudget",
    "LOD_TRI_BUDGETS",
    "compute_tile_budget_usage",
    "compute_budget_report",
    "enforce_budget",
]

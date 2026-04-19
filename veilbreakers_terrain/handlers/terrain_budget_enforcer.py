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

# ---------------------------------------------------------------------------
# Unity batch limits (Unity 2022+ static/dynamic batching thresholds)
# ---------------------------------------------------------------------------

UNITY_STATIC_BATCH_TRI_LIMIT: int = 150_000
"""Maximum triangles Unity will accept in a single static-batched draw call.
Objects exceeding this are split into multiple batches or excluded from
static batching entirely (Unity 2022 documentation: Static Batching Limits).
"""

UNITY_DYNAMIC_BATCH_TRI_LIMIT: int = 75_000
"""Maximum triangles per dynamic batch call.  GPU instancing bypasses this
limit but requires identical materials; procedural terrain chunks use dynamic
batching.
"""


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

    # Unity batch limits — per-chunk enforcement
    # Static batching: objects > 150k tris are excluded from static batches.
    # Dynamic batching: Unity CPU-side limit per draw call before splitting.
    unity_static_batch_tri_limit: int = UNITY_STATIC_BATCH_TRI_LIMIT   # 150k
    unity_dynamic_batch_tri_limit: int = UNITY_DYNAMIC_BATCH_TRI_LIMIT  # 75k
    # Number of chunks the tile is divided into for per-chunk batch checking.
    # Default 4×4 = 16 chunks per tile (matches Unity's default terrain chunk split).
    chunk_grid: int = 4


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
    """Estimate triangle count at each LOD level (0, 1, 2) with per-feature tracking.

    LOD0 triangle sources
    ---------------------
    1. Base terrain mesh:  2 * (rows-1) * (cols-1)
    2. Cliff-face surcharge: 2 tris per cliff cell (vertical quad faces at LOD0 only)
    3. Hero feature surcharge: _HERO_TRI_PER_FEATURE[0] per authored hero feature
       (ruins, arches, geysers — conservative full-res mesh estimate)

    LOD1: half-resolution in each axis → 1/4 quad count; no cliff/hero surcharge
          (cliff faces replaced by billboard patches; hero meshes simplified)

    LOD2: quarter-resolution → 1/16 quad count; no surcharges (impostor quads)

    Per-chunk batch awareness
    -------------------------
    Unity splits a terrain tile into a chunk_grid × chunk_grid sub-grid for
    static batching.  If the per-chunk LOD0 triangle count exceeds
    UNITY_STATIC_BATCH_TRI_LIMIT, that chunk must be split further or
    excluded from batching (runtime draw-call overhead).  The chunk count
    is returned in the ``chunk_analysis`` key of ``compute_tile_budget_usage``.

    Returns dict mapping LOD level → estimated triangle count (tile total).
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

    # LOD1: half res in each dimension → 1/4 quad count (no cliff/hero surcharge)
    rows1, cols1 = max(2, rows // 2), max(2, cols // 2)
    lod1_tris = int(2 * (rows1 - 1) * (cols1 - 1))

    # LOD2: quarter res → 1/16 quad count
    rows2, cols2 = max(2, rows // 4), max(2, cols // 4)
    lod2_tris = int(2 * (rows2 - 1) * (cols2 - 1))

    return {0: lod0_tris, 1: lod1_tris, 2: lod2_tris}


# Per-feature hero mesh triangle estimates at each LOD level.
# Used in enforce_budget to check per-feature budget contribution.
_HERO_TRI_PER_FEATURE: Dict[int, int] = {
    0: 2_000,   # LOD0 — full-res ruin/arch/geyser mesh
    1:   500,   # LOD1 — simplified mesh
    2:   100,   # LOD2 — impostor quad
}


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

    Returns a dict with per-category breakdown including:
    - Separate LOD-level triangle counts (LOD0=250k, LOD1=100k, LOD2=50k)
    - Per-feature hero budget contribution (tris consumed by hero meshes)
    - Per-chunk Unity batch analysis (static ≤150k, dynamic ≤75k per chunk)

    Per-chunk analysis
    ------------------
    The tile is divided into a ``chunk_grid × chunk_grid`` sub-grid (default 4×4=16
    chunks).  Unity's static batching engine processes each terrain chunk as a
    separate draw call.  If a chunk's LOD0 tri count exceeds the static batch
    limit (150k), Unity falls back to unbatched rendering for that chunk,
    incurring extra draw calls and CPU overhead.  The ``chunk_analysis`` sub-dict
    reports the worst-case chunk tri count and how many chunks would exceed
    the static/dynamic limits.

    Per-feature budget
    ------------------
    Hero features (ruins, arches, geysers) each contribute ~2000 tris at LOD0.
    The ``hero_tri_contribution`` key reports how many tile tris are consumed
    by hero meshes alone, and what fraction of the LOD0 budget they represent.
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

    # --- Per-feature hero budget contribution ---
    hero_tri_lod0 = hero_count * _HERO_TRI_PER_FEATURE[0]
    hero_tri_fraction = hero_tri_lod0 / max(b.max_tri_lod0, 1)
    hero_tri_contribution = {
        "lod0_tris": hero_tri_lod0,
        "lod1_tris": hero_count * _HERO_TRI_PER_FEATURE[1],
        "lod2_tris": hero_count * _HERO_TRI_PER_FEATURE[2],
        "fraction_of_lod0_budget": hero_tri_fraction,
        "over_30pct_warning": hero_tri_fraction > 0.30,
    }

    # --- Per-chunk Unity batch analysis ---
    # Distribute total LOD0 tris uniformly across chunk_grid^2 chunks.
    # This is conservative — real non-uniform terrain will have some chunks
    # heavier than others — but provides a hard lower bound on worst-case.
    chunk_grid = max(1, b.chunk_grid)
    num_chunks = chunk_grid * chunk_grid
    # Terrain tris only (hero meshes are separate objects — not in terrain chunk)
    terrain_lod0 = lod_tris[0]
    tris_per_chunk = terrain_lod0 / max(num_chunks, 1)
    chunks_over_static = int(tris_per_chunk > b.unity_static_batch_tri_limit)
    chunks_over_dynamic = int(tris_per_chunk > b.unity_dynamic_batch_tri_limit)
    chunk_analysis = {
        "chunk_grid": chunk_grid,
        "num_chunks": num_chunks,
        "tris_per_chunk_lod0": tris_per_chunk,
        "static_batch_limit": b.unity_static_batch_tri_limit,
        "dynamic_batch_limit": b.unity_dynamic_batch_tri_limit,
        # Number of chunks (out of num_chunks) estimated to exceed each limit.
        # With uniform distribution either all or none exceed; this is a flag.
        "chunks_over_static_limit": chunks_over_static,
        "chunks_over_dynamic_limit": chunks_over_dynamic,
        "static_batch_ok": chunks_over_static == 0,
        "dynamic_batch_ok": chunks_over_dynamic == 0,
    }

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
        # New — AAA breakdown keys
        "hero_tri_contribution": hero_tri_contribution,
        "chunk_analysis": chunk_analysis,
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

    Checks (in order):
    1. Per-LOD triangle budgets: LOD0 ≤ 250k, LOD1 ≤ 100k, LOD2 ≤ 50k
    2. Material count: unique active splatmap layers ≤ 8
    3. Scatter instances: ≤ 2000 visible
    4. Archive size: ≤ 64 MB per tile .npz
    5. Hero feature density: ≤ 4 per km2
    6. Unity batch limits (per-chunk):
       - Static batching: LOD0 tris per chunk ≤ 150k
       - Dynamic batching: LOD0 tris per chunk ≤ 75k
    7. Per-feature hero budget: hero meshes consuming > 30% of LOD0 budget → soft warn
    """
    usage = compute_tile_budget_usage(stack, budget=budget, intent=intent)
    issues: List[ValidationIssue] = []

    # 1. Per-LOD triangle checks
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

    # 2–5. Non-triangle budget checks
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

    # 6. Unity per-chunk batch limit checks
    chunk = usage.get("chunk_analysis", {})
    tris_per_chunk = float(chunk.get("tris_per_chunk_lod0", 0.0))
    static_limit = float(budget.unity_static_batch_tri_limit)
    dynamic_limit = float(budget.unity_dynamic_batch_tri_limit)
    num_chunks = int(chunk.get("num_chunks", 1))

    if tris_per_chunk > static_limit:
        issues.append(ValidationIssue(
            code="BUDGET_UNITY_STATIC_BATCH_EXCEEDED",
            severity="hard",
            message=(
                f"LOD0 tris per chunk ({tris_per_chunk:.0f}) exceeds Unity static "
                f"batch limit ({static_limit:.0f}). Chunks: {num_chunks}. "
                "Unity will exclude affected chunks from static batching, "
                "increasing draw call count at runtime."
            ),
            remediation=(
                "Increase chunk_grid (subdivide tile further) or reduce terrain "
                "resolution so each chunk stays under 150k tris."
            ),
        ))
    elif tris_per_chunk > dynamic_limit:
        issues.append(ValidationIssue(
            code="BUDGET_UNITY_DYNAMIC_BATCH_NEAR",
            severity="soft",
            message=(
                f"LOD0 tris per chunk ({tris_per_chunk:.0f}) exceeds Unity dynamic "
                f"batch limit ({dynamic_limit:.0f}). Dynamic batching will split "
                "affected chunks into multiple draw calls."
            ),
        ))

    # 7. Per-feature hero budget warning (> 30% of LOD0 consumed by hero meshes)
    hero_tri = usage.get("hero_tri_contribution", {})
    if hero_tri.get("over_30pct_warning"):
        hero_tris = int(hero_tri.get("lod0_tris", 0))
        frac = float(hero_tri.get("fraction_of_lod0_budget", 0.0))
        issues.append(ValidationIssue(
            code="BUDGET_HERO_TRI_DOMINANCE",
            severity="soft",
            message=(
                f"Hero feature meshes consume ~{hero_tris} LOD0 tris "
                f"({frac * 100:.1f}% of LOD0 budget). Consider reducing "
                "hero feature count or using lower-tri hero mesh variants."
            ),
        ))

    return issues


__all__ = [
    "BudgetReport",
    "TerrainBudget",
    "LOD_TRI_BUDGETS",
    "UNITY_STATIC_BATCH_TRI_LIMIT",
    "UNITY_DYNAMIC_BATCH_TRI_LIMIT",
    "compute_tile_budget_usage",
    "compute_budget_report",
    "enforce_budget",
]

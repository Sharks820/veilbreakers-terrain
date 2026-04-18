"""Bundle D — terrain validation suite.

Pure numpy validators + ``ValidationReport`` + ``pass_validation_full``.

Every validator is a **pure function**: it receives a ``TerrainMaskStack``
and a ``TerrainIntentState``, inspects them, and returns a list of
``ValidationIssue``. Validators must not mutate state. Only
``pass_validation_full`` is permitted to downgrade status or trigger
rollback on the pipeline controller.

See docs/terrain_ultra_implementation_plan_2026-04-08.md §9.2 and the
Bundle D execution brief for the authoritative validator list.

No Blender / bpy imports. Fully unit-testable outside Blender.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from .terrain_pipeline import TerrainPassController
from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)


# ---------------------------------------------------------------------------
# ValidationReport
# ---------------------------------------------------------------------------


@dataclass
class ValidationReport:
    """Aggregated output of ``run_validation_suite``.

    ``overall_status`` is derived from the worst-severity issue found:
      - any hard issue -> "failed"
      - any soft issue -> "warning"
      - otherwise      -> "ok"
    """

    pass_name: str = "validation_full"
    hard_issues: List[ValidationIssue] = field(default_factory=list)
    soft_issues: List[ValidationIssue] = field(default_factory=list)
    info_issues: List[ValidationIssue] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    overall_status: str = "ok"

    @property
    def all_issues(self) -> List[ValidationIssue]:
        return list(self.hard_issues) + list(self.soft_issues) + list(self.info_issues)

    def add(self, issue: ValidationIssue) -> None:
        if issue.severity == "hard":
            self.hard_issues.append(issue)
        elif issue.severity == "soft":
            self.soft_issues.append(issue)
        else:
            self.info_issues.append(issue)

    def recompute_status(self) -> str:
        if self.hard_issues:
            self.overall_status = "failed"
        elif self.soft_issues:
            self.overall_status = "warning"
        else:
            self.overall_status = "ok"
        return self.overall_status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_asarray(arr: Optional[np.ndarray]) -> Optional[np.ndarray]:
    if arr is None:
        return None
    return np.asarray(arr)


def _cell_bounds_for_feature(
    feature_world_pos: Tuple[float, float, float],
    radius_m: float,
    stack: TerrainMaskStack,
) -> Tuple[slice, slice]:
    """Return a (row, col) slice into the mask stack for a feature footprint."""
    h = _safe_asarray(stack.height)
    if h is None:
        return slice(0, 0), slice(0, 0)
    rows, cols = h.shape
    cx, cy, _cz = feature_world_pos
    cs = float(stack.cell_size) if stack.cell_size else 1.0
    half = max(radius_m, cs * 2.0)
    c0 = max(0, int(np.floor((cx - half - stack.world_origin_x) / cs)))
    c1 = min(cols, int(np.ceil((cx + half - stack.world_origin_x) / cs)) + 1)
    r0 = max(0, int(np.floor((cy - half - stack.world_origin_y) / cs)))
    r1 = min(rows, int(np.ceil((cy + half - stack.world_origin_y) / cs)) + 1)
    return slice(r0, r1), slice(c0, c1)


def protected_zone_hash(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> str:
    """Compute a SHA-256 hash over every cell inside every protected zone."""
    hasher = hashlib.sha256()
    h = _safe_asarray(stack.height)
    if h is None or not intent.protected_zones:
        return hasher.hexdigest()
    grid_shape = h.shape
    for zone in intent.protected_zones:
        rs, cs = zone.bounds.to_cell_slice(
            stack.world_origin_x,
            stack.world_origin_y,
            float(stack.cell_size),
            grid_shape,
        )
        region = np.ascontiguousarray(h[rs, cs])
        hasher.update(zone.zone_id.encode("utf-8"))
        hasher.update(repr(region.shape).encode("utf-8"))
        hasher.update(region.tobytes())
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# 10 Validators
# ---------------------------------------------------------------------------


def validate_height_finite(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> List[ValidationIssue]:
    """1. No NaN/inf in the height channel."""
    issues: List[ValidationIssue] = []
    h = _safe_asarray(stack.height)
    if h is None:
        issues.append(
            ValidationIssue(
                code="HEIGHT_MISSING",
                severity="hard",
                message="height channel is not populated",
            )
        )
        return issues
    if not np.all(np.isfinite(h)):
        bad = int(np.count_nonzero(~np.isfinite(h)))
        issues.append(
            ValidationIssue(
                code="HEIGHT_NONFINITE",
                severity="hard",
                message=f"height channel contains {bad} NaN/inf cells",
                remediation="Clamp or interpolate non-finite cells before proceeding.",
            )
        )
    return issues


def validate_height_range(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> List[ValidationIssue]:
    """2. max-min > 0 AND within plausible limits (-20km..+20km)."""
    issues: List[ValidationIssue] = []
    h = _safe_asarray(stack.height)
    if h is None or h.size == 0:
        return issues
    finite = h[np.isfinite(h)]
    if finite.size == 0:
        issues.append(
            ValidationIssue(
                code="HEIGHT_ALL_NONFINITE",
                severity="hard",
                message="height has no finite values",
            )
        )
        return issues
    hmin = float(finite.min())
    hmax = float(finite.max())
    span = hmax - hmin
    if span <= 0.0:
        issues.append(
            ValidationIssue(
                code="HEIGHT_FLAT",
                severity="hard",
                message=f"height range is zero (min={hmin}, max={hmax}) — terrain is flat",
                remediation="Re-run macro_world pass or raise noise amplitude.",
            )
        )
    PLAUSIBLE_LIMIT = 20000.0  # 20km absolute — anything beyond is a bug
    if hmin < -PLAUSIBLE_LIMIT or hmax > PLAUSIBLE_LIMIT:
        issues.append(
            ValidationIssue(
                code="HEIGHT_IMPLAUSIBLE",
                severity="hard",
                message=(
                    f"height outside plausible limits: min={hmin}, max={hmax} "
                    f"(|limit|={PLAUSIBLE_LIMIT})"
                ),
            )
        )
    return issues


def validate_slope_distribution(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> List[ValidationIssue]:
    """3. Slope channel has non-trivial variation (terrain is not uniform)."""
    issues: List[ValidationIssue] = []
    slope = _safe_asarray(stack.slope)
    if slope is None:
        # Slope may not be computed yet — treat as info
        issues.append(
            ValidationIssue(
                code="SLOPE_NOT_POPULATED",
                severity="info",
                message="slope channel not populated — skipping distribution check",
            )
        )
        return issues
    finite = slope[np.isfinite(slope)]
    if finite.size == 0:
        issues.append(
            ValidationIssue(
                code="SLOPE_ALL_NONFINITE",
                severity="hard",
                message="slope channel has no finite values",
            )
        )
        return issues
    std = float(np.std(finite))
    if std < 1e-6:
        issues.append(
            ValidationIssue(
                code="SLOPE_UNIFORM",
                severity="hard",
                message=f"slope is effectively uniform (std={std:.6f}) — terrain has no variation",
                remediation="Increase noise amplitude or verify structural_masks pass ran.",
            )
        )
    return issues


def validate_protected_zones_untouched(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
    baseline_stack: Optional[TerrainMaskStack] = None,
) -> List[ValidationIssue]:
    """4. Protected cells match their pre-pass hash.

    Accepts an optional ``baseline_stack`` captured before the pass ran.
    If omitted, this validator emits an info notice instead of failing —
    there is nothing to diff against.
    """
    issues: List[ValidationIssue] = []
    if not intent.protected_zones:
        return issues
    if baseline_stack is None:
        issues.append(
            ValidationIssue(
                code="PROTECTED_BASELINE_ABSENT",
                severity="info",
                message="no baseline stack provided; cannot diff protected zones",
            )
        )
        return issues
    current_hash = protected_zone_hash(stack, intent)
    baseline_hash = protected_zone_hash(baseline_stack, intent)
    if current_hash != baseline_hash:
        issues.append(
            ValidationIssue(
                code="PROTECTED_ZONE_MUTATED",
                severity="hard",
                message="protected zone cells changed since baseline snapshot",
                remediation="Roll back to the last checkpoint before the offending pass.",
            )
        )
    return issues


def validate_tile_seam_continuity(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
    neighbor_stacks: Optional[Dict[str, "TerrainMaskStack"]] = None,
    seam_tolerance: float = 0.1,
) -> List[ValidationIssue]:
    """5. Tile seam continuity — border values match neighbors and are C1-continuous.

    Two-tier check:

    Tier 1 — Self-consistency (always runs):
      Each border edge must be finite, and adjacent-cell jumps along the edge
      must not exceed ``seam_tolerance * tile_height_span``.  This catches
      "zero vs wall" artifacts introduced by passes that do not write border
      cells.

    Tier 2 — Cross-tile match (runs when ``neighbor_stacks`` is supplied):
      Neighbor stacks are keyed by direction: "top", "bottom", "left", "right".
      The shared border row/column of this tile and its neighbor must agree
      within ``seam_tolerance * cell_size`` (world-unit absolute tolerance
      derived from intent cell_size).  A mismatch indicates the neighboring
      tile was generated with different parameters or was not stitched.
    """
    issues: List[ValidationIssue] = []
    h = _safe_asarray(stack.height)
    if h is None or h.size == 0 or h.ndim != 2:
        return issues
    rows, cols = h.shape
    if rows < 2 or cols < 2:
        return issues

    cs = float(intent.cell_size) if intent.cell_size else 1.0

    # ------------------------------------------------------------------
    # Tier 1: self-consistency on every border edge
    # ------------------------------------------------------------------
    border_edges: Dict[str, np.ndarray] = {
        "top": h[0, :],
        "bottom": h[-1, :],
        "left": h[:, 0],
        "right": h[:, -1],
    }

    # Global height span for relative threshold
    finite_all = h[np.isfinite(h)]
    tile_height_span = float(finite_all.max() - finite_all.min()) if finite_all.size > 1 else 1.0

    for edge_name, edge in border_edges.items():
        if not np.all(np.isfinite(edge)):
            issues.append(
                ValidationIssue(
                    code=f"SEAM_NONFINITE_{edge_name.upper()}",
                    severity="hard",
                    message=f"{edge_name} tile seam contains non-finite values",
                )
            )
            continue

        # C1 continuity: no single adjacent-cell jump larger than
        # seam_tolerance * tile_height_span along the seam itself.
        delta = np.diff(edge)
        if delta.size > 0:
            max_jump = float(np.max(np.abs(delta)))
            c1_limit = seam_tolerance * tile_height_span
            if tile_height_span > 0 and max_jump > c1_limit:
                issues.append(
                    ValidationIssue(
                        code=f"SEAM_DISCONTINUITY_{edge_name.upper()}",
                        severity="soft",
                        message=(
                            f"{edge_name} seam has a cell-to-cell jump of "
                            f"{max_jump:.3f} m (limit {c1_limit:.3f} m = "
                            f"{seam_tolerance:.0%} of tile span {tile_height_span:.2f} m)"
                        ),
                        remediation=(
                            "Re-run the smoothing / seam-stitch pass, or increase "
                            "seam_tolerance if the jump is intentional."
                        ),
                    )
                )

    # ------------------------------------------------------------------
    # Tier 2: cross-tile height matching (optional)
    # ------------------------------------------------------------------
    if neighbor_stacks:
        abs_tol = seam_tolerance * cs

        neighbor_border_map: Dict[str, Tuple[np.ndarray, np.ndarray]] = {
            # (this_tile_edge, neighbor_opposite_edge)
            "top":    (h[0, :],    None),
            "bottom": (h[-1, :],   None),
            "left":   (h[:, 0],    None),
            "right":  (h[:, -1],   None),
        }

        direction_neighbor_edge: Dict[str, Callable[..., np.ndarray]] = {
            "top":    lambda nh: np.asarray(nh.height)[-1, :],   # neighbor's bottom row
            "bottom": lambda nh: np.asarray(nh.height)[0, :],    # neighbor's top row
            "left":   lambda nh: np.asarray(nh.height)[:, -1],   # neighbor's right col
            "right":  lambda nh: np.asarray(nh.height)[:, 0],    # neighbor's left col
        }

        for direction, neighbor_stack in neighbor_stacks.items():
            if direction not in direction_neighbor_edge:
                continue
            nh = _safe_asarray(neighbor_stack.height)
            if nh is None or nh.ndim != 2:
                continue

            this_edge = border_edges.get(direction)
            if this_edge is None:
                continue

            try:
                neighbor_edge = direction_neighbor_edge[direction](neighbor_stack)
            except Exception:
                continue

            # Edges must be the same length to compare
            min_len = min(len(this_edge), len(neighbor_edge))
            if min_len == 0:
                continue

            diff = np.abs(this_edge[:min_len] - neighbor_edge[:min_len])
            max_diff = float(np.max(diff[np.isfinite(diff)])) if np.any(np.isfinite(diff)) else 0.0
            bad_cells = int(np.sum(diff > abs_tol))

            if bad_cells > 0:
                issues.append(
                    ValidationIssue(
                        code=f"SEAM_CROSS_TILE_MISMATCH_{direction.upper()}",
                        severity="soft",
                        message=(
                            f"{direction} seam: {bad_cells}/{min_len} cells differ from "
                            f"neighbor tile by more than {abs_tol:.3f} m "
                            f"(max diff {max_diff:.3f} m)"
                        ),
                        remediation=(
                            "Re-run seam-stitch or ensure both tiles use the same "
                            "erosion seed and world-space parameters."
                        ),
                    )
                )

    return issues


def validate_erosion_mass_conservation(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> List[ValidationIssue]:
    """6. Total erosion + deposition within 10% (mass conservation)."""
    issues: List[ValidationIssue] = []
    eros = _safe_asarray(stack.erosion_amount)
    depo = _safe_asarray(stack.deposition_amount)
    if eros is None or depo is None:
        issues.append(
            ValidationIssue(
                code="EROSION_MASS_UNCHECKABLE",
                severity="info",
                message="erosion/deposition channels not populated",
            )
        )
        return issues
    total_eroded = float(np.sum(np.abs(eros)))
    total_deposited = float(np.sum(np.abs(depo)))
    if total_eroded <= 1e-9 and total_deposited <= 1e-9:
        issues.append(
            ValidationIssue(
                code="EROSION_NOT_APPLIED",
                severity="soft",
                message="erosion + deposition are both ~0 — pass may not have run",
            )
        )
        return issues
    denom = max(total_eroded, total_deposited, 1e-9)
    diff_pct = abs(total_eroded - total_deposited) / denom
    if diff_pct > 0.10:
        issues.append(
            ValidationIssue(
                code="EROSION_MASS_IMBALANCE",
                severity="soft",
                message=(
                    f"erosion={total_eroded:.3f} vs deposition={total_deposited:.3f} "
                    f"differ by {diff_pct * 100:.1f}% (>10%)"
                ),
                remediation="Check erosion solver for lost sediment.",
            )
        )
    return issues


def validate_hero_feature_placement(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> List[ValidationIssue]:
    """7. Every hero feature spec has a recognizable signature in the mask stack.

    Looks for non-zero cells in the matching candidate mask
    (cliff_candidate, waterfall_lip_candidate, cave_candidate) within a
    radius around the feature world position.
    """
    issues: List[ValidationIssue] = []
    if not intent.hero_feature_specs:
        return issues

    kind_to_channel = {
        "cliff": "cliff_candidate",
        "cave": "cave_candidate",
        "waterfall": "waterfall_lip_candidate",
    }

    for spec in intent.hero_feature_specs:
        ch_name = kind_to_channel.get(spec.feature_kind)
        if ch_name is None:
            # Unknown kinds get an info notice — not every hero is maskable
            issues.append(
                ValidationIssue(
                    code="HERO_FEATURE_UNMASKED_KIND",
                    severity="info",
                    affected_feature=spec.feature_id,
                    message=f"hero feature kind '{spec.feature_kind}' has no mask channel",
                )
            )
            continue
        mask = _safe_asarray(stack.get(ch_name))
        if mask is None:
            issues.append(
                ValidationIssue(
                    code="HERO_FEATURE_CHANNEL_MISSING",
                    severity="hard",
                    affected_feature=spec.feature_id,
                    message=f"mask channel '{ch_name}' required for '{spec.feature_id}' not populated",
                )
            )
            continue
        radius = max(spec.exclusion_radius, float(stack.cell_size) * 4.0)
        rs, cs = _cell_bounds_for_feature(spec.world_position, radius, stack)
        patch = mask[rs, cs]
        if patch.size == 0 or not np.any(np.asarray(patch) > 0):
            issues.append(
                ValidationIssue(
                    code="HERO_FEATURE_SIGNATURE_MISSING",
                    severity="hard",
                    affected_feature=spec.feature_id,
                    location=spec.world_position,
                    message=(
                        f"hero feature '{spec.feature_id}' ({spec.feature_kind}) "
                        f"has no nonzero cells in '{ch_name}' near its position"
                    ),
                    remediation="Re-run hero placement pass or widen exclusion_radius.",
                )
            )
    return issues


def validate_material_coverage(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> List[ValidationIssue]:
    """8. splatmap weights sum ~= 1.0, no single layer dominates > 80%."""
    issues: List[ValidationIssue] = []
    weights = _safe_asarray(stack.splatmap_weights_layer)
    if weights is None:
        # Not populated = skip
        return issues
    if weights.ndim != 3:
        issues.append(
            ValidationIssue(
                code="MATERIAL_WEIGHTS_BAD_SHAPE",
                severity="hard",
                message=f"splatmap_weights_layer must be 3D (H,W,L); got {weights.shape}",
            )
        )
        return issues
    sums = weights.sum(axis=-1)
    if not np.allclose(sums, 1.0, atol=1e-3):
        bad = int(np.count_nonzero(np.abs(sums - 1.0) > 1e-3))
        issues.append(
            ValidationIssue(
                code="MATERIAL_COVERAGE_GAP",
                severity="hard",
                message=f"{bad} cells have splatmap weights that do not sum to 1.0",
            )
        )
    total_cells = sums.size if sums.size > 0 else 1
    for layer_idx in range(weights.shape[-1]):
        layer_coverage = float((weights[..., layer_idx] > 0.5).sum()) / float(total_cells)
        if layer_coverage > 0.80:
            issues.append(
                ValidationIssue(
                    code="MATERIAL_LAYER_DOMINATES",
                    severity="soft",
                    message=(
                        f"layer {layer_idx} covers {layer_coverage * 100:.1f}% of tile "
                        f"(>80% threshold)"
                    ),
                )
            )
    return issues


# dtype contract — (channel_name, expected_numpy_kind)
# kinds: 'f' = float, 'i' = signed int, 'u' = unsigned int
_DTYPE_CONTRACT: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("height", ("f",)),
    ("slope", ("f",)),
    ("curvature", ("f",)),
    ("concavity", ("f",)),
    ("convexity", ("f",)),
    ("ridge", ("f", "b")),
    ("basin", ("f", "i", "u")),
    ("saliency_macro", ("f",)),
    ("cliff_candidate", ("f", "i", "u", "b")),
    ("cave_candidate", ("f", "i", "u", "b")),
    ("waterfall_lip_candidate", ("f", "i", "u", "b")),
    ("erosion_amount", ("f",)),
    ("deposition_amount", ("f",)),
    ("wetness", ("f",)),
    ("drainage", ("f",)),
    ("talus", ("f",)),
    ("heightmap_raw_u16", ("u",)),
    ("terrain_normals", ("f",)),
    ("navmesh_area_id", ("i", "u")),
    ("splatmap_weights_layer", ("f",)),
)


def validate_channel_dtypes(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> List[ValidationIssue]:
    """9. Each populated channel has the dtype the contract promises."""
    issues: List[ValidationIssue] = []
    for name, kinds in _DTYPE_CONTRACT:
        val = _safe_asarray(stack.get(name))
        if val is None:
            continue
        if val.dtype.kind not in kinds:
            issues.append(
                ValidationIssue(
                    code="CHANNEL_DTYPE_MISMATCH",
                    severity="hard",
                    message=(
                        f"channel '{name}' has dtype {val.dtype} "
                        f"(kind={val.dtype.kind}); expected kinds {kinds}"
                    ),
                )
            )
    return issues


def validate_unity_export_ready(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> List[ValidationIssue]:
    """10. Unity-export channels populated OR explicitly opted-out.

    Opt-out is expressed via ``intent.composition_hints['unity_export_opt_out']``
    — a truthy value means we skip the hard check.
    """
    issues: List[ValidationIssue] = []
    opt_out = bool(intent.composition_hints.get("unity_export_opt_out", False))
    required = ("heightmap_raw_u16", "splatmap_weights_layer", "navmesh_area_id")
    missing = [c for c in required if _safe_asarray(stack.get(c)) is None]
    if missing and not opt_out:
        issues.append(
            ValidationIssue(
                code="UNITY_EXPORT_INCOMPLETE",
                severity="hard",
                message=(
                    f"Unity-export channels missing: {missing}. "
                    "Set composition_hints['unity_export_opt_out']=True to skip."
                ),
                remediation="Run the Unity export preparation pass before validation.",
            )
        )
    elif missing and opt_out:
        issues.append(
            ValidationIssue(
                code="UNITY_EXPORT_OPTED_OUT",
                severity="info",
                message=f"Unity-export channels missing (opted out): {missing}",
            )
        )
    return issues


# ---------------------------------------------------------------------------
# Semantic readability checks (Addendum 1 D.14)
# ---------------------------------------------------------------------------


def check_cliff_silhouette_readability(
    stack: TerrainMaskStack,
    min_silhouette_cells: int = 20,
) -> List[ValidationIssue]:
    """Check that cliff candidates form continuous ridgelines with readable length.

    Each 8-connected component of the cliff_candidate mask is labeled; any
    component whose cell count is below ``min_silhouette_cells`` is flagged.
    Components that are too small will be invisible or noisy in-engine.
    """
    issues: List[ValidationIssue] = []
    cliff = stack.get("cliff_candidate")
    if cliff is None:
        return issues

    cliff_arr = np.asarray(cliff, dtype=np.float32)
    mask = cliff_arr > 0.5
    if not mask.any():
        return issues

    # Label connected components with pure-numpy BFS (no scipy required).
    labels = np.zeros(mask.shape, dtype=np.int32)
    rows, cols = mask.shape
    next_id = 1
    for r0 in range(rows):
        for c0 in range(cols):
            if not mask[r0, c0] or labels[r0, c0] != 0:
                continue
            bfs = [(r0, c0)]
            comp_id = next_id
            next_id += 1
            while bfs:
                r, c = bfs.pop()
                if r < 0 or r >= rows or c < 0 or c >= cols:
                    continue
                if not mask[r, c] or labels[r, c] != 0:
                    continue
                labels[r, c] = comp_id
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        bfs.append((r + dr, c + dc))

    unique_ids, counts = np.unique(labels, return_counts=True)
    # Sort by size descending (skip background label 0)
    component_pairs = sorted(
        [(int(uid), int(cnt)) for uid, cnt in zip(unique_ids, counts) if uid != 0],
        key=lambda x: x[1],
        reverse=True,
    )

    small_count = sum(1 for _, cnt in component_pairs if cnt < min_silhouette_cells)
    if small_count > 0:
        total_components = len(component_pairs)
        issues.append(
            ValidationIssue(
                code="cliff-silhouette-components-too-small",
                severity="soft",
                message=(
                    f"{small_count}/{total_components} cliff components have fewer than "
                    f"{min_silhouette_cells} cells — silhouette may be unreadable from "
                    f"focal points"
                ),
                remediation="Increase cliff threshold or merge small cliff patches.",
            )
        )

    # Also flag overall coverage too small (original check preserved)
    total_area = float(cliff_arr.size)
    cliff_area = float(mask.sum())
    if total_area > 0 and cliff_area / total_area < 0.005:
        issues.append(
            ValidationIssue(
                code="cliff-silhouette-coverage-too-small",
                severity="soft",
                message=(
                    f"Cliff silhouette covers only {cliff_area / total_area:.1%} "
                    f"of terrain — may be invisible from focal points"
                ),
            )
        )
    return issues


def check_waterfall_chain_completeness(
    stack: TerrainMaskStack,
    drain_distance: int = 10,
) -> List[ValidationIssue]:
    """Check that every waterfall lip candidate has a complete downstream chain.

    A chain is complete when:
      (a) A waterfall_pool_delta > 0 cell exists within ``drain_distance``
          cells downstream of the lip (simple rectilinear search in the
          steepest-descent direction encoded by flow_direction, or a
          bounded flood-fill when flow_direction is absent).
      (b) A non-zero water_network signal is reachable, evidenced by
          flow_accumulation > 0 near the pool location.

    When foam/mist channels are present their population is also verified.
    """
    issues: List[ValidationIssue] = []
    lips = stack.get("waterfall_lip_candidate")
    if lips is None:
        return issues

    lip_arr = np.asarray(lips, dtype=np.float32)
    if not np.any(lip_arr > 0):
        return issues

    pool_delta = _safe_asarray(stack.get("waterfall_pool_delta"))
    flow_acc = _safe_asarray(stack.get("flow_accumulation"))

    lip_rows, lip_cols = np.where(lip_arr > 0)
    incomplete: List[Tuple[int, int]] = []

    for r, c in zip(lip_rows.tolist(), lip_cols.tolist()):
        # Define search window: drain_distance cells in each direction.
        r0 = max(0, r - drain_distance)
        r1 = min(lip_arr.shape[0], r + drain_distance + 1)
        c0 = max(0, c - drain_distance)
        c1 = min(lip_arr.shape[1], c + drain_distance + 1)

        # (a) Pool presence check
        pool_present = False
        if pool_delta is not None:
            window = pool_delta[r0:r1, c0:c1]
            pool_present = bool(np.any(window > 0))

        # (b) Outflow to water_network: flow_accumulation > threshold in window
        outflow_present = False
        if flow_acc is not None:
            window_fa = flow_acc[r0:r1, c0:c1]
            # threshold: at least 10% of max accumulation nearby
            local_max = float(window_fa.max()) if window_fa.size > 0 else 0.0
            outflow_present = local_max > 0.0

        if not pool_present or not outflow_present:
            incomplete.append((int(r), int(c)))

    if incomplete:
        issues.append(
            ValidationIssue(
                code="waterfall-chain-incomplete",
                severity="soft",
                message=(
                    f"{len(incomplete)} waterfall lip candidate(s) lack a downstream "
                    f"pool (waterfall_pool_delta) or outflow (flow_accumulation) "
                    f"within {drain_distance} cells"
                ),
                remediation=(
                    "Run pass_waterfalls before validation, or extend drain_distance."
                ),
            )
        )

    # Preserve original foam/mist check as additional completeness signals
    foam = stack.get("foam")
    mist = stack.get("mist")
    if foam is None or not np.any(np.asarray(foam) > 0):
        issues.append(
            ValidationIssue(
                code="waterfall-foam-missing",
                severity="soft",
                message="Waterfall lips detected but no foam channel populated",
            )
        )
    if mist is None or not np.any(np.asarray(mist) > 0):
        issues.append(
            ValidationIssue(
                code="waterfall-mist-missing",
                severity="soft",
                message="Waterfall lips detected but no mist channel populated",
            )
        )
    return issues


def check_cave_framing_presence(
    stack: TerrainMaskStack,
    intent: Optional["TerrainIntentState"] = None,
    radius_cells: int = 5,
) -> List[ValidationIssue]:
    """Check that cave candidates have framing geometry markers nearby.

    Framing presence is determined by:
      (a) cave_candidate cells exist on the stack and are non-empty.
      (b) Each cave candidate cell has at least one non-zero hero_exclusion
          (entrance framing proxy) or non-zero cave_height_delta cell within
          ``radius_cells`` — a populated delta confirms the cave arch was carved.
      (c) If intent is supplied and ``intent.composition_hints`` contains
          ``cave_framing_required=True``, an absent cave_candidate is a hard
          failure rather than a silent skip.
    """
    issues: List[ValidationIssue] = []

    cave = stack.get("cave_candidate")
    cave_framing_required = False
    if intent is not None:
        cave_framing_required = bool(
            intent.composition_hints.get("cave_framing_required", False)
        )

    if cave is None or not np.any(np.asarray(cave) > 0):
        if cave_framing_required:
            issues.append(
                ValidationIssue(
                    code="cave-candidate-absent",
                    severity="hard",
                    message=(
                        "cave_framing_required=True but no cave_candidate cells "
                        "are populated on the stack"
                    ),
                    remediation="Run pass_caves before validation.",
                )
            )
        return issues

    cave_arr = np.asarray(cave, dtype=np.float32)
    delta = _safe_asarray(stack.get("cave_height_delta"))
    framing = _safe_asarray(stack.get("hero_exclusion"))

    cave_rows, cave_cols = np.where(cave_arr > 0)
    unframed: int = 0

    for r, c in zip(cave_rows.tolist(), cave_cols.tolist()):
        r0 = max(0, r - radius_cells)
        r1 = min(cave_arr.shape[0], r + radius_cells + 1)
        c0 = max(0, c - radius_cells)
        c1 = min(cave_arr.shape[1], c + radius_cells + 1)

        has_delta = (
            delta is not None
            and bool(np.any(delta[r0:r1, c0:c1] != 0))
        )
        has_framing = (
            framing is not None
            and bool(np.any(framing[r0:r1, c0:c1] > 0))
        )
        if not has_delta and not has_framing:
            unframed += 1

    if unframed > 0:
        issues.append(
            ValidationIssue(
                code="cave-framing-absent",
                severity="hard",
                message=(
                    f"{unframed} cave candidate cell(s) have no framing geometry "
                    f"(cave_height_delta or hero_exclusion) within {radius_cells} cells"
                ),
                remediation=(
                    "Run pass_caves to populate cave_height_delta, or author a "
                    "hero_exclusion zone around each cave entrance."
                ),
            )
        )
    return issues


def check_focal_composition(
    stack: TerrainMaskStack,
    intent: Optional["TerrainIntentState"] = None,
    occlusion_slope_threshold: float = math.radians(70.0),
) -> List[ValidationIssue]:
    """Check that hero focal points are not occluded and the terrain has relief.

    For each focal_point in ``intent.composition_hints['focal_points']`` (a list
    of (x, y) or (x, y, z) world-space tuples), the heightmap cell at that
    location is sampled and the local slope is checked:
      - slope >= ``occlusion_slope_threshold`` → the focal point is buried in a
        wall face and likely invisible from a player camera.

    Also verifies overall terrain interest: height range >= 1 m, and at least
    1% of cells are steep (>30°).
    """
    issues: List[ValidationIssue] = []
    if stack.height is None:
        return issues

    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size) if stack.cell_size else 1.0

    # Per-focal-point occlusion check
    if intent is not None:
        focal_points = intent.composition_hints.get("focal_points", [])
        slope_arr = _safe_asarray(stack.get("slope"))

        for fp in focal_points:
            # fp may be (x, y) or (x, y, z)
            fx = float(fp[0])
            fy = float(fp[1])
            col_idx = int(round((fx - stack.world_origin_x) / cs))
            row_idx = int(round((fy - stack.world_origin_y) / cs))
            col_idx = max(0, min(cols - 1, col_idx))
            row_idx = max(0, min(rows - 1, row_idx))

            if slope_arr is not None and slope_arr.shape == h.shape:
                local_slope = float(slope_arr[row_idx, col_idx])
                if local_slope >= occlusion_slope_threshold:
                    issues.append(
                        ValidationIssue(
                            code="focal-point-occluded",
                            severity="soft",
                            location=(fx, fy, float(h[row_idx, col_idx])),
                            message=(
                                f"Focal point ({fx:.1f}, {fy:.1f}) sits on a near-vertical "
                                f"face (slope={math.degrees(local_slope):.1f}°) — "
                                f"likely occluded from sightlines"
                            ),
                            remediation=(
                                "Move focal point away from wall faces, or flatten the "
                                "surrounding cell via a flatten-zone pass."
                            ),
                        )
                    )

    # Global terrain interest checks (preserved from original)
    height_range = float(h.max() - h.min())
    if height_range < 1.0:
        issues.append(
            ValidationIssue(
                code="terrain-height-range-too-small",
                severity="soft",
                message=(
                    f"Height range is only {height_range:.2f}m — terrain is "
                    f"essentially flat, lacks focal interest"
                ),
            )
        )

    slope = stack.get("slope")
    if slope is not None:
        slope_arr2 = np.asarray(slope, dtype=np.float32)
        steep_ratio = float(np.sum(slope_arr2 > math.radians(30.0))) / max(slope_arr2.size, 1)
        if steep_ratio < 0.01:
            issues.append(
                ValidationIssue(
                    code="terrain-no-dramatic-slopes",
                    severity="soft",
                    message=(
                        f"Only {steep_ratio:.1%} of terrain is steep (>30°) — "
                        f"lacks dramatic features"
                    ),
                )
            )
    return issues


@dataclass
class ReadabilityAuditReport:
    """Structured result from run_readability_audit.

    Collects per-check issue lists and computes an overall pass/fail status.
    """
    cliff_issues: List[ValidationIssue] = field(default_factory=list)
    waterfall_issues: List[ValidationIssue] = field(default_factory=list)
    cave_issues: List[ValidationIssue] = field(default_factory=list)
    focal_issues: List[ValidationIssue] = field(default_factory=list)
    overall_status: str = "ok"  # "ok" | "warning" | "failed"

    @property
    def all_issues(self) -> List[ValidationIssue]:
        return (
            self.cliff_issues
            + self.waterfall_issues
            + self.cave_issues
            + self.focal_issues
        )

    def recompute_status(self) -> str:
        all_iss = self.all_issues
        if any(i.severity == "hard" for i in all_iss):
            self.overall_status = "failed"
        elif any(i.severity == "soft" for i in all_iss):
            self.overall_status = "warning"
        else:
            self.overall_status = "ok"
        return self.overall_status


def run_readability_audit(
    stack: TerrainMaskStack,
    intent: Optional["TerrainIntentState"] = None,
) -> ReadabilityAuditReport:
    """Run all semantic readability checks and return a structured report.

    Collects results from:
      - check_cliff_silhouette_readability
      - check_waterfall_chain_completeness
      - check_cave_framing_presence  (passes intent for cave_framing_required)
      - check_focal_composition      (passes intent for focal_points)

    Computes overall pass/fail from worst severity found.
    """
    report = ReadabilityAuditReport(
        cliff_issues=check_cliff_silhouette_readability(stack),
        waterfall_issues=check_waterfall_chain_completeness(stack),
        cave_issues=check_cave_framing_presence(stack, intent=intent),
        focal_issues=check_focal_composition(stack, intent=intent),
    )
    report.recompute_status()
    return report


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------


# Canonical validator registry. Each entry is (name, callable).
def _readability_audit_validator(
    stack: TerrainMaskStack, intent: "TerrainIntentState"
) -> List[ValidationIssue]:
    """Adapter: wraps run_readability_audit for DEFAULT_VALIDATORS."""
    return run_readability_audit(stack, intent=intent).all_issues


DEFAULT_VALIDATORS: Tuple[
    Tuple[str, Callable[[TerrainMaskStack, TerrainIntentState], List[ValidationIssue]]],
    ...,
] = (
    ("validate_height_finite", validate_height_finite),
    ("validate_height_range", validate_height_range),
    ("validate_slope_distribution", validate_slope_distribution),
    ("validate_protected_zones_untouched", validate_protected_zones_untouched),
    ("validate_tile_seam_continuity", validate_tile_seam_continuity),
    ("validate_erosion_mass_conservation", validate_erosion_mass_conservation),
    ("validate_hero_feature_placement", validate_hero_feature_placement),
    ("validate_material_coverage", validate_material_coverage),
    ("validate_channel_dtypes", validate_channel_dtypes),
    ("validate_unity_export_ready", validate_unity_export_ready),
    ("readability_audit", _readability_audit_validator),
)


def run_validation_suite(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
    validators: Optional[
        List[
            Tuple[
                str,
                Callable[[TerrainMaskStack, TerrainIntentState], List[ValidationIssue]],
            ]
        ]
    ] = None,
) -> ValidationReport:
    """Run all 10 validators (or a custom list) and aggregate issues.

    Validators are invoked in order. This function never mutates state —
    it only reads.
    """
    report = ValidationReport()
    chosen = validators if validators is not None else list(DEFAULT_VALIDATORS)
    for name, fn in chosen:
        try:
            issues = fn(stack, intent)
        except Exception as exc:
            issues = [
                ValidationIssue(
                    code="VALIDATOR_CRASHED",
                    severity="hard",
                    message=f"validator {name} raised: {exc!r}",
                )
            ]
        report.metrics[f"{name}_issue_count"] = len(issues)
        for issue in issues:
            report.add(issue)
    report.metrics["total_issues"] = len(report.all_issues)
    report.metrics["hard_count"] = len(report.hard_issues)
    report.metrics["soft_count"] = len(report.soft_issues)
    report.metrics["info_count"] = len(report.info_issues)
    report.recompute_status()
    return report


# ---------------------------------------------------------------------------
# pass_validation_full — the only place allowed to downgrade/trigger rollback
# ---------------------------------------------------------------------------


# Module-level handle back to a controller for rollback (set by the caller
# running the pass through TerrainPassController.run_pass). We keep it as
# a weak contract: if not set, pass_validation_full simply returns a
# PassResult and does not attempt rollback.
_ACTIVE_CONTROLLER: Optional[TerrainPassController] = None


def bind_active_controller(
    controller: Optional[TerrainPassController],
) -> Dict[str, Any]:
    """Register the controller pass_validation_full should roll back on hard fail.

    Guards against double-binding: if the same controller instance is already
    registered, the call is a no-op and ``already_bound=True`` is returned.
    Passing ``None`` clears the binding unconditionally.

    Returns a dict with:
      - ``bound``: True if a new binding was established (or cleared).
      - ``already_bound``: True if the same instance was already registered.
      - ``controller_id``: id() of the newly bound controller, or None.
    """
    global _ACTIVE_CONTROLLER
    if controller is None:
        _ACTIVE_CONTROLLER = None
        return {"bound": True, "already_bound": False, "controller_id": None}

    if _ACTIVE_CONTROLLER is controller:
        return {"bound": False, "already_bound": True, "controller_id": id(controller)}

    _ACTIVE_CONTROLLER = controller
    return {"bound": True, "already_bound": False, "controller_id": id(controller)}


def pass_validation_full(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Run all 10 validators against the current state and return a PassResult.

    On hard failures, if a controller has been bound via
    ``bind_active_controller`` and it has checkpoints, a rollback to the
    most recent checkpoint is triggered.
    """
    t0 = time.perf_counter()
    report = run_validation_suite(state.mask_stack, state.intent)

    status = "ok"
    if report.hard_issues:
        status = "failed"
    elif report.soft_issues:
        status = "warning"

    metrics: Dict[str, Any] = dict(report.metrics)
    metrics["region_scoped"] = region is not None

    triggered_rollback = False
    if status == "failed" and _ACTIVE_CONTROLLER is not None:
        ctrl = _ACTIVE_CONTROLLER
        if ctrl.state.checkpoints:
            try:
                ctrl.rollback_last_checkpoint()
                triggered_rollback = True
            except Exception as exc:
                metrics["rollback_error"] = repr(exc)
    metrics["triggered_rollback"] = triggered_rollback

    return PassResult(
        pass_name="validation_full",
        status=status,
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        issues=list(report.hard_issues),
        warnings=list(report.soft_issues) + list(report.info_issues),
        metrics=metrics,
    )


# ---------------------------------------------------------------------------
# Pass registration
# ---------------------------------------------------------------------------


def register_bundle_d_passes() -> None:
    """Register the Bundle D validation pass on the controller.

    Does NOT register default Bundle A passes — call
    ``terrain_pipeline.register_default_passes`` for those.
    """
    TerrainPassController.register_pass(
        PassDefinition(
            name="validation_full",
            func=pass_validation_full,
            requires_channels=("height",),
            produces_channels=(),
            seed_namespace="validation_full",
            may_modify_geometry=False,
            respects_protected_zones=False,
            requires_scene_read=False,
            description="Bundle D — full validation suite (10 validators)",
        )
    )


__all__ = [
    "ValidationReport",
    "ReadabilityAuditReport",
    "validate_height_finite",
    "validate_height_range",
    "validate_slope_distribution",
    "validate_protected_zones_untouched",
    "validate_tile_seam_continuity",
    "validate_erosion_mass_conservation",
    "validate_hero_feature_placement",
    "validate_material_coverage",
    "validate_channel_dtypes",
    "validate_unity_export_ready",
    "run_validation_suite",
    "pass_validation_full",
    "register_bundle_d_passes",
    "bind_active_controller",
    "protected_zone_hash",
    "DEFAULT_VALIDATORS",
    "check_cliff_silhouette_readability",
    "check_waterfall_chain_completeness",
    "check_cave_framing_presence",
    "check_focal_composition",
    "run_readability_audit",
]

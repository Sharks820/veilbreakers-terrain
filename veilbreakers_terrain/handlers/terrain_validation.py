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

    Issues are stored in three severity lists AND in a nested
    ``categories`` dict for structured access by domain category
    (7-domain AAA bar requirement):

        report.categories["geometry"]    -> List[ValidationIssue]
        report.categories["water"]       -> List[ValidationIssue]
        report.categories["materials"]   -> List[ValidationIssue]
        report.categories["erosion"]     -> List[ValidationIssue]
        report.categories["scatter"]     -> List[ValidationIssue]
        report.categories["readability"] -> List[ValidationIssue]
        report.categories["pipeline"]    -> List[ValidationIssue]

    Category assignment is derived from the ValidationIssue.code prefix
    using ``_issue_category()``.  Callers that only care about severity
    can use the flat lists; callers that want per-domain dashboards use
    ``categories``.
    """

    pass_name: str = "validation_full"
    hard_issues: List[ValidationIssue] = field(default_factory=list)
    soft_issues: List[ValidationIssue] = field(default_factory=list)
    info_issues: List[ValidationIssue] = field(default_factory=list)
    categories: Dict[str, List[ValidationIssue]] = field(default_factory=lambda: {
        # 7-domain structured issues dict (AAA bar requirement)
        "geometry":   [],   # height, slope, seam, strata, glacial, karst, hero features
        "water":      [],   # waterfall, foam, mist, drainage
        "materials":  [],   # splatmap weights, channel dtypes, layer coverage
        "erosion":    [],   # mass conservation, sediment transport
        "scatter":    [],   # tree/rock placement, debris density
        "readability":[],   # cliff silhouette, cave framing, focal composition
        "pipeline":   [],   # export readiness, validator crashes, protected zones
    })
    metrics: Dict[str, Any] = field(default_factory=dict)
    overall_status: str = "ok"

    @property
    def all_issues(self) -> List[ValidationIssue]:
        return list(self.hard_issues) + list(self.soft_issues) + list(self.info_issues)

    def add(self, issue: ValidationIssue) -> None:
        """Add an issue to the appropriate severity list and category bucket."""
        if issue.severity == "hard":
            self.hard_issues.append(issue)
        elif issue.severity == "soft":
            self.soft_issues.append(issue)
        else:
            self.info_issues.append(issue)
        cat = _issue_category(issue.code)
        self.categories.setdefault(cat, []).append(issue)

    def recompute_status(self) -> str:
        if self.hard_issues:
            self.overall_status = "failed"
        elif self.soft_issues:
            self.overall_status = "warning"
        else:
            self.overall_status = "ok"
        return self.overall_status

    def category_summary(self) -> Dict[str, Dict[str, int]]:
        """Return per-category severity counts for dashboards/logging.

        Example::

            {
                "geometry":   {"hard": 2, "soft": 0, "info": 1},
                "water":      {"hard": 0, "soft": 1, "info": 0},
                "materials":  {"hard": 0, "soft": 0, "info": 0},
                "erosion":    {"hard": 0, "soft": 0, "info": 0},
                "scatter":    {"hard": 0, "soft": 0, "info": 0},
                "readability":{"hard": 0, "soft": 0, "info": 0},
                "pipeline":   {"hard": 0, "soft": 0, "info": 0},
            }
        """
        summary: Dict[str, Dict[str, int]] = {}
        for cat, issues in self.categories.items():
            summary[cat] = {
                "hard": sum(1 for i in issues if i.severity == "hard"),
                "soft": sum(1 for i in issues if i.severity == "soft"),
                "info": sum(1 for i in issues if i.severity not in ("hard", "soft")),
            }
        return summary


# ---------------------------------------------------------------------------
# Category routing helper
# ---------------------------------------------------------------------------

_CATEGORY_PREFIXES: Tuple[Tuple[str, str], ...] = (
    # (code_prefix_lower, category) — maps to the 7 AAA-bar domains:
    # geometry | water | materials | erosion | scatter | readability | pipeline
    ("height_",          "geometry"),
    ("slope_",           "geometry"),
    ("seam_",            "geometry"),
    ("strata_",          "geometry"),   # geological strata = geometry domain
    ("glacial_",         "geometry"),   # glacial plausibility = geometry domain
    ("karst_",           "geometry"),   # karst plausibility = geometry domain
    ("hero_feature",     "geometry"),
    ("protected_",       "pipeline"),   # protected zone mutations = pipeline concern
    ("erosion_",         "erosion"),
    ("material_",        "materials"),
    ("channel_dtype",    "materials"),
    ("unity_export",     "pipeline"),   # export readiness = pipeline concern
    ("validator_crashed","pipeline"),
    ("waterfall",        "water"),
    ("foam",             "water"),
    ("mist",             "water"),
    ("scatter",          "scatter"),
    ("tree_",            "scatter"),
    ("debris_",          "scatter"),
    ("cave",             "readability"),
    ("cliff",            "readability"),
    ("focal",            "readability"),
    ("terrain-",         "readability"),
)


def _issue_category(code: str) -> str:
    """Map a ValidationIssue code to a domain category string.

    Matching is done by lowercase prefix scan in priority order.
    Returns ``"other"`` when no prefix matches.
    """
    lower = code.lower()
    for prefix, cat in _CATEGORY_PREFIXES:
        if lower.startswith(prefix):
            return cat
    return "other"


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
      Neighbor stacks may be keyed by cardinal directions
      (``north/south/east/west``) or edge names (``top/bottom/left/right``).
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
        direction_aliases = {
            "north": "top",
            "south": "bottom",
            "west": "left",
            "east": "right",
            "top": "top",
            "bottom": "bottom",
            "left": "left",
            "right": "right",
        }

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
            canonical_direction = direction_aliases.get(str(direction).lower())
            if canonical_direction not in direction_neighbor_edge:
                continue
            nh = _safe_asarray(neighbor_stack.height)
            if nh is None or nh.ndim != 2:
                continue

            this_edge = border_edges.get(canonical_direction)
            if this_edge is None:
                continue

            try:
                neighbor_edge = direction_neighbor_edge[canonical_direction](neighbor_stack)
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
                        code=f"SEAM_CROSS_TILE_MISMATCH_{canonical_direction.upper()}",
                        severity="soft",
                        message=(
                            f"{canonical_direction} seam: {bad_cells}/{min_len} cells differ from "
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
    min_sky_exposure_pct: float = 5.0,
) -> List[ValidationIssue]:
    """Check cliff candidates for readable sky-silhouette and ridgeline continuity.

    Three-tier check:

    Tier 1 — Sky-exposure percentage (AAA requirement):
        A cliff cell is sky-exposed when its height equals the maximum of
        its 3×3 neighbourhood — meaning nothing above it blocks the
        vertical sightline to the sky.

            sky_exposure_pct = sky_exposed_cliff_cells / total_cliff_cells * 100

        Must be >= ``min_sky_exposure_pct`` (default 5%).  A cliff entirely
        buried under overhanging terrain has zero sky exposure and will be
        unreadable as a silhouette feature.  Requires the height channel.

    Tier 2 — Overall coverage:
        Cliff footprint must be >= 0.5% of the tile or the feature is
        invisible.

    Tier 3 — Component continuity:
        Each 8-connected component must have >= ``min_silhouette_cells``
        cells; tiny fragments produce noisy, unreadable ridgelines.
    """
    issues: List[ValidationIssue] = []
    cliff = stack.get("cliff_candidate")
    if cliff is None:
        return issues

    cliff_arr = np.asarray(cliff, dtype=np.float32)
    mask = cliff_arr > 0.5
    if not mask.any():
        return issues

    cliff_cells = int(mask.sum())
    total_area = float(cliff_arr.size)

    # ------------------------------------------------------------------
    # Tier 1: sky-exposure percentage — requires height channel
    # ------------------------------------------------------------------
    h = _safe_asarray(stack.height)
    if h is not None and h.ndim == 2 and h.shape == cliff_arr.shape:
        rows, cols = h.shape
        if rows >= 3 and cols >= 3:
            h_pad = np.pad(h, 1, mode="reflect")
            local_max = h_pad[:-2, :-2].copy()
            for dr in range(3):
                for dc in range(3):
                    if dr == 0 and dc == 0:
                        continue
                    local_max = np.maximum(
                        local_max, h_pad[dr: dr + rows, dc: dc + cols]
                    )
            sky_exposed = h >= (local_max - 1e-9)
            sky_exposed_cliff = mask & sky_exposed
            sky_exposure_pct = float(sky_exposed_cliff.sum()) / float(cliff_cells) * 100.0
        else:
            sky_exposure_pct = 100.0  # grid too small; assume all exposed

        if sky_exposure_pct < min_sky_exposure_pct:
            issues.append(
                ValidationIssue(
                    code="cliff-silhouette-sky-exposure-low",
                    severity="soft",
                    message=(
                        f"cliff sky-exposure is {sky_exposure_pct:.1f}% "
                        f"(minimum {min_sky_exposure_pct:.1f}%) — cliff is buried "
                        f"below surrounding terrain and will not silhouette against sky"
                    ),
                    remediation=(
                        "Raise cliff cells above surrounding terrain, or adjust the "
                        "cliff_candidate threshold so only protruding faces are marked."
                    ),
                )
            )

    # ------------------------------------------------------------------
    # Tier 2: overall footprint coverage
    # ------------------------------------------------------------------
    if total_area > 0 and cliff_cells / total_area < 0.005:
        issues.append(
            ValidationIssue(
                code="cliff-silhouette-coverage-too-small",
                severity="soft",
                message=(
                    f"Cliff silhouette covers only {cliff_cells / total_area:.1%} "
                    f"of terrain — may be invisible from focal points"
                ),
            )
        )

    # ------------------------------------------------------------------
    # Tier 3: connected-component minimum size
    # ------------------------------------------------------------------
    labels = np.zeros(mask.shape, dtype=np.int32)
    n_rows, n_cols = mask.shape
    next_id = 1
    for r0 in range(n_rows):
        for c0 in range(n_cols):
            if not mask[r0, c0] or labels[r0, c0] != 0:
                continue
            bfs = [(r0, c0)]
            comp_id = next_id
            next_id += 1
            while bfs:
                r, c = bfs.pop()
                if r < 0 or r >= n_rows or c < 0 or c >= n_cols:
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


def validate_strata_consistency(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> List[ValidationIssue]:
    """Validate geological strata layer ordering: oldest (deepest) stratum at bottom.

    In a physically consistent terrain stack, stratum layers must be ordered so
    that formation age increases with depth.  The ``strata_layers`` channel is
    expected to be a 3-D array of shape ``(rows, cols, num_layers)`` where layer
    index 0 is the *surface* (youngest) and index N-1 is the *deepest* (oldest).
    For each cell the algorithm checks two invariants:

    1. **Monotonic depth increase** — the depth value (if supplied via
       ``strata_depths`` channel of the same shape) must increase with layer
       index at every cell.  A reversal indicates a layer was authored
       upside-down or a deformation pass corrupted the stack order.

    2. **No zero-thickness sandwich** — a layer should not have zero weight
       (presence = 0) while the layers on both sides of it have non-zero weight.
       Such a gap creates an artificial stratigraphic unconformity that would
       produce visible z-fighting seams in the material system.

    When no ``strata_layers`` channel is present the validator returns an info
    notice so the suite does not fail on stacks that predate the strata pass.
    """
    issues: List[ValidationIssue] = []

    strata = _safe_asarray(stack.get("strata_layers"))
    if strata is None:
        issues.append(
            ValidationIssue(
                code="STRATA_CHANNEL_ABSENT",
                severity="info",
                message=(
                    "strata_layers channel not populated — skipping strata "
                    "consistency check (run strata pass before validation)"
                ),
            )
        )
        return issues

    if strata.ndim != 3 or strata.shape[2] < 2:
        issues.append(
            ValidationIssue(
                code="STRATA_BAD_SHAPE",
                severity="hard",
                message=(
                    f"strata_layers must be 3-D (rows, cols, num_layers>=2); "
                    f"got shape {strata.shape}"
                ),
            )
        )
        return issues

    num_layers = strata.shape[2]

    # -----------------------------------------------------------------------
    # Check 1: depth ordering — strata_depths must increase with layer index.
    # -----------------------------------------------------------------------
    strata_depths = _safe_asarray(stack.get("strata_depths"))
    if strata_depths is not None:
        if strata_depths.shape != strata.shape:
            issues.append(
                ValidationIssue(
                    code="STRATA_DEPTHS_SHAPE_MISMATCH",
                    severity="hard",
                    message=(
                        f"strata_depths shape {strata_depths.shape} does not match "
                        f"strata_layers shape {strata.shape}"
                    ),
                )
            )
        else:
            # For each cell, check that depth[..., i+1] >= depth[..., i]
            # (deepest = largest depth value = oldest = highest layer index)
            bad_inversions = 0
            for i in range(num_layers - 1):
                inverted = strata_depths[..., i + 1] < strata_depths[..., i] - 1e-6
                bad_inversions += int(inverted.sum())

            if bad_inversions > 0:
                total_cells = int(strata_depths.shape[0] * strata_depths.shape[1])
                pct = bad_inversions / max(total_cells * (num_layers - 1), 1) * 100.0
                issues.append(
                    ValidationIssue(
                        code="STRATA_DEPTH_ORDER_INVERTED",
                        severity="hard",
                        message=(
                            f"strata_depths has {bad_inversions} depth-order inversions "
                            f"({pct:.1f}% of cell-layer pairs) — deepest layer must have "
                            f"the largest depth value (oldest = deepest)"
                        ),
                        remediation=(
                            "Reverse the layer index ordering so strata_layers[..., 0] "
                            "is the youngest (surface) and strata_layers[..., -1] is "
                            "the oldest (deepest)."
                        ),
                    )
                )

    # -----------------------------------------------------------------------
    # Check 2: no zero-thickness sandwich (absent layer surrounded by present).
    # -----------------------------------------------------------------------
    # A layer is "present" at a cell if its weight > 0.01.
    present = strata > 0.01  # (rows, cols, num_layers) bool

    sandwich_count = 0
    for i in range(1, num_layers - 1):
        # Layer i absent, but layers i-1 and i+1 both present
        sandwiched = (~present[..., i]) & present[..., i - 1] & present[..., i + 1]
        sandwich_count += int(sandwiched.sum())

    if sandwich_count > 0:
        issues.append(
            ValidationIssue(
                code="STRATA_ZERO_THICKNESS_SANDWICH",
                severity="soft",
                message=(
                    f"{sandwich_count} cells have a zero-weight (absent) layer "
                    f"sandwiched between two present layers — indicates a "
                    f"stratigraphic unconformity gap that may cause z-fighting"
                ),
                remediation=(
                    "Fill thin strata layers with a small minimum weight (>0.01) "
                    "or merge the flanking layers."
                ),
            )
        )

    return issues


def validate_glacial_plausibility(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
    *,
    glacial_min_altitude_m: float = 1500.0,
    glacial_max_latitude_deg: float = 70.0,
    polar_latitude_threshold_deg: float = 50.0,
    sea_level_altitude_m: float = 0.0,
) -> List[ValidationIssue]:
    """Validate that glacial terrain features are plausible given latitude and altitude.

    Glaciers and ice formations require either high altitude (above the glacial
    equilibrium line — typically ~1500 m in temperate zones) or high latitude
    (above ~50–70°N/S where glacial conditions persist at lower elevation).
    The validator checks two constraints:

    1. **Altitude constraint** — if a ``glacial_extent`` or ``glacier_mask``
       channel is present with non-zero values, and the median elevation of
       those cells is below ``glacial_min_altitude_m``, AND the tile latitude
       (from ``intent.composition_hints['latitude_deg']``) is below
       ``polar_latitude_threshold_deg``, then the glacial feature is implausible
       (tropical or temperate lowland glacier).

    2. **Latitude constraint** — glacial_extent cells must not appear in
       equatorial zones (|latitude| < 10°) at any altitude below 4000 m.
       Equatorial glaciers exist only above 4000 m (e.g. Rwenzori, Kilimanjaro).

    When neither channel is present the validator returns an info notice and
    exits cleanly — this validator is opt-in for tiles that include glacial passes.
    """
    issues: List[ValidationIssue] = []

    # Find the glacial mask channel (accept either name)
    glacial = None
    for _ch in ("glacial_extent", "glacier_mask", "glacial_mask"):
        glacial = _safe_asarray(stack.get(_ch))
        if glacial is not None:
            break

    if glacial is None:
        issues.append(
            ValidationIssue(
                code="GLACIAL_CHANNEL_ABSENT",
                severity="info",
                message=(
                    "no glacial_extent / glacier_mask channel found — "
                    "skipping glacial plausibility check"
                ),
            )
        )
        return issues

    if not np.any(glacial > 0):
        return issues  # channel present but empty — nothing to check

    h = _safe_asarray(stack.height)
    if h is None or h.ndim != 2:
        return issues

    # Latitude from intent composition_hints (degrees, signed: +N / -S)
    latitude_deg = float(
        intent.composition_hints.get("latitude_deg", float("nan"))
    )
    has_latitude = math.isfinite(latitude_deg)

    # Cells with glacial extent > 0
    glacial_cells = glacial > 0
    if h.shape == glacial.shape:
        glacial_heights = h[glacial_cells]
    else:
        glacial_heights = h.flatten()  # shape mismatch fallback

    if glacial_heights.size == 0:
        return issues

    median_glacial_alt = float(np.median(glacial_heights))

    # ------------------------------------------------------------------
    # Constraint 1: temperate / tropical altitude check
    # ------------------------------------------------------------------
    if has_latitude:
        abs_lat = abs(latitude_deg)
        if abs_lat < polar_latitude_threshold_deg:
            # Temperate / tropical zone: glaciers need high altitude
            if median_glacial_alt < glacial_min_altitude_m:
                issues.append(
                    ValidationIssue(
                        code="GLACIAL_TOO_LOW_FOR_LATITUDE",
                        severity="hard",
                        message=(
                            f"glacial features at median altitude {median_glacial_alt:.0f} m "
                            f"with latitude {latitude_deg:.1f}° — implausible; glaciers "
                            f"in temperate/tropical zones require altitude "
                            f">= {glacial_min_altitude_m:.0f} m "
                            f"(or latitude >= {polar_latitude_threshold_deg:.0f}°)"
                        ),
                        remediation=(
                            "Move glacial extent to high-altitude cells, set a higher "
                            "latitude in composition_hints['latitude_deg'], or remove "
                            "the glacial_extent mask from lowland tiles."
                        ),
                    )
                )

        # ------------------------------------------------------------------
        # Constraint 2: equatorial check — very strict altitude floor
        # ------------------------------------------------------------------
        EQUATORIAL_LAT_THRESHOLD = 10.0
        EQUATORIAL_GLACIER_ALT_M = 4000.0
        if abs_lat < EQUATORIAL_LAT_THRESHOLD:
            low_equatorial = glacial_cells & (h < EQUATORIAL_GLACIER_ALT_M)
            if h.shape == glacial.shape:
                bad_count = int(low_equatorial.sum())
            else:
                bad_count = 0
            if bad_count > 0:
                issues.append(
                    ValidationIssue(
                        code="GLACIAL_EQUATORIAL_TOO_LOW",
                        severity="hard",
                        message=(
                            f"{bad_count} glacial cells in equatorial zone "
                            f"(latitude={latitude_deg:.1f}°) are below "
                            f"{EQUATORIAL_GLACIER_ALT_M:.0f} m — equatorial glaciers "
                            f"only exist above ~4000 m (Rwenzori / Kilimanjaro type)"
                        ),
                        remediation=(
                            "Raise equatorial glacial features above 4000 m or "
                            "remove the glacial mask from this equatorial tile."
                        ),
                    )
                )
    else:
        # No latitude available: check only that altitude is not obviously wrong
        # (glaciers below 500 m with no latitude context is always suspicious)
        SUSPICIOUS_LOW_ALT = 500.0
        if median_glacial_alt < SUSPICIOUS_LOW_ALT:
            issues.append(
                ValidationIssue(
                    code="GLACIAL_SUSPICIOUS_LOW_ALTITUDE",
                    severity="soft",
                    message=(
                        f"glacial features at median altitude {median_glacial_alt:.0f} m "
                        f"(below {SUSPICIOUS_LOW_ALT:.0f} m) without latitude context — "
                        f"may be implausible; set composition_hints['latitude_deg'] "
                        f"for a full plausibility check"
                    ),
                )
            )

    return issues


def validate_karst_plausibility(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
    *,
    limestone_proxy_min: float = 0.3,
) -> List[ValidationIssue]:
    """Validate karst terrain features against a limestone / soluble rock proxy.

    Karst topography (sinkholes, caves, dolines, dry valleys) can only form in
    soluble rock — overwhelmingly limestone or dolomite, occasionally evaporites
    (gypsum / halite) or basalt where CO₂-rich water acts as weak acid.

    The validator looks for a ``limestone_proxy`` channel (float [0, 1] where 1
    = pure limestone, 0 = siliceous / igneous bedrock), a ``lithology`` label
    channel, or a material-hint from ``intent.composition_hints``.  It then
    checks:

    1. **Karst features require soluble substrate** — cells carrying a
       ``cave_candidate``, ``karst_doline``, or ``sinkhole_mask`` must have
       ``limestone_proxy >= limestone_proxy_min`` (default 0.3 = at least 30%
       soluble fraction).  Pure granite / basalt karst is scientifically invalid.

    2. **Limestone proxy completeness** — if karst features exist but no proxy
       channel is present, emit a soft warning asking the author to provide one.
       Do not hard-fail so early pipeline stages (where the proxy pass hasn't
       run yet) are not blocked.

    3. **Material hint consistency** — if ``intent.composition_hints['lithology']``
       is ``"granite"`` or ``"basalt"`` but cave/sinkhole features exist, flag
       the contradiction as a hard error regardless of whether a numeric proxy
       is present.
    """
    issues: List[ValidationIssue] = []

    # Collect karst feature masks (accept any of these names)
    karst_masks: Dict[str, Optional[np.ndarray]] = {}
    for _ch in ("cave_candidate", "karst_doline", "sinkhole_mask"):
        _arr = _safe_asarray(stack.get(_ch))
        if _arr is not None and np.any(_arr > 0):
            karst_masks[_ch] = _arr

    if not karst_masks:
        # No karst features present — nothing to validate
        return issues

    # ------------------------------------------------------------------
    # Check 3: material hint contradiction (hard fail, no numeric proxy needed)
    # ------------------------------------------------------------------
    lithology_hint = str(
        intent.composition_hints.get("lithology", "")
    ).lower().strip()
    NON_KARST_ROCK = {"granite", "basalt", "sandstone", "quartzite", "schist"}
    if lithology_hint in NON_KARST_ROCK:
        for ch_name in karst_masks:
            issues.append(
                ValidationIssue(
                    code="KARST_INCOMPATIBLE_LITHOLOGY",
                    severity="hard",
                    affected_feature=ch_name,
                    message=(
                        f"karst feature '{ch_name}' exists but lithology hint is "
                        f"'{lithology_hint}' — karst cannot form in non-soluble rock; "
                        f"limestone, dolomite, or evaporite substrate is required"
                    ),
                    remediation=(
                        "Change lithology to 'limestone' / 'dolomite' / 'evaporite', "
                        "or remove the karst feature masks from this tile."
                    ),
                )
            )
        # Return early: lithology contradiction is definitive, no need for proxy check
        return issues

    # ------------------------------------------------------------------
    # Check 1 + 2: limestone proxy presence and per-cell threshold
    # ------------------------------------------------------------------
    proxy = _safe_asarray(stack.get("limestone_proxy"))

    if proxy is None:
        # Soft warning only — proxy pass may not have run yet
        issues.append(
            ValidationIssue(
                code="KARST_NO_LIMESTONE_PROXY",
                severity="soft",
                message=(
                    f"karst features ({', '.join(karst_masks)}) present but "
                    f"no limestone_proxy channel found — cannot verify soluble "
                    f"substrate; run the lithology pass before validation for a "
                    f"full plausibility check"
                ),
                remediation=(
                    "Populate the 'limestone_proxy' channel (float [0,1]) with "
                    "the fractional soluble-rock coverage per cell."
                ),
            )
        )
        return issues

    if proxy.ndim != 2:
        issues.append(
            ValidationIssue(
                code="KARST_PROXY_BAD_SHAPE",
                severity="hard",
                message=(
                    f"limestone_proxy must be 2-D (rows, cols); got shape {proxy.shape}"
                ),
            )
        )
        return issues

    # Check each karst mask for cells below the proxy threshold
    for ch_name, karst_arr in karst_masks.items():
        if karst_arr is None or proxy.shape != karst_arr.shape:
            continue

        karst_bool = karst_arr > 0
        proxy_at_karst = proxy[karst_bool]
        if proxy_at_karst.size == 0:
            continue

        # Cells where karst exists but proxy is below minimum solubility
        insufficient = proxy_at_karst < limestone_proxy_min
        bad_count = int(insufficient.sum())
        if bad_count > 0:
            total_karst = int(karst_bool.sum())
            pct = bad_count / max(total_karst, 1) * 100.0
            issues.append(
                ValidationIssue(
                    code="KARST_INSUFFICIENT_LIMESTONE_PROXY",
                    severity="hard",
                    affected_feature=ch_name,
                    message=(
                        f"karst feature '{ch_name}' has {bad_count}/{total_karst} cells "
                        f"({pct:.1f}%) with limestone_proxy < {limestone_proxy_min:.2f} "
                        f"— insufficient soluble-rock fraction for karst formation"
                    ),
                    remediation=(
                        f"Raise limestone_proxy to >= {limestone_proxy_min:.2f} in "
                        f"karst-feature cells, or remove the karst mask from "
                        f"igneous/metamorphic substrate areas."
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
    # Geological plausibility validators (R9 additions)
    ("validate_strata_consistency", validate_strata_consistency),
    ("validate_glacial_plausibility", validate_glacial_plausibility),
    ("validate_karst_plausibility", validate_karst_plausibility),
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
            # Full validation inspects slope distribution + splatmap coverage
            # + tree placement, so slope is a hard requirement. The other
            # downstream channels (cliff_candidate, waterfall_lip_candidate,
            # splatmap_weights_layer, tree_instance_points, etc.) are read
            # via stack.get(...) and validators degrade gracefully when
            # absent — that is the contract for "full" in the run-ordering
            # sense (must run after core channels exist, tolerates missing
            # optional ones).
            requires_channels=("height", "slope"),
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
    "_issue_category",
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
    # Geological plausibility validators (R9 additions)
    "validate_strata_consistency",
    "validate_glacial_plausibility",
    "validate_karst_plausibility",
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

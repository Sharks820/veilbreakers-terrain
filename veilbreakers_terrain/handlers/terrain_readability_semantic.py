"""Bundle N supplements — terrain-semantic readability checks (Addendum 1.B.8).

Image-stat-only verification is deprecated. Every visible hero feature
must have a semantic readability check that actually inspects the
TerrainMaskStack instead of just histograms.

AAA standard requirements (from audit brief):
  - check_cliff_silhouette_readability must compute actual sky-exposure
    percentage from the height channel, not just a footprint ratio.
  - check_waterfall_chain_completeness must verify stack channels
    (pool_delta, flow_accumulation, foam, mist), not just object attrs.
  - check_cave_framing_presence must inspect stack channels
    (cave_height_delta, hero_exclusion) with per-cell radius search.
  - check_focal_composition must verify rule-of-thirds with full
    occlusion context (slope at focal cell).
"""

from __future__ import annotations

import math
from typing import Any, List, Optional, Sequence, Tuple

import numpy as np

from .terrain_semantics import TerrainMaskStack, ValidationIssue


# ---------------------------------------------------------------------------
# Cliff silhouette readability — sky-exposure percentage
# ---------------------------------------------------------------------------


def check_cliff_silhouette_readability(
    stack: TerrainMaskStack,
    view_distance_m: float = 100.0,
    min_sky_exposure_pct: float = 5.0,
    min_silhouette_cells: int = 20,
) -> List[ValidationIssue]:
    """Cliffs must form readable sky-silhouettes: actual sky-exposure >= threshold.

    Sky-exposure percentage is the fraction of cliff_candidate cells that
    are locally sky-visible when looking straight up.  A cell is sky-exposed
    when its height equals the maximum in its 3×3 neighbourhood — meaning
    nothing above it blocks the vertical sightline to the sky.

    Two-tier check:

    Tier 1 — Sky-exposure percentage:
        sky_exposure_pct = sky_exposed_cliff_cells / total_cliff_cells * 100
        Must be >= ``min_sky_exposure_pct`` (default 5%).  A cliff buried
        entirely under overhanging geometry (or on a valley floor) with
        zero sky exposure will be unreadable from overhead.

    Tier 2 — Component size (silhouette continuity):
        Each 8-connected component of cliff_candidate must have at least
        ``min_silhouette_cells`` cells.  Tiny isolated cliff blobs do not
        produce a readable ridgeline silhouette at game camera distances.

    Also checks:
        - slope channel present and sharp lip (>= 25% of cliff cells at
          slope > 0.7 rad) to catch procedurally flat "cliff" artifacts.
    """
    issues: List[ValidationIssue] = []

    cliff_raw = stack.get("cliff_candidate")
    if cliff_raw is None:
        return issues  # no cliffs in this tile — vacuously readable

    if stack.height is None:
        issues.append(
            ValidationIssue(
                code="CLIFF_READABILITY_NO_HEIGHT",
                severity="hard",
                message="cliff_candidate present but height channel missing",
                remediation="Populate height channel before readability audit",
            )
        )
        return issues

    cliff_arr = np.asarray(cliff_raw, dtype=np.float32)
    h = np.asarray(stack.height, dtype=np.float64)

    if cliff_arr.shape != h.shape:
        issues.append(
            ValidationIssue(
                code="CLIFF_READABILITY_SHAPE_MISMATCH",
                severity="hard",
                message=(
                    f"cliff_candidate shape {cliff_arr.shape} != "
                    f"height shape {h.shape}"
                ),
            )
        )
        return issues

    cliff_mask = cliff_arr > 0.5
    total_cells = cliff_mask.size
    cliff_cells = int(cliff_mask.sum())

    if cliff_cells == 0:
        return issues

    # ------------------------------------------------------------------
    # Tier 1: sky-exposure percentage
    # ------------------------------------------------------------------
    rows, cols = h.shape
    if rows >= 3 and cols >= 3:
        h_pad = np.pad(h, 1, mode="reflect")
        local_max = h_pad[:-2, :-2].copy()
        for dr in range(3):
            for dc in range(3):
                if dr == 0 and dc == 0:
                    continue
                local_max = np.maximum(local_max, h_pad[dr: dr + rows, dc: dc + cols])

        sky_exposed = h >= (local_max - 1e-9)  # cell is at or near neighbourhood top
        sky_exposed_cliff = cliff_mask & sky_exposed
        sky_exposure_pct = float(sky_exposed_cliff.sum()) / float(cliff_cells) * 100.0
    else:
        # Grid too small for neighbourhood; assume all cliff cells sky-exposed.
        sky_exposure_pct = 100.0

    if sky_exposure_pct < min_sky_exposure_pct:
        issues.append(
            ValidationIssue(
                code="CLIFF_READABILITY_SKY_EXPOSURE_LOW",
                severity="hard",
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
    # Footprint coverage (kept from original, but now info-tier)
    # ------------------------------------------------------------------
    footprint_pct = float(cliff_cells) / float(total_cells) * 100.0
    if footprint_pct < 0.5:
        issues.append(
            ValidationIssue(
                code="CLIFF_READABILITY_UNDERFOOTED",
                severity="hard",
                message=(
                    f"cliff footprint {cliff_cells}/{total_cells} "
                    f"({footprint_pct:.2f}%) < 0.5% — "
                    f"unreadable at {view_distance_m:.0f}m"
                ),
                remediation="Expand cliff candidate zones or raise slope threshold",
            )
        )

    # ------------------------------------------------------------------
    # Slope sharpness — lip boundary check
    # ------------------------------------------------------------------
    slope_raw = stack.get("slope")
    if slope_raw is not None:
        slope_arr = np.asarray(slope_raw, dtype=np.float64)
        if slope_arr.shape == cliff_arr.shape:
            sharp_ratio = float((slope_arr[cliff_mask] > 0.7).mean()) if cliff_cells else 0.0
            if sharp_ratio < 0.25:
                issues.append(
                    ValidationIssue(
                        code="CLIFF_READABILITY_SOFT_LIP",
                        severity="hard",
                        message=(
                            f"only {sharp_ratio:.1%} of cliff cells exceed 0.7 rad slope — "
                            "lip boundary will not read at game camera distance"
                        ),
                        remediation="Sharpen cliff lip via cliff carver pass",
                    )
                )
    else:
        issues.append(
            ValidationIssue(
                code="CLIFF_READABILITY_NO_SLOPE",
                severity="hard",
                message="cliff_candidate present but slope channel missing",
                remediation="Run pass_structural_masks before readability audit",
            )
        )

    # ------------------------------------------------------------------
    # Tier 2: connected-component minimum size
    # ------------------------------------------------------------------
    labels = np.zeros(cliff_mask.shape, dtype=np.int32)
    r_count, c_count = cliff_mask.shape
    next_id = 1
    for r0 in range(r_count):
        for c0 in range(c_count):
            if not cliff_mask[r0, c0] or labels[r0, c0] != 0:
                continue
            bfs: List[Tuple[int, int]] = [(r0, c0)]
            comp_id = next_id
            next_id += 1
            while bfs:
                r, c = bfs.pop()
                if r < 0 or r >= r_count or c < 0 or c >= c_count:
                    continue
                if not cliff_mask[r, c] or labels[r, c] != 0:
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
        issues.append(
            ValidationIssue(
                code="CLIFF_READABILITY_SMALL_COMPONENTS",
                severity="soft",
                message=(
                    f"{small_count}/{len(component_pairs)} cliff components have fewer "
                    f"than {min_silhouette_cells} cells — silhouette may be fragmented "
                    f"and unreadable from focal points"
                ),
                remediation="Increase cliff threshold or merge small cliff patches.",
            )
        )

    return issues


# ---------------------------------------------------------------------------
# Waterfall chain completeness — stack-channel inspection
# ---------------------------------------------------------------------------


def check_waterfall_chain_completeness(
    stack: TerrainMaskStack,
    chains: Optional[Sequence[Any]] = None,
    drain_distance: int = 10,
) -> List[ValidationIssue]:
    """Every waterfall chain must have a complete downstream chain in the stack.

    Two modes:

    Mode A — stack inspection (always runs when waterfall_lip_candidate is
    present):
        For each waterfall lip cell, verify that within ``drain_distance``
        cells there is (a) a waterfall_pool_delta > 0 cell and (b) a
        flow_accumulation > 0 cell.  Also checks that foam and mist
        channels are populated.

    Mode B — structured chain objects (runs when ``chains`` is supplied):
        Each chain item (dict or object) must carry source, lip, pool,
        and outflow attributes/keys that are non-None.

    Both modes run independently if their inputs are present.
    """
    issues: List[ValidationIssue] = []

    # ------------------------------------------------------------------
    # Mode A: stack inspection
    # ------------------------------------------------------------------
    lips_raw = stack.get("waterfall_lip_candidate")
    if lips_raw is not None:
        lip_arr = np.asarray(lips_raw, dtype=np.float32)
        if np.any(lip_arr > 0):
            pool_delta = _safe_asarray(stack.get("waterfall_pool_delta"))
            flow_acc = _safe_asarray(stack.get("flow_accumulation"))

            lip_rows, lip_cols = np.where(lip_arr > 0)
            incomplete: List[Tuple[int, int]] = []

            for r, c in zip(lip_rows.tolist(), lip_cols.tolist()):
                r0 = max(0, r - drain_distance)
                r1 = min(lip_arr.shape[0], r + drain_distance + 1)
                c0 = max(0, c - drain_distance)
                c1 = min(lip_arr.shape[1], c + drain_distance + 1)

                pool_present = (
                    pool_delta is not None
                    and bool(np.any(pool_delta[r0:r1, c0:c1] > 0))
                )
                outflow_present = (
                    flow_acc is not None
                    and bool(np.any(flow_acc[r0:r1, c0:c1] > 0))
                )
                if not pool_present or not outflow_present:
                    incomplete.append((int(r), int(c)))

            if incomplete:
                issues.append(
                    ValidationIssue(
                        code="WATERFALL_CHAIN_INCOMPLETE_STACK",
                        severity="soft",
                        message=(
                            f"{len(incomplete)} waterfall lip candidate(s) lack a "
                            f"downstream pool (waterfall_pool_delta) or outflow "
                            f"(flow_accumulation) within {drain_distance} cells"
                        ),
                        remediation=(
                            "Run pass_waterfalls before validation, or extend "
                            "drain_distance."
                        ),
                    )
                )

            # Foam / mist population check
            foam = stack.get("foam")
            if foam is None or not np.any(np.asarray(foam) > 0):
                issues.append(
                    ValidationIssue(
                        code="WATERFALL_FOAM_MISSING",
                        severity="soft",
                        message="Waterfall lips detected but no foam channel populated",
                        remediation="Run pass_waterfalls to populate foam channel.",
                    )
                )
            mist = stack.get("mist")
            if mist is None or not np.any(np.asarray(mist) > 0):
                issues.append(
                    ValidationIssue(
                        code="WATERFALL_MIST_MISSING",
                        severity="soft",
                        message="Waterfall lips detected but no mist channel populated",
                        remediation="Run pass_waterfalls to populate mist channel.",
                    )
                )

    # ------------------------------------------------------------------
    # Mode B: structured chain objects
    # ------------------------------------------------------------------
    required = ("source", "lip", "pool", "outflow")
    for idx, chain in enumerate(chains or ()):
        for attr in required:
            if isinstance(chain, dict):
                present = attr in chain and chain[attr] is not None
            else:
                present = getattr(chain, attr, None) is not None
            if not present:
                issues.append(
                    ValidationIssue(
                        code="WATERFALL_CHAIN_INCOMPLETE",
                        severity="hard",
                        affected_feature=f"waterfall_chain[{idx}]",
                        message=f"waterfall chain {idx} missing {attr!r}",
                        remediation=(
                            "Populate source/lip/pool/outflow before "
                            "readability audit"
                        ),
                    )
                )

    return issues


# ---------------------------------------------------------------------------
# Cave framing presence — stack-channel per-cell radius search
# ---------------------------------------------------------------------------


def check_cave_framing_presence(
    stack: TerrainMaskStack,
    caves: Optional[Sequence[Any]] = None,
    radius_cells: int = 5,
) -> List[ValidationIssue]:
    """Cave candidates must have framing geometry within a cell radius.

    Two modes:

    Mode A — stack inspection (always runs when cave_candidate is present):
        Each cave_candidate cell must have at least one of:
          (a) cave_height_delta != 0 within ``radius_cells`` — confirms
              the cave arch was actually carved.
          (b) hero_exclusion > 0 within ``radius_cells`` — confirms a
              designer-authored framing zone is present.
        Cells lacking both are counted as "unframed" and trigger a hard
        issue.

    Mode B — structured cave objects (runs when ``caves`` is supplied):
        Each cave item must carry >= 2 framing_markers and a damp_signal
        > 0.  Missing attributes are hard issues.
    """
    issues: List[ValidationIssue] = []

    # ------------------------------------------------------------------
    # Mode A: stack inspection
    # ------------------------------------------------------------------
    cave_raw = stack.get("cave_candidate")
    if cave_raw is not None and np.any(np.asarray(cave_raw) > 0):
        cave_arr = np.asarray(cave_raw, dtype=np.float32)
        delta = _safe_asarray(stack.get("cave_height_delta"))
        framing = _safe_asarray(stack.get("hero_exclusion"))

        cave_rows, cave_cols = np.where(cave_arr > 0)
        unframed = 0

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
                    code="CAVE_FRAMING_ABSENT_STACK",
                    severity="hard",
                    message=(
                        f"{unframed} cave candidate cell(s) have no framing geometry "
                        f"(cave_height_delta or hero_exclusion) within {radius_cells} "
                        f"cells"
                    ),
                    remediation=(
                        "Run pass_caves to populate cave_height_delta, or author a "
                        "hero_exclusion zone around each cave entrance."
                    ),
                )
            )

    # ------------------------------------------------------------------
    # Mode B: structured cave objects
    # ------------------------------------------------------------------
    for idx, cave in enumerate(caves or ()):
        if isinstance(cave, dict):
            framing_markers = cave.get("framing_markers") or ()
            damp = cave.get("damp_signal")
        else:
            framing_markers = getattr(cave, "framing_markers", ()) or ()
            damp = getattr(cave, "damp_signal", None)

        if len(framing_markers) < 2:
            issues.append(
                ValidationIssue(
                    code="CAVE_FRAMING_INSUFFICIENT",
                    severity="hard",
                    affected_feature=f"cave[{idx}]",
                    message=(
                        f"cave {idx} has {len(framing_markers)} framing markers; "
                        "require >= 2"
                    ),
                    remediation="Place framing rocks at cave mouth",
                )
            )

        if damp is None or (isinstance(damp, (int, float)) and float(damp) <= 0.0):
            issues.append(
                ValidationIssue(
                    code="CAVE_DAMP_MISSING",
                    severity="hard",
                    affected_feature=f"cave[{idx}]",
                    message=f"cave {idx} missing damp signal",
                    remediation="Paint damp mask at cave entrance",
                )
            )

    return issues


# ---------------------------------------------------------------------------
# Focal composition — rule of thirds + occlusion
# ---------------------------------------------------------------------------


def check_focal_composition(
    stack: TerrainMaskStack,
    focal_point: Optional[Tuple[float, float]] = None,
    occlusion_slope_threshold: float = math.radians(70.0),
) -> List[ValidationIssue]:
    """Focal point must land near a rule-of-thirds intersection and not be occluded.

    ``focal_point`` is a normalised (u, v) pair in [0, 1].  The four
    rule-of-thirds intersections are at (1/3, 1/3), (2/3, 1/3),
    (1/3, 2/3), (2/3, 2/3).  The minimum distance must be < 0.10.

    Additionally, if the stack has slope and height channels, the terrain
    cell at the focal point is checked for occlusion:
      - slope >= ``occlusion_slope_threshold`` (default 70°) → the focal
        point sits on a near-vertical wall face and will likely be
        invisible from any reasonable camera angle.
    """
    issues: List[ValidationIssue] = []

    if focal_point is None:
        return issues

    u, v = float(focal_point[0]), float(focal_point[1])
    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        issues.append(
            ValidationIssue(
                code="FOCAL_OUT_OF_FRAME",
                severity="hard",
                message=f"focal point ({u:.3f}, {v:.3f}) outside [0,1]^2",
                remediation="Reposition camera or focal anchor",
            )
        )
        return issues

    # Rule-of-thirds distance check
    thirds = [(1 / 3, 1 / 3), (2 / 3, 1 / 3), (1 / 3, 2 / 3), (2 / 3, 2 / 3)]
    d_min = min(((u - tu) ** 2 + (v - tv) ** 2) ** 0.5 for tu, tv in thirds)
    if d_min > 0.10:
        issues.append(
            ValidationIssue(
                code="FOCAL_COMPOSITION_OFF_THIRDS",
                severity="hard",
                message=(
                    f"focal point ({u:.3f},{v:.3f}) is {d_min:.3f} from nearest "
                    "rule-of-thirds intersection (limit 0.10)"
                ),
                remediation="Nudge focal point toward a thirds intersection",
            )
        )

    # Occlusion check: slope at the focal-point cell
    if stack.height is not None and stack.get("slope", default=None) is not None:  # FIX-10-H14
        h = np.asarray(stack.height, dtype=np.float64)
        slope_arr = np.asarray(stack.get("slope"), dtype=np.float64)
        if h.ndim == 2 and slope_arr.shape == h.shape:
            rows, cols = h.shape
            row_idx = int(np.clip(round(v * (rows - 1)), 0, rows - 1))
            col_idx = int(np.clip(round(u * (cols - 1)), 0, cols - 1))
            local_slope = float(slope_arr[row_idx, col_idx])
            if local_slope >= occlusion_slope_threshold:
                issues.append(
                    ValidationIssue(
                        code="FOCAL_POINT_OCCLUDED",
                        severity="soft",
                        message=(
                            f"Focal point ({u:.3f}, {v:.3f}) sits on a near-vertical "
                            f"face (slope={math.degrees(local_slope):.1f}°) — "
                            f"likely occluded from sightlines"
                        ),
                        remediation=(
                            "Move focal point away from wall faces, or flatten the "
                            "surrounding cell via a flatten-zone pass."
                        ),
                    )
                )

    return issues


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_asarray(arr: Any) -> Optional[np.ndarray]:
    if arr is None:
        return None
    return np.asarray(arr)


# ---------------------------------------------------------------------------
# Aggregate audit entry-point
# ---------------------------------------------------------------------------


def run_semantic_readability_audit(
    stack: TerrainMaskStack,
    *,
    chains: Optional[Sequence[Any]] = None,
    caves: Optional[Sequence[Any]] = None,
    focal: Optional[Tuple[float, float]] = None,
) -> List[ValidationIssue]:
    """Run all terrain-semantic readability checks.

    Callers receive a flat list of issues.  An empty list means the
    audit passed; any hard issue is treated as a release blocker.

    All checks inspect the TerrainMaskStack directly.  Optional
    structured ``chains`` and ``caves`` sequences are also validated
    when supplied.
    """
    issues: List[ValidationIssue] = []
    issues.extend(check_cliff_silhouette_readability(stack))
    issues.extend(check_waterfall_chain_completeness(stack, chains=chains))
    issues.extend(check_cave_framing_presence(stack, caves=caves))
    if focal is not None:
        issues.extend(check_focal_composition(stack, focal_point=focal))
    return issues

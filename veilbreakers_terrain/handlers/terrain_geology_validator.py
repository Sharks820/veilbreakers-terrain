"""Bundle I — terrain_geology_validator.

Validation helpers for geology plausibility. Also owns the
``register_bundle_i_passes()`` registrar for all Bundle I passes.

Pure numpy, no bpy.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np

from .terrain_semantics import (
    TerrainMaskStack,
    ValidationIssue,
)


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def validate_strata_consistency(
    stack: TerrainMaskStack,
    tol_deg: float = 5.0,
) -> List[ValidationIssue]:
    """Strata orientation must vary smoothly over the tile.

    We check that the angular difference between each cell's bedding
    normal and its 4-neighbor average is under ``tol_deg`` degrees.
    Returns a soft issue if more than 5% of cells exceed the tolerance.
    """
    issues: List[ValidationIssue] = []
    orient = stack.strata_orientation
    if orient is None:
        issues.append(
            ValidationIssue(
                code="STRATA_MISSING",
                severity="soft",
                message="strata_orientation channel not populated",
            )
        )
        return issues

    arr = np.asarray(orient, dtype=np.float64)
    if arr.ndim != 3 or arr.shape[-1] != 3:
        issues.append(
            ValidationIssue(
                code="STRATA_BAD_SHAPE",
                severity="hard",
                message=f"strata_orientation must be (H,W,3), got {arr.shape}",
            )
        )
        return issues

    # Smoothed orientation (4-neighbor mean, not including self)
    # Edge-reflect padding prevents toroidal seam contamination from np.roll.
    _padded = np.pad(arr, ((1, 1), (1, 1), (0, 0)), mode="edge")
    up    = _padded[:-2, 1:-1]
    down  = _padded[2:,  1:-1]
    left  = _padded[1:-1, :-2]
    right = _padded[1:-1, 2:]
    avg = (up + down + left + right) / 4.0

    # Normalize both
    def _norm(v: np.ndarray) -> np.ndarray:
        n = np.sqrt((v * v).sum(axis=-1, keepdims=True))
        return v / np.where(n < 1e-9, 1.0, n)

    a = _norm(arr)
    b = _norm(avg)
    dot = np.clip((a * b).sum(axis=-1), -1.0, 1.0)
    angle_deg = np.degrees(np.arccos(dot))

    # Strip edges (roll introduces wrap artifacts)
    inner = angle_deg[1:-1, 1:-1]
    if inner.size == 0:
        return issues

    violation_frac = float((inner > tol_deg).mean())
    if violation_frac > 0.05:
        issues.append(
            ValidationIssue(
                code="STRATA_INCONSISTENT",
                severity="soft",
                message=(
                    f"{violation_frac*100:.1f}% of cells exceed "
                    f"{tol_deg}° strata-orientation tolerance"
                ),
                remediation="reduce dip variance or increase smoothing",
            )
        )
    return issues


def validate_strahler_ordering(
    water_network: Optional[Any],
) -> List[ValidationIssue]:
    """Validate Strahler stream-ordering topology using BFS from outlets.

    Strahler ordering rules (Strahler 1952):
      - Order 1: headwater streams (no tributaries).
      - Order N: confluence of two order-(N-1) streams raises the order to N.
      - Merging streams of unequal order keeps the higher order unchanged.

    This function accepts a river network in several formats (see below),
    computes the expected Strahler order for every node via BFS from the
    outlet(s), then flags any edge where a *higher-order stream feeds into a
    lower-order one* — a topological impossibility under Strahler rules.

    Accepted ``water_network`` formats
    -----------------------------------
    1. **Dict with ``nodes`` + ``edges`` keys** (preferred)::

           {
             "nodes": [{"id": "n0"}, {"id": "n1"}, ...],
             "edges": [{"from": "n0", "to": "n1"}, ...]
           }

       Edges are directed *downstream* (from tributary toward outlet).
       If a ``strahler_order`` key is present on an edge or node it is used
       as the asserted order for violation-detection; otherwise the function
       computes orders from topology.

    2. **Flat list of stream records** — same legacy format as before::

           [{"order": 2, "parent_order": 1}, ...]

       or list-of-2-tuples ``[(order, parent_order), ...]``.
       Topology BFS is skipped; the flat-list path checks the
       ``order > parent_order + 1`` rule directly.

    3. **Object with ``.streams`` attribute or dict with ``"streams"`` key**
       — same legacy flat-record path as format 2.

    4. **networkx DiGraph** (``edges(data=True)``) — BFS is performed on the
       graph; asserted orders are taken from edge ``strahler_order`` attrs when
       present.

    Returns
    -------
    List of :class:`ValidationIssue` (severity ``"soft"``) for every
    detected violation.  An empty list means the network is topologically
    consistent with Strahler rules.
    """
    issues: List[ValidationIssue] = []
    if water_network is None:
        return issues

    # ------------------------------------------------------------------
    # Helper: extract a value from a dict-or-object
    # ------------------------------------------------------------------
    def _get(obj: Any, name: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    def _first_present(obj: Any, *names: str) -> Any:
        for name in names:
            value = _get(obj, name)
            if value is not None:
                return value
        return None

    def _segment_edges_from_network(obj: Any) -> Optional[Dict[str, Any]]:
        segments_obj = _get(obj, "segments")
        if segments_obj is None:
            return None
        segment_values = (
            list(segments_obj.values())
            if isinstance(segments_obj, dict)
            else list(segments_obj)
        )
        asserted_by_segment = _get(obj, "strahler_orders", {}) or {}
        edges: list[dict[str, Any]] = []
        for segment in segment_values:
            src = _get(segment, "source_node_id")
            dst = _get(segment, "target_node_id")
            if src is None or dst is None:
                continue
            segment_id = _get(segment, "segment_id")
            asserted = _get(segment, "strahler_order")
            if asserted is None and segment_id is not None:
                asserted = asserted_by_segment.get(segment_id)
                if asserted is None:
                    asserted = asserted_by_segment.get(str(segment_id))
            edge = {"from": src, "to": dst}
            if asserted is not None:
                edge["strahler_order"] = int(asserted)
            edges.append(edge)
        if not edges:
            return None
        nodes_obj = _get(obj, "nodes", {}) or {}
        node_values = (
            list(nodes_obj.values())
            if isinstance(nodes_obj, dict)
            else list(nodes_obj)
        )
        nodes = []
        for node in node_values:
            node_id = _get(node, "node_id", _get(node, "id"))
            if node_id is None:
                continue
            node_row = {"id": node_id}
            node_order = _get(node, "strahler_order")
            if node_order is not None:
                node_row["strahler_order"] = int(node_order)
            nodes.append(node_row)
        return {"nodes": nodes, "edges": edges}

    segment_network = _segment_edges_from_network(water_network)
    if segment_network is not None:
        water_network = segment_network

    # ------------------------------------------------------------------
    # Path A: dict with "nodes"/"edges" — full BFS topology validation
    # ------------------------------------------------------------------
    if isinstance(water_network, dict) and "edges" in water_network:
        nodes_raw: List[Any] = list(water_network.get("nodes", []) or [])
        edges_raw: List[Any] = list(water_network.get("edges", []))
        # Build adjacency: downstream_of[node] = list of upstream nodes
        # Edges are directed FROM upstream TO downstream.
        downstream: Dict[Any, Any] = {}   # node -> downstream node
        upstream_of: Dict[Any, List[Any]] = {}  # node -> [upstream nodes]
        asserted_order: Dict[tuple, int] = {}  # (from, to) -> strahler_order
        asserted_node_order: Dict[Any, int] = {}

        for node in nodes_raw:
            node_id = _get(node, "id", _get(node, "node_id"))
            node_order = _get(node, "strahler_order", _get(node, "order"))
            if node_id is not None and node_order is not None:
                asserted_node_order[node_id] = int(node_order)

        for e in edges_raw:
            src = _first_present(e, "from", "source")
            dst = _first_present(e, "to", "target")
            if src is None or dst is None:
                continue
            if src in downstream and downstream[src] != dst:
                issues.append(
                    ValidationIssue(
                        code="STRAHLER_BRANCHING_DOWNSTREAM",
                        severity="hard",
                        affected_feature=f"node_{src}",
                        message=(
                            f"stream node {src!r} has multiple downstream "
                            "targets; river graph must split braided flow into "
                            "separate segment geometry, not topology forks"
                        ),
                        remediation="repair segment directions or merge forked downstream links",
                    )
                )
            downstream[src] = dst
            upstream_of.setdefault(dst, []).append(src)
            so = _get(e, "strahler_order")
            if so is not None:
                asserted_order[(src, dst)] = int(so)

        # Identify headwaters (nodes with no upstream neighbors)
        all_nodes: set = (
            set(downstream.keys())
            | set(upstream_of.keys())
            | set(asserted_node_order.keys())
        )
        headwaters = [n for n in all_nodes if n not in upstream_of]
        if edges_raw and not headwaters:
            issues.append(
                ValidationIssue(
                    code="STRAHLER_NO_HEADWATER",
                    severity="hard",
                    message="water network has edges but no headwater/source nodes",
                    remediation="break graph cycles or fix upstream/downstream directions",
                )
            )

        # BFS/post-order from headwaters to outlets to compute Strahler order.
        # We use iterative post-order DFS so deep networks don't hit Python's
        # recursion limit.
        computed: Dict[Any, int] = {}
        cycle_nodes: set[Any] = set()

        def _compute_order(start_node: Any) -> int:
            """Iterative post-order DFS to compute Strahler order."""
            stack = [(start_node, False)]
            visiting: set[Any] = set()
            while stack:
                node, visited = stack.pop()
                if visited:
                    visiting.discard(node)
                    ups = upstream_of.get(node, [])
                    if not ups:
                        computed[node] = 1
                    else:
                        child_orders = sorted(
                            [computed.get(u, 1) for u in ups], reverse=True
                        )
                        if len(child_orders) >= 2 and child_orders[0] == child_orders[1]:
                            computed[node] = child_orders[0] + 1
                        else:
                            computed[node] = child_orders[0]
                else:
                    if node in computed:
                        continue
                    if node in visiting:
                        cycle_nodes.add(node)
                        continue
                    visiting.add(node)
                    stack.append((node, True))
                    for up in upstream_of.get(node, []):
                        if up in visiting:
                            cycle_nodes.update((node, up))
                            continue
                        if up not in computed:
                            stack.append((up, False))
            return computed.get(start_node, 1)

        # Seed computation from every outlet (nodes with no downstream)
        outlets = [n for n in all_nodes if n not in downstream]
        if edges_raw and not outlets:
            issues.append(
                ValidationIssue(
                    code="STRAHLER_NO_OUTLET",
                    severity="hard",
                    message="water network has edges but no outlet/drain node; cycle likely",
                    remediation="break graph cycles or add an outlet/drain node",
                )
            )
        for outlet in outlets:
            _compute_order(outlet)

        if cycle_nodes:
            ordered_cycle_nodes = sorted(cycle_nodes, key=str)
            issues.append(
                ValidationIssue(
                    code="STRAHLER_CYCLE_OR_DISCONNECTED",
                    severity="hard",
                    message=(
                        "water network contains a cycle connected to an outlet: "
                        f"{ordered_cycle_nodes[:8]}"
                    ),
                    remediation="break graph cycles before computing Strahler ordering",
                )
            )

        unresolved = sorted((all_nodes - set(computed.keys())), key=str)
        if edges_raw and unresolved:
            issues.append(
                ValidationIssue(
                    code="STRAHLER_CYCLE_OR_DISCONNECTED",
                    severity="hard",
                    message=(
                        "water network contains nodes unreachable from outlets: "
                        f"{unresolved[:8]}"
                    ),
                    remediation="repair cycles, disconnected islands, or edge directions",
                )
            )

        # Validate each edge: upstream node order must be <= downstream order.
        # A violation occurs when a higher-order stream feeds into a lower-order
        # node — impossible under Strahler rules.
        for e_idx, e in enumerate(edges_raw):
            src = _first_present(e, "from", "source")
            dst = _first_present(e, "to", "target")
            if src is None or dst is None:
                continue

            src_order = asserted_order.get(
                (src, dst),
                asserted_node_order.get(src, computed.get(src, 1)),
            )
            dst_order = asserted_node_order.get(dst, computed.get(dst, 1))

            if src_order > dst_order:
                code = (
                    "STRAHLER_JUMP"
                    if src_order > dst_order + 1
                    else "STRAHLER_UPHILL_ORDER"
                )
                issues.append(
                    ValidationIssue(
                        code=code,
                        severity="soft",
                        affected_feature=f"edge_{e_idx}_{src}_to_{dst}",
                        message=(
                            f"stream edge {src!r}→{dst!r}: upstream order "
                            f"{src_order} > downstream order {dst_order} — "
                            "higher-order tributary feeding lower-order channel"
                        ),
                        remediation=(
                            "check edge direction or recompute Strahler orders "
                            "from corrected network topology"
                        ),
                    )
                )
        return issues

    # ------------------------------------------------------------------
    # Path B: networkx DiGraph
    # ------------------------------------------------------------------
    if callable(getattr(water_network, "edges", None)) and callable(
        getattr(water_network, "predecessors", None)
    ):
        # Build upstream_of from the graph and run the same BFS logic.
        upstream_of_nx: Dict[Any, List[Any]] = {}
        has_downstream_nx: set = set()
        asserted_nx: Dict[tuple, int] = {}

        for u, v, data in water_network.edges(data=True):
            upstream_of_nx.setdefault(v, []).append(u)
            has_downstream_nx.add(u)
            so = data.get("strahler_order") if isinstance(data, dict) else None
            if so is not None:
                asserted_nx[(u, v)] = int(so)

        all_nx = set(water_network.nodes())
        computed_nx: Dict[Any, int] = {}

        def _compute_nx(start: Any) -> int:
            stack = [(start, False)]
            while stack:
                node, visited = stack.pop()
                if visited:
                    ups = upstream_of_nx.get(node, [])
                    if not ups:
                        computed_nx[node] = 1
                    else:
                        child_orders = sorted(
                            [computed_nx.get(u, 1) for u in ups], reverse=True
                        )
                        if len(child_orders) >= 2 and child_orders[0] == child_orders[1]:
                            computed_nx[node] = child_orders[0] + 1
                        else:
                            computed_nx[node] = child_orders[0]
                else:
                    stack.append((node, True))
                    for up in upstream_of_nx.get(node, []):
                        if up not in computed_nx:
                            stack.append((up, False))
            return computed_nx.get(start, 1)

        outlets_nx = [n for n in all_nx if n not in has_downstream_nx]
        for outlet in outlets_nx:
            _compute_nx(outlet)

        for e_idx, (u, v, data) in enumerate(water_network.edges(data=True)):
            src_order = asserted_nx.get((u, v), computed_nx.get(u, 1))
            dst_order = computed_nx.get(v, 1)
            if src_order > dst_order:
                code = (
                    "STRAHLER_JUMP"
                    if src_order > dst_order + 1
                    else "STRAHLER_UPHILL_ORDER"
                )
                issues.append(
                    ValidationIssue(
                        code=code,
                        severity="soft",
                        affected_feature=f"edge_{e_idx}_{u}_to_{v}",
                        message=(
                            f"stream edge {u!r}→{v!r}: upstream order "
                            f"{src_order} > downstream order {dst_order}"
                        ),
                    )
                )
        return issues

    # ------------------------------------------------------------------
    # Path C: flat list / legacy object with .streams — order-pair checks
    # ------------------------------------------------------------------
    streams: Optional[Iterable[Any]] = None
    if hasattr(water_network, "streams"):
        streams = getattr(water_network, "streams")
    elif isinstance(water_network, dict) and "streams" in water_network:
        streams = water_network["streams"]
    elif isinstance(water_network, list):
        # Accept list-of-dicts (with "order"/"parent_order" keys) directly,
        # OR list-of-2-tuples [(order, parent_order), ...].
        streams_list: List[Any] = []
        for t in water_network:
            if isinstance(t, dict) and ("order" in t or "parent_order" in t):
                streams_list.append(t)
            elif isinstance(t, (tuple, list)) and len(t) >= 2:
                streams_list.append({"order": t[0], "parent_order": t[1]})
        streams = streams_list

    if streams is None:
        return issues

    for idx, s in enumerate(streams):
        order = _get(s, "order")
        parent_order = _get(s, "parent_order")
        if order is None or parent_order is None:
            continue
        order_i = int(order)
        parent_i = int(parent_order)

        # Strahler rule: a tributary's order must be <= parent order.
        # A single-step rise is still a topology violation, while a jump of
        # more than one order indicates obviously corrupted ordering metadata.
        if order_i > parent_i + 1:
            issues.append(
                ValidationIssue(
                    code="STRAHLER_JUMP",
                    severity="soft",
                    affected_feature=f"stream_{idx}",
                    message=(
                        f"stream order {order_i} jumps more than one level above "
                        f"parent (downstream) order {parent_i}"
                    ),
                    remediation=(
                        "recompute Strahler orders from the stream network and "
                        "verify parent/downstream links"
                    ),
                )
            )
        elif order_i > parent_i:
            issues.append(
                ValidationIssue(
                    code="STRAHLER_UPHILL_ORDER",
                    severity="soft",
                    affected_feature=f"stream_{idx}",
                    message=(
                        f"stream order {order_i} exceeds parent (downstream) "
                        f"order {parent_i} — higher-order stream cannot "
                        "feed into a lower-order channel"
                    ),
                    remediation=(
                        "verify stream direction; tributaries must be "
                        "equal-or-lower order than the channel they join"
                    ),
                )
            )
    return issues


def validate_glacial_plausibility(
    stack: TerrainMaskStack,
    glacier_paths: Sequence[Dict[str, Any]],
    tree_line_altitude_m: float = 1800.0,
) -> List[ValidationIssue]:
    """U-valleys should be carved only above the tree line.

    For every point in every glacier path, verify the underlying
    ``stack.height`` is at or above ``tree_line_altitude_m``. Reports a
    hard issue per path that dips too low.
    """
    issues: List[ValidationIssue] = []
    if stack.height is None:
        return issues
    h = np.asarray(stack.height, dtype=np.float64)
    H, W = h.shape

    for i, gp in enumerate(glacier_paths):
        path = gp.get("path", []) if isinstance(gp, dict) else []
        if not path:
            continue
        too_low_count = 0
        for (wx, wy) in path:
            c = int(round((wx - stack.world_origin_x) / stack.cell_size))
            r = int(round((wy - stack.world_origin_y) / stack.cell_size))
            if not (0 <= r < H and 0 <= c < W):
                continue
            if h[r, c] < tree_line_altitude_m:
                too_low_count += 1
        if too_low_count > 0:
            issues.append(
                ValidationIssue(
                    code="GLACIER_BELOW_TREELINE",
                    severity="hard",
                    affected_feature=f"glacier_{i}",
                    message=(
                        f"{too_low_count} points of glacier_{i} lie below "
                        f"tree line {tree_line_altitude_m} m"
                    ),
                    remediation="raise glacier path or lower tree line",
                )
            )
    return issues


def validate_karst_plausibility(
    stack: TerrainMaskStack,
    karst_features: Sequence[Any],
    min_hardness: float = 0.35,
    max_hardness: float = 0.75,
) -> List[ValidationIssue]:
    """Karst should only form in soluble rock (limestone-like hardness).

    Reports a hard issue for any feature whose local ``rock_hardness``
    falls outside [min_hardness, max_hardness].
    """
    issues: List[ValidationIssue] = []
    if stack.rock_hardness is None:
        return issues
    hardness = np.asarray(stack.rock_hardness, dtype=np.float64)
    H, W = hardness.shape

    for f in karst_features:
        pos = getattr(f, "world_pos", None) or (
            f.get("world_pos") if isinstance(f, dict) else None
        )
        fid = getattr(f, "feature_id", None) or (
            f.get("feature_id") if isinstance(f, dict) else "unknown"
        )
        if pos is None:
            continue
        c = int(round((pos[0] - stack.world_origin_x) / stack.cell_size))
        r = int(round((pos[1] - stack.world_origin_y) / stack.cell_size))
        if not (0 <= r < H and 0 <= c < W):
            continue
        local = float(hardness[r, c])
        if not (min_hardness <= local <= max_hardness):
            issues.append(
                ValidationIssue(
                    code="KARST_WRONG_ROCK",
                    severity="hard",
                    affected_feature=fid,
                    message=(
                        f"karst feature {fid} at hardness={local:.2f} "
                        f"outside soluble band [{min_hardness},{max_hardness}]"
                    ),
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Bundle registrar
# ---------------------------------------------------------------------------


BUNDLE_I_PASSES = (
    "stratigraphy",
    "glacial",
    "wind_erosion",
    "coastline",
    "karst",
)


def register_bundle_i_passes() -> None:
    """Register every Bundle I pass on the TerrainPassController.

    Does NOT modify ``register_default_passes``. Call this explicitly
    (same pattern as Bundle J).
    """
    from .terrain_pipeline import TerrainPassController
    from .terrain_semantics import PassDefinition

    from . import (
        coastline as _coastline,
        terrain_glacial as _glacial,
        terrain_karst as _karst,
        terrain_stratigraphy as _strat,
        terrain_wind_erosion as _wind,
    )

    TerrainPassController.register_pass(
        PassDefinition(
            name="stratigraphy",
            func=_strat.pass_stratigraphy,
            requires_channels=("height",),
            produces_channels=(
                "rock_hardness",
                "strata_orientation",
                "strat_erosion_delta",
                "unconformity_mask",
                "intrusion_mask",
                "albedo_shift_rgb",
                "strata_cross_section",
            ),
            seed_namespace="stratigraphy",
            requires_scene_read=False,
            description="Bundle I: rock hardness + strata orientation",
        )
    )
    TerrainPassController.register_pass(
        PassDefinition(
            name="glacial",
            func=_glacial.pass_glacial,
            requires_channels=("height",),
            produces_channels=("snow_line_factor", "glacial_delta"),
            # OVERRIDE: Bundle A's ``snow_line`` pass writes a sigmoid-altitude
            # baseline ``snow_line_factor``. Bundle I's glacial pass refines it
            # with glacial-carving context (ice flow reduces local snow line,
            # moraine accumulation raises it) and writes the authoritative
            # value used by downstream materials / ecosystem passes.
            overrides=("snow_line_factor",),
            seed_namespace="glacial",
            requires_scene_read=False,
            description="Bundle I: glacial carving + snow line",
        )
    )
    TerrainPassController.register_pass(
        PassDefinition(
            name="wind_erosion",
            func=_wind.pass_wind_erosion,
            requires_channels=("height",),
            produces_channels=("wind_erosion_delta",),
            seed_namespace="wind_erosion",
            requires_scene_read=False,
            description="Bundle I: aeolian erosion + dune generation",
        )
    )
    TerrainPassController.register_pass(
        PassDefinition(
            name="coastline",
            func=_coastline.pass_coastline,
            requires_channels=("height",),
            produces_channels=("tidal", "tidal_zone_label", "wave_energy", "coastline_delta"),
            seed_namespace="coastline",
            requires_scene_read=False,
            description="Bundle I: wave energy + tidal zones + cliff retreat",
        )
    )
    TerrainPassController.register_pass(
        PassDefinition(
            name="karst",
            func=_karst.pass_karst,
            requires_channels=("height", "rock_hardness"),
            produces_channels=("karst_delta",),
            seed_namespace="karst",
            requires_scene_read=False,
            protocol_enforced=True,
            protocol_require_rule_2=False,
            protocol_require_rule_5=True,
            protocol_bulk_edit=True,
            description="Bundle I: karst feature detection + carving",
        )
    )


__all__ = [
    "validate_strata_consistency",
    "validate_strahler_ordering",
    "validate_glacial_plausibility",
    "validate_karst_plausibility",
    "register_bundle_i_passes",
    "BUNDLE_I_PASSES",
]

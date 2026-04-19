"""Bundle J — terrain_ecotone_graph.

Builds an adjacency graph of biomes present on a tile and defines the
smooth transition zones between them (ecotones). Outputs are stored on
``stack.populated_by_pass['ecotone_graph']`` via metrics; the graph is
also returned to the caller.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)


@dataclass
class EcotoneEdge:
    """Describes a transition between two adjacent biomes."""

    from_biome: int
    to_biome: int
    transition_width_m: float
    mixing_curve: str = "smoothstep"  # "linear" | "smoothstep" | "sigmoid"
    shared_cells: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "from_biome": int(self.from_biome),
            "to_biome": int(self.to_biome),
            "transition_width_m": float(self.transition_width_m),
            "mixing_curve": self.mixing_curve,
            "shared_cells": int(self.shared_cells),
        }


def _find_adjacencies(biome: np.ndarray) -> Dict[Tuple[int, int], int]:
    """Return a dict of (a, b) -> number of shared 4-neighbor borders.

    Always stores with ``a < b`` to deduplicate.

    Fully vectorised — no Python per-border loop.  All differing pairs are
    extracted as two flat arrays, canonicalised (min, max) with numpy, then
    counted via np.unique with return_counts=True.  O(N) in the number of
    border cells, all inside numpy C-layer.
    """
    def _count_pairs(arr_a: np.ndarray, arr_b: np.ndarray) -> Dict[Tuple[int, int], int]:
        """Vectorised count of canonicalised (min, max) pairs."""
        if arr_a.size == 0:
            return {}
        lo = np.minimum(arr_a, arr_b)   # canonical ordering — no Python loop
        hi = np.maximum(arr_a, arr_b)
        # Encode as single int64 key: lo * stride + hi.
        # Biome IDs are small (<2^24), stride = 2^24 is collision-free.
        _STRIDE = np.int64(1 << 24)
        encoded = lo.astype(np.int64) * _STRIDE + hi.astype(np.int64)
        unique_enc, counts = np.unique(encoded, return_counts=True)
        result: Dict[Tuple[int, int], int] = {}
        for enc, cnt in zip(unique_enc.tolist(), counts.tolist()):
            a = int(enc // _STRIDE)
            b = int(enc %  _STRIDE)
            result[(a, b)] = int(cnt)
        return result

    pairs: Dict[Tuple[int, int], int] = {}

    # Horizontal neighbors
    left  = biome[:, :-1]
    right = biome[:, 1:]
    diff_h = left != right
    h_pairs = _count_pairs(left[diff_h], right[diff_h])
    for k, v in h_pairs.items():
        pairs[k] = pairs.get(k, 0) + v

    # Vertical neighbors
    up   = biome[:-1, :]
    down = biome[1:, :]
    diff_v = up != down
    v_pairs = _count_pairs(up[diff_v], down[diff_v])
    for k, v in v_pairs.items():
        pairs[k] = pairs.get(k, 0) + v

    return pairs


def build_ecotone_graph(stack: TerrainMaskStack) -> Dict[str, Any]:
    """Return a dict describing the biome adjacency graph.

    If ``stack.biome_id`` is None, returns an empty graph.

    Shape::
        {
            "nodes": [biome_id, ...],
            "edges": [EcotoneEdge.as_dict(), ...],
            "cell_size_m": float,
            "tile_size": int,
        }
    """
    if stack.biome_id is None:
        return {
            "nodes": [],
            "edges": [],
            "cell_size_m": float(stack.cell_size),
            "tile_size": int(stack.tile_size),
        }

    biome = np.asarray(stack.biome_id, dtype=np.int64)
    nodes = sorted({int(v) for v in np.unique(biome).tolist()})
    adjacencies = _find_adjacencies(biome)

    edges: List[EcotoneEdge] = []
    for (a, b), shared in sorted(adjacencies.items()):
        # Transition width scales with shared border length (cells * cell_size)
        width = float(max(2, min(32, int(round(shared ** 0.5)))) * stack.cell_size)
        edges.append(
            EcotoneEdge(
                from_biome=a,
                to_biome=b,
                transition_width_m=width,
                mixing_curve="smoothstep",
                shared_cells=int(shared),
            )
        )

    return {
        "nodes": nodes,
        "edges": [e.as_dict() for e in edges],
        "cell_size_m": float(stack.cell_size),
        "tile_size": int(stack.tile_size),
    }


def validate_ecotone_smoothness(graph: Dict[str, Any]) -> List[ValidationIssue]:
    """Flag any ecotone edge whose transition_width is unreasonably narrow.

    Narrow edges (< 2 cells) signal hard biome boundaries, which look
    painterly rather than natural. Soft issue (warning).
    """
    issues: List[ValidationIssue] = []
    cell_size = float(graph.get("cell_size_m", 1.0) or 1.0)
    for edge in graph.get("edges", []):
        width = float(edge.get("transition_width_m", 0.0))
        if width < 2.0 * cell_size:
            issues.append(
                ValidationIssue(
                    code="ECOTONE_HARD_BOUNDARY",
                    severity="soft",
                    message=(
                        f"biomes {edge['from_biome']}->{edge['to_biome']} "
                        f"have narrow ecotone {width:.2f}m (< 2 cells)"
                    ),
                )
            )
    return issues


def pass_ecotones(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle J pass: build ecotone graph.

    Consumes: height, biome_id (optional)
    Produces: (metadata only; no new mask channel)
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    # Populate traversability as the Unity-ready channel this pass guarantees,
    # so protocol Rule 7 holds even when biome_id is absent. Only compute if
    # not already populated.
    if stack.traversability is None:
        from .terrain_navmesh_export import compute_traversability

        stack.set("traversability", compute_traversability(stack), "ecotones")

    graph = build_ecotone_graph(stack)
    issues = validate_ecotone_smoothness(graph)

    return PassResult(
        pass_name="ecotones",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("traversability",),
        metrics={
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
            "graph": graph,
        },
        issues=issues,
    )


def register_bundle_j_ecotones_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="ecotones",
            func=pass_ecotones,
            # NOTE: produces_channels=("traversability",) overlaps with navmesh.
            # This is NOT a clobber: pass_ecotones explicitly guards with
            # `if stack.traversability is None` so navmesh's traversability
            # survives when navmesh runs first. Declared as produced so the
            # DAG recognises ecotones as a fallback producer for tiles where
            # navmesh was skipped.
            requires_channels=("height",),
            produces_channels=("traversability",),
            seed_namespace="ecotones",
            requires_scene_read=False,
            description="Bundle J: biome adjacency / ecotone graph",
        )
    )


__all__ = [
    "EcotoneEdge",
    "build_ecotone_graph",
    "validate_ecotone_smoothness",
    "pass_ecotones",
    "register_bundle_j_ecotones_pass",
]

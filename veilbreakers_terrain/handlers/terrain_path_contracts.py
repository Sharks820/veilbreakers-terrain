"""Path, road, river-crossing, and bridge contracts for terrain nodes."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal, Tuple


Vec3 = Tuple[float, float, float]
ContinuationEdge = Literal["north", "south", "east", "west", "internal", "none"]
PathSegmentType = Literal["path", "road", "bridge", "ford", "riverwalk"]


def infer_continuation_edge(
    points: Tuple[Vec3, ...] | list[Vec3],
    terrain_bounds: tuple[float, float, float, float] | None,
    *,
    tolerance_m: float = 1.0,
) -> ContinuationEdge:
    """Infer which node edge a path continues through from either endpoint."""
    if not points or terrain_bounds is None:
        return "internal"
    min_x, min_y, max_x, max_y = (float(v) for v in terrain_bounds)

    def _edge_for(point: Vec3) -> ContinuationEdge:
        x, y, _ = point
        candidates = [
            ("west", abs(float(x) - min_x)),
            ("east", abs(float(x) - max_x)),
            ("south", abs(float(y) - min_y)),
            ("north", abs(float(y) - max_y)),
        ]
        edge, distance = min(candidates, key=lambda item: item[1])
        if distance <= float(tolerance_m):
            return edge  # type: ignore[return-value]
        return "internal"

    end_edge = _edge_for(points[-1])
    if end_edge != "internal":
        return end_edge
    start_edge = _edge_for(points[0])
    if start_edge != "internal":
        return start_edge
    return "internal"


def material_stack_for_path(
    surface_or_type: str,
    *,
    bridge: bool = False,
) -> Tuple[str, ...]:
    """Return the required material layers for road/path/bridge generation."""
    key = str(surface_or_type or "").strip().lower()
    if bridge:
        if key in {"trail", "path", "dirt_track", "rope"}:
            return ("wood_planks", "bridge_edge", "approach_transition")
        return ("stone_deck", "bridge_edge", "approach_transition")
    if key in {"trail", "path"}:
        return ("road_core", "road_edge", "approach_transition", "dirt_path")
    if key in {"dirt", "dirt_track"}:
        return ("road_core", "road_edge", "approach_transition", "compacted_dirt")
    if key in {"gravel", "gravel_road"}:
        return ("road_core", "road_edge", "approach_transition", "gravel")
    if key in {"paved", "paved_road", "highway", "main"}:
        return ("road_core", "road_edge", "approach_transition", "cobblestone_floor")
    return ("road_core", "road_edge", "approach_transition", key or "terrain_path")


@dataclass(frozen=True)
class PathSegmentContract:
    segment_id: str
    segment_type: PathSegmentType
    points: Tuple[Vec3, ...]
    width_m: float
    material_stack: Tuple[str, ...]
    continuation_edge: ContinuationEdge = "internal"
    crosses_water: bool = False
    water_depth_m: float = 0.0
    bridge_required: bool = False
    bridge_span_m: float = 0.0
    bridge_clearance_m: float = 0.0
    max_grade: float = 0.18
    metadata: dict[str, Any] = field(default_factory=dict)

    def length_m(self) -> float:
        total = 0.0
        for a, b in zip(self.points, self.points[1:]):
            total += math.dist(a, b)
        return total

    def max_observed_grade(self) -> float:
        max_grade = 0.0
        for a, b in zip(self.points, self.points[1:]):
            horizontal = math.hypot(b[0] - a[0], b[1] - a[1])
            if horizontal <= 1.0e-6:
                if not math.isclose(b[2], a[2]):
                    return math.inf
                continue
            max_grade = max(max_grade, abs(b[2] - a[2]) / horizontal)
        return max_grade

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "segment_type": self.segment_type,
            "points": [list(p) for p in self.points],
            "width_m": float(self.width_m),
            "material_stack": list(self.material_stack),
            "continuation_edge": self.continuation_edge,
            "crosses_water": bool(self.crosses_water),
            "water_depth_m": float(self.water_depth_m),
            "bridge_required": bool(self.bridge_required),
            "bridge_span_m": float(self.bridge_span_m),
            "bridge_clearance_m": float(self.bridge_clearance_m),
            "max_grade": float(self.max_grade),
            "observed_max_grade": self.max_observed_grade(),
            "length_m": self.length_m(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PathNetworkContract:
    node_id: str
    segments: Tuple[PathSegmentContract, ...] | list[PathSegmentContract]
    continuation_edges: Tuple[ContinuationEdge, ...] = ("north", "south", "east", "west")
    material_layers_required: Tuple[str, ...] = ("road_core", "road_edge", "approach_transition")

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "PathNetworkContract",
            "node_id": self.node_id,
            "continuation_edges": list(self.continuation_edges),
            "material_layers_required": list(self.material_layers_required),
            "segments": [segment.to_dict() for segment in self.segments],
        }


def validate_path_network_contract(network: PathNetworkContract) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    seen: set[str] = set()
    for segment in network.segments:
        prefix = segment.segment_id or "<unnamed>"
        if not segment.segment_id:
            issues.append({"code": "missing_segment_id", "message": "Path segment has no id"})
        if segment.segment_id in seen:
            issues.append({"code": "duplicate_segment_id", "message": f"{prefix} appears more than once"})
        seen.add(segment.segment_id)

        if len(segment.points) < 2:
            issues.append({"code": "path_segment_too_short", "message": f"{prefix} needs at least two points"})
        if segment.width_m <= 0.0:
            issues.append({"code": "invalid_path_width", "message": f"{prefix} width must be positive"})
        if not segment.material_stack:
            issues.append({"code": "missing_path_material_stack", "message": f"{prefix} has no material stack"})

        if segment.crosses_water and segment.water_depth_m > 0.75 and not (
            segment.bridge_required or segment.segment_type in {"bridge", "ford"}
        ):
            issues.append({
                "code": "deep_water_crossing_requires_bridge",
                "message": f"{prefix} crosses {segment.water_depth_m:.2f}m water without bridge/ford contract",
            })

        observed_grade = segment.max_observed_grade()
        if observed_grade > segment.max_grade:
            issues.append({
                "code": "path_grade_exceeds_budget",
                "message": f"{prefix} grade {observed_grade:.3f} exceeds budget {segment.max_grade:.3f}",
            })

        requires_bridge_geometry = segment.segment_type == "bridge" or (
            segment.bridge_required and segment.segment_type != "ford"
        )
        if segment.bridge_required and segment.segment_type not in {"bridge", "ford"}:
            issues.append({
                "code": "bridge_required_but_segment_not_bridge_or_ford",
                "message": f"{prefix} is marked bridge_required but segment_type is {segment.segment_type}",
            })

        if requires_bridge_geometry:
            if segment.bridge_span_m <= 0.0:
                issues.append({"code": "bridge_missing_span", "message": f"{prefix} bridge has no span"})
            if segment.bridge_clearance_m < max(0.75, segment.water_depth_m * 0.5):
                issues.append({"code": "bridge_clearance_too_low", "message": f"{prefix} clearance is too low"})
            if "approach_transition" not in segment.material_stack:
                issues.append({
                    "code": "bridge_missing_approach_material_transition",
                    "message": f"{prefix} needs approach transition material",
                })

        if segment.continuation_edge not in network.continuation_edges and segment.continuation_edge not in {"internal", "none"}:
            issues.append({"code": "invalid_continuation_edge", "message": f"{prefix} exits unknown edge"})
    return issues


__all__ = [
    "infer_continuation_edge",
    "material_stack_for_path",
    "PathNetworkContract",
    "PathSegmentContract",
    "validate_path_network_contract",
]

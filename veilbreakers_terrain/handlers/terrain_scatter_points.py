"""Canonical scatter point contracts for terrain vegetation and props.

The table mirrors the point-cloud workflow used by modern terrain tools:
World Creator instance exports, Unreal PCG point data, Houdini scatter points,
and Blender Geometry Nodes instancing all reduce to validated points carrying
transform, density, seed, prototype, species, mask provenance, and LOD data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence, Tuple


Vec3 = Tuple[float, float, float]
Quat = Tuple[float, float, float, float]


@dataclass(frozen=True)
class ScatterPoint:
    position: Vec3
    normal: Vec3
    orient: Quat
    scale: Vec3
    prototype_id: str
    species_id: str
    biome_id: str
    density: float
    seed: int
    slope: float
    height_m: float
    mask_sources: Tuple[str, ...]
    lod_bucket: str
    wind_profile: str
    source_layer: str = ""
    point_mode: str = "exact_instance"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": list(self.position),
            "normal": list(self.normal),
            "orient": list(self.orient),
            "scale": list(self.scale),
            "prototype_id": self.prototype_id,
            "species_id": self.species_id,
            "biome_id": self.biome_id,
            "density": float(self.density),
            "seed": int(self.seed),
            "slope": float(self.slope),
            "height_m": float(self.height_m),
            "mask_sources": list(self.mask_sources),
            "lod_bucket": self.lod_bucket,
            "wind_profile": self.wind_profile,
            "source_layer": self.source_layer,
            "point_mode": self.point_mode,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ScatterPointTable:
    # T1-27 (P0-internal): canonical storage is a tuple. The annotation
    # accepts a list at construction time for ergonomics (callers commonly
    # build ``ScatterPointTable(points=[...])``), but ``__post_init__``
    # freezes the input into a tuple so downstream code cannot mutate the
    # table by calling ``.points.append(...)`` on what is supposed to be a
    # frozen dataclass. Previously the mixed Tuple|list typing silently
    # tolerated mutation through aliased list references, breaking the
    # frozen invariant.
    points: Tuple[ScatterPoint, ...] | list[ScatterPoint]
    format: str = "ScatterPointTable"
    coordinate_space: str = "world_m"
    source: str = "canonical"

    def __post_init__(self) -> None:
        if not isinstance(self.points, tuple):
            object.__setattr__(self, "points", tuple(self.points))

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "coordinate_space": self.coordinate_space,
            "source": self.source,
            "point_count": len(self.points),
            "points": [point.to_dict() for point in self.points],
        }


@dataclass(frozen=True)
class ScatterCandidate:
    """Candidate row retained before final accept/reject.

    This is the auditable bridge between artist-friendly scatter rules and
    baked `ScatterPointTable` output. Rejected rows matter: they prove rocks,
    trees, vines, and props were filtered by terrain facts instead of silently
    disappearing or floating.
    """

    candidate_id: str
    source_rule_id: str
    source_layer_id: str
    species_or_prop_id: str
    sampled_position: Vec3
    sampled_slope_deg: float
    sampled_material_layer_id: str
    sampled_wetness: float
    sampled_deposition: float
    sampled_talus: float
    nearest_water_distance_m: float
    support_score: float
    embed_depth_m: float
    collision_reason: str = ""
    budget_reason: str = ""
    rejected_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source_rule_id": self.source_rule_id,
            "source_layer_id": self.source_layer_id,
            "species_or_prop_id": self.species_or_prop_id,
            "sampled_position": list(self.sampled_position),
            "sampled_slope_deg": float(self.sampled_slope_deg),
            "sampled_material_layer_id": self.sampled_material_layer_id,
            "sampled_wetness": float(self.sampled_wetness),
            "sampled_deposition": float(self.sampled_deposition),
            "sampled_talus": float(self.sampled_talus),
            "nearest_water_distance_m": float(self.nearest_water_distance_m),
            "support_score": float(self.support_score),
            "embed_depth_m": float(self.embed_depth_m),
            "collision_reason": self.collision_reason,
            "budget_reason": self.budget_reason,
            "rejected_reason": self.rejected_reason,
        }


@dataclass(frozen=True)
class ScatterCandidateTable:
    """Accepted and rejected scatter candidates with reason-code provenance."""

    accepted: Tuple[ScatterCandidate, ...] | list[ScatterCandidate] = ()
    rejected: Tuple[ScatterCandidate, ...] | list[ScatterCandidate] = ()
    format: str = "ScatterCandidateTable"
    coordinate_space: str = "world_m"
    source: str = "canonical"

    def __post_init__(self) -> None:
        # T1-27 (P0-internal): same fix as ScatterPointTable — freeze input
        # lists into tuples so the frozen dataclass invariant survives
        # mixed Tuple|list construction patterns.
        if not isinstance(self.accepted, tuple):
            object.__setattr__(self, "accepted", tuple(self.accepted))
        if not isinstance(self.rejected, tuple):
            object.__setattr__(self, "rejected", tuple(self.rejected))

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "coordinate_space": self.coordinate_space,
            "source": self.source,
            "accepted_count": len(self.accepted),
            "rejected_count": len(self.rejected),
            "accepted": [candidate.to_dict() for candidate in self.accepted],
            "rejected": [candidate.to_dict() for candidate in self.rejected],
        }


@dataclass(frozen=True)
class SurfaceSupportGate:
    """Terrain support thresholds for vegetation, rocks, and environmental props."""

    max_slope_deg: float = 45.0
    min_support_score: float = 0.55
    min_embed_depth_m: float = 0.02
    allowed_material_layer_ids: Tuple[str, ...] = ()
    allow_waterlogged: bool = True
    max_wetness: float = 1.0


def evaluate_surface_support(
    candidate: ScatterCandidate,
    gate: SurfaceSupportGate,
) -> ScatterCandidate:
    """Return candidate with `rejected_reason` populated when support fails."""
    reasons: list[str] = []
    if not all(math.isfinite(v) for v in candidate.sampled_position):
        reasons.append("non_finite_position")
    if not math.isfinite(float(candidate.sampled_slope_deg)):
        reasons.append("non_finite_slope")
    elif float(candidate.sampled_slope_deg) > float(gate.max_slope_deg):
        reasons.append("slope_exceeds_gate")
    if not math.isfinite(float(candidate.support_score)):
        reasons.append("non_finite_support_score")
    elif float(candidate.support_score) < float(gate.min_support_score):
        reasons.append("support_score_below_gate")
    if not math.isfinite(float(candidate.embed_depth_m)):
        reasons.append("non_finite_embed_depth")
    elif float(candidate.embed_depth_m) < float(gate.min_embed_depth_m):
        reasons.append("embed_depth_below_gate")
    if (
        gate.allowed_material_layer_ids
        and candidate.sampled_material_layer_id not in gate.allowed_material_layer_ids
    ):
        reasons.append("material_incompatible")
    sampled_wetness = float(candidate.sampled_wetness)
    max_wetness = float(gate.max_wetness)
    if not math.isfinite(sampled_wetness):
        reasons.append("non_finite_wetness")
    else:
        if not gate.allow_waterlogged and sampled_wetness > 1.0e-6:
            reasons.append("waterlogged_disallowed")
        if sampled_wetness > max_wetness:
            reasons.append("wetness_exceeds_gate")
    if candidate.collision_reason:
        reasons.append(f"collision:{candidate.collision_reason}")
    if candidate.budget_reason:
        reasons.append(f"budget:{candidate.budget_reason}")

    return replace(candidate, rejected_reason=";".join(reasons))


def build_scatter_candidate_table(
    candidates: Iterable[ScatterCandidate],
    gate: SurfaceSupportGate,
    *,
    source: str = "canonical",
) -> ScatterCandidateTable:
    """Evaluate candidates and split them into accepted/rejected rows."""
    accepted: list[ScatterCandidate] = []
    rejected: list[ScatterCandidate] = []
    for candidate in candidates:
        evaluated = evaluate_surface_support(candidate, gate)
        if evaluated.rejected_reason:
            rejected.append(evaluated)
        else:
            accepted.append(evaluated)
    return ScatterCandidateTable(
        accepted=tuple(accepted),
        rejected=tuple(rejected),
        source=source,
    )


def _float(row: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    raw = row.get(key, default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _int(row: Mapping[str, Any], key: str, default: int = 0) -> int:
    raw = row.get(key, default)
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return int(default)


def _quat_len(q: Quat) -> float:
    return math.sqrt(sum(v * v for v in q))


def _normalise_quat(q: Quat) -> Quat:
    length = _quat_len(q)
    if length <= 1.0e-8:
        return q
    return tuple(v / length for v in q)  # type: ignore[return-value]


def load_world_creator_instance_pointcloud(
    *,
    layer_id: str,
    prototype_id: str,
    species_id: str,
    biome_id: str,
    rows: Iterable[Mapping[str, Any]],
    model_scale: Sequence[float] = (1.0, 1.0, 1.0),
    coordinate_scale_m: float = 1024.0,
    lod_bucket: str = "lod0",
    wind_profile: str = "none",
) -> ScatterPointTable:
    """Convert World Creator-style instance CSV rows into ScatterPointTable.

    World Creator's conventional export stores normalized translation,
    per-instance scale, quaternion rotation, gradient, and seed. We preserve
    those fields and convert normalized coordinates into world meters.
    """
    sx_base, sy_base, sz_base = (float(model_scale[0]), float(model_scale[1]), float(model_scale[2]))
    points: list[ScatterPoint] = []
    for row in rows:
        density = max(0.0, min(1.0, _float(row, "gradient", 1.0)))
        orient = _normalise_quat((
            _float(row, "qx"),
            _float(row, "qy"),
            _float(row, "qz"),
            _float(row, "qw", 1.0),
        ))
        position = (
            _float(row, "tx") * coordinate_scale_m,
            _float(row, "ty") * coordinate_scale_m,
            _float(row, "tz") * coordinate_scale_m,
        )
        scale = (
            _float(row, "sx", 1.0) * sx_base,
            _float(row, "sy", 1.0) * sy_base,
            _float(row, "sz", 1.0) * sz_base,
        )
        points.append(
            ScatterPoint(
                position=position,
                normal=(0.0, 0.0, 1.0),
                orient=orient,
                scale=scale,
                prototype_id=prototype_id,
                species_id=species_id,
                biome_id=biome_id,
                density=density,
                seed=_int(row, "seed"),
                slope=0.0,
                height_m=position[2],
                mask_sources=(f"world_creator_instance:{layer_id}",),
                lod_bucket=lod_bucket,
                wind_profile=wind_profile,
                source_layer=layer_id,
                point_mode="exact_instance",
                metadata={"world_creator_gradient": density},
            )
        )
    return ScatterPointTable(points=tuple(points), source="world_creator_instance")


def validate_scatter_point_table(table: ScatterPointTable) -> list[dict[str, str]]:
    """Validate a ScatterPointTable against AAA scatter contracts.

    Per-point checks:
      - finite position / normal / orient
      - non-empty prototype/species/biome/mask/lod/wind ids
      - positive scale
      - density in [0, 1]
      - quaternion roughly unit-length
      - slope in [0, 90] degrees
      - height_m matches position[2] (catches mis-wired stacks)

    Whole-table checks (AAA scatter quality):
      - duplicate-position detection (perfect overlap = scatter bug)
      - species diversity heuristic (single-species table is suspicious
        for a populated biome)
      - floating / sub-water cell detection via abs(height_m) sanity range
    """
    issues: list[dict[str, str]] = []
    seen_positions: dict[tuple[int, int, int], int] = {}
    species_counter: dict[str, int] = {}
    for index, point in enumerate(table.points):
        prefix = f"point[{index}]"
        if not all(math.isfinite(v) for v in point.position):
            issues.append({"code": "invalid_position", "message": f"{prefix} has non-finite position"})
        if (
            not all(math.isfinite(v) for v in point.normal)
            or _quat_len((point.normal[0], point.normal[1], point.normal[2], 0.0)) <= 1.0e-6
        ):
            issues.append({"code": "invalid_normal", "message": f"{prefix} has zero normal"})
        if not point.prototype_id:
            issues.append({"code": "missing_prototype_id", "message": f"{prefix} has no prototype_id"})
        if not point.species_id:
            issues.append({"code": "missing_species_id", "message": f"{prefix} has no species_id"})
        if not point.biome_id:
            issues.append({"code": "missing_biome_id", "message": f"{prefix} has no biome_id"})
        if not point.mask_sources:
            issues.append({"code": "missing_mask_sources", "message": f"{prefix} has no mask provenance"})
        if not point.lod_bucket:
            issues.append({"code": "missing_lod_bucket", "message": f"{prefix} has no lod_bucket"})
        if not point.wind_profile:
            issues.append({"code": "missing_wind_profile", "message": f"{prefix} has no wind_profile"})
        orient_len = _quat_len(point.orient)
        if orient_len < 0.5:
            issues.append({"code": "invalid_orientation_quaternion", "message": f"{prefix} has invalid orient quaternion"})
        elif abs(orient_len - 1.0) > 0.05:
            issues.append({"code": "non_unit_orientation_quaternion", "message": f"{prefix} orient quaternion not unit-length (|q|={orient_len:.3f})"})
        if min(point.scale) <= 0.0:
            issues.append({"code": "invalid_scale", "message": f"{prefix} has non-positive scale"})
        if not 0.0 <= float(point.density) <= 1.0:
            issues.append({"code": "density_out_of_range", "message": f"{prefix} density outside [0,1]"})
        # Slope band — slope is degrees, must be in [0, 90].
        slope_val = float(point.slope)
        if not (0.0 <= slope_val <= 90.0):
            issues.append({"code": "slope_out_of_range", "message": f"{prefix} slope={slope_val:.2f}deg outside [0,90]"})
        # height_m / position[2] mismatch: the canonical contract is that
        # point.height_m == point.position[2] (world Z).  Allow 1 cm slack.
        if abs(float(point.height_m) - float(point.position[2])) > 0.01:
            issues.append({
                "code": "height_position_mismatch",
                "message": (
                    f"{prefix} height_m={point.height_m:.3f} != position.z={point.position[2]:.3f}"
                ),
            })
        # AAA "no floating objects" sanity: anything beyond ±10 km altitude
        # is almost certainly a unit-conversion bug.
        if abs(float(point.height_m)) > 10_000.0:
            issues.append({
                "code": "implausible_height",
                "message": f"{prefix} height_m={point.height_m:.1f}m outside ±10 km",
            })
        # Duplicate-position detection — round to mm to ignore float noise.
        # Skip points with non-finite positions (already flagged above).
        if all(math.isfinite(v) for v in point.position):
            key = (
                int(round(point.position[0] * 1000.0)),
                int(round(point.position[1] * 1000.0)),
                int(round(point.position[2] * 1000.0)),
            )
            prev = seen_positions.get(key)
            if prev is not None:
                issues.append({
                    "code": "duplicate_position",
                    "message": f"{prefix} duplicates point[{prev}] at mm-rounded position",
                })
            else:
                seen_positions[key] = index
        if point.species_id:
            species_counter[point.species_id] = species_counter.get(point.species_id, 0) + 1

    # Whole-table heuristics — only flag when the table is non-trivial.
    point_count = len(table.points)
    if point_count >= 25 and len(species_counter) == 1:
        only = next(iter(species_counter))
        issues.append({
            "code": "single_species_table",
            "message": (
                f"table contains {point_count} points but only species {only!r} — "
                "AAA scatter expects 2+ species per pass for visual diversity"
            ),
        })
    return issues


__all__ = [
    "ScatterCandidate",
    "ScatterCandidateTable",
    "ScatterPoint",
    "ScatterPointTable",
    "SurfaceSupportGate",
    "build_scatter_candidate_table",
    "evaluate_surface_support",
    "load_world_creator_instance_pointcloud",
    "validate_scatter_point_table",
]

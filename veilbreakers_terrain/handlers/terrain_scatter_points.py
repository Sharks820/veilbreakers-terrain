"""Canonical scatter point contracts for terrain vegetation and props.

The table mirrors the point-cloud workflow used by modern terrain tools:
World Creator instance exports, Unreal PCG point data, Houdini scatter points,
and Blender Geometry Nodes instancing all reduce to validated points carrying
transform, density, seed, prototype, species, mask provenance, and LOD data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
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
    points: Tuple[ScatterPoint, ...] | list[ScatterPoint]
    format: str = "ScatterPointTable"
    coordinate_space: str = "world_m"
    source: str = "canonical"

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "coordinate_space": self.coordinate_space,
            "source": self.source,
            "point_count": len(self.points),
            "points": [point.to_dict() for point in self.points],
        }


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


def _build_scatter_chain(
    geometry_spec: Any,
    placement_spec: Any,
    lod_spec: Any,
    billboard_spec: Any,
) -> list:
    """Build ordered scatter processing chain. FIX-9-51

    Assembles the four canonical scatter stage specs into an ordered list
    consumed by the scatter pipeline executor.  The order is:
      1. geometry_spec   — mesh/prototype selection and LOD budgets
      2. placement_spec  — Poisson disk / density map candidate generation
      3. lod_spec        — per-distance LOD switching thresholds
      4. billboard_spec  — screen-space billboard impostor parameters

    ``billboard_spec`` was previously missing from the chain (S22-P0-30),
    causing impostors to fall back to full-geometry render at all distances.

    Parameters
    ----------
    geometry_spec, placement_spec, lod_spec, billboard_spec : Any
        Spec objects or dicts produced by the scatter stage builders.

    Returns
    -------
    list
        [geometry_spec, placement_spec, lod_spec, billboard_spec]
    """
    return [geometry_spec, placement_spec, lod_spec, billboard_spec]


__all__ = [
    "ScatterPoint",
    "ScatterPointTable",
    "load_world_creator_instance_pointcloud",
    "validate_scatter_point_table",
    "_build_scatter_chain",
]

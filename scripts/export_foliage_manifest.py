"""Export scatter points to the VeilBreakers foliage placement manifest.

This replaces the retired DCC-specific scatter handoff. The output is the
engine-facing manifest consumed by Unity Terrain tree instances, Unity GPU
instancing, and editor import tooling. It requires real scatter input and a
mesh library; it does not generate placeholder grids or tool-specific scripts.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from veilbreakers_terrain.handlers.vegetation_system import (
    build_foliage_placement_manifest,
    load_mesh_library,
    write_foliage_placement_manifest,
)


def load_scatter_points(path: str | Path) -> list[dict[str, Any]]:
    """Load ScatterPointTable JSON as a list of placement records."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        points = data
    elif isinstance(data, dict) and isinstance(data.get("points"), list):
        points = data["points"]
    elif isinstance(data, dict):
        points = [data]
    else:
        raise ValueError(f"unrecognised scatter point JSON shape: {p}")
    out: list[dict[str, Any]] = []
    for index, point in enumerate(points):
        if not isinstance(point, dict):
            raise ValueError(f"scatter point {index} is not an object")
        out.append(point)
    return out


def _mesh_name_for_point(point: dict[str, Any]) -> str:
    mesh_name = point.get("mesh_name") or point.get("species_id") or point.get("prototype_id")
    if mesh_name:
        return str(mesh_name)
    return f"{point.get('type', 'unknown')}_{point.get('style', 'default')}"


def _position_for_point(point: dict[str, Any]) -> tuple[float, float, float]:
    raw = point.get("position") or point.get("position_world")
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        raise ValueError(f"scatter point missing 3D position: {point!r}")
    return float(raw[0]), float(raw[1]), float(raw[2])


def _rotation_deg_for_point(point: dict[str, Any]) -> float:
    """Return engine-world yaw in degrees without DCC axis remapping."""
    if "rotation" in point:
        return float(point["rotation"])
    if "rotation_y_rad" in point:
        return math.degrees(float(point["rotation_y_rad"]))
    if "yaw_rad" in point:
        return math.degrees(float(point["yaw_rad"]))
    if "yaw_deg" in point:
        return float(point["yaw_deg"])

    orient = point.get("orient") or point.get("rotation_quaternion")
    if isinstance(orient, (list, tuple)) and len(orient) >= 4:
        qx, qy, qz, qw = (float(orient[0]), float(orient[1]), float(orient[2]), float(orient[3]))
        length = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
        if length > 1e-12:
            qx, qy, qz, qw = qx / length, qy / length, qz / length, qw / length
            siny_cosp = 2.0 * (qw * qz + qx * qy)
            cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
            return math.degrees(math.atan2(siny_cosp, cosy_cosp))
    return 0.0


def _scale_for_point(point: dict[str, Any]) -> float:
    raw = point.get("scale", 1.0)
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, (list, tuple)) and raw:
        values = [abs(float(v)) for v in raw[:3]]
        return sum(values) / len(values)
    return 1.0


def build_spec_from_points(
    points: list[dict[str, Any]],
    *,
    biome: str,
    camera_position: list[float] | None = None,
) -> dict[str, Any]:
    """Convert raw scatter points to vegetation_system placement spec shape."""
    placements: list[dict[str, Any]] = []
    species_density: dict[str, int] = {}
    lod_distribution: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
    for point in points:
        mesh_name = _mesh_name_for_point(point)
        lod_level = max(0, min(3, int(point.get("lod_level", point.get("lod_hint", 0)))))
        placement = {
            "position": _position_for_point(point),
            "rotation": _rotation_deg_for_point(point),
            "scale": _scale_for_point(point),
            "mesh_name": mesh_name,
            "type": str(point.get("type", mesh_name.split("_", 1)[0])),
            "style": str(point.get("style", mesh_name.split("_", 1)[-1])),
            "lod_level": lod_level,
            "lod_hint": int(point.get("lod_hint", lod_level)),
            "biome": str(point.get("biome", biome)),
            "category": point.get("category"),
            "moisture": float(point.get("moisture", 0.0)),
            "tint_rgb": list(point.get("tint_rgb", [1.0, 1.0, 1.0])),
            "color_variation_seed": point.get("color_variation_seed", point.get("seed")),
        }
        placements.append(placement)
        species_density[mesh_name] = species_density.get(mesh_name, 0) + 1
        lod_distribution[lod_level] = lod_distribution.get(lod_level, 0) + 1
    spec: dict[str, Any] = {
        "placements": placements,
        "biome": biome,
        "instance_count": len(placements),
        "species_density": species_density,
        "lod_distribution": lod_distribution,
        "lod_distances": [15.0, 35.0, 60.0],
    }
    if camera_position is not None:
        spec["camera_position"] = camera_position
    return spec


def _parse_float_list(raw: str, *, expected: int, label: str) -> list[float]:
    values = [float(part.strip()) for part in raw.split(",") if part.strip()]
    if len(values) != expected:
        raise argparse.ArgumentTypeError(f"{label} must contain {expected} comma-separated floats")
    return values


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export scatter points to foliage_placement_manifest.json."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="ScatterPointTable JSON path.",
    )
    parser.add_argument(
        "--mesh-library",
        required=True,
        help="Mesh library JSON with species keys and Unity asset paths.",
    )
    parser.add_argument(
        "--output",
        default="output/unity/foliage_placement_manifest.json",
        help="Output manifest path.",
    )
    parser.add_argument("--biome", default="mixed", help="Biome label embedded in manifest.")
    parser.add_argument("--season", default=None, help="Optional season label.")
    parser.add_argument(
        "--lod-distances",
        type=lambda s: _parse_float_list(s, expected=4, label="--lod-distances"),
        default=[15.0, 35.0, 60.0, 200.0],
        help="LOD distance bands in metres: lod0,lod1,lod2,lod3.",
    )
    parser.add_argument(
        "--camera-position",
        type=lambda s: _parse_float_list(s, expected=3, label="--camera-position"),
        default=None,
        help="Optional reference camera position: x,y,z.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    mesh_library_path = Path(args.mesh_library)
    output_path = Path(args.output)
    if not input_path.is_file():
        print(f"ERROR: scatter input not found: {input_path}", file=sys.stderr)
        return 1
    if not mesh_library_path.is_file():
        print(f"ERROR: mesh library not found: {mesh_library_path}", file=sys.stderr)
        return 1

    points = load_scatter_points(input_path)
    mesh_library = load_mesh_library(mesh_library_path)
    spec = build_spec_from_points(
        points,
        biome=str(args.biome),
        camera_position=args.camera_position,
    )
    manifest = build_foliage_placement_manifest(
        spec=spec,
        mesh_library=mesh_library,
        stack=None,
        biome_name=str(args.biome),
        season=args.season,
        lod_distances_m=list(args.lod_distances),
    )
    write_foliage_placement_manifest(manifest, output_path)
    print(
        f"Wrote {manifest['instance_count']} foliage instances "
        f"across {len(manifest['mesh_library'])} meshes: {output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

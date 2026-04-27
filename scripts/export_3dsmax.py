"""export_3dsmax.py — VeilBreakers terrain → 3ds Max / Forest Pack Pro pipeline.

Reads the terrain pipeline's ScatterPointTable JSON (output/aaa_node_v4/scatter_points.json
or any compatible file) and writes:
  1. A Forest Pack-compatible InstanceInfo CSV that can be ingested via MaxScript
     using the $.trees.create / $.trees.setPosition / $.trees.setRotation API.
  2. A species manifest JSON mapping species_id strings to 3ds Max mesh indices.

Forest Pack Pro "Custom Edit" mode is the recommended target: load the CSV via the
companion MaxScript (docs/3DSMAX_PIPELINE.md) which calls $.trees.create() per row.

Coordinate conventions:
  - Terrain pipeline: Y-up Blender world space, metres.
  - 3ds Max default:  Z-up right-hand, centimetres (1 m = 100 cm).
  This script applies *100 scaling unless --units m is passed.
  Axis remap: Blender (X, Y, Z) → 3ds Max (X, -Y, Z) i.e. negate Y to flip
  from Blender's Y-forward to Max's Y-right convention.

Usage:
  python scripts/export_3dsmax.py [options]

Options:
  --input PATH        ScatterPointTable JSON (default: output/aaa_node_v4/scatter_points.json)
  --output PATH       Output CSV path (default: output/3dsmax/forest_pack_instances.csv)
  --units cm|m        Unit system for output positions (default: cm)
  --species-map PATH  JSON mapping species_id → mesh_index (optional)
  --grid-fallback     If input JSON is missing, generate a regular-grid placeholder
  --grid-spacing M    Spacing in metres for the grid fallback (default: 10.0)
  --seed INT          RNG seed for grid fallback (default: 42)

No bpy dependency — runs with plain Python 3.10+.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Quaternion → Euler (ZYX extrinsic / XYZ intrinsic) conversion
# Returns degrees (RX, RY, RZ) in 3ds Max convention.
# ---------------------------------------------------------------------------

def quat_to_euler_deg(qx: float, qy: float, qz: float, qw: float) -> tuple[float, float, float]:
    """Convert a unit quaternion (x,y,z,w) to Euler angles in degrees.

    Uses ZYX extrinsic decomposition (= XYZ intrinsic), which matches 3ds Max
    Euler XYZ rotation order.  Input quaternion is assumed to be in Blender
    Z-up world space; axis remapping (negate Y) is applied BEFORE decomposition
    so the returned angles are already in 3ds Max space.
    """
    # Remap Blender → 3ds Max: negate Y component of quaternion.
    # Blender: X-right, Y-forward, Z-up
    # 3ds Max: X-right, Y-right (i.e. Blender -Y), Z-up
    # For a pure-Z yaw rotation this just negates the rotation direction, which
    # is correct because the Y axis flips.
    qy = -qy

    # Normalise
    length = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if length < 1e-12:
        return 0.0, 0.0, 0.0
    qx, qy, qz, qw = qx / length, qy / length, qz / length, qw / length

    # ZYX extrinsic (XYZ intrinsic) decomposition
    sinr_cosp = 2.0 * (qw * qx + qy * qz)
    cosr_cosp = 1.0 - 2.0 * (qx * qx + qy * qy)
    rx = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (qw * qy - qz * qx)
    sinp = max(-1.0, min(1.0, sinp))
    ry = math.asin(sinp)

    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    rz = math.atan2(siny_cosp, cosy_cosp)

    return math.degrees(rx), math.degrees(ry), math.degrees(rz)


# ---------------------------------------------------------------------------
# Normal → RX/RY tilt (align Z-axis of instance to surface normal)
# ---------------------------------------------------------------------------

def normal_to_tilt_deg(nx: float, ny: float, nz: float) -> tuple[float, float]:
    """Return (rx_deg, ry_deg) that tilts the instance Z-axis to match the surface normal.

    Uses a simple arc-sin/atan2 decomposition — sufficient for vegetation that
    sits on gentle to moderate slopes.  For near-vertical normals (cliffs) the
    result will have high RX which is intentional (rock/cliff props lean into
    the wall).
    """
    nx, ny, nz = float(nx), float(ny), float(nz)
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-9:
        return 0.0, 0.0
    nx, ny, nz = nx / length, ny / length, nz / length

    # Tilt around X by the angle between the up-axis and the normal projected
    # in the YZ plane.
    rx = math.degrees(math.atan2(-ny, nz))  # negate Y (axis remap)
    ry = math.degrees(math.asin(max(-1.0, min(1.0, nx))))
    return rx, ry


# ---------------------------------------------------------------------------
# Species map helpers
# ---------------------------------------------------------------------------

@dataclass
class SpeciesEntry:
    species_id: str
    mesh_index: int
    label: str = ""
    lod_count: int = 1
    notes: str = ""


def build_default_species_map(species_ids: list[str]) -> dict[str, SpeciesEntry]:
    """Assign sequential mesh indices to all distinct species encountered."""
    seen: dict[str, SpeciesEntry] = {}
    idx = 0
    for sid in species_ids:
        if sid not in seen:
            seen[sid] = SpeciesEntry(species_id=sid, mesh_index=idx, label=sid)
            idx += 1
    return seen


def load_species_map(path: str) -> dict[str, SpeciesEntry]:
    """Load a species-map JSON:  { "oak_tree": {"mesh_index": 0, "label": "Oak"}, ... }"""
    with open(path, "r", encoding="utf-8") as fh:
        raw: dict[str, Any] = json.load(fh)
    result: dict[str, SpeciesEntry] = {}
    for species_id, val in raw.items():
        if isinstance(val, int):
            result[species_id] = SpeciesEntry(species_id=species_id, mesh_index=val)
        elif isinstance(val, dict):
            result[species_id] = SpeciesEntry(
                species_id=species_id,
                mesh_index=int(val.get("mesh_index", 0)),
                label=str(val.get("label", species_id)),
                lod_count=int(val.get("lod_count", 1)),
                notes=str(val.get("notes", "")),
            )
        else:
            raise ValueError(f"Invalid species map entry for '{species_id}': {val!r}")
    return result


# ---------------------------------------------------------------------------
# Point loading
# ---------------------------------------------------------------------------

def load_scatter_points(path: str) -> list[dict[str, Any]]:
    """Load a ScatterPointTable JSON and return the raw point list."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "points" in data:
            return list(data["points"])
        # Bare object with positional keys — wrap in list
        return [data]
    raise ValueError(f"Unrecognised scatter points JSON shape in {path!r}")


def generate_grid_fallback(
    *,
    tile_size_m: float = 1024.0,
    spacing_m: float = 10.0,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Generate a simple regular-grid placeholder scatter point set.

    Produces a jittered grid across the full terrain tile with 5 placeholder
    species evenly distributed.  Useful for testing the 3ds Max workflow before
    the real scatter pipeline has run.
    """
    rng = random.Random(seed)
    species = ["tree_oak", "tree_pine", "shrub_briar", "rock_small", "fern_cluster"]
    half = tile_size_m * 0.5
    cols = int(tile_size_m / spacing_m)
    rows = int(tile_size_m / spacing_m)
    points: list[dict[str, Any]] = []
    jitter = spacing_m * 0.4
    for row in range(rows):
        for col in range(cols):
            cx = -half + (col + 0.5) * spacing_m
            cy = -half + (row + 0.5) * spacing_m
            x = cx + rng.uniform(-jitter, jitter)
            y = cy + rng.uniform(-jitter, jitter)
            z = rng.uniform(0.0, 5.0)  # placeholder — real values come from heightmap
            yaw_rad = rng.uniform(0.0, math.tau)
            scale = rng.uniform(0.85, 1.15)
            sp = species[(row * cols + col) % len(species)]
            # Construct a Z-axis quaternion from yaw
            hw = math.cos(yaw_rad * 0.5)
            hz = math.sin(yaw_rad * 0.5)
            points.append({
                "position": [x, y, z],
                "normal": [0.0, 0.0, 1.0],
                "orient": [0.0, 0.0, hz, hw],
                "scale": [scale, scale, scale],
                "species_id": sp,
                "prototype_id": sp,
                "biome_id": "grassland",
                "seed": rng.randint(0, 0xFFFFFF),
                "lod_bucket": "lod0",
                "height_m": z,
                "density": 1.0,
                "slope": 0.0,
            })
    return points


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

# Forest Pack InstanceInfo CSV column order:
#   X, Y, Z          — position in output units (cm by default)
#   RX, RY, RZ       — Euler rotation in degrees (XYZ order, 3ds Max convention)
#   SX, SY, SZ       — scale (unitless multipliers, 1.0 = default size)
#   MeshIndex        — integer index into FP Geometry List (0-based)
#   Seed             — per-instance random seed for FP colour/animation variation
#
# These columns are read by the companion MaxScript; the MaxScript maps them to
# $.trees.create(), $.trees.setPosition(), $.trees.setRotation(), etc.

CSV_COLUMNS = ["X", "Y", "Z", "RX", "RY", "RZ", "SX", "SY", "SZ", "MeshIndex", "Seed"]


def convert_position(
    px: float, py: float, pz: float, *, units_cm: bool
) -> tuple[float, float, float]:
    """Apply Blender→3ds Max axis remap and optional m→cm scaling.

    Blender: X-right, Y-forward, Z-up
    3ds Max: X-right, Y-right (=Blender -Y), Z-up
    """
    scale = 100.0 if units_cm else 1.0
    return px * scale, -py * scale, pz * scale


def write_csv(
    points: list[dict[str, Any]],
    species_map: dict[str, SpeciesEntry],
    output_path: str,
    *,
    units_cm: bool = True,
) -> int:
    """Write the InstanceInfo CSV. Returns number of rows written."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    rows_written = 0
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()

        for pt in points:
            pos_raw = pt.get("position", [0.0, 0.0, 0.0])
            if len(pos_raw) < 3:
                continue
            px, py, pz = convert_position(
                float(pos_raw[0]), float(pos_raw[1]), float(pos_raw[2]),
                units_cm=units_cm,
            )

            # Rotation: prefer full quaternion orient, fall back to yaw-only
            orient = pt.get("orient")
            normal = pt.get("normal", [0.0, 0.0, 1.0])
            if isinstance(orient, (list, tuple)) and len(orient) == 4:
                rx, ry, rz = quat_to_euler_deg(
                    float(orient[0]), float(orient[1]),
                    float(orient[2]), float(orient[3]),
                )
            else:
                # Fall back to surface normal tilt + yaw from metadata
                nx, ny, nz = (
                    float(normal[0] if len(normal) > 0 else 0.0),
                    float(normal[1] if len(normal) > 1 else 0.0),
                    float(normal[2] if len(normal) > 2 else 1.0),
                )
                rx_tilt, ry_tilt = normal_to_tilt_deg(nx, ny, nz)
                meta = pt.get("metadata", {})
                yaw_deg = float(
                    meta.get("rotation_y", 0.0) if isinstance(meta, dict)
                    else pt.get("rotation", 0.0)
                )
                rx, ry, rz = rx_tilt, ry_tilt, yaw_deg

            # Scale
            scale_raw = pt.get("scale", [1.0, 1.0, 1.0])
            if isinstance(scale_raw, (int, float)):
                sx = sy = sz = float(scale_raw)
            elif len(scale_raw) == 3:
                sx, sy, sz = float(scale_raw[0]), float(scale_raw[1]), float(scale_raw[2])
            elif len(scale_raw) == 1:
                sx = sy = sz = float(scale_raw[0])
            else:
                sx = sy = sz = 1.0

            # Species → mesh index
            species_id = str(pt.get("species_id") or pt.get("prototype_id") or "unknown")
            if species_id not in species_map:
                # Auto-assign: find next free index
                used = {e.mesh_index for e in species_map.values()}
                next_idx = max(used, default=-1) + 1
                species_map[species_id] = SpeciesEntry(
                    species_id=species_id, mesh_index=next_idx, label=species_id
                )
            mesh_index = species_map[species_id].mesh_index

            # Seed
            inst_seed = int(pt.get("seed", 0)) & 0xFFFFFF

            writer.writerow({
                "X":         f"{px:.4f}",
                "Y":         f"{py:.4f}",
                "Z":         f"{pz:.4f}",
                "RX":        f"{rx:.4f}",
                "RY":        f"{ry:.4f}",
                "RZ":        f"{rz:.4f}",
                "SX":        f"{sx:.6f}",
                "SY":        f"{sy:.6f}",
                "SZ":        f"{sz:.6f}",
                "MeshIndex": mesh_index,
                "Seed":      inst_seed,
            })
            rows_written += 1

    return rows_written


# ---------------------------------------------------------------------------
# Manifest writer
# ---------------------------------------------------------------------------

def write_manifest(
    species_map: dict[str, SpeciesEntry],
    output_path: str,
    *,
    units: str,
    source_file: str,
    point_count: int,
) -> None:
    """Write a JSON manifest alongside the CSV."""
    manifest = {
        "format": "VeilBreakers_3dsMax_ForestPack_Manifest",
        "version": "1.0",
        "source_file": source_file,
        "output_units": units,
        "axis_convention": "3dsmax_z_up_cm" if units == "cm" else "3dsmax_z_up_m",
        "blender_to_3dsmax_remap": "X=X, Y=-Y, Z=Z",
        "point_count": point_count,
        "species": {
            entry.species_id: {
                "mesh_index": entry.mesh_index,
                "label": entry.label or entry.species_id,
                "lod_count": entry.lod_count,
                "notes": entry.notes,
            }
            for entry in sorted(species_map.values(), key=lambda e: e.mesh_index)
        },
        "forest_pack_setup": {
            "mode": "Custom Edit",
            "ingest_via": "MaxScript (see docs/3DSMAX_PIPELINE.md)",
            "geometry_list_order": "Add meshes in ascending MeshIndex order",
        },
    }
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)


# ---------------------------------------------------------------------------
# MaxScript snippet generator
# ---------------------------------------------------------------------------

MAXSCRIPT_TEMPLATE = """\
-- VeilBreakers Forest Pack InstanceInfo loader
-- Generated by export_3dsmax.py
-- Drop this file into the 3ds Max Script Editor and run.
-- Prerequisites:
--   1. A Forest Pack Pro object named "FP_Terrain_Scatter" exists in the scene.
--   2. Geometry objects are in the FP Geometry List in MeshIndex order (0-based).
--   3. Forest Pack is in Custom Edit mode.
--
-- Adjust the path below to match your install location.

local csvPath = @"{csv_path}"
local fp = $FP_Terrain_Scatter

-- Activate Custom Edit mode
fp.mode = 1  -- 1 = Custom Edit

-- Parse CSV and create instances
local f = openFile csvPath
if f == undefined do (
    messageBox ("Cannot open: " + csvPath)
    return undefined
)

-- Skip header
local headerLine = readLine f

local count = 0
while not eof f do (
    local line = readLine f
    if line == "" then continue

    -- Parse comma-separated fields:
    -- X,Y,Z,RX,RY,RZ,SX,SY,SZ,MeshIndex,Seed
    local fields = filterString line ","
    if fields.count < 11 then continue

    local px  = fields[1]  as float
    local py  = fields[2]  as float
    local pz  = fields[3]  as float
    local rx  = fields[4]  as float
    local ry  = fields[5]  as float
    local rz  = fields[6]  as float
    local sx  = fields[7]  as float
    local sy  = fields[8]  as float
    local sz  = fields[9]  as float
    local mid = fields[10] as integer
    local sd  = fields[11] as integer

    -- Create item; returns new item index (1-based)
    local idx = fp.trees.create()
    fp.trees.setPosition idx [px, py, pz]
    fp.trees.setRotation idx [rx, ry, rz]
    fp.trees.setScale    idx [sx, sy, sz]
    fp.trees.setGeomID   idx mid
    fp.trees.setSeed     idx sd

    count += 1
)
close f

print ("Loaded " + count as string + " instances into " + fp.name)
"""


def write_maxscript(csv_path: str, output_dir: str) -> str:
    """Write a companion MaxScript to the same output directory."""
    script_path = os.path.join(output_dir, "load_forest_pack_instances.ms")
    # Use a Windows-style path in the MaxScript since 3ds Max runs on Windows
    win_csv_path = csv_path.replace("/", "\\")
    with open(script_path, "w", encoding="utf-8") as fh:
        fh.write(MAXSCRIPT_TEMPLATE.format(csv_path=win_csv_path))
    return script_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Export VeilBreakers scatter points to Forest Pack-compatible CSV."
    )
    p.add_argument(
        "--input",
        default="output/aaa_node_v4/scatter_points.json",
        help="Path to ScatterPointTable JSON (default: output/aaa_node_v4/scatter_points.json)",
    )
    p.add_argument(
        "--output",
        default="output/3dsmax/forest_pack_instances.csv",
        help="Output CSV path (default: output/3dsmax/forest_pack_instances.csv)",
    )
    p.add_argument(
        "--units",
        choices=["cm", "m"],
        default="cm",
        help="Output unit system: 'cm' for 3ds Max default, 'm' to keep metres (default: cm)",
    )
    p.add_argument(
        "--species-map",
        metavar="PATH",
        help="JSON file mapping species_id → mesh_index (optional; auto-assigned if omitted)",
    )
    p.add_argument(
        "--grid-fallback",
        action="store_true",
        help="Generate a regular-grid placeholder scatter if the input JSON is absent",
    )
    p.add_argument(
        "--grid-spacing",
        type=float,
        default=10.0,
        metavar="M",
        help="Grid spacing in metres for --grid-fallback (default: 10.0)",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for grid fallback (default: 42)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    units_cm = args.units == "cm"

    # ---- Resolve project root so relative paths work when script is run from
    #      any CWD (e.g. project root or scripts/ subdir).
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent  # scripts/ is one level below project root

    def resolve(p: str) -> str:
        path = Path(p)
        if path.is_absolute():
            return str(path)
        # Try relative to CWD first, then relative to project root
        if Path(p).exists():
            return str(Path(p).resolve())
        candidate = project_root / p
        return str(candidate)

    input_path = resolve(args.input)
    output_path = resolve(args.output)
    output_dir = str(Path(output_path).parent)

    # ---- Load species map
    species_map: dict[str, SpeciesEntry] = {}
    if args.species_map:
        smap_path = resolve(args.species_map)
        print(f"Loading species map: {smap_path}")
        species_map = load_species_map(smap_path)

    # ---- Load scatter points
    if os.path.exists(input_path):
        print(f"Loading scatter points: {input_path}")
        points = load_scatter_points(input_path)
        source_label = input_path
    elif args.grid_fallback:
        print(
            f"Input not found ({input_path}); generating grid fallback "
            f"(spacing={args.grid_spacing}m, seed={args.seed})"
        )
        points = generate_grid_fallback(
            spacing_m=args.grid_spacing,
            seed=args.seed,
        )
        source_label = f"grid_fallback(spacing={args.grid_spacing}m)"
    else:
        print(
            f"ERROR: Input file not found: {input_path}\n"
            "       Pass --grid-fallback to generate a placeholder grid instead.",
            file=sys.stderr,
        )
        return 1

    print(f"  {len(points)} scatter points loaded.")

    # ---- Auto-build species map from points if not pre-loaded
    if not species_map:
        all_ids = [
            str(pt.get("species_id") or pt.get("prototype_id") or "unknown")
            for pt in points
        ]
        species_map = build_default_species_map(all_ids)
        print(f"  Auto-assigned {len(species_map)} species to mesh indices.")

    # ---- Write CSV
    print(f"Writing CSV: {output_path}  (units={args.units})")
    n = write_csv(points, species_map, output_path, units_cm=units_cm)
    print(f"  {n} rows written.")

    # ---- Write manifest JSON
    manifest_path = output_path.replace(".csv", "_manifest.json")
    write_manifest(
        species_map,
        manifest_path,
        units=args.units,
        source_file=source_label,
        point_count=n,
    )
    print(f"Manifest: {manifest_path}")

    # ---- Write companion MaxScript
    ms_path = write_maxscript(output_path, output_dir)
    print(f"MaxScript: {ms_path}")

    # ---- Summary
    print()
    print("Done.  3ds Max workflow:")
    print(f"  1. Import terrain FBX into 3ds Max.")
    print(f"  2. Create a ForestPack Pro object named 'FP_Terrain_Scatter'.")
    print(f"  3. Add geometry meshes to the FP Geometry List in MeshIndex order:")
    for entry in sorted(species_map.values(), key=lambda e: e.mesh_index):
        print(f"       [{entry.mesh_index}] {entry.label or entry.species_id}")
    print(f"  4. Set Forest Pack to Custom Edit mode.")
    print(f"  5. Run MaxScript: {ms_path}")
    print()
    print("  See docs/3DSMAX_PIPELINE.md for the full integration guide.")

    return 0


if __name__ == "__main__":
    sys.exit(main())


# ---------------------------------------------------------------------------
# Handler registration note
# ---------------------------------------------------------------------------
# Register export_3dsmax in COMMAND_HANDLERS as 'export_3dsmax_forest_pack'
# when scatter agent completes. Example entry:
#
#   "export_3dsmax_forest_pack": {
#       "module": "scripts.export_3dsmax",
#       "entry": "main",
#       "description": "Export scatter points to Forest Pack InstanceInfo CSV for 3ds Max",
#   }

"""Scene v3 visual quality gate.

This gate is intentionally stricter than "did Blender render a file?". It checks
the generated node contract, required scene objects, targeted closeup evidence,
and basic image diagnostics so blank thumbnails or generic hero shots cannot be
used as completion proof.

Run after ``scripts/build_scene_v3.py`` and ``scripts/render_closeups_v3.py``:

    blender --background output/scene_v3/VeilBreakers_Scene_v3.blend \
        --python scripts/scene_v3_visual_quality_gate.py
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

try:
    import bpy  # type: ignore
except Exception:  # pragma: no cover - exercised through Blender in live use
    bpy = None  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[1]
SCENE_DIR = REPO_ROOT / "output" / "scene_v3"
CLOSEUP_DIR = SCENE_DIR / "closeups"
SUMMARY_PATH = SCENE_DIR / "BUILD_SUMMARY.json"
JSON_OUT = SCENE_DIR / "SCENE_V3_VISUAL_QUALITY_GATE.json"
MD_OUT = SCENE_DIR / "SCENE_V3_VISUAL_QUALITY_GATE.md"

MIN_RENDER_WIDTH = 1600
MIN_RENDER_HEIGHT = 900
MIN_RENDER_BYTES = 25_000
MIN_LUMA_STDDEV = 4.0
MIN_COLOR_BUCKETS = 24
MIN_EDGE_DENSITY = 0.015

REQUIRED_CLOSEUPS = {
    "01_tile_overview": "full node scope",
    "02_hero_establishing": "mountain pass, river, water body composition",
    "05_waterfall_closeup": "waterfall quality",
    "06_river_bank_entry": "river depth and bank entry",
    "07_bridge_waterline": "bridge anchoring over river",
    "08_bridge_approach_path": "bridge-to-path transition",
    "10_large_water_panorama": "off-node large water continuation",
    "11_large_water_shoreline": "large water shoreline",
    "12_cliff_face": "cliff and mountain material read",
    "13_mountain_peak_lookdown": "mountain pass macro shape",
    "14_forest_bridge_side": "forest-side scatter near bridge",
}

REQUIRED_OBJECT_GROUPS = {
    "bridge": ("bridge", 1),
    "road_or_path": ("road", 2),
    "river": ("river", 2),
    "lake_or_large_water": ("lake", 1),
    "waterfall": ("waterfall", 3),
    "trees": ("tree", 50),
    "grass": ("grass", 100),
}


def _read_summary() -> dict[str, Any]:
    if not SUMMARY_PATH.exists():
        return {}
    try:
        return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_read_error": repr(exc)}


def _load_image_sample(path: Path, sample_size: tuple[int, int] = (96, 54)) -> dict[str, Any] | None:
    try:
        from PIL import Image  # type: ignore
    except Exception:
        Image = None  # type: ignore
    if Image is not None:
        try:
            with Image.open(path) as img:
                rgb = img.convert("RGB")
                sample = rgb.resize(sample_size)
                return {
                    "decoder": "pillow",
                    "width": rgb.size[0],
                    "height": rgb.size[1],
                    "pixels": list(sample.getdata()),
                }
        except Exception:
            pass

    if bpy is None:
        return None
    try:
        image = bpy.data.images.load(str(path), check_existing=False)
    except Exception:
        return None
    try:
        width, height = int(image.size[0]), int(image.size[1])
        if width <= 0 or height <= 0:
            return None
        sample_w, sample_h = sample_size
        image.scale(sample_w, sample_h)
        pixels = list(image.pixels)
        sample_pixels: list[tuple[int, int, int]] = []
        for base in range(0, len(pixels), 4):
            sample_pixels.append((
                int(max(0.0, min(1.0, float(pixels[base]))) * 255.0),
                int(max(0.0, min(1.0, float(pixels[base + 1]))) * 255.0),
                int(max(0.0, min(1.0, float(pixels[base + 2]))) * 255.0),
            ))
        return {
            "decoder": "blender",
            "width": width,
            "height": height,
            "pixels": sample_pixels,
        }
    finally:
        bpy.data.images.remove(image)


def analyze_image_file(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "byte_size": path.stat().st_size if path.exists() else 0,
        "issues": [],
    }
    if not path.exists():
        report["issues"].append("missing_render")
        return report
    if report["byte_size"] < MIN_RENDER_BYTES:
        report["issues"].append("render_file_too_small")

    image_data = _load_image_sample(path)
    if image_data is None:
        report["issues"].append("image_decode_failed")
        return report

    width, height = image_data["width"], image_data["height"]
    report["width"] = width
    report["height"] = height
    report["decoder"] = image_data["decoder"]
    if width < MIN_RENDER_WIDTH or height < MIN_RENDER_HEIGHT:
        report["issues"].append("render_resolution_too_low")

    # Downsampled pixels keep diagnostics cheap and deterministic in both Pillow
    # and Blender's embedded Python.
    pixels = image_data["pixels"]
    lumas = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in pixels]
    mean_luma = sum(lumas) / max(len(lumas), 1)
    std_luma = statistics.pstdev(lumas) if len(lumas) > 1 else 0.0
    report["mean_luma"] = mean_luma
    report["std_luma"] = std_luma
    if std_luma < MIN_LUMA_STDDEV:
        report["issues"].append("render_flat_or_blank")
    if mean_luma < 4.0:
        report["issues"].append("render_too_dark")
    if mean_luma > 250.0:
        report["issues"].append("render_too_bright")

    color_buckets = {
        (r // 16, g // 16, b // 16)
        for r, g, b in pixels
    }
    report["color_bucket_count"] = len(color_buckets)
    if len(color_buckets) < MIN_COLOR_BUCKETS:
        report["issues"].append("low_color_diversity")

    w, h = 96, 54
    edge_hits = 0
    edge_total = 0
    for y in range(h - 1):
        row = y * w
        next_row = (y + 1) * w
        for x in range(w - 1):
            i = row + x
            dx = abs(lumas[i] - lumas[row + x + 1])
            dy = abs(lumas[i] - lumas[next_row + x])
            if dx + dy > 18.0:
                edge_hits += 1
            edge_total += 1
    edge_density = edge_hits / max(edge_total, 1)
    report["edge_density"] = edge_density
    if edge_density < MIN_EDGE_DENSITY:
        report["issues"].append("low_spatial_detail")

    return report


def _object_counts() -> dict[str, int]:
    if bpy is None:
        return {}
    names = [obj.name.lower() for obj in bpy.data.objects]
    return {
        key: sum(1 for name in names if token in name)
        for key, (token, _minimum) in REQUIRED_OBJECT_GROUPS.items()
    }


def _bridge_bounds() -> dict[str, Any]:
    if bpy is None:
        return {"present": False}
    bridge = bpy.data.objects.get("VB_River_RopeBridge_Main")
    if bridge is None:
        return {"present": False}
    verts = [bridge.matrix_world @ v.co for v in bridge.data.vertices]
    if not verts:
        return {"present": True, "vertex_count": 0}
    xs = [float(v.x) for v in verts]
    ys = [float(v.y) for v in verts]
    zs = [float(v.z) for v in verts]
    span_xy = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    return {
        "present": True,
        "vertex_count": len(verts),
        "span_xy": span_xy,
        "min_z": min(zs),
        "max_z": max(zs),
        "bbox": [[min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)]],
    }


def evaluate_gate() -> tuple[dict[str, Any], int]:
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    summary = _read_summary()

    if not summary:
        blockers.append({"code": "missing_build_summary", "message": str(SUMMARY_PATH)})
    elif summary.get("_read_error"):
        blockers.append({"code": "build_summary_unreadable", "message": summary["_read_error"]})
    elif int(summary.get("failures", 0)) != 0:
        blockers.append({
            "code": "build_summary_failures",
            "message": f"BUILD_SUMMARY failures={summary.get('failures')} stages={summary.get('failure_stages')}",
        })

    bridge_paths = summary.get("bridge_paths") if isinstance(summary, dict) else None
    if not isinstance(bridge_paths, dict) or not bridge_paths:
        blockers.append({"code": "missing_bridge_path_contract", "message": "bridge_paths is empty"})
    else:
        if bridge_paths.get("path_network_contract_issues"):
            blockers.append({
                "code": "path_contract_issues",
                "message": repr(bridge_paths.get("path_network_contract_issues")),
            })
        used = set(bridge_paths.get("callables_used", []))
        required_callables = {
            "COMMAND_HANDLERS.env_generate_road",
            "generate_terrain_bridge_mesh",
            "validate_path_network_contract",
        }
        missing = sorted(required_callables - used)
        if missing:
            blockers.append({"code": "bridge_path_missing_callable_evidence", "message": ", ".join(missing)})

    node_contracts = summary.get("node_contracts") if isinstance(summary, dict) else None
    if not isinstance(node_contracts, dict) or node_contracts.get("issues"):
        blockers.append({"code": "node_contract_issues", "message": repr(node_contracts)})
    else:
        water_contract = node_contracts.get("off_node_water_contract", {})
        if water_contract.get("type") != "off_node_large_water_body" or water_contract.get("edge") != "south":
            blockers.append({"code": "off_node_water_contract_invalid", "message": repr(water_contract)})
        if node_contracts.get("scatter_point_contract_issues"):
            blockers.append({
                "code": "scatter_point_contract_issues",
                "message": repr(node_contracts.get("scatter_point_contract_issues")),
            })

    if summary.get("model_asset_props_placed", 0) <= 0:
        warnings.append({"code": "model_asset_fallback_active", "message": "No external model assets placed; procedural fallback evidence required."})
    if summary.get("trees_placed", 0) < 100:
        warnings.append({"code": "low_tree_count", "message": f"trees_placed={summary.get('trees_placed')}"})
    if summary.get("procedural_grass_clumps_placed", 0) < 1000:
        warnings.append({"code": "low_grass_count", "message": f"procedural_grass_clumps_placed={summary.get('procedural_grass_clumps_placed')}"})

    counts = _object_counts()
    for key, (_token, minimum) in REQUIRED_OBJECT_GROUPS.items():
        actual = counts.get(key, 0)
        if actual < minimum:
            blockers.append({"code": f"missing_scene_objects_{key}", "message": f"{actual} < {minimum}"})

    bridge_bounds = _bridge_bounds()
    if not bridge_bounds.get("present"):
        blockers.append({"code": "bridge_object_missing", "message": "VB_River_RopeBridge_Main not present"})
    elif bridge_bounds.get("vertex_count", 0) <= 0 or bridge_bounds.get("span_xy", 0.0) < 20.0:
        blockers.append({"code": "bridge_geometry_invalid", "message": repr(bridge_bounds)})

    image_reports: dict[str, Any] = {}
    for label, requirement in REQUIRED_CLOSEUPS.items():
        report = analyze_image_file(CLOSEUP_DIR / f"{label}.png")
        report["requirement"] = requirement
        image_reports[label] = report
        for issue in report.get("issues", []):
            blockers.append({"code": f"{label}_{issue}", "message": requirement})

    payload = {
        "status": "pass" if not blockers else "fail",
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "blockers": blockers,
        "warnings": warnings,
        "summary_path": str(SUMMARY_PATH),
        "closeup_dir": str(CLOSEUP_DIR),
        "object_counts": counts,
        "bridge_bounds": bridge_bounds,
        "required_closeups": REQUIRED_CLOSEUPS,
        "image_reports": image_reports,
        "fallback_policy": {
            "procedural_tree_fallback": "allowed only when counted, rendered, and called out as fallback evidence",
            "external_asset_missing": "warning until asset manifest is available; blocker if density or visual evidence fails",
            "blank_or_low_resolution_render": "hard blocker",
            "build_summary_failure": "hard blocker",
        },
    }
    return payload, 0 if not blockers else 1


def write_outputs(payload: dict[str, Any]) -> None:
    SCENE_DIR.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Scene v3 Visual Quality Gate",
        "",
        f"- Status: {payload['status']}",
        f"- Blockers: {payload['blocker_count']}",
        f"- Warnings: {payload['warning_count']}",
        f"- Closeup directory: {payload['closeup_dir']}",
        "",
        "## Blockers",
    ]
    if payload["blockers"]:
        lines.extend(f"- {item['code']}: {item['message']}" for item in payload["blockers"])
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Warnings")
    if payload["warnings"]:
        lines.extend(f"- {item['code']}: {item['message']}" for item in payload["warnings"])
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Object Counts")
    for key, count in payload["object_counts"].items():
        lines.append(f"- {key}: {count}")
    MD_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    payload, code = evaluate_gate()
    write_outputs(payload)
    print(f"wrote {JSON_OUT}")
    print(f"wrote {MD_OUT}")
    print(f"scene_v3_visual_quality_status={payload['status']}")
    print(f"blocker_count={payload['blocker_count']}")
    if payload["blockers"]:
        print("blockers=" + ",".join(item["code"] for item in payload["blockers"]))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

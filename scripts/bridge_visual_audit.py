"""Generate and inspect procedural bridge variants from multiple camera angles.

This is a headless visual/geometry audit. It does not claim Blender viewport
coverage unless Blender is actually present; instead it produces SVG previews,
OBJ meshes, and a JSON report that catches stretched primitives, bad endpoint
alignment, invalid faces, and missing material/profile contracts.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUTPUT_DIR = REPO_ROOT / "output" / "bridge_visual_audit"
JSON_OUT = OUTPUT_DIR / "BRIDGE_VISUAL_AUDIT.json"
MD_OUT = OUTPUT_DIR / "BRIDGE_VISUAL_AUDIT.md"


VARIANTS: tuple[dict[str, Any], ...] = (
    {
        "name": "wood_short_path",
        "style": "wood",
        "start_pos": (0.0, 0.0, 0.0),
        "end_pos": (8.0, 0.0, 0.0),
        "width": 2.0,
        "water_level": -0.6,
        "waterbed_z": -1.6,
    },
    {
        "name": "wood_long_stretched",
        "style": "wood",
        "start_pos": (0.0, 0.0, 0.0),
        "end_pos": (22.0, 0.0, 0.0),
        "width": 2.4,
        "water_level": -0.6,
        "waterbed_z": -1.8,
    },
    {
        "name": "stone_short_road",
        "style": "stone",
        "start_pos": (0.0, 0.0, 0.0),
        "end_pos": (14.0, 0.0, 0.0),
        "width": 4.0,
        "water_level": -1.0,
        "waterbed_z": -2.8,
    },
    {
        "name": "stone_long_viaduct",
        "style": "stone",
        "start_pos": (0.0, 0.0, 0.0),
        "end_pos": (42.0, 0.0, 0.0),
        "width": 5.5,
        "water_level": -1.2,
        "waterbed_z": -3.2,
    },
    {
        "name": "rope_straight_sway_bridge",
        "style": "rope",
        "control_points": [
            (0.0, 0.0, 3.0),
            (8.0, 0.0, 2.2),
            (16.0, 0.0, 3.4),
        ],
        "width": 1.7,
        "water_level": 0.0,
        "waterbed_z": -1.6,
    },
    {
        "name": "drawbridge_wide",
        "style": "drawbridge",
        "start_pos": (0.0, 0.0, 0.0),
        "end_pos": (12.0, -4.0, 0.5),
        "width": 4.2,
    },
    {
        "name": "wood_curved_shallow_water",
        "style": "wood",
        "control_points": [
            (0.0, 0.0, 0.0),
            (6.0, 3.0, 0.4),
            (12.0, 0.0, 0.8),
        ],
        "width": 2.2,
        "water_level": -0.6,
        "waterbed_z": -1.8,
    },
    {
        "name": "stone_curved_deep_water_high_to_low",
        "style": "stone",
        "control_points": [
            (0.0, 0.0, 5.0),
            (14.0, -4.0, 3.0),
            (28.0, 1.5, 1.0),
        ],
        "width": 5.0,
        "water_level": -2.0,
        "waterbed_z": -4.5,
    },
)


def _finite_vec3(value: Any) -> bool:
    return (
        isinstance(value, (tuple, list))
        and len(value) >= 3
        and all(math.isfinite(float(value[i])) for i in range(3))
    )


def _dist2(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))


def _bbox(vertices: list[tuple[float, float, float]]) -> dict[str, list[float]]:
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]
    return {
        "min": [min(xs), min(ys), min(zs)],
        "max": [max(xs), max(ys), max(zs)],
        "size": [max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)],
    }


def _validate_mesh(
    spec: dict[str, Any],
    *,
    start_pos: tuple[float, float, float],
    end_pos: tuple[float, float, float],
    expected_width: float,
    water_level: float | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    vertices = [tuple(float(c) for c in v[:3]) for v in spec.get("vertices", [])]
    faces = spec.get("faces", [])
    if len(vertices) < 8:
        issues.append({"code": "too_few_vertices", "message": f"{len(vertices)} vertices"})
    if len(faces) < 4:
        issues.append({"code": "too_few_faces", "message": f"{len(faces)} faces"})
    for idx, vertex in enumerate(vertices):
        if not _finite_vec3(vertex):
            issues.append({"code": "non_finite_vertex", "index": idx})
            break
    for face_idx, face in enumerate(faces):
        if len(face) < 3:
            issues.append({"code": "degenerate_face", "face_index": face_idx})
            continue
        for vi in face:
            if int(vi) < 0 or int(vi) >= len(vertices):
                issues.append({"code": "face_index_out_of_range", "face_index": face_idx})
                break

    if vertices:
        box = _bbox(vertices)
        expected_span = _dist2(start_pos, end_pos)
        actual_span = max(box["size"][0], box["size"][1])
        if actual_span < expected_span * 0.82:
            issues.append({
                "code": "span_too_short",
                "message": f"actual {actual_span:.2f} expected {expected_span:.2f}",
            })
        horizontal_width = min(
            max(box["size"][0], box["size"][1]),
            max(expected_width, min(box["size"][0], box["size"][1])),
        )
        if horizontal_width < expected_width * 0.55:
            issues.append({
                "code": "width_collapsed",
                "message": f"actual {horizontal_width:.2f} expected {expected_width:.2f}",
            })

    profile = spec.get("metadata", {}).get("bridge_profile", {})
    required_profile_fields = {
        "resolved_style",
        "material_family",
        "module_count",
        "support_count",
        "approach_transition_m",
        "material_slots",
    }
    missing = sorted(field for field in required_profile_fields if field not in profile)
    if missing:
        issues.append({"code": "missing_bridge_profile_fields", "fields": missing})
    if "approach_transition" not in profile.get("material_slots", []):
        issues.append({"code": "missing_approach_transition_material"})
    if int(profile.get("module_count", 0)) < 1:
        issues.append({"code": "invalid_module_count"})
    if spec.get("metadata", {}).get("waterbed_z") is not None and vertices:
        if profile.get("swept_centerline") is not True:
            issues.append({"code": "waterbed_bridge_not_swept"})
        if profile.get("resolved_style") == "rope":
            if profile.get("anchored_to_banks") is not True:
                issues.append({"code": "rope_bridge_missing_bank_anchors"})
            if profile.get("supports_reach_foundation") is True:
                issues.append({"code": "rope_bridge_wrongly_claims_waterbed_supports"})
        elif profile.get("supports_reach_foundation") is not True:
            issues.append({"code": "waterbed_bridge_missing_foundation_supports"})
        expected_foundation = spec.get("metadata", {}).get("waterbed_z")
        actual_foundation = profile.get("support_foundation_z")
        if actual_foundation is None or abs(float(actual_foundation) - float(expected_foundation)) > 1.0e-4:
            issues.append({
                "code": "waterbed_foundation_z_mismatch",
                "expected": expected_foundation,
                "actual": actual_foundation,
            })
    if profile.get("resolved_style") == "rope":
        if profile.get("rope_planform") != "straight_bank_to_bank":
            issues.append({"code": "rope_bridge_not_straight_bank_to_bank"})
        centerline = profile.get("centerline_points", [])
        if len(centerline) >= 2:
            y_values = [float(point[1]) for point in centerline]
            if max(y_values) - min(y_values) > 0.25:
                issues.append({"code": "rope_bridge_has_unsupported_plan_curve"})
    if water_level is not None and vertices:
        bottom_z = min(vertex[2] for vertex in vertices)
        top_z = max(vertex[2] for vertex in vertices)
        if top_z <= float(water_level):
            issues.append({
                "code": "bridge_below_waterline",
                "message": f"top {top_z:.2f} water {float(water_level):.2f}",
            })
        if profile.get("resolved_style") in {"timber_beam", "stone_arch", "stone_viaduct"}:
            if float(profile.get("approach_transition_m", 0.0)) <= 0.0:
                issues.append({"code": "missing_bank_transition"})
    return issues


def _write_obj(path: Path, spec: dict[str, Any]) -> None:
    lines: list[str] = []
    for v in spec.get("vertices", []):
        lines.append(f"v {float(v[0]):.6f} {float(v[1]):.6f} {float(v[2]):.6f}")
    for face in spec.get("faces", []):
        indices = " ".join(str(int(i) + 1) for i in face)
        lines.append(f"f {indices}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _project(vertex: tuple[float, float, float], view: str) -> tuple[float, float, float]:
    x, y, z = vertex
    if view == "top":
        return x, y, z
    if view == "side":
        return x, z, y
    if view == "approach":
        return y, z, x
    # isometric
    u = (x - y) * 0.82
    v = z + (x + y) * 0.28
    d = x + y - z
    return u, v, d


def _svg_for_view(spec: dict[str, Any], view: str) -> str:
    vertices = [tuple(float(c) for c in v[:3]) for v in spec.get("vertices", [])]
    faces = [tuple(int(i) for i in face) for face in spec.get("faces", []) if len(face) >= 3]
    projected = [_project(vertex, view) for vertex in vertices]
    xs = [p[0] for p in projected] or [0.0]
    ys = [p[1] for p in projected] or [0.0]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    scale = min(920.0 / max(max_x - min_x, 1e-6), 520.0 / max(max_y - min_y, 1e-6))

    def _screen(point: tuple[float, float, float]) -> tuple[float, float]:
        sx = 40.0 + (point[0] - min_x) * scale
        sy = 560.0 - (40.0 + (point[1] - min_y) * scale)
        return sx, sy

    face_depths = []
    for face in faces:
        depth = sum(projected[i][2] for i in face) / len(face)
        face_depths.append((depth, face))
    face_depths.sort()

    polygons: list[str] = []
    palette = {
        "wood": "#8a5a32",
        "stone": "#8f9495",
        "rope": "#a87945",
        "drawbridge": "#6f4a2b",
    }
    family = spec.get("metadata", {}).get("bridge_profile", {}).get("material_family", "stone")
    fill = palette.get(str(family), "#8f9495")
    for _, face in face_depths:
        pts = []
        for vi in face:
            sx, sy = _screen(projected[vi])
            pts.append(f"{sx:.1f},{sy:.1f}")
        polygons.append(
            f'<polygon points="{" ".join(pts)}" fill="{fill}" '
            'fill-opacity="0.62" stroke="#1f2528" stroke-width="0.8" />'
        )
    title = spec.get("metadata", {}).get("name", "bridge")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="600" '
        'viewBox="0 0 1000 600">'
        '<rect width="1000" height="600" fill="#f3f0e8" />'
        f'<text x="28" y="34" font-family="Arial" font-size="20" fill="#202020">'
        f'{title} - {view}</text>'
        + "".join(polygons)
        + "</svg>\n"
    )


def _write_previews(out_dir: Path, variant_name: str, spec: dict[str, Any]) -> dict[str, str]:
    paths: dict[str, str] = {}
    for view in ("top", "side", "approach", "isometric"):
        path = out_dir / f"{variant_name}_{view}.svg"
        path.write_text(_svg_for_view(spec, view), encoding="utf-8")
        paths[view] = str(path)
    return paths


def run_audit(output_dir: Path = OUTPUT_DIR) -> tuple[dict[str, Any], int]:
    from veilbreakers_terrain.handlers._bridge_mesh import generate_terrain_bridge_mesh

    output_dir.mkdir(parents=True, exist_ok=True)
    variants_dir = output_dir / "variants"
    variants_dir.mkdir(parents=True, exist_ok=True)

    blender_path = shutil.which("blender")
    results: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []

    for variant in VARIANTS:
        control_points = variant.get("control_points")
        spec = generate_terrain_bridge_mesh(
            start_pos=variant.get("start_pos", (0.0, 0.0, 0.0)),
            end_pos=variant.get("end_pos", (10.0, 0.0, 0.0)),
            width=float(variant["width"]),
            style=str(variant["style"]),
            seed=17,
            control_points=control_points,
            water_level=variant.get("water_level"),
            waterbed_z=variant.get("waterbed_z"),
        )
        audit_start = tuple(control_points[0]) if control_points else variant["start_pos"]
        audit_end = tuple(control_points[-1]) if control_points else variant["end_pos"]
        issues = _validate_mesh(
            spec,
            start_pos=audit_start,
            end_pos=audit_end,
            expected_width=float(variant["width"]),
            water_level=variant.get("water_level"),
        )
        obj_path = variants_dir / f"{variant['name']}.obj"
        _write_obj(obj_path, spec)
        previews = _write_previews(variants_dir, str(variant["name"]), spec)
        result = {
            "variant": variant,
            "obj_path": str(obj_path),
            "preview_paths": previews,
            "vertex_count": len(spec.get("vertices", [])),
            "face_count": len(spec.get("faces", [])),
            "metadata": spec.get("metadata", {}),
            "issues": issues,
        }
        results.append(result)
        blockers.extend({"variant": variant["name"], **issue} for issue in issues)

    payload = {
        "bridge_visual_audit": "2026-04-26",
        "blender_runtime_detected": blender_path is not None,
        "blender_path": blender_path,
        "variant_count": len(results),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "variants": results,
        "note": (
            "SVG/OBJ previews are generated in headless Python. This is not a "
            "substitute for Blender viewport review; when Blender is available, "
            "run these OBJ/spec variants through visual_qa_setup_camera and "
            "visual_qa_capture_screenshot."
        ),
    }
    return payload, 1 if blockers else 0


def write_outputs(payload: dict[str, Any], output_dir: Path = OUTPUT_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / JSON_OUT.name
    md_path = output_dir / MD_OUT.name
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Bridge Visual Audit",
        "",
        f"- Blender runtime detected: {payload['blender_runtime_detected']}",
        f"- Variant count: {payload['variant_count']}",
        f"- Blocker count: {payload['blocker_count']}",
        "",
    ]
    for result in payload["variants"]:
        meta = result["metadata"]
        profile = meta.get("bridge_profile", {})
        lines.extend([
            f"## {result['variant']['name']}",
            "",
            f"- Requested style: {result['variant']['style']}",
            f"- Resolved style: {profile.get('resolved_style')}",
            f"- Material family: {profile.get('material_family')}",
            f"- Modules: {profile.get('module_count')}",
            f"- Supports: {profile.get('support_count')}",
            f"- Arches: {profile.get('arch_count')}",
            f"- OBJ: `{result['obj_path']}`",
            f"- Previews: {', '.join(result['preview_paths'].keys())}",
            f"- Issues: {len(result['issues'])}",
            "",
        ])
    lines.append(str(payload["note"]))
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bridge mesh visual audit")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args(argv)
    payload, code = run_audit(Path(args.output_dir))
    write_outputs(payload, Path(args.output_dir))
    print(f"wrote {Path(args.output_dir) / JSON_OUT.name}")
    print(f"wrote {Path(args.output_dir) / MD_OUT.name}")
    print(f"blocker_count={payload['blocker_count']}")
    print(f"blender_runtime_detected={payload['blender_runtime_detected']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

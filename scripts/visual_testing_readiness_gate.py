"""Verify the terrain stack is wired for visual testing.

This is not an AAA visual-quality verdict. It is the preflight gate that proves
an agent or MCP caller can reach camera setup, viewport shading, screenshot
capture, viewport freshness, and core visual-adjacent terrain paths without
dispatch disconnections.

Hardening rules enforced here:

* **Fail-hard on no Blender runtime.** If ``blender_runtime_detected`` is
  ``False`` the gate exits non-zero unless ``--allow-no-blender`` is passed for
  local/dev preview (which still records ``ready_for_visual_testing=False``).
* **Reject placeholder PNG bytes.** A captured thumbnail smaller than 500 bytes
  is always a fake. Real PNGs with a single IDAT chunk exceed that minimum.
* **Real pixel-level assertion.** A reference thumbnail must exist at
  ``output/visual_readiness/reference/test_live_preview_thumbnail.png`` for a
  release-ready run. The captured thumbnail is compared channel-wise.
  Mean-absolute-diff above ``10/255`` or a shape mismatch fails the gate.
* **Perceptual hash.** A simple 8x8 brightness-grid hash (average hash) is
  recorded in the JSON artifact for change tracking over time.
* **CI enforcement.** CI runs this inside headless Blender; no-Blender runs are
  developer preview only and are not accepted as visual proof.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import sys
import zlib
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
OUTPUT_DIR = REPO_ROOT / "output" / "visual_readiness"
REFERENCE_DIR = OUTPUT_DIR / "reference"
JSON_OUT = OUTPUT_DIR / "VISUAL_TESTING_READINESS.json"
MD_OUT = OUTPUT_DIR / "VISUAL_TESTING_READINESS.md"
THUMBNAIL_NAME = "test_live_preview_thumbnail.png"
THUMBNAIL_PATH = OUTPUT_DIR / THUMBNAIL_NAME
REFERENCE_PATH = REFERENCE_DIR / THUMBNAIL_NAME

# A minimally valid PNG (header + IDAT + IEND) is roughly ~100 bytes.
# Real viewport captures we care about are >> 500 bytes. Anything below that
# threshold is guaranteed to be a placeholder or corrupt file.
PLACEHOLDER_PNG_THRESHOLD_BYTES = 500
PIXEL_DIFF_CHANNEL_THRESHOLD = 10.0  # out of 255


def _is_placeholder_png_bytes(image_bytes: bytes | None) -> bool:
    return image_bytes is None or len(image_bytes) <= PLACEHOLDER_PNG_THRESHOLD_BYTES


def _status_ok(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("status") == "ok"


def _result_status_ok(payload: Any) -> bool:
    return _status_ok(payload) and isinstance(payload.get("result"), dict)


def _load_image_rgb(image_bytes: bytes):
    """Decode PNG bytes into a row-major RGB grid.

    Returns a dict with width/height/pixels or ``None`` when decoding fails.
    Requires Pillow; if Pillow is missing we return ``None`` and callers fall
    back to byte-level heuristics.
    """

    try:
        from PIL import Image  # type: ignore
    except Exception:  # pragma: no cover - pillow is in requirements
        return _load_png_rgb_stdlib(image_bytes)

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = img.convert("RGB")
            width, height = img.size
            # ``tobytes`` returns RGBRGB... which is faster than getdata() and
            # avoids the PIL deprecation warning. We rebuild the 2D grid for
            # the pixel-diff loop below.
            raw = img.tobytes()
            rows = []
            for y in range(height):
                start = y * width * 3
                row = []
                for x in range(width):
                    off = start + x * 3
                    row.append((raw[off], raw[off + 1], raw[off + 2]))
                rows.append(row)
            return {"width": width, "height": height, "pixels": rows}
    except Exception:
        return _load_png_rgb_stdlib(image_bytes)


def _load_png_rgb_stdlib(image_bytes: bytes):
    """Small PNG decoder fallback for Blender Python, where Pillow is absent."""

    if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    try:
        pos = 8
        width = height = 0
        bit_depth = color_type = None
        idat = bytearray()
        while pos + 8 <= len(image_bytes):
            length = struct.unpack(">I", image_bytes[pos:pos + 4])[0]
            tag = image_bytes[pos + 4:pos + 8]
            data_start = pos + 8
            data_end = data_start + length
            if data_end + 4 > len(image_bytes):
                return None
            data = image_bytes[data_start:data_end]
            if tag == b"IHDR":
                width, height, bit_depth, color_type, _, _, _ = struct.unpack(">IIBBBBB", data)
            elif tag == b"IDAT":
                idat.extend(data)
            elif tag == b"IEND":
                break
            pos = data_end + 4
        if width <= 0 or height <= 0 or bit_depth != 8 or color_type not in (2, 6):
            return None
        channels = 3 if color_type == 2 else 4
        stride = width * channels
        raw = zlib.decompress(bytes(idat))
        rows = []
        prev = [0] * stride
        offset = 0
        for _y in range(height):
            filter_type = raw[offset]
            offset += 1
            scan = list(raw[offset:offset + stride])
            offset += stride
            recon = [0] * stride
            for i, value in enumerate(scan):
                left = recon[i - channels] if i >= channels else 0
                up = prev[i]
                up_left = prev[i - channels] if i >= channels else 0
                if filter_type == 0:
                    predictor = 0
                elif filter_type == 1:
                    predictor = left
                elif filter_type == 2:
                    predictor = up
                elif filter_type == 3:
                    predictor = (left + up) // 2
                elif filter_type == 4:
                    p = left + up - up_left
                    pa = abs(p - left)
                    pb = abs(p - up)
                    pc = abs(p - up_left)
                    predictor = left if pa <= pb and pa <= pc else up if pb <= pc else up_left
                else:
                    return None
                recon[i] = (value + predictor) & 0xFF
            rows.append([
                (recon[x * channels], recon[x * channels + 1], recon[x * channels + 2])
                for x in range(width)
            ])
            prev = recon
        return {"width": width, "height": height, "pixels": rows}
    except Exception:
        return None


def _compute_perceptual_hash(image_bytes: bytes) -> str:
    """Compute a simple 8x8 average-hash over the image brightness.

    The function is intentionally dependency-light: it downsamples to an 8x8
    luminance grid (nearest-neighbour) and emits a 16-char hex digest where
    each bit records whether a cell is brighter than the grid mean. When
    Pillow is unavailable or decoding fails we fall back to a ``"raw:"`` sha1
    prefix so the field remains a stable, debuggable string.
    """

    decoded = _load_image_rgb(image_bytes)
    if decoded is None:
        return "raw:" + hashlib.sha1(image_bytes).hexdigest()[:16]

    width = decoded["width"]
    height = decoded["height"]
    if width <= 0 or height <= 0:
        return "raw:empty"

    brightness_grid: list[float] = []
    for gy in range(8):
        src_y = min(height - 1, int(gy * height / 8))
        for gx in range(8):
            src_x = min(width - 1, int(gx * width / 8))
            r, g, b = decoded["pixels"][src_y][src_x]
            brightness_grid.append(0.299 * r + 0.587 * g + 0.114 * b)

    mean = sum(brightness_grid) / len(brightness_grid)
    bits = 0
    for i, value in enumerate(brightness_grid):
        if value >= mean:
            bits |= 1 << i
    return f"{bits:016x}"


def _mean_abs_channel_diff(a_bytes: bytes, b_bytes: bytes) -> dict[str, Any]:
    """Compare two PNG blobs channel-wise.

    Returns ``{ok, reason, mean_abs_diff, channel_means, shape}`` on success
    or ``{ok: False, reason}`` for decode/shape failures.
    """

    a = _load_image_rgb(a_bytes)
    b = _load_image_rgb(b_bytes)
    if a is None or b is None:
        return {"ok": False, "reason": "decode_failed"}

    if a["width"] != b["width"] or a["height"] != b["height"]:
        return {
            "ok": False,
            "reason": "shape_mismatch",
            "captured_shape": [a["width"], a["height"]],
            "reference_shape": [b["width"], b["height"]],
        }

    totals = [0.0, 0.0, 0.0]
    count = 0
    for y in range(a["height"]):
        row_a = a["pixels"][y]
        row_b = b["pixels"][y]
        for x in range(a["width"]):
            px_a = row_a[x]
            px_b = row_b[x]
            totals[0] += abs(px_a[0] - px_b[0])
            totals[1] += abs(px_a[1] - px_b[1])
            totals[2] += abs(px_a[2] - px_b[2])
            count += 1

    if count == 0:
        return {"ok": False, "reason": "empty_image"}

    channel_means = [total / count for total in totals]
    mean_abs_diff = sum(channel_means) / 3.0

    return {
        "ok": True,
        "reason": None,
        "mean_abs_diff": mean_abs_diff,
        "channel_means": channel_means,
        "shape": [a["width"], a["height"]],
    }


def _read_bytes_safely(path: Path) -> bytes | None:
    if not path.exists():
        return None
    try:
        return path.read_bytes()
    except Exception:
        return None


def _running_in_blender_runtime() -> bool:
    try:
        import bpy  # type: ignore

        return not bpy.__class__.__module__.startswith("unittest")
    except Exception:
        return False


def _ensure_blender_readiness_fixture() -> dict[str, Any]:
    """Create a tiny inspectable terrain scene when running inside Blender."""

    if not _running_in_blender_runtime():
        return {"created": False, "reason": "no_blender_runtime"}

    try:
        import math
        import bpy  # type: ignore
        sample_warning: str | None = None

        # Clear prior gate fixture only; never touch user-authored objects.
        for obj in list(bpy.data.objects):
            if obj.name.startswith("VB_VisualGate_"):
                bpy.data.objects.remove(obj, do_unlink=True)

        size = 18.0
        verts = []
        faces = []
        grid = 18
        for y in range(grid + 1):
            for x in range(grid + 1):
                px = (x / grid - 0.5) * size
                py = (y / grid - 0.5) * size
                pz = (
                    0.9 * math.sin(px * 0.35)
                    + 0.45 * math.cos(py * 0.42)
                    + 0.18 * math.sin((px + py) * 0.7)
                )
                verts.append((px, py, pz))
        for y in range(grid):
            for x in range(grid):
                i = y * (grid + 1) + x
                faces.append((i, i + 1, i + grid + 2, i + grid + 1))

        mesh = bpy.data.meshes.new("VB_VisualGate_TerrainMesh")
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        terrain_obj = bpy.data.objects.new("VB_VisualGate_Terrain", mesh)
        bpy.context.collection.objects.link(terrain_obj)

        mat = bpy.data.materials.new("VB_VisualGate_TerrainMat")
        mat.diffuse_color = (0.22, 0.33, 0.18, 1.0)
        terrain_obj.data.materials.append(mat)

        light_data = bpy.data.lights.new("VB_VisualGate_KeyLightData", type="SUN")
        light_obj = bpy.data.objects.new("VB_VisualGate_KeyLight", light_data)
        bpy.context.collection.objects.link(light_obj)
        light_obj.rotation_euler = (math.radians(48.0), 0.0, math.radians(36.0))
        light_data.energy = 2.2

        camera_data = bpy.data.cameras.new("VB_VisualGate_CameraData")
        camera_obj = bpy.data.objects.new("VB_VisualGate_Camera", camera_data)
        bpy.context.collection.objects.link(camera_obj)
        camera_obj.location = (15.0, -18.0, 12.0)
        direction = terrain_obj.location - camera_obj.location
        camera_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        camera_data.lens = 32.0
        camera_data.clip_end = 500.0
        bpy.context.scene.camera = camera_obj

        try:
            bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
        except Exception:
            bpy.context.scene.render.engine = "BLENDER_EEVEE"
        if hasattr(bpy.context.scene, "eevee"):
            try:
                bpy.context.scene.eevee.taa_render_samples = 32
            except (AttributeError, TypeError) as exc:
                sample_warning = repr(exc)
        bpy.context.scene.world.color = (0.035, 0.045, 0.055)
        return {
            "created": True,
            "object_count": 3,
            "mesh_vertices": len(verts),
            "mesh_faces": len(faces),
            "sample_warning": sample_warning,
        }
    except Exception as exc:  # noqa: BLE001 - readiness gate reports exact fixture failure
        return {"created": False, "reason": repr(exc)}


def _image_luma_stats(image_bytes: bytes) -> dict[str, Any]:
    decoded = _load_image_rgb(image_bytes)
    if decoded is None:
        return {"decoded": False}
    values = []
    for row in decoded["pixels"]:
        for r, g, b in row:
            values.append(0.299 * r + 0.587 * g + 0.114 * b)
    if not values:
        return {"decoded": True, "mean": 0.0, "stddev": 0.0}
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return {
        "decoded": True,
        "mean": mean,
        "stddev": variance ** 0.5,
    }


def run_gate(
    *,
    allow_no_blender: bool = False,
    screenshot_width: int = 320,
    screenshot_height: int = 180,
) -> tuple[dict[str, Any], int]:
    from veilbreakers_terrain.handlers import COMMAND_HANDLERS
    from veilbreakers_terrain.src.veilbreakers_mcp.blender_server import (
        dispatch,
        resolve_command,
    )

    required_commands = {
        "terrain_capture_scene_read",
        "terrain_read_viewport_vantage",
        "terrain_assert_vantage_fresh",
        "terrain_is_in_frustum",
        "visual_qa_setup_camera",
        "visual_qa_set_shading",
        "visual_qa_capture_screenshot",
        "material_create_procedural",
        "terrain_generate_lods",
        "terrain_validation",
    }
    required_locations = {
        "scene_read": "terrain_capture_scene_read",
        "viewport_read": "terrain_read_viewport_vantage",
        "viewport_fresh": "terrain_assert_vantage_fresh",
        "frustum_check": "terrain_is_in_frustum",
        "visual_setup_camera": "visual_qa_setup_camera",
        "visual_set_shading": "visual_qa_set_shading",
        "visual_capture_screenshot": "visual_qa_capture_screenshot",
        "material_procedural": "material_create_procedural",
        "terrain_lods": "terrain_generate_lods",
        "validation": "terrain_validation",
    }

    missing_commands = sorted(cmd for cmd in required_commands if cmd not in COMMAND_HANDLERS)
    noncallable_commands = sorted(
        cmd for cmd in required_commands
        if cmd in COMMAND_HANDLERS and not callable(COMMAND_HANDLERS[cmd])
    )
    location_mismatches = {
        loc: {"expected": cmd, "actual": resolve_command(loc)}
        for loc, cmd in required_locations.items()
        if resolve_command(loc) != cmd
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    blender_runtime = _running_in_blender_runtime()
    fixture_report = _ensure_blender_readiness_fixture()
    probes: dict[str, Any] = {}
    probes["scene_read"] = dispatch("scene_read", {"reviewer": "visual_gate"})
    probes["viewport_read"] = dispatch("viewport_read", {})
    vantage = (
        probes["viewport_read"].get("result", {}).get("vantage")
        if _result_status_ok(probes["viewport_read"])
        else None
    )
    probes["viewport_fresh"] = dispatch(
        "viewport_fresh",
        {"vantage": vantage, "max_age_seconds": 300.0},
    )
    probes["frustum_check"] = dispatch(
        "frustum_check",
        {"vantage": vantage, "world_position": [0.0, 0.0, 0.0]},
    )
    probes["visual_setup_camera"] = dispatch(
        "visual_setup_camera",
        {"max_extent": 128.0, "fov_degrees": 45.0, "padding": 1.2},
    )
    probes["visual_set_shading"] = dispatch(
        "visual_set_shading",
        {"shading_type": "MATERIAL", "use_scene_lights": True},
    )
    probes["visual_capture_screenshot"] = dispatch(
        "visual_capture_screenshot",
        {
            "filepath": str(THUMBNAIL_PATH),
            "width": screenshot_width,
            "height": screenshot_height,
            "mode": "render" if blender_runtime else "viewport",
        },
    )
    probes["material_list"] = dispatch("material_procedural", {"list_available": True})

    probe_failures = {
        name: payload
        for name, payload in probes.items()
        if not _status_ok(payload)
    }

    # Honour the caller's requested shape rather than a canned 507x64 constant.
    # The screenshot handler may still clamp, in which case the contract check
    # records the mismatch as a blocker (screenshot_contract).
    screenshot_result = probes["visual_capture_screenshot"].get("result", {})
    screenshot_contract_ok = (
        screenshot_result.get("width") == screenshot_width
        and screenshot_result.get("height") == screenshot_height
        and screenshot_result.get("captured") is True
    )
    material_result = probes["material_list"].get("result", {})
    material_contract_ok = material_result.get("count", 0) >= 45

    # --- Thumbnail byte/pixel analysis -----------------------------------------
    thumbnail_bytes = _read_bytes_safely(THUMBNAIL_PATH)
    captured_byte_length = len(thumbnail_bytes) if thumbnail_bytes is not None else 0
    placeholder_png = _is_placeholder_png_bytes(thumbnail_bytes)
    perceptual_hash = (
        _compute_perceptual_hash(thumbnail_bytes) if thumbnail_bytes else "raw:missing"
    )
    image_stats = _image_luma_stats(thumbnail_bytes) if thumbnail_bytes else {"decoded": False}
    thumbnail_decode_failed = bool(
        thumbnail_bytes is not None
        and not placeholder_png
        and image_stats.get("decoded") is not True
    )
    blank_png = bool(
        blender_runtime
        and image_stats.get("decoded")
        and float(image_stats.get("stddev", 0.0)) < 1.0
    )

    reference_bytes = _read_bytes_safely(REFERENCE_PATH)
    reference_hash = (
        _compute_perceptual_hash(reference_bytes) if reference_bytes else None
    )

    pixel_diff_report: dict[str, Any] = {"compared": False}
    pixel_diff_exceeded = False
    if (
        thumbnail_bytes is not None
        and reference_bytes is not None
        and image_stats.get("decoded") is True
        and not _is_placeholder_png_bytes(thumbnail_bytes)
        and not _is_placeholder_png_bytes(reference_bytes)
    ):
        diff = _mean_abs_channel_diff(thumbnail_bytes, reference_bytes)
        pixel_diff_report = {"compared": True, **diff}
        if not diff["ok"]:
            pixel_diff_exceeded = True
        elif diff.get("mean_abs_diff", 0.0) > PIXEL_DIFF_CHANNEL_THRESHOLD:
            pixel_diff_exceeded = True
            pixel_diff_report["reason"] = "mean_abs_diff_exceeded"
    elif thumbnail_bytes is not None and reference_bytes is not None:
        pixel_diff_report = {
            "compared": False,
            "ok": False,
            "reason": "decode_failed_or_placeholder",
        }

    blockers: list[str] = []
    if missing_commands:
        blockers.append("missing_commands")
    if noncallable_commands:
        blockers.append("noncallable_commands")
    if location_mismatches:
        blockers.append("location_mismatches")
    if probe_failures:
        blockers.append("probe_failures")
    if not screenshot_contract_ok:
        blockers.append("screenshot_contract")
    if not material_contract_ok:
        blockers.append("material_library_contract")
    if placeholder_png:
        blockers.append("placeholder_png")
    if thumbnail_decode_failed:
        blockers.append("thumbnail_decode_failed")
    if blank_png:
        blockers.append("blank_png")
    if pixel_diff_exceeded:
        blockers.append("pixel_diff_exceeded")
    if blender_runtime and reference_bytes is None:
        blockers.append("missing_visual_reference")
    if not blender_runtime:
        blockers.append("no_blender_runtime")
    if blender_runtime and not fixture_report.get("created"):
        blockers.append("fixture_creation_failed")

    ready = not blockers
    if not blender_runtime:
        ready = False

    payload = {
        "ready_for_visual_testing": ready,
        "blockers": blockers,
        "missing_commands": missing_commands,
        "noncallable_commands": noncallable_commands,
        "location_mismatches": location_mismatches,
        "probe_failures": probe_failures,
        "screenshot_contract_ok": screenshot_contract_ok,
        "material_contract_ok": material_contract_ok,
        "blender_runtime_detected": blender_runtime,
        "captured_byte_length": captured_byte_length,
        "placeholder_png": placeholder_png,
        "thumbnail_decode_failed": thumbnail_decode_failed,
        "blank_png": blank_png,
        "image_stats": image_stats,
        "blender_fixture": fixture_report,
        "perceptual_hash": perceptual_hash,
        "reference_perceptual_hash": reference_hash,
        "reference_present": reference_bytes is not None,
        "pixel_diff": pixel_diff_report,
        "pixel_diff_exceeded": pixel_diff_exceeded,
        "requested_screenshot_shape": [screenshot_width, screenshot_height],
        "allow_no_blender": allow_no_blender,
        "note": (
            "Headless dispatch wiring checked. blender_runtime_detected=false "
            "means the next gate must be run inside Blender/headless Blender "
            "for real renders; the captured PNG, PHash, and pixel-diff fields "
            "only carry meaning when a real Blender runtime is present."
        ),
    }

    # Exit code rules:
    #   * no blender + no flag  -> exit 1 (fail-hard)
    #   * no blender + flag     -> exit 0, ready=False, for CI plumbing
    #   * placeholder/pixel_diff -> exit 1 regardless of flag
    exit_code = 0 if ready else 1
    if not blender_runtime:
        exit_code = 0 if allow_no_blender else 1
    if (
        placeholder_png
        or blank_png
        or pixel_diff_exceeded
        or thumbnail_decode_failed
        or "missing_visual_reference" in blockers
        or "fixture_creation_failed" in blockers
    ):
        exit_code = 1

    return payload, exit_code


def write_outputs(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Visual Testing Readiness",
        "",
        f"- Ready for visual testing: {payload['ready_for_visual_testing']}",
        f"- Blockers: {', '.join(payload['blockers']) if payload['blockers'] else 'none'}",
        f"- Blender runtime detected: {payload['blender_runtime_detected']}",
        f"- Screenshot contract ok: {payload['screenshot_contract_ok']}",
        f"- Material library contract ok: {payload['material_contract_ok']}",
        f"- Captured thumbnail bytes: {payload['captured_byte_length']}",
        f"- Placeholder PNG detected: {payload['placeholder_png']}",
        f"- Blank PNG detected: {payload['blank_png']}",
        f"- Blender fixture created: {payload['blender_fixture'].get('created')}",
        f"- Perceptual hash: {payload['perceptual_hash']}",
        f"- Reference present: {payload['reference_present']}",
        f"- Pixel diff exceeded: {payload['pixel_diff_exceeded']}",
        "",
        payload["note"],
        "",
    ]
    MD_OUT.write_text("\n".join(lines), encoding="utf-8")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Visual testing readiness gate")
    parser.add_argument(
        "--allow-no-blender",
        action="store_true",
        help=(
            "Dev/CI preview: exit 0 when Blender runtime is missing, but still "
            "record ready_for_visual_testing=False. Placeholder PNGs and pixel "
            "diff exceedance continue to fail the gate."
        ),
    )
    parser.add_argument(
        "--screenshot-width",
        type=int,
        default=320,
        help="Requested screenshot width (enforced in contract check).",
    )
    parser.add_argument(
        "--screenshot-height",
        type=int,
        default=180,
        help="Requested screenshot height (enforced in contract check).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    if argv is None and _running_in_blender_runtime():
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = parser.parse_args(argv)
    payload, code = run_gate(
        allow_no_blender=args.allow_no_blender,
        screenshot_width=args.screenshot_width,
        screenshot_height=args.screenshot_height,
    )
    write_outputs(payload)
    print(f"wrote {JSON_OUT}")
    print(f"wrote {MD_OUT}")
    print(f"ready_for_visual_testing={payload['ready_for_visual_testing']}")
    print(f"blender_runtime_detected={payload['blender_runtime_detected']}")
    print(f"placeholder_png={payload['placeholder_png']}")
    print(f"blank_png={payload['blank_png']}")
    print(f"pixel_diff_exceeded={payload['pixel_diff_exceeded']}")
    if payload["blockers"]:
        print(f"blockers={','.join(payload['blockers'])}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

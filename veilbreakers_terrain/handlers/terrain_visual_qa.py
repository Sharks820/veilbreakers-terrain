"""Visual QA utilities for Blender terrain visualization.

Defect fixes (BLOCKER 2):
  A - Camera aim uses Vector.to_track_quat('-Z', 'Y') in Blender; the
      pure-math compute_rotation_to_look_at returns Blender-convention Euler.
  B - THUMBNAIL_MAX_DIM (507) vs RENDER_MAX_DIM (7680) context-aware clamp.
  C - capture_viewport_screenshot uses bpy.ops.render.opengl by default.
  D - Output filepath must resolve inside VEILBREAKERS_VISUAL_QA_ROOT.

Also extends camera.data.sensor_width and camera.data.clip_end so km-scale
terrains aren't clipped.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

_HAS_BPY = False
try:
    import bpy
    _HAS_BPY = True
except ImportError:
    pass


VALID_SHADING_TYPES = frozenset({"WIREFRAME", "SOLID", "MATERIAL", "RENDERED"})

THUMBNAIL_MAX_DIM: int = 507
RENDER_MAX_DIM: int = 7680
_SCREENSHOT_MIN_DIM: int = 64

_DEFAULT_VISUAL_QA_ROOT = "output/visual_readiness"


def _visual_qa_root() -> Path:
    root_env = os.environ.get("VEILBREAKERS_VISUAL_QA_ROOT")
    root = Path(root_env) if root_env else Path(_DEFAULT_VISUAL_QA_ROOT)
    return root.resolve()


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _sanitize_output_filepath(filepath: str) -> tuple[Optional[Path], Optional[str]]:
    if not filepath:
        return None, "missing_filepath"
    try:
        candidate = Path(filepath).resolve()
    except (OSError, RuntimeError):
        return None, "invalid_filepath"
    root = _visual_qa_root()
    if not _is_relative_to(candidate, root):
        return None, "filepath_outside_allowed_root"
    return candidate, None


@dataclass
class CameraSetup:
    location: tuple[float, float, float]
    rotation: tuple[float, float, float]
    focal_length: float
    fov_degrees: float
    sensor_width_mm: float = 36.0
    max_extent: float = 0.0


@dataclass
class ViewportShading:
    shading_type: str
    use_scene_lights: bool = True
    use_world_lighting: bool = True


def fov_to_focal_length(fov_degrees: float, sensor_width: float = 36.0) -> float:
    fov_rad = math.radians(fov_degrees)
    return sensor_width / (2.0 * math.tan(fov_rad / 2.0))


def compute_rotation_to_look_at(
    camera_pos: tuple[float, float, float],
    target_pos: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Blender-convention Euler for -Z forward / +Y up look-at."""
    dx = target_pos[0] - camera_pos[0]
    dy = target_pos[1] - camera_pos[1]
    dz = target_pos[2] - camera_pos[2]

    horizontal = math.sqrt(dx * dx + dy * dy)
    rx = math.atan2(horizontal, -dz)
    ry = 0.0
    rz = math.atan2(-dx, dy)
    return (rx, ry, rz)


def auto_frame_terrain(
    max_extent: float,
    fov_degrees: float = 45.0,
    padding: float = 1.2,
) -> float:
    if max_extent <= 0:
        return 10.0
    fov_rad = math.radians(fov_degrees)
    return max_extent / (2.0 * math.tan(fov_rad / 2.0)) * padding


def _clamp_screenshot_dimension(value: int, context: str = "render") -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = _SCREENSHOT_MIN_DIM
    upper = THUMBNAIL_MAX_DIM if context == "thumbnail" else RENDER_MAX_DIM
    if v < _SCREENSHOT_MIN_DIM:
        return _SCREENSHOT_MIN_DIM
    if v > upper:
        return upper
    return v


def _coerce_shading_type(shading_type: str) -> str:
    value = str(shading_type or "SOLID").upper()
    if value not in VALID_SHADING_TYPES:
        raise ValueError(
            f"Unsupported viewport shading type {shading_type!r}; "
            f"expected one of {sorted(VALID_SHADING_TYPES)}"
        )
    return value


def set_viewport_shading(shading: ViewportShading) -> bool:
    shading_type = _coerce_shading_type(shading.shading_type)
    if not _HAS_BPY:
        return False
    try:
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        space.shading.type = shading_type
                        if hasattr(space.shading, "use_scene_lights"):
                            space.shading.use_scene_lights = shading.use_scene_lights
                        if hasattr(space.shading, "use_world_lighting"):
                            space.shading.use_world_lighting = shading.use_world_lighting
                        return True
        return False
    except Exception:
        return False


def _setup_camera_in_blender(
    camera_setup: CameraSetup,
    target_pos: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> Optional[Any]:
    if not _HAS_BPY:
        return None
    try:
        if "Camera" not in bpy.data.objects:
            camera_data = bpy.data.cameras.new(name="Camera")
            camera_obj = bpy.data.objects.new("Camera", camera_data)
            bpy.context.collection.objects.link(camera_obj)
        else:
            camera_obj = bpy.data.objects["Camera"]

        camera_obj.location = camera_setup.location

        target = target_pos
        applied_rotation: tuple[float, float, float]
        try:
            from mathutils import Vector  # type: ignore

            direction = Vector(target) - Vector(camera_setup.location)
            if direction.length > 0.0:
                rot_quat = direction.to_track_quat('-Z', 'Y')
                euler = rot_quat.to_euler()
                applied_rotation = (float(euler.x), float(euler.y), float(euler.z))
            else:
                applied_rotation = camera_setup.rotation
        except Exception:
            applied_rotation = camera_setup.rotation

        camera_obj.rotation_euler = applied_rotation

        if camera_obj.data is not None:
            camera_obj.data.lens = camera_setup.focal_length
            if hasattr(camera_obj.data, "sensor_width"):
                try:
                    camera_obj.data.sensor_width = float(camera_setup.sensor_width_mm)
                except Exception:
                    pass
            if hasattr(camera_obj.data, "clip_end") and camera_setup.max_extent > 0.0:
                try:
                    current = float(getattr(camera_obj.data, "clip_end", 0.0) or 0.0)
                except Exception:
                    current = 0.0
                required = float(camera_setup.max_extent) * 4.0
                if required > current:
                    try:
                        camera_obj.data.clip_end = required
                    except Exception:
                        pass

        bpy.context.scene.camera = camera_obj
        return camera_obj
    except Exception:
        return None


def capture_viewport_screenshot(
    filepath: str,
    width: int = 1920,
    height: int = 1080,
    mode: str = "viewport",
) -> bool:
    if not _HAS_BPY:
        return False

    width = _clamp_screenshot_dimension(width, context="render")
    height = _clamp_screenshot_dimension(height, context="render")

    try:
        render = bpy.context.scene.render
        render.filepath = filepath
        render.resolution_x = width
        render.resolution_y = height
        render.image_settings.file_format = "PNG"
        if mode == "render":
            bpy.ops.render.render(write_still=True)
        else:
            bpy.ops.render.opengl(write_still=True)
        return True
    except Exception:
        return False


def handle_visual_qa_setup_camera(
    max_extent: float,
    fov_degrees: float = 45.0,
    padding: float = 1.2,
    camera_height: float = 0.0,
    look_at_center: bool = True,
    sensor_width_mm: float = 36.0,
) -> dict[str, Any]:
    try:
        distance = auto_frame_terrain(max_extent, fov_degrees, padding)
        focal_length = fov_to_focal_length(fov_degrees, sensor_width=sensor_width_mm)

        camera_pos = (distance * 0.7, distance * 0.7, camera_height + distance * 0.5)
        target_pos = (0.0, 0.0, camera_height) if look_at_center else (0.0, 0.0, 0.0)
        rotation = compute_rotation_to_look_at(camera_pos, target_pos)

        camera_setup = CameraSetup(
            location=camera_pos,
            rotation=rotation,
            focal_length=focal_length,
            fov_degrees=fov_degrees,
            sensor_width_mm=sensor_width_mm,
            max_extent=float(max_extent),
        )
        camera_obj = _setup_camera_in_blender(camera_setup, target_pos=target_pos)

        applied_rotation: tuple[float, float, float] = rotation
        if camera_obj is not None:
            rot = getattr(camera_obj, "rotation_euler", None)
            if rot is not None:
                try:
                    applied_rotation = (float(rot[0]), float(rot[1]), float(rot[2]))
                except Exception:
                    try:
                        applied_rotation = (float(rot.x), float(rot.y), float(rot.z))
                    except Exception:
                        pass

        clip_end: Optional[float] = None
        if camera_obj is not None and getattr(camera_obj, "data", None) is not None:
            clip_end_val = getattr(camera_obj.data, "clip_end", None)
            if clip_end_val is not None:
                try:
                    clip_end = float(clip_end_val)
                except Exception:
                    clip_end = None

        return {
            "status": "ok",
            "distance": distance,
            "focal_length": focal_length,
            "sensor_width_mm": sensor_width_mm,
            "camera_location": camera_pos,
            "camera_rotation": applied_rotation,
            "camera_applied": camera_obj is not None,
            "clip_end": clip_end,
            "has_bpy": _HAS_BPY,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def handle_visual_qa_set_shading(
    shading_type: str = "SOLID",
    use_scene_lights: bool = True,
    use_world_lighting: bool = True,
) -> dict[str, Any]:
    try:
        shading_type = _coerce_shading_type(shading_type)
        shading = ViewportShading(
            shading_type=shading_type,
            use_scene_lights=use_scene_lights,
            use_world_lighting=use_world_lighting,
        )
        success = set_viewport_shading(shading)
        return {
            "status": "ok",
            "shading_type": shading_type,
            "applied": success,
            "has_bpy": _HAS_BPY,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# V-1: Channel validation
# ---------------------------------------------------------------------------

# Maps channel name -> (dtype_family, (min_value, max_value)).
# dtype_family is "float", "integer", or "bool".
REQUIRED_STACK_CHANNELS: Dict[str, Tuple[str, Tuple[float, float]]] = {
    "height":              ("float", (0.0, 9000.0)),
    "slope":               ("float", (0.0, 90.0)),
    "curvature":           ("float", (-1000.0, 1000.0)),
    "ridge":               ("float", (0.0, 1.0)),
    "basin":               ("float", (0.0, 1.0)),
    "flow_accumulation":   ("float", (0.0, 1.0e12)),
    "wetness":             ("float", (0.0, 1.0)),
    "drainage":            ("float", (0.0, 1.0e12)),
    "water_surface_mask":  ("float", (0.0, 1.0)),
    "water_surface_elevation_m": ("float", (0.0, 9000.0)),
    "water_depth_m":       ("float", (0.0, 500.0)),
    "cliff_mask":          ("float", (0.0, 1.0)),
    "talus_mask":          ("float", (0.0, 1.0)),
    "strata_mask":         ("float", (0.0, 1.0)),
    "foam":                ("float", (0.0, 1.0)),
    "mist":                ("float", (0.0, 1.0)),
    "splatmap_weights_layer": ("float", (0.0, 1.0)),
    "heightmap_raw_u16":   ("integer", (0.0, 65535.0)),
    "terrain_normals":     ("float", (-1.0, 1.0)),
    "ambient_occlusion_bake": ("float", (0.0, 1.0)),
    "navmesh_area_id":     ("integer", (0.0, 255.0)),
    "gameplay_zone":       ("integer", (0.0, 255.0)),
    "traversability":      ("float", (0.0, 1.0)),
    "road_mask":           ("float", (0.0, 1.0)),
}


def validate_stack_channels(
    stack: Any,
    required_channels: Optional[Dict[str, Tuple[str, Tuple[float, float]]]] = None,
) -> Dict[str, Any]:
    """Validate required channels on a TerrainMaskStack-like object."""
    if required_channels is None:
        required_channels = REQUIRED_STACK_CHANNELS

    missing: List[str] = []
    dtype_mismatch: List[str] = []
    range_violations: List[str] = []
    invalid_channels: List[str] = []
    checked: int = 0

    for channel, (dtype_family, (lo, hi)) in required_channels.items():
        arr = getattr(stack, channel, None)
        if arr is None:
            missing.append(channel)
            continue

        try:
            arr = np.asarray(arr)
        except Exception:
            missing.append(channel)
            continue

        if arr.size == 0:
            invalid_channels.append(channel)
            checked += 1
            continue
        try:
            finite_ok = bool(np.isfinite(arr).all())
        except TypeError:
            finite_ok = False
        if not finite_ok:
            invalid_channels.append(channel)
            checked += 1
            continue

        # dtype check
        if dtype_family == "float":
            if not np.issubdtype(arr.dtype, np.floating):
                dtype_mismatch.append(channel)
                checked += 1
                continue
        elif dtype_family == "integer":
            if not np.issubdtype(arr.dtype, np.integer):
                dtype_mismatch.append(channel)
                checked += 1
                continue
        elif dtype_family == "bool":
            if arr.dtype != np.bool_:
                dtype_mismatch.append(channel)
                checked += 1
                continue

        # range check
        arr_min = float(np.nanmin(arr))
        arr_max = float(np.nanmax(arr))
        if arr_min < lo or arr_max > hi:
            range_violations.append(channel)

        checked += 1

    ok = not missing and not dtype_mismatch and not range_violations and not invalid_channels
    return {
        "ok": ok,
        "missing": missing,
        "dtype_mismatch": dtype_mismatch,
        "range_violations": range_violations,
        "invalid_channels": invalid_channels,
        "checked": checked,
    }


def validate_channel_manifest(
    stack: Any,
    required_channels: Optional[Dict[str, Tuple[str, Tuple[float, float]]]] = None,
) -> Dict[str, Any]:
    """Public API: validate required channels on a stack object.

    Parameters
    ----------
    stack:
        Any object that exposes terrain channel arrays as attributes (e.g. a
        ``TerrainMaskStack``).  Each channel is retrieved via ``getattr``.
    required_channels:
        Mapping of ``channel_name -> (dtype_family, (min_val, max_val))``.
        Defaults to :data:`REQUIRED_STACK_CHANNELS` when ``None``.

    Returns
    -------
    dict with keys:
        ``valid`` (bool)
            True when no issues were found.
        ``missing`` (list[str])
            Channel names absent from the stack or not array-convertible.
        ``out_of_range`` (list[str])
            Channel names whose values exceed the declared min/max bounds.
        ``issues`` (list[str])
            Human-readable summary lines (``missing:<name>``,
            ``dtype_mismatch:<name>``, ``out_of_range:<name>``).
    """
    raw = validate_stack_channels(stack, required_channels=required_channels)

    # Merge dtype_mismatch into out_of_range to match the simplified public contract
    out_of_range: List[str] = (
        raw["range_violations"] + raw["dtype_mismatch"] + raw.get("invalid_channels", [])
    )

    issues: List[str] = (
        [f"missing:{c}" for c in raw["missing"]]
        + [f"dtype_mismatch:{c}" for c in raw["dtype_mismatch"]]
        + [f"out_of_range:{c}" for c in raw["range_violations"]]
        + [f"invalid:{c}" for c in raw.get("invalid_channels", [])]
    )

    return {
        "valid": raw["ok"],
        "missing": raw["missing"],
        "out_of_range": out_of_range,
        "issues": issues,
    }


def _array_or_none(stack: Any, channel: str) -> Optional[np.ndarray]:
    value = getattr(stack, channel, None)
    if value is None:
        return None
    try:
        arr = np.asarray(value)
    except Exception:
        return None
    if arr.size == 0:
        return None
    return arr


def _qa_result(name: str, ok: bool, reason: str) -> Dict[str, Any]:
    return {"name": name, "ok": bool(ok), "reason": str(reason)}


def _check_stochastic_seam(stack: Any) -> Dict[str, Any]:
    arr = _array_or_none(stack, "stochastic_uv_mask")
    if arr is None:
        arr = _array_or_none(stack, "splatmap_weights_layer")
    if arr is None:
        return _qa_result("stochastic_seam", False, "missing stochastic_uv_mask or splatmap_weights_layer")
    if arr.ndim == 3:
        arr = arr[..., 0]
    if arr.ndim != 2 or min(arr.shape) < 3:
        return _qa_result("stochastic_seam", False, f"bad shape {arr.shape}")

    n = min(arr.shape)
    idx = np.arange(n - 1)
    diag = arr[idx, idx]
    adjacent = arr[idx, idx + 1]
    diag_delta = np.asarray(diag, dtype=np.float64) - np.asarray(adjacent, dtype=np.float64)
    seam_variance = float(np.nanvar(diag_delta))
    seam_score = max(seam_variance, float(np.nanmean(np.abs(diag_delta))))
    return _qa_result(
        "stochastic_seam",
        seam_score <= 0.2,
        f"diagonal_score={seam_score:.4f} variance={seam_variance:.4f} (need <= 0.2)",
    )


def _check_foam_alpha(stack: Any) -> Dict[str, Any]:
    foam = _array_or_none(stack, "foam")
    if foam is None:
        return _qa_result("foam_alpha", False, "missing foam")
    finite = np.isfinite(foam)
    if not finite.all():
        return _qa_result("foam_alpha", False, "non-finite foam values")
    lo = float(np.nanmin(foam))
    hi = float(np.nanmax(foam))
    return _qa_result("foam_alpha", lo >= 0.0 and hi <= 1.0, f"range=[{lo:.4f},{hi:.4f}]")


def _check_water_elevation(stack: Any) -> Dict[str, Any]:
    mask = _array_or_none(stack, "water_surface_mask")
    elev = _array_or_none(stack, "water_surface_elevation_m")
    if mask is None or elev is None:
        return _qa_result("water_elevation", False, "missing water_surface_mask or water_surface_elevation_m")
    wet = np.asarray(mask) > 0.01
    if not wet.any():
        return _qa_result("water_elevation", True, "no water cells")
    wet_elev = np.asarray(elev)[wet]
    ok = bool(np.isfinite(wet_elev).all() and float(np.nanmax(wet_elev)) > 0.0)
    return _qa_result(
        "water_elevation",
        ok,
        f"wet_cells={int(wet.sum())} max_elevation={float(np.nanmax(wet_elev)):.4f}",
    )


def _check_tree_z_export(stack: Any) -> Dict[str, Any]:
    points = _array_or_none(stack, "tree_instance_points")
    if points is None:
        return _qa_result("tree_z_export", True, "no tree_instance_points")
    if points.ndim != 2 or points.shape[1] < 3:
        return _qa_result("tree_z_export", False, f"bad shape {points.shape}")
    height = _array_or_none(stack, "height")
    non_flat = height is not None and (float(np.nanmax(height)) - float(np.nanmin(height))) > 1e-5
    z = np.asarray(points[:, 2], dtype=np.float64)
    ok = (not non_flat) or bool(np.all(np.abs(z) > 1e-6))
    return _qa_result("tree_z_export", ok, f"tree_count={len(z)} zero_z={int((np.abs(z) <= 1e-6).sum())}")


def _check_phantom_channel_writers(stack: Any) -> Dict[str, Any]:
    populated = getattr(stack, "populated_by_pass", {}) or {}
    missing_writers: List[str] = []
    for channel in REQUIRED_STACK_CHANNELS:
        if _array_or_none(stack, channel) is not None and not populated.get(channel):
            missing_writers.append(channel)
    return _qa_result(
        "phantom_channel_writers",
        not missing_writers,
        "missing_writers=" + ",".join(missing_writers[:8]) if missing_writers else "all present channels have writers",
    )


# Renamed from VisualQA per FIX-B14-13: this gate checks data contracts, not rendered output.
def run_checks(stack: Any) -> Dict[str, Any]:
    """Run Phase 9 data-contract checks on a stack-like object.

    This is code-level validation only; it does not claim rendered visual
    quality. Blender viewport/render proof remains a separate gate.
    """
    checks = [
        _check_stochastic_seam(stack),
        _check_foam_alpha(stack),
        _check_water_elevation(stack),
        _check_tree_z_export(stack),
        _check_phantom_channel_writers(stack),
    ]
    failed = [check for check in checks if not check["ok"]]
    return {
        "ok": not failed,
        "checks": checks,
        "failed": failed,
        "failed_names": [check["name"] for check in failed],
    }


def handle_visual_qa_validate_channels(
    stack: Any,
    required_channels: Optional[Dict[str, Tuple[str, Tuple[float, float]]]] = None,
) -> Dict[str, Any]:
    """Handler wrapping validate_stack_channels with try/except for pipeline use."""
    try:
        result = validate_stack_channels(stack, required_channels=required_channels)
        issues: List[str] = (
            [f"missing:{c}" for c in result["missing"]]
            + [f"dtype_mismatch:{c}" for c in result["dtype_mismatch"]]
            + [f"out_of_range:{c}" for c in result["range_violations"]]
            + [f"invalid:{c}" for c in result.get("invalid_channels", [])]
        )
        return {
            "status": "ok",
            "ok": result["ok"],
            "missing": result["missing"],
            "issues": issues,
            "checked": result["checked"],
        }
    except Exception as exc:
        return {"status": "error", "ok": False, "message": str(exc), "issues": []}


def handle_visual_qa_capture_screenshot(
    filepath: str,
    width: int = 1920,
    height: int = 1080,
    mode: str = "viewport",
    thumbnail: bool = False,
) -> dict[str, Any]:
    try:
        sanitized, err = _sanitize_output_filepath(filepath)
        if err is not None:
            return {"status": "error", "error": err, "filepath": filepath}
        assert sanitized is not None
        safe_path = str(sanitized)
        context = "thumbnail" if thumbnail else "render"
        clamped_width = _clamp_screenshot_dimension(width, context=context)
        clamped_height = _clamp_screenshot_dimension(height, context=context)

        try:
            sanitized.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        success = capture_viewport_screenshot(
            safe_path, clamped_width, clamped_height, mode=mode
        )
        status = "ok" if success else "failed"
        error = None if success else ("bpy_unavailable" if not _HAS_BPY else "capture_failed")

        result = {
            "status": status,
            "ok": bool(success),
            "filepath": safe_path,
            "width": clamped_width,
            "height": clamped_height,
            "mode": mode,
            "thumbnail": bool(thumbnail),
            "captured": success,
            "has_bpy": _HAS_BPY,
        }
        if error is not None:
            result["error"] = error
        return result
    except Exception as e:
        return {"status": "error", "ok": False, "message": str(e)}


# NOTE: register handle_visual_qa_validate_channels in handlers/__init__.py COMMAND_HANDLERS


# ---------------------------------------------------------------------------
# V-2: Render vs golden SSIM comparison (CI gate)
# ---------------------------------------------------------------------------

def compare_render_to_golden(
    render_path: str,
    golden_path: str,
    ssim_threshold: float = 0.95,
    *,
    allow_missing_golden: bool = False,
    allow_resize: bool = False,
    min_luma_std: float = 0.005,
    min_unique_colors: int = 8,
) -> Dict[str, Any]:
    """Compare a rendered image against a stored golden using SSIM.

    Returns a dict with keys:
      - ``ok`` (bool): True when SSIM >= ssim_threshold.
      - ``ssim`` (float | None): computed SSIM score; None when either image
        cannot be loaded.
      - ``threshold`` (float): the threshold used.
      - ``render_path`` (str), ``golden_path`` (str): paths as supplied.
      - ``reason`` (str): human-readable outcome.

    Missing goldens fail by default so release gates cannot pass without a
    committed baseline. Development seeding scripts can pass
    ``allow_missing_golden=True`` explicitly.

    Requires ``Pillow`` (PIL) + ``scikit-image`` or ``scipy`` for SSIM.
    Falls back to pixel-MAE when scikit-image is unavailable, using
    ``ssim_threshold`` as a MAE tolerance (0–1 scale, lower = stricter).
    """
    result: Dict[str, Any] = {
        "ok": False,
        "ssim": None,
        "threshold": ssim_threshold,
        "render_path": render_path,
        "golden_path": golden_path,
        "reason": "unknown",
        "render_shape": None,
        "golden_shape": None,
        "render_luma_std": None,
        "golden_luma_std": None,
        "render_unique_colors": None,
        "golden_unique_colors": None,
    }

    golden = Path(golden_path)
    if not golden.exists():
        result["ok"] = bool(allow_missing_golden)
        result["reason"] = "golden_absent"
        return result

    render = Path(render_path)
    if not render.exists():
        result["reason"] = "render_absent"
        return result

    try:
        from PIL import Image as _Image
        import numpy as _np_local

        r_img = _np_local.asarray(_Image.open(render_path).convert("RGB"), dtype=_np_local.float32) / 255.0
        g_img = _np_local.asarray(_Image.open(golden_path).convert("RGB"), dtype=_np_local.float32) / 255.0
        result["render_shape"] = list(r_img.shape)
        result["golden_shape"] = list(g_img.shape)

        def _information_floor(img: Any, prefix: str) -> Optional[str]:
            luma = _np_local.asarray(img, dtype=_np_local.float32).mean(axis=2)
            luma_std = float(_np_local.nanstd(luma))
            quantized = _np_local.asarray((img * 255.0).clip(0, 255), dtype=_np_local.uint8)
            unique = int(_np_local.unique(quantized.reshape(-1, 3), axis=0).shape[0])
            result[f"{prefix}_luma_std"] = round(luma_std, 6)
            result[f"{prefix}_unique_colors"] = unique
            if luma_std < min_luma_std:
                return f"low_information_{prefix}:luma_std={luma_std:.6f}"
            if unique < min_unique_colors:
                return f"low_information_{prefix}:unique_colors={unique}"
            return None

        render_info_error = _information_floor(r_img, "render")
        if render_info_error is not None:
            result["reason"] = render_info_error
            return result
        golden_info_error = _information_floor(g_img, "golden")
        if golden_info_error is not None:
            result["reason"] = golden_info_error
            return result

        if r_img.shape != g_img.shape:
            if not allow_resize:
                result["reason"] = "shape_mismatch"
                return result
            # Resize render to match golden dimensions for explicit dev seeding.
            from PIL import Image as _PIL
            r_pil = _PIL.open(render_path).convert("RGB").resize(
                (g_img.shape[1], g_img.shape[0]), _PIL.Resampling.LANCZOS
            )
            r_img = _np_local.asarray(r_pil, dtype=_np_local.float32) / 255.0

        try:
            from skimage.metrics import structural_similarity as _ssim_fn
            score = float(_ssim_fn(r_img, g_img, data_range=1.0, channel_axis=2))
            result["ssim"] = round(score, 6)
            result["ok"] = score >= ssim_threshold
            result["reason"] = "ssim_pass" if result["ok"] else "ssim_fail"
        except ImportError:
            # Fallback: mean absolute error (lower is better, threshold inverted)
            mae = float(_np_local.abs(r_img - g_img).mean())
            result["ssim"] = round(1.0 - mae, 6)
            mae_threshold = 1.0 - ssim_threshold
            result["ok"] = mae <= mae_threshold
            result["reason"] = "mae_pass" if result["ok"] else "mae_fail"

    except ImportError:
        result["reason"] = "pillow_unavailable"
        result["ok"] = False
    except Exception as exc:
        result["reason"] = f"error:{exc}"

    return result


def handle_visual_qa_compare_render(
    render_path: str,
    golden_path: str,
    ssim_threshold: float = 0.95,
    *,
    allow_missing_golden: bool = False,
    allow_resize: bool = False,
) -> Dict[str, Any]:
    """Pipeline handler wrapping compare_render_to_golden with error guard."""
    try:
        return compare_render_to_golden(
            render_path,
            golden_path,
            ssim_threshold=ssim_threshold,
            allow_missing_golden=allow_missing_golden,
            allow_resize=allow_resize,
        )
    except Exception as exc:
        return {
            "ok": False,
            "ssim": None,
            "threshold": ssim_threshold,
            "render_path": render_path,
            "golden_path": golden_path,
            "reason": f"exception:{exc}",
        }

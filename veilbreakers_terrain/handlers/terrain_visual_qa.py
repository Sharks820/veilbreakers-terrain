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

# Maps channel name → (dtype_family, (min_value, max_value))
# dtype_family is "float" or "bool".
REQUIRED_STACK_CHANNELS: Dict[str, Tuple[str, Tuple[float, float]]] = {
    "heightmap":           ("float", (0.0, 9000.0)),
    "water_surface_mask":  ("float", (0.0, 1.0)),
    "water_depth_m":       ("float", (0.0, 500.0)),
    "cliff_mask":          ("float", (0.0, 1.0)),
    "talus_mask":          ("float", (0.0, 1.0)),
    "strata_mask":         ("float", (0.0, 1.0)),
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
            checked += 1
            continue

        # dtype check
        if dtype_family == "float":
            if not np.issubdtype(arr.dtype, np.floating):
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

    ok = not missing and not dtype_mismatch and not range_violations
    return {
        "ok": ok,
        "missing": missing,
        "dtype_mismatch": dtype_mismatch,
        "range_violations": range_violations,
        "checked": checked,
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
            + [f"range_violation:{c}" for c in result["range_violations"]]
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

        return {
            "status": "ok",
            "filepath": safe_path,
            "width": clamped_width,
            "height": clamped_height,
            "mode": mode,
            "thumbnail": bool(thumbnail),
            "captured": success,
            "has_bpy": _HAS_BPY,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# NOTE: register handle_visual_qa_validate_channels in handlers/__init__.py COMMAND_HANDLERS

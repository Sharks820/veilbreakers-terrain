"""Water runtime contract validation for terrain export and visual QA."""

from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np


_REQUIRED_WATER_CHANNELS = (
    "water_surface_elevation_m",
    "flow_direction",
    "flow_accumulation",
)

_OPTIONAL_ADVANCED_WATER_CHANNELS = (
    "flow_speed",
    "foam",
    "mist",
    "wet_rock",
)


def _get(stack: Any, key: str) -> Any:
    getter = getattr(stack, "get", None)
    if callable(getter):
        return getter(key)
    return getattr(stack, key, None)


def _shape_of_height(stack: Any) -> tuple[int, int] | None:
    height = _get(stack, "height")
    if height is None:
        return None
    arr = np.asarray(height)
    if arr.ndim < 2:
        return None
    return int(arr.shape[0]), int(arr.shape[1])


def _check_array(
    issues: list[dict[str, str]],
    *,
    stack: Any,
    channel: str,
    expected_shape: tuple[int, int] | None,
    nonnegative: bool = False,
) -> None:
    raw = _get(stack, channel)
    if raw is None:
        issues.append({"code": "missing_water_channel", "message": f"missing {channel}"})
        return
    arr = np.asarray(raw)
    if expected_shape is not None and arr.shape[:2] != expected_shape:
        issues.append({
            "code": "water_channel_shape_mismatch",
            "message": f"{channel} shape {arr.shape} does not match height {expected_shape}",
        })
    if not np.issubdtype(arr.dtype, np.number):
        issues.append({
            "code": "water_channel_non_numeric",
            "message": f"{channel} contains non-numeric values",
        })
        return
    if not np.isfinite(arr).all():
        issues.append({"code": "water_channel_non_finite", "message": f"{channel} contains non-finite values"})
    if nonnegative and arr.size and float(np.nanmin(arr)) < 0.0:
        issues.append({"code": "water_channel_negative", "message": f"{channel} contains negative values"})


def validate_water_runtime_contract(
    stack: Any,
    *,
    water_shader_manifest: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Validate canonical water channels needed by Blender/Unity handoff.

    Add-on water state is not accepted as proof. The contract requires exported
    terrain channels for elevation, depth/bathymetry, flow, foam, mist, wet rock,
    and shader manifest metadata.
    """
    issues: list[dict[str, str]] = []
    expected_shape = _shape_of_height(stack)
    if expected_shape is None:
        issues.append({"code": "missing_height", "message": "water contract needs a 2-D height channel"})

    for channel in _REQUIRED_WATER_CHANNELS:
        _check_array(
            issues,
            stack=stack,
            channel=channel,
            expected_shape=expected_shape,
            nonnegative=channel in {"water_surface_elevation_m", "flow_accumulation"},
        )

    for channel in _OPTIONAL_ADVANCED_WATER_CHANNELS:
        if _get(stack, channel) is not None:
            _check_array(
                issues,
                stack=stack,
                channel=channel,
                expected_shape=expected_shape,
                nonnegative=True,
            )

    has_depth = _get(stack, "water_depth_m") is not None
    has_bathymetry = _get(stack, "bathymetry") is not None
    has_depth_zone = _get(stack, "water_depth_zone") is not None
    if has_depth:
        _check_array(
            issues,
            stack=stack,
            channel="water_depth_m",
            expected_shape=expected_shape,
            nonnegative=True,
        )
    elif has_bathymetry and has_depth_zone:
        _check_array(
            issues,
            stack=stack,
            channel="bathymetry",
            expected_shape=expected_shape,
            nonnegative=True,
        )
        _check_array(
            issues,
            stack=stack,
            channel="water_depth_zone",
            expected_shape=expected_shape,
            nonnegative=True,
        )
    else:
        issues.append({
            "code": "missing_water_depth_contract",
            "message": "expected water_depth_m or bathymetry plus water_depth_zone",
        })

    if water_shader_manifest is None:
        issues.append({
            "code": "missing_water_shader_manifest",
            "message": "missing water_shader_manifest.json payload",
        })
    else:
        materials = water_shader_manifest.get("materials")
        textures = water_shader_manifest.get("shader_textures")
        if not (
            (isinstance(materials, Mapping) and bool(materials))
            or (isinstance(materials, list) and bool(materials))
        ):
            issues.append({"code": "water_manifest_missing_materials", "message": "manifest has no materials"})
        if not isinstance(textures, Mapping) or not textures:
            issues.append({"code": "water_manifest_missing_textures", "message": "manifest has no shader_textures"})
        level = water_shader_manifest.get("water_level_m")
        if level is not None:
            try:
                if not math.isfinite(float(level)):
                    issues.append({"code": "water_manifest_non_finite_level", "message": "water_level_m is non-finite"})
            except (TypeError, ValueError):
                issues.append({"code": "water_manifest_invalid_level", "message": "water_level_m is not numeric"})

    return issues


__all__ = ["validate_water_runtime_contract"]

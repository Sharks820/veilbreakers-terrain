"""Bundle A — animation gaits shared types.

Provides the Keyframe dataclass used across all animation generators.
No Blender imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

import numpy as np


BIOME_GAIT_MAP: dict[int, str] = {
    0: "walk",
    1: "wade",
    2: "scramble",
    3: "trudge",
    4: "crouch",
}


@dataclass
class Keyframe:
    """A single animation keyframe value — Unity Animator compatible.

    frame: Timeline frame index.
    value: Channel value (radians, metres, or scale factor).
    channel: Data path type — 'location', 'rotation', or 'scale'.
    axis: Axis index 0=X, 1=Y, 2=Z.
    bone_name: Armature bone name for pose keyframes; empty for object-level.
    time: Time in SECONDS (Unity Animator Keyframe.time). 0.0 when not set.
    in_tangent: Unity Animator inTangent (slope of the curve arriving at this key).
                float('inf') = constant/stepped; 0.0 = linear/auto by default.
    out_tangent: Unity Animator outTangent (slope of the curve leaving this key).
                 float('inf') = constant/stepped; 0.0 = linear/auto by default.
    """

    frame: int
    value: float
    channel: str = "location"
    axis: int = 0
    bone_name: str = ""
    time: float = 0.0
    in_tangent: float = 0.0
    out_tangent: float = 0.0


def _json_safe_float(value: float) -> float | str | None:
    v = float(value)
    if math.isfinite(v):
        return v
    if math.isinf(v):
        return "Infinity" if v > 0 else "-Infinity"
    return None


def keyframe_to_dict(kf: Keyframe) -> dict[str, Any]:
    """Return a JSON-serialisable Unity Animator keyframe dict."""
    return {
        "frame": int(kf.frame),
        "value": _json_safe_float(kf.value),
        "channel": str(kf.channel),
        "axis": int(kf.axis),
        "bone_name": str(kf.bone_name),
        "time": _json_safe_float(kf.time),
        "in_tangent": _json_safe_float(kf.in_tangent),
        "out_tangent": _json_safe_float(kf.out_tangent),
    }


@dataclass
class GaitSelector:
    """Select terrain-aware locomotion gait from stack biome/material data."""

    default_gait: str = "walk"

    def select_gait(
        self,
        speed_mps: float = 1.0,
        *,
        stack: Any = None,
        row: int | None = None,
        col: int | None = None,
    ) -> str:
        if stack is None:
            return "run" if speed_mps >= 4.0 else self.default_gait

        biome = stack.get("biome_id") if hasattr(stack, "get") else getattr(stack, "biome_id", None)
        if biome is not None:
            arr = np.asarray(biome)
            if arr.size:
                rr = int(np.clip(row if row is not None else arr.shape[0] // 2, 0, arr.shape[0] - 1))
                cc = int(np.clip(col if col is not None else arr.shape[1] // 2, 0, arr.shape[1] - 1))
                gait = BIOME_GAIT_MAP.get(int(arr[rr, cc]))
                if gait:
                    return gait

        material = getattr(stack, "splatmap_weights_layer", None)
        if material is not None:
            weights = np.asarray(material)
            if weights.ndim == 3 and weights.shape[2] >= 2 and weights.size:
                rr = int(np.clip(row if row is not None else weights.shape[0] // 2, 0, weights.shape[0] - 1))
                cc = int(np.clip(col if col is not None else weights.shape[1] // 2, 0, weights.shape[1] - 1))
                layer = int(np.argmax(weights[rr, cc]))
                if layer == 1:
                    return "wade"
                if layer == 2:
                    return "scramble"

        return "run" if speed_mps >= 4.0 else self.default_gait


__all__ = ["BIOME_GAIT_MAP", "GaitSelector", "Keyframe", "keyframe_to_dict"]

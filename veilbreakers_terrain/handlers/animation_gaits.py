"""Bundle A — animation gaits shared types.

Provides the Keyframe dataclass used across all animation generators.
No Blender imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field


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


__all__ = ["Keyframe"]

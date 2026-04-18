"""Bundle A — animation gaits shared types.

Provides the Keyframe dataclass used across all animation generators.
No Blender imports.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Keyframe:
    """A single animation keyframe value.

    frame: Timeline frame index.
    value: Channel value (radians, metres, or scale factor).
    channel: Data path type — 'location', 'rotation', or 'scale'.
    axis: Axis index 0=X, 1=Y, 2=Z.
    bone_name: Armature bone name for pose keyframes; empty for object-level.
    """

    frame: int
    value: float
    channel: str = "location"
    axis: int = 0
    bone_name: str = ""


__all__ = ["Keyframe"]

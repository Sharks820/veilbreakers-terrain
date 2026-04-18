"""Bundle A supplement — environmental/world animation generators.

27 animation types for dark fantasy game objects. Pure-logic: no Blender imports.
Doors/gates, fire/water/cloth physics, traps, interactables, ambient.
"""
from __future__ import annotations

import inspect
import math
from typing import Any, Dict, List

from .animation_gaits import Keyframe

VALID_ENV_TYPES: frozenset = frozenset({
    "door_open", "door_close", "door_slam", "door_creak",
    "gate_raise", "gate_lower", "drawbridge",
    "shatter", "wobble_collapse",
    "fire_flicker", "torch_sway",
    "water_wave", "water_ripple", "waterfall",
    "flag_wind", "banner_wind",
    "chain_swing", "rope_sway",
    "trap_trigger", "trap_reset", "trap_idle",
    "chest_open", "lever_pull", "switch_toggle",
    "candle_flicker", "chandelier_sway", "windmill_rotate",
})


def validate_env_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and fill defaults. Raises ValueError on missing name or bad type."""
    if "object_name" not in params:
        raise ValueError("params must include 'object_name'")
    out = dict(params)
    out.setdefault("env_type", "door_open")
    out.setdefault("frame_count", 30)
    out.setdefault("intensity", 1.0)
    if out["env_type"] not in VALID_ENV_TYPES:
        raise ValueError(
            f"unknown env_type: {out['env_type']!r}; "
            f"must be one of {sorted(VALID_ENV_TYPES)}"
        )
    return out


# ---------------------------------------------------------------------------
# Doors
# ---------------------------------------------------------------------------

def generate_door_open_keyframes(
    frame_count: int = 30,
    angle: float = 90.0,
) -> List[Keyframe]:
    target = math.radians(angle)
    fc = max(frame_count, 1)
    return [
        Keyframe(frame=f, value=target * (1.0 - (1.0 - f / fc) ** 3),
                 channel="rotation", axis=2)
        for f in range(0, frame_count + 1)
    ]


def generate_door_close_keyframes(
    frame_count: int = 30,
    angle: float = 90.0,
) -> List[Keyframe]:
    target = math.radians(angle)
    fc = max(frame_count, 1)
    return [
        Keyframe(frame=f, value=target * ((1.0 - f / fc) ** 3),
                 channel="rotation", axis=2)
        for f in range(0, frame_count + 1)
    ]


def generate_door_slam_keyframes(
    frame_count: int = 20,
    angle: float = 90.0,
) -> List[Keyframe]:
    target = math.radians(angle)
    snap = max(1, frame_count // 3)
    kfs: List[Keyframe] = []
    for f in range(0, snap + 1):
        kfs.append(Keyframe(frame=f, value=target * ((f / snap) ** 0.5),
                            channel="rotation", axis=2))
    kfs.append(Keyframe(frame=snap + 3, value=target + 0.12,
                        channel="rotation", axis=2))
    kfs.append(Keyframe(frame=frame_count, value=target,
                        channel="rotation", axis=2))
    return kfs


def generate_door_creak_keyframes(
    frame_count: int = 60,
    angle: float = 30.0,
) -> List[Keyframe]:
    target = math.radians(angle)
    stops = [max(1, frame_count // 6) * i for i in range(1, 6)] + [frame_count]
    kfs = [Keyframe(frame=0, value=0.0, channel="rotation", axis=2)]
    for i, stop in enumerate(stops):
        val = target * (i + 1) / len(stops)
        kfs.append(Keyframe(frame=stop, value=val, channel="rotation", axis=2))
        if stop < frame_count:
            kfs.append(Keyframe(frame=stop + 2, value=val, channel="rotation", axis=2))
    return kfs


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def generate_gate_raise_keyframes(
    frame_count: int = 60,
    height: float = 3.0,
    jerk: float = 0.05,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    for f in range(0, frame_count + 1):
        t = f / frame_count
        val = height * (1.0 - (1.0 - t) ** 2)
        if f % 15 == 5:
            val -= jerk
        kfs.append(Keyframe(frame=f, value=val, channel="location", axis=2))
    return kfs


def generate_gate_lower_keyframes(
    frame_count: int = 45,
    height: float = 3.0,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    for f in range(0, frame_count + 1):
        t = f / frame_count
        kfs.append(Keyframe(frame=f, value=height * (1.0 - t ** 0.8),
                            channel="location", axis=2))
    kfs.append(Keyframe(frame=frame_count + 3, value=-0.05,
                        channel="location", axis=2))
    kfs.append(Keyframe(frame=frame_count + 6, value=0.0,
                        channel="location", axis=2))
    return kfs


def generate_drawbridge_keyframes(
    frame_count: int = 90,
    angle: float = 90.0,
) -> List[Keyframe]:
    target = math.radians(angle)
    return [
        Keyframe(frame=f,
                 value=target * (3.0 * (f / frame_count) ** 2
                                 - 2.0 * (f / frame_count) ** 3),
                 channel="rotation", axis=0)
        for f in range(0, frame_count + 1)
    ]


# ---------------------------------------------------------------------------
# Destructibles
# ---------------------------------------------------------------------------

def generate_shatter_keyframes(frame_count: int = 20) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    for f in range(0, frame_count + 1):
        t = f / frame_count
        for axis in range(3):
            scale = 1.0 - 0.9 * t ** 0.5 + 0.1 * math.sin(t * math.pi * 4 + axis)
            kfs.append(Keyframe(frame=f, value=scale, channel="scale", axis=axis))
    return kfs


def generate_wobble_collapse_keyframes(frame_count: int = 30) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    pivot = max(1, frame_count // 2)
    for f in range(0, pivot):
        t = f / pivot
        kfs.append(Keyframe(frame=f,
                            value=0.1 * math.sin(t * math.pi * 6) * (1.0 - t),
                            channel="rotation", axis=1))
    for f in range(pivot, frame_count + 1):
        t = (f - pivot) / max(1, frame_count - pivot)
        kfs.append(Keyframe(frame=f, value=-math.pi / 2 * t ** 2,
                            channel="rotation", axis=1))
    return kfs


# ---------------------------------------------------------------------------
# Fire
# ---------------------------------------------------------------------------

def generate_fire_flicker_keyframes(
    frame_count: int = 24,
    intensity: float = 1.0,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    for f in range(0, frame_count + 1):
        t = f / max(frame_count, 1)
        sy = intensity * (1.0 + 0.3 * math.sin(t * math.pi * 6)
                          + 0.15 * math.sin(t * math.pi * 14))
        kfs.append(Keyframe(frame=f, value=sy, channel="scale", axis=1))
        sx = intensity * (1.0 + 0.1 * math.sin(t * math.pi * 9 + 0.5))
        kfs.append(Keyframe(frame=f, value=sx, channel="scale", axis=0))
        sway = 0.02 * intensity * math.sin(t * math.pi * 7 + 1.0)
        kfs.append(Keyframe(frame=f, value=sway, channel="location", axis=0))
    return kfs


def generate_torch_sway_keyframes(
    frame_count: int = 30,
    intensity: float = 1.0,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    for f in range(0, frame_count + 1):
        t = f / max(frame_count, 1)
        kfs.append(Keyframe(frame=f,
                            value=0.05 * intensity * math.sin(t * math.pi * 4),
                            channel="rotation", axis=0))
        kfs.append(Keyframe(frame=f,
                            value=1.0 + 0.2 * intensity * math.sin(t * math.pi * 8),
                            channel="scale", axis=1))
    return kfs


# ---------------------------------------------------------------------------
# Water
# ---------------------------------------------------------------------------

def generate_water_wave_keyframes(
    frame_count: int = 24,
    amplitude: float = 0.1,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    for f in range(0, frame_count + 1):
        t = f / max(frame_count, 1)
        kfs.append(Keyframe(frame=f, value=amplitude * math.sin(t * math.pi * 2),
                            channel="location", axis=2))
        kfs.append(Keyframe(frame=f, value=amplitude * 0.3 * math.sin(t * math.pi * 4),
                            channel="location", axis=0))
    return kfs


def generate_water_ripple_keyframes(
    frame_count: int = 20,
    amplitude: float = 0.05,
) -> List[Keyframe]:
    return [
        Keyframe(frame=f,
                 value=amplitude * math.exp(-3.0 * f / max(frame_count, 1))
                 * math.sin(f / max(frame_count, 1) * math.pi * 8),
                 channel="location", axis=2)
        for f in range(0, frame_count + 1)
    ]


def generate_waterfall_keyframes(
    frame_count: int = 30,
    amplitude: float = 0.08,
) -> List[Keyframe]:
    return [
        Keyframe(frame=f,
                 value=amplitude * (math.sin(f / max(frame_count, 1) * math.pi * 3)
                                    + 0.5 * math.sin(f / max(frame_count, 1) * math.pi * 7)),
                 channel="location", axis=2)
        for f in range(0, frame_count + 1)
    ]


# ---------------------------------------------------------------------------
# Cloth
# ---------------------------------------------------------------------------

def generate_flag_wind_keyframes(
    frame_count: int = 24,
    segments: int = 4,
    intensity: float = 1.0,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    bones = [f"flag_bone_{i}" for i in range(segments)]
    for f in range(0, frame_count + 1):
        t = f / max(frame_count, 1)
        for i, bone in enumerate(bones):
            phase = i * math.pi / segments
            val = 0.1 * intensity * math.sin(t * math.pi * 4 + phase) * (i + 1) / segments
            kfs.append(Keyframe(frame=f, value=val, channel="rotation",
                                axis=1, bone_name=bone))
    return kfs


def generate_banner_wind_keyframes(
    frame_count: int = 24,
    segments: int = 3,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    bones = [f"banner_bone_{i}" for i in range(segments)]
    for f in range(0, frame_count + 1):
        t = f / max(frame_count, 1)
        for i, bone in enumerate(bones):
            val = 0.08 * math.sin(t * math.pi * 5 + i * 0.8)
            kfs.append(Keyframe(frame=f, value=val, channel="rotation",
                                axis=1, bone_name=bone))
    return kfs


# ---------------------------------------------------------------------------
# Physics
# ---------------------------------------------------------------------------

def generate_chain_swing_keyframes(
    frame_count: int = 40,
    amplitude: float = 0.4,
) -> List[Keyframe]:
    return [
        Keyframe(frame=f,
                 value=amplitude * math.exp(-1.5 * f / max(frame_count, 1))
                 * math.sin(f / max(frame_count, 1) * math.pi * 4),
                 channel="rotation", axis=0)
        for f in range(0, frame_count + 1)
    ]


def generate_rope_sway_keyframes(
    frame_count: int = 40,
    amplitude: float = 0.3,
) -> List[Keyframe]:
    return [
        Keyframe(frame=f,
                 value=amplitude * math.sin(f / max(frame_count, 1) * math.pi * 3),
                 channel="rotation", axis=1)
        for f in range(0, frame_count + 1)
    ]


# ---------------------------------------------------------------------------
# Traps
# ---------------------------------------------------------------------------

def generate_trap_trigger_keyframes(
    frame_count: int = 12,
    angle: float = 45.0,
) -> List[Keyframe]:
    """Returns exactly frame_count + 1 keyframes (frames 0..frame_count)."""
    target = math.radians(angle)
    snap = max(1, frame_count // 4)
    kfs: List[Keyframe] = []
    for f in range(0, frame_count + 1):
        if f <= snap:
            val = target * (f / snap)
        else:
            t = (f - snap) / max(1, frame_count - snap)
            val = target * (1.0 + 0.2 * math.sin(t * math.pi * 3)
                            * math.exp(-3.0 * t))
        kfs.append(Keyframe(frame=f, value=val, channel="rotation", axis=2))
    return kfs


def generate_trap_reset_keyframes(
    frame_count: int = 20,
    angle: float = 45.0,
) -> List[Keyframe]:
    target = math.radians(angle)
    return [
        Keyframe(frame=f, value=target * (1.0 - f / frame_count),
                 channel="rotation", axis=2)
        for f in range(0, frame_count + 1)
    ]


def generate_trap_idle_keyframes(frame_count: int = 24) -> List[Keyframe]:
    return [
        Keyframe(frame=f,
                 value=0.005 * math.sin(f / max(frame_count, 1) * math.pi * 12),
                 channel="rotation", axis=2)
        for f in range(0, frame_count + 1)
    ]


# ---------------------------------------------------------------------------
# Interactables
# ---------------------------------------------------------------------------

def generate_chest_open_keyframes(
    frame_count: int = 30,
    angle: float = 110.0,
) -> List[Keyframe]:
    target = math.radians(angle)   # ~1.92 rad > 1.5
    kfs: List[Keyframe] = []
    for f in range(0, frame_count + 1):
        t = f / frame_count
        val = target * (1.0 - (1.0 - t) ** 3)
        if 0.4 < t < 0.8:
            val *= 1.05
        kfs.append(Keyframe(frame=f, value=val, channel="rotation", axis=0))
    return kfs


def generate_lever_pull_keyframes(
    frame_count: int = 15,
    angle: float = 60.0,
) -> List[Keyframe]:
    target = math.radians(angle)
    return [
        Keyframe(frame=f,
                 value=target * (3.0 * (f / frame_count) ** 2
                                 - 2.0 * (f / frame_count) ** 3),
                 channel="rotation", axis=0)
        for f in range(0, frame_count + 1)
    ]


def generate_switch_toggle_keyframes(
    frame_count: int = 8,
    angle: float = 30.0,
) -> List[Keyframe]:
    target = math.radians(angle)
    mid = max(1, frame_count // 2)
    return [
        Keyframe(frame=0, value=0.0, channel="rotation", axis=1),
        Keyframe(frame=mid, value=target * 1.1, channel="rotation", axis=1),
        Keyframe(frame=frame_count, value=target, channel="rotation", axis=1),
    ]


# ---------------------------------------------------------------------------
# Ambient
# ---------------------------------------------------------------------------

def generate_candle_flicker_keyframes(
    frame_count: int = 30,
    intensity: float = 1.0,
) -> List[Keyframe]:
    return [
        Keyframe(frame=f,
                 value=intensity * (0.9 + 0.2 * math.sin(f / max(frame_count, 1) * math.pi * 10)
                                    + 0.05 * math.sin(f / max(frame_count, 1) * math.pi * 27)),
                 channel="scale", axis=1)
        for f in range(0, frame_count + 1)
    ]


def generate_chandelier_sway_keyframes(
    frame_count: int = 60,
    amplitude: float = 0.05,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    for f in range(0, frame_count + 1):
        t = f / max(frame_count, 1)
        kfs.append(Keyframe(frame=f, value=amplitude * math.sin(t * math.pi * 2),
                            channel="rotation", axis=0))
        kfs.append(Keyframe(frame=f, value=amplitude * 0.5 * math.sin(t * math.pi * 3),
                            channel="rotation", axis=1))
    return kfs


def generate_windmill_rotate_keyframes(
    frame_count: int = 120,
    rotations: float = 1.0,
    speed: float = 1.0,
) -> List[Keyframe]:
    """Continuous rotation. At frame_count, value = 2π * rotations * speed."""
    total = 2.0 * math.pi * rotations * speed
    fc = max(frame_count, 1)
    return [
        Keyframe(frame=f, value=total * f / fc,
                 channel="rotation", axis=1)
        for f in range(0, frame_count + 1)
    ]


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_DISPATCH: Dict[str, Any] = {
    "door_open": generate_door_open_keyframes,
    "door_close": generate_door_close_keyframes,
    "door_slam": generate_door_slam_keyframes,
    "door_creak": generate_door_creak_keyframes,
    "gate_raise": generate_gate_raise_keyframes,
    "gate_lower": generate_gate_lower_keyframes,
    "drawbridge": generate_drawbridge_keyframes,
    "shatter": generate_shatter_keyframes,
    "wobble_collapse": generate_wobble_collapse_keyframes,
    "fire_flicker": generate_fire_flicker_keyframes,
    "torch_sway": generate_torch_sway_keyframes,
    "water_wave": generate_water_wave_keyframes,
    "water_ripple": generate_water_ripple_keyframes,
    "waterfall": generate_waterfall_keyframes,
    "flag_wind": generate_flag_wind_keyframes,
    "banner_wind": generate_banner_wind_keyframes,
    "chain_swing": generate_chain_swing_keyframes,
    "rope_sway": generate_rope_sway_keyframes,
    "trap_trigger": generate_trap_trigger_keyframes,
    "trap_reset": generate_trap_reset_keyframes,
    "trap_idle": generate_trap_idle_keyframes,
    "chest_open": generate_chest_open_keyframes,
    "lever_pull": generate_lever_pull_keyframes,
    "switch_toggle": generate_switch_toggle_keyframes,
    "candle_flicker": generate_candle_flicker_keyframes,
    "chandelier_sway": generate_chandelier_sway_keyframes,
    "windmill_rotate": generate_windmill_rotate_keyframes,
}


def generate_env_keyframes(params: Dict[str, Any]) -> List[Keyframe]:
    """Dispatch to the appropriate generator. Raises ValueError for unknown type."""
    env_type = params.get("env_type", "door_open")
    if env_type not in VALID_ENV_TYPES:
        raise ValueError(f"unknown env_type: {env_type!r}")
    fn = _DISPATCH[env_type]
    sig = inspect.signature(fn)
    kwargs = {k: v for k, v in params.items() if k in sig.parameters}
    return fn(**kwargs)


__all__ = [
    "VALID_ENV_TYPES",
    "validate_env_params",
    "generate_env_keyframes",
    "generate_door_open_keyframes",
    "generate_door_close_keyframes",
    "generate_door_slam_keyframes",
    "generate_door_creak_keyframes",
    "generate_gate_raise_keyframes",
    "generate_gate_lower_keyframes",
    "generate_drawbridge_keyframes",
    "generate_shatter_keyframes",
    "generate_wobble_collapse_keyframes",
    "generate_fire_flicker_keyframes",
    "generate_torch_sway_keyframes",
    "generate_water_wave_keyframes",
    "generate_water_ripple_keyframes",
    "generate_waterfall_keyframes",
    "generate_flag_wind_keyframes",
    "generate_banner_wind_keyframes",
    "generate_chain_swing_keyframes",
    "generate_rope_sway_keyframes",
    "generate_trap_trigger_keyframes",
    "generate_trap_reset_keyframes",
    "generate_trap_idle_keyframes",
    "generate_chest_open_keyframes",
    "generate_lever_pull_keyframes",
    "generate_switch_toggle_keyframes",
    "generate_candle_flicker_keyframes",
    "generate_chandelier_sway_keyframes",
    "generate_windmill_rotate_keyframes",
]

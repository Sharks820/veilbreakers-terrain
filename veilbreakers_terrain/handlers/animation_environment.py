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
    hinge_axis: int = 2,
    squeak_offset_frames: int = 2,
    num_stops: int = 5,
) -> List[Keyframe]:
    """Door creak — ease-in at start, ease-out at stop, micro-stall hesitations.

    Models a sticky hinge: the door accelerates briefly (ease-in cubic),
    then stalls at each hesitation point (duplicate value keyframe), then
    resumes.  The final key uses an ease-out so the door slows to its final
    angle.  ``squeak_offset_frames`` controls how many frames the door
    holds at each stall — matching how Unreal's door creak SFX aligns with
    the motion hold.

    Args:
        frame_count:           Total duration in frames.
        angle:                 Target opening angle in degrees.
        hinge_axis:            Blender rotation axis (0=X, 1=Y, 2=Z).
        squeak_offset_frames:  Hold duration at each stall (min 1).
        num_stops:             Number of hesitation stalls along the arc.
    """
    target = math.radians(angle)
    fc = max(frame_count, 1)
    squeak = max(1, squeak_offset_frames)
    stops = [max(1, fc // (num_stops + 1)) * i for i in range(1, num_stops + 1)] + [fc]

    kfs: List[Keyframe] = [Keyframe(frame=0, value=0.0, channel="rotation", axis=hinge_axis)]

    for i, stop in enumerate(stops):
        frac = (i + 1) / len(stops)
        # Ease-in cubic at start segment, ease-out cubic approaching final angle
        if i == 0:
            # ease-in: slow start, accelerate
            eased = frac ** 3
        elif i == len(stops) - 1:
            # ease-out: decelerate to target
            eased = 1.0 - (1.0 - frac) ** 3
        else:
            # smooth-step for mid-stalls
            eased = frac * frac * (3.0 - 2.0 * frac)
        val = target * eased

        # Arrive key
        kfs.append(Keyframe(frame=stop, value=val, channel="rotation", axis=hinge_axis))
        # Hold/stall: duplicate value = zero velocity = squeak moment
        if stop < fc:
            kfs.append(
                Keyframe(
                    frame=stop + squeak,
                    value=val,
                    channel="rotation",
                    axis=hinge_axis,
                )
            )
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

def generate_shatter_keyframes(
    frame_count: int = 20,
    num_shards: int = 6,
    impact_normal: tuple = (0.0, 0.0, 1.0),
    gravity: float = -9.81,
    sleep_threshold_velocity: float = 0.05,
    lod_visible_shards: int = 3,
) -> List[Keyframe]:
    """Shatter -- Voronoi shard trajectories with physics, angular velocity, LOD gating.

    Each shard gets a deterministic outward velocity (radially spread around
    the impact normal), angular velocity proportional to linear speed, parabolic
    gravity, and a sleep keyframe once velocity drops below
    sleep_threshold_velocity.

    LOD-gated visibility: only the first lod_visible_shards shards start
    at scale=1. The rest begin at scale=0 -- LOD0 enables them when close enough.

    Physics matches UE5 Chaos Destruction at medium quality: parabolic
    trajectory, exponentially decaying angular spin, hard sleep threshold.
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    n = max(1, num_shards)

    # Normalise impact normal
    nx, ny, nz = impact_normal
    nlen = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    nx, ny, nz = nx / nlen, ny / nlen, nz / nlen

    for shard_idx in range(n):
        spread_angle = 2.0 * math.pi * shard_idx / n
        tx = math.cos(spread_angle)
        ty = math.sin(spread_angle)
        speed = 0.4 + 0.6 * ((shard_idx % 3) + 1) / 3.0
        vx = (0.6 * nx + 0.4 * tx) * speed
        vy = (0.6 * ny + 0.4 * ty) * speed
        vz = 0.6 * nz * speed

        ang_vel = speed * 0.3 * (1.0 + (shard_idx % 2) * 0.5)

        lod_scale = 1.0 if shard_idx < lod_visible_shards else 0.0
        for axis in range(3):
            kfs.append(Keyframe(frame=0, value=lod_scale, channel="scale", axis=axis))

        sleep_frame = fc + 1
        for f in range(1, fc + 1):
            t = f / fc
            pz = vz * t + 0.5 * gravity * (t ** 2) * 0.01
            px = vx * t
            py = vy * t

            vz_now = vz + gravity * t * 0.01
            cur_speed = math.sqrt(vx * vx + vy * vy + vz_now * vz_now)

            if cur_speed < sleep_threshold_velocity and f < sleep_frame:
                sleep_frame = f

            kfs.append(Keyframe(frame=f, value=px, channel="location", axis=0))
            kfs.append(Keyframe(frame=f, value=py, channel="location", axis=1))
            kfs.append(Keyframe(frame=f, value=pz, channel="location", axis=2))

            rot = ang_vel * t * math.exp(-2.0 * t)
            kfs.append(Keyframe(frame=f, value=rot, channel="rotation", axis=shard_idx % 3))

            if f >= sleep_frame:
                for axis in range(3):
                    kfs.append(Keyframe(frame=f, value=lod_scale, channel="scale", axis=axis))

    return kfs


def generate_wobble_collapse_keyframes(
    frame_count: int = 30,
    num_pieces: int = 1,
    damping_ratio: float = 0.3,
    omega_0_hz: float = 3.0,
) -> List[Keyframe]:
    """Wobble collapse -- underdamped harmonic oscillation then per-mass collapse delay.

    Phase 1 (first half): underdamped SHM: x(t) = A*exp(-zeta*w0*t)*cos(wd*t).
    Phase 2 (second half): collapse with delay proportional to piece index
    (heavier/later pieces delay longer before falling).

    Args:
        frame_count:    Total duration in frames.
        num_pieces:     Number of structural pieces to animate (each on axis=1).
        damping_ratio:  zeta < 1 = underdamped; 0.3 gives visible oscillation.
        omega_0_hz:     Natural frequency in Hz (scaled to frame_count).
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    pivot = max(1, fc // 2)
    n = max(1, num_pieces)
    zeta = max(0.01, min(0.99, damping_ratio))
    w0 = abs(omega_0_hz) * 2.0 * math.pi / fc
    wd = w0 * math.sqrt(1.0 - zeta * zeta)

    for piece_idx in range(n):
        mass = max(0.1, 1.0 - piece_idx / max(n, 1) * 0.6)
        amplitude = 0.12 / mass

        for f in range(0, pivot):
            wobble = amplitude * math.exp(-zeta * w0 * f) * math.cos(wd * f)
            kfs.append(Keyframe(frame=f, value=wobble, channel="rotation", axis=1))

        collapse_delay = int(mass * (fc - pivot) * 0.4)
        collapse_start = pivot + collapse_delay
        for f in range(pivot, fc + 1):
            if f < collapse_start:
                kfs.append(Keyframe(frame=f, value=0.0, channel="rotation", axis=1))
            else:
                t = (f - collapse_start) / max(1, fc - collapse_start)
                fall_angle = -math.pi / 2 * t ** 2
                kfs.append(Keyframe(frame=f, value=fall_angle, channel="rotation", axis=1))

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
    wave_direction: float = 0.0,
    water_depth_m: float = 2.0,
) -> List[Keyframe]:
    """Water waves -- sinusoidal displacement with foam crest keys.

    Uses shallow water wave model: c = sqrt(g * d).
    Foam crest keys (scale axis 0) are emitted at wave peaks.
    wave_direction rotates horizontal drift components.
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    g = 9.81
    depth = max(0.1, water_depth_m)
    phase_speed = math.sqrt(g * depth)
    freq = 2.0 * math.pi / fc
    dx = math.cos(wave_direction)
    dz = math.sin(wave_direction)

    for f in range(0, frame_count + 1):
        t = f / fc
        phase = freq * f
        disp = amplitude * math.sin(phase)
        horiz = amplitude * 0.3 * math.cos(phase) * phase_speed * 0.01

        kfs.append(Keyframe(frame=f, value=disp, channel="location", axis=2))
        kfs.append(Keyframe(frame=f, value=horiz * dx, channel="location", axis=0))
        kfs.append(Keyframe(frame=f, value=horiz * dz, channel="location", axis=1))

        # Foam crest: signal to particle system when wave is at peak
        foam_val = max(0.0, (disp / amplitude - 0.7) / 0.3) if amplitude > 0 else 0.0
        kfs.append(Keyframe(frame=f, value=foam_val, channel="scale", axis=0))

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
    flow_volume: float = 1.0,
) -> List[Keyframe]:
    """Waterfall -- particle emission rate keys, mist density, foam spawn rate.

    Emits three scale channels keyed to flow_volume:
    - scale axis 0: particle emission rate (proportional to flow_volume)
    - scale axis 1: mist density (rises with flow)
    - scale axis 2: foam spawn rate (proportional to flow_volume^2)

    Matches Unreal Niagara waterfall setups where VFX modules are driven
    by scalar float tracks set from the animation curve.
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    fv = max(0.0, float(flow_volume))

    for f in range(0, frame_count + 1):
        t = f / fc
        disp = amplitude * (math.sin(t * math.pi * 3) + 0.5 * math.sin(t * math.pi * 7))
        kfs.append(Keyframe(frame=f, value=disp, channel="location", axis=2))

        emission_rate = fv * (0.7 + 0.3 * math.sin(t * math.pi * 2))
        kfs.append(Keyframe(frame=f, value=emission_rate, channel="scale", axis=0))

        mist = fv * 0.5 * (1.0 + math.sin(t * math.pi * 1.5)) * 0.8
        kfs.append(Keyframe(frame=f, value=mist, channel="scale", axis=1))

        foam = (fv ** 2) * (0.5 + 0.5 * math.sin(t * math.pi * 4))
        kfs.append(Keyframe(frame=f, value=foam, channel="scale", axis=2))

    return kfs


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
    segments: int = 4,
    wind_response: float = 0.0,
    damping: float = 0.05,
) -> List[Keyframe]:
    """Rope sway -- catenary rest shape, pendulum oscillation, wind response.

    Each segment gets its own bone keyframe. Rest shape follows catenary sag.
    Tip segments oscillate at higher natural frequency (shorter effective length).
    Wind response keys (scale axis 0) let callers drive a wind force parameter.
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    n = max(1, segments)
    bones = [f"rope_bone_{i}" for i in range(n)]
    catenary_sag_total = 0.15

    for seg_i, bone in enumerate(bones):
        rest_angle = catenary_sag_total * (seg_i + 1) / n
        effective_length_frac = max(0.1, 1.0 - seg_i / (n * 2.0))
        nat_freq = 2.0 * math.pi * (1.0 / (fc * effective_length_frac))
        wind_amp = wind_response * (seg_i + 1) / n

        for f in range(0, fc + 1):
            t = f / fc
            decay = math.exp(-damping * f)
            swing = amplitude * decay * math.sin(nat_freq * f)
            wind_drift = wind_amp * math.sin(t * math.pi * 0.7)
            kfs.append(
                Keyframe(frame=f, value=rest_angle + swing + wind_drift,
                         channel="rotation", axis=1, bone_name=bone)
            )
            if seg_i == 0:
                kfs.append(
                    Keyframe(frame=f, value=1.0 + wind_amp * math.sin(t * math.pi),
                             channel="scale", axis=0)
                )

    return kfs


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
    spring_compression_frames: int = 3,
    sound_cue_offset_frames: int = 1,
) -> List[Keyframe]:
    """Trap reset -- spring-load compression, trigger release, ease-back, sound cue.

    Phase 1 (spring_compression_frames): trap compresses slightly past origin
    (spring being re-loaded under tension, 8% overshoot).
    Phase 2: cubic ease-out from triggered angle back to 0.
    Sound cue: scale axis 2 = 1.0 key at release click moment (for SFX trigger).

    Matches Unity Animator: sound cue is a scale key queried by a MonoBehaviour.
    """
    target = math.radians(angle)
    fc = max(frame_count, 1)
    compress = max(1, spring_compression_frames)
    cue_frame = compress + max(0, sound_cue_offset_frames)

    kfs: List[Keyframe] = []

    # Phase 1: spring compression overshoot
    compression_overshoot = target * 0.08
    for f in range(0, compress + 1):
        t = f / compress
        val = target + compression_overshoot * math.sin(t * math.pi)
        kfs.append(Keyframe(frame=f, value=val, channel="rotation", axis=2))

    # Sound cue at release point
    if cue_frame <= fc:
        kfs.append(Keyframe(frame=cue_frame, value=0.0, channel="scale", axis=2))
        kfs.append(Keyframe(frame=cue_frame, value=1.0, channel="scale", axis=2))

    # Phase 2: cubic ease-out back to rest
    release_start = compress
    release_frames = max(1, fc - release_start)
    for f in range(release_start, fc + 1):
        t = (f - release_start) / release_frames
        eased = 1.0 - (1.0 - t) ** 3
        val = target * (1.0 - eased)
        kfs.append(Keyframe(frame=f, value=val, channel="rotation", axis=2))

    return kfs


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

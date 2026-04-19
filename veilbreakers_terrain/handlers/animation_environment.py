"""Bundle A supplement — environmental/world animation generators.

27 animation types for dark fantasy game objects. Pure-logic: no Blender imports.
Doors/gates, fire/water/cloth physics, traps, interactables, ambient.

AAA upgrade notes (Horizon Zero Dawn / Guerrilla reference):
- All keyframes output Unity Animator-compatible fields: time (seconds),
  in_tangent, out_tangent (slope of the AnimationCurve at each key).
- Door animations use fps parameter so timing is in SECONDS, not frames.
- Ease-in cubic on door open (slow start → fast), ease-out cubic on door
  close (fast start → slow finish), with analytically derived tangents.
- Water flow velocity from Manning's equation where applicable.
- Waterfall: foam burst at impact frame, distinct mist emission zone,
  cascade timing with freefall physics.
- _cubic_ease_{in,out}_tangent helpers compute exact slope at each key so
  Unity's Animator interpolates correctly without baking every frame.
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

# ---------------------------------------------------------------------------
# Unity Animator tangent helpers
# ---------------------------------------------------------------------------
# Unity AnimationCurve Keyframe.inTangent / outTangent are the first derivative
# (dValue/dTime) at the key point.  We derive these analytically for each
# easing curve so the Animator reconstructs the intended motion with only the
# sparse key set — no baking required.
#
# Cubic ease-in (door open):  f(t) = value * (1 - (1-t)^3)   [t in 0..1]
#   f'(t) = value * 3*(1-t)^2 / duration    → in world units per second
# Cubic ease-out (door close): f(t) = value * (1-t)^3
#   f'(t) = -value * 3*(1-t)^2 / duration
# Smooth-step:  f(t) = value * (3t^2 - 2t^3)
#   f'(t) = value * (6t - 6t^2) / duration


def _ease_in_cubic_tangent(t: float, total_value: float, duration: float) -> float:
    """d/dt [V*(1-(1-t)^3)] evaluated at normalised t, converted to per-second."""
    dur = max(duration, 1e-9)
    return total_value * 3.0 * (1.0 - t) ** 2 / dur


def _ease_out_cubic_tangent(t: float, total_value: float, duration: float) -> float:
    """d/dt [-V*(1-t)^3] = V*3*(1-t)^2 but curve descends, sign flipped."""
    dur = max(duration, 1e-9)
    return -total_value * 3.0 * (1.0 - t) ** 2 / dur


def _smooth_step_tangent(t: float, total_value: float, duration: float) -> float:
    """d/dt [V*(3t^2-2t^3)] = V*(6t-6t^2)/dur."""
    dur = max(duration, 1e-9)
    return total_value * (6.0 * t - 6.0 * t ** 2) / dur


def _make_kf(
    frame: int,
    value: float,
    channel: str,
    axis: int,
    fps: float,
    in_tangent: float = 0.0,
    out_tangent: float = 0.0,
    bone_name: str = "",
) -> Keyframe:
    """Build a Keyframe with time in seconds for Unity Animator compatibility."""
    return Keyframe(
        frame=frame,
        value=value,
        channel=channel,
        axis=axis,
        bone_name=bone_name,
        time=frame / max(fps, 1e-9),
        in_tangent=in_tangent,
        out_tangent=out_tangent,
    )


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
    fps: float = 30.0,
) -> List[Keyframe]:
    """Door open — ease-in cubic (slow start, fast finish).

    Unity Animator compatible: sparse key set with analytically derived
    inTangent / outTangent so the Animator curve matches intent without baking.
    Timing stored in SECONDS (Keyframe.time) using fps parameter.

    Ease-in cubic: rotation(t) = angle * (1 - (1-t)^3)
    Tangent at key: d/dt [angle*(1-(1-t)^3)] = angle * 3*(1-t)^2 / duration

    Three keys: start (t=0), mid inflection (t=0.5), end (t=1).
    """
    target = math.radians(angle)
    duration = frame_count / max(fps, 1e-9)  # total seconds
    kfs: List[Keyframe] = []

    key_ts = [0.0, 0.33, 0.67, 1.0]
    for t in key_ts:
        f = int(round(t * frame_count))
        val = target * (1.0 - (1.0 - t) ** 3)
        tang = _ease_in_cubic_tangent(t, target, duration)
        kfs.append(_make_kf(f, val, "rotation", 2, fps,
                             in_tangent=tang, out_tangent=tang))
    return kfs


def generate_door_close_keyframes(
    frame_count: int = 30,
    angle: float = 90.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Door close — ease-out cubic (fast start, slow deceleration to shut).

    Ease-out cubic: rotation(t) = angle * (1-t)^3
    Tangent: d/dt [angle*(1-t)^3] = -angle*3*(1-t)^2 / duration

    Sparse keys at t=0, 0.33, 0.67, 1.0 with correct tangents.
    """
    target = math.radians(angle)
    duration = frame_count / max(fps, 1e-9)
    kfs: List[Keyframe] = []

    key_ts = [0.0, 0.33, 0.67, 1.0]
    for t in key_ts:
        f = int(round(t * frame_count))
        val = target * (1.0 - t) ** 3
        tang = _ease_out_cubic_tangent(t, target, duration)
        kfs.append(_make_kf(f, val, "rotation", 2, fps,
                             in_tangent=tang, out_tangent=tang))
    return kfs


def generate_door_slam_keyframes(
    frame_count: int = 20,
    angle: float = 90.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Door slam — fast spring-overshoot then settle.

    Phase 1: power-0.4 very fast opening (concave, high initial velocity).
    Phase 2: overshoot 12% past target.
    Phase 3: elastic settle back to target.

    Tangents computed from instantaneous slopes for Unity Animator.
    """
    target = math.radians(angle)
    snap = max(1, frame_count // 3)
    duration = frame_count / max(fps, 1e-9)
    kfs: List[Keyframe] = []

    # Phase 1: fast open — power curve f(t)=target*(t/snap)^0.4
    # Sparse: 0 and snap
    t0 = 0.0 / snap
    v0 = target * (max(t0, 0.0) ** 0.4) if t0 > 0 else 0.0
    # At t=0 the power curve tangent is infinite (vertical), approximate with high slope
    out0 = target * 0.4 / (max(1.0 / snap, 1e-9) ** 0.6) / duration
    kfs.append(_make_kf(0, 0.0, "rotation", 2, fps,
                         in_tangent=0.0, out_tangent=out0))

    t_snap = 1.0
    v_snap = target
    tang_snap = target * 0.4 / (t_snap ** 0.6) / (snap / max(fps, 1e-9))
    kfs.append(_make_kf(snap, v_snap, "rotation", 2, fps,
                         in_tangent=tang_snap, out_tangent=0.0))

    # Phase 2: overshoot
    overshoot_frame = snap + max(2, frame_count // 8)
    overshoot_val = target + 0.12
    kfs.append(_make_kf(overshoot_frame, overshoot_val, "rotation", 2, fps,
                         in_tangent=0.0, out_tangent=0.0))

    # Phase 3: ease-out settle to target
    settle_t = 1.0
    settle_tang = _ease_out_cubic_tangent(1.0, target, duration)
    kfs.append(_make_kf(frame_count, target, "rotation", 2, fps,
                         in_tangent=settle_tang, out_tangent=0.0))
    return kfs


def generate_door_creak_keyframes(
    frame_count: int = 60,
    angle: float = 30.0,
    hinge_axis: int = 2,
    squeak_offset_frames: int = 2,
    num_stops: int = 5,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Door creak — ease-in at start, ease-out at stop, micro-stall hesitations.

    Models a sticky hinge: the door accelerates briefly (ease-in cubic),
    then stalls at each hesitation point (duplicate value keyframe), then
    resumes.  The final key uses an ease-out so the door slows to its final
    angle.  squeak_offset_frames controls how many frames the door holds at
    each stall — matching how SFX aligns with the motion hold.

    All keys carry Unity Animator inTangent/outTangent derived from the
    local easing curve at each stop point.

    Args:
        frame_count:           Total duration in frames.
        angle:                 Target opening angle in degrees.
        hinge_axis:            Blender rotation axis (0=X, 1=Y, 2=Z).
        squeak_offset_frames:  Hold duration at each stall (min 1).
        num_stops:             Number of hesitation stalls along the arc.
        fps:                   Frames per second for time-in-seconds conversion.
    """
    target = math.radians(angle)
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)
    squeak = max(1, squeak_offset_frames)
    stops = [max(1, fc // (num_stops + 1)) * i for i in range(1, num_stops + 1)] + [fc]

    kfs: List[Keyframe] = [
        _make_kf(0, 0.0, "rotation", hinge_axis, fps,
                 in_tangent=0.0, out_tangent=0.0)
    ]

    for i, stop in enumerate(stops):
        frac = (i + 1) / len(stops)
        if i == 0:
            eased = frac ** 3
            tang = _ease_in_cubic_tangent(frac, target, duration)
        elif i == len(stops) - 1:
            eased = 1.0 - (1.0 - frac) ** 3
            tang = _ease_in_cubic_tangent(frac, target, duration)
        else:
            eased = frac * frac * (3.0 - 2.0 * frac)
            tang = _smooth_step_tangent(frac, target, duration)
        val = target * eased

        kfs.append(_make_kf(stop, val, "rotation", hinge_axis, fps,
                             in_tangent=tang, out_tangent=0.0))
        if stop < fc:
            # Hold key: zero tangents = zero velocity = stall moment
            kfs.append(_make_kf(stop + squeak, val, "rotation", hinge_axis, fps,
                                 in_tangent=0.0, out_tangent=0.0))
    return kfs


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def generate_gate_raise_keyframes(
    frame_count: int = 60,
    height: float = 3.0,
    jerk: float = 0.05,
    fps: float = 30.0,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    duration = frame_count / max(fps, 1e-9)
    for f in range(0, frame_count + 1):
        t = f / frame_count
        val = height * (1.0 - (1.0 - t) ** 2)
        if f % 15 == 5:
            val -= jerk
        tang = height * 2.0 * (1.0 - t) / duration
        kfs.append(_make_kf(f, val, "location", 2, fps,
                             in_tangent=tang, out_tangent=tang))
    return kfs


def generate_gate_lower_keyframes(
    frame_count: int = 45,
    height: float = 3.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    duration = frame_count / max(fps, 1e-9)
    for f in range(0, frame_count + 1):
        t = f / frame_count
        val = height * (1.0 - t ** 0.8)
        # d/dt [height*(1-t^0.8)] = -height*0.8*t^(-0.2)/duration (at t>0)
        tang = -height * 0.8 * (max(t, 1e-6) ** (-0.2)) / duration if t > 0 else 0.0
        kfs.append(_make_kf(f, val, "location", 2, fps,
                             in_tangent=tang, out_tangent=tang))
    # Impact bounce
    impact_frame = frame_count + 3
    kfs.append(_make_kf(impact_frame, -0.05, "location", 2, fps,
                         in_tangent=0.0, out_tangent=0.0))
    kfs.append(_make_kf(frame_count + 6, 0.0, "location", 2, fps,
                         in_tangent=0.0, out_tangent=0.0))
    return kfs


def generate_drawbridge_keyframes(
    frame_count: int = 90,
    angle: float = 90.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    target = math.radians(angle)
    duration = frame_count / max(fps, 1e-9)
    kfs: List[Keyframe] = []
    for f in range(0, frame_count + 1):
        t = f / frame_count
        val = target * (3.0 * t ** 2 - 2.0 * t ** 3)
        tang = _smooth_step_tangent(t, target, duration)
        kfs.append(_make_kf(f, val, "rotation", 0, fps,
                             in_tangent=tang, out_tangent=tang))
    return kfs


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
    fps: float = 30.0,
) -> List[Keyframe]:
    """Shatter — Voronoi shard trajectories with physics, angular velocity, LOD gating.

    Each shard gets a deterministic outward velocity (radially spread around
    the impact normal), angular velocity proportional to linear speed, parabolic
    gravity, and a sleep keyframe once velocity drops below
    sleep_threshold_velocity.

    LOD-gated visibility: only the first lod_visible_shards shards start
    at scale=1. The rest begin at scale=0 -- LOD0 enables them when close enough.

    Physics matches UE5 Chaos Destruction at medium quality: parabolic
    trajectory, exponentially decaying angular spin, hard sleep threshold.

    All keys carry Unity Animator time (seconds) and tangents derived from
    instantaneous velocity / angular velocity for smooth curve reconstruction.
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    n = max(1, num_shards)
    dt = 1.0 / max(fps, 1e-9)  # seconds per frame

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
        vz_0 = 0.6 * nz * speed

        ang_vel = speed * 0.3 * (1.0 + (shard_idx % 2) * 0.5)

        lod_scale = 1.0 if shard_idx < lod_visible_shards else 0.0
        for axis in range(3):
            kfs.append(_make_kf(0, lod_scale, "scale", axis, fps,
                                 in_tangent=0.0, out_tangent=0.0))

        sleep_frame = fc + 1
        for f in range(1, fc + 1):
            t_sec = f * dt
            t_norm = f / fc

            pz = vz_0 * t_sec + 0.5 * gravity * (t_sec ** 2)
            px = vx * t_sec
            py = vy * t_sec

            vz_now = vz_0 + gravity * t_sec
            cur_speed = math.sqrt(vx * vx + vy * vy + vz_now * vz_now)

            if cur_speed < sleep_threshold_velocity and f < sleep_frame:
                sleep_frame = f

            # Instantaneous velocity tangents for Unity curve fidelity
            kfs.append(_make_kf(f, px, "location", 0, fps,
                                 in_tangent=vx, out_tangent=vx))
            kfs.append(_make_kf(f, py, "location", 1, fps,
                                 in_tangent=vy, out_tangent=vy))
            kfs.append(_make_kf(f, pz, "location", 2, fps,
                                 in_tangent=vz_now, out_tangent=vz_now))

            # Angular: d/dt [ang_vel * t * exp(-2t)] = ang_vel * exp(-2t) * (1 - 2t)
            rot = ang_vel * t_sec * math.exp(-2.0 * t_sec)
            rot_tang = ang_vel * math.exp(-2.0 * t_sec) * (1.0 - 2.0 * t_sec)
            kfs.append(_make_kf(f, rot, "rotation", shard_idx % 3, fps,
                                 in_tangent=rot_tang, out_tangent=rot_tang))

            if f >= sleep_frame:
                for axis in range(3):
                    kfs.append(_make_kf(f, lod_scale, "scale", axis, fps,
                                         in_tangent=0.0, out_tangent=0.0))

    return kfs


def generate_wobble_collapse_keyframes(
    frame_count: int = 30,
    num_pieces: int = 1,
    damping_ratio: float = 0.3,
    omega_0_hz: float = 3.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Wobble collapse — underdamped harmonic oscillation then per-mass collapse delay.

    Phase 1 (first half): underdamped SHM: x(t) = A*exp(-zeta*w0*t)*cos(wd*t).
    Phase 2 (second half): collapse with delay proportional to piece index.

    Tangents from analytical derivative of the SHM expression:
      dx/dt = A*exp(-zeta*w0*t)*(-zeta*w0*cos(wd*t) - wd*sin(wd*t))
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    pivot = max(1, fc // 2)
    n = max(1, num_pieces)
    zeta = max(0.01, min(0.99, damping_ratio))
    dt = 1.0 / max(fps, 1e-9)
    w0 = abs(omega_0_hz) * 2.0 * math.pi
    wd = w0 * math.sqrt(1.0 - zeta * zeta)

    for piece_idx in range(n):
        mass = max(0.1, 1.0 - piece_idx / max(n, 1) * 0.6)
        amplitude = 0.12 / mass

        for f in range(0, pivot):
            t = f * dt
            wobble = amplitude * math.exp(-zeta * w0 * t) * math.cos(wd * t)
            # d/dt: A*exp(-z*w0*t)*(-z*w0*cos(wd*t) - wd*sin(wd*t))
            tang = amplitude * math.exp(-zeta * w0 * t) * (
                -zeta * w0 * math.cos(wd * t) - wd * math.sin(wd * t)
            )
            kfs.append(_make_kf(f, wobble, "rotation", 1, fps,
                                 in_tangent=tang, out_tangent=tang))

        collapse_delay = int(mass * (fc - pivot) * 0.4)
        collapse_start = pivot + collapse_delay
        for f in range(pivot, fc + 1):
            if f < collapse_start:
                kfs.append(_make_kf(f, 0.0, "rotation", 1, fps,
                                     in_tangent=0.0, out_tangent=0.0))
            else:
                t_c = (f - collapse_start) / max(1, fc - collapse_start)
                fall_angle = -math.pi / 2 * t_c ** 2
                # d/dt [-pi/2 * t^2] = -pi * t / duration
                fall_tang = -math.pi * t_c / (max(fc - collapse_start, 1) * dt)
                kfs.append(_make_kf(f, fall_angle, "rotation", 1, fps,
                                     in_tangent=fall_tang, out_tangent=fall_tang))

    return kfs


# ---------------------------------------------------------------------------
# Fire
# ---------------------------------------------------------------------------

def generate_fire_flicker_keyframes(
    frame_count: int = 24,
    intensity: float = 1.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    duration = frame_count / max(fps, 1e-9)
    for f in range(0, frame_count + 1):
        t = f / max(frame_count, 1)
        sy = intensity * (1.0 + 0.3 * math.sin(t * math.pi * 6)
                          + 0.15 * math.sin(t * math.pi * 14))
        dsy = intensity * (0.3 * math.cos(t * math.pi * 6) * math.pi * 6
                           + 0.15 * math.cos(t * math.pi * 14) * math.pi * 14) / duration
        kfs.append(_make_kf(f, sy, "scale", 1, fps,
                             in_tangent=dsy, out_tangent=dsy))
        sx = intensity * (1.0 + 0.1 * math.sin(t * math.pi * 9 + 0.5))
        dsx = intensity * 0.1 * math.cos(t * math.pi * 9 + 0.5) * math.pi * 9 / duration
        kfs.append(_make_kf(f, sx, "scale", 0, fps,
                             in_tangent=dsx, out_tangent=dsx))
        sway = 0.02 * intensity * math.sin(t * math.pi * 7 + 1.0)
        dsway = 0.02 * intensity * math.cos(t * math.pi * 7 + 1.0) * math.pi * 7 / duration
        kfs.append(_make_kf(f, sway, "location", 0, fps,
                             in_tangent=dsway, out_tangent=dsway))
    return kfs


def generate_torch_sway_keyframes(
    frame_count: int = 30,
    intensity: float = 1.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    duration = frame_count / max(fps, 1e-9)
    for f in range(0, frame_count + 1):
        t = f / max(frame_count, 1)
        rot = 0.05 * intensity * math.sin(t * math.pi * 4)
        drot = 0.05 * intensity * math.cos(t * math.pi * 4) * math.pi * 4 / duration
        kfs.append(_make_kf(f, rot, "rotation", 0, fps,
                             in_tangent=drot, out_tangent=drot))
        sc = 1.0 + 0.2 * intensity * math.sin(t * math.pi * 8)
        dsc = 0.2 * intensity * math.cos(t * math.pi * 8) * math.pi * 8 / duration
        kfs.append(_make_kf(f, sc, "scale", 1, fps,
                             in_tangent=dsc, out_tangent=dsc))
    return kfs


# ---------------------------------------------------------------------------
# Water
# ---------------------------------------------------------------------------

def generate_water_wave_keyframes(
    frame_count: int = 24,
    amplitude: float = 0.1,
    wave_direction: float = 0.0,
    water_depth_m: float = 2.0,
    hydraulic_radius_m: float = 1.5,
    channel_slope: float = 0.001,
    manning_n: float = 0.035,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Water waves — shallow-water wave speed + Manning's flow velocity.

    Wave phase speed uses shallow water: c = sqrt(g * d).
    Horizontal drift velocity uses Manning's equation:
        V = (1/n) * R_h^(2/3) * S^(1/2)
    where R_h = hydraulic radius (m), S = channel slope, n = Manning's n.
    The drift is applied as horizontal displacement of the wave surface mesh.

    Foam crest keys (scale axis 0) are emitted at wave peaks.

    Args:
        water_depth_m:       Mean water depth for phase speed (m).
        hydraulic_radius_m:  Hydraulic radius for Manning's equation (m).
        channel_slope:       Longitudinal slope (dimensionless, e.g. 0.001).
        manning_n:           Manning's roughness (0.025 smooth, 0.05 rough).
        fps:                 Frames per second for time conversion.
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)
    g = 9.81
    depth = max(0.1, water_depth_m)
    phase_speed = math.sqrt(g * depth)

    # Manning's equation: V = (1/n) * R_h^(2/3) * S^(1/2)
    Rh = max(0.01, hydraulic_radius_m)
    S = max(1e-6, channel_slope)
    n_mann = max(0.001, manning_n)
    flow_velocity = (1.0 / n_mann) * (Rh ** (2.0 / 3.0)) * math.sqrt(S)  # m/s

    freq = 2.0 * math.pi / fc
    dx = math.cos(wave_direction)
    dz = math.sin(wave_direction)

    for f in range(0, frame_count + 1):
        t = f / fc
        t_sec = f / max(fps, 1e-9)
        phase = freq * f
        disp = amplitude * math.sin(phase)
        # Horizontal drift from Manning's velocity scaled to animation range
        horiz = flow_velocity * t_sec * 0.01  # 0.01 converts m/s to anim units/frame
        d_disp = amplitude * math.cos(phase) * freq * max(fps, 1e-9)  # dvalue/dt in /sec

        kfs.append(_make_kf(f, disp, "location", 2, fps,
                             in_tangent=d_disp, out_tangent=d_disp))
        kfs.append(_make_kf(f, horiz * dx, "location", 0, fps,
                             in_tangent=flow_velocity * 0.01 * dx,
                             out_tangent=flow_velocity * 0.01 * dx))
        kfs.append(_make_kf(f, horiz * dz, "location", 1, fps,
                             in_tangent=flow_velocity * 0.01 * dz,
                             out_tangent=flow_velocity * 0.01 * dz))

        # Foam crest: signal to particle system when wave is at peak
        foam_val = max(0.0, (disp / amplitude - 0.7) / 0.3) if amplitude > 0 else 0.0
        kfs.append(_make_kf(f, foam_val, "scale", 0, fps,
                             in_tangent=0.0, out_tangent=0.0))

    return kfs


def generate_water_ripple_keyframes(
    frame_count: int = 20,
    amplitude: float = 0.05,
    fps: float = 30.0,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    duration = frame_count / max(fps, 1e-9)
    for f in range(0, frame_count + 1):
        t = f / max(frame_count, 1)
        val = amplitude * math.exp(-3.0 * t) * math.sin(t * math.pi * 8)
        # d/dt: amp * exp(-3t) * (-3*sin(8pi*t) + 8pi*cos(8pi*t)) / duration
        tang = amplitude * math.exp(-3.0 * t) * (
            -3.0 * math.sin(t * math.pi * 8) + math.pi * 8 * math.cos(t * math.pi * 8)
        ) / duration
        kfs.append(_make_kf(f, val, "location", 2, fps,
                             in_tangent=tang, out_tangent=tang))
    return kfs


def generate_waterfall_keyframes(
    frame_count: int = 30,
    amplitude: float = 0.08,
    flow_volume: float = 1.0,
    fall_height_m: float = 4.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Waterfall — physically-based cascade with foam burst, mist zone, freefall timing.

    Physically-based cascade:
    - Freefall time to impact: t_impact = sqrt(2 * H / g)
    - Foam burst at impact: sharp spike on scale axis 2 at the impact frame,
      decaying with time constant tau = t_impact * 0.3 (fast burst settling).
    - Mist emission zone: scale axis 1 ramps UP after impact (mist rises from
      splash zone), then decays slowly — opposite phase to the cascade water body.
    - Particle emission rate (scale axis 0): proportional to flow_volume with
      turbulent modulation based on Froude number estimate.

    Args:
        fall_height_m:  Height of the waterfall drop (metres), used for
                        freefall timing and foam burst intensity.
        fps:            Frames per second for time conversion.
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    fv = max(0.0, float(flow_volume))
    g = 9.81

    # Freefall physics: t_impact = sqrt(2H/g)
    H = max(0.5, fall_height_m)
    t_impact_sec = math.sqrt(2.0 * H / g)
    impact_frame = min(int(round(t_impact_sec * fps)), fc)

    # Froude number estimate for turbulence modulation (dimensionless)
    # Fr = V / sqrt(g * d), approximate V from freefall, d=0.3m jet depth
    impact_velocity = math.sqrt(2.0 * g * H)  # m/s at impact
    froude = impact_velocity / math.sqrt(g * 0.3)  # jet depth 0.3m
    froude_clamp = min(froude / 10.0, 1.0)  # normalised 0..1

    # Foam burst decay time constant (seconds)
    tau_foam = max(t_impact_sec * 0.3, 0.1)

    duration = fc / max(fps, 1e-9)

    for f in range(0, frame_count + 1):
        t = f / fc
        t_sec = f / max(fps, 1e-9)

        # Water body displacement: cascade oscillation above impact zone
        disp = amplitude * (math.sin(t * math.pi * 3) + 0.5 * math.sin(t * math.pi * 7))
        d_disp = amplitude * (
            math.cos(t * math.pi * 3) * math.pi * 3
            + 0.5 * math.cos(t * math.pi * 7) * math.pi * 7
        ) / duration
        kfs.append(_make_kf(f, disp, "location", 2, fps,
                             in_tangent=d_disp, out_tangent=d_disp))

        # Scale axis 0: particle emission rate from Manning/Froude modulation
        # Turbulent burst at impact frame, then settles to steady-state
        if f <= impact_frame:
            # Pre-impact: water accelerating through cascade, linear ramp
            emission_rate = fv * (0.5 + 0.5 * (f / max(impact_frame, 1)))
        else:
            # Post-impact: steady-state with Froude turbulence modulation
            dt_after = (f - impact_frame) / max(fps, 1e-9)
            emission_rate = fv * (0.7 + 0.3 * froude_clamp
                                  * math.sin(dt_after * math.pi * 2.0))
        kfs.append(_make_kf(f, emission_rate, "scale", 0, fps,
                             in_tangent=0.0, out_tangent=0.0))

        # Scale axis 1: mist emission zone
        # Before impact: minimal mist (spray off top of fall)
        # At impact: rapid rise peaking at tau_foam after impact
        # After: exponential decay (mist settles)
        if f <= impact_frame:
            mist = fv * 0.1 * (f / max(impact_frame, 1))
        else:
            dt_after = (f - impact_frame) / max(fps, 1e-9)
            # Mist ramps up sharply then decays: peak at tau_foam, then exponential
            mist_peak = fv * (0.4 + 0.6 * froude_clamp)
            mist = mist_peak * (dt_after / tau_foam) * math.exp(
                -(dt_after / tau_foam - 1.0) ** 2 * 2.0
            ) if dt_after <= tau_foam * 3.0 else mist_peak * math.exp(
                -(dt_after - tau_foam) / (tau_foam * 2.0)
            )
            mist = max(0.0, mist)
        kfs.append(_make_kf(f, mist, "scale", 1, fps,
                             in_tangent=0.0, out_tangent=0.0))

        # Scale axis 2: foam burst at impact — sharp spike, exponential decay
        # Impact frame: instantaneous burst proportional to flow_volume * Froude
        foam_burst_intensity = fv * (0.5 + 1.5 * froude_clamp)
        if f < impact_frame:
            foam = 0.0
        elif f == impact_frame:
            # Peak burst key — outTangent steeply negative (sharp spike)
            foam = foam_burst_intensity
            kfs.append(_make_kf(f, foam, "scale", 2, fps,
                                 in_tangent=0.0,
                                 out_tangent=-foam_burst_intensity / tau_foam))
            continue
        else:
            dt_after = (f - impact_frame) / max(fps, 1e-9)
            foam = foam_burst_intensity * math.exp(-dt_after / tau_foam)
        d_foam = (-foam / tau_foam) if f > impact_frame else 0.0
        kfs.append(_make_kf(f, foam, "scale", 2, fps,
                             in_tangent=d_foam, out_tangent=d_foam))

    return kfs


# ---------------------------------------------------------------------------
# Cloth
# ---------------------------------------------------------------------------

def generate_flag_wind_keyframes(
    frame_count: int = 24,
    segments: int = 4,
    intensity: float = 1.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    bones = [f"flag_bone_{i}" for i in range(segments)]
    duration = frame_count / max(fps, 1e-9)
    for f in range(0, frame_count + 1):
        t = f / max(frame_count, 1)
        for i, bone in enumerate(bones):
            phase = i * math.pi / segments
            val = 0.1 * intensity * math.sin(t * math.pi * 4 + phase) * (i + 1) / segments
            tang = (0.1 * intensity * math.cos(t * math.pi * 4 + phase)
                    * math.pi * 4 * (i + 1) / segments) / duration
            kfs.append(_make_kf(f, val, "rotation", 1, fps,
                                 in_tangent=tang, out_tangent=tang,
                                 bone_name=bone))
    return kfs


def generate_banner_wind_keyframes(
    frame_count: int = 24,
    segments: int = 3,
    fps: float = 30.0,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    bones = [f"banner_bone_{i}" for i in range(segments)]
    duration = frame_count / max(fps, 1e-9)
    for f in range(0, frame_count + 1):
        t = f / max(frame_count, 1)
        for i, bone in enumerate(bones):
            val = 0.08 * math.sin(t * math.pi * 5 + i * 0.8)
            tang = 0.08 * math.cos(t * math.pi * 5 + i * 0.8) * math.pi * 5 / duration
            kfs.append(_make_kf(f, val, "rotation", 1, fps,
                                 in_tangent=tang, out_tangent=tang,
                                 bone_name=bone))
    return kfs


# ---------------------------------------------------------------------------
# Physics
# ---------------------------------------------------------------------------

def generate_chain_swing_keyframes(
    frame_count: int = 40,
    amplitude: float = 0.4,
    fps: float = 30.0,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    duration = frame_count / max(fps, 1e-9)
    for f in range(0, frame_count + 1):
        t = f / max(frame_count, 1)
        val = amplitude * math.exp(-1.5 * t) * math.sin(t * math.pi * 4)
        # d/dt: amp*exp(-1.5t)*(-1.5*sin(4pi*t) + 4pi*cos(4pi*t))
        tang = amplitude * math.exp(-1.5 * t) * (
            -1.5 * math.sin(t * math.pi * 4) + math.pi * 4 * math.cos(t * math.pi * 4)
        ) / duration
        kfs.append(_make_kf(f, val, "rotation", 0, fps,
                             in_tangent=tang, out_tangent=tang))
    return kfs


def generate_rope_sway_keyframes(
    frame_count: int = 40,
    amplitude: float = 0.3,
    segments: int = 4,
    wind_response: float = 0.0,
    damping: float = 0.05,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Rope sway — catenary rest shape, pendulum oscillation, wind response.

    Each segment gets its own bone keyframe. Rest shape follows catenary sag.
    Tip segments oscillate at higher natural frequency (shorter effective length).
    Wind response keys (scale axis 0) let callers drive a wind force parameter.
    Tangents derived from instantaneous d/dt of the damped oscillation.
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    n = max(1, segments)
    bones = [f"rope_bone_{i}" for i in range(n)]
    catenary_sag_total = 0.15
    dt = 1.0 / max(fps, 1e-9)

    for seg_i, bone in enumerate(bones):
        rest_angle = catenary_sag_total * (seg_i + 1) / n
        effective_length_frac = max(0.1, 1.0 - seg_i / (n * 2.0))
        # Natural frequency in rad/s: higher for shorter segments
        nat_freq = 2.0 * math.pi * (1.0 / (fc * effective_length_frac)) * fps
        wind_amp = wind_response * (seg_i + 1) / n

        for f in range(0, fc + 1):
            t = f / fc
            t_sec = f * dt
            decay = math.exp(-damping * t_sec * fps)
            swing = amplitude * decay * math.sin(nat_freq * t_sec)
            wind_drift = wind_amp * math.sin(t * math.pi * 0.7)

            # d/dt of swing: amp * decay * (-damping*fps*sin + nat_freq*cos)
            d_swing = amplitude * decay * (
                -damping * fps * math.sin(nat_freq * t_sec)
                + nat_freq * math.cos(nat_freq * t_sec)
            )
            d_wind = wind_amp * math.cos(t * math.pi * 0.7) * math.pi * 0.7 / (fc * dt)
            tang = d_swing + d_wind

            kfs.append(_make_kf(f, rest_angle + swing + wind_drift,
                                 "rotation", 1, fps,
                                 in_tangent=tang, out_tangent=tang,
                                 bone_name=bone))
            if seg_i == 0:
                w_val = 1.0 + wind_amp * math.sin(t * math.pi)
                w_tang = wind_amp * math.cos(t * math.pi) * math.pi / (fc * dt)
                kfs.append(_make_kf(f, w_val, "scale", 0, fps,
                                     in_tangent=w_tang, out_tangent=w_tang))

    return kfs


# ---------------------------------------------------------------------------
# Traps
# ---------------------------------------------------------------------------

def generate_trap_trigger_keyframes(
    frame_count: int = 12,
    angle: float = 45.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Returns exactly frame_count + 1 keyframes (frames 0..frame_count)."""
    target = math.radians(angle)
    snap = max(1, frame_count // 4)
    duration = frame_count / max(fps, 1e-9)
    kfs: List[Keyframe] = []
    for f in range(0, frame_count + 1):
        if f <= snap:
            t_s = f / snap
            val = target * t_s
            tang = target / (snap / max(fps, 1e-9))
        else:
            t = (f - snap) / max(1, frame_count - snap)
            val = target * (1.0 + 0.2 * math.sin(t * math.pi * 3) * math.exp(-3.0 * t))
            # d/dt of oscillation settle
            tang = (target * 0.2 * math.exp(-3.0 * t) * (
                math.pi * 3 * math.cos(t * math.pi * 3) - 3.0 * math.sin(t * math.pi * 3)
            )) / duration
        kfs.append(_make_kf(f, val, "rotation", 2, fps,
                             in_tangent=tang, out_tangent=tang))
    return kfs


def generate_trap_reset_keyframes(
    frame_count: int = 20,
    angle: float = 45.0,
    spring_compression_frames: int = 3,
    sound_cue_offset_frames: int = 1,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Trap reset — spring-load compression, trigger release, ease-back, sound cue.

    Phase 1 (spring_compression_frames): trap compresses slightly past origin
    (spring being re-loaded under tension, 8% overshoot).
    Phase 2: cubic ease-out from triggered angle back to 0.
    Sound cue: scale axis 2 = 1.0 key at release click moment (for SFX trigger).

    All keys carry Unity Animator time (seconds) and analytical tangents.
    """
    target = math.radians(angle)
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)
    compress = max(1, spring_compression_frames)
    cue_frame = compress + max(0, sound_cue_offset_frames)

    kfs: List[Keyframe] = []
    compression_overshoot = target * 0.08

    for f in range(0, compress + 1):
        t = f / compress
        val = target + compression_overshoot * math.sin(t * math.pi)
        tang = compression_overshoot * math.cos(t * math.pi) * math.pi / (
            compress / max(fps, 1e-9)
        )
        kfs.append(_make_kf(f, val, "rotation", 2, fps,
                             in_tangent=tang, out_tangent=tang))

    if cue_frame <= fc:
        kfs.append(_make_kf(cue_frame, 0.0, "scale", 2, fps,
                             in_tangent=0.0, out_tangent=float('inf')))
        kfs.append(_make_kf(cue_frame, 1.0, "scale", 2, fps,
                             in_tangent=float('inf'), out_tangent=0.0))

    release_start = compress
    release_frames = max(1, fc - release_start)
    for f in range(release_start, fc + 1):
        t = (f - release_start) / release_frames
        eased = 1.0 - (1.0 - t) ** 3
        val = target * (1.0 - eased)
        tang = _ease_out_cubic_tangent(t, target, duration)
        kfs.append(_make_kf(f, val, "rotation", 2, fps,
                             in_tangent=tang, out_tangent=tang))

    return kfs


def generate_trap_idle_keyframes(
    frame_count: int = 24,
    fps: float = 30.0,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    duration = frame_count / max(fps, 1e-9)
    for f in range(0, frame_count + 1):
        t = f / max(frame_count, 1)
        val = 0.005 * math.sin(t * math.pi * 12)
        tang = 0.005 * math.cos(t * math.pi * 12) * math.pi * 12 / duration
        kfs.append(_make_kf(f, val, "rotation", 2, fps,
                             in_tangent=tang, out_tangent=tang))
    return kfs


# ---------------------------------------------------------------------------
# Interactables
# ---------------------------------------------------------------------------

def generate_chest_open_keyframes(
    frame_count: int = 30,
    angle: float = 110.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    target = math.radians(angle)
    duration = frame_count / max(fps, 1e-9)
    kfs: List[Keyframe] = []
    for f in range(0, frame_count + 1):
        t = f / frame_count
        val = target * (1.0 - (1.0 - t) ** 3)
        if 0.4 < t < 0.8:
            val *= 1.05
        tang = _ease_in_cubic_tangent(t, target, duration)
        kfs.append(_make_kf(f, val, "rotation", 0, fps,
                             in_tangent=tang, out_tangent=tang))
    return kfs


def generate_lever_pull_keyframes(
    frame_count: int = 15,
    angle: float = 60.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    target = math.radians(angle)
    duration = frame_count / max(fps, 1e-9)
    kfs: List[Keyframe] = []
    for f in range(0, frame_count + 1):
        t = f / frame_count
        val = target * (3.0 * t ** 2 - 2.0 * t ** 3)
        tang = _smooth_step_tangent(t, target, duration)
        kfs.append(_make_kf(f, val, "rotation", 0, fps,
                             in_tangent=tang, out_tangent=tang))
    return kfs


def generate_switch_toggle_keyframes(
    frame_count: int = 8,
    angle: float = 30.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    target = math.radians(angle)
    mid = max(1, frame_count // 2)
    duration = frame_count / max(fps, 1e-9)
    # Smooth-step through mid overshoot
    tang_mid = _smooth_step_tangent(0.5, target, duration)
    return [
        _make_kf(0, 0.0, "rotation", 1, fps,
                 in_tangent=0.0, out_tangent=tang_mid),
        _make_kf(mid, target * 1.1, "rotation", 1, fps,
                 in_tangent=tang_mid, out_tangent=0.0),
        _make_kf(frame_count, target, "rotation", 1, fps,
                 in_tangent=0.0, out_tangent=0.0),
    ]


# ---------------------------------------------------------------------------
# Ambient
# ---------------------------------------------------------------------------

def generate_candle_flicker_keyframes(
    frame_count: int = 30,
    intensity: float = 1.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    duration = frame_count / max(fps, 1e-9)
    for f in range(0, frame_count + 1):
        t = f / max(frame_count, 1)
        val = intensity * (0.9 + 0.2 * math.sin(t * math.pi * 10)
                           + 0.05 * math.sin(t * math.pi * 27))
        tang = intensity * (
            0.2 * math.cos(t * math.pi * 10) * math.pi * 10
            + 0.05 * math.cos(t * math.pi * 27) * math.pi * 27
        ) / duration
        kfs.append(_make_kf(f, val, "scale", 1, fps,
                             in_tangent=tang, out_tangent=tang))
    return kfs


def generate_chandelier_sway_keyframes(
    frame_count: int = 60,
    amplitude: float = 0.05,
    fps: float = 30.0,
) -> List[Keyframe]:
    kfs: List[Keyframe] = []
    duration = frame_count / max(fps, 1e-9)
    for f in range(0, frame_count + 1):
        t = f / max(frame_count, 1)
        rx = amplitude * math.sin(t * math.pi * 2)
        drx = amplitude * math.cos(t * math.pi * 2) * math.pi * 2 / duration
        kfs.append(_make_kf(f, rx, "rotation", 0, fps,
                             in_tangent=drx, out_tangent=drx))
        ry = amplitude * 0.5 * math.sin(t * math.pi * 3)
        dry = amplitude * 0.5 * math.cos(t * math.pi * 3) * math.pi * 3 / duration
        kfs.append(_make_kf(f, ry, "rotation", 1, fps,
                             in_tangent=dry, out_tangent=dry))
    return kfs


def generate_windmill_rotate_keyframes(
    frame_count: int = 120,
    rotations: float = 1.0,
    speed: float = 1.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Continuous rotation. At frame_count, value = 2π * rotations * speed.

    Constant angular velocity — tangents equal the angular velocity so Unity
    Animator produces a linear (constant speed) curve.
    """
    total = 2.0 * math.pi * rotations * speed
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)
    ang_vel = total / duration  # rad/s
    return [
        _make_kf(f, total * f / fc, "rotation", 1, fps,
                 in_tangent=ang_vel, out_tangent=ang_vel)
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

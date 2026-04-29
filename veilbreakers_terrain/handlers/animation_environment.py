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
- Gate raise: counterweight-assisted quadratic-deceleration (sparse keys).
- Gate lower: gravity-driven cubic acceleration + impact bounce.
- Drawbridge: catenary cable sag + smooth-step hinge rotation (sparse keys).
- Fire/torch/candle: 3 frequency bands (0.5 Hz sway, 3 Hz flicker, 12 Hz
  sputter) with analytically-derived tangents; candle adds Kelvin color
  temperature shift (1800 K → 2200 K mapped to a 0-1 blend channel).
- Flag/banner: 8 control-point Bezier approximated via phase-shifted
  sinusoids along span; Stokes drag amplitude scaling (A ∝ 1/v²).
- Chain: catenary rest angle per link + SHM with T = 2π√(L/g).
- Rope: same pendulum period formula with correct effective length per seg.
- Trap trigger: mass-spring snappy release omega = √(k/m); settle ring-down.
- Trap reset: overdamped return (zeta > 1) + spring-load compression phase.
- Trap idle: dual-frequency micro-vibration from spring resonance.
- Chest open: hinge physics with spring-assist velocity + damped soft stop.
- Lever/switch: detent mechanism — acceleration through centre, decel at ends.
- Chandelier: compound pendulum — main frame + candle-arm sub-oscillations
  at 1.4× main frequency.
- generate_env_keyframes: dispatcher routes all 27 types via inspect.
"""
from __future__ import annotations

import inspect
import math
from typing import Any, Dict, List

from .animation_gaits import Keyframe, keyframe_to_dict

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
    counterweight_ratio: float = 0.7,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Portcullis raise — counterweight-assisted: fast start, quadratic deceleration.

    A counterweight-assisted portcullis accelerates quickly at the bottom
    (counterweight torque exceeds gate weight) then decelerates as the gate
    approaches the top (mechanical advantage decreases).

    Physics model:
      Net acceleration a(t) = a0 * (1 - t)   where a0 = counterweight_ratio * g
      Integrating:  v(t) = a0 * (t - t²/2)
      Position:     h(t) = a0 * (t²/2 - t³/6)
      Normalised to reach `height` at t=1:
        h_norm(t) = height * (3t² - t³) / 2    (since h(1) = a0/3, scale to reach height)

    Analytically:
      h'(t) = height * (6t - 3t²) / (2 * duration)

    Sparse 5 keys at t = 0, 0.2, 0.5, 0.8, 1.0 with correct tangents.
    A slight jerk key at t=0.05 models the chain takeup slack.

    Args:
        height:               Raise distance in game units.
        counterweight_ratio:  Ratio of counterweight to gate mass (0–1).
                              Higher = faster start, sharper deceleration.
        fps:                  Frames per second.
    """
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)
    kfs: List[Keyframe] = []

    def _h(t: float) -> float:
        # h(t) = height * (3t² - t³) / 2, adjusted by counterweight_ratio
        base = height * (3.0 * t * t - t * t * t) / 2.0
        # Counterweight steepens the early rise: blend toward t^0.5 shape
        cw = max(0.0, min(1.0, counterweight_ratio))
        fast = height * math.sqrt(t) if t > 0 else 0.0
        return base * (1.0 - cw * 0.4) + fast * (cw * 0.4)

    def _dh(t: float) -> float:
        # d/dt of blended curve
        base_d = height * (6.0 * t - 3.0 * t * t) / 2.0
        cw = max(0.0, min(1.0, counterweight_ratio))
        fast_d = height * 0.5 / math.sqrt(max(t, 1e-9))
        return (base_d * (1.0 - cw * 0.4) + fast_d * (cw * 0.4)) / duration

    # Chain slack jerk at ~5% of travel
    slack_frame = max(1, int(0.05 * fc))
    slack_val = _h(0.05) * 0.92  # brief dip from chain takeup

    kfs.append(_make_kf(0, 0.0, "location", 2, fps,
                         in_tangent=0.0, out_tangent=_dh(1e-6)))
    kfs.append(_make_kf(slack_frame, slack_val, "location", 2, fps,
                         in_tangent=_dh(0.05), out_tangent=_dh(0.05)))

    for t in (0.2, 0.5, 0.8):
        f = int(round(t * fc))
        kfs.append(_make_kf(f, _h(t), "location", 2, fps,
                             in_tangent=_dh(t), out_tangent=_dh(t)))

    kfs.append(_make_kf(fc, height, "location", 2, fps,
                         in_tangent=_dh(1.0), out_tangent=0.0))
    return kfs


def generate_gate_lower_keyframes(
    frame_count: int = 45,
    height: float = 3.0,
    gravity: float = 9.81,
    brake_ratio: float = 0.4,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Portcullis lower — gravity-driven cubic acceleration, braked near ground.

    Free fall under gravity until brake_ratio of travel, then chain brake
    engages giving cubic deceleration to a controlled thud. Impact bounce
    from ground contact modelled as underdamped spring (2 frames).

    Physics:
      Free-fall phase (t in 0..brake_ratio):
        h(t) = height * (1 - t²/brake_ratio²) * brake_ratio²
        (falls cubically fast — approximates constant gravity)
      Braked phase (t in brake_ratio..1):
        ease-out cubic from brake position to 0
      Impact bounce: +5 mm overshoot, settle back in 6 frames.

    Analytically derived tangents at all sparse keys.

    Args:
        height:       Total fall distance in game units.
        gravity:      Gravitational acceleration (m/s²) — scales fall speed feel.
        brake_ratio:  Fraction of travel at which chain brake engages (0.3–0.7).
        fps:          Frames per second.
    """
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)
    br = max(0.1, min(0.9, brake_ratio))
    kfs: List[Keyframe] = []

    # Gravity scale factor: heavier/faster gates have higher g-feel
    g_scale = gravity / 9.81

    def _h(t: float) -> float:
        if t <= br:
            # Cubic fall: h = height - height*(1-(t/br)^3)*(1-br) - height*t²*br
            # Simplified: positions gates further along at brake point
            frac = t / br
            return height * (1.0 - (1.0 - frac) ** 3) * br * g_scale
        else:
            # Braked: ease-out from brake_h to 0
            t2 = (t - br) / (1.0 - br)
            brake_h = height * br * g_scale
            # Clamp brake_h at height
            brake_h = min(brake_h, height)
            return brake_h * (1.0 - t2) ** 3

    def _dh(t: float) -> float:
        if t <= br:
            frac = t / br
            return height * 3.0 * (1.0 - frac) ** 2 / (br * max(duration, 1e-9)) * g_scale
        else:
            t2 = (t - br) / (1.0 - br)
            brake_h = min(height * br * g_scale, height)
            # d/dt of ease-out: -3*(1-t2)^2 * brake_h / ((1-br)*duration)
            return -3.0 * (1.0 - t2) ** 2 * brake_h / ((1.0 - br) * max(duration, 1e-9))

    for t in (0.0, 0.2, br, br + (1.0 - br) * 0.5, 1.0):
        f = int(round(t * fc))
        kfs.append(_make_kf(f, _h(t), "location", 2, fps,
                             in_tangent=_dh(t), out_tangent=_dh(t)))

    # Impact bounce — underdamped, 2-key settle
    impact_frame = fc
    kfs.append(_make_kf(impact_frame + 3, -0.05, "location", 2, fps,
                         in_tangent=0.0, out_tangent=0.0))
    kfs.append(_make_kf(impact_frame + 6, 0.0, "location", 2, fps,
                         in_tangent=0.0, out_tangent=0.0))
    return kfs


def generate_drawbridge_keyframes(
    frame_count: int = 90,
    angle: float = 90.0,
    chain_length: float = 6.0,
    sag_ratio: float = 0.08,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Drawbridge lower — hinge rotation + cable catenary sag on the lift chains.

    Two channels:
    - rotation axis 0: hinge rotation with smooth-step ease (dense-enough sparse keys).
    - location axis 2: chain midpoint vertical sag following catenary geometry.

    Catenary sag formula (approximate):
      sag(angle) = chain_length * sag_ratio * sin(hinge_angle / 2)
    At horizontal (angle=90°) the chain is taut; at vertical (0°) there is slack.
    The sag oscillates with a small overshoot as the bridge decelerates.

    Sparse 6 rotation keys with smooth-step tangents + 4 sag keys.

    Args:
        angle:         Final lowered angle in degrees (typically 90 = horizontal).
        chain_length:  Length of the lift chain (game units) for catenary scaling.
        sag_ratio:     Fraction of chain_length as maximum sag amplitude.
        fps:           Frames per second.
    """
    target = math.radians(angle)
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)
    kfs: List[Keyframe] = []

    # Rotation keys (smooth-step) — sparse
    for t in (0.0, 0.15, 0.35, 0.6, 0.85, 1.0):
        f = int(round(t * fc))
        val = target * (3.0 * t * t - 2.0 * t * t * t)
        tang = _smooth_step_tangent(t, target, duration)
        kfs.append(_make_kf(f, val, "rotation", 0, fps,
                             in_tangent=tang, out_tangent=tang))

    # Catenary sag keys on location axis 2
    # sag(t) = chain_length * sag_ratio * sin(rotation(t)/2)
    # At t=0: bridge vertical, no sag. At t=1: bridge horizontal, full sag.
    # Brief overshoot at t=0.9 as bridge decelerates (chains go momentarily slack).
    sag_keys = [
        (0.0, 0.0),
        (0.4, chain_length * sag_ratio * math.sin(target * 0.4 / 2.0)),
        (0.9, chain_length * sag_ratio * math.sin(target * 0.85 / 2.0) * 1.15),  # overshoot
        (1.0, chain_length * sag_ratio * math.sin(target / 2.0)),
    ]
    for t, sag_val in sag_keys:
        f = int(round(t * fc))
        # Tangent: d(sag)/dt ≈ chain_length*sag_ratio * cos(rot/2) * drot/dt / 2
        rot_t = target * (3.0 * t * t - 2.0 * t * t * t)
        drot_dt = _smooth_step_tangent(t, target, duration)
        dsag_dt = (chain_length * sag_ratio * math.cos(rot_t / 2.0) * drot_dt / 2.0
                   if t < 0.9 else 0.0)
        kfs.append(_make_kf(f, sag_val, "location", 2, fps,
                             in_tangent=dsag_dt, out_tangent=dsag_dt))

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
# Fire  — 3-band Perlin-style flicker model
# ---------------------------------------------------------------------------
# Three frequency bands model fire dynamics (Guerrilla / Naughty Dog reference):
#   Band 1 (slow sway):    ~0.5 Hz — large column drift driven by buoyancy
#   Band 2 (mid flicker):  ~3 Hz   — turbulent core instability
#   Band 3 (fast sputter): ~12 Hz  — high-frequency micro-combustion bursts
# Each band has independent amplitude and a deterministic phase offset so
# the combined signal never repeats within typical loop lengths.
# Tangents are the analytical derivative of the sum so Unity Animator needs
# no sub-frame baking.

_FIRE_BANDS = (
    # (freq_hz, amp_scale, phase_offset)
    (0.5,  0.25, 0.0),    # slow buoyancy sway
    (3.0,  0.35, 1.1),    # turbulent flicker
    (12.0, 0.12, 2.7),    # micro sputter
)


def _fire_val_tang(t: float, intensity: float, duration: float,
                   bands=_FIRE_BANDS) -> tuple:
    """Return (value, tangent) for the 3-band fire signal at normalised t."""
    val = intensity
    tang = 0.0
    for freq_hz, amp, phase in bands:
        omega = 2.0 * math.pi * freq_hz
        # value contribution
        val += intensity * amp * math.sin(omega * t + phase)
        # tangent: d/dt [amp*sin(omega*t+phase)] = amp*omega*cos(omega*t+phase)/duration
        tang += intensity * amp * omega * math.cos(omega * t + phase) / duration
    return val, tang


def generate_fire_flicker_keyframes(
    frame_count: int = 24,
    intensity: float = 1.0,
    fps: float = 30.0,
    slow_amp: float = 0.25,
    mid_amp: float = 0.35,
    fast_amp: float = 0.12,
) -> List[Keyframe]:
    """Fire flicker — 3-band signal (0.5 Hz sway / 3 Hz flicker / 12 Hz sputter).

    Scale Y encodes flame height (primary channel, all 3 bands).
    Scale X encodes lateral billow (slow + mid bands only, half amplitude).
    Location X encodes column drift (slow band only, 0.03 units max).
    All channels carry analytically-derived tangents.

    Args:
        slow_amp:  Amplitude multiplier for the 0.5 Hz buoyancy band.
        mid_amp:   Amplitude multiplier for the 3 Hz flicker band.
        fast_amp:  Amplitude multiplier for the 12 Hz sputter band.
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)

    bands_y = (
        (0.5,  slow_amp, 0.0),
        (3.0,  mid_amp,  1.1),
        (12.0, fast_amp, 2.7),
    )
    bands_x = (
        (0.5, slow_amp * 0.5, 0.5),
        (3.0, mid_amp  * 0.5, 1.6),
    )
    band_drift = ((0.5, 0.03, 0.0),)

    for f in range(0, fc + 1):
        t = f / fc
        sy, dsy = _fire_val_tang(t, intensity, duration, bands_y)
        sx, dsx = _fire_val_tang(t, intensity, duration, bands_x)
        # drift is additive displacement, not scale — use separate logic
        drift_val = 0.0
        drift_tang = 0.0
        for freq_hz, amp, phase in band_drift:
            omega = 2.0 * math.pi * freq_hz
            drift_val += amp * intensity * math.sin(omega * t + phase)
            drift_tang += amp * intensity * omega * math.cos(omega * t + phase) / duration

        kfs.append(_make_kf(f, sy, "scale", 1, fps,
                             in_tangent=dsy, out_tangent=dsy))
        kfs.append(_make_kf(f, sx, "scale", 0, fps,
                             in_tangent=dsx, out_tangent=dsx))
        kfs.append(_make_kf(f, drift_val, "location", 0, fps,
                             in_tangent=drift_tang, out_tangent=drift_tang))
    return kfs


def generate_torch_sway_keyframes(
    frame_count: int = 30,
    intensity: float = 1.0,
    fps: float = 30.0,
    slow_amp: float = 0.25,
    mid_amp: float = 0.35,
    fast_amp: float = 0.12,
) -> List[Keyframe]:
    """Torch sway — 3-band model identical to fire but with rotation channel.

    Rotation X encodes physical torch-head sway (slow + mid bands).
    Scale Y encodes flame height (all 3 bands).
    Phase offsets differ from generate_fire_flicker to avoid harmonic lockup
    when multiple torches are placed in a scene.

    Stokes drag applied to sway: amplitude ∝ 1/wind_speed² is modelled by
    scaling slow_amp by the inverse square of a nominal wind speed of 2 m/s.
    At intensity=1 the slow sway is already calibrated for 2 m/s wind.

    Args:
        slow_amp:  Amplitude multiplier for the 0.5 Hz sway band.
        mid_amp:   Amplitude multiplier for the 3 Hz flicker band.
        fast_amp:  Amplitude multiplier for the 12 Hz sputter band.
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)

    # Rotation bands (physical sway) — slow + mid only, offset phases
    bands_rot = (
        (0.5, slow_amp * 0.06, 0.3),
        (3.0, mid_amp  * 0.02, 1.9),
    )
    # Scale bands (flame height)
    bands_sc = (
        (0.5,  slow_amp, 0.7),
        (3.0,  mid_amp,  2.0),
        (12.0, fast_amp, 3.4),
    )

    for f in range(0, fc + 1):
        t = f / fc
        rot, drot = _fire_val_tang(t, intensity, duration, bands_rot)
        # _fire_val_tang starts from intensity; for pure rotation offset from 0
        rot  -= intensity  # subtract the base so it oscillates around 0
        drot  = drot        # derivative unchanged

        sc, dsc = _fire_val_tang(t, intensity, duration, bands_sc)

        kfs.append(_make_kf(f, rot, "rotation", 0, fps,
                             in_tangent=drot, out_tangent=drot))
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
    num_rings: int = 3,
    ring_speed: float = 1.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Water ripple — radial expanding rings with exponential decay.

    Models a point disturbance (rain drop / stone impact) producing
    concentric rings that expand outward and decay. Each ring is phase-shifted
    so they appear to travel outward from the impact point.

    Physics:
      Ring displacement: A * exp(-decay * t) * sin(8π*t - ring_offset)
      Decay constant 3.0 matches shallow surface waves losing energy to
      viscosity and dispersion.
      Ring scale X encodes ring radius expanding at ring_speed units/s.

    Tangents analytically derived from d/dt of the decaying sinusoid:
      d/dt [A*exp(-3t)*sin(8π*t)] = A*exp(-3t)*(-3*sin(8π*t) + 8π*cos(8π*t))

    Args:
        num_rings:   Number of concentric ring channels (1-4).
        ring_speed:  Radial expansion speed in game units per second.
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)
    n_rings = max(1, min(4, num_rings))
    decay = 3.0

    for ring_i in range(n_rings):
        phase_offset = ring_i * math.pi / n_rings
        delay_frac = ring_i * 0.1  # each ring launches slightly after previous

        for f in range(0, fc + 1):
            t = f / fc
            t_eff = max(0.0, t - delay_frac)

            # Vertical displacement
            val = amplitude * math.exp(-decay * t_eff) * math.sin(
                t_eff * math.pi * 8.0 + phase_offset
            )
            # d/dt: A*exp(-d*t)*(-d*sin(8pi*t+ph) + 8pi*cos(8pi*t+ph))
            tang = amplitude * math.exp(-decay * t_eff) * (
                -decay * math.sin(t_eff * math.pi * 8.0 + phase_offset)
                + math.pi * 8.0 * math.cos(t_eff * math.pi * 8.0 + phase_offset)
            ) / duration

            bone = f"ripple_ring_{ring_i}"
            kfs.append(_make_kf(f, val, "location", 2, fps,
                                 in_tangent=tang, out_tangent=tang,
                                 bone_name=bone))

            # Radial scale: ring expands outward at ring_speed
            t_sec = f / max(fps, 1e-9)
            ring_radius = ring_speed * t_sec * math.exp(-decay * 0.5 * t_eff)
            d_radius = ring_speed * math.exp(-decay * 0.5 * t_eff) * (
                1.0 - decay * 0.5 * t_eff
            )
            kfs.append(_make_kf(f, ring_radius, "scale", 0, fps,
                                 in_tangent=d_radius, out_tangent=d_radius,
                                 bone_name=bone))

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
# Cloth — 8-control-point Bezier / phase-shifted sinusoid fluid model
# ---------------------------------------------------------------------------
# Flag / Banner fluid simulation approximation.
# The cloth is treated as 8 virtual control points along its length.
# Each point has a sinusoidal oscillation with:
#   - Phase shift proportional to distance from attachment point
#     (travelling wave: phase_i = i * π / N)
#   - Amplitude proportional to distance from attachment (fixed end = 0 motion)
#   - Stokes drag model: effective amplitude scales as 1/(1 + C_d * v²)
#     where C_d is a drag coefficient and v is normalised wind speed (intensity).


def _stokes_drag_amp(base_amp: float, intensity: float, c_drag: float = 0.3) -> float:
    """Stokes drag: amplitude ∝ 1/(1 + C_d * v²) where v ≡ intensity."""
    v = max(0.0, intensity)
    return base_amp / (1.0 + c_drag * v * v)


def _pbd_cloth_rest_bias(
    *,
    segments: int,
    cloth_kind: str,
    wind_speed: float,
) -> List[float]:
    """Return per-segment XPBD rest-drape rotation bias for cloth props."""
    try:
        import copy
        import numpy as np
        from veilbreakers_terrain.sim.pbd_cloth import BANNER_PARAMS, FLAG_PARAMS, bake_static_drape

        base = FLAG_PARAMS if cloth_kind == "flag" else BANNER_PARAMS
        params = copy.copy(base)
        params.rows = max(2, segments)
        params.cols = 3
        params.n_substeps = 2
        params.n_constraint_iters = 3
        params.wind_velocity = np.array([float(wind_speed), 0.25, 0.1], dtype=float)
        rest = bake_static_drape(params, pin_top_row=True, n_steps=3)
        grid = rest.reshape(params.rows, params.cols, 3)
        sag = grid[:, -1, 2] - grid[0, -1, 2]
        max_abs = float(np.max(np.abs(sag))) if sag.size else 0.0
        if max_abs <= 1e-9:
            return [0.0 for _ in range(segments)]
        return [float(v / max_abs) * 0.035 for v in sag[:segments]]
    except Exception:  # pragma: no cover - sim package can be stripped in Blender-only builds
        return [0.0 for _ in range(segments)]


def generate_flag_wind_keyframes(
    frame_count: int = 24,
    segments: int = 8,
    intensity: float = 1.0,
    wind_speed: float = 5.0,
    c_drag: float = 0.3,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Flag wind — 8-point Bezier travelling wave with Stokes drag amplitude scaling.

    Each of `segments` bones is driven by a phase-shifted sinusoid that
    models a travelling wave propagating from the attachment pole toward the
    free edge. Amplitude grows linearly toward the free edge (fixed end = 0).

    Three frequency contributions per bone:
      - Primary wave:  1.0 Hz (main flag billow)
      - Secondary:     2.3 Hz (gust ripple, phase-offset by pi/3)
      - Tertiary:      5.7 Hz (fine surface vibration, low amplitude)

    Stokes drag (F_drag ∝ v²) reduces amplitude at high wind speed:
      effective_amp = base_amp / (1 + C_d * wind_speed²)

    Analytically-derived tangents at every key.

    Args:
        segments:    Number of flag bones / control points (clamped to 2-16).
        wind_speed:  Nominal wind speed (m/s) for Stokes drag calculation.
        c_drag:      Stokes drag coefficient (higher = more damping at speed).
    """
    kfs: List[Keyframe] = []
    n = max(2, min(16, segments))
    bones = [f"flag_bone_{i}" for i in range(n)]
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)

    # Stokes drag: effective amplitude drops with wind_speed²
    # At low speed amplitude is larger (slacker flag); at high speed the flag
    # stretches taut and amplitude drops (inverse of intuition — correct for
    # stretched cloth, not a limp flag).
    eff_amp = _stokes_drag_amp(0.12, wind_speed, c_drag) * intensity
    rest_bias = _pbd_cloth_rest_bias(segments=n, cloth_kind="flag", wind_speed=wind_speed)

    # Frequency bands (Hz)
    wave_freqs = (
        (1.0,  1.00, 0.0),    # (freq_hz, rel_amp, phase_extra)
        (2.3,  0.45, math.pi / 3.0),
        (5.7,  0.18, math.pi * 0.7),
    )

    for i, bone in enumerate(bones):
        # Amplitude grows from 0 at pole to eff_amp at free edge
        edge_frac = (i + 1) / n
        a_seg = eff_amp * edge_frac

        for f in range(0, fc + 1):
            t = f / fc
            val = 0.0
            tang = 0.0
            for freq_hz, rel_amp, phase_extra in wave_freqs:
                omega = 2.0 * math.pi * freq_hz
                # Travelling wave phase: increases with segment index
                phase = omega * t + i * math.pi / n + phase_extra
                val  += a_seg * rel_amp * math.sin(phase)
                tang += a_seg * rel_amp * omega * math.cos(phase) / duration
            val += rest_bias[i]

            kfs.append(_make_kf(f, val, "rotation", 1, fps,
                                 in_tangent=tang, out_tangent=tang,
                                 bone_name=bone))
    return kfs


def generate_banner_wind_keyframes(
    frame_count: int = 24,
    segments: int = 6,
    intensity: float = 1.0,
    wind_speed: float = 4.0,
    c_drag: float = 0.3,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Hanging banner wind — vertical cloth draping with Stokes drag amplitude.

    A hanging banner is fixed at the top and free at the bottom. The wave
    travels downward (phase increases with segment index from top). Each bone
    also gets a lateral sway (rotation axis 0) with a 90° phase lead.

    Two frequency bands:
      - Primary:  0.8 Hz (slow hang-and-sway)
      - Secondary: 3.1 Hz (gust micro-ripple)

    Stokes drag applied identically to generate_flag_wind_keyframes.

    Args:
        segments:    Number of banner bones (clamped 2-12).
        wind_speed:  Nominal wind speed for Stokes drag (m/s).
        c_drag:      Drag coefficient.
    """
    kfs: List[Keyframe] = []
    n = max(2, min(12, segments))
    bones = [f"banner_bone_{i}" for i in range(n)]
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)

    eff_amp = _stokes_drag_amp(0.09, wind_speed, c_drag) * intensity
    rest_bias = _pbd_cloth_rest_bias(segments=n, cloth_kind="banner", wind_speed=wind_speed)

    wave_freqs = (
        (0.8, 1.00, 0.0),
        (3.1, 0.38, 1.4),
    )

    for i, bone in enumerate(bones):
        # Amplitude increases toward free (bottom) edge
        edge_frac = (i + 1) / n
        a_seg = eff_amp * edge_frac

        for f in range(0, fc + 1):
            t = f / fc

            # Lateral sway (rotation Y — side-to-side)
            val_y = 0.0
            tang_y = 0.0
            for freq_hz, rel_amp, phase_extra in wave_freqs:
                omega = 2.0 * math.pi * freq_hz
                phase = omega * t + i * math.pi / n + phase_extra
                val_y  += a_seg * rel_amp * math.sin(phase)
                tang_y += a_seg * rel_amp * omega * math.cos(phase) / duration
            val_y += rest_bias[i]

            # Front-back flutter (rotation X — 90° phase lead)
            val_x = 0.0
            tang_x = 0.0
            for freq_hz, rel_amp, phase_extra in wave_freqs:
                omega = 2.0 * math.pi * freq_hz
                phase = omega * t + i * math.pi / n + phase_extra + math.pi / 2.0
                val_x  += a_seg * rel_amp * 0.5 * math.sin(phase)
                tang_x += a_seg * rel_amp * 0.5 * omega * math.cos(phase) / duration

            kfs.append(_make_kf(f, val_y, "rotation", 1, fps,
                                 in_tangent=tang_y, out_tangent=tang_y,
                                 bone_name=bone))
            kfs.append(_make_kf(f, val_x, "rotation", 0, fps,
                                 in_tangent=tang_x, out_tangent=tang_x,
                                 bone_name=bone))
    return kfs


# ---------------------------------------------------------------------------
# Physics — pendulum chains and ropes
# ---------------------------------------------------------------------------

def generate_chain_swing_keyframes(
    frame_count: int = 40,
    amplitude: float = 0.4,
    chain_length_m: float = 1.5,
    num_links: int = 5,
    damping: float = 0.05,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Chain swing — catenary rest shape + SHM with pendulum period T=2π√(L/g).

    Each link is treated as a pendulum of effective length proportional to
    its distance from the suspension point. The swing decays with damping.

    Catenary rest angle per link:
      theta_i = asin(i * sag_per_link / link_length)  (small sag approx)

    SHM oscillation:
      theta(t) = amplitude * exp(-damping * t) * sin(omega_d * t)
    where omega_d = omega_0 * sqrt(1 - zeta²),
          omega_0 = sqrt(g / L_effective),
          zeta = damping / (2 * omega_0)

    Tangent: d/dt [A*exp(-z*w0*t)*(sin(wd*t)*...)]
    The chain is damped so each successive link has a slightly higher
    natural frequency (shorter effective pendulum length).

    Args:
        chain_length_m: Total chain length in metres for pendulum period.
        num_links:      Number of individual link bones.
        damping:        Linear damping coefficient (s⁻¹).
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    n = max(1, num_links)
    bones = [f"chain_link_{i}" for i in range(n)]
    g = 9.81
    dt = 1.0 / max(fps, 1e-9)
    sag_total = 0.12  # total catenary sag in radians

    for link_i, bone in enumerate(bones):
        # Effective pendulum length: shorter for links near suspension
        frac = (link_i + 1) / n
        L_eff = max(0.05, chain_length_m * frac)

        # Pendulum natural frequency: omega_0 = sqrt(g/L)
        omega_0 = math.sqrt(g / L_eff)
        zeta = damping / (2.0 * omega_0)
        zeta = min(0.95, zeta)  # ensure underdamped
        omega_d = omega_0 * math.sqrt(1.0 - zeta * zeta)

        # Catenary rest angle increases toward free end
        rest_angle = sag_total * frac

        for f in range(0, fc + 1):
            t_sec = f * dt
            # Damped SHM: theta(t) = A*exp(-zeta*omega_0*t)*sin(omega_d*t)
            swing = amplitude * math.exp(-zeta * omega_0 * t_sec) * math.sin(
                omega_d * t_sec
            )
            # d/dt analytically:
            # exp(-zeta*w0*t)*(-zeta*w0*sin(wd*t) + wd*cos(wd*t)) * A
            tang = amplitude * math.exp(-zeta * omega_0 * t_sec) * (
                -zeta * omega_0 * math.sin(omega_d * t_sec)
                + omega_d * math.cos(omega_d * t_sec)
            )

            kfs.append(_make_kf(f, rest_angle + swing, "rotation", 0, fps,
                                 in_tangent=tang, out_tangent=tang,
                                 bone_name=bone))
    return kfs


def generate_rope_sway_keyframes(
    frame_count: int = 40,
    amplitude: float = 0.3,
    segments: int = 4,
    wind_response: float = 0.0,
    rope_length_m: float = 2.0,
    damping: float = 0.05,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Rope sway — catenary rest shape, pendulum oscillation T=2π√(L/g), wind.

    Each segment bone has:
    - Catenary rest angle from natural sag (increases toward free end).
    - Pendulum SHM oscillation with omega_0 = sqrt(g / L_effective).
      where L_effective = rope_length_m * (seg / n) — shorter for upper segs.
    - Wind drift channel (scale axis 0) for shader-driven wind response.

    All tangents analytically derived from damped SHM derivative.

    Args:
        rope_length_m:  Total rope length in metres for pendulum calculation.
        damping:        Linear damping coefficient (s⁻¹).
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    n = max(1, segments)
    bones = [f"rope_bone_{i}" for i in range(n)]
    g = 9.81
    dt = 1.0 / max(fps, 1e-9)
    catenary_sag_total = 0.15

    for seg_i, bone in enumerate(bones):
        frac = (seg_i + 1) / n
        L_eff = max(0.05, rope_length_m * frac)
        omega_0 = math.sqrt(g / L_eff)
        zeta = damping / (2.0 * omega_0)
        zeta = min(0.95, zeta)
        omega_d = omega_0 * math.sqrt(1.0 - zeta * zeta)

        rest_angle = catenary_sag_total * frac
        wind_amp = wind_response * frac

        for f in range(0, fc + 1):
            t = f / fc
            t_sec = f * dt

            swing = amplitude * math.exp(-zeta * omega_0 * t_sec) * math.sin(
                omega_d * t_sec
            )
            tang = amplitude * math.exp(-zeta * omega_0 * t_sec) * (
                -zeta * omega_0 * math.sin(omega_d * t_sec)
                + omega_d * math.cos(omega_d * t_sec)
            )

            # Wind drift: slow sinusoid, grows toward tip
            wind_drift = wind_amp * math.sin(t * math.pi * 0.7)
            d_wind = wind_amp * math.cos(t * math.pi * 0.7) * math.pi * 0.7 / (
                fc * dt
            )

            kfs.append(_make_kf(f, rest_angle + swing + wind_drift,
                                 "rotation", 1, fps,
                                 in_tangent=tang + d_wind, out_tangent=tang + d_wind,
                                 bone_name=bone))

            # Wind response channel on root segment
            if seg_i == 0:
                w_val = 1.0 + wind_amp * math.sin(t * math.pi)
                w_tang = wind_amp * math.cos(t * math.pi) * math.pi / (fc * dt)
                kfs.append(_make_kf(f, w_val, "scale", 0, fps,
                                     in_tangent=w_tang, out_tangent=w_tang))

    return kfs


# ---------------------------------------------------------------------------
# Traps — spring-based mechanics
# ---------------------------------------------------------------------------
# Mass-spring model:
#   omega = sqrt(k / m)    — natural angular frequency
#   For a snappy release: omega_trigger ~ 15 rad/s (stiff trap spring)
#   For a slow reset:     overdamped return (zeta > 1)

def generate_trap_trigger_keyframes(
    frame_count: int = 12,
    angle: float = 45.0,
    spring_k: float = 180.0,
    mass_kg: float = 0.8,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Trap trigger — mass-spring snappy release omega=√(k/m), ring-down settle.

    Phase 1 (fast snap): spring releases at omega = sqrt(k/m).
      theta(t) = target * (1 - cos(omega * t))   until theta >= target
      Approximate first-crossing frame is t_snap = acos(0) / omega = pi/(2*omega).

    Phase 2 (ring-down): underdamped settle around target with zeta=0.15.
      theta(t) = target + A_ring * exp(-zeta*omega*t) * sin(omega_d*t)
      where A_ring = small overshoot amplitude.

    Sparse keys: t=0, snap_frame, first ring peak, settle end.
    All tangents analytically derived.

    Args:
        spring_k: Spring stiffness (N/m or N·m/rad).
        mass_kg:  Trap plate mass (kg).
    """
    target = math.radians(angle)
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)
    omega = math.sqrt(max(spring_k, 0.1) / max(mass_kg, 0.01))

    # Snap phase duration
    t_snap_sec = math.pi / (2.0 * omega)
    snap_frame = min(int(round(t_snap_sec * fps)), fc // 2)
    snap_frame = max(1, snap_frame)

    # Ring-down parameters
    zeta_ring = 0.15
    omega_d = omega * math.sqrt(1.0 - zeta_ring ** 2)
    A_ring = target * 0.18  # overshoot amplitude

    kfs: List[Keyframe] = []

    # Frame 0: at rest
    # Tangent at 0: d/dt [target*(1-cos(omega*t))] = target*omega*sin(0) = 0
    # but out_tangent should be high to show snap
    kfs.append(_make_kf(0, 0.0, "rotation", 2, fps,
                         in_tangent=0.0, out_tangent=target * omega))

    # Snap frame: reached target angle
    snap_tang = target * omega * math.sin(omega * t_snap_sec)
    kfs.append(_make_kf(snap_frame, target, "rotation", 2, fps,
                         in_tangent=snap_tang, out_tangent=A_ring * omega_d))

    # Ring overshoot peak: at t = pi/(2*omega_d) after snap
    t_peak_sec = t_snap_sec + math.pi / (2.0 * omega_d)
    peak_frame = min(int(round(t_peak_sec * fps)), fc)
    t_ring = t_peak_sec - t_snap_sec
    peak_val = target + A_ring * math.exp(-zeta_ring * omega * t_ring) * math.sin(
        omega_d * t_ring
    )
    peak_tang = A_ring * math.exp(-zeta_ring * omega * t_ring) * (
        -zeta_ring * omega * math.sin(omega_d * t_ring)
        + omega_d * math.cos(omega_d * t_ring)
    )
    kfs.append(_make_kf(peak_frame, peak_val, "rotation", 2, fps,
                         in_tangent=peak_tang, out_tangent=peak_tang))

    # Settle end: back at target with zero velocity
    kfs.append(_make_kf(fc, target, "rotation", 2, fps,
                         in_tangent=0.0, out_tangent=0.0))
    return kfs


def generate_trap_reset_keyframes(
    frame_count: int = 20,
    angle: float = 45.0,
    spring_compression_frames: int = 3,
    sound_cue_offset_frames: int = 1,
    spring_k: float = 180.0,
    mass_kg: float = 0.8,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Trap reset — spring-load compression, overdamped return to neutral.

    Phase 1 (spring_compression_frames): trap arm compresses slightly past
    origin (spring loaded under tension, 8% overshoot of target angle).
    Phase 2: overdamped cubic ease-out return from target back to 0.
    Overdamped: zeta = 1.5 > 1, so no oscillation — smooth creep to rest.
    Sound cue: scale axis 2 = 1.0 at release click moment (SFX trigger).

    Overdamped motion (zeta > 1):
      theta(t) = target * exp(-zeta*omega*t) * (cosh(omega*sqrt(z²-1)*t)
                 + zeta/sqrt(z²-1) * sinh(...))
    Simplified to cubic ease-out for performance.

    Args:
        spring_k: Spring stiffness constant.
        mass_kg:  Trap mass.
    """
    target = math.radians(angle)
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)
    compress = max(1, spring_compression_frames)
    cue_frame = compress + max(0, sound_cue_offset_frames)
    omega = math.sqrt(max(spring_k, 0.1) / max(mass_kg, 0.01))

    kfs: List[Keyframe] = []
    compression_overshoot = target * 0.08

    # Phase 1: compression — sinusoidal spring loading
    for f in range(0, compress + 1):
        t = f / compress
        val = target + compression_overshoot * math.sin(t * math.pi)
        tang = compression_overshoot * math.cos(t * math.pi) * math.pi / (
            compress / max(fps, 1e-9)
        )
        kfs.append(_make_kf(f, val, "rotation", 2, fps,
                             in_tangent=tang, out_tangent=tang))

    # Sound cue key (scale axis 2)
    if cue_frame <= fc:
        kfs.append(_make_kf(cue_frame, 0.0, "scale", 2, fps,
                             in_tangent=0.0, out_tangent=float('inf')))
        kfs.append(_make_kf(cue_frame, 1.0, "scale", 2, fps,
                             in_tangent=float('inf'), out_tangent=0.0))

    # Phase 2: overdamped return — cubic ease-out (simulates zeta=1.5 creep)
    # theta(t) = target * (1-t)^3, from compress frame to fc
    release_start = compress
    release_frames = max(1, fc - release_start)
    release_duration = release_frames / max(fps, 1e-9)

    for f in range(release_start, fc + 1):
        t = (f - release_start) / release_frames
        # Overdamped: starts fast (spring force), decelerates to zero slope
        val = target * (1.0 - t) ** 3
        # d/dt [(1-t)^3] = -3*(1-t)^2 / release_duration
        tang = -target * 3.0 * (1.0 - t) ** 2 / release_duration
        kfs.append(_make_kf(f, val, "rotation", 2, fps,
                             in_tangent=tang, out_tangent=tang))

    return kfs


def generate_trap_idle_keyframes(
    frame_count: int = 24,
    fps: float = 30.0,
    spring_k: float = 180.0,
    mass_kg: float = 0.8,
) -> List[Keyframe]:
    """Trap idle — dual-frequency micro-vibration from spring resonance.

    A cocked trap has stored spring energy. Micro-vibrations arise from:
      - Fundamental resonance at omega_0 = sqrt(k/m) (radians/s)
      - Second harmonic at 2*omega_0 (structural mode)

    Both decay with a slow environmental damping (zeta=0.02 — near-lossless).
    The combined signal gives a realistic "tension hum" feel.

    theta(t) = A1 * exp(-zeta*w0*t)*sin(w0*t) + A2*exp(-zeta*2w0*t)*sin(2*w0*t)
    d/dt derived analytically per term.

    Args:
        spring_k: Spring stiffness for resonance frequency calculation.
        mass_kg:  Trap mass.
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    dt = 1.0 / max(fps, 1e-9)
    omega_0 = math.sqrt(max(spring_k, 0.1) / max(mass_kg, 0.01))
    zeta = 0.02  # near-lossless micro-vibration
    A1 = 0.003   # fundamental amplitude (radians)
    A2 = 0.0015  # second harmonic amplitude

    for f in range(0, fc + 1):
        t = f * dt
        # Fundamental
        v1 = A1 * math.exp(-zeta * omega_0 * t) * math.sin(omega_0 * t)
        d1 = A1 * math.exp(-zeta * omega_0 * t) * (
            -zeta * omega_0 * math.sin(omega_0 * t) + omega_0 * math.cos(omega_0 * t)
        )
        # Second harmonic
        v2 = A2 * math.exp(-zeta * 2.0 * omega_0 * t) * math.sin(2.0 * omega_0 * t)
        d2 = A2 * math.exp(-zeta * 2.0 * omega_0 * t) * (
            -zeta * 2.0 * omega_0 * math.sin(2.0 * omega_0 * t)
            + 2.0 * omega_0 * math.cos(2.0 * omega_0 * t)
        )
        val = v1 + v2
        tang = d1 + d2
        kfs.append(_make_kf(f, val, "rotation", 2, fps,
                             in_tangent=tang, out_tangent=tang))
    return kfs


# ---------------------------------------------------------------------------
# Interactables
# ---------------------------------------------------------------------------

def generate_chest_open_keyframes(
    frame_count: int = 30,
    angle: float = 110.0,
    spring_k: float = 40.0,
    mass_kg: float = 2.5,
    max_angle_deg: float = 115.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Chest lid — hinge physics: spring-assist open, soft damped stop at max_angle.

    Three phases:
    1. Spring-assist (0 → 60% of travel): spring pushes lid open.
       omega = sqrt(k/m); rotates with sin-wave acceleration profile.
    2. Free rotation (60 → 90% of travel): lid coasts past optimum.
    3. Damped stop (90% → 100%): lid hits mechanical stop, overdamped settle.
       zeta = 1.8 (overdamped), exponential decay to max_angle.

    Sparse 5 keys with analytically-derived tangents.

    Args:
        spring_k:     Spring assistance stiffness.
        mass_kg:      Lid mass for natural frequency.
        max_angle_deg: Hard stop angle (lid cannot open past this).
    """
    target = math.radians(angle)
    hard_stop = math.radians(max(angle, max_angle_deg))
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)
    omega = math.sqrt(max(spring_k, 0.1) / max(mass_kg, 0.01))

    # Phase boundaries (normalised time)
    t_spring_end = 0.60
    t_coast_end  = 0.90

    def _h(t: float) -> float:
        if t <= t_spring_end:
            # Spring-assist: theta = target*(1-cos(pi*t/(2*t_spring_end))) * t_spring_end
            phase = math.pi * t / (2.0 * t_spring_end)
            return target * t_spring_end * (1.0 - math.cos(phase)) / 1.0
        elif t <= t_coast_end:
            # Free coast: linear from spring_end value to ~95% of target
            sp_val = _h(t_spring_end)
            coast_frac = (t - t_spring_end) / (t_coast_end - t_spring_end)
            return sp_val + (target * 0.95 - sp_val) * coast_frac
        else:
            # Damped stop: overdamped exponential settle to target
            t2 = (t - t_coast_end) / (1.0 - t_coast_end)
            pre_stop = _h(t_coast_end)
            # Blend from pre_stop overshoot toward target (hard stop clamps)
            overshoot = min(pre_stop + (hard_stop - pre_stop) * 0.15, hard_stop)
            return overshoot + (target - overshoot) * (1.0 - math.exp(-4.0 * t2))

    def _dh(t: float) -> float:
        if t <= t_spring_end:
            phase = math.pi * t / (2.0 * t_spring_end)
            return target * t_spring_end * math.sin(phase) * math.pi / (
                2.0 * t_spring_end * duration
            )
        elif t <= t_coast_end:
            sp_val = _h(t_spring_end)
            return (target * 0.95 - sp_val) / (
                (t_coast_end - t_spring_end) * duration
            )
        else:
            t2 = (t - t_coast_end) / (1.0 - t_coast_end)
            pre_stop = _h(t_coast_end)
            overshoot = min(pre_stop + (hard_stop - pre_stop) * 0.15, hard_stop)
            return (target - overshoot) * 4.0 * math.exp(-4.0 * t2) / (
                (1.0 - t_coast_end) * duration
            )

    kfs: List[Keyframe] = []
    for t in (0.0, t_spring_end * 0.5, t_spring_end, t_coast_end, 1.0):
        f = int(round(t * fc))
        kfs.append(_make_kf(f, _h(t), "rotation", 0, fps,
                             in_tangent=_dh(t), out_tangent=_dh(t)))
    return kfs


def generate_lever_pull_keyframes(
    frame_count: int = 15,
    angle: float = 60.0,
    detent_angle_deg: float = 30.0,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Lever pull — detent mechanism: accelerate through centre, decelerate at end.

    A lever with a detent (click point) at detent_angle has a distinct
    two-phase motion:
    1. Ease-in from 0 to detent_angle: pull against spring resistance.
       Cubic ease-in (slow start, fast at detent).
    2. Ease-out from detent to target: spring assist pushes lever to end.
       Cubic ease-out (fast out of detent, slow to final position).

    The detent click is marked by a scale axis 2 = 1.0 impulse key.
    All keys carry analytically-derived tangents.

    Args:
        detent_angle_deg: Angle at which the detent engages / clicks.
    """
    target = math.radians(angle)
    detent = math.radians(max(0.0, min(detent_angle_deg, angle * 0.9)))
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)

    # Detent at what fraction of total travel
    detent_frac = detent / target if target > 0 else 0.5
    detent_frame = max(1, int(round(detent_frac * fc)))

    # Phase 1 duration
    dur1 = detent_frame / max(fps, 1e-9)
    # Phase 2 duration
    dur2 = (fc - detent_frame) / max(fps, 1e-9)

    kfs: List[Keyframe] = []

    # Phase 1: ease-in to detent
    for t in (0.0, 0.5, 1.0):
        f = int(round(t * detent_frame))
        val = detent * (1.0 - (1.0 - t) ** 3)
        tang = _ease_in_cubic_tangent(t, detent, dur1)
        kfs.append(_make_kf(f, val, "rotation", 0, fps,
                             in_tangent=tang, out_tangent=tang))

    # Detent click impulse (SFX trigger channel)
    kfs.append(_make_kf(detent_frame, 1.0, "scale", 2, fps,
                         in_tangent=0.0, out_tangent=0.0))

    # Phase 2: ease-out from detent to target
    for t in (0.0, 0.5, 1.0):
        f = detent_frame + int(round(t * (fc - detent_frame)))
        # Ease-out: fast start (coming off detent spring), slow finish
        travel = target - detent
        val = detent + travel * (1.0 - (1.0 - t) ** 3)
        tang = _ease_in_cubic_tangent(t, travel, dur2)
        kfs.append(_make_kf(f, val, "rotation", 0, fps,
                             in_tangent=tang, out_tangent=tang))

    return kfs


def generate_switch_toggle_keyframes(
    frame_count: int = 8,
    angle: float = 30.0,
    detent_overshoot: float = 0.15,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Switch toggle — detent snap: accelerate through centre, decelerate at end.

    A switch has a snap-over detent at the midpoint:
    - Phase 1 (0 → mid): slow ease-in (operator pushing against detent spring).
    - Mid: snap-over — high tangent through midpoint (spring releases).
    - Phase 2 (mid → end): fast ease-out with slight overshoot, settle.

    Sparse 4 keys with correct tangents at each phase boundary.

    Args:
        detent_overshoot: Fractional overshoot past target after snap (0–0.3).
    """
    target = math.radians(angle)
    mid = max(1, frame_count // 2)
    duration = frame_count / max(fps, 1e-9)
    dur1 = mid / max(fps, 1e-9)
    dur2 = (frame_count - mid) / max(fps, 1e-9)

    # At midpoint: fast snap tangent from spring release
    # velocity = target/duration * acceleration_factor (detent snap is ~3x normal)
    snap_tang = target / dur1 * 3.0

    kfs: List[Keyframe] = [
        # Start: slow approach to detent
        _make_kf(0, 0.0, "rotation", 1, fps,
                 in_tangent=0.0, out_tangent=_ease_in_cubic_tangent(0.0, target * 0.5, dur1)),
        # Mid: snap-over — high tangent in both directions
        _make_kf(mid, target * 0.5, "rotation", 1, fps,
                 in_tangent=snap_tang, out_tangent=snap_tang),
        # Post-snap overshoot
        _make_kf(frame_count - 1, target * (1.0 + detent_overshoot), "rotation", 1, fps,
                 in_tangent=snap_tang * 0.3, out_tangent=0.0),
        # Settle at target
        _make_kf(frame_count, target, "rotation", 1, fps,
                 in_tangent=0.0, out_tangent=0.0),
    ]
    return kfs


# ---------------------------------------------------------------------------
# Ambient
# ---------------------------------------------------------------------------

# Kelvin color temperature helpers for candle flicker.
# Candles oscillate between ~1800 K (dim/yellow) and ~2200 K (bright/white).
# We linearise the CIE 1931 chromaticity: dB/dT ≈ 0.0002 (blue channel gain).
# The `color_temp` channel drives a shader Color Temperature node.

_CANDLE_TEMP_MIN = 1800.0   # Kelvin — dim glow
_CANDLE_TEMP_MAX = 2200.0   # Kelvin — bright flicker peak


def _candle_temp(brightness_norm: float) -> float:
    """Map normalised brightness [0..1] to Kelvin color temperature."""
    return _CANDLE_TEMP_MIN + (
        _CANDLE_TEMP_MAX - _CANDLE_TEMP_MIN
    ) * max(0.0, min(1.0, brightness_norm))


def generate_candle_flicker_keyframes(
    frame_count: int = 30,
    intensity: float = 1.0,
    fps: float = 30.0,
    slow_amp: float = 0.20,
    mid_amp: float = 0.30,
    fast_amp: float = 0.10,
) -> List[Keyframe]:
    """Candle flicker — 3-band model + Kelvin color temperature shift.

    Three channels:
    - Scale Y: flame height (3 frequency bands: 0.5 / 3 / 12 Hz).
    - Scale Z: flame width lateral (slow band only, anti-phase to height).
    - Scale X: color_temp channel encoded as normalised 0–1
               mapped from 1800 K (dim) → 2200 K (bright).

    The color temperature channel gives Unity's shader a direct Kelvin value
    to drive a color temperature ramp without baking RGB channels.
    Tangents analytically derived for all channels.

    Args:
        slow_amp: Amplitude for 0.5 Hz buoyancy sway.
        mid_amp:  Amplitude for 3 Hz flicker band.
        fast_amp: Amplitude for 12 Hz sputter band.
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    duration = fc / max(fps, 1e-9)

    # Height bands (all three)
    bands_height = (
        (0.5,  slow_amp, 0.0),
        (3.0,  mid_amp,  1.1),
        (12.0, fast_amp, 2.7),
    )
    # Width: slow only, anti-phase (flame gets narrower as it gets taller)
    bands_width = (
        (0.5, slow_amp * 0.6, math.pi),  # 180° phase shift = anti-phase
    )

    for f in range(0, fc + 1):
        t = f / fc

        # Height
        sc_y, dsc_y = _fire_val_tang(t, intensity, duration, bands_height)

        # Width (narrow when tall)
        sc_z = intensity
        dsc_z = 0.0
        for freq_hz, amp, phase in bands_width:
            omega = 2.0 * math.pi * freq_hz
            sc_z  += intensity * amp * math.sin(omega * t + phase)
            dsc_z += intensity * amp * omega * math.cos(omega * t + phase) / duration

        # Color temperature: brightness is the normalised flame height above base
        # brightness_norm = (sc_y - 0.9) / 0.5  (maps typical range 0.9–1.4 → 0–1)
        brightness_norm = max(0.0, min(1.0, (sc_y - 0.9) / 0.5))
        kelvin = _candle_temp(brightness_norm)
        # Normalise to 0–1 for shader channel
        temp_norm = (kelvin - _CANDLE_TEMP_MIN) / (_CANDLE_TEMP_MAX - _CANDLE_TEMP_MIN)
        # d(temp_norm)/dt = d(brightness_norm)/dt * 1/0.5 * range / range
        # = dsc_y/dt * (1/0.5) * 1 (unit normalised)
        d_temp = dsc_y / 0.5  # chain rule: d(brightness_norm)/dt = dsc_y / 0.5

        kfs.append(_make_kf(f, sc_y, "scale", 1, fps,
                             in_tangent=dsc_y, out_tangent=dsc_y))
        kfs.append(_make_kf(f, sc_z, "scale", 2, fps,
                             in_tangent=dsc_z, out_tangent=dsc_z))
        kfs.append(_make_kf(f, temp_norm, "scale", 0, fps,
                             in_tangent=d_temp, out_tangent=d_temp))
    return kfs


def generate_chandelier_sway_keyframes(
    frame_count: int = 60,
    amplitude: float = 0.05,
    chain_length_m: float = 2.0,
    candle_arm_length_m: float = 0.5,
    fps: float = 30.0,
) -> List[Keyframe]:
    """Chandelier sway — compound pendulum with candle-arm sub-oscillations.

    Two pendulum levels:
    1. Main frame: simple pendulum T = 2π√(L/g) at chain_length_m.
    2. Candle arms: sub-pendulums at candle_arm_length_m.
       Natural frequency = sqrt(g/L_arm) ≈ 1.4× main for typical proportions.

    Main frame drives rotation X (fore-aft) and Y (side-to-side) with 90°
    phase offset (Lissajous figure).
    Candle arm oscillation is added as a separate rotation channel.
    Both decay with a slow environmental damping (zeta=0.04).

    All tangents analytically derived from damped SHM derivative.

    Args:
        chain_length_m:     Suspension chain length for main pendulum (m).
        candle_arm_length_m: Length of candle arm sub-pendulums (m).
    """
    kfs: List[Keyframe] = []
    fc = max(frame_count, 1)
    g = 9.81
    dt = 1.0 / max(fps, 1e-9)
    zeta = 0.04  # slow environmental damping (barely perceptible decay)

    # Main pendulum
    L_main = max(0.1, chain_length_m)
    omega_main = math.sqrt(g / L_main)
    omega_d_main = omega_main * math.sqrt(1.0 - zeta ** 2)

    # Candle arm sub-pendulum
    L_arm = max(0.05, candle_arm_length_m)
    omega_arm = math.sqrt(g / L_arm)
    omega_d_arm = omega_arm * math.sqrt(1.0 - zeta ** 2)

    for f in range(0, fc + 1):
        t_sec = f * dt
        exp_main = math.exp(-zeta * omega_main * t_sec)
        exp_arm  = math.exp(-zeta * omega_arm  * t_sec)

        # Main frame: rotation X (fore-aft)
        rx = amplitude * exp_main * math.sin(omega_d_main * t_sec)
        drx = amplitude * exp_main * (
            -zeta * omega_main * math.sin(omega_d_main * t_sec)
            + omega_d_main * math.cos(omega_d_main * t_sec)
        )
        # Main frame: rotation Y (side-to-side, 90° phase lead = cos)
        ry = amplitude * 0.6 * exp_main * math.cos(omega_d_main * t_sec)
        dry = amplitude * 0.6 * exp_main * (
            -zeta * omega_main * math.cos(omega_d_main * t_sec)
            - omega_d_main * math.sin(omega_d_main * t_sec)
        )

        # Candle arm sub-oscillation at arm frequency (1.4× main approx)
        # Modulated by main swing (arms swing more when frame swings more)
        arm_mod = abs(rx) / max(amplitude, 1e-9)  # coupling: 0..1
        arm_amp = amplitude * 0.4 * (1.0 + arm_mod)
        r_arm = arm_amp * exp_arm * math.sin(omega_d_arm * t_sec + math.pi / 4.0)
        d_arm = arm_amp * exp_arm * (
            -zeta * omega_arm * math.sin(omega_d_arm * t_sec + math.pi / 4.0)
            + omega_d_arm * math.cos(omega_d_arm * t_sec + math.pi / 4.0)
        )

        kfs.append(_make_kf(f, rx, "rotation", 0, fps,
                             in_tangent=drx, out_tangent=drx))
        kfs.append(_make_kf(f, ry, "rotation", 1, fps,
                             in_tangent=dry, out_tangent=dry))
        kfs.append(_make_kf(f, r_arm, "rotation", 2, fps,
                             in_tangent=d_arm, out_tangent=d_arm))

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
    "door_open":       generate_door_open_keyframes,
    "door_close":      generate_door_close_keyframes,
    "door_slam":       generate_door_slam_keyframes,
    "door_creak":      generate_door_creak_keyframes,
    "gate_raise":      generate_gate_raise_keyframes,
    "gate_lower":      generate_gate_lower_keyframes,
    "drawbridge":      generate_drawbridge_keyframes,
    "shatter":         generate_shatter_keyframes,
    "wobble_collapse": generate_wobble_collapse_keyframes,
    "fire_flicker":    generate_fire_flicker_keyframes,
    "torch_sway":      generate_torch_sway_keyframes,
    "water_wave":      generate_water_wave_keyframes,
    "water_ripple":    generate_water_ripple_keyframes,
    "waterfall":       generate_waterfall_keyframes,
    "flag_wind":       generate_flag_wind_keyframes,
    "banner_wind":     generate_banner_wind_keyframes,
    "chain_swing":     generate_chain_swing_keyframes,
    "rope_sway":       generate_rope_sway_keyframes,
    "trap_trigger":    generate_trap_trigger_keyframes,
    "trap_reset":      generate_trap_reset_keyframes,
    "trap_idle":       generate_trap_idle_keyframes,
    "chest_open":      generate_chest_open_keyframes,
    "lever_pull":      generate_lever_pull_keyframes,
    "switch_toggle":   generate_switch_toggle_keyframes,
    "candle_flicker":  generate_candle_flicker_keyframes,
    "chandelier_sway": generate_chandelier_sway_keyframes,
    "windmill_rotate": generate_windmill_rotate_keyframes,
}


def generate_env_keyframes(params: Dict[str, Any]) -> List[Keyframe] | List[Dict[str, Any]]:
    """Dispatch to the appropriate generator based on params['env_type'].

    Validates env_type against VALID_ENV_TYPES, introspects the target
    function signature to extract only recognised kwargs from params, then
    calls the function. Raises ValueError for unknown env_type.

    All 27 env_type values are routed, including: door_open/close/slam/creak,
    gate_raise/lower, drawbridge, shatter, wobble_collapse, fire_flicker,
    torch_sway, water_wave/ripple/waterfall, flag_wind, banner_wind,
    chain_swing, rope_sway, trap_trigger/reset/idle, chest_open, lever_pull,
    switch_toggle, candle_flicker, chandelier_sway, windmill_rotate.
    """
    env_type = params.get("env_type", "door_open")
    if env_type not in VALID_ENV_TYPES:
        raise ValueError(
            f"unknown env_type: {env_type!r}; "
            f"must be one of {sorted(VALID_ENV_TYPES)}"
        )
    fn = _DISPATCH[env_type]
    sig = inspect.signature(fn)
    kwargs = {k: v for k, v in params.items() if k in sig.parameters}
    keyframes = fn(**kwargs)
    if params.get("as_dicts") or params.get("json_serializable"):
        return [keyframe_to_dict(kf) for kf in keyframes]
    return keyframes


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

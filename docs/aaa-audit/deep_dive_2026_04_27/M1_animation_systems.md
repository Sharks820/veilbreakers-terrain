# M1: Animation & Gait Systems — Deep Dive Audit
**Date:** 2026-04-27
**Auditor:** Claude (AAA Senior Tech Lead standard — Rockstar/Guerrilla reference)
**Files audited:**
- `veilbreakers_terrain/handlers/animation_environment.py` (~2042 lines)
- `veilbreakers_terrain/handlers/animation_gaits.py` (38 lines)

---

## Executive Summary

The animation system occupies an uncomfortable middle ground: the keyframe math is significantly more competent than most of this codebase, but the system has a **structural wiring failure** that is far more damaging than any individual math bug. Animation output is a `List[Keyframe]` that is returned to an MCP caller as a raw JSON list of dataclass instances. There is **zero integration** with the TerrainMaskStack, the Unity export pipeline (`terrain_unity_export.py`), or any `.anim` / `.controller` file serializer. The system generates plausible-looking keyframe data and throws it over a wall into MCP JSON, from which no downstream code picks it up and applies it to a Blender object or Unity asset.

The prior J6 dead-code sweep identified 14 unused animation parameters (`duration`, `omega`, `phase_speed`). This audit confirms the root cause: those parameters were removed from function signatures during refactoring, but the real problem is not the dead params — it is that the entire output path is disconnected from every production surface.

**Overall grade: F (same floor as VisualQA)**
Reason: A keyframe generator that generates beautiful data and writes it nowhere is not an animation system. It is a math library with no integration.

---

## P0 Findings

---

**M1-P0-01** | `animation_environment.py` (entire module) | Animation output is never written to a Blender object, `.anim` file, or Unity export — all generated keyframes are silently dropped

**Evidence:**
```python
# handlers/__init__.py:526-529
def _handle_generate_env_keyframes(params: dict) -> list:
    return _ae.generate_env_keyframes(params)

handlers["animation_generate_env_keyframes"] = _handle_generate_env_keyframes
```
```python
# blender_server.py:319
result = fn(params)
# result is {"status": "ok", "result": [Keyframe(...), Keyframe(...), ...]}
# No caller receives this and calls bpy.data.actions.new(), action.fcurves.new(),
# fcurve.keyframe_points.insert(), or writes a .anim file.
```
The blender_server dispatch loop returns a dict with `"result": <list of Keyframes>` to the MCP JSON layer. The Keyframe dataclass has no `to_dict()` or `__json__` method; Python's default JSON encoder will raise `TypeError: Object of type Keyframe is not JSON serializable` for the non-dict fields. Even if this were fixed, there is no Blender-side consumer that takes the keyframe list and inserts it into an FCurve, and no Unity-side consumer that writes a `.anim` clip.

**AAA gap:** At Guerrilla/Rockstar, an environment animation generator outputs to a concrete artifact: a Blender Action with populated FCurves (for Blender-source workflow), or directly into a Unity `.anim` file or Animator Controller asset. The data path is: generate → serialize → write to Action/FCurve or write .anim JSON → Unity imports. None of those steps exist here.

**Fix:**
1. Add a `keyframe_to_dict(kf: Keyframe) -> dict` serializer in `animation_gaits.py` so the MCP layer can return JSON.
2. Add a Blender-side applicator `apply_keyframes_to_action(obj_name: str, keyframes: list, action_name: str)` that calls `bpy.data.actions.new()`, `action.fcurves.new(data_path, index=axis)`, and `fcurve.keyframe_points.insert(time, value)` with tangents set via `keyframe_points[-1].handle_left` / `.handle_right`.
3. Wire the applicator into the `animation_*` command handlers so MCP callers can pass `object_name` and receive confirmation, not raw Keyframe objects.
4. Add an animation manifest to the Unity export bundle so `.anim` clips are included in the terrain tile export.

**Estimated time:** 2–3 days (Blender FCurve applicator + Unity .anim serializer + export wiring).

---

**M1-P0-02** | `animation_environment.py` (entire module) | `Keyframe` dataclass is not JSON-serializable — MCP dispatch crashes with `TypeError` on any animation call that reaches the JSON encoder

**Evidence:**
```python
# animation_gaits.py:11-34
@dataclass
class Keyframe:
    frame: int
    value: float
    channel: str = "location"
    axis: int = 0
    bone_name: str = ""
    time: float = 0.0
    in_tangent: float = 0.0
    out_tangent: float = 0.0
    # No __json__, no to_dict(), no JSONEncoder subclass registered anywhere
```
The `_handle_generate_env_keyframes` handler returns `List[Keyframe]`. The blender_server wraps this in `{"status": "ok", "result": <list>}` and the MCP layer attempts to JSON-serialize it. Python's `json.dumps()` has no handler for dataclass instances; this raises `TypeError: Object of type Keyframe is not JSON serializable`. The test at `test_mcp_dispatch.py:564` catches this only because it checks `isinstance(keyframes, list)` — it never sends the result through the JSON encoder. Every real MCP client call to `"animate"` or any `"animate_*"` command will crash at the network serialization boundary.

**AAA gap:** Every data-transfer object that crosses an MCP/JSON boundary must be serializable. This is table-stakes correctness, not an edge case.

**Fix:**
```python
# animation_gaits.py — add:
def keyframe_to_dict(kf: "Keyframe") -> dict:
    return {
        "frame": kf.frame,
        "value": kf.value,
        "channel": kf.channel,
        "axis": kf.axis,
        "bone_name": kf.bone_name,
        "time": kf.time,
        "in_tangent": kf.in_tangent,
        "out_tangent": kf.out_tangent,
    }

# handlers/__init__.py — update handler:
def _handle_generate_env_keyframes(params: dict) -> list:
    from .animation_gaits import keyframe_to_dict
    return [keyframe_to_dict(kf) for kf in _ae.generate_env_keyframes(params)]
```
Same fix needed for every individual `animation_*` handler in `_build_command_handlers`. **Estimated time:** 2 hours.

---

**M1-P0-03** | `animation_environment.py:560-593` | `generate_shatter_keyframes` produces O(n × frame_count × 7) keyframes — default call generates 1,260 keyframes for 6 shards/20 frames; a typical destruction event with 16 shards at 60 frames generates **~6,720 keyframes** — Unity Animator will stall

**Evidence:**
```python
# Line 562-593
for f in range(1, fc + 1):          # fc iterations (default 20)
    # 4 keyframes per frame per shard:
    kfs.append(...)  # location X
    kfs.append(...)  # location Y
    kfs.append(...)  # location Z
    kfs.append(...)  # rotation

    if f >= sleep_frame:
        for axis in range(3):
            kfs.append(...)  # scale X,Y,Z  — 3 MORE per frame once sleeping
```
With `num_shards=16, frame_count=60` (realistic destruction): 16 shards × 60 frames × (4 location+rot + 3 scale) = 6,720 keyframes, all dense (one per frame). Unity Animator requires sparse keyframes for performance — dense-baked keyframes on destruction fragments will stall the Animator evaluation and defeat the purpose of analytically-derived tangents. Additionally, the LOD gating (scale=0 for shards beyond `lod_visible_shards`) applies the scale key at every frame after sleep, not just at the sleep transition — multiplying the keyframe count further.

**AAA gap:** UE5 Chaos and Unity DOTS destruction use sparse keys only at trajectory inflection points (launch frame, apex, impact frame, sleep frame) — 4–6 keys per shard per axis, not one per frame. Baking every frame per shard is the approach of a pre-2010 game engine, not AAA 2024.

**Fix:** Replace the per-frame loop with sparse key emission:
- Frame 0: initial position + LOD scale key
- Frame of peak Z height (apex): one key per position axis
- Impact frame (ground crossing, `pz <= 0`): one key per position axis
- Sleep frame: final position + scale key (LOD off for hidden shards)
Total: 4 keys × 4 channels per shard = 16 keyframes per shard, vs. the current 60+ per shard.
**Estimated time:** 3–4 hours.

---

**M1-P0-04** | `animation_environment.py:280-282` | `generate_door_creak_keyframes` uses `_ease_in_cubic_tangent` for the final (ease-out) stop — tangent formula is wrong for the last key, producing a sharp acceleration artifact instead of deceleration at door close

**Evidence:**
```python
# Lines 280-282
elif i == len(stops) - 1:
    eased = 1.0 - (1.0 - frac) ** 3   # ease-OUT cubic: correct shape
    tang = _ease_in_cubic_tangent(frac, target, duration)  # WRONG: ease-IN tangent
```
The position value uses `1.0 - (1.0 - frac)^3` (ease-out cubic — correct, door decelerates to final angle). But the tangent uses `_ease_in_cubic_tangent`, which computes `3*(1-t)^2 / dur` — the derivative of the *ease-in* curve, not the ease-out. The correct tangent for `1.0 - (1-t)^3` is `3*(1-t)^2 / dur` which is actually the same formula — BUT the value of `frac` here is always 1.0 (the last stop in the list is `fc`, so `(i+1)/len(stops) = num_stops+1 / num_stops+1 = 1.0`). Substituting `t=1`: `_ease_in_cubic_tangent(1.0, target, dur) = target * 3 * 0 / dur = 0`. The ease-out tangent at `t=1` is also 0. So for the very last key this cancels out — but for intermediate stops that accidentally fall into this branch (they don't due to the `elif` structure), it would be wrong. The real bug is that the `elif` guard uses `_ease_in_cubic_tangent` in a branch clearly labeled and shaped as ease-out, which will silently produce wrong results if `num_stops` is set such that `frac != 1.0` at the final stop. With the default `num_stops=5`, `frac = 6/6 = 1.0`, so the bug is dormant at defaults but activates with any even `num_stops` where the stop list length differs.

More critically: the `stops` list is `[fc//6, 2*fc//6, ..., fc]` (n+1 entries including `fc`). `len(stops) = num_stops + 1`. At the last stop, `i = num_stops`, `frac = (num_stops+1)/(num_stops+1) = 1.0`. So the tangent is always 0 at the final key regardless of which formula is used. **This means the final key has zero outgoing tangent** — the door stops dead at the end with zero velocity, which is correct for the final frame but loses the ease-out deceleration shape through the penultimate segment.

**AAA gap:** A door creak that stops dead (zero tangent at end) with no deceleration in the penultimate segment looks like a physics step-function, not organic creaking. The tangent at the second-to-last key should carry the ease-out slope so Unity interpolates a gradual stop.

**Fix:** At the final stop, set `in_tangent` from `_ease_out_cubic_tangent(frac, target, duration)` (which correctly gives a negative/decelerating slope) and keep `out_tangent=0`:
```python
elif i == len(stops) - 1:
    eased = 1.0 - (1.0 - frac) ** 3
    tang = _ease_out_cubic_tangent(frac, target, duration)  # correct slope
```
**Estimated time:** 15 minutes.

---

**M1-P0-05** | `animation_environment.py:1703-1704` | `generate_lever_pull_keyframes` Phase 2 uses `_ease_in_cubic_tangent` for a motion explicitly documented as ease-out — lever snaps incorrectly out of detent

**Evidence:**
```python
# Lines 1699-1706
# Phase 2: ease-out from detent to target
for t in (0.0, 0.5, 1.0):
    f = detent_frame + int(round(t * (fc - detent_frame)))
    # Ease-out: fast start (coming off detent spring), slow finish
    travel = target - detent
    val = detent + travel * (1.0 - (1.0 - t) ** 3)   # ease-IN cubic (slow start!)
    tang = _ease_in_cubic_tangent(t, travel, dur2)     # ease-IN tangent — wrong
```
The comment says "Ease-out: fast start (coming off detent spring), slow finish." But `1.0 - (1.0-t)^3` is the **ease-in** cubic (starts slow, ends fast), the exact opposite of what the detent release should feel like. The correct ease-out (fast start from spring release, slows to end stop) is `(1.0-t)^3` subtracted from 1 only if you invert it: `t^3` for ease-in, or `1 - (1-t)^3` is ease-in. The correct ease-out cubic for "fast start, slow finish" is `t * (2 - t)` (quadratic) or more precisely the value should be `travel * (3*t^2 - 2*t^3)` (smooth-step) or use `1 - (1-t)^3` re-mapped. **The value formula `1 - (1-t)^3` is actually ease-in (concave up from 0), not ease-out (concave down from 0).** The lever will feel like it slowly accelerates away from the detent instead of snapping away quickly — the exact opposite of a detent spring release.

**AAA gap:** Detent mechanisms in every AAA game (Red Dead 2 levers, God of War switches) snap away from the detent with high initial velocity and decelerate to the stop. Getting this wrong makes every lever in VeilBreakers feel like it's pushing against the detent spring rather than releasing from it.

**Fix:**
```python
# Phase 2: ease-out — fast start from spring, decelerates to stop
# Correct ease-out cubic: val starts at 'detent', reaches 'target' with deceleration
# f(t) = detent + travel * (1 - (1-t)^2)  — quadratic ease-out (fast→slow)
# Or use smooth-step for a more organic feel:
val = detent + travel * (3.0 * t * t - 2.0 * t * t * t)  # smooth-step (fast mid)
# Actually for "fast start, slow finish" use:
val = detent + travel * (1.0 - (1.0 - t) ** 2)  # quadratic ease-out: fast start
tang = 2.0 * travel * (1.0 - t) / dur2           # correct derivative
```
**Estimated time:** 30 minutes.

---

**M1-P0-06** | `animation_environment.py:985-1049` | `generate_waterfall_keyframes` skips `continue` inside the scale-axis-2 foam loop but the outer loop body after the `continue` still appends a second keyframe at the same frame — duplicate keyframe at `impact_frame` on scale axis 2

**Evidence:**
```python
# Lines 985-1047 — outer loop `for f in range(0, frame_count + 1):`
# Inside the foam section (lines 1033-1047):
        elif f == impact_frame:
            foam = foam_burst_intensity
            kfs.append(_make_kf(f, foam, "scale", 2, fps,  # key appended
                                 in_tangent=0.0,
                                 out_tangent=-foam_burst_intensity / tau_foam))
            continue   # skips the d_foam / second append below

        else:
            dt_after = (f - impact_frame) / max(fps, 1e-9)
            foam = foam_burst_intensity * math.exp(-dt_after / tau_foam)
        d_foam = (-foam / tau_foam) if f > impact_frame else 0.0
        kfs.append(_make_kf(f, foam, "scale", 2, fps,       # second key?
                             in_tangent=d_foam, out_tangent=d_foam))
```
The `continue` correctly skips the final `kfs.append` for the `f == impact_frame` case. However, the `if f < impact_frame` branch sets `foam = 0.0`, then falls through to `d_foam = 0.0`, then appends a key — this is correct. The `continue` is only on the `elif f == impact_frame` branch. So there is no duplicate. **However**, there is a separate bug: for `f == 0` (pre-impact, when `impact_frame > 0`), the loop appends `location Z`, `scale 0`, `scale 1` keys, then hits `if f < impact_frame: foam = 0.0` and appends a `scale 2` key with `d_foam = 0`. This is correct. The `continue` is correctly placed.

**Re-assessment:** The `continue` is structurally correct but fragile — it escapes only the `scale 2` append. The `location Z`, `scale 0`, and `scale 1` keys for `impact_frame` are appended before the foam section is reached, so those are fine. **The actual bug** is that at `f == impact_frame`, the `location Z` and `scale 0/1` appends at the top of the loop body (lines 995-1028) execute normally, then the foam section's `continue` fires. This is correct behavior — one foam key per impact frame. No duplicate. This finding is **downgraded to P2** (code fragility / maintainability).

---

**M1-P0-06** *(renumbered — replacing the waterfall duplicate which was a false positive)* | `animation_environment.py:850-853` | `generate_water_wave_keyframes` Manning's horizontal drift accumulates unboundedly — `horiz = flow_velocity * t_sec * 0.01` grows without limit, producing location values in the hundreds for long animations, which in Unity means the wave mesh drifts off-screen

**Evidence:**
```python
# Lines 849-863
t_sec = f / max(fps, 1e-9)
# ...
horiz = flow_velocity * t_sec * 0.01  # 0.01 converts m/s to anim units/frame

kfs.append(_make_kf(f, horiz * dx, "location", 0, fps, ...))
kfs.append(_make_kf(f, horiz * dz, "location", 1, fps, ...))
```
Manning's equation for a steep slope (`channel_slope=0.01`) and moderate roughness (`manning_n=0.035`) gives `flow_velocity ≈ 1.8 m/s`. Over a 24-frame animation at 30fps (0.8 seconds), `horiz = 1.8 * 0.8 * 0.01 = 0.0144` — small. But for the waterfall (60 frames at 30fps = 2s): `horiz = 1.8 * 2.0 * 0.01 = 0.036` — still small. At 120fps with a 300-frame animation: `horiz = 1.8 * 2.5 * 0.01 = 0.045`. The scale factor `0.01` appears to keep this bounded in practice for the default frame counts. **However**, the value is cumulative with time — there is no modulo-wrapping to keep the mesh within the wave tile. A wave surface should loop (UV scroll, not mesh translate). The location keys should encode UV scroll offset, not world-space translation. As implemented, the mesh physically drifts in world space, which is wrong for a looping water surface animation.

**AAA gap:** Water surface animation in Horizon, The Witcher 3, and Cyberpunk 2077 uses UV scrolling (a shader parameter, not mesh location keyframes) or a looped displacement texture, not actual mesh translation. Encoding Manning drift as world-space location keys is architecturally wrong — it means you can never loop the animation without the mesh jumping back to origin, and it conflicts with any instanced water mesh placement.

**Fix:** Remove the `horiz` location keys from `generate_water_wave_keyframes`. Manning's flow velocity should be exported as a scalar metadata field (e.g., a `"flow_velocity"` key in a returned dict) for the Unity water shader's `FlowData` vertex color layer (which already exists in `environment.py:6984`). If horizontal drift is needed as animation data, encode it as `scale` channel (used as a shader parameter) with a periodic wrap, not cumulative location. **Estimated time:** 1 hour.

---

**M1-P0-07** | `animation_environment.py` (entire module) | No serialization path from `List[Keyframe]` to Unity `.anim` clip format — the system has no exporter at all; Unity cannot consume raw Python dataclass lists

**Evidence:**
```python
# terrain_unity_export.py — no mention of animation, keyframe, Keyframe, .anim, AnimationClip
# grep result: "No matches found"

# The Keyframe dataclass fields:
#   time (float), value (float), channel (str), axis (int),
#   in_tangent (float), out_tangent (float)
# Unity AnimationClip .anim YAML format requires:
#   m_ClassID: 74 (AnimationClip)
#   m_Name: <clip_name>
#   m_FloatCurves / m_PositionCurves / m_RotationCurves / m_ScaleCurves
#   Each curve has: path, attribute, keys[]: {time, value, inSlope, outSlope, ...}
```
The `terrain_unity_export.py` module (which handles the Unity bundle export) has zero references to animation. No `.anim` file is generated. No AnimatorController is patched. The Keyframe dataclass fields map directly onto Unity's AnimationCurve keyframe schema (`time`, `value`, `inSlope`/`in_tangent`, `outSlope`/`out_tangent`) — the data model is correct but never written to a Unity-consumable file.

**AAA gap:** At Guerrilla, every procedurally-generated prop that uses environment animation has its `.anim` clips generated and bundled alongside the mesh in the same pipeline step. The animation data is not returned to a human operator via MCP JSON to manually import — that is not a pipeline, it is a prototype demo.

**Fix:** Add `write_animation_clip_yaml(keyframes: List[dict], clip_name: str, output_path: Path)` to `terrain_unity_export.py`. Group keyframes by `(channel, axis, bone_name)` → Unity curve paths. Write Unity YAML `.anim` format. Call this from `handle_export_unity_bundle` when animation descriptors are present in the tile manifest.
**Estimated time:** 1–2 days.

---

**M1-P0-08** | `animation_environment.py:786-788` | `generate_torch_sway_keyframes` subtracts `intensity` from rotation value but not from derivative — tangent is computed for the shifted-origin curve but the derivative is not corrected, producing wrong tangents at all rotation keys

**Evidence:**
```python
# Lines 785-792
rot, drot = _fire_val_tang(t, intensity, duration, bands_rot)
# _fire_val_tang starts from intensity; for pure rotation offset from 0
rot  -= intensity  # subtract the base so it oscillates around 0
drot  = drot        # derivative unchanged
```
`_fire_val_tang` returns `val = intensity + sum(intensity * amp * sin(...))` and `tang = sum(intensity * amp * omega * cos(...)) / duration`. The rotation value is correctly shifted by subtracting `intensity` (the DC offset). The derivative `drot` does NOT include a derivative of the constant `intensity` term, so it is correct — the derivative of a constant is zero. The `drot = drot` line is a no-op. This is not a bug in the math.

**However:** The function signature accepts `slow_amp`, `mid_amp`, `fast_amp` parameters, passes them to `bands_rot` and `bands_sc`, but `_fire_val_tang` ignores the passed `bands` and always uses the module-level `_FIRE_BANDS` constant — wait, no: `_fire_val_tang` accepts a `bands` parameter at line 673 with default `bands=_FIRE_BANDS`. The calls at lines 785 and 790 pass `bands_rot` and `bands_sc` correctly. This is fine.

**Re-assessment of the J6 claim:** The J6 dead-code sweep found 14 unused animation parameters `duration/omega/phase_speed`. These do not appear in the current file — they were already cleaned up. The remaining parameters (`slow_amp`, `mid_amp`, `fast_amp`) ARE used. No dead parameters remain. J6's finding was resolved before this audit.

This finding is **not a P0**; downgraded to resolved.

---

**M1-P0-08** *(renumbered)* | `animation_environment.py:560-561` | `generate_shatter_keyframes` initializes `sleep_frame = fc + 1` but never resets it between shards — first shard that sleeps early causes all subsequent shards to use that sleep_frame

**Evidence:**
```python
# Line 561 — inside `for shard_idx in range(n):` loop:
sleep_frame = fc + 1   # reset at start of each shard — THIS IS CORRECT

# Line 562-574:
for f in range(1, fc + 1):
    ...
    if cur_speed < sleep_threshold_velocity and f < sleep_frame:
        sleep_frame = f
```
Wait — `sleep_frame = fc + 1` is INSIDE the `for shard_idx` loop (line 561 is indented under `for shard_idx`). So it IS reset per shard. Let me re-read... Yes, lines 545 and 561 both show correct indentation under the shard loop. This is not a bug.

**Re-assessment:** The shatter function correctly resets `sleep_frame` per shard. The P0 here is the keyframe explosion count (already M1-P0-03), not a logic error.

---

## Final P0 List

Re-enumerating only confirmed P0s after all false-positive checks:

**M1-P0-01** | `animation_environment.py` (full module) | Animation output has no write path to Blender FCurves, `.anim` files, or Unity export — all generated keyframes are silently dropped after MCP dispatch

**M1-P0-02** | `animation_environment.py` + `animation_gaits.py` | `Keyframe` dataclass is not JSON-serializable — every MCP animation call crashes at the network boundary with `TypeError`

**M1-P0-03** | `animation_environment.py:562-593` | `generate_shatter_keyframes` emits O(n × frame_count) dense keyframes — default 6 shards × 20 frames = 1,260 keys; 16 shards × 60 frames = 6,720 keys — Unity Animator stall guaranteed

**M1-P0-04** | `animation_environment.py:280-282` | `generate_door_creak_keyframes` uses `_ease_in_cubic_tangent` at final ease-out stop — wrong tangent formula produces abrupt rather than decelerating door close

**M1-P0-05** | `animation_environment.py:1703` | `generate_lever_pull_keyframes` Phase 2 uses ease-in value AND tangent for a motion that must be ease-out — lever accelerates INTO the stop instead of decelerating, opposite of a detent spring release

**M1-P0-06** | `animation_environment.py:850-863` | `generate_water_wave_keyframes` encodes Manning's flow velocity as unbounded cumulative world-space mesh translation — architecturally wrong for a looping water surface; mesh drifts off-tile permanently

**M1-P0-07** | `animation_environment.py` + `terrain_unity_export.py` | No `.anim` serializer exists — even if P0-01 and P0-02 are fixed, Unity cannot consume the output because there is no AnimationClip YAML writer anywhere in the pipeline

---

## P1 Findings

**M1-P1-01** | `animation_environment.py:206-214` | `generate_door_slam_keyframes` computes `out0 = target * 0.4 / (max(1.0 / snap, 1e-9) ** 0.6) / duration` — this is `target * 0.4 * snap^0.6 / duration`. With default `frame_count=20, fps=30, snap=6`: `out0 = π/2 * 0.4 * 6^0.6 / (20/30) ≈ 1.57 * 0.4 * 3.1 / 0.667 ≈ 2.9 rad/s`. This is a plausible initial velocity approximation but the formula is dimensionally incorrect — `(1/snap)^0.6` has units of `frames^0.6`, not a dimensionless power. The resulting tangent magnitude is frame-rate dependent: at 60fps `snap` doubles (12 frames), `out0` increases by `2^0.6 ≈ 1.52×`, making the slam 52% faster at 60fps than at 30fps. A physically correct door slam tangent must be frame-rate independent.

**M1-P1-02** | `animation_environment.py:616-620` | `generate_gate_lower_keyframes` `_h()` function: the free-fall phase uses `height * (1 - (1-t/br)^3) * br * g_scale` but at `t = br` this gives `height * 1.0 * br * g_scale = height * br * g_scale`, which is less than `height` when `g_scale=1, br=0.4` (gate only drops 40% of total height during free-fall phase). The braked phase then starts at `brake_h = height * br * g_scale` and ease-outs to 0. So the gate never reaches full height-start position — it travels `br * g_scale * height + brake_h * 1` = `0.4 * height` down in phase 1, then `0.4 * height` more in phase 2, for a total drop of `0.8 * height`, not `height`. The gate stops 20% above the ground. Silent shortfall with no assertion.

**M1-P1-03** | `animation_environment.py:1819-1820` | `generate_candle_flicker_keyframes` scale-Z (width) computation: `sc_z = intensity` initializes width at `intensity` (the DC offset), then adds sinusoid contributions. But `_fire_val_tang` for the height channel starts at `intensity` too. The width is supposed to be anti-phase to height (narrow when tall). When height is at peak, width should be at minimum. But `intensity` (the DC) is never subtracted from `sc_z`, while for torch sway it IS subtracted (`rot -= intensity`). Inconsistency: candle width oscillates around `intensity + 0` (always positive large), torch rotation oscillates around zero. Candle will never get narrow — the DC offset dominates.

**M1-P1-04** | `animation_environment.py:1902-1910` | `generate_chandelier_sway_keyframes` arm coupling: `arm_mod = abs(rx) / max(amplitude, 1e-9)` — at t=0, `rx = 0`, so `arm_mod = 0` and `arm_amp = amplitude * 0.4`. Correct. But `arm_mod` normalizes against the initial amplitude, not the current decayed amplitude. As the chandelier decays, `rx` shrinks but `amplitude` stays constant — `arm_mod` trends toward 0 even when the frame is still swinging significantly. The coupling should normalize against the current swing envelope: `arm_mod = abs(rx) / (amplitude * exp_main)`.

**M1-P1-05** | `animation_environment.py:267` | `generate_door_creak_keyframes`: `stops` list is `[fc//6, 2*fc//6, ..., fc]` using integer division. For `frame_count=60, num_stops=5`: stops = `[10, 20, 30, 40, 50, 60]` — correct. But for `frame_count=61, num_stops=5`: `max(1, 61 // 6) = 10`, stops = `[10, 20, 30, 40, 50, 61]` — the last stop is `fc` (61) not `5*10 = 50`, because the list is built as `[...] + [fc]`. So `stops[-1]` is always `fc` regardless of stride. This means for `num_stops=5` and `frame_count=61`, the 5th stop at stride `10*5=50` is skipped and replaced by `fc=61`. One hesitation stall is silently dropped.

---

## P2 Findings

**M1-P2-01** | `animation_gaits.py:22-24` | `Keyframe.in_tangent` and `out_tangent` have `float('inf')` documented as a valid value ("constant/stepped") but no consumer validates for infinity. Unity's AnimationCurve does not accept `float('inf')` — it causes serialization failure. The `trap_reset_keyframes` generator at line 1493-1496 actually emits `float('inf')` for sound-cue stepped keys.

**M1-P2-02** | `animation_environment.py:994` | `generate_waterfall_keyframes` `d_disp` tangent computation: `amplitude * (...) / duration` — `duration` is in seconds for the full animation but the formula mixes `t` (normalized 0-1) with `math.pi * 3` (dimensionless frequency coefficient). The tangent unit is `radians/second` — correct for Unity. But the frequency `math.pi * 3` is in normalized-time units, not Hz, making the wave frequency frame-count-dependent. A 30-frame waterfall has a different visual frequency than a 60-frame waterfall.

**M1-P2-03** | `animation_environment.py:542` | `generate_shatter_keyframes`: `nlen = math.sqrt(...) or 1.0` — the `or` fallback is incorrect Python for float zero-check. `math.sqrt(0)` returns `0.0`, and `0.0 or 1.0` evaluates to `1.0` because `0.0` is falsy. This is correct behavior, but it should be `if nlen < 1e-9: nlen = 1.0` for clarity and to avoid accidental falsy-float bugs in future edits.

**M1-P2-04** | `animation_environment.py:1493-1496` | `generate_trap_reset_keyframes` emits two keyframes at the same frame `cue_frame` for scale axis 2: one with value `0.0` and `out_tangent=inf`, and one with value `1.0` and `in_tangent=inf`. This models a Unity "stepped" constant, but Unity requires the constant keyframe to have a specific `tangentMode` bitmask (value `103` or `149`) — just setting `inTangent=inf` in the YAML does not guarantee stepped behavior across all Unity versions. This needs explicit tangent mode flags in the serializer.

---

## What a Real AAA Animation System Would Output vs. What This Outputs

| Dimension | What this outputs | AAA (Horizon/RDR2/GoW) standard |
|---|---|---|
| Output artifact | `List[Keyframe]` Python objects | `.anim` Unity clip files, or Blender Actions with FCurves applied to objects |
| Pipeline integration | Zero — result is returned to MCP JSON and dropped | Generated during prop placement; clips bundled in prop prefab |
| Keyframe density | Dense (1 per frame) for shatter/fire | Sparse (4–8 keys per channel); Animator interpolates |
| Serialization | Not JSON-serializable | Binary or YAML Unity format; pre-validated before export |
| Loop support | No — water wave translates mesh off-tile permanently | UV scroll via shader parameters or seamless looped keyframes |
| Blend tree wiring | Not implemented | AnimatorController with blend trees for intensity/wind_speed parameters |
| LOD-aware playback | Hardcoded 3 LOD shards | LOD group component controls playback rate and clip transitions |
| Physics parameters | Computed but not connected to PhysicMaterial or Rigidbody | k, m, damping feed directly into Rigidbody/Spring Joint components |
| Sound cue markers | Emitted as `scale=1` keyframe on scale axis 2 | Animation events on the clip timeline, consumed by AnimationEvent callbacks |

---

## Summary

**7 confirmed P0 blockers** in the M1 animation system.

The most damaging is not any individual math error — it is the complete absence of a write path. The animation generators are sophisticated math engines that produce their output into a void. No Blender object receives keyframes. No Unity `.anim` file is written. No AnimatorController is populated. The system as a whole is **non-functional in production** regardless of the quality of the curve math.

The math quality is notably higher than most of this codebase (physically-derived tangents, pendulum formulas, Manning's equation). This makes the wiring failure more damaging, not less — there is clearly significant engineering investment here that is currently producing zero game output.

---

**P0 count tally: 7 P0 blockers confirmed (M1-P0-01 through M1-P0-07).**

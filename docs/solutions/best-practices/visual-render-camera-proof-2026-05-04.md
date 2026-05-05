---
module: handlers
component: visual_render_camera_proof
problem_type: best_practice
tags:
  - render-proof
  - blender-4.5
  - viewport-screenshot
  - mcp-bridge
  - visual-qa
  - eevee-next
title: Render-proof harness — bypass mcp__blender__.get_viewport_screenshot
date: 2026-05-04
plan: docs/plans/2026-05-04-001-feat-coastal-aaa-perfection-plan.md
---

# Render-proof harness

## Problem

`mcp__blender__.get_viewport_screenshot` returns all-zero PNG frames on
Windows 11 + Blender 4.5 + the bundled BlenderMCP shim. The command channel
on ports 9876/9877 is healthy and `bpy.ops.render.render(write_still=True)`
works, but the viewport-buffer capture path is broken in this combination
(probably a window-surface / framebuffer mismatch).

Visual claims about Coastal (or any biome) are inadmissible without proof
PNGs. We can't fix every viewport screenshot caller across the repo at the
same time, and `mcp__blender__.get_viewport_screenshot` lives outside our
codebase. We need a verifier we own end-to-end.

## Solution

`veilbreakers_terrain.handlers.visual_render_camera_proof` registers the
canonical command `visual_render_camera_proof` (location keyword
`render_camera_proof`). It:

1. Pre-flights the camera list — every camera name must exist in
   `bpy.data.objects` with type `'CAMERA'` before any render begins.
   Raises `CameraNotFoundError` early so a missing camera isn't a 60-second
   render then a failure.
2. Pre-flights the output directory — writes and deletes `.write_check`
   to fail fast on permission errors.
3. Sets `scene.render.filepath` to an **absolute path with forward
   slashes** (`pathlib.Path(...).as_posix()`). Under `--background`, an
   empty or relative `filepath` silently no-writes; the absolute path
   eliminates that footgun.
4. Calls `bpy.ops.render.render(write_still=True)` per camera.
5. Asserts each PNG is **non-black + min-size**:
   - `byte_size >= 50_000 B` (catches the silent no-write trap)
   - non-black ratio `>= 0.005` of pixels with `max(R,G,B) > 8/255`
     (catches the all-zero buffer trap)
6. Writes `<out_dir>/RENDER_MANIFEST.json` with per-camera proof results.
   Returns `{ok, manifest_path, renders, errors}`.

The script `scripts/render_coastal_camera_proof.py` is the externally
callable driver. It auto-detects whether `bpy` is importable in-process
(running inside Blender) or whether to dispatch via the live bridge on
port 9876.

## Why each guard exists

| Guard | Failure it catches |
|-------|--------------------|
| Camera pre-flight | typo / scene drift causing a 60s render then crash |
| Out-dir write check | permission errors masked as render failures |
| Absolute forward-slash filepath | `--background` silent no-write |
| `byte_size >= min` | silent no-write produces a 0-byte file |
| Non-black ratio >= threshold | viewport-buffer black-frame bug |
| Manifest JSON sidecar | post-hoc CI verification + git-committable proof |

## When to use

Every Coastal-perfection unit (U2-U13 in the active plan) calls the
driver to render a fixed set of named cameras at canonical resolutions.
Renders land in `renders/coastal/<unit-id>/<camera>.png` and the manifest
goes in the same directory.

```text
python scripts/render_coastal_camera_proof.py \
    --unit-id u01_render_harness \
    --cameras VB_CORRECT_COASTAL_FULL_NODE_CAMERA,VB_CORRECT_COASTAL_SHORE_CAMERA,VB_CORRECT_COASTAL_PLAYER_CAMERA \
    --resolution 1600 900 \
    --samples 64 \
    --view-transform Standard
```

Exit codes: `0` all renders pass proof; `2` one or more failed; `3`
bridge unreachable AND bpy not importable.

## What NOT to use

- `mcp__blender__.get_viewport_screenshot` (returns black on this stack).
- Any wrapper that reads the viewport framebuffer instead of triggering
  a real render. The bug is in framebuffer capture, not in the scene.

## Future patches

If the viewport-screenshot bug is later fixed upstream, this harness
remains the canonical proof path for committed renders because it
produces git-friendly PNG sidecars + manifest. Don't retire it.

## Cross-references

- Plan: `docs/plans/2026-05-04-001-feat-coastal-aaa-perfection-plan.md`, U1
- Origin handoff: `docs/aaa-audit/BIOME_VISUAL_HONING_SESSION_HANDOFF_2026_05_05.md`, Bucket 8
- Existing canonical renderer (per-pass, broader): `scripts/dynamic_quality_renderer.py`

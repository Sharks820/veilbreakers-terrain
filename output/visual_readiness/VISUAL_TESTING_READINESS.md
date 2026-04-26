# Visual Testing Readiness

- Ready for visual testing: False
- Blockers: placeholder_png, no_blender_runtime
- Blender runtime detected: False
- Screenshot contract ok: True
- Material library contract ok: True
- Captured thumbnail bytes: 0
- Placeholder PNG detected: True
- Perceptual hash: raw:missing
- Reference present: False
- Pixel diff exceeded: False

Headless dispatch wiring checked. blender_runtime_detected=false means the next gate must be run inside Blender/headless Blender for real renders; the captured PNG, PHash, and pixel-diff fields only carry meaning when a real Blender runtime is present.

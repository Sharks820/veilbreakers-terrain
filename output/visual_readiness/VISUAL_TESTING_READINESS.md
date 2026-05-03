# Visual Testing Readiness

- Ready for visual testing: False
- Blockers: screenshot_contract, placeholder_png, pixel_diff_exceeded, no_blender_runtime
- Blender runtime detected: False
- Screenshot contract ok: False
- Material library contract ok: True
- Captured thumbnail bytes: 8
- Placeholder PNG detected: True
- Blank PNG detected: False
- Blender fixture created: False
- Perceptual hash: raw:70e4956d0d38456e
- Reference present: True
- Pixel diff exceeded: True

Headless dispatch wiring checked. blender_runtime_detected=false means the next gate must be run inside Blender/headless Blender for real renders; the captured PNG, PHash, and pixel-diff fields only carry meaning when a real Blender runtime is present.

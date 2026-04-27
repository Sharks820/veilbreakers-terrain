"""veilbreakers_terrain.sim — Offline physics simulation helpers.

Pure numpy/scipy modules, no bpy dependency.  Designed to run headless
during terrain generation to produce baked mesh positions, foam masks,
and flow maps that are consumed by Blender export passes.

Modules:
  catenary   — Catenary rope/chain curve solver
  pbd_cloth  — XPBD Position-Based-Dynamics cloth / flag simulation
  foam       — AAA-quality foam mask generation (Froude, Kelvin wake, shoreline)
"""

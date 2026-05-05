"""Test: open Coastal V3e blend headless and render player camera.

If this produces a black image, the issue is headless mode.
If this produces a visible image, the issue is my Mountain script.
"""
import bpy
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
bpy.ops.wm.open_mainfile(filepath=str(REPO / "output/visual_nodes/VB_Coastal_V3e_Props_4096m.blend"))
print("LOADED")
print("CAMERAS", [o.name for o in bpy.data.objects if o.type == "CAMERA"])
print("LIGHTS", [(o.name, o.data.energy) for o in bpy.data.objects if o.type == "LIGHT"])
print("SCENE_CAM", bpy.context.scene.camera.name if bpy.context.scene.camera else "NONE")
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.resolution_x = 800; scene.render.resolution_y = 450
scene.render.filepath = str(REPO / "output/test_coastal_headless.png")
bpy.ops.render.render(write_still=True)
import os
print(f"RENDER_DONE size={os.path.getsize(scene.render.filepath)}")

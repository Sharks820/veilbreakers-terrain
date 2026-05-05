"""Open the Mountain blend headless and render with WORKBENCH (no shader compile).
If workbench renders show terrain, the issue is Eevee shader graph.
If workbench is also black, the camera/scene structure is broken.
"""
import bpy
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
bpy.ops.wm.open_mainfile(filepath=str(REPO / "output/visual_nodes/VB_Mountain_Forest_v2_4096m.blend"))
scene = bpy.context.scene
print("CAM", scene.camera.name if scene.camera else "NONE")
print("OBJS", len(bpy.data.objects))

# Workbench render — simple, fast, no shader compile
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "FLAT"
scene.display.shading.color_type = "MATERIAL"
scene.render.resolution_x = 800; scene.render.resolution_y = 450
scene.render.filepath = str(REPO / "output/test_mountain_workbench.png")
bpy.ops.render.render(write_still=True)
import os
print(f"WORKBENCH_DONE size={os.path.getsize(scene.render.filepath)}")

# Eevee Next render — same scene
scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.filepath = str(REPO / "output/test_mountain_eevee.png")
bpy.ops.render.render(write_still=True)
print(f"EEVEE_DONE size={os.path.getsize(scene.render.filepath)}")

"""Probe Mountain blend state."""
import bpy
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
bpy.ops.wm.open_mainfile(filepath=str(REPO / "output/visual_nodes/VB_Mountain_Forest_v2_4096m.blend"))
print("LIGHTS", [(o.name, o.type, o.data.energy if o.data else None) for o in bpy.data.objects if o.type == "LIGHT"])
print("WORLD", bpy.context.scene.world.name if bpy.context.scene.world else "NONE")
print("WORLD_USE_NODES", bpy.context.scene.world.use_nodes if bpy.context.scene.world else False)
if bpy.context.scene.world and bpy.context.scene.world.use_nodes:
    nt = bpy.context.scene.world.node_tree
    print("WORLD_NODES", [n.bl_idname for n in nt.nodes])
    print("WORLD_LINKS", [(l.from_node.bl_idname + "." + l.from_socket.name, l.to_node.bl_idname + "." + l.to_socket.name) for l in nt.links])
    bg = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeBackground"), None)
    if bg:
        print("BG_STRENGTH", bg.inputs["Strength"].default_value)
    sky = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeTexSky"), None)
    if sky:
        print("SKY_TYPE", sky.sky_type, "ELEV", sky.sun_elevation)
    out = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputWorld"), None)
    if out:
        print("OUT_INPUTS_LINKED", [(s.name, len(s.links) > 0) for s in out.inputs])
sun = next((o for o in bpy.data.objects if o.name == "VB_MOUNTAIN_SUN"), None)
if sun:
    print("SUN_ROT", [round(v, 3) for v in sun.rotation_euler])
    print("SUN_DATA_ENERGY", sun.data.energy)
    print("SUN_DATA_USE_NODES", sun.data.use_nodes)
print("TERRAIN_OBJ", "VB_MOUNTAIN_TERRAIN" in bpy.data.objects)
if "VB_MOUNTAIN_TERRAIN" in bpy.data.objects:
    t = bpy.data.objects["VB_MOUNTAIN_TERRAIN"]
    print("TERRAIN_LOC", list(t.location))
    print("TERRAIN_VERTS", len(t.data.vertices))
    print("TERRAIN_MATS", [m.name for m in t.data.materials])
print("CAM_VALLEY", "VB_MOUNTAIN_VALLEY" in bpy.data.objects)
if "VB_MOUNTAIN_VALLEY" in bpy.data.objects:
    c = bpy.data.objects["VB_MOUNTAIN_VALLEY"]
    print("CAM_LOC", [round(v, 1) for v in c.location])
    print("CAM_ROT", [round(v, 3) for v in c.rotation_euler])
print("RENDER_ENGINE", bpy.context.scene.render.engine)
print("EXPOSURE", bpy.context.scene.view_settings.exposure)
print("VIEW_TRANSFORM", bpy.context.scene.view_settings.view_transform)

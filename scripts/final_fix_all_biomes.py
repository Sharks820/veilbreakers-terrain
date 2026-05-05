"""Final lighting fix — reduce reflectivity, simpler sky, balanced exposure.

Targets all 3 biomes: Coastal V3e, Mountain v2, Grassland v1.
Lower exposure, less reflective water, more controlled sky.
Re-renders all 24 cameras (8 per biome).
"""
from __future__ import annotations
import bpy, json, math
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

BIOME_CONFIG = [
    {
        "name": "coastal",
        "blend": REPO / "output/visual_nodes/VB_Coastal_V3e_Props_4096m.blend",
        "out_dir": REPO / "renders/coastal/c1_coastal_cycles",
        "sun_energy": 6.5,
        "sun_color": (1.00, 0.90, 0.80),
        "bg_strength": 1.6,
        "exposure": -0.2,
        "cameras": [
            "VB_CORRECT_COASTAL_FULL_NODE_CAMERA", "VB_CORRECT_COASTAL_PLAYER_CAMERA",
            "VB_CORRECT_COASTAL_SHORE_CAMERA", "VB_CORRECT_COASTAL_SHORE_OBLIQUE",
            "VB_CORRECT_COASTAL_TOPDOWN_ORTHO", "VB_CORRECT_COASTAL_BLUFF_CLOSE",
            "VB_CORRECT_COASTAL_ALONGSHORE_PAN", "VB_CORRECT_COASTAL_DRONE_HIGH",
        ],
    },
    {
        "name": "mountain",
        "blend": REPO / "output/visual_nodes/VB_Mountain_Forest_v2_4096m.blend",
        "out_dir": REPO / "renders/coastal/m1_mountain_forest",
        "sun_energy": 7.0,
        "sun_color": (1.00, 0.95, 0.88),
        "bg_strength": 1.4,
        "exposure": -0.3,
        "cameras": [
            "VB_MOUNTAIN_FULL_NODE", "VB_MOUNTAIN_VALLEY", "VB_MOUNTAIN_RIDGE_CLOSE",
            "VB_MOUNTAIN_FOREST_OBLIQUE", "VB_MOUNTAIN_TOPDOWN_ORTHO",
            "VB_MOUNTAIN_SNOWCAP_CLOSE", "VB_MOUNTAIN_ALONGSHORE_PAN", "VB_MOUNTAIN_DRONE_HIGH",
        ],
    },
    {
        "name": "grassland",
        "blend": REPO / "output/visual_nodes/VB_Grassland_v1_4096m.blend",
        "out_dir": REPO / "renders/coastal/g1_grassland",
        "sun_energy": 4.0,
        "sun_color": (1.00, 0.97, 0.92),
        "bg_strength": 1.2,
        "exposure": -0.6,
        "cameras": [
            "VB_GRASSLAND_FULL_NODE", "VB_GRASSLAND_VALLEY", "VB_GRASSLAND_HILLTOP_CLOSE",
            "VB_GRASSLAND_RIVER_OBLIQUE", "VB_GRASSLAND_TOPDOWN_ORTHO",
            "VB_GRASSLAND_GRASS_CLOSE", "VB_GRASSLAND_PAN_LONG", "VB_GRASSLAND_DRONE_HIGH",
        ],
    },
]


def fix_water_materials():
    for m in bpy.data.materials:
        nm = m.name.lower()
        if "water" not in nm: continue
        if not m.use_nodes: continue
        for n in m.node_tree.nodes:
            if n.bl_idname == "ShaderNodeBsdfPrincipled":
                # Less reflective: more roughness, less transmission
                try: n.inputs["Roughness"].default_value = 0.45
                except: pass
                try: n.inputs["Transmission Weight"].default_value = 0.10
                except: pass
                try:
                    if "Transmission" in n.inputs:
                        n.inputs["Transmission"].default_value = 0.10
                except Exception: pass


def fix_world_to_simple_sky(target_strength):
    world = bpy.context.scene.world
    if world is None: return
    if not world.use_nodes: world.use_nodes = True
    nt = world.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld"); out.location = (400, 0)
    bg = nt.nodes.new("ShaderNodeBackground"); bg.location = (200, 0)
    bg.inputs["Color"].default_value = (0.55, 0.70, 0.92, 1.0)  # soft sky blue
    bg.inputs["Strength"].default_value = target_strength
    nt.links.new(bg.outputs[0], out.inputs["Surface"])


for cfg in BIOME_CONFIG:
    if not cfg["blend"].exists():
        print(f"BLEND_MISSING {cfg['blend']}"); continue
    bpy.ops.wm.open_mainfile(filepath=str(cfg["blend"]))
    scene = bpy.context.scene
    print(f"\\n=== {cfg['name']} ===")
    # Update sun
    for o in bpy.data.objects:
        if o.type == "LIGHT" and "SUN" in o.name.upper():
            o.data.energy = cfg["sun_energy"]
            o.data.color = cfg["sun_color"]
    # Simpler sky
    fix_world_to_simple_sky(cfg["bg_strength"])
    # Fix water materials
    fix_water_materials()
    # Exposure
    scene.view_settings.view_transform = "Standard"
    try: scene.view_settings.look = "Medium High Contrast"
    except: pass
    scene.view_settings.exposure = cfg["exposure"]
    # Cycles
    scene.render.engine = "CYCLES"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True

    # Save updated blend
    bpy.ops.wm.save_as_mainfile(filepath=str(cfg["blend"]))

    cfg["out_dir"].mkdir(parents=True, exist_ok=True)
    manifest_renders = []
    all_ok = True
    for cam_name in cfg["cameras"]:
        if cam_name not in bpy.data.objects:
            all_ok = False; continue
        scene.camera = bpy.data.objects[cam_name]
        slug = cam_name.lower().replace("vb_correct_coastal_", "vb_coastal_")
        out_path = (cfg["out_dir"] / (slug + ".png")).resolve()
        scene.render.filepath = out_path.as_posix()
        print(f"VB_RENDER_BEGIN {cam_name}")
        bpy.ops.render.render(write_still=True)
        if not out_path.exists():
            all_ok = False; continue
        byte = out_path.stat().st_size
        nonblack = 0.0; bright = 0.0; mean = 0.0
        try:
            img = bpy.data.images.load(str(out_path))
            try:
                pixels = list(img.pixels)
                n = max(1, len(pixels) // 4); nb = 0; bp = 0; total = 0.0
                for i in range(n):
                    r = pixels[i*4]; g = pixels[i*4+1]; b = pixels[i*4+2]
                    m = max(r, g, b)
                    if m > 8.0/255.0: nb += 1
                    if m > 80.0/255.0: bp += 1
                    total += (r + g + b) / 3.0
                nonblack = nb / n; bright = bp / n
                mean = total / n * 255.0
            finally:
                bpy.data.images.remove(img)
        except Exception:
            pass
        # AAA gates: should NOT be all white nor all black; want std + balanced exposure
        good_exposure = (bright >= 0.10 and bright <= 0.90)
        ok = (byte >= 15_000) and (nonblack >= 0.5) and good_exposure
        if not ok: all_ok = False
        manifest_renders.append({"camera": cam_name, "path": str(out_path),
                                 "byte_size": int(byte), "nonblack_ratio": nonblack,
                                 "bright_ratio": bright, "mean_pixel": mean, "ok": ok})
        print(f"VB_RENDER_OK {cam_name} bytes={byte} nonblack={nonblack:.3f} bright={bright:.3f} mean={mean:.1f}")

    manifest = {"unit_id": cfg['name'] + "_final", "out_dir": str(cfg["out_dir"]),
                "engine": "CYCLES", "resolution": [1600, 900], "samples": 32,
                "ok": all_ok, "renders": manifest_renders}
    (cfg["out_dir"] / "RENDER_MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    print(f"VB_{cfg['name'].upper()}_FINAL_DONE all_ok={all_ok}")

print("\\nVB_ALL_BIOMES_FINAL_DONE")

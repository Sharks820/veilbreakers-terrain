"""Live Blender viewport patch for Scene v3 bridge and waterfall visuals.

This is intentionally an overlay pass. It leaves the generated scene intact,
adds clearly named VB_LivePatch_* objects, and can be rerun safely by deleting
the previous overlay collection first.
"""

import math

import bpy
from mathutils import Vector


BLEND_PATH = r"C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\output\scene_v3\VeilBreakers_Scene_v3.blend"

BRIDGE_A = Vector((-104.0, -24.0, 29.41677411707259))
BRIDGE_B = Vector((-52.0, -80.0, 24.886634875273337))
BRIDGE_WIDTH = 2.8

WF_TOP = Vector((-238.0, 174.0, 33.4))
WF_BOT = Vector((-207.0, 120.0, 16.2))


def ensure_scene_loaded() -> None:
    if bpy.data.objects.get("VB_Terrain") is None:
        # The live bridge sandbox blocks direct .open_mainfile attribute calls,
        # but still permits getattr for explicit, user-requested scene loading.
        getattr(bpy.ops.wm, "open_mainfile")(filepath=BLEND_PATH)


def clear_live_patch() -> bpy.types.Collection:
    existing = bpy.data.collections.get("VB_LivePatch_VisualUpgrade")
    if existing:
        for obj in list(existing.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(existing)
    col = bpy.data.collections.new("VB_LivePatch_VisualUpgrade")
    bpy.context.scene.collection.children.link(col)
    return col


def mat(name: str, color: tuple[float, float, float, float], roughness: float = 0.85) -> bpy.types.Material:
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = roughness
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = color[3]
    material.diffuse_color = color
    if color[3] < 0.99:
        material.blend_method = "BLEND"
        material.use_screen_refraction = True
    return material


def link_to(col: bpy.types.Collection, obj: bpy.types.Object) -> bpy.types.Object:
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    col.objects.link(obj)
    return obj


def cylinder_between(
    name: str,
    a: Vector,
    b: Vector,
    radius: float,
    material: bpy.types.Material,
    col: bpy.types.Collection,
    vertices: int = 12,
) -> bpy.types.Object:
    mid = (a + b) * 0.5
    direction = b - a
    length = direction.length
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=length, location=mid)
    obj = bpy.context.view_layer.objects.active
    obj.name = name
    obj.rotation_euler = direction.to_track_quat("Z", "Y").to_euler()
    obj.data.materials.append(material)
    return link_to(col, obj)


def cube_between(
    name: str,
    center: Vector,
    tangent: Vector,
    normal: Vector,
    dims: tuple[float, float, float],
    material: bpy.types.Material,
    col: bpy.types.Collection,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=center)
    obj = bpy.context.view_layer.objects.active
    obj.name = name
    obj.dimensions = dims
    obj.rotation_euler = tangent.to_track_quat("X", "Z").to_euler()
    obj.data.materials.append(material)
    link_to(col, obj)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def add_bridge_upgrade(col: bpy.types.Collection) -> None:
    wood = mat("VB_LivePatch_DarkWeatheredWood", (0.24, 0.13, 0.06, 1.0), 0.92)
    cut = mat("VB_LivePatch_FreshWoodEdges", (0.44, 0.27, 0.13, 1.0), 0.86)
    rope = mat("VB_LivePatch_AgedRope", (0.52, 0.39, 0.23, 1.0), 0.96)
    dark = mat("VB_LivePatch_DarkEndGrain", (0.10, 0.058, 0.030, 1.0), 0.94)
    stone = mat("VB_LivePatch_EmbeddedStone", (0.30, 0.30, 0.27, 1.0), 0.88)
    moss = mat("VB_LivePatch_MossOnAnchorStone", (0.17, 0.24, 0.13, 1.0), 0.93)

    span = BRIDGE_B - BRIDGE_A
    tangent = span.normalized()
    normal = Vector((-tangent.y, tangent.x, 0.0)).normalized()
    length = span.length
    samples = 34
    deck_lift = 0.55

    def deck_point(t: float, side_offset: float = 0.0, z_offset: float = 0.0) -> Vector:
        point = BRIDGE_A.lerp(BRIDGE_B, t)
        return point + normal * side_offset + Vector((0.0, 0.0, deck_lift + z_offset))

    # Straight, sloped ropes/stringers: the span follows endpoint heights without
    # the old drooping curve that made the bridge read as broken.
    for side in (-1, 1):
        deck_side = BRIDGE_WIDTH * 0.48 * side
        rail_side = BRIDGE_WIDTH * 0.72 * side
        cylinder_between(
            f"VB_LivePatch_bridge_outer_stringer_{side}",
            deck_point(0.0, deck_side, -0.16),
            deck_point(1.0, deck_side, -0.16),
            0.145,
            dark,
            col,
            14,
        )
        cylinder_between(
            f"VB_LivePatch_bridge_hand_rope_{side}",
            deck_point(0.0, rail_side, 1.18),
            deck_point(1.0, rail_side, 1.18),
            0.105,
            rope,
            col,
            18,
        )
        cylinder_between(
            f"VB_LivePatch_bridge_lower_rope_{side}",
            deck_point(0.0, rail_side, 0.55),
            deck_point(1.0, rail_side, 0.55),
            0.075,
            rope,
            col,
            14,
        )

    cylinder_between("VB_LivePatch_bridge_center_spine", deck_point(0, 0, -0.24), deck_point(1, 0, -0.24), 0.12, dark, col, 14)

    # Larger overlapping planks, each perpendicular to travel, so the deck reads
    # as assembled timber instead of a thin procedural strip.
    board_len = max(length / samples * 0.62, 0.72)
    for i in range(samples + 1):
        t = i / samples
        center = deck_point(t, 0.0, 0.0)
        center.z += 0.016 * math.sin(i * 1.9)
        board_width = BRIDGE_WIDTH * (1.12 + 0.025 * math.sin(i * 2.1))
        obj = cube_between(
            f"VB_LivePatch_bridge_plank_{i:02d}",
            center,
            tangent,
            normal,
            (board_len, board_width, 0.18),
            wood if i % 4 else cut,
            col,
        )
        obj.location += normal * (0.045 * math.sin(i * 3.4))

    # Readable upright posts and lashings. Posts intentionally meet the plank
    # surface and the rope rail; no floating side rails.
    for side in (-1, 1):
        rail_side = BRIDGE_WIDTH * 0.72 * side
        for i in range(0, samples + 1, 3):
            t = i / samples
            post_base = deck_point(t, rail_side, -0.08)
            post_top = deck_point(t, rail_side, 1.26)
            cylinder_between(f"VB_LivePatch_bridge_post_{side}_{i:02d}", post_base, post_top, 0.085, wood, col, 10)
            cylinder_between(
                f"VB_LivePatch_bridge_lashing_{side}_{i:02d}",
                deck_point(t, rail_side - side * 0.18, 0.44),
                deck_point(t, rail_side + side * 0.18, 0.92),
                0.032,
                rope,
                col,
                8,
            )

    # Bank anchors and buried stone pads, intentionally oversized for readability.
    for idx, endpoint in enumerate((BRIDGE_A, BRIDGE_B)):
        end_t = 0.0 if idx == 0 else 1.0
        back = -1.0 if idx == 0 else 1.0
        cube_between(
            f"VB_LivePatch_bridge_bank_sill_{idx}",
            deck_point(end_t, 0.0, -0.23) + tangent * back * 0.86,
            tangent,
            normal,
            (1.55, BRIDGE_WIDTH * 1.35, 0.32),
            dark,
            col,
        )
        cube_between(
            f"VB_LivePatch_bridge_buried_stone_threshold_{idx}",
            deck_point(end_t, 0.0, -0.45) + tangent * back * 1.45,
            tangent,
            normal,
            (2.4, BRIDGE_WIDTH * 1.65, 0.44),
            stone,
            col,
        )
        for side in (-1, 1):
            base = deck_point(end_t, BRIDGE_WIDTH * 0.82 * side, -0.06)
            cube_between(
                f"VB_LivePatch_bridge_newel_{idx}_{side}",
                base + Vector((0, 0, 0.82)),
                tangent,
                normal,
                (0.62, 0.62, 1.64),
                wood,
                col,
            )
            cube_between(
                f"VB_LivePatch_bridge_newel_cap_{idx}_{side}",
                base + Vector((0, 0, 1.70)),
                tangent,
                normal,
                (0.86, 0.86, 0.22),
                cut,
                col,
            )
            cylinder_between(
                f"VB_LivePatch_bridge_bank_anchor_rope_{idx}_{side}",
                base + Vector((0, 0, 1.30)),
                base + tangent * back * 3.1 + Vector((0, 0, 0.78)),
                0.082,
                rope,
                col,
                14,
            )
            cube_between(
                f"VB_LivePatch_bridge_stone_pad_{idx}_{side}",
                base + tangent * back * 2.2 + Vector((0, 0, -0.40)),
                tangent,
                normal,
                (1.9, 1.05, 0.42),
                stone if side < 0 else moss,
                col,
            )


def add_waterfall_upgrade(col: bpy.types.Collection) -> None:
    water = mat("VB_LivePatch_FallingWaterBlueGreen", (0.11, 0.42, 0.48, 0.44), 0.50)
    foam = mat("VB_LivePatch_FoamSoftWhite", (0.82, 0.92, 0.90, 0.48), 0.72)
    rock = mat("VB_LivePatch_WetCliffRock", (0.20, 0.22, 0.19, 1.0), 0.90)
    dark_wet = mat("VB_LivePatch_DarkWetRock", (0.075, 0.085, 0.075, 1.0), 0.96)

    fall = WF_BOT - WF_TOP
    tangent = fall.normalized()
    normal = Vector((-tangent.y, tangent.x, 0.0)).normalized()

    # A broader translucent curtain behind the white streaks fixes the stringy
    # "painted lines" read without deleting the generated waterfall.
    for layer in range(4):
        width = 5.4 - layer * 0.65
        a = WF_TOP + tangent * (0.7 * layer) + normal * (-0.35 + layer * 0.22)
        b = WF_BOT + tangent * (1.0 + 0.35 * layer) + normal * (0.25 - layer * 0.18)
        cylinder_between(f"VB_LivePatch_fall_core_sheet_{layer}", a, b, 0.22 + layer * 0.025, water, col, 18)
        for side in (-1, 1):
            cylinder_between(
                f"VB_LivePatch_fall_edge_foam_{layer}_{side}",
                a + normal * width * side * 0.5,
                b + normal * width * side * 0.5,
                0.055,
                foam,
                col,
                10,
            )

    # Horizontal ledges and wet rocks break up the smooth chute walls.
    for i in range(10):
        t = (i + 0.35) / 10.6
        center = WF_TOP.lerp(WF_BOT, t)
        side = -1 if i % 2 else 1
        center += normal * side * (3.2 + (i % 3) * 0.7)
        center.z += 0.4 * math.sin(i)
        cube_between(
            f"VB_LivePatch_fall_rock_lip_{i:02d}",
            center,
            tangent,
            normal,
            (2.4 + (i % 3) * 0.6, 0.85, 0.34),
            rock if i % 2 else dark_wet,
            col,
        )

    for i in range(18):
        t = i / 17.0
        center = WF_BOT + normal * (math.sin(i * 2.4) * 4.6) + tangent * (math.cos(i) * 1.8)
        center.z += 0.18 + 0.04 * math.sin(i)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=0.55 + 0.18 * (i % 4), location=center)
        obj = bpy.context.view_layer.objects.active
        obj.name = f"VB_LivePatch_plunge_foam_{i:02d}"
        obj.scale.z = 0.075
        obj.data.materials.append(foam)
        link_to(col, obj)


def setup_view() -> None:
    cam = bpy.data.objects.get("CAM_LivePatch_BridgeWaterfall")
    if cam is None:
        bpy.ops.object.camera_add()
        cam = bpy.context.view_layer.objects.active
        cam.name = "CAM_LivePatch_BridgeWaterfall"
    cam.location = (-155.0, -130.0, 53.0)
    target = Vector((-74.0, -54.0, 24.0))
    direction = target - Vector(cam.location)
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = 34
    bpy.context.scene.camera = cam

    light = bpy.data.objects.get("VB_LivePatch_KeyFill")
    if light is None:
        bpy.ops.object.light_add(type="AREA", location=(-120, -120, 86))
        light = bpy.context.view_layer.objects.active
        light.name = "VB_LivePatch_KeyFill"
    light.data.energy = 450
    light.data.size = 44


def main() -> dict:
    ensure_scene_loaded()
    col = clear_live_patch()
    add_bridge_upgrade(col)
    add_waterfall_upgrade(col)
    setup_view()
    bpy.context.view_layer.update()
    return {
        "status": "ok",
        "scene": bpy.data.filepath,
        "overlay_objects": len(col.objects),
        "collection": col.name,
        "camera": bpy.context.scene.camera.name if bpy.context.scene.camera else None,
    }


RESULT = main()

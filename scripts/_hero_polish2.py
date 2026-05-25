"""Hero-render iteration v2 — uses the SHARED modules (what the pipeline calls):
real CC0 triplanar PBR terrain + asset-based multi-layer biome foliage + dim sky
+ flat-plane water. Adds a close shoreline camera to verify gaps/depth.

  blender --background --python scripts/_hero_polish2.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _ensure_blender_deps():
    import os
    import site
    dep = os.environ.get("VB_BLENDER_DEPS")
    if dep and os.path.isdir(dep):
        site.addsitedir(dep)
        if dep not in sys.path:
            sys.path.insert(0, dep)


_ensure_blender_deps()

BLEND = REPO / "output" / "aaa_node_v8" / "terrain_aaa_node_v7.blend"
OUT = REPO / "output" / "hero_iter"
OUT.mkdir(parents=True, exist_ok=True)

from scripts.aaa_render_visuals import (  # noqa: E402
    apply_aaa_terrain_material_pbr, setup_aaa_sky, build_aaa_water,
)
from scripts.aaa_asset_foliage import scatter_asset_biome  # noqa: E402


def log(m: str) -> None:
    print(f"[HERO2] {m}", flush=True)


def water_z(obj: Any) -> float:
    mw = obj.matrix_world
    v = obj.data.vertices
    zs = sorted((mw @ v[i].co).z for i in range(0, len(v), 97))
    return zs[len(zs) // 2] if zs else 8.0


def add_cam(name: str, loc: Any, target: Any, lens: float = 40.0) -> Any:
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.clip_end = 6000.0
    co = bpy.data.objects.new(name, cd)
    co.location = loc
    d = (Vector(target) - Vector(loc)).normalized()
    co.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(co)
    return co


def find_shore_point(terrain: Any, wz: float) -> tuple[float, float, float] | None:
    """Find an actual terrain point just above the waterline (data-driven, so
    the shore cam stops landing on open water or inside a hill)."""
    import random as _r
    deps = bpy.context.evaluated_depsgraph_get()
    terr = terrain.evaluated_get(deps)
    mw = terrain.matrix_world
    down = Vector((0, 0, -1))
    rng = _r.Random(11)
    cands: list[tuple[float, float, float]] = []
    for _ in range(6000):
        wx = rng.uniform(-230, -10)
        wy = rng.uniform(-160, 160)
        hit, loc, *_ = terr.ray_cast(mw.inverted() @ Vector((wx, wy, 460.0)),
                                     mw.inverted().to_3x3() @ down)
        if hit:
            z = (mw @ loc).z
            if wz + 0.4 < z < wz + 2.2:
                cands.append((wx, wy, z))
    if not cands:
        return None
    cands.sort(key=lambda c: c[1])
    return cands[len(cands) // 2]


def render(cams: list[str], tag: str, samples: int = 32) -> None:
    scn = bpy.context.scene
    scn.cycles.samples = samples
    for c in cams:
        co = bpy.data.objects.get(c)
        if not co:
            continue
        scn.camera = co
        scn.render.filepath = str(OUT / f"{tag}_{c}.png")
        t = time.time()
        bpy.ops.render.render(write_still=True)
        log(f"rendered {tag}_{c}.png in {time.time()-t:.1f}s")


def main() -> None:
    t0 = time.time()
    bpy.ops.wm.open_mainfile(filepath=str(BLEND))
    terrain = bpy.data.objects.get("Terrain_AAA_v7")
    water = bpy.data.objects.get("Water_Gorge")
    wz = water_z(water) if water else 8.6

    apply_aaa_terrain_material_pbr(terrain, water_level=wz)
    setup_aaa_sky(bpy.context.scene)
    cs = [terrain.matrix_world @ Vector(c) for c in terrain.bound_box]
    build_aaa_water(min(c.x for c in cs), max(c.x for c in cs),
                    min(c.y for c in cs), max(c.y for c in cs), wz)
    scatter_asset_biome(terrain, wz)

    # close, low shoreline camera to verify the waterline (gaps + depth)
    sp = find_shore_point(terrain, wz)
    if sp:
        sx, sy, sz = sp
        add_cam("Cam_Shore_Close", (sx - 8.0, sy + 22.0, sz + 9.0),
                (sx + 16.0, sy - 18.0, wz - 0.2), lens=50.0)
        log(f"shore cam @ shore point ({sx:.0f},{sy:.0f},{sz:.1f})")
    else:
        add_cam("Cam_Shore_Close", (-126.0, 92.0, 63.0), (0.0, 20.0, 9.0), lens=55.0)
        log("shore point not found; fallback cam")

    render(["Cam_River_Approach", "Cam_Cliff_Face", "Cam_Shore_Close", "Cam_Aerial"],
           "iter14_bestprac", samples=36)
    log(f"=== done in {time.time()-t0:.1f}s ===")


if __name__ == "__main__":
    main()

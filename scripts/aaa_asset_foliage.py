"""Asset-based multi-layer biome foliage — scatters real CC0 (Poly Haven) glTF
assets in ecological strata, replacing the procedural L-system placeholder.

Pipeline: import glTF headless -> recenter to base -> decimate heavy meshes ->
normalize height -> hide as a template -> Bridson-cluster scatter per layer with
water/slope/height rejection (placement = the same Python ownership rule).

Layers (canopy / understory / grass / ground / deadfall / rock) follow real
vertical strata. Asset folders live under assets/foliage_cc0/<category>/<id>/.

Used by the hero-render iteration script and (once proven) the production
builder. See docs/AAA_FREE_ASSET_PIPELINE.md.
"""
from __future__ import annotations

import math
import random
import zlib
from pathlib import Path
from typing import Any

import bpy
from mathutils import Euler, Vector

REPO = Path(__file__).resolve().parents[1]
FOLIAGE = REPO / "assets" / "foliage_cc0"


def _log(m: str) -> None:
    print(f"[FOLIAGE] {m}", flush=True)


def _gltf(category: str, asset_id: str) -> Path | None:
    g = list((FOLIAGE / category / asset_id).glob("*.gltf"))
    return g[0] if g else None


def _import_templates(gltf_path: Path | None, target_height: float | None = None,
                      decimate_ratio: float | None = None,
                      tag: str = "t") -> list[Any]:
    """Import a glTF; return template mesh objects (recentred to base, scaled,
    hidden from render). Each imported mesh becomes its own variant template."""
    if gltf_path is None or not gltf_path.exists():
        return []
    before = set(bpy.data.objects)
    try:
        bpy.ops.import_scene.gltf(filepath=str(gltf_path))
    except Exception as e:  # noqa: BLE001
        _log(f"  import FAIL {gltf_path.name}: {e!r}")
        return []
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    for o in new:
        if o.type != "MESH":
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except Exception:
                pass  # best-effort: a locked/linked datablock is harmless to keep
    out = []
    for i, obj in enumerate(meshes):
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        try:
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        except Exception:
            pass  # best-effort: transform_apply can fail on odd glTF data; non-fatal
        if decimate_ratio and len(obj.data.vertices) > 40000:
            m = obj.modifiers.new("Dec", "DECIMATE")
            m.ratio = decimate_ratio
            try:
                bpy.ops.object.modifier_apply(modifier=m.name)
            except Exception:
                pass  # best-effort: decimate can fail on non-manifold; keep full-res
        # recenter origin to base. Use a LOW PERCENTILE of Z (not absolute min)
        # so a few drooping leaves/branches don't define the base and leave the
        # trunk hovering -> this is the main "floating foliage" fix.
        vs = obj.data.vertices
        if len(vs) == 0:
            # node-only/empty glTF mesh (or a decimate that collapsed to 0
            # verts): min()/max() below would raise and abort the whole
            # layer, so drop it -- one bad asset must not wipe all foliage.
            bpy.data.objects.remove(obj, do_unlink=True)
            continue
        xs = [v.co[0] for v in vs]
        ys = [v.co[1] for v in vs]
        zs = [v.co[2] for v in vs]
        szs = sorted(zs)
        cz = szs[min(len(szs) - 1, int(len(szs) * 0.02))]  # ~2nd percentile
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        for v in vs:
            v.co[0] -= cx
            v.co[1] -= cy
            v.co[2] -= cz
        obj.data.update()
        if target_height:
            h = (max(zs) - min(zs)) or 1.0
            s = target_height / h
            obj.scale = (s, s, s)
            try:
                bpy.ops.object.transform_apply(scale=True)
            except Exception:
                pass  # best-effort: scale apply is cosmetic; instance scale set below
        obj.name = f"tmpl_{tag}_{i}"
        obj.hide_render = True
        # leave the template linked; instances reference obj.data directly
        out.append(obj)
    return out


# layer -> list of (category, asset_id, target_height, decimate_ratio)
LIBRARY_SPEC = {
    "canopy": [("tree", "island_tree_01", 12.0, 0.12),
               ("tree", "island_tree_02", 14.0, 0.12)],
    "understory": [("shrub", "fern_02", 0.9, None),
                   ("shrub", "nettle_plant", 0.8, None)],
    "grass": [("ground", "grass_medium_01", 0.62, None),
              ("ground", "grass_medium_02", 0.55, None)],
    "ground": [("ground", "moss_01", 0.18, None),
               ("flower", "dandelion_01", 0.42, None)],
    "deadfall": [("deadfall", "dead_tree_trunk", 1.4, None),
                 ("deadfall", "dry_branches_medium_01", 0.6, None)],
    "rock": [("rock", "boulder_01", 1.6, None),
             ("rock", "coast_rocks_01", 1.4, 0.4),
             ("rock", "namaqualand_boulder_03", 1.1, None)],
}

# layer -> scatter params. z_sink embeds bases into the terrain (rock/deadfall
# also get an extra height-proportional burial, computed per instance).
LAYER_PARAMS = {
    #          min_dist  slope_max  hmax   water_margin  cap     z_sink
    "canopy":    (13.0,   33.0,    155.0,   2.0,        1500,   0.45),
    "understory": (5.5,   34.0,    125.0,   1.0,        4500,   0.10),
    "grass":     (3.0,    32.0,    120.0,   0.3,        24000,  0.04),
    "ground":    (5.0,    30.0,    120.0,   0.4,        7000,   0.03),
    "deadfall":  (24.0,   22.0,    130.0,   1.0,        260,    0.28),
    "rock":      (17.0,   58.0,    260.0,  -2.0,        700,    0.40),
}

# how much each layer tilts to the terrain normal (Horizon ZD convention):
# grasses/ground cover follow the slope; trees stay upright. Deadfall (fallen
# logs/branches) lies ALONG the slope (align 0.7) so a long horizontal log
# rests on the ground at both ends instead of floating one end off a bank.
LAYER_ALIGN = {"canopy": 0.0, "understory": 0.4, "grass": 0.65,
               "ground": 0.6, "deadfall": 0.7, "rock": 0.0}


def _bounds(obj: Any) -> tuple[float, float, float, float]:
    mw = obj.matrix_world
    cs = [mw @ Vector(c) for c in obj.bound_box]
    xs = [c.x for c in cs]
    ys = [c.y for c in cs]
    return min(xs), max(xs), min(ys), max(ys)


def _layer_seed(seed: int, layer: str) -> int:
    """Deterministic per-layer seed from the layer NAME. `seed + len(layer)`
    collides same-length layers (canopy/ground are both 6 chars); crc32 of the
    name does not, and is stable across runs/processes (unlike hash())."""
    return (seed + zlib.crc32(layer.encode("utf-8"))) % (2 ** 31)


def scatter_asset_biome(terrain: Any, water_z: float, *, seed: int = 20260525) -> int:
    """Build the CC0 asset library and scatter all layers onto the terrain."""
    from veilbreakers_terrain.handlers._scatter_engine import poisson_disk_sample
    np = None
    cluster_density_map = None
    try:
        import numpy as np
        from veilbreakers_terrain.handlers._scatter_engine import cluster_density_map
    except Exception:
        pass  # numpy / scatter-engine absent -> uniform (no cluster-density) scatter

    # Idempotent: clear any prior foliage so re-running on an already-populated
    # .blend (e.g. the iteration harness) does not stack duplicate instances.
    for _coll in [c for c in bpy.data.collections if c.name.startswith("Foliage_")]:
        for _o in list(_coll.objects):
            bpy.data.objects.remove(_o, do_unlink=True)
        bpy.data.collections.remove(_coll)
    for _o in [o for o in bpy.data.objects if o.name.startswith("tmpl_")]:
        bpy.data.objects.remove(_o, do_unlink=True)  # drop leaked templates

    # ---- build library ----
    library = {}
    for layer, specs in LIBRARY_SPEC.items():
        tmpls = []
        for j, (cat, aid, th, dec) in enumerate(specs):
            tmpls += _import_templates(_gltf(cat, aid), target_height=th,
                                       decimate_ratio=dec, tag=f"{layer}{j}")
        library[layer] = tmpls
        _log(f"  library[{layer}] = {len(tmpls)} templates "
             f"({sum(len(t.data.vertices) for t in tmpls)} verts)")

    bpy.context.view_layer.update()   # ensure the DISPLACE-modified surface is
    deps = bpy.context.evaluated_depsgraph_get()   # what the raycast hits
    terr = terrain.evaluated_get(deps)
    mw = terrain.matrix_world
    minx, maxx, miny, maxy = _bounds(terrain)
    width, depth = maxx - minx, maxy - miny
    down = Vector((0, 0, -1))

    total = 0
    for layer, tmpls in library.items():
        if not tmpls:
            continue
        min_d, slope_max, hmax, wmarg, cap, zsink = LAYER_PARAMS[layer]
        dmap = None
        if (cluster_density_map is not None and np is not None
                and layer in ("canopy", "understory")):
            try:
                dmap = cluster_density_map(width, depth, resolution=256,
                                           cluster_size=60.0, noise_amount=0.4,
                                           seed=seed + zlib.crc32(layer.encode()) % 997)
                dmap = np.clip(0.2 + 0.8 * dmap, 0.35, 1.0).astype("float32")
            except Exception:
                dmap = None
        lseed = _layer_seed(seed, layer)
        pts = poisson_disk_sample(width, depth, min_d, seed=lseed,
                                  density_map=dmap)
        coll = bpy.data.collections.new(f"Foliage_{layer}")
        bpy.context.scene.collection.children.link(coll)
        rng = random.Random(lseed ^ 0x9E3779B1)
        placed = 0
        for (px, py) in pts:
            if placed >= cap:
                break
            wx, wy = minx + px, miny + py
            hit, loc, nrm, *_ = terr.ray_cast(mw.inverted() @ Vector((wx, wy, 450.0)),
                                              mw.inverted().to_3x3() @ down)
            if not hit:
                continue
            z = (mw @ loc).z
            if z < water_z + wmarg or z > hmax:
                continue
            nrm_w = (mw.to_3x3() @ nrm).normalized()
            slope = math.degrees(math.acos(max(-1.0, min(1.0, nrm_w.z))))
            if slope > slope_max:
                continue
            tmpl = rng.choice(tmpls)
            sc = rng.uniform(0.8, 1.25)
            # bury bases into the terrain; rocks/logs partially (mesh them in)
            base_sink = zsink
            if layer in ("rock", "deadfall"):
                base_sink = max(zsink, 0.32 * (tmpl.dimensions.z or 1.0) * sc)
            inst = bpy.data.objects.new(f"{layer}_{placed}", tmpl.data)
            inst.location = (wx, wy, z - base_sink)
            yaw = rng.uniform(0, math.tau)
            align = LAYER_ALIGN.get(layer, 0.0)
            if align > 0.0:
                up: Any = Vector((0, 0, 1))
                aligned = up.lerp(nrm_w, align).normalized()
                tilt = up.rotation_difference(aligned)
                yaw_rot: Any = Euler((0, 0, yaw))
                inst.rotation_euler = (
                    tilt @ yaw_rot.to_quaternion()).to_euler()
            else:
                inst.rotation_euler = (rng.uniform(-0.05, 0.05),
                                       rng.uniform(-0.05, 0.05), yaw)
            inst.scale = (sc, sc, sc)
            coll.objects.link(inst)
            placed += 1
        _log(f"  {layer}: {placed} placed (of {len(pts)} pts, cap {cap})")
        total += placed
    _log(f"TOTAL foliage instances: {total}")
    return total

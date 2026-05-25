"""AAA showcase-render visuals — the single source of truth for terrain
material, sky, and water used by the production builder
(build_terrain_aaa_node_v8.py) and the hero-render iteration script.

These are the settings proven across the hero-render iteration (current
best: iter14, the first render the project lead signed off on):

* Terrain: world-space multi-scale procedural PBR. Replaces the flat 5-colour
  splat. Multi-octave noise albedo (no Voronoi -> no cell "splotches"), gentle
  procedural micro-relief bump, and slope+height biome blending whose
  thresholds are HEAVILY noise-broken at two scales so cliffs never show
  constant-elevation contour "layers". Vegetation is the default cover; rock on
  steep/high ground; snow on peaks; sand at the shore.
* Sky: dim cool gradient. A bright Nishita dome reads as a washed-out milky haze
  under the scene's AgX view transform, so a low-radiance gradient is used
  instead (preserves shadow contrast; dark rock stays dark, not blown white).
* Water: a flat plane at the water level. The visible shoreline becomes the
  terrain<->plane intersection, which follows topography organically (no blocky
  footprint-mesh edge). Reflective, light transmission, subtle ripple normal.
* Foliage: real CC0 (Poly Haven) glTF assets in ecological strata — that
  lives in aaa_asset_foliage.py (scatter_asset_biome); this module owns
  terrain/sky/water. Both share the same Python-owned Bridson placement.

All functions are Blender/bpy and run headless (`blender --background`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import bpy

REPO = Path(__file__).resolve().parents[1]


def _log(msg: str) -> None:
    print(f"[AAA-VIS] {msg}", flush=True)


# --------------------------------------------------------------------------- #
#  Shader-node helpers
# --------------------------------------------------------------------------- #
def _is_sock(x: object) -> bool:
    return hasattr(x, "node")


def _noise(nt: Any, vec: Any, scale: float, detail: float = 6.0,
           rough: float = 0.6, distortion: float = 0.0) -> Any:
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    n.inputs["Roughness"].default_value = rough
    if "Distortion" in n.inputs:
        n.inputs["Distortion"].default_value = distortion
    if vec is not None:
        nt.links.new(vec, n.inputs["Vector"])
    return n


def _mix(nt: Any, fac: Any, a: Any, b: Any, blend: str = "MIX") -> Any:
    """fac: socket|float; a,b: socket|3-tuple. Returns Result(Color) socket."""
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    n.blend_type = blend
    if _is_sock(fac):
        nt.links.new(fac, n.inputs[0])
    else:
        n.inputs[0].default_value = float(fac)
    for idx, val in ((6, a), (7, b)):
        if _is_sock(val):
            nt.links.new(val, n.inputs[idx])
        else:
            n.inputs[idx].default_value = (*val, 1.0)
    return n.outputs[2]


def _maprange(nt: Any, value: Any, fmin: float, fmax: float,
              tmin: float = 0.0, tmax: float = 1.0,
              clamp: bool = True) -> Any:
    n = nt.nodes.new("ShaderNodeMapRange")
    n.clamp = clamp
    if _is_sock(value):
        nt.links.new(value, n.inputs["Value"])
    else:
        n.inputs["Value"].default_value = value
    n.inputs["From Min"].default_value = fmin
    n.inputs["From Max"].default_value = fmax
    n.inputs["To Min"].default_value = tmin
    n.inputs["To Max"].default_value = tmax
    return n.outputs["Result"]


def _math(nt: Any, op: str, a: Any, b: Any = 0.5) -> Any:
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    for idx, val in ((0, a), (1, b)):
        if _is_sock(val):
            nt.links.new(val, n.inputs[idx])
        else:
            n.inputs[idx].default_value = float(val)
    return n.outputs[0]


# --------------------------------------------------------------------------- #
#  Terrain material
# --------------------------------------------------------------------------- #
def make_terrain_material_aaa(name: str = "VB_TerrainAAA") -> Any:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep_n = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Normal"], sep_n.inputs["Vector"])
    slope_z = sep_n.outputs["Z"]        # 1=flat, 0=vertical
    sep_p = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Position"], sep_p.inputs["Vector"])
    height = sep_p.outputs["Z"]
    pos = geo.outputs["Position"]

    # world-space noise bank (NO Voronoi -> avoids cell "splotches")
    n_huge = _noise(nt, pos, 0.010, detail=4, rough=0.5)     # ~100 m weathering
    n_macro = _noise(nt, pos, 0.030, detail=5, rough=0.55)   # ~33 m
    n_meso = _noise(nt, pos, 0.12, detail=6, rough=0.6)      # ~8 m
    n_micro = _noise(nt, pos, 0.6, detail=8, rough=0.65)     # ~1.7 m
    n_fine = _noise(nt, pos, 2.6, detail=8, rough=0.7)       # micro-relief

    def sgn(nz: Any, amt: float) -> Any:
        return _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", nz.outputs["Fac"], 0.5), amt)

    # slope/height drivers HEAVILY noise-broken at two scales, so biome edges
    # never read as constant-elevation contour bands ("curved layers").
    slope_pert = _math(nt, "ADD", _math(nt, "ADD", slope_z, sgn(n_meso, 0.16)),
                       sgn(n_micro, 0.10))
    rock_mask = _maprange(nt, slope_pert, 0.66, 0.42, 0.0, 1.0)
    scree_mask = _maprange(nt, slope_pert, 0.82, 0.64, 0.0, 1.0)

    h_pert = _math(nt, "ADD", _math(nt, "ADD", height, sgn(n_huge, 34.0)),
                   sgn(n_macro, 17.0))
    snow_mask = _maprange(nt, h_pert, 160.0, 198.0, 0.0, 1.0)
    highrock = _maprange(nt, h_pert, 122.0, 170.0, 0.0, 1.0)
    sand_mask = _maprange(nt, h_pert, 12.0, 6.0, 0.0, 1.0)

    # multi-octave albedo -> fine natural mottling, not blotches
    grass = _mix(nt, n_macro.outputs["Fac"], (0.030, 0.060, 0.020), (0.066, 0.106, 0.038))
    grass = _mix(nt, _math(nt, "MULTIPLY", n_meso.outputs["Fac"], 0.5), grass, (0.044, 0.082, 0.028))
    grass = _mix(nt, _math(nt, "MULTIPLY", n_micro.outputs["Fac"], 0.35), grass, (0.052, 0.092, 0.032))
    rock = _mix(nt, n_huge.outputs["Fac"], (0.060, 0.056, 0.049), (0.150, 0.136, 0.116))
    rock = _mix(nt, _math(nt, "MULTIPLY", n_macro.outputs["Fac"], 0.5), rock, (0.092, 0.083, 0.071))
    rock = _mix(nt, _math(nt, "MULTIPLY", n_micro.outputs["Fac"], 0.4), rock, (0.070, 0.063, 0.054))
    scree = _mix(nt, n_macro.outputs["Fac"], (0.095, 0.085, 0.069), (0.150, 0.134, 0.110))
    scree = _mix(nt, _math(nt, "MULTIPLY", n_micro.outputs["Fac"], 0.4), scree, (0.082, 0.073, 0.060))
    snow = _mix(nt, n_micro.outputs["Fac"], (0.70, 0.74, 0.82), (0.87, 0.90, 0.97))
    sand = _mix(nt, n_micro.outputs["Fac"], (0.150, 0.128, 0.095), (0.225, 0.195, 0.150))

    snow_slope = _maprange(nt, slope_z, 0.35, 0.62, 0.30, 1.0)  # less snow on steep
    col = grass
    col = _mix(nt, scree_mask, col, scree)
    col = _mix(nt, highrock, col, rock)
    col = _mix(nt, rock_mask, col, rock)
    col = _mix(nt, _math(nt, "MULTIPLY", snow_mask, snow_slope), col, snow)
    col = _mix(nt, _math(nt, "MULTIPLY", sand_mask, slope_z), col, sand)

    # very subtle weathering tint + gentle cavity (no harsh splotches)
    tint = _mix(nt, _math(nt, "MULTIPLY", n_huge.outputs["Fac"], 0.5),
                (0.94, 0.96, 0.92), (1.04, 1.0, 0.96))
    col = _mix(nt, 0.4, col, tint, blend="MULTIPLY")
    cav = _maprange(nt, geo.outputs["Pointiness"], 0.40, 0.62, 0.88, 1.08)
    col = _mix(nt, 0.5, col, cav, blend="MULTIPLY")
    nt.links.new(col, bsdf.inputs["Base Color"])

    # roughness: ground matte, rock/high a touch glossier; gentle noise variation
    rough = _math(nt, "SUBTRACT", 0.94, _math(nt, "MULTIPLY", rock_mask, 0.24))
    rough = _math(nt, "SUBTRACT", rough, _math(nt, "MULTIPLY", highrock, 0.08))
    rough = _math(nt, "ADD", rough,
                  _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", n_micro.outputs["Fac"], 0.5), 0.10))
    nt.links.new(rough, bsdf.inputs["Roughness"])

    # gentle fine micro-relief only (no Voronoi cracks -> no blotches)
    bump_h = _math(nt, "ADD",
                   _math(nt, "MULTIPLY", n_fine.outputs["Fac"], 0.45),
                   _math(nt, "MULTIPLY", n_micro.outputs["Fac"], 0.40))
    bump_h = _math(nt, "ADD", bump_h, _math(nt, "MULTIPLY", n_meso.outputs["Fac"], 0.15))
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.22
    bump.inputs["Distance"].default_value = 0.40
    nt.links.new(bump_h, bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


# --------------------------------------------------------------------------- #
#  Terrain material v2 — real CC0 scanned PBR via triplanar (kills the
#  "architecture render" look). Uses Poly Haven texture sets under
#  assets/terrain_pbr/. Falls back to the procedural material if absent.
# --------------------------------------------------------------------------- #
def _load_img(path: Path) -> Any:
    try:
        return bpy.data.images.load(str(path), check_existing=True)
    except Exception as e:  # noqa: BLE001
        _log(f"  img load fail {path.name}: {e!r}")
        return None


def _img_node(nt: Any, image: Any, vec: Any, *, non_color: bool = False,
              blend: float = 0.35) -> Any:
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = image
    n.projection = "BOX"            # triplanar in one node
    n.projection_blend = blend
    if non_color and image is not None:
        try:
            image.colorspace_settings.name = "Non-Color"
        except Exception:
            pass  # best-effort: colorspace name varies by Blender build; non-fatal
    if vec is not None:
        nt.links.new(vec, n.inputs["Vector"])
    return n


def make_terrain_material_pbr(name: str = "VB_TerrainPBR", tile_m: float = 9.0,
                              water_level: float = 8.6) -> Any:
    pbr = REPO / "assets" / "terrain_pbr"
    sets = {"veg": "forest_ground_04", "rock": "aerial_rocks_02",
            "scree": "dry_ground_rocks", "sand": "coast_sand_01"}
    img = {}
    for k, sid in sets.items():
        d = pbr / sid
        img[k] = {m: _load_img(d / f"{sid}_{suf}_1k.jpg")
                  for m, suf in (("diff", "diff"), ("nor", "nor_gl"),
                                 ("rough", "rough"))}
    if not all(img[k][m] for k in sets for m in ("diff", "nor", "rough")):
        _log("  PBR texture set incomplete -> procedural terrain material")
        return make_terrain_material_aaa(name)

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep_n = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Normal"], sep_n.inputs["Vector"])
    slope_z = sep_n.outputs["Z"]
    sep_p = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Position"], sep_p.inputs["Vector"])
    height = sep_p.outputs["Z"]
    pos = geo.outputs["Position"]

    tc = nt.nodes.new("ShaderNodeTexCoord")
    mapn = nt.nodes.new("ShaderNodeMapping")
    s = 1.0 / max(tile_m, 0.1)
    mapn.inputs["Scale"].default_value = (s, s, s)
    nt.links.new(tc.outputs["Object"], mapn.inputs["Vector"])
    vec = mapn.outputs["Vector"]

    n_huge = _noise(nt, pos, 0.010, detail=4, rough=0.5)
    n_macro = _noise(nt, pos, 0.030, detail=5, rough=0.55)
    n_meso = _noise(nt, pos, 0.12, detail=6, rough=0.6)
    n_micro = _noise(nt, pos, 0.6, detail=8, rough=0.65)

    def sgn(nz: Any, amt: float) -> Any:
        return _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", nz.outputs["Fac"], 0.5), amt)

    slope_pert = _math(nt, "ADD", _math(nt, "ADD", slope_z, sgn(n_meso, 0.16)),
                       sgn(n_micro, 0.10))
    rock_mask = _maprange(nt, slope_pert, 0.66, 0.42, 0.0, 1.0)
    scree_mask = _maprange(nt, slope_pert, 0.82, 0.64, 0.0, 1.0)
    h_pert = _math(nt, "ADD", _math(nt, "ADD", height, sgn(n_huge, 34.0)),
                   sgn(n_macro, 17.0))
    snow_mask = _maprange(nt, h_pert, 160.0, 198.0, 0.0, 1.0)
    highrock = _maprange(nt, h_pert, 122.0, 170.0, 0.0, 1.0)
    sand_mask = _maprange(nt, h_pert, 12.0, 6.0, 0.0, 1.0)
    snow_slope = _maprange(nt, slope_z, 0.35, 0.62, 0.30, 1.0)

    def lset(key: str, blend: float = 0.35) -> tuple[Any, Any, Any]:
        d = _img_node(nt, img[key]["diff"], vec, blend=blend)
        r = _img_node(nt, img[key]["rough"], vec, non_color=True, blend=blend)
        no = _img_node(nt, img[key]["nor"], vec, non_color=True, blend=blend)
        return d.outputs["Color"], r.outputs["Color"], no.outputs["Color"]

    vd, vr, vn = lset("veg")
    _rd, rr, rn = lset("rock")
    _sd, sr, sn = lset("scree")
    _nd, nr, _nn = lset("sand")

    # PROCEDURAL green albedo: scanned diffuse reads tan/arid and tiles visibly,
    # so the proven biome colours drive COLOUR while the scanned maps drive
    # NORMAL grit (below). Best of both: green + real surface detail.
    grass = _mix(nt, n_macro.outputs["Fac"], (0.030, 0.060, 0.020), (0.066, 0.106, 0.038))
    grass = _mix(nt, _math(nt, "MULTIPLY", n_meso.outputs["Fac"], 0.5), grass, (0.044, 0.082, 0.028))
    rock_c = _mix(nt, n_huge.outputs["Fac"], (0.060, 0.056, 0.049), (0.150, 0.136, 0.116))
    rock_c = _mix(nt, _math(nt, "MULTIPLY", n_micro.outputs["Fac"], 0.4), rock_c, (0.070, 0.063, 0.054))
    scree_c = _mix(nt, n_macro.outputs["Fac"], (0.095, 0.085, 0.069), (0.150, 0.134, 0.110))
    sand_c = _mix(nt, n_micro.outputs["Fac"], (0.150, 0.128, 0.095), (0.225, 0.195, 0.150))
    snow_c = (0.86, 0.89, 0.95)

    col = grass
    col = _mix(nt, scree_mask, col, scree_c)
    col = _mix(nt, highrock, col, rock_c)
    col = _mix(nt, rock_mask, col, rock_c)
    col = _mix(nt, _math(nt, "MULTIPLY", snow_mask, snow_slope), col, snow_c)
    col = _mix(nt, _math(nt, "MULTIPLY", sand_mask, slope_z), col, sand_c)
    # faint scanned-diffuse detail for micro texture break-up (subtle multiply)
    col = _mix(nt, 0.12, col, vd, blend="MULTIPLY")
    tint = _mix(nt, _math(nt, "MULTIPLY", n_huge.outputs["Fac"], 0.5),
                (0.95, 0.97, 0.93), (1.04, 1.0, 0.97))
    col = _mix(nt, 0.3, col, tint, blend="MULTIPLY")
    cav = _maprange(nt, geo.outputs["Pointiness"], 0.42, 0.62, 0.90, 1.06)
    col = _mix(nt, 0.4, col, cav, blend="MULTIPLY")
    # shoreline definition: wet darkening just above the waterline + a thin foam
    # line at the edge (true shallow->deep depth-colour needs a depth pass; this
    # is the high-impact approximation).
    wet = _maprange(nt, height, water_level + 3.0, water_level - 1.0, 0.0, 1.0)
    col = _mix(nt, _math(nt, "MULTIPLY", wet, 0.5), col, (0.20, 0.18, 0.15))
    foam = _math(nt, "MULTIPLY",
                 _maprange(nt, height, water_level - 0.3, water_level + 0.4, 0.0, 1.0),
                 _maprange(nt, height, water_level + 1.6, water_level + 0.5, 0.0, 1.0))
    col = _mix(nt, _math(nt, "MULTIPLY", foam, 0.75), col, (0.60, 0.62, 0.60))
    nt.links.new(col, bsdf.inputs["Base Color"])

    rgh = vr
    rgh = _mix(nt, scree_mask, rgh, sr)
    rgh = _mix(nt, highrock, rgh, rr)
    rgh = _mix(nt, rock_mask, rgh, rr)
    rgh = _mix(nt, _math(nt, "MULTIPLY", sand_mask, slope_z), rgh, nr)
    rgh = _mix(nt, _math(nt, "MULTIPLY", wet, 0.5), rgh, (0.22, 0.22, 0.22))  # wet sheen
    nt.links.new(rgh, bsdf.inputs["Roughness"])

    nrm = vn
    nrm = _mix(nt, scree_mask, nrm, sn)
    nrm = _mix(nt, highrock, nrm, rn)
    nrm = _mix(nt, rock_mask, nrm, rn)
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    # LOW strength: RGB-lerp of tangent normals across biomes + BOX-projection
    # axes is not strictly correct (Golus/selfshadow). Keep it a whisper for
    # texture character; the geometrically-correct procedural Bump below (scalar
    # height -> normal, projection-independent) is the PRIMARY surface detail.
    nmap.inputs["Strength"].default_value = 0.18
    nt.links.new(nrm, nmap.inputs["Color"])
    # macro + meso + micro procedural relief (non-tiling, correct on all areas)
    bump_h = _math(nt, "ADD",
                   _math(nt, "MULTIPLY",
                         _noise(nt, pos, 2.6, detail=8).outputs["Fac"], 0.5),
                   _math(nt, "MULTIPLY", n_micro.outputs["Fac"], 0.4))
    bump_h = _math(nt, "ADD", bump_h,
                   _math(nt, "MULTIPLY", n_meso.outputs["Fac"], 0.25))
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.5
    bump.inputs["Distance"].default_value = 0.45
    nt.links.new(bump_h, bump.inputs["Height"])
    nt.links.new(nmap.outputs["Normal"], bump.inputs["Normal"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def apply_aaa_terrain_material_pbr(obj: Any, water_level: float = 8.6) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(make_terrain_material_pbr(water_level=water_level))
    _log(f"terrain material -> VB_TerrainPBR (triplanar CC0 scans) on {obj.name!r}")


# --------------------------------------------------------------------------- #
#  Sky
# --------------------------------------------------------------------------- #
def setup_aaa_sky(scene: Any = None) -> None:
    """Dim cool gradient sky (low radiance so AgX keeps shadow contrast)."""
    scene = scene or bpy.context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("VB_Sky")
        scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = 0.6
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Incoming"], sep.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.50, 0.56, 0.64, 1.0)   # horizon
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (0.13, 0.22, 0.40, 1.0)   # zenith
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.clamp = True
    nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
    mr.inputs["From Min"].default_value = -0.15
    mr.inputs["From Max"].default_value = 0.6
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    # gentle world AO is preserved if present
    try:
        world.light_settings.use_ambient_occlusion = True
        world.light_settings.ao_factor = 0.4
        world.light_settings.distance = 8.0
    except Exception:
        pass  # best-effort: world AO settings absent on some engines; non-fatal
    _log("sky -> dim cool gradient (strength 0.6)")


# --------------------------------------------------------------------------- #
#  Water
# --------------------------------------------------------------------------- #
def make_water_material_aaa(name: str = "VB_WaterAAA") -> Any:
    """Refractive water with Beer-Lambert depth colour (shallow teal -> deep
    navy) via Volume Absorption, plus a subtle ripple-normal surface.

    Depth colour is physically driven: the camera ray refracts through the
    near-black transmissive surface and accumulates volume absorption over the
    water column down to the terrain, so deeper water (longer in-volume path)
    reads darker and bluer. Needs the water mesh to have downward thickness
    (see `build_aaa_water`) so a water column actually exists to absorb through.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    # Build nodes explicitly (like the terrain materials) rather than fetching
    # the auto-created defaults by English display name -- nodes.get() returns
    # None on a locale/version where the name differs, and the next .inputs
    # access would raise an opaque AttributeError.
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])
    # Surface: near-black, fully transmissive glass. The visible colour comes
    # from the VOLUME (below), so the surface must not double-tint the gradient;
    # it only contributes Fresnel sky reflection + the ripple normal.
    b.inputs["Base Color"].default_value = (0.01, 0.02, 0.025, 1.0)
    b.inputs["Roughness"].default_value = 0.04
    if "Transmission Weight" in b.inputs:
        b.inputs["Transmission Weight"].default_value = 1.0
    if "IOR" in b.inputs:
        b.inputs["IOR"].default_value = 1.333
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    n1 = _noise(nt, geo.outputs["Position"], 0.8, detail=6, rough=0.6)
    n2 = _noise(nt, geo.outputs["Position"], 3.2, detail=8, rough=0.6)
    h = _math(nt, "ADD", _math(nt, "MULTIPLY", n1.outputs["Fac"], 0.6),
              _math(nt, "MULTIPLY", n2.outputs["Fac"], 0.4))
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.10
    bump.inputs["Distance"].default_value = 0.15
    nt.links.new(h, bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    # Beer-Lambert depth colour via a Principled Volume: its teal scatter-albedo
    # "Color" makes the shallows glow teal (single-scatter), while it absorbs the
    # complement (red, then green) with depth so the deep column trends navy ->
    # dark. One physically-based node = shallow-teal -> deep-navy in a single pass.
    # Density sets the falloff over the ~2-18 m water column in this scene.
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Color"].default_value = (0.08, 0.45, 0.52, 1.0)
    vol.inputs["Density"].default_value = 0.10
    if "Anisotropy" in vol.inputs:
        vol.inputs["Anisotropy"].default_value = 0.0
    if "Emission Strength" in vol.inputs:
        vol.inputs["Emission Strength"].default_value = 0.0
    nt.links.new(vol.outputs["Volume"], out.inputs["Volume"])
    return mat


def build_aaa_water(minx: float, maxx: float, miny: float, maxy: float,
                    water_z: float, replace_name: str = "Water_Gorge",
                    depth_m: float = 40.0) -> Any:
    """Water surface at water_z with `depth_m` of downward thickness so the
    Principled-Volume water material renders Beer-Lambert depth colour (shallow ->
    deep). The visible shoreline is still the terrain<->top-face intersection
    (organic, no blocky edge). Removes the generator footprint mesh
    `replace_name` if present."""
    old = bpy.data.objects.get(replace_name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    pad = 60.0
    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=64, y_subdivisions=64, size=1.0,
        location=((minx + maxx) * 0.5, (miny + maxy) * 0.5, water_z))
    plane = bpy.context.active_object
    plane.name = "Water_Flat"
    plane.scale = ((maxx - minx) * 0.5 + pad, (maxy - miny) * 0.5 + pad, 1.0)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    # Downward thickness -> a closed water volume to absorb through. offset=-1
    # extrudes on the -normal (-Z) side so the top face stays exactly at water_z.
    sol = plane.modifiers.new("WaterDepth", "SOLIDIFY")
    sol.thickness = depth_m
    sol.offset = -1.0
    plane.data.materials.clear()
    plane.data.materials.append(make_water_material_aaa())
    _log(f"water -> {depth_m:.0f}m-deep volume, top at z={water_z:.1f}m "
         f"(Beer-Lambert depth colour)")
    return plane

"""build_scene_v3.py — VeilBreakers Node 1 full spec.

Tile spec:
  - 1024m × 1024m
  - South half: flatland 2-8m, forested hills, transitions north into mountain pass (320m peak)
  - River spring(-300,250) → 40m waterfall at (-150,50) → lake(100,-300, r=150m)
  - Traversable cave: entry(0,100,180) → exit(400,100,180), r=6m
  - 80-120m cliff band on south mountain face

Visuals:
  - Triplanar PBR terrain: slope×altitude → 5 stratigraphy bands (wetland→grass→dirt→rock→stone)
  - Stacked-cone pine + layered broad-leaf trees (NO UV spheres, NO boxes)
  - Vertex-group restricted grass, aligned to terrain normals
  - Principled BSDF water (transmission 0.85, ripple bump, IOR 1.333)
  - Nishita sky + warm sun + AgX compositor

Run:
    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \\
        --background --python scripts/build_scene_v3.py

Outputs: output/scene_v3/
"""

from __future__ import annotations

import json
import math
import random
import sys
import traceback
from pathlib import Path
from typing import Any, TypeAlias

import bpy
import bmesh
import numpy as np
from mathutils import Vector

Heightmap: TypeAlias = Any
MeshSpec: TypeAlias = dict[str, Any]
AssetTemplate: TypeAlias = dict[str, Any]
ScatterCounts: TypeAlias = dict[str, int]

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_script_path = Path(__file__).resolve()
if _script_path.name != "build_scene_v3.py" or not (_script_path.parent.parent / "scripts" / "build_scene_v3.py").exists():
    # Blender Text.as_module() can report __file__ under the Blender install
    # directory. The previous fallback hardcoded a Conner-local path; that path
    # does not exist on CI, on a teammate's box, or in any environment outside
    # the original author's machine. T1-37 (Y04 v3) — fail loud rather than
    # silently run against a nonexistent path.
    raise RuntimeError(
        f"Could not resolve build_scene_v3.py canonical path from {_script_path!r}; "
        f"Blender Text.as_module() may have relocated __file__. Re-run with `blender "
        f"--background --python <repo>/scripts/build_scene_v3.py` so __file__ resolves "
        f"to the on-disk script."
    )
REPO_ROOT = _script_path.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUT_DIR = REPO_ROOT / "output" / "scene_v3"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEED = 0xAAA3
RNG = random.Random(SEED)

TILE_M = 1024.0
HM_RES = 513       # heightmap grid (512+1 cells)
MESH_RES = 513     # render mesh matches heightmap grid to avoid scatter height drift

X_MIN = -TILE_M / 2.0
X_MAX = TILE_M / 2.0
Y_MIN = -TILE_M / 2.0
Y_MAX = TILE_M / 2.0

SPRING_XY = (-330.0, 300.0)
WATERFALL_XY = (-238.0, 174.0)
WATERFALL_TOP_Z = 32.0
LAKE_XY = (120.0, -315.0)
LAKE_RADIUS = 210.0
LAKE_WATER_LEVEL = 8.0
CAVE_ENTRY = (282.0, 80.0, 78.0)
CAVE_EXIT = (432.0, 132.0, 110.0)
CAVE_RADIUS = 6.0
MOUNTAIN_PEAK_Z = 320.0
MIN_FOREST_TREE_TARGET = 320
BRIDGE_A = (-104.0, -24.0)
BRIDGE_B = (-52.0, -80.0)
BRIDGE_WIDTH_M = 2.8
NODE_ID = "VB_AAA_NODE_MOUNTAIN_PASS_RIVER_BRIDGE_001"
OFF_NODE_WATER_BODY_TYPE = "off_node_large_water_body"

AZIMUTH_RAD = 2.356  # 135 degrees

FAILURES: list[dict[str, str]] = []

def lake_shore_radius(angle: Any) -> Any:
    return LAKE_RADIUS * (
        0.88
        + 0.050 * np.sin(angle * 3.0 + 0.35)
        + 0.035 * np.sin(angle * 7.0 + 1.2)
        + 0.018 * np.sin(angle * 13.0 + 0.7)
    )


RIVER_POINTS = [
    (-330., 300., 94.), (-306., 264., 58.), (-276., 226., 46.),
    (-254., 195., 38.), (-238., 174., WATERFALL_TOP_Z),
    (-226., 150., 22.), (-207., 120., 15.), (-170., 80., 15.),
    (-116., 30., 14.5), (-58., -38., 13.), (8., -112., 10.0),
    (58., -198., LAKE_WATER_LEVEL + 0.55), (132., -322., LAKE_WATER_LEVEL + 0.36),
    (242., -462., LAKE_WATER_LEVEL + 0.18), (296., Y_MIN - 18.0, LAKE_WATER_LEVEL + 0.05),
]
RIVER_WIDTHS = [5.5, 6.0, 6.8, 7.5, 8.0, 8.5, 9.0, 10.5, 12.0, 13.0, 11.0, 8.5, 13.5, 24.0, 32.0]
MODEL_ASSET_ROOT = REPO_ROOT / "output" / "model_asset_generation" / "downloads"
MODEL_ASSET_DOWNLOAD_ROOTS = [
    MODEL_ASSET_ROOT,
    REPO_ROOT / "output" / "model_asset_generation_node_rescue" / "downloads",
]

MODEL_TREE_ASSETS = [
    ("tree_pine_black_v4.glb", MODEL_ASSET_ROOT / "tree" / "tree_pine_black_v4.glb", 950, 18.0),
    ("tree_oak_ancient_v4.glb", MODEL_ASSET_ROOT / "tree" / "tree_oak_ancient_v4.glb", 1250, 16.0),
    ("tree_birch_pale_v4.glb", MODEL_ASSET_ROOT / "tree" / "tree_birch_pale_v4.glb", 900, 16.0),
    ("tree_dead_claw_v4.glb", MODEL_ASSET_ROOT / "tree" / "tree_dead_claw_v4.glb", 900, 14.0),
]
MODEL_FOLIAGE_ASSETS = [
    ("grass_lush_wet_v4.glb", MODEL_ASSET_ROOT / "grass" / "grass_lush_wet_v4.glb", 300, 1.15),
    ("grass_riverbank_lush_v4.glb", MODEL_ASSET_ROOT / "grass" / "grass_riverbank_lush_v4.glb", 300, 1.25),
    ("grass_tall_overland_v4.glb", MODEL_ASSET_ROOT / "grass" / "grass_tall_overland_v4.glb", 340, 1.45),
    ("bush_fern_shadowleaf_v4.glb", MODEL_ASSET_ROOT / "bush" / "bush_fern_shadowleaf_v4.glb", 550, 1.65),
    ("bush_bramble_thorn_v4.glb", MODEL_ASSET_ROOT / "bush" / "bush_bramble_thorn_v4.glb", 600, 1.55),
    ("reed_water_edge_v4.glb", MODEL_ASSET_ROOT / "water_foliage" / "reed_water_edge_v4.glb", 320, 1.55),
]
MODEL_ROCK_ASSETS = [
    ("boulder_mossy_forest_v4.glb", MODEL_ASSET_ROOT / "rock_boulder" / "boulder_mossy_forest_v4.glb", 900, 1.8),
    ("boulder_shattered_cliff_v4.glb", MODEL_ASSET_ROOT / "rock_boulder" / "boulder_shattered_cliff_v4.glb", 900, 1.6),
    ("pebbles_streambed_v4.glb", MODEL_ASSET_ROOT / "rock_small" / "pebbles_streambed_v4.glb", 350, 0.45),
]


def _existing_model_asset_paths(display_category: str, patterns: tuple[str, ...]) -> list[Path]:
    """Discover generated GLBs across the normal and node-rescue model-provider outputs."""
    found: list[Path] = []
    seen: set[str] = set()
    for root in MODEL_ASSET_DOWNLOAD_ROOTS:
        folder = root / display_category
        if not folder.exists():
            continue
        for pattern in patterns:
            for path in sorted(folder.glob(pattern)):
                key = str(path.resolve()).lower()
                if key not in seen and path.suffix.lower() == ".glb":
                    found.append(path)
                    seen.add(key)
    return found


def _asset_specs_from_paths(paths: list[Path], target_faces: int, target_height: float) -> list[tuple[str, Path, int, float]]:
    return [(path.name, path, target_faces, target_height) for path in paths]


def _model_tree_asset_specs() -> list[tuple[str, Path, int, float]]:
    paths = _existing_model_asset_paths("tree", (
        "tree_pine_shadow_fir*.glb",
        "tree_pine_black*.glb",
    ))
    return _asset_specs_from_paths(paths, 1250, 17.0)


def _model_foliage_asset_specs() -> list[tuple[str, Path, int, float]]:
    specs: list[tuple[str, Path, int, float]] = []
    specs += _asset_specs_from_paths(_existing_model_asset_paths("grass", (
        "grass_forest_floor_muted*.glb",
        "grass_wet_sedge_bank*.glb",
        "grass_shadow_dark*.glb",
        "grass_rotten_forest*.glb",
        "grass_riverbank_lush*.glb",
        "grass_lush_wet*.glb",
        "grass_highland_moor*.glb",
        "grass_tall_overland*.glb",
    )), 300, 1.2)
    specs += _asset_specs_from_paths(_existing_model_asset_paths("bush", (
        "fern_waterfall_spray_muted*.glb",
        "bush_fern_shadowleaf*.glb",
        "bush_bramble_thorn*.glb",
    )), 550, 1.45)
    specs += _asset_specs_from_paths(_existing_model_asset_paths("water_foliage", (
        "reed_water_edge*.glb",
        "lily_pad_swamp*.glb",
    )), 340, 1.2)
    specs += _asset_specs_from_paths(_existing_model_asset_paths("moss", (
        "moss_leaf_litter_mat*.glb",
        "moss_patch_ground*.glb",
    )), 300, 0.35)
    return specs


def _model_rock_asset_specs() -> list[tuple[str, Path, int, float]]:
    specs: list[tuple[str, Path, int, float]] = []
    specs += _asset_specs_from_paths(_existing_model_asset_paths("rock_boulder", (
        "boulder_mossy_forest*.glb",
        "boulder_shattered_cliff*.glb",
    )), 900, 1.8)
    specs += _asset_specs_from_paths(_existing_model_asset_paths("rock_small", (
        "shore_pebble_sedge_cluster*.glb",
        "pebbles_streambed*.glb",
        "gravel_ruin_debris*.glb",
    )), 350, 0.45)
    specs += _asset_specs_from_paths(_existing_model_asset_paths("ground_detail", (
        "root_moss_bank_blend*.glb",
        "root_gnarled_surface*.glb",
        "leaf_mound_dead*.glb",
    )), 450, 0.55)
    return specs


def _model_water_surface_asset_specs() -> list[tuple[str, Path, int, float]]:
    specs: list[tuple[str, Path, int, float]] = []
    specs += _asset_specs_from_paths(_existing_model_asset_paths("water_foliage", (
        "lily_pad_swamp*.glb",
        "algae_mat_surface*.glb",
        "lotus_dark_bloom*.glb",
    )), 180, 0.04)
    return specs


def log(msg: str) -> None:
    print(f"[V3] {msg}", flush=True)


def log_fail(stage: str, exc: BaseException) -> None:
    trace = traceback.format_exc()
    FAILURES.append({"stage": stage, "error": repr(exc), "trace": trace})
    try:
        with (OUT_DIR / "BUILD_FAILURE.log").open("a", encoding="utf-8") as fh:
            fh.write(f"\n=== {stage} ===\n{trace}\n")
    except Exception:
        pass
    log(f"FAILURE in {stage}: {exc!r}")


# ---------------------------------------------------------------------------
# Heightmap — numpy, deterministic, 320m peak
# ---------------------------------------------------------------------------
def compose_heightmap() -> Heightmap:
    xs = np.linspace(X_MIN, X_MAX, HM_RES)
    ys = np.linspace(Y_MIN, Y_MAX, HM_RES)
    X, Y = np.meshgrid(xs, ys, indexing="xy")

    def smoothstep01(v: Any) -> Any:
        v = np.clip(v, 0.0, 1.0)
        return v * v * (3.0 - 2.0 * v)

    def fbm(
        x: Any,
        y: Any,
        octaves: int = 6,
        base_freq: float = 0.008,
        persistence: float = 0.55,
        lacunarity: float = 2.1,
        seed_val: int = 0,
    ) -> Any:
        rn = np.random.default_rng(seed_val)
        total = np.zeros_like(x, dtype=np.float64)
        amp, freq, amp_sum = 1.0, base_freq, 0.0
        for _ in range(octaves):
            ox = float(rn.uniform(0, 1000.0))
            oy = float(rn.uniform(0, 1000.0))
            wave = (
                np.sin((x + ox) * freq) * np.cos((y + oy) * freq * 1.3)
                + 0.7 * np.sin((x + oy) * freq * 1.7 + (y + ox) * freq * 0.9)
            )
            total = total + amp * wave
            amp_sum += amp
            amp *= persistence
            freq *= lacunarity
        return total / max(amp_sum, 1e-6)

    # Macro terrain: flat forest basin in the south, long foothills through the
    # middle, and localized mountain mass in the north. The transition is broad
    # enough to read as traversable land instead of a generated retaining wall.
    north_t = smoothstep01((Y + 95.0) / 625.0)
    west_high = np.exp(-((X + 250.0) ** 2) / (2 * 270.0 ** 2))
    east_high = np.exp(-((X - 235.0) ** 2) / (2 * 340.0 ** 2))
    peak_a = np.exp(-((X + 285.0) ** 2) / (2 * 155.0 ** 2) - ((Y - 365.0) ** 2) / (2 * 150.0 ** 2))
    peak_b = np.exp(-((X - 210.0) ** 2) / (2 * 230.0 ** 2) - ((Y - 305.0) ** 2) / (2 * 185.0 ** 2))
    mountain = 8.0 + 118.0 * (north_t ** 1.75) * (0.62 + 0.38 * west_high)
    ridge = 92.0 * peak_a + 42.0 * peak_b
    east_shoulder = 26.0 * east_high * smoothstep01((Y + 10.0) / 320.0)
    flat = 8.0 + 2.2 * np.sin(X / 155.0 + 0.4) + 1.7 * np.cos(Y / 135.0)
    foothill = 18.0 * smoothstep01((Y + 250.0) / 430.0)
    heightmap = flat + foothill + mountain + ridge + east_shoulder

    noise_hi = fbm(X, Y, octaves=6, base_freq=0.010, seed_val=SEED)
    noise_lo = fbm(X, Y, octaves=4, base_freq=0.0045, seed_val=SEED ^ 0x5A5A)
    elev_norm = np.clip(heightmap / 280.0, 0.0, 1.0)
    heightmap = heightmap + noise_lo * (3.0 + 12.0 * elev_norm) + noise_hi * (1.4 + 5.0 * elev_norm)

    def segment_distance(pts: list[tuple[float, float]]) -> Any:
        best = np.full_like(heightmap, 1e9)
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            dx, dy = x1 - x0, y1 - y0
            seg2 = dx * dx + dy * dy
            if seg2 < 1e-6:
                continue
            tt = np.clip(((X - x0) * dx + (Y - y0) * dy) / seg2, 0.0, 1.0)
            d = np.sqrt((X - (x0 + tt * dx)) ** 2 + (Y - (y0 + tt * dy)) ** 2)
            best = np.minimum(best, d)
        return best

    river_xy = [(p[0], p[1]) for p in RIVER_POINTS]
    upper_xy = river_xy[:5]
    lower_xy = river_xy[5:]
    upper_d = segment_distance(upper_xy)
    lower_d = segment_distance(lower_xy)
    # A broad natural ravine funnels the spring and waterfall. It is a shallow
    # valley with shoulders, not a vertical wall.
    ravine_axis = segment_distance([(-314.0, 282.0), (-238.0, 174.0), (-198.0, 112.0), (-118.0, 28.0)])
    ravine = np.clip(1.0 - ravine_axis / 95.0, 0.0, 1.0)
    heightmap = heightmap - 30.0 * (ravine ** 1.65) * smoothstep01((Y + 25.0) / 420.0)
    shoulder = np.clip(1.0 - np.abs(ravine_axis - 88.0) / 58.0, 0.0, 1.0)
    heightmap = heightmap + 5.5 * shoulder * smoothstep01((Y + 40.0) / 470.0)

    # River bed: continuous segment-based channel with a feathered shelf. The
    # earlier point-clamp pass made hard height discontinuities that rendered as
    # vertical curtain cliffs around the water.
    river_target = np.full_like(heightmap, 1e9)
    river_blend = np.zeros_like(heightmap)
    river_core = np.zeros_like(heightmap)
    for idx in range(len(RIVER_POINTS) - 1):
        x0, y0, z0 = RIVER_POINTS[idx]
        x1, y1, z1 = RIVER_POINTS[idx + 1]
        dx, dy = x1 - x0, y1 - y0
        seg2 = dx * dx + dy * dy
        if seg2 < 1e-6:
            continue
        tt = np.clip(((X - x0) * dx + (Y - y0) * dy) / seg2, 0.0, 1.0)
        px = x0 + tt * dx
        py = y0 + tt * dy
        d = np.sqrt((X - px) ** 2 + (Y - py) ** 2)
        w0 = RIVER_WIDTHS[min(idx, len(RIVER_WIDTHS) - 1)]
        w1 = RIVER_WIDTHS[min(idx + 1, len(RIVER_WIDTHS) - 1)]
        water_w = w0 * (1.0 - tt) + w1 * tt
        inner = water_w * 0.62
        outer = water_w * 2.85
        water_z = z0 * (1.0 - tt) + z1 * tt

        if idx <= 4:
            support_outer = 118.0
            support_t = smoothstep01((support_outer - d) / support_outer)
            bank_t = smoothstep01(np.clip(d / support_outer, 0.0, 1.0))
            supported_grade = water_z - 5.0 + bank_t * 18.0
            heightmap = np.maximum(heightmap, heightmap * (1.0 - support_t) + supported_grade * support_t)

        shelf = smoothstep01(d / np.maximum(outer, 0.001))
        bed = water_z - (2.4 + 0.10 * idx) + shelf * (7.0 + 0.34 * idx)
        blend = smoothstep01((outer - d) / np.maximum(outer - inner, 0.001))
        core = smoothstep01((inner - d) / np.maximum(inner, 0.001))
        river_target = np.minimum(river_target, bed)
        river_blend = np.maximum(river_blend, blend)
        river_core = np.maximum(river_core, core)
    heightmap = np.where(
        river_blend > 0.0,
        heightmap * (1.0 - river_blend) + river_target * river_blend,
        heightmap,
    )
    heightmap = heightmap - 0.9 * river_core

    lower_bank = np.clip(1.0 - lower_d / 62.0, 0.0, 1.0)
    lower_inner = np.clip(1.0 - lower_d / 22.0, 0.0, 1.0)
    heightmap = heightmap - 3.2 * lower_bank + 2.2 * lower_inner

    # Lake basin — irregular shore, deep floor, and wading shelf for entry/exit.
    lake_d = np.sqrt((X - LAKE_XY[0]) ** 2 + (Y - LAKE_XY[1]) ** 2)
    ang_lake = np.arctan2(Y - LAKE_XY[1], X - LAKE_XY[0])
    shore_r = lake_shore_radius(ang_lake)
    lake_rel = lake_d / shore_r
    lake_floor_rel = np.clip(lake_rel, 0.0, 1.0)
    lake_int = lake_rel < 0.98
    lake_floor = LAKE_WATER_LEVEL - (0.9 + 8.5 * ((1.0 - lake_floor_rel) ** 1.65))
    heightmap = np.where(lake_int, np.minimum(heightmap, lake_floor), heightmap)

    bank_t = smoothstep01((lake_rel - 0.98) / 1.08)
    bank_mask = (lake_rel >= 0.98) & (lake_rel < 2.06)
    bank_target = LAKE_WATER_LEVEL + 0.35 + bank_t * 22.0
    heightmap = np.where(bank_mask, np.minimum(heightmap, bank_target), heightmap)

    # Outflow/approach channel should meet the lake below the waterline, not
    # climb over the lake rim.
    lake_inlet = np.exp(-((X - 68.0) ** 2) / (2 * 42.0 ** 2) - ((Y + 206.0) ** 2) / (2 * 52.0 ** 2))
    heightmap = np.where(lake_inlet > 0.05, np.minimum(heightmap, LAKE_WATER_LEVEL - 0.9 + (1.0 - lake_inlet) * 3.0), heightmap)

    for _ in range(2):
        smooth = (
            heightmap
            + np.roll(heightmap, 1, axis=0) + np.roll(heightmap, -1, axis=0)
            + np.roll(heightmap, 1, axis=1) + np.roll(heightmap, -1, axis=1)
        ) / 5.0
        protect_water = lake_int | (upper_d < 5.5) | (lower_d < 7.0)
        heightmap = np.where(protect_water, heightmap, heightmap * 0.62 + smooth * 0.38)

    # Talus-style slope limiting. This is a render-oriented erosion pass that
    # prevents one-grid-cell height steps from becoming vertical mesh curtains.
    max_delta = 2.4
    for _ in range(30):
        diff_x = heightmap[:, :-1] - heightmap[:, 1:]
        transfer_x = np.sign(diff_x) * np.clip(np.abs(diff_x) - max_delta, 0.0, None) * 0.46
        heightmap[:, :-1] -= transfer_x
        heightmap[:, 1:] += transfer_x

        diff_y = heightmap[:-1, :] - heightmap[1:, :]
        transfer_y = np.sign(diff_y) * np.clip(np.abs(diff_y) - max_delta, 0.0, None) * 0.46
        heightmap[:-1, :] -= transfer_y
        heightmap[1:, :] += transfer_y

    log(f"heightmap: shape={heightmap.shape} min={heightmap.min():.1f} max={heightmap.max():.1f} mean={heightmap.mean():.1f}")
    return heightmap


def sample_h(hm: Heightmap, x: float, y: float) -> float:
    u = (x - X_MIN) / (X_MAX - X_MIN) * (HM_RES - 1)
    v = (y - Y_MIN) / (Y_MAX - Y_MIN) * (HM_RES - 1)
    u = max(0.0, min(float(HM_RES - 1.001), u))
    v = max(0.0, min(float(HM_RES - 1.001), v))
    i0, j0 = int(u), int(v)
    fu, fv = u - i0, v - j0
    return float(
        hm[j0, i0] * (1 - fu) * (1 - fv) +
        hm[j0, i0 + 1] * fu * (1 - fv) +
        hm[j0 + 1, i0] * (1 - fu) * fv +
        hm[j0 + 1, i0 + 1] * fu * fv
    )


def _world_to_grid(x: float, y: float) -> tuple[int, int]:
    col = int(round((float(x) - X_MIN) / (X_MAX - X_MIN) * (HM_RES - 1)))
    row = int(round((float(y) - Y_MIN) / (Y_MAX - Y_MIN) * (HM_RES - 1)))
    return max(0, min(HM_RES - 1, row)), max(0, min(HM_RES - 1, col))


def _path_points_with_height(
    hm: Heightmap,
    points: list[tuple[float, float]],
    lift: float = 0.10,
) -> tuple[tuple[float, float, float], ...]:
    return tuple((float(x), float(y), sample_h(hm, x, y) + lift) for x, y in points)


def _materialize_mesh_spec(
    name: str,
    spec: MeshSpec,
    material: bpy.types.Material,
    parent: bpy.types.Object | None = None,
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(spec.get("vertices", []), [], spec.get("faces", []))
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    if parent is not None:
        obj.parent = parent
    for poly in mesh.polygons:
        poly.use_smooth = False
    return obj


def build_bridge_and_approach_paths(terrain_obj: bpy.types.Object, hm: Heightmap) -> dict[str, Any]:
    """Build the requested river bridge and approach paths via canonical callables."""
    from veilbreakers_terrain.handlers import COMMAND_HANDLERS
    from veilbreakers_terrain.handlers._bridge_mesh import generate_terrain_bridge_mesh
    from veilbreakers_terrain.handlers.terrain_path_contracts import (
        PathNetworkContract,
        PathSegmentContract,
        material_stack_for_path,
        validate_path_network_contract,
    )

    log("building bridge + approach paths through real terrain callables...")

    route_in_xy = [(-332.0, -314.0), (-238.0, -206.0), (-162.0, -110.0), BRIDGE_A]
    route_out_xy = [
        BRIDGE_B,
        (-52.0, -112.0),
        (0.0, -130.0),
        (60.0, -180.0),
        (120.0, -220.0),
    ]
    road_results: list[dict[str, Any]] = []
    route_grade_degrees = {
        "route_in": 13.0,
        "route_out": 18.5,
    }
    for label, route_xy in (("route_in", route_in_xy), ("route_out", route_out_xy)):
        max_grade_degrees = route_grade_degrees[label]
        result = COMMAND_HANDLERS["env_generate_road"]({
            "terrain_name": terrain_obj.name,
            "waypoints": [_world_to_grid(x, y) for x, y in route_xy],
            "width": 5,
            "surface": "trail",
            "force_mesh_overlay": True,
            "return_road_channels": True,
            "allow_bridges": False,
            "grade_strength": 0.92,
            "max_grade_degrees": max_grade_degrees,
            "seed": SEED ^ (0xBAD if label == "route_in" else 0xCAB),
        })
        road_results.append(result)
        if result.get("path_network_contract_issues"):
            raise RuntimeError(f"{label} path contract issues: {result['path_network_contract_issues']}")

    a_z = max(sample_h(hm, *BRIDGE_A) + 3.8, 18.0)
    b_z = max(sample_h(hm, *BRIDGE_B) + 3.8, 18.0)
    bridge_spec = generate_terrain_bridge_mesh(
        control_points=[(BRIDGE_A[0], BRIDGE_A[1], a_z), (BRIDGE_B[0], BRIDGE_B[1], b_z)],
        width=BRIDGE_WIDTH_M,
        style="rope",
        seed=SEED ^ 0xB17D6E,
        water_level=14.0,
        waterbed_z=7.4,
    )
    bridge_profile = bridge_spec["metadata"]["bridge_profile"]
    bridge_mat = _simple_principled_material("VB_RopeBridgeWeathered", (0.42, 0.255, 0.125, 1.0), roughness=0.91)
    bridge_obj = _materialize_mesh_spec("VB_River_RopeBridge_Main", bridge_spec, bridge_mat, parent=terrain_obj)

    route_in_points = _path_points_with_height(hm, route_in_xy, lift=0.18)
    route_out_points = _path_points_with_height(hm, route_out_xy, lift=0.18)
    bridge_points: tuple[tuple[float, float, float], ...] = tuple(
        (float(p[0]), float(p[1]), float(p[2]))
        for p in bridge_profile["centerline_points"]
    )
    path_contract = PathNetworkContract(
        node_id=NODE_ID,
        continuation_edges=("north", "south", "east", "west"),
        segments=(
            PathSegmentContract(
                segment_id="route_in_to_bridge",
                segment_type="path",
                points=route_in_points,
                width_m=5.0,
                material_stack=material_stack_for_path("trail"),
                continuation_edge="south",
                max_grade=0.22,
                metadata={"callable": "env_generate_road", "road_mesh_name": road_results[0].get("road_mesh_name")},
            ),
            PathSegmentContract(
                segment_id="bridge_0_river_crossing",
                segment_type="bridge",
                points=bridge_points,
                width_m=BRIDGE_WIDTH_M,
                material_stack=material_stack_for_path("rope", bridge=True),
                crosses_water=True,
                water_depth_m=4.2,
                bridge_required=True,
                bridge_span_m=float(bridge_profile["span_m"]),
                bridge_clearance_m=max(min(a_z, b_z) - 14.0, 0.0),
                max_grade=0.22,
                metadata={"callable": "generate_terrain_bridge_mesh", "object_name": bridge_obj.name},
            ),
            PathSegmentContract(
                segment_id="route_out_to_lowland_shoreline",
                segment_type="path",
                points=route_out_points,
                width_m=5.0,
                material_stack=material_stack_for_path("trail"),
                continuation_edge="internal",
                max_grade=math.tan(math.radians(route_grade_degrees["route_out"])),
                metadata={"callable": "env_generate_road", "road_mesh_name": road_results[1].get("road_mesh_name")},
            ),
        ),
    )
    path_issues = validate_path_network_contract(path_contract)
    if path_issues:
        raise RuntimeError(f"node path contract issues: {path_issues}")

    return {
        "bridge_object": bridge_obj.name,
        "bridge_profile": bridge_profile,
        "road_results": road_results,
        "path_network_contract": path_contract.to_dict(),
        "path_network_contract_issues": path_issues,
        "callables_used": [
            "COMMAND_HANDLERS.env_generate_road",
            "generate_terrain_bridge_mesh",
            "validate_path_network_contract",
        ],
    }


def validate_node_generation_contracts(
    hm: Heightmap,
    bridge_path_result: dict[str, Any],
    *,
    scatter_counts: ScatterCounts,
) -> dict[str, Any]:
    from veilbreakers_terrain.handlers.terrain_scatter_points import (
        ScatterPoint,
        ScatterPointTable,
        validate_scatter_point_table,
    )

    samples = []
    for index, (x, y) in enumerate([(-205.0, -118.0), (-182.0, -86.0), (-150.0, -142.0), (-124.0, -76.0)]):
        z = sample_h(hm, x, y)
        samples.append(ScatterPoint(
            position=(x, y, z),
            normal=(0.0, 0.0, 1.0),
            orient=(0.0, 0.0, 0.0, 1.0),
            scale=(1.0, 1.0, 1.0),
            prototype_id="cc0_forest_prop_seed",
            species_id="mixed_lowland_forest",
            biome_id="mountain_pass_river_forest_edge",
            density=0.72,
            seed=SEED + index,
            slope=0.0,
            height_m=z,
            mask_sources=("forest_edge_near_bridge", "road_exclusion", "water_exclusion"),
            lod_bucket="lod1",
            wind_profile="light_canopy_sway",
            source_layer="forest_side_bridge_approach",
            metadata={"prop_route": "TreeIt/EZ-Tree or existing CC0 manifest fallback"},
        ))
    scatter_table = ScatterPointTable(points=tuple(samples), source="node_contract_sample")
    scatter_issues = validate_scatter_point_table(scatter_table)

    off_node_water_contract = {
        "type": OFF_NODE_WATER_BODY_TYPE,
        "edge": "south",
        "river_exits_tile": True,
        "classification_deferred_to_next_node": True,
        "acceptable_next_node_types": ["ocean", "large_lake", "coastal_shoreline"],
        "exit_point": [RIVER_POINTS[-1][0], Y_MIN, RIVER_POINTS[-1][2]],
        "shoreline_style": "coastal_large_water_transition",
    }
    issues = []
    if bridge_path_result.get("path_network_contract_issues"):
        issues.append({"code": "path_contract_issues"})
    if scatter_issues:
        issues.append({"code": "scatter_contract_issues", "issues": scatter_issues})
    if not scatter_counts.get("trees", 0):
        issues.append({"code": "no_tree_scatter"})
    if not scatter_counts.get("foliage", 0):
        issues.append({"code": "no_foliage_scatter"})

    return {
        "node_id": NODE_ID,
        "off_node_water_contract": off_node_water_contract,
        "scatter_point_contract_sample": scatter_table.to_dict(),
        "scatter_point_contract_issues": scatter_issues,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Terrain mesh
# ---------------------------------------------------------------------------
def build_terrain_mesh(hm: Heightmap) -> bpy.types.Object:
    import numpy as np
    idx = np.linspace(0, HM_RES - 1, MESH_RES).astype(int)
    hm_down = hm[np.ix_(idx, idx)]

    bm = bmesh.new()
    verts = [[None] * MESH_RES for _ in range(MESH_RES)]
    for j in range(MESH_RES):
        for i in range(MESH_RES):
            x = X_MIN + (X_MAX - X_MIN) * (i / (MESH_RES - 1))
            y = Y_MIN + (Y_MAX - Y_MIN) * (j / (MESH_RES - 1))
            verts[j][i] = bm.verts.new((x, y, float(hm_down[j, i])))
    bm.verts.ensure_lookup_table()
    for j in range(MESH_RES - 1):
        for i in range(MESH_RES - 1):
            try:
                bm.faces.new((verts[j][i], verts[j][i + 1], verts[j + 1][i + 1], verts[j + 1][i]))
            except ValueError:
                pass
    bm.normal_update()
    mesh = bpy.data.meshes.new("VB_Terrain_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("VB_Terrain", mesh)
    bpy.context.collection.objects.link(obj)
    for p in mesh.polygons:
        p.use_smooth = True
    try:
        mesh.use_auto_smooth = True
        mesh.auto_smooth_angle = math.radians(30)
    except AttributeError:
        pass
    log(f"terrain mesh: {len(mesh.vertices)} verts, {len(mesh.polygons)} faces")
    return obj


# ---------------------------------------------------------------------------
# Terrain material — triplanar PBR, slope×altitude blending, 5 bands
# ---------------------------------------------------------------------------
def make_terrain_material() -> bpy.types.Material:
    mat = bpy.data.materials.new("VB_TerrainPBR")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (2000, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (1700, 0)
    bsdf.inputs["Roughness"].default_value = 0.88

    geom = nt.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-1400, 0)

    # Slope: 1 - normal.z  (0 = flat, 1 = vertical wall)
    sep_n = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep_n.location = (-1100, 350)
    nt.links.new(geom.outputs["Normal"], sep_n.inputs[0])
    slope = nt.nodes.new("ShaderNodeMath")
    slope.location = (-800, 350)
    slope.operation = "SUBTRACT"
    slope.inputs[0].default_value = 1.0
    nt.links.new(sep_n.outputs["Z"], slope.inputs[1])
    slope_ramp = nt.nodes.new("ShaderNodeValToRGB")
    slope_ramp.location = (-500, 350)
    slope_ramp.color_ramp.elements[0].position = 0.22
    slope_ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
    slope_ramp.color_ramp.elements[1].position = 0.65
    slope_ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
    nt.links.new(slope.outputs[0], slope_ramp.inputs["Fac"])

    # Altitude: world Z remapped 0..320m → 0..1
    sep_p = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep_p.location = (-1100, -100)
    nt.links.new(geom.outputs["Position"], sep_p.inputs[0])
    alt_range = nt.nodes.new("ShaderNodeMapRange")
    alt_range.location = (-800, -100)
    alt_range.inputs["From Min"].default_value = -2.0
    alt_range.inputs["From Max"].default_value = MOUNTAIN_PEAK_Z
    alt_range.inputs["To Min"].default_value = 0.0
    alt_range.inputs["To Max"].default_value = 1.0
    alt_range.clamp = True
    nt.links.new(sep_p.outputs["Z"], alt_range.inputs["Value"])

    # 5-stop stratigraphy ramp: dark wetland, grass, loam, rock-dirt, cold stone.
    alt_ramp = nt.nodes.new("ShaderNodeValToRGB")
    alt_ramp.location = (-500, -100)
    nt.links.new(alt_range.outputs["Result"], alt_ramp.inputs["Fac"])
    ar = alt_ramp.color_ramp
    ar.elements[0].position = 0.01
    ar.elements[0].color = (0.012, 0.038, 0.020, 1)   # dark wetland/moss
    ar.elements[1].position = 1.00
    ar.elements[1].color = (0.18, 0.18, 0.17, 1)      # high cold stone
    e2 = ar.elements.new(0.18)
    e2.color = (0.026, 0.105, 0.038, 1)              # lowland grass
    e3 = ar.elements.new(0.42)
    e3.color = (0.045, 0.085, 0.044, 1)              # mossy loam
    e4 = ar.elements.new(0.68)
    e4.color = (0.080, 0.088, 0.070, 1)              # rooty rock-dirt
    e5 = ar.elements.new(0.86)
    e5.color = (0.145, 0.145, 0.135, 1)              # weathered stone

    # Rock color for steep faces — noise-varied
    noise_v = nt.nodes.new("ShaderNodeTexNoise")
    noise_v.location = (-1100, -500)
    noise_v.inputs["Scale"].default_value = 8.0
    noise_v.inputs["Detail"].default_value = 8.0
    noise_v.inputs["Roughness"].default_value = 0.65
    nt.links.new(geom.outputs["Position"], noise_v.inputs["Vector"])

    rock_mix = nt.nodes.new("ShaderNodeMixRGB")
    rock_mix.location = (100, 450)
    rock_mix.inputs["Color1"].default_value = (0.065, 0.066, 0.060, 1)
    rock_mix.inputs["Color2"].default_value = (0.145, 0.132, 0.105, 1)
    nt.links.new(noise_v.outputs["Fac"], rock_mix.inputs["Fac"])

    # Final: blend altitude color → rock by slope factor
    mix_final = nt.nodes.new("ShaderNodeMixRGB")
    mix_final.location = (900, 100)
    nt.links.new(slope_ramp.outputs["Color"], mix_final.inputs["Fac"])
    nt.links.new(alt_ramp.outputs["Color"], mix_final.inputs["Color1"])
    nt.links.new(rock_mix.outputs["Color"], mix_final.inputs["Color2"])
    nt.links.new(mix_final.outputs["Color"], bsdf.inputs["Base Color"])

    # Roughness: higher on rock walls, lower on flat grass
    rough_ramp = nt.nodes.new("ShaderNodeValToRGB")
    rough_ramp.location = (900, -300)
    nt.links.new(slope_ramp.outputs["Color"], rough_ramp.inputs["Fac"])
    rough_ramp.color_ramp.elements[0].color = (0.65, 0.65, 0.65, 1)
    rough_ramp.color_ramp.elements[1].color = (0.92, 0.92, 0.92, 1)
    nt.links.new(rough_ramp.outputs["Color"], bsdf.inputs["Roughness"])

    # Micro-detail bump
    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (1350, -200)
    bump.inputs["Strength"].default_value = 0.24
    bump.inputs["Distance"].default_value = 0.045
    nt.links.new(noise_v.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


# ---------------------------------------------------------------------------
# Water material (shared factory)
# ---------------------------------------------------------------------------
def make_water_material(name: str, tint: tuple[float, float, float, float] = (0.04, 0.10, 0.18, 1),
                        emission: float = 0.0,
                        roughness: float = 0.10,
                        transparency: float = 0.0) -> bpy.types.Material:
    """Diffuse+Glossy water: base color always visible regardless of viewing angle.
    Avoids the grey-mirror artifact from Principled BSDF + high Transmission at oblique angles."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (1800, 0)

    # Ripple normal — noise+voronoi bump on position
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-900, 0)
    noise1 = nt.nodes.new("ShaderNodeTexNoise")
    noise1.location = (-600, 200)
    noise1.inputs["Scale"].default_value = 6.0
    noise1.inputs["Detail"].default_value = 5.0
    for key in ("Distortion", "Distort"):
        if key in noise1.inputs:
            try:
                noise1.inputs[key].default_value = 0.3
                break
            except Exception:
                pass
    nt.links.new(geom.outputs["Position"], noise1.inputs["Vector"])
    vor = nt.nodes.new("ShaderNodeTexVoronoi")
    vor.location = (-600, -100)
    vor.voronoi_dimensions = "2D"
    vor.inputs["Scale"].default_value = 14.0
    nt.links.new(geom.outputs["Position"], vor.inputs["Vector"])
    mix_r = nt.nodes.new("ShaderNodeMixRGB")
    mix_r.location = (-300, 100)
    mix_r.inputs["Fac"].default_value = 0.5
    nt.links.new(noise1.outputs["Fac"], mix_r.inputs["Color1"])
    nt.links.new(vor.outputs["Distance"], mix_r.inputs["Color2"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (0, 0)
    bump.inputs["Strength"].default_value = 0.16
    bump.inputs["Distance"].default_value = 0.08
    nt.links.new(mix_r.outputs["Color"], bump.inputs["Height"])

    # Diffuse: base color always contributes so water reads blue from all angles.
    # Keep it dark; earlier builds used emission-heavy water that read as white
    # glass sheets from close cameras.
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.location = (300, 200)
    diff.inputs["Color"].default_value = tint
    diff.inputs["Roughness"].default_value = 0.0
    nt.links.new(bump.outputs["Normal"], diff.inputs["Normal"])

    # Glossy: sky reflections / glint
    glossy = nt.nodes.new("ShaderNodeBsdfGlossy")
    glossy.location = (300, -100)
    glossy.inputs["Color"].default_value = (0.18, 0.32, 0.42, 1)
    glossy.inputs["Roughness"].default_value = max(roughness, 0.24)
    nt.links.new(bump.outputs["Normal"], glossy.inputs["Normal"])

    # Fresnel mix: keep the reflective lobe subtle so water never blows out into
    # the white-glass-sheet artifact seen in viewport renders.
    fresnel = nt.nodes.new("ShaderNodeFresnel")
    fresnel.location = (300, -350)
    fresnel.inputs["IOR"].default_value = 1.333
    nt.links.new(bump.outputs["Normal"], fresnel.inputs["Normal"])
    cap = nt.nodes.new("ShaderNodeMath")
    cap.location = (550, -350)
    cap.operation = "MULTIPLY"
    cap.inputs[1].default_value = 0.16
    nt.links.new(fresnel.outputs["Fac"], cap.inputs[0])

    mix_dg = nt.nodes.new("ShaderNodeMixShader")
    mix_dg.location = (800, 0)
    nt.links.new(cap.outputs["Value"], mix_dg.inputs["Fac"])
    nt.links.new(diff.outputs["BSDF"], mix_dg.inputs[1])
    nt.links.new(glossy.outputs["BSDF"], mix_dg.inputs[2])

    # Optional emission for extra blue pop at low light.
    final_shader = mix_dg.outputs["Shader"]
    if emission > 0.0:
        emit = nt.nodes.new("ShaderNodeEmission")
        emit.location = (800, -300)
        r, g, b = tint[0], tint[1], tint[2]
        emit.inputs["Color"].default_value = (min(r * 2.5, 1.0), min(g * 2.5, 1.0), min(b * 1.2, 1.0), 1)
        emit.inputs["Strength"].default_value = emission
        mix_e = nt.nodes.new("ShaderNodeMixShader")
        mix_e.location = (1100, 0)
        mix_e.inputs["Fac"].default_value = min(emission * 1.6, 0.45)
        nt.links.new(mix_dg.outputs["Shader"], mix_e.inputs[1])
        nt.links.new(emit.outputs["Emission"], mix_e.inputs[2])
        final_shader = mix_e.outputs["Shader"]

    transparency = max(0.0, min(0.85, transparency))
    if transparency > 0.0:
        trans = nt.nodes.new("ShaderNodeBsdfTransparent")
        trans.location = (1080, -420)
        trans.inputs["Color"].default_value = (0.030, 0.110, 0.125, 1)
        mix_t = nt.nodes.new("ShaderNodeMixShader")
        mix_t.location = (1350, 0)
        mix_t.inputs["Fac"].default_value = transparency
        nt.links.new(final_shader, mix_t.inputs[1])
        nt.links.new(trans.outputs["BSDF"], mix_t.inputs[2])
        nt.links.new(mix_t.outputs["Shader"], out.inputs["Surface"])
        mat.blend_method = "BLEND"
        mat.use_screen_refraction = True
        mat.show_transparent_back = True
    else:
        nt.links.new(final_shader, out.inputs["Surface"])

    return mat


# ---------------------------------------------------------------------------
# Water surfaces: lake disk + river ribbon + waterfall sheet
# ---------------------------------------------------------------------------
def _simple_principled_material(name: str, color: tuple[float, float, float, float],
                                roughness: float = 0.85,
                                alpha: float = 1.0) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Alpha"].default_value = alpha
    if alpha < 1.0:
        mat.blend_method = "BLEND"
        mat.use_screen_refraction = True
        mat.show_transparent_back = True
    return mat


def _make_flat_ribbon_mesh(name: str, points: list[tuple[float, float, float]],
                           widths: list[float], *, subdivisions: int = 5,
                           edge_wobble: float = 0.0) -> bpy.types.Mesh:
    bm = bmesh.new()
    prev_row = None
    for idx, p in enumerate(points):
        nxt = points[idx + 1] if idx < len(points) - 1 else points[idx - 1]
        prv = points[idx - 1] if idx > 0 else points[idx + 1]
        dx = nxt[0] - prv[0]
        dy = nxt[1] - prv[1]
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        w = widths[min(idx, len(widths) - 1)]
        row = []
        for side_i in range(subdivisions + 1):
            side_t = side_i / subdivisions
            side = (side_t - 0.5) * w
            bank_noise = math.sin(idx * 1.73 + side_t * 5.19) * edge_wobble
            edge_factor = abs(side_t - 0.5) * 2.0
            x = p[0] + nx * (side + bank_noise * edge_factor)
            y = p[1] + ny * (side + bank_noise * edge_factor)
            # Subtle crown avoids the perfectly planar "glass strip" read.
            z = p[2] + 0.08 * math.cos((side_t - 0.5) * math.pi)
            row.append(bm.verts.new((x, y, z)))
        if prev_row is not None:
            for side_i in range(subdivisions):
                try:
                    bm.faces.new((
                        prev_row[side_i],
                        row[side_i],
                        row[side_i + 1],
                        prev_row[side_i + 1],
                    ))
                except ValueError:
                    pass
        prev_row = row
    bm.normal_update()
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for poly in mesh.polygons:
        poly.use_smooth = True
    return mesh


def _build_foam_ring(name: str, radius_inner: float, radius_outer: float,
                     z: float, material: bpy.types.Material,
                     center_xy: tuple[float, float] | None = None) -> bpy.types.Object:
    bm = bmesh.new()
    segs = 96
    inner = []
    outer = []
    cx, cy = center_xy if center_xy is not None else LAKE_XY
    for k in range(segs):
        ang = 2 * math.pi * k / segs
        c, s = math.cos(ang), math.sin(ang)
        wob = 1.0 + 0.025 * math.sin(ang * 5.0 + 1.3) + 0.018 * math.sin(ang * 11.0)
        inner.append(bm.verts.new((cx + radius_inner * wob * c,
                                   cy + radius_inner * wob * s, z)))
        outer.append(bm.verts.new((cx + radius_outer * wob * c,
                                   cy + radius_outer * wob * s, z + 0.03)))
    for k in range(segs):
        nk = (k + 1) % segs
        try:
            bm.faces.new((inner[k], outer[k], outer[nk], inner[nk]))
        except ValueError:
            pass
    bm.normal_update()
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def _build_river_edge_foam(material: bpy.types.Material, hm: Heightmap) -> None:
    for side_name, side_sign in (("L", 1.0), ("R", -1.0)):
        pts = []
        widths = []
        for idx, p in enumerate(RIVER_POINTS):
            nxt = RIVER_POINTS[idx + 1] if idx < len(RIVER_POINTS) - 1 else RIVER_POINTS[idx - 1]
            prv = RIVER_POINTS[idx - 1] if idx > 0 else RIVER_POINTS[idx + 1]
            dx = nxt[0] - prv[0]
            dy = nxt[1] - prv[1]
            ln = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / ln, dx / ln
            w = RIVER_WIDTHS[min(idx, len(RIVER_WIDTHS) - 1)]
            x = p[0] + nx * side_sign * w * 0.45
            y = p[1] + ny * side_sign * w * 0.45
            pts.append((x, y, sample_h(hm, x, y) + 0.28))
            widths.append(0.12 if idx < 6 else 0.18)
        mesh = _make_flat_ribbon_mesh(f"VB_RiverFoam_{side_name}_Mesh", pts, widths,
                                      subdivisions=1, edge_wobble=0.08)
        obj = bpy.data.objects.new(f"VB_RiverFoam_{side_name}", mesh)
        bpy.context.collection.objects.link(obj)
        obj.data.materials.append(material)
        obj.visible_shadow = False


def _sample_river_path(hm: Heightmap, src: list[tuple[float, float, float]], *,
                       water_lift: float, width_scale: float,
                       width_offset: int = 0,
                       steps_per_segment: int = 9,
                       use_profile_z: bool = False) -> tuple[list[tuple[float, float, float]], list[float]]:
    pts: list[tuple[float, float, float]] = []
    widths: list[float] = []
    for i in range(len(src) - 1):
        p0 = src[i]
        p1 = src[i + 1]
        for step in range(steps_per_segment):
            if i > 0 and step == 0:
                continue
            t = step / steps_per_segment
            x = p0[0] * (1.0 - t) + p1[0] * t
            y = p0[1] * (1.0 - t) + p1[1] * t
            ground_z = sample_h(hm, x, y)
            profile_z = p0[2] * (1.0 - t) + p1[2] * t
            z = min(max(profile_z + water_lift, ground_z + water_lift), ground_z + 1.15)
            pts.append((x, y, z if use_profile_z else ground_z + water_lift))
            wi = min(width_offset + i, len(RIVER_WIDTHS) - 1)
            wj = min(width_offset + i + 1, len(RIVER_WIDTHS) - 1)
            widths.append((RIVER_WIDTHS[wi] * (1.0 - t) + RIVER_WIDTHS[wj] * t) * width_scale)
    p_last = src[-1]
    last_ground = sample_h(hm, p_last[0], p_last[1])
    last_z = min(max(p_last[2] + water_lift, last_ground + water_lift), last_ground + 1.15)
    pts.append((p_last[0], p_last[1], last_z if use_profile_z else last_ground + water_lift))
    widths.append(RIVER_WIDTHS[min(width_offset + len(src) - 1, len(RIVER_WIDTHS) - 1)] * width_scale)
    return pts, widths


def _build_water_depth_disk(hm: Heightmap, water_mats: list[bpy.types.Material],
                            bed_mat: bpy.types.Material) -> bpy.types.Object:
    ring_n = 144
    bm = bmesh.new()

    def lake_rel(x: float, y: float) -> float:
        ang = math.atan2(y - LAKE_XY[1], x - LAKE_XY[0])
        return math.hypot(x - LAKE_XY[0], y - LAKE_XY[1]) / max(float(lake_shore_radius(ang)), 0.001)

    # Use clipped quads instead of a triangle fan. The old center fan created a
    # radial shading/normal artifact that read as a fake island in hero renders.
    step = 7.0
    pad = LAKE_RADIUS * 1.08
    x0 = LAKE_XY[0] - pad
    y0 = LAKE_XY[1] - pad
    nx = int((pad * 2.0) / step) + 1
    ny = int((pad * 2.0) / step) + 1
    grid: dict[tuple[int, int], bmesh.types.BMVert] = {}

    def grid_vert(ix: int, iy: int) -> bmesh.types.BMVert:
        key = (ix, iy)
        if key not in grid:
            x = x0 + ix * step
            y = y0 + iy * step
            grid[key] = bm.verts.new((x, y, LAKE_WATER_LEVEL + 0.045))
        return grid[key]

    for iy in range(ny):
        for ix in range(nx):
            cx = x0 + (ix + 0.5) * step
            cy = y0 + (iy + 0.5) * step
            if lake_rel(cx, cy) > 0.985:
                continue
            try:
                face = bm.faces.new((
                    grid_vert(ix, iy),
                    grid_vert(ix + 1, iy),
                    grid_vert(ix + 1, iy + 1),
                    grid_vert(ix, iy + 1),
                ))
                face.material_index = 0
            except ValueError:
                pass
    bm.normal_update()
    lake_mesh = bpy.data.meshes.new("VB_Lake_Mesh")
    bm.to_mesh(lake_mesh)
    bm.free()
    for p in lake_mesh.polygons:
        p.use_smooth = False
    lake_obj = bpy.data.objects.new("VB_Lake", lake_mesh)
    bpy.context.collection.objects.link(lake_obj)
    lake_obj.visible_shadow = False
    for mat in water_mats:
        lake_obj.data.materials.append(mat)

    bed_bm = bmesh.new()
    bed_fracs = [0.10, 0.36, 0.62, 0.84, 1.02]
    bed_rings: list[list[bmesh.types.BMVert]] = []
    for ri, frac in enumerate(bed_fracs):
        row = []
        for k in range(ring_n):
            ang = 2 * math.pi * k / ring_n
            r = float(lake_shore_radius(ang)) * frac
            x = LAKE_XY[0] + r * math.cos(ang)
            y = LAKE_XY[1] + r * math.sin(ang)
            row.append(bed_bm.verts.new((x, y, sample_h(hm, x, y) + 0.075)))
        bed_rings.append(row)
    for ri in range(len(bed_rings) - 1):
        inner = bed_rings[ri]
        outer = bed_rings[ri + 1]
        for k in range(ring_n):
            nk = (k + 1) % ring_n
            try:
                bed_bm.faces.new((inner[k], outer[k], outer[nk], inner[nk]))
            except ValueError:
                pass
    bed_bm.normal_update()
    bed_mesh = bpy.data.meshes.new("VB_LakeBedDepth_Mesh")
    bed_bm.to_mesh(bed_mesh)
    bed_bm.free()
    bed_obj = bpy.data.objects.new("VB_LakeBedDepth", bed_mesh)
    bpy.context.collection.objects.link(bed_obj)
    bed_obj.data.materials.append(bed_mat)
    bed_obj.visible_shadow = False
    bed_obj.hide_render = True
    bed_obj.hide_viewport = True
    return lake_obj


def _build_waterfall_volume(hm: Heightmap, material: bpy.types.Material,
                            foam_mat: bpy.types.Material) -> None:
    """Layered falling water volume, replacing the former terrain-hugging strip."""
    top = RIVER_POINTS[4]
    bot = RIVER_POINTS[6]
    dx = bot[0] - top[0]
    dy = bot[1] - top[1]
    ln = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / ln, dx / ln
    top_z = sample_h(hm, top[0], top[1]) + 1.4
    bot_z = sample_h(hm, bot[0], bot[1]) + 1.2
    sheet_count = 5
    for sheet in range(sheet_count):
        bm = bmesh.new()
        cols = 6
        rows = 12
        width = 7.6 - sheet * 0.65
        forward = sheet * 0.85
        grid = []
        for r in range(rows + 1):
            t = r / rows
            cx = top[0] * (1.0 - t) + bot[0] * t + dx / ln * forward
            cy = top[1] * (1.0 - t) + bot[1] * t + dy / ln * forward
            cz = top_z * (1.0 - t) + bot_z * t - 4.0 * math.sin(t * math.pi)
            row = []
            for c in range(cols + 1):
                side_t = (c / cols - 0.5)
                edge_noise = math.sin(r * 0.91 + c * 1.7 + sheet) * 0.55
                x = cx + nx * (side_t * width + edge_noise)
                y = cy + ny * (side_t * width + edge_noise * 0.35)
                row.append(bm.verts.new((x, y, cz + 0.25 * math.sin(c + r))))
            grid.append(row)
        for r in range(rows):
            for c in range(cols):
                try:
                    bm.faces.new((grid[r][c], grid[r][c + 1], grid[r + 1][c + 1], grid[r + 1][c]))
                except ValueError:
                    pass
        bm.normal_update()
        mesh = bpy.data.meshes.new(f"VB_WaterfallSheet_{sheet}_Mesh")
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(f"VB_WaterfallSheet_{sheet}", mesh)
        bpy.context.collection.objects.link(obj)
        obj.data.materials.append(material)
        obj.visible_shadow = False

    streak_mat = _simple_principled_material("VB_WaterfallWhiteStreaks", (0.72, 0.88, 0.90, 0.34),
                                             roughness=0.58, alpha=0.34)
    for i in range(34):
        offset = RNG.uniform(-4.2, 4.2)
        side = RNG.uniform(-0.8, 0.8)
        pts = []
        for r in range(6):
            t = r / 5.0
            x = top[0] * (1.0 - t) + bot[0] * t + nx * (offset + side * t) + RNG.uniform(-0.35, 0.35)
            y = top[1] * (1.0 - t) + bot[1] * t + ny * (offset * 0.25) + RNG.uniform(-0.35, 0.35)
            z = top_z * (1.0 - t) + bot_z * t - RNG.uniform(0.0, 1.0) * t
            pts.append((x, y, z))
        curve = bpy.data.curves.new(f"VB_WaterfallStreak_{i:02d}_Curve", "CURVE")
        curve.dimensions = "3D"
        curve.resolution_u = 2
        curve.bevel_depth = RNG.uniform(0.035, 0.085)
        curve.bevel_resolution = 2
        spl = curve.splines.new("POLY")
        spl.points.add(len(pts) - 1)
        for pnt, co in zip(spl.points, pts):
            pnt.co = (co[0], co[1], co[2], 1.0)
        obj = bpy.data.objects.new(f"VB_WaterfallStreak_{i:02d}", curve)
        bpy.context.collection.objects.link(obj)
        obj.data.materials.append(streak_mat)
        obj.visible_shadow = False

    _build_foam_ring("VB_PlungePoolAeration", 4.2, 15.5, bot_z + 0.18, foam_mat,
                     center_xy=(bot[0], bot[1]))


def _build_bank_ribbon(name: str, hm: Heightmap, src: list[tuple[float, float, float]], *,
                       water_lift: float, width_scale: float, width_offset: int,
                       material: bpy.types.Material) -> bpy.types.Object:
    pts, widths = _sample_river_path(hm, src, water_lift=water_lift,
                                     width_scale=width_scale,
                                     width_offset=width_offset,
                                     steps_per_segment=10)
    mesh = _make_flat_ribbon_mesh(f"{name}_Mesh", pts, widths, subdivisions=7, edge_wobble=1.15)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    obj.visible_shadow = False
    return obj


def _build_plunge_pool(hm: Heightmap, water_mat: bpy.types.Material,
                       foam_mat: bpy.types.Material,
                       bed_mat: bpy.types.Material) -> None:
    cx, cy = RIVER_POINTS[6][0], RIVER_POINTS[6][1]
    angle = math.atan2(RIVER_POINTS[7][1] - RIVER_POINTS[5][1],
                       RIVER_POINTS[7][0] - RIVER_POINTS[5][0])
    ca, sa = math.cos(angle), math.sin(angle)
    segs = 72

    def ellipse_obj(name: str, z_lift: float, sx: float, sy: float,
                    mat: bpy.types.Material, wobble: float = 0.0) -> bpy.types.Object:
        bm = bmesh.new()
        center = bm.verts.new((cx, cy, sample_h(hm, cx, cy) + z_lift))
        ring = []
        for k in range(segs):
            a = math.tau * k / segs
            rr = 1.0 + wobble * math.sin(a * 5.0 + 0.8) + wobble * 0.55 * math.sin(a * 11.0)
            lx, ly = math.cos(a) * sx * rr, math.sin(a) * sy * rr
            x = cx + lx * ca - ly * sa
            y = cy + lx * sa + ly * ca
            ring.append(bm.verts.new((x, y, sample_h(hm, x, y) + z_lift)))
        for k in range(segs):
            try:
                bm.faces.new((center, ring[k], ring[(k + 1) % segs]))
            except ValueError:
                pass
        bm.normal_update()
        mesh = bpy.data.meshes.new(f"{name}_Mesh")
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        obj.data.materials.append(mat)
        obj.visible_shadow = False
        return obj

    ellipse_obj("VB_PlungePoolBed", 0.06, 19.0, 12.0, bed_mat, wobble=0.045)
    ellipse_obj("VB_PlungePoolWater", 0.36, 14.0, 8.5, water_mat, wobble=0.035)


def _make_grass_clump_mesh(name: str, blade_count: int, height: float,
                           width: float, lean: float) -> bpy.types.Mesh:
    bm = bmesh.new()
    for i in range(blade_count):
        ang = (math.tau * i / blade_count) + RNG.uniform(-0.22, 0.22)
        radial = RNG.uniform(0.02, 0.12)
        base_x = math.cos(ang) * radial
        base_y = math.sin(ang) * radial
        blade_ang = ang + RNG.uniform(-0.45, 0.45)
        side_x = -math.sin(blade_ang) * width * RNG.uniform(0.65, 1.25)
        side_y = math.cos(blade_ang) * width * RNG.uniform(0.65, 1.25)
        tip_x = base_x + math.cos(blade_ang) * lean * RNG.uniform(0.35, 1.0)
        tip_y = base_y + math.sin(blade_ang) * lean * RNG.uniform(0.35, 1.0)
        tip_z = height * RNG.uniform(0.65, 1.35)
        mid_z = tip_z * 0.55
        v0 = bm.verts.new((base_x - side_x, base_y - side_y, 0.0))
        v1 = bm.verts.new((base_x + side_x, base_y + side_y, 0.0))
        v2 = bm.verts.new((tip_x + side_x * 0.18, tip_y + side_y * 0.18, tip_z))
        v3 = bm.verts.new((tip_x - side_x * 0.18, tip_y - side_y * 0.18, tip_z))
        face = bm.faces.new((v0, v1, v2, v3))
        face.smooth = True
        # A tiny crossing blade through the center prevents card-flat silhouettes.
        if i % 2 == 0:
            cx = (base_x + tip_x) * 0.5
            cy = (base_y + tip_y) * 0.5
            sx = -side_y * 0.55
            sy = side_x * 0.55
            a = bm.verts.new((cx - sx, cy - sy, mid_z * 0.15))
            b = bm.verts.new((cx + sx, cy + sy, mid_z * 0.15))
            c = bm.verts.new((tip_x + sx * 0.10, tip_y + sy * 0.10, tip_z * 0.92))
            d = bm.verts.new((tip_x - sx * 0.10, tip_y - sy * 0.10, tip_z * 0.92))
            bm.faces.new((a, b, c, d))
    bm.normal_update()
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _surface_slope(hm: Heightmap, x: float, y: float, step: float = 3.0) -> float:
    dx = sample_h(hm, min(X_MAX, x + step), y) - sample_h(hm, max(X_MIN, x - step), y)
    dy = sample_h(hm, x, min(Y_MAX, y + step)) - sample_h(hm, x, max(Y_MIN, y - step))
    return math.hypot(dx, dy) / (step * 2.0)


def _lake_relative_radius(x: float, y: float) -> float:
    ang = math.atan2(y - LAKE_XY[1], x - LAKE_XY[0])
    shore = float(lake_shore_radius(ang))
    return math.hypot(x - LAKE_XY[0], y - LAKE_XY[1]) / max(shore, 0.001)


def _river_clearance(x: float, y: float) -> tuple[float, float]:
    """Return distance to nearest river centreline and local water width."""
    best_d = 1e9
    best_w = RIVER_WIDTHS[0]
    for idx in range(len(RIVER_POINTS) - 1):
        x0, y0, _ = RIVER_POINTS[idx]
        x1, y1, _ = RIVER_POINTS[idx + 1]
        dx, dy = x1 - x0, y1 - y0
        seg2 = dx * dx + dy * dy
        if seg2 < 1e-6:
            continue
        t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / seg2))
        px = x0 + t * dx
        py = y0 + t * dy
        d = math.hypot(x - px, y - py)
        if d < best_d:
            wi = RIVER_WIDTHS[min(idx, len(RIVER_WIDTHS) - 1)]
            wj = RIVER_WIDTHS[min(idx + 1, len(RIVER_WIDTHS) - 1)]
            best_d = d
            best_w = wi * (1.0 - t) + wj * t
    return best_d, best_w


def _hydro_zone(x: float, y: float) -> str:
    """Classify scatter placement so trees stay out of water and banks stay lush."""
    lake_rel = _lake_relative_radius(x, y)
    river_d, river_w = _river_clearance(x, y)
    if lake_rel < 1.01 or river_d < river_w * 0.46:
        return "water"
    if lake_rel < 1.30 or river_d < river_w * 2.20:
        return "wet_bank"
    return "dry"


def _mesh_bounds_local(mesh: bpy.types.Mesh) -> tuple[Vector, Vector]:
    mins = Vector((1e9, 1e9, 1e9))
    maxs = Vector((-1e9, -1e9, -1e9))
    for v in mesh.vertices:
        mins.x = min(mins.x, v.co.x)
        mins.y = min(mins.y, v.co.y)
        mins.z = min(mins.z, v.co.z)
        maxs.x = max(maxs.x, v.co.x)
        maxs.y = max(maxs.y, v.co.y)
        maxs.z = max(maxs.z, v.co.z)
    return mins, maxs


def _normalize_mesh_to_base(mesh: bpy.types.Mesh, target_height: float) -> tuple[float, float]:
    mins, maxs = _mesh_bounds_local(mesh)
    height = max(0.001, maxs.z - mins.z)
    scale = target_height / height
    cx = (mins.x + maxs.x) * 0.5
    cy = (mins.y + maxs.y) * 0.5
    for v in mesh.vertices:
        v.co.x = (v.co.x - cx) * scale
        v.co.y = (v.co.y - cy) * scale
        v.co.z = (v.co.z - mins.z) * scale
    mesh.update()
    mins2, maxs2 = _mesh_bounds_local(mesh)
    radius = max(maxs2.x - mins2.x, maxs2.y - mins2.y) * 0.5
    return target_height, max(0.2, radius)


def _model_asset_palette_material(label: str, slot_name: str = "") -> bpy.types.Material:
    key = f"{label} {slot_name}".lower()
    if any(token in key for token in ("bark", "trunk", "wood", "root", "log", "stump")):
        color = (0.125, 0.095, 0.065, 1.0)
        name = "VB_ModelAssetPalette_BarkRoot"
    elif any(token in key for token in ("lily", "algae", "lotus", "pad", "surface")):
        color = (0.055, 0.115, 0.070, 1.0)
        name = "VB_ModelAssetPalette_WaterSurfacePlant"
    elif any(token in key for token in ("oak", "pine", "birch", "tree", "leaf", "leaves", "needle", "canopy")):
        color = (0.075, 0.125, 0.064, 1.0)
        name = "VB_ModelAssetPalette_MutedCanopy"
    elif any(token in key for token in ("grass", "sedge", "reed")):
        color = (0.070, 0.135, 0.065, 1.0)
        name = "VB_ModelAssetPalette_WetGrass"
    elif any(token in key for token in ("fern", "bush", "bramble")):
        color = (0.060, 0.120, 0.070, 1.0)
        name = "VB_ModelAssetPalette_FernUnderstory"
    elif any(token in key for token in ("moss", "litter", "leaf")):
        color = (0.085, 0.120, 0.055, 1.0)
        name = "VB_ModelAssetPalette_MossLitter"
    elif any(token in key for token in ("rock", "boulder", "pebble", "gravel", "stone", "shore")):
        color = (0.145, 0.140, 0.120, 1.0)
        name = "VB_ModelAssetPalette_WetStone"
    else:
        color = (0.100, 0.115, 0.080, 1.0)
        name = "VB_ModelAssetPalette_GroundMuted"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = _simple_principled_material(name, color, roughness=0.88)
    return mat


def _material_uses_image_textures(mat: bpy.types.Material | None) -> bool:
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return False
    return any(node.bl_idname == "ShaderNodeTexImage" for node in mat.node_tree.nodes)


def _retint_model_asset_mesh_to_biome(mesh: bpy.types.Mesh, label: str) -> None:
    """Force generated GLBs into the terrain palette so scatter does not clash."""
    if not mesh.materials:
        mesh.materials.append(_model_asset_palette_material(label))
        return
    for idx, mat in enumerate(list(mesh.materials)):
        slot_name = mat.name if mat is not None else ""
        key = f"{label} {slot_name}".lower()
        palette_mat = _model_asset_palette_material(label, slot_name)
        if any(token in key for token in ("tree", "pine", "oak", "birch", "canopy", "needle")):
            mesh.materials[idx] = palette_mat
            continue
        if _material_uses_image_textures(mat):
            # Preserve asset alpha cards and authored texture masks. Replacing
            # these with flat opaque materials turns foliage into visible boxes.
            try:
                mat.blend_method = "HASHED"
                mat.show_transparent_back = False
                mat.diffuse_color = palette_mat.diffuse_color
                if mat.use_nodes and mat.node_tree is not None:
                    for node in mat.node_tree.nodes:
                        if node.bl_idname == "ShaderNodeBsdfPrincipled":
                            if "Roughness" in node.inputs:
                                node.inputs["Roughness"].default_value = 0.88
                            if "Alpha" in node.inputs:
                                node.inputs["Alpha"].default_value = 1.0
            except Exception:
                pass
            continue
        mesh.materials[idx] = palette_mat


def _import_model_asset_template(label: str, path: Path, target_faces: int,
                           target_height: float) -> AssetTemplate | None:
    if not path.exists():
        return None
    before = set(bpy.data.objects)
    try:
        bpy.ops.import_scene.gltf(filepath=str(path))
    except Exception as exc:
        log(f"model_asset template import failed {path.name}: {exc}")
        return None
    imported = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    if not imported:
        return None

    bpy.ops.object.select_all(action="DESELECT")
    for obj in imported:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = imported[0]
    if len(imported) > 1:
        try:
            bpy.ops.object.join()
        except Exception:
            pass
    obj = bpy.context.view_layer.objects.active
    if obj is None or obj.type != "MESH":
        return None
    obj.name = f"TPL_{label}"
    obj.data.name = f"TPL_{label}_Mesh"
    try:
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    except Exception:
        pass

    poly_count = len(obj.data.polygons)
    if target_faces > 0 and poly_count > target_faces:
        mod = obj.modifiers.new("VB_DecimateForScatter", "DECIMATE")
        mod.ratio = max(0.05, min(1.0, target_faces / max(1, poly_count)))
        try:
            bpy.ops.object.modifier_apply(modifier=mod.name)
        except Exception:
            obj.modifiers.remove(mod)

    height, radius = _normalize_mesh_to_base(obj.data, target_height)
    _retint_model_asset_mesh_to_biome(obj.data, label)
    obj.location = (0, 0, 0)
    obj.hide_viewport = True
    obj.hide_render = True
    return {"label": label, "mesh": obj.data, "height": height, "radius": radius}


def _load_model_asset_templates(asset_specs: list[tuple[str, Path, int, float]]) -> list[AssetTemplate]:
    templates: list[AssetTemplate] = []
    for label, path, target_faces, target_height in asset_specs:
        tpl = _import_model_asset_template(label.replace(".glb", ""), path, target_faces, target_height)
        if tpl is not None:
            templates.append(tpl)
    return templates


def build_water_surfaces(hm: Heightmap) -> None:
    lake_bed_mat = _simple_principled_material("VB_LakeBedWetSilt", (0.045, 0.070, 0.055, 1),
                                               roughness=0.94)
    stream_bed_mat = _simple_principled_material("VB_StreamBedPebbleSilt", (0.085, 0.105, 0.080, 1),
                                                 roughness=0.96)
    damp_bank_mat = _simple_principled_material("VB_DampBankSedgeMud", (0.070, 0.125, 0.075, 1),
                                                roughness=0.92)
    foam_mat = _simple_principled_material("VB_WaterFoam", (0.52, 0.66, 0.62, 0.10),
                                           roughness=0.76, alpha=0.13)

    lake_mats = [
        make_water_material("WaterLakeUnified", tint=(0.010, 0.055, 0.060, 1),
                            roughness=0.54, emission=0.0, transparency=0.0),
    ]
    _build_water_depth_disk(hm, lake_mats, lake_bed_mat)

    def sampled_path(src: list[tuple[float, float, float]], name: str,
                     water_lift: float, width_scale: float,
                     width_offset: int = 0) -> bpy.types.Object:
        pts, widths = _sample_river_path(hm, src, water_lift=water_lift,
                                         width_scale=width_scale,
                                         width_offset=width_offset,
                                         steps_per_segment=10,
                                         use_profile_z=True)
        mesh = _make_flat_ribbon_mesh(f"{name}_Mesh", pts, widths, subdivisions=7, edge_wobble=0.75)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        obj.visible_shadow = False
        return obj

    river_mat = make_water_material("WaterRiver", tint=(0.004, 0.048, 0.060, 1),
                                    roughness=0.48, emission=0.0, transparency=0.14)
    _build_bank_ribbon("VB_StreamBed_Upper", hm, RIVER_POINTS[:5], water_lift=0.075,
                       width_scale=0.92, width_offset=0, material=stream_bed_mat)
    _build_bank_ribbon("VB_StreamBed_Lower", hm, RIVER_POINTS[6:], water_lift=0.075,
                       width_scale=1.08, width_offset=6, material=stream_bed_mat)
    _build_bank_ribbon("VB_DampBank_Upper", hm, RIVER_POINTS[:5], water_lift=0.105,
                       width_scale=1.48, width_offset=0, material=damp_bank_mat)
    _build_bank_ribbon("VB_DampBank_Lower", hm, RIVER_POINTS[6:], water_lift=0.105,
                       width_scale=1.62, width_offset=6, material=damp_bank_mat)
    upper_river = sampled_path(RIVER_POINTS[:5], "VB_River_Upper", water_lift=0.25, width_scale=0.70, width_offset=0)
    lower_river = sampled_path(RIVER_POINTS[6:], "VB_River_Lower", water_lift=0.30, width_scale=0.78, width_offset=6)
    upper_river.data.materials.append(river_mat)
    lower_river.data.materials.append(river_mat)

    wf_mat = _simple_principled_material("WaterFall", (0.035, 0.125, 0.135, 0.38),
                                         roughness=0.78, alpha=0.38)
    _build_bank_ribbon("VB_WaterfallChuteBed", hm, RIVER_POINTS[4:7], water_lift=0.08,
                       width_scale=0.94, width_offset=4, material=stream_bed_mat)
    _build_waterfall_volume(hm, wf_mat, foam_mat)
    _build_plunge_pool(hm, river_mat, foam_mat, stream_bed_mat)
    _build_river_edge_foam(foam_mat, hm)

    spray_mat = _simple_principled_material("VB_WaterfallMist", (0.68, 0.82, 0.86, 0.28),
                                            roughness=0.88, alpha=0.28)
    spray_col = bpy.data.collections.new("VB_Waterfall_Spray")
    bpy.context.scene.collection.children.link(spray_col)
    for i in range(46):
        t = RNG.random()
        x = WATERFALL_XY[0] + RNG.uniform(-8.0, 8.0)
        y = WATERFALL_XY[1] - 9.0 - t * 34.0 + RNG.uniform(-5.5, 5.5)
        z = sample_h(hm, x, y) + RNG.uniform(0.6, 4.4) + (1.0 - t) * 2.5
        bpy.ops.mesh.primitive_uv_sphere_add(segments=8, ring_count=4, radius=RNG.uniform(0.35, 1.25),
                                             location=(x, y, z))
        mist = bpy.context.view_layer.objects.active
        mist.name = f"VB_WaterfallMist_{i:02d}"
        mist.scale.x *= RNG.uniform(1.6, 3.5)
        mist.scale.y *= RNG.uniform(0.7, 1.4)
        mist.scale.z *= RNG.uniform(0.25, 0.55)
        mist.data.materials.append(spray_mat)
        bpy.context.collection.objects.unlink(mist)
        spray_col.objects.link(mist)
        mist.visible_shadow = False

    log("water: depth-banded lake + streambeds + damp banks + attached cascade/plunge pool built")


# ---------------------------------------------------------------------------
# Beach ring — sandy shore for player water entry/exit
# ---------------------------------------------------------------------------
def build_beach_ring(hm: Heightmap) -> bpy.types.Object:
    """Sandy/gravel beach ring around lake. Gradual wading shelf — 20-50m wide."""
    bm = bmesh.new()
    segs = 80
    inner_verts: list[bmesh.types.BMVert] = []
    outer_verts: list[bmesh.types.BMVert] = []
    for k in range(segs):
        ang = 2 * math.pi * k / segs
        c, s = math.cos(ang), math.sin(ang)
        shore_r = float(lake_shore_radius(ang))
        inner_r = shore_r * 0.98
        outer_r = shore_r * 1.34
        outer_x = LAKE_XY[0] + outer_r * c
        outer_y = LAKE_XY[1] + outer_r * s
        out_z = sample_h(hm, outer_x, outer_y) + 0.08
        inner_verts.append(bm.verts.new((
            LAKE_XY[0] + inner_r * c, LAKE_XY[1] + inner_r * s, LAKE_WATER_LEVEL - 0.05
        )))
        outer_verts.append(bm.verts.new((outer_x, outer_y, out_z)))

    for k in range(segs):
        nk = (k + 1) % segs
        try:
            bm.faces.new((inner_verts[k], outer_verts[k], outer_verts[nk], inner_verts[nk]))
        except ValueError:
            pass
    bm.normal_update()
    beach_mesh = bpy.data.meshes.new("VB_Beach_Mesh")
    bm.to_mesh(beach_mesh)
    bm.free()
    for p in beach_mesh.polygons:
        p.use_smooth = True

    beach_obj = bpy.data.objects.new("VB_Beach", beach_mesh)
    bpy.context.collection.objects.link(beach_obj)

    beach_mat = bpy.data.materials.new("VB_BeachSand")
    beach_mat.use_nodes = True
    nt = beach_mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.075, 0.095, 0.070, 1)   # muted wet gravel/mud
    bsdf.inputs["Roughness"].default_value = 0.91
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 22.0
    noise.inputs["Detail"].default_value = 7.0
    nt.links.new(geom.outputs["Position"], noise.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.60
    bump.inputs["Distance"].default_value = 0.035
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    beach_obj.data.materials.append(beach_mat)

    log("beach ring: built (sandy shore for player entry/exit)")
    return beach_obj


# ---------------------------------------------------------------------------
# Cave boolean carve
# ---------------------------------------------------------------------------
def carve_cave(terrain_obj: bpy.types.Object) -> None:
    cps = [
        (CAVE_ENTRY[0], CAVE_ENTRY[1] - 8.0, CAVE_ENTRY[2]),
        (CAVE_ENTRY[0], CAVE_ENTRY[1] + 20.0, CAVE_ENTRY[2] - 5.0),
        (150.0, 120.0, 175.0),
        (280.0, 110.0, 170.0),
        (CAVE_EXIT[0] - 20.0, CAVE_EXIT[1] - 10.0, CAVE_EXIT[2] - 10.0),
        (CAVE_EXIT[0] + 8.0, CAVE_EXIT[1], CAVE_EXIT[2]),
    ]
    segs_per_leg = 8
    ring_n = 16
    dense: list[tuple[float, float, float]] = []
    for i in range(len(cps) - 1):
        for step in range(segs_per_leg):
            t = step / segs_per_leg
            dense.append((
                cps[i][0] * (1 - t) + cps[i + 1][0] * t,
                cps[i][1] * (1 - t) + cps[i + 1][1] * t,
                cps[i][2] * (1 - t) + cps[i + 1][2] * t,
            ))
    dense.append(cps[-1])

    bm = bmesh.new()
    first_ring: list[bmesh.types.BMVert] | None = None
    prev_ring: list[bmesh.types.BMVert] | None = None
    for idx, p in enumerate(dense):
        if idx < len(dense) - 1:
            tv = tuple(dense[idx + 1][k] - p[k] for k in range(3))
        else:
            tv = tuple(p[k] - dense[idx - 1][k] for k in range(3))
        tl = math.sqrt(sum(x * x for x in tv)) or 1.0
        tv = tuple(x / tl for x in tv)
        _Z = (0.0, 0.0, 1.0)
        _X = (1.0, 0.0, 0.0)
        up = _Z if abs(tv[0] * _Z[0] + tv[1] * _Z[1] + tv[2] * _Z[2]) < 0.95 else _X
        r = (tv[1] * up[2] - tv[2] * up[1], tv[2] * up[0] - tv[0] * up[2], tv[0] * up[1] - tv[1] * up[0])
        rl = math.sqrt(sum(x * x for x in r)) or 1.0
        r = tuple(x / rl for x in r)
        u2 = (r[1] * tv[2] - r[2] * tv[1], r[2] * tv[0] - r[0] * tv[2], r[0] * tv[1] - r[1] * tv[0])
        ring: list[bmesh.types.BMVert] = []
        for k in range(ring_n):
            ang = 2 * math.pi * k / ring_n
            off = (
                r[0] * math.cos(ang) * CAVE_RADIUS + u2[0] * math.sin(ang) * CAVE_RADIUS,
                r[1] * math.cos(ang) * CAVE_RADIUS + u2[1] * math.sin(ang) * CAVE_RADIUS,
                r[2] * math.cos(ang) * CAVE_RADIUS + u2[2] * math.sin(ang) * CAVE_RADIUS,
            )
            ring.append(bm.verts.new((p[0] + off[0], p[1] + off[1], p[2] + off[2])))
        if first_ring is None:
            first_ring = ring
        if prev_ring is not None:
            for k in range(ring_n):
                try:
                    bm.faces.new((prev_ring[k], prev_ring[(k + 1) % ring_n],
                                  ring[(k + 1) % ring_n], ring[k]))
                except ValueError:
                    pass
        prev_ring = ring

    if first_ring is not None and prev_ring is not None:
        try:
            bm.faces.new(tuple(reversed(first_ring)))
            bm.faces.new(tuple(prev_ring))
        except ValueError:
            pass

    bm.normal_update()
    cave_mesh = bpy.data.meshes.new("VB_CaveVol_Mesh")
    bm.to_mesh(cave_mesh)
    bm.free()
    cave_obj = bpy.data.objects.new("VB_CaveVol", cave_mesh)
    bpy.context.collection.objects.link(cave_obj)
    cave_obj.hide_viewport = True
    cave_obj.hide_render = True

    mod = terrain_obj.modifiers.new("CaveBool", type="BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cave_obj
    try:
        mod.solver = "EXACT"
    except Exception:
        pass
    # Keep as live modifier — renders correctly in Cycles without apply overhead
    log("cave boolean modifier added (live, renders in Cycles)")


# ---------------------------------------------------------------------------
# Tree templates — stacked-cone silhouettes, NOT spheres/boxes
# ---------------------------------------------------------------------------
def _build_cone_stack(bm: bmesh.types.BMesh, layers: list[tuple[float, float, float]],
                      segs: int = 12) -> None:
    """Add stacked cone layers to an existing bmesh. layers = [(z_center, r_base, r_tip), ...]"""
    for z_c, r1, r2 in layers:
        depth = abs(z_c - (layers[layers.index((z_c, r1, r2)) - 1][0]
                           if layers.index((z_c, r1, r2)) > 0 else 0)) * 0.5 + 0.8
        depth = max(depth, 0.6)
        cone_bm = bmesh.new()
        bmesh.ops.create_cone(
            cone_bm, cap_ends=True, cap_tris=False, segments=segs,
            radius1=r1, radius2=r2, depth=depth,
        )
        for v in cone_bm.verts:
            v.co.z += z_c
        tmp = bpy.data.meshes.new("_cone_tmp")
        cone_bm.to_mesh(tmp)
        cone_bm.free()
        bm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)


def make_pine_mesh() -> bpy.types.Mesh:
    """Dark conifer: tapered trunk + 4 stacked cone layers narrowing toward apex."""
    bm = bmesh.new()
    trunk_h = 10.0
    # Trunk cylinder
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=8,
                          radius1=0.50, radius2=0.18, depth=trunk_h)
    for v in bm.verts:
        v.co.z += trunk_h / 2.0
    # 4 cone layers: z_center, base_radius, tip_radius
    _build_cone_stack(bm, [
        (3.5, 5.2, 3.0),
        (5.5, 4.0, 2.2),
        (7.5, 2.8, 1.2),
        (9.5, 1.5, 0.2),
    ])
    bm.normal_update()
    mesh = bpy.data.meshes.new("PineMesh")
    bm.to_mesh(mesh)
    bm.free()
    for p in mesh.polygons:
        p.use_smooth = True

    bark = bpy.data.materials.new("PineBark")
    bark.use_nodes = True
    bark.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.11, 0.07, 0.04, 1)
    bark.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.93
    foliage = bpy.data.materials.new("PineFoliage")
    foliage.use_nodes = True
    foliage.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.04, 0.11, 0.04, 1)
    foliage.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.82
    try:
        foliage.node_tree.nodes["Principled BSDF"].inputs["Subsurface Weight"].default_value = 0.10
    except KeyError:
        pass
    mesh.materials.append(bark)    # slot 0
    mesh.materials.append(foliage)  # slot 1
    # Below 45% of trunk_h = bark, above = foliage
    threshold = trunk_h * 0.45
    for poly in mesh.polygons:
        zs = [mesh.vertices[vi].co.z for vi in poly.vertices]
        poly.material_index = 1 if sum(zs) / len(zs) > threshold else 0
    return mesh


def make_broad_tree_mesh() -> bpy.types.Mesh:
    """Broad-leaf tree: trunk + 4 wide flat cone layers (larger radius, lower profile)."""
    bm = bmesh.new()
    trunk_h = 8.0
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=10,
                          radius1=0.42, radius2=0.18, depth=trunk_h)
    for v in bm.verts:
        v.co.z += trunk_h / 2.0
    # Wide overlapping cone layers for deciduous canopy silhouette
    _build_cone_stack(bm, [
        (5.0, 6.0, 4.5),
        (6.5, 5.0, 3.5),
        (8.0, 3.8, 2.2),
        (9.5, 2.0, 0.4),
    ], segs=14)
    bm.normal_update()
    mesh = bpy.data.meshes.new("BroadTreeMesh")
    bm.to_mesh(mesh)
    bm.free()
    for p in mesh.polygons:
        p.use_smooth = True

    bark = bpy.data.materials.get("PineBark")
    if bark is None:
        bark = bpy.data.materials.new("PineBark")
        bark.use_nodes = True
        bark.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.11, 0.07, 0.04, 1)
        bark.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.93
    broad_foliage = bpy.data.materials.new("BroadFoliage")
    broad_foliage.use_nodes = True
    broad_foliage.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.07, 0.16, 0.05, 1)
    broad_foliage.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.76
    try:
        broad_foliage.node_tree.nodes["Principled BSDF"].inputs["Subsurface Weight"].default_value = 0.12
    except KeyError:
        pass
    mesh.materials.append(bark)
    mesh.materials.append(broad_foliage)
    threshold = trunk_h * 0.55
    for poly in mesh.polygons:
        zs = [mesh.vertices[vi].co.z for vi in poly.vertices]
        poly.material_index = 1 if sum(zs) / len(zs) > threshold else 0
    return mesh


def scatter_trees(
    terrain_obj: bpy.types.Object,
    hm: Heightmap,
    pine_mesh: bpy.types.Mesh,
    broad_mesh: bpy.types.Mesh,
    count: int = 120,
) -> int:
    """Scatter linked tree instances on terrain. Pines on slopes/altitude, broad-leaf on flatland."""
    trees_col = bpy.data.collections.new("VB_Trees")
    bpy.context.scene.collection.children.link(trees_col)
    placed = 0
    attempts = 0
    placed_xys: list[tuple[float, float]] = []

    while placed < count and attempts < count * 18:
        attempts += 1
        wx = RNG.uniform(X_MIN + 25, X_MAX - 25)
        wy = RNG.uniform(Y_MIN + 25, Y_MAX - 25)
        wz = sample_h(hm, wx, wy)

        # Filter: no water, no high peaks, no lake, no waterfall corridor
        if wz < LAKE_WATER_LEVEL + 1.5:
            continue
        if wz > 230.0:
            continue
        if _hydro_zone(wx, wy) != "dry":
            continue
        if math.hypot(wx - LAKE_XY[0], wy - LAKE_XY[1]) < LAKE_RADIUS + 15.0:
            continue
        if abs(wx - WATERFALL_XY[0]) < 22 and 20.0 < wy < 260.0:
            continue

        # Raycast to get surface normal — skip very steep cliff faces
        origin = Vector((wx, wy, 500.0))
        result, _loc, norm, _ = terrain_obj.ray_cast(
            terrain_obj.matrix_world.inverted() @ origin,
            Vector((0, 0, -1)),
        )
        if not result:
            continue
        if norm.z < 0.52:  # cliff (> ~58° slope)
            continue

        # Blue-noise-ish: skip if a neighbor tree is within min_dist
        min_dist = 5.0
        too_close = any(
            (px - wx) ** 2 + (py - wy) ** 2 < min_dist * min_dist
            for px, py in placed_xys[-300:]
        )
        if too_close:
            continue

        # Species: pine on slopes / high altitude, broad-leaf on flatland
        use_pine = (wz > 55.0) or (norm.z < 0.78) or (RNG.random() < 0.35)
        obj = bpy.data.objects.new(f"VB_Tree_{placed:03d}",
                                   pine_mesh if use_pine else broad_mesh)
        obj.location = (wx, wy, wz)
        scale = RNG.uniform(1.5, 2.8)
        obj.scale = (scale, scale, scale)
        obj.rotation_euler = (RNG.uniform(-0.04, 0.04),
                               RNG.uniform(-0.04, 0.04),
                               RNG.uniform(0, math.tau))
        trees_col.objects.link(obj)
        placed_xys.append((wx, wy))
        placed += 1

    log(f"trees: {placed} placed in {attempts} attempts")
    return placed


def scatter_model_asset_trees(terrain_obj: bpy.types.Object, hm: Heightmap, count: int = 170) -> int:
    templates = _load_model_asset_templates(_model_tree_asset_specs() or MODEL_TREE_ASSETS)
    if not templates:
        log("model_asset trees: no usable GLB templates found")
        return 0
    trees_col = bpy.data.collections.new("VB_ModelAssetTrees")
    bpy.context.scene.collection.children.link(trees_col)

    placed = 0
    attempts = 0
    placed_xys: list[tuple[float, float, float]] = []
    forest_centers = [
        (-330.0, -310.0, 150.0), (-185.0, -235.0, 150.0), (10.0, -255.0, 135.0),
        (-270.0, -70.0, 125.0), (-155.0, 35.0, 110.0), (-245.0, 170.0, 105.0),
        (85.0, -145.0, 110.0), (260.0, -180.0, 120.0),
    ]
    while placed < count and attempts < count * 36:
        attempts += 1
        pick = RNG.random()
        if pick < 0.68:
            cx, cy, spread = RNG.choice(forest_centers)
            wx = RNG.gauss(cx, spread * 0.45)
            wy = RNG.gauss(cy, spread * 0.45)
        elif pick < 0.86:
            p = RIVER_POINTS[RNG.randint(5, len(RIVER_POINTS) - 3)]
            wx = p[0] + RNG.uniform(-95.0, 95.0)
            wy = p[1] + RNG.uniform(-85.0, 85.0)
        else:
            wx = RNG.uniform(X_MIN + 35.0, X_MAX - 35.0)
            wy = RNG.uniform(Y_MIN + 35.0, Y_MAX - 35.0)
        if not (X_MIN + 24.0 < wx < X_MAX - 24.0 and Y_MIN + 24.0 < wy < Y_MAX - 24.0):
            continue
        wz = sample_h(hm, wx, wy)
        if wz < LAKE_WATER_LEVEL + 2.5 or wz > 225.0:
            continue
        if _hydro_zone(wx, wy) != "dry":
            continue
        river_d, river_w = _river_clearance(wx, wy)
        if river_d < river_w * 3.35:
            continue
        slope = _surface_slope(hm, wx, wy)
        if slope > 0.62:
            continue

        high = wz > 86.0 or slope > 0.28
        flat_forest = wy < -70.0 and wz < 55.0
        dead = wz > 150.0 and RNG.random() < 0.12
        if dead:
            choices = [t for t in templates if "dead" in t["label"]]
        elif flat_forest:
            choices = [t for t in templates if "oak" in t["label"] or "birch" in t["label"]]
        elif high:
            choices = [t for t in templates if "pine" in t["label"] or "birch" in t["label"]]
        else:
            choices = [t for t in templates if "oak" in t["label"] or "birch" in t["label"]]
        tpl = RNG.choice(choices or templates)
        sc = RNG.uniform(0.72, 1.16)
        radius = tpl["radius"] * sc
        min_dist = max(4.2, radius * RNG.uniform(1.25, 1.85))
        if any((px - wx) ** 2 + (py - wy) ** 2 < (min_dist + pr * 0.45) ** 2
               for px, py, pr in placed_xys[-620:]):
            continue

        obj = bpy.data.objects.new(f"VB_ModelAssetTree_{placed:03d}", tpl["mesh"])
        obj.location = (wx, wy, wz - 0.22)
        obj.scale = (sc, sc, sc * RNG.uniform(0.92, 1.10))
        obj.rotation_euler = (RNG.uniform(-0.035, 0.035), RNG.uniform(-0.035, 0.035),
                              RNG.uniform(0, math.tau))
        trees_col.objects.link(obj)
        placed_xys.append((wx, wy, radius))
        placed += 1

    log(f"model_asset trees: {placed} placed from {len(templates)} normalized templates")
    return placed


# ---------------------------------------------------------------------------
# Rocks — deformed icospheres, 4 template meshes, linked instances
# ---------------------------------------------------------------------------
def scatter_rocks(terrain_obj: bpy.types.Object, hm: Heightmap, count: int = 80) -> int:
    rocks_col = bpy.data.collections.new("VB_Rocks")
    bpy.context.scene.collection.children.link(rocks_col)
    rock_mat = bpy.data.materials.new("VB_RockMat")
    rock_mat.use_nodes = True
    rock_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.18, 0.15, 0.11, 1)
    rock_mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.88

    templates = []
    for ri in range(4):
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
        rng_r = random.Random(SEED + ri * 997)
        for v in bm.verts:
            v.co.x *= rng_r.uniform(0.5, 1.5)
            v.co.y *= rng_r.uniform(0.5, 1.5)
            v.co.z *= rng_r.uniform(0.35, 0.75)
        bm.normal_update()
        rmesh = bpy.data.meshes.new(f"RockTpl{ri}")
        bm.to_mesh(rmesh)
        bm.free()
        for p in rmesh.polygons:
            p.use_smooth = True
        rmesh.materials.append(rock_mat)
        templates.append(rmesh)

    placed = 0
    attempts = 0
    while placed < count and attempts < count * 14:
        attempts += 1
        wx = RNG.uniform(X_MIN + 8, X_MAX - 8)
        wy = RNG.uniform(Y_MIN + 8, Y_MAX - 8)
        wz = sample_h(hm, wx, wy)
        if wz < LAKE_WATER_LEVEL + 0.4:
            continue
        if math.hypot(wx - LAKE_XY[0], wy - LAKE_XY[1]) < LAKE_RADIUS + 50.0:
            continue
        size = RNG.uniform(0.4, 2.5)
        obj = bpy.data.objects.new(f"VB_Rock_{placed:03d}", templates[RNG.randint(0, 3)])
        obj.location = (wx, wy, wz - size * 0.28)
        obj.scale = (size, size, size)
        obj.rotation_euler = (RNG.uniform(0, math.tau),
                               RNG.uniform(0, math.tau),
                               RNG.uniform(0, math.tau))
        rocks_col.objects.link(obj)
        placed += 1

    log(f"rocks: {placed} placed")
    return placed


def scatter_model_asset_detail_assets(
    hm: Heightmap,
    foliage_count: int = 850,
    rock_count: int = 130,
) -> ScatterCounts:
    foliage_templates = _load_model_asset_templates(_model_foliage_asset_specs() or MODEL_FOLIAGE_ASSETS)
    rock_templates = _load_model_asset_templates(_model_rock_asset_specs() or MODEL_ROCK_ASSETS)
    col = bpy.data.collections.new("VB_ModelAssetGroundDetail")
    bpy.context.scene.collection.children.link(col)

    counts = {"foliage": 0, "rocks": 0}
    occupied: list[tuple[float, float, float]] = []

    def place_instance(name_prefix: str, tpl: AssetTemplate, wx: float, wy: float, wz: float,
                       scale: float, radius_mult: float = 1.6) -> bool:
        radius = tpl["radius"] * scale * radius_mult
        if any((px - wx) ** 2 + (py - wy) ** 2 < (radius + pr * 0.45) ** 2 for px, py, pr in occupied[-1400:]):
            return False
        obj = bpy.data.objects.new(f"{name_prefix}_{len(occupied):04d}", tpl["mesh"])
        obj.location = (wx, wy, wz - 0.05)
        obj.scale = (scale * RNG.uniform(0.85, 1.2), scale * RNG.uniform(0.85, 1.2), scale)
        obj.rotation_euler = (RNG.uniform(-0.04, 0.04), RNG.uniform(-0.04, 0.04),
                              RNG.uniform(0.0, math.tau))
        col.objects.link(obj)
        occupied.append((wx, wy, radius))
        return True

    attempts = 0
    while counts["foliage"] < foliage_count and attempts < foliage_count * 28 and foliage_templates:
        attempts += 1
        near_water_pick = RNG.random() < 0.46
        if near_water_pick:
            if RNG.random() < 0.65:
                p = RIVER_POINTS[RNG.randint(5, len(RIVER_POINTS) - 1)]
                off = RNG.choice((-1.0, 1.0)) * RNG.uniform(18.0, 56.0)
                wx = p[0] + RNG.uniform(-20.0, 20.0) + off
                wy = p[1] + RNG.uniform(-20.0, 20.0)
            else:
                ang = RNG.uniform(0.0, math.tau)
                shore = float(lake_shore_radius(ang))
                r = RNG.uniform(shore * 1.04, shore * 1.32)
                wx = LAKE_XY[0] + math.cos(ang) * r
                wy = LAKE_XY[1] + math.sin(ang) * r
        elif RNG.random() < 0.46:
            cx, cy = RNG.choice(((-310.0, -330.0), (-210.0, -205.0), (-75.0, -230.0),
                                 (80.0, -160.0), (-190.0, -45.0)))
            wx = RNG.gauss(cx, 90.0)
            wy = RNG.gauss(cy, 72.0)
        else:
            wx = RNG.uniform(X_MIN + 20.0, X_MAX - 20.0)
            wy = RNG.uniform(Y_MIN + 20.0, Y_MAX - 20.0)
        if not (X_MIN < wx < X_MAX and Y_MIN < wy < Y_MAX):
            continue
        wz = sample_h(hm, wx, wy)
        if wz < LAKE_WATER_LEVEL + 0.4 or wz > 120.0:
            continue
        zone = _hydro_zone(wx, wy)
        if zone == "water":
            continue
        if _surface_slope(hm, wx, wy) > 0.48:
            continue
        wet = zone == "wet_bank"
        if wet:
            choices = [t for t in foliage_templates if any(k in t["label"] for k in ("reed", "riverbank", "sedge", "wet", "spray", "fern"))]
        else:
            choices = [t for t in foliage_templates if not any(k in t["label"] for k in ("reed", "lily", "algae"))]
        tpl = RNG.choice(choices or foliage_templates)
        sc = RNG.uniform(0.85, 1.65)
        if place_instance("VB_ModelAssetFoliage", tpl, wx, wy, wz, sc, radius_mult=0.72):
            counts["foliage"] += 1

    attempts = 0
    while counts["rocks"] < rock_count and attempts < rock_count * 16 and rock_templates:
        attempts += 1
        if RNG.random() < 0.40:
            wx = RNG.uniform(-420.0, 420.0)
            wy = RNG.uniform(-55.0, 70.0)
        elif RNG.random() < 0.55:
            p = RIVER_POINTS[RNG.randint(6, len(RIVER_POINTS) - 1)]
            wx = p[0] + RNG.uniform(-28.0, 28.0)
            wy = p[1] + RNG.uniform(-28.0, 28.0)
        else:
            wx = RNG.uniform(X_MIN + 24.0, X_MAX - 24.0)
            wy = RNG.uniform(Y_MIN + 24.0, Y_MAX - 24.0)
        wz = sample_h(hm, wx, wy)
        if wz < LAKE_WATER_LEVEL + 0.5 or wz > 245.0:
            continue
        if _hydro_zone(wx, wy) == "water":
            continue
        tpl = RNG.choice(rock_templates)
        sc = RNG.uniform(0.65, 1.55)
        if "pebbles" in tpl["label"]:
            sc *= 0.75
        if place_instance("VB_ModelAssetRock", tpl, wx, wy, wz, sc, radius_mult=1.55):
            counts["rocks"] += 1

    log(f"model_asset detail: {counts['foliage']} foliage, {counts['rocks']} rocks")
    return counts


def scatter_water_surface_assets(hm: Heightmap, count: int = 95) -> int:
    """Place floating plant assets only on calm lake water, never on banks or river flow.

    T1-38 (Y04 v3, cert-YES, XR-003 missing-content) — Previously the function
    returned 0 unconditionally with 44 lines of dead code below. The dead
    scatter logic is real, was previously working, and the audit decision is
    "ship the feature" (vs delete). The legacy disabled-until-rebuilt comment
    is preserved as a known-failure note: if downstream artefacts surface,
    the gate is the empty-templates check below (silent skip when no lily/
    algae GLBs exist on disk).
    """
    log(f"water surface foliage: scattering up to {count} lily/algae assets")
    templates = _load_model_asset_templates(_model_water_surface_asset_specs())
    if not templates:
        log("water surface foliage: no external lily/algae templates found")
        return 0

    col = bpy.data.collections.new("VB_WaterSurfaceFoliage")
    bpy.context.scene.collection.children.link(col)
    occupied: list[tuple[float, float, float]] = []
    placed = 0
    attempts = 0
    while placed < count and attempts < count * 22:
        attempts += 1
        ang = RNG.uniform(0.0, math.tau)
        shore = float(lake_shore_radius(ang))
        # Bias toward shelves and edges; the center stays open so the lake reads as water volume.
        r = shore * (0.42 + 0.54 * (RNG.random() ** 0.42))
        wx = LAKE_XY[0] + math.cos(ang) * r + RNG.uniform(-2.5, 2.5)
        wy = LAKE_XY[1] + math.sin(ang) * r + RNG.uniform(-2.5, 2.5)
        if _hydro_zone(wx, wy) != "water":
            continue
        river_d, river_w = _river_clearance(wx, wy)
        if river_d < river_w * 3.25:
            continue
        terrain_z = sample_h(hm, wx, wy)
        if terrain_z > LAKE_WATER_LEVEL - 0.08:
            continue
        tpl = RNG.choice(templates)
        scale = RNG.uniform(0.16, 0.44)
        radius = tpl["radius"] * scale * 1.45
        if any((px - wx) ** 2 + (py - wy) ** 2 < (radius + pr) ** 2 for px, py, pr in occupied[-220:]):
            continue

        obj = bpy.data.objects.new(f"VB_WaterPlant_{placed:03d}", tpl["mesh"])
        obj.location = (wx, wy, LAKE_WATER_LEVEL + 0.055)
        obj.scale = (scale * RNG.uniform(0.82, 1.24), scale * RNG.uniform(0.82, 1.24), scale)
        obj.rotation_euler = (RNG.uniform(-0.025, 0.025), RNG.uniform(-0.025, 0.025),
                              RNG.uniform(0.0, math.tau))
        obj.visible_shadow = False
        col.objects.link(obj)
        occupied.append((wx, wy, radius))
        placed += 1

    log(f"water surface foliage: {placed} placed")
    return placed


def _cliff_strata_band_specs() -> list[tuple[float, float, float]]:
    """Return ``(y_base, band_h, lift)`` rows describing cliff stratigraphy bands.

    T1-39 (Y04 v3, cert-YES, XR-003 missing-content). Previously the list was
    empty so ``VB_Cliff_Strata`` materialised with 0 polygons and every cliff
    rendered monolithic-flat.

    Band placement strategy (T1-39 round-2 per CE review CORR-T1-39-01):
    the strata loop sweeps the full world-X range (-430..+430) and relies
    on the per-step height guard (``LAKE_WATER_LEVEL + 12 < z < 310``) to
    stamp bands ONLY on cliff-height terrain. Y values cover BOTH the
    LAKE_XY band (Y ~ -315, the south cliff face) and the mid-map cliff
    band (Y ~ 0), so wherever cliff geometry exists the strata read
    correctly. The lift values stagger so bands do not z-fight.

    NOTE: this is the initial placement set. Visual verification via the
    11-camera Wave-VV proof is mandatory before claiming the cliff strata
    look correct — if the south cliff has no cliff-height terrain at Y in
    [-320, -310], or the mid-map cliff is absent, those band rows will
    stamp 0 polygons silently and the cliff face will look monolithic
    along that Y axis. Follow-up to add a render-pass that asserts
    ``len(strata_bm.faces) > 0`` per band row.

    Tuple semantics — keep in sync with ``build_cliff_strata_and_talus``:
      - y_base: world-space Y centre for this band's ribbon.
      - band_h: half-thickness in metres (top/bot vertex offset from z).
      - lift:   vertical offset from the sampled terrain height.
    """
    # 7 sediment bands across BOTH cliff regions:
    #   4 bands at Y in [-320..-310] for the south cliff face (LAKE_XY=-315)
    #   3 bands at Y in [-2..7] for the mid-map cliff (if present)
    # The height guards in the consuming loop ensure bands only stamp on
    # actual cliff terrain regardless of which region exists.
    return [
        (-320.0, 0.18, 0.40),  # south cliff — bottom band, closest to lake
        (-317.0, 0.22, 1.10),  # south cliff — mid-low
        (-314.0, 0.26, 1.90),  # south cliff — mid-high
        (-311.0, 0.30, 2.80),  # south cliff — top
        (-2.0, 0.20, 0.70),    # mid-map cliff — lower (if present)
        (2.0, 0.24, 1.60),     # mid-map cliff — mid
        (6.0, 0.28, 2.50),     # mid-map cliff — upper
    ]


def _cliff_ledge_y_bases() -> tuple[float, ...]:
    """Return Y-coords for the ledge shelves cut into the cliff face.

    T1-39 (Y04 v3) sibling fix. Previously this was an empty tuple at the
    ``enumerate(())`` call site so ``VB_Cliff_Ledges`` was a 0-polygon mesh.
    Round-2 (CE review CORR-T1-39-01): cover BOTH the LAKE_XY south cliff
    band (Y ~ -315) and the mid-map cliff band (Y ~ 0) so ledges materialise
    wherever cliff terrain exists — the per-step height guard
    (``LAKE_WATER_LEVEL + 16 < z < 300``) filters non-cliff cells.
    """
    return (-316.5, -312.0, -4.5, 2.5, 9.0)


def build_cliff_strata_and_talus(hm: Heightmap, talus_count: int = 165) -> int:
    """Add readable sediment bands and broken talus to the south cliff face."""
    strata_mat = _simple_principled_material("VB_CliffStrataDark", (0.13, 0.11, 0.09, 1),
                                             roughness=0.96)
    ledge_mat = _simple_principled_material("VB_CliffLedgeStone", (0.24, 0.22, 0.18, 1),
                                            roughness=0.94)

    strata_bm = bmesh.new()
    # T1-39: band_specs was previously [] so VB_Cliff_Strata materialised
    # with 0 polygons. _cliff_strata_band_specs() returns 4 sediment beds
    # laterally offset along Y so the bands read as parallel strata rather
    # than the broad-horizontal-strip terrace-bug the old generator
    # produced. See cross-wave note in MASTER_FINAL §B.4.5 / X02 row 1.
    band_specs = _cliff_strata_band_specs()
    for band_idx, (y_base, band_h, lift) in enumerate(band_specs):
        last_top = None
        last_bot = None
        for step in range(54):
            x = -430.0 + step * (860.0 / 53.0)
            y = y_base + 4.0 * math.sin(step * 0.31 + band_idx * 0.9)
            z = sample_h(hm, x, y) + lift
            if z < LAKE_WATER_LEVEL + 12.0 or z > 310.0:
                last_top = last_bot = None
                continue
            top = strata_bm.verts.new((x, y + 0.18, z + band_h))
            bot = strata_bm.verts.new((x, y - 0.18, z - band_h))
            if last_top and last_bot:
                try:
                    strata_bm.faces.new((last_bot, bot, top, last_top))
                except ValueError:
                    pass
            last_top, last_bot = top, bot
    strata_bm.normal_update()
    strata_mesh = bpy.data.meshes.new("VB_Cliff_Strata_Mesh")
    strata_bm.to_mesh(strata_mesh)
    strata_bm.free()
    strata_obj = bpy.data.objects.new("VB_Cliff_Strata", strata_mesh)
    bpy.context.collection.objects.link(strata_obj)
    strata_obj.data.materials.append(strata_mat)

    ledge_bm = bmesh.new()
    # T1-39: enumerate(()) on the empty tuple produced 0 ledge geometry.
    # _cliff_ledge_y_bases() returns 3 staggered Y-coords so the ledges
    # form readable traversable shelves below, between, and above the
    # strata bands.
    for band_idx, y_base in enumerate(_cliff_ledge_y_bases()):
        prev = None
        for step in range(34):
            x = -380.0 + step * (760.0 / 33.0)
            y = y_base + 5.0 * math.sin(step * 0.41 + band_idx)
            z = sample_h(hm, x, y) + 0.55
            if z < LAKE_WATER_LEVEL + 16.0 or z > 300.0:
                prev = None
                continue
            shelf = RNG.uniform(1.6, 4.2)
            v0 = ledge_bm.verts.new((x - 5.0, y - shelf, z + 0.20))
            v1 = ledge_bm.verts.new((x + 5.0, y - shelf * 0.9, z + 0.15))
            v2 = ledge_bm.verts.new((x + 4.0, y + 0.35, z + 0.55))
            v3 = ledge_bm.verts.new((x - 4.0, y + 0.30, z + 0.60))
            try:
                ledge_bm.faces.new((v0, v1, v2, v3))
            except ValueError:
                pass
            if prev and RNG.random() < 0.35:
                try:
                    ledge_bm.faces.new((prev[1], v0, v3, prev[2]))
                except ValueError:
                    pass
            prev = (v0, v1, v2, v3)
    ledge_bm.normal_update()
    ledge_mesh = bpy.data.meshes.new("VB_Cliff_Ledges_Mesh")
    ledge_bm.to_mesh(ledge_mesh)
    ledge_bm.free()
    ledge_obj = bpy.data.objects.new("VB_Cliff_Ledges", ledge_mesh)
    bpy.context.collection.objects.link(ledge_obj)
    ledge_obj.data.materials.append(ledge_mat)

    talus_col = bpy.data.collections.new("VB_Cliff_Talus")
    bpy.context.scene.collection.children.link(talus_col)
    talus_mat = _simple_principled_material("VB_TalusStone", (0.19, 0.17, 0.14, 1),
                                            roughness=0.95)
    templates = []
    for ti in range(5):
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=1 if ti < 3 else 2, radius=1.0)
        rng_t = random.Random(SEED + 6100 + ti)
        for v in bm.verts:
            v.co.x *= rng_t.uniform(0.55, 1.95)
            v.co.y *= rng_t.uniform(0.45, 1.45)
            v.co.z *= rng_t.uniform(0.22, 0.78)
        bm.normal_update()
        mesh = bpy.data.meshes.new(f"VB_TalusTpl_{ti}")
        bm.to_mesh(mesh)
        bm.free()
        mesh.materials.append(talus_mat)
        templates.append(mesh)

    placed = 0
    attempts = 0
    while placed < talus_count and attempts < talus_count * 18:
        attempts += 1
        wx = RNG.uniform(-440.0, 440.0)
        wy = RNG.uniform(-55.0, 58.0)
        wz = sample_h(hm, wx, wy)
        if wz < LAKE_WATER_LEVEL + 8.0 or wz > 260.0:
            continue
        if math.hypot(wx - LAKE_XY[0], wy - LAKE_XY[1]) < LAKE_RADIUS + 24.0:
            continue
        size = RNG.uniform(0.45, 2.8) ** 1.08
        obj = bpy.data.objects.new(f"VB_Talus_{placed:03d}", templates[RNG.randint(0, len(templates) - 1)])
        obj.location = (wx, wy, wz - size * 0.18)
        obj.scale = (size * RNG.uniform(0.8, 1.35), size * RNG.uniform(0.65, 1.15), size)
        obj.rotation_euler = (RNG.uniform(-0.35, 0.35), RNG.uniform(-0.25, 0.25),
                              RNG.uniform(0.0, math.tau))
        talus_col.objects.link(obj)
        placed += 1

    log(f"cliff detail: strata bands + ledges + {placed} talus rocks")
    return placed


# ---------------------------------------------------------------------------
# external model provider catalog — import and scatter GLB assets generated by external model provider.
# Falls back silently when catalog.json is absent or all entries missing on
# disk so the build completes without provider auth.
# ---------------------------------------------------------------------------
def scatter_model_asset_catalog(terrain_obj: bpy.types.Object, hm: Heightmap, count: int = 40) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    cat_path = repo_root / "assets" / "foliage" / "catalog.json"

    if not cat_path.exists():
        log("model_asset_catalog: catalog.json not found — skipping external prop scatter")
        return 0

    try:
        catalog = json.loads(cat_path.read_text(encoding="utf-8"))
    except Exception as exc:
        log(f"model_asset_catalog: parse error: {exc}")
        return 0

    # catalog["assets"] is a dict keyed by asset_id (written by ingest_model_asset_asset.py)
    # Each entry has: {"lods": [{"lod": 0, "path": "/abs/path/lod0.glb"}, ...]}
    asset_map = catalog.get("assets", {})
    entries = list(asset_map.values()) if isinstance(asset_map, dict) else asset_map

    def _lod0(entry: dict[str, Any]) -> str:
        lods = entry.get("lods", [])
        return str(lods[0].get("path", "")) if lods else ""

    valid = [e for e in entries if _lod0(e) and Path(_lod0(e)).exists()]

    if not valid:
        log(f"model_asset_catalog: {len(entries)} catalog entries, 0 GLBs on disk — skipping")
        return 0

    log(f"model_asset_catalog: placing up to {count} instances from {len(valid)} GLBs")
    model_asset_col = bpy.data.collections.new("VB_ModelAssetProps")
    bpy.context.scene.collection.children.link(model_asset_col)

    placed = 0
    placed_xys: list[tuple[float, float]] = []
    instances_per = max(1, count // len(valid))

    for asset in valid:
        glb_path = _lod0(asset)
        try:
            bpy.ops.import_scene.gltf(filepath=glb_path)
        except Exception as exc:
            log(f"model_asset_catalog: import failed for {glb_path}: {exc}")
            continue

        imported = [o for o in bpy.context.selected_objects if o.type == "MESH"]
        if not imported:
            continue

        template = imported[0]
        for o in imported:
            for col in list(o.users_collection):
                col.objects.unlink(o)
            model_asset_col.objects.link(o)
        template.hide_render = True
        template.hide_viewport = True

        inst, attempts = 0, 0
        while inst < instances_per and attempts < instances_per * 15:
            attempts += 1
            wx = RNG.uniform(X_MIN + 20, X_MAX - 20)
            wy = RNG.uniform(Y_MIN + 20, Y_MAX - 20)
            wz = sample_h(hm, wx, wy)

            if wz < LAKE_WATER_LEVEL + 1.5:
                continue
            if wz > 240.0:
                continue
            if math.hypot(wx - LAKE_XY[0], wy - LAKE_XY[1]) < LAKE_RADIUS + 10.0:
                continue
            if any((px - wx) ** 2 + (py - wy) ** 2 < 64.0
                   for px, py in placed_xys[-200:]):
                continue

            obj = bpy.data.objects.new(f"VB_ModelAsset_{placed:04d}", template.data)
            obj.location = (wx, wy, wz)
            scale = RNG.uniform(0.8, 1.4)
            obj.scale = (scale, scale, scale)
            obj.rotation_euler = (0.0, 0.0, RNG.uniform(0, math.tau))
            model_asset_col.objects.link(obj)
            placed_xys.append((wx, wy))
            inst += 1
            placed += 1

    log(f"model_asset_catalog: {placed} props placed from {len(valid)} catalog assets")
    return placed


# ---------------------------------------------------------------------------
# Grass — hair particle system, vertex-group restricted to gentle flat terrain
# ---------------------------------------------------------------------------
def add_grass(terrain_obj: bpy.types.Object, hm: Heightmap) -> None:
    # Grass blade: 3 crossed quads, origin at Z=0 (base), tapered toward tip
    gbm = bmesh.new()
    blade_h = 0.42
    blade_w = 0.055
    for ang in (0.0, math.pi / 3.0, -math.pi / 3.0):
        s, c = math.sin(ang), math.cos(ang)
        v0 = gbm.verts.new((-s * blade_w, -c * blade_w, 0.0))
        v1 = gbm.verts.new((s * blade_w, c * blade_w, 0.0))
        v2 = gbm.verts.new((s * blade_w * 0.25, c * blade_w * 0.25, blade_h))
        v3 = gbm.verts.new((-s * blade_w * 0.25, -c * blade_w * 0.25, blade_h))
        gbm.faces.new((v0, v1, v2, v3))
    gmesh = bpy.data.meshes.new("VB_GrassBlade")
    gbm.to_mesh(gmesh)
    gbm.free()
    grass_obj = bpy.data.objects.new("VB_GrassBlade", gmesh)
    bpy.context.collection.objects.link(grass_obj)
    grass_obj.hide_render = True
    grass_obj.hide_viewport = True
    gmat = bpy.data.materials.new("VB_GrassMat")
    gmat.use_nodes = True
    gmat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.08, 0.15, 0.05, 1)
    gmat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.80
    gmesh.materials.append(gmat)

    # Vertex group: weight=1 on flat low-altitude areas, 0 on cliffs/heights/lake
    vg = terrain_obj.vertex_groups.new(name="GrassDensity")
    mesh = terrain_obj.data
    all_vi = list(range(len(mesh.vertices)))
    vg.add(all_vi, 0.0, "REPLACE")
    grass_vi = []
    for vi in all_vi:
        v = mesh.vertices[vi]
        wz = v.co.z
        wx, wy = v.co.x, v.co.y
        if (LAKE_WATER_LEVEL + 1.5) < wz < 52.0:
            if _hydro_zone(wx, wy) == "dry" and _surface_slope(hm, wx, wy) < 0.26:
                grass_vi.append(vi)
    if grass_vi:
        vg.add(grass_vi, 1.0, "REPLACE")
    log(f"grass vertex group: {len(grass_vi)}/{len(all_vi)} verts weighted")

    # Particle system
    terrain_obj.modifiers.new("GrassPS", type="PARTICLE_SYSTEM")
    psys = terrain_obj.particle_systems[-1]
    settings = psys.settings
    settings.type = "HAIR"
    settings.count = 18000
    settings.render_type = "OBJECT"
    settings.instance_object = grass_obj
    settings.particle_size = 0.65
    settings.size_random = 0.35
    # Align to surface normal so blades grow from terrain, not float
    settings.use_rotations = True
    settings.rotation_mode = "NOR"
    settings.phase_factor_random = 1.0        # random yaw per blade
    settings.rotation_factor_random = 0.06   # subtle tilt variation
    # Disable child particles (they caused the "cubes" artifact)
    for attr in ("child_nbr", "child_percent"):
        if hasattr(settings, attr):
            try:
                setattr(settings, attr, 0)
            except Exception:
                pass
    try:
        settings.hair_length = 1.0
    except Exception:
        pass
    try:
        settings.use_advanced_hair = True
    except Exception:
        pass
    # Restrict emission to GrassDensity vertex group
    psys.vertex_group_density = "GrassDensity"
    log("grass particle system added")


def scatter_grass_clumps(terrain_obj: bpy.types.Object, hm: Heightmap, count: int = 1500) -> int:
    grass_col = bpy.data.collections.new("VB_GrassClumps")
    bpy.context.scene.collection.children.link(grass_col)

    mats = []
    for name, color in (
        ("VB_GrassMeadow", (0.11, 0.22, 0.065, 1)),
        ("VB_GrassDryEdge", (0.27, 0.25, 0.12, 1)),
        ("VB_GrassWetBank", (0.05, 0.16, 0.08, 1)),
    ):
        mat = _simple_principled_material(name, color, roughness=0.86)
        mats.append(mat)

    templates = [
        _make_grass_clump_mesh("VB_GrassClumpShort", 7, 0.62, 0.035, 0.18),
        _make_grass_clump_mesh("VB_GrassClumpMeadow", 10, 0.95, 0.045, 0.26),
        _make_grass_clump_mesh("VB_GrassClumpReed", 12, 1.35, 0.035, 0.34),
    ]
    for i, mesh in enumerate(templates):
        mesh.materials.append(mats[i])

    placed = 0
    attempts = 0
    recent: list[tuple[float, float]] = []
    while placed < count and attempts < count * 18:
        attempts += 1
        if RNG.random() < 0.45:
            pidx = RNG.randint(6, len(RIVER_POINTS) - 1)
            p = RIVER_POINTS[pidx]
            wx = p[0] + RNG.uniform(-34.0, 34.0)
            wy = p[1] + RNG.uniform(-34.0, 34.0)
        elif RNG.random() < 0.28:
            ang = RNG.uniform(0.0, math.tau)
            r = RNG.uniform(LAKE_RADIUS * 1.18, LAKE_RADIUS * 1.75)
            wx = LAKE_XY[0] + math.cos(ang) * r
            wy = LAKE_XY[1] + math.sin(ang) * r
        else:
            wx = RNG.uniform(X_MIN + 15.0, X_MAX - 15.0)
            wy = RNG.uniform(Y_MIN + 15.0, Y_MAX - 15.0)

        if not (X_MIN < wx < X_MAX and Y_MIN < wy < Y_MAX):
            continue
        wz = sample_h(hm, wx, wy)
        if wz < LAKE_WATER_LEVEL + 0.7 or wz > 74.0:
            continue
        zone = _hydro_zone(wx, wy)
        if zone == "water":
            continue

        dx = sample_h(hm, min(X_MAX, wx + 2.0), wy) - sample_h(hm, max(X_MIN, wx - 2.0), wy)
        dy = sample_h(hm, wx, min(Y_MAX, wy + 2.0)) - sample_h(hm, wx, max(Y_MIN, wy - 2.0))
        slope = math.hypot(dx, dy) / 4.0
        if slope > 0.55:
            continue
        min_dist = 1.5 if placed < 700 else 1.0
        if any((px - wx) ** 2 + (py - wy) ** 2 < min_dist * min_dist for px, py in recent[-450:]):
            continue

        near_water = zone == "wet_bank"
        template_idx = 2 if near_water and RNG.random() < 0.55 else RNG.randint(0, 1)
        obj = bpy.data.objects.new(f"VB_GrassClump_{placed:04d}", templates[template_idx])
        obj.location = (wx, wy, wz + 0.03)
        sc = RNG.uniform(0.75, 1.45)
        obj.scale = (sc * RNG.uniform(0.75, 1.35), sc * RNG.uniform(0.75, 1.35), sc)
        obj.rotation_euler = (RNG.uniform(-0.05, 0.05), RNG.uniform(-0.05, 0.05),
                              RNG.uniform(0.0, math.tau))
        grass_col.objects.link(obj)
        recent.append((wx, wy))
        placed += 1

    log(f"grass clumps: {placed} blade clusters placed")
    return placed


# ---------------------------------------------------------------------------
# Lighting, world, compositor
# ---------------------------------------------------------------------------
def setup_world() -> None:
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(28)
    sky.sun_rotation = AZIMUTH_RAD
    sky.sun_intensity = 0.15
    sky.air_density = 1.0
    sky.dust_density = 1.0
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.30
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def setup_sun() -> bpy.types.Object:
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 100))
    sun = bpy.context.view_layer.objects.active
    sun.name = "VB_Sun"
    sun.data.energy = 1.05
    sun.data.angle = math.radians(1.5)
    sun.data.color = (1.0, 0.88, 0.72)
    sun.rotation_euler = (math.radians(55), 0, AZIMUTH_RAD)
    # Cool fill from north so backlit mountain faces aren't pitch-black in orbit
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 100))
    fill = bpy.context.view_layer.objects.active
    fill.name = "VB_Fill"
    fill.data.energy = 0.38
    fill.data.color = (0.62, 0.72, 1.0)
    fill.rotation_euler = (math.radians(38), 0, math.radians(215))
    # Ground-bounce fill: very low angle from south, warm ambient
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 100))
    bounce = bpy.context.view_layer.objects.active
    bounce.name = "VB_Bounce"
    bounce.data.energy = 0.10
    bounce.data.color = (1.0, 0.95, 0.82)
    bounce.rotation_euler = (math.radians(75), 0, math.radians(195))
    # Large area light above scene — soft sky-ambient so north mountain face is never black
    bpy.ops.object.light_add(type="AREA", location=(0, 0, 700))
    sky_amb = bpy.context.view_layer.objects.active
    sky_amb.name = "VB_SkyAmb"
    sky_amb.data.energy = 125.0
    sky_amb.data.size = 2200.0
    sky_amb.data.color = (0.68, 0.80, 1.0)
    sky_amb.rotation_euler = (0, 0, 0)   # faces straight down
    # Rim from south: horizontal fill to reach north-facing slopes without top-occlusion
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 100))
    rim = bpy.context.view_layer.objects.active
    rim.name = "VB_NorthRim"
    rim.data.energy = 0.26
    rim.data.color = (0.70, 0.80, 1.0)
    rim.rotation_euler = (math.radians(88), 0, math.radians(0))  # nearly horizontal, from south
    try:
        rim.data.cycles.cast_shadow = False
    except AttributeError:
        pass
    return sun


def setup_compositor() -> None:
    scn = bpy.context.scene
    scn.use_nodes = True
    nt = scn.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rl = nt.nodes.new("CompositorNodeRLayers")
    glare = nt.nodes.new("CompositorNodeGlare")
    glare.glare_type = "FOG_GLOW"
    glare.quality = "HIGH"
    glare.mix = 0.05
    glare.threshold = 0.8
    lens = nt.nodes.new("CompositorNodeLensdist")
    lens.use_fit = True
    for key, val in (("Distort", 0.015), ("Distortion", 0.015)):
        if key in lens.inputs:
            try:
                lens.inputs[key].default_value = val
                break
            except Exception:
                pass
    if "Dispersion" in lens.inputs:
        try:
            lens.inputs["Dispersion"].default_value = 0.003
        except Exception:
            pass
    cbal = nt.nodes.new("CompositorNodeColorBalance")
    cbal.correction_method = "LIFT_GAMMA_GAIN"
    cbal.lift = (0.98, 0.99, 1.02)
    cbal.gamma = (1.02, 1.00, 0.98)
    cbal.gain = (1.06, 1.04, 1.00)
    out = nt.nodes.new("CompositorNodeComposite")
    nt.links.new(rl.outputs["Image"], glare.inputs["Image"])
    nt.links.new(glare.outputs["Image"], lens.inputs["Image"])
    nt.links.new(lens.outputs["Image"], cbal.inputs["Image"])
    nt.links.new(cbal.outputs["Image"], out.inputs["Image"])


def setup_hero_camera() -> bpy.types.Object:
    """Cinematic establishing shot: from SSW looking NNE, showing flatland + lake + mountain."""
    cam_data = bpy.data.cameras.new("CAM_Hero")
    cam_data.lens = 32.0
    cam_data.clip_end = 4000.0
    cam = bpy.data.objects.new("CAM_Hero", cam_data)
    bpy.context.collection.objects.link(cam)
    # Position: south, elevated — frames lake (bottom-centre), flatland, cliff, and peaks together
    cam.location = (-60.0, -700.0, 180.0)
    target = Vector((80.0, -80.0, 50.0))
    d = target - Vector(cam.location)
    if d.length > 0:
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    return cam


def setup_cave_pov_camera() -> bpy.types.Object:
    """Camera positioned near cave entrance looking into the tunnel."""
    cam_data = bpy.data.cameras.new("CAM_CavePOV")
    cam_data.lens = 24.0
    cam_data.clip_end = 800.0
    cam = bpy.data.objects.new("CAM_CavePOV", cam_data)
    bpy.context.collection.objects.link(cam)
    # South face of mountain, looking toward cave opening
    cam.location = (-30.0, 70.0, 175.0)
    target = Vector((CAVE_ENTRY[0], CAVE_ENTRY[1] + 15.0, CAVE_ENTRY[2]))
    d = target - Vector(cam.location)
    if d.length > 0:
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return cam


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
def configure_render(samples: int = 64, res_x: int = 1920, res_y: int = 1080) -> None:
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.samples = samples
    scn.cycles.use_denoising = True
    scn.render.resolution_x = res_x
    scn.render.resolution_y = res_y
    scn.render.resolution_percentage = 100
    scn.render.image_settings.file_format = "PNG"
    scn.view_settings.view_transform = "AgX"
    scn.view_settings.exposure = 0.0
    try:
        scn.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    try:
        prefs = bpy.context.preferences
        cp = prefs.addons.get('cycles')
        if cp:
            cp.preferences.compute_device_type = 'OPTIX'
            cp.preferences.get_devices()
            for d in cp.preferences.devices:
                d.use = True
        scn.cycles.device = "GPU"
    except Exception:
        pass


def render_to(filepath: Path) -> None:
    bpy.context.scene.render.filepath = str(filepath)
    bpy.ops.render.render(write_still=True)
    log(f"rendered -> {filepath.name}")


def render_orbit(out_dir: Path, frames: int = 8,
                 radius: float = 480.0, height: float = 420.0) -> None:
    orbit_dir = out_dir / "orbit"
    orbit_dir.mkdir(exist_ok=True)
    configure_render(samples=96, res_x=1280, res_y=720)
    cam_data = bpy.data.cameras.new("CAM_Orbit")
    cam_data.lens = 35.0
    cam_data.clip_end = 4000.0
    cam = bpy.data.objects.new("CAM_Orbit", cam_data)
    bpy.context.collection.objects.link(cam)
    target = Vector((0.0, 0.0, 80.0))
    for i in range(frames):
        ang = 2 * math.pi * (i / frames) + math.radians(22)  # offset avoids pure-north shadow position
        cam.location = (math.cos(ang) * radius, math.sin(ang) * radius, height)
        d = target - Vector(cam.location)
        if d.length > 0:
            cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        bpy.context.scene.camera = cam
        render_to(orbit_dir / f"orbit_{i:02d}.png")
    log(f"orbit: {frames} frames done")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    failure_log = OUT_DIR / "BUILD_FAILURE.log"
    if failure_log.exists():
        failure_log.unlink()

    # ---- Heightmap ----
    log("composing heightmap...")
    try:
        hm = compose_heightmap()
    except Exception as exc:
        log_fail("heightmap", exc)
        sys.exit(1)

    # ---- Terrain mesh + material ----
    log("building terrain mesh...")
    terrain = build_terrain_mesh(hm)
    terrain.data.materials.append(make_terrain_material())

    # ---- Cave ----
    log("carving cave...")
    try:
        carve_cave(terrain)
    except Exception as exc:
        log_fail("cave", exc)

    # ---- Water ----
    log("building water surfaces...")
    try:
        build_beach_ring(hm)
        build_water_surfaces(hm)
    except Exception as exc:
        log_fail("water", exc)

    # ---- Bridge + approach paths: canonical callables and contracts ----
    bridge_path_result: dict[str, Any] = {}
    log("building bridge crossing and approach paths...")
    try:
        bridge_path_result = build_bridge_and_approach_paths(terrain, hm)
    except Exception as exc:
        log_fail("bridge_paths", exc)

    # ---- Cliff anatomy: strata/ledges/talus are required for readable mountain faces ----
    log("building cliff strata and talus...")
    n_cliff_talus = 0
    try:
        n_cliff_talus = build_cliff_strata_and_talus(hm)
    except Exception as exc:
        log_fail("cliff_detail", exc)

    # ---- Trees: prefer normalized external GLBs; procedural templates are fallback only ----
    n_trees = 0
    log("scattering normalized model-asset trees...")
    try:
        n_trees = scatter_model_asset_trees(terrain, hm, count=430)
    except Exception as exc:
        log_fail("model_asset_trees", exc)
    if n_trees == 0:
        log("falling back to procedural tree templates...")
        try:
            pine_mesh = make_pine_mesh()
            broad_mesh = make_broad_tree_mesh()
            n_trees = scatter_trees(terrain, hm, pine_mesh, broad_mesh, count=MIN_FOREST_TREE_TARGET)
        except Exception as exc:
            log_fail("trees_fallback", exc)
    else:
        log("adding supplemental procedural broadleaf forest fill...")
        try:
            pine_mesh = make_pine_mesh()
            broad_mesh = make_broad_tree_mesh()
            n_trees += scatter_trees(terrain, hm, pine_mesh, broad_mesh, count=240)
        except Exception as exc:
            log_fail("trees_supplemental", exc)
    if 0 < n_trees < MIN_FOREST_TREE_TARGET:
        log("forest density below target; adding procedural forest fill...")
        try:
            pine_mesh = bpy.data.meshes.get("PineMesh") or make_pine_mesh()
            broad_mesh = bpy.data.meshes.get("BroadTreeMesh") or make_broad_tree_mesh()
            n_trees += scatter_trees(
                terrain,
                hm,
                pine_mesh,
                broad_mesh,
                count=MIN_FOREST_TREE_TARGET - n_trees,
            )
        except Exception as exc:
            log_fail("trees_min_density_fill", exc)

    # ---- Rocks ----
    log("scattering fallback procedural rocks...")
    n_rocks = 0
    try:
        n_rocks = scatter_rocks(terrain, hm, count=85)
    except Exception as exc:
        log_fail("rocks", exc)

    # ---- model-asset foliage / rock details ----
    log("scattering normalized model-asset foliage and rocks...")
    n_talus = n_cliff_talus
    n_grass_clumps = 0
    n_procedural_grass_clumps = 0
    n_model_asset_detail = 0
    n_water_surface_foliage = 0
    try:
        n_water_surface_foliage = scatter_water_surface_assets(hm, count=85)
    except Exception as exc:
        log_fail("water_surface_foliage", exc)
    try:
        detail_counts = scatter_model_asset_detail_assets(hm, foliage_count=1800, rock_count=180)
        n_grass_clumps = detail_counts["foliage"]
        n_talus += detail_counts["rocks"]
        n_model_asset_detail = n_grass_clumps + n_talus + n_water_surface_foliage
    except Exception as exc:
        log_fail("model_asset_detail", exc)

    n_model_asset = n_trees + n_model_asset_detail

    log("scattering supplemental blade grass clumps...")
    try:
        n_procedural_grass_clumps = scatter_grass_clumps(terrain, hm, count=2400)
    except Exception as exc:
        log_fail("grass_clumps", exc)

    # ---- Grass particle fill, restrained under model-asset clumps ----
    log("adding restrained particle grass fill...")
    try:
        add_grass(terrain, hm)
    except Exception as exc:
        log_fail("grass", exc)

    # ---- Node-level guardrail contracts ----
    node_contracts: dict[str, Any] = {}
    log("validating node generation contracts...")
    try:
        node_contracts = validate_node_generation_contracts(
            hm,
            bridge_path_result,
            scatter_counts={
                "trees": n_trees,
                "foliage": n_grass_clumps + n_procedural_grass_clumps,
                "rocks": n_rocks + n_talus,
            },
        )
        if node_contracts.get("issues"):
            raise RuntimeError(node_contracts["issues"])
    except Exception as exc:
        log_fail("node_contracts", exc)

    # ---- Lighting / world / compositor ----
    log("setup lighting + compositor...")
    setup_world()
    setup_sun()
    setup_compositor()
    hero_cam = setup_hero_camera()
    setup_cave_pov_camera()

    # ---- Save .blend ----
    blend_path = OUT_DIR / "VeilBreakers_Scene_v3.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    log(f"saved {blend_path}")

    # ---- Hero render (1920×1080, 64 spp) ----
    configure_render(samples=96, res_x=1920, res_y=1080)
    bpy.context.scene.camera = hero_cam
    render_to(OUT_DIR / "render_hero.png")

    # ---- 8-frame orbit ----
    log("orbit renders...")
    render_orbit(OUT_DIR, frames=8)

    # ---- Summary ----
    summary = {
        "tile_m": TILE_M,
        "heightmap_min_m": float(hm.min()),
        "heightmap_max_m": float(hm.max()),
        "mountain_peak_z": MOUNTAIN_PEAK_Z,
        "lake_water_level": LAKE_WATER_LEVEL,
        "lake_radius_m": LAKE_RADIUS,
        "waterfall_top_z": WATERFALL_TOP_Z,
        "cave_entry": CAVE_ENTRY,
        "cave_exit": CAVE_EXIT,
        "trees_placed": n_trees,
        "rocks_placed": n_rocks,
        "model_asset_rocks_placed": n_talus,
        "grass_clumps_placed": n_grass_clumps,
        "water_surface_foliage_placed": n_water_surface_foliage,
        "procedural_grass_clumps_placed": n_procedural_grass_clumps,
        "model_asset_props_placed": n_model_asset,
        "bridge_paths": bridge_path_result,
        "node_contracts": node_contracts,
        "failures": len(FAILURES),
        "failure_stages": [f["stage"] for f in FAILURES],
        "blend_path": str(blend_path),
    }
    (OUT_DIR / "BUILD_SUMMARY.json").write_text(json.dumps(summary, indent=2))
    log(f"DONE — {len(FAILURES)} failures, {n_trees} trees, {n_rocks} fallback rocks, {n_talus} model-asset rocks, {n_grass_clumps} model-asset foliage, {n_water_surface_foliage} water plants, {n_procedural_grass_clumps} grass clumps, {n_model_asset} model-asset props")
    if FAILURES:
        for f in FAILURES:
            log(f"  FAIL {f['stage']}: {f['error']}")
    elif failure_log.exists():
        failure_log.unlink()
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:
        traceback.print_exc()
        try:
            (OUT_DIR / "BUILD_FAILURE.log").write_text(traceback.format_exc())
        except Exception:
            pass
        sys.exit(1)
    sys.exit(rc)


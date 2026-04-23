"""Bundle J — terrain_unity_export.

Writes Unity-ready terrain artifacts from a ``TerrainMaskStack``:
16-bit RAW heightmaps, packed RAW splatmaps, RAW detail layers, binary
auxiliary grids, and JSON descriptors with explicit Y-up coordinates.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .terrain_semantics import BBox, PassDefinition, PassResult, TerrainMaskStack, TerrainPipelineState
from .terrain_chunking import build_tile_seam_contract
from .terrain_unity_export_contracts import UnityExportContract, validate_bit_depth_contract


_DETAIL_DENSITY_MAX_PER_CELL = 16
_EXPORT_COORDINATE_SYSTEM = "y-up"
_PRODUCTION_PLUS_PROFILES = frozenset({"hero_shot", "aaa_open_world"})

UNITY_SCALE_FACTOR: float = 0.85
"""Conversion factor: 1 terrain metre = 0.85 Unity units (Fix 13.3).
Camera clavicle height 1.4 terrain m = 1.19 Unity units.
Applied as the LAST step before serialization — internal computation is unchanged.
"""


def _apply_unity_scale(v: "float | list[float]") -> "float | list[float]":
    """Multiply v by UNITY_SCALE_FACTOR.  Supports scalar or list-of-float."""
    if isinstance(v, list):
        return [x * UNITY_SCALE_FACTOR for x in v]
    return float(v) * UNITY_SCALE_FACTOR


def _is_unity_heightmap_resolution(n: int) -> bool:
    """Return True when ``n`` matches Unity Terrain's 2^k + 1 contract."""
    return n >= 33 and ((n - 1) & (n - 2)) == 0


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _quantize_heightmap(stack: TerrainMaskStack) -> np.ndarray:
    """Quantize world-unit heightmap to uint16 for Unity RAW import.

    Unity's RAW heightmap importer expects:
    - 16-bit little-endian unsigned integers normalised to [0, 65535]
    - Row 0 = the *bottom* (south) edge of the terrain in world space

    The internal heightmap stores row 0 at the top (north), so we flip
    axis 0 here to match Unity's row-major convention.  Omitting the flip
    (as was the case before this fix) produces terrain that is mirrored
    north-south when imported — a cliff on the north side of the tile
    appears on the south side in Unity.

    Flat-tile handling
    ------------------
    When the height range is zero (flat tile or height_min_m == height_max_m),
    the previous code produced ``(h - lo) / 1e-9`` which overflowed to ~1e9
    and clipped to all-65535 — wrong for a flat terrain that should export as
    all-0.  We now detect this case and return an all-zero array, which matches
    the Unity convention: the manifest records the real-world height range, so
    a flat tile correctly imports as a level surface at ``height_min_m``.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    lo = float(stack.height_min_m) if stack.height_min_m is not None else float(h.min())
    hi = float(stack.height_max_m) if stack.height_max_m is not None else float(h.max())

    if hi - lo <= 1e-9:
        # Flat tile: all cells are at the minimum height → all-zero RAW.
        out = np.zeros(h.shape, dtype=np.uint16)
        if h.ndim >= 2:
            out = np.flip(out, axis=0)
        return np.ascontiguousarray(out)

    norm = np.clip((h - lo) / (hi - lo), 0.0, 1.0)
    # Unity row-convention: flip so row 0 = south (bottom of terrain).
    if norm.ndim >= 2:
        norm = np.flip(norm, axis=0)
    return np.ascontiguousarray(
        np.round(norm * 65535.0).astype(np.uint16)
    )


def _compute_terrain_normals_zup(heightmap: np.ndarray, cell_size: float) -> np.ndarray:
    """Compute a Z-up normal field from a world-unit heightmap."""
    h = np.asarray(heightmap, dtype=np.float64)
    if h.ndim != 2:
        raise ValueError("heightmap must be 2D")
    if h.size == 0:
        return np.zeros((0, 0, 3), dtype=np.float32)

    spacing = max(float(cell_size), 1e-9)
    dzdy, dzdx = np.gradient(h, spacing, spacing, edge_order=1)
    normals = np.stack((-dzdx, -dzdy, np.ones_like(h, dtype=np.float64)), axis=-1)
    lengths = np.linalg.norm(normals, axis=-1, keepdims=True)
    lengths = np.where(lengths <= 1e-9, 1.0, lengths)
    normals = normals / lengths
    return normals.astype(np.float32)


def _zup_to_unity_vectors(arr: np.ndarray) -> np.ndarray:
    """Convert a vector field from Blender Z-up into Unity Y-up."""
    arr_np = np.asarray(arr, dtype=np.float32)
    if arr_np.ndim < 1 or arr_np.shape[-1] != 3:
        raise ValueError("vector field must have a trailing dimension of 3")
    return np.ascontiguousarray(
        np.stack((arr_np[..., 0], arr_np[..., 2], arr_np[..., 1]), axis=-1),
        dtype=np.float32,
    )


def _export_heightmap(
    heightmap: np.ndarray,
    bit_depth: int = 16,
    *,
    flip_y: bool = True,
    height_min_m: Optional[float] = None,
    height_max_m: Optional[float] = None,
) -> np.ndarray:
    """Export a heightmap to a Unity-ready RAW array.

    Unity Terrain RAW format requirements
    --------------------------------------
    * **16-bit, little-endian** — Unity's RAW importer expects uint16 LE
      values normalised [0..65535] where 0 = ``height_min_m`` and 65535 =
      ``height_max_m``.  The real-world height range must be recorded in the
      manifest so Unity can invert the normalisation on import.
    * **Y-axis flip** — Unity uses a different row-major convention: row 0 is
      the *bottom* of the terrain in world space, whereas our heightmap stores
      row 0 at the *top* (north).  ``flip_y=True`` (default) inverts axis 0
      so the exported RAW byte stream matches Unity's expectation.
    * **8-bit path** — when ``bit_depth=8`` (mobile preview), the array is
      quantised to uint8 [0..255] instead.  Precision loss is intentional for
      mobile.

    Height scale factor
    -------------------
    Unity derives real-world height from::

        world_height = value_norm * (height_max_m - height_min_m) + height_min_m

    where ``value_norm = raw_value / (2^bit_depth - 1)``.  The caller must
    write ``height_min_m`` and ``height_max_m`` into the manifest JSON so
    Unity can apply the inverse transform.  UNITY_SCALE_FACTOR (0.85) is
    applied to those manifest values by ``export_unity_manifest``; this
    function works in raw terrain metres and does not apply the scale itself.

    Args:
        heightmap:    2-D float array of world-space heights in metres.
        bit_depth:    Target quantisation depth.  16 = uint16 (default,
                      production); 8 = uint8 (mobile preview).
        flip_y:       Flip row axis before export (True by default — required
                      for Unity RAW import).
        height_min_m: Minimum real-world height (metres).  Defaults to
                      ``heightmap.min()``.
        height_max_m: Maximum real-world height (metres).  Defaults to
                      ``heightmap.max()``.

    Returns:
        C-contiguous array of dtype uint16 (bit_depth=16) or uint8
        (bit_depth=8), ready for ``.tobytes()`` → RAW file write.
    """
    h = np.asarray(heightmap, dtype=np.float64)

    lo = float(h.min()) if height_min_m is None else float(height_min_m)
    hi = float(h.max()) if height_max_m is None else float(height_max_m)
    span = max(hi - lo, 1e-9)

    norm = np.clip((h - lo) / span, 0.0, 1.0)

    if flip_y and norm.ndim >= 2:
        norm = np.flip(norm, axis=0)

    if bit_depth == 8:
        quantized = np.round(norm * 255.0).astype(np.uint8)
    else:
        # 16-bit (default production path)
        quantized = np.round(norm * 65535.0).astype(np.uint16)

    return np.ascontiguousarray(quantized)


def _bit_depth_for_profile(profile: Optional[str]) -> int:
    """Return the Unity RAW heightmap bit depth for the given export profile.

    Profile table (matches Unity Terrain importer presets):

    +------------------+-------+------------------------------------------------+
    | profile          | bits  | notes                                          |
    +==================+=======+================================================+
    | mobile           |   8   | uint8 RAW; lossy but fast to load on mobile    |
    | standard         |  16   | uint16 RAW; default Unity Terrain import mode  |
    | high_fidelity    |  16   | uint16 (Unity RAW is always int; float is EXR) |
    | hero_shot        |  16   | same as high_fidelity; precision via metadata  |
    | aaa_open_world   |  16   | same as high_fidelity                          |
    | None / default   |  16   | fallback — always safe                         |
    +------------------+-------+------------------------------------------------+

    Note: Unity's own RAW importer only supports 8-bit and 16-bit.  Float
    precision for ``high_fidelity`` is achieved by recording the real-world
    ``height_min_m`` / ``height_max_m`` range in the manifest JSON so Unity
    can reconstruct sub-centimetre heights from the 16-bit normalised value,
    rather than relying on a floating-point RAW file (which Unity does not
    natively support for Terrain heightmaps).
    """
    _PROFILE_TABLE: Dict[str, int] = {
        "mobile":         8,
        "standard":      16,
        "high_fidelity": 16,
        "hero_shot":     16,
        "aaa_open_world": 16,
    }
    if profile is None:
        return 16
    return _PROFILE_TABLE.get(profile.lower(), 16)


def pass_prepare_terrain_normals(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Populate the Unity-space terrain normal field inside the pass DAG."""
    t0 = time.perf_counter()
    stack = state.mask_stack
    normals_zup = _compute_terrain_normals_zup(np.asarray(stack.height, dtype=np.float64), float(stack.cell_size))
    normals_unity = _zup_to_unity_vectors(normals_zup)
    stack.set("terrain_normals", normals_unity, "prepare_terrain_normals")

    return PassResult(
        pass_name="prepare_terrain_normals",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("terrain_normals",),
        metrics={
            "dtype": str(normals_unity.dtype),
            "shape": list(normals_unity.shape),
            "region_scoped": region is not None,
        },
    )


def pass_prepare_heightmap_raw_u16(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Populate the Unity-ready uint16 heightmap channel inside the pass DAG."""
    t0 = time.perf_counter()
    stack = state.mask_stack
    arr = _quantize_heightmap(stack)
    stack.set("heightmap_raw_u16", arr, "prepare_heightmap_raw_u16")

    return PassResult(
        pass_name="prepare_heightmap_raw_u16",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("heightmap_raw_u16",),
        metrics={
            "dtype": str(arr.dtype),
            "shape": list(arr.shape),
            "min": int(arr.min()) if arr.size else 0,
            "max": int(arr.max()) if arr.size else 0,
            "region_scoped": region is not None,
        },
    )


def register_bundle_j_terrain_normals_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="prepare_terrain_normals",
            func=pass_prepare_terrain_normals,
            requires_channels=("height",),
            produces_channels=("terrain_normals",),
            seed_namespace="prepare_terrain_normals",
            requires_scene_read=False,
            description="Bundle J: compute Unity-space terrain normals from world heightmap",
        )
    )


def register_bundle_j_heightmap_u16_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="prepare_heightmap_raw_u16",
            func=pass_prepare_heightmap_raw_u16,
            requires_channels=("height",),
            produces_channels=("heightmap_raw_u16",),
            seed_namespace="prepare_heightmap_raw_u16",
            requires_scene_read=False,
            description="Bundle J: quantize world heightmap into Unity-ready uint16 channel",
        )
    )


def _flip_for_unity(arr: np.ndarray) -> np.ndarray:
    arr_np = np.asarray(arr)
    if arr_np.ndim >= 2:
        return np.flip(arr_np, axis=0)
    return arr_np


def _ensure_little_endian(arr: np.ndarray) -> np.ndarray:
    arr_np = np.asarray(arr)
    if arr_np.dtype.itemsize <= 1:
        return np.ascontiguousarray(arr_np)
    return np.ascontiguousarray(arr_np.astype(arr_np.dtype.newbyteorder("<"), copy=False))


def _write_raw_array(
    files: Dict[str, Dict[str, Any]],
    output_dir: Path,
    *,
    filename: str,
    channel: str,
    arr: np.ndarray,
    encoding: str,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    export_arr = _ensure_little_endian(_flip_for_unity(np.asarray(arr)))
    target = output_dir / filename
    target.write_bytes(export_arr.tobytes())
    meta: Dict[str, Any] = {
        "sha256": _sha256(target),
        "size": int(target.stat().st_size),
        "dtype": str(export_arr.dtype),
        "shape": list(export_arr.shape),
        "channel": channel,
        "channels": int(export_arr.shape[2]) if export_arr.ndim >= 3 else 1,
        "bit_depth": export_arr.dtype.itemsize * 8,
        "encoding": encoding,
        "flip_vertical": bool(export_arr.ndim >= 2),
    }
    if export_arr.dtype.itemsize > 1:
        meta["endianness"] = "little"
    if extra:
        meta.update(extra)
    files[target.name] = meta
    return target.name


def _write_json(
    files: Dict[str, Dict[str, Any]],
    output_dir: Path,
    *,
    filename: str,
    payload: Dict[str, Any],
) -> str:
    target = output_dir / filename
    target.write_text(json.dumps(payload, indent=2, sort_keys=True))
    files[target.name] = {
        "sha256": _sha256(target),
        "size": int(target.stat().st_size),
        "channels": 0,
        "encoding": "json",
        "bit_depth": 0,
    }
    return target.name


def _supplemental_mesh_specs_json(stack: TerrainMaskStack) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema_version": "1.0",
        "coordinate_system": _EXPORT_COORDINATE_SYSTEM,
        "mesh_specs": [],
    }
    mesh_specs: List[Dict[str, Any]] = []
    for raw_spec in list(stack.cliff_mesh_specs or []) + list(stack.cave_mesh_specs or []):
        raw_vertices = list(raw_spec.get("vertices") or [])
        raw_faces = list(raw_spec.get("faces") or [])
        if not raw_vertices or not raw_faces:
            continue

        vertices: List[Dict[str, float]] = []
        for vec in raw_vertices:
            if not isinstance(vec, (list, tuple)) or len(vec) < 3:
                vertices = []
                break
            unity_vec = _apply_unity_scale(_zup_to_unity_vector(vec))
            vertices.append(
                {
                    "x": float(unity_vec[0]),
                    "y": float(unity_vec[1]),
                    "z": float(unity_vec[2]),
                }
            )
        if not vertices:
            continue

        faces: List[Dict[str, List[int]]] = []
        for face in raw_faces:
            if not isinstance(face, (list, tuple)) or len(face) < 3:
                continue
            faces.append({"indices": [int(idx) for idx in face]})
        if not faces:
            continue

        uvs: List[Dict[str, float]] = []
        for uv in list(raw_spec.get("uvs") or []):
            if not isinstance(uv, (list, tuple)) or len(uv) < 2:
                uvs = []
                break
            uvs.append({"x": float(uv[0]), "y": float(uv[1])})

        serialized = {
            "mesh_id": str(raw_spec.get("mesh_id", f"supplemental_mesh_{len(mesh_specs):03d}")),
            "mesh_type": str(raw_spec.get("mesh_type", "supplemental")),
            "material_hint": str(raw_spec.get("material_hint", "terrain_rock")),
            "tier": str(raw_spec.get("tier", "secondary")),
            "vertices": vertices,
            "faces": faces,
        }
        drip_edge_indices = raw_spec.get("drip_edge_indices")
        if isinstance(drip_edge_indices, (list, tuple)):
            serialized["drip_edge_indices"] = [int(idx) for idx in drip_edge_indices]
        if uvs and len(uvs) == len(vertices):
            serialized["uvs"] = uvs
        mesh_specs.append(serialized)

    payload["mesh_specs"] = mesh_specs
    return payload


def _hex_to_rgb01(hex_color: str) -> list[float]:
    color = str(hex_color).strip().lstrip("#")
    if len(color) != 6:
        return [0.5, 0.5, 0.5]
    try:
        return [
            int(color[0:2], 16) / 255.0,
            int(color[2:4], 16) / 255.0,
            int(color[4:6], 16) / 255.0,
        ]
    except ValueError:
        return [0.5, 0.5, 0.5]


def _default_splatmap_layer_meta(
    stack: TerrainMaskStack,
    layer_count: int,
) -> List[Dict[str, Any]]:
    from .terrain_materials_v2 import default_dark_fantasy_rules

    rules = list(default_dark_fantasy_rules().channels)
    layers: List[Dict[str, Any]] = []
    for layer_index in range(layer_count):
        if layer_index < len(rules):
            channel = rules[layer_index]
            layer_id = str(channel.channel_id)
            base_color_hex = str(channel.base_color_hex)
            triplanar = bool(channel.triplanar)
            roughness = float(channel.roughness)
        else:
            layer_id = f"layer_{layer_index:02d}"
            base_color_hex = "#808080"
            triplanar = False
            roughness = 0.8

        layers.append(
            {
                "layer_index": layer_index,
                "layer_id": layer_id,
                "terrain_layer_asset_path": f"Assets/Terrain/Layers/Layer_{layer_index:03d}.terrainlayer",
                "uv_scale_meters": float(max(stack.cell_size, 1.0)),
                "normal_map_intensity": 1.15 if triplanar else 0.9,
                "roughness": roughness,
                "roughness_multiplier": 1.0,
                "smoothness": float(np.clip(1.0 - roughness, 0.0, 1.0)),
                "height_blend_factor": 0.25 if triplanar else 0.1,
                "base_color_hex": base_color_hex,
                "base_color_rgb": _hex_to_rgb01(base_color_hex),
                "triplanar": triplanar,
            }
        )
    return layers


def _iter_connected_components(mask: np.ndarray) -> List[tuple[np.ndarray, np.ndarray]]:
    mask_np = np.asarray(mask, dtype=bool)
    if mask_np.ndim != 2 or not mask_np.any():
        return []

    rows, cols = mask_np.shape
    visited = np.zeros_like(mask_np, dtype=bool)
    components: List[tuple[np.ndarray, np.ndarray]] = []
    starts = np.argwhere(mask_np)

    for start_r, start_c in starts:
        sr = int(start_r)
        sc = int(start_c)
        if visited[sr, sc]:
            continue

        visited[sr, sc] = True
        frontier = [(sr, sc)]
        rr: List[int] = []
        cc: List[int] = []

        while frontier:
            r, c = frontier.pop()
            rr.append(r)
            cc.append(c)
            for nr in range(max(0, r - 1), min(rows, r + 2)):
                for nc in range(max(0, c - 1), min(cols, c + 2)):
                    if (nr == r and nc == c) or visited[nr, nc] or not mask_np[nr, nc]:
                        continue
                    visited[nr, nc] = True
                    frontier.append((nr, nc))

        components.append(
            (
                np.asarray(rr, dtype=np.int32),
                np.asarray(cc, dtype=np.int32),
            )
        )
    return components


def _component_bounds(
    stack: TerrainMaskStack,
    rr: np.ndarray,
    cc: np.ndarray,
    min_z: float,
    max_z: float,
) -> Dict[str, Any]:
    min_x = float(stack.world_origin_x + int(cc.min()) * stack.cell_size)
    max_x = float(stack.world_origin_x + (int(cc.max()) + 1) * stack.cell_size)
    min_y = float(stack.world_origin_y + int(rr.min()) * stack.cell_size)
    max_y = float(stack.world_origin_y + (int(rr.max()) + 1) * stack.cell_size)
    return _bounds_to_unity(
        [min_x, min_y, float(min_z)],
        [max_x, max_y, float(max_z)],
    )


def _component_vertical_extent(
    stack: TerrainMaskStack,
    rr: np.ndarray,
    cc: np.ndarray,
    *,
    floor_pad_m: float,
    ceil_pad_m: float,
    fallback_min_m: float,
    fallback_max_m: float,
) -> tuple[float, float]:
    """Resolve a terrain-aware vertical span for a connected component."""
    height = stack.height
    if height is None:
        return float(fallback_min_m), float(fallback_max_m)

    h = np.asarray(height, dtype=np.float64)
    if h.ndim != 2 or rr.size == 0 or cc.size == 0:
        return float(fallback_min_m), float(fallback_max_m)

    samples = h[rr, cc]
    if samples.size == 0:
        return float(fallback_min_m), float(fallback_max_m)
    return (
        float(samples.min()) - float(floor_pad_m),
        float(samples.max()) + float(ceil_pad_m),
    )


def _build_unity_import_descriptor(
    stack: TerrainMaskStack,
    manifest: Dict[str, Any],
    files: Dict[str, Dict[str, Any]],
    splatmap_layer_meta: List[Dict[str, Any]],
    splatmap_files: List[str],
    detail_files: Dict[str, str],
    tree_prototype_list: List[Dict[str, Any]],
) -> Dict[str, Any]:
    height_meta = files["heightmap.raw"]
    height_shape = list(height_meta.get("shape", []))
    height_rows = int(height_shape[0]) if len(height_shape) >= 1 else 0
    height_cols = int(height_shape[1]) if len(height_shape) >= 2 else 0

    splatmaps: List[Dict[str, Any]] = []
    for filename in splatmap_files:
        meta = files.get(filename, {})
        shape = list(meta.get("shape", []))
        layer_range = list(meta.get("layer_range", []))
        terrain_layer_assets = meta.get("terrain_layer_assets", {})
        splatmaps.append(
            {
                "file": filename,
                "width": int(shape[1]) if len(shape) >= 2 else 0,
                "height": int(shape[0]) if len(shape) >= 1 else 0,
                "channels": int(meta.get("channels", 4)),
                "bit_depth": int(meta.get("bit_depth", 8)),
                "encoding": str(meta.get("encoding", "raw_rgba_u8")),
                "flip_vertical": bool(meta.get("flip_vertical", True)),
                "layer_start": int(layer_range[0]) if len(layer_range) >= 1 else 0,
                "layer_end": int(layer_range[1]) if len(layer_range) >= 2 else -1,
                "terrain_layer_assets": [
                    str(terrain_layer_assets.get(channel, ""))
                    for channel in ("R", "G", "B", "A")
                ],
            }
        )

    detail_layers: List[Dict[str, Any]] = []
    for kind, filename in sorted(detail_files.items()):
        meta = files.get(filename, {})
        shape = list(meta.get("shape", []))
        detail_layers.append(
            {
                "kind": str(kind),
                "file": filename,
                "width": int(shape[1]) if len(shape) >= 2 else 0,
                "height": int(shape[0]) if len(shape) >= 1 else 0,
                "bit_depth": int(meta.get("bit_depth", 16)),
                "encoding": str(meta.get("encoding", "raw_u16_le_detail_count")),
                "flip_vertical": bool(meta.get("flip_vertical", True)),
                "max_density_per_cell": int(meta.get("max_density_per_cell", _DETAIL_DENSITY_MAX_PER_CELL)),
                "placeholder_texture_asset_path": f"Assets/Terrain/Details/{kind}_Detail.asset",
            }
        )

    return {
        "schema_version": "1.0",
        "world_id": str(manifest.get("world_id", "unknown")),
        "tile_x": int(manifest["tile_x"]),
        "tile_y": int(manifest["tile_y"]),
        "tile_size": int(manifest["tile_size"]),
        "cell_size": float(manifest["cell_size"]),
        "unity_world_origin": list(manifest["unity_world_origin"]),
        "terrain_size_x_m": float(int(manifest["tile_size"]) * float(manifest["cell_size"])),
        "terrain_size_z_m": float(int(manifest["tile_size"]) * float(manifest["cell_size"])),
        "height_min_m": manifest.get("height_min_m"),
        "height_max_m": manifest.get("height_max_m"),
        "heightmap": {
            "file": "heightmap.raw",
            "width": height_cols,
            "height": height_rows,
            "bit_depth": int(height_meta.get("bit_depth", 16)),
            "encoding": str(height_meta.get("encoding", "raw_u16_le")),
            "flip_vertical": bool(height_meta.get("flip_vertical", True)),
            "endianness": str(height_meta.get("endianness", "little")),
        },
        "terrain_normals_file": "terrain_normals.bin",
        "splatmaps": splatmaps,
        "terrain_layers": splatmap_layer_meta,
        "detail_layers": detail_layers,
        "tree_prototypes": tree_prototype_list,
        "tree_instances_file": "tree_instances.json",
        "audio_zones_file": "audio_zones.json",
        "gameplay_zones_file": "gameplay_zones.json",
        "wildlife_zones_file": "wildlife_zones.json",
        "decals_file": "decals.json",
        "supplemental_mesh_specs_file": (
            "supplemental_mesh_specs.json"
            if "supplemental_mesh_specs.json" in files
            else ""
        ),
        "seam_contract": manifest.get("seam_contract", {}),
        "validation_status": str(manifest.get("validation_status", "unknown")),
        "validation_issue_count": int(manifest.get("validation_issue_count", 0)),
        "game_object_name": f"VB_{manifest.get('world_id', 'world')}_{manifest['tile_x']}_{manifest['tile_y']}",
        "terrain_data_asset_path": (
            f"Assets/VeilBreakersTerrain/Imported/{manifest.get('world_id', 'world')}"
            f"/TerrainData_{manifest['tile_x']}_{manifest['tile_y']}.asset"
        ),
        "tile_metadata_asset_path": (
            f"Assets/VeilBreakersTerrain/Imported/{manifest.get('world_id', 'world')}"
            f"/TerrainTile_{manifest['tile_x']}_{manifest['tile_y']}.asset"
        ),
    }


def _zup_to_unity_vector(vec: list[float] | tuple[float, float, float]) -> list[float]:
    x, y, z = (float(vec[0]), float(vec[1]), float(vec[2]))
    return [x, z, y]


def _bounds_to_unity(bounds_min: list[float], bounds_max: list[float]) -> Dict[str, Any]:
    return {
        "min": _zup_to_unity_vector(bounds_min),
        "max": _zup_to_unity_vector(bounds_max),
    }


def _terrain_normal_at(stack: TerrainMaskStack, row: int, col: int) -> list[float]:
    h = np.asarray(stack.height, dtype=np.float64) if stack.height is not None else None
    if h is None or h.size == 0:
        return [0.0, 0.0, 1.0]

    r0 = max(0, row - 1)
    r1 = min(h.shape[0] - 1, row + 1)
    c0 = max(0, col - 1)
    c1 = min(h.shape[1] - 1, col + 1)
    dzdx = 0.0 if c1 == c0 else float(h[row, c1] - h[row, c0]) / (float(c1 - c0) * float(stack.cell_size))
    dzdy = 0.0 if r1 == r0 else float(h[r1, col] - h[r0, col]) / (float(r1 - r0) * float(stack.cell_size))
    normal = np.asarray([-dzdx, -dzdy, 1.0], dtype=np.float64)
    norm = float(np.linalg.norm(normal))
    if norm <= 1e-9:
        return [0.0, 0.0, 1.0]
    normal /= norm
    return [float(normal[0]), float(normal[1]), float(normal[2])]


def _quantize_detail_density(arr: np.ndarray) -> np.ndarray:
    density = np.asarray(arr, dtype=np.float64)
    density = np.clip(density, 0.0, 1.0)
    return np.rint(density * _DETAIL_DENSITY_MAX_PER_CELL).astype(np.uint16)


def _write_splatmap_groups(
    files: Dict[str, Dict[str, Any]],
    output_dir: Path,
    stack: TerrainMaskStack,
) -> list[str]:
    """Write splatmap groups as Unity-compliant RGBA uint8 RAW files.

    Unity TerrainData splatmap format requirements
    -----------------------------------------------
    * Unity's ``TerrainData.alphamapTextures`` is an array of RGBA Texture2D.
      Each texture encodes 4 terrain layer weights in R, G, B, A channels.
    * Channel packing: layer N*4+0 → R, N*4+1 → G, N*4+2 → B, N*4+3 → A.
    * Weights are normalised floats [0,1] quantised to uint8 [0,255].
    * Per-group weights across all 4 channels must sum to ≤ 1.0 (Unity
      does NOT automatically re-normalise splatmap reads — unnormalised
      weights cause rendering artefacts).  We enforce normalisation here.
    * Unity TerrainLayer asset format: each layer slot corresponds to one
      TerrainLayer .asset file; the manifest records ``layer_asset_path``
      as the expected relative asset path so the Unity importer can bind
      them without manual slot assignment.
    * Y-flip: applied by ``_write_raw_array`` → ``_flip_for_unity``.
    * Endianness: single-byte (uint8) — no endian tag needed.
    """
    weights = stack.splatmap_weights_layer
    if weights is None:
        return []

    weights_np = np.asarray(weights, dtype=np.float32)
    if weights_np.ndim != 3:
        raise ValueError("splatmap_weights_layer must be 3D (H, W, L)")
    if weights_np.shape[2] < 1:
        raise ValueError("splatmap_weights_layer must contain at least one layer")
    if stack.height is not None and weights_np.shape[:2] != np.asarray(stack.height).shape:
        raise ValueError(
            "splatmap_weights_layer spatial dimensions must match stack.height"
        )

    H, W, L = weights_np.shape

    # Normalise per-pixel so all active layers across the full stack sum to 1.
    # This matches Unity's expectation: SetAlphamaps requires normalised weights.
    total_weight = weights_np.sum(axis=2, keepdims=True)
    # Only normalise pixels where total > 0; leave zero pixels as zero.
    safe_total = np.where(total_weight > 1e-7, total_weight, 1.0)
    weights_norm = (weights_np / safe_total).astype(np.float32)

    group_files: list[str] = []
    group_count = max(1, (L + 3) // 4)
    for group_index in range(group_count):
        start = group_index * 4
        end = min(start + 4, L)
        block = weights_norm[:, :, start:end]

        # Pad to exactly 4 channels (RGBA) — unused channels are zero weight.
        padded = np.zeros((H, W, 4), dtype=np.float32)
        padded[:, :, : end - start] = np.clip(block, 0.0, 1.0)

        # Quantise to uint8 using round-half-up to minimise weight drift.
        block_u8 = np.rint(padded * 255.0).astype(np.uint8)

        # Unity TerrainLayer asset path hints — one per valid channel in this group.
        # Format matches Unity's TerrainLayer asset naming convention:
        #   "Assets/Terrain/Layers/Layer_NNN.terrainlayer"
        layer_asset_paths = [
            f"Assets/Terrain/Layers/Layer_{start + i:03d}.terrainlayer"
            for i in range(end - start)
        ]
        # Pad to 4 slots (empty string = unused channel / no asset).
        while len(layer_asset_paths) < 4:
            layer_asset_paths.append("")

        filename = f"splatmap_{group_index:02d}.raw"
        group_files.append(
            _write_raw_array(
                files,
                output_dir,
                filename=filename,
                channel="splatmap_weights_layer",
                arr=block_u8,
                encoding="raw_rgba_u8",
                extra={
                    "channels": 4,
                    "channel_layout": "RGBA",
                    "group_index": group_index,
                    "layer_range": [start, end - 1],
                    "valid_layer_count": end - start,
                    # Unity TerrainLayer asset binding per channel slot.
                    "terrain_layer_assets": {
                        "R": layer_asset_paths[0],
                        "G": layer_asset_paths[1],
                        "B": layer_asset_paths[2],
                        "A": layer_asset_paths[3],
                    },
                    # Normalisation applied before quantisation (required by Unity).
                    "weights_normalised": True,
                },
            )
        )
    return group_files


_MANIFEST_REQUIRED_FIELDS = (
    "height",
    "tile_x",
    "tile_y",
    "tile_size",
    "cell_size",
    "world_origin_x",
    "world_origin_y",
)


def export_unity_manifest(
    stack: TerrainMaskStack,
    output_dir: Path,
    profile: Optional[str] = None,
    *,
    strict_unity_resolution: bool = False,
) -> Dict[str, Any]:
    """Write a Unity-consumable export bundle to ``output_dir``.

    Validates required stack fields before writing any files so callers get
    a descriptive error rather than a cryptic AttributeError mid-export.
    Required: height, tile_x, tile_y, tile_size, cell_size, world_origin_x,
    world_origin_y. Missing fields raise ValueError listing all absent fields.
    """
    # --- Required field validation ---
    missing: List[str] = []
    for field_name in _MANIFEST_REQUIRED_FIELDS:
        val = getattr(stack, field_name, None)
        if val is None:
            missing.append(field_name)
    if missing:
        raise ValueError(
            f"export_unity_manifest: stack is missing required fields: {missing}. "
            "Ensure the terrain pipeline has run at least the height pass before export."
        )

    height_shape = np.asarray(stack.height, dtype=np.float64).shape
    if len(height_shape) != 2:
        raise ValueError("export_unity_manifest requires a 2D heightmap")
    if height_shape[0] != height_shape[1]:
        raise ValueError(
            "export_unity_manifest requires a square heightmap for Unity Terrain import"
        )
    unity_heightmap_resolution_valid = _is_unity_heightmap_resolution(int(height_shape[0]))
    if strict_unity_resolution and not unity_heightmap_resolution_valid:
        raise ValueError(
            "export_unity_manifest requires heightmap resolution 2^n+1 "
            f"(e.g. 33, 65, 129, 257, 513, 1025, 2049, 4097), got {height_shape[0]}"
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    hm_bit_depth = _bit_depth_for_profile(profile)
    if stack.heightmap_raw_u16 is None:
        stack.set("heightmap_raw_u16", _quantize_heightmap(stack), "prepare_heightmap_raw_u16")
    else:
        stack.set(
            "heightmap_raw_u16",
            np.asarray(stack.heightmap_raw_u16, dtype=np.uint16),
            stack.populated_by_pass.get("heightmap_raw_u16", "prepare_heightmap_raw_u16"),
        )
    normals = stack.get("terrain_normals")
    if normals is None or np.asarray(normals).shape != (*height_shape, 3):
        normals_zup = _compute_terrain_normals_zup(np.asarray(stack.height, dtype=np.float64), float(stack.cell_size))
        stack.set("terrain_normals", _zup_to_unity_vectors(normals_zup), "prepare_terrain_normals")
    else:
        stack.set(
            "terrain_normals",
            np.asarray(normals, dtype=np.float32),
            stack.populated_by_pass.get("terrain_normals", "prepare_terrain_normals"),
        )

    files: Dict[str, Dict[str, Any]] = {}
    _write_raw_array(
        files,
        output_dir,
        filename="heightmap.raw",
        channel="heightmap_raw_u16",
        arr=np.asarray(stack.heightmap_raw_u16, dtype=np.uint16),
        encoding="raw_u16_le",
    )
    _write_raw_array(
        files,
        output_dir,
        filename="terrain_normals.bin",
        channel="terrain_normals",
        arr=np.asarray(stack.terrain_normals, dtype=np.float32),
        encoding="raw_vec3_f32_le",
    )
    splatmap_files = _write_splatmap_groups(files, output_dir, stack)

    for channel in (
        # Gameplay / engine channels
        "navmesh_area_id", "wind_field", "cloud_shadow", "gameplay_zone",
        "audio_reverb_class", "traversability",
        # Terrain-derived data channels (previously dropped — CRITICAL fix)
        "slope", "curvature", "concavity", "convexity",
        "ridge", "basin", "saliency_macro",
        "erosion_amount", "deposition_amount", "wetness",
        "drainage", "bank_instability", "talus",
        "flow_direction", "flow_accumulation",
        "water_surface", "foam", "mist", "wet_rock", "tidal", "waterfall_velocity",
        "biome_id", "macro_color", "roughness_variation", "snow_line_factor",
        "strata_orientation", "rock_hardness",
        "strat_erosion_delta", "sediment_height", "bedrock_height",
        "coastline_delta", "karst_delta", "wind_erosion_delta", "glacial_delta",
        "sediment_accumulation_at_base", "pool_deepening_delta",
        "physics_collider_mask", "lightmap_uv_chart_id", "lod_bias",
        "ambient_occlusion_bake",
    ):
        value = stack.get(channel)
        if value is None:
            continue
        _write_raw_array(
            files,
            output_dir,
            filename=f"{channel}.bin",
            channel=channel,
            arr=np.asarray(value),
            encoding="raw_le",
        )

    detail_files: Dict[str, str] = {}
    if stack.detail_density:
        for key, value in stack.detail_density.items():
            detail_files[key] = _write_raw_array(
                files,
                output_dir,
                filename=f"detail_density__{key}.raw",
                channel="detail_density",
                arr=_quantize_detail_density(value),
                encoding="raw_u16_le_detail_count",
                extra={"detail_kind": key, "max_density_per_cell": _DETAIL_DENSITY_MAX_PER_CELL},
            )

    if stack.wildlife_affinity:
        for key, value in stack.wildlife_affinity.items():
            _write_raw_array(
                files,
                output_dir,
                filename=f"wildlife_affinity__{key}.bin",
                channel="wildlife_affinity",
                arr=np.asarray(value, dtype=np.float32),
                encoding="raw_f32_le",
                extra={"species": key},
            )

    if stack.decal_density and isinstance(stack.decal_density, dict):
        for key, value in stack.decal_density.items():
            _write_raw_array(
                files,
                output_dir,
                filename=f"decal_density__{key}.bin",
                channel="decal_density",
                arr=np.asarray(value, dtype=np.float32),
                encoding="raw_f32_le",
                extra={"decal_kind": key},
            )

    tree_instances_json = _tree_instances_json(stack)
    audio_zones_json = _audio_zones_json(stack)
    gameplay_zones_json = _gameplay_zones_json(stack)
    wildlife_zones_json = _wildlife_zones_json(stack)
    decals_json = _decals_json(stack)
    supplemental_mesh_specs_json = _supplemental_mesh_specs_json(stack)
    ecosystem_meta_json = {
        "schema_version": "1.0",
        "coordinate_system": _EXPORT_COORDINATE_SYSTEM,
        "source_coordinate_system": stack.coordinate_system,
        "heightmap_descriptor": "heightmap.raw",
        "terrain_normals_descriptor": "terrain_normals.bin",
        "splatmap_descriptors": splatmap_files,
        "detail_density_descriptors": detail_files,
        "tree_instances_descriptor": "tree_instances.json" if tree_instances_json["trees"] else None,
        "has_terrain_normals": stack.terrain_normals is not None,
        "has_audio_zones": stack.audio_reverb_class is not None,
        "has_wildlife_zones": bool(stack.wildlife_affinity),
        "has_gameplay_zones": stack.gameplay_zone is not None,
        "has_wind_field": stack.wind_field is not None,
        "has_cloud_shadow": stack.cloud_shadow is not None,
        "has_navmesh": stack.navmesh_area_id is not None,
        "has_traversability": stack.traversability is not None,
        "has_decals": bool(stack.decal_density),
        "has_supplemental_mesh_specs": bool(supplemental_mesh_specs_json["mesh_specs"]),
        "wind_field_descriptor": "wind_field.bin" if stack.wind_field is not None else None,
        "cloud_shadow_descriptor": "cloud_shadow.bin" if stack.cloud_shadow is not None else None,
        "supplemental_mesh_specs_descriptor": (
            "supplemental_mesh_specs.json"
            if supplemental_mesh_specs_json["mesh_specs"]
            else None
        ),
    }

    for name, payload in (
        ("tree_instances.json", tree_instances_json),
        ("audio_zones.json", audio_zones_json),
        ("gameplay_zones.json", gameplay_zones_json),
        ("wildlife_zones.json", wildlife_zones_json),
        ("decals.json", decals_json),
        ("ecosystem_meta.json", ecosystem_meta_json),
    ):
        _write_json(files, output_dir, filename=name, payload=payload)
    if supplemental_mesh_specs_json["mesh_specs"]:
        _write_json(
            files,
            output_dir,
            filename="supplemental_mesh_specs.json",
            payload=supplemental_mesh_specs_json,
        )

    # ---------------------------------------------------------------------- #
    # Tree prototype list — derived from tree_instance_points column 4.
    # Unity Terrain requires a TerrainData.treePrototypes list; each unique
    # prototype_id in the instance array maps to one entry.  We emit a
    # placeholder list so the Unity importer knows how many prototype slots to
    # reserve (actual mesh/prefab assignment happens in the Unity project).
    # ---------------------------------------------------------------------- #
    tree_prototype_list: List[Dict[str, Any]] = []
    if stack.tree_instance_points is not None:
        pts = np.asarray(stack.tree_instance_points, dtype=np.float64)
        if pts.ndim == 2 and pts.shape[1] >= 5:
            proto_ids = np.unique(pts[:, 4].astype(np.int32)).tolist()
            tree_prototype_list = [
                {
                    "prototype_id": int(pid),
                    "prefab_asset": f"Trees/Prototype_{int(pid):03d}",
                    "bend_factor": 1.0,
                    "width": _apply_unity_scale(_TREE_HEIGHT_DEFAULT * 0.5),
                    "height": _apply_unity_scale(_TREE_HEIGHT_DEFAULT),
                }
                for pid in proto_ids
            ]

    # ---------------------------------------------------------------------- #
    # Water level — derived from water_surface channel (if present).
    # Unity's water system needs a world-space Y value for the base plane.
    # We emit the 75th-percentile water surface height as the canonical level
    # so brief splash-zones don't inflate the baseline.
    # ---------------------------------------------------------------------- #
    water_level_unity: Optional[float] = None
    ws = stack.get("water_surface")
    if ws is not None:
        ws_arr = np.asarray(ws, dtype=np.float64)
        nonzero = ws_arr[ws_arr > 0.0]
        if nonzero.size > 0:
            raw_level = float(np.percentile(nonzero, 75))
            water_level_unity = _apply_unity_scale(raw_level)

    # ---------------------------------------------------------------------- #
    # Lightmap hints — baked AO + chart IDs for Unity Progressive lightmapper.
    # chart_count: number of unique UV chart IDs (0 if not assigned).
    # ao_channel_present: signals Unity to use our baked AO instead of
    #   recomputing it from geometry (avoids double-darkening in caves).
    # ---------------------------------------------------------------------- #
    lm_chart_count = 0
    lm_chart_id = stack.get("lightmap_uv_chart_id")
    if lm_chart_id is not None:
        lm_chart_count = int(np.unique(np.asarray(lm_chart_id)).size)
    lightmap_hints: Dict[str, Any] = {
        "uv_chart_count": lm_chart_count,
        "ao_channel_present": stack.get("ambient_occlusion_bake") is not None,
        "lightmap_scale": 1.0,
        "lightmap_resolution_hint": 64 if (profile or "").lower() == "mobile" else 256,
        "realtime_gi": profile not in _PRODUCTION_PLUS_PROFILES,
        "baked_gi": profile in _PRODUCTION_PLUS_PROFILES or profile in {"standard", "high_fidelity"},
    }

    # ---------------------------------------------------------------------- #
    # Splatmap layer metadata — names + per-layer roughness/normal hints used
    # by the Unity MicroSplat terrain shader to drive per-layer material params
    # without re-reading source textures at runtime.
    # ---------------------------------------------------------------------- #
    splatmap_layer_meta: List[Dict[str, Any]] = []
    weights = stack.splatmap_weights_layer
    if weights is not None:
        n_layers = int(np.asarray(weights).shape[2]) if np.asarray(weights).ndim == 3 else 1
        splatmap_layer_meta = _default_splatmap_layer_meta(stack, n_layers)

    determinism_hash = stack.compute_hash()
    world_id = str(getattr(stack, "world_id", "unknown"))
    batch_id = getattr(stack, "batch_id", None)
    terrain_base_y = (
        float(stack.height_min_m)
        if stack.height_min_m is not None
        else float(np.asarray(stack.height, dtype=np.float64).min())
    )
    manifest: Dict[str, Any] = {
        "schema_version": stack.unity_export_schema_version,
        "world_id": world_id,
        "tile_x": int(stack.tile_x),
        "tile_y": int(stack.tile_y),
        "tile_size": int(stack.tile_size),
        "cell_size": _apply_unity_scale(float(stack.cell_size)),
        "world_origin_x_m": _apply_unity_scale(float(stack.world_origin_x)),
        "world_origin_y_m": _apply_unity_scale(float(stack.world_origin_y)),
        "unity_world_origin": _apply_unity_scale(
            [float(stack.world_origin_x), terrain_base_y, float(stack.world_origin_y)]
        ),
        "height_min_m": _apply_unity_scale(float(stack.height_min_m)) if stack.height_min_m is not None else None,
        "height_max_m": _apply_unity_scale(float(stack.height_max_m)) if stack.height_max_m is not None else None,
        "height_scale_factor": UNITY_SCALE_FACTOR,
        "coordinate_system": _EXPORT_COORDINATE_SYSTEM,
        "source_coordinate_system": stack.coordinate_system,
        "generation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generator_version": "bundle_j_v2.1",
        "profile": profile or "default",
        "heightmap_bit_depth": hm_bit_depth,
        "heightmap_flip_y": True,
        "direct_unity_heightmap_import_supported": unity_heightmap_resolution_valid,
        "unity_heightmap_resolution_warning": (
            None
            if unity_heightmap_resolution_valid
            else (
                "heightmap resolution is not 2^n+1; import through the generated Unity "
                "bridge or resample before direct TerrainData RAW import"
            )
        ),
        "splatmap_group_count": len(splatmap_files),
        "splatmap_layer_count": len(splatmap_layer_meta),
        "splatmap_layers": splatmap_layer_meta,
        "detail_density_max_per_cell": _DETAIL_DENSITY_MAX_PER_CELL,
        "tree_prototype_list": tree_prototype_list,
        "water_level_unity_units": water_level_unity,
        "lightmap_hints": lightmap_hints,
        "files": files,
        "populated_channels": list(stack.populated_by_pass.keys()),
        "determinism_hash": determinism_hash,
        "terrain_layer_assets_required": [
            {
                "layer_index": int(layer["layer_index"]),
                "layer_id": str(layer["layer_id"]),
                "asset_path": str(layer["terrain_layer_asset_path"]),
            }
            for layer in splatmap_layer_meta
        ],
        "seam_contract": build_tile_seam_contract(
            np.asarray(stack.height, dtype=np.float64),
            tile_x=int(stack.tile_x),
            tile_y=int(stack.tile_y),
            cell_size=float(stack.cell_size),
            world_origin_x=float(stack.world_origin_x),
            world_origin_y=float(stack.world_origin_y),
            world_id=world_id,
            batch_id=str(batch_id) if batch_id is not None else None,
        ),
    }
    validation_issues = validate_bit_depth_contract(UnityExportContract(), files)
    manifest["validation_issue_count"] = len(validation_issues)
    manifest["validation_issues"] = [
        {
            "code": issue.code,
            "severity": issue.severity,
            "affected_feature": issue.affected_feature,
            "message": issue.message,
            "remediation": issue.remediation,
        }
        for issue in validation_issues
    ]
    manifest["validation_status"] = (
        "failed" if any(issue.is_hard() for issue in validation_issues) else "passed"
    )
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    import_descriptor = _build_unity_import_descriptor(
        stack,
        manifest,
        files,
        splatmap_layer_meta,
        splatmap_files,
        detail_files,
        tree_prototype_list,
    )
    _write_json(
        files,
        output_dir,
        filename="unity_import_descriptor.json",
        payload=import_descriptor,
    )
    manifest["files"] = files
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def _audio_zones_json(stack: TerrainMaskStack) -> Dict[str, Any]:
    zones: List[Dict[str, Any]] = []
    arr = stack.audio_reverb_class
    if arr is None:
        return {"schema_version": "1.0", "coordinate_system": _EXPORT_COORDINATE_SYSTEM, "zones": zones}

    arr_np = np.asarray(arr)
    class_params = {
        0: ("open_field", 0.15, 0.2, 0.4),
        1: ("forest_dense", 0.45, 0.3, 0.7),
        2: ("forest_sparse", 0.3, 0.25, 0.55),
        3: ("cave_tight", 0.8, 0.6, 1.2),
        4: ("canyon_long", 0.7, 0.55, 1.6),
        5: ("water_near", 0.35, 0.3, 0.5),
        6: ("mountain_high", 0.2, 0.15, 0.45),
        7: ("interior", 0.5, 0.4, 0.9),
    }
    world_tile_extent = stack.tile_size * stack.cell_size
    for val in np.unique(arr_np).tolist():
        name, wet, er, tail = class_params.get(int(val), ("unknown", 0.2, 0.2, 0.5))
        mask = arr_np == val
        if not mask.any():
            continue
        for rr, cc in _iter_connected_components(mask):
            min_z, max_z = _component_vertical_extent(
                stack,
                rr,
                cc,
                floor_pad_m=1.0,
                ceil_pad_m=8.0,
                fallback_min_m=0.0,
                fallback_max_m=float(world_tile_extent),
            )
            zones.append(
                {
                    "bounds": _component_bounds(stack, rr, cc, min_z, max_z),
                    "reverb_class": name,
                    "wet_mix": wet,
                    "early_reflections": er,
                    "tail_length": tail,
                    "cell_count": int(rr.size),
                }
            )
    return {"schema_version": "1.0", "coordinate_system": _EXPORT_COORDINATE_SYSTEM, "zones": zones}


def _gameplay_zones_json(stack: TerrainMaskStack) -> Dict[str, Any]:
    zones: List[Dict[str, Any]] = []
    arr = stack.gameplay_zone
    if arr is None:
        return {"schema_version": "1.0", "coordinate_system": _EXPORT_COORDINATE_SYSTEM, "zones": zones}

    kind_names = {
        0: ("safe", "low_slope_basin"),
        1: ("combat", "open_terrain"),
        2: ("stealth", "dense_cover"),
        3: ("exploration", "default_open"),
        4: ("boss_arena", "authored"),
        5: ("narrative", "hero_feature_footprint"),
        6: ("puzzle", "cave_candidate"),
    }
    arr_np = np.asarray(arr)
    for val in np.unique(arr_np).tolist():
        name, reason = kind_names.get(int(val), ("unknown", "unclassified"))
        mask = arr_np == val
        if not mask.any():
            continue
        for rr, cc in _iter_connected_components(mask):
            min_z, max_z = _component_vertical_extent(
                stack,
                rr,
                cc,
                floor_pad_m=0.5,
                ceil_pad_m=6.0,
                fallback_min_m=0.0,
                fallback_max_m=100.0,
            )
            zones.append(
                {
                    "bounds": _component_bounds(stack, rr, cc, min_z, max_z),
                    "kind": name,
                    "reason": reason,
                    "suggestion_tags": [],
                    "cell_count": int(rr.size),
                }
            )
    return {"schema_version": "1.0", "coordinate_system": _EXPORT_COORDINATE_SYSTEM, "zones": zones}


def _wildlife_zones_json(stack: TerrainMaskStack) -> Dict[str, Any]:
    volumes: List[Dict[str, Any]] = []
    if not stack.wildlife_affinity:
        return {"schema_version": "1.0", "coordinate_system": _EXPORT_COORDINATE_SYSTEM, "volumes": volumes}

    for species, arr in stack.wildlife_affinity.items():
        values = np.asarray(arr, dtype=np.float32)
        mask = values > 0.1
        if not mask.any():
            continue
        for rr, cc in _iter_connected_components(mask):
            component_values = values[rr, cc]
            min_z, max_z = _component_vertical_extent(
                stack,
                rr,
                cc,
                floor_pad_m=0.5,
                ceil_pad_m=10.0,
                fallback_min_m=0.0,
                fallback_max_m=50.0,
            )
            volumes.append(
                {
                    "bounds": _component_bounds(stack, rr, cc, min_z, max_z),
                    "species": species,
                    "density": float(component_values.mean()) if component_values.size else 0.0,
                    "cell_count": int(rr.size),
                    "spawn_rules": {},
                }
            )
    return {"schema_version": "1.0", "coordinate_system": _EXPORT_COORDINATE_SYSTEM, "volumes": volumes}


def _decals_json(stack: TerrainMaskStack) -> Dict[str, Any]:
    decals: Dict[str, List[Dict[str, Any]]] = {}
    if not stack.decal_density or not isinstance(stack.decal_density, dict):
        return {"schema_version": "1.0", "coordinate_system": _EXPORT_COORDINATE_SYSTEM, "decals": decals}

    for kind, arr in stack.decal_density.items():
        arr_np = np.asarray(arr, dtype=np.float32)
        coords = np.argwhere(arr_np > 0.5)
        if coords.size:
            order = np.argsort(arr_np[coords[:, 0], coords[:, 1]])[::-1]
            coords = coords[order]
        placements: List[Dict[str, Any]] = []
        truncated_count = max(0, int(coords.shape[0]) - 512)
        for r, c in coords[:512]:
            strength = float(arr_np[r, c])
            jitter_hash = ((int(r) * 73856093) ^ (int(c) * 19349663)) & 0xFFFFFFFF
            rotation = float((jitter_hash % 36000) / 100.0)
            scale = float(np.clip(0.8 + strength * 0.6, 0.8, 1.4))
            position_zup = [
                _apply_unity_scale(float(stack.world_origin_x + c * stack.cell_size)),
                _apply_unity_scale(float(stack.world_origin_y + r * stack.cell_size)),
                _apply_unity_scale(float(stack.height[r, c]) if stack.height is not None else 0.0),
            ]
            placements.append(
                {
                    "position": _zup_to_unity_vector(position_zup),
                    "normal": _zup_to_unity_vector(_terrain_normal_at(stack, int(r), int(c))),
                    "scale": scale,
                    "rotation": rotation,
                    "strength": strength,
                }
            )
        decals[kind] = {
            "placements": placements,
            "truncated_count": truncated_count,
        }
    return {"schema_version": "1.0", "coordinate_system": _EXPORT_COORDINATE_SYSTEM, "decals": decals}


_WIND_DIR_DEFAULT = (1.0, 0.0)  # +X fallback per CONTEXT.md Claude's Discretion
_TREE_HEIGHT_DEFAULT = 10.0     # metres; used when height not in instance data


# ---------------------------------------------------------------------------
# Wind bend vertex color — Fix 13.2
# ---------------------------------------------------------------------------

def compute_wind_bend_vertex_color(
    vertex_heights: np.ndarray,
    tree_height: float,
    wind_dir_xz: "tuple[float, float]" = (1.0, 0.0),
    vertex_normals_xz: "np.ndarray | None" = None,
) -> np.ndarray:
    """Bake per-vertex wind bend color for tree mesh export (Fix 13.2).

    Layout (per CONTEXT.md decision D-02):
        R = XZ bend magnitude  (horizontal sway, quadratic height falloff)
        G = Y sway magnitude   (0.1 * R, small vertical component)
        B = 0.0                (reserved for future LOD or flex data)
        A = 1.0

    Formula:
        wind_bend_xz = abs(dot(vertex_normal_xz, wind_dir)) * (h / tree_height)^2
        wind_bend_y  = 0.1 * wind_bend_xz

    Args:
        vertex_heights: 1-D float array, tree-local height of each vertex (metres,
            0 = root, tree_height = crown tip).
        tree_height: Total tree height in metres. Must be > 0.
        wind_dir_xz: Normalised world-space XZ wind direction.  Defaults to +X.
            If (0,0) (no wind), all bend values are 0.
        vertex_normals_xz: (N, 2) float array of per-vertex XZ normals.
            If None, every vertex is treated as facing +X (1, 0).

    Returns:
        np.ndarray of shape (N, 4), dtype float32, values in [0, 1] for R/G/B;
        A channel is always 1.0.
    """
    heights = np.asarray(vertex_heights, dtype=np.float64).ravel()
    n = heights.shape[0]
    th = max(float(tree_height), 1e-9)

    # Height ratio with quadratic falloff — roots don't sway
    height_ratio = np.clip(heights / th, 0.0, 1.0) ** 2

    # Per-vertex dot product with wind direction
    wd = np.asarray(wind_dir_xz, dtype=np.float64)
    wd_norm = float(np.linalg.norm(wd))
    if wd_norm < 1e-9:
        # No wind — all zeros
        rgba = np.zeros((n, 4), dtype=np.float32)
        rgba[:, 3] = 1.0
        return rgba

    wd = wd / wd_norm
    if vertex_normals_xz is not None:
        nxz = np.asarray(vertex_normals_xz, dtype=np.float64).reshape(n, 2)
    else:
        nxz = np.tile([1.0, 0.0], (n, 1))

    dot = np.abs(nxz[:, 0] * wd[0] + nxz[:, 1] * wd[1])

    wind_bend_xz = np.clip(dot * height_ratio, 0.0, 1.0).astype(np.float32)
    wind_bend_y  = np.clip(0.1 * wind_bend_xz, 0.0, 1.0).astype(np.float32)

    rgba = np.zeros((n, 4), dtype=np.float32)
    rgba[:, 0] = wind_bend_xz   # R = XZ bend
    rgba[:, 1] = wind_bend_y    # G = Y sway
    # rgba[:, 2] = 0.0           # B reserved
    rgba[:, 3] = 1.0            # A always 1
    return rgba


def _tree_instances_json(stack: TerrainMaskStack) -> Dict[str, Any]:
    trees: List[Dict[str, Any]] = []
    arr = stack.tree_instance_points
    if arr is None:
        return {
            "schema_version": "1.0",
            "coordinate_system": _EXPORT_COORDINATE_SYSTEM,
            "trees": trees,
            "skipped_out_of_bounds": 0,
        }

    points = np.asarray(arr, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] < 5:
        return {
            "schema_version": "1.0",
            "coordinate_system": _EXPORT_COORDINATE_SYSTEM,
            "trees": trees,
            "skipped_out_of_bounds": 0,
        }

    tile_min_x = float(stack.world_origin_x)
    tile_min_y = float(stack.world_origin_y)
    tile_max_x = tile_min_x + float(stack.tile_size) * float(stack.cell_size)
    tile_max_y = tile_min_y + float(stack.tile_size) * float(stack.cell_size)
    skipped_out_of_bounds = 0

    for row in points:
        if not (tile_min_x <= float(row[0]) <= tile_max_x and tile_min_y <= float(row[1]) <= tile_max_y):
            skipped_out_of_bounds += 1
            continue
        # Wind bend vertex color — Fix 13.2 / REQ-P13-002
        # Two representative heights: root (0.0) and crown (tree_height)
        _representative_heights = np.array([0.0, _TREE_HEIGHT_DEFAULT], dtype=np.float32)
        _vcolors = compute_wind_bend_vertex_color(
            vertex_heights=_representative_heights,
            tree_height=_TREE_HEIGHT_DEFAULT,
            wind_dir_xz=_WIND_DIR_DEFAULT,
        )
        # Serialize as list of RGBA dicts (root + crown)
        vertex_color_list = [
            {"r": float(_vcolors[i, 0]), "g": float(_vcolors[i, 1]),
             "b": float(_vcolors[i, 2]), "a": float(_vcolors[i, 3])}
            for i in range(len(_vcolors))
        ]
        trees.append(
            {
                "position": _zup_to_unity_vector([
                    _apply_unity_scale(float(row[0])),
                    _apply_unity_scale(float(row[1])),
                    _apply_unity_scale(float(row[2])),
                ]),
                "yaw_degrees": float(row[3]),
                "prototype_id": int(row[4]),
                "width_scale": 1.0,
                "height_scale": 1.0,
                "color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0},
                "lightmap_color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0},
                "vertex_color": vertex_color_list,  # NEW — Fix 13.2
            }
        )
    return {
        "schema_version": "1.0",
        "coordinate_system": _EXPORT_COORDINATE_SYSTEM,
        "trees": trees,
        "skipped_out_of_bounds": skipped_out_of_bounds,
    }


__all__ = [
    "pass_prepare_heightmap_raw_u16",
    "register_bundle_j_heightmap_u16_pass",
    "export_unity_manifest",
    "_export_heightmap",
    "_bit_depth_for_profile",
    "compute_wind_bend_vertex_color",
    "UNITY_SCALE_FACTOR",
    "_apply_unity_scale",
]

"""Bundle K — terrain_shadow_clipmap_bake.

Bakes a per-cell sun-shadow mask by ray-marching the heightmap along the
sun direction. Produces a float32 (clipmap_res, clipmap_res) mask in [0, 1]
(1 = fully lit, 0 = in shadow). Populates ``cloud_shadow`` channel when
sun occlusion is used as a multiplier on top of cloud shadows (both fold
into the shader AO path in Unity).

Shadow is baked at 4 cascaded clipmap levels (LOD0=fine → LOD3=coarse)
and composited into a single output, matching the cascaded shadow map
approach used in UE5 and Unity HDRP terrain shaders.

Pure numpy ray march — not production-fast, but deterministic and
dependency-free. For production bakes use a Houdini/Bake shader.
"""

from __future__ import annotations

import json
import struct
import time
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)

# ---------------------------------------------------------------------------
# Cascade configuration
# ---------------------------------------------------------------------------

# 4 cascade levels: (resolution_divisor, step_count)
# LOD0 is the finest (full res, most steps); LOD3 is the coarsest.
# Resolution is clipmap_res // divisor; steps halve each cascade.
_CASCADE_CONFIGS: List[Tuple[int, int]] = [
    (1, 32),   # LOD0: full res, 32 steps — fine detail, close range
    (2, 16),   # LOD1: half  res, 16 steps
    (4,  8),   # LOD2: quarter res, 8 steps
    (8,  4),   # LOD3: eighth res,  4 steps — coarse, far range
]


def _resample_height(h: np.ndarray, target: int) -> np.ndarray:
    """Bilinear resample a heightmap to (target, target)."""
    rows, cols = h.shape
    if rows == target and cols == target:
        return h.astype(np.float64)
    ys = np.linspace(0.0, rows - 1.0, target)
    xs = np.linspace(0.0, cols - 1.0, target)
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    y1 = np.clip(y0 + 1, 0, rows - 1)
    x1 = np.clip(x0 + 1, 0, cols - 1)
    ty = (ys - y0).reshape(-1, 1)
    tx = (xs - x0).reshape(1, -1)
    a = h[np.ix_(y0, x0)]
    b = h[np.ix_(y0, x1)]
    c = h[np.ix_(y1, x0)]
    d = h[np.ix_(y1, x1)]
    top = a * (1 - tx) + b * tx
    bot = c * (1 - tx) + d * tx
    return (top * (1 - ty) + bot * ty).astype(np.float64)


def _bake_single_cascade(
    h: np.ndarray,
    az: float,
    el: float,
    cell_m: float,
    num_steps: int,
) -> np.ndarray:
    """Vectorised horizon-scan shadow test for a single cascade level.

    Parameters
    ----------
    h : (R, C) float64 heightmap already resampled to cascade resolution.
    az : sun azimuth in radians.
    el : sun elevation in radians (> 0).
    cell_m : world-space metres per cell at this cascade's resolution.
    num_steps : ray-march steps for this cascade.

    Returns
    -------
    (R, C) float32 shadow mask: 1.0 = lit, 0.0 = shadowed.
    """
    rows, cols = h.shape

    sun_dx = float(np.cos(az))
    sun_dy = float(np.sin(az))
    tan_el = float(np.tan(el))

    # Step size: spread steps evenly across the diagonal so step width ≤ 1 cell
    max_reach = float(np.sqrt(rows * rows + cols * cols))
    step_cells = min(1.0, max_reach / max(num_steps, 1))

    rr, cc = np.mgrid[0:rows, 0:cols].astype(np.float64)
    running_max_h = np.full((rows, cols), -np.inf, dtype=np.float64)
    shadowed = np.zeros((rows, cols), dtype=bool)

    for step in range(1, num_steps + 1):
        dist_cells = step * step_cells
        dist_m = dist_cells * cell_m

        # Walk toward the sun from each receiver cell
        sx = cc + sun_dx * dist_cells
        sy = rr + sun_dy * dist_cells

        in_bounds = (sx >= 0) & (sx < cols - 1) & (sy >= 0) & (sy < rows - 1)
        sxi = np.clip(sx.astype(np.int32), 0, cols - 1)
        syi = np.clip(sy.astype(np.int32), 0, rows - 1)

        sampled_h = h[syi, sxi]
        np.maximum(running_max_h,
                   np.where(in_bounds, sampled_h, running_max_h),
                   out=running_max_h)

        # Horizon-angle occlusion test:
        #   receiver is in shadow if any terrain sample along the ray
        #   rises above the sun-ray height at that distance.
        ray_height = h + dist_m * tan_el
        shadowed |= in_bounds & (running_max_h > ray_height)

    return np.where(shadowed, 0.0, 1.0).astype(np.float32)


def bake_shadow_clipmap(
    stack: TerrainMaskStack,
    sun_dir_rad: Tuple[float, float],
    clipmap_res: int = 512,
    num_steps: int = 24,
) -> np.ndarray:
    """Ray-march sun shadows with 4-cascade clipmap levels.

    Parameters
    ----------
    sun_dir_rad : (azimuth_rad, elevation_rad)
        Azimuth measured from world +X toward +Y (CCW). Elevation is angle
        above horizon in radians; <= 0 means entire map is in shadow.
    clipmap_res : int
        Base output resolution (LOD0). Must be > 0.
    num_steps : int
        Ray-march steps for LOD0. Each subsequent cascade halves the step
        count (see ``_CASCADE_CONFIGS``). The ``num_steps`` parameter is
        used as the LOD0 budget; the cascade table scales from it.

    Algorithm
    ---------
    4 cascades are baked independently at decreasing resolutions:
      LOD0 (clipmap_res × clipmap_res)    — captures fine near-field shadows
      LOD1 (clipmap_res/2 × clipmap_res/2)
      LOD2 (clipmap_res/4 × clipmap_res/4)
      LOD3 (clipmap_res/8 × clipmap_res/8) — captures coarse far-field shadows

    Each cascade is upsampled back to clipmap_res and blended using a
    min() composite (any cascade that says "shadowed" wins), so coarse
    cascades fill in large-scale shadow that the fine cascade's shorter
    reach misses, while the fine cascade preserves sharp local shadow edges.

    Returns
    -------
    np.ndarray
        (clipmap_res, clipmap_res) float32 in [0, 1].
        1.0 = fully lit, 0.0 = fully in hard shadow.
    """
    if stack.height is None:
        raise ValueError("bake_shadow_clipmap requires stack.height")
    if clipmap_res <= 0:
        raise ValueError(f"clipmap_res must be > 0, got {clipmap_res}")

    az, el = float(sun_dir_rad[0]), float(sun_dir_rad[1])
    if el <= 0.0:
        return np.zeros((clipmap_res, clipmap_res), dtype=np.float32)

    # World-space cell size at LOD0 resolution
    tile_extent_m = float(stack.tile_size) * float(stack.cell_size)
    base_cell_m = tile_extent_m / max(clipmap_res, 1)

    # Base heightmap at LOD0 resolution
    h_base = _resample_height(np.asarray(stack.height, dtype=np.float64), clipmap_res)

    # Accumulate cascade results: start with fully-lit, then take min() with
    # each cascade's shadow mask so any shadowed cascade darkens the result.
    composite = np.ones((clipmap_res, clipmap_res), dtype=np.float32)

    for lod_idx, (res_div, cascade_steps) in enumerate(_CASCADE_CONFIGS):
        # Cascade resolution and cell size
        cascade_res = max(4, clipmap_res // res_div)
        cascade_cell_m = base_cell_m * res_div  # coarser cascades have larger cells

        # Resample height to cascade resolution
        if cascade_res == clipmap_res:
            h_cascade = h_base
        else:
            h_cascade = _resample_height(h_base, cascade_res)

        # Scale num_steps: LOD0 uses the caller's budget; coarser cascades use
        # the fixed cascade table step counts (independent of num_steps).
        steps = cascade_steps if lod_idx > 0 else max(cascade_steps, num_steps)

        shadow_lod = _bake_single_cascade(h_cascade, az, el, cascade_cell_m, steps)

        # Upsample back to clipmap_res if needed
        if cascade_res != clipmap_res:
            shadow_lod = _resample_height(
                shadow_lod.astype(np.float64), clipmap_res
            ).astype(np.float32)

        # min() composite: shadowed in any cascade → shadowed in output
        np.minimum(composite, shadow_lod, out=composite)

    return composite


# ---------------------------------------------------------------------------
# Mini-EXR writer (struct-packed, no OpenEXR dependency)
# ---------------------------------------------------------------------------

def _write_mini_exr_f32(path: Path, arr: np.ndarray) -> None:
    """Write a single-channel float32 EXR file using struct-packed binary.

    Implements a minimal subset of the ILM OpenEXR specification sufficient
    to produce a valid single-channel scanline EXR that Unity, Houdini, and
    standard EXR readers (Nuke, Blender, ffmpeg) can open.

    Format
    ------
    - Magic: 0x76 2F 31 01  (OpenEXR magic number)
    - Version: 2, flags 0
    - Header attributes: compression=NO_COMPRESSION, dataWindow, displayWindow,
      lineOrder=INCREASING_Y, pixelAspectRatio, screenWindowCenter,
      screenWindowWidth, channels (single Y channel, FLOAT 32-bit)
    - Offset table: one 8-byte entry per scanline
    - Scanline blocks: (y_coord int32, data_size int32, scanline_data bytes)

    The pixel data is written as-is (native endian float32) — EXR spec
    specifies little-endian, and x86/ARM are both LE so no swap is needed
    on any supported platform.

    Raises
    ------
    ValueError
        If ``arr`` is not a 2-D float32 array.
    """
    if arr.ndim != 2:
        raise ValueError(f"_write_mini_exr_f32: expected 2D array, got shape {arr.shape}")
    rows, cols = arr.shape
    arr_f32 = np.ascontiguousarray(arr, dtype=np.float32)

    def _write_str(s: str) -> bytes:
        b = s.encode("ascii") + b"\x00"
        return b

    def _write_attr(name: str, atype: str, data: bytes) -> bytes:
        return _write_str(name) + _write_str(atype) + struct.pack("<i", len(data)) + data

    # --- channel list: single channel "Y", FLOAT (2=float32), xSampling=1, ySampling=1 ---
    # Channel type: 0=UINT, 1=HALF, 2=FLOAT
    channel_entry = b"Y\x00" + struct.pack("<i", 2) + struct.pack("<B", 0) + b"\x00\x00\x00" + struct.pack("<ii", 1, 1)
    chlist_data = channel_entry + b"\x00"  # null sentinel terminates channel list

    # dataWindow / displayWindow: Box2i = (xMin, yMin, xMax, yMax)
    box2i = struct.pack("<iiii", 0, 0, cols - 1, rows - 1)

    # compression: 0 = NO_COMPRESSION
    compression_data = struct.pack("<B", 0)

    # lineOrder: 0 = INCREASING_Y
    lineorder_data = struct.pack("<B", 0)

    # pixelAspectRatio: float32 1.0
    par_data = struct.pack("<f", 1.0)

    # screenWindowCenter: V2f (0.0, 0.0)
    swc_data = struct.pack("<ff", 0.0, 0.0)

    # screenWindowWidth: float32 1.0
    sww_data = struct.pack("<f", 1.0)

    header = b""
    header += _write_attr("channels",           "chlist",      chlist_data)
    header += _write_attr("compression",        "compression", compression_data)
    header += _write_attr("dataWindow",         "box2i",       box2i)
    header += _write_attr("displayWindow",      "box2i",       box2i)
    header += _write_attr("lineOrder",          "lineOrder",   lineorder_data)
    header += _write_attr("pixelAspectRatio",   "float",       par_data)
    header += _write_attr("screenWindowCenter", "v2f",         swc_data)
    header += _write_attr("screenWindowWidth",  "float",       sww_data)
    header += b"\x00"  # end of header sentinel

    # Magic + version field
    magic = struct.pack("<I", 0x01312F76)  # OpenEXR magic (little-endian)
    version = struct.pack("<I", 2)         # version 2, no flags

    # Offset table: one uint64 per scanline pointing to its file offset
    # Offset = magic(4) + version(4) + header(len) + offset_table(8*rows)
    header_offset = 4 + 4 + len(header)
    offset_table_size = 8 * rows
    # Each scanline block: int32 y + int32 data_size + cols*4 bytes of pixel data
    scanline_block_size = 4 + 4 + cols * 4

    offsets = []
    scanline_data_start = header_offset + offset_table_size
    for y in range(rows):
        offsets.append(scanline_data_start + y * scanline_block_size)
    offset_table = struct.pack(f"<{rows}Q", *offsets)

    # Scanline pixel data
    scanlines = b""
    for y in range(rows):
        row_bytes = arr_f32[y].tobytes()
        scanlines += struct.pack("<i", y) + struct.pack("<i", len(row_bytes)) + row_bytes

    path.write_bytes(magic + version + header + offset_table + scanlines)


def export_shadow_clipmap_exr(mask: np.ndarray, output_path: Path) -> None:
    """Write a shadow clipmap to disk as a proper EXR file.

    Primary path: struct-packed mini-EXR (float32, single Y channel).
    No external dependencies required — the EXR is assembled from first
    principles using the OpenEXR binary format specification.

    Fallback chain (if the primary EXR write fails, which should not happen
    under normal conditions):
      1. imageio EXR half-float
      2. OpenEXR + Imath package
      3. 16-bit PNG via imageio
      4. float32 .npy with honest labelling

    A JSON sidecar is always written alongside the output recording the
    schema, format used, shape, dtype, and value range.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    arr_f16 = np.ascontiguousarray(mask, dtype=np.float16)
    arr_f32 = np.ascontiguousarray(mask, dtype=np.float32)
    rows, cols = arr_f32.shape
    written_format: str = "unknown"
    actual_path = output_path

    # --- Primary: struct-packed mini-EXR (float32) ----------------------
    _exr_ok = False
    if output_path.suffix.lower() == ".exr":
        try:
            _write_mini_exr_f32(output_path, arr_f32)
            written_format = "exr_float32_mini"
            _exr_ok = True
        except Exception:
            pass

    # --- Fallback 1: imageio EXR (half-float) ---------------------------
    if not _exr_ok and output_path.suffix.lower() == ".exr":
        try:
            import imageio  # type: ignore[import]
            imageio.imwrite(str(output_path), arr_f16)
            written_format = "exr_float16_imageio"
            _exr_ok = True
        except Exception:
            pass

    # --- Fallback 2: OpenEXR + Imath -----------------------------------
    if not _exr_ok and output_path.suffix.lower() == ".exr":
        try:
            import OpenEXR  # type: ignore[import]
            import Imath  # type: ignore[import]
            header = OpenEXR.Header(cols, rows)
            header["channels"] = {"Y": Imath.Channel(Imath.PixelType(Imath.PixelType.HALF))}
            exr_file = OpenEXR.OutputFile(str(output_path), header)
            exr_file.writePixels({"Y": arr_f16.tobytes()})
            exr_file.close()
            written_format = "exr_float16_openexr"
            _exr_ok = True
        except Exception:
            pass

    # --- Fallback 3: 16-bit PNG via imageio ----------------------------
    if not _exr_ok:
        png_path = output_path.with_suffix(".png")
        try:
            import imageio  # type: ignore[import]
            arr_u16 = (np.clip(arr_f32, 0.0, 1.0) * 65535.0).astype(np.uint16)
            imageio.imwrite(str(png_path), arr_u16)
            actual_path = png_path
            written_format = "png_uint16_imageio"
            _exr_ok = True
        except Exception:
            pass

    # --- Fallback 4: float32 .npy with honest labelling ----------------
    if not _exr_ok:
        npy_path = output_path.with_suffix(".npy")
        np.save(str(npy_path), arr_f32)
        actual_path = npy_path
        written_format = "float32_npy"

    sidecar = actual_path.with_suffix(".json")
    sidecar.write_text(
        json.dumps(
            {
                "schema": "veilbreakers.terrain.shadow_clipmap/v1",
                "format": written_format,
                "path": str(actual_path),
                "shape": list(arr_f32.shape),
                "dtype": "float16" if "float16" in written_format else "float32",
                "value_min": float(arr_f32.min()),
                "value_max": float(arr_f32.max()),
                "lit_fraction": float((arr_f32 > 0.5).mean()),
                "cascade_levels": len(_CASCADE_CONFIGS),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def pass_shadow_clipmap(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle K pass: bake 4-cascade sun shadow clipmap and export EXR.

    Sun direction is read from ``intent.composition_hints`` under the keys
    ``sun_azimuth_rad`` and ``sun_elevation_rad``.  Defaults are a
    mid-afternoon angle (az=0.6 rad ≈ 34°, el=0.85 rad ≈ 49°) that gives
    visible shadow contrast without being at zenith.

    Workflow
    --------
    1. Call ``bake_shadow_clipmap`` (4 cascades: LOD0=fine, LOD3=coarse).
    2. Resample result back to heightmap resolution.
    3. Store in stack channels ``shadow_map`` and ``cloud_shadow``.
    4. Export EXR to ``shadow_clipmap_export_path`` if set in hints
       (uses ``export_shadow_clipmap_exr`` with mini-EXR writer).

    Consumes: height
    Produces: shadow_map  — (H, W) float32 [0,1] stored on the stack.
              cloud_shadow — multiplied with existing cloud_shadow if present.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    hints = state.intent.composition_hints if state.intent else {}

    sun_az = float(hints.get("sun_azimuth_rad", 0.6))
    sun_el = float(hints.get("sun_elevation_rad", 0.85))

    h_arr = np.asarray(stack.height)
    rows, cols = h_arr.shape
    clipmap_res = int(hints.get("shadow_clipmap_res", max(32, rows)))
    num_steps = int(hints.get("shadow_clipmap_steps", 24))

    # Step 1: Bake 4-cascade shadow map
    shadow_map = bake_shadow_clipmap(
        stack,
        sun_dir_rad=(sun_az, sun_el),
        clipmap_res=clipmap_res,
        num_steps=num_steps,
    )

    # Step 2: Resample back to heightmap resolution
    if shadow_map.shape != (rows, cols):
        resampled = _resample_height(shadow_map.astype(np.float64), max(rows, cols))
        resampled = resampled[:rows, :cols].astype(np.float32)
    else:
        resampled = shadow_map.astype(np.float32)

    # Step 3: Store stack channels
    stack.set("shadow_map", resampled, "shadow_clipmap")

    existing_cloud = stack.get("cloud_shadow")
    if existing_cloud is not None:
        combined = (np.asarray(existing_cloud, dtype=np.float32) * resampled).astype(np.float32)
    else:
        combined = resampled.copy()
    stack.set("cloud_shadow", combined, "shadow_clipmap")

    # Step 4: Export EXR if a path is provided in hints
    export_path_str = hints.get("shadow_clipmap_export_path", "")
    exported_path: Optional[str] = None
    if export_path_str:
        export_path = Path(str(export_path_str))
        export_shadow_clipmap_exr(shadow_map, export_path)
        exported_path = str(export_path)

    produced = ("shadow_map", "cloud_shadow")

    metrics: dict = {
        "sun_azimuth_rad": sun_az,
        "sun_elevation_rad": sun_el,
        "clipmap_res": int(clipmap_res),
        "num_steps": num_steps,
        "cascade_levels": len(_CASCADE_CONFIGS),
        "lit_fraction": float((resampled > 0.5).mean()),
        "shadow_min": float(resampled.min()),
        "shadow_max": float(resampled.max()),
    }
    if exported_path:
        metrics["exported_exr"] = exported_path

    return PassResult(
        pass_name="shadow_clipmap",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=produced,
        metrics=metrics,
        issues=[],
    )


def register_bundle_k_shadow_clipmap_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="shadow_clipmap",
            func=pass_shadow_clipmap,
            requires_channels=("height",),
            produces_channels=("shadow_map", "cloud_shadow"),
            seed_namespace="shadow_clipmap",
            requires_scene_read=False,
            description="Bundle K: vectorised horizon-scan sun shadow clipmap bake",
        )
    )


__all__ = [
    "bake_shadow_clipmap",
    "export_shadow_clipmap_exr",
    "pass_shadow_clipmap",
    "register_bundle_k_shadow_clipmap_pass",
]
